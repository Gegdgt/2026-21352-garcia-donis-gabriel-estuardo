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

/** Reproduces the premature arrival of freight_000155: a final-link original
 * queue can finish before earlier bodies in its terminal permit its modeled
 * front to reach that queue's endpoint. Synthetic isolated geometry only;
 * signals, actors and capacities of the massive experiment are not edited. */
public final class SimZ1ArrivalClearanceCheck {
    public static void main(String[] args) throws Exception {
        try {
            if(args.length==1&&args[0].equals("--fixed-day-only")) {
                run(false,false,true,true,86399);run(false,false,true,true,86383);
            } else {pureQueries(); run(true,false); run(false,false); run(true,true); run(false,false,true);}
        }
        finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
    static void pureQueries() throws Exception {
        try(var f=new SimZ1StorageFixture(SimZ1StorageFixture.PROFILES.get(0),false)){
            var actor=f.actor("query-truck",8,"receipt-a","dest-a");f.seed(actor,".lane.0",0);
            String before=SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger);int count=f.events.size();
            for(int i=0;i<240;i++)require(!f.ledger.arrivalReady(actor.vehicle,Id.createLinkId("receipt-a"),"receipt-a.lane.0"),"Early arrival query accepted before native endpoint");
            require(before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger))&&count==f.events.size(),"Failed arrival query mutated state/events");
            f.ready(f.queue("receipt-a",".lane.0"),100);before=SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger);count=f.events.size();
            for(int i=0;i<240;i++)require(f.ledger.arrivalReady(actor.vehicle,Id.createLinkId("receipt-a"),"receipt-a.lane.0"),"Actual native endpoint not recognized");
            require(before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger))&&count==f.events.size(),"Successful arrival query mutated state/events");f.safety();
        }
    }
    static void run(boolean leaders,boolean parallel) throws Exception {
        run(leaders,parallel,false);
    }
    static void run(boolean leaders,boolean parallel,boolean experimentalFreight) throws Exception {
        run(leaders,parallel,experimentalFreight,false,86399);
    }
    static void run(boolean leaders,boolean parallel,boolean experimentalFreight,boolean fixedDay,double plannedDeparture) throws Exception {
        var out=Files.createTempDirectory(Path.of("runtime"),"native-arrival-clearance-");
        var c=ConfigUtils.createConfig();c.controler().setOutputDirectory(out.resolve("run").toString());
        c.controler().setLastIteration(0);c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);
        c.qsim().setUseLanes(true);c.qsim().setStartTime(0);c.qsim().setEndTime(200);
        if(experimentalFreight){c.qsim().setStartTime(86390);c.qsim().setEndTime(108000);}
        if(fixedDay){c.qsim().setStartTime(86370);c.qsim().setEndTime(86399);c.controler().setLastIteration(1);
            c.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
            c.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
            var observation=new org.matsim.core.config.ConfigGroup("simz1Observation");observation.addParam("policy",SimZ1DayObservation.POLICY);c.addModule(observation);}
        c.qsim().setUsingFastCapacityUpdate(false);c.qsim().setRemoveStuckVehicles(false);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.travelTimeCalculator().setSeparateModes(false);c.controler().setLinkToLinkRoutingEnabled(true);
        c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var a=new ActivityParams(name);a.setTypicalDuration(3600);a.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(a);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();double[][] xy={{-100,0},{0,0},{90,0},{190,0},{90,100},{290,0},{90,200}};
        for(int i=0;i<xy.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        link(n,"origin","0","1",100,1);link(n,"terminal","1","2",90,parallel?2:1);
        link(n,"out","2","3",100,1);link(n,"side","2","4",100,1);link(n,"destination","3","5",100,1);
        link(n,"side-destination","4","6",100,1);
        // Separate the activity-origin domain: new activities may not insert
        // into an occupied domain, whereas real upstream traffic may queue.
        n.getNodes().get(Id.createNodeId(1)).getAttributes().putAttribute("osm:highway","stop");
        n.getNodes().get(Id.createNodeId(2)).getAttributes().putAttribute("osm:highway","traffic_signals");
        LanesGenerator.build(s);
        var f=s.getLanes().getFactory();var assignment=f.createLanesToLinkAssignment(Id.createLinkId("terminal"));
        var original=f.createLane(Id.create("terminal.original",Lane.class));original.setStartsAtMeterFromLinkEnd(90);
        original.setNumberOfRepresentedLanes(parallel?2:1);original.setCapacityVehiclesPerHour(parallel?4000:2000);
        for(int slot=0;slot<(parallel?2:1);slot++){
            var lane=f.createLane(Id.create("terminal.lane."+slot,Lane.class));lane.setStartsAtMeterFromLinkEnd(5);
            lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(2000);lane.addToLinkId(Id.createLinkId(slot==0?"out":"side"));
            if(!parallel)lane.addToLinkId(Id.createLinkId("side"));assignment.addLane(lane);original.addToLaneId(lane.getId());
        }
        assignment.addLane(original);s.getLanes().getLanesToLinkAssignments().put(assignment.getLinkId(),assignment);
        var sc=ConfigUtils.addOrGetModule(c,SignalSystemsConfigGroup.class);sc.setUseSignalSystems(true);sc.setUseAmbertimes(true);
        var data=SignalUtils.createSignalsData(sc);data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);
        var systemId=Id.create("2",SignalSystem.class);var systems=data.getSignalSystemsData();var groups=data.getSignalGroupsData();var controls=data.getSignalControlData();
        var system=systems.getFactory().createSignalSystemData(systemId);systems.addSignalSystemData(system);
        var controller=controls.getFactory().createSignalSystemControllerData(systemId);controller.setControllerIdentifier(Zona1FixedTimeController.ID);controls.addSignalSystemControllerData(controller);
        var plan=controls.getFactory().createSignalPlanData(Id.create("daily",SignalPlan.class));plan.setStartTime(0.);plan.setEndTime(0.);plan.setCycleTime(200);plan.setOffset(0);
        for(int slot=0;slot<(parallel?2:1);slot++){
            var signal=systems.getFactory().createSignalData(Id.create("signal"+slot,Signal.class));signal.setLinkId(Id.createLinkId("terminal"));signal.addLaneId(Id.create("terminal.lane."+slot,Lane.class));system.addSignalData(signal);
            var group=groups.getFactory().createSignalGroupData(systemId,Id.create("group"+slot,SignalGroup.class));group.addSignalId(signal.getId());groups.addSignalGroupData(group);
            var setting=controls.getFactory().createSignalGroupSettingsData(group.getId());setting.setOnset(slot==0?100:82);setting.setDropping(190);plan.addSignalGroupSettings(setting);
        }
        controller.addSignalPlanData(plan);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
        int truckIndex=parallel?6:2;
        for(int i=leaders?0:truckIndex;i<(parallel?8:3);i++){
            boolean truck=i==truckIndex,independent=parallel&&i==7,right=parallel&&i>=2&&!truck;
            String name=truck?"truck":independent?"independent":"moto"+i;double body=truck?8:independent?4.5:2.1;
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(body).setWidth(truck?2.3:independent?1.8:.8).setPcuEquivalents(truck?3.5:independent?1:.25).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(type);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicle(vehicle);
            var pf=s.getPopulation().getFactory();var person=pf.createPerson(Id.createPersonId(name));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            var p=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("origin"));home.setEndTime(experimentalFreight?plannedDeparture:1+4*i);p.addActivity(home);
            var path=truck?List.of("origin","terminal"):List.of("origin","terminal",right?"side":"out",right?"side-destination":"destination");
            var leg=pf.createLeg("car");var route=RouteUtils.createNetworkRoute(path.stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);p.addLeg(leg);
            p.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId(path.get(path.size()-1))));person.addPlan(p);s.getPopulation().addPerson(person);
            if(truck&&experimentalFreight) {
                var a=person.getAttributes();a.putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
                a.putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);
                a.putAttribute("simz1FreightDeparture",plannedDeparture);a.putAttribute("simz1FreightRoute","origin terminal");
                a.putAttribute("simz1FreightCompletionPolicy","freight-close-plus3600-v1");
                a.putAttribute("simz1FreightAssignedWindow","[75600,104400]");
                a.putAttribute("simz1FreightGateway","{\"body_length_m\":8,\"minimum_gap_m\":0.1,\"entry_distance_from_route_start_m\":30,\"exit_distance_from_route_start_m\":160,\"route_link_start_m\":{\"origin\":0,\"terminal\":100}}");
            }
        }
        var events=new ArrayList<Event>();var ctl=new Controler(s);RunZona1Simulation.configureSignals(ctl);
        if(fixedDay)SimZ1DayObservation.install(ctl);
        if(experimentalFreight)SimZ1Freight.install(ctl);
        ctl.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});ctl.run();
        var fronts=new HashMap<String,Map<String,String>>();var arrivals=new TreeMap<String,Double>();var departures=new TreeMap<String,Double>();
        Map<String,String> arrivalProof=null;double truckEntry=Double.NaN;
        for(var e:events){var a=e.getAttributes();String vehicle=a.get("vehicle");
            if(e.getEventType().equals("simz1OccupancyProgress"))fronts.put(vehicle,a);
            if(e instanceof LinkEnterEvent enter&&enter.getVehicleId().toString().equals("truck")&&enter.getLinkId().toString().equals("terminal"))truckEntry=e.getTime();
            if(e instanceof LinkLeaveEvent leave&&leave.getLinkId().toString().equals("terminal"))departures.put(leave.getVehicleId().toString(),e.getTime());
            if(e instanceof VehicleLeavesTrafficEvent leave&&leave.getVehicleId().toString().equals("truck"))arrivalProof=fronts.get("truck");
            if(e instanceof PersonArrivalEvent aev)arrivals.put(aev.getPersonId().toString(),e.getTime());
        }
        Files.writeString(out.resolve("proof.txt"),"leaders="+leaders+"\nparallel="+parallel+"\narrivals="+arrivals+"\nterminalDepartures="+departures+"\ntruckEntry="+truckEntry+"\narrivalProof="+arrivalProof+"\n");
        System.out.println("ARRIVAL CLEARANCE evidence="+out+" arrivals="+arrivals+" proof="+arrivalProof);
        if(fixedDay) {
            var physical=Set.of("departure","arrival","vehicle enters traffic","vehicle leaves traffic","entered link","left link","entered lane","left lane");
            require(events.stream().noneMatch(e->physical.contains(e.getEventType())&&e.getTime()>86400),"Physical event beyond cutoff");
            require(events.stream().filter(e->e.getEventType().equals("simz1DayCut")&&e.getTime()==86400).count()==2,"Missing cut or iteration reset");
            for(int it=0;it<2;it++) {
                var file=out.resolve("run/ITERS/it."+it+"/"+it+".simz1-day-census.jsonl.gz");
                try(var input=new java.util.zip.GZIPInputStream(Files.newInputStream(file))) {
                    String census=new String(input.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
                    require(census.contains("\"iteration\":"+it),"Iteration identity leaked");
                    require(census.contains(plannedDeparture==86399?"\"status\":\"active_at_cut\"":"\"status\":\"completed\""),"Unexpected day census: "+census);
                    if(plannedDeparture==86399)require(census.contains("\"arrival\":null"),"Censoring invented arrival");
                }
            }
            require(plannedDeparture==86399?arrivals.isEmpty():arrivals.get("truck")==86400,"Real arrival exactly at T is not retained");
            System.out.println("FIXED DAY PASS two iterations, one freight expedition each; planned="+plannedDeparture+" cutoff=86400; "+out);
            return;
        }
        require(arrivals.size()==(parallel?8:leaders?3:1)&&arrivalProof!=null,"Missing real native arrivals; "+out);
        require(Double.parseDouble(arrivalProof.get("modeledFrontLowerBoundMeters"))+1e-8>=Double.parseDouble(arrivalProof.get("nativeFrontBoundMeters")),"PREMATURE_NATIVE_ARRIVAL: leader still bounds final queue position; "+out);
        require(leaders?arrivals.get("truck")>=departures.get("moto1"):arrivals.get("truck")<(experimentalFreight?86500:100),"Body clearance ignored or clear terminal activity incorrectly waits for a signal it does not cross");
        if(parallel)require(truckEntry<82&&departures.get("independent")<100,"Pending arrival imprisoned an independent physical slot; "+out);
        require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Abort/forced removal");
        require(events.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"GO".equals(e.getAttributes().get("decision"))&&"false".equals(e.getAttributes().get("nativeHasGreen"))),"Crossed red");
        verifyTransactions(events);
        if(experimentalFreight) {
            require(arrivals.get("truck")>86400&&arrivals.get("truck")<=108000,"Night journey was clipped to demand midnight");
            String audit=Files.readString(out.resolve("run/ITERS/it.0/0.simz1-freight-audit.csv"));
            require(audit.contains("freight-close-plus3600-v1")&&audit.contains("nominal")&&audit.contains("rear_plus_gap_clearance_m"),"Native freight completion proof absent");
        }
        System.out.println("PASS arrival waits for native body progress; FIFO, unchanged dimensions/gap, all reservations released");
    }
}
