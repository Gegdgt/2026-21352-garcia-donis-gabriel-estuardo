package gt.edu.uvg.sim.labs;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
/** Shared prescribed historical map for Lab08 and subsequent laboratories. */
public final class Zona1BaseNetwork {
 private Zona1BaseNetwork() {}
    private static final double PIVOT_LON = -90.5180;
    private static final double PIVOT_LAT = 14.6460;
    private static final double ANGLE = Math.toRadians(-9.0);
    private static final double COS = Math.cos(ANGLE), SIN = Math.sin(ANGLE);
    private static final double METRES_PER_DEGREE = Math.PI * 6378137.0 / 180.0;
    private static final double LONGITUDE_METRES = METRES_PER_DEGREE * Math.cos(Math.toRadians(PIVOT_LAT));

    /** Parametric approximation, not surveyed GIS; all output coordinates are UTM metres. */
    public static void build(org.matsim.api.core.v01.network.Network net) {
        CoordinateTransformation projection = TransformationFactory.getCoordinateTransformation("EPSG:4326", "EPSG:32615");
        Objects.requireNonNull(net, "network");
        if (!net.getNodes().isEmpty() || !net.getLinks().isEmpty())
            throw new IllegalArgumentException("Zona1BaseNetwork requires an empty network");
        net.setCapacityPeriod(3600);
        net.getAttributes().putAttribute("visualProjection", "EPSG:32615");
        net.getAttributes().putAttribute("coordinateReferenceSystem", "EPSG:32615");
        net.getAttributes().putAttribute("geometrySource", "Parametric warp v1: rotation -9deg, quadratic avenue spacing, Gaussian central shear; not surveyed GIS");
        for (int a=2; a<=12; a++) for (int c=4; c<=18; c++) {
            if (a==7 && c==7) continue;
            var n = net.getFactory().createNode(Id.createNodeId("A"+a+"_C"+c), projection.transform(coordinate(a,c)));
            n.getAttributes().putAttribute("avenue", a);
            n.getAttributes().putAttribute("street", c);
            net.addNode(n);
        }
        for (int a=2; a<=12; a++) for (int c=4; c<=18; c++) {
            if (c<18 && !(a==7 && c>=5 && c<8)) addRoad(net, a,c,a,c+1,a%2==0,a>=6 && a<=9 ? 4:2,"avenue");
            if (a<12 && !(c==7 && a>=5 && a<9) && !(c==13 && a==7) && !(c==14 && a==8)) addRoad(net, a,c,a+1,c,c%2!=0,c==9 || c==12 ? 3:2,"street");
        }
        // Boundary return directions close all corner source/sink nodes. Shared
        // endpoints are genuine junctions, not invisible disconnected ramps.
        for (int a=2; a<12; a++) {
            addRoad(net,a,4,a+1,4,true,2,"return");
            addRoad(net,a,18,a+1,18,true,2,"return");
        }
        for (int c=4; c<18; c++) {
            addRoad(net,2,c,2,c+1,false,2,"return");
            addRoad(net,12,c,12,c+1,false,2,"return");
        }
        Lab05MiniCityNetwork.validateNetwork(net);
        for (Link link : net.getLinks().values()) {
            if (!Boolean.TRUE.equals(link.getAttributes().getAttribute("stopBeforeAvenue"))) continue;
            var junction = link.getToNode();
            boolean avenueCrossing = java.util.stream.Stream.concat(
                    junction.getInLinks().values().stream(), junction.getOutLinks().values().stream())
                    .anyMatch(l -> "avenue".equals(l.getAttributes().getAttribute("roadClass")));
            link.getAttributes().putAttribute("stopBeforeAvenue", avenueCrossing);
            double halfWidth = java.util.stream.Stream.concat(
                    junction.getInLinks().values().stream(), junction.getOutLinks().values().stream())
                    .filter(l -> "avenue".equals(l.getAttributes().getAttribute("roadClass")))
                    .mapToDouble(l -> l.getNumberOfLanes()*3.8/2
                            + ((Number) l.getAttributes().getAttribute("lateralOffset")).doubleValue())
                    .max().orElse(0);
            link.getAttributes().putAttribute("stopLineSetback", halfWidth + 3.25);
        }
        configureSignals(net);
        passage(net,7,13,35);
        passage(net,9,14,-35);
    }

