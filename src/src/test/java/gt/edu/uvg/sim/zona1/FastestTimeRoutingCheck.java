package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.LinkLeaveEvent;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

/** Synthetic expected-time contracts only: no Controler, QSim, export or observed scientific data. */
public final class FastestTimeRoutingCheck {
    private static Id<Link> id(String value) {return Id.createLinkId(value);}
    private static Id<Lane> lane(String value) {return Id.create(value,Lane.class);}
    private static List<Id<Link>> route(String... links) {return Arrays.stream(links).map(FastestTimeRoutingCheck::id).toList();}
    private static void require(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
    private static void near(double actual,double expected,String message) {
        require(Double.isFinite(actual) && Math.abs(actual-expected)<1e-8,message+": "+actual+" != "+expected);
    }
    private static void rejects(Runnable action) {
        try {action.run();} catch(IllegalArgumentException expected) {return;}
        throw new AssertionError("Invalid routing input accepted");
    }
    private static void add(Network network,String name,int from,int to,double length,double speed) {
        var link=network.getFactory().createLink(id(name),network.getNodes().get(Id.createNodeId(from)),network.getNodes().get(Id.createNodeId(to)));
        link.setLength(length);link.setFreespeed(speed);link.setCapacity(2000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of("car"));
        network.addLink(link);
    }
    private static Scenario fixture() {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());var network=scenario.getNetwork();
        for(int i=0;i<4;i++)network.addNode(network.getFactory().createNode(Id.createNodeId(i),new Coord(i*100,0)));
        add(network,"s",0,1,10,10);add(network,"short",1,2,100,2);add(network,"long",1,2,200,20);add(network,"e",2,3,10,10);
        for(String profile:List.of("Tortuga","Normal","Liebre")) {
            var person=scenario.getPopulation().getFactory().createPerson(Id.createPersonId(profile));
            person.getAttributes().putAttribute("drivingProfile",profile);scenario.getPopulation().addPerson(person);
        }
        DrivingProfiles.configure(scenario);return scenario;
    }
    private static Person person(Scenario scenario,String profile) {return scenario.getPopulation().getPersons().get(Id.createPersonId(profile));}
    private static Vehicle vehicle(Scenario scenario,Person person) {return scenario.getVehicles().getVehicles().get(VehicleUtils.getVehicleId(person,"car"));}
    private static void restrictToLong(Scenario scenario) {
        var lanes=scenario.getLanes();var factory=lanes.getFactory();var assignment=factory.createLanesToLinkAssignment(id("s"));
        LanesUtils.createAndAddLane(assignment,factory,lane("only-long"),2000,5,0,1,route("long"),null);
        LanesUtils.createAndAddLane(assignment,factory,lane("original"),2000,10,0,1,null,List.of(lane("only-long")));
        lanes.addLanesToLinkAssignment(assignment);scenario.getConfig().qsim().setUseLanes(true);
    }
    public static void main(String[] args) {
        try {
            var scenario=fixture();var network=scenario.getNetwork();var safety=new SimZ1RouteSafety(scenario);
            var fastest=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->Double.NaN,null,DrivingProfiles.FASTEST_TIME);
            var legacy=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->Double.NaN,null,DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL);
            var congested=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->link.getId().equals(id("long"))?100:Double.NaN,null,DrivingProfiles.FASTEST_TIME);
            for(String profile:List.of("Tortuga","Normal","Liebre")) {
                var person=person(scenario,profile);var vehicle=vehicle(scenario,person);
                var selected=fastest.path(id("s"),id("e"),0,person,vehicle);
                require(selected.equals(route("s","long","e")),"Longer faster alternative must win for "+profile+": "+selected);
                require(safety.validateNetwork(selected)==null,"Fastest route must preserve allowed movements");
                var estimate=fastest.evaluate(selected,0,person,vehicle,Double.NaN);
                double start=profile.equals("Tortuga")?1.8:1,branch=profile.equals("Tortuga")?36:profile.equals("Normal")?14.4:10;
                near(estimate.seconds(),start+branch,"Physical profile ceiling and destination exclusion");
                near(estimate.cost(),estimate.seconds(),"Fastest cost is expected seconds only");
                require(congested.path(id("s"),id("e"),0,person,vehicle).equals(route("s","short","e")),"Observed delay should reverse the choice for "+profile);
                require(fastest.path(id("s"),id("e"),0,person,vehicle).equals(selected),"Repeated pure routing is deterministic");
            }
            var turtle=person(scenario,"Tortuga");
            require(legacy.path(id("s"),id("e"),0,turtle,vehicle(scenario,turtle)).equals(route("s","short","e")),"Legacy distance preference remains explicit and experimental");
            require(fastest.path(id("s"),id("s"),0,turtle,vehicle(scenario,turtle)).equals(route("s")),"Same-link route");
            near(fastest.evaluate(route("s"),0,turtle,vehicle(scenario,turtle),Double.NaN).seconds(),0,"No fabricated turn on terminal link");

            var normal=person(scenario,"Normal");var normalVehicle=vehicle(scenario,normal);
            // These are supplied, synthetic FROM-link traversal+turn observations.
            // No penalty is invented from a signal or priority label.
            for(var item:Map.of("signal_delay_fixture",80.,"priority_delay_fixture",90.).entrySet()) {
                var delayedTurn=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->link.getId().equals(id("long"))?100:Double.NaN,
                    (from,to,time,person,vehicle)->from.getId().equals(id("long"))?item.getValue():Double.NaN,DrivingProfiles.FASTEST_TIME);
                near(delayedTurn.evaluate(route("s","long","e"),0,normal,normalVehicle,Double.NaN).seconds(),1+item.getValue(),"Observed FROM-link time charged once for "+item.getKey());
                require(delayedTurn.path(id("s"),id("e"),0,normal,normalVehicle).equals(route("s","short","e")),"Backed turn delay affects candidate "+item.getKey());
            }
            var missingTurn=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->link.getId().equals(id("long"))?100:Double.NaN,
                (from,to,time,person,vehicle)->Double.NaN,DrivingProfiles.FASTEST_TIME);
            near(missingTurn.evaluate(route("s","long","e"),0,normal,normalVehicle,Double.NaN).seconds(),101,"Missing turn retains backed FROM-link delay");
            var calls=new ArrayList<String>();
            var residual=new SimZ1TurnRouter(network,safety,(link,time,person,vehicle)->Double.NaN,
                (from,to,time,person,vehicle)->{calls.add(from.getId()+"@"+time);return from.getId().equals(id("s"))?20:80;},DrivingProfiles.FASTEST_TIME);
            near(residual.evaluate(route("s","long","e"),5,normal,normalVehicle,0).seconds(),95,"Subtract only elapsed current-link time");
            require(calls.equals(List.of("s@0.0","long@20.0")),"Turn time must use FROM entry clock: "+calls);
            calls.clear();near(residual.evaluate(route("s","long","e"),5,normal,normalVehicle,Double.NaN).seconds(),100,"Unknown entry retains full estimate");
            require(calls.equals(List.of("s@5.0","long@25.0")),"Unknown entry clock convention: "+calls);
            rejects(()->residual.evaluate(route("s","long","e"),5,normal,normalVehicle,6));

            var returned=fixture();add(returned.getNetwork(),"return",2,0,10,10);
            var laneFactory=returned.getLanes().getFactory();var assignment=laneFactory.createLanesToLinkAssignment(id("s"));
            LanesUtils.createAndAddLane(assignment,laneFactory,lane("long-only"),1000,5,-1,1,route("long"),null);
            LanesUtils.createAndAddLane(assignment,laneFactory,lane("short-only"),1000,5,1,1,route("short"),null);
            LanesUtils.createAndAddLane(assignment,laneFactory,lane("original"),2000,10,0,1,null,List.of(lane("long-only"),lane("short-only")));
            returned.getLanes().addLanesToLinkAssignment(assignment);returned.getConfig().qsim().setUseLanes(true);
            var returnRouter=new SimZ1TurnRouter(returned.getNetwork(),new SimZ1RouteSafety(returned),(link,time,person,vehicle)->Double.NaN);
            var returnPerson=person(returned,"Normal");var returnVehicle=vehicle(returned,returnPerson);
            var legalReturn=returnRouter.path(id("s"),id("short"),5,returnPerson,returnVehicle,lane("long-only"),0);
            require(route("s","long","return","s","short").equals(legalReturn),"Actual lane constrains first occurrence, not legal later return: "+legalReturn);
            near(returnRouter.evaluate(legalReturn,5,returnPerson,returnVehicle,0).seconds(),16.4,"Current-link elapsed time subtracted only on first occurrence");

            var observations=new CongestionAwareRerouting(scenario);var observedVehicle=Id.createVehicleId("observed");
            observations.handleEvent(new LinkEnterEvent(10,observedVehicle,id("s")));
            observations.handleEvent(new LinkLeaveEvent(30,observedVehicle,id("s")));
            observations.handleEvent(new LinkEnterEvent(30,observedVehicle,id("long")));
            near(observations.observedLinkSeconds(id("s"),30),20,"Link observation from paired native events");
            near(observations.observedTurnSeconds(id("s"),id("long"),30),20,"Turn observation uses FROM entry to TO entry");
            near(observations.observedTurnSeconds(id("s"),id("long"),330),20,"Observation TTL inclusive boundary");
            require(Double.isNaN(observations.observedTurnSeconds(id("s"),id("long"),29)),"Future evidence must not leak backward");
            require(Double.isNaN(observations.observedTurnSeconds(id("s"),id("long"),330.001)),"Expired evidence is missing, not zero");
            observations.reset(1);require(Double.isNaN(observations.observedTurnSeconds(id("s"),id("long"),30)),"Observation state resets between iterations");

            restrictToLong(scenario);var restrictedSafety=new SimZ1RouteSafety(scenario);
            var restricted=new SimZ1TurnRouter(network,restrictedSafety,(link,time,person,vehicle)->link.getId().equals(id("long"))?100:Double.NaN,null,DrivingProfiles.FASTEST_TIME);
            require(restrictedSafety.validateNetwork(route("s","short","e")).contains("forbidden_movement"),"Restricted movement fixture");
            for(String profile:List.of("Tortuga","Normal","Liebre")) {
                var person=person(scenario,profile);var vehicle=vehicle(scenario,person);
                require(restricted.path(id("s"),id("e"),0,person,vehicle,lane("only-long"),Double.NaN).equals(route("s","long","e")),"Lower time never bypasses native lane restriction for "+profile);
            }
            require(restricted.path(id("s"),id("e"),0,normal,normalVehicle,lane("missing"),Double.NaN)==null,"Unknown occupied lane must fail closed");
            require(!CongestionAwareRerouting.shouldInstall(false,100,50),"Disabled rerouting cannot install an improvement");
            require(CongestionAwareRerouting.shouldInstall(true,100,50),"Enabled routing accepts strict expected-time improvement");
            require(!CongestionAwareRerouting.shouldInstall(true,50,100),"Worse candidate rejected");
            require(!CongestionAwareRerouting.shouldInstall(true,50,50),"Equal candidate rejected");
            require(!CongestionAwareRerouting.shouldInstall(true,50,50-1e-10),"Numerical noise is not an improvement");
            rejects(()->CongestionAwareRerouting.shouldInstall(true,Double.NaN,50));
            rejects(()->CongestionAwareRerouting.shouldInstall(true,50,Double.POSITIVE_INFINITY));
            require(!CongestionAwareRerouting.needsReroute(false,10,100,100,10),"Disabled congestion gate");
            require(!CongestionAwareRerouting.needsReroute(true,10,30,100,100),"Ratio alone is insufficient without60 s excess");
            require(CongestionAwareRerouting.needsReroute(true,10,70,100,100),"Existing duration threshold boundary");
            require(CongestionAwareRerouting.needsReroute(true,10,10,100,50),"Existing capacity threshold boundary");
            require(!CongestionAwareRerouting.needsReroute(true,10,10,100,51),"No severe delay/capacity evidence");
            rejects(()->CongestionAwareRerouting.needsReroute(true,Double.NaN,100,100,100));
            System.out.println("PASS: all three profiles choose fastest expected time, observed delay reverses choice, explicit legacy policy remains separate");
            System.out.println("PASS: FROM-link/turn timing, no double-counted delay, current-link residual, forbidden turn and actual lane constraints");
            System.out.println("PASS: pure rerouting off/on improvement gate; no QSim or claim of physical paired-run outcomes");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
