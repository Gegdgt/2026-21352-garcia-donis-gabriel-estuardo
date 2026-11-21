package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Phase 1 baseline, not an approval or a proposed admission implementation.
 * Reads frozen effective network/lanes/signals, never population or events.
 * Seeds two native terminal queues to reproduce the documented day-cut state;
 * it does not claim to replay their historical route or first denied attempt.
 * Only component methods run: no Controller, QSim or massive launcher.
 */
public final class SimZ1OriginAdmissionFixture {
    static final String PRE="osm_762765906_0_forward", ORIGIN="osm_762765906_1_forward";
    static final String TAIL="osm_762765906_2_forward", OUT="osm_762765906_3_forward";
    static final double OFFSET=29.455442492391022, CAPACITY=244.45828413352223;
    static final double BUFFER=125.24319035189197;
    static final List<Map<String,Object>> results=new ArrayList<>();
    static Id<Link> id(String s){return Id.createLinkId(s);}
    static void check(boolean b,String why){if(!b)throw new AssertionError(why);}
    static void near(double a,double b,String why){check(Math.abs(a-b)<1e-7,why+": "+a+" != "+b);}
    static Object field(Object object,String name)throws ReflectiveOperationException{
        var f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);
    }
    static Object call(Object object,String method,Class<?>[] types,Object... args)throws Exception{
        var m=object.getClass().getDeclaredMethod(method,types);m.setAccessible(true);return m.invoke(object,args);
    }
    /** Value snapshot of mutable ledger objects; Map.toString alone would miss
     * changes to an existing reservation, its front, domain usage or timers. */
    static String deep(Object value,IdentityHashMap<Object,Integer> seen)throws Exception{
        if(value==null||value instanceof Number||value instanceof Boolean||value instanceof CharSequence||value instanceof Enum<?>||value instanceof Id<?>)return String.valueOf(value);
        if(value instanceof Link link)return "link:"+link.getId();
        if(seen.containsKey(value))return "ref:"+seen.get(value);seen.put(value,seen.size());
        if(value instanceof Map<?,?> map){var out=new TreeMap<String,String>();for(var entry:map.entrySet())out.put(String.valueOf(entry.getKey()),deep(entry.getValue(),seen));return out.toString();}
        if(value instanceof Collection<?> values){var out=new ArrayList<String>();for(var item:values)out.add(deep(item,seen));return out.toString();}
        if(value.getClass().isArray()){var out=new ArrayList<String>();for(int i=0;i<Array.getLength(value);i++)out.add(deep(Array.get(value,i),seen));return out.toString();}
        if(value.getClass().getName().startsWith(SimZ1CorridorOccupancy.class.getName()+"$")){
            var out=new TreeMap<String,String>();var fields=new ArrayList<>(List.of(value.getClass().getDeclaredFields()));fields.sort(Comparator.comparing(Field::getName));
            for(var member:fields)if(!Modifier.isStatic(member.getModifiers())){member.setAccessible(true);out.put(member.getName(),deep(member.get(value),seen));}return out.toString();
        }
        return value.toString();
    }
    static void result(String name,Map<String,Object> details){var row=new LinkedHashMap<String,Object>();row.put("case",name);row.put("status","PASS");row.putAll(details);results.add(row);System.out.println("PASS "+name+" "+details);}

    static final class NativeOrigin implements AutoCloseable {
        final Scenario scenario;final MobsimTimer timer=new MobsimTimer(1);
        final List<Event> events=new ArrayList<>();final SimZ1CorridorOccupancy ledger;
        final Map<Id<Link>,QLinkI> links=new LinkedHashMap<>();final QNetwork qnet;
        NativeOrigin(Scenario scenario){
            this.scenario=scenario;var cfg=scenario.getConfig().qsim();
            cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);
            cfg.setTimeStepSize(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);
            var em=EventsUtils.createEventsManager();em.addHandler((BasicEventHandler)events::add);
            var controlled=new HashSet<Id<Node>>();var data=(SignalsData)scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
            for(var system:data.getSignalSystemsData().getSignalSystemData().values())for(var signal:system.getSignalData().values())
                controlled.add(scenario.getNetwork().getLinks().get(signal.getLinkId()).getToNode().getId());
            ledger=new SimZ1CorridorOccupancy(scenario,controlled,em);
            near(ledger.offset(id(ORIGIN)),OFFSET,"Frozen origin offset");
            check(ledger.corridorId(id(ORIGIN)).equals(PRE)&&ledger.corridorId(id(TAIL)).equals(PRE),"Frozen corridor identity");
            qnet=new QNetwork(scenario.getNetwork(),null){
                @Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}
                @Override public QLinkI getNetsimLink(Id<Link> key){return links.get(key);}
            };
            var engine=new QNetsimEngineI.NetsimInternalInterface(){
                public QNetwork getNetsimNetwork(){return qnet;}
                public void arrangeNextAgentState(MobsimAgent a){throw new AssertionError("Unexpected removal/state transition");}
                public void letVehicleArrive(QVehicle v){throw new AssertionError("No arrival in origin fixture");}
            };
            var context=new NetsimEngineContext(em,7.5,null,null,cfg,timer,null);
            var registry=new NetElementActivationRegistry(){
                void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}
                int getNumberOfSimulatedNodes(){return 0;}int getNumberOfSimulatedLinks(){return links.size();}
            };
            for(String name:List.of(PRE,ORIGIN,TAIL)){
                var link=scenario.getNetwork().getLinks().get(id(name));var lanes=scenario.getLanes().getLanesToLinkAssignments().get(link.getId());
                var q=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(link,null,LanesUtils.createLanes(link,lanes));
                q.setNetElementActivationRegistry(registry);links.put(link.getId(),q);
                for(var queue:q.getQueueLanes().values()){
                    var lane=lanes.getLanes().get(queue.getId());double length=lane.getStartsAtMeterFromLinkEnd();
                    if(lane.getToLaneIds()!=null)for(var child:lane.getToLaneIds())length=Math.min(length,lane.getStartsAtMeterFromLinkEnd()-lanes.getLanes().get(child).getStartsAtMeterFromLinkEnd());
                    near(queue.getStorageCapacity(),length*lane.getNumberOfRepresentedLanes()/7.5,"Native capacity changed");
                }
            }
            SimZ1CorridorOccupancy.install(cfg,ledger);
        }
        QLinkLanesImpl link(String name){return (QLinkLanesImpl)links.get(id(name));}
        QueueWithBuffer queue(String name,String suffix){return (QueueWithBuffer)link(name).getQueueLanes().get(Id.create(name+suffix,Lane.class));}
        QVehicleImpl actor(String name,double body,String... path){
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
            type.setLength(body).setPcuEquivalents(body==2.1?.25:1).setMaximumVelocity(10).setNetworkMode("car");
            var vehicle=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
            var leg=scenario.getPopulation().getFactory().createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(Arrays.stream(path).map(SimZ1OriginAdmissionFixture::id).toList(),scenario.getNetwork()));
            vehicle.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class<?>[]{MobsimDriverAgent.class,PlanAgent.class},(p,m,a)->switch(m.getName()){
                case "getId"->Id.createPersonId(name);case "getMode"->"car";case "getCurrentPlanElement"->leg;
                case "getCurrentLinkId"->id(path[0]);case "chooseNextLinkId"->path.length>1?id(path[1]):null;
                case "isWantingToArriveOnCurrentLink"->false;
                default->throw new AssertionError("Unexpected native actor call: "+m);
            }));return vehicle;
        }
        void seed(QVehicle vehicle,String name,String suffix,double now){
            timer.setTime(now);var q=queue(name,suffix);
            check(q.isAcceptingFromUpstream()&&ledger.canEnter(vehicle,id(name),q.getId().toString(),now),"Invalid native seed "+vehicle.getId());q.addFromUpstream(vehicle);
        }
        void ready(String name,String suffix,double now){timer.setTime(now);var q=queue(name,suffix);q.initBeforeSimStep();q.doSimStep();}
        boolean admit(String name,double now)throws Exception{timer.setTime(now);return (boolean)call(link(name),"moveWaitToRoad",new Class<?>[]{double.class},now);}
        void waitFor(QVehicle v,String origin){link(origin).getWaitingList().add(v);}
        Object reservation(QVehicle v)throws Exception{return ((Map<?,?>)field(ledger,"active")).get(v.getId());}
        double front(QVehicle v)throws Exception{return (double)field(reservation(v),"frontBound");}
        int slot(QVehicle v)throws Exception{return (int)field(reservation(v),"slot");}
        long entries(){return events.stream().filter(e->e instanceof VehicleEntersTrafficEvent).count();}
        QVehicleImpl seedHolder(String name,int slot){var v=actor(name,2.1,TAIL,OUT);seed(v,TAIL,".lane."+slot,0);return v;}
        void readyHolder(QVehicleImpl v,int slot)throws Exception{
            ready(TAIL,".lane."+slot,100);
            near(front(v),CAPACITY,"Native endpoint does not reproduce historical lower bound");
            near((double)field(reservation(v),"footprint"),2.2,"Historical body/gap");
        }
        void pureQuery(QVehicle v,String origin,boolean expected,double now)throws Exception{
            var before=new LinkedHashMap<String,String>();
            for(String name:List.of("domains","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks","nextOrdinal","passageRequestTime","passageRequests","passageDeadlines","waits","waitReasons"))before.put(name,deep(field(ledger,name),new IdentityHashMap<>()));
            double beforeClock=timer.getTimeOfDay();
            int count=events.size();var probe=SimZ1CorridorOccupancy.receiverFeasibility(scenario.getConfig().qsim(),v,id(origin),origin+".original",qnet,now);
            check(probe.feasible()==expected,"Unexpected pure query: "+probe);
            for(var entry:before.entrySet())check(entry.getValue().equals(deep(field(ledger,entry.getKey()),new IdentityHashMap<>())),"Probe mutated "+entry.getKey());
            check(count==events.size()&&beforeClock==timer.getTimeOfDay(),"Probe emitted event or changed clock");
        }
        void safety()throws Exception{
            var active=(Map<?,?>)field(ledger,"active");
            for(var r:active.values()){
                near((double)field(r,"footprint"),(double)field(r,"length")+.1,"Lost minimum gap");
                var domain=field(r,"domain");var maps=(List<?>)field(domain,"reservations");
                for(var map:maps){Object leader=null;for(var body:((NavigableMap<?,?>)map).values()){
                    if(leader!=null)check((double)field(body,"frontBound")<=(double)field(leader,"frontBound")-(double)field(leader,"footprint")+1e-8,"Body overlap or FIFO overtaking");leader=body;
                }}
            }
            check(events.stream().noneMatch(e->e instanceof PersonArrivalEvent||e instanceof VehicleLeavesTrafficEvent||e instanceof PersonStuckEvent),"Manufactured arrival/removal");
        }
        @Override public void close(){SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());}
    }

    static void focal(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var a=f.seedHolder("focal-slot-0",0);var b=f.seedHolder("focal-slot-1",1);f.readyHolder(a,0);f.readyHolder(b,1);
            var third=f.actor("focal-third",2.1,ORIGIN,TAIL,OUT);f.pureQuery(third,ORIGIN,false,101);
            double rear=f.front(a)-2.2;check(BUFFER-2.2>=OFFSET&&rear>BUFFER,"Full body does not fit at native activity buffer point");
            f.waitFor(third,ORIGIN);check(!f.admit(ORIGIN,101),"Baseline changed: interior nonempty-slot guard no longer rejects");
            check(f.entries()==0&&f.reservation(third)==null&&f.link(ORIGIN).getWaitingList().peek()==third,"Denied activity mutated entry/FIFO/reservation");
            check(f.slot(a)==0&&f.slot(b)==1,"Historical slots drifted");
            check(f.events.stream().anyMatch(e->e.getEventType().equals("simz1OccupancyReservation")&&"WAIT".equals(e.getAttributes().get("action"))&&"receiver_storage_or_terminal_slot".equals(e.getAttributes().get("reason"))),"Missing current choose() rejection");
            f.safety();result("12-avenida-two-downstream-holders",Map.of("origin_offset_m",OFFSET,"native_activity_buffer_m",BUFFER,"leader_front_lower_bound_m",CAPACITY,"leader_rear_with_gap_m",rear,"free_interval_ahead_of_buffer_m",rear-BUFFER,"full_body_fits_at_buffer",true,"current_native_admission",false,"observed_positions",false));
            // Same downstream occupancy at the corridor entrance separates the
            // additional activity gate from choose()'s interior-entry rule.
            var atStart=f.actor("start-comparison",2.1,PRE,ORIGIN,TAIL,OUT);f.pureQuery(atStart,PRE,true,102);
            check(f.ledger.canEnter(atStart,id(PRE),PRE+".original",102),"Ordinary upstream reception should permit a body behind holders");
            check(!f.ledger.activity(atStart,id(PRE),PRE+".original",102),"Baseline activity empty-slot gate missing");
            check(f.reservation(atStart)==null,"Denied start activity reserved body");
            result("separate-activity-empty-slot-gate",Map.of("ordinary_upstream_receivable",true,"activity_admissible",false,"changes_origin_in_production",false));
        }
    }
    static void freeLaneAndIncompatibleSlot(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var holder=f.seedHolder("one-holder",0);f.readyHolder(holder,0);var v=f.actor("free-lane",2.1,ORIGIN,TAIL,OUT);
            f.waitFor(v,ORIGIN);check(f.admit(ORIGIN,101),"Empty compatible model slot rejected");
            check(f.entries()==1&&f.slot(v)==1&&f.link(ORIGIN).getWaitingList().isEmpty(),"Wrong native entry count or slot");
            near(f.front(v),BUFFER,"Actual addFromWait buffer anchor");
            check(!f.ledger.canEnter(v,id(TAIL),TAIL+".lane.0",102),"Reservation changed to occupied incompatible slot");
            check(f.slot(v)==1&&f.slot(holder)==0,"Rejected lateral change mutated slots");f.safety();
            result("free-compatible-lane-and-frozen-slot",Map.of("native_entries",1,"selected_slot",1,"buffer_front_m",f.front(v),"cross_slot_transfer_rejected",true));
        }
    }
    static void upstreamAndFifo(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var lead=f.actor("upstream-lead",2.1,PRE,ORIGIN,TAIL,OUT);var follow=f.actor("upstream-follow",2.1,PRE,ORIGIN,TAIL,OUT);
            f.seed(lead,PRE,".lane.0",0);f.ready(PRE,".lane.0",100);
            f.seed(follow,PRE,".lane.0",101);f.ready(PRE,".lane.0",110);
            near(f.front(follow),f.front(lead)-2.2,"Native same-slot body spacing");
            check(f.queue(PRE,".lane.0").getFirstVehicle()==lead,"Same-lane native FIFO changed");
            var other=f.actor("other-upstream-slot",2.1,PRE,ORIGIN,TAIL,OUT);f.seed(other,PRE,".lane.1",111);f.ready(PRE,".lane.1",120);
            var activity=f.actor("would-overtake-upstream",2.1,ORIGIN,TAIL,OUT);f.waitFor(activity,ORIGIN);
            check(!f.admit(ORIGIN,121)&&f.reservation(activity)==null,"Interior insertion jumped over an upstream reservation");f.safety();
            result("upstream-reservation-and-per-lane-fifo",Map.of("same_slot_gap_m",f.front(lead)-f.front(follow),"interior_overtake_rejected",true,"other_slot_independent",f.slot(other)!=f.slot(lead)));
        }
        try(var f=new NativeOrigin(s)){
            var head=f.actor("unreceivable-head",1000,ORIGIN,TAIL,OUT);var follower=f.actor("fitting-follower",2.1,ORIGIN,TAIL,OUT);
            f.pureQuery(follower,ORIGIN,true,1);f.waitFor(head,ORIGIN);f.waitFor(follower,ORIGIN);
            check(!f.admit(ORIGIN,1)&&f.link(ORIGIN).getWaitingList().size()==2&&f.link(ORIGIN).getWaitingList().peek()==head,"Wait-list FIFO bypassed rejected head");
            check(f.entries()==0&&f.reservation(follower)==null,"Follower examined/entered despite rejected head");
            result("global-origin-wait-list-fifo",Map.of("waiting",2,"entries",0,"follower_independently_receivable",true));
        }
    }
    static void nativeFlow(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var consuming=f.actor("flow-consumer",8,ORIGIN,TAIL,OUT);consuming.getVehicle().getType().setPcuEquivalents(3.5);
            var next=f.actor("flow-waiter",4.5,ORIGIN,TAIL,OUT);f.waitFor(consuming,ORIGIN);
            check(f.admit(ORIGIN,0),"Positive native flow control failed");
            f.pureQuery(next,ORIGIN,true,0);int count=f.events.size();f.waitFor(next,ORIGIN);
            check(!f.admit(ORIGIN,0)&&f.reservation(next)==null&&f.entries()==1,"Native flow debt bypassed");
            check(f.events.size()==count,"Flow short circuit fabricated a body rejection event");f.safety();
            result("native-flow-before-body-admission",Map.of("first_entries",1,"next_physically_receivable",true,"flow_rejected_without_body_attempt",true));
        }
    }
    static void overlapAtBuffer(Scenario s)throws Exception{
        try(var f=new NativeOrigin(s)){
            var a=f.actor("buffer-holder-0",2.1,ORIGIN,TAIL,OUT);var b=f.actor("buffer-holder-1",2.1,ORIGIN,TAIL,OUT);
            f.waitFor(a,ORIGIN);f.waitFor(b,ORIGIN);check(f.admit(ORIGIN,0)&&f.entries()==2,"Two empty lanes did not admit their initial bodies");
            near(f.front(a),BUFFER,"First native buffer anchor");near(f.front(b),BUFFER,"Second native buffer anchor");
            var third=f.actor("overlapping-third",2.1,ORIGIN,TAIL,OUT);f.waitFor(third,ORIGIN);
            check(BUFFER>f.front(a)-2.2&&BUFFER>f.front(b)-2.2,"Overlap control has a free insertion interval");
            check(!f.admit(ORIGIN,0)&&f.reservation(third)==null&&f.entries()==2,"Activity inserted on an existing body");f.safety();
            result("occupied-buffer-overlap-control",Map.of("free_front_m",BUFFER-2.2,"candidate_front_m",BUFFER,"overlap_rejected",true));
        }
    }
    static void nativeReceptionSignalsAndPriority()throws Exception{
        // Complementary controlled fixtures use existing metric native harness;
        // these synthetic states are not asserted as the historical junction.
        try(var f=new SimZ1StorageFixture(SimZ1StorageFixture.PROFILES.get(0),false)){
            var avenue=f.through("control-avenue",4.5,"avenue","receipt-a");var street=f.through("control-street",4.5,"street","receipt-b");
            f.seed(avenue,".lane.0",0);f.seed(street,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);f.ready(f.queue("street",".lane.0"),100);
            var cfg=new Zona1PriorityConfigGroup();cfg.setClassification("explicit");cfg.setConflicts("conservative");
            var priority=new UnsignalizedPriority.StopAndYield(f.scenario.getNetwork().getNodes().get(Id.createNodeId("j")),cfg,null,null,f.scenario.getConfig().qsim());
            check(!priority.passageMayProceed(f.links.get(id("street")).getLink(),id("short0"),street.vehicle,f.qnet,101),"Executable avenue lost priority");
            var blocker=f.actor("control-receiver",4.5,"receipt-a","dest-a");f.seed(blocker,".original",102);
            check(!f.query(avenue,"short0",103).feasible()&&f.query(street,"short0",103).feasible(),"Native receiver did not distinguish corridors");
            check(priority.passageMayProceed(f.links.get(id("street")).getLink(),id("short0"),street.vehicle,f.qnet,103),"Unreceivable competitor held artificial priority");
            check(!f.cross(avenue,104)&&f.moves==0,"Native blocked receiver was bypassed");
            var q=f.queue("street",".lane.0");q.setSignalized(true);q.setSignalStateAllTurningMoves(org.matsim.core.mobsim.qsim.interfaces.SignalGroupState.RED);
            check(!f.cross(street,105)&&f.moves==0,"Native red signal was bypassed");
            q.setSignalStateAllTurningMoves(org.matsim.core.mobsim.qsim.interfaces.SignalGroupState.GREEN);
            check(f.cross(street,106)&&f.moves==1,"Green, receivable native movement did not recover");f.safety();
            result("controlled-native-reception-signal-priority",Map.of("synthetic_control",true,"blocked_receipt_rejected",true,"red_rejected",true,"green_receivable_moves",1,"viable_priority_preserved",true,
                "priority_scope","Separate production StopAndYield.passageMayProceed calls; cross() tests native receiver/signals, not integrated priority arbitration"));
        }
    }
    public static void main(String[] args)throws Exception{
        try{
            check(args.length==2,"Usage: SimZ1OriginAdmissionFixture <frozen-run-inputs> <new-evidence-json>");
            var inputs=Path.of(args[0]);check(Files.isRegularFile(inputs.resolve("network-inputNetworkFile.xml")),"Explicit frozen inputs required");
            var scenario=SimZ1TerminalTurnCheck.scenario(inputs);
            focal(scenario);freeLaneAndIncompatibleSlot(scenario);upstreamAndFifo(scenario);nativeFlow(scenario);overlapAtBuffer(scenario);nativeReceptionSignalsAndPriority();
            var report=new LinkedHashMap<String,Object>();report.put("kind","native_component_baseline_not_run_approval");report.put("frozen_inputs",inputs.toAbsolutePath().toString());
            report.put("historical_run_id","simz1-d42056291fa2422699a8b6613f795eeb");report.put("seeded_state_not_historical_replay",true);report.put("production_changes",false);report.put("qsim_executed",false);report.put("cases",results);
            var out=Path.of(args[1]);check(!Files.exists(out),"Do not overwrite baseline evidence");Files.createDirectories(out.toAbsolutePath().getParent());new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.toFile(),report);
            System.out.println("PASS SimZ1OriginAdmissionFixture: "+results.size()+" native baseline/control cases; no production mutation, simulation or historical event scan");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
