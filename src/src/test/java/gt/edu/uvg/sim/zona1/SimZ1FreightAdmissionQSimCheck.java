package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import org.apache.commons.csv.CSVFormat;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Network;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;

/** Two native QSim integrations, two actors each, on synthetic fixture roads.
 * A private leader creates ordinary flow debt at the shared origin; the freight
 * actor is scheduled inside its original nominal window. No event, movement,
 * body clearance, reservation release or terminal outcome is injected.
 * The caller must supply a NEW diagnostics directory; no massive launcher,
 * historical run, acceptance receipt or production network is touched.
 */
public final class SimZ1FreightAdmissionQSimCheck {
    private static final double PLANNED=57599,END=61220;
    private static final String TRUCK="synthetic-freight",LEADER="synthetic-leader";
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void road(Network n,String name,String from,String to,double length,double capacity) {
        var link=n.getFactory().createLink(Id.createLinkId(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        link.setLength(length);link.setFreespeed(10);link.setCapacity(capacity);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car"));n.addLink(link);
    }
    static void actor(Scenario s,boolean freight) {
        String name=freight?TRUCK:LEADER;
        var type=VehicleUtils.createVehicleType(Id.create(freight?"FreightTruck":"SyntheticLeader",VehicleType.class));
        type.setLength(freight?8:4.5).setWidth(freight?2.3:1.8).setPcuEquivalents(freight?3.5:1).setMaximumVelocity(10).setNetworkMode("car");
        if(freight){type.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);type.getAttributes().putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);}
        s.getVehicles().addVehicleType(type);var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicle(vehicle);
        var f=s.getPopulation().getFactory();var p=f.createPerson(Id.createPersonId(name));
        VehicleUtils.insertVehicleIdsIntoAttributes(p,Map.of("car",vehicle.getId()));
        var path=freight?List.of("origin","terminal"):List.of("origin","terminal","out","destination");
        var plan=f.createPlan();var origin=f.createActivityFromLinkId(freight?"freight_external":"home",Id.createLinkId("origin"));origin.setEndTime(freight?PLANNED:57590);plan.addActivity(origin);
        var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute(path.stream().map(Id::createLinkId).toList(),s.getNetwork());route.setVehicleId(vehicle.getId());leg.setRoute(route);plan.addLeg(leg);
        plan.addActivity(f.createActivityFromLinkId(freight?"freight_external":"work",Id.createLinkId(path.get(path.size()-1))));p.addPlan(plan);s.getPopulation().addPerson(p);
        if(freight) {
            var a=p.getAttributes();a.putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);a.putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);
            a.putAttribute("simz1GrossWeightTonnes",12.);a.putAttribute("simz1FreightDeparture",PLANNED);a.putAttribute("simz1FreightRoute","origin terminal");
            a.putAttribute("simz1FreightCompletionPolicy",SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY);a.putAttribute("simz1FreightAssignedWindow","[32400,57600]");
            a.putAttribute("simz1FreightGateway","{\"body_length_m\":8,\"minimum_gap_m\":0.1,\"entry_distance_from_route_start_m\":30,\"exit_distance_from_route_start_m\":160,\"route_link_start_m\":{\"origin\":0,\"terminal\":100}}");
        }
    }
    static Map<String,Object> run(Path directory,boolean expires)throws Exception {
        Files.createDirectory(directory);
        var c=ConfigUtils.createConfig();c.controler().setOutputDirectory(directory.resolve("output").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);c.qsim().setRemoveStuckVehicles(false);
        c.qsim().setStartTime(57580);c.qsim().setEndTime(END-1);c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        c.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.parallelEventHandling().setNumberOfThreads(2);c.parallelEventHandling().setSynchronizeOnSimSteps(true);
        c.travelTimeCalculator().setSeparateModes(false);c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var a=new ActivityParams(name);a.setTypicalDuration(3600);a.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(a);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        admission.setOriginPolicy("physical-gap-origin-v1");
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();double[] x={-100,0,90,190,290};
        for(int i=0;i<x.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(x[i],0)));
        double originCapacity=expires?.5:2.;
        road(n,"origin","0","1",100,originCapacity);road(n,"terminal","1","2",90,2000);road(n,"out","2","3",100,2000);road(n,"destination","3","4",100,2000);
        // Split the body domains at the origin exit; flow debt remains native.
        n.getNodes().get(Id.createNodeId(1)).getAttributes().putAttribute("osm:highway","stop");
        LanesGenerator.build(s);
        // The final activity's original endpoint can provide a real 8.1m rear
        // clearance past the synthetic perimeter at route coordinate 160m.
        var lf=s.getLanes().getFactory();var assignment=lf.createLanesToLinkAssignment(Id.createLinkId("terminal"));
        var original=lf.createLane(Id.create("terminal.original",Lane.class));original.setStartsAtMeterFromLinkEnd(90);original.setNumberOfRepresentedLanes(1);original.setCapacityVehiclesPerHour(2000);
        var tail=lf.createLane(Id.create("terminal.lane.0",Lane.class));tail.setStartsAtMeterFromLinkEnd(5);tail.setNumberOfRepresentedLanes(1);tail.setCapacityVehiclesPerHour(2000);tail.addToLinkId(Id.createLinkId("out"));
        assignment.addLane(tail);original.addToLaneId(tail.getId());assignment.addLane(original);s.getLanes().getLanesToLinkAssignments().put(assignment.getLinkId(),assignment);
        var signalConfig=ConfigUtils.addOrGetModule(c,SignalSystemsConfigGroup.class);signalConfig.setUseSignalSystems(true);signalConfig.setUseAmbertimes(true);
        s.addScenarioElement(SignalsData.ELEMENT_NAME,SignalUtils.createSignalsData(signalConfig));
        actor(s,false);actor(s,true);SimZ1Freight.configure(s);
        var events=new ArrayList<Event>();var ctl=new Controler(s);RunZona1Simulation.configureSignals(ctl);SimZ1Freight.install(ctl);
        ctl.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});
        boolean incompleteRejected=false;
        try {ctl.run();}
        catch(RuntimeException failure) {
            for(Throwable cause=failure;cause!=null;cause=cause.getCause())if(String.valueOf(cause.getMessage()).contains("FREIGHT_NOT_APPROVED"))incompleteRejected=true;
            if(!expires||!incompleteRejected)throw failure;
        }
        check(incompleteRejected==expires,"Wrong native completion/rejection result");
        var truckEvents=events.stream().filter(e->TRUCK.equals(e.getAttributes().getOrDefault("person",e.getAttributes().get("vehicle")))).toList();
        var entries=truckEvents.stream().filter(e->e instanceof VehicleEntersTrafficEvent).toList();
        var arrivals=truckEvents.stream().filter(e->e instanceof PersonArrivalEvent).toList();
        var denied=truckEvents.stream().filter(e->e.getEventType().equals("simz1FreightAdmissionRejected")).toList();
        var aborts=truckEvents.stream().filter(e->Set.of("stuckAndAbort","vehicle aborts").contains(e.getEventType())).toList();
        check(truckEvents.stream().filter(e->e instanceof PersonDepartureEvent).count()==1,"Missing/duplicated native freight departure");
        check(aborts.stream().noneMatch(e->e.getTime()<END),"Truck removed before normal QSim cleanup");
        check(events.stream().noneMatch(e->e instanceof PersonStuckEvent&&e.getTime()<END),"Actor forced out before cutoff");
        Path report=directory.resolve("output/ITERS/it.0/0.simz1-freight-audit.csv");
        Map<String,String> audit;
        try(var reader=Files.newBufferedReader(report);var csv=CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {
            var rows=csv.getRecords();check(rows.size()==1,"Freight audit fleet changed");audit=rows.get(0).toMap();
        }
        check(audit.get("completion_policy").equals(SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY),"Auditor lost v2 policy");
        check(audit.get("completion_deadline_inclusive").equals("61200.0"),"Completion limit extended after entry");
        if(expires) {
            check(entries.isEmpty()&&arrivals.isEmpty(),"Expired actor entered/arrived");
            check(denied.size()==1&&denied.get(0).getTime()==61201,"Missing or repeated native expiry evidence");
            check(denied.get(0).getAttributes().get("reason").equals("assigned_entry_deadline_expired"),"Wrong native rejection reason");
            check(!aborts.isEmpty(),"Expected normal cleanup terminal evidence missing");
            check(truckEvents.stream().noneMatch(e->e.getEventType().equals("simz1OccupancyReservation")&&"ENTER".equals(e.getAttributes().get("action"))),"Expired actor acquired a body reservation");
            check(audit.get("traffic_entry").isEmpty()&&audit.get("arrival").isEmpty()&&audit.get("body_clearance_proof").isEmpty(),"Audit manufactured movement/clearance");
            check(audit.get("admission_status").equals("authorization_expired_not_admitted")&&audit.get("completion_classification").equals("pending_not_evaluable"),"Expired actor wrongly accepted");
        } else {
            check(entries.size()==1&&entries.get(0).getTime()>=57600&&entries.get(0).getTime()<=61200,"Expected one tolerated native entry");
            check(arrivals.size()==1&&arrivals.get(0).getTime()<=61200,"Native completion exceeded unchanged deadline");
            check(denied.isEmpty()&&aborts.isEmpty(),"Authorized completed freight was denied/aborted");
            check(audit.get("completion_classification").equals("tolerated")&&audit.get("body_clearance_proof").contains("rear_plus_gap_clearance_m"),"Missing real native clearance/tolerated result");
        }
        var result=new LinkedHashMap<String,Object>();result.put("status","PASS");result.put("fixture",expires?"expired_origin_retained":"tolerated_entry_and_native_clearance");
        result.put("actors",2);result.put("native_start_seconds",57580);result.put("native_physical_end_seconds",END);result.put("synthetic_origin_capacity_veh_per_hour",originCapacity);
        result.put("scheduled_departure",PLANNED);result.put("entry_times",entries.stream().map(Event::getTime).toList());result.put("arrival_times",arrivals.stream().map(Event::getTime).toList());
        result.put("rejection_times",denied.stream().map(Event::getTime).toList());result.put("cleanup_abort_times",aborts.stream().map(Event::getTime).toList());result.put("freight_audit",audit);
        new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(directory.resolve("result.json").toFile(),result);
        return result;
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("Supply one NEW diagnostics directory");
        var directory=Path.of(args[0]).toAbsolutePath();if(Files.exists(directory))throw new IllegalArgumentException("Diagnostics directory must not exist");Files.createDirectory(directory);
        try {
            var results=List.of(run(directory.resolve("tolerated"),false),run(directory.resolve("expired"),true));
            new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(directory.resolve("result.json").toFile(),Map.of("status","PASS","native_qsim_fixtures",results));
            System.out.println("SIMZ1_FREIGHT_ADMISSION_QSIM_OK: "+directory);
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
