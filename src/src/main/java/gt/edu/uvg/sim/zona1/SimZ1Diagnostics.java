package gt.edu.uvg.sim.zona1;

import java.lang.management.ManagementFactory;
import java.lang.management.ThreadInfo;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.*;
import org.matsim.core.controler.listener.ShutdownListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;

/** Observe only: no thresholds, signals, vehicles or routes are modified. */
public final class SimZ1Diagnostics implements BasicEventHandler, MobsimInitializedListener,
        MobsimAfterSimStepListener, MobsimBeforeCleanupListener {
    private static final org.apache.logging.log4j.Logger LOG=org.apache.logging.log4j.LogManager.getLogger(SimZ1Diagnostics.class);
    private final Scenario scenario;
    private final AtomicLong links=new AtomicLong(), arrivals=new AtomicLong(), active=new AtomicLong(), routing=new AtomicLong();
    private final Map<String,AtomicLong> decisions=new ConcurrentHashMap<>();
    private final Object waitLock=new Object();
    private final Map<String,Long> waitAttempts=new TreeMap<>();
    private final Map<String,Set<String>> waitingVehicles=new TreeMap<>();
    private final Map<String,Double> maximumWaitAge=new TreeMap<>();
    private static final String REGISTRY=SimZ1Diagnostics.class.getName();
    record Work(long threadId,String threadName,String callback,String phase,int iteration,double simulatedTime,
                long startedNanos,long phaseStartedNanos,boolean active) { }
    private volatile Work work;
    private volatile long callbackThreadId=-1;
    private long lastStackWall, suppressedStackSamples;
    private String lastStackSignature;
    private static final long STACK_INTERVAL_NANOS=60_000_000_000L, IDENTICAL_STACK_INTERVAL_NANOS=300_000_000_000L;
    static void work(Scenario scenario,String callback,String phase,int iteration,double time,long start,boolean active) {
        var value=scenario.getScenarioElement(REGISTRY);
        if(value instanceof SimZ1Diagnostics monitor) {
            Thread thread=Thread.currentThread();monitor.callbackThreadId=thread.getId();
            monitor.work=new Work(thread.getId(),thread.getName(),callback,phase,iteration,time,start,System.nanoTime(),active);
        }
    }
    private QSim qsim;
    private ScheduledExecutorService watchdog;
    private long watchdogGeneration;
    private volatile long lastStepWall, latestCpu, latestWatchdogWall;
    private volatile double simulatedTime;
    private volatile int deadlockedThreads;
    private int iteration, stepCount, interval;
    private double next, previousTime;
    private long previousWall, previousCpu, previousLinks, previousArrivals, previousRouting;
    private final Map<String,Long> previousDecisions=new HashMap<>();
    public SimZ1Diagnostics(Scenario scenario) { this.scenario=scenario; }
    public static SimZ1Diagnostics install(Controler controler) {
        var monitor=new SimZ1Diagnostics(controler.getScenario());
        controler.getScenario().addScenarioElement(REGISTRY,monitor);
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addMobsimListenerBinding().toInstance(monitor); addEventHandlerBinding().toInstance(monitor);
            }
        });
        controler.addControlerListener((ShutdownListener)e->monitor.close());
        return monitor;
    }
    @Override public void reset(int iteration) {
        this.iteration=iteration; links.set(0); arrivals.set(0); active.set(0); routing.set(0); decisions.clear();
        synchronized(waitLock){waitAttempts.clear();waitingVehicles.clear();maximumWaitAge.clear();}
        work=null;callbackThreadId=-1;lastStackWall=0;suppressedStackSamples=0;lastStackSignature=null;
    }
    @Override public void handleEvent(Event event) {
        if (event instanceof LinkEnterEvent) links.incrementAndGet();
        else if (event instanceof PersonArrivalEvent) arrivals.incrementAndGet();
        else if (event instanceof VehicleEntersTrafficEvent) active.incrementAndGet();
        else if (event instanceof VehicleLeavesTrafficEvent) active.decrementAndGet();
        else if (event.getEventType().equals("zona1RerouteStep")) routing.addAndGet(Long.parseLong(event.getAttributes().get("calculations")));
        else if (event.getEventType().equals("simz1NativeDecision")) {
            var a=event.getAttributes();
            decisions.computeIfAbsent(a.get("reason"),key->new AtomicLong()).incrementAndGet();
            if("WAIT".equals(a.get("decision"))) {
                String category=org.matsim.core.mobsim.qsim.qnetsimengine.Zona1NativeDiagnostics.category(a.get("reason"));
                synchronized(waitLock) {
                    waitAttempts.merge(category,1L,Long::sum);
                    if(a.get("vehicle")!=null)waitingVehicles.computeIfAbsent(category,k->new HashSet<>()).add(a.get("vehicle"));
                    String age=a.get("waitSeconds");
                    if(age!=null) {double seconds=Double.parseDouble(age);if(Double.isFinite(seconds)&&seconds>=0)maximumWaitAge.merge(category,seconds,Math::max);}
                }
            }
        }
    }
    private static long cpu() {
        var bean=ManagementFactory.getOperatingSystemMXBean();
        return bean instanceof com.sun.management.OperatingSystemMXBean os?os.getProcessCpuTime():-1;
    }
    /** A stall is not proof of deadlock. Only the JVM's detected lock cycle earns that name. */
    static String classifyProgress(long[] detectedDeadlocks,double idleWallSeconds,long cpuDelta,long linkDelta,long waits) {
        if (detectedDeadlocks!=null && detectedDeadlocks.length>0) return "thread_deadlock_detected";
        if (idleWallSeconds>=10) return cpuDelta>0?"no_simulated_progress_cpu_active":"no_simulated_progress_low_cpu";
        if (linkDelta==0 && waits>0) return "traffic_wait_observed";
        return "progress_observed";
    }
    @Override public synchronized void notifyMobsimInitialized(MobsimInitializedEvent event) {
        close(); qsim=(QSim)event.getQueueSimulation();
        callbackThreadId=Thread.currentThread().getId();
        var settings=ConfigUtils.addOrGetModule(scenario.getConfig(),Zona1DiagnosticsConfigGroup.class);
        interval=settings.getProgressIntervalSeconds(); stepCount=0; previousDecisions.clear();
        previousLinks=previousArrivals=previousRouting=0;
        simulatedTime=qsim.getSimTimer().getTimeOfDay(); previousTime=simulatedTime; next=simulatedTime;
        lastStepWall=previousWall=latestWatchdogWall=System.nanoTime(); previousCpu=latestCpu=cpu(); deadlockedThreads=0;
        watchdog=Executors.newSingleThreadScheduledExecutor(task->{
            Thread thread=new Thread(task,"SimZ1-progress-watchdog"); thread.setDaemon(true); return thread;
        });
        long generation=watchdogGeneration;
        watchdog.scheduleAtFixedRate(()->watch(generation),settings.getWatchdogSeconds(),settings.getWatchdogSeconds(),TimeUnit.SECONDS);
        LOG.info("SIMZ1_CONFIG iteration={} signals={} lanes={} threads={} stuckTime={} removeStuckVehicles={} linkToLinkRouting={} linkToLinkTimes={} admissionPolicy={} microscopicLaneAdapterInstalled=false",
            iteration,ConfigUtils.addOrGetModule(scenario.getConfig(),org.matsim.contrib.signals.SignalSystemsConfigGroup.class).isUseSignalSystems(),
            scenario.getConfig().qsim().isUseLanes(),scenario.getConfig().qsim().getNumberOfThreads(),
            scenario.getConfig().qsim().getStuckTime(),scenario.getConfig().qsim().isRemoveStuckVehicles(),
            scenario.getConfig().controler().isLinkToLinkRoutingEnabled(),scenario.getConfig().travelTimeCalculator().isCalculateLinkToLinkTravelTimes(),
            ConfigUtils.addOrGetModule(scenario.getConfig(),SimZ1AdmissionConfigGroup.class).getStoragePolicy());
    }
    private synchronized void watch(long generation) {
        if (generation!=watchdogGeneration) return; // A canceled task must not observe the next iteration.
        try {
            long now=System.nanoTime(), currentCpu=cpu();
            var bean=ManagementFactory.getThreadMXBean();
            long[] deadlocks=bean.findDeadlockedThreads(); deadlockedThreads=deadlocks==null?0:deadlocks.length;
            double idle=(now-lastStepWall)/1e9;
            String classification=classifyProgress(deadlocks,idle,currentCpu-latestCpu,1,0);
            LOG.info("SIMZ1_WATCHDOG iteration={} simulatedTime={} idleWallSeconds={} processCpuDeltaNanos={} wallDeltaNanos={} classification={} deadlockedThreads={}",
                iteration,simulatedTime,idle,currentCpu<0?-1:currentCpu-latestCpu,now-latestWatchdogWall,classification,deadlockedThreads);
            Work activeWork=work;
            if(activeWork!=null)LOG.info("SIMZ1_ACTIVE_WORK threadId={} threadName={} callback={} phase={} iteration={} simulatedTime={} active={} workElapsedNanos={} phaseElapsedNanos={} threadCpuNanos={}",
                activeWork.threadId(),activeWork.threadName(),activeWork.callback(),activeWork.phase(),activeWork.iteration(),activeWork.simulatedTime(),activeWork.active(),
                now-activeWork.startedNanos(),now-activeWork.phaseStartedNanos(),bean.isThreadCpuTimeSupported()?bean.getThreadCpuTime(activeWork.threadId()):-1);
            if ((deadlockedThreads>0||idle>=10) && now-lastStackWall>=STACK_INTERVAL_NANOS) {
                var ids=new LinkedHashSet<Long>();
                if(callbackThreadId>0)ids.add(callbackThreadId);
                if(activeWork!=null&&activeWork.active())ids.add(activeWork.threadId());
                if(deadlocks!=null)for(long id:deadlocks)ids.add(id);
                var samples=new ArrayList<String>();
                for(long id:ids) {
                    ThreadInfo info=bean.getThreadInfo(id,Integer.MAX_VALUE);
                    samples.add(formatThread(info,id,bean.isThreadCpuTimeSupported()?bean.getThreadCpuTime(id):-1));
                }
                String signature=String.join("\n",samples).replaceAll("cpuNanos=-?[0-9]+","cpuNanos=<sample>");
                if(signature.equals(lastStackSignature)&&now-lastStackWall<IDENTICAL_STACK_INTERVAL_NANOS)suppressedStackSamples++;
                else {
                    LOG.info("SIMZ1_STACK_SAMPLE target=callback_identity suppressedIdenticalSamples={} stackCount={}",suppressedStackSamples,samples.size());
                    for(String sample:samples)LOG.info("SIMZ1_STALL_STACK {}",sample);
                    lastStackWall=now;lastStackSignature=signature;suppressedStackSamples=0;
                }
            }
            latestCpu=currentCpu; latestWatchdogWall=now;
        } catch (RuntimeException error) { LOG.error("SIMZ1_WATCHDOG_ERROR",error); }
    }
    /** ThreadInfo.toString() truncates to eight frames in JDK17. Enumerate the
     * exact returned array; no name filter can exclude a callback named main. */
    static String formatThread(ThreadInfo info,long requestedId,long cpuNanos) {
        if(info==null)return "requestedThreadId="+requestedId+" unavailable=true stackTruncated=unknown";
        var stack=info.getStackTrace();var text=new StringBuilder("threadId=").append(info.getThreadId())
            .append(" name=").append(info.getThreadName()).append(" state=").append(info.getThreadState())
            .append(" cpuNanos=").append(cpuNanos).append(" lockOwnerId=").append(info.getLockOwnerId())
            .append(" frameCount=").append(stack.length).append(" stackTruncated=false");
        for(int i=0;i<stack.length;i++)text.append("\n  frame[").append(i).append("]=").append(stack[i]);
        return text.toString();
    }
    @Override public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent event) {
        callbackThreadId=Thread.currentThread().getId();
        simulatedTime=event.getSimulationTime(); lastStepWall=System.nanoTime(); stepCount++;
        if (simulatedTime<next) return;
        report(simulatedTime,"after_step"); next=simulatedTime+interval;
    }
    private long delta(String reason) {
        long count=decisions.getOrDefault(reason,new AtomicLong()).get();
        long before=previousDecisions.getOrDefault(reason,0L); previousDecisions.put(reason,count); return count-before;
    }
    private void report(double now,String phase) {
        long wall=System.nanoTime(), currentCpu=cpu(), currentLinks=links.get(), currentArrivals=arrivals.get(), currentRouting=routing.get();
        var data=new TreeMap<String,String>();
        long signal=delta("signal_red")+delta("signal_yellow")+delta("signal_redyellow")+delta("signal_not_green")+
            delta("signal_queue_not_green");
        long storage=delta("storage_wait")+delta("receiver_native_storage")+delta("receiver_storage_or_terminal_slot")+
            delta("passage_receipt_storage_or_slot")+delta("passage_receipt_native_queue")+delta("passage_native_storage")+
            delta("passage_receipt_locked")+delta("passage_previous_not_cleared"), priority=delta("priority_stop")+delta("priority_yield")+
            delta("priority_yield_conflict")+delta("priority_conflict_executed")+delta("priority_fairness")+
            delta("intersection_conflict")+delta("admission_conflict_executed");
        long congestion=delta("congestion_queue"), restrictions=delta("turn_restriction");
        data.put("iteration",""+iteration); data.put("elapsedSimSeconds",""+(now-previousTime)); data.put("stepCount",""+stepCount);
        data.put("observationPhase",phase);
        data.put("lastCompletedStepTime",stepCount==0?"unknown":Double.toString(simulatedTime));
        data.put("processCpuNanos",""+(currentCpu<0||previousCpu<0?-1:currentCpu-previousCpu)); data.put("wallNanos",""+(wall-previousWall));
        data.put("linkTransitions",""+(currentLinks-previousLinks)); data.put("arrivals",""+(currentArrivals-previousArrivals));
        data.put("activeVehicles",""+active.get()); data.put("rerouteCalculations",""+(currentRouting-previousRouting));
        data.put("waitSignal",""+signal); data.put("waitStorage",""+storage); data.put("waitPriority",""+priority);
        data.put("waitCongestion",""+congestion); data.put("turnRestrictions",""+restrictions);
        data.put("forcedMoves",""+delta("storage_forced_move")); data.put("threadDeadlocks",""+deadlockedThreads);
        data.put("storageStuckRemovals",""+delta("storage_stuck_removal"));
        synchronized(waitLock) {
            data.put("waitAttemptsUnit","native_decision_events_in_interval");
            data.put("waitAttempts",""+waitAttempts.values().stream().mapToLong(Long::longValue).sum());
            data.put("waitUnknown",""+waitAttempts.getOrDefault("unknown",0L));
            data.put("waitAttemptsByCategory",waitAttempts.toString());
            var distinct=new TreeMap<String,Integer>();var all=new HashSet<String>();
            waitingVehicles.forEach((category,ids)->{distinct.put(category,ids.size());all.addAll(ids);});
            data.put("waitingDistinctVehicles",""+all.size());data.put("waitingDistinctVehiclesByCategory",distinct.toString());
            data.put("maximumObservedWaitAgeSecondsByCategory",maximumWaitAge.toString());
            data.put("waitDurationBasis","maximum_native_head_age_gauge_not_summed_attempts_or_reason_duration");
            waitAttempts.clear();waitingVehicles.clear();maximumWaitAge.clear();
        }
        data.put("classification",classifyProgress(deadlockedThreads>0?new long[]{1}:null,0,currentCpu-previousCpu,currentLinks-previousLinks,signal+storage+priority+congestion));
        qsim.getEventsManager().processEvent(new Event(now) {
            @Override public String getEventType() { return "simz1Progress"; }
            @Override public Map<String,String> getAttributes() { var attributes=super.getAttributes(); attributes.putAll(data); return attributes; }
        });
        LOG.info("SIMZ1_PROGRESS simulatedTime={} {}",now,data);
        previousTime=now; previousWall=wall; previousCpu=currentCpu; previousLinks=currentLinks; previousArrivals=currentArrivals; previousRouting=currentRouting;
    }
    @Override public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        if (qsim!=null) {
            // A failed step can already have emitted events before its after-step
            // callback. Timestamp this observation with QSim's current clock, as
            // native cleanup does; never backdate it to the last completed step.
            // Counters are observations so far, not a drained/final event total.
            double now=qsim.getSimTimer().getTimeOfDay();
            if (now>previousTime) report(now,"before_cleanup");
        }
        close();
    }
    private synchronized void close() {
        watchdogGeneration++;
        if (watchdog!=null) { watchdog.shutdownNow(); watchdog=null; }
    }
}
