package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;

/** User-invoked fixture harness: default only loads and validates; --simulate explicitly runs QSim. */
public final class SimZ1TransitFixture {
    private static void requireCounter(Map<String,String> counters,String key,String expected) {
        if(!expected.equals(counters.get(key)))
            throw new AssertionError("Synthetic fleet result "+key+"="+counters.get(key)+"; expected "+expected);
    }
    private static String requiredFile(Path directory, String name) throws Exception {
        var path=directory.resolve(name).toRealPath();
        if (!path.startsWith(directory) || !Files.isRegularFile(path) || Files.size(path)>1_000_000)
            throw new IllegalArgumentException("Expected bounded fixture file inside prepared directory: "+name);
        return path.toString();
    }
    public static void main(String[] args) throws Exception {
        if (args.length<1 || args.length>2 || (args.length==2 && !"--simulate".equals(args[1])))
            throw new IllegalArgumentException("Usage: SimZ1TransitFixture <prepared-dir> [--simulate]");
        boolean simulate=args.length==2;
        var directory=Path.of(args[0]).toRealPath();
        var config=ConfigUtils.createConfig();
        config.network().setInputFile(requiredFile(directory,"synthetic-network.xml"));
        config.transit().setUseTransit(true);
        config.transit().setTransitScheduleFile(requiredFile(directory,"transitSchedule.xml"));
        config.transit().setVehiclesFile(requiredFile(directory,"transitVehicles.xml"));
        config.qsim().setMainModes(Set.of("car")); // MATSim 15 native driver leg mode, not road demand membership.
        config.qsim().setRemoveStuckVehicles(false);
        config.qsim().setNumberOfThreads(1);
        config.qsim().setStartTime(0);config.qsim().setEndTime(600);
        config.global().setRandomSeed(42);
        config.controler().setLastIteration(0);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.failIfDirectoryExists);
        config.planCalcScore().addActivityParams(new ActivityParams("synthetic-origin").setScoringThisActivityAtAll(false));
        config.planCalcScore().addActivityParams(new ActivityParams("synthetic-destination").setScoringThisActivityAtAll(false));
        var scenario=ScenarioUtils.loadScenario(config);
        var attributes=scenario.getTransitSchedule().getAttributes();
        if (!"synthetic_fixture".equals(String.valueOf(attributes.getAttribute("simz1:purpose"))) ||
            !"3".equals(String.valueOf(attributes.getAttribute("simz1:monteCarloPersons"))) ||
            !"2".equals(String.valueOf(attributes.getAttribute("simz1:configuredFleetSize"))) ||
            !"4".equals(String.valueOf(attributes.getAttribute("simz1:scheduledExpeditions"))) ||
            scenario.getNetwork().getLinks().size()!=4 || !scenario.getPopulation().getPersons().isEmpty())
            throw new IllegalArgumentException("Harness accepts only the separate N=3/B=2/four-link synthetic fixture");
        var population=scenario.getPopulation();var factory=population.getFactory();
        for(int i=0;i<3;i++) {
            var person=factory.createPerson(Id.createPersonId("synthetic-road-"+i));
            var plan=factory.createPlan();
            var origin=factory.createActivityFromLinkId("synthetic-origin",Id.createLinkId("a_terminal"));origin.setEndTime(400+i*10);
            var destination=factory.createActivityFromLinkId("synthetic-destination",Id.createLinkId("b_terminal"));
            var leg=factory.createLeg("car");
            var route=RouteUtils.createLinkNetworkRouteImpl(origin.getLinkId(),destination.getLinkId());
            route.setLinkIds(origin.getLinkId(),List.of(Id.createLinkId("a_to_b")),destination.getLinkId());leg.setRoute(route);
            plan.addActivity(origin);plan.addLeg(leg);plan.addActivity(destination);person.addPlan(plan);person.setSelectedPlan(plan);population.addPerson(person);
        }
        DrivingProfiles.configure(scenario);
        var prepared=SimZ1TransitFleet.validate(scenario);
        var blocks=SimZ1TransitFleet.buildUmlaeufe(scenario,prepared);
        if(blocks.size()!=2 || prepared.scheduledExpeditions()!=4 || prepared.roadPersonsN()!=3)
            throw new IllegalArgumentException("Native XML fixture differs from declared fleet");
        System.out.println("Loaded synthetic fixture: N=3, B=2, expeditions=4, native blocks=2. No public service is enabled.");
        if (!simulate) {
            System.out.println("Validation only; no Controler/QSim constructed. Use --simulate explicitly for the small future run.");
            org.apache.logging.log4j.LogManager.shutdown();return;
        }
        var output=directory.resolve("simulation-"+UUID.randomUUID()).normalize();
        if(!output.startsWith(directory) || Files.exists(output)) throw new IllegalArgumentException("Output must be a new fixture child directory");
        config.controler().setOutputDirectory(output.toString());
        config.controler().setRunId("synthetic-fixed-fleet-"+UUID.randomUUID());
        var originalPersons=Set.copyOf(population.getPersons().keySet());
        var originalFleet=Set.copyOf(scenario.getTransitVehicles().getVehicles().keySet());
        var controler=new Controler(scenario);
        // Exercise the exact install path used by ejecutar_simz1.py, not a parallel setup.
        var monitor=RunZona1Simulation.installTransit(controler);
        if (monitor == null) throw new AssertionError("Production launcher did not install public transit");
        TripTableExporter.install(controler);
        controler.run();
        // MATSim 15 QSim.run finishes EventsManager processing before returning; the parallel
        // manager drains its iteration barrier. IterationEnds closes the compact summary.
        var finalCounters=monitor.snapshot();
        requireCounter(finalCounters,"roadDemandPersonsN","3");
        requireCounter(finalCounters,"configuredFleetB","2");
        requireCounter(finalCounters,"scheduledExpeditions","4");
        requireCounter(finalCounters,"observedExpeditionStarts","4");
        requireCounter(finalCounters,"observedInternalTransitDrivers","2");
        requireCounter(finalCounters,"roadPopulationSizeUnchanged","true");
        for(String key:List.of("activePublicVehiclesNetwork","activePublicVehiclesInDomain",
                "activePublicVehiclesLocationUnknown","duplicateTrafficEntries","unmatchedTrafficLeaves",
                "linkEventsWithoutTraffic","duplicateDepartureStarts","unregisteredTransitStarts",
                "demandDriverIdCollisions","publicVehicleAbortEvents")) requireCounter(finalCounters,key,"0");
        if(!originalPersons.equals(population.getPersons().keySet()) ||
            !originalFleet.equals(scenario.getTransitVehicles().getVehicles().keySet()))
            throw new AssertionError("Synthetic run changed the configured demand or fleet identities");
        var summaryPath=Path.of(controler.getControlerIO().getIterationPath(0)).resolve("0.simz1-trip-summary.json");
        if(!Files.isRegularFile(summaryPath) || Files.size(summaryPath)>100_000)
            throw new AssertionError("Missing or unexpectedly large completed compact summary: "+summaryPath);
        var mapper=new com.fasterxml.jackson.databind.ObjectMapper();
        var summary=mapper.readTree(Files.readString(summaryPath));
        var counts=summary.path("counts");
        if(counts.path("rows").asInt(-1)!=3 || counts.path("departures").asInt(-1)!=3 ||
            counts.path("completed").asInt(-1)!=3 || counts.path("aborted").asInt(0)!=0 ||
            counts.path("censored").asInt(0)!=0 || summary.path("demand_persons_N").asInt(-1)!=3 ||
            summary.path("configured_public_vehicles_B").asInt(-1)!=2 ||
            summary.path("observed_internal_transit_drivers").asInt(-1)!=2)
            throw new AssertionError("Compact summary must contain exactly three completed road trips, separate from the fixed fleet");
        if(!summary.path("anomalies").isObject()) throw new AssertionError("Compact summary lacks anomaly counts");
        for(var anomaly:summary.path("anomalies")) if(anomaly.asLong(-1)!=0)
            throw new AssertionError("Compact road-trip summary contains an anomaly");
        Files.writeString(output.resolve("synthetic-fleet-result.json"),mapper.writerWithDefaultPrettyPrinter().writeValueAsString(
            Map.of("status","passed_after_actual_simulation","transit_counters",finalCounters,
                   "completed_road_trips",3,"population_and_fleet_identities_unchanged",true))+System.lineSeparator(),
            StandardOpenOption.CREATE_NEW);
        System.out.println("PASS: actual synthetic run N=3, B=2, four departures, two reused drivers, zero active buses/aborts/anomalies, three completed road trips.");
        System.out.println("Synthetic fixture output: "+output);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
