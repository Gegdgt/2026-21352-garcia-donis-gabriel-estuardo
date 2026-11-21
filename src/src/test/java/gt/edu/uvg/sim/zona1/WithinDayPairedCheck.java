package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
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
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.*;

/** Small paired QSim experiments; exogenous incidents do not depend on rerouted occupancy. */
public final class WithinDayPairedCheck {
    private static final double END = 1600;

    private static final class Iteration {
        final Map<String, List<String>> tracks = new TreeMap<>();
        final Set<String> departed = new TreeSet<>(), arrived = new TreeSet<>(), cutoff = new TreeSet<>();
        final List<String> signalChanges = new ArrayList<>();
        final List<Map<String, String>> reroutingEvents = new ArrayList<>();
        int invalidTransitions, earlyAborts;
    }

    private record Result(Path directory, int agents, boolean enabled, int budget, boolean restrictedTerminal,
                          Map<Integer, Iteration> iterations, String inputSignature) { }

    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        var root = Files.createTempDirectory(Path.of("target"), "within-day-paired-");
        List<Integer> sizes = args.length == 0 ? List.of(1, 10, 100) :
            Arrays.stream(args).map(Integer::parseInt).toList();
        var summary = new ArrayList<String>();
        summary.add("agents\trestricted_terminal\tenabled\tbudget\titeration\tdeparted\tarrived\tpending_at_horizon\tinvalid_transitions\tearly_aborts\tbypass_vehicles\tcandidates\tcalculations\tinstalled\trejected\tdeferred\tcpu_nanos\twall_nanos");
        for (int count : sizes) {
            if (count < 1 || count > 100) throw new IllegalArgumentException("Fixture sizes must be in [1,100]");
            var disabled = run(root.resolve("agents-" + count + "-off"), count, false, 100);
            var enabled = run(root.resolve("agents-" + count + "-on"), count, true, 100);
            assertPair(disabled, enabled);
            appendSummary(summary, disabled);
            appendSummary(summary, enabled);
            if (count == 100) {
                var bounded = run(root.resolve("agents-100-on-budget-1"), count, true, 1);
                assertPair(disabled, bounded);
                for (int iteration : List.of(0,1)) {
                    long unrestrictedBypasses = enabled.iterations.get(iteration).tracks.values().stream().filter(track -> track.contains("b1")).count();
                    long boundedBypasses = bounded.iterations.get(iteration).tracks.values().stream().filter(track -> track.contains("b1")).count();
                    if (boundedBypasses >= unrestrictedBypasses) throw new AssertionError("Budget has no observable experimental effect");
                }
                appendSummary(summary, bounded);
            }
        }
        var restrictedOff = run(root.resolve("terminal-restricted-off"), 1, false, 100, true);
        var restrictedOn = run(root.resolve("terminal-restricted-on"), 1, true, 100, true);
        assertPair(restrictedOff, restrictedOn);
        for (int iteration : List.of(0,1)) {
            var off = restrictedOff.iterations.get(iteration);
            var on = restrictedOn.iterations.get(iteration);
            if (!off.tracks.equals(on.tracks)) throw new AssertionError("Rejected candidate changed the physical route");
            if (on.tracks.size() != 1 || on.tracks.values().stream().anyMatch(track -> !track.equals(List.of("s", "a", "bad", "e"))))
                throw new AssertionError("Restricted terminal did not retain its reachable original route: " + on.tracks);
            if (on.reroutingEvents.stream().anyMatch(event -> "zona1WithinDayReroute".equals(event.get("type")) ||
                    "zona1RerouteStep".equals(event.get("type")) && !"0".equals(event.get("installed"))))
                throw new AssertionError("Restricted terminal installed an unnecessary route");
            var rejected = on.reroutingEvents.stream().filter(event -> "zona1RerouteRejected".equals(event.get("type"))).toList();
            if (rejected.isEmpty()) throw new AssertionError("No live terminal-lane no-improvement decision");
            for (var event : rejected) {
                if (!"no_expected_improvement".equals(event.get("reason"))) throw new AssertionError("Wrong rejection reason: " + event);
                if (!"false".equals(event.get("changed")) || !"false".equals(event.get("candidateDiffers")))
                    throw new AssertionError("Reachable original route was reported as a differing candidate: " + event);
                for (String field : List.of("person", "vehicle", "time", "currentLink", "physicalLink", "routeIndex", "lane", "oldRoute", "candidateRoute", "traversedLinks"))
                    if (event.get(field) == null || event.get(field).equals("unavailable")) throw new AssertionError("Missing rejection evidence: " + field);
                if (!event.get("currentLink").equals("a") || !event.get("physicalLink").equals("a") || !event.get("routeIndex").equals("1") ||
                    !event.get("lane").equals("a.bad") || !event.get("oldRoute").equals("[s, a, bad, e]") ||
                    !event.get("candidateRoute").equals("[s, a, bad, e]") || !event.get("traversedLinks").equals("[s, a]"))
                    throw new AssertionError("Unexpected no-improvement position/routes: " + event);
            }
        }
        appendSummary(summary, restrictedOff);
        appendSummary(summary, restrictedOn);
        Files.write(root.resolve("paired-results.tsv"), summary);
        System.out.println("PASS: paired rerouting on/off, identical plans/signals/exogenous incidents, two iterations, sizes=" + sizes);
        System.out.println("PASS: zero invalid transitions and zero early route aborts; horizon-pending trips counted separately; evidence=" + root);
        System.out.println("PASS: actual terminal-lane search retains its feasible original route without improvement, full position/route evidence and trip completion");
        org.apache.logging.log4j.LogManager.shutdown();
    }

    private static Result run(Path output, int count, boolean enabled, int budget) throws Exception {
        return run(output, count, enabled, budget, false);
    }

    private static Result run(Path output, int count, boolean enabled, int budget, boolean restrictedTerminal) throws Exception {
        Files.createDirectories(output);
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup(), new Zona1RoutingConfigGroup());
        config.global().setRandomSeed(20261004);
        config.network().setTimeVariantNetwork(true);
        config.controler().setOutputDirectory(output.resolve("run").toString());
        config.controler().setLastIteration(1);
        config.qsim().setNumberOfThreads(1);
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(END);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setUsingFastCapacityUpdate(false);
        config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        config.travelTimeCalculator().setSeparateModes(false);
        config.qsim().setRemoveStuckVehicles(false);
        config.qsim().setStuckTime(10000);
        var settings = ConfigUtils.addOrGetModule(config, Zona1RoutingConfigGroup.class);
        settings.setEnabled(Boolean.toString(enabled));
        settings.setAgentShare(1);
        settings.setMaxReroutesPerStep(budget);
        for (String type : List.of("home", "work")) {
            var activity = new ActivityParams(type);
            activity.setTypicalDuration(3600);
            activity.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(activity);
        }
        var strategy = new StrategySettings();
        strategy.setStrategyName("KeepLastSelected");
        strategy.setWeight(1);
        config.strategy().addStrategySettings(strategy);
        var scenario = ScenarioUtils.createScenario(config);
        var net = scenario.getNetwork();
        double[][] xy = {{-10,0},{0,0},{1000,0},{2000,0},{2100,0},{1500,100}};
        for (int i = 0; i < xy.length; i++)
            net.addNode(net.getFactory().createNode(Id.createNodeId(i), new Coord(xy[i][0],xy[i][1])));
        addLink(net, "s", 0, 1, 10);
        addLink(net, "a", 1, 2, 1000);
        addLink(net, "bad", 2, 3, 1000);
        addLink(net, "b1", 2, 5, 200);
        addLink(net, "b2", 5, 3, 200);
        addLink(net, "e", 3, 4, 10);
        net.getNodes().get(Id.createNodeId(3)).getAttributes().putAttribute("osm:highway", "traffic_signals");
        // The same fixed sequence is replayed in each iteration and both treatments.
        var bad = net.getLinks().get(Id.createLinkId("bad"));
        NetworkUtils.setNetworkChangeEvents(net, List.of(
            StochasticCrashEvent.change(bad, 10, 1200, 1, 3600),
            StochasticCrashEvent.change(bad, 1200, 6000, 10, 3600)));
        var factory = scenario.getPopulation().getFactory();
        for (int i = 0; i < count; i++) {
            var person = factory.createPerson(Id.createPersonId(String.format(Locale.ROOT, "p%03d", i)));
            person.getAttributes().putAttribute("drivingProfile", "Normal");
            var plan = factory.createPlan();
            var home = factory.createActivityFromLinkId("home", Id.createLinkId("s"));
            home.setEndTime(count > 1 && i == count - 1 ? END - 10 : 1);
            plan.addActivity(home);
            plan.addLeg(factory.createLeg("car"));
            plan.addActivity(factory.createActivityFromLinkId("work", Id.createLinkId("e")));
            person.addPlan(plan);
            scenario.getPopulation().addPerson(person);
        }
        restoreOriginalRoutes(scenario);
        LanesGenerator.build(scenario);
        if (restrictedTerminal) restrictTerminals(scenario);
        DrivingProfiles.configure(scenario);
        new org.matsim.api.core.v01.population.PopulationWriter(scenario.getPopulation(), net).write(output.resolve("input-plans.xml").toString());
        new org.matsim.core.network.io.NetworkWriter(net).write(output.resolve("input-network.xml").toString());
        new org.matsim.lanes.LanesWriter(scenario.getLanes()).write(output.resolve("input-lanes.xml").toString());
        Files.writeString(output.resolve("input-incidents.tsv"), "time\tlink\tcapacity_per_hour\tfreespeed_mps\n10\tbad\t1200\t1\n1200\tbad\t6000\t10\n");
        TrafficLightsGenerator.build(scenario);
        TrafficLightsGenerator.write(scenario, output);
        var signals = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class);
        signals.setSignalSystemFile(output.resolve("signalSystems.xml").toAbsolutePath().toString());
        signals.setSignalGroupsFile(output.resolve("signalGroups.xml").toAbsolutePath().toString());
        signals.setSignalControlFile(output.resolve("signalControl.xml").toAbsolutePath().toString());
        ((MutableScenario)scenario).removeScenarioElement(SignalsData.ELEMENT_NAME);
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME, new SignalsDataLoader(config).loadSignalsData());
        String signature = signature(output);
        var movementPolicy = new SimZ1RouteSafety(scenario);
        var iteration = new AtomicInteger();
        var observations = new TreeMap<Integer, Iteration>();
        BasicEventHandler observer = event -> observe(net, movementPolicy, observations.computeIfAbsent(iteration.get(), key -> new Iteration()), event);
        var controler = new Controler(scenario);
        ExperiencedTimeRouting.configure(controler);
        RunZona1Simulation.configureSignals(controler);
        // Prevent the previous iteration's within-day route from changing the experimental input.
        controler.addControlerListener((IterationStartsListener)event -> {
            iteration.set(event.getIteration());
            restoreOriginalRoutes(scenario);
        });
        var rerouting = new CongestionAwareRerouting(scenario);
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance(observer);
                addMobsimListenerBinding().toInstance(rerouting);
                addEventHandlerBinding().toInstance(rerouting);
            }
        });
        controler.run();
        return new Result(output, count, enabled, budget, restrictedTerminal, observations, signature);
    }

    private static void addLink(Network net, String id, int from, int to, double length) {
        var link = net.getFactory().createLink(Id.createLinkId(id), net.getNodes().get(Id.createNodeId(from)), net.getNodes().get(Id.createNodeId(to)));
        link.setLength(length); link.setFreespeed(10); link.setCapacity(6000); link.setNumberOfLanes(3);
        link.setAllowedModes(Set.of("car")); net.addLink(link);
    }

    private static void restoreOriginalRoutes(Scenario scenario) {
        for (var person : scenario.getPopulation().getPersons().values()) {
            var route = RouteUtils.createLinkNetworkRouteImpl(Id.createLinkId("s"), Id.createLinkId("e"));
            route.setLinkIds(Id.createLinkId("s"), List.of(Id.createLinkId("a"), Id.createLinkId("bad")), Id.createLinkId("e"));
            route.setVehicleId(Id.createVehicleId(person.getId()));
            ((Leg)person.getSelectedPlan().getPlanElements().get(1)).setRoute(route);
        }
    }

    private static void restrictTerminals(Scenario scenario) {
        var lanes = scenario.getLanes();
        var factory = lanes.getFactory();
        var assignment = factory.createLanesToLinkAssignment(Id.createLinkId("a"));
        var bad = Id.create("a.bad", org.matsim.lanes.Lane.class);
        var bypass = Id.create("a.bypass", org.matsim.lanes.Lane.class);
        org.matsim.lanes.LanesUtils.createAndAddLane(assignment, factory, bad, 4000, 900, 0, 2, List.of(Id.createLinkId("bad")), null);
        org.matsim.lanes.LanesUtils.createAndAddLane(assignment, factory, bypass, 2000, 900, 1, 1, List.of(Id.createLinkId("b1")), null);
        org.matsim.lanes.LanesUtils.createAndAddLane(assignment, factory, Id.create("a.original", org.matsim.lanes.Lane.class), 6000, 1000, 0, 3, null, List.of(bad, bypass));
        lanes.getLanesToLinkAssignments().remove(Id.createLinkId("a"));
        lanes.addLanesToLinkAssignment(assignment);
    }

    private static void observe(Network net, SimZ1RouteSafety policy, Iteration record, Event event) {
        if (event instanceof PersonDepartureEvent departure) record.departed.add(departure.getPersonId().toString());
        if (event instanceof PersonArrivalEvent arrival) record.arrived.add(arrival.getPersonId().toString());
        if (event instanceof PersonStuckEvent stuck) {
            if (stuck.getTime() >= END) record.cutoff.add(stuck.getPersonId().toString());
            else record.earlyAborts++;
        }
        if (event instanceof VehicleAbortsEvent abort && abort.getTime() < END) record.earlyAborts++;
        if (event instanceof VehicleEntersTrafficEvent enter)
            record.tracks.computeIfAbsent(enter.getVehicleId().toString(), key -> new ArrayList<>()).add(enter.getLinkId().toString());
        if (event instanceof LinkEnterEvent enter) {
            var track = record.tracks.computeIfAbsent(enter.getVehicleId().toString(), key -> new ArrayList<>());
            if (track.isEmpty()) throw new AssertionError("Vehicle entered link without traffic entry " + enter.getAttributes());
            var before = net.getLinks().get(Id.createLinkId(track.get(track.size() - 1)));
            var after = net.getLinks().get(enter.getLinkId());
            if (after == null || !after.getAllowedModes().contains("car") || !before.getToNode().getId().equals(after.getFromNode().getId()) || !policy.successors(before.getId()).contains(after.getId()))
                record.invalidTransitions++;
            track.add(enter.getLinkId().toString());
        }
        if (event instanceof SignalGroupStateChangedEvent signal)
            record.signalChanges.add(signal.getTime() + ":" + signal.getSignalSystemId() + ":" + signal.getSignalGroupId() + ":" + signal.getNewState());
        if (event.getEventType().startsWith("zona1WithinDay") || event.getEventType().startsWith("zona1Reroute") || event.getEventType().equals("zona1InvalidCurrentRoute"))
            record.reroutingEvents.add(new TreeMap<>(event.getAttributes()));
    }

    private static String signature(Path folder) throws Exception {
        var digest = java.security.MessageDigest.getInstance("SHA-256");
        for (String file : List.of("input-plans.xml", "input-network.xml", "input-lanes.xml", "input-incidents.tsv", "signalSystems.xml", "signalGroups.xml", "signalControl.xml"))
            digest.update(Files.readAllBytes(folder.resolve(file)));
        return java.util.HexFormat.of().formatHex(digest.digest());
    }

    private static void assertPair(Result off, Result on) {
        if (!off.inputSignature.equals(on.inputSignature)) throw new AssertionError("Paired inputs differ");
        for (Result result : List.of(off, on)) {
            if (!result.iterations.keySet().equals(Set.of(0,1))) throw new AssertionError("Missing iterations: " + result.iterations.keySet());
            for (var item : result.iterations.entrySet()) {
                var record = item.getValue();
                int pending = result.agents > 1 ? 1 : 0;
                if (record.invalidTransitions != 0 || record.earlyAborts != 0)
                    throw new AssertionError("Physically invalid transition or early abort: " + result.directory + " iteration=" + item.getKey());
                if (record.departed.size() != result.agents || record.arrived.size() != result.agents - pending)
                    throw new AssertionError("Unexpected completion counts " + result.directory + " iteration=" + item.getKey() + " departed=" + record.departed + " arrived=" + record.arrived);
                var outstanding = new TreeSet<>(record.departed); outstanding.removeAll(record.arrived);
                if (outstanding.size() != pending || !outstanding.equals(record.cutoff))
                    throw new AssertionError("Horizon-pending trips differ from cutoff events " + outstanding + "/" + record.cutoff);
                long bypass = record.tracks.values().stream().filter(track -> track.contains("b1")).count();
                if (result.enabled && !result.restrictedTerminal ? bypass == 0 : bypass != 0)
                    throw new AssertionError("Rerouting treatment did not change bypass use: " + result.directory + " bypass=" + bypass);
                if (!result.enabled && record.reroutingEvents.stream().anyMatch(event -> !"zona1RerouteStep".equals(event.get("type"))))
                    throw new AssertionError("Disabled rerouter attempted rerouting");
                if (record.reroutingEvents.stream().anyMatch(event -> "zona1InvalidCurrentRoute".equals(event.get("type"))))
                    throw new AssertionError("Invalid current route was observed");
                var metrics = record.reroutingEvents.stream().filter(event -> "zona1RerouteStep".equals(event.get("type"))).toList();
                if (metrics.isEmpty()) throw new AssertionError("Missing per-step metrics");
                for (var metric : metrics) {
                    long calculations = Long.parseLong(metric.get("calculations"));
                    if (calculations > result.budget || calculations < 0 || Long.parseLong(metric.get("budget")) != result.budget)
                        throw new AssertionError("Deterministic budget exceeded: " + metric);
                    if (!result.enabled && (calculations != 0 || Long.parseLong(metric.get("installed")) != 0))
                        throw new AssertionError("Disabled rerouter calculated or installed a candidate: " + metric);
                    if (Boolean.parseBoolean(metric.get("enabled")) != result.enabled) throw new AssertionError("Wrong treatment recorded: " + metric);
                    if (Long.parseLong(metric.get("cpuNanos")) < 0 || Long.parseLong(metric.get("wallNanos")) < 0)
                        throw new AssertionError("Missing execution cost: " + metric);
                    if (Integer.parseInt(metric.get("iteration")) != item.getKey()) throw new AssertionError("Iteration state leaked: " + metric);
                }
            }
            if (!result.iterations.get(0).tracks.equals(result.iterations.get(1).tracks))
                throw new AssertionError("Repeated identical inputs selected different vehicle routes: " + result.directory);
        }
        for (int iteration : List.of(0,1))
            if (!off.iterations.get(iteration).signalChanges.equals(on.iterations.get(iteration).signalChanges))
                throw new AssertionError("Signal schedules differ between treatments");
    }

    private static void appendSummary(List<String> lines, Result result) {
        for (var item : result.iterations.entrySet()) {
            var record = item.getValue();
            long bypass = record.tracks.values().stream().filter(track -> track.contains("b1")).count();
            var row = new StringBuilder(result.agents + "\t" + result.restrictedTerminal + "\t" + result.enabled + "\t" + result.budget + "\t" + item.getKey() + "\t" + record.departed.size() + "\t" + record.arrived.size() + "\t" + (record.departed.size()-record.arrived.size()) + "\t" + record.invalidTransitions + "\t" + record.earlyAborts + "\t" + bypass);
            for (String field : List.of("candidates", "calculations", "installed", "rejected", "deferred", "cpuNanos", "wallNanos")) {
                long total = record.reroutingEvents.stream().filter(event -> "zona1RerouteStep".equals(event.get("type"))).mapToLong(event -> Long.parseLong(event.get(field))).sum();
                row.append('\t').append(total);
            }
            lines.add(row.toString());
        }
    }
}
