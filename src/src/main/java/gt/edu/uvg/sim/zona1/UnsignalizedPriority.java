package gt.edu.uvg.sim.zona1;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.core.controler.Controler;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.qnetsimengine.*;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.api.core.v01.events.Event;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;

/** Stop at the queue head for five seconds, then yield to incoming avenues.
 * Uses QSim's WAIT decision, so no synthetic traffic lights enter the replay.
 */
public final class UnsignalizedPriority {
    public static final double STOP_SECONDS = 5;
    private UnsignalizedPriority() { }

    public static void configure(Controler controler) {
        ConfigUtils.addOrGetModule(controler.getConfig(),Zona1PriorityConfigGroup.class);
        controler.addOverridingModule(new org.matsim.core.controler.AbstractModule() {
            @Override public void install() {
                bind(Zona1NativeDiagnostics.class).asEagerSingleton();
                addEventHandlerBinding().to(Zona1NativeDiagnostics.class);
                addMobsimListenerBinding().to(Zona1NativeDiagnostics.class);
                addMobsimListenerBinding().to(SimZ1PassageTimeListener.class);
            }
        });
        controler.addOverridingQSimModule(new AbstractQSimModule() {
            @Override protected void configureQSim() {
                bind(QNetworkFactory.class).to(Zona1PriorityNetworkFactory.class);
            }
        });
    }

    /** Same road-mode coverage for queue decisions AND their policy evidence. */
    public static boolean roadLink(Link link) {
        return link.getAllowedModes().contains("car") || link.getAllowedModes().contains("bus");
    }

    static boolean horizontal(Link link) {
        var from = link.getFromNode().getCoord();
        var to = link.getToNode().getCoord();
        return Math.abs(to.getX()-from.getX()) > Math.abs(to.getY()-from.getY());
    }

    public record Classification(String role,String source) { }
    public static Classification classify(Link link,Zona1PriorityConfigGroup settings) {
        Object explicit=link.getAttributes().getAttribute("simz1:priorityRole");
        if(explicit!=null) {
            if(!Set.of("street","avenue").contains(explicit.toString())) throw new IllegalArgumentException("CONFIG_INVALID: priority role "+link.getId());
            return new Classification(explicit.toString(),"network_attribute");
        }
        if(settings.getClassification().equals("explicit")) throw new IllegalArgumentException("CONFIG_INVALID: missing explicit priority role "+link.getId());
        boolean hierarchy=settings.getClassification().equals("osm-hierarchy");
        String highway=Objects.toString(link.getAttributes().getAttribute("osm:highway"),"").toLowerCase(Locale.ROOT);
        // Priority is a reproducible modeling policy, not evidence of a surveyed stop sign.
        // Parking/service access remains secondary even when named after an avenue.
        if(hierarchy && Set.of("service","living_street").contains(highway))
            return new Classification("street","osm_highway_service_assumption");
        // An arterial calle is not a secondary street merely because its name says Calle.
        if(hierarchy && Set.of("motorway","motorway_link","trunk","trunk_link","primary","primary_link","secondary","secondary_link").contains(highway))
            return new Classification("avenue","osm_highway_major_assumption");
        if(hierarchy || settings.getClassification().equals("osm-name-orientation")) {
            String name=Objects.toString(link.getAttributes().getAttribute("osm:name"),"");
            name=java.text.Normalizer.normalize(name,java.text.Normalizer.Form.NFKD).replaceAll("\\p{M}","").toLowerCase(Locale.ROOT);
            Set<String> words=new HashSet<>(Arrays.asList(name.split("[^a-z]+")));
            boolean avenue=!Collections.disjoint(words,Set.of("avenida","bulevar","boulevard","calzada")), street=words.contains("calle");
            if(avenue!=street) return new Classification(avenue?"avenue":"street",hierarchy?"osm_name_assumption":"osm_name_synthetic_rule");
        }
        if(hierarchy && Set.of("tertiary","tertiary_link","residential","unclassified").contains(highway))
            return new Classification("street","osm_highway_minor_assumption");
        return new Classification(horizontal(link)?"street":"avenue","orientation_approximation");
    }

