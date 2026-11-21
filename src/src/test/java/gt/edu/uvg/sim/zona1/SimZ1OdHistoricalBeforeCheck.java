package gt.edu.uvg.sim.zona1;

import com.fasterxml.jackson.databind.*;
import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;

/** Replay the exact recorded route against the pre-C529-B Java admission.
 * The cost fixture selects that path; it does not reconstruct historical travel times. */
public final class SimZ1OdHistoricalBeforeCheck {
    static final ObjectMapper JSON=new ObjectMapper();
    static List<Id<Link>> path(JsonNode a){var r=new ArrayList<Id<Link>>();a.forEach(v->r.add(Id.createLinkId(v.asText())));return r;}
    static void check(boolean v,String m){if(!v)throw new AssertionError(m);System.out.println("PASS "+m);}
    static Scenario scenario(JsonNode fixture)throws Exception {
        var config=ConfigUtils.createConfig();
        config.setContext(Path.of(fixture.path("run").asText(),"config-simz1.xml").toUri().toURL());
        config.network().setInputFile(fixture.path("network").asText());
        config.network().setLaneDefinitionsFile(fixture.path("lanes").asText());
        config.qsim().setUseLanes(true);config.controler().setLinkToLinkRoutingEnabled(true);
        var scenario=ScenarioUtils.createScenario(config);
        new MatsimNetworkReader(scenario.getNetwork()).readFile(config.network().getInputFile());
        new LanesReader(scenario).readFile(config.network().getLaneDefinitionsFile());return scenario;
    }
    static SimZ1TurnRouter preferred(Scenario s,SimZ1RouteSafety safety,List<Id<Link>> candidate) {
        var turns=new HashSet<String>();for(int i=1;i<candidate.size();i++)turns.add(candidate.get(i-1)+"/"+candidate.get(i));
        return new SimZ1TurnRouter(s.getNetwork(),safety,(l,t,p,v)->Double.NaN,
            (a,b,t,p,v)->turns.contains(a.getId()+"/"+b.getId())?1:1000000,DrivingProfiles.FASTEST_TIME);
    }
    public static void main(String[] args)throws Exception {
        try {
            var f=JSON.readTree(Files.readAllBytes(Path.of(args[0])));var s=scenario(f);var safety=new SimZ1RouteSafety(s);
            var old=path(f.path("old")); var candidate=path(f.path("candidate"));int index=f.path("index").asInt();
            var lane=Id.create(f.path("lane").asText(),Lane.class);var current=old.get(index);var end=old.get(old.size()-1);
            check(safety.validateReplacement(old,candidate,index,current,end,lane)==null,"BEFORE exact recorded candidate passes native replacement validation");
            var suffix=preferred(s,safety,candidate).path(current,end,720,null,null,lane,719,old.subList(0,index+1));
            check(candidate.equals(SimZ1RouteSafety.splice(old,index,suffix)),"BEFORE real router constructs exact counterexample with focal cost fixture");
            check(!candidate.contains(Id.createLinkId("osm_1196283991_0_backward")),"BEFORE destination retained while mandatory gateway observation omitted");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
