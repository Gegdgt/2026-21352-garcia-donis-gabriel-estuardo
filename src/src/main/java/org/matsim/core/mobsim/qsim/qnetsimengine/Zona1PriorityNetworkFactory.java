package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import com.google.inject.Inject;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.interfaces.AgentCounter;
import gt.edu.uvg.sim.zona1.UnsignalizedPriority;
import gt.edu.uvg.sim.zona1.Zona1PriorityConfigGroup;
import org.matsim.vis.snapshotwriters.SnapshotLinkWidthCalculator;

// MATSim 15 exposes package-private QNodeI in QNetworkFactory's public API.
// Keep this small adapter in that package; policy lives in zona1.
public final class Zona1PriorityNetworkFactory implements QNetworkFactory {
    private final QSignalsNetworkFactory signals;
    private final Scenario scenario;
    private final EventsManager events;
    private final Zona1NativeDiagnostics diagnostics;
    private final SignalSystemsConfigGroup signalConfig;
    private final Zona1PriorityConfigGroup priorityConfig;
    private final gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup admissionConfig;
    private final gt.edu.uvg.sim.zona1.SimZ1RouteSafety routeSafety;
    private NetsimEngineContext context;
    private QNetsimEngineI.NetsimInternalInterface engine;
    private final Set<Id<Node>> controlled = new HashSet<>();

    @Inject public Zona1PriorityNetworkFactory(Scenario scenario, EventsManager events, Zona1NativeDiagnostics diagnostics) {
        this.scenario = scenario;
        this.events = events;
        this.diagnostics = diagnostics;
        signalConfig = ConfigUtils.addOrGetModule(scenario.getConfig(), SignalSystemsConfigGroup.class);
        priorityConfig = ConfigUtils.addOrGetModule(scenario.getConfig(),Zona1PriorityConfigGroup.class);
        admissionConfig = ConfigUtils.addOrGetModule(scenario.getConfig(),gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup.class);
        if(admissionConfig.getWholeVehicleReservation() && scenario.getConfig().qsim().getNumberOfThreads()!=1)
            throw new IllegalArgumentException("corridor-length-v1 occupancy requires one QSim thread");
        if(admissionConfig.getWholeVehicleReservation()&&!admissionConfig.isStrict())
            throw new IllegalArgumentException("corridor-length-v1 occupancy requires strict admission");
        routeSafety = new gt.edu.uvg.sim.zona1.SimZ1RouteSafety(scenario);
        // A supplied table is validated even at an excluded node. Do not silently
        // ignore malformed experimental inputs when priority/signals are toggled.
        for(var node:scenario.getNetwork().getNodes().values())
            if(node.getAttributes().getAttribute("simz1:nonConflictingMovements")!=null)
                new gt.edu.uvg.sim.zona1.PriorityMovements(node,priorityConfig);
        signals = new QSignalsNetworkFactory(scenario, events);
        var data = (SignalsData) scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
        if (signalConfig.isUseSignalSystems() && data != null) for (var system : data.getSignalSystemsData().getSignalSystemData().values())
            for (var signal : system.getSignalData().values()) {
                var link = scenario.getNetwork().getLinks().get(signal.getLinkId());
                if (link != null) controlled.add(link.getToNode().getId());
            }
    }

    @Override public void initializeFactory(AgentCounter counter, MobsimTimer timer,
            QNetsimEngineI.NetsimInternalInterface engine) {
        signals.initializeFactory(counter, timer, engine);
        this.engine = engine;
        var widths = new SnapshotLinkWidthCalculator();
        widths.setLinkWidthForVis(scenario.getConfig().qsim().getLinkWidthForVis());
        widths.setLaneWidth(scenario.getNetwork().getEffectiveLaneWidth());
        var snapshots = AbstractQNetsimEngine.createAgentSnapshotInfoBuilder(scenario, widths);
        context = new NetsimEngineContext(events, scenario.getNetwork().getEffectiveCellSize(), counter,
            snapshots, scenario.getConfig().qsim(), timer, widths);
        if(admissionConfig.getWholeVehicleReservation()) {
            var occupancy=new SimZ1CorridorOccupancy(scenario,controlled,events);
            SimZ1CorridorOccupancy.install(scenario.getConfig().qsim(),occupancy);
            occupancy.emitDomains(scenario.getConfig().qsim().getStartTime().orElse(0));
        } else SimZ1CorridorOccupancy.uninstall(scenario.getConfig().qsim());
    }