    public static boolean eligible(Node node, Set<Id<Node>> controlled) {
        return eligible(node,controlled,new Zona1PriorityConfigGroup());
    }
    public static boolean eligible(Node node,Set<Id<Node>> controlled,Zona1PriorityConfigGroup settings) {
        if(!Boolean.parseBoolean(settings.getEnabled())) return false;
        if (controlled.contains(node.getId()) ||
            "traffic_signals".equals(node.getAttributes().getAttribute("osm:highway")) ||
            "traffic_signals".equals(node.getAttributes().getAttribute("highway"))) return false;
        var incoming = node.getInLinks().values().stream()
            .filter(l -> roadLink(l)).toList();
        return incoming.stream().anyMatch(l->classify(l,settings).role.equals("street")) &&
            incoming.stream().anyMatch(l->classify(l,settings).role.equals("avenue"));
    }

    /** These are modeled controls; an absent attribute is not evidence of a field sign. */
    public static String control(Link link,Zona1PriorityConfigGroup settings) {
        Object explicit=link.getAttributes().getAttribute("simz1:priorityControl");
        if(explicit!=null && !Set.of("stop","yield").contains(explicit.toString()))
            throw new IllegalArgumentException("CONFIG_INVALID: priority control "+link.getId());
        if(!classify(link,settings).role().equals("street")) {
            if(explicit!=null) throw new IllegalArgumentException("CONFIG_INVALID: street control on priority avenue "+link.getId());
            return "free";
        }
        return explicit==null?"stop":explicit.toString();
    }

    public static final class StopAndYield implements TurnAcceptanceLogic {
        private record Stop(QVehicle vehicle,double headTime,double ready,long visit) { }
        private record Reservation(QLaneI lane,QVehicle vehicle,PriorityMovements.Movement movement,double ready) { }
        private final Map<QLaneI, Stop> heads = new IdentityHashMap<>();
        private final List<Id<Link>> avenues;
        private final Map<Id<Link>,Classification> roles=new HashMap<>();
        private final TurnAcceptanceLogic delegate = new DefaultTurnAcceptanceLogic();
        private final Node node;
        private final Zona1PriorityConfigGroup settings;
        private final PriorityMovements conflicts;
        private final EventsManager events;
        private final SimZ1RouteSafety routeSafety;
        private final org.matsim.core.config.groups.QSimConfigGroup receiverConfig;
        private final List<PriorityMovements.Movement> crossed=new ArrayList<>();
        private Reservation reservation;
        private double step=Double.NEGATIVE_INFINITY;
        private long visits;
        private String lastWaitReason = "priority_yield";
        private PriorityMovements.Movement blockingMovement;

        /** Node-local diagnostic; read immediately after this node's turn decision. */
        public String getLastWaitReason() { return lastWaitReason; }

        public StopAndYield(Node node) {
            this(node,new Zona1PriorityConfigGroup(),null);
        }
        public StopAndYield(Node node,Zona1PriorityConfigGroup settings,EventsManager events) {
            this(node,settings,events,null);
        }
        public StopAndYield(Node node,Zona1PriorityConfigGroup settings,EventsManager events,SimZ1RouteSafety routeSafety) {
            this(node,settings,events,routeSafety,null);
        }
        public StopAndYield(Node node,Zona1PriorityConfigGroup settings,EventsManager events,SimZ1RouteSafety routeSafety,
                org.matsim.core.config.groups.QSimConfigGroup receiverConfig) {
            this.node=node; this.settings=settings; this.events=events;
            this.routeSafety=routeSafety;
            this.receiverConfig=receiverConfig;
            conflicts=new PriorityMovements(node,settings);
            for(var link:node.getInLinks().values()) if(roadLink(link)) roles.put(link.getId(),classify(link,settings));
            avenues = node.getInLinks().values().stream()
                .filter(l -> roadLink(l) && classify(l,settings).role.equals("avenue"))
                .map(Link::getId).sorted(Comparator.comparing(Object::toString)).toList();
        }

