package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;
import static gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow.Feasibility.*;

/** Exact historical inputs, production candidate search, no successor edits. */
public final class SimZ1TemporalRouteCheck {
    static void check(boolean value,String message) { if(!value)throw new AssertionError(message); }
    public static void main(String[] args)throws Exception {
        try {run(Path.of(args[0]),Path.of(args[1]));} finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
    static void run(Path evidence,Path output)throws Exception {
        var json=new ObjectMapper();var input=json.readTree(evidence.resolve("signal_fixture_input.json").toFile());
        var run=Path.of(input.path("run").asText());
        var cfg=ConfigUtils.createConfig(new SignalSystemsConfigGroup(),new SimZ1AdmissionConfigGroup());
        cfg.setContext(run.resolve("config.xml").toUri().toURL());cfg.qsim().setUseLanes(true);
        ConfigUtils.addOrGetModule(cfg,SimZ1AdmissionConfigGroup.class).setWholeVehicleReservation(true);
        var sc=ConfigUtils.addOrGetModule(cfg,SignalSystemsConfigGroup.class);sc.setUseSignalSystems(true);sc.setUseAmbertimes(true);
        sc.setSignalSystemFile(run.resolve("inputs/signalsystems-signalsystems.xml").toString());
        sc.setSignalGroupsFile(run.resolve("inputs/signalsystems-signalgroups.xml").toString());
        sc.setSignalControlFile(run.resolve("inputs/signalsystems-signalcontrol.xml").toString());
        cfg.network().setInputFile(run.resolve("inputs/transit-weekday/network.xml").toString());
        cfg.network().setLaneDefinitionsFile(run.resolve("inputs/transit-weekday/lanes.xml").toString());
        var s=ScenarioUtils.createScenario(cfg);new MatsimNetworkReader(s.getNetwork()).readFile(cfg.network().getInputFile());
        new LanesReader(s).readFile(cfg.network().getLaneDefinitionsFile());
        s.addScenarioElement(SignalsData.ELEMENT_NAME,new SignalsDataLoader(cfg).loadSignalsData());
        var p=s.getPopulation().getFactory().createPerson(Id.createPersonId(input.path("vehicle").asText()));
        input.path("attributes").fields().forEachRemaining(a->p.getAttributes().putAttribute(a.getKey(),a.getValue().asText()));
        s.getPopulation().addPerson(p);
        var old=SimZ1TripOd.ids(input.path("path"));int at=input.path("currentIndex").asInt();
        var lane=Id.create(old.get(at)+".lane.0",Lane.class);
        var leg=s.getPopulation().getFactory().createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(old,s.getNetwork()));
        leg.getAttributes().putAttribute("simz1TripId",json.readTree(input.path("attributes").path("simz1Trips").asText()).get(0).path("id").asText());
        var type=VehicleUtils.createVehicleType(Id.create("Normal",VehicleType.class));
        type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(13.88888888888889).setNetworkMode("car");
        var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(p.getId()),type);
        s.getVehicles().addVehicleType(type);s.getVehicles().addVehicle(vehicle);
        p.getAttributes().removeAttribute("vehicles"); // JSON fixture strings are not MATSim's native PersonVehicles object.
        VehicleUtils.insertVehicleIdsIntoAttributes(p,Map.of("car",vehicle.getId()));
        var safety=new SimZ1RouteSafety(s);var contract=safety.tripOd().forLeg(p,leg);
        var before=safety.temporal(old,at,p,vehicle,lane,true);
        check(before.status()==IMPOSSIBLE,"Exact car passage must be proved impossible: "+before);
        var router=new SimZ1TurnRouter(s.getNetwork(),safety,(l,t,person,v)->l.getLength()/l.getFreespeed(t));
        var prepared=CongestionAwareRerouting.candidate(safety,router,p,leg,at,old.get(at),lane,1729,vehicle,1696,List.copyOf(old.subList(0,at+1)));
        check(prepared.issue()==null,"Production search failed: "+prepared.issue());
        check(prepared.route().subList(0,at+1).equals(old.subList(0,at+1)),"Occurrence prefix changed");
        check(!prepared.route().get(at+1).equals(old.get(at+1)),"Returned to same impossible first passage");
        check(safety.validateReplacement(old,prepared.route(),at,old.get(at),old.get(old.size()-1),lane,contract)==null,"OD/OSM/current lane invalid");
        var after=safety.temporal(prepared.route(),at,p,vehicle,lane,true);
        check(after.status()==COMPATIBLE,"Alternative full temporal audit: "+after);
        check(safety.temporal(old,at,p,null,lane,true).status()==IMPOSSIBLE,"Standard routing must resolve the person's physical vehicle");
        var factory=s.getPopulation().getFactory();var plan=factory.createPlan();p.addPlan(plan);
        var origin=factory.createActivityFromLinkId("home",old.get(0));origin.setEndTime(0);plan.addActivity(origin);
        ((org.matsim.core.population.routes.NetworkRoute)leg.getRoute()).setVehicleId(vehicle.getId());plan.addLeg(leg);
        plan.addActivity(factory.createActivityFromLinkId("work",old.get(old.size()-1)));
        var standard=ExperiencedTimeRouting.sequenceRouting(s,(l,t,person,v)->Double.NaN,null,DrivingProfiles.FASTEST_TIME);
        var tripRouter=new org.matsim.core.router.TripRouter.Builder(cfg).setRoutingModule("car",standard).build();
        new org.matsim.core.replanning.modules.ReRoute(s,()->tripRouter,org.matsim.core.utils.timing.TimeInterpretation.create(cfg)).getPlanAlgoInstance().run(plan);
        var standardLeg=(org.matsim.api.core.v01.population.Leg)plan.getPlanElements().get(1);
        var standardRoute=(org.matsim.core.population.routes.NetworkRoute)standardLeg.getRoute();
        check(safety.temporal(SimZ1RouteSafety.full(standardRoute),0,p,null,null,true).status()==COMPATIBLE,"Standard ReRoute retained an impossible passage");
        check(contract.validate(SimZ1RouteSafety.full(standardRoute))==null&&vehicle.getId().equals(standardRoute.getVehicleId()),"Standard ReRoute changed OD/vehicle identity");
        var windows=new Zona1SignalGreenWindow(s);
        var requirements=List.of(new Zona1SignalGreenWindow.Requirement(old.get(at),lane,old.get(at+1),0,true),
            new Zona1SignalGreenWindow.Requirement(old.get(at+1),Id.create(old.get(at+1)+".lane.0",Lane.class),old.get(at+2),4,false));
        check(windows.feasibility(requirements,1)==IMPOSSIBLE,"Distinct controllers lost");
        check(windows.feasibility(requirements,Math.sqrt(2))==UNKNOWN,"Partial period must not prove impossible");
        check(windows.feasibility(List.of(requirements.get(0)),1)==COMPATIBLE,"Temporary red is not impossible");
        check(windows.feasibility(List.of(new Zona1SignalGreenWindow.Requirement(old.get(at+1),requirements.get(1).lane(),old.get(at+2),100,false)),1)==IMPOSSIBLE,"Insufficient clearance window");
        check(windows.feasibility(List.of(new Zona1SignalGreenWindow.Requirement(old.get(at+1),null,old.get(at+2),4,false)),1)==UNKNOWN,"Unresolved controlled lane must be unknown");
        var data=(SignalsData)s.getScenarioElement(SignalsData.ELEMENT_NAME);
        var shiftedPlan=data.getSignalControlData().getSignalSystemControllerDataBySystemId().get(
            Id.create("333531372",org.matsim.contrib.signals.model.SignalSystem.class)).getSignalPlanData().values().iterator().next();
        int oldOffset=shiftedPlan.getOffset();shiftedPlan.setOffset(40);
        check(windows.feasibility(requirements,1)==COMPATIBLE,"Offset change/cache identity ignored");
        shiftedPlan.setOffset(oldOffset);
        check(windows.feasibility(requirements,1)==IMPOSSIBLE,"Original effective phases not restored");
        type.setLength(2.1);
        check(safety.temporal(old,at,p,vehicle,lane,true).status()==COMPATIBLE,"Motorcycle has an intermediate stopping place");
        type.setLength(4.5);
        Files.createDirectories(output);
        json.writerWithDefaultPrettyPrinter().writeValue(output.resolve("route-result.json").toFile(),Map.of(
            "scope","production temporal detection and candidate; installation/movement tested separately",
            "old",old.stream().map(Object::toString).toList(),"candidate",prepared.route().stream().map(Object::toString).toList(),
            "index",at,"old_status",before.status(),"candidate_status",after.status(),
            "old_cost",router.evaluate(old.subList(at,old.size()),1729,p,vehicle,1696).cost(),
            "candidate_cost",router.evaluate(prepared.suffix(),1729,p,vehicle,1696).cost()));
        // Fixed services are audited with their saved dimensions and complete
        // routes. They are never passed to the private repair search.
        new org.matsim.pt.transitSchedule.api.TransitScheduleReader(s).readFile(run.resolve("inputs/transit-weekday/transitSchedule.xml").toString());
        new MatsimVehicleReader(s.getTransitVehicles()).readFile(run.resolve("inputs/transit-weekday/transitVehicles.xml").toString());
        var geometry=org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancy.temporalGeometry(s);
        var services=new ArrayList<Map<String,Object>>();int incompatibleBuses=0;
        for(var line:s.getTransitSchedule().getTransitLines().values())for(var service:line.getRoutes().values()) {
            var dimensions=new HashSet<VehicleType>();
            for(var departure:service.getDepartures().values())dimensions.add(s.getTransitVehicles().getVehicles().get(departure.getVehicleId()).getType());
            for(var dimensionsType:dimensions) {
                var fixed=SimZ1RouteSafety.full(service.getRoute());
                var outcome=geometry.temporalRoute(fixed,0,dimensionsType.getLength(),dimensionsType.getMaximumVelocity(),null,true);
                if(outcome.status()==IMPOSSIBLE){incompatibleBuses++;check(service.getId().toString().equals("L18_6245758_part1"),"Unexpected fixed service incompatibility: "+service.getId());}
                services.add(Map.of("class","bus","route",service.getId().toString(),"body_m",dimensionsType.getLength(),"speed_mps",dimensionsType.getMaximumVelocity(),"status",outcome.status(),"reason",outcome.reason(),"stops",service.getStops().size(),"expeditions",service.getDepartures().size()));
            }
        }
        check(incompatibleBuses==1,"Must retain the demonstrated fixed L18 scenario incompatibility");
        var freight=json.readTree(run.resolve("inputs/freight-weekday/routes.json").toFile());
        for(var service:freight.path("routes")) {
            var outcome=geometry.temporalRoute(SimZ1TripOd.ids(service.path("link_ids")),0,8.,40./3.6,null,true);
            check(outcome.status()==COMPATIBLE,"Fixed compact freight temporal check: "+outcome);
            services.add(Map.of("class","freight","route",service.path("route_id").asText(),"body_m",8.,"speed_mps",40./3.6,"status",outcome.status(),"reason",outcome.reason()));
        }
        json.writerWithDefaultPrettyPrinter().writeValue(output.resolve("fixed-service-java.json").toFile(),services);
        System.out.println("PASS temporal production candidate: "+prepared.route().size()+" links; OD/OSM/prefix preserved");
    }
}
