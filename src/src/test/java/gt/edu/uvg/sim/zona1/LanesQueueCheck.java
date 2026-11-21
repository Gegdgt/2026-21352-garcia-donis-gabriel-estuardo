package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.api.experimental.events.LaneEnterEvent;
import org.matsim.core.api.experimental.events.LaneLeaveEvent;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.controler.listener.IterationStartsListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.LanesUtils;

/** Native queue measurements, not a microscopic lateral-motion experiment. */
public final class LanesQueueCheck {
    private record Treatment(boolean lanes, int represented, double length, boolean blocked, int persons) {
        String label() { return "lanes-" + lanes + "-represented-" + represented + "-length-" + length +
            "-blocked-" + blocked + "-persons-" + persons; }
    }
    private static final class Observation {
        final Set<String> departed = new TreeSet<>(), arrived = new TreeSet<>();
        final Map<String, String> currentLink = new HashMap<>();
        final Map<String, Double> probeEntry = new HashMap<>(), probeDuration = new TreeMap<>();
        final Map<String, Long> nativeReasons = new TreeMap<>();
        final Map<String, Integer> destinations = new TreeMap<>();
        final Map<Double, Integer> probeOutflow = new TreeMap<>();
        int laneEntered, laneLeft, transitions, pending, maximumQueued, invalid, earlyAborts;
        double probeStorage, acceptingStorage, terminalStorage, terminalFlow;
        String nativeLinkClass;
    }
    private record Result(Treatment treatment, Map<Integer, Observation> iterations) { }
    private static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    private static void close(double actual, double expected, String message) {
        require(Math.abs(actual - expected) < 1e-8 * Math.max(1, Math.abs(expected)), message + ": " + actual + " != " + expected);
    }

    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        try {
            Path root = Files.createTempDirectory(Path.of("target"), "lanes-queue-check-");
            List<Result> results = new ArrayList<>();
            for (int represented : List.of(1, 2)) {
                for (double length : List.of(6., 100.))
                    for (boolean lanes : List.of(false, true))
                        results.add(run(root, new Treatment(lanes, represented, length, false, 1)));
                for (boolean blocked : List.of(false, true))
                    for (boolean lanes : List.of(false, true))
                        results.add(run(root, new Treatment(lanes, represented, 100, blocked, 24)));
            }
            for (Result result : results) assertResult(result);
            for (int represented : List.of(1, 2)) {
                var off = select(results, false, represented, 6, false, 1).iterations.get(0);
                var on = select(results, true, represented, 6, false, 1).iterations.get(0);
                require(on.probeStorage > off.probeStorage, "Short-link native storage splitting was not measured");
                require(on.probeDuration.get("person-00") > off.probeDuration.get("person-00"),
                    "Serial-queue time-step discretization was not measured");
            }
            writeSummary(root, results);
            System.out.println("PASS: " + results.size() + " native QSim cases, two iterations each; evidence=" + root);
            System.out.println("PASS: one/two represented lanes, all three exits including return, effective lengths/flow, native storage/time-step effects, downstream blocking and vehicle conservation");
            System.out.println("NOTE: forced storage movements use unchanged stuckTime=10/removeStuckVehicles=false and are not evidence of physical stability");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }

    private static Result select(List<Result> results, boolean lanes, int represented, double length, boolean blocked, int persons) {
        return results.stream().filter(r -> r.treatment.equals(new Treatment(lanes, represented, length, blocked, persons))).findFirst().orElseThrow();
    }