    @Override public QNodeI createNetsimNode(Node node) {
        TurnAcceptanceLogic logic;
        // Each node owns its priority state; a new QSim factory is created each iteration.
        boolean eligible=UnsignalizedPriority.eligible(node,controlled,priorityConfig);
        if (eligible) logic = new UnsignalizedPriority.StopAndYield(node,priorityConfig,events,routeSafety,scenario.getConfig().qsim());
        else if (!signalConfig.isUseSignalSystems()) logic = new DefaultTurnAcceptanceLogic();
        else if (signalConfig.getIntersectionLogic() == SignalSystemsConfigGroup.IntersectionLogic.CONFLICTING_DIRECTIONS_AND_TURN_RESTRICTIONS) {
            var data = (SignalsData) scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
            logic = new UnprotectedLeftTurnAcceptanceLogic(data.getConflictingDirectionsData(), scenario.getLanes());
        } else logic = new SignalTurnAcceptanceLogic();
        double time=scenario.getConfig().qsim().getStartTime().orElse(0);
        for(var link:node.getInLinks().values()) if(UnsignalizedPriority.roadLink(link)) {
            var role=UnsignalizedPriority.classify(link,priorityConfig);
            var values=new LinkedHashMap<>(Map.of("node",node.getId().toString(),"link",link.getId().toString(),
                "enabled",priorityConfig.getEnabled(),"eligible",Boolean.toString(eligible),
                "stopSeconds",Double.toString(priorityConfig.getStopSeconds()),"role",role.role(),
                "classificationSource",role.source(),"conflictPolicy",priorityConfig.getConflicts(),
                "controlled",Boolean.toString(controlled.contains(node.getId()))));
            values.put("policyCoverage","car-bus-v2");
            String control=UnsignalizedPriority.control(link,priorityConfig);
            values.put("control",control);
            values.put("controlSource",link.getAttributes().getAttribute("simz1:priorityControl")==null?"modeled_default":"network_attribute");
            values.put("appliedStopSeconds",Double.toString(eligible&&control.equals("stop")?Math.max(UnsignalizedPriority.STOP_SECONDS,priorityConfig.getStopSeconds()):0));
            values.put("maxYieldSeconds",Double.toString(priorityConfig.getMaxYieldSeconds()));
            events.processEvent(new org.matsim.api.core.v01.events.Event(time) {
                @Override public String getEventType(){return "simz1PriorityPolicy";}
                @Override public Map<String,String> getAttributes(){var attrs=super.getAttributes();attrs.putAll(values);return attrs;}
            });
        }
        var builder = new Zona1QNodeImpl.Builder(engine, context, scenario.getConfig().qsim(), diagnostics);
        builder.setTurnAcceptanceLogic(logic);
        builder.setRouteSafety(routeSafety);
        builder.setAdmissionPolicy(admissionConfig, priorityConfig);
        var result=builder.build(node);
        var occupancy=SimZ1CorridorOccupancy.get(scenario.getConfig().qsim());if(occupancy!=null)occupancy.registerNode(result);
        return result;
    }

    @Override public QLinkI createNetsimLink(Link link, QNodeI node) {
        var queue=signals.createNetsimLink(link, node); // preserve QLinkLanesImpl
        diagnostics.registerQueueLink(queue);
        return queue;
    }
}

