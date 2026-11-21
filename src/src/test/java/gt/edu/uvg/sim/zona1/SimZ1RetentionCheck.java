package gt.edu.uvg.sim.zona1;

import java.lang.reflect.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionFixture;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.lanes.Lane;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1RetentionFixture.*;

/** Component evidence only. No simulation, arrival certificate or acceptance receipt. */
public final class SimZ1RetentionCheck {
    static int checks;
    static void check(boolean v,String text){checks++;if(!v)throw new AssertionError(text);}
    static void equal(double a,double b,String text){check(Math.abs(a-b)<1e-6,text+": "+a+" != "+b);}
    static Object field(Object o,String name)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void field(Object o,String name,Object value)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    static SimZ1TurnRouter router(SimZ1RetentionFixture f){return new SimZ1TurnRouter(f.s.getNetwork(),new SimZ1RouteSafety(f.s),(l,t,p,v)->l.getLength()/l.getFreespeed());}
    static CongestionAwareRerouting.Candidate candidate(SimZ1RetentionFixture f,SimZ1TurnRouter router,double now,double entered){
        return CongestionAwareRerouting.candidate(new SimZ1RouteSafety(f.s),router,f.person,f.leg,0,id("s"),Id.create("s.lane.0",Lane.class),now,f.head.getVehicle(),entered,path("s"));
    }
    static CongestionAwareRerouting attach(SimZ1RetentionFixture f){var r=new CongestionAwareRerouting(f.s);f.events.addHandler(r);return r;}
    static Map<String,SimZ1ActiveRetention.Retained> retained(CongestionAwareRerouting r,SimZ1RetentionFixture f,double now){return r.retained(f.network,new SimZ1RouteSafety(f.s),now);}
    static void expiryAndAlternative()throws Exception {
        var f=new SimZ1RetentionFixture(false);var r=attach(f);var logs=new ArrayList<Event>();
        f.events.addHandler(new BasicEventHandler(){public void handleEvent(Event event){logs.add(event);}});
        f.markTraffic(0); // Partial initial link: no fabricated LinkEnter or duplicate occurrence.
        var previous=Id.createVehicleId("completed");r.handleEvent(new LinkEnterEvent(31449,previous,id("s")));r.handleEvent(new LinkLeaveEvent(31658,previous,id("s")));
        var originalObservation=((Map<?,?>)field(r,"observations")).get(id("s"));
        f.waitUntil(31659,31980);
        equal(r.observedLinkSeconds(id("s"),31920),209,"historical-age arithmetic: fresh completed observation");
        equal(r.observedLinkSeconds(id("s"),31958),209,"TTL inclusive at300");
        check(Double.isNaN(r.observedLinkSeconds(id("s"),31980)),"old sample expired, not renewed by waiting");
        check(((Map<?,?>)field(r,"observations")).get(id("s"))==originalObservation,"no replacement of completed sample");
        var active=retained(r,f,31980);check(active.containsKey("road"),"native retained head survives completed-sample expiry; last="+logs.get(logs.size()-1).getAttributes()+" waits="+field(field(r,"retention"),"waits"));
        equal(active.get("road").evidence().seconds(),316,"confirmed physical wait excludes initial mandatory stop");
        check(!CongestionAwareRerouting.triggered(path("s","bad","slow","end"),0,Set.of(id("s")),false),"old downstream-only filter");
        check(CongestionAwareRerouting.triggered(path("s","bad","slow","end"),0,Set.of(),true),"active current head triggers evaluation");
        check(logs.stream().noneMatch(e->e instanceof LinkLeaveEvent),"no exits during retention");
        check(logs.stream().filter(e->"simz1NativeDecision".equals(e.getEventType()) && "receiver_native_storage".equals(e.getAttributes().get("reason"))).count()==317,"317 real QNode/StopAndYield physical WAIT events");
        check(((Map<?,?>)field(r,"traversed")).get("road").equals(path("s")),"actual event prefix equals candidate prefix");
        var original=f.leg.getRoute();var router=router(f);var prepared=candidate(f,router,31980,Double.NaN);
        check(prepared.issue()==null && prepared.route().equals(path("s","good","end")),"compatible alternative from actual lane");
        check(CongestionAwareRerouting.activeCandidateIssue(f.network,id("s"),Id.create("s.lane.0",Lane.class),id("good"))==null,"native alternative receiver usable");
        check("active_candidate_receiver_native_storage".equals(CongestionAwareRerouting.activeCandidateIssue(f.network,id("s"),Id.create("s.lane.0",Lane.class),id("bad"))),"full receiver remains rejected");
        var old=router.evaluate(path("s","bad","slow","end"),31980,f.person,f.head.getVehicle(),Double.NaN);
        var alternative=router.evaluate(prepared.suffix(),31980,f.person,f.head.getVehicle(),Double.NaN);
        equal(old.seconds(),103.553278,"unknown partial entry retains current estimate and all downstream cost");equal(alternative.seconds(),4.953278,"alternative uses identical entry semantics");
        check(CongestionAwareRerouting.shouldInstall(true,old.cost(),alternative.cost()),"existing strict improvement criterion");
        for(int i=0;i<5;i++){retained(r,f,31980);candidate(f,router,31980,Double.NaN);}
        check(f.leg.getRoute()==original && WithinDayAgentUtils.getCurrentRouteLinkIdIndex(f.driver)==0 && f.driver.chooseNextLinkId().equals(id("bad")),"queries preserve route, cursor, next movement");
        check(f.lane("s","s.lane.0").getFirstVehicle()==f.head,"queries do not move or skip native queue");
        equal(router.evaluate(path("s","good","end"),1,f.person,f.head.getVehicle(),0).seconds(),3.953278,"partial elapsed deducted once");
        equal(router.evaluate(path("s","good","end"),31980,f.person,f.head.getVehicle(),Double.NaN).seconds(),4.953278,"unknown partial entry remains conservative");
        double released=f.clearReceiver(31981);
        check(((SimZ1ActiveRetention)field(r,"retention")).pending()==1,"unqueried evidence remains until native departure event");
        check(f.attempt(f.head,"s","s.lane.0",released+1),"normal native admission after receiver release");
        check(((SimZ1ActiveRetention)field(r,"retention")).pending()==0,"LinkLeave cleans active evidence");
        check(Double.isNaN(r.observedLinkSeconds(id("s"),released+1)),"partial initial link is not a completed full-link sample");
        check(f.driver.getCurrentLinkId().equals(id("bad")),"normal cursor progressed only on native movement");
        check(((Map<?,?>)field(r,"traversed")).get("road").equals(path("s","bad")),"native movement preserves exact occurrence prefix");
        var entry=(CongestionAwareRerouting.Entry)((Map<?,?>)field(r,"entries")).get("road");equal(entry.time(),released+1,"next full link has a real native entry");
        equal(router.evaluate(path("bad","slow","end"),released+2,f.person,f.head.getVehicle(),entry.time()).seconds(),100,"known elapsed current traversal deducted once; downstream slow cost retained");
        double left=f.leaveBadHead(released+2);equal(r.observedLinkSeconds(id("bad"),left),left-entry.time(),"new completed sample only after real native full-link exit");
        System.out.println("AFTER: observation still expired;316s physical receiver WAIT triggers legal candidate; partial-entry remaining103.553278->4.953278; departure cleans evidence; next completed sample uses native entry/exit");
    }
    static void conditions()throws Exception {
        var f=new SimZ1RetentionFixture(false);var r=attach(f);
        f.waitUntil(10,400);check(retained(r,f,400).isEmpty(),"no VehicleEntersTraffic: insertion waiting cannot count");
        f.markTraffic(401);f.green(false);f.waitUntil(401,750);check(retained(r,f,750).isEmpty(),"normal red is not severe retention");
        check("active_candidate_signal_not_green".equals(CongestionAwareRerouting.activeCandidateIssue(f.network,id("s"),Id.create("s.lane.0",Lane.class),id("good"))),"red rejects current-movement alternative");
        f.green(true);f.waitUntil(751,810);check(retained(r,f,810).isEmpty(),"59 seconds below existing threshold");
        f.waitUntil(811,812);check(!retained(r,f,812).isEmpty(),"threshold reached on confirmed physical wait");
        f.green(false);check(retained(r,f,812).isEmpty(),"current red invalidates previously observed storage wait");
        f.green(true);f.waitUntil(813,880);check(!retained(r,f,880).isEmpty(),"new continuous wait can qualify");
        check(retained(r,f,884).isEmpty(),"missing confirmations expire, elapsed time alone is not evidence");
        f.waitUntil(885,950);check(!retained(r,f,950).isEmpty(),"reconfirmed retention");
        var original=f.leg.getRoute();var changed=RouteUtils.createNetworkRoute(path("s","good","end"));changed.setVehicleId(f.head.getId());f.leg.setRoute(changed);WithinDayAgentUtils.resetCaches(f.driver);
        check(retained(r,f,950).isEmpty(),"next movement changed: stale wait invalidated");f.leg.setRoute(original);WithinDayAgentUtils.resetCaches(f.driver);
        f.waitUntil(951,1020);check(!retained(r,f,1020).isEmpty(),"wait for original movement re-established");
        f.events.processEvent(new PersonStuckEvent(1021,f.person.getId(),id("s"),"car"));check(((SimZ1ActiveRetention)field(r,"retention")).pending()==0,"abort event cleans evidence (no queue removal)");
        f.markTraffic(1022);f.waitUntil(1022,1090);f.events.processEvent(new VehicleLeavesTrafficEvent(1091,f.person.getId(),id("s"),f.head.getId(),"car",1));
        check(retained(r,f,1091).isEmpty(),"leaves traffic clears evidence");
        f.person.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);f.markTraffic(1092);f.waitUntil(1092,1450);check(retained(r,f,1450).isEmpty(),"freight service excluded");
        f.person.getAttributes().removeAttribute("simz1FreightService");f.s.getTransitVehicles().addVehicleType(f.head.getVehicle().getType());f.s.getTransitVehicles().addVehicle(f.head.getVehicle());
        f.markTraffic(1451);f.waitUntil(1451,1800);check(retained(r,f,1800).isEmpty(),"registered transit/service stop excluded");
        var restricted=new SimZ1RetentionFixture(true);var router=router(restricted);var prepared=candidate(restricted,router,400,0);
        check(prepared.issue()==null && prepared.route().equals(path("s","bad","slow","end")),"cannot use alternate lane; no alternative fabricated");
        check(!CongestionAwareRerouting.shouldInstall(true,100.6,router.evaluate(prepared.suffix(),400,restricted.person,restricted.head.getVehicle(),0).cost()),"same route has no improvement");
        var safety=new SimZ1RouteSafety(restricted.s);
        check(safety.validateReplacement(path("s","bad","slow","end"),path("s","good","end"),0,id("s"),id("end"),Id.create("s.lane.0",Lane.class))!=null,"actual incompatible lane rejected");
        check(!CongestionAwareRerouting.triggered(path("s","bad","slow","end"),0,Set.of(),false),"no retention or downstream severity: no new evaluation");
        check(CongestionAwareRerouting.triggered(path("s","bad","slow","end"),0,Set.of(id("slow")),false),"ordinary downstream trigger retained");
    }
    static void nativeStorageBranch()throws Exception {
        // Actual MATSim default acceptance, followed by QNode's real full-receiver rejection.
        var f=new SimZ1RetentionFixture(false,false);var r=attach(f);f.markTraffic(0);f.waitUntil(10,400);
        var active=retained(r,f,400);check(active.containsKey("road"),"paired turn_go/storage_wait also qualifies");
        equal(active.get("road").evidence().seconds(),390,"local GO does not reset receiver WAIT each step");
        check(Double.isNaN(r.observedLinkSeconds(id("s"),400)),"partial initial link/wait is never a completed observation");
        f.beginReceiverProgress(401);check(retained(r,f,401).isEmpty(),"native receiver capacity change invalidates fresh evidence");
    }
    @SuppressWarnings("unchecked") static void scheduling()throws Exception {
        var f=new SimZ1RetentionFixture(false);var r=attach(f);var config=new Zona1RoutingConfigGroup();
        check(config.getMaxReroutesPerStep()==100 && config.getAgentShare()==.5,"defaults budget100,cohort50%");
        check(r.evaluationDue(0) && !r.evaluationDue(59) && r.evaluationDue(60) && !r.evaluationDue(60),"60-second evaluation cadence");
        var ids=List.of("a","b","c","d");var cohort=CongestionAwareRerouting.selectCohort(ids,.5,20261023);
        check(cohort.size()==2 && cohort.equals(CongestionAwareRerouting.selectCohort(ids,.5,20261023)),"fixed deterministic cohort");
        field(r,"selected",Set.of(f.person.getId()));check(r.eligible(f.driver,0),"eligible cohort driver");
        ((Map<Id<org.matsim.api.core.v01.population.Person>,Double>)field(r,"last")).put(f.person.getId(),0.);
        check(!r.eligible(f.driver,299) && r.eligible(f.driver,300),"300-second cooldown");
        field(r,"selected",Set.of());check(!r.eligible(f.driver,1000),"non-cohort cannot reroute even if retained");
        field(r,"selected",Set.of(f.person.getId()));f.person.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);check(!r.eligible(f.driver,1000),"freight cannot reroute");
        f.person.getAttributes().removeAttribute("simz1FreightService");f.s.getTransitVehicles().addVehicleType(f.head.getVehicle().getType());f.s.getTransitVehicles().addVehicle(f.head.getVehicle());check(!r.eligible(f.driver,1000),"transit cannot reroute");
        // Scheduling identities only; no population or simulated vehicles are generated.
        var agents=new ArrayList<MobsimAgent>();for(int i=0;i<105;i++) {
            var id=Id.createPersonId(String.format("candidate-%03d",i));agents.add((MobsimAgent)Proxy.newProxyInstance(MobsimAgent.class.getClassLoader(),new Class<?>[]{MobsimAgent.class},(o,m,a)->{if(m.getName().equals("getId"))return id;throw new AssertionError(m);}));
        }
        field(r,"budget",100);var first=r.chooseAttempts(agents);check(first.size()==100,"per-evaluation budget limits candidates");
        field(r,"cursor",first.get(99).getId().toString());var second=r.chooseAttempts(agents);check(second.size()==100 && second.get(0).getId().equals(agents.get(100).getId()),"budget renews and cyclic fairness retained");
        check(r.chooseAttempts(new ArrayList<>()).isEmpty(),"empty cohort does not spend budget");
    }
    public static void main(String[] args)throws Exception {
        try{expiryAndAlternative();conditions();nativeStorageBranch();scheduling();System.out.println("C529-C PASS "+checks+" checks; controlled native queues; no simulation/arrival certificate");}
        finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
