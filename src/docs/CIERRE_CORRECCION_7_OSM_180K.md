# SimZ1 — Corrección 7, 2026-11-01

**Los dos bloqueos OSM están resueltos y las regresiones focalizadas pasan.**
Esto habilita la siguiente revisión manual, **no certifica Validate, DryRun,
capacidad ni una corrida de 180000**. No se ejecutaron Controller, QSim, MATSim,
Run1000, Validate integrado, DryRun, benchmarks ni generación masiva.
No se usaron subagentes.

Este cierre sustituye el estado operativo de los diagnósticos anteriores en
`CIERRE_DOS_RESTRICCIONES.md`, `remaining-osm-review.json`,
`osm-turn-resolution.json`, `access.json` y los cierres de Corrección 6.
Esos registros se conservan como evidencia histórica; no se borran sus hallazgos
ni se reescriben los insumos para conseguir PASS. El estado actual de producción
se comprueba con `validate_osm_turns()` y `load_model()` y queda registrado en
`scenarios/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/correction7/closure.json`.

| Relación | Estado final | Alcance |
|---|---|---|
| 17478998 v1 | `ENFORCED_BY_SHARED_SEQUENCE_DFA` | Rechaza A→V→B en validación, generación, búsqueda, reruteo y ReRoute |
| 17884471 v2 | `MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER` | Tratamiento de datos activado exclusivamente con identidad y fuentes exactas; advertencia explícita |

Para 17478998, A=`osm_1273145789_0_forward`,
V=`osm_1270930401_0_forward`, B=`osm_1273145790_0_forward`,
C=`osm_734011349_14_forward` y D=`osm_260940553_0_forward`.
**A→V→B se rechaza; C→V→B y A→V→D permanecen permitidas.**
No se retiraron A→V ni V→B del grafo de pares ni de los carriles.

Java modificado:

- `src/main/java/gt/edu/uvg/sim/zona1/SimZ1RouteSafety.java`: conserva conectividad,
  sentido, modos, dominio y carriles; añade secuencias a rutas completas y al
  empalme de reemplazos. Las rutas fijas de buses también se comprueban contra
  las secuencias aplicables a `bus`.
- `src/main/java/gt/edu/uvg/sim/zona1/SimZ1TurnRouter.java`: separa estados de llegada
  por progreso de restricciones. Conserva un estado acotado de vías intermedias
  visitadas durante la búsqueda para no borrar la prohibición mediante un
  circuito por V y para no perder alternativas legales más costosas.
- `src/main/java/gt/edu/uvg/sim/zona1/CongestionAwareRerouting.java`: transmite
  `List.copyOf(history)`, después de comprobar el prefijo nativo de eventos
  contra el índice real de la ruta. No usa la primera coincidencia del enlace.
  La falta de historial conserva `physical_history_not_ready`; sin alternativa
  se conserva el rechazo `no_allowed_path`, sin instalar una ruta ni mover el
  vehículo. Las reservas y la revisión física de reemplazo siguen intactas.
- `src/main/java/gt/edu/uvg/sim/zona1/ExperiencedTimeRouting.java`: registra un
  `RoutingModule` para `car` que usa la misma búsqueda. `TripRouter` y el
  `ReRoute` estándar consumen este módulo. Se conserva el calculador de tiempos
  experimentados, los tiempos de giro, los costos por perfil y la política de
  conducción; no se deshabilita ReRoute.
- Nueva `SimZ1SequenceContract.java`: carga y verifica el contrato compartido y
  construye el autómata de prefijos. No crea enlaces ni carriles físicos.

Python modificado:

- `python/simz1_sequence_contract.py` (nuevo): carga, hashes, tratamiento exacto
  de fuente y autómata de secuencias por modo.
- `python/simz1_balanced_od.py`: búsqueda por estados, prefijo de entrada y
  evaluación de la cadena de salida antes de elegir la llegada. Encuentra
  alternativas legales y valida la ruta completa.
- `python/simz1_osm_turn_audit.py`: comprueba la correspondencia de la secuencia
  con los miembros OSM y los segmentos dirigidos reales.
- `python/simz1_od_policy.py`: activa ambos tratamientos de producción,
  conserva el rechazo de las otras restricciones incumplidas y exige el hash
  exacto del mapa suministrado cuando está representada la secuencia revisada.
- `python/generate_montecarlo_z1.py`: verifica otra vez la ruta completa antes
  de escribir cada particular; se reutiliza el generador existente.
- `python/simz1_balanced_od_audit.py` y `python/simz1_workflow_state.py`: incluyen
  la implementación, el contrato, sus fuentes y el probe en la identidad de la
  revisión correspondiente.
- `python/test_simz1_sequence_contract.py` (nuevo) y
  `python/test_simz1_access_final.py`: regresiones de éxito.

`scripts/simz1_workflow.ps1` incorpora la nueva suite focalizada al Validate
manual antes de emitir el recibo. No se ejecutó ese flujo durante esta reparación.

El contrato compartido es **`src/main/resources/simz1/osm-sequences-v1.json`**,
esquema `simz1-osm-sequences`, versión **1**, SHA256:

```text
2dc457548aaf57a5551d09928688be8bdc2b84cdbf383fda691f3eb5a4b7d254
```

