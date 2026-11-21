# Fase 6: lanzamiento manual 110000 balanced-gateway-v1

> Actualización 2026-11-01: el usuario priorizó **180000**. Véase
> [CIERRE_180K_OSM.md](CIERRE_180K_OSM.md) para estado, perímetro OSM completo,
> bloqueos reales, contratos reparados, 18 pruebas focalizadas y comandos vigentes.
> El requisito histórico Run1000 de este documento puede sustituirse únicamente
> por la opción explícita de primera corrida de escala documentada allí.
> El contenido siguiente conserva el registro anterior; no describe el estado actual.

Estado al 2026-11-01: **lanzador implementado, pendiente de validación manual;
escenario real BLOQUEADO POR INSUMOS**. El usuario informó 45 verificaciones
focalizadas aprobadas de Correcciones 1–5. No equivalen a Validate integrado de
esta nueva revisión. En esta fase el agente no ejecutó Python, Java, Maven,
pruebas, Validate, Run1000, DryRun, generaciones ni simulaciones.

## Selección y controles

`scripts/run_simz1_110k_balanced_gateway.ps1` tiene operaciones excluyentes:

- Sin opción: muestra ayuda y termina sin iniciar procesos de validación/QSim.
- `-DryRun`: controles reales, sin carpeta de corrida, archivos de población o
  MATSim. Sí conserva una carpeta de evidencia de preflight bajo runtime/launches.
- `-Run`: autorización explícita para N=110000. Repite preflight y exige Validate
  y Run1000 de la misma revisión/OD. No inicia otra corrida al terminar ni reintenta.

Se conserva exactamente 48400 carros, 60500 motos y 1100 camiones incluidos en N;
269 buses adicionales (176 Transmetro y 93 TuBus). Semilla 20261023, iteración 0,
JDK17, carga weekday-compact-v3 de 8 × 2.3 m y calendario 2026-10-23. El generador,
catálogos, servicios y todas las implementaciones de Correcciones 1–5 se reutilizan
sin editar. La distribución OD solo se aplica a 108900 particulares.

El camino nuevo fija `balanced-gateway-v1`, `lane-length-access-v1` y
`lane-length-destinations-v1`. La Corrección 5 exige semáforos fuente preservados:
`ShortLinkSignalCoordination=none`, `signal-offset-policy=preserve`. No se cambió
ningún XML ni ciclo. Las ramas históricas 180000/220000 conservan network,
uniform-nodes-v1, derive-activity-v2 y sus cantidades/comportamiento. El lanzador
10it conserva su interfaz histórica; sus funciones compartidas admiten 110000
exclusivamente mediante el contrato nuevo de una iteración.

Se conservan mutex de workspace, detección de escritores, JDK17, bytecode,
memoria/commit, reserva de pagefile y espacio en disco, hashes, integridad de
eventos, retención, validación de demanda y servicios, FIFO, reservas físicas y
0.10 m. Se mantiene el mínimo de disco de 100 GiB y el cálculo conservador previo;
no se rebaja por ser N menor. No hay whitelist global nueva.

Validate conserva todas sus comprobaciones, CrossingClearance y PassageTimer
incluidas. Integra los ocho checks de Correcciones 1–4 que no estaban en ese
script (los otros tres ya estaban), las 34 pruebas OD y 12 pruebas nuevas de
lanzamiento/observación. No existe opción de omitirlas por un PASS previo.
El usuario autorizó conservar la validación integrada; únicamente él la ejecutará.

La aprobación nueva se guarda en `validated-balanced-gateway-v1.json`, además de
`validated-source.txt`. `trial-balanced-gateway-v1.json` es independiente del trial
network. Run1000 debe aprobar calidad, flota completa, carga, rutas y despeje
nativo; se comparan perímetro, accesos, mezcla OD, catálogo, carga, política de
señales y fuentes. Una prueba network o un cambio posterior de insumos no autoriza
110000. No se escriben hashes de aprobación sin ejecutar sus controles.

## Insumos que bloquean la ejecución real

Se volvió a buscar únicamente en los archivos del proyecto. No apareció un
GeoJSON de perímetro ni catálogo real verificado. Solo está la plantilla
`docs/simz1-balanced-gateway-access.example.json`, todavía no aprobada.

Rutas previstas por defecto (NO se crearon archivos ficticios):

1. `scenarios/zona1/od/balanced-gateway-v1/perimeter.geojson`: Polygon RFC7946 real.
2. `scenarios/zona1/od/balanced-gateway-v1/access.json`: contrato
   simz1-verified-private-access-v1 con procedencia/revisión, SHA256 de perímetro,
   red, carriles y OSM; cadenas exteriores/cruces/observadores interiores;
   incorporaciones interiores y capacidad PCU/h documentada.
