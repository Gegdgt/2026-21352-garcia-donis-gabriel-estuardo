# SimZ1: observabilidad nativa de incidentes y conflictos

Auditoría de solo lectura del 22/10/2026, Prompt 7. Se leyó `AGENTS.md` y el
árbol estaba limpio al comenzar. No se ejecutaron MATSim, QSim, servidores,
navegadores, simulaciones ni escaneos de eventos masivos. Este documento no
implementa un modelo de accidentes ni cambia la admisión.

## Qué puede afirmarse

SimZ1 registra decisiones de circulación, cambios entre enlaces/carriles y
perturbaciones sintéticas. **Esos registros no observan contacto entre
carrocerías.** Un movimiento conflictivo o ambiguo, un WAIT, un FORCE, una
coincidencia temporal en el nodo y un solapamiento del replay son evidencias
distintas; ninguna equivale por sí sola a una colisión física.

[`PriorityMovements.java`](../src/main/java/gt/edu/uvg/sim/zona1/PriorityMovements.java),
líneas 6–11 y 62–78, declara conflictos de movimientos por nodo/paso, no geometría
de barrido. Sus evidencias son `same_approach_native_queue`, `shared_exit_merge`,
`verified_node_table`, `reciprocal_opposite_through`, `separated_geometric_chords`
y `conflicting_or_ambiguous`. La última incluye incertidumbre geométrica; no es
una observación de choque. Las dimensiones de `VehicleType` son parámetros
configurados, no posiciones, velocidades ni aceleraciones continuas medidas.

## Eventos actuales y sus límites

| Fuente local y líneas | Campos disponibles | Límite relevante |
|---|---|---|
| `Zona1NativeDiagnostics.java`, 126–146, 256–284 | `simz1NativeDecision`: `time`, `person`, `vehicle`, `link`, `nextLink`, `lane`, `decision`, `reason`, `waitCategory`, `waitSeconds`, `earliestLinkExitTime`, `stuckTime`, `removeStuckVehicles`, `trafficDynamics`, `signalState`, `nativeHasGreen`, `admissionPolicy`, `admissionPolicyVersion`, `source` | Es una decisión o intento. `turn_go` no confirma inserción ni trayectoria continua. |
| Mismo archivo, 153–158 | WAIT `admission_conflict_executed`: también `node`, `admissionScope=node_step`, `blockingFromLink`, `blockingNextLink`, `conflictEvidence` | Identifica el movimiento bloqueante, pero no su vehículo, persona, carril ni visita. |
| Mismo archivo, 162–178 | `simz1Admission`: `vehicle`, `person`, `node`, `link`, `nextLink`, `lane`, `receivingLane`, `receiverAcceptedAtDecision=true`, política/versión/fuente | Comprobante emitido después de retornar `addFromUpstream`, solo en política estricta. No contiene pareja, episodio ni duración física del cruce. |
| Mismo archivo, 181–247 | Rechazo receptor y, cuando corresponde muestreo, `storageObservationVersion`, `receivingQueueType`, `receivingLoadIndicator`, `receivingLoadSemantics`, `receivingStorageCapacityPcu`, `receivingFlowCapacityPcuPerStep`, `vehicleSizePcu`, `sourceHeadLastMovedTime`, contadores de salidas | El rechazo pertenece a la rama ejecutada. Los valores de las colas vecinas no constituyen una instantánea atómica con varios hilos. WAIT se muestrea como máximo una vez por receptor cada 60 s; las intervenciones se observan siempre. |
| `UnsignalizedPriority.java`, 137–158, 180–213 | `simz1Priority`: `HEAD/GO/WAIT/CROSS`, nodo, vehículo/persona/carril/movimiento, `headTime`, `readyTime`, `visit`, rol/control, política, reserva y movimiento bloqueante | Solo nodos elegibles de prioridad. `visit` no es un identificador universal de episodio para todos los nodos. La pareja bloqueante no está identificada por vehículo. |
| MATSim `LinkEnterEvent.java`, 71–75; eventos de carril existentes | Tiempo, vehículo, enlace; eventos de carril añaden pertenencia al carril | Registran fronteras de cola, no punto de impacto, orientación, velocidad instantánea o separación entre cuerpos. |

