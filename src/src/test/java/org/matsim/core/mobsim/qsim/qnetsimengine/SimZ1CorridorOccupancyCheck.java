package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;
import gt.edu.uvg.sim.zona1.*;

/** Reproducible metric reservation and actual native QSim hook fixtures.
 * No microscopic positions are asserted from queue events. */
public final class SimZ1CorridorOccupancyCheck {
    static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static void close(double a,double b,String message){require(Math.abs(a-b)<1e-7,message+": "+a+" != "+b);}
    static Scenario scenario() {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var network=scenario.getNetwork();var f=network.getFactory();
        var coords=Map.of("o",new Coord(-46,0),"a",new Coord(-6,0),"j",new Coord(0,0),"b",new Coord(40,0),
            "d",new Coord(80,0),"side",new Coord(0,40),"tiny",new Coord(0,41));
        for(var e:coords.entrySet())network.addNode(f.createNode(Id.createNodeId(e.getKey()),e.getValue()));
        link(network,"origin","o","a",40,1);link(network,"short","a","j",6,1);
        link(network,"out","j","b",40,1);link(network,"destination","b","d",40,1);
        link(network,"branch","j","side",40,1);link(network,"tiny","side","tiny",1,1);
        // A real control on side prevents the 1m terminal from joining branch.
        network.getNodes().get(Id.createNodeId("side")).getAttributes().putAttribute("osm:highway","stop");
        return scenario;
    }
    static void link(Network n,String id,String from,String to,double length,int lanes){
        var l=n.getFactory().createLink(Id.createLinkId(id),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setFreespeed(10);l.setCapacity(10000);l.setNumberOfLanes(lanes);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
    }
    static QVehicle vehicle(String name,double length) {
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));type.setLength(length).setPcuEquivalents(1).setMaximumVelocity(10);
        var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);
        return (QVehicle)Proxy.newProxyInstance(QVehicle.class.getClassLoader(),new Class[]{QVehicle.class},(p,m,a)->switch(m.getName()) {
            case "getId"->v.getId();case "getVehicle"->v;case "getDriver"->null;default->throw new AssertionError(m);
        });
    }
    static List<Event> ledgerFixture() {
        var scenario=scenario();var manager=EventsUtils.createEventsManager();var events=new ArrayList<Event>();manager.addHandler((BasicEventHandler)events::add);
        var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);ledger.emitDomains(0);
        require(ledger.corridorId(Id.createLinkId("origin")).equals(ledger.corridorId(Id.createLinkId("short"))),"OSM subdivision split storage");
        require(!ledger.corridorId(Id.createLinkId("short")).equals(ledger.corridorId(Id.createLinkId("out"))),"Crossed real junction");
        var bus=vehicle("bus",13.5);var truck=vehicle("truck",12);var car=vehicle("car",4.5);var moto=vehicle("motorcycle",2.1);
        var origin=Id.createLinkId("origin");var shortId=Id.createLinkId("short");
        require(ledger.activity(bus,origin,"origin.original",1),"Bus activity rejected despite full corridor room");
        require(!ledger.activity(truck,origin,"origin.original",1),"Activity inserted ahead of occupied model slot");
        ledger.enter(bus,shortId,"short.original",1,"queue_entry");ledger.progress(bus,shortId,"short.lane.0",1);
        for(var following:List.of(truck,car,moto)){require(ledger.canEnter(following,origin,"origin.original",1),"Following body rejected");ledger.enter(following,origin,"origin.original",1,"queue_entry");
            ledger.enter(following,shortId,"short.original",1,"queue_entry");ledger.progress(following,shortId,"short.lane.0",1);}
        require(!ledger.canEnter(vehicle("secondBus",13.5),origin,"origin.original",1),"Admitted incomplete bus footprint");
        require(ledger.canEnter(bus,shortId,"short.original",2),"13.5m bus froze at 6m subdivision");
        ledger.enter(bus,shortId,"short.original",2,"queue_entry");ledger.progress(bus,shortId,"short.original",3);
        require(ledger.canEnter(bus,shortId,"short.lane.0",3),"Internal lane duplicate reservation");
        ledger.enter(bus,shortId,"short.lane.0",3,"queue_entry");
        require(!ledger.canEnter(bus,Id.createLinkId("tiny"),"tiny.original",4),"Artificially enlarged tiny conflict domain");
        require(ledger.corridorId(shortId).equals("origin"),"Stable corridor identity changed");
        ledger.clearLink(shortId,4);ledger.release(truck.getId(),4,"abort");ledger.release(car.getId(),4,"arrival");ledger.release(moto.getId(),4,"arrival");
        // An exact length+0.10m fit is accepted; any extra body is rejected.
        double capacity=events.stream().filter(e->e.getEventType().equals("simz1OccupancyDomain")&&e.getAttributes().get("link").equals("origin"))
            .mapToDouble(e->Double.parseDouble(e.getAttributes().get("laneCapacityMeters"))).findFirst().orElseThrow();
        var exact=vehicle("exact",capacity-.1);require(ledger.activity(exact,origin,"origin.original",5),"Exact metric fit rejected");
        require(!ledger.canEnter(moto,origin,"origin.original",5),"Minimum gap ignored at full corridor");ledger.release(exact.getId(),6,"arrival");
        verifyTransactions(events);return events;
    }
    static void verifyTransactions(List<Event> events) {
        var active=new HashMap<String,Map<String,String>>();var used=new HashMap<String,Double>();
        for(var e:events)if(e.getEventType().equals("simz1OccupancyReservation")) {
            var a=e.getAttributes();String v=a.get("vehicle"),key=a.get("corridor")+"/"+a.get("modelSlot");double footprint=Double.parseDouble(a.get("footprintMeters"));
            close(footprint-Double.parseDouble(a.get("bodyLengthMeters")),.1,"Gap missing");
            switch(a.get("action")) {
                case "ENTER" -> {require(active.put(v,a)==null,"Double ENTER");used.merge(key,footprint,Double::sum);}
                case "TRANSFER" -> {var previous=active.put(v,a);require(previous!=null,"TRANSFER without reservation");require(previous.get("modelSlot").equals(a.get("modelSlot")),"Mid-corridor slot drift");require(previous.get("reservationOrdinal").equals(a.get("reservationOrdinal")),"Ordinal drift");}
                case "EXIT" -> {require(active.remove(v)!=null,"EXIT missing reservation");used.merge(key,-footprint,Double::sum);}
                case "WAIT" -> {require(!a.get("modelSlot").equals("0"),"WAIT reserved a slot");continue;}
                default -> throw new AssertionError(a);
            }
            double current=used.getOrDefault(key,0.0);close(current,Double.parseDouble(a.get("slotUsedMeters")),"Ledger snapshot mismatch");
            require(current>=-1e-7 && current<=Double.parseDouble(a.get("laneCapacityMeters"))+1e-7,"Storage overflow");
        }
        require(active.isEmpty(),"Leaked final reservations: "+active.keySet());
    }
    static void qsimFixture(boolean lanes) throws Exception {qsimFixture(lanes,false);}
    static void qsimFixture(boolean lanes,boolean passage) throws Exception {qsimFixture(lanes,passage,false,false);}
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt) throws Exception {
        qsimFixture(lanes,passage,boundaryExit,interiorReceipt,false,false);
    }
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt,boolean passagePriority,boolean rejectedPrefix) throws Exception {
        qsimFixture(lanes,passage,boundaryExit,interiorReceipt,passagePriority,rejectedPrefix,false);
    }
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt,boolean passagePriority,boolean rejectedPrefix,boolean earlyTurn) throws Exception {
        qsimFixture(lanes,passage,boundaryExit,interiorReceipt,passagePriority,rejectedPrefix,earlyTurn,false);
    }
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt,boolean passagePriority,boolean rejectedPrefix,boolean earlyTurn,boolean signalWindow) throws Exception {
        qsimFixture(lanes,passage,boundaryExit,interiorReceipt,passagePriority,rejectedPrefix,earlyTurn,signalWindow,false);
    }
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt,boolean passagePriority,boolean rejectedPrefix,boolean earlyTurn,boolean signalWindow,boolean activityPassage) throws Exception {
        qsimFixture(lanes,passage,boundaryExit,interiorReceipt,passagePriority,rejectedPrefix,earlyTurn,signalWindow,activityPassage,false);
    }
    static void qsimFixture(boolean lanes,boolean passage,boolean boundaryExit,boolean interiorReceipt,boolean passagePriority,boolean rejectedPrefix,boolean earlyTurn,boolean signalWindow,boolean activityPassage,boolean rerouteRevisit) throws Exception {
        var scenario=scenario();var config=scenario.getConfig();
        if(rerouteRevisit)link(scenario.getNetwork(),"loop-return","b","j",40,1);
        if(passage){var n=scenario.getNetwork();n.addNode(n.getFactory().createNode(Id.createNodeId("parking"),new Coord(-6,30)));
            link(n,"parking-exit","parking","a",30,1);}
        if(boundaryExit){var n=scenario.getNetwork();n.getLinks().get(Id.createLinkId("destination")).setLength(5);
            n.getNodes().get(Id.createNodeId("b")).getAttributes().putAttribute("osm:highway","traffic_signals");}
        if(interiorReceipt){var n=scenario.getNetwork();n.removeLink(Id.createLinkId("branch"));
            link(n,"receipt-prefix","a","j",40,2);n.getLinks().get(Id.createLinkId("out")).setNumberOfLanes(2);n.getLinks().get(Id.createLinkId("destination")).setNumberOfLanes(2);}
        if(passagePriority){var n=scenario.getNetwork();link(n,"priority-avenue","side","j",40,1);
            n.getLinks().get(Id.createLinkId("priority-avenue")).getAttributes().putAttribute("simz1:priorityRole","avenue");
            n.getLinks().get(Id.createLinkId("short")).getAttributes().putAttribute("simz1:priorityRole","street");}
        if(rejectedPrefix){var n=scenario.getNetwork();n.removeLink(Id.createLinkId("out"));
            n.addNode(n.getFactory().createNode(Id.createNodeId("mid"),new Coord(1,0)));
            link(n,"out","j","mid",1,1);link(n,"out-tail","mid","b",13,1);
            n.getLinks().get(Id.createLinkId("branch")).setNumberOfLanes(6);
            n.getNodes().get(Id.createNodeId("b")).getAttributes().putAttribute("osm:highway","traffic_signals");}
        if(earlyTurn){var n=scenario.getNetwork();n.removeLink(Id.createLinkId("out"));n.removeLink(Id.createLinkId("destination"));
            n.addNode(n.getFactory().createNode(Id.createNodeId("turn"),new Coord(3,0)));
            link(n,"out","j","turn",3,1);link(n,"unvisited-tail","turn","b",37,1);link(n,"return","turn","j",3,1);
            link(n,"destination","side","d",80,1);}
        if(signalWindow){var n=scenario.getNetwork();link(n,"signal-cross-in","side","j",40,1);n.getNodes().get(Id.createNodeId("j")).getAttributes().putAttribute("osm:highway","traffic_signals");}
        if(activityPassage)scenario.getNetwork().getLinks().get(Id.createLinkId("origin")).setLength(5);
        var out=Files.createTempDirectory(Path.of("runtime"),"corridor-native-"+(lanes?"lanes-":"plain-"));
        config.controler().setOutputDirectory(out.resolve("run").toString());config.controler().setLastIteration(0);
        config.global().setNumberOfThreads(1);config.qsim().setNumberOfThreads(1);config.qsim().setUseLanes(lanes);
        config.qsim().setStartTime(0);config.qsim().setEndTime(900);config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);config.qsim().setRemoveStuckVehicles(false);
        config.travelTimeCalculator().setSeparateModes(false);config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);config.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var f=scenario.getPopulation().getFactory();var vf=scenario.getVehicles().getFactory();
        for(int i=0;i<12;i++) {
            String name=List.of("bus","truck","car","motorcycle").get(i%4)+i;
            var type=vf.createVehicleType(Id.create(name,VehicleType.class));type.setLength(new double[]{13.5,12,4.5,2.1}[i%4]).setPcuEquivalents(new double[]{3,3.5,1,.25}[i%4]);
            type.setMaximumVelocity(i==0?.5:10).setNetworkMode("car");scenario.getVehicles().addVehicleType(type);
            var v=vf.createVehicle(Id.createVehicleId(name),type);scenario.getVehicles().addVehicle(v);
            var person=f.createPerson(Id.createPersonId(name));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",v.getId()));
            var plan=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("origin"));home.setEndTime(signalWindow?30:1);plan.addActivity(home);
            var leg=f.createLeg("car");var route=RouteUtils.createNetworkRoute((earlyTurn?List.of("origin","short","out","return","branch","destination"):rejectedPrefix?List.of("origin","short","out","out-tail","destination"):List.of("origin","short","out","destination")).stream().map(Id::createLinkId).toList(),scenario.getNetwork());route.setVehicleId(v.getId());leg.setRoute(route);plan.addLeg(leg);
            plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId("destination")));person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        if(lanes)LanesGenerator.build(scenario);
        if(signalWindow){var signals=TrafficLightsGenerator.build(scenario,null);
            for(var control:signals.getSignalControlData().getSignalSystemControllerDataBySystemId().values())for(var plan:control.getSignalPlanData().values()){
                plan.setCycleTime(100);plan.setOffset(0);for(var setting:plan.getSignalGroupSettingsDataByGroupId().values()){
                    boolean horizontal=setting.getSignalGroupId().toString().equals("calle");setting.setOnset(horizontal?0:50);setting.setDropping(horizontal?40:90);}}}
        var observed=new ArrayList<Event>();
        var controller=new Controler(scenario);if(signalWindow)RunZona1Simulation.configureSignals(controller);else UnsignalizedPriority.configure(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)observed::add);}});
        // Synthetic within-day revisit: retain the traversed prefix and install
        // one legal loop after entering out. This reproduces the historical
        // z1_00507 mechanism, not its measured times or a replacement demand.
        var rerouted=new HashSet<Id<org.matsim.api.core.v01.population.Person>>();
        if(rerouteRevisit)controller.addOverridingModule(new AbstractModule(){public void install(){
            addMobsimListenerBinding().toInstance((org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener)event->{
                var qsim=(org.matsim.core.mobsim.qsim.QSim)event.getQueueSimulation();
                for(var agent:qsim.getAgents().values())if(agent.getState()==org.matsim.core.mobsim.framework.MobsimAgent.State.LEG
                        &&Id.createLinkId("out").equals(agent.getCurrentLinkId())&&rerouted.add(agent.getId())){
                    var leg=org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.getModifiableCurrentLeg(agent);
                    int index=org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent);
                    require(index==2,"Synthetic reroute must retain the already traversed prefix");
                    var candidate=List.of("origin","short","out","loop-return","out","destination").stream().map(Id::createLinkId).toList();
                    var vehicle=((org.matsim.core.mobsim.framework.MobsimDriverAgent)agent).getPlannedVehicleId();
                    require(SimZ1CorridorOccupancy.replacementIssue(config.qsim(),vehicle,candidate,index)==null,"Synthetic revisit invalidates an existing reservation");
                    var route=((org.matsim.core.population.routes.NetworkRoute)leg.getRoute()).clone();
                    route.setLinkIds(candidate.get(0),candidate.subList(1,candidate.size()-1),candidate.get(candidate.size()-1));leg.setRoute(route);
                    org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.resetCaches(agent);
                    require(org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent)==index,"Reroute moved native route cursor");
                }
            });
        }});
        controller.run();verifyTransactions(observed);
        require(observed.stream().filter(e->e instanceof PersonArrivalEvent).count()==12,"Native fixture lost vehicles");
        require(observed.stream().noneMatch(e->e instanceof PersonStuckEvent),"Native fixture aborted");
        require(observed.stream().anyMatch(e->e.getEventType().equals("simz1OccupancyReservation")&&e.getAttributes().get("action").equals("WAIT")),"No capacity rejection exercised");
        require(observed.stream().filter(e->e instanceof LinkEnterEvent v&&v.getLinkId().toString().equals("short")).count()==12,"Heavy body froze on short native link");
        if(rerouteRevisit){
            require(rerouted.size()==12,"Synthetic revisit omitted a driver");
            require(observed.stream().filter(e->e instanceof LinkEnterEvent v&&v.getLinkId().toString().equals("out")).count()==24,"Revisited receiver did not admit every body twice");
            require(observed.stream().filter(e->e instanceof LinkEnterEvent v&&v.getLinkId().toString().equals("loop-return")).count()==12,"Revisit bypassed the native return link");
            System.out.println("PASS native reroute revisit: 3 buses, 3 trucks, 3 cars, 3 motorcycles arrive; no abort or leaked reservation; evidence="+out);
        }
        if(passage||interiorReceipt||boundaryExit){long acquired=observed.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&e.getAttributes().get("action").equals("ACQUIRE")).count();
            long released=observed.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&e.getAttributes().get("action").equals("RELEASE")).count();
            require(acquired>=9&&acquired==released,"Missing passage receipts/lock releases: "+acquired+"/"+released);
            var passages=new HashMap<String,Set<String>>();
            for(var e:observed){var a=e.getAttributes();if(e.getEventType().equals("simz1OccupancyPassage")){
                if(a.get("action").equals("ACQUIRE"))passages.put(a.get("vehicle"),Set.of(a.getOrDefault("passageLinks",a.getOrDefault("exitLinks","")).split(",")));
                else passages.remove(a.get("vehicle"));}
                if(e.getEventType().equals("simz1NativeDecision")&&"WAIT".equals(a.get("decision")))require(!passages.getOrDefault(a.get("vehicle"),Set.of()).contains(a.get("link")),"Stopped inside preauthorized connector");}}
        if(boundaryExit)require(observed.stream().anyMatch(e->e.getEventType().equals("simz1OccupancyPassage")&&"boundary_exit".equals(e.getAttributes().get("passageKind"))),"Missing retained-origin exit reservation");
        if(interiorReceipt)require(observed.stream().anyMatch(e->e.getEventType().equals("simz1OccupancyPassage")&&"out".equals(e.getAttributes().get("receiptLink"))&&"receipt-prefix".equals(e.getAttributes().get("corridor"))),"Missing interior receipt");
        if(passagePriority){var heads=new HashMap<String,String>();var permission=new HashMap<String,Double>();int credited=0,crossed=0;
            for(var event:observed)if(event.getEventType().equals("simz1Priority")){var a=event.getAttributes();var vehicle=a.get("vehicle");switch(a.get("action")){
                case "HEAD" -> require(heads.put(vehicle,a.get("lane"))==null,"Passage left a previous priority HEAD alive");
                case "GO" -> {permission.put(vehicle,event.getTime());if(a.containsKey("passageStopCreditSeconds")){credited++;require(Double.parseDouble(a.get("passageAuthorizedTime"))-Double.parseDouble(a.get("passageHoldStartTime"))+1e-8>=Double.parseDouble(a.get("passageRequiredStopSeconds")),"Unpaid upstream stop credit");}}
                case "CROSS" -> {require(heads.remove(vehicle)!=null,"Priority CROSS without HEAD");require(Objects.equals(permission.remove(vehicle),event.getTime()),"Priority CROSS omitted its native GO");crossed++;}
            }}
            require(heads.isEmpty()&&credited>=12&&crossed>=12,"Passage priority lifecycle incomplete");}
        if(rejectedPrefix){var domains=new HashMap<String,String>();boolean crossedRejected=false;
            for(var event:observed){var a=event.getAttributes();if(event.getEventType().equals("simz1OccupancyDomain"))domains.put(a.get("link"),a.get("corridor"));
                if(event.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(a.get("action"))&&a.containsKey("receiptLink")){
                    var prefix=List.of(a.get("passageLinks").split(","));for(var connector:prefix)require(!domains.get(connector).equals(a.get("corridor")),"Rejected domain reused as its own downstream receipt");
                    crossedRejected|=prefix.contains("out")&&prefix.contains("out-tail")&&"destination".equals(a.get("receiptLink"));}}
            require(crossedRejected,"Missing full traversal of rejected domain");}
        if(earlyTurn){require(observed.stream().noneMatch(e->e instanceof LinkEnterEvent l&&l.getLinkId().toString().equals("unvisited-tail")),"Fixture unexpectedly visited full receiver");
            boolean traversed=false;for(var e:observed)if(e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(e.getAttributes().get("action"))){var a=e.getAttributes();
                if(a.containsKey("receiptLink")){require(!a.get("receiptLink").equals("out"),"Receipt used unvisited corridor length after U-turn");
                    require(Double.parseDouble(a.get("receiptReachableFrontMeters"))+1e-8>=Double.parseDouble(a.get("clearanceFrontMeters")),"Route cannot reach its promised clearance");}
                traversed|=a.getOrDefault("passageLinks","").contains("out,return");}require(traversed,"U-turn was not preauthorized as a complete connector path");}
        if(signalWindow){double first=observed.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(e.getAttributes().get("action"))).mapToDouble(Event::getTime).min().orElseThrow();
            require(first>=100,"Entered short connector when current green could expire before native crossing");
            require(observed.stream().noneMatch(e->e.getEventType().equals("simz1NativeDecision")&&"GO".equals(e.getAttributes().get("decision"))&&"false".equals(e.getAttributes().get("nativeHasGreen"))),"Preauthorized passage crossed actual native red");}
        if(activityPassage)require(observed.stream().anyMatch(e->e.getEventType().equals("simz1OccupancyReservation")&&"activity_requires_empty_model_slot".equals(e.getAttributes().get("reason"))&&e.getAttributes().containsKey("passageLinks")),"Missing explicit candidate passage on rejected activity receipt");
        System.out.println("PASS native QSim lanes="+lanes+" passage="+passage+" boundaryExit="+boundaryExit+" interiorReceipt="+interiorReceipt+" passagePriority="+passagePriority+" rejectedPrefix="+rejectedPrefix+" earlyTurn="+earlyTurn+" signalWindow="+signalWindow+" activityPassage="+activityPassage+", 12 mixed bodies, activity rejection, short links, slow leader, complete ledger; evidence="+out);
    }
    public static void main(String[] args) throws Exception {
        if(args.length==1&&args[0].equals("reroute-revisit")){
            Zona1Logging.configure();qsimFixture(true,false,false,false,false,false,false,false,false,true);return;
        }
        qsimFixture(true,false,false,false,false,false,false,false,false,true);
        Zona1Logging.configure();ledgerFixture();rerouteGuardFixture();interiorTurnSlotsFixture();activityBufferPassageFixture();qsimFixture(false);qsimFixture(true);qsimFixture(true,true);qsimFixture(true,true,true,false);qsimFixture(true,false,false,true);ringFixture();qsimFixture(true,true,false,false,true,false);qsimFixture(true,true,false,false,false,true);qsimFixture(true,true,false,false,false,false,true);qsimFixture(true,true,false,false,false,false,false,true);qsimFixture(true,true,false,false,false,false,false,false,true);
        System.out.println("PASS corridor-length-v1: body+0.10m, bus/truck storage, short-link continuity, internal queues, exact fit, clear/abort/arrival and real QSim");
        org.apache.logging.log4j.LogManager.shutdown();
    }
    /** V7's two censored origin actors. The old ceil budget was 25s generic
     * or 24s from the activity buffer. Native floor needs 17s with every +2
     * scheduling margin retained; the tighter window reproduces that defect. */
    static void activityBufferPassageFixture() throws Exception {
        activityBufferPassageFixture(false);
    }
    static void activityBufferPassageFixture(boolean tightWindow) throws Exception {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=scenario.getNetwork();var nf=n.getFactory();
        double[] lengths={4.202513737548575,7.857235806864687,4.257955303480768,4.933572286831278,80};
        double distance=0;for(int i=0;i<6;i++){n.addNode(nf.createNode(Id.createNodeId("n"+i),new Coord(distance,0)));if(i<5)distance+=lengths[i];}
        var signalNode=n.getNodes().get(Id.createNodeId("n4"));
        n.addNode(nf.createNode(Id.createNodeId("south"),new Coord(signalNode.getCoord().getX(),-50)));
        n.addNode(nf.createNode(Id.createNodeId("north"),new Coord(signalNode.getCoord().getX(),50)));
        n.addNode(nf.createNode(Id.createNodeId("merge-south"),new Coord(n.getNodes().get(Id.createNodeId("n2")).getCoord().getX(),-50)));
        for(int i=0;i<5;i++){link(n,"p"+i,"n"+i,"n"+(i+1),lengths[i],i<2?1:2);n.getLinks().get(Id.createLinkId("p"+i)).setFreespeed(i<2?4.166666666666667:11.11111111111111);}
        link(n,"cross-in","south","n4",50,1);link(n,"cross-out","n4","north",50,1);
        // Actual origin joins a two-lane road here: its conflict width makes
        // p1 too short to receive the whole car, extending the same passage.
        link(n,"merge-in","merge-south","n2",50,2);
        n.getNodes().get(Id.createNodeId("n1")).getAttributes().putAttribute("osm:highway","stop");
        signalNode.getAttributes().putAttribute("osm:highway","traffic_signals");
        LanesGenerator.build(scenario);var signals=TrafficLightsGenerator.build(scenario,null);
        for(var control:signals.getSignalControlData().getSignalSystemControllerDataBySystemId().values())for(var plan:control.getSignalPlanData().values()){
            plan.setCycleTime(80);plan.setOffset(0);for(var setting:plan.getSignalGroupSettingsDataByGroupId().values()){
                boolean road=setting.getSignalGroupId().toString().equals("calle");setting.setOnset(road?49:0);setting.setDropping(road?(tightWindow?76:78):47);}}
        double originalTravel=0;for(int i=0;i<4;i++){double speed=n.getLinks().get(Id.createLinkId("p"+i)).getFreespeed();originalTravel+=Math.ceil(.2*lengths[i]/speed)+2+Math.ceil(.8*lengths[i]/speed)+2;}
        close(originalTravel,25,"Regression must reproduce impossible old 25s bound");
        var c=scenario.getConfig();var out=Files.createTempDirectory(Path.of("runtime"),"corridor-activity-buffer-");
        c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setUseLanes(true);
        c.qsim().setStartTime(0);c.qsim().setEndTime(360);c.qsim().setUsingFastCapacityUpdate(false);c.qsim().setRemoveStuckVehicles(false);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);c.travelTimeCalculator().setSeparateModes(false);
        c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var a=new ActivityParams(name);a.setTypicalDuration(3600);a.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(a);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var pf=scenario.getPopulation().getFactory();var vf=scenario.getVehicles().getFactory();
        for(int i=0;i<2;i++){
            String id="activity-car"+i;var type=vf.createVehicleType(Id.create(id,VehicleType.class));type.setLength(4.5).setPcuEquivalents(1).setMaximumVelocity(i==0?13.88888888888889:6.944444444444445).setNetworkMode("car");scenario.getVehicles().addVehicleType(type);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),type);scenario.getVehicles().addVehicle(vehicle);
            var person=pf.createPerson(Id.createPersonId(id));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("p0"));home.setEndTime(1+i);plan.addActivity(home);
            var leg=pf.createLeg("car");var route=RouteUtils.createNetworkRoute(List.of("p0","p1","p2","p3","p4").stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);plan.addLeg(leg);
            plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("p4")));person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controller=new Controler(scenario);RunZona1Simulation.configureSignals(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controller.run();verifyTransactions(events);
        require(events.stream().filter(e->e instanceof PersonArrivalEvent).count()==2,"Activity connector head/follower never admitted");
        require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Activity connector aborted");
        int acquired=0;for(var e:events){var a=e.getAttributes();
            if(e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(a.get("action"))){
                require("p0,p1,p2,p3".equals(a.get("passageLinks")),"Activity origin was not reserved through the complete short prefix");
                close(Double.parseDouble(a.get("passageSignalTraversalSeconds")),17,"Eight queue scheduling margins plus the one native travel tick");
                require(Double.parseDouble(a.get("passageSignalGreenSeconds"))>17,"Insufficient actual green deadline");acquired++;}
            if(e.getEventType().equals("simz1NativeDecision")&&"GO".equals(a.get("decision")))require(!"false".equals(a.get("nativeHasGreen")),"Activity passage crossed native red");
            if(e instanceof LinkLeaveEvent leave&&leave.getLinkId().toString().equals("p3")){double phase=e.getTime()%80;require(phase>=49&&phase<(tightWindow?72:74),"Native crossing missed actual green");}
        }
        require(acquired==2,"Missing activity origin reservations");
        System.out.println("PASS native activity buffer origin: floor-based budget17s retains all scheduling/debt margins, Normal+Tortuga arrive, all native GO green and reservations released; tightWindow="+tightWindow+"; evidence="+out);
    }
    /** Two-lane OSM subdivisions with explicit, different native turn slots.
     * The old endpoint-only lookup rejected the legal U-turn on an empty road. */
    static void interiorTurnSlotsFixture() throws Exception {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=scenario.getNetwork();var f=n.getFactory();
        for(int i=0;i<5;i++)n.addNode(f.createNode(Id.createNodeId("n"+i),new Coord(i*40,0)));
        for(int i=0;i<4;i++)for(int reverse=0;reverse<2;reverse++)
            link(n,"l"+i+(reverse==0?"f":"r"),"n"+(i+reverse),"n"+(i+1-reverse),40,2);
        n.getNodes().get(Id.createNodeId("n3")).getAttributes().putAttribute("osm:highway","stop");
        LanesGenerator.build(scenario);
        // First subdivision: slot0 straight, slot1 U-turn. Second subdivision:
        // slot1 U-turn only, so continuing then turning requires a prohibited
        // lateral reassignment and must never be admitted in a frozen slot.
        var assignments=scenario.getLanes().getLanesToLinkAssignments();
        assignments.get(Id.createLinkId("l0f")).getLanes().get(Id.create("l0f.lane.0",org.matsim.lanes.Lane.class)).getToLinkIds().remove(Id.createLinkId("l0r"));
        assignments.get(Id.createLinkId("l0f")).getLanes().get(Id.create("l0f.lane.1",org.matsim.lanes.Lane.class)).getToLinkIds().remove(Id.createLinkId("l1f"));
        assignments.get(Id.createLinkId("l1f")).getLanes().get(Id.create("l1f.lane.0",org.matsim.lanes.Lane.class)).getToLinkIds().remove(Id.createLinkId("l1r"));
        var config=scenario.getConfig();var out=Files.createTempDirectory(Path.of("runtime"),"corridor-interior-turn-slots-");
        config.controler().setOutputDirectory(out.resolve("run").toString());config.controler().setLastIteration(0);
        config.global().setNumberOfThreads(1);config.qsim().setNumberOfThreads(1);config.qsim().setUseLanes(true);
        config.qsim().setStartTime(0);config.qsim().setEndTime(180);config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);config.qsim().setRemoveStuckVehicles(false);
        config.travelTimeCalculator().setSeparateModes(false);config.controler().setLinkToLinkRoutingEnabled(true);config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);config.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),EventsUtils.createEventsManager());
        require(ledger.corridorId(Id.createLinkId("l0f")).equals(ledger.corridorId(Id.createLinkId("l2f"))),"Fixture did not group forward subdivisions");
        var rejectedLeg=scenario.getPopulation().getFactory().createLeg("car");
        rejectedLeg.setRoute(RouteUtils.createNetworkRoute(List.of("l0f","l1f","l1r").stream().map(Id::createLinkId).toList(),n));
        var rejectedDriver=Proxy.newProxyInstance(org.matsim.core.mobsim.framework.PlanAgent.class.getClassLoader(),
            new Class[]{org.matsim.core.mobsim.framework.PlanAgent.class,org.matsim.core.mobsim.framework.MobsimDriverAgent.class},
            (p,m,a)->{if(m.getName().equals("getCurrentPlanElement"))return rejectedLeg;throw new AssertionError(m);});
        var body=vehicle("incompatibleInterior",4.5);
        var rejected=(QVehicle)Proxy.newProxyInstance(QVehicle.class.getClassLoader(),new Class[]{QVehicle.class},(p,m,a)->switch(m.getName()){
            case "getDriver"->rejectedDriver;case "getId"->body.getId();case "getVehicle"->body.getVehicle();default->throw new AssertionError(m);});
        require(!ledger.canEnter(rejected,Id.createLinkId("l0f"),"l0f.original",0),"Admitted a route requiring an unmodeled interior lane change");
        var pf=scenario.getPopulation().getFactory();var vf=scenario.getVehicles().getFactory();
        for(int i=0;i<4;i++){
            var name=List.of("bus","truck","car","motorcycle").get(i);var type=vf.createVehicleType(Id.create(name,VehicleType.class));
            type.setLength(new double[]{13.5,12,4.5,2.1}[i]).setPcuEquivalents(new double[]{3,3.5,1,.25}[i]).setMaximumVelocity(10).setNetworkMode("car");scenario.getVehicles().addVehicleType(type);
            var v=VehicleUtils.createVehicle(Id.createVehicleId(name),type);scenario.getVehicles().addVehicle(v);
            var person=pf.createPerson(Id.createPersonId(name));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",v.getId()));
            var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("l0f"));home.setEndTime(1+i);plan.addActivity(home);
            var leg=pf.createLeg("car");var route=RouteUtils.createNetworkRoute(List.of(Id.createLinkId("l0f"),Id.createLinkId("l0r")),n);route.setVehicleId(v.getId());leg.setRoute(route);plan.addLeg(leg);
            plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("l0r")));person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        var events=new ArrayList<Event>();var controller=new Controler(scenario);UnsignalizedPriority.configure(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controller.run();verifyTransactions(events);
        require(events.stream().filter(e->e instanceof PersonArrivalEvent).count()==4,"Legal interior U-turn left a mixed body stuck");
        require(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Interior U-turn aborted");
        require(events.stream().noneMatch(e->e instanceof LinkEnterEvent l&&Set.of("l1f","l2f").contains(l.getLinkId().toString())),"Visited an unplanned corridor tail");
        int entered=0;for(var e:events){var a=e.getAttributes();if(e.getEventType().equals("simz1OccupancyReservation")&&"ENTER".equals(a.get("action"))&&"l0f".equals(a.get("link"))){
            require("1".equals(a.get("modelSlot")),"Early turn assigned to forbidden slot0");entered++;}}
        require(entered==4,"Missing complete mixed-fleet reservations for interior turn");
        System.out.println("PASS native two-lane interior U-turn: four bodies complete via slot1, unvisited tail ignored, incompatible interior-slot route rejected; evidence="+out);
    }
    static void rerouteGuardFixture(){
        var scenario=scenario();for(String id:List.of("origin","short"))scenario.getNetwork().getLinks().get(Id.createLinkId(id)).setNumberOfLanes(2);
        LanesGenerator.build(scenario);
        var assignment=scenario.getLanes().getLanesToLinkAssignments().get(Id.createLinkId("short"));
        var lane=assignment.getLanes().values().stream().filter(l->l.getId().toString().equals("short.lane.0")).findFirst().orElseThrow();
        lane.getToLinkIds().remove(Id.createLinkId("branch")); // explicit fixture: slot0 is straight-only
        var ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),EventsUtils.createEventsManager());SimZ1CorridorOccupancy.install(scenario.getConfig().qsim(),ledger);
        var car=vehicle("rerouteCar",4.5);require(ledger.activity(car,Id.createLinkId("origin"),"origin.original",1),"Reroute fixture admission");
        String incompatible=List.of("out","branch").stream().filter(id->!lane.getToLinkIds().contains(Id.createLinkId(id))).findFirst().orElseThrow();
        String compatible=lane.getToLinkIds().get(0).toString();
        var accepted=List.of("origin","short",compatible).stream().map(Id::createLinkId).toList();
        require(SimZ1CorridorOccupancy.replacementIssue(scenario.getConfig().qsim(),car.getId(),accepted,0)==null,"Rejected compatible reservation-aware reroute");
        var rejected=List.of("origin","short",incompatible).stream().map(Id::createLinkId).toList();
        require("occupancy_reserved_terminal_slot".equals(SimZ1CorridorOccupancy.replacementIssue(scenario.getConfig().qsim(),car.getId(),rejected,0)),"Reroute can invalidate frozen model slot");
        ledger.release(car.getId(),2,"arrival");SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());
    }
    static void ringFixture() throws Exception {
        var config=ConfigUtils.createConfig();var out=Files.createTempDirectory(Path.of("runtime"),"corridor-ring-");
        config.controler().setOutputDirectory(out.resolve("run").toString());config.controler().setLastIteration(0);
        config.global().setNumberOfThreads(1);config.qsim().setNumberOfThreads(1);config.qsim().setUseLanes(true);
        config.qsim().setStartTime(0);config.qsim().setEndTime(180);config.qsim().setUsingFastCapacityUpdate(false);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);config.qsim().setRemoveStuckVehicles(false);
        config.travelTimeCalculator().setSeparateModes(false);config.controler().setLinkToLinkRoutingEnabled(true);config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);config.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(config,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var scenario=ScenarioUtils.createScenario(config);var n=scenario.getNetwork();
        for(int i=0;i<6;i++){var node=n.getFactory().createNode(Id.createNodeId("n"+i),new Coord(100*Math.cos(i*Math.PI/3),100*Math.sin(i*Math.PI/3)));n.addNode(node);
            if(i%2==1)node.getAttributes().putAttribute("osm:highway","traffic_signals");}
        for(int i=0;i<3;i++){link(n,"long"+i,"n"+(2*i),"n"+(2*i+1),100,1);link(n,"connector"+i,"n"+(2*i+1),"n"+((2*i+2)%6),6,1);}
        var f=scenario.getPopulation().getFactory();var type=scenario.getVehicles().getFactory().createVehicleType(Id.create("rigid",VehicleType.class));
        type.setLength(13.5).setPcuEquivalents(3).setMaximumVelocity(10).setNetworkMode("car");scenario.getVehicles().addVehicleType(type);
        for(int i=0;i<3;i++){var vehicle=VehicleUtils.createVehicle(Id.createVehicleId("ringBus"+i),type);scenario.getVehicles().addVehicle(vehicle);
            var person=f.createPerson(Id.createPersonId(vehicle.getId()));VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle.getId()));
            var plan=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("long"+i));home.setEndTime(1);plan.addActivity(home);
            var leg=f.createLeg("car");var path=List.of("long"+i,"connector"+i,"long"+((i+1)%3),"connector"+((i+1)%3),"long"+((i+2)%3));
            var route=RouteUtils.createNetworkRoute(path.stream().map(Id::createLinkId).toList(),n);route.setVehicleId(vehicle.getId());leg.setRoute(route);plan.addLeg(leg);
            plan.addActivity(f.createActivityFromLinkId("work",Id.createLinkId(path.get(4))));person.addPlan(plan);scenario.getPopulation().addPerson(person);}
        LanesGenerator.build(scenario);var events=new ArrayList<Event>();var controller=new Controler(scenario);UnsignalizedPriority.configure(controller);
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)events::add);}});controller.run();verifyTransactions(events);
        require(events.stream().filter(e->e instanceof PersonArrivalEvent).count()==3,"Artificial empty-receiver cycle: three buses with ~80m free each");
        var capacities=new HashMap<String,Double>();boolean occupiedReceipt=false;
        for(var e:events){var a=e.getAttributes();if(e.getEventType().equals("simz1OccupancyDomain"))capacities.put(a.get("corridor"),Double.parseDouble(a.get("laneCapacityMeters")));
            if(e.getEventType().equals("simz1OccupancyPassage")&&"ACQUIRE".equals(a.get("action"))&&a.containsKey("receiptFreeFrontMeters")){
                double free=Double.parseDouble(a.get("receiptFreeFrontMeters"));require(free+1e-8>=Double.parseDouble(a.get("clearanceFrontMeters")),"Unproved receiving interval");
                occupiedReceipt|=free<capacities.get(a.get("corridor"))-1e-8;}}
        require(occupiedReceipt,"Ring did not exercise an occupied but physically free receipt");
        System.out.println("PASS native three-bus 100m/6m ring: occupied receivers with proved free entry interval, no artificial empty-receiver deadlock; evidence="+out);
    }
}
