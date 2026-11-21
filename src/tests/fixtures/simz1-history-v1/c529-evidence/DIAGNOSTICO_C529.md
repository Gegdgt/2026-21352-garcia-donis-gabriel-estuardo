# SIMZ1 — Diagnóstico causal de C529

Diagnóstico únicamente. No se modificaron fuentes de producción, pruebas, escenarios, manifiestos, recibos ni resultados históricos; no se ejecutaron simulaciones, Maven, recompilación, Validate integrado, DryRun ni subagentes. Los scripts de este paquete son lectores y cálculos diagnósticos.

## Dictamen operativo

El fallo terminal es **`FREIGHT_NOT_APPROVED` en `SimZ1Freight.requireApproved()`**, llamado por `notifyIterationEnds()`. El controlador alcanzó el cierre de QSim; la excepción no es el inicio del atasco. Se rechazan 1492 expediciones de carga sin completar y 215 incumplimientos de permanencia, superpuestos con esos abortos.

La causa anterior comprobada es una pérdida progresiva de descarga con vehículos retenidos y rechazo de incorporación. El foco más temprano y mejor reconstruido está en **Avenida Elena / el conector modelado de 10a Calle**, desde **251 s (00:04:11)**. Dos cabezas reciben permiso local pero no obtienen autorización para su pasaje. La reconstrucción de los dos nodos y el código sustentan **un veto circular de prioridad entre pasajes futuros** como explicación de alta confianza. El evento agrupa varias ramas bajo `passage_control_or_crossing_wait`: falta la identificación directa de la rama y del competidor para elevar esa inferencia a una prueba ejecutable del defecto del motor. No se demuestra que este único foco explique todos los bloqueos posteriores.

El rechazo OD del monitor tiene otra causa demostrada: un reruteo nativo omite un enlace obligatorio del gateway de salida. **El vehículo llega cinco segundos después del rechazo del lector.** Este error no detuvo QSim y tampoco originó el foco de 251 s, que lo precede.

- Última transición y última llegada de toda la red: **72061 s (20:01:01)**, ambas del bus `ptbus_transmetro_L2_003`.
- Intervalo final continuo sin transiciones ni llegadas: **después de 72061 hasta 86401 s**; primer paso entero sin descarga, **72062 s**. Duración entre la última descarga y la observación final: **14340 s = 3 h 59 min**; siguen 6861 vehículos dentro de la red.
- Los particulares ya no transitan después de **33512 s (09:18:32)**; los camiones, después de **35547 s (09:52:27)**. La última llegada privada es a 31560 s y la última de carga a 16364 s.
- Último cálculo de reruteo: **31920 s (08:52:00)**; desde **31980 s (08:53:00)** el conjunto de enlaces que activa el disparador queda vacío.
- Cobertura completa: **117935374 eventos**, gzip íntegro y XML cerrado. No son contadores de un prefijo.

## 1. Identidad, revisión y cobertura

- Repositorio: `C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala`.
- Corrida exclusiva: `scenarios/zona1/montecarlo/run-bg180-c52934de7de1435ebc85867e0b728f50` (en adelante **RUN**).
- Run ID: `simz1-309d75ccb2d947629807a89d2e826987`.
- Launch ID: `c52934de7de1435ebc85867e0b728f50`; evidencia: `runtime/launches/c52934de7de1435ebc85867e0b728f50` (**LAUNCH**).
- `LAUNCH/state.json`: `failed`, fase `verify_result`, `native_status=failed`, `native_validation=invalid`, salida 1. `RUN/run-manifest.json`: `failed/invalid`, `returncode_origin=natural_exit`, iteraciones solicitadas `[0]`, completadas `[]`.
- Coinciden 180000 no públicos = 79200 carros + 99000 motos + 1800 camiones; 178200 particulares y 269 buses adicionales. OD privado EE/EI/IE/II = 89100/35640/35640/17820 (50/20/20/10); semillas de demanda y MATSim 20261023; variante `balanced-gateway-v1`.
- Fecha de servicio fijada: 2026-10-23; fecha real de ejecución del log: 2026-11-01. No son la misma referencia temporal.
- Se verificaron **42 referencias de insumos** del manifiesto y las **19 firmas Python** del contrato OD: todas coinciden. Algunas referencias apuntan al mismo archivo; 42 no significa 42 archivos distintos.
- La huella actual coincide exactamente con la del lanzamiento: `e16a53773f31334ab0a1c54087d88981cedb71cf720cb0c8784abce04cc28588`. HEAD inspeccionado: `91d3ffce66bee80da3f0450e9d98a5a0316b3ec7`; árbol y diff de producción limpios. El manifiesto no declara un commit histórico: la igualdad demostrada es la de la huella protegida de fuentes/configuración, no una asociación inventada con un commit.

No existe `output/output_config.xml` en esta corrida fallida. Se recuperó la configuración materializada de **`matsim-run.log:1398–2089`**, guardada aquí como `effective_config_from_log.xml`. Los parámetros explícitos del archivo fijado coinciden semánticamente; las únicas diferencias textuales son `5`/`5.0`, `30`/`30.0`, `10`/`10.0`. Se observan QSim con 1 hilo, FIFO/queue, señales activas, `strict-receiver-v1`, reserva de cuerpo entero, `removeStuckVehicles=false`, `stuckTime=10`, actualización rápida de capacidad desactivada, `onlyUseEndtime`, horizonte 86400. El módulo materializado fija reruteo activo, fracción 0.5 y presupuesto **100 por paso de reruteo**. `network.inputChangeEventsFile=null` e incidentes desactivados: no hay cambios programados de capacidad/velocidad que expliquen el disparador de reruteo. Los 12 hilos globales no equivalen a 12 hilos QSim.

Se usaron red y carriles efectivos `inputs/transit-weekday/{network,lanes}.xml`, señales `inputs/signalsystems-*.xml`, vehículos y contratos guardados bajo RUN, planes fijados `RUN/plans.xml`, auditoría de carga y eventos de it.0. No se seleccionó otra corrida, `latest-successful` ni una carpeta de análisis anterior. No apareció un log persistido del monitor en RUN/LAUNCH: su rechazo se reprodujo desde los eventos. Su hora real de lectura original no está disponible.

Se leyó incrementalmente el archivo de eventos completo de **3914696837 bytes comprimidos**, desde t=0 hasta **86401.0 s**, con **117935374 eventos**. La lectura alcanzó EOF y comprobó el CRC gzip; Expat terminó de validar la estructura XML y su cierre sin error. La segunda lectura independiente contó el mismo número de eventos. Retrocesos de tiempo global detectados: **0**. SHA-256 de los eventos: `8dd526c2e6e43c56427cfc7e95b1bf73165875c715b803744f0a8fa1cd8a4fbd`. No se descomprimió un XML completo a disco ni se cargó en RAM.

`identity.json`, `source_provenance.json`, `effective_config_summary.json` y `code_sources.json` registran identidades, firmas, tamaños y fuentes; `terminal_error_extracts.json` conserva el error, incluido `LAUNCH/06-simulation-and-analysis.log:32350`.

La posición `event_index` es ordinal de evento, comenzando en 1; `xml_line` es la línea del XML descomprimido, sin guardar ese XML completo. Las referencias `E#n` de este informe apuntan siempre a `RUN/output/ITERS/it.0/0.events.xml.gz`. Los extractos de prefijo declaran su límite propio; sus contadores no se presentan como totales del día. Las posiciones modeladas son cotas del ledger, con `positionsObserved=false`, no mediciones microscópicas ni cartografía GIS verificada.

Las clases Java citadas están bajo `src/main/java/gt/edu/uvg/sim/zona1/`, salvo `SimZ1CorridorOccupancy`, `Zona1QNodeImpl` y `QueueWithBuffer`, bajo `src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/`. `code_excerpts.txt` conserva las líneas numeradas reales y `code_sources.json` sus rutas y firmas.

## 2. Cuándo se deteriora y cuándo cesa la descarga

Hay tres escalas distintas:

1. **Foco local persistente:** las cabezas ocupan sus enlaces a 242 y 246 s; el primer rechazo conjunto de pasaje es a **251 s**. No es correcto fechar el problema en 74460 s.
2. **Deterioro de red:** las transiciones por hora bajan de 85660 (00–01) a 68162 (01–02) y 49998 (02–03), mientras suben los vehículos activos. Hay recuperación agregada posterior: 56699 (04–05) y 79437 (05–06). Desde 06–07 la descarga cae a 71209, luego 36110 (07–08), 18615 (08–09), y solo 1086 (09–10). Estas cifras describen la descarga observada; no constituyen una estimación de capacidad máxima calibrada.
3. **Servicio residual y detención global final:** quedan unos 6861–6863 vehículos mientras persisten unos pocos movimientos. Una meseta de activos no basta para afirmar cero descarga. Las horas 10–20 todavía tienen 325–334 transiciones y 36–38 llegadas por hora, y 20–21 conserva 7 transiciones y 2 llegadas. Después cesa ese flujo residual.

| Clase | Última transición | Última llegada | Última incorporación |
|---|---|---|---|
| Particulares | 33512.0 / 09:18:32; z1_150098; E#33350798 | 31560.0 / 08:46:00; z1_106598; E#30283735 | 33563.0; z1_164324; E#33431081 |
| Carga | 35547.0 / 09:52:27; freight_000719; E#36561843 | 16364.0 / 04:32:44; freight_000597; E#8113251 | 35649.0; freight_000721; E#36724308 |
| Transporte público | 72061.0 / 20:01:01; ptbus_transmetro_L2_003; E#94754581 | 72061.0 / 20:01:01; pt_ptbus_transmetro_L2_003_Transmetro_RigidProxy; E#94754590 | 71966.0; ptbus_transmetro_L2_003; E#94603518 |

La última transición global es `E#94754581`, XML 94754583, y la llegada `E#94754590`, XML 94754592. El bus acaba en `osm_1057741805_2_forward`; persona conductora `pt_ptbus_transmetro_L2_003_Transmetro_RigidProxy`, vinculada por los eventos de servicio/incorporación. El flujo residual después de 35547 s corresponde exclusivamente a buses. Hubo pausas anteriores y recuperación: por ejemplo **36906→36988 s**, 82 s sin transiciones/llegadas y luego movimiento. Esa es la mayor pausa cerrada observada antes del intervalo final; no debe confundirse con la detención definitiva.

En el log, el último intervalo no vacío termina en **72120 s**, línea **5103**; el primer intervalo completo posterior con ambos contadores en cero termina en **72180 s**, línea **5105**. La fila final `before_cleanup` está en **86401 s**, línea **5653**, con 6861 activos, ninguna transición/llegada y todavía intentos de espera. `SimZ1Diagnostics.java:112–140` calcula diferencias entre reportes: los contadores por minuto no son acumulados. `activeVehicles` es un estado instantáneo, y `linkTransitions` cuenta eventos `LinkEnter` (`SimZ1Diagnostics.java:47–58`), no velocidad ni distancia.

