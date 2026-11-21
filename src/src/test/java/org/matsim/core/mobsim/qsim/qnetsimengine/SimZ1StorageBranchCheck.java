package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;

/** Calls the actual scoped MATSim QNode movement branch, with two tiny queue
 * doubles. No controller, population generation, output directory or QSim run.
 * This checks branch semantics, not calibrated flow or a full network's stability.
 */
public final class SimZ1StorageBranchCheck {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    static final class QueueState {
        double load = 1, capacity = 1, lastMoved = 0;
        boolean green = true, offered = true;
        boolean rejectHeadRead, failAdmission;
        int pops, additions, admissionQueries, headReads;
        QVehicle vehicle;
        QLaneI lane;
        QueueState(String id) {
            lane = (QLaneI) Proxy.newProxyInstance(QLaneI.class.getClassLoader(),
                new Class<?>[]{QLaneI.class, SignalizeableItem.class}, (proxy, method, args) -> switch (method.getName()) {
                    case "getId" -> Id.create(id, Lane.class);
                    case "getLastMovementTimeOfFirstVehicle" -> lastMoved;
                    case "getLoadIndicator" -> load;
                    case "getStorageCapacity" -> capacity;
                    case "getSimulatedFlowCapacityPerTimeStep" -> .05;
                    case "isAcceptingFromUpstream" -> {
                        if (failAdmission) throw new IllegalStateException("fixture physical admission failure");
                        admissionQueries++; yield load < capacity;
                    }
                    case "isNotOfferingVehicle" -> !offered;
                    case "hasGreenForToLink", "hasGreenForAllToLinks" -> green;
                    case "getFirstVehicle" -> {
                        headReads++;
                        if (rejectHeadRead) throw new AssertionError("Unsafe receiver head read");
                        yield vehicle;
                    }
                    case "popFirstVehicle" -> { pops++; offered = false; yield vehicle; }
                    case "addFromUpstream" -> { additions++; load++; yield null; }
                    default -> throw new AssertionError("Unexpected queue call: "+method);
                });
        }
    }

    static final class Fixture {
        final Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final QueueState source = new QueueState("in.0"), receiver = new QueueState("out.original"), terminal = new QueueState("out.0");
        final ArrayList<Event> events = new ArrayList<>();
        final MobsimTimer timer = new MobsimTimer(1.0);
        final QVehicle vehicle;
        final Zona1QNodeImpl node;
        final Zona1NativeDiagnostics diagnostics;
        final QLinkI fromLink;
        int aborted, advanced, arranged;

        Fixture(boolean remove) { this(remove, true); }

        Fixture(boolean remove, boolean divided) {
            this(remove, divided, true, EventsUtils.createEventsManager());
        }

        Fixture(boolean remove, boolean divided, boolean receiverSnapshots, EventsManager manager) {
            this(remove, divided, receiverSnapshots, manager, false);
        }

