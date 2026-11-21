package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Method;
import java.util.*;
import org.apache.commons.lang3.tuple.Pair;
import org.matsim.api.core.v01.Id;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Focal native queue checks, not a Controller or historical replay. At most
 * three actors per isolated fixture. The existing five-actor Controller check
 * owns end-to-end arrivals; this matrix covers selection guards and flow debt. */
public final class SimZ1OriginalTravelSlotCheck {
    private static final Method SELECT;
    static {
        try {SELECT=QueueWithBuffer.class.getDeclaredMethod("peekFromVehQueue");SELECT.setAccessible(true);}
        catch(ReflectiveOperationException e){throw new ExceptionInInitializerError(e);}
    }
    private static QVehicle selected(QueueWithBuffer q,QVehicle first)throws Exception{
        var iterator=((Iterable<?>)field(q,"vehQueue")).iterator();
        require(iterator.hasNext()&&iterator.next()==first,"Fixture did not identify the actual first travelling actor");
        return (QVehicle)SELECT.invoke(q);
    }
    private static List<String> travelling(QueueWithBuffer q)throws Exception{
        var result=new ArrayList<String>();for(Object item:(Iterable<?>)field(q,"vehQueue"))result.add(((QVehicle)item).getId().toString());return result;
    }
    private static List<String> buffered(QueueWithBuffer q)throws Exception{
        var result=new ArrayList<String>();for(Object item:(Iterable<?>)field(q,"buffer"))result.add(((QVehicle)((Pair<?,?>)item).getKey()).getId().toString());return result;
    }
    private static double credit(QueueWithBuffer q)throws Exception{return (double)field(field(q,"flowcap_accumulate"),"value");}
    private static String snapshot(SimZ1StorageFixture f,QueueWithBuffer q)throws Exception {
        return travelling(q)+"|"+buffered(q)+"|"+credit(q)+"|"+field(field(q,"flowcap_accumulate"),"timeStep")
            +"|"+q.getLoadIndicator()+"|"+q.getLastMovementTimeOfFirstVehicle()+"|"+f.events.size()
            +"|"+SimZ1OpposedReturnRerouteCheck.snapshot(f.ledger);
    }
    private static void pureChoice(SimZ1StorageFixture f,QueueWithBuffer q,QVehicle first,QVehicle expected,String reason)throws Exception {
        String before=snapshot(f,q);for(int i=0;i<20;i++)require(selected(q,first)==expected,reason);
        require(before.equals(snapshot(f,q)),"Read-only selection mutated queue, credit, age, events or reservations: "+reason);
    }
    private static Map<String,Object> run(boolean fast,double step,double body)throws Exception {
        try(var f=new SimZ1StorageFixture(PROFILES.get(1),true,true,step,true)){
            var config=f.scenario.getConfig().qsim();config.setUsingFastCapacityUpdate(fast);config.setPcuThresholdForFlowCapacityEasing(0);
            var q=f.queue("receipt-a",".original");
            // This synthetic queue's explicit .05 PCU/s creates real native
            // debt when its first one-PCU car enters the buffer. No credit,
            // reservation, position, vehicle PCU or travel clock is injected.
            q.changeUnscaledFlowCapacityPerSecond(.05);
            var head=f.actor("head-slot0",4.5,"receipt-a","dest-a");
            var following=f.actor("traveller-slot0",4.5,"receipt-a","dest-a");
            var independent=f.actor("independent-slot1",body,"receipt-a","dest-a1");
            f.seed(head,".original",0);
            double lastNativeTime=0;int tick=0;
            while(buffered(q).isEmpty()&&tick<100){lastNativeTime=++tick*step;f.ready(q,lastNativeTime);}
            require(buffered(q).equals(List.of(head.vehicle.getId().toString())),"Initial native head did not reach its buffer");
            require(credit(q)<0,"Native head failed to establish negative flow credit");
            double retainedAge=q.getLastMovementTimeOfFirstVehicle();int headSlot=f.slot(head);
            f.seed(following,".original",lastNativeTime);
            f.timer.setTime(following.vehicle.getEarliestLinkExitTime()+step);
            pureChoice(f,q,following.vehicle,following.vehicle,"Same-slot follower must keep its predecessor");
            f.seed(independent,".original",f.timer.getTimeOfDay());
            require(f.slot(following)==0&&f.slot(independent)==1&&headSlot==0,"Routes did not commit distinct physical slots");
            pureChoice(f,q,following.vehicle,following.vehicle,"Candidate cannot bypass its native earliest exit");
            f.timer.setTime(independent.vehicle.getEarliestLinkExitTime()+step);
            pureChoice(f,q,following.vehicle,independent.vehicle,"Eligible independent travelling head is hidden");

            SimZ1CorridorOccupancy.uninstall(config);
            try {pureChoice(f,q,following.vehicle,following.vehicle,"No ledger must preserve native FIFO");}
            finally {SimZ1CorridorOccupancy.install(config,f.ledger);}

            // Pure guard inputs only: restore immediately, execute no movement
            // while effective lane count or ownership is intentionally unknown.
            double lanes=(double)field(q,"effectiveNumberOfLanesUsedInQsim");set(q,"effectiveNumberOfLanesUsedInQsim",1.);
            try {pureChoice(f,q,following.vehicle,following.vehicle,"Single physical original lane cannot overtake");}
            finally {set(q,"effectiveNumberOfLanesUsedInQsim",lanes);}
            Object reservation=f.reservation(head);String nativeQueue=(String)field(reservation,"nativeQueue");set(reservation,"nativeQueue","unobserved-ownership");
            try {pureChoice(f,q,following.vehicle,following.vehicle,"Unknown buffered ownership must remain a barrier");}
            finally {set(reservation,"nativeQueue",nativeQueue);}
            reservation=f.reservation(following);nativeQueue=(String)field(reservation,"nativeQueue");set(reservation,"nativeQueue","unobserved-ownership");
            try {pureChoice(f,q,following.vehicle,following.vehicle,"Unknown first travelling ownership must remain a barrier");}
            finally {set(reservation,"nativeQueue",nativeQueue);}
            require(credit(q)<0,"Read-only selection erased preexisting flow debt");

            double start=f.timer.getTimeOfDay(),rate=(double)field(q,"flowCapacityPerTimeStep");int blockedSteps=0;
            for(int i=0;i<Math.ceil(100/step)&&!buffered(q).contains(independent.vehicle.getId().toString());i++){
                double now=start+i*step,before=credit(q),elapsed=now-lastNativeTime;
                f.ready(q,now);double after=credit(q);
                require(after<=before+elapsed/step*rate+1e-8,"Flow credit grew faster than the native rate or debt was erased");
                if(before+elapsed/step*rate<-1e-8){
                    require(!buffered(q).contains(independent.vehicle.getId().toString()),"Independent actor moved while its native flow debt remained negative");blockedSteps++;
                }
                lastNativeTime=now;
            }
            require(blockedSteps>0,"Fixture did not test a live negative-debt wait");
            require(buffered(q).equals(List.of(head.vehicle.getId().toString(),independent.vehicle.getId().toString())),"Independent slot failed to reach native buffer, or same-slot FIFO changed");
            require(travelling(q).equals(List.of(following.vehicle.getId().toString())),"Same-slot travelling follower moved past its retained predecessor");
            near(q.getLastMovementTimeOfFirstVehicle(),retainedAge,"Independent selection reset retained buffer head age");
            require(f.slot(head)==headSlot&&f.slot(following)==0&&f.slot(independent)==1,"Selection changed physical reservations");
            require(credit(q)<=rate-independent.vehicle.getSizeInEquivalents()+1e-8,"Independent actor did not pay native PCU flow consumption");
            f.safety();require(f.moves==0,"Component matrix invented node movement or arrival");
            return Map.of("fast",fast,"step",step,"independent_body_m",body,"independent_pcu",independent.vehicle.getSizeInEquivalents(),"negative_debt_wait_steps",blockedSteps,"native_buffer_time",lastNativeTime,"final_credit_pcu",credit(q),"native_node_moves",f.moves);
        }
    }
    public static void main(String[] args)throws Exception {
        try {
            var results=new ArrayList<Map<String,Object>>();for(boolean fast:List.of(false,true))for(double step:new double[]{1,.1})for(double body:new double[]{4.5,8,13.5})results.add(run(fast,step,body));
            System.out.println("PASS 12 native component cases; at most three actors each; fast/slow, 1/.1 step, car/truck/bus, unchanged PCU debt, same-slot/single-lane/no-ledger/unknown-ownership negatives: "+new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(results));
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
