package gt.edu.uvg.sim.zona1;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
public final class PriorityContractCheck {
    static void require(boolean value){if(!value)throw new AssertionError();}
    static void rejects(Runnable value){try{value.run();}catch(IllegalArgumentException expected){return;}throw new AssertionError("invalid table accepted");}
    static PriorityMovements.Movement move(String a,String b){return new PriorityMovements.Movement(Id.createLinkId(a),Id.createLinkId(b));}
    public static void main(String[] args) {
        try {
            var net=ScenarioUtils.createScenario(ConfigUtils.createConfig()).getNetwork();
            double[][] xy={{0,0},{-10,0},{0,-10},{10,0},{0,10}};
            for(int i=0;i<5;i++) net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
            String[] names={"w","s","e","n"};int[][] edges={{1,0},{2,0},{0,3},{0,4}};
            for(int i=0;i<4;i++){var link=net.getFactory().createLink(Id.createLinkId(names[i]),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));link.setAllowedModes(Set.of("car"));net.addLink(link);}
            var roadProbe=net.getLinks().get(Id.createLinkId("w"));
            for(var modes:List.of(Set.of("car"),Set.of("bus"),Set.of("car","bus"))) {
                roadProbe.setAllowedModes(modes);
                require(UnsignalizedPriority.roadLink(roadProbe));
            }
            roadProbe.setAllowedModes(Set.of("walk","bike"));
            require(!UnsignalizedPriority.roadLink(roadProbe));
            roadProbe.setAllowedModes(Set.of("car"));
            var node=net.getNodes().get(Id.createNodeId(0));var settings=new Zona1PriorityConfigGroup();
            require(!new PriorityMovements(node,settings).conflicts(move("w","n"),move("s","e")));
            require(new PriorityMovements(node,settings).conflicts(move("w","e"),move("s","n")));
            require(new PriorityMovements(node,settings).conflicts(move("w","e"),move("s","e")));
            for(var edge:List.of(new String[]{"nIn","4","0"},new String[]{"sOut","0","2"})) {
                var link=net.getFactory().createLink(Id.createLinkId(edge[0]),net.getNodes().get(Id.createNodeId(edge[1])),net.getNodes().get(Id.createNodeId(edge[2])));
                link.setAllowedModes(Set.of("car"));net.addLink(link);
            }
            require(!new PriorityMovements(node,settings).conflicts(move("s","n"),move("nIn","sOut")));
            require(new PriorityMovements(node,settings).evidence(move("s","n"),move("nIn","sOut")).equals("reciprocal_opposite_through"));
            settings.setConflicts("conservative");
            require(new PriorityMovements(node,settings).conflicts(move("w","n"),move("s","e")));
            node.getAttributes().putAttribute("simz1:nonConflictingMovements","w>n|s>e");
            rejects(()->new PriorityMovements(node,settings)); settings.setConflicts("verified-node-table");
            var policy=new PriorityMovements(node,settings);
            require(!policy.conflicts(move("w","n"),move("s","e")));
            require(!policy.conflicts(move("s","e"),move("w","n")));
            require(policy.conflicts(move("w","e"),move("s","n")));
            for(String invalid:List.of("w>e|s>n","w>e|s>e","w>n|missing>e","w>n|e>s","w>n|s>e;w>n|s>e","")) {
                node.getAttributes().putAttribute("simz1:nonConflictingMovements",invalid);rejects(()->new PriorityMovements(node,settings));
            }
            var w=net.getLinks().get(Id.createLinkId("w"));
            require(UnsignalizedPriority.classify(w,settings).source().equals("orientation_approximation"));
            w.getAttributes().putAttribute("osm:name","Avenida Elena");
            require(UnsignalizedPriority.classify(w,settings).role().equals("avenue"));
            w.getAttributes().putAttribute("osm:name","Calle 3");
            require(UnsignalizedPriority.classify(w,settings).role().equals("street"));
            w.getAttributes().putAttribute("osm:name","Calle Avenida ambigua");
            require(UnsignalizedPriority.classify(w,settings).source().equals("orientation_approximation"));
            w.getAttributes().putAttribute("osm:highway","primary");
            w.getAttributes().putAttribute("osm:name","Calle 3");
            require(UnsignalizedPriority.classify(w,settings).role().equals("avenue"));
            require(UnsignalizedPriority.classify(w,settings).source().equals("osm_highway_major_assumption"));
            var vertical=net.getLinks().get(Id.createLinkId("s"));
            vertical.getAttributes().putAttribute("osm:highway","service");
            vertical.getAttributes().putAttribute("osm:name","Avenida de servicio");
            require(UnsignalizedPriority.classify(vertical,settings).role().equals("street"));
            require(UnsignalizedPriority.classify(vertical,settings).source().equals("osm_highway_service_assumption"));
            vertical.getAttributes().putAttribute("osm:highway","residential");
            vertical.getAttributes().removeAttribute("osm:name");
            require(UnsignalizedPriority.classify(vertical,settings).role().equals("street"));
            require(UnsignalizedPriority.classify(vertical,settings).source().equals("osm_highway_minor_assumption"));
            vertical.getAttributes().putAttribute("osm:highway","unknown_type");
            require(UnsignalizedPriority.classify(vertical,settings).source().equals("orientation_approximation"));
            settings.setClassification("osm-name-orientation");
            require(UnsignalizedPriority.classify(w,settings).role().equals("street"));
            settings.setClassification("explicit");rejects(()->UnsignalizedPriority.classify(w,settings));
            w.getAttributes().putAttribute("simz1:priorityRole","avenue");require(UnsignalizedPriority.classify(w,settings).source().equals("network_attribute"));
            w.getAttributes().putAttribute("simz1:priorityRole","guess");rejects(()->UnsignalizedPriority.classify(w,settings));
            rejects(()->settings.setStopSeconds(Double.NaN));rejects(()->settings.setStopSeconds(-1));
            rejects(()->settings.setMaxYieldSeconds(Double.NaN));rejects(()->settings.setMaxYieldSeconds(-1));
            System.out.println("PASS geometric disjoint/crossing/merge, conservative control, symmetric verified table, malformed rejection, OSM hierarchy/legacy/explicit/fallback classification");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
