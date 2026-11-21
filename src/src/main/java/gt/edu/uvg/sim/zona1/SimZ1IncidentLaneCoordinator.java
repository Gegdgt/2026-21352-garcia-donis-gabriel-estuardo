package gt.edu.uvg.sim.zona1;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.LaneKey;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.Participant;
import gt.edu.uvg.sim.zona1.SimZ1LaneIncidentEvent.State;

/**
 * Fixture-only gate ledger, NOT a QLane/QNode adapter. No native vehicle, queue,
 * arrival, capacity, signal, RNG or event manager is read or changed here.
 * One collector owns mutations after immutable acknowledgments from every worker.
 */
public final class SimZ1IncidentLaneCoordinator {
    public record NativeCapabilities(boolean installed, boolean independentlyAddressableLane,
            boolean allRemovalPathsCovered, boolean arrivalsCovered, boolean internalTransfersCovered,
            boolean ownerPhaseBarrier, boolean fifoPreserved, List<String> blockers) {
        public NativeCapabilities { blockers = List.copyOf(blockers); }
    }
    public static NativeCapabilities nativeCapabilities() {
        return new NativeCapabilities(false, false, false, false, false, false, false, List.of(
            "QLaneI has no exact vehicle hold/release contract",
            "QueueWithBuffer arrival and queue-to-buffer paths need reviewed hooks",
            "QLinkLanesImpl internal lane transfers bypass QNode",
            "represented lanes and shared upstream FIFO are not independent physical lanes",
            "no paired observer, native closure adapter or verified incident registry installed"));
    }
    public record WorkerStamp(int worker, long completedTimeUs) { }
    public record Request(String incidentId, String opportunityId, LaneKey location,
            List<Participant> participants, long startUs, String evidenceRef) {
        public Request {
            SimZ1LaneIncidentEvent.requireText(incidentId, "incidentId");
            SimZ1LaneIncidentEvent.requireText(opportunityId, "opportunityId");
            SimZ1LaneIncidentEvent.requireText(evidenceRef, "evidenceRef");
            SimZ1LaneIncidentEvent.requireTime(startUs);
            if (startUs > SimZ1LaneIncidentEvent.MAX_SAFE_US - SimZ1LaneIncidentEvent.DURATION_US)
                throw new IllegalArgumentException("Scheduled end exceeds exact microsecond contract");
            if (location == null || participants == null || participants.size() != 2 ||
                participants.stream().anyMatch(p -> p == null || !location.equals(p.location())) ||
                participants.get(0).vehicleId().equals(participants.get(1).vehicleId()))
                throw new IllegalArgumentException("Both participants must be distinct and on the exact affected lane");
            participants = participants.stream().sorted(Comparator.comparing(Participant::vehicleId)).toList();
        }
        long endUs() { return Math.addExact(startUs, SimZ1LaneIncidentEvent.DURATION_US); }
    }
    public record Snapshot(long timeUs, Map<String, Request> pending, Set<String> heldVehicleIds,
            Set<LaneKey> closedLanes, boolean horizonClosed) {
        public Snapshot {
            pending = Map.copyOf(pending); heldVehicleIds = Set.copyOf(heldVehicleIds);
            closedLanes = Set.copyOf(closedLanes);
        }
        /** A fixture gate decision only; it says nothing about native QSim state. */
        public boolean isVehicleHeld(String id) { return heldVehicleIds.contains(id); }
        public boolean isLaneClosed(LaneKey lane) { return closedLanes.contains(lane); }
    }

    private final boolean enabled;
    private final String runId;
    private final int iteration, workers;
    private final long collectorThread = Thread.currentThread().getId();
    private final Set<String> seenIncidents = new HashSet<>(), seenOpportunities = new HashSet<>();
    private volatile Snapshot snapshot = new Snapshot(-1, Map.of(), Set.of(), Set.of(), false);

    private SimZ1IncidentLaneCoordinator(boolean enabled, String runId, int iteration, int workers) {
        SimZ1LaneIncidentEvent.requireText(runId, "runId");
        if (iteration < 0 || workers < 1) throw new IllegalArgumentException("Invalid fixture iteration/workers");
        this.enabled = enabled; this.runId = runId; this.iteration = iteration; this.workers = workers;
    }
    public static SimZ1IncidentLaneCoordinator forFixtures(boolean enabled, String runId, int iteration, int workers) {
        return new SimZ1IncidentLaneCoordinator(enabled, runId, iteration, workers);
    }
    public Snapshot snapshot() { return snapshot; }

