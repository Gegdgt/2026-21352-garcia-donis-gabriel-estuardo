package gt.edu.uvg.sim.zona1;

/** Pure availability policy used by the weekday native driver; times are simulated seconds. */
public final class SimZ1TransitTiming {
    private SimZ1TransitTiming() { }
    public static double readyAt(double actualArrival, double terminal, double exterior) {
        for (double v : new double[]{actualArrival,terminal,exterior})
            if (!Double.isFinite(v) || v < 0) throw new IllegalArgumentException("invalid transit availability time");
        double result=actualArrival+terminal+exterior;
        if (!Double.isFinite(result)) throw new IllegalArgumentException("transit availability overflow");
        return result;
    }
    /** Infinity cancels this start; later civil-day duties must be checked separately. */
    public static double nextDeparture(double scheduled, double actualReady, double closing) {
        for (double v : new double[]{scheduled,actualReady,closing})
            if (!Double.isFinite(v) || v < 0) throw new IllegalArgumentException("invalid transit departure time");
        double result=Math.max(scheduled,actualReady);
        return result < closing ? result : Double.POSITIVE_INFINITY;
    }
}
