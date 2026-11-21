package gt.edu.uvg.sim.labs;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkFactory;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup.SnapshotStyle;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

public class Lab04LanesAndTurnsNetwork {

    public static void main(String[] args) {
        Config config = ConfigUtils.createConfig();
        config.qsim().setUseLanes(true);
        config.qsim().setSnapshotStyle(SnapshotStyle.queue); 
        
        String outputDir = "output/labs/04-lanes-turns";
        config.controler().setOutputDirectory(outputDir);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.deleteDirectoryIfExists);
        config.controler().setFirstIteration(0);
        config.controler().setLastIteration(10);
        config.controler().setWriteEventsInterval(1);

        // Parámetros de Actividades
        ActivityParams homeParams = new ActivityParams("home");
        homeParams.setTypicalDuration(12 * 3600);
        config.planCalcScore().addActivityParams(homeParams);

        // Actividad de Parqueo estricta de 3 segundos (bloqueo en orillas)
        ActivityParams parkParams = new ActivityParams("parking");
        parkParams.setTypicalDuration(3.0); 
        config.planCalcScore().addActivityParams(parkParams);

        ActivityParams workParams = new ActivityParams("work");
        workParams.setTypicalDuration(8 * 3600);
        config.planCalcScore().addActivityParams(workParams);

        StrategySettings reRoute = new StrategySettings();
        reRoute.setStrategyName("ReRoute");
        reRoute.setWeight(0.5);
        config.strategy().addStrategySettings(reRoute);

        StrategySettings keepPlan = new StrategySettings();
        keepPlan.setStrategyName("ChangeExpBeta");
        keepPlan.setWeight(0.5);
        config.strategy().addStrategySettings(keepPlan);

        Scenario scenario = ScenarioUtils.createScenario(config);
        Network network = scenario.getNetwork();
        NetworkFactory netFactory = network.getFactory();

        // Malla 10x10
        int gridSize = 10;
        double spacing = 400.0;

        for (int x = 0; x < gridSize; x++) {
            for (int y = 0; y < gridSize; y++) {
                String nodeId = x + "_" + y;
                Node node = netFactory.createNode(Id.createNodeId(nodeId), new Coord(x * spacing, y * spacing));
                network.addNode(node);
            }
        }

        buildDirectionalGridNetwork(network, netFactory, gridSize);
        new org.matsim.core.network.algorithms.NetworkCleaner().run(network);
        buildLanesForNetwork(scenario, network);

        // Filtrar enlaces ÚNICAMENTE en la periferia / orillas del grid para evitar spawns internos
        List<Link> boundaryLinks = new ArrayList<>();
        for (Link link : network.getLinks().values()) {
            Coord fromCoord = link.getFromNode().getCoord();
            Coord toCoord = link.getToNode().getCoord();
            boolean isFromBoundary = (fromCoord.getX() == 0 || fromCoord.getX() == (gridSize - 1) * spacing ||
                                      fromCoord.getY() == 0 || fromCoord.getY() == (gridSize - 1) * spacing);
            boolean isToBoundary = (toCoord.getX() == 0 || toCoord.getX() == (gridSize - 1) * spacing ||
                                    toCoord.getY() == 0 || toCoord.getY() == (gridSize - 1) * spacing);
            if (isFromBoundary || isToBoundary) {
                boundaryLinks.add(link);
            }
        }
        if (boundaryLinks.isEmpty()) {
            boundaryLinks = new ArrayList<>(network.getLinks().values());
        }

        // Población aumentada a 250 agentes
        Population population = scenario.getPopulation();
        PopulationFactory popFactory = population.getFactory();
        Random rand = new Random(42);

