package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.*;
import java.lang.reflect.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.qsim.agents.*;
import org.matsim.core.mobsim.qsim.interfaces.*;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Five native links, manually stepped queues. No QSim or Controller is constructed. */
public final class SimZ1RetentionFixture {
    public final Scenario s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
    public final org.matsim.core.api.experimental.events.EventsManager events=EventsUtils.createEventsManager();
    public final MobsimTimer timer=new MobsimTimer(1);
    public final Map<Id<Link>,QLinkI> links=new HashMap<>();
    public final Map<Id<Node>,Zona1QNodeImpl> nodes=new HashMap<>();
    public final QNetwork network;
    public final QVehicleImpl head,blocker;
    public final Person person;
    public final Leg leg;
    public final PersonDriverAgentImpl driver;
    public static Id<Link> id(String v){return Id.createLinkId(v);}
    public static List<Id<Link>> path(String... v){return Arrays.stream(v).map(SimZ1RetentionFixture::id).toList();}
    public QLaneI lane(String link,String lane){return ((QLinkLanesImpl)links.get(id(link))).getQueueLanes().get(Id.create(lane,Lane.class));}
    private void road(String id,String from,String to,double length){
        var n=s.getNetwork();var l=n.getFactory().createLink(id(id),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setFreespeed(10);l.setCapacity(1800);l.setNumberOfLanes(id.equals("s")?2:1);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
    }
    private QVehicleImpl actor(String name,List<Id<Link>> route) {
        var f=s.getPopulation().getFactory();var p=f.createPerson(Id.createPersonId(name));var plan=f.createPlan();p.addPlan(plan);s.getPopulation().addPerson(p);
        var a=f.createActivityFromLinkId("origin",route.get(0));a.setEndTime(0);plan.addActivity(a);var leg=f.createLeg("car");
        var r=RouteUtils.createNetworkRoute(route);r.setVehicleId(Id.createVehicleId(name));leg.setRoute(r);plan.addLeg(leg);
        plan.addActivity(f.createActivityFromLinkId("destination",route.get(route.size()-1)));
        var netsim=(Netsim)Proxy.newProxyInstance(Netsim.class.getClassLoader(),new Class<?>[]{Netsim.class},(o,m,args)->switch(m.getName()) {
            case "getScenario"->s;case "getEventsManager"->events;case "getSimTimer"->timer;case "getNetsimNetwork"->network;
            default->throw new AssertionError("No simulation callback: "+m);
        });
        var driver=new PersonDriverAgentImpl(plan,netsim,TimeInterpretation.create(s.getConfig()));driver.endActivityAndComputeNextState(0);
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(4.5).setPcuEquivalents(1).setMaximumVelocity(10).setNetworkMode("car");
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicleType(type);s.getVehicles().addVehicle(v);
        var q=new QVehicleImpl(v);q.setDriver(driver);driver.setVehicle(q);return q;
    }
    public SimZ1RetentionFixture(boolean restricted)throws Exception {this(restricted,true);}
    public SimZ1RetentionFixture(boolean restricted,boolean priorityControl)throws Exception {this(restricted,priorityControl,(s,e)->{});}
    public SimZ1RetentionFixture(boolean restricted,boolean priorityControl,java.util.function.BiConsumer<Scenario,org.matsim.core.api.experimental.events.EventsManager> setup)throws Exception {
        var cfg=s.getConfig().qsim();cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);
        for(int i=0;i<4;i++)s.getNetwork().addNode(s.getNetwork().getFactory().createNode(Id.createNodeId("n"+i),new Coord(i*30,0)));
        road("s","n0","n1",29.53278);road("bad","n1","n2",6);road("slow","n2","n3",1000);road("good","n1","n3",20);road("end","n3","n0",30);
        var f=s.getLanes().getFactory();
        for(var l:s.getNetwork().getLinks().values()) {
            var a=f.createLanesToLinkAssignment(l.getId());var next=new ArrayList<>(l.getToNode().getOutLinks().keySet());
            if(l.getId().equals(id("s"))) {
                LanesUtils.createAndAddLane(a,f,Id.create("s.lane.0",Lane.class),1800,10,0,1,restricted?path("bad"):path("bad","good"),null);
                LanesUtils.createAndAddLane(a,f,Id.create("s.lane.1",Lane.class),1800,10,1,1,path("bad","good"),null);
                LanesUtils.createAndAddLane(a,f,Id.create("s.original",Lane.class),3600,l.getLength(),0,2,null,List.of(Id.create("s.lane.0",Lane.class),Id.create("s.lane.1",Lane.class)));
            }else LanesUtils.createAndAddLane(a,f,Id.create(l.getId()+".original",Lane.class),1800,l.getLength(),0,1,next,null);
            s.getLanes().addLanesToLinkAssignment(a);
        }
        setup.accept(s,events);
        network=new QNetwork(s.getNetwork(),null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
        var engine=new QNetsimEngineI.NetsimInternalInterface(){
            public QNetwork getNetsimNetwork(){return network;}
            public void arrangeNextAgentState(MobsimAgent agent){throw new AssertionError("No abort/forced movement");}
            public void letVehicleArrive(QVehicle vehicle){throw new AssertionError("Fixture stops before arrival");}
        };
        var context=new NetsimEngineContext(events,7.5,null,null,cfg,timer,null);
        var registry=new NetElementActivationRegistry(){void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}int getNumberOfSimulatedNodes(){return nodes.size();}int getNumberOfSimulatedLinks(){return links.size();}};
        var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(false);
        s.getConfig().addModule(admission);
        var priority=new Zona1PriorityConfigGroup();var safety=new SimZ1RouteSafety(s);
        for(var l:s.getNetwork().getLinks().values()) {
            var node=l.getToNode();
            if(!nodes.containsKey(node.getId())) {
                var diagnostics=new Zona1NativeDiagnostics(s,events);events.addHandler(diagnostics);
                var builder=new Zona1QNodeImpl.Builder(engine,context,cfg,diagnostics);builder.setAdmissionPolicy(admission,priority);builder.setRouteSafety(safety);
                if(priorityControl)builder.setTurnAcceptanceLogic(new UnsignalizedPriority.StopAndYield(node,priority,events,safety,cfg));
                var qnode=builder.build(node);qnode.setNetElementActivationRegistry(registry);nodes.put(node.getId(),qnode);
            }
            var q=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(l,nodes.get(node.getId()),LanesUtils.createLanes(l,s.getLanes().getLanesToLinkAssignments().get(l.getId())));
            q.setNetElementActivationRegistry(registry);links.put(l.getId(),q);
        }
        head=actor("road",path("s","bad","slow","end"));blocker=actor("blocker",path("bad","slow","end"));
        person=s.getPopulation().getPersons().get(Id.createPersonId("road"));leg=(Leg)person.getSelectedPlan().getPlanElements().get(1);driver=(PersonDriverAgentImpl)head.getDriver();
        timer.setTime(0);lane("bad","bad.original").addFromUpstream(blocker);lane("s","s.lane.0").addFromUpstream(head);
        timer.setTime(10);lane("s","s.lane.0").doSimStep();
        if(lane("bad","bad.original").isAcceptingFromUpstream())throw new AssertionError("Receiver fixture is not full");
        if(lane("s","s.lane.0").isNotOfferingVehicle())throw new AssertionError("Source is not offered");
    }
    public void markTraffic(double time){events.processEvent(new VehicleEntersTrafficEvent(time,person.getId(),id("s"),head.getId(),"car",0));}
    public boolean attempt(QVehicle vehicle,String link,String lane,double now)throws Exception {
        timer.setTime(now);var queue=lane(link,lane);if(queue.isNotOfferingVehicle() || queue.getFirstVehicle()!=vehicle)return false;
        var method=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);method.setAccessible(true);
        return (boolean)method.invoke(nodes.get(s.getNetwork().getLinks().get(id(link)).getToNode().getId()),vehicle,links.get(id(link)),lane(link,lane),now);
    }
    public void waitUntil(int start,int end)throws Exception{for(int t=start;t<=end;t++)if(attempt(head,"s","s.lane.0",t))throw new AssertionError("Unexpected movement");}
    public double clearReceiver(double now)throws Exception {
        beginReceiverProgress(now);
        for(int i=0;i<=10;i++) {
            if(attempt(blocker,"bad","bad.original",now+i))return now+i;
        }
        throw new AssertionError("Blocker did not leave through normal admission");
    }
    public void beginReceiverProgress(double now){timer.setTime(now);var lane=lane("bad","bad.original");lane.initBeforeSimStep();lane.doSimStep();}
    public double leaveBadHead(double now)throws Exception {
        for(int i=0;i<=15;i++) {
            beginReceiverProgress(now+i);
            if(attempt(head,"bad","bad.original",now+i))return now+i;
        }
        throw new AssertionError("Head did not complete bad link through normal admission: offered="+!lane("bad","bad.original").isNotOfferingVehicle()+" vehicles="+lane("bad","bad.original").getAllVehicles()+" earliest="+head.getEarliestLinkExitTime()+" now="+timer.getTimeOfDay());
    }
    public void green(boolean value){var lane=(SignalizeableItem)lane("s","s.lane.0");lane.setSignalized(true);lane.setSignalStateAllTurningMoves(value?SignalGroupState.GREEN:SignalGroupState.RED);}
}
