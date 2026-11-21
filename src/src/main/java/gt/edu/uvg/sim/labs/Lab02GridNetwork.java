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
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;

public class Lab02GridNetwork {

    public static void main(String[] args) {
        // 1. Configuración de directorio de salida
        Config config = ConfigUtils.createConfig();
        String outputDir = "output/labs/02-grid-network";
        config.controler().setOutputDirectory(outputDir);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.deleteDirectoryIfExists);
        config.controler().setLastIteration(0);

        // 2. Parámetros de scoring requeridos
        ActivityParams homeParams = new ActivityParams("home");
        homeParams.setTypicalDuration(12 * 3600);
        config.planCalcScore().addActivityParams(homeParams);

        ActivityParams workParams = new ActivityParams("work");
        workParams.setTypicalDuration(8 * 3600);
        config.planCalcScore().addActivityParams(workParams);

        Scenario scenario = ScenarioUtils.createScenario(config);
        Network network = scenario.getNetwork();
        NetworkFactory netFactory = network.getFactory();

        // 3. Crear Malla 3x3 de Nodos (espaciados cada 500m)
        int gridSize = 3;
        double spacing = 500.0;

        for (int x = 0; x < gridSize; x++) {
            for (int y = 0; y < gridSize; y++) {
                String nodeId = x + "_" + y;
                Node node = netFactory.createNode(Id.createNodeId(nodeId), new Coord(x * spacing, y * spacing));
                network.addNode(node);
            }
        }

        createGridLinks(network, netFactory, gridSize);

        // 4. Crear Población de 10 Agentes con Rutas Diversas
        Population population = scenario.getPopulation();
        PopulationFactory popFactory = population.getFactory();

        // Pares de orígenes y destinos distribuidos por toda la malla
        String[][] diverseRoutes = {
            {"link_0_0_to_1_0", "link_1_2_to_2_2"}, // Diagonal principal
            {"link_0_2_to_1_2", "link_1_0_to_2_0"}, // Diagonal inversa
            {"link_0_0_to_0_1", "link_2_1_to_2_2"}, // Lateral izquierdo a superior
            {"link_2_0_to_2_1", "link_0_1_to_0_2"}, // Lateral derecho a izquierdo
            {"link_1_0_to_1_1", "link_1_1_to_1_2"}, // Centro vertical norte
            {"link_0_1_to_1_1", "link_1_1_to_2_1"}, // Centro horizontal este
            {"link_2_2_to_1_2", "link_1_0_to_0_0"}, // Retorno superior a inferior
            {"link_0_2_to_0_1", "link_2_1_to_2_0"}, // Esquina sup-izq a inf-der
            {"link_1_2_to_1_1", "link_1_1_to_1_0"}, // Centro vertical sur
            {"link_0_0_to_0_1", "link_2_2_to_1_2"}  // Origen inferior a centro-derecha
        };

        for (int i = 1; i <= 10; i++) {
            Person person = popFactory.createPerson(Id.createPersonId("agente_" + i));
            Plan plan = popFactory.createPlan();

            String startLink = diverseRoutes[i - 1][0];
            String endLink = diverseRoutes[i - 1][1];

            Activity actHome = popFactory.createActivityFromLinkId("home", Id.createLinkId(startLink));
            // TODOS salen exactamente al mismo tiempo: 08:00:00 AM
            actHome.setEndTime(8 * 3600);
            plan.addActivity(actHome);

            Leg leg = popFactory.createLeg(TransportMode.car);
            plan.addLeg(leg);

            Activity actWork = popFactory.createActivityFromLinkId("work", Id.createLinkId(endLink));
            plan.addActivity(actWork);

            person.addPlan(plan);
            population.addPerson(person);
        }

        // 5. Ejecutar Simulación
        Controler controler = new Controler(scenario);
        controler.run();

        System.out.println(">>> Laboratorio 02 (Red en Malla Multiruta Simultánea) Finalizado con Éxito.");
    }

    private static void createGridLinks(Network network, NetworkFactory netFactory, int gridSize) {
        for (int x = 0; x < gridSize; x++) {
            for (int y = 0; y < gridSize; y++) {
                if (x < gridSize - 1) {
                    addBidirectionalLink(network, netFactory, x + "_" + y, (x + 1) + "_" + y, 500.0);
                }
                if (y < gridSize - 1) {
                    addBidirectionalLink(network, netFactory, x + "_" + y, x + "_" + (y + 1), 500.0);
                }
            }
        }
    }

    private static void addBidirectionalLink(Network network, NetworkFactory netFactory, String fromId, String toId, double length) {
        Node fromNode = network.getNodes().get(Id.createNodeId(fromId));
        Node toNode = network.getNodes().get(Id.createNodeId(toId));

        Link link1 = netFactory.createLink(Id.createLinkId("link_" + fromId + "_to_" + toId), fromNode, toNode);
        link1.setLength(length);
        link1.setFreespeed(13.8889);
        link1.setCapacity(1000.0);
        link1.setNumberOfLanes(1.0);
        network.addLink(link1);

        Link link2 = netFactory.createLink(Id.createLinkId("link_" + toId + "_to_" + fromId), toNode, fromNode);
        link2.setLength(length);
        link2.setFreespeed(13.8889);
        link2.setCapacity(1000.0);
        link2.setNumberOfLanes(1.0);
        network.addLink(link2);
    }
}