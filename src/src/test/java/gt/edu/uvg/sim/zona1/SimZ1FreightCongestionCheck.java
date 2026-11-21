package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;

/** Opt-in small native congestion regression. Writes only a NEW caller-selected directory.
 * Its bottleneck is a test fixture, never a change to the SimZ1 road parameters. */
public final class SimZ1FreightCongestionCheck {
    public static void main(String[] args) throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("Supply one NEW output directory");
        Path output=Path.of(args[0]).toAbsolutePath();
        if(Files.exists(output))throw new IllegalArgumentException("Output must not exist");
        var config=ConfigUtils.createConfig();
        config.controler().setOutputDirectory(output.toString()); config.controler().setLastIteration(0);
        config.qsim().setStartTime(57570); config.qsim().setEndTime(57620);
        config.qsim().setNumberOfThreads(1);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        config.parallelEventHandling().setNumberOfThreads(2);
        config.parallelEventHandling().setSynchronizeOnSimSteps(true);
        var scenario=ScenarioUtils.createScenario(config);
        var network=scenario.getNetwork(); var nf=network.getFactory();
        for(int i=0;i<4;i++)network.addNode(nf.createNode(Id.createNodeId(i),new Coord(i*100,0)));
        for(int i=0;i<3;i++) {
            var link=nf.createLink(Id.createLinkId(List.of("a","b","c").get(i)),
                network.getNodes().get(Id.createNodeId(i)),network.getNodes().get(Id.createNodeId(i+1)));
            link.setLength(100); link.setFreespeed(10); link.setNumberOfLanes(1);
            link.setCapacity(i==1?60:3600); link.setAllowedModes(Set.of("car")); network.addLink(link);
        }
        var vf=scenario.getVehicles().getFactory();
        var type=vf.createVehicleType(Id.create("FreightTruck",VehicleType.class));
        type.setNetworkMode("car").setLength(12).setWidth(2.5).setPcuEquivalents(3.5).setMaximumVelocity(40/3.6);
        type.getAttributes().putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
        type.getAttributes().putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);
        scenario.getVehicles().addVehicleType(type);
        var pf=scenario.getPopulation().getFactory();
        for(int i=0;i<8;i++) {
            var person=pf.createPerson(Id.createPersonId("h"+i)); var attrs=person.getAttributes();
            attrs.putAttribute("simz1FreightService",SimZ1Freight.SCHEMA);
            attrs.putAttribute("simz1FreightResidencePolicy",SimZ1Freight.OVERNIGHT_POLICY);
            attrs.putAttribute("simz1FreightDeparture",57580.); attrs.putAttribute("simz1GrossWeightTonnes",12.);
            attrs.putAttribute("simz1FreightRoute","a b c");
            var plan=pf.createPlan(); var origin=pf.createActivityFromLinkId("freight_external",Id.createLinkId("a"));
            origin.setEndTime(57580); plan.addActivity(origin); var leg=pf.createLeg("car");
            leg.setRoute(RouteUtils.createNetworkRoute(List.of(Id.createLinkId("a"),Id.createLinkId("b"),Id.createLinkId("c")),network));
            plan.addLeg(leg); plan.addActivity(pf.createActivityFromLinkId("freight_external",Id.createLinkId("c")));
            person.addPlan(plan); scenario.getPopulation().addPerson(person);
            scenario.getVehicles().addVehicle(vf.createVehicle(Id.createVehicleId(person.getId()),type));
        }
        SimZ1Freight.configure(scenario);
        var controler=new Controler(scenario); SimZ1Freight.install(controler);
        var terminals=new AtomicInteger();
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                addEventHandlerBinding().toInstance((BasicEventHandler)e->{
                    if(Set.of("arrival","stuckAndAbort").contains(e.getEventType()))terminals.incrementAndGet();
                });
            }
        });
        boolean rejected=false;
        try { controler.run(); }
        catch(RuntimeException failure) {
            for(Throwable cause=failure;cause!=null;cause=cause.getCause())
                if(String.valueOf(cause.getMessage()).contains("FREIGHT_NOT_APPROVED"))rejected=true;
            if(!rejected)throw failure;
        }
        SimZ1FreightClosureCheck.check(rejected,"Congestion was approved");
        SimZ1FreightClosureCheck.check(terminals.get()==8,"Cleanup lost terminal events");
        Path report=output.resolve("ITERS/it.0/0.simz1-freight-audit.csv");
        String csv=Files.readString(report);
        SimZ1FreightClosureCheck.check(csv.contains("violated") && csv.contains("terminal_residence"),"Missing terminal residence evidence");
        System.out.println("SIMZ1_FREIGHT_CONGESTION_REJECTED_AFTER_CLEANUP: "+report);
    }
}
