# SimZ1: corrida masiva reproducible con alcance explícito

**Estado global: BLOCKED para una corrida con todas las funcionalidades solicitadas.**
El lanzador permite preparar y ejecutar un experimento del subconjunto disponible:
red histórica, demanda vial de carros/motos, admisión estricta, semáforos y carriles
QSim configurados. No representa una validación completa de circulación urbana,
transporte público ni accidentes físicos. Ninguna corrida MATSim, servidor o
navegador se ejecutó al preparar esta entrega.

**BLOCKED por espacio en el equipo actual:** la lectura de la unidad real C:
durante esta revisión mostró 2,328,416,256 bytes libres (aproximadamente 2.17 GiB).
Es una medición puntual, no capacidad garantizada al ejecutar. No alcanza la
reserva predeterminada de 64 GiB ni los presupuestos SQLite de ejemplo. El flujo
debe detenerse antes de compilar/generar población; `-PrepareOnly` tampoco omite
esa condición. No se borró ni movió ninguna corrida para liberar espacio. El
launcher completo preparado no se declara validado extremo a extremo en este
equipo bloqueado.

La existencia de una clase, un prompt o un fixture no acredita su instalación en
QSim. La tabla distingue código conectado al launcher, representación del replay
y componentes aislados que rechazan activación productiva.

## Funcionalidades verificadas en código

| # | Funcionalidad | Estado en este experimento | Alcance comprobable y límite |
|---|---|---|---|
| 1 | `strict-receiver-v1` | **ACTIVA** | `RunZona1Simulation` carga el módulo tipado; la fábrica instala la política. `Zona1QNodeImpl` conserva WAIT ante receptor lleno y no usa FORCE por diez segundos. El contrato compara política y cuatro hilos solicitados/efectivos. No cubre por sí mismo espacio métrico del vehículo candidato, inserciones de salida ni todas las transferencias internas. |
| 2 | Giros y semáforos | **ACTIVA, alcance parcial** | QSim ejecuta semáforos y destinos permitidos por los carriles existentes. Cumplimiento completo de restricciones OSM: **BLOCKED**. La auditoría de archivos actuales encuentra 19 restricciones: 10 mapeables y una via-way siguen permitidas; seis están fuera de red y dos tienen miembros incompletos. No se aplica silenciosamente una red nueva. |
| 3 | Detención antes de intersecciones | **ACTIVA visualmente** | WAIT procede de eventos nativos; `simz1_visual_queues.js` coloca la carrocería completa detrás del límite de parada inferido. Las coordenadas no constituyen posición física longitudinal observada ni límite levantado en campo. |
| 4 | Separación de vehículos | **ACTIVA con límites** | Admisión/capacidad PCU nativa; envolventes y colas visuales métricas verificables en fixtures válidos. Seguimiento físico continuo y garantía universal de ausencia de contacto: **BLOCKED**. Enlaces demasiado cortos conservan diagnóstico; no se ocultan cuerpos para superar un chequeo. |
| 5 | Carril rápido/lento | **BLOCKED** | `SimZ1LanePolicy` implementa decisiones aisladas; no hay adaptador nativo que las ejecute. `simz1LanePolicy.enabled=true` se rechaza. |
| 6 | Cambio de carril con ventaja | **BLOCKED** | Se verifican permisos, ventaja, receptor, envolvente y espacio en solicitudes aisladas. Falta estado continuo, reserva/transferencia nativa atómica y eventos de maniobra confirmada. No se activa desplazamiento WebGL como sustituto. |
| 7 | Perfiles físicos de motos, carros, pesados y buses | **ACTIVA carros/motos; resto BLOCKED** | Dimensiones supuestas, PCU y techos de velocidad se escriben en `VehicleType` y atributos versionados. No hay aceleración física integrada. Pesados son rechazados por falta de aplicación de restricciones de acceso; los buses dependen de la flota no activada en este launcher. |
| 8 | Flota pública fija y separada de N | **BLOCKED** | El modelo de flota separada existe y `SimZ1.main` puede instalarlo; el launcher actual invoca `RunZona1Simulation`, que no lo instala. Tampoco hay autorización completa de rutas, paradas y dominio productivo. B=0 en este experimento, no una cuota de buses dentro de N. |
| 9 | Incidentes estocásticos con eventos propios | **DESACTIVADA** | Se impone `--no-incidents`. El incidente histórico reduce capacidad/velocidad del enlace, pero no inmoviliza los vehículos ni cierra realmente un carril; no cumple el contrato solicitado. |
| 10 | Bloqueo de carril durante 1800 s simulados | **BLOCKED** | `SimZ1IncidentLaneCoordinator` es un coordinador de fixture. `SimZ1IncidentConfigGroup.validateProduction()` rechaza activación: faltan observador pareado, adaptador de cierre por carril y registro nativo verificado. |
| 11 | Llegada durante 5000 ms reales | **ACTIVA visualmente** | `SimZ1ArrivalEffects` usa `performance.now()`, solo llegada confirmada y posición final comprobable; integración real en controles y animación. Marcador no seleccionable, independiente de velocidad/pausa y de conteos activos; no añade segundos MATSim. Verificado con reloj falso; revisión GPU/navegador de esta nueva corrida pendiente. |
| 12 | SQLite directo para WebGL | **ACTIVA, exportación posterior explícita** | `visualizador_z1.py --sqlite-direct` publica SQLite y metadatos sin 96 HTML. `simz1_continuous_replay.py` prepara una vista que reutiliza la base; el servidor consulta en lectura. El launcher de replay admite ahora el manifiesto `sqlite-direct-v1`. |
| 13 | Rutas, paradas y accesos realmente verificados | **BLOCKED para afirmación completa** | Hay validadores y evidencia parcial; no equivalen a aprobación del dominio, de todas las restricciones, de rutas municipales ni de paradas operativas. La versión de conectividad existente declara `review_only_blocked`, `runnable=false`. |

