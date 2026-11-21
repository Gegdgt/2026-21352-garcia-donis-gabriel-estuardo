package gt.edu.uvg.sim.zona1;

import java.util.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import org.apache.commons.csv.CSVFormat;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;

/** Prepared lifecycle regressions: actual parallel manager, no production input. */
public final class SimZ1FreightClosureCheck {
    static void check(boolean condition, String message) {
        if(!condition)throw new AssertionError(message);
    }
    static void rejected(Runnable action) {
        try { action.run(); } catch(IllegalStateException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    static Scenario scenario(double departure, String policy) {
        var config=ConfigUtils.createConfig();
        config.parallelEventHandling().setNumberOfThreads(2);
        config.parallelEventHandling().setSynchronizeOnSimSteps(true);
        var scenario=ScenarioUtils.createScenario(config);
        var person=scenario.getPopulation().getFactory().createPerson(Id.createPersonId("h"));
        person.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
        person.getAttributes().putAttribute("simz1FreightDeparture",departure);
        person.getAttributes().putAttribute("simz1FreightRoute","a b c");
        person.getAttributes().putAttribute("simz1FreightResidencePolicy",policy);
        scenario.getPopulation().addPerson(person);
        return scenario;
    }
    static Event event(String kind, double time, String link) {
        return event("h",kind,time,link);
    }
    static Event event(String id, String kind, double time, String link) {
        return new Event(time) {
            @Override public String getEventType() { return kind; }
            @Override public Map<String,String> getAttributes() {
                var attrs=super.getAttributes(); attrs.put("person",id); attrs.put("vehicle",id);
                attrs.put("link",link); return attrs;
            }
        };
    }
    static void send(SimZ1Freight h,String kind,double time,String link) { h.handleEvent(event(kind,time,link)); }
    static SimZ1Freight begin(double departure, Double entry, String policy) {
        var h=new SimZ1Freight(scenario(departure,policy)); send(h,"departure",departure,"a");
        if(entry!=null)send(h,"vehicle enters traffic",entry,"a"); return h;
    }
    static void finish(SimZ1Freight h,double time) {
        send(h,"entered link",time,"b"); send(h,"entered link",time+1,"c");
        send(h,"vehicle leaves traffic",time+2,"c"); send(h,"arrival",time+3,"c");
    }
    private static void lifecycle() {
        var good=begin(34320,34320.,SimZ1Freight.OVERNIGHT_POLICY); finish(good,34400); good.requireApproved();
        var waiting=begin(34320,null,SimZ1Freight.OVERNIGHT_POLICY);
        send(waiting,"vehicle enters traffic",77400,"a"); finish(waiting,86400); waiting.requireApproved();
        var notInserted=begin(34320,null,SimZ1Freight.OVERNIGHT_POLICY);
        send(notInserted,"stuckAndAbort",86401,"a");
        check(notInserted.violations().isEmpty() && notInserted.activeCount()==0,"Insertion wait became residence");
        rejected(notInserted::requireApproved);
        for(String policy:List.of(SimZ1Freight.OVERNIGHT_POLICY,SimZ1Freight.LEGACY_RESIDENCE_POLICY)) {
            var night=begin(77400,77400.,policy); finish(night,86400);
            check(night.approved()==policy.equals(SimZ1Freight.OVERNIGHT_POLICY),"Historical window changed");
        }
        for(double[] window:new double[][]{{0,18000},{32400,57600},{75600,104400}}) {
            for(int offset:new int[]{-1,0}) {
                var h=begin(window[0],window[0],SimZ1Freight.OVERNIGHT_POLICY);
                send(h,"stuckAndAbort",window[1]+offset,"a");
                check(h.violations().size()==(offset==0?1:0),"Half-open boundary");
            }
        }
        var exited=begin(34320,34320.,SimZ1Freight.OVERNIGHT_POLICY);
        finish(exited,57597); // leaves 57599, arrival 57600: already outside traffic.
        exited.requireApproved();
        var retained=begin(34320,34320.,SimZ1Freight.OVERNIGHT_POLICY);
        send(retained,"left link",57600,"a"); finish(retained,77400);
        send(retained,"actstart",86401,"c");
        check(retained.violations().get("h").observed()==57600 && retained.activeCount()==0,"Arrival lost violation");
        rejected(retained::requireApproved);
        var abort=begin(34320,34320.,SimZ1Freight.OVERNIGHT_POLICY);
        send(abort,"stuckAndAbort",86401,"a"); send(abort,"vehicle aborts",86401,"a");
        check(abort.violations().size()==1 && abort.activeCount()==0,"Abort reconciliation");
        rejected(()->send(abort,"arrival",86401,"c"));
        rejected(()->send(abort,"vehicle aborts",86401,"a"));
        abort.reset(1); abort.reset(1);
        send(abort,"departure",34320,"a"); send(abort,"vehicle enters traffic",34320,"a");
        finish(abort,34400); abort.requireApproved();
        rejected(()->send(abort,"departure",34404,"a"));
        var structural=begin(34320,34320.,SimZ1Freight.OVERNIGHT_POLICY);
        rejected(()->send(structural,"entered link",34321,"c"));
        rejected(()->send(structural,"left link",Double.NaN,"a"));
    }
    private static void parallelCleanup() {
        var scenario=scenario(34320,SimZ1Freight.OVERNIGHT_POLICY);
        var handler=new SimZ1Freight(scenario);
        var manager=EventsUtils.createEventsManager(scenario.getConfig());
        check(manager.getClass().getSimpleName().equals("SimStepParallelEventsManagerImpl"),"Wrong manager");
        var downstream=new AtomicInteger();
        manager.addHandler(handler);
        manager.addHandler((BasicEventHandler)e->downstream.incrementAndGet());
        for(int iteration=0;iteration<2;iteration++) {
            handler.reset(iteration); handler.reset(iteration); downstream.set(0);
            manager.initProcessing();
            manager.processEvent(event("departure",34320,"a"));
            manager.processEvent(event("vehicle enters traffic",34320,"a")); manager.afterSimStep(34320);
            if(iteration==0) {
                // QSim's terminal events can follow the last step barrier.
                manager.processEvent(event("stuckAndAbort",86401,"a"));
                manager.processEvent(event("vehicle aborts",86401,"a"));
            } else {
                manager.processEvent(event("entered link",34400,"b")); manager.afterSimStep(34400);
                manager.processEvent(event("entered link",34401,"c")); manager.afterSimStep(34401);
                manager.processEvent(event("vehicle leaves traffic",34402,"c")); manager.afterSimStep(34402);
                manager.processEvent(event("arrival",34403,"c"));
            }
            manager.finishProcessing();
            check(downstream.get()==(iteration==0?4:6),"Worker lost events during cleanup");
            check(handler.activeCount()==0,"Stale active state");
            if(iteration==0)rejected(handler::requireApproved); else handler.requireApproved();
        }
    }
    private static void neverDepartedCleanup() throws Exception {
        var scenario=scenario(52.69614317752584,SimZ1Freight.OVERNIGHT_POLICY);
        var h=new SimZ1Freight(scenario);
        rejected(()->send(h,"stuckAndAbort",1,"a"));
        h.reset(0);
        // A text event with the marker's name is not lifecycle evidence.
        send(h,"simz1FreightCleanupStart",1,"a");
        rejected(()->send(h,"vehicle aborts",1,"a"));
        h.reset(0);
        var manager=EventsUtils.createEventsManager(); manager.addHandler(h);
        h.beforeCleanup(manager,1);
        send(h,"stuckAndAbort",1,"a"); send(h,"vehicle aborts",1,"a");
        check(h.activeCount()==0&&h.violations().isEmpty(),"Never started acquired road residence");
        rejected(h::requireApproved);
        // Exercise the actual failure-path reporting callback with services that
        // expose ONLY output paths. No controller or QSim is constructed.
        var outputConfig=ConfigUtils.createConfig();
        outputConfig.controler().setOutputDirectory(Files.createTempDirectory("freight-after-mobsim-").resolve("output").toString());
        var output=new org.matsim.core.controler.OutputDirectoryHierarchy(outputConfig);
        output.createIterationDirectory(0);
        var services=(org.matsim.core.controler.MatsimServices)java.lang.reflect.Proxy.newProxyInstance(
            SimZ1FreightClosureCheck.class.getClassLoader(),new Class<?>[]{org.matsim.core.controler.MatsimServices.class},
            (proxy,method,args)->{ if(method.getName().equals("getControlerIO"))return output; throw new AssertionError("Unexpected native call: "+method); });
        h.notifyAfterMobsim(new org.matsim.core.controler.events.AfterMobsimEvent(services,0,true));
        var persisted=Path.of(output.getIterationFilename(0,"simz1-freight-audit.csv"));
        check(Files.readString(persisted).contains("aborted_before_departure"),"Failed iteration lost incomplete report");
        rejected(h::requireApproved);
        System.out.println("FREIGHT_FAILED_ITERATION_REPORT="+persisted);
        rejected(()->send(h,"vehicle aborts",1,"a"));
        rejected(()->send(h,"stuckAndAbort",2,"a"));
        rejected(()->send(h,"arrival",3,"c"));
        rejected(()->send(h,"departure",52.69614317752584,"a"));
        Path report=Files.createTempFile("freight-unstarted-cleanup-", ".csv");
        try {
            h.writeReport(report);
            try(var reader=Files.newBufferedReader(report,StandardCharsets.UTF_8);
                var csv=CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {
                var row=csv.getRecords().get(0);
                check(row.get("trip_outcome").equals("aborted_before_departure"),"Cleanup became completion");
                check(row.get("schedule_compliance").equals("undetermined"),"Unstarted compliance invented");
                for(String key:List.of("departure","traffic_entry","traffic_exit","violation_observed"))
                    check(row.get(key).isEmpty(),"Fictitious "+key);
                check(row.get("terminal_time").equals("1.0")&&row.get("evidence").equals("qsim_cleanup_without_departure"),"Cleanup provenance missing");
                check(row.get("terminal_sources").equals("stuckAndAbort|vehicle aborts"),"Terminal pair lost");
            }
        } finally { Files.deleteIfExists(report); }
        h.reset(1); h.reset(1);
        rejected(()->send(h,"stuckAndAbort",1,"a")); // cleanup flag must not leak.
        h.reset(2); h.beforeCleanup(manager,1);
        rejected(()->send(h,"stuckAndAbort",Double.NaN,"a"));
        rejected(()->send(h,"stuckAndAbort",0,"a")); // before cleanup, despite no prior event.
        h.reset(3); h.beforeCleanup(manager,57600); // after planned time and inside a restricted window.
        send(h,"vehicle aborts",57600,"a"); send(h,"stuckAndAbort",57600,"a");
        check(h.violations().isEmpty(),"Planned departure was used as road residence");
        rejected(h::requireApproved);
        var waiting=begin(34320,null,SimZ1Freight.OVERNIGHT_POLICY);
        rejected(()->send(waiting,"left link",34321,"a"));
        rejected(()->send(waiting,"departure",34320,"a"));
        rejected(()->send(waiting,"vehicle enters traffic",34319,"a"));
        var identity=begin(34320,null,SimZ1Freight.OVERNIGHT_POLICY);
        identity.handleEvent(new Event(34321) {
            @Override public String getEventType() { return "unrelated"; }
        });
        rejected(()->identity.handleEvent(new Event(34321) {
            @Override public String getEventType() { return "vehicle enters traffic"; }
            @Override public Map<String,String> getAttributes() { return Map.of("person","h","vehicle","wrong","link","a"); }
        }));
    }
    private static void orderedUnstartedCleanup() throws Exception {
        // Real event manager and real freight handler; no QSim construction.
        var s=scenario(52.69614317752584,SimZ1Freight.OVERNIGHT_POLICY);
        var h=new SimZ1Freight(s); var manager=EventsUtils.createEventsManager(s.getConfig());
        manager.addHandler(h);
        var downstream=new AtomicInteger(); manager.addHandler((BasicEventHandler)e->downstream.incrementAndGet());
        for(int iteration=0;iteration<2;iteration++) {
            h.reset(iteration); downstream.set(0); manager.initProcessing();
            if(iteration==0) {
                h.beforeCleanup(manager,1);
                manager.processEvent(event("stuckAndAbort",1,"a"));
                manager.processEvent(event("vehicle aborts",1,"a"));
            } else {
                manager.processEvent(event("departure",52.69614317752584,"a"));
                manager.processEvent(event("vehicle enters traffic",53,"a"));
                manager.processEvent(event("entered link",54,"b"));
                manager.processEvent(event("entered link",55,"c"));
                manager.processEvent(event("vehicle leaves traffic",56,"c"));
                manager.processEvent(event("arrival",56,"c"));
                h.beforeCleanup(manager,57);
            }
            manager.finishProcessing();
            check(downstream.get()==(iteration==0?3:7),"Cleanup prevented downstream processing");
            if(iteration==0)rejected(h::requireApproved); else h.requireApproved();
        }
        var bad=new SimZ1Freight(s); var queued=EventsUtils.createEventsManager(s.getConfig());
        var entered=new CountDownLatch(1); var release=new CountDownLatch(1);
        queued.addHandler((BasicEventHandler)e->{
            if(e.getEventType().equals("stuckAndAbort")) {
                entered.countDown();
                try { if(!release.await(5,TimeUnit.SECONDS))throw new AssertionError("Gate timeout"); }
                catch(InterruptedException ex) { throw new RuntimeException(ex); }
            }
            bad.handleEvent(e);
        });
        queued.initProcessing(); queued.processEvent(event("stuckAndAbort",1,"a"));
        check(entered.await(5,TimeUnit.SECONDS),"Pending event not observed");
        bad.beforeCleanup(queued,1); release.countDown();
        try { queued.finishProcessing(); throw new AssertionError("Earlier abort excused by later callback"); }
        catch(RuntimeException expected) {
            Throwable root=expected; while(root.getCause()!=null)root=root.getCause();
            check(root.getMessage().contains("Freight abort without departure"),"Wrong queued rejection");
        }
        rejected(bad::requireApproved);
    }
    private static void synthetic27ReportBeforeRejection() throws Exception {
        // Synthetic IDs and timings, deliberately different from the failed run.
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        for(int i=0;i<27;i++) {
            var p=scenario.getPopulation().getFactory().createPerson(Id.createPersonId(String.format(Locale.ROOT,"synthetic_h%02d",i)));
            p.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
            p.getAttributes().putAttribute("simz1FreightDeparture",i==26?78000.:34500.);
            p.getAttributes().putAttribute("simz1FreightRoute","a b c");
            p.getAttributes().putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);
            scenario.getPopulation().addPerson(p);
        }
        var handler=new SimZ1Freight(scenario);
        for(int i=0;i<27;i++) {
            String id=String.format(Locale.ROOT,"synthetic_h%02d",i);
            double start=i==26?78000:34500;
            handler.handleEvent(event(id,"departure",start,"a")); handler.handleEvent(event(id,"vehicle enters traffic",start+1,"a"));
            if(i<23) {
                handler.handleEvent(event(id,"entered link",start+10,"b")); handler.handleEvent(event(id,"entered link",start+20,"c"));
                handler.handleEvent(event(id,"vehicle leaves traffic",start+30,"c")); handler.handleEvent(event(id,"arrival",start+30,"c"));
            } else {
                if(i<26)for(double time:new double[]{57600,57601,75601})
                    handler.handleEvent(event(id,"simz1NativeDecision",time,"a"));
                handler.handleEvent(event(id,"stuckAndAbort",86401,"a")); handler.handleEvent(event(id,"vehicle aborts",86401,"a"));
            }
        }
        check(handler.activeCount()==0 && handler.violations().size()==3,"Zero active is not full completion");
        check(handler.violations().values().stream().allMatch(v->v.observed()==57600),"First violation lost/double counted");
        Path report=Files.createTempFile("synthetic-freight-27-", ".csv");
        try {
            handler.writeReport(report);
            byte[] before=Files.readAllBytes(report);
            try {
                handler.requireApproved();
                throw new AssertionError("Incomplete fleet approved");
            } catch(IllegalStateException expected) {
                check(expected.getMessage().equals("FREIGHT_NOT_APPROVED: restricted=3, active_or_censored=0, completed=23/27"),
                    "Wrong rejection/reconciliation: "+expected.getMessage());
            }
            check(Arrays.equals(before,Files.readAllBytes(report)),"Rejection changed persisted evidence");
            try(var reader=Files.newBufferedReader(report,StandardCharsets.UTF_8);
                var csv=CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {
                var rows=csv.getRecords();
                check(rows.size()==27 && rows.stream().map(r->r.get("vehicle")).distinct().count()==27,"Incomplete reconciliation");
                check(rows.stream().filter(r->r.get("trip_outcome").equals("completed")).count()==23,"Wrong completed count");
                check(rows.stream().filter(r->r.get("trip_outcome").equals("aborted")).count()==4,"Abort pair counted twice");
                check(rows.stream().filter(r->r.get("schedule_compliance").equals("violated")).count()==3,"Wrong restricted count");
                var night=rows.stream().filter(r->r.get("vehicle").equals("synthetic_h26")).findFirst().orElseThrow();
                check(night.get("trip_outcome").equals("aborted") && night.get("violation_observed").isEmpty(),"Night cleanup invented a violation/completion");
            }
            handler.reset(1);
            check(handler.violations().isEmpty() && !handler.approved(),"Iteration reset retained findings or approved missing trips");
        } finally { Files.deleteIfExists(report); }
    }
    public static void main(String[] args) throws Exception {
        SimZ1FreightCheck.main(args); lifecycle(); synthetic27ReportBeforeRejection(); neverDepartedCleanup();
        var executor=Executors.newSingleThreadExecutor(r->{var t=new Thread(r);t.setDaemon(true);return t;});
        try { executor.submit(()->{ parallelCleanup(); orderedUnstartedCleanup(); return null; }).get(20,TimeUnit.SECONDS); }
        finally { executor.shutdownNow(); }
        System.out.println("SIMZ1_FREIGHT_CLOSURE_OK");
    }
}
