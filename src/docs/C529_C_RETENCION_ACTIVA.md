# C529-C — retención activa sin muestras de salida frescas

La reparación conserva una evidencia separada de retención física y permite
evaluar la siguiente maniobra de la cabeza afectada aunque hayan caducado las
muestras de viajes completados. No demuestra la causa única ni la solución del
atasco histórico. C529-A y el contrato OD de C529-B se conservan.

## Antes y después

Se reutilizan, sin modificarlos, el diagnóstico C529 sección 6,
`routing_observation_summary.json`, `reroute_trigger_timeline.csv`,
`rerouting_decisions_summary.json`, `code_excerpts.txt` y `code_sources.json`.
En el resumen histórico, la muestra de `osm_1057486080_2_forward` dura 209 s,
se completa a 31658 s y tiene nominal 2.9532778234516086 s. Su edad es 262 s
a 31920 y 322 s a 31980. En esas evaluaciones, los enlaces severos pasan de
6 a 0 y los cálculos de 17 a 0; el presupuesto sigue siendo 100.

La rama defectuosa es `if (severe.isEmpty()) return` en
`CongestionAwareRerouting.notifyMobsimBeforeSimStep()`, combinada con la selección
exclusiva de `full.subList(index+1, ...)`. La caducidad es correcta para una muestra
completada; faltaba otra fuente para detectar una cabeza todavía retenida.

La prueba compila aisladamente el detector histórico exacto de
`91d3ffce66bee80da3f0450e9d98a5a0316b3ec7`, comprobando su SHA contra
`code_sources.json`. No revierte producción ni ejercita la instalación antigua
de rutas. Los controles de las colas en ambas compilaciones conservan C529-A.

Una fixture de cinco enlaces utiliza `QLinkLanesImpl`, `QueueWithBuffer`,
`PersonDriverAgentImpl`, `Zona1QNodeImpl` y `StopAndYield` reales. Conserva la
aritmética temporal de la muestra anterior en un enlace sintético de nominal
2.953278 s. No es una reconstrucción geométrica de Elena. Una cabeza ofrecida
espera ante un receptor lleno; se consulta el nodo de 31659 a 31980. Los primeros
5 s son parada obligatoria; siguen 317 rechazos físicos consecutivos, separados
por un segundo: 316 s de espera comprobada, sin salidas.

Antes, la muestra caduca y el detector deja de encontrar severidad. Después,
la misma muestra caduca sin cambiar su timestamp, pero la cabeza queda incluida
por retención activa. Una alternativa desde su carril resulta legal y tiene
estimaciones restantes de 103.553278 s para la ruta anterior y 4.953278 s para la
candidata. Ambas conservan la misma estimación del primer enlace parcial cuya
entrada completa no se conoce; la espera no se descuenta artificialmente.
La consulta no instala la ruta ni mueve vehículos. La salida posterior se prueba
mediante admisión normal y pasos controlados de las colas, conservando la ruta
original; no se fuerza movimiento, aborto, timeout ni llegada.
El prefijo usado para construir el candidato coincide con los eventos registrados.
La salida del enlace parcial no fabrica una muestra completa; el recorrido del
enlace siguiente sí genera una muestra cuando se completan su entrada y salida
nativas. La comparación adicional con entrada conocida conserva los 100 s del
movimiento posterior, sin descontar de él tiempo ya transcurrido.

## Fuentes y significado del tiempo

| Dato | Fuente | Uso |
|---|---|---|
| Recorrido completado | Par `LinkEnter`/`LinkLeave`; duración y hora de salida | Estimación histórica fresca hasta 300 s inclusive; sin cambios |
| Vehículo incorporado | `VehicleEntersTraffic`; identidad de servicio existente | Habilita evidencia activa; esperar incorporación no basta |
| Espera comprobada | Rechazos nativos consecutivos del mismo vehículo/enlace/carril/siguiente movimiento | Disparador; nunca muestra completada ni pronóstico de demora futura |
| Tiempo transcurrido | Entrada real del enlace actual, si se conoce | Se descuenta una sola vez de la estimación de ese movimiento |
| Recorrido restante | Muestras frescas de movimiento/enlace o modelo de tiempo libre y perfil ya existente | Misma comparación estricta de mejora entre ambas rutas |

