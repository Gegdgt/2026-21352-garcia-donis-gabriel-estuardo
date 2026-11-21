package gt.edu.uvg.sim.zona1;

/** The dormant lane contract must not permit a smaller gap than presentation.
 * These settings checks do not claim a microscopic adapter has been installed. */
public final class SimZ1PhysicalGap20261027Check {
    private static void reject(Runnable work) {
        try { work.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Subminimum physical gap accepted");
    }
    public static void main(String[] args) {
        for(double gap:new double[]{0,-.1,.09,Math.nextDown(.10),Double.NaN,Double.POSITIVE_INFINITY}) {
            reject(()->new SimZ1LanePolicy.Settings(true,8,gap,8.33,5));
            reject(()->new SimZ1LanePolicyConfigGroup().setMinimumGapM(gap));
        }
        var config=new SimZ1LanePolicyConfigGroup();
        config.setMinimumGapM(.10);
        if(config.settings().minimumGapM()!=.10)throw new AssertionError("Exact 0.10 m rejected or modified");
        reject(()->config.setMinimumGapM(.09));
        if(config.getMinimumGapM()!=.10)throw new AssertionError("Rejected setting mutated configuration");
        config.validateProduction();
        config.setEnabled(true);
        reject(config::validateProduction);
        System.out.println("PASS: minimum 0.10 m, exact boundary, invalid configuration atomicity and no false microscopic activation");
    }
}
