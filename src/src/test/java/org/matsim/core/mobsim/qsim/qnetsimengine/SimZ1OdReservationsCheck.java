package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.SimZ1OdContractCheck;
import java.util.List;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.lanes.Lane;

/** Reuse the existing occupied-ledger fixture; never runs its simulation counterparts. */
public final class SimZ1OdReservationsCheck {
    static Object field(Object o,String name)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    public static void main(String[] args)throws Exception {
        try {
            var type=Class.forName(SimZ1OpposedReturnRerouteCheck.class.getName()+"$Fixture");
            var constructor=type.getDeclaredConstructor(double.class,int.class,boolean.class,double.class,boolean.class);constructor.setAccessible(true);
            try(var fixture=(AutoCloseable)constructor.newInstance(4.5,2,true,79.33965536064153,true)) {
                var ledger=(SimZ1CorridorOccupancy)field(fixture,"ledger");String before=SimZ1OpposedReturnRerouteCheck.snapshot(ledger);
                var actor=field(fixture,"backward");var leg=(Leg)field(actor,"leg");int index=(int)field(actor,"index");
                var events=(List<?>)field(fixture,"events");int count=events.size();
                SimZ1OdContractCheck.reservationQueries((Scenario)field(fixture,"s"),leg,index,Id.create("backward.original",Lane.class));
                SimZ1OpposedReturnRerouteCheck.check(before.equals(SimZ1OpposedReturnRerouteCheck.snapshot(ledger)),"OD queries changed actual reservations/locks/ordinals");
                SimZ1OpposedReturnRerouteCheck.check(count==events.size() && index==(int)field(actor,"index"),"OD queries emitted ledger events or consumed route cursor");
                System.out.println("PASS C529-B: 20 accepted/rejected candidate queries preserve occupied ledger, reservations, locks, cursor and events");
            }
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
