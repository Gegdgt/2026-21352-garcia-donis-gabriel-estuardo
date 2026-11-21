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

/** Native regression on frozen inputs coordinated with derive-activity-v2.
 * The v1 offsets from the diagnosed Run1000 leave these three departures stuck
 * in an empty network. No production admission rule or map is overridden here.
 */
public final class SimZ1ActivityOriginCheck {
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        try {
            check(args.length == 1, "Supply an isolated, coordinated inputs directory");
            var scenario = SimZ1TerminalTurnCheck.scenario(Path.of(args[0]));
            var config = scenario.getConfig();
            var out = Files.createTempDirectory(Path.of("runtime"), "activity-origin-check-");
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
            var type = VehicleUtils.createVehicleType(Id.create("Normal", VehicleType.class));
            type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(50./3.6).setNetworkMode("car");
            scenario.getVehicles().addVehicleType(type);
            var path = List.of("osm_39931896_3_forward", "osm_1274975826_4_forward",
                    "osm_1274975826_5_forward", "osm_1274975827_0_forward", "osm_1274975827_1_forward")
                    .stream().map(Id::createLinkId).toList();
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
