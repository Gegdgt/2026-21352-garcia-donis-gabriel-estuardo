package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;
import org.matsim.lanes.*;
import gt.edu.uvg.sim.zona1.*;

/** Regression for z1_143187: downstream displacement must use downstream
 * conflict geometry. Uses the exact small OSM fragment; never changes it. */
public final class SimZ1CrossingClearanceCheck {
    private static final String IN="osm_381144595_2_forward", OUT="osm_381144595_3_forward";
    private static final String SERVICE="osm_1305258446_0_forward", RETURN="osm_1305258446_0_backward";
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Id<Link> id(String value){return Id.createLinkId(value);}

    private static Scenario scenario(){
        var source=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimNetworkReader(source.getNetwork()).readFile("scenarios/zona1/network.xml");
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        var network=scenario.getNetwork();var factory=network.getFactory();
        var wanted=new ArrayList<String>();
        for(int i=1;i<=4;i++)wanted.add("osm_381144595_"+i+"_forward");
        for(int i=0;i<=3;i++)for(String direction:List.of("forward","backward"))wanted.add("osm_1305258446_"+i+"_"+direction);
        for(String direction:List.of("forward","backward"))wanted.add("osm_1305258447_0_"+direction);
        for(String name:wanted){
            var old=source.getNetwork().getLinks().get(id(name));require(old!=null,"Fixture source link missing: "+name);
            for(var node:List.of(old.getFromNode(),old.getToNode()))if(!network.getNodes().containsKey(node.getId()))
                network.addNode(factory.createNode(node.getId(),node.getCoord()));
            var link=factory.createLink(old.getId(),network.getNodes().get(old.getFromNode().getId()),network.getNodes().get(old.getToNode().getId()));
            link.setLength(old.getLength());link.setFreespeed(old.getFreespeed());link.setCapacity(old.getCapacity());
            link.setNumberOfLanes(old.getNumberOfLanes());link.setAllowedModes(Set.of("car","bus"));network.addLink(link);
        }
        // Straight extension only beyond the retained Avenue fragment. It
        // supplies an ordinary destination after the reproduced junction.
        var last=network.getLinks().get(id("osm_381144595_4_forward"));
        var from=last.getToNode();var a=last.getFromNode().getCoord();var b=from.getCoord();
        double norm=Math.hypot(b.getX()-a.getX(),b.getY()-a.getY());
        var destination=factory.createNode(Id.createNodeId("fixture-destination"),new Coord(
            b.getX()+80*(b.getX()-a.getX())/norm,b.getY()+80*(b.getY()-a.getY())/norm));network.addNode(destination);
        var extension=factory.createLink(id("fixture-destination"),from,destination);
        extension.setLength(80);extension.setFreespeed(last.getFreespeed());extension.setCapacity(last.getCapacity());
        extension.setNumberOfLanes(1);extension.setAllowedModes(Set.of("car","bus"));network.addLink(extension);
        return scenario;
    }

