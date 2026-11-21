package gt.edu.uvg.sim.zona1;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;

/** Immutable routing DFA. State is a sequence prefix, never a physical lane/link.
 * Both runtimes read these exact bytes. Sources are repository-relative and must
 * be available at startup; missing/changed evidence is an error, not a fallback.
 */
final class SimZ1SequenceContract {
    static final String SHA256 = "2dc457548aaf57a5551d09928688be8bdc2b84cdbf383fda691f3eb5a4b7d254";
    private final Map<String, Automaton> modes = new HashMap<>();
    private final Set<Id<Link>> viaLinks = new HashSet<>();
    private static final class Holder {
        static final SimZ1SequenceContract INSTANCE = read();
    }
    static SimZ1SequenceContract shared() { return Holder.INSTANCE; }

    private static String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    static SimZ1SequenceContract load(byte[] bytes, Path sourceRoot) throws Exception {
        if (!SHA256.equals(sha(bytes))) throw new IllegalArgumentException("OSM sequence contract SHA256 mismatch");
        JsonNode doc = new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION).readTree(bytes);
        if (!"simz1-osm-sequences".equals(doc.path("schema").asText()) || doc.path("version").asInt() != 1)
            throw new IllegalArgumentException("Unsupported OSM sequence contract");
        var sources = doc.path("sources").fields();
        while (sources.hasNext()) {
            var source = sources.next();
            if (!source.getValue().path("sha256").asText().equals(sha(Files.readAllBytes(sourceRoot.resolve(source.getKey())))))
                throw new IllegalArgumentException("OSM source evidence hash mismatch: " + source.getKey());
        }
        var result = new SimZ1SequenceContract();
        for (String mode : List.of("car", "bus")) {
            var patterns = new LinkedHashMap<List<String>, String>();
            for (var rule : doc.path("restrictions")) {
                boolean applies = false, excepted = false;
                for (var value : rule.path("modes")) applies |= mode.equals(value.asText());
                for (var value : rule.path("exceptions")) excepted |= mode.equals(value.asText());
                if (!applies || excepted) continue;
                for (var sequence : rule.path("sequences")) {
                    var path = new ArrayList<String>();
                    sequence.forEach(value -> path.add(value.asText()));
                    for (String link : path.subList(1,path.size()-1)) result.viaLinks.add(Id.createLinkId(link));
                    patterns.put(List.copyOf(path), rule.path("relation_id").asText());
                }
            }
            result.modes.put(mode, new Automaton(patterns));
        }
        for (var treatment : doc.path("malformed_source_treatments"))
            org.apache.logging.log4j.LogManager.getLogger(SimZ1SequenceContract.class).warn("{}: {}",
                treatment.path("status").asText(), treatment.path("warning").asText());
        return result;
    }
    private static SimZ1SequenceContract read() {
        try (var stream = SimZ1SequenceContract.class.getResourceAsStream("/simz1/osm-sequences-v1.json")) {
            if (stream == null) throw new IllegalStateException("Missing shared OSM sequence contract resource");
            return load(stream.readAllBytes(), Path.of(""));
        } catch (Exception e) { throw new IllegalStateException("Cannot verify shared OSM sequence contract", e); }
    }

    private record Transition(int state, String link) { }
    private static final class Automaton {
        final Map<Transition, Integer> next = new HashMap<>();
        final Map<Transition, String> violations = new HashMap<>();
        Automaton(Map<List<String>, String> patterns) {
            var prefixes = new ArrayList<List<String>>();
            prefixes.add(List.of());
            var alphabet = new TreeSet<String>();
            for (var pattern : patterns.keySet()) {
                alphabet.addAll(pattern);
                for (int n=1; n<pattern.size(); n++) {
                    var prefix = List.copyOf(pattern.subList(0,n));
                    if (!prefixes.contains(prefix)) prefixes.add(prefix);
                }
            }
            prefixes.sort(Comparator.<List<String>>comparingInt(List::size).thenComparing(p -> String.join("\0",p)));
            for (int state=0; state<prefixes.size(); state++) for (String link : alphabet) {
                var value = new ArrayList<>(prefixes.get(state)); value.add(link);
                var key = new Transition(state,link);
                for (var pattern : patterns.entrySet()) if (endsWith(value,pattern.getKey()))
                    violations.put(key,pattern.getValue());
                int target = 0;
                for (int i=1; i<prefixes.size(); i++) if (endsWith(value,prefixes.get(i))) target=i;
                next.put(key,violations.containsKey(key)?-1:target);
            }
        }
        private static boolean endsWith(List<String> path,List<String> suffix) {
            return path.size()>=suffix.size() && path.subList(path.size()-suffix.size(),path.size()).equals(suffix);
        }
    }
    int advance(int state, Id<Link> link, String mode) {
        return state<0?-1:modes.get(mode).next.getOrDefault(new Transition(state,link.toString()),0);
    }
    boolean isVia(Id<Link> link) { return viaLinks.contains(link); }
    int progress(List<Id<Link>> path, String mode) {
        int state=0;
        for (var link:path) {state=advance(state,link,mode); if(state<0) return -1;}
        return state;
    }
    String validate(List<Id<Link>> path, String mode) {
        int state=0;
        for (int i=0; i<path.size(); i++) {
            var key=new Transition(state,path.get(i).toString());
            String relation=modes.get(mode).violations.get(key);
            if (relation!=null) return "forbidden_osm_sequence relation="+relation+" index="+i;
            state=advance(state,path.get(i),mode);
        }
        return null;
    }
}
