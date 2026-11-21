package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.Config;

/** Validate supplied options before QSim; never repair them by deleting stuck agents. */
public final class SimZ1Configuration {
    private SimZ1Configuration() { }
    public static void validate(Config config) {
        org.matsim.core.config.ConfigUtils.addOrGetModule(config,SimZ1IncidentConfigGroup.class).validateProduction();
        org.matsim.core.config.ConfigUtils.addOrGetModule(config,SimZ1LanePolicyConfigGroup.class).validateProduction();
        org.matsim.core.config.ConfigUtils.addOrGetModule(config,Zona1PriorityConfigGroup.class);
        var admission = org.matsim.core.config.ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);
        admission.validateOriginPolicy(config.qsim());
        if (admission.getStoragePolicy().equals("strict-receiver-v1") && config.qsim().isRemoveStuckVehicles())
            throw new IllegalArgumentException("CONFIG_INVALID: strict-receiver-v1 is incompatible with removeStuckVehicles=true; blocked vehicles must remain waiting");
        boolean turns=config.travelTimeCalculator().isCalculateLinkToLinkTravelTimes();
        if (turns && config.qsim().isRemoveStuckVehicles())
            throw new IllegalArgumentException("CONFIG_INVALID: calculateLinkToLinkTravelTimes=true is incompatible with removeStuckVehicles=true (MATSim 15)");
        if (config.controler().isLinkToLinkRoutingEnabled() && !turns)
            throw new IllegalArgumentException("CONFIG_INVALID: enableLinkToLinkRouting=true requires calculateLinkToLinkTravelTimes=true");
        if (turns && config.travelTimeCalculator().getSeparateModes())
            throw new IllegalArgumentException("CONFIG_INVALID: calculateLinkToLinkTravelTimes=true requires separateModes=false (MATSim 15); do not rely on the signals module to change it");
        if (config.qsim().getNumberOfThreads()<1)
            throw new IllegalArgumentException("CONFIG_INVALID: qsim.numberOfThreads must be positive");
        double stuck=config.qsim().getStuckTime();
        if (!Double.isFinite(stuck) || stuck<0)
            throw new IllegalArgumentException("CONFIG_INVALID: qsim.stuckTime must be finite and nonnegative");
    }
}
