package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.Id;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Phase 4 component controls, using the unmodified producer, never QSim.
 * Two actors per synthetic case; no historical queue/cursor is reconstructed.
 * The construction seam installs the actual StopAndYield strategy in an
 * existing native node. Only signals change afterwards; no reservations,
 * native capacity, body fronts, deadlines or queue membership are injected.
 */
public final class SimZ1DownstreamReleaseCheck {
    private static final List<Map<String,Object>> evidence=new ArrayList<>();
    private static final List<Map<String,Object>> observations=new ArrayList<>();

    private static UnsignalizedPriority.StopAndYield priority(SimZ1StorageFixture f,String node) throws Exception {
        // The helper already builds strict native nodes, but its diagnostic
        // module defaults to matsim15-native. Align the shared diagnostic
        // configuration before actors; the existing node policy is unchanged.
        var admission=org.matsim.core.config.ConfigUtils.addOrGetModule(f.scenario.getConfig(),SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");settings.setConflicts("conservative");
        var nativeNode=f.nodes.get(Id.createNodeId(node));
        var logic=new UnsignalizedPriority.StopAndYield(f.scenario.getNetwork().getNodes().get(Id.createNodeId(node)),
            settings,f.manager,null,f.scenario.getConfig().qsim());
        set(nativeNode,"turnAcceptanceLogic",logic);
        require(field(nativeNode,"turnAcceptanceLogic")==logic,"Native node did not use the real priority strategy");
        return logic;
    }

    private static List<String> ids(Iterable<?> queue,boolean pairs) {
        var ids=new ArrayList<String>();
        for(var item:queue){var vehicle=(QVehicle)(pairs?((org.apache.commons.lang3.tuple.Pair<?,?>)item).getKey():item);ids.add(vehicle.getId().toString());}
        return ids;
    }

    private static Map<String,Object> queue(QueueWithBuffer q) throws Exception {
        var out=new LinkedHashMap<String,Object>();
        out.put("queue",q.getId().toString());out.put("buffer",ids((Iterable<?>)field(q,"buffer"),true));
        out.put("travelling",ids((Iterable<?>)field(q,"vehQueue"),false));
        out.put("head",q.getFirstVehicle()==null?null:q.getFirstVehicle().getId().toString());
        out.put("offering",!q.isNotOfferingVehicle());out.put("used_pcu_excluding_buffer",q.getLoadIndicator());
        out.put("storage_capacity_pcu",q.getStorageCapacity());out.put("native_accepting",q.isAcceptingFromUpstream());
        out.put("flow_credit_pcu",field(field(q,"flowcap_accumulate"),"value"));
        out.put("flow_credit_time",field(field(q,"flowcap_accumulate"),"timeStep"));
        out.put("flow_capacity_pcu_per_step",q.getSimulatedFlowCapacityPerTimeStep());return out;
    }

    private static List<Map<String,Object>> reservations(SimZ1StorageFixture f) throws Exception {
        var result=new ArrayList<Map<String,Object>>();
        for(var actor:f.actors.values()){
            var r=f.reservation(actor);var item=new LinkedHashMap<String,Object>();item.put("vehicle",actor.vehicle.getId().toString());
            item.put("route_index",actor.index);item.put("route",actor.path);item.put("present",r!=null);
            if(r!=null){
                for(String name:List.of("ordinal","slot","length","footprint","frontBound","nativeFront","nativeQueue"))item.put(name,field(r,name));
                item.put("link",field(r,"link").toString());var domain=field(r,"domain");item.put("domain",field(domain,"id"));
                item.put("domain_capacity_m",field(domain,"capacity"));item.put("domain_used_m",((double[])field(domain,"used")).clone());
                var p=field(r,"passage");item.put("passage_present",p!=null);
                if(p!=null)for(String name:List.of("released","notBefore","clearFront"))item.put("passage_"+name,field(p,name));
            }
            result.add(item);
        }
        return result;
    }

    private static String queryState(SimZ1StorageFixture f) throws Exception {
        var state=new LinkedHashMap<String,Object>();
        for(String name:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks","nextOrdinal","passageRequestTime","passageRequests","passageDeadlines","waits","waitReasons"))
            state.put(name,SimZ1OriginAdmissionFixture.deep(field(f.ledger,name),new IdentityHashMap<>()));
        var queues=new TreeMap<String,Object>();
        for(var link:f.links.values()){
            var lanes=link instanceof QLinkLanesImpl multi?multi.getQueueLanes().values():List.of(link.getAcceptingQLane());
            for(var lane:lanes)queues.put(lane.getId().toString(),queue((QueueWithBuffer)lane));
        }
        state.put("queues",queues);state.put("clock",f.timer.getTimeOfDay());state.put("events",f.events.size());state.put("moves",f.moves);
        state.put("actor_cursors",f.actors.values().stream().map(a->a.vehicle.getId()+":"+a.index).toList());
        return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(state);
    }

    private static Map<String,Object> snapshot(SimZ1StorageFixture f,SimZ1StorageFixture.Actor actor,double now) throws Exception {
        var source=f.links.get(id(actor.path.get(actor.index)));
        var offered=(QueueWithBuffer)source.getOfferingQLanes().stream()
            .filter(q->!q.isNotOfferingVehicle()&&q.getFirstVehicle()==actor.vehicle).findFirst().orElseThrow();
        String target=actor.path.get(actor.index+1);var targetQueue=(QueueWithBuffer)f.links.get(id(target)).getAcceptingQLane();
        var node=f.nodes.get(source.getLink().getToNode().getId());var result=new LinkedHashMap<String,Object>();
        result.put("time",now);result.put("vehicle",actor.vehicle.getId().toString());result.put("source",source.getLink().getId().toString());result.put("target",target);
        result.put("source_queue",queue(offered));result.put("receiver_queue",queue(targetQueue));
        result.put("signal_green",offered.hasGreenForToLink(id(target)));
        result.put("node_locked_by_other",f.ledger.lockedByOther(source.getLink().getToNode().getId(),actor.vehicle.getId()));
        result.put("preauthorized_passage",f.ledger.preauthorized(actor.vehicle.getId(),source.getLink().getId(),id(target)));
        var logic=field(node,"turnAcceptanceLogic");result.put("turn_logic",logic.getClass().getName());
        if(logic instanceof UnsignalizedPriority.StopAndYield){
            var head=((Map<?,?>)field(logic,"heads")).get(offered);
            result.put("priority_head_known",head!=null);
            if(head!=null){result.put("priority_head_vehicle",((QVehicle)field(head,"vehicle")).getId().toString());result.put("priority_ready_time",field(head,"ready"));result.put("priority_time_satisfied",now>=(double)field(head,"ready"));}
        }
        String beforeQuery=queryState(f);var query=f.query(actor,target,now);
        require(beforeQuery.equals(queryState(f)),"Snapshot query mutated deep ledger/native queues, flow, clock, events or actor cursors");
        result.put("physical_query_feasible",query.feasible());result.put("physical_query_reason",query.reason());
        result.put("reservations",reservations(f));
        for(String name:List.of("nodeLocks","connectorLocks","receiptLocks","crossings")){
            Object value=field(name.equals("crossings")?node:f.ledger,name);result.put(name,value.toString());
        }
        result.put("positions_observed",false);return result;
    }

    private static void attempt(SimZ1StorageFixture f,SimZ1StorageFixture.Actor actor,String stage,double now,boolean expected) throws Exception {
        f.timer.setTime(now);var before=snapshot(f,actor,now);int start=f.events.size(),moves=f.moves;
        boolean moved=f.cross(actor,now);require(moved==expected,"Unexpected native crossing at "+stage);
        require(f.moves==moves+(moved?1:0),"Attempt did not match actual native route movement");
        var row=new LinkedHashMap<String,Object>();row.put("stage",stage);row.put("before",before);row.put("crossed",moved);
        row.put("events",f.events.subList(start,f.events.size()).stream().map(e->{var item=new LinkedHashMap<String,Object>();item.put("type",e.getEventType());item.put("time",e.getTime());item.put("attributes",e.getAttributes());return item;}).toList());
        row.put("reservations_after",reservations(f));row.put("moves_after",f.moves);evidence.add(row);f.safety();
    }

    private static void requireReason(SimZ1StorageFixture f,String vehicle,String reason,double time){
        var actual=f.events.stream().filter(e->e.getTime()==time&&vehicle.equals(e.getAttributes().get("vehicle"))).map(e->e.getEventType()+":"+e.getAttributes()).toList();
        require(f.events.stream().anyMatch(e->e.getTime()==time&&vehicle.equals(e.getAttributes().get("vehicle"))&&reason.equals(e.getAttributes().get("reason"))),"Missing native reason "+reason+" for "+vehicle+" at "+time+"; actual="+actual);
    }

    private static void leaderExitAndCrossingBody() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,true)){
            // Explicit synthetic approach control. The helper's default role
            // is avenue/free: a node highway=stop is not this priority API's
            // stop contract. Configure it before constructing the strategy.
            var approach=f.links.get(id("receipt-a")).getLink();
            approach.getAttributes().putAttribute("simz1:priorityRole","street");
            approach.getAttributes().putAttribute("simz1:priorityControl","stop");
            var priority=priority(f,"a-end");
            var leader=f.actor("release-leader",4.5,"receipt-a","dest-a");
            var follower=f.actor("release-follower",4.5,"receipt-a","dest-a");
            var terminal=f.queue("receipt-a",".lane.0");
            f.seed(leader,".lane.0",0);f.ready(terminal,100);f.seed(follower,".lane.0",100);f.ready(terminal,200);
            require(f.slot(leader)==0&&f.slot(follower)==0,"Route-compatible FIFO slot changed");
            require(terminal.getFirstVehicle()==leader.vehicle,"Native leader is not the queue head");
            var reservation=f.reservation(follower);var ordinal=field(reservation,"ordinal");double bound=f.front(follower),nativeFront=(double)field(reservation,"nativeFront");
            near(bound,f.front(leader)-4.6,"Follower must be held by the leader body plus gap");
            require(nativeFront>bound,"Synthetic case does not isolate leader-constrained progress");
            priority.observeHeads(f.qnet,200);terminal.setSignalized(true);terminal.setSignalStateAllTurningMoves(SignalGroupState.RED);
            attempt(f,leader,"red_preserves_fifo_head",201,false);requireReason(f,"release-leader","signal_not_green",201);
            terminal.setSignalStateAllTurningMoves(SignalGroupState.GREEN);
            attempt(f,leader,"green_still_requires_native_stop",202,false);requireReason(f,"release-leader","priority_stop",202);
            require(f.reservation(follower)==reservation&&f.front(follower)==bound,"Rejected crossing altered follower body");
            attempt(f,leader,"leader_native_exit_recomputes_follower",206,true);
            require(f.reservation(follower)==reservation&&field(reservation,"ordinal").equals(ordinal),"Leader exit replaced follower identity or FIFO ordinal");
            near((double)field(reservation,"nativeFront"),nativeFront,"Release invented native endpoint progress");
            near(f.front(follower),nativeFront,"Leader release failed to propagate already eligible progress");
            require(f.events.stream().anyMatch(e->e.getTime()==206&&e.getEventType().equals("simz1OccupancyProgress")&&"release-follower".equals(e.getAttributes().get("vehicle"))&&"leader_release".equals(e.getAttributes().get("reason"))),"No synchronous leader_release propagation");
            // Ordinary flow/queue processing, not removing or buffering by hand.
            f.ready(terminal,207);
            require(terminal.getFirstVehicle()==follower.vehicle&&terminal.isNotOfferingVehicle(),"Travelling head with native flow debt must not be offered");
            require((double)field(field(terminal,"flowcap_accumulate"),"value")<0,"Expected native PCU debt at207 is absent");
            observations.add(Map.of("stage","native_flow_debt_after_leader_exit","time",207,"queue",queue(terminal),
                "native_rate_pcu_per_second",terminal.getSimulatedFlowCapacityPerTimeStep()/f.scenario.getConfig().qsim().getTimeStepSize(),
                "meaning","getFirstVehicle can be travelling; no node attempt is made before buffer offering"));
            f.ready(terminal,208);priority.observeHeads(f.qnet,208);
            require(!terminal.isNotOfferingVehicle()&&terminal.getFirstVehicle()==follower.vehicle,"Follower never became the real offered native head");
            var stop=((Map<?,?>)field(priority,"heads")).get(terminal);
            require(stop!=null&&(double)field(stop,"ready")<=213,"Receiver control would be masked by a pending STOP");
            require(terminal.hasGreenForToLink(id("dest-a"))&&f.queue("dest-a",".original").isAcceptingFromUpstream(),"Crossing control is masked by red or native receiving storage");
            require(f.query(follower,"dest-a",213).feasible(),"Expected other compatible receiving slots to remain physically feasible");
            attempt(f,follower,"green_stop_ready_and_receipt_feasible_but_crossing_body_uncleared",213,false);
            requireReason(f,"release-follower","permission_not_crossing",213);
            requireReason(f,"release-follower","admission_conflict_executed",213);
            require(f.events.stream().anyMatch(e->e.getTime()==213&&"release-follower".equals(e.getAttributes().get("vehicle"))&&"modeled_body_clearance".equals(e.getAttributes().get("conflictEvidence"))),"Rejection is not the existing crossing body's clearance gate");
            require(f.reservation(follower)==reservation,"Body rejection discarded source reservation");
            f.ready(f.queue("dest-a",".original"),300);
            attempt(f,follower,"native_receiver_progress_then_follower_crosses",301,true);
            require(f.moves==2,"Case requires exactly two native node moves");
            System.out.println("PASS leader exit: FIFO body recompute, red, actual stop, feasible receiver with uncleared crossing body, native recovery");
        }
    }

    private static void passageBodyThenSignal() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true)){
            var priority=priority(f,"j");
            var owner=f.through("passage-owner",4.5,"avenue","receipt-a");
            var requester=f.through("passage-requester",4.5,"street","receipt-b");
            f.seed(owner,".lane.0",0);f.seed(requester,".lane.0",0);
            f.ready(f.queue("avenue",".lane.0"),100);f.ready(f.queue("street",".lane.0"),100);priority.observeHeads(f.qnet,100);
            attempt(f,owner,"passage_acquisition",101,true);
            f.ready(f.queue("short0",".original"),102);f.split("short0",103);f.ready(f.queue("short0",".lane.0"),104);
            attempt(f,owner,"owner_reaches_reserved_receipt",105,true);
            var passage=field(f.reservation(owner),"passage");require(passage!=null&&!(boolean)field(passage,"released"),"Passage disappeared before body clearance");
            near(f.front(owner),0,"Entering receipt invented travel");
            attempt(f,requester,"real_passage_owner_blocks_competitor",106,false);
            f.timer.setTime(200);f.ledger.advanceTime(200);
            require(200>=(double)field(passage,"notBefore")&&!(boolean)field(passage,"released"),"Time alone released an uncleared passage");
            attempt(f,requester,"deadline_elapsed_body_still_holds_lock",201,false);
            var source=f.queue("street",".lane.0");source.setSignalized(true);source.setSignalStateAllTurningMoves(SignalGroupState.RED);
            f.ready(f.queue("receipt-a",".original"),202);
            require((boolean)field(passage,"released"),"Native receiver progress left obsolete passage lock");
            require(!f.ledger.lockedByOther(Id.createNodeId("j"),requester.vehicle.getId()),"Cleared owner kept node lock");
            attempt(f,requester,"released_lock_does_not_override_red",203,false);requireReason(f,"passage-requester","signal_not_green",203);
            source.setSignalStateAllTurningMoves(SignalGroupState.GREEN);
            attempt(f,requester,"clearance_and_green_allow_real_crossing",204,true);
            long releases=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"passage-owner".equals(e.getAttributes().get("vehicle"))&&"RELEASE".equals(e.getAttributes().get("action"))).count();
            require(releases==1,"Owner passage did not release exactly once");require(f.moves==3,"Case requires exactly three native node moves");
            System.out.println("PASS passage release: real owner, no timeout, exact-once body clearance, red preserved, real recovery");
        }
    }

    public static void main(String[] args) throws Exception {
        require(args.length==1,"Usage: SimZ1DownstreamReleaseCheck <native-output.json>");
        try{
            leaderExitAndCrossingBody();passageBodyThenSignal();
            var result=new LinkedHashMap<String,Object>();result.put("status","PASS");result.put("case_count",2);result.put("max_actors_per_case",2);
            result.put("scope","synthetic native component controls using current producer; no historical replay, no QSim, no admission overlay");
            result.put("priority_seam","At fixture construction only, the actual StopAndYield is installed in the existing native node; attempts run through Zona1QNodeImpl.moveVehicleOverNode");
            result.put("diagnostic_configuration","The helper already constructs strict nodes with whole-body reservations. Before actor seeding, its shared diagnostic config module is aligned with that existing node policy; this corrects the default event label without changing node admission logic.");
            result.put("signal_scope","Signals are set directly on the native queue for controlled red/green cases; this is not a full SignalsData plan. The gate is native hasGreenForToLink and actual turn decisions, not the diagnostic calendar label.");
            result.put("explicit_synthetic_control","Case 1 configures receipt-a priorityRole=street and priorityControl=stop before strategy construction and actor seeding; geometric lengths, capacities, body sizes and queue partitions remain the helper defaults. Attempt 1 incorrectly expected STOP from a node attribute while the approach was avenue/free; its failing source/log are preserved separately.");
            result.put("query_guard","Before/after value snapshots compare ledger domains/reservations/pending/locks/timers/ordinal, all native queue membership and PCU/flow fields, clock, events, moves and actor cursors.");
            result.put("flow_setup_correction","Attempt 2 mistook getFirstVehicle for an offered buffer head. The final case preserves native debt/no offering at207, processes the queue at208 and starts its STOP clock from actual offering; no credit or capacity is injected.");
            result.put("crossing_attribution_correction","Attempts3/4 establish that another receiving slot remains feasible while the previous same-movement crossing body is uncleared. The final control requires green, STOP ready, native receipt and physical feasibility, followed by the exact modeled_body_clearance rejection. It preserves the three-slot geometry and later native recovery.");
            result.put("stop_scope","Native priority STOP is tested; a blocking transit dwell is covered by the separately recorded existing blocking-stop fixture, not simulated here");
            result.put("gates","Same-attempt queue/head/FIFO and flow state, receiver PCU, signal, real priority decision, body feasibility, passage/crossing locks, reservation ownership; no missing historical gate is inferred");
            result.put("historical_classification","No new historical A finding; positive/negative controls do not classify incomplete historical states");result.put("attempts",evidence);result.put("native_observations",observations);
            var output=Path.of(args[0]);if(output.toAbsolutePath().getParent()!=null)Files.createDirectories(output.toAbsolutePath().getParent());
            Files.writeString(output,new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(result)+System.lineSeparator(),StandardCharsets.UTF_8);
            System.out.println("PASS SimZ1DownstreamReleaseCheck: 2 controlled native release cases; JSON="+output);
        }catch(Exception|AssertionError failure){
            // Preserve the exact failing prefix for review; this never turns
            // a failure into PASS and the original exception still exits1.
            var result=new LinkedHashMap<String,Object>();result.put("status","FAIL");result.put("exception",failure.toString());
            result.put("scope","synthetic native component failure prefix; no historical replay, no producer change");
            result.put("attempts",evidence);result.put("native_observations",observations);
            var output=Path.of(args[0]);if(output.toAbsolutePath().getParent()!=null)Files.createDirectories(output.toAbsolutePath().getParent());
            Files.writeString(output,new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(result)+System.lineSeparator(),StandardCharsets.UTF_8);
            throw failure;
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
