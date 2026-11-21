package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup;
import gt.edu.uvg.sim.zona1.Zona1PriorityConfigGroup;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.*;
import java.util.concurrent.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;

/** Pure adapter check: both four node owners and two owners + two event readers.
 * No Controler, QSim run, population, files or network requests. Queue ownership
 * follows MATSim 15's single actor per node, not concurrent calls on one node.
 * It checks isolation and completed transfers, not the actual QSim scheduler,
 * calibrated capacity, a network's freedom from gridlock, or physical trajectories.
 */
public final class SimZ1AdmissionConcurrencyCheck {
    private static final int EPISODES = 50;
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private record Snapshot(String type, double time, Map<String,String> attributes) { }

    private static final class Owner {
        Thread thread;
        void bind() { check(thread == null, "Node actor was rebound"); thread = Thread.currentThread(); }
        void require() {
            if (thread != null && thread != Thread.currentThread())
                throw new AssertionError("Queue accessed outside its node actor");
        }
    }

    private static final class Queue {
        final QLaneI lane;
        final Owner owner;
        final boolean receiving;
        final Set<String> inserted = new HashSet<>();
        QVehicle head;
        double load;
        int pops, additions, admissions;
        Queue(String id, Owner owner, boolean receiving) {
            this.owner = owner; this.receiving = receiving;
            lane = (QLaneI) Proxy.newProxyInstance(QLaneI.class.getClassLoader(),
                new Class<?>[]{QLaneI.class, SignalizeableItem.class}, (proxy, method, args) -> {
                    owner.require();
                    return switch (method.getName()) {
                        case "getId" -> Id.create(id, Lane.class);
                        case "getLastMovementTimeOfFirstVehicle" -> 0.0;
                        case "getLoadIndicator" -> load;
                        case "getStorageCapacity" -> 1.0;
                        case "getSimulatedFlowCapacityPerTimeStep" -> 1.0;
                        case "isAcceptingFromUpstream" -> { admissions++; yield load < 1; }
                        // Simulate an offering downstream buffer whose head is
                        // unsafe to inspect during the parallel node phase.
                        case "isNotOfferingVehicle" -> !receiving && head == null;
                        case "hasGreenForToLink", "hasGreenForAllToLinks" -> true;
                        case "getFirstVehicle" -> {
                            check(!receiving, "Parallel decision read a receiving head"); yield head;
                        }
                        case "popFirstVehicle" -> {
                            check(!receiving && head != null, "Duplicate or wrong source pop");
                            QVehicle value = head; head = null; pops++; yield value;
                        }
                        case "addFromUpstream" -> {
                            check(receiving && load < 1, "Insertion without receiver admission");
                            String vehicle = ((QVehicle) args[0]).getId().toString();
                            check(inserted.add(vehicle), "Vehicle inserted twice: " + vehicle);
                            load++; additions++; yield null;
                        }
                        default -> throw new AssertionError("Unexpected queue call: " + method);
                    };
                });
        }
    }

    private static final class Fixture {
        final String prefix;
        final Owner owner = new Owner();
        final Queue[] source = new Queue[2], receiver = new Queue[2];
        final QLinkI[] incoming = new QLinkI[2];
        final Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final MobsimTimer timer = new MobsimTimer(1);
        final Zona1QNodeImpl node;
        final Method move;
        final Set<String> advanced = new HashSet<>();

