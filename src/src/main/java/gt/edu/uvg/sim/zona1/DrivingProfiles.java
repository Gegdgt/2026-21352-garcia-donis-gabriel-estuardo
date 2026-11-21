package gt.edu.uvg.sim.zona1;

import java.util.Map;
import java.util.Set;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.router.util.*;
import org.matsim.vehicles.*;

/** Profile-dependent vehicle ceilings and routing costs; QSim has no acceleration model. */
public final class DrivingProfiles {
    public static final String FASTEST_TIME = "fastest-time";
    public static final String LEGACY_GENERALIZED_EXPERIMENTAL = "legacy-generalized-experimental";
    public static final String SIX_TYPE_SCHEMA = "simz1-six-v1";
    public static final Set<String> AGENT_TYPES = Set.of("Normal", "Motociclista", "Liebre", "Tortuga", "TransportePublico", "TransportePesado");
    private static final Set<String> LEGACY_TYPES = Set.of("Normal", "Tortuga", "Liebre");
    private static final Map<String, Double> SIX_TYPE_KMH = Map.of("Normal",50.,"Motociclista",60.,"Liebre",90.,"Tortuga",25.);
    private static final Map<String, Double> SIX_TYPE_PCU = Map.of("Normal",1.,"Motociclista",.25,"Liebre",1.,"Tortuga",1.);
    private DrivingProfiles() { }
    public static boolean usesSixTypeSchema(Person person) {
        Object schema=person==null?null:person.getAttributes().getAttribute("simz1AgentSchema");
        if (schema==null || RoadVehicleProfiles.SCHEMA.equals(schema.toString())) return false;
        if (!SIX_TYPE_SCHEMA.equals(schema.toString()))
            throw new IllegalArgumentException("Unknown simz1AgentSchema: " + schema);
        return true;
    }
    private static String required(Person person,String key) {
        Object value=person.getAttributes().getAttribute(key);
        if (value==null || value.toString().isBlank())
            throw new IllegalArgumentException("Missing " + key + " on person " + person.getId());
        return value.toString();
    }
    public static String profile(Person person) {
        if (SimZ1Freight.applies(person)) return "Normal"; // routing cost only; native type/PCU remain freight
        if (RoadVehicleProfiles.applies(person)) return RoadVehicleProfiles.profile(person);
        if (usesSixTypeSchema(person)) {
            String result=required(person,"simz1AgentType");
            if (!AGENT_TYPES.contains(result)) throw new IllegalArgumentException("Unknown simz1AgentType: " + result);
            return result;
        }
        Object value=person==null?null:person.getAttributes().getAttribute("drivingProfile");
        String result=value==null?"Normal":value.toString();
        if (!LEGACY_TYPES.contains(result))
            throw new IllegalArgumentException("Unknown drivingProfile: "+result);
        return result;
    }
    private static double maximumVelocity(String name) {
        return (name.equals("Tortuga")?20:name.equals("Liebre")?90:50)/3.6;
    }
    /** Versioned routing metadata is checked against the loaded VehicleType before QSim starts. */
    private static double maximumVelocity(Person person) {
        if (RoadVehicleProfiles.applies(person)) return RoadVehicleProfiles.maximumVelocity(person);
        String name=profile(person);
        if (!usesSixTypeSchema(person)) return maximumVelocity(name);
        requireSupportedRoadType(name);
        double ceiling=Double.parseDouble(required(person,"simz1MaximumVelocityMps"));
        if (!Double.isFinite(ceiling) || Math.abs(ceiling-SIX_TYPE_KMH.get(name)/3.6)>1e-8)
            throw new IllegalArgumentException("Inconsistent simz1MaximumVelocityMps on person " + person.getId());
        return ceiling;
    }
    private static void requireSupportedRoadType(String name) {
        if ("TransportePublico".equals(name))
            throw new IllegalArgumentException("TransportePublico denotes passenger demand, not a car VehicleType; a verified fixed-route TransitSchedule, stops, fleet and finite service timetable are required before activation");
        if ("TransportePesado".equals(name))
            throw new IllegalArgumentException("TransportePesado is not activatable: verified or explicitly approved route access, temporal restrictions and routing enforcement are required");
    }
    private static void validateSixTypeVehicle(Person person,Vehicles vehicles) {
        String name=profile(person);
        requireSupportedRoadType(name);
        if (!name.equals(required(person,"drivingProfile")) || !name.equals(required(person,"effectiveVehicleType")))
            throw new IllegalArgumentException("Inconsistent agent/person/vehicle type mapping on person " + person.getId());
        var type=vehicles.getVehicleTypes().get(Id.create(name,VehicleType.class));
        if (type==null)
            throw new IllegalArgumentException("Missing loaded VehicleType for " + SIX_TYPE_SCHEMA + ": " + name + "; no legacy fallback is permitted");
        double ceiling=maximumVelocity(person);
        if (!"car".equals(type.getNetworkMode()) || !Double.isFinite(type.getPcuEquivalents()) ||
            Math.abs(type.getPcuEquivalents()-SIX_TYPE_PCU.get(name))>1e-8 ||
            !Double.isFinite(type.getMaximumVelocity()) || Math.abs(type.getMaximumVelocity()-ceiling)>1e-8)
            throw new IllegalArgumentException("VehicleType does not match versioned PCU, car mode or speed metadata: " + name);
    }
    /** Common car routing cannot safely enforce motorcycle-specific access or conditional rules. */
    private static void validateMotorcycleAttributes(Object element,Map<String,Object> attributes) {
        for (var attribute:attributes.entrySet()) {
            String key=attribute.getKey();
            if (key.startsWith("osm:")) key=key.substring(4);
            if (key.equals("motorcycle") && !Set.of("yes","permissive","designated").contains(String.valueOf(attribute.getValue())))
                throw new IllegalArgumentException("Motorcycle-specific access requires supported routing: " + element + " " + key + "=" + attribute.getValue());
            if (key.contains("motorcycle") && !key.equals("motorcycle"))
                throw new IllegalArgumentException("Unsupported motorcycle-specific restriction: " + element + " " + key);
        }
    }
    private static void validateMotorcycleAccess(Scenario scenario) {
        for (var node:scenario.getNetwork().getNodes().values())
            validateMotorcycleAttributes(node.getId(),node.getAttributes().getAsMap());
        for (var link:scenario.getNetwork().getLinks().values())
            validateMotorcycleAttributes(link.getId(),link.getAttributes().getAsMap());
    }
    public static void addTypes(Vehicles vehicles) {
        for (String name: java.util.List.of("Tortuga","Normal","Liebre")) {
            var id=Id.create(name,VehicleType.class);
            if (vehicles.getVehicleTypes().containsKey(id)) continue;
            var type=vehicles.getFactory().createVehicleType(id);
            type.setNetworkMode("car").setLength(4.5).setWidth(1.8).setPcuEquivalents(1);
            type.setMaximumVelocity(maximumVelocity(name));
            type.getAttributes().putAttribute("desiredAccelerationMps2",name.equals("Tortuga")?.8:name.equals("Liebre")?3.0:2.0);
            type.getAttributes().putAttribute("accelerationModel","metadata only; standard QSim does not integrate acceleration");
            vehicles.addVehicleType(type);
        }
    }
    public static void configure(Scenario scenario) {
        var vehicles=scenario.getVehicles();
        boolean versioned=false,legacy=false,road=false;
        for (var person:scenario.getPopulation().getPersons().values()) {
            if (SimZ1Freight.applies(person)) continue;
            if (usesSixTypeSchema(person)) versioned=true;
            else if (RoadVehicleProfiles.applies(person)) road=true;
            else legacy=true;
        }
        if ((versioned?1:0)+(legacy?1:0)+(road?1:0)>1)
            throw new IllegalArgumentException("Do not mix historical and " + SIX_TYPE_SCHEMA + " populations: shared vehicle IDs have different historical parameters");
        if (road) {
            var routing=scenario.getConfig().getModules().get("zona1WithinDayRouting");
            if (routing!=null && !FASTEST_TIME.equals(routing.getParams().getOrDefault("routingPolicy",FASTEST_TIME)))
                throw new IllegalArgumentException("Road profiles require fastest-time global routing; per-person policy is explicit");
            if (scenario.getConfig().qsim().getLinkDynamics()!=QSimConfigGroup.LinkDynamics.FIFO ||
                scenario.getConfig().qsim().getTrafficDynamics()!=QSimConfigGroup.TrafficDynamics.queue)
                throw new IllegalArgumentException("Road profiles support only queue/FIFO; no motorcycle filtering is claimed");
            RoadVehicleProfiles.validateCatalog(vehicles);
            boolean motorcycles=false;
            for (var person:scenario.getPopulation().getPersons().values()) {
                if (SimZ1Freight.applies(person)) continue;
                RoadVehicleProfiles.validateVehicle(person,vehicles);
                motorcycles |= RoadVehicleProfiles.motorcycle(person);
            }
            if (motorcycles) validateMotorcycleAccess(scenario);
        } else if (versioned) {
            var routing=scenario.getConfig().getModules().get("zona1WithinDayRouting");
            String policy=routing==null?FASTEST_TIME:routing.getParams().getOrDefault("routingPolicy",FASTEST_TIME);
            if (!FASTEST_TIME.equals(policy))
                throw new IllegalArgumentException(SIX_TYPE_SCHEMA + " requires fastest-time routing");
            // Preflight the entire population before assigning vehicles. Never synthesize v2 XML defaults.
            boolean hasMotorcycles=false;
            for (var person:scenario.getPopulation().getPersons().values()) {
                if (SimZ1Freight.applies(person)) continue;
                validateSixTypeVehicle(person,vehicles);
                if ("Motociclista".equals(profile(person))) hasMotorcycles=true;
            }
            if (hasMotorcycles) validateMotorcycleAccess(scenario);
        } else {
            for (var type:vehicles.getVehicleTypes().values()) {
                if (type.getAttributes().getAttribute("simz1AgentSchema")!=null)
                    throw new IllegalArgumentException("Historical populations cannot use versioned VehicleTypes: " + type.getId());
            }
            addTypes(vehicles);
        }
        for (var person:scenario.getPopulation().getPersons().values()) {
            if (SimZ1Freight.applies(person)) continue;
            String name=RoadVehicleProfiles.applies(person)?RoadVehicleProfiles.vehicleType(person):profile(person);
            var id=Id.createVehicleId(person.getId());
            if (vehicles.getVehicles().containsKey(id)) vehicles.removeVehicle(id);
            vehicles.addVehicle(vehicles.getFactory().createVehicle(id,vehicles.getVehicleTypes().get(Id.create(name,VehicleType.class))));
            VehicleUtils.insertVehicleIdsIntoAttributes(person,Map.of("car",id));
        }
        SimZ1Freight.configure(scenario);
        scenario.getConfig().qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
    }
    public static String validatePolicy(String policy) {
        if (!FASTEST_TIME.equals(policy) && !LEGACY_GENERALIZED_EXPERIMENTAL.equals(policy))
            throw new IllegalArgumentException("Unknown routingPolicy: " + policy);
        return policy;
    }
    /** Reproducible physical lower bound, including the profile when MATSim passes vehicle=null. */
    public static double freeFlowTime(Link link,double time,Person person,Vehicle vehicle) {
        double length=link.getLength(), speed=link.getFreespeed(time);
        if (!Double.isFinite(time) || !Double.isFinite(length) || length<=0 ||
            !Double.isFinite(speed) || speed<=0)
            throw new IllegalArgumentException("Invalid free-flow input on " + link.getId());
        speed=Math.min(speed,maximumVelocity(person));
        if (vehicle!=null) {
            if (vehicle.getType()==null) throw new IllegalArgumentException("Vehicle without type: " + vehicle.getId());
            double ceiling=vehicle.getType().getMaximumVelocity();
            if (Double.isNaN(ceiling) || ceiling<=0)
                throw new IllegalArgumentException("Invalid vehicle speed ceiling: " + vehicle.getId());
            speed=Math.min(speed,ceiling);
        }
        double duration=length/speed;
        if (!Double.isFinite(duration)) throw new IllegalArgumentException("Non-finite free-flow time on " + link.getId());
        return duration;
    }
    /** NaN denotes unavailable observations. Malformed measured times fail rather than masquerade as free flow. */
    public static double expectedTime(Link link,double time,Person person,Vehicle vehicle,double observed) {
        double lowerBound=freeFlowTime(link,time,person,vehicle);
        if (Double.isNaN(observed)) return lowerBound;
        if (!Double.isFinite(observed) || observed<0)
            throw new IllegalArgumentException("Invalid observed travel time on " + link.getId() + ": " + observed);
        return Math.max(lowerBound,observed);
    }
    public static TravelTime expectedTimes(TravelTime observations) {
        return (link,time,person,vehicle)->expectedTime(link,time,person,vehicle,
            observations==null?Double.NaN:observations.getLinkTravelTime(link,time,person,vehicle));
    }
    /** MATSim turn time already includes the FROM link and its exit delay; never add the link twice. */
    public static LinkToLinkTravelTime expectedTurns(LinkToLinkTravelTime observations) {
        return (from,to,time,person,vehicle)->expectedTime(from,time,person,vehicle,
            observations==null?Double.NaN:observations.getLinkToLinkTravelTime(from,to,time,person,vehicle));
    }
    public static double cost(Link link,double time,Person person,Vehicle vehicle,double duration,String policy) {
        validatePolicy(policy);
        if (usesSixTypeSchema(person) && !FASTEST_TIME.equals(policy))
            throw new IllegalArgumentException(SIX_TYPE_SCHEMA + " requires fastest-time routing");
        if (!Double.isFinite(duration) || duration<0)
            throw new IllegalArgumentException("Invalid expected travel time on " + link.getId() + ": " + duration);
        if (RoadVehicleProfiles.applies(person)) {
            if (RoadVehicleProfiles.SHORTEST_DISTANCE.equals(RoadVehicleProfiles.routingPolicy(person))) {
                double distance=link.getLength();
                if (!Double.isFinite(distance) || distance<0) throw new IllegalArgumentException("Invalid route distance");
                return distance;
            }
            return duration;
        }
        if (FASTEST_TIME.equals(policy)) return duration;
        // Historical, uncalibrated generalized weights: explicitly experimental, not fastest-time.
        String name=profile(person);
        double result=(name.equals("Tortuga")?0:name.equals("Liebre")?3:1)*duration+.02*link.getLength();
        if (!Double.isFinite(result) || result<0) throw new IllegalArgumentException("Invalid generalized cost on " + link.getId());
        return result;
    }
    public static TravelDisutility costs(TravelTime times) { return costs(times,FASTEST_TIME); }
    public static TravelDisutility costs(TravelTime times,String policy) {
        validatePolicy(policy);
        return new TravelDisutility() {
            public double getLinkTravelDisutility(Link link,double time,Person person,Vehicle vehicle) {
                // Link may be an INVERTED-network movement. Its proxy time is already normalized
                // on the physical fromLink by expectedTurns; do not apply a geometry floor here.
                return cost(link,time,person,vehicle,times.getLinkTravelTime(link,time,person,vehicle),policy);
            }
            public double getLinkMinimumTravelDisutility(Link link) {
                // Zero remains admissible on inverted networks and with time-varying link speeds.
                return FASTEST_TIME.equals(policy)?0:.02*link.getLength();
            }
        };
    }
    public static void main(String[] args) {
        var vehicles=VehicleUtils.createVehiclesContainer(); addTypes(vehicles);
        new MatsimVehicleWriter(vehicles).writeFile(args.length==0?"scenarios/zona1/vehicle-types.xml":args[0]);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
