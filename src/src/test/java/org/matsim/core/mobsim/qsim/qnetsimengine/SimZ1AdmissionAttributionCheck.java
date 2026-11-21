package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Native component reproduction of the live-run empty-connector rejection.
 * Admission observations must distinguish native queue refusal from a later
 * whole-body refusal. No capacities, speed, reservations or clocks are bypassed.
 */
public final class SimZ1AdmissionAttributionCheck {
    private static void strict(SimZ1StorageFixture f) {
        var cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(f.scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
        cfg.setStoragePolicy(gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.STRICT);
        cfg.setWholeVehicleReservation(true);
    }
    private static void emit(String name,Map<String,String> row) throws Exception {
        System.out.println("ATTRIBUTION_JSON "+new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(Map.of("case",name,"attributes",row)));
    }
    private static Map<String,String> decision(SimZ1StorageFixture f,String vehicle) {
        return f.events.stream().filter(e->e.getEventType().equals("simz1NativeDecision")&&
            vehicle.equals(e.getAttributes().get("vehicle"))&&"WAIT".equals(e.getAttributes().get("decision")))
            .reduce((a,b)->b).orElseThrow().getAttributes();
    }
    private static void ledgerOnly() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),false)) {
            strict(f);
            var actor=f.through("ledger-request",4.5,"avenue","receipt-a");
            f.seed(actor,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);
            var blocker=f.actor("receipt-blocker",4.5,"receipt-a","dest-a");
            f.seed(blocker,".original",101);
            var nativeReceiver=f.queue("short0",".original");
            require(nativeReceiver.isAcceptingFromUpstream()&&nativeReceiver.getLoadIndicator()==0,"Fixture requires empty native connector");
            require(!f.query(actor,"short0",102).feasible(),"Receipt must be physically occupied");
            var original=f.reservation(actor);int before=f.moves;
            require(!f.cross(actor,115),"Body rejection allowed an impossible movement beyond stuckTime");
            var row=decision(f,"ledger-request");emit("ledger-only",row);
            require("false".equals(row.get("receiverAcceptedAtDecision")),"Combined admission must remain rejected");
            require("combined_admission_result".equals(row.get("receiverAcceptanceSemantics")),"Unqualified receiver refusal confuses body and native admission");
            require("true".equals(row.get("nativeReceiverAcceptedAtDecision")),"Lost actual native permission");
            require("false".equals(row.get("bodyReservationAcceptedAtDecision")),"Lost actual body refusal");
            require("whole_vehicle_reservation".equals(row.get("rejectionStage")),"Missing body rejection stage");
            require("storage_wait".equals(row.get("reason")),"Changed established storage counter contract");
            require("0.0".equals(row.get("receivingLoadIndicator")),"Empty native connector no longer observed faithfully");
            require(f.moves==before&&f.reservation(actor)==original,"Observation moved a vehicle or changed its body");
            require(((Map<?,?>)field(f.ledger,"pending")).isEmpty(),"Rejected body left admission pending");
            f.safety();
        }
    }
    private static void nativeFull(boolean bodyEnabled) throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(3),false)) {
            strict(f);
            var actor=f.through("native-request",2.1,"avenue","receipt-a");
            f.seed(actor,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);
            var blocker=f.actor("native-blocker",4.5,"short0","short1","short2","receipt-a","dest-a");
            f.seed(blocker,".original",101);
            var receiver=f.queue("short0",".original");
            require(!receiver.isAcceptingFromUpstream()&&receiver.getLoadIndicator()>=receiver.getStorageCapacity(),"Native queue must really be full");
            require(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(f.scenario.getConfig().qsim(),actor.vehicle,id("short0"),"short0.original"),"Both-rejection fixture requires occupied body entry too");
            if(!bodyEnabled)for(var node:f.nodes.values())set(node,"wholeVehicleReservation",false);
            var original=f.reservation(actor);int before=f.moves;
            require(!f.cross(actor,115),"Full native receiver allowed a movement beyond stuckTime");
            var row=decision(f,"native-request");emit(bodyEnabled?"both-reject":"native-only",row);
            require("false".equals(row.get("receiverAcceptedAtDecision")),"Lost actual native rejection");
            require("false".equals(row.get("nativeReceiverAcceptedAtDecision")),"Lost actual native refusal attribution");
            require("native_receiver".equals(row.get("rejectionStage")),"Native refusal has wrong stage");
            require("storage_wait".equals(row.get("reason")),"Native refusal reclassified as body refusal");
            require(!row.containsKey("bodyReservationAcceptedAtDecision"),"Short-circuited body query must remain unobserved");
            require("non_atomic_read_only".equals(row.get("snapshotConsistency")),"Snapshot falsely advertised as atomic");
            require(f.moves==before&&f.reservation(actor)==original,"Native rejection moved a vehicle or changed its body");
            f.safety();
        }
    }
    private static void accepted() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),false)) {
            strict(f);
            var actor=f.through("accepted-request",4.5,"avenue","receipt-a");
            f.seed(actor,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);
            require(f.cross(actor,101)&&f.moves==1,"Joint permission failed to move through native queues");
            require(f.events.stream().anyMatch(e->e.getEventType().equals("simz1Admission")&&"accepted-request".equals(e.getAttributes().get("vehicle"))),"Missing committed admission event");
            require(f.events.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"accepted-request".equals(e.getAttributes().get("vehicle"))&&"WAIT".equals(e.getAttributes().get("decision"))),"Successful movement reported as refused");
            f.safety();System.out.println("accepted native moves="+f.moves);
        }
    }
    public static void main(String[] args) throws Exception {
        try {
            String which=args.length==0?"all":args[0];
            if(which.equals("all")||which.equals("ledger"))ledgerOnly();
            if(which.equals("all")||which.equals("native"))nativeFull(false);
            if(which.equals("all")||which.equals("both"))nativeFull(true);
            if(which.equals("all")||which.equals("accepted"))accepted();
            System.out.println("PASS SimZ1AdmissionAttributionCheck "+which);
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
