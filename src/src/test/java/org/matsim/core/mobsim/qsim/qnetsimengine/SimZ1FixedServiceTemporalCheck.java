package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.*;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.*;
import org.matsim.contrib.signals.events.SignalGroupStateChangedEvent;
import org.matsim.contrib.signals.model.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.qsim.agents.HasModifiablePlan;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import org.matsim.vehicles.*;

/** Diagnostic only: exact effective metadata, one native body, no other traffic.
 * Establishes a necessary signal obstruction without claiming full state replay. */
public final class SimZ1FixedServiceTemporalCheck {
 static final String S="osm_420120098_2_forward",P="osm_420120098_1_forward",C="osm_420138103_0_forward",R="osm_1056730555_0_forward";
 static Id<Link> id(String s){return Id.createLinkId(s);}
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static Object field(Object o,String n)throws Exception{var f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
 public static void main(String[] args)throws Exception{
  try{run(Path.of(args[0]),args.length>1&&args[1].equals("alternative"),args.length>2?Path.of(args[1]):null,args.length>2?args[2]:null);}finally{org.apache.logging.log4j.LogManager.shutdown();}
 }
 static void run(Path out,boolean alternative,Path variant,String obstruction)throws Exception {
  var json=new ObjectMapper();var input=json.readTree(out.resolve("signal_fixture_input.json").toFile());var run=Path.of(input.path("run").asText());
  var config=ConfigUtils.createConfig(new SignalSystemsConfigGroup());var cfg=config.qsim();cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);
  var sc=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);sc.setUseSignalSystems(true);sc.setUseAmbertimes(true);
  sc.setSignalSystemFile(run.resolve("inputs/signalsystems-signalsystems.xml").toString());sc.setSignalGroupsFile(run.resolve("inputs/signalsystems-signalgroups.xml").toString());sc.setSignalControlFile(run.resolve("inputs/signalsystems-signalcontrol.xml").toString());
  if(variant!=null){check(Set.of("receiver_full","connector_conflict","red").contains(obstruction),"Unknown negative case");sc.setSignalControlFile(variant.toAbsolutePath().toString());}
  var s=ScenarioUtils.createScenario(config);new MatsimNetworkReader(s.getNetwork()).readFile(run.resolve("inputs/transit-weekday/network.xml").toString());new LanesReader(s).readFile(run.resolve("inputs/transit-weekday/lanes.xml").toString());
  var data=new SignalsDataLoader(config).loadSignalsData();data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
  var controlled=new HashSet<Id<Node>>();for(var system:data.getSignalSystemsData().getSignalSystemData().values())for(var signal:system.getSignalData().values())controlled.add(s.getNetwork().getLinks().get(signal.getLinkId()).getToNode().getId());
  var events=EventsUtils.createEventsManager();var log=new ArrayList<Event>();events.addHandler((BasicEventHandler)log::add);var timer=new MobsimTimer(1);
  var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);config.addModule(admission);
  var ledger=new SimZ1CorridorOccupancy(s,controlled,events);SimZ1CorridorOccupancy.install(cfg,ledger);
  var links=new HashMap<Id<Link>,QLinkI>();var nodes=new HashMap<Id<Node>,Zona1QNodeImpl>();
  var qnet=new QNetwork(s.getNetwork(),null){public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}public QLinkI getNetsimLink(Id<Link> key){return links.get(key);}};
  var engine=new QNetsimEngineI.NetsimInternalInterface(){public QNetwork getNetsimNetwork(){return qnet;}public void arrangeNextAgentState(MobsimAgent a){throw new AssertionError("No abort/forced progress");}public void letVehicleArrive(QVehicle v){throw new AssertionError("No arrival");}};
  var context=new NetsimEngineContext(events,7.5,null,null,cfg,timer,null);var settings=new Zona1PriorityConfigGroup();var safety=new SimZ1RouteSafety(s);
  var selected=new HashSet<Id<Link>>();for(String name:List.of(P,S,C,R,"osm_1056730555_1_forward","osm_1056730555_2_forward")){
   var l=s.getNetwork().getLinks().get(id(name));selected.add(l.getId());selected.addAll(l.getToNode().getInLinks().keySet());selected.addAll(l.getToNode().getOutLinks().keySet());
  }
  var registry=new NetElementActivationRegistry(){void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}int getNumberOfSimulatedNodes(){return nodes.size();}int getNumberOfSimulatedLinks(){return links.size();}};
  for(var lid:selected){var l=s.getNetwork().getLinks().get(lid);var node=l.getToNode();
   if(!nodes.containsKey(node.getId())){
    var diagnostics=new Zona1NativeDiagnostics(s,events);events.addHandler(diagnostics);var b=new Zona1QNodeImpl.Builder(engine,context,cfg,diagnostics);b.setAdmissionPolicy(admission,settings);b.setRouteSafety(safety);
    if(UnsignalizedPriority.eligible(node,controlled,settings))b.setTurnAcceptanceLogic(new UnsignalizedPriority.StopAndYield(node,settings,events,safety,cfg));
    else b.setTurnAcceptanceLogic(new SignalTurnAcceptanceLogic());
    var q=b.build(node);q.setNetElementActivationRegistry(registry);nodes.put(node.getId(),q);ledger.registerNode(q);
   }
   var assignment=s.getLanes().getLanesToLinkAssignments().get(lid);
   AbstractQLink q=assignment==null?new QLinkImpl.Builder(context,engine).build(l,nodes.get(node.getId())):
       new QLinkLanesImpl.Builder(context,engine).build(l,nodes.get(node.getId()),LanesUtils.createLanes(l,assignment));
   q.setNetElementActivationRegistry(registry);links.put(lid,q);
  }
  // Actual fixed controllers and native amber logic; only two systems have clocks stepped.
  var systemsManager=new SignalSystemsManagerImpl(data,events);systemsManager.setAmberLogic(new AmberLogicImpl(data.getAmberTimesData()));var systems=new ArrayList<SignalSystemImpl>();
  for(String name:List.of("579787032","333531372")){
   var sid=Id.create(name,SignalSystem.class);var system=new SignalSystemImpl(sid);system.setSignalSystemsManager(systemsManager);systemsManager.addSignalSystem(system);
   for(var gd:data.getSignalGroupsData().getSignalGroupDataBySystemId(sid).values())system.addSignalGroup(new SignalGroupImpl(gd.getId()));
   var control=new Zona1FixedTimeController();control.setSignalSystem(system);for(var plan:data.getSignalControlData().getSignalSystemControllerDataBySystemId().get(sid).getSignalPlanData().values())control.addPlan(new DatabasedSignalPlan(plan));system.setSignalSystemController(control);systems.add(system);
   for(var signal:data.getSignalSystemsData().getSignalSystemData().get(sid).getSignalData().values())if(links.containsKey(signal.getLinkId()))for(var lane:signal.getLaneIds())((SignalizeableItem)((QLinkLanesImpl)links.get(signal.getLinkId())).getQueueLanes().get(lane)).setSignalized(true);
  }
  events.addHandler((BasicEventHandler)e->{if(e instanceof SignalGroupStateChangedEvent change){var gd=data.getSignalGroupsData().getSignalGroupDataBySystemId(change.getSignalSystemId()).get(change.getSignalGroupId());for(var sid:gd.getSignalIds()){var signal=data.getSignalSystemsData().getSignalSystemData().get(change.getSignalSystemId()).getSignalData().get(sid);if(links.containsKey(signal.getLinkId()))for(var lane:signal.getLaneIds())((SignalizeableItem)((QLinkLanesImpl)links.get(signal.getLinkId())).getQueueLanes().get(lane)).setSignalStateAllTurningMoves(change.getNewState());}}});
  for(var system:systems){system.simulationInitialized(1689);system.updateState(1689);}
  var path=new ArrayList<Id<Link>>();var routeInput=alternative?json.readTree(out.resolve("early_route_probe.json").toFile()).path("excludedImpossibleTurn").path("route"):input.path("path");
  for(var v:routeInput)path.add(id(v.asText()));int at=input.path("currentIndex").asInt();check(path.get(at).equals(id(S))&&path.get(at-1).equals(id(P)),"Historical occurrence witness mismatch");
  for(int i=0;i<=at;i++)check(path.get(i).toString().equals(input.path("path").get(i).asText()),"Historical prefix occurrence changed");
  var d=new SimZ1PassageCycleCheck.Driver(s,"z1_32590",path);d.cursor=at-1;var type=VehicleUtils.createVehicleType(Id.create("Normal",VehicleType.class));type.setLength(13.5).setWidth(2.5).setPcuEquivalents(1).setMaximumVelocity(13.88888888888889).setNetworkMode("car");
  var head=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId("z1_32590"),type));head.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(SimZ1FixedServiceTemporalCheck.class.getClassLoader(),new Class<?>[]{PlanAgent.class,MobsimDriverAgent.class,HasModifiablePlan.class},d));
  var previous=((QLinkLanesImpl)links.get(id(P))).getQueueLanes().get(Id.create(P+".lane.0",Lane.class));timer.setTime(1689);check(ledger.canEnter(head,id(P),previous.getId().toString(),1689),"Initial source body cannot fit");previous.addFromUpstream(head);
  var move=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);move.setAccessible(true);
  for(int t=1690;t<1729;t++){timer.setTime(t);for(var system:systems)system.updateState(t);if(d.cursor<at){previous.doSimStep();if(!previous.isNotOfferingVehicle())move.invoke(nodes.get(links.get(id(P)).getLink().getToNode().getId()),head,links.get(id(P)),previous,(double)t);}if(d.cursor==at)((QLinkLanesImpl)links.get(id(S))).doSimStep();}
  check(d.cursor==at,"Native transfer to exact current occurrence failed");var source=(QLinkLanesImpl)links.get(id(S));
  var lane=source.getQueueLanes().get(Id.create(S+".lane.0",Lane.class));check(lane.getFirstVehicle()==head,"Historical offered head absent");
  if(variant!=null&&!obstruction.equals("red")){
   String blocked=obstruction.equals("receiver_full")?R:C;
   var blockerPath=obstruction.equals("receiver_full")?List.of(id(R),id("osm_1056730555_1_forward"),id("osm_1056730555_2_forward")):List.of(id(C),id(R),id("osm_1056730555_1_forward"),id("osm_1056730555_2_forward"));
   var otherDriver=new SimZ1PassageCycleCheck.Driver(s,"obstructing-third",blockerPath);
   var otherType=VehicleUtils.createVehicleType(Id.create("obstruction-fixture",VehicleType.class));
   otherType.setLength(blocked.equals(C)?2.1:13.5).setWidth(blocked.equals(C)?.8:2.5).setPcuEquivalents(blocked.equals(C)?1:2.5).setMaximumVelocity(13.8888888889).setNetworkMode("car");
   var other=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId("obstructing-third"),otherType));
   other.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(SimZ1FixedServiceTemporalCheck.class.getClassLoader(),new Class<?>[]{PlanAgent.class,MobsimDriverAgent.class,HasModifiablePlan.class},otherDriver));
   var entry=links.get(id(blocked)).getAcceptingQLane();timer.setTime(1728);
   check(ledger.canEnter(other,id(blocked),entry.getId().toString(),1728),"Cannot seed legal third body");entry.addFromUpstream(other);
  }
  var window=new Zona1SignalGreenWindow(s);var rows=new ArrayList<String>();rows.add("time,source_native_permission,source_green_remaining,connector_green_remaining,native_receiver_available,receipt_native_available,node_moved,native_reason,ledger_reason");int moved=0,common=0;var reasons=new TreeMap<String,Integer>();
  check(Math.abs(ledger.setback(id(C))-(7.421461596057132-3.9195925625039463))<1e-8,"Effective stopping geometry differs");
  String before=SimZ1OpposedReturnRerouteCheck.snapshot(ledger);
  String replacement=SimZ1CorridorOccupancy.replacementIssue(cfg,head.getId(),path,at,qnet);
  check(before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(ledger)),"Read-only replacement query mutated ledger or wait counters");
  String physicalBefore=SimZ1OpposedReturnRerouteCheck.physicalSnapshot(ledger);
  for(int t=1729;t<1969;t++){
   timer.setTime(t);for(var system:systems)system.updateState(t);
   if(variant!=null&&obstruction.equals("red")&&t!=1760)continue;
   double w0=window.remainingGreenSeconds(id(S),lane.getId(),id(C),t),w1=window.remainingGreenSeconds(id(C),Id.create(C+".lane.0",Lane.class),id(R),t);boolean green=((SignalizeableItem)lane).hasGreenForToLink(id(C));if(green&&w1>0)common++;
   int mark=log.size();boolean ok=(boolean)move.invoke(nodes.get(source.getLink().getToNode().getId()),head,source,lane,(double)t);if(ok)moved++;
   String reason=log.subList(mark,log.size()).stream().filter(e->e.getEventType().equals("simz1NativeDecision")).reduce((a,b)->b).orElseThrow().getAttributes().get("reason");
   String lr=log.subList(mark,log.size()).stream().filter(e->e.getEventType().equals("simz1OccupancyReservation")&&"WAIT".equals(e.getAttributes().get("action"))).reduce((a,b)->b).map(e->e.getAttributes().get("reason")).orElse("deduplicated_or_not_reached");
   reasons.merge(reason,1,Integer::sum);rows.add(t+","+green+","+w0+","+w1+","+links.get(id(C)).getAcceptingQLane().isAcceptingFromUpstream()+","+links.get(id(R)).getAcceptingQLane().isAcceptingFromUpstream()+","+ok+","+reason+","+lr);
   if(alternative){
    check(ok&&d.cursor==at+1&&d.path.get(d.cursor).equals(path.get(at+1)),"Legal alternative first native move failed");
    var proof=new LinkedHashMap<String,Object>();proof.put("scope","First move with preconfigured legal alternative in separate empty-traffic fixture. No reroute installation or full-route feasibility claim.");proof.put("time",t);proof.put("prefixRetainedByOccurrence",true);proof.put("cursorBefore",at);proof.put("cursorAfter",d.cursor);proof.put("nativeNext",path.get(d.cursor).toString());proof.put("replacementIssue",replacement);proof.put("nativeReason",reason);proof.put("events",log.subList(mark,log.size()).stream().map(Event::getAttributes).toList());
    json.writerWithDefaultPrettyPrinter().writeValue(out.resolve("alternative_first_move.json").toFile(),proof);System.out.println("PASS alternative first native move: "+path.get(d.cursor));SimZ1CorridorOccupancy.uninstall(cfg);return;
   }
  }
  Files.write(out.resolve("signal_fixture_cycle.csv"),rows);
  if(variant!=null){
   check(moved==0&&d.cursor==at,"Negative case moved the bus");
   check(obstruction.equals("red")?reasons.containsKey("signal_red"):common>0,"Negative case lacks the intended actual signal state");
   // A real failed native attempt records WAIT diagnostics; the earlier pure
   // query must not. Neither is allowed to change physical ownership/ordinals.
   check(physicalBefore.equals(SimZ1OpposedReturnRerouteCheck.physicalSnapshot(ledger)),"Failed admission changed physical reservations");
   check(field(ledger,"nodeLocks").toString().equals("{}"),"Failed admission acquired body locks");
   json.writerWithDefaultPrettyPrinter().writeValue(out.resolve("negative-result.json").toFile(),Map.of("case",obstruction,"native_moves",moved,"joint_permission_ticks",common,"native_reasons",reasons,"reservations_unchanged",true));
   SimZ1CorridorOccupancy.uninstall(cfg);System.out.println("PASS native L18 negative "+obstruction);return;
  }
  check(moved==0&&common==0,"Expected no feasible simultaneous permission");check(field(ledger,"nodeLocks").toString().equals("{}"),"No lock owner should be needed for this counterexample");
  var result=new LinkedHashMap<String,Object>();result.put("metadata","exact 5906 effective inputs and L18 route; native 13.5m actor; no other traffic");result.put("scope","necessary control obstruction, not full historical queue replay or a simulation");result.put("source",S);result.put("connector",C);result.put("receipt",R);result.put("currentIndex",at);result.put("replacementIssue",replacement);result.put("simultaneousPermissiveTicks",common);result.put("nativeMoves",moved);result.put("nativeReasons",reasons);result.put("locks",field(ledger,"nodeLocks").toString());result.put("bodyMeters",13.5);result.put("footprintMeters",13.6);result.put("connectorStoppingMeters",3.9195925625039463);result.put("ledgerBefore",before);result.put("ledgerAfter",SimZ1OpposedReturnRerouteCheck.snapshot(ledger));result.put("controllerStarted",false);result.put("qsimRun",false);
  result.put("initialNativeMovements",log.stream().filter(e->e.getTime()<1729&&Set.of("entered link","entered lane").contains(e.getEventType())).map(Event::getAttributes).toList());
  json.writerWithDefaultPrettyPrinter().writeValue(out.resolve("signal_fixture_result.json").toFile(),result);SimZ1CorridorOccupancy.uninstall(cfg);
  System.out.println("PASS exact native control obstruction; moves="+moved+" common="+common+" replacementIssue="+replacement+" reasons="+reasons);
 }
}