        Fixture(String prefix, List<BlockingQueue<Snapshot>> readers) throws Exception {
            this(prefix,readers,true);
        }
        Fixture(String prefix, List<BlockingQueue<Snapshot>> readers, boolean strict) throws Exception {
            this.prefix = prefix;
            var config = scenario.getConfig().qsim();
            config.setStuckTime(10); config.setRemoveStuckVehicles(false); config.setNumberOfThreads(4);
            var admission = ConfigUtils.addOrGetModule(scenario.getConfig(), SimZ1AdmissionConfigGroup.class);
            admission.setStoragePolicy(strict ? SimZ1AdmissionConfigGroup.STRICT : SimZ1AdmissionConfigGroup.NATIVE);
            var signals = ConfigUtils.addOrGetModule(scenario.getConfig(),SignalSystemsConfigGroup.class);
            signals.setUseSignalSystems(true);
            signals.setIntersectionLogic(SignalSystemsConfigGroup.IntersectionLogic.NONE);
            var network = scenario.getNetwork();
            double[][] xy = {{0,0},{-10,0},{10,0},{0,-10},{0,10}};
            for (int i = 0; i < xy.length; i++) network.addNode(network.getFactory().createNode(
                Id.createNodeId(prefix + i), new Coord(xy[i][0],xy[i][1])));
            var links = new HashMap<Id<Link>,QLinkI>();
            for (int movement = 0; movement < 2; movement++) {
                source[movement] = new Queue(prefix + "in" + movement + ".0", owner, false);
                receiver[movement] = new Queue(prefix + "out" + movement + ".original", owner, true);
                for (int direction = 0; direction < 2; direction++) {
                    boolean in = direction == 0;
                    int end = movement * 2 + direction + 1;
                    String id = prefix + (in ? "in" : "out") + movement;
                    var link = network.getFactory().createLink(Id.createLinkId(id),
                        network.getNodes().get(Id.createNodeId(prefix + (in ? end : 0))),
                        network.getNodes().get(Id.createNodeId(prefix + (in ? 0 : end))));
                    link.setLength(10); link.setFreespeed(10); link.setCapacity(3600);
                    link.setNumberOfLanes(1); link.setAllowedModes(Set.of("car")); network.addLink(link);
                    Queue queue = in ? source[movement] : receiver[movement];
                    QLinkI qlink = (QLinkI) Proxy.newProxyInstance(QLinkI.class.getClassLoader(),
                        new Class<?>[]{QLinkI.class}, (proxy, method, args) -> {
                            owner.require();
                            return switch (method.getName()) {
                                case "getLink" -> link;
                                case "getAcceptingQLane" -> queue.lane;
                                case "getOfferingQLanes" -> List.of(queue.lane);
                                default -> throw new AssertionError("Unexpected link call: " + method);
                            };
                        });
                    links.put(link.getId(), qlink);
                    if (in) incoming[movement] = qlink;
                }
            }
            var qnet = new QNetwork(network, null) {
                @Override public Map<Id<Link>,QLinkI> getNetsimLinks() { owner.require(); return links; }
            };
            var engine = new QNetsimEngineI.NetsimInternalInterface() {
                public QNetwork getNetsimNetwork() { owner.require(); return qnet; }
                public void arrangeNextAgentState(org.matsim.core.mobsim.framework.MobsimAgent agent) {
                    throw new AssertionError("Strict blocked receiver aborted a vehicle");
                }
                public void letVehicleArrive(QVehicle vehicle) { throw new AssertionError("Unexpected arrival"); }
            };
            var manager = (EventsManager) Proxy.newProxyInstance(EventsManager.class.getClassLoader(),
                new Class<?>[]{EventsManager.class}, (proxy, method, args) -> {
                    check(method.getName().equals("processEvent"), "Unexpected events manager call: " + method);
                    owner.require(); Event event = (Event) args[0];
                    var snapshot = new Snapshot(event.getEventType(), event.getTime(), Map.copyOf(event.getAttributes()));
                    for (var reader : readers) check(reader.offer(snapshot), "Bounded event reader overflow");
                    return null;
                });
            var diagnostics = new Zona1NativeDiagnostics(scenario, manager);
            var context = new NetsimEngineContext(manager,7.5,null,null,config,timer,null);
            var builder = new Zona1QNodeImpl.Builder(engine,context,config,diagnostics);
            // The factory selects this native logic for signalized NONE nodes.
            // Queue doubles supply green; no signal scheduler is simulated.
            builder.setTurnAcceptanceLogic(new SignalTurnAcceptanceLogic());
            builder.setAdmissionPolicy(admission,new Zona1PriorityConfigGroup());
            node = builder.build(network.getNodes().get(Id.createNodeId(prefix + 0)));
            move = Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);
            move.setAccessible(true);
        }

        private QVehicle vehicle(int movement, int episode) {
            String id = prefix + "v" + episode + "_" + movement;
            var driver = (MobsimDriverAgent) Proxy.newProxyInstance(MobsimDriverAgent.class.getClassLoader(),
                new Class<?>[]{MobsimDriverAgent.class}, (proxy, method, args) -> {
                    owner.require();
                    return switch (method.getName()) {
                        case "getId" -> Id.createPersonId(prefix + "p" + episode + "_" + movement);
                        case "chooseNextLinkId" -> Id.createLinkId(prefix + "out" + movement);
                        case "notifyMoveOverNode" -> { check(advanced.add(id), "Driver advanced twice: " + id); yield null; }
                        case "setStateToAbort" -> throw new AssertionError("Unexpected vehicle abort");
                        default -> throw new AssertionError("Unexpected driver call: " + method);
                    };
                });
            return (QVehicle) Proxy.newProxyInstance(QVehicle.class.getClassLoader(), new Class<?>[]{QVehicle.class},
                (proxy, method, args) -> {
                    owner.require();
                    return switch (method.getName()) {
                        case "getId" -> Id.createVehicleId(id);
                        case "getDriver" -> driver;
                        case "getCurrentLink" -> incoming[movement].getLink();
                        case "getEarliestLinkExitTime" -> 0.0;
                        case "getSizeInEquivalents" -> 1.0;
                        case "getPassengers" -> List.of();
                        default -> throw new AssertionError("Unexpected vehicle call: " + method);
                    };
                });
        }

