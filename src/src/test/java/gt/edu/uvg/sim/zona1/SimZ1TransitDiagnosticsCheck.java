package gt.edu.uvg.sim.zona1;

import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.zip.GZIPInputStream;
import org.apache.commons.csv.CSVFormat;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.vehicles.VehicleType;

/** Synthetic events only: no controller, QSim, population generator or network simulation. */
public final class SimZ1TransitDiagnosticsCheck {
    private static final Id<Link> INSIDE=Id.createLinkId("inside"), OUTSIDE=Id.createLinkId("outside");
    private static void check(boolean value,String reason) { if (!value) throw new AssertionError(reason); }
    private static void value(SimZ1TransitDiagnostics monitor,String key,String expected) {
        check(expected.equals(monitor.snapshot().get(key)),key+" expected "+expected+": "+monitor.snapshot());
    }
    private static Scenario scenario() {
        var config=ConfigUtils.createConfig(); config.qsim().setEndTime(1000);
        var scenario=ScenarioUtils.createScenario(config);
        var network=scenario.getNetwork(); var f=network.getFactory();
        for (int i=0;i<3;i++) network.addNode(f.createNode(Id.createNodeId(i),new Coord(i*100,0)));
        for (int i=0;i<2;i++) {
            var link=f.createLink(i==0?INSIDE:OUTSIDE,network.getNodes().get(Id.createNodeId(i)),network.getNodes().get(Id.createNodeId(i+1)));
            link.setLength(100); link.setFreespeed(10); link.setCapacity(1000); link.setNumberOfLanes(1); network.addLink(link);
        }
        var people=scenario.getPopulation();
        for (String id:List.of("road-1","road-2","pt_not_a_native_driver"))
            people.addPerson(people.getFactory().createPerson(Id.createPersonId(id)));
        var fleet=scenario.getTransitVehicles(); var vf=fleet.getFactory();
        var type=vf.createVehicleType(Id.create("synthetic-bus",VehicleType.class)); fleet.addVehicleType(type);
        for (String id:List.of("stable-a","stable-b")) fleet.addVehicle(vf.createVehicle(Id.createVehicleId(id),type));
        var schedule=scenario.getTransitSchedule(); var sf=schedule.getFactory();
        var line=sf.createTransitLine(Id.create("synthetic-service",TransitLine.class));
        var route=sf.createTransitRoute(Id.create("outbound",TransitRoute.class),
            RouteUtils.createLinkNetworkRouteImpl(INSIDE,OUTSIDE),List.of(),"bus");
        for (int i=0;i<4;i++) {
            var departure=sf.createDeparture(Id.create("departure-"+i,Departure.class),i*100);
            departure.setVehicleId(Id.createVehicleId(i%2==0?"stable-a":"stable-b")); route.addDeparture(departure);
        }
        line.addRoute(route); schedule.addTransitLine(line); return scenario;
    }
    private static TransitDriverStartsEvent start(double time,String driver,String bus,int departure) {
        return new TransitDriverStartsEvent(time,Id.createPersonId(driver),Id.createVehicleId(bus),
            Id.create("synthetic-service",TransitLine.class),Id.create("outbound",TransitRoute.class),Id.create("departure-"+departure,Departure.class));
    }
    private static VehicleEntersTrafficEvent enter(double time,String driver,String bus,Id<Link> link) {
        return new VehicleEntersTrafficEvent(time,Id.createPersonId(driver),link,Id.createVehicleId(bus),"car",0);
    }
    private static VehicleLeavesTrafficEvent leave(double time,String driver,String bus,Id<Link> link) {
        return new VehicleLeavesTrafficEvent(time,Id.createPersonId(driver),link,Id.createVehicleId(bus),"car",1);
    }
    private static void counters() {
        var scenario=scenario();
        var monitor=new SimZ1TransitDiagnostics(scenario,Set.of(INSIDE),"synthetic_fixture");
        value(monitor,"roadDemandPersonsN","3"); value(monitor,"configuredFleetB","2"); value(monitor,"scheduledExpeditions","4");
        monitor.handleEvent(start(0,"internal-a","stable-a",0));
        monitor.handleEvent(start(0,"internal-b","stable-b",1));
        // Driver starts are scheduled dispatch, not proof that a bus entered traffic.
        value(monitor,"activePublicVehiclesNetwork","0");
        monitor.handleEvent(enter(0,"internal-a","stable-a",INSIDE));
        monitor.handleEvent(enter(0,"internal-b","stable-b",OUTSIDE));
        value(monitor,"activePublicVehiclesNetwork","2"); value(monitor,"activePublicVehiclesInDomain","1");
        monitor.handleEvent(new LinkLeaveEvent(10,Id.createVehicleId("stable-a"),INSIDE));
        value(monitor,"activePublicVehiclesInDomain","unknown"); value(monitor,"activePublicVehiclesLocationUnknown","1");
        monitor.handleEvent(new LinkEnterEvent(10,Id.createVehicleId("stable-a"),OUTSIDE));
        value(monitor,"activePublicVehiclesInDomain","0");
        monitor.handleEvent(new LinkLeaveEvent(10,Id.createVehicleId("stable-b"),OUTSIDE));
        monitor.handleEvent(new LinkEnterEvent(10,Id.createVehicleId("stable-b"),INSIDE));
        value(monitor,"activePublicVehiclesInDomain","1");
        monitor.handleEvent(leave(30,"internal-a","stable-a",OUTSIDE));
        monitor.handleEvent(leave(30,"internal-b","stable-b",INSIDE));
        // A second expedition uses the same vehicle and driver, after terminal availability.
        monitor.handleEvent(start(100,"internal-a","stable-a",2));
        monitor.handleEvent(enter(100,"internal-a","stable-a",INSIDE));
        value(monitor,"observedInternalTransitDrivers","2"); value(monitor,"observedExpeditionStarts","3");
        value(monitor,"configuredFleetB","2"); value(monitor,"roadDemandPersonsN","3");
        monitor.handleEvent(enter(100,"internal-a","stable-a",INSIDE));
        value(monitor,"activePublicVehiclesNetwork","1"); value(monitor,"duplicateTrafficEntries","1");
        monitor.handleEvent(start(100,"internal-a","stable-a",2)); value(monitor,"duplicateDepartureStarts","1");
        monitor.handleEvent(leave(130,"internal-a","stable-a",INSIDE));
        monitor.handleEvent(leave(130,"internal-a","stable-a",INSIDE));
        value(monitor,"activePublicVehiclesNetwork","0"); value(monitor,"unmatchedTrafficLeaves","1");
        monitor.handleEvent(start(140,"road-1","stable-a",3)); value(monitor,"demandDriverIdCollisions","1");
        value(monitor,"observedInternalTransitDrivers","2");
        monitor.handleEvent(start(150,"foreign-driver","unknown-bus",3)); value(monitor,"unregisteredTransitStarts","1");
        monitor.handleEvent(enter(160,"road-1","road-vehicle",INSIDE)); value(monitor,"activePublicVehiclesNetwork","0");
        monitor.handleEvent(enter(170,"internal-a","stable-a",INSIDE));
        monitor.handleEvent(new VehicleAbortsEvent(180,Id.createVehicleId("stable-a"),INSIDE));
        value(monitor,"activePublicVehiclesNetwork","0"); value(monitor,"publicVehicleAbortEvents","1");
        monitor.reset(2); value(monitor,"iteration","2"); value(monitor,"observedInternalTransitDrivers","0");
        value(monitor,"roadDemandPersonsN","3"); value(monitor,"configuredFleetB","2");
        var unknown=new SimZ1TransitDiagnostics(scenario,null,"unknown");
        value(unknown,"activePublicVehiclesInDomain","unknown"); value(unknown,"domainCounterScope","unknown");
        var fleet=scenario.getTransitVehicles();
        fleet.addVehicle(fleet.getFactory().createVehicle(Id.createVehicleId("spare"),fleet.getVehicleTypes().values().iterator().next()));
        var withSpare=new SimZ1TransitDiagnostics(scenario,Set.of(INSIDE),"synthetic_fixture");
        value(withSpare,"roadDemandPersonsN","3"); value(withSpare,"configuredFleetB","3"); value(withSpare,"scheduledExpeditions","4");
        value(withSpare,"eventObservationBasis","registered_fleet_events_processed_at_snapshot");
        value(withSpare,"observerGuaranteesEventQueueDrain","false");
        check(withSpare.observationCompleteness("before_cleanup").contains("may_lag"),"Cleanup is not a drained total");
        scenario.getConfig().parallelEventHandling().setSynchronizeOnSimSteps(false);
        check(withSpare.observationCompleteness("after_step").contains("may_lag"),"Asynchronous delivery must disclose lag");
    }
    private static void rerouting() {
        var rerouting=new CongestionAwareRerouting(scenario());
        check(rerouting.isRegisteredTransitVehicle(Id.createVehicleId("stable-a")),"Fleet vehicle must be excluded without pt_ prefix");
        check(!rerouting.isRegisteredTransitVehicle(Id.createVehicleId("pt_ordinary_road_vehicle")),"Prefixes cannot classify transit");
        rerouting.handleEvent(new LinkEnterEvent(0,Id.createVehicleId("stable-a"),INSIDE));
        rerouting.handleEvent(new LinkLeaveEvent(100,Id.createVehicleId("stable-a"),INSIDE));
        check(Double.isNaN(rerouting.observedLinkSeconds(INSIDE,100)),"Transit dwell contaminated road observations");
        rerouting.handleEvent(new LinkEnterEvent(101,Id.createVehicleId("pt_ordinary_road_vehicle"),INSIDE));
        rerouting.handleEvent(new LinkLeaveEvent(111,Id.createVehicleId("pt_ordinary_road_vehicle"),INSIDE));
        check(rerouting.observedLinkSeconds(INSIDE,111)==10,"Road observation lost due to prefix");
    }
    private static Map<String,String> leg(String type,double time,String person) {
        return Map.of("type",type,"time",Double.toString(time),"person",person,"link",INSIDE.toString(),"legMode","car");
    }
    private static void tripTable() throws Exception {
        Path root=Files.createTempDirectory(Path.of("target"),"simz1-transit-events-");
        var exporter=new TripTableExporter(scenario(),"synthetic-events-only",null);
        exporter.begin(root,0);
        exporter.handleEvent(start(1,"native-without-prefix","stable-a",0));
        exporter.accept(leg("departure",1,"native-without-prefix"));
        exporter.handleEvent(enter(1,"native-without-prefix","stable-a",INSIDE));
        exporter.accept(leg("arrival",10,"native-without-prefix"));
        exporter.handleEvent(start(100,"native-without-prefix","stable-a",2));
        exporter.accept(leg("departure",100,"native-without-prefix"));
        exporter.handleEvent(enter(100,"native-without-prefix","stable-a",INSIDE));
        exporter.accept(leg("arrival",110,"native-without-prefix"));
        exporter.accept(leg("departure",2,"pt_not_a_native_driver"));
        exporter.accept(leg("arrival",12,"pt_not_a_native_driver"));
        boolean rejected=false;
        try { exporter.accept(leg("departure",120,"pt_unknown_road_person")); }
        catch (IllegalArgumentException expected) { rejected=true; }
        check(rejected,"An unknown road departure must still fail");
        exporter.finish();
        try (var reader=new InputStreamReader(new GZIPInputStream(Files.newInputStream(root.resolve("0.simz1-trips.csv.gz"))),StandardCharsets.UTF_8);
             var parser=CSVFormat.DEFAULT.withFirstRecordAsHeader().parse(reader)) {
            var rows=parser.getRecords(); check(rows.size()==1,"Native drivers changed Monte Carlo trip count");
            check(rows.get(0).get("person_id").equals("pt_not_a_native_driver"),"Prefix hid a real demand person");
        }
        String summary=Files.readString(root.resolve("0.simz1-trip-summary.json"));
        check(summary.contains("\"demand_persons_N\":3") && summary.contains("\"configured_public_vehicles_B\":2"),"Separate N/B missing");
        check(summary.contains("\"observed_internal_transit_drivers\":1") && summary.contains("\"TransitDriverStarts\":2"),"Native driver reuse not documented");
    }
    public static void main(String[] args) throws Exception {
        try {
            counters(); rerouting(); tripTable();
            System.out.println("PASS: synthetic transit counters, road reroute exclusion, internal-driver separation; no simulation executed");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
