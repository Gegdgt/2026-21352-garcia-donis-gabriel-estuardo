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
import org.matsim.lanes.Lane;
import org.matsim.lanes.LanesUtils;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;
import org.matsim.vehicles.MatsimVehicleReader;

/** In-memory configuration/routing contracts only. Does not run a Controler or QSim. */
public final class SixTypeProfilesCheck {
    private static final Map<String,Double> KMH=Map.of("Normal",50.,"Motociclista",60.,"Liebre",90.,"Tortuga",25.);
    private static void require(boolean condition,String message) {if (!condition) throw new AssertionError(message);}
    private static void near(double actual,double expected,String message) {
        require(Double.isFinite(actual) && Math.abs(actual-expected)<1e-8,message + ": " + actual + " != " + expected);
    }
    private static void rejects(Runnable action,String detail) {
        try {action.run();} catch (IllegalArgumentException expected) {
            require(expected.getMessage().contains(detail),"Unexpected rejection: " + expected.getMessage());return;
        }
        throw new AssertionError("Invalid setup accepted: " + detail);
    }
    private static Person addPerson(Scenario scenario,String name,boolean versioned) {
        var person=scenario.getPopulation().getFactory().createPerson(Id.createPersonId(name));
        person.getAttributes().putAttribute("drivingProfile",name);
        if (versioned) {
            person.getAttributes().putAttribute("simz1AgentSchema",DrivingProfiles.SIX_TYPE_SCHEMA);
            person.getAttributes().putAttribute("simz1AgentType",name);
            person.getAttributes().putAttribute("effectiveVehicleType",name);
            if (KMH.containsKey(name)) person.getAttributes().putAttribute("simz1MaximumVelocityMps",KMH.get(name)/3.6);
        }
        scenario.getPopulation().addPerson(person);return person;
    }
    private static VehicleType type(Scenario scenario,String name) {
        return scenario.getVehicles().getVehicleTypes().get(Id.create(name,VehicleType.class));
    }
    private static Scenario fixture() {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        var vehicles=scenario.getVehicles();
        for (String name:KMH.keySet()) {
            var type=vehicles.getFactory().createVehicleType(Id.create(name,VehicleType.class));
            type.setNetworkMode("car").setMaximumVelocity(KMH.get(name)/3.6).setPcuEquivalents(name.equals("Motociclista")?.25:1);
            type.setLength(name.equals("Motociclista")?2:4.5).setWidth(name.equals("Motociclista")?.8:1.8);
            vehicles.addVehicleType(type);addPerson(scenario,name,true);
        }
        return scenario;
    }
    private static Id<Link> link(String name) {return Id.createLinkId(name);}
    private static void addLink(Scenario scenario,String name,int from,int to,double speed) {
        var n=scenario.getNetwork();var l=n.getFactory().createLink(link(name),n.getNodes().get(Id.createNodeId(from)),n.getNodes().get(Id.createNodeId(to)));
        l.setLength(100);l.setFreespeed(speed);l.setCapacity(2000);l.setNumberOfLanes(1);l.setAllowedModes(Set.of("car"));n.addLink(l);
    }
    private static void checkRoadTypesAndRestrictions() {
        var scenario=fixture();var network=scenario.getNetwork();
        for (int i=0;i<4;i++) network.addNode(network.getFactory().createNode(Id.createNodeId(i),new Coord(i*100,0)));
        addLink(scenario,"s",0,1,100);addLink(scenario,"legal",1,2,10);addLink(scenario,"forbidden",1,2,100);addLink(scenario,"e",2,3,100);
        var lanes=scenario.getLanes();var f=lanes.getFactory();var assignment=f.createLanesToLinkAssignment(link("s"));
        LanesUtils.createAndAddLane(assignment,f,Id.create("legal-only",Lane.class),2000,50,0,1,List.of(link("legal")),null);
        LanesUtils.createAndAddLane(assignment,f,Id.create("original",Lane.class),2000,100,0,1,null,List.of(Id.create("legal-only",Lane.class)));
        lanes.addLanesToLinkAssignment(assignment);
        scenario.getConfig().qsim().setUseLanes(true);
        scenario.getConfig().qsim().setTrafficDynamics(QSimConfigGroup.TrafficDynamics.queue);
        scenario.getConfig().qsim().setLinkDynamics(QSimConfigGroup.LinkDynamics.FIFO);
        DrivingProfiles.configure(scenario);
        require(scenario.getVehicles().getVehicleTypes().size()==4,"No duplicated or fallback types");
        require(scenario.getVehicles().getVehicles().size()==4,"One vehicle per supported road person");
        require(scenario.getConfig().qsim().getVehiclesSource()==QSimConfigGroup.VehiclesSource.fromVehiclesData,"QSim receives explicit vehicles");
        require(scenario.getConfig().qsim().isUseLanes(),"Lanes preserved");
        require(scenario.getConfig().qsim().getTrafficDynamics()==QSimConfigGroup.TrafficDynamics.queue,"Queue dynamics preserved");
        require(scenario.getConfig().qsim().getLinkDynamics()==QSimConfigGroup.LinkDynamics.FIFO,"FIFO preserved; no invented motorcycle filtering");
        var safety=new SimZ1RouteSafety(scenario);
        var router=new SimZ1TurnRouter(network,safety,(l,t,p,v)->Double.NaN,null,DrivingProfiles.FASTEST_TIME);
        var legalRoute=List.of(link("s"),link("legal"),link("e"));
        for (var person:scenario.getPopulation().getPersons().values()) {
            String name=DrivingProfiles.profile(person);var vehicle=scenario.getVehicles().getVehicles().get(VehicleUtils.getVehicleId(person,"car"));
            require(vehicle.getType().getId().toString().equals(name),"Canonical effective type retained");
            near(vehicle.getType().getPcuEquivalents(),name.equals("Motociclista")?.25:1,"PCU retained in VehicleType");
            near(vehicle.getType().getMaximumVelocity(),KMH.get(name)/3.6,"Vehicle speed ceiling");
            near(DrivingProfiles.freeFlowTime(network.getLinks().get(link("s")),0,person,null),360/KMH.get(name),"Versioned null-vehicle routing ceiling");
            near(DrivingProfiles.freeFlowTime(network.getLinks().get(link("s")),0,person,vehicle),360/KMH.get(name),"Loaded vehicle routing ceiling");
            require(router.path(link("s"),link("e"),0,person,vehicle).equals(legalRoute),"Time objective cannot bypass lane restrictions: " + name);
            require(router.path(link("e"),link("s"),0,person,vehicle)==null,"No reverse traversal against link direction");
            require(DrivingProfiles.freeFlowTime(network.getLinks().get(link("legal")),0,person,vehicle)>=10,"No bypass of link speed ceiling");
            near(DrivingProfiles.cost(network.getLinks().get(link("s")),0,person,vehicle,100,DrivingProfiles.FASTEST_TIME),100,"Time-based routing");
        }
        var motorcycle=scenario.getPopulation().getPersons().get(Id.createPersonId("Motociclista"));
        near(type(scenario,"Motociclista").getLength(),2,"PCU does not rewrite vehicle geometry");
        rejects(()->DrivingProfiles.cost(network.getLinks().get(link("s")),0,motorcycle,null,100,DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL),"requires fastest-time");
    }
    private static void checkRejectedActivation() {
        for (String name:List.of("TransportePublico","TransportePesado")) {
            var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());addPerson(scenario,name,true);
            require(DrivingProfiles.profile(scenario.getPopulation().getPersons().get(Id.createPersonId(name))).equals(name),"Distinct pending category");
            rejects(()->DrivingProfiles.configure(scenario),name.equals("TransportePublico")?"TransitSchedule":"route access");
            require(scenario.getVehicles().getVehicleTypes().isEmpty() && scenario.getVehicles().getVehicles().isEmpty(),"Blocked category must not create cars");
        }
        var missing=ScenarioUtils.createScenario(ConfigUtils.createConfig());addPerson(missing,"Tortuga",true);
        rejects(()->DrivingProfiles.configure(missing),"Missing loaded VehicleType");
        require(missing.getVehicles().getVehicleTypes().isEmpty(),"No legacy fallback when v2 XML is missing");
        var oldType=fixture();type(oldType,"Tortuga").setMaximumVelocity(20/3.6);
        rejects(()->DrivingProfiles.configure(oldType),"VehicleType does not match");
        require(oldType.getVehicles().getVehicles().isEmpty(),"Preflight is completed before assignments");
        var pcu=fixture();type(pcu,"Motociclista").setPcuEquivalents(1);
        rejects(()->DrivingProfiles.configure(pcu),"VehicleType does not match");
        var mapping=fixture();mapping.getPopulation().getPersons().get(Id.createPersonId("Normal")).getAttributes().putAttribute("effectiveVehicleType","Liebre");
        rejects(()->DrivingProfiles.configure(mapping),"type mapping");
        var metadata=fixture();metadata.getPopulation().getPersons().get(Id.createPersonId("Normal")).getAttributes().putAttribute("simz1MaximumVelocityMps",90/3.6);
        rejects(()->DrivingProfiles.configure(metadata),"simz1MaximumVelocityMps");
        var mixed=fixture();addPerson(mixed,"legacy-person",false);
        rejects(()->DrivingProfiles.configure(mixed),"Do not mix historical");
        var policy=fixture();ConfigUtils.addOrGetModule(policy.getConfig(),Zona1RoutingConfigGroup.class).setRoutingPolicy(DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL);
        rejects(()->DrivingProfiles.configure(policy),"requires fastest-time");
        var unknown=fixture();unknown.getPopulation().getPersons().get(Id.createPersonId("Normal")).getAttributes().putAttribute("simz1AgentSchema","future-unknown");
        rejects(()->DrivingProfiles.configure(unknown),"Unknown simz1AgentSchema");
    }
    private static void checkLegacy() {
        var historical=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        for (String name:List.of("Normal","Liebre","Tortuga")) addPerson(historical,name,false);
        DrivingProfiles.configure(historical);
        near(type(historical,"Tortuga").getMaximumVelocity(),20/3.6,"Historical Tortuga unchanged");
        near(type(historical,"Normal").getMaximumVelocity(),50/3.6,"Historical Normal unchanged");
        near(type(historical,"Liebre").getMaximumVelocity(),90/3.6,"Historical Liebre unchanged");
        for (var p:historical.getPopulation().getPersons().values()) require(!DrivingProfiles.usesSixTypeSchema(p),"Never reinterpret old persons");
        var unknown=ScenarioUtils.createScenario(ConfigUtils.createConfig());addPerson(unknown,"Motociclista",false);
        rejects(()->DrivingProfiles.configure(unknown),"Unknown drivingProfile");
        var stripped=fixture();
        for (var p:stripped.getPopulation().getPersons().values()) p.getAttributes().removeAttribute("simz1AgentSchema");
        for (var t:stripped.getVehicles().getVehicleTypes().values()) t.getAttributes().putAttribute("simz1AgentSchema",DrivingProfiles.SIX_TYPE_SCHEMA);
        rejects(()->DrivingProfiles.configure(stripped),"Historical populations cannot use versioned VehicleTypes");
        require(stripped.getVehicles().getVehicles().isEmpty(),"Stripped person schema cannot reinterpret versioned vehicle data");
    }
    private static Scenario accessFixture(String key,String value,boolean nodeTag) {
        var scenario=fixture();var n=scenario.getNetwork();
        n.addNode(n.getFactory().createNode(Id.createNodeId(0),new Coord(0,0)));
        n.addNode(n.getFactory().createNode(Id.createNodeId(1),new Coord(100,0)));
        addLink(scenario,"s",0,1,10);
        var attributes=nodeTag?n.getNodes().get(Id.createNodeId(0)).getAttributes():n.getLinks().get(link("s")).getAttributes();
        attributes.putAttribute(key,value);return scenario;
    }
    private static void checkMotorcycleAccess() {
        for (boolean nodeTag:List.of(false,true)) {
            for (String allowed:List.of("yes","permissive","designated")) {
                var accepted=accessFixture("osm:motorcycle",allowed,nodeTag);
                DrivingProfiles.configure(accepted);
                require(accepted.getVehicles().getVehicles().size()==4,"Explicit allowed motorcycle access accepted");
            }
            for (String denied:List.of("no","unknown","")) {
                var blocked=accessFixture("osm:motorcycle",denied,nodeTag);
                rejects(()->DrivingProfiles.configure(blocked),"Motorcycle-specific access");
                require(blocked.getVehicles().getVehicles().isEmpty(),"Denied access preflight must not create vehicles");
            }
            for (String key:List.of("motorcycle:conditional","osm:motorcycle:conditional","osm:maxspeed:motorcycle","osm:restriction:motorcycle")) {
                var blocked=accessFixture(key,"yes",nodeTag);
                rejects(()->DrivingProfiles.configure(blocked),"Unsupported motorcycle-specific restriction");
            }
        }
        var bare=accessFixture("motorcycle","no",false);
        rejects(()->DrivingProfiles.configure(bare),"Motorcycle-specific access");
        var absent=accessFixture("osm:motorcycle","no",false);
        absent.getPopulation().removePerson(Id.createPersonId("Motociclista"));
        DrivingProfiles.configure(absent);
        require(absent.getVehicles().getVehicles().size()==3,"Motorcycle restriction does not block a population without motorcycles");
    }
    private static void checkPythonVehicleXml(String path) {
        var scenario=ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimVehicleReader(scenario.getVehicles()).readFile(path);
        require(scenario.getVehicles().getVehicleTypes().size()==4,"Python XML must contain four supported road types");
        require(scenario.getVehicles().getVehicles().isEmpty(),"Vehicle types XML must not fabricate fleet vehicles");
        for (String name:KMH.keySet()) {
            var loaded=type(scenario,name);
            require(loaded!=null,"Missing Python XML type: " + name);
            near(loaded.getMaximumVelocity(),KMH.get(name)/3.6,"Python XML vehicle maximum velocity");
            near(loaded.getPcuEquivalents(),name.equals("Motociclista")?.25:1,"Python XML PCU");
            require(DrivingProfiles.SIX_TYPE_SCHEMA.equals(loaded.getAttributes().getAttribute("simz1AgentSchema")),"Python XML schema metadata");
            require("car".equals(loaded.getNetworkMode()),"Python XML road network mode");
            addPerson(scenario,name,true);
        }
        DrivingProfiles.configure(scenario);
        require(scenario.getVehicles().getVehicles().size()==4,"Python XML types accepted by versioned Java configuration");
        System.out.println("PASS: Python vehicleDefinitions XML parsed by MATSim reader; four PCU/speed/schema mappings preserved.");
    }
    public static void main(String[] args) {
        try {
            if (args.length>1) throw new IllegalArgumentException("Usage: SixTypeProfilesCheck [python-vehicle-types.xml]");
            require(DrivingProfiles.AGENT_TYPES.equals(Set.of("Normal","Motociclista","Liebre","Tortuga","TransportePublico","TransportePesado")),"Six distinct canonical categories");
            checkRoadTypesAndRestrictions();checkRejectedActivation();checkLegacy();checkMotorcycleAccess();
            if (args.length==1) checkPythonVehicleXml(args[0]);
            System.out.println("PASS: six canonical types; four explicit road VehicleTypes; PCU/speed/routing metadata; lane/direction limits; pending transit/heavy fail closed; legacy preserved. No QSim simulation executed.");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