Fuentes principales: [`RunZona1Simulation.java`](../src/main/java/gt/edu/uvg/sim/zona1/RunZona1Simulation.java),
[`RoadVehicleProfiles.java`](../src/main/java/gt/edu/uvg/sim/zona1/RoadVehicleProfiles.java),
[`SimZ1LanePolicyConfigGroup.java`](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1LanePolicyConfigGroup.java),
[`SimZ1IncidentConfigGroup.java`](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1IncidentConfigGroup.java),
[`simz1_arrival_effects.js`](../python/simz1_arrival_effects.js),
[`simz1_sqlite_export.py`](../python/simz1_sqlite_export.py) y
[`scenario-revision.json`](../scenarios/zona1/versions/connectivity-review-v1/scenario-revision.json).

## Parámetros del subconjunto ejecutable

N cuenta personas de demanda vial; no viajes, pasajeros de buses ni tamaño de
flota. Se sortea una sola N en el rango inclusivo mediante la semilla registrada;
`MinAgents=MaxAgents` fija N para las pruebas pequeñas. Una sola iteración MATSim
corresponde a la iteración 0, con un viaje por persona y horizonte 0..86400 s.
Con el código actual y semilla 20261022, el rango 150000..250000 selecciona
239096 personas; el rango 150000..2500000 selecciona 1628959. Son cálculos del
sorteo reproducible, no poblaciones generadas ni simulaciones ejecutadas.

Se usa `--od-mode network`: experimento sobre la red histórica existente. El modo
`gateway-od` futuro queda fuera del lanzador hasta aprobar límites e importar las
restricciones pendientes. No se ejecuta `prepare_simz1.py` ni se reemplazan red,
carriles, señales o corridas anteriores.

La copia versionada del catálogo mantiene las siete definiciones requeridas por
Java, pero fija el peso de TransportePesado a cero. Pesos sintéticos de demanda:
Normal 40, Motociclista 25, Liebre 10, Tortuga 10, Pesado 0; denominador 85.
La cuota de motos se divide 1:2:1 entre lenta/normal/rápida. No son frecuencias
observadas. Los horarios del catálogo cubren 0..86400; no se combina
`--agent-catalog` con `--temporal-profile` o `--hourly-weights`.

