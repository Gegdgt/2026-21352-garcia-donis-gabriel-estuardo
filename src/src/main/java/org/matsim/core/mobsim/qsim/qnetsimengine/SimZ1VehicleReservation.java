package org.matsim.core.mobsim.qsim.qnetsimengine;

/** Conservative aggregate storage reservation, including buffer bodies.
 * This is not microscopic car following or a measured vehicle trajectory. */
public final class SimZ1VehicleReservation {
    public static final double MIN_GAP_METERS = .10;
    public static double footprint(double pcu, double length, double cell) {
        if (!(pcu > 0 && length > 0 && cell > 0) || !Double.isFinite(pcu+length+cell))
            throw new IllegalArgumentException("Invalid vehicle storage footprint");
        return Math.max(pcu, (length+MIN_GAP_METERS)/cell);
    }
    static boolean accepts(QLaneI lane, QVehicle incoming, double cell) {
        double occupied=0;
        for(var present:lane.getAllVehicles()) {
            var type=present.getVehicle().getType();
            occupied+=footprint(type.getPcuEquivalents(),type.getLength(),cell);
        }
        var type=incoming.getVehicle().getType();
        return occupied+footprint(incoming.getSizeInEquivalents(),type.getLength(),cell)<=lane.getStorageCapacity()+1e-9;
    }
    static boolean acceptsLink(QLinkI link, QVehicle incoming, double cell) {
        // The accepting .original queue is a SERIAL subdivision, often only
        // a few metres. It cannot be treated as the whole receiving road.
        var queues=new java.util.HashSet<QLaneI>(link.getOfferingQLanes());
        queues.add(link.getAcceptingQLane());
        double occupied=0,capacity=0;
        var ids=new java.util.HashSet<org.matsim.api.core.v01.Id<org.matsim.vehicles.Vehicle>>();
        for(var queue:queues) {
            capacity+=queue.getStorageCapacity();
            for(var present:queue.getAllVehicles())if(ids.add(present.getId())) {
                var type=present.getVehicle().getType();
                occupied+=footprint(type.getPcuEquivalents(),type.getLength(),cell);
            }
        }
        var type=incoming.getVehicle().getType();
        return occupied+footprint(incoming.getSizeInEquivalents(),type.getLength(),cell)<=capacity+1e-9;
    }
}
