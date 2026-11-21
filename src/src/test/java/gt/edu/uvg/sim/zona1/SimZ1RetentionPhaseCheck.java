package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;

/** Same native reproduction compiled before and after D. CSV is component evidence, not a run. */
public final class SimZ1RetentionPhaseCheck {
    static Object field(Object o,String name)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void check(boolean b,String text){if(!b)throw new AssertionError(text);}
    static void cycle(Path out,int onset,int dropping,boolean after)throws Exception {
        var phase=new SimZ1RetentionPhases(onset,dropping);var f=new SimZ1RetentionFixture(false,true,phase);
        var r=new CongestionAwareRerouting(f.s);f.events.addHandler(r);var safety=new SimZ1RouteSafety(f.s);
        var completed=Id.createVehicleId("previous");r.handleEvent(new LinkEnterEvent(-600,completed,Id.createLinkId("s")));r.handleEvent(new LinkLeaveEvent(-391,completed,Id.createLinkId("s")));
        f.markTraffic(0);phase.attach(f,80);
        Map<String,String>[] last=new Map[]{Map.of()};f.events.addHandler((BasicEventHandler)e->{if(Zona1NativeDiagnostics.EVENT_TYPE.equals(e.getEventType()))last[0]=e.getAttributes();});
        var rows=new ArrayList<String>();rows.add("time,color,native_permission,reason,physical_confirmed_total,stored_continuous_seconds,stored_accumulated_seconds,continuous_interval_reset,history_lost,evaluation,retained");
        boolean previousPhysical=false;double total=0,max=0,previousAccumulated=0;int resets=0,losses=0,eligible=0,redEligible=0;double previousSince=Double.NaN;
        for(int t=80;t<880;t++) {
            phase.step(t);check(!f.attempt(f.head,"s","s.lane.0",t),"Full native receiver unexpectedly moved head");
            var event=last[0];boolean green=((SignalizeableItem)f.lane("s","s.lane.0")).hasGreenForToLink(Id.createLinkId("bad"));
            check(green==(t%80>=onset && t%80<dropping),"Native amber/green duration differs from source interval at "+t);
            boolean physical=green && "receiver_native_storage".equals(event.get("reason"));
            if(physical && previousPhysical)total++;previousPhysical=physical;
            var waits=(Map<?,?>)field(field(r,"retention"),"waits");var state=waits.get("road");double seconds=0,accumulated=0;boolean reset=false;
            if(state!=null) {
                var value=(SimZ1ActiveRetention.Wait)state;seconds=value.seconds();max=Math.max(max,seconds);
                reset=Double.isFinite(previousSince)&&value.since()!=previousSince;previousSince=value.since();
                try{var method=state.getClass().getDeclaredMethod("accumulatedSeconds");method.setAccessible(true);accumulated=(double)method.invoke(state);}catch(NoSuchMethodException old){accumulated=seconds;}
            }else if(Double.isFinite(previousSince)){reset=true;previousSince=Double.NaN;}
            if(reset)resets++;
            boolean lost=accumulated<previousAccumulated;if(lost)losses++;previousAccumulated=accumulated;
            boolean evaluation=t%60==0,retained=false;
            if(evaluation){retained=!r.retained(f.network,safety,t).isEmpty();if(retained)eligible++;if(retained&&!green)redEligible++;}
            check(Double.isNaN(r.observedLinkSeconds(Id.createLinkId("s"),t)),"Completed sample rejuvenated");
            if(after && physical)check(Math.abs(accumulated-total)<1e-9,"Physical accumulation differs at "+t+": "+accumulated+" vs "+total);
            rows.add(t+","+phase.group.getState()+","+green+","+event.get("reason")+","+total+","+seconds+","+accumulated+","+reset+","+lost+","+evaluation+","+retained);
        }
        Files.write(out.resolve("phase-"+onset+"-"+dropping+".csv"),rows);
        check(total>60 && max==dropping-onset-1,"Native counterexample not established");
        check(redEligible==0 && (after?eligible>0:eligible==0),"Unexpected eligibility: "+eligible+" red="+redEligible);
        check(losses==(after?0:10),"Unexpected historical evidence losses: "+losses);
        System.out.println((after?"AFTER":"BEFORE")+" cycle=80 permitted="+(dropping-onset)+" maxContinuous="+max+" confirmedTotal="+total+" intervalResets="+resets+" historyLosses="+losses+" eligible60s="+eligible+" redEligible="+redEligible);
    }
    public static void main(String[] args)throws Exception{try{var out=Path.of(args[0]);boolean after=args[1].equals("after");cycle(out,0,47,after);cycle(out,49,78,after);}finally{org.apache.logging.log4j.LogManager.shutdown();}}
}