    private static Result run(Path root, Treatment treatment) {
        var config = ConfigUtils.createConfig();
        config.global().setRandomSeed(20261015);
        config.global().setNumberOfThreads(1);
        config.controler().setOutputDirectory(root.resolve(treatment.label()).toString());
        config.controler().setLastIteration(1);
        config.qsim().setNumberOfThreads(1);
        config.qsim().setUseLanes(treatment.lanes);
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(1500);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setRemoveStuckVehicles(false);
        // Native stuckTime=10 deliberately unchanged, including blocked cases.
        config.travelTimeCalculator().setSeparateModes(false);
        for (String type : List.of("home", "work")) {
            var activity = new ActivityParams(type); activity.setTypicalDuration(3600);
            activity.setScoringThisActivityAtAll(false); config.planCalcScore().addActivityParams(activity);
        }
        var strategy = new StrategySettings(); strategy.setStrategyName("KeepLastSelected");
        strategy.setWeight(1); config.strategy().addStrategySettings(strategy);
        var scenario = ScenarioUtils.createScenario(config);
        buildNetwork(scenario, treatment);
        buildPopulation(scenario, treatment.persons);
        if (treatment.lanes) LanesGenerator.build(scenario);
        Map<Integer, Observation> observations = new TreeMap<>();
        AtomicInteger iteration = new AtomicInteger();
        var current = new java.util.function.Supplier<Observation>() {
            public Observation get() { return observations.computeIfAbsent(iteration.get(), k -> new Observation()); }
        };
        BasicEventHandler events = event -> observe(event, current.get(), scenario.getNetwork());
        var monitor = new QueueMonitor(scenario, treatment, current);
        var controler = new Controler(scenario);
        UnsignalizedPriority.configure(controler);
        controler.addControlerListener((IterationStartsListener) event -> iteration.set(event.getIteration()));
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance(events);
                addMobsimListenerBinding().toInstance(monitor);
            }
        });
        controler.run();
        System.out.println("PASS QSim completed " + treatment.label());
        return new Result(treatment, observations);
    }

    private static void buildNetwork(Scenario scenario, Treatment treatment) {
        var n = scenario.getNetwork(); var f = n.getFactory();
        for (var entry : Map.of("o", new Coord(-100, 0), "a", new Coord(0, 0),
            "b", new Coord(treatment.length, 0), "l", new Coord(treatment.length + 7.5, 7.5),
            "r", new Coord(treatment.length + 100, -100), "ld", new Coord(treatment.length + 100, 100),
            "rd", new Coord(treatment.length + 200, -100)).entrySet())
            n.addNode(f.createNode(Id.createNodeId(entry.getKey()), entry.getValue()));
        link(n, "origin", "o", "a", 100, 10, 3600, treatment.represented);
        link(n, "probe", "a", "b", treatment.length, 10, 3600, treatment.represented);
        link(n, "left", "b", "l", treatment.blocked ? 7.5 : 100, treatment.blocked ? .1 : 10,
            treatment.blocked ? 36 : 3600, 1);
        link(n, "right", "b", "r", 100, 10, 3600, 1);
        link(n, "return", "b", "a", treatment.length, 10, 3600, 1);
        link(n, "left-destination", "l", "ld", 100, 10, 3600, 1);
        link(n, "right-destination", "r", "rd", 100, 10, 3600, 1);
    }
    private static void link(Network n, String id, String from, String to, double length, double speed, double capacity, int lanes) {
        var l = n.getFactory().createLink(Id.createLinkId(id), n.getNodes().get(Id.createNodeId(from)), n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length); l.setFreespeed(speed); l.setCapacity(capacity); l.setNumberOfLanes(lanes);
        l.setAllowedModes(Set.of("car")); n.addLink(l);
    }
    private static void buildPopulation(Scenario scenario, int persons) {
        var f = scenario.getPopulation().getFactory();
        for (int i = 0; i < persons; i++) {
            var person = f.createPerson(Id.createPersonId(String.format(Locale.ROOT, "person-%02d", i)));
            var plan = f.createPlan(); var home = f.createActivityFromLinkId("home", Id.createLinkId("origin"));
            home.setEndTime(1); plan.addActivity(home);
            List<String> path = switch (i % 3) {
                case 0 -> List.of("origin", "probe", "left", "left-destination");
                case 1 -> List.of("origin", "probe", "right", "right-destination");
                default -> List.of("origin", "probe", "return");
            };
            var leg = f.createLeg("car");
            leg.setRoute(RouteUtils.createNetworkRoute(path.stream().map(Id::createLinkId).toList(), scenario.getNetwork()));
            plan.addLeg(leg); plan.addActivity(f.createActivityFromLinkId("work", Id.createLinkId(path.get(path.size() - 1))));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
    }

    private static void observe(Event event, Observation o, Network network) {
        if (event instanceof PersonDepartureEvent e) o.departed.add(e.getPersonId().toString());
        if (event instanceof PersonArrivalEvent e) o.arrived.add(e.getPersonId().toString());
        if (event instanceof VehicleEntersTrafficEvent e) o.currentLink.put(e.getVehicleId().toString(), e.getLinkId().toString());
        if (event instanceof LinkEnterEvent e) {
            String id = e.getVehicleId().toString(), link = e.getLinkId().toString();
            String previous = o.currentLink.put(id, link);
            if (previous == null || !network.getLinks().get(Id.createLinkId(previous)).getToNode().getId()
                    .equals(network.getLinks().get(e.getLinkId()).getFromNode().getId())) o.invalid++;
            o.transitions++;
            if (link.equals("probe")) o.probeEntry.put(id, e.getTime());
            if (Set.of("left", "right", "return").contains(link)) o.destinations.merge(link, 1, Integer::sum);
        }
        if (event instanceof LinkLeaveEvent e && e.getLinkId().toString().equals("probe")) {
            o.probeDuration.put(e.getVehicleId().toString(), e.getTime() - o.probeEntry.get(e.getVehicleId().toString()));
            o.probeOutflow.merge(e.getTime(), 1, Integer::sum);
        }
        if (event instanceof LaneEnterEvent) o.laneEntered++;
        if (event instanceof LaneLeaveEvent) o.laneLeft++;
        if (event instanceof PersonStuckEvent e) { if (e.getTime() < 1500) o.earlyAborts++; else o.pending++; }
        if (event.getEventType().equals("simz1NativeDecision"))
            o.nativeReasons.merge(event.getAttributes().get("reason"), 1L, Long::sum);
    }

    private static final class QueueMonitor implements MobsimInitializedListener, MobsimAfterSimStepListener {
        final Scenario scenario; final Treatment treatment; final java.util.function.Supplier<Observation> observation;
        QSim sim;
        QueueMonitor(Scenario scenario, Treatment treatment, java.util.function.Supplier<Observation> observation) {
            this.scenario = scenario; this.treatment = treatment; this.observation = observation;
        }
        @Override public void notifyMobsimInitialized(MobsimInitializedEvent event) {
            sim = (QSim) event.getQueueSimulation(); var o = observation.get();
            var qlink = (QLinkI) sim.getNetsimNetwork().getNetsimLink(Id.createLinkId("probe"));
            o.nativeLinkClass = qlink.getClass().getSimpleName();
            require((qlink instanceof QLinkLanesImpl) == treatment.lanes, "Requested lane configuration differs from loaded QSim implementation");
            o.acceptingStorage = qlink.getAcceptingQLane().getStorageCapacity();
            o.terminalStorage = qlink.getOfferingQLanes().stream().mapToDouble(QLaneI::getStorageCapacity).sum();
            o.terminalFlow = qlink.getOfferingQLanes().stream().mapToDouble(QLaneI::getSimulatedFlowCapacityPerTimeStep).sum();
            close(o.terminalFlow, 1, "Total flow per tick changed");
            if (qlink instanceof QLinkLanesImpl multi) {
                var link = scenario.getNetwork().getLinks().get(Id.createLinkId("probe"));
                var assignment = scenario.getLanes().getLanesToLinkAssignments().get(link.getId());
                for (var model : LanesUtils.createLanes(link, assignment)) {
                    var data = model.getLaneData();
                    double flow = data.getCapacityVehiclesPerHour() / 3600.;
                    double geometric = model.getLength() * data.getNumberOfRepresentedLanes() / scenario.getNetwork().getEffectiveCellSize();
                    double expected = Math.max(geometric, Math.max(flow, model.getLength() / 10 * flow));
                    var queue = multi.getQueueLanes().get(data.getId());
                    close(queue.getStorageCapacity(), expected, "Native queue storage disagrees with MATSim 15 queue contract");
                    close(queue.getSimulatedFlowCapacityPerTimeStep(), flow, "Native queue flow disagrees with generated definition");
                    o.probeStorage += queue.getStorageCapacity();
                }
            } else o.probeStorage = o.acceptingStorage;
        }
        @Override public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent event) {
            Set<String> seen = new HashSet<>();
            for (var link : sim.getNetsimNetwork().getNetsimLinks().values()) {
                for (var vehicle : ((QLinkI) link).getAllNonParkedVehicles())
                    require(seen.add(vehicle.getId().toString()), "Vehicle duplicated across native queues: " + vehicle.getId());
            }
            observation.get().maximumQueued = Math.max(observation.get().maximumQueued, seen.size());
        }
    }

    private static void assertResult(Result result) {
        require(result.iterations.size() == 2, "Missing iteration");
        var t = result.treatment;
        for (var entry : result.iterations.entrySet()) {
            var o = entry.getValue(); String label = t.label() + " iteration=" + entry.getKey();
            require(o.departed.size() == t.persons && o.arrived.equals(o.departed), "Vehicle/person conservation failed: " + label);
            require(o.pending == 0 && o.earlyAborts == 0 && o.invalid == 0, "Unfinished/invalid trip: " + label);
            require(o.probeDuration.size() == t.persons, "Probe throughput differs from demand: " + label);
            require(o.nativeReasons.entrySet().stream().noneMatch(e -> e.getKey().startsWith("turn_abort") && e.getValue() > 0), "Native ABORT: " + label);
            require(t.lanes ? o.laneEntered > 0 && o.laneLeft > 0 : o.laneEntered == 0 && o.laneLeft == 0,
                "Native lane event availability differs from useLanes: " + label);
            if (t.persons > 1) {
                require(o.destinations.equals(Map.of("left", 8, "right", 8, "return", 8)), "Destination or U-turn lost: " + label);
                if (t.blocked) require(o.nativeReasons.getOrDefault("storage_wait", 0L) > 0, "Downstream blockage not exercised: " + label);
                else {
                    double span = o.probeOutflow.keySet().stream().mapToDouble(Double::doubleValue).max().orElseThrow() -
                        o.probeOutflow.keySet().stream().mapToDouble(Double::doubleValue).min().orElseThrow();
                    require(t.persons <= span * o.terminalFlow + t.represented + 1,
                        "Unblocked discharge exceeds configured flow plus initial discrete buffer: " + label);
                    require(o.nativeReasons.getOrDefault("storage_forced_move", 0L) == 0, "Unexpected intervention in free fixture: " + label);
                }
            }
        }
    }
    private static void writeSummary(Path root, List<Result> results) throws Exception {
        var summary = new StringBuilder("case\titeration\tpersons\tarrived\tpending\tinvalid_transitions\tlane_enter\tlane_leave\tprobe_storage_pcu\taccepting_storage_pcu\tterminal_storage_pcu\tterminal_flow_pcu_per_tick\tmin_probe_seconds\tmax_probe_seconds\tmax_queued\tstorage_wait_attempts\tforced_moves\timplementation\n");
        for (var result : results) for (var entry : result.iterations.entrySet()) {
            var o = entry.getValue();
            summary.append(result.treatment.label()).append('\t').append(entry.getKey()).append('\t').append(o.departed.size()).append('\t')
                .append(o.arrived.size()).append('\t').append(o.pending).append('\t').append(o.invalid).append('\t').append(o.laneEntered).append('\t')
                .append(o.laneLeft).append('\t').append(o.probeStorage).append('\t').append(o.acceptingStorage).append('\t').append(o.terminalStorage).append('\t')
                .append(o.terminalFlow).append('\t').append(Collections.min(o.probeDuration.values())).append('\t')
                .append(Collections.max(o.probeDuration.values())).append('\t').append(o.maximumQueued).append('\t')
                .append(o.nativeReasons.getOrDefault("storage_wait", 0L)).append('\t').append(o.nativeReasons.getOrDefault("storage_forced_move", 0L)).append('\t')
                .append(o.nativeLinkClass).append('\n');
        }
        Files.writeString(root.resolve("summary.tsv"), summary);
    }
}