        boolean attempt(int movement, double time) throws Exception {
            timer.setTime(time);
            try { return (boolean) move.invoke(node,source[movement].head,incoming[movement],source[movement].lane,time); }
            catch (InvocationTargetException error) {
                if (error.getCause() instanceof Error failure) throw failure;
                if (error.getCause() instanceof Exception failure) throw failure;
                throw error;
            }
        }

        void run(CyclicBarrier phase) throws Exception {
            owner.bind();
            for (int episode = 0; episode < EPISODES; episode++) {
                double now = 100 + 2 * episode;
                for (int i = 0; i < 2; i++) { source[i].head = vehicle(i,episode); receiver[i].load = i == 0 ? 1 : 0; }
                phase.await(10,TimeUnit.SECONDS);
                int pops = source[0].pops, queries = receiver[0].admissions;
                check(!attempt(0,now), "Full receiver crossed after stuckTime");
                check(source[0].pops == pops && receiver[0].admissions == queries + 1, "WAIT mutated source or repeated admission");
                check(attempt(1,now), "Blocked other movement reserved conflict, or another node interfered");
                receiver[0].load = 0; // Explicit fixture release, not simulated drainage.
                check(!attempt(0,now), "Incompatible green crossed a movement already executed in this step");
                check(source[0].pops == pops && source[0].head != null, "Conflict WAIT removed the head");
                phase.await(10,TimeUnit.SECONDS);
                check(attempt(0,now + 1), "Node-local conflict state failed to reset next step");
                check(source[0].head == null && source[1].head == null, "Completed transfer retained a duplicate source");
            }
            for (int i = 0; i < 2; i++) check(source[i].pops == EPISODES && receiver[i].additions == EPISODES,
                "Lost or duplicate transfer at " + prefix + i);
            check(advanced.size() == 2 * EPISODES, "Driver/link transfer identity mismatch");
        }
    }

    private static void signalNoneCharacterization() throws Exception {
        for (boolean strict : new boolean[]{false,true}) {
            var fixture = new Fixture(strict ? "S_" : "L_",List.of(),strict);
            fixture.owner.bind();
            for (int i = 0; i < 2; i++) {
                fixture.source[i].head = fixture.vehicle(i,0);
                fixture.receiver[i].load = 0;
            }
            check(fixture.attempt(0,100), "First green movement failed with an accepting receiver");
            boolean second = fixture.attempt(1,100);
            check(second == !strict, "Signal NONE legacy/strict incompatibility characterization changed");
            if (strict) {
                check(fixture.source[1].pops == 0 && fixture.receiver[1].additions == 0 && fixture.source[1].head != null,
                    "Strict conflict lost or transferred the waiting vehicle");
                check(fixture.attempt(1,101), "Strict conflict did not release in the following step");
            }
            check(fixture.source[0].pops == 1 && fixture.source[1].pops == 1 &&
                fixture.receiver[0].additions == 1 && fixture.receiver[1].additions == 1 && fixture.advanced.size() == 2,
                "Signal NONE comparison lost or duplicated a transfer");
        }
        System.out.println("PASS signal NONE characterization: legacy admits both incompatible green movements in one step; strict waits until the next step; no QSim run");
    }

    private static int read(BlockingQueue<Snapshot> events, CountDownLatch actorsDone) throws Exception {
        return read(events, actorsDone, Set.of("A_", "B_"));
    }

    private static int read(BlockingQueue<Snapshot> events, CountDownLatch actorsDone, Set<String> prefixes) throws Exception {
        var entered = new HashSet<String>(); var left = new HashSet<String>(); var receipts = new HashSet<String>();
        var decisions = new HashMap<String,Integer>();
        while (actorsDone.getCount() > 0 || !events.isEmpty()) {
            Snapshot event = events.poll(1,TimeUnit.SECONDS);
            if (event == null) continue;
            String vehicle = event.attributes.get("vehicle");
            check(vehicle != null && prefixes.stream().anyMatch(vehicle::startsWith), "Cross-node identity corruption");
            if (event.type.equals("left link")) check(left.add(vehicle), "Duplicate LinkLeave: " + vehicle);
            if (event.type.equals("entered link")) {
                check(left.contains(vehicle), "LinkEnter preceded LinkLeave: " + vehicle);
                check(entered.add(vehicle), "Duplicate LinkEnter: " + vehicle);
            }
            if (event.type.equals("simz1Admission")) {
                check(entered.contains(vehicle), "Admission receipt preceded LinkEnter: " + vehicle);
                check(receipts.add(vehicle), "Duplicate admission receipt: " + vehicle);
                check("true".equals(event.attributes.get("receiverAcceptedAtDecision")), "Receipt lacks receiver acceptance");
                check(event.attributes.get("node").startsWith(vehicle.substring(0,2)), "Cross-node receipt corruption");
            }
            if (event.type.equals(Zona1NativeDiagnostics.EVENT_TYPE)) {
                check(!Set.of("FORCE","ABORT").contains(event.attributes.get("decision")), "Strict blocked receiver forced/aborted");
                check(SimZ1AdmissionConfigGroup.STRICT.equals(event.attributes.get("admissionPolicy")), "Wrong policy provenance");
                decisions.merge(event.attributes.get("reason"),1,Integer::sum);
                String person = event.attributes.get("person");
                check(person.equals(vehicle.replace("_v","_p")), "Vehicle/person mismatch");
            }
        }
        check(entered.size() == 2 * prefixes.size() * EPISODES && entered.equals(left) && entered.equals(receipts),
            "Event transfers and receipts did not conserve identities");
        check(decisions.getOrDefault("admission_conflict_executed",0) == prefixes.size() * EPISODES, "Missing executed-conflict WAIT evidence");
        return entered.size();
    }

    private static void fourNodeOwners() throws Exception {
        // Four concurrent native-node branch callers; the event observer reads
        // immutable receipts afterward. This still does not run QSim's scheduler.
        var events = new ArrayBlockingQueue<Snapshot>(8192);
        var fixtures = new ArrayList<Fixture>();
        for (String prefix : List.of("C_", "D_", "E_", "F_")) fixtures.add(new Fixture(prefix, List.of(events)));
        var phase = new CyclicBarrier(4);
        var done = new CountDownLatch(4);
        var workers = Executors.newFixedThreadPool(4);
        try {
            var futures = new ArrayList<Future<?>>();
            for (var fixture : fixtures) futures.add(workers.submit(() -> {
                try { fixture.run(phase); return null; } finally { done.countDown(); }
            }));
            for (var future : futures) future.get(30, TimeUnit.SECONDS);
            check(read(events, done, Set.of("C_", "D_", "E_", "F_")) == 400, "Four-owner receipts missing");
            System.out.println("PASS SimZ1 strict admission: four concurrent node owners, 400 unique transfers, " +
                "full receiver remains WAIT beyond 10 seconds, no force/abort/duplicate; no QSim scheduler run");
        } finally {
            workers.shutdownNow(); check(workers.awaitTermination(10, TimeUnit.SECONDS), "Four owners did not stop");
        }
    }

    public static void main(String[] args) throws Exception {
        signalNoneCharacterization();
        fourNodeOwners();
        var readers = List.<BlockingQueue<Snapshot>>of(new ArrayBlockingQueue<>(4096),new ArrayBlockingQueue<>(4096));
        var first = new Fixture("A_",readers); var second = new Fixture("B_",readers);
        var start = new CyclicBarrier(4); var phase = new CyclicBarrier(2);
        var actorsDone = new CountDownLatch(2);
        var executor = Executors.newFixedThreadPool(4);
        try {
            var tasks = new ArrayList<Future<?>>();
            for (Fixture fixture : List.of(first,second)) tasks.add(executor.submit(() -> {
                try { start.await(10,TimeUnit.SECONDS); fixture.run(phase); return null; }
                finally { actorsDone.countDown(); }
            }));
            for (var reader : readers) tasks.add(executor.submit(() -> { start.await(10,TimeUnit.SECONDS); return read(reader,actorsDone); }));
            for (var task : tasks) task.get(30,TimeUnit.SECONDS);
            boolean rejected = false;
            try { first.receiver[0].lane.getId(); } catch (AssertionError expected) { rejected = true; }
            check(rejected,"Fixture ownership negative control did not reject a foreign actor");
            System.out.println("PASS SimZ1 strict admission: 2 node owners + 2 event readers; 200 unique transfers, no force, abort, duplicate or cross-node conflict; no QSim run");
        } finally {
            executor.shutdownNow();
            check(executor.awaitTermination(10,TimeUnit.SECONDS),"Fixture workers did not terminate");
            org.apache.logging.log4j.LogManager.shutdown();
        }
    }
}
