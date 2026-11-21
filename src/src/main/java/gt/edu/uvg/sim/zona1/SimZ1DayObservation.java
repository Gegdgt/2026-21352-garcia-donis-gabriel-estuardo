package gt.edu.uvg.sim.zona1;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPOutputStream;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.ReflectiveConfigGroup;
import org.matsim.core.controler.*;
import org.matsim.core.controler.events.*;
import org.matsim.core.controler.listener.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;

/** Observes a fixed day BEFORE native cleanup. Never moves or removes an agent. */
public final class SimZ1DayObservation implements BasicEventHandler, MobsimAfterSimStepListener,
        MobsimBeforeCleanupListener, AfterMobsimListener, IterationEndsListener {
    public static final String POLICY="fixed-day-24h-v1";
    public static final double END=86400;
    public static final class Settings extends ReflectiveConfigGroup {
        private String policy=POLICY;
        public Settings(){super("simz1Observation");}
        @StringGetter("policy") public String getPolicy(){return policy;}
        @StringSetter("policy") public void setPolicy(String value){
            if(!POLICY.equals(value))throw new IllegalArgumentException("Unknown observation policy");policy=value;
        }
    }
    private static final Set<String> PHYSICAL=Set.of("departure","arrival","vehicle enters traffic",
        "vehicle leaves traffic","entered link","left link","entered lane","left lane","TransitDriverStarts");
    private final Map<String,Map<String,Object>> templates=new TreeMap<>(),rows=new TreeMap<>();
    private final Map<String,String> drivers=new HashMap<>(),vehicles=new HashMap<>();
    private final Map<String,Long> cleanupAborts=new TreeMap<>();
    private Map<String,Map<String,Object>> census;
    private double lastStep=Double.NaN,cut=Double.NaN;
    private int iteration;
    private Object token=new Object();
    private final String runId;
    private final class Cut extends Event {
        final Object generation=token;
        Cut(double time){super(time);}
        @Override public String getEventType(){return "simz1DayCut";}
        @Override public Map<String,String> getAttributes(){var a=super.getAttributes();a.put("policy",POLICY);a.put("run_id",runId);
            a.put("lastCompletedStep",Double.toString(lastStep));a.put("iteration",Integer.toString(iteration));return a;}
    }
    public static boolean enabled(Config c) {
        if(!c.getModules().containsKey("simz1Observation"))return false;
        return POLICY.equals(ConfigUtils.addOrGetModule(c,Settings.class).getPolicy());
    }
    public static double horizon(Config c){return enabled(c)?END:c.qsim().getEndTime().seconds();}
    public static SimZ1DayObservation get(Scenario s){return (SimZ1DayObservation)s.getScenarioElement(POLICY);}
    public static void install(Controler c) {
        if(!enabled(c.getConfig()))return;
        var observer=new SimZ1DayObservation(c.getScenario(),Objects.toString(System.getenv("SIMZ1_RUN_ID"),"unmanaged"));
        c.getScenario().addScenarioElement(POLICY,observer);
        c.addControlerListener(observer);
        c.addOverridingModule(new AbstractModule(){@Override public void install(){
            addEventHandlerBinding().toInstance(observer);addMobsimListenerBinding().toInstance(observer);}});
    }
    SimZ1DayObservation(Scenario s,String runId) {
        this.runId=runId;
        var mapper=new ObjectMapper();
        if(s.getConfig().qsim().getEndTime().seconds()!=86399 || s.getConfig().qsim().getTimeStepSize()!=1)
            throw new IllegalArgumentException("MATSim15 fixed-day requires native endTime=86399 and step=1 (physical cutoff=86400)");
        try(var stream=getClass().getResourceAsStream("/simz1/day-observation-v1.json")) {
            var doc=mapper.readTree(Objects.requireNonNull(stream));
            if(!POLICY.equals(doc.path("version").asText())||doc.path("observation_end_seconds").asInt()!=86400||doc.path("native_qsim_end_seconds").asInt()!=86399)
                throw new IllegalArgumentException("Changed fixed-day resource");
        } catch(IOException e){throw new UncheckedIOException(e);}
        for(var p:s.getPopulation().getPersons().values()) {
            String id=p.getId().toString();
            double scheduled=((Activity)p.getSelectedPlan().getPlanElements().get(0)).getEndTime().seconds();
            Object exact=p.getAttributes().getAttribute(SimZ1Freight.applies(p)?"simz1FreightDeparture":"simz1PlannedDepartureSeconds");
            if(exact!=null)scheduled=Double.parseDouble(exact.toString());
            if(!SimZ1Freight.applies(p)&&p.getAttributes().getAttribute("simz1Trips")!=null)try {
                scheduled=mapper.readTree(p.getAttributes().getAttribute("simz1Trips").toString()).get(0).get("planned_departure").asDouble();
            }catch(IOException ex){throw new UncheckedIOException(ex);}
            var row=template(id,id,scheduled,SimZ1Freight.applies(p)?"pesado":Objects.toString(p.getAttributes().getAttribute("simz1VehicleFamily"),"unknown"));
            row.put("profile",p.getAttributes().getAttribute("drivingProfile"));
            row.put("od",p.getAttributes().getAttribute("simz1SpatialOD"));
            templates.put(id,row);
        }
        for(var line:s.getTransitSchedule().getTransitLines().values())for(var route:line.getRoutes().values())for(var d:route.getDepartures().values()) {
            String id=busKey(line.getId().toString(),route.getId().toString(),d.getId().toString());
            templates.put(id,template(id,d.getVehicleId().toString(),d.getDepartureTime(),"bus"));
        }
        reset(0);
    }
    private static String busKey(String line,String route,String dep){return "bus:"+line+":"+route+":"+dep;}
    private static Map<String,Object> template(String trip,String vehicle,double scheduled,String family) {
        if(!Double.isFinite(scheduled)||scheduled<0||scheduled>=END)throw new IllegalArgumentException("Demand outside [0,86400): "+trip);
        var r=new LinkedHashMap<String,Object>();r.put("trip_id",trip);r.put("vehicle_id",vehicle);r.put("family",family);
        r.put("scheduled_departure",scheduled);
        for(String k:List.of("departure","traffic_entry","traffic_exit","arrival","abort_before_cleanup","last_transition","last_link"))r.put(k,null);
        return r;
    }
    @Override public synchronized void reset(int it){iteration=it;token=new Object();rows.clear();
        templates.forEach((id,r)->rows.put(id,new LinkedHashMap<>(r)));drivers.clear();vehicles.clear();cleanupAborts.clear();
        census=null;lastStep=cut=Double.NaN;}
    @Override public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent e){lastStep=e.getSimulationTime();
        if(lastStep>END)throw new IllegalStateException("Physical QSim step beyond fixed-day cut");}
    @Override public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent e){var q=(QSim)e.getQueueSimulation();
        q.getEventsManager().processEvent(new Cut(q.getSimTimer().getTimeOfDay()));}
    @Override public synchronized void handleEvent(Event e) {
        if(e instanceof SimZ1DayObservation.Cut marker) {
            if(marker.generation!=token||census!=null)throw new IllegalStateException("Stale/duplicate day census");
            cut=e.getTime();census=new TreeMap<>();rows.forEach((id,r)->census.put(id,classify(r,cut,reached())));return;
        }
        String kind=e.getEventType();var a=e.getAttributes();double time=e.getTime();
        if(PHYSICAL.contains(kind)&&time>END)throw new IllegalStateException("Physical event after cutoff: "+kind+" "+time);
        if(e instanceof TransitDriverStartsEvent t) {
            String key=busKey(t.getTransitLineId().toString(),t.getTransitRouteId().toString(),t.getDepartureId().toString());
            if(!rows.containsKey(key))throw new IllegalStateException("Unscheduled bus expedition");
            drivers.put(t.getDriverId().toString(),key);vehicles.put(t.getVehicleId().toString(),key);
        }
        String person=a.get("person"),vehicle=a.get("vehicle");
        String id=person!=null?drivers.getOrDefault(person,person):vehicles.getOrDefault(vehicle,vehicle);
        if(id==null)return;
        var row=rows.get(id);if(row==null)return;
        boolean abort=Set.of("stuckAndAbort","vehicle aborts").contains(kind);
        if(census!=null) {
            if(abort)cleanupAborts.merge(id,1L,Long::sum);
            else if(PHYSICAL.contains(kind))throw new IllegalStateException("Physical event during administrative cleanup");
            return;
        }
        String field=switch(kind){case "departure"->"departure";case "vehicle enters traffic"->"traffic_entry";
            case "vehicle leaves traffic"->"traffic_exit";case "arrival"->"arrival";default->null;};
        if(field!=null)row.put(field,time);
        if(abort)row.put("abort_before_cleanup",time);
        if(PHYSICAL.contains(kind)) {row.put("last_transition",time);row.put("last_link",a.get("link"));}
        if(vehicle!=null)vehicles.put(vehicle,id);
    }
    public synchronized boolean reached(){return cut==END&&lastStep==END;}
    public synchronized boolean censored(String id){var r=census==null?null:census.get(id);
        return reached()&&r!=null&&Set.of("active_at_cut","waiting_for_incorporation","scheduled_not_departed").contains(r.get("status"));}
    static Map<String,Object> classify(Map<String,Object> row,double cut,boolean reached) {
        var r=new LinkedHashMap<>(row);Double entry=(Double)row.get("traffic_entry"),departure=(Double)row.get("departure"),arrival=(Double)row.get("arrival");
        Double exit=(Double)row.get("traffic_exit"),abort=(Double)row.get("abort_before_cleanup");
        double scheduled=(double)row.get("scheduled_departure");r.put("cut_seconds",cut);
        r.put("complete_duration_seconds",arrival!=null&&departure!=null?arrival-departure:null);
        // A native traffic exit is not an arrival. Its observed traffic interval
        // nevertheless ends there, even when a later abort or horizon is seen.
        // Equal timestamps retain the more specific native exit as the basis.
        Double observedEnd=null;String observedBasis=null;
        if(arrival==null&&entry!=null) {
            observedEnd=cut;observedBasis="observation_cut";
            if(abort!=null&&abort<=observedEnd){observedEnd=abort;observedBasis="abort_before_cleanup";}
            if(exit!=null&&exit<=observedEnd){observedEnd=exit;observedBasis="traffic_exit";}
            if(!Double.isFinite(entry)||entry<0||!Double.isFinite(observedEnd)||observedEnd<entry)
                throw new IllegalArgumentException("Invalid observed traffic interval: "+row.get("trip_id"));
        }
        r.put("observed_traffic_end_seconds",observedEnd);r.put("observed_traffic_end_basis",observedBasis);
        r.put("observed_traffic_seconds",observedEnd!=null?observedEnd-entry:null);
        r.put("request_age_seconds",Math.max(0,cut-scheduled));r.put("incorporation_delay_seconds",entry!=null&&departure!=null?entry-departure:null);
        String status=arrival!=null?"completed":abort!=null?"aborted_before_cut":!reached?"interrupted_before_horizon":
            exit!=null?"exited_without_arrival":entry!=null?"active_at_cut":departure!=null?"waiting_for_incorporation":"scheduled_not_departed";
        String pending=null;
        if(status.equals("active_at_cut"))pending=Set.of("carro","moto").contains(row.get("family"))?
            cut-entry>3600?"prolonged_traffic_review_required":scheduled>=cut-3600&&departure!=null&&departure>=cut-3600?
            "recent_at_horizon":"recent_entry_old_request":"horizon_censored_no_private_duration_threshold";
        if(status.equals("waiting_for_incorporation"))pending="incorporation_wait";
        if(status.equals("exited_without_arrival"))pending="arrival_not_observed_review_required";
        r.put("status",status);r.put("pending_class",pending);return r;
    }
    @Override public synchronized void notifyAfterMobsim(AfterMobsimEvent e) {
        if(census==null)return;
        Path target=Path.of(e.getServices().getControlerIO().getIterationFilename(iteration,"simz1-day-census.jsonl.gz"));
        Path temp=target.resolveSibling(target.getFileName()+".tmp");var mapper=new ObjectMapper();
        try(var out=new BufferedWriter(new OutputStreamWriter(new GZIPOutputStream(Files.newOutputStream(temp,StandardOpenOption.CREATE_NEW)),StandardCharsets.UTF_8))) {
            for(var row:census.values()){var r=new LinkedHashMap<>(row);r.put("run_id",runId);r.put("iteration",iteration);r.put("policy",POLICY);
                r.put("cleanup_abort_events",cleanupAborts.getOrDefault(row.get("trip_id"),0L));out.write(mapper.writeValueAsString(r));out.newLine();}
        }catch(IOException ex){throw new UncheckedIOException(ex);}
        try {Files.move(temp,target,StandardCopyOption.ATOMIC_MOVE);}catch(IOException ex){throw new UncheckedIOException(ex);}
    }
    @Override public void notifyIterationEnds(IterationEndsEvent e){if(!reached()||census==null)throw new IllegalStateException("Fixed day not fully observed");}
}
