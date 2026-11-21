package org.matsim.core.mobsim.qsim.qnetsimengine;

/** Select only component portions of existing suites whose main also runs a
 * controller. This runner never calls those simulation entry points. */
public final class SimZ1PassageAffectedChecks {
    public static void main(String[] args)throws Exception {
        try{
            switch(args[0]){
                case "ledger"->SimZ1CorridorOccupancyCheck.ledgerFixture();
                case "parallel"->SimZ1ParallelPassagePriorityCheck.pureQueries();
                case "clearance"->SimZ1CrossingClearanceCheck.bodyAndTimeAreBothRequired();
                case "timers"->{for(var name:new String[]{"fractionalDeadlineWithoutProgress","timeAloneCannotRelease","canceledDeadlineCannotReleaseNewReservation","boundaryExitRemainsLockedUntilExit"}){
                    var method=SimZ1PassageTimerCheck.class.getDeclaredMethod(name);method.setAccessible(true);method.invoke(null);
                }}
                default->throw new IllegalArgumentException(args[0]);
            }
            System.out.println("PASS existing component checks: "+args[0]);
        }finally{org.apache.logging.log4j.LogManager.shutdown();}
    }
}
