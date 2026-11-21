package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.network.algorithms.NetworkExpandNode.TurnInfo;
import org.matsim.core.network.algorithms.NetworkTurnInfoBuilder;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesToLinkAssignment;
import org.matsim.lanes.LanesUtils;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancy;
import gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow.Feasibility;

/** One immutable movement policy for initial routing and within-day validation.
 * MATSim 15's route index addresses [start, internal links..., end], not the
 * internal-link list. An occurrence must never be located using indexOf.
 */
public final class SimZ1RouteSafety {
    private final Scenario scenario;
    private final Network network;
    private final SimZ1SequenceContract sequences = SimZ1SequenceContract.shared();
    private final Map<Id<Link>, List<Id<Link>>> successors = new LinkedHashMap<>();
    private final Map<Id<Link>, Map<Id<Lane>, Set<Id<Link>>>> laneExits = new HashMap<>();
    private final Map<Id<Link>, Set<Id<Link>>> entryExits = new HashMap<>();
    private final Set<Id<Link>> spatialLinks;
    private final Set<Id<Vehicle>> transitVehicles;
    private final Map<Id<Link>, Set<Id<Link>>> transitSuccessors = new HashMap<>();
    private SimZ1CorridorOccupancy temporalGeometry;

    private VehicleType physicalType(Person person,Vehicle vehicle) {
        if(vehicle!=null)return vehicle.getType();
        if(person==null)return null;
        var ids=VehicleUtils.getVehicleIds(person);
        var id=ids==null?null:ids.get("car");
        var loaded=id==null?null:scenario.getVehicles().getVehicles().get(id);
        if(loaded!=null)return loaded.getType();
        var name=person.getAttributes().getAttribute("effectiveVehicleType");
        return name==null?null:scenario.getVehicles().getVehicleTypes().get(Id.create(name.toString(),VehicleType.class));
    }
    public synchronized SimZ1CorridorOccupancy.TemporalResult temporal(List<Id<Link>> path,int at,
            Person person,Vehicle vehicle,Id<Lane> lane,boolean complete) {
        var config=scenario.getConfig().getModules().get("simz1Admission");
        if(config==null||!"true".equals(config.getParams().get("wholeVehicleReservation")))
            return new SimZ1CorridorOccupancy.TemporalResult(Feasibility.COMPATIBLE,List.of(path.get(path.size()-1)),"body_passages_disabled");
        if(temporalGeometry==null)temporalGeometry=SimZ1CorridorOccupancy.temporalGeometry(scenario);
        var type=physicalType(person,vehicle);
        if(type==null)return new SimZ1CorridorOccupancy.TemporalResult(Feasibility.UNKNOWN,List.of(path.get(path.size()-1)),"vehicle_type_unavailable");
        return temporalGeometry.temporalRoute(path,at,type.getLength(),type.getMaximumVelocity(),lane,complete);
    }

