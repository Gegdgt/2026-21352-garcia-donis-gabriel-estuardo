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
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.model.*;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancyCheck.*;

/** Native fork: a full red terminal must not imprison a different physical
 * slot's head in the shared original buffer. No body changes its model slot. */
public final class SimZ1ParallelOriginalFifoCheck {
    public static void main(String[] args) throws Exception {
        try {
            if(args.length==1&&args[0].equals("free-first"))run(false,true);
            else {run(true,true);run(false,true);run(true,false);}
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
    static void run(boolean blockedFirst,boolean parallel) throws Exception {
        var c=ConfigUtils.createConfig();
        var out=Files.createTempDirectory(Path.of("runtime"),"parallel-original-fifo-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);
        c.qsim().setStartTime(0);c.qsim().setEndTime(parallel?350:550);c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setRemoveStuckVehicles(false);c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.travelTimeCalculator().setSeparateModes(false);c.controler().setLinkToLinkRoutingEnabled(true);
        c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();
        double[][] xy={{-100,0},{0,0},{90,0},{190,0},{90,100},{290,0},{90,200}};
        for(int i=0;i<xy.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        link(n,"origin","0","1",100,1);link(n,"fork","1","2",90,2);
        link(n,"left","2","3",100,1);link(n,"right","2","4",100,1);
        link(n,"left-dest","3","5",100,1);link(n,"right-dest","4","6",100,1);
        n.getNodes().get(Id.createNodeId(2)).getAttributes().putAttribute("osm:highway","traffic_signals");
        LanesGenerator.build(s);
        var factory=s.getLanes().getFactory();var assignment=factory.createLanesToLinkAssignment(Id.createLinkId("fork"));
        var original=factory.createLane(Id.create("fork.original",Lane.class));original.setStartsAtMeterFromLinkEnd(90);
        original.setNumberOfRepresentedLanes(parallel?2:1);original.setCapacityVehiclesPerHour(n.getLinks().get(Id.createLinkId("fork")).getCapacity());
        for(int i=0;i<2;i++){
            var lane=factory.createLane(Id.create("fork.lane."+i,Lane.class));lane.setStartsAtMeterFromLinkEnd(5);
            lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(original.getCapacityVehiclesPerHour()/2);
            lane.addToLinkId(Id.createLinkId(i==0?"left":"right"));assignment.addLane(lane);original.addToLaneId(lane.getId());
        }
        assignment.addLane(original);s.getLanes().getLanesToLinkAssignments().put(assignment.getLinkId(),assignment);
        var signalConfig=ConfigUtils.addOrGetModule(c,SignalSystemsConfigGroup.class);signalConfig.setUseSignalSystems(true);signalConfig.setUseAmbertimes(true);
        var data=SignalUtils.createSignalsData(signalConfig);data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);
        var systemId=Id.create("2",SignalSystem.class);var systems=data.getSignalSystemsData();var groups=data.getSignalGroupsData();var controls=data.getSignalControlData();
        var system=systems.getFactory().createSignalSystemData(systemId);systems.addSignalSystemData(system);
        var controller=controls.getFactory().createSignalSystemControllerData(systemId);controller.setControllerIdentifier(Zona1FixedTimeController.ID);controls.addSignalSystemControllerData(controller);
        var plan=controls.getFactory().createSignalPlanData(Id.create("daily",SignalPlan.class));plan.setStartTime(0.);plan.setEndTime(0.);plan.setCycleTime(400);plan.setOffset(0);
        for(int i=0;i<2;i++){
            var signal=systems.getFactory().createSignalData(Id.create("signal"+i,Signal.class));signal.setLinkId(Id.createLinkId("fork"));signal.addLaneId(Id.create("fork.lane."+i,Lane.class));system.addSignalData(signal);
            var group=groups.getFactory().createSignalGroupData(systemId,Id.create("group"+i,SignalGroup.class));group.addSignalId(signal.getId());groups.addSignalGroupData(group);
            var setting=controls.getFactory().createSignalGroupSettingsData(group.getId());setting.setOnset(i==0?200:0);setting.setDropping(i==0?390:180);plan.addSignalGroupSettings(setting);
        }
        controller.addSignalPlanData(plan);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
        var f=s.getPopulation().getFactory();
        for(int i=0;i<9;i++){
            String id="actor"+i,branch=i<5?"left":"right";double length=i==5?2.1:i==7?13.5:i==8?12:4.5;
            var type=VehicleUtils.createVehicleType(Id.create(id,VehicleType.class));type.setLength(length).setPcuEquivalents(length==2.1?.25:length==13.5?3:length==12?3.5:1).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(type);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),type);s.getVehicles().addVehicle(vehicle);
            var person=f.createPerson(Id.createPersonId(id));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            int order=!blockedFirst&&i==4?5:!blockedFirst&&i==5?4:i;
            var p=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("origin"));home.setEndTime(1+15*order);p.addActivity(home);
            var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute(List.of("origin","fork",branch,branch+"-dest").stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);p.addLeg(leg);
            p.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(branch+"-dest")));person.addPlan(p);s.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controler=new Controler(s);RunZona1Simulation.configureSignals(controler);
        controler.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controler.run();
        var arrivals=new TreeMap<String,Double>();for(var e:events)if(e instanceof PersonArrivalEvent a)arrivals.put(a.getPersonId().toString(),a.getTime());
        System.out.println("ARRIVALS blockedFirst="+blockedFirst+" parallel="+parallel+" "+arrivals+" evidence="+out);
        require(arrivals.keySet().containsAll(List.of("actor5","actor6","actor7","actor8"))&&arrivals.entrySet().stream().filter(e->Set.of("actor5","actor6","actor7","actor8").contains(e.getKey())).allMatch(e->parallel?e.getValue()<180:e.getValue()>=400),
            parallel?"Artificial cross-slot FIFO: a red terminal imprisons the green physical slot in the original buffer":"Overtook in a single physical original lane");
        require(arrivals.size()==9,"Missing native arrivals");
        for(var ids:List.of(List.of(0,1,2,3,4),List.of(5,6,7,8)))
            for(int i=1;i<ids.size();i++)require(arrivals.get("actor"+ids.get(i))>arrivals.get("actor"+ids.get(i-1)),"Within-slot FIFO changed");
        require(arrivals.entrySet().stream().filter(e->Set.of("actor0","actor1","actor2","actor3","actor4").contains(e.getKey())).allMatch(e->e.getValue()>=200),"Crossed red");
        require(events.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"GO".equals(e.getAttributes().get("decision"))&&"false".equals(e.getAttributes().get("nativeHasGreen"))),"Native red crossed");
        verifyTransactions(events);require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Forced or stuck removal");
        System.out.println("PASS parallel original FIFO: nine real arrivals, both per-slot FIFO orders, red respected, unchanged slots, complete metric releases");
    }
}
