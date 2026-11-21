package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.controler.listener.IterationStartsListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;

/** Small native QSim cases: two iterations each, same inputs for 1/4 threads. */
public final class PriorityMatrixCheck {
    record Person(String id,double departure,List<String> route) { }
    record Result(String label,int persons,Map<Integer,List<Map<String,String>>> events) { }
    static boolean disjoint(String name) { return name.endsWith("nonconflict"); }
    static boolean nativeSignals(String name) { return name.equals("native-signal")||name.startsWith("avenue-signal-"); }
    static void require(boolean condition,String message){if(!condition) throw new AssertionError(message);}
    public static void main(String[] args) throws Exception {
        Zona1Logging.configure();
        try {
            Path root=Files.createTempDirectory(Path.of("target"),"priority-matrix-");
            var summaries=new ArrayList<String>(); summaries.add("case\tthreads\titeration\tvehicle\thead\tready\tcross\twait_seconds");
            var operations=new ArrayList<String>(); operations.add("case\tthreads\titeration\tpersons\tarrived\tpending\tpriority_crossings\tpending_heads\tforced_moves\tnative_wait_reasons");
            var names=List.of("alone","avenue-free","avenue-congestion","yield-only","consecutive","conflict","nonconflict","geometric-nonconflict","conservative-nonconflict","sustained-priority","blocked-avenue","blocked-street","repeat","tagged-signal","native-signal","avenue-signal-red","avenue-signal-green","disabled");
            if(args.length>0) names=Arrays.asList(args);
            for(String name:names)
                for(int threads:List.of(1,4)) {
                    Result result=run(root,name,threads);
                    check(result,name,threads,summaries,operations);
                    Files.write(root.resolve("evidence.tsv"),summaries);
                    Files.write(root.resolve("operations.tsv"),operations);
                    System.out.println("PASS priority matrix "+result.label);
                }
            System.out.println("PASS "+names.size()*2+" small controllers x 2 iterations; native HEAD/GO/CROSS plus LinkLeave/LinkEnter; evidence="+root);
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
    static Result run(Path root,String name,int threads) throws Exception {
        String label=name+"-threads-"+threads; Path folder=root.resolve(label); Files.createDirectories(folder);
        var settings=new Zona1PriorityConfigGroup();
        settings.setEnabled(Boolean.toString(!name.equals("disabled")));
        if(name.equals("nonconflict")) settings.setConflicts("verified-node-table");
        if(name.equals("conservative-nonconflict")) settings.setConflicts("conservative");
        if(name.equals("sustained-priority")) settings.setMaxYieldSeconds(6);
        var config=ConfigUtils.createConfig(new SignalSystemsConfigGroup(),settings);
        config.global().setRandomSeed(20261015); config.global().setNumberOfThreads(threads);
        config.controler().setOutputDirectory(folder.resolve("run").toString()); config.controler().setLastIteration(1);
        config.controler().setWriteEventsInterval(1); config.controler().setWritePlansInterval(1);
        config.qsim().setStartTime(0); config.qsim().setEndTime(150); config.qsim().setNumberOfThreads(threads);
        config.qsim().setUsingFastCapacityUpdate(false); config.qsim().setRemoveStuckVehicles(false);
        // This fixture isolates storage wait from MATSim's forced-overfill fallback.
        // The production threshold is not altered; the entire test lasts < 1000 s.
        config.qsim().setStuckTime(1000);
        config.controler().setLinkToLinkRoutingEnabled(true);
        config.travelTimeCalculator().setCalculateLinkToLinkTravelTimes(true);config.travelTimeCalculator().setSeparateModes(false);
        for(String type:List.of("home","work")) {
            var activity=new ActivityParams(type);activity.setTypicalDuration(3600);activity.setScoringThisActivityAtAll(false);config.planCalcScore().addActivityParams(activity);
        }
        var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);config.strategy().addStrategySettings(strategy);
        var scenario=ScenarioUtils.createScenario(config); var net=scenario.getNetwork();
        double[][] xy={{-30,0},{-15,0},{0,0},{15,0},{0,-30},{0,-15},{0,15},{30,0},{0,30},{-30,30},{-15,15}};
        for(int i=0;i<xy.length;i++) net.addNode(net.getFactory().createNode(Id.createNodeId(i),new Coord(xy[i][0],xy[i][1])));
        String[] ids={"sw","w","e","ee","ss","s","n","nn","sb","b","loop"};
        int[][] edges={{0,1},{1,2},{2,3},{3,7},{4,5},{5,2},{2,6},{6,8},{9,10},{10,2},{3,1}};
        for(int i=0;i<ids.length;i++) {
            var link=net.getFactory().createLink(Id.createLinkId(ids[i]),net.getNodes().get(Id.createNodeId(edges[i][0])),net.getNodes().get(Id.createNodeId(edges[i][1])));
            link.setLength(7.5);link.setFreespeed(15);link.setNumberOfLanes(1);link.setCapacity(3600);link.setAllowedModes(Set.of("car"));
            link.getAttributes().putAttribute("simz1:priorityRole",ids[i].equals("w")?"street":"avenue");
            net.addLink(link);
        }
        var center=net.getNodes().get(Id.createNodeId(2));
        if(name.equals("tagged-signal")||nativeSignals(name)) center.getAttributes().putAttribute("osm:highway","traffic_signals");
        if(name.equals("nonconflict")) center.getAttributes().putAttribute("simz1:nonConflictingMovements","w>n|s>e");
        if(name.equals("yield-only")) net.getLinks().get(Id.createLinkId("w")).getAttributes().putAttribute("simz1:priorityControl","yield");
        if(name.equals("avenue-congestion")) {
            var approach=net.getLinks().get(Id.createLinkId("s"));
            approach.setLength(30);approach.setCapacity(360);
        }
        if(name.startsWith("blocked-")) {
            var target=net.getLinks().get(Id.createLinkId(name.equals("blocked-avenue")?"n":"e"));
            target.setFreespeed(.15); target.setCapacity(72);
            // 50 s free travel * .02 veh/s = one storage cell, avoiding native
            // storage expansion (a high flow capacity would invalidate this fixture).
        }
        var persons=new ArrayList<Person>();
        if(!name.startsWith("avenue-")) persons.add(new Person("street",1,name.equals("repeat")?List.of("sw","w","e","loop","w","e","ee"):
            disjoint(name)?List.of("sw","w","n","nn"):List.of("sw","w","e","ee")));
        if(name.equals("consecutive")) persons.add(new Person("street2",1,List.of("sw","w","e","ee")));
        if(Set.of("conflict","nonconflict","geometric-nonconflict","conservative-nonconflict","blocked-avenue").contains(name)||name.startsWith("avenue-"))
            persons.add(new Person("avenue",name.equals("avenue-signal-red")?50:name.startsWith("avenue-")?1:6,
                disjoint(name)?List.of("ss","s","e","ee"):List.of("ss","s","n","nn")));
        if(name.equals("sustained-priority")) for(int i=0;i<12;i++) persons.add(new Person("avenue"+i,6+i,List.of("ss","s","n","nn")));
        if(name.equals("avenue-congestion")) for(int i=0;i<3;i++) persons.add(new Person("following"+i,2+i,List.of("ss","s","n","nn")));
        if(name.startsWith("blocked-")) persons.add(new Person("blocker",0,name.equals("blocked-avenue")?
            List.of("sb","b","n","nn"):List.of("sb","b","e","ee")));
        var pf=scenario.getPopulation().getFactory();
        for(var p:persons) {
            var person=pf.createPerson(Id.createPersonId(p.id));var plan=pf.createPlan();
            var home=pf.createActivityFromLinkId("home",Id.createLinkId(p.route.get(0)));home.setEndTime(p.departure);plan.addActivity(home);
            plan.addLeg(pf.createLeg("car"));plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId(p.route.get(p.route.size() - 1))));
            person.addPlan(plan);scenario.getPopulation().addPerson(person);
        }
        Runnable restore=()->{for(var p:persons){var route=RouteUtils.createLinkNetworkRouteImpl(Id.createLinkId(p.route.get(0)),Id.createLinkId(p.route.get(p.route.size() - 1)));
            route.setLinkIds(route.getStartLinkId(),p.route.subList(1,p.route.size()-1).stream().map(Id::createLinkId).toList(),route.getEndLinkId());
            ((Leg)scenario.getPopulation().getPersons().get(Id.createPersonId(p.id)).getSelectedPlan().getPlanElements().get(1)).setRoute(route);}};
        restore.run();
        new org.matsim.api.core.v01.population.PopulationWriter(scenario.getPopulation()).write(folder.resolve("input-plans.xml").toString());
        new org.matsim.core.network.io.NetworkWriter(net).write(folder.resolve("input-network.xml").toString());
        var events=new TreeMap<Integer,List<Map<String,String>>>();var iteration=new AtomicInteger();
        BasicEventHandler handler=event->{if(event.getEventType().startsWith("simz1Priority")||event.getEventType().equals("simz1NativeDecision")||event.getEventType().equals("signalGroupStateChangedEvent")||event instanceof LinkLeaveEvent||event instanceof LinkEnterEvent||event instanceof PersonStuckEvent||event instanceof PersonArrivalEvent)
            events.computeIfAbsent(iteration.get(),k->new ArrayList<>()).add(new LinkedHashMap<>(event.getAttributes()));};
        if(nativeSignals(name)) {
            TrafficLightsGenerator.build(scenario);
            var signalConfig=ConfigUtils.addOrGetModule(config,SignalSystemsConfigGroup.class);
            TrafficLightsGenerator.write(scenario,folder);
            signalConfig.setSignalSystemFile(folder.resolve("signalSystems.xml").toAbsolutePath().toString());
            signalConfig.setSignalGroupsFile(folder.resolve("signalGroups.xml").toAbsolutePath().toString());
            signalConfig.setSignalControlFile(folder.resolve("signalControl.xml").toAbsolutePath().toString());
            ((org.matsim.core.scenario.MutableScenario)scenario).removeScenarioElement(org.matsim.contrib.signals.data.SignalsData.ELEMENT_NAME);
            scenario.addScenarioElement(org.matsim.contrib.signals.data.SignalsData.ELEMENT_NAME,new org.matsim.contrib.signals.data.SignalsDataLoader(config).loadSignalsData());
        }
        var controler=new Controler(scenario);
        if(nativeSignals(name)) RunZona1Simulation.configureSignals(controler); else UnsignalizedPriority.configure(controler);
        controler.addControlerListener((IterationStartsListener)e->{iteration.set(e.getIteration());restore.run();});
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){addEventHandlerBinding().toInstance(handler);}});
        controler.run();return new Result(label,persons.size(),events);
    }
    static void check(Result result,String name,int threads,List<String> summary,List<String> operations) {
        require(result.events.size()==2,"missing iterations");
        for(var entry:result.events.entrySet()) {
            var events=entry.getValue(); String context=result.label+" iteration "+entry.getKey();
            require(events.stream().noneMatch(e->e.get("type").equals("stuckAndAbort")),"abort "+context);
            var all=events.stream().filter(e->e.get("type").equals("simz1Priority")).toList();
            var crosses=all.stream().filter(e->e.get("action").equals("CROSS")).toList();
            var nativeDecisions=events.stream().filter(e->e.get("type").equals("simz1NativeDecision")).toList();
            long arrivals=events.stream().filter(e->e.get("type").equals("arrival")).count();
            long forced=nativeDecisions.stream().filter(e->e.get("reason").equals("storage_forced_move")).count();
            long pendingHeads=all.stream().filter(e->e.get("action").equals("HEAD")).count()-crosses.size();
            var waits=new TreeMap<String,Integer>();
            nativeDecisions.stream().filter(e->e.get("decision").equals("WAIT")).forEach(e->waits.merge(e.get("reason"),1,Integer::sum));
            require(arrivals==result.persons,"unfinished persons "+context+": "+arrivals+"/"+result.persons);
            require(forced==0,"forced native storage "+context);
            require(pendingHeads==0,"pending priority heads "+context);
            operations.add(name+"\t"+threads+"\t"+entry.getKey()+"\t"+result.persons+"\t"+arrivals+"\t"+(result.persons-arrivals)+"\t"+crosses.size()+"\t"+pendingHeads+"\t"+forced+"\t"+waits);
            if(Set.of("disabled","tagged-signal").contains(name)||nativeSignals(name)) {
                require(all.isEmpty(),"priority applies in excluded fixture "+context);
                if(name.startsWith("avenue-signal-")) {
                    var leave=events.stream().filter(e->e.get("type").equals("left link")&&"avenue".equals(e.get("vehicle"))&&"s".equals(e.get("link"))).findFirst().orElseThrow();
                    double crossing=Double.parseDouble(leave.get("time"));
                    var approach=nativeDecisions.stream().filter(e->"avenue".equals(e.get("vehicle"))&&"s".equals(e.get("link"))).toList();
                    require(approach.stream().anyMatch(e->e.get("decision").equals("GO")&&e.get("time").equals(leave.get("time"))&&e.get("nativeHasGreen").equals("true")),"crossing lacks native queue permission "+context);
                    // Event delivery may expose the color after the GO in the
                    // same step. Check its native timestamp, never infer a color
                    // from a generated schedule or force synchronous delivery.
                    var state=events.stream().filter(e->e.get("type").equals("signalGroupStateChangedEvent")&&"avenida".equals(e.get("signalGroupId"))&&Double.parseDouble(e.get("time"))<=crossing)
                        .max(Comparator.comparingDouble(e->Double.parseDouble(e.get("time")))).orElseThrow();
                    require(state.get("signalGroupState").equals("GREEN"),"crossing lacks native green event "+context);
                    if(name.endsWith("red")) {
                        require(crossing==80,"red avenue crossed before actual green "+context+leave);
                        require(approach.stream().anyMatch(e->e.get("reason").equals("signal_red")&&e.get("nativeHasGreen").equals("false")),"red wait absent "+context);
                    } else require(crossing==3&&approach.stream().noneMatch(e->e.get("decision").equals("WAIT")),"green avenue delayed "+context);
                    summary.add(name+"\t"+threads+"\t"+entry.getKey()+"\tavenue\t"+(name.endsWith("red")?52:3)+"\t"+(name.endsWith("red")?80:3)+"\t"+crossing+"\t"+(crossing-(name.endsWith("red")?52:3)));
                }
                continue;
            }
            var street=crosses.stream().filter(e->e.get("vehicle").equals("street")&&e.get("link").equals("w")).toList();
            require(street.size()==(name.startsWith("avenue-")?0:name.equals("repeat")?2:1),"street crossings "+context+street);
            for(var cross:crosses) {
                double time=Double.parseDouble(cross.get("time")),head=Double.parseDouble(cross.get("headTime")),ready=Double.parseDouble(cross.get("readyTime"));
                require(time>=ready,"early crossing "+cross);require(!cross.get("reason").equals("storage_forced_move"),"forced storage "+context);
                if(cross.get("role").equals("avenue")) require(head==ready,"avenue has mandatory stop "+cross);
                require(events.stream().anyMatch(e->e.get("type").equals("left link")&&Objects.equals(e.get("vehicle"),cross.get("vehicle"))&&Objects.equals(e.get("link"),cross.get("link"))&&e.get("time").equals(cross.get("time"))),"missing actual LinkLeave "+cross);
                require(events.stream().anyMatch(e->e.get("type").equals("entered link")&&Objects.equals(e.get("vehicle"),cross.get("vehicle"))&&Objects.equals(e.get("link"),cross.get("nextLink"))&&e.get("time").equals(cross.get("time"))),"missing actual LinkEnter "+cross);
                require(all.stream().filter(e->e.get("action").equals("HEAD")&&e.get("visit").equals(cross.get("visit"))&&e.get("node").equals(cross.get("node"))).count()==1,"head reset "+cross);
                summary.add(name+"\t"+threads+"\t"+entry.getKey()+"\t"+cross.get("vehicle")+"\t"+head+"\t"+ready+"\t"+time+"\t"+(time-head));
            }
            if(name.equals("avenue-free")) {
                require(crosses.size()==1&&crosses.get(0).get("time").equals(crosses.get(0).get("headTime")),"free avenue delayed "+context+crosses);
                require(all.stream().noneMatch(e->e.get("action").equals("WAIT")),"free avenue WAIT "+context);
                continue;
            }
            if(name.equals("avenue-congestion")) {
                require(crosses.size()==4,"lost congestion vehicles "+context);
                require(nativeDecisions.stream().anyMatch(e->e.get("reason").equals("congestion_queue")&&e.get("waitCategory").equals("congestion")&&e.get("source").equals("MATSim15_queue_post_step")),"missing genuine flow-capacity queue wait "+context);
                require(all.stream().noneMatch(e->e.get("reason").equals("priority_stop")),"avenue congestion incorrectly classified as Alto "+context);
                continue;
            }
            var first=street.get(0);double time=Double.parseDouble(first.get("time")),ready=Double.parseDouble(first.get("readyTime"));
            if(Set.of("alone","yield-only","nonconflict","geometric-nonconflict","blocked-avenue").contains(name)) require(time==ready,"unnecessary wait "+context+street);
            if(name.equals("yield-only")) require(time==Double.parseDouble(first.get("headTime")),"yield-only has artificial stop "+context);
            if(name.equals("sustained-priority")) {
                require(time<=ready+7,"street starved under continuous feasible priority demand "+context+first);
                require(all.stream().anyMatch(e->"street".equals(e.get("reservationVehicle"))&&Double.parseDouble(e.get("reservationAge"))>=6),"safe reservation unobserved "+context);
                require(crosses.stream().filter(e->e.get("vehicle").startsWith("avenue")).noneMatch(e->Double.parseDouble(e.get("time"))==time),"incompatible fairness crossings share step "+context);
            }
            if(name.equals("consecutive")) {
                var second=crosses.stream().filter(e->e.get("vehicle").equals("street2")).findFirst().orElseThrow();
                require(Math.abs(Double.parseDouble(second.get("time"))-time)>=5,"following vehicle skipped minimum "+context);
            }
            if(Set.of("conflict","nonconflict","geometric-nonconflict","conservative-nonconflict","blocked-avenue").contains(name)) {
                var avenue=crosses.stream().filter(e->e.get("vehicle").equals("avenue")).findFirst().orElseThrow();double at=Double.parseDouble(avenue.get("time"));
                if(name.equals("conflict")) require(at<time&&all.stream().anyMatch(e->e.get("reason").startsWith("priority_yield_conflict")||e.get("reason").equals("priority_conflict_executed")),"missing real conflict "+context);
                if(disjoint(name)&&!name.equals("conservative-nonconflict")) require(at==time,"disjoint movements unnecessarily serialized "+context+avenue+first);
                if(name.equals("conservative-nonconflict")) require(at<time,"conservative control did not serialize different approaches "+context);
                if(name.equals("blocked-avenue")) require(time<at,"blocked avenue reserved intersection "+context);
            }
            if(name.equals("blocked-street")) require(time>ready&&all.stream().anyMatch(e->e.get("reason").equals("storage_wait")&&e.get("vehicle").equals("street")),"missing storage wait "+context);
            if(name.equals("repeat")) require(!street.get(0).get("visit").equals(street.get(1).get("visit")),"repeat visit reused clock");
        }
    }
}
