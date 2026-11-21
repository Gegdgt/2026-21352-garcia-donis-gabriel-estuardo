# SimZ1: auditoría del cierre nativo de un carril

Prompt 8, 22/10/2026. Se leyó `AGENTS.md`; el árbol estaba limpio al iniciar.
Esta auditoría conserva la red, QSim, admisión, capacidades, señales y corridas
históricas. No ejecuta MATSim, Controler, QSim, servidores ni navegadores.

## Decisión técnica

**No está garantizada ni instalada la inmovilización física de dos vehículos
durante 1800 s y el cierre independiente de un carril.** Las interfaces actuales
permiten consultar colas y modificar capacidad, pero no ofrecen una operación
atómica de retención/liberación por vehículo que cubra todas las salidas,
llegadas, paradas y transferencias internas. Añadir solo un WAIT al nodo dejaría
rutas de movimiento sin cubrir. No se instala ese parche parcial.

El nuevo módulo `simz1IncidentConsequences` queda apagado por defecto.
`SimZ1.loadConfiguration` lo reconoce y `SimZ1Configuration.validate` rechaza
`enabled=true` antes de cargar el escenario: faltan el adaptador físico, el
observador nativo de parejas y el catálogo de conflictos reales verificado.
El rechazo no convierte la solicitud en `false`, ni modifica `stuckTime`,
`removeStuckVehicles`, políticas de admisión o capacidad. No cambia la entrada
`RunZona1Simulation` ni el generador legado `StochasticCrashEvent`.

## Fuente primaria y rutas de movimiento

Fuente local examinada:
`C:\Users\gegdg\.m2\repository\org\matsim\matsim\15.0\matsim-15.0-sources.jar`.
SHA-256 comprobado en la auditoría de Prompt 7:
`916e8271b34df4de935a1ff95bc8ecabf1a03f4991111164bb43a03b08de37e3`.
Las líneas siguientes corresponden a entradas de ese jar, salvo el nodo local.

| Fuente | Evidencia | Consecuencia |
|---|---|---|
| `QLaneI.java:40–89` | API de entrada, consulta, capacidad, paso y `getFirstVehicle/popFirstVehicle`; no `hold(vehicle,until)` | No hay contrato de retención individual ni transacción de dos participantes. |
| `QueueWithBuffer.java:256–303` | `moveQueueToBuffer` es privado; consulta earliest exit, maneja paradas de tránsito, llegada al destino y finalmente flujo hacia buffer | Un guard de nodo no impide una llegada ni una salida de la cola hacia parada/buffer. |
| `QueueWithBuffer.java:561–575` | `doSimStep` es final y llama al método anterior | Un decorador que omita el paso entero también omitiría trabajo de otros vehículos/huecos. No es un cierre selectivo acreditado. |
| `QueueWithBuffer.java:587–610` | `addFromUpstream` activa enlace, contabiliza PCU y recalcula `earliestLinkExitTime` | Alterar solo ese tiempo no es una reserva persistente: una transferencia lo reescribe y el buffer no consulta ese reloj para salir. |
| `QueueWithBuffer.java:644–685,793–811` | Retirar de la cola y retirar del buffer tienen contabilidad y efectos distintos; `popFirstVehicle` emite salida de carril | Extraer dos vehículos para guardarlos externamente y reinsertarlos no preserva automáticamente FIFO, PCU, eventos ni viaje. No se hace. |
| `QueueWithBuffer.java:780–789` | `getAllVehicles()` construye una colección nueva | No es una API de edición de la cola. |
| `QueueWithBuffer.java:719–723,926–936` | Admisión por almacenamiento; setters de flujo/número efectivo recalculan atributos | Capacidad cero no equivale a una barrera para vehículos ya en buffer o con llegada. No prueba cierre físico de un subcarril. |
| `QLinkLanesImpl.java:214–221` | Un `QueueWithBuffer` FIFO por objeto Lane usa `numberOfRepresentedLanes` | Un objeto puede representar varios carriles físicos; no cabe cerrar uno individual sin representación independiente probada. |
| `QLinkLanesImpl.java:281–340,361–370` | La fase de enlaces mueve vehículos entre carriles, antes de ejecutar cada cola | Esa transferencia no pasa por `Zona1QNodeImpl`. Hace falta cobertura separada. |
| `QLinkLanesImpl.java:387–400` | Elige el carril siguiente por menor carga; después comprueba admisión y puede parar la cabeza | Envolver un carril con rechazo puede bloquear la cabeza aunque otro carril permita el movimiento; no basta para demostrar independencia. |
| `NetworkChangeEvent.java:87–97,130–139` | Conserva `List<Link>` y cambios de flujo, velocidad o número de carriles | No es un evento dirigido a `lane_id`. No se emplea como supuesto cierre independiente. |
| Nodo local `Zona1QNodeImpl.java:376–400,423–510,536–550` | Mueve cabeza de buffer, permiso/conflicto/receptor e inserción entre enlaces | Solo cubre la transición entre enlaces. No se modifica; la política estricta y el diagnóstico FORCE histórico se conservan. |

La ubicación de un participante en un evento no demuestra que ambos vehículos
estén en el mismo carril. El encuentro de Prompt 7 —una admisión y una demanda
conflictiva en WAIT— puede dejar a los vehículos en enlaces/carriles distintos.
El nuevo fixture rechaza esa pareja como solicitud de cierre compartido: no
traslada el vehículo admitido hacia atrás, no fusiona carriles y no inventa un
punto de impacto. Dos participantes retenidos tampoco significa que solo dos
vehículos resulten afectados: sus seguidores pueden esperar por FIFO.

