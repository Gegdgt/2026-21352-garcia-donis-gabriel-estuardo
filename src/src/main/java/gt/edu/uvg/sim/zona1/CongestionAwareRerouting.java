package gt.edu.uvg.sim.zona1;

import java.lang.management.ManagementFactory;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.mobsim.framework.*;
import org.matsim.core.mobsim.framework.events.*;
import org.matsim.core.mobsim.framework.listeners.*;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.mobsim.qsim.agents.WithinDayAgentUtils;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.Vehicle;

/** Detached candidates, validated before serialized installation at QSim's before-step barrier. */
public final class CongestionAwareRerouting implements MobsimInitializedListener,
        MobsimBeforeSimStepListener, org.matsim.core.events.handler.BasicEventHandler {
    private static final org.apache.logging.log4j.Logger LOG=org.apache.logging.log4j.LogManager.getLogger(CongestionAwareRerouting.class);
    private final Scenario scenario;
    private final Map<String,Entry> entries=new ConcurrentHashMap<>();
    private final Map<String,Exit> pendingTurns=new ConcurrentHashMap<>();
    private final Map<Id<Link>,Observation> observations=new ConcurrentHashMap<>();
    private final Map<Turn,Observation> turnObservations=new ConcurrentHashMap<>();
    private final Map<Id<Person>,Double> last=new HashMap<>();
    private final Map<Id<Link>,Double> times=new HashMap<>();
    private final Map<Turn,Double> turnTimes=new HashMap<>();
    private final Map<String,List<Id<Link>>> traversed=new ConcurrentHashMap<>();
    private QSim qsim;
    private QNetwork network;
    private Map<Id<Vehicle>,? extends org.matsim.core.mobsim.qsim.interfaces.MobsimVehicle> vehicles;
    private org.matsim.core.api.experimental.events.EventsManager events;
    private SimZ1RouteSafety safety;
    private SimZ1TurnRouter router;
    private double next;
    private int iteration, budget;
    private boolean enabled;
    private String routingPolicy=DrivingProfiles.FASTEST_TIME;
    private String cursor="";
    private Set<Id<Person>> selected=Set.of();
    private final SimZ1ActiveRetention retention;
    private record TemporalObservation(NetworkRoute route,int index,Id<org.matsim.lanes.Lane> lane,
                                       gt.edu.uvg.sim.zona1.Zona1SignalGreenWindow.Feasibility status) { }
    private final Map<Id<Vehicle>,TemporalObservation> temporalObservations=new HashMap<>();
    private Map<String,SimZ1ActiveRetention.Retained> activeRetentions=Map.of();
    private StepTiming timing;
    private Map<String,String> lastTiming=Map.of();
    /** Exclusive monotonic costs, independent of simulation time and decisions.
     * Nested measurements pause their parent; no double counting of search and
     * context/physical/event work. Logs are bounded to phase first-start + one
     * evaluation end, not one log per candidate or path expansion. */
    static final class StepTiming {
        static final List<String> PHASES=List.of("selection","context_validation","physical_queries","search","installation","data_emission");
        private static final class Metric {long nanos,calls,firstStart=-1,lastEnd=-1;}
        private final Scenario scenario;
        private final int iteration;
        private final double simulatedTime;
        final long started=System.nanoTime(),threadId=Thread.currentThread().getId();
        private final Map<String,Metric> metrics=new LinkedHashMap<>();
        private String phase;
        private long previous=started;
        private boolean finished;
        private String failurePhase;
        StepTiming(Scenario scenario,int iteration,double now) {
            this.scenario=scenario;this.iteration=iteration;simulatedTime=now;
            for(String name:PHASES)metrics.put(name,new Metric());
            LOG.info("SIMZ1_REROUTE_BEGIN iteration={} simulatedTime={} threadId={} threadName={} monotonicStartNanos={}",
                iteration,now,threadId,Thread.currentThread().getName(),started);
            switchTo("selection");
        }
        private void checkpoint(long now) {if(phase!=null)metrics.get(phase).nanos+=now-previous;previous=now;}
        private void switchTo(String next) {
            long now=System.nanoTime();checkpoint(now);phase=next;
            if(next==null)return;
            Metric metric=metrics.get(next);metric.calls++;
            if(metric.firstStart<0) {
                metric.firstStart=now;
                LOG.info("SIMZ1_REROUTE_PHASE_BEGIN iteration={} simulatedTime={} threadId={} phase={} monotonicStartNanos={}",iteration,simulatedTime,threadId,next,now);
            }
            SimZ1Diagnostics.work(scenario,"CongestionAwareRerouting.evaluate",next,iteration,simulatedTime,started,true);
        }
        final class Scope implements AutoCloseable {
            final String parent,entered;boolean closed;
            Scope(String name){parent=phase;entered=name;switchTo(name);}
            @Override public void close(){if(closed)return;closed=true;metrics.get(entered).lastEnd=System.nanoTime();switchTo(parent);}
        }
        Scope enter(String name){return new Scope(name);}
        Map<String,String> snapshot() {
            checkpoint(System.nanoTime());var result=new LinkedHashMap<String,String>();
            result.put("timingVersion","exclusive-monotonic-v1");result.put("evaluationThreadId",Long.toString(threadId));
            for(var entry:metrics.entrySet()) {
                var m=entry.getValue();String key=entry.getKey();
                result.put(key+"Nanos",Long.toString(m.nanos));result.put(key+"Segments",Long.toString(m.calls));
                result.put(key+"FirstStartNanos",Long.toString(m.firstStart));result.put(key+"LastEndNanos",Long.toString(m.lastEnd));
            }
            result.put("activePhase",Objects.toString(phase,"none"));result.put("failurePhase",Objects.toString(failurePhase,"none"));return result;
        }
        Map<String,String> finish(String outcome) {
            if(finished)throw new IllegalStateException("Duplicate timing finish");finished=true;
            if(phase!=null)metrics.get(phase).lastEnd=System.nanoTime();
            var result=snapshot();result.put("outcome",outcome);result.put("wallNanos",Long.toString(System.nanoTime()-started));
            SimZ1Diagnostics.work(scenario,"CongestionAwareRerouting.evaluate",Objects.toString(phase,"none"),iteration,simulatedTime,started,false);
            LOG.info("SIMZ1_REROUTE_END iteration={} simulatedTime={} {}",iteration,simulatedTime,result);return Map.copyOf(result);
        }
    }
    private static <T> T measured(StepTiming timer,String phase,Supplier<T> work) {
        if(timer==null)return work.get();
        try(var ignored=timer.enter(phase)){
            try{return work.get();}
            catch(RuntimeException|Error error){if(timer.failurePhase==null)timer.failurePhase=phase;throw error;}
        }
    }
    Map<String,String> lastTiming(){return lastTiming;}
    static <T> Set<T> selectCohort(List<T> sortedIds,double share,long seed) {
        var shuffled=new ArrayList<>(sortedIds); Collections.shuffle(shuffled,new Random(seed));
        return new HashSet<>(shuffled.subList(0,(int)Math.floor(shuffled.size()*share)));
    }
    record Entry(Id<Link> link,double time) { }
    record Observation(double duration,double time) { }
    private record Exit(Entry entry,double time) { }
    private record Turn(Id<Link> from,Id<Link> to) { }
    private record Position(QVehicle vehicle,Id<Link> link,Id<Lane> lane) { }
    private static final class Step { int candidates, calculations, installed, rejected, deferred; }
    public CongestionAwareRerouting(Scenario scenario) { this.scenario=scenario;retention=new SimZ1ActiveRetention(scenario); }
    /** Public service identity comes from the loaded fleet, never a naming convention. */
    boolean isRegisteredTransitVehicle(Id<Vehicle> vehicle) {
        return vehicle!=null && scenario.getTransitVehicles().getVehicles().containsKey(vehicle);
    }
    public static void install(Controler controler) {
        var rerouting=new CongestionAwareRerouting(controler.getScenario());
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                // Integrity listeners remain active when route mutation is disabled.
                addMobsimListenerBinding().toInstance(rerouting);
                addEventHandlerBinding().toInstance(rerouting);
            }
        });
    }
    @Override public void reset(int iteration) {
        this.iteration=iteration; entries.clear(); pendingTurns.clear(); observations.clear(); turnObservations.clear(); traversed.clear();
        retention.reset();activeRetentions=Map.of();
        timing=null;lastTiming=Map.of();
    }
    @Override public void handleEvent(Event event) {
        if(event instanceof VehicleEntersTrafficEvent e)handleEvent(e);
        else if(event instanceof VehicleLeavesTrafficEvent e)handleEvent(e);
        else if(event instanceof LinkEnterEvent e)handleEvent(e);
        else if(event instanceof LinkLeaveEvent e)handleEvent(e);
        else if(event instanceof PersonStuckEvent e)retention.abortedPerson(e.getPersonId().toString());
        else if(event.getEventType().equals(Zona1NativeDiagnostics.EVENT_TYPE))retention.decision(event);
        else if(event.getEventType().equals("vehicle aborts") || event.getEventType().equals("simz1Admission")) {
            var vehicle=event.getAttributes().get("vehicle");
            if(vehicle!=null){if(event.getEventType().equals("vehicle aborts"))retention.left(vehicle);else retention.moved(vehicle);}
        }
    }
    public void handleEvent(VehicleEntersTrafficEvent e) {
        retention.entered(e.getVehicleId().toString(),e.getPersonId().toString());
        if (isRegisteredTransitVehicle(e.getVehicleId())) return;
        entries.remove(e.getVehicleId().toString()); pendingTurns.remove(e.getVehicleId().toString());
        traversed.put(e.getVehicleId().toString(),List.of(e.getLinkId()));
    }
    public void handleEvent(VehicleLeavesTrafficEvent e) {
        retention.left(e.getVehicleId().toString());
        if (isRegisteredTransitVehicle(e.getVehicleId())) return;
        entries.remove(e.getVehicleId().toString()); pendingTurns.remove(e.getVehicleId().toString());
        traversed.remove(e.getVehicleId().toString());
    }
    public void handleEvent(LinkEnterEvent e) {
        retention.moved(e.getVehicleId().toString());
        // Stop dwell belongs to the fixed service, not an estimate of car running time.
        if (isRegisteredTransitVehicle(e.getVehicleId())) return;
        Exit previous=pendingTurns.remove(e.getVehicleId().toString());
        if (previous!=null && previous.entry().time()<=previous.time() && previous.time()<=e.getTime()) {
            var from=scenario.getNetwork().getLinks().get(previous.entry().link());
            var to=scenario.getNetwork().getLinks().get(e.getLinkId());
            if (from!=null && to!=null && from.getToNode()==to.getFromNode())
                turnObservations.put(new Turn(from.getId(),to.getId()),
                    new Observation(e.getTime()-previous.entry().time(),e.getTime()));
        }
        entries.put(e.getVehicleId().toString(),new Entry(e.getLinkId(),e.getTime()));
        traversed.computeIfPresent(e.getVehicleId().toString(),(id,old)->{
            var path=new ArrayList<>(old); path.add(e.getLinkId()); return List.copyOf(path);
        });
    }
    public void handleEvent(LinkLeaveEvent e) {
        retention.moved(e.getVehicleId().toString());
        if (isRegisteredTransitVehicle(e.getVehicleId())) return;
        Entry entry=entries.remove(e.getVehicleId().toString());
        pendingTurns.remove(e.getVehicleId().toString());
        if (entry!=null && entry.link().equals(e.getLinkId()) && e.getTime()>=entry.time()) {
            observations.put(entry.link(),new Observation(e.getTime()-entry.time(),e.getTime()));
            pendingTurns.put(e.getVehicleId().toString(),new Exit(entry,e.getTime()));
        }
    }
    private static boolean fresh(Observation observation,double now) {
        return observation!=null && now>=observation.time() && now-observation.time()<=300;
    }
    double observedLinkSeconds(Id<Link> link,double now) {
        var observation=observations.get(link);
        return fresh(observation,now)?observation.duration():Double.NaN;
    }
    double observedTurnSeconds(Id<Link> from,Id<Link> to,double now) {
        var observation=turnObservations.get(new Turn(from,to));
        return fresh(observation,now)?observation.duration():Double.NaN;
    }
    static boolean shouldInstall(boolean enabled,double oldCost,double candidateCost) {
        if (!Double.isFinite(oldCost) || oldCost<0 || !Double.isFinite(candidateCost) || candidateCost<0)
            throw new IllegalArgumentException("Invalid estimated rerouting costs");
        return enabled && candidateCost+1e-9<oldCost;
    }
    static boolean needsReroute(boolean enabled,double nominal,double estimate,double baseCapacity,double currentCapacity) {
        if (!Double.isFinite(nominal) || nominal<=0 || !Double.isFinite(estimate) || estimate<0 ||
            !Double.isFinite(baseCapacity) || baseCapacity<=0 || !Double.isFinite(currentCapacity) || currentCapacity<0)
            throw new IllegalArgumentException("Invalid congestion or capacity evidence");
        return enabled && ((estimate>=3*nominal && estimate-nominal>=60) || currentCapacity<=.5*baseCapacity);
    }
    @Override public void notifyMobsimInitialized(MobsimInitializedEvent event) {
        qsim=(QSim)event.getQueueSimulation();
        initializeNative((QNetwork)qsim.getNetsimNetwork(),qsim.getVehicles(),qsim.getEventsManager());
    }
    /** The same native collaborators used by QSim; also permits bounded queue fixtures without running QSim. */
    void initializeNative(QNetwork network,Map<Id<Vehicle>,? extends org.matsim.core.mobsim.qsim.interfaces.MobsimVehicle> vehicles,
            org.matsim.core.api.experimental.events.EventsManager events) {
        this.network=network;this.vehicles=vehicles;this.events=events;
        var config=ConfigUtils.addOrGetModule(scenario.getConfig(),Zona1RoutingConfigGroup.class);
        enabled=Boolean.parseBoolean(config.getEnabled()); budget=config.getMaxReroutesPerStep();
        routingPolicy=config.getRoutingPolicy();
        var ids=new ArrayList<>(scenario.getPopulation().getPersons().keySet()); ids.sort(Comparator.comparing(Object::toString));
        ids.removeIf(id->SimZ1Freight.applies(scenario.getPopulation().getPersons().get(id)));
        selected=selectCohort(ids,config.getAgentShare(),scenario.getConfig().global().getRandomSeed()+iteration);
        last.clear(); times.clear(); turnTimes.clear(); entries.clear(); pendingTurns.clear(); observations.clear(); turnObservations.clear();
        traversed.clear(); next=Double.NEGATIVE_INFINITY; cursor="";
        retention.reset();activeRetentions=Map.of();
        safety=new SimZ1RouteSafety(scenario);
        temporalObservations.clear();
        router=new SimZ1TurnRouter(scenario.getNetwork(),safety,
            (link,time,person,vehicle)->times.getOrDefault(link.getId(),Double.NaN),
            (from,to,time,person,vehicle)->turnTimes.getOrDefault(new Turn(from.getId(),to.getId()),
                times.getOrDefault(from.getId(),Double.NaN)),routingPolicy);
        // Already-routed inputs must be valid even when rerouting is switched off.
        for (var person:scenario.getPopulation().getPersons().values()) {
            for (var element:person.getSelectedPlan().getPlanElements()) {
                if (element instanceof Leg leg && "car".equals(leg.getMode()) && leg.getRoute() instanceof NetworkRoute route) {
                    var full=SimZ1RouteSafety.full(route); String reason=safety.validateNetwork(full);
                    if (reason!=null) {
                        String evidence="person="+person.getId()+" iteration="+iteration+" oldRoute="+full+" reason="+reason;
                        LOG.error("Invalid initial route: {}",evidence);
                        throw new IllegalStateException(evidence);
                    }
                }
            }
        }
    }
    private void emit(double now,String type,Map<String,String> values) {
        measured(timing,"data_emission",()->{emitUnmeasured(now,type,values);return null;});
    }
    private void emitUnmeasured(double now,String type,Map<String,String> values) {
        Map<String,String> saved=Map.copyOf(values);
        events.processEvent(new Event(now) {
            @Override public String getEventType() { return type; }
            @Override public Map<String,String> getAttributes() {
                var result=super.getAttributes(); result.putAll(saved); result.put("iteration",Integer.toString(iteration)); return result;
            }
        });
    }
    private void evidence(double now,String type,MobsimAgent agent,int index,List<Id<Link>> old,
                          List<Id<Link>> candidate,Position position,String reason) {
        evidence(now,type,agent,index,old,candidate,position,reason,null,null,Double.NaN);
    }
    private void evidence(double now,String type,MobsimAgent agent,int index,List<Id<Link>> old,
                          List<Id<Link>> candidate,Position position,String reason,
                          SimZ1TurnRouter.Estimate oldEstimate,SimZ1TurnRouter.Estimate candidateEstimate,double enteredAt) {
        measured(timing,"data_emission",()->{evidenceUnmeasured(now,type,agent,index,old,candidate,position,reason,oldEstimate,candidateEstimate,enteredAt);return null;});
    }
    private void evidenceUnmeasured(double now,String type,MobsimAgent agent,int index,List<Id<Link>> old,
                          List<Id<Link>> candidate,Position position,String reason,
                          SimZ1TurnRouter.Estimate oldEstimate,SimZ1TurnRouter.Estimate candidateEstimate,double enteredAt) {
        var data=new LinkedHashMap<String,String>();
        var person=scenario.getPopulation().getPersons().get(agent.getId());
        String effectivePolicy=RoadVehicleProfiles.applies(person)?RoadVehicleProfiles.routingPolicy(person):routingPolicy;
        data.put("routingPolicy",effectivePolicy);
        if (RoadVehicleProfiles.applies(person))
            data.put("routingCostUnit",RoadVehicleProfiles.SHORTEST_DISTANCE.equals(effectivePolicy)?"meters":"seconds");
        if (oldEstimate!=null && candidateEstimate!=null) {
            data.put("trigger","congestion_or_capacity_reduction");
            data.put("estimateSource","recent_observed_turn_else_link_else_freeflow_profile_vehicle");
            data.put("estimateSnapshotTime",Double.toString(now));
            data.put("estimateObservationTtlSeconds","300");
            data.put("estimatedOldSeconds",Double.toString(oldEstimate.seconds()));
            data.put("estimatedCandidateSeconds",Double.toString(candidateEstimate.seconds()));
            data.put("estimatedOldCost",Double.toString(oldEstimate.cost()));
            data.put("estimatedCandidateCost",Double.toString(candidateEstimate.cost()));
            data.put("currentLinkEntryTime",Double.isNaN(enteredAt)?"unknown":Double.toString(enteredAt));
            data.put("remainingTimeModel",Double.isNaN(enteredAt)?"full_current_link_estimate_entry_unknown":"estimated_turn_minus_elapsed");
        }
        data.put("person",agent.getId().toString());
        data.put("vehicle",position==null?String.valueOf(((MobsimDriverAgent)agent).getPlannedVehicleId()):position.vehicle().getId().toString());
        var retained=activeRetentions.get(data.get("vehicle"));
        if(retained!=null) {
            data.put("activeRetentionSource","native_receiver_WAIT_revalidated_head_lane_signal_physical_receiver");
            data.put("activeRetentionSince",Double.toString(retained.evidence().since()));
            data.put("activeRetentionLastConfirmed",Double.toString(retained.evidence().last()));
            data.put("activeRetentionConfirmedSeconds",Double.toString(retained.evidence().seconds()));
            data.put("activeRetentionTimeBasis","confirmed_physical_intervals_v2");
            data.put("activeRetentionAccumulatedPhysicalSeconds",Double.toString(retained.evidence().accumulatedSeconds()));
            data.put("activeRetentionEvidenceSpanSeconds",Double.toString(now-retained.evidence().started()));
            data.put("activeRetentionLastStateObserved",Double.toString(retained.evidence().observed()));
            data.put("activeRetentionPhysicalReason",retained.physicalReason());
            data.put("activeRetentionUsedAsTravelTime","false");
        }
        data.put("currentLink",String.valueOf(agent.getCurrentLinkId()));
        data.put("physicalLink",position==null?"unavailable":position.link().toString());
        data.put("lane",position==null?"unavailable":String.valueOf(position.lane()));
        data.put("routeIndex",Integer.toString(index)); data.put("oldRoute",old.toString());
        data.put("candidateRoute",candidate==null?"unavailable":candidate.toString()); data.put("reason",reason);
        data.put("traversedLinks",String.valueOf(traversed.get(data.get("vehicle"))));
        boolean differs=candidate!=null&&!old.equals(candidate);
        data.put("candidateDiffers",Boolean.toString(differs));
        data.put("changed",Boolean.toString(type.equals("zona1WithinDayReroute") && differs));
        emit(now,type,data);
        if (type.equals("zona1InvalidCurrentRoute")) LOG.error("Route validation failed at {}: {}",now,data);
    }
    private void fatal(double now,MobsimAgent agent,int index,List<Id<Link>> old,Position position,String reason) {
        evidence(now,"zona1InvalidCurrentRoute",agent,index,old,null,position,reason);
        throw new IllegalStateException("Invalid current route: person="+agent.getId()+" vehicle="+
            ((MobsimDriverAgent)agent).getPlannedVehicleId()+" time="+now+" link="+agent.getCurrentLinkId()+
            " index="+index+" oldRoute="+old+" reason="+reason);
    }
    private Position locate(MobsimDriverAgent agent) {
        var vehicle=vehicles.get(agent.getPlannedVehicleId());
        if (!(vehicle instanceof QVehicle qvehicle) || vehicle.getCurrentLink()==null || qvehicle.getDriver()!=agent) return null;
        Id<Link> actual=vehicle.getCurrentLink().getId();
        var link=network.getNetsimLink(actual);
        if (link==null || link.getVehicle(vehicle.getId())!=vehicle) return null;
        Id<Lane> lane=null;
        if (link instanceof QLinkLanesImpl multi) {
            for (var queue:multi.getQueueLanes().values()) if (queue.getVehicle(vehicle.getId())==vehicle) {
                if (lane!=null) throw new IllegalStateException("Vehicle in two QSim lanes: "+vehicle.getId());
                lane=queue.getId();
            }
            if (lane==null) return null; // waiting for insertion: do not guess the receiving lane
        }
        return new Position(qvehicle,actual,lane);
    }
    record Candidate(List<Id<Link>> suffix,List<Id<Link>> route,String issue) { }
    Map<String,SimZ1ActiveRetention.Retained> retained(QNetwork network,SimZ1RouteSafety policy,double now) {
        return retention.snapshot(network,policy,now);
    }
    static boolean triggered(List<Id<Link>> route,int index,Set<Id<Link>> severe,boolean retainedHead) {
        return retainedHead || route.subList(index+1,route.size()).stream().anyMatch(severe::contains);
    }
    boolean evaluationDue(double now){if(now<next)return false;next=now+60;return true;}
    boolean eligible(MobsimAgent agent,double now) {
        return !SimZ1Freight.applies(scenario.getPopulation().getPersons().get(agent.getId())) &&
            !(agent instanceof org.matsim.core.mobsim.qsim.pt.TransitDriverAgent) && selected.contains(agent.getId()) &&
            agent instanceof MobsimDriverAgent driver && agent.getState()==MobsimAgent.State.LEG &&
            "car".equals(agent.getMode()) && now-last.getOrDefault(agent.getId(),Double.NEGATIVE_INFINITY)>=300 &&
            !isRegisteredTransitVehicle(driver.getPlannedVehicleId());
    }
    List<MobsimAgent> chooseAttempts(List<MobsimAgent> candidates) {
        candidates.sort(Comparator.comparing(a->a.getId().toString()));
        int first=0;while(first<candidates.size() && candidates.get(first).getId().toString().compareTo(cursor)<=0)first++;
        var chosen=new ArrayList<MobsimAgent>();
        for(int i=0;i<Math.min(budget,candidates.size());i++)chosen.add(candidates.get((first+i)%candidates.size()));
        return chosen;
    }
    /** An active current-head trigger does not authorize a lane change or queue jump. */
    static String activeCandidateIssue(QNetwork network,Id<Link> from,Id<Lane> laneId,Id<Link> next) {
        var source=network.getNetsimLinks().get(from);var target=network.getNetsimLinks().get(next);
        if(source==null || target==null)return "active_candidate_native_link_missing";
        var lane=SimZ1ActiveRetention.lane(source,laneId);
        if(lane==null || lane.isNotOfferingVehicle())return "active_candidate_head_not_offered";
        if(lane instanceof org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem signal && !signal.hasGreenForToLink(next))
            return "active_candidate_signal_not_green";
        return target.getAcceptingQLane().isAcceptingFromUpstream()?null:"active_candidate_receiver_native_storage";
    }
    /** Pure preparation: rejection never installs a route, advances a cursor or touches reservations. */
    static Candidate candidate(SimZ1RouteSafety safety,SimZ1TurnRouter router,Person person,org.matsim.api.core.v01.population.Leg leg,
            int index,Id<Link> current,Id<Lane> lane,double now,Vehicle vehicle,double enteredAt,List<Id<Link>> history) {
        return candidate(safety,router,person,leg,index,current,lane,now,vehicle,enteredAt,history,null);
    }
    private static Candidate candidate(SimZ1RouteSafety safety,SimZ1TurnRouter router,Person person,org.matsim.api.core.v01.population.Leg leg,
            int index,Id<Link> current,Id<Lane> lane,double now,Vehicle vehicle,double enteredAt,List<Id<Link>> history,StepTiming timer) {
        var route=(NetworkRoute)leg.getRoute();var old=SimZ1RouteSafety.full(route);
        String issue=safety.validateReplacement(old,old,index,current,route.getEndLinkId(),lane);
        if(issue!=null)return new Candidate(null,null,issue);
        if(!old.subList(0,index+1).equals(history))return new Candidate(null,null,"traversed_event_prefix_mismatch");
        SimZ1TripOd.Contract contract;
        try {contract=safety.tripOd().forLeg(person,leg);}
        catch(IllegalArgumentException error){return new Candidate(null,null,error.getMessage());}
        if(contract!=null && (issue=contract.validate(old))!=null)return new Candidate(null,null,"old_route "+issue);
        var suffix=measured(timer,"search",()->router.path(current,route.getEndLinkId(),now,person,vehicle,lane,enteredAt,history,contract));
        if(suffix==null)return new Candidate(null,null,contract==null?"no_allowed_path":"no_od_compatible_path");
        var proposed=SimZ1RouteSafety.splice(old,index,suffix);
        return new Candidate(suffix,proposed,safety.validateReplacement(old,proposed,index,current,route.getEndLinkId(),lane,contract));
    }

    private void attempt(MobsimAgent agent,double now,Step step) {
        var leg=WithinDayAgentUtils.getModifiableCurrentLeg(agent);
        var route=(NetworkRoute)leg.getRoute(); var old=SimZ1RouteSafety.full(route);
        int index=WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent);
        String invalid=safety.validateReplacement(old,old,index,agent.getCurrentLinkId(),route.getEndLinkId(),null);
        if (invalid!=null) fatal(now,agent,index,old,null,invalid);
        Position position=measured(timing,"physical_queries",()->locate((MobsimDriverAgent)agent));
        if (position==null) {
            step.rejected++; evidence(now,"zona1RerouteRejected",agent,index,old,null,null,"physical_vehicle_or_lane_not_ready"); return;
        }
        if (!position.link().equals(agent.getCurrentLinkId())) fatal(now,agent,index,old,position,"agent_vehicle_link_mismatch");
        var history=traversed.get(position.vehicle().getId().toString());
        if (history==null) {
            step.rejected++; evidence(now,"zona1RerouteRejected",agent,index,old,null,position,"physical_history_not_ready"); return;
        }
        if (!history.equals(old.subList(0,index+1))) fatal(now,agent,index,old,position,"traversed_event_prefix_mismatch actual="+history);
        invalid=safety.validateReplacement(old,old,index,position.link(),route.getEndLinkId(),position.lane());
        if (invalid!=null) fatal(now,agent,index,old,position,invalid);
        step.calculations++;
        var person=scenario.getPopulation().getPersons().get(agent.getId());
        var vehicle=scenario.getVehicles().getVehicles().get(position.vehicle().getId());
        var oldFeasibility=safety.temporal(old,index,person,vehicle,position.lane(),true).status();
        Entry entry=entries.get(position.vehicle().getId().toString());
        double enteredAt=entry!=null && entry.link().equals(position.link())?entry.time():Double.NaN;
        Candidate prepared;
        try { prepared=candidate(safety,router,person,leg,index,position.link(),position.lane(),now,vehicle,enteredAt,List.copyOf(history),timing); }
        catch (RuntimeException error) {
            evidence(now,"zona1RerouteRejected",agent,index,old,null,position,"calculation_exception: "+error);
            throw error;
        }
        last.put(agent.getId(),now);
        var suffix=prepared.suffix();var candidate=prepared.route();
        if (prepared.issue()!=null) {
            step.rejected++; evidence(now,"zona1RerouteRejected",agent,index,old,candidate,position,prepared.issue()); return;
        }
        var candidateFeasibility=safety.temporal(candidate,index,person,vehicle,position.lane(),true).status();
        if(candidateFeasibility==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE||
                oldFeasibility==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE&&candidateFeasibility!=Zona1SignalGreenWindow.Feasibility.COMPATIBLE) {
            step.rejected++;evidence(now,"zona1RerouteRejected",agent,index,old,candidate,position,"temporal_candidate_"+candidateFeasibility);return;
        }
        invalid=measured(timing,"physical_queries",()->org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancy.replacementIssue(
            scenario.getConfig().qsim(),position.vehicle().getId(),candidate,index,network));
        if(invalid!=null){step.rejected++;evidence(now,"zona1RerouteRejected",agent,index,old,candidate,position,invalid);return;}
        boolean temporalRepair=oldFeasibility==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE &&
            candidateFeasibility==Zona1SignalGreenWindow.Feasibility.COMPATIBLE;
        if(activeRetentions.containsKey(position.vehicle().getId().toString())||temporalRepair) {
            invalid=measured(timing,"physical_queries",()->activeCandidateIssue(network,position.link(),position.lane(),candidate.get(index+1)));
            if(invalid!=null){step.rejected++;evidence(now,"zona1RerouteRejected",agent,index,old,candidate,position,invalid);return;}
        }
        var oldEstimate=router.evaluate(old.subList(index,old.size()),now,person,vehicle,enteredAt);
        var candidateEstimate=router.evaluate(suffix,now,person,vehicle,enteredAt);
        if (!shouldInstall(enabled,oldEstimate.cost(),candidateEstimate.cost()) && !(enabled&&temporalRepair)) {
            step.rejected++; evidence(now,"zona1RerouteRejected",agent,index,old,candidate,position,
                "no_expected_improvement",oldEstimate,candidateEstimate,enteredAt); return;
        }
        if (!candidate.equals(old)) {
          try(var ignored=timing.enter("installation")) {
            var replacement=route.clone();
            replacement.setLinkIds(candidate.get(0),candidate.subList(1,Math.max(1,candidate.size()-1)),candidate.get(candidate.size()-1));
            replacement.setDistance(RouteUtils.calcDistance(replacement,1.,1.,scenario.getNetwork()));
            replacement.setTravelTimeUndefined();
            leg.setRoute(replacement);
            // EditRoutes.replanCurrentLeg already resets caches. We replace its splice,
            // so refresh once after our own validated installation.
            WithinDayAgentUtils.resetCaches(agent);
            int after=WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent);
            var driver=(MobsimDriverAgent)agent;
            boolean nextValid=index==candidate.size()-1 ? driver.isWantingToArriveOnCurrentLink() :
                Objects.equals(candidate.get(index+1),driver.chooseNextLinkId());
            if (after!=index || !nextValid) {
                leg.setRoute(route); WithinDayAgentUtils.resetCaches(agent);
                fatal(now,agent,index,old,position,"post_install_index_or_next_link_mismatch candidate="+candidate);
            }
            step.installed++;
            retention.moved(position.vehicle().getId().toString()); // even a change downstream of the current movement invalidates its old evidence
          }
        }
        evidence(now,"zona1WithinDayReroute",agent,index,old,candidate,position,
            temporalRepair?"validated_temporal_repair":"validated_improvement",oldEstimate,candidateEstimate,enteredAt);
    }
    @Override public void notifyMobsimBeforeSimStep(MobsimBeforeSimStepEvent event) {
        evaluate(event.getSimulationTime(),qsim.getAgents().values());
    }
    void evaluate(double now,Collection<? extends MobsimAgent> agents) {
        if (!evaluationDue(now)) return;
        var step=new Step(); long wall=System.nanoTime(); var bean=ManagementFactory.getThreadMXBean();
        long cpu=bean.isCurrentThreadCpuTimeSupported()?bean.getCurrentThreadCpuTime():-1;
        timing=new StepTiming(scenario,iteration,now);String outcome="failed";
        try {
            if (!enabled) {outcome="disabled";return;}
            Set<Id<Link>> severe=new HashSet<>();
            for (Link link:scenario.getNetwork().getLinks().values()) {
                double nominal=Math.max(1,link.getLength()/link.getFreespeed());
                double estimate=link.getLength()/Math.max(.1,link.getFreespeed(now));
                double observed=observedLinkSeconds(link.getId(),now);
                if (!Double.isNaN(observed)) estimate=Math.max(estimate,observed);
                times.put(link.getId(),estimate);
                if (needsReroute(enabled,nominal,estimate,link.getCapacity(),link.getCapacity(now))) severe.add(link.getId());
            }
            turnTimes.clear();
            turnObservations.forEach((turn,observation)->{
                if (fresh(observation,now)) {
                    Link from=scenario.getNetwork().getLinks().get(turn.from());
                    double currentFreeflow=from.getLength()/Math.max(.1,from.getFreespeed(now));
                    turnTimes.put(turn,Math.max(currentFreeflow,observation.duration()));
                }
            });
            activeRetentions=measured(timing,"physical_queries",()->retained(network,safety,now));
            var candidates=new ArrayList<MobsimAgent>();
            for (MobsimAgent agent:agents) {
                if (!eligible(agent,now)) continue;
                var leg=WithinDayAgentUtils.getModifiableCurrentLeg(agent);
                if (leg==null || !(leg.getRoute() instanceof NetworkRoute route)) continue;
                var full=SimZ1RouteSafety.full(route); int index=WithinDayAgentUtils.getCurrentRouteLinkIdIndex(agent);
                String invalid=measured(timing,"context_validation",()->safety.validateReplacement(full,full,index,agent.getCurrentLinkId(),route.getEndLinkId(),null));
                if (invalid!=null) fatal(now,agent,index,full,null,invalid);
                if (index==full.size()-1) continue; // occurrence/index, not currentLinkId==endLinkId
                // Current-link age alone is insufficient: require a live, revalidated offered head.
                boolean impossible=false;
                var position=measured(timing,"physical_queries",()->locate((MobsimDriverAgent)agent));
                if(position!=null) {
                    var observation=temporalObservations.get(position.vehicle().getId());
                    if(observation==null||observation.route()!=route||observation.index()!=index||
                            !Objects.equals(observation.lane(),position.lane())) {
                        var person=scenario.getPopulation().getPersons().get(agent.getId());
                        var status=measured(timing,"context_validation",()->safety.temporal(full,index,person,position.vehicle().getVehicle(),position.lane(),true).status());
                        observation=new TemporalObservation(route,index,position.lane(),status);
                        temporalObservations.put(position.vehicle().getId(),observation);
                    }
                    impossible=observation.status()==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE;
                }
                if (impossible||triggered(full,index,severe,activeRetentions.containsKey(((MobsimDriverAgent)agent).getPlannedVehicleId().toString())))
                    candidates.add(agent);
            }
            step.candidates=candidates.size();
            var attempts=chooseAttempts(candidates);step.deferred=candidates.size()-attempts.size();
            // Same deterministic cyclic priority and per-evaluation budget.
            for (MobsimAgent agent:attempts) {
                cursor=agent.getId().toString();
                measured(timing,"context_validation",()->{attempt(agent,now,step);return null;});
            }
            outcome="completed";
        } finally {
            long elapsedCpu=cpu<0?-1:bean.getCurrentThreadCpuTime()-cpu;
            var data=new LinkedHashMap<>(Map.of("candidates",""+step.candidates,"calculations",""+step.calculations,
                "installed",""+step.installed,"rejected",""+step.rejected,"deferred",""+step.deferred,
                "budget",""+budget,"activeRetentions",""+activeRetentions.size(),"cpuNanos",""+elapsedCpu,"wallNanos",""+(System.nanoTime()-wall),"enabled",""+enabled));
            data.putAll(timing.snapshot());data.put("timingExcludesThisStepSummaryEmission","true");data.put("evaluationOutcome",outcome);
            try {emit(now,"zona1RerouteStep",data);}
            finally {lastTiming=timing.finish(outcome);timing=null;}
        }
    }
}
