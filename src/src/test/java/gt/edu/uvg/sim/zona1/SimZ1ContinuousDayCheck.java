package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.VehicleUtils;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Four vehicles in real MATSim 15 QSim. Sensitivity is illustrative, not calibration. */
public final class SimZ1ContinuousDayCheck {
    private static void check(boolean value,String message) {
        if (!value) throw new AssertionError(message);
    }
    private static Map<String,Object> run(Path output,int warmup) throws Exception {
        double studyStart=warmup, studyEnd=warmup+86400., technicalEnd=studyEnd+900;
        var config=ConfigUtils.createConfig();
        config.controler().setOutputDirectory(output.toString());config.controler().setLastIteration(0);
        config.qsim().setStartTime(0);config.qsim().setEndTime(technicalEnd);
        config.qsim().setSimStarttimeInterpretation(QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        config.qsim().setRemoveStuckVehicles(false);
        config.qsim().setNumberOfThreads(1);config.global().setNumberOfThreads(1);config.global().setRandomSeed(7731);
        for (String type:List.of("home","work")) {
            var p=new ActivityParams(type);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(p);
        }
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);
        config.strategy().addStrategySettings(strategy);
        var scenario=ScenarioUtils.createScenario(config);var net=scenario.getNetwork();var nf=net.getFactory();
        for(int i=0;i<4;i++) net.addNode(nf.createNode(Id.createNodeId(i),new Coord(i*100,0)));
        for(int i=0;i<3;i++) {
            var l=nf.createLink(Id.createLinkId("l"+i),net.getNodes().get(Id.createNodeId(i)),net.getNodes().get(Id.createNodeId(i+1)));
            l.setLength(i==1?6000:10);l.setFreespeed(10);l.setCapacity(3600);l.setNumberOfLanes(1);l.setAllowedModes(Set.of("car"));net.addLink(l);
        }
        var vf=scenario.getVehicles().getFactory();var vt=vf.createVehicleType(Id.create("car",org.matsim.vehicles.VehicleType.class));
        vt.setMaximumVelocity(10);scenario.getVehicles().addVehicleType(vt);
        var planned=new LinkedHashMap<String,Double>();
        planned.put("context-fixed",0.);planned.put("context-carry",studyStart-20);
        planned.put("main-early",studyStart+30);planned.put("main-midnight",studyEnd-20);
        var pf=scenario.getPopulation().getFactory();
        for(var pair:planned.entrySet()) {
            var person=pf.createPerson(Id.createPersonId(pair.getKey()));var vehicle=Id.createVehicleId("v-"+pair.getKey());
            VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle));scenario.getVehicles().addVehicle(vf.createVehicle(vehicle,vt));
            var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId("l0"));home.setEndTime(pair.getValue());
            plan.addActivity(home);var leg=pf.createLeg("car");
            leg.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("l0"),Id.createLinkId("l1"),Id.createLinkId("l2")),net));
            plan.addLeg(leg);plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("l2")));
            person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        var dep=new TreeMap<String,Double>();var arr=new TreeMap<String,Double>();
        var enter=new TreeMap<String,Double>();var leave=new TreeMap<String,Double>();
        var chronology=new ArrayList<Map<String,Object>>();double[] last={-1};
        BasicEventHandler handler=e->{
            if(!(e instanceof PersonDepartureEvent || e instanceof PersonArrivalEvent || e instanceof VehicleEntersTrafficEvent || e instanceof VehicleLeavesTrafficEvent)) return;
            check(e.getTime()>=last[0],"Non-monotone native clock");last[0]=e.getTime();
            if(e instanceof PersonDepartureEvent x) check(dep.put(x.getPersonId().toString(),x.getTime())==null,"Duplicate departure");
            if(e instanceof PersonArrivalEvent x) check(arr.put(x.getPersonId().toString(),x.getTime())==null,"Duplicate arrival");
            if(e instanceof VehicleEntersTrafficEvent x) check(enter.put(x.getVehicleId().toString(),x.getTime())==null,"Duplicate traffic entry");
            if(e instanceof VehicleLeavesTrafficEvent x) check(leave.put(x.getVehicleId().toString(),x.getTime())==null,"Duplicate traffic exit");
            chronology.add(Map.of("type",e.getEventType(),"time",e.getTime(),"attributes",e.getAttributes()));
        };
        var controler=new Controler(scenario);
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});
        controler.run();
        check(dep.size()==4 && arr.size()==4 && enter.size()==4 && leave.size()==4,"Conservation/identity mismatch");
        check(dep.get("context-carry")<studyStart && arr.get("context-carry")>studyStart,"Warmup vehicle not carried into study");
        check(dep.get("main-midnight")<studyEnd && arr.get("main-midnight")>studyEnd,"Late trip reset/truncated at midnight");
        check(arr.get("main-midnight")>86400,"Clock wrapped to first day");
        long atStart=enter.entrySet().stream().filter(x->x.getValue()<=studyStart && leave.get(x.getKey())>studyStart).count();
        long atMidnight=enter.entrySet().stream().filter(x->x.getValue()<=studyEnd && leave.get(x.getKey())>studyEnd).count();
        return Map.of("warmup_seconds",warmup,"study_start",studyStart,"study_end",studyEnd,"technical_end",technicalEnd,
            "main_persons",2,"auxiliary_persons",2,"active_at_study_start",atStart,"active_at_midnight",atMidnight,
            "chronology",chronology,"planned",planned);
    }
    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        try {
            Path root=Path.of(args[0]).toAbsolutePath();Files.createDirectories(root);
            var results=new ArrayList<Map<String,Object>>();
            for(int warmup:new int[]{300,600,900})results.add(run(root.resolve("warmup-"+warmup),warmup));
            check(!results.get(0).get("active_at_study_start").equals(results.get(2).get("active_at_study_start")),
                "Fixture should demonstrate warmup sensitivity, not promise its absence");
            new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(root.resolve("continuous-day-check.json").toFile(),
                Map.of("status","passed","matsim_version","15.0","qsim_executions",3,"vehicles_per_execution",4,
                       "interpretation","Synthetic warmup sensitivity; no claim of stationarity or massive feasibility","runs",results));
            System.out.println("PASS real QSim: warmup carryover, absolute midnight, four conserved vehicles; sensitivity 300/600/900 seconds: "+results.stream().map(x->x.get("active_at_study_start")).toList());
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
