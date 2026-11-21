package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.utils.objectattributes.attributable.Attributable;
import org.matsim.vehicles.*;

/** Six native actors on eight explicitly synthetic links: four private OD
 * classes, one fixed-route freight trip, and one bus with three real stops.
 * No massive preparation, counter-only arrival, or historical reconstruction. */
public final class SimZ1DischargeArrivalCheck {
    private static final ObjectMapper JSON=new ObjectMapper();
    private static final List<String> CHAIN=List.of("e0","eC","eI","i","j","xI","xC","xE");
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private static Id<Link> id(String value){return Id.createLinkId(value);}
    private static void attr(Attributable item,String key,Object value){item.getAttributes().putAttribute("simz1:"+key,value.toString());}
    private static ObjectNode gateway(String anchor,List<String> links,String crossing){
        var row=JSON.createObjectNode();row.put("id",anchor+"-gateway");row.put("anchor_link",anchor);
        row.put("observation_link",anchor.equals("e0")?"eI":"xI");row.put("crossing_link",crossing);row.set("link_ids",JSON.valueToTree(links));return row;
    }
    private static Object installSyntheticOd(Scenario scenario)throws Exception {
        var spatial=JSON.createObjectNode();spatial.put("mode","balanced-gateway-v1");
        spatial.set("allowed_links",JSON.valueToTree(CHAIN));spatial.set("internal_links",JSON.valueToTree(List.of("i","j")));
        spatial.putObject("internal_origins").putObject("i");
        spatial.putObject("entry_gateways").set("e0",gateway("e0",CHAIN.subList(0,3),"eC"));
        spatial.putObject("exit_gateways").set("xE",gateway("xE",CHAIN.subList(5,8),"xC"));
        // The package constructor is the existing focal-test seam. No prepared
        // manifest is fabricated, and production input loading is not bypassed.
        var cls=Class.forName("gt.edu.uvg.sim.zona1.SimZ1TripOd");var ctor=cls.getDeclaredConstructor(JsonNode.class);ctor.setAccessible(true);
        Object od=ctor.newInstance(spatial);scenario.addScenarioElement(cls.getName(),od);return od;
    }
    private static Person privateTrip(Scenario s,String name,String kind,List<String> path,double departure)throws Exception {
        var pf=s.getPopulation().getFactory();var p=pf.createPerson(Id.createPersonId(name));
        var type=VehicleUtils.createVehicleType(Id.create(name,VehicleType.class));
        type.setLength(4.5).setWidth(1.8).setMaximumVelocity(10).setPcuEquivalents(1).setNetworkMode("car");s.getVehicles().addVehicleType(type);
        var vehicle=VehicleUtils.createVehicle(Id.createVehicleId(name),type);s.getVehicles().addVehicle(vehicle);
        VehicleUtils.insertVehicleIdsIntoAttributes(p,Map.of("car",vehicle.getId()));
        var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",id(path.get(0)));home.setEndTime(departure);plan.addActivity(home);
        var leg=pf.createLeg("car");var route=RouteUtils.createNetworkRoute(path.stream().map(SimZ1DischargeArrivalCheck::id).toList(),s.getNetwork());route.setVehicleId(vehicle.getId());leg.setRoute(route);
        String trip=name+":trip:0001";leg.getAttributes().putAttribute("simz1TripId",trip);plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",id(path.get(path.size()-1))));p.addPlan(plan);s.getPopulation().addPerson(p);
        var record=JSON.createObjectNode();record.put("od_type",kind);record.put("od_class",switch(kind){case "external-external"->"EXTERNAL_EXTERNAL_THROUGH";case "external-internal"->"EXTERNAL_INTERNAL";case "internal-external"->"INTERNAL_EXTERNAL";default->"INTERNAL_INTERNAL";});
        record.put("origin_link",path.get(0));record.put("destination_link",path.get(path.size()-1));
        boolean entry=kind.startsWith("external"),exit=kind.endsWith("external");
        for(String side:List.of("origin","destination")){boolean external=side.equals("origin")?entry:exit;String anchor=side.equals("origin")?"e0":"xE";
            record.put(side+"_gateway",external?anchor:null);record.put(side+"_zone",external?anchor+"-gateway":null);
            record.put(side+"_observation_link",external?(side.equals("origin")?"eI":"xI"):null);}
        record.put("entry_crossing_link",entry?"eC":null);record.put("exit_crossing_link",exit?"xC":null);
        record.put("scope","observed_z1_and_declared_anchors_only");record.putNull("door_to_door_seconds");record.put("metadata_source","simz1-private-gateway-trip-v1");
        record.put("body_length_m",4.5);record.put("minimum_gap_m",.1);record.set("route_link_ids",JSON.valueToTree(path));
        p.getAttributes().putAttribute("simz1SpatialOD",JSON.createObjectNode().set(trip,record).toString());
        var identity=JSON.createObjectNode();identity.put("id",trip);identity.put("index",1);identity.put("origin_link",path.get(0));identity.put("destination_link",path.get(path.size()-1));identity.put("planned_departure",departure);
        p.getAttributes().putAttribute("simz1Trips",JSON.createArrayNode().add(identity).toString());return p;
    }
    private static void verifyOd(Object od,Person person,List<String> actual)throws Exception {
        var method=od.getClass().getDeclaredMethod("forLeg",Person.class,Leg.class);method.setAccessible(true);
        Object contract=method.invoke(od,person,(Leg)person.getSelectedPlan().getPlanElements().get(1));
        var validate=contract.getClass().getDeclaredMethod("validate",List.class);validate.setAccessible(true);
        check(validate.invoke(contract,actual.stream().map(SimZ1DischargeArrivalCheck::id).toList())==null,"Actual native route violates private OD: "+person.getId()+" "+actual);
        var wrong=new ArrayList<>(actual);wrong.set(wrong.size()-1,"e0");
        check(validate.invoke(contract,wrong.stream().map(SimZ1DischargeArrivalCheck::id).toList())!=null,"OD negative accepted changed destination");
    }
    private static void bus(Scenario s) {
        var schedule=s.getTransitSchedule();
        Map.ofEntries(Map.entry("fleetSchema","fixed-fleet-v1"),Map.entry("scenarioVersion","synthetic-fixed-fleet-v1"),Map.entry("serviceDate","2026-11-03"),Map.entry("purpose","synthetic_fixture"),Map.entry("passengersModeled","false"),Map.entry("minimumTurnPolicy","reject_on_actual_violation"),Map.entry("domainApproved","false"),Map.entry("domainSynthetic","true"),Map.entry("domainSource","synthetic eight-link fixture; not Zona 1 GIS"),Map.entry("domainLinks",String.join(" ",CHAIN)),Map.entry("monteCarloPersons","4"),Map.entry("configuredFleetSize","1"),Map.entry("scheduledExpeditions","1")).forEach((k,v)->attr(schedule,k,v));
        var vehicles=s.getTransitVehicles();var vf=vehicles.getFactory();var type=vf.createVehicleType(Id.create("synthetic-bus",VehicleType.class));
        type.setNetworkMode("bus").setLength(13.5).setWidth(2.5).setPcuEquivalents(3).setMaximumVelocity(10);type.getCapacity().setSeats(20);type.getCapacity().setStandingRoom(0);vehicles.addVehicleType(type);vehicles.addVehicle(vf.createVehicle(Id.createVehicleId("bus"),type));
        var sf=schedule.getFactory();var visits=new ArrayList<TransitRouteStop>();int index=0;
        for(String name:List.of("e0","i","xE")){
            var link=s.getNetwork().getLinks().get(id(name));var stop=sf.createTransitStopFacility(Id.create("stop-"+name,TransitStopFacility.class),link.getToNode().getCoord(),false);stop.setLinkId(link.getId());
            attr(stop,"stopPlacement","bay");attr(stop,"dwellBasis","explicit_scenario_assumption");attr(stop,"dwellSeconds",10);schedule.addStopFacility(stop);
            double offset=80*index++;var visit=sf.createTransitRouteStop(stop,offset,offset+10);visit.setAwaitDepartureTime(true);visits.add(visit);
        }
        var line=sf.createTransitLine(Id.create("line",TransitLine.class));attr(line,"serviceId","line");attr(line,"productionEnabled",false);attr(line,"assignedVehicleIds","bus");schedule.addTransitLine(line);
        var path=RouteUtils.createNetworkRoute(CHAIN.stream().map(SimZ1DischargeArrivalCheck::id).toList(),s.getNetwork());
        var route=sf.createTransitRoute(Id.create("route",TransitRoute.class),path,visits,"bus");attr(route,"routePolicy","fixed-v1");attr(route,"runningWay","mixed");line.addRoute(route);
        var departure=sf.createDeparture(Id.create("duty",Departure.class),550);departure.setVehicleId(Id.createVehicleId("bus"));attr(departure,"endTimeSeconds",720);attr(departure,"terminalSeconds",20);attr(departure,"turnaroundSeconds",10);route.addDeparture(departure);
    }
    public static void main(String[] args)throws Exception {
        try {run(args);} finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
    private static void nativeStorageControls()throws Exception {
        try(var f=new SimZ1StorageFixture(SimZ1StorageFixture.PROFILES.get(0),false)){
            var bus=f.actor("one-bus-storage-control",13.5,"receipt-a","dest-a");var q=f.queue("receipt-a",".original");
            check(q.getStorageCapacity()<bus.vehicle.getSizeInEquivalents(),"Control must test native capacity rejection after insertion");
            check(f.ledger.activity(bus.vehicle,id("receipt-a"),q.getId().toString(),1),"Synthetic stop owner not reserved");
            var remove=QueueWithBuffer.class.getDeclaredMethod("removeVehicleFromQueue",QVehicle.class);remove.setAccessible(true);
            // Same two native queue methods as repeated stop polling; only one
            // bus. Reflection selects the accepted-stop removal seam, without
            // emitting movement, arrival, or pretending to execute a duty.
            for(int cycle=0;cycle<10;cycle++){
                f.timer.setTime(1+cycle);check(q.getLoadIndicator()==0&&q.isAcceptingFromUpstream(),"Empty queue retained storage debt");
                q.addTransitSlightlyUpstreamOfStop(bus.vehicle);
                check(q.getLoadIndicator()==3&&!q.isAcceptingFromUpstream(),"Reinserted bus failed to occupy native receiving storage");
                check(q.getVehicle(bus.vehicle.getId())==bus.vehicle,"Bus missing after native reinsertion");
                remove.invoke(q,bus.vehicle);
                check(q.getLoadIndicator()==0&&q.getVehicle(bus.vehicle.getId())==null,"Accepted stop removal leaked native storage");
            }
            f.safety();check(f.moves==0,"Component control fabricated motion");
        }
    }
    private static void run(String[] args)throws Exception {
        String originPolicy=SimZ1AdmissionConfigGroup.LEGACY_ORIGIN;boolean originSpecified=false;
        var originalOptions=new ArrayList<String>();
        for(int i=0;i<args.length;i++){
            if(!args[i].equals("--origin-policy")){originalOptions.add(args[i]);continue;}
            check(!originSpecified&&i+1<args.length,"--origin-policy requires one explicit value and may occur only once");
            originSpecified=true;originPolicy=args[++i];
            check(SimZ1AdmissionConfigGroup.LEGACY_ORIGIN.equals(originPolicy)||SimZ1AdmissionConfigGroup.PHYSICAL_GAP_ORIGIN.equals(originPolicy),"Unknown origin policy: "+originPolicy);
        }
        args=originalOptions.toArray(String[]::new);
        if(args.length==2&&args[1].equals("--day-cycle")){runDayCycle(Path.of(args[0]),originPolicy);return;}
        check(args.length>=1&&args.length<=2,"Usage: SimZ1DischargeArrivalCheck <new-output-directory> [--require-native-storage|--day-cycle] [--origin-policy <empty-slot-origin-v1|physical-gap-origin-v1>]");
        check(args.length<2||args[1].equals("--require-native-storage"),"Unknown option");
        Path out=Path.of(args[0]).toAbsolutePath();check(!Files.exists(out),"Output must be new");Files.createDirectories(out);
        var c=ConfigUtils.createConfig();c.controler().setOutputDirectory(out.resolve("simulation").toString());c.controler().setLastIteration(0);c.controler().setRunId("synthetic-six-discharge");
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.parallelEventHandling().setNumberOfThreads(1);c.parallelEventHandling().setSynchronizeOnSimSteps(true);
        c.qsim().setUseLanes(true);c.qsim().setMainModes(Set.of("car"));c.qsim().setStartTime(0);c.qsim().setEndTime(800);c.qsim().setUsingFastCapacityUpdate(false);c.qsim().setRemoveStuckVehicles(false);c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);c.transit().setUseTransit(true);
        c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);c.travelTimeCalculator().setSeparateModes(false);
        for(String name:List.of("home","work"))c.planCalcScore().addActivityParams(new ActivityParams(name).setScoringThisActivityAtAll(false));
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        admission.setOriginPolicy(originPolicy);admission.validateOriginPolicy(c.qsim());
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();for(int i=0;i<=CHAIN.size();i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(i*40,0)));
        for(int i=0;i<CHAIN.size();i++)SimZ1CorridorOccupancyCheck.link(n,CHAIN.get(i),""+i,""+(i+1),40,1);LanesGenerator.build(s);
        Object od=installSyntheticOd(s);var paths=new LinkedHashMap<String,List<String>>();paths.put("EE",CHAIN);paths.put("EI",CHAIN.subList(0,5));paths.put("IE",CHAIN.subList(3,8));paths.put("II",CHAIN.subList(3,5));
        int ordinal=0;var people=new LinkedHashMap<String,Person>();for(var e:paths.entrySet())people.put(e.getKey(),privateTrip(s,e.getKey(),switch(e.getKey()){case "EE"->"external-external";case "EI"->"external-internal";case "IE"->"internal-external";default->"internal-internal";},e.getValue(),1+100*ordinal++));
        var freight=privateTrip(s,"freight","external-external",CHAIN,450);freight.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);freight.getAttributes().putAttribute("simz1FreightDeparture",450.);freight.getAttributes().putAttribute("simz1FreightRoute",String.join(" ",CHAIN));
        var freightType=s.getVehicles().getVehicles().get(Id.createVehicleId("freight")).getType();freightType.setLength(8).setWidth(2.3).setPcuEquivalents(3.5);
        bus(s);var events=new ArrayList<Event>();var storage=new ArrayList<Map<String,Object>>();var prior=new HashMap<String,String>();
        var controller=new Controler(s);UnsignalizedPriority.configure(controller);RunZona1Simulation.installTransit(controller);SimZ1Freight.install(controller);
        var queueField=QueueWithBuffer.class.getDeclaredField("vehQueue");queueField.setAccessible(true);
        controller.addOverridingModule(new AbstractModule(){@Override public void install(){
            addEventHandlerBinding().toInstance((BasicEventHandler)events::add);
            addMobsimListenerBinding().toInstance((MobsimAfterSimStepListener)e->{
                var qsim=(QSim)e.getQueueSimulation();
                for(var link:qsim.getNetsimNetwork().getNetsimLinks().values()){
                    Collection<QLaneI> queues=link instanceof QLinkLanesImpl lanes?lanes.getQueueLanes().values():List.of(((QLinkI)link).getAcceptingQLane());
                    for(var q:queues)if(q instanceof QueueWithBuffer queue){
                    try {double sum=0;int actors=0;for(Object item:(Iterable<?>)queueField.get(queue)){sum+=((QVehicle)item).getSizeInEquivalents();actors++;}
                        double load=queue.getLoadIndicator();String key=link.getLink().getId()+"/"+queue.getId();String state=actors+"/"+sum+"/"+load;
                        if(!state.equals(prior.put(key,state)))storage.add(Map.of("time",e.getSimulationTime(),"link",link.getLink().getId().toString(),"lane",queue.getId().toString(),"travelling_actors",actors,"travelling_pcu",sum,"native_used_pcu",load));
                    }catch(ReflectiveOperationException ex){throw new RuntimeException(ex);}
                    }
                }
            });
        }});
        controller.run();
        var actual=new LinkedHashMap<String,List<String>>();var arrivals=new LinkedHashMap<String,Double>();var exits=new LinkedHashMap<String,Double>();String busDriver=null;double finalStopDeparture=Double.NaN;
        var releases=new HashMap<String,Integer>();var lastProgress=new HashMap<String,Map<String,String>>();var proof=new LinkedHashMap<String,Map<String,String>>();
        for(var e:events){var a=e.getAttributes();if(e instanceof TransitDriverStartsEvent start)busDriver=start.getDriverId().toString();
            if(e instanceof VehicleEntersTrafficEvent start)actual.computeIfAbsent(start.getVehicleId().toString(),k->new ArrayList<>()).add(start.getLinkId().toString());
            if(e instanceof LinkEnterEvent enter)actual.computeIfAbsent(enter.getVehicleId().toString(),k->new ArrayList<>()).add(enter.getLinkId().toString());
            if(e.getEventType().equals("simz1OccupancyProgress"))lastProgress.put(a.get("vehicle"),a);
            if(e instanceof VehicleLeavesTrafficEvent leave){String v=leave.getVehicleId().toString();exits.put(v,e.getTime());proof.put(v,lastProgress.get(v));}
            if(e instanceof PersonArrivalEvent arrival)arrivals.put(arrival.getPersonId().toString(),arrival.getTime());
            if(e.getEventType().equals("VehicleDepartsAtFacility")&&"bus".equals(a.get("vehicle"))&&"stop-xE".equals(a.get("facility")))finalStopDeparture=e.getTime();
            if(e.getEventType().equals("simz1OccupancyReservation")&&"EXIT".equals(a.get("action"))&&"arrival".equals(a.get("reason")))releases.merge(a.get("vehicle"),1,Integer::sum);
        }
        var mismatches=storage.stream().filter(r->Math.abs((double)r.get("travelling_pcu")-(double)r.get("native_used_pcu"))>1e-7).toList();
        var evidence=new LinkedHashMap<String,Object>(Map.of("scope","six actors, eight synthetic links, Controller/QSim, not historical replay","arrivals",arrivals,"traffic_exits",exits,"actual_routes",actual,"arrival_progress",proof,"arrival_reservation_releases",releases,"bus_last_stop_departure",finalStopDeparture,"native_storage_changes",storage,"native_storage_mismatches",mismatches));
        if(!SimZ1AdmissionConfigGroup.LEGACY_ORIGIN.equals(originPolicy))evidence.put("origin_policy",originPolicy);
        JSON.writerWithDefaultPrettyPrinter().writeValue(out.resolve("evidence.json").toFile(),evidence);
        check(arrivals.size()==6&&exits.size()==6,"Missing six real native arrivals/exits: "+arrivals+" evidence="+out);
        for(var p:people.entrySet()){check(actual.get(p.getKey()).equals(paths.get(p.getKey())),"Actual route changed "+p.getKey());verifyOd(od,p.getValue(),actual.get(p.getKey()));}
        for(String v:List.of("freight","bus"))check(actual.get(v).equals(CHAIN),"Fixed route changed "+v);
        check(busDriver!=null&&Double.isFinite(finalStopDeparture)&&arrivals.get(busDriver)>=finalStopDeparture&&finalStopDeparture>=720,"Bus arrived before its real final stop departure");
        check(releases.size()==6&&releases.values().stream().allMatch(x->x==1),"Native arrivals did not release their body once: "+releases);
        check(proof.size()==6&&proof.values().stream().allMatch(p->p!=null&&Double.parseDouble(p.get("modeledFrontLowerBoundMeters"))+1e-8>=Double.parseDouble(p.get("nativeFrontBoundMeters"))),"Arrival removed a body still held by leader");
        check(events.stream().noneMatch(e->e instanceof PersonStuckEvent),"Abort/forced removal");SimZ1CorridorOccupancyCheck.verifyTransactions(events);
        if(args.length==2){check(args[1].equals("--require-native-storage"),"Unknown option");check(mismatches.isEmpty(),"NATIVE_STORAGE_MISMATCH: "+mismatches.size()+" samples; evidence="+out);nativeStorageControls();}
        System.out.println("PASS six real arrivals: EE/EI/IE/II + freight + bus; exact routes, last stop, bodies released once; native storage mismatches="+mismatches.size()+" evidence="+out);
    }

    /** Additional bounded coverage only. The original six-actor mode and its
     * before/after artifacts retain their original inputs and behavior. */
    private record DayExpected(String vehicle,String censusId,String family,String od,List<String> route,
                               double scheduled,double body,double pcu,String metadata) { }
    private static void count(ObjectNode row,String field){row.put(field,row.path(field).asInt()+1);}
    private static void verifyDayRow(DayExpected expected,ObjectNode actual,JsonNode census,String runId) {
        String who=expected.vehicle();
        for(String kind:List.of("departure","entry","exit","arrival"))
            check(actual.path(kind+"_count").asInt()==1,"DAY_MULTIPLICITY "+who+" "+kind);
        check(actual.path("arrival_release_count").asInt()==1,"DAY_RELEASE "+who);
        check(actual.path("abort_count").asInt()==0,"DAY_ABORT "+who);
        check(actual.path("body_m").asDouble()==expected.body()
            &&Math.abs(actual.path("footprint_m").asDouble()-expected.body()-.1)<1e-8,"DAY_BODY "+who);
        check(actual.has("native_pcu")&&actual.path("native_pcu").asDouble()==expected.pcu(),"DAY_NATIVE_PCU "+who);
        check(actual.has("modeled_front")&&actual.has("native_front")
            &&actual.path("progress_link").asText().equals(expected.route().get(expected.route().size()-1))
            &&actual.path("modeled_front").asDouble()+1e-8>=actual.path("native_front").asDouble(),"DAY_CLEARANCE "+who);
        check(actual.path("route").equals(JSON.valueToTree(expected.route())),"DAY_ROUTE "+who);
        check(actual.path("release_time").asDouble()==actual.path("exit_time").asDouble(),"DAY_RELEASE_TIME "+who);
        check(actual.path("exit_time").asDouble()==actual.path("arrival_time").asDouble(),"DAY_ARRIVAL_TIME "+who);
        check(census!=null&&census.path("trip_id").asText().equals(expected.censusId())
            &&census.path("vehicle_id").asText().equals(who)&&census.path("family").asText().equals(expected.family()),"DAY_CENSUS_ID "+who);
        check(census.path("run_id").asText().equals(runId)&&census.path("iteration").asInt(-1)==0
            &&census.path("policy").asText().equals(SimZ1DayObservation.POLICY),"DAY_CENSUS_SCOPE "+who);
        check(census.path("status").asText().equals("completed")&&census.path("pending_class").isNull()
            &&census.path("abort_before_cleanup").isNull()&&census.path("cleanup_abort_events").asInt()==0,"DAY_CENSUS_STATE "+who);
        check(census.path("scheduled_departure").asDouble()==expected.scheduled(),"DAY_CENSUS_SCHEDULE "+who);
        for(String[] fields:List.of(new String[]{"departure","departure_time"},new String[]{"traffic_entry","entry_time"},
                new String[]{"traffic_exit","exit_time"},new String[]{"arrival","arrival_time"}))
            check(census.hasNonNull(fields[0])&&census.path(fields[0]).asDouble()==actual.path(fields[1]).asDouble(),"DAY_CENSUS_EVENT "+who+" "+fields[0]);
        check(census.path("complete_duration_seconds").asDouble()==actual.path("arrival_time").asDouble()-actual.path("departure_time").asDouble(),"DAY_DURATION "+who);
        if(expected.metadata()!=null)check(census.path("od").asText().equals(expected.metadata()),"DAY_CENSUS_OD "+who);
        if(expected.family().equals("bus"))check(actual.path("driver_starts").asInt()==1&&actual.path("final_stop_departures").asInt()==1
            &&actual.path("final_stop_departure").asDouble()>=expected.scheduled()+170
            &&actual.path("arrival_time").asDouble()>=actual.path("final_stop_departure").asDouble(),"DAY_FINAL_STOP "+who);
    }
    private static void rejectDayCopy(DayExpected expected,ObjectNode actual,JsonNode census,String runId,
                                      String label,java.util.function.BiConsumer<ObjectNode,ObjectNode> mutate,List<String> rejected) {
        var observedCopy=actual.deepCopy();var censusCopy=((ObjectNode)census).deepCopy();mutate.accept(observedCopy,censusCopy);
        boolean failed=false;try{verifyDayRow(expected,observedCopy,censusCopy,runId);}catch(AssertionError wanted){failed=true;}
        check(failed,"Corrupted observation copy accepted: "+expected.vehicle()+"/"+label);rejected.add(expected.vehicle()+"/"+label);
    }
    private static void runDayCycle(Path requested,String originPolicy)throws Exception {
        Path out=requested.toAbsolutePath();check(!Files.exists(out),"Output must be new");Files.createDirectories(out);
        final double base=85300;String runId=Objects.toString(System.getenv("SIMZ1_RUN_ID"),"unmanaged");
        var c=ConfigUtils.createConfig();c.controler().setOutputDirectory(out.resolve("simulation").toString());
        c.controler().setRunId("synthetic-ten-day-cycle");c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.parallelEventHandling().setNumberOfThreads(1);
        c.parallelEventHandling().setSynchronizeOnSimSteps(true);c.qsim().setUseLanes(true);c.qsim().setMainModes(Set.of("car"));
        c.qsim().setStartTime(base);c.qsim().setEndTime(86399);c.qsim().setTimeStepSize(1);
        c.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        c.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        c.qsim().setUsingFastCapacityUpdate(false);c.qsim().setRemoveStuckVehicles(false);
        c.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);c.transit().setUseTransit(true);
        c.controler().setLinkToLinkRoutingEnabled(true);c.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);c.travelTimeCalculator().setSeparateModes(false);
        var observation=new org.matsim.core.config.ConfigGroup("simz1Observation");observation.addParam("policy",SimZ1DayObservation.POLICY);c.addModule(observation);
        for(String name:List.of("home","work"))c.planCalcScore().addActivityParams(new ActivityParams(name).setScoringThisActivityAtAll(false));
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
        var admission=ConfigUtils.addOrGetModule(c,SimZ1AdmissionConfigGroup.class);admission.setStoragePolicy(SimZ1AdmissionConfigGroup.STRICT);admission.setWholeVehicleReservation(true);
        admission.setOriginPolicy(originPolicy);admission.validateOriginPolicy(c.qsim());
        var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();for(int i=0;i<=CHAIN.size();i++)n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(i*40,0)));
        for(int i=0;i<CHAIN.size();i++)SimZ1CorridorOccupancyCheck.link(n,CHAIN.get(i),""+i,""+(i+1),40,1);LanesGenerator.build(s);
        Object od=installSyntheticOd(s);var paths=new LinkedHashMap<String,List<String>>();paths.put("EE",CHAIN);paths.put("EI",CHAIN.subList(0,5));paths.put("IE",CHAIN.subList(3,8));paths.put("II",CHAIN.subList(3,5));
        var expected=new LinkedHashMap<String,DayExpected>();var people=new LinkedHashMap<String,Person>();int ordinal=0;
        for(String family:List.of("carro","moto"))for(var entry:paths.entrySet()){
            String name=family+"_"+entry.getKey(),kind=switch(entry.getKey()){case "EE"->"external-external";case "EI"->"external-internal";case "IE"->"internal-external";default->"internal-internal";};
            double departure=base+1+100*ordinal++,body=family.equals("moto")?2.1:4.5,pcu=family.equals("moto")?.25:1;
            var person=privateTrip(s,name,kind,entry.getValue(),departure);people.put(name,person);
            var type=s.getVehicles().getVehicles().get(Id.createVehicleId(name)).getType();type.setLength(body).setWidth(family.equals("moto")?.8:1.8).setPcuEquivalents(pcu);
            person.getAttributes().putAttribute("simz1VehicleFamily",family);person.getAttributes().putAttribute("drivingProfile","normal");
            var metadata=(ObjectNode)JSON.readTree(person.getAttributes().getAttribute("simz1SpatialOD").toString());
            ((ObjectNode)metadata.get(name+":trip:0001")).put("body_length_m",body);person.getAttributes().putAttribute("simz1SpatialOD",metadata.toString());
            expected.put(name,new DayExpected(name,name,family,entry.getKey(),entry.getValue(),departure,body,pcu,metadata.toString()));
        }
        var freight=privateTrip(s,"freight","external-external",CHAIN,base+750);
        freight.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);freight.getAttributes().putAttribute("simz1FreightDeparture",base+750);
        freight.getAttributes().putAttribute("simz1FreightRoute",String.join(" ",CHAIN));
        var freightType=s.getVehicles().getVehicles().get(Id.createVehicleId("freight")).getType();freightType.setLength(8).setWidth(2.3).setPcuEquivalents(3.5);
        expected.put("freight",new DayExpected("freight","freight","pesado","service",CHAIN,base+750,8,3.5,null));
        bus(s);attr(s.getTransitSchedule(),"monteCarloPersons",8);
        var busDeparture=s.getTransitSchedule().getTransitLines().values().iterator().next().getRoutes().values().iterator().next().getDepartures().values().iterator().next();
        // Replace only this new mode's scheduled departure; offsets/dwell and the
        // original mode's bus() helper remain unchanged.
        var transitRoute=s.getTransitSchedule().getTransitLines().values().iterator().next().getRoutes().values().iterator().next();
        transitRoute.removeDeparture(busDeparture);var shifted=s.getTransitSchedule().getFactory().createDeparture(busDeparture.getId(),base+850);
        shifted.setVehicleId(busDeparture.getVehicleId());attr(shifted,"endTimeSeconds",base+1020);attr(shifted,"terminalSeconds",20);attr(shifted,"turnaroundSeconds",10);transitRoute.addDeparture(shifted);
        expected.put("bus",new DayExpected("bus","bus:line:route:duty","bus","expedition",CHAIN,base+850,13.5,3,null));
        var events=new ArrayList<Event>();var storage=new ArrayList<Map<String,Object>>();var storagePrior=new HashMap<String,String>();var nativePcu=new LinkedHashMap<String,Double>();
        var controller=new Controler(s);UnsignalizedPriority.configure(controller);RunZona1Simulation.installTransit(controller);SimZ1Freight.install(controller);SimZ1DayObservation.install(controller);
        var queueField=QueueWithBuffer.class.getDeclaredField("vehQueue");queueField.setAccessible(true);
        controller.addOverridingModule(new AbstractModule(){@Override public void install(){
            addEventHandlerBinding().toInstance((BasicEventHandler)events::add);
            addMobsimListenerBinding().toInstance((MobsimAfterSimStepListener)e->{
                var qsim=(QSim)e.getQueueSimulation();
                for(var link:qsim.getNetsimNetwork().getNetsimLinks().values()){
                    Collection<QLaneI> queues=link instanceof QLinkLanesImpl lanes?lanes.getQueueLanes().values():List.of(((QLinkI)link).getAcceptingQLane());
                    for(var q:queues)if(q instanceof QueueWithBuffer queue)try{
                        double sum=0;int actors=0;for(Object item:(Iterable<?>)queueField.get(queue)){
                            var nativeVehicle=(QVehicle)item;String vehicleId=nativeVehicle.getId().toString();var declared=expected.get(vehicleId);
                            check(declared!=null&&nativeVehicle.getSizeInEquivalents()==declared.pcu(),"Unexpected native vehicle/PCU "+vehicleId);
                            nativePcu.put(vehicleId,nativeVehicle.getSizeInEquivalents());sum+=nativeVehicle.getSizeInEquivalents();actors++;
                        }
                        double load=queue.getLoadIndicator();String key=link.getLink().getId()+"/"+queue.getId(),state=actors+"/"+sum+"/"+load;
                        if(!state.equals(storagePrior.put(key,state)))storage.add(Map.of("time",e.getSimulationTime(),"link",link.getLink().getId().toString(),"lane",queue.getId().toString(),"travelling_actors",actors,"travelling_pcu",sum,"native_used_pcu",load));
                    }catch(ReflectiveOperationException ex){throw new RuntimeException(ex);}
                }
            });
        }});controller.run();
        var actual=new LinkedHashMap<String,ObjectNode>();expected.forEach((key,value)->{var row=JSON.createObjectNode();row.putArray("route");if(nativePcu.containsKey(key))row.put("native_pcu",nativePcu.get(key));actual.put(key,row);});
        var driverVehicles=new HashMap<String,String>();var lastProgress=new HashMap<String,Map<String,String>>();var cuts=new ArrayList<Map<String,String>>();
        var physical=Set.of("departure","arrival","vehicle enters traffic","vehicle leaves traffic","entered link","left link","entered lane","left lane","TransitDriverStarts");
        for(var e:events){var a=e.getAttributes();String kind=e.getEventType();check(!physical.contains(kind)||e.getTime()<=86400,"Physical event after T");
            if(e instanceof TransitDriverStartsEvent start){check(start.getVehicleId().toString().equals("bus")&&start.getTransitLineId().toString().equals("line")&&start.getTransitRouteId().toString().equals("route")&&start.getDepartureId().toString().equals("duty"),"Wrong bus expedition");driverVehicles.put(start.getDriverId().toString(),"bus");count(actual.get("bus"),"driver_starts");actual.get("bus").put("driver_id",start.getDriverId().toString());}
            if(kind.equals("simz1DayCut"))cuts.add(new LinkedHashMap<>(a));
            String vehicle=a.get("vehicle"),person=a.get("person");if(vehicle==null&&person!=null)vehicle=driverVehicles.getOrDefault(person,person);
            var row=actual.get(vehicle);if(row==null){check(!physical.contains(kind)||vehicle==null,"Unexpected physical actor "+vehicle+" in "+kind);continue;}
            if(kind.equals("simz1OccupancyProgress"))lastProgress.put(vehicle,a);
            if(e instanceof VehicleEntersTrafficEvent enter){count(row,"entry_count");row.put("entry_time",e.getTime());((ArrayNode)row.get("route")).add(enter.getLinkId().toString());}
            if(e instanceof LinkEnterEvent enter)((ArrayNode)row.get("route")).add(enter.getLinkId().toString());
            if(e instanceof PersonDepartureEvent){count(row,"departure_count");row.put("departure_time",e.getTime());}
            if(e instanceof PersonArrivalEvent){count(row,"arrival_count");row.put("arrival_time",e.getTime());}
            if(e instanceof VehicleLeavesTrafficEvent){count(row,"exit_count");row.put("exit_time",e.getTime());var proof=lastProgress.get(vehicle);if(proof!=null){row.put("progress_link",proof.get("link"));row.put("modeled_front",Double.parseDouble(proof.get("modeledFrontLowerBoundMeters")));row.put("native_front",Double.parseDouble(proof.get("nativeFrontBoundMeters")));}}
            if(kind.equals("stuckAndAbort")||kind.equals("vehicle aborts"))count(row,"abort_count");
            if(kind.equals("simz1OccupancyReservation")&&"ENTER".equals(a.get("action"))){row.put("body_m",Double.parseDouble(a.get("bodyLengthMeters")));row.put("footprint_m",Double.parseDouble(a.get("footprintMeters")));}
            if(kind.equals("simz1OccupancyReservation")&&"EXIT".equals(a.get("action"))&&"arrival".equals(a.get("reason"))){count(row,"arrival_release_count");row.put("release_time",e.getTime());}
            if(kind.equals("VehicleDepartsAtFacility")&&vehicle.equals("bus")&&"stop-xE".equals(a.get("facility"))){count(row,"final_stop_departures");row.put("final_stop_departure",e.getTime());}
        }
        Path censusPath=Path.of(controller.getControlerIO().getIterationFilename(0,"simz1-day-census.jsonl.gz"));var census=new LinkedHashMap<String,JsonNode>();
        try(var reader=new java.io.BufferedReader(new java.io.InputStreamReader(new java.util.zip.GZIPInputStream(Files.newInputStream(censusPath)),java.nio.charset.StandardCharsets.UTF_8))){String line;while((line=reader.readLine())!=null){var row=JSON.readTree(line);check(census.put(row.path("trip_id").asText(),row)==null,"Duplicate census row");}}
        var mismatches=storage.stream().filter(r->Math.abs((double)r.get("travelling_pcu")-(double)r.get("native_used_pcu"))>1e-7).toList();
        var evidence=new LinkedHashMap<String,Object>();evidence.put("scope","ten native actors, eight synthetic links, one iteration near T; not a massive run");evidence.put("expected",expected);evidence.put("observed",actual);evidence.put("census",census);evidence.put("census_path",censusPath.toString());evidence.put("cuts",cuts);evidence.put("native_storage_changes",storage);evidence.put("native_storage_mismatches",mismatches);
        if(!SimZ1AdmissionConfigGroup.LEGACY_ORIGIN.equals(originPolicy))evidence.put("origin_policy",originPolicy);
        JSON.writerWithDefaultPrettyPrinter().writeValue(out.resolve("evidence.json").toFile(),evidence);
        check(expected.size()==10&&actual.size()==10&&census.size()==10,"Ten cases required");
        check(cuts.size()==1&&Double.parseDouble(cuts.get(0).get("time"))==86400&&Double.parseDouble(cuts.get(0).get("lastCompletedStep"))==86400
            &&cuts.get(0).get("run_id").equals(runId)&&cuts.get(0).get("iteration").equals("0")&&cuts.get(0).get("policy").equals(SimZ1DayObservation.POLICY),"Exact native census cut missing");
        for(var entry:expected.entrySet())verifyDayRow(entry.getValue(),actual.get(entry.getKey()),census.get(entry.getValue().censusId()),runId);
        for(var entry:people.entrySet()){var route=new ArrayList<String>();actual.get(entry.getKey()).get("route").forEach(x->route.add(x.asText()));verifyOd(od,entry.getValue(),route);}
        SimZ1CorridorOccupancyCheck.verifyTransactions(events);check(mismatches.isEmpty(),"NATIVE_STORAGE_MISMATCH "+mismatches.size());
        var rejected=new ArrayList<String>();
        for(var entry:expected.entrySet()){
            var exp=entry.getValue();var row=actual.get(entry.getKey());var censusRow=census.get(exp.censusId());
            for(String field:List.of("departure_count","entry_count","exit_count","arrival_count","arrival_release_count"))for(int wrong:List.of(0,2))
                rejectDayCopy(exp,row,censusRow,runId,field+"="+wrong,(r,z)->r.put(field,wrong),rejected);
            rejectDayCopy(exp,row,censusRow,runId,"body_not_clear",(r,z)->r.put("modeled_front",r.path("native_front").asDouble()-.01),rejected);
            rejectDayCopy(exp,row,censusRow,runId,"wrong_census_identity",(r,z)->z.put("vehicle_id","another-vehicle"),rejected);
            rejectDayCopy(exp,row,censusRow,runId,"wrong_census_state",(r,z)->z.put("status","active_at_cut"),rejected);
            rejectDayCopy(exp,row,censusRow,runId,"invented_census_arrival",(r,z)->z.put("arrival",r.path("arrival_time").asDouble()+1),rejected);
            if(exp.family().equals("bus")){
                rejectDayCopy(exp,row,censusRow,runId,"arrival_before_final_stop",(r,z)->r.put("final_stop_departure",r.path("arrival_time").asDouble()+1),rejected);
                rejectDayCopy(exp,row,censusRow,runId,"wrong_bus_expedition",(r,z)->z.put("trip_id","bus:line:route:other-duty"),rejected);
            }
        }
        evidence.put("copy_negative_scope","Validator-only mutations of deep copies after native positive validation; original events/census are never edited and no native event is injected.");evidence.put("rejected_copy_mutations",rejected);evidence.put("od_wrong_destination_rejections",people.size());evidence.put("status","PASS");
        JSON.writerWithDefaultPrettyPrinter().writeValue(out.resolve("evidence.json").toFile(),evidence);
        System.out.println("PASS ten native day-cycle arrivals: carro/moto x EE/EI/IE/II + freight + bus; unique events, body release, exact census, last stop; "+rejected.size()+" copy-only negatives; evidence="+out);
    }
}
