package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.network.NetworkChangeEvent;
import org.matsim.core.network.NetworkUtils;

/** Synthetic incidents, not a calibrated crash-frequency or collision model. */
public final class StochasticCrashEvent implements MobsimInitializedListener,
        MobsimBeforeSimStepListener, MobsimBeforeCleanupListener {
    public static final double DEFAULT_PROBABILITY = 0.0005;
    private final Scenario scenario;
    private final double probability, capacityFactor, speedFactor;
    private final long seed;
    private final Set<Id<Link>> evaluated = new HashSet<>();
    private final PriorityQueue<Incident> pending = new PriorityQueue<>(
        Comparator.comparingDouble(Incident::end).thenComparing(i -> i.link().getId().toString()));
    private List<? extends Link> candidates;
    private Random random;
    private QSim qsim;
    private double nextScan;
    private int iteration;

    record Incident(Link link, double start, double end, double capacity, double speed) { }

    public StochasticCrashEvent(Scenario scenario, long seed) {
        this(scenario, seed, DEFAULT_PROBABILITY, 0.2, 0.3);
    }

    public StochasticCrashEvent(Scenario scenario, long seed, double probability,
                                double capacityFactor, double speedFactor) {
        if (!Double.isFinite(probability) || probability < 0 || probability > 1 ||
            !Double.isFinite(capacityFactor) || capacityFactor <= 0 || capacityFactor >= 1 ||
            !Double.isFinite(speedFactor) || speedFactor <= 0 || speedFactor >= 1) {
            throw new IllegalArgumentException("Probability must be in [0,1], reduction factors in (0,1)");
        }
        this.scenario = scenario;
        this.seed = seed;
        this.probability = probability;
        this.capacityFactor = capacityFactor;
        this.speedFactor = speedFactor;
    }

    @Override public void notifyMobsimInitialized(MobsimInitializedEvent event) {
        if (!(event.getQueueSimulation() instanceof QSim sim)) {
            throw new IllegalStateException("StochasticCrashEvent requires QSim");
        }
        if (!scenario.getConfig().network().isTimeVariantNetwork() ||
            !NetworkUtils.getNetworkChangeEvents(scenario.getNetwork()).isEmpty()) {
            throw new IllegalStateException("Requires time-variant network without other change events");
        }
        qsim = sim;
        random = new Random(seed + iteration++);
        evaluated.clear();
        pending.clear();
        nextScan = Double.NEGATIVE_INFINITY;
        candidates = scenario.getNetwork().getLinks().values().stream()
            .filter(l -> l.getAllowedModes().contains("car"))
            .sorted(Comparator.comparing(l -> l.getId().toString())).toList();
    }

    static NetworkChangeEvent change(Link link, double time, double capacity, double speed, double period) {
        var change = new NetworkChangeEvent(time);
        change.addLink(link);
        var absolute = NetworkChangeEvent.ChangeType.ABSOLUTE_IN_SI_UNITS;
        // Network XML capacity is per capperiod; the change-event API requires veh/s.
        change.setFlowCapacityChange(new NetworkChangeEvent.ChangeValue(absolute, capacity / period));
        change.setFreespeedChange(new NetworkChangeEvent.ChangeValue(absolute, speed));
        return change;
    }

    @Override public void notifyMobsimBeforeSimStep(MobsimBeforeSimStepEvent event) {
        double now = event.getSimulationTime();
        while (!pending.isEmpty() && pending.peek().end() <= now) {
            Incident incident = pending.remove();
            apply(incident, now, false, "duration_elapsed");
        }
        // Reserve the full maximum duration before QSim ends, never shorten a late incident.
        double latestStart = scenario.getConfig().qsim().getEndTime().seconds() - 2700;
        if (now < nextScan || now > latestStart) return;
        nextScan = now + 60;
        for (Link link : candidates) {
            if (evaluated.contains(link.getId())) continue;
            var simulationLink = qsim.getNetsimNetwork().getNetsimLink(link.getId());
            if (simulationLink == null || simulationLink.getAllNonParkedVehicles().isEmpty()) continue;
            evaluated.add(link.getId());
            if (random.nextDouble() >= probability) continue;
            int duration = 900 + random.nextInt(1801);
            Incident incident = new Incident(link, now, now + duration,
                link.getCapacity(now), link.getFreespeed(now));
            pending.add(incident);
            apply(incident, now, true, "random_selection");
        }
    }

    private void apply(Incident incident, double now, boolean start, String reason) {
        double capacity = incident.capacity() * (start ? capacityFactor : 1);
        double speed = incident.speed() * (start ? speedFactor : 1);
        qsim.addNetworkChangeEvent(change(incident.link(), now, capacity, speed,
            scenario.getNetwork().getCapacityPeriod()));
        qsim.getEventsManager().processEvent(new IncidentLog(now, start, incident, capacity, speed, reason));
    }

    @Override public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        // Abnormal early shutdown is explicitly labelled, not reported as a full-duration incident.
        while (!pending.isEmpty()) apply(pending.remove(), qsim.getSimTimer().getTimeOfDay(), false, "simulation_cleanup");
        NetworkUtils.setNetworkChangeEvents(scenario.getNetwork(), List.of());
        evaluated.clear();
    }

    private static final class IncidentLog extends Event {
        private final boolean start;
        private final Incident incident;
        private final double capacity, speed;
        private final String reason;
        IncidentLog(double time, boolean start, Incident incident, double capacity, double speed, String reason) {
            super(time);
            this.start = start; this.incident = incident;
            this.capacity = capacity; this.speed = speed; this.reason = reason;
        }
        @Override public String getEventType() { return start ? "zona1IncidentStart" : "zona1IncidentRecovered"; }
        @Override public Map<String, String> getAttributes() {
            var attributes = super.getAttributes();
            attributes.put("link", incident.link().getId().toString());
            attributes.put("capacityPerHour", Double.toString(capacity * 3600 / incident.link().getCapacityPeriod()));
            attributes.put("freespeedMps", Double.toString(speed));
            attributes.put("scheduledRecovery", Double.toString(incident.end()));
            attributes.put("durationSeconds", Double.toString(incident.end() - incident.start()));
            attributes.put("reason", reason);
            return attributes;
        }
    }
}