    public SimZ1RouteSafety(Scenario scenario) {
        this.scenario = scenario;
        network = scenario.getNetwork();
        spatialLinks = spatialDomain(scenario);
        transitVehicles = scenario.getConfig().transit().isUseTransit()
            ? Set.copyOf(scenario.getTransitVehicles().getVehicles().keySet()) : Set.of();
        if (scenario.getConfig().qsim().isUseLanes()) {
            for (var assignment : scenario.getLanes().getLanesToLinkAssignments().values())
                indexLanes(assignment);
        }
        // This is the same MATSim 15 builder used by LinkToLinkRouting. It also
        // honors laneDefinitionsFile when detailed QSim lanes are disabled.
        var source = new NetworkTurnInfoBuilder(scenario).createAllowedTurnInfos();
        var links = new ArrayList<>(network.getLinks().keySet());
        links.sort(Comparator.comparing(Object::toString));
        for (var id : links) {
            var allowed = new TreeSet<Id<Link>>(Comparator.comparing(Object::toString));
            var from = network.getLinks().get(id);
            if (from.getAllowedModes().contains("car") && insideSpatialDomain(id)) {
                for (var turn : source.getOrDefault(id, List.of())) {
                    var to = network.getLinks().get(turn.getToLinkId());
                    if (to != null && to.getAllowedModes().contains("car") && insideSpatialDomain(to.getId()) &&
                        from.getToNode() == to.getFromNode() &&
                        (turn.getModes() == null || turn.getModes().contains("car")) &&
                        (!entryExits.containsKey(id) || entryExits.get(id).contains(to.getId())))
                        allowed.add(to.getId());
                }
            }
            successors.put(id, List.copyOf(allowed));
        }
        // MATSim 15 NetworkTurnInfoBuilder only builds car turns. Fixed transit
        // routes are validated by SimZ1TransitFleet and must not inherit car-only
        // restrictions. Keep a distinct bus graph; never expose it to car routing.
        if (!transitVehicles.isEmpty()) for (var from : network.getLinks().values()) {
            var allowed = new HashSet<Id<Link>>();
            if (from.getAllowedModes().contains("bus")) {
                Set<Id<Link>> laneRestriction = entryExits.get(from.getId());
                if (laneRestriction == null && scenario.getConfig().network().getLaneDefinitionsFile() != null) {
                    var assignment = scenario.getLanes().getLanesToLinkAssignments().get(from.getId());
                    if (assignment != null) {
                        laneRestriction = new HashSet<>();
                        for (var lane : assignment.getLanes().values())
                            if ((lane.getToLaneIds() == null || lane.getToLaneIds().isEmpty()) && lane.getToLinkIds() != null)
                                laneRestriction.addAll(lane.getToLinkIds());
                    }
                }
                for (var to : from.getToNode().getOutLinks().values())
                    if (to.getAllowedModes().contains("bus") &&
                        (laneRestriction == null || laneRestriction.contains(to.getId()))) allowed.add(to.getId());
            }
            transitSuccessors.put(from.getId(), Set.copyOf(allowed));
        }
        // Fixed transit routes share OSM sequence legality, retaining their
        // separate bus connectivity and all original service routes.
        if (scenario.getConfig().transit().isUseTransit())
            for (var line : scenario.getTransitSchedule().getTransitLines().values())
                for (var route : line.getRoutes().values()) if (route.getRoute()!=null) {
                    String issue=sequences.validate(full(route.getRoute()),"bus");
                    if (issue!=null) throw new IllegalArgumentException("Transit route "+route.getId()+": "+issue);
                }
    }

    private Set<Id<Link>> spatialDomain(Scenario scenario) {
        var group=scenario.getConfig().getModules().get("zona1SpatialRouting");
        if (group==null) return null; // Existing network-wide runs have no spatial module.
        if (!scenario.getConfig().controler().isLinkToLinkRoutingEnabled())
            throw new IllegalArgumentException("zona1SpatialRouting requires enableLinkToLinkRouting=true");
        if (!"gateway-od".equals(group.getParams().get("mode")))
            throw new IllegalArgumentException("zona1SpatialRouting.mode must be gateway-od");
        String value=group.getParams().get("allowedLinks");
        if (value==null || value.isBlank())
            throw new IllegalArgumentException("zona1SpatialRouting.allowedLinks must be nonempty");
        var allowed=new HashSet<Id<Link>>();
        for (String token:value.trim().split("\\s+")) {
            var id=Id.createLinkId(token);var link=network.getLinks().get(id);
            if (link==null || !link.getAllowedModes().contains("car"))
                throw new IllegalArgumentException("Invalid spatial car link: "+token);
            if (!allowed.add(id)) throw new IllegalArgumentException("Duplicate spatial link: "+token);
        }
        return Set.copyOf(allowed);
    }

    private boolean insideSpatialDomain(Id<Link> link) {return spatialLinks==null || spatialLinks.contains(link);}

    private void indexLanes(LanesToLinkAssignment assignment) {
        var link = network.getLinks().get(assignment.getLinkId());
        if (link == null) throw new IllegalArgumentException("Lane assignment on missing link " + assignment.getLinkId());
        if (assignment.getLanes().isEmpty()) throw new IllegalArgumentException("Empty lane assignment on " + link.getId());
        Map<Id<Lane>, Set<Id<Link>>> exits = new HashMap<>();
        for (var lane : assignment.getLanes().values())
            collectExits(link, assignment, lane.getId(), exits, new HashSet<>());
        // Use MATSim's own lane ordering: QLinkLanesImpl iterates this list and
        // sets firstLaneQueue to the last model lane (its accepting queue).
        var models = LanesUtils.createLanes(link, assignment);
        if (models.isEmpty()) throw new IllegalArgumentException("No modeled lanes on " + link.getId());
        var modeledIds = new HashSet<Id<Lane>>();
        for (var model : models) modeledIds.add(model.getLaneData().getId());
        if (!modeledIds.equals(assignment.getLanes().keySet()))
            throw new IllegalArgumentException("Unreachable lane definition on " + link.getId());
        entryExits.put(link.getId(), exits.get(models.get(models.size()-1).getLaneData().getId()));
        laneExits.put(link.getId(), Collections.unmodifiableMap(exits));
    }