Contiene las 11 restricciones válidas representadas, IDs OSM, identidades de
relación, secuencias ordenadas, modos `car`/`bus`, clases vehiculares, excepciones
vacías, proveniencia y hashes. `car` comprende los particulares, motocicletas y
camiones compactos de este escenario. No hay una excepción de modo declarada
para 17478998. Las diez correcciones anteriores y sus **22 retiradas de destinos
terminales** permanecen intactas en la copia aislada y siguen siendo exigidas.

17884471 conserva su objeto original, versión 2, changeset 178612606,
timestamp 2026-02-16T06:36:31Z, único miembro `to=34993910` y sus dos tags
exactos. Se verifican los hashes de las cuatro respuestas oficiales y de su
proveniencia, además de los insumos aislados. El historial de la relación y la
eliminación del way 381158225 quedan vinculados por esos hashes. No se restaura
la v1, no se inventan `from`/`via`, no se prohíbe globalmente el destino y no se
declara un permiso de giro. Otros registros incompletos no reciben este
tratamiento. Las mutaciones verificadas vuelven a bloquear.

El recurso se empaqueta con Java. Sus archivos fuente se verifican desde la
raíz del repositorio; si faltan o cambian, la carga falla. Los comandos siguientes
fijan esa raíz. No hay fallback que omita el contrato.

| Prueba ejecutada | Resultado |
|---|---|
| Nueva suite Python focalizada | **16/16 PASS**, 0 fallos, 0 errores, 0 omitidas |
| Probe Java original convertido en regresión de éxito | **28 comprobaciones PASS** |
| Java `RouteSafetyCheck`, `FastestTimeRoutingCheck`, `GatewayRouteSafetyCheck` | **3 suites PASS**, sin iniciar simulación |
| Python `test_simz1_access_final.py` | **12/12 PASS** |
| Auditoría OSM y contratos de gateway/perímetro seleccionados | **20/20 PASS** |
| `git diff --check` | **PASS** |

Las comprobaciones incluyen procedencia A/C, alternativa por D, ausencia de
alternativa sin circuito por V, prefijo ausente, enlace único, enlaces repetidos,
ocurrencia real de reemplazo, continuidad de carriles y modos, el `ReRoute`
estándar sobre un plan, y cambio de elección por tiempos experimentados. También
comprueban una alternativa que llega a un estado posterior sin haber usado V,
para que una llegada más barata ya restringida no la oculte.

Se validaron completas **115 parejas OD existentes** y **99 particulares de
prueba** producidos por el generador existente con las cuatro clases y sus
horarios del catálogo conservados. No se generaron los 178200 particulares
finales; su comprobación individual corresponde al DryRun manual. El contrato
se aplica en cada generación y reemplazo, no solo a esa muestra.

Se conservan y se verifican estáticamente **4 rutas de carga** y **24 tramos de
buses**, incluidas las extensiones bus-only ya documentadas. L12 y L13 conservan
`osm_34993910_0_forward`. No se reescribieron las rutas, horarios ni servicios
para evitar la restricción.

Las huellas confirman **48 archivos Java principales ajenos a los cuatro
archivos de routing sin cambios**, junto con **108 huellas preservadas** de la
evidencia anterior. No se modificaron SimZ1CorridorOccupancy, QueueWithBuffer,
UnsignalizedPriority, semáforos, carriles, capacidades, longitudes, dimensiones,
FIFO, reservas, separación de 0.10 m ni reglas de QSim.

La configuración final continúa en N=180000: **79200 carros, 99000 motocicletas,
1800 camiones compactos**, más **269 buses**. Particulares=178200;
EE=89100, EI=35640, IE=35640, II=17820; seed=20261023; una iteración (0),
JDK17; carga `weekday-compact-v3`; horarios originales del catálogo balanceado.
Las cifras de 180K se comprobaron mediante aritmética de cuotas, no mediante
generación o simulación.

La evidencia reproducible está en
`scenarios/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/correction7/`:
`closure.json`, `focused-results.json`, `focused-tests.log`, logs Java y Python,
huellas de Java protegido, el contraejemplo original archivado y el primer
intento de tests conservado. El primer intento no se declara PASS; el resultado
final pasó después de corregir dos expectativas del nuevo test.

El recibo de Validate **no fue modificado**. Ya difería del recibo de la revisión
diagnóstica anterior al comenzar este trabajo. SHA256 de inicio y final:
`765cbd1fe8eb7d1e407a479f5332bdf5aa2a67c273da2aa594519931f5d52178`.
Su huella aprobada es
`0e90642a28041355f9af92645987f7ad4345c004b8eaec43b193f7076ee8707c`;
la huella actual es
`8560c984e4a5ae654ffaa77bf603b4d0934f78ea54dd3e027738ed814f3e797f`.
El gate exige un nuevo Validate; no se transfirió la aprobación antigua.

Comando manual de Validate, **no ejecutado**:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Validate fallo: $LASTEXITCODE" }
```

Después de Validate aprobado, DryRun exacto de 180000, **no ejecutado**:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "DryRun bloqueado: $LASTEXITCODE" }
```

`-FirstScaleTrial` registra explícitamente la ausencia de Run1000; no ejecuta
Run1000 ni omite los gates vigentes. El wrapper conserva la copia aislada y el
servicio de carga correspondientes. La programación completa y los presupuestos
por gateway/hora siguen pendientes de ese DryRun; no se certifican de antemano.
El trabajo se detiene aquí, sin iniciar ninguna etapa posterior.
