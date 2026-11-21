package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Bounded native QUEUE components, never QSim or a historical replay.
 * Measured lengths are from the 220K prefix; other junction geometry is the
 * existing synthetic StorageFixture. Reproduces sufficient mechanisms, not
 * every queue/reservation of the historical network. */
public final class SimZ1ClosureCirculationCheck {
    private static void downstreamReceiptQueue() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(4),true)) {
            var requester=f.through("passage-request",4.5,"avenue","receipt-a");
            var a=f.actor("native-receiver-truck-a",8,"receipt-a","dest-a");
            var b=f.actor("native-receiver-truck-b",8,"receipt-a","dest-a");
            f.seed(a,".original",0);f.seed(b,".original",0);
            var q=f.queue("receipt-a",".original");
            require(!q.isAcceptingFromUpstream(),"Fixture must fill the real native original queue");
            near(q.getLoadIndicator(),7,"Both real truck PCUs must be counted once");
            near(f.used("receipt-a",2),0,"Third body slot must remain available");
            int before=f.events.size();String active=field(f.ledger,"active").toString();
            for(double now:new double[]{1,60,3600,59159}) {
                var result=f.query(requester,"short0",now);
                require(!result.feasible()&&result.reason().equals("passage_receipt_native_queue"),
                    "Empty immediate connector is not a receipt: "+result);
            }
            require(f.events.size()==before&&active.equals(field(f.ledger,"active").toString()),"Probe changed events/reservations");
            require(!f.ledger.canEnter(requester.vehicle,id("short0"),"short0.original",59159),"Full downstream original was bypassed");
            require(f.reservation(requester)==null,"Rejected query acquired a body");
            // Native queue progression frees reception; no timeout or deletion.
            f.ready(q,59160);f.split("receipt-a",59161);f.ready(q,59162);f.split("receipt-a",59163);
            require(q.isAcceptingFromUpstream(),"Native receipt failed to release travel PCU into terminal queues");
            require(f.query(requester,"short0",59164).feasible(),"Available compatible third slot ignored");
            f.safety();
            System.out.println("PASS passage receipt: empty connector + free body slot still WAIT while native receiving queue full; real progression releases it");
        }
    }

    private static void nativePcuVersusCorridorMeters() throws Exception {
        var profile=new Profile("48273209_10_11 measured lengths",new double[]{6.419016889214191,100.24623620713076},2,102.77982061443232);
        try(var f=new SimZ1StorageFixture(profile,false)) {
            var q=f.queue("short1",".original");
            var busA=f.actor("bus-a",13.5,"short1","receipt-a","dest-a");
            var busB=f.actor("bus-b",13.5,"short1","receipt-a","dest-a");
            f.seed(busA,".original",11);
            require(q.isAcceptingFromUpstream(),"3 PCU must be below original capacity");
            f.seed(busB,".original",11);
            near(q.getStorageCapacity(),5.346465931046972,"Historical original queue geometry");
            near(q.getLoadIndicator(),6,"Two bus travel reservations count 6 PCU");
            require(!q.isAcceptingFromUpstream(),"Native threshold must reject 6 >= 5.346466");
            require(f.used("short1",0)+f.used("short1",1)<2*profile.usable(),"Body ledger must still have aggregate room");
            var requester=f.actor("requesting-motorcycle",2.1,"short0","short1","receipt-a","dest-a");
            int before=f.events.size();
            for(double now:new double[]{21,3600,59159}) {
                var result=f.query(requester,"short1",now);
                require(!result.feasible()&&result.reason().equals("receiver_native_storage"),"PCU-full receiver admitted a motorcycle: "+result);
            }
            require(f.moves==0&&requester.index==0&&f.events.size()==before,"WAIT changed cursor, events or movement");
            near(f.used("short1",0)+f.used("short1",1),13.6+13.6,"Each body exists exactly once in shared corridor");
            // Normal native queue processing accounts a bus in buffer separately.
            f.ready(q,59160);
            require(q.getFirstVehicle()==busA.vehicle,"Native FIFO changed while moving to buffer");
            near(q.getLoadIndicator(),3,"Native travel PCU excludes the buffered bus");
            near(f.used("short1",0)+f.used("short1",1),13.6+13.6,"Buffer transition must retain both bodies");
            f.safety();
            System.out.println("PASS PCU/meter reconciliation: actual native queue 6/5.346465931 PCU, later buffer excluded, two body reservations once; aggregate space is not native admission");
        }
    }

    private static void crossingBodyAndParallelLanes() throws Exception {
        var profile=new Profile("30262980_10 measured receiver",new double[]{31.02062790185436},3,26.02052437573696);
        try(var f=new SimZ1StorageFixture(profile,false)) {
            var owner=f.through("crossing-truck",8,"avenue","receipt-a");
            var follower=f.through("parallel-requester",4.5,"avenue","receipt-a");
            f.seed(owner,".lane.0",0);f.seed(follower,".lane.1",0);
            f.ready(f.queue("avenue",".lane.0"),100);f.ready(f.queue("avenue",".lane.1"),100);
            require(f.cross(owner,101),"Truck was not natively admitted");
            f.ready(f.queue("short0",".original"),110);
            near(f.front(owner),6.204125580370871,"Native original endpoint must reproduce measured front");
            double threshold=f.ledger.entryClearanceDistance(owner.vehicle,id("short0"));
            require(threshold>=8.1&&f.front(owner)<8.1,"Truck body/gap still straddles entry before any conflict margin");
            int ordinal=f.slot(owner);String active=field(f.ledger,"active").toString();
            for(double now:new double[]{111,3600,59159}) {
                require(!f.cross(follower,now),"Different lane/elapsed time bypassed crossing body");
                require(!f.ledger.crossingCleared(owner.vehicle.getId(),f.ledger.corridorId(id("short0")),threshold,101,now),"Timer released uncleared body");
            }
            require(f.slot(owner)==ordinal&&active.equals(field(f.ledger,"active").toString()),"WAIT changed reservations");
            require(f.events.stream().anyMatch(e->"modeled_body_clearance".equals(e.getAttributes().get("conflictEvidence"))||
                "admission_conflict_executed".equals(e.getAttributes().get("reason"))),"Missing native crossing rejection evidence");
            f.split("short0",59160);f.ready(f.queue("short0",".lane."+f.slot(owner)),59170);
            require(f.ledger.crossingCleared(owner.vehicle.getId(),f.ledger.corridorId(id("short0")),threshold,101,59171),"Real body progression did not clear crossing");
            require(f.cross(follower,59172),"Cleared crossing retained obsolete lock");
            f.safety();
            System.out.println("PASS crossing body: front=6.204125580 < footprint=8.1, parallel source lane and long wait do not clear; real native progression releases");
        }
    }
    public static void main(String[] args) throws Exception {
        try {downstreamReceiptQueue();nativePcuVersusCorridorMeters();crossingBodyAndParallelLanes();
            System.out.println("PASS closure circulation mechanisms; component-only, no QSim, no capacity changes to production");}
        finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
