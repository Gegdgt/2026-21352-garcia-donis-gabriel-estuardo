package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.*;
import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgent;
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1TransitPassageReleaseCheck.*;

/** Correction 3 integration seam: real QueueWithBuffer / QLinkLanesImpl calls,
 * including the native transit arrival branch. No controller, generated demand,
 * QSim run, historical input mutation or benchmark. Reflection only selects the
 * existing private lane-transfer method and installs a full-storage snapshot.
 */
public final class SimZ1TransitPassageNativeCheck {
    private static final class NativeFixture implements AutoCloseable {
        final Fixture f;
        final MobsimTimer timer=new MobsimTimer(1);
        final QLinkLanesImpl link;
        final QueueWithBuffer original,middle,terminal;
        final QVehicleImpl blockedHead;
        boolean wantsArrival;
        int arrivals;
        NativeFixture(String name,double deadline) throws Exception {this(name,deadline,false);}
        NativeFixture(String name,double deadline,boolean directSplit) throws Exception {
            f=new Fixture(name,13.5,directSplit);var config=f.scenario.getConfig().qsim();
            config.setUseLanes(true);config.setUsingFastCapacityUpdate(false);config.setRemoveStuckVehicles(false);
            config.setNodeOffset(0); // no visualization services in this native queue fixture
            config.setNumberOfThreads(1);config.setTrafficDynamics(QSimConfigGroup.TrafficDynamics.queue);
            blockedHead=directSplit?vehicle("blocked-other-slot",4.5):null;
            if(blockedHead!=null)f.admit(blockedHead,RECEIPT,ORIGINAL,25439);
            f.held(deadline);
            var driver=(TransitDriverAgent)Proxy.newProxyInstance(TransitDriverAgent.class.getClassLoader(),new Class<?>[]{TransitDriverAgent.class},
                (proxy,method,args)->switch(method.getName()){
                    case "getId"->Id.createPersonId(name+"-driver");
                    case "getMode"->"car";
                    case "getNextTransitStop"->null;
                    case "chooseNextLinkId"->wantsArrival?null:TAIL;
                    case "isWantingToArriveOnCurrentLink"->wantsArrival;
                    default->throw new AssertionError("Unexpected transit driver call: "+method);
                });
            f.owner.setDriver(driver);
            if(blockedHead!=null)blockedHead.setDriver((org.matsim.core.mobsim.framework.MobsimDriverAgent)Proxy.newProxyInstance(
                org.matsim.core.mobsim.framework.MobsimDriverAgent.class.getClassLoader(),
                new Class<?>[]{org.matsim.core.mobsim.framework.MobsimDriverAgent.class},(proxy,method,args)->switch(method.getName()){
                    case "getId"->Id.createPersonId("blocked-other-slot-driver");case "getMode"->"car";
                    case "chooseNextLinkId"->TAIL;case "isWantingToArriveOnCurrentLink"->false;
                    default->throw new AssertionError("Unexpected car driver call: "+method);
                }));
            var engine=new QNetsimEngineI.NetsimInternalInterface(){
                public QNetwork getNetsimNetwork(){throw new AssertionError("No network simulation expected");}
                public void arrangeNextAgentState(MobsimAgent agent){throw new AssertionError("No abort/forced arrival expected");}
                public void letVehicleArrive(QVehicle vehicle){require(vehicle==f.owner,"Wrong native arrival");arrivals++;}
            };
            var context=new NetsimEngineContext(f.manager,7.5,null,null,config,timer,null);
            var road=f.scenario.getNetwork().getLinks().get(RECEIPT);
            link=(QLinkLanesImpl)new QLinkLanesImpl.Builder(context,engine).build(road,null,
                LanesUtils.createLanes(road,f.scenario.getLanes().getLanesToLinkAssignments().get(RECEIPT)));
            link.setNetElementActivationRegistry(new NetElementActivationRegistry(){
                void registerNodeAsActive(QNodeI node) { }
                void registerLinkAsActive(QLinkI qlink) { }
                int getNumberOfSimulatedNodes(){return 0;}
                int getNumberOfSimulatedLinks(){return 1;}
            });
            original=(QueueWithBuffer)link.getQueueLanes().get(Id.create(ORIGINAL,Lane.class));
            middle=(QueueWithBuffer)link.getQueueLanes().get(Id.create(MIDDLE,Lane.class));
            terminal=(QueueWithBuffer)link.getQueueLanes().get(Id.create(TERMINAL,Lane.class));
            SimZ1CorridorOccupancy.install(config,f.ledger);
        }
        void transfer(QLaneI from,double now) throws Exception {
            timer.setTime(now);var method=QLinkLanesImpl.class.getDeclaredMethod("moveBufferToNextLane",QLaneI.class);
            method.setAccessible(true);method.invoke(link,from);
        }
        public void close(){SimZ1CorridorOccupancy.uninstall(f.scenario.getConfig().qsim());}
    }
    private static void realBufferAndTransfers() throws Exception {
        try(var n=new NativeFixture("native-buffer-bus",DEADLINE)){
            var f=n.f;n.timer.setTime(25447);n.original.addFromUpstream(f.owner);
            close(f.front(f.owner),0,"Native entry did not update ledger");
            double earliest=f.owner.getEarliestLinkExitTime();require(earliest>25447,"Fixture travel interval missing");
            n.original.doSimStep();require(n.original.isNotOfferingVehicle(),"Moved to buffer before native earliest exit");
            close(f.front(f.owner),0,"Progress invented before earliest exit");
            n.timer.setTime(earliest);n.original.doSimStep();
            require(n.original.getFirstVehicle()==f.owner,"Native queue-to-buffer transition failed");
            close(f.nativeFront(f.owner),ORIGINAL_END,"Buffer endpoint not synchronized");f.heldLocks();
            int beforeProbe=f.states().size();
            f.ledger.passageStorageWait(f.owner,RECEIPT,ORIGINAL,RECEIPT,n.middle,earliest);
            require(f.states().size()==beforeProbe,"Available storage mislabeled as downstream blockage");
            // Reconstruct a rejected receiving queue, without inventing any
            // native vehicle trajectory. Restore its exact prior load below.
            double oldLoad=n.middle.getLoadIndicator();set(n.middle,"usedStorageCapacity",n.middle.getStorageCapacity());
            n.transfer(n.original,25501);long count=f.states().size();int allEvents=f.events.size();
            require("passage_waiting_for_downstream_storage".equals(f.states().get(f.states().size()-1).getAttributes().get("reason")),"Missing internal native-storage observation");
            for(int i=0;i<100;i++){
                n.timer.setTime(68400+i);f.ledger.advanceTime(68400+i);n.original.doSimStep();n.transfer(n.original,68400+i);
            }
            require(n.original.getFirstVehicle()==f.owner&&n.middle.getVehicle(f.owner.getId())==null,"Rejected receiver moved bus");
            require(f.events.size()==allEvents&&f.states().size()==count,"Stationary native buffer produced event growth");
            close(f.front(f.owner),ORIGINAL_END,"Buffer wait invented physical progress");require(f.releases(f.owner)==0,"Full receiver released uncleared passage");
            set(n.middle,"usedStorageCapacity",oldLoad);n.transfer(n.original,68501);
            require(n.original.isNotOfferingVehicle()&&n.middle.getVehicle(f.owner.getId())==f.owner,"Real lane transfer missing");
            close(f.front(f.owner),ORIGINAL_END,"Lane entry invented endpoint traversal");
            n.timer.setTime(Math.max(68501,f.owner.getEarliestLinkExitTime()));n.middle.doSimStep();
            close(f.front(f.owner),f.clearance,"Native earliest exit failed to propagate clearance");
            f.releasedLocks();require(f.releases(f.owner)==1,"Native progress after consumed deadline failed release");
            n.transfer(n.middle,68502);require(n.terminal.getVehicle(f.owner.getId())==f.owner,"Transfer to terminal missed");
            require(f.releases(f.owner)==1&&n.arrivals==0,"Duplicate release or forced arrival");
            f.finish(68503);
            System.out.println("PASS native addFromUpstream / earliest exit / addToBuffer / storage WAIT / lane transfer; no fabricated progress");
        }
    }
    private static void verifiedTransitExit() throws Exception {
        try(var n=new NativeFixture("native-exit-bus",70000)){
            var f=n.f;n.timer.setTime(25447);n.original.addFromUpstream(f.owner);n.wantsArrival=true;
            n.timer.setTime(f.owner.getEarliestLinkExitTime());n.original.doSimStep();
            require(n.arrivals==1&&n.link.getParkedVehicle(f.owner.getId())==f.owner,"Native transit arrival not verified");
            require(f.events.stream().filter(e->e instanceof VehicleLeavesTrafficEvent).count()==1,"Missing native leaves-traffic event");
            require(n.original.getVehicle(f.owner.getId())==null&&f.reservation(f.owner)==null,"Native exit left orphan reservation");
            f.releasedLocks();require(f.releases(f.owner)==1,"Transit native exit failed exactly-once release");
            require(f.states().stream().noneMatch(e->"passage_released_after_clearance".equals(e.getAttributes().get("reason"))),"Native exit reported as observed body clearance");
            f.ledger.advanceTime(70001);require(f.releases(f.owner)==1,"Old deadline duplicated native exit release");f.finish(70002);
            System.out.println("PASS real transit native arrival: parked, leaves traffic, all locks removed once");
        }
    }
    private static void activePassageInIndependentReceivingSlot() throws Exception {
        try(var n=new NativeFixture("parallel-receipt-bus",DEADLINE,true)){
            var f=n.f;var freeTerminal=(QueueWithBuffer)n.link.getQueueLanes().get(Id.create("receipt.lane.1",Lane.class));
            n.timer.setTime(25447);n.original.addFromUpstream(n.blockedHead);n.original.addFromUpstream(f.owner);
            n.timer.setTime(f.owner.getEarliestLinkExitTime());n.original.doSimStep();
            require(n.original.getFirstVehicle()==n.blockedHead,"Missing older native buffer head");
            require(f.ledger.originalSlot(n.blockedHead,RECEIPT,ORIGINAL)==0,"Blocked head's slot drifted");
            require(f.ledger.originalSlot(f.owner,RECEIPT,ORIGINAL)==1,
                "ACTIVE_PASSAGE_RECEIVER_FIFO: an already-entered bus is hidden from its independent receiving slot until it clears itself");
            f.heldLocks();double oldLoad=n.terminal.getLoadIndicator();set(n.terminal,"usedStorageCapacity",n.terminal.getStorageCapacity());
            double headAge=n.original.getLastMovementTimeOfFirstVehicle(),headFront=f.front(n.blockedHead);
            require(freeTerminal.isAcceptingFromUpstream(),"Independent native terminal is not free");
            n.transfer(n.original,25501);
            require(n.original.getFirstVehicle()==n.blockedHead&&freeTerminal.getVehicle(f.owner.getId())==f.owner,
                "Full unrelated terminal blocked the active passage owner's available terminal");
            close(n.original.getLastMovementTimeOfFirstVehicle(),headAge,"Passing other slot reset blocked head's age");
            close(f.front(n.blockedHead),headFront,"Independent transfer moved the blocked head");
            close(f.front(f.owner),ORIGINAL_END,"Native internal transfer invented clearance");
            require((int)field(f.reservation(f.owner),"slot")==1,"Bus changed its reserved lane");
            f.heldLocks();require(f.releases(f.owner)==0,"Parallel transfer released uncleared tail");
            n.timer.setTime(f.owner.getEarliestLinkExitTime());freeTerminal.doSimStep();
            require(f.releases(f.owner)==1,"Bus cleared receiving lane but failed to release");f.releasedLocks();
            require(n.original.getFirstVehicle()==n.blockedHead&&n.arrivals==0,"Forced movement or arrival");
            set(n.terminal,"usedStorageCapacity",oldLoad);f.finish(25510);
            System.out.println("PASS active passage in independent receiving slot: native progress allowed, old FIFO/age preserved, locks held until body clearance");
        }
    }
    public static void main(String[] args) throws Exception {
        realBufferAndTransfers();activePassageInIndependentReceivingSlot();verifiedTransitExit();
        System.out.println("PASS SimZ1TransitPassageNativeCheck (native queue fixtures only)");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
