package gt.edu.uvg.sim.zona1;

import java.time.LocalDate;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.TransitDriverStartsEvent;
import org.matsim.api.core.v01.events.handler.PersonArrivalEventHandler;
import org.matsim.api.core.v01.events.handler.TransitDriverStartsEventHandler;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.mobsim.qsim.interfaces.MobsimVehicle;
import org.matsim.core.mobsim.qsim.pt.*;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesToLinkAssignment;
import org.matsim.lanes.LanesUtils;
import org.matsim.pt.*;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.utils.objectattributes.attributable.Attributable;
import org.matsim.vehicles.Vehicle;

/** Opt-in, fixed native fleet. Never changes N, network geometry, or historical schedules. */
public final class SimZ1TransitFleet {
    private static final String PREFIX = "simz1:";
    private static final double EPS = 1e-7;
    private SimZ1TransitFleet() { }

    public record Duty(TransitLine line, TransitRoute route, Departure departure,
                       double endTime, double terminalSeconds, double turnaroundSeconds) {
        public double readyTime() { return endTime + terminalSeconds + turnaroundSeconds; }
        public String key() { return line.getId()+"/"+route.getId()+"/"+departure.getId(); }
    }
    public record Prepared(int roadPersonsN, int configuredFleetB, int scheduledExpeditions,
                           Set<Id<Link>> domainLinks, String domainScope,
                           Map<Id<Vehicle>, List<Duty>> duties) { }

    private static IllegalArgumentException invalid(String text) {
        return new IllegalArgumentException("TRANSIT_INVALID: " + text);
    }
    private static String required(Attributable item, String key) {
        Object value = item.getAttributes().getAttribute(PREFIX + key);
        if (value == null || value.toString().isBlank()) throw invalid("missing " + PREFIX + key);
        return value.toString();
    }
    private static void requireValue(Attributable item, String key, String expected) {
        if (!expected.equals(required(item, key))) throw invalid(key + " must be " + expected);
    }
    private static double seconds(Attributable item, String key) {
        double value;
        try { value = Double.parseDouble(required(item, key)); }
        catch (NumberFormatException error) { throw invalid(key + " is not numeric"); }
        if (!Double.isFinite(value) || value < 0) throw invalid(key + " must be finite and nonnegative");
        return value;
    }
    private static void count(Attributable item, String key, int expected) {
        if (seconds(item, key) != expected) throw invalid(key + " does not match loaded data: " + expected);
    }
    private static void positive(double value, String label) {
        if (!Double.isFinite(value) || value <= 0) throw invalid("invalid " + label);
    }