Los archivos Java de diagnóstico/nodo están en
[`src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/`](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/).
La prioridad está en
[`UnsignalizedPriority.java`](../src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java).

[`Zona1QNodeImpl.java`](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1QNodeImpl.java),
líneas 423–510, conserva el orden permiso/ruta → conflicto → receptor → inserción.
`admitted` almacena solo `Movement(from,to)` (103–104), se limpia al cambiar de
instante (426–430) y se añade tras la inserción (468–471). En 536–550 se emiten
`LinkLeave` y `LinkEnter` antes de que termine `addFromUpstream`; el comprobante
`simz1Admission` posterior distingue la confirmación de esa llamada.

El exportador [`simz1_trajectories.py`](../python/simz1_trajectories.py), 224–239,
reduce WAIT a `first/last/attempts/sources/position_evidence/wait_category` por
razón y estancia. No conserva ahí todas las decisiones, parejas, carriles o
receptores. El SQLite de trayectorias no sustituye un registro de oportunidades.
[`simz1_admission_validation.py`](../python/simz1_admission_validation.py), 24–81,
audita intentos y comprobantes, y declara `physical_spacing_proven=false`.

## Incidentes sintéticos anteriores y entradas de ejecución

[`StochasticCrashEvent.java`](../src/main/java/gt/edu/uvg/sim/zona1/StochasticCrashEvent.java):

- Línea 14: contrato explícito de incidentes sintéticos, sin frecuencia de
  accidentes calibrada ni modelo de colisión.
- Líneas 17, 32–33: probabilidad predeterminada `0.0005`, factor de capacidad
  `0.2` y de velocidad `0.3`.
- Líneas 59–65, 85–98: semilla `seed + iteration`, enlaces `car` ordenados,
  revisión cada 60 s, **una evaluación por enlace ocupado e iteración**.
  `evaluated.add` precede al Bernoulli, incluso si no genera incidente.
  Duración entera uniforme de 900 a 2700 s; no comienza después de
  `endTime-2700`.
- Líneas 68–75, 102–107: aplica cambios de red absolutos; convierte capacidad
  del período nativo a unidades por segundo antes de enviarla a QSim.
- Líneas 110–135: recuperación por duración o limpieza; eventos
  `zona1IncidentStart` / `zona1IncidentRecovered` con `link`, `capacityPerHour`,
  `freespeedMps`, `scheduledRecovery`, `durationSeconds`, `reason`.

No registra participantes, perfil de conductor, oportunidad, pareja, colisión,
coordenada de impacto ni semilla/draw por incidente. Puede reutilizarse como
referencia de cambio/restauración temporal y unidades; no como detector causal.
Su test [`StochasticCrashCheck.java`](../src/test/java/gt/edu/uvg/sim/zona1/StochasticCrashCheck.java)
ejecuta `controler.run()` en la línea 73 y **no se ejecutó** en esta auditoría.

[`RunZona1Simulation.java`](../src/main/java/gt/edu/uvg/sim/zona1/RunZona1Simulation.java),
61–64 y 83, instala ese generador si `incidentsEnabled=true` y prohíbe combinarlo
con otros cambios de red externos. La entrada actual
[`SimZ1.java`](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1.java), 84–94, **no lo
instala**. El campo `incidents_enabled` del preflight expresa configuración;
por sí solo no certifica que una entrada Java haya instalado el componente.

