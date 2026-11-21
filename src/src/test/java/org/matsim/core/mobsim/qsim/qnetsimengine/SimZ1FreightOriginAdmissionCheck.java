package org.matsim.core.mobsim.qsim.qnetsimengine;

import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OriginAdmissionFixture.*;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OriginPolicyCheck.*;
import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.population.routes.RouteUtils;

/** Native waiting-list regression for the Run55K freight admission defect.
 * Synthetic Small geometry isolates authorization from physical admission.
 * The real schedule/window are preserved; this is not a replay of city traffic.
 * Historical v1 grants +3600 for completion only. Authorized v2 grants entry
 * through that same deadline inclusively, without extending final completion.
 * No Controller, QSim, historical output writes, removals or forced movements.
 */
public final class SimZ1FreightOriginAdmissionCheck {
    static final double PLANNED=50620.17320287385, OPEN=32400, CLOSE=57600;
    static final String POLICY="freight-close-plus3600-v1";
    static final String TOLERATED_ENTRY_POLICY="freight-entry-and-completion-close-plus3600-v2";
    static final List<Map<String,Object>> RESULTS=new ArrayList<>();

    static QVehicleImpl freight(Small f,String name,String freightPolicy) {
        var v=f.actor(name,8,3.5,false,false,"origin","tail");
        var population=f.scenario.getPopulation();
        var person=population.getFactory().createPerson(Id.createPersonId(name));
        person.getAttributes().putAttribute("simz1FreightService","simz1-freight-weekday-v1");
        person.getAttributes().putAttribute("simz1FreightCompletionPolicy",freightPolicy);
        person.getAttributes().putAttribute("simz1FreightDeparture",Double.toString(PLANNED));
        person.getAttributes().putAttribute("simz1FreightAssignedWindow","[32400,57600]");
        person.getAttributes().putAttribute("simz1FreightResidencePolicy","weekday_overnight_until_05_v2");
        person.getAttributes().putAttribute("simz1FreightRoute","origin tail");
        population.addPerson(person);
        var leg=population.getFactory().createLeg("car");
        leg.setRoute(RouteUtils.createNetworkRoute(List.of(id("origin"),id("tail")),f.scenario.getNetwork()));
        v.setDriver((MobsimDriverAgent)Proxy.newProxyInstance(PlanAgent.class.getClassLoader(),
            new Class<?>[]{MobsimDriverAgent.class,PlanAgent.class,HasPerson.class},(p,m,a)->switch(m.getName()) {
                case "getId"->person.getId(); case "getPerson"->person;
                case "getMode"->"car"; case "getCurrentPlanElement"->leg;
                case "getCurrentLinkId"->id("origin"); case "chooseNextLinkId"->id("tail");
                case "isWantingToArriveOnCurrentLink"->false;
                default->throw new AssertionError("Unexpected native freight actor call: "+m);
            }));
        return v;
    }

