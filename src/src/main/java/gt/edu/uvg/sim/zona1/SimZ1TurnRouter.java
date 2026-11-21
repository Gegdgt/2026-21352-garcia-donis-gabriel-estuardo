package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.router.util.*;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.Vehicle;

/** Dijkstra over allowed link movements and estimated times, not merely shared nodes.
 * Time-dependent non-FIFO estimates do not establish a global fastest-route guarantee.
 */
final class SimZ1TurnRouter {
    private final Network network;
    private final SimZ1RouteSafety safety;
    private final TravelTime times;
    private final LinkToLinkTravelTime turns;
    private final String policy;
    SimZ1TurnRouter(Network network, SimZ1RouteSafety safety, TravelTime times) {
        this(network,safety,times,null,DrivingProfiles.FASTEST_TIME);
    }
    SimZ1TurnRouter(Network network, SimZ1RouteSafety safety, TravelTime times,
            LinkToLinkTravelTime turns, String policy) {
        this.network=network; this.safety=safety; this.times=DrivingProfiles.expectedTimes(times);
        this.turns=turns;
        this.policy=DrivingProfiles.validatePolicy(policy);
    }
    private record State(Id<Link> id,int progress,boolean initial,Set<Id<Link>> visitedVias,SimZ1TripOd.Progress od,
                         List<Id<Link>> passage,boolean initialPassage) { }
    private record Label(State state, double cost, double time) { }
    record Estimate(double seconds, double cost) { }
    private record Weight(double seconds, double cost) { }

