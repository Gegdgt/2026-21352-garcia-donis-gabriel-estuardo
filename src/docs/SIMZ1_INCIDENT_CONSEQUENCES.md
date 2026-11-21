# SimZ1: consecuencias de incidentes sintéticos, Prompt 8

**La consecuencia física permanece deshabilitada.** Esta revisión prepara un
coordinador aislado, eventos, validación y presentación comprobables con fixtures.
No instala cierres gráficos que aparenten cambiar el tráfico, ni afirma que las
pruebas del coordinador demuestren integridad de las colas reales de QSim.

El [Prompt 7](SIMZ1_INCIDENT_DESIGN.md) dejó la detección en `fixture_only`, sin
observador nativo de parejas y con cero oportunidades reales habilitadas. Por
tanto, no existe actualmente un accidente confirmado de ese módulo que pueda
convertirse legítimamente en una intervención sobre una corrida real.

## Decisión sobre las estructuras nativas

La [auditoría de carriles](SIMZ1_INCIDENT_LANE_NATIVE_AUDIT.md) contrasta el código
local de MATSim 15.0 con `Zona1QNodeImpl`. Un guard en el nodo no controla todos
los movimientos: `QueueWithBuffer` procesa llegadas al destino y movimiento a su
búfer; `QLinkLanesImpl` realiza transferencias internas entre carriles. Cambiar la
capacidad tampoco inmoviliza automáticamente vehículos ya presentes en el búfer.
`NetworkChangeEvent` recibe enlaces y no identifica una cola independiente por
`laneId`. No se reutiliza como cierre de un carril.

Además, un `QLaneI` puede representar varias bandas físicas. Hace falta demostrar
la correspondencia uno a uno con un carril independiente antes de prometer que
sus vecinos seguirán circulando. Una cola de aproximación compartida puede
producir espera legítima por FIFO incluso cuando otro carril sigue abierto.

La pareja ADMITTED + WAIT del diseño describe exposición conflictiva gestionada.
Tras la admisión los dos vehículos pueden encontrarse en enlaces diferentes.
No se les reasigna un lugar común para fabricar el bloqueo: el prototipo exige
pertenencia exacta al mismo enlace/carril en la instantánea autorizante.

## Contrato preparado

- Duración física solicitada: **1800 segundos simulados**, intervalo
  `[startTime, scheduledEndTime)`. No usa tiempo de pared, frames o velocidad de
  reproducción. Los 900 s del Prompt 7 solo eran exclusión de anotaciones.
- Dos participantes distintos, con IDs de vehículo y tipo, enlace y carril.
  Persona opcional; no se inventan pasajeros o conductores. No se cambian las
  dimensiones configuradas de bus, moto, camión o carro.
- Un único `LaneKey(link,lane)`, ID de incidente, oportunidad, corrida,
  iteración y referencia de evidencia. Prohibido derivarlo de hitboxes WebGL.
- Eventos MATSim `simz1LaneIncidentStart`, `simz1LaneIncidentResolved` y
  `simz1LaneIncidentCensored`, con esquema `simz1-lane-incident-v1`. El emisor
  disponible es exclusivamente de fixture: `scope=fixture_only`,
  `physicsEffect=none`, `adapterVersion=uninstalled`. No se publica en SimZ1.
- Censura al finalizar el horizonte no equivale a recuperación. Un cierre
  temprano nunca inventa circulación, llegada, aborto o eliminación.
- El modo apagado no solicita instantáneas, consume observaciones ni emite
  eventos. Activarlo en configuración de producción produce un error previo a
  cargar el escenario, en Java y Python, incluso con cuatro hilos y admisión
  estricta.

La configuración reservada es:

```xml
<module name="simz1IncidentConsequences">
  <param name="enabled" value="false"/>
  <param name="durationSeconds" value="1800"/>
</module>
```

No es necesario añadirla a un escenario existente. La ausencia equivale a
apagado. `enabled=true` se rechaza hasta completar el adaptador nativo, el
observador y el catálogo. `zona1Diagnostics.incidentsEnabled` conserva su
significado anterior y no habilita este módulo.

## Integración pendiente para una corrida real

1. Portar una extensión de cola acotada a SimZ1, con hooks en **todas** las
   salidas: nodo, transferencias internas, llegadas, tránsito/estacionamiento y
   vaciado al final. No editar directamente colecciones privadas ni retirar y
   reinsertar vehículos para simular espera.
2. Resolver la pertenencia exacta a cola/búfer de ambos participantes y el mapeo
   de carril físico, incluyendo carriles originales compartidos. Rechazar un
   incidente que ya no pueda aplicarse íntegramente; jamás aplicarlo a uno solo.
