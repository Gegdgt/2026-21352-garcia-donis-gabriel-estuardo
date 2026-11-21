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
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.qsim.agents.*;
import org.matsim.core.mobsim.qsim.interfaces.*;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Native body reservations and real plan agent, including a repeated current link. */
public final class SimZ1RetentionInstallationFixture implements AutoCloseable {
    public static final String A="osm_1273145789_0_forward",C="osm_734011349_14_forward",V="osm_1270930401_0_forward",B="osm_1273145790_0_forward";
    public static Id<Link> id(String s){return Id.createLinkId(s);}
    public static List<Id<Link>> path(String... s){return Arrays.stream(s).map(SimZ1RetentionInstallationFixture::id).toList();}
    public final Scenario s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
    public final org.matsim.core.api.experimental.events.EventsManager events=EventsUtils.createEventsManager();
    public final List<Event> log=new ArrayList<>();
    public final MobsimTimer timer=new MobsimTimer(1);
    public final Map<Id<Link>,QLinkI> links=new HashMap<>();
    public final Map<Id<Node>,Zona1QNodeImpl> nodes=new HashMap<>();
    public final Map<Id<Vehicle>,QVehicle> vehicles=new HashMap<>();
    public final QNetwork network;
    public final SimZ1CorridorOccupancy ledger;
    public final QVehicleImpl head,blocker;
    public final Person person;
    public final Leg leg;
    public final PersonDriverAgentImpl driver;
    public final List<Id<Link>> old=path("e0","eC","eI",A,"loop","return",A,"slow","detour",C,V,B,"xE");
    private void road(String name,String from,String to,double length,double speed) {
        var n=s.getNetwork();for(String key:List.of(from,to))if(!n.getNodes().containsKey(Id.createNodeId(key)))n.addNode(n.getFactory().createNode(Id.createNodeId(key),new Coord(n.getNodes().size()*40,0)));
        var l=n.getFactory().createLink(id(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setFreespeed(speed);l.setCapacity(1800);l.setNumberOfLanes(name.equals(A)?2:1);l.setAllowedModes(Set.of("car"));n.addLink(l);
    }
    private QVehicleImpl actor(String name,List<Id<Link>> path) {
        var pf=s.getPopulation().getFactory();var p=pf.createPerson(Id.createPersonId(name));var plan=pf.createPlan();p.addPlan(plan);s.getPopulation().addPerson(p);
        var a=pf.createActivityFromLinkId("origin",path.get(0));a.setEndTime(0);plan.addActivity(a);var leg=pf.createLeg("car");var route=RouteUtils.createNetworkRoute(path);route.setVehicleId(Id.createVehicleId(name));leg.setRoute(route);plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("destination",path.get(path.size()-1)));
        var netsim=(Netsim)Proxy.newProxyInstance(Netsim.class.getClassLoader(),new Class<?>[]{Netsim.class},(o,m,args)->switch(m.getName()) {
            case "getScenario"->s;case "getEventsManager"->events;case "getSimTimer"->timer;case "getNetsimNetwork"->network;default->throw new AssertionError(m);
        });
        var driver=new PersonDriverAgentImpl(plan,netsim,TimeInterpretation.create(s.getConfig()));driver.endActivityAndComputeNextState(0);
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(10).setNetworkMode("car");
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicleType(type);s.getVehicles().addVehicle(v);
        var q=new QVehicleImpl(v);q.setDriver(driver);driver.setVehicle(q);vehicles.put(v.getId(),q);return q;
    }
    public SimZ1RetentionInstallationFixture(boolean reservedOtherSlot)throws Exception {
        var cfg=s.getConfig().qsim();cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);s.getConfig().global().setRandomSeed(20261023);
        road("e0","0","1",30,10);road("eC","1","2",30,10);road("eI","2","a",30,10);
        road(A,"a","j",30,10);road("loop","j","z",30,10);road("return","z","a",30,10);
        road("slow","j","c0",8,10);road("detour","c0","c",1000,10);road("H","j","c",30,10);road(C,"c","j",30,10);
        road(V,"j","v",30,10);road(B,"v","m",30,10);road("xE","m","end",30,10);road("tail","end","0",30,10);
        var lf=s.getLanes().getFactory();
        for(var l:s.getNetwork().getLinks().values()) {
            var assignment=lf.createLanesToLinkAssignment(l.getId());var exits=new ArrayList<>(l.getToNode().getOutLinks().keySet());
            if(l.getId().equals(id(A))) {
                var first=new ArrayList<>(exits);if(reservedOtherSlot)first.remove(id("slow"));
                LanesUtils.createAndAddLane(assignment,lf,Id.create(A+".lane.0",Lane.class),1800,10,0,1,first,null);
                LanesUtils.createAndAddLane(assignment,lf,Id.create(A+".lane.1",Lane.class),1800,10,1,1,reservedOtherSlot?path("slow"):first,null);
                LanesUtils.createAndAddLane(assignment,lf,Id.create(A+".original",Lane.class),3600,30,0,2,null,List.of(Id.create(A+".lane.0",Lane.class),Id.create(A+".lane.1",Lane.class)));
            }else LanesUtils.createAndAddLane(assignment,lf,Id.create(l.getId()+".lane.0",Lane.class),1800,l.getLength(),0,1,exits,null);
            s.getLanes().addLanesToLinkAssignment(assignment);
        }
        events.addHandler((BasicEventHandler)log::add);var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);s.getConfig().addModule(admission);
        ledger=new SimZ1CorridorOccupancy(s,Set.copyOf(s.getNetwork().getNodes().keySet()),events);SimZ1CorridorOccupancy.install(cfg,ledger);
        network=new QNetwork(s.getNetwork(),null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}@Override public QLinkI getNetsimLink(Id<Link> link){return links.get(link);}};
        var engine=new QNetsimEngineI.NetsimInternalInterface(){public QNetwork getNetsimNetwork(){return network;}public void arrangeNextAgentState(MobsimAgent a){throw new AssertionError("No forced movement/abort");}public void letVehicleArrive(QVehicle v){throw new AssertionError("Stops before arrival");}};
        var context=new NetsimEngineContext(events,7.5,null,null,cfg,timer,null);
        var registry=new NetElementActivationRegistry(){void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}int getNumberOfSimulatedNodes(){return nodes.size();}int getNumberOfSimulatedLinks(){return links.size();}};
        var priority=new Zona1PriorityConfigGroup();var safety=new SimZ1RouteSafety(s);
        for(var l:s.getNetwork().getLinks().values()) {
            var node=l.getToNode();if(!nodes.containsKey(node.getId())) {
                var diagnostics=new Zona1NativeDiagnostics(s,events);events.addHandler(diagnostics);
                var b=new Zona1QNodeImpl.Builder(engine,context,cfg,diagnostics);b.setAdmissionPolicy(admission,priority);b.setRouteSafety(safety);b.setTurnAcceptanceLogic(new UnsignalizedPriority.StopAndYield(node,priority,events,safety,cfg));
                var q=b.build(node);q.setNetElementActivationRegistry(registry);nodes.put(node.getId(),q);ledger.registerNode(q);
            }
            var q=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(l,nodes.get(node.getId()),LanesUtils.createLanes(l,s.getLanes().getLanesToLinkAssignments().get(l.getId())));q.setNetElementActivationRegistry(registry);links.put(l.getId(),q);
        }
        head=actor("a-road",old);blocker=actor("blocker",path("slow","detour",C,V,B,"xE"));person=s.getPopulation().getPersons().get(Id.createPersonId("a-road"));driver=(PersonDriverAgentImpl)head.getDriver();leg=WithinDayAgentUtils.getModifiableCurrentLeg(driver);
    }
    /** Initial fixture state, not a simulated traversal or certified arrival.
     * Existing native plan-agent seam advances the supplied occurrence witness;
     * the physical body is seeded only at that current occurrence. */
    public void seedHead(){
        events.processEvent(new VehicleEntersTrafficEvent(0,person.getId(),id("e0"),head.getId(),"car",0));
        for(int i=1;i<=6;i++){if(!driver.chooseNextLinkId().equals(old.get(i)))throw new AssertionError("Initial occurrence witness mismatch");driver.notifyMoveOverNode(old.get(i));events.processEvent(new LinkEnterEvent(i,head.getId(),old.get(i)));}
        timer.setTime(6);seed(head,A);
    }
    public void seedBlocker(){seed(blocker,"slow");}
    private void seed(QVehicle v,String link){var q=links.get(id(link)).getAcceptingQLane();if(!ledger.canEnter(v,id(link),q.getId().toString(),timer.getTimeOfDay()))throw new AssertionError("Cannot seed body");q.addFromUpstream(v);}
    public QLaneI currentLane(){var q=(QLinkLanesImpl)links.get(driver.getCurrentLinkId());return q.getQueueLanes().values().stream().filter(l->l.getVehicle(head.getId())==head).findFirst().orElseThrow();}
    public boolean moveHead(double time)throws Exception {
        timer.setTime(time);var link=links.get(driver.getCurrentLinkId());
        for(var lane:link.getOfferingQLanes())if(!lane.isNotOfferingVehicle() && lane.getFirstVehicle()==head) {
            var m=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);m.setAccessible(true);
            return (boolean)m.invoke(nodes.get(link.getLink().getToNode().getId()),head,link,lane,time);
        }return false;
    }
    public void advanceLink(double now){timer.setTime(now);links.get(driver.getCurrentLinkId()).doSimStep();}
    public double advanceToSecondA(boolean stopInOriginal)throws Exception {
        for(int t=7;t<300;t++) {
            advanceLink(t);
            if(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(driver)==6) {
                if(stopInOriginal) {if(!currentLane().isNotOfferingVehicle())return t;}
                else if(!currentLane().getId().toString().endsWith(".original") && !currentLane().isNotOfferingVehicle())return t;
            }
            if(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(driver)<6)moveHead(t);
        }throw new AssertionError("Native prefix did not reach second A: index="+WithinDayAgentUtils.getCurrentRouteLinkIdIndex(driver)+" lane="+currentLane().getId()+" offered="+!currentLane().isNotOfferingVehicle()+" events="+log.stream().skip(Math.max(0,log.size()-4)).map(Event::getAttributes).toList());
    }
    public String ledgerSnapshot()throws Exception{return SimZ1OpposedReturnRerouteCheck.snapshot(ledger);}
    public void close(){SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());}
}
