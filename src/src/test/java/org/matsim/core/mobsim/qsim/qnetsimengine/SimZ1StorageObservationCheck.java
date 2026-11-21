package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import org.apache.commons.lang3.tuple.Pair;
import org.matsim.api.core.v01.Id;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.MobsimAfterSimStepEvent;
import org.matsim.core.mobsim.qsim.qnetsimengine.vehicleq.FIFOVehicleQ;
import org.matsim.lanes.Lane;

/** Unit fixtures only: real MATSim 15 queue getters and isolated SimZ1 branches.
 * Never creates a controller, runs QSim, generates demand or reads a run folder.
 */
public final class SimZ1StorageObservationCheck {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    /** Deterministic interleaving: model a downstream consumer draining the last
     * buffer entry after isEmpty observed false, but before the caller's peek.
     * No timing lottery, production reflection, or replacement MATSim class.
     */
    private static final class DrainingBuffer extends LinkedList<Pair<QVehicle,Double>> {
        int checks;
        @Override public boolean isEmpty() {
            boolean empty = super.isEmpty();
            if (++checks == 2) clear(); // storage guard first, native getter second
            return empty;
        }
    }

    private record NativeQueue(QueueWithBuffer lane, LinkedList<Pair<QVehicle,Double>> buffer,
                               FIFOVehicleQ travelling) { }

    private static NativeQueue nativeQueue(SimZ1StorageBranchCheck.Fixture fixture,
                                           LinkedList<Pair<QVehicle,Double>> buffer) throws Exception {
        var config = fixture.scenario.getConfig().qsim();
        var context = new NetsimEngineContext(EventsUtils.createEventsManager(), 7.5, null, null,
            config, fixture.timer, null);
        var travelling = new FIFOVehicleQ();
        var lanes = new QueueWithBuffer.Builder(context);
        lanes.setVehicleQueue(travelling);
        lanes.setLaneId(Id.create("out.terminal", Lane.class));
        var links = new QLinkImpl.Builder(context, null);
        links.setLaneFactory(lanes);
        var lane = (QueueWithBuffer) links.build(fixture.scenario.getNetwork().getLinks().get(Id.createLinkId("out")), null).getAcceptingQLane();
        var field = QueueWithBuffer.class.getDeclaredField("buffer");
        field.setAccessible(true);
        field.set(lane, buffer); // test-only controlled native queue state
        return new NativeQueue(lane, buffer, travelling);
    }

    private static void reproduceNativeRace() throws Exception {
        var fixture = new SimZ1StorageBranchCheck.Fixture(false);
        var queue = nativeQueue(fixture, new DrainingBuffer());
        queue.buffer.add(Pair.of(fixture.vehicle, 1.0));
        check(!queue.lane.isNotOfferingVehicle(), "Fixture must initially offer a vehicle");
        try {
            queue.lane.getFirstVehicle();
            throw new AssertionError("Pinned MATSim getter did not reproduce the race");
        } catch (NullPointerException expected) {
            check(Arrays.stream(expected.getStackTrace()).anyMatch(frame ->
                frame.getClassName().equals(QueueWithBuffer.class.getName()) &&
                frame.getMethodName().equals("getFirstVehicle")), "Not the original getter failure");
        }
        check(queue.buffer.isEmpty(), "Interleaving must drain the native buffer");
        System.out.println("REPRODUCED: MATSim 15 buffer isEmpty/peek race; outer guard is insufficient");
    }

    private static void receiverRaceMustNotAbortDecision() throws Exception {
        var fixture = new SimZ1StorageBranchCheck.Fixture(false);
        fixture.scenario.getConfig().qsim().setNumberOfThreads(4);
        var queue = nativeQueue(fixture, new DrainingBuffer());
        queue.buffer.add(Pair.of(fixture.vehicle, 1.0));
        fixture.terminal.lane = queue.lane;
        check(fixture.attempt(11), "Native FORCE must finish despite unavailable receiver head");
        check(fixture.decisions("storage_forced_move").size() == 1, "Lost intervention");
        check(fixture.source.pops == 1 && fixture.receiver.additions == 1, "Changed physical branch");
        var snapshot = fixture.decisions("storage_forced_move").get(0).getAttributes();
        check(snapshot.get("receiverExitHeadsSignalBlocked").equals("unknown"), "Unknown head was reported as zero");
        check(snapshot.get("receiverExitHeadObservation").equals("unavailable_parallel_qsim"), "Missing availability evidence");
        check(snapshot.get("vehicle").equals("v") && snapshot.get("person").equals("p"), "Source identity was replaced");
        check(queue.buffer.size() == 1 && ((DrainingBuffer)queue.buffer).checks == 1, "Diagnosis peeked into or mutated terminal buffer");
    }