`SimZ1ActiveRetention` escucha los eventos existentes. Reconoce tanto
`receiver_native_storage` emitido por la consulta física de prioridad de C529-A
como el par `turn_go`/`storage_wait` del nodo. Un GO local seguido de rechazo de
almacenamiento no reinicia artificialmente la espera. Los rechazos exclusivamente
de prioridad, parada o señal no la acumulan.

Cada 60 s se revalidan únicamente los registros pendientes: incorporación,
cabeza ofrecida, enlace, carril, salida mínima, siguiente movimiento, permiso
nativo de señal y `receiverFeasibility()`. Esta última conserva su consulta
física sin adquirir reservas ni llamar recursivamente a prioridad. Solo motivos
físicos explícitos sostienen la evidencia. Se aplica el umbral existente de demora
de 60 s y relación 3× respecto al nominal; la duración confirmada es un límite
inferior de espera, no un nuevo tiempo de viaje.

La evidencia se borra al entrar/salir de enlace, salir del tráfico, abortar,
recibir admisión o cambiar la condición. También caduca si faltan confirmaciones
durante más de dos pasos de simulación. Esa caducidad afecta solamente evidencia,
jamás reservas. No se reconstruye el historial ni se enruta por segundo; los
eventos actualizan un registro acotado por vehículo y las consultas físicas se
hacen en la barrera previa al paso.

El modelo de tiempo restante de `SimZ1TurnRouter` permanece intacto:
`max(0, estimación del movimiento actual − tiempo desde entrada)` y costos de
los movimientos posteriores. La edad de la espera no se suma a esos costos.
Cuando falta la entrada completa del primer enlace parcial, se conserva la
estimación completa y conservadora anterior. No se recupera tiempo ya gastado.

## Cambios e integración

- `SimZ1ActiveRetention.java`: estado acotado, limpieza y revalidación física.
- `CongestionAwareRerouting.java`: despacho único de eventos mediante
  `BasicEventHandler`, disparador activo además del existente, filtro adicional
  del receptor y señal de la siguiente maniobra, y campos focales de evidencia.
  Los filtros de cohorte, elegibilidad, cooldown y orden cíclico se extraen para
  probarlos sin QSim, conservando su comportamiento.
- `SimZ1RetentionBeforeCheck`, `SimZ1RetentionCheck`, `SimZ1RetentionFixture` y
  `python/test_simz1_active_retention.py`: reproducción y regresión focal.
- `test_simz1_native_od.py` y la compilación focal de
  `test_simz1_sequence_contract.py`: incluyen la nueva dependencia Java.
- `scripts/simz1_workflow.ps1`: ejecuta C529-C después de C529-B en Validate.
  El fingerprint existente incluye todos los nuevos Java y Python; las pruebas
  verifican esa cobertura por mutación en un directorio sintético.
- Se actualiza únicamente la expectativa del reruteador protegido afectada por
  C529-C, con justificación y cobertura; se mantiene su SHA histórico y las
  protecciones de A/B. No se renueva ninguna aprobación.

La construcción de candidatos de C529-B, `SimZ1TripOd`, `SimZ1RouteSafety`,
`SimZ1TurnRouter`, `ExperiencedTimeRouting`, el prefijo por ocurrencia y la
secuencia OSM 17478998 siguen vigentes. La comprobación existente de reservas
precede a la instalación. El disparador nuevo no cambia carriles, salta colas,
autoriza cruces ni modifica prioridades. Se conserva presupuesto 100 por
evaluación, cohorte fija 50%, cooldown 300 s y frecuencia 60 s; carga y transporte
público continúan excluidos.

