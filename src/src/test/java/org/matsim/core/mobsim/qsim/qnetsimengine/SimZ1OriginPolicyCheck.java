package org.matsim.core.mobsim.qsim.qnetsimengine;

import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OriginAdmissionFixture.*;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup;
import org.apache.commons.lang3.tuple.Pair;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.qsim.agents.HasModifiablePlan;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgent;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Versioned origin integration controls. Native component calls only: no
 * controller, QSim, historical census/events or full-scale launch. Synthetic
 * geometry deliberately exposes a route exit inside a longer model corridor.
 */
public final class SimZ1OriginPolicyCheck {
    static final String LEGACY=SimZ1AdmissionConfigGroup.LEGACY_ORIGIN;
    static final String GAP=SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN;
    static final List<Map<String,Object>> rows=new ArrayList<>();
    static void row(String name,Map<String,Object> details){var r=new LinkedHashMap<String,Object>();r.put("case",name);r.put("status","PASS");r.putAll(details);rows.add(r);System.out.println("PASS "+name);}
    static void configure(Scenario s,String policy){
        var q=s.getConfig().qsim();q.setUseLanes(true);q.setUsingFastCapacityUpdate(false);q.setNumberOfThreads(1);q.setTimeStepSize(1);q.setNodeOffset(0);q.setRemoveStuckVehicles(false);
        q.setTrafficDynamics(QSimConfigGroup.TrafficDynamics.queue);q.setLinkDynamics(QSimConfigGroup.LinkDynamics.FIFO);
        var p=ConfigUtils.addOrGetModule(s.getConfig(),SimZ1AdmissionConfigGroup.class);p.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);p.setWholeVehicleReservation(true);p.setOriginPolicy(policy);
    }
    static Throwable cause(Throwable t){while(t instanceof InvocationTargetException&&t.getCause()!=null)t=t.getCause();return t;}
    interface Checked {void run()throws Exception;}
    static void rejects(Checked action,String what)throws Exception{boolean rejected=false;try{action.run();}catch(Exception ex){var c=cause(ex);check(c instanceof IllegalArgumentException||c instanceof IllegalStateException,"Unexpected rejection type for "+what+": "+c);rejected=true;}check(rejected,"Accepted "+what);}
    static String digest(String value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
    static MessageDigest sha(){try{return MessageDigest.getInstance("SHA-256");}catch(Exception ex){throw new IllegalStateException(ex);}}
    static String ledgerState(SimZ1CorridorOccupancy ledger)throws Exception{
        var result=new TreeMap<String,String>();for(String key:List.of("domains","originSlots","laneIndices","exits","queueStarts","queueEnds","active","pending","pendingPassages","nodeLocks","connectorLocks","receiptLocks","nextOrdinal","passageRequestTime","passageRequests","passageDeadlines","waits","waitReasons"))result.put(key,deep(field(ledger,key),new IdentityHashMap<>()));return result.toString();
    }
    static String vehicleState(QVehicle v)throws Exception{
        var d=v.getDriver();var result=new ArrayList<Object>();result.add(v.getId());result.add(v.getEarliestLinkExitTime());result.add(d.getCurrentLinkId());result.add(d.chooseNextLinkId());
        if(d instanceof HasModifiablePlan indexed)result.add(indexed.getCurrentLinkIndex());
        if(d instanceof PlanAgent p&&p.getCurrentPlanElement() instanceof Leg leg){result.add(System.identityHashCode(leg.getRoute()));result.add(leg.getRoute().getRouteDescription());}
        return result.toString();
    }
    static String queueState(QueueWithBuffer q)throws Exception{
        var result=new TreeMap<String,Object>();var travel=new ArrayList<String>();for(var v:(Iterable<?>)field(q,"vehQueue"))travel.add(vehicleState((QVehicle)v));
        var buffer=new ArrayList<String>();for(var item:(Iterable<?>)field(q,"buffer")){var p=(Pair<?,?>)item;buffer.add(vehicleState((QVehicle)p.getKey())+"/"+p.getValue());}
        result.put("travelling",travel);result.put("buffer",buffer);result.put("used_pcu",q.getLoadIndicator());result.put("storage_pcu",q.getStorageCapacity());
        result.put("flow",field(field(q,"flowcap_accumulate"),"value"));result.put("flow_time",field(field(q,"flowcap_accumulate"),"timeStep"));result.put("last_moved",field(q,"bufferLastMovedTime"));return result.toString();
    }
    static String fullState(NativeOrigin f,QVehicle probe)throws Exception{
        var result=new TreeMap<String,Object>();result.put("ledger",ledgerState(f.ledger));result.put("clock",f.timer.getTimeOfDay());result.put("events",f.events.stream().map(e->new TreeMap<>(e.getAttributes()).toString()).toList());result.put("probe",vehicleState(probe));
        for(var link:f.links.values()){var lanes=(QLinkLanesImpl)link;result.put("waiting:"+link.getLink().getId(),lanes.getWaitingList().stream().map(v->v.getId().toString()).toList());for(var q:lanes.getQueueLanes().values())result.put("queue:"+q.getId(),queueState((QueueWithBuffer)q));}return result.toString();
    }
    static void configControls()throws Exception{
        var p=new SimZ1AdmissionConfigGroup();check(LEGACY.equals(p.getOriginPolicy()),"Historical default changed");rejects(()->p.setOriginPolicy("unversioned"),"unknown origin policy");
        for(String bad:List.of("storage","whole","threads","remove","traffic","fifo")){
            var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());configure(s,GAP);var q=s.getConfig().qsim();var a=ConfigUtils.addOrGetModule(s.getConfig(),SimZ1AdmissionConfigGroup.class);
            switch(bad){case "storage"->a.setStoragePolicy(SimZ1AdmissionConfigGroup.NATIVE);case "whole"->a.setWholeVehicleReservation(false);case "threads"->q.setNumberOfThreads(2);case "remove"->q.setRemoveStuckVehicles(true);case "traffic"->q.setTrafficDynamics(QSimConfigGroup.TrafficDynamics.kinematicWaves);case "fifo"->q.setLinkDynamics(QSimConfigGroup.LinkDynamics.PassingQ);default->throw new AssertionError();}
            rejects(()->a.validateOriginPolicy(q),"unsupported "+bad);
        }
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());configure(s,GAP);ConfigUtils.addOrGetModule(s.getConfig(),SimZ1AdmissionConfigGroup.class).validateOriginPolicy(s.getConfig().qsim());
        row("versioned-policy-and-rejected-configurations",Map.of("default",LEGACY,"variant",GAP,"negative_configurations",7));
    }
    /** Two forward subdivisions and a legal represented U-turn at their joint.
     * Forward links share a 148 m storage domain, but an origin->reverse route
     * stops at 50-2=48 m. Lane starts, not ledger internals, set native anchor.
     */
    static final class Small implements AutoCloseable {
        final Scenario scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final List<Event> events=new ArrayList<>();final MobsimTimer timer=new MobsimTimer(1);
        final MessageDigest nativeEventsDigest=sha();final Map<String,Long> nativeEventCounts=new TreeMap<>();
        final Map<Id<Link>,QLinkI> links=new LinkedHashMap<>();final SimZ1CorridorOccupancy ledger;final QLinkLanesImpl link;final QueueWithBuffer original;
        Small(String policy,double anchor,boolean observe){
            configure(scenario,policy);var n=scenario.getNetwork();
            for(var point:List.of(new Object[]{"a",0.},new Object[]{"j",50.},new Object[]{"b",150.})){var node=n.getFactory().createNode(Id.createNodeId((String)point[0]),new Coord((double)point[1],0));n.addNode(node);}
            road("origin","a","j",50);road("tail","j","b",100);road("reverse","j","a",50);
            for(var road:n.getLinks().values()){
                var fac=scenario.getLanes().getFactory();var assignment=fac.createLanesToLinkAssignment(road.getId());var orig=fac.createLane(Id.create(road.getId()+".original",Lane.class));orig.setStartsAtMeterFromLinkEnd(road.getLength());orig.setNumberOfRepresentedLanes(2);
                double terminal=road.getId().toString().equals("origin")?50-anchor:20;
                double perLane=terminal<3?360:2000;road.setCapacity(2*perLane);orig.setCapacityVehiclesPerHour(2*perLane);
                for(int slot=0;slot<2;slot++){var lane=fac.createLane(Id.create(road.getId()+".lane."+slot,Lane.class));lane.setStartsAtMeterFromLinkEnd(terminal);lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(perLane);for(var out:road.getToNode().getOutLinks().values())lane.addToLinkId(out.getId());assignment.addLane(lane);orig.addToLaneId(lane.getId());}assignment.addLane(orig);scenario.getLanes().addLanesToLinkAssignment(assignment);
            }
            var manager=EventsUtils.createEventsManager();manager.addHandler((BasicEventHandler)e->{nativeEventCounts.merge(e.getEventType(),1L,Long::sum);nativeEventsDigest.update((new TreeMap<>(e.getAttributes()).toString()+"\n").getBytes(StandardCharsets.UTF_8));if(observe)events.add(e);});ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);
            near(ledger.offset(id("origin")),0,"Synthetic origin offset");check(ledger.corridorId(id("origin")).equals(ledger.corridorId(id("tail"))),"U-turn control did not retain shared forward domain");
            var net=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}@Override public QLinkI getNetsimLink(Id<Link> key){return links.get(key);}};
            var engine=new QNetsimEngineI.NetsimInternalInterface(){public QNetwork getNetsimNetwork(){return net;}public void arrangeNextAgentState(MobsimAgent a){throw new AssertionError("Unexpected actor removal");}public void letVehicleArrive(QVehicle v){throw new AssertionError("No arrivals in component check");}};
            var context=new NetsimEngineContext(manager,7.5,null,null,scenario.getConfig().qsim(),timer,null);var road=n.getLinks().get(id("origin"));var assignment=scenario.getLanes().getLanesToLinkAssignments().get(road.getId());
            link=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(road,null,LanesUtils.createLanes(road,assignment));
            link.setNetElementActivationRegistry(new NetElementActivationRegistry(){void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}int getNumberOfSimulatedNodes(){return 0;}int getNumberOfSimulatedLinks(){return links.size();}});links.put(road.getId(),link);
            original=(QueueWithBuffer)link.getQueueLanes().get(Id.create("origin.original",Lane.class));near(original.getStorageCapacity(),anchor*2/7.5,"Original storage enlargement");
            for(int slot=0;slot<2;slot++)near(((QueueWithBuffer)link.getQueueLanes().get(Id.create("origin.lane."+slot,Lane.class))).getStorageCapacity(),(50-anchor)/7.5,"Terminal storage enlargement");
            SimZ1CorridorOccupancy.install(scenario.getConfig().qsim(),ledger);
        }
        void road(String name,String from,String to,double length){var n=scenario.getNetwork();var l=n.getFactory().createLink(id(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));l.setLength(length);l.setNumberOfLanes(2);l.setFreespeed(10);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);}
        QVehicleImpl actor(String name,double length,double pcu,boolean transit,boolean terminal,String... path){
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(length).setWidth(length<3?.8:length==8?2.3:2.5).setPcuEquivalents(pcu).setMaximumVelocity(10).setNetworkMode(transit?"bus":"car");var v=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
            var leg=scenario.getPopulation().getFactory().createLeg(transit?"bus":"car");leg.setRoute(RouteUtils.createNetworkRoute(Arrays.stream(path).map(SimZ1OriginAdmissionFixture::id).toList(),scenario.getNetwork()));
            var driverType=transit?TransitDriverAgent.class:MobsimDriverAgent.class;
            v.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class<?>[]{driverType,PlanAgent.class},(p,m,a)->switch(m.getName()){case "getId"->Id.createPersonId(name);case "getMode"->transit?"bus":"car";case "getCurrentPlanElement"->leg;case "getCurrentLinkId"->id(path[0]);case "chooseNextLinkId"->path.length>1?id(path[1]):null;case "isWantingToArriveOnCurrentLink"->terminal;case "getNextTransitStop"->null;default->throw new AssertionError("Unexpected driver call "+m);}));return v;
        }
        QVehicleImpl moto(String name,String next){return actor(name,2.1,.25,false,false,"origin",next);}
        SimZ1CorridorOccupancy.OriginOffer offer(QVehicle v){return ledger.originOffer(v,id("origin"),"origin.original",timer.getTimeOfDay());}
        boolean admit(QVehicle v)throws Exception{link.getWaitingList().add(v);return attempt();}
        boolean attempt()throws Exception{return (boolean)call(link,"moveWaitToRoad",new Class<?>[]{double.class},timer.getTimeOfDay());}
        Object reservation(QVehicle v)throws Exception{return ((Map<?,?>)field(ledger,"active")).get(v.getId());}
        String stableState()throws Exception{var out=new TreeMap<String,Object>();out.put("ledger",ledgerState(ledger));out.put("waiting",link.getWaitingList().stream().map(v->v.getId().toString()).toList());for(var q:link.getQueueLanes().values())out.put(q.getId().toString(),queueState((QueueWithBuffer)q));out.put("clock",timer.getTimeOfDay());out.put("event_counts",new TreeMap<>(nativeEventCounts));out.put("event_digest",eventDigest());out.put("collected_events",events.size());return out.toString();}
        String eventDigest()throws CloneNotSupportedException{return HexFormat.of().formatHex(((MessageDigest)nativeEventsDigest.clone()).digest());}
        @Override public void close(){SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());}
    }
    static void reachBoundaries()throws Exception{
        for(double anchor:new double[]{47.5,48,48.5})try(var f=new Small(GAP,anchor,true)){
            var v=f.moto("reach-"+anchor,"reverse");var before=f.stableState()+vehicleState(v);var offer=f.offer(v);check(before.equals(f.stableState()+vehicleState(v)),"Boundary query mutated native state or route");
            check(offer.applicable()&&offer.feasible()==(anchor<=48),"Anchor/reach boundary wrong: "+offer);near(offer.insertionFront(),anchor,"Native lane anchor changed");
            if(anchor>48)check(offer.reason().equals("origin_anchor_beyond_route_reach"),"Beyond-reach cause masked");
            check(f.admit(v)==(anchor<=48),"Native commit disagrees with route reach");
            if(anchor<=48){near((double)field(f.reservation(v),"frontBound"),anchor,"Admitted body moved anchor");check((double)field(f.reservation(v),"admissionClearFront")>=anchor-1e-8,"Reservation forgot anchor");}
            else check(f.reservation(v)==null&&f.events.stream().noneMatch(e->e instanceof VehicleEntersTrafficEvent),"Beyond-reach actor entered traffic");
        }
        // The origin->tail route reaches 148 m; replacing it by the represented
        // interior U-turn reaches only 48 m, although body clearance alone fits.
        try(var f=new Small(GAP,48.5,true)){var v=f.moto("reroute-anchor","tail");check(f.admit(v),"Through-route anchor should fit");
            String bad=SimZ1CorridorOccupancy.replacementIssue(f.scenario.getConfig().qsim(),v.getId(),List.of(id("origin"),id("reverse")),0);
            check("occupancy_reserved_receipt_clearance".equals(bad),"Reroute discarded occupied anchor: "+bad);
            check(SimZ1CorridorOccupancy.replacementIssue(f.scenario.getConfig().qsim(),v.getId(),List.of(id("origin"),id("tail")),0)==null,"Unchanged sufficient route rejected");
            check((double)field(f.reservation(v),"admissionClearFront")>=48.5-1e-8,"addFromWait TRANSFER lost anchor bound");}
        row("native-anchor-before-equal-after-route-setback",Map.of("route_reach_m",48,"anchors_m",List.of(47.5,48.,48.5),"unchanged_point",true,"reroute_must_cover_admitted_anchor",true));
    }
    static void pureAndCommit(Scenario scenario)throws Exception{
        configure(scenario,GAP);try(var f=new NativeOrigin(scenario)){
            SimZ1OriginMechanismsCheck.pairHolders(f);var v=SimZ1OriginMechanismsCheck.motor(f,"full-state-query",ORIGIN,TAIL,OUT);f.waitFor(v,ORIGIN);var before=fullState(f,v);
            for(int i=0;i<5;i++){var a=f.ledger.originOffer(v,id(ORIGIN),ORIGIN+".original",101);check(a.applicable()&&a.feasible(),"Positive pure offer failed");}
            check(before.equals(fullState(f,v)),"Offer changed native queues/flow/route/clock/events/ledger");check(f.admit(ORIGIN,101),"Rechecked valid native head did not enter");
            check(f.entries()==1,"More than one TrafficEntry");long enter=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyReservation")&&"ENTER".equals(e.getAttributes().get("action"))&&v.getId().toString().equals(e.getAttributes().get("vehicle"))).count();check(enter==1,"Double occupancy ENTER");
            long copies=f.links.values().stream().flatMap(l->((QLinkLanesImpl)l).getQueueLanes().values().stream()).flatMap(q->q.getAllVehicles().stream()).filter(a->a.getId().equals(v.getId())).count();check(copies==1,"Vehicle duplicated in native queues");
            near(f.front(v),BUFFER,"Original buffer anchor changed");near((double)field(f.reservation(v),"admissionClearFront"),BUFFER,"Admitted anchor not retained");
            double used=f.queue(ORIGIN,".original").getLoadIndicator();f.timer.setTime(102);call(f.link(ORIGIN),"moveBufferToNextLane",new Class<?>[]{QLaneI.class},f.queue(ORIGIN,".original"));
            check(f.queue(ORIGIN,".original").getAllVehicles().stream().noneMatch(a->a.getId().equals(v.getId())),"Admitted activity did not leave original buffer");
            check(f.link(ORIGIN).getQueueLanes().values().stream().filter(q->!q.getId().toString().endsWith(".original")).flatMap(q->q.getAllVehicles().stream()).anyMatch(a->a.getId().equals(v.getId())),"No native terminal receiver after buffer discharge");near(f.queue(ORIGIN,".original").getLoadIndicator(),used,"Buffer discharge changed travelling storage");
            check(f.entries()==1,"Internal transfer fabricated traffic entry");f.safety();
        }
        row("pure-full-native-state-and-single-commit-discharge",Map.of("pure_queries",5,"occupancy_enter",1,"traffic_entry",1,"native_internal_transfer",true,"queue_and_flow_snapshot",true));
    }
    @SuppressWarnings("unchecked") static void stage(SimZ1CorridorOccupancy l,QVehicle v)throws Exception{
        var pc=Class.forName(SimZ1CorridorOccupancy.class.getName()+"$Pending").getDeclaredConstructor(Id.class,String.class,int.class);pc.setAccessible(true);
        ((Map<Object,Object>)field(l,"pending")).put(v.getId(),pc.newInstance(id("origin"),"origin.original",0));
        var pass=Class.forName(SimZ1CorridorOccupancy.class.getName()+"$Passage").getDeclaredConstructor(List.class,Map.class,Link.class,double.class,Id.class);pass.setAccessible(true);
        ((Map<Object,Object>)field(l,"pendingPassages")).put(v.getId(),pass.newInstance(List.of(),Map.of(),null,0.,id("origin")));
    }
    static void noStaging(SimZ1CorridorOccupancy l,QVehicle v)throws Exception{for(String key:List.of("pending","pendingPassages","active"))check(!((Map<?,?>)field(l,key)).containsKey(v.getId()),"Failed commit retained "+key);}
    @SuppressWarnings("unchecked") static void invalidAndMetadata(Scenario scenario)throws Exception{
        for(String bad:List.of("body","cursor"))try(var f=new Small(GAP,20,true)){
            var v=f.moto("invalid-"+bad,"tail");stage(f.ledger,v);
            if(bad.equals("body"))v.getVehicle().getType().setLength(Double.NaN);
            else{var original=v.getDriver();v.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class<?>[]{MobsimDriverAgent.class,PlanAgent.class,HasModifiablePlan.class},(p,m,a)->switch(m.getName()){case "getCurrentLinkIndex"->-1;case "getCurrentPlanElement"->((PlanAgent)original).getCurrentPlanElement();case "getCurrentLinkId"->original.getCurrentLinkId();case "getMode"->original.getMode();case "isWantingToArriveOnCurrentLink"->false;case "getId"->original.getId();default->throw new AssertionError("Unexpected invalid-cursor call "+m);}));}
            var flow=field(field(f.original,"flowcap_accumulate"),"value");rejects(()->f.ledger.activityFromWait(v,id("origin"),"origin.original",0),"invalid "+bad);noStaging(f.ledger,v);check(flow.equals(field(field(f.original,"flowcap_accumulate"),"value")),"Invalid commit consumed native flow");check(f.events.stream().noneMatch(e->e instanceof VehicleEntersTrafficEvent),"Invalid commit entered traffic");
        }
        for(String geometry:List.of("offset","endpoint"))try(var f=new Small(GAP,20,true)){
            var v=f.moto("nan-"+geometry,"tail");if(geometry.equals("offset")){var domain=((Map<?,?>)field(f.ledger,"domains")).get(id("origin"));((Map<Id<Link>,Double>)field(domain,"offsets")).put(id("origin"),Double.NaN);}else ((Map<Id<Link>,Map<String,Double>>)field(f.ledger,"queueEnds")).get(id("origin")).put("origin.original",Double.NaN);
            var before=f.stableState();var o=f.offer(v);check(o.applicable()&&!o.feasible()&&o.reason().equals("origin_nonfinite_geometry"),"NaN geometry granted or silently fell back: "+o);check(before.equals(f.stableState()),"NaN query mutated state");check(!f.admit(v),"NaN commit admitted body");noStaging(f.ledger,v);
        }
        for(String partial:List.of("indices","exits")){configure(scenario,GAP);try(var f=new NativeOrigin(scenario)){
            SimZ1OriginMechanismsCheck.pairHolders(f);var v=SimZ1OriginMechanismsCheck.motor(f,"partial-"+partial,ORIGIN,TAIL,OUT);
            if(partial.equals("indices"))((Map<String,Integer>)((Map<?,?>)field(f.ledger,"laneIndices")).get(id(TAIL))).remove(TAIL+".lane.1");
            else ((Map<Integer,Set<Id<Link>>>)((Map<?,?>)field(f.ledger,"exits")).get(id(TAIL))).remove(1);
            var o=f.ledger.originOffer(v,id(ORIGIN),ORIGIN+".original",101);check(!o.applicable()&&o.reason().equals("legacy_unrepresented_movement"),"Partial lane metadata granted new policy");f.waitFor(v,ORIGIN);check(!f.admit(ORIGIN,101)&&f.reservation(v)==null,"Incomplete metadata enabled occupied-slot entry");f.safety();
        }}
        row("invalid-staging-and-incomplete-geometry-metadata",Map.of("invalid_commit_cleanup",List.of("body","cursor"),"nonfinite_negative_injection",List.of("offset","endpoint"),"metadata_fallback",List.of("indices","exits"),"injections_are_synthetic",true));
    }
    static void originalConnections(Scenario scenario)throws Exception{
        for(String constrained:List.of(ORIGIN,TAIL)){
            var assignment=scenario.getLanes().getLanesToLinkAssignments().get(id(constrained));var original=assignment.getLanes().get(Id.create(constrained+".original",Lane.class));var previous=new ArrayList<>(original.getToLaneIds());
            try{original.getToLaneIds().remove(Id.create(constrained+".lane.1",Lane.class));check(original.getToLaneIds().equals(List.of(Id.create(constrained+".lane.0",Lane.class))),"Topology negative setup did not select only slot 0");
                for(boolean legalFree:List.of(false,true)){configure(scenario,GAP);try(var f=new NativeOrigin(scenario)){
                    // MATSim materializes only lanes reachable from original.
                    // The disconnected terminal is deliberately absent, so use
                    // an existing upstream queue to block a slot. In the
                    // negative, slot 1 is completely empty yet unreachable.
                    check(f.queue(constrained,".lane.1")==null,"Disconnected terminal was unexpectedly materialized");
                    int blocked=legalFree?1:0;var upstream=SimZ1OriginMechanismsCheck.motor(f,"topology-upstream",PRE,ORIGIN,TAIL,OUT);f.seed(upstream,PRE,".lane."+blocked,0);f.ready(PRE,".lane."+blocked,100);
                    var v=SimZ1OriginMechanismsCheck.motor(f,"topology-entrant",ORIGIN,TAIL,OUT);var offer=f.ledger.originOffer(v,id(ORIGIN),ORIGIN+".original",101);check(offer.applicable()&&offer.feasible()==legalFree,"Original queue connectivity ignored at "+constrained+": "+offer);if(legalFree)check(offer.slot()==0,"Selected terminal unreachable from original queue");
                    f.waitFor(v,ORIGIN);check(f.admit(ORIGIN,101)==legalFree,"Topology commit disagreed with physical offer");if(legalFree)check(f.slot(v)==0,"Commit switched to unreachable slot");else check(f.reservation(v)==null&&f.entries()==0,"Unreachable free slot admitted actor");f.safety();
                }}
            }finally{original.getToLaneIds().clear();original.getToLaneIds().addAll(previous);}
        }
        var original=scenario.getLanes().getLanesToLinkAssignments().get(id(ORIGIN)).getLanes().get(Id.create(ORIGIN+".original",Lane.class));double represented=original.getNumberOfRepresentedLanes();
        try{original.setNumberOfRepresentedLanes(1);configure(scenario,GAP);try(var f=new NativeOrigin(scenario)){
            SimZ1OriginMechanismsCheck.pairHolders(f);var v=SimZ1OriginMechanismsCheck.motor(f,"one-original-two-terminal-slots",ORIGIN,TAIL,OUT);var offer=f.ledger.originOffer(v,id(ORIGIN),ORIGIN+".original",101);
            check(!offer.applicable()&&offer.reason().equals("legacy_unrepresented_movement"),"One shared original lane was treated as two independent bodies");f.waitFor(v,ORIGIN);check(!f.admit(ORIGIN,101)&&f.reservation(v)==null,"Narrow original enabled occupied-slot extension");f.safety();
        }}finally{original.setNumberOfRepresentedLanes(represented);}
        row("original-to-terminal-connectivity-through-route-prefix",Map.of("restricted_links",List.of(ORIGIN,TAIL),"positive_and_negative_each",true,"unreachable_terminal_not_independent",true,"original_one_lane_two_terminal_slots_rejected",true));
    }
    static void dimensionsAndFallback()throws Exception{
        for(double width:new double[]{0,Double.NaN,Double.POSITIVE_INFINITY,3,3.0001})try(var f=new Small(GAP,20,true)){
            var v=f.moto("width-"+width,"tail");v.getVehicle().getType().setWidth(width);var before=f.stableState()+vehicleState(v);check(f.offer(v).feasible()==(width==3),"Width boundary bypassed");check(before.equals(f.stableState()+vehicleState(v)),"Width query mutated");check(f.admit(v)==(width==3),"Width commit disagreed");}
        for(double pcu:new double[]{0,Double.NaN,Double.POSITIVE_INFINITY})try(var f=new Small(GAP,20,true)){var v=f.moto("pcu-"+pcu,"tail");v.getVehicle().getType().setPcuEquivalents(pcu);var before=f.stableState();var offer=f.offer(v);check(offer.applicable()&&!offer.feasible()&&offer.reason().equals("origin_invalid_pcu"),"Invalid PCU granted");check(before.equals(f.stableState()),"Invalid PCU query mutated");check(!f.admit(v),"Invalid PCU committed");noStaging(f.ledger,v);}
        for(double[] profile:new double[][]{{8,3.5},{13.5,3},{12,2.5}})try(var f=new Small(GAP,20,true)){
            boolean transit=profile[0]!=8;var v=f.actor("profile-"+profile[0],profile[0],profile[1],transit,false,"origin","tail");var offer=f.offer(v);check(offer.applicable()!=transit,"Transit eligibility changed");
            if(transit)check(offer.reason().equals("legacy_metric_transit_or_terminal_activity"),"Transit did not retain original path");
            check(f.admit(v),"Real profile cannot use empty legacy/native buffer");near((double)field(f.reservation(v),"footprint"),profile[0]+.1,"Full profile body lost");
            long entries=f.events.stream().filter(e->e instanceof VehicleEntersTrafficEvent).count();check(entries==1,"Profile entry count changed");
        }
        try(var f=new Small(GAP,20,true)){var v=f.actor("terminal-fallback",2.1,.25,false,true,"origin","tail");check(!f.offer(v).applicable(),"Current-link arrival was treated as generic origin");}
        row("nominal-width-profiles-and-service-fallback",Map.of("width_model_m",3,"negative_widths",4,"negative_pcu",3,"profiles_body_pcu",List.of(List.of(8.,3.5),List.of(13.5,3.),List.of(12.,2.5)),"scheduled_service_semantics","Covered separately by existing transit/freight/L18 fixtures; these are native profile controls"));
    }
    static String movementState(Small f)throws Exception{
        var active=(Map<?,?>)field(f.ledger,"active");var result=new TreeMap<String,Object>();for(var e:active.entrySet()){var r=e.getValue();result.put(e.getKey().toString(),List.of(field(r,"slot"),field(r,"ordinal"),field(r,"frontBound"),field(r,"footprint")));}result.put("waiting",f.link.getWaitingList().stream().map(v->v.getId().toString()).toList());
        for(var q:f.link.getQueueLanes().values())result.put("queue:"+q.getId(),q.getAllVehicles().stream().map(v->v.getId().toString()).toList());result.put("flow",field(field(f.original,"flowcap_accumulate"),"value"));return result.toString();
    }
    static Map<String,Object> boundedWork(String policy,boolean observe,int warm,int measured)throws Exception{
        try(var f=new Small(policy,20,observe)){
            check(f.admit(f.moto("owner-0","tail")),"First benchmark body not admitted");check(f.admit(f.moto("owner-1","tail")),"Second benchmark body not admitted");var waiting=f.moto("blocked-head","tail");f.link.getWaitingList().add(waiting);check(!f.attempt(),"Benchmark head should overlap occupied anchor");
            for(int i=0;i<warm;i++)check(!f.attempt(),"Warmup changed blocked movement");var state=movementState(f);var eventsBefore=f.events.size();var nativeBefore=new TreeMap<>(f.nativeEventCounts);
            var bean=ManagementFactory.getThreadMXBean();boolean cpu=bean.isCurrentThreadCpuTimeSupported();if(cpu&&!bean.isThreadCpuTimeEnabled())bean.setThreadCpuTimeEnabled(true);
            com.sun.management.ThreadMXBean alloc=bean instanceof com.sun.management.ThreadMXBean a&&a.isThreadAllocatedMemorySupported()?a:null;if(alloc!=null&&!alloc.isThreadAllocatedMemoryEnabled())alloc.setThreadAllocatedMemoryEnabled(true);
            long thread=Thread.currentThread().getId(),heapBefore=ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed();
            long bytesBefore=alloc==null?0:alloc.getThreadAllocatedBytes(thread),cpuBefore=cpu?bean.getCurrentThreadCpuTime():0,wallBefore=System.nanoTime();
            int moves=0;for(int i=0;i<measured;i++)if(f.attempt())moves++;
            long wall=System.nanoTime()-wallBefore,cpuNs=cpu?bean.getCurrentThreadCpuTime()-cpuBefore:0,bytes=alloc==null?0:alloc.getThreadAllocatedBytes(thread)-bytesBefore;
            long heapAfter=ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed();check(moves==0&&state.equals(movementState(f)),"Measured workload changed native state");check(eventsBefore==f.events.size()&&nativeBefore.equals(f.nativeEventCounts),"Stable repeated rejection emitted unbounded diagnostics");
            var r=new LinkedHashMap<String,Object>();r.put("policy",policy);r.put("observer_collector_enabled",observe);r.put("warmup_attempts",warm);r.put("measured_attempts",measured);r.put("native_movements_during_measurement",moves);r.put("initial_native_entries",2);r.put("owner_count",2);r.put("slot_count",2);r.put("wall_ns",wall);r.put("current_thread_cpu_ns",cpu?cpuNs:null);r.put("current_thread_allocated_bytes",alloc==null?null:bytes);r.put("heap_used_before_bytes",heapBefore);r.put("heap_used_after_bytes",heapAfter);var peaks=new TreeMap<String,Object>();for(var pool:ManagementFactory.getMemoryPoolMXBeans()){var peak=pool.getPeakUsage();if(peak!=null)peaks.put(pool.getName(),Map.of("used_bytes",peak.getUsed(),"committed_bytes",peak.getCommitted(),"type",pool.getType().toString()));}r.put("jvm_memory_pool_peaks_since_process_start_or_external_reset",peaks);r.put("rss_bytes",null);r.put("movement_digest",digest(state));r.put("collected_events",f.events.size());r.put("native_event_counts",new TreeMap<>(f.nativeEventCounts));r.put("measured_events",f.events.size()-eventsBefore);r.put("event_digest",f.eventDigest());r.put("scope","Warmed repeated native moveWaitToRoad of one head blocked by two bodies; reflection/loop included equally, startup and warmup excluded. No full-QSim/throughput claim. Observer comparison toggles collection only; constant streaming count/hash checks native events even without retaining them. Anchor protection differs by version and is tested separately; movement digest excludes that policy-specific future-route constraint.");return r;
        }
    }
    static List<Map<String,Object>> benchmark(int iterations)throws Exception{
        var values=new ArrayList<Map<String,Object>>();for(String policy:List.of(LEGACY,GAP))for(boolean observer:List.of(false,true))for(int repeat=0;repeat<2;repeat++){var value=boundedWork(policy,observer,Math.min(iterations,1000),iterations);value.put("repeat",repeat);values.add(value);}
        String movement=(String)values.get(0).get("movement_digest");for(var value:values)check(movement.equals(value.get("movement_digest")),"Baseline/policy/observer changed equivalent native movement");
        for(String policy:List.of(LEGACY,GAP)){var repeats=values.stream().filter(v->v.get("policy").equals(policy)).toList();for(var repeat:repeats)check(repeats.get(0).get("event_digest").equals(repeat.get("event_digest"))&&repeats.get(0).get("native_event_counts").equals(repeat.get("native_event_counts")),"Repeated/observer native events differ for "+policy);}
        row("bounded-native-cost-and-observer-determinism",Map.of("workloads",values.size(),"iterations_each",iterations,"movement_digest_equal",true,"event_digest_equal_within_policy",true,"full_scale_extrapolation",false));return values;
    }
    public static void main(String[] args)throws Exception{
        try{check(args.length==2||args.length==3,"Usage: <frozen-inputs> <new-report-json> [measured-attempts<=100000]");int iterations=args.length==3?Integer.parseInt(args[2]):10000;check(iterations>0&&iterations<=100000,"Bounded measured attempts required");var out=Path.of(args[1]);check(!Files.exists(out),"Preserve existing evidence");rows.clear();
            configControls();reachBoundaries();var scenario=SimZ1TerminalTurnCheck.scenario(Path.of(args[0]));pureAndCommit(scenario);invalidAndMetadata(scenario);originalConnections(scenario);dimensionsAndFallback();var costs=benchmark(iterations);
            var report=new LinkedHashMap<String,Object>();report.put("kind","versioned_origin_policy_native_component_check");report.put("status","PASS");report.put("cases",rows);report.put("benchmarks",costs);report.put("qsim_executed",false);report.put("historical_events_or_census_read",false);report.put("massive_approval",false);report.put("limitations",List.of("Synthetic boundary geometry is not an observed city junction", "Transit profile checks do not replace scheduled last-stop/dwell/L18 checks", "Serial reservation ownership only; no event-handler exception rollback guarantee", "Benchmark is one bounded blocked-head workload, not network-wide CPU overhead", "Thread allocation is cumulative allocated bytes; heap delta is not retained memory; process RSS must be measured by runner"));Files.createDirectories(out.toAbsolutePath().getParent());new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.toFile(),report);System.out.println("PASS SimZ1OriginPolicyCheck "+rows.size()+" cases");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
