package gt.edu.uvg.sim.zona1;

import java.nio.file.Files;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.LinkLeaveEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;

/** Isolate inter-iteration learning: a short red-light route versus a longer but faster bypass. */
public final class ExperiencedTimeRoutingCheck {
    public static void main(String[] args) throws Exception {
        double startTime = 0;
        var output = Files.createTempDirectory(java.nio.file.Path.of("target"), "learned-routing-");
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
        config.controler().setOutputDirectory(output.resolve("run").toString());
        config.controler().setLastIteration(1);
        config.qsim().setStartTime(startTime); config.qsim().setEndTime(startTime+180);
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
        var strategy = new StrategySettings(); strategy.setStrategyName("ReRoute"); strategy.setWeight(1);
        config.strategy().addStrategySettings(strategy);
        config.strategy().setFractionOfIterationsToDisableInnovation(1.0);
        config.planCalcScore().getModes().get("car").setMarginalUtilityOfTraveling(-6);
        var scenario = ScenarioUtils.createScenario(config);
        var net = scenario.getNetwork();
        double[][] xy={{-20,0},{-10,0},{0,0},{10,0},{0,100},{20,0}};
        for (int i=0;i<xy.length;i++) net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        net.getNodes().get(Id.createNodeId(2)).getAttributes().putAttribute("osm:highway","traffic_signals");
        int[][] edges={{0,1},{1,2},{2,3},{3,5},{1,4},{4,3}};
        for (int i=0;i<edges.length;i++) {
            var link=net.getFactory().createLink(Id.createLinkId(i),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
            link.setLength(i>=4?100:10); link.setFreespeed(10); link.setNumberOfLanes(3); link.setCapacity(6000);
            link.setAllowedModes(Set.of("car")); net.addLink(link);
        }
        var f=scenario.getPopulation().getFactory();
        for (int i=0;i<1;i++) {
            var person=f.createPerson(Id.createPersonId("p"+i)); var plan=f.createPlan();
            int start=0, end=3;
            var home=f.createActivityFromLinkId("home",Id.createLinkId(start)); home.setEndTime(startTime+(i<3?1:45));
            plan.addActivity(home); plan.addLeg(f.createLeg("car"));
            plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(end)));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
        LanesGenerator.build(scenario);
        TrafficLightsGenerator.build(scenario);
        TrafficLightsGenerator.write(scenario,output);
        var signals=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);
        signals.setSignalSystemFile(output.resolve("signalSystems.xml").toAbsolutePath().toString());
        signals.setSignalGroupsFile(output.resolve("signalGroups.xml").toAbsolutePath().toString());
        signals.setSignalControlFile(output.resolve("signalControl.xml").toAbsolutePath().toString());
        ((org.matsim.core.scenario.MutableScenario)scenario).removeScenarioElement(SignalsData.ELEMENT_NAME);
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME,new SignalsDataLoader(config).loadSignalsData());
        var routes = new java.util.TreeMap<Integer,java.util.List<String>>();
        var durations = new java.util.TreeMap<Integer,Double>();
        var measured = new java.util.TreeMap<Integer,Double>();
        var scores = new java.util.TreeMap<Integer,Double>();
        var iteration = new java.util.concurrent.atomic.AtomicInteger();
        BasicEventHandler handler=event->{
            if (event instanceof org.matsim.api.core.v01.events.LinkEnterEvent enter)
                routes.computeIfAbsent(iteration.get(),key->new ArrayList<>()).add(enter.getLinkId().toString());
            if (event instanceof PersonArrivalEvent arrival) durations.put(iteration.get(),arrival.getTime()-1);
        };
        var controler=new Controler(scenario); RunZona1Simulation.configureSignals(controler);
        ExperiencedTimeRouting.configure(controler);
        controler.addControlerListener((org.matsim.core.controler.listener.IterationStartsListener)e->iteration.set(e.getIteration()));
        controler.addControlerListener((org.matsim.core.controler.listener.IterationEndsListener)e->{
            measured.put(e.getIteration(),controler.getLinkTravelTimes().getLinkTravelTime(net.getLinks().get(Id.createLinkId(1)),2,null,null));
            scores.put(e.getIteration(),scenario.getPopulation().getPersons().values().iterator().next().getSelectedPlan().getScore());
        });
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});
        controler.run();
        if (!routes.get(0).contains("1") || routes.get(1).contains("1") || !routes.get(1).contains("4"))
            throw new AssertionError("Route did not avoid signal after learning: "+routes);
        if (measured.get(0)<40 || durations.get(1)>=durations.get(0) || scores.get(1)<=scores.get(0))
            throw new AssertionError("Signal delay not learned/scored: "+measured+" / "+durations+" / "+scores);
        System.out.println("PASS: routes="+routes+" observedTimes="+measured+" tripSeconds="+durations+" scores="+scores+" evidence="+output);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
