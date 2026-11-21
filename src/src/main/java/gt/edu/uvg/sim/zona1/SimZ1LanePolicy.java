package gt.edu.uvg.sim.zona1;

import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * Isolated, deterministic decision contract for a future microscopic adapter.
 * This class never moves a QVehicle, changes a MATSim queue or draws a vehicle.
 * Its REQUEST_CHANGE is a request requiring atomic revalidation and reservation,
 * not an executed lane change. Installed QSim does not supply this input state.
 *
 * Coordinates use a common straight-road metric frame: s increases downstream,
 * lateral metres increase to the left, and lane index zero is the rightmost lane.
 * Curves must be split into validated local frames by the future native adapter;
 * deriving these envelopes from replay interpolation is not valid evidence.
 */
public final class SimZ1LanePolicy {
    private SimZ1LanePolicy() { }
    public static final String POLICY = "scenario-lane-preference-v1";
    /** Only numerical coordinate roundoff may separate adjacent lane boundaries. */
    public static final double ADJACENCY_TOLERANCE_M = 1e-6;
    public static final double MINIMUM_GAP_M = .10;

    public record Settings(boolean enabled, double minimumAdvanceM, double minimumGapM,
            double slowSpeedMps, double lookaheadSeconds) {
        public Settings {
            positive(minimumAdvanceM, "minimumAdvanceM");
            positive(minimumGapM, "minimumGapM");
            if (minimumGapM < MINIMUM_GAP_M)
                throw new IllegalArgumentException("minimumGapM must be at least 0.10 metres");
            positive(slowSpeedMps, "slowSpeedMps");
            positive(lookaheadSeconds, "lookaheadSeconds");
        }
        public static Settings defaults(boolean enabled) { return new Settings(enabled, 8, 2, 8.33, 5); }
    }

    /** Explicit lane rules from the scenario. Empty permissions permit nobody.
     * evidenceId identifies the network/rules source, never just a lane count.
     * localPolicyAllowed is false where local rules override the preference.
     * changeTargets must explicitly authorize the crossed lane boundary.
     */
    public record Lane(String id, String directedLink, String direction, int indexFromRight,
            double lateralM, double widthM, double startM, double stopBoundaryM,
            Set<String> allowedModes, Set<String> allowedVehicleClasses, Set<String> allowedExits,
            Set<String> changeTargets, String evidenceId, boolean localPolicyAllowed) {
        public Lane {
            nonempty(id, "lane id"); nonempty(directedLink, "directed link"); nonempty(direction, "direction");
            if (indexFromRight < 0) throw new IllegalArgumentException("Negative lane index");
            finite(lateralM, "lateralM"); positive(widthM, "widthM"); finite(startM, "startM");
            finite(stopBoundaryM, "stopBoundaryM");
            if (stopBoundaryM <= startM) throw new IllegalArgumentException("Invalid stopping interval");
            allowedModes = Set.copyOf(allowedModes); allowedVehicleClasses = Set.copyOf(allowedVehicleClasses);
            allowedExits = Set.copyOf(allowedExits); changeTargets = Set.copyOf(changeTargets);
            evidenceId = evidenceId == null ? "" : evidenceId;
        }
    }

    public record Vehicle(String id, String mode, String vehicleClass, String nextLink,
            double centerM, double lengthM, double widthM, double desiredSpeedMps) {
        public Vehicle {
            nonempty(id, "vehicle id"); nonempty(mode, "mode"); nonempty(vehicleClass, "vehicle class");
            nonempty(nextLink, "next link"); finite(centerM, "centerM");
            positive(lengthM, "lengthM"); positive(widthM, "widthM"); positive(desiredSpeedMps, "desiredSpeedMps");
        }
    }

