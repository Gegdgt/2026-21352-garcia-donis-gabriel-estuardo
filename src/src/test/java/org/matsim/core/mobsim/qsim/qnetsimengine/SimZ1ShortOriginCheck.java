package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.vehicles.*;

/** Native empty-network regression: ceil per queue demanded 31s of a 25s
 * green. Native floor plus unchanged scheduling/debt bound requires 22s. */
public final class SimZ1ShortOriginCheck {
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        try {
            // Portable regression with a 23s green: ceil needs 24s even at
            // onset, while native floor plus all safety margins needs 17s.
            if(args.length==0){SimZ1CorridorOccupancyCheck.activityBufferPassageFixture(true);return;}
            check(args.length <= 1, "Optional isolated inputs directory");
            var scenario = SimZ1TerminalTurnCheck.scenario(Path.of(args.length==0?"scenarios/zona1":args[0]));
            var config = scenario.getConfig();
            var out = Files.createTempDirectory(Path.of("runtime"), "short-origin-check-");
            config.controler().setOutputDirectory(out.resolve("run").toString());
            config.controler().setLastIteration(0);
            config.controler().setLinkToLinkRoutingEnabled(true);
            config.global().setNumberOfThreads(1);
            config.qsim().setNumberOfThreads(1);
            config.qsim().setStartTime(0); config.qsim().setEndTime(600);
            config.qsim().setUsingFastCapacityUpdate(false);
            config.qsim().setRemoveStuckVehicles(false);
            config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
            config.travelTimeCalculator().setSeparateModes(false);
            config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
            var admission = ConfigUtils.addOrGetModule(config, SimZ1AdmissionConfigGroup.class);
            admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);
            admission.setWholeVehicleReservation(true);
            ConfigUtils.addOrGetModule(config, Zona1PriorityConfigGroup.class).setClassification("osm-hierarchy");
            for (String name : List.of("home", "work")) {
                var activity = new ActivityParams(name);
                activity.setTypicalDuration(3600); activity.setScoringThisActivityAtAll(false);
                config.planCalcScore().addActivityParams(activity);
            }
            var strategy = new StrategySettings();
            strategy.setStrategyName("KeepLastSelected"); strategy.setWeight(1);
            config.strategy().addStrategySettings(strategy);
            var factory = scenario.getPopulation().getFactory();
            var type = VehicleUtils.createVehicleType(Id.create("Tortuga", VehicleType.class));
            type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(25./3.6).setNetworkMode("car");
            scenario.getVehicles().addVehicleType(type);
            var path = List.of("osm_1272882106_0_forward","osm_1272882106_1_forward","osm_1272882108_1_forward","osm_48273209_13_forward","osm_48273209_14_forward","osm_48273209_15_forward","osm_48273209_16_forward","osm_48273209_17_forward").stream().map(Id::createLinkId).toList();
            for (int i = 0; i < 3; i++) {
                var vehicle = VehicleUtils.createVehicle(Id.createVehicleId("activity-"+i), type);
                scenario.getVehicles().addVehicle(vehicle);
                var person = factory.createPerson(Id.createPersonId("activity-"+i));
                VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicle.getId()));
                var plan = factory.createPlan();
                var home = factory.createActivityFromLinkId("home", path.get(0));
                home.setEndTime(1+i); plan.addActivity(home);
                var leg = factory.createLeg("car");
                var route = RouteUtils.createNetworkRoute(path, scenario.getNetwork());
                route.setVehicleId(vehicle.getId()); leg.setRoute(route); plan.addLeg(leg);
                plan.addActivity(factory.createActivityFromLinkId("work", path.get(path.size()-1)));
                person.addPlan(plan); scenario.getPopulation().addPerson(person);
            }
            var events = new ArrayList<Event>();
            var controler = new Controler(scenario); RunZona1Simulation.configureSignals(controler);
            controler.addOverridingModule(new AbstractModule() {
                public void install() { addEventHandlerBinding().toInstance((BasicEventHandler) events::add); }
            });
            controler.run();
            check(events.stream().filter(e -> e instanceof PersonArrivalEvent).count() == 3,
                    "Empty network activity passage never admitted all departures; evidence="+out);
            check(events.stream().noneMatch(e -> e instanceof PersonStuckEvent), "Forced removal");
            SimZ1CorridorOccupancyCheck.verifyTransactions(events);
            var passages = new HashSet<String>();
            var entries = new ArrayList<String>();
            for (var event : events) {
                var a = event.getAttributes();
                if (event instanceof VehicleEntersTrafficEvent entry) entries.add(entry.getVehicleId().toString());
                if (event.getEventType().equals("simz1OccupancyPassage")) {
                    if ("ACQUIRE".equals(a.get("action"))) check(passages.add(a.get("vehicle")), "Double acquire");
                    else check(passages.remove(a.get("vehicle")), "Release without acquire");
                }
                if (event.getEventType().equals("simz1OccupancyProgress") && a.containsKey("leaderVehicle"))
                    check(Double.parseDouble(a.get("modeledFrontLowerBoundMeters")) <=
                            Double.parseDouble(a.get("leaderFrontLowerBoundMeters"))-
                            Double.parseDouble(a.get("leaderFootprintMeters"))+1e-8, "Body overlap");
                if (event.getEventType().equals("simz1NativeDecision") && "GO".equals(a.get("decision")))
                    check(!"false".equals(a.get("nativeHasGreen")), "Red crossing");
            }
            check(passages.isEmpty(), "Leaked passage locks");
            check(entries.equals(List.of("activity-0", "activity-1", "activity-2")), "Activity FIFO changed: "+entries);
            System.out.println("PASS 3 native arrivals, FIFO, no overlap/red/removal/leaked reservations; evidence="+out);
        } finally {
            org.apache.logging.log4j.LogManager.shutdown();
        }
    }
}
