package gt.edu.uvg.sim.zona1;
import org.matsim.api.core.v01.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
public final class DrivingProfilesCheck {
    private static void near(double actual,double expected,String message) {
        if(!Double.isFinite(actual) || Math.abs(actual-expected)>1e-8)throw new AssertionError(message+": "+actual+" != "+expected);
    }
    private static void rejects(Runnable action) {
        try {action.run();} catch(IllegalArgumentException expected) {return;}
        throw new AssertionError("Invalid expected-time input accepted");
    }
    public static void main(String[] args) {
        var config=ConfigUtils.createConfig();
        config.vehicles().setVehiclesFile("scenarios/zona1/vehicle-types.xml");
        var scenario=ScenarioUtils.loadScenario(config);
        for(String profile:java.util.List.of("Tortuga","Normal","Liebre")) {
            var person=scenario.getPopulation().getFactory().createPerson(Id.createPersonId(profile));
            person.getAttributes().putAttribute("drivingProfile",profile);
            scenario.getPopulation().addPerson(person);
        }
        DrivingProfiles.configure(scenario);
        var network=scenario.getNetwork(); var f=network.getFactory();
        var a=f.createNode(Id.createNodeId("a"),new Coord(0,0));
        var b=f.createNode(Id.createNodeId("b"),new Coord(100,0));
        var link=f.createLink(Id.createLinkId("l"),a,b);link.setLength(100);link.setFreespeed(10);
        var cost=DrivingProfiles.costs((l,t,p,v)->100);
        var legacy=DrivingProfiles.costs((l,t,p,v)->100,DrivingProfiles.LEGACY_GENERALIZED_EXPERIMENTAL);
        var fallback=DrivingProfiles.expectedTimes((l,t,p,v)->Double.NaN);
        for(String name:java.util.List.of("Tortuga","Normal","Liebre")) {
            var person=scenario.getPopulation().getPersons().get(Id.createPersonId(name));
            var vehicle=scenario.getVehicles().getVehicles().get(org.matsim.vehicles.VehicleUtils.getVehicleId(person,"car"));
            if(!vehicle.getType().getId().toString().equals(name)) throw new AssertionError("Type mapping");
            near(vehicle.getType().getMaximumVelocity(),(name.equals("Tortuga")?20:name.equals("Liebre")?90:50)/3.6,"XML vehicle speed ceiling");
            near(vehicle.getType().getLength(),4.5,"XML vehicle length");
            near(vehicle.getType().getWidth(),1.8,"XML vehicle width");
            near(cost.getLinkTravelDisutility(link,0,person,vehicle),100,"Default pure expected seconds");
            double expected=name.equals("Tortuga")?2:name.equals("Liebre")?302:102;
            near(legacy.getLinkTravelDisutility(link,0,person,vehicle),expected,"Explicit experimental legacy cost");
            near(fallback.getLinkTravelTime(link,0,person,vehicle),name.equals("Tortuga")?18:10,"Missing observation falls back to applicable speed ceiling");
            near(DrivingProfiles.expectedTime(link,0,person,vehicle,1),name.equals("Tortuga")?18:10,"Impossible observation cannot exceed speed ceiling");
            near(DrivingProfiles.expectedTime(link,0,person,vehicle,100),100,"Observed delay retained once");
            near(DrivingProfiles.expectedTime(link,0,person,null,Double.NaN),name.equals("Tortuga")?18:10,"Profile ceiling retained when MATSim passes vehicle=null");
            near(DrivingProfiles.expectedTurns(null).getLinkToLinkTravelTime(link,link,0,person,null),name.equals("Tortuga")?18:10,"Missing turn observation floors the physical FROM link");
            near(DrivingProfiles.expectedTurns((from,to,t,p,v)->100).getLinkToLinkTravelTime(link,link,0,person,null),100,"Turn observation already contains FROM-link traversal");
            rejects(()->DrivingProfiles.expectedTime(link,0,person,vehicle,-1));
            rejects(()->DrivingProfiles.expectedTime(link,0,person,vehicle,Double.POSITIVE_INFINITY));
        }
        near(cost.getLinkMinimumTravelDisutility(link),0,"Safe lower bound for inverted proxy links");
        near(DrivingProfiles.costs((l,t,p,v)->1).getLinkTravelDisutility(link,0,null,null),1,"Cost does not apply a second physical floor to inverted links");
        var technicalType=scenario.getVehicles().getFactory().createVehicleType(Id.create("technical",org.matsim.vehicles.VehicleType.class));
        technicalType.setMaximumVelocity(4);
        var technical=scenario.getVehicles().getFactory().createVehicle(Id.createVehicleId("technical"),technicalType);
        near(DrivingProfiles.expectedTime(link,0,scenario.getPopulation().getPersons().get(Id.createPersonId("Normal")),technical,Double.NaN),25,"Technical vehicle ceiling");
        System.out.println("PASS: vehicle XML, three assignments, physical speed ceilings, fastest-time default and explicit experimental legacy costs");
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
