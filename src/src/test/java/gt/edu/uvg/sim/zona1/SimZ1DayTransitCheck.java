package gt.edu.uvg.sim.zona1;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPInputStream;
import com.fasterxml.jackson.databind.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.utils.objectattributes.attributable.Attributable;

/** Bounded native QSim near midnight: N=3, B=2, two duties of one bus,
 * one spare bus, two iterations. Synthetic topology, never a massive Run. */
public final class SimZ1DayTransitCheck {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void attr(Attributable item,String key,Object value){item.getAttributes().putAttribute("simz1:"+key,value.toString());}
    private static final Set<String> PHYSICAL=Set.of("departure","arrival","vehicle enters traffic","vehicle leaves traffic",
        "entered link","left link","entered lane","left lane","TransitDriverStarts");
    private static final class Evidence implements BasicEventHandler {
        int iteration;
        final Map<Integer,List<Map<String,String>>> events=new TreeMap<>();
        @Override public void reset(int it){iteration=it;events.put(it,new ArrayList<>());}
        @Override public void handleEvent(Event event){events.computeIfAbsent(iteration,k->new ArrayList<>()).add(new LinkedHashMap<>(event.getAttributes()));}
    }
    public static void main(String[] args)throws Exception {
        Zona1Logging.configure();
        try {
            check(args.length==1,"Usage: SimZ1DayTransitCheck <new-output-directory>");
            Path root=Path.of(args[0]).toAbsolutePath();check(!Files.exists(root),"Output must be new");Files.createDirectories(root);
            var scenario=SimZ1TransitFleetCheck.fixture();var config=scenario.getConfig();
            config.controler().setOutputDirectory(root.resolve("simulation").toString());config.controler().setLastIteration(1);
            config.controler().setRunId("synthetic-day-bus");
            config.qsim().setStartTime(85990);config.qsim().setEndTime(86399);config.qsim().setTimeStepSize(1);
            config.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
            config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
            config.qsim().setMainModes(Set.of("car"));config.qsim().setNumberOfThreads(1);config.global().setNumberOfThreads(1);
            config.parallelEventHandling().setNumberOfThreads(1);config.parallelEventHandling().setSynchronizeOnSimSteps(true);
            var observation=new ConfigGroup("simz1Observation");observation.addParam("policy",SimZ1DayObservation.POLICY);config.addModule(observation);
            for(String name:List.of("home","work"))config.planCalcScore().addActivityParams(new ActivityParams(name).setScoringThisActivityAtAll(false));
            var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
            var pop=scenario.getPopulation();var pf=pop.getFactory();int index=0;
            for(var person:pop.getPersons().values()) {
                var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("a_terminal"));home.setEndTime(86200+index++*10);
                var leg=pf.createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("a_terminal"),Id.createLinkId("a_to_b"),Id.createLinkId("b_terminal")),scenario.getNetwork()));
                plan.addActivity(home);plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("b_terminal")));
                person.addPlan(plan);person.setSelectedPlan(plan);person.getAttributes().putAttribute("simz1VehicleFamily","carro");
            }
            DrivingProfiles.configure(scenario);
            // Separate synthetic slow return: its pending duty lasts beyond T.
            var slow=scenario.getNetwork().getLinks().get(Id.createLinkId("b_to_a"));slow.setLength(1000);slow.setFreespeed(1);
            var schedule=scenario.getTransitSchedule();attr(schedule,"scheduledExpeditions",2);
            var line=schedule.getTransitLines().get(Id.create("synthetic-service",TransitLine.class));
            for(var route:line.getRoutes().values()) {
                new ArrayList<>(route.getDepartures().values()).forEach(route::removeDeparture);
                double time=route.getId().toString().equals("ida")?86000:86340;
                var departure=schedule.getFactory().createDeparture(Id.create(route.getId()+"-day",Departure.class),time);
                departure.setVehicleId(Id.createVehicleId("synthetic-bus-1"));attr(departure,"endTimeSeconds",time+110);
                attr(departure,"terminalSeconds",20);attr(departure,"turnaroundSeconds",10);route.addDeparture(departure);
            }
            var originalPersons=Set.copyOf(pop.getPersons().keySet());var originalFleet=Set.copyOf(scenario.getTransitVehicles().getVehicles().keySet());
            var prepared=SimZ1TransitFleet.validate(scenario);
            check(prepared.roadPersonsN()==3&&prepared.configuredFleetB()==2&&prepared.scheduledExpeditions()==2,"Bounded fixture counts changed");
            var evidence=new Evidence();var controller=new Controler(scenario);
            var monitor=RunZona1Simulation.installTransit(controller);check(monitor!=null,"Production transit path not installed");
            SimZ1DayObservation.install(controller);
            controller.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(evidence);}});
            controller.run();
            check(originalPersons.equals(pop.getPersons().keySet())&&originalFleet.equals(scenario.getTransitVehicles().getVehicles().keySet()),"Fleet/population identity changed");
            var mapper=new ObjectMapper();var summaries=new ArrayList<Map<String,Object>>();List<JsonNode> previous=null;
            for(int it=0;it<=1;it++) {
                Path census=Path.of(controller.getControlerIO().getIterationFilename(it,"simz1-day-census.jsonl.gz"));
                var rows=new ArrayList<JsonNode>();
                try(var reader=new BufferedReader(new InputStreamReader(new GZIPInputStream(Files.newInputStream(census)),StandardCharsets.UTF_8))){String row;while((row=reader.readLine())!=null)rows.add(mapper.readTree(row));}
                check(rows.size()==5,"Expected three road trips and two bus expeditions, not B bus rows");
                var buses=rows.stream().filter(r->r.path("family").asText().equals("bus")).toList();
                check(buses.size()==2&&buses.stream().allMatch(r->r.path("vehicle_id").asText().equals("synthetic-bus-1")),"Bus vehicle and expedition identity conflated");
                var arrived=buses.stream().filter(r->r.path("trip_id").asText().contains(":ida:")).findFirst().orElseThrow();
                var pending=buses.stream().filter(r->r.path("trip_id").asText().contains(":vuelta:")).findFirst().orElseThrow();
                check(arrived.path("status").asText().equals("completed")&&!arrived.path("arrival").isNull(),"First bus duty did not really arrive");
                check(pending.path("status").asText().equals("active_at_cut"),"Pending duty not censored at horizon: "+pending);
                check(pending.path("pending_class").asText().equals("horizon_censored_no_private_duration_threshold"),"Bus got private duration threshold");
                check(pending.path("arrival").isNull()&&pending.path("complete_duration_seconds").isNull()&&pending.path("abort_before_cleanup").isNull(),"Cleanup fabricated arrival/complete travel or prior abort");
                check(pending.path("traffic_entry").asDouble()>=86340&&pending.path("observed_traffic_seconds").asDouble()>0,"Missing native bus incorporation/duration");
                check(pending.path("cleanup_abort_events").asLong()>0,"Raw cleanup abort not retained separately");
                var stream=evidence.events.get(it);check(stream!=null,"Missing iteration events");
                var cuts=stream.stream().filter(e->"simz1DayCut".equals(e.get("type"))).toList();
                check(cuts.size()==1&&cuts.get(0).get("time").equals("86400.0")&&cuts.get(0).get("lastCompletedStep").equals("86400.0"),"Missing exact pre-cleanup cut");
                check(stream.stream().noneMatch(e->PHYSICAL.contains(e.get("type"))&&Double.parseDouble(e.get("time"))>86400),"Physical event after T");
                var starts=stream.stream().filter(e->"TransitDriverStarts".equals(e.get("type"))).toList();
                check(starts.size()==2,"Bus duty counter carried across iterations or lost a start");
                var counters=stream.stream().filter(e->"simz1TransitCounters".equals(e.get("type"))&&"before_cleanup".equals(e.get("observationPhase"))).findFirst().orElseThrow();
                check("2".equals(counters.get("configuredFleetB"))&&"2".equals(counters.get("observedExpeditionStarts"))&&"1".equals(counters.get("observedInternalTransitDrivers"))&&"1".equals(counters.get("activePublicVehiclesNetwork")),"Parked fleet/active duty/counters conflated: "+counters);
                for(var row:rows)check(row.path("iteration").asInt(-1)==it,"Stale census iteration");
                var comparable=new ArrayList<JsonNode>();for(var row:rows){var copy=row.deepCopy();((com.fasterxml.jackson.databind.node.ObjectNode)copy).remove("iteration");comparable.add(copy);}
                if(previous!=null)check(previous.equals(comparable),"Census changed/carried old state between identical iterations");previous=comparable;
                summaries.add(Map.of("iteration",it,"census",census.toString(),"bus_rows",buses,"before_cleanup_counters",counters,"cut",cuts.get(0)));
            }
            mapper.writerWithDefaultPrettyPrinter().writeValue(root.resolve("day-transit-result.json").toFile(),Map.of("status","passed","scope","synthetic bounded native QSim; N=3 B=2 two duties, one spare bus, two iterations near T","iterations",summaries));
            System.out.println("PASS native day transit: one completed and one censored expedition of same bus; spare bus remains distinct; T=86400; no post-cut physical events; two fresh iterations. "+root);
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
