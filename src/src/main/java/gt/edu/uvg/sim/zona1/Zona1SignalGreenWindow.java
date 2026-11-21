package gt.edu.uvg.sim.zona1;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalPlanData;
import org.matsim.contrib.signals.model.Signal;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.lanes.Lane;

/** Read-only index of the effective, all-day Zona1 fixed-time signal plans.
 * Remaining GREEN is a conservative admission deadline; native lane permission
 * must still be checked at execution. No controller, offset, or event is changed.
 */
public final class Zona1SignalGreenWindow {
    public enum Feasibility { COMPATIBLE, IMPOSSIBLE, UNKNOWN }
    /** Source uses native GREEN/AMBER permission; connectors need GREEN until
     * their cumulative empty-queue deadline. Amber is subtracted exactly once. */
    public record Requirement(Id<Link> from, Id<Lane> lane, Id<Link> to,
                              double deadline, boolean source) { }
    private record Query(List<Requirement> requirements, double step,List<Integer> effectivePhases) { }
    private final Map<Query, Feasibility> feasibilityCache = new HashMap<>();
    private static final long MAX_PERIOD_TICKS = 100_000;
    private record Movement(Set<Id<Lane>> lanes, Set<Id<Link>> turns,
                            SignalPlanData plan, Id<SignalGroup> group) { }
    private final Map<Id<Link>, List<Movement>> movements = new HashMap<>();

    public Zona1SignalGreenWindow(Scenario scenario) {
        var module = scenario.getConfig().getModules().get(SignalSystemsConfigGroup.GROUP_NAME);
        if (module == null) return;
        if (!(module instanceof SignalSystemsConfigGroup config))
            throw new IllegalArgumentException("Typed SignalSystemsConfigGroup required for passage signal deadline");
        if (!config.isUseSignalSystems()) return;
        var element = scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
        if (!(element instanceof SignalsData data))
            throw new IllegalArgumentException("Enabled signal systems require effective SignalsData");
        for (var system : data.getSignalSystemsData().getSignalSystemData().values()) {
            var controller = data.getSignalControlData().getSignalSystemControllerDataBySystemId().get(system.getId());
            if (controller == null || !Zona1FixedTimeController.ID.equals(controller.getControllerIdentifier()) ||
                    controller.getSignalPlanData().size() != 1)
                throw new IllegalArgumentException("Passage signal deadline requires one Zona1FixedTime plan: " + system.getId());
            var plan = controller.getSignalPlanData().values().iterator().next();
            if (plan.getStartTime() != 0 || plan.getEndTime() != 0 || plan.getCycleTime() == null || plan.getCycleTime() <= 0)
                throw new IllegalArgumentException("Passage signal plan must cover the entire day: " + system.getId());
            var groups = data.getSignalGroupsData().getSignalGroupDataBySystemId(system.getId());
            if (groups == null || !plan.getSignalGroupSettingsDataByGroupId().keySet().equals(groups.keySet()))
                throw new IllegalArgumentException("Every signal group requires phase settings: " + system.getId());
            var membership = new HashMap<Id<Signal>, Id<SignalGroup>>();
            for (var group : groups.values()) {
                Zona1FixedTimeController.remainingGreenSeconds(plan,
                    plan.getSignalGroupSettingsDataByGroupId().get(group.getId()), 0);
                for (var signal : group.getSignalIds()) {
                    if (!system.getSignalData().containsKey(signal) || membership.put(signal, group.getId()) != null)
                        throw new IllegalArgumentException("Signal must belong to exactly one existing group: " + signal);
                }
            }
            for (var signal : system.getSignalData().values()) {
                var group = membership.get(signal.getId());
                if (signal.getLinkId() == null || group == null)
                    throw new IllegalArgumentException("Signal lacks link/group: " + signal.getId());
                var lanes = signal.getLaneIds();
                var turns = signal.getTurningMoveRestrictions();
                movements.computeIfAbsent(signal.getLinkId(), ignored -> new ArrayList<>()).add(new Movement(
                    lanes == null ? Set.of() : Set.copyOf(lanes),
                    turns == null ? Set.of() : Set.copyOf(turns), plan, group));
            }
        }
    }

    /** +Infinity when no signal applies to this native link/lane/turn;
     * zero at amber onset, while amber/red, and before green onset.
     */
    public double remainingGreenSeconds(Id<Link> from, Id<Lane> lane, Id<Link> to, double now) {
        if (!Double.isFinite(now) || from == null || to == null)
            throw new IllegalArgumentException("Finite time and native from/to links required");
        double remaining = Double.POSITIVE_INFINITY;
        for (var movement : movements.getOrDefault(from, List.of())) {
            if (!movement.lanes().isEmpty() && !movement.lanes().contains(lane)) continue;
            if (!movement.turns().isEmpty() && !movement.turns().contains(to)) continue;
            remaining = Math.min(remaining, Zona1FixedTimeController.remainingGreenSeconds(movement.plan(),
                movement.plan().getSignalGroupSettingsDataByGroupId().get(movement.group()), now));
        }
        return remaining;
    }

