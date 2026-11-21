package gt.edu.uvg.sim.zona1;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

/** No MATSim, Maven or logging dependencies. */
public final class SimZ1FailureReportCheck {
    public static final class BadFormat extends RuntimeException {
        BadFormat(Throwable cause) { super(cause); }
        @Override public String getMessage() { throw new IllegalArgumentException("formatter cannot read bytecode"); }
        public List<RawMessage> getErrorMessages() { return List.of(new RawMessage(getCause())); }
    }
    public record RawMessage(Throwable cause) {
        public String getMessage() { return "raw provisioning description"; }
        public Throwable getCause() { return cause; }
    }
    public static void main(String[] args) {
        var original = new IllegalStateException("real binding failure");
        var failure = new BadFormat(original);
        failure.addSuppressed(new IllegalArgumentException("secondary failure"));
        var bytes = new ByteArrayOutputStream();
        SimZ1FailureReport.print(failure, new PrintStream(bytes, true, StandardCharsets.UTF_8));
        String text = bytes.toString(StandardCharsets.UTF_8);
        for (String required : List.of("raw provisioning description", "real binding failure", "secondary failure", "simulation remains invalid"))
            if (!text.contains(required)) throw new AssertionError("Lost diagnostic: " + required);
        if (failure.getCause() != original) throw new AssertionError("Cause mutated");
        if (!text.contains("SIMZ1_CAUSE 1 [cause]")||!text.contains("SIMZ1_CAUSE 1 [suppressed]")||!text.contains("SIMZ1_CAUSE end"))
            throw new AssertionError("Cause/suppressed/completeness relationship lost");
        System.out.print(text);
        System.out.println("PASS: raw injector cause, broken formatter, suppressed error and no mutation");
    }
}
