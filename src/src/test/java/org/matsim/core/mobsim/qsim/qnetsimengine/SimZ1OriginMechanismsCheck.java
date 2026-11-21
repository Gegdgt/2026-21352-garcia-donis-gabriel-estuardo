package org.matsim.core.mobsim.qsim.qnetsimengine;

import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OriginAdmissionFixture.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.lanes.Lane;

/** Paired component experiment. Historical baseline/candidate overlay modes
 * remain available; legacy/physical-gap select the integrated versioned policy.
 * No massive events, Controller, QSim, launcher, demand regeneration or GUI.
 */
public final class SimZ1OriginMechanismsCheck {
    static final List<Map<String,Object>> rows=new ArrayList<>();
    static final List<Map<String,Object>> attempts=new ArrayList<>();
    static boolean candidate;
    static boolean overlay;
    static boolean integratedPolicy;
    static SimZ1StorageFixture storageFixture(){return integratedPolicy?new SimZ1StorageFixture(SimZ1StorageFixture.PROFILES.get(0),true,false,SimZ1StorageFixture.STEP,false,candidate?SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN:SimZ1AdmissionConfigGroup.LEGACY_ORIGIN):new SimZ1StorageFixture(SimZ1StorageFixture.PROFILES.get(0),true);}
    static String selectedStoragePolicy(){return integratedPolicy?(candidate?SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN:SimZ1AdmissionConfigGroup.LEGACY_ORIGIN):"historical-default-or-overlay";}
    static void row(String name,Map<String,Object> values){var r=new LinkedHashMap<String,Object>();r.put("case",name);r.put("status","PASS");r.putAll(values);rows.add(r);System.out.println("PASS "+name+" "+values);}
    static Object offer(SimZ1CorridorOccupancy ledger,QVehicle v,String link,double now)throws Exception{
        return call(ledger,overlay?"candidateOriginOffer":"originOffer",new Class<?>[]{QVehicle.class,Id.class,String.class,double.class},v,id(link),link+".original",now);
    }
    static Object value(Object offer,String key)throws Exception{var method=offer.getClass().getDeclaredMethod(key);method.setAccessible(true);return method.invoke(offer);}
    static boolean feasible(Object offer)throws Exception{return (boolean)value(offer,"feasible");}
    static boolean attempt(NativeOrigin f,String origin,double now)throws Exception{
        check(attempts.size()<64,"Bounded fixture trace exceeded");
        var trace=new LinkedHashMap<String,Object>();var head=f.link(origin).getWaitingList().peek();
        trace.put("time",now);trace.put("origin",origin);trace.put("head_vehicle",head==null?null:head.getId().toString());
        trace.put("waiting_before",f.link(origin).getWaitingList().size());
        trace.put("first_outer_head_trace_for_fixture_actor",head!=null&&attempts.stream().noneMatch(a->head.getId().toString().equals(a.get("head_vehicle"))));
        if(candidate&&head!=null){var proposed=offer(f.ledger,head,origin,now);var details=new LinkedHashMap<String,Object>();for(String key:List.of("applicable","feasible","slot","insertionFront","reason"))details.put(key,value(proposed,key));trace.put("geometric_offer",details);}
        trace.put("native_flow_credit_before",field(field(f.queue(origin,".original"),"flowcap_accumulate"),"value"));
        long entries=f.entries();trace.put("entries_before",entries);
        boolean moved=f.admit(origin,now);
        trace.put("native_flow_credit_after",field(field(f.queue(origin,".original"),"flowcap_accumulate"),"value"));
        trace.put("entries_after",f.entries());trace.put("waiting_after",f.link(origin).getWaitingList().size());trace.put("moved",moved);
        trace.put("head_reserved_after",head!=null&&f.reservation(head)!=null);
        trace.put("attempt_scope","Direct invocation of native moveWaitToRoad; inner-loop heads may already have been attempted, so this is not a census of each actor's first attempt");attempts.add(trace);return moved;
    }
    static String state(NativeOrigin f)throws Exception{
        var state=new LinkedHashMap<String,String>();
        for(String key:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks","nextOrdinal","passageRequestTime","passageRequests","passageDeadlines","waits","waitReasons"))
            state.put(key,deep(field(f.ledger,key),new IdentityHashMap<>()));
        state.put("clock",Double.toString(f.timer.getTimeOfDay()));state.put("events",Integer.toString(f.events.size()));
        return state.toString();
    }
    static void pureOffer(NativeOrigin f,QVehicle v,String origin,boolean expected,double now)throws Exception{
        if(!candidate)return;
        var before=state(f);for(int i=0;i<3;i++)check(feasible(offer(f.ledger,v,origin,now))==expected,"Wrong geometric offer");
        check(before.equals(state(f)),"Geometric offer changed reservations, queue-independent timers or events");
    }
    static void noCommit(NativeOrigin f,QVehicle v,long entries)throws Exception{
        check(f.reservation(v)==null&&f.entries()==entries,"Rejected commit created reservation or TrafficEntry");
        check(!((Map<?,?>)field(f.ledger,"pending")).containsKey(v.getId()),"Rejected commit left pending slot");
        check(!((Map<?,?>)field(f.ledger,"pendingPassages")).containsKey(v.getId()),"Rejected commit left pending passage");
    }
    static QVehicleImpl motor(NativeOrigin f,String name,String... path){var v=f.actor(name,2.1,path);v.getVehicle().getType().setWidth(.8);return v;}
    static void pairHolders(NativeOrigin f)throws Exception{
        var a=f.seedHolder("paired-holder-0",0);var b=f.seedHolder("paired-holder-1",1);f.readyHolder(a,0);f.readyHolder(b,1);
    }
    static void pairedGap(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            pairHolders(f);var a=motor(f,"new-a",ORIGIN,TAIL,OUT);var b=motor(f,"new-b",ORIGIN,TAIL,OUT);var c=motor(f,"new-c",ORIGIN,TAIL,OUT);
            var originalRoute=((Leg)((PlanAgent)a.getDriver()).getCurrentPlanElement()).getRoute();
            pureOffer(f,a,ORIGIN,true,101);f.waitFor(a,ORIGIN);f.waitFor(b,ORIGIN);f.waitFor(c,ORIGIN);
            check(attempt(f,ORIGIN,101)==candidate,"Paired baseline/candidate origin outcome changed");
            if(candidate){
                check(f.entries()==2&&f.slot(a)!=f.slot(b)&&f.link(ORIGIN).getWaitingList().peek()==c,"Compatible slots/FIFO not preserved");
                near(f.front(a),BUFFER,"Candidate moved native anchor");near(f.front(b),BUFFER,"Candidate moved second native anchor");
                noCommit(f,c,2);check(((Leg)((PlanAgent)a.getDriver()).getCurrentPlanElement()).getRoute()==originalRoute,"Origin admission rerouted actor");
                long enter=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyReservation")&&"ENTER".equals(e.getAttributes().get("action"))&&a.getId().toString().equals(e.getAttributes().get("vehicle"))).count();
                check(enter==1,"Double body reservation");
                check(!(boolean)call(f.ledger,overlay?"candidateActivityFromWait":"activityFromWait",new Class<?>[]{QVehicle.class,Id.class,String.class,double.class},a,id(ORIGIN),ORIGIN+".original",101.),"Double native-origin commit accepted existing vehicle");
                check(!attempt(f,ORIGIN,101)&&f.entries()==2,"Retry fabricated TrafficEntry");
            }else{check(f.entries()==0&&f.link(ORIGIN).getWaitingList().size()==3,"Baseline did not reproduce blocked origin");noCommit(f,a,0);}
            f.safety();row("native-gap-with-downstream-traffic",Map.of("entries",f.entries(),"waiting",f.link(ORIGIN).getWaitingList().size(),"insertion_front_m",BUFFER,"native_anchor_unchanged",true,"route_empty_required",false,"candidate_expected",candidate));
        }
    }
    static void alternativeSlot(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var upstream=motor(f,"upstream-slot0",PRE,ORIGIN,TAIL,OUT);f.seed(upstream,PRE,".lane.0",0);
            var downstream=f.seedHolder("downstream-slot1",1);f.ready(PRE,".lane.0",100);f.readyHolder(downstream,1);
            var a=motor(f,"alternative-lane",ORIGIN,TAIL,OUT);pureOffer(f,a,ORIGIN,true,101);
            if(candidate)check((int)value(offer(f.ledger,a,ORIGIN,101),"slot")==1,"Candidate chose blocked first slot");
            f.waitFor(a,ORIGIN);check(attempt(f,ORIGIN,101)==candidate,"Alternate accessible nonempty slot outcome");
            if(candidate)check(f.slot(a)==1,"Committed different slot from rechecked available lane");else noCommit(f,a,0);
            f.safety();row("enumerate-compatible-accessible-slots",Map.of("entries",f.entries(),"blocked_slot",0,"accessible_slot",1));
        }
    }
    static void fullBodies(Scenario s)throws Exception{
        for(double body:new double[]{2.1,4.5,8,13.5})try(var f=new NativeOrigin(s)){
            pairHolders(f);var v=f.actor("body-control-"+body,body,ORIGIN,TAIL,OUT);v.getVehicle().getType().setWidth(body<3?.8:body<5?1.8:2.5);
            pureOffer(f,v,ORIGIN,true,101);f.waitFor(v,ORIGIN);check(attempt(f,ORIGIN,101)==candidate,"Full-body admission changed for "+body);
            if(candidate){near(f.front(v),BUFFER,"Changed full-body anchor");near((double)field(f.reservation(v),"footprint"),body+.1,"Lost complete body footprint");}
            else noCommit(f,v,0);f.safety();
        }
        row("complete-body-dimensions",Map.of("body_lengths_m",List.of(2.1,4.5,8,13.5),"additional_gap_m",.1,"scope","Synthetic body controls, not a scheduled transit-service test","new_entries_each",candidate?1:0));
    }
    static void upstreamAndOverlap(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var a=motor(f,"earlier-upstream0",PRE,ORIGIN,TAIL,OUT);var b=motor(f,"earlier-upstream1",PRE,ORIGIN,TAIL,OUT);
            f.seed(a,PRE,".lane.0",0);f.seed(b,PRE,".lane.1",0);f.ready(PRE,".lane.0",100);f.ready(PRE,".lane.1",100);
            var entrant=motor(f,"upstream-overtake",ORIGIN,TAIL,OUT);pureOffer(f,entrant,ORIGIN,false,101);f.waitFor(entrant,ORIGIN);
            check(!attempt(f,ORIGIN,101),"Interior insertion overtook older upstream body");noCommit(f,entrant,0);f.safety();
        }
        try(var f=new NativeOrigin(s)){
            var a=motor(f,"anchor0",ORIGIN,TAIL,OUT);var b=motor(f,"anchor1",ORIGIN,TAIL,OUT);f.waitFor(a,ORIGIN);f.waitFor(b,ORIGIN);
            check(attempt(f,ORIGIN,0)&&f.entries()==2,"Positive empty-slot control");
            var entrant=motor(f,"anchor-overlap",ORIGIN,TAIL,OUT);pureOffer(f,entrant,ORIGIN,false,0);f.waitFor(entrant,ORIGIN);
            check(!attempt(f,ORIGIN,0),"Inserted overlapping body at native anchor");noCommit(f,entrant,2);f.safety();
        }
        row("upstream-and-overlap-negative-controls",Map.of("overtake_rejected",true,"same_anchor_overlap_rejected",true,"minimum_gap_m",.1));
    }
    static void nativeFlowAndGlobalFifo(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var busSized=f.actor("native-credit-consumer",8,ORIGIN,TAIL,OUT);busSized.getVehicle().getType().setPcuEquivalents(3.5).setWidth(2.3);
            f.waitFor(busSized,ORIGIN);check(attempt(f,ORIGIN,0),"Native initial credit unavailable");
            var next=motor(f,"native-credit-waiter",ORIGIN,TAIL,OUT);pureOffer(f,next,ORIGIN,true,0);f.waitFor(next,ORIGIN);var before=state(f);
            check(!attempt(f,ORIGIN,0),"Geometric offer bypassed exhausted native credit");noCommit(f,next,1);
            check(before.equals(state(f)),"Flow short circuit reached ledger/body mutation");
        }
        try(var f=new NativeOrigin(s)){
            var head=f.actor("unreceivable-origin-head",1000,ORIGIN,TAIL,OUT);head.getVehicle().getType().setWidth(2.5);
            var next=motor(f,"receivable-origin-follower",ORIGIN,TAIL,OUT);pureOffer(f,next,ORIGIN,true,0);f.waitFor(head,ORIGIN);f.waitFor(next,ORIGIN);
            check(!attempt(f,ORIGIN,0)&&f.link(ORIGIN).getWaitingList().peek()==head,"Global waiting FIFO bypassed");noCommit(f,head,0);noCommit(f,next,0);
        }
        row("native-flow-and-global-wait-fifo",Map.of("flow_source_unchanged",true,"debit_source_unchanged",true,"rejected_without_new_entry",true,"follower_bypass",false));
    }
    static void routeLaneModeWidth(Scenario s)throws Exception{
        if(!candidate)return;
        var assignment=s.getLanes().getLanesToLinkAssignments().get(id(TAIL));var lane0=assignment.getLanes().get(Id.create(TAIL+".lane.0",Lane.class));var lane1=assignment.getLanes().get(Id.create(TAIL+".lane.1",Lane.class));
        var prior0=new ArrayList<>(lane0.getToLinkIds());var prior1=new ArrayList<>(lane1.getToLinkIds());
        try{
            lane0.getToLinkIds().remove(id(OUT));
            try(var f=new NativeOrigin(s)){
                var v=motor(f,"restricted-slot0",ORIGIN,TAIL,OUT);pureOffer(f,v,ORIGIN,true,0);
                check((int)value(offer(f.ledger,v,ORIGIN,0),"slot")==1,"Turn permission ignored when first slot was free");
                f.waitFor(v,ORIGIN);check(attempt(f,ORIGIN,0)&&f.slot(v)==1,"Committed forbidden terminal lane");f.safety();
            }
            lane1.getToLinkIds().remove(id(OUT));
            try(var f=new NativeOrigin(s)){
                var v=motor(f,"no-turn-slot",ORIGIN,TAIL,OUT);pureOffer(f,v,ORIGIN,false,0);f.waitFor(v,ORIGIN);check(!attempt(f,ORIGIN,0),"No permitted terminal slot admitted");noCommit(f,v,0);
            }
        }finally{lane0.getToLinkIds().clear();lane0.getToLinkIds().addAll(prior0);lane1.getToLinkIds().clear();lane1.getToLinkIds().addAll(prior1);}
        for(String kind:List.of("direction","width","mode"))try(var f=new NativeOrigin(s)){
            var v=kind.equals("direction")?motor(f,"wrong-direction",ORIGIN,PRE):motor(f,"wrong-"+kind,ORIGIN,TAIL,OUT);
            var link=s.getNetwork().getLinks().get(id(ORIGIN));var modes=new HashSet<>(link.getAllowedModes());
            try{
                if(kind.equals("width"))v.getVehicle().getType().setWidth(3.01);
                if(kind.equals("mode"))link.setAllowedModes(Set.of("bus"));
                pureOffer(f,v,ORIGIN,false,0);f.waitFor(v,ORIGIN);check(!attempt(f,ORIGIN,0),"Origin ignored "+kind);noCommit(f,v,0);
            }finally{link.setAllowedModes(modes);}
        }
        row("physical-slot-permissions",Map.of("restricted_turns",true,"directed_route",true,"allowed_mode",true,"nominal_width_limit_m",3.,"nominal_not_observed_width",true,"scenario_changes","In-memory negative controls restored"));
    }
    static void staleAndMutation(Scenario s)throws Exception{
        if(!candidate)return;
        try(var f=new NativeOrigin(s)){
            var v=motor(f,"stale-gap",ORIGIN,TAIL,OUT);pureOffer(f,v,ORIGIN,true,0);
            var a=motor(f,"later-blocker0",PRE,ORIGIN,TAIL,OUT);var b=motor(f,"later-blocker1",PRE,ORIGIN,TAIL,OUT);
            f.seed(a,PRE,".lane.0",0);f.seed(b,PRE,".lane.1",0);f.waitFor(v,ORIGIN);
            check(!attempt(f,ORIGIN,1),"A previous pure offer was treated as a durable grant");noCommit(f,v,0);f.safety();
        }
        for(String mutation:List.of("width","route"))try(var f=new NativeOrigin(s)){
            var v=motor(f,"mutation-"+mutation,ORIGIN,TAIL,OUT);pureOffer(f,v,ORIGIN,true,0);
            if(mutation.equals("width"))v.getVehicle().getType().setWidth(3.01);
            else ((Leg)((PlanAgent)v.getDriver()).getCurrentPlanElement()).setRoute(RouteUtils.createNetworkRoute(List.of(id(ORIGIN),id(PRE)),s.getNetwork()));
            f.waitFor(v,ORIGIN);check(!attempt(f,ORIGIN,0),"Commit trusted stale "+mutation);noCommit(f,v,0);
        }
        try(var f=new NativeOrigin(s)){
            var v=motor(f,"stale-passage-request",ORIGIN,TAIL,OUT);
            // Explicit negative-state injection, not a claimed native history:
            // an obsolete request must not survive a changed route at commit.
            var cls=Class.forName(SimZ1CorridorOccupancy.class.getName()+"$PassageRequest");
            var constructor=cls.getDeclaredConstructor(List.class,String.class,double.class);constructor.setAccessible(true);
            @SuppressWarnings("unchecked") var requests=(Map<Object,Object>)field(f.ledger,"passageRequests");
            @SuppressWarnings("unchecked") var times=(Map<Object,Object>)field(f.ledger,"passageRequestTime");
            requests.put(v.getId(),constructor.newInstance(List.of(id(ORIGIN),id(PRE)),"",0.));times.put(v.getId(),0.);
            pureOffer(f,v,ORIGIN,true,0);f.waitFor(v,ORIGIN);check(attempt(f,ORIGIN,0),"Valid replacement route did not commit");
            check(!requests.containsKey(v.getId())&&!times.containsKey(v.getId()),"Commit retained obsolete passage request/stop credit");f.safety();
        }
        row("pure-offer-stale-and-mutation",Map.of("queries_repeated",3,"ledger_query_mutation",false,"stale_slot_rejected",true,"mutated_route_rejected",true,"mutated_width_rejected",true,"offer_is_permission",false,"obsolete_passage_request_cleared",true,"stale_request_control","Explicit injected negative state"));
    }
    static void nativePassageLock()throws Exception{
        try(var f=storageFixture()){
            var owner=f.through("real-passage-owner",4.5,"avenue","receipt-a");f.seed(owner,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);
            check(f.cross(owner,101),"Native passage control did not acquire its receipt");
            var activity=f.actor("receipt-activity",2.1,"receipt-a","dest-a");
            if(candidate){var offer=offer(f.ledger,activity.vehicle,"receipt-a",101);check(!feasible(offer),"Geometric offer ignored a native acquired passage lock");}
            var receiving=(QLinkLanesImpl)f.links.get(id("receipt-a"));receiving.getWaitingList().add(activity.vehicle);
            check(!(boolean)call(receiving,"moveWaitToRoad",new Class<?>[]{double.class},101.),"Native origin activity stole a reserved receipt");
            check(f.reservation(activity)==null&&f.reservation(owner)!=null,"Rejected origin altered passage owner");f.safety();
            row("native-passage-reservation-control",Map.of("passage_acquired_by_native_node",true,"receipt_activity_rejected",true,"owner_retained",true,"origin_policy",selectedStoragePolicy()));
        }
    }
    static void legacyMetricCaller(){
        var events=SimZ1CorridorOccupancyCheck.ledgerFixture();
        check(!events.isEmpty(),"Legacy metric control did not execute");
        row("legacy-metric-null-driver-callers",Map.of("unchanged_component_fixture",true,"legacy_transactions",events.size()));
    }
    static void nativeStorageBoundary()throws Exception{
        // Both receiving trucks are inserted through unchanged native storage
        // acceptance. The second can consume the native one-vehicle overshoot.
        // This controlled state investigates the producer's distinction between
        // travelling-queue PCU and an activity inserted directly into its buffer.
        try(var f=storageFixture()){
            var a=f.actor("storage-truck0",8,"receipt-a","dest-a");var b=f.actor("storage-truck1",8,"receipt-a","dest-a");
            f.seed(a,".original",0);f.seed(b,".original",0);
            var q=f.queue("receipt-a",".original");double capacity=q.getStorageCapacity(),used=q.getLoadIndicator();
            check(!q.isAcceptingFromUpstream()&&used>=capacity,"Native storage control was not saturated");
            var entrant=f.actor("storage-activity",2.1,"receipt-a","dest-a");
            if(candidate)check(feasible(offer(f.ledger,entrant.vehicle,"receipt-a",0)),"Third distinct slot should have a geometric body interval");
            var link=(QLinkLanesImpl)f.links.get(id("receipt-a"));link.getWaitingList().add(entrant.vehicle);
            boolean moved=(boolean)call(link,"moveWaitToRoad",new Class<?>[]{double.class},0.);
            check(moved&&f.reservation(entrant)!=null,"Baseline activity-buffer storage semantics changed unexpectedly");
            near(q.getLoadIndicator(),used,"Activity buffer changed native travelling-queue storage");f.safety();
            row("native-storage-buffer-boundary-observation",Map.of("synthetic_native_state",true,"native_capacity_pcu",capacity,"native_travelling_used_pcu",used,
                "native_upstream_receivable",false,"activity_buffer_entry",true,"baseline_behavior_preserved",true,"origin_policy",selectedStoragePolicy(),"integration_gate","review_required: preserve the distinction between native upstream receipt and activity buffer entry; no production activation from this test"));
        }
    }
    public static void main(String[] args)throws Exception{
        try{
            check(args.length==3,"Usage: <frozen-inputs> <baseline|candidate|legacy|physical-gap> <new-report-json>");
            rows.clear();attempts.clear();candidate=Set.of("candidate","physical-gap").contains(args[1]);
            check(Set.of("baseline","candidate","legacy","physical-gap").contains(args[1]),"Explicit revision mode required");
            overlay=Arrays.stream(SimZ1CorridorOccupancy.class.getDeclaredMethods()).anyMatch(m->m.getName().equals("candidateOriginOffer"));
            boolean integrated=Arrays.stream(SimZ1CorridorOccupancy.class.getDeclaredMethods()).anyMatch(m->m.getName().equals("originOffer"));
            integratedPolicy=integrated;
            if(args[1].equals("candidate"))check(overlay&&!integrated&&Arrays.stream(SimZ1CorridorOccupancy.class.getDeclaredMethods()).anyMatch(m->m.getName().equals("candidateActivityFromWait")),"Historical candidate mode requires isolated v2 overlay");
            else check(!overlay,"Historical candidate overlay cannot represent a selected production policy");
            if(Set.of("legacy","physical-gap").contains(args[1]))check(integrated,"Integrated policy API required");
            var scenario=SimZ1TerminalTurnCheck.scenario(Path.of(args[0]));
            if(integrated){var policy=ConfigUtils.addOrGetModule(scenario.getConfig(),SimZ1AdmissionConfigGroup.class);policy.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);policy.setWholeVehicleReservation(true);policy.setOriginPolicy(candidate?SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN:SimZ1AdmissionConfigGroup.LEGACY_ORIGIN);}
            pairedGap(scenario);alternativeSlot(scenario);fullBodies(scenario);upstreamAndOverlap(scenario);nativeFlowAndGlobalFifo(scenario);routeLaneModeWidth(scenario);staleAndMutation(scenario);nativePassageLock();legacyMetricCaller();nativeStorageBoundary();
            var report=new LinkedHashMap<String,Object>();report.put("kind","origin_mechanisms_component_experiment");report.put("revision",args[1]);report.put("cases",rows);report.put("native_attempts",attempts);
            report.put("candidate_overlay_loaded",overlay);report.put("integrated_policy_selected",integrated);report.put("qsim_executed",false);report.put("massive_acceptance",false);report.put("offer_scope","Pure geometry/routing/lock evidence, excludes native flow and right of way");
            report.put("candidate_revision",overlay?"v2":integrated?(candidate?SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN:SimZ1AdmissionConfigGroup.LEGACY_ORIGIN):"historical-producer");report.put("commit_scope","Native origin hook before waiting-head poll; original activity API unchanged; serial ownership only");
            report.put("integration_status","component_evidence_only_not_massive_approval");
            report.put("limitations",List.of("No calibrated capacity conclusion", "No claim to fix citywide circulation", "Short/passage/transit activities retain original commit", "Nominal lane width is not observed width", "Signals, stop holds and downstream native admission require unchanged regression fixtures", "Native upstream storage refusal is not the producer's activity-buffer gate; the controlled boundary observation is not waived"));
            var out=Path.of(args[2]);check(!Files.exists(out),"Do not overwrite experiment evidence");Files.createDirectories(out.toAbsolutePath().getParent());new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.toFile(),report);
            System.out.println("PASS SimZ1OriginMechanismsCheck "+args[1]+": "+rows.size()+" cases");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
