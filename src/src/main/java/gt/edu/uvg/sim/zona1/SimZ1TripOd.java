package gt.edu.uvg.sim.zona1;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URL;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.router.RoutingRequest;
import org.matsim.core.router.TripStructureUtils;

/** Private OD constraints belong to a trip, not to the car routing graph.
 * Reads the existing prepared manifest; never changes plans or preparation evidence. */
final class SimZ1TripOd {
    static final String ATTRIBUTE="simz1TripId", SCHEMA="simz1-private-gateway-trip-v1";
    private static final String ELEMENT=SimZ1TripOd.class.getName();
    private static final ObjectMapper JSON=new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
    private static final Map<String,String> CLASSES=Map.of("internal-internal","INTERNAL_INTERNAL",
        "internal-external","INTERNAL_EXTERNAL","external-internal","EXTERNAL_INTERNAL",
        "external-external","EXTERNAL_EXTERNAL_THROUGH");
    private final JsonNode spatial;
    private final Set<Id<Link>> interior, internal, crossings;
    private boolean plansBound;

    static IllegalArgumentException invalid(String detail) { return new IllegalArgumentException("private_od: "+detail); }
    static SimZ1TripOd shared(Scenario scenario) {
        synchronized (scenario) {
            var found=scenario.getScenarioElement(ELEMENT);
            if (found instanceof SimZ1TripOd od) return od;
            var od=load(scenario); scenario.addScenarioElement(ELEMENT,od); return od;
        }
    }
    private static SimZ1TripOd load(Scenario scenario) {
        try {
            URL context=scenario.getConfig().getContext();
            if (context==null || !"file".equals(context.getProtocol())) return new SimZ1TripOd(null);
            Path manifest=Path.of(new URL(context,"run-manifest.json").toURI());
            if (!Files.isRegularFile(manifest)) return new SimZ1TripOd(null);
            JsonNode doc=JSON.readTree(Files.readAllBytes(manifest)), spatial=doc.path("spatial_demand");
            if (!"balanced-gateway-v1".equals(spatial.path("mode").asText()) && !doc.has("balanced_od"))
                return new SimZ1TripOd(null); // Explicit compatibility with historical preparation modes.
            if (!"balanced-gateway-v1".equals(doc.path("balanced_od").path("variant").asText()) ||
                !"balanced-gateway-v1".equals(spatial.path("mode").asText())) throw invalid("manifest identity mismatch");
            Path access=checked(manifest.getParent(),doc.path("balanced_od").path("access_catalog"));
            if (!digest(access).equals(spatial.path("access_sha256").asText())) throw invalid("access identity mismatch");
            checkFile(scenario.getConfig().network().getInputFileURL(context),spatial.path("network_sha256").asText());
            checkFile(org.matsim.core.config.ConfigGroup.getInputFileURL(context,scenario.getConfig().network().getLaneDefinitionsFile()),spatial.path("lanes_sha256").asText());
            if (!SimZ1SequenceContract.SHA256.equals(spatial.path("sequence_contract_sha256").asText()))
                throw invalid("OSM sequence identity mismatch");
            JsonNode catalog=JSON.readTree(Files.readAllBytes(access));
            for (String table:List.of("entry_gateways","exit_gateways")) {
                if (catalog.path(table).size()!=spatial.path(table).size()) throw invalid("gateway catalogue size mismatch");
                for (var row:catalog.path(table)) {
                    var saved=spatial.path(table).path(row.path("anchor_link").asText());
                    for (String key:List.of("id","anchor_link","observation_link","crossing_link","link_ids"))
                        if (!Objects.equals(saved.get(key),row.get(key))) throw invalid("gateway catalogue mismatch: "+key);
                }
            }
            return new SimZ1TripOd(spatial);
        } catch (Exception e) { throw new IllegalArgumentException("private_od: cannot load prepared trip domain: "+e.getMessage(),e); }
    }
    private static String digest(Path path) throws Exception {
        var digest=MessageDigest.getInstance("SHA-256");
        try (var stream=Files.newInputStream(path)) {byte[] b=new byte[65536];int n;while((n=stream.read(b))!=-1)digest.update(b,0,n);}
        return HexFormat.of().formatHex(digest.digest());
    }
    private static void checkFile(URL url,String expected) throws Exception {
        if (url==null || !"file".equals(url.getProtocol()) || !expected.equals(digest(Path.of(url.toURI()))))
            throw invalid("effective network/lanes identity mismatch");
    }
    private static Path checked(Path root,JsonNode reference) throws Exception {
        Path path=root.resolve(reference.path("path").asText()).normalize();
        if (!path.startsWith(root) || !reference.path("sha256").asText().equals(digest(path))) throw invalid("artifact identity mismatch");
        return path;
    }
    // Package constructor also accepts explicitly synthetic catalogues in focal tests.
    SimZ1TripOd(JsonNode spatial) {
        this.spatial=spatial==null?null:spatial.deepCopy();
        if (spatial==null) {interior=internal=crossings=Set.of();return;}
        var inside=new HashSet<>(ids(spatial.path("allowed_links")));
        var cuts=new HashSet<Id<Link>>();
        for (String table:List.of("entry_gateways","exit_gateways")) for (var row:spatial.path(table)) {
            var chain=ids(row.path("link_ids")); var cut=Id.createLinkId(row.path("crossing_link").asText());
            int at=chain.indexOf(cut); // Catalogue chains are unique; this is NOT a traveled route occurrence.
            if (chain.size()<3 || new HashSet<>(chain).size()!=chain.size() || at<=0 || at>=chain.size()-1 || !cuts.add(cut))
                throw invalid("invalid gateway chain");
            // The verified catalogue classifies every chain: exterior, crossing, interior (or reverse).
            inside.removeAll(table.equals("entry_gateways")?chain.subList(0,at+1):chain.subList(at,chain.size()));
        }
        interior=Set.copyOf(inside);internal=Set.copyOf(ids(spatial.path("internal_links")));crossings=Set.copyOf(cuts);
        if (internal.isEmpty() || !interior.containsAll(internal)) throw invalid("inconsistent interior domain");
    }
    static List<Id<Link>> ids(JsonNode values) {
        if (!values.isArray()) throw invalid("missing link array");
        var result=new ArrayList<Id<Link>>();
        for (var v:values) {if(!v.isTextual() || v.asText().isBlank())throw invalid("invalid link ID");result.add(Id.createLinkId(v.asText()));}
        return List.copyOf(result);
    }
    private static JsonNode attribute(Person person,String key) {
        Object value=person.getAttributes().getAttribute(key);
        if (value==null) return JSON.nullNode();
        try {return JSON.readTree(value.toString());}catch(Exception e){throw invalid("malformed "+key);}
    }
    boolean requires(Person person) {
        if (person==null) return spatial!=null;
        if (SimZ1Freight.applies(person)) return false;
        if (spatial!=null) return true;
        var records=attribute(person,"simz1SpatialOD");
        if (records.isNull()) return false;
        if (!records.isObject() || records.isEmpty()) throw invalid("invalid or empty simz1SpatialOD");
        for (var r:records) if (!"synthetic_gateway_od".equals(r.path("metadata_source").asText())) return true;
        return false;
    }
    Contract forLeg(Person person,Leg leg) {
        if (!requires(person)) return null;
        if (person==null) throw invalid("missing private person identity");
        Object id=leg.getAttributes().getAttribute(ATTRIBUTE);
        if (!(id instanceof String)) throw invalid("missing leg simz1TripId");
        return contract(person,(String)id);
    }
    synchronized void bindPlans(Scenario scenario) {
        if (plansBound) return;
        for (Person person:scenario.getPopulation().getPersons().values()) {
            if (!requires(person)) continue;
            for (Plan plan:person.getPlans()) for (var trip:TripStructureUtils.getTrips(plan)) {
                if (trip.getLegsOnly().size()!=1) continue;
                Object id=trip.getLegsOnly().get(0).getAttributes().getAttribute(ATTRIBUTE);
                // Only carry the existing ID into MATSim's request attributes. Plan clones inherit it.
                // No route/demand serialization or trip identity is generated here.
                var attributes=trip.getOriginActivity().getAttributes();
                if (id instanceof String && attributes.getAttribute(ATTRIBUTE)==null) attributes.putAttribute(ATTRIBUTE,id);
            }
        }
        plansBound=true;
    }
    Contract forRequest(RoutingRequest request) {
        Person person=request.getPerson();
        if (!requires(person)) return null;
        if (person==null) throw invalid("missing private person identity");
        // MATSim 15 PlanRouter passes the ORIGIN ACTIVITY attributes, not the leg attributes.
        // bindPlans carries the leg ID to that activity before native routing (empty attributes
        // otherwise use a new LazyAllocationAttributes wrapper on every getAttributes call).
        // Use object identity in the actual plan being routed, including nonselected plan copies.
        // Never guess a trip from equal links, departure time, or the first matching occurrence.
        var matches=new ArrayList<Leg>();
        for (Plan plan:person.getPlans()) for (var trip:TripStructureUtils.getTrips(plan))
            if (trip.getOriginActivity().getAttributes()==request.getAttributes()) {
                if (trip.getLegsOnly().size()!=1 || !Objects.equals(trip.getDestinationActivity().getLinkId(),request.getToFacility().getLinkId()))
                    throw invalid("inconsistent native trip request");
                matches.add(trip.getLegsOnly().get(0));
            }
        Object explicit=request.getAttributes().getAttribute(ATTRIBUTE);
        Contract result;
        if (matches.size()==1) {
            result=forLeg(person,matches.get(0));
            if (explicit!=null && !result.tripId.equals(explicit)) throw invalid("request/leg trip identity mismatch");
        } else if (matches.isEmpty() && explicit instanceof String) result=contract(person,(String)explicit);
        else throw invalid("missing or ambiguous native trip identity matches="+matches.size()+" plans="+person.getPlans().size());
        if (!result.origin.equals(request.getFromFacility().getLinkId()) || !result.destination.equals(request.getToFacility().getLinkId()))
            throw invalid("request endpoints differ from trip");
        return result;
    }
    private Contract contract(Person person,String tripId) {
        if (spatial==null) throw invalid("missing prepared domain for required trip "+tripId);
        var record=attribute(person,"simz1SpatialOD").path(tripId);
        if (!record.isObject() || !SCHEMA.equals(record.path("metadata_source").asText())) throw invalid("missing trip metadata "+tripId);
        JsonNode identity=null;
        var trips=attribute(person,"simz1Trips");
        if (!trips.isArray()) throw invalid("missing trip identity array");
        for (var row:trips) if (tripId.equals(row.path("id").asText())) {
            if(identity!=null)throw invalid("duplicate trip identity");identity=row;
        }
        if (identity==null || !Objects.equals(identity.get("origin_link"),record.get("origin_link")) ||
            !Objects.equals(identity.get("destination_link"),record.get("destination_link"))) throw invalid("trip identity/endpoints mismatch");
        int ordinal=identity.path("index").asInt();
        if (!identity.path("index").isIntegralNumber() || ordinal<1 ||
            !tripId.equals(person.getId()+":trip:"+String.format(Locale.ROOT,"%04d",ordinal)))
            throw invalid("trip/person/ordinal mismatch");
        String kind=record.path("od_type").asText();
        if (!Objects.equals(CLASSES.get(kind),record.path("od_class").asText()) ||
            !"observed_z1_and_declared_anchors_only".equals(record.path("scope").asText()) ||
            !record.path("door_to_door_seconds").isNull() || !record.path("minimum_gap_m").isNumber() ||
            record.path("minimum_gap_m").asDouble()!=.10 || !record.path("body_length_m").isNumber() ||
            !Double.isFinite(record.path("body_length_m").asDouble()) ||
            !(record.path("body_length_m").asDouble()>0)) throw invalid("inconsistent private class/scope/dimensions");
        var entry=gateway(record,"origin","entry",kind.startsWith("external"));
        var exit=gateway(record,"destination","exit",kind.endsWith("external"));
        var result=new Contract(tripId,Id.createLinkId(record.path("origin_link").asText()),
            Id.createLinkId(record.path("destination_link").asText()),entry,exit);
        String issue=result.validate(ids(record.path("route_link_ids")));
        if (issue!=null) throw invalid("inconsistent prepared route: "+issue);
        return result;
    }
    private List<Id<Link>> gateway(JsonNode record,String side,String role,boolean external) {
        String link=record.path(side+"_link").asText();
        var row=spatial.path(role+"_gateways").path(link);
        if (external && row.isMissingNode() || !external && (!internal.contains(Id.createLinkId(link)) ||
            side.equals("origin") && !spatial.path("internal_origins").has(link))) throw invalid("invalid "+side+" domain");
        for (String key:List.of("gateway","zone","observation_link")) {
            String expected=external?(key.equals("gateway")?link:row.path(key.equals("zone")?"id":key).asText()):null;
            requireValue(record,side+"_"+key,expected);
        }
        requireValue(record,role+"_crossing_link",external?row.path("crossing_link").asText():null);
        return external?ids(row.path("link_ids")):List.of();
    }
    private static void requireValue(JsonNode record,String key,String expected) {
        var value=record.get(key);
        if (value==null || !Objects.equals(value.isNull()?null:value.asText(),expected)) throw invalid("inconsistent "+key);
    }
    record Progress(int entry,int exit,int crossings,boolean interior) { }
    final class Contract {
        final String tripId;
        final Id<Link> origin,destination;
        final List<Id<Link>> entry,exit,expectedCrossings;
        final int exitCut;
        Contract(String tripId,Id<Link> origin,Id<Link> destination,List<Id<Link>> entry,List<Id<Link>> exit) {
            this.tripId=tripId;this.origin=origin;this.destination=destination;this.entry=entry;this.exit=exit;
            var expected=new ArrayList<Id<Link>>();
            for(var chain:List.of(entry,exit))for(var id:chain)if(crossings.contains(id))expected.add(id);
            expectedCrossings=List.copyOf(expected);exitCut=exit.isEmpty()?-1:exit.indexOf(expected.get(expected.size()-1));
        }
        Progress advance(Progress state,Id<Link> next) {
            if (state==null || (!interior.contains(next) && !entry.contains(next) && !exit.contains(next))) return null;
            int e=state.entry(), x=state.exit(), c=state.crossings();
            if (e<entry.size()) {if(!next.equals(entry.get(e)))return null;e++;}
            if (crossings.contains(next)) {
                if(c>=expectedCrossings.size() || !next.equals(expectedCrossings.get(c)))return null;c++;
            }
            if (!exit.isEmpty()) {
                if (x>exitCut) {if(x==exit.size() || !next.equals(exit.get(x)))return null;x++;}
                else {
                    x=next.equals(exit.get(x))?x+1:(next.equals(exit.get(0))?1:0);
                    if (next.equals(exit.get(exitCut)) && x!=exitCut+1) return null;
                }
            }
            return new Progress(e,x,c,state.interior()||internal.contains(next));
        }
        Progress progress(List<Id<Link>> prefix) {
            if (prefix==null || prefix.isEmpty() || !origin.equals(prefix.get(0)))return null;
            Progress state=new Progress(0,0,0,false);
            for(var next:prefix){state=advance(state,next);if(state==null)return null;}return state;
        }
        boolean complete(Progress state) {
            return state!=null && state.entry()==entry.size() && state.exit()==exit.size() &&
                state.crossings()==expectedCrossings.size() && state.interior();
        }
        String validate(List<Id<Link>> route) {
            if (route==null || route.isEmpty() || !origin.equals(route.get(0)) || !destination.equals(route.get(route.size()-1)))
                return "private_od_endpoints trip="+tripId;
            return complete(progress(route))?null:"private_od_chain_or_domain trip="+tripId;
        }
    }
}
