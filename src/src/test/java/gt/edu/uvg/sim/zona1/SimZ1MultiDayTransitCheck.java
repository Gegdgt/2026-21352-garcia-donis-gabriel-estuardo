package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.utils.objectattributes.attributable.Attributable;
import com.fasterxml.jackson.databind.ObjectMapper;

/** One real native bus: a delayed duty cancels an expired slot, never the next civil day. */
public final class SimZ1MultiDayTransitCheck {
    private static void check(boolean value,String message) { if(!value)throw new AssertionError(message); }
    private static void attr(Attributable item,String key,Object value) { item.getAttributes().putAttribute("simz1:"+key,value.toString()); }
    private static String sha(byte[] bytes)throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
    private static void line(Scenario scenario,String id,String dep,double start,double closes,Double cutoff) {
        var schedule=scenario.getTransitSchedule();var sf=schedule.getFactory();
        var line=sf.createTransitLine(Id.create(id,TransitLine.class));
        attr(line,"serviceId",id);attr(line,"productionEnabled",false);attr(line,"assignedVehicleIds","synthetic-bus-1");
        attr(line,"opensSeconds",0);attr(line,"closesSeconds",closes);
        if(cutoff!=null)attr(line,"departureCutoffSeconds",cutoff);
        var route=RouteUtils.createLinkNetworkRouteImpl(Id.createLinkId("a_terminal"),Id.createLinkId("b_terminal"));
        route.setLinkIds(route.getStartLinkId(),List.of(Id.createLinkId("a_to_b")),route.getEndLinkId());
        var first=sf.createTransitRouteStop(schedule.getFacilities().get(Id.create("a_terminal",TransitStopFacility.class)),0,10);
        var last=sf.createTransitRouteStop(schedule.getFacilities().get(Id.create("b_terminal",TransitStopFacility.class)),100,110);
        first.setAwaitDepartureTime(false);last.setAwaitDepartureTime(false);
        var tr=sf.createTransitRoute(Id.create("route-"+dep,TransitRoute.class),route,List.of(first,last),"bus");
        attr(tr,"routePolicy","fixed-v1");attr(tr,"runningWay","mixed");attr(tr,"transferKind","exterior");
        attr(tr,"transferBasis","bounded synthetic regression assumption");attr(tr,"transferSeconds",10);
        var departure=sf.createDeparture(Id.create(dep,Departure.class),start);departure.setVehicleId(Id.createVehicleId("synthetic-bus-1"));
        attr(departure,"endTimeSeconds",start+110);attr(departure,"terminalSeconds",20);attr(departure,"turnaroundSeconds",10);
        tr.addDeparture(departure);line.addRoute(tr);schedule.addTransitLine(line);
    }
    public static void main(String[] args)throws Exception {
        Zona1Logging.configure();
        try {
            Path root=Path.of(args[0]).toAbsolutePath();Files.createDirectories(root);
            boolean lateStart=args.length>1&&"--late-start".equals(args[1]);
            var mapper=new ObjectMapper();var scenario=SimZ1TransitFleetCheck.fixture();var config=scenario.getConfig();
            config.controler().setOutputDirectory(root.resolve("simulation").toString());config.controler().setLastIteration(0);
            config.qsim().setStartTime(lateStart?700:0);config.qsim().setEndTime(88000);
            config.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
            config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
            config.qsim().setMainModes(Set.of("car"));config.qsim().setNumberOfThreads(1);config.global().setNumberOfThreads(1);
            for(String name:List.of("home","work"))config.planCalcScore().addActivityParams(new ActivityParams(name).setScoringThisActivityAtAll(false));
            var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
            var pop=scenario.getPopulation();var pf=pop.getFactory();int index=0;
            for(var person:pop.getPersons().values()) {
                var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("b_terminal"));home.setEndTime(10+index++*10);
                var leg=pf.createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("b_terminal"),Id.createLinkId("b_to_a"),Id.createLinkId("a_terminal")),scenario.getNetwork()));
                plan.addActivity(home);plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("a_terminal")));person.addPlan(plan);
            }
            DrivingProfiles.configure(scenario);
            // Actual travel >1000 s, planned trip 110 s. Delay remains physical and must not fabricate arrivals.
            var slow=scenario.getNetwork().getLinks().get(Id.createLinkId("a_to_b"));slow.setLength(1000);slow.setFreespeed(1);
            scenario.getTransitVehicles().removeVehicle(Id.createVehicleId("synthetic-bus-2"));
            var schedule=scenario.getTransitSchedule();new ArrayList<>(schedule.getTransitLines().values()).forEach(schedule::removeTransitLine);
            attr(schedule,"purpose","weekday_scenario_v2");attr(schedule,"minimumTurnPolicy","delay_until_ready_v2");
            attr(schedule,"domainSynthetic",false);attr(schedule,"configuredFleetSize",1);attr(schedule,"scheduledExpeditions",3);
            attr(schedule,"weekdayPolicyFile","weekday-policy.json");
            byte[] bundle="{}".getBytes(java.nio.charset.StandardCharsets.UTF_8);Files.write(root.resolve("route-bundle.json"),bundle,StandardOpenOption.CREATE_NEW);
            var policy=new LinkedHashMap<String,Object>();
            policy.put("schema_version","simz1-weekday-transit-v2");policy.put("scenario_assumptions_acknowledged",true);
            policy.put("route_assumptions_accepted",true);policy.put("passengers_modeled",false);policy.put("empirical_calibration",false);
            policy.put("domain_scope","computational_network");policy.put("closing_policy","no_new_departures_finish_active");policy.put("outside_policy","timed_off_network_v2");
            policy.put("service_date","2026-10-22");policy.put("road_demand_persons",3);policy.put("configured_fleet_size",1);
            policy.put("route_bundle_file","route-bundle.json");policy.put("source_bundle_sha256",sha(bundle));
            byte[] policyBytes=mapper.writeValueAsBytes(policy);Files.write(root.resolve("weekday-policy.json"),policyBytes,StandardOpenOption.CREATE_NEW);
            attr(schedule,"weekdayPolicySha256",sha(policyBytes));config.transit().setTransitScheduleFile(root.resolve("schedule.xml").toString());
            line(scenario,"day-0-first","d0-first",0,500,null);
            line(scenario,"day-0-expired","d0-expired",160,500,null);
            // Planned arrival exceeds departure cutoff but remains within civil service hours.
            line(scenario,"day-1","d1-valid",86400,90000,86500.);
            new TransitScheduleWriter(schedule).writeFile(root.resolve("schedule.xml").toString());
            var prepared=SimZ1TransitFleet.validate(scenario);
            check(prepared.configuredFleetB()==1&&prepared.scheduledExpeditions()==3,"Fixture N/B/roster invalid");
            var chronology=new ArrayList<Map<String,String>>();var starts=new TreeMap<String,Double>();var arrivals=new ArrayList<Double>();
            var active=new HashSet<String>();var drivers=new HashSet<String>();int[] peak={0};
            BasicEventHandler handler=e->{
                if(e instanceof TransitDriverStartsEvent x) {
                    check(starts.put(x.getDepartureId().toString(),x.getTime())==null,"Duplicate expedition");drivers.add(x.getDriverId().toString());
                }
                if(e instanceof VehicleEntersTrafficEvent x&&x.getVehicleId().toString().equals("synthetic-bus-1")) {
                    check(active.add(x.getVehicleId().toString()),"Concurrent duplicate bus");peak[0]=Math.max(peak[0],active.size());
                }
                if(e instanceof VehicleLeavesTrafficEvent x&&x.getVehicleId().toString().equals("synthetic-bus-1"))check(active.remove(x.getVehicleId().toString()),"Unmatched bus exit");
                if(e instanceof PersonArrivalEvent x&&x.getPersonId().toString().startsWith("pt_"))arrivals.add(x.getTime());
                if(e.getEventType().equals("simz1TransitBoundary")||e instanceof TransitDriverStartsEvent||e instanceof PersonArrivalEvent)chronology.add(new LinkedHashMap<>(e.getAttributes()));
            };
            var controler=new Controler(scenario);SimZ1TransitFleet.install(controler,prepared);
            controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});controler.run();
            check(starts.keySet().equals(lateStart?Set.of("d1-valid"):Set.of("d0-first","d1-valid")),"Expired day 0 canceled valid future day, or expired duty started: "+starts);
            check(starts.get("d1-valid")>=86400&&starts.get("d1-valid")<86500,"Future departure violated absolute time/cutoff");
            check(arrivals.size()==(lateStart?1:2)&&arrivals.get(0)>500&&arrivals.get(arrivals.size()-1)>86500,"Arrival invented/truncated at service cutoff");
            check(active.isEmpty()&&peak[0]==1&&drivers.size()==1,"Stable bus conservation failed");
            var cancelled=chronology.stream().filter(e->"cancelled_duty_after_closing".equals(e.get("action"))).toList();
            check(cancelled.size()==(lateStart?2:1)&&"d0-expired".equals(cancelled.get(cancelled.size()-1).get("departure")),"Wrong explicit duty cancellation");
            mapper.writerWithDefaultPrettyPrinter().writeValue(root.resolve("multi-day-transit-check.json").toFile(),Map.of(
                "status","passed","matsim_version","15.0","configured_buses",1,"main_persons",3,"scheduled_expeditions",3,
                "starts",starts,"native_arrivals",arrivals,"cancelled_expired_duties",cancelled,"peak_active_buses",peak[0],"chronology",chronology));
            System.out.println("PASS native multiday bus: expired duties canceled, same bus starts next day, active trip finishes past departure cutoff, actual arrivals="+arrivals.size()+", lateStart="+lateStart);
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
