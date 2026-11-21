package org.matsim.core.mobsim.qsim.qnetsimengine;
import java.lang.reflect.Proxy;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.lanes.Lane;
import gt.edu.uvg.sim.zona1.UnsignalizedPriority;

/** Reproduces the old blanket yield with a physically blocked priority exit. */
public final class PriorityBlockedRegression {
    @SuppressWarnings("unchecked") static <T> T proxy(Class<T> type, Map<String,Object> values) {
        return (T)Proxy.newProxyInstance(type.getClassLoader(),new Class[]{type},(p,m,a)->{
            if (values.containsKey(m.getName())) return values.get(m.getName());
            throw new AssertionError("Unexpected method: "+m);
        });
    }
    public static void main(String[] args) {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig()); var net=scenario.getNetwork();
        double[][] xy={{0,0},{-10,0},{0,-10},{10,0},{0,10}};
        for(int i=0;i<xy.length;i++) net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        String[] ids={"street","avenue","streetOut","avenueOut"}; int[][] edges={{1,0},{2,0},{0,3},{0,4}};
        var qlinks=new HashMap<Id<Link>,QLinkI>(); var lanes=new HashMap<String,QLaneI>(); var vehicles=new HashMap<String,QVehicle>();
        for(int i=0;i<ids.length;i++) {
            var link=net.getFactory().createLink(Id.createLinkId(ids[i]),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
            link.setAllowedModes(Set.of("car")); net.addLink(link);
            var driver=proxy(MobsimDriverAgent.class,Map.of("getId",Id.createPersonId(ids[i]),"chooseNextLinkId",Id.createLinkId(i==0?"streetOut":"avenueOut")));
            var vehicle=proxy(QVehicle.class,Map.of("getDriver",driver,"getEarliestLinkExitTime",1.0,"getId",Id.createVehicleId(ids[i])));
            var lane=proxy(QLaneI.class,Map.of("getId",Id.create(ids[i],Lane.class),"isNotOfferingVehicle",i>=2,
                "getFirstVehicle",vehicle,"isAcceptingFromUpstream",i!=3));
            lanes.put(ids[i],lane); vehicles.put(ids[i],vehicle);
            qlinks.put(link.getId(),proxy(QLinkI.class,Map.of("getLink",link,"isNotOfferingVehicle",i>=2,"getOfferingQLanes",List.of(lane),"getAcceptingQLane",lane)));
        }
        var qnet=new QNetwork(net,null) { @Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return qlinks;} };
        var logic=new UnsignalizedPriority.StopAndYield(net.getNodes().get(Id.createNodeId(0)));
        var street=net.getLinks().get(Id.createLinkId("street"));
        logic.isAcceptingTurn(street,lanes.get("street"),Id.createLinkId("streetOut"),vehicles.get("street"),qnet,0);
        // A turn permission is not an executed exit. Full downstream storage
        // prevents QNode from moving this avenue even though turn logic says GO.
        logic.isAcceptingTurn(net.getLinks().get(Id.createLinkId("avenue")),lanes.get("avenue"),Id.createLinkId("avenueOut"),vehicles.get("avenue"),qnet,5);
        var result=logic.isAcceptingTurn(street,lanes.get("street"),Id.createLinkId("streetOut"),vehicles.get("street"),qnet,5);
        if(result!=TurnAcceptanceLogic.AcceptTurn.GO) throw new AssertionError("Blocked avenue incorrectly prevents ready street: "+result);
        System.out.println("PASS blocked avenue: ready street GO while avenue output rejects upstream storage");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
