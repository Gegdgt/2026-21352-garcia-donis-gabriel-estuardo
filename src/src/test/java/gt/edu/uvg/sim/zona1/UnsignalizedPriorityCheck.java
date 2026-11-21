package gt.edu.uvg.sim.zona1;
import java.nio.file.Files;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.LinkLeaveEvent;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;

/** Compare actual link exits with/without stop policy, across two iterations. */
public final class UnsignalizedPriorityCheck {
    static Map<String,List<Double>> run(boolean priority) throws Exception {
        var output = Files.createTempDirectory(java.nio.file.Path.of("target"), "priority-");
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
        config.controler().setOutputDirectory(output.resolve("run").toString());
        config.controler().setLastIteration(1);
        config.qsim().setStartTime(0); config.qsim().setEndTime(0+180);
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

        int[][] edges={{0,1},{1,2},{2,3},{4,5},{5,2},{2,6}};
        for (int i=0;i<edges.length;i++) {
            var link=net.getFactory().createLink(Id.createLinkId(i),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
            link.setLength(10); link.setFreespeed(10); link.setNumberOfLanes(1); link.setCapacity(6000);
            link.setAllowedModes(Set.of("car")); net.addLink(link);
        }
        var f=scenario.getPopulation().getFactory();
        for (int i=0;i<4;i++) {
            var person=f.createPerson(Id.createPersonId("p"+i)); var plan=f.createPlan();
            person.getAttributes().putAttribute("drivingProfile",java.util.List.of("Tortuga","Normal","Liebre").get(i%3));
            int start=i<3?0:3, end=i<3?2:5;
            var home=f.createActivityFromLinkId("home",Id.createLinkId(start)); home.setEndTime((i<3?1:6));
            plan.addActivity(home); plan.addLeg(f.createLeg("car"));
            plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(end)));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
        }
        LanesGenerator.build(scenario);

        var node=net.getNodes().get(Id.createNodeId(2));
        if (!UnsignalizedPriority.eligible(node,Set.of())) throw new AssertionError("Missing crossing");
        node.getAttributes().putAttribute("osm:highway","traffic_signals");
        if (UnsignalizedPriority.eligible(node,Set.of())) throw new AssertionError("Tagged signals changed");
        node.getAttributes().removeAttribute("osm:highway");
        if (UnsignalizedPriority.eligible(node,Set.of(node.getId()))) throw new AssertionError("Explicit signals changed");
        if (UnsignalizedPriority.eligible(net.getNodes().get(Id.createNodeId(1)),Set.of())) throw new AssertionError("Single axis changed");
        var exits=new HashMap<String,List<Double>>();
        BasicEventHandler handler=event->{
            if (event instanceof LinkLeaveEvent leave && Set.of("1","4").contains(leave.getLinkId().toString()))
                exits.computeIfAbsent(leave.getVehicleId().toString(), k->new ArrayList<>()).add(leave.getTime());
        };
        var controler=new Controler(scenario);
        if (priority) UnsignalizedPriority.configure(controler);
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});
        controler.run();
        return exits;
    }
    public static void main(String[] args) throws Exception {
        var base=run(false); var stops=run(true);
        for(int i=0;i<4;i++) {
            var b=base.get("p"+i); var s=stops.get("p"+i);
            if(b==null || s==null || b.size()!=2 || s.size()!=2) throw new AssertionError("Missing exits");
            for(int j=0;j<2;j++) {
                if(i<3 && s.get(j)-b.get(j)<5) throw new AssertionError("Street did not stop: "+stops);
                if(i==3 && !s.get(j).equals(b.get(j))) throw new AssertionError("Avenue delayed");
            }
        }
        for(int j=0;j<2;j++) {
            var times=new ArrayList<Double>();
            for(int i=0;i<3;i++) times.add(stops.get("p"+i).get(j));
            Collections.sort(times);
            if(times.get(0)<=stops.get("p3").get(j)) throw new AssertionError("Street failed to yield to simultaneous avenue");
            for(int i=1;i<3;i++) if(times.get(i)-times.get(i-1)<5) throw new AssertionError("Following vehicle skipped stop");
        }
        System.out.println("PASS: per-vehicle five-second stops, avenue unchanged, two iterations; baseline="+base+" priority="+stops);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
