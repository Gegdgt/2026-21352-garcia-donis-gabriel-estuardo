package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;

/** Explicit synthetic native-event-manager audit fixtures, no fabricated run. */
public final class SimZ1FreightCompletionCheck {
    static void check(boolean v,String why){if(!v)throw new AssertionError(why);}
    static Event event(String kind,double t,String... pairs) {
        return new Event(t) {
            @Override public String getEventType(){return kind;}
            @Override public Map<String,String> getAttributes(){
                var a=super.getAttributes();for(int i=0;i<pairs.length;i+=2)a.put(pairs[i],pairs[i+1]);return a;
            }
        };
    }
    static org.matsim.api.core.v01.Scenario scenario(double departure,String policy) {
        var s=SimZ1FreightClosureCheck.scenario(departure,SimZ1Freight.OVERNIGHT_POLICY);
        var p=s.getPopulation().getPersons().get(Id.createPersonId("h"));var a=p.getAttributes();
        a.putAttribute(SimZ1FreightCompletion.ATTRIBUTE,policy);
        var w=SimZ1FreightCompletion.assigned(departure);
        a.putAttribute("simz1FreightAssignedWindow","["+w.start()+","+w.close()+"]");
        a.putAttribute(SimZ1FreightCompletion.GEOMETRY,"{\"minimum_gap_m\":0.1,\"body_length_m\":8,\"entry_distance_from_route_start_m\":2,\"exit_distance_from_route_start_m\":20,\"route_link_start_m\":{\"a\":0,\"b\":10,\"c\":20}}");
        return s;
    }
    static SimZ1Freight handler(double departure) {return handler(departure,SimZ1FreightCompletion.POLICY);}
    static SimZ1Freight handler(double departure,String policy) {return new SimZ1Freight(scenario(departure,policy));}
    static void start(SimZ1Freight h,double departure,double entry) {
        for(int i=0;i<3;i++)h.handleEvent(event("simz1OccupancyDomain",0,"link",""+(char)('a'+i),"corridor","C","linkOffsetMeters",""+(i*10),"linkLengthMeters","10"));
        SimZ1FreightClosureCheck.send(h,"departure",departure,"a");
        h.handleEvent(event("simz1OccupancyReservation",entry,"vehicle","h","link","a","corridor","C","action","ENTER","bodyLengthMeters","8","footprintMeters","8.1","reservationOrdinal","1"));
        progress(h,entry,"a",0);
        SimZ1FreightClosureCheck.send(h,"vehicle enters traffic",entry,"a");
    }
    static void progress(SimZ1Freight h,double t,String link,double front) {
        h.handleEvent(event("simz1OccupancyProgress",t,"vehicle","h","link",link,"corridor","C","modeledFrontLowerBoundMeters",""+front));
    }
    static void finish(SimZ1Freight h,double time,boolean clear) {
        SimZ1FreightClosureCheck.send(h,"entered link",time-2,"b");
        SimZ1FreightClosureCheck.send(h,"entered link",time-1,"c");
        progress(h,time,"c",clear?30:28);
        SimZ1FreightClosureCheck.send(h,"vehicle leaves traffic",time,"c");
        SimZ1FreightClosureCheck.send(h,"arrival",time,"c");
        h.handleEvent(event("simz1OccupancyReservation",time,"vehicle","h","action","EXIT"));
    }
    static void rejectedWith(Runnable action,String message) {
        try {action.run();throw new AssertionError("Expected rejection: "+message);}
        catch(IllegalStateException expected) {check(expected.getMessage().contains(message),"Wrong rejection: "+expected);}
    }
    static void entryAndLifecycle() {
        // The versioned +3600 indicator applies to completion, never to entry.
        // Independent fixture clocks cover both sides of the half-open close.
        for(double entry:new double[]{17999,18000,19800,21600,21600.001,33000}) {
            var h=handler(100);
            if(entry<18000) {start(h,100,entry);finish(h,18010,true);h.requireApproved();}
            else rejectedWith(()->start(h,100,entry),"entry outside assigned nominal window");
        }
        var waiting=handler(100);
        SimZ1FreightClosureCheck.send(waiting,"departure",100,"a");
        SimZ1FreightClosureCheck.send(waiting,"stuckAndAbort",86400,"a");
        check(waiting.activeCount()==0&&waiting.violations().isEmpty(),"Origin wait became road residence");
        rejectedWith(waiting::requireApproved,"FREIGHT_NOT_APPROVED");
        var duplicate=handler(100);start(duplicate,100,100);
        rejectedWith(()->SimZ1FreightClosureCheck.send(duplicate,"vehicle enters traffic",100,"a"),"identity mismatch");
        var late=handler(100);start(late,100,101);
        rejectedWith(()->SimZ1FreightClosureCheck.send(late,"vehicle enters traffic",100,"a"),"non-monotone event time");
        var lateDeparture=handler(100);
        rejectedWith(()->SimZ1FreightClosureCheck.send(lateDeparture,"departure",102,"a"),"duplicate/late/incorrect departure");
    }
    static Event denial(org.matsim.api.core.v01.population.Person person,double time,String... mutate) {
        var authorization=SimZ1Freight.originEntry(person,time);
        var a=new LinkedHashMap<String,String>();
        a.put("person",person.getId().toString());a.put("vehicle",person.getId().toString());a.put("link","a");
        a.put("reason",authorization.reason());a.put("completionPolicy",authorization.completionPolicy());a.put("entryPolicy",authorization.entryPolicy());
        a.put("scheduledDeparture",Double.toString(authorization.plannedDeparture()));
        a.put("assignedWindowStart",Double.toString(authorization.windowStart()));a.put("assignedWindowClose",Double.toString(authorization.nominalClose()));
        a.put("latestEntryTime",Double.toString(authorization.latestEntryTime()));a.put("latestEntryInclusive",Boolean.toString(authorization.latestEntryInclusive()));
        a.put("completionDeadline",Double.toString(authorization.completionDeadline()));
        for(int i=0;i<mutate.length;i+=2)a.put(mutate[i],mutate[i+1]);
        return new Event(time) {
            @Override public String getEventType(){return "simz1FreightAdmissionRejected";}
            @Override public Map<String,String> getAttributes(){var attrs=super.getAttributes();attrs.putAll(a);return attrs;}
        };
    }
    static void toleratedEntryAndRejectionEvidence()throws Exception {
        String policy=SimZ1FreightCompletion.TOLERATED_ENTRY_POLICY;
        SimZ1FreightCompletion.requirePolicy(policy);
        for(double[] window:SimZ1FreightCompletion.WINDOWS) {
            double planned=window[0]+100,close=window[1];
            var s=scenario(planned,policy);var person=s.getPopulation().getPersons().get(Id.createPersonId("h"));
            for(double t:new double[]{planned,close-1,close,close+1800,close+3600,close+3600.001,close+14400}) {
                var authorization=SimZ1Freight.originEntry(person,t);
                check(authorization.permitted()==(t<=close+3600),"v2 entry boundary: "+t);
                check(authorization.latestEntryInclusive()&&authorization.latestEntryTime()==close+3600&&
                    authorization.completionDeadline()==close+3600,"Entry extended completion deadline");
                var h=handler(planned,policy);
                if(t<=close+3600) {start(h,planned,t);if(t<=close+1800){finish(h,t+3,true);h.requireApproved();}else rejectedWith(h::requireApproved,"FREIGHT_NOT_APPROVED");}
                else rejectedWith(()->start(h,planned,t),"entry outside assigned authorization");
            }
        }
        var over=handler(100,policy);start(over,100,19800);finish(over,21601,true);
        rejectedWith(over::requireApproved,"FREIGHT_NOT_APPROVED");
        check(SimZ1FreightCompletion.classify(policy,100,19800.,21601.,21601.,true,false,true).equals("excess_tolerance"),"Entry tolerance reopened completion deadline");
        var s=scenario(100,policy);var person=s.getPopulation().getPersons().get(Id.createPersonId("h"));
        for(String[] mutation:List.of(new String[]{"reason","authorized"},new String[]{"vehicle","wrong"},
                new String[]{"link","b"},new String[]{"scheduledDeparture","101"},new String[]{"assignedWindowClose","32400"},
                new String[]{"latestEntryTime","36000"},new String[]{"latestEntryInclusive","false"},
                new String[]{"completionDeadline","36000"},new String[]{"entryPolicy","unknown"},
                new String[]{"completionPolicy",SimZ1FreightCompletion.POLICY},new String[]{"assignedWindowStart","NaN"},
                new String[]{"latestEntryTime","malformed"})) {
            var h=new SimZ1Freight(s);SimZ1FreightClosureCheck.send(h,"departure",100,"a");
            rejectedWith(()->h.handleEvent(denial(person,21601,mutation)),"freight admission rejection");
        }
        var h=new SimZ1Freight(s);SimZ1FreightClosureCheck.send(h,"departure",100,"a");
        h.handleEvent(denial(person,21601));
        rejectedWith(()->h.handleEvent(denial(person,21601)),"Duplicate freight admission rejection");
        check(h.activeCount()==1&&h.violations().isEmpty(),"Authorization denial moved/removed actor or invented road residence");
        var report=java.nio.file.Files.createTempFile("freight-origin-denial-",".csv");
        try {
            h.writeReport(report);
            try(var reader=java.nio.file.Files.newBufferedReader(report);
                    var csv=org.apache.commons.csv.CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {
                var row=csv.getRecords().get(0);
                check(row.get("admission_status").equals("authorization_expired_not_admitted"),"Expired origin missing from audit");
                check(row.get("traffic_entry").isEmpty()&&row.get("traffic_exit").isEmpty()&&row.get("arrival").isEmpty(),"Denial manufactured movement");
                check(row.get("completion_classification").equals("pending_not_evaluable"),"Denied freight was approved");
                check(row.get("completion_policy").equals(policy)&&row.get("latest_entry_time").equals("21600.0")&&row.get("latest_entry_inclusive").equals("true"),"Wrong audit policy/boundary");
            }
        } finally {java.nio.file.Files.deleteIfExists(report);}
        SimZ1FreightClosureCheck.send(h,"stuckAndAbort",86400,"a");rejectedWith(h::requireApproved,"FREIGHT_NOT_APPROVED");
        var before=new SimZ1Freight(s);rejectedWith(()->before.handleEvent(denial(person,21601)),"Invalid freight admission rejection");
        var entered=new SimZ1Freight(s);start(entered,100,100);rejectedWith(()->entered.handleEvent(denial(person,21601)),"Invalid freight admission rejection");
        h.reset(1);SimZ1FreightClosureCheck.send(h,"departure",100,"a");h.handleEvent(denial(person,21601));
        var duplicate=handler(100,policy);start(duplicate,100,19800);
        rejectedWith(()->SimZ1FreightClosureCheck.send(duplicate,"vehicle enters traffic",19800,"a"),"identity mismatch");
        var late=handler(100,policy);start(late,100,19800);
        rejectedWith(()->SimZ1FreightClosureCheck.send(late,"vehicle enters traffic",19799,"a"),"non-monotone event time");
    }
    public static void main(String[] args)throws Exception {
        SimZ1FreightCompletion.requirePolicy(SimZ1FreightCompletion.POLICY);
        for(double[] window:SimZ1FreightCompletion.WINDOWS) {
            double dep=window[0]+100,close=window[1];
            for(double delta:new double[]{-1,0,3599,3600,3600.001}) {
                var h=handler(dep);start(h,dep,dep);finish(h,close+delta,true);
                check(h.approved()==(delta<=3600),"Inclusive deadline");
                check(h.violations().isEmpty()==(delta<0),"Original nominal violation retained");
                if(delta>3600)SimZ1FreightClosureCheck.rejected(h::requireApproved);else h.requireApproved();
                h.reset(9);check(!h.approved()&&h.violations().isEmpty(),"Iteration 9 ledger reset");
                start(h,dep,dep);finish(h,dep+100,true);h.requireApproved();
            }
        }
        var body=handler(100);start(body,100,100);SimZ1FreightClosureCheck.rejected(()->finish(body,200,false));
        var entry=handler(100);SimZ1FreightClosureCheck.rejected(()->start(entry,100,19800));
        var reassigned=handler(100);SimZ1FreightClosureCheck.rejected(()->start(reassigned,100,33000));
        var missing=handler(100);start(missing,100,100);check(!missing.approved(),"Missing arrival accepted");
        SimZ1FreightClosureCheck.send(missing,"stuckAndAbort",200,"a");SimZ1FreightClosureCheck.rejected(missing::requireApproved);
        check(SimZ1FreightCompletion.classify(80000,80000.,86401.,86401.,true,false,false).equals("nominal"),"Midnight reset");
        check(SimZ1FreightCompletion.classify(100,100.,33000.,33000.,true,false,true).equals("excess_tolerance"),"Window reopened deadline");
        check(!SimZ1Freight.permitted(100,18000),"Global entry window widened");
        entryAndLifecycle();
        toleratedEntryAndRejectionEvidence();
        System.out.println("SIMZ1_FREIGHT_COMPLETION_OK");
    }
}
