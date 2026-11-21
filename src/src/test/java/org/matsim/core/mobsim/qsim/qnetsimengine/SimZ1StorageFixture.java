package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgent;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Correction 4 component fixtures only. No controller or simulation runner.
 * Composite junctions reproduce reported metric storage, not geographic maps.
 * All native queues assert their geometric PCU capacity: even MATSim's silent
 * max(storage, per-step flow) enlargement fails the fixture.
 */
final class SimZ1StorageFixture implements AutoCloseable {
    record Profile(String name,double[] segments,int lanes,double usable) {
        double length(){return Arrays.stream(segments).sum();}
    }
    static final List<Profile> PROFILES=List.of(
        new Profile("14 Calle",new double[]{6.983588944583202},1,1.981222063995009),
        new Profile("8a Avenida",new double[]{7.9312903543363324},1,4.430171450006364),
        new Profile("10a Calle",new double[]{8.752758533070127},1,2.2527432388284243),
        new Profile("64387808",new double[]{10.036052767279244,5.667256571568172,3.598852169981324},1,12.57386889238471),
        new Profile("9a Calle",new double[]{4.257955303480768,4.933572286831278},2,4.19151301070082));
    static final double STEP=.1, CELL=7.5;
    final Scenario scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
    final List<Event> events=new ArrayList<>();
    final org.matsim.core.api.experimental.events.EventsManager manager=EventsUtils.createEventsManager();
    final MobsimTimer timer;
    final Map<Id<Link>,QLinkI> links=new LinkedHashMap<>();
    final Map<Id<Node>,Zona1QNodeImpl> nodes=new LinkedHashMap<>();
    final QNetwork qnet;
    final SimZ1CorridorOccupancy ledger;
    final Profile profile;
    final boolean splitReceiptRoutes;
    final List<String> connectors=new ArrayList<>();
    final Map<Id<Vehicle>,Actor> actors=new LinkedHashMap<>();
    int moves;

