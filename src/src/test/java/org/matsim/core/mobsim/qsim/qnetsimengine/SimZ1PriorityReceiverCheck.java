package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;

/** Two-body reproduction of 4a Avenida/service access: an empty native entry
 * queue does not imply enough metric space behind the body at its exit. */
public final class SimZ1PriorityReceiverCheck {
    static void require(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Id<Link> id(String s){return Id.createLinkId(s);}
    @SuppressWarnings("unchecked") static <T>T proxy(Class<T> c,java.lang.reflect.InvocationHandler h){
        return (T)Proxy.newProxyInstance(c.getClassLoader(),new Class<?>[]{c},h);
    }
    static QVehicle vehicle(String name,double length,String next){
        var t=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
        t.setLength(length).setPcuEquivalents(length==2.1?.25:1).setMaximumVelocity(10);
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),t);
        var driver=proxy(MobsimDriverAgent.class,(p,m,a)->switch(m.getName()){
            case "chooseNextLinkId"->id(next);case "getId"->Id.createPersonId(name);
            default->throw new AssertionError(m);
        });
        return proxy(QVehicle.class,(p,m,a)->switch(m.getName()){
            case "getId"->v.getId();case "getVehicle"->v;case "getDriver"->driver;
            default->throw new AssertionError(m);
        });
    }
    public static void main(String[] args){
        try {
            var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();var f=n.getFactory();
            double[][] xy={{0,-40},{0,0},{0,40},{6.379667052692052,0},{40,0}};
            for(int i=0;i<xy.length;i++)n.addNode(f.createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
            String[] ids={"avenue","out","service-in","service-return","service-far","service-far-return"};
            int[][] edges={{0,1},{1,2},{1,3},{3,1},{3,4},{4,3}};
            for(int i=0;i<ids.length;i++){
                var l=f.createLink(id(ids[i]),n.getNodes().get(Id.createNodeId(edges[i][0])),n.getNodes().get(Id.createNodeId(edges[i][1])));
                l.setLength(Math.hypot(l.getToNode().getCoord().getX()-l.getFromNode().getCoord().getX(),l.getToNode().getCoord().getY()-l.getFromNode().getCoord().getY()));
                l.setFreespeed(10);l.setCapacity(2000);l.setNumberOfLanes(1);l.setAllowedModes(Set.of("car"));
                l.getAttributes().putAttribute("simz1:priorityRole",i<2?"avenue":"street");
                n.addLink(l);
            }
            var cfg=s.getConfig().qsim();var events=EventsUtils.createEventsManager();
            var ledger=new SimZ1CorridorOccupancy(s,Set.of(),events);SimZ1CorridorOccupancy.install(cfg,ledger);
            var car=vehicle("blocked-return",4.5,"out");var moto=vehicle("blocked-avenue",2.1,"service-in");
            require(ledger.canEnter(car,id("service-in"),"original",0),"Fixture must admit car normally");
            ledger.enter(car,id("service-in"),"original",0,"queue_entry");ledger.progress(car,id("service-in"),"original",1);
            require(!ledger.canEnter(moto,id("service-in"),"original",2),"Native-empty receiver must be metrically blocked");
            var nativeSpace=new AtomicBoolean(true);
            var head=proxy(QLaneI.class,(p,m,a)->switch(m.getName()){
                case "getId"->Id.create("avenue-lane",Lane.class);case "isNotOfferingVehicle"->false;case "getFirstVehicle"->moto;
                default->throw new AssertionError(m);
            });
            var receiver=proxy(QLaneI.class,(p,m,a)->switch(m.getName()){
                case "getId"->Id.create("original",Lane.class);case "isAcceptingFromUpstream"->nativeSpace.get();
                default->throw new AssertionError(m);
            });
            var qlinks=new HashMap<Id<Link>,QLinkI>();
            for(var l:n.getLinks().values())qlinks.put(l.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()){
                case "getLink"->l;case "getOfferingQLanes"->l.getId().equals(id("avenue"))?List.of(head):List.of();
                case "getAcceptingQLane"->receiver;default->throw new AssertionError(m);
            }));
            var qnet=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return qlinks;}};
            var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");
            var priority=new UnsignalizedPriority.StopAndYield(n.getNodes().get(Id.createNodeId(1)),settings,null,null,cfg);
            require(priority.passageMayProceed(n.getLinks().get(id("service-return")),id("out"),car,qnet,100),
                    "Artificial cycle: metrically blocked avenue prevents service return to empty outlet");
            // A priority probe must not admit the competitor or release the car.
            require(!ledger.canEnter(moto,id("service-in"),"original",101),"Priority probe changed the physical reservation");
            ledger.release(car.getId(),102,"test_native_departure");
            require(ledger.canEnter(moto,id("service-in"),"original",103),"Freed receiver must accept competitor");
            require(!priority.passageMayProceed(n.getLinks().get(id("service-return")),id("out"),car,qnet,104),"Available avenue must keep priority");
            nativeSpace.set(false);
            require(priority.passageMayProceed(n.getLinks().get(id("service-return")),id("out"),car,qnet,105),"Native storage rejection must remain respected");
            SimZ1CorridorOccupancy.uninstall(cfg);
            System.out.println("PASS priority receiver: blocked competitor cannot hold an empty outlet; real priority and reservations preserved");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
