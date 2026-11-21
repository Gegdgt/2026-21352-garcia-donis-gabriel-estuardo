package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.core.population.routes.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionFixture.*;

/** Native physical/signal inputs; labelled fault inputs only for lost provenance. */
public final class SimZ1RetentionLifecycleCheck {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static void equal(double a,double b,String message){check(Math.abs(a-b)<1e-9,message+": "+a+" vs "+b);}
    static Object field(Object o,String name)throws Exception{return SimZ1RetentionPhaseCheck.field(o,name);}
    static final class Scene {
        final SimZ1RetentionPhases phase=new SimZ1RetentionPhases(0,47);
        final SimZ1RetentionFixture f=new SimZ1RetentionFixture(false,true,phase);
        final CongestionAwareRerouting r=new CongestionAwareRerouting(f.s);
        final SimZ1ActiveRetention state=(SimZ1ActiveRetention)field(r,"retention");
        Event last;int time=79;
        Scene()throws Exception{
            f.events.addHandler(r);f.events.addHandler((BasicEventHandler)e->{if(Zona1NativeDiagnostics.EVENT_TYPE.equals(e.getEventType()))last=e;});
            f.markTraffic(0);phase.attach(f,80);
        }
        void tick(int t)throws Exception{time=t;phase.step(t);check(!f.attempt(f.head,"s","s.lane.0",t),"Receiver-filled fixture moved");}
        void until(int t)throws Exception{for(int i=time+1;i<=t;i++)tick(i);}
        SimZ1ActiveRetention.Wait waitState()throws Exception{return (SimZ1ActiveRetention.Wait)((Map<?,?>)field(state,"waits")).get("road");}
        boolean retained(double t){return r.retained(f.network,new SimZ1RouteSafety(f.s),t).containsKey("road");}
        // Corrupt only provenance/identity of a recorded native event. Fullness
        // in positive tests is always established by real queues, never a mock.
        void fault(Map<String,String> overrides){
            var attrs=new HashMap<>(last.getAttributes());attrs.putAll(overrides);
            r.handleEvent(new Event(last.getTime()) {
                public String getEventType(){return Zona1NativeDiagnostics.EVENT_TYPE;}
                public Map<String,String> getAttributes(){return attrs;}
            });
        }
    }
    static void repeatedAndPause()throws Exception {
        var x=new Scene();x.until(180);check(x.retained(180),"Two permitted intervals qualify");
        equal(x.waitState().accumulatedSeconds(),61,"41+20 confirmed seconds");equal(x.waitState().seconds(),20,"Latest interval keeps C meaning");
        var plan=x.f.driver.getCurrentPlan();var route=x.f.leg.getRoute();
        for(int i=0;i<5;i++){x.tick(180);check(x.retained(180),"Repeated read");}
        equal(x.waitState().accumulatedSeconds(),61,"Repeated timestamps cannot duplicate seconds");
        check(x.f.driver.getCurrentPlan()==plan && x.f.leg.getRoute()==route && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(x.f.driver)==0,"Queries do not clone plan, replace route or consume cursor");
        x.until(239);check(!x.retained(239) && x.state.pending()==1,"Observed red preserves history, never current eligibility");
        equal(x.waitState().accumulatedSeconds(),87,"Red adds zero seconds");equal(x.waitState().last(),206,"Red does not refresh physical confirmation");
        x.phase.step(240);check(!x.retained(240) && x.state.pending()==1,"Green alone cannot reactivate history");
        x.tick(240);check(x.retained(240),"Fresh physical rejection reactivates accumulated history");
        equal(x.waitState().accumulatedSeconds(),87,"First confirmation after red adds zero");equal(x.waitState().seconds(),0,"New interval starts now");
    }
    static void gapsAndUnknown()throws Exception {
        var x=new Scene();x.until(126);x.phase.step(127);x.tick(128);
        check(x.state.pending()==0,"Missing red confirmation breaks the chain");
        x.until(180);equal(x.waitState().accumulatedSeconds(),20,"Lost history is not recovered");check(!x.retained(180),"Unknown gap cannot satisfy threshold");
        x.fault(Map.of("nativeHasGreen","false","signalState","UNKNOWN","reason","signal_native_color_unavailable"));check(x.state.pending()==0,"Unknown signal invalidates rather than pauses");
        x.until(250);x.fault(Map.of("nativeHasGreen","true","reason","stop_wait"));check(x.state.pending()==0,"Ordinary stop is not physical rejection");
        var longRed=new Scene();longRed.until(127);
        // Keep the real native red state; no assumed future phase is supplied.
        for(int t=128;t<=427;t++)check(!longRed.f.attempt(longRed.f.head,"s","s.lane.0",t),"Real red blocks movement");
        check(longRed.state.pending()==0,"Observed pause beyond300s expires history");
        var silence=new Scene();silence.until(180);check(!silence.retained(184)&&silence.state.pending()==0,"No observations: cleanup at evaluation");
    }
    static void releaseAndIdentity()throws Exception {
        var x=new Scene();x.until(127);check(x.state.pending()==1,"History before red");
        x.f.beginReceiverProgress(127);check(!x.retained(127)&&x.state.pending()==0,"Receiver release invalidates even during red");
        x.until(159);check(x.state.pending()==0,"Red with available receiver creates no physical history");
        var changed=new Scene();changed.until(180);check(changed.retained(180),"Route stamp captured");
        var replacement=RouteUtils.createNetworkRoute(path("s","bad","slow","end","s","bad","slow","end"));replacement.setVehicleId(changed.f.head.getId());
        changed.f.leg.setRoute(replacement);WithinDayAgentUtils.resetCaches(changed.f.driver);
        check(!changed.retained(180)&&changed.state.pending()==0,"Changed downstream route, same next movement, invalidates");
        changed.until(260);changed.retained(260);
        replacement.setLinkIds(id("s"),path("bad","slow"),id("end"));WithinDayAgentUtils.resetCaches(changed.f.driver);
        check(!changed.retained(260)&&changed.state.pending()==0,"In-place mutation invalidates occurrence stamp");
        var lane=new Scene();lane.until(180);lane.fault(Map.of("lane","s.lane.1"));
        equal(lane.waitState().accumulatedSeconds(),0,"Changed lane cannot inherit history");check(!lane.retained(180)&&lane.state.pending()==0,"Actual lane has no matching head");
        var identity=new Scene();identity.until(180);identity.state.entered("other",identity.f.person.getId().toString());
        identity.fault(Map.of("vehicle","other"));identity.retained(180);
        check(((Map<?,?>)field(identity.state,"waits")).size()==1,"Unmatched identity removed, actual head unchanged");
    }
    public static void main(String[] args)throws Exception{
        try{repeatedAndPause();gapsAndUnknown();releaseAndIdentity();System.out.println("LIFECYCLE PASS checks="+checks+"; native red/receiver, bounded pauses, no duplicate credit, read-only identity/route checks");}
        finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
