package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Native component witness for an original-to-terminal storage dependency.
 * Metric lengths and body/PCU mix come from the saved 734011350_23 observation;
 * this is not a replay of its unavailable route cursors or exact queue state.
 */
public final class SimZ1InternalSplitBackpressureCheck {
    private static final Profile METRIC=new Profile("734011350_22-23 observed metric",
        new double[]{6.202513045612158,63.56138773467124},1,66.26355697915965);
    private static Map<String,Object> snapshot(SimZ1StorageFixture f,String stage) throws Exception {
        var out=new LinkedHashMap<String,Object>();out.put("stage",stage);out.put("moves",f.moves);
        out.put("time_step",f.scenario.getConfig().qsim().getTimeStepSize());
        out.put("native_fast_capacity_update",f.scenario.getConfig().qsim().isUsingFastCapacityUpdate());
        for(String suffix:List.of(".original",".lane.0")) {
            var q=f.queue("short1",suffix);var values=new LinkedHashMap<String,Object>();
            values.put("used_pcu_excluding_buffer",q.getLoadIndicator());values.put("capacity_pcu",q.getStorageCapacity());
            values.put("offering",!q.isNotOfferingVehicle());values.put("native_accepting",q.isAcceptingFromUpstream());
            values.put("head",q.getFirstVehicle()==null?null:q.getFirstVehicle().getId().toString());
            values.put("buffer",((Iterable<?>)field(q,"buffer")).toString());values.put("travelling",((Iterable<?>)field(q,"vehQueue")).toString());
            out.put(suffix,values);
        }
        return out;
    }
    private static void run() throws Exception {
        // The standard component step avoids MATSim's automatic per-step
        // storage enlargement on the 6.2m entrance. Its native fast accumulator
        // preserves rate/debt across sparse component calls. Neither the step
        // nor the update mode claims to reproduce the historical run's clock.
        try(var f=new SimZ1StorageFixture(METRIC,false,false,.1,false)) {
            var settings=org.matsim.core.config.ConfigUtils.addOrGetModule(f.scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
            settings.setStoragePolicy(gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.STRICT);settings.setWholeVehicleReservation(true);
            // Occupied downstream entry is established by real native insertion.
            var downstream=f.actor("downstream-body",4.5,"receipt-a","dest-a");f.seed(downstream,".original",0);
            double[] bodies={2.1,4.5,4.5,12,2.1,4.5,4.5,2.1,2.1,2.1,4.5};
            var actors=new ArrayList<SimZ1StorageFixture.Actor>();double now=10;
            for(int i=0;i<bodies.length;i++) {
                var actor=f.actor("terminal-"+i,bodies[i],"short0","short1","receipt-a","dest-a");
                if(bodies[i]==12)actor.vehicle.getVehicle().getType().setPcuEquivalents(2.5).setWidth(2.5);
                actors.add(actor);f.seed(actor,".original",now);
                f.ready(f.queue("short0",".original"),now+2);f.split("short0",now+3);
                f.ready(f.queue("short0",".lane.0"),now+5);
                require(f.cross(actor,now+6),"Metric corridor entry unexpectedly blocked at actor "+i);
                f.ready(f.queue("short1",".original"),now+10);f.split("short1",now+11);
                require(f.queue("short1",".lane.0").getVehicle(actor.vehicle.getId())==actor.vehicle,"Seed actor failed native internal split "+i);
                f.ready(f.queue("short1",".lane.0"),now+25);now+=40;
                if(!f.queue("short1",".lane.0").isAcceptingFromUpstream())break;
            }
            var terminal=f.queue("short1",".lane.0");
            require(!terminal.isAcceptingFromUpstream()&&terminal.getLoadIndicator()>=terminal.getStorageCapacity(),"Actual terminal PCU is not full");
            var waiting=f.actor("original-head",4.5,"short0","short1","receipt-a","dest-a");
            f.seed(waiting,".original",now);f.ready(f.queue("short0",".original"),now+2);f.split("short0",now+3);
            f.ready(f.queue("short0",".lane.0"),now+5);require(f.cross(waiting,now+6),"Original insertion unexpectedly blocked");
            var reservation=f.reservation(waiting);var ordinal=field(reservation,"ordinal");
            f.ready(f.queue("short1",".original"),now+10);
            require(!f.queue("short1",".original").isNotOfferingVehicle()&&f.queue("short1",".original").getFirstVehicle()==waiting.vehicle,"Original head must actually be offered; travel/flow debt is not the rejection under test");
            require(!terminal.isAcceptingFromUpstream(),"Terminal must reject at this exact split attempt");
            int before=f.moves;f.split("short1",now+11);
            require(f.queue("short1",".original").getVehicle(waiting.vehicle.getId())==waiting.vehicle,"Full terminal let original cross");
            require(f.moves==before&&f.reservation(waiting)==reservation,"Rejected split moved/replaced a reserved body");
            var evidence=new ArrayList<Map<String,Object>>();evidence.add(snapshot(f,"full_terminal_rejects_original"));
            require(!f.cross(actors.get(0),now+12),"Occupied downstream entry allowed native movement");
            f.safety();
            // Clear the blocker by ordinary native travel and a real node move.
            now+=40;f.ready(f.queue("receipt-a",".original"),now);f.split("receipt-a",now+1);
            f.ready(f.queue("receipt-a",".lane.0"),now+10);require(f.cross(downstream,now+11),"Available downstream exit failed to clear");
            int movedHeads=0;
            for(int i=0;i<8&&f.queue("short1",".original").getVehicle(waiting.vehicle.getId())!=null;i++) {
                now+=40;f.ready(terminal,now);
                var first=terminal.getFirstVehicle();
                if(!terminal.isNotOfferingVehicle()&&first!=null) {
                    var actor=f.actors.get(first.getId());
                    if(f.cross(actor,now+1))movedHeads++;
                }
                f.ready(f.queue("receipt-a",".original"),now+4);f.split("receipt-a",now+5);
                f.ready(f.queue("receipt-a",".lane.0"),now+15);
                f.ready(f.queue("short1",".original"),now+20);f.split("short1",now+21);
            }
            require(movedHeads>0,"No real terminal head movement freed storage");
            require(f.queue("short1",".original").getVehicle(waiting.vehicle.getId())==null&&terminal.getVehicle(waiting.vehicle.getId())==waiting.vehicle,"Native capacity release did not discharge the internal split");
            require(field(f.reservation(waiting),"ordinal").equals(ordinal),"Internal split replaced FIFO reservation identity");
            near((double)field(f.reservation(waiting),"footprint"),4.6,"Internal split lost body/gap");
            evidence.add(snapshot(f,"native_head_moves_then_original_advances"));f.safety();
            System.out.println("SPLIT_EVIDENCE_JSON "+new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(evidence));
            System.out.println("PASS SimZ1InternalSplitBackpressureCheck: full terminal retains original; real downstream moves restore split; FIFO/body/PCU preserved");
        }
    }
    public static void main(String[] args) throws Exception {
        try {run();} finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
