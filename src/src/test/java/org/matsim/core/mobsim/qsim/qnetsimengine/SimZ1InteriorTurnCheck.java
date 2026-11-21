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

/** Native interior U-turn: a stopping prefix must retain its exit setback. */
public final class SimZ1InteriorTurnCheck {
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        try {
            var scenario = SimZ1TerminalTurnCheck.scenario(Path.of(args.length==0?"scenarios/zona1":args[0]));
            var ledger = new SimZ1CorridorOccupancy(scenario, Set.of(), org.matsim.core.events.EventsUtils.createEventsManager());
            var terminal = SimZ1TerminalTurnCheck.body(scenario,"terminal-prefix",2.1,
                    List.of("osm_406843605_33_forward","osm_381097546_0_forward"));
            check(ledger.canEnter(terminal,Id.createLinkId("osm_381097546_0_forward"),"osm_381097546_0_forward.original",0),
                    "Native final activity was given an unnecessary stopping setback");
            var config = scenario.getConfig();
            var out = Files.createTempDirectory(Path.of("runtime"), "interior-turn-check-");
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
            var paths = List.of(
                List.of("osm_381097546_0_forward","osm_381097546_0_backward","osm_381097538_0_forward","osm_381097538_1_forward","osm_381097538_2_forward","osm_381097538_3_forward"),
                List.of("osm_381097546_1_backward","osm_381097546_1_forward","osm_381097546_2_forward","osm_381097546_3_forward","osm_381097546_4_forward","osm_381097546_5_forward"));
            for (int i = 0; i < 6; i++) {
                int kind=i%3;
                var path=new ArrayList<>(paths.get(kind==1?1:0).stream().map(Id::createLinkId).toList());
                // From upstream the short return requires incompatible phases.
                // Its rejection is checked separately. This longer return has
                // a full receiver where it can wait between those phases.
                if(i>=3&&kind!=1){
                    path.addAll(1,List.of(Id.createLinkId("osm_381097546_1_forward"),Id.createLinkId("osm_381097546_1_backward")));
                    path.add(0,Id.createLinkId("osm_406843605_33_forward"));
                    path.add(0,Id.createLinkId("osm_406843605_32_forward"));
                }
                var type=VehicleUtils.createVehicleType(Id.create("body-"+i,VehicleType.class));
                type.setLength(kind==1?4.5:2.1).setWidth(kind==1?1.8:.8).setPcuEquivalents(kind==1?1:.25).setMaximumVelocity(13.8888889).setNetworkMode("car");
                scenario.getVehicles().addVehicleType(type);
                var vehicle = VehicleUtils.createVehicle(Id.createVehicleId("activity-"+i), type);
                scenario.getVehicles().addVehicle(vehicle);
                var person = factory.createPerson(Id.createPersonId("activity-"+i));
                VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicle.getId()));
                var plan = factory.createPlan();
                var home = factory.createActivityFromLinkId("home", path.get(0));
                home.setEndTime(i<3?(kind==2?2:1):(kind==2?101:100)); plan.addActivity(home);
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
            check(events.stream().filter(e -> e instanceof PersonArrivalEvent).count() == 6,
                    "Interior return cycle retained vehicles; evidence="+out);
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
            for(String actor:List.of("activity-0"))check(events.stream().anyMatch(e -> e.getEventType().equals("simz1OccupancyPassage") &&
                    "ACQUIRE".equals(e.getAttributes().get("action")) && actor.equals(e.getAttributes().get("vehicle")) &&
                    "osm_381097546_0_forward,osm_381097546_0_backward".equals(e.getAttributes().get("passageLinks")) &&
                    "osm_381097538_0_forward".equals(e.getAttributes().get("receiptLink"))),
                    "Short interior return was admitted without a full downstream receipt");
            for(String actor:List.of("activity-3","activity-5"))for(String link:List.of(
                    "osm_406843605_33_forward","osm_381097546_0_forward","osm_381097546_1_forward",
                    "osm_381097546_1_backward","osm_381097546_0_backward"))
                check(events.stream().anyMatch(e->e instanceof LinkEnterEvent enter &&
                        enter.getVehicleId().toString().equals(actor)&&enter.getLinkId().toString().equals(link)),
                        "Upstream full-receiver return did not execute: "+actor+" "+link);
            check(entries.indexOf("activity-0")<entries.indexOf("activity-2")&&entries.indexOf("activity-3")<entries.indexOf("activity-5"), "Same-origin FIFO changed: "+entries);
            System.out.println("PASS 6 native arrivals (activity and upstream entry), FIFO, no overlap/red/removal/leaked reservations; evidence="+out);
        } finally {
            org.apache.logging.log4j.LogManager.shutdown();
        }
    }
}