    /** Read-only preflight over MATSim objects and, for production, a bounded local catalog; no Controler/QSim. */
    public static Prepared validate(Scenario scenario) {
        if (!scenario.getConfig().transit().isUseTransit()) return null;
        if (!scenario.getConfig().transit().isUsingTransitInMobsim())
            throw invalid("usingTransitInMobsim=false is unsupported");
        // MATSim 15 DefaultTransitDriverAgentFactory uses car as its internal driving leg mode.
        if (!scenario.getConfig().qsim().getMainModes().contains("car") ||
            scenario.getConfig().transit().getTransitModes().contains("car"))
            throw invalid("MATSim 15 native transit driver requires car mainMode, separate from passenger transitModes");
        if (scenario.getConfig().qsim().isRemoveStuckVehicles())
            throw invalid("removeStuckVehicles must remain false; an unavailable bus is not replaced");
        var schedule = scenario.getTransitSchedule();
        requireValue(schedule, "fleetSchema", "fixed-fleet-v1");
        required(schedule, "scenarioVersion");
        LocalDate.parse(required(schedule, "serviceDate"));
        requireValue(schedule, "passengersModeled", "false");
        String purpose = required(schedule, "purpose");
        boolean synthetic = "synthetic_fixture".equals(purpose);
        boolean weekday = "weekday_scenario_v2".equals(purpose);
        requireValue(schedule, "minimumTurnPolicy", weekday ? "delay_until_ready_v2" : "reject_on_actual_violation");
        if (!synthetic && !weekday && !"production".equals(purpose)) throw invalid("unknown purpose " + purpose);
        requireValue(schedule, "domainApproved", Boolean.toString(!synthetic && !weekday));
        requireValue(schedule, "domainSynthetic", Boolean.toString(synthetic));
        required(schedule, "domainSource");
        var domain = new LinkedHashSet<Id<Link>>();
        for (String token : required(schedule, "domainLinks").trim().split("\\s+")) {
            var id = Id.createLinkId(token);
            if (!scenario.getNetwork().getLinks().containsKey(id) || !domain.add(id))
                throw invalid("missing or duplicate domain link " + token);
        }
        if (weekday) validateWeekdayPolicy(scenario);
        else if (!synthetic) validateCatalogFile(scenario, domain);
        int n = SimZ1Freight.privateCount(scenario);
        if (n < 1) throw invalid("road demand N must be positive; B is independent of N");
        count(schedule, "monteCarloPersons", n);
        for (var person : scenario.getPopulation().getPersons().values()) {
            for (var plan : person.getPlans()) for (var element : plan.getPlanElements())
                if (element instanceof Leg leg && scenario.getConfig().transit().getTransitModes().contains(leg.getMode()))
                    throw invalid("passenger plan unsupported in no-passenger fleet: " + person.getId());
        }
        var vehicles = scenario.getTransitVehicles().getVehicles();
        count(schedule, "configuredFleetSize", vehicles.size());
        if (vehicles.isEmpty()) throw invalid("an enabled fleet must explicitly configure B > 0");
        var internalDriverIds = new HashSet<Id<Person>>();
        for (var vehicle : vehicles.values()) {
            if (scenario.getVehicles().getVehicles().containsKey(vehicle.getId()) ||
                scenario.getPopulation().getPersons().containsKey(Id.createPersonId(vehicle.getId())))
                throw invalid("public vehicle ID collides with road demand " + vehicle.getId());
            var type = vehicle.getType();
            positive(type.getLength(), "bus length"); positive(type.getWidth(), "bus width");
            positive(type.getPcuEquivalents(), "bus PCU"); positive(type.getMaximumVelocity(), "bus maximum velocity");
            if (!"bus".equals(type.getNetworkMode())) throw invalid("public VehicleType must use bus networkMode");
            var driverId = Id.createPersonId("pt_" + vehicle.getId() + "_" + type.getId());
            if (scenario.getPopulation().getPersons().containsKey(driverId) || !internalDriverIds.add(driverId))
                throw invalid("internal driver ID collides with N or another bus: " + driverId);
        }
        var duties = new TreeMap<Id<Vehicle>, List<Duty>>(Comparator.comparing(Object::toString));
        vehicles.keySet().forEach(id -> duties.put(id, new ArrayList<>()));
        var departureIds = new HashSet<Id<Departure>>();
        var allAssigned = new HashSet<Id<Vehicle>>();
        int expeditions = 0;
        for (var line : schedule.getTransitLines().values()) {
            required(line, "serviceId");
            requireValue(line, "productionEnabled", Boolean.toString(!synthetic && !weekday));
            var assigned = new HashSet<Id<Vehicle>>();
            for (String token : required(line, "assignedVehicleIds").trim().split("\\s+")) {
                var id = Id.createVehicleId(token);
                if (!vehicles.containsKey(id)) throw invalid("unconfigured bus assigned to service: " + token);
                if (!assigned.add(id)) throw invalid("duplicate bus assignment within service: " + token);
            }
            allAssigned.addAll(assigned);
            for (var route : line.getRoutes().values()) {
                requireValue(route, "routePolicy", "fixed-v1");
                if (!"bus".equals(route.getTransportMode())) throw invalid("route mode must be bus: " + route.getId());
                String runningWay = required(route, "runningWay");
                if (!Set.of("mixed", "segregated").contains(runningWay)) throw invalid("unknown runningWay");
                if (route.getRoute() == null) throw invalid("missing directed route " + route.getId());
                var links = SimZ1RouteSafety.full(route.getRoute());
                Link previous = null;
                for (var linkId : links) {
                    var link = scenario.getNetwork().getLinks().get(linkId);
                    if (link == null || !link.getAllowedModes().contains("bus")) throw invalid("missing bus access: " + linkId);
                    if (!domain.contains(linkId)) throw invalid("blocked_exterior_runtime_not_implemented: " + linkId);
                    if ("segregated".equals(runningWay) && link.getAllowedModes().contains("car"))
                        throw invalid("segregated service requires separate bus-only links: " + linkId);
                    if (previous != null && (previous.getToNode() != link.getFromNode() || !laneAllows(scenario, previous, link)))
                        throw invalid("disconnected or forbidden bus movement: " + previous.getId() + " -> " + linkId);
                    previous = link;
                }
                double finalOffset = validateStops(scenario, route, links);
                for (var departure : route.getDepartures().values()) {
                    if (!departureIds.add(departure.getId())) throw invalid("departure IDs must be globally unique: " + departure.getId());
                    if (departure.getVehicleId() == null || !duties.containsKey(departure.getVehicleId()))
                        throw invalid("unconfigured bus/insufficient fleet: " + departure.getId());
                    if (!assigned.contains(departure.getVehicleId()))
                        throw invalid("departure uses bus not assigned to its service: " + departure.getId());
                    double start = departure.getDepartureTime();
                    if (!Double.isFinite(start) || start < 0) throw invalid("invalid departure time");
                    double end = seconds(departure, "endTimeSeconds");
                    if (weekday) {
                        double opens=seconds(line,"opensSeconds"), closes=seconds(line,"closesSeconds");
                        double cutoff=line.getAttributes().getAttribute(PREFIX+"departureCutoffSeconds")==null
                            ? closes : Math.min(closes,seconds(line,"departureCutoffSeconds"));
                        if (start<opens || start>=cutoff || end>closes+EPS) throw invalid("departure outside weekday operating window");
                        if (!Set.of("exterior","terminal").contains(required(route,"transferKind"))) throw invalid("unknown boundary transfer");
                        required(route,"transferBasis");
                        if (seconds(route,"transferSeconds")<=0 || Math.abs(seconds(route,"transferSeconds")-seconds(departure,"turnaroundSeconds"))>EPS)
                            throw invalid("missing explicit positive boundary/terminal time");
                    }
                    if (Math.abs(end - start - finalOffset) > EPS) throw invalid("endTimeSeconds must equal departure + final departureOffset");
                    duties.get(departure.getVehicleId()).add(new Duty(line, route, departure, end,
                        seconds(departure, "terminalSeconds"), seconds(departure, "turnaroundSeconds")));
                    expeditions++;
                }
            }
        }
        if (!allAssigned.equals(vehicles.keySet())) throw invalid("every configured bus, including reserves, needs an explicit service assignment");
        if (expeditions == 0) throw invalid("no departures on serviceDate; leave transit disabled");
        count(schedule, "scheduledExpeditions", expeditions);
        var immutable = new LinkedHashMap<Id<Vehicle>, List<Duty>>();
        for (var entry : duties.entrySet()) {
            entry.getValue().sort(Comparator.comparingDouble(d -> d.departure().getDepartureTime()));
            Duty previous = null;
            for (var duty : entry.getValue()) {
                if (previous != null) {
                    if (duty.departure().getDepartureTime() + EPS < previous.readyTime())
                        throw invalid("overlapping duty or insufficient terminal/return time: " + entry.getKey());
                    if (!weekday && !previous.route().getRoute().getEndLinkId().equals(duty.route().getRoute().getStartLinkId()))
                        throw invalid("blocked_exterior_runtime_not_implemented or missing explicit terminal movement: " + entry.getKey());
                }
                previous = duty;
            }
            immutable.put(entry.getKey(), List.copyOf(entry.getValue()));
        }
        return new Prepared(n, vehicles.size(), expeditions, Set.copyOf(domain),
            weekday ? "computational_network" : synthetic ? "synthetic_fixture" : "approved_domain", Collections.unmodifiableMap(immutable));
    }

