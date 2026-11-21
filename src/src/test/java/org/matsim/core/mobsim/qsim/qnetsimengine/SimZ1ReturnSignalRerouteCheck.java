package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import gt.edu.uvg.sim.zona1.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.model.*;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OpposedReturnRerouteCheck.*;

/** Synthetic fixed-phase route validation only: no controller or QSim runs.
 * Documents an existing protection, rather than changing its signal policy. */
public final class SimZ1ReturnSignalRerouteCheck {
    private static Scenario scenario(double connectorLength,boolean disjoint) {
        var config=ConfigUtils.createConfig(new SignalSystemsConfigGroup());
        var signals=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);
        signals.setUseSignalSystems(true);signals.setUseAmbertimes(true);
        var s=ScenarioUtils.createScenario(config);var n=s.getNetwork();
        var coords=Map.of("o",new Coord(-100,0),"j",new Coord(0,0),"p",new Coord(connectorLength,0),
            "n",new Coord(0,100),"d",new Coord(0,200));
        for(var e:coords.entrySet())n.addNode(n.getFactory().createNode(Id.createNodeId(e.getKey()),e.getValue()));
        link(n,"approach","o","j",100,1);link(n,"return-out","j","p",connectorLength,1);
        link(n,"return-back","p","j",connectorLength,1);link(n,"out","j","n",100,1);link(n,"destination","n","d",100,1);
        LanesGenerator.build(s);
        var data=SignalUtils.createSignalsData(signals);s.addScenarioElement(SignalsData.ELEMENT_NAME,data);
        var systemId=Id.create("junction",SignalSystem.class);var systems=data.getSignalSystemsData();
        var system=systems.getFactory().createSignalSystemData(systemId);systems.addSignalSystemData(system);
        var control=data.getSignalControlData();var controller=control.getFactory().createSignalSystemControllerData(systemId);
        controller.setControllerIdentifier(Zona1FixedTimeController.ID);control.addSignalSystemControllerData(controller);
        var plan=control.getFactory().createSignalPlanData(Id.create("daily",SignalPlan.class));
        plan.setStartTime(0.0);plan.setEndTime(0.0);plan.setCycleTime(60);plan.setOffset(0);controller.addSignalPlanData(plan);
        String[][] movements={{"approach","return-out"},{"return-back","out"}};
        for(int i=0;i<movements.length;i++) {
            var signal=systems.getFactory().createSignalData(Id.create("s"+i,Signal.class));
            signal.setLinkId(id(movements[i][0]));signal.addLaneId(lane(movements[i][0]+".lane.0"));signal.addTurningMoveRestriction(id(movements[i][1]));system.addSignalData(signal);
            var gid=Id.create("g"+i,SignalGroup.class);var groups=data.getSignalGroupsData();
            var group=groups.getFactory().createSignalGroupData(systemId,gid);group.addSignalId(signal.getId());groups.addSignalGroupData(group);
            var settings=control.getFactory().createSignalGroupSettingsData(gid);
            settings.setOnset(i==1&&disjoint?30:0);settings.setDropping(i==1&&disjoint?50:20);plan.addSignalGroupSettings(settings);
        }
        return s;
    }
    private static void checkRoute(double body,double length,boolean disjoint,String expected) throws Exception {
        var s=scenario(length,disjoint);var events=new ArrayList<Event>();var manager=EventsUtils.createEventsManager();
        manager.addHandler((BasicEventHandler)events::add);
        var ledger=new SimZ1CorridorOccupancy(s,Set.of(Id.createNodeId("j")),manager);SimZ1CorridorOccupancy.install(s.getConfig().qsim(),ledger);
        try {
            var old=path("approach","out","destination");
            var candidate=path("approach","return-out","return-back","out","destination");
            var actor=new Actor(s,"returning-body",body,old);
            check(ledger.activity(actor.vehicle,id("approach"),"approach.original",0),"Initial complete-body reservation missing");
            var safety=new SimZ1RouteSafety(s);
            check(safety.validateReplacement(old,candidate,0,id("approach"),id("destination"),lane("approach.original"))==null,"Fixture return must be topologically legal");
            var windows=new Zona1SignalGreenWindow(s);
            check(windows.mutuallyExclusive(id("approach"),lane("approach.lane.0"),id("return-out"),
                id("return-back"),lane("return-back.lane.0"),id("out"))==disjoint,"Wrong signal proof fixture");
            String before=snapshot(ledger);int count=events.size();var original=actor.leg.getRoute();
            // This guard already existed before correction 2; preserve it.
            String issue=SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),actor.vehicle.getId(),candidate,0);
            check(Objects.equals(expected,issue),"Expected "+expected+", got "+issue);
            check(Objects.equals(expected,SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),actor.vehicle.getId(),candidate,0,null)),
                "New pre-installation guard bypassed the existing signal protection");
            check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),actor.vehicle.getId(),old,0)==null,"Ordinary destination-preserving route rejected");
            check(before.equals(snapshot(ledger))&&count==events.size(),"Signal validation mutated reservations/events");
            check(original==actor.leg.getRoute()&&actor.full().equals(old),"Candidate validation installed a route");
        } finally {SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());}
    }
    public static void main(String[] args) throws Exception {
        try {
            for(double body:new double[]{2.1,4.5,12.0}) {
                checkRoute(body,2,true,"occupancy_incompatible_passage_signals");
                checkRoute(body,40,true,null); // full stopping receiver separates the incompatible phases
                checkRoute(body,2,false,null); // no incompatible phase proof: do not ban a legal return
            }
            System.out.println("PASS existing return-phase protection: incompatible nonstopping cycles rejected; long stopping returns and compatible phases retained; body reservations, routes and destinations untouched");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