    /** Conservative occupied envelope for the ENTIRE requested maneuver horizon,
     * including actual motion bounds/reservations, not a point-in-time snapshot.
     */
    public record Occupancy(String vehicleId, double rearM, double frontM, double rightM, double leftM) {
        public Occupancy {
            nonempty(vehicleId, "occupant id"); finite(rearM, "rearM"); finite(frontM, "frontM");
            finite(rightM, "rightM"); finite(leftM, "leftM");
            if (frontM <= rearM || leftM <= rightM) throw new IllegalArgumentException("Invalid occupied envelope");
        }
    }

    /** Native adapter must provide one coherent snapshot for source, target and
     * every intervening swept envelope. Expected advances share this horizon and
     * are used only for the gain decision. sweptAdvanceM is a separate conservative
     * upper bound on the ego vehicle's downstream travel throughout the complete
     * maneuver, including uncertainty and execution/reservation duration. It must
     * cover both expected advances and must not be inferred from a mean forecast.
     * Motion must be monotone downstream in this frame; reverse maneuvers are not
     * supported. egoSweep is the independently supplied native bounding envelope
     * of the whole body throughout the maneuver, INCLUDING yaw/rotation and any
     * motion uncertainty. It must contain both lane-aligned endpoint poses and
     * the travel bound. Width/length alone cannot produce a safe rotating sweep,
     * especially for buses or trucks. Only explicitly supplied physical evidence
     * may establish that bound; this policy cannot reconstruct it from snapshots.
     * The envelope determines both stop-line and occupied-space checks.
     * receiverHasStorage is a vehicle-aware reservation, not load < capacity.
     */
    public record Request(Vehicle vehicle, Lane source, Lane target,
            double sourceAdvanceM, double targetAdvanceM, double sweptAdvanceM, double horizonSeconds,
            Occupancy egoSweep, boolean completePhysicalEvidence, boolean receiverHasStorage, List<Occupancy> occupancy) {
        public Request {
            Objects.requireNonNull(vehicle); Objects.requireNonNull(source); Objects.requireNonNull(target); Objects.requireNonNull(egoSweep);
            nonnegative(sourceAdvanceM, "sourceAdvanceM"); nonnegative(targetAdvanceM, "targetAdvanceM");
            nonnegative(sweptAdvanceM, "sweptAdvanceM");
            if (sweptAdvanceM < Math.max(sourceAdvanceM, targetAdvanceM))
                throw new IllegalArgumentException("sweptAdvanceM must bound both expected advances");
            positive(horizonSeconds, "horizonSeconds"); occupancy = List.copyOf(occupancy);
        }
    }

    public enum Action { DISABLED, KEEP, REQUEST_CHANGE }
    public record Decision(Action action, String reason, String targetLane, double advanceGainM) { }

