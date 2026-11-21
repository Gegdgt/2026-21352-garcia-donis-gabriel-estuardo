package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ReflectiveConfigGroup;

/** The decision component exists; a native microscopic execution adapter does not. */
public final class SimZ1LanePolicyConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "simz1LanePolicy";
    private boolean enabled;
    private double minimumAdvanceM = 8, minimumGapM = 2, slowSpeedMps = 8.33, lookaheadSeconds = 5;

    public SimZ1LanePolicyConfigGroup() { super(GROUP_NAME); }
    @StringGetter("enabled") public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean value) { enabled = value; }
    @StringSetter("enabled") public void readEnabled(String value) {
        if (!"true".equals(value) && !"false".equals(value))
            throw new IllegalArgumentException("CONFIG_INVALID: simz1LanePolicy.enabled must be true or false");
        enabled = Boolean.parseBoolean(value);
    }
    @StringGetter("minimumAdvanceM") public double getMinimumAdvanceM() { return minimumAdvanceM; }
    @StringSetter("minimumAdvanceM") public void setMinimumAdvanceM(double value) { minimumAdvanceM = positive(value, "minimumAdvanceM"); }
    @StringGetter("minimumGapM") public double getMinimumGapM() { return minimumGapM; }
    @StringSetter("minimumGapM") public void setMinimumGapM(double value) {
        positive(value, "minimumGapM");
        if (value < SimZ1LanePolicy.MINIMUM_GAP_M)
            throw new IllegalArgumentException("CONFIG_INVALID: simz1LanePolicy.minimumGapM must be at least 0.10 metres");
        minimumGapM = value;
    }
    @StringGetter("slowSpeedMps") public double getSlowSpeedMps() { return slowSpeedMps; }
    @StringSetter("slowSpeedMps") public void setSlowSpeedMps(double value) { slowSpeedMps = positive(value, "slowSpeedMps"); }
    @StringGetter("lookaheadSeconds") public double getLookaheadSeconds() { return lookaheadSeconds; }
    @StringSetter("lookaheadSeconds") public void setLookaheadSeconds(double value) { lookaheadSeconds = positive(value, "lookaheadSeconds"); }

    public SimZ1LanePolicy.Settings settings() {
        return new SimZ1LanePolicy.Settings(enabled, minimumAdvanceM, minimumGapM, slowSpeedMps, lookaheadSeconds);
    }
    public void validateProduction() {
        settings();
        if (enabled) throw new IllegalArgumentException(
            "CONFIG_INVALID: LANE_POLICY_UNAVAILABLE simz1LanePolicy.enabled=true: native microscopic lane-state, " +
            "vehicle-aware storage, atomic swept-envelope reservation/transfer, network lane-rule import and " +
            "committed lane-change events are not installed; the isolated decision fixture cannot move QSim vehicles");
    }
    private static double positive(double value, String parameter) {
        if (!Double.isFinite(value) || value <= 0)
            throw new IllegalArgumentException("CONFIG_INVALID: simz1LanePolicy." + parameter + " must be finite and positive");
        return value;
    }
}
