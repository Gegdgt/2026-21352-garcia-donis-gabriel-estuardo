package gt.edu.uvg.sim.zona1;

import java.util.Map;
import java.util.Set;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.Vehicles;

/** Explicit future scenario metadata, never a migration of historical persons. */
public final class RoadVehicleProfiles {
    public static final String SCHEMA = "simz1-road-profiles-v1";
    public static final String SHORTEST_DISTANCE = "shortest-distance";
    private static final Map<String,String> FAMILY = Map.of(
        "Normal","carro","Tortuga","carro","Liebre","carro",
        "MotocicletaLenta","moto","Motociclista","moto","MotocicletaRapida","moto","TransportePesado","pesado");
    private static final Map<String,String> PROFILE = Map.of(
        "Normal","normal","Tortuga","tortuga","Liebre","liebre",
        "MotocicletaLenta","tortuga","Motociclista","normal","MotocicletaRapida","liebre","TransportePesado","normal");
    private RoadVehicleProfiles() { }
    public static boolean applies(Person person) {
        return person != null && SCHEMA.equals(person.getAttributes().getAttribute("simz1AgentSchema"));
    }
    private static String required(Person person,String key) {
        Object value=person.getAttributes().getAttribute(key);
        if (value==null || value.toString().isBlank()) throw new IllegalArgumentException("Missing " + key + " on " + person.getId());
        return value.toString();
    }
    private static double positive(double value,String key) {
        if (!Double.isFinite(value) || value<=0) throw new IllegalArgumentException("Invalid " + key);
        return value;
    }
    private static double number(Person person,String key) {
        return positive(Double.parseDouble(required(person,key)),key);
    }
    public static String vehicleType(Person person) {
        String kind=required(person,"effectiveVehicleType");
        if (!FAMILY.containsKey(kind) || !kind.equals(required(person,"simz1AgentType")) ||
            !FAMILY.get(kind).equals(required(person,"simz1VehicleFamily")) ||
            !PROFILE.get(kind).equals(required(person,"drivingProfile")))
            throw new IllegalArgumentException("Inconsistent road family/profile/type on " + person.getId());
        return kind;
    }
    public static String profile(Person person) { return PROFILE.get(vehicleType(person)); }
    public static boolean motorcycle(Person person) { return "moto".equals(FAMILY.get(vehicleType(person))); }
    public static double maximumVelocity(Person person) { vehicleType(person); return number(person,"simz1MaximumVelocityMps"); }
    public static String routingPolicy(Person person) {
        String policy=required(person,"simz1RoutingPolicy");
        if (!Set.of(DrivingProfiles.FASTEST_TIME,SHORTEST_DISTANCE).contains(policy))
            throw new IllegalArgumentException("Unsupported road routing policy: " + policy);
        return policy;
    }
    public static void validateCatalog(Vehicles vehicles) {
        if (!vehicles.getVehicleTypes().values().stream().filter(t->!SimZ1Freight.serviceType(t)).map(t->t.getId().toString()).collect(java.util.stream.Collectors.toSet()).equals(FAMILY.keySet()))
            throw new IllegalArgumentException("Road catalog requires exactly seven explicit types; no buses or legacy fallback");
        String version=null;
        for (var type:vehicles.getVehicleTypes().values()) {
            if (SimZ1Freight.serviceType(type)) continue;
            String name=type.getId().toString(); var attrs=type.getAttributes();
            if (!SCHEMA.equals(attrs.getAttribute("simz1AgentSchema")) || !FAMILY.get(name).equals(attrs.getAttribute("simz1VehicleFamily")) ||
                !PROFILE.get(name).equals(attrs.getAttribute("drivingProfile")) || !"car".equals(type.getNetworkMode()) ||
                !"true".equals(String.valueOf(attrs.getAttribute("simz1DimensionsAssumed"))) ||
                attrs.getAttribute("simz1DimensionsSource")==null ||
                !"not_integrated_by_QSim".equals(attrs.getAttribute("accelerationModel")) ||
                !Set.of(DrivingProfiles.FASTEST_TIME,SHORTEST_DISTANCE).contains(String.valueOf(attrs.getAttribute("simz1RoutingPolicy"))))
                throw new IllegalArgumentException("Invalid versioned VehicleType: " + name);
            Object current=attrs.getAttribute("simz1ScenarioVersion");
            if (current==null || current.toString().isBlank() || (version!=null && !version.equals(current.toString())))
                throw new IllegalArgumentException("Inconsistent road scenario version");
            version=current.toString();
            positive(type.getMaximumVelocity(),name+" speed"); positive(type.getPcuEquivalents(),name+" PCU");
            positive(type.getLength(),name+" length"); positive(type.getWidth(),name+" width");
        }
        double slow=type(vehicles,"MotocicletaLenta").getMaximumVelocity(), normal=type(vehicles,"Motociclista").getMaximumVelocity(),
               fast=type(vehicles,"MotocicletaRapida").getMaximumVelocity();
        if (!(slow<normal && normal<fast)) throw new IllegalArgumentException("Motorcycle ceilings must satisfy tortuga < normal < liebre");
    }
    private static VehicleType type(Vehicles vehicles,String name) {
        return vehicles.getVehicleTypes().get(Id.create(name,VehicleType.class));
    }
    public static void validateVehicle(Person person,Vehicles vehicles) {
        String name=vehicleType(person);
        if ("TransportePesado".equals(name))
            throw new IllegalArgumentException("TransportePesado: route access enforcement is not implemented; configured parameters are not authorization");
        var type=type(vehicles,name);
        if (type==null || Math.abs(type.getMaximumVelocity()-maximumVelocity(person))>1e-8 ||
            Math.abs(type.getPcuEquivalents()-number(person,"simz1VehiclePCU"))>1e-8 ||
            Math.abs(type.getLength()-number(person,"simz1VehicleLengthM"))>1e-8 ||
            Math.abs(type.getWidth()-number(person,"simz1VehicleWidthM"))>1e-8 ||
            !routingPolicy(person).equals(type.getAttributes().getAttribute("simz1RoutingPolicy")) ||
            !required(person,"simz1ScenarioVersion").equals(type.getAttributes().getAttribute("simz1ScenarioVersion")))
            throw new IllegalArgumentException("Road VehicleType disagrees with person metadata: " + name);
    }
}
