package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.vehicles.Vehicle;

/** Read-only counters for the fixed public fleet. Never adds drivers to Monte Carlo N.
 * Network activity means native traffic events, not scheduled service or parked stock.
 * Domain activity requires an explicit, scoped set of directed links; no bbox fallback.
 */
public final class SimZ1TransitDiagnostics implements BasicEventHandler, MobsimInitializedListener,
        MobsimAfterSimStepListener, MobsimBeforeCleanupListener {
    private static final org.apache.logging.log4j.Logger LOG=
        org.apache.logging.log4j.LogManager.getLogger(SimZ1TransitDiagnostics.class);
    private final Scenario scenario;
    private final Set<Id<Person>> demandPersonIds;
    private final Set<Id<Vehicle>> fleet;
    private final Set<Id<Link>> domainLinks;
    private final String domainScope;
    private final int scheduledExpeditions;
    private final Map<Id<Person>,Id<Vehicle>> drivers=new HashMap<>();
    private final Set<Id<Vehicle>> activeNetwork=new HashSet<>();
    private final Map<Id<Vehicle>,Id<Link>> locations=new HashMap<>();
    private final Set<DepartureKey> startedDepartures=new HashSet<>();
    private long duplicateTrafficEntries, unmatchedTrafficLeaves, linkEventsWithoutTraffic,
        duplicateDepartureStarts, unregisteredTransitStarts, demandDriverIdCollisions, publicVehicleAbortEvents;
    private int iteration, interval=60;
    private QSim qsim;
    private double nextReport=Double.NEGATIVE_INFINITY;

    private record DepartureKey(String line,String route,String departure) { }

    public SimZ1TransitDiagnostics(Scenario scenario,Set<Id<Link>> domainLinks,String domainScope) {
        this.scenario=Objects.requireNonNull(scenario);
        demandPersonIds=Set.copyOf(scenario.getPopulation().getPersons().keySet());
        fleet=Set.copyOf(scenario.getTransitVehicles().getVehicles().keySet());
        this.domainLinks=domainLinks==null?null:Set.copyOf(domainLinks);
        this.domainScope=domainLinks==null?"unknown":Objects.requireNonNull(domainScope);
        if (domainLinks!=null && !Set.of("approved_domain","synthetic_fixture","computational_network").contains(domainScope))
            throw new IllegalArgumentException("Domain counters need approved_domain or synthetic_fixture scope");
        if (domainLinks!=null && !scenario.getNetwork().getLinks().keySet().containsAll(domainLinks))
            throw new IllegalArgumentException("Domain counters reference missing directed network links");
        scheduledExpeditions=scenario.getTransitSchedule().getTransitLines().values().stream()
            .flatMap(line->line.getRoutes().values().stream()).mapToInt(route->route.getDepartures().size()).sum();
    }

    public static SimZ1TransitDiagnostics install(Controler controler,Set<Id<Link>> domainLinks,String domainScope) {
        var monitor=new SimZ1TransitDiagnostics(controler.getScenario(),domainLinks,domainScope);
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addMobsimListenerBinding().toInstance(monitor);
                addEventHandlerBinding().toInstance(monitor);
            }
        });
        return monitor;
    }

    @Override public synchronized void reset(int iteration) {
        this.iteration=iteration;
        drivers.clear(); activeNetwork.clear(); locations.clear(); startedDepartures.clear();
        duplicateTrafficEntries=unmatchedTrafficLeaves=linkEventsWithoutTraffic=duplicateDepartureStarts=0;
        unregisteredTransitStarts=demandDriverIdCollisions=publicVehicleAbortEvents=0;
        nextReport=Double.NEGATIVE_INFINITY;
    }

    @Override public synchronized void handleEvent(Event event) {
        if (event instanceof TransitDriverStartsEvent e) {
            if (!fleet.contains(e.getVehicleId())) { unregisteredTransitStarts++; return; }
            if (demandPersonIds.contains(e.getDriverId())) demandDriverIdCollisions++;
            else drivers.put(e.getDriverId(),e.getVehicleId());
            var key=new DepartureKey(e.getTransitLineId().toString(),e.getTransitRouteId().toString(),e.getDepartureId().toString());
            if (!startedDepartures.add(key)) duplicateDepartureStarts++;
        } else if (event instanceof VehicleEntersTrafficEvent e && fleet.contains(e.getVehicleId())) {
            if (!activeNetwork.add(e.getVehicleId())) duplicateTrafficEntries++;
            locations.put(e.getVehicleId(),e.getLinkId());
        } else if (event instanceof VehicleLeavesTrafficEvent e && fleet.contains(e.getVehicleId())) {
            if (!activeNetwork.remove(e.getVehicleId())) unmatchedTrafficLeaves++;
            locations.remove(e.getVehicleId());
        } else if (event instanceof VehicleAbortsEvent e && fleet.contains(e.getVehicleId())) {
            publicVehicleAbortEvents++;
            activeNetwork.remove(e.getVehicleId()); locations.remove(e.getVehicleId());
        } else if (event instanceof LinkEnterEvent e && fleet.contains(e.getVehicleId())) {
            if (activeNetwork.contains(e.getVehicleId())) locations.put(e.getVehicleId(),e.getLinkId());
            else linkEventsWithoutTraffic++;
        } else if (event instanceof LinkLeaveEvent e && fleet.contains(e.getVehicleId())) {
            if (!activeNetwork.contains(e.getVehicleId())) linkEventsWithoutTraffic++;
            // Between native leave/enter events the next link is not yet evidence.
            locations.remove(e.getVehicleId());
        }
    }

    /** Native TransitDriverStarts events supply these identities; no pt_ prefix heuristic. */
    public synchronized Map<String,String> observedDriverVehicleIds() {
        var result=new TreeMap<String,String>();
        drivers.forEach((driver,vehicle)->result.put(driver.toString(),vehicle.toString()));
        return Collections.unmodifiableMap(result);
    }

    public synchronized Map<String,String> snapshot() {
        var result=new TreeMap<String,String>();
        long located=activeNetwork.stream().filter(id->locations.get(id)!=null).count();
        long unknownLocations=activeNetwork.size()-located;
        long inside=domainLinks==null?0:activeNetwork.stream()
            .filter(id->locations.get(id)!=null && domainLinks.contains(locations.get(id))).count();
        result.put("iteration",Integer.toString(iteration));
        result.put("roadDemandPersonsN",Integer.toString(SimZ1Freight.privateCount(scenario)));
        result.put("configuredFleetB",Integer.toString(fleet.size()));
        result.put("scheduledExpeditions",Integer.toString(scheduledExpeditions));
        result.put("observedInternalTransitDrivers",Integer.toString(drivers.size()));
        result.put("observedExpeditionStarts",Integer.toString(startedDepartures.size()));
        result.put("activePublicVehiclesNetwork",Integer.toString(activeNetwork.size()));
        result.put("activePublicVehiclesLocationUnknown",Long.toString(unknownLocations));
        result.put("domainCounterScope",domainScope);
        result.put("activePublicVehiclesOnKnownDomainLinks",domainLinks==null?"unknown":Long.toString(inside));
        result.put("activePublicVehiclesInDomain",domainLinks==null||unknownLocations>0?"unknown":Long.toString(inside));
        result.put("domainCounterDefinition","native_traffic_active_on_explicit_directed_links_not_parked_fleet");
        result.put("eventObservationBasis","registered_fleet_events_processed_at_snapshot");
        result.put("observerGuaranteesEventQueueDrain","false");
        result.put("configuredAfterStepEventSynchronization",String.valueOf(
            scenario.getConfig().parallelEventHandling().getSynchronizeOnSimSteps()));
        result.put("duplicateTrafficEntries",Long.toString(duplicateTrafficEntries));
        result.put("unmatchedTrafficLeaves",Long.toString(unmatchedTrafficLeaves));
        result.put("linkEventsWithoutTraffic",Long.toString(linkEventsWithoutTraffic));
        result.put("duplicateDepartureStarts",Long.toString(duplicateDepartureStarts));
        result.put("unregisteredTransitStarts",Long.toString(unregisteredTransitStarts));
        result.put("demandDriverIdCollisions",Long.toString(demandDriverIdCollisions));
        result.put("publicVehicleAbortEvents",Long.toString(publicVehicleAbortEvents));
        result.put("roadPopulationSizeUnchanged",Boolean.toString(scenario.getPopulation().getPersons().size()==demandPersonIds.size()));
        return Collections.unmodifiableMap(result);
    }

    @Override public void notifyMobsimInitialized(MobsimInitializedEvent event) {
        qsim=(QSim)event.getQueueSimulation();
        interval=ConfigUtils.addOrGetModule(scenario.getConfig(),Zona1DiagnosticsConfigGroup.class).getProgressIntervalSeconds();
        // Do not clear here: native transit preparation can already have emitted driver starts.
    }

    @Override public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent event) {
        double now=event.getSimulationTime();
        if (now<nextReport) return;
        report(now,"after_step"); nextReport=now+interval;
    }

    private void report(double now,String phase) {
        var data=new TreeMap<>(snapshot()); data.put("observationPhase",phase);
        data.put("observationCompleteness",observationCompleteness(phase));
        qsim.getEventsManager().processEvent(new Event(now) {
            @Override public String getEventType() { return "simz1TransitCounters"; }
            @Override public Map<String,String> getAttributes() {
                var attributes=super.getAttributes(); attributes.putAll(data); return attributes;
            }
        });
        LOG.info("SIMZ1_TRANSIT_COUNTERS simulatedTime={} {}",now,data);
    }

    String observationCompleteness(String phase) {
        // MATSim 15 QSim calls EventsManager.afterSimStep before these listeners.
        // ParallelEventsManager flushes there only when synchronization is enabled.
        // Cleanup after a failed step and other listener-generated events need not
        // have crossed that barrier. This observer never drains or changes queues.
        if ("before_cleanup".equals(phase) || Boolean.FALSE.equals(
                scenario.getConfig().parallelEventHandling().getSynchronizeOnSimSteps()))
            return "processed_events_so_far_delivery_may_lag_native_clock";
        return "processed_events_so_far_not_a_final_drained_total";
    }

    @Override public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        // Use the native current clock even after a failed, partially observed step.
        if (qsim!=null) report(qsim.getSimTimer().getTimeOfDay(),"before_cleanup");
    }
}