    static long entries(Small f,QVehicle v) {
        return f.events.stream().filter(e->e instanceof VehicleEntersTrafficEvent &&
            v.getId().toString().equals(e.getAttributes().get("vehicle"))).count();
    }
    static void unadmitted(Small f,QVehicle v) throws Exception {
        check(entries(f,v)==0,"Unauthorized traffic entry: "+v.getId());
        check(f.reservation(v)==null,"Unauthorized body reservation: "+v.getId());
        noStaging(f.ledger,v);
        check(f.link.getWaitingList().contains(v),"Waiting freight silently removed");
        check(f.events.stream().noneMatch(e->e instanceof PersonArrivalEvent ||
            e instanceof VehicleLeavesTrafficEvent || e instanceof PersonStuckEvent),
            "Manufactured arrival, traffic exit or stuck removal");
    }
    static void boundary(String policy,String freightPolicy,double time,boolean allowed) throws Exception {
        try(var f=new Small(policy,20,true)) {
            // Run55K preserved its synchronous ENTER/progress at 86309, but
            // the failing VehicleEntersTraffic event was not serialized. This
            // reconstructs that admission attempt, not the historical traffic.
            var v=freight(f,time==86309?"freight_000392":"freight-boundary",freightPolicy); f.timer.setTime(time);
            boolean moved=f.admit(v);
            check(moved==allowed,"Admission at "+time+" under "+policy+": expected "+allowed+", got "+moved);
            if(allowed) {
                check(entries(f,v)==1&&f.reservation(v)!=null,"Authorized freight did not commit exactly once");
                near((double)field(f.reservation(v),"footprint"),8.1,"Freight body/gap changed");
                check(!f.link.getWaitingList().contains(v),"Admitted freight remains in origin queue");
                check(!f.attempt()&&entries(f,v)==1,"Repeated native attempt duplicated entry");
            } else {
                unadmitted(f,v);var before=movementState(f);
                for(int i=0;i<3;i++)check(!f.attempt(),"Repeated denied request became admission");
                unadmitted(f,v);check(before.equals(movementState(f)),"Denied retries changed movement, ownership or flow");
            }
        }
    }
    static void blockedUntilExpiry(String policy,String freightPolicy) throws Exception {
        try(var f=new Small(policy,20,true)) {
            double deadline=freightPolicy.equals(POLICY)?CLOSE:CLOSE+3600;
            f.timer.setTime(deadline-1);
            var owner0=f.moto("owner-0","tail");var owner1=f.moto("owner-1","tail");
            check(f.admit(owner0)&&f.admit(owner1),"Could not create two native blocking bodies");
            var v=freight(f,"freight-expiring",freightPolicy);var follower=f.moto("follower","tail");
            f.link.getWaitingList().add(v);f.link.getWaitingList().add(follower);
            check(!f.attempt(),"Freight overlaps occupied origin anchor before expiry");
            unadmitted(f,v);var before=movementState(f);
            for(double time:new double[]{deadline,deadline+0.001,deadline+1,CLOSE+14400,86309}) {
                f.timer.setTime(time);check(!f.attempt(),"Expired queue head admitted at "+time);
                unadmitted(f,v);check(entries(f,follower)==0&&f.reservation(follower)==null,"Follower bypassed expired head");
                check(f.link.getWaitingList().stream().map(x->x.getId().toString()).toList()
                    .equals(List.of("freight-expiring","follower")),"Shared origin FIFO changed");
                check(before.equals(movementState(f)),"Expiry moved owners, released reservations or changed flow");
            }
        }
    }
    static void nonFreightUnaffected(String policy) throws Exception {
        try(var f=new Small(policy,20,true)) {
            f.timer.setTime(86309);var v=f.moto("ordinary-after-close","tail");
            check(f.admit(v)&&entries(f,v)==1,"Freight authorization restricted an ordinary actor");
        }
    }
    static QVehicleImpl follower(Small f,String family) {
        return switch(family) {
            case "carro"->f.actor("follower-carro",4.5,1,false,false,"origin","tail");
            case "moto"->f.moto("follower-moto","tail");
            case "bus"->f.actor("follower-bus",13.5,3,true,false,"origin","tail");
            case "camion"->{
                var v=freight(f,"follower-camion",TOLERATED_ENTRY_POLICY);
                var p=f.scenario.getPopulation().getPersons().get(Id.createPersonId("follower-camion"));
                // A separately scheduled night-window actor remains authorized
                // while the original afternoon head has permanently expired.
                p.getAttributes().putAttribute("simz1FreightDeparture","75600");
                p.getAttributes().putAttribute("simz1FreightAssignedWindow","[75600,104400]");
                yield v;
            }
            default->throw new AssertionError("Unknown follower family: "+family);
        };
    }
    static void queryWithoutMovement(Small f,QVehicle v,String policy,String family) throws Exception {
        var before=f.stableState()+vehicleState(v);var offer=f.offer(v);
        check(before.equals(f.stableState()+vehicleState(v)),"Physical offer mutated movement or events: "+family);
        if(GAP.equals(policy)&&!family.equals("bus"))
            check(offer.applicable()&&offer.feasible(),"Empty origin has no compatible accessible gap: "+family);
        check(entries(f,v)==0&&f.reservation(v)==null,"A physical offer became an admission: "+family);
        noStaging(f.ledger,v);
    }
    static void expiredHeadAloneBlocksFollower(String policy,String family) throws Exception {
        // Positive control uses a separate native origin, never removal of the
        // expired head. This rules out body size, route, flow debt and the
        // follower's own authorization as causes of the retained request.
        try(var control=new Small(policy,20,true)) {
            control.timer.setTime(75601);var v=follower(control,family);
            queryWithoutMovement(control,v,policy,family);
            check(control.admit(v)&&entries(control,v)==1&&control.reservation(v)!=null,
                "Independent authorized follower could not enter: "+family);
            near((double)field(control.reservation(v),"footprint"),v.getVehicle().getType().getLength()+.1,
                "Positive-control body or separation changed");
            check(control.link.getWaitingList().isEmpty(),"Admitted control remains in FIFO");
        }
        try(var f=new Small(policy,20,true)) {
            f.timer.setTime(75601);var head=freight(f,"expired-head",TOLERATED_ENTRY_POLICY);
            var next=follower(f,family);queryWithoutMovement(f,head,policy,"camion");queryWithoutMovement(f,next,policy,family);
            f.link.getWaitingList().add(head);f.link.getWaitingList().add(next);
            var before=movementState(f);
            for(double now:new double[]{75601,75602,86399,86400}) {
                f.timer.setTime(now);check(!f.attempt(),"Expired FIFO head allowed a movement: "+family);
                unadmitted(f,head);unadmitted(f,next);
                check(before.equals(movementState(f)),"Expiry altered FIFO, bodies or native flow: "+family);
                check(f.link.getWaitingList().stream().map(v->v.getId().toString()).toList()
                    .equals(List.of("expired-head","follower-"+family)),"Follower skipped the expired head: "+family);
            }
            var denials=f.events.stream().filter(e->e.getEventType().equals("simz1FreightAdmissionRejected")).toList();
            check(denials.size()==1,"Expired head rejection missing or repeated: "+family);
            var denial=denials.get(0);var a=denial.getAttributes();
            check(denial.getTime()==75601&&"expired-head".equals(a.get("vehicle"))
                &&"assigned_entry_deadline_expired".equals(a.get("reason"))
                &&"61200.0".equals(a.get("latestEntryTime"))&&"true".equals(a.get("latestEntryInclusive"))
                &&"61200.0".equals(a.get("completionDeadline")),"Wrong expiry identity or original deadline");
            check(f.events.stream().noneMatch(e->e.getEventType().equals("simz1OccupancyReservation")),
                "Expired head or follower acquired a body reservation");
            // No cleanup is invoked in Small: it has no lifecycle counter.
            // Normal cleanup and its terminal evidence are covered separately
            // by SimZ1FreightAdmissionQSimCheck, not manufactured here.
        }
    }
    static void runCase(String name,Checked action) {
        var r=new LinkedHashMap<String,Object>();r.put("case",name);
        try{action.run();r.put("status","PASS");System.out.println("PASS "+name);}
        catch(Throwable failure){var actual=cause(failure);r.put("status","FAIL");r.put("error",actual.toString());System.out.println("FAIL "+name+" "+actual);}
        RESULTS.add(r);
    }
    public static void main(String[] args) throws Exception {
        try {
            check(args.length==1,"Usage: <new-report-json>");var out=Path.of(args[0]);
            check(!Files.exists(out),"Preserve existing native regression evidence");RESULTS.clear();
            for(String policy:List.of(LEGACY,GAP)) {
                for(String freightPolicy:List.of(POLICY,TOLERATED_ENTRY_POLICY)) {
                    String label=policy+" "+freightPolicy;
                    for(double time:new double[]{Math.ceil(PLANNED),CLOSE-1})
                        runCase(label+" nominal "+time,()->boundary(policy,freightPolicy,time,true));
                    for(double time:new double[]{CLOSE,CLOSE+1800,CLOSE+3600})
                        runCase(label+" completion-tolerance interval "+time,
                            ()->boundary(policy,freightPolicy,time,freightPolicy.equals(TOLERATED_ENTRY_POLICY)));
                    for(double time:new double[]{CLOSE+3600.001,CLOSE+3601,CLOSE+14400,86309})
                        runCase(label+(time==86309?" reconstructed freight_000392 ":" expired ")+time,()->boundary(policy,freightPolicy,time,false));
                    runCase(label+" physically blocked until expiry preserves FIFO",()->blockedUntilExpiry(policy,freightPolicy));
                }
                runCase(policy+" ordinary actor unaffected",()->nonFreightUnaffected(policy));
                for(String family:List.of("carro","moto","bus","camion"))
                    runCase(policy+" expired head alone retains "+family+" with independent admissible control",
                        ()->expiredHeadAloneBlocksFollower(policy,family));
            }
            long failures=RESULTS.stream().filter(r->r.get("status").equals("FAIL")).count();
            var report=new LinkedHashMap<String,Object>();report.put("kind","freight_origin_authorization_native_component_regression");
            report.put("status",failures==0?"PASS":"FAIL");report.put("cases",RESULTS);
            report.put("real_schedule_seconds",PLANNED);report.put("assigned_window_seconds",List.of(OPEN,CLOSE));
            report.put("entry_contracts",Map.of(POLICY,"original_assigned_nominal_window_only",TOLERATED_ENTRY_POLICY,"original_window_close_plus3600_inclusive"));
            report.put("completion_tolerance_seconds",3600);report.put("final_deadline_unchanged",true);
            report.put("fixture_geometry","synthetic Small fixture; not historical city traffic replay");
            report.put("expired_head_followers",List.of("carro","moto","bus","camion"));
            report.put("expired_head_followers_control","empty native origin, authorized follower in a separate fixture; head never removed");
            report.put("expired_head_retention_checked_through_seconds",86400);
            report.put("cleanup_scope","not invoked by this component fixture; separate SimZ1FreightAdmissionQSimCheck covers normal native cleanup");
            report.put("qsim_executed",false);report.put("massive_approval",false);
            Files.createDirectories(out.toAbsolutePath().getParent());new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.toFile(),report);
            check(failures==0,"Freight origin regression failures="+failures);
            System.out.println("PASS SimZ1FreightOriginAdmissionCheck "+RESULTS.size()+" cases");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
