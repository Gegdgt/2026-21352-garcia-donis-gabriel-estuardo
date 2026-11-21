package gt.edu.uvg.sim.labs;
import com.google.common.base.CaseFormat;
import org.matsim.api.core.v01.Id;
import org.matsim.core.network.NetworkUtils;
import org.matsim.api.core.v01.network.NetworkWriter;

public final class Lab08ProjectionCheck {
    public static void main(String[] args) {
        if (!"utm-test".equals(CaseFormat.UPPER_UNDERSCORE.to(CaseFormat.LOWER_HYPHEN,"UTM_TEST")))
            throw new AssertionError("Guava runtime");
        var net=NetworkUtils.createNetwork();
        Zona1BaseNetwork.build(net);
        var pivot=Zona1BaseNetwork.coordinate(2,4);
        if(pivot.getX()!=-90.518 || pivot.getY()!=14.646) throw new AssertionError("Pivot moved");
        for(int a=2;a<12;a++) for(int t=4;t<18;t++) {
            var nw=Zona1BaseNetwork.coordinate(a,t);
            var ne=Zona1BaseNetwork.coordinate(a+1,t);
            var sw=Zona1BaseNetwork.coordinate(a,t+1);
            var se=Zona1BaseNetwork.coordinate(a+1,t+1);
            var polygon=new org.matsim.api.core.v01.Coord[]{nw,ne,se,sw};
            for(int i=0;i<4;i++) {
                var x=polygon[i];var y=polygon[(i+1)%4];var z=polygon[(i+2)%4];
                double cross=(y.getX()-x.getX())*(z.getY()-y.getY())-(y.getY()-x.getY())*(z.getX()-y.getX());
                if(!Double.isFinite(cross) || cross>=0) throw new AssertionError("Folded cell");
            }
        }
        for(var link:net.getLinks().values())
            if(!Double.isFinite(link.getLength()) || link.getLength()<=0) throw new AssertionError("Invalid length");
        if (net.getNodes().size()!=166 || net.getLinks().size()!=345) throw new AssertionError("Topology changed");
        var c=net.getNodes().get(Id.createNodeId("A2_C4")).getCoord();
        if(c.getX()<700000 || c.getY()<1500000) throw new AssertionError("Not UTM");
        if(net.getAttributes().getAsMap().keySet().stream().anyMatch(k->k.startsWith("visualArea") || k.startsWith("visualPoi")))
            throw new AssertionError("Decorations remain");
        new NetworkWriter(net).write("target/lab08-utm-fixture.xml");
        Lab08ArgumentsCheck.main(args);
        System.out.println("Guava, warped UTM network, 140 convex cells, topology and clean export verified");
    }
}
