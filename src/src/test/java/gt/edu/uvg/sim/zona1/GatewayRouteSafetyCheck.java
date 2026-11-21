package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;

/** In-memory whitelist/turn contracts only; no QSim, scenario files or population generation. */
public final class GatewayRouteSafetyCheck {
    private static Id<Link> id(String value) {return Id.createLinkId(value);}
    private static Id<Lane> lane(String value) {return Id.create(value,Lane.class);}
    private static List<Id<Link>> route(String... values) {return Arrays.stream(values).map(GatewayRouteSafetyCheck::id).toList();}
    private static void require(boolean value,String message) {if(!value)throw new AssertionError(message);}
    private static void rejects(Runnable action) {
        try {action.run();} catch(IllegalArgumentException expected) {return;}
        throw new AssertionError("Invalid spatial whitelist accepted");
    }
    private static Scenario fixture() {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var network=scenario.getNetwork();
        scenario.getConfig().controler().setLinkToLinkRoutingEnabled(true);
        for(int i=0;i<6;i++)network.addNode(network.getFactory().createNode(Id.createNodeId(i),new Coord(i*100,0)));
        add(network,"entry",0,1,100,"car");add(network,"inside",1,2,100,"car");add(network,"exit",2,3,100,"car");
        add(network,"outside-a",1,4,1,"car");add(network,"outside-b",4,2,1,"car");
        add(network,"outside-in",5,1,1,"car");add(network,"walk",1,2,1,"walk");return scenario;
    }
    private static void add(Network network,String name,int from,int to,double length,String mode) {
        var link=network.getFactory().createLink(id(name),network.getNodes().get(Id.createNodeId(from)),network.getNodes().get(Id.createNodeId(to)));
        link.setLength(length);link.setFreespeed(10);link.setCapacity(2000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of(mode));network.addLink(link);
    }
    private static ConfigGroup domain(Scenario scenario,String mode,String links) {
        var group=new ConfigGroup("zona1SpatialRouting");
        if(mode!=null)group.addParam("mode",mode);
        if(links!=null)group.addParam("allowedLinks",links);
        scenario.getConfig().addModule(group);return group;
    }
    public static void main(String[] args) {
        try {
            var scenario=fixture();var original=new SimZ1RouteSafety(scenario);
            require(original.validateNetwork(route("entry","outside-a","outside-b","exit"))==null,"Legacy network-wide route remains available without module");
            var unbounded=new SimZ1TurnRouter(scenario.getNetwork(),original,(link,time,person,vehicle)->Double.NaN);
            require(unbounded.path(id("entry"),id("exit"),0,null,null).contains(id("outside-a")),"Fixture needs a tempting external shortcut");
            var group=domain(scenario,"gateway-od","entry\tinside\nexit");var bounded=new SimZ1RouteSafety(scenario);
            require(bounded.validateNetwork(route("entry","inside","exit"))==null,"Internal route must remain valid");
            require(bounded.validateNetwork(route("entry","outside-a","outside-b","exit")).contains("outside_spatial_domain"),"External excursion is rejected explicitly");
            require(bounded.validateNetwork(route("outside-a")).contains("outside_spatial_domain"),"Same-link external route cannot bypass domain validation");
            require(bounded.successors(id("entry")).equals(route("inside")),"Internal entry cannot exit the spatial whitelist");
            require(bounded.successors(id("outside-in")).isEmpty(),"External from-link cannot enter the whitelist through the movement table");
            var expected=Set.of(id("entry"),id("inside"),id("exit"));
            bounded.allowedTurnInfos().forEach((from,turns)->turns.forEach(turn->require(expected.contains(from) && expected.contains(turn.getToLinkId()),"Primary routing table exposes external movement")));
            var router=new SimZ1TurnRouter(scenario.getNetwork(),bounded,(link,time,person,vehicle)->Double.NaN);
            require(router.path(id("entry"),id("exit"),0,null,null).equals(route("entry","inside","exit")),"Within-day candidate honors the same domain");
            require(router.path(id("outside-a"),id("outside-a"),0,null,null)==null,"Same-link external endpoint is rejected before early return");
            require(router.path(id("entry"),id("outside-a"),0,null,null)==null,"External destination rejected before search");
            require(bounded.validateReplacement(route("entry","inside","exit"),route("entry","outside-a","outside-b","exit"),0,id("entry"),id("exit"),null).contains("outside_spatial_domain"),"Replacement cannot escape domain");
            group.addParam("allowedLinks","entry inside exit outside-a outside-b");
            require(bounded.successors(id("entry")).equals(route("inside")),"Policy snapshot must be immutable after construction");
            var exposed=bounded.allowedTurnInfos();exposed.get(id("entry")).clear();
            require(bounded.successors(id("entry")).equals(route("inside")),"Returned movement map is defensive");

            var blocked=fixture();domain(blocked,"gateway-od","entry inside exit");
            var lanes=blocked.getLanes();var factory=lanes.getFactory();var assignment=factory.createLanesToLinkAssignment(id("entry"));
            LanesUtils.createAndAddLane(assignment,factory,lane("external-only"),2000,20,0,1,route("outside-a"),null);
            LanesUtils.createAndAddLane(assignment,factory,lane("original"),2000,100,0,1,null,List.of(lane("external-only")));
            lanes.addLanesToLinkAssignment(assignment);blocked.getConfig().qsim().setUseLanes(true);
            var combined=new SimZ1RouteSafety(blocked);
            require(combined.successors(id("entry")).isEmpty(),"Spatial whitelist never broadens native lane restrictions");
            require(!combined.laneAllows(id("entry"),lane("external-only"),id("outside-a")),"Actual external-only lane remains outside domain");

            var disabled=fixture();domain(disabled,"gateway-od","entry inside exit");
            disabled.getConfig().controler().setLinkToLinkRoutingEnabled(false);
            rejects(()->new SimZ1RouteSafety(disabled));
            var legacyDisabled=fixture();legacyDisabled.getConfig().controler().setLinkToLinkRoutingEnabled(false);
            require(new SimZ1RouteSafety(legacyDisabled).validateNetwork(route("entry","inside","exit"))==null,
                "Network-wide legacy mode does not acquire a spatial routing requirement");

            for(String mode:Arrays.asList(null,"network","through-traffic","typo"))rejects(()->{var s=fixture();domain(s,mode,"entry inside exit");new SimZ1RouteSafety(s);});
            for(String links:Arrays.asList(null,"","   ","entry missing","entry walk","entry entry"))rejects(()->{var s=fixture();domain(s,"gateway-od",links);new SimZ1RouteSafety(s);});
            System.out.println("PASS: spatial whitelist excludes external shortcuts, from/to movement leakage and invalid endpoints; legacy module absence preserved");
            System.out.println("PASS: primary/within-day shared safety, link-to-link requirement, lane intersections, immutable whitelist and malformed-config rejection; no QSim");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