    private static void emptyAndPopulatedQueues() throws Exception {
        for (int threads : new int[]{1, 4}) for (int size : new int[]{0, 1, 3}) for (boolean divided : new boolean[]{true, false}) {
            var fixture = new SimZ1StorageBranchCheck.Fixture(false, divided);
            fixture.scenario.getConfig().qsim().setNumberOfThreads(threads);
            var queue = nativeQueue(fixture, new LinkedList<>());
            var second = (QVehicle) Proxy.newProxyInstance(QVehicle.class.getClassLoader(), new Class<?>[]{QVehicle.class},
                (proxy, method, args) -> method.getName().equals("getId") ? Id.createVehicleId("receiver-v") : method.invoke(fixture.vehicle, args));
            for (int i=0; i<size; i++) queue.buffer.add(Pair.of(i==0 ? fixture.vehicle : second, 1.0));
            // A full receiving vehQueue can coexist with an empty outgoing buffer.
            queue.travelling.add(second);
            var load = QueueWithBuffer.class.getDeclaredField("usedStorageCapacity");
            load.setAccessible(true); load.setDouble(queue.lane, queue.lane.getStorageCapacity());
            if (divided) fixture.terminal.lane = queue.lane;
            else fixture.receiver.lane = queue.lane;
            var before = queue.buffer.toArray();
            var travellingBefore = queue.travelling.toArray();
            check(!fixture.attempt(5), "Full receiver must WAIT");
            check(Arrays.equals(before, queue.buffer.toArray()), "Diagnostic changed native buffer/FIFO");
            check(Arrays.equals(travellingBefore, queue.travelling.toArray()), "Diagnostic changed travelling queue");
            check(fixture.source.pops == 0 && fixture.receiver.additions == 0, "Diagnostic moved a car");
            var snapshot = fixture.decisions("storage_wait").get(0).getAttributes();
            check(snapshot.get("receiverExitQueuesOffering").equals(size==0 ? "0" : "1"), "Buffer presence confused with travelling occupancy");
            check(snapshot.get("vehicle").equals("v"), "Terminal car substituted for decision vehicle");
            check(snapshot.get("receiverExitHeadsSignalBlocked").equals(threads==1 ? "0" : "unknown"), "Incorrect head availability");
        }
        // An entirely empty native queue also returns null legitimately.
        var fixture = new SimZ1StorageBranchCheck.Fixture(false);
        var empty = nativeQueue(fixture, new LinkedList<>());
        check(empty.lane.getFirstVehicle() == null, "Native empty queue must have no first vehicle");
        fixture.terminal.lane = empty.lane;
        check(!fixture.attempt(5), "Empty receiver terminal must not abort WAIT");

        var missing = new SimZ1StorageBranchCheck.Fixture(false);
        missing.terminal.vehicle = null; // unavailable observation, never fabricate signal evidence
        check(!missing.attempt(5), "Unavailable head must not abort WAIT");
        var snapshot = missing.decisions("storage_wait").get(0).getAttributes();
        check(snapshot.get("receiverExitHeadObservation").equals("unavailable_head") &&
            snapshot.get("receiverExitHeadsSignalBlocked").equals("unknown"), "Missing head became a blocking cause");
    }

    private static List<?> physicalOutcome(boolean enabled, boolean remove, boolean full, boolean red) throws Exception {
        var fixture = new SimZ1StorageBranchCheck.Fixture(remove, true, enabled, EventsUtils.createEventsManager());
        fixture.scenario.getConfig().qsim().setNumberOfThreads(4);
        fixture.terminal.rejectHeadRead = true;
        fixture.source.green = !red;
        fixture.receiver.load = full ? 1 : 0;
        var moved = new ArrayList<Boolean>();
        if (full && !red) { moved.add(fixture.attempt(5)); moved.add(fixture.attempt(10)); }
        moved.add(fixture.attempt(11));
        var physicalEvents = fixture.events.stream().filter(e -> !e.getEventType().equals(Zona1NativeDiagnostics.EVENT_TYPE))
            .map(e -> e.getAttributes()).toList();
        var decisions = fixture.events.stream().filter(e -> e.getEventType().equals(Zona1NativeDiagnostics.EVENT_TYPE))
            .map(e -> List.of(e.getAttributes().get("vehicle"), e.getAttributes().get("person"),
                e.getAttributes().get("reason"), e.getAttributes().get("decision"), e.getTime())).toList();
        check(fixture.terminal.headReads == 0, "Parallel diagnostics queried foreign head");
        return List.of(moved, physicalEvents, decisions, fixture.source.pops, fixture.receiver.additions,
            fixture.receiver.load, fixture.receiver.admissionQueries, fixture.advanced, fixture.aborted, fixture.arranged);
    }

