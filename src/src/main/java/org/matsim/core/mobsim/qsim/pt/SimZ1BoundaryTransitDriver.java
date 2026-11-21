package org.matsim.core.mobsim.qsim.pt;

import java.util.List;
import java.util.Map;
import java.util.function.BiConsumer;
import gt.edu.uvg.sim.zona1.SimZ1TransitFleet.Duty;
import gt.edu.uvg.sim.zona1.SimZ1TransitTiming;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.qnetsimengine.QLinkI;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.utils.misc.OptionalTime;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.facilities.Facility;
import org.matsim.pt.Umlauf;
import org.matsim.pt.transitSchedule.api.*;
import org.matsim.vehicles.Vehicle;

/**
 * MATSim 15 adapter for finite, reusable fixed buses crossing the computational
 * boundary. All driving links and stop dwell use native transit/QSim. Only a
 * PARKED vehicle is relocated, after its explicit off-network duration elapsed.
 * No exterior LinkEnter/LinkLeave events or imaginary roads are fabricated.
 * Kept in this package to use AbstractTransitDriverAgent's package lifecycle API.
 */
public final class SimZ1BoundaryTransitDriver extends AbstractTransitDriverAgent {
    private final InternalInterface internal;
    private final Scenario scenario;
    private final List<Duty> roster;
    private final Id<Vehicle> vehicleId;
    private final Plan plan;
    private final BiConsumer<Id<Vehicle>, Id<TransitStopFacility>> stopDeparted;
    private int currentDuty = 0, pendingDuty = 0, element = 0;
    private double activityEnd;

