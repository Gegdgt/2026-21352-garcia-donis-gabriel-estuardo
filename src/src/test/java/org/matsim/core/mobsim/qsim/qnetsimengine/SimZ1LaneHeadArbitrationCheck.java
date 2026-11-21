package org.matsim.core.mobsim.qsim.qnetsimengine;

import org.matsim.api.core.v01.Id;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Real native lane heads, QNode selection, body ledger and receiver admission.
 * No selected movement is pre-authorized or replaced with a GO mock.
 * Conditions are controlled fixture states, not a reconstruction of Run-2 QSim.
 */
public final class SimZ1LaneHeadArbitrationCheck {
    private static Zona1QNodeImpl node(SimZ1StorageFixture f) {
        var node=f.nodes.get(Id.createNodeId("a-end"));node.init();return node;
    }
    private static void step(SimZ1StorageFixture f,Zona1QNodeImpl node,double now) {
        f.timer.setTime(now);node.doSimStep(now);
    }
    private static void olderHeadWinsAndClearanceStillApplies() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,false,1,true)) {
            var older=f.actor("older-lane1",8,"receipt-a","dest-a");
            var younger=f.actor("younger-lane0",8,"receipt-a","dest-a");
            f.seed(older,".lane.1",0);f.ready(f.queue("receipt-a",".lane.1"),100);
            f.seed(younger,".lane.0",101);f.ready(f.queue("receipt-a",".lane.0"),200);
            require(f.query(older,"dest-a",201).feasible()&&f.query(younger,"dest-a",201).feasible(),"Both heads must have real reception before arbitration");
            var node=node(f);step(f,node,201);
            require(older.index==1&&younger.index==0,"FIXED_LANE_STARVATION: a newer lane.0 head consumed the shared crossing before the eligible older lane.1 head");
            var before=field(node,"crossings").toString();
            for(int i=0;i<5;i++) {
                require(!f.cross(younger,201),"Converging follower crossed before body clearance");
                require(before.equals(field(node,"crossings").toString()),"Failed crossing query changed crossing ownership");
            }
            require(f.moves==1&&f.slot(older)>=0,"Failed crossing consumed route or reservations");
            // Time alone cannot release the modeled body. Native downstream
            // progress must occur at the actual native receiver endpoint.
            step(f,node,300);require(younger.index==0,"Timeout released the crossing without native progress");
            f.ready(f.queue("dest-a",".original"),301);
            step(f,node,321);
            require(younger.index==1&&f.moves==2,"Crossing did not release after real body progress");
            require(field(node,"crossings").toString().contains("younger-lane0")&&!field(node,"crossings").toString().contains("older-lane1"),"Obsolete crossing owner retained");
            f.safety();
        }
    }
    private static void redHeadDoesNotBlockOtherLane() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,true,1,true)) {
            var older=f.actor("red-lane1",8,"receipt-a","dest-a1");
            var younger=f.actor("green-lane0",8,"receipt-a","dest-a");
            var red=f.queue("receipt-a",".lane.1");
            f.seed(older,".lane.1",0);f.ready(red,100);
            f.seed(younger,".lane.0",101);f.ready(f.queue("receipt-a",".lane.0"),200);
            red.setSignalized(true);red.setSignalStateAllTurningMoves(SignalGroupState.RED);
            step(f,node(f),201);
            require(older.index==0&&younger.index==1,"Oldest-first arbitration bypassed red or blocked a different legal head");
            require(red.getFirstVehicle()==older.vehicle,"Red lost its native FIFO head");f.safety();
        }
    }
    private static void fullReceiverDoesNotBlockOtherLane() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true,false,.1,false)) {
            for(int i=0;i<2;i++)f.seed(f.actor("receiver-body"+i,8,"receipt-a","dest-a"),".original",0);
            require(!f.queue("receipt-a",".original").isAcceptingFromUpstream(),"Fixture did not fill native receiving storage");
            var older=f.through("full-lane1",8,"avenue","receipt-a");
            var younger=f.through("available-lane0",8,"avenue","receipt-b");
            f.seed(older,".lane.1",0);f.ready(f.queue("avenue",".lane.1"),100);
            f.seed(younger,".lane.0",101);f.ready(f.queue("avenue",".lane.0"),200);
            var snapshot=SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger);
            for(int i=0;i<240;i++)require(!f.query(older,"short0",201).feasible(),"Pure query accepted a full native receiver");
            require(snapshot.equals(SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger)),"Failed repeated queries changed body reservations");
            var node=f.nodes.get(Id.createNodeId("j"));node.init();step(f,node,201);
            require(older.index==0&&younger.index==1,"Arbitration bypassed full reception or imposed a dependency on a different receiver");
            require(f.queue("avenue",".lane.1").getFirstVehicle()==older.vehicle,"Full receiver lost FIFO head");f.safety();
        }
    }
    public static void main(String[] args) throws Exception {
        olderHeadWinsAndClearanceStillApplies();redHeadDoesNotBlockOtherLane();fullReceiverDoesNotBlockOtherLane();
        System.out.println("PASS native lane head arbitration, body clearance, owner replacement, red and full receiver");
    }
}
