package gt.edu.uvg.sim.zona1;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.lanes.Lane;

/** Bounded evidence from existing native receiver rejections. This is neither
 * a completed travel-time sample nor a forecast of remaining delay. */
final class SimZ1ActiveRetention {
    private static final Set<String> PHYSICAL_REASONS=Set.of("receiver_native_storage","receiver_storage_or_terminal_slot",
        "passage_receipt_storage_or_slot","passage_receipt_native_queue","passage_native_storage",
        "passage_connector_occupied","passage_node_locked","passage_connector_locked",
        "passage_receipt_locked","passage_previous_not_cleared");
    private final Scenario scenario;
    private final Map<String,String> inTraffic=new ConcurrentHashMap<>();
    private final Map<String,Wait> waits=new ConcurrentHashMap<>();
    private final Map<String,RouteStamp> routes=new ConcurrentHashMap<>();
    private record RouteStamp(Object route,List<Id<Link>> links,int index) { }
    // One constant-size aggregate per live head. Historical credit survives only
    // an unbroken observed state chain; a confirmed signal pause is capped at 300s.
    record Wait(String vehicle,Id<Link> link,Id<Lane> lane,Id<Link> next,double since,double last,
                double started,double observed,double accumulatedSeconds,boolean signalPause) {
        // Kept as the duration of the latest continuous physical interval (C529-C meaning).
        double seconds(){return last-since;}
        boolean same(Wait other){return link.equals(other.link)&&lane.equals(other.lane)&&next.equals(other.next);}
    }
    record Retained(Wait evidence,String physicalReason) { }
    SimZ1ActiveRetention(Scenario scenario){this.scenario=scenario;}
    void reset(){inTraffic.clear();waits.clear();routes.clear();}
    void entered(String vehicle,String person) {
        left(vehicle);
        if(!scenario.getTransitVehicles().getVehicles().containsKey(org.matsim.api.core.v01.Id.createVehicleId(vehicle)) &&
            !SimZ1Freight.applies(scenario.getPopulation().getPersons().get(Id.createPersonId(person))))inTraffic.put(vehicle,person);
    }
    void moved(String vehicle){waits.remove(vehicle);routes.remove(vehicle);}
    void left(String vehicle){moved(vehicle);inTraffic.remove(vehicle);}
    void abortedPerson(String person){inTraffic.forEach((vehicle,owner)->{if(owner.equals(person))left(vehicle);});}
    int pending(){return waits.size();}
    void decision(Event event) {
        var a=event.getAttributes();String vehicle=a.get("vehicle");
        if(vehicle==null || !inTraffic.containsKey(vehicle))return;
        String from=a.get("link"),lane=a.get("lane"),next=a.get("nextLink");
        if(from==null || lane==null || next==null || next.isEmpty()){moved(vehicle);return;}
        double now=event.getTime();
        var value=new Wait(vehicle,Id.createLinkId(from),Id.create(lane,Lane.class),Id.createLinkId(next),now,now,now,now,0,false);
        // GO is local permission; QNode can emit storage_wait immediately after it.
        // It must not restart a continuous receiver wait on every simulation step.
        if("turn_go".equals(a.get("reason")) && "true".equals(a.get("nativeHasGreen"))) {
            waits.computeIfPresent(vehicle,(key,old)->{if(old.same(value))return old;routes.remove(vehicle);return null;});return;
        }
        boolean signalPause="WAIT".equals(a.get("decision")) && "false".equals(a.get("nativeHasGreen")) &&
            Set.of("RED","REDYELLOW").contains(a.getOrDefault("signalState","")) &&
            a.getOrDefault("reason","").startsWith("signal_");
        boolean receiverWait=PHYSICAL_REASONS.contains(a.getOrDefault("reason","")) ||
            "storage_passage_lock".equals(a.get("reason")) ||
            "storage_wait".equals(a.get("reason")) && "false".equals(a.get("receiverAcceptedAtDecision"));
        if(!signalPause && (!"WAIT".equals(a.get("decision")) || !receiverWait || !"true".equals(a.get("nativeHasGreen")))) {
            moved(vehicle);return;
        }
        waits.compute(vehicle,(key,old)->{
            double gap=old==null?Double.POSITIVE_INFINITY:now-old.observed;
            boolean consecutive=old!=null && old.same(value) && gap>=0 &&
                gap<=scenario.getConfig().qsim().getTimeStepSize()+1e-9 && now-old.last<=300;
            if(!consecutive){routes.remove(vehicle);return signalPause?null:value;}
            if(signalPause)return new Wait(vehicle,value.link,value.lane,value.next,old.since,old.last,
                old.started,now,old.accumulatedSeconds,true);
            double added=old.signalPause?0:gap;
            return new Wait(vehicle,value.link,value.lane,value.next,old.signalPause?now:old.since,now,
                old.started,now,old.accumulatedSeconds+added,false);
        });
    }
    private double freshness(){return Math.max(1e-6,2*scenario.getConfig().qsim().getTimeStepSize());}
    static QLaneI lane(QLinkI link,Id<Lane> id) {
        if(link instanceof QLinkLanesImpl multi)return multi.getQueueLanes().get(id);
        var lane=link.getAcceptingQLane();return lane.getId().equals(id)?lane:null;
    }
    /** Only at the joined before-step barrier, never from another node's writer. */
    private QVehicle head(Wait wait,QNetwork network,SimZ1RouteSafety safety,double now) {
        if(!inTraffic.containsKey(wait.vehicle) || now<wait.observed || now-wait.observed>freshness() || now-wait.last>300)return null;
        var link=network.getNetsimLinks().get(wait.link);if(link==null)return null;
        var lane=lane(link,wait.lane);if(lane==null || lane.isNotOfferingVehicle())return null;
        var head=lane.getFirstVehicle();
        if(head==null || !head.getId().toString().equals(wait.vehicle) || head.getDriver()==null ||
            !head.getDriver().getId().toString().equals(inTraffic.get(wait.vehicle)) ||
            head.getCurrentLink()==null || !head.getCurrentLink().getId().equals(wait.link) || head.getEarliestLinkExitTime()>now ||
            head.getDriver().isWantingToArriveOnCurrentLink() ||
            !Objects.equals(head.getDriver().chooseNextLinkId(),wait.next) ||
            !safety.laneAllows(wait.link,wait.lane,wait.next))return null;
        // Read-only access: WithinDayAgentUtils' element helpers can clone the plan.
        if(!(head.getDriver() instanceof org.matsim.core.mobsim.framework.PlanAgent agent))return null;
        var element=agent.getCurrentPlanElement();
        if(!(element instanceof org.matsim.api.core.v01.population.Leg leg) ||
            !(leg.getRoute() instanceof org.matsim.core.population.routes.NetworkRoute route))return null;
        var stamp=new RouteStamp(route,SimZ1RouteSafety.full(route),org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.getCurrentRouteLinkIdIndex(head.getDriver()));
        var previous=routes.putIfAbsent(wait.vehicle,stamp);
        return previous!=null && !previous.equals(stamp)?null:head;
    }
    Map<String,Retained> snapshot(QNetwork network,SimZ1RouteSafety safety,double now) {
        var result=new HashMap<String,Retained>();
        waits.forEach((vehicle,wait)->{
            var head=head(wait,network,safety,now);
            var receiver=network.getNetsimLinks().get(wait.next);
            if(head==null || receiver==null){moved(vehicle);return;}
            var probe=SimZ1CorridorOccupancy.receiverFeasibility(scenario.getConfig().qsim(),head,wait.next,
                receiver.getAcceptingQLane().getId().toString(),network,now);
            if(probe.feasible()){moved(vehicle);return;}
            var lane=lane(network.getNetsimLinks().get(wait.link),wait.lane);
            boolean permitted=!(lane instanceof SignalizeableItem signal)||signal.hasGreenForToLink(wait.next);
            // A current red never authorizes evaluation. Only observed red WAITs
            // can bridge intervals; a mere unobserved signal change grants no credit.
            if(!permitted){if(!wait.signalPause)moved(vehicle);return;}
            if(wait.signalPause || now-wait.last>freshness())return; // fresh physical confirmation required after red
            if(!PHYSICAL_REASONS.contains(probe.reason())){moved(vehicle);return;}
            var link=scenario.getNetwork().getLinks().get(wait.link);
            double nominal=Math.max(1,link.getLength()/link.getFreespeed());
            // Existing severity thresholds, applied to proven delay, not a travel-time observation.
            if(CongestionAwareRerouting.needsReroute(true,nominal,nominal+wait.accumulatedSeconds(),link.getCapacity(),link.getCapacity()))
                result.put(vehicle,new Retained(wait,probe.reason()));
        });
        return Map.copyOf(result);
    }
}
