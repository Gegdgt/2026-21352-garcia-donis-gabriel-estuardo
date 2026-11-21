package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.population.routes.*;
import org.matsim.core.router.*;
import org.matsim.core.router.util.TravelTime;
import org.matsim.core.replanning.modules.ReRoute;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.lanes.LanesUtils;
import org.matsim.lanes.Lane;

/** Success regression of the original counterexample. Routing functions only:
 * no Controller, QSim, mobsim or output scenario is created or run. */
public final class Restriction17478998Probe {
    static final String A="osm_1273145789_0_forward", V="osm_1270930401_0_forward",
        B="osm_1273145790_0_forward", C="osm_734011349_14_forward", D="osm_260940553_0_forward";
    static int checks=0;
    static Id<Link> id(String s) { return Id.createLinkId(s); }
    static List<Id<Link>> path(String... names) { return Arrays.stream(names).map(Restriction17478998Probe::id).toList(); }
    static void check(boolean value,String label) { if(!value) throw new AssertionError(label); checks++; System.out.println("PASS "+label); }
    static void link(Network n, String name, String from, String to, double length) {
        var l = n.getFactory().createLink(id(name), n.getNodes().get(Id.createNodeId(from)),
            n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length); l.setFreespeed(10); l.setCapacity(4000);
        l.setNumberOfLanes(2); l.setAllowedModes(Set.of("car","bus")); n.addLink(l);
    }
    static Scenario fixture() {
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();
        for(String key:List.of("root","a","c","j","v","m","end"))
            n.addNode(n.getFactory().createNode(Id.createNodeId(key),new Coord(n.getNodes().size()*10,0)));
        link(n,A,"a","j",10);link(n,C,"c","j",36);link(n,V,"j","v",9.5);
        link(n,B,"v","m",70);link(n,D,"v","m",200);link(n,"E","m","end",20);
        link(n,"X","root","a",10);link(n,"H","a","c",36);link(n,"R","m","a",200);
        return s;
    }
    static void only(Scenario s,String from,String to) {
        var factory=s.getLanes().getFactory();var assignment=factory.createLanesToLinkAssignment(id(from));
        LanesUtils.createAndAddLane(assignment,factory,Id.create(from+".terminal",Lane.class),4000,
            s.getNetwork().getLinks().get(id(from)).getLength(),0,2,path(to),null);
        s.getLanes().addLanesToLinkAssignment(assignment);s.getConfig().qsim().setUseLanes(true);
    }
    static List<Id<Link>> reRoute(Scenario s, TravelTime times, String from) {
        var module=ExperiencedTimeRouting.sequenceRouting(s,times,null,DrivingProfiles.FASTEST_TIME);
        var trip=new TripRouter.Builder(s.getConfig()).setRoutingModule("car",module).build();
        var factory=s.getPopulation().getFactory();var person=factory.createPerson(Id.createPersonId("probe"));
        var plan=factory.createPlan();person.addPlan(plan);
        var home=factory.createActivityFromLinkId("home",id(from));home.setEndTime(1234);plan.addActivity(home);
        var leg=factory.createLeg("car");TripStructureUtils.setRoutingMode(leg,"car");
        leg.setRoute(RouteUtils.createNetworkRoute(path(from,V,B,"E")));plan.addLeg(leg);
        plan.addActivity(factory.createActivityFromLinkId("work",id("E")));
        new ReRoute(s,()->trip,TimeInterpretation.create(s.getConfig())).getPlanAlgoInstance().run(plan);
        var routed=(Leg)plan.getPlanElements().get(1);
        check(routed.getDepartureTime().seconds()==1234,"ReRoute retains departure time");
        return SimZ1RouteSafety.full((NetworkRoute)routed.getRoute());
    }
    public static void main(String[] args) throws Exception {
        try {
            var s=fixture();var n=s.getNetwork();var safety=new SimZ1RouteSafety(s);
            TravelTime times=(l,t,p,v)->l.getLength()/l.getFreespeed();
            var router=new SimZ1TurnRouter(n,safety,times);
            check(safety.validateNetwork(path(A,V,B))!=null,"A V B rejected");
            check(safety.validateNetwork(path(C,V,B))==null,"C V B allowed");
            check(safety.validateNetwork(path(A,V,D))==null,"A V other exit allowed");
            check(safety.validateNetwork(path(V))==null,"single link valid");
            check(SimZ1RouteSafety.full(RouteUtils.createNetworkRoute(path(V))).equals(path(V)),"single occurrence retained");
            check(router.path(id(A),id("E"),0,null,null).equals(path(A,V,D,"E")),"initial router finds connected legal alternative");
            check(router.path(id("X"),id("E"),0,null,null).equals(path("X","H",C,V,B,"E")),"distinct arrival states at V are not merged");
            var alternative=fixture();var other=alternative.getNetwork();
            other.removeLink(id("H"));other.removeLink(id("R"));
            link(other,"H","j","v",1000);link(other,"R","m","j",200);
            only(alternative,"H",D);only(alternative,D,"R");
            var alternatives=new SimZ1TurnRouter(other,new SimZ1RouteSafety(alternative),times);
            check(alternatives.path(id(A),id("E"),0,null,null).equals(path(A,"H",D,"R",V,B,"E")),
                "non-circular alternative survives a cheaper arrival after V");
            check(router.path(id(V),id("E"),0,null,null,null,Double.NaN,path(A,V)).equals(path(V,D,"E")),"native prefix A V retained");
            check(router.path(id(V),id("E"),0,null,null,null,Double.NaN,path(C,V)).equals(path(V,B,"E")),"native prefix C V retained");
            check(router.path(id(V),id("E"),0,null,null,null,Double.NaN,null)==null,"missing native prefix rejected without invented history");
            var repeated=path(C,V,B,"R",A,V,D,"E");
            check(safety.validateNetwork(repeated)==null,"legal full route with repeated link");
            check(safety.validateReplacement(repeated,SimZ1RouteSafety.splice(repeated,1,path(V,B,"E")),1,id(V),id("E"),null)==null,"first V occurrence preserves C");
            check(safety.validateReplacement(repeated,SimZ1RouteSafety.splice(repeated,5,path(V,B,"E")),5,id(V),id("E"),null)!=null,"second V occurrence rejects B after A");
            check(router.path(id(V),id("E"),0,null,null,null,Double.NaN,repeated.subList(0,6)).equals(path(V,D,"E")),"reroute uses real second occurrence");
            check(safety.allowedTurnInfos().get(id(A)).stream().anyMatch(t->t.getToLinkId().equals(id(V))) && safety.allowedTurnInfos().get(id(V)).stream().anyMatch(t->t.getToLinkId().equals(id(B))),"both physical pairs retained");
            check(reRoute(s,times,A).equals(path(A,V,D,"E")),"standard MATSim ReRoute rejects forbidden sequence");
            check(reRoute(s,times,C).equals(path(C,V,B,"E")),"standard MATSim ReRoute keeps legal origin");
            TravelTime observed=(l,t,p,v)->l.getId().equals(id(B))?900:l.getLength()/l.getFreespeed();
            check(reRoute(s,observed,C).equals(path(C,V,D,"E")),"ReRoute retains experienced delay costs");
            var turns=new SimZ1TurnRouter(n,safety,times,(a,b,t,p,v)->a.getId().equals(id(V))&&b.getId().equals(id(B))?900:Double.NaN,DrivingProfiles.FASTEST_TIME);
            check(turns.path(id(C),id("E"),0,null,null).equals(path(C,V,D,"E")),"experienced turn costs retained");
            check(SimZ1SequenceContract.shared().validate(path(A,V,B),"bus")!=null,"bus mode also honors no-exception restriction");
            n.removeLink(id(D));link(n,"Q","v","c",20);
            var blocked=new SimZ1TurnRouter(n,new SimZ1RouteSafety(s),times);
            check(blocked.path(id(V),id("E"),0,null,null,null,Double.NaN,path(A,V))==null,"no alternative rejects without a circular escape");
            check(blocked.path(id(V),id("E"),0,null,null,null,Double.NaN,path(C,V)).equals(path(V,B,"E")),"other origin remains available in no-alternative fixture");
            check(n.getLinks().get(id(V)).getCapacity()==4000 && n.getLinks().get(id(V)).getNumberOfLanes()==2,"routing does not change physical link parameters");
            var bytes=java.nio.file.Files.readAllBytes(java.nio.file.Path.of("src/main/resources/simz1/osm-sequences-v1.json"));
            var changed=Arrays.copyOf(bytes,bytes.length+1);
            boolean rejected=false;
            try {SimZ1SequenceContract.load(changed,java.nio.file.Path.of(""));}
            catch(IllegalArgumentException e) {rejected=e.getMessage().contains("contract SHA256 mismatch");}
            check(rejected,"Java rejects modified contract bytes");
            System.out.println("OSM_PROBE={\"status\":\"PASS\",\"checks\":"+checks+",\"controller_started\":false,\"qsim_started\":false}");
        } finally { org.apache.logging.log4j.LogManager.shutdown(); }
    }
}
