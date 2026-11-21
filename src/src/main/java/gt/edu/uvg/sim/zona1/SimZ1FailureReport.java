package gt.edu.uvg.sim.zona1;

import java.io.PrintStream;
import java.lang.reflect.Method;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;

/** Last-resort diagnostics. No Log4j, Throwable.toString or Guice source formatter. */
public final class SimZ1FailureReport {
    private SimZ1FailureReport() { }
    public static void print(Throwable error, PrintStream stream) {
        stream.println("SIMZ1_CAUSE failure; simulation remains invalid");
        Set<Throwable> visited = Collections.newSetFromMap(new IdentityHashMap<>());
        report(error, stream, visited, 0, "root");
        stream.println("SIMZ1_CAUSE end");
        stream.flush();
    }
    private static String message(Throwable error) {
        // ProvisionException.getMessage() formats source locations using embedded ASM.
        if (error.getClass().getName().startsWith("com.google.inject.")) return "(see raw injector messages below)";
        try { return String.valueOf(error.getMessage()); }
        catch (Throwable formattingError) { return "(message unavailable; " + formattingError.getClass().getName() + ")"; }
    }
    private static void report(Throwable error, PrintStream stream, Set<Throwable> visited, int depth, String relation) {
        if (error == null || !visited.add(error)) return;
        if (depth > 20) { stream.println("SIMZ1_CAUSE truncated"); return; }
        stream.println("SIMZ1_CAUSE " + depth + " [" + relation + "] " + error.getClass().getName() + ": " + message(error));
        StackTraceElement[] trace = error.getStackTrace();
        for (int i = 0; i < Math.min(trace.length, 24); i++) stream.println("SIMZ1_CAUSE at " + trace[i]);
        // Emit the actual cause chain before injector details/suppressed errors.
        // Depth alone cannot distinguish a cause from a suppressed sibling.
        report(error.getCause(), stream, visited, depth + 1, relation.equals("root")||relation.equals("cause")?"cause":relation);
        // Guice SPI Message.getMessage() is the raw description (not Message.toString()).
        try {
            Method getter = error.getClass().getMethod("getErrorMessages");
            Object messages = getter.invoke(error);
            if (messages instanceof Iterable<?> items) {
                int count = 0;
                for (Object item : items) {
                    if (++count > 30) break;
                    stream.println("SIMZ1_CAUSE injector: " + item.getClass().getMethod("getMessage").invoke(item));
                    Object cause = item.getClass().getMethod("getCause").invoke(item);
                    if (cause instanceof Throwable nested) report(nested, stream, visited, depth + 1, "injector");
                }
            }
        } catch (NoSuchMethodException notGuice) {
            // Ordinary Throwable; no injector SPI.
        } catch (Throwable diagnosticsError) {
            stream.println("SIMZ1_CAUSE injector details unavailable: " + diagnosticsError.getClass().getName());
        }
        for (Throwable suppressed : error.getSuppressed()) report(suppressed, stream, visited, depth + 1, "suppressed");
    }
}
