package gt.edu.uvg.sim.zona1;

import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;

/** Preflight rejects invalid combinations without silently repairing the input. */
public final class SimZ1ConfigurationCheck {
    private static void expectInvalid(Config config, String detail) {
        try { SimZ1Configuration.validate(config); }
        catch (IllegalArgumentException error) {
            if (!error.getMessage().startsWith("CONFIG_INVALID:") || !error.getMessage().contains(detail))
                throw new AssertionError("Missing causal configuration diagnostic",error);
            return;
        }
        throw new AssertionError("Invalid combination accepted: "+detail);
    }
    public static void main(String[] args) throws Exception {
        for (boolean signals:new boolean[]{false,true}) for (boolean lanes:new boolean[]{false,true}) {
            var config=ConfigUtils.createConfig(new SignalSystemsConfigGroup());
            ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class).setUseSignalSystems(signals);
            config.qsim().setUseLanes(lanes);
            config.qsim().setStuckTime(17);
            config.controler().setLinkToLinkRoutingEnabled(true);
            config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
            config.travelTimeCalculator().setSeparateModes(false);
            config.qsim().setRemoveStuckVehicles(false);
            SimZ1Configuration.validate(config);
            if (config.qsim().isUseLanes()!=lanes || config.qsim().getStuckTime()!=17
                    || config.qsim().isRemoveStuckVehicles()) throw new AssertionError("Preflight mutated configuration");
            config.qsim().setRemoveStuckVehicles(true);
            expectInvalid(config,"removeStuckVehicles");
            if (!config.qsim().isRemoveStuckVehicles()) throw new AssertionError("Silently repaired removal setting");
            config.qsim().setRemoveStuckVehicles(false);
            config.travelTimeCalculator().setSeparateModes(true);
            expectInvalid(config,"separateModes");
            config.travelTimeCalculator().setSeparateModes(false);
            config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(false);
            expectInvalid(config,"enableLinkToLinkRouting");
            config.controler().setLinkToLinkRoutingEnabled(false);
            SimZ1Configuration.validate(config);
        }
        var strict = ConfigUtils.createConfig(new SimZ1AdmissionConfigGroup());
        var policy = ConfigUtils.addOrGetModule(strict, SimZ1AdmissionConfigGroup.class);
        if (!policy.getStoragePolicy().equals("matsim15-native")) throw new AssertionError("Other scenarios changed default");
        policy.setStoragePolicy("strict-receiver-v1");
        strict.qsim().setRemoveStuckVehicles(true);
        expectInvalid(strict,"strict-receiver-v1");
        if (!strict.qsim().isRemoveStuckVehicles()) throw new AssertionError("Removal silently changed");
        strict.qsim().setRemoveStuckVehicles(false);
        SimZ1Configuration.validate(strict);
        var file = java.nio.file.Files.createTempFile("simz1-admission-config-", ".xml");
        var dtd = java.util.Objects.requireNonNull(ConfigUtils.class.getResource("/dtd/config_v2.dtd")).toExternalForm();
        var header = "<?xml version=\"1.0\"?><!DOCTYPE config SYSTEM \"" + dtd + "\">";
        try {
            java.nio.file.Files.writeString(file,header + "<config/>");
            var loaded = SimZ1.loadConfiguration(file.toString());
            if (!ConfigUtils.addOrGetModule(loaded,SimZ1AdmissionConfigGroup.class).getStoragePolicy().equals("strict-receiver-v1"))
                throw new AssertionError("Future SimZ1 entry point did not opt into strict admission");
            java.nio.file.Files.writeString(file,header + "<config><module name=\"simz1Admission\"><param name=\"storagePolicy\" value=\"matsim15-native\"/></module></config>");
            loaded = SimZ1.loadConfiguration(file.toString());
            if (!ConfigUtils.addOrGetModule(loaded,SimZ1AdmissionConfigGroup.class).getStoragePolicy().equals("matsim15-native"))
                throw new AssertionError("Explicit legacy audit policy was rewritten");
            // This is the Python launcher's actual entry point. Loading only:
            // never constructs Controler, Scenario or a QSim scheduler.
            java.nio.file.Files.writeString(file,header + "<config/>");
            loaded = RunZona1Simulation.loadConfiguration(file.toString());
            if (!ConfigUtils.addOrGetModule(loaded,SimZ1AdmissionConfigGroup.class).getStoragePolicy().equals("matsim15-native"))
                throw new AssertionError("Shared entry point rewrote absent historical policy");
            for (boolean signals : new boolean[]{false,true}) {
                String requested = "<config><module name=\"qsim\">"
                    + "<param name=\"numberOfThreads\" value=\"4\"/><param name=\"useLanes\" value=\"true\"/>"
                    + "<param name=\"removeStuckVehicles\" value=\"false\"/><param name=\"stuckTime\" value=\"10\"/></module>"
                    + "<module name=\"signalsystems\"><param name=\"useSignalsystems\" value=\"" + signals + "\"/></module>"
                    + "<module name=\"simz1Admission\"><param name=\"storagePolicy\" value=\"strict-receiver-v1\"/></module>"
                    + "<module name=\"simz1LanePolicy\"><param name=\"enabled\" value=\"false\"/></module></config>";
                java.nio.file.Files.writeString(file,header + requested);
                loaded = RunZona1Simulation.loadConfiguration(file.toString());
                SimZ1Configuration.validate(loaded);
                if (!(loaded.getModules().get("simz1Admission") instanceof SimZ1AdmissionConfigGroup)
                        || !ConfigUtils.addOrGetModule(loaded,SimZ1AdmissionConfigGroup.class).getStoragePolicy().equals("strict-receiver-v1")
                        || loaded.qsim().getNumberOfThreads()!=4 || !loaded.qsim().isUseLanes()
                        || loaded.qsim().isRemoveStuckVehicles() || loaded.qsim().getStuckTime()!=10)
                    throw new AssertionError("Launcher lost explicit admission/lanes/four-thread configuration");
                java.nio.file.Files.writeString(file,header + requested.replace(
                    "name=\"enabled\" value=\"false\"", "name=\"enabled\" value=\"true\""));
                loaded = RunZona1Simulation.loadConfiguration(file.toString());
                expectInvalid(loaded,"LANE_POLICY_UNAVAILABLE");
            }
        } finally { java.nio.file.Files.delete(file); }
        if (!SimZ1Diagnostics.classifyProgress(null,15,10,0,100).equals("no_simulated_progress_cpu_active")
            || !SimZ1Diagnostics.classifyProgress(null,15,0,0,100).equals("no_simulated_progress_low_cpu")
            || !SimZ1Diagnostics.classifyProgress(null,0,10,0,100).equals("traffic_wait_observed")
            || !SimZ1Diagnostics.classifyProgress(new long[]{123},0,0,0,0).equals("thread_deadlock_detected"))
            throw new AssertionError("Traffic/CPU waits confused with an observed JVM lock cycle");
        System.out.println("PASS: actual launcher loads explicit strict admission with four threads; legacy defaults preserved; physical lane activation rejected; wait is not deadlock; no QSim run");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