| Hora simulada, intervalo (inicio,fin] | Activos al final | Transiciones | Llegadas | Intentos storage | Cálculos reruteo |
|---|---|---|---|---|---|
| 00–01 | 339 | 85660 | 1057 | 31234 | 73 |
| 01–02 | 517 | 68162 | 863 | 67241 | 42 |
| 02–03 | 779 | 49998 | 550 | 114032 | 1 |
| 03–04 | 1091 | 49774 | 531 | 191597 | 9 |
| 04–05 | 1661 | 56699 | 609 | 300982 | 40 |
| 05–06 | 3012 | 79437 | 771 | 573499 | 1015 |
| 06–07 | 4936 | 71209 | 549 | 1036160 | 1416 |
| 07–08 | 6153 | 36110 | 275 | 1487212 | 1157 |
| 08–09 | 6748 | 18615 | 153 | 1733312 | 589 |
| 09–10 | 6862 | 1086 | 36 | 1853511 | 0 |
| 10–11 | 6863 | 325 | 36 | 1862910 | 0 |
| 11–12 | 6861 | 331 | 38 | 1862910 | 0 |
| 12–13 | 6862 | 334 | 36 | 1862910 | 0 |
| 13–14 | 6863 | 325 | 36 | 1862910 | 0 |
| 14–15 | 6861 | 331 | 38 | 1862910 | 0 |
| 15–16 | 6862 | 334 | 36 | 1862910 | 0 |
| 16–17 | 6863 | 325 | 36 | 1862910 | 0 |
| 17–18 | 6861 | 331 | 38 | 1862910 | 0 |
| 18–19 | 6862 | 334 | 36 | 1862910 | 0 |
| 19–20 | 6863 | 325 | 36 | 1862910 | 0 |
| 20–21 | 6861 | 7 | 2 | 1862910 | 0 |
| 21–22 | 6861 | 0 | 0 | 1862910 | 0 |
| 22–23 | 6861 | 0 | 0 | 1862910 | 0 |
| 23–24 | 6861 | 0 | 0 | 1862910 | 0 |

En total se observaron **12623 incorporaciones de expediciones**: 10849 privadas, 523 de carga y 1251 públicas. Estas últimas pertenecen a **238 buses distintos** de los 269 configurados. No son 12623 vehículos de flota distintos ni 180000 vehículos simultáneos. Son llegadas nativas, no una certificación del contrato OD. Las llegadas suman 4405 privadas + 308 de carga + 1049 públicas = **5762**; las transiciones, **520052**. `cronologia_log.csv` conserva cada intervalo de 60 s, sus esperas y la hora real; `cronologia_eventos.csv` usa intervalos horarios [inicio,fin), por lo que los eventos exactamente en la frontera pueden ir a horas distintas.

`waitStorage`, `waitPriority` y `waitSignal` son **intentos de decisión**, que pueden repetirse sobre las mismas cabezas y cambiar de razón durante un ciclo de señal. No representan vehículos distintos ni segundos de espera. `threadDeadlocks=0` no descarta ciclos entre colas o solicitudes; solo evita confundirlos con interbloqueos detectados por la JVM. No se observaron movimientos forzados ni remociones por `stuckTime`. La política estricta conserva WAIT en ese caso (`Zona1QNodeImpl.java:532–539`).

Las horas reales son las del proceso de esta corrida, en Guatemala (UTC−6): inicio del lanzamiento 15:40:29; comienzo registrado del proceso de corrida 16:06:36; log de simulación t=0 a 16:07:32.121; observación previa al cierre a 16:34:14.226; llamada de carga a 16:34:20.317; estado del launcher terminado a 16:34:35. El lector diagnóstico procesa el archivo después del cierre: su tiempo de lectura y el tiempo simulado no son la hora del proceso. No se conoce el retraso del monitor original.

## 3. Foco temprano y dependencias aguas abajo

**Certeza alta sobre los hechos y la rama general; inferencia de alta confianza sobre el veto circular; alcance local y su propagación documentada.** Nombres tomados de los atributos de la red guardada.

| Conductor = vehículo | Tipo | Última incorporación/transición al enlace | Cola de cabeza comprobada a 251 s | Solicitud inmediata | Receptor posterior según su ruta |
|---|---|---:|---|---|---|
| `z1_106044` | Motociclista, cuerpo 2.1 m, huella 2.2 m | `osm_406654687_6_forward`, 242 s | `.lane.0` | `osm_405188986_0_backward.original` | `osm_381667651_4_forward` |
| `z1_49500` | Liebre/carro, cuerpo 4.5 m, huella 4.6 m | `osm_381667651_3_forward`, 246 s | `.lane.0` | `osm_405188986_0_forward.original` | `osm_406654687_7_forward` |

Evidencia central:

- `E#57883`: `z1_106044` es `HEAD`, nodo **4074069083**, a 251 s, listo inmediatamente; `E#57884`: permiso local `GO/permission_not_crossing`.
- Durante esa secuencia se observa la cabeza opuesta `z1_49500` en el nodo **579746301**, `E#57886`, también lista a 251 s.
- `E#57887`: WAIT del ledger para el pasaje hacia `_backward`, motivo **`passage_control_or_crossing_wait`**; `E#57888`: el diagnóstico nativo lo clasifica `storage_wait`, con receptor original **0 PCU usados / 0.5555556 PCU de capacidad**, ninguna cola receptora ofreciendo vehículos y `nativeHasGreen=true`.
- `E#57918`: el segundo conductor obtiene su permiso local; `E#57920`: WAIT de pasaje hacia `_forward` por el mismo motivo; `E#57921`: `storage_wait` nativo. Ambos siguen esperando en los extractos posteriores.
- Antes de t=251 había **101 vehículos en tráfico**. En el estado después de t=251 los dos conectores y los enlaces receptores están vacíos. El ledger reconstruido tiene cero metros usados en sus slots: capacidad útil de conector 2.252743 m backward y 3.752711 m forward; corredor receptor `_381667651_4_forward` con tres slots de 453.682270 m y receptor `_406654687_7_forward` con dos slots de 33.538350 m. Estas capacidades son del dominio modelado, no necesariamente de un solo enlace.
- No hay pasajes adquiridos que mantengan locks sobre esos dos nodos en ese estado. Las reservas de los dos solicitantes permanecen en sus corredores de origen. **Un evento de reserva con `action=WAIT`, `modelSlot=-1`, `reservationOrdinal=0` no es una reserva adquirida.**

