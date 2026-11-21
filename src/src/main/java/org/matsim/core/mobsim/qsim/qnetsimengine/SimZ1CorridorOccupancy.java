package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.mobsim.qsim.agents.HasModifiablePlan;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.vehicles.Vehicle;
import gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow;
import gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow.Feasibility;
import gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow.Requirement;
import org.matsim.lanes.Lane;

/** Synchronous metric storage, across OSM subdivisions but never across a junction.
 * Slots are model allocations, not measured lateral positions or trajectories.
 * PCU flow calculations remain owned by MATSim. */
public final class SimZ1CorridorOccupancy {
    public static final String POLICY="corridor-length-v1";
    public static final String ROUTE_COVERAGE="planned_stopping_prefix_v2";
    public static final double GAP=.10, NOMINAL_LANE_WIDTH=3.0;
    private static final Map<QSimConfigGroup,SimZ1CorridorOccupancy> REGISTRY=Collections.synchronizedMap(new WeakHashMap<>());
    static SimZ1CorridorOccupancy get(QSimConfigGroup config) { return REGISTRY.get(config); }
    static void install(QSimConfigGroup config,SimZ1CorridorOccupancy ledger) { REGISTRY.put(config,ledger); }
    static void uninstall(QSimConfigGroup config) { REGISTRY.remove(config); }

    static final class Domain {
        final String id; final List<Link> links; final int lanes; final double length,setback,capacity;
        final double[] used; final Map<Id<Link>,Double> offsets=new HashMap<>();
        final List<NavigableMap<Long,Reservation>> reservations=new ArrayList<>();
        Domain(List<Link> links) {
            this.links=List.copyOf(links);id=links.get(0).getId().toString();lanes=(int)links.get(0).getNumberOfLanes();
            double at=0;for(var l:links){offsets.put(l.getId(),at);at+=l.getLength();}length=at;
            setback=stopSetback(links.get(links.size()-1));capacity=Math.max(0,length-setback);used=new double[lanes];
            for(int slot=0;slot<lanes;slot++)reservations.add(new TreeMap<>());
        }
        double total() { return Arrays.stream(used).sum(); }
    }
    private static final class Reservation {
        final Domain domain; final double length,footprint; final long ordinal;
        int slot; Id<Link> link; Id<Vehicle> vehicle;double frontBound,nativeFront,admissionClearFront,maximumSpeed;String nativeQueue="";Passage passage;
        Reservation(Domain d,int slot,double length,long ordinal,Id<Link> link){domain=d;this.slot=slot;this.length=length;
            footprint=length+GAP;this.ordinal=ordinal;this.link=link;frontBound=0;}
    }
    private record Pending(Id<Link> link,String lane,int slot) { }
    private record PassageDeadline(double time,long ordinal,Id<Vehicle> vehicle,Passage passage) { }
    private static final class Passage {
        final List<Link> links;final Map<Id<Link>,Integer> slots;final Link receipt;final Set<Id<Node>> nodes=new LinkedHashSet<>();
        final Map<Id<Link>,Double> offsets=new HashMap<>();final Id<Link> exitFrom;double notBefore,clearFront,freeFront,holdStart,authorizedTime,requiredStop,reachableFront;boolean released;
        List<Id<Link>> receiptPath=List.of();Id<Link> receiptFollowingLink;double receiptStoppingSetback;
        String lastDiagnostic="";
        boolean lastDiagnosticTimeSatisfied,lastDiagnosticBodyCleared;
        final Map<Id<Link>,Double> stopCredits=new LinkedHashMap<>();
        final Map<Id<Link>,Double> greenWindows=new LinkedHashMap<>(),traversalBudgets=new LinkedHashMap<>();
        Passage(List<Link> links,Map<Id<Link>,Integer> slots,Link receipt,double receiptOffset,Id<Link> exitFrom){this.links=List.copyOf(links);this.slots=Map.copyOf(slots);this.receipt=receipt;this.exitFrom=exitFrom;
            double at=receipt==null?receiptOffset:receiptOffset-links.stream().mapToDouble(Link::getLength).sum();
            for(var l:links){offsets.put(l.getId(),at);at+=l.getLength();nodes.add(l.getFromNode().getId());}if(receipt!=null)nodes.add(receipt.getFromNode().getId());}
    }
    private final Map<Id<Link>,Domain> domains=new HashMap<>();
    private final Map<Id<Link>,Map<String,Integer>> laneIndices=new HashMap<>();
    private final Map<Id<Link>,Map<Integer,Set<Id<Link>>>> exits=new HashMap<>();
    private final Map<Id<Link>,Map<String,Double>> queueEnds=new HashMap<>();
    private final Map<Id<Link>,Map<String,Double>> queueStarts=new HashMap<>();
    private final Map<Id<Link>,Set<Integer>> originSlots=new HashMap<>();
    private final Map<Id<Vehicle>,Reservation> active=new HashMap<>();
    private final Map<Id<Vehicle>,Pending> pending=new HashMap<>();
    private final Map<Id<Vehicle>,Passage> pendingPassages=new HashMap<>();
    private final Map<Id<Node>,Id<Vehicle>> nodeLocks=new HashMap<>();
    private final Map<Id<Link>,Id<Vehicle>> connectorLocks=new HashMap<>();
    private final Map<Domain,Id<Vehicle>> receiptLocks=new IdentityHashMap<>();
    private final Map<Id<Node>,Zona1QNodeImpl> nativeNodes=new HashMap<>();
    private final Map<Id<Vehicle>,Double> passageRequestTime=new HashMap<>();
    private record PassageRequest(List<Id<Link>> path,String queue,double headSince) { }
    private final Map<Id<Vehicle>,PassageRequest> passageRequests=new HashMap<>();
    private final PriorityQueue<PassageDeadline> passageDeadlines=new PriorityQueue<>(
        Comparator.comparingDouble(PassageDeadline::time).thenComparingLong(PassageDeadline::ordinal));
    private final Network network;
    private final QSimConfigGroup.TrafficDynamics trafficDynamics;
    private final gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow signalWindows;
    private final Set<String> waits=new HashSet<>();
    private final Map<Id<Vehicle>,String> waitReasons=new HashMap<>();
    private final EventsManager events;
    private long nextOrdinal=0;
    private final double timeStep;
    private final boolean physicalGapOrigin;