    public Set<Id<Link>> controlledLinks() { return Set.copyOf(movements.keySet()); }

    /** Complete periodic proof on the native tick lattice, across controllers.
     * An unsupported lattice or bounded-search exhaustion is UNKNOWN, never a
     * permanent veto. Cache is instance-local to this effective signal index. */
    public Feasibility feasibility(List<Requirement> requirements, double step) {
        var phases=new ArrayList<Integer>();
        for(var r:requirements)for(var m:movements.getOrDefault(r.from(),List.of())) {
            var settings=m.plan().getSignalGroupSettingsDataByGroupId().get(m.group());
            phases.addAll(List.of(m.plan().getCycleTime(),m.plan().getOffset(),settings.getOnset(),settings.getDropping()));
        }
        var key = new Query(List.copyOf(requirements), step,List.copyOf(phases));
        var cached = feasibilityCache.get(key);
        if (cached != null) return cached;
        var result = computeFeasibility(requirements, step);
        if (feasibilityCache.size() < 100_000) feasibilityCache.put(key, result);
        return result;
    }

    private Feasibility computeFeasibility(List<Requirement> requirements, double step) {
        if (!(step > 0) || !Double.isFinite(step)) return Feasibility.UNKNOWN;
        long period = 1;
        for (var r : requirements) {
            if (r.from() == null || r.to() == null || !Double.isFinite(r.deadline()) || r.deadline() < 0)
                return Feasibility.UNKNOWN;
            for (var m : movements.getOrDefault(r.from(), List.of())) {
                if (!m.turns().isEmpty() && !m.turns().contains(r.to())) continue;
                if (!m.lanes().isEmpty() && r.lane() == null) return Feasibility.UNKNOWN;
                if (!m.lanes().isEmpty() && !m.lanes().contains(r.lane())) continue;
                double ticks = m.plan().getCycleTime() / step;
                if (Math.abs(ticks - Math.rint(ticks)) > 1e-8 || ticks < 1 || ticks > MAX_PERIOD_TICKS)
                    return Feasibility.UNKNOWN;
                long cycle = Math.round(ticks), divisor = gcd(period, cycle);
                if (period / divisor > MAX_PERIOD_TICKS / cycle) return Feasibility.UNKNOWN;
                period = period / divisor * cycle;
            }
        }
        for (long tick = 0; tick < period; tick++) {
            boolean open = true;
            for (var r : requirements) {
                for (var m : movements.getOrDefault(r.from(), List.of())) {
                    if (!m.lanes().isEmpty() && !m.lanes().contains(r.lane()) ||
                        !m.turns().isEmpty() && !m.turns().contains(r.to())) continue;
                    var settings = m.plan().getSignalGroupSettingsDataByGroupId().get(m.group());
                    if (r.source()) {
                        double cycle = m.plan().getCycleTime();
                        double elapsed = ((tick * step - m.plan().getOffset() - settings.getOnset()) % cycle + cycle) % cycle;
                        if (elapsed >= (settings.getDropping() - settings.getOnset() + cycle) % cycle) open = false;
                    } else if (Zona1FixedTimeController.remainingGreenSeconds(m.plan(), settings, tick * step) <= r.deadline())
                        open = false;
                }
                if (!open) break;
            }
            if (open) return Feasibility.COMPATIBLE;
        }
        return Feasibility.IMPOSSIBLE;
    }
    private static long gcd(long a, long b) { while (b != 0) { long next = a % b; a = b; b = next; } return a; }

    /** Proves that two native movements cannot be green together under the
     * same fixed controller. Different controllers or missing coverage do not
     * establish impossibility. Integer phase boundaries make this exact. */
    public boolean mutuallyExclusive(Id<Link> from,Id<Lane> lane,Id<Link> to,
                                     Id<Link> other,Id<Lane> otherLane,Id<Link> otherTo) {
        for(var a:movements.getOrDefault(from,List.of())) {
            if(!a.lanes().isEmpty()&&(lane==null||!a.lanes().contains(lane))||!a.turns().isEmpty()&&!a.turns().contains(to))continue;
            for(var b:movements.getOrDefault(other,List.of())) {
                if(a.plan()!=b.plan()||!b.lanes().isEmpty()&&(otherLane==null||!b.lanes().contains(otherLane))||
                        !b.turns().isEmpty()&&!b.turns().contains(otherTo))continue;
                boolean common=false;
                for(int tick=0;tick<a.plan().getCycleTime();tick++)
                    if(Zona1FixedTimeController.remainingGreenSeconds(a.plan(),a.plan().getSignalGroupSettingsDataByGroupId().get(a.group()),tick)>0 &&
                       Zona1FixedTimeController.remainingGreenSeconds(b.plan(),b.plan().getSignalGroupSettingsDataByGroupId().get(b.group()),tick)>0){common=true;break;}
                if(!common)return true;
            }
        }
        return false;
    }
}
