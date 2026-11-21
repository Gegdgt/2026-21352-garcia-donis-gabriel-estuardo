package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.io.*;
import java.util.*;
import java.util.zip.GZIPInputStream;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVRecord;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.VehicleUtils;

/** Three tiny native iterations plus event-contract edge cases. No OSM population run. */
public final class TripTableCheck {
    private static void require(boolean ok,String reason) { if(!ok)throw new AssertionError(reason); }
    private static List<CSVRecord> read(Path path) throws Exception {
        try(var reader=new InputStreamReader(new GZIPInputStream(Files.newInputStream(path)),StandardCharsets.UTF_8);
            var parser=CSVFormat.DEFAULT.withFirstRecordAsHeader().parse(reader)) { return parser.getRecords(); }
    }
    private static void feed(TripTableExporter exporter,String type,double time,String person,String vehicle,String mode) {
        var a=new HashMap<String,String>();a.put("type",type);a.put("time",Double.toString(time));a.put("link","l0");
        if(person!=null)a.put("person",person);if(vehicle!=null)a.put("vehicle",vehicle);if(mode!=null)a.put("legMode",mode);
        exporter.accept(a);
    }
    private static void edgeCases(Path root) throws Exception {
        var config=ConfigUtils.createConfig();config.qsim().setEndTime(90000);
        var scenario=ScenarioUtils.createScenario(config);var f=scenario.getPopulation().getFactory();
        for(String id:List.of("p1","p2","p3","p4"))scenario.getPopulation().addPerson(f.createPerson(Id.createPersonId(id)));
        var exporter=new TripTableExporter(scenario,"edge-contract",null);
        for(int iteration=0;iteration<2;iteration++) {
            Path folder=root.resolve("contract-"+iteration);exporter.begin(folder,iteration);
            feed(exporter,"departure",10,"p1",null,"car");
            feed(exporter,"vehicle enters traffic",10,"p1","vehicle-other-id",null);
            feed(exporter,"vehicle aborts",20,null,"vehicle-other-id",null);
            feed(exporter,"stuckAndAbort",20,"p1",null,"car");
            feed(exporter,"departure",30,"p1",null,"car");
            feed(exporter,"vehicle enters traffic",30,"p1","vehicle-other-id",null);
            feed(exporter,"arrival",40,"p1",null,"car");
            feed(exporter,"arrival",40,"p1",null,"car");
            feed(exporter,"vehicle aborts",41,null,"vehicle-other-id",null);
            feed(exporter,"departure",86399,"p2",null,"walk");
            feed(exporter,"arrival",86410,"p2",null,"walk");
            feed(exporter,"departure",89999,"p3",null,"car");
            feed(exporter,"departure",89999,"p4",null,"car");
            feed(exporter,"stuckAndAbort",90001,"p3",null,"car");
            exporter.finish();
            var rows=read(folder.resolve(iteration+".simz1-trips.csv.gz"));
            require(rows.size()==5,"Rows duplicated/lost");
            require(rows.get(0).get("person_id").equals("p1") && rows.get(0).get("vehicle_id").equals("vehicle-other-id"),"Person/vehicle identity");
            require(rows.get(0).get("status").equals("aborted") && rows.get(0).get("duration_seconds").isEmpty(),"Abort duration invented");
            require(rows.get(1).get("trip_index").equals("2") && rows.get(1).get("duration_seconds").equals("10.0"),"New trip after abort");
            require(rows.get(2).get("arrival").equals("86410.0") && rows.get(2).get("vehicle_id").isEmpty(),"Midnight/mode/vehicle");
            require(rows.stream().filter(r->r.get("status").equals("censored")).count()==2,"Censoring");
            String summary=Files.readString(folder.resolve(iteration+".simz1-trip-summary.json"));
            require(summary.contains("\"paired_terminal_events\":1") && summary.contains("\"duplicate_arrivals\":1"),"Anomalies absent");
            require(summary.contains("\"abort_after_arrival\":1"),"Inconsistent abort confused with paired terminal events");
        }
    }
    private static void nativeIterations(Path output) throws Exception {
        var config=ConfigUtils.createConfig();config.controler().setOutputDirectory(output.toString());
        config.controler().setLastIteration(2);config.controler().setWriteEventsInterval(10);
        config.controler().setWritePlansInterval(10);config.controler().setWriteTripsInterval(10);
        config.qsim().setStartTime(0);config.qsim().setEndTime(200);
        config.qsim().setSimEndtimeInterpretation(QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        config.qsim().setNumberOfThreads(1);config.global().setNumberOfThreads(1);config.global().setRandomSeed(811);
        for(String type:List.of("home","work")) {
            var params=new ActivityParams(type);params.setTypicalDuration(3600);params.setScoringThisActivityAtAll(false);
            config.planCalcScore().addActivityParams(params);
        }
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var scenario=ScenarioUtils.createScenario(config);var net=scenario.getNetwork();var nf=net.getFactory();
        for(int i=0;i<4;i++)net.addNode(nf.createNode(Id.createNodeId(i),new Coord(i%2*100,i/2*100)));
        for(int i=0;i<4;i++) {
            var link=nf.createLink(Id.createLinkId("l"+i),net.getNodes().get(Id.createNodeId(i)),net.getNodes().get(Id.createNodeId((i+1)%4)));
            link.setLength(i==1?1000:100);link.setFreespeed(10);link.setCapacity(3600);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car"));net.addLink(link);
        }
        var vf=scenario.getVehicles().getFactory();var vehicleType=vf.createVehicleType(Id.create("car",org.matsim.vehicles.VehicleType.class));
        vehicleType.setMaximumVelocity(10);scenario.getVehicles().addVehicleType(vehicleType);
        var f=scenario.getPopulation().getFactory();
        for(int i=0;i<2;i++) {
            var person=f.createPerson(Id.createPersonId("person-"+i));person.getAttributes().putAttribute("drivingProfile",i==0?"Normal":"Tortuga");
            var vehicle=Id.createVehicleId("vehicle-"+i);VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",vehicle));
            scenario.getVehicles().addVehicle(vf.createVehicle(vehicle,vehicleType));
            var plan=f.createPlan();var home=f.createActivityFromLinkId("home",Id.createLinkId("l0"));home.setEndTime(i==0?1:190);plan.addActivity(home);
            var leg=f.createLeg("car");leg.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("l0"),Id.createLinkId("l1"),Id.createLinkId("l2")),net));plan.addLeg(leg);
            var work=f.createActivityFromLinkId("work",Id.createLinkId("l2"));plan.addActivity(work);
            if(i==0) {
                work.setEndTime(150);var back=f.createLeg("car");
                back.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("l2"),Id.createLinkId("l3"),Id.createLinkId("l0")),net));plan.addLeg(back);
                plan.addActivity(f.createActivityFromLinkId("home",Id.createLinkId("l0")));
            }
            person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        var controler=new Controler(scenario);TripTableExporter.install(controler,"native-three-iterations");controler.run();
        for(int i=0;i<3;i++) {
            var rows=read(output.resolve("ITERS/it."+i+"/"+i+".simz1-trips.csv.gz"));
            require(rows.size()==3,"Missing per-iteration legs");
            require(rows.stream().filter(r->r.get("status").equals("completed")).count()==2,"Expected two arrivals");
            require(rows.stream().filter(r->r.get("status").equals("censored")).count()==1,"Expected horizon censoring");
            require(rows.stream().allMatch(r->!r.get("vehicle_id").equals(r.get("person_id"))),"Vehicle identity lost");
        }
        for(String file:List.of("1.events.xml.gz","1.legs.csv.gz","1.trips.csv.gz"))
            require(!Files.exists(output.resolve("ITERS/it.1/"+file)),"Fixture should demonstrate missing interval XML/legs: "+file);
        System.out.println("PASS: iteration 1 has compact CSV despite absent events, legs and trips; plans may be written before replanning; 3 iterations, 2 people, repeated trip and censoring");
    }
    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        try {
            Path root=Files.createTempDirectory(Path.of("target"),"prompt8-trips-");
            edgeCases(root);nativeIterations(root.resolve("native"));
            Files.writeString(Path.of("target/prompt8-native-evidence.txt"),root.toAbsolutePath().toString());
            System.out.println("PASS: compact export edge cases and native evidence="+root);
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
