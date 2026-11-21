package gt.edu.uvg.sim.zona1;

import java.nio.file.Path;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import org.matsim.lanes.LanesWriter;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;

/**
 * Parallel downstream queues with a shared upstream queue; not surveyed turn lanes.
 * Every terminal queue permits every existing car exit, including return links.
 * An assignment is a queue graph for one link, not a count of physical lanes.
 *
 * <p>MATSim 15 LanesUtils derives the upstream queue's effective length by
 * subtracting the terminal start distance from the original lane's start
 * distance. The represented-lane weighted length therefore remains n * L,
 * and the sum of terminal flow capacities remains the link's flow capacity.
 * Native QSim still applies its storage minima, whole-vehicle admission and
 * separate time-step rounding to each queue. Those effects are measured in
 * LanesQueueCheck; they are not corrected by changing road lengths/capacities.
 * No continuous lateral movement or car-following model is introduced here.
 */
public final class LanesGenerator {
    private LanesGenerator() { }
    private static final org.apache.logging.log4j.Logger LOG = org.apache.logging.log4j.LogManager.getLogger(LanesGenerator.class);

    private static boolean validGeometry(Link link, Network network) {
        if (link.getFromNode() == null || link.getToNode() == null ||
            network.getNodes().get(link.getFromNode().getId()) != link.getFromNode() ||
            network.getNodes().get(link.getToNode().getId()) != link.getToNode()) return false;
        var a = link.getFromNode().getCoord(); var b = link.getToNode().getCoord();
        return a != null && b != null && Double.isFinite(a.getX()) && Double.isFinite(a.getY()) &&
            Double.isFinite(b.getX()) && Double.isFinite(b.getY()) &&
            (a.getX() != b.getX() || a.getY() != b.getY()) &&
            Double.isFinite(link.getLength()) && link.getLength() > 0;
    }

    /** Do not partially filter an ambiguous junction: that would silently remove route choices. */
    private static java.util.List<Id<Link>> outgoingLinks(Link link, Network network) {
        if (!validGeometry(link, network)) return java.util.List.of();
        var ids = new ArrayList<Id<Link>>();
        for (var entry : link.getToNode().getOutLinks().entrySet()) {
            var out = entry.getValue();
            if (out == null || !entry.getKey().equals(out.getId()) || network.getLinks().get(out.getId()) != out ||
                out.getFromNode() != link.getToNode()) return java.util.List.of();
            if (!out.getAllowedModes().contains("car")) continue;
            if (!validGeometry(out, network)) return java.util.List.of();
            ids.add(out.getId());
        }
        ids.sort(Comparator.comparing(Object::toString));
        return ids;
    }
    public static void build(Scenario scenario) {
        var lanes = scenario.getLanes();
        if (!lanes.getLanesToLinkAssignments().isEmpty()) throw new IllegalArgumentException("Lanes already populated");
        var factory = lanes.getFactory();
        for (var link : scenario.getNetwork().getLinks().values()) {
            if (!link.getAllowedModes().contains("car")) continue;
            double count = link.getNumberOfLanes();
            if (!Double.isFinite(count) || count < 1 || count != Math.rint(count) || count > Integer.MAX_VALUE)
                throw new IllegalArgumentException("Invalid lane count on " + link.getId());
            var outgoing = outgoingLinks(link, scenario.getNetwork());
            // Every parallel lane uses these exits. Validate before creating any
            // lane so an invalid junction cannot leave empty or dangling queues.
            boolean disconnected = outgoing.stream().anyMatch(targetId -> {
                if (!link.getToNode().getOutLinks().containsKey(targetId)) return true;
                var target = link.getToNode().getOutLinks().get(targetId);
                return target == null || target.getFromNode() != link.getToNode() ||
                    scenario.getNetwork().getLinks().get(targetId) != target;
            });
            if (outgoing.isEmpty() || disconnected) {
                LOG.warn("Skipping detailed lanes for {}: no usable car exits or ambiguous geometry/topology", link.getId());
                continue; // Keep the link and its standard QSim queue.
            }
            double length = link.getLength();
            double capacity = link.getCapacity() * 3600 / scenario.getNetwork().getCapacityPeriod();
            if (!Double.isFinite(length) || length <= 0 || !Double.isFinite(capacity) || capacity <= 0)
                throw new IllegalArgumentException("Invalid geometry/capacity on " + link.getId());
            var assignment = factory.createLanesToLinkAssignment(link.getId());
            var terminalIds = new ArrayList<Id<Lane>>();
            // Existing modelling choice, not a measured turning-pocket length.
            // startsAtMeterFromLinkEnd is a position; LanesUtils derives each
            // queue's effective length from the complete graph below.
            double queueLength = Math.min(100, length * .8);
            for (int i=0; i<(int)count; i++) {
                var id = Id.create(link.getId()+".lane."+i, Lane.class);
                terminalIds.add(id);
                LanesUtils.createAndAddLane(assignment,factory,id,capacity/count,queueLength,
                    2*i-((int)count-1),1,outgoing,null);
                var lane = assignment.getLanes().get(id);
                if (lane.getToLinkIds() == null || lane.getToLinkIds().isEmpty())
                    throw new IllegalStateException("Missing toLinkIds for terminal lane " + id);
                // Validate the actual lane references, not just the source list.
                for (var destinationId : lane.getToLinkIds()) {
                    var destination = link.getToNode().getOutLinks().get(destinationId);
                    if (destination == null || destination != scenario.getNetwork().getLinks().get(destinationId) ||
                        destination.getFromNode() != link.getToNode())
                        throw new IllegalStateException("Invalid toLinkId " + destinationId + " for lane " + id);
                }
            }
            // Shared upstream section ends where parallel queues begin, not extra road storage.
            LanesUtils.createAndAddLane(assignment,factory,Id.create(link.getId()+".original",Lane.class),
                capacity,length,0,(int)count,null,terminalIds);
            // Build the complete lane graph before publishing the assignment.
            LanesUtils.createLanes(link, assignment);
            // Every routable exit must remain reachable through a terminal queue,
            // including return links; otherwise QSim can reject a valid route turn.
            for (var outLink : link.getToNode().getOutLinks().values()) {
                if (!outLink.getAllowedModes().contains("car")) continue;
                boolean reachable = terminalIds.stream().anyMatch(laneId -> {
                    var destinations = assignment.getLanes().get(laneId).getToLinkIds();
                    return destinations != null && destinations.contains(outLink.getId());
                });
                if (!reachable)
                    throw new IllegalStateException("No terminal lane from " + link.getId() + " to " + outLink.getId());
            }
            lanes.addLanesToLinkAssignment(assignment);
        }
        scenario.getConfig().qsim().setUseLanes(true);
    }
    public static void main(String[] args) throws Exception {
        if (args.length > 2) throw new IllegalArgumentException("LanesGenerator [network.xml] [output-directory]");
        var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimNetworkReader(scenario.getNetwork()).readFile(args.length>0?args[0]:"scenarios/zona1/network.xml");
        Path output=Path.of(args.length>1?args[1]:"scenarios/zona1");
        Files.createDirectories(output);
        build(scenario);
        new LanesWriter(scenario.getLanes()).write(output.resolve("lanes.xml").toString());
        TrafficLightsGenerator.build(scenario);
        TrafficLightsGenerator.write(scenario,output);
        System.out.println("Lane assignments exported: "+scenario.getLanes().getLanesToLinkAssignments().size());
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
