package gt.edu.uvg.sim.labs;

import java.security.SecureRandom;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;

/** One stochastic focal journey. QSim models travel times; Python integrates acceleration. */
public final class Lab08Zona1Network {
    public static void main(String[] args) {
        String output = parseOutput(args);
        SecureRandom random = new SecureRandom();
        String profile = List.of("normal", "tortuga", "liebre").get(random.nextInt(3));
        double variation;
        do { variation = 1 + .05 * random.nextGaussian(); } while (variation < .8 || variation > 1.2);
        Config config = ConfigUtils.createConfig();
        config.global().setCoordinateSystem("EPSG:32615");
        config.global().setRandomSeed(random.nextLong());
        config.controler().setOutputDirectory(output);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.failIfDirectoryExists);
        config.controler().setLastIteration(0);
        config.qsim().setUseLanes(false); // Link lane counts; no explicit turning-lane file.
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(86400);
        config.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(1).setScoringThisActivityAtAll(false));
        config.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(86400));
        Scenario scenario = ScenarioUtils.createScenario(config);
        buildNetwork(scenario.getNetwork());
        // A single agent permits profile-dependent free speeds without changing other users.
        for (Link link : scenario.getNetwork().getLinks().values()) {
            double nominal = link.getFreespeed();
            link.getAttributes().putAttribute("focalBaseSpeed", nominal);
            link.getAttributes().putAttribute("focalProfile", profile);
            link.getAttributes().putAttribute("individualSpeedFactor", variation);
            link.getAttributes().putAttribute("maxActiveVehicles", 1);
            link.setFreespeed(variation * (profile.equals("tortuga") ? 3.0 : nominal * (profile.equals("liebre") ? 1.5 : 1.0)));
        }
        var attributes = scenario.getNetwork().getAttributes();
        attributes.putAttribute("focalProfile", profile);
        attributes.putAttribute("playbackScale", 120.0);
        attributes.putAttribute("dayDuration", 86400);
        attributes.putAttribute("dailyAgents", 1);
        attributes.putAttribute("persistentFocal", true);
        List<? extends Link> links = scenario.getNetwork().getLinks().values().stream()
                .filter(l -> !Boolean.FALSE.equals(l.getAttributes().getAttribute("routingEligible")))
                .sorted(Comparator.comparing(l -> l.getId().toString())).toList();
        if (links.isEmpty()) throw new IllegalStateException("No drivable links in Zona 1");
        Link origin = links.get(random.nextInt(links.size()));
        // Reachability is checked explicitly, including incomplete streets.
        Set<Id<org.matsim.api.core.v01.network.Node>> reached = new HashSet<>();
        var queue = new ArrayDeque<org.matsim.api.core.v01.network.Node>();
        queue.add(origin.getToNode());
        while (!queue.isEmpty()) {
            var node = queue.remove();
            if (reached.add(node.getId())) node.getOutLinks().values().forEach(l -> queue.add(l.getToNode()));
        }
        var destinations = links.stream().filter(l -> l != origin && reached.contains(l.getFromNode().getId())).toList();
        if (destinations.isEmpty()) throw new IllegalStateException("No reachable destination");
        Link destination = destinations.get(random.nextInt(destinations.size()));
        var factory = scenario.getPopulation().getFactory();
        Person person = factory.createPerson(Id.createPersonId("focal"));
        person.getAttributes().putAttribute("drivingProfile", profile);
        person.getAttributes().putAttribute("individualSpeedFactor", variation);
        person.getAttributes().putAttribute("vehicleLength", 4.5);
        person.getAttributes().putAttribute("vehicleWidth", 1.8);
        var vehicles = scenario.getVehicles();
        var vehicleType = vehicles.getFactory().createVehicleType(Id.create("focal-car", org.matsim.vehicles.VehicleType.class));
        vehicleType.setLength(4.5);
        vehicleType.setWidth(1.8);
        vehicles.addVehicleType(vehicleType);
        vehicles.addVehicle(vehicles.getFactory().createVehicle(Id.createVehicleId("focal"), vehicleType));
        person.getAttributes().putAttribute("clockUnit", "simulated hours; seconds / 3600");
        Plan plan = factory.createPlan();
        Activity home = factory.createActivityFromLinkId("home", origin.getId());
        home.setEndTime(0);
        plan.addActivity(home);
        person.getAttributes().putAttribute("theoreticalDestination", destination.getId().toString());
        List<Link> cycle = new ArrayList<>();
        cycle.add(origin);
        cycle.addAll(path(origin.getToNode(), destination.getFromNode()));
        cycle.add(destination);
        cycle.addAll(path(destination.getToNode(), origin.getFromNode()));
        List<Id<Link>> itinerary = new ArrayList<>();
        double duration = 0;
        while (duration < 90000) {
            for (Link link : cycle) {
                itinerary.add(link.getId());
                duration += link.getLength() / link.getFreespeed();
            }
        }
        var route = org.matsim.core.population.routes.RouteUtils.createLinkNetworkRouteImpl(
                itinerary.get(0), itinerary.get(itinerary.size() - 1));
        route.setLinkIds(itinerary.get(0), itinerary.subList(1, itinerary.size()-1), itinerary.get(itinerary.size() - 1));
        Leg leg = factory.createLeg(TransportMode.car);
        leg.setRoute(route);
        plan.addLeg(leg);
        plan.addActivity(factory.createActivityFromLinkId("work", itinerary.get(itinerary.size() - 1)));
        person.addPlan(plan);
        scenario.getPopulation().addPerson(person);
        System.out.printf("Lab08 profile=%s origin=%s destination=%s; clock 120x%n", profile, origin.getId(), destination.getId());
        new Controler(scenario).run();
    }

    static String parseOutput(String[] args) {
        if (args.length == 0) return "output/labs/08-zona1-warped";
        String[] tokens = args;
        if (args.length == 1) tokens = args[0].strip().split("\\s+", 2);
        if (tokens.length != 2 || !"--output".equals(tokens[0]))
            throw new IllegalArgumentException("Usage: --output directory");
        String output = tokens[1].strip();
        if (output.length() >= 2 &&
                ((output.startsWith("\"") && output.endsWith("\"")) ||
                 (output.startsWith("'") && output.endsWith("'")))) {
            output = output.substring(1, output.length()-1);
        }
        if (output.isBlank()) throw new IllegalArgumentException("Output directory cannot be empty");
        return output;
    }

    static void buildNetwork(org.matsim.api.core.v01.network.Network net) {
        Zona1BaseNetwork.build(net);
    }

    private static List<Link> path(org.matsim.api.core.v01.network.Node start, org.matsim.api.core.v01.network.Node end) {
        Map<Id<org.matsim.api.core.v01.network.Node>,Link> parents = new HashMap<>();
        var queue = new ArrayDeque<org.matsim.api.core.v01.network.Node>();
        Set<Id<org.matsim.api.core.v01.network.Node>> seen = new HashSet<>();
        queue.add(start); seen.add(start.getId());
        while (!queue.isEmpty()) {
            var n = queue.remove();
            for (Link l : n.getOutLinks().values()) if (l.getAllowedModes().contains(TransportMode.car) && seen.add(l.getToNode().getId())) {
                parents.put(l.getToNode().getId(),l); queue.add(l.getToNode());
            }
        }
        List<Link> result = new ArrayList<>();
        while (!end.equals(start)) {
            Link l = parents.get(end.getId());
            if (l == null) throw new IllegalStateException("Unreachable destination");
            result.add(l); end=l.getFromNode();
        }
        Collections.reverse(result);
        return result;
    }
}