        private boolean street(Link link){return roles.get(link.getId()).role.equals("street");}
        private double stopSeconds(Link link) {return control(link,settings).equals("stop")?Math.max(STOP_SECONDS,settings.getStopSeconds()):0;}
        /** Passage lookahead never inserts a fictitious queue head. Required
         * stops are accumulated at the upstream holding point before locking
         * the connector; real conflicting offered approaches still have priority. */
        public double passageStopSeconds(Link link){return stopSeconds(link);}
        public record PassageDecision(String reason,List<QVehicle> blockers) {
            public boolean permitted(){return reason.equals("passage_priority_clear");}
        }
        private PassageDecision lastPassageDecision=new PassageDecision("not_queried",List.of());
        public PassageDecision getLastPassageDecision(){return lastPassageDecision;}
        /** Readiness of an actual head, using the same stop clock as local GO. */
        public boolean passageHeadReady(Link from,QLaneI lane,QVehicle vehicle,QNetwork network,double now){
            observeHeads(network,now);var stop=heads.get(lane);
            return stop!=null&&stop.vehicle==vehicle&&!lane.isNotOfferingVehicle()&&lane.getFirstVehicle()==vehicle&&now>=stop.ready;
        }
        public boolean passageMayProceed(Link link,Id<Link> next,QVehicle vehicle,QNetwork network,double now) {
            lastPassageDecision=passageDecision(link,next,vehicle,network,now);
            return lastPassageDecision.permitted();
        }
        private PassageDecision passageDecision(Link link,Id<Link> next,QVehicle vehicle,QNetwork network,double now) {
            observeHeads(network,now);var movement=new PriorityMovements.Movement(link.getId(),next);
            if(crossed.stream().anyMatch(prior->conflicts.conflicts(movement,prior)))return new PassageDecision("priority_conflict_executed",List.of());
            if(reservation!=null&&reservation.vehicle!=vehicle&&conflicts.conflicts(movement,reservation.movement)&&
                    canCompete(node.getInLinks().get(reservation.movement.from()),reservation.lane,reservation.movement.to(),network,now))return new PassageDecision("priority_fairness",List.of(reservation.vehicle));
            // A granted fairness turn has the same meaning for a reserved
            // short-link passage as for an ordinary turn below.
            var blockers=new ArrayList<QVehicle>();
            if(street(link)&&(reservation==null||reservation.vehicle!=vehicle))for(var avenue:avenues)for(var offered:network.getNetsimLinks().get(avenue).getOfferingQLanes()) {
                if(offered.isNotOfferingVehicle())continue;var head=offered.getFirstVehicle();var target=head.getDriver().chooseNextLinkId();
                if(head!=vehicle&&target!=null&&canCompete(node.getInLinks().get(avenue),offered,target,network,now)&&
                        conflicts.conflicts(movement,new PriorityMovements.Movement(avenue,target))&&
                        !SimZ1CorridorOccupancy.sameParallelPassageEntrance(receiverConfig,vehicle,head,link.getId(),next))blockers.add(head);
            }
            return new PassageDecision(blockers.isEmpty()?"passage_priority_clear":"priority_yield_conflict",List.copyOf(blockers));
        }
        /** The real queue head consumes a stop credit already held upstream.
         * Keep its native head/ready times unchanged so the audit must verify
         * the ACQUIRE receipt instead of treating this as a local stop. */
        public AcceptTurn passagePermission(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,double now,Map<String,String> proof) {
            if(lane.isNotOfferingVehicle()||lane.getFirstVehicle()!=vehicle)throw new IllegalStateException("Passage permission outside real queue head");
            head(link,lane,vehicle,now);
            double credit=Double.parseDouble(proof.get("passageStopCreditSeconds"));
            if(Math.abs(credit-stopSeconds(link))>1e-8)throw new IllegalStateException("Passage priority credit differs from control");
            record(link,lane,next,vehicle,now,"GO","preauthorized_passage",proof);return AcceptTurn.GO;
        }
        private Stop head(Link link,QLaneI lane,QVehicle vehicle,double now) {
            Stop stop=heads.get(lane);
            if(stop==null||stop.vehicle!=vehicle) {
                stop=new Stop(vehicle,now,now+stopSeconds(link),++visits);
                heads.put(lane,stop);
                record(link,lane,vehicle.getDriver().chooseNextLinkId(),vehicle,now,"HEAD","queue_head");
            }
            return stop;
        }
        public void observeHeads(QNetwork network,double now) {
            boolean newStep=step!=now;
            if(newStep){step=now;crossed.clear();reservation=null;}
            for(var link:node.getInLinks().values()) if(roadLink(link))
                for(var lane:network.getNetsimLinks().get(link.getId()).getOfferingQLanes())
                    if(!lane.isNotOfferingVehicle()) head(link,lane,lane.getFirstVehicle(),now);
            if(newStep && settings.getMaxYieldSeconds()>0) {
                // Select before any crossing this step. Reservation only lasts this
                // node step and never overrides red, forbidden turns or storage.
                // Stable ordering makes equal-age choices independent of hash maps.
                for(var link:node.getInLinks().values().stream().filter(l->roadLink(l)&&street(l))
                        .sorted(Comparator.comparing(l->l.getId().toString())).toList())
                    for(var lane:network.getNetsimLinks().get(link.getId()).getOfferingQLanes().stream()
                            .sorted(Comparator.comparing(l->l.getId().toString())).toList()) {
                        if(lane.isNotOfferingVehicle()) continue;
                        var stop=heads.get(lane); var next=stop.vehicle.getDriver().chooseNextLinkId();
                        if(now-stop.ready<settings.getMaxYieldSeconds() || !canCompete(link,lane,next,network,now)) continue;
                        if(reservation==null || stop.ready<reservation.ready)
                            reservation=new Reservation(lane,stop.vehicle,new PriorityMovements.Movement(link.getId(),next),stop.ready);
                    }
            }
        }
        private boolean canCompete(Link link,QLaneI lane,Id<Link> next,QNetwork network,double now) {
            if(next==null || lane.isNotOfferingVehicle()) return false;
            var target=network.getNetsimLinks().get(next);
            var observed=heads.get(lane);
            return observed!=null && lane.getFirstVehicle()==observed.vehicle && now>=observed.ready &&
                target!=null && target.getLink().getFromNode()==node && roadLink(target.getLink()) &&
                (routeSafety==null || routeSafety.laneAllowsVehicle(link.getId(),lane.getId(),next,observed.vehicle.getId())) &&
                (!(lane instanceof SignalizeableItem signal)||signal.hasGreenForToLink(next)) &&
                SimZ1CorridorOccupancy.receiverFeasibility(receiverConfig,observed.vehicle,next,
                    target.getAcceptingQLane().getId().toString(),network,now).feasible();
        }
        private AcceptTurn decide(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,double now,AcceptTurn value,String reason) {
            lastWaitReason=reason;
            record(link,lane,next,vehicle,now,value.name(),reason);
            return value;
        }
        private void record(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,double now,String action,String reason) {
            record(link,lane,next,vehicle,now,action,reason,Map.of());
        }
        private void record(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,double now,String action,String reason,Map<String,String> proof) {
            if(events==null) return;
            var stop=heads.get(lane); var role=roles.get(link.getId());
            var values=new LinkedHashMap<String,String>();
            values.put("node",node.getId().toString()); values.put("link",link.getId().toString());
            values.put("nextLink",next==null?"":next.toString());values.put("lane",lane.getId().toString());
            values.put("person",vehicle.getDriver().getId().toString());values.put("vehicle",vehicle.getId().toString());
            values.put("action",action);values.put("reason",reason);values.put("role",role.role);values.put("classificationSource",role.source);
            values.put("headTime",stop==null?"unknown":Double.toString(stop.headTime));
            values.put("readyTime",stop==null?"unknown":Double.toString(stop.ready));values.put("visit",stop==null?"unknown":Long.toString(stop.visit));
            values.put("stopSeconds",Double.toString(settings.getStopSeconds()));values.put("conflictPolicy",settings.getConflicts());
            values.put("control",control(link,settings));values.put("appliedStopSeconds",Double.toString(stopSeconds(link)));
            values.put("maxYieldSeconds",Double.toString(settings.getMaxYieldSeconds()));
            values.put("readyWaitSeconds",stop==null?"0":Double.toString(Math.max(0,now-stop.ready)));
            values.put("reservationVehicle",reservation==null?"":reservation.vehicle.getId().toString());
            values.put("reservationAge",reservation==null?"0":Double.toString(now-reservation.ready));
            if(action.equals("WAIT") && blockingMovement!=null) {
                values.put("blockingFromLink",blockingMovement.from().toString());
                values.put("blockingNextLink",blockingMovement.to().toString());
                values.put("conflictEvidence",conflicts.evidence(new PriorityMovements.Movement(link.getId(),next),blockingMovement));
            }
            values.putAll(proof);
            events.processEvent(new Event(now){@Override public String getEventType(){return "simz1Priority";}
                @Override public Map<String,String> getAttributes(){var attrs=super.getAttributes();attrs.putAll(values);return attrs;}});
        }
        public void storageWait(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,double now) {
            record(link,lane,next,vehicle,now,"WAIT","storage_wait");
        }
        public void crossed(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,QNetwork network,double now,boolean forced) {
            crossed(link,lane,next,vehicle,network,now,forced,Map.of());
        }
        public void crossedPassage(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,QNetwork network,double now,Map<String,String> proof) {
            crossed(link,lane,next,vehicle,network,now,false,proof);
        }
        private void crossed(Link link,QLaneI lane,Id<Link> next,QVehicle vehicle,QNetwork network,double now,boolean forced,Map<String,String> proof) {
            crossed.add(new PriorityMovements.Movement(link.getId(),next));
            record(link,lane,next,vehicle,now,"CROSS",proof.isEmpty()?(forced?"storage_forced_move":"executed"):"preauthorized_passage",proof);
            heads.remove(lane);
            if(reservation!=null && reservation.vehicle==vehicle) reservation=null;
            if(!lane.isNotOfferingVehicle()) head(link,lane,lane.getFirstVehicle(),now);
        }