3. Preparar y confirmar la intervención en barrera global, sin workers activos.
   Los actores consultan una instantánea inmutable durante el paso. La apertura
   a los 1800 s debe reactivar la cola y conservar los mismos objetos e IDs.
4. Impedir que stuckTime, FORCE, limpieza o llegada salten el bloqueo; conservar
   los contadores y registrar espera por incidente por separado. No autorizar
   giros prohibidos ni saltarse señales, prioridades o almacenamiento.
5. Reanudar mediante la admisión normal al cumplirse el plazo. Liberar el cierre
   no implica autorizar inmediatamente a todos los vehículos a cruzar.
6. Completar el observador y registro de conflictos del Prompt 7 y una evidencia
   de instalación efectiva en el manifiesto. Solo entonces sustituir la barrera
   de rechazo y habilitar ingestión/presentación de eventos nativos verificados.

El tiempo de cierre debe caer en una frontera real del paso QSim. El prototipo
rechaza saltarse la frontera exacta; no fecha retroactivamente un desbloqueo.
La integración real deberá validar el tamaño del paso o programar esa frontera
sin alterar el reloj de MATSim.
En el prototipo, `finishAtHorizon` sustituye a `completeStep` en la última
barrera: no se invocan ambos con el mismo timestamp. Si coincide con el fin
programado, se registra resolución; si lo precede, censura sin liberar reservas.

## Criterios para una prueba real pequeña, aún no habilitable

Preparar una red separada de pocos enlaces, dos carriles **independientes** donde
corresponda, dos vehículos afectados y seguidores identificados, horizonte mayor
que inicio + 1800 + tiempo de vaciado. Repetir con las mismas entradas/semillas,
primero apagado y luego encendido. No usar el histórico de 227187 personas.

| Caso | Criterio de aceptación nativa |
|---|---|
| Apagado frente a base | Mismos eventos normalizados, rutas, llegadas, abortos, WAIT/FORCE y estados finales; ningún listener de incidentes instalado |
| Carril único | Dos participantes conservados; seguidores respetan FIFO; ninguna salida/llegada/aborto de afectados durante el intervalo |
| Dos carriles | Solo la cola identificada cerrada; movimientos autorizados de la otra cola posibles; explicar cualquier bloqueo por FIFO compartida |
| Fin exacto | Cierre efectivo a inicio + 1800, sin resoluciones anticipadas ni eventos nativos con fecha futura |
| Semáforo/receptor | Tras abrir, rojo, prioridad, giro prohibido o receptor lleno siguen produciendo espera |
| Cuatro hilos/dos lugares | Sin doble intervención, pérdidas, carreras ni modificación de colas ajenas; mismos sorteos para iguales oportunidades |
| Horizonte corto | Evento de censura y participantes contabilizados como pendientes, sin declarar recuperación o llegada |
| Visor | Naranja solo en participantes activos; restauración al resolver, seek/ventanas correctos, icono no seleccionable |

No hay todavía un comando válido para ejecutar esta prueba con el efecto físico
encendido. Dar `enabled=true` actualmente comprueba el rechazo de preflight,
no ejecuta un cierre real. MATSim QSim continúa siendo un modelo de colas;
la seguridad de transiciones y la separación continua de carrocerías son
propiedades diferentes.

## Regresión sin simulaciones

Desde la raíz del repositorio, con JDK 25, Python y Node instalados:

```powershell
powershell -ExecutionPolicy Bypass -File .\check_simz1_incident_consequences.ps1
```

El script compila desde fuentes actuales en un directorio nuevo bajo `target`,
con jars de dependencias existentes. No reutiliza clases de otra revisión ni
ejecuta `Controler.run`, `QSim.run` o `StochasticCrashCheck`. Si falta el listado
de dependencias, prepararlo sin simulación ni conexión a repositorios:

```powershell
.\mvnw.cmd -o -q dependency:build-classpath -Dmdep.outputFile=target/simz1-storage-classpath.txt
```

El script comprueba también el diagnóstico del compilador: un error interno
se rechaza aunque `javac` devuelva código 0. En el sandbox Windows se observó
`AccessDeniedException` al cerrar ZIP, incluso con copias locales; la misma
compilación autorizada fuera del sandbox terminó correctamente, sin alterar
permisos ni dependencias globales. Los hashes de las fuentes Java se fijan antes
de compilar y deben seguir iguales después de los checks.

