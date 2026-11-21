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

/** Three receivers form a closed ring only because their shared originals
 * imprison the independent exit-slot heads. No saved network is modified. */
public final class SimZ1ParallelOriginalRingCheck {
    public static void main(String[] args) throws Exception {
        try { run(); } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
    static void run() throws Exception {
        var c=ConfigUtils.createConfig();var out=Files.createTempDirectory(Path.of("runtime"),"parallel-original-ring-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);
        c.qsim().setStartTime(0);c.qsim().setEndTime(350);c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setRemoveStuckVehicles(false);c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.travelTimeCalculator().setSeparateModes(false);c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();double[][] xy={{0,0},{33,0},{16.5,33*Math.sqrt(3)/2}};
        for(int i=0;i<3;i++){
            var node=n.getFactory().createNode(Id.createNodeId("n"+i),new Coord(xy[i][0],xy[i][1]));node.getAttributes().putAttribute("osm:highway","traffic_signals");n.addNode(node);
        }
        for(int i=0;i<3;i++){
            int j=(i+1)%3;double dx=(xy[j][0]-xy[i][0])/33,dy=(xy[j][1]-xy[i][1])/33;
            n.addNode(n.getFactory().createNode(Id.createNodeId("o"+i),new Coord(xy[i][0]-20*dx,xy[i][1]-20*dy)));
            n.addNode(n.getFactory().createNode(Id.createNodeId("e"+i),new Coord(xy[j][0]+100*dx,xy[j][1]+100*dy)));
            n.addNode(n.getFactory().createNode(Id.createNodeId("d"+i),new Coord(xy[j][0]+200*dx,xy[j][1]+200*dy)));
            link(n,"origin"+i,"o"+i,"n"+i,20,1);link(n,"ring"+i,"n"+i,"n"+j,33,2);
            link(n,"exit"+i,"n"+j,"e"+i,100,1);link(n,"dest"+i,"e"+i,"d"+i,100,1);
        }
        LanesGenerator.build(s);var lf=s.getLanes().getFactory();
        for(int i=0;i<3;i++){
            String id="ring"+i;var assignment=lf.createLanesToLinkAssignment(Id.createLinkId(id));
            var original=lf.createLane(Id.create(id+".original",Lane.class));original.setStartsAtMeterFromLinkEnd(33);original.setNumberOfRepresentedLanes(2);original.setCapacityVehiclesPerHour(10000);
            for(int k=0;k<2;k++){
                var lane=lf.createLane(Id.create(id+".lane."+k,Lane.class));lane.setStartsAtMeterFromLinkEnd(5);lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(5000);
                lane.addToLinkId(Id.createLinkId("exit"+i));if(k==0)lane.addToLinkId(Id.createLinkId("ring"+(i+1)%3));
                assignment.addLane(lane);original.addToLaneId(lane.getId());
            }
            assignment.addLane(original);s.getLanes().getLanesToLinkAssignments().put(assignment.getLinkId(),assignment);
        }
        var sc=ConfigUtils.addOrGetModule(c,SignalSystemsConfigGroup.class);sc.setUseSignalSystems(true);sc.setUseAmbertimes(true);
        var data=SignalUtils.createSignalsData(sc);data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);
        var systems=data.getSignalSystemsData();var groups=data.getSignalGroupsData();var controls=data.getSignalControlData();
        for(int i=0;i<3;i++){
            var systemId=Id.create("n"+i,SignalSystem.class);var system=systems.getFactory().createSignalSystemData(systemId);systems.addSignalSystemData(system);
            var controller=controls.getFactory().createSignalSystemControllerData(systemId);controller.setControllerIdentifier(Zona1FixedTimeController.ID);controls.addSignalSystemControllerData(controller);
            var plan=controls.getFactory().createSignalPlanData(Id.create("daily",SignalPlan.class));plan.setStartTime(0.);plan.setEndTime(0.);plan.setCycleTime(400);plan.setOffset(0);
            for(int k=0;k<2;k++){
                String incoming=k==0?"origin"+i:"ring"+(i+2)%3;
                var signal=systems.getFactory().createSignalData(Id.create(incoming,Signal.class));signal.setLinkId(Id.createLinkId(incoming));
                for(var lane:s.getLanes().getLanesToLinkAssignments().get(signal.getLinkId()).getLanes().values())if(lane.getToLinkIds()!=null&&!lane.getToLinkIds().isEmpty())signal.addLaneId(lane.getId());
                system.addSignalData(signal);var group=groups.getFactory().createSignalGroupData(systemId,Id.create(incoming,SignalGroup.class));group.addSignalId(signal.getId());groups.addSignalGroupData(group);
                var setting=controls.getFactory().createSignalGroupSettingsData(group.getId());setting.setOnset(k==0?0:160);setting.setDropping(k==0?150:390);plan.addSignalGroupSettings(setting);
            }
            controller.addSignalPlanData(plan);
        }
        s.addScenarioElement(SignalsData.ELEMENT_NAME,data);var f=s.getPopulation().getFactory();
        for(int i=0;i<3;i++)for(int j=0;j<15;j++){
            String id="actor"+i+"_"+j;boolean car=j<5;int exit=car?(i+1)%3:i;
            var type=VehicleUtils.createVehicleType(Id.create(id,VehicleType.class));type.setLength(car?4.5:2.1).setPcuEquivalents(car?1:.25).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(type);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),type);s.getVehicles().addVehicle(vehicle);var person=f.createPerson(Id.createPersonId(id));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            var p=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("origin"+i));home.setEndTime(1+6*j);p.addActivity(home);
            var path=new ArrayList<>(List.of("origin"+i,"ring"+i));if(car)path.add("ring"+(i+1)%3);path.add("exit"+exit);path.add("dest"+exit);
            var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute(path.stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);p.addLeg(leg);
            p.addActivity(f.createActivityFromLinkId("work",Id.createLinkId("dest"+exit)));person.addPlan(p);s.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controler=new Controler(s);RunZona1Simulation.configureSignals(controler);
        controler.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controler.run();
        var loaded=new HashSet<Id<Vehicle>>();for(var e:events)if(e instanceof LinkEnterEvent l&&l.getTime()<150&&l.getLinkId().toString().startsWith("ring"))loaded.add(l.getVehicleId());
        long arrivals=events.stream().filter(e->e instanceof PersonArrivalEvent).count();
        System.out.println("RING loaded="+loaded.size()+" arrivals="+arrivals+" evidence="+out);
        require(loaded.size()==45,"Fixture must load all bodies before opening the ring");
        require(arrivals==45,"Artificial shared-original ring: independent exit heads cannot unload the three receivers");
        verifyTransactions(events);require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Forced/stuck removal");
        require(events.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"GO".equals(e.getAttributes().get("decision"))&&"false".equals(e.getAttributes().get("nativeHasGreen"))),"Red crossing");
        System.out.println("PASS native three-receiver ring: 45 real arrivals, no slot changes, no overlap in ledger, complete releases, native signals retained");
    }
}