Los conectores cortos requieren una autorización de pasaje completo hacia un receptor donde pueda detenerse el cuerpo. Que el conector esté vacío no autoriza por sí solo a entrar. Aquí la autorización llegó hasta `preparePassage()` y fue rechazada en `node.passageClear()` (`SimZ1CorridorOccupancy.java:820–840`, especialmente 829); no es el rechazo `passage_receipt_storage_or_slot` ni `passage_node_locked`.

La dependencia reconstruida es:

`z1_106044 → salida del pasaje backward en nodo 579746301 → cabeza de avenida z1_49500 → salida del pasaje forward en nodo 4074069083 → cabeza de avenida z1_106044`.

`UnsignalizedPriority.StopAndYield.passageMayProceed()` consulta las cabezas reales de avenida que compiten con el movimiento futuro del conector, clasificado como calle; `canCompete()` consulta **factibilidad física**, no si ese competidor conseguirá también su autorización de prioridad aguas abajo (`UnsignalizedPriority.java:154–166, 210–220`; `SimZ1CorridorOccupancy.java:456–467`). Las dos parejas resultan `conflicting_or_ambiguous` bajo la geometría exacta de `PriorityMovements.java:43–88`, reproducida con los nodos guardados. La excepción `sameParallelPassageEntrance` no corresponde a solicitantes en dominios y sentidos distintos. La reserva de equidad se concede a cabezas reales de calle (`UnsignalizedPriority.java:188–207`); estos solicitantes siguen retenidos en las avenidas, antes de esas calles.

Esto explica por qué pueden vetarse sin ocupar los receptores. **Límite:** `Zona1QNodeImpl.passageClear():570–584` devuelve un booleano por conflictos retenidos, movimientos del paso, recepción, carril, señal o prioridad. El WAIT no guarda cuál de esas condiciones fue falsa ni el ID del competidor. El código y los estados descartan varias explicaciones y sostienen fuertemente el ciclo; no sustituyen una captura directa de esa rama. La comprobación mínima faltante es reproducir esas dos solicitudes con el estado de 251 s y registrar/revisar esa devolución y ambos `canCompete`, sin ejecutar demanda masiva.

No se justifica atribuir este inicio únicamente al volumen solicitado N=180000: el foco aparece con 101 vehículos ya incorporados y receptores libres. Eso tampoco demuestra que la configuración pueda descargar satisfactoriamente toda la demanda de 180000; falta el contrafactual del foco resuelto con la misma demanda.

### Propagación comprobada hacia carga y 14 Calle

En el estado anterior a 18000 s, los eventos `simz1OccupancyProgress` contienen la cadena explícita de líderes:

`freight_000016 → z1_167087 → z1_39505 → z1_106044`.

El camión, ruta **west-north-elena**, entró al tráfico a **375 s** (`E#104502`) y al enlace `_406654687_6_forward` a **383 s** (`E#107676`). Su reserva de 8.1 m ocupa el slot 0. `E#647858`, a 1291 s, identifica `leaderVehicle=z1_167087`; la cadena termina en la cabeza ya bloqueada. Esto demuestra una dependencia de carga concreta, sin inventar posiciones ni atribuir a un seguidor una decisión de cabeza.

Más atrás se observan rechazos reales de recepción:

- `z1_123586`, `_406654687_5_forward.lane.1 → _406654687_6_forward.original`, a **1086 s**: 6.0 PCU de carga receptora frente a 5.076914 PCU de capacidad.
- `z1_49847`, `_384737905_41_forward.lane.0 → _384737905_42_forward.original`, a **2408 s**: 4.0 / 1.111111 PCU.
- `z1_67994`, `_384737905_40_forward.lane.0 → _384737905_41_forward.original`, a **3231 s**: 11.75 / 10.839018 PCU.
- `freight_000119`, ruta **east-west-14calle**, llega a `_384737905_39_forward` a **3601 s**. A **3649 s**, `E#2007306`, solicita `_384737905_40_forward` y recibe `storage_wait` **con señal GREEN**. Una observación roja posterior no prueba que un rojo permanente cause su retención.

La secuencia de receptores va desde los enlaces 39→40→41→42 de `_384737905`, hacia `_406654687_3_forward` y los dominios de Elena 3/4 y 5/6. Un enlace nativo vacío puede pertenecer a un dominio ocupado por vehículos en otra subdivisión: a 18000 s el dominio Elena 3/4 retiene 47.4 y 47.6 m en slots de 52.412 m; el dominio 5/6 retiene 95.6 y 85.3 m en slots de 127.273 m, con solo 3.016 m de frente libre modelado. La suma de metros libres del dominio no equivale a una entrada compatible libre junto al receptor.

Los PCU citados excluyen el buffer según el propio evento y no son coordenadas físicas. Las cotas métricas proceden de reservas/progreso y se guardan separadas. No se demuestra una liberación omitida de reservas ni un defecto de recuperación de crédito de flujo en estos ejemplos. En el foco original las cabezas ya estaban ofreciéndose y obtenían GO local, lo que lo distingue de un vehículo inmovilizado antes de alcanzar el buffer.

La lectura completa confirma que estos actores permanecen activos justo antes de la limpieza; no se infiere persistencia solo a partir del prefijo inicial:

| Vehículo | Último cambio de enlace | Enlace al cierre | Última decisión | Razón nativa | t último WAIT del ledger | Última razón del ledger |
|---|---|---|---|---|---|---|
| z1_106044 | 242.0 | osm_406654687_6_forward | 86401.0 | storage_wait | 251.0 | passage_control_or_crossing_wait |
| z1_49500 | 246.0 | osm_381667651_3_forward | 86401.0 | storage_wait | 251.0 | passage_control_or_crossing_wait |
| z1_111853 | 335.0 | osm_406654687_6_forward | 86401.0 | storage_wait | 344.0 | passage_control_or_crossing_wait |
| freight_000016 | 383.0 | osm_406654687_6_forward | sin decisión propia de cabeza | sin decisión propia de cabeza | — | sin WAIT propio de recepción |
| freight_000119 | 3601.0 | osm_384737905_39_forward | 86401.0 | signal_red | — | sin WAIT propio de recepción |

