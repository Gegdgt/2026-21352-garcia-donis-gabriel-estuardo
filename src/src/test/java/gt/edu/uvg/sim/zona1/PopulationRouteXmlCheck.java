package gt.edu.uvg.sim.zona1;

import java.nio.file.Files;
import java.nio.file.Path;
import javax.xml.stream.XMLOutputFactory;
import javax.xml.stream.XMLStreamWriter;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PopulationWriter;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.io.PopulationReader;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.misc.Time;
import org.matsim.vehicles.PersonVehicles;

/** XML reader/writer probe only. No controller, mobsim, freight listener or routing. */
public final class PopulationRouteXmlCheck {
    private static Scenario read(String path) {
        Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new PopulationReader(scenario).readFile(path);
        if (scenario.getPopulation().getPersons().size() > 150)
            throw new AssertionError("Only bounded fixtures are permitted");
        return scenario;
    }

    private static void snapshot(Scenario scenario, Path path) throws Exception {
        try (var out = Files.newOutputStream(path)) {
            XMLStreamWriter xml = XMLOutputFactory.newFactory().createXMLStreamWriter(out, "UTF-8");
            xml.writeStartDocument("UTF-8", "1.0");
            xml.writeStartElement("nativePopulation");
            for (var person : scenario.getPopulation().getPersons().values()) {
                xml.writeStartElement("person");
                xml.writeAttribute("id", person.getId().toString());
                xml.writeStartElement("attributes");
                for (var entry : person.getAttributes().getAsMap().entrySet()) {
                    xml.writeStartElement("attribute");
                    xml.writeAttribute("name", entry.getKey());
                    xml.writeCharacters(entry.getValue() instanceof PersonVehicles vehicles
                            ? new java.util.TreeMap<>(vehicles.getModeVehicles()).toString() : entry.getValue().toString());
                    xml.writeEndElement();
                }
                xml.writeEndElement();
                xml.writeStartElement("plan");
                for (var element : person.getSelectedPlan().getPlanElements()) {
                    if (element instanceof Activity activity) {
                        xml.writeStartElement("activity");
                        xml.writeAttribute("type", activity.getType());
                        xml.writeAttribute("link", activity.getLinkId().toString());
                        if (activity.getEndTime().isDefined())
                            xml.writeAttribute("end_time", Double.toString(activity.getEndTime().seconds()));
                        if (activity.getCoord() != null) {
                            xml.writeAttribute("x", Double.toString(activity.getCoord().getX()));
                            xml.writeAttribute("y", Double.toString(activity.getCoord().getY()));
                        }
                        xml.writeEndElement();
                    } else if (element instanceof Leg leg) {
                        xml.writeStartElement("leg");
                        xml.writeAttribute("mode", leg.getMode());
                        if (leg.getRoute() != null) {
                            if (!(leg.getRoute() instanceof NetworkRoute route))
                                throw new AssertionError("Expected native NetworkRoute");
                            xml.writeStartElement("route");
                            xml.writeAttribute("type", route.getRouteType());
                            xml.writeAttribute("start_link", route.getStartLinkId().toString());
                            xml.writeAttribute("end_link", route.getEndLinkId().toString());
                            xml.writeAttribute("vehicleRefId", String.valueOf(route.getVehicleId()));
                            xml.writeAttribute("intermediates", String.join(" ", route.getLinkIds().stream().map(Object::toString).toList()));
                            xml.writeCharacters(route.getRouteDescription());
                            xml.writeEndElement();
                        }
                        xml.writeEndElement();
                    }
                }
                xml.writeEndElement();
                xml.writeEndElement();
            }
            xml.writeEndElement();
            xml.writeEndDocument();
            xml.close();
        }
    }

    public static void main(String[] args) throws Exception {
        if (Runtime.version().feature() != 17) throw new AssertionError("JDK17 required");
        if (args.length != 2) throw new IllegalArgumentException("input.xml output-prefix");
        System.out.println("NATIVE_READER_JAR=" + PopulationReader.class.getProtectionDomain().getCodeSource().getLocation());
        Scenario loaded = read(args[0]);
        snapshot(loaded, Path.of(args[1] + ".loaded.xml"));
        // Keep fractional departures in this IO test; MATSim's default writer
        // formats HH:mm:ss and truncates fractions. No production config change.
        Time.setDefaultTimeFormat(Time.TIMEFORMAT_HHMMSSDOTSS);
        String roundtrip = args[1] + ".roundtrip.xml";
        new PopulationWriter(loaded.getPopulation()).write(roundtrip);
        snapshot(read(roundtrip), Path.of(args[1] + ".reloaded.xml"));
        System.out.println("NATIVE_XML_ONLY persons=" + loaded.getPopulation().getPersons().size()
                + " controller_started=false qsim_started=false");
    }
}
