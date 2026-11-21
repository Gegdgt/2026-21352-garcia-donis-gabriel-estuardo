package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.mobsim.qsim.agents.HasModifiablePlan;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.mobsim.qsim.qnetsimengine.TurnAcceptanceLogic.AcceptTurn;

/** C529-A: only two native queue heads. No Controller or QSim.run. The driver
 * adapter advances its route only on the real notifyMoveOverNode callback. */
public final class SimZ1PassageCycleCheck {
    static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    static Id<Link> id(String s){return Id.createLinkId(s);}
    static Object field(Object o,String name)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String name,Object value)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    static final String A="osm_406654687_6_forward", B="osm_381667651_3_forward",
        CA="osm_405188986_0_backward",CB="osm_405188986_0_forward",
        RA="osm_381667651_4_forward",RB="osm_406654687_7_forward";
    static final class Driver implements InvocationHandler {
        final List<Id<Link>> path;final Leg leg;final String name;int cursor,moves;
        Driver(Scenario s,String name,List<Id<Link>> path){this.name=name;this.path=new ArrayList<>(path);
            leg=s.getPopulation().getFactory().createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(path,s.getNetwork()));}
        public Object invoke(Object p,Method m,Object[] args){return switch(m.getName()){
            case "getCurrentPlanElement"->leg;case "getCurrentLinkId"->path.get(cursor);
            case "getCurrentLinkIndex"->cursor;
            case "chooseNextLinkId"->cursor+1<path.size()?path.get(cursor+1):null;
            case "getId"->Id.createPersonId(name);case "getMode"->"car";
            case "isWantingToArriveOnCurrentLink"->false;
            case "notifyMoveOverNode"->{require(path.get(cursor+1).equals(args[0]),"Unexpected native route advance");cursor++;moves++;yield null;}
            default->throw new AssertionError("Unexpected driver callback "+m);
        };}
    }
    static final class Fixture implements AutoCloseable {
        final Scenario s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final List<Event> events=new ArrayList<>();final MobsimTimer timer=new MobsimTimer(1);
        final Map<Id<Link>,QLinkI> links=new HashMap<>();final Map<Id<Node>,Zona1QNodeImpl> nodes=new HashMap<>();
        final Map<Id<Node>,UnsignalizedPriority.StopAndYield> priorities=new HashMap<>();
        final Map<String,Driver> drivers=new HashMap<>();final SimZ1CorridorOccupancy ledger;final QNetwork qnet;
        final QVehicleImpl a,b;
        Fixture(Path inputs)throws Exception {
            var props=new Properties();try(var r=Files.newBufferedReader(inputs.resolve("fixture.properties"))){props.load(r);}
            var cfg=s.getConfig().qsim();cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);
            new MatsimNetworkReader(s.getNetwork()).readFile(props.getProperty("network"));
            new LanesReader(s).readFile(props.getProperty("lanes"));
            var manager=EventsUtils.createEventsManager();manager.addHandler((BasicEventHandler)events::add);
            var controlled=new HashSet<Id<Node>>();for(var n:props.getProperty("controlled").split(","))if(!n.isBlank())controlled.add(Id.createNodeId(n));
            ledger=new SimZ1CorridorOccupancy(s,controlled,manager);SimZ1CorridorOccupancy.install(cfg,ledger);
            qnet=new QNetwork(s.getNetwork(),null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
            var engine=new QNetsimEngineI.NetsimInternalInterface(){
                public QNetwork getNetsimNetwork(){return qnet;}
                public void arrangeNextAgentState(MobsimAgent agent){throw new AssertionError("No forced move/abort");}
                public void letVehicleArrive(QVehicle vehicle){throw new AssertionError("Fixture stops before arrival");}
            };
            var context=new NetsimEngineContext(manager,7.5,null,null,cfg,timer,null);
            var settings=new Zona1PriorityConfigGroup();settings.setClassification(props.getProperty("classification"));settings.setConflicts(props.getProperty("conflicts"));
            settings.setStopSeconds(Double.parseDouble(props.getProperty("stopSeconds")));settings.setMaxYieldSeconds(Double.parseDouble(props.getProperty("maxYieldSeconds")));
            var safety=new SimZ1RouteSafety(s);var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
            var selected=new HashSet<Id<Link>>();for(var n:List.of("4074069083","579746301")){
                var node=s.getNetwork().getNodes().get(Id.createNodeId(n));selected.addAll(node.getInLinks().keySet());selected.addAll(node.getOutLinks().keySet());}
            // Metadata remains the exact effective network (including full storage
            // domains); only the focal links get queues and manual time steps.
            for(var name:props.getProperty("nativeLinks").split(","))selected.add(id(name));
            var registry=new NetElementActivationRegistry(){void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}int getNumberOfSimulatedNodes(){return nodes.size();}int getNumberOfSimulatedLinks(){return links.size();}};
            for(var lid:selected){var l=s.getNetwork().getLinks().get(lid);
                var node=l.getToNode();if(!nodes.containsKey(node.getId())){
                    var builder=new Zona1QNodeImpl.Builder(engine,context,cfg,new Zona1NativeDiagnostics(s,manager));builder.setAdmissionPolicy(admission,settings);builder.setRouteSafety(safety);
                    if(UnsignalizedPriority.eligible(node,controlled,settings)){
                        var priority=new UnsignalizedPriority.StopAndYield(node,settings,manager,safety,cfg);priorities.put(node.getId(),priority);builder.setTurnAcceptanceLogic(priority);}
                    var qnode=builder.build(node);qnode.setNetElementActivationRegistry(registry);nodes.put(node.getId(),qnode);ledger.registerNode(qnode);
                }
                var qlink=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(l,nodes.get(node.getId()),LanesUtils.createLanes(l,s.getLanes().getLanesToLinkAssignments().get(lid)));
                qlink.setNetElementActivationRegistry(registry);links.put(lid,qlink);
            }
            // All incoming lanes of each queried node are available for actual priority.
            for(var n:List.of("4074069083","579746301"))require(priorities.containsKey(Id.createNodeId(n)),"Historical unsignalized control absent");
            a=actor("z1_106044",props.getProperty("pathA"),2.1,.8,.25,Double.parseDouble(props.getProperty("speedA")));
            b=actor("z1_49500",props.getProperty("pathB"),4.5,1.8,1,Double.parseDouble(props.getProperty("speedB")));
            seed(a,A,Double.parseDouble(props.getProperty("laneEntryA")),Double.parseDouble(props.getProperty("earliestExitA")));
            seed(b,B,Double.parseDouble(props.getProperty("laneEntryB")),Double.parseDouble(props.getProperty("earliestExitB")));
            require(Math.abs(ledger.setback(id(CA))-6.500015294241702)<1e-8,"Backward historical geometry differs");
            require(Math.abs(ledger.setback(id(CB))-5.000047322607996)<1e-8,"Forward historical geometry differs");
        }
        QVehicleImpl actor(String name,String path,double length,double width,double pcu,double speed){
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(length).setWidth(width).setPcuEquivalents(pcu).setMaximumVelocity(speed).setNetworkMode("car");
            var v=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
            var d=new Driver(s,name,Arrays.stream(path.split(",")).map(SimZ1PassageCycleCheck::id).toList());drivers.put(name,d);
            v.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(Driver.class.getClassLoader(),new Class<?>[]{PlanAgent.class,MobsimDriverAgent.class,HasModifiablePlan.class},d));return v;
        }
        QueueWithBuffer queue(String link,String suffix){return (QueueWithBuffer)((QLinkLanesImpl)links.get(id(link))).getQueueLanes().get(Id.create(link+suffix,Lane.class));}
        void seed(QVehicleImpl v,String link,double entry,double exit)throws Exception{
            seed(v,link,0,entry,exit);
        }
        void seed(QVehicleImpl v,String link,int slot,double entry,double exit)throws Exception{
            var q=queue(link,".lane."+slot);boolean empty=q.isNotOfferingVehicle();
            timer.setTime(entry);require(ledger.canEnter(v,id(link),link+".lane."+slot,entry),"Source cannot store body");q.addFromUpstream(v);
            v.setEarliestLinkExitTime(exit);timer.setTime(exit);q.doSimStep();if(empty)require(q.getFirstVehicle()==v,"Historical head missing");
        }
        boolean query(QVehicle v,double now){var d=drivers.get(v.getId().toString());var target=d.path.get(d.cursor+1);timer.setTime(now);return ledger.canEnter(v,target,target+".original",now);}
        void trace(QVehicle v,double now)throws Exception {
            var d=drivers.get(v.getId().toString());var from=s.getNetwork().getLinks().get(d.path.get(d.cursor));var next=d.path.get(d.cursor+1);var connector=s.getNetwork().getLinks().get(next);var receipt=s.getNetwork().getLinks().get(d.path.get(d.cursor+2));
            var lane=queue(from.getId().toString(),".lane.0");var p=priorities.get(from.getToNode().getId());
            var local=p.isAcceptingTurn(from,lane,next,v,qnet,now);
            var physical=SimZ1CorridorOccupancy.receiverFeasibility(s.getConfig().qsim(),v,next,next+".original",qnet,now);
            var node=nodes.get(connector.getToNode().getId());boolean clear=node.passageClear(v,connector,receipt,0,now);
            String reason="original_boolean_only";List<QVehicle> blockers=List.of();
            try{var detail=field(node,"lastPassageCheck");reason=(String)field(detail,"reason");blockers=(List<QVehicle>)field(detail,"blockers");}catch(NoSuchFieldException baseline){}
            boolean enter=query(v,now);
            System.out.println("TRACE vehicle="+v.getId()+" origin="+from.getId()+" lane="+lane.getId()+" next="+next+" node="+node.getNode().getId()+" movement="+connector.getId()+"->"+receipt.getId()+" local="+local+" physical="+physical+" passageClear="+clear+" branch="+reason+" blockers="+blockers.stream().map(x->x.getId()+":"+x.getCurrentLink().getId()+"->"+x.getDriver().chooseNextLinkId()).toList()+" canEnter="+enter+" locks="+field(ledger,"nodeLocks")+" headLastMove="+lane.getLastMovementTimeOfFirstVehicle()+" prepare="+field(ledger,"passageRequestTime")+" requiredStop="+node.passageStopSeconds(connector)+" greenRemaining="+node.passageGreenRemaining(connector,receipt,0,now));
            require(local==TurnAcceptanceLogic.AcceptTurn.GO&&physical.feasible(),"Historical local/physical decision differs");
            require(!clear,"Historical passageClear unexpectedly passed");
            if(!reason.equals("original_boolean_only")){
                require(reason.equals("priority_yield_conflict")&&blockers.size()==1,"Expected exact reciprocal priority branch");
                // This is the last branch of the real fail-fast passageClear;
                // every preceding condition passed, not a second mock control.
                System.out.println("CONDITIONS bodyCrossings=clear admittedThisStep=clear nativeLinks=present nativeReceiver=available selectedLane=present routeLane=allowed signal=green priority=WAIT exclusivelyPriority=true");
                var priority=priorities.get(node.getNode().getId());var method=UnsignalizedPriority.StopAndYield.class.getDeclaredMethod("canCompete",Link.class,QLaneI.class,Id.class,QNetwork.class,double.class);method.setAccessible(true);
                for(var blocker:blockers){var l=blocker.getCurrentLink();var q=links.get(l.getId()).getOfferingQLanes().stream().filter(x->!x.isNotOfferingVehicle()&&x.getFirstVehicle()==blocker).findFirst().orElseThrow();
                    var stop=((Map<?,?>)field(priority,"heads")).get(q);
                    require((boolean)method.invoke(priority,l,q,blocker.getDriver().chooseNextLinkId(),qnet,now),"Identified blocker cannot compete");
                    System.out.println("COMPETITOR vehicle="+blocker.getId()+" lane="+q.getId()+" canCompete=true headTime="+field(stop,"headTime")+" readyTime="+field(stop,"ready")+" physical="+SimZ1CorridorOccupancy.receiverFeasibility(s.getConfig().qsim(),blocker,blocker.getDriver().chooseNextLinkId(),blocker.getDriver().chooseNextLinkId()+".original",qnet,now));}
            }
        }
        boolean move(QVehicle v,double now)throws Exception {
            var d=drivers.get(v.getId().toString());var from=d.path.get(d.cursor);
            var lane=links.get(from).getOfferingQLanes().stream().filter(q->!q.isNotOfferingVehicle()&&q.getFirstVehicle()==v).findFirst().orElseThrow();timer.setTime(now);
            var method=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);method.setAccessible(true);
            return (boolean)method.invoke(nodes.get(s.getNetwork().getLinks().get(from).getToNode().getId()),v,links.get(from),lane,now);
        }
        long passageEvents(String action,QVehicle vehicle){return events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&action.equals(e.getAttributes().get("action"))&&vehicle.getId().toString().equals(e.getAttributes().get("vehicle"))).count();}
        double traverse(QVehicle v,double start)throws Exception {
            var d=drivers.get(v.getId().toString());String connector=d.path.get(d.cursor).toString();double t=start;
            for(;t<start+20&&queue(connector,".lane.0").isNotOfferingVehicle();t++){
                timer.setTime(t);((QLinkLanesImpl)links.get(id(connector))).doSimStep();ledger.advanceTime(t);
                require(passageEvents("RELEASE",v)==0,"Tail released inside connector");
            }
            require(!queue(connector,".lane.0").isNotOfferingVehicle(),"No native connector progress");
            require(move(v,t),"Preauthorized native connector exit rejected");
            require(passageEvents("RELEASE",v)==0,"Tail released on receipt entry");
            String receipt=d.path.get(d.cursor).toString();double earliest=v.getEarliestLinkExitTime();
            timer.setTime(earliest-1);queue(receipt,".original").doSimStep();ledger.advanceTime(earliest-1);
            require(passageEvents("RELEASE",v)==0,"Released before native receiving progress");
            timer.setTime(earliest);queue(receipt,".original").doSimStep();ledger.advanceTime(earliest);
            require(passageEvents("RELEASE",v)==1,"Native body clearance did not release exactly once");
            System.out.println("PROGRESS vehicle="+v.getId()+" receipt="+receipt+" cleared="+earliest+" moves="+d.moves);
            return earliest;
        }
        void repaired(boolean reverse)throws Exception {
            require(!query(a,255)&&!query(b,255),"Stop hold or losing request bypassed");
            boolean first=query(reverse?b:a,256),second=query(reverse?a:b,256);
            require((reverse?!first&&second:first&&!second),"Order changed cycle winner");
            int moves=drivers.values().stream().mapToInt(d->d.moves).sum();int tx=events.size();
            for(int i=0;i<20;i++){require(query(a,256)&&!query(b,256),"Repeated decision drift");}
            require(drivers.values().stream().mapToInt(d->d.moves).sum()==moves&&passageEvents("ACQUIRE",a)==0&&passageEvents("ACQUIRE",b)==0,"Query consumed route/reservation");
            require(events.size()==tx,"Repeated stable WAIT grew events");
            require(move(a,256),"Winner failed real node admission");require(passageEvents("ACQUIRE",a)==1&&!query(b,256),"Double passage reservation");
            require(field(ledger,"nodeLocks").toString().contains("z1_106044"),"Winner did not lock both nodes");
            var locks=(Map<?,?>)field(ledger,"nodeLocks");require(locks.size()==2&&locks.values().stream().allMatch(a.getId()::equals),"Incoherent node ownership");
            var independent=actor("independent",B+","+RA+",osm_381667651_5_forward",4.5,1.8,1,10);
            require(ledger.canEnter(independent,id(B),B+".lane.2",256),"Passage arbitration blocked independent entry at upstream node");
            double clear=traverse(a,257);require(field(ledger,"nodeLocks").toString().equals("{}"),"Locks remained after clearance");
            require(!query(b,clear+1),"Second request skipped its stop");require(query(b,clear+6),"Second request cannot compete after release");
            require(move(b,clear+6),"Second request failed native admission");traverse(b,clear+7);
            require(passageEvents("ACQUIRE",a)==1&&passageEvents("ACQUIRE",b)==1&&passageEvents("RELEASE",a)==1&&passageEvents("RELEASE",b)==1,"Unbalanced reservations");
            for(var event:events)if(event.getEventType().equals("simz1OccupancyReservation")&&event.getAttributes().containsKey("footprintMeters")){
                var attrs=event.getAttributes();require(Math.abs(Double.parseDouble(attrs.get("footprintMeters"))-Double.parseDouble(attrs.get("bodyLengthMeters"))-.1)<1e-8,"Lost 0.10m gap");}
            for(var event:events)if(event.getEventType().equals("simz1OccupancyPassage"))System.out.println("RECEIPT "+new TreeMap<>(event.getAttributes()));
            System.out.println("PASS repaired cycle: deterministic A then B, actual native queues, two acquisitions/releases, stops and body clearance retained");
        }
        void route(QVehicle v,String... path){var d=drivers.get(v.getId().toString());d.path.clear();d.path.addAll(Arrays.stream(path).map(SimZ1PassageCycleCheck::id).toList());d.cursor=0;d.leg.setRoute(RouteUtils.createNetworkRoute(d.path,s.getNetwork()));}
        void window(String connector,int dropping)throws Exception {
            var factory=new org.matsim.contrib.signals.data.signalcontrol.v20.SignalControlDataImpl().getFactory();
            var plan=factory.createSignalPlanData(Id.create("fixture-plan",org.matsim.contrib.signals.model.SignalPlan.class));plan.setStartTime(0.);plan.setEndTime(0.);plan.setCycleTime(300);plan.setOffset(0);
            var group=Id.create("fixture-group",org.matsim.contrib.signals.model.SignalGroup.class);var setting=factory.createSignalGroupSettingsData(group);setting.setOnset(200);setting.setDropping(dropping);plan.addSignalGroupSettings(setting);
            var cls=Class.forName("gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow$Movement");var constructor=cls.getDeclaredConstructors()[0];constructor.setAccessible(true);
            var movement=constructor.newInstance(Set.of(Id.create(connector+".lane.0",Lane.class)),Set.of(),plan,group);
            ((Map)field(field(ledger,"signalWindows"),"movements")).put(id(connector),List.of(movement));
        }
        public void close(){SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());}
    }
    public static void main(String[] args)throws Exception{
        try{
            for(boolean reverse:new boolean[]{false,true})try(var f=new Fixture(Path.of(args[0]))){
                System.out.println("ORDER "+(reverse?"B,A":"A,B"));
                f.trace(reverse?f.b:f.a,251);f.trace(reverse?f.a:f.b,251);
                if(args.length>1&&args[1].equals("before")){
                    require(!f.query(f.a,256)&&!f.query(f.b,256),"Baseline must reproduce both WAIT");
                    System.out.println("BASELINE reciprocal priority veto reproduced; no locks, no physical rejection");
                }else f.repaired(reverse);
            }
            if(args.length==1)adversarial(Path.of(args[0]));
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
    static void adversarial(Path inputs)throws Exception{
        try(var f=new Fixture(inputs)){
            f.query(f.a,251);require(f.query(f.a,256),"Initial selection missing");
            // Real receiving bodies occupy all three metric slots; no timeout/removal.
            for(int slot=0;slot<3;slot++){
                var v=f.actor("receipt-body"+slot,RA+",osm_381667651_5_forward",4.5,1.8,1,10);
                String lane=RA+".original";f.timer.setTime(256);require(f.ledger.canEnter(v,id(RA),lane,256),"Receipt body setup");f.queue(RA,".original").addFromUpstream(v);
            }
            require(!f.query(f.a,256),"Stale winner ignored occupied receipt");require(((Map<?,?>)field(f.ledger,"pendingPassages")).isEmpty(),"Stale staged passage survived rejection");
            f.query(f.b,256);require(f.query(f.b,261),"Physically blocked A still vetoes viable B");
            System.out.println("PASS occupied receipt: real bodies block winner; other feasible request retains progress");
        }
        try(var f=new Fixture(inputs)){
            f.query(f.a,251);require(f.query(f.a,256),"Initial selection missing");
            var signal=f.queue(CA,".lane.0");signal.setSignalized(true);signal.setSignalStateAllTurningMoves(org.matsim.core.mobsim.qsim.interfaces.SignalGroupState.RED);
            require(!f.query(f.a,256),"Red signal ignored");
            signal.setSignalStateAllTurningMoves(org.matsim.core.mobsim.qsim.interfaces.SignalGroupState.GREEN);
            f.window(CA,257);require(!f.query(f.a,256),"Insufficient green window ignored");
            f.window(CA,290);require(f.query(f.a,256),"Valid green window did not recover");
            System.out.println("PASS red and insufficient fixed-plan window reject; valid window revalidated");
        }
        try(var f=new Fixture(inputs)){
            var third=f.actor("third-priority",B+","+RA+",osm_381667651_5_forward",4.5,1.8,1,10);f.seed(third,B,1,244,250);
            require(!f.query(f.a,251)&&!f.query(f.b,251)&&!f.query(f.a,256)&&!f.query(f.b,256),"Ordinary conflicting third was waived");
            require(f.move(third,256),"Applicable third priority lost");
            require(!f.query(f.a,256)&&!f.query(f.a,257),"Actual crossing/body ignored");
            System.out.println("PASS third ordinary priority preserved; executed crossing and uncleared body still block");
        }
        try(var f=new Fixture(inputs)){
            f.query(f.a,251);require(f.query(f.a,256),"Initial selection missing");
            f.route(f.b,B,RA,"osm_381667651_5_forward");
            require(!f.query(f.a,256),"Changed competitor route retained cyclic priority exemption");
            require(f.query(f.b,256),"Ordinary noncyclic movement changed");
            f.route(f.b,B,CB,RB,"osm_406654687_8_forward");
            f.route(f.a,A,RB,"osm_406654687_8_forward");require(f.query(f.a,256),"Changed ordinary route rejected");
            f.route(f.a,A,CA,RA);require(!f.query(f.a,256)&&!f.query(f.a,260)&&f.query(f.a,261),"Route change reused stale stop preparation");
            System.out.println("PASS changed routes revalidated; noncyclic turns unchanged; stop preparation invalidated");
        }
        try(var f=new Fixture(inputs)){
            String upstream="osm_406654687_5_forward";
            var follower=f.actor("new-head",upstream+","+A+","+CA+","+RA,2.1,.8,.25,10);f.seed(follower,upstream,244,250);
            require(f.move(follower,251),"Follower did not enter from its actual upstream domain");
            for(int t=252;t<=265;t++){f.timer.setTime(t);((QLinkLanesImpl)f.links.get(id(A))).doSimStep();}
            f.query(f.a,265);require(f.query(f.a,270),"Initial winner absent");
            require(f.queue(A,".lane.0").getFirstVehicle()==f.a,"Follower overtook actual FIFO head");
            var active=(Map<?,?>)field(f.ledger,"active");var front=active.get(f.a.getId());var rear=active.get(follower.getId());
            require((double)field(front,"frontBound")-(double)field(front,"length")-(double)field(rear,"frontBound")>=.1-1e-8,"Real FIFO gap smaller than 0.10m");
            f.route(f.a,A,RB,"osm_406654687_8_forward");require(f.move(f.a,270),"Native head change failed");
            require(f.queue(A,".lane.0").getFirstVehicle()==follower,"Native FIFO successor absent");
            // Clear the ordinary head's actual body before testing the new cycle.
            double clear=f.a.getEarliestLinkExitTime();f.timer.setTime(clear);f.queue(RB,".original").doSimStep();f.ledger.advanceTime(clear);
            f.query(f.b,clear+1);require(f.query(f.b,clear+6)&&!f.query(follower,clear+6),"New head inherited stale winning age");
            require(f.drivers.get("new-head").moves==1,"Query moved FIFO follower");
            System.out.println("PASS native FIFO and head change: older B wins over new A head; no inherited decision");
        }
    }
}
