package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.*;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;
import gt.edu.uvg.sim.zona1.*;

/** Reproduce the acquired-passage state observed at 24 Calle on 2026-10-30.
 * Reflection installs that already-authorized state, not a new admission rule.
 * The clock advances with an empty vehQueue: the owner has reached its buffer.
 */
public final class SimZ1PassageTimerCheck {
    private static final double DEADLINE=43463.48344132278, CLEAR=7.60001889293846;
    private static final double FRONT=10.215542268763684;
    private static final Id<Link> CONNECTOR=Id.createLinkId("connector"), RECEIPT=Id.createLinkId("receipt");
    private static final Id<Node> LOCKED=Id.createNodeId("n1");
    private static final Id<Vehicle> WAITER=Id.createVehicleId("waiter");
    private record Fixture(SimZ1CorridorOccupancy ledger,QVehicle owner,List<Event> events) { }
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Object field(Object object,String name) throws Exception {
        var field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    private static void set(Object object,String name,Object value) throws Exception {
        var field=object.getClass().getDeclaredField(name);field.setAccessible(true);field.set(object,value);
    }
    private static void link(Network network,String name,String from,String to,double length){
        var link=network.getFactory().createLink(Id.createLinkId(name),network.getNodes().get(Id.createNodeId(from)),network.getNodes().get(Id.createNodeId(to)));
        link.setLength(length);link.setFreespeed(10);link.setCapacity(2000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car"));network.addLink(link);
    }
    private static QVehicle vehicle(String name){
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(4.5).setMaximumVelocity(10).setPcuEquivalents(1);
        var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(name),type);
        return (QVehicle)Proxy.newProxyInstance(QVehicle.class.getClassLoader(),new Class[]{QVehicle.class},(p,m,a)->switch(m.getName()){
            case "getId"->vehicle.getId();case "getVehicle"->vehicle;case "getDriver"->null;
            case "getEarliestLinkExitTime"->43463.;default->throw new AssertionError(m);
        });
    }
    private static Fixture fixture(String name,boolean receipt) throws Exception {
        var scenario=scenario();var network=scenario.getNetwork();
        var manager=EventsUtils.createEventsManager();var observed=new ArrayList<Event>();manager.addHandler((BasicEventHandler)observed::add);
        var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);var owner=vehicle(name);
        require(ledger.activity(owner,RECEIPT,"receipt.original",43459),"Snapshot fixture cannot hold one car");
        installPassage(ledger,owner,network,receipt,DEADLINE);
        require(ledger.lockedByOther(LOCKED,WAITER),"Passage did not lock its junction");
        return new Fixture(ledger,owner,observed);
    }
    private static Scenario scenario(){
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var network=scenario.getNetwork();
        for(int i=0;i<3;i++)network.addNode(network.getFactory().createNode(Id.createNodeId("n"+i),new Coord(i==0?0:i==1?3:FRONT+5,0)));
        network.getNodes().get(LOCKED).getAttributes().putAttribute("osm:highway","stop");
        link(network,"connector","n0","n1",3);link(network,"receipt","n1","n2",FRONT+2);return scenario;
    }
    @SuppressWarnings("unchecked")
    private static void installPassage(SimZ1CorridorOccupancy ledger,QVehicle owner,Network network,boolean receipt,double deadline) throws Exception {
        var reservation=((Map<Id<Vehicle>,?>)field(ledger,"active")).get(owner.getId());
        var type=Class.forName(SimZ1CorridorOccupancy.class.getName()+"$Passage");
        var constructor=type.getDeclaredConstructors()[0];constructor.setAccessible(true);
        var passage=constructor.newInstance(List.of(network.getLinks().get(CONNECTOR)),Map.of(CONNECTOR,0),receipt?network.getLinks().get(RECEIPT):null,0.,receipt?null:RECEIPT);
        set(passage,"notBefore",deadline);set(passage,"clearFront",CLEAR);set(passage,"freeFront",FRONT);set(passage,"reachableFront",FRONT);
        // The historical passage contains the receiving junction as a lock.
        ((Set<Id<Node>>)field(passage,"nodes")).add(LOCKED);
        var acquire=SimZ1CorridorOccupancy.class.getDeclaredMethod("acquirePassage",Id.class,reservation.getClass(),type,Id.class);
        acquire.setAccessible(true);acquire.invoke(ledger,owner.getId(),reservation,passage,CONNECTOR);
    }
    private static long releases(Fixture f){return f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"RELEASE".equals(e.getAttributes().get("action"))).count();}
    private static void clock(Fixture f,double now){f.ledger.advanceEligible(List.of(),RECEIPT,"receipt.original",now);}
    private static void fractionalDeadlineWithoutProgress() throws Exception {
        var f=fixture("z1_92569",true);
        f.ledger.progress(f.owner,RECEIPT,"receipt.original",43463);
        require(f.ledger.lockedByOther(LOCKED,WAITER),"Released before fractional minimum time");
        long progress=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyProgress")).count();
        clock(f,43463);require(f.ledger.lockedByOther(LOCKED,WAITER),"Same tick released early");
        clock(f,43464);
        require(!f.ledger.lockedByOther(LOCKED,WAITER),"STALE_PASSAGE: spatial clearance satisfied at 43463, minimum time 43463.483441; lock survives tick 43464 without new progress");
        require(releases(f)==1,"Passage must release exactly once");
        require(f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyProgress")).count()==progress,"Timer invented progress");
        clock(f,64800);require(releases(f)==1,"Repeated tick duplicated passage release");
        require(((Map<?,?>)field(f.ledger,"active")).containsKey(f.owner.getId()),"Timer released the vehicle's occupancy reservation");
        require(((Map<?,?>)field(f.ledger,"nodeLocks")).isEmpty()&&((Map<?,?>)field(f.ledger,"connectorLocks")).isEmpty()&&((Map<?,?>)field(f.ledger,"receiptLocks")).isEmpty(),"Passage left one of its lock maps behind");
        f.ledger.release(f.owner.getId(),64801,"arrival");require(releases(f)==1,"Arrival duplicated passage release");
        System.out.println("PASS fractional 24 Calle deadline: release at 43464, no new progress, occupancy retained, all three lock maps released once");
    }
    private static void timeAloneCannotRelease() throws Exception {
        var f=fixture("uncleared",true);clock(f,64800);
        require(f.ledger.lockedByOther(LOCKED,WAITER)&&releases(f)==0,"Age alone released an uncleared body");
        f.ledger.progress(f.owner,RECEIPT,"receipt.original",64801);
        require(!f.ledger.lockedByOther(LOCKED,WAITER)&&releases(f)==1,"Late body clearance did not release");
        f.ledger.release(f.owner.getId(),64802,"arrival");
        System.out.println("PASS deadline before body clearance: holds indefinitely until actual modeled endpoint progress");
    }
    private static void canceledDeadlineCannotReleaseNewReservation() throws Exception {
        var f=fixture("reused-id",true);f.ledger.progress(f.owner,RECEIPT,"receipt.original",43463);
        f.ledger.release(f.owner.getId(),43463.1,"abort");require(releases(f)==1,"Abort did not release locks");
        require(f.ledger.activity(f.owner,RECEIPT,"receipt.original",43463.2),"Replacement reservation not admitted");
        clock(f,43464);require(releases(f)==1,"Old deadline affected a different reservation ordinal");
        require(((Map<?,?>)field(f.ledger,"active")).containsKey(f.owner.getId()),"Stale deadline removed new reservation");
        f.ledger.release(f.owner.getId(),43465,"arrival");
        System.out.println("PASS obsolete deadline cannot affect reused vehicle ID/new reservation ordinal");
    }
    private static void boundaryExitRemainsLockedUntilExit() throws Exception {
        var f=fixture("boundary",false);f.ledger.progress(f.owner,CONNECTOR,"connector.original",43463);clock(f,64800);
        require(f.ledger.lockedByOther(LOCKED,WAITER)&&releases(f)==0,"Timer prematurely released a retained-origin boundary exit");
        f.ledger.release(f.owner.getId(),64801,"arrival");require(releases(f)==1,"Boundary arrival failed to release");
        System.out.println("PASS boundary exit remains reserved until its native traffic exit");
    }
    /** Exercise the production controller binding with no native vehicles to
     * call advanceEligible. Only the actual QSim BeforeSimStep hook can expire
     * this reconstructed already-acquired passage. This is a lifecycle fixture,
     * not a traffic-capacity or successful-trip acceptance test.
     */
    private static void nativeClockHookWithNoActiveQueues() throws Exception {
        var scenario=scenario();var config=scenario.getConfig();
        var out=Files.createTempDirectory(Path.of("runtime"),"passage-timer-hook-");
        config.controler().setOutputDirectory(out.resolve("run").toString());config.controler().setLastIteration(0);
        config.global().setNumberOfThreads(1);config.qsim().setNumberOfThreads(1);config.qsim().setStartTime(0);config.qsim().setEndTime(5);
        config.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setRemoveStuckVehicles(false);config.qsim().setUsingFastCapacityUpdate(false);
        var admission=ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var owner=vehicle("native-hook-snapshot");var events=new ArrayList<Event>();var checked=new HashSet<Integer>();
        var controller=new Controler(scenario);UnsignalizedPriority.configure(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){
            addEventHandlerBinding().toInstance((BasicEventHandler)events::add);
            addMobsimListenerBinding().toInstance((org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener)event->{
                int tick=(int)event.getSimulationTime();var ledger=SimZ1CorridorOccupancy.get(config.qsim());
                try{
                    if(tick==1){
                        require(ledger!=null,"Native factory did not install its ledger");
                        require(ledger.activity(owner,RECEIPT,"receipt.original",1),"Native snapshot admission");
                        installPassage(ledger,owner,scenario.getNetwork(),true,3.48344132278);
                    }
                    if(tick==2)ledger.progress(owner,RECEIPT,"receipt.original",2);
                    if(tick==3){require(ledger.lockedByOther(LOCKED,WAITER),"Native clock released before minimum time");checked.add(3);}
                    if(tick==4){require(!ledger.lockedByOther(LOCKED,WAITER),"BeforeSimStep listener omitted buffer-only passage deadline");checked.add(4);ledger.release(owner.getId(),4,"fixture_cleanup");}
                }catch(Exception ex){throw new RuntimeException(ex);}
            });
        }});
        controller.run();require(checked.equals(Set.of(3,4)),"Native QSim did not exercise both deadline ticks");
        var releases=events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"RELEASE".equals(e.getAttributes().get("action"))).toList();
        require(releases.size()==1&&releases.get(0).getTime()==4&&"body_clearance".equals(releases.get(0).getAttributes().get("reason")),"Native clock release was missing, duplicated, or only cleanup");
        System.out.println("PASS production QSim BeforeSimStep binding: empty queues, due body-cleared passage released once at tick4; lifecycle fixture evidence="+out);
    }
    public static void main(String[] args) throws Exception {
        fractionalDeadlineWithoutProgress();timeAloneCannotRelease();canceledDeadlineCannotReleaseNewReservation();boundaryExitRemainsLockedUntilExit();
        nativeClockHookWithNoActiveQueues();
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
