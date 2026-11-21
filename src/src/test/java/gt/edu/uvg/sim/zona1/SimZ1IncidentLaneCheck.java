package gt.edu.uvg.sim.zona1;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;
import javax.xml.stream.XMLOutputFactory;
import org.matsim.core.config.ConfigUtils;
import gt.edu.uvg.sim.zona1.SimZ1IncidentLaneCoordinator.Request;
import gt.edu.uvg.sim.zona1.SimZ1IncidentLaneCoordinator.WorkerStamp;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.LaneKey;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.Participant;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.State;

/** Pure contract fixtures. Never constructs Scenario, QSim, Controler or native queues. */
public final class SimZ1IncidentLaneCheck {
    private static final long SECOND = 1_000_000L;
    private static final LaneKey LANE = new LaneKey("fixture-link", "fixture-lane-0");
    private static final LaneKey PARALLEL = new LaneKey("fixture-link", "fixture-lane-1");
    private static int assertions;

    private static void check(boolean condition, String message) {
        assertions++;
        if (!condition) throw new AssertionError(message);
    }
    private static void rejected(Runnable action, String detail) {
        assertions++;
        try { action.run(); }
        catch (IllegalArgumentException | IllegalStateException expected) {
            if (!expected.getMessage().contains(detail)) throw new AssertionError("Unexpected rejection", expected);
            return;
        }
        throw new AssertionError("Accepted invalid fixture: " + detail);
    }
    private static List<WorkerStamp> stamps(long time) {
        return IntStream.range(0, 4).mapToObj(i -> new WorkerStamp(i, time)).toList();
    }
    private static Request request(String suffix, LaneKey lane, long time) {
        return new Request("fixture-incident-" + suffix, "fixture-opportunity-" + suffix, lane,
            List.of(new Participant("fixture-B-" + suffix, null, "fixture-bus", lane),
                    new Participant("fixture-A-" + suffix, "fixture-person-A-" + suffix, "fixture-car", lane)),
            time, "fixture-evidence-" + suffix);
    }
    private static SimZ1IncidentLaneCoordinator coordinator(boolean enabled) {
        return SimZ1IncidentLaneCoordinator.forFixtures(enabled, "fixture-run", 0, 4);
    }

    private static void configuration() throws Exception {
        var config = ConfigUtils.createConfig(new SimZ1IncidentConfigGroup());
        var group = ConfigUtils.addOrGetModule(config, SimZ1IncidentConfigGroup.class);
        check(!group.isEnabled() && group.getDurationSeconds() == 1800, "Not default off/fixed duration");
        var randomSeed = config.global().getRandomSeed();
        var admission = ConfigUtils.addOrGetModule(config, SimZ1AdmissionConfigGroup.class).getStoragePolicy();
        var stuck = config.qsim().getStuckTime();
        var remove = config.qsim().isRemoveStuckVehicles();
        SimZ1Configuration.validate(config);
        check(config.global().getRandomSeed() == randomSeed && config.qsim().getStuckTime() == stuck &&
            config.qsim().isRemoveStuckVehicles() == remove && admission.equals(
                ConfigUtils.addOrGetModule(config, SimZ1AdmissionConfigGroup.class).getStoragePolicy()),
            "Disabled preflight changed physical/admission options");
        rejected(() -> group.readEnabled("yes"), "must be true or false");
        rejected(() -> group.readDurationSeconds("900"), "must be 1800");
        group.setEnabled(true);
        rejected(() -> SimZ1Configuration.validate(config), "not installed");
        check(group.isEnabled(), "Enabled request silently rewritten instead of rejected");
        var file = Files.createTempFile("simz1-incident-config-", ".xml");
        var dtd = java.util.Objects.requireNonNull(ConfigUtils.class.getResource("/dtd/config_v2.dtd")).toExternalForm();
        var header = "<?xml version=\"1.0\"?><!DOCTYPE config SYSTEM \"" + dtd + "\">";
        try {
            Files.writeString(file, header + "<config/>");
            var loaded = SimZ1.loadConfiguration(file.toString());
            check(!ConfigUtils.addOrGetModule(loaded, SimZ1IncidentConfigGroup.class).isEnabled(), "Entry point not off by default");
            Files.writeString(file, header + "<config><module name=\"simz1IncidentConsequences\">" +
                "<param name=\"enabled\" value=\"true\"/><param name=\"durationSeconds\" value=\"1800\"/></module></config>");
            var enabled = SimZ1.loadConfiguration(file.toString());
            rejected(() -> SimZ1Configuration.validate(enabled), "not installed");
        } finally { Files.delete(file); }
    }