El censo de pasajes adquiridos aún retenidos antes del cierre es **0** (`retained_passages_before_cleanup.json`). En esta corrida no quedan locks de pasajes adquiridos que expliquen la detención final; el ciclo inferido corresponde a solicitudes pendientes de autorización. Los actores y campos modelados de los 6861 vehículos quedan en `vehiculos_activos_antes_limpieza.csv`; `focus_state_history.json` conserva los estados focales y sus posiciones de evidencia, sin presentar esa selección como un censo de todas las causas.

## 4. Por qué se rechazaron los camiones

**Certeza alta, alcance: las 1800 filas y sus eventos terminales.**

| Estado terminal | Entraron al tráfico | Cumplimiento de permanencia | Cantidad |
|---|---|---|---:|
| completed | sí | no_violation_observed | 308 |
| aborted | sí | violated | 215 |
| aborted | no | no_violation_observed | 1277 |

No hay camiones `not_departed`, `aborted_before_departure` ni `active_or_censored` en la auditoría final. **Los 1800 emitieron `departure`; solo 523 se incorporaron.** Los 1492 restantes están incompletos como viajes y clasificados como abortados, todos a 86401 s. Los dos eventos terminales `vehicle aborts` y `stuckAndAbort` se reconcilian en una sola expedición abortada: no se suman como dos camiones.

En esta revisión, `restricted` es `violations.size()`: vehículos únicos con algún intervalo **desde entrada real al tráfico hasta un evento observado** que no cabe completo en una ventana permitida (`SimZ1Freight.java:153–168`). No significa giros restringidos, peso incompatible ni simplemente una salida programada fuera de hora.

Las ventanas son `[0,18000)`, `[32400,57600)` y `[75600,104400)` para `weekday_overnight_until_05_v2` (`SimZ1Freight.java:74–79`). Los horarios guardados y los eventos `departure` coinciden dentro de la tolerancia de un paso; no se encontró programación fuera de esas ventanas. La política nocturna permite permanecer hasta las 05:00 siguientes, pero esta corrida termina a las 24:00: no se inventa una llegada ni se extiende retrospectivamente el horizonte.

`completed` exige una llegada real al último enlace, habiendo seguido la secuencia completa; entonces se elimina el estado activo y se registra `Terminal("completed",...)` (`SimZ1Freight.java:226–245`). `approved()` exige además ausencia de violaciones, ausencia de activos y todos los terminales completados. Por eso un hipotético camión completado y restringido pertenecería a ambas dimensiones; aquí los 215 restringidos son un subconjunto de los 1492 abortados.

La limpieza final elimina los activos al procesar abortos y registra `Terminal("aborted",...)` (`SimZ1Freight.java:246–263`). Así se obtiene **`active_or_censored=0` con solo 308 completados**. Los 1277 que nunca entraron no infringieron permanencia en tráfico; la etiqueta `no_violation_observed` no convierte su viaje en satisfactorio.

Las primeras observaciones de infracción se distribuyen así: **25 a 18000 s**, **21 a 57600 s**, **169 a 86401 s**. Estas últimas no demuestran que la infracción comenzara al cierre: `residence()` se invoca ante eventos del vehículo, no mediante un temporizador por camión. Los seguidores silenciosos pueden permanecer fuera de ventana y ser detectados recién por el aborto. De los 215, 154 entraron en la ventana de madrugada y 61 durante la diurna; los 169 detectados al final incluyen 129 y 40, respectivamente.

| Ruta fija | Ventana de salida | Completos | Abortados tras entrar (restringidos) | Abortados sin entrar |
|---|---|---|---|---|
| east-west-14calle | 00-05 | 17 | 133 | 0 |
| east-west-14calle | 09-16 | 0 | 30 | 188 |
| east-west-14calle | 21-next05 | 0 | 0 | 82 |
| north-south-2avenida | 00-05 | 138 | 12 | 0 |
| north-south-2avenida | 09-16 | 0 | 0 | 218 |
| north-south-2avenida | 21-next05 | 0 | 0 | 82 |
| south-north-7avenida | 00-05 | 150 | 0 | 0 |
| south-north-7avenida | 09-16 | 0 | 31 | 187 |
| south-north-7avenida | 21-next05 | 0 | 0 | 82 |
| west-north-elena | 00-05 | 3 | 9 | 138 |
| west-north-elena | 09-16 | 0 | 0 | 217 |
| west-north-elena | 21-next05 | 0 | 0 | 83 |

La reconciliación por ID entre CSV y eventos comprueba las 1800 salidas, 523 incorporaciones, 308 llegadas y ambos eventos terminales de cada uno de los 1492 abortos; **cero discrepancias** (`freight_event_reconciliation.json`).

Ejemplos contrastables: `freight_000001` completa a 524 s; `freight_000016` queda detrás de la cadena de Elena y su infracción se registra por `vehicle aborts` a 86401 s; `freight_000119` espera con verde por recepción en 14 Calle y es detectado fuera de ventana a 18000 s; `freight_000601` sale/entra a 32454 s y su permanencia infringe la ventana a 57600 s; `freight_000048` sale a 1338 s pero nunca entra al tráfico y termina abortado. Véanse `estados_carga.csv`, `freight_events.json`, `carga_por_ruta_ventana.csv` y los extractos seleccionados.

El rechazo final es coherente con la circulación e incorporación fallidas y el horizonte alcanzado. **No se ha demostrado un defecto de la auditoría de carga.** No corresponde eliminar `requireApproved()`, reinterpretar abortos como completados ni renovar aprobaciones.

## 5. Rechazo del monitor y contrato privado OD

**Defecto demostrado de conservación del contrato en el reruteo instalado; certeza alta para este caso.**