    private static void addRoad(org.matsim.api.core.v01.network.Network net, int a,int c,int b,int d,
                                boolean forward,int lanes,String kind) {
        var from = net.getNodes().get(Id.createNodeId("A"+(forward?a:b)+"_C"+(forward?c:d)));
        var to = net.getNodes().get(Id.createNodeId("A"+(forward?b:a)+"_C"+(forward?d:c)));
        if (from == null || to == null)
            throw new IllegalStateException("Missing road endpoint: " + a + "," + c + " -> " + b + "," + d);
        var l = net.getFactory().createLink(Id.createLinkId(from.getId()+"__"+to.getId()),from,to);
        if (net.getLinks().containsKey(l.getId())) return;
        l.setLength(Math.hypot(to.getCoord().getX()-from.getCoord().getX(), to.getCoord().getY()-from.getCoord().getY()));
        l.setNumberOfLanes(lanes);
        l.setFreespeed(lanes>=3 ? 12.5 : 8.33);
        l.setCapacity(lanes*800);
        l.setAllowedModes(Set.of(TransportMode.car));
        l.getAttributes().putAttribute("laneWidth", 3.8);
        l.getAttributes().putAttribute("laneChanging", true);
        l.getAttributes().putAttribute("roadClass", kind);
        l.getAttributes().putAttribute("signalGroup", a==b ? "avenue" : "street");
        l.getAttributes().putAttribute("rightOfWay", a==b && a>=6 && a<=9);
        l.getAttributes().putAttribute("stopBeforeAvenue", c==d);
        l.getAttributes().putAttribute("mandatoryStopSeconds", 1.0);
        l.getAttributes().putAttribute("stopLineSetback", 3.25);
        l.getAttributes().putAttribute("roadWidth", lanes*3.8);
        l.getAttributes().putAttribute("lateralOffset", (a==b && (a==2 || a==12)) || (c==d && (c==4 || c==18)) ? lanes*3.8/2 : 0.0);
        net.addLink(l);
    }


    private static void configureSignals(org.matsim.api.core.v01.network.Network net) {
        for (var junction : net.getNodes().values()) {
            Set<Object> groups = new HashSet<>();
            junction.getInLinks().values().forEach(l -> groups.add(l.getAttributes().getAttribute("signalGroup")));
            if (!groups.contains("avenue") || !groups.contains("street")) continue;
            junction.getAttributes().putAttribute("signalized", true);
            for (Link link : junction.getInLinks().values()) {
                var attrs = link.getAttributes();
                attrs.putAttribute("signalized", true);
                attrs.putAttribute("signalCycle", 80.0);
                attrs.putAttribute("avenueGreen", 43.0);
                attrs.putAttribute("streetGreen", 25.0);
                attrs.putAttribute("signalYellow", 4.0);
                attrs.putAttribute("signalAllRed", 2.0);
                attrs.putAttribute("signalOffset", 0.0);
                double width = java.util.stream.Stream.concat(junction.getInLinks().values().stream(), junction.getOutLinks().values().stream())
                    .filter(l -> !Objects.equals(attrs.getAttribute("signalGroup"),l.getAttributes().getAttribute("signalGroup")))
                    .mapToDouble(l -> l.getNumberOfLanes()*3.8/2 + ((Number)l.getAttributes().getAttribute("lateralOffset")).doubleValue())
                    .max().orElse(0);
                attrs.putAttribute("stopLineSetback", width+3.25);
            }
        }
    }

    /** WGS84 lon/lat. Smooth metre-space deformation before rotation and projection. */
    static Coord coordinate(int avenue, int street) {
        if (avenue < 2 || avenue > 12 || street < 4 || street > 18)
            throw new IllegalArgumentException("Expected avenues 2..12 and streets 4..18");
        double u = avenue - 2.0, v = street - 4.0;
        // Avenue intervals grow eastward, with another 2.5% widening to the south.
        double east = (112.0*u + 1.2*u*u) * (1.0 + .025*v/14.0);
        // Maximum 22 m bow at the central avenues and streets 8/9; no sharp joins.
        double band = (v - 4.5) / 2.0;
        double north = -120.0*v + 22.0*Math.sin(Math.PI*u/10.0)*Math.exp(-band*band);
        double rotatedEast = COS*east - SIN*north;
        double rotatedNorth = SIN*east + COS*north;
        return new Coord(PIVOT_LON + rotatedEast/LONGITUDE_METRES,
                         PIVOT_LAT + rotatedNorth/METRES_PER_DEGREE);
    }
    private static void passage(org.matsim.api.core.v01.network.Network net,int a,int c,double offset) {
        var from=net.getNodes().get(Id.createNodeId("A"+a+"_C"+c));
        if (from == null) throw new IllegalStateException("Missing passage origin");
        Coord delta = new Coord(offset,12);
        var end=net.getFactory().createNode(Id.createNodeId("D_"+a+"_"+c),new Coord(from.getCoord().getX()+delta.getX(),from.getCoord().getY()+delta.getY()));
        end.getAttributes().putAttribute("deadEnd",true); net.addNode(end);
        var l=net.getFactory().createLink(Id.createLinkId("PASSAGE_"+a+"_"+c),from,end);
        l.setLength(Math.hypot(offset,12)); l.setFreespeed(1.4); l.setCapacity(100); l.setNumberOfLanes(1);
        l.setAllowedModes(Set.of(TransportMode.walk));
        l.getAttributes().putAttribute("routingEligible",false);
        l.getAttributes().putAttribute("roadClass","pedestrian");
        l.getAttributes().putAttribute("laneWidth",2.0); net.addLink(l);
    }
}