    private static void validateTime(double now,double enteredAt) {
        if (!Double.isFinite(now) || (!Double.isNaN(enteredAt) && (!Double.isFinite(enteredAt) || enteredAt>now)))
            throw new IllegalArgumentException("Invalid routing clock or current-link entry time");
    }
    /** A turn contains the from-link traversal; never add the from-link time again. */
    private Weight weight(Id<Link> from,Id<Link> to,double now,Person person,Vehicle vehicle,double enteredAt) {
        Link link=network.getLinks().get(from),target=network.getLinks().get(to);
        double departure=Double.isNaN(enteredAt)?now:enteredAt;
        double observed=turns==null?Double.NaN:turns.getLinkToLinkTravelTime(link,target,departure,person,vehicle);
        // An absent movement observation retains the link estimate, including its observed delay.
        double full=Double.isNaN(observed)?times.getLinkTravelTime(link,departure,person,vehicle):
            DrivingProfiles.expectedTime(link,departure,person,vehicle,observed);
        // This is a remaining-time estimate, not an observed future departure.
        // When entry is unknown (e.g. the partial departure link), use the full estimate.
        double remaining=Double.isNaN(enteredAt)?full:Math.max(0,full-(now-enteredAt));
        return new Weight(remaining,DrivingProfiles.cost(link,departure,person,vehicle,remaining,policy));
    }
    Estimate evaluate(List<Id<Link>> suffix,double now,Person person,Vehicle vehicle,double enteredAt) {
        validateTime(now,enteredAt);
        String invalid=safety.validateNetwork(suffix);
        if (invalid!=null) throw new IllegalArgumentException("Invalid evaluated route: "+invalid);
        double clock=now,cost=0;
        for (int i=0;i+1<suffix.size();i++) {
            var weight=weight(suffix.get(i),suffix.get(i+1),clock,person,vehicle,i==0?enteredAt:Double.NaN);
            clock+=weight.seconds(); cost+=weight.cost();
            if (!Double.isFinite(clock) || !Double.isFinite(cost))
                throw new IllegalStateException("Non-finite accumulated routing estimate");
        }
        return new Estimate(clock-now,cost);
    }
    List<Id<Link>> path(Id<Link> start, Id<Link> destination, double now, Person person, Vehicle vehicle) {
        return path(start,destination,now,person,vehicle,null,Double.NaN);
    }
    List<Id<Link>> path(Id<Link> start, Id<Link> destination, double now, Person person, Vehicle vehicle,
            Id<Lane> currentLane,double enteredAt) {
        return path(start,destination,now,person,vehicle,currentLane,enteredAt,List.of(start));
    }
    /** traversedPrefix includes the actual current occurrence. A within-day caller
     * must supply native history, never infer an occurrence with indexOf. */
    List<Id<Link>> path(Id<Link> start, Id<Link> destination, double now, Person person, Vehicle vehicle,
            Id<Lane> currentLane,double enteredAt,List<Id<Link>> traversedPrefix) {
        if (safety.tripOd().requires(person)) throw SimZ1TripOd.invalid("routing requires explicit trip context");
        return path(start,destination,now,person,vehicle,currentLane,enteredAt,traversedPrefix,null);
    }
    List<Id<Link>> path(Id<Link> start, Id<Link> destination, double now, Person person, Vehicle vehicle,
            Id<Lane> currentLane,double enteredAt,List<Id<Link>> traversedPrefix,SimZ1TripOd.Contract contract) {
        if (contract==null && safety.tripOd().requires(person)) throw SimZ1TripOd.invalid("missing routing trip context");
        validateTime(now,enteredAt);
        if (traversedPrefix==null || traversedPrefix.isEmpty() ||
            !start.equals(traversedPrefix.get(traversedPrefix.size()-1))) return null;
        if (safety.validateNetwork(traversedPrefix)!=null) return null;
        var od=contract==null?null:contract.progress(traversedPrefix);
        if (contract!=null && (od==null || !contract.destination.equals(destination))) return null;
        if (!network.getLinks().containsKey(start) || !network.getLinks().containsKey(destination)) return null;
        if (!network.getLinks().get(start).getAllowedModes().contains("car") ||
            !network.getLinks().get(destination).getAllowedModes().contains("car")) return null;
        if (safety.validateNetwork(List.of(start))!=null ||
            safety.validateNetwork(List.of(destination))!=null) return null;
        Map<State,Double> best=new HashMap<>();
        Map<State,State> previous=new HashMap<>();
        var queue=new PriorityQueue<Label>(Comparator.comparingDouble(Label::cost)
            .thenComparing(l->l.state().id().toString()).thenComparingInt(l->l.state().progress())
            .thenComparing(l->l.state().initial()));
        var initial=new State(start,safety.sequenceProgress(traversedPrefix),true,
            safety.sequenceVia(start)?Set.of(start):Set.of(),od,List.of(start),true);
        queue.add(new Label(initial,0,now)); best.put(initial,0.);
        while (!queue.isEmpty()) {
            Label label=queue.remove();
            if (label.cost()!=best.get(label.state())) continue;
            if (label.state().id().equals(destination) && (contract==null || contract.complete(label.state().od()))) {
                if(safety.temporal(label.state().passage(),0,person,vehicle,
                        label.state().initialPassage()?currentLane:null,true).status()==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE)continue;
                var result=new ArrayList<Id<Link>>();
                for (State state=label.state(); state!=null; state=previous.get(state)) result.add(state.id());
                Collections.reverse(result); return result;
            }
            for (Id<Link> id:safety.successors(label.state().id())) {
                if (label.state().visitedVias().contains(id)) continue;
                int progress=safety.advanceSequence(label.state().progress(),id);
                if (progress<0) continue;
                var nextOd=contract==null?null:contract.advance(label.state().od(),id);
                if (contract!=null && nextOd==null) continue;
                boolean first=label.state().initial();
                if (first && currentLane!=null && !safety.laneAllows(start,currentLane,id)) continue;
                var extended=new ArrayList<>(label.state().passage());extended.add(id);
                // Preserve the actual source lane for the whole pending initial
                // passage, including labels after its first connector.
                var passage=safety.temporal(extended,0,person,vehicle,
                    label.state().initialPassage()?currentLane:null,id.equals(destination));
                if(passage.status()==Zona1SignalGreenWindow.Feasibility.IMPOSSIBLE)continue;
                // A repeated link inside an unresolved passage cannot be a
                // native unambiguous receipt; stop expanding that cycle.
                if(label.state().passage().contains(id))continue;
                var weight=weight(label.state().id(),id,label.time(),person,vehicle,first?enteredAt:Double.NaN);
                double candidate=label.cost()+weight.cost();
                double arrival=label.time()+weight.seconds();
                if (!Double.isFinite(candidate) || !Double.isFinite(arrival))
                    throw new IllegalStateException("Non-finite accumulated routing estimate");
                // Retain this small extra bit of search history after leaving a
                // via: a cheaper arrival that already visited V cannot dominate
                // an alternative arrival that can still legally use V once.
                var visitedVias=label.state().visitedVias();
                if (safety.sequenceVia(id)) {
                    var copy=new HashSet<>(visitedVias); copy.add(id); visitedVias=Set.copyOf(copy);
                }
                var target=new State(id,progress,false,visitedVias,nextOd,passage.context(),
                    label.state().initialPassage()&&passage.context().size()==extended.size());
                if (candidate < best.getOrDefault(target,Double.POSITIVE_INFINITY)) {
                    best.put(target,candidate); previous.put(target,label.state());
                    queue.add(new Label(target,candidate,arrival));
                }
            }
        }
        return null;
    }
}
