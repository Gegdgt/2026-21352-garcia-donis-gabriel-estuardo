package gt.edu.uvg.sim.zona1;

public final class SimZ1FreightCheck {
    public static void main(String[] args) {
        for(double t:new double[]{0,17999,32400,57599,75600,86399,86400,104399})
            if(!SimZ1Freight.permitted(t,t)) throw new AssertionError("Allowed "+t);
        for(double t:new double[]{-1,18000,32399,57600,75599,104400,Double.NaN})
            if(SimZ1Freight.permitted(t,t)) throw new AssertionError("Forbidden "+t);
        if(SimZ1Freight.permitted(17999,32401) || SimZ1Freight.permitted(57599,75601))
            throw new AssertionError("Queue residence crossed a restriction");
        if(!SimZ1Freight.permitted(77400,86400) || !SimZ1Freight.permitted(77400,104399) ||
                SimZ1Freight.permitted(77400,104400)) throw new AssertionError("Overnight window boundary");
        if(SimZ1Freight.permitted(77400,86400,SimZ1Freight.LEGACY_RESIDENCE_POLICY) ||
                !SimZ1Freight.permitted(77400,86399,SimZ1Freight.LEGACY_RESIDENCE_POLICY))
            throw new AssertionError("Historical clipped contract must remain explicit");
        System.out.println("SIMZ1_FREIGHT_WINDOWS_OK");
    }
}
