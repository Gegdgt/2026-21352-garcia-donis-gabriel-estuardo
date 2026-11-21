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
import org.matsim.core.scenario.ScenarioUtils;

/** Event-only observer regression. Does NOT construct a Controler or run QSim. */
public final class TripReconciliationCheck {
    private static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    private static void feed(TripTableExporter exporter, String type, double time,
            String person, String vehicle, String mode) {
        var values = new HashMap<String,String>();
        values.put("type",type); values.put("time",Double.toString(time)); values.put("link","l0");
        if (person!=null) values.put("person",person);
        if (vehicle!=null) values.put("vehicle",vehicle);
        if (mode!=null) values.put("legMode",mode);
        exporter.accept(values);
    }
    private static List<CSVRecord> read(Path file) throws Exception {
        try (var reader=new InputStreamReader(new GZIPInputStream(Files.newInputStream(file)),StandardCharsets.UTF_8);
             var parser=CSVFormat.DEFAULT.withFirstRecordAsHeader().parse(reader)) {
            return parser.getRecords();
        }
    }
    public static void main(String[] args) throws Exception {
        var config=ConfigUtils.createConfig(); config.qsim().setEndTime(100);
        var scenario=ScenarioUtils.createScenario(config);
        String[] profiles={"Normal","Liebre","Tortuga","Motociclista","MotocicletaLenta","MotocicletaRapida"};
        for (int i=0;i<6;i++) {
            var person=scenario.getPopulation().getFactory().createPerson(Id.createPersonId("person-"+i));
            person.getAttributes().putAttribute("effectiveVehicleType",profiles[i]);
            person.getAttributes().putAttribute("drivingProfile","Normal"); // effective identity takes precedence
            scenario.getPopulation().addPerson(person);
        }
        Files.createDirectories(Path.of("target"));
        var root=Files.createTempDirectory(Path.of("target"),"trip-reconciliation-");
        var exporter=new TripTableExporter(scenario,"event-only-regression",null);
        exporter.begin(root,0);
        for (int i=0;i<6;i++) {
            feed(exporter,"departure",1,"person-"+i,null,"car");
            feed(exporter,"PersonEntersVehicle",1,"person-"+i,"vehicle-"+i,null);
        }
        // An early vehicle/person abort pair closes one leg, in either order.
        feed(exporter,"vehicle aborts",10,null,"vehicle-0",null);
        feed(exporter,"stuckAndAbort",10,"person-0",null,"car");
        feed(exporter,"stuckAndAbort",10,"person-1",null,"car");
        feed(exporter,"vehicle aborts",10,null,"vehicle-1",null);
        feed(exporter,"vehicle aborts",10,null,"vehicle-1",null); // real duplicate
        feed(exporter,"vehicle enters traffic",20,"person-2","vehicle-2",null);
        feed(exporter,"vehicle leaves traffic",30,"person-2","vehicle-2",null);
        feed(exporter,"arrival",30,"person-2",null,"car");
        feed(exporter,"vehicle aborts",31,null,"vehicle-2",null); // remains invalid
        feed(exporter,"vehicle enters traffic",40,"person-4","vehicle-4",null);
        feed(exporter,"vehicle enters traffic",40,"person-5","vehicle-5",null);
        feed(exporter,"vehicle leaves traffic",50,"person-5","vehicle-5",null);
        // person-3 boarded but never entered traffic. Preserve this distinction.
        for (int i=3;i<6;i++) {
            feed(exporter,"vehicle aborts",100,null,"vehicle-"+i,null);
            feed(exporter,"stuckAndAbort",100,"person-"+i,null,"car");
        }
        exporter.finish();
        var rows=read(root.resolve("0.simz1-trips.csv.gz"));
        require(rows.size()==6,"Exactly one row per departure");
        require(rows.stream().filter(r->r.get("status").equals("completed")).count()==1,"One real arrival");
        require(rows.stream().filter(r->r.get("status").equals("aborted")).count()==2,"Two early aborts");
        require(rows.stream().filter(r->r.get("status").equals("censored")).count()==3,"Three horizon censures");
        require(rows.stream().allMatch(r->!r.get("person_id").equals(r.get("vehicle_id"))),"No guessed person/vehicle equality");
        require(rows.stream().map(r->r.get("profile")).collect(java.util.stream.Collectors.toSet()).equals(Set.of(profiles)),"All effective profile identities");
        require(rows.stream().filter(r->!r.get("status").equals("completed"))
            .allMatch(r->r.get("arrival").isEmpty() && r.get("duration_seconds").isEmpty()),"No fake arrivals/durations");
        String summary=Files.readString(root.resolve("0.simz1-trip-summary.json"));
        require(summary.contains("\"paired_terminal_events\":5"),"Five native pairs, not duplicates");
        require(summary.contains("\"duplicate_terminal_events\":1"),"Actual duplicate retained");
        require(summary.contains("\"abort_after_arrival\":1"),"Abort after arrival remains anomalous");
        require(!summary.contains("unmapped_vehicle_abort"),"Boarding mapped driver before traffic entry");
        for (String key:List.of("boarded_without_traffic_entry","entered_traffic_without_arrival","left_traffic_without_arrival"))
            require(summary.contains("\""+key+"\":1"),"Censoring stage: "+key);
        System.out.println("PASS: six effective profiles, boarding-before-admission, terminal pairs, true duplicates, early aborts and horizon censoring. Event fixture only; no QSim. "+root);
    }
}
