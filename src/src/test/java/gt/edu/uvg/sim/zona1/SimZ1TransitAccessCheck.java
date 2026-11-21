package gt.edu.uvg.sim.zona1;

import java.util.List;
import java.util.Set;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import org.matsim.vehicles.VehicleUtils;

/** Regression: an authorized bus-only exit must not break initialization or become a car turn. */
public final class SimZ1TransitAccessCheck {
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static Id<Link> id(String value) { return Id.createLinkId(value); }
    private static Id<Lane> lane(String value) { return Id.create(value,Lane.class); }
    private static Link add(Network n,String name,int from,int to,Set<String> modes) {
        var l=n.getFactory().createLink(id(name), n.getNodes().get(Id.createNodeId(from)), n.getNodes().get(Id.createNodeId(to)));
        l.setLength(100);l.setFreespeed(10);l.setCapacity(1800);l.setNumberOfLanes(1);l.setAllowedModes(modes);n.addLink(l);return l;
    }
    public static void main(String[] args) {
        var config=ConfigUtils.createConfig();config.transit().setUseTransit(true);config.qsim().setUseLanes(true);
        var s=ScenarioUtils.createScenario(config);var net=s.getNetwork();
        for(int i=0;i<6;i++)net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(i*100,(i%2)*80)));
        add(net,"mixed",0,1,Set.of("car","bus"));
        add(net,"bus-only",1,2,Set.of("bus"));
        add(net,"car-only",1,3,Set.of("car"));
        add(net,"forbidden-bus",1,4,Set.of("bus"));
        add(net,"disconnected",4,5,Set.of("bus"));
        add(net,"return-mixed",2,5,Set.of("car","bus"));
        var factory=s.getLanes().getFactory();var assignment=factory.createLanesToLinkAssignment(id("mixed"));
        LanesUtils.createAndAddLane(assignment,factory,lane("terminal"),1800,20,0,1,List.of(id("bus-only"),id("car-only")),null);
        LanesUtils.createAndAddLane(assignment,factory,lane("original"),1800,100,0,1,null,List.of(lane("terminal")));
        s.getLanes().addLanesToLinkAssignment(assignment);
        var vf=VehicleUtils.getFactory();var type=vf.createVehicleType(Id.create("fixed-bus-type",org.matsim.vehicles.VehicleType.class));
        var busId=Id.createVehicleId("fleet-001");s.getTransitVehicles().addVehicleType(type);
        s.getTransitVehicles().addVehicle(vf.createVehicle(busId,type));
        var safety=new SimZ1RouteSafety(s); // previously threw Invalid lane movement.
        check(safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("bus-only"),busId),"registered bus must use bus-only exit");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("bus-only"),Id.createVehicleId("car")),"car cannot inherit bus access");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("bus-only"),Id.createVehicleId("pt_fake")),"name is not authorization");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("car-only"),busId),"bus must respect allowed modes");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("forbidden-bus"),busId),"lane restriction applies to bus");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("terminal"),id("disconnected"),busId),"disconnected bus turn rejected");
        check(!safety.laneAllowsVehicle(id("mixed"),lane("missing"),id("bus-only"),busId),"unknown lane rejected");
        check(safety.laneAllows(id("mixed"),lane("terminal"),id("car-only")),"original car turn unchanged");
        check(!safety.successors(id("mixed")).contains(id("bus-only")),"car router remains car-only");
        check(safety.laneAllowsVehicle(id("bus-only"),null,id("return-mixed"),busId),"bus-only link can leave into mixed road");
        var current=net.getLinks().get(id("mixed"));current.getAttributes().putAttribute("simz1:priorityRole","street");
        var incomingBus=add(net,"bus-approach",3,1,Set.of("bus"));incomingBus.getAttributes().putAttribute("simz1:priorityRole","avenue");
        check(UnsignalizedPriority.eligible(current.getToNode(),Set.of()),"bus-only avenue must participate in priority");
        System.out.println("PASS: 11 bus/car permissions, lanes, identity and priority checks; no QSim run");
    }
}