## Cuatro hilos y fases

`AbstractQNetsimEngine.java:387–423` asigna cada nodo y sus enlaces salientes a
un runner. `QNetsimEngineWithThreadpool.java:96–107` espera todos los workers
de nodos antes de la fase de enlaces. Esto no autoriza a un colector externo a
editar simultáneamente las colas: el productor aguas arriba y el consumidor
aguas abajo intervienen sobre un enlace en rutas distintas del motor.

Una integración física futura necesitaría estado inmutable publicado en una
frontera común antes de las operaciones afectadas; cobertura de nodos,
transferencias internas, llegadas, tránsito y activación de enlaces; y prueba
de restauración exacta sin FORCE/remoción ni capacidad inventada. No debe leer
la cabeza receptora de otro actor ni introducir bloqueos cruzados. La ausencia
de un deadlock JVM no garantiza que una red congestionada pueda vaciarse.

## Contrato implementado exclusivamente para fixtures

Archivos nuevos:

- `SimZ1IncidentConfigGroup.java`: módulo apagado, duración contractual fija
  de 1800 s y rechazo de toda activación productiva.
- `SimZ1IncidentLaneCoordinator.java`: libro de reservas de prueba, sin
  referencias a QVehicle, QLane, red, RNG o EventsManager. Sus capacidades
  nativas son explícitamente `false` y enumeran los bloqueantes anteriores.
- `SimZ1LaneIncidentEvent.java`: evento MATSim separado con factoría que
  rechaza cualquier `scope` distinto de `fixture_only`. No se publica desde
  `SimZ1.main` ni se instala listener alguno.
- `SimZ1IncidentLaneCheck.java`: pruebas puras, sin construir una simulación.

El coordinador exige exactamente dos IDs distintos, tipos conocidos por el
fixture y la misma pareja exacta `(link,lane)` para ambos. Persona es opcional;
no se inventa. Solo el hilo colector modifica su estado, después de recibir
un watermark único por cada productor registrado. Los cuatro productores de
la prueba leen snapshots inmutables; ninguno tiene acceso a colas nativas.

Los tiempos internos son microsegundos enteros en `[0,9007199254740991]`, con
fin también dentro del intervalo. XML conserva decimales exactos en segundos;
`Event.getTime()` expone el `double` de segundos exigido por MATSim. Los campos
`scheduledEndTime-startTime` representan exactamente 1800 s. El colector debe
procesar esa frontera exacta: si la omite, falla antes de modificar el estado,
en vez de afirmar una liberación a una hora que no procesó. El horizonte
censurado registra el corte actual y conserva las reservas pendientes; no
emite una recuperación futura ni libera anticipadamente.

| Atributo del evento | Valor/significado actual |
|---|---|
| `type` | `simz1LaneIncidentStart`, `simz1LaneIncidentResolved` o `simz1LaneIncidentCensored` |
| `schema`, `scope` | `simz1-lane-incident-v1`, **`fixture_only`** |
| `physicsEffect`, `intendedPhysicsEffect` | **`none`**, `independent_lane_hold` |
| `adapterVersion`, `adapterEvidence` | **`uninstalled`**, `fixture_gate_only_not_native` |
| `time`, `startTime`, `scheduledEndTime`, `durationSeconds` | Tiempo simulado del registro, inicio, inicio + 1800, `1800` |
| `incidentId`, `opportunityId`, `runId`, `iteration`, `evidenceRef` | Identidad y procedencia del fixture |
| `link`, `lane`, `vehicle1/2`, `vehicleType1/2`, `person1/2` | Ubicación común y participantes; persona ausente si desconocida; asociación conservada al ordenar |
| `state` | `active`, `resolved` o `censored`; son estados del fixture, no confirmaciones físicas |

Una futura variante `scope=native` y `physicsEffect=independent_lane_hold`
requeriría adaptador instalado, prueba de aplicación y manifiesto concordante.
**Esta factoría no permite crearla.** Los nombres comunes de evento no bastan
para aceptar un incidente como real: el consumidor debe verificar alcance,
efecto, identidad, procedencia y ciclo de vida. No se convierten eventos Design
de Prompt 7, perturbaciones legadas ni solapamientos del visor.

## Pruebas y límites de lo que prueban

El check cubre apagado sin leer entradas, igualdad de una FIFO de fixture,
dos retenciones identificadas, independencia de otro `LaneKey`, 1800 s exactos
incluyendo tiempo fraccional, censura, duplicados, barreras incompletas, lotes
inválidos sin publicación parcial, escritor ajeno, cuatro productores reales,
identidades y atributos inmutables, y rechazo de configuración/eventos nativos.
No certifica el scheduler QSim, retención física, llegadas reales, paralelismo
entre colas MATSim ni circulación alrededor de un accidente.

Regresión preparada desde la raíz:

```powershell
powershell -ExecutionPolicy Bypass -File .\check_simz1_incident_consequences.ps1
```

El main puro `gt.edu.uvg.sim.zona1.SimZ1IncidentLaneCheck` acepta opcionalmente
una ruta XML nueva y crea exclusivamente Start/Resolved de fixture para comprobar
el parser. Usa creación exclusiva; nunca sobrescribe un archivo existente.
El resultado de la ejecución de esa regresión se registra en la entrega general.