    private Set<Id<Link>> collectExits(Link link, LanesToLinkAssignment assignment, Id<Lane> id,
            Map<Id<Lane>, Set<Id<Link>>> cache, Set<Id<Lane>> visiting) {
        if (cache.containsKey(id)) return cache.get(id);
        if (!visiting.add(id)) throw new IllegalArgumentException("Lane cycle on " + link.getId() + ": " + id);
        var lane = assignment.getLanes().get(id);
        if (lane == null) throw new IllegalArgumentException("Missing lane " + id + " on " + link.getId());
        if (!Double.isFinite(lane.getCapacityVehiclesPerHour()) || lane.getCapacityVehiclesPerHour() <= 0 ||
            !Double.isFinite(lane.getNumberOfRepresentedLanes()) || lane.getNumberOfRepresentedLanes() <= 0 ||
            !Double.isFinite(lane.getStartsAtMeterFromLinkEnd()) || lane.getStartsAtMeterFromLinkEnd() <= 0 ||
            lane.getStartsAtMeterFromLinkEnd() > link.getLength())
            throw new IllegalArgumentException("Invalid physical lane " + id + " on " + link.getId());
        var result = new HashSet<Id<Link>>();
        boolean internal = lane.getToLaneIds() != null && !lane.getToLaneIds().isEmpty();
        if (internal) {
            if (lane.getToLinkIds() != null && !lane.getToLinkIds().isEmpty())
                throw new IllegalArgumentException("Lane has both toLane and toLink references: " + id);
            for (var next : lane.getToLaneIds()) {
                var downstream = assignment.getLanes().get(next);
                if (downstream != null && downstream.getStartsAtMeterFromLinkEnd() > lane.getStartsAtMeterFromLinkEnd())
                    throw new IllegalArgumentException("Upstream lane movement " + id + " -> " + next);
                result.addAll(collectExits(link, assignment, next, cache, visiting));
            }
        } else {
            if (lane.getToLinkIds() == null || lane.getToLinkIds().isEmpty())
                throw new IllegalArgumentException("Terminal lane without an exit: " + id);
            for (var next : lane.getToLinkIds()) {
                var target = network.getLinks().get(next);
                if (target == null || !sharesRoadMode(link, target) ||
                    link.getToNode() != target.getFromNode())
                    throw new IllegalArgumentException("Invalid lane movement " + link.getId() + "/" + id + " -> " + next);
                result.add(next);
            }
        }
        visiting.remove(id);
        var immutable = Set.copyOf(result);
        cache.put(id, immutable);
        return immutable;
    }

    /** Lane structure may contain bus-only exits without granting them to cars. */
    private static boolean sharesRoadMode(Link a, Link b) {
        return (a.getAllowedModes().contains("car") && b.getAllowedModes().contains("car")) ||
               (a.getAllowedModes().contains("bus") && b.getAllowedModes().contains("bus"));
    }

    /** Defensive map for MATSim's primary LinkToLinkRouting binding (road demand only). */
    public Map<Id<Link>, List<TurnInfo>> allowedTurnInfos() {
        Map<Id<Link>, List<TurnInfo>> result = new LinkedHashMap<>();
        successors.forEach((from, tos) -> {
            var turns = new ArrayList<TurnInfo>();
            for (var to : tos) turns.add(new TurnInfo(from, to, new HashSet<>(Set.of("car"))));
            result.put(from, turns);
        });
        return result;
    }

    public List<Id<Link>> successors(Id<Link> from) { return successors.getOrDefault(from, List.of()); }

    int sequenceProgress(List<Id<Link>> prefix) { return sequences.progress(prefix,"car"); }
    int advanceSequence(int state,Id<Link> next) { return sequences.advance(state,next,"car"); }
    boolean sequenceVia(Id<Link> link) { return sequences.isVia(link); }

    public boolean laneAllows(Id<Link> from, Id<Lane> lane, Id<Link> next) {
        if (!successors(from).contains(next)) return false;
        if (!laneExits.containsKey(from)) return true; // Standard QSim queue.
        return lane != null && laneExits.get(from).getOrDefault(lane, Set.of()).contains(next);
    }