    static void require(boolean condition,String reason){if(!condition)throw new AssertionError(reason);}
    static void near(double actual,double expected,String reason){require(Math.abs(actual-expected)<1e-8,reason+": "+actual+" != "+expected);}
    static Id<Link> id(String value){return Id.createLinkId(value);}
    static Object field(Object object,String name) throws ReflectiveOperationException {
        var f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);
    }
    static void set(Object object,String name,Object value) throws ReflectiveOperationException {
        var f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);
    }
    SimZ1StorageFixture(Profile profile,boolean parallelReceipt) {
        this(profile,parallelReceipt,false);
    }
    SimZ1StorageFixture(Profile profile,boolean parallelReceipt,boolean splitReceiptRoutes) {
        this(profile,parallelReceipt,splitReceiptRoutes,STEP,false);
    }
    SimZ1StorageFixture(Profile profile,boolean parallelReceipt,boolean splitReceiptRoutes,double step,boolean receiptOnly) {
        this(profile,parallelReceipt,splitReceiptRoutes,step,receiptOnly,null);
    }
    /** Explicit integrated policy only; historical constructors retain their
     * original module/default behavior. Select before ledger construction. */
    SimZ1StorageFixture(Profile profile,boolean parallelReceipt,boolean splitReceiptRoutes,double step,boolean receiptOnly,String originPolicy) {
        this.profile=profile;
        this.splitReceiptRoutes=splitReceiptRoutes;
        timer=new MobsimTimer(step);
        var config=scenario.getConfig().qsim();
        config.setUseLanes(true);config.setUsingFastCapacityUpdate(true);config.setRemoveStuckVehicles(false);
        config.setNumberOfThreads(1);config.setNodeOffset(0);config.setTimeStepSize(step);
        config.setTrafficDynamics(QSimConfigGroup.TrafficDynamics.queue);
        config.setFlowCapFactor(1);config.setStorageCapFactor(1);
        if(originPolicy!=null){var selected=ConfigUtils.addOrGetModule(scenario.getConfig(),SimZ1AdmissionConfigGroup.class);selected.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);selected.setWholeVehicleReservation(true);selected.setOriginPolicy(originPolicy);}
        manager.addHandler((BasicEventHandler)events::add);
        double length=profile.length();
        node("west",-100,0);node("south",0,-100);node("j",0,0);
        double at=0;String previous="j";
        for(int i=0;i<profile.segments().length;i++) {
            at+=profile.segments()[i];String end=i+1==profile.segments().length?"b":"split"+i;
            node(end,at,0);String name="short"+i;connectors.add(name);
            road(name,previous,end,profile.segments()[i],profile.lanes());previous=end;
        }
        // Reproduce the reported stopping setback by projecting an incident
        // road's width; retain every real segment length and lane count above.
        double margin=length-profile.usable()-2;
        int crossLanes=(int)Math.floor(margin/1.5);
        double sin=1.5*crossLanes/margin;
        node("cross-end",length+100*Math.sqrt(1-sin*sin),100*sin);
        road("cross","b","cross-end",100,crossLanes);
        double receiptLength=parallelReceipt?57.24485776989736:31.124837111815197;
        int receiptLanes=parallelReceipt?3:1;
        node("a-end",length+receiptLength,0);node("a-dest",length+receiptLength+100,0);
        node("b-end",length,31.124837111815197);node("b-dest",length,131.1248371118152);
        road("avenue","south","j",100,2);road("street","west","j",100,1);
        road("receipt-a","b","a-end",receiptLength,receiptLanes);
        road("receipt-b","b","b-end",31.124837111815197,1);
        road("dest-a","a-end","a-dest",100,receiptLanes);
        if(splitReceiptRoutes)for(int slot=1;slot<3;slot++)road("dest-a"+slot,"a-end","a-dest",100,1);
        road("dest-b","b-end","b-dest",100,1);
        for(String name:List.of("a-end","b-end"))scenario.getNetwork().getNodes().get(Id.createNodeId(name))
            .getAttributes().putAttribute("highway","stop");
        for(var link:scenario.getNetwork().getLinks().values()) {
            link.getAttributes().putAttribute("simz1:priorityRole",link.getId().equals(id("street"))?"street":"avenue");
            if(!link.getToNode().getOutLinks().isEmpty())lanes(link);
        }
        ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);
        near(length-ledger.setback(id(connectors.get(0))),profile.usable(),"Historical lane storage changed: "+profile.name());
        ledger.emitDomains(0);
        qnet=new QNetwork(scenario.getNetwork(),null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}};
        var engine=new QNetsimEngineI.NetsimInternalInterface(){
            public QNetwork getNetsimNetwork(){return qnet;}
            public void arrangeNextAgentState(MobsimAgent agent){throw new AssertionError("Unexpected abort/state transition");}
            public void letVehicleArrive(QVehicle vehicle){throw new AssertionError("No arrival in a discharge fixture");}
        };
        var context=new NetsimEngineContext(manager,CELL,null,null,config,timer,null);
        var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");settings.setConflicts("conservative");
        var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var builder=new Zona1QNodeImpl.Builder(engine,context,config,new Zona1NativeDiagnostics(scenario,manager));
        builder.setAdmissionPolicy(admission,settings);builder.setTurnAcceptanceLogic(new SignalTurnAcceptanceLogic());
        for(var n:scenario.getNetwork().getNodes().values()){var nativeNode=builder.build(n);nodes.put(n.getId(),nativeNode);ledger.registerNode(nativeNode);}
        for(var link:scenario.getNetwork().getLinks().values()) {
            if(receiptOnly&&!link.getId().toString().startsWith("receipt-a")&&!link.getId().toString().startsWith("dest-a"))continue;
            var assignment=scenario.getLanes().getLanesToLinkAssignments().get(link.getId());
            if(assignment==null) {
                var laneBuilder=new QueueWithBuffer.Builder(context);laneBuilder.setLaneId(Id.create(link.getId()+".original",Lane.class));
                var linkBuilder=new QLinkImpl.Builder(context,engine);linkBuilder.setLaneFactory(laneBuilder);
                var sink=linkBuilder.build(link,null);
                sink.setNetElementActivationRegistry(new NetElementActivationRegistry(){
                    void registerNodeAsActive(QNodeI n){} void registerLinkAsActive(QLinkI l){}
                    int getNumberOfSimulatedNodes(){return 0;} int getNumberOfSimulatedLinks(){return links.size();}
                });
                links.put(link.getId(),sink);
                near(sink.getAcceptingQLane().getStorageCapacity(),link.getLength()*link.getNumberOfLanes()/CELL,"Sink capacity enlargement");
                continue;
            }
            var nativeLink=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(link,null,LanesUtils.createLanes(link,assignment));
            nativeLink.setNetElementActivationRegistry(new NetElementActivationRegistry(){
                void registerNodeAsActive(QNodeI n){} void registerLinkAsActive(QLinkI l){}
                int getNumberOfSimulatedNodes(){return 0;} int getNumberOfSimulatedLinks(){return links.size();}
            });
            links.put(link.getId(),nativeLink);
            for(var queue:nativeLink.getQueueLanes().values()) {
                var lane=assignment.getLanes().get(queue.getId());
                double queueLength=lane.getStartsAtMeterFromLinkEnd();
                if(lane.getToLaneIds()!=null)for(var child:lane.getToLaneIds())
                    queueLength=Math.min(queueLength,lane.getStartsAtMeterFromLinkEnd()-assignment.getLanes().get(child).getStartsAtMeterFromLinkEnd());
                near(queue.getStorageCapacity(),queueLength*lane.getNumberOfRepresentedLanes()/CELL,"Automatic native storage enlargement: "+queue.getId());
            }
            require(link.getAttributes().getAttribute("storageCapacityUsedInQsim")==null,"MATSim enlarged storage: "+link.getId());
        }
        SimZ1CorridorOccupancy.install(config,ledger);
    }
    private void node(String name,double x,double y){var n=scenario.getNetwork();n.addNode(n.getFactory().createNode(Id.createNodeId(name),new Coord(x,y)));}
    private void road(String name,String from,String to,double length,int count){
        var n=scenario.getNetwork();var l=n.getFactory().createLink(id(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setNumberOfLanes(count);l.setCapacity(2000*count);
        l.setFreespeed(name.equals("receipt-a")&&count==3||name.startsWith("short")&&profile.name().equals("9a Calle")?11.11111111111111:8.333333333333334);
        l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
    }
    private void lanes(Link link){
        var factory=scenario.getLanes().getFactory();var assignment=factory.createLanesToLinkAssignment(link.getId());
        var original=factory.createLane(Id.create(link.getId()+".original",Lane.class));
        original.setStartsAtMeterFromLinkEnd(link.getLength());original.setNumberOfRepresentedLanes(link.getNumberOfLanes());original.setCapacityVehiclesPerHour(link.getCapacity());
        for(int slot=0;slot<link.getNumberOfLanes();slot++) {
            var lane=factory.createLane(Id.create(link.getId()+".lane."+slot,Lane.class));
            lane.setStartsAtMeterFromLinkEnd(.8*link.getLength());lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(2000);
            for(var out:link.getToNode().getOutLinks().values())if(!splitReceiptRoutes||!link.getId().equals(id("receipt-a"))||
                out.getId().equals(id(slot==0?"dest-a":"dest-a"+slot)))lane.addToLinkId(out.getId());
            assignment.addLane(lane);original.addToLaneId(lane.getId());
        }
        assignment.addLane(original);scenario.getLanes().addLanesToLinkAssignment(assignment);
    }
    final class Actor {
        final QVehicleImpl vehicle;final List<String> path;int index;
        Actor(String name,double body,List<String> path) {
            this.path=List.copyOf(path);
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
            type.setLength(body).setWidth(body==2.1?.8:body==8?2.3:body==13.5?2.5:1.8)
                .setPcuEquivalents(body==2.1?.25:body==8?3.5:body==13.5?3:1).setMaximumVelocity(8.333333333333334).setNetworkMode(body==13.5?"bus":"car");
            vehicle=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
            var leg=scenario.getPopulation().getFactory().createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(path.stream().map(SimZ1StorageFixture::id).toList(),scenario.getNetwork()));
            Class<?> driverType=body==13.5?TransitDriverAgent.class:MobsimDriverAgent.class;
            vehicle.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class<?>[]{PlanAgent.class,driverType},(p,m,a)->switch(m.getName()){
                case "getId"->Id.createPersonId(name);case "getMode"->"car";case "getCurrentPlanElement"->leg;
                case "getCurrentLinkId"->id(path.get(index));case "chooseNextLinkId"->index+1<path.size()?id(path.get(index+1)):null;
                case "isWantingToArriveOnCurrentLink"->false;case "getNextTransitStop"->null;
                case "notifyMoveOverNode"->{require(index+1<path.size()&&id(path.get(index+1)).equals(a[0]),"Unexpected native route advance");index++;moves++;yield null;}
                default->throw new AssertionError("Unexpected driver call: "+m);
            }));
        }
    }
    Actor actor(String name,double body,String... path){var a=new Actor(name,body,List.of(path));actors.put(a.vehicle.getId(),a);return a;}
    Actor through(String name,double body,String source,String receipt){var path=new ArrayList<String>();path.add(source);path.addAll(connectors);path.add(receipt);path.add(receipt.equals("receipt-a")?"dest-a":"dest-b");return actor(name,body,path.toArray(String[]::new));}
    QueueWithBuffer queue(String link,String suffix){var nativeLink=links.get(id(link));return (QueueWithBuffer)(nativeLink instanceof QLinkLanesImpl multi?multi.getQueueLanes().get(Id.create(link+suffix,Lane.class)):nativeLink.getAcceptingQLane());}
    void seed(Actor actor,String suffix,double now){
        timer.setTime(now);String link=actor.path.get(actor.index);var q=queue(link,suffix);
        require(q.isAcceptingFromUpstream()&&ledger.canEnter(actor.vehicle,id(link),q.getId().toString(),now),"Invalid initial native insertion: "+actor.vehicle.getId());q.addFromUpstream(actor.vehicle);
    }
    void ready(QueueWithBuffer q,double now){timer.setTime(now);q.initBeforeSimStep();q.doSimStep();}
    void split(String link,double now) throws Exception {
        timer.setTime(now);var m=QLinkLanesImpl.class.getDeclaredMethod("moveBufferToNextLane",QLaneI.class);m.setAccessible(true);m.invoke(links.get(id(link)),queue(link,".original"));
    }
    boolean cross(Actor a,double now) throws Exception {
        timer.setTime(now);String link=a.path.get(a.index);var source=links.get(id(link));
        QLaneI offered=source.getOfferingQLanes().stream().filter(q->!q.isNotOfferingVehicle()&&q.getFirstVehicle()==a.vehicle).findFirst().orElseThrow();
        var m=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);m.setAccessible(true);
        return (boolean)m.invoke(nodes.get(source.getLink().getToNode().getId()),a.vehicle,source,offered,now);
    }
    SimZ1CorridorOccupancy.PhysicalFeasibility query(Actor a,String target,double now){return SimZ1CorridorOccupancy.receiverFeasibility(scenario.getConfig().qsim(),a.vehicle,id(target),target+".original",qnet,now);}
    Object reservation(Actor a) throws Exception {return ((Map<?,?>)field(ledger,"active")).get(a.vehicle.getId());}
    double front(Actor a) throws Exception {return (double)field(reservation(a),"frontBound");}
    int slot(Actor a) throws Exception {return (int)field(reservation(a),"slot");}
    double used(String link,int slot) throws Exception {var domains=(Map<?,?>)field(ledger,"domains");return ((double[])field(domains.get(id(link)),"used"))[slot];}
    void safety() throws Exception {
        for(var a:actors.values()) {
            long copies=links.values().stream().filter(l->l.getVehicle(a.vehicle.getId())!=null).count();
            require(copies<=1,"Duplicate native vehicle across links");
            var r=reservation(a);if(r==null)continue;
            near((double)field(r,"footprint"),a.vehicle.getVehicle().getType().getLength()+.1,"Lost body/gap");
            var d=field(r,"domain");int slot=(int)field(r,"slot");
            var order=(List<?>)field(d,"reservations");var entries=(NavigableMap<?,?>)order.get(slot);Object leader=null;
            for(var body:entries.values()) {if(leader!=null)require((double)field(body,"frontBound")<=(double)field(leader,"frontBound")-(double)field(leader,"footprint")+1e-8,"Longitudinal overlap/overtake");leader=body;}
        }
        long leave=events.stream().filter(e->e instanceof org.matsim.api.core.v01.events.LinkLeaveEvent).count();
        long enter=events.stream().filter(e->e instanceof org.matsim.api.core.v01.events.LinkEnterEvent).count();
        require(leave==moves&&enter==moves,"Fabricated/missing native link event");
        require(events.stream().noneMatch(e->e instanceof org.matsim.api.core.v01.events.PersonArrivalEvent||e instanceof org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent||e instanceof org.matsim.api.core.v01.events.PersonStuckEvent||"FORCE".equals(e.getAttributes().get("decision"))),"Fabricated arrival/removal/FORCE");
    }
    @Override public void close(){SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());}
}