        @Override public AcceptTurn isAcceptingTurn(Link link, QLaneI lane, Id<Link> next,
                QVehicle vehicle, QNetwork network, double now) {
            blockingMovement=null;
            var decision = delegate.isAcceptingTurn(link, lane, next, vehicle, network, now);
            if (decision != AcceptTurn.GO) return decision;
            observeHeads(network,now);
            var stop=head(link,lane,vehicle,now);
            if(routeSafety!=null && !routeSafety.laneAllowsVehicle(link.getId(),lane.getId(),next,vehicle.getId()))
                return decide(link,lane,next,vehicle,now,AcceptTurn.ABORT,"turn_restriction");
            if(lane instanceof SignalizeableItem signal && !signal.hasGreenForToLink(next))
                return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,"signal_not_green");
            if(now<stop.ready) return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,"priority_stop");
            var target=network.getNetsimLinks().get(next);
            var physical=SimZ1CorridorOccupancy.receiverFeasibility(receiverConfig,vehicle,next,
                target.getAcceptingQLane().getId().toString(),network,now);
            if(!physical.feasible())return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,physical.reason());
            var movement=new PriorityMovements.Movement(link.getId(),next);
            blockingMovement=crossed.stream().filter(prior->conflicts.conflicts(movement,prior)).findFirst().orElse(null);
            if(blockingMovement!=null)
                return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,"priority_conflict_executed");
            if(reservation!=null && reservation.vehicle!=vehicle && conflicts.conflicts(movement,reservation.movement) &&
                    canCompete(node.getInLinks().get(reservation.movement.from()),reservation.lane,reservation.movement.to(),network,now)) {
                blockingMovement=reservation.movement;
                return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,"priority_fairness");
            }
            if(street(link) && (reservation==null || reservation.vehicle!=vehicle)) for(var avenue:avenues) for(var offered:network.getNetsimLinks().get(avenue).getOfferingQLanes()) {
                if(offered.isNotOfferingVehicle()) continue;
                QVehicle first=offered.getFirstVehicle(); Id<Link> destination=first.getDriver().chooseNextLinkId();
                if(destination==null) continue;
                // Only a permitted, offered and physically executable movement
                // competes. A car merely present on an avenue reserves nothing.
                if(!canCompete(node.getInLinks().get(avenue),offered,destination,network,now)) continue;
                var prior=new PriorityMovements.Movement(avenue,destination);
                if(!conflicts.conflicts(movement,prior)) continue;
                if(crossed.stream().anyMatch(done->conflicts.conflicts(prior,done))) continue;
                blockingMovement=prior;
                return decide(link,lane,next,vehicle,now,AcceptTurn.WAIT,"priority_yield_conflict");
            }
            return decide(link,lane,next,vehicle,now,AcceptTurn.GO,"permission_not_crossing");
        }
    }
}