    /** Called only at native admission: registry identity, never name or speed, selects bus permissions. */
    public boolean laneAllowsVehicle(Id<Link> from, Id<Lane> lane, Id<Link> next, Id<Vehicle> vehicle) {
        if (!transitVehicles.contains(vehicle)) return laneAllows(from, lane, next);
        if (!transitSuccessors.getOrDefault(from, Set.of()).contains(next)) return false;
        if (!laneExits.containsKey(from)) return true;
        return lane != null && laneExits.get(from).getOrDefault(lane, Set.of()).contains(next);
    }

    public static List<Id<Link>> full(NetworkRoute route) {
        Objects.requireNonNull(route, "route");
        var result = new ArrayList<Id<Link>>();
        result.add(route.getStartLinkId());
        result.addAll(route.getLinkIds());
        // A same-link, no-internal-links leg is a single physical occurrence.
        if (!route.getLinkIds().isEmpty() || !Objects.equals(route.getStartLinkId(), route.getEndLinkId()))
            result.add(route.getEndLinkId());
        return Collections.unmodifiableList(result);
    }

    /** suffix includes current link and destination; preserves occurrences, never deduplicates. */
    public static List<Id<Link>> splice(List<Id<Link>> old, int index, List<Id<Link>> suffix) {
        if (old == null || index < 0 || index >= old.size() || suffix == null || suffix.isEmpty() ||
            !Objects.equals(old.get(index), suffix.get(0)))
            throw new IllegalArgumentException("Invalid current-link occurrence for route splice");
        var result = new ArrayList<>(old.subList(0, index));
        result.addAll(suffix);
        return List.copyOf(result);
    }

    public String validateNetwork(List<Id<Link>> route) {
        if (route == null || route.isEmpty()) return "empty_route";
        Link previous = null;
        for (int i=0; i<route.size(); i++) {
            var id = route.get(i);
            var link = id == null ? null : network.getLinks().get(id);
            if (link == null) return "missing_link index=" + i + " link=" + id;
            if (!link.getAllowedModes().contains("car")) return "mode_not_car index=" + i + " link=" + id;
            if (!insideSpatialDomain(id)) return "outside_spatial_domain index=" + i + " link=" + id;
            if (network.getNodes().get(link.getFromNode().getId()) != link.getFromNode() ||
                network.getNodes().get(link.getToNode().getId()) != link.getToNode())
                return "unregistered_node_reference index=" + i + " link=" + id;
            if (previous != null) {
                if (previous.getToNode() != link.getFromNode())
                    return "disconnected index=" + i + " from=" + previous.getId() + " to=" + id;
                if (!successors(previous.getId()).contains(id))
                    return "forbidden_movement index=" + i + " from=" + previous.getId() + " to=" + id;
            }
            previous = link;
        }
        return sequences.validate(route,"car");
    }

    /** Null means valid. The caller must obtain actualCurrent/actualLane from QSim, not the route. */
    SimZ1TripOd tripOd() { return SimZ1TripOd.shared(scenario); }

    String validateReplacement(List<Id<Link>> old, List<Id<Link>> candidate, int index,
            Id<Link> actualCurrent, Id<Link> destination, Id<Lane> actualLane, SimZ1TripOd.Contract contract) {
        String issue=validateReplacement(old,candidate,index,actualCurrent,destination,actualLane);
        if (issue!=null || contract==null) return issue;
        issue=contract.validate(old);
        return issue!=null?"old_route "+issue:contract.validate(candidate);
    }

    public String validateReplacement(List<Id<Link>> old, List<Id<Link>> candidate, int index,
            Id<Link> actualCurrent, Id<Link> destination, Id<Lane> actualLane) {
        String reason = validateNetwork(old);
        if (reason != null) return "old_route " + reason;
        if (index < 0 || index >= old.size()) return "route_index_out_of_bounds index=" + index;
        if (actualCurrent == null || !actualCurrent.equals(old.get(index))) return "current_link_index_mismatch index=" + index;
        if (destination == null || !destination.equals(old.get(old.size()-1))) return "old_destination_mismatch";
        reason = validateNetwork(candidate);
        if (reason != null) return "candidate " + reason;
        if (candidate.size() <= index || !old.subList(0,index+1).equals(candidate.subList(0,index+1)))
            return "traversed_prefix_changed index=" + index;
        if (!destination.equals(candidate.get(candidate.size()-1))) return "destination_changed";
        if (index == old.size()-1 && !old.equals(candidate)) return "route_extended_after_arrival";
        if (actualLane != null && index+1 < candidate.size() && !laneAllows(actualCurrent, actualLane, candidate.get(index+1)))
            return "current_lane_cannot_reach_next lane=" + actualLane + " next=" + candidate.get(index+1);
        return null;
    }
}
