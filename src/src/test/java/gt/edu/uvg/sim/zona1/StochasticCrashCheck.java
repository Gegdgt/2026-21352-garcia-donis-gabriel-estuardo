package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener;

/** Deterministic integration fixture: forced incidents, two controller iterations. */
public final class StochasticCrashCheck {
    public static void main(String[] args) {
        var config = ConfigUtils.createConfig();
        config.network().setTimeVariantNetwork(true);
        config.controler().setLastIteration(1);
        config.controler().setOutputDirectory("target/simz1-crash-test-v2");
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(6000);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        for (String type : List.of("home", "work")) {
            var activity = new org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams(type);
            activity.setTypicalDuration(3600);
            activity.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(activity);
        }
        var strategy = new org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings();
        strategy.setStrategyName("KeepLastSelected");
        strategy.setWeight(1.0);
        config.strategy().addStrategySettings(strategy);
        var scenario = ScenarioUtils.createScenario(config);
        var net = scenario.getNetwork();
        for (int i=0;i<4;i++) {
            var node = net.getFactory().createNode(Id.createNodeId(i),new Coord(i*2000,0));
            net.addNode(node);
        }
        for (int i=0;i<4;i++) {
            var link = net.getFactory().createLink(Id.createLinkId(i),net.getNodes().get(Id.createNodeId(i)),
                net.getNodes().get(Id.createNodeId((i+1)%4)));
            link.setLength(2000); link.setFreespeed(10); link.setCapacity(2000); link.setNumberOfLanes(1);
            net.addLink(link);
        }
        var factory = scenario.getPopulation().getFactory();
        var person = factory.createPerson(Id.createPersonId("test"));
        var plan = factory.createPlan();
        var home = factory.createActivityFromLinkId("home", Id.createLinkId(0)); home.setEndTime(1);
        plan.addActivity(home); plan.addLeg(factory.createLeg("car"));
        plan.addActivity(factory.createActivityFromLinkId("work", Id.createLinkId(2)));
        person.addPlan(plan); scenario.getPopulation().addPerson(person);
        var records = Collections.synchronizedList(new ArrayList<Map<String,String>>());
        BasicEventHandler logger = event -> {
            if (event.getEventType().startsWith("zona1Incident")) records.add(new HashMap<>(event.getAttributes()));
        };
        var observedReduced = new java.util.concurrent.atomic.AtomicBoolean();
        MobsimAfterSimStepListener observer = event -> {
            for (var link : net.getLinks().values()) {
                double t=event.getSimulationTime();
                if (Math.abs(link.getCapacity(t)-400)<1e-6 && Math.abs(link.getFreespeed(t)-3)<1e-6) {
                    observedReduced.set(true);
                }
            }
        };
        var controler = new Controler(scenario);
        RunZona1Simulation.install(controler,new StochasticCrashEvent(scenario,42,1,.2,.3));
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance(logger);
                addMobsimListenerBinding().toInstance(observer);
            }
        });
        controler.run();
        long starts=0, ends=0;
        for (var record : records) {
            double duration=Double.parseDouble(record.get("durationSeconds"));
            if (duration<900 || duration>2700) throw new AssertionError("duration");
            boolean start=record.get("type").equals("zona1IncidentStart");
            if (start) starts++; else ends++;
            if (!start && !record.get("reason").equals("duration_elapsed")) throw new AssertionError("early recovery");
            if (Math.abs(Double.parseDouble(record.get("capacityPerHour"))-(start?400:2000))>1e-6)
                throw new AssertionError("capacity units");
        }
        if (starts<2 || starts!=ends || !observedReduced.get()) throw new AssertionError("incidents not applied/recovered");
        if (!org.matsim.core.network.NetworkUtils.getNetworkChangeEvents(net).isEmpty()) throw new AssertionError("iteration leak");
        for (var link : net.getLinks().values()) {
            if (link.getCapacity(6000)!=2000 || link.getFreespeed(6000)!=10) throw new AssertionError("not restored");
        }
        System.out.println("PASS: two iterations, "+starts+" starts/recoveries; live attributes and hourly units verified");
    }
}
