package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1PriorityReceiverCheck.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancyCheck.link;

/** Isolated calls, never Controler.run/QSim. Synthetic geometry reproduces the
 * reported 8.7528m connectors with 2.2527m and 3.7527m usable storage per lane.
 * Real metric reservations and an empty native connector queue; controllable
 * receiving queues fail loudly on any insertion, removal or unexpected call. */
public final class SimZ1TenthStreetReceptionCheck {
    private static final class LaneState {
        boolean accepting=true,green=true;
        QVehicle head;
        final QLaneI lane;
        LaneState(String name) {
            lane=(QLaneI)Proxy.newProxyInstance(QLaneI.class.getClassLoader(),
                new Class<?>[]{QLaneI.class,SignalizeableItem.class},(p,m,a)->switch(m.getName()) {
                    case "getId"->Id.create(name,Lane.class);
                    case "isAcceptingFromUpstream"->accepting;
                    case "hasGreenForToLink"->green;
                    case "isNotOfferingVehicle"->head==null;
                    case "getFirstVehicle"->head;
                    default->throw new AssertionError("Physical probe touched/mutated native queue: "+m);
                });
        }
    }

    static QLaneI emptyNativeQueue(Scenario scenario,EventsManager events,Link link) {
        var context=new NetsimEngineContext(events,7.5,null,null,scenario.getConfig().qsim(),new MobsimTimer(),null);
        var lanes=new QueueWithBuffer.Builder(context);lanes.setLaneId(Id.create(link.getId()+".original",Lane.class));
        var builder=new QLinkImpl.Builder(context,null);builder.setLaneFactory(lanes);
        return builder.build(link,null).getAcceptingQLane();
    }
    static void registerNodes(Scenario scenario,EventsManager events,QNetwork qnet,SimZ1CorridorOccupancy ledger) {
        var engine=proxy(QNetsimEngineI.NetsimInternalInterface.class,(p,m,a)->switch(m.getName()) {
            case "getNetsimNetwork"->qnet;
            default->throw new AssertionError("No simulated movement/arrival allowed: "+m);
        });
        var context=new NetsimEngineContext(events,7.5,null,null,scenario.getConfig().qsim(),new MobsimTimer(),null);
        var builder=new Zona1QNodeImpl.Builder(engine,context,scenario.getConfig().qsim(),new Zona1NativeDiagnostics(scenario,events));
        var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);
        builder.setAdmissionPolicy(admission,new Zona1PriorityConfigGroup());
        // Any accidental turn/admission callback from a physical query fails.
        builder.setTurnAcceptanceLogic((l,q,n,v,network,time)->{throw new AssertionError("Recursive priority/admission query");});
        for(var node:scenario.getNetwork().getNodes().values())ledger.registerNode(builder.build(node));
    }

    private static final class Fixture implements AutoCloseable {
        final Scenario scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final List<Event> events=new ArrayList<>();
        final Map<String,LaneState> entrances=new HashMap<>(),terminals=new HashMap<>();
        final SimZ1CorridorOccupancy ledger;
        final QNetwork qnet;
        final QVehicle avenue,street;
        final UnsignalizedPriority.StopAndYield priority;
        Fixture(double usable,double body,boolean forbidReceiptSlot0) {
            var n=scenario.getNetwork();var coords=new LinkedHashMap<String,Coord>();
            coords.put("west",new Coord(-100,0));coords.put("south",new Coord(0,-100));coords.put("j",new Coord(0,0));
            coords.put("b",new Coord(8.7528,0));coords.put("a-end",new Coord(28.7528,0));coords.put("a-dest",new Coord(128.7528,0));
            coords.put("b-end",new Coord(48.7528,0));coords.put("b-dest",new Coord(148.7528,0));
            int crossLanes=usable<3?3:2;double sin=1.5*crossLanes/(8.7528-usable-2);
            coords.put("side",new Coord(8.7528+100*Math.sqrt(1-sin*sin),100*sin));
            for(var e:coords.entrySet())n.addNode(n.getFactory().createNode(Id.createNodeId(e.getKey()),e.getValue()));
            link(n,"avenue","south","j",100,2);link(n,"street","west","j",100,1);
            link(n,"short","j","b",8.7528,1);
            link(n,"receipt-a","b","a-end",20,2);link(n,"receipt-b","b","b-end",20,2);
            link(n,"dest-a","a-end","a-dest",100,2);link(n,"dest-b","b-end","b-dest",100,2);
            link(n,"cross","b","side",100,crossLanes);
            for(String name:List.of("a-end","b-end"))n.getNodes().get(Id.createNodeId(name)).getAttributes().putAttribute("highway","stop");
            for(var l:n.getLinks().values())l.getAttributes().putAttribute("simz1:priorityRole",l.getId().equals(id("street"))?"street":"avenue");
            LanesGenerator.build(scenario);
            if(forbidReceiptSlot0)scenario.getLanes().getLanesToLinkAssignments().get(id("receipt-a")).getLanes()
                .get(Id.create("receipt-a.lane.0",Lane.class)).getToLinkIds().remove(id("dest-a"));
            var manager=EventsUtils.createEventsManager();manager.addHandler((BasicEventHandler)events::add);
            ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);SimZ1CorridorOccupancy.install(scenario.getConfig().qsim(),ledger);
            require(Math.abs(8.7528-ledger.setback(id("short"))-usable)<1e-8,"Reported short-link storage not reproduced");
            avenue=planned("major",body,List.of("avenue","short","receipt-a","dest-a"));
            street=planned("minor",body,List.of("street","short","receipt-b","dest-b"));
            var links=new HashMap<Id<Link>,QLinkI>();
            for(var l:n.getLinks().values()) {
                String name=l.getId().toString();var entry=new LaneState(name+".original");entrances.put(name,entry);
                var offered=new ArrayList<QLaneI>();
                for(int slot=0;slot<(int)l.getNumberOfLanes();slot++) {
                    var terminal=new LaneState(name+".lane."+slot);terminals.put(name+"."+slot,terminal);offered.add(terminal.lane);
                }
                QLaneI accepting=name.equals("short")?emptyNativeQueue(scenario,manager,l):entry.lane;
                links.put(l.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()) {
                    case "getLink"->l;case "getAcceptingQLane"->accepting;case "getOfferingQLanes"->offered;
                    default->throw new AssertionError("Unexpected native link query: "+m);
                }));
            }
            qnet=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
            registerNodes(scenario,manager,qnet,ledger);
            terminals.get("avenue.0").head=avenue;terminals.get("street.0").head=street;
            var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");settings.setConflicts("conservative");
            priority=new UnsignalizedPriority.StopAndYield(n.getNodes().get(Id.createNodeId("j")),settings,null,null,scenario.getConfig().qsim());
            require(ledger.activity(avenue,id("avenue"),"avenue.original",0),"Avenue origin cannot store body");
            require(ledger.activity(street,id("street"),"street.original",0),"Street origin cannot store body");
        }
        QVehicle planned(String name,double body,List<String> path) {
            var v=SimZ1PriorityLookaheadCheck.planned(scenario,name,path);v.getVehicle().getType().setLength(body);
            v.getVehicle().getType().setPcuEquivalents(body<3?.25:body>10?3:1).setWidth(body<3?.8:body>10?2.5:1.8).setNetworkMode(body>10?"bus":"car");return v;
        }
        SimZ1CorridorOccupancy.PhysicalFeasibility query(QVehicle v,double now) {
            return SimZ1CorridorOccupancy.receiverFeasibility(scenario.getConfig().qsim(),v,id("short"),"short.original",qnet,now);
        }
        TurnAcceptanceLogic.AcceptTurn decide(QVehicle v,double now) {
            String name=v==avenue?"avenue":"street";
            return priority.isAcceptingTurn(scenario.getNetwork().getLinks().get(id(name)),terminals.get(name+".0").lane,id("short"),v,qnet,now);
        }
        boolean passage(QVehicle v,double now) {
            return priority.passageMayProceed(scenario.getNetwork().getLinks().get(id(v==avenue?"avenue":"street")),id("short"),v,qnet,now);
        }
        @Override public void close(){SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());}
    }

    /** Deep read of all mutable ledger state, including private bodies, slots,
     * locks, pending choices, hold times and ordinals. No production test hook. */
    private static String state(SimZ1CorridorOccupancy ledger) throws ReflectiveOperationException {
        var result=new StringBuilder();var seen=new IdentityHashMap<Object,Integer>();
        for(String name:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks",
                "passageRequestTime","passageDeadlines","waits","waitReasons","nextOrdinal")) {
            var field=SimZ1CorridorOccupancy.class.getDeclaredField(name);field.setAccessible(true);
            result.append(name).append(freeze(field.get(ledger),seen));
        }
        return result.toString();
    }
    private static String freeze(Object value,IdentityHashMap<Object,Integer> seen) throws ReflectiveOperationException {
        if(value==null)return "null";
        if(value instanceof Number||value instanceof String||value instanceof Boolean||value instanceof Id<?>)return value.toString();
        if(seen.containsKey(value))return "ref"+seen.get(value);seen.put(value,seen.size());
        var text=new StringBuilder(value.getClass().getName()).append('[');
        if(value instanceof Map<?,?> map)for(var e:map.entrySet())text.append(freeze(e.getKey(),seen)).append('=').append(freeze(e.getValue(),seen));
        else if(value instanceof Iterable<?> items)for(var item:items)text.append(freeze(item,seen));
        else if(value.getClass().isArray())for(int i=0;i<Array.getLength(value);i++)text.append(freeze(Array.get(value,i),seen));
        else if(value.getClass().getEnclosingClass()==SimZ1CorridorOccupancy.class)for(var f:value.getClass().getDeclaredFields()) {
            if(Modifier.isStatic(f.getModifiers()))continue;f.setAccessible(true);text.append(f.getName()).append('=').append(freeze(f.get(value),seen));
        }
        else text.append(System.identityHashCode(value));
        return text.append(']').toString();
    }
    private static void expect(Fixture f,QVehicle vehicle,boolean feasible,String reason) throws Exception {
        String before=state(f.ledger);int events=f.events.size();
        for(double now:new double[]{7835,7836,36000,72000}) {
            var result=f.query(vehicle,now);require(result.feasible()==feasible,"Unexpected physical result: "+result);
            require(reason.equals(result.reason()),"Unspecific/wrong physical cause: "+result);
        }
        require(before.equals(state(f.ledger))&&events==f.events.size(),"Pure probe changed bodies/locks/timers/events");
    }
    private static void physicalCases(double usable,double body) throws Exception {
        try(var f=new Fixture(usable,body,false)) {
            expect(f,f.avenue,true,"receiver_available");
            // Both routes enter the same 8.7528m connector, then diverge.
            f.entrances.get("receipt-a").accepting=false;
            expect(f,f.avenue,false,"passage_receipt_native_queue");expect(f,f.street,true,"receiver_available");
            require(f.passage(f.street,7835),"Unreceivable avenue monopolized priority");
            require(!f.ledger.canEnter(f.avenue,id("short"),"short.original",7835),"Admission ignored downstream queue");
            require(f.events.stream().anyMatch(e->"passage_receipt_native_queue".equals(e.getAttributes().get("reason"))),"Admission lost the precise cause");
            f.entrances.get("receipt-a").accepting=true;
            expect(f,f.avenue,true,"receiver_available");
            require(!f.passage(f.street,7836),"Executable avenue lost priority");
            // Empty entry queue is insufficient when the body needs terminal space.
            f.terminals.get("receipt-a.0").accepting=false;f.terminals.get("receipt-a.1").accepting=false;
            expect(f,f.avenue,false,"passage_receipt_native_queue");
            f.terminals.get("receipt-a.1").accepting=true;
            expect(f,f.avenue,true,"receiver_available");
            // Admission must commit the same free, compatible slot as the probe.
            require(f.ledger.canEnter(f.avenue,id("short"),"short.original",7840),"Free compatible receipt lane ignored");
            f.ledger.enter(f.avenue,id("short"),"short.original",7840,"queue_entry");
            var acquired=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(e.getAttributes().get("action"))).findFirst().orElseThrow().getAttributes();
            require("receipt-a".equals(acquired.get("receiptLink")),"Wrong full-body receiver");
            require(Double.parseDouble(acquired.get("receiptFreeFrontMeters"))+1e-8>=Double.parseDouble(acquired.get("clearanceFrontMeters")),"Missing full-body exit clearance");
            var reservation=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyReservation")&&"ENTER".equals(e.getAttributes().get("action"))&&"short".equals(e.getAttributes().get("link"))).findFirst().orElseThrow().getAttributes();
            require("1".equals(reservation.get("modelSlot")),"Admission reselected blocked slot0");
            require(Math.abs(Double.parseDouble(reservation.get("footprintMeters"))-body-.10)<1e-8,"Lost 0.10m gap");
            expect(f,f.street,false,"passage_node_locked");
            String before=state(f.ledger);int count=f.events.size();
            require(!f.passage(f.street,7841),"Acquired avenue passage lost priority");
            require(before.equals(state(f.ledger))&&count==f.events.size(),"Priority acquired/released storage");
            require(f.events.stream().noneMatch(e->e.getEventType().equals("arrival")||e.getEventType().equals("PersonArrival")),"Artificial arrival");
            var leg=(org.matsim.api.core.v01.population.Leg)((org.matsim.core.mobsim.framework.PlanAgent)f.avenue.getDriver()).getCurrentPlanElement();
            var route=(org.matsim.core.population.routes.NetworkRoute)leg.getRoute();
            require(route.getEndLinkId().equals(id("dest-a"))&&route.getLinkIds().equals(List.of(id("short"),id("receipt-a"))),"Destination/route changed during reception");
        }
    }
    private static void blockedFairness(double usable,double body) throws Exception {
        try(var f=new Fixture(usable,body,false)) {
            f.entrances.get("receipt-b").accepting=false;
            f.priority.observeHeads(f.qnet,7800);
            require(f.decide(f.avenue,7836)==TurnAcceptanceLogic.AcceptTurn.GO,"Blocked minor acquired fairness");
            require(f.decide(f.street,7836)==TurnAcceptanceLogic.AcceptTurn.WAIT&&"passage_receipt_native_queue".equals(f.priority.getLastWaitReason()),"Blocked minor concealed under priority_fairness");
            f.entrances.get("receipt-b").accepting=true;
            require(f.decide(f.avenue,7837)==TurnAcceptanceLogic.AcceptTurn.WAIT&&"priority_fairness".equals(f.priority.getLastWaitReason()),"Executable old street lost fairness");
            f.entrances.get("receipt-b").accepting=false;
            require(f.decide(f.avenue,7837)==TurnAcceptanceLogic.AcceptTurn.GO,"Stale fairness monopolized the same step");
        }
    }
    private static void metricAndLaneCases(double usable,double body) throws Exception {
        try(var f=new Fixture(usable,body,true)) {
            f.terminals.get("receipt-a.1").accepting=false;
            expect(f,f.avenue,false,"passage_receipt_native_queue"); // free slot0 cannot make this turn
            f.terminals.get("receipt-a.1").accepting=true;
            expect(f,f.avenue,true,"receiver_available");
            var blocker=vehicle("receiving-body",4.5,"dest-a");
            require(f.ledger.canEnter(blocker,id("receipt-a"),"receipt-a.lane.1",1),"Blocker setup");
            f.ledger.enter(blocker,id("receipt-a"),"receipt-a.lane.1",1,"queue_entry");
            expect(f,f.avenue,false,"passage_receipt_storage_or_slot");
            require(f.passage(f.street,7835),"Metric/FIFO-blocked avenue competed");
            f.ledger.release(blocker.getId(),7836,"fixture_departure");
            expect(f,f.avenue,true,"receiver_available");
            f.terminals.get("short.0").green=false;
            expect(f,f.avenue,false,"passage_signal_not_green");
            require(f.passage(f.street,7837),"Red downstream connector competed");
        }
        try(var f=new Fixture(usable,body,false)) {
            var unknown=vehicle("no-route",body,"short");
            expect(f,unknown,false,"passage_route_unavailable");
            // A route that ends on the tiny connector cannot borrow off-network storage.
            var terminal=f.planned("terminal",body,List.of("avenue","short"));
            expect(f,terminal,false,"passage_no_receipt_or_origin_storage");
            require(!f.ledger.canEnter(terminal,id("short"),"short.original",10),"Invented an origin reservation");
            require(f.events.stream().noneMatch(e->"passage_not_authorized".equals(e.getAttributes().get("reason"))),"Generic cause returned");
        }
    }
    public static void main(String[] args) throws Exception {
        try {
            for(double usable:new double[]{2.2527,3.7527})for(double body:new double[]{4.5,2.1,12.0}) {
                physicalCases(usable,body);blockedFairness(usable,body);metricAndLaneCases(usable,body);
            }
            System.out.println("PASS tenth-street reception: car/motorcycle/bus; both short receivers; pure queries; native/metric blocks; avenue/fairness; compatible slots; FIFO, signals, 0.10m gap and body locks");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
