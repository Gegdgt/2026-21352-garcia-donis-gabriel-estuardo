package gt.edu.uvg.sim.zona1;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.agents.*;
import org.matsim.core.population.routes.*;
import org.matsim.core.replanning.modules.ReRoute;
import org.matsim.core.router.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.lanes.Lane;

/** Native routing/plan agents only. No Controller, QSim.run or fabricated arrival events. */
public final class SimZ1OdContractCheck {
    static final ObjectMapper JSON=new ObjectMapper();
    static final ArrayNode results=JSON.createArrayNode();
    static int checks;
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;System.out.println("PASS "+label);}
    static void rejects(Runnable action,String label){try{action.run();}catch(IllegalArgumentException|IllegalStateException e){check(true,label+": "+e.getMessage());return;}throw new AssertionError(label);}
    static List<Id<Link>> path(JsonNode a){return SimZ1TripOd.ids(a);}
    static Id<Link> id(String s){return Id.createLinkId(s);}
    static Person person(Scenario s,JsonNode row) {
        var f=s.getPopulation().getFactory();var p=f.createPerson(Id.createPersonId(row.path("person").asText()));
        row.path("attributes").fields().forEachRemaining(e->p.getAttributes().putAttribute(e.getKey(),e.getValue().asText()));
        var old=path(row.path("old"));var plan=f.createPlan();p.addPlan(plan);s.getPopulation().addPerson(p);
        var a=f.createActivityFromLinkId("origin",old.get(0));a.setEndTime(705.8073986087196);plan.addActivity(a);
        var leg=f.createLeg("car");leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,row.path("trip").asText());
        TripStructureUtils.setRoutingMode(leg,"car");var route=RouteUtils.createNetworkRoute(old);route.setVehicleId(Id.createVehicleId(p.getId()));leg.setRoute(route);plan.addLeg(leg);
        plan.addActivity(f.createActivityFromLinkId("destination",old.get(old.size()-1)));return p;
    }
    static Leg leg(Person p){return (Leg)p.getSelectedPlan().getPlanElements().get(1);}
    static Scenario tiny(JsonNode f) {
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());var n=s.getNetwork();
        s.getConfig().controler().setLinkToLinkRoutingEnabled(true);
        for(var e:f.path("edges"))for(int i=1;i<=2;i++) {
            var id=Id.createNodeId(e.get(i).asText());if(!n.getNodes().containsKey(id))
                n.addNode(n.getFactory().createNode(id,new Coord(n.getNodes().size()*10,0)));
        }
        for(var e:f.path("edges")) {
            var l=n.getFactory().createLink(id(e.get(0).asText()),n.getNodes().get(Id.createNodeId(e.get(1).asText())),n.getNodes().get(Id.createNodeId(e.get(2).asText())));
            l.setLength(e.get(3).asDouble());l.setFreespeed(10);l.setCapacity(2000);l.setNumberOfLanes(1);l.setAllowedModes(Set.of("car","bus"));n.addLink(l);
        }
        s.addScenarioElement(SimZ1TripOd.class.getName(),new SimZ1TripOd(f.path("spatial")));return s;
    }
    static void checkCase(Scenario s,JsonNode row,boolean historical)throws Exception {
        var p=person(s,row);var leg=leg(p);var old=path(row.path("old"));var bad=path(row.path("candidate"));
        var safety=new SimZ1RouteSafety(s);var od=safety.tripOd().forLeg(p,leg);int at=row.path("index").asInt();
        var lane=row.has("lane")?Id.create(row.path("lane").asText(),Lane.class):null;
        String issue=safety.validateReplacement(old,bad,at,old.get(at),old.get(old.size()-1),lane,od);
        boolean accepted=issue==null;
        check(accepted==row.path("accepted").asBoolean(),row.path("name").asText()+" candidate acceptance="+accepted+" reason="+issue);
        results.addObject().put("name",row.path("name").asText()).put("accepted",accepted).set("path",row.path("candidate"));
        var router=SimZ1OdHistoricalBeforeCheck.preferred(s,safety,bad);
        var agent=new BasicPlanAgentImpl(p.getSelectedPlan(),s,EventsUtils.createEventsManager(),new MobsimTimer(),TimeInterpretation.create(s.getConfig()));
        var driver=new PlanBasedDriverAgentImpl(agent);agent.endActivityAndComputeNextState(0);
        for(int i=1;i<=at;i++) {
            check(driver.chooseNextLinkId().equals(old.get(i)),"controlled native advance to occurrence "+i);
            driver.notifyMoveOverNode(old.get(i));
        }
        var oldRoute=leg.getRoute();var next=driver.chooseNextLinkId();
        CongestionAwareRerouting.Candidate proposal=null;
        for(int repeat=0;repeat<5;repeat++) {
            proposal=CongestionAwareRerouting.candidate(safety,router,p,leg,at,old.get(at),lane,720,null,719,old.subList(0,at+1));
            check(proposal.issue()==null,"compatible alternative: "+row.path("name").asText()+" "+proposal.issue());
            check(leg.getRoute()==oldRoute && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent)==at &&
                driver.chooseNextLinkId().equals(next) && SimZ1RouteSafety.full((NetworkRoute)leg.getRoute()).equals(old),"pure preparation retains native route/cursor/destination");
        }
        check(od.validate(proposal.route())==null && proposal.route().subList(0,at+1).equals(old.subList(0,at+1)),"accepted alternative preserves OD and exact traveled occurrence");
        results.addObject().put("name",row.path("name").asText()+"_alternative").put("accepted",true).set("path",JSON.valueToTree(proposal.route().stream().map(Object::toString).toList()));
        if(!accepted)check(!proposal.route().equals(bad),"router searches beyond the invalid candidate");
        if(row.has("forbidden_prefix")) {
            var prefix=path(row.path("forbidden_prefix"));
            check(router.path(prefix.get(prefix.size()-1),old.get(old.size()-1),720,p,null,null,719,prefix,od)==null,
                "17478998 DFA retained at mandatory exit join");
        }
        Object trip=leg.getAttributes().getAttribute(SimZ1TripOd.ATTRIBUTE);leg.getAttributes().removeAttribute(SimZ1TripOd.ATTRIBUTE);
        var refused=CongestionAwareRerouting.candidate(safety,router,p,leg,at,old.get(at),lane,720,null,719,old.subList(0,at+1));
        check(refused.issue().contains("missing leg simz1TripId") && leg.getRoute()==oldRoute && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent)==at,
            "missing required contract rejects without installation");
        leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,trip);
        rejects(()->router.path(old.get(at),old.get(old.size()-1),720,p,null),"required context cannot use legacy overload");
        var originalMeta=p.getAttributes().getAttribute("simz1SpatialOD");p.getAttributes().removeAttribute("simz1SpatialOD");
        rejects(()->safety.tripOd().forLeg(p,leg),"missing metadata in balanced private trip rejected");p.getAttributes().putAttribute("simz1SpatialOD",originalMeta);
        var malformed=JSON.readTree(originalMeta.toString());((ObjectNode)malformed.path(trip.toString())).put("destination_gateway","wrong");
        p.getAttributes().putAttribute("simz1SpatialOD",malformed.toString());rejects(()->safety.tripOd().forLeg(p,leg),"inconsistent gateway rejected");p.getAttributes().putAttribute("simz1SpatialOD",originalMeta);
        var identities=p.getAttributes().getAttribute("simz1Trips");
        var wrongIdentity=(ArrayNode)JSON.readTree(identities.toString());((ObjectNode)wrongIdentity.get(0)).put("index",2);
        p.getAttributes().putAttribute("simz1Trips",wrongIdentity.toString());rejects(()->safety.tripOd().forLeg(p,leg),"trip ordinal mismatch rejected");p.getAttributes().putAttribute("simz1Trips",identities);
        malformed=JSON.readTree(originalMeta.toString());((ObjectNode)malformed.path(trip.toString())).put("body_length_m","4.5");
        p.getAttributes().putAttribute("simz1SpatialOD",malformed.toString());rejects(()->safety.tripOd().forLeg(p,leg),"malformed contract dimensions rejected");p.getAttributes().putAttribute("simz1SpatialOD",originalMeta);
        // A nonselected plan with identical endpoints must still resolve its own leg ID.
        var f=s.getPopulation().getFactory();var copy=f.createPlan();
        org.matsim.core.population.PopulationUtils.copyFromTo(p.getSelectedPlan(),copy);p.addPlan(copy);
        String routedTrip=trip.toString();
        if(!historical) {
            routedTrip=p.getId()+":trip:0002";
            var records=(ObjectNode)JSON.readTree(originalMeta.toString());records.set(routedTrip,records.get(trip.toString()).deepCopy());
            p.getAttributes().putAttribute("simz1SpatialOD",records.toString());
            var trips=(ArrayNode)JSON.readTree(p.getAttributes().getAttribute("simz1Trips").toString());
            var second=(ObjectNode)trips.get(0).deepCopy();second.put("id",routedTrip).put("index",2);trips.add(second);
            p.getAttributes().putAttribute("simz1Trips",trips.toString());
            ((Leg)copy.getPlanElements().get(1)).getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,routedTrip);
        }
        var standard=ExperiencedTimeRouting.sequenceRouting(s,(l,t,person,v)->Double.NaN,null,DrivingProfiles.FASTEST_TIME);
        var tripRouter=new TripRouter.Builder(s.getConfig()).setRoutingModule("car",standard).build();
        new ReRoute(s,()->tripRouter,TimeInterpretation.create(s.getConfig())).getPlanAlgoInstance().run(copy);
        var routed=(Leg)copy.getPlanElements().get(1);
        check(routedTrip.equals(routed.getAttributes().getAttribute(SimZ1TripOd.ATTRIBUTE)),"standard ReRoute retains correct trip ID on nonselected plan with equal endpoints");
        check(od.validate(SimZ1RouteSafety.full((NetworkRoute)routed.getRoute()))==null,"standard ReRoute honors same trip OD");
        check(((NetworkRoute)routed.getRoute()).getVehicleId().equals(((NetworkRoute)oldRoute).getVehicleId()),"standard ReRoute preserves vehicle identity");
        var noIdentity=DefaultRoutingRequest.withoutAttributes(org.matsim.facilities.FacilitiesUtils.wrapActivity((Activity)copy.getPlanElements().get(0)),
            org.matsim.facilities.FacilitiesUtils.wrapActivity((Activity)copy.getPlanElements().get(2)),720,p);
        rejects(()->standard.calcRoute(noIdentity),"ambiguous endpoints cannot replace native trip identity");
        if(!historical) {
            // Remove only in-memory fixture access to the destination: no compatible alternative exists.
            var last=old.get(old.size()-1);var removed=s.getNetwork().removeLink(last);
            var blockedSafety=new SimZ1RouteSafety(s);var blocked=new SimZ1TurnRouter(s.getNetwork(),blockedSafety,(l,t,person,v)->Double.NaN);
            check(blocked.path(old.get(at),last,720,p,null,lane,719,old.subList(0,at+1),od)==null,"no compatible route is not replaced by another destination");
            check(leg.getRoute()==oldRoute && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent)==at,"no-path query leaves native state intact");s.getNetwork().addLink(removed);
        }
    }
    static void compatibility(JsonNode fixture)throws Exception {
        var s=tiny(fixture);var f=s.getPopulation().getFactory();var freight=f.createPerson(Id.createPersonId("service"));
        freight.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
        check(!SimZ1TripOd.shared(s).requires(freight),"registered freight has no private OD whitelist");
        s.getConfig().transit().setUseTransit(true);
        var busType=org.matsim.vehicles.VehicleUtils.createVehicleType(Id.create("bus-type",org.matsim.vehicles.VehicleType.class));
        busType.setNetworkMode("bus");s.getTransitVehicles().addVehicleType(busType);
        var bus=org.matsim.vehicles.VehicleUtils.createVehicle(Id.createVehicleId("registered-service"),busType);s.getTransitVehicles().addVehicle(bus);
        var safety=new SimZ1RouteSafety(s);var router=new SimZ1TurnRouter(s.getNetwork(),safety,(l,t,p,v)->Double.NaN);
        check(router.path(id("outside"),id("xE"),0,freight,null)!=null,"service retains network-wide routing");
        check(safety.successors(id("outside")).contains(id("xC")),"private contract does not remove physical/service graph edges");
        check(safety.laneAllowsVehicle(id("outside"),null,id("xC"),bus.getId()),"registered bus retains native permission outside private domain");
        var transitRegression=SimZ1TransitDiagnosticsCheck.class.getDeclaredMethod("rerouting");transitRegression.setAccessible(true);transitRegression.invoke(null);
        check(true,"existing transit identity/dwell exclusion regression; no arrival traces generated");
        var legacy=ScenarioUtils.createScenario(ConfigUtils.createConfig());var p=f.createPerson(Id.createPersonId("legacy"));
        p.getAttributes().putAttribute("simz1SpatialOD","{\"trip\":{\"metadata_source\":\"synthetic_gateway_od\"}}");
        check(!SimZ1TripOd.shared(legacy).requires(p),"explicit legacy metadata keeps historical compatibility");
        var balanced=f.createPerson(Id.createPersonId("required-without-manifest"));
        balanced.getAttributes().putAttribute("simz1SpatialOD","{\"trip\":{\"metadata_source\":\""+SimZ1TripOd.SCHEMA+"\"}}");
        var leg=f.createLeg("car");leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,"trip");
        rejects(()->SimZ1TripOd.shared(legacy).forLeg(balanced,leg),"required trip cannot fall back when domain artifact absent");
    }
    /** Called with an already occupied native ledger by the companion reservation fixture. */
    public static void reservationQueries(Scenario s,Leg leg,int index,Id<Lane> lane)throws Exception {
        var old=SimZ1RouteSafety.full((NetworkRoute)leg.getRoute());var original=leg.getRoute();
        var spatial=JSON.createObjectNode();var links=JSON.valueToTree(s.getNetwork().getLinks().keySet().stream().map(Object::toString).toList());
        spatial.set("allowed_links",links);spatial.set("internal_links",links);spatial.putObject("internal_origins").putObject(old.get(0).toString());
        spatial.putObject("entry_gateways");spatial.putObject("exit_gateways");
        s.addScenarioElement(SimZ1TripOd.class.getName(),new SimZ1TripOd(spatial));
        var p=s.getPopulation().getFactory().createPerson(Id.createPersonId("reservation"));String trip="reservation:trip:0001";
        var row=JSON.createObjectNode().put("od_type","internal-internal").put("od_class","INTERNAL_INTERNAL")
            .put("origin_link",old.get(0).toString()).put("destination_link",old.get(old.size()-1).toString())
            .put("scope","observed_z1_and_declared_anchors_only").putNull("door_to_door_seconds")
            .put("body_length_m",4.5).put("minimum_gap_m",.1).put("metadata_source",SimZ1TripOd.SCHEMA);
        row.set("route_link_ids",JSON.valueToTree(old.stream().map(Object::toString).toList()));
        for(String key:List.of("origin_gateway","destination_gateway","origin_zone","destination_zone","origin_observation_link","destination_observation_link","entry_crossing_link","exit_crossing_link"))row.putNull(key);
        var records=JSON.createObjectNode();records.set(trip,row);p.getAttributes().putAttribute("simz1SpatialOD",records.toString());
        var trips=JSON.createArrayNode();trips.addObject().put("id",trip).put("index",1).put("origin_link",old.get(0).toString()).put("destination_link",old.get(old.size()-1).toString());
        p.getAttributes().putAttribute("simz1Trips",trips.toString());leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,trip);
        var safety=new SimZ1RouteSafety(s);var router=new SimZ1TurnRouter(s.getNetwork(),safety,(l,t,person,v)->Double.NaN);
        for(int i=0;i<10;i++) {
            var proposed=CongestionAwareRerouting.candidate(safety,router,p,leg,index,old.get(index),lane,100,null,Double.NaN,old.subList(0,index+1));
            check(proposed.issue()==null,"OD candidate can be prepared while actual reservations are held");
        }
        row.put("destination_gateway","undeclared");p.getAttributes().putAttribute("simz1SpatialOD",records.toString());
        for(int i=0;i<10;i++) {
            var refused=CongestionAwareRerouting.candidate(safety,router,p,leg,index,old.get(index),lane,100,null,Double.NaN,old.subList(0,index+1));
            check(refused.issue().contains("inconsistent destination_gateway"),"OD rejection with live reservations");
        }
        check(leg.getRoute()==original && SimZ1RouteSafety.full((NetworkRoute)leg.getRoute()).equals(old),"accepted/rejected queries do not install a route");
    }
    public static void main(String[] args)throws Exception {
        try {
            var root=Path.of(args[0]);var historical=JSON.readTree(Files.readAllBytes(root.resolve("historical.json")));
            checkCase(SimZ1OdHistoricalBeforeCheck.scenario(historical),historical,true);
            var tiny=JSON.readTree(Files.readAllBytes(root.resolve("synthetic.json")));
            for(var row:tiny.path("cases"))checkCase(tiny(tiny),row,false);
            compatibility(tiny);
            var sequence=JSON.readTree(Files.readAllBytes(root.resolve("sequence.json")));
            for(var row:sequence.path("cases"))checkCase(tiny(sequence),row,false);
            JSON.writerWithDefaultPrettyPrinter().writeValue(root.resolve("java-cases.json").toFile(),results);
            System.out.println("PASS C529-B checks="+checks+"; synthetic routing only; no arrivals certified");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