    private static void offAndCapabilities() {
        var disabled = coordinator(false); var before = disabled.snapshot();
        check(disabled.completeStep(-100, null, null).isEmpty(), "Off consumed input");
        var unreadableStamps = new java.util.AbstractCollection<WorkerStamp>() {
            @Override public int size() { throw new AssertionError("Off read producer size"); }
            @Override public java.util.Iterator<WorkerStamp> iterator() { throw new AssertionError("Off iterated producers"); }
        };
        var unreadableRequests = new java.util.AbstractList<Request>() {
            @Override public int size() { throw new AssertionError("Off read request size"); }
            @Override public Request get(int index) { throw new AssertionError("Off read a request"); }
        };
        check(disabled.completeStep(0, unreadableStamps, unreadableRequests).isEmpty(), "Off consumed unreadable input");
        check(disabled.finishAtHorizon(-100, null).isEmpty() && before == disabled.snapshot(), "Off mutated ledger");
        var baseline = new ArrayDeque<>(List.of("A", "B", "C"));
        var offQueue = new ArrayDeque<>(baseline);
        var baselineDepartures = new ArrayList<String>(); var offDepartures = new ArrayList<String>();
        while (!baseline.isEmpty()) baselineDepartures.add(baseline.removeFirst());
        while (!offQueue.isEmpty()) {
            check(!disabled.snapshot().isVehicleHeld(offQueue.peekFirst()) && !disabled.snapshot().isLaneClosed(LANE), "Off gate closed");
            offDepartures.add(offQueue.removeFirst());
        }
        check(baselineDepartures.equals(offDepartures), "Off fixture FIFO differs");
        var capabilities = SimZ1IncidentLaneCoordinator.nativeCapabilities();
        check(!capabilities.installed() && !capabilities.independentlyAddressableLane() &&
            !capabilities.allRemovalPathsCovered() && !capabilities.arrivalsCovered() &&
            !capabilities.internalTransfersCovered() && !capabilities.ownerPhaseBarrier() &&
            !capabilities.fifoPreserved() && !capabilities.blockers().isEmpty(), "Native guarantees fabricated");
    }

    private static List<SimZ1LaneIncidentEvent> durationAndIdentity() {
        var coordinator = coordinator(true); var request = request("duration", LANE, 0);
        var events = new ArrayList<>(coordinator.completeStep(0, stamps(0), List.of(request)));
        var start = events.get(0); var attributes = start.getAttributes();
        check(start.getTime() == 0 && start.getEventType().equals("simz1LaneIncidentStart"), "Start event timestamp/type");
        check(attributes.get("scope").equals("fixture_only") && attributes.get("physicsEffect").equals("none") &&
            attributes.get("adapterVersion").equals("uninstalled"), "False native claim");
        check(attributes.get("vehicle1").equals("fixture-A-duration") && attributes.get("person1").equals("fixture-person-A-duration") &&
            attributes.get("vehicleType1").equals("fixture-car") && !attributes.containsKey("person2"), "Identity association lost/invented");
        check(Double.parseDouble(attributes.get("scheduledEndTime")) == 1800 && attributes.get("durationSeconds").equals("1800"), "Duration not exactly 1800");
        attributes.put("vehicle1", "tampered");
        check(!start.getAttributes().get("vehicle1").equals("tampered"), "Event attributes are mutable shared state");
        check(coordinator.snapshot().heldVehicleIds().equals(Set.of("fixture-A-duration", "fixture-B-duration")), "Not exactly two selected holds");
        check(coordinator.snapshot().isLaneClosed(LANE) && !coordinator.snapshot().isLaneClosed(PARALLEL), "Parallel lane gate incorrectly closed");
        check(!coordinator.snapshot().isVehicleHeld("fixture-following"), "Follower mislabeled participant");
        var fifo = new ArrayDeque<>(List.of("fixture-A-duration", "fixture-B-duration", "fixture-following"));
        for (long t : new long[]{1, 900 * SECOND, 1799 * SECOND, 1800 * SECOND - 1}) {
            check(coordinator.completeStep(t, stamps(t), List.of()).isEmpty(), "Premature resolve");
            check(coordinator.snapshot().isLaneClosed(LANE) && coordinator.snapshot().isVehicleHeld(fifo.peekFirst()), "Early gate release");
        }
        check(fifo.size() == 3, "Fixture removed held/following vehicle");
        events.addAll(coordinator.completeStep(1800 * SECOND, stamps(1800 * SECOND), List.of()));
        check(events.size() == 2 && events.get(events.size() - 1).getEventType().equals("simz1LaneIncidentResolved") && events.get(events.size() - 1).getTime() == 1800, "Missing exact resolved event");
        check(coordinator.snapshot().heldVehicleIds().isEmpty() && coordinator.snapshot().closedLanes().isEmpty(), "Gate not released at 1800");
        check(new ArrayList<>(fifo).equals(List.of("fixture-A-duration", "fixture-B-duration", "fixture-following")), "Fixture queue reordered");
        rejected(() -> SimZ1LaneIncidentEvent.fixture("native", State.ACTIVE, 0, "x", "o", "r", 0,
            LANE, request.participants(), 0, "e"), "no installed physical adapter");
        rejected(() -> SimZ1LaneIncidentEvent.fixture("fixture_only", State.RESOLVED, 1, "x", "o", "r", 0,
            LANE, request.participants(), 0, "e"), "actual fixture boundary");
        long fractional = 1_234_567;
        var fractionalEvent = SimZ1LaneIncidentEvent.fixture("fixture_only", State.ACTIVE, fractional,
            "fractional", "fractional-opportunity", "fixture-run", 0, LANE, request.participants(), fractional, "fixture");
        var wire = fractionalEvent.getAttributes();
        check(wire.get("time").equals("1.234567") && new java.math.BigDecimal(wire.get("scheduledEndTime"))
            .subtract(new java.math.BigDecimal(wire.get("startTime"))).compareTo(java.math.BigDecimal.valueOf(1800)) == 0,
            "Fractional timestamps lost exact 1800-second interval");
        rejected(() -> request("overflow", LANE, Long.MAX_VALUE), "exact microsecond contract");
        return events;
    }

