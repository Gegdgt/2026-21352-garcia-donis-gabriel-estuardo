package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.handler.BasicEventHandler;

/** Isolated native one-duty fixture, using the ORIGINAL full L18 route, stops,
 * departure and bus dimensions. Not a reduced production experiment. */
public final class SimZ1L18NativeTripCheck {
    static void require(boolean value,String why){if(!value)throw new AssertionError(why);}
    public static void main(String[] args)throws Exception {
        try{run(Path.of(args[0]),Path.of(args[1]),Path.of(args[2]));}
        finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
    static void run(Path historical,Path signalControl,Path output)throws Exception {
        var config=RunZona1Simulation.loadConfiguration(historical.resolve("config-simz1.xml").toString());
        config.plans().setInputFile(null);config.facilities().setInputFile(null);config.vehicles().setVehiclesFile(null);
        config.controler().setFirstIteration(0);config.controler().setLastIteration(0);
        config.controler().setOutputDirectory(output.toAbsolutePath().toString());
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.failIfDirectoryExists);
        config.controler().setRunId("l18-native-fixture");
        config.qsim().setNumberOfThreads(1);config.qsim().setRemoveStuckVehicles(false);
        var signals=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);
        signals.setSignalControlFile(signalControl.toAbsolutePath().toString());
        var scenario=ScenarioUtils.loadScenario(config);
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME,new SignalsDataLoader(config).loadSignalsData());
        var line=scenario.getTransitSchedule().getTransitLines().get(Id.create("transmetro_L18",org.matsim.pt.transitSchedule.api.TransitLine.class));
        var route=line.getRoutes().get(Id.create("L18_6245758_part1",org.matsim.pt.transitSchedule.api.TransitRoute.class));
        var departure=route.getDepartures().values().stream().min(Comparator.comparingDouble(org.matsim.pt.transitSchedule.api.Departure::getDepartureTime)).orElseThrow();
        var vehicle=scenario.getTransitVehicles().getVehicles().get(departure.getVehicleId());
        require(vehicle.getType().getLength()==13.5,"Changed bus body");
        var path=SimZ1RouteSafety.full(route.getRoute());
        var geometry=org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancy.temporalGeometry(scenario);
        var audits=new ArrayList<Map<String,Object>>();
        for(var fixedLine:scenario.getTransitSchedule().getTransitLines().values())for(var fixed:fixedLine.getRoutes().values()) {
            var dep=fixed.getDepartures().values().iterator().next();var dimensions=scenario.getTransitVehicles().getVehicles().get(dep.getVehicleId()).getType();
            var result=geometry.temporalRoute(SimZ1RouteSafety.full(fixed.getRoute()),0,dimensions.getLength(),dimensions.getMaximumVelocity(),null,true);
            require(result.status()==Zona1SignalGreenWindow.Feasibility.COMPATIBLE,"Fixed public route incompatible: "+fixed.getId());
            audits.add(Map.of("route",fixed.getId().toString(),"status",result.status(),"body_m",dimensions.getLength()));
        }
        var json=new com.fasterxml.jackson.databind.ObjectMapper();
        var localAudits=new ArrayList<Map<String,Object>>();
        var policy=json.readTree(signalControl.resolveSibling("l18-local-v1.json").toFile());
        for(var constraint:policy.path("local"))for(var witness:constraint.path("witnesses")) {
            var links=new ArrayList<Id<Link>>();for(var link:witness.path("path"))links.add(Id.createLinkId(link.asText()));
            var lane=Id.create(witness.path("source_lane").asText(),org.matsim.lanes.Lane.class);
            var result=geometry.temporalRoute(links,0,witness.path("body").asDouble(),witness.path("speed").asDouble(),lane,false);
            require(result.status()==Zona1SignalGreenWindow.Feasibility.COMPATIBLE,"Local physical witness incompatible: "+witness);
            localAudits.add(Map.of("path",links.stream().map(Object::toString).toList(),"lane",lane.toString(),"body",witness.path("body").asDouble(),"speed",witness.path("speed").asDouble(),"status",result.status()));
        }
        for(var fixed:json.readTree(historical.resolve("inputs/freight-weekday/routes.json").toFile()).path("routes")) {
            var links=new ArrayList<Id<Link>>();for(var link:fixed.path("link_ids"))links.add(Id.createLinkId(link.asText()));
            var result=geometry.temporalRoute(links,0,8.,40/3.6,null,true);
            require(result.status()==Zona1SignalGreenWindow.Feasibility.COMPATIBLE,"Fixed freight route incompatible");
            audits.add(Map.of("route",fixed.path("route_id").asText(),"status",result.status(),"body_m",8.));
        }
        require(path.contains(Id.createLinkId("osm_420138103_0_forward")),"Missing fixed connector");
        config.qsim().setStartTime(departure.getDepartureTime()-1);config.qsim().setEndTime(departure.getDepartureTime()+3600);
        var duty=new SimZ1TransitFleet.Duty(line,route,departure,departure.getDepartureTime()+route.getStops().get(route.getStops().size()-1).getDepartureOffset().seconds(),0,0);
        var prepared=new SimZ1TransitFleet.Prepared(0,1,1,Set.copyOf(path),"computational_network",Map.of(vehicle.getId(),List.of(duty)));
        var events=new ArrayList<Map<String,String>>();
        var controler=new Controler(scenario);
        SimZ1TransitFleet.install(controler,prepared);RunZona1Simulation.configureSignals(controler);
        controler.addOverridingModule(new AbstractModule(){public void install(){
            addEventHandlerBinding().toInstance((BasicEventHandler)e->{var a=e.getAttributes();if(a.containsValue(vehicle.getId().toString()))events.add(new LinkedHashMap<>(a));});
        }});
        controler.run();
        Files.writeString(output.resolve("fixed-service-java.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(audits));
        Files.writeString(output.resolve("local-movements-java.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(localAudits));
        Files.writeString(output.resolve("l18-events.json"),new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(events));
        require(events.stream().noneMatch(e->"vehicle aborts".equals(e.get("type"))),"Native bus aborted");
        for(String link:List.of("osm_420120098_2_forward","osm_420138103_0_forward","osm_1056730555_0_forward"))
            require(events.stream().anyMatch(e->"entered link".equals(e.get("type"))&&link.equals(e.get("link"))),"Bus did not traverse "+link);
        require(events.stream().anyMatch(e->"simz1OccupancyPassage".equals(e.get("type"))&&"RELEASE".equals(e.get("action"))),"No native body passage release");
        var release=events.stream().filter(e->"simz1OccupancyPassage".equals(e.get("type"))&&"RELEASE".equals(e.get("action"))&&"osm_420138103_0_forward".equals(e.get("passageLinks"))).findFirst().orElseThrow();
        require("body_clearance".equals(release.get("reason"))&&Double.parseDouble(release.get("time"))>=Double.parseDouble(release.get("minimumReleaseTime")),"Affected passage released without physical clearance");
        require(events.stream().anyMatch(e->"vehicle leaves traffic".equals(e.get("type"))),"Full L18 duty did not arrive");
        String stop="gis_station_6_L18_6245758_part1";
        var arrival=events.stream().filter(e->"VehicleArrivesAtFacility".equals(e.get("type"))&&stop.equals(e.get("facility"))).findFirst().orElseThrow();
        var leaving=events.stream().filter(e->"VehicleDepartsAtFacility".equals(e.get("type"))&&stop.equals(e.get("facility"))).findFirst().orElseThrow();
        require(Double.parseDouble(leaving.get("time"))-Double.parseDouble(arrival.get("time"))>=25,"Nearby configured dwell lost");
        Files.writeString(output.resolve("result.json"),new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(Map.of(
            "status","PASS_native_full_L18_duty","scope","one original duty fixture; not 180000 approval","vehicle",vehicle.getId().toString(),
            "departure",departure.getDepartureTime(),"body_m",13.5,"original_route_links",path.size(),"nearby_stop_dwell_preserved",true)));
        System.out.println("PASS full native L18 duty, nearby stop and bodily passage release");
    }
}