3. `scenarios/zona1/od/balanced-gateway-v1/mix.json`: las cuatro claves de clases
   OD y porcentajes explícitos que sumen exactamente 100. No hay mezcla por
   defecto. Se conserva la hipótesis, versión y hash de Corrección 5.

Se pueden pasar otras ubicaciones reales mediante `-ZoneBoundary`,
`-OdAccessCatalog` y `-OdMixFile`, usando las mismas en Run1000, DryRun y Run.
No use las fixtures ni cambie verified a true en la plantilla sin revisión real.
El preflight rechaza procedencia de ejemplo/prueba. El contrato geométrico de
Corrección 5 comprueba además hashes, sentidos, giros, longitud útil, conectividad
y despeje; una bandera de revisión por sí sola no acredita esos requisitos.

Son pendientes distintos: (a) perímetro no verificado; (b) catálogo no verificado;
(c) continuaciones exteriores no acreditadas —no se presume que existan o falten
antes del perímetro—; (d) conectividad entre gateways no acreditada; (e) capacidad
real documentada y compatibilidad con la demanda aún no comprobadas. La mezcla
experimental también debe decidirse explícitamente. No hay bbox de respaldo.

DryRun recorre el MISMO iterador OD para verificar cada par y presupuesto horario,
descartando cada elemento después de comprobarlo: no escribe planes ni prepara
una corrida. Puede tardar y usar memoria porque examina las 108900 solicitudes.
Un rechazo conserva N, clase y horario, e incluye el diagnóstico en 05-preflight.log.
Esto no predice incorporación o descarga QSim ni garantiza ausencia de congestión.

## Archivos de esta fase

Nuevos:
- scripts/run_simz1_110k_balanced_gateway.ps1
- scripts/check_simz1_110k_balanced_gateway.ps1
- scripts/watch_simz1_110k.ps1
- python/simz1_balanced_launch.py
- python/simz1_balanced_execute.py (solo transporte seguro del JSON por archivo
  hacia el CLI existente; no es otro generador)
- python/simz1_balanced_launch_report.py
- python/test_simz1_balanced_launch.py (12 pruebas pequeñas, no ejecutadas)
- docs/FASE_6_110K.md

Modificados:
- scripts/run_massive_z1_pasante_1it.ps1
- scripts/run_massive_z1_pasante_10it.ps1
- scripts/run_simz1_with_analysis.ps1
- scripts/simz1_workflow.ps1
- scripts/prepare_simz1_runtime.ps1 (agrega integración; ninguna prueba eliminada)
- python/simz1_experiment_preflight.py
- python/simz1_workflow_state.py

No se modificaron generate_montecarlo_z1.py, simz1_balanced_od.py, sus auditorías
de Corrección 5 ni las implementaciones Java de Correcciones 1–4. Los diff previos
de esos archivos pertenecen a fases anteriores. No se sobrescribieron históricos.

## A. Comprobaciones obligatorias (el usuario las ejecuta)

El segundo comando ejecuta SOLO Run1000, nunca 110000; hoy se bloqueará por
insumos. Validate puede ejecutarse independientemente. Detenerse ante cualquier
fallo; no copiar hashes ni reemplazar trials para autorizar la carga.

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate
if ($LASTEXITCODE -ne 0) { throw "FAIL Validate: $LASTEXITCODE" }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Run1000
if ($LASTEXITCODE -ne 0) { throw "FAIL Run1000: $LASTEXITCODE" }
Write-Host 'PASS: Validate y Run1000 de esta revision OD.' -ForegroundColor Green
```

## B. Preflight 110000, sin simular

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_110k_balanced_gateway.ps1 -DryRun
if ($LASTEXITCODE -ne 0) { throw "BLOQUEADO/FAIL preflight: $LASTEXITCODE" }
Write-Host 'PASS preflight; no se inicio MATSim.' -ForegroundColor Green
```

## C. Ejecución REAL 110000, solo con autorización explícita del usuario

NO ejecutar mientras falten los insumos o aprobaciones. Este bloque está separado
del preflight y nunca se invoca automáticamente desde B.

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_110k_balanced_gateway.ps1 -Run
if ($LASTEXITCODE -ne 0) { throw "FAIL lanzamiento; conservar logs: $LASTEXITCODE" }
Write-Host 'PASS lanzamiento 110000 y controles finales.' -ForegroundColor Green
```

## D. Monitoreo desde otra terminal

Seleccionar el LaunchId impreso por C (no el de DryRun). No se elige la carpeta
más reciente automáticamente. Ctrl+C detiene únicamente el lector.

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -List
if ($LASTEXITCODE -ne 0) { throw 'No se pudo listar la evidencia.' }
$odLaunchId = Read-Host 'LaunchId exacto de la corrida (32 caracteres hexadecimales)'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $odLaunchId -Watch
if ($LASTEXITCODE -ne 0) { throw "Lector detenido: $LASTEXITCODE; MATSim no fue modificado." }
```