No se emiten nuevos eventos por cada WAIT: se consumen los existentes. Se añade
el contador de retenciones al resumen por evaluación y, en decisiones de reruteo
ya existentes, su fuente, inicio, última confirmación, duración y motivo físico,
marcando expresamente `activeRetentionUsedAsTravelTime=false`.

## Pruebas ejecutadas

| Comprobación | Resultado |
|---|---|
| C529-C: compilación JDK17 antes/después y ambos checks | 4 comandos, salida 0; 65 aserciones después |
| Caducidad, receptor lleno >300 s, salida y limpieza, entrada parcial/completa | PASS en colas nativas |
| Señal/parada, incorporación, carga/transporte, cambio de movimiento y falta de confirmaciones | PASS |
| Alternativa legal, carril incompatible, ausencia de mejora, consultas sin consumo de ruta, tiempos restantes | PASS |
| Presupuesto 100, cohorte 50%, cooldown 300 s, frecuencia 60 s y turno cíclico | PASS |
| C529-B y regresiones afectadas de rutas, señales y reservas | 12 comandos, salida 0; 362 aserciones OD |
| Auditor Python original frente a Java | 26 rutas en paridad; contraejemplo histórico sigue rechazado |
| Protecciones y fingerprint | 112 fuentes comprobadas; 7 pruebas de mutación; 9 archivos C529-C cubiertos |
| Método focal existente `test_16_java_probe_and_standard_reroute_no_simulation` | Salida 0, sin setup global; resultados en directorio nuevo |
| Parser PowerShell del workflow y `git diff --check` | Salida 0 |

Evidencia final C529-C:
[`runtime/c529-c-94pkmeu7/focused-results.json`](../runtime/c529-c-94pkmeu7/focused-results.json),
[`after.log`](../runtime/c529-c-94pkmeu7/after.log),
[`historical-evidence.json`](../runtime/c529-c-94pkmeu7/historical-evidence.json),
[`integration.json`](../runtime/c529-c-94pkmeu7/integration.json) y
[`additional-checks.json`](../runtime/c529-c-94pkmeu7/additional-checks.json).
Regresiones B sobre las mismas fuentes Java de producción:
[`runtime/c529-b-jfhvbf_q/focused-results.json`](../runtime/c529-b-jfhvbf_q/focused-results.json).
Los hashes capturados antes/después confirman que la evidencia C529, entradas
históricas verificadas, auditor original, recibos y fuentes preservadas de A/B
permanecieron intactos. Las correcciones de la fixture posteriores a esa ejecución
B solo cambiaron pruebas de C, no producción.

## Comando focal y límites

Desde la raíz, con JDK17 y el classpath local ya preparado:

```powershell
.\.venv\Scripts\python.exe -B .\python\test_simz1_active_retention.py --with-routing-regressions
```

La opción ejecuta también C529-B y sus regresiones de reservas, señales, OD,
tiempos y secuencia OSM, además de paridad con el auditor Python original. Validate
invoca C529-C sin esa opción porque ya ejecuta C529-B inmediatamente antes.

No se ejecutan Controller, QSim.run, Validate completo, generación de población,
DryRun, Run1000 ni simulación masiva. Las trazas son pruebas sintéticas de
componentes; no son resultados de una corrida ni certificados de llegada.

La corrección no garantiza detección de toda retención: es conservadora ante
confirmaciones ausentes, esperas de prioridad, cambios de señal o vehículos que
no son cabeza. Tampoco garantiza alternativa, mejora, instalación, salida del
atasco, equidad a escala ni rendimiento de la red completa. No añade un pronóstico
de espera futura. Una alternativa temporalmente inutilizable puede rechazarse
sin buscar una segunda opción física. Las dos cabezas iniciales del diagnóstico
siguen fuera de la cohorte; no se afirma que esta reparación las rerutearía.
No se acredita la corrida de 180000 ni la llegada histórica de z1_60650.