    private static List<SimZ1LaneIncidentEvent> censorAndFailures() {
        var coordinator = coordinator(true); var request = request("censor", LANE, 10 * SECOND);
        var events = new ArrayList<>(coordinator.completeStep(10 * SECOND, stamps(10 * SECOND), List.of(request)));
        var before = coordinator.snapshot();
        rejected(() -> coordinator.completeStep(11 * SECOND, stamps(11 * SECOND).subList(0, 3), List.of()), "Every worker");
        rejected(() -> coordinator.completeStep(11 * SECOND, List.of(new WorkerStamp(0, 11 * SECOND), new WorkerStamp(1, 11 * SECOND),
            new WorkerStamp(2, 11 * SECOND), new WorkerStamp(2, 11 * SECOND)), List.of()), "duplicate");
        rejected(() -> coordinator.completeStep(11 * SECOND, stamps(10 * SECOND), List.of()), "watermark");
        rejected(() -> coordinator.completeStep(11 * SECOND, stamps(11 * SECOND), List.of(request("clash", LANE, 11 * SECOND))), "already reserves");
        check(before == coordinator.snapshot(), "Invalid batch partially mutated ledger");
        rejected(() -> coordinator.completeStep(1811 * SECOND, stamps(1811 * SECOND), List.of()), "Missed exact");
        check(before == coordinator.snapshot(), "Late boundary mutated ledger");
        events.addAll(coordinator.finishAtHorizon(600 * SECOND, stamps(600 * SECOND)));
        check(events.size() == 2 && events.get(events.size() - 1).getEventType().equals("simz1LaneIncidentCensored") && events.get(events.size() - 1).getTime() == 600, "Censor event timestamp/type");
        check(coordinator.snapshot().heldVehicleIds().size() == 2 && coordinator.snapshot().isLaneClosed(LANE) &&
            coordinator.snapshot().horizonClosed(), "Censor fabricated early release");
        rejected(() -> coordinator.completeStep(1810 * SECOND, stamps(1810 * SECOND), List.of()), "Closed horizon");
        rejected(() -> new Request("i", "o", LANE, List.of(new Participant("a", null, "car", LANE),
            new Participant("b", null, "car", PARALLEL)), 0, "fixture"), "exact affected lane");
        rejected(() -> new Request("i", "o", LANE, List.of(new Participant("a", null, "car", LANE),
            new Participant("a", null, "bus", LANE)), 0, "fixture"), "distinct");
        return events;
    }

