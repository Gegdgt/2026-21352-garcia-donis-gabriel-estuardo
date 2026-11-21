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

/** Isolated native five-car fork. A retained buffer actor and a travelling
 * predecessor occupy slot 0; slot 1's ordinary car must still reach its buffer.
 * All actors are PCU 1: the PCU easing shortcut cannot hide flow starvation.
 * Synthetic geometry/capacities are fixture inputs, never scenario mutations. */
public final class SimZ1OriginalTravelHeadCheck {
    public static void main(String[] args) throws Exception {
        try {
            String mode=args.length==0?"all":args[0];
            if(mode.equals("parallel")||mode.equals("all"))run(true,false,3600,4);
            if(mode.equals("single")||mode.equals("all"))run(false,false,3600,4);
            if(mode.equals("same-slot")||mode.equals("all"))run(true,true,3600,4);
            if(mode.equals("debt")||mode.equals("all"))run(true,false,900,4);
            if(mode.equals("minimal-control")||mode.equals("all"))run(true,false,3600,3);
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
    static void run(boolean parallel,boolean sameSlot,double originalCapacity,int blockedActors) throws Exception {
        int actorCount=blockedActors+1;String freeId="actor"+blockedActors;
        var c=ConfigUtils.createConfig();
        var out=Files.createTempDirectory(Path.of("runtime"),"original-travel-head-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);
        c.qsim().setPcuThresholdForFlowCapacityEasing(0);
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
        original.setNumberOfRepresentedLanes(parallel?2:1);original.setCapacityVehiclesPerHour(originalCapacity);
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
        for(int i=0;i<actorCount;i++){
            String id="actor"+i,branch=i<blockedActors||sameSlot?"left":"right";
            var type=VehicleUtils.createVehicleType(Id.create(id,VehicleType.class));
            type.setLength(4.5).setPcuEquivalents(1).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(type);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),type);s.getVehicles().addVehicle(vehicle);
            var person=f.createPerson(Id.createPersonId(id));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            var p=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("origin"));home.setEndTime(1+15*i);p.addActivity(home);
            var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute(List.of("origin","fork",branch,branch+"-dest").stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);p.addLeg(leg);
            p.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(branch+"-dest")));person.addPlan(p);s.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controler=new Controler(s);RunZona1Simulation.configureSignals(controler);
        var snapshots=new ArrayList<Map<String,Object>>();double[] previousFlow={Double.NaN,Double.NaN};
        controler.addOverridingModule(new AbstractModule(){public void install(){
            addEventHandlerBinding().toInstance((BasicEventHandler)events::add);
            addMobsimListenerBinding().toInstance((org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener)event->{
                try {
                    var qsim=(org.matsim.core.mobsim.qsim.QSim)event.getQueueSimulation();
                    var qlink=(QLinkLanesImpl)qsim.getNetsimNetwork().getNetsimLink(Id.createLinkId("fork"));
                    var originalQueue=(QueueWithBuffer)qlink.getAcceptingQLane();double now=event.getSimulationTime();
                    var accumulated=readField(originalQueue,"flowcap_accumulate");
                    double value=(double)readField(accumulated,"value");double rate=(double)readField(originalQueue,"flowCapacityPerTimeStep");
                    if(now==previousFlow[0]+1)require(value<=previousFlow[1]+rate+1e-8,"Native flow debt was forgiven or accumulated faster than its native rate");
                    previousFlow[0]=now;previousFlow[1]=value;
                    if(now==100){
                        var snapshot=new LinkedHashMap<String,Object>();snapshot.put("time",now);snapshot.put("parallel",parallel);snapshot.put("sameSlot",sameSlot);
                        snapshot.put("actorCount",actorCount);snapshot.put("originalCapacity",originalCapacity);snapshot.put("flowCreditPcu",value);snapshot.put("flowRatePcuPerStep",rate);
                        var queues=new LinkedHashMap<String,Object>();var ledger=SimZ1CorridorOccupancy.get(c.qsim());
                        for(var lane:qlink.getQueueLanes().values()){
                            var queue=(QueueWithBuffer)lane;var state=new LinkedHashMap<String,Object>();
                            var buffer=new ArrayList<Map<String,Object>>();
                            for(var pair:(Iterable<?>)readField(queue,"buffer"))buffer.add(actorState((QVehicle)((org.apache.commons.lang3.tuple.Pair<?,?>)pair).getKey(),ledger,queue));
                            var travelling=new ArrayList<Map<String,Object>>();
                            for(var actor:(Iterable<?>)readField(queue,"vehQueue"))travelling.add(actorState((QVehicle)actor,ledger,queue));
                            state.put("buffer",buffer);state.put("travelling",travelling);state.put("nativeUsedPcu",queue.getLoadIndicator());state.put("nativeCapacityPcu",queue.getStorageCapacity());
                            queues.put(queue.getId().toString(),state);
                        }
                        snapshot.put("queues",queues);snapshots.add(snapshot);
                        new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.resolve("native-snapshot-t100.json").toFile(),snapshot);
                        System.out.println("NATIVE_TRAVEL_SNAPSHOT "+snapshot);
                    }
                } catch(ReflectiveOperationException|java.io.IOException e){throw new RuntimeException(e);}
            });
        }});controler.run();
        var arrivals=new TreeMap<String,Double>();for(var e:events)if(e instanceof PersonArrivalEvent a)arrivals.put(a.getPersonId().toString(),a.getTime());
        System.out.println("TRAVEL_HEAD arrivals parallel="+parallel+" sameSlot="+sameSlot+" originalCapacity="+originalCapacity+" "+arrivals+" evidence="+out);
        Double observedFreeArrival=arrivals.get(freeId);
        double freeArrival=observedFreeArrival==null?Double.POSITIVE_INFINITY:observedFreeArrival;
        require(sameSlot?observedFreeArrival!=null&&freeArrival>=200:parallel?freeArrival<180:observedFreeArrival!=null&&freeArrival>=400,
            sameSlot?"Passed a predecessor in the same committed slot":parallel?
            "Artificial travelling cross-slot FIFO: ordinary car cannot reach the independent green lane":
            "Overtook within a single physical original lane");
        require(arrivals.size()==actorCount,"Missing native arrivals");
        require(snapshots.size()==1,"Missing atomic post-step native snapshot");
        for(int i=1;i<(sameSlot?actorCount:blockedActors);i++)require(arrivals.get("actor"+i)>arrivals.get("actor"+(i-1)),"Within-slot FIFO changed");
        require(arrivals.entrySet().stream().filter(e->!e.getKey().equals(freeId)||sameSlot).allMatch(e->e.getValue()>=200),"Crossed red");
        // Exact PCU identity and zero easing are part of the reproduction: changing
        // the independent car to a motorcycle is not a valid fix for this test.
        require(s.getVehicles().getVehicles().values().stream().allMatch(v->v.getType().getPcuEquivalents()==1),"Fixture PCU identity changed");
        require(events.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"GO".equals(e.getAttributes().get("decision"))&&"false".equals(e.getAttributes().get("nativeHasGreen"))),"Native red crossed");
        verifyTransactions(events);require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Forced or stuck removal");
        System.out.println("PASS original travelling heads: "+actorCount+" real arrivals, committed-slot FIFO, red respected, no easing, complete metric releases");
    }

    private static Object readField(Object instance,String name) throws ReflectiveOperationException {
        var field=instance.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(instance);
    }
    private static Map<String,Object> actorState(QVehicle vehicle,SimZ1CorridorOccupancy ledger,QueueWithBuffer queue){
        var row=new LinkedHashMap<String,Object>();row.put("vehicle",vehicle.getId().toString());
        row.put("committedOriginalSlot",ledger.originalSlot(vehicle,Id.createLinkId("fork"),queue.getId().toString()));
        row.put("earliestExitTime",vehicle.getEarliestLinkExitTime());row.put("pcu",vehicle.getSizeInEquivalents());
        row.put("nextLink",String.valueOf(vehicle.getDriver().chooseNextLinkId()));return row;
    }
}
