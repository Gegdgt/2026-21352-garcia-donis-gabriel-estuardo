package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup;
import org.matsim.core.events.EventsUtils;

/** Actual scoped QNode branches with queue doubles; never runs Controller/QSim. */
public final class SimZ1AdmissionCheck {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static SimZ1StorageBranchCheck.Fixture fixture(boolean remove) {
        return new SimZ1StorageBranchCheck.Fixture(remove, true, true, EventsUtils.createEventsManager(), true);
    }
    public static void main(String[] args) throws Exception {
        try {
            var defaults = new SimZ1AdmissionConfigGroup();
            check(defaults.getStoragePolicy().equals(SimZ1AdmissionConfigGroup.NATIVE), "Historical absent policy changed");
            try { defaults.setStoragePolicy("guess"); throw new AssertionError("Unknown policy accepted"); }
            catch (IllegalArgumentException expected) { }

            for (boolean remove : new boolean[]{false, true}) {
                var blocked = fixture(remove);
                for (double time : new double[]{5, 10, 11, 60, 3600}) {
                    check(!blocked.attempt(time), "Rejected receiver crossed at " + time);
                    check(blocked.source.pops == 0 && blocked.receiver.additions == 0 && blocked.source.offered,
                        "Blocked head disappeared or moved upstream");
                }
                check(blocked.aborted == 0 && blocked.arranged == 0 && blocked.advanced == 0,
                    "Strict blockage changed the driver or removed an agent");
                check(blocked.decisions("storage_forced_move").isEmpty() && blocked.decisions("storage_stuck_removal").isEmpty(),
                    "Strict timeout reached native intervention");
                check(blocked.count("simz1Admission") == 0 && blocked.count("entered link") == 0,
                    "WAIT was reported as a successful admission");
                var evidence = blocked.decisions("storage_wait");
                check(evidence.size() == 5, "Missing rejected attempts");
                for (int i = 0; i < evidence.size(); i++) {
                    var values = evidence.get(i).getAttributes();
                    check(values.get("admissionPolicy").equals(SimZ1AdmissionConfigGroup.STRICT) &&
                        values.get("admissionPolicyVersion").equals("1") && values.get("receiverAcceptedAtDecision").equals("false"),
                        "Missing strict receiver evidence");
                    check(values.get("storageTimeoutExceeded").equals(Boolean.toString(i >= 2)), "Incorrect strict > threshold");
                }
                blocked.receiver.load = 0;
                check(blocked.attempt(3601), "Released receiver did not allow a legal transition");
                check(blocked.source.pops == 1 && blocked.receiver.additions == 1 && blocked.advanced == 1,
                    "Release did not transfer exactly once");
                check(blocked.count("simz1Admission") == 1 && blocked.count("entered link") == 1 && blocked.count("left link") == 1,
                    "Success receipt is not paired with one actual transition");
                int receipt = -1, entry = -1;
                for (int i = 0; i < blocked.events.size(); i++) {
                    var event = blocked.events.get(i);
                    if (event.getEventType().equals("entered link")) entry = i;
                    if (event.getEventType().equals("simz1Admission")) {
                        receipt = i;
                        check(event.getAttributes().get("receiverAcceptedAtDecision").equals("true"), "Receipt missing actual acceptance");
                    }
                }
                check(receipt > entry, "Admission receipt preceded the transition");
            }

            var red = fixture(false);
            red.receiver.load = 0; red.source.green = false;
            check(!red.attempt(100) && red.receiver.admissionQueries == 0 && red.source.pops == 0,
                "Red reached receiver admission despite long head age");
            red.source.green = true; red.receiver.load = 1;
            check(!red.attempt(101), "Green bypassed a full receiver");
            red.receiver.load = 0;
            check(red.attempt(102), "Green plus accepting receiver failed");

            var multilane = fixture(false); multilane.receiver.load = 0;
            var blockedLane = new SimZ1StorageBranchCheck.QueueState("in.1");
            blockedLane.vehicle = multilane.vehicle; blockedLane.green = false;
            check(!multilane.attempt(100, blockedLane.lane) && multilane.receiver.admissionQueries == 0,
                "Another green lane overrode this lane's red permission");
            check(multilane.attempt(100) && blockedLane.pops == 0 && multilane.source.pops == 1,
                "Lane-specific signal permission failed on the same link and step");

            // Preserve the installed API's threshold semantics. Requiring the
            // whole next PCU to fit would permanently block short original lanes.
            var fractional = fixture(false);
            fractional.receiver.capacity = 0.5555555555555556; fractional.receiver.load = 0;
            check(fractional.attempt(11), "Changed native fractional-capacity admission");
            check(fractional.receiver.load == 1 && fractional.decisions("storage_forced_move").isEmpty(),
                "Native accepted insertion was mislabeled FORCE");

            var failure = fixture(false); failure.receiver.failAdmission = true;
            try { failure.attempt(11); throw new AssertionError("Real receiver error swallowed"); }
            catch (java.lang.reflect.InvocationTargetException expected) {
                check(expected.getCause() instanceof IllegalStateException, "Unexpected failure cause");
            }
            check(failure.source.pops == 0 && failure.receiver.additions == 0 && failure.count("simz1Admission") == 0,
                "Failed check mutated queues or produced a receipt");
            var clock = fixture(false);
            for (double invalid : new double[]{Double.NEGATIVE_INFINITY, Double.NaN, Double.POSITIVE_INFINITY}) {
                try { clock.attempt(invalid); throw new AssertionError("Invalid native time accepted"); }
                catch (java.lang.reflect.InvocationTargetException expected) {
                    check(expected.getCause() instanceof IllegalArgumentException, "Unexpected clock failure");
                }
            }
            System.out.println("PASS strict admission: red/green, receiver rejection, prolonged WAIT, no forced removal, release, fractional capacity and committed receipts; no QSim run");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
