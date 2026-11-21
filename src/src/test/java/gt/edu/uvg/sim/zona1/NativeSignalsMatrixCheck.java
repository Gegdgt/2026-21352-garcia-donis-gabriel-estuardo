package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.contrib.signals.events.SignalGroupStateChangedEvent;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.controler.listener.IterationStartsListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.*;

/** Controlled, deliberately small experiments; never loads or rewrites a saved SimZ1 scenario. */
public final class NativeSignalsMatrixCheck {
    private static final double START = 43; // Native avenue phase is YELLOW at initialization.
    private static final double END = 500;
    private static final int PERSONS = 8;
    private static final long SEED = 20261004;
    private static final Set<String> CONTROLLED = Set.of("w", "s");

    private record Treatment(boolean signals, boolean lanes, boolean rerouting, boolean incidents,
                             int threads, boolean lowStuckTime, boolean priorityFixture) {
        String label() {
            return "signals-" + signals + "-lanes-" + lanes + "-reroute-" + rerouting +
                "-incidents-" + incidents + "-threads-" + threads +
                (lowStuckTime ? "-forced-storage-negative-control" : "") +
                (priorityFixture ? "-untagged-priority" : "");
        }
    }

    private static final class Observation {
        final Set<String> departed = new TreeSet<>(), arrived = new TreeSet<>(), cutoff = new TreeSet<>();
        final Map<String, List<String>> tracks = new TreeMap<>();
        final Map<String, SignalGroupState> states = new HashMap<>();
        final Map<String, Double> yellowStarts = new HashMap<>();
        final List<Double> amberDurations = new ArrayList<>();
        final List<String> signalChanges = new ArrayList<>();
        final Map<String, Long> nativeReasons = new TreeMap<>();
        final List<Map<String, String>> reroutingSteps = new ArrayList<>();
        final List<Map<String, String>> progress = new ArrayList<>();
        final Map<String, Double> nativePermissions = new HashMap<>();
        int crossings, amberCrossings, invalidTransitions, invalidSignalCrossings, earlyAborts, restoredYellow;
    }

