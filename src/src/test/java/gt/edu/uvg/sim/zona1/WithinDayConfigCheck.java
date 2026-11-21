package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ConfigUtils;

/** Checks actual MATSim XML parsing and the custom routing switch without running QSim. */
public final class WithinDayConfigCheck {
    public static void main(String[] args) {
        var ids = java.util.stream.IntStream.range(0, 10000).boxed().toList();
        var cohort = CongestionAwareRerouting.selectCohort(ids, .5, 42);
        if (cohort.size()!=5000 || !cohort.equals(CongestionAwareRerouting.selectCohort(ids,.5,42)) ||
            cohort.equals(CongestionAwareRerouting.selectCohort(ids,.5,43)))
            throw new AssertionError("Cohort size/reproducibility/rotation");
        if (CongestionAwareRerouting.selectCohort(java.util.List.of(1,2,3),.5,42).size()!=1)
            throw new AssertionError("Odd population must round down");
        var config = ConfigUtils.loadConfig("scenarios/zona1/config-simz1.xml");
        if (!RunZona1Simulation.withinDayRoutingEnabled(config)) throw new AssertionError("Master disabled");
        var group = config.getModules().get("zona1WithinDayRouting");
        var typed=(Zona1RoutingConfigGroup)group;
        if (!DrivingProfiles.FASTEST_TIME.equals(typed.getRoutingPolicy()) ||
            !DrivingProfiles.FASTEST_TIME.equals(new Zona1RoutingConfigGroup().getRoutingPolicy()))
            throw new AssertionError("Fastest-time must be the normal routing policy");
        typed.setRoutingPolicy(DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL);
        if (!DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL.equals(typed.getValue("routingPolicy")))
            throw new AssertionError("Explicit experimental policy serialization");
        try {typed.setRoutingPolicy("typo");throw new AssertionError("Unknown policy accepted");}
        catch (IllegalArgumentException expected) { }
        typed.setRoutingPolicy(DrivingProfiles.FASTEST_TIME);
        if (typed.getMaxReroutesPerStep()!=100) throw new AssertionError("Wrong default reroute budget");
        typed.setMaxReroutesPerStep(7);
        if (!"7".equals(typed.getValue("maxReroutesPerStep"))) throw new AssertionError("Budget serialization");
        for (int invalid: new int[]{0,-1}) {
            try { typed.setMaxReroutesPerStep(invalid); throw new AssertionError("Invalid budget accepted"); }
            catch (IllegalArgumentException expected) { }
        }
        if (((Zona1RoutingConfigGroup)group).getAgentShare()!=.5) throw new AssertionError("Wrong share");
        try {
            ((Zona1RoutingConfigGroup)group).setAgentShare(Double.NaN);
            throw new AssertionError("Invalid share accepted");
        } catch (IllegalArgumentException expected) { }
        long pairedSeed=config.global().getRandomSeed();
        var enabledCohort=CongestionAwareRerouting.selectCohort(ids,typed.getAgentShare(),pairedSeed);
        group.addParam("enabled", "false");
        if (RunZona1Simulation.withinDayRoutingEnabled(config)) throw new AssertionError("Switch ignored");
        if (config.global().getRandomSeed()!=pairedSeed || !enabledCohort.equals(
            CongestionAwareRerouting.selectCohort(ids,typed.getAgentShare(),config.global().getRandomSeed())))
            throw new AssertionError("Off/on configuration changed seed or cohort");
        if (!DrivingProfiles.FASTEST_TIME.equals(typed.getRoutingPolicy()))
            throw new AssertionError("Disabling rerouting changed route-cost policy");
        try {
            ((Zona1RoutingConfigGroup)group).setEnabled("typo");
            RunZona1Simulation.withinDayRoutingEnabled(config);
            throw new AssertionError("Invalid switch accepted");
        } catch (IllegalArgumentException expected) { }
        if (!RunZona1Simulation.withinDayRoutingEnabled(ConfigUtils.createConfig())) {
            throw new AssertionError("Legacy default lost");
        }
        System.out.println("PASS: within-day XML switch, false, invalid value and legacy default");
        System.out.println("PASS: exact half cohort, seed reproducibility, iteration rotation, odd population, XML share");
        System.out.println("PASS: fastest-time default, explicit experimental policy, off/on same seed/cohort; no paired QSim execution");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
