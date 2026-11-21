package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** New Correction 4 checks. Direct component calls, never a previous check's
 * main(), Controler.run(), QSim.run(), or historical replay. */
public final class SimZ1DownstreamStorageCheck {
    private static void pure(SimZ1StorageFixture f,SimZ1StorageFixture.Actor actor,String target,boolean expected,double now) throws Exception {
        // A physical query may not create pending admission, hold clocks,
        // reservations, events, node locks, or native movement.
        var before=new LinkedHashMap<String,String>();
        for(String key:List.of("pending","pendingPassages","passageRequestTime","nodeLocks","connectorLocks","receiptLocks","active","nextOrdinal"))before.put(key,field(f.ledger,key).toString());
        int events=f.events.size(),moves=f.moves;
        for(int i=0;i<3;i++){var result=f.query(actor,target,now+i);require(result.feasible()==expected,"Wrong physical decision: "+f.profile.name()+" "+actor.vehicle.getId()+" "+result);}
        for(var e:before.entrySet())require(e.getValue().equals(field(f.ledger,e.getKey()).toString()),"Physical query mutated "+e.getKey());
        require(events==f.events.size()&&moves==f.moves,"Physical query emitted events/moved traffic");
    }
    private static void realStorageProfiles(Profile profile,double body) throws Exception {
        try(var f=new SimZ1StorageFixture(profile,false)) {
            var actor=f.through("requester",body,"avenue","receipt-a");
            pure(f,actor,"short0",true,10);
            boolean continuous=profile.usable()+1e-8<f.ledger.entryClearanceDistance(actor.vehicle,id("short0"));
            // A real native vehicle at the receiver's entrance occupies its
            // entry interval. Do not fake a full lane by enlarging its capacity.
            String receiving=continuous?"receipt-a":"short0";
            var holder=f.actor("receiving-body",2.1,receiving,continuous?"dest-a":
                f.connectors.size()>1?f.connectors.get(1):"receipt-a");
            f.seed(holder,".original",20);
            // For the two-lane short receiver, occupy every compatible slot.
            if(!continuous&&profile.lanes()>1) {
                var second=f.actor("receiving-body-2",2.1,receiving,f.connectors.size()>1?f.connectors.get(1):"receipt-a");
                f.seed(second,".original",20);
            }
            pure(f,actor,"short0",false,21);
            require(!f.ledger.canEnter(actor.vehicle,id("short0"),"short0.original",25),"Admission contradicted blocked physical query");
            require(f.reservation(actor)==null,"WAIT acquired body storage");
            f.safety();
        }
    }
    private static void noContinuity() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),false)) {
            // No existing origin reservation, no legal downstream stopping
            // place: ending on 1.9812m cannot manufacture off-network storage.
            var actor=f.actor("missing-receipt",13.5,"avenue","short0");
            pure(f,actor,"short0",false,10);
            require(!f.ledger.canEnter(actor.vehicle,id("short0"),"short0.original",10),"Short terminal invented storage");
            f.safety();
        }
    }
    private static void passageLifecycle(double body) throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),true)) {
            var owner=f.through("passage-owner",body,"avenue","receipt-a");
            var follower=f.through("next-request",body,"street","receipt-b");
            f.seed(owner,".lane.0",0);f.ready(f.queue("avenue",".lane.0"),100);
            require(f.cross(owner,101),"Available continuous passage rejected");
            require(f.ledger.lockedByOther(org.matsim.api.core.v01.Id.createNodeId("j"),follower.vehicle.getId())&&
                f.ledger.lockedByOther(org.matsim.api.core.v01.Id.createNodeId("b"),follower.vehicle.getId()),"Connector conflict nodes unprotected");
            near(f.used("avenue",0),0,"Old corridor retained duplicate occupancy");
            near(f.used("receipt-a",f.slot(owner)),body+.1,"Downstream body not reserved exactly once");
            pure(f,follower,"short0",false,101);
            f.ready(f.queue("short0",".original"),101.2);f.split("short0",101.3);
            f.ready(f.queue("short0",".lane.0"),102);
            require(f.cross(owner,102.1),"Owner failed to reach its reserved receiver");
            near(f.front(owner),0,"Entry invented receiver traversal");
            var p=field(f.reservation(owner),"passage");
            f.ledger.advanceTime(200);
            require(!(boolean)field(p,"released"),"Elapsed time released an uncleared body");
            pure(f,follower,"short0",false,200);
            f.ready(f.queue("receipt-a",".original"),201);f.split("receipt-a",202);
            f.ready(f.queue("receipt-a",".lane."+f.slot(owner)),210);
            require((boolean)field(p,"released"),"Native body clearance left obsolete passage locks");
            require(!f.ledger.lockedByOther(org.matsim.api.core.v01.Id.createNodeId("j"),follower.vehicle.getId())&&
                !f.ledger.lockedByOther(org.matsim.api.core.v01.Id.createNodeId("b"),follower.vehicle.getId()),"Cleared passage retained a conflict node");
            pure(f,follower,"short0",true,211);
            long releases=f.events.stream().filter(e->e.getEventType().equals("simz1OccupancyPassage")&&"RELEASE".equals(e.getAttributes().get("action"))).count();
            require(releases==1,"Passage release must occur exactly once");
            require(f.links.get(id("short0")).getVehicle(owner.vehicle.getId())==null&&
                f.links.get(id("receipt-a")).getVehicle(owner.vehicle.getId())==owner.vehicle,"Transferred vehicle has stale native reference");
            f.safety();
        }
    }
    private static void prioritiesAndTwoCorridors() throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(0),false)) {
            var avenue=f.through("avenue-head",4.5,"avenue","receipt-a");
            var street=f.through("street-head",4.5,"street","receipt-b");
            f.seed(avenue,".lane.0",0);f.seed(street,".lane.0",0);
            f.ready(f.queue("avenue",".lane.0"),100);f.ready(f.queue("street",".lane.0"),100);
            var cfg=new Zona1PriorityConfigGroup();cfg.setClassification("explicit");cfg.setConflicts("conservative");
            var priority=new UnsignalizedPriority.StopAndYield(f.scenario.getNetwork().getNodes().get(org.matsim.api.core.v01.Id.createNodeId("j")),cfg,null,null,f.scenario.getConfig().qsim());
            var streetLink=f.links.get(id("street")).getLink();
            require(!priority.passageMayProceed(streetLink,id("short0"),street.vehicle,f.qnet,101),"Viable avenue lost legitimate priority");
            var blockerA=f.actor("blocked-a",4.5,"receipt-a","dest-a");f.seed(blockerA,".original",102);
            pure(f,avenue,"short0",false,103);pure(f,street,"short0",true,103);
            require(priority.passageMayProceed(streetLink,id("short0"),street.vehicle,f.qnet,103),"Unreceivable competitor creates circular priority wait");
            var blockerB=f.actor("blocked-b",4.5,"receipt-b","dest-b");f.seed(blockerB,".original",104);
            pure(f,avenue,"short0",false,105);pure(f,street,"short0",false,105);
            require(!f.cross(street,105),"Two occupied corridors allowed an impossible movement");
            require(f.moves==0,"Congestion manufactured a discharge");
            // Native travel in B creates real entry space. A remains occupied.
            f.ready(f.queue("receipt-b",".original"),110);f.split("receipt-b",111);
            f.ready(f.queue("receipt-b",".lane.0"),120);
            pure(f,street,"short0",true,121);pure(f,avenue,"short0",false,121);
            require(priority.passageMayProceed(streetLink,id("short0"),street.vehicle,f.qnet,121),"Newly freed corridor still waits on blocked competitor");
            require(f.cross(street,122),"Freed corridor did not discharge");
            f.safety();
        }
    }
    public static void main(String[] args) throws Exception {
        try {
            for(var profile:PROFILES)for(double body:new double[]{2.1,4.5,8,13.5})realStorageProfiles(profile,body);
            noContinuity();for(double body:new double[]{2.1,4.5,8,13.5})passageLifecycle(body);
            prioritiesAndTwoCorridors();
            System.out.println("PASS SimZ1DownstreamStorageCheck: real metric profiles, native discharge, passage lifetime, viable priority; geometric capacities unchanged");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
