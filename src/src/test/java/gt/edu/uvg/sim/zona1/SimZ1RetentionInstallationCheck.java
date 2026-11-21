package gt.edu.uvg.sim.zona1;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionInstallationFixture.*;

/** Exercises the production evaluate -> attempt -> clone/install path, with a live body ledger. */
public final class SimZ1RetentionInstallationCheck {
    static final ObjectMapper JSON=new ObjectMapper();static int checks;
    static void check(boolean b,String text){checks++;if(!b)throw new AssertionError(text);}
    static ObjectNode gateway(String name,String anchor,String observed,String crossing,List<String> chain) {
        var n=JSON.createObjectNode().put("id",name).put("anchor_link",anchor).put("observation_link",observed).put("crossing_link",crossing);n.set("link_ids",JSON.valueToTree(chain));return n;
    }
    static void contract(SimZ1RetentionInstallationFixture f) {
        var spatial=JSON.createObjectNode().put("mode","balanced-gateway-v1");
        spatial.set("allowed_links",JSON.valueToTree(f.s.getNetwork().getLinks().keySet().stream().map(Object::toString).filter(x->!x.equals("tail")).toList()));
        spatial.set("internal_links",JSON.valueToTree(List.of(A,"loop","return","slow","detour","H",C)));spatial.putObject("internal_origins").putObject(A);
        spatial.putObject("entry_gateways").set("e0",gateway("entry","e0","eI","eC",List.of("e0","eC","eI")));
        spatial.putObject("exit_gateways").set("xE",gateway("exit","xE",V,B,List.of(V,B,"xE")));
        f.s.addScenarioElement(SimZ1TripOd.class.getName(),new SimZ1TripOd(spatial));
        String trip=f.person.getId()+":trip:0001";f.leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,trip);
        var record=JSON.createObjectNode().put("metadata_source",SimZ1TripOd.SCHEMA).put("od_type","external-external").put("od_class","EXTERNAL_EXTERNAL_THROUGH")
            .put("scope","observed_z1_and_declared_anchors_only").put("body_length_m",4.5).put("minimum_gap_m",.10).putNull("door_to_door_seconds")
            .put("origin_link","e0").put("destination_link","xE").put("origin_gateway","e0").put("destination_gateway","xE")
            .put("origin_zone","entry").put("destination_zone","exit").put("origin_observation_link","eI").put("destination_observation_link",V)
            .put("entry_crossing_link","eC").put("exit_crossing_link",B);
        record.set("route_link_ids",JSON.valueToTree(f.old.stream().map(Object::toString).toList()));
        var records=JSON.createObjectNode();records.set(trip,record);f.person.getAttributes().putAttribute("simz1SpatialOD",records.toString());
        var trips=JSON.createArrayNode();trips.addObject().put("id",trip).put("index",1).put("origin_link","e0").put("destination_link","xE");f.person.getAttributes().putAttribute("simz1Trips",trips.toString());
    }
    static Event decision(SimZ1RetentionInstallationFixture f) {
        return f.log.stream().filter(e->e.getEventType().equals("zona1RerouteRejected")||e.getEventType().equals("zona1WithinDayReroute")).reduce((a,b)->b).orElseThrow();
    }
    static Map<String,Object> run(boolean negative)throws Exception {
        try(var f=new SimZ1RetentionInstallationFixture(negative)) {
            contract(f);var r=new CongestionAwareRerouting(f.s);r.initializeNative(f.network,f.vehicles,f.events);f.events.addHandler(r);
            check(r.eligible(f.driver,0),"Real50% cohort must include fixture driver at seed20261023");
            f.seedHead();double reached=f.advanceToSecondA(negative);f.seedBlocker();
            check(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(f.driver)==6,"Actual repeated-link index6, not first occurrence3");
            var safety=new SimZ1RouteSafety(f.s);var od=safety.tripOd().forLeg(f.person,f.leg);check(od!=null && od.validate(f.old)==null,"OD is required and original route valid");
            if(!negative) {
                for(int t=(int)reached+1;t<=480;t++) {
                    check(!f.moveHead(t),"Full real receiving queue must retain head");
                    if(t%60==0)r.retained(f.network,safety,t);
                }
                check(!r.retained(f.network,safety,480).isEmpty(),"Fresh active trigger with body reservation");
            } else {
                check(f.currentLane().getId().toString().endsWith(".original"),"Negative is still in shared original queue with committed body slot");
                // Completed-time input only to invoke the unchanged downstream trigger.
                var prior=Id.createVehicleId("completed-observation");r.handleEvent(new LinkEnterEvent(-600,prior,id("slow")));r.handleEvent(new LinkLeaveEvent(480,prior,id("slow")));
            }
            var beforeRoute=f.leg.getRoute();String before=f.ledgerSnapshot();var vehicle=f.head.getId();var destination=f.driver.getDestinationLinkId();
            r.evaluate(480,List.of(f.driver)); // SAME production scheduling, preparation, validation, reservation gate and installation
            var event=decision(f);var after=SimZ1RouteSafety.full((NetworkRoute)f.leg.getRoute());
            check(before.equals(f.ledgerSnapshot()),"Rerouting acquired/released/changed an actual reservation or lock");
            check(WithinDayAgentUtils.getCurrentRouteLinkIdIndex(f.driver)==6 && f.head.getId().equals(vehicle) && f.driver.getDestinationLinkId().equals(destination),"Cursor, vehicle or destination changed during installation");
            check(after.subList(0,7).equals(f.old.subList(0,7)),"Traversed occurrence prefix changed");
            var result=new LinkedHashMap<String,Object>();result.put("negative",negative);result.put("prefixIsSyntheticInitialState",true);result.put("before",f.old.stream().map(Object::toString).toList());result.put("after",after.stream().map(Object::toString).toList());result.put("indexBefore",6);result.put("indexAfter",6);result.put("decision",event.getAttributes());result.put("ledgerUnchangedDuringReroute",true);
            result.put("ledgerBefore",before);result.put("ledgerAfterInstallation",f.ledgerSnapshot());
            if(negative) {
                check(f.leg.getRoute()==beforeRoute && event.getEventType().equals("zona1RerouteRejected") && event.getAttributes().get("reason").equals("occupancy_reserved_terminal_slot"),"Expected actual reservation rejection: "+event.getAttributes());
                check(f.driver.chooseNextLinkId().equals(id("slow")),"Rejected candidate consumed native next link");
            }else {
                check(event.getEventType().equals("zona1WithinDayReroute") && f.leg.getRoute()!=beforeRoute && f.driver.chooseNextLinkId().equals(id("H")),"Production installer did not accept legal improvement: "+event.getAttributes());
                check(od.validate(after)==null && safety.validateNetwork(after)==null,"Installed OD/OSM contract broken");
                check(after.subList(7,after.size()).equals(path("H",C,V,B,"xE")),"17478998 DFA or required exit chain lost");
                check(safety.validateNetwork(path(A,V,B))!=null,"17478998 forbidden sequence unexpectedly accepted");
                check(event.getAttributes().get("activeRetentionUsedAsTravelTime").equals("false"),"Active waiting used as cost");
                check(!r.eligible(f.driver,779) && r.eligible(f.driver,780),"Installation cooldown changed");
                // Completed sample on the shared downstream link: both estimates
                // use it; a trigger must not force a legal non-improving change.
                var installed=f.leg.getRoute();var prior=Id.createVehicleId("prior-shared-link");
                r.handleEvent(new LinkEnterEvent(280,prior,id(C)));r.handleEvent(new LinkLeaveEvent(780,prior,id(C)));
                r.evaluate(780,List.of(f.driver));
                var noImprovement=f.log.stream().filter(e->"zona1RerouteRejected".equals(e.getEventType())&&e.getTime()==780).findFirst().orElseThrow();
                check("no_expected_improvement".equals(noImprovement.getAttributes().get("reason")) && f.leg.getRoute()==installed && before.equals(f.ledgerSnapshot()),"Non-improving candidate must leave route/locks unchanged: "+noImprovement.getAttributes());
                result.put("noImprovementDecision",noImprovement.getAttributes());
                boolean moved=false;for(int t=781;t<=810;t++){f.advanceLink(t);if(f.moveHead(t)){moved=true;break;}}
                check(moved && f.driver.getCurrentLinkId().equals(id("H")) && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(f.driver)==7,"Native next movement did not use installed route");
                check(f.log.stream().anyMatch(e->e instanceof LinkEnterEvent entered && entered.getVehicleId().equals(f.head.getId()) && entered.getLinkId().equals(id("H"))),"No native link-entry evidence for installed next movement");
                check(f.log.stream().noneMatch(e->e instanceof PersonArrivalEvent),"Fixture must not certify arrival");
                result.put("nativeNextLink","H");result.put("nativeIndexAfterMove",7);
                result.put("nativeMovementEvent",f.log.stream().filter(e->e instanceof LinkEnterEvent entered && entered.getVehicleId().equals(f.head.getId()) && entered.getLinkId().equals(id("H"))).findFirst().orElseThrow().getAttributes());
                result.put("ledgerAfterNativeMovement",f.ledgerSnapshot());
            }
            return result;
        }
    }
    public static void main(String[] args)throws Exception {
        try {var result=List.of(run(false),run(true));JSON.writerWithDefaultPrettyPrinter().writeValue(Path.of(args[0]).resolve("installation.json").toFile(),result);System.out.println("INSTALLATION PASS checks="+checks+"; actual evaluate/attempt, native reservations and next movement, no arrival");}
        finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
