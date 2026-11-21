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

public class Lab01LineaRecta {

    public static void main(String[] args) {
        // 1. Configuración Base
        Config config = ConfigUtils.createConfig();
        String outputDir = "output/labs/01-linea-recta";
        config.controler().setOutputDirectory(outputDir);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.deleteDirectoryIfExists);
        config.controler().setLastIteration(0);

        // Registro de Actividades
        ActivityParams homeParams = new ActivityParams("home");
        homeParams.setTypicalDuration(12 * 3600);
        config.planCalcScore().addActivityParams(homeParams);

        ActivityParams workParams = new ActivityParams("work");
        workParams.setTypicalDuration(8 * 3600);
        config.planCalcScore().addActivityParams(workParams);

        // 2. Crear Escenario
        Scenario scenario = ScenarioUtils.createScenario(config);

        // 3. Construir Red Vial (3 Nodos, 2 Enlaces)
        Network network = scenario.getNetwork();
        NetworkFactory netFactory = network.getFactory();

        Node node1 = netFactory.createNode(Id.createNodeId("1"), new Coord(0, 0));
        Node node2 = netFactory.createNode(Id.createNodeId("2"), new Coord(1000, 0));
        Node node3 = netFactory.createNode(Id.createNodeId("3"), new Coord(2000, 0));
        
        network.addNode(node1);
        network.addNode(node2);
        network.addNode(node3);

        Link link1 = netFactory.createLink(Id.createLinkId("1-2"), node1, node2);
        link1.setLength(1000.0);
        link1.setFreespeed(13.8889);
        link1.setCapacity(1800.0);
        link1.setNumberOfLanes(1.0);
        
        Link link2 = netFactory.createLink(Id.createLinkId("2-3"), node2, node3);
        link2.setLength(1000.0);
        link2.setFreespeed(13.8889);
        link2.setCapacity(1800.0);
        link2.setNumberOfLanes(1.0);

        network.addLink(link1);
        network.addLink(link2);

        // 4. Población
        Population population = scenario.getPopulation();
        PopulationFactory popFactory = population.getFactory();

        Person person = popFactory.createPerson(Id.createPersonId("agente_1"));
        Plan plan = popFactory.createPlan();

        Activity actHome = popFactory.createActivityFromLinkId("home", Id.createLinkId("1-2"));
        actHome.setEndTime(8 * 3600);
        plan.addActivity(actHome);

        Leg leg = popFactory.createLeg(TransportMode.car);
        plan.addLeg(leg);

        Activity actWork = popFactory.createActivityFromLinkId("work", Id.createLinkId("2-3"));
        plan.addActivity(actWork);

        person.addPlan(plan);
        population.addPerson(person);

        // 5. Ejecutar Simulación
        Controler controler = new Controler(scenario);
        controler.run();

        System.out.println(">>> Laboratorio 01 (Línea Recta) Finalizado con Éxito.");
    }
}