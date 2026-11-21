package gt.edu.uvg.sim.zona1;

import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionFixture;

/** Run against the exact historical detector, isolated from repaired production. */
public final class SimZ1RetentionBeforeCheck {
    public static void main(String[] args)throws Exception {
        try {
            var f=new SimZ1RetentionFixture(false);var r=new CongestionAwareRerouting(f.s);f.events.addHandler(r);
            int[] physicalWaits={0};f.events.addHandler(new org.matsim.core.events.handler.BasicEventHandler(){
                public void handleEvent(Event event){if("simz1NativeDecision".equals(event.getEventType()) && "receiver_native_storage".equals(event.getAttributes().get("reason")))physicalWaits[0]++;}
            });
            var previous=Id.createVehicleId("completed");var link=SimZ1RetentionFixture.id("s");
            r.handleEvent(new LinkEnterEvent(31449,previous,link));r.handleEvent(new LinkLeaveEvent(31658,previous,link));
            f.markTraffic(0);f.waitUntil(31659,31980);
            var road=f.s.getNetwork().getLinks().get(link);double nominal=road.getLength()/road.getFreespeed();
            if(r.observedLinkSeconds(link,31920)!=209 || !Double.isNaN(r.observedLinkSeconds(link,31980)))throw new AssertionError("TTL mismatch");
            if(CongestionAwareRerouting.needsReroute(true,nominal,nominal,road.getCapacity(),road.getCapacity()))throw new AssertionError("Old detector unexpectedly severe");
            if(f.lane("s","s.lane.0").getFirstVehicle()!=f.head || f.lane("bad","bad.original").isAcceptingFromUpstream())throw new AssertionError("No real retained head");
            if(physicalWaits[0]!=317)throw new AssertionError("Expected317 confirmed native rejections after stop: "+physicalWaits[0]);
            System.out.println("BEFORE: completed=209@31658 fresh at31920, expired at31980; old severe=false despite 316s of native receiver WAIT after mandatory stop and no exits");
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
