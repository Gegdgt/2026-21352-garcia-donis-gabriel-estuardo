package org.matsim.core.mobsim.qsim.qnetsimengine;

import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.events.SignalGroupStateChangedEvent;
import org.matsim.contrib.signals.model.*;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.lanes.Lane;

/** Native fixed controller, amber logic, system and lane permission. No simulation engine. */
public final class SimZ1RetentionPhases implements java.util.function.BiConsumer<Scenario,EventsManager> {
    private SignalSystemImpl system;
    public SignalGroupImpl group;
    private final int onset,dropping;
    public SimZ1RetentionPhases(int onset,int dropping){this.onset=onset;this.dropping=dropping;}
    public void accept(Scenario s,EventsManager events) {
        var config=ConfigUtils.addOrGetModule(s.getConfig(),SignalSystemsConfigGroup.class);
        config.setUseSignalSystems(true);config.setUseAmbertimes(true);
        var data=SignalUtils.createSignalsData(config);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
        data.getAmberTimesData().setDefaultAmber(RunZona1Simulation.AMBER_SECONDS);
        var sid=Id.create("phase-fixture",SignalSystem.class);var gid=Id.create("g",SignalGroup.class);
        var systems=data.getSignalSystemsData();var sd=systems.getFactory().createSignalSystemData(sid);systems.addSignalSystemData(sd);
        var signal=systems.getFactory().createSignalData(Id.create("s",Signal.class));signal.setLinkId(Id.createLinkId("s"));signal.addLaneId(Id.create("s.lane.0",Lane.class));sd.addSignalData(signal);
        var groups=data.getSignalGroupsData();var gd=groups.getFactory().createSignalGroupData(sid,gid);gd.addSignalId(signal.getId());groups.addSignalGroupData(gd);
        var factory=data.getSignalControlData().getFactory();var controllerData=factory.createSignalSystemControllerData(sid);
        controllerData.setControllerIdentifier(Zona1FixedTimeController.ID);data.getSignalControlData().addSignalSystemControllerData(controllerData);
        var plan=factory.createSignalPlanData(Id.create("all-day",SignalPlan.class));plan.setStartTime(0.);plan.setEndTime(0.);plan.setCycleTime(80);plan.setOffset(0);controllerData.addSignalPlanData(plan);
        var setting=factory.createSignalGroupSettingsData(gid);setting.setOnset(onset);setting.setDropping(dropping);plan.addSignalGroupSettings(setting);
        var manager=new SignalSystemsManagerImpl(data,events);manager.setAmberLogic(new AmberLogicImpl(data.getAmberTimesData()));
        system=new SignalSystemImpl(sid);system.setSignalSystemsManager(manager);manager.addSignalSystem(system);
        group=new SignalGroupImpl(gid);system.addSignalGroup(group);
        var controller=new Zona1FixedTimeController();controller.setSignalSystem(system);controller.addPlan(new DatabasedSignalPlan(plan));system.setSignalSystemController(controller);
    }
    public void attach(SimZ1RetentionFixture f,double start) {
        var lane=(SignalizeableItem)f.lane("s","s.lane.0");lane.setSignalized(true);
        f.events.addHandler((BasicEventHandler)e->{if(e instanceof SignalGroupStateChangedEvent state && state.getSignalSystemId().equals(system.getId()))lane.setSignalStateAllTurningMoves(state.getNewState());});
        system.simulationInitialized(start);system.updateState(start);
    }
    public void step(double time){system.updateState(time);}
}
