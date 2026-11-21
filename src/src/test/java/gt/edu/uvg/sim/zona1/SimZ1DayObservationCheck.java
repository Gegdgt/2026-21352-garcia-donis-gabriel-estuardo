package gt.edu.uvg.sim.zona1;

import java.util.*;
/** Pure classification controls; native cutoff is exercised by ArrivalClearanceCheck. */
public final class SimZ1DayObservationCheck {
    static Map<String,Object> row(String family,double scheduled,double departure,double entry) {
        var r=new LinkedHashMap<String,Object>();r.put("family",family);r.put("scheduled_departure",scheduled);
        r.put("departure",departure);r.put("traffic_entry",entry);r.put("traffic_exit",null);r.put("arrival",null);r.put("abort_before_cleanup",null);return r;
    }
    static void check(boolean ok){if(!ok)throw new AssertionError("Fixed-day classification");}
    public static void main(String[] args) {
        var recent=row("carro",86340,86340,86340);
        check(SimZ1DayObservation.classify(recent,86400,true).get("pending_class").equals("recent_at_horizon"));
        check(SimZ1DayObservation.classify(row("moto",82799,82799,82799),86400,true).get("pending_class").equals("prolonged_traffic_review_required"));
        check(SimZ1DayObservation.classify(row("carro",82800,82800,82800),86400,true).get("pending_class").equals("recent_at_horizon"));
        check(SimZ1DayObservation.classify(row("carro",100,100,86399),86400,true).get("pending_class").equals("recent_entry_old_request"));
        for(String family:List.of("pesado","bus"))check(SimZ1DayObservation.classify(row(family,75600,75600,75600),86400,true).get("pending_class").equals("horizon_censored_no_private_duration_threshold"));
        var arrival=row("carro",86340,86340,86340);arrival.put("arrival",86400.);
        check(SimZ1DayObservation.classify(arrival,86400,true).get("status").equals("completed"));
        arrival.put("arrival",null);arrival.put("abort_before_cleanup",86399.);
        var aborted=SimZ1DayObservation.classify(arrival,86400,true);
        check(aborted.get("status").equals("aborted_before_cut"));
        check(aborted.get("observed_traffic_seconds").equals(59.)&&aborted.get("observed_traffic_end_basis").equals("abort_before_cleanup"));
        check(SimZ1DayObservation.classify(row("carro",50000,50000,50000),59159,false).get("status").equals("interrupted_before_horizon"));
        var exited=row("carro",100,100,100);exited.put("traffic_exit",500.);
        var afterExit=SimZ1DayObservation.classify(exited,86400,true);
        check(afterExit.get("status").equals("exited_without_arrival")&&afterExit.get("pending_class").equals("arrival_not_observed_review_required"));
        check(afterExit.get("observed_traffic_seconds").equals(400.)&&afterExit.get("observed_traffic_end_seconds").equals(500.)&&afterExit.get("observed_traffic_end_basis").equals("traffic_exit"));
        check(afterExit.get("arrival")==null&&afterExit.get("complete_duration_seconds")==null);
        exited.put("abort_before_cleanup",600.);
        var exitThenAbort=SimZ1DayObservation.classify(exited,86400,true);
        check(exitThenAbort.get("status").equals("aborted_before_cut")&&exitThenAbort.get("observed_traffic_seconds").equals(400.));
        exited.put("abort_before_cleanup",400.);
        var abortThenExit=SimZ1DayObservation.classify(exited,86400,true);
        check(abortThenExit.get("observed_traffic_seconds").equals(300.)&&abortThenExit.get("observed_traffic_end_basis").equals("abort_before_cleanup"));
        exited.put("abort_before_cleanup",500.);
        check(SimZ1DayObservation.classify(exited,86400,true).get("observed_traffic_end_basis").equals("traffic_exit"));
        exited.put("abort_before_cleanup",null);exited.put("cleanup_abort_events",2L);
        var cleanupAfterExit=SimZ1DayObservation.classify(exited,86400,true);
        check(cleanupAfterExit.get("status").equals("exited_without_arrival")&&cleanupAfterExit.get("observed_traffic_seconds").equals(400.)&&cleanupAfterExit.get("abort_before_cleanup")==null);
        check(SimZ1DayObservation.classify(exited,59159,false).get("status").equals("interrupted_before_horizon"));
        var pendingCleanup=row("bus",86340,86340,86340);pendingCleanup.put("cleanup_abort_events",2L);
        var pendingAfterCleanup=SimZ1DayObservation.classify(pendingCleanup,86400,true);
        check(pendingAfterCleanup.get("status").equals("active_at_cut")&&pendingAfterCleanup.get("observed_traffic_seconds").equals(60.)&&pendingAfterCleanup.get("observed_traffic_end_basis").equals("observation_cut"));
        exited.put("arrival",700.);
        var completedAfterExit=SimZ1DayObservation.classify(exited,86400,true);
        check(completedAfterExit.get("status").equals("completed")&&completedAfterExit.get("complete_duration_seconds").equals(600.));
        check(completedAfterExit.get("observed_traffic_seconds")==null&&completedAfterExit.get("observed_traffic_end_seconds")==null&&completedAfterExit.get("observed_traffic_end_basis")==null);
        var noEntry=row("bus",86340,86340,86340);noEntry.put("traffic_entry",null);noEntry.put("traffic_exit",86350.);
        var unknownEntry=SimZ1DayObservation.classify(noEntry,86400,true);
        check(unknownEntry.get("status").equals("exited_without_arrival")&&unknownEntry.get("observed_traffic_seconds")==null&&unknownEntry.get("observed_traffic_end_seconds")==null);
        var invalidExit=row("carro",100,100,100);invalidExit.put("traffic_exit",99.);boolean invalidRejected=false;
        try{SimZ1DayObservation.classify(invalidExit,86400,true);}catch(IllegalArgumentException expected){invalidRejected=true;}
        check(invalidRejected);
        var config=org.matsim.core.config.ConfigUtils.createConfig();config.qsim().setEndTime(86399);
        var scenario=org.matsim.core.scenario.ScenarioUtils.createScenario(config);
        var observer=new SimZ1DayObservation(scenario,"fixture");
        boolean rejected=false;
        try {observer.handleEvent(new org.matsim.api.core.v01.events.PersonArrivalEvent(86401,
            org.matsim.api.core.v01.Id.createPersonId("p"),org.matsim.api.core.v01.Id.createLinkId("l"),"car"));}
        catch(IllegalStateException expected){rejected=true;}
        check(rejected);
        System.out.println("DAY CLASSIFICATION PASS: recent, >3600, =3600, old request, freight 3h, bus, T arrival, prior abort, interruption, traffic exit/abort/cut intervals, cleanup separation");
    }
}
