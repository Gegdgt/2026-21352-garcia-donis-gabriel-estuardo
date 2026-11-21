package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Inert JVM only. Does not construct Controler/QSim or load a configuration. */
public final class SimZ1ProcessIdentityCheck {
    public static void main(String[] args)throws Exception {
        SimZ1ProcessIdentity.record();
        Path target=Path.of(System.getenv("SIMZ1_CONFIG")).toAbsolutePath().getParent().resolve("native-process.json");
        var doc=new ObjectMapper().readTree(Files.readString(target));var id=doc.path("identity");
        if(id.path("pid").asLong()!=ProcessHandle.current().pid()||
            id.path("parent_pid").asLong()!=ProcessHandle.current().parent().orElseThrow().pid()||
            !id.path("created_utc").asText().matches(".*\\.\\d{3}Z")||id.path("executable").isNull()||
            !doc.path("run_id").asText().equals(System.getenv("SIMZ1_RUN_ID")))throw new AssertionError("Native identity differs");
        try(var files=Files.list(target.getParent())) {
            if(files.anyMatch(p->p.toString().endsWith(".tmp")))throw new AssertionError("Unpublished identity temporary");
        }
        System.out.println("PROCESS IDENTITY PASS inert JVM, atomic file, pid/creation/parent/executable/run identity");
    }
}