Pruebas Python/JS independientes de la compilación Java:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p 'test_simz1_incident_*.py' -v
node python/test_simz1_incident_effects.cjs
```

El check Java es `gt.edu.uvg.sim.zona1.SimZ1IncidentLaneCheck`; el script guarda
su classpath y dos eventos de fixture en el directorio de compilación que imprime.
`python/check_simz1_incident_wire.py <ruta-fixture-events.xml>` valida que Python
lee esos mismos IDs/tiempos solo al optar explícitamente por fixtures y los
rechaza por defecto. Ese archivo de dos eventos no se agrega a ningún replay.

## Resultado de la verificación

Regresión final del 22/10/2026: **55 pruebas Python, cuatro suites Node y cinco
checks Java aprobados**, más el contrato XML Java → Python. El nuevo check Java
incluye 67 comprobaciones y cuatro threads productores reales del fixture.
No se ejecutó el scheduler QSim. La comparación visual incluye Lanes/Queues,
los mismos cuerpos/poses/IDs/counts con el efecto de fixture apagado/encendido,
seek, cambio de ventana en pausa, inicio/fin y censura. La prueba de agrupación
incluye 300 incidentes y 600 cuerpos; no mide FPS de GPU.

El resto de la validación comprende configuración, detección previa, exclusiones,
preservación del contrato legado y comprobantes de admisión. El XML de dos
eventos se conserva únicamente como fixture en
[`incident-consequences-2026-10-22`](../scenarios/zona1/versions/incident-consequences-2026-10-22/validation.json).
Ese informe registra hashes, comando, log y alcance exacto. La compilación
final no presentó la excepción del sandbox descrita arriba.

La suite amplia `test_simz1_continuous_replay.cjs` conserva el fallo conocido
`future route stops at day closure` (`0 !== 1`). No se afirma que toda la suite
del repositorio esté verde ni se modifica ese comportamiento ajeno al incidente.

El SQLite histórico y el archivo masivo de eventos conservan tamaño y mtime
nanosegundo frente a la evidencia anterior; no se releyeron completos. Los hashes
SHA-256 del manifiesto histórico y de `output_vehicles.xml.gz` siguen iguales.
No hubo simulaciones, servidores, navegadores, cambios de resultados, commits
ni push.

## Archivos y presentación

| Área | Archivos |
|---|---|
| Configuración y rechazo | `SimZ1.java`, `SimZ1Configuration.java`, `SimZ1IncidentConfigGroup.java`, `python/simz1_config_validation.py` |
| Coordinación y evento aislados | `SimZ1IncidentLaneCoordinator.java`, `SimZ1LaneIncidentEvent.java` |
| Contrato Python y guardias de exportación | `python/simz1_incident_replay.py`, `simz1_trajectories.py`, `simz1_recovery_native.py` |
| Visor y carga | `python/simz1_incident_effects.js`, `visualizador_z1_controls.js`, `simz1_continuous_loader.js`, `visualizador_z1_continuous.html`, `simz1_continuous_replay.py` |
| Regresión | `SimZ1IncidentLaneCheck.java`, `python/test_simz1_incident_configuration.py`, `test_simz1_incident_replay.py`, `test_simz1_incident_effects.cjs`, `check_simz1_incident_wire.py`, `check_simz1_incident_consequences.ps1` |

Las clases Java residen en `src/main/java/gt/edu/uvg/sim/zona1`; el check, en la
ruta equivalente de `src/test/java`. Los harnesses existentes de HTML continuo
y el inspector offline incluyen el nuevo módulo para verificar la plantilla
completa. README y esta documentación enlazan la auditoría y los resultados.

El módulo visual conserva cuerpo, posición, selección e identidad. En sus
fixtures aislados, naranja `[255,140,0]` tiene prioridad sobre velocidad durante
el intervalo activo; al terminar se recupera el marcador original. Utiliza
una capa WebGL de iconos, atlas reutilizado y `pickable=false`. La emergencia
de fixture anota la pose visual de un participante existente, con procedencia
`participant_visual_pose;not_native_incident_location`; no afirma un punto de
impacto ni crea un vehículo ausente.

El constructor productivo **no permite activar fixtures mediante configuración,
URL o un supuesto `adapter_installed=true` en metadatos**. La ausencia de visita
nativa universal y coordenada acreditada sigue siendo una limitación explícita.
`getIncidentDiagnostics()` y `getVisualDiagnostics().synthetic_incidents`
exponen el estado y los registros rechazados. Los incidentes antiguos por enlace,
los FORCE y las anotaciones Design conservan sus categorías originales y no
activan naranja. La exportación rechaza explícitamente eventos del nuevo contrato
mientras no exista adaptador, en lugar de descartarlos silenciosamente o
convertirlos en perturbaciones legadas.
