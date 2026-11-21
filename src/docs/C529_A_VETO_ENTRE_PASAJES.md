# SIMZ1 — C529-A: veto entre pasajes

Se reprodujo y corrigió el veto recíproco de prioridad del foco Elena/10a Calle de t=251 s. La corrección es local a un ciclo cerrado de solicitudes físicamente viables que necesitan el mismo conjunto de nodos. No constituye una aprobación de la corrida de 180000 ni una demostración de descarga de toda la red.

La evidencia original permanece en `runtime/diagnostics/c529-a27d8bae5d/`. La corrida consultada en solo lectura es `scenarios/zona1/montecarlo/run-bg180-c52934de7de1435ebc85867e0b728f50`, run_id `simz1-309d75ccb2d947629807a89d2e826987`. Se reutilizan los siete archivos pedidos y `effective_config_summary.json`; el check fija sus SHA-256 y guarda los eventos seleccionados de t=251 en su propia carpeta de resultados. No vuelve a recorrer los 117 millones de eventos ni modifica ese paquete.

La fixture carga los metadatos completos de red y carriles efectivos para conservar los dominios de almacenamiento y la geometría de conflictos. Sólo instancia colas del foco y enlaces de recepción necesarios; empieza con las dos cabezas. Usa `QLinkLanesImpl`, `QueueWithBuffer`, `Zona1QNodeImpl`, `StopAndYield`, `SimZ1RouteSafety` y el ledger reales. No sustituye ningún control por un GO. El adaptador del conductor conserva la ruta y su cursor; sólo avanza cuando el nodo nativo llama `notifyMoveOverNode`. La carga inicial reconstruye las entradas a `.lane.0` a 244 s para A y 246 s para B, y la disponibilidad a 250 s, a partir de `focus_state_history.json`. Después, el progreso utiliza pasos controlados de las colas nativas. Los dos nodos no tienen señal en los insumos efectivos. Se conservan clasificación `osm-hierarchy`, conflictos `geometric`, parada de 5 s y equidad local de 30 s. La geometría sigue siendo modelada; no se afirma cartografía GIS verificada.

La rama interna queda identificada así:

| Solicitante | Movimiento futuro evaluado | Nodo | Competidor real que lo veta |
|---|---|---|---|
| A: `z1_106044`, 2.1 m + 0.10 m | `osm_405188986_0_backward` → `osm_381667651_4_forward` | `579746301` | B: `osm_381667651_3_forward.lane.0` → `osm_405188986_0_forward` |
| B: `z1_49500`, 4.5 m + 0.10 m | `osm_405188986_0_forward` → `osm_406654687_7_forward` | `4074069083` | A: `osm_406654687_6_forward.lane.0` → `osm_405188986_0_backward` |

En ambos casos `preparePassage()` llega a `passageClear()`. Pasan las condiciones de cruces corporales anteriores, admisiones del paso, existencia de enlaces y receptor nativo, selección del carril, permiso de ruta y señal. Falla el bucle de avenidas de `StopAndYield.passageMayProceed()`: el movimiento futuro sale de una calle; existe otra cabeza real de avenida; `canCompete()` devuelve true; la pareja tiene conflicto geométrico; `sameParallelPassageEntrance()` devuelve false. El resultado específico es `priority_yield_conflict`, convertido por el ledger en `passage_control_or_crossing_wait`. No es una reserva de equidad, ocupación física ni señal roja.

Las consultas reales de `receiverFeasibility()` devuelven `receiver_available` para ambas cabezas. Sus tiempos internos de cabeza y disponibilidad son 251 s; el último movimiento del buffer es 250 s. No existen locks. En las fuentes originales, ambas solicitudes quedan WAIT también a 256 s, con preparación vacía: el retorno por prioridad sucede antes de iniciar el crédito de parada. El resultado se repite consultando A,B y B,A; no se atribuye el defecto a un orden de HashMap.

La primera reproducción instrumentada, todavía sin arbitraje, está en `runtime/c529-a-gtikyg9q/cycle.log`. El comando final además extrae las tres fuentes originales del commit `91d3ffce66bee80da3f0450e9d98a5a0316b3ec7`, verifica sus bytes contra `code_sources.json` de C529 y las compila en una carpeta aislada. `baseline-cycle.log` comprueba los dos WAIT con esas fuentes originales. Su código de salida 0 significa que reprodujo el fallo esperado, no que el escenario anterior progresó.

La reparación modifica estos métodos y responsabilidades:

| Archivo | Cambio autorizado |
|---|---|
| `UnsignalizedPriority.java` | `passageMayProceed()` conserva la decisión local y expone su causa y **todos** los competidores aplicables; `passageHeadReady()` reutiliza el reloj de parada de la cabeza real. No cambia `canCompete()`. |
| `Zona1QNodeImpl.java` | `passageClear()` distingue causas físicas, cruces, ruta, señal y prioridad; `passageHead()` verifica la cabeza ofrecida. Los resultados internos no emiten eventos nuevos. |
| `SimZ1CorridorOccupancy.java` | `preparePassage()` puede resolver un ciclo mediante `closedPriorityCycleWinner()`. `canEnter()` elimina decisiones preparadas obsoletas; la preparación de parada se identifica por ruta, cola y tiempo de cabeza. Adquisición y salida limpian esa identidad. |

