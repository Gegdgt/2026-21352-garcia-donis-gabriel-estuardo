package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.agents.BasicPlanAgentImpl;
import org.matsim.core.mobsim.qsim.agents.PlanBasedDriverAgentImpl;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.util.LeastCostPathCalculator;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import org.matsim.withinday.utils.EditRoutes;

/** Small deterministic topology/route checks; does not execute QSim. */
public final class RouteSafetyCheck {
    private static Id<Link> id(String value) { return Id.createLinkId(value); }
    private static Id<Lane> lane(String value) { return Id.create(value, Lane.class); }
    private static List<Id<Link>> path(String... links) { return Arrays.stream(links).map(RouteSafetyCheck::id).toList(); }
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void valid(String reason) { require(reason == null, "Rejected valid route: " + reason); }
    private static void invalid(String reason, String expected) {
        require(reason != null && reason.contains(expected), "Expected " + expected + ", got " + reason);
    }
    private static Scenario scenario() {
        var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        var net = scenario.getNetwork(); var f = net.getFactory();
        for (int i=0; i<6; i++) net.addNode(f.createNode(Id.createNodeId("N"+i), new Coord(i*100, (i%2)*100)));
        add(net,"a",0,1,"car"); add(net,"b",1,2,"car"); add(net,"c",2,0,"car");
        add(net,"d",1,3,"car"); add(net,"e",3,4,"car"); add(net,"f",4,5,"car");
        add(net,"g",1,4,"car"); add(net,"x",3,1,"car"); add(net,"walk",1,3,"walk");
        return scenario;
    }
    private static void add(Network net, String id, int from, int to, String mode) {
        var link = net.getFactory().createLink(id(id), net.getNodes().get(Id.createNodeId("N"+from)),
            net.getNodes().get(Id.createNodeId("N"+to)));
        link.setLength(100); link.setFreespeed(10); link.setCapacity(2000); link.setNumberOfLanes(1);
        link.setAllowedModes(Set.of(mode)); net.addLink(link);
    }
    private static NetworkRoute route(Scenario s, List<Id<Link>> full) {
        var route = s.getPopulation().getFactory().getRouteFactories().createRoute(NetworkRoute.class,
            full.get(0), full.get(full.size()-1));
        route.setLinkIds(full.get(0), full.size()<2 ? List.of() : full.subList(1,full.size()-1), full.get(full.size()-1));
        return route;
    }
    private static void lanes(Scenario s) {
        var f = s.getLanes().getFactory(); var assignment = f.createLanesToLinkAssignment(id("a"));
        LanesUtils.createAndAddLane(assignment,f,lane("left"),1000,20,-1,1,path("b"),null);
        LanesUtils.createAndAddLane(assignment,f,lane("right"),1000,20,1,1,path("d"),null);
        LanesUtils.createAndAddLane(assignment,f,lane("middle"),2000,60,0,1,null,List.of(lane("left"),lane("right")));
        LanesUtils.createAndAddLane(assignment,f,lane("original"),2000,100,0,1,null,List.of(lane("middle")));
        s.getLanes().addLanesToLinkAssignment(assignment);
        s.getConfig().qsim().setUseLanes(true);
    }
    private static void checkActualAgentIndexContract(Scenario s,List<Id<Link>> full) {
        var factory=s.getPopulation().getFactory();
        var person=factory.createPerson(Id.createPersonId("index-contract")); var plan=factory.createPlan();
        var origin=factory.createActivityFromLinkId("home",full.get(0)); origin.setEndTime(0);
        plan.addActivity(origin);
        var leg=factory.createLeg("car"); leg.setRoute(route(s,full)); plan.addLeg(leg);
        plan.addActivity(factory.createActivityFromLinkId("work",full.get(full.size()-1))); person.addPlan(plan);
        var agent=new BasicPlanAgentImpl(plan,s,EventsUtils.createEventsManager(),new MobsimTimer(),TimeInterpretation.create(s.getConfig()));
        var driver=new PlanBasedDriverAgentImpl(agent);
        agent.endActivityAndComputeNextState(0);
        for (int i=0; i<full.size(); i++) {
            require(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent)==i,"Actual MATSim route index at " + i);
            require(agent.getCurrentLinkId().equals(full.get(i)),"Actual MATSim current-link occurrence");
            if (i+1<full.size()) {
                require(driver.chooseNextLinkId().equals(full.get(i+1)),"Actual MATSim next-link index");
                require(!driver.isWantingToArriveOnCurrentLink(),"Premature arrival on repeated link");
                driver.notifyMoveOverNode(full.get(i+1));
            } else require(driver.isWantingToArriveOnCurrentLink(),"Actual MATSim terminal arrival");
        }
        // For a same-link route with zero internals, MATSim wants to arrive but
        // chooseNextLinkId still returns destination. Null is NOT its arrival contract.
        if (full.size()==1) require(driver.chooseNextLinkId().equals(full.get(0)),"Single-link next/arrival contract");
    }
    public static void main(String[] args) {
        var s = scenario(); var safety = new SimZ1RouteSafety(s);
        checkActualAgentIndexContract(s,path("a"));
        checkActualAgentIndexContract(s,path("a","d"));
        checkActualAgentIndexContract(s,path("a","b","c","a","d","e"));
        checkActualAgentIndexContract(s,path("a","b","c","a"));
        var router = new SimZ1TurnRouter(s.getNetwork(),safety,(link,time,person,vehicle)->link.getLength()/10);
        require(router.path(id("a"),id("e"),0,null,null).equals(path("a","d","e")),
            "Link-state routing did not reach the required destination link");
        require(router.path(id("e"),id("a"),0,null,null)==null,"Impossible directed route accepted");
        require(router.path(id("missing"),id("a"),0,null,null)==null,"Missing start accepted");
        require(router.path(id("a"),id("a"),0,null,null).equals(path("a")),"Same-link suffix");
        var ordinary = path("a","d","e");
        valid(safety.validateReplacement(ordinary,ordinary,0,id("a"),id("e"),null));
        valid(safety.validateReplacement(ordinary,ordinary,2,id("e"),id("e"),null));
        invalid(safety.validateReplacement(ordinary,ordinary,3,id("e"),id("e"),null),"index_out_of_bounds");
        invalid(safety.validateReplacement(ordinary,ordinary,1,id("a"),id("e"),null),"index_mismatch");
        invalid(safety.validateReplacement(ordinary,path("a","d","e","f"),0,id("a"),id("e"),null),"destination_changed");

        var single = route(s,path("a"));
        require(SimZ1RouteSafety.full(single).equals(path("a")), "Single-link normalization");
        valid(safety.validateReplacement(path("a"),path("a"),0,id("a"),id("a"),null));
        valid(safety.validateNetwork(path("a","d"))); // No internal links.
        invalid(safety.validateNetwork(path("a","e")),"disconnected");
        invalid(safety.validateNetwork(path("a","missing")),"missing_link");
        invalid(safety.validateNetwork(path("a","walk")),"mode_not_car");
        invalid(safety.validateReplacement(ordinary,List.of(),0,id("a"),id("e"),null),"empty_route");

        var loop = path("a","b","c","a","d","e");
        var replacement = SimZ1RouteSafety.splice(loop,3,path("a","d","e"));
        require(replacement.equals(loop),"Lost return occurrence of origin link");
        valid(safety.validateReplacement(loop,replacement,3,id("a"),id("e"),null));
        invalid(safety.validateReplacement(loop,ordinary,3,id("a"),id("e"),null),"prefix_changed");
        var repeated = path("a","b","c","a","b","c","a","d","e");
        var repeatedCandidate = SimZ1RouteSafety.splice(repeated,4,path("b","c","a","d","e"));
        require(repeated.equals(repeatedCandidate),"Repeated internal occurrence was lost");
        valid(safety.validateReplacement(repeated,repeatedCandidate,4,id("b"),id("e"),null));
        require(SimZ1RouteSafety.full(route(s,path("a","b","c","a"))).equals(path("a","b","c","a")),
            "Nonempty same-origin/destination loop was collapsed");
        invalid(safety.validateReplacement(path("a","e"),ordinary,0,id("a"),id("e"),null),"old_route");

        // MATSim 15 source regression: EditRoutes skips the current occurrence
        // whenever its ID equals the original start link, even at index 3.
        var leg = s.getPopulation().getFactory().createLeg("car"); leg.setRoute(route(s,loop));
        LeastCostPathCalculator calculator = (from,to,time,person,vehicle) ->
            new LeastCostPathCalculator.Path(List.of(from,to), List.of(s.getNetwork().getLinks().get(id("d"))),10,10);
        var editor = new EditRoutes(s.getNetwork(),calculator,s.getPopulation().getFactory());
        editor.replanCurrentLegRoute(leg,s.getPopulation().getFactory().createPerson(Id.createPersonId("loop")),3,0);
        var unsafe = SimZ1RouteSafety.full((NetworkRoute)leg.getRoute());
        require(unsafe.equals(path("a","b","c","d","e")),"MATSim 15 splice contract unexpectedly changed: " + unsafe);
        invalid(safety.validateNetwork(unsafe),"disconnected");

        lanes(s); safety = new SimZ1RouteSafety(s);
        router = new SimZ1TurnRouter(s.getNetwork(),safety,(link,time,person,vehicle)->link.getLength()/10);
        // The direct a->g movement is forbidden, but d->x legally returns to
        // the junction from another incoming link. Do not confuse a forbidden
        // movement with an unreachable destination link.
        var detour=router.path(id("a"),id("g"),0,null,null);
        require(detour.equals(path("a","d","x","g")),"Router ignored forbidden turn or lost legal return detour");
        valid(safety.validateNetwork(detour));
        var allowedPath = router.path(id("a"),id("e"),0,null,null);
        require(allowedPath.equals(path("a","d","e")),"Router did not use a permitted lane exit");
        valid(safety.validateNetwork(allowedPath));
        valid(safety.validateNetwork(loop));
        invalid(safety.validateNetwork(path("a","g")),"forbidden_movement");
        invalid(safety.validateReplacement(loop,loop,3,id("a"),id("e"),lane("left")),"current_lane_cannot_reach_next");
        valid(safety.validateReplacement(loop,loop,3,id("a"),id("e"),lane("right")));
        require(safety.laneAllows(id("a"),lane("original"),id("d")) &&
            safety.laneAllows(id("a"),lane("middle"),id("b")),"Intermediate lane DAG reachability");
        require(!safety.laneAllows(id("a"),lane("missing"),id("d")),"Unknown lane accepted");
        require(safety.successors(id("a")).equals(path("b","d")),"Unstable successor order/restricted movement");
        var exported = safety.allowedTurnInfos(); exported.get(id("a")).clear();
        require(safety.successors(id("a")).equals(path("b","d")),"Exposed mutable movement policy");
        s.getConfig().qsim().setUseLanes(false);
        valid(new SimZ1RouteSafety(s).validateNetwork(path("a","g")));

        var bad = scenario(); lanes(bad);
        bad.getLanes().getLanesToLinkAssignments().get(id("a")).getLanes().get(lane("middle")).addToLaneId(lane("middle"));
        try { new SimZ1RouteSafety(bad); throw new AssertionError("Accepted lane cycle"); }
        catch (IllegalArgumentException expected) { require(expected.getMessage().contains("cycle"),expected.getMessage()); }
        var inconsistent=scenario(); var net=inconsistent.getNetwork();
        var impostor=net.getFactory().createNode(Id.createNodeId("N1"),new Coord(100,100));
        var badLink=net.getFactory().createLink(id("impostor"),impostor,net.getNodes().get(Id.createNodeId("N3")));
        badLink.setAllowedModes(Set.of("car")); net.addLink(badLink);
        // NetworkImpl.addLink canonicalizes its endpoints. Corrupt the public
        // setter only afterwards so this fixture truly has a stale reference.
        badLink.setFromNode(impostor);
        require(badLink.getFromNode()!=net.getNodes().get(impostor.getId()),"Malformed node fixture was canonicalized");
        invalid(new SimZ1RouteSafety(inconsistent).validateNetwork(path("impostor")),"unregistered_node_reference");
        System.out.println("PASS: first/last link, full route index, single/short/impossible route, repeated links, return to origin, immutable prefix/destination, car modes");
        System.out.println("PASS: MATSim 15 EditRoutes loop-splice regression reproduced; candidate continuity rejection");
        System.out.println("PASS: restricted turns, actual terminal/intermediate lane reachability, deterministic successors, lane cycles, lanes off");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
