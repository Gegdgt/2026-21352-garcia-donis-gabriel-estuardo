package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Correction 3: release lifecycle only, no controller or simulation.
 * Reconstructs an already-held passage through the production acquire hook,
 * as in PassageTimerCheck. This seam does NOT test passage authorization.
 * Synthetic fixture links/lanes never rewrite the project network or a run.
 * All coordinates asserted here are conservative bounds, not observations.
 */
public final class SimZ1TransitPassageReleaseCheck {
    static final double ORIGINAL_END=11.448971553979469, LINK_LENGTH=57.24485776989736;
    static final double BUS_CLEAR=17.279379950716642, DEADLINE=25444.51655811328;
    static final Id<Link> RECEIPT=id("receipt"), TAIL=id("tail");
    static final String ORIGINAL="receipt.original", MIDDLE="receipt.middle", TERMINAL="receipt.lane.0";
    static final Id<Vehicle> WAITER=Id.createVehicleId("unrelated-waiter");
    static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void close(double value,double expected,String message){require(Math.abs(value-expected)<1e-9,message+": "+value+" != "+expected);}
    static Id<Link> id(String value){return Id.createLinkId(value);}
    static Object field(Object object,String name) throws Exception {
        var f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);
    }
    static void set(Object object,String name,Object value) throws Exception {
        var f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);
    }
    static QVehicleImpl vehicle(String name,double body){
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
        type.setLength(body).setWidth(body==2.1?.8:2.5).setMaximumVelocity(10)
            .setPcuEquivalents(body==13.5?3:body==2.1?.25:body==8?2:1).setNetworkMode("car");
        return new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
    }
    static Scenario scenario(double clearance,boolean directSplit){
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();
        // Each connector is its own domain; the receiver and tail form one.
        double[][] coords={{-9,0},{-6,0},{-3,0},{0,0},{LINK_LENGTH,0},{LINK_LENGTH+110,0},
            {-3,100},{0,100},{80,100}};
        for(int i=0;i<coords.length;i++)n.addNode(n.getFactory().createNode(Id.createNodeId("n"+i),new Coord(coords[i][0],coords[i][1])));
        for(int i:new int[]{0,1,2,3,7})n.getNodes().get(Id.createNodeId("n"+i)).getAttributes().putAttribute("osm:highway","stop");
        link(n,"c0","n0","n1",3,1);link(n,"c1","n1","n2",3,1);link(n,"c2","n2","n3",3,1);
        link(n,"receipt","n3","n4",LINK_LENGTH,2);link(n,"tail","n4","n5",110,2);
        link(n,"foreign-c","n6","n7",3,1);link(n,"foreign-r","n7","n8",80,1);
        var lf=s.getLanes().getFactory();var assignment=lf.createLanesToLinkAssignment(RECEIPT);
        // For small vehicles keep the first endpoint strictly below clearance.
        double split=Math.min(ORIGINAL_END,clearance-1);
        var terminals=List.of(Id.create(TERMINAL,Lane.class),Id.create("receipt.lane.1",Lane.class));
        LanesUtils.createAndAddLane(assignment,lf,Id.create(ORIGINAL,Lane.class),10000,LINK_LENGTH,0,2,null,
            directSplit?terminals:List.of(Id.create(MIDDLE,Lane.class)));
        if(!directSplit)LanesUtils.createAndAddLane(assignment,lf,Id.create(MIDDLE,Lane.class),10000,LINK_LENGTH-split,0,2,null,terminals);
        for(int slot=0;slot<2;slot++)LanesUtils.createAndAddLane(assignment,lf,Id.create("receipt.lane."+slot,Lane.class),5000,
            LINK_LENGTH-(directSplit?split:clearance),slot,1,List.of(TAIL),null);
        s.getLanes().addLanesToLinkAssignment(assignment);return s;
    }
    private static void link(Network n,String name,String from,String to,double length,int lanes){
        var l=n.getFactory().createLink(id(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setNumberOfLanes(lanes);l.setCapacity(10000);l.setFreespeed(10);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
    }
    static final class Fixture {
        final Scenario scenario;
        final List<Event> events=new ArrayList<>();
        final org.matsim.core.api.experimental.events.EventsManager manager=EventsUtils.createEventsManager();
        final SimZ1CorridorOccupancy ledger;
        final QVehicleImpl owner;
        final double clearance;
        Fixture(String name,double body){this(name,body,false);}
        Fixture(String name,double body,boolean directSplit){
            double requested=body==13.5?BUS_CLEAR:body+SimZ1CorridorOccupancy.GAP+(BUS_CLEAR-13.6);
            // Use the identical double coordinate generated by queueEndpoint;
            // the exact-boundary check must not depend on cancellation rounding.
            clearance=LINK_LENGTH-(LINK_LENGTH-requested);
            scenario=scenario(clearance,directSplit);manager.addHandler((BasicEventHandler)events::add);
            ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);owner=vehicle(name,body);
        }
        void admit(QVehicle v,Id<Link> link,String lane,double now){
            require(ledger.canEnter(v,link,lane,now),"Fixture admission rejected: "+v.getId());ledger.enter(v,link,lane,now,"queue_entry");
        }
        void held(double deadline) throws Exception {
            admit(owner,RECEIPT,ORIGINAL,25440);installPassage(this,owner,RECEIPT,List.of(id("c0"),id("c1"),id("c2")),clearance,deadline);
            ledger.enter(owner,RECEIPT,ORIGINAL,25447,"queue_entry");
        }
        long releases(QVehicle v){return events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")
            &&"RELEASE".equals(e.getAttributes().get("action"))&&v.getId().toString().equals(e.getAttributes().get("vehicle"))).count();}
        List<Event> states(){return events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassageState")).toList();}
        Object reservation(QVehicle v) throws Exception {return ((Map<?,?>)field(ledger,"active")).get(v.getId());}
        double front(QVehicle v) throws Exception {return (double)field(reservation(v),"frontBound");}
        double nativeFront(QVehicle v) throws Exception {return (double)field(reservation(v),"nativeFront");}
        void heldLocks(){for(int i=0;i<4;i++)require(ledger.lockedByOther(Id.createNodeId("n"+i),WAITER),"Missing held node n"+i);}
        void releasedLocks(){for(int i=0;i<4;i++)require(!ledger.lockedByOther(Id.createNodeId("n"+i),WAITER),"Leaked node n"+i);}
        void finish(double now) throws Exception {
            var ids=new ArrayList<>(((Map<Id<Vehicle>,?>)field(ledger,"active")).keySet());
            for(var v:ids)ledger.release(v,now,"fixture_cleanup");
            for(String name:List.of("active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks"))
                require(((Map<?,?>)field(ledger,name)).isEmpty(),"Orphan in "+name);
            ledger.advanceTime(now+100000);require(((Queue<?>)field(ledger,"passageDeadlines")).isEmpty(),"Unconsumed obsolete deadline");
            verifyEvidence(this);
        }
    }
    static void installPassage(Fixture f,QVehicle owner,Id<Link> receipt,List<Id<Link>> connectors,double clear,double deadline) throws Exception {
        Object reservation=f.reservation(owner);var n=f.scenario.getNetwork();
        var type=Class.forName(SimZ1CorridorOccupancy.class.getName()+"$Passage");
        var ctor=type.getDeclaredConstructors()[0];ctor.setAccessible(true);
        var slots=new LinkedHashMap<Id<Link>,Integer>();for(var link:connectors)slots.put(link,0);
        var p=ctor.newInstance(connectors.stream().map(n.getLinks()::get).toList(),slots,n.getLinks().get(receipt),0.,null);
        set(p,"notBefore",deadline);set(p,"clearFront",clear);set(p,"freeFront",100.);set(p,"reachableFront",100.);
        var acquire=SimZ1CorridorOccupancy.class.getDeclaredMethod("acquirePassage",Id.class,reservation.getClass(),type,Id.class);
        acquire.setAccessible(true);acquire.invoke(f.ledger,owner.getId(),reservation,p,connectors.get(0));
    }
    static void verifyEvidence(Fixture f){
        for(var e:f.events){var a=e.getAttributes();
            require(!"FORCE".equals(a.get("decision")),"Forced movement");
            if(e.getEventType().equals("simz1OccupancyProgress")){
                require("false".equals(a.get("positionsObserved")),"Invented microscopic position");
                if(a.containsKey("leaderVehicle"))require(Double.parseDouble(a.get("modeledFrontLowerBoundMeters"))
                    <=Double.parseDouble(a.get("leaderFrontLowerBoundMeters"))-Double.parseDouble(a.get("leaderFootprintMeters"))+1e-9,"FIFO/gap violation");
            }
            if(e.getEventType().equals("simz1OccupancyPassageState")){
                require("false".equals(a.get("positionsObserved")),"Diagnostic claims observed position");
                close(Double.parseDouble(a.get("minimumGapMeters")),.1,"Diagnostic gap changed");
                if("passage_released_after_clearance".equals(a.get("reason")))require(
                    "true".equals(a.get("minimumTimeSatisfied"))&&"true".equals(a.get("bodyClearanceSatisfied")),"Unproved clearance release");
            }
        }
        SimZ1CorridorOccupancyCheck.verifyTransactions(f.events);
    }
    private static void historicalStoppedBus() throws Exception {
        var f=new Fixture("ptbus_transmetro_L12_031",13.5);f.held(DEADLINE);
        f.ledger.progress(f.owner,RECEIPT,ORIGINAL,25501);
        close(f.front(f.owner),ORIGINAL_END,"Historical bound");close(f.nativeFront(f.owner),ORIGINAL_END,"Native endpoint");
        long events=f.events.size();
        f.ledger.advanceTime(68400); // consumes the earlier deadline without granting displacement
        require(((Queue<?>)field(f.ledger,"passageDeadlines")).isEmpty(),"Deadline was not consumed");
        for(int now=68401;now<=68500;now++)f.ledger.advanceEligible(List.of(),RECEIPT,ORIGINAL,now);
        f.heldLocks();require(f.releases(f.owner)==0,"Waiting time released stopped 13.5m bus");
        close(f.front(f.owner),ORIGINAL_END,"Empty native buffer clock invented progress");
        require(f.events.size()==events,"Stationary wait emitted repeated events");
        require(f.states().stream().anyMatch(e->"passage_waiting_for_native_progress".equals(e.getAttributes().get("reason"))),"Missing native-progress distinction");
        close((double)field(f.reservation(f.owner),"footprint"),13.6,"Bus resized");
        f.finish(68600);System.out.println("PASS stopped bus: 11.448971553979469 < 17.279379950716642; no timeout release");
    }
    private static void lateExactClearance(double body) throws Exception {
        var f=new Fixture("late-"+body,body);f.held(DEADLINE);f.ledger.advanceTime(26000);
        require(((Queue<?>)field(f.ledger,"passageDeadlines")).isEmpty(),"Deadline still queued");
        f.ledger.enter(f.owner,RECEIPT,MIDDLE,26001,"queue_entry");f.owner.setEarliestLinkExitTime(26002);
        f.ledger.advanceEligible(List.of(f.owner),RECEIPT,MIDDLE,26001);f.heldLocks();
        f.ledger.advanceEligible(List.of(f.owner),RECEIPT,MIDDLE,26002);
        close(f.front(f.owner),f.clearance,"Exact native endpoint");f.releasedLocks();require(f.releases(f.owner)==1,"Late clearance did not release once");
        f.ledger.progress(f.owner,RECEIPT,MIDDLE,26002);f.ledger.advanceTime(68400);
        require(f.releases(f.owner)==1,"Buffer arrival or clock duplicated release");
        require(f.reservation(f.owner)!=null,"Passage release removed body reservation");f.finish(68401);
        System.out.println("PASS late exact clearance / consumed deadline, body="+body);
    }
    private static void bodyBeforeTime() throws Exception {
        var f=new Fixture("early-bus",13.5);double deadline=26000.5;f.held(deadline);
        f.ledger.enter(f.owner,RECEIPT,MIDDLE,25500,"queue_entry");f.ledger.progress(f.owner,RECEIPT,MIDDLE,25501);
        f.ledger.advanceTime(26000);f.heldLocks();require(f.releases(f.owner)==0,"Early spatial clearance ignored time");
        long progress=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyProgress")).count();
        f.ledger.advanceTime(deadline);f.releasedLocks();require(f.releases(f.owner)==1,"Timer missed cleared buffer owner");
        require(f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyProgress")).count()==progress,"Timer invented progress");
        require(f.states().stream().anyMatch(e->"passage_waiting_for_time".equals(e.getAttributes().get("reason"))),"Missing time distinction");
        f.finish(26001);System.out.println("PASS body before time: fractional deadline, no extra native transition");
    }
    private static void leaderRelease() throws Exception {
        var f=new Fixture("bus-behind-leader",13.5);var leader=vehicle("leader",2.1);
        f.admit(leader,RECEIPT,TERMINAL,25439); // native start is exactly BUS_CLEAR
        // Reconstructed held lifecycle state, not a claim that authorization
        // would allow a fresh passage behind this already stopped leader.
        f.admit(f.owner,RECEIPT,TERMINAL,25440);installPassage(f,f.owner,RECEIPT,List.of(id("c0"),id("c1"),id("c2")),f.clearance,DEADLINE);
        f.ledger.enter(f.owner,RECEIPT,MIDDLE,25447,"queue_entry");f.ledger.progress(f.owner,RECEIPT,MIDDLE,25501);f.ledger.advanceTime(26000);
        close(f.front(f.owner),BUS_CLEAR-2.2,"Leader FIFO bound");f.heldLocks();
        require(f.states().stream().anyMatch(e->"passage_waiting_for_body_clearance".equals(e.getAttributes().get("reason"))),"Missing body/leader distinction");
        double nativeFront=f.nativeFront(f.owner);f.ledger.release(leader.getId(),26001,"arrival");
        close(f.nativeFront(f.owner),nativeFront,"Leader release invented endpoint");close(f.front(f.owner),BUS_CLEAR,"Leader release failed recompute");
        f.releasedLocks();require(f.releases(f.owner)==1,"Leader release missed consumed deadline");f.finish(26002);
        System.out.println("PASS leader release: same slot FIFO recompute releases once, native endpoint unchanged");
    }
    private static void nativeTransferAndOtherLocks() throws Exception {
        var f=new Fixture("transfer-bus",13.5);f.held(DEADLINE);
        var other=vehicle("other-owner",4.5);f.admit(other,id("foreign-r"),"foreign-r.original",25448);
        installPassage(f,other,id("foreign-r"),List.of(id("foreign-c")),20,70000);
        f.ledger.advanceTime(26000);
        var foreignNodes=new HashMap<>((Map<?,?>)field(f.ledger,"nodeLocks"));foreignNodes.entrySet().removeIf(e->!other.getId().equals(e.getValue()));
        require(foreignNodes.size()==2,"Foreign lock fixture");
        f.ledger.enter(f.owner,RECEIPT,TERMINAL,26001,"queue_entry"); // start of this native queue proves CLEAR
        close(f.front(f.owner),BUS_CLEAR,"Native lane start not processed");f.releasedLocks();require(f.releases(f.owner)==1,"Native transfer missed clearance");
        require(field(f.ledger,"nodeLocks").equals(foreignNodes),"Released another owner's nodes");
        require(((Map<?,?>)field(f.ledger,"connectorLocks")).size()==1&&((Map<?,?>)field(f.ledger,"receiptLocks")).size()==1,"Own connector/receipt lock leaked");
        f.ledger.enter(f.owner,TAIL,"tail.original",26002,"queue_entry");
        close(f.front(f.owner),LINK_LENGTH,"Next-link entry not synchronized");require(f.releases(f.owner)==1,"Next link released twice");
        f.finish(26003);System.out.println("PASS native transfers and four protected nodes: only correct owner's locks removed");
    }
    private static void fifoAndIndependentSlots() throws Exception {
        var f=new Fixture("fifo-bus",13.5);f.admit(f.owner,RECEIPT,TERMINAL,1);f.ledger.progress(f.owner,RECEIPT,TERMINAL,2);
        var followers=List.of(vehicle("car",4.5),vehicle("motorcycle",2.1),vehicle("truck",8));
        for(var v:followers){f.admit(v,RECEIPT,TERMINAL,3);f.ledger.progress(v,RECEIPT,TERMINAL,4);}
        var independent=vehicle("independent",4.5);f.admit(independent,RECEIPT,"receipt.lane.1",5);
        f.ledger.progress(independent,RECEIPT,"receipt.lane.1",6);close(f.front(independent),LINK_LENGTH,"Independent lane held by bus lane");
        double front=LINK_LENGTH,footprint=13.6;
        for(var v:followers){front-=footprint;close(f.front(v),front,"Follower overtook occupied body");footprint=v.getVehicle().getType().getLength()+.1;}
        f.ledger.advanceTime(68400);close(f.front(followers.get(0)),LINK_LENGTH-13.6,"Time overtook bus");
        f.ledger.release(f.owner.getId(),68401,"arrival");close(f.front(followers.get(0)),LINK_LENGTH,"Follower not updated after departure");
        close(f.front(independent),LINK_LENGTH,"Unrelated slot changed");f.finish(68402);
        System.out.println("PASS FIFO and >=0.10m separation for bus, car, motorcycle, 8m truck; independent slot progresses");
    }
    private static void nativeExitAndReusedId() throws Exception {
        var f=new Fixture("reused-bus",13.5);f.held(70000);f.ledger.progress(f.owner,RECEIPT,ORIGINAL,25501);
        f.ledger.release(f.owner.getId(),26000,"arrival");f.releasedLocks();require(f.releases(f.owner)==1,"Verified native exit leaked passage");
        f.ledger.release(f.owner.getId(),26000,"arrival");require(f.releases(f.owner)==1,"Repeated exit released twice");
        f.admit(f.owner,RECEIPT,ORIGINAL,26001);Object newReservation=f.reservation(f.owner);
        f.ledger.advanceTime(70001);require(f.reservation(f.owner)==newReservation,"Stale deadline affected reused vehicle ID");
        require(f.states().stream().noneMatch(e->"passage_released_after_clearance".equals(e.getAttributes().get("reason"))),"Native exit mislabeled as spatial clearance");
        f.finish(70002);System.out.println("PASS native exit cleanup, idempotent release, stale deadline/new ordinal isolation");
    }
    public static void main(String[] args) throws Exception {
        historicalStoppedBus();for(double body:new double[]{13.5,4.5,2.1,8})lateExactClearance(body);
        bodyBeforeTime();leaderRelease();nativeTransferAndOtherLocks();fifoAndIndependentSlots();nativeExitAndReusedId();
        System.out.println("PASS SimZ1TransitPassageReleaseCheck (ledger lifecycle fixtures only)");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
