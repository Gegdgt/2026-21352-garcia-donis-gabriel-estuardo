package gt.edu.uvg.sim.zona1;

import java.util.*;
import java.io.*;
import java.nio.file.*;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;
import org.matsim.core.controler.events.AfterMobsimEvent;
import org.matsim.core.controler.listener.AfterMobsimListener;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.vehicles.*;

/** Explicit service actors, independent of private N. Never fabricates movement events. */
public final class SimZ1Freight implements BasicEventHandler, BeforeMobsimListener, AfterMobsimListener, IterationEndsListener, MobsimBeforeCleanupListener {
    public static final String SCHEMA = "simz1-freight-weekday-v1";
    public static final String OVERNIGHT_POLICY = "weekday_overnight_until_05_v2";
    public static final String LEGACY_RESIDENCE_POLICY = "legacy_horizon_clip_v1";
    private final Scenario scenario;
    private final Set<String> fleet = new HashSet<>();
    private final Map<String,Double> active = new HashMap<>();
    private final Map<String,Double> traffic = new HashMap<>(), lastTimes = new HashMap<>();
    private final Map<String,Double> departures = new HashMap<>(), entries = new HashMap<>(), exits = new HashMap<>();
    private final Set<String> started = new HashSet<>(), seen = new HashSet<>();
    private final Map<String,Integer> positions = new HashMap<>();
    record Violation(double entry, double observed, String eventType, String policy, String evidence) { }
    private record Terminal(String status, double time, Set<String> sources) { }
    private final Map<String,Violation> violations = new TreeMap<>();
    private final Map<String,Terminal> terminals = new TreeMap<>();
    private Object iterationToken = new Object();
    private double cleanupTime = Double.NaN;
    private final class CleanupStart extends Event {
        private final Object token;
        CleanupStart(double time, Object token) { super(time); this.token=token; }
        boolean current(SimZ1Freight handler) { return handler==SimZ1Freight.this&&token==iterationToken; }
        @Override public String getEventType() { return "simz1FreightCleanupStart"; }
    }
    private static final Set<String> MOVEMENT = Set.of("vehicle enters traffic", "vehicle leaves traffic",
        "entered link", "left link", "entered lane", "left lane");
    private final Map<String,String> residencePolicies = new HashMap<>();
    private final Map<String,String> completionPoliciesById = new HashMap<>();
    private final Map<String,Double> scheduled = new HashMap<>();
    private record AdmissionRejection(double time,String reason) { }
    private final Map<String,AdmissionRejection> admissionRejections = new HashMap<>();
    private final Map<String,Set<String>> admissionRejectionReasons = new HashMap<>();
    private final SimZ1FreightCompletion.Clearance clearance = new SimZ1FreightCompletion.Clearance();
    private final boolean experimental;
    SimZ1Freight(Scenario scenario) {
        this.scenario=scenario;
        var completionPolicies=new HashSet<String>();
        scenario.getPopulation().getPersons().values().stream().filter(SimZ1Freight::applies)
            .forEach(p->{
                String id=p.getId().toString();fleet.add(id);residencePolicies.put(id,residencePolicy(p));
                String policy=Objects.toString(p.getAttributes().getAttribute(SimZ1FreightCompletion.ATTRIBUTE),SimZ1FreightCompletion.HISTORICAL);
                completionPoliciesById.put(id,policy);
                completionPolicies.add(policy);SimZ1FreightCompletion.requirePolicy(policy);
                scheduled.put(id,Double.parseDouble(p.getAttributes().getAttribute("simz1FreightDeparture").toString()));
                if(SimZ1FreightCompletion.experimental(policy)) {
                    var w=SimZ1FreightCompletion.assigned(scheduled.get(id));
                    if(!OVERNIGHT_POLICY.equals(residencePolicy(p)))throw new IllegalArgumentException("Experimental freight requires original overnight windows");
                    try {
                        var declared=new com.fasterxml.jackson.databind.ObjectMapper().readTree(p.getAttributes().getAttribute("simz1FreightAssignedWindow").toString());
                        if(declared.size()!=2||declared.get(0).asDouble()!=w.start()||declared.get(1).asDouble()!=w.close())throw new IllegalArgumentException("Freight assigned window changed");
                    }catch(Exception ex){throw new IllegalArgumentException("Invalid assigned freight window",ex);}
                    clearance.add(p);
                }
            });
        if(completionPolicies.size()>1)throw new IllegalArgumentException("Mixed freight completion policies");
        experimental=completionPolicies.stream().anyMatch(SimZ1FreightCompletion::experimental);
    }
    public static boolean applies(Person p) {
        return p!=null && SCHEMA.equals(p.getAttributes().getAttribute("simz1FreightService"));
    }
    public static boolean serviceType(VehicleType t) {
        return "FreightTruck".equals(t.getId().toString()) && SCHEMA.equals(t.getAttributes().getAttribute("simz1FreightService"));
    }
    /** Pure authorization query; this neither reserves a body nor moves/removes
     * an actor. The native wait-list calls it before any admission mutation. */
    public record OriginEntry(boolean applicable,boolean permitted,String reason,
            double plannedDeparture,double windowStart,double nominalClose,
            double latestEntryTime,boolean latestEntryInclusive,double completionDeadline,String completionPolicy) {
        public String entryPolicy() {
            return SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY.equals(completionPolicy)?
                SimZ1FreightCompletion.TOLERATED_ENTRY:SimZ1FreightCompletion.NOMINAL_ENTRY;
        }
    }
    private static final OriginEntry UNRESTRICTED_ORIGIN_ENTRY=new OriginEntry(false,true,"not_applicable",
        Double.NaN,Double.NaN,Double.NaN,Double.NaN,false,Double.NaN,SimZ1FreightCompletion.HISTORICAL);
    public static OriginEntry originEntry(Person person,double now) {
        if(!applies(person))return UNRESTRICTED_ORIGIN_ENTRY;
        String policy=Objects.toString(
            person.getAttributes().getAttribute(SimZ1FreightCompletion.ATTRIBUTE),SimZ1FreightCompletion.HISTORICAL);
        if(SimZ1FreightCompletion.HISTORICAL.equals(policy))return UNRESTRICTED_ORIGIN_ENTRY;
        if(!SimZ1FreightCompletion.experimental(policy))throw new IllegalArgumentException("Unknown freight origin policy: "+policy);
        if(!OVERNIGHT_POLICY.equals(residencePolicy(person)))throw new IllegalArgumentException("Experimental freight requires original overnight windows");
        if(!Double.isFinite(now))throw new IllegalArgumentException("Nonfinite freight origin time");
        double planned=Double.parseDouble(Objects.requireNonNull(person.getAttributes().getAttribute("simz1FreightDeparture")).toString());
        var w=SimZ1FreightCompletion.assigned(planned);
        // Validate the per-person declaration without loading a resource or
        // constructing a JSON parser in the per-timestep native path.
        String declared=Objects.requireNonNull(person.getAttributes().getAttribute("simz1FreightAssignedWindow")).toString().trim();
        if(!declared.startsWith("[")||!declared.endsWith("]"))throw new IllegalArgumentException("Invalid assigned freight origin window");
        var values=declared.substring(1,declared.length()-1).split(",",-1);
        if(values.length!=2||Double.parseDouble(values[0].trim())!=w.start()||Double.parseDouble(values[1].trim())!=w.close())
            throw new IllegalArgumentException("Changed assigned freight origin window");
        boolean inclusive=SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY.equals(policy);
        double latest=inclusive?w.deadline():w.close();
        String reason=now<w.start()||now<planned-1.01?"before_scheduled_departure":
            SimZ1FreightCompletion.entryPermitted(policy,planned,now)?"authorized":
                inclusive?"assigned_entry_deadline_expired":"assigned_nominal_window_closed";
        return new OriginEntry(true,reason.equals("authorized"),reason,planned,w.start(),w.close(),latest,inclusive,w.deadline(),policy);
    }
    public static int privateCount(Scenario s) {
        return (int)s.getPopulation().getPersons().values().stream().filter(p->!applies(p)).count();
    }
    public static boolean permitted(double start,double end) {
        return permitted(start,end,OVERNIGHT_POLICY);
    }
    private static String residencePolicy(Person p) {
        return Objects.toString(p.getAttributes().getAttribute("simz1FreightResidencePolicy"),LEGACY_RESIDENCE_POLICY);
    }
    public static boolean permitted(double start,double end,String policy) {
        if(!Set.of(OVERNIGHT_POLICY,LEGACY_RESIDENCE_POLICY).contains(policy))return false;
        double nightEnd=OVERNIGHT_POLICY.equals(policy)?104400:86400;
        return Double.isFinite(start) && Double.isFinite(end) && start<=end &&
            (start>=0 && end<18000 || start>=32400 && end<57600 || start>=75600 && end<nightEnd);
    }
    public static void configure(Scenario s) {
        if (s.getPopulation().getPersons().values().stream().anyMatch(SimZ1Freight::applies))
            s.getConfig().planCalcScore().addActivityParams(new org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams("freight_external").setScoringThisActivityAtAll(false));
        for (Person p:s.getPopulation().getPersons().values()) {
            if (!applies(p)) continue;
            double weight=Double.parseDouble(p.getAttributes().getAttribute("simz1GrossWeightTonnes").toString());
            double departure=Double.parseDouble(p.getAttributes().getAttribute("simz1FreightDeparture").toString());
            var type=s.getVehicles().getVehicleTypes().get(Id.create("FreightTruck",VehicleType.class));
            String residence=residencePolicy(p);
            if (!Double.isFinite(weight) || weight<=3.5 || departure>=86400 || !permitted(departure,departure,residence) || type==null ||
                !"car".equals(type.getNetworkMode()) || type.getMaximumVelocity()<=0 || type.getPcuEquivalents()<=0)
                throw new IllegalArgumentException("Invalid explicit freight contract: "+p.getId());
            if(!residence.equals(Objects.toString(type.getAttributes().getAttribute("simz1FreightResidencePolicy"),LEGACY_RESIDENCE_POLICY)))
                throw new IllegalArgumentException("Freight vehicle/person residence policy mismatch: "+p.getId());
            var id=Id.createVehicleId(p.getId());
            if (!s.getVehicles().getVehicles().containsKey(id) ||
                !s.getVehicles().getVehicles().get(id).getType().getId().equals(type.getId()))
                throw new IllegalArgumentException("Freight vehicle missing/mismatched: "+id);
            VehicleUtils.insertVehicleIdsIntoAttributes(p,Map.of("car",id));
        }
    }
    public static void install(Controler c) {
        var handler=new SimZ1Freight(c.getScenario());
        if (handler.fleet.isEmpty()) return;
        c.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance(handler);
                addControlerListenerBinding().toInstance(handler);
                addMobsimListenerBinding().toInstance(handler);
            }
        });
    }
    @Override public synchronized void notifyBeforeMobsim(BeforeMobsimEvent event) {
        reset(event.getIteration());
        var safety=new SimZ1RouteSafety(scenario);
        for (Person p:scenario.getPopulation().getPersons().values()) {
            if (!applies(p)) continue;
            var links=Arrays.stream(p.getAttributes().getAttribute("simz1FreightRoute").toString().split(" "))
                .map(Id::createLinkId).toList();
            String reason=safety.validateNetwork(links);
            if (reason!=null) throw new IllegalArgumentException("Invalid freight corridor: "+reason);
            var elements=p.getSelectedPlan().getPlanElements();
            if (elements.size()!=3 || !(elements.get(1) instanceof Leg leg))
                throw new IllegalArgumentException("Freight must have one explicit expedition");
            var route=RouteUtils.createLinkNetworkRouteImpl(links.get(0),links.get(links.size()-1));
            route.setLinkIds(links.get(0),links.subList(1,links.size()-1),links.get(links.size()-1));
            route.setVehicleId(Id.createVehicleId(p.getId()));
            leg.setRoute(route);
            ((Activity)elements.get(0)).setEndTime(Double.parseDouble(p.getAttributes().getAttribute("simz1FreightDeparture").toString()));
        }
    }
    @Override public synchronized void reset(int iteration) {
        iterationToken=new Object(); cleanupTime=Double.NaN;
        active.clear(); traffic.clear(); lastTimes.clear(); started.clear(); seen.clear();
        positions.clear(); violations.clear(); terminals.clear();
        departures.clear(); entries.clear(); exits.clear();
        admissionRejections.clear(); admissionRejectionReasons.clear();
        clearance.reset();
    }
    @Override public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        var qsim=(QSim)event.getQueueSimulation();
        beforeCleanup(qsim.getEventsManager(),qsim.getSimTimer().getTimeOfDay());
    }
    // Enqueue on the same manager BEFORE QSim's engines emit their aborts. A
    // callback-thread boolean would also excuse earlier, still queued events.
    // Package access permits component tests without constructing/running QSim.
    void beforeCleanup(EventsManager manager, double time) {
        final CleanupStart marker;
        synchronized(this) {
            if(!Double.isFinite(time)||time<0)throw new IllegalStateException("Invalid freight cleanup time");
            marker=new CleanupStart(time,iterationToken);
        }
        // Never wait on the manager while holding the event-handler monitor.
        manager.processEvent(marker);
    }
    private void residence(String id, double time, String kind) {
        Double entry=traffic.get(id);
        if(entry!=null && !permitted(entry,time,residencePolicies.get(id)))
            violations.putIfAbsent(id,new Violation(entry,time,kind,residencePolicies.get(id),
                Set.of("arrival","stuckAndAbort","vehicle aborts").contains(kind)?"terminal_residence":"traffic_residence"));
    }
    synchronized Map<String,Violation> violations() { return Map.copyOf(violations); }
    synchronized int activeCount() { return active.size(); }
    synchronized boolean approved() {
        return complete() && (experimental?fleet.stream().allMatch(id->Set.of("nominal","tolerated").contains(classification(id))):violations.isEmpty());
    }
    private boolean complete() {return active.isEmpty()&&terminals.size()==fleet.size()&&terminals.values().stream().allMatch(t->t.status.equals("completed"));}
    private String classification(String id) {
        var t=terminals.get(id);
        return SimZ1FreightCompletion.classify(completionPoliciesById.get(id),scheduled.get(id),entries.get(id),exits.get(id),
            t!=null&&t.status.equals("completed")?t.time:null,clearance.proofs.containsKey(id),
            t!=null&&!t.status.equals("completed"),violations.containsKey(id));
    }
    synchronized void requireApproved() {
        if(!approved()) throw new IllegalStateException("FREIGHT_NOT_APPROVED: restricted="+violations.size()+
            ", active_or_censored="+active.size()+", completed="+
            terminals.values().stream().filter(t->t.status.equals("completed")).count()+"/"+fleet.size());
    }
    // Runs on the controller thread AFTER QSim cleanup/finishProcessing, never on an event worker.
    @Override public synchronized void notifyAfterMobsim(AfterMobsimEvent event) {
        // MATSim invokes this even when the mobsim threw. IterationEnds may never
        // follow; persist incomplete outcomes without replacing the primary error
        // with requireApproved(). Scientific rejection remains at IterationEnds.
        writeReport(Path.of(event.getServices().getControlerIO().getIterationFilename(event.getIteration(),"simz1-freight-audit.csv")));
    }
    @Override public synchronized void notifyIterationEnds(IterationEndsEvent event) {
        Path report=Path.of(event.getServices().getControlerIO().getIterationFilename(event.getIteration(),"simz1-freight-audit.csv"));
        writeReport(report);
        if(!experimental)requireApproved();
        else {
            // Timing failure is retained but must not interrupt later iterations
            // or turn a naturally completed native trip into an abort.
            var day=SimZ1DayObservation.get(scenario);
            boolean fixedDay=SimZ1DayObservation.enabled(scenario.getConfig());
            if((fixedDay&&(day==null||!day.reached())) || (!fixedDay&&!complete()) || fleet.stream().anyMatch(id->
                "technical_physical_error".equals(classification(id)) || "pending_not_evaluable".equals(classification(id))&&!(fixedDay&&day.censored(id))))
                throw new IllegalStateException("FREIGHT_NOT_APPROVED: incomplete or missing native physical evidence");
            if(!approved())System.out.println("FREIGHT_EXPERIMENT_REVIEW_REQUIRED: unfinished or outside completion indicator; consult per-trip day census and native timing evidence");
        }
    }
    synchronized void writeReport(Path report) {
        try(var writer=Files.newBufferedWriter(report,java.nio.charset.StandardCharsets.UTF_8);
            var csv=new CSVPrinter(writer,CSVFormat.DEFAULT)) {
            csv.printRecord("audit_version","vehicle","technical_integrity","schedule_compliance","trip_outcome",
                "residence_policy","departure","traffic_entry","traffic_exit","violation_observed","violation_event","evidence","terminal_time","terminal_sources",
                "completion_policy","assigned_window_start","assigned_window_close","completion_deadline_inclusive","scheduled_departure","arrival","delay_seconds","completion_classification","body_clearance_proof",
                "admission_status","admission_rejection_time","admission_rejection_reason","latest_entry_time","latest_entry_inclusive");
            for(String id:new TreeSet<>(fleet)) {
                var v=violations.get(id); var t=terminals.get(id);
                var w=experimental?SimZ1FreightCompletion.assigned(scheduled.get(id)):null;
                var denial=admissionRejections.get(id);
                boolean inclusive=SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY.equals(completionPoliciesById.get(id));
                csv.printRecord(experimental?3:2,id,"valid",v!=null?"violated":active.containsKey(id)||!started.contains(id)?"undetermined":"no_violation_observed",
                    t!=null?t.status:active.containsKey(id)?"active_or_censored":"not_departed",residencePolicies.get(id),
                    departures.get(id),entries.get(id),exits.get(id),v!=null?v.observed:null,v!=null?v.eventType:null,
                    v!=null?v.evidence:t!=null&&t.status.equals("aborted_before_departure")?"qsim_cleanup_without_departure":null,
                    t!=null?t.time:null,t!=null?String.join("|",new TreeSet<>(t.sources)):null,
                    completionPoliciesById.get(id),
                    w!=null?w.start():null,w!=null?w.close():null,w!=null?w.deadline():null,scheduled.get(id),
                    t!=null&&t.status.equals("completed")?t.time:null,
                    w!=null&&t!=null&&t.status.equals("completed")?Math.max(0,t.time-w.close()):null,
                    experimental?classification(id):null,experimental?clearance.proofs.get(id):null,
                    !experimental?null:entries.containsKey(id)?"entered":denial!=null?
                        denial.reason.equals("before_scheduled_departure")?"waiting_before_scheduled_departure":"authorization_expired_not_admitted":
                        started.contains(id)?"waiting_for_incorporation":"not_departed",
                    denial!=null?denial.time:null,denial!=null?denial.reason:null,
                    w!=null?(inclusive?w.deadline():w.close()):null,w!=null?inclusive:null);
            }
        } catch(IOException ex) { throw new UncheckedIOException(ex); }
    }
    @Override public synchronized void handleEvent(Event e) {
        if(e instanceof SimZ1Freight.CleanupStart marker) {
            if(!marker.current(this)||Double.isFinite(cleanupTime))
                throw new IllegalStateException("Stale/duplicate freight cleanup marker");
            cleanupTime=e.getTime();
            return;
        }
        if(experimental)clearance.consume(e);
        var a=e.getAttributes();
        String id=a.getOrDefault("person",a.get("vehicle"));
        if (!fleet.contains(id)) return;
        String kind=e.getEventType();
        boolean abort=kind.equals("stuckAndAbort")||kind.equals("vehicle aborts");
        if(!MOVEMENT.contains(kind) && !Set.of("departure","arrival","simz1NativeDecision","simz1FreightAdmissionRejected").contains(kind) && !abort)return;
        double time=e.getTime();
        if(!Double.isFinite(time)||time<lastTimes.getOrDefault(id,Double.NEGATIVE_INFINITY))
            throw new IllegalStateException("Freight invalid/non-monotone event time: "+id);
        lastTimes.put(id,time);
        Person person=scenario.getPopulation().getPersons().get(Id.createPersonId(id));
        var path=Arrays.asList(person.getAttributes().getAttribute("simz1FreightRoute").toString().split(" "));
        if(kind.equals("simz1FreightAdmissionRejected")) {
            var authorization=originEntry(person,time);
            if(!authorization.applicable()||authorization.permitted()||!active.containsKey(id)||seen.contains(id)||
                    !id.equals(a.get("vehicle"))||!path.get(0).equals(a.get("link"))||
                    !authorization.reason().equals(a.get("reason"))||!authorization.entryPolicy().equals(a.get("entryPolicy"))||
                    !authorization.completionPolicy().equals(a.get("completionPolicy"))||
                    !Boolean.toString(authorization.latestEntryInclusive()).equals(a.get("latestEntryInclusive")))
                throw new IllegalStateException("Invalid freight admission rejection: "+id);
            for(var expected:Map.of("scheduledDeparture",authorization.plannedDeparture(),"assignedWindowStart",authorization.windowStart(),
                    "assignedWindowClose",authorization.nominalClose(),"latestEntryTime",authorization.latestEntryTime(),"completionDeadline",authorization.completionDeadline()).entrySet()) {
                double actual;
                try {actual=Double.parseDouble(Objects.requireNonNull(a.get(expected.getKey())));}
                catch(RuntimeException ex){throw new IllegalStateException("Malformed freight admission rejection: "+id,ex);}
                if(actual!=expected.getValue())throw new IllegalStateException("Changed freight admission rejection boundary: "+id);
            }
            if(!admissionRejectionReasons.computeIfAbsent(id,k->new HashSet<>()).add(authorization.reason()))
                throw new IllegalStateException("Duplicate freight admission rejection: "+id);
            admissionRejections.put(id,new AdmissionRejection(time,authorization.reason()));
            return;
        }
        if(kind.equals("departure")) {
            double planned=Double.parseDouble(person.getAttributes().getAttribute("simz1FreightDeparture").toString());
            if(started.contains(id)||terminals.containsKey(id)||Math.abs(time-planned)>1.01||!path.get(0).equals(a.get("link")))
                throw new IllegalStateException("Freight duplicate/late/incorrect departure: "+id);
            started.add(id); active.put(id,time); departures.put(id,time);
        }
        if((MOVEMENT.contains(kind)||kind.equals("departure")||kind.equals("arrival")) && !path.contains(a.get("link")))
            throw new IllegalStateException("Freight outside configured route: "+id);
        if((MOVEMENT.contains(kind)||kind.equals("arrival")) && !active.containsKey(id))
            throw new IllegalStateException("Freight movement/arrival without active departure: "+id);
        if(MOVEMENT.contains(kind)&&!kind.equals("vehicle enters traffic")&&!traffic.containsKey(id))
            throw new IllegalStateException("Freight movement without traffic entry: "+id);
        if(kind.equals("vehicle enters traffic")) {
            if(seen.contains(id)||!id.equals(a.get("vehicle"))||!path.get(0).equals(a.get("link")))
                throw new IllegalStateException("Freight vehicle/driver identity mismatch: "+id);
            if(experimental) {
                if(!SimZ1FreightCompletion.entryPermitted(completionPoliciesById.get(id),scheduled.get(id),time))
                    throw new IllegalStateException((SimZ1FreightCompletion.POLICY.equals(completionPoliciesById.get(id))?
                        "Freight entry outside assigned nominal window: ":"Freight entry outside assigned authorization: ")+id);
            }
            seen.add(id); positions.put(id,0); traffic.put(id,time); entries.put(id,time);
        }
        residence(id,time,kind);
        if(kind.equals("entered link")) {
            int index=positions.getOrDefault(id,-1)+1;
            if(index>=path.size()||!path.get(index).equals(a.get("link")))
                throw new IllegalStateException("Freight route sequence mismatch: "+id);
            positions.put(id,index);
        }
        if(kind.equals("vehicle leaves traffic")) { traffic.remove(id); exits.put(id,time); }
        if(kind.equals("arrival")) {
            if(positions.getOrDefault(id,-1)!=path.size()-1||!path.get(path.size()-1).equals(a.get("link")))
                throw new IllegalStateException("Freight incomplete route/arrival: "+id);
            active.remove(id); terminals.put(id,new Terminal("completed",time,new HashSet<>(Set.of(kind))));
        }
        if(abort) {
            var terminal=terminals.get(id);
            if(terminal!=null) {
                if(!Set.of("aborted","aborted_before_departure").contains(terminal.status)||terminal.time!=time||!terminal.sources.add(kind))
                    throw new IllegalStateException("Freight conflicting/duplicate terminal event: "+id);
            } else {
                boolean neverStarted=!started.contains(id)&&!active.containsKey(id);
                if(!active.containsKey(id)&&!(neverStarted&&Double.isFinite(cleanupTime)&&time>=cleanupTime))
                    throw new IllegalStateException("Freight abort without departure: "+id);
                active.remove(id);
                terminals.put(id,new Terminal(neverStarted?"aborted_before_departure":"aborted",time,new HashSet<>(Set.of(kind))));
            }
        }
        if(kind.equals("arrival")||abort) { traffic.remove(id); positions.remove(id); }
    }
}