    static void exactMotorcycleReturn() throws Exception {
        var scenario=scenario();var config=scenario.getConfig();
        var out=Files.createTempDirectory(Path.of("runtime/diagnostics/circulation-fixes-20261030"),"crossing-clearance-");
        config.controler().setOutputDirectory(out.resolve("run").toString());config.controler().setLastIteration(0);
        config.global().setNumberOfThreads(1);config.qsim().setNumberOfThreads(1);config.qsim().setUseLanes(true);
        config.qsim().setStartTime(0);config.qsim().setEndTime(120);config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);config.qsim().setRemoveStuckVehicles(false);
        config.travelTimeCalculator().setSeparateModes(false);config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);config.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var vf=scenario.getVehicles().getFactory();var type=vf.createVehicleType(Id.create("motorcycle",VehicleType.class));
        type.setLength(2.1).setWidth(.8).setPcuEquivalents(.25).setMaximumVelocity(10).setNetworkMode("car");scenario.getVehicles().addVehicleType(type);
        var vehicle=vf.createVehicle(Id.createVehicleId("z1_143187_fixture"),type);scenario.getVehicles().addVehicle(vehicle);
        var factory=scenario.getPopulation().getFactory();var person=factory.createPerson(Id.createPersonId(vehicle.getId().toString()));
        VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
        var path=List.of("osm_381144595_1_forward",IN,SERVICE,RETURN,OUT,"osm_381144595_4_forward","fixture-destination");
        var plan=factory.createPlan();var home=factory.createActivityFromLinkId("home",id(path.get(0)));home.setEndTime(1);plan.addActivity(home);
        var leg=factory.createLeg("car");var route=RouteUtils.createNetworkRoute(path.stream().map(SimZ1CrossingClearanceCheck::id).toList(),scenario.getNetwork());
        route.setVehicleId(vehicle.getId());leg.setRoute(route);plan.addLeg(leg);plan.addActivity(factory.createActivityFromLinkId("work",id(path.get(path.size()-1))));
        person.addPlan(plan);scenario.getPopulation().addPerson(person);LanesGenerator.build(scenario);
        var observed=new ArrayList<Event>();var controller=new Controler(scenario);UnsignalizedPriority.configure(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)observed::add);}});
        controller.run();
        var domain=observed.stream().filter(e->e.getEventType().equals("simz1OccupancyDomain")&&SERVICE.equals(e.getAttributes().get("link"))).findFirst().orElseThrow().getAttributes();
        double capacity=Double.parseDouble(domain.get("laneCapacityMeters"));
        require(Math.abs(capacity-4.430330303869269)<1e-7,"Exact historical receiver capacity changed: "+capacity);
        long arrivals=observed.stream().filter(e->e instanceof PersonArrivalEvent).count();
        long aborts=observed.stream().filter(e->e instanceof PersonStuckEvent).count();
        var entered=observed.stream().filter(e->e instanceof LinkEnterEvent).map(e->((LinkEnterEvent)e).getLinkId().toString()).toList();
        Files.writeString(out.resolve("proof.txt"),"receiverCapacityMeters="+capacity+"\narrivals="+arrivals+"\naborts="+aborts+"\nentered="+entered+"\n");
        System.out.println("Crossing clearance exact OSM fixture: arrivals="+arrivals+", aborts="+aborts+", evidence="+out);
        require(entered.contains(SERVICE),"Fixture did not reproduce entry to the short service corridor");
        require(arrivals==1&&aborts==0,"Admitted motorcycle cannot clear its own crossing and finish its legal return: "+entered);
        require(entered.equals(path.subList(1,path.size())),"Return path changed or vehicle skipped a native link: "+entered);
        require(observed.stream().noneMatch(e->"FORCE".equals(e.getAttributes().get("decision"))),"Forced admission bypassed physical reservation");
        SimZ1CorridorOccupancyCheck.verifyTransactions(observed);
    }

    static void bodyAndTimeAreBothRequired() {
        for(double body:new double[]{2.1,4.5,12,13.5}) {
            var scenario=SimZ1CorridorOccupancyCheck.scenario();
            var assignment=scenario.getLanes().getFactory().createLanesToLinkAssignment(id("out"));
            double clearance=body+SimZ1CorridorOccupancy.GAP+1.5,epsilon=1e-5;
            var lf=scenario.getLanes().getFactory();
            var before=Id.create("before",Lane.class);var exact=Id.create("exact",Lane.class);var after=Id.create("after",Lane.class);
            LanesUtils.createAndAddLane(assignment,lf,before,10000,40,0,1,null,List.of(exact));
            LanesUtils.createAndAddLane(assignment,lf,exact,10000,40-clearance+epsilon,0,1,null,List.of(after));
            LanesUtils.createAndAddLane(assignment,lf,after,10000,40-clearance,0,1,List.of(id("destination")),null);
            scenario.getLanes().addLanesToLinkAssignment(assignment);
            var manager=EventsUtils.createEventsManager();var observed=new ArrayList<Event>();manager.addHandler((BasicEventHandler)observed::add);
            var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);
            var vehicle=SimZ1CorridorOccupancyCheck.vehicle("body-"+body,body);
            require(Math.abs(ledger.entryClearanceDistance(vehicle,id("out"))-clearance)<1e-9,"Downstream-axis width projection changed");
            require(ledger.canEnter(vehicle,id("out"),"before",0),"Ordinary receiving corridor lacks body space");
            ledger.enter(vehicle,id("out"),"before",0,"queue_entry");
            String corridor=ledger.corridorId(id("out"));
            require(!ledger.crossingCleared(vehicle.getId(),corridor,clearance,1.5,1000),"Elapsed time released an unmoved body");
            ledger.progress(vehicle,id("out"),"before",1000);
            require(!ledger.crossingCleared(vehicle.getId(),corridor,clearance,1.5,1000),"Crossing released before tail plus gap cleared the conflict width");
            ledger.enter(vehicle,id("out"),"exact",1000,"queue_entry");ledger.progress(vehicle,id("out"),"exact",1001);
            require(!ledger.crossingCleared(vehicle.getId(),corridor,clearance,1001.5,1001),"Complete body release ignored minimum crossing time");
            require(ledger.crossingCleared(vehicle.getId(),corridor,clearance,1001.5,1001.5),"Exact clearance with elapsed time was not released");
            ledger.release(vehicle.getId(),1002,"arrival");SimZ1CorridorOccupancyCheck.verifyTransactions(observed);
        }
        // Unchanged exact short domain cannot absorb a larger body merely
        // because the crossing-axis inconsistency was corrected.
        var scenario=scenario();var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),EventsUtils.createEventsManager());
        for(double body:new double[]{4.5,12,13.5})require(!ledger.canEnter(SimZ1CorridorOccupancyCheck.vehicle("oversize-"+body,body),id(SERVICE),"",0),
            "Larger body admitted into the unchanged 4.430m receiver without a full passage");
    }

    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();Files.createDirectories(Path.of("runtime/diagnostics/circulation-fixes-20261030"));
        bodyAndTimeAreBothRequired();
        exactMotorcycleReturn();
        System.out.println("PASS crossing clearance: admitted 2.1m motorcycle clears exact asymmetric intersection; return and arrival preserved");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