    public SimZ1BoundaryTransitDriver(Umlauf umlauf, List<Duty> duties,
            TransitStopAgentTracker tracker, InternalInterface internal,
            BiConsumer<Id<Vehicle>, Id<TransitStopFacility>> stopDeparted) {
        super(internal, tracker);
        if (duties == null || duties.isEmpty()) throw new IllegalArgumentException("empty boundary bus roster");
        this.internal=internal; this.scenario=internal.getMobsim().getScenario();
        this.roster=List.copyOf(duties); this.vehicleId=umlauf.getVehicleId();
        this.stopDeparted=stopDeparted;
        this.plan=PopulationUtils.createPlan();
        plan.addActivity(PopulationUtils.createActivityFromLinkId("transit boundary", duties.get(0).route().getRoute().getStartLinkId()));
        for (Duty duty : roster) {
            Leg leg=PopulationUtils.createLeg("car");
            leg.setRoute(getWrappedCarRoute(duty.route().getRoute()));
            plan.addLeg(leg);
            plan.addActivity(PopulationUtils.createActivityFromLinkId("transit boundary",duty.route().getRoute().getEndLinkId()));
        }
        Person driver=PopulationUtils.getFactory().createPerson(Id.createPersonId("pt_"+umlauf.getId()));
        driver.addPlan(plan);driver.setSelectedPlan(plan);setDriver(driver);
        activityEnd=duties.get(0).departure().getDepartureTime();
        init();
    }
    private Duty duty() { return roster.get(currentDuty); }
    private double closes(Duty d) {
        double civilClose=Double.parseDouble(d.line().getAttributes().getAttribute("simz1:closesSeconds").toString());
        Object cutoff=d.line().getAttributes().getAttribute("simz1:departureCutoffSeconds");
        return cutoff==null?civilClose:Math.min(civilClose,Double.parseDouble(cutoff.toString()));
    }
    private void boundary(double now,String action,Duty related,double ready) {
        internal.getMobsim().getEventsManager().processEvent(new Event(now) {
            @Override public String getEventType() { return "simz1TransitBoundary"; }
            @Override public Map<String,String> getAttributes() {
                Map<String,String> values=super.getAttributes();
                values.put("vehicle",vehicleId.toString());values.put("driver",getId().toString());
                values.put("action",action);values.put("service",related.line().getId().toString());
                values.put("departure",related.departure().getId().toString());
                values.put("readyAt",Double.toString(ready));
                values.put("basis","timed_off_network_scenario_not_observed_trajectory");
                return values;
            }
        });
    }
    /** Cancel only an expired duty, retaining later civil days for the same bus. */
    private boolean schedulePending(double now,double ready) {
        while (pendingDuty>=0 && pendingDuty<roster.size()) {
            Duty next=roster.get(pendingDuty);
            activityEnd=SimZ1TransitTiming.nextDeparture(next.departure().getDepartureTime(),ready,closes(next));
            if (Double.isFinite(activityEnd)) return true;
            boundary(now,"cancelled_duty_after_closing",next,Math.max(ready,next.departure().getDepartureTime()));
            pendingDuty++;
        }
        pendingDuty=-1;activityEnd=Double.POSITIVE_INFINITY;
        boundary(now,"service_finished",duty(),now);
        return false;
    }
    @Override public void endActivityAndComputeNextState(double now) {
        if (state != MobsimAgent.State.ACTIVITY || pendingDuty<0) throw new IllegalStateException("invalid boundary departure state");
        Duty next=roster.get(pendingDuty);
        if (now+1e-7<activityEnd) throw new IllegalStateException("bus departs before availability");
        if (now >= closes(next)) {
            if (!schedulePending(now,now) || activityEnd>now) return;
            next=roster.get(pendingDuty);
        }
        Id<Link> oldLink=getCurrentLinkId(), newLink=next.route().getRoute().getStartLinkId();
        if (!oldLink.equals(newLink)) {
            // ActivityEngine removed the old additional-agent registration before
            // this hook. We are not changing an active queue or the global B.
            QLinkI origin=(QLinkI)internal.getMobsim().getNetsimNetwork().getNetsimLink(oldLink);
            QLinkI destination=(QLinkI)internal.getMobsim().getNetsimNetwork().getNetsimLink(newLink);
            if (origin==null || destination==null || origin.getParkedVehicle(vehicleId)!=getVehicle() ||
                    destination.getParkedVehicle(vehicleId)!=null)
                throw new IllegalStateException("boundary bus unavailable in parking: "+vehicleId);
            var parked=origin.removeParkedVehicle(vehicleId);
            if (parked!=getVehicle()) throw new IllegalStateException("boundary vehicle identity changed");
            destination.addParkedVehicle(parked);
        }
        currentDuty=pendingDuty;
        ((Activity)plan.getPlanElements().get(currentDuty*2)).setLinkId(newLink);
        element=currentDuty*2+1;init();
        boundary(now,"entry",next,now);
        sendTransitDriverStartsEvent(now);
        state=MobsimAgent.State.LEG;
    }
    @Override public void endLegAndComputeNextState(double now) {
        if (state!=MobsimAgent.State.LEG) throw new IllegalStateException("duplicate bus arrival");
        internal.getMobsim().getEventsManager().processEvent(new PersonArrivalEvent(now,getId(),getDestinationLinkId(),"car"));
        element=currentDuty*2+2;state=MobsimAgent.State.ACTIVITY;
        pendingDuty=currentDuty+1;
        double ready=SimZ1TransitTiming.readyAt(now,duty().terminalSeconds(),duty().turnaroundSeconds());
        String kind=String.valueOf(duty().route().getAttributes().getAttribute("simz1:transferKind"));
        boundary(now,"exterior".equals(kind)?"outside_start":"terminal_start",duty(),ready);
        schedulePending(now,ready);
    }
    @Override public double handleTransitStop(TransitStopFacility stop,double now) {
        double left=super.handleTransitStop(stop,now);
        if (left==0)stopDeparted.accept(vehicleId,stop.getId());
        return left;
    }
    @Override protected NetworkRoute getCarRoute() { return duty().route().getRoute(); }
    @Override protected TransitLine getTransitLine() { return duty().line(); }
    @Override public TransitRoute getTransitRoute() { return duty().route(); }
    @Override protected Departure getDeparture() { return duty().departure(); }
    @Override public double getActivityEndTime() { return activityEnd; }
    @Override Leg getCurrentLeg() { return (Leg)plan.getPlanElements().get(currentDuty*2+1); }
    @Override public OptionalTime getExpectedTravelTime() { return getCurrentLeg().getTravelTime(); }
    @Override public Double getExpectedTravelDistance() { return getCurrentLeg().getRoute().getDistance(); }
    @Override public String getMode() { return "car"; }
    @Override public Id<Vehicle> getPlannedVehicleId() { return vehicleId; }
    @Override public Id<Link> getDestinationLinkId() { return duty().route().getRoute().getEndLinkId(); }
    @Override public Plan getCurrentPlan() { return PopulationUtils.unmodifiablePlan(plan); }
    @Override public PlanElement getCurrentPlanElement() { return plan.getPlanElements().get(element); }
    @Override public PlanElement getPreviousPlanElement() { return element>0?plan.getPlanElements().get(element-1):null; }
    @Override public PlanElement getNextPlanElement() { return element+1<plan.getPlanElements().size()?plan.getPlanElements().get(element+1):null; }
    @Override public boolean isWantingToArriveOnCurrentLink() { return chooseNextLinkId()==null; }
    @Override public Facility getCurrentFacility() {
        Activity activity=(Activity)plan.getPlanElements().get(element%2==0?element:element-1);
        return FacilitiesUtils.toFacility(activity,scenario.getActivityFacilities());
    }
    @Override public Facility getDestinationFacility() {
        return state==MobsimAgent.State.LEG?FacilitiesUtils.toFacility((Activity)plan.getPlanElements().get(element+1),scenario.getActivityFacilities()):null;
    }
}
