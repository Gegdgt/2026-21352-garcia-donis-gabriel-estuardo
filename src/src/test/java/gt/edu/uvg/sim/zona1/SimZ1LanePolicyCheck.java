package gt.edu.uvg.sim.zona1;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import static gt.edu.uvg.sim.zona1.SimZ1LanePolicy.*;

/** Pure Java fixture, no MATSim engine, renderer, events, files or population. */
public final class SimZ1LanePolicyCheck {
    private static final Settings ON = Settings.defaults(true);
    private static final Set<String> CLASSES = Set.of("car", "bus", "truck");
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static Lane lane(int index) {
        return new Lane("lane" + index, "forward", "east", index, index * 3.5, 3.5, 0, 100,
            Set.of("car", "pt"), CLASSES, Set.of("straight", "right"), Set.of("lane0", "lane1", "lane2"), "fixture:explicit-local-rules", true);
    }
    private static Lane rules(Lane lane, String direction, Set<String> modes, Set<String> classes,
            Set<String> exits, Set<String> boundaries, String evidence, boolean enabled) {
        return new Lane(lane.id(), lane.directedLink(), direction, lane.indexFromRight(), lane.lateralM(),
            lane.widthM(), lane.startM(), lane.stopBoundaryM(), modes, classes, exits, boundaries, evidence, enabled);
    }
    private static Vehicle vehicle(String type, double length, double speed) {
        return new Vehicle("ego", type.equals("bus") ? "pt" : "car", type, "straight", 20, length, 2.4, speed);
    }
    private static Request request(Vehicle vehicle, Lane from, Lane to, List<Occupancy> occupancy) {
        return new Request(vehicle, from, to, 3, 15, 15, 5, straightSweep(vehicle, from, to, 15), true, true, occupancy);
    }
    // Only these synthetic fixtures prescribe a straight zero-yaw maneuver.
    // Production may not derive a rotating body's sweep from endpoint width.
    private static Occupancy straightSweep(Vehicle vehicle, Lane from, Lane to, double advanceBound) {
        return new Occupancy(vehicle.id(), vehicle.centerM() - vehicle.lengthM() / 2,
            vehicle.centerM() + vehicle.lengthM() / 2 + advanceBound,
            Math.min(from.lateralM(), to.lateralM()) - vehicle.widthM() / 2,
            Math.max(from.lateralM(), to.lateralM()) + vehicle.widthM() / 2);
    }
    private static void reject(Request request, String reason) {
        var decision = evaluate(ON, request);
        check(decision.action() == Action.KEEP && decision.reason().equals(reason), "Expected " + reason + " but got " + decision);
    }
    public static void main(String[] args) throws Exception {
        var right = lane(0); var left = lane(1);
        var fast = vehicle("car", 4.5, 14); var slow = vehicle("car", 4.5, 5);
        var faster = request(fast, right, left, List.of());
        check(evaluate(ON, faster).action() == Action.REQUEST_CHANGE, "Fast vehicle cannot request legal faster left lane");
        check(evaluate(ON, request(slow, left, right, List.of())).reason().equals("right_slow_with_gain"), "Slow right preference missing");
        reject(request(slow, right, left, List.of()), "speed_preference_not_satisfied");
        reject(new Request(fast, right, left, 10, 17.999, 18, 5, straightSweep(fast, right, left, 18), true, true, List.of()), "insufficient_advance");
        check(evaluate(ON, new Request(fast, right, left, 10, 18, 18, 5, straightSweep(fast, right, left, 18), true, true, List.of())).action() == Action.REQUEST_CHANGE,
            "Exact minimum gain rejected");
        reject(new Request(fast, right, left, 3, 15, 15, 4, straightSweep(fast, right, left, 15), true, true, List.of()), "prediction_horizon_mismatch");
        reject(new Request(fast, right, left, 3, 15, 15, 5, straightSweep(fast, right, left, 15), false, true, List.of()), "physical_evidence_missing");
        reject(new Request(fast, right, left, 3, 15, 15, 5, straightSweep(fast, right, left, 15), true, false, List.of()), "receiver_storage_rejected");
        reject(request(fast, right, lane(2), List.of()), "target_not_adjacent");
        for (double invalidCenter : new double[]{50, 3, -3.5}) {
            var invalidGeometry = new Lane("lane1", "forward", "east", 1, invalidCenter, 3.5, 0, 100,
                Set.of("car"), CLASSES, Set.of("straight"), Set.of("lane0"), "metric-adjacency", true);
            reject(request(fast, right, invalidGeometry, List.of()), "invalid_lane_geometry");
        }
        reject(request(fast, right, rules(left, "west", Set.of("car"), CLASSES, Set.of("straight"), Set.of(), "rules", true), List.of()),
            "different_link_or_direction");
        reject(request(fast, right, rules(left, "east", Set.of("car"), CLASSES, Set.of("right"), Set.of(), "mandatory-right-turn", true), List.of()),
            "mode_class_or_turn_forbidden");
        var busLane = rules(left, "east", Set.of("pt"), Set.of("bus"), Set.of("straight"), Set.of("lane0"), "exclusive-bus-lane", true);
        reject(request(fast, right, busLane, List.of()), "mode_class_or_turn_forbidden");
        check(evaluate(ON, request(vehicle("bus", 12, 12), right, busLane, List.of())).action() == Action.REQUEST_CHANGE,
            "Authorized bus rejected from its exclusive lane");
        reject(request(fast, rules(right, "east", Set.of("car"), CLASSES, Set.of("straight"), Set.of(), "solid-line", true), left, List.of()),
            "lane_boundary_forbidden");
        reject(request(fast, right, rules(left, "east", Set.of("car"), CLASSES, Set.of("straight"), Set.of(), "local-rule", false), List.of()),
            "local_rule_override");
        reject(request(fast, right, rules(left, "east", Set.of("car"), CLASSES, Set.of("straight"), Set.of(), "", true), List.of()),
            "physical_evidence_missing");

        // The obstacle can be laterally between source and target even if neither
        // endpoint overlaps it. Checking only target occupancy is insufficient.
        reject(request(fast, right, left, List.of(new Occupancy("crossing", 19, 24, 1.4, 2.1))), "swept_envelope_occupied");
        reject(request(fast, right, left, List.of(new Occupancy("leader", 36, 41, 2.3, 4.7))), "swept_envelope_occupied");
        reject(request(fast, right, left, List.of(new Occupancy("follower", 12, 17, 2.3, 4.7))), "swept_envelope_occupied");
        check(evaluate(ON, request(fast, right, left, List.of(new Occupancy("outside", 41, 46, 2.3, 4.7)))).action() == Action.REQUEST_CHANGE,
            "Separated body rejected");
        // The mean forecast stops before this obstacle; the conservative ego
        // travel bound reaches it. Safety must use the bound, never the forecast.
        reject(new Request(fast, right, left, 3, 15, 25, 5, straightSweep(fast, right, left, 25), true, true,
            List.of(new Occupancy("beyond-expected", 41, 46, 2.3, 4.7))), "swept_envelope_occupied");
        var nearerStop = new Lane("lane1", "forward", "east", 1, 3.5, 3.5, 0, 45,
            Set.of("car"), CLASSES, Set.of("straight"), Set.of("lane0"), "metric-stop-boundary", true);
        check(evaluate(ON, request(fast, right, nearerStop, List.of())).action() == Action.REQUEST_CHANGE,
            "Valid bounded trajectory rejected before stop boundary");
        reject(new Request(fast, right, nearerStop, 3, 15, 25, 5, straightSweep(fast, right, nearerStop, 25), true, true, List.of()), "insufficient_physical_length");
        for (double[] expected : new double[][]{{3, 15}, {15, 3}}) {
            try {
                new Request(fast, right, left, expected[0], expected[1], 14.999, 5, straightSweep(fast, right, left, 15), true, true, List.of());
                throw new AssertionError("Swept travel smaller than expected advance accepted");
            } catch (IllegalArgumentException required) {
                check(required.getMessage().contains("sweptAdvanceM"), "Unexpected bound validation failure");
            }
        }

        var truck = vehicle("truck", 18, 12);
        check(evaluate(ON, request(truck, right, left, List.of())).action() == Action.REQUEST_CHANGE, "Long truck on sufficient space rejected");
        var nextToTruck = new Occupancy("neighbor", 32, 36, 4.9, 5.2);
        check(evaluate(ON, request(truck, right, left, List.of(nextToTruck))).action() == Action.REQUEST_CHANGE,
            "Separated zero-yaw fixture rejected");
        // An explicitly provided yaw envelope extends beyond either endpoint's
        // axis-aligned width. The same neighbor must now block the maneuver.
        var truckYaw = new Occupancy("ego", 10, 44, -1.7, 5.2);
        reject(new Request(truck, right, left, 3, 15, 15, 5, truckYaw, true, true, List.of(nextToTruck)), "swept_envelope_occupied");
        var articulatedBus = vehicle("bus", 18, 12);
        reject(new Request(articulatedBus, right, left, 3, 15, 15, 5, truckYaw, true, true, List.of(nextToTruck)), "swept_envelope_occupied");
        for (var invalidSweep : List.of(new Occupancy("wrong-vehicle", 10, 44, -1.7, 5.2),
                new Occupancy("ego", 12, 44, -1.7, 5.2), new Occupancy("ego", 10, 43.99, -1.7, 5.2),
                new Occupancy("ego", 10, 44, -1.1, 5.2), new Occupancy("ego", 10, 44, -1.7, 4.6)))
            reject(new Request(truck, right, left, 3, 15, 15, 5, invalidSweep, true, true, List.of()), "invalid_ego_swept_envelope");
        reject(new Request(truck, right, left, 3, 15, 15, 5, new Occupancy("ego", 10, 44, -1.8, 5.2),
            true, true, List.of()), "swept_envelope_outside_lanes");
        reject(new Request(truck, right, nearerStop, 3, 15, 15, 5, new Occupancy("ego", 10, 46, -1.7, 5.2),
            true, true, List.of()), "insufficient_physical_length");
        var shortLane = new Lane("lane1", "forward", "east", 1, 3.5, 3.5, 0, 35,
            Set.of("car", "pt"), CLASSES, Set.of("straight"), Set.of("lane0"), "short-link", true);
        reject(request(truck, right, shortLane, List.of()), "insufficient_physical_length");
        reject(request(vehicle("bus", 12, 12), right, shortLane, List.of()), "insufficient_physical_length");
        reject(request(new Vehicle("wide", "car", "truck", "straight", 20, 10, 3.6, 12), right, left, List.of()), "vehicle_too_wide");

        // Disabled mode is a true bypass: it must not demand any new physical
        // inputs, produce a change request, mutate state or invoke native queues.
        check(evaluate(Settings.defaults(false), null).action() == Action.DISABLED, "Disabled policy requires new state");
        var original = faster;
        for (int i = 0; i < 100; i++) check(evaluate(Settings.defaults(false), faster).action() == Action.DISABLED, "Disabled changed result");
        check(original.equals(faster), "Decision mutated input");

        var workers = Executors.newFixedThreadPool(4);
        try {
            var futures = new ArrayList<java.util.concurrent.Future<?>>();
            for (int actor = 0; actor < 4; actor++) futures.add(workers.submit(() -> {
                for (int i = 0; i < 1000; i++) check(evaluate(ON, faster).equals(evaluate(ON, original)), "Shared policy state changed decision");
            }));
            for (var future : futures) future.get(10, TimeUnit.SECONDS);
        } finally {
            workers.shutdownNow(); check(workers.awaitTermination(10, TimeUnit.SECONDS), "Workers did not stop");
        }
        System.out.println("PASS isolated lane policy: speed preferences, gain threshold, legal/exclusive/mandatory lanes, " +
            "full swept occupancy, short storage, bus/truck, disabled bypass and four workers; no executed lane changes or QSim run");
    }
}
