package org.matsim.core.mobsim.qsim.qnetsimengine;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.mobsim.framework.events.MobsimBeforeSimStepEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeSimStepListener;

/** Recheck due passage deadlines before native admissions, including owners
 * waiting in a buffer. The ledger enforces both time and modeled body clearance.
 */
public final class SimZ1PassageTimeListener implements MobsimBeforeSimStepListener {
    private final QSimConfigGroup config;
    @Inject public SimZ1PassageTimeListener(Scenario scenario){config=scenario.getConfig().qsim();}
    @Override public void notifyMobsimBeforeSimStep(MobsimBeforeSimStepEvent event){
        var ledger=SimZ1CorridorOccupancy.get(config);
        if(ledger!=null)ledger.advanceTime(event.getSimulationTime());
    }
}