| Perfil activo | PCU | Largo × ancho (m) | Techo configurado (km/h) |
|---|---:|---:|---:|
| Carro Tortuga / Normal / Liebre | 1 | 4.5 × 1.8 | 25 / 50 / 90 |
| Moto lenta / normal / rápida | 0.25 | 2.1 × 0.8 | 30 / 50 / 70 |

Estos techos no son velocidades garantizadas: prevalecen red, cola y semáforo.
Dimensiones declaradas `assumed=true`; `acceleration.model=not_integrated_by_QSim`.
Las rampas de movimiento del replay son reconstrucción visual.

Parámetros fijos: `--mode montecarlo`, `--massive`, `--iterations 1`,
`--trips-per-person 1`, `--drain-seconds 0`, `--qsim-threads 4`,
`--storage-policy strict-receiver-v1`, `--use-lanes`, `--signals`,
`--unsignalized-priority`, `--signal-offset-policy preserve`, `--no-incidents`,
`--od-mode network`, `--within-day-routing`, `--routing-share 0.5` y
`--reroute-budget 64`, `--corridor-policy redistribute`,
`--priority-stop-seconds 5`, `--priority-max-yield-seconds 30`,
`--priority-classification osm-hierarchy`, `--priority-conflicts geometric`.
`--seed` y `--matsim-seed` reciben el mismo `-Seed` explícito.
Cuatro hilos se permiten solo después de aprobar el fixture de concurrencia
nativo; el fallo detiene el flujo, sin degradar silenciosamente a otro modo.

## Lanzador y pruebas manuales

Archivo: [`scripts/run_simz1_massive_verified.ps1`](../scripts/run_simz1_massive_verified.ps1).
Ejecutar desde la raíz del proyecto. `-PrepareOnly` prepara y verifica el plan
sin generar la población ni ejecutar MATSim; sí compila y ejecuta regresiones
aisladas. Las invocaciones sin ese modificador sí ejecutan MATSim
cuando el usuario las lance; no se ejecutaron en esta entrega.

Parámetros PowerShell predeterminados: `-MinAgents 150000 -MaxAgents 250000
-Seed 20261022 -MinimumFreeGiB 64`. Este último es un mínimo inicial de espacio,
no una estimación de la corrida. JDK 25, Maven del wrapper, `.venv`, Node,
procesos con rutas de destino y unidades reales se comprueban antes del lanzamiento.
La compilación usa un directorio nuevo y no reutiliza `target/classes`.

Para volver a consultar espacio, sin borrar nada, puede usarse este inventario;
el script comprueba además el volumen real que contiene cada ruta de salida,
temporales y dependencias (incluidos puntos de montaje):

```powershell
[IO.DriveInfo]::GetDrives() | Where-Object IsReady |
    Select-Object Name, DriveFormat, AvailableFreeSpace, TotalSize
```

No reducir `-MinimumFreeGiB` únicamente para eludir el bloqueo. Dimensionar la
corrida y disponer de capacidad suficiente en las rutas realmente utilizadas.

Cada invocación crea `scenarios/zona1/montecarlo/verified-<GUID>/`, con
`build/`, `verification/` y `verified-launch.json`. La corrida usa un hijo
`run-<GUID>/`, creado solo al ejecutar. El recibo distingue
`prepared_verified_plan`, `running`, `validating`, `completed_validated_subset`
y `failed`; `full_requested_feature_set` permanece `BLOCKED`. La verificación
final queda en `verification/result.json`; preflight, argumentos, semillas,
catálogo, fuentes y hashes quedan junto a los registros de regresión.
Repetir sin `-PrepareOnly` crea otro GUID y repite verificaciones; no reanuda ni
modifica el directorio de preparación anterior.

```powershell
# Primero preparar el experimento y revisar su alcance BLOCKED parcial.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 10 -MaxAgents 10 -Seed 20261022 -PrepareOnly
if ($LASTEXITCODE -ne 0) { throw 'Falló la preparación; no continuar.' }

# Ejecutar manualmente cada tamaño por separado; inspeccionar su resultado
# antes de pasar al siguiente. Cada invocación usa una carpeta GUID nueva.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 10 -MaxAgents 10 -Seed 20261022
if ($LASTEXITCODE -ne 0) { throw 'Falló la corrida de 10.' }

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 100 -MaxAgents 100 -Seed 20261022
if ($LASTEXITCODE -ne 0) { throw 'Falló la corrida de 100.' }

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 1000 -MaxAgents 1000 -Seed 20261022
if ($LASTEXITCODE -ne 0) { throw 'Falló la corrida de 1000.' }
```

