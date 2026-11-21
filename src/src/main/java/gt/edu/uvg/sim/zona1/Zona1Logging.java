package gt.edu.uvg.sim.zona1;

import org.apache.logging.log4j.Level;
import org.apache.logging.log4j.core.config.Configurator;

/** Suppress verbose routing messages without changing the root logger or event output. */
public final class Zona1Logging {
    private Zona1Logging() { }

    public static void configure() {
        Configurator.setLevel("org.matsim.routing", Level.WARN);
        Configurator.setLevel("org.matsim.withinday.utils.EditRoutes", Level.WARN);
    }
}