    public static Decision evaluate(Settings settings, Request request) {
        Objects.requireNonNull(settings);
        // No reads of native state and no new requirements when disabled.
        if (!settings.enabled()) return new Decision(Action.DISABLED, "policy_disabled", "", 0);
        Objects.requireNonNull(request);
        var vehicle = request.vehicle(); var source = request.source(); var target = request.target();
        double gain = request.targetAdvanceM() - request.sourceAdvanceM();
        if (!request.completePhysicalEvidence() || source.evidenceId().isBlank() || target.evidenceId().isBlank())
            return keep("physical_evidence_missing", gain);
        if (Double.compare(request.horizonSeconds(), settings.lookaheadSeconds()) != 0)
            return keep("prediction_horizon_mismatch", gain);
        if (!source.localPolicyAllowed() || !target.localPolicyAllowed()) return keep("local_rule_override", gain);
        if (!source.directedLink().equals(target.directedLink()) || !source.direction().equals(target.direction()))
            return keep("different_link_or_direction", gain);
        if (source.id().equals(target.id()) || Math.abs(source.indexFromRight() - target.indexFromRight()) != 1)
            return keep("target_not_adjacent", gain);
        // Index adjacency alone is insufficient: the actual lane boundaries must
        // touch. A median, void or intervening lane is not a legal lateral path.
        double lateral = target.lateralM() - source.lateralM();
        double adjacentCenterDistance = source.widthM() / 2 + target.widthM() / 2;
        if (!Double.isFinite(lateral) || Math.signum(lateral) != Math.signum(target.indexFromRight() - source.indexFromRight()) ||
                Math.abs(Math.abs(lateral) - adjacentCenterDistance) > ADJACENCY_TOLERANCE_M)
            return keep("invalid_lane_geometry", gain);
        if (!source.changeTargets().contains(target.id())) return keep("lane_boundary_forbidden", gain);
        if (!allowed(source, vehicle) || !allowed(target, vehicle)) return keep("mode_class_or_turn_forbidden", gain);
        if (vehicle.widthM() > Math.min(source.widthM(), target.widthM())) return keep("vehicle_too_wide", gain);
        double rear = vehicle.centerM() - vehicle.lengthM() / 2;
        double front = vehicle.centerM() + vehicle.lengthM() / 2;
        var sweep = request.egoSweep();
        double endpointRight = Math.min(source.lateralM(), target.lateralM()) - vehicle.widthM() / 2;
        double endpointLeft = Math.max(source.lateralM(), target.lateralM()) + vehicle.widthM() / 2;
        if (!sweep.vehicleId().equals(vehicle.id()) || sweep.rearM() > rear ||
                sweep.frontM() < front + request.sweptAdvanceM() ||
                sweep.rightM() > endpointRight || sweep.leftM() < endpointLeft)
            return keep("invalid_ego_swept_envelope", gain);
        double roadRight = Math.min(source.lateralM() - source.widthM() / 2, target.lateralM() - target.widthM() / 2);
        double roadLeft = Math.max(source.lateralM() + source.widthM() / 2, target.lateralM() + target.widthM() / 2);
        if (sweep.rightM() < roadRight || sweep.leftM() > roadLeft)
            return keep("swept_envelope_outside_lanes", gain);
        if (sweep.rearM() < Math.max(source.startM(), target.startM()) ||
                sweep.frontM() > Math.min(source.stopBoundaryM(), target.stopBoundaryM()))
            return keep("insufficient_physical_length", gain);
        if (!request.receiverHasStorage()) return keep("receiver_storage_rejected", gain);
        if (gain < settings.minimumAdvanceM()) return keep("insufficient_advance", gain);
        // Both preferences require a measurable gain; never override local rules
        // merely to put a slow vehicle right or a fast vehicle left.
        boolean slow = vehicle.desiredSpeedMps() <= settings.slowSpeedMps();
        boolean right = target.indexFromRight() < source.indexFromRight();
        if (slow != right) return keep("speed_preference_not_satisfied", gain);
        double sweptRear = sweep.rearM() - settings.minimumGapM();
        double sweptFront = sweep.frontM() + settings.minimumGapM();
        for (var other : request.occupancy()) {
            if (other.vehicleId().equals(vehicle.id())) continue;
            if (other.frontM() > sweptRear && other.rearM() < sweptFront &&
                    other.leftM() > sweep.rightM() && other.rightM() < sweep.leftM())
                return keep("swept_envelope_occupied", gain);
        }
        return new Decision(Action.REQUEST_CHANGE, slow ? "right_slow_with_gain" : "left_fast_with_gain", target.id(), gain);
    }

    private static boolean allowed(Lane lane, Vehicle vehicle) {
        return lane.allowedModes().contains(vehicle.mode()) && lane.allowedVehicleClasses().contains(vehicle.vehicleClass()) &&
            lane.allowedExits().contains(vehicle.nextLink());
    }
    private static Decision keep(String reason, double gain) { return new Decision(Action.KEEP, reason, "", gain); }
    private static void nonempty(String value, String name) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing " + name);
    }
    private static void finite(double value, String name) {
        if (!Double.isFinite(value)) throw new IllegalArgumentException("Non-finite " + name);
    }
    private static void positive(double value, String name) {
        finite(value, name); if (value <= 0) throw new IllegalArgumentException("Non-positive " + name);
    }
    private static void nonnegative(double value, String name) {
        finite(value, name); if (value < 0) throw new IllegalArgumentException("Negative " + name);
    }
}
