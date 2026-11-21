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

/** Exact effective geometry and signals; real plan agent and production evaluate/attempt. */
public final class SimZ1TemporalInstallationCheck {
 static final String S="osm_420120098_2_forward",P="osm_420120098_1_forward",C="osm_420138103_0_forward",R="osm_60237267_0_forward";
 static Id<Link> id(String s){return Id.createLinkId(s);}
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static Object field(Object o,String n)throws Exception{var f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
 public static void main(String[] args)throws Exception{
  try{run(Path.of(args[0]),Path.of(args[1]),args.length>2&&args[2].equals("red"));}finally{org.apache.logging.log4j.LogManager.shutdown();}
 }
 static void run(Path evidence,Path out,boolean red)throws Exception {
  var json=new ObjectMapper();var input=json.readTree(evidence.resolve("signal_fixture_input.json").toFile());var run=Path.of(input.path("run").asText());
  var config=ConfigUtils.createConfig(new SignalSystemsConfigGroup());config.setContext(run.resolve("config-simz1.xml").toUri().toURL());config.global().setRandomSeed(20261023);var cfg=config.qsim();cfg.setUseLanes(true);cfg.setUsingFastCapacityUpdate(false);cfg.setNumberOfThreads(1);cfg.setNodeOffset(0);cfg.setRemoveStuckVehicles(false);
  var sc=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);sc.setUseSignalSystems(true);sc.setUseAmbertimes(true);
  sc.setSignalSystemFile(run.resolve("inputs/signalsystems-signalsystems.xml").toString());sc.setSignalGroupsFile(run.resolve("inputs/signalsystems-signalgroups.xml").toString());sc.setSignalControlFile(run.resolve("inputs/signalsystems-signalcontrol.xml").toString());
  config.network().setInputFile(run.resolve("inputs/transit-weekday/network.xml").toString());config.network().setLaneDefinitionsFile(run.resolve("inputs/transit-weekday/lanes.xml").toString());
  var s=ScenarioUtils.createScenario(config);new MatsimNetworkReader(s.getNetwork()).readFile(config.network().getInputFile());new LanesReader(s).readFile(config.network().getLaneDefinitionsFile());
  var data=new SignalsDataLoader(config).loadSignalsData();data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
  var controlled=new HashSet<Id<Node>>();for(var system:data.getSignalSystemsData().getSignalSystemData().values())for(var signal:system.getSignalData().values())controlled.add(s.getNetwork().getLinks().get(signal.getLinkId()).getToNode().getId());
  var events=EventsUtils.createEventsManager();var log=new ArrayList<Event>();events.addHandler((BasicEventHandler)log::add);var timer=new MobsimTimer(1);
  var admission=new SimZ1AdmissionConfigGroup();admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);config.addModule(admission);
  var ledger=new SimZ1CorridorOccupancy(s,controlled,events);SimZ1CorridorOccupancy.install(cfg,ledger);
  var links=new HashMap<Id<Link>,QLinkI>();var nodes=new HashMap<Id<Node>,Zona1QNodeImpl>();
  var qnet=new QNetwork(s.getNetwork(),null){public Map<Id<Link>,QLinkI> getNetsimLinks(){return links;}public QLinkI getNetsimLink(Id<Link> key){return links.get(key);}};
  var engine=new QNetsimEngineI.NetsimInternalInterface(){public QNetwork getNetsimNetwork(){return qnet;}public void arrangeNextAgentState(MobsimAgent a){throw new AssertionError("No abort/forced progress");}public void letVehicleArrive(QVehicle v){throw new AssertionError("No arrival");}};
  var context=new NetsimEngineContext(events,7.5,null,null,cfg,timer,null);var settings=new Zona1PriorityConfigGroup();var safety=new SimZ1RouteSafety(s);
  var selected=new HashSet<Id<Link>>();for(String name:List.of(P,S,C,R,"osm_60237267_1_forward")){
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

  var path=new ArrayList<Id<Link>>();for(var v:input.path("path"))path.add(id(v.asText()));int at=input.path("currentIndex").asInt();
  var pf=s.getPopulation().getFactory();var person=pf.createPerson(Id.createPersonId("z1_32590"));
  input.path("attributes").fields().forEachRemaining(a->person.getAttributes().putAttribute(a.getKey(),a.getValue().asText()));
  var plan=pf.createPlan();person.addPlan(plan);s.getPopulation().addPerson(person);
  var origin=pf.createActivityFromLinkId("home",path.get(0));origin.setEndTime(0);plan.addActivity(origin);
  var leg=pf.createLeg("car");var route=org.matsim.core.population.routes.RouteUtils.createNetworkRoute(path);route.setVehicleId(Id.createVehicleId(person.getId()));leg.setRoute(route);
  leg.getAttributes().putAttribute("simz1TripId",json.readTree(input.path("attributes").path("simz1Trips").asText()).get(0).path("id").asText());
  plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",path.get(path.size()-1)));
  // A two-person fixture uses the unchanged seeded 50% cohort. The dummy is
  // inactive; this is not a substitute for the historical cohort identity.
  String dummyName=new Random(20261023).nextInt(2)==1?"zz-inactive":"aa-inactive";
  var dummy=pf.createPerson(Id.createPersonId(dummyName));dummy.addPlan(pf.createPlan());s.getPopulation().addPerson(dummy);
  var netsim=(org.matsim.core.mobsim.qsim.interfaces.Netsim)Proxy.newProxyInstance(SimZ1TemporalInstallationCheck.class.getClassLoader(),new Class<?>[]{org.matsim.core.mobsim.qsim.interfaces.Netsim.class},(o,m,a)->switch(m.getName()){
   case "getScenario"->s;case "getEventsManager"->events;case "getSimTimer"->timer;case "getNetsimNetwork"->qnet;default->throw new AssertionError(m);
  });
  var driver=new org.matsim.core.mobsim.qsim.agents.PersonDriverAgentImpl(plan,netsim,org.matsim.core.utils.timing.TimeInterpretation.create(config));driver.endActivityAndComputeNextState(0);
  leg=org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.getModifiableCurrentLeg(driver);
  var type=VehicleUtils.createVehicleType(Id.create("Normal",VehicleType.class));type.setLength(4.5).setWidth(1.8).setPcuEquivalents(1).setMaximumVelocity(13.88888888888889).setNetworkMode("car");
  var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(person.getId()),type);s.getVehicles().addVehicleType(type);s.getVehicles().addVehicle(vehicle);
  var head=new QVehicleImpl(vehicle);head.setDriver(driver);driver.setVehicle(head);
  var rerouter=new CongestionAwareRerouting(s);
  var init=CongestionAwareRerouting.class.getDeclaredMethod("initializeNative",QNetwork.class,Map.class,org.matsim.core.api.experimental.events.EventsManager.class);init.setAccessible(true);init.invoke(rerouter,qnet,Map.of(head.getId(),head),events);events.addHandler(rerouter);
  var eligible=CongestionAwareRerouting.class.getDeclaredMethod("eligible",MobsimAgent.class,double.class);eligible.setAccessible(true);check((boolean)eligible.invoke(rerouter,driver,0.),"Unchanged real cohort must select fixture driver");
  events.processEvent(new org.matsim.api.core.v01.events.VehicleEntersTrafficEvent(0,person.getId(),path.get(0),head.getId(),"car",0));
  for(int i=1;i<at;i++){check(driver.chooseNextLinkId().equals(path.get(i)),"Fixture occurrence prefix mismatch");driver.notifyMoveOverNode(path.get(i));events.processEvent(new org.matsim.api.core.v01.events.LinkEnterEvent(i,head.getId(),path.get(i)));}
  var previous=((QLinkLanesImpl)links.get(id(P))).getQueueLanes().get(Id.create(P+".lane.0",Lane.class));timer.setTime(1689);check(ledger.canEnter(head,id(P),previous.getId().toString(),1689),"Initial fixture body cannot fit");previous.addFromUpstream(head);
  var move=Zona1QNodeImpl.class.getDeclaredMethod("moveVehicleOverNode",QVehicle.class,QLinkI.class,QLaneI.class,double.class);move.setAccessible(true);
  int evaluation=red?1728:1729;
  for(int t=1690;t<evaluation;t++){
   timer.setTime(t);for(var system:systems)system.updateState(t);
   if(driver.getCurrentLinkIndex()<at){previous.doSimStep();if(!previous.isNotOfferingVehicle())move.invoke(nodes.get(links.get(id(P)).getLink().getToNode().getId()),head,links.get(id(P)),previous,(double)t);}
   if(driver.getCurrentLinkIndex()==at)((QLinkLanesImpl)links.get(id(S))).doSimStep();
  }
  check(driver.getCurrentLinkIndex()==at,"Native transfer to current occurrence failed");
  timer.setTime(evaluation);for(var system:systems)system.updateState(evaluation);
  var source=(QLinkLanesImpl)links.get(id(S));var lane=source.getQueueLanes().get(Id.create(S+".lane.0",Lane.class));check(lane.getFirstVehicle()==head,"Offered native head missing");
  String before=SimZ1OpposedReturnRerouteCheck.snapshot(ledger);var oldLegRoute=leg.getRoute();
  var evaluate=CongestionAwareRerouting.class.getDeclaredMethod("evaluate",double.class,Collection.class);evaluate.setAccessible(true);evaluate.invoke(rerouter,(double)evaluation,List.of(driver));
  if(red) {
   var rejection=log.stream().filter(e->e.getEventType().equals("zona1RerouteRejected")).findFirst().orElseThrow();
   check("active_candidate_signal_not_green".equals(rejection.getAttributes().get("reason")),"Temporary red must retain native admission");
   check(leg.getRoute()==oldLegRoute&&before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(ledger))&&driver.getCurrentLinkIndex()==at,"Rejected query mutated route/cursor/reservations");
   Files.createDirectories(out);json.writerWithDefaultPrettyPrinter().writeValue(out.resolve("red-rejection.json").toFile(),rejection.getAttributes());
   SimZ1CorridorOccupancy.uninstall(cfg);System.out.println("PASS temporal repair red rejection leaves route/cursor/reservations unchanged");return;
  }
  var installed=log.stream().filter(e->e.getEventType().equals("zona1WithinDayReroute")).findFirst().orElseThrow(()->new AssertionError("No installation: "+log.stream().filter(e->e.getEventType().startsWith("zona1Reroute")).map(Event::getAttributes).toList()));
  check("validated_temporal_repair".equals(installed.getAttributes().get("reason")),"Expected temporal repair: "+installed.getAttributes());
  var candidate=SimZ1RouteSafety.full((org.matsim.core.population.routes.NetworkRoute)leg.getRoute());
  check(leg.getRoute()!=oldLegRoute&&driver.getCurrentLinkIndex()==at&&candidate.subList(0,at+1).equals(path.subList(0,at+1)),"Installation mutated cursor/prefix");
  check(before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(ledger)),"Pure search/installation mutated reservations");
  check(!candidate.get(at+1).equals(id(C)),"Same impossible next passage installed");
  check((boolean)move.invoke(nodes.get(source.getLink().getToNode().getId()),head,source,lane,1729.),"Native admission did not move after production repair");
  check(driver.getCurrentLinkIndex()==at+1&&driver.getCurrentLinkId().equals(candidate.get(at+1)),"Native cursor did not follow installed occurrence");
  for(int t=1730;t<1750;t++){timer.setTime(t);links.get(driver.getCurrentLinkId()).doSimStep();}
  check(!field(ledger,"active").toString().equals("{}"),"Body reservation lost after movement");
  var receiptProgress=log.stream().filter(e->e.getEventType().equals("simz1OccupancyProgress")&&candidate.get(at+1).toString().equals(e.getAttributes().get("link")))
      .mapToDouble(e->Double.parseDouble(e.getAttributes().get("modeledFrontLowerBoundMeters"))).max().orElseThrow();
  check(receiptProgress>=4.6,"Native movement did not clear the whole body plus 0.10m gap into the receipt");
  var oldDomain=((Map<?,?>)field(ledger,"domains")).get(id(S));
  check(Arrays.stream((double[])field(oldDomain,"used")).sum()==0,"Old domain retained a cleared body reservation");
  check(((Map<?,?>)field(ledger,"nodeLocks")).isEmpty()&&((Map<?,?>)field(ledger,"connectorLocks")).isEmpty(),"Repair leaked passage locks");
  var result=new LinkedHashMap<String,Object>();result.put("scope","production detect/select/search/attempt/install/native movement to full-body receipt; not full-trip arrival");
  result.put("prefix_seeded_fixture",true);result.put("historical_run_id",input.path("run_id").asText());result.put("iteration",0);result.put("index_before",at);result.put("index_after",driver.getCurrentLinkIndex());
  result.put("old",path.stream().map(Object::toString).toList());result.put("candidate",candidate.stream().map(Object::toString).toList());result.put("installation",installed.getAttributes());
  result.put("native_events",log.stream().filter(e->e.getTime()>=1729).map(Event::getAttributes).toList());result.put("ledger_after",SimZ1OpposedReturnRerouteCheck.snapshot(ledger));
  Files.createDirectories(out);json.writerWithDefaultPrettyPrinter().writeValue(out.resolve("installation-result.json").toFile(),result);
  SimZ1CorridorOccupancy.uninstall(cfg);System.out.println("PASS production temporal installation and native receipt "+driver.getCurrentLinkId());
 }
}
