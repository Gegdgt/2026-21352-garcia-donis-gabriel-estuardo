package gt.edu.uvg.sim.zona1;

import java.util.*;
import com.fasterxml.jackson.databind.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Person;

/** Opt-in experiment audit. It cannot grant admission, move or remove an actor. */
final class SimZ1FreightCompletion {
    static final String POLICY="freight-close-plus3600-v1", HISTORICAL="nominal-residence-v2";
    static final String TOLERATED_ENTRY_POLICY="freight-entry-and-completion-close-plus3600-v2";
    static final String NOMINAL_ENTRY="original_assigned_nominal_window_only";
    static final String TOLERATED_ENTRY="assigned_window_close_plus3600_inclusive";
    static final String ATTRIBUTE="simz1FreightCompletionPolicy", GEOMETRY="simz1FreightGateway";
    static final double[][] WINDOWS={{0,18000},{32400,57600},{75600,104400}};
    record Window(double start,double close) { double deadline(){return close+3600;} }
    static Window assigned(double departure) {
        if(Double.isFinite(departure)&&departure<86400)for(var w:WINDOWS)
            if(w[0]<=departure&&departure<w[1])return new Window(w[0],w[1]);
        throw new IllegalArgumentException("Invalid original freight scheduled window");
    }
    static String classify(double planned,Double entry,Double exit,Double arrival,boolean bodyClear,boolean aborted,boolean nominalViolation) {
        return classify(POLICY,planned,entry,exit,arrival,bodyClear,aborted,nominalViolation);
    }
    static boolean experimental(String policy) {return POLICY.equals(policy)||TOLERATED_ENTRY_POLICY.equals(policy);}
    static boolean entryPermitted(String policy,double planned,double entry) {
        var w=assigned(planned);
        if(!experimental(policy))throw new IllegalArgumentException("No experimental freight entry policy: "+policy);
        return Double.isFinite(entry)&&entry>=w.start()&&entry>=planned-1.01&&
            (POLICY.equals(policy)?entry<w.close():entry<=w.deadline());
    }
    static String classify(String policy,double planned,Double entry,Double exit,Double arrival,boolean bodyClear,boolean aborted,boolean nominalViolation) {
        var w=assigned(planned);
        for(var value:Arrays.asList(entry,exit,arrival))if(value!=null&&!Double.isFinite(value))return "technical_physical_error";
        if(entry!=null&&!entryPermitted(policy,planned,entry))return "technical_physical_error";
        if(aborted||entry==null||exit==null||arrival==null||!bodyClear)return "pending_not_evaluable";
        if(entry<planned-1.01||exit<entry||arrival<exit)return "technical_physical_error";
        return !nominalViolation&&arrival<w.close?"nominal":arrival<=w.deadline()?"tolerated":"excess_tolerance";
    }
    static void requirePolicy(String policy) {
        if(!Set.of(POLICY,TOLERATED_ENTRY_POLICY,HISTORICAL).contains(policy))throw new IllegalArgumentException("Unknown freight completion policy");
        if(policy.equals(HISTORICAL))return;
        boolean toleratedEntry=TOLERATED_ENTRY_POLICY.equals(policy);
        try(var stream=SimZ1FreightCompletion.class.getResourceAsStream(toleratedEntry?"/simz1/freight-entry-completion-v2.json":"/simz1/freight-completion-v1.json")) {
            var doc=new ObjectMapper().readTree(Objects.requireNonNull(stream));
            if(!policy.equals(doc.path("version").asText())||doc.path("tolerance_seconds").asInt()!=3600||
                    !doc.path("deadline_inclusive").asBoolean()||doc.path("observation_end_seconds").asInt()!=(toleratedEntry?86400:108000)||
                    !(toleratedEntry?TOLERATED_ENTRY:NOMINAL_ENTRY).equals(doc.path("entry_policy").asText())||
                    doc.path("demand_end_seconds_exclusive").asInt()!=86400||!doc.path("nominal_windows_seconds").equals(new ObjectMapper().readTree("[[0,18000],[32400,57600],[75600,104400]]")))
                throw new IllegalArgumentException("Freight completion resource mismatch");
            if(toleratedEntry&&(!"simz1-freight-completion-policy".equals(doc.path("schema").asText())||
                    !"synthetic_experiment_not_legal_permission".equals(doc.path("assumption_status").asText())||
                    !"original_roster_planned_departure".equals(doc.path("window_assignment").asText())||
                    !doc.path("entry_deadline_equals_completion_deadline").asBoolean()||
                    !doc.path("nominal_violation_retained").asBoolean()||!doc.path("deadline_does_not_interrupt_qsim").asBoolean()||
                    !doc.has("historical_runs_reinterpreted")||!doc.path("historical_runs_reinterpreted").isBoolean()||doc.path("historical_runs_reinterpreted").asBoolean()||
                    !doc.path("completion_requires").equals(new ObjectMapper().readTree("[\"native_arrival\",\"traffic_exit\",\"native_body_plus_0.10m_clearance\"]"))||
                    !"fixed-day-24h-v1".equals(doc.path("observation_policy").asText())||
                    !"retain_native_fifo_wait_until_normal_day_census_and_cleanup".equals(doc.path("expired_origin_behavior").asText())))
                throw new IllegalArgumentException("Freight entry/completion resource mismatch");
        } catch(Exception ex){throw new IllegalArgumentException("Cannot validate freight completion policy",ex);}
    }
    /** Independent check of the native ledger lower bound, in route coordinates. */
    static final class Clearance {
        final Map<String,JsonNode> geometry=new HashMap<>();
        final Map<String,Map<String,String>> domains=new HashMap<>(),reservations=new HashMap<>();
        final Map<String,Map<String,Object>> progress=new HashMap<>(),proofs=new HashMap<>();
        void add(Person person) {
            try {
                var value=Objects.toString(person.getAttributes().getAttribute(GEOMETRY),null);
                var g=new ObjectMapper().readTree(Objects.requireNonNull(value));
                if(g.path("minimum_gap_m").asDouble(-1)!=.1||g.path("body_length_m").asDouble(-1)!=8||!g.has("route_link_start_m"))
                    throw new IllegalArgumentException("Missing freight native geometry");
                for(String key:List.of("entry_distance_from_route_start_m","exit_distance_from_route_start_m"))
                    if(!g.path(key).isNumber()||!Double.isFinite(g.path(key).asDouble()))throw new IllegalArgumentException("Missing freight crossing distance: "+key);
                if(!g.path("route_link_start_m").isObject()||g.path("route_link_start_m").isEmpty())throw new IllegalArgumentException("Missing route coordinates");
                for(var coordinate:g.path("route_link_start_m"))if(!coordinate.isNumber()||!Double.isFinite(coordinate.asDouble()))throw new IllegalArgumentException("Invalid route coordinate");
                geometry.put(person.getId().toString(),g);
            }catch(Exception ex){throw new IllegalArgumentException("Invalid freight native gateway contract: "+person.getId(),ex);}
        }
        void reset(){domains.clear();reservations.clear();progress.clear();proofs.clear();}
        static double number(Map<String,String> a,String key) {
            double v=Double.parseDouble(Objects.requireNonNull(a.get(key),key));
            if(!Double.isFinite(v))throw new IllegalStateException("Nonfinite freight ledger: "+key);return v;
        }
        void consume(Event event) {
            var a=event.getAttributes();var kind=event.getEventType();
            if(kind.equals("simz1OccupancyDomain")&&!geometry.isEmpty()) {
                if(domains.putIfAbsent(a.get("link"),Map.copyOf(a))!=null)throw new IllegalStateException("Duplicate freight domain");return;
            }
            var id=a.getOrDefault("person",a.get("vehicle"));var g=geometry.get(id);if(g==null)return;
            if(kind.equals("simz1OccupancyReservation")) {
                var action=a.get("action");if("WAIT".equals(action))return;
                if("EXIT".equals(action)){reservations.remove(id);progress.remove(id);return;}
                if(!Set.of("ENTER","TRANSFER").contains(action)||Math.abs(number(a,"bodyLengthMeters")-8)>1e-7||Math.abs(number(a,"footprintMeters")-8.1)>1e-7)
                    throw new IllegalStateException("Invalid freight body reservation");
                reservations.put(id,Map.copyOf(a));progress.remove(id);
            } else if(kind.equals("simz1OccupancyProgress")) {
                var r=reservations.get(id);if(r==null||!Objects.equals(r.get("corridor"),a.get("corridor")))throw new IllegalStateException("Missing freight reservation");
                String link=a.get("link"),anchor=link;var domain=domains.get(link);
                if(domain==null||!Objects.equals(domain.get("corridor"),r.get("corridor"))) {
                    var path=Arrays.asList(r.getOrDefault("exitLinks",r.getOrDefault("passageLinks","")).split(","));
                    if(!path.contains(link))throw new IllegalStateException("Freight outside reserved passage");
                    anchor="boundary_exit".equals(r.get("passageKind"))?r.get("exitFromLink"):r.get("receiptLink");domain=domains.get(anchor);
                }
                if(domain==null||!Objects.equals(domain.get("corridor"),r.get("corridor"))||!g.path("route_link_start_m").has(anchor))throw new IllegalStateException("Missing freight coordinate reference");
                double front=g.path("route_link_start_m").path(anchor).asDouble()-number(domain,"linkOffsetMeters")+number(a,"modeledFrontLowerBoundMeters");
                progress.put(id,Map.of("front_from_route_start_m",front,"time",event.getTime(),"anchor_link",anchor));
            } else if(kind.equals("vehicle enters traffic")||kind.equals("vehicle leaves traffic")||kind.equals("arrival")) {
                var proof=progress.get(id);if(proof==null||!reservations.containsKey(id))throw new IllegalStateException("Freight terminal lacks native body evidence: "+id);
                double front=(double)proof.get("front_from_route_start_m");
                if(kind.equals("vehicle enters traffic")) {
                    if(front>g.path("entry_distance_from_route_start_m").asDouble()+1e-7)throw new IllegalStateException("Freight insertion beyond entry");
                } else {
                    double gap=front-8.1-g.path("exit_distance_from_route_start_m").asDouble();
                    if(gap < -1e-7)throw new IllegalStateException("Freight body and gap have not cleared perimeter: "+id);
                    var saved=new LinkedHashMap<String,Object>(proof);saved.put("rear_plus_gap_clearance_m",gap);saved.put("minimum_gap_m",.1);saved.put("observed_terminal_time",event.getTime());proofs.put(id,saved);
                }
            }
        }
    }
}