- Persona y vehículo: **`z1_60650`**, Liebre/carro, clase **EE / `EXTERNAL_EXTERNAL_THROUGH`**, `simz1TripId=z1_60650:trip:0001`.
- Salida programada 705.807399 s; incorporación real **706 s**, `E#275366`, con persona y vehículo idénticos.
- Ruta inicial guardada y `simz1SpatialOD`: contienen el sufijo obligatorio `osm_1196283991_0_backward → osm_60237264_2_forward → osm_60237264_3_forward`.
- Último reruteo anterior: **720 s**, `E#283199`, `zona1WithinDayReroute`, `changed=true`, razón `validated_improvement`; índice 2, enlace físico y lógico `osm_30288333_3_forward`, carril `.original`. Costo/tiempo estimado anterior 488 s, candidato 358.458436 s.
- El candidato mantiene el destino `_60237264_3_forward`, pero llega por `_60237264_0_forward → _60237264_1_forward → _60237264_2_forward → _60237264_3_forward`; omite `_1196283991_0_backward` y el desvío previo que lo alcanzaba.
- Evento rechazado: **1106 s**, `E#527208`, línea XML **527210**, `entered link` en `_60237264_2_forward` (cruce de salida). La secuencia observada llega directamente desde `_60237264_1_forward`, no desde la observación obligatoria `_1196283991_0_backward`.
- Método: **`PrivateODAudit.validate_observed_route()`**, `python/simz1_balanced_od_audit.py:290–299`, llamado por `consume():394`. Al localizar el cruce, compara el sufijo observado con la cadena completa. La llamada al método original sin caché reproduce exactamente **`Private route skipped part of its verified exit chain`**.
- A **1111 s** el mismo actor emite salida del tráfico `E#531336` y llegada `E#531338`. Son eventos nativos posteriores al rechazo del lector; no una llegada aprobada por OD.

No hay incoherencia inicial de esa ruta, confusión persona/vehículo ni repetición del cruce que explique el rechazo. El lector distingue el LinkEnter inicial duplicado (`simz1_balanced_od_audit.py:382–387`); el fallo sucede en un cruce posterior, recorrido una sola vez. La coincidencia del error no se obtuvo desactivando el auditor.

`SimZ1RouteSafety.validateReplacement():253–269` verifica red, índice, enlace actual, prefijo recorrido, destino y carril. No recibe un contrato de viaje privado. `CongestionAwareRerouting.attempt():232–277` usa esa validación, la comprobación de reservas y la mejora de costo para instalar el candidato, pero no comprueba el gateway privado. No se encontró lectura de `simz1SpatialOD` ni `simz1TripId` en las fuentes Java de producción inspeccionadas.

El ReRoute estándar resuelve el binding `car` de `ExperiencedTimeRouting.configure():60–68`, cuyo `sequenceRouting():79–99` llama a `SimZ1TurnRouter.path(from,to,...)`. Este router controla conectividad, movimientos y contrato OSM de secuencias (`SimZ1TurnRouter.java:74–112`), pero tampoco impone las cadenas privadas por viaje. Es una omisión estática de ese camino; **no se atribuye este evento a ReRoute entre iteraciones**: la evidencia instalada es within-day y esta corrida solo ejecuta it.0.

`simz1_balanced_launch_report.py` es un consumidor de eventos; `watch():231–270` llama al auditor y no controla QSim. No se encontró evidencia de que el fallo del lector enviara una orden de terminación al proceso nativo. El bloqueo local de 251 s precede incluso al reruteo de 720 s de este caso. No está demostrada una conexión causal entre el error OD y la detención global, aunque ambos invaliden aspectos distintos de los resultados.

Como control de identidad histórica, **`z1_97936` sí se incorpora a 1 s y llega a 669 s en C529** (`E#253712`). No recurrió aquí su antiguo fallo inicial.

## 6. Por qué desaparecen los cálculos de reruteo

La configuración efectiva y los eventos confirman:

- Evaluación cada **60 s**, presupuesto **100 por evaluación**, no un presupuesto acumulado del día (`CongestionAwareRerouting.java:299–300, 340–352`).
- Cohorte fija de **50%**, seleccionada por mezcla determinista; se excluye carga y transporte público. Los agentes deben estar en un leg `car`, tener ruta nativa y esperar **300 s** después de un cálculo anterior (`:138–140, 323–333`).
- Las observaciones se actualizan al **salir** de un enlace, a partir de un `LinkEnter` previo. El enlace parcial de incorporación no se registra como una observación completa. Los vehículos públicos se excluyen de esas observaciones (`:76–109`).
- Una observación es fresca durante **300 s inclusive**; después se devuelve NaN (`:111–120`). El estimador comienza con tiempo libre del enlace y solo lo eleva con una observación fresca (`:306–312`).
- Congestión severa requiere estimación ≥3 veces nominal y exceso ≥60 s, o capacidad actual ≤50% de la base (`:127–132`). Sin cambios de red/incidentes, el segundo disparador no interviene aquí.
- La búsqueda de enlaces severos para cada candidato usa `full.subList(index+1,...)`: **excluye el enlace actual** (`:338`). No lee directamente la edad de una cola sin salidas para marcarlo severo. Si el conjunto severo queda vacío, retorna antes de evaluar candidatos (`:322`).

La reconstrucción independiente usa los mismos `LinkEnter`/`LinkLeave`, el registro de flota pública y la red fijada; no ejecuta el router. A **31920 s** quedan seis enlaces severos. Sus últimas observaciones son de 31657–31669 s; a la siguiente evaluación, **31980 s**, tienen 311–323 s de edad y caducaron. Todavía quedan 67 observaciones frescas de otros enlaces, pero ninguna supera el umbral. Desde allí, las **908 evaluaciones restantes** tienen cero candidatos y cero cálculos, con presupuesto 100. Desde **35880 s** tampoco queda ninguna observación no pública fresca. Los buses siguen moviéndose, pero están excluidos del estimador.