    private record Result(Path path, Treatment treatment, String demandHash, String networkHash,
                          String signalsHash, String incidentsHash, Map<Integer, Observation> observations) { }

    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        try { runChecks(args); }
        finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }

    private static void runChecks(String[] args) throws Exception {
        if (args.length > 1 || args.length == 1 && !args[0].equals("smoke"))
            throw new IllegalArgumentException("NativeSignalsMatrixCheck [smoke]");
        boolean smoke = args.length == 1;
        Path root = Files.createTempDirectory(Path.of("target"), "native-signals-matrix-");
        var results = new ArrayList<Result>();
        for (boolean incidents : List.of(false, true))
            for (boolean signals : List.of(false, true))
                for (boolean lanes : List.of(false, true))
                    for (boolean rerouting : List.of(false, true))
                        for (int threads : List.of(1, 4)) {
                            if (smoke && (incidents || !signals || rerouting || threads != 1)) continue;
                            var treatment = new Treatment(signals, lanes, rerouting, incidents, threads, false, false);
                            Result result = run(root, treatment);
                            assertResult(result);
                            results.add(result);
                            writeSummary(root, results);
                            System.out.println("PASS matrix " + treatment.label());
                        }
        if (!smoke) {
            // Deliberately unsafe threshold in a test fixture only. A completed trip
            // after this intervention is NOT evidence of physically stable traffic.
            for (int threads : List.of(1, 4)) {
                var forced = run(root, new Treatment(true, false, false, true, threads, true, false));
                assertResult(forced);
                results.add(forced);
                writeSummary(root, results);
                var priority = run(root, new Treatment(false, false, false, false, threads, false, true));
                assertResult(priority);
                results.add(priority);
                writeSummary(root, results);
            }
        }
        assertMatchedInputs(results);
        writeSummary(root, results);
        System.out.println("PASS: " + results.size() + " small QSim controllers, each with two iterations; evidence=" + root);
        System.out.println("PASS: native-permitted GREEN/YELLOW crossings, initialized amber, identical demand/seed, explicit pending trips, no corrupt transitions or early aborts");
        if (!smoke) System.out.println("PASS: forced storage is measured at the unchanged native threshold and in deliberate low-stuckTime controls; affected runs are not evidence of physical stability");
    }

    private static Result run(Path root, Treatment treatment) throws Exception {
        Path output = root.resolve(treatment.label());
        Files.createDirectories(output);
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup(), new Zona1RoutingConfigGroup());
        config.global().setRandomSeed(SEED);
        config.global().setNumberOfThreads(treatment.threads);
        config.network().setTimeVariantNetwork(true);
        config.controler().setOutputDirectory(output.resolve("run").toString());
        config.controler().setLastIteration(1);
        config.qsim().setNumberOfThreads(treatment.threads);
        config.qsim().setStartTime(START);
        config.qsim().setEndTime(END);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setRemoveStuckVehicles(false);
        // Leave the native default unchanged in the matrix. Changing it to a
        // large value would conceal the storage intervention being investigated.
        if (treatment.lowStuckTime) config.qsim().setStuckTime(2);
        config.qsim().setUseLanes(treatment.lanes);
        config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        config.travelTimeCalculator().setSeparateModes(false);
        var routing = ConfigUtils.addOrGetModule(config, Zona1RoutingConfigGroup.class);
        routing.setEnabled(Boolean.toString(treatment.rerouting));
        routing.setAgentShare(1);
        routing.setMaxReroutesPerStep(3);
        for (String type : List.of("home", "work")) {
            var activity = new ActivityParams(type);
            activity.setTypicalDuration(3600);
            activity.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(activity);
        }
        var strategy = new StrategySettings();
        strategy.setStrategyName("KeepLastSelected"); strategy.setWeight(1);
        config.strategy().addStrategySettings(strategy);
        var scenario = ScenarioUtils.createScenario(config);
        buildNetwork(scenario, treatment.priorityFixture);
        var network = scenario.getNetwork();
        if (treatment.incidents) {
            var affected = network.getLinks().get(Id.createLinkId("xw"));
            NetworkUtils.setNetworkChangeEvents(network, List.of(
                StochasticCrashEvent.change(affected, START, 6000, .05, 3600),
                StochasticCrashEvent.change(affected, 180, 6000, 10, 3600)));
        }
        buildPopulation(scenario);
        if (treatment.lanes) LanesGenerator.build(scenario);
        DrivingProfiles.configure(scenario);
        new org.matsim.api.core.v01.population.PopulationWriter(scenario.getPopulation(), network)
            .write(output.resolve("input-plans.xml").toString());
        new org.matsim.core.network.io.NetworkWriter(network).write(output.resolve("input-network.xml").toString());
        new org.matsim.lanes.LanesWriter(scenario.getLanes()).write(output.resolve("input-lanes.xml").toString());
        Files.writeString(output.resolve("input-incidents.tsv"), "time\tlink\tcapacity_per_hour\tfreespeed_mps\n" +
            (treatment.incidents ? "43\txw\t6000\t0.05\n180\txw\t6000\t10\n" : ""));
        var signalConfig = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class);
        if (treatment.signals) {
            TrafficLightsGenerator.build(scenario);
            if (config.qsim().isUseLanes() != treatment.lanes)
                throw new AssertionError("Signal generation changed explicit lane option");
            TrafficLightsGenerator.write(scenario, output);
            signalConfig.setSignalSystemFile(output.resolve("signalSystems.xml").toAbsolutePath().toString());
            signalConfig.setSignalGroupsFile(output.resolve("signalGroups.xml").toAbsolutePath().toString());
            signalConfig.setSignalControlFile(output.resolve("signalControl.xml").toAbsolutePath().toString());
            ((MutableScenario) scenario).removeScenarioElement(SignalsData.ELEMENT_NAME);
            scenario.addScenarioElement(SignalsData.ELEMENT_NAME, new SignalsDataLoader(config).loadSignalsData());
        } else signalConfig.setUseSignalSystems(false);
        String signalHash = treatment.signals ? hash(output, "signalGroups.xml", "signalControl.xml") : "off";
        var policy = new SimZ1RouteSafety(scenario);
        var currentIteration = new AtomicInteger();
        var observations = new TreeMap<Integer, Observation>();
        BasicEventHandler observer = event -> observe(network, policy, treatment,
            observations.computeIfAbsent(currentIteration.get(), key -> new Observation()), event);
        var controler = new Controler(scenario);
        ExperiencedTimeRouting.configure(controler);
        if (treatment.signals) RunZona1Simulation.configureSignals(controler);
        else UnsignalizedPriority.configure(controler);
        SimZ1Diagnostics.install(controler);
        controler.addControlerListener((IterationStartsListener) event -> {
            currentIteration.set(event.getIteration());
            restoreRoutes(scenario);
        });
        var rerouter = new CongestionAwareRerouting(scenario);
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance(observer);
                addEventHandlerBinding().toInstance(rerouter);
                addMobsimListenerBinding().toInstance(rerouter);
            }
        });
        controler.run();
        return new Result(output, treatment, hash(output, "input-plans.xml"), hash(output, "input-network.xml"),
            signalHash, hash(output, "input-incidents.tsv"), observations);
    }

    private static void buildNetwork(Scenario scenario, boolean priorityFixture) {
        var network = scenario.getNetwork();
        double[][] coords = {{-30,0},{-20,0},{0,0},{10,0},{0,-30},{0,-20},{0,10},{20,0},{0,20},{5,15}};
        for (int i = 0; i < coords.length; i++) network.addNode(network.getFactory().createNode(
            Id.createNodeId(i), new Coord(coords[i][0], coords[i][1])));
        addLink(network, "sw", 0, 1, 10);
        addLink(network, "w", 1, 2, 20);
        addLink(network, "xw", 2, 3, 10);
        addLink(network, "ew", 3, 7, 10);
        addLink(network, "ss", 4, 5, 10);
        addLink(network, "s", 5, 2, 10);
        addLink(network, "xs", 2, 6, 10);
        addLink(network, "es", 6, 8, 10);
        addLink(network, "b1", 2, 9, 100);
        addLink(network, "b2", 9, 3, 100);
        if (!priorityFixture) network.getNodes().get(Id.createNodeId(2)).getAttributes().putAttribute("osm:highway", "traffic_signals");
    }

    private static void addLink(Network network, String name, int from, int to, double length) {
        Link link = network.getFactory().createLink(Id.createLinkId(name),
            network.getNodes().get(Id.createNodeId(from)), network.getNodes().get(Id.createNodeId(to)));
        link.setLength(length); link.setFreespeed(10); link.setCapacity(6000); link.setNumberOfLanes(1);
        link.setAllowedModes(Set.of("car")); network.addLink(link);
    }

    private static void buildPopulation(Scenario scenario) {
        var factory = scenario.getPopulation().getFactory();
        for (int i = 0; i < PERSONS; i++) {
            var person = factory.createPerson(Id.createPersonId("p" + i));
            person.getAttributes().putAttribute("drivingProfile", "Normal");
            var plan = factory.createPlan();
            boolean south = i == PERSONS - 2;
            var home = factory.createActivityFromLinkId("home", Id.createLinkId(south ? "s" : "sw"));
            // One approach is already due when QSim starts inside its amber;
            // MATSim 15 permits native YELLOW clearance, but never RED/REDYELLOW.
            home.setEndTime(i == PERSONS - 1 ? END - 1 : south ? START - 1 : START + 1);
            plan.addActivity(home); plan.addLeg(factory.createLeg("car"));
            plan.addActivity(factory.createActivityFromLinkId("work", Id.createLinkId(south ? "es" : "ew")));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
        restoreRoutes(scenario);
    }

    private static void restoreRoutes(Scenario scenario) {
        for (var person : scenario.getPopulation().getPersons().values()) {
            boolean south = person.getId().toString().equals("p" + (PERSONS - 2));
            var start = Id.createLinkId(south ? "s" : "sw");
            var end = Id.createLinkId(south ? "es" : "ew");
            var route = RouteUtils.createLinkNetworkRouteImpl(start, end);
            route.setLinkIds(start, south ? List.of(Id.createLinkId("xs")) : List.of(Id.createLinkId("w"), Id.createLinkId("xw")), end);
            route.setVehicleId(Id.createVehicleId(person.getId()));
            ((Leg) person.getSelectedPlan().getPlanElements().get(1)).setRoute(route);
        }
    }

    private static String axis(String link) { return link.equals("s") ? "avenida" : "calle"; }
    private static boolean permittedSignalState(SignalGroupState state) {
        // DefaultSignalizeableItem.checkGreen permits GREEN, YELLOW and OFF.
        // This fixed-time enabled fixture never schedules OFF.
        return state == SignalGroupState.GREEN || state == SignalGroupState.YELLOW;
    }

    private static void observe(Network network, SimZ1RouteSafety policy, Treatment treatment, Observation obs, Event event) {
        if (event instanceof PersonDepartureEvent departure) obs.departed.add(departure.getPersonId().toString());
        if (event instanceof PersonArrivalEvent arrival) obs.arrived.add(arrival.getPersonId().toString());
        if (event instanceof PersonStuckEvent stuck) {
            if (stuck.getTime() >= END) obs.cutoff.add(stuck.getPersonId().toString());
            else obs.earlyAborts++;
        }
        if (event instanceof VehicleAbortsEvent abort && abort.getTime() < END) obs.earlyAborts++;
        if (event instanceof VehicleEntersTrafficEvent entry)
            obs.tracks.computeIfAbsent(entry.getVehicleId().toString(), key -> new ArrayList<>()).add(entry.getLinkId().toString());
        if (event instanceof LinkEnterEvent entry) {
            var track = obs.tracks.computeIfAbsent(entry.getVehicleId().toString(), key -> new ArrayList<>());
            if (track.isEmpty()) throw new AssertionError("Missing vehicle traffic entry " + entry.getAttributes());
            Link before = network.getLinks().get(Id.createLinkId(track.get(track.size() - 1)));
            Link after = network.getLinks().get(entry.getLinkId());
            if (after == null || !after.getAllowedModes().contains("car") ||
                !before.getToNode().getId().equals(after.getFromNode().getId()) ||
                !policy.successors(before.getId()).contains(after.getId())) obs.invalidTransitions++;
            track.add(entry.getLinkId().toString());
        }
        if (event instanceof SignalGroupStateChangedEvent signal) {
            String group = signal.getSignalGroupId().toString();
            obs.states.put(group, signal.getNewState());
            obs.signalChanges.add(signal.getTime() + ":" + group + ":" + signal.getNewState());
            if (signal.getNewState() == SignalGroupState.YELLOW) {
                obs.yellowStarts.put(group, signal.getTime());
                if (signal.getTime() <= START + 1 && group.equals("avenida")) obs.restoredYellow++;
            }
            if (signal.getNewState() == SignalGroupState.RED && signal.getTime() > START + 1) {
                Double yellowStart = obs.yellowStarts.remove(group);
                if (yellowStart == null) throw new AssertionError("Native RED without preceding amber " + signal.getAttributes());
                if (yellowStart > START + 1) obs.amberDurations.add(signal.getTime() - yellowStart);
            }
        }
        if (event instanceof LinkLeaveEvent leave && CONTROLLED.contains(leave.getLinkId().toString())) {
            obs.crossings++;
            if (treatment.signals) {
                var state = obs.states.get(axis(leave.getLinkId().toString()));
                if (!permittedSignalState(state) || !Objects.equals(leave.getTime(),
                        obs.nativePermissions.get(leave.getVehicleId() + ":" + leave.getLinkId()))) obs.invalidSignalCrossings++;
                if (state == SignalGroupState.YELLOW) obs.amberCrossings++;
            }
        }
        if (event.getEventType().equals("simz1NativeDecision")) {
            var attrs = event.getAttributes();
            String reason = Objects.requireNonNull(attrs.get("reason"));
            obs.nativeReasons.merge(reason, 1L, Long::sum);
            for (String field : List.of("decision", "person", "vehicle", "link", "nextLink", "lane", "waitSeconds", "stuckTime", "removeStuckVehicles", "signalState", "nativeHasGreen", "trafficDynamics"))
                if (!attrs.containsKey(field)) throw new AssertionError("Native decision missing evidence " + field + ":" + attrs);
            if (reason.equals("turn_go") && "true".equals(attrs.get("nativeHasGreen")))
                obs.nativePermissions.put(attrs.get("vehicle") + ":" + attrs.get("link"), event.getTime());
            if (reason.equals("storage_forced_move") && treatment.signals && CONTROLLED.contains(attrs.get("link")) &&
                (!permittedSignalState(obs.states.get(axis(attrs.get("link")))) || !"true".equals(attrs.get("nativeHasGreen"))))
                throw new AssertionError("Forced storage crossed a native signal without permission: " + attrs);
        }
        if (event.getEventType().equals("zona1RerouteStep")) obs.reroutingSteps.add(new TreeMap<>(event.getAttributes()));
        if (event.getEventType().equals("simz1Progress")) obs.progress.add(new TreeMap<>(event.getAttributes()));
        if (event.getEventType().equals("zona1InvalidCurrentRoute"))
            throw new AssertionError("Corrupt input/current route: " + event.getAttributes());
    }

    private static void assertResult(Result result) {
        if (!result.observations.keySet().equals(Set.of(0, 1))) throw new AssertionError("Two iterations missing: " + result.path);
        for (var item : result.observations.entrySet()) {
            var obs = item.getValue();
            String context = result.path + " iteration=" + item.getKey();
            if (obs.invalidTransitions != 0 || obs.earlyAborts != 0 || obs.invalidSignalCrossings != 0)
                throw new AssertionError("Invalid transitions/aborts/prohibited-state crossings " + context + ": " +
                    obs.invalidTransitions + "/" + obs.earlyAborts + "/" + obs.invalidSignalCrossings);
            if (obs.departed.size() != PERSONS || !obs.departed.containsAll(obs.arrived))
                throw new AssertionError("Incorrect demand accounting " + context);
            var pending = new TreeSet<>(obs.departed); pending.removeAll(obs.arrived);
            if (!pending.equals(Set.of("p7")) || !pending.equals(obs.cutoff))
                throw new AssertionError("Unexpected horizon-pending trips " + context + ": " + pending + " vs " + obs.cutoff);
            if (obs.crossings != PERSONS - 1) throw new AssertionError("Missing junction crossings " + context + ": " + obs.crossings);
            if (result.treatment.signals) {
                if (obs.restoredYellow == 0 || obs.amberDurations.isEmpty() ||
                    obs.amberDurations.stream().anyMatch(duration -> duration != RunZona1Simulation.AMBER_SECONDS))
                    throw new AssertionError("Mid-cycle amber was not restored or native amber duration changed " + context + ": " + obs.amberDurations);
                if (obs.nativeReasons.getOrDefault("signal_red", 0L) == 0)
                    throw new AssertionError("Missing native red WAIT observations " + context);
                if (obs.amberCrossings == 0)
                    throw new AssertionError("Missing native-permitted amber clearance at mid-cycle start " + context);
            } else if (!obs.signalChanges.isEmpty() || obs.nativeReasons.keySet().stream().anyMatch(reason -> reason.startsWith("signal_")))
                throw new AssertionError("Disabled signals emitted native signal decisions " + context);
            long forced = obs.nativeReasons.getOrDefault("storage_forced_move", 0L);
            if (result.treatment.lowStuckTime && forced == 0 || !result.treatment.incidents && forced != 0)
                throw new AssertionError("Unexpected forced-storage intervention count " + context + ": " + forced);
            if (obs.nativeReasons.keySet().stream().anyMatch(reason -> reason.startsWith("turn_abort") || reason.equals("storage_stuck_removal")))
                throw new AssertionError("Native abort/removal occurred " + context + ": " + obs.nativeReasons);
            if (result.treatment.priorityFixture && obs.nativeReasons.getOrDefault("priority_stop", 0L) == 0)
                throw new AssertionError("Unsignalized fixture did not report priority WAIT " + context);
            if (obs.reroutingSteps.isEmpty()) throw new AssertionError("Missing routing activity monitoring " + context);
            for (var step : obs.reroutingSteps) {
                long calculations = Long.parseLong(step.get("calculations"));
                if (calculations < 0 || calculations > 3 || Integer.parseInt(step.get("iteration")) != item.getKey())
                    throw new AssertionError("Routing budget/iteration monitoring invalid: " + step);
                if (!result.treatment.rerouting && (calculations != 0 || Long.parseLong(step.get("installed")) != 0))
                    throw new AssertionError("Explicit disabled routing was ignored: " + step);
            }
            if (obs.progress.isEmpty()) throw new AssertionError("Missing simulation/CPU/wait progress monitor " + context);
            double previousTime = -1;
            for (var progress : obs.progress) {
                double elapsed = Double.parseDouble(progress.get("elapsedSimSeconds"));
                double simulatedTime = Double.parseDouble(progress.get("time"));
                if (elapsed < 0 || simulatedTime < previousTime ||
                    previousTime >= 0 && elapsed != simulatedTime - previousTime || Long.parseLong(progress.get("processCpuNanos")) < -1 ||
                    Long.parseLong(progress.get("wallNanos")) < 0 || Integer.parseInt(progress.get("iteration")) != item.getKey())
                    throw new AssertionError("Invalid progress/CPU/iteration evidence: " + progress);
                previousTime = simulatedTime;
                for (String field : List.of("stepCount", "linkTransitions", "arrivals", "activeVehicles", "rerouteCalculations",
                        "waitSignal", "waitStorage", "waitPriority", "forcedMoves", "threadDeadlocks"))
                    if (Long.parseLong(progress.get(field)) < 0) throw new AssertionError("Invalid progress counter " + field + ":" + progress);
                if (Long.parseLong(progress.get("threadDeadlocks")) != 0 || progress.get("classification").equals("thread_deadlock"))
                    throw new AssertionError("Fixture unexpectedly reports a thread deadlock: " + progress);
            }
        }
        if (!result.observations.get(0).signalChanges.equals(result.observations.get(1).signalChanges))
            throw new AssertionError("Signal initialization/schedule leaked across iterations: " + result.path);
    }

    private static void assertMatchedInputs(List<Result> results) {
        String demand = results.get(0).demandHash;
        for (Result result : results) if (!result.demandHash.equals(demand))
            throw new AssertionError("Plan inputs changed between treatments: " + result.path);
        for (Result left : results) for (Result right : results) {
            if (left.treatment.priorityFixture != right.treatment.priorityFixture) continue;
            if (!left.networkHash.equals(right.networkHash)) throw new AssertionError("Network inputs differ across treatments");
            if (left.treatment.incidents == right.treatment.incidents && !left.incidentsHash.equals(right.incidentsHash))
                throw new AssertionError("Fixed exogenous incident schedule differs across paired treatments");
            if (left.treatment.signals && right.treatment.signals) {
                if (!left.signalsHash.equals(right.signalsHash)) throw new AssertionError("Signal phase input differs across treatments");
                for (int iteration : List.of(0, 1))
                    if (!left.observations.get(iteration).signalChanges.equals(right.observations.get(iteration).signalChanges))
                        throw new AssertionError("Native signal state schedules differ between treatments");
            }
        }
    }

    private static String hash(Path folder, String... files) throws Exception {
        var digest = MessageDigest.getInstance("SHA-256");
        for (String file : files) digest.update(Files.readAllBytes(folder.resolve(file)));
        return HexFormat.of().formatHex(digest.digest());
    }

    private static void writeSummary(Path root, List<Result> results) throws Exception {
        var lines = new ArrayList<String>();
        lines.add("treatment\titeration\tseed\tdeparted\tarrived\tpending_at_horizon\tcrossings\tamber_clearance_crossings\tinvalid_transitions\tprohibited_state_crossings\tearly_aborts\trestored_yellow\tphysical_intervention_observed\tnative_reasons\tprogress_samples\tdemand_sha256\tnetwork_sha256\tsignal_phase_sha256\tincidents_sha256");
        for (Result result : results) for (var item : result.observations.entrySet()) {
            var obs = item.getValue();
            lines.add(result.treatment.label() + "\t" + item.getKey() + "\t" + SEED + "\t" + obs.departed.size() + "\t" +
                obs.arrived.size() + "\t" + (obs.departed.size() - obs.arrived.size()) + "\t" + obs.crossings + "\t" + obs.amberCrossings + "\t" +
                obs.invalidTransitions + "\t" + obs.invalidSignalCrossings + "\t" + obs.earlyAborts + "\t" + obs.restoredYellow + "\t" +
                (obs.nativeReasons.getOrDefault("storage_forced_move", 0L) > 0) + "\t" + obs.nativeReasons + "\t" + obs.progress.size() + "\t" +
                result.demandHash + "\t" + result.networkHash + "\t" + result.signalsHash + "\t" + result.incidentsHash);
        }
        Files.write(root.resolve("matrix-results.tsv"), lines);
    }
}
