package org.matsim.core.mobsim.qsim.qnetsimengine;

/** The native empty-queue budget, also used by static temporal route checks. */
public final class SimZ1PassageTiming {
    private SimZ1PassageTiming() { }
    public static double budget(double length, double speed, double step, double debtSteps, boolean activityEntry) {
        if (!(speed > 0) || !Double.isFinite(speed) || !(step > 0) || !Double.isFinite(step) ||
            !Double.isFinite(length) || length < 0 || !Double.isFinite(debtSteps) || debtSteps < 0)
            return Double.POSITIVE_INFINITY;
        return step * ((activityEntry ? 0 : Math.floor(length / speed / step)) + Math.ceil(debtSteps) + 2);
    }
}