    /** Versioned scenario gate: never relabels a dated candidate catalog as verified production. */
    private static void validateWeekdayPolicy(Scenario scenario) {
        var schedule=scenario.getTransitSchedule();
        try {
            var url=scenario.getConfig().transit().getTransitScheduleFileURL(scenario.getConfig().getContext());
            if (url==null || !"file".equals(url.getProtocol())) throw invalid("weekday policy requires local schedule");
            Path parent=Path.of(url.toURI()).toRealPath().getParent();
            Path relative=Path.of(required(schedule,"weekdayPolicyFile"));
            Path file=parent.resolve(relative).normalize().toRealPath();
            if (relative.isAbsolute() || !file.startsWith(parent)) throw invalid("unsafe weekday policy path");
            byte[] bytes;
            try (var input=Files.newInputStream(file)) { bytes=input.readNBytes(1_000_001); }
            if (bytes.length>1_000_000) throw invalid("weekday policy exceeds 1MB");
            if (!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(required(schedule,"weekdayPolicySha256")))
                throw invalid("weekday policy hash mismatch");
            var mapper=new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
            JsonNode p=mapper.readTree(bytes);
            if (!"simz1-weekday-transit-v2".equals(p.path("schema_version").asText()) ||
                !p.path("scenario_assumptions_acknowledged").asBoolean() ||
                !p.path("route_assumptions_accepted").asBoolean() || p.path("passengers_modeled").asBoolean(true) ||
                p.path("empirical_calibration").asBoolean(true) || !"computational_network".equals(p.path("domain_scope").asText()) ||
                !"no_new_departures_finish_active".equals(p.path("closing_policy").asText()) ||
                !"timed_off_network_v2".equals(p.path("outside_policy").asText())) throw invalid("invalid weekday assumptions contract");
            if (!p.path("service_date").asText().equals(required(schedule,"serviceDate")) ||
                LocalDate.parse(p.path("service_date").asText()).getDayOfWeek().getValue()>5) throw invalid("weekday date mismatch");
            if (p.path("road_demand_persons").asInt(-1)!=SimZ1Freight.privateCount(scenario) ||
                p.path("configured_fleet_size").asInt(-1)!=scenario.getTransitVehicles().getVehicles().size()) throw invalid("weekday N/B mismatch");
            Path routes=parent.resolve(p.path("route_bundle_file").asText()).normalize().toRealPath();
            if (!routes.startsWith(parent) || Files.size(routes)>8_000_000) throw invalid("unsafe route bundle");
            if (!HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(routes))).equals(p.path("source_bundle_sha256").asText()))
                throw invalid("weekday route bundle hash mismatch");
        } catch (IllegalArgumentException error) { throw error; }
        catch (Exception error) { throw invalid("weekday policy: "+error.getMessage()); }
    }

    private static void validateCatalogFile(Scenario scenario, Set<Id<Link>> domain) {
        var schedule = scenario.getTransitSchedule();
        String file = required(schedule, "catalogFile"), expectedHash = required(schedule, "catalogSha256");
        if (!expectedHash.matches("[0-9a-f]{64}")) throw invalid("catalogSha256 must be a lowercase SHA256 digest");
        try {
            var scheduleUrl = scenario.getConfig().transit().getTransitScheduleFileURL(scenario.getConfig().getContext());
            if (scheduleUrl == null || !"file".equalsIgnoreCase(scheduleUrl.getProtocol()))
                throw invalid("catalog requires a local transitSchedule file");
            var parent = Path.of(scheduleUrl.toURI()).toRealPath().getParent();
            var relative = Path.of(file);
            if (relative.isAbsolute()) throw invalid("catalogFile must be relative to the transitSchedule");
            var catalogPath = parent.resolve(relative).normalize().toRealPath();
            if (!catalogPath.startsWith(parent) || !Files.isRegularFile(catalogPath))
                throw invalid("catalogFile must remain inside the transitSchedule directory");
            byte[] bytes;
            try (var input = Files.newInputStream(catalogPath)) { bytes = input.readNBytes(1_000_001); }
            if (bytes.length > 1_000_000) throw invalid("enabled catalog exceeds 1 MB limit");
            String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
            if (!expectedHash.equals(hash)) throw invalid("enabled catalog SHA256 mismatch");
            var ids = new LinkedHashSet<String>();
            for (var line : schedule.getTransitLines().values()) {
                requireValue(line, "enabledCatalogSource", hash);
                ids.add(required(line, "catalogServiceId"));
            }
            var links = new LinkedHashSet<String>();domain.forEach(id -> links.add(id.toString()));
            var mapper = new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
            validateCatalogDocument(mapper.readTree(bytes), links, ids);
        } catch (IllegalArgumentException error) { throw error; }
        catch (Exception error) { throw invalid("cannot validate bounded local enabled catalog: " + error.getMessage()); }
    }

    /** Pure catalog gate shared by the file preflight and tiny synthetic checks. */
    static void validateCatalogDocument(JsonNode catalog, Set<String> domainLinks, Set<String> selectedServices) {
        if (catalog == null || !catalog.isObject() || !catalog.path("production_enabled").isBoolean() ||
            !catalog.path("production_enabled").booleanValue()) throw invalid("catalog production is disabled");
        var domain = catalog.path("domain");
        if (!domain.path("approved").isBoolean() || !domain.path("approved").booleanValue())
            throw invalid("catalog domain is not approved");
        var mapped = new LinkedHashSet<String>();
        if (!domain.path("link_ids").isArray()) throw invalid("catalog lacks approved directed domain link mapping");
        for (var value : domain.path("link_ids")) {
            if (!value.isTextual() || value.textValue().isBlank() || !mapped.add(value.textValue()))
                throw invalid("invalid or duplicate catalog domain link");
        }
        if (!mapped.equals(domainLinks)) throw invalid("catalog domain differs from configured transit domain");
        var services = new HashMap<String, JsonNode>();
        if (!catalog.path("services").isArray()) throw invalid("catalog lacks services");
        for (var service : catalog.path("services")) {
            if (!service.path("service_id").isTextual() ||
                services.putIfAbsent(service.path("service_id").textValue(), service) != null)
                throw invalid("invalid or duplicate catalog service identity");
        }
        for (var id : selectedServices) {
            var service = services.get(id);
            if (service == null || !service.path("production_enabled").isBoolean() || !service.path("production_enabled").booleanValue())
                throw invalid("service not enabled in catalog: " + id);
            var verification = service.path("verification");
            if (!"verified".equals(verification.path("status").asText()) ||
                !verification.path("blockers").isArray() || !verification.path("blockers").isEmpty())
                throw invalid("service remains unverified or blocked: " + id);
        }
    }

    private static double validateStops(Scenario scenario, TransitRoute route, List<Id<Link>> links) {
        if (route.getStops().size() < 2) throw invalid("route needs two explicit ordered stops: " + route.getId());
        double previousDeparture = -1;
        int occurrence = 0;
        Id<Link> previousStopLink = null;
        for (var stop : route.getStops()) {
            var facility = stop.getStopFacility();
            if (scenario.getTransitSchedule().getFacilities().get(facility.getId()) != facility || facility.getLinkId() == null)
                throw invalid("unregistered stop facility " + facility.getId());
            if (facility.getCoord() == null || !Double.isFinite(facility.getCoord().getX()) || !Double.isFinite(facility.getCoord().getY()))
                throw invalid("stop without finite source coordinates " + facility.getId());
            if (facility.getLinkId().equals(previousStopLink))
                throw invalid("consecutive stops on the same link have ambiguous native occurrence: " + facility.getId());
            while (occurrence < links.size() && !links.get(occurrence).equals(facility.getLinkId())) occurrence++;
            if (occurrence == links.size()) throw invalid("stop is not on directed route in order: " + facility.getId());
            String placement = required(facility, "stopPlacement");
            if (!Set.of("bay", "in_lane", "nonblocking_proxy").contains(placement)) throw invalid("unknown stop placement");
            if (Set.of("bay","nonblocking_proxy").contains(placement) && facility.getIsBlockingLane()) throw invalid("bay cannot block native queue");
            if ("in_lane".equals(placement) && !facility.getIsBlockingLane()) throw invalid("in_lane requires explicit native blocking");
            var stopLink = scenario.getNetwork().getLinks().get(facility.getLinkId());
            var stopLanes = scenario.getLanes().getLanesToLinkAssignments().get(facility.getLinkId());
            boolean explicitQueueBlocking="scenario_blocking_native_queue_not_microscopic_lane".equals(
                facility.getAttributes().getAttribute("simz1:stopOccupancyBasis"));
            if ("in_lane".equals(placement) && !explicitQueueBlocking && (stopLink.getNumberOfLanes() != 1 ||
                (scenario.getConfig().qsim().isUseLanes() && stopLanes != null && stopLanes.getLanes().size() > 1)))
                throw invalid("unsupported_multilane_in_lane_stop: native stop has no laneRefId; do not block an aggregate queue implicitly");
            requireValue(facility, "dwellBasis", "explicit_scenario_assumption");
            double dwell = seconds(facility, "dwellSeconds");
            if (!stop.getArrivalOffset().isDefined() || !stop.getDepartureOffset().isDefined() ||
                (!stop.isAwaitDepartureTime() && !"weekday_scenario_v2".equals(scenario.getTransitSchedule().getAttributes().getAttribute("simz1:purpose"))))
                throw invalid("explicit arrival/departure offsets and awaitDepartureTime required");
            double arrival = stop.getArrivalOffset().seconds(), departure = stop.getDepartureOffset().seconds();
            if (!Double.isFinite(arrival) || !Double.isFinite(departure) || arrival < 0 || arrival + EPS < previousDeparture ||
                departure + EPS < arrival + dwell) throw invalid("invalid ordered offsets or assumed dwell");
            previousDeparture = departure;
            previousStopLink = facility.getLinkId();
        }
        if (!route.getStops().get(0).getStopFacility().getLinkId().equals(links.get(0)) ||
            !route.getStops().get(route.getStops().size()-1).getStopFacility().getLinkId().equals(links.get(links.size()-1)))
            throw invalid("first/last stop must anchor route endpoints; no unmodeled terminal traversal");
        return previousDeparture;
    }

    // MATSim 15 NetworkTurnInfoBuilder hard-codes car. Traverse the native lane graph for buses instead.
    private static boolean laneAllows(Scenario scenario, Link from, Link to) {
        var assignment = scenario.getLanes().getLanesToLinkAssignments().get(from.getId());
        if (assignment == null) return true;
        var models = LanesUtils.createLanes(from, assignment);
        if (models.isEmpty()) throw invalid("empty lane graph: " + from.getId());
        return laneExits(assignment, models.get(models.size()-1).getLaneData().getId(), new HashSet<>()).contains(to.getId());
    }
    private static Set<Id<Link>> laneExits(LanesToLinkAssignment assignment, Id<Lane> id, Set<Id<Lane>> visiting) {
        if (!visiting.add(id)) throw invalid("cycle in transit lane graph: " + id);
        var lane = assignment.getLanes().get(id);
        if (lane == null) throw invalid("missing transit lane: " + id);
        var result = new HashSet<Id<Link>>();
        if (lane.getToLaneIds() != null && !lane.getToLaneIds().isEmpty()) {
            if (lane.getToLinkIds() != null && !lane.getToLinkIds().isEmpty()) throw invalid("ambiguous lane exits: " + id);
            for (var next : lane.getToLaneIds()) result.addAll(laneExits(assignment, next, visiting));
        } else if (lane.getToLinkIds() != null) result.addAll(lane.getToLinkIds());
        visiting.remove(id);
        return result;
    }

    /** Exactly one native Umlauf per used vehicle, containing only explicitly supplied duties. */
    public static Collection<Umlauf> buildUmlaeufe(Scenario scenario, Prepared prepared) {
        var result = new ArrayList<Umlauf>();
        for (var entry : prepared.duties().entrySet()) {
            if (entry.getValue().isEmpty()) continue; // configured reserve bus: B includes it, drivers do not.
            var vehicle = scenario.getTransitVehicles().getVehicles().get(entry.getKey());
            var umlauf = new UmlaufImpl(Id.create(vehicle.getId()+"_"+vehicle.getType().getId(), Umlauf.class));
            umlauf.setVehicleId(vehicle.getId());
            for (var duty : entry.getValue()) umlauf.getUmlaufStuecke().add(new UmlaufStueck(duty.line(), duty.route(), duty.departure()));
            result.add(umlauf);
        }
        return result;
    }

    public static void install(Controler controler, Prepared prepared) {
        if (prepared == null) return;
        var scenario = controler.getScenario();
        var dwell = new AssumedDwellFactory();
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                installOverridingQSimModule(new AbstractQSimModule() {
                    @Override protected void configureQSim() {
                        bind(Prepared.class).toInstance(prepared);
                        bind(UmlaufBuilder.class).toInstance(() -> buildUmlaeufe(scenario, prepared));
                        bind(TransitStopHandlerFactory.class).toInstance(dwell);
                        bind(TransitQSimEngine.class).to(ExactTransitEngine.class).asEagerSingleton();
                    }
                });
            }
        });
    }

    /** Native lifecycle hooks are synchronous; event handlers may be parallel and cannot enforce availability. */
    public static final class ExactTransitEngine extends TransitQSimEngine {
        private final AvailabilityGuard guard;
        private final AssumedDwellFactory dwell;
        private final Prepared prepared;
        @javax.inject.Inject public ExactTransitEngine(QSim qsim, TransitStopHandlerFactory stopFactory,
                                                       UmlaufBuilder builder, Prepared prepared) {
            super(qsim, stopFactory, builder);
            if (!(stopFactory instanceof AssumedDwellFactory configured))
                throw invalid("fixed fleet requires its explicitly assumed dwell handler");
            dwell = configured;
            this.prepared=prepared;
            guard = new AvailabilityGuard(prepared);
        }
        @Override public void setInternalInterface(InternalInterface internal) {
            super.setInternalInterface(internal);
            if ("computational_network".equals(prepared.domainScope())) {
                setAbstractTransitDriverFactory(umlauf -> new SimZ1BoundaryTransitDriver(umlauf,
                    prepared.duties().get(umlauf.getVehicleId()),getAgentTracker(),internal,dwell::departed));
                return;
            }
            setAbstractTransitDriverFactory(umlauf -> new TransitDriverAgentImpl(umlauf, "car", getAgentTracker(), internal) {
                @Override public void endActivityAndComputeNextState(double now) {
                    // Check BEFORE native TransitDriverStartsEvent/state=LEG; never retime a scheduled departure.
                    guard.handleEvent(new TransitDriverStartsEvent(now, getId(), getVehicle().getId(),
                        getTransitLine().getId(), getTransitRoute().getId(), getDeparture().getId()));
                    super.endActivityAndComputeNextState(now);
                }
                @Override public void endLegAndComputeNextState(double now) {
                    guard.handleEvent(new PersonArrivalEvent(now, getId(), getDestinationLinkId(), getMode()));
                    super.endLegAndComputeNextState(now);
                }
                @Override public double handleTransitStop(TransitStopFacility stop, double now) {
                    double remaining = super.handleTransitStop(stop, now);
                    if (remaining == 0) dwell.departed(getVehicle().getId(), stop.getId());
                    return remaining;
                }
            });
        }
    }

    /** Strict policy: actual delays cannot consume a configured minimum terminal/return interval. */
    public static final class AvailabilityGuard implements TransitDriverStartsEventHandler, PersonArrivalEventHandler {
        private final Prepared prepared;
        private final Map<Id<Person>, Id<Vehicle>> drivers = new HashMap<>();
        private final Map<Id<Vehicle>, Integer> next = new HashMap<>();
        private final Map<Id<Vehicle>, Duty> active = new HashMap<>();
        private final Map<Id<Vehicle>, Double> readyAt = new HashMap<>();
        public AvailabilityGuard(Prepared prepared) { this.prepared = prepared; }
        @Override public synchronized void reset(int iteration) { drivers.clear(); next.clear(); active.clear(); readyAt.clear(); }
        @Override public synchronized void handleEvent(TransitDriverStartsEvent event) {
            var id = event.getVehicleId(); var roster = prepared.duties().get(id);
            int index = next.getOrDefault(id, 0);
            if (roster == null || index >= roster.size() || active.containsKey(id)) throw invalid("unavailable or unregistered bus starts: " + id);
            var duty = roster.get(index);
            if (!duty.line().getId().equals(event.getTransitLineId()) || !duty.route().getId().equals(event.getTransitRouteId()) ||
                !duty.departure().getId().equals(event.getDepartureId())) throw invalid("departure is not the next fixed duty: " + id);
            if (event.getTime() + EPS < duty.departure().getDepartureTime() ||
                event.getTime() + EPS < readyAt.getOrDefault(id, Double.NEGATIVE_INFINITY))
                throw invalid("actual_terminal_or_return_time_violation: " + id + " starts=" + event.getTime() + " ready=" + readyAt.get(id));
            var previous = drivers.putIfAbsent(event.getDriverId(), id);
            if (previous != null && !previous.equals(id)) throw invalid("internal driver assigned to multiple buses");
            active.put(id, duty); next.put(id, index+1);
        }
        @Override public synchronized void handleEvent(PersonArrivalEvent event) {
            var vehicle = drivers.get(event.getPersonId());
            if (vehicle == null) return;
            var duty = active.get(vehicle);
            if (duty == null || !duty.route().getRoute().getEndLinkId().equals(event.getLinkId()))
                throw invalid("transit arrival without matching terminal: " + vehicle);
            active.remove(vehicle);
            readyAt.put(vehicle, event.getTime() + duty.terminalSeconds() + duty.turnaroundSeconds());
        }
    }

    /** No passengers are synthesized. Dwell is an explicitly configured minimum, including late buses. */
    public static final class AssumedDwellFactory implements TransitStopHandlerFactory {
        private final Map<Id<Vehicle>, AssumedDwell> handlers = new ConcurrentHashMap<>();
        @Override public TransitStopHandler createTransitStopHandler(Vehicle vehicle) {
            var handler = new AssumedDwell(); handlers.put(vehicle.getId(), handler); return handler;
        }
        void departed(Id<Vehicle> vehicle, Id<TransitStopFacility> stop) {
            var handler = handlers.get(vehicle);
            if (handler == null) throw invalid("stop departure without configured bus dwell handler");
            handler.departed(stop);
        }
    }
    public static final class AssumedDwell implements TransitStopHandler {
        private Id<TransitStopFacility> stopId;
        private double ready;
        @Override public synchronized double handleTransitStop(TransitStopFacility stop, double now,
                List<PTPassengerAgent> leaving, List<PTPassengerAgent> entering, PassengerAccessEgress access, MobsimVehicle vehicle) {
            if (!leaving.isEmpty() || !entering.isEmpty()) throw invalid("passengers are not modeled in this fleet version");
            if (stopId == null) { stopId = stop.getId(); ready = now + seconds(stop, "dwellSeconds"); }
            if (!stopId.equals(stop.getId())) throw invalid("stop changed without departure event");
            // One-second revisits match MATSim's passenger access/egress contract even without passengers.
            return Math.min(1.0, Math.max(0, ready-now));
        }
        synchronized void departed(Id<TransitStopFacility> id) {
            if (stopId != null && !stopId.equals(id)) throw invalid("wrong stop departure");
            stopId = null;
        }
    }
}