        for (int i = 1; i <= 250; i++) {
            Person person = popFactory.createPerson(Id.createPersonId("agente_" + i));
            Plan plan = popFactory.createPlan();

            // Seleccionar enlaces de inicio y fin estrictamente en los bordes/orillas
            Link startLink = boundaryLinks.get(rand.nextInt(boundaryLinks.size()));
            Link endLink = boundaryLinks.get(boundaryLinks.size() > 1 ? rand.nextInt(boundaryLinks.size()) : 0);

            Activity actHome = popFactory.createActivityFromLinkId("home", startLink.getId());
            actHome.setEndTime((8 * 3600) + rand.nextInt(300));
            plan.addActivity(actHome);

            plan.addLeg(popFactory.createLeg(TransportMode.car));

            // Actividad intermedia de parqueo de 3 segundos en orillas para evitar choques
            Activity actPark = popFactory.createActivityFromLinkId("parking", endLink.getId());
            actPark.setMaximumDuration(3.0);
            plan.addActivity(actPark);
            
            plan.addLeg(popFactory.createLeg(TransportMode.car));

            Activity actWork = popFactory.createActivityFromLinkId("work", endLink.getId());
            plan.addActivity(actWork);

            person.addPlan(plan);
            population.addPerson(person);
        }

        Controler controler = new Controler(scenario);
        controler.run();

        System.out.println(">>> Laboratorio 04 (250 Agentes, Orillas Periféricas, Velocidades Dinámicas) Finalizado con Éxito.");
    }

    private static void buildDirectionalGridNetwork(Network network, NetworkFactory netFactory, int gridSize) {
        Random randSpeed = new Random(123);
        for (int y = 0; y < gridSize; y++) {
            boolean goRight = (y % 2 == 0);
            for (int x = 0; x < gridSize - 1; x++) {
                double dynamicSpeed = 4.0 + randSpeed.nextDouble() * 9.0; // Velocidad variable entre 4 y 13 m/s
                if (goRight) {
                    addCustomLink(network, netFactory, x + "_" + y, (x + 1) + "_" + y, dynamicSpeed);
                } else {
                    addCustomLink(network, netFactory, (x + 1) + "_" + y, x + "_" + y, dynamicSpeed);
                }
            }
        }

        for (int x = 0; x < gridSize; x++) {
            boolean goUp = (x % 2 == 0);
            for (int y = 0; y < gridSize - 1; y++) {
                double dynamicSpeed = 4.0 + randSpeed.nextDouble() * 9.0; // Velocidad variable entre 4 y 13 m/s
                if (goUp) {
                    addCustomLink(network, netFactory, x + "_" + y, x + "_" + (y + 1), dynamicSpeed);
                } else {
                    addCustomLink(network, netFactory, x + "_" + (y + 1), x + "_" + y, dynamicSpeed);
                }
            }
        }
    }

    private static void addCustomLink(Network network, NetworkFactory netFactory, String fromId, String toId, double freespeed) {
        Node fromNode = network.getNodes().get(Id.createNodeId(fromId));
        Node toNode = network.getNodes().get(Id.createNodeId(toId));

        Link link = netFactory.createLink(Id.createLinkId("link_" + fromId + "_to_" + toId), fromNode, toNode);
        link.setLength(400.0);
        link.setFreespeed(freespeed); // Velocidad dinámica por enlace
        link.setCapacity(1000.0);
        link.setNumberOfLanes(1.0);
        network.addLink(link);
    }

    private static void buildLanesForNetwork(Scenario scenario, Network network) {
        Lanes lanes = scenario.getLanes();

        for (Link link : network.getLinks().values()) {
            LanesToLinkAssignment assignment = lanes.getFactory().createLanesToLinkAssignment(link.getId());

            List<Id<Link>> toLinkIds = new ArrayList<>();
            for (Link outLink : link.getToNode().getOutLinks().values()) {
                if (!outLink.getToNode().getId().equals(link.getFromNode().getId())) {
                    toLinkIds.add(outLink.getId());
                }
            }

            LanesUtils.createAndAddLane(
                    assignment,
                    lanes.getFactory(),
                    Id.create(link.getId().toString() + ".ol", Lane.class),
                    1000.0,
                    link.getLength(),
                    0,
                    1,
                    toLinkIds,
                    null
            );

            lanes.addLanesToLinkAssignment(assignment);
        }
    }
}