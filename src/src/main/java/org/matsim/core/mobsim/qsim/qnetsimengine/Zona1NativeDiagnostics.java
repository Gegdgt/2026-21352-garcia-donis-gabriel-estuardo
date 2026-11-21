package org.matsim.core.mobsim.qsim.qnetsimengine;

import com.google.inject.Inject;
import com.google.inject.Singleton;
import gt.edu.uvg.sim.zona1.UnsignalizedPriority;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.signalsystems.v20.SignalData;
import org.matsim.contrib.signals.events.SignalGroupStateChangedEvent;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;

/** Observations at the actual native decision branches, never a replacement decision.
 * Counts are decision attempts, not unique people or seconds of waiting.
 */
@Singleton
public final class Zona1NativeDiagnostics implements BasicEventHandler,
        org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener {
    public static final String EVENT_TYPE = "simz1NativeDecision";
    private static final Set<String> STORAGE_REASONS=Set.of("receiver_native_storage","receiver_storage_or_terminal_slot",
        "passage_receipt_storage_or_slot","passage_receipt_native_queue","passage_native_storage",
        "passage_receipt_locked","passage_previous_not_cleared");
    private record GroupKey(String system, String group) { }
    private record ControlledMovement(GroupKey group, SignalData signal) { }
    private record NativeState(double time, SignalGroupState state) { }
    private final Map<Id<Link>, List<ControlledMovement>> movements = new HashMap<>();
    private final Map<GroupKey, NativeState> states = new ConcurrentHashMap<>();
    private final EventsManager events;
    private final QSimConfigGroup config;
    private final gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup admission;
    private final boolean receiverSnapshots;
    private final List<QLinkI> queueLinks=new ArrayList<>();
    private record ReceiverKey(Id<Link> link, String lane) { }
    private final Map<ReceiverKey, Double> lastStorageSample = new ConcurrentHashMap<>();

    @Inject public Zona1NativeDiagnostics(Scenario scenario, EventsManager events) {
        this(scenario, events, true);
    }

    // Package-private comparison seam: disable receiver enrichment only, keeping
    // every native decision event. Production injection always enables it.
    Zona1NativeDiagnostics(Scenario scenario, EventsManager events, boolean receiverSnapshots) {
        this.events = events;
        this.receiverSnapshots = receiverSnapshots;
        config = scenario.getConfig().qsim();
        admission = ConfigUtils.addOrGetModule(scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
        var settings = ConfigUtils.addOrGetModule(scenario.getConfig(), SignalSystemsConfigGroup.class);
        var data = (SignalsData) scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
        if (!settings.isUseSignalSystems() || data == null) return;
        for (var system : data.getSignalSystemsData().getSignalSystemData().values()) {
            var groups = data.getSignalGroupsData().getSignalGroupDataBySystemId(system.getId());
            if (groups == null) continue;
            for (var group : groups.values()) for (var signalId : group.getSignalIds()) {
                var signal = system.getSignalData().get(signalId);
                if (signal == null) throw new IllegalArgumentException("Missing signal " + signalId);
                movements.computeIfAbsent(signal.getLinkId(), key -> new ArrayList<>()).add(
                    new ControlledMovement(new GroupKey(system.getId().toString(), group.getId().toString()), signal));
            }
        }
    }

    @Override public void reset(int iteration) { states.clear(); queueLinks.clear(); lastStorageSample.clear(); }
    void registerQueueLink(QLinkI link) { if(link.getLink().getAllowedModes().contains("car")) queueLinks.add(link); }

    @Override public void notifyMobsimAfterSimStep(org.matsim.core.mobsim.framework.events.MobsimAfterSimStepEvent event) {
        double now=event.getSimulationTime();
        // QSim invokes this after all engine tasks have joined (MATSim 15
        // QNetsimEngineWithThreadpool.run -> Future.get). Unlike storage(), no
        // downstream node can pop this buffer concurrently at this barrier.
        // Post-step observation covers the native queue before it offers a car
        // to QNode. No capacity getter that mutates fast accumulation is invoked.
        // QueueWithBuffer checks earliest exit, arrival/transit, then flow capacity.
        for(var link:queueLinks) for(var lane:link.getOfferingQLanes()) {
            if(!lane.isNotOfferingVehicle()) continue;
            var vehicle=lane.getFirstVehicle();
            if(vehicle==null || vehicle.getDriver()==null || vehicle.getEarliestLinkExitTime()>=now ||
                    vehicle.getDriver() instanceof org.matsim.core.mobsim.qsim.pt.TransitDriverAgent ||
                    vehicle.getDriver().isWantingToArriveOnCurrentLink()) continue;
            var next=vehicle.getDriver().chooseNextLinkId();
            if(next==null) continue;
            boolean permitted=!(lane instanceof SignalizeableItem signal)||signal.hasGreenForToLink(next);
            record(link.getLink(),lane,next,vehicle,now,permitted?"congestion_queue":"signal_queue_not_green","WAIT");
        }
    }

    @Override public void handleEvent(Event event) {
        if (event instanceof SignalGroupStateChangedEvent signal) {
            states.put(new GroupKey(signal.getSignalSystemId().toString(), signal.getSignalGroupId().toString()),
                new NativeState(signal.getTime(), signal.getNewState()));
        }
    }

    /** MATSim 15 DefaultSignalizeableItem.checkGreen permits amber clearance and OFF.
     * The legacy API name hasGreenForToLink does not mean the color is GREEN.
     */
    static boolean nativePermitsPassage(SignalGroupState state) {
        return state == SignalGroupState.GREEN || state == SignalGroupState.YELLOW || state == SignalGroupState.OFF;
    }

    /** State comes from native events, checked against the native queue permission.
     * Asynchronous delivery can leave the state unavailable: label it explicitly,
     * rather than inferring RED/YELLOW from a schedule or using a stale color.
     */
    private String signalState(Link link, QLaneI lane, Id<Link> next, double now) {
        boolean green = !(lane instanceof SignalizeableItem signal) || signal.hasGreenForToLink(next);
        var colors = new TreeSet<String>();
        for (var movement : movements.getOrDefault(link.getId(), List.of())) {
            var signal = movement.signal;
            if (signal.getLaneIds() != null && !signal.getLaneIds().isEmpty() && !signal.getLaneIds().contains(lane.getId())) continue;
            if (signal.getTurningMoveRestrictions() != null && !signal.getTurningMoveRestrictions().isEmpty()
                    && !signal.getTurningMoveRestrictions().contains(next)) continue;
            var state = states.get(movement.group);
            if (state == null || state.time > now || green != nativePermitsPassage(state.state))
                return green ? "PERMITTED_NATIVE_COLOR_UNAVAILABLE" : "BLOCKED_NATIVE_COLOR_UNAVAILABLE";
            colors.add(state.state.name());
        }
        return colors.isEmpty() ? (green ? "UNSIGNALIZED" : "BLOCKED_NATIVE_COLOR_UNAVAILABLE") : String.join("+", colors);
    }

    void turn(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, QNetwork network,
            double now, TurnAcceptanceLogic.AcceptTurn decision, TurnAcceptanceLogic logic) {
        String reason;
        if (decision == TurnAcceptanceLogic.AcceptTurn.ABORT) {
            reason = next == null ? "turn_abort_null_route" :
                !network.getNetsimLinks().containsKey(next) ? "turn_abort_missing_link" :
                link.getToNode() != network.getNetsimLinks().get(next).getLink().getFromNode() ?
                    "turn_abort_disconnected" : "turn_abort_other";
        } else if (decision == TurnAcceptanceLogic.AcceptTurn.WAIT) {
            boolean permitted = !(lane instanceof SignalizeableItem signal) || signal.hasGreenForToLink(next);
            if (logic instanceof UnsignalizedPriority.StopAndYield priority && permitted) reason = priority.getLastWaitReason();
            else {
                String color = signalState(link, lane, next, now);
                reason = permitted ? "intersection_conflict" : switch (color) {
                    case "RED" -> "signal_red";
                    case "REDYELLOW" -> "signal_redyellow";
                    default -> "signal_not_green";
                };
            }
        } else reason = "turn_go";
        record(link, lane, next, vehicle, now, reason, decision.name());
    }

    void storage(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now, String reason, String decision) {
        record(link, lane, next, vehicle, now, reason, decision);
    }

    void admissionConflict(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now,
            gt.edu.uvg.sim.zona1.PriorityMovements.Movement blocking, String evidence) {
        record(link, lane, next, vehicle, now, "admission_conflict_executed", "WAIT", Map.of(
            "node", link.getToNode().getId().toString(), "admissionScope", "node_step",
            "blockingFromLink", blocking.from().toString(), "blockingNextLink", blocking.to().toString(),
            "conflictEvidence", evidence));
    }

    /** A receipt after addFromUpstream returned; distinct from a turn request. */
    void admitted(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now, QLaneI receiver) {
        var values = new LinkedHashMap<String,String>();
        values.put("decision", "GO"); values.put("reason", "receiver_accepted");
        values.put("node", link.getToNode().getId().toString());
        values.put("person", vehicle.getDriver().getId().toString()); values.put("vehicle", vehicle.getId().toString());
        values.put("link", link.getId().toString()); values.put("nextLink", next.toString());
        values.put("lane", lane.getId().toString()); values.put("receivingLane", receiver.getId().toString());
        values.put("receiverAcceptedAtDecision", "true");
        values.put("wholeVehicleReservation", Boolean.toString(admission.getWholeVehicleReservation()));
        if(admission.getWholeVehicleReservation()) values.put("minimumFootprintGapMeters", "0.1");
        values.put("admissionPolicy", admission.getStoragePolicy()); values.put("admissionPolicyVersion", "1");
        values.put("source", "SimZ1_QNode_strict_receiver_v1");
        var frozen = Map.copyOf(values);
        events.processEvent(new Event(now) {
            @Override public String getEventType() { return "simz1Admission"; }
            @Override public Map<String,String> getAttributes() {
                var attributes = super.getAttributes(); attributes.putAll(frozen); return attributes;
            }
        });
    }

    /** Compatibility entry for callers which observed a native queue refusal. */
    void storage(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now,
            String reason, String decision, QLinkI receiver, QLaneI receivingLane) {
        storage(link,lane,next,vehicle,now,reason,decision,receiver,receivingLane,false);
    }

    /** Called AFTER combined admission failed. The native queue result is
     * captured by QNode before the optional body query; neither is re-queried.
     * receiverAcceptedAtDecision retains its combined-result compatibility
     * meaning. New attribution distinguishes an empty native connector whose
     * downstream body receipt is unavailable from a native queue refusal.
     * With parallel QSim, the following read-only values are not atomic.
     */
    void storage(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now,
            String reason, String decision, QLinkI receiver, QLaneI receivingLane,
            boolean nativeReceiverAccepted) {
        var extra = new LinkedHashMap<String,String>();
        extra.put("receivingLane", receivingLane.getId().toString());
        extra.put("receiverAcceptedAtDecision", "false");
        extra.put("receiverAcceptanceSemantics", "combined_admission_result");
        extra.put("admissionAttributionVersion", "1");
        extra.put("nativeReceiverAcceptedAtDecision", Boolean.toString(nativeReceiverAccepted));
        extra.put("rejectionStage", nativeReceiverAccepted ? "whole_vehicle_reservation" : "native_receiver");
        extra.put("bodyReservationObservation", nativeReceiverAccepted ? "rejected" : "not_evaluated");
        if (nativeReceiverAccepted) extra.put("bodyReservationAcceptedAtDecision", "false");
        if (!receiverSnapshots) {
            record(link,lane,next,vehicle,now,reason,decision,extra);
            return;
        }
        extra.put("storageObservationVersion", "2");
        boolean sample = !decision.equals("WAIT");
        if (!sample) {
            var key = new ReceiverKey(next, receivingLane.getId().toString());
            // QNode owns the decision; compute also serializes sampling if two
            // callers ever observe the same receiver concurrently.
            boolean[] taken = {false};
            lastStorageSample.compute(key, (ignored, previous) -> {
                if (previous == null || now - previous >= 60) { taken[0] = true; return now; }
                return previous;
            });
            sample = taken[0];
        }
        extra.put("storageSnapshot", sample ? (decision.equals("WAIT") ? "sampled_wait" : "intervention") : "not_sampled");
        if (sample) {
            extra.put("snapshotConsistency", "non_atomic_read_only");
            extra.put("receivingQueueType", receivingLane.getClass().getSimpleName());
            extra.put("receivingLoadIndicator", Double.toString(receivingLane.getLoadIndicator()));
            // QLaneI does not promise PCU semantics for arbitrary implementations.
            extra.put("receivingLoadSemantics", receivingLane instanceof QueueWithBuffer ? "pcu_excluding_buffer" : "unspecified");
            extra.put("receivingStorageCapacityPcu", Double.toString(receivingLane.getStorageCapacity()));
            extra.put("receivingFlowCapacityPcuPerStep", Double.toString(receivingLane.getSimulatedFlowCapacityPerTimeStep()));
            extra.put("vehicleSizePcu", Double.toString(vehicle.getSizeInEquivalents()));
            extra.put("sourceHeadLastMovedTime", Double.toString(lane.getLastMovementTimeOfFirstVehicle()));
            int queues = 0, rejecting = 0, offering = 0, signalBlocked = 0;
            // These are another node's incoming buffers, not our owned source.
            // MATSim 15 getFirstVehicle() does isEmpty() then peek().getKey(): a
            // concurrent downstream pop can invalidate even its INTERNAL check.
            // getAllVehicles() also iterates the unsynchronized buffer, so it is
            // not an atomic alternative. Do not peek, copy, lock or catch an NPE.
            // Only serial QSim guarantees no queue writer during this call.
            String headObservation = config.getNumberOfThreads() == 1 ?
                "observed_serial" : "unavailable_parallel_qsim";
            for (var terminal : receiver.getOfferingQLanes()) {
                queues++;
                // An undivided link offers its accepting queue too. Reuse its
                // actual native result, which can be true after body refusal.
                if (terminal == receivingLane ? !nativeReceiverAccepted : !terminal.isAcceptingFromUpstream()) rejecting++;
                if (!terminal.isNotOfferingVehicle()) {
                    offering++;
                    if (config.getNumberOfThreads() != 1) continue;
                    var head = terminal.getFirstVehicle();
                    var target = head == null || head.getDriver() == null ? null : head.getDriver().chooseNextLinkId();
                    if (target == null) headObservation = "unavailable_head";
                    if (target != null && terminal instanceof SignalizeableItem signal && !signal.hasGreenForToLink(target)) signalBlocked++;
                }
            }
            extra.put("receiverExitQueues", Integer.toString(queues));
            extra.put("receiverExitQueuesRejecting", Integer.toString(rejecting));
            extra.put("receiverExitQueuesOffering", Integer.toString(offering));
            extra.put("receiverExitHeadObservation", headObservation);
            extra.put("receiverExitHeadsSignalBlocked", headObservation.equals("observed_serial") ? Integer.toString(signalBlocked) : "unknown");
        }
        record(link, lane, next, vehicle, now, reason, decision, extra);
    }

    private void record(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now, String reason, String decision) {
        record(link, lane, next, vehicle, now, reason, decision, Map.of());
    }

    private void record(Link link, QLaneI lane, Id<Link> next, QVehicle vehicle, double now,
            String reason, String decision, Map<String,String> extra) {
        var attributes = new LinkedHashMap<String,String>();
        attributes.put("reason", reason);
        attributes.put("waitCategory",category(reason));
        attributes.put("waitCategoryVersion","2");
        attributes.put("attemptUnit","native_decision_event");
        attributes.put("decision", decision);
        attributes.put("person", vehicle.getDriver().getId().toString());
        attributes.put("vehicle", vehicle.getId().toString());
        attributes.put("link", link.getId().toString());
        attributes.put("nextLink", next == null ? "" : next.toString());
        attributes.put("lane", lane.getId().toString());
        boolean queued=reason.equals("congestion_queue")||reason.equals("signal_queue_not_green");
        attributes.put("waitSeconds", Double.toString(Math.max(0,now - (queued?vehicle.getEarliestLinkExitTime():lane.getLastMovementTimeOfFirstVehicle()))));
        attributes.put("waitSecondsBasis",queued?"age_since_earliest_link_exit_not_sum_of_wait_attempts":"head_age_since_last_movement_not_reason_duration");
        attributes.put("earliestLinkExitTime",Double.toString(vehicle.getEarliestLinkExitTime()));
        attributes.put("stuckTime", Double.toString(config.getStuckTime()));
        attributes.put("removeStuckVehicles", Boolean.toString(config.isRemoveStuckVehicles()));
        attributes.put("trafficDynamics", config.getTrafficDynamics().name());
        attributes.put("admissionPolicy", admission.getStoragePolicy());
        attributes.put("admissionPolicyVersion", "1");
        if (reason.startsWith("storage_")) attributes.put("storageTimeoutExceeded",
            Boolean.toString(now - lane.getLastMovementTimeOfFirstVehicle() > config.getStuckTime()));
        boolean invalidTurn = reason.startsWith("turn_abort_")||reason.equals("turn_restriction");
        attributes.put("signalState", invalidTurn || next == null ? "NOT_APPLICABLE" : signalState(link, lane, next, now));
        attributes.put("nativeHasGreen", invalidTurn || next == null ? "NOT_APPLICABLE" :
            Boolean.toString(!(lane instanceof SignalizeableItem signal) || signal.hasGreenForToLink(next)));
        attributes.put("source", queued?"MATSim15_queue_post_step":admission.isStrict()?
            "SimZ1_QNode_strict_receiver_v1":"MATSim15_QNode_native_branch");
        attributes.putAll(extra);
        events.processEvent(new DecisionEvent(now, attributes));
    }
    /** Categories describe raw reasons. Only WAIT decisions count as attempts;
     * priority/reservation events from other layers are never added to this total. */
    public static String category(String reason) {
        if(reason==null)return "unknown";
        if(reason.equals("priority_stop")) return "mandatory_stop";
        if(reason.startsWith("priority_")||reason.equals("intersection_conflict")||reason.equals("admission_conflict_executed")) return "yield";
        if(reason.startsWith("signal_")) return "signal";
        if(reason.startsWith("storage_")||STORAGE_REASONS.contains(reason)) return "insufficient_storage";
        if(reason.startsWith("congestion_")) return "congestion";
        if(reason.equals("turn_restriction")||reason.startsWith("turn_abort_")) return "turn_restriction";
        return reason.equals("turn_go")||reason.equals("receiver_accepted")?"none":"unknown";
    }

    public static final class DecisionEvent extends Event {
        private final Map<String,String> values;
        DecisionEvent(double time, Map<String,String> values) { super(time); this.values = Map.copyOf(values); }
        @Override public String getEventType() { return EVENT_TYPE; }
        @Override public Map<String,String> getAttributes() {
            var attributes = super.getAttributes();
            attributes.putAll(values);
            return attributes;
        }
    }
}
