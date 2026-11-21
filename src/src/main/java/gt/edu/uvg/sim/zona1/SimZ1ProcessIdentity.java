package gt.edu.uvg.sim.zona1;

import java.nio.file.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Self-identification before loading a run; no invented PID for a future JVM. */
final class SimZ1ProcessIdentity {
    static void record() {
        var process=ProcessHandle.current();var info=process.info();
        var identity=new LinkedHashMap<String,Object>();
        identity.put("pid",process.pid());identity.put("parent_pid",process.parent().map(ProcessHandle::pid).orElse(null));
        identity.put("created_utc",info.startInstant().map(t->new java.time.format.DateTimeFormatterBuilder()
            .appendInstant(3).toFormatter().format(t.truncatedTo(ChronoUnit.MILLIS))).orElse(null));
        identity.put("executable",info.command().orElse(null));identity.put("command",info.commandLine().orElse(null));
        identity.put("name",info.command().map(p->Path.of(p).getFileName().toString()).orElse(null));
        identity.put("role","native_jvm");identity.put("identity_source","java_ProcessHandle");
        var doc=new LinkedHashMap<String,Object>();doc.put("schema_version",1);doc.put("identity",identity);
        doc.put("run_id",System.getenv("SIMZ1_RUN_ID"));doc.put("launch_id",System.getenv("SIMZ1_LAUNCH_ID"));
        try {
            String json=new ObjectMapper().writeValueAsString(doc);
            String config=System.getenv("SIMZ1_CONFIG");
            if(config!=null&&!config.isBlank()) {
                Path target=Path.of(config).toAbsolutePath().getParent().resolve("native-process.json");
                Path temporary=Files.createTempFile(target.getParent(),"native-process-",".tmp");
                Files.writeString(temporary,json+"\n");
                Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            }
            System.out.println("SIMZ1_PROCESS_IDENTITY "+json);System.out.flush();
        } catch(Exception e){throw new IllegalStateException("Cannot persist native JVM identity",e);}
    }
}