Un ejemplo exacto es `osm_1057486080_2_forward`: 209 s observados al salir a 31658 s, tiempo nominal 2.953278 s; a 31920 sigue severo (edad 262), a 31980 caducó (edad 322). En el foco de Elena, el último dato de `_406654687_6_forward` es apenas **9 s, observado a 285 s**; `_381667651_3_forward` ni siquiera obtiene una observación completa. Esos datos no representan la espera de las cabezas que permanecen en ambos enlaces.

| t | Enlaces severos | Observaciones frescas | Candidatos | Cálculos | Instalados | Rechazos | Diferidos | Presupuesto |
|---|---|---|---|---|---|---|---|---|
| 31800 | 7 | 125 | 2956 | 6 | 0 | 100 | 2856 | 100 |
| 31860 | 6 | 100 | 2203 | 15 | 6 | 94 | 2103 | 100 |
| 31920 | 6 | 79 | 2214 | 17 | 10 | 90 | 2114 | 100 |
| 31980 | 0 | 67 | 0 | 0 | 0 | 0 | 0 | 100 |
| 32400 | 0 | 29 | 0 | 0 | 0 | 0 | 0 | 100 |
| 35880 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 |
| 86400 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 |

En todo el día hay **4342 cálculos**, **2724 instalaciones**, **23509 rechazos de intento** y **293119 diferimientos**. Los candidatos sumados y diferimientos son intentos repetibles, no personas distintas. Antes del apagado del disparador sí hubo competencia por el presupuesto: a 31920 se consideran 2214 candidatos, se intentan 100 y se difieren 2114; solo 17 llegan al cálculo. La distinción se explica por los rechazos previos a `step.calculations++`.

| Resultado de intento | Cantidad |
|---|---|
| validated_improvement | 2724 |
| physical_vehicle_or_lane_not_ready | 21891 |
| no_expected_improvement | 1607 |
| occupancy_active_passage_prefix | 5 |
| occupancy_active_passage_clearance | 5 |
| occupancy_incompatible_passage_signals | 1 |

La reproducción aritmética de `Collections.shuffle` con semilla 20261023 da una cohorte de **89100 particulares**. Las dos primeras cabezas, `z1_106044` y `z1_49500`, están **fuera** de ella; no recibieron intentos. Las otras cabezas `z1_111853` y `z1_39556` sí pertenecen y tampoco tienen decisiones registradas de reruteo. Por tanto, una corrección de caducidad por sí sola no habría reruteado necesariamente a las dos cabezas originales. No hay una alternativa de escape demostrada para ellas. Véanse `reroute_trigger_timeline.csv`, `routing_observation_summary.json` y `rerouting_decisions_summary.json`.

La caducidad y la exclusión del enlace actual son comportamiento reproducible por lectura de las expresiones; la pérdida del disparador está contrastada con eventos de esta corrida. Se trata de una limitación de observabilidad del reruteador bajo inmovilidad, no de agotamiento del presupuesto. El foco temprano ya existe miles de segundos antes de desaparecer los cálculos. **No se demuestra que esa limitación originara el atasco ni que hubiera una ruta alternativa admisible y utilizable para liberarlo.** Un cálculo adicional podría ser rechazado por carril, secuencia, gateway, reserva, recepción o falta de mejora.

## 7. Limpieza y fallo terminal

Antes del marcador de limpieza, a **86401 s**, hay **6861 vehículos en tráfico**, **6861 reservas** y **0 pasajes activos. Los vehículos se distribuyen en **6444 privados, 215 camiones y 202 buses**. Los demás viajes pendientes no deben contarse como ocupación de la red.

El marcador `simz1FreightCleanupStart` es **E#117500535**, línea XML 117500537. Después se emiten **175545 `vehicle aborts`** y la misma cantidad de `stuckAndAbort`, a 86401 s: **173795 particulares + 1492 camiones + 258 expediciones públicas**. Entre los abortos, 168684 no habían entrado al tráfico; otros 6861 estaban dentro. Los abortos son cierre/censura de expediciones, no llegadas ni descarga.

Al terminar el archivo, el reconstruidor registra **0 vehículos activos, 0 reservas y 0 pasajes** según los eventos emitidos. Esto describe la limpieza y no modifica la observación previa de congestión. La auditoría de carga queda sin activos porque sus abortos son terminales. Todos los abortos de carga observados pertenecen a este cierre; no hubo abortos de carga anteriores que explicaran el deterioro.

`SimZ1Freight.notifyAfterMobsim()` escribe la auditoría sin sustituir un error anterior; `notifyIterationEnds()` la vuelve a escribir y exige aprobación (`SimZ1Freight.java:170–180`). En C529 la cadena causal preservada identifica `requireApproved()` como la excepción terminal de esa fase (`matsim-run.log:5702–5703, 5760–5762`). No se detecta un error previo fatal de QSim ni un OutOfMemory en el manifiesto. El launcher posteriormente constata que MATSim no terminó `completed/valid` y conserva `failed`; esa constatación no explica por qué las colas dejaron de descargar.

## 8. Qué está demostrado, qué falta y reparación mínima propuesta

