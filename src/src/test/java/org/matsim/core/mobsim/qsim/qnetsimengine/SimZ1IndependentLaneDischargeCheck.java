package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Native shared original / terminal seam at unchanged metric/PCU capacity.
 * A controlled full-load snapshot isolates the receiving queue's rejection;
 * it never changes storageCapacity and is restored before subsequent travel.
 */
public final class SimZ1IndependentLaneDischargeCheck {
    private static boolean buffered(QueueWithBuffer q,SimZ1StorageFixture.Actor a,SimZ1StorageFixture f){
        return q.originalSlotHeads(f.ledger).contains(a.vehicle);
    }
    private static void discharge(double body,boolean fast,double step) throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,true,step,true)) {
            f.scenario.getConfig().qsim().setUsingFastCapacityUpdate(fast);
            var blocked=f.actor("older-slot0",8,"receipt-a","dest-a");
            var independent=f.actor("independent-slot1",body,"receipt-a","dest-a1");
            var original=f.queue("receipt-a",".original");var terminal0=f.queue("receipt-a",".lane.0");
            var terminal1=f.queue("receipt-a",".lane.1");
            f.seed(blocked,".original",0);f.seed(independent,".original",0);
            require(f.slot(blocked)==0&&f.slot(independent)==1,"Fixture did not reserve independent compatible slots");
            double bodyPcu=independent.vehicle.getSizeInEquivalents();
            near(original.getLoadIndicator(),3.5+bodyPcu,"Native travelling load duplicated/missing");
            f.ready(original,2);
            require(original.getFirstVehicle()==blocked.vehicle&&!buffered(original,independent,f),"Fixture must begin with retained old grant and travelling head");
            near(original.getLoadIndicator(),bodyPcu,"Native travelling-to-buffer failed to debit storage");
            double age=original.getLastMovementTimeOfFirstVehicle();
            f.ready(original,2+step);
            require(!buffered(original,independent,f),"Independent slot received free flow credit before prior PCU debt was paid");
            for(int tick=2;tick<=Math.round(3/step);tick++)f.ready(original,2+tick*step);
            // Before Correction 4 this fails: the old slot0 grant caps the
            // accumulator at flowPerStep - 3.5 forever, below zero. The ready
            // independent body never becomes visible to originalSlotHeads.
            require(buffered(original,independent,f),"ORIGINAL_RETAINED_GRANT: ready independent head is imprisoned before the offering buffer");
            near(original.getLoadIndicator(),0,"Buffer arrival retained native travelling storage");
            near(f.used("receipt-a",0),8.1,"Original vehicle counted twice in ledger");
            near(f.used("receipt-a",1),body+.1,"Independent vehicle counted twice in ledger");
            double savedLoad=terminal0.getLoadIndicator();double capacity=terminal0.getStorageCapacity();
            set(terminal0,"usedStorageCapacity",capacity);
            try {
                f.split("receipt-a",6);
                require(original.getFirstVehicle()==blocked.vehicle&&terminal1.getVehicle(independent.vehicle.getId())==independent.vehicle,
                    "Full independent terminal prevented legal discharge");
                near(original.getLastMovementTimeOfFirstVehicle(),age,"Independent discharge reset the older head's age");
                require(f.slot(independent)==1,"Vehicle changed reserved lane");
                near(terminal1.getLoadIndicator(),bodyPcu,"Receiver did not acquire native storage exactly once");
                near(f.used("receipt-a",1),body+.1,"Internal transfer duplicated/released metric body");
                require(original.getVehicle(independent.vehicle.getId())==null,"Original retained transferred vehicle");
                require(f.moves==0,"Internal lane discharge invented a link crossing");
            } finally {set(terminal0,"usedStorageCapacity",savedLoad);}
            near(terminal0.getStorageCapacity(),capacity,"Fixture changed capacity to obtain PASS");
            f.ready(terminal1,13);
            near(terminal1.getLoadIndicator(),0,"Native receiver did not free travelling storage at buffer arrival");
            require(terminal1.getFirstVehicle()==independent.vehicle,"Freed PCU lost physical buffered vehicle");
            near(f.used("receipt-a",1),body+.1,"Body storage was released before native link departure");
            require(f.cross(independent,14),"Available downstream link rejected a real discharge");
            near(f.used("receipt-a",1),0,"Link departure retained old metric storage");
            require(f.links.get(id("receipt-a")).getVehicle(independent.vehicle.getId())==null&&
                f.links.get(id("dest-a1")).getVehicle(independent.vehicle.getId())==independent.vehicle,"Native transfer left obsolete references");
            near(f.used("dest-a1",0),body+.1,"New corridor occupancy missing/doubled");
            f.safety();
        }
    }
    private static void sameLaneFifo() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,true)) {
            var head=f.actor("same-slot-head",4.5,"receipt-a","dest-a");
            var next=f.actor("same-slot-follower",2.1,"receipt-a","dest-a");
            var original=f.queue("receipt-a",".original");f.seed(head,".original",0);f.ready(original,2);
            f.seed(next,".original",3);require(f.slot(head)==f.slot(next),"Fixture has no FIFO relationship");
            for(int tick=50;tick<=100;tick++)f.ready(original,tick/10.0);
            require(original.getFirstVehicle()==head.vehicle&&!buffered(original,next,f),"Same-slot follower overtook retained head");
            near(original.getLoadIndicator(),next.vehicle.getSizeInEquivalents(),"Waiting follower lost native storage");
            boolean rejected=false;
            try {original.popOriginalSlotHead(next.vehicle,f.ledger);}catch(IllegalStateException expected){rejected=true;}
            require(rejected,"Native FIFO removal accepted a non-head");
            f.split("receipt-a",11);require(f.queue("receipt-a",".lane.0").getVehicle(head.vehicle.getId())==head.vehicle,"First body did not transfer");
            for(int tick=111;tick<=130;tick++)f.ready(original,tick/10.0);
            require(original.getFirstVehicle()==next.vehicle,"Next same-lane head did not retry after discharge");
            f.safety();
        }
    }
    private static void nativeFullReceiver() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true)) {
            var first=f.actor("native-load-0",8,"receipt-a","dest-a");
            var second=f.actor("native-load-1",8,"receipt-a","dest-a");
            f.seed(first,".original",0);f.seed(second,".original",0);
            var queue=f.queue("receipt-a",".original");var requester=f.through("third-free-slot",2.1,"avenue","receipt-a");
            require(!queue.isAcceptingFromUpstream(),"Two real native trucks did not fill the original queue");
            require(!f.query(requester,"receipt-a",1).feasible(),"Free metric slot bypassed full native receiving storage");
            near(f.used("receipt-a",2),0,"Third lane unexpectedly occupied");
            f.ready(queue,2);
            require(queue.isAcceptingFromUpstream()&&f.query(requester,"receipt-a",2).feasible(),"Native storage freed by real buffer arrival was not visible");
            near(queue.getLoadIndicator(),3.5,"Native first departure double-debited or failed to free storage");
            near(f.used("receipt-a",f.slot(first)),8.1,"Travelling storage release incorrectly removed physical body");
            f.safety();
        }
    }
    private static void greenStillNeedsStorage() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true)) {
            var a=f.actor("signal-head",4.5,"receipt-a","dest-a");f.seed(a,".lane.0",0);
            var source=f.queue("receipt-a",".lane.0");f.ready(source,100);
            source.setSignalized(true);source.setSignalStateAllTurningMoves(SignalGroupState.GREEN);
            var receiver=f.queue("dest-a",".original");double saved=receiver.getLoadIndicator();
            set(receiver,"usedStorageCapacity",receiver.getStorageCapacity());
            try {
                require(!f.cross(a,101)&&f.moves==0,"Green manufactured space in full receiver");
                require(source.getFirstVehicle()==a.vehicle,"Green WAIT removed source head");
            } finally {set(receiver,"usedStorageCapacity",saved);}
            source.setSignalStateAllTurningMoves(SignalGroupState.RED);
            require(!f.cross(a,102)&&f.moves==0,"Free receiver crossed red");
            source.setSignalStateAllTurningMoves(SignalGroupState.GREEN);
            require(f.cross(a,103)&&f.moves==1,"Green with available receipt failed to move");
            f.safety();
        }
    }
    private static void withoutLedgerKeepsNativeRule() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,true,1,true)) {
            var head=f.actor("no-ledger-head",8,"receipt-a","dest-a");
            var other=f.actor("no-ledger-other",4.5,"receipt-a","dest-a1");
            var original=f.queue("receipt-a",".original");f.seed(head,".original",0);f.seed(other,".original",0);f.ready(original,2);
            SimZ1CorridorOccupancy.uninstall(f.scenario.getConfig().qsim());
            try {
                for(int tick=3;tick<=10;tick++)f.ready(original,tick);
                require(original.getFirstVehicle()==head.vehicle&&!buffered(original,other,f),"Changed native rule without the SimZ1 ledger");
                near(original.getLoadIndicator(),1,"Unproven independent slot changed native storage");
            } finally {SimZ1CorridorOccupancy.install(f.scenario.getConfig().qsim(),f.ledger);}
            f.safety();
        }
    }
    public static void main(String[] args) throws Exception {
        try {
            for(double step:new double[]{1,.1})for(boolean fast:new boolean[]{true,false})
                for(double body:new double[]{2.1,4.5,8,13.5})discharge(body,fast,step);
            sameLaneFifo();nativeFullReceiver();greenStillNeedsStorage();withoutLedgerKeepsNativeRule();
            System.out.println("PASS SimZ1IndependentLaneDischargeCheck: retained grants, flow debt, independent discharge, FIFO, native storage and signals; no capacity enlargement");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
