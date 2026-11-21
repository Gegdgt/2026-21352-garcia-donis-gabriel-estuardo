package gt.edu.uvg.sim.labs;

/** Executable regression check; no additional testing dependency required. */
public final class Lab08ArgumentsCheck {
    public static void main(String[] ignored) {
        check(new String[]{}, "output/labs/08-zona1-warped");
        check(new String[]{"--output", "output/run with spaces"}, "output/run with spaces");
        check(new String[]{"--output output/labs/08-zona1"}, "output/labs/08-zona1");
        check(new String[]{"  --output   output/run with spaces  "}, "output/run with spaces");
        check(new String[]{"--output \"output/run with spaces\""}, "output/run with spaces");
        check(new String[]{"--output 'output/run with spaces'"}, "output/run with spaces");
        for (String[] invalid : new String[][]{{"--output"},{"--other x"},{"--output", ""},{"--output ''"}}) {
            try { Lab08Zona1Network.parseOutput(invalid); }
            catch (IllegalArgumentException expected) { continue; }
            throw new AssertionError("Invalid arguments accepted");
        }
        System.out.println("10 argument checks passed");
    }
    private static void check(String[] args,String expected) {
        if (!Lab08Zona1Network.parseOutput(args).equals(expected)) throw new AssertionError(expected);
    }
}
