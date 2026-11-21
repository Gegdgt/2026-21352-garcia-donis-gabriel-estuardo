package gt.edu.uvg.sim.zona1;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalPlanData;
import org.matsim.contrib.signals.model.DatabasedSignalPlan;
import org.matsim.contrib.signals.model.Signal;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.contrib.signals.model.SignalPlan;
import org.matsim.contrib.signals.model.SignalSystem;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;

/** Pure plan/index checks plus comparison with actual controller requests. */
public final class Zona1SignalGreenWindowCheck {
    private static final Id<Link> FROM = Id.createLinkId("from"), TO = Id.createLinkId("to");
    private static final Id<Lane> LANE = Id.create("from.lane.0", Lane.class);
    private static final Id<SignalGroup> GROUP = Id.create("g", SignalGroup.class);
    private record Fixture(Scenario scenario, SignalsData data, SignalPlanData plan) { }
    private static int checks;

    public static void main(String[] args) {
        var normal = fixture(0, 0, 47, false);
        var window = new Zona1SignalGreenWindow(normal.scenario());
        equal(43, window.remainingGreenSeconds(FROM, LANE, TO, 0), "green onset");
        equal(1, window.remainingGreenSeconds(FROM, LANE, TO, 42), "one second remains");
        equal(.001, window.remainingGreenSeconds(FROM, LANE, TO, 42.999), "fraction before amber");
        for (double time : new double[]{43, 44.5, 46.999, 47, 79.999})
            equal(0, window.remainingGreenSeconds(FROM, LANE, TO, time), "amber/red boundary " + time);
        equal(43, window.remainingGreenSeconds(FROM, LANE, TO, 80), "next cycle");
        equal(43, window.remainingGreenSeconds(FROM, LANE, TO, 86400), "next day");
        equal(43, window.remainingGreenSeconds(FROM, LANE, TO, 108000), "experimental 30-hour endpoint");
        var shifted = fixture(17, 49, 78, true);
        var lanes = new Zona1SignalGreenWindow(shifted.scenario());
        equal(25, lanes.remainingGreenSeconds(FROM, LANE, TO, 66), "offset onset");
        equal(1, lanes.remainingGreenSeconds(FROM, LANE, TO, 90), "offset across midnight of cycle");
        equal(0, lanes.remainingGreenSeconds(FROM, LANE, TO, 91), "offset amber");
        equal(Double.POSITIVE_INFINITY, lanes.remainingGreenSeconds(FROM, Id.create("other", Lane.class), TO, 91), "other lane");
        equal(Double.POSITIVE_INFINITY, lanes.remainingGreenSeconds(FROM, LANE, Id.createLinkId("other"), 91), "other turn");
        equal(Double.POSITIVE_INFINITY, lanes.remainingGreenSeconds(Id.createLinkId("other"), LANE, TO, 91), "other link");
        var wrap = fixture(0, 70, 15, false);
        var wrapped = new Zona1SignalGreenWindow(wrap.scenario());
        equal(21, wrapped.remainingGreenSeconds(FROM, LANE, TO, 70), "wrapped onset");
        equal(11, wrapped.remainingGreenSeconds(FROM, LANE, TO, 80), "wrapped cycle edge");
        equal(1, wrapped.remainingGreenSeconds(FROM, LANE, TO, 90), "wrapped green end");
        equal(0, wrapped.remainingGreenSeconds(FROM, LANE, TO, 91), "wrapped amber end");
        compareController(normal, new double[]{42, 43, 47, 80}, List.of("onset@42.0", "drop@43.0", "onset@80.0"));
        compareController(normal, new double[]{45, 80}, List.of("drop@43.0", "onset@80.0"));
        compareController(normal, new double[]{50, 80}, List.of("drop@43.0", "onset@80.0"));
        compareController(normal, new double[]{86442, 86443, 86447, 86480},
                List.of("onset@86442.0", "drop@86443.0", "onset@86480.0"));
        compareController(normal, new double[]{107962, 107963, 107967, 108000},
                List.of("onset@107962.0", "drop@107963.0", "onset@108000.0"));
        compareController(wrap, new double[]{79, 80, 91, 150}, List.of("onset@79.0", "drop@91.0", "onset@150.0"));
        rejected(() -> window.remainingGreenSeconds(FROM, LANE, TO, Double.NaN), "nonfinite query");
        var bad = fixture(0, 0, 4, false);
        rejected(() -> new Zona1SignalGreenWindow(bad.scenario()), "no green time");
        var unknown = fixture(0, 0, 47, false);
        unknown.data().getSignalControlData().getSignalSystemControllerDataBySystemId().values().iterator().next().setControllerIdentifier("unknown");
        rejected(() -> new Zona1SignalGreenWindow(unknown.scenario()), "unsupported controller");
        var partial = fixture(0, 0, 47, false); partial.plan().setStartTime(10.0);
        rejected(() -> new Zona1SignalGreenWindow(partial.scenario()), "partial day plan");
        var missing = ScenarioUtils.createScenario(ConfigUtils.createConfig(new SignalSystemsConfigGroup()));
        ConfigUtils.addOrGetModule(missing.getConfig(), SignalSystemsConfigGroup.class).setUseSignalSystems(true);
        rejected(() -> new Zona1SignalGreenWindow(missing), "missing effective data");
        ConfigUtils.addOrGetModule(missing.getConfig(), SignalSystemsConfigGroup.class).setUseSignalSystems(false);
        equal(Double.POSITIVE_INFINITY, new Zona1SignalGreenWindow(missing).remainingGreenSeconds(FROM, LANE, TO, 1), "signals disabled");
        System.out.println("PASS Zona1SignalGreenWindowCheck: " + checks + " exact boundary, offset, wrap, lane/turn, controller and malformed-input checks");
    }

