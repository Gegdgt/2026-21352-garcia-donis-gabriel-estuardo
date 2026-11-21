package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.SimZ1RouteSafety;
import java.lang.reflect.Proxy;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;

/** Executes the real QNode branch for a route that changes to a forbidden lane exit. */
public final class PriorityRestrictionCheck {
    @SuppressWarnings("unchecked") static <T> T proxy(Class<T> type,java.lang.reflect.InvocationHandler handler) {
        Class<?>[] interfaces = type == QLaneI.class ? new Class<?>[]{type,
            org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem.class} : new Class<?>[]{type};
        return (T)Proxy.newProxyInstance(type.getClassLoader(),interfaces,(p,m,a) ->
            m.getName().equals("hasGreenForToLink") || m.getName().equals("hasGreenForAllToLinks") ? true : handler.invoke(p,m,a));
    }
    public static void main(String[] args) {
        try {
          for (boolean strict : new boolean[]{false, true}) {
            var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
            var admission=ConfigUtils.addOrGetModule(scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
            if(strict) admission.setStoragePolicy(gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.STRICT);
            scenario.getConfig().qsim().setUseLanes(true);
            var net=scenario.getNetwork(); var factory=net.getFactory();
            for(int i=0;i<4;i++) net.addNode(factory.createNode(Id.createNodeId(i),new Coord(i*100,0)));
            String[] ids={"in","allowed","forbidden"}; int[][] edges={{0,1},{1,2},{1,3}};
            for(int i=0;i<ids.length;i++) {
                var link=factory.createLink(Id.createLinkId(ids[i]),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
                link.setLength(100); link.setFreespeed(10);link.setCapacity(1000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car")); net.addLink(link);
            }
            var laneId=Id.create("allowed-lane",Lane.class);
            var lanes=scenario.getLanes(); var assignment=lanes.getFactory().createLanesToLinkAssignment(Id.createLinkId("in"));
            LanesUtils.createAndAddLane(assignment,lanes.getFactory(),laneId,1000,100,0,1,List.of(Id.createLinkId("allowed")),null);
            lanes.addLanesToLinkAssignment(assignment);
            var safety=new SimZ1RouteSafety(scenario);
            if(safety.laneAllows(Id.createLinkId("in"),laneId,Id.createLinkId("forbidden"))) throw new AssertionError("fixture restriction missing");
            var offered=new AtomicBoolean(true);var aborted=new AtomicBoolean();var arranged=new AtomicBoolean();
            var driver=proxy(MobsimDriverAgent.class,(p,m,a)->switch(m.getName()) {
                case "getId" -> Id.createPersonId("restricted");
                case "chooseNextLinkId" -> Id.createLinkId("forbidden");
                case "setStateToAbort" -> {aborted.set(true);yield null;}
                default -> throw new AssertionError("Unexpected driver call "+m);
            });
            var vehicle=proxy(QVehicle.class,(p,m,a)->switch(m.getName()) {
                case "getId" -> Id.createVehicleId("restricted");
                case "getDriver" -> driver;
                case "getEarliestLinkExitTime" -> 1.0;
                case "getPassengers" -> List.of();
                default -> throw new AssertionError("Unexpected vehicle call "+m);
            });
            var lane=proxy(QLaneI.class,(p,m,a)->switch(m.getName()) {
                case "getId" -> laneId;
                case "getFirstVehicle" -> vehicle;
                case "isNotOfferingVehicle" -> !offered.get();
                case "getLastMovementTimeOfFirstVehicle" -> 1.0;
                case "popFirstVehicle" -> {offered.set(false);yield vehicle;}
                default -> throw new AssertionError("Forbidden exit touched lane storage: "+m);
            });
            var qlinks=new HashMap<Id<Link>,QLinkI>();
            for(var link:net.getLinks().values()) qlinks.put(link.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()) {
                case "getLink" -> link;
                case "isNotOfferingVehicle" -> !offered.get();
                case "getOfferingQLanes" -> List.of(lane);
                default -> throw new AssertionError("Forbidden exit touched outgoing link: "+m);
            }));
            var qnet=new QNetwork(net,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return qlinks;}};
            var engine=proxy(QNetsimEngineI.NetsimInternalInterface.class,(p,m,a)->switch(m.getName()) {
                case "getNetsimNetwork" -> qnet;
                case "arrangeNextAgentState" -> {arranged.set(true);yield null;}
                default -> throw new AssertionError("Unexpected engine call "+m);
            });
            var events=EventsUtils.createEventsManager(); var captured=new ArrayList<Event>();events.addHandler((BasicEventHandler)captured::add);
            var diagnostics=new Zona1NativeDiagnostics(scenario,events);
            var context=new NetsimEngineContext(events,7.5,null,null,scenario.getConfig().qsim(),new MobsimTimer(),null);
            var builder=new Zona1QNodeImpl.Builder(engine,context,scenario.getConfig().qsim(),diagnostics);
            builder.setRouteSafety(safety);
            builder.setAdmissionPolicy(admission,new gt.edu.uvg.sim.zona1.Zona1PriorityConfigGroup());
            builder.setTurnAcceptanceLogic((l,q,n,v,network,time)->{throw new AssertionError("Forbidden turn reached permission logic");});
            var node=builder.build(net.getNodes().get(Id.createNodeId(1)));node.init();node.doSimStep(10);
            if(!aborted.get()||!arranged.get()||offered.get()) throw new AssertionError("Forbidden route did not abort once");
            if(captured.stream().anyMatch(e->e instanceof LinkEnterEvent)) throw new AssertionError("Forbidden turn crossed");
            var decision=captured.stream().filter(e->e.getEventType().equals(Zona1NativeDiagnostics.EVENT_TYPE)).findFirst().orElseThrow().getAttributes();
            if(!decision.get("reason").equals("turn_restriction")||!decision.get("decision").equals("ABORT")||!decision.get("waitCategory").equals("turn_restriction")) throw new AssertionError(decision);
            System.out.println("PASS "+admission.getStoragePolicy()+" forbidden lane with green: ABORT turn_restriction, no outgoing storage access or LinkEnter");
          }
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
