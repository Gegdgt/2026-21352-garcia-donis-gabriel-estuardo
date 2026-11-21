package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancyCheck.*;

/** Two parallel avenue heads need the same complete short service return.
 * Its downstream priority query must not create a mutual upstream veto. */
public final class SimZ1ParallelPassagePriorityCheck {
    public static void main(String[] args) throws Exception {try{run();pureQueries();}finally{org.apache.logging.log4j.LogManager.shutdown();}}
    static void run() throws Exception {
        var c=ConfigUtils.createConfig();var out=Files.createTempDirectory(Path.of("runtime"),"parallel-passage-priority-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);
        c.qsim().setStartTime(0);c.qsim().setEndTime(200);c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setRemoveStuckVehicles(false);c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.travelTimeCalculator().setSeparateModes(false);c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var priority=ConfigUtils.addOrGetModule(c,Zona1PriorityConfigGroup.class);priority.setClassification("explicit");
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();double[][] xy={{-100,0},{0,0},{0,8},{0,40},{100,0},{200,0}};
        for(int i=0;i<xy.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        link(n,"avenue","0","1",100,2);link(n,"service-out","1","2",8,1);link(n,"service-tail","2","3",32,1);
        link(n,"service-back-tail","3","2",32,1);link(n,"service-back","2","1",8,1);link(n,"receipt","1","4",100,2);link(n,"destination","4","5",100,2);
        for(var l:n.getLinks().values()){l.getAttributes().putAttribute("simz1:priorityRole",l.getId().toString().startsWith("service")?"street":"avenue");l.setCapacity(2000*l.getNumberOfLanes());}
        LanesGenerator.build(s);var f=s.getPopulation().getFactory();
        for(int i=0;i<2;i++){
            String name="actor"+i;var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(type);
            var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicle(v);var person=f.createPerson(Id.createPersonId(name));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",v.getId()));
            var plan=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("avenue"));home.setEndTime(1);plan.addActivity(home);
            var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute(List.of("avenue","service-out","service-back","receipt","destination").stream().map(Id::createLinkId).toList(),n);route.setVehicleId(v.getId());leg.setRoute(route);plan.addLeg(leg);plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId("destination")));person.addPlan(plan);s.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controller=new Controler(s);UnsignalizedPriority.configure(controller);controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controller.run();
        var arrivals=events.stream().filter(e->e instanceof PersonArrivalEvent).toList();System.out.println("PARALLEL_PASSAGE arrivals="+arrivals.size()+" evidence="+out);
        require(arrivals.size()==2,"Artificial mutual veto: parallel avenue heads cannot acquire their common service-return passage");
        require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Aborted native vehicle");verifyTransactions(events);
        long acquired=events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(e.getAttributes().get("action"))).count();
        long released=events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"RELEASE".equals(e.getAttributes().get("action"))).count();require(acquired==2&&released==2,"Complete passage receipts missing");
        for(var id:List.of("service-out","service-back"))require(events.stream().filter(e->e instanceof LinkEnterEvent a&&a.getLinkId().toString().equals(id)).count()==2,"A native connector was skipped");
        System.out.println("PASS native parallel passage priority: 2 arrivals, actual return traversed, complete body reservations released");
    }
    static void pureQueries() {
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();double[][] xy={{-100,0},{0,0},{0,8},{0,40},{100,0},{200,0}};
        for(int i=0;i<xy.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        link(n,"avenue","0","1",100,2);link(n,"service-out","1","2",8,1);link(n,"service-tail","2","3",32,1);link(n,"service-back-tail","3","2",32,1);link(n,"service-back","2","1",8,1);link(n,"receipt","1","4",100,2);link(n,"destination","4","5",100,2);
        LanesGenerator.build(s);var manager=EventsUtils.createEventsManager();var events=new ArrayList<Event>();manager.addHandler((BasicEventHandler)events::add);var cfg=s.getConfig().qsim();var ledger=new SimZ1CorridorOccupancy(s,Set.of(),manager);SimZ1CorridorOccupancy.install(cfg,ledger);
        var path=List.of("avenue","service-out","service-back","receipt","destination");
        var a=SimZ1PriorityLookaheadCheck.planned(s,"first",path);var b=SimZ1PriorityLookaheadCheck.planned(s,"second",path);var avenue=Id.createLinkId("avenue");var from=Id.createLinkId("service-back");var to=Id.createLinkId("receipt");
        require(ledger.activity(a,avenue,"avenue.original",0)&&ledger.activity(b,avenue,"avenue.original",0),"Parallel fixture needs two existing slots");
        require(!SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,a,b,from,to),"Original-buffer bodies are not offered terminal peers");
        require(ledger.canEnter(a,avenue,"avenue.lane.0",1)&&ledger.canEnter(b,avenue,"avenue.lane.1",1),"Fixture slots differ");ledger.enter(a,avenue,"avenue.lane.0",1,"queue_entry");ledger.progress(a,avenue,"avenue.lane.0",2);ledger.enter(b,avenue,"avenue.lane.1",1,"queue_entry");ledger.progress(b,avenue,"avenue.lane.1",2);
        int before=events.size();require(SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,a,b,from,to)&&SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,b,a,from,to),"Equivalent native entrance peers unrecognized");
        require(!SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,a,a,from,to),"Within-slot FIFO must remain authoritative");require(!SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,a,b,avenue,to),"Ordinary source movement priority changed");require(events.size()==before,"Pure comparison emitted a transaction");
        ledger.release(b.getId(),3,"native_arrival");var other=SimZ1PriorityLookaheadCheck.planned(s,"ordinary",List.of("avenue","receipt","destination"));require(ledger.activity(other,avenue,"avenue.original",3),"Ordinary peer fixture rejected");require(ledger.canEnter(other,avenue,"avenue.lane.1",4),"Ordinary peer has a distinct slot");ledger.enter(other,avenue,"avenue.lane.1",4,"queue_entry");ledger.progress(other,avenue,"avenue.lane.1",5);
        before=events.size();require(!SimZ1CorridorOccupancy.sameParallelPassageEntrance(cfg,a,other,from,to),"A different ordinary avenue movement must keep priority");require(events.size()==before,"Negative comparison changed ledger");ledger.release(a.getId(),6,"native_arrival");ledger.release(other.getId(),6,"native_arrival");SimZ1CorridorOccupancy.uninstall(cfg);
        System.out.println("PASS pure passage comparison: equivalent parallel heads only; ordinary priority, terminal readiness and per-slot FIFO preserved");
    }
}
