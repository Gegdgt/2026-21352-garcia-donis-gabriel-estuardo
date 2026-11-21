package gt.edu.uvg.sim.zona1;

import java.util.List;
import java.util.Map;
import org.matsim.api.core.v01.events.Event;

/** Wire-contract fixture. No production publisher or physical lane adapter exists. */
public final class SimZ1LaneIncidentEvent extends Event {
    public static final String SCHEMA = "simz1-lane-incident-v1";
    public static final long DURATION_US = 1_800_000_000L;
    public static final long MAX_SAFE_US = 9_007_199_254_740_991L;
    public enum State {
        ACTIVE("simz1LaneIncidentStart", "active"),
        RESOLVED("simz1LaneIncidentResolved", "resolved"),
        CENSORED("simz1LaneIncidentCensored", "censored");
        final String eventType, wireState;
        State(String eventType, String wireState) { this.eventType = eventType; this.wireState = wireState; }
    }

    public record LaneKey(String link, String lane) {
        public LaneKey { requireText(link, "link"); requireText(lane, "lane"); }
    }
    public record Participant(String vehicleId, String personId, String vehicleTypeId, LaneKey location) {
        public Participant {
            requireText(vehicleId, "vehicle"); requireText(vehicleTypeId, "vehicleType");
            if (personId != null) requireText(personId, "person");
            if (location == null) throw new IllegalArgumentException("Missing exact native lane location");
        }
    }

    private final State state;
    private final String incidentId, opportunityId, runId, evidenceRef;
    private final int iteration;
    private final long timeUs, startUs, endUs;
    private final LaneKey location;
    private final List<Participant> participants;

    private SimZ1LaneIncidentEvent(String scope, State state, long timeUs, String incidentId,
            String opportunityId, String runId, int iteration, LaneKey location,
            List<Participant> participants, long startUs, String evidenceRef) {
        super(timeUs / 1_000_000.0);
        if (!"fixture_only".equals(scope)) throw new IllegalArgumentException(
            "Native incident events unavailable: no installed physical adapter evidence");
        if (state == null || iteration < 0)
            throw new IllegalArgumentException("Invalid incident state, time or iteration");
        requireTime(timeUs); requireTime(startUs);
        if (startUs > MAX_SAFE_US - DURATION_US)
            throw new IllegalArgumentException("Scheduled end exceeds exact microsecond contract");
        long until = Math.addExact(startUs, DURATION_US);
        if ((state == State.ACTIVE && timeUs != startUs) ||
            (state == State.RESOLVED && timeUs != until) ||
            (state == State.CENSORED && (timeUs < startUs || timeUs >= until)))
            throw new IllegalArgumentException("Event timestamp must describe the actual fixture boundary");
        requireText(incidentId, "incidentId"); requireText(opportunityId, "opportunityId");
        requireText(runId, "runId"); requireText(evidenceRef, "evidenceRef");
        if (location == null || participants == null || participants.size() != 2 ||
            participants.stream().anyMatch(p -> p == null || !location.equals(p.location())) ||
            participants.get(0).vehicleId().equals(participants.get(1).vehicleId()))
            throw new IllegalArgumentException("Exactly two distinct vehicles on the same exact LaneKey are required");
        this.state = state; this.incidentId = incidentId; this.opportunityId = opportunityId;
        this.runId = runId; this.iteration = iteration; this.location = location;
        this.participants = participants.stream().sorted(java.util.Comparator.comparing(Participant::vehicleId)).toList();
        this.timeUs = timeUs; this.startUs = startUs; this.endUs = until; this.evidenceRef = evidenceRef;
    }

    public static SimZ1LaneIncidentEvent fixture(String scope, State state, long timeUs,
            String incidentId, String opportunityId, String runId, int iteration,
            LaneKey location, List<Participant> participants, long startUs, String evidenceRef) {
        return new SimZ1LaneIncidentEvent(scope, state, timeUs, incidentId, opportunityId, runId,
            iteration, location, participants, startUs, evidenceRef);
    }

    static void requireText(String value, String field) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing " + field);
    }
    static void requireTime(long value) {
        if (value < 0 || value > MAX_SAFE_US) throw new IllegalArgumentException("Time outside exact microsecond contract");
    }
    private static String seconds(long microseconds) {
        return java.math.BigDecimal.valueOf(microseconds, 6).stripTrailingZeros().toPlainString();
    }

    @Override public String getEventType() { return state.eventType; }
    @Override public Map<String, String> getAttributes() {
        var result = super.getAttributes();
        // Event.getTime() remains the native seconds API; XML retains exact microseconds.
        result.put("time", seconds(timeUs));
        result.put("schema", SCHEMA); result.put("scope", "fixture_only");
        result.put("physicsEffect", "none"); result.put("adapterVersion", "uninstalled");
        result.put("intendedPhysicsEffect", "independent_lane_hold");
        result.put("adapterEvidence", "fixture_gate_only_not_native");
        result.put("incidentId", incidentId); result.put("opportunityId", opportunityId);
        result.put("runId", runId); result.put("iteration", Integer.toString(iteration));
        result.put("link", location.link()); result.put("lane", location.lane());
        result.put("startTime", seconds(startUs));
        result.put("scheduledEndTime", seconds(endUs));
        result.put("durationSeconds", "1800"); result.put("evidenceRef", evidenceRef);
        result.put("state", state.wireState);
        for (int i = 0; i < participants.size(); i++) {
            var p = participants.get(i); String suffix = Integer.toString(i + 1);
            result.put("vehicle" + suffix, p.vehicleId());
            result.put("vehicleType" + suffix, p.vehicleTypeId());
            if (p.personId() != null) result.put("person" + suffix, p.personId());
        }
        return result;
    }
}
