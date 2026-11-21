package gt.edu.uvg.sim.zona1;
import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.*;

/** Reproducible node-step movement conflicts, not swept vehicle geometry.
 * Geometry only proves separated chords or opposing reciprocal through movements;
 * merges, near-collinear arms and all other ambiguous pairs remain conflicting.
 */
public final class PriorityMovements {
    public record Movement(Id<Link> from,Id<Link> to) { }
    private final Set<Set<Movement>> disjoint=new HashSet<>();
    private final Node node;
    private final boolean geometric;
    public PriorityMovements(Node node,Zona1PriorityConfigGroup settings) {
        this.node=node;
        geometric=settings.getConflicts().equals("geometric");
        Object value=node.getAttributes().getAttribute("simz1:nonConflictingMovements");
        if(value==null) return;
        if(!settings.getConflicts().equals("verified-node-table"))
            throw new IllegalArgumentException("CONFIG_INVALID: explicit non-conflict table requires verified-node-table: "+node.getId());
        for(String row:value.toString().split(";",-1)) {
            String[] pair=row.split("\\|",-1);
            if(pair.length!=2) throw new IllegalArgumentException("CONFIG_INVALID: non-conflict row "+row);
            Movement a=parse(node,pair[0]), b=parse(node,pair[1]);
            if(a.from.equals(b.from)||a.to.equals(b.to)||!(disjointChords(node,a,b)||oppositeThrough(node,a,b)))
                throw new IllegalArgumentException("CONFIG_INVALID: cannot verify disjoint movements: "+node.getId()+" "+row);
            if(!disjoint.add(Set.of(a,b))) throw new IllegalArgumentException("CONFIG_INVALID: duplicate movement pair "+row);
        }
    }
    private static Movement parse(Node node,String text) {
        String[] ids=text.trim().split(">",-1);
        if(ids.length!=2) throw new IllegalArgumentException("CONFIG_INVALID: movement must be incoming>outgoing");
        var in=node.getInLinks().get(Id.createLinkId(ids[0])); var out=node.getOutLinks().get(Id.createLinkId(ids[1]));
        if(in==null||out==null||!in.getAllowedModes().contains("car")||!out.getAllowedModes().contains("car"))
            throw new IllegalArgumentException("CONFIG_INVALID: unknown/disconnected car movement "+text);
        return new Movement(in.getId(),out.getId());
    }
    private static double[] point(Node center,Node end) {
        double x=end.getCoord().getX()-center.getCoord().getX(), y=end.getCoord().getY()-center.getCoord().getY(), length=Math.hypot(x,y);
        if(!Double.isFinite(length)||length<1e-6) throw new IllegalArgumentException("CONFIG_INVALID: ambiguous movement geometry");
        return new double[]{x/length,y/length};
    }
    private static double cross(double[] a,double[] b,double[] c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);}
    private static boolean disjointChords(Node n,Movement a,Movement b) {
        double[][] p={point(n,n.getInLinks().get(a.from).getFromNode()),point(n,n.getOutLinks().get(a.to).getToNode()),
                      point(n,n.getInLinks().get(b.from).getFromNode()),point(n,n.getOutLinks().get(b.to).getToNode())};
        for(int i=0;i<4;i++) for(int j=0;j<i;j++) if(Math.hypot(p[i][0]-p[j][0],p[i][1]-p[j][1])<1e-6) return false;
        double c1=cross(p[0],p[1],p[2]),c2=cross(p[0],p[1],p[3]),c3=cross(p[2],p[3],p[0]),c4=cross(p[2],p[3],p[1]);
        if(Math.min(Math.min(Math.abs(c1),Math.abs(c2)),Math.min(Math.abs(c3),Math.abs(c4)))<1e-6) return false;
        return c1*c2>0 || c3*c4>0;
    }
    private static boolean oppositeThrough(Node n,Movement a,Movement b) {
        var ai=n.getInLinks().get(a.from); var ao=n.getOutLinks().get(a.to);
        var bi=n.getInLinks().get(b.from); var bo=n.getOutLinks().get(b.to);
        // Exact reciprocal topology establishes two existing opposite directions;
        // no direction of circulation is invented from an axis or road name.
        if(ai.getFromNode()!=bo.getToNode()||bi.getFromNode()!=ao.getToNode()) return false;
        var x=point(n,ai.getFromNode()); var y=point(n,bi.getFromNode());
        return x[0]*y[0]+x[1]*y[1] < -Math.cos(Math.toRadians(15));
    }
    public String evidence(Movement a,Movement b) {
        if(a.from.equals(b.from)) return "same_approach_native_queue";
        if(a.to.equals(b.to)) return "shared_exit_merge";
        if(disjoint.contains(Set.of(a,b))) return "verified_node_table";
        if(geometric) {
            try {
                if(oppositeThrough(node,a,b)) return "reciprocal_opposite_through";
                if(disjointChords(node,a,b)) return "separated_geometric_chords";
            } catch(IllegalArgumentException | NullPointerException ignored) {
                // Missing/degenerate geometry cannot prove a safe non-conflict.
            }
        }
        return "conflicting_or_ambiguous";
    }
    public boolean conflicts(Movement a,Movement b) {
        // Same approach is served serially by QSim queues and their flow limits.
        return Set.of("shared_exit_merge","conflicting_or_ambiguous").contains(evidence(a,b));
    }
}
