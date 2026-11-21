package gt.edu.uvg.sim.zona1;

import java.util.Set;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;

public final class LanesTopologyCheck {
    public static void main(String[] args) {
        checkConservation();
        for (String mode : new String[]{"valid", "multiple-exits", "dead-end", "pedestrian", "coincident", "nonfinite", "unregistered", "wrong-node", "missing-outlink"}) {
            var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
            var net=scenario.getNetwork(); var f=net.getFactory();
            var a=f.createNode(Id.createNodeId("a"),new Coord(0,0));
            var b=f.createNode(Id.createNodeId("b"),new Coord(100,0));
            var c=f.createNode(Id.createNodeId("c"),new Coord(mode.equals("nonfinite")?Double.NaN:mode.equals("coincident")?100:200,0));
            net.addNode(a);net.addNode(b);net.addNode(c);
            var in=f.createLink(Id.createLinkId("in"),a,b);
            in.setLength(100);in.setCapacity(4000);in.setFreespeed(10);in.setNumberOfLanes(2);in.setAllowedModes(Set.of("car"));net.addLink(in);
            if (!mode.equals("dead-end")) {
                var out=f.createLink(Id.createLinkId("out"),b,c);
                out.setLength(100);out.setCapacity(2000);out.setFreespeed(10);out.setNumberOfLanes(1);
                out.setAllowedModes(Set.of(mode.equals("pedestrian")?"walk":"car"));net.addLink(out);
                if (mode.equals("missing-outlink")) {
                    b.removeOutLink(out.getId()); // Globally registered, absent from receiving node exits.
                }
                if (mode.equals("unregistered")) {
                    net.removeLink(out.getId());
                    b.addOutLink(out); // Deliberately stale adjacency reference.
                }
                if (mode.equals("wrong-node")) {
                    var unrelated=f.createLink(Id.createLinkId("unrelated"),c,a);
                    unrelated.setLength(200);unrelated.setCapacity(2000);unrelated.setFreespeed(10);
                    unrelated.setAllowedModes(Set.of("car"));net.addLink(unrelated);
                    b.addOutLink(unrelated); // Exists globally, but does not originate at b.
                }
            }
            if (mode.equals("multiple-exits")) {
                for (var destination : java.util.List.of(a, c)) {
                    var exit = f.createLink(Id.createLinkId("exit-" + destination.getId()), b, destination);
                    exit.setLength(100);exit.setCapacity(2000);exit.setFreespeed(10);
                    exit.setNumberOfLanes(1);exit.setAllowedModes(Set.of("car"));net.addLink(exit);
                }
            }
            LanesGenerator.build(scenario);
            var assignment=scenario.getLanes().getLanesToLinkAssignments().get(in.getId());
            if (!mode.equals("valid") && !mode.equals("multiple-exits")) {
                if (assignment!=null) throw new AssertionError("Unsafe assignment: "+mode);
            } else {
                if (assignment==null || assignment.getLanes().size()!=3) throw new AssertionError("Missing valid assignment");
                for (var lane:assignment.getLanes().values()) {
                    if (lane.getId().toString().endsWith("original")) {
                        if (lane.getToLaneIds().size()!=2) throw new AssertionError("Missing internal lane queues");
                    } else if (!Set.copyOf(lane.getToLinkIds()).equals(b.getOutLinks().keySet())) {
                        throw new AssertionError("Missing outgoing link on terminal lane");
                    }
                }
            }
        }
        System.out.println("PASS: terminal exits, original lane graph, dead ends, pedestrian-only, ambiguous coordinates, stale references, wrong receiving node");
        org.apache.logging.log4j.LogManager.shutdown();
    }

    private static void checkConservation() {
        for (int count : new int[]{1, 2, 3})
            for (double length : new double[]{0.1, 6, 7.5, 100, 150, 1000})
                for (double capacityPeriod : new double[]{1800, 3600, 86400}) {
                    var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
                    var net = scenario.getNetwork(); var f = net.getFactory();
                    net.setCapacityPeriod(capacityPeriod);
                    var a = f.createNode(Id.createNodeId("a"), new Coord(0, 0));
                    var b = f.createNode(Id.createNodeId("b"), new Coord(length, 0));
                    var c = f.createNode(Id.createNodeId("c"), new Coord(length + 100, 100));
                    net.addNode(a); net.addNode(b); net.addNode(c);
                    var in = f.createLink(Id.createLinkId("in"), a, b);
                    in.setLength(length); in.setNumberOfLanes(count); in.setCapacity(1800);
                    in.setFreespeed(10); in.setAllowedModes(Set.of("car")); net.addLink(in);
                    // A return movement is intentional and must remain available.
                    for (var node : java.util.List.of(a, c)) {
                        var out = f.createLink(Id.createLinkId("out-" + node.getId()), b, node);
                        out.setLength(100); out.setNumberOfLanes(1); out.setCapacity(1800);
                        out.setFreespeed(10); out.setAllowedModes(Set.of("car")); net.addLink(out);
                    }
                    LanesGenerator.build(scenario);
                    var assignment = scenario.getLanes().getLanesToLinkAssignments().get(in.getId());
                    var models = org.matsim.lanes.LanesUtils.createLanes(in, assignment);
                    double weightedLength = 0, terminalFlow = 0, originalLength = -1;
                    double terminalLength = Math.min(100, length * .8);
                    for (var model : models) {
                        var lane = model.getLaneData();
                        require(model.getLength() > 0, "Non-positive effective queue length");
                        weightedLength += model.getLength() * lane.getNumberOfRepresentedLanes();
                        if (lane.getToLinkIds() != null && !lane.getToLinkIds().isEmpty()) {
                            close(model.getLength(), terminalLength, "Terminal effective length");
                            close(lane.getNumberOfRepresentedLanes(), 1, "Terminal represented lanes");
                            require(Set.copyOf(lane.getToLinkIds()).equals(b.getOutLinks().keySet()), "Lost exit or return movement");
                            terminalFlow += lane.getCapacityVehiclesPerHour();
                        } else {
                            originalLength = model.getLength();
                            close(lane.getNumberOfRepresentedLanes(), count, "Original represented lanes");
                            close(lane.getCapacityVehiclesPerHour(), 1800 * 3600 / capacityPeriod, "Original flow");
                            require(lane.getToLaneIds().size() == count, "Missing downstream queue");
                        }
                    }
                    close(weightedLength, count * length, "Represented-lane weighted length");
                    close(originalLength + terminalLength, length, "Path effective length");
                    close(terminalFlow, 1800 * 3600 / capacityPeriod, "Terminal flow conservation");
                    close(in.getLength(), length, "Generator changed link length");
                    close(in.getCapacity(), 1800, "Generator changed link capacity");
                    close(in.getNumberOfLanes(), count, "Generator changed represented lanes");
                }
        System.out.println("PASS: 54 length/lane/capacity-period combinations preserve effective lengths, terminal flow and return movements");
    }
    private static void close(double actual, double expected, String description) {
        require(Math.abs(actual - expected) <= 1e-8 * Math.max(1, Math.abs(expected)), description + ": " + actual + " != " + expected);
    }
    private static void require(boolean valid, String message) { if (!valid) throw new AssertionError(message); }
}
