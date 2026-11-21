package gt.edu.uvg.sim.zona1;

/** Dependency-free checks; no scenario, population, QSim or browser is constructed. */
public final class SimZ1TransitTimingCheck {
    private static int checks;
    private static void equal(double a,double b) {
        checks++; if (Double.compare(a,b)!=0) throw new AssertionError(a+" != "+b);
    }
    private static void rejects(Runnable r) {
        try { r.run(); } catch(IllegalArgumentException e) { checks++;return; }
        throw new AssertionError("accepted invalid time");
    }
    public static void main(String[] args) {
        equal(SimZ1TransitTiming.readyAt(400,25,1800),2225);
        equal(SimZ1TransitTiming.nextDeparture(2300,2225,72000),2300);
        equal(SimZ1TransitTiming.nextDeparture(2100,2225,72000),2225);
        equal(SimZ1TransitTiming.nextDeparture(71999,71999,72000),71999);
        equal(SimZ1TransitTiming.nextDeparture(72000,71999,72000),Double.POSITIVE_INFINITY);
        equal(SimZ1TransitTiming.nextDeparture(71999,72000,72000),Double.POSITIVE_INFINITY);
        // A very late arrival remains recorded; it does not create another bus or depart immediately.
        equal(SimZ1TransitTiming.nextDeparture(72000,SimZ1TransitTiming.readyAt(79250,0,1800),79200),Double.POSITIVE_INFINITY);
        rejects(()->SimZ1TransitTiming.readyAt(100,0,-1));
        rejects(()->SimZ1TransitTiming.readyAt(Double.NaN,0,1800));
        rejects(()->SimZ1TransitTiming.nextDeparture(100,Double.POSITIVE_INFINITY,200));
        rejects(()->SimZ1TransitTiming.readyAt(Double.MAX_VALUE,Double.MAX_VALUE,0));
        System.out.println("PASS: "+checks+" weekday availability assertions; no QSim executed");
    }
}