        Fixture(boolean remove, boolean divided, boolean receiverSnapshots, EventsManager manager, boolean strict) {
            var config = scenario.getConfig().qsim();
            config.setStuckTime(10); config.setRemoveStuckVehicles(remove); config.setNumberOfThreads(1);
            var admission = ConfigUtils.addOrGetModule(scenario.getConfig(), gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
            if (strict) admission.setStoragePolicy(gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.STRICT);
            var network = scenario.getNetwork();
            for (int i = 0; i < 3; i++) network.addNode(network.getFactory().createNode(Id.createNodeId(i), new Coord(i*10, 0)));
            for (int i = 0; i < 2; i++) {
                var link = network.getFactory().createLink(Id.createLinkId(i == 0 ? "in" : "out"),
                    network.getNodes().get(Id.createNodeId(i)), network.getNodes().get(Id.createNodeId(i+1)));
                link.setLength(10); link.setFreespeed(10); link.setCapacity(180); link.setNumberOfLanes(1);
                link.setAllowedModes(Set.of("car")); network.addLink(link);
            }
            var driver = (MobsimDriverAgent) Proxy.newProxyInstance(MobsimDriverAgent.class.getClassLoader(),
                new Class<?>[]{MobsimDriverAgent.class}, (proxy, method, args) -> switch (method.getName()) {
                    case "getId" -> Id.createPersonId("p");
                    case "chooseNextLinkId" -> Id.createLinkId("out");
                    case "notifyMoveOverNode" -> { advanced++; yield null; }
                    case "setStateToAbort" -> { aborted++; yield null; }
                    default -> throw new AssertionError("Unexpected driver call: "+method);
                });
            vehicle = (QVehicle) Proxy.newProxyInstance(QVehicle.class.getClassLoader(), new Class<?>[]{QVehicle.class},
                (proxy, method, args) -> switch (method.getName()) {
                    case "getId" -> Id.createVehicleId("v");
                    case "getDriver" -> driver;
                    case "getCurrentLink" -> network.getLinks().get(Id.createLinkId("in"));
                    case "getEarliestLinkExitTime" -> 0.0;
                    case "getSizeInEquivalents" -> 1.0;
                    case "getPassengers" -> List.of();
                    default -> throw new AssertionError("Unexpected vehicle call: "+method);
                });
            source.vehicle = vehicle;
            receiver.vehicle = vehicle;
            // A full terminal can coexist with a blocked shared receiving queue;
            // this is a controlled snapshot, not simulated causal attribution.
            terminal.vehicle = vehicle; terminal.green = false;
            var links = new HashMap<Id<Link>,QLinkI>();
            for (var link : network.getLinks().values()) {
                var queue = link.getId().toString().equals("in") ? source : receiver;
                var exit = queue == source ? source : (divided ? terminal : receiver);
                links.put(link.getId(), (QLinkI) Proxy.newProxyInstance(QLinkI.class.getClassLoader(), new Class<?>[]{QLinkI.class},
                    (proxy, method, args) -> switch (method.getName()) {
                        case "getLink" -> link;
                        case "getAcceptingQLane" -> queue.lane;
                        case "getOfferingQLanes" -> List.of(exit.lane);
                        default -> throw new AssertionError("Unexpected link call: "+method);
                    }));
            }
            fromLink = links.get(Id.createLinkId("in"));
            var qnet = new QNetwork(network, null) {
                @Override public Map<Id<Link>,QLinkI> getNetsimLinks() { return links; }
            };
            var engine = new QNetsimEngineI.NetsimInternalInterface() {
                public QNetwork getNetsimNetwork() { return qnet; }
                public void arrangeNextAgentState(org.matsim.core.mobsim.framework.MobsimAgent agent) { arranged++; }
                public void letVehicleArrive(QVehicle veh) { throw new AssertionError("Unexpected arrival"); }
            };
            manager.addHandler((BasicEventHandler) events::add);
            diagnostics = new Zona1NativeDiagnostics(scenario, manager, receiverSnapshots);
            var context = new NetsimEngineContext(manager, 7.5, null, null, config, timer, null);
            var builder = new Zona1QNodeImpl.Builder(engine, context, config, diagnostics);
            builder.setTurnAcceptanceLogic(new SignalTurnAcceptanceLogic());
            builder.setAdmissionPolicy(admission, new gt.edu.uvg.sim.zona1.Zona1PriorityConfigGroup());
            node = builder.build(network.getNodes().get(Id.createNodeId(1)));
        }

        boolean attempt(double time) throws Exception {
            return attempt(time, source.lane);
        }
        boolean attempt(double time, QLaneI offeredLane) throws Exception {
            timer.setTime(time);
            var method = Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode", QVehicle.class, QLinkI.class, QLaneI.class, double.class);
            method.setAccessible(true);
            return (boolean) method.invoke(node, vehicle, fromLink, offeredLane, time);
        }
        List<Event> decisions(String reason) {
            return events.stream().filter(e -> reason.equals(e.getAttributes().get("reason"))).toList();
        }
        long count(String type) { return events.stream().filter(e -> e.getEventType().equals(type)).count(); }
    }

