package gt.edu.uvg.sim.zona1;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Explicit future-run admission policy. Absent historical modules remain native. */
public final class SimZ1AdmissionConfigGroup extends ReflectiveConfigGroup {
    public static final String NATIVE = "matsim15-native";
    public static final String STRICT = "strict-receiver-v1";
    public static final String LEGACY_ORIGIN = "empty-slot-origin-v1";
    public static final String PHYSICAL_GAP_ORIGIN = "physical-gap-origin-v1";
    private String storagePolicy = NATIVE;
    private String originPolicy = LEGACY_ORIGIN;
    private boolean wholeVehicleReservation = false;
    @StringGetter("wholeVehicleReservation") public boolean getWholeVehicleReservation() { return wholeVehicleReservation; }
    @StringSetter("wholeVehicleReservation") public void setWholeVehicleReservation(boolean value) { wholeVehicleReservation = value; }

    public SimZ1AdmissionConfigGroup() { super("simz1Admission"); }

    @StringGetter("storagePolicy") public String getStoragePolicy() { return storagePolicy; }
    @StringSetter("storagePolicy") public void setStoragePolicy(String value) {
        if (!NATIVE.equals(value) && !STRICT.equals(value))
            throw new IllegalArgumentException("CONFIG_INVALID: simz1Admission.storagePolicy");
        storagePolicy = value;
    }
    public boolean isStrict() { return STRICT.equals(storagePolicy); }

    @StringGetter("originPolicy") public String getOriginPolicy() { return originPolicy; }
    @StringSetter("originPolicy") public void setOriginPolicy(String value) {
        if (!LEGACY_ORIGIN.equals(value) && !PHYSICAL_GAP_ORIGIN.equals(value))
            throw new IllegalArgumentException("CONFIG_INVALID: simz1Admission.originPolicy");
        originPolicy = value;
    }
    public boolean usesPhysicalGapOrigin() { return PHYSICAL_GAP_ORIGIN.equals(originPolicy); }

    /** The new commit relies on the existing single QSim writer and queue/FIFO model. */
    public void validateOriginPolicy(org.matsim.core.config.groups.QSimConfigGroup qsim) {
        if (!usesPhysicalGapOrigin()) return;
        if (!isStrict() || !wholeVehicleReservation || qsim.isRemoveStuckVehicles()
                || qsim.getNumberOfThreads()!=1
                || qsim.getTrafficDynamics()!=org.matsim.core.config.groups.QSimConfigGroup.TrafficDynamics.queue
                || qsim.getLinkDynamics()!=org.matsim.core.config.groups.QSimConfigGroup.LinkDynamics.FIFO)
            throw new IllegalArgumentException("CONFIG_INVALID: physical-gap-origin-v1 requires strict receiver, whole-body reservations, queue/FIFO, one QSim thread and retained blocked vehicles");
    }
}