    private static Fixture fixture(int offset, int onset, int dropping, boolean restricted) {
        var config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
        var signals = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class);
        signals.setUseSignalSystems(true); signals.setUseAmbertimes(true);
        var scenario = ScenarioUtils.createScenario(config);
        var data = SignalUtils.createSignalsData(signals);
        scenario.addScenarioElement(SignalsData.ELEMENT_NAME, data);
        var sid = Id.create("system", SignalSystem.class);
        var systems = data.getSignalSystemsData(); var system = systems.getFactory().createSignalSystemData(sid);
        systems.addSignalSystemData(system);
        var signal = systems.getFactory().createSignalData(Id.create("signal", Signal.class));
        signal.setLinkId(FROM);
        if (restricted) { signal.addLaneId(LANE); signal.addTurningMoveRestriction(TO); }
        system.addSignalData(signal);
        var groups = data.getSignalGroupsData(); var group = groups.getFactory().createSignalGroupData(sid, GROUP);
        group.addSignalId(signal.getId()); groups.addSignalGroupData(group);
        var control = data.getSignalControlData(); var controller = control.getFactory().createSignalSystemControllerData(sid);
        controller.setControllerIdentifier(Zona1FixedTimeController.ID); control.addSignalSystemControllerData(controller);
        var plan = control.getFactory().createSignalPlanData(Id.create("daily", SignalPlan.class));
        plan.setStartTime(0.0); plan.setEndTime(0.0); plan.setCycleTime(80); plan.setOffset(offset);
        var settings = control.getFactory().createSignalGroupSettingsData(GROUP);
        settings.setOnset(onset); settings.setDropping(dropping); plan.addSignalGroupSettings(settings);
        controller.addSignalPlanData(plan);
        return new Fixture(scenario, data, plan);
    }

    private static void compareController(Fixture fixture, double[] times, List<String> expected) {
        var requests = new ArrayList<String>();
        var system = (SignalSystem) Proxy.newProxyInstance(SignalSystem.class.getClassLoader(), new Class<?>[]{SignalSystem.class},
            (proxy, method, args) -> switch (method.getName()) {
                case "getSignalGroups" -> java.util.Collections.singletonMap(GROUP, null);
                case "scheduleOnset" -> { requests.add("onset@" + args[0]); yield null; }
                case "scheduleDropping" -> { requests.add("drop@" + args[0]); yield null; }
                default -> throw new AssertionError("Unexpected controller call " + method.getName());
            });
        var controller = new Zona1FixedTimeController(); controller.setSignalSystem(system);
        controller.addPlan(new DatabasedSignalPlan(fixture.plan())); controller.simulationInitialized(times[0]);
        for (int i = 1; i < times.length; i++) controller.updateState(times[i]);
        if (!requests.equals(expected)) throw new AssertionError("Controller transitions changed: " + requests + " expected " + expected);
        checks++;
    }

    private static void equal(double expected, double actual, String label) {
        if (expected != actual && Math.abs(expected - actual) > 1e-8) throw new AssertionError(label + ": " + actual + " expected " + expected);
        checks++;
    }
    private static void rejected(Runnable action, String label) {
        try { action.run(); } catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Accepted " + label);
    }
}