    public static void main(String[] args) throws Exception {
        var blocked = new Fixture(false);
        check(!blocked.attempt(5), "Full receiver must wait before timeout");
        check(!blocked.attempt(10), "Timeout is strict >, not >=");
        check(blocked.source.pops == 0 && blocked.receiver.additions == 0, "WAIT changed queues");
        check(blocked.count("entered link") == 0, "GO permission is not LinkEnter");
        var waits = blocked.decisions("storage_wait");
        check(waits.size() == 2, "Missing WAIT evidence");
        check(waits.get(0).getAttributes().get("storageSnapshot").equals("sampled_wait"), "First WAIT not sampled");
        check(waits.get(1).getAttributes().get("storageSnapshot").equals("not_sampled"), "WAIT sampling not bounded");
        check(blocked.attempt(11), "Full receiver must take native force branch after timeout");
        check(blocked.source.pops == 1 && blocked.receiver.additions == 1 && blocked.receiver.load == 2,
            "Native forced move did not insert into the full receiver");
        check(blocked.count("entered link") == 1 && blocked.count("left link") == 1 && blocked.aborted == 0,
            "Forced move confused with removal");
        var snapshot = blocked.decisions("storage_forced_move").get(0).getAttributes();
        check(snapshot.get("receivingLoadIndicator").equals("1.0"), "Snapshot must precede forced insertion");
        check(snapshot.get("receivingLane").equals("out.original"), "Must inspect receiving queue, not source/terminal");
        check(snapshot.get("receiverExitQueuesRejecting").equals("1") && snapshot.get("receiverExitHeadsSignalBlocked").equals("1"),
            "Terminal pressure/signal evidence missing");
        check(snapshot.get("receivingLoadSemantics").equals("unspecified"), "Proxy must not claim native PCU semantics");
        check(blocked.receiver.admissionQueries == 3, "Diagnostics repeated the receiving admission decision");

        var undivided = new Fixture(false, false);
        check(!undivided.attempt(5), "Undivided full link must wait");
        check(undivided.receiver.admissionQueries == 1, "Undivided receiver was queried twice");

        var normal = new Fixture(false);
        normal.receiver.load = 0;
        check(normal.attempt(100) && normal.decisions("storage_forced_move").isEmpty(), "Age alone must not force a normal move");
        check(normal.receiver.load == 1 && normal.aborted == 0, "Normal movement failed");

        var red = new Fixture(false);
        red.source.green = false;
        check(!red.attempt(30), "Red must wait even beyond stuckTime");
        check(red.receiver.admissionQueries == 0 && red.decisions("storage_forced_move").isEmpty(), "Red reached storage force branch");
        red.source.green = true;
        check(red.attempt(31), "Green with a full receiver inherits native head clock");
        check(red.decisions("storage_forced_move").size() == 1, "Expected inherited-clock intervention");

        var removal = new Fixture(true);
        check(!removal.attempt(11), "Preserve native removal return value");
        check(removal.aborted == 1 && removal.arranged == 1 && removal.receiver.additions == 0,
            "Removal must abort without insertion");
        check(removal.decisions("storage_stuck_removal").size() == 1 && removal.count("entered link") == 0, "Removal evidence incorrect");

        var resample = new Fixture(false);
        resample.scenario.getConfig().qsim().setStuckTime(1000);
        resample.attempt(1); resample.attempt(60); resample.attempt(61);
        check(resample.decisions("storage_wait").stream().filter(e -> "sampled_wait".equals(e.getAttributes().get("storageSnapshot"))).count() == 2,
            "WAIT should sample once per receiver per 60 seconds");
        resample.diagnostics.reset(1);
        resample.attempt(1);
        check(resample.decisions("storage_wait").get(resample.decisions("storage_wait").size() - 1).getAttributes().get("storageSnapshot").equals("sampled_wait"), "Sampling did not reset between iterations");
        System.out.println("PASS SimZ1: WAIT, strict timeout, forced insertion, removal, red/green head clock and receiver snapshots; no QSim run");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
