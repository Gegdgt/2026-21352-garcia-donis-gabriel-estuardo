package gt.edu.uvg.sim.zona1;

import java.lang.management.ManagementFactory;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.matsim.api.core.v01.events.Event;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.mobsim.qsim.qnetsimengine.Zona1NativeDiagnostics;

/** Inert threads and diagnostic events only. No QSim or demand generation. */
public final class SimZ1DiagnosticsPhaseCheck {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static Object field(Object target,String name)throws Exception {var f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void deep(int depth,CountDownLatch ready,CountDownLatch release)throws InterruptedException {
        if(depth==0){ready.countDown();release.await();}else deep(depth-1,ready,release);
    }
    private static Event event(String type,String reason,String decision,String vehicle,double age) {
        return new Event(120){@Override public String getEventType(){return type;}
            @Override public Map<String,String> getAttributes(){var a=super.getAttributes();a.put("reason",reason);a.put("decision",decision);
                a.put("vehicle",vehicle);a.put("waitSeconds",Double.toString(age));return a;}};
    }
    public static void main(String[] args)throws Exception {
        try {
            var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var monitor=new SimZ1Diagnostics(scenario);
            scenario.addScenarioElement(SimZ1Diagnostics.class.getName(),monitor);
            var ready=new CountDownLatch(1);var release=new CountDownLatch(1);
            Thread callback=new Thread(()->{try {SimZ1Diagnostics.work(scenario,"fixture_callback","search",0,120,System.nanoTime(),true);deep(24,ready,release);}
                catch(InterruptedException e){Thread.currentThread().interrupt();}},"callback-without-name-heuristic");
            callback.start();check(ready.await(5,TimeUnit.SECONDS),"Callback did not reach inert deep stack");
            var bean=ManagementFactory.getThreadMXBean();String stack;
            try {
                var work=(SimZ1Diagnostics.Work)field(monitor,"work");
                check(work.threadId()==callback.getId()&&work.phase().equals("search"),"Callback identity/phase not retained");
                var info=bean.getThreadInfo(work.threadId(),Integer.MAX_VALUE);
                stack=SimZ1Diagnostics.formatThread(info,work.threadId(),bean.getThreadCpuTime(work.threadId()));
                check(info.getStackTrace().length>24&&stack.contains("frame[24]="),"Stack still abbreviated to eight frames");
                check(stack.contains("stackTruncated=false")&&stack.contains(callback.getName()),"Stack coverage/identity absent");
                check(!SimZ1Diagnostics.formatThread(null,-1,-1).contains("stackTruncated=false"),"Missing thread claimed full coverage");
            } finally {release.countDown();callback.join(5000);}
            check(!callback.isAlive(),"Inert callback did not close");
            monitor.handleEvent(event(Zona1NativeDiagnostics.EVENT_TYPE,"receiver_storage_or_terminal_slot","WAIT","v1",80));
            monitor.handleEvent(event(Zona1NativeDiagnostics.EVENT_TYPE,"receiver_storage_or_terminal_slot","WAIT","v1",81));
            monitor.handleEvent(event(Zona1NativeDiagnostics.EVENT_TYPE,"storage_wait","WAIT","v2",20));
            monitor.handleEvent(event(Zona1NativeDiagnostics.EVENT_TYPE,"new_unclassified_reason","WAIT","v1",7));
            monitor.handleEvent(event(Zona1NativeDiagnostics.EVENT_TYPE,"turn_go","GO","v1",8));
            monitor.handleEvent(event("simz1PriorityDecision","receiver_storage_or_terminal_slot","WAIT","v3",999));
            var attempts=(Map<?,?>)field(monitor,"waitAttempts");var vehicles=(Map<?,?>)field(monitor,"waitingVehicles");
            var ages=(Map<?,?>)field(monitor,"maximumWaitAge");
            check(attempts.equals(Map.of("insufficient_storage",3L,"unknown",1L)),"Different layers/GO double-counted as WAIT");
            check(((Set<?>)vehicles.get("insufficient_storage")).size()==2,"Attempts conflated with distinct vehicles");
            check(ages.get("insufficient_storage").equals(81.),"Wait age gauge summed repeated attempts");
            for(String reason:List.of("receiver_storage_or_terminal_slot","receiver_native_storage","passage_receipt_native_queue"))
                check(Zona1NativeDiagnostics.category(reason).equals("insufficient_storage"),"Unclassified physical receiver reason: "+reason);
            check(Zona1NativeDiagnostics.category("something_new").equals("unknown"),"Unknown reason silently accepted as none");
            check(Zona1NativeDiagnostics.category("priority_stop").equals("mandatory_stop")&&Zona1NativeDiagnostics.category("signal_red").equals("signal"),"Signal/stop conflated with receiver");
            check(SimZ1Diagnostics.classifyProgress(null,20,100,0,0).equals("no_simulated_progress_cpu_active"),"CPU classified as deadlock");
            check(SimZ1Diagnostics.classifyProgress(new long[]{1},20,0,0,0).equals("thread_deadlock_detected"),"Detected lock cycle not classified");
            var timer=new CongestionAwareRerouting.StepTiming(scenario,2,480);
            try(var outer=timer.enter("context_validation")) {
                try(var inner=timer.enter("search")){for(int i=0;i<20000;i++)Math.sqrt(i);}
            }
            var timing=timer.finish("completed");long sum=0;
            for(String phase:CongestionAwareRerouting.StepTiming.PHASES)sum+=Long.parseLong(timing.get(phase+"Nanos"));
            check(sum<=Long.parseLong(timing.get("wallNanos")),"Nested phase durations double counted");
            check(Long.parseLong(timing.get("searchNanos"))>0&&Long.parseLong(timing.get("searchFirstStartNanos"))>0,"Search begin/end costs missing");
            check(((SimZ1Diagnostics.Work)field(monitor,"work")).threadId()==Thread.currentThread().getId(),"Main/current callback omitted by name");
            monitor.reset(3);check(((Map<?,?>)field(monitor,"waitAttempts")).isEmpty()&&field(monitor,"work")==null,"Diagnostic state leaked into next iteration");
            Path output=Path.of(args[0]);Files.createDirectories(output);
            Files.writeString(output.resolve("callback-stack.txt"),stack);
            new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(output.resolve("diagnostics-check.json").toFile(),
                Map.of("checks",checks,"passed",true,"qsim_started",false,"timing",timing,"deep_stack_frames_exceed_24",true));
            System.out.println("DIAGNOSTICS PHASE PASS checks="+checks+"; inert threads/events, no QSim");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
