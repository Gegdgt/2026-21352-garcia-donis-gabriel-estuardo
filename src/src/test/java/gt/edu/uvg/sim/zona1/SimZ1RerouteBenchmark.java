package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.core.population.routes.NetworkRoute;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionInstallationFixture.*;

/** Bounded production evaluate/attempt benchmark. Two actors, 14 links, native
 * queues and reservations. Its seeded prefix is a partial synthetic state,
 * not replay of the historical 220K run. No QSim is started. */
public final class SimZ1RerouteBenchmark {
    private static final ObjectMapper JSON=new ObjectMapper();
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static Map<String,Object> sample(boolean negative,JsonNode baseline)throws Exception {
        try(var f=new SimZ1RetentionInstallationFixture(negative)) {
            SimZ1RetentionInstallationCheck.contract(f);
            var rerouting=new CongestionAwareRerouting(f.s);rerouting.initializeNative(f.network,f.vehicles,f.events);f.events.addHandler(rerouting);
            f.seedHead();double reached=f.advanceToSecondA(negative);f.seedBlocker();
            if(!negative) {
                var safety=new SimZ1RouteSafety(f.s);
                for(int t=(int)reached+1;t<=480;t++) {
                    check(!f.moveHead(t),"Full receiver fixture moved head");if(t%60==0)rerouting.retained(f.network,safety,t);
                }
            } else {
                var prior=Id.createVehicleId("completed-observation");
                rerouting.handleEvent(new LinkEnterEvent(-600,prior,id("slow")));rerouting.handleEvent(new LinkLeaveEvent(480,prior,id("slow")));
            }
            String before=f.ledgerSnapshot();
            rerouting.evaluate(480,List.of(f.driver));
            var decision=SimZ1RetentionInstallationCheck.decision(f).getAttributes();
            var after=SimZ1RouteSafety.full((NetworkRoute)f.leg.getRoute()).stream().map(Object::toString).toList();
            check(JSON.valueToTree(decision).equals(baseline.get("decision")),"Instrumented production decision/costs differ from baseline: "+decision);
            check(JSON.valueToTree(after).equals(baseline.get("after")),"Chosen route differs from baseline");
            check(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(f.driver)==6,"Native repeated-link cursor changed");
            check(before.equals(f.ledgerSnapshot()),"Instrumentation mutated native reservations");
            var step=f.log.stream().filter(e->e.getEventType().equals("zona1RerouteStep")).reduce((a,b)->b).orElseThrow().getAttributes();
            check(step.get("budget").equals("100")&&step.get("candidates").equals("1")&&step.get("calculations").equals("1"),"Budget/selection changed");
            check(step.get("installed").equals(negative?"0":"1")&&step.get("rejected").equals(negative?"1":"0"),"Admission outcome changed");
            var result=new LinkedHashMap<String,Object>();result.put("negative_reserved_other_slot",negative);result.put("timing",rerouting.lastTiming());
            result.put("decision",decision);result.put("route",after);result.put("native_cursor",6);result.put("ledger_unchanged",true);
            result.put("candidate_order",List.of(f.driver.getId().toString()));result.put("network_links",f.s.getNetwork().getLinks().size());
            result.put("actors",f.s.getPopulation().getPersons().size());return result;
        }
    }
    public static void main(String[] args)throws Exception {
        try {
            Path baseline=Path.of(args[0]),output=Path.of(args[1]);Files.createDirectories(output);
            var reference=JSON.readTree(baseline.toFile());var samples=new ArrayList<Map<String,Object>>();
            // Warmup is also checked against the same baseline, but excluded from timing summaries.
            for(int i=0;i<2;i++){sample(false,reference.get(0));sample(true,reference.get(1));}
            for(int i=0;i<7;i++){samples.add(sample(false,reference.get(0)));samples.add(sample(true,reference.get(1)));}
            var report=new LinkedHashMap<String,Object>();report.put("scope","partial synthetic native queue fixture; not historical replay and not scale evidence");
            report.put("qsim_started",false);report.put("source_fixture","src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1RetentionInstallationFixture.java");
            report.put("baseline",baseline.toString());report.put("baseline_decisions_exactly_equal",true);report.put("checks",checks);
            report.put("warmups",4);report.put("measured_evaluations",samples.size());report.put("samples",samples);
            report.put("optimization","none: no dynamic decision cache introduced; production subphase measurements now available");
            JSON.writerWithDefaultPrettyPrinter().writeValue(output.resolve("benchmark.json").toFile(),report);
            System.out.println("REROUTE BENCHMARK PASS checks="+checks+" measured="+samples.size()+"; exact baseline decisions/costs/routes, cursor and native reservations preserved; no QSim");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