    public SimZ1CorridorOccupancy(Scenario scenario,Set<Id<Node>> controlled,EventsManager events) {
        this(scenario,controlled,events,true);
    }
    private SimZ1CorridorOccupancy(Scenario scenario,Set<Id<Node>> controlled,EventsManager events,boolean annotate) {
        var admission=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
        admission.validateOriginPolicy(scenario.getConfig().qsim());
        this.physicalGapOrigin=admission.usesPhysicalGapOrigin();
        this.timeStep=scenario.getConfig().qsim().getTimeStepSize();
        this.trafficDynamics=scenario.getConfig().qsim().getTrafficDynamics();
        this.events=events;this.network=scenario.getNetwork();this.signalWindows=new gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow(scenario);
        var road=new TreeMap<Id<Link>,Link>(Comparator.comparing(Object::toString));
        for(var l:scenario.getNetwork().getLinks().values())if(road(l)) {
            if(!Double.isFinite(l.getLength()) || l.getLength()<=0 || l.getNumberOfLanes()<1 ||
                    l.getNumberOfLanes()!=Math.rint(l.getNumberOfLanes()))throw new IllegalArgumentException("Invalid occupancy geometry: "+l.getId());
            road.put(l.getId(),l);
        }
        var next=new HashMap<Id<Link>,Id<Link>>();var previous=new HashMap<Id<Link>,Id<Link>>();
        for(var a:road.values()) {
            var node=a.getToNode(); if(controlled.contains(node.getId()) || explicitControl(node,a))continue;
            var neighbours=new HashSet<Id<Node>>();
            for(var l:node.getInLinks().values())if(road(l))neighbours.add(l.getFromNode().getId());
            for(var l:node.getOutLinks().values())if(road(l))neighbours.add(l.getToNode().getId());
            if(neighbours.size()!=2)continue;
            var successors=node.getOutLinks().values().stream().filter(b->road(b)&&b.getToNode()!=a.getFromNode()).toList();
            if(successors.size()!=1)continue;var b=successors.get(0);
            if(!compatible(a,b))continue;
            next.put(a.getId(),b.getId());
            if(previous.put(b.getId(),a.getId())!=null)throw new IllegalArgumentException("Ambiguous occupancy predecessor");
        }
        var assigned=new HashSet<Id<Link>>();
        var starts=new ArrayList<Id<Link>>();
        for(var id:road.keySet())if(!previous.containsKey(id))starts.add(id);
        starts.addAll(road.keySet()); // deterministic cut of isolated cycles
        for(var start:starts)if(!assigned.contains(start)) {
            var chain=new ArrayList<Link>();var id=start;
            while(id!=null && assigned.add(id)){chain.add(road.get(id));id=next.get(id);}
            var d=new Domain(chain);for(var l:chain)domains.put(l.getId(),d);
        }
        for(var assignment:scenario.getLanes().getLanesToLinkAssignments().values()) {
            var d=domains.get(assignment.getLinkId());if(d==null)continue;
            var indices=new HashMap<String,Integer>();var allowed=new HashMap<Integer,Set<Id<Link>>>();
            var ends=new HashMap<String,Double>();var startsAt=new HashMap<String,Double>();
            for(var lane:assignment.getLanes().values()) {
                double end=0;
                if(lane.getToLaneIds()!=null)for(var child:lane.getToLaneIds())end=Math.max(end,assignment.getLanes().get(child).getStartsAtMeterFromLinkEnd());
                ends.put(lane.getId().toString(),scenario.getNetwork().getLinks().get(assignment.getLinkId()).getLength()-end);
                startsAt.put(lane.getId().toString(),scenario.getNetwork().getLinks().get(assignment.getLinkId()).getLength()-lane.getStartsAtMeterFromLinkEnd());
                String name=lane.getId().toString();int marker=name.lastIndexOf(".lane.");
                if(marker<0 || lane.getNumberOfRepresentedLanes()!=1 || lane.getToLinkIds()==null)continue;
                int index;try{index=Integer.parseInt(name.substring(marker+6));}catch(NumberFormatException e){continue;}
                if(index<0 || index>=d.lanes)throw new IllegalArgumentException("Invalid terminal model slot: "+name);
                indices.put(name,index);allowed.put(index,new HashSet<>(lane.getToLinkIds()));
            }
            laneIndices.put(assignment.getLinkId(),indices);exits.put(assignment.getLinkId(),allowed);queueEnds.put(assignment.getLinkId(),ends);queueStarts.put(assignment.getLinkId(),startsAt);
            // Only direct, explicitly connected original-to-terminal queues
            // support this variant. Complex lane graphs keep legacy admission.
            var original=assignment.getLanes().get(Id.create(assignment.getLinkId()+".original",Lane.class));
            if(original!=null&&original.getNumberOfRepresentedLanes()==d.lanes
                    &&original.getToLaneIds()!=null&&!original.getToLaneIds().isEmpty()
                    &&(original.getToLinkIds()==null||original.getToLinkIds().isEmpty())) {
                var reachable=new TreeSet<Integer>();boolean represented=true;
                for(var child:original.getToLaneIds()) {
                    var slot=indices.get(child.toString());var terminal=assignment.getLanes().get(child);
                    if(slot==null||terminal==null||terminal.getToLaneIds()!=null&&!terminal.getToLaneIds().isEmpty()){
                        represented=false;break;
                    }
                    reachable.add(slot);
                }
                if(represented)originSlots.put(assignment.getLinkId(),Collections.unmodifiableSet(reachable));
            }
        }
        // Mark network metadata too; authoritative observations are emitted below.
        if(annotate) for(var l:road.values()) {
            var d=domains.get(l.getId());var attrs=l.getAttributes();
            attrs.putAttribute("simz1:occupancyPolicy",POLICY);attrs.putAttribute("simz1:occupancyCorridor",d.id);
            attrs.putAttribute("simz1:occupancyOffsetMeters",d.offsets.get(l.getId()));
            attrs.putAttribute("simz1:occupancyCorridorLengthMeters",d.length);
        }
    }
    /** Same geometry as production admission, without registration, events,
     * reservations or network metadata writes. Construct after effective inputs. */
    public static SimZ1CorridorOccupancy temporalGeometry(Scenario scenario) {
        var windows=new Zona1SignalGreenWindow(scenario);var controlled=new HashSet<Id<Node>>();
        for(var id:windows.controlledLinks())controlled.add(scenario.getNetwork().getLinks().get(id).getToNode().getId());
        return new SimZ1CorridorOccupancy(scenario,controlled,null,false);
    }
    public record TemporalResult(Feasibility status,List<Id<Link>> context,String reason) { }
    /** Static empty/debt-free feasibility, independent of current red, occupancy
     * and reservations. Partial prefixes retain the pending physical passage;
     * a full stopping receipt ends the conjunction, never the whole route. */
    public TemporalResult temporalRoute(List<Id<Link>> path,int at,double body,double maximumSpeed,
                                        Id<Lane> actualLane,boolean complete) {
        if(path==null||at<0||at>=path.size()||!(body>0)||!Double.isFinite(body)||
                !(maximumSpeed>0)||!Double.isFinite(maximumSpeed))
            return new TemporalResult(Feasibility.UNKNOWN,path==null?List.of():List.copyOf(path),"physical_parameters_unavailable");
        Feasibility status=Feasibility.COMPATIBLE;int lastReceipt=at;
        for(int start=at;start+1<path.size();start++) {
            if(domains.get(path.get(start))==null||domains.get(path.get(start+1))==null)
                return new TemporalResult(Feasibility.UNKNOWN,List.copyOf(path.subList(at,path.size())),"nonroad_geometry");
            if(domains.get(path.get(start))==domains.get(path.get(start+1)))continue;
            var source=new RouteMovement(path.get(start),path.get(start+1));
            var sourceLanes=start==at&&actualLane!=null&&laneIndices.getOrDefault(source.from(),Map.of()).containsKey(actualLane.toString())?
                List.of(actualLane):movementLanes(source);
            var connectors=new ArrayList<Requirement>();var usedDomains=new HashSet<Domain>();double budget=0;
            boolean pending=false;
            for(int i=start+1;i<path.size();) {
                var link=network.getLinks().get(path.get(i));var d=domains.get(link.getId());
                if(d==null){status=Feasibility.UNKNOWN;break;}
                int end=i+1;while(end<path.size()&&domains.get(path.get(end))==d)end++;
                var reach=routeReach(path,i,d);
                // A partial path's last link is not a final activity. Keep the
                // junction setback until its outgoing occurrence is known.
                double front=reach.front();
                if(!complete&&end==path.size())front=Math.min(front,d.offsets.get(path.get(end-1))+
                        network.getLinks().get(path.get(end-1)).getLength()-stopSetback(network.getLinks().get(path.get(end-1))));
                if(!usedDomains.contains(d)&&front-d.offsets.get(link.getId())>=body+GAP+conflictMargin(link,link.getFromNode())) {
                    lastReceipt=Math.max(lastReceipt,i);break;
                }
                if(!complete&&end==path.size()){pending=true;break;}
                usedDomains.add(d);
                for(int j=i;j<end&&j+1<path.size();j++) {
                    var movement=new RouteMovement(path.get(j),path.get(j+1));
                    var lanes=movementLanes(movement);
                    // Production describePassagePlan selects the lowest
                    // compatible model slot for each connector.
                    Id<Lane> lane=lanes.get(0);
                    budget+=temporalTraversal(movement.from(),lane,maximumSpeed);
                    connectors.add(new Requirement(movement.from(),lane,movement.to(),budget,false));
                }
                i=end;
            }
            Feasibility passage=Feasibility.IMPOSSIBLE;
            for(var lane:sourceLanes) {
                var requirements=new ArrayList<Requirement>();requirements.add(new Requirement(source.from(),lane,source.to(),0,true));
                requirements.addAll(connectors);
                var outcome=signalWindows.feasibility(requirements,timeStep);
                if(outcome==Feasibility.COMPATIBLE){passage=outcome;break;}
                if(outcome==Feasibility.UNKNOWN)passage=outcome;
            }
            if(passage==Feasibility.IMPOSSIBLE)return new TemporalResult(passage,List.copyOf(path.subList(at,path.size())),
                    "no_periodic_passage_window:"+source.from()+"->"+source.to());
            if(passage==Feasibility.UNKNOWN||pending)status=Feasibility.UNKNOWN;
        }
        return new TemporalResult(status,List.copyOf(path.subList(lastReceipt,path.size())),
                status==Feasibility.COMPATIBLE?"empty_queue_periodic_window":"incomplete_or_unsupported_passage");
    }
    private double temporalTraversal(Id<Link> id,Id<Lane> lane,double maximumSpeed) {
        var link=network.getLinks().get(id);double speed=Math.min(maximumSpeed,link.getFreespeed());
        var ends=queueEnds.getOrDefault(id,Map.of());var starts=queueStarts.getOrDefault(id,Map.of());
        if(ends.isEmpty())return SimZ1PassageTiming.budget(link.getLength(),speed,timeStep,0,false);
        if(lane==null||!ends.containsKey(lane.toString()))return Double.POSITIVE_INFINITY;
        double total=0;
        for(var entry:ends.entrySet())if(entry.getKey().endsWith(".original")||entry.getKey().equals(lane.toString()))
            total+=SimZ1PassageTiming.budget(entry.getValue()-starts.get(entry.getKey()),speed,timeStep,0,false);
        return total;
    }
    private static boolean road(Link l){return l.getAllowedModes().contains("car")||l.getAllowedModes().contains("bus");}
    private static boolean explicitControl(Node n,Link in) {
        for(String key:List.of("osm:highway","highway"))if(Set.of("traffic_signals","stop","give_way").contains(Objects.toString(n.getAttributes().getAttribute(key),"")))return true;
        return Set.of("stop","yield").contains(Objects.toString(in.getAttributes().getAttribute("simz1:priorityControl"),""));
    }
    private static boolean compatible(Link a,Link b) {
        if(a.getNumberOfLanes()!=b.getNumberOfLanes() || !a.getAllowedModes().equals(b.getAllowedModes()))return false;
        for(String key:List.of("osm:layer","osm:bridge","osm:tunnel"))if(!Objects.equals(a.getAttributes().getAttribute(key),b.getAttributes().getAttribute(key)))return false;
        var u=direction(a);var v=direction(b);return u[0]*v[0]+u[1]*v[1]>=.95;
    }
    private static double[] direction(Link l) {
        double x=l.getToNode().getCoord().getX()-l.getFromNode().getCoord().getX(),y=l.getToNode().getCoord().getY()-l.getFromNode().getCoord().getY();
        double n=Math.hypot(x,y);if(!(n>0))throw new IllegalArgumentException("Degenerate occupancy link "+l.getId());return new double[]{x/n,y/n};
    }
    private static double stopSetback(Link end) {
        return 2+conflictMargin(end,end.getToNode());
    }
    private static double conflictMargin(Link end,Node node) {
        double margin=0;var u=direction(end);
        var incident=new ArrayList<Link>(node.getInLinks().values());incident.addAll(node.getOutLinks().values());
        for(var other:incident)if(road(other)&&other!=end) {
            var v=direction(other);double cross=Math.abs(u[0]*v[1]-u[1]*v[0]);if(cross<.25)continue;
            double lanes=other.getNumberOfLanes();
            for(var reverse:incident)if(reverse.getFromNode()==other.getToNode() && reverse.getToNode()==other.getFromNode())lanes+=reverse.getNumberOfLanes();
            margin=Math.max(margin,.5*NOMINAL_LANE_WIDTH*lanes/cross);
        }
        return margin;
    }
    public void emitDomains(double now) {
        for(var entry:new TreeMap<Id<Link>,Domain>(domains).entrySet()) {
            var d=entry.getValue();var id=entry.getKey();var l=d.links.stream().filter(x->x.getId().equals(id)).findFirst().orElseThrow();
            var values=new LinkedHashMap<String,String>();values.put("policy",POLICY);values.put("corridor",d.id);values.put("link",id.toString());
            values.put("links",String.join(",",d.links.stream().map(x->x.getId().toString()).toList()));
            values.put("linkOffsetMeters",Double.toString(d.offsets.get(id)));values.put("linkLengthMeters",Double.toString(l.getLength()));
            values.put("corridorLengthMeters",Double.toString(d.length));values.put("representedLanes",Integer.toString(d.lanes));
            values.put("minimumGapMeters",Double.toString(GAP));values.put("endSetbackMeters",Double.toString(d.setback));
            values.put("laneCapacityMeters",Double.toString(d.capacity));values.put("capacityMeters",Double.toString(d.capacity*d.lanes));values.put("positionsObserved","false");
            values.put("receiptRouteCoveragePolicy",ROUTE_COVERAGE);
            emit(now,"simz1OccupancyDomain",values);
        }
    }
    private double length(QVehicle vehicle) {
        double value=vehicle.getVehicle().getType().getLength();if(!Double.isFinite(value)||value<=0)throw new IllegalArgumentException("Invalid body length "+vehicle.getId());return value;
    }
    /** Front displacement along the receiving link, measured from its entry.
     * Project the incident road widths onto that same downstream axis. The
     * source's setback is measured along a different axis and cannot be used
     * as the receiver's clearance, especially at asymmetric intersections. */
    double entryClearanceDistance(QVehicle vehicle,Id<Link> target) {
        var link=network.getLinks().get(target);
        return length(vehicle)+GAP+conflictMargin(link,link.getFromNode());
    }
    private record Reach(double front,List<Id<Link>> links,double stoppingSetback,Id<Link> followingLink) { }
    private List<Id<Link>> plannedPath(QVehicle vehicle){
        if(!(vehicle.getDriver() instanceof PlanAgent plan)||!(plan.getCurrentPlanElement() instanceof Leg leg)||!(leg.getRoute() instanceof NetworkRoute route))return null;
        var path=new ArrayList<Id<Link>>();path.add(route.getStartLinkId());path.addAll(route.getLinkIds());path.add(route.getEndLinkId());
        if(vehicle.getDriver() instanceof HasModifiablePlan indexed){
            // Within-day rerouting preserves the travelled prefix. A link in
            // that prefix may legally be visited again; it is not an ambiguous
            // future receipt. Use the same native cursor as the route updater,
            // without resetting caches, acquiring storage or releasing origin.
            int at=indexed.getCurrentLinkIndex();
            if(at<0||at>=path.size()||!path.get(at).equals(vehicle.getDriver().getCurrentLinkId()))
                throw new IllegalStateException("Occupancy route cursor mismatch for "+vehicle.getId()+": "+at);
            return path.subList(at,path.size());
        }
        return path;
    }
    private Reach routeReach(List<Id<Link>> path,int at,Domain d){
        var links=new ArrayList<Id<Link>>();double front=d.offsets.get(path.get(at));int i=at;
        for(;i<path.size()&&domains.get(path.get(i))==d;i++){
            var id=path.get(i);links.add(id);front=d.offsets.get(id)+network.getLinks().get(id).getLength();
        }
        // An interior exit (including a U-turn) has its own stopping margin.
        // The unvisited end of the storage domain cannot supply this space.
        // A native final activity does not need an additional junction stop.
        double setback=i<path.size()&&!links.isEmpty()?stopSetback(network.getLinks().get(links.get(links.size()-1))):0;
        return new Reach(Math.min(d.capacity,front-setback),List.copyOf(links),setback,i<path.size()?path.get(i):null);
    }
    private Reach routeReach(QVehicle vehicle,Id<Link> target){
        var d=domains.get(target);var path=plannedPath(vehicle);
        if(path==null)return new Reach(d.capacity,d.links.stream().map(Link::getId).toList(),0,null);
        int at=path.indexOf(target);if(at<0||at!=path.lastIndexOf(target))return new Reach(d.offsets.get(target),List.of(),0,null);
        return routeReach(path,at,d);
    }
    /** Replanning may not invalidate storage already committed to a model slot
     * or a connector path whose complete exit has been reserved. */
    public static String replacementIssue(QSimConfigGroup config,Id<Vehicle> vehicle,List<Id<Link>> candidate,int currentIndex){
        var ledger=get(config);return ledger==null?null:ledger.replacementIssue(vehicle,candidate,currentIndex);
    }
    /** At the rerouter's before-step barrier, also inspect the actual offered
     * heads. A rejected detached candidate never changes routes or reservations.
     * The four-argument form retains its geometry/reservation-only contract. */
    public static String replacementIssue(QSimConfigGroup config,Id<Vehicle> vehicle,List<Id<Link>> candidate,int currentIndex,
            org.matsim.core.mobsim.qsim.interfaces.NetsimNetwork qnet) {
        var ledger=get(config);if(ledger==null)return null;
        String issue=ledger.replacementIssue(vehicle,candidate,currentIndex);
        return issue!=null?issue:ledger.opposedReturnIssue(vehicle,candidate,currentIndex,qnet);
    }
    private String replacementIssue(Id<Vehicle> vehicle,List<Id<Link>> path,int at){
        var r=active.get(vehicle);if(r==null)return null;
        if(at<0||at>=path.size()||!path.get(at).equals(r.link))return "occupancy_current_link_mismatch";
        var p=r.passage;
        if(p!=null&&!p.released){
            var expected=new ArrayList<Id<Link>>(p.links.stream().map(Link::getId).toList());if(p.receipt!=null)expected.add(p.receipt.getId());
            int start=expected.indexOf(r.link);
            if(start>=0)for(int i=start;i<expected.size();i++)if(at+i-start>=path.size()||!path.get(at+i-start).equals(expected.get(i)))return "occupancy_active_passage_prefix";
            if(p.receipt!=null){int receiptAt=path.subList(at,path.size()).indexOf(p.receipt.getId());
                if(receiptAt<0||routeReach(path,at+receiptAt,r.domain).front()<p.clearFront-1e-8)return "occupancy_active_passage_clearance";}
        }
        // Preserve the clearance that justified an ordinary receipt too. A
        // reroute may not turn that committed receiver into a short connector.
        if((p==null||p.released)&&routeReach(path,at,r.domain).front()<r.admissionClearFront-1e-8)
            return "occupancy_reserved_receipt_clearance";
        int first=at;while(first<path.size()&&domains.get(path.get(first))!=r.domain)first++;
        for(int i=first;i+1<path.size()&&domains.get(path.get(i))==r.domain;i++){
            var allowed=exits.get(path.get(i));var choices=allowed==null?null:allowed.get(r.slot);
            if(choices!=null&&!choices.contains(path.get(i+1)))return "occupancy_reserved_terminal_slot";
        }
        if(temporalRoute(path,at,r.length,r.maximumSpeed,Id.create(r.nativeQueue,Lane.class),true).status()==Feasibility.IMPOSSIBLE)
            return "occupancy_incompatible_passage_signals";
        return null;
    }
    /** Prove only an immediate two-head storage cycle, not a forecast of future
     * congestion. Both heads must really be offered in their committed slots,
     * with reciprocal turns. A red signal, native inflow debt, or a merely full
     * queue is not proof that a route is impossible. */
    private String opposedReturnIssue(Id<Vehicle> vehicle,List<Id<Link>> path,int at,
            org.matsim.core.mobsim.qsim.interfaces.NetsimNetwork qnet) {
        var r=active.get(vehicle);
        if(r==null||qnet==null||at+1>=path.size()||r.passage!=null&&!r.passage.released)return null;
        var from=network.getLinks().get(path.get(at));var to=network.getLinks().get(path.get(at+1));
        if(from.getFromNode()!=to.getToNode()||from.getToNode()!=to.getFromNode())return null;
        if(!(qnet.getNetsimLinks().get(from.getId()) instanceof QLinkI source)||
                !(qnet.getNetsimLinks().get(to.getId()) instanceof QLinkI target))return null;
        if(offeredReservationHead(source,r)==null)return null;
        // Read only the opposite offered heads, never a global vehicle scan.
        for(var lane:target.getOfferingQLanes()) {
            if(lane.isNotOfferingVehicle())continue;
            var other=lane.getFirstVehicle();var peer=active.get(other.getId());
            if(peer==null||peer==r||peer.domain==r.domain||peer.passage!=null&&!peer.passage.released||
                    !peer.link.equals(to.getId())||offeredReservationHead(target,peer)!=other)continue;
            var peerPath=plannedPath(other);if(peerPath==null)continue;
            int peerAt=peerPath.indexOf(peer.link);
            if(peerAt<0||peerAt!=peerPath.lastIndexOf(peer.link)||peerAt+1>=peerPath.size()||
                    !peerPath.get(peerAt+1).equals(from.getId())||
                    !from.getId().equals(other.getDriver().chooseNextLinkId()))continue;
            if(receiptDependsOnHead(r,path,at+1,peer,target)&&receiptDependsOnHead(peer,peerPath,peerAt+1,r,source))
                return "occupancy_opposed_return_cycle";
        }
        return null;
    }
    private QVehicle offeredReservationHead(QLinkI link,Reservation r) {
        for(var lane:link.getOfferingQLanes()) {
            if(lane.isNotOfferingVehicle()||!lane.getId().toString().equals(r.nativeQueue))continue;
            var head=lane.getFirstVehicle();
            if(!head.getId().equals(r.vehicle))continue;
            if(terminalMatchesSlot(r.link,r.nativeQueue,r.slot)||
                    r.domain.lanes==1&&laneIndices.getOrDefault(r.link,Map.of()).isEmpty())return head;
        }
        return null;
    }
    /** Can this receipt become available while the opposing head remains?
     * Use an optimistic bound: unrelated bodies may all leave, and the head
     * and its FIFO followers may advance to the end of their current link.
     * Reject only if even that bound cannot receive the new body. */
    private boolean receiptDependsOnHead(Reservation incoming,List<Id<Link>> path,int at,Reservation holder,QLinkI holdingLink) {
        var target=path.get(at);var d=domains.get(target);
        if(d!=holder.domain||d==incoming.domain||!target.equals(holder.link))return false;
        double need=incoming.length+GAP+conflictMargin(network.getLinks().get(target),network.getLinks().get(target).getFromNode());
        // Compare in domain coordinates with the ledger's storage tolerance.
        // Subtracting an interior offset can round an exact body+GAP receipt
        // just below need (2.1999999999999993 vs 2.2), hiding a proven cycle.
        if(routeReach(path,at,d).front()<d.offsets.get(target)+need-1e-8)return false;
        // Short passages and ambiguous future revisits need a different proof;
        // do not convert uncertain reception into a blanket U-turn ban.
        if(path.subList(at+1,path.size()).contains(target))return false;
        var slots=new TreeSet<Integer>();for(int slot=0;slot<d.lanes;slot++)slots.add(slot);
        for(int i=at;i+1<path.size()&&domains.get(path.get(i))==d;i++) {
            var allowed=exits.get(path.get(i));if(allowed==null||allowed.isEmpty())continue;
            final var next=path.get(i+1);
            slots.removeIf(slot->!allowed.getOrDefault(slot,Set.of()).contains(next));
        }
        if(!slots.equals(Set.of(holder.slot)))return false; // another compatible lane can break the cycle
        // Same interior-entry rule as choose(): no insertion ahead of an
        // existing reserved body, irrespective of unused metres downstream.
        if(d.offsets.get(target)>1e-8)return true;
        double held=holder.footprint;
        for(var body:d.reservations.get(holder.slot).tailMap(holder.ordinal,false).values()) {
            if(!body.link.equals(holder.link)||body.passage!=null&&!body.passage.released)continue;
            var queued=holdingLink.getVehicle(body.vehicle);
            // A final activity can leave a native travelling queue before the
            // head crosses. Transit also has a separate stop/exit lifecycle.
            // Neither is a proved FIFO-dependent contribution to this bound.
            if(queued==null)continue;
            var driver=queued.getDriver();
            if(driver==null||driver instanceof org.matsim.core.mobsim.qsim.pt.TransitDriverAgent||
                    driver.isWantingToArriveOnCurrentLink())continue;
            held+=body.footprint;
        }
        double maximumFront=Math.min(d.capacity,d.offsets.get(holder.link)+network.getLinks().get(holder.link).getLength());
        return maximumFront-held<d.offsets.get(target)+need-1e-8||held+incoming.footprint>d.capacity+1e-8;
    }
    private record RouteMovement(Id<Link> from,Id<Link> to) { }
    private List<Id<org.matsim.lanes.Lane>> movementLanes(RouteMovement movement) {
        var result=new ArrayList<Id<org.matsim.lanes.Lane>>();
        var allowed=exits.getOrDefault(movement.from(),Map.of());
        for(var lane:laneIndices.getOrDefault(movement.from(),Map.of()).entrySet())
            if(allowed.getOrDefault(lane.getValue(),Set.of()).contains(movement.to()))
                result.add(Id.create(lane.getKey(),org.matsim.lanes.Lane.class));
        result.sort(Comparator.comparingInt(id->laneIndices.get(movement.from()).get(id.toString())));
        // An unrepresented lane cannot prove a signal restriction.
        return result.isEmpty()?java.util.Collections.singletonList(null):result;
    }
    private Set<Integer> compatibleSlots(QVehicle vehicle,Domain d,Id<Link> target) {
        var all=new TreeSet<Integer>();for(int i=0;i<d.lanes;i++)all.add(i);
        var ids=plannedPath(vehicle);if(ids==null)return all;
        // A route may leave at an interior subdivision (e.g. an allowed U-turn).
        // Freeze a slot against each native movement it will actually traverse,
        // never the permissions of a distant, unvisited corridor endpoint.
        // Any still-ambiguous future occurrences remain conservative. Traversed
        // occurrences were excluded using the native cursor in plannedPath.
        for(int i=0;i<ids.size();i++)if(ids.get(i).equals(target)) {
            for(int j=i;j+1<ids.size()&&domains.get(ids.get(j))==d;j++) {
                var allowed=exits.get(ids.get(j));if(allowed==null||allowed.isEmpty())continue;
                var next=ids.get(j+1);
                all.removeIf(slot->!allowed.containsKey(slot)||!allowed.get(slot).contains(next));
            }
        }
        return all;
    }
    private int choose(QVehicle vehicle,Id<Link> target,String lane) {
        return choose(vehicle,target,lane,slot->true);
    }
    private int choose(QVehicle vehicle,Id<Link> target,String lane,java.util.function.IntPredicate usable) {
        var d=domains.get(target);if(d==null)return -2;var old=active.get(vehicle.getId());
        var connectorOwner=connectorLocks.get(target);if(connectorOwner!=null&&!connectorOwner.equals(vehicle.getId()))return -1;
        if(old!=null&&old.passage!=null&&!old.passage.released&&old.passage.offsets.containsKey(target)) {
            Integer terminal=laneIndices.getOrDefault(target,Map.of()).get(lane);
            return terminal==null||terminal.equals(old.passage.slots.get(target))?old.slot:-1;
        }
        var owner=receiptLocks.get(d);if(owner!=null&&!owner.equals(vehicle.getId())&&(old==null||old.domain!=d))return -1;
        Integer terminal=laneIndices.getOrDefault(target,Map.of()).get(lane);
        Set<Integer> slots=terminal==null ? compatibleSlots(vehicle,d,target) : Set.of(terminal);
        // No lateral reassignment is inferred inside a corridor. The entry slot
        // is chosen against the downstream terminal turn permissions.
        if(old!=null&&old.domain==d)slots=slots.contains(old.slot)?Set.of(old.slot):Set.of();
        double size=length(vehicle)+GAP;int chosen=-1;double least=Double.POSITIVE_INFINITY;
        for(int slot:slots) {
            if(!usable.test(slot))continue;
            double current=d.used[slot]-(old!=null&&old.domain==d&&old.slot==slot?old.footprint:0);
            // Entering at an interior route point cannot jump ahead of an older
            // reservation. Reserve an empty slot, preserving native entry order.
            if((old==null||old.domain!=d)&&d.offsets.get(target)>1e-8&&current>1e-8)continue;
            double clear=d.offsets.get(target)+entryClearanceDistance(vehicle,target);
            if((old==null||old.domain!=d)&&freeFront(d,slot,null)<clear-1e-8)continue;
            if(current+size<=d.capacity+1e-8 && (old!=null&&old.domain==d&&old.slot==slot || current<least)) {
                chosen=slot;least=current;if(old!=null&&old.domain==d&&old.slot==slot)break;
            }
        }
        return chosen;
    }
    /** Identify an existing parallel slot at a native original-to-terminal split.
     * This does not choose a new lane or change a reservation. Connector bodies
     * and retained-origin exits remain barriers. Once native entry has reached
     * the actual receiver, the existing receiving slot is already unambiguous:
     * requiring passage release here would make clearance depend on itself. */
    int originalSlot(QVehicle vehicle,Id<Link> link,String queue) {
        var r=active.get(vehicle.getId());var d=domains.get(link);
        var terminals=laneIndices.getOrDefault(link,Map.of());
        if(r==null||d==null||r.domain!=d||!r.link.equals(link)||!queue.equals(r.nativeQueue)
                ||d.lanes<2||terminals.size()!=d.lanes)return -1;
        var p=r.passage;
        if(p!=null&&!p.released&&(p.receipt==null||domains.get(p.receipt.getId())!=d||p.offsets.containsKey(link)
                ||d.offsets.get(link)<d.offsets.get(p.receipt.getId())||r.nativeFront<d.offsets.get(link)))return -1;
        return r.slot;
    }
    boolean terminalMatchesSlot(Id<Link> link,String queue,int slot) {
        return Objects.equals(laneIndices.getOrDefault(link,Map.of()).get(queue),slot);
    }
    /** A physical feasibility result is not a right of way or an admission.
     * Queries never change reservations, pending entries, timers or events. */
    public record PhysicalFeasibility(boolean feasible,String reason) { }
    private record PhysicalPlan(Passage passage,int slot,String reason) {
        boolean feasible(){return reason==null;}
    }
    private static PhysicalPlan blocked(String reason){return new PhysicalPlan(null,-1,reason);}

