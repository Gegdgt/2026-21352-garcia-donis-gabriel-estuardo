package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1PriorityReceiverCheck.*;

/** A fairness reservation must have the same meaning for a short-body passage
 * as for an ordinary turn. Both opposing receivers are free in this fixture. */
public final class SimZ1PassageFairnessCheck {
    public static void main(String[] args) {
        try {
            var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
            var n=s.getNetwork();var f=n.getFactory();
            double[][] xy={{0,-40},{0,0},{0,1},{-40,0},{0,40},{40,1}};
            for(int i=0;i<xy.length;i++)n.addNode(f.createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
            String[] ids={"avenue","street","connector","receipt","branch"};
            int[][] edges={{0,1},{3,1},{1,2},{2,4},{2,5}};
            for(int i=0;i<ids.length;i++) {
                var link=f.createLink(id(ids[i]),n.getNodes().get(Id.createNodeId(edges[i][0])),n.getNodes().get(Id.createNodeId(edges[i][1])));
                link.setLength(Math.hypot(link.getToNode().getCoord().getX()-link.getFromNode().getCoord().getX(),link.getToNode().getCoord().getY()-link.getFromNode().getCoord().getY()));
                link.setNumberOfLanes(1);link.setCapacity(2000);link.setFreespeed(10);link.setAllowedModes(Set.of("car"));
                link.getAttributes().putAttribute("simz1:priorityRole",i==1?"street":"avenue");n.addLink(link);
            }
            var major=vehicle("major",4.5,"connector");var minor=vehicle("minor",4.5,"connector");
            var minorOffered=new AtomicBoolean(true);var space=new AtomicBoolean(true);
            var majorLane=proxy(QLaneI.class,(p,m,a)->switch(m.getName()) {
                case "getId"->Id.create("major-lane",Lane.class);case "isNotOfferingVehicle"->false;case "getFirstVehicle"->major;
                default->throw new AssertionError(m);
            });
            var minorLane=proxy(QLaneI.class,(p,m,a)->switch(m.getName()) {
                case "getId"->Id.create("minor-lane",Lane.class);case "isNotOfferingVehicle"->!minorOffered.get();case "getFirstVehicle"->minor;
                default->throw new AssertionError(m);
            });
            var receiver=proxy(QLaneI.class,(p,m,a)->switch(m.getName()) {
                case "getId"->Id.create("original",Lane.class);case "isAcceptingFromUpstream"->space.get();
                default->throw new AssertionError(m);
            });
            var qlinks=new HashMap<Id<Link>,QLinkI>();
            for(var link:n.getLinks().values())qlinks.put(link.getId(),proxy(QLinkI.class,(p,m,a)->switch(m.getName()) {
                case "getLink"->link;
                case "getOfferingQLanes"->link.getId().equals(id("avenue"))?List.of(majorLane):link.getId().equals(id("street"))?List.of(minorLane):List.of();
                case "getAcceptingQLane"->receiver;default->throw new AssertionError(m);
            }));
            var qnet=new QNetwork(n,null){@Override public Map<Id<Link>,QLinkI> getNetsimLinks(){return qlinks;}};
            var settings=new Zona1PriorityConfigGroup();settings.setClassification("explicit");
            var node=n.getNodes().get(Id.createNodeId(1));
            var priority=new UnsignalizedPriority.StopAndYield(node,settings,null);
            var street=n.getLinks().get(id("street"));var avenue=n.getLinks().get(id("avenue"));
            require(!priority.passageMayProceed(street,id("connector"),minor,qnet,0),"Street must initially respect the avenue");
            require(!priority.passageMayProceed(avenue,id("connector"),major,qnet,36),"Avenue must respect the awarded fairness reservation");
            require(priority.passageMayProceed(street,id("connector"),minor,qnet,36),
                    "Artificial priority deadlock: fairness holder still yields to the avenue it has stopped");
            minorOffered.set(false);
            priority.crossedPassage(street,minorLane,id("connector"),minor,qnet,36,Map.of());
            require(!priority.passageMayProceed(avenue,id("connector"),major,qnet,36),"Conflicting crossings in the same step");
            require(priority.passageMayProceed(avenue,id("connector"),major,qnet,37),"Avenue must recover after the minor clears priority");
            System.out.println("PASS fairness passage: no circular yield; normal avenue priority and same-step conflict exclusion retained");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
