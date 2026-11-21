package org.matsim.core.mobsim.qsim.qnetsimengine;
import java.lang.reflect.Proxy;
import java.util.List;
import org.matsim.api.core.v01.Id;
import org.matsim.vehicles.VehicleUtils;

/** Actual reservation implementation with deterministic lane contents. */
public final class SimZ1VehicleReservationCheck {
    static QVehicle vehicle(String id,double length,double pcu) {
        var type=VehicleUtils.createVehicleType(Id.create(id,org.matsim.vehicles.VehicleType.class));
        type.setLength(length);type.setPcuEquivalents(pcu);
        var nativeVehicle=VehicleUtils.createVehicle(Id.createVehicleId(id),type);
        return (QVehicle)Proxy.newProxyInstance(QVehicle.class.getClassLoader(),new Class[]{QVehicle.class},
            (proxy,method,args)->switch(method.getName()) {
                case "getVehicle" -> nativeVehicle;
                case "getId" -> nativeVehicle.getId();
                case "getSizeInEquivalents" -> pcu;
                default -> throw new AssertionError(method);
            });
    }
    static QLaneI lane(double capacity,QVehicle... vehicles) {
        return (QLaneI)Proxy.newProxyInstance(QLaneI.class.getClassLoader(),new Class[]{QLaneI.class},
            (proxy,method,args)->switch(method.getName()) {
                case "getAllVehicles" -> List.of(vehicles);
                case "getStorageCapacity" -> capacity;
                case "hashCode" -> System.identityHashCode(proxy);
                case "equals" -> proxy==args[0];
                default -> throw new AssertionError(method);
            });
    }
    public static void main(String[] args) {
        var car=vehicle("car",4.5,1);var bus=vehicle("bus",12,3);var truck=vehicle("truck",12,3.5);
        var moto=vehicle("moto",2.1,.25);
        for(var heavy:List.of(bus,truck)) {
            if(SimZ1VehicleReservation.accepts(lane(4,heavy,car),car,7.5))throw new AssertionError("buffer body ignored");
            if(SimZ1VehicleReservation.accepts(lane(3.6,car),heavy,7.5))throw new AssertionError("partial heavy slot accepted");
            if(!SimZ1VehicleReservation.accepts(lane(5,heavy),car,7.5))throw new AssertionError("full free slot rejected");
        }
        double footprint=SimZ1VehicleReservation.footprint(.25,2.1,7.5);
        if(Math.abs(footprint*7.5-2.2)>1e-9)throw new AssertionError("motorcycle 10cm gap missing");
        if(SimZ1VehicleReservation.accepts(lane(footprint-1e-6),moto,7.5))throw new AssertionError("length not reserved");
        if(!SimZ1VehicleReservation.accepts(lane(footprint),moto,7.5))throw new AssertionError("exact fit rejected");
        var original=lane(.5);var terminal=lane(4);
        var link=(QLinkI)Proxy.newProxyInstance(QLinkI.class.getClassLoader(),new Class[]{QLinkI.class},
            (proxy,method,arguments)->switch(method.getName()) {
                case "getAcceptingQLane" -> original;
                case "getOfferingQLanes" -> List.of(terminal);
                default -> throw new AssertionError(method);
            });
        if(!SimZ1VehicleReservation.acceptsLink(link,bus,7.5))throw new AssertionError("serial original queue mistaken for complete road");
        System.out.println("PASS: whole bus/truck/car/motorcycle storage including buffers and minimum 0.10m footprint");
    }
}
