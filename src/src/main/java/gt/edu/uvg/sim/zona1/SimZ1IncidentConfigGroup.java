package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Fail-closed declaration only: there is no installed native incident adapter. */
public final class SimZ1IncidentConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "simz1IncidentConsequences";
    public static final int DURATION_SECONDS = 1800;
    private boolean enabled;

    public SimZ1IncidentConfigGroup() { super(GROUP_NAME); }

    @StringGetter("enabled") public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean value) { enabled = value; }
    @StringSetter("enabled") public void readEnabled(String value) {
        if (!"true".equals(value) && !"false".equals(value))
            throw new IllegalArgumentException("CONFIG_INVALID: simz1IncidentConsequences.enabled must be true or false");
        enabled = Boolean.parseBoolean(value);
    }

    @StringGetter("durationSeconds") public int getDurationSeconds() { return DURATION_SECONDS; }
    @StringSetter("durationSeconds") public void readDurationSeconds(String value) {
        if (!Integer.toString(DURATION_SECONDS).equals(value))
            throw new IllegalArgumentException("CONFIG_INVALID: simz1IncidentConsequences.durationSeconds must be 1800");
    }

    public void validateProduction() {
        if (enabled) throw new IllegalArgumentException(
            "CONFIG_INVALID: simz1IncidentConsequences.enabled=true is unavailable: " +
            "native independent-lane adapter, paired observer and verified registry are not installed; " +
            "fixture-only events cannot enable physical consequences");
    }
}
