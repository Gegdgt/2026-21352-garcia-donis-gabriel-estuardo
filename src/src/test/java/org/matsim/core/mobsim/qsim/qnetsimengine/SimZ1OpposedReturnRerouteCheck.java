package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.mobsim.qsim.agents.HasModifiablePlan;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;

/** Isolated route/ledger checks. Never starts QSim or a controller. Synthetic
 * opposite corridors retain the observed 79.339655m link and 22.937083m interior
 * offset; this is not a replay of the unknown full 220K reservation snapshot. */
public final class SimZ1OpposedReturnRerouteCheck {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Id<Link> id(String value){return Id.createLinkId(value);}
    static Id<Lane> lane(String value){return Id.create(value,Lane.class);}
    static List<Id<Link>> path(String... values){return Arrays.stream(values).map(SimZ1OpposedReturnRerouteCheck::id).toList();}
    @SuppressWarnings("unchecked") static <T>T proxy(Class<T> type,InvocationHandler handler){
        return (T)Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},handler);
    }
    static void link(Network n,String name,String from,String to,double length,int lanes){
        var l=n.getFactory().createLink(id(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setNumberOfLanes(lanes);l.setCapacity(2000*lanes);l.setFreespeed(10);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
    }
    static final class Actor {
        final Leg leg;final QVehicle vehicle;int index;
        Actor(Scenario scenario,String name,double body,List<Id<Link>> route) {
            leg=scenario.getPopulation().getFactory().createLeg("car");setRoute(scenario,route);
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
            type.setLength(body).setWidth(body<3?.8:body>10?2.5:1.8).setMaximumVelocity(10).setPcuEquivalents(body<3?.25:body>10?3:1);
            var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);
            var driver=Proxy.newProxyInstance(HasModifiablePlan.class.getClassLoader(),
                new Class<?>[]{HasModifiablePlan.class,PlanAgent.class,MobsimDriverAgent.class},(p,m,a)->switch(m.getName()) {
                    case "getCurrentPlanElement"->leg;case "getCurrentLinkIndex"->index;
                    case "getCurrentLinkId"->full().get(index);
                    case "chooseNextLinkId"->index+1<full().size()?full().get(index+1):null;
                    case "isWantingToArriveOnCurrentLink"->index+1==full().size();
                    case "getId"->Id.createPersonId(name);
                    default->throw new AssertionError("Unexpected route mutation/query: "+m);
                });
            vehicle=proxy(QVehicle.class,(p,m,a)->switch(m.getName()) {
                case "getId"->v.getId();case "getVehicle"->v;case "getDriver"->driver;
                case "getMaximumVelocity"->type.getMaximumVelocity();
                default->throw new AssertionError("Unexpected vehicle mutation/query: "+m);
            });
        }
        List<Id<Link>> full(){return SimZ1RouteSafety.full((NetworkRoute)leg.getRoute());}
        void setRoute(Scenario s,List<Id<Link>> route){leg.setRoute(RouteUtils.createNetworkRoute(route,s.getNetwork()));}
    }
    private static final class Offered {
        QVehicle head;final QLaneI lane;
        Offered(String name){lane=proxy(QLaneI.class,(p,m,a)->switch(m.getName()) {
            case "getId"->lane(name);case "isNotOfferingVehicle"->head==null;case "getFirstVehicle"->head;
            case "isAcceptingFromUpstream"->true;
            default->throw new AssertionError("Query attempted native queue mutation: "+m);
        });}
    }
    private static final class Fixture implements AutoCloseable {
        final Scenario s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final List<Event> events=new ArrayList<>();final Map<String,Offered> offered=new HashMap<>();
        final Map<Id<Vehicle>,Actor> actors=new HashMap<>();
        final List<Actor> followers=new ArrayList<>();
        final SimZ1CorridorOccupancy ledger;final SimZ1RouteSafety safety;final QNetwork qnet;
        final Actor forward,backward;
        final List<Id<Link>> candidate=path("back-tail","backward","forward","forward-tail","exit-c","destination");
        Fixture(double body,int lanes,boolean restricted,double firstLength,boolean forwardTurns) {
            var n=s.getNetwork();double tail=22.93708267195983;
            var xy=Map.of("a",new Coord(0,0),"b",new Coord(firstLength,0),"c",new Coord(firstLength+tail,0),
                "d",new Coord(-100,0),"e",new Coord(-200,0),"side",new Coord(-50,0),"detour",new Coord(-150,0));
            for(var entry:xy.entrySet())n.addNode(n.getFactory().createNode(Id.createNodeId(entry.getKey()),entry.getValue()));
            link(n,"forward","a","b",firstLength,lanes);link(n,"forward-tail","b","c",tail,lanes);
            link(n,"back-tail","c","b",tail,lanes);link(n,"backward","b","a",firstLength,lanes);
            link(n,"exit-a","a","d",100,1);link(n,"exit-c","c","d",200,1);link(n,"destination","d","e",100,1);
            link(n,"detour-out","a","detour",150,1);link(n,"detour-in","detour","d",50,1);
            link(n,"street","side","a",50,1);
            for(String name:List.of("a","c"))n.getNodes().get(Id.createNodeId(name)).getAttributes().putAttribute("highway","stop");
            for(var l:n.getLinks().values())l.getAttributes().putAttribute("simz1:priorityRole",l.getId().equals(id("street"))?"street":"avenue");
            LanesGenerator.build(s);
            if(restricted)s.getLanes().getLanesToLinkAssignments().get(id("backward")).getLanes()
                .get(lane("backward.lane.0")).getToLinkIds().remove(id("forward"));
            safety=new SimZ1RouteSafety(s);
            var manager=EventsUtils.createEventsManager();manager.addHandler((BasicEventHandler)events::add);
            ledger=new SimZ1CorridorOccupancy(s,Set.of(),manager);SimZ1CorridorOccupancy.install(s.getConfig().qsim(),ledger);
            forward=new Actor(s,"opposed-forward",body,forwardTurns?path("forward","backward","exit-a","destination"):
                path("forward","forward-tail","exit-c","destination"));
            backward=new Actor(s,"candidate-backward",body,path("back-tail","backward","exit-a","destination"));
            actors.put(forward.vehicle.getId(),forward);actors.put(backward.vehicle.getId(),backward);
            hold(forward,"forward",0);
            check(ledger.activity(backward.vehicle,id("back-tail"),"back-tail.original",0),"Backward origin cannot store body");
            backward.index=1;hold(backward,"backward",1);
            var links=new HashMap<Id<Link>,QLinkI>();
            for(var l:n.getLinks().values()) {
                var lanesHere=new ArrayList<QLaneI>();
                for(int slot=0;slot<(int)l.getNumberOfLanes();slot++) {
                    var q=new Offered(l.getId()+".lane."+slot);offered.put(l.getId()+"."+slot,q);lanesHere.add(q.lane);
                }
                var entry=new Offered(l.getId()+".original");
                links.put(l.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()) {
                    case "getLink"->l;case "getOfferingQLanes"->lanesHere;case "getAcceptingQLane"->entry.lane;
                    case "getVehicle"->{var actor=actors.get(a[0]);yield actor!=null&&actor.full().get(actor.index).equals(l.getId())?actor.vehicle:null;}
                    default->throw new AssertionError("Unexpected native link mutation/query: "+m);
                }));
            }
            qnet=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
            offered.get("forward.0").head=forward.vehicle;offered.get("backward.0").head=backward.vehicle;
        }
        void hold(Actor actor,String link,double now) {
            if(link.equals("forward"))check(ledger.activity(actor.vehicle,id(link),link+".original",now),"Forward origin cannot store body");
            check(ledger.canEnter(actor.vehicle,id(link),link+".lane.0",now),"Cannot reach committed terminal");
            ledger.enter(actor.vehicle,id(link),link+".lane.0",now,"queue_entry");ledger.progress(actor.vehicle,id(link),link+".lane.0",now);
        }
        void fillForward(double body){fillForward(body,false);}
        void fillForward(double body,boolean finalActivities) {
            for(int i=0;i<100;i++) {
                var follower=new Actor(s,"fifo-"+i,body,finalActivities?path("street","forward"):path("forward","forward-tail","exit-c","destination"));
                if(finalActivities)follower.index=1; // actual final-link occurrence, without manufacturing an arrival
                if(!ledger.canEnter(follower.vehicle,id("forward"),"forward.lane.0",10+i)) {
                    check(!followers.isEmpty(),"Fixture did not create a FIFO queue");return;
                }
                ledger.enter(follower.vehicle,id("forward"),"forward.lane.0",10+i,"queue_entry");
                ledger.progress(follower.vehicle,id("forward"),"forward.lane.0",10+i);followers.add(follower);actors.put(follower.vehicle.getId(),follower);
            }
            throw new AssertionError("Fixture receiver never became full");
        }
        String issue(Actor actor,List<Id<Link>> candidate){return SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),actor.vehicle.getId(),candidate,actor.index,qnet);}
        void expect(Actor actor,List<Id<Link>> candidate,String expected) throws Exception {
            String state=snapshot(ledger);int before=events.size();var route=actor.leg.getRoute();int cursor=actor.index;
            for(int repeat=0;repeat<3;repeat++)check(Objects.equals(expected,issue(actor,candidate)),"Expected "+expected+", got "+issue(actor,candidate));
            check(state.equals(snapshot(ledger))&&events.size()==before,"Reroute probe changed reservations/locks/ordinals/events");
            check(route==actor.leg.getRoute()&&cursor==actor.index,"Rejected probe installed a route or moved its cursor");
        }
        @Override public void close(){SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());}
    }
    private static void cycleAndAlternative(double body) throws Exception {
        try(var f=new Fixture(body,1,false,79.33965536064153,true)) {
            f.fillForward(body);
            check(f.safety.validateReplacement(f.backward.full(),f.candidate,1,id("backward"),id("destination"),lane("backward.lane.0"))==null,"Candidate is not a legal network turn");
            check(SimZ1CorridorOccupancy.replacementIssue(f.s.getConfig().qsim(),f.backward.vehicle.getId(),f.candidate,1)==null,
                "Fixture must expose the gap in the geometry/reservation-only guard");
            check(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(f.s.getConfig().qsim(),f.forward.vehicle,id("backward"),"backward.original"),"Interior FIFO entry unexpectedly free");
            f.expect(f.backward,f.candidate,"occupancy_opposed_return_cycle");
            check(f.offered.get("forward.0").head==f.forward.vehicle&&f.offered.get("backward.0").head==f.backward.vehicle,"Query advanced a queue head");
            // Both retaining the old route and changing to a safe detour preserve
            // the actual destination; neither requires the opposite receiver.
            f.expect(f.backward,f.backward.full(),null);
            var alternative=path("back-tail","backward","detour-out","detour-in","destination");
            check(!alternative.equals(f.backward.full()),"Alternative must change the remaining route");
            f.expect(f.backward,alternative,null);
            check(f.safety.validateReplacement(f.backward.full(),alternative,1,id("backward"),id("destination"),lane("backward.lane.0"))==null,"Safe alternative changed prefix/destination");
            check(f.safety.validateReplacement(f.backward.full(),path("back-tail","backward","exit-a"),1,id("backward"),id("destination"),lane("backward.lane.0")).equals("destination_changed"),"Artificial destination accepted");
            assertPriorityAndFifo(f,body);
            // Construct the pre-existing bad state explicitly to check symmetry;
            // production must reject the detached candidate before this assignment.
            f.backward.setRoute(f.s,f.candidate);
            f.expect(f.forward,f.forward.full(),"occupancy_opposed_return_cycle");
            check(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(f.s.getConfig().qsim(),f.backward.vehicle,id("forward"),"forward.original"),"Cycle's second receiving dependency is missing");
        }
    }
    private static void twoBodiesOnly(double body) throws Exception {
        // Each directional receipt can hold one complete body plus 0.10m,
        // but cannot receive the opposite body until its own head leaves.
        try(var f=new Fixture(body,1,false,body+.10+2,true)) {
            check(f.followers.isEmpty(),"Two-body fixture must have no queued followers");
            assertTwoBodyState(f,body);
            f.expect(f.backward,f.candidate,"occupancy_opposed_return_cycle");
            f.backward.setRoute(f.s,f.candidate); // explicit old bad-state fixture, never production installation
            f.expect(f.forward,f.forward.full(),"occupancy_opposed_return_cycle");
        }
    }
    private static Object field(Object owner,String name) throws ReflectiveOperationException {
        var field=owner.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(owner);
    }
    /** Read-only fixture audit, in detector order. Report the first missing
     * prerequisite with the actual receipt bounds; never release a body or
     * install the detached candidate to manufacture the dependency. */
    private static void assertTwoBodyState(Fixture f,double body) throws ReflectiveOperationException {
        String before=snapshot(f.ledger);int eventCount=f.events.size();
        var active=(Map<?,?>)field(f.ledger,"active");
        check(active.size()==2,"Two-body fixture must have exactly two active reservations");
        var candidate=active.get(f.backward.vehicle.getId());var peer=active.get(f.forward.vehicle.getId());
        check(candidate!=null&&peer!=null,"Missing candidate/opposite reservation");
        check(field(candidate,"domain")!=field(peer,"domain"),"Opposite reservations share a domain");
        for(var actor:List.of(f.backward,f.forward)) {
            var r=active.get(actor.vehicle.getId());var current=actor.full().get(actor.index);String queue=current+".lane.0";
            check(current.equals(field(r,"link"))&&actor.vehicle.getId().equals(field(r,"vehicle")),"Reservation/current-link mismatch: "+current);
            check(queue.equals(field(r,"nativeQueue"))&&Integer.valueOf(0).equals(field(r,"slot")),"Native queue/slot mismatch: "+current);
            check(field(r,"passage")==null,"Unexpected passage in ordinary two-body fixture: "+current);
            var head=f.offered.get(current+".0").lane;
            check(!head.isNotOfferingVehicle()&&head.getFirstVehicle()==actor.vehicle,"Missing real offered head: "+current);
            check(f.ledger.terminalMatchesSlot(current,queue,0),"Offered terminal does not match reservation: "+current);
            check(Math.abs((double)field(r,"footprint")-body-.10)<1e-8,"Body/gap mismatch: "+current);
        }
        check(id("exit-a").equals(f.backward.vehicle.getDriver().chooseNextLinkId()),"Candidate route was installed before validation");
        check(id("backward").equals(f.forward.vehicle.getDriver().chooseNextLinkId()),"Opposite head is not returning");
        check(f.safety.validateReplacement(f.backward.full(),f.candidate,1,id("backward"),id("destination"),lane("backward.lane.0"))==null,
            "Candidate is not a connected, lane-compatible return preserving the destination");
        var domains=(Map<?,?>)field(f.ledger,"domains");
        var reachMethod=SimZ1CorridorOccupancy.class.getDeclaredMethod("routeReach",List.class,int.class,SimZ1CorridorOccupancy.Domain.class);
        reachMethod.setAccessible(true);
        var dependsMethod=SimZ1CorridorOccupancy.class.getDeclaredMethod("receiptDependsOnHead",candidate.getClass(),List.class,int.class,peer.getClass(),QLinkI.class);
        dependsMethod.setAccessible(true);
        for(var incoming:List.of(f.backward,f.forward)) {
            var route=incoming==f.backward?f.candidate:f.forward.full();int at=incoming.index+1;
            var holder=incoming==f.backward?peer:candidate;var target=route.get(at);
            var d=(SimZ1CorridorOccupancy.Domain)field(holder,"domain");
            check(domains.get(target)==d&&target.equals(field(holder,"link"))&&d.lanes==1,"Wrong receiving domain/slot: "+target);
            for(int i=at;i+1<route.size()&&domains.get(route.get(i))==d;i++)
                check(f.s.getLanes().getLanesToLinkAssignments().get(route.get(i)).getLanes().get(lane(route.get(i)+".lane.0")).getToLinkIds().contains(route.get(i+1)),
                    "Receiver slot cannot follow route: "+route.get(i));
            double front=(double)field(reachMethod.invoke(f.ledger,route,at,d),"front"),offset=d.offsets.get(target);
            double need=f.ledger.entryClearanceDistance(incoming.vehicle,target);
            double maximumFront=Math.min(d.capacity,offset+f.s.getNetwork().getLinks().get(target).getLength());
            double maximumFree=maximumFront-(double)field(holder,"footprint")-offset;
            String bounds="target="+target+", routeReach="+(front-offset)+", need="+need+", maximumFreeWithHead="+maximumFree;
            check(front>=offset+need-1e-8,"Receipt is actually too short: "+bounds);
            check(maximumFree<need-1e-8,"Opposite head can remain with enough reception: "+bounds);
            boolean depends=(boolean)dependsMethod.invoke(f.ledger,active.get(incoming.vehicle.getId()),route,at,holder,f.qnet.getNetsimLinks().get(target));
            check(depends,"receiptDependsOnHead lost the proved two-body dependency: "+bounds);
        }
        check(before.equals(snapshot(f.ledger))&&eventCount==f.events.size(),"Fixture audit mutated the ledger or emitted events");
    }
    private static void assertPriorityAndFifo(Fixture f,double body) throws Exception {
        var minor=new Actor(f.s,"yielding-street",body,path("street","exit-a","destination"));
        check(f.ledger.activity(minor.vehicle,id("street"),"street.original",100),"Minor origin setup");
        f.offered.get("street.0").head=minor.vehicle;
        var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");settings.setConflicts("conservative");settings.setMaxYieldSeconds(0);
        var priority=new UnsignalizedPriority.StopAndYield(f.s.getNetwork().getNodes().get(Id.createNodeId("a")),settings,null,null,f.s.getConfig().qsim());
        var street=f.s.getNetwork().getLinks().get(id("street"));var qlane=f.offered.get("street.0").lane;
        priority.isAcceptingTurn(street,qlane,id("exit-a"),minor.vehicle,f.qnet,100);
        var decision=priority.isAcceptingTurn(street,qlane,id("exit-a"),minor.vehicle,f.qnet,105);
        check(decision==TurnAcceptanceLogic.AcceptTurn.WAIT&&"priority_yield_conflict".equals(priority.getLastWaitReason()),"Rejection changed the executable avenue's priority");
        f.expect(f.backward,f.candidate,"occupancy_opposed_return_cycle");
        check(priority.isAcceptingTurn(street,qlane,id("exit-a"),minor.vehicle,f.qnet,106)==TurnAcceptanceLogic.AcceptTurn.WAIT,"Reroute query altered priority state");
        for(var e:f.events)if(e.getEventType().equals("simz1OccupancyReservation")&&e.getAttributes().containsKey("footprintMeters")) {
            var a=e.getAttributes();check(Math.abs(Double.parseDouble(a.get("footprintMeters"))-Double.parseDouble(a.get("bodyLengthMeters"))-.10)<1e-8,"Changed 0.10m body gap");
        }
    }
    private static void feasibleAndUnproven(double body) throws Exception {
        try(var f=new Fixture(body,1,false,79.33965536064153,true)) {
            f.expect(f.backward,f.candidate,null); // opposite head present, but enough entry space
            f.fillForward(body);f.offered.get("forward.0").head=null;
            f.expect(f.backward,f.candidate,null); // occupancy alone is not proof of reciprocal waiting
        }
        try(var f=new Fixture(body,2,false,79.33965536064153,true)) {
            f.fillForward(body);f.expect(f.backward,f.candidate,null); // a legal parallel receiver breaks the proof
        }
        try(var f=new Fixture(body,1,false,79.33965536064153,false)) {
            f.fillForward(body);f.expect(f.backward,f.candidate,null); // opposite head will go straight and can drain
        }
        try(var f=new Fixture(body,1,false,79.33965536064153,true)) {
            f.fillForward(body,true);f.expect(f.backward,f.candidate,null); // legitimate final activities can free reception
        }
    }
    private static void existingReservationGuards() throws Exception {
        try(var f=new Fixture(4.5,2,true,79.33965536064153,true)) {
            // Original queue can reach slot1, but the admitted body already owns
            // slot0. A reroute must not invent a lateral move between them.
            check(f.safety.validateReplacement(f.backward.full(),f.candidate,1,id("backward"),id("destination"),lane("backward.original"))==null,"Original-lane test cannot reach the return");
            f.expect(f.backward,f.candidate,"occupancy_reserved_terminal_slot");
            check(f.safety.validateReplacement(f.backward.full(),f.candidate,1,id("backward"),id("destination"),lane("backward.lane.0")).startsWith("current_lane_cannot_reach_next"),"Native terminal restriction ignored");
        }
        try(var f=new Fixture(4.5,1,false,6,false)) {
            f.expect(f.forward,path("forward","backward","exit-a","destination"),"occupancy_reserved_receipt_clearance");
            f.expect(f.forward,f.forward.full(),null);
        }
    }
    static String snapshot(SimZ1CorridorOccupancy ledger) throws ReflectiveOperationException {
        var text=new StringBuilder();var seen=new IdentityHashMap<Object,Integer>();
        for(String name:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks",
                "passageRequestTime","passageDeadlines","waits","waitReasons","nextOrdinal")) {
            var field=SimZ1CorridorOccupancy.class.getDeclaredField(name);field.setAccessible(true);text.append(name).append(freeze(field.get(ledger),seen));
        }
        return text.toString();
    }
    static String physicalSnapshot(SimZ1CorridorOccupancy ledger) throws ReflectiveOperationException {
        var text=new StringBuilder();var seen=new IdentityHashMap<Object,Integer>();
        for(String name:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks","nextOrdinal")) {
            var field=SimZ1CorridorOccupancy.class.getDeclaredField(name);field.setAccessible(true);text.append(name).append(freeze(field.get(ledger),seen));
        }
        return text.toString();
    }
    private static String freeze(Object v,IdentityHashMap<Object,Integer> seen) throws ReflectiveOperationException {
        if(v==null)return "null";if(v instanceof Number||v instanceof String||v instanceof Boolean||v instanceof Id<?>)return v.toString();
        if(seen.containsKey(v))return "ref"+seen.get(v);seen.put(v,seen.size());var text=new StringBuilder(v.getClass().getName()).append('[');
        if(v instanceof Map<?,?> map)for(var e:map.entrySet())text.append(freeze(e.getKey(),seen)).append('=').append(freeze(e.getValue(),seen));
        else if(v instanceof Iterable<?> items)for(var item:items)text.append(freeze(item,seen));
        else if(v.getClass().isArray())for(int i=0;i<Array.getLength(v);i++)text.append(freeze(Array.get(v,i),seen));
        else if(v.getClass().getEnclosingClass()==SimZ1CorridorOccupancy.class)for(var field:v.getClass().getDeclaredFields()) {
            if(Modifier.isStatic(field.getModifiers()))continue;field.setAccessible(true);text.append(field.getName()).append('=').append(freeze(field.get(v),seen));
        }
        else text.append(System.identityHashCode(v));return text.append(']').toString();
    }
    public static void main(String[] args) throws Exception {
        try {
            for(double body:new double[]{2.1,4.5,12.0}){twoBodiesOnly(body);cycleAndAlternative(body);feasibleAndUnproven(body);}
            existingReservationGuards();
            System.out.println("PASS opposed-return rerouting: proven two-head cycles rejected; receivable returns, parallel lanes, transient queues and straight exits retained; reservations/FIFO/priority/destination unchanged");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
