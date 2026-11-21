package gt.edu.uvg.sim.labs;

import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.QSimConfigGroup.SnapshotStyle;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.*;
import java.util.*;

/**
 * Zona 1: avenidas 2..11, calles 2..15, sentidos prescritos por el laboratorio.
 * Coordenadas locales en metros (X este, Y norte), NO un levantamiento GIS.
 * Distancias y quiebres aproximados; incorpora cierres y areas especiales del mapeo verbal.
 * No constituye cartografia verificada. Ver LAB07_MULTILANE.md para alcance y ejecucion.
 */
public class Lab07MultiLaneZona1 {
    /** Shared geometry only; no Lab07 demand is generated. */
    static void buildZona1ScenarioNetwork(Scenario scenario) {
        buildMiniCityNetwork(scenario.getNetwork());
        configureMultiLaneNetwork(scenario.getNetwork());
        configureHotspots(scenario.getNetwork());
        validateNetwork(scenario.getNetwork());
        buildLanesForNetwork(scenario);
    }
    private static final int FIRST_AVENUE = 2, LAST_AVENUE = 11;
    private static final int FIRST_STREET = 2, LAST_STREET = 15;
    private static final int DEFAULT_AGENTS = 72000;
    // Escenario de saturacion: no son participaciones OD medidas por EMETRA.
    private static final double MORNING_GATEWAY_SHARE = .05;
    private static final double EVENING_GATEWAY_SHARE = .08;
    // Pesos estimados, NO aforos medidos. Intervalos contiguos de 24 h.
    private static final double[][] DEFAULT_DEMAND = {
        {0, 4, .04}, {4, 4.5, .4}, {4.5, 5, 1.6}, {5, 5.5, 2.5},
        {5.5, 8.75, 3.2}, {8.75, 9.5, 1.0}, {9.5, 12, .65},
        {12, 14, 1.25}, {14, 15, .65}, {15, 16.5, 1.2},
        {16.5, 20.5, 3.4}, {20.5, 21, .9},
        {21, 22, .4}, {22, 23, .2}, {23, 24, .08}
    };
    // Abscisas acumuladas: 9 intervalos entre avenidas y 13 entre calles.
    private static final double[] AVENUE_EAST = {0, 112, 235, 351, 475, 596, 724, 839, 960, 1084};
    private static final double[] STREET_SOUTH = {0, 119, 246, 365, 497, 625, 749,
            881, 1001, 1128, 1259, 1381, 1508, 1638};
    private static final double[] STREET_SHIFT = {0, 2, 4, 3, 6, 8, 5, 3, 0, -2, 1, 3, 2, 0};
    private static final double[] AVENUE_SHIFT = {0, 2, -2, 1, 4, 2, -1, 3, 1, 0};
    private static final double LOCAL_SPEED = 30.0 / 3.6, LOCAL_CAPACITY = 600;
    private static final double MAIN_SPEED = 45.0 / 3.6, MAIN_CAPACITY = 1200;

