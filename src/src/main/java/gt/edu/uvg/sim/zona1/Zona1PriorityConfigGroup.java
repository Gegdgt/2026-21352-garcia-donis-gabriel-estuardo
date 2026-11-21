package gt.edu.uvg.sim.zona1;
import org.matsim.core.config.ReflectiveConfigGroup;

/** Persisted experimental assumptions, never surveyed intersection priorities. */
public final class Zona1PriorityConfigGroup extends ReflectiveConfigGroup {
    private boolean enabled=true;
    private double stopSeconds=UnsignalizedPriority.STOP_SECONDS;
    private double maxYieldSeconds=30;
    private String classification="osm-hierarchy", conflicts="geometric";
    public Zona1PriorityConfigGroup(){super("zona1Priority");}
    @StringGetter("enabled") public String getEnabled(){return Boolean.toString(enabled);}
    @StringSetter("enabled") public void setEnabled(String value){
        if(!value.equals("true")&&!value.equals("false")) throw new IllegalArgumentException("CONFIG_INVALID: priority enabled must be true/false");
        enabled=Boolean.parseBoolean(value);
    }
    @StringGetter("stopSeconds") public double getStopSeconds(){return stopSeconds;}
    @StringSetter("stopSeconds") public void setStopSeconds(double value){
        if(!Double.isFinite(value)||value<0) throw new IllegalArgumentException("CONFIG_INVALID: stopSeconds must be finite and nonnegative");
        stopSeconds=value;
    }
    @StringGetter("classification") public String getClassification(){return classification;}
    @StringGetter("maxYieldSeconds") public double getMaxYieldSeconds(){return maxYieldSeconds;}
    @StringSetter("maxYieldSeconds") public void setMaxYieldSeconds(double value){
        if(!Double.isFinite(value)||value<0) throw new IllegalArgumentException("CONFIG_INVALID: maxYieldSeconds must be finite and nonnegative");
        maxYieldSeconds=value;
    }
    @StringSetter("classification") public void setClassification(String value){
        if(!java.util.Set.of("osm-hierarchy","osm-name-orientation","orientation","explicit").contains(value)) throw new IllegalArgumentException("CONFIG_INVALID: priority classification");
        classification=value;
    }
    @StringGetter("conflicts") public String getConflicts(){return conflicts;}
    @StringSetter("conflicts") public void setConflicts(String value){
        if(!java.util.Set.of("geometric","conservative","verified-node-table").contains(value)) throw new IllegalArgumentException("CONFIG_INVALID: priority conflicts");
        conflicts=value;
    }
}