No saltar a escala masiva porque el proceso Java termine con código cero.
Revisar `run-manifest.json`: estado `completed`, validación `valid`, iteración 0
completa, identidad de carpeta, hashes de artefactos y reconciliación de personas,
viajes, llegadas, abortos y censurados. La configuración efectiva debe conservar
strict, cuatro hilos, `removeStuckVehicles=false`, semáforos/carriles activos,
incidentes desactivados y módulos físicos no disponibles desactivados.

El caso controlado de incidente nativo queda **BLOCKED**, no se entrega un comando
que afirme simularlo. El contrato pendiente exige, con semilla y oportunidad
fijas, dos participantes comprobados, carril concreto cerrado, vehículos
inmóviles y receptor cerrado exactamente en `[t, t+1800)`, liberación en
`t+1800`, eventos propios y representación naranja/símbolo de emergencia
derivada de esos eventos. Repetir con un carril vecino libre, cuatro hilos,
pausa/seek del replay y mera superposición visual que no active accidente.
Un fixture del coordinador aislado solo valida su lógica; no valida QSim.

Hay un caso sintético controlado ya separado de las corridas en
`scenarios/zona1/versions/incident-design-2026-10-22/fixture.json`: semilla
20261022, probabilidad 0.00001 por oportunidad elegible y participantes de prueba.
Su contrato declara `physics_effect=none`. Para revisar manualmente solo ese
prototipo, sin MATSim ni bloqueo físico, está disponible esta orden; **no se
ejecutó como corrida de incidente**:

```powershell
& .\.venv\Scripts\python.exe -B .\python\simz1_incident_design.py --fixture .\scenarios\zona1\versions\incident-design-2026-10-22\fixture.json
```

Una oportunidad seleccionada no basta para activar accidentes productivos.
El caso nativo solicitado de inmovilización y cierre durante 1800 s permanece
BLOCKED hasta implementar y conectar los componentes anteriores.

## Comandos masivos para ejecutar posteriormente

El comando solicita el subconjunto descrito, no una corrida con todas las
funcionalidades. Sigue pendiente comprobar tiempo, RAM y disco sobre resultados
manuales 10/100/1000 y resolver cualquier bloqueo del preflight.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 150000 -MaxAgents 250000 -Seed 20261022
if ($LASTEXITCODE -ne 0) { throw 'Corrida masiva no validada; revisar evidencias.' }
```

Alternativa solicitada, con máximo de **2,500,000**, diez veces el máximo anterior:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_massive_verified.ps1 -MinAgents 150000 -MaxAgents 2500000 -Seed 20261022
if ($LASTEXITCODE -ne 0) { throw 'Corrida de escala ampliada no validada.' }
```

No hay una prueba de capacidad que acredite esa escala. Eventos, planes, análisis,
SQLite, scratch, tiempos de ruteo y memoria pueden crecer mucho más que una regla
lineal simple. Cuatro hilos QSim no limitan todo el paralelismo JVM ni garantizan
velocidad. La detección de espacio libre es una condición inicial; no constituye
una predicción del tamaño final. No se dimensiona el disco con letra C: supuesta.

## SQLite directo después de una corrida válida

Asignar `$simz1Run` a la carpeta **run** concreta que haya completado la
validación, no a otra corrida histórica ni a un puntero ambiguo. No usar estos
comandos sobre una corrida fallida, en escritura o con manifiesto incompleto.

La extracción inicial necesita leer los eventos una vez. Presupuestos de ejemplo:
32 GiB de base, 32 GiB de scratch y reserva de 2 GiB. Son límites operativos,
no una garantía de que alcancen para N. El exportador verifica las unidades reales
y suma los presupuestos si comparten volumen. Ajustarlos antes de exportar según
las mediciones de las corridas pequeñas y la capacidad disponible.
Con los aproximadamente 2.17 GiB libres observados, esta exportación queda
**BLOCKED**; no ejecutarla todavía ni sustituir los presupuestos por cifras mínimas
para hacer pasar el chequeo.