    private static void independentBatchAndNoReroll() {
        var first = request("batch-A", LANE, 0);
        var second = request("batch-B", new LaneKey("fixture-other-link", "fixture-other-lane"), 0);
        var left = coordinator(true); var right = coordinator(true);
        var leftEvents = left.completeStep(0, stamps(0), List.of(first, second));
        var rightEvents = right.completeStep(0, stamps(0), List.of(second, first));
        check(leftEvents.stream().map(SimZ1LaneIncidentEvent::getAttributes).toList().equals(
            rightEvents.stream().map(SimZ1LaneIncidentEvent::getAttributes).toList()), "Delivery order changed event ledger");
        check(left.snapshot().heldVehicleIds().size() == 4 && left.snapshot().closedLanes().size() == 2,
            "Independent simultaneous fixture incidents interfered");
        var atHorizon = left.finishAtHorizon(1800 * SECOND, stamps(1800 * SECOND));
        check(atHorizon.size() == 2 && atHorizon.stream().allMatch(e -> e.getEventType().equals("simz1LaneIncidentResolved")),
            "Exact-end horizon censored a completed interval");
        check(left.snapshot().pending().isEmpty() && left.snapshot().horizonClosed(), "Exact horizon did not close cleanly");
        right.completeStep(1800 * SECOND, stamps(1800 * SECOND), List.of());
        var before = right.snapshot(); long next = 1801 * SECOND;
        var reusedId = new Request(first.incidentId(), "fixture-opportunity-new", first.location(), first.participants(), next, "fixture");
        rejected(() -> right.completeStep(next, stamps(next), List.of(reusedId)), "previously consumed");
        var reusedOpportunity = new Request("fixture-incident-new", first.opportunityId(), first.location(), first.participants(), next, "fixture");
        rejected(() -> right.completeStep(next, stamps(next), List.of(reusedOpportunity)), "previously consumed");
        check(before == right.snapshot(), "Duplicate after expiry altered state");
        var valid = request("atomic-valid", PARALLEL, next);
        rejected(() -> right.completeStep(next, stamps(next), List.of(valid, reusedId)), "previously consumed");
        check(before == right.snapshot(), "Invalid second request partially published valid first request");
    }

    private static void fourWorkers() throws Exception {
        var coordinator = coordinator(true); var request = request("workers", LANE, 0);
        var pool = Executors.newFixedThreadPool(4);
        try {
            for (long t : new long[]{0, 1, 1799 * SECOND, 1800 * SECOND}) {
                var snapshot = coordinator.snapshot(); var ready = new CountDownLatch(4);
                var threadIds = java.util.concurrent.ConcurrentHashMap.<Long>newKeySet();
                var tasks = new ArrayList<Callable<WorkerStamp>>();
                for (int worker = 0; worker < 4; worker++) {
                    final int id = worker;
                    tasks.add(() -> {
                        threadIds.add(Thread.currentThread().getId()); ready.countDown();
                        if (!ready.await(5, TimeUnit.SECONDS)) throw new AssertionError("Four fixture producers did not meet");
                        // Producers read immutable published state; no QLane or other owner's queue is touched.
                        for (int read = 0; read < 100; read++) {
                            if (snapshot != coordinator.snapshot()) throw new AssertionError("Collector advanced before producer closure");
                            if (snapshot.isLaneClosed(PARALLEL)) throw new AssertionError("Independent fixture lane affected");
                        }
                        return new WorkerStamp(id, t);
                    });
                }
                var acknowledgments = new ArrayList<WorkerStamp>();
                for (var future : pool.invokeAll(tasks)) acknowledgments.add(future.get());
                check(threadIds.size() == 4, "Fixture did not exercise four producer threads");
                coordinator.completeStep(t, acknowledgments, t == 0 ? List.of(request) : List.of());
            }
            check(coordinator.snapshot().pending().isEmpty(), "Concurrent fixture did not expire");
            pool.submit(() -> rejected(() -> coordinator.completeStep(1801 * SECOND, stamps(1801 * SECOND), List.of()), "Only the fixture collector")).get();
        } finally {
            pool.shutdownNow();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS)) throw new AssertionError("Fixture workers did not terminate");
        }
    }

    /** Optional new XML artifact for parser contract tests; never overwrites an existing file. */
    private static void exportNew(Path file, List<SimZ1LaneIncidentEvent> events) throws Exception {
        try (var stream = Files.newOutputStream(file, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            var xml = XMLOutputFactory.newFactory().createXMLStreamWriter(stream, "UTF-8");
            xml.writeStartDocument("UTF-8", "1.0"); xml.writeStartElement("events");
            for (var event : events) {
                xml.writeEmptyElement("event");
                for (var attribute : new java.util.TreeMap<>(event.getAttributes()).entrySet())
                    xml.writeAttribute(attribute.getKey(), attribute.getValue());
            }
            xml.writeEndElement(); xml.writeEndDocument(); xml.close();
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length > 1) throw new IllegalArgumentException("Usage: SimZ1IncidentLaneCheck [new-fixture-events.xml]");
        configuration(); offAndCapabilities();
        var events = durationAndIdentity(); censorAndFailures();
        independentBatchAndNoReroll();
        fourWorkers();
        if (args.length == 1) exportNew(Path.of(args[0]), events.stream().sorted(java.util.Comparator.comparingDouble(SimZ1LaneIncidentEvent::getTime)).toList());
        System.out.println("PASS: " + assertions + " pure fixture checks; off, exact 1800s, censored, fail-closed, four producers; no native holds installed");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
