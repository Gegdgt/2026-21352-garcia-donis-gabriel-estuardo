package gt.edu.uvg.sim.labs;

/** Compatibility entry point. The canonical executable is Lab08Zona1Network. */
public final class Lab08FocalAgent {
    private Lab08FocalAgent() {}
    public static void main(String[] args) { Lab08Zona1Network.main(args); }
    static void buildNetwork(org.matsim.api.core.v01.network.Network net) {
        Zona1BaseNetwork.build(net);
    }
}