```powershell
$simz1Run = (Resolve-Path -LiteralPath '<carpeta-run-validada>').Path
$simz1Python = Join-Path $PWD.Path '.venv\Scripts\python.exe'
$simz1SourceRoot = Join-Path $simz1Run 'webgl-source'
$simz1Source = Join-Path $simz1SourceRoot 'sqlite-source'
$simz1Continuous = Join-Path $simz1Run 'webgl-continuo'
$simz1Scratch = Join-Path $simz1Run 'sqlite-scratch'

# Una extracción; omite los 96 HTML y no genera el index.html de salida indicado.
& $simz1Python -B .\python\visualizador_z1.py --run-dir $simz1Run --iteration 0 --sqlite-direct --output (Join-Path $simz1SourceRoot 'index.html') --temp-dir $simz1Scratch --sqlite-budget-gib 32 --scratch-budget-gib 32 --window-seconds 900 --replay-start 0 --replay-end 86400
if ($LASTEXITCODE -ne 0) { throw 'Exportación SQLite incompleta; conservar evidencia.' }

# Usa el contrato publicado, no los eventos ni HTML paginados.
& $simz1Python -B .\python\simz1_continuous_replay.py --source $simz1Source --output $simz1Continuous --sqlite-direct --run-dir $simz1Run --iteration 0 --temp-dir $simz1Scratch --window-seconds 120 --start 0 --end 86400
if ($LASTEXITCODE -ne 0) { throw 'Vista continua incompleta.' }

& $simz1Python -B .\python\verify_simz1_continuous_data.py --directory $simz1Continuous --offline --times 0 120 28080 43200 86340 86400
if ($LASTEXITCODE -ne 0) { throw 'La vista no conserva la evidencia nativa.' }

# Inspección sin servidor ni navegador; exige identidad y jornada correctas.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\replay\start_replay.ps1 -RunDir $simz1Run -Iteration 0 -ReplayDir $simz1Continuous -CheckOnly
if ($LASTEXITCODE -ne 0) { throw 'Replay incompatible.' }
```

Si la fuente publicada ya existe y coincide en identidad/opciones, la primera
orden la reutiliza sin volver a extraer. Un `spool-ready.json.gz` finalizado permite
reanudar solo publicación; un SQLite sin checkpoint finalizado se conserva y se
rechaza, sin reextracción silenciosa. Una vista continua ya completa no se vuelve
a construir: pasar directamente a verificación/apertura. `--resume-incomplete`
se limita a una preparación continua incompleta de la misma identidad.

Para abrir el replay SQLite existente, el usuario puede ejecutar:

```powershell
# Inicia/reutiliza únicamente un servidor compatible, sin abrir navegador.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\replay\start_replay.ps1 -RunDir $simz1Run -Iteration 0 -ReplayDir $simz1Continuous -Port 8793 -NoBrowser
```

Abrir manualmente `http://127.0.0.1:8793/index.html`. El comando equivalente del
servidor es `& $simz1Python -B .\python\serve_simz1_continuous.py --directory
$simz1Continuous --port 8793`; no agregar `--open` si no se desea apertura
automática. Estas órdenes no reexportan datos. Ctrl+C cierra el servidor propio;
si se reutilizó otro servidor, debe cerrarse desde su consola original.

## Validación antes de interpretar resultados físicos

1. Contrastar config efectiva, hashes, semillas, versión de catálogo y N elegida
   con el recibo del lanzador; comprobar que no se usó bytecode antiguo.
2. Separar capacidad/admisión nativa, pertenencia de carril observada por eventos
   y coordenadas/envolventes reconstruidas. PCU no es largo ni ancho físico.
3. Revisar WAIT de rojo y receptor lleno, ausencia de FORCE por almacenamiento
   bajo strict, transferencias, esperas, abortos, censurados, congestión y deadlock.
   Rechazar conclusiones de capacidad derivadas de una cola físicamente inviable
   en un enlace corto sin resolver y documentar ese conflicto.
