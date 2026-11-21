package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1PriorityReceiverCheck.*;

/** Empty connectors do not make a blocked downstream receipt executable. */
public final class SimZ1PriorityLookaheadCheck {
    static QVehicle planned(Scenario s,String name,List<String> path){
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
        type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(10);
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);
        var leg=s.getPopulation().getFactory().createLeg("car");
        leg.setRoute(RouteUtils.createNetworkRoute(path.stream().map(SimZ1PriorityReceiverCheck::id).toList(),s.getNetwork()));
        var driver=Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class[]{PlanAgent.class,MobsimDriverAgent.class},(p,m,a)->switch(m.getName()){
            case "getCurrentPlanElement"->leg;case "chooseNextLinkId"->id(path.get(1));
            case "getCurrentLinkId"->id(path.get(0));case "getId"->Id.createPersonId(name);
            default->throw new AssertionError(m);
        });
        return proxy(QVehicle.class,(p,m,a)->switch(m.getName()){
            case "getId"->v.getId();case "getVehicle"->v;case "getDriver"->driver;
            case "getMaximumVelocity"->v.getType().getMaximumVelocity();
            default->throw new AssertionError(m);
        });
    }
    public static void main(String[] args){try{
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();var f=n.getFactory();
        double[][] xy={{-40,0},{0,0},{0,-40},{2,0},{4,0},{22,0},{4,40}};
        for(int i=0;i<xy.length;i++)n.addNode(f.createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        String[] names={"avenue","service","short-a","short-b","blocked-receipt","free-receipt"};
        int[][] edges={{0,1},{2,1},{1,3},{3,4},{4,5},{4,6}};
        for(int i=0;i<names.length;i++){
            var from=n.getNodes().get(Id.createNodeId(edges[i][0]));var to=n.getNodes().get(Id.createNodeId(edges[i][1]));
            var link=f.createLink(id(names[i]),from,to);link.setLength(Math.hypot(to.getCoord().getX()-from.getCoord().getX(),to.getCoord().getY()-from.getCoord().getY()));
            link.setFreespeed(10);link.setCapacity(2000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car"));
            link.getAttributes().putAttribute("simz1:priorityRole",i==0?"avenue":"street");n.addLink(link);
        }
        var em=EventsUtils.createEventsManager();var emitted=new ArrayList<org.matsim.api.core.v01.events.Event>();em.addHandler((BasicEventHandler)emitted::add);
        var ledger=new SimZ1CorridorOccupancy(s,Set.of(),em);var cfg=s.getConfig().qsim();SimZ1CorridorOccupancy.install(cfg,ledger);
        var avenue=planned(s,"through",List.of("avenue","short-a","short-b","blocked-receipt"));
        var service=planned(s,"turning",List.of("service","short-a","short-b","free-receipt"));
        var blocker=vehicle("bus-body",13.5,"blocked-receipt");blocker.getVehicle().getType().setWidth(2.5).setPcuEquivalents(3.5);
        require(ledger.canEnter(blocker,id("blocked-receipt"),"original",0),"Blocker needs a genuine full receipt");
        ledger.enter(blocker,id("blocked-receipt"),"original",0,"queue_entry");ledger.progress(blocker,id("blocked-receipt"),"original",1);
        require(ledger.activity(avenue,id("avenue"),"original",2)&&ledger.activity(service,id("service"),"original",2),"Origins must store complete bodies");
        require(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(cfg,avenue,id("blocked-receipt"),"original"),"Fixture receipt must be blocked");
        var head=proxy(QLaneI.class,(p,m,a)->switch(m.getName()){
            case "getId"->Id.create("avenue-lane",Lane.class);case "isNotOfferingVehicle"->false;case "getFirstVehicle"->avenue;default->throw new AssertionError(m);
        });
        var receiving=proxy(QLaneI.class,(p,m,a)->switch(m.getName()){
            case "getId"->Id.create("original",Lane.class);case "isAcceptingFromUpstream"->true;case "isNotOfferingVehicle"->true;default->throw new AssertionError(m);
        });
        var links=new HashMap<Id<Link>,QLinkI>();
        for(var link:n.getLinks().values()) {
            QLaneI entry=link.getId().toString().startsWith("short-")?SimZ1TenthStreetReceptionCheck.emptyNativeQueue(s,em,link):receiving;
            links.put(link.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()){
                case "getLink"->link;case "getOfferingQLanes"->link.getId().equals(id("avenue"))?List.of(head):List.of(receiving);case "getAcceptingQLane"->entry;default->throw new AssertionError(m);
            }));
        }
        var qnet=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
        SimZ1TenthStreetReceptionCheck.registerNodes(s,em,qnet,ledger);
        var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");
        var priority=new UnsignalizedPriority.StopAndYield(n.getNodes().get(Id.createNodeId(1)),settings,null,null,cfg);
        int before=emitted.size();
        require(priority.passageMayProceed(n.getLinks().get(id("service")),id("short-a"),service,qnet,100),
                "Artificial priority: empty connectors hide the avenue's blocked downstream receipt");
        require(SimZ1CorridorOccupancy.receiverNotKnownBlocked(cfg,service,id("short-a"),"original"),"Alternative full receiver is available");
        require(emitted.size()==before,"Priority lookahead must not emit/acquire/release reservations");
        require(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(cfg,avenue,id("blocked-receipt"),"original"),"Priority query released the blocking body");
        ledger.release(blocker.getId(),101,"native_arrival");
        require(!priority.passageMayProceed(n.getLinks().get(id("service")),id("short-a"),service,qnet,102),"Available avenue must retain priority");
        ledger.release(avenue.getId(),103,"native_arrival");ledger.release(service.getId(),103,"native_arrival");SimZ1CorridorOccupancy.uninstall(cfg);
        System.out.println("PASS priority lookahead: blocked receipt cannot compete through empty connectors; valid priority and bodies retained");
    }finally{org.apache.logging.log4j.LogManager.shutdown();}}
}