El lector sigue el gzip incremental de it.0, comprueba identidad de planes y
reporta hora de eventos procesados, entradas reales/acumuladas, vehículos únicos,
llegadas, activos privados/carga/PT, esperas de incorporación, transiciones por
minuto/hora, intentos storage_wait, carga completada/restringida y salidas privadas
por gateway con prueba nativa. Muestra bytes disponibles/procesados: puede ir
atrasado respecto a QSim por compresión/buffering o lectura costosa. No sustituye
la aceptación final. Se muestran estado/fase/error y primera causa del manifiesto.

## E. Comprobar completed/valid y obtener informes

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$odLaunchId = Read-Host 'LaunchId exacto de la corrida'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $odLaunchId -Reports
if ($LASTEXITCODE -ne 0) { throw "FAIL integridad/informes: $LASTEXITCODE" }
```

Exige manifiesto completed/valid y salida natural 0; verifica inventario/hashes
con select_run y consume XML/gzip completo. Repite la auditoría OD/carga existente
y compara con el resultado de esa corrida; un archivo truncado, entrada sin
evidencia, llegada sin despeje o resultado de otra corrida no se aprueba. No
promueve failed ni modifica el manifiesto. `state.json=completed` acredita además
la cadena de análisis/screening del lanzamiento; completed/valid nativo no basta
para afirmar que el análisis final también terminó. Incompletos siguen siendo
incompletos; jamás se declara llegada al terminar el reloj.

Las gráficas y empaquetado existentes siguen conectados. El replay histórico
no acepta el contrato nuevo y no se inicia para esta variante; no se relajan sus
validaciones. Las ramas network siguen preparando su replay anterior.

## F. Logs y evidencias de fallo

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$odLaunchId = Read-Host 'LaunchId exacto del intento fallido o bloqueado'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $odLaunchId -Evidence
if ($LASTEXITCODE -ne 0) { throw "No se pudo leer la evidencia: $LASTEXITCODE" }
```

Evidencia conservada:

- `runtime/validation/balanced-launch-<UUID>/`: request, Validate.log o Run1000.log,
  y memoria cuando corresponde. Se imprime la ruta antes de ejecutar controles.
- `runtime/workflow/`: validated-source.txt, validated-balanced-gateway-v1.json,
  trial-balanced-gateway-v1.json. No se crean por esta preparación de código.
- `runtime/launches/<LaunchId>/`: request.json, state.json, commands.json,
  05-preflight.log, memoria/disco/retención, fingerprints, 06-simulation-and-analysis.log,
  informe operativo y 08-hourly-balanced.log. Un bloqueo temprano tendrá solo
  los artefactos de las fases que realmente alcanzó.
- `scenarios/zona1/montecarlo/run-bg110-<LaunchId>/`: run-manifest.json,
  matsim-run.log, inputs/balanced-od-audit.json, planes y output/ITERS/it.0,
  además del output_events.xml.gz final. Se crea solo con ejecución autorizada.
- Dentro de esa corrida, `analysis/it.0/balanced-launch/`: report.json con hashes,
  minutes.csv, hours.csv, hours-05-09.csv y freight-restrictions.csv.
- `analysis/it.0/graficas_perfiles`, `analysis/prompt13/it.0` y `entregables/`:
  productos existentes del pipeline y reporte operacional.

Los intervalos son de minuto/hora **simulada**. Entradas son vehicle enters traffic;
el LinkEnter inicial opcional no suma otra transición. Storage_wait cuenta intentos,
no segundos ni personas únicas. Activos/esperas son snapshots al cierre; se marca
la última cubeta parcial. Los buses cuentan flota única y expediciones separadas.
El reporte de restricciones de carga distingue ventanas prohibidas de intentos
de giro restringido. Una restricción puede invalidar la corrida: en ese caso se
conservan eventos/logs y observaciones provisionales, no un informe oficial válido.

## Revisión realizada y siguiente acción

Solo lectura, edición, revisión textual de interfaces/diff y parseo estático
PowerShell (ocho scripts sin errores sintácticos). No se ejecutó código Python,
ninguna prueba ni ninguno de los bloques anteriores. Los 12 tests nuevos quedan
pendientes, junto con Validate integrado y Run1000. Los 45 PASS anteriores son
los comunicados por el usuario, no resultados producidos en esta fase.
Se compararon SHA256 de 194 archivos protegidos capturados antes de editar:
Java, red/OSM/carriles, configuraciones/servicios y módulos/tests de Corrección 5;
ninguno cambió. `git diff --check` no encontró errores de whitespace. Estas
comprobaciones estáticas no son un PASS funcional del nuevo lanzador.

Siguiente acción: obtener/revisar insumos reales; el usuario ejecuta A, luego B,
y decide separadamente si invoca C. Sin insumos, B/C rechazan con ruta/condición
faltante. No se ha preparado ni autorizado una corrida de 220000.