    private static void physicalEquivalenceAndFailurePropagation() throws Exception {
        for (boolean remove : new boolean[]{false, true}) for (boolean full : new boolean[]{false, true})
            for (boolean red : new boolean[]{false, true})
                check(physicalOutcome(true,remove,full,red).equals(physicalOutcome(false,remove,full,red)),
                    "Receiver enrichment changed physical results/counters");
        var fixture = new SimZ1StorageBranchCheck.Fixture(false);
        fixture.receiver.failAdmission = true;
        try {
            fixture.attempt(11);
            throw new AssertionError("Physical failure swallowed");
        } catch (InvocationTargetException expected) {
            check(expected.getCause() instanceof IllegalStateException &&
                expected.getCause().getMessage().equals("fixture physical admission failure"), "Changed physical failure");
        }
    }

    private static void postStepEmptyQueue() throws Exception {
        var fixture = new SimZ1StorageBranchCheck.Fixture(false);
        fixture.scenario.getConfig().qsim().setNumberOfThreads(4);
        var empty = nativeQueue(fixture, new LinkedList<>());
        fixture.source.lane = empty.lane;
        fixture.diagnostics.registerQueueLink(fixture.fromLink);
        fixture.diagnostics.notifyMobsimAfterSimStep(new MobsimAfterSimStepEvent<>(null, 5));
        check(fixture.events.isEmpty(), "Empty post-step queue invented a vehicle or WAIT");
    }

    private static void parallelEventDelivery() throws Exception {
        var config = ConfigUtils.createConfig();
        config.parallelEventHandling().setNumberOfThreads(2);
        config.parallelEventHandling().setSynchronizeOnSimSteps(true);
        var manager = EventsUtils.createEventsManager(config);
        check(manager.getClass().getSimpleName().equals("SimStepParallelEventsManagerImpl"), "Wrong parallel events implementation");
        var fixture = new SimZ1StorageBranchCheck.Fixture(false, true, true, manager);
        var secondHandler = new java.util.concurrent.ConcurrentLinkedQueue<org.matsim.api.core.v01.events.Event>();
        manager.addHandler((BasicEventHandler) secondHandler::add);
        fixture.scenario.getConfig().qsim().setNumberOfThreads(4);
        fixture.terminal.rejectHeadRead = true;
        manager.initProcessing();
        try {
            check(!fixture.attempt(5), "Expected WAIT"); manager.afterSimStep(5);
            check(!fixture.attempt(10), "Expected strict-timeout WAIT"); manager.afterSimStep(10);
            check(fixture.attempt(11), "Expected FORCE"); manager.afterSimStep(11);
        } finally { manager.finishProcessing(); }
        check(fixture.decisions("storage_wait").size()==2 && fixture.decisions("storage_forced_move").size()==1,
            "Parallel event delivery lost or duplicated storage counters");
        check(fixture.count("entered link")==1 && fixture.count("left link")==1, "Parallel delivery changed crossing identity/count");
        check(secondHandler.stream().map(e -> e.getAttributes()).toList().equals(
            fixture.events.stream().map(e -> e.getAttributes()).toList()), "Parallel handlers received different events/order");
        for (var event : fixture.events) if (event.getEventType().equals(Zona1NativeDiagnostics.EVENT_TYPE))
            check(event.getAttributes().get("vehicle").equals("v"), "Parallel event identity corrupted");
    }

    public static void main(String[] args) throws Exception {
        try {
            reproduceNativeRace();
            receiverRaceMustNotAbortDecision();
            emptyAndPopulatedQueues();
            physicalEquivalenceAndFailurePropagation();
            postStepEmptyQueue();
            parallelEventDelivery();
            System.out.println("PASS: empty/one/multiple queues, receiving/terminal buffers, unavailable heads, unchanged FIFO/decisions/identities, WAIT/FORCE/removal, parallel event delivery; no QSim run");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
