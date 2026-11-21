package gt.edu.uvg.sim.zona1;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPOutputStream;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.Event;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.events.*;
import org.matsim.core.controler.listener.*;
import org.matsim.core.events.handler.BasicEventHandler;

/** One compact event-leg row per departure, every iteration, independent of XML/score output. */
public final class TripTableExporter implements BasicEventHandler, IterationStartsListener,
        IterationEndsListener, ShutdownListener {
    public static final String[] COLUMNS = {"run_id","iteration","person_id","vehicle_id","trip_index","mode","profile",
        "departure","arrival","duration_seconds","status","abort","departure_link","arrival_link","unit","vehicle_ids"};
    private static final Set<String> TYPES = Set.of("departure","arrival","stuckAndAbort","vehicle enters traffic","vehicle leaves traffic","PersonEntersVehicle","vehicle aborts","TransitDriverStarts");
    private static final class Leg {
        final String person, mode, profile, origin;
        final int index;
        final double departure;
        final List<String> vehicles = new ArrayList<>();
        boolean boarded, trafficEntered, trafficLeft;
        Leg(String p, String m, String profile, String origin, int index, double time) {
            person=p;mode=m;this.profile=profile;this.origin=origin;this.index=index;departure=time;
        }
    }
    private static final class Terminal {
        final String status; final double time;
        final Set<String> sources = new HashSet<>();
        Terminal(String status, double time, String source) {
            this.status=status;this.time=time;sources.add(source);
        }
    }
    private final Scenario scenario;
    private final String runId;
    private final Controler controler;
    private final double horizon;
    private final Map<String,Leg> pending = new LinkedHashMap<>();
    private final Map<String,Integer> ordinals = new HashMap<>();
    private final Map<String,String> vehiclePeople = new HashMap<>();
    private final Map<String,Terminal> terminals = new HashMap<>(), closedVehicles = new HashMap<>();
    private final Map<String,Long> counts = new TreeMap<>(), anomalies = new TreeMap<>();
    private final Map<String,Long> reconciliation = new TreeMap<>(), censoring = new TreeMap<>();
    private final Map<String,String> internalTransitDrivers = new HashMap<>();
    private final Map<String,Long> internalTransitEvents = new TreeMap<>();
    private int iteration;
    private Path target, temporary;
    private CSVPrinter printer;
    private boolean dayCut;

    TripTableExporter(Scenario scenario, String runId, Controler controler) {
        this.scenario=scenario;this.runId=runId;this.controler=controler;
        horizon=SimZ1DayObservation.horizon(scenario.getConfig());
    }
    public static void install(Controler controler) {
        String id=System.getenv("SIMZ1_RUN_ID");
        install(controler,id == null || id.isBlank() ? "unmanaged-"+UUID.randomUUID() : id);
    }
    public static void install(Controler controler, String runId) {
        var exporter=new TripTableExporter(controler.getScenario(),runId,controler);
        controler.addControlerListener(exporter);
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() { addEventHandlerBinding().toInstance(exporter); }
        });
    }
    private static void add(Map<String,Long> map,String key) { map.merge(key,1L,Long::sum); }
    private void terminalAnomaly(Terminal terminal,double time,String missing,String source) {
        if (terminal!=null && !terminal.status.equals("completed") && terminal.time==time
                && !terminal.sources.contains(source)
                && (source.equals("stuckAndAbort") || source.equals("vehicle aborts"))
                && (terminal.sources.contains("stuckAndAbort") || terminal.sources.contains("vehicle aborts"))) {
            terminal.sources.add(source);add(reconciliation,"paired_terminal_events");return;
        }
        if (terminal==null && missing.equals("unmapped_vehicle_abort"))
            add(reconciliation,time>=horizon?"unmapped_vehicle_abort_at_horizon":"unmapped_vehicle_abort_before_horizon");
        add(anomalies,terminal!=null && terminal.status.equals("completed") ? "abort_after_arrival" :
            terminal!=null && terminal.time==time ? "duplicate_terminal_events" : missing);
    }
    private static String text(Map<String,String> a,String key,String fallback) {
        String value=a.get(key);return value == null || value.isBlank() ? fallback : value;
    }
    static String quote(String text) {
        StringBuilder b=new StringBuilder("\"");
        for (char c:text.toCharArray()) {
            switch(c) {
                case '"' -> b.append("\\\""); case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n"); case '\r' -> b.append("\\r"); case '\t' -> b.append("\\t");
                default -> { if(c<32)b.append(String.format(Locale.ROOT,"\\u%04x",(int)c)); else b.append(c); }
            }
        }
        return b.append('"').toString();
    }
    private static String jsonCounts(Map<String,Long> values) {
        return "{"+String.join(",",values.entrySet().stream().map(e->quote(e.getKey())+":"+e.getValue()).toList())+"}";
    }
    private String profile(String person) {
        var p=scenario.getPopulation().getPersons().get(org.matsim.api.core.v01.Id.createPersonId(person));
        if(p==null)throw new IllegalArgumentException("Trip person outside scenario: "+person);
        Object profile=p.getAttributes().getAttribute("effectiveVehicleType");
        if(profile==null)profile=p.getAttributes().getAttribute("simz1AgentType");
        if(profile==null)profile=p.getAttributes().getAttribute("drivingProfile");
        return profile==null ? "unknown" : profile.toString();
    }
    synchronized void begin(Path folder,int iteration) {
        if(printer!=null)throw new IllegalStateException("Unclosed compact iteration");
        pending.clear();ordinals.clear();vehiclePeople.clear();terminals.clear();closedVehicles.clear();counts.clear();anomalies.clear();
        internalTransitDrivers.clear();internalTransitEvents.clear();reconciliation.clear();censoring.clear();
        this.iteration=iteration;
        dayCut=false;
        target=folder.resolve(iteration+".simz1-trips.csv.gz");temporary=folder.resolve(iteration+".simz1-trips.csv.gz.tmp");
        try {
            Files.createDirectories(folder);
            printer=new CSVPrinter(new BufferedWriter(new OutputStreamWriter(new GZIPOutputStream(
                Files.newOutputStream(temporary,StandardOpenOption.CREATE_NEW)),StandardCharsets.UTF_8)),
                CSVFormat.DEFAULT.withHeader(COLUMNS));
        } catch(IOException e) { throw new UncheckedIOException(e); }
    }
    @Override public void notifyIterationStarts(IterationStartsEvent e) {
        begin(Path.of(controler.getControlerIO().getIterationPath(e.getIteration())),e.getIteration());
    }
    @Override public void handleEvent(Event e) {
        if("simz1DayCut".equals(e.getEventType())){dayCut=true;return;}
        if(TYPES.contains(e.getEventType()))accept(e.getAttributes());
    }
    synchronized void accept(Map<String,String> a) {
        if(printer==null)throw new IllegalStateException("Trip event outside iteration");
        String type=a.get("type"),person=a.get("person"),vehicle=a.get("vehicle");
        String actor=person!=null?person:vehicle;
        if (actor!=null && SimZ1Freight.applies(scenario.getPopulation().getPersons().get(org.matsim.api.core.v01.Id.createPersonId(actor)))) return;
        if(!TYPES.contains(type))return;
        double time=Double.parseDouble(a.get("time"));
        if(!Double.isFinite(time) || time<0)throw new IllegalArgumentException("Trip event without valid time: "+a);
        if(type.equals("TransitDriverStarts")) {
            // MATSim 15 emits this before the native driver's PersonDepartureEvent.
            // Its person is not a Monte Carlo demand member. Names are not evidence.
            String driver=a.get("driverId"),bus=a.get("vehicleId");
            if(driver==null || driver.isBlank() || !registeredTransitVehicle(bus))
                throw new IllegalArgumentException("Transit driver without registered fleet vehicle: "+a);
            if(scenario.getPopulation().getPersons().containsKey(org.matsim.api.core.v01.Id.createPersonId(driver)))
                throw new IllegalArgumentException("Native transit driver collides with demand person: "+driver);
            internalTransitDrivers.put(driver,bus);add(internalTransitEvents,type);return;
        }
        if(internalTransitDrivers.containsKey(person)) {
            if(vehicle!=null && !vehicle.equals(internalTransitDrivers.get(person)))
                throw new IllegalArgumentException("Native transit driver changed vehicle without TransitDriverStarts: "+a);
            add(internalTransitEvents,type);return;
        }
        if(registeredTransitVehicle(vehicle)) {
            if(!type.equals("vehicle aborts") && !type.equals("PersonEntersVehicle") && !type.equals("vehicle leaves traffic"))
                throw new IllegalArgumentException("Transit traffic event lacks a previously registered native driver: "+a);
            add(internalTransitEvents,type);return;
        }
        if(type.equals("vehicle aborts")) {
            person=vehiclePeople.get(vehicle);
            if(person==null) {
                terminalAnomaly(closedVehicles.get(vehicle),time,"unmapped_vehicle_abort",type);return;
            }
        }
        if(person==null || person.isBlank() || !Double.isFinite(time) || time<0)throw new IllegalArgumentException("Trip event without valid person/time: "+a);
        Leg leg=pending.get(person);
        if(type.equals("PersonEntersVehicle")) {
            // Scope is the current road-driver mode, never transit passengers.
            if(leg==null || !scenario.getConfig().qsim().getMainModes().contains(leg.mode))return;
            if(vehicle==null || vehicle.isBlank() || time<leg.departure)
                throw new IllegalArgumentException("Invalid driver boarding: "+a);
            bindVehicle(leg,vehicle);leg.boarded=true;add(reconciliation,"driver_boardings_observed");return;
        }
        if(type.equals("vehicle leaves traffic")) {
            if(leg!=null && leg.vehicles.contains(vehicle))leg.trafficLeft=true;
            return;
        }
        switch(type) {
            case "departure" -> {
                String mode=text(a,"legMode","unknown");
                if(leg!=null) {
                    if(leg.departure==time && leg.mode.equals(mode)){add(anomalies,"duplicate_departures");return;}
                    throw new IllegalArgumentException("Overlapping departures: "+person);
                }
                int index=ordinals.merge(person,1,Integer::sum);
                pending.put(person,new Leg(person,mode,profile(person),a.get("link"),index,time));
                terminals.remove(person);add(counts,"departures");
            }
            case "vehicle enters traffic" -> {
                if(vehicle==null || vehicle.isBlank())throw new IllegalArgumentException("Traffic entry without vehicle");
                if(leg==null){add(anomalies,"traffic_entry_without_departure");return;}
                if(time<leg.departure)throw new IllegalArgumentException("Traffic entry before departure");
                bindVehicle(leg,vehicle);leg.trafficEntered=true;leg.trafficLeft=false;
            }
            case "arrival" -> {
                if(leg==null) {
                    Terminal t=terminals.get(person);
                    add(anomalies,t!=null && t.status.equals("completed") && t.time==time ? "duplicate_arrivals" :
                        t!=null && !t.status.equals("completed") ? "arrival_after_abort" : "unmatched_arrivals");return;
                }
                if(time<leg.departure || !text(a,"legMode",leg.mode).equals(leg.mode))throw new IllegalArgumentException("Incompatible arrival: "+a);
                emit(leg,"completed",time,null,a.get("link"),type);pending.remove(person);
            }
            default -> {
                if(leg==null){terminalAnomaly(terminals.get(person),time,"unmatched_abort",type);return;}
                if(time<leg.departure)throw new IllegalArgumentException("Abort before departure");
                boolean censored=SimZ1DayObservation.enabled(scenario.getConfig())?dayCut&&time>=horizon:time>=horizon;
                String status=censored ? "censored":"aborted";
                emit(leg,status,null,time,null,type);pending.remove(person);
                if(censored)add(counts,"horizon_abort_events");
            }
        }
    }
    private boolean registeredTransitVehicle(String vehicle) {
        return vehicle!=null && scenario.getTransitVehicles().getVehicles()
            .containsKey(org.matsim.api.core.v01.Id.createVehicleId(vehicle));
    }
    private void bindVehicle(Leg leg,String vehicle) {
        String owner=vehiclePeople.get(vehicle);
        if(owner!=null && !owner.equals(leg.person))
            throw new IllegalArgumentException("Vehicle bound to two active drivers: "+vehicle);
        if(!leg.vehicles.contains(vehicle))leg.vehicles.add(vehicle);
        vehiclePeople.put(vehicle,leg.person);closedVehicles.remove(vehicle);
    }
    private void emit(Leg leg,String status,Double arrival,Double abort,String destination,String source) {
        try {
            printer.printRecord(runId,iteration,leg.person,leg.vehicles.isEmpty()?null:leg.vehicles.get(0),leg.index,
                leg.mode,leg.profile,leg.departure,arrival,arrival==null?null:arrival-leg.departure,status,abort,
                leg.origin,destination,"departure_arrival_leg","["+String.join(",",leg.vehicles.stream().map(TripTableExporter::quote).toList())+"]");
        } catch(IOException e) { throw new UncheckedIOException(e); }
        add(counts,"rows");add(counts,status);
        if(status.equals("censored"))add(censoring,leg.trafficLeft?"left_traffic_without_arrival":
            leg.trafficEntered?"entered_traffic_without_arrival":leg.boarded?"boarded_without_traffic_entry":"no_traffic_entry_evidence");
        Terminal terminal=new Terminal(status,arrival!=null?arrival:abort!=null?abort:horizon,source);
        terminals.put(leg.person,terminal);
        for(String vehicle:leg.vehicles){vehiclePeople.remove(vehicle);closedVehicles.put(vehicle,terminal);}
    }
    synchronized void finish() {
        try {
            for(Leg leg:pending.values())emit(leg,"censored",null,null,null,"end_of_observation");
            pending.clear();printer.close();printer=null;
            Path summary=target.resolveSibling(iteration+".simz1-trip-summary.json");
            Path summaryTmp=summary.resolveSibling(summary.getFileName()+".tmp");
            long total=counts.getOrDefault("rows",0L),completed=counts.getOrDefault("completed",0L);
            String json="{\"schema_version\":1,\"run_id\":"+quote(runId)+",\"iteration\":"+iteration+
                ",\"counts\":"+jsonCounts(counts)+",\"anomalies\":"+jsonCounts(anomalies)+
                ",\"terminal_reconciliation_version\":2,\"terminal_reconciliation\":"+jsonCounts(reconciliation)+
                ",\"censoring_breakdown\":"+jsonCounts(censoring)+
                ",\"demand_persons_N\":"+SimZ1Freight.privateCount(scenario)+
                ",\"configured_public_vehicles_B\":"+scenario.getTransitVehicles().getVehicles().size()+
                ",\"observed_internal_transit_drivers\":"+internalTransitDrivers.size()+
                ",\"internal_transit_events\":"+jsonCounts(internalTransitEvents)+
                ",\"completion_rate\":"+(total==0?"null":Double.toString((double)completed/total))+"}\n";
            Files.writeString(summaryTmp,json,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
            Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE);
            Files.move(summaryTmp,summary,StandardCopyOption.ATOMIC_MOVE);
        } catch(IOException e) { throw new UncheckedIOException(e); }
    }
    @Override public void notifyIterationEnds(IterationEndsEvent e) { finish(); }
    @Override public synchronized void notifyShutdown(ShutdownEvent e) {
        // An interrupted iteration stays .tmp and is never accepted as complete.
        if(printer!=null)try { printer.close();printer=null; } catch(IOException ex){throw new UncheckedIOException(ex);}
    }
}
