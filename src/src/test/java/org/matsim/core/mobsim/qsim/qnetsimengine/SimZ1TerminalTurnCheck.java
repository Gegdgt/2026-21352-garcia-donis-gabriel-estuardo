package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.*;

/** Exact OSM links and lanes, generic bodies/IDs. Never reads massive events.
 * The bus-sized native actor tests its body; scheduled PT stops are unchanged. */
public final class SimZ1TerminalTurnCheck {
    static final String PRE="osm_1358273941_12_forward", FROM="osm_1358273941_13_forward";
    static final String TO="osm_1358273951_0_forward", TAIL="osm_1358273951_3_forward", END="osm_1358273951_4_forward";
    static Id<Link> id(String s){return Id.createLinkId(s);}
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static List<String> route(boolean terminal){return terminal?List.of(PRE,FROM,TO):List.of(PRE,FROM,TO,"osm_1358273951_1_forward","osm_1358273951_2_forward",TAIL,END);}
    static Scenario scenario(Path input){
        boolean frozen=Files.exists(input.resolve("network-inputNetworkFile.xml"));
        var c=ConfigUtils.createConfig(new SignalSystemsConfigGroup(),new Zona1PriorityConfigGroup());
        c.global().setCoordinateSystem("EPSG:32615");
        c.network().setInputFile(input.resolve(frozen?"transit-weekday/network.xml":"network.xml").toAbsolutePath().toString());
        c.network().setLaneDefinitionsFile(input.resolve(frozen?"transit-weekday/lanes.xml":"lanes.xml").toAbsolutePath().toString());
        c.qsim().setUseLanes(true);
        var sig=ConfigUtils.addOrGetModule(c,SignalSystemsConfigGroup.class);sig.setUseSignalSystems(true);sig.setUseAmbertimes(true);
        sig.setSignalSystemFile(input.resolve(frozen?"signalsystems-signalsystems.xml":"signalSystems.xml").toAbsolutePath().toString());
        sig.setSignalGroupsFile(input.resolve(frozen?"signalsystems-signalgroups.xml":"signalGroups.xml").toAbsolutePath().toString());
        sig.setSignalControlFile(input.resolve(frozen?"signalsystems-signalcontrol.xml":"signalControl.xml").toAbsolutePath().toString());
        var s=ScenarioUtils.loadScenario(c);s.addScenarioElement(SignalsData.ELEMENT_NAME,new SignalsDataLoader(c).loadSignalsData());
        return s;
    }
    static QVehicle body(Scenario s,String name,double length,List<String> path){
        var t=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));t.setLength(length).setPcuEquivalents(1).setMaximumVelocity(10);
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),t);var leg=s.getPopulation().getFactory().createLeg("car");
        leg.setRoute(RouteUtils.createNetworkRoute(path.stream().map(SimZ1TerminalTurnCheck::id).toList(),s.getNetwork()));
        var driver=Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),new Class[]{MobsimDriverAgent.class,PlanAgent.class},(p,m,a)->switch(m.getName()){
            case "getCurrentPlanElement"->leg;case "getCurrentLinkId"->id(path.get(0));case "getId"->Id.createPersonId(name);
            default->throw new AssertionError(m);
        });
        return (QVehicle)Proxy.newProxyInstance(QVehicle.class.getClassLoader(),new Class[]{QVehicle.class},(p,m,a)->switch(m.getName()){
            case "getId"->v.getId();case "getVehicle"->v;case "getDriver"->driver;default->throw new AssertionError(m);
        });
    }
    static void ledgerCheck(Scenario s){
        var events=new ArrayList<Event>();var em=EventsUtils.createEventsManager();em.addHandler((BasicEventHandler)events::add);
        var l=new SimZ1CorridorOccupancy(s,Set.of(),em);l.emitDomains(0);SimZ1CorridorOccupancy.install(s.getConfig().qsim(),l);
        var safety=new SimZ1RouteSafety(s);
        check(s.getNetwork().getLinks().get(id(FROM)).getToNode().getId().toString().equals("333531458"),"Wrong junction");
        check(safety.laneAllows(id(FROM),Id.create(FROM+".lane.1",Lane.class),id(TO)),"Turn prohibited by exact lane/connectivity policy");
        for(String link:List.of(FROM,TO))check(s.getNetwork().getLinks().get(id(link)).getAllowedModes().contains("car"),"Missing road vehicle access");
        var leaders=new ArrayList<QVehicle>();var through=route(false).subList(2,7);
        for(int i=0;i<2;i++){
            var v=body(s,"downstream-"+i,12,through);leaders.add(v);
            check(l.canEnter(v,id(TO),TO+".original",i),"Fixture lead admission");l.enter(v,id(TO),TO+".original",i,"queue_entry");
            for(String link:through.subList(1,4))l.enter(v,id(link),link+".original",i,"queue_entry");
            l.progress(v,id(TAIL),TAIL+".lane.0",i);
        }
        for(double length:new double[]{4.5,2.1,13.5,12}){
            var v=body(s,"terminal-body-"+length,length,route(true));
            check(l.activity(v,id(PRE),PRE+".original",10),"Origin must store full body");l.enter(v,id(FROM),FROM+".lane.0",11,"queue_entry");l.progress(v,id(FROM),FROM+".lane.0",11);
            check(l.canEnter(v,id(TO),TO+".original",12),"Artificial rejection: final short link has a free prefix, occupied unvisited tail");
            check(SimZ1CorridorOccupancy.receiverNotKnownBlocked(s.getConfig().qsim(),v,id(TO),TO+".original"),"Priority probe disagrees with terminal eligibility");
            l.enter(v,id(TO),TO+".original",12,"queue_entry");
            if(length!=2.1){
                check(l.lockedByOther(Id.createNodeId("333531458"),Id.createVehicleId("other")),"Body crossing lost node lock");
                var a=events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(e.getAttributes().get("action"))).reduce((x,y)->y).orElseThrow().getAttributes();
                check("boundary_exit".equals(a.get("passageKind"))&&TO.equals(a.get("exitLinks"))&&!a.containsKey("receiptLink"),"Reserved unvisited downstream links");
            }
            l.progress(v,id(TO),TO+".original",13);l.release(v.getId(),14,"arrival");
            check(!l.lockedByOther(Id.createNodeId("333531458"),Id.createVehicleId("other")),"Arrival leaked node lock");
        }
        var third=body(s,"third-downstream",12,through);check(l.canEnter(third,id(TO),TO+".original",20),"Third lead fits physical domain");
        l.enter(third,id(TO),TO+".original",20,"queue_entry");for(String link:through.subList(1,4))l.enter(third,id(link),link+".original",20,"queue_entry");l.progress(third,id(TAIL),TAIL+".lane.0",20);
        var waiting=body(s,"waiting-terminal",4.5,route(true));check(l.activity(waiting,id(PRE),PRE+".original",21),"Origin admission");
        l.enter(waiting,id(FROM),FROM+".lane.0",21,"queue_entry");l.progress(waiting,id(FROM),FROM+".lane.0",21);
        check(!l.canEnter(waiting,id(TO),TO+".original",22),"Overlapping downstream tail must block terminal arrival");
        check(!SimZ1CorridorOccupancy.receiverNotKnownBlocked(s.getConfig().qsim(),waiting,id(TO),TO+".original"),"Blocked head retained priority competition");
        l.release(third.getId(),23,"arrival");check(l.canEnter(waiting,id(TO),TO+".original",24),"Freed prefix did not recover");l.enter(waiting,id(TO),TO+".original",24,"queue_entry");
        var follower=body(s,"continuing-follower",4.5,route(false));check(l.activity(follower,id(PRE),PRE+".original",25),"Following origin body fits");
        check(!l.canEnter(follower,id(TO),TO+".original",25),"Follower entered occupied terminal passage");
        for(var v:leaders)l.release(v.getId(),26,"arrival");
        var insertion=body(s,"interior-insertion",4.5,through.subList(1,through.size()));
        check(!l.activity(insertion,id(through.get(1)),through.get(1)+".original",26),"Interior insertion invaded retained terminal body");
        l.release(waiting.getId(),27,"arrival");check(l.canEnter(follower,id(TO),TO+".original",28),"Released passage still blocks continuing vehicle");
        l.enter(follower,id(TO),TO+".original",28,"queue_entry");l.release(follower.getId(),29,"arrival");
        SimZ1CorridorOccupancyCheck.verifyTransactions(events);SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());
        System.out.println("PASS exact ledger: legal turn; car/moto/bus/truck; occupied downstream tail; blocked overlap; retained origin; released locks; continuing follower");
    }
    static void nativeCheck(Scenario s)throws Exception{
        var c=s.getConfig();var out=Files.createTempDirectory(Path.of("runtime"),"terminal-turn-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);c.controler().setLinkToLinkRoutingEnabled(true);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setStartTime(0);c.qsim().setEndTime(1200);
        c.qsim().setUsingFastCapacityUpdate(false);c.qsim().setRemoveStuckVehicles(false);c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        c.travelTimeCalculator().setSeparateModes(false);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        ConfigUtils.addOrGetModule(c,Zona1PriorityConfigGroup.class).setClassification("osm-hierarchy");
        var ad=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);ad.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);ad.setWholeVehicleReservation(true);
        for(String name:List.of("home","work")){var a=new ActivityParams(name);a.setTypicalDuration(3600);a.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(a);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var pf=s.getPopulation().getFactory();var vf=s.getVehicles().getFactory();
        for(int i=0;i<9;i++){
            String name="actor-"+i;boolean terminal=i>0&&i<=4;int kind=(i+3)%4;
            var path=i==0?route(false).subList(2,7):route(terminal);
            var t=vf.createVehicleType(Id.create(name,VehicleType.class));t.setLength(i==0?12:new double[]{4.5,2.1,13.5,12}[kind]).setPcuEquivalents(i==0?3.5:new double[]{1,.25,3,3.5}[kind]);
            t.setMaximumVelocity(i==0?.1:10).setNetworkMode("car");s.getVehicles().addVehicleType(t);
            var v=vf.createVehicle(Id.createVehicleId(name),t);s.getVehicles().addVehicle(v);
            var person=pf.createPerson(Id.createPersonId(name));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",v.getId()));var plan=pf.createPlan();
            var home=pf.createActivityFromLinkId("home",id(path.get(0)));home.setEndTime(i==0?1:200+i);plan.addActivity(home);
            var leg=pf.createLeg("car");var r=RouteUtils.createNetworkRoute(path.stream().map(SimZ1TerminalTurnCheck::id).toList(),s.getNetwork());r.setVehicleId(v.getId());leg.setRoute(r);plan.addLeg(leg);
            plan.addActivity(pf.createActivityFromLinkId("work",id(path.get(path.size()-1))));person.addPlan(plan);s.getPopulation().addPerson(person);
        }
        var observed=new ArrayList<Event>();var controller=new Controler(s);RunZona1Simulation.configureSignals(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)observed::add);}});controller.run();
        SimZ1CorridorOccupancyCheck.verifyTransactions(observed);
        check(observed.stream().filter(e->e instanceof PersonArrivalEvent).count()==9,"Native arrivals missing");
        check(observed.stream().noneMatch(e->e instanceof PersonStuckEvent),"Forced native removal");
        var acquired=new HashSet<String>();var entered=new ArrayList<String>();boolean coexist=false;boolean leaderInDomain=false;
        var reservations=new HashMap<String,Map<String,String>>();var fronts=new HashMap<String,Double>();var arrivals=new ArrayList<String>();int sharedExits=0;
        for(var e:observed){var a=e.getAttributes();
            if(e.getEventType().equals("simz1OccupancyReservation")){
                if(Set.of("ENTER","TRANSFER").contains(a.get("action")))reservations.put(a.get("vehicle"),a);
                else if("EXIT".equals(a.get("action"))){reservations.remove(a.get("vehicle"));fronts.remove(a.get("vehicle"));}}
            if(e.getEventType().equals("simz1OccupancyProgress"))fronts.put(a.get("vehicle"),Double.parseDouble(a.get("modeledFrontLowerBoundMeters")));
            if(e instanceof PersonArrivalEvent arrival){
                check(arrival.getPersonId().toString().equals("actor-0")||entered.contains(arrival.getPersonId().toString()),"Arrival without native turn");
                arrivals.add(arrival.getPersonId()+"="+arrival.getTime());}
            if(e.getEventType().equals("simz1OccupancyReservation")&&"actor-0".equals(a.get("vehicle"))){
                if(TO.equals(a.get("corridor")))leaderInDomain=!"EXIT".equals(a.get("action"));}
            if(e.getEventType().equals("simz1OccupancyPassage")){
                if("ACQUIRE".equals(a.get("action"))){check(acquired.add(a.get("vehicle")),"Duplicate passage");if(TO.equals(a.get("exitLinks"))){
                    coexist|=leaderInDomain;if(leaderInDomain)sharedExits++;
                    check(reservations.get(a.get("vehicle")).get("corridor").equals(PRE),"Origin body released before native final activity");
                    for(var entry:reservations.entrySet())if(TO.equals(entry.getValue().get("corridor")))
                        check(fronts.get(entry.getKey())-Double.parseDouble(entry.getValue().get("footprintMeters"))>=s.getNetwork().getLinks().get(id(TO)).getLength()-1e-8,"Terminal body would overlap downstream tail");}}
                else check(acquired.remove(a.get("vehicle")),"Release without acquire");}
            if(e instanceof LinkEnterEvent le&&le.getLinkId().equals(id(TO))&&!le.getVehicleId().toString().equals("actor-0"))entered.add(le.getVehicleId().toString());
            if(e.getEventType().equals("simz1OccupancyProgress")&&a.containsKey("leaderVehicle"))check(Double.parseDouble(a.get("modeledFrontLowerBoundMeters"))<=Double.parseDouble(a.get("leaderFrontLowerBoundMeters"))-Double.parseDouble(a.get("leaderFootprintMeters"))+1e-8,"Modeled body overlap");
            if(e.getEventType().equals("simz1NativeDecision")&&"GO".equals(a.get("decision")))check(!"false".equals(a.get("nativeHasGreen")),"Red crossing");
        }
        check(acquired.isEmpty(),"Leaked passage locks");check(coexist,"Short terminal waited for unrelated downstream occupant to leave");
        check(entered.equals(List.of("actor-1","actor-2","actor-3","actor-4","actor-5","actor-6","actor-7","actor-8")),"Native shared FIFO changed: "+entered);
        Files.writeString(out.resolve("checks.txt"),"arrivals="+arrivals+"\nturn_order="+entered+"\nterminal_passages_with_downstream_occupant="+sharedExits+"\nno_overlap=true\nno_reservations_leaked=true\n");
        System.out.println("PASS native exact network/signals/lanes: 9 arrivals; terminal + continuing mixed bodies; FIFO; no overlap/removal/leaked reservation; evidence="+out);
    }
    public static void main(String[] args)throws Exception{try{Zona1Logging.configure();var s=scenario(Path.of(args.length==0?"scenarios/zona1":args[0]));ledgerCheck(s);nativeCheck(s);}finally{org.apache.logging.log4j.LogManager.shutdown();}}
}