    public List<SimZ1LaneIncidentEvent> completeStep(long timeUs, Collection<WorkerStamp> stamps,
            List<Request> requests) {
        return apply(timeUs, stamps, requests, false);
    }
    public List<SimZ1LaneIncidentEvent> finishAtHorizon(long timeUs, Collection<WorkerStamp> stamps) {
        return apply(timeUs, stamps, List.of(), true);
    }
    private List<SimZ1LaneIncidentEvent> apply(long timeUs, Collection<WorkerStamp> stamps,
            List<Request> requests, boolean finish) {
        if (!enabled) return List.of(); // Off does not consume or inspect producer/request input.
        if (Thread.currentThread().getId() != collectorThread)
            throw new IllegalStateException("Only the fixture collector may mutate the ledger");
        SimZ1LaneIncidentEvent.requireTime(timeUs);
        var before = snapshot;
        if (before.horizonClosed() || timeUs < 0 || timeUs <= before.timeUs())
            throw new IllegalStateException("Closed horizon or repeated/decreasing simulated barrier");
        if (stamps == null || stamps.size() != workers)
            throw new IllegalStateException("Every worker must close this simulated step");
        var ids = new HashSet<Integer>();
        for (var stamp : stamps) {
            if (stamp == null || stamp.worker() < 0 || stamp.worker() >= workers ||
                    stamp.completedTimeUs() != timeUs || !ids.add(stamp.worker()))
                throw new IllegalStateException("Incomplete, duplicate or mismatched worker watermark");
        }
        if (requests == null) throw new IllegalArgumentException("Missing fixture requests");
        var active = new HashMap<>(before.pending());
        var expired = new ArrayList<Request>();
        for (var prior : before.pending().values()) {
            if (timeUs > prior.endUs()) throw new IllegalStateException(
                "Missed exact 1800-second boundary; cannot claim an on-time native release");
            if (timeUs == prior.endUs()) { active.remove(prior.incidentId()); expired.add(prior); }
        }
        var nextIds = new HashSet<>(seenIncidents);
        var nextOpportunities = new HashSet<>(seenOpportunities);
        var ordered = new ArrayList<>(requests);
        if (ordered.stream().anyMatch(r -> r == null)) throw new IllegalArgumentException("Null fixture request");
        ordered.sort(Comparator.comparing(Request::incidentId));
        for (var request : ordered) {
            if (request.startUs() != timeUs || !nextIds.add(request.incidentId()) ||
                    !nextOpportunities.add(request.opportunityId()))
                throw new IllegalStateException("Late/duplicate fixture request or previously consumed opportunity");
            for (var prior : active.values()) {
                if (prior.location().equals(request.location()) || prior.participants().stream().anyMatch(p ->
                        request.participants().stream().anyMatch(q -> p.vehicleId().equals(q.vehicleId()))))
                    throw new IllegalStateException("An active incident already reserves this fixture lane or vehicle");
            }
            active.put(request.incidentId(), request);
        }
        // All validation precedes publication; an invalid batch leaves state unchanged.
        var events = new ArrayList<SimZ1LaneIncidentEvent>();
        expired.sort(Comparator.comparing(Request::incidentId));
        for (var prior : expired) events.add(event(prior, State.RESOLVED, timeUs));
        for (var request : ordered) events.add(event(request, State.ACTIVE, timeUs));
        if (finish) for (var pending : active.values().stream().sorted(Comparator.comparing(Request::incidentId)).toList())
            events.add(event(pending, State.CENSORED, timeUs));
        var held = new HashSet<String>(); var closed = new HashSet<LaneKey>();
        for (var pending : active.values()) {
            pending.participants().forEach(p -> held.add(p.vehicleId())); closed.add(pending.location());
        }
        seenIncidents.clear(); seenIncidents.addAll(nextIds);
        seenOpportunities.clear(); seenOpportunities.addAll(nextOpportunities);
        snapshot = new Snapshot(timeUs, active, held, closed, finish);
        return List.copyOf(events);
    }
    private SimZ1LaneIncidentEvent event(Request request, State state, long timeUs) {
        return SimZ1LaneIncidentEvent.fixture("fixture_only", state, timeUs, request.incidentId(),
            request.opportunityId(), runId, iteration, request.location(), request.participants(),
            request.startUs(), request.evidenceRef());
    }
}