    /** Full receiver probe used by priority. It reads native queues and signals,
     * but never calls canEnter, preparePassage, passageClear or priority logic.
     * Downstream right of way is still decided only during real admission. */
    public static PhysicalFeasibility receiverFeasibility(QSimConfigGroup config,QVehicle vehicle,
            Id<Link> target,String lane,QNetwork network,double now) {
        var qlink=network.getNetsimLinks().get(target);
        if(qlink==null)return new PhysicalFeasibility(false,"receiver_missing");
        if(!qlink.getAcceptingQLane().isAcceptingFromUpstream())return new PhysicalFeasibility(false,"receiver_native_storage");
        var ledger=config==null?null:get(config);
        if(ledger==null)return new PhysicalFeasibility(true,"receiver_available");
        var plan=ledger.physicalPlan(vehicle,target,lane,network,true);
        String issue=plan.reason;
        if(issue==null&&plan.passage!=null)issue=ledger.passagePhysicalIssue(vehicle,plan.passage,now,null,network);
        return new PhysicalFeasibility(issue==null,issue==null?"receiver_available":issue);
    }
    /** Compatibility metric-only probe for callers without a native network.
     * Priority must use receiverFeasibility, including native receiving queues. */
    public static boolean receiverNotKnownBlocked(QSimConfigGroup config,QVehicle vehicle,Id<Link> target,String lane) {
        var ledger=config==null?null:get(config);
        return ledger==null||ledger.physicalPlan(vehicle,target,lane,null,false).feasible();
    }
    private PhysicalPlan physicalPlan(QVehicle vehicle,Id<Link> target,String lane,QNetwork qnet,boolean nativeReceipt) {
        var d=domains.get(target);if(d==null)return new PhysicalPlan(null,-2,null);
        var old=active.get(vehicle.getId());
        boolean own=old!=null&&old.domain==d;
        boolean passage=old!=null&&old.passage!=null&&!old.passage.released&&old.passage.offsets.containsKey(target);
        // A node lock forbids a new entry, not progress of bodies already in
        // the receiving domain or inside their own authorized passage.
        if(!own&&!passage&&lockedByOther(network.getLinks().get(target).getFromNode().getId(),vehicle.getId()))return blocked("passage_node_locked");
        if(!own&&!passage&&routeReach(vehicle,target).front()-d.offsets.get(target)<entryClearanceDistance(vehicle,target)) {
            var description=describePassagePlan(vehicle,target);if(!description.feasible())return description;
            var p=description.passage;
            Integer terminal=laneIndices.getOrDefault(target,Map.of()).get(lane);
            if(terminal!=null&&!terminal.equals(p.slots.get(target)))return blocked("passage_terminal_slot");
            if(p.receipt==null)return new PhysicalPlan(p,old.slot,null);
            var receipt=domains.get(p.receipt.getId());
            int slot=choose(vehicle,p.receipt.getId(),"",s->freeFront(receipt,s,old)>=p.clearFront-1e-8);
            if(slot<0)return blocked("passage_receipt_storage_or_slot");
            if(nativeReceipt) {
                // Choose among physically usable slots. A blocked terminal in
                // the least-loaded slot must not hide a free compatible lane.
                slot=choose(vehicle,p.receipt.getId(),"",s->freeFront(receipt,s,old)>=p.clearFront-1e-8&&receiptQueuesClear(p,s,qnet));
                if(slot<0)return blocked("passage_receipt_native_queue");
            }
            p.freeFront=freeFront(receipt,slot,old);
            return new PhysicalPlan(p,slot,null);
        }
        int slot=choose(vehicle,target,lane);
        return slot<0?blocked("receiver_storage_or_terminal_slot"):new PhysicalPlan(null,slot,null);
    }
    /** Parallel heads of the same entrance movement are arbitrated by the real
     * node before either acquires its whole passage. Looking ahead to a return
     * at that same node must not make those equivalent requests veto each
     * other. This only recognizes identical connector/receipt paths, with
     * different existing slots; it grants no entry, priority or storage. The
     * first native admission locks the passage before the other is examined.
     * Distinct approaches, different paths and ordinary receivers still compete.
     */
    public static boolean sameParallelPassageEntrance(QSimConfigGroup config,QVehicle requester,QVehicle competitor,
            Id<Link> from,Id<Link> to) {
        var ledger=config==null?null:get(config);if(ledger==null)return false;
        var a=ledger.active.get(requester.getId());var b=ledger.active.get(competitor.getId());
        if(a==null||b==null||a.domain!=b.domain||!a.link.equals(b.link)||a.slot==b.slot||a.domain.lanes<2)return false;
        if(!ledger.terminalMatchesSlot(a.link,a.nativeQueue,a.slot)||!ledger.terminalMatchesSlot(b.link,b.nativeQueue,b.slot))return false;
        var pa=ledger.plannedPath(requester);var pb=ledger.plannedPath(competitor);
        if(pa==null||pb==null||pa.size()<2||pb.size()<2||!pa.get(0).equals(a.link)||!pb.get(0).equals(b.link)||!pa.get(1).equals(pb.get(1)))return false;
        var da=ledger.domains.get(pa.get(1));
        if(da==null||ledger.routeReach(requester,pa.get(1)).front()-da.offsets.get(pa.get(1))>=ledger.entryClearanceDistance(requester,pa.get(1))
                ||ledger.routeReach(competitor,pb.get(1)).front()-da.offsets.get(pb.get(1))>=ledger.entryClearanceDistance(competitor,pb.get(1)))return false;
        var first=ledger.describePassage(requester,pa.get(1));var other=ledger.describePassage(competitor,pb.get(1));
        if(first==null||other==null||first.receipt==null||first.receipt!=other.receipt||!first.links.equals(other.links)||!first.slots.equals(other.slots))return false;
        for(int i=0;i<first.links.size();i++)if(first.links.get(i).getId().equals(from))
            return (i+1<first.links.size()?first.links.get(i+1):first.receipt).getId().equals(to);
        return false;
    }
    /** A native final activity traverses only this prefix, not the unvisited
     * remainder of its storage domain. The existing origin reservation keeps
     * the full body until native arrival. The downstream tail (including GAP)
     * must be beyond the entire terminal link; no fictitious receipt is used.
     * Pure necessary-space query, also safe for priority competition. */
    private int terminalExitSlot(QVehicle vehicle,Id<Link> target) {
        var old=active.get(vehicle.getId());if(old==null)return -1;
        var path=plannedPath(vehicle);
        if(path==null||!path.get(path.size()-1).equals(target)||path.indexOf(target)!=path.size()-1)return -1;
        var d=domains.get(target);var owner=receiptLocks.get(d);
        if(owner!=null&&!owner.equals(vehicle.getId()))return -1;
        owner=connectorLocks.get(target);if(owner!=null&&!owner.equals(vehicle.getId()))return -1;
        double end=d.offsets.get(target)+network.getLinks().get(target).getLength();
        for(int slot:compatibleSlots(vehicle,d,target))if(freeFront(d,slot,old)>=end-1e-8)return slot;
        return -1;
    }
    boolean canEnter(QVehicle vehicle,Id<Link> target,String lane,double now) {
        return canEnter(vehicle,target,lane,now,null);
    }
    private boolean canEnter(QVehicle vehicle,Id<Link> target,String lane,double now,String activityBufferQueue) {
        // An unsuccessful recheck must not leave an older admission staged.
        pending.remove(vehicle.getId());pendingPassages.remove(vehicle.getId());
        var previousRequest=passageRequests.get(vehicle.getId());
        if(previousRequest!=null&&!Objects.equals(previousRequest.path(),plannedPath(vehicle))){
            passageRequests.remove(vehicle.getId());passageRequestTime.remove(vehicle.getId());
        }
        var d=domains.get(target);var plan=physicalPlan(vehicle,target,lane,null,true);
        String issue=plan.reason;
        if(issue==null&&plan.passage!=null)issue=preparePassage(vehicle,target,plan.passage,now,activityBufferQueue);
        if(issue==null) {
            if(plan.slot==-2)return true;
            waitReasons.remove(vehicle.getId());
            if(plan.passage!=null)pendingPassages.put(vehicle.getId(),plan.passage);
            pending.put(vehicle.getId(),new Pending(target,lane,plan.slot));return true;
        }
        // Emit when the cause changes too; a previous stop hold must not hide
        // a subsequently discovered impossible route or occupied receipt.
        String cause=d.id+"\0"+issue;
        if(!cause.equals(waitReasons.put(vehicle.getId(),cause)))transaction(now,"WAIT",vehicle.getId(),target,new Reservation(d,-1,length(vehicle),0,target),-1,issue);
        return false;
    }
    /** Read-only body offer at the actual activity-buffer anchor. This is not
     * flow credit, a reservation, a signal/priority permission or a movement. */
    record OriginOffer(boolean applicable,boolean feasible,int slot,double insertionFront,String reason) { }
    OriginOffer originOffer(QVehicle vehicle,Id<Link> link,String lane,double now) {
        var d=domains.get(link);var road=network.getLinks().get(link);
        if(d==null||road==null)return new OriginOffer(false,false,-1,Double.NaN,"legacy_unmanaged_origin");
        var driver=vehicle.getDriver();
        if(driver==null||driver instanceof org.matsim.core.mobsim.qsim.pt.TransitDriverAgent
                ||driver.isWantingToArriveOnCurrentLink())
            return new OriginOffer(false,false,-1,Double.NaN,"legacy_metric_transit_or_terminal_activity");
        var endpoints=queueEnds.get(link);
        if(!Objects.equals(lane,link+".original")||endpoints==null||!endpoints.containsKey(lane))
            return new OriginOffer(false,false,-1,Double.NaN,"legacy_unrepresented_queue");
        var path=plannedPath(vehicle);String mode=driver.getMode();
        if(path==null||path.size()<2||!path.get(0).equals(link)||!link.equals(driver.getCurrentLinkId()))
            return new OriginOffer(true,false,-1,Double.NaN,"origin_route_or_cursor");
        if(mode==null||!road.getAllowedModes().contains(mode))
            return new OriginOffer(true,false,-1,Double.NaN,"origin_mode");
        double width=vehicle.getVehicle().getType().getWidth();
        if(!Double.isFinite(width)||width<=0||width>NOMINAL_LANE_WIDTH)
            return new OriginOffer(true,false,-1,Double.NaN,"origin_nominal_width");
        double pcu=vehicle.getVehicle().getType().getPcuEquivalents();
        if(!Double.isFinite(pcu)||pcu<=0)
            return new OriginOffer(true,false,-1,Double.NaN,"origin_invalid_pcu");
        var accessible=new TreeSet<Integer>();for(int slot=0;slot<d.lanes;slot++)accessible.add(slot);
        for(int i=0;i+1<path.size()&&domains.get(path.get(i))==d;i++) {
            var from=network.getLinks().get(path.get(i));var to=network.getLinks().get(path.get(i+1));
            if(from==null||to==null||from.getToNode()!=to.getFromNode()||!to.getAllowedModes().contains(mode))
                return new OriginOffer(true,false,-1,Double.NaN,"origin_direction_or_mode");
            // A permissive legacy fallback for absent lane metadata does not
            // prove independent storage for an occupied-slot extension.
            var indices=laneIndices.get(path.get(i));var permissions=exits.get(path.get(i));
            if(indices==null||permissions==null||indices.size()!=d.lanes||permissions.size()!=d.lanes)
                return new OriginOffer(false,false,-1,Double.NaN,"legacy_unrepresented_movement");
            for(int slot=0;slot<d.lanes;slot++)if(!indices.containsValue(slot)||!permissions.containsKey(slot))
                return new OriginOffer(false,false,-1,Double.NaN,"legacy_unrepresented_movement");
            var connected=originSlots.get(path.get(i));
            if(connected==null)return new OriginOffer(false,false,-1,Double.NaN,"legacy_unrepresented_movement");
            accessible.retainAll(connected);
        }
        double offset=d.offsets.get(link),endpoint=endpoints.get(lane);
        double front=Math.min(d.capacity,offset+endpoint),need=entryClearanceDistance(vehicle,link);
        double size=length(vehicle)+GAP,reach=routeReach(vehicle,link).front();
        if(!Double.isFinite(d.capacity)||!Double.isFinite(offset)||!Double.isFinite(endpoint)||!Double.isFinite(front)
                ||!Double.isFinite(need)||!Double.isFinite(size)||!Double.isFinite(reach))
            return new OriginOffer(true,false,-1,Double.NaN,"origin_nonfinite_geometry");
        // Short sources retain the complete native passage/stop/receipt path.
        if(front-offset<need-1e-8||reach-offset<need-1e-8)
            return new OriginOffer(false,false,-1,front,"legacy_short_origin_or_passage");
        // A sufficient body prefix cannot justify an anchor beyond the actual
        // route occurrence's stopping boundary. Never move that anchor to fit.
        if(front>reach+1e-8)
            return new OriginOffer(true,false,-1,front,"origin_anchor_beyond_route_reach");
        if(active.containsKey(vehicle.getId()))return new OriginOffer(true,false,-1,front,"origin_already_reserved");
        if(lockedByOther(road.getFromNode().getId(),vehicle.getId())
                ||connectorLocks.containsKey(link)||receiptLocks.containsKey(d))
            return new OriginOffer(true,false,-1,front,"origin_conflict_or_passage_lock");
        int chosen=-1;double least=Double.POSITIVE_INFINITY;
        for(int slot:compatibleSlots(vehicle,d,link)) {
            // All older bodies, including ones upstream, must be ahead of
            // this insertion. Total unused metres alone never grant entry.
            if(!accessible.contains(slot))continue;
            double free=freeFront(d,slot,null),used=d.used[slot];
            if(!Double.isFinite(free)||!Double.isFinite(used)||used < -1e-8
                    ||free<front-1e-8||used+size>d.capacity+1e-8)continue;
            if(d.used[slot]<least){least=d.used[slot];chosen=slot;}
        }
        return new OriginOffer(true,chosen>=0,chosen,front,chosen>=0?"origin_accessible_gap":"origin_no_compatible_accessible_gap");
    }
    /** Synchronous reservation commit immediately before the native wait-head
     * poll. Native flow remains in QueueWithBuffer; addFromWait debits it once.
     * In particular, the travelling-queue PCU gate is not the activity buffer. */
    boolean activityFromWait(QVehicle vehicle,Id<Link> link,String lane,double now) {
        if(!physicalGapOrigin)return activity(vehicle,link,lane,now);
        // Invalidate staging even if malformed current route/body data throws.
        pending.remove(vehicle.getId());pendingPassages.remove(vehicle.getId());
        var offer=originOffer(vehicle,link,lane,now);
        if(!offer.applicable())return activity(vehicle,link,lane,now);
        var previousRequest=passageRequests.get(vehicle.getId());
        if(previousRequest!=null&&!Objects.equals(previousRequest.path(),plannedPath(vehicle))){
            passageRequests.remove(vehicle.getId());passageRequestTime.remove(vehicle.getId());
        }
        if(!offer.feasible()) {
            var d=domains.get(link);String cause=d.id+"\0"+offer.reason();
            if(!cause.equals(waitReasons.put(vehicle.getId(),cause)))
                transaction(now,"WAIT",vehicle.getId(),link,new Reservation(d,-1,length(vehicle),0,link),-1,offer.reason());
            return false;
        }
        waitReasons.remove(vehicle.getId());
        passageRequests.remove(vehicle.getId());passageRequestTime.remove(vehicle.getId());
        pending.put(vehicle.getId(),new Pending(link,lane,offer.slot()));
        enter(vehicle,link,lane,now,"activity");
        // Future rerouting must retain the anchor already committed here.
        var reservation=active.get(vehicle.getId());
        reservation.admissionClearFront=Math.max(reservation.admissionClearFront,offer.insertionFront());
        return true;
    }
    boolean activity(QVehicle vehicle,Id<Link> link,String lane,double now) {
        // This call comes from this named queue's isAcceptingFromWait. Its
        // addFromWait insertion is at the buffer, unlike upstream admission.
        if(!canEnter(vehicle,link,lane,now,lane))return false;
        var selected=pending.get(vehicle.getId());var passage=pendingPassages.get(vehicle.getId());var d=passage!=null&&passage.receipt==null?active.get(vehicle.getId()).domain:domains.get(passage==null?link:passage.receipt.getId());
        if(selected!=null&&d.used[selected.slot()]>1e-8&&!active.containsKey(vehicle.getId())){
            pending.remove(vehicle.getId());pendingPassages.remove(vehicle.getId());
            if(waits.add(vehicle.getId()+"\0"+d.id)){var waiting=new Reservation(d,-1,length(vehicle),0,link);waiting.passage=passage;
                transaction(now,"WAIT",vehicle.getId(),link,waiting,-1,"activity_requires_empty_model_slot");}return false;}
        enter(vehicle,link,lane,now,"activity");return true;
    }
    void enter(QVehicle vehicle,Id<Link> link,String lane,double now,String reason) {
        var d=domains.get(link);if(d==null)return;
        var passage=pendingPassages.remove(vehicle.getId());var existing=active.get(vehicle.getId());
        if(passage!=null)d=passage.receipt==null?existing.domain:domains.get(passage.receipt.getId());
        else if(existing!=null&&existing.passage!=null&&!existing.passage.released&&existing.passage.offsets.containsKey(link))d=existing.domain;
        var selected=pending.remove(vehicle.getId());int slot=selected!=null&&selected.link().equals(link)&&selected.lane().equals(lane)?selected.slot():choose(vehicle,link,lane);
        if(slot<0)throw new IllegalStateException("OCCUPANCY_UNRESERVED_INSERTION: "+vehicle.getId()+" at "+link);
        var old=active.get(vehicle.getId());
        if(old!=null && old.domain==d && (passage==null||passage.receipt==null)) {
            int previous=old.slot;if(previous!=slot){d.used[previous]-=old.footprint;d.used[slot]+=old.footprint;d.reservations.get(previous).remove(old.ordinal);d.reservations.get(slot).put(old.ordinal,old);}old.slot=slot;old.link=link;
            if(passage!=null)acquirePassage(vehicle.getId(),old,passage,link);
            transaction(now,"TRANSFER",vehicle.getId(),link,old,previous,reason);
            if(passage!=null)passageEvent(now,"ACQUIRE",vehicle.getId(),old);nativeEntry(old,lane,now);return;
        }
        if(old!=null)release(vehicle.getId(),now,"node_transfer");
        var next=new Reservation(d,slot,length(vehicle),++nextOrdinal,link);
        next.admissionClearFront=passage==null?d.offsets.get(link)+entryClearanceDistance(vehicle,link):passage.clearFront;
        next.vehicle=vehicle.getId();next.maximumSpeed=vehicle.getVehicle().getType().getMaximumVelocity();active.put(vehicle.getId(),next);d.used[slot]+=next.footprint;d.reservations.get(slot).put(next.ordinal,next);
        if(passage!=null)acquirePassage(vehicle.getId(),next,passage,link);
        waits.remove(vehicle.getId()+"\0"+d.id);transaction(now,"ENTER",vehicle.getId(),link,next,-1,reason);
        if(passage!=null)passageEvent(now,"ACQUIRE",vehicle.getId(),next);
        nativeEntry(next,lane,now);
    }
    private void acquirePassage(Id<Vehicle> vehicle,Reservation reservation,Passage passage,Id<Link> link){
        reservation.passage=passage;reservation.frontBound=passage.offsets.get(link);reservation.nativeFront=reservation.frontBound;passageRequestTime.remove(vehicle);passageRequests.remove(vehicle);
        for(var node:passage.nodes){var previous=nodeLocks.put(node,vehicle);if(previous!=null&&!previous.equals(vehicle))throw new IllegalStateException("Passage lock race");}
        for(var connector:passage.links)connectorLocks.put(connector.getId(),vehicle);
        if(passage.receipt!=null)receiptLocks.put(reservation.domain,vehicle);
        // Existing downstream bodies may leave. New entries/activities may not
        // consume the exit prefix while its body is still reserved at origin.
        else receiptLocks.put(domains.get(passage.links.get(passage.links.size()-1).getId()),vehicle);
        if(passage.receipt!=null)passageDeadlines.add(new PassageDeadline(passage.notBefore,reservation.ordinal,vehicle,passage));
    }
    void release(Id<Vehicle> id,double now,String reason) {
        waitReasons.remove(id);
        var old=active.remove(id);pending.remove(id);pendingPassages.remove(id);passageRequestTime.remove(id);passageRequests.remove(id);if(old==null)return;
        releasePassage(id,old,now);
        old.domain.reservations.get(old.slot).remove(old.ordinal);
        old.domain.used[old.slot]-=old.footprint;if(Math.abs(old.domain.used[old.slot])<1e-8)old.domain.used[old.slot]=0;
        transaction(now,"EXIT",id,old.link,old,old.slot,reason);
        recompute(old.domain,old.slot,now,"leader_release");
    }
    void clearLink(Id<Link> link,double now) {
        for(var id:new ArrayList<>(active.keySet()))if(active.get(id).link.equals(link))release(id,now,"clear");
    }
    /** Conservative model coordinate inferred from native buffer arrival and
     * earlier reservations. This is not a measured microscopic position. */
    void progress(QVehicle vehicle,Id<Link> link,String lane,double now) {
        progress(vehicle,link,lane,now,"buffer_arrival");
    }
    void advanceEligible(Iterable<QVehicle> vehicles,Id<Link> link,String lane,double now){
        advanceTime(now);
        for(var vehicle:vehicles){var r=active.get(vehicle.getId());if(r==null||vehicle.getEarliestLinkExitTime()>now)continue;
            double bound=queueEndpoint(r,link,lane);
            if(bound>r.nativeFront+1e-8)progress(vehicle,link,lane,now,"native_earliest_exit_reached");
        }
    }
    /** Time is a separate release condition from physical progress. A vehicle
     * already in a native buffer may never emit another endpoint update.
     * Consume each deadline once; if the body is still uncleared, recompute()
     * keeps responsibility for releasing after later real modeled progress.
     * Boundary exits deliberately retain their locks until native traffic exit.
     */
    void advanceTime(double now){
        while(!passageDeadlines.isEmpty()&&passageDeadlines.peek().time()<=now){
            var due=passageDeadlines.remove();var r=active.get(due.vehicle());
            if(r==null||r.ordinal!=due.ordinal()||r.passage!=due.passage()||r.passage.released)continue;
            if(r.passage.receipt!=null&&now>=r.passage.notBefore&&r.frontBound>=r.passage.clearFront)
                releasePassage(r.vehicle,r,now);
            else passageWaiting(r,now);
        }
    }
    private double queueEndpoint(Reservation r,Id<Link> link,String lane){
        var l=network.getLinks().get(link);double offset=r.passage!=null&&r.passage.offsets.containsKey(link)?r.passage.offsets.get(link):r.domain.offsets.get(link);
        double bound=offset+queueEnds.getOrDefault(link,Map.of()).getOrDefault(lane,l.getLength());
        return r.passage==null||r.passage.receipt!=null?Math.min(r.domain.capacity,bound):bound;
    }
    /** Arrival is not physical progress. A ready native queue clock cannot
     * remove a body still held behind an earlier reservation in another queue
     * of this domain. Pure query; ordinary progress/release hooks advance it. */
    boolean arrivalReady(QVehicle vehicle,Id<Link> link,String lane){
        var r=active.get(vehicle.getId());
        return r==null||r.frontBound+1e-8>=queueEndpoint(r,link,lane);
    }
    private void progress(QVehicle vehicle,Id<Link> link,String lane,double now,String reason) {
        var r=active.get(vehicle.getId());if(r==null)return;
        r.nativeFront=Math.max(r.nativeFront,queueEndpoint(r,link,lane));r.nativeQueue=lane;
        if(reason.equals("native_earliest_exit_reached"))recompute(r.domain,r.slot,now,reason,vehicle.getId(),vehicle.getEarliestLinkExitTime());
        else recompute(r.domain,r.slot,now,reason);
    }
    private double freeFront(Domain d,int slot,Reservation exclude){double bound=d.capacity;for(var r:d.reservations.get(slot).values())if(r!=exclude)bound=Math.min(bound,r.frontBound-r.footprint);return bound;}
    private void nativeEntry(Reservation r,String lane,double now){
        double offset=r.passage!=null&&r.passage.offsets.containsKey(r.link)?r.passage.offsets.get(r.link):r.domain.offsets.get(r.link);
        double nativeStart=offset+queueStarts.getOrDefault(r.link,Map.of()).getOrDefault(lane,0.);
        if(r.passage==null||r.passage.receipt!=null)nativeStart=Math.min(r.domain.capacity,nativeStart);
        r.nativeFront=Math.max(r.nativeFront,nativeStart);r.nativeQueue=lane;
        recompute(r.domain,r.slot,now,"queue_entry");
    }
    private void recompute(Domain d,int slot,double now,String reason){recompute(d,slot,now,reason,null,null);}
    private void recompute(Domain d,int slot,double now,String reason,Id<Vehicle> trigger,Double earliest){Reservation leader=null;
        for(var r:d.reservations.get(slot).values()){
            double bound=leader==null?r.nativeFront:Math.min(r.nativeFront,leader.frontBound-leader.footprint);
            if(bound<r.frontBound-1e-8)throw new IllegalStateException("OCCUPANCY_QUEUE_ORDER_REVERSED: "+r.vehicle);
            r.frontBound=bound;var attrs=new LinkedHashMap<String,String>();attrs.put("policy",POLICY);attrs.put("vehicle",r.vehicle.toString());
            attrs.put("corridor",d.id);attrs.put("link",r.link.toString());attrs.put("nativeQueue",r.nativeQueue);attrs.put("modeledFrontLowerBoundMeters",Double.toString(bound));
            attrs.put("nativeFrontBoundMeters",Double.toString(r.nativeFront));attrs.put("reason",trigger!=null&&!trigger.equals(r.vehicle)?"leader_progress":reason);attrs.put("positionsObserved","false");attrs.put("source","native_queue_endpoint_and_leader_reservation_order");
            if(trigger!=null){attrs.put("triggerVehicle",trigger.toString());if(trigger.equals(r.vehicle))attrs.put("nativeEarliestLinkExitTime",Double.toString(earliest));}
            if(leader!=null){attrs.put("leaderVehicle",leader.vehicle.toString());attrs.put("leaderFrontLowerBoundMeters",Double.toString(leader.frontBound));attrs.put("leaderFootprintMeters",Double.toString(leader.footprint));}
            emit(now,"simz1OccupancyProgress",attrs);
            if(r.passage!=null&&!r.passage.released&&r.passage.receipt!=null&&now>=r.passage.notBefore&&bound>=r.passage.clearFront)releasePassage(r.vehicle,r,now);
            else passageWaiting(r,now);
            leader=r;
        }
    }
    /** Observations only: neither an admission probe nor a progress/release hook.
     * The caller has just rejected this native receiver. Restrict attribution to
     * queue dynamics, where QueueWithBuffer's rejection means occupied storage;
     * inflow debt in other dynamics must not be mislabeled as storage.
     * This includes the original-to-terminal split inside a receiving link. */
    void passageStorageWait(QVehicle vehicle,Id<Link> from,String lane,Id<Link> target,QLaneI receiver,double now){
        var r=active.get(vehicle.getId());
        if(r==null||r.passage==null||r.passage.released||r.passage.receipt==null
                ||r.frontBound>=r.passage.clearFront
                ||!r.link.equals(from)||!r.nativeQueue.equals(lane)
                ||!(receiver instanceof QueueWithBuffer)
                ||trafficDynamics!=QSimConfigGroup.TrafficDynamics.queue)return;
        double used=receiver.getLoadIndicator(),capacity=receiver.getStorageCapacity();
        if(!Double.isFinite(used)||!Double.isFinite(capacity)||used<capacity)return;
        passageDiagnostic(r,now,"passage_waiting_for_downstream_storage",target,receiver.getId().toString(),used,capacity);
    }
    private void passageWaiting(Reservation r,double now){
        var p=r.passage;if(p==null||p.released||p.receipt==null)return;
        String reason=now<p.notBefore?"passage_waiting_for_time":
            r.nativeFront<p.clearFront?"passage_waiting_for_native_progress":"passage_waiting_for_body_clearance";
        passageDiagnostic(r,now,reason,null,null,0,0);
    }
    private void passageDiagnostic(Reservation r,double now,String reason,Id<Link> target,String queue,double used,double capacity){
        var p=r.passage;boolean timeSatisfied=now>=p.notBefore,bodyCleared=r.frontBound>=p.clearFront;
        if(reason.equals(p.lastDiagnostic)&&timeSatisfied==p.lastDiagnosticTimeSatisfied&&bodyCleared==p.lastDiagnosticBodyCleared)return;
        p.lastDiagnostic=reason;p.lastDiagnosticTimeSatisfied=timeSatisfied;p.lastDiagnosticBodyCleared=bodyCleared;
        var attrs=new LinkedHashMap<String,String>();attrs.put("policy",POLICY);attrs.put("vehicle",r.vehicle.toString());
        attrs.put("reservationOrdinal",Long.toString(r.ordinal));attrs.put("corridor",r.domain.id);attrs.put("link",r.link.toString());
        attrs.put("modelSlot",Integer.toString(r.slot));attrs.put("nativeQueue",r.nativeQueue);attrs.put("reason",reason);
        attrs.put("minimumReleaseTime",Double.toString(p.notBefore));attrs.put("minimumTimeSatisfied",Boolean.toString(now>=p.notBefore));
        attrs.put("clearanceFrontMeters",Double.toString(p.clearFront));attrs.put("modeledFrontLowerBoundMeters",Double.toString(r.frontBound));
        attrs.put("nativeFrontBoundMeters",Double.toString(r.nativeFront));attrs.put("bodyLengthMeters",Double.toString(r.length));
        attrs.put("minimumGapMeters",Double.toString(GAP));attrs.put("bodyClearanceSatisfied",Boolean.toString(r.frontBound>=p.clearFront));
        attrs.put("nativeEndpointSufficient",Boolean.toString(r.nativeFront>=p.clearFront));
        var prior=r.domain.reservations.get(r.slot).lowerEntry(r.ordinal);
        if(prior!=null){var leader=prior.getValue();attrs.put("leaderVehicle",leader.vehicle.toString());
            attrs.put("leaderFrontLowerBoundMeters",Double.toString(leader.frontBound));attrs.put("leaderFootprintMeters",Double.toString(leader.footprint));}
        if(target!=null){attrs.put("receivingLink",target.toString());attrs.put("receivingQueue",queue);
            attrs.put("receivingUsedPcu",Double.toString(used));attrs.put("receivingCapacityPcu",Double.toString(capacity));}
        attrs.put("source",target==null?"conservative_ledger_conditions":"native_queue_storage_rejection");
        attrs.put("positionsObserved","false");attrs.put("laneObserved","false");
        // Only changes of category or clearance conditions emit. No clock polling, queue scan,
        // microscopic position estimate, or event for each second of waiting.
        emit(now,"simz1OccupancyPassageState",attrs);
    }
    String corridorId(Id<Link> link){var d=domains.get(link);return d==null?null:d.id;}
    double offset(Id<Link> link){var d=domains.get(link);return d==null?0:d.offsets.get(link);}
    double setback(Id<Link> link){var d=domains.get(link);return d==null?2:d.setback;}
    boolean releasedOrPast(Id<Vehicle> vehicle,String corridor,double threshold){var r=active.get(vehicle);return r==null||!r.domain.id.equals(corridor)||r.frontBound>=threshold;}
    boolean crossingCleared(Id<Vehicle> vehicle,String corridor,double front,double notBefore,double now){
        return now>=notBefore&&releasedOrPast(vehicle,corridor,front);
    }
    QLaneI preferred(QVehicle vehicle,Id<Link> link,List<QLaneI> candidates) {
        var old=active.get(vehicle.getId());if(old==null)return candidates.get(0);
        int desired=old.passage!=null&&old.passage.slots.containsKey(link)?old.passage.slots.get(link):old.slot;
        var indices=laneIndices.getOrDefault(link,Map.of());
        for(var lane:candidates)if(Objects.equals(indices.get(lane.getId().toString()),desired))return lane;
        for(var lane:candidates)if(choose(vehicle,link,lane.getId().toString())>=0)return lane;
        return candidates.get(0); // caller's vehicle-aware admission will WAIT
    }
    private void transaction(double now,String action,Id<Vehicle> vehicle,Id<Link> link,Reservation r,int previous,String reason) {
        var d=r.domain;var values=new LinkedHashMap<String,String>();values.put("policy",POLICY);values.put("action",action);
        values.put("vehicle",vehicle.toString());values.put("link",link.toString());values.put("corridor",d.id);values.put("modelSlot",Integer.toString(r.slot));
        values.put("previousModelSlot",Integer.toString(previous));values.put("reservationOrdinal",Long.toString(r.ordinal));
        values.put("bodyLengthMeters",Double.toString(r.length));values.put("footprintMeters",Double.toString(r.footprint));
        values.put("minimumGapMeters",Double.toString(GAP));values.put("usedMeters",Double.toString(d.total()));values.put("capacityMeters",Double.toString(d.capacity*d.lanes));
        values.put("slotUsedMeters",Double.toString(r.slot<0?0:d.used[r.slot]));values.put("laneCapacityMeters",Double.toString(d.capacity));
        values.put("reason",reason);values.put("source","synchronous_QSim_corridor_ledger");values.put("laneObserved","false");
        if(r.passage!=null)addPassage(values,r.passage);
        emit(now,"simz1OccupancyReservation",values);
    }
    void registerNode(Zona1QNodeImpl node){nativeNodes.put(node.getNode().getId(),node);}
    double greenRemaining(Id<Link> from,Id<org.matsim.lanes.Lane> lane,Id<Link> to,double now){return signalWindows.remainingGreenSeconds(from,lane,to,now);}
    boolean lockedByOther(Id<Node> node,Id<Vehicle> vehicle){var owner=nodeLocks.get(node);return owner!=null&&!owner.equals(vehicle);}
    boolean preauthorized(Id<Vehicle> vehicle,Id<Link> from,Id<Link> to){var r=active.get(vehicle);if(r==null||r.passage==null||r.passage.released)return false;
        var p=r.passage;for(int i=0;i<p.links.size();i++)if(p.links.get(i).getId().equals(from)){var next=i+1<p.links.size()?p.links.get(i+1):p.receipt;return next!=null&&next.getId().equals(to);}return false;}
    Map<String,String> passagePriorityProof(Id<Vehicle> vehicle,Id<Link> from,Id<Link> to){
        if(!preauthorized(vehicle,from,to))throw new IllegalStateException("Priority credit without active passage");
        var r=active.get(vehicle);var p=r.passage;var attrs=new LinkedHashMap<String,String>();
        attrs.put("passageReservationOrdinal",Long.toString(r.ordinal));attrs.put("passageCorridor",r.domain.id);
        attrs.put("passageStopCreditSeconds",Double.toString(p.stopCredits.getOrDefault(from,0.)));
        addPassage(attrs,p);addStopCredit(attrs,p);return Map.copyOf(attrs);
    }
    /** Pure geometry/storage description shared by admission and competition.
     * No priority callbacks, hold timers, events, pending entries or acquisitions. */
    private Passage describePassage(QVehicle vehicle,Id<Link> target) {
        return describePassagePlan(vehicle,target).passage;
    }
    private PhysicalPlan describePassagePlan(QVehicle vehicle,Id<Link> target) {
        var path=plannedPath(vehicle);if(path==null)return blocked("passage_route_unavailable");
        var old=active.get(vehicle.getId());
        // No hold-and-wait across separate passage acquisitions. A receipt was
        // selected with enough longitudinal room to clear the previous locks.
        if(old!=null&&old.passage!=null&&!old.passage.released)return blocked("passage_previous_not_cleared");
        int at=path.indexOf(target);if(at<0||path.lastIndexOf(target)!=at)return blocked("passage_route_ambiguous");
        var connectors=new ArrayList<Link>();var connectorDomains=new HashSet<Domain>();var slots=new HashMap<Id<Link>,Integer>();Link receipt=null;Reach receiptReach=null;
        for(int i=at;i<path.size();i++) {
            var id=path.get(i);var d=domains.get(id);if(d==null)return blocked("passage_route_nonroad");
            var link=network.getLinks().get(id);double need=entryClearanceDistance(vehicle,id);
            if(i>at&&network.getLinks().get(path.get(i-1)).getToNode()!=link.getFromNode())return blocked("passage_route_disconnected");
            // A domain rejected at its conflict entrance must be traversed in
            // full. A later subdivision's smaller angle margin cannot turn its
            // own prefix into a receipt and bypass the original clearance.
            var reach=routeReach(path,i,d);
            if(!connectorDomains.contains(d)&&reach.front()-d.offsets.get(id)>=need){receipt=link;receiptReach=reach;break;}
            boolean terminal=i+1==path.size();int terminalSlot=terminal?terminalExitSlot(vehicle,id):-1;
            var owner=receiptLocks.get(d);if(owner!=null&&!owner.equals(vehicle.getId()))return blocked("passage_receipt_locked");
            owner=connectorLocks.get(id);if(owner!=null&&!owner.equals(vehicle.getId()))return blocked("passage_connector_locked");
            if(d.total()-(old!=null&&old.domain==d?old.footprint:0)>1e-8&&terminalSlot<0)return blocked("passage_connector_occupied");
            connectors.add(link);connectorDomains.add(d);
            if(vehicle.getDriver() instanceof org.matsim.core.mobsim.qsim.pt.TransitDriverAgent transit && transit.getNextTransitStop()!=null && id.equals(transit.getNextTransitStop().getLinkId())) {
                var stop=transit.getNextTransitStop();boolean exit=terminal&&!stop.getIsBlockingLane()&&"gateway".equals(Objects.toString(stop.getAttributes().getAttribute("simz1:stopRole"),""));
                Object dwell=stop.getAttributes().getAttribute("simz1:dwellSeconds");
                if(!exit||dwell==null||Double.parseDouble(dwell.toString())!=0)return blocked("passage_transit_stop_requires_storage");
            }
            var allowed=exits.get(id);int slot=terminalSlot>=0?terminalSlot:0;
            if(!terminal&&allowed!=null&&!allowed.isEmpty()) {final var next=path.get(i+1);slot=allowed.entrySet().stream().filter(e->e.getValue().contains(next)).mapToInt(Map.Entry::getKey).min().orElse(-1);if(slot<0)return blocked("passage_turn_without_lane");}
            slots.put(id,slot);
        }
        if(connectors.isEmpty())return blocked("passage_connector_missing");
        if(receipt==null&&old==null)return blocked("passage_no_receipt_or_origin_storage"); // no fictitious off-network origin storage
        // Check only this acquired passage, not a remote route after its receipt.
        // The same complete-period proof handles distinct controllers as well
        // as a return through one node; execution still checks current signals.
        var temporal=temporalRoute(path.subList(Math.max(0,at-1),Math.min(path.size(),at+connectors.size()+1)),0,
            length(vehicle),vehicle.getVehicle().getType().getMaximumVelocity(),old==null?null:Id.create(old.nativeQueue,Lane.class),true);
        if(temporal.status()==Feasibility.IMPOSSIBLE)return blocked("passage_incompatible_signal_phases");
        double base=receipt==null?old.domain.offsets.get(old.link)+network.getLinks().get(old.link).getLength():domains.get(receipt.getId()).offsets.get(receipt.getId());
        var p=new Passage(connectors,slots,receipt,base,receipt==null?old.link:null);
        if(receiptReach!=null){p.reachableFront=receiptReach.front();p.receiptPath=receiptReach.links();
            p.receiptStoppingSetback=receiptReach.stoppingSetback();p.receiptFollowingLink=receiptReach.followingLink();}
        p.clearFront=receipt==null?base+connectors.stream().mapToDouble(Link::getLength).sum():base+entryClearanceDistance(vehicle,receipt.getId());
        for(var node:p.nodes)if(lockedByOther(node,vehicle.getId()))return blocked("passage_node_locked");
        return new PhysicalPlan(p,-1,null);
    }
    private String preparePassage(QVehicle vehicle,Id<Link> target,Passage p,double now,String activityBufferQueue) {
        String physicalIssue=passagePhysicalIssue(vehicle,p,now,activityBufferQueue,null);
        if(physicalIssue!=null)return physicalIssue;
        var old=active.get(vehicle.getId());var connectors=p.links;var slots=p.slots;var receipt=p.receipt;
        var origin=old==null?null:nativeNodes.get(network.getLinks().get(old.link).getToNode().getId());
        var head=origin==null?null:origin.passageHead(vehicle,network.getLinks().get(old.link),old.nativeQueue,now);
        var request=new PassageRequest(List.copyOf(plannedPath(vehicle)),old==null?"":old.nativeQueue,
            head==null?Double.NaN:head.getLastMovementTimeOfFirstVehicle());
        if(!request.equals(passageRequests.put(vehicle.getId(),request)))passageRequestTime.remove(vehicle.getId());
        double wait=0;
        boolean cycleWinner=false;
        for(int i=0;i<connectors.size();i++) {
            var from=connectors.get(i);var to=i+1<connectors.size()?connectors.get(i+1):receipt;
            if(to==null)continue; // final activity/gateway leaves native traffic
            var node=nativeNodes.get(from.getToNode().getId());if(node==null)return "passage_native_node_missing";
            if(!node.passageClear(vehicle,from,to,slots.get(from.getId()),now)) {
                if(!node.lastPassageCheck().reason().equals("priority_yield_conflict"))return "passage_control_or_crossing_wait";
                if(!cycleWinner)cycleWinner=closedPriorityCycleWinner(vehicle,p,now);
                if(!cycleWinner)return "passage_control_or_crossing_wait";
            }
            double seconds=node.passageStopSeconds(from);wait+=seconds;p.stopCredits.put(from.getId(),seconds);
        }
        Double first=passageRequestTime.get(vehicle.getId());
        if(first==null){first=now;passageRequestTime.put(vehicle.getId(),first);
            p.holdStart=first;p.requiredStop=wait;var attrs=new LinkedHashMap<String,String>();
            attrs.put("vehicle",vehicle.getId().toString());attrs.put("link",old==null?target.toString():old.link.toString());attrs.put("requestedLink",target.toString());
            attrs.put("source","native_admission_hold");attrs.put("positionsObserved","false");addStopCredit(attrs,p);attrs.remove("passageAuthorizedTime");emit(now,"simz1OccupancyPassageHold",attrs);
        }
        if(now<first+wait)return "passage_stop_hold";
        p.holdStart=first;p.authorizedTime=now;p.requiredStop=wait;
        double speed=Math.min(vehicle.getVehicle().getType().getMaximumVelocity(),connectors.stream().mapToDouble(l->l.getFreespeed(now)).min().orElse(1));
        p.notBefore=now+(connectors.stream().mapToDouble(Link::getLength).sum()+(receipt==null?length(vehicle)+GAP:entryClearanceDistance(vehicle,receipt.getId())))/speed;
        return null;
    }
    private record CycleRequest(QVehicle vehicle,double headSince,List<QVehicle> blockers) { }
    /** Resolve only a closed priority cycle inside this exact passage's node
     * footprint. Build from current offered heads, not from query order or a
     * city-wide pending map. No reservation is acquired here. Ordinary turns,
     * outside blockers, fairness grants and physical constraints stay binding.
     * Recompute on every admission; the existing acquire/clearance locks commit
     * the winner across all its nodes in the serial whole-body ledger. */
    private boolean closedPriorityCycleWinner(QVehicle requester,Passage passage,double now){
        var graph=new LinkedHashMap<Id<Vehicle>,CycleRequest>();var todo=new ArrayDeque<QVehicle>();todo.add(requester);
        while(!todo.isEmpty()){
            var vehicle=todo.remove();if(graph.containsKey(vehicle.getId()))continue;
            var old=active.get(vehicle.getId());if(old==null)return false;
            var path=plannedPath(vehicle);if(path==null||path.size()<2||!path.get(0).equals(old.link)||
                    !path.get(1).equals(vehicle.getDriver().chooseNextLinkId()))return false;
            var from=network.getLinks().get(old.link);var node=nativeNodes.get(from.getToNode().getId());if(node==null)return false;
            var head=node.passageHead(vehicle,from,old.nativeQueue,now);if(head==null)return false;
            var target=path.get(1);var plan=physicalPlan(vehicle,target,"",null,true);
            if(!plan.feasible()||plan.passage==null||!plan.passage.nodes.equals(passage.nodes)||
                    passagePhysicalIssue(vehicle,plan.passage,now,null,null)!=null)return false;
            var blockers=new ArrayList<QVehicle>();
            // The real entrance remains subject to its local priority and stop.
            // Cycles repaired here are future-passage vetoes after local GO.
            if(!node.passageClear(vehicle,from,network.getLinks().get(target),old.slot,now))return false;
            var p=plan.passage;
            for(int i=0;i<p.links.size();i++){
                var a=p.links.get(i);var b=i+1<p.links.size()?p.links.get(i+1):p.receipt;if(b==null)continue;
                var at=nativeNodes.get(a.getToNode().getId());if(at==null)return false;
                if(!at.passageClear(vehicle,a,b,p.slots.get(a.getId()),now)){
                    var check=at.lastPassageCheck();if(!check.reason().equals("priority_yield_conflict"))return false;
                    blockers.addAll(check.blockers());
                }
            }
            if(blockers.isEmpty())return false; // dependency is executable, not cyclic
            graph.put(vehicle.getId(),new CycleRequest(vehicle,head.getLastMovementTimeOfFirstVehicle(),List.copyOf(blockers)));
            todo.addAll(blockers);
        }
        if(graph.size()<2)return false;
        // Every discovered dependency must belong to the same strongly connected
        // component. A chain leading out of a cycle does not waive that priority.
        for(var start:graph.keySet()){
            var seen=new HashSet<Id<Vehicle>>();var scan=new ArrayDeque<Id<Vehicle>>();scan.add(start);
            while(!scan.isEmpty()){var id=scan.remove();if(seen.add(id))for(var blocker:graph.get(id).blockers)scan.add(blocker.getId());}
            if(seen.size()!=graph.size())return false;
        }
        // Oldest native head first; stable ID only breaks equal-age ties. A new
        // head cannot steal age from its predecessor after the winner clears.
        var winner=graph.values().stream().min(Comparator.comparingDouble(CycleRequest::headSince)
            .thenComparing(r->r.vehicle.getId().toString())).orElseThrow();
        return winner.vehicle==requester;
    }
    /** Read native physical constraints only. No passageClear/priority callback:
     * admission may call priority, whose competitor probes end here. */
    private String passagePhysicalIssue(QVehicle vehicle,Passage p,double now,String activityBufferQueue,QNetwork qnet) {
        double traversal=0;
        for(int i=0;i<p.links.size();i++) {
            var from=p.links.get(i);var to=i+1<p.links.size()?p.links.get(i+1):p.receipt;
            if(to==null)continue;
            int slot=p.slots.get(from.getId());
            var node=nativeNodes.get(from.getToNode().getId());
            if(qnet!=null) {
                var qfrom=qnet.getNetsimLinks().get(from.getId());var qto=qnet.getNetsimLinks().get(to.getId());
                if(qfrom==null||qto==null)return "passage_native_link_missing";
                if(!qto.getAcceptingQLane().isAcceptingFromUpstream())return "passage_native_storage";
                var offered=qfrom.getOfferingQLanes();
                var selected=offered.stream().filter(l->offered.size()==1||l.getId().toString().endsWith(".lane."+slot)).findFirst().orElse(null);
                if(selected==null)return "passage_native_lane_missing";
                if(selected instanceof org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem signal&&!signal.hasGreenForToLink(to.getId()))return "passage_signal_not_green";
            }
            if(node!=null) {
                traversal+=node.passageTraversalUpperBound(vehicle,from,slot,now,i==0?activityBufferQueue:null);
                if(!Double.isFinite(traversal))return "passage_traversal_unavailable";
                double remaining=node.passageGreenRemaining(from,to,slot,now);
                if(!(remaining>0))return "passage_signal_not_green";
                if(remaining<=traversal)return "passage_signal_window_too_short";
                if(Double.isFinite(remaining)) {
                    p.greenWindows.put(from.getId(),remaining);p.traversalBudgets.put(from.getId(),traversal);
                }
            }else return "passage_native_node_missing";
        }
        return null;
    }
    private boolean receiptQueuesClear(Passage passage,int slot,QNetwork qnet){
        var d=domains.get(passage.receipt.getId());boolean reached=false;
        for(var link:d.links){if(link==passage.receipt)reached=true;if(!reached)continue;
            double originalEnd=queueEnds.getOrDefault(link.getId(),Map.of()).getOrDefault(link.getId()+".original",link.getLength());
            boolean needsTerminal=passage.clearFront>d.offsets.get(link.getId())+originalEnd+1e-8;
            if(qnet!=null) {
                var qlink=qnet.getNetsimLinks().get(link.getId());
                if(qlink==null||!qlink.getAcceptingQLane().isAcceptingFromUpstream())return false;
                if(needsTerminal) {
                    var offered=qlink.getOfferingQLanes();
                    if(offered.stream().filter(l->offered.size()==1||l.getId().toString().endsWith(".lane."+slot))
                            .noneMatch(QLaneI::isAcceptingFromUpstream))return false;
                }
            }else {
                var node=nativeNodes.get(link.getFromNode().getId());
                if(node==null||!node.receiptQueueReady(link,slot,needsTerminal))return false;
            }
            if(d.offsets.get(link.getId())+link.getLength()>=passage.clearFront-1e-8)return true;
        }
        return false;
    }
    private void addPassage(Map<String,String> attrs,Passage p){attrs.put(p.receipt==null?"exitLinks":"passageLinks",String.join(",",p.links.stream().map(l->l.getId().toString()).toList()));
        attrs.put(p.receipt==null?"exitSlots":"passageSlots",String.join(",",p.links.stream().map(l->p.slots.get(l.getId()).toString()).toList()));
        attrs.put("passageKind",p.receipt==null?"boundary_exit":"downstream_receipt");
        if(p.receipt==null)attrs.put("exitFromLink",p.exitFrom.toString());else attrs.put("receiptLink",p.receipt.getId().toString());}
    private void passageEvent(double now,String action,Id<Vehicle> vehicle,Reservation r){var attrs=new LinkedHashMap<String,String>();
        attrs.put("policy",POLICY);attrs.put("action",action);attrs.put("vehicle",vehicle.toString());attrs.put("corridor",r.domain.id);
        attrs.put("reservationOrdinal",Long.toString(r.ordinal));attrs.put("lockedNodes",String.join(",",r.passage.nodes.stream().map(Object::toString).toList()));
        attrs.put("minimumReleaseTime",Double.toString(r.passage.notBefore));attrs.put("clearanceFrontMeters",Double.toString(r.passage.clearFront));
        if(r.passage.receipt!=null){attrs.put("receiptFreeFrontMeters",Double.toString(r.passage.freeFront));attrs.put("admissionBasis","modeled_free_entry_interval");
            attrs.put("receiptReachableFrontMeters",Double.toString(r.passage.reachableFront));attrs.put("receiptPathLinks",String.join(",",r.passage.receiptPath.stream().map(Object::toString).toList()));
            attrs.put("receiptFollowingLink",Objects.toString(r.passage.receiptFollowingLink,""));
            attrs.put("receiptStoppingSetbackMeters",Double.toString(r.passage.receiptStoppingSetback));}
        attrs.put("receiptRouteCoveragePolicy",ROUTE_COVERAGE);
        attrs.put("passageSignalWindowPolicy","fixed_plan_empty_native_queue_bound_v1");
        attrs.put("passageSignalLinks",String.join(",",r.passage.greenWindows.keySet().stream().map(Object::toString).toList()));
        attrs.put("passageSignalGreenSeconds",String.join(",",r.passage.greenWindows.values().stream().map(Object::toString).toList()));
        attrs.put("passageSignalTraversalSeconds",String.join(",",r.passage.traversalBudgets.values().stream().map(Object::toString).toList()));
        attrs.put("reason",action.equals("ACQUIRE")?r.passage.receipt==null?"authorized_native_traffic_exit":"authorized_downstream_receipt":active.containsKey(vehicle)?"body_clearance":"reservation_exit");
        attrs.put("source","synchronous_QSim_corridor_ledger");attrs.put("positionsObserved","false");attrs.put("laneObserved","false");addPassage(attrs,r.passage);addStopCredit(attrs,r.passage);emit(now,"simz1OccupancyPassage",attrs);}
    private void addStopCredit(Map<String,String> attrs,Passage p){
        attrs.put("passageHoldStartTime",Double.toString(p.holdStart));attrs.put("passageAuthorizedTime",Double.toString(p.authorizedTime));
        attrs.put("passageRequiredStopSeconds",Double.toString(p.requiredStop));attrs.put("passageStopLinks",String.join(",",p.stopCredits.keySet().stream().map(Object::toString).toList()));
        attrs.put("passageStopSeconds",String.join(",",p.stopCredits.values().stream().map(Object::toString).toList()));
    }
    private void releasePassage(Id<Vehicle> vehicle,Reservation r,double now){if(r.passage==null)return;
        if(r.passage.nodes.stream().anyMatch(n->vehicle.equals(nodeLocks.get(n)))){
            if(active.containsKey(vehicle)&&r.passage.receipt!=null&&now>=r.passage.notBefore&&r.frontBound>=r.passage.clearFront)
                passageDiagnostic(r,now,"passage_released_after_clearance",null,null,0,0);
            passageEvent(now,"RELEASE",vehicle,r);
            for(var n:r.passage.nodes)nodeLocks.remove(n,vehicle);for(var l:r.passage.links)connectorLocks.remove(l.getId(),vehicle);receiptLocks.remove(r.domain,vehicle);
            if(r.passage.receipt==null)receiptLocks.remove(domains.get(r.passage.links.get(r.passage.links.size()-1).getId()),vehicle);}
        r.passage.released=true;
        // Keep immutable path metadata with the reservation for replay body tails.
    }
    private void emit(double now,String kind,Map<String,String> values) {
        var frozen=Map.copyOf(values);events.processEvent(new Event(now){@Override public String getEventType(){return kind;}
            @Override public Map<String,String> getAttributes(){var attrs=super.getAttributes();attrs.putAll(frozen);return attrs;}});
    }
}
