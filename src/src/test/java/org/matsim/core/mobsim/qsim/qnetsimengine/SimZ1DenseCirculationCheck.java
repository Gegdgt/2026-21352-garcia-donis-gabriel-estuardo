package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.NetworkWriter;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.vehicles.*;
import gt.edu.uvg.sim.zona1.*;

/** Bounded density experiments. Run explicitly only after the real Run1000 passes.
 * Same geometry, 2000 PCU/h/lane, storage factors, signal plan and mixed body
 * sizes at every demand level. Burst demand is a synthetic stress fixture,
 * never a capacity claim for Zona 1 and never a replacement for its 269 buses. */
public final class SimZ1DenseCirculationCheck {
    private static final double END = 43200;
    private static final List<String> PATH = List.of("origin", "short", "out", "destination");
    private record Result(int vehicles, String networkHash, double lastArrival, int peakTraffic,
                          int peakReserved, double peakSlotFraction, long reservationWaits,
                          long passages, double longestPassage, long greenPermissions,
                          long priorityCrossings, double peakNativeOutBodyFraction,
                          int peakNativeOutVehicles, Path output) { }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 1) throw new IllegalArgumentException("SimZ1DenseCirculationCheck [12,48,192,768]");
        int[] levels = args.length == 0 ? new int[]{12, 48, 192, 768} :
            Arrays.stream(args[0].split(",")).mapToInt(Integer::parseInt).toArray();
        if (levels.length == 0 || Arrays.stream(levels).anyMatch(n -> n < 4 || n > 5000 || n % 4 != 0))
            throw new IllegalArgumentException("Each bounded mixed-body level must be 4..5000 and divisible by four");
        Zona1Logging.configure();
        Path parent = Path.of("runtime", "diagnostics", "circulation-fixes-20261030");
        Files.createDirectories(parent);
        Path root = Files.createTempDirectory(parent, "dense-circulation-");
        var results = new ArrayList<Result>();
        try {
            for (int count : levels) {
                Result result = run(root, count);
                if (!results.isEmpty()) require(results.get(0).networkHash.equals(result.networkHash),
                    "A demand level changed network geometry or capacity");
                results.add(result);
                writeSummary(root, results);
                System.out.println("PASS dense circulation N=" + count + " arrivals=" + count +
                    " peakTraffic=" + result.peakTraffic + " peakReserved=" + result.peakReserved +
                    " peakSlotFraction=" + result.peakSlotFraction +
                    " peakNativeOutBodyFraction=" + result.peakNativeOutBodyFraction +
                    " peakNativeOutVehicles=" + result.peakNativeOutVehicles + " waits=" + result.reservationWaits +
                    " lastArrival=" + result.lastArrival + " evidence=" + result.output);
            }
            System.out.println("DENSE_CIRCULATION_OK levels=" + Arrays.toString(levels) + " evidence=" + root);
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }

    private static Result run(Path root, int count) throws Exception {
        var scenario = SimZ1CorridorOccupancyCheck.scenario();
        var net = scenario.getNetwork();
        // A true side approach prevents the 6 m connector from being absorbed
        // into origin. Every body must retain all passage/green checks.
        net.addNode(net.getFactory().createNode(Id.createNodeId("parking"), new Coord(-6, 30)));
        SimZ1CorridorOccupancyCheck.link(net, "parking-exit", "parking", "a", 30, 1);
        SimZ1CorridorOccupancyCheck.link(net, "signal-cross-in", "side", "j", 40, 1);
        // A second real intersection separates the receiving corridor from
        // the final activity link. A slow leader there can build an internal
        // queue in out, instead of only leaving demand in the activity buffer.
        net.addNode(net.getFactory().createNode(Id.createNodeId("bp"), new Coord(40, 40)));
        SimZ1CorridorOccupancyCheck.link(net, "receiver-priority-in", "bp", "b", 40, 1);
        net.getNodes().get(Id.createNodeId("j")).getAttributes().putAttribute("osm:highway", "traffic_signals");
        for (var link : net.getLinks().values()) link.setCapacity(2000);
        Path out = root.resolve("N-" + count); Files.createDirectory(out);
        Path networkFile = out.resolve("fixture-network.xml");
        new NetworkWriter(net).write(networkFile.toString());
        String networkHash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(networkFile)));

        var c = scenario.getConfig();
        c.controler().setOutputDirectory(out.resolve("run").toString());
        c.controler().setLastIteration(0);
        c.global().setRandomSeed(20261030);
        c.global().setNumberOfThreads(1); c.qsim().setNumberOfThreads(1);
        c.qsim().setUseLanes(true); c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setStartTime(0); c.qsim().setEndTime(END);
        c.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        c.qsim().setFlowCapFactor(1); c.qsim().setStorageCapFactor(1);
        c.qsim().setRemoveStuckVehicles(false); c.qsim().setStuckTime(10);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.controler().setLinkToLinkRoutingEnabled(true);
        c.travelTimeCalculator().setSeparateModes(false);
        c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for (String name : List.of("home", "work")) {
            var activity = new ActivityParams(name); activity.setTypicalDuration(3600);
            activity.setScoringThisActivityAtAll(false); c.planCalcScore().addActivityParams(activity);
        }
        var strategy = new StrategySettings(); strategy.setStrategyName("KeepLastSelected");
        strategy.setWeight(1); c.strategy().addStrategySettings(strategy);
        var admission = ConfigUtils.addOrGetModule(c, SimZ1AdmissionConfigGroup.class);
        admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT); admission.setWholeVehicleReservation(true);

        var expected = new TreeSet<String>();
        var pf = scenario.getPopulation().getFactory(); var vf = scenario.getVehicles().getFactory();
        for (int i = 0; i < count; i++) {
            String id = String.format(Locale.ROOT, "%06d-%s", i, List.of("bus-body", "truck", "car", "motorcycle").get(i % 4));
            expected.add(id);
            var type = vf.createVehicleType(Id.create(id, VehicleType.class));
            type.setLength(new double[]{13.5, 12, 4.5, 2.1}[i % 4]);
            type.setWidth(new double[]{2.5, 2.5, 1.8, .7}[i % 4]);
            type.setPcuEquivalents(new double[]{3, 3.5, 1, .25}[i % 4]);
            // One deliberately slow leading body builds receiver occupancy.
            // It is present with exactly the same profile in every level.
            type.setMaximumVelocity(i == 0 ? .5 : 10); type.setNetworkMode("car");
            scenario.getVehicles().addVehicleType(type);
            var vehicle = vf.createVehicle(Id.createVehicleId(id), type); scenario.getVehicles().addVehicle(vehicle);
            var person = pf.createPerson(Id.createPersonId(id));
            VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicle.getId()));
            var plan = pf.createPlan(); var start = pf.createActivityFromLinkId("home", Id.createLinkId(PATH.get(0)));
            // Native activity insertion does not preserve ID order for equal
            // departure times. Admit the slow leader one tick before the burst.
            start.setEndTime(i == 0 ? 0 : 1); plan.addActivity(start);
            var leg = pf.createLeg("car");
            var route = RouteUtils.createNetworkRoute(PATH.stream().map(Id::createLinkId).toList(), net);
            route.setVehicleId(vehicle.getId()); leg.setRoute(route); plan.addLeg(leg);
            plan.addActivity(pf.createActivityFromLinkId("work", Id.createLinkId(PATH.get(PATH.size()-1))));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
        LanesGenerator.build(scenario);
        var signals = TrafficLightsGenerator.build(scenario, null);
        for (var system : signals.getSignalControlData().getSignalSystemControllerDataBySystemId().values())
            for (var plan : system.getSignalPlanData().values()) {
                plan.setCycleTime(100); plan.setOffset(0);
                for (var setting : plan.getSignalGroupSettingsDataByGroupId().values()) {
                    boolean main = setting.getSignalGroupId().toString().equals("calle");
                    setting.setOnset(main ? 0 : 66); setting.setDropping(main ? 64 : 98);
                }
            }
        var events = new ArrayList<Event>();
        var controller = new Controler(scenario); RunZona1Simulation.configureSignals(controller);
        controller.addOverridingModule(new AbstractModule() {
            @Override public void install() { addEventHandlerBinding().toInstance((BasicEventHandler)events::add); }
        });
        controller.run();

        SimZ1CorridorOccupancyCheck.verifyTransactions(events);
        var arrived = new TreeSet<String>(); var departed = new TreeSet<String>();
        var entered = new TreeSet<String>(); var traffic = new HashSet<String>();
        var reserved = new HashSet<String>(); var passages = new HashMap<String, Double>();
        var tracks = new HashMap<String, List<String>>();
        var nativeOutBodies = new HashMap<String, Double>();
        int peakTraffic = 0, peakReserved = 0; double peakSlot = 0, lastArrival = 0, longestPassage = 0;
        int peakNativeOutVehicles = 0; double outCapacity = 0, peakNativeOutBodyFraction = 0;
        String firstTrafficId = null;
        long waits = 0, acquired = 0, green = 0, priorityCrossings = 0;
        for (Event event : events) {
            var a = event.getAttributes(); var kind = event.getEventType();
            require(!(event instanceof PersonStuckEvent) && !kind.equals("vehicle aborts"), "Dense fixture aborted a vehicle");
            require(!"FORCE".equals(a.get("decision")) && !"storage_forced_move".equals(a.get("reason")), "Dense fixture forced admission");
            if (event instanceof PersonDepartureEvent departure) require(departed.add(departure.getPersonId().toString()), "Duplicate departure");
            if (event instanceof PersonArrivalEvent arrival) {
                require(arrived.add(arrival.getPersonId().toString()), "Duplicate arrival"); lastArrival = Math.max(lastArrival, event.getTime());
            }
            if (event instanceof VehicleEntersTrafficEvent entry) {
                String id = entry.getVehicleId().toString(); require(entered.add(id) && traffic.add(id), "Duplicate traffic admission");
                if (firstTrafficId == null) firstTrafficId = id;
                peakTraffic = Math.max(peakTraffic, traffic.size());
            }
            if (event instanceof VehicleLeavesTrafficEvent exit) require(traffic.remove(exit.getVehicleId().toString()), "Traffic exit without entry");
            if (kind.equals("simz1OccupancyDomain") && "out".equals(a.get("link"))) outCapacity = Double.parseDouble(a.get("laneCapacityMeters"));
            if (event instanceof LinkEnterEvent enter) {
                tracks.computeIfAbsent(enter.getVehicleId().toString(), ignored -> new ArrayList<>()).add(enter.getLinkId().toString());
                if (enter.getLinkId().toString().equals("out")) {
                    require(outCapacity > 0, "Missing receiver domain capacity");
                    double body = scenario.getVehicles().getVehicles().get(enter.getVehicleId()).getType().getLength();
                    require(nativeOutBodies.put(enter.getVehicleId().toString(), body) == null, "Duplicate native receiver entry");
                    peakNativeOutVehicles = Math.max(peakNativeOutVehicles, nativeOutBodies.size());
                    peakNativeOutBodyFraction = Math.max(peakNativeOutBodyFraction,
                        nativeOutBodies.values().stream().mapToDouble(Double::doubleValue).sum()/outCapacity);
                }
            }
            if (event instanceof LinkLeaveEvent leave && leave.getLinkId().toString().equals("out"))
                require(nativeOutBodies.remove(leave.getVehicleId().toString()) != null, "Receiver exit without native entry");
            if (kind.equals("simz1OccupancyReservation")) {
                String id = a.get("vehicle"), action = a.get("action");
                if (action.equals("ENTER")) require(reserved.add(id), "Duplicate reservation");
                if (action.equals("EXIT")) require(reserved.remove(id), "Reservation exit without entry");
                if (action.equals("WAIT")) waits++;
                else {
                    double capacity = Double.parseDouble(a.get("laneCapacityMeters"));
                    if (capacity > 0) peakSlot = Math.max(peakSlot, Double.parseDouble(a.get("slotUsedMeters"))/capacity);
                    peakReserved = Math.max(peakReserved, reserved.size());
                }
            }
            if (kind.equals("simz1OccupancyPassage")) {
                String id = a.get("vehicle");
                if (a.get("action").equals("ACQUIRE")) {
                    require(passages.put(id, event.getTime()) == null, "Double passage lock"); acquired++;
                } else {
                    Double start = passages.remove(id); require(start != null, "Passage release without acquire");
                    longestPassage = Math.max(longestPassage, event.getTime()-start);
                    require(event.getTime()+1e-8 >= Double.parseDouble(a.get("minimumReleaseTime")), "Early time-only passage release");
                }
            }
            if (kind.equals("simz1NativeDecision") && "GO".equals(a.get("decision"))) {
                require(!"false".equals(a.get("nativeHasGreen")), "Native crossing at red");
                if ("short".equals(a.get("link"))) green++;
            }
            if (kind.equals("simz1Priority") && "CROSS".equals(a.get("action"))) priorityCrossings++;
        }
        require(departed.equals(expected) && entered.equals(expected) && arrived.equals(expected), "Dense population identities did not reconcile");
        require(traffic.isEmpty() && reserved.isEmpty() && passages.isEmpty() && nativeOutBodies.isEmpty(), "Leaked traffic, reservation or passage after drainage");
        require("000000-bus-body".equals(firstTrafficId), "Slow fixture leader did not enter traffic first");
        for (String id : expected) require(PATH.subList(1, PATH.size()).equals(tracks.get(id)), "Teleport or incorrect native route for " + id);
        require(lastArrival < END && waits > 0 && acquired >= 3L*count/4 && acquired <= count,
            "Did not exercise congestion and compound passage drainage");
        require(peakSlot <= 1+1e-8 && (count < 48 || peakSlot >= .5), "Dense treatment did not reach at least 50% of a metric slot");
        require(count < 48 || peakNativeOutBodyFraction >= .5,
            "Dense receiver did not hold bodies already entered in native traffic over at least 50% of its metric capacity");
        require(priorityCrossings > 0 && green > 0, "No native priority and signal movement exercised");
        return new Result(count, networkHash, lastArrival, peakTraffic, peakReserved, peakSlot,
                          waits, acquired, longestPassage, green, priorityCrossings,
                          peakNativeOutBodyFraction, peakNativeOutVehicles, out);
    }

    private static void writeSummary(Path root, List<Result> results) throws Exception {
        StringBuilder csv = new StringBuilder("vehicles,bodies_each,capacity_pcu_h_lane,flow_factor,storage_factor,horizon_s,last_arrival_s,peak_traffic,peak_reserved,peak_metric_slot_fraction,peak_native_out_body_fraction,peak_native_out_vehicles,reservation_wait_events,passages,longest_passage_s,controlled_green_permissions,priority_crossings,network_sha256,departures,traffic_entries,arrivals,final_traffic,final_reservations,final_passages,abort_events,forced_moves,capacity_overflows,output\n");
        for (var r : results) csv.append(String.format(Locale.ROOT,
            "%d,%d,2000,1,1,%.0f,%.3f,%d,%d,%.9f,%.9f,%d,%d,%d,%.3f,%d,%d,%s,%d,%d,%d,0,0,0,0,0,0,%s%n",
            r.vehicles, r.vehicles/4, END, r.lastArrival, r.peakTraffic, r.peakReserved,
            r.peakSlotFraction, r.peakNativeOutBodyFraction, r.peakNativeOutVehicles,
            r.reservationWaits, r.passages, r.longestPassage,
            r.greenPermissions, r.priorityCrossings, r.networkHash, r.vehicles, r.vehicles, r.vehicles, r.output));
        Files.writeString(root.resolve("summary.csv"), csv, StandardCharsets.UTF_8);
    }
}
