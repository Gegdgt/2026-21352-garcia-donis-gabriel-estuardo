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
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;

import java.util.Random;

public class Lab03BottleneckNetwork {

    public static void main(String[] args) {
        // 1. Configuración de directorio y Múltiples Iteraciones
        Config config = ConfigUtils.createConfig();
        String outputDir = "output/labs/03-bottleneck";
        config.controler().setOutputDirectory(outputDir);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.deleteDirectoryIfExists);
        
        // CORRIDAS MÚLTIPLES: Correrá 10 iteraciones para aprender y cambiar rutas
        config.controler().setFirstIteration(0);
        config.controler().setLastIteration(10);
        config.controler().setWriteEventsInterval(1); // Guardar eventos de todas las corridas

        // 2. Parámetros de Scoring
        ActivityParams homeParams = new ActivityParams("home");
        homeParams.setTypicalDuration(12 * 3600);
        config.planCalcScore().addActivityParams(homeParams);

        ActivityParams workParams = new ActivityParams("work");
        workParams.setTypicalDuration(8 * 3600);
        config.planCalcScore().addActivityParams(workParams);

        // Estrategias de Re-planning para tomar decisiones distintas
        StrategySettings reRoute = new StrategySettings();
        reRoute.setStrategyName("ReRoute");
        reRoute.setWeight(0.3); // 30% de los agentes cambiarán de ruta si encuentran tráfico
        config.strategy().addStrategySettings(reRoute);

        StrategySettings keepPlan = new StrategySettings();
        keepPlan.setStrategyName("ChangeExpBeta");
        keepPlan.setWeight(0.7);
        config.strategy().addStrategySettings(keepPlan);

        Scenario scenario = ScenarioUtils.createScenario(config);
        Network network = scenario.getNetwork();
        NetworkFactory netFactory = network.getFactory();

        // 3. Crear Malla 5x5
        int gridSize = 5;
        double spacing = 400.0;

        for (int x = 0; x < gridSize; x++) {
            for (int y = 0; y < gridSize; y++) {
                String nodeId = x + "_" + y;
                Node node = netFactory.createNode(Id.createNodeId(nodeId), new Coord(x * spacing, y * spacing));
                network.addNode(node);
            }
        }

        createGridWithBottleneck(network, netFactory, gridSize);

        // 4. Crear Población de 50 Agentes
        Population population = scenario.getPopulation();
        PopulationFactory popFactory = population.getFactory();
        Random rand = new Random(42);

        for (int i = 1; i <= 50; i++) {
            boolean isSlow = (i % 2 == 0);
            String agentPrefix = isSlow ? "lento_" : "rapido_";
            Person person = popFactory.createPerson(Id.createPersonId(agentPrefix + i));
            Plan plan = popFactory.createPlan();

            int startX = rand.nextInt(2);
            int startY = rand.nextInt(2);
            String startLink = "link_" + startX + "_" + startY + "_to_" + (startX + 1) + "_" + startY;

            int endX = 3 + rand.nextInt(2);
            int endY = 3 + rand.nextInt(2);
            String endLink = "link_" + (endX - 1) + "_" + endY + "_to_" + endX + "_" + endY;

            Activity actHome = popFactory.createActivityFromLinkId("home", Id.createLinkId(startLink));
            actHome.setEndTime((8 * 3600) + rand.nextInt(300));
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

        System.out.println(">>> Laboratorio 03 (Múltiples Iteraciones y Re-routing) Finalizado.");
    }

    private static void createGridWithBottleneck(Network network, NetworkFactory netFactory, int gridSize) {
        for (int x = 0; x < gridSize; x++) {
            for (int y = 0; y < gridSize; y++) {
                if (x < gridSize - 1) {
                    addConfiguredLink(network, netFactory, x + "_" + y, (x + 1) + "_" + y, x, y);
                }
                if (y < gridSize - 1) {
                    addConfiguredLink(network, netFactory, x + "_" + y, x + "_" + (y + 1), x, y);
                }
            }
        }
    }

    private static void addConfiguredLink(Network network, NetworkFactory netFactory, String fromId, String toId, int x, int y) {
        Node fromNode = network.getNodes().get(Id.createNodeId(fromId));
        Node toNode = network.getNodes().get(Id.createNodeId(toId));

        boolean isCenterZone = (x >= 1 && x <= 3 && y >= 1 && y <= 3);

        double capacity = isCenterZone ? 100.0 : 1800.0;  // Capacidad crítica de 100 veh/h
        double speed = isCenterZone ? 4.1667 : 16.6667;   // Lentos en el centro (~15 km/h)

        Link link1 = netFactory.createLink(Id.createLinkId("link_" + fromId + "_to_" + toId), fromNode, toNode);
        link1.setLength(400.0);
        link1.setFreespeed(speed);
        link1.setCapacity(capacity);
        link1.setNumberOfLanes(1.0);
        network.addLink(link1);

        Link link2 = netFactory.createLink(Id.createLinkId("link_" + toId + "_to_" + fromId), toNode, fromNode);
        link2.setLength(400.0);
        link2.setFreespeed(speed);
        link2.setCapacity(capacity);
        link2.setNumberOfLanes(1.0);
        network.addLink(link2);
    }
}