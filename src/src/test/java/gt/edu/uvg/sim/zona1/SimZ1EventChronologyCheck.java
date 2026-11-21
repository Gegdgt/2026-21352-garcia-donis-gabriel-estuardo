package gt.edu.uvg.sim.zona1;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.scenario.ScenarioUtils;

/** Event/lifecycle fixtures only. Never runs QSim, a controller or a simulation.
 * Four producers represent one native step; the real MATSim 15 event manager
 * delivers their events to handlers on one or two asynchronous worker threads.
 */
public final class SimZ1EventChronologyCheck {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void await(CountDownLatch latch) {
        try { check(latch.await(5, TimeUnit.SECONDS), "Event fixture timed out"); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new AssertionError(e); }
    }

    private static void bounded(Callable<Void> task) throws Exception {
        var executor = Executors.newSingleThreadExecutor(r -> {
            var thread = new Thread(r, "SimZ1-chronology-fixture"); thread.setDaemon(true); return thread;
        });
        try { executor.submit(task).get(15, TimeUnit.SECONDS); }
        finally { executor.shutdownNow(); }
    }

    // Test-only construction of the native clock/EventsManager holder. No engines,
    // agents, injector, preparation, doSimStep or QSim.run are invoked.
    private static QSim clockHolder(Scenario scenario, EventsManager manager) throws Exception {
        var constructor = QSim.class.getDeclaredConstructor(Scenario.class, EventsManager.class, com.google.inject.Injector.class);
        constructor.setAccessible(true);
        return constructor.newInstance(scenario, manager, null);
    }

    private static Event decision(double time, int index) {
        return new Event(time) {
            @Override public String getEventType() { return "simz1NativeDecision"; }
            @Override public Map<String,String> getAttributes() {
                var data = super.getAttributes();
                data.put("vehicle", "v" + index); data.put("person", "p" + index);
                data.put("reason", index==0 ? "storage_forced_move" : index==1 ? "storage_stuck_removal" : "storage_wait");
                return data;
            }
        };
    }

    private static long counter(SimZ1Diagnostics monitor, String field) throws Exception {
        var member = SimZ1Diagnostics.class.getDeclaredField(field); member.setAccessible(true);
        return ((AtomicLong)member.get(monitor)).get();
    }

    private static void cleanupAfterParallelStep(int eventThreads, boolean completed, boolean backlog) throws Exception {
        var config = ConfigUtils.createConfig();
        config.qsim().setNumberOfThreads(4);
        config.parallelEventHandling().setNumberOfThreads(eventThreads);
        config.parallelEventHandling().setSynchronizeOnSimSteps(true);
        ConfigUtils.addOrGetModule(config, Zona1DiagnosticsConfigGroup.class).setWatchdogSeconds(3600);
        var scenario = ScenarioUtils.createScenario(config);
        var manager = EventsUtils.createEventsManager(config);
        check(manager.getClass().getSimpleName().equals("SimStepParallelEventsManagerImpl"), "Wrong native event manager");
        var qsim = clockHolder(scenario, manager);
        var monitor = new SimZ1Diagnostics(scenario);
        var first = new ArrayList<Event>(); var second = new ArrayList<Event>();
        var enteredHandler = new CountDownLatch(1); var releaseHandler = new CountDownLatch(backlog ? 1 : 0);
        var delivered = new CountDownLatch(8);
        manager.addHandler((BasicEventHandler) event -> {
            if (event.getTime()==25480 && event instanceof LinkLeaveEvent) {
                enteredHandler.countDown(); await(releaseHandler);
            }
            first.add(event);
        });
        manager.addHandler((BasicEventHandler) event -> {
            monitor.handleEvent(event);
            if (event instanceof PersonArrivalEvent) delivered.countDown();
        });
        manager.addHandler((BasicEventHandler) event -> {
            second.add(event);
            if (event instanceof PersonArrivalEvent) delivered.countDown();
        });
        manager.initProcessing();
        qsim.getSimTimer().setTime(25440);
        monitor.notifyMobsimInitialized(new MobsimInitializedEvent<>(qsim));
        var producers = Executors.newFixedThreadPool(4);
        try {
            // Match QSim's actual callback order: event barrier, then after-step listeners.
            manager.afterSimStep(25440);
            monitor.notifyMobsimAfterSimStep(new MobsimAfterSimStepEvent<>(qsim, 25440));
            qsim.getSimTimer().setTime(25479);
            for (int i=0; i<4; i++) {
                manager.processEvent(new PersonDepartureEvent(25479, Id.createPersonId("p"+i), Id.createLinkId("in"), "car", "car"));
                manager.processEvent(new VehicleEntersTrafficEvent(25479, Id.createPersonId("p"+i), Id.createLinkId("in"), Id.createVehicleId("v"+i), "car", 0));
            }
            manager.afterSimStep(25479);
            monitor.notifyMobsimAfterSimStep(new MobsimAfterSimStepEvent<>(qsim, 25479));
            qsim.getSimTimer().setTime(25480);
            var ready = new CountDownLatch(4); var start = new CountDownLatch(1); var tasks = new ArrayList<Future<?>>();
            for (int i=0; i<4; i++) {
                final int index=i;
                tasks.add(producers.submit(() -> {
                    ready.countDown(); await(start);
                    var vehicle=Id.createVehicleId("v"+index); var person=Id.createPersonId("p"+index);
                    manager.processEvent(new LinkLeaveEvent(25480, vehicle, Id.createLinkId("in")));
                    manager.processEvent(new LinkEnterEvent(25480, vehicle, Id.createLinkId("out")));
                    manager.processEvent(decision(25480, index));
                    manager.processEvent(new VehicleLeavesTrafficEvent(25480, person, Id.createLinkId("out"), vehicle, "car", 1));
                    manager.processEvent(new PersonArrivalEvent(25480, person, Id.createLinkId("out"), "car"));
                }));
            }
            await(ready); start.countDown();
            for (var task : tasks) task.get(5, TimeUnit.SECONDS);
            if (backlog) await(enteredHandler); else await(delivered);
            if (completed) {
                manager.afterSimStep(25480);
                monitor.notifyMobsimAfterSimStep(new MobsimAfterSimStepEvent<>(qsim, 25480));
            }
            // A failed native step skips afterSimStep/after-step listeners. QSim
            // still invokes BeforeCleanup with its clock at the attempted step.
            monitor.notifyMobsimBeforeCleanup(new MobsimBeforeCleanupEvent<>(qsim));
            monitor.notifyMobsimBeforeCleanup(new MobsimBeforeCleanupEvent<>(qsim));
            check(qsim.getSimTimer().getTimeOfDay()==25480, "Diagnostic changed the native clock");
            releaseHandler.countDown();
            manager.finishProcessing();

            check(first.size()==30, "Lost/duplicated events: " + first.size());
            check(first.stream().map(Event::getAttributes).toList().equals(second.stream().map(Event::getAttributes).toList()),
                "Async handlers saw different identity/order");
            double previous=0;
            for (var event : first) {
                check(event.getTime()>=previous, "Backdated event " + event.getAttributes()); previous=event.getTime();
            }
            for (int i=0; i<4; i++) {
                String vehicle="v"+i, person="p"+i;
                var own=first.stream().filter(e -> vehicle.equals(e.getAttributes().get("vehicle"))).toList();
                check(own.stream().map(Event::getEventType).toList().equals(List.of("vehicle enters traffic", "left link", "entered link", "simz1NativeDecision", "vehicle leaves traffic")),
                    "Per-vehicle FIFO changed for " + vehicle);
                for (var event : own) if (event.getAttributes().containsKey("person"))
                    check(person.equals(event.getAttributes().get("person")), "Wrong person for " + vehicle);
            }
            check(counter(monitor,"links")==4 && counter(monitor,"arrivals")==4 && counter(monitor,"active")==0,
                "Monitor lost final events/counters");
            var member=SimZ1Diagnostics.class.getDeclaredField("decisions"); member.setAccessible(true);
            var decisions=(Map<?,?>)member.get(monitor);
            check(((AtomicLong)decisions.get("storage_forced_move")).get()==1 &&
                ((AtomicLong)decisions.get("storage_stuck_removal")).get()==1 &&
                ((AtomicLong)decisions.get("storage_wait")).get()==2, "Backlog lost intervention counters");
            var progress=first.stream().filter(e -> e.getEventType().equals("simz1Progress")).toList();
            check(progress.size()==2 && progress.get(progress.size() - 1).getTime()==25480, "Cleanup must use native clock, not last completed step");
            var data=progress.get(progress.size() - 1).getAttributes();
            check(data.get("lastCompletedStepTime").equals(completed ? "25480.0" : "25479.0"), "Completion time lost");
            check(data.get("observationPhase").equals("before_cleanup"), "Cleanup snapshot mislabeled");
            check(data.get("stepCount").equals(completed ? "3" : "2"), "Invented a completed step");
            check(data.get("elapsedSimSeconds").equals("40.0"), "Wrong observation interval");
            if (!backlog) {
                for (String field : List.of("arrivals","linkTransitions")) check(data.get(field).equals("4"), "Wrong " + field);
                check(data.get("forcedMoves").equals("1") && data.get("storageStuckRemovals").equals("1") && data.get("waitStorage").equals("2"),
                    "Lost WAIT/FORCE/removal counters");
            }
        } finally {
            releaseHandler.countDown(); producers.shutdownNow();
            // Close only the observer's watchdog even if the expected old-code failure occurred.
            var close=SimZ1Diagnostics.class.getDeclaredMethod("close"); close.setAccessible(true); close.invoke(monitor);
        }
    }

    private static void genuineBackwardsEventIsRejected() {
        var config=ConfigUtils.createConfig();
        config.parallelEventHandling().setNumberOfThreads(1);
        var manager=EventsUtils.createEventsManager(config);
        manager.initProcessing(); manager.processEvent(decision(10,0)); manager.afterSimStep(10);
        manager.processEvent(decision(9,0));
        try {
            manager.finishProcessing(); throw new AssertionError("Real temporal disorder was hidden");
        } catch (RuntimeException expected) {
            Throwable cause=expected;
            while (cause.getCause()!=null) cause=cause.getCause();
            check(cause.getMessage().contains("not ordered chronologically"), "Unexpected event manager failure");
        }
    }

    public static void main(String[] args) throws Exception {
        try {
            for (int threads : new int[]{1,2}) {
                bounded(() -> { cleanupAfterParallelStep(threads,false,false); return null; });
                bounded(() -> { cleanupAfterParallelStep(threads,false,true); return null; });
                bounded(() -> { cleanupAfterParallelStep(threads,true,false); return null; });
            }
            bounded(() -> { genuineBackwardsEventIsRejected(); return null; });
            System.out.println("PASS: four concurrent producers; one/two event workers; same-second FIFO/IDs/counters; completed/interrupted cleanup; delayed handlers; genuine backwards event rejected; no QSim run");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
