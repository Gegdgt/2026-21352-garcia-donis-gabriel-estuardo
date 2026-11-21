package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.utils.objectattributes.attributable.Attributable;
import org.matsim.vehicles.VehicleType;

/** Small synthetic object checks. main never constructs Controler or QSim. */
public final class SimZ1TransitFleetCheck {
    private static void attr(Attributable item, String key, Object value) {
        item.getAttributes().putAttribute("simz1:"+key, value.toString());
    }
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void rejected(Runnable action, String cause) {
        try { action.run(); }
        catch (IllegalArgumentException error) {
            require(error.getMessage().contains(cause), "wrong failure: "+error); return;
        }
        throw new AssertionError("accepted invalid case: "+cause);
    }
    static Scenario fixture() {
        var config=ConfigUtils.createConfig(); config.transit().setUseTransit(true);
        config.qsim().setRemoveStuckVehicles(false);
        var scenario=ScenarioUtils.createScenario(config); var network=scenario.getNetwork(); var nf=network.getFactory();
        for (int i=0;i<4;i++) network.addNode(nf.createNode(Id.createNodeId(i), new Coord(i%2*50,i/2*50)));
        String[] ids={"a_terminal","a_to_b","b_terminal","b_to_a"};
        for (int i=0;i<4;i++) {
            var link=nf.createLink(Id.createLinkId(ids[i]),network.getNodes().get(Id.createNodeId(i)),network.getNodes().get(Id.createNodeId((i+1)%4)));
            link.setLength(50); link.setFreespeed(10); link.setCapacity(1800); link.setNumberOfLanes(1); link.setAllowedModes(Set.of("car","bus")); network.addLink(link);
        }
        var pf=scenario.getPopulation().getFactory();
        for(int i=0;i<3;i++) scenario.getPopulation().addPerson(pf.createPerson(Id.createPersonId("synthetic-road-"+i)));
        var schedule=scenario.getTransitSchedule();
        var metadata=Map.ofEntries(Map.entry("fleetSchema","fixed-fleet-v1"),Map.entry("scenarioVersion","synthetic-fixed-fleet-v1"),
            Map.entry("serviceDate","2026-10-22"),Map.entry("purpose","synthetic_fixture"),Map.entry("passengersModeled","false"),
            Map.entry("minimumTurnPolicy","reject_on_actual_violation"),Map.entry("domainApproved","false"),Map.entry("domainSynthetic","true"),
            Map.entry("domainSource","synthetic local topology; not Zona 1 cartography"),Map.entry("domainLinks",String.join(" ",ids)),
            Map.entry("monteCarloPersons","3"),Map.entry("configuredFleetSize","2"),Map.entry("scheduledExpeditions","4"));
        metadata.forEach((k,v)->attr(schedule,k,v));
        var vehicles=scenario.getTransitVehicles();var vf=vehicles.getFactory();
        var type=vf.createVehicleType(Id.create("synthetic-bus",VehicleType.class));
        type.setNetworkMode("bus").setLength(12).setWidth(2.5).setPcuEquivalents(2.5).setMaximumVelocity(10);
        type.getCapacity().setSeats(20);type.getCapacity().setStandingRoom(0);vehicles.addVehicleType(type);
        for(int i=1;i<=2;i++) vehicles.addVehicle(vf.createVehicle(Id.createVehicleId("synthetic-bus-"+i),type));
        var sf=schedule.getFactory();
        for(String name:List.of("a_terminal","b_terminal")) {
            var link=network.getLinks().get(Id.createLinkId(name));
            var stop=sf.createTransitStopFacility(Id.create(name,TransitStopFacility.class),link.getToNode().getCoord(),false);
            stop.setLinkId(link.getId()); attr(stop,"stopPlacement","bay");attr(stop,"dwellBasis","explicit_scenario_assumption");attr(stop,"dwellSeconds",10);
            schedule.addStopFacility(stop);
        }
        var line=sf.createTransitLine(Id.create("synthetic-service",TransitLine.class));
        attr(line,"serviceId","synthetic-service");attr(line,"productionEnabled",false);
        attr(line,"assignedVehicleIds","synthetic-bus-1 synthetic-bus-2");schedule.addTransitLine(line);
        addRoute(scenario,line,"ida",List.of(ids[0],ids[1],ids[2]),0);
        addRoute(scenario,line,"vuelta",List.of(ids[2],ids[3],ids[0]),160);
        return scenario;
    }
    private static void addRoute(Scenario scenario,TransitLine line,String name,List<String> links,int firstDeparture) {
        var schedule=scenario.getTransitSchedule();var factory=schedule.getFactory();
        var net=RouteUtils.createLinkNetworkRouteImpl(Id.createLinkId(links.get(0)),Id.createLinkId(links.get(2)));
        net.setLinkIds(net.getStartLinkId(),List.of(Id.createLinkId(links.get(1))),net.getEndLinkId());
        var first=factory.createTransitRouteStop(schedule.getFacilities().get(Id.create(links.get(0),TransitStopFacility.class)),0,10);
        var last=factory.createTransitRouteStop(schedule.getFacilities().get(Id.create(links.get(2),TransitStopFacility.class)),100,110);
        first.setAwaitDepartureTime(true);last.setAwaitDepartureTime(true);
        var route=factory.createTransitRoute(Id.create(name,TransitRoute.class),net,List.of(first,last),"bus");
        attr(route,"routePolicy","fixed-v1");attr(route,"runningWay","mixed");line.addRoute(route);
        for(int i=1;i<=2;i++) {
            var departure=factory.createDeparture(Id.create(name+"-"+i,Departure.class),firstDeparture+(i-1)*30);
            departure.setVehicleId(Id.createVehicleId("synthetic-bus-"+i));attr(departure,"endTimeSeconds",departure.getDepartureTime()+110);
            attr(departure,"terminalSeconds",20);attr(departure,"turnaroundSeconds",10);route.addDeparture(departure);
        }
    }
    private static TransitRoute route(Scenario scenario,String name) {
        return scenario.getTransitSchedule().getTransitLines().values().iterator().next().getRoutes().get(Id.create(name,TransitRoute.class));
    }
    private static TransitDriverStartsEvent start(SimZ1TransitFleet.Duty duty,double time,String bus) {
        return new TransitDriverStartsEvent(time,Id.createPersonId("driver-"+bus),Id.createVehicleId(bus),
            duty.line().getId(),duty.route().getId(),duty.departure().getId());
    }
    public static void main(String[] args) throws Exception {
        var mapper=new com.fasterxml.jackson.databind.ObjectMapper();
        String enabledCatalog="""
            {"production_enabled":true,"domain":{"approved":true,"link_ids":["a"]},
             "services":[{"service_id":"fixture-verified-only-for-unit-check","production_enabled":true,
               "verification":{"status":"verified","blockers":[]}}]}
            """;
        var enabled=mapper.readTree(enabledCatalog);var selected=Set.of("fixture-verified-only-for-unit-check");
        SimZ1TransitFleet.validateCatalogDocument(enabled,Set.of("a"),selected);
        var disabled=mapper.readTree("{\"production_enabled\":false}");
        rejected(()->SimZ1TransitFleet.validateCatalogDocument(disabled,Set.of("a"),selected),"production is disabled");
        rejected(()->SimZ1TransitFleet.validateCatalogDocument(enabled,Set.of("other"),selected),"domain differs");
        rejected(()->SimZ1TransitFleet.validateCatalogDocument(enabled,Set.of("a"),Set.of("unregistered")),"not enabled");
        var unresolved=mapper.readTree(enabledCatalog.replace("\"blockers\":[]","\"blockers\":[\"pending timetable\"]"));
        rejected(()->SimZ1TransitFleet.validateCatalogDocument(unresolved,Set.of("a"),selected),"unverified or blocked");
        var scenario=fixture(); var prepared=SimZ1TransitFleet.validate(scenario);
        require(prepared.roadPersonsN()==3 && prepared.configuredFleetB()==2 && prepared.scheduledExpeditions()==4,"N/B/expeditions conflated");
        var blocks=SimZ1TransitFleet.buildUmlaeufe(scenario,prepared);
        require(blocks.size()==2 && blocks.stream().allMatch(b->b.getUmlaufStuecke().size()==2 && b.getUmlaufStuecke().stream().allMatch(p->p.isFahrt())),"bus duplication or implicit deadhead");
        var reserves=scenario.getTransitVehicles();
        reserves.addVehicle(reserves.getFactory().createVehicle(Id.createVehicleId("synthetic-reserve"),reserves.getVehicleTypes().values().iterator().next()));
        attr(scenario.getTransitSchedule(),"configuredFleetSize",3);
        attr(scenario.getTransitSchedule().getTransitLines().values().iterator().next(),"assignedVehicleIds","synthetic-bus-1 synthetic-bus-2 synthetic-reserve");
        var withReserve=SimZ1TransitFleet.validate(scenario);
        require(withReserve.roadPersonsN()==3 && withReserve.configuredFleetB()==3 && withReserve.scheduledExpeditions()==4 &&
            SimZ1TransitFleet.buildUmlaeufe(scenario,withReserve).size()==2,"reserve changed N or created scheduled driver");
        var missing=fixture();missing.getTransitVehicles().removeVehicle(Id.createVehicleId("synthetic-bus-2"));attr(missing.getTransitSchedule(),"configuredFleetSize",1);
        rejected(()->SimZ1TransitFleet.validate(missing),"unconfigured bus");
        var overlap=fixture();route(overlap,"ida").getDepartures().values().forEach(d->attr(d,"terminalSeconds",100));
        rejected(()->SimZ1TransitFleet.validate(overlap),"overlapping duty");
        var gap=fixture();route(gap,"vuelta").getRoute().setStartLinkId(Id.createLinkId("a_terminal"));
        rejected(()->SimZ1TransitFleet.validate(gap),"disconnected");
        var exterior=fixture();attr(exterior.getTransitSchedule(),"domainLinks","a_terminal a_to_b b_terminal");
        rejected(()->SimZ1TransitFleet.validate(exterior),"blocked_exterior_runtime_not_implemented");
        var reversed=fixture();route(reversed,"ida").getStops().get(0).setStopFacility(reversed.getTransitSchedule().getFacilities().get(Id.create("b_terminal",TransitStopFacility.class)));
        rejected(()->SimZ1TransitFleet.validate(reversed),"consecutive stops");
        var wrongCount=fixture();attr(wrongCount.getTransitSchedule(),"monteCarloPersons",5);
        rejected(()->SimZ1TransitFleet.validate(wrongCount),"monteCarloPersons");
        var unversioned=fixture();unversioned.getTransitSchedule().getAttributes().removeAttribute("simz1:fleetSchema");
        rejected(()->SimZ1TransitFleet.validate(unversioned),"fleetSchema");
        var unassigned=fixture();attr(unassigned.getTransitSchedule().getTransitLines().values().iterator().next(),"assignedVehicleIds","synthetic-bus-1");
        rejected(()->SimZ1TransitFleet.validate(unassigned),"not assigned to its service");
        var forbiddenMode=fixture();forbiddenMode.getNetwork().getLinks().get(Id.createLinkId("a_to_b")).setAllowedModes(Set.of("car"));
        rejected(()->SimZ1TransitFleet.validate(forbiddenMode),"missing bus access");
        var fakeSegregation=fixture();attr(route(fakeSegregation,"ida"),"runningWay","segregated");
        rejected(()->SimZ1TransitFleet.validate(fakeSegregation),"separate bus-only links");
        var wide=fixture();var stops=wide.getTransitSchedule();
        var old=stops.getFacilities().get(Id.create("a_terminal",TransitStopFacility.class));
        var blocking=stops.getFactory().createTransitStopFacility(old.getId(),old.getCoord(),true);blocking.setLinkId(old.getLinkId());
        attr(blocking,"stopPlacement","in_lane");attr(blocking,"dwellBasis","explicit_scenario_assumption");attr(blocking,"dwellSeconds",10);
        stops.removeStopFacility(old);stops.addStopFacility(blocking);
        for(var line:stops.getTransitLines().values()) for(var r:line.getRoutes().values()) for(var stopVisit:r.getStops())
            if(stopVisit.getStopFacility()==old) stopVisit.setStopFacility(blocking);
        wide.getNetwork().getLinks().get(old.getLinkId()).setNumberOfLanes(2);
        rejected(()->SimZ1TransitFleet.validate(wide),"unsupported_multilane_in_lane_stop");
        var guard=new SimZ1TransitFleet.AvailabilityGuard(prepared);var duty=prepared.duties().get(Id.createVehicleId("synthetic-bus-1"));
        guard.handleEvent(start(duty.get(0),0,"synthetic-bus-1"));
        rejected(()->guard.handleEvent(start(duty.get(1),160,"synthetic-bus-1")),"unavailable");
        guard.handleEvent(new PersonArrivalEvent(150,Id.createPersonId("driver-synthetic-bus-1"),Id.createLinkId("b_terminal"),"car"));
        rejected(()->guard.handleEvent(start(duty.get(1),160,"synthetic-bus-1")),"actual_terminal_or_return_time_violation");
        guard.handleEvent(start(duty.get(1),180,"synthetic-bus-1"));
        guard.handleEvent(new PersonArrivalEvent(300,Id.createPersonId("driver-synthetic-bus-1"),Id.createLinkId("a_terminal"),"car"));
        rejected(()->guard.handleEvent(start(duty.get(1),400,"synthetic-bus-1")),"unavailable");
        var dwell=new SimZ1TransitFleet.AssumedDwell();var stop=scenario.getTransitSchedule().getFacilities().values().iterator().next();
        require(dwell.handleTransitStop(stop,700,List.of(),List.of(),null,null)==1,"late arrival skipped minimum dwell");
        require(dwell.handleTransitStop(stop,709,List.of(),List.of(),null,null)==1,"dwell ended early");
        require(dwell.handleTransitStop(stop,710,List.of(),List.of(),null,null)==0,"dwell never ends");
        require(dwell.handleTransitStop(stop,750,List.of(),List.of(),null,null)==0,"scheduled wait restarts dwell");
        dwell.departed(stop.getId());require(dwell.handleTransitStop(stop,800,List.of(),List.of(),null,null)==1,"repeated stop did not start new dwell");
        System.out.println("PASS: synthetic fixed fleet API checks; no Controler or QSim was run");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