4. Verificar rutas permitidas por la red efectiva y dejar explícitos giros OSM
   todavía no aplicados. No atribuir los resultados a restricciones municipales
   completas, paradas aprobadas ni transporte público inexistente en la corrida.
5. Revisar en replay rojo, cola 2/5/10, vehículos largos, posiciones desconocidas,
   aviso de llegada a 1x/120x, pausa, buffering, cambio de ventana y seek grande.
   Una llegada sin posición final comprobable no recibe coordenadas inventadas.
6. No interpretar contacto visual como accidente, ni un fixture de cambios de
   carril como adelantamiento físico de QSim. La corrida mantiene incidentes y
   módulos físicos no instalados desactivados.

## Regresiones aisladas de replay realizadas en esta entrega

Se inspeccionaron productor, publicador SQLite, API y controles actuales.
Se corrigió el selector de replay que intentaba leer un manifiesto paginado en
una fuente SQLite directa. También se corrigieron los validadores de recorrido
que rechazaban límites nativos `vehicle enters/leaves traffic` emitidos por el
propio exportador; se preserva el borrado de pertenencia sin inventar carril.
El fixture diario anterior omitía `type`: ahora usa tipos nativos y mantiene una
prueba negativa para tipos inventados. No se debilitó el rechazo de identidades,
campos o eventos inválidos.
Se actualizaron dos fixtures de controles a sus contratos actuales: Escape
libera el viaje completo y reseleccionar requiere responder una consulta nueva;
una cola necesita contexto de espera completo, no solo los vehículos de la ventana.

Resultados sin simulación/servidor/navegador: 18 pruebas de launcher replay,
8 de ciclo de exportación, 27 de fuente SQLite, 7 de dimensiones físicas y una
de cronología de carril aprobadas. Cuatro suites JavaScript de llegada, dimensiones,
recorrido seleccionado y replay continuo aprobadas. Las bases de prueba son pequeñas y temporales;
no se leyeron ni regeneraron corridas históricas. No equivalen a validar una
corrida nueva grande ni al comportamiento GPU.

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_replay_launch.py
& .\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_sqlite_source.py
& node .\python\test_simz1_arrival_effects.cjs
& node .\python\test_simz1_selected_route.cjs
& node .\python\test_simz1_continuous_replay.cjs
```

## Comprobaciones del lanzador realizadas

Pasaron 14 pruebas Python del contrato masivo, seis de perfiles viales, cuatro de
configuración de incidentes y 27 comprobaciones PowerShell de guardas/estructura.
Las suites JavaScript de semáforos y separación también pasaron. Sumadas a las
anteriores, son **85 pruebas Python y seis suites JavaScript**, sin simulación,
servidor ni navegador.

Se compiló desde cero con Maven y, por separado, con javac JDK 25: **101 clases
productivas resultaron idénticas byte a byte**. Sobre la compilación independiente
pasaron los diez ejecutables Java de admisión, configuración, prioridad,
observación y concurrencia (incluidos cuatro propietarios y 400 transferencias).
Los dos compiladores usan explícitamente `-g:none`; `debug=false` de Maven por sí
solo no produce esa equivalencia. Evidencia local:
`target/simz1-massive-build-check-6abc58d9f9864a3b9a079d0c0b267822/equivalence-receipt.json`.
Estos fixtures no ejecutan el scheduler QSim ni acreditan una corrida real de
cuatro hilos. La compilación aislada reutilizó JAR locales sin duplicarlos para
mantener pequeño el consumo de disco de esta comprobación.

La invocación real `-PrepareOnly` verificó JDK 25, Maven 3.9.6, `.venv` y Node y
rechazó correctamente el espacio insuficiente **antes** de compilar/generar
población. Su log es `target/simz1-massive-prepare-only.log`. No se presenta como
aprobación del flujo completo; el bloqueo de disco debe resolverse antes de
ejecutar las órdenes manuales. El inventario y hashes de fuentes se vuelven a
comprobar antes y después de la ejecución, también ante fuentes nuevas.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validation\test_simz1_massive_launcher.ps1
& .\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_massive_contract.py
git diff --check
```
