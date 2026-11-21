package gt.edu.uvg.sim.zona1;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.*;

/** User-run in-memory contracts. Never creates a Controler or executes QSim. */
public final class RoadVehicleProfilesCheck {
    private static final Map<String,Double> SPEEDS=Map.of("Normal",50.,"Liebre",90.,"Tortuga",25.,
        "MotocicletaLenta",30.,"Motociclista",50.,"MotocicletaRapida",70.,"TransportePesado",50.);
    private static void require(boolean value,String detail) { if (!value) throw new AssertionError(detail); }
    private static void near(double a,double b) { require(Double.isFinite(a) && Math.abs(a-b)<1e-8,a+" != "+b); }
    private static void rejects(Runnable action) {
        try {action.run();} catch (IllegalArgumentException expected) {return;}
        throw new AssertionError("Invalid setup accepted");
    }
    private static VehicleType type(Scenario s,String id) { return s.getVehicles().getVehicleTypes().get(Id.create(id,VehicleType.class)); }
    private static Person person(Scenario s,String id) { return s.getPopulation().getPersons().get(Id.createPersonId(id)); }
    private static Person addPerson(Scenario s,String name) {
        var p=s.getPopulation().getFactory().createPerson(Id.createPersonId(name));var t=type(s,name);
        for (String key:List.of("simz1VehicleFamily","drivingProfile","simz1RoutingPolicy","simz1ScenarioVersion"))
            p.getAttributes().putAttribute(key,t.getAttributes().getAttribute(key));
        p.getAttributes().putAttribute("simz1AgentSchema",RoadVehicleProfiles.SCHEMA);
        p.getAttributes().putAttribute("simz1AgentType",name);p.getAttributes().putAttribute("effectiveVehicleType",name);
        p.getAttributes().putAttribute("simz1MaximumVelocityMps",t.getMaximumVelocity());
        p.getAttributes().putAttribute("simz1VehiclePCU",t.getPcuEquivalents());
        p.getAttributes().putAttribute("simz1VehicleLengthM",t.getLength());p.getAttributes().putAttribute("simz1VehicleWidthM",t.getWidth());
        s.getPopulation().addPerson(p);return p;
    }
    private static Scenario fixture(String xml) {
        var s=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        if (xml!=null) new MatsimVehicleReader(s.getVehicles()).readFile(xml);
        else for (var entry:SPEEDS.entrySet()) {
            String name=entry.getKey();boolean moto=name.startsWith("Motocicl"), heavy=name.equals("TransportePesado");
            String profile=name.equals("Tortuga") || name.equals("MotocicletaLenta")?"tortuga":
                name.equals("Liebre") || name.equals("MotocicletaRapida")?"liebre":"normal";
            var t=s.getVehicles().getFactory().createVehicleType(Id.create(name,VehicleType.class));
            t.setNetworkMode("car").setLength(moto?2.1:heavy?10:4.5).setWidth(moto?.8:heavy?2.5:1.8)
                .setPcuEquivalents(moto?.25:heavy?3.5:1).setMaximumVelocity(entry.getValue()/3.6);
            var a=t.getAttributes();a.putAttribute("simz1AgentSchema",RoadVehicleProfiles.SCHEMA);
            a.putAttribute("simz1VehicleFamily",moto?"moto":heavy?"pesado":"carro");a.putAttribute("drivingProfile",profile);
            a.putAttribute("simz1RoutingPolicy",DrivingProfiles.FASTEST_TIME);a.putAttribute("simz1ScenarioVersion","fixture-new-only");
            a.putAttribute("simz1DimensionsAssumed","true");a.putAttribute("simz1DimensionsSource","synthetic fixture");
            a.putAttribute("accelerationModel","not_integrated_by_QSim");s.getVehicles().addVehicleType(t);
        }
        for (String name:SPEEDS.keySet()) if (!name.equals("TransportePesado")) addPerson(s,name);
        return s;
    }
    private static Link link(Scenario s,String id,int from,int to,double length,double speed,Set<String> modes) {
        var n=s.getNetwork();var l=n.getFactory().createLink(Id.createLinkId(id),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(length);l.setFreespeed(speed);l.setAllowedModes(modes);l.setCapacity(2000);l.setNumberOfLanes(1);n.addLink(l);return l;
    }
    private static List<Id<Link>> ids(String... names) {return java.util.Arrays.stream(names).map(Id::createLinkId).toList();}
    private static void checkRouting(String xml) {
        var s=fixture(xml);var n=s.getNetwork();
        for (int i=0;i<5;i++) n.addNode(n.getFactory().createNode(Id.createNodeId(i),new Coord(i*100,0)));
        var start=link(s,"start",0,1,100,100,Set.of("car"));
        var limited=link(s,"short",1,2,100,5,Set.of("car"));
        link(s,"fast",1,3,200,100,Set.of("car"));link(s,"join",3,2,10,100,Set.of("car"));
        link(s,"end",2,4,100,100,Set.of("car"));link(s,"forbidden",1,2,1,100,Set.of("walk"));
        DrivingProfiles.configure(s);
        require(s.getConfig().qsim().getLinkDynamics()==QSimConfigGroup.LinkDynamics.FIFO,"FIFO preserved");
        require(s.getVehicles().getVehicles().size()==6,"No bus or heavy inserted by catalog labels");
        var slow=person(s,"MotocicletaLenta");var fast=person(s,"MotocicletaRapida");
        near(DrivingProfiles.freeFlowTime(start,0,slow,null),12);
        near(DrivingProfiles.freeFlowTime(start,0,fast,null),360./70);
        near(DrivingProfiles.freeFlowTime(limited,0,slow,null),20);near(DrivingProfiles.freeFlowTime(limited,0,fast,null),20);
        var router=new SimZ1TurnRouter(n,new SimZ1RouteSafety(s),(l,t,p,v)->Double.NaN);
        require(router.path(start.getId(),Id.createLinkId("end"),0,slow,null).equals(ids("start","short","end")),"Slow freeflow route");
        require(router.path(start.getId(),Id.createLinkId("end"),0,fast,null).equals(ids("start","fast","join","end")),"Fast ceiling affects route");
        fast.getAttributes().putAttribute("simz1RoutingPolicy",RoadVehicleProfiles.SHORTEST_DISTANCE);
        type(s,"MotocicletaRapida").getAttributes().putAttribute("simz1RoutingPolicy",RoadVehicleProfiles.SHORTEST_DISTANCE);
        RoadVehicleProfiles.validateVehicle(fast,s.getVehicles());
        require(router.path(start.getId(),Id.createLinkId("end"),0,fast,null).equals(ids("start","short","end")),"Explicit distance policy respects modes");
        require(router.path(Id.createLinkId("end"),start.getId(),0,fast,null)==null,"No invented reverse road");
        near(DrivingProfiles.cost(start,0,fast,null,999,DrivingProfiles.FASTEST_TIME),100);
        near(type(s,"Motociclista").getLength(),2.1);near(type(s,"Motociclista").getWidth(),.8);
        near(type(s,"TransportePesado").getLength(),10);near(type(s,"TransportePesado").getPcuEquivalents(),3.5);
        // A measured wait remains binding even for the fast profile.
        near(DrivingProfiles.expectedTime(start,0,fast,null,500),500);
    }
    private static void checkRejections() {
        var heavy=fixture(null);addPerson(heavy,"TransportePesado");rejects(()->DrivingProfiles.configure(heavy));
        require(heavy.getVehicles().getVehicles().isEmpty(),"Blocked activation cannot partially assign vehicles");
        var wrong=fixture(null);type(wrong,"Motociclista").setWidth(1.8);rejects(()->DrivingProfiles.configure(wrong));
        var order=fixture(null);type(order,"MotocicletaRapida").setMaximumVelocity(1);rejects(()->DrivingProfiles.configure(order));
        var unknown=fixture(null);person(unknown,"Normal").getAttributes().putAttribute("simz1AgentSchema","unknown");rejects(()->DrivingProfiles.configure(unknown));
        var family=fixture(null);person(family,"Motociclista").getAttributes().putAttribute("simz1VehicleFamily","carro");rejects(()->DrivingProfiles.configure(family));
        var access=fixture(null);var node=access.getNetwork().getFactory().createNode(Id.createNodeId("blocked"),new Coord(0,0));
        node.getAttributes().putAttribute("osm:motorcycle","no");access.getNetwork().addNode(node);rejects(()->DrivingProfiles.configure(access));
        var passing=fixture(null);passing.getConfig().qsim().setLinkDynamics(QSimConfigGroup.LinkDynamics.PassingQ);rejects(()->DrivingProfiles.configure(passing));
        var old=ScenarioUtils.createScenario(ConfigUtils.createConfig());var p=old.getPopulation().getFactory().createPerson(Id.createPersonId("unchanged"));
        p.getAttributes().putAttribute("drivingProfile","Tortuga");old.getPopulation().addPerson(p);DrivingProfiles.configure(old);
        near(type(old,"Tortuga").getMaximumVelocity(),20/3.6);require(old.getVehicles().getVehicles().containsKey(Id.createVehicleId("unchanged")),"Historical ID retained");
    }
    public static void main(String[] args) {
        try {
            if (args.length>1) throw new IllegalArgumentException("Usage: RoadVehicleProfilesCheck [python-vehicle-types.xml]");
            checkRouting(args.length==1?args[0]:null);checkRejections();
            System.out.println("PASS: future profiles, explicit ceilings/routes, dimensions, modes, blocked heavy and unchanged history. No QSim executed.");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
