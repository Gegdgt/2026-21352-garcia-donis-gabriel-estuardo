package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.pt.TransitStopHandlerFactory;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.vehicles.*;
import gt.edu.uvg.sim.zona1.*;

/** Actual native transit stop + private followers + a 3.5m red terminal queue.
 * Forty-second dwell is a fixture assumption; no passengers are synthesized. */
public final class SimZ1BlockingStopCheck {
    private static void require(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    public static void main(String[] args)throws Exception {
        if(args.length>0&&args[0].startsWith("incident")) {
            try {
                if(args[0].equals("incident-free-bus"))incidentFreeBus();
                else {
                    if(!args[0].equals("incident-blocking"))incident(false);
                    if(!args[0].equals("incident-nonblocking"))incident(true);
                }
            } finally {org.apache.logging.log4j.LogManager.shutdown();}
            return;
        }
        incident(false);incident(true);incidentFreeBus();
        Zona1Logging.configure();var out=Files.createTempDirectory(Path.of("runtime"),"corridor-blocking-stop-");
        var c=ConfigUtils.createConfig();c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
        c.transit().setUseTransit(true);c.qsim().setMainModes(Set.of("car"));c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);
        c.qsim().setUseLanes(true);c.qsim().setStartTime(0);c.qsim().setEndTime(240);c.qsim().setRemoveStuckVehicles(false);c.qsim().setUsingFastCapacityUpdate(false);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);c.travelTimeCalculator().setSeparateModes(false);
        c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);
        for(String name:List.of("home","work")){var p=new ActivityParams(name);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(p);}
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();
        for(var e:Map.of("o",new Coord(-200,0),"a",new Coord(-100,0),"j",new Coord(0,0),"d",new Coord(100,0),"south",new Coord(0,-100),"north",new Coord(0,100)).entrySet())
            n.addNode(n.getFactory().createNode(Id.createNodeId(e.getKey()),e.getValue()));
        SimZ1CorridorOccupancyCheck.link(n,"origin","o","a",100,1);SimZ1CorridorOccupancyCheck.link(n,"approach","a","j",100,1);
        SimZ1CorridorOccupancyCheck.link(n,"exit","j","d",100,1);SimZ1CorridorOccupancyCheck.link(n,"cross-in","south","j",100,1);SimZ1CorridorOccupancyCheck.link(n,"cross-out","j","north",100,1);
        n.getNodes().get(Id.createNodeId("a")).getAttributes().putAttribute("osm:highway","stop");
        n.getNodes().get(Id.createNodeId("j")).getAttributes().putAttribute("osm:highway","traffic_signals");
        LanesGenerator.build(s);
        // Same native lane IDs/turns/flow; original queue ends at the stop line.
        var assignment=s.getLanes().getLanesToLinkAssignments().get(Id.createLinkId("approach"));
        for(var lane:assignment.getLanes().values())if(lane.getToLinkIds()!=null&&!lane.getToLinkIds().isEmpty())lane.setStartsAtMeterFromLinkEnd(3.5);
        var signals=TrafficLightsGenerator.build(s,null);
        for(var control:signals.getSignalControlData().getSignalSystemControllerDataBySystemId().values())for(var plan:control.getSignalPlanData().values()){
            plan.setCycleTime(180);plan.setOffset(0);
            for(var setting:plan.getSignalGroupSettingsDataByGroupId().values()){
                boolean road=setting.getSignalGroupId().toString().equals("calle");setting.setOnset(road?100:0);setting.setDropping(road?150:90);}}
        var pf=s.getPopulation().getFactory();var path=List.of("origin","approach","exit").stream().map(Id::createLinkId).toList();
        for(int i=0;i<2;i++){
            String id=i==0?"following-car":"following-motorcycle";var vt=s.getVehicles().getFactory().createVehicleType(Id.create(id,VehicleType.class));
            vt.setLength(i==0?4.5:2.1).setPcuEquivalents(i==0?1:.25).setMaximumVelocity(10).setNetworkMode("car");s.getVehicles().addVehicleType(vt);
            var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),vt);s.getVehicles().addVehicle(vehicle);
            var p=pf.createPerson(Id.createPersonId(id));VehicleUtils.insertVehicleIdsIntoAttributes(p,Map.of("car",vehicle.getId()));var plan=pf.createPlan();
            var home=pf.createActivityFromLinkId("home",path.get(0));home.setEndTime(5+i*3);plan.addActivity(home);var leg=pf.createLeg("car");
            var route=RouteUtils.createNetworkRoute(path,n);route.setVehicleId(vehicle.getId());leg.setRoute(route);plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",path.get(2)));p.addPlan(plan);s.getPopulation().addPerson(p);
        }
        var vf=s.getTransitVehicles().getFactory();var busType=vf.createVehicleType(Id.create("fixture-bus",VehicleType.class));busType.setNetworkMode("car").setLength(13.5).setWidth(2.5).setPcuEquivalents(3).setMaximumVelocity(10);busType.getCapacity().setSeats(20);s.getTransitVehicles().addVehicleType(busType);
        var bus=vf.createVehicle(Id.createVehicleId("blocking-bus"),busType);s.getTransitVehicles().addVehicle(bus);
        var schedule=s.getTransitSchedule();var sf=schedule.getFactory();var stops=new ArrayList<TransitRouteStop>();
        for(int i=0;i<3;i++){
            var facility=sf.createTransitStopFacility(Id.create("stop"+i,TransitStopFacility.class),new Coord(i==0?-101:i==1?-3.5:100,0),i==1);facility.setLinkId(path.get(i));schedule.addStopFacility(facility);
            var stop=sf.createTransitRouteStop(facility,i==0?0:i==1?20:80,i==0?0:i==1?60:80);stop.setAwaitDepartureTime(false);stops.add(stop);
        }
        var route=sf.createTransitRoute(Id.create("route",TransitRoute.class),RouteUtils.createNetworkRoute(path,n),stops,"bus");
        var departure=sf.createDeparture(Id.create("departure",Departure.class),0);departure.setVehicleId(bus.getId());route.addDeparture(departure);
        var line=sf.createTransitLine(Id.create("line",TransitLine.class));line.addRoute(route);schedule.addTransitLine(line);
        TransitStopHandlerFactory dwell=vehicle->{var first=new HashMap<Id<TransitStopFacility>,Double>();return (stop,now,leaving,entering,access,v)->{
            require(leaving.isEmpty()&&entering.isEmpty(),"Fixture invented passengers");double start=first.computeIfAbsent(stop.getId(),key->now);return Math.min(1,Math.max(0,start+(stop.getId().toString().equals("stop1")?40:0)-now));};};
        var observed=new ArrayList<Event>();var controller=new Controler(s);RunZona1Simulation.configureSignals(controller);
        controller.addOverridingQSimModule(new AbstractQSimModule(){protected void configureQSim(){bind(TransitStopHandlerFactory.class).toInstance(dwell);}});
        controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance((BasicEventHandler)observed::add);}});controller.run();
        SimZ1CorridorOccupancyCheck.verifyTransactions(observed);
        double stopArrival=observed.stream().filter(e->e.getEventType().equals("VehicleArrivesAtFacility")&&"stop1".equals(e.getAttributes().get("facility"))).mapToDouble(Event::getTime).findFirst().orElseThrow();
        double stopDeparture=observed.stream().filter(e->e.getEventType().equals("VehicleDepartsAtFacility")&&"stop1".equals(e.getAttributes().get("facility"))).mapToDouble(Event::getTime).findFirst().orElseThrow();
        require(stopDeparture-stopArrival>=40,"Native blocking dwell missing");
        for(String follower:List.of("following-car","following-motorcycle")){
            double entered=observed.stream().filter(e->e instanceof LinkEnterEvent v&&v.getVehicleId().toString().equals(follower)&&v.getLinkId().toString().equals("approach")).mapToDouble(Event::getTime).findFirst().orElseThrow();
            require(entered>=stopArrival&&entered<stopDeparture,"Follower could not form a queue during bus dwell: "+follower+" entered="+entered+", dwell="+stopArrival+".."+stopDeparture);
        }
        for(var e:observed)if(e instanceof LinkLeaveEvent v&&v.getLinkId().toString().equals("approach"))require(e.getTime()>=100,"Short terminal ignored red or cut through intersection");
        require(observed.stream().filter(e->e instanceof PersonArrivalEvent).count()>=2,"Road followers did not arrive");
        require(observed.stream().anyMatch(e->e instanceof VehicleLeavesTrafficEvent v&&v.getVehicleId().equals(bus.getId())),"Native bus did not finish");
        require(observed.stream().noneMatch(e->e instanceof PersonStuckEvent),"Fixture aborted a vehicle");
        System.out.println("PASS actual blocking transit stop: 40s dwell, car+moto queued behind, 3.5m terminal held red until100s, all vehicles finish; evidence="+out);
        org.apache.logging.log4j.LogManager.shutdown();
    }

    /** Run10K ordering seam. Real queues, lane split, reservation ledger and
     * TransitQLink execute the stop. A small fixture driver supplies a planned
     * route and invokes the production 25-second assumed dwell handler; it does
     * not emit facility events or invent native arrivals. The Controller case
     * above separately owns real transit-agent/event lifecycle coverage.
     *
     * Incident link/queue lengths, lane count, speeds, capacities and bus body
     * are copied from the effective Run10K inputs. The downstream branch is a
     * synthetic fixture constraint that commits unchanged model slots, not an
     * alteration of the historical scenario. No signal is red or even present.
     */
    private static final class IncidentFixture implements AutoCloseable {
        static final String ROAD="osm_1057486080_1_forward",RECEIVER="osm_1057486080_2_forward";
        final org.matsim.api.core.v01.Scenario scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        final org.matsim.core.api.experimental.events.EventsManager manager=org.matsim.core.events.EventsUtils.createEventsManager();
        final org.matsim.core.mobsim.framework.MobsimTimer timer=new org.matsim.core.mobsim.framework.MobsimTimer(1);
        final List<Event> events=new ArrayList<>();
        final SimZ1CorridorOccupancy ledger;
        final QLinkLanesImpl nativeLink;
        final QueueWithBuffer original,blockedTerminal,freeTerminal;
        final List<QVehicle> actors=new ArrayList<>();
        final TransitStopFacility stop;
        double stopArrival=Double.NaN,stopDeparture=Double.NaN;
        final List<String> bufferAtStopArrival=new ArrayList<>();
        boolean stopDone;

        IncidentFixture(boolean blocking) {
            var config=scenario.getConfig().qsim();config.setUseLanes(true);config.setUsingFastCapacityUpdate(false);
            config.setRemoveStuckVehicles(false);config.setNumberOfThreads(1);config.setNodeOffset(0);
            config.setTimeStepSize(1);config.setTrafficDynamics(QSimConfigGroup.TrafficDynamics.queue);
            manager.addHandler((BasicEventHandler)events::add);
            var network=scenario.getNetwork();var nf=network.getFactory();
            for(int i=0;i<6;i++)network.addNode(nf.createNode(Id.createNodeId(i),new Coord(i<3?i*100:300,(i-3)*100)));
            road(ROAD,"0","1",78.84125001045511,3);road(RECEIVER,"1","2",100,3);
            for(int slot=0;slot<3;slot++)road("exit"+slot,"2",Integer.toString(slot+3),100,1);
            lanes(ROAD,2,false);lanes(RECEIVER,20,true);
            stop=scenario.getTransitSchedule().getFactory().createTransitStopFacility(
                Id.create("gis_station_41_L12_14106867_part1",TransitStopFacility.class),new Coord(76.84125001045511,0),blocking);
            stop.setLinkId(Id.createLinkId(ROAD));stop.getAttributes().putAttribute("simz1:dwellSeconds","25.0");
            stop.getAttributes().putAttribute("simz1:stopOccupancyBasis","scenario_blocking_native_queue_not_microscopic_lane");
            ledger=new SimZ1CorridorOccupancy(scenario,Set.of(),manager);ledger.emitDomains(0);
            var engine=new QNetsimEngineI.NetsimInternalInterface(){
                public QNetwork getNetsimNetwork(){throw new AssertionError("No node crossing in internal-split fixture");}
                public void arrangeNextAgentState(org.matsim.core.mobsim.framework.MobsimAgent agent){throw new AssertionError("No forced state change");}
                public void letVehicleArrive(QVehicle vehicle){throw new AssertionError("No fabricated arrival");}
            };
            var context=new NetsimEngineContext(manager,7.5,null,null,config,timer,null);
            var road=network.getLinks().get(Id.createLinkId(ROAD));
            nativeLink=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(road,null,
                org.matsim.lanes.LanesUtils.createLanes(road,scenario.getLanes().getLanesToLinkAssignments().get(road.getId())));
            nativeLink.setNetElementActivationRegistry(new NetElementActivationRegistry(){
                void registerNodeAsActive(QNodeI n){}void registerLinkAsActive(QLinkI l){}
                int getNumberOfSimulatedNodes(){return 0;}int getNumberOfSimulatedLinks(){return 1;}
            });
            original=queue(".original");blockedTerminal=queue(".lane.1");freeTerminal=queue(".lane.0");
            SimZ1CorridorOccupancy.install(config,ledger);
        }
        private void road(String id,String from,String to,double length,int count) {
            var network=scenario.getNetwork();var road=network.getFactory().createLink(Id.createLinkId(id),network.getNodes().get(Id.createNodeId(from)),network.getNodes().get(Id.createNodeId(to)));
            road.setLength(length);road.setNumberOfLanes(count);road.setCapacity(2000*count);road.setFreespeed(11.11111111111111);road.setAllowedModes(Set.of("car","bus"));network.addLink(road);
        }
        private void lanes(String linkId,double terminalLength,boolean branch) {
            var road=scenario.getNetwork().getLinks().get(Id.createLinkId(linkId));var factory=scenario.getLanes().getFactory();
            var assignment=factory.createLanesToLinkAssignment(road.getId());var original=factory.createLane(Id.create(linkId+".original",org.matsim.lanes.Lane.class));
            original.setStartsAtMeterFromLinkEnd(road.getLength());original.setNumberOfRepresentedLanes(3);original.setCapacityVehiclesPerHour(6000);
            for(int slot=0;slot<3;slot++){
                var lane=factory.createLane(Id.create(linkId+".lane."+slot,org.matsim.lanes.Lane.class));lane.setStartsAtMeterFromLinkEnd(terminalLength);
                lane.setNumberOfRepresentedLanes(1);lane.setCapacityVehiclesPerHour(2000);lane.addToLinkId(Id.createLinkId(branch?"exit"+slot:RECEIVER));
                assignment.addLane(lane);original.addToLaneId(lane.getId());
            }
            assignment.addLane(original);scenario.getLanes().addLanesToLinkAssignment(assignment);
        }
        QueueWithBuffer queue(String suffix){return (QueueWithBuffer)nativeLink.getQueueLanes().get(Id.create(ROAD+suffix,org.matsim.lanes.Lane.class));}
        QVehicle actor(String name,double body,int slot,boolean bus) {
            var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
            type.setLength(body).setWidth(bus?2.5:body==2.1?.8:1.8).setPcuEquivalents(bus?3:body==2.1?.25:1).setMaximumVelocity(13.88888888888889).setNetworkMode(bus?"bus":"car");
            var vehicle=new QVehicleImpl(VehicleUtils.createVehicle(Id.createVehicleId(name),type));
            var leg=scenario.getPopulation().getFactory().createLeg("car");
            leg.setRoute(RouteUtils.createNetworkRoute(List.of(ROAD,RECEIVER,"exit"+slot).stream().map(Id::createLinkId).toList(),scenario.getNetwork()));
            var dwell=new SimZ1TransitFleet.AssumedDwell();
            Class<?> driver=bus?org.matsim.core.mobsim.qsim.pt.TransitDriverAgent.class:org.matsim.core.mobsim.framework.MobsimDriverAgent.class;
            vehicle.setDriver((org.matsim.core.mobsim.framework.MobsimDriverAgent)java.lang.reflect.Proxy.newProxyInstance(
                org.matsim.core.mobsim.framework.PlanAgent.class.getClassLoader(),new Class<?>[]{org.matsim.core.mobsim.framework.PlanAgent.class,driver},(proxy,method,args)->switch(method.getName()){
                    case "getId"->Id.createPersonId(name);case "getMode"->"car";case "getCurrentPlanElement"->leg;
                    case "getCurrentLinkId"->Id.createLinkId(ROAD);case "chooseNextLinkId"->Id.createLinkId(RECEIVER);
                    case "isWantingToArriveOnCurrentLink"->false;case "getNextTransitStop"->stopDone?null:stop;
                    case "handleTransitStop"->{
                        double now=(double)args[1];if(Double.isNaN(stopArrival)){
                            stopArrival=now;
                            for(var pair:(Iterable<?>)SimZ1StorageFixture.field(original,"buffer"))
                                bufferAtStopArrival.add(((QVehicle)((org.apache.commons.lang3.tuple.Pair<?,?>)pair).getKey()).getId().toString());
                        }
                        double delay=dwell.handleTransitStop(stop,now,List.of(),List.of(),null,vehicle);
                        if(delay==0){stopDone=true;stopDeparture=now;}yield delay;
                    }
                    default->throw new AssertionError("Unexpected fixture driver call "+method);
                }));
            actors.add(vehicle);return vehicle;
        }
        void seed(QVehicle vehicle,QueueWithBuffer queue,double now){
            timer.setTime(now);String where=vehicle.getId()+" at "+now+" in "+queue.getId();
            require(queue.isAcceptingFromUpstream(),"Fixture insertion lacks native receiving storage: "+where);
            require(ledger.canEnter(vehicle,Id.createLinkId(ROAD),queue.getId().toString(),now),"Fixture insertion lacks body reservation: "+where);
            queue.addFromUpstream(vehicle);
        }
        void ready(double now){timer.setTime(now);original.initBeforeSimStep();original.doSimStep();}
        void split(double now)throws Exception {
            timer.setTime(now);var method=QLinkLanesImpl.class.getDeclaredMethod("moveBufferToNextLane",QLaneI.class);method.setAccessible(true);method.invoke(nativeLink,original);
        }
        void bodySafety()throws Exception {
            var active=(Map<?,?>)SimZ1StorageFixture.field(ledger,"active");
            for(var vehicle:actors){
                var r=active.get(vehicle.getId());require(r!=null,"Fixture lost body reservation");
                SimZ1StorageFixture.near((double)SimZ1StorageFixture.field(r,"footprint"),vehicle.getVehicle().getType().getLength()+.1,"Body/gap changed");
                var domain=SimZ1StorageFixture.field(r,"domain");int slot=(int)SimZ1StorageFixture.field(r,"slot");
                var reservations=(List<?>)SimZ1StorageFixture.field(domain,"reservations");Object leader=null;
                for(var entry:((NavigableMap<?,?>)reservations.get(slot)).values()){
                    if(leader!=null)require((double)SimZ1StorageFixture.field(entry,"frontBound")<=(double)SimZ1StorageFixture.field(leader,"frontBound")-(double)SimZ1StorageFixture.field(leader,"footprint")+1e-8,"Native body overlap or same-slot overtake");leader=entry;
                }
            }
        }
        public void close(){SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());}
    }

    private static void incident(boolean blocking)throws Exception {
        try(var f=new IncidentFixture(blocking)){
            var terminalPredecessor=f.actor("terminal-predecessor",4.5,1,false);
            var retained=f.actor("retained-original-predecessor",4.5,1,false);
            var bus=f.actor("ptbus_transmetro_L12_006",13.5,1,true);
            var follower=f.actor("z1_05698",2.1,0,false);
            f.seed(terminalPredecessor,f.blockedTerminal,0);f.seed(retained,f.original,1);
            double headReady=retained.getEarliestLinkExitTime();f.ready(headReady);
            require(f.original.getFirstVehicle()==retained,"Retained predecessor did not reach native buffer");
            f.seed(bus,f.original,headReady+1);f.seed(follower,f.original,headReady+2);
            double ready=Math.max(bus.getEarliestLinkExitTime(),follower.getEarliestLinkExitTime());f.ready(ready);
            require(f.stopArrival==ready,"Real TransitQLink did not start fixture dwell in the selected tick");
            require(f.ledger.originalSlot(bus,Id.createLinkId(IncidentFixture.ROAD),f.original.getId().toString())==1,"Bus slot changed");
            require(f.ledger.originalSlot(follower,Id.createLinkId(IncidentFixture.ROAD),f.original.getId().toString())==0,"Follower slot changed");
            require(!f.blockedTerminal.isAcceptingFromUpstream()&&f.freeTerminal.isAcceptingFromUpstream(),"Fixture receiver conditions do not isolate the stop");
            System.out.println("INCIDENT_NATIVE_ORDER blocking="+blocking+" dwellStart="+f.stopArrival+" bufferBeforeNativeStopHandling="+f.bufferAtStopArrival+" attempt="+(ready+1));
            f.split(ready+1);f.bodySafety();
            boolean moved=f.freeTerminal.getVehicle(follower.getId())==follower;
            if(!blocking){
                require(moved,"Nonblocking stop incorrectly imprisons an independent physical slot");
                System.out.println("PASS native incident nonblocking control: free receiver, no red, follower leaves original at dwell+1; dwellStart="+f.stopArrival);return;
            }
            require(!moved,"RUN10K_BLOCKING_STOP_BYPASS: later follower exited original at dwell+1 while bus remains in native blocking stop");
            require(!f.bufferAtStopArrival.contains(follower.getId().toString()),"Later follower was buffered before earlier blocking bus began dwell in the same tick");
            for(int second=1;second<=25;second++){
                f.ready(ready+second);f.split(ready+second);f.bodySafety();
                if(second<25)require(f.freeTerminal.getVehicle(follower.getId())==null,"Follower passed during blocking dwell");
            }
            require(f.stopDeparture==f.stopArrival+25,"Production assumed dwell duration changed");
            for(int second=26;second<=35&&f.freeTerminal.getVehicle(follower.getId())==null;second++){f.ready(ready+second);f.split(ready+second);f.bodySafety();}
            require(f.freeTerminal.getVehicle(follower.getId())==follower,"Follower cannot move legitimately after bus departure");
            require(f.original.getFirstVehicle()==retained,"Independent movement bypassed or removed older same-slot predecessor");
            require(f.events.stream().noneMatch(e->e instanceof LinkLeaveEvent||e instanceof PersonArrivalEvent||e instanceof PersonStuckEvent),"Fixture fabricated node crossing/arrival/removal");
            System.out.println("PASS native incident blocking control: 25s dwell, attempt+1 held, departure releases independent slot, original predecessor and body/gap reservations retained; dwell="+f.stopArrival+".."+f.stopDeparture);
        }
    }

    /** A pending stop bars actors behind the bus, not the eligible bus itself.
     * Two real one-PCU buffer grants produce native negative flow credit;
     * neither flow counters nor body ownership are injected by this control. */
    private static void incidentFreeBus()throws Exception {
        try(var f=new IncidentFixture(true)){
            var terminal=f.actor("terminal-predecessor",4.5,1,false);
            var retained=f.actor("retained-original-predecessor",4.5,1,false);
            var retainedSecond=f.actor("retained-original-second",4.5,1,false);
            var travelling=f.actor("earlier-travelling-same-slot",4.5,1,false);
            var bus=f.actor("eligible-independent-blocking-bus",13.5,2,true);
            var follower=f.actor("later-motorcycle",2.1,0,false);
            f.seed(terminal,f.blockedTerminal,0);f.seed(retained,f.original,1);
            f.ready(retained.getEarliestLinkExitTime());
            // The first body must actually advance before admitting another
            // body into the same slot's entrance. Retain its real flow grant.
            f.seed(retainedSecond,f.original,f.timer.getTimeOfDay()+1);
            double headReady=retainedSecond.getEarliestLinkExitTime();f.ready(headReady);
            require((double)SimZ1StorageFixture.field(SimZ1StorageFixture.field(f.original,"flowcap_accumulate"),"value")<0,"Control failed to establish native flow debt");
            f.seed(travelling,f.original,headReady+1);f.seed(bus,f.original,headReady+2);f.seed(follower,f.original,headReady+3);
            double ready=follower.getEarliestLinkExitTime();f.ready(ready);
            require(f.stopArrival==ready,"BLOCKING_STOP_GUARD_OVERREACH: first eligible independent bus cannot begin service behind unrelated retained slot");
            require(!f.bufferAtStopArrival.contains(follower.getId().toString()),"Later actor passed pending blocking stop bus");
            for(int second=1;second<25;second++){
                f.split(ready+second);f.ready(ready+second);f.bodySafety();
                require(f.freeTerminal.getVehicle(follower.getId())==null,"Later independent follower escaped active blocking dwell");
            }
            f.ready(ready+25);require(f.stopDeparture==ready+25,"Eligible independent bus dwell did not end natively");
            for(int second=26;second<=35&&f.freeTerminal.getVehicle(follower.getId())==null;second++){f.split(ready+second);f.ready(ready+second);f.bodySafety();}
            require(f.freeTerminal.getVehicle(follower.getId())==follower,"Later independent follower remained held after legitimate service completion");
            require(f.original.getFirstVehicle()==retained,"Independent service removed older retained predecessor");
            System.out.println("PASS blocking barrier scope: eligible bus serves independent slot despite earlier held slot; later actor waits through25s dwell; native debt/FIFO/body reservations preserved");
        }
    }
}
