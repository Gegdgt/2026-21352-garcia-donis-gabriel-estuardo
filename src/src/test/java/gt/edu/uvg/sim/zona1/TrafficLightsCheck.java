package gt.edu.uvg.sim.zona1;

import java.nio.file.Files;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.LinkLeaveEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.contrib.signals.events.SignalGroupStateChangedEvent;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;

/** Actual QSim regression, XML round trip, two iterations and a three-lane controlled link. */
public final class TrafficLightsCheck {
    public static void main(String[] args) throws Exception {
        double startTime = args.length == 0 ? 0 : Double.parseDouble(args[0]);
        int offset = args.length < 2 ? 0 : Integer.parseInt(args[1]);
        if (offset < 0 || offset >= 80) throw new IllegalArgumentException("offset outside cycle");
        var output = Files.createTempDirectory(java.nio.file.Path.of("target"), "native-signals-");
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
        config.controler().setOutputDirectory(output.resolve("run").toString());
        config.controler().setLastIteration(1);
        config.qsim().setStartTime(startTime); config.qsim().setEndTime(startTime+180);
        config.qsim().setSimEndtimeInterpretation(org.matsim.core.config.groups.QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setNumberOfThreads(1);
        config.qsim().setUsingFastCapacityUpdate(false);
        config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        config.travelTimeCalculator().setSeparateModes(false);
        for (String type : List.of("home", "work")) {
            var activity = new ActivityParams(type);
            activity.setTypicalDuration(3600); activity.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(activity);
        }
        var strategy = new StrategySettings(); strategy.setStrategyName("KeepLastSelected"); strategy.setWeight(1);
        config.strategy().addStrategySettings(strategy);
        var scenario = ScenarioUtils.createScenario(config);
        var net = scenario.getNetwork();
        double[][] xy={{-20,0},{-10,0},{0,0},{10,0},{0,-20},{0,-10},{0,10}};
        for (int i=0;i<xy.length;i++) net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        net.getNodes().get(Id.createNodeId(2)).getAttributes().putAttribute("osm:highway","traffic_signals");
        int[][] edges={{0,1},{1,2},{2,3},{4,5},{5,2},{2,6}};
        for (int i=0;i<edges.length;i++) {
            var link=net.getFactory().createLink(Id.createLinkId(i),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
            link.setLength(10); link.setFreespeed(10); link.setNumberOfLanes(3); link.setCapacity(6000);
            link.setAllowedModes(Set.of("car")); net.addLink(link);
        }
        var f=scenario.getPopulation().getFactory();
        for (int i=0;i<4;i++) {
            var person=f.createPerson(Id.createPersonId("p"+i)); var plan=f.createPlan();
            person.getAttributes().putAttribute("drivingProfile",java.util.List.of("Tortuga","Normal","Liebre").get(i%3));
            int start=i<3?0:3, end=i<3?2:5;
            var home=f.createActivityFromLinkId("home",Id.createLinkId(start)); home.setEndTime(startTime+(i<3?1:45));
            plan.addActivity(home); plan.addLeg(f.createLeg("car"));
            plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(end)));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
        LanesGenerator.build(scenario);
        DrivingProfiles.configure(scenario);
        if (TrafficLightsGenerator.stableOffset("2",20261015L,80) != 8)
            throw new AssertionError("Cross-language SHA-256 offset contract changed");
        var generatedSignals=TrafficLightsGenerator.build(scenario,20261015L);
        for (var system : generatedSignals.getSignalControlData().getSignalSystemControllerDataBySystemId().values())
            for (var plan : system.getSignalPlanData().values()) {
                if (plan.getOffset()!=8) throw new AssertionError("Generator did not persist hash offset");
                plan.setOffset(offset); // Explicit boundary fixture, before XML round trip.
            }
        for (var system:generatedSignals.getSignalSystemsData().getSignalSystemData().values()) {
            for (var signal:system.getSignalData().values()) {
                var assignment=scenario.getLanes().getLanesToLinkAssignments().get(signal.getLinkId());
                var terminals=new java.util.HashSet<org.matsim.api.core.v01.Id<org.matsim.lanes.Lane>>();
                for (var lane:assignment.getLanes().values())
                    if (lane.getToLinkIds()!=null && !lane.getToLinkIds().isEmpty()) terminals.add(lane.getId());
                if (terminals.isEmpty() || !terminals.equals(signal.getLaneIds()))
                    throw new AssertionError("Signal must control every terminal lane");
            }
        }
        TrafficLightsGenerator.write(scenario,output);
        byte[] persistedPlan = Files.readAllBytes(output.resolve("signalControl.xml"));
        var signals=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);
        signals.setSignalSystemFile(output.resolve("signalSystems.xml").toAbsolutePath().toString());
        signals.setSignalGroupsFile(output.resolve("signalGroups.xml").toAbsolutePath().toString());
        signals.setSignalControlFile(output.resolve("signalControl.xml").toAbsolutePath().toString());
        ((org.matsim.core.scenario.MutableScenario)scenario).removeScenarioElement(SignalsData.ELEMENT_NAME);
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME,new SignalsDataLoader(config).loadSignalsData());
        var exits=Collections.synchronizedList(new ArrayList<LinkLeaveEvent>());
        var arrivals=new java.util.concurrent.atomic.AtomicInteger();
        var changes=new java.util.concurrent.atomic.AtomicInteger();
        var redChanges=new java.util.concurrent.atomic.AtomicInteger();
        var greenChanges=new java.util.concurrent.atomic.AtomicInteger();
        var yellowChanges=new java.util.concurrent.atomic.AtomicInteger();
        var yellowStarted=new java.util.HashMap<String,Double>();
        var amberDurations=new java.util.ArrayList<Double>();
        var states = new java.util.HashMap<String,SignalGroupState>();
        var signatures = new java.util.HashSet<String>();
        var iterationEvents = new java.util.ArrayList<java.util.List<String>>();
        var currentEvents = new java.util.ArrayList<String>();
        BasicEventHandler handler=event->{
            if (event instanceof LinkLeaveEvent leave && Set.of("1","4").contains(leave.getLinkId().toString())) {
                exits.add(leave);
                String axis = leave.getLinkId().toString().equals("1") ? "calle" : "avenida";
                var state = states.get("2:"+axis);
                // MATSim 15 permits native YELLOW clearance as well as GREEN.
                if (state != SignalGroupState.GREEN && state != SignalGroupState.YELLOW)
                    throw new AssertionError("Exit without native permission: "+leave.getAttributes()+" state="+state);
            }
            if (event instanceof PersonArrivalEvent) arrivals.incrementAndGet();
            if (event instanceof SignalGroupStateChangedEvent change) {
                changes.incrementAndGet();
                if (change.getNewState()==SignalGroupState.RED) redChanges.incrementAndGet();
                if (change.getNewState()==SignalGroupState.GREEN) greenChanges.incrementAndGet();
                String group=change.getSignalSystemId()+":"+change.getSignalGroupId();
                String signature = group+":"+change.getTime()+":"+change.getNewState();
                if (!signatures.add(signature)) throw new AssertionError("Duplicate signal event: "+signature);
                currentEvents.add(signature);
                states.put(group,change.getNewState());
                if (states.get("2:avenida") == SignalGroupState.GREEN && states.get("2:calle") == SignalGroupState.GREEN)
                    throw new AssertionError("Incompatible GREEN groups");
                if (change.getNewState()==SignalGroupState.YELLOW) {
                    yellowChanges.incrementAndGet(); yellowStarted.put(group,change.getTime());
                }
                if (change.getNewState()==SignalGroupState.RED && change.getTime()>startTime) {
                    Double yellow=yellowStarted.remove(group);
                    if (yellow==null) throw new AssertionError("RED without YELLOW");
                    // QSim initializes signals on its first step; restoring an
                    // existing red/amber phase need not emit a full yellow interval.
                    if (yellow>startTime+1) amberDurations.add(change.getTime()-yellow);
                    if (change.getTime()>startTime+1) {
                        double expectedRed=change.getSignalGroupId().toString().equals("avenida")?47:78;
                        if (((change.getTime()-offset)%80+80)%80!=expectedRed) throw new AssertionError("Incorrect red boundary");
                    }
                }
            }
        };
        var controler=new Controler(scenario); RunZona1Simulation.configureSignals(controler);
        controler.addControlerListener((org.matsim.core.controler.listener.IterationStartsListener) event -> {
            if (!currentEvents.isEmpty()) iterationEvents.add(java.util.List.copyOf(currentEvents));
            currentEvents.clear(); signatures.clear(); states.clear(); yellowStarted.clear();
        });
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});
        controler.run();
        iterationEvents.add(java.util.List.copyOf(currentEvents));
        if (iterationEvents.size()!=2 || !iterationEvents.get(0).equals(iterationEvents.get(1)))
            throw new AssertionError("Signal series changed between iterations");
        if (!java.util.Arrays.equals(persistedPlan,Files.readAllBytes(output.resolve("signalControl.xml"))))
            throw new AssertionError("Persisted plan was mutated");
        if (arrivals.get()!=8 || exits.size()!=8 || changes.get()==0) throw new AssertionError("Missing arrivals/exits: "+arrivals+"/"+exits.size());
        if (redChanges.get()==0 || greenChanges.get()==0)
            throw new AssertionError("EventsManager did not receive RED and GREEN transitions");
        if (yellowChanges.get()==0 || amberDurations.isEmpty() ||
            amberDurations.stream().anyMatch(d -> d != RunZona1Simulation.AMBER_SECONDS))
            throw new AssertionError("Expected native 4-second amber transitions: "+amberDurations);
        System.out.println("PASS: 8/8 crossings with native permission, 8 arrivals, XML roundtrip, identical signal series in 2 iterations; start="+startTime+" offset="+offset+" evidence "+output);
        System.out.println("PASS: native EventsManager transitions RED="+redChanges+", GREEN="+greenChanges);
        System.out.println("PASS: native YELLOW="+yellowChanges+", amber durations="+amberDurations);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
