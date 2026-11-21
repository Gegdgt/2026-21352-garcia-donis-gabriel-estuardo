package gt.edu.uvg.sim.zona1;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;

/** Runs the separate OSM scenario; leaves historical laboratory generators intact. */
public final class SimZ1 {
    private SimZ1() { }

    private static double positive(double value, String field, Object link) {
        if (!Double.isFinite(value) || value <= 0) {
            throw new IllegalArgumentException("Invalid " + field + " on link " + link);
        }
        return value;
    }

    static void validatePhysicalNetwork(Scenario scenario) {
        if (Math.abs(scenario.getNetwork().getCapacityPeriod() - 3600.0) > 1e-6) {
            throw new IllegalArgumentException("SimZ1 requires hourly capacities (capperiod=01:00:00)");
        }
        scenario.getNetwork().getLinks().values().forEach(link -> {
            double lanes = positive(link.getNumberOfLanes(), "lanes", link.getId());
            positive(link.getLength(), "length", link.getId());
            positive(link.getFreespeed(), "freespeed", link.getId());
            positive(link.getCapacity(), "capacity", link.getId());
            if (lanes != Math.rint(lanes)) {
                throw new IllegalArgumentException("Fractional physical lanes on " + link.getId());
            }
            Object ideal = link.getAttributes().getAttribute("physical:idealCapacityPerLane");
            if (ideal != null) {
                double base = positive(Double.parseDouble(ideal.toString()), "ideal capacity", link.getId());
                double factor = positive(Double.parseDouble(String.valueOf(
                    link.getAttributes().getAttribute("physical:capacityFactor"))), "capacity factor", link.getId());
                double kmh = positive(Double.parseDouble(String.valueOf(
                    link.getAttributes().getAttribute("physical:modeledMaxSpeedKmh"))), "speed metadata", link.getId());
                if (base != 2000.0 || factor > 1 ||
                    Math.abs(link.getCapacity() - base * lanes * factor) > 1e-6 ||
                    Math.abs(link.getFreespeed() * 3.6 - kmh) > 1e-6) {
                    throw new IllegalArgumentException("Inconsistent physical attributes on " + link.getId());
                }
            }
        });
    }

    static Config loadConfiguration(String path) {
        // Only this independent scenario opts future executions into strict
        // receiver admission. Historical XML/results and other labs are intact.
        var admission = new SimZ1AdmissionConfigGroup();
        admission.setStoragePolicy("strict-receiver-v1");
        return ConfigUtils.loadConfig(path, new SignalSystemsConfigGroup(), new Zona1RoutingConfigGroup(),new Zona1DiagnosticsConfigGroup(),new Zona1PriorityConfigGroup(), admission, new SimZ1IncidentConfigGroup(), new SimZ1LanePolicyConfigGroup());
    }

    public static void main(String[] args) {
        Zona1Logging.configure();
        if (args.length > 1) {
            throw new IllegalArgumentException("Usage: SimZ1 [path/to/config-simz1.xml]");
        }
        String path = args.length == 0 ? "scenarios/zona1/config-simz1.xml" : args[0];
        Config config = loadConfiguration(path);
        SimZ1Configuration.validate(config);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        DrivingProfiles.configure(scenario);
        if (scenario.getNetwork().getLinks().isEmpty() || scenario.getPopulation().getPersons().isEmpty()) {
            throw new IllegalStateException("SimZ1 requires a network and a population");
        }
        validatePhysicalNetwork(scenario);
        scenario.getActivityFacilities().getFacilities().values().forEach(f -> {
            if (f.getLinkId() == null || !scenario.getNetwork().getLinks().containsKey(f.getLinkId())) {
                throw new IllegalStateException("Invalid facility link: " + f.getId());
            }
        });
        boolean signals = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class).isUseSignalSystems();
        if (signals) {
            ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class).setUseAmbertimes(true);
            scenario.addScenarioElement(SignalsData.ELEMENT_NAME, new SignalsDataLoader(config).loadSignalsData());
        }
        var controler = new Controler(scenario);
        RunZona1Simulation.installTransit(controler);
        SimZ1DayObservation.install(controler);
        TripTableExporter.install(controler);
        SimZ1Freight.install(controler);
        ExperiencedTimeRouting.configure(controler);
        if (signals) RunZona1Simulation.configureSignals(controler);
        else UnsignalizedPriority.configure(controler);
        SimZ1Diagnostics.install(controler);
        CongestionAwareRerouting.install(controler);
        controler.run();
    }
}
