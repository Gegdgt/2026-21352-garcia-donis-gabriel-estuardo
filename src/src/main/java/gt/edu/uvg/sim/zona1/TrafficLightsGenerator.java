package gt.edu.uvg.sim.zona1;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.LinkedHashMap;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsScenarioWriter;
import org.matsim.contrib.signals.data.signalgroups.v20.SignalGroupData;
import org.matsim.contrib.signals.model.Signal;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.contrib.signals.model.SignalPlan;
import org.matsim.contrib.signals.model.SignalSystem;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;

/** Native fixed-time link or lane signals from OSM markers. No surveyed timing claimed. */
public final class TrafficLightsGenerator {
    private TrafficLightsGenerator() { }

    public static SignalsData build(Scenario scenario) {
        return build(scenario, null);
    }

    /** SHA-256 UTF-8 SimZ1-offset-v1:seed:systemId, unsigned modulo cycle. */
    public static int stableOffset(String systemId, long seed, int cycle) {
        if (cycle <= 0) throw new IllegalArgumentException("Positive signal cycle required");
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(
                ("SimZ1-offset-v1:" + seed + ":" + systemId).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return new java.math.BigInteger(1, digest).mod(java.math.BigInteger.valueOf(cycle)).intValueExact();
        } catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    /** Null retains the legacy zero policy; a seed explicitly requests synthetic offsets. */
    public static SignalsData build(Scenario scenario, Long offsetSeed) {
        boolean useLanes=scenario.getConfig().qsim().isUseLanes();
        var config = ConfigUtils.addOrGetModule(scenario.getConfig(), SignalSystemsConfigGroup.class);
        config.setUseSignalSystems(true);
        config.setUseAmbertimes(true);
        var data = SignalUtils.createSignalsData(config);
        data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);
        var systems = data.getSignalSystemsData();
        var groups = data.getSignalGroupsData();
        var control = data.getSignalControlData();
        for (var node : scenario.getNetwork().getNodes().values().stream()
                .sorted(Comparator.comparing(n -> n.getId().toString())).toList()) {
            if (!"traffic_signals".equals(node.getAttributes().getAttribute("osm:highway"))) continue;
            var incoming = node.getInLinks().values().stream().filter(l -> l.getAllowedModes().contains("car"))
                .sorted(Comparator.comparing(l -> l.getId().toString())).toList();
            if (incoming.isEmpty()) continue;
            var systemId = Id.create(node.getId().toString(), SignalSystem.class);
            var system = systems.getFactory().createSignalSystemData(systemId);
            systems.addSignalSystemData(system);
            var byAxis = new LinkedHashMap<String, SignalGroupData>();
            for (var link : incoming) {
                double dx = node.getCoord().getX() - link.getFromNode().getCoord().getX();
                double dy = node.getCoord().getY() - link.getFromNode().getCoord().getY();
                String axis = Math.abs(dy) >= Math.abs(dx) ? "avenida" : "calle";
                var group = byAxis.computeIfAbsent(axis, key -> {
                    var created = groups.getFactory().createSignalGroupData(systemId, Id.create(key, SignalGroup.class));
                    groups.addSignalGroupData(created);
                    return created;
                });
                var signal = systems.getFactory().createSignalData(Id.create(link.getId().toString(), Signal.class));
                signal.setLinkId(link.getId()); // Native link signal also works without detailed lanes.
                var assignment = useLanes?scenario.getLanes().getLanesToLinkAssignments().get(link.getId()):null;
                int controlledLanes = 0;
                if (assignment!=null) for (var lane : assignment.getLanes().values()) {
                    if (lane.getToLinkIds() == null || lane.getToLinkIds().isEmpty()) continue;
                    for (var targetId : lane.getToLinkIds()) {
                        var target = link.getToNode().getOutLinks().get(targetId);
                        if (target == null || target.getFromNode() != link.getToNode())
                            throw new IllegalStateException("Disconnected signal lane " + lane.getId());
                    }
                    signal.addLaneId(lane.getId());
                    controlledLanes++;
                }
                if (assignment!=null && controlledLanes == 0)
                    throw new IllegalStateException("No terminal lanes for signal " + signal.getId());
                system.addSignalData(signal);
                group.addSignalId(signal.getId());
            }
            var controller = control.getFactory().createSignalSystemControllerData(systemId);
            controller.setControllerIdentifier(Zona1FixedTimeController.ID);
            control.addSignalSystemControllerData(controller);
            var plan = control.getFactory().createSignalPlanData(Id.create("daily", SignalPlan.class));
            plan.setStartTime(0.0); plan.setEndTime(0.0); // MATSim: valid all day.
            plan.setCycleTime(80);
            plan.setOffset(offsetSeed == null ? 0 : stableOffset(systemId.toString(), offsetSeed, 80));
            for (var entry : byAxis.entrySet()) {
                var settings = control.getFactory().createSignalGroupSettingsData(entry.getValue().getId());
                boolean avenue = entry.getKey().equals("avenida");
                settings.setOnset(avenue ? 0 : 49);
                // XML dropping marks RED; controller requests native amber 4 s earlier.
                settings.setDropping(avenue ? 47 : 78);
                plan.addSignalGroupSettings(settings);
            }
            controller.addSignalPlanData(plan);
        }
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME, data);
        return data;
    }

    public static void write(Scenario scenario, Path directory) throws java.io.IOException {
        Files.createDirectories(directory);
        var writer = new SignalsScenarioWriter();
        writer.setSignalSystemsOutputFilename(directory.resolve("signalSystems.xml").toString());
        writer.setSignalGroupsOutputFilename(directory.resolve("signalGroups.xml").toString());
        writer.setSignalControlOutputFilename(directory.resolve("signalControl.xml").toString());
        writer.writeSignalsData(scenario);
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 3) throw new IllegalArgumentException("TrafficLightsGenerator [network.xml] [output-directory] [offset-seed]");
        Path network = Path.of(args.length > 0 ? args[0] : "scenarios/zona1/network.xml");
        Path output = Path.of(args.length > 1 ? args[1] : "scenarios/zona1");
        var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimNetworkReader(scenario.getNetwork()).readFile(network.toString());
        Files.createDirectories(output);
        LanesGenerator.build(scenario);
        new org.matsim.lanes.LanesWriter(scenario.getLanes()).write(output.resolve("lanes.xml").toString());
        var data = build(scenario, args.length > 2 ? Long.valueOf(args[2]) : null);
        if (data.getSignalSystemsData().getSignalSystemData().isEmpty())
            throw new IllegalArgumentException("No car-accessible traffic_signals nodes in network");
        write(scenario, output);
        System.out.println("Signal systems exported: " + data.getSignalSystemsData().getSignalSystemData().size());
    }
}