| Problema | Evidencia | Causa demostrada o hipótesis | Reparación propuesta | Prueba necesaria |
|---|---|---|---|---|
| Rechazo terminal de carga | 308 completos, 1492 abortos; 215 violaciones, limpieza y stack | **Demostrado:** rechazo de servicio incumplido; no defecto de `requireApproved()` | Conservar auditoría; corregir el mecanismo anterior que impide circular/incorporar | Reconciliar cada uno de los 1800 IDs; para una futura corrida corregida, exigir 1800 llegadas reales sin violaciones |
| Foco Elena/10a Calle a 251 s | Cabezas identificadas, GO local, WAIT de pasaje, receptores libres, dos conflictos geométricos | **Alta confianza, rama interna por confirmar:** veto circular de prioridad entre solicitudes futuras | Primero aislar el caso; si se confirma, arbitraje común, determinista y con equidad de las solicitudes que comparten nodos, antes de adquirir el pasaje; conservar señales, espacio y reservas atómicas | Fixture de los dos nodos de conflicto, seis enlaces y rutas exactas, inicialmente solo dos cabezas: capturar retorno de `passageClear`, competidor y `canCompete`; luego uno obtiene autorización tras sus paradas, libera y avanza el otro; no doble lock, invasión ni giro inválido |
| Propagación de colas a carga | Cadena explícita de líderes y receptores llenos en 14 Calle/Elena | **Demostrado localmente:** almacenamiento y bloqueo aguas abajo; alcance global no cuantificado | No aumentar capacidad ni quitar reservas como supuesto arreglo; tratar primero el foco y comprobar la propagación | Misma cadena de receptores con la causa inicial resuelta; verificar descarga y liberación de cada slot con la demanda fija |
| Gateway omitido por reruteo | `z1_60650`, candidato 720 s, rechazo 1106 s, llegada 1111 s | **Defecto observado demostrado:** validación nativa no conserva el contrato OD privado | Validar y construir candidatos por `simz1TripId`/`simz1SpatialOD`, conservando cadenas de entrada/salida y dominio permitido; aplicar también al binding de ReRoute sin una whitelist global ni afectar servicios | Reproducir exactamente candidato rechazado; impedir su instalación, aceptar una alternativa que preserve ambas cadenas y comprobar luego el auditor original, identidad y enlaces repetidos |
| Cero cálculos pese a colas | Serie de `zona1RerouteStep` y reconstrucción de observaciones | **Limitación observada:** caducidad/falta de salidas; no prueba de causa primaria ni de ruta de escape | Después del foco, considerar un disparador que incluya espera activa y el siguiente movimiento, sin rejuvenecer observaciones ficticiamente | Caso sin LinkLeave durante >300 s: debe conservar evidencia de retención; demostrar una alternativa legal y con recepción disponible; preservar presupuesto, cohorte, cooldown y reglas |
| Otros bloqueos / crédito de flujo | Eventos no exponen el contenido completo del buffer ni `flowcap_accumulate` | **No demostrado:** recuperación incorrecta de flujo o reserva retenida ilegalmente | No aplicar una reparación especulativa | Para un caso concreto: cabeza de `vehQueue` y buffer, slot, deuda de flujo, límite de recuperación, receptor compatible y motivo exacto del rechazo en el mismo paso |

El mínimo dato faltante para el foco principal no es “más logs” en general: es **el resultado desglosado de `passageClear()` para `z1_106044`/`z1_49500` a 251 s en los nodos 579746301 y 4074069083**, con cabeza competidora y factibilidad. El archivo actual permite probar la detención y reconstruir el ciclo esperado, pero no trae esos campos. Tampoco contiene una prueba contrafactual de que corregir ese foco baste para completar N=180000 ni demuestra una alternativa útil de reruteo en la detención final.

La reparación OD puede plantearse de forma independiente porque su contraejemplo está completo. La posible corrección de prioridad requiere primero la prueba focal anterior; el ajuste del reruteador no debe usarse como sustituto de esa comprobación. No se propone cambiar composición, horarios, capacidades, señales, rutas de servicios ni reglas físicas de forma arbitraria.

## Archivos del paquete y reproducibilidad

- `resumen_estructurado.json`: dictamen, certezas, límites, identidades, tiempos y fuentes.
- `cronologia_log.csv`, `cronologia_eventos.csv`, `reroute_trigger_timeline.csv`: cronología de intervalos, eventos y disparador.
- `estados_carga.csv`, `carga_por_ruta_ventana.csv`, `freight_summary.json`, `freight_events.json`, `freight_event_reconciliation.json`: censo de carga, eventos y reconciliación.
- `early_dependency.json`, `early_cases_minimal.json`, `focus_dependency_evidence.json`, `focus_state_history.json`, `focos_dependencias.csv`: foco y propagación, con ordinal y línea de cada extracto.
- `vehiculos_activos_antes_limpieza.csv`, `retained_passages_before_cleanup.json`, `final_state_summary.json`: estado final observado.
- `monitor_first_rejection.json`, `early_case_plans.json`, `freight_example_plans.json`, `rerouting_decisions_summary.json`, `last_movement_events.json`: casos y rutas.
- `event_summary.json`, `identity.json`, `source_provenance.json`, `effective_config_from_log.xml`, `effective_config_summary.json`, `code_excerpts.txt`, `code_sources.json`, `terminal_error_extracts.json`: integridad y trazabilidad.
- Scripts `*.py`: lectores, extractores, cálculos y ensamblado. `package_inventory.json` registra tamaño y firma de los entregables. Las instantáneas generales y listas de reruteos intermedias se sustituyen por extractos focales y resúmenes; no se copia el archivo de eventos completo.

Los scripts usan exclusivamente el RUN/LAUNCH escrito de forma explícita. `prepare_diagnostic.py` verifica identidad y extrae log/carga; `scan_events.py` reproduce el rechazo original (una caché del conjunto permitido evita recalcular una función pura, sin eliminar comprobaciones, y el método original sin caché confirma el rechazo); `scan_fast.py` realiza agregación independiente y validación XML incremental; `reconstruct_routing_observations.py` hace la segunda lectura de movimientos y la aritmética histórica del disparador; los extractores focales conservan eventos mínimos y las líneas de código están numeradas a partir de los archivos reales. Se interrumpieron lectores diagnósticos intermedios por rendimiento: solo las lecturas declaradas completas sustentan los totales finales. Ninguno de estos procedimientos aprueba o convierte el estado de la corrida.

**Fin del diagnóstico. No se aplicó una reparación ni se lanzó otra corrida.**
