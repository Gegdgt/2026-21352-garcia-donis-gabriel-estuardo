package gt.edu.uvg.sim.labs;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;

/** Synthetic intermediate scenario: 10 x 10 blocks, coordinates in metres.
 * The central crossing is replaced by a clockwise roundabout (no central node).
 * Parking is a three-second activity, not a QSim in-lane obstruction.
 */
public final class Lab05MiniCityNetwork {
    private static final double SPACING = 1000, LOCAL_SPEED = 8.33, BYPASS_SPEED = 22.22;
    private Lab05MiniCityNetwork() { }

    public static void main(String[] args) {
        int agents = 400, iterations = 10;
        String output = "output/labs/05-mini-city";
        for (int i = 0; i < args.length; i++) {
            if (i + 1 == args.length) throw new IllegalArgumentException("Missing option value");
            switch (args[i]) {
                case "--agents" -> agents = Integer.parseInt(args[++i]);
                case "--iter" -> iterations = Integer.parseInt(args[++i]);
                case "--output" -> output = args[++i];
                default -> throw new IllegalArgumentException("Usage: --agents 250..500 --iter N --output directory");
            }
        }
        if (agents < 250 || agents > 500 || iterations < 1)
            throw new IllegalArgumentException("Use 250..500 agents and at least one iteration");
        Config config = ConfigUtils.createConfig();
        config.global().setRandomSeed(42);
        config.controler().setOutputDirectory(output);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.failIfDirectoryExists);
        config.controler().setFirstIteration(0);
        config.controler().setLastIteration(iterations - 1);
        config.controler().setWriteEventsInterval(1);
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(24 * 3600);
        config.qsim().setTimeStepSize(1);
        config.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(12 * 3600));
        config.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(8 * 3600));
        config.planCalcScore().addActivityParams(new ActivityParams("parking").setTypicalDuration(3).setScoringThisActivityAtAll(false));
        StrategySettings reroute = new StrategySettings();
        reroute.setStrategyName("ReRoute");
        reroute.setWeight(.2);
        config.strategy().addStrategySettings(reroute);
        StrategySettings retain = new StrategySettings();
        retain.setStrategyName("ChangeExpBeta");
        retain.setWeight(.8);
        config.strategy().addStrategySettings(retain);
        Scenario scenario = ScenarioUtils.createScenario(config);
        buildNetwork(scenario.getNetwork());
        validateNetwork(scenario.getNetwork());
        buildPopulation(scenario, agents);
        System.out.printf("Lab05: %d nodes, %d links, %d agents, %d iterations%n",
                scenario.getNetwork().getNodes().size(), scenario.getNetwork().getLinks().size(), agents, iterations);
        new Controler(scenario).run();
    }

    private static String grid(int x, int y) { return "G_" + x + "_" + y; }

    public static void buildNetwork(Network network) {
        if (!network.getNodes().isEmpty()) throw new IllegalArgumentException("Expected an empty network");
        network.setCapacityPeriod(3600);
        network.getAttributes().putAttribute("geometrySource", "synthetic mini-city, metres");
        network.getAttributes().putAttribute("parkingDuration", 3.0);
        for (int x = 0; x <= 10; x++) for (int y = 0; y <= 10; y++) {
            if (x != 5 || y != 5) node(network, grid(x, y), x * SPACING, y * SPACING);
        }
        for (int i = 0; i < 8; i++) {
            double angle = -i * Math.PI / 4;
            node(network, "R_" + i, 5000 + 250 * Math.cos(angle), 5000 + 250 * Math.sin(angle));
        }
        for (int i = 0; i < 8; i++)
            road(network, "ROUND_" + i, "R_" + i, "R_" + ((i + 1) % 8), "roundabout", 5.56, 600, 1);
        for (int x = 0; x <= 10; x++) for (int y = 0; y <= 10; y++) {
            if (x < 10) {
                String a = crossing(x, y, x + 1, y), b = crossing(x + 1, y, x, y);
                road(network, "H_" + x + "_" + y, y % 2 == 0 ? a : b, y % 2 == 0 ? b : a,
                        "local", LOCAL_SPEED, 600, 1);
            }
            if (y < 10) {
                String a = crossing(x, y, x, y + 1), b = crossing(x, y + 1, x, y);
                road(network, "V_" + x + "_" + y, x % 2 == 0 ? a : b, x % 2 == 0 ? b : a,
                        "local", LOCAL_SPEED, 600, 1);
            }
        }
        // Alternating entry/exit spokes, without opposite links on the same segment.
        road(network, "DIAG_NW", grid(4, 6), "R_5", "diagonal", 13.89, 1000, 1);
        road(network, "DIAG_NE", "R_7", grid(6, 6), "diagonal", 13.89, 1000, 1);
        road(network, "DIAG_SW", grid(4, 4), "R_3", "diagonal", 13.89, 1000, 1);
        road(network, "DIAG_SE", "R_1", grid(6, 4), "diagonal", 13.89, 1000, 1);
        buildBypass(network);
        buildWing(network, false);
        buildWing(network, true);
    }

    private static String crossing(int x, int y, int otherX, int otherY) {
        if (x != 5 || y != 5) return grid(x, y);
        if (otherX > 5) return "R_0";
        if (otherX < 5) return "R_4";
        return otherY > 5 ? "R_6" : "R_2";
    }

    private static void buildBypass(Network network) {
        List<int[]> perimeter = new ArrayList<>();
        for (int y = 0; y < 10; y++) perimeter.add(new int[]{0, y});
        for (int x = 0; x < 10; x++) perimeter.add(new int[]{x, 10});
        for (int y = 10; y > 0; y--) perimeter.add(new int[]{10, y});
        for (int x = 10; x > 0; x--) perimeter.add(new int[]{x, 0});
        for (int i = 0; i < perimeter.size(); i++) {
            int[] p = perimeter.get(i);
            node(network, "B_" + i, outer(p[0]), outer(p[1]));
        }
        for (int i = 0; i < perimeter.size(); i++) {
            int next = (i + 1) % perimeter.size();
            int[] p = perimeter.get(i);
            road(network, "BYPASS_" + i, "B_" + i, "B_" + next, "bypass", BYPASS_SPEED, 2400, 2);
            road(network, "ENTRY_" + i, "B_" + i, grid(p[0], p[1]), "ramp", LOCAL_SPEED, 900, 1);
            road(network, "EXIT_" + i, grid(p[0], p[1]), "B_" + next, "ramp", LOCAL_SPEED, 900, 1);
        }
    }

    private static double outer(int value) {
        return value == 0 ? -500 : value == 10 ? 10500 : value * SPACING;
    }

    private static void buildWing(Network network, boolean mirrored) {
        // Each detour lies inside a grid block, joining existing corners. Thus
        // geometric crossings never masquerade as unconnected intersections.
        double[][] offsets = {{.35, .15}, {.35, .65}, {.8, .65}};
        String side = mirrored ? "RIGHT" : "LEFT";
        for (int block = 0; block < 3; block++) {
            int y = block == 0 ? 2 : 3;
            String previous = grid(mirrored ? 10 - block : block, y);
            for (int j = 0; j < offsets.length; j++) {
                double x = block + offsets[j][0];
                String id = "W_" + side + "_" + block + "_" + j;
                node(network, id, (mirrored ? 10 - x : x) * SPACING, (y + offsets[j][1]) * SPACING);
                road(network, "WING_" + side + "_" + block + "_" + j, previous, id, "wing", LOCAL_SPEED, 600, 1);
                previous = id;
            }
            road(network, "WING_" + side + "_" + block + "_END", previous,
                    grid(mirrored ? 9 - block : block + 1, y + 1), "wing", LOCAL_SPEED, 600, 1);
        }
    }

    private static void node(Network net, String id, double x, double y) {
        net.addNode(net.getFactory().createNode(Id.createNodeId(id), new Coord(x, y)));
    }

    private static void road(Network net, String id, String from, String to, String kind,
                             double speed, double capacity, int lanes) {
        Node a = net.getNodes().get(Id.createNodeId(from)), b = net.getNodes().get(Id.createNodeId(to));
        if (a == null || b == null || a == b) throw new IllegalStateException("Invalid endpoints: " + id);
        Link link = net.getFactory().createLink(Id.createLinkId(id), a, b);
        link.setLength(Math.hypot(b.getCoord().getX() - a.getCoord().getX(), b.getCoord().getY() - a.getCoord().getY()));
        link.setFreespeed(speed);
        link.setCapacity(capacity);
        link.setNumberOfLanes(lanes);
        link.setAllowedModes(Set.of(TransportMode.car));
        link.getAttributes().putAttribute("roadClass", kind);
        link.getAttributes().putAttribute("laneWidth", 3.2);
        net.addLink(link);
    }

    /** Strong connectivity in both directions; never silently delete disconnected nodes. */
    public static void validateNetwork(Network net) {
        if (net.getNodes().isEmpty()) throw new IllegalStateException("Empty network");
        for (boolean reverse : new boolean[]{false, true}) {
            Set<Id<Node>> reached = new HashSet<>();
            Deque<Node> queue = new ArrayDeque<>();
            queue.add(net.getNodes().values().iterator().next());
            while (!queue.isEmpty()) {
                Node n = queue.remove();
                if (!reached.add(n.getId())) continue;
                for (Link link : (reverse ? n.getInLinks() : n.getOutLinks()).values())
                    queue.add(reverse ? link.getFromNode() : link.getToNode());
            }
            if (reached.size() != net.getNodes().size()) throw new IllegalStateException("Network is not strongly connected");
        }
    }

    private static void buildPopulation(Scenario scenario, int count) {
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        List<? extends Link> boundary = scenario.getNetwork().getLinks().values().stream()
                .filter(l -> l.getId().toString().startsWith("BYPASS_"))
                .sorted(Comparator.comparing(l -> l.getId().toString())).toList();
        List<? extends Link> parkingLinks = scenario.getNetwork().getLinks().values().stream()
                .filter(l -> "local".equals(l.getAttributes().getAttribute("roadClass")))
                .sorted(Comparator.comparing(l -> l.getId().toString())).toList();
        Random random = new Random(42);
        for (int i = 0; i < count; i++) {
            Link homeLink = boundary.get(i % boundary.size());
            Link workLink = boundary.get((i + 10 + random.nextInt(20)) % boundary.size());
            Link parkingLink = parkingLinks.get(random.nextInt(parkingLinks.size()));
            Person person = factory.createPerson(Id.createPersonId("mini_" + i));
            Plan plan = factory.createPlan();
            Activity home = factory.createActivityFromLinkId("home", homeLink.getId());
            home.setEndTime(7 * 3600 + random.nextInt(1800));
            plan.addActivity(home);
            plan.addLeg(factory.createLeg(TransportMode.car));
            Activity parking = factory.createActivityFromLinkId("parking", parkingLink.getId());
            parking.setMaximumDuration(3.0);
            plan.addActivity(parking);
            plan.addLeg(factory.createLeg(TransportMode.car));
            plan.addActivity(factory.createActivityFromLinkId("work", workLink.getId()));
            person.addPlan(plan);
            population.addPerson(person);
        }
    }
}
