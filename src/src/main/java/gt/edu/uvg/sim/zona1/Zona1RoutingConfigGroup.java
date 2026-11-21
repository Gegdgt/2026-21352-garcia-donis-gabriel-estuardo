package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Typed config module so MATSim can materialize it in the controller injector. */
public final class Zona1RoutingConfigGroup extends ReflectiveConfigGroup {
    private String enabled = "true";
    private double agentShare = 0.5;
    private int maxReroutesPerStep = 100;
    private String routingPolicy = DrivingProfiles.FASTEST_TIME;
    @StringGetter("routingPolicy") public String getRoutingPolicy() { return routingPolicy; }
    @StringSetter("routingPolicy") public void setRoutingPolicy(String value) {
        routingPolicy = DrivingProfiles.validatePolicy(value);
    }
    @StringGetter("maxReroutesPerStep") public int getMaxReroutesPerStep() { return maxReroutesPerStep; }
    @StringSetter("maxReroutesPerStep") public void setMaxReroutesPerStep(int value) {
        if (value < 1) throw new IllegalArgumentException("maxReroutesPerStep must be positive");
        maxReroutesPerStep = value;
    }
    @StringGetter("agentShare") public double getAgentShare() { return agentShare; }
    @StringSetter("agentShare") public void setAgentShare(double value) {
        if (!Double.isFinite(value) || value < 0 || value > 1)
            throw new IllegalArgumentException("agentShare must be in [0,1]");
        agentShare = value;
    }
    public Zona1RoutingConfigGroup() { super("zona1WithinDayRouting"); }
    @StringGetter("enabled") public String getEnabled() { return enabled; }
    @StringSetter("enabled") public void setEnabled(String value) {
        if (!"true".equals(value) && !"false".equals(value))
            throw new IllegalArgumentException("zona1WithinDayRouting.enabled must be true or false");
        enabled = value;
    }
}
