package gt.edu.uvg.sim.zona1;

import java.util.HashMap;
import java.util.Map;
import org.matsim.api.core.v01.Id;
import org.matsim.contrib.signals.controller.AbstractSignalController;
import org.matsim.contrib.signals.controller.SignalController;
import org.matsim.contrib.signals.controller.SignalControllerFactory;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalPlanData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalGroupSettingsData;
import org.matsim.contrib.signals.model.DatabasedSignalPlan;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.contrib.signals.model.SignalSystem;

/** Native signals controller for one all-day plan; initializes RED/GREEN even mid-cycle. */
public final class Zona1FixedTimeController extends AbstractSignalController {
    public static final String ID = "Zona1FixedTime";
    private final Map<Id<SignalGroup>, Boolean> green = new HashMap<>();
    private SignalPlanData plan;

    public static final class Factory implements SignalControllerFactory {
        @Override public SignalController createSignalSystemController(SignalSystem system) {
            var controller = new Zona1FixedTimeController();
            controller.setSignalSystem(system);
            return controller;
        }
    }

    @Override public void simulationInitialized(double time) {
        if (signalPlans.size() != 1) throw new IllegalArgumentException("Zona1 requires one all-day signal plan");
        plan = ((DatabasedSignalPlan)signalPlans.values().iterator().next()).getPlanData();
        if (plan.getStartTime() != 0 || plan.getEndTime() != 0 || plan.getCycleTime() <= 0)
            throw new IllegalArgumentException("Zona1 plan must cover the entire day with positive cycle");
        if (!plan.getSignalGroupSettingsDataByGroupId().keySet().equals(system.getSignalGroups().keySet()))
            throw new IllegalArgumentException("Every signal group must have phase settings");
        green.clear();
        updateState(time);
    }

    @Override public void updateState(double time) {
        double cycle = plan.getCycleTime();
        double phase = ((time - plan.getOffset()) % cycle + cycle) % cycle;
        for (var settings : plan.getSignalGroupSettingsDataByGroupId().values()) {
            int onset = settings.getOnset(), dropping = settings.getDropping();
            if (onset < 0 || dropping < 0 || onset >= cycle || dropping >= cycle || onset == dropping)
                throw new IllegalArgumentException("Invalid or ambiguous signal phase");
            double greenAndAmber = (dropping - onset + cycle) % cycle;
            if (greenAndAmber <= RunZona1Simulation.AMBER_SECONDS)
                throw new IllegalArgumentException("Signal phase must leave time for green before amber");
            double amberStart = (dropping - RunZona1Simulation.AMBER_SECONDS + cycle) % cycle;
            boolean open = remainingGreenSeconds(plan, settings, time) > 0;
            var id = settings.getSignalGroupId();
            Boolean previous = green.put(id, open);
            if (previous == null || previous != open) {
                // SignalSystemImpl applies these requests and sends
                // SignalGroupStateChangedEvent through its EventsManager.
                // QSim's native signal integration closes/opens the lane queues;
                // emitting a second event here would duplicate the transition.
                if (open) system.scheduleOnset(time, id);
                else {
                    // On initialization restore the remaining amber time (or RED),
                    // instead of starting a new yellow interval at an arbitrary time.
                    double elapsed = (phase - amberStart + cycle) % cycle;
                    system.scheduleDropping(previous == null ? time - elapsed : time, id);
                }
            }
        }
    }

    /** Exact fixed-plan GREEN interval, excluding the existing amber clearance.
     * This is schedule evidence for admission, not a replacement signal event.
     */
    public static double remainingGreenSeconds(SignalPlanData plan, SignalGroupSettingsData settings, double time) {
        if (!Double.isFinite(time) || plan.getCycleTime() == null || plan.getCycleTime() <= 0)
            throw new IllegalArgumentException("Finite time and positive signal cycle required");
        double cycle = plan.getCycleTime();
        int onset = settings.getOnset(), dropping = settings.getDropping();
        if (onset < 0 || dropping < 0 || onset >= cycle || dropping >= cycle || onset == dropping)
            throw new IllegalArgumentException("Invalid or ambiguous signal phase");
        double greenAndAmber = (dropping - onset + cycle) % cycle;
        if (greenAndAmber <= RunZona1Simulation.AMBER_SECONDS)
            throw new IllegalArgumentException("Signal phase must leave time for green before amber");
        double phase = ((time - plan.getOffset()) % cycle + cycle) % cycle;
        double amberStart = (dropping - RunZona1Simulation.AMBER_SECONDS + cycle) % cycle;
        boolean open = onset < amberStart ? phase >= onset && phase < amberStart : phase >= onset || phase < amberStart;
        return open ? (amberStart - phase + cycle) % cycle : 0;
    }
}