El arbitraje sólo se intenta ante `priority_yield_conflict`. Recorre las dependencias actuales de esas cabezas, exige factibilidad física, disponibilidad del origen, todos los controles del pasaje y el mismo conjunto de nodos. Exige que todas las dependencias formen un componente fuertemente conexo cerrado: un tercero ordinario, una salida del ciclo, una reserva local de equidad o cualquier rechazo físico impiden la excepción. Elige la cabeza nativa más antigua y usa el ID como desempate estable, sin excepciones por nombres. Recalcula en cada consulta; no conserva una elección global ni adquiere reservas al consultar. La admisión efectiva sigue usando los locks existentes del pasaje completo y su liberación por tiempo **y** despeje corporal.

Con ambas cabezas históricas empatadas en antigüedad, A gana el desempate en los dos órdenes. Inicia su parada a 251, todavía espera a 255 y entra a 256. La fixture observa su despeje nativo a 260. B vuelve a competir, prepara desde 261, entra a 266 y despeja a 269. Son tiempos del contrafactual focal controlado, no nuevos eventos de la corrida histórica. Cada vehículo adquiere y libera una sola vez. `cycle.log` conserva los registros `TRACE`, `CONDITIONS`, `COMPETITOR`, `PROGRESS` y `RECEIPT`.

Las nuevas pruebas verifican también:

- Receptor ocupado por cuerpos reales en los tres slots: rechaza A y permite competir a B cuando sus controles lo permiten.
- Señal roja y ventana fija insuficiente: rechazan; una ventana suficiente recupera la decisión. Son variantes en memoria de la fixture, sin editar señales del escenario.
- Tercero ordinario realmente conflictivo: conserva su prioridad. Su cruce ejecutado y cuerpo sin despejar siguen bloqueando.
- Veinte consultas repetidas: no consumen ruta, no adquieren/liberan pasajes y no producen crecimiento de eventos de WAIT estable.
- Cambio de ruta del competidor: invalida la excepción cíclica. Cambio de ruta del solicitante y retorno: exige nuevamente su preparación de parada.
- Cambio de cabeza mediante movimiento nativo: conserva FIFO y separación de al menos 0.10 m; B, más antiguo, gana frente al sucesor de A.
- Exclusión del perdedor mientras están adquiridos los dos locks, sin liberar por timeout ni retirar vehículos.
- Entrada físicamente independiente en otro nodo y movimientos sin ciclo: conservan su comportamiento.

El resultado final está en `runtime/c529-a-mexkr_j3/`: comandos y códigos en `results.json`, identidades de fuentes compiladas en `sources.json`, insumos históricos en `historical-251.json` y conservación de 81 archivos en `preservation.json`. La ejecución focal termina con código 0. Se ejecutan con JDK17 las regresiones existentes `SimZ1PriorityReceiverCheck`, `SimZ1PriorityLookaheadCheck`, `SimZ1PassageFairnessCheck`, `SimZ1TenthStreetReceptionCheck`, `SimZ1DownstreamStorageCheck`, `SimZ1TransitPassageReleaseCheck` y `SimZ1TransitPassageNativeCheck`. Todas terminan en 0. `SimZ1PassageAffectedChecks` ejecuta únicamente las partes de ledger, comparación paralela, despeje y cuatro pruebas de temporizadores de las suites existentes cuyos otros métodos arrancan simulaciones; esas partes también terminan en 0.

`scripts/simz1_workflow.ps1` incorpora el nuevo check antes de escribir aprobaciones. La prueba de integración confirma que el fingerprint existente cubre los ocho archivos de producción, pruebas y workflow afectados. `python/test_simz1_sequence_contract.py` incorpora tres expectativas SHA-256 revisadas, con causa y cobertura; no excluye esas fuentes ni reescribe el baseline histórico. Se comprueban 108 entradas protegidas y pasan las siete pruebas de mutación, ausencia, hash histórico, recibo y fingerprint de `ProtectedSourceExpectationTests`. No se ejecuta la batería OD ni se modifica su lógica. `integration.json` registra `approval_written=false`.

Desde la raíz del repositorio, el comando reproducible es:

```powershell
.\.venv\Scripts\python.exe -B .\python\test_simz1_passage_cycle.py
```

Usa el JDK de `C:\Program Files\Java\jdk-17` o `SIMZ1_JDK17`, y las dependencias ya presentes en `target/classes`, `target/test-classes` y `target/simz1-runtime-classpath.txt`. Compila las fuentes afectadas en una carpeta nueva `runtime/c529-a-*`. No llama Controller, `QSim.run()`, Run1000, Validate completo, DryRun ni generación de demanda. No escribe recibos de aprobación.

Queda sin comprobar el efecto agregado sobre la descarga, rendimiento y otros focos de la corrida completa. La reparación deliberadamente no arbitra ciclos con conjuntos de nodos distintos o con una dependencia externa: mantiene su rechazo. Tampoco se prueba aquí un régimen paralelo del ledger; el caso efectivo usa un hilo QSim. No se cambia `requireApproved()`, OD, reruteo, geometría, dimensiones, capacidades, demanda, semillas, servicios, históricos ni visor/replay. La tarea termina en este mecanismo local.
