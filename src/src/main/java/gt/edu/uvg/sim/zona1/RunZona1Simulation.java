package gt.edu.uvg.sim.zona1;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.builder.Signals;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;

/** Args: [config.xml] [new-output-directory]. Default input remains the configured population. */
public final class RunZona1Simulation {
    private RunZona1Simulation() { }
    public static final int AMBER_SECONDS = 4;

    public static void configureSignals(Controler controler) {
        var signals = ConfigUtils.addOrGetModule(controler.getConfig(), SignalSystemsConfigGroup.class);
        signals.setUseSignalSystems(true);
        signals.setUseAmbertimes(true);
        SimZ1Configuration.validate(controler.getConfig());
        var data = (SignalsData) controler.getScenario().getScenarioElement(SignalsData.ELEMENT_NAME);
        if (data == null || data.getAmberTimesData() == null)
            throw new IllegalStateException("Enable amber times before loading SignalsData");
        data.getAmberTimesData().setDefaultAmber(AMBER_SECONDS);
        // Green starts at onset without an additional red-yellow transition.
        data.getAmberTimesData().setDefaultRedAmber(null);
        // MATSim 15: SignalsModule is package-private, with no configure method.
        // The public Configurator installs SignalsModule AND SignalsQSimModule.
        new Signals.Configurator(controler).addSignalControllerFactory(
            Zona1FixedTimeController.ID, Zona1FixedTimeController.Factory.class);
        UnsignalizedPriority.configure(controler);
    }

    /** Persist the legacy default; fail on typos instead of silently disabling routing. */
    public static boolean withinDayRoutingEnabled(Config config) {
        return Boolean.parseBoolean(ConfigUtils.addOrGetModule(config, Zona1RoutingConfigGroup.class).getEnabled());
    }

    /** Actual launcher loading path, testable without constructing a scenario or QSim.
     * Missing admission remains historical/native; future SimZ1 launch configs
     * must carry their explicit policy. Do not change other laboratories' defaults.
     */
    static Config loadConfiguration(String path) {
        return ConfigUtils.loadConfig(path, new SignalSystemsConfigGroup(), new Zona1RoutingConfigGroup(),
            new Zona1DiagnosticsConfigGroup(), new Zona1PriorityConfigGroup(),
            new SimZ1AdmissionConfigGroup(), new SimZ1IncidentConfigGroup(), new SimZ1LanePolicyConfigGroup());
    }

    public static void install(Controler controler, StochasticCrashEvent listener) {
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addMobsimListenerBinding().toInstance(listener);
            }
        });
    }

    /** Shared by the real CLI and the bounded transit integration fixture. */
    public static SimZ1TransitDiagnostics installTransit(Controler controler) {
        var fleet = SimZ1TransitFleet.validate(controler.getScenario());
        if (fleet == null) return null;
        SimZ1TransitFleet.install(controler, fleet);
        var diagnostics = SimZ1TransitDiagnostics.install(controler, fleet.domainLinks(), fleet.domainScope());
        System.out.println("SIMZ1_TRANSIT_INSTALLED N=" + fleet.roadPersonsN()
            + " B=" + fleet.configuredFleetB() + " departures=" + fleet.scheduledExpeditions()
            + " engine=" + SimZ1TransitFleet.ExactTransitEngine.class.getName());
        return diagnostics;
    }

    public static void main(String[] args) {
        SimZ1ProcessIdentity.record();
        // The executor records this JVM independently of the Maven launcher.
        System.out.println("SIMZ1_PROCESS_STARTED pid="+ProcessHandle.current().pid());
        System.out.flush();
        Throwable primary = null;
        try {
            run(args);
        } catch (RuntimeException | Error failure) {
            primary = failure;
            // Keep the real causes even if Guice/Log4j cannot format a nested error.
            SimZ1FailureReport.print(failure, System.err);
            throw failure;
        } finally {
            // The dedicated process owns these helpers. Do not leave Maven to
            // interrupt them, and never replace the original simulation failure.
            try {
                org.matsim.utils.MemoryObserver.stop();
                org.apache.logging.log4j.LogManager.shutdown();
            } catch (RuntimeException | Error closingFailure) {
                SimZ1FailureReport.print(closingFailure, System.err);
                if (primary != null) primary.addSuppressed(closingFailure);
                else throw closingFailure;
            }
        }
    }

    private static void run(String[] args) {
        Zona1Logging.configure();
        if (args.length > 2) throw new IllegalArgumentException("Usage: RunZona1Simulation [config.xml] [new-output-directory]");
        String environmentConfig = System.getenv("SIMZ1_CONFIG");
        String configPath = args.length > 0 ? args[0] :
            environmentConfig != null && !environmentConfig.isBlank() ? environmentConfig :
            "scenarios/zona1/config-simz1.xml";
        var config = loadConfiguration(configPath);
        withinDayRoutingEnabled(config); // materialize and validate the typed switch
        SimZ1Configuration.validate(config);
        boolean incidents=Boolean.parseBoolean(ConfigUtils.addOrGetModule(config,Zona1DiagnosticsConfigGroup.class).getIncidentsEnabled());
        config.network().setTimeVariantNetwork(true); // Must be set BEFORE network loading.
        if (incidents && config.network().getChangeEventsInputFile() != null) {
            throw new IllegalArgumentException("External network change events cannot be combined with this incident model");
        }
        if (!config.qsim().getEndTime().isDefined()) throw new IllegalArgumentException("QSim endTime required");
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        if (args.length > 1) config.controler().setOutputDirectory(args[1]);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        DrivingProfiles.configure(scenario);
        SimZ1.validatePhysicalNetwork(scenario);
        boolean signalsEnabled = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class).isUseSignalSystems();
        if (signalsEnabled) {
            ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class).setUseAmbertimes(true);
        }
        if (signalsEnabled) scenario.addScenarioElement(SignalsData.ELEMENT_NAME,
            new SignalsDataLoader(config).loadSignalsData());
        var controler = new Controler(scenario);
        installTransit(controler);
        SimZ1DayObservation.install(controler);
        TripTableExporter.install(controler);
        SimZ1Freight.install(controler);
        ExperiencedTimeRouting.configure(controler);
        if (signalsEnabled) configureSignals(controler);
        else UnsignalizedPriority.configure(controler);
        if (incidents) install(controler, new StochasticCrashEvent(scenario, config.global().getRandomSeed()));
        SimZ1Diagnostics.install(controler);
        CongestionAwareRerouting.install(controler);
        controler.run();
    }
}