    public static void main(String[] args) {
        int iterations = 10, agents = DEFAULT_AGENTS;
        String demandFile = null;
        String outputDir = "output/labs/07-multilane-zona1";
        for (int i = 0; i < args.length; i++) {
            if ("--iter".equals(args[i]) && i + 1 < args.length) iterations = Integer.parseInt(args[++i]);
            else if ("--output".equals(args[i]) && i + 1 < args.length) outputDir = args[++i];
            else if ("--agents".equals(args[i]) && i + 1 < args.length) agents = Integer.parseInt(args[++i]);
            else if ("--demand".equals(args[i]) && i + 1 < args.length) demandFile = args[++i];
            else throw new IllegalArgumentException("Uso: --iter N --output directorio --agents N --demand perfil.csv");
        }
        if (iterations < 1) throw new IllegalArgumentException("--iter debe ser >= 1");
        if (agents < 1) throw new IllegalArgumentException("--agents debe ser positivo");
        double[][] demand = demandFile == null ? DEFAULT_DEMAND : readDemand(demandFile);
        Config config = ConfigUtils.createConfig();
        config.qsim().setUseLanes(true);
        config.qsim().setStartTime(0);
        config.qsim().setEndTime(30 * 3600); // Drenaje de viajes que cruzan medianoche.
        config.qsim().setSnapshotStyle(SnapshotStyle.queue);
        config.controler().setOutputDirectory(outputDir);
        config.controler().setOverwriteFileSetting(OverwriteFileSetting.failIfDirectoryExists);
        config.controler().setFirstIteration(0);
        config.controler().setLastIteration(Math.max(0, iterations - 1));
        config.controler().setWriteEventsInterval(1);
        config.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(12 * 3600));
        config.planCalcScore().addActivityParams(new ActivityParams("parking").setTypicalDuration(3));
        config.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(8 * 3600));
        StrategySettings reRoute = new StrategySettings();
        reRoute.setStrategyName("ReRoute");
        reRoute.setWeight(0.5);
        config.strategy().addStrategySettings(reRoute);
        Scenario scenario = ScenarioUtils.createScenario(config);
        buildMiniCityNetwork(scenario.getNetwork());
        configureMultiLaneNetwork(scenario.getNetwork());
        configureHotspots(scenario.getNetwork());
        validateNetwork(scenario.getNetwork());
        buildLanesForNetwork(scenario);
        scenario.getNetwork().getAttributes().putAttribute("dayDuration", 86400);
        scenario.getNetwork().getAttributes().putAttribute("dailyAgents", agents);
        scenario.getNetwork().getAttributes().putAttribute("demandSource",
                demandFile == null ? "estimated profile; see LAB07_MULTILANE.md" : demandFile);
        scenario.getNetwork().getAttributes().putAttribute("demandProfile", Arrays.deepToString(demand));
        scenario.getNetwork().getAttributes().putAttribute("gatewayShares",
                "estimated: morning=" + MORNING_GATEWAY_SHARE + "; evening=" + EVENING_GATEWAY_SHARE);
        scenario.getNetwork().getAttributes().putAttribute("playbackScale", 120.0);
        buildBoundaryPopulation(scenario, agents, demand);
        System.out.printf("Zona 1 (geometria aproximada): %d nodos, %d enlaces, %d agentes%n",
                scenario.getNetwork().getNodes().size(), scenario.getNetwork().getLinks().size(), agents);
        new Controler(scenario).run();
        writeDemandSummary(scenario, outputDir);
        System.out.println(">>> Laboratorio 07 Zona 1 finalizado: " + outputDir);
    }

    private static boolean isBoundary(int avenue, int street) {
        return avenue == FIRST_AVENUE || avenue == LAST_AVENUE || street == FIRST_STREET || street == LAST_STREET;
    }

    private static String gridId(int avenue, int street) {
        return (isBoundary(avenue, street) ? "B_" : "G_") + "A" + avenue + "_C" + street;
    }

    private static void buildMiniCityNetwork(Network network) {
        network.setCapacityPeriod(3600);
        network.getAttributes().putAttribute("geometrySource", "approximate-local-metric; not surveyed GIS");
        network.getAttributes().putAttribute("trafficAssignment", "laboratory alternating one-way; one to four lanes");
        registerAreas(network);
        for (int avenue = FIRST_AVENUE; avenue <= LAST_AVENUE; avenue++) {
            for (int street = FIRST_STREET; street <= LAST_STREET; street++) {
                if (!hasCrossing(avenue, street)) continue;
                int a = avenue - FIRST_AVENUE, s = street - FIRST_STREET;
                // Desfases interiores que se anulan en los limites del recinto.
                double x = AVENUE_EAST[a] + STREET_SHIFT[s] * Math.sin(Math.PI * a / 9);
                double y = STREET_SOUTH[13] - STREET_SOUTH[s] + AVENUE_SHIFT[a] * Math.sin(Math.PI * s / 13);
                if (avenue == FIRST_AVENUE || avenue == LAST_AVENUE) x = AVENUE_EAST[a];
                if (street == FIRST_STREET || street == LAST_STREET) y = STREET_SOUTH[13] - STREET_SOUTH[s];
                if (avenue >= 6 && avenue <= 8 && street >= 5 && street <= 8) {
                    x = AVENUE_EAST[a];
                    y = STREET_SOUTH[13] - STREET_SOUTH[s];
                }
                Node node = addNode(network, gridId(avenue, street), new Coord(x, y));
                node.getAttributes().putAttribute("avenue", avenue);
                node.getAttributes().putAttribute("street", street);
                node.getAttributes().putAttribute("boundary", isBoundary(avenue, street));
                tagArea(node.getAttributes(), avenue, street);
                if (avenue >= 6 && avenue <= 8 && street >= 6 && street <= 8)
                    node.getAttributes().putAttribute("landmark", "entorno Palacio / Plaza de la Constitucion");
                else if (avenue <= 3 && street >= 9 && street <= 12)
                    node.getAttributes().putAttribute("landmark", "aproximacion occidental Hospital San Juan de Dios");
            }
        }
        for (int avenue = FIRST_AVENUE; avenue <= LAST_AVENUE; avenue++) {
            for (int street = FIRST_STREET; street <= LAST_STREET; street++) {
                if (!hasCrossing(avenue, street)) continue;
                if (street < LAST_STREET && hasCrossing(avenue, street + 1)
                        && !(avenue == 7 && street >= 5 && street < 8)) {
                    boolean southbound = avenue % 2 == 0;
                    addRoad(network, "A" + avenue + "_C" + street,
                            gridId(avenue, southbound ? street : street + 1),
                            gridId(avenue, southbound ? street + 1 : street),
                            avenue + "a Avenida", avenue == 6 || avenue == 7,
                            avenue == 2 && (street == 10 || street == 14) ? 6 : 0);
                }
                if (avenue < LAST_AVENUE && hasCrossing(avenue + 1, street)
                        && !(street == 7 && avenue >= 5 && avenue < 9)
                        && !(street == 13 && avenue == 7)
                        && !(street == 14 && avenue == 8)) {
                    boolean westbound = street % 2 == 0;
                    double bend = (street == 8 && avenue == 7)
                            || (street == 12 && avenue == 2) || (street == 15 && avenue == 3) ? 6 : 0;
                    addRoad(network, "C" + street + "_A" + avenue,
                            gridId(westbound ? avenue + 1 : avenue, street),
                            gridId(westbound ? avenue : avenue + 1, street),
                            street + "a Calle", street == 9 || street == 12, bend);
                }
            }
        }
        addDeadEnd(network, 7, 13, 45);
        addDeadEnd(network, 9, 14, -45);
    }

    private static boolean hasCrossing(int avenue, int street) {
        return !(avenue == 7 && street == 7);
    }

    private static void registerAreas(Network network) {
        // Poligonos locales exportados en network.xml, sin archivos laterales.
        network.getAttributes().putAttribute("visualArea.palacio",
                "institutional|Palacio Nacional|475,1273;724,1273;724,1141;475,1141");
        network.getAttributes().putAttribute("visualArea.plaza",
                "green|Plaza / Catedral|475,1141;724,1141;724,889;475,889");
        // Colon es una referencia externa al este de A11; no extiende la red vial.
        network.getAttributes().putAttribute("visualArea.colon",
                "green|Parque Colon (referencia exterior)|1094,879;1194,879;1194,767;1094,767");
        network.getAttributes().putAttribute("visualPoi.hospital",
                "hospital|Hospital San Juan de Dios (oeste)|0,620");
        network.getAttributes().putAttribute("visualPoi.catedral",
                "institutional|Catedral Metropolitana|724,1015");
        network.getAttributes().putAttribute("mappingSource", "user verbal specification; approximate coordinates");
    }

    private static void tagArea(org.matsim.utils.objectattributes.attributable.Attributes attributes,
                                int avenue, int street) {
        if (avenue >= 6 && avenue <= 8 && street >= 6 && street <= 8)
            attributes.putAttribute("greenArea", "plaza");
        if (avenue >= 6 && avenue <= 8 && street >= 5 && street <= 6)
            attributes.putAttribute("institutionalArea", "palacio");
        if (avenue <= 3 && street >= 9 && street <= 11)
            attributes.putAttribute("hospitalZone", true);
    }

    private static void addDeadEnd(Network network, int avenue, int street, double offset) {
        Node start = network.getNodes().get(Id.createNodeId(gridId(avenue, street)));
        String id = "D_C" + street + "_A" + avenue;
        Node end = addNode(network, id, new Coord(start.getCoord().getX() + offset, start.getCoord().getY()));
        end.getAttributes().putAttribute("deadEnd", true);
        addRoad(network, id, start.getId().toString(), id, street + "a Calle sin salida", false, 0);
        Link terminal = network.getLinks().get(Id.createLinkId(id + "_1"));
        terminal.getAttributes().putAttribute("deadEnd", true);
        terminal.getAttributes().putAttribute("routingEligible", false);
    }

    /** Quiebres sobre la misma via, sin diagonales ficticias que atraviesen manzanas. */
    private static void addRoad(Network network, String roadId, String from, String to,
                                String name, boolean main, double bend) {
        Node start = network.getNodes().get(Id.createNodeId(from));
        Node finish = network.getNodes().get(Id.createNodeId(to));
        List<Node> path = new ArrayList<>();
        path.add(start);
        if (bend != 0) {
            double dx = finish.getCoord().getX() - start.getCoord().getX();
            double dy = finish.getCoord().getY() - start.getCoord().getY();
            double length = Math.hypot(dx, dy);
            for (int i = 1; i <= 2; i++) {
                double t = i / 3.0;
                // En la 2a avenida el quiebre queda al este, dentro del perimetro.
                Node shape = addNode(network, "S_" + roadId + "_" + i,
                        new Coord(start.getCoord().getX() + t * dx - bend * dy / length,
                                start.getCoord().getY() + t * dy + bend * dx / length));
                shape.getAttributes().putAttribute("geometryOnly", true);
                path.add(shape);
            }
        }
        path.add(finish);
        for (int i = 1; i < path.size(); i++) {
            Node n1 = path.get(i - 1), n2 = path.get(i);
            Link link = network.getFactory().createLink(Id.createLinkId(roadId + "_" + i), n1, n2);
            link.setLength(Math.hypot(n2.getCoord().getX() - n1.getCoord().getX(),
                    n2.getCoord().getY() - n1.getCoord().getY()));
            link.setFreespeed(main ? MAIN_SPEED : LOCAL_SPEED);
            link.setCapacity(main ? MAIN_CAPACITY : LOCAL_CAPACITY);
            link.setNumberOfLanes(1);
            link.setAllowedModes(Set.of(TransportMode.car));
            link.getAttributes().putAttribute("roadId", roadId);
            link.getAttributes().putAttribute("roadName", name);
            link.getAttributes().putAttribute("roadClass", main ? "principal" : "local");
            String[] parts = roadId.split("_");
            if (!roadId.startsWith("D_")) {
                int avenue = Integer.parseInt((parts[0].startsWith("A") ? parts[0] : parts[1]).substring(1));
                int street = Integer.parseInt((parts[0].startsWith("C") ? parts[0] : parts[1]).substring(1));
                tagArea(link.getAttributes(), avenue, street);
                if (avenue <= 3 && street >= 9 && street <= 11) {
                    link.setFreespeed(25.0 / 3.6);
                    link.setCapacity(400);
                    link.getAttributes().putAttribute("roadClass", "hospital");
                }
            }
            if ("principal".equals(link.getAttributes().getAttribute("roadClass")))
                link.getAttributes().putAttribute("nightFreeSpeed", 75.0 / 3.6);
            network.addLink(link);
        }
    }

    /** Secciones de escenario prescritas; no son aforos ni anchos GIS medidos. */
    private static void configureMultiLaneNetwork(Network network) {
        network.getAttributes().putAttribute("laneModel", "Lab07: scenario sections, shared turn lanes");
        network.getAttributes().putAttribute("maxActiveVehicles", 1500);
        network.getAttributes().putAttribute("targetActiveVehicles", "1000-1500 at peak; measured in Python");
        for (Link link : network.getLinks().values()) {
            String road = (String) link.getAttributes().getAttribute("roadId");
            String axis = road.split("_")[0];
            int lanes;
            if (axis.equals("A6")) lanes = 4;
            else if (Set.of("A7", "A9", "C12").contains(axis)) lanes = 3;
            else if (axis.startsWith("A")) lanes = 2;
            else if (axis.equals("D")) lanes = 1;
            else lanes = Integer.parseInt(axis.substring(1)) % 2 == 0 ? 2 : 1;
            boolean trunk = Set.of("A6", "A7", "A9", "C12").contains(axis);
            boolean hospital = Boolean.TRUE.equals(link.getAttributes().getAttribute("hospitalZone"));
            link.setNumberOfLanes(lanes);
            link.setCapacity(lanes * (trunk ? 800 : hospital ? 400 : 600));
            link.setFreespeed((hospital ? 25 : trunk ? 45 : 30) / 3.6);
            link.getAttributes().putAttribute("roadClass", hospital ? "hospital" : trunk ? "principal" : "local");
            link.getAttributes().removeAttribute("nightFreeSpeed");
            link.getAttributes().putAttribute("laneWidth", 3.2);
            link.getAttributes().putAttribute("roadWidth", lanes * 3.2);
            link.getAttributes().putAttribute("laneChanging", lanes > 1);
            link.getAttributes().putAttribute("extremeNight", !axis.equals("D"));
            link.getAttributes().putAttribute("maxActiveVehicles", 1500);
        }
    }

    /** Effective friction, not a measured traffic-light programme. Apply once
     * to whole physical roads, including geometry subdivisions. Both routers
     * see the same reduced free speed and capacity through network XML. */
    private static void configureHotspots(Network network) {
        network.getAttributes().putAttribute("hotspotSource", "user scenario; uncalibrated effective friction");
        network.getAttributes().putAttribute("externalConnections", "boundary proxies only; Periferico outside extent");
        for (Link link : network.getLinks().values()) {
            String road = (String) link.getAttributes().getAttribute("roadId");
            if (road.startsWith("D_")) continue;
            String[] parts = road.split("_");
            boolean avenueAxis = parts[0].startsWith("A");
            int avenue = Integer.parseInt(parts[avenueAxis ? 0 : 1].substring(1));
            int street = Integer.parseInt(parts[avenueAxis ? 1 : 0].substring(1));
            String hotspot = "";
            double factor = 1, capacityFactor = 1;
            if (avenue >= 8 && avenue <= 9 && street >= 9 && street <= 10) {
                hotspot = "Congreso"; factor = .70; capacityFactor = .90;
            } else if (avenue >= 6 && avenue <= 8 && street >= 5 && street <= 8) {
                hotspot = "Plaza-Catedral"; factor = .75; capacityFactor = .90;
            } else if (avenueAxis && (avenue == 4 || avenue == 7)) {
                hotspot = "Eje-A" + avenue; factor = .90; capacityFactor = .95;
            } else if ((avenue == 2 || street == 15)
                    && link.getToNode().getId().toString().startsWith("B_")) {
                hotspot = "Salida-perimetral-proxy"; factor = .90; capacityFactor = .95;
            }
            if (hotspot.isEmpty()) continue;
            double nominalSpeed = link.getFreespeed();
            link.getAttributes().putAttribute("hotspot", hotspot);
            link.getAttributes().putAttribute("nominalFreeSpeed", nominalSpeed);
            link.getAttributes().putAttribute("nominalCapacity", link.getCapacity());
            link.getAttributes().putAttribute("frictionSpeedFactor", factor);
            link.getAttributes().putAttribute("frictionCapacityFactor", capacityFactor);
            link.setFreespeed(nominalSpeed * factor);
            link.setCapacity(link.getCapacity() * capacityFactor);
            link.getAttributes().putAttribute("effectiveDelaySeconds",
                    link.getLength() / link.getFreespeed() - link.getLength() / nominalSpeed);
        }
    }

    private static Node addNode(Network network, String name, Coord coord) {
        Node node = network.getFactory().createNode(Id.createNodeId(name), coord);
        network.addNode(node);
        return node;
    }

    private static Set<Id<Node>> reachable(Node root) {
        Set<Id<Node>> visited = new HashSet<>();
        Deque<Node> pending = new ArrayDeque<>();
        pending.add(root);
        while (!pending.isEmpty()) {
            Node node = pending.removeFirst();
            if (!visited.add(node.getId())) continue;
            for (Link link : node.getOutLinks().values()) pending.addLast(link.getToNode());
        }
        return visited;
    }

    private static void validateNetwork(Network network) {
        for (Node node : network.getNodes().values()) {
            if (node.getInLinks().isEmpty() && node.getOutLinks().isEmpty())
                throw new IllegalStateException("Nodo huerfano: " + node.getId());
        }
        for (Link link : network.getLinks().values()) {
            if (!Double.isFinite(link.getLength()) || link.getLength() <= 0 || (link.getNumberOfLanes() < 1 || link.getNumberOfLanes() > 4))
                throw new IllegalStateException("Enlace invalido: " + link.getId());
            for (Link reverse : link.getToNode().getOutLinks().values())
                if (reverse.getToNode().equals(link.getFromNode()))
                    throw new IllegalStateException("Contravia: " + link.getId());
        }
    }

    private static double[][] readDemand(String filename) {
        List<double[]> bins = new ArrayList<>();
        try {
            for (String line : java.nio.file.Files.readAllLines(java.nio.file.Path.of(filename))) {
                if (line.isBlank() || line.startsWith("#") || line.startsWith("start_hour")) continue;
                String[] fields = line.split(",");
                if (fields.length != 3) throw new IllegalArgumentException("CSV: start_hour,end_hour,weight");
                double[] bin = Arrays.stream(fields).mapToDouble(Double::parseDouble).toArray();
                double expected = bins.isEmpty() ? 0 : bins.get(bins.size() - 1)[1];
                if (Arrays.stream(bin).anyMatch(v -> !Double.isFinite(v)) || bin[0] != expected
                        || bin[1] <= bin[0] || bin[1] > 24 || bin[2] < 0)
                    throw new IllegalArgumentException("Intervalos invalidos o no contiguos en " + filename);
                bins.add(bin);
            }
        } catch (java.io.IOException ex) { throw new IllegalArgumentException("No se pudo leer " + filename, ex); }
        if (bins.isEmpty() || bins.get(bins.size() - 1)[1] != 24
                || bins.stream().noneMatch(b -> b[2] > 0))
            throw new IllegalArgumentException("La demanda debe cubrir [0,24] y tener peso positivo");
        return bins.toArray(double[][]::new);
    }

    private static void buildBoundaryPopulation(Scenario scenario, int agents, double[][] demand) {
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        Random random = new Random(42);
        List<Node> boundary = new ArrayList<>(scenario.getNetwork().getNodes().values().stream()
                .filter(n -> n.getId().toString().startsWith("B_"))
                .sorted(Comparator.comparing(n -> n.getId().toString())).toList());
        Collections.shuffle(boundary, random);
        List<Node> origins = boundary.stream().filter(n -> !n.getOutLinks().isEmpty()).toList();
        List<Node> destinations = boundary.stream().filter(n -> !n.getInLinks().isEmpty()).toList();
        Random demandRandom = new Random(20260922);
        double[] departures24h = new double[agents];
        double weight = Arrays.stream(demand).mapToDouble(b -> (b[1] - b[0]) * b[2]).sum();
        for (int i = 0; i < agents; i++) {
            double draw = demandRandom.nextDouble() * weight;
            for (double[] bin : demand) {
                double mass = (bin[1] - bin[0]) * bin[2];
                if (draw < mass) { departures24h[i] = 3600 * (bin[0] + draw / bin[2]); break; }
                draw -= mass;
            }
        }
        Arrays.sort(departures24h);
        List<Node> gateways = origins.stream().filter(n -> Set.of(
                gridId(6, 2), gridId(2, 9), gridId(11, 12), gridId(7, 15))
                .contains(n.getId().toString())).toList();
        // Reparto reproducible entre accesos viables; se verifica cada OD antes de enrutar.
        for (int i = 0; i < agents; i++) {
            double hour = departures24h[i] / 3600;
            boolean peak = (hour >= 4.5 && hour < 8.75) || (hour >= 16.5 && hour < 20.5);
            boolean concentrated = peak && random.nextDouble()
                    < (hour < 12 ? MORNING_GATEWAY_SHARE : EVENING_GATEWAY_SHARE);
            List<Node> sourcePool = concentrated ? gateways.stream().filter(n -> n.getId().toString().equals(
                    hour < 12 ? gridId(2, 9) : gridId(11, 12))).toList() : origins;
            Node origin = sourcePool.get(random.nextInt(sourcePool.size()));
            List<? extends Link> departures = origin.getOutLinks().values().stream()
                    .filter(l -> !l.getToNode().getOutLinks().isEmpty())
                    .filter(l -> !concentrated || l.getId().toString().startsWith(
                            hour < 12 ? "C9_A2_" : "A11_C11_")).toList();
            Link start = departures.get(random.nextInt(departures.size()));
            Set<Id<Node>> reachable = reachable(start.getToNode());
            List<Link> arrivals = new ArrayList<>();
            for (int j = 0; j < destinations.size(); j++) {
                Node destination = destinations.get((i + j + destinations.size() / 2) % destinations.size());
                if (destination.equals(origin)) continue;
                for (Link link : destination.getInLinks().values())
                    if (!link.equals(start) && reachable.contains(link.getFromNode().getId())) arrivals.add(link);
                if (!arrivals.isEmpty()) break;
            }
            if (arrivals.isEmpty()) throw new IllegalStateException("Origen sin destino alcanzable: " + origin.getId());
            Link end = arrivals.get(random.nextInt(arrivals.size()));
            Person person = factory.createPerson(Id.createPersonId("agente_" + (i + 1)));
            Plan plan = factory.createPlan();
            Activity home = factory.createActivityFromLinkId("home", start.getId());
            home.setEndTime(departures24h[i]);
            plan.addActivity(home);
            plan.addLeg(factory.createLeg(TransportMode.car));
            Activity parking = factory.createActivityFromLinkId("parking", end.getId());
            parking.setMaximumDuration(3);
            plan.addActivity(parking);
            plan.addLeg(factory.createLeg(TransportMode.car));
            plan.addActivity(factory.createActivityFromLinkId("work", end.getId()));
            person.addPlan(plan);
            population.addPerson(person);
        }
    }

    private static void writeDemandSummary(Scenario scenario, String outputDir) {
        int[] counts = new int[48];
        for (Person person : scenario.getPopulation().getPersons().values()) {
            Activity home = (Activity) person.getSelectedPlan().getPlanElements().get(0);
            counts[Math.min(47, (int) (home.getEndTime().seconds() / 1800))]++;
        }
        List<String> lines = new ArrayList<>();
        lines.add("start_hour,end_hour,generated_trips");
        for (int i = 0; i < counts.length; i++) lines.add((i / 2.0) + "," + ((i + 1) / 2.0) + "," + counts[i]);
        try { java.nio.file.Files.write(java.nio.file.Path.of(outputDir, "output_demand.csv"), lines); }
        catch (java.io.IOException ex) { throw new IllegalStateException("No se pudo exportar demanda", ex); }
    }

    private static void buildLanesForNetwork(Scenario scenario) {
        Lanes lanes = scenario.getLanes();
        for (Link link : scenario.getNetwork().getLinks().values()) {
            LanesToLinkAssignment assignment = lanes.getFactory().createLanesToLinkAssignment(link.getId());
            List<Id<Link>> next = new ArrayList<>(link.getToNode().getOutLinks().keySet());
            if (next.isEmpty()) continue; // Nodo ciego o salida del recinto.
            // Un carril compartido por todos los giros legales segun los sentidos de la malla.
            LanesUtils.createAndAddLane(assignment, lanes.getFactory(),
                    Id.create(link.getId() + ".ol", Lane.class), link.getCapacity(),
                    link.getLength(), 0, (int) link.getNumberOfLanes(), next, null);
            lanes.addLanesToLinkAssignment(assignment);
        }
    }
}
