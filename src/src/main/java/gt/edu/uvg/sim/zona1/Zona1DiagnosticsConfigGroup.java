package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Explicit experimental switches; no congestion thresholds are changed by diagnostics. */
public final class Zona1DiagnosticsConfigGroup extends ReflectiveConfigGroup {
    private String incidentsEnabled="true";
    private int progressIntervalSeconds=60, watchdogSeconds=5;
    public Zona1DiagnosticsConfigGroup() { super("zona1Diagnostics"); }
    @StringGetter("incidentsEnabled") public String getIncidentsEnabled() { return incidentsEnabled; }
    @StringSetter("incidentsEnabled") public void setIncidentsEnabled(String value) {
        if (!"true".equals(value) && !"false".equals(value)) throw new IllegalArgumentException("CONFIG_INVALID: incidentsEnabled must be true/false");
        incidentsEnabled=value;
    }
    @StringGetter("progressIntervalSeconds") public int getProgressIntervalSeconds() { return progressIntervalSeconds; }
    @StringSetter("progressIntervalSeconds") public void setProgressIntervalSeconds(int value) {
        if (value<1) throw new IllegalArgumentException("CONFIG_INVALID: progressIntervalSeconds must be positive");
        progressIntervalSeconds=value;
    }
    @StringGetter("watchdogSeconds") public int getWatchdogSeconds() { return watchdogSeconds; }
    @StringSetter("watchdogSeconds") public void setWatchdogSeconds(int value) {
        if (value<1) throw new IllegalArgumentException("CONFIG_INVALID: watchdogSeconds must be positive");
        watchdogSeconds=value;
    }
}
