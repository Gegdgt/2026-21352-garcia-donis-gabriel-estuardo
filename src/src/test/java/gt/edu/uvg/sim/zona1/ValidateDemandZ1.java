package gt.edu.uvg.sim.zona1;

import javax.xml.parsers.SAXParserFactory;
import org.xml.sax.InputSource;
import org.xml.sax.SAXException;
import org.xml.sax.SAXParseException;
import org.xml.sax.helpers.DefaultHandler;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.io.PopulationReader;

/** Validates against the exact DTD bundled with the installed MATSim version. */
public final class ValidateDemandZ1 {
    public static void main(String[] args) throws Exception {
        int expected = args.length > 2 ? Integer.parseInt(args[2]) : 10000;
        String network = args.length > 0 ? args[0] : "scenarios/zona1/network.xml";
        String plans = args.length > 1 ? args[1] : "scenarios/zona1/plans.xml";
        var factory = SAXParserFactory.newInstance();
        factory.setValidating(true);
        var reader = factory.newSAXParser().getXMLReader();
        reader.setEntityResolver((publicId, systemId) -> {
            if (!systemId.endsWith("/population_v6.dtd")) {
                throw new SAXException("Unexpected external entity: " + systemId);
            }
            var stream = ValidateDemandZ1.class.getResourceAsStream("/dtd/population_v6.dtd");
            if (stream == null) throw new SAXException("MATSim population DTD not found");
            return new InputSource(stream);
        });
        reader.setErrorHandler(new DefaultHandler() {
            @Override public void error(SAXParseException e) throws SAXException { throw e; }
            @Override public void fatalError(SAXParseException e) throws SAXException { throw e; }
        });
        reader.parse(new java.io.File(plans).toURI().toString());
        var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimNetworkReader(scenario.getNetwork()).readFile(network);
        new PopulationReader(scenario).readFile(plans);
        if (scenario.getPopulation().getPersons().size() != expected) {
            throw new IllegalStateException("Expected " + expected + " persons");
        }
        for (var person : scenario.getPopulation().getPersons().values()) {
            var plan = person.getSelectedPlan();
            if (person.getPlans().size() != 1 || plan.getPlanElements().size() != 3 ||
                !(plan.getPlanElements().get(0) instanceof Activity origin) ||
                !(plan.getPlanElements().get(1) instanceof Leg leg) ||
                !(plan.getPlanElements().get(2) instanceof Activity destination)) {
                throw new IllegalStateException("Invalid single-trip plan " + person.getId());
            }
            if (!leg.getMode().equals("car") || origin.getLinkId().equals(destination.getLinkId()) ||
                !scenario.getNetwork().getLinks().containsKey(origin.getLinkId()) ||
                !scenario.getNetwork().getLinks().containsKey(destination.getLinkId()) ||
                origin.getEndTime().seconds() < 32400 || origin.getEndTime().seconds() >= 54000) {
                throw new IllegalStateException("Invalid trip " + person.getId());
            }
        }
        System.out.println("PASS: MATSim 15 DTD and reader validated " + expected + " single-trip plans");
    }
}