El histórico `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0, sí ejecutó
`RunZona1Simulation`, según `run-manifest.json`, 3735–3742, clave `command`.
Su cache lateral conserva exactamente un incidente genérico:

| Campo | Valor |
|---|---|
| Enlace | `osm_1313303878_6_backward` |
| Inicio / recuperación | 1500 / 4076 s; duración 2576 s |
| Capacidad exportada | 400 por hora |
| Velocidad exportada | 4,5 km/h |
| Posición visual | `[-90.50579330000028,14.636123949997204]` |
| Icono | `crash` |

Fuente conservada:
`runtime/simz1-227187-direct/webgl-continuo/sqlite-source/source-side.json`.
El manifiesto adyacente declara SHA-256
`6ef047736ccd5767b7179db26ca8cb6d156ec07ade705a420d76e3c3cc6339bd`.
Se leyeron solo prefijos/finales acotados de estas caches, sin recalcular su hash
ni leer el archivo masivo de eventos. La posición proviene del punto medio de
enlace calculado en `simz1_trajectories.py:114–117` y
`simz1_recovery_native.py:189–192`: **no es un impacto observado**, y `icon=crash`
no establece una colisión. No se conocen participantes de ese incidente.

## Cuatro hilos y lugares posibles de instrumentación

Fuente primaria local: `C:\Users\gegdg\.m2\repository\org\matsim\matsim\15.0\matsim-15.0-sources.jar`.
SHA-256 comprobado en esta auditoría:
`916e8271b34df4de935a1ff95bc8ecabf1a03f4991111164bb43a03b08de37e3`.

Entradas internas del jar:

- `org/matsim/core/mobsim/qsim/qnetsimengine/AbstractQNetsimEngine.java:387–423`
  asigna cada nodo y sus enlaces salientes al mismo runner.
- `.../AbstractQNetsimEngineRunner.java:86–107` ejecuta serialmente los nodos
  de cada actor y después sus enlaces.
- `.../QNetsimEngineWithThreadpool.java:96–107` espera todos los workers de
  nodos antes de ejecutar la fase de enlaces.
- `org/matsim/core/mobsim/qsim/QSim.java:390–411,425–426` sitúa callbacks
  antes/después de los motores; una futura modificación de red debe respetar
  esas fronteras, no mutar colas ajenas desde un callback de decisión.

Se pueden instrumentar, **sin implementación en esta revisión**, las cabeceras
que observa el propietario del nodo, su decisión y la inserción confirmada.
Cada observación debería ser una copia inmutable con IDs de ambos participantes,
visitas y movimientos. No debe consultar la cabecera del receptor aguas abajo:
`Zona1NativeDiagnostics.java:221–240` explica la carrera y marca la observación
como `unavailable_parallel_qsim` cuando corresponde. Tampoco se debe introducir
un lock global, dependencia del orden de eventos entre nodos o Random global.

Una oportunidad estable necesita modelo, lugar canónico y pareja de visitas,
con los movimientos asociados a cada vehículo en su evidencia. El mismo
episodio no debe volver a sortearse por WAIT, frame, consulta, cambio de carril
o movimiento dentro de la visita. El diseño elegido deduplica conservadoramente
toda la pareja de visitas/lugar; una visita nueva permite otra oportunidad.
El draw usa semilla independiente, réplica estable, iteración y catálogo; el
UUID de corrida particiona el registro sin cambiar ese sorteo. El orden de
cuatro workers no debe cambiarlo para iguales observaciones. Es un contrato
propuesto, no un dato presente. Véase el [diseño](SIMZ1_INCIDENT_DESIGN.md).

Faltan actualmente: ID universal de oportunidad/episodio, ambos vehículos y
personas en el conflicto, visitas nativas en todos los nodos, decisión y receptor
de cada participante, desenlace enlazado a ambas admisiones, criterio de exposición
y parámetros/modelo versionados. También faltan posiciones continuas, aceleración,
velocidad relativa, tiempo de ocupación del cruce y geometría de impacto. Sin
esas últimas observaciones, TTC, choque y severidad física quedarían estimados
o desconocidos; deben permanecer separados del conflicto potencial y de una
perturbación sintética explícitamente modelada.
