# Cierre manual 180000 — 2026-11-01

> Actualización posterior: [cierre del catálogo y copia aislada](CIERRE_ACCESS_180K.md).
> Hay 10 entradas, 12 salidas y 22 orígenes interiores revisados como hipótesis
> del modelo; diez giros corregidos en la copia. Persisten 17478998, 17884471 y
> el gate de huella de Validate. El texto siguiente conserva el cierre anterior.

**BLOQUEADO para ejecución real. Código de lanzamiento preparado; no es una aprobación científica ni un preflight aprobado.**

Se continuó el diff de rescate sin reset. No se ejecutaron Validate, preflight completo,
Run1000, Java/Maven, MATSim, generación de población masiva ni replay. No se usaron
subagentes. No se cambiaron Java de Correcciones 1–4, generador OD, red, OSM local,
carriles, semáforos, capacidades, horarios ni históricos.

## Resultado geográfico

Se descargó la [relación OSM 9283360 completa](https://api.openstreetmap.org/api/0.6/relation/9283360/full),
versión **34**, changeset **188201709**, timestamp **2026-08-29T14:55:45Z**.
Los tags son Zona 1, administrative, admin_level=8, type=boundary. Coincide con
la revisión de la relación dentro del OSM local. La descarga contiene los **59 ways
exteriores**, todos sus nodos y un label; al OSM local le faltan **43** de esos ways.

Se ensambló un anillo cerrado sin autointersecciones, con orientación exterior
antihoraria, lon/lat WGS84 y sin miembro `crs`. No se simplificó ni recortó contra
el bbox. El área geodésica WGS84 calculada es **6.412448522 km²**, no 6.89 km².
Esta diferencia se conserva explícitamente: no se escaló la geometría para ajustar
el dato aproximado. Es cartografía comunitaria OSM administrativa; no certificación
catastral municipal ni levantamiento GIS verificado de la geometría vial local.

Archivo: `scenarios/zona1/od/balanced-gateway-v1/perimeter.geojson`.

SHA256: `441e7ca4fefff91d7b475d26f12a600415c67b862c5bb2195cd13f486b015688`.

Atribución: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).
La respuesta original y metadatos quedan en `source/`; la fecha, revisión y hashes
de fuentes y red están en `geography-review.json`. Los dos registros ArcGIS
anteriores (44 partes, aproximadamente 0.52 km²) se conservan como evidencia
rechazada para este propósito; no se usaron ni fusionaron con OSM.

El perímetro y las polilíneas viales se transformaron a **EPSG:32615** para revisar
intersecciones y longitudes. Resultado de 6183 enlaces dirigidos:

| Clasificación geométrica | Enlaces |
|---|---:|
| Interiores | 5623 |
| Entrada exterior → interior | 27 |
| Salida interior → exterior | 27 |
| Exteriores | 504 |
| Complejos/sobre límite, excluidos | 2 |

Hay **27 anclas candidatas de entrada y 30 de salida** con cadenas exteriores
existentes de hasta 250 m, conectadas según carriles, y primera cola suficiente
para el mayor vehículo particular más 0.10 m. Son anclas, no 57 cruces distintos.
La conectividad interior del grafo de carriles permite **706 pares candidatos**;
esto no acredita legalidad OSM ni aceptación de todo el OD. Hay **62 candidatos
interiores** en driveways/parking_aisles mapeados con espacio suficiente.

Ejemplos reales, sin crear enlaces:

- Entrada: `osm_30279782_1_forward → osm_30279782_2_forward → osm_30279782_3_forward`.
  Ancla exterior de 38.4962 m, primera cola 7.6992 m; capacidad nativa 2000 PCU/h,
  carril asumido por el importador, no observado en campo.
- Salida: `osm_30263020_50_forward → osm_30263020_51_forward → osm_381667651_19_forward`.
  Ancla exterior de 65.0384 m, primera cola 13.0077 m; capacidad nativa 6000 PCU/h,
  3 carriles de la etiqueta OSM. Tampoco es un aforo de incorporación.

`network-access-inventory.csv` contiene todos los IDs, predecesores/sucesores
permitidos por carriles, longitudes, primeras colas, capacidades y fuentes de
carriles. `access.json` conserva hashes y candidatos en campos `candidate_*`;
**review.verified=false** y las listas de accesos aprobados permanecen vacías.
No basta con cambiar esa bandera: faltan los siguientes controles.

## Bloqueos exactos

1. El comprobador existente `validate_osm_turns` rechaza **12 relaciones**:
   `6008781, 6016436, 17146405, 17146406, 17373677, 17475192, 17478998,
   17502672, 17884471, 17947071, 20224530, 20224531`.
   `osm-turn-evidence.json` contiene miembros, enlaces, movimientos/carriles y
   secuencias de cada restricción. Resolverlas requiere una revisión de red/carriles
   autorizada por separado; esta tarea prohíbe editar esos archivos. No se desactivó
   el validador ni se creó una whitelist para esconderlas.
2. Faltan permiso de actividad y capacidad documentada de incorporación para
   anclas/sitios concretos. La capacidad nominal de circulación de un enlace es
   únicamente un límite superior, no evidencia de su flujo de incorporación.
   Se guardan como `null`, sin inventar mediciones o aprobaciones.
3. A estos cruces les falta continuación exterior utilizable en la red actual:
   entradas `osm_30263035_0_forward`, `osm_30263036_0_forward`,
   `osm_59566258_0_forward`, `osm_67112965_0_forward`,
   `osm_142995412_0_forward`, `osm_381158292_0_forward`,
   `osm_405703103_1_backward`, `osm_1467361288_0_forward`;
   salidas `osm_59566258_0_backward`, `osm_405703103_1_forward`,
   `osm_732305247_8_forward`. El cruce `osm_699533700_8_forward` no tiene
   observador interior inmediato permitido. Los nodos y conexiones exactos están
   en `geography-review.json → blocked_crossings`. No se afirma que toda la red
   carezca de gateways; se excluyen estos casos.
4. Validate integrado de esta revisión y preflight real de 180000 quedan a cargo
   del usuario. El preflight recorre el iterador OD existente sin guardar población;
   puede rechazar capacidad/cohortes manteniendo N, horarios y composición.
5. Incorporación observada, despeje corporal, llegadas, completed/valid y screening
   requieren eventos de una corrida real. No se predicen ni se fabrican aquí.

Mezcla: `mix.json`, **EE/EI/IE/II = 50/20/20/10**, hipótesis sintética
`synthetic-ee50-ei20-ie20-ii10-v1`; su hash y alcance están en
`mix-provenance.json`. Aplica a 178200 particulares, no reemplaza la carga ni buses.

## Contratos reparados y pruebas

- Adaptador Python: `allow_abbrev=False`; rechaza dos mezclas; conserva JSON decimal
  como un solo argumento y rutas con espacios.
- PowerShell: nombres y valores en elementos separados; aserciones de argv en
  checker, workflow, lanzador y wrapper Python. Splatting nativo entre wrappers.
- Resultados: PASSED=0, BLOCKED/FAILED=1, REVIEW_REQUIRED=3; estados/logs/código
  propagados. Un `completed/valid` con screening `review_required` conserva
  informes y gráficas y termina 3, sin etiquetarlo fallo nativo MATSim.
- `-FirstScaleTrial`: decisión explícita registrada en request.json. No lee ni
  escribe aprobación Run1000; mantiene Validate integrado, fingerprint, runtime,
  exclusión de escritores, mutex, memoria/disco, preflight, hashes y auditorías.
- 180000: 79200 carros + 99000 motos + 1800 camiones compactos; 269 buses
  adicionales. Seed 20261023, iteración 0, JDK17, weekday-compact-v3, servicios
  2026-10-23. El generador ya admitía el tamaño; no se cambió su algoritmo.
- Balanced no ejecuta ni depende de la herramienta replay. El pipeline oficial
  de gráficas/empaquetado conserva el requisito completed/valid.

**18 pruebas focalizadas distintas aprobadas:** 17 en
`python/test_simz1_rescue_contracts.py` y la regresión existente
`LaunchContracts.test_adapter_preserves_decimal_json_as_one_argument`.
Fixtures pequeñas/temp; ningún Java, Validate, preflight real ni población masiva.
Incluyen checker fallido sin PASS, wrappers anidados 0/1/3, fingerprint obsoleto,
lectura de gzip truncado y cuatro PNG desde un log mínimo conservando sus fuentes.
Se corrigió y repitió la prueba PNG para cerrar el descriptor del log.

## Comandos manuales

Ejecutar cada bloque por separado. La ruta real conserva el punto antes de UVG.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
```

Validate integrado (el nombre histórico 110k también valida la revisión 180k):

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Validate fallo: $LASTEXITCODE" }
```

Preflight, sin iniciar simulación; actualmente bloqueará por el catálogo no verificado:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Preflight BLOQUEADO/FAILED: $LASTEXITCODE" }
```

Inicio manual **solo después de resolver los bloqueos y aprobar Validate/preflight**:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
$launchExit = $LASTEXITCODE
if ($launchExit -eq 3) { Write-Warning 'MATSim completed/valid; screening review_required. Conservar graficas e informes.' }
elseif ($launchExit -ne 0) { throw "Lanzamiento detenido: $launchExit. Consultar state.json y logs." }
```

Monitoreo en otra terminal; el lector histórico ahora admite 110000/180000:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -List
$launchId = Read-Host 'LaunchId exacto de 180000, impreso por el lanzador'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Watch
```

Gráficas oficiales y empaquetado de una carpeta explícita completed/valid. No repite MATSim:

```powershell
$runDir = Read-Host 'Ruta completa de la corrida exacta'
$runId = Read-Host 'run_id exacto de run-manifest.json'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runDir -ExpectedRunId $runId
$analysisExit = $LASTEXITCODE
if ($analysisExit -eq 3) { Write-Warning 'Graficas conservadas; screening review_required.' }
elseif ($analysisExit -ne 0) { throw "Analisis/empaquetado fallo: $analysisExit" }
Get-ChildItem -LiteralPath (Join-Path $runDir 'analysis') -Filter *.png -Recurse | Select-Object FullName
Get-ChildItem -LiteralPath (Join-Path $runDir 'entregables') -Filter *.png -Recurse | Select-Object FullName
```

PNG oficiales: `analysis/it.0/graficas_perfiles/`; copias empaquetadas bajo
`entregables/<nombre-carpeta-corrida>/graficas/`.

Diagnóstico de una corrida fallida/interrumpida, sin alterar manifiesto, fuentes o aceptación:

```powershell
$runDir = Read-Host 'Ruta completa de la corrida fallida/interrumpida'
$runId = Read-Host 'run_id exacto de run-manifest.json'
& .\.venv\Scripts\python.exe -B .\python\simz1_diagnostic_plots.py --run-dir $runDir --expected-run-id $runId --iteration 0
if ($LASTEXITCODE -ne 0) { throw "Diagnostico sin evidencia suficiente o bloqueado: $LASTEXITCODE" }
Get-ChildItem -LiteralPath (Join-Path $runDir 'analysis\diagnostico-provisional') -Filter *.png -Recurse | Select-Object FullName
```

Cada exportación conserva sus PNG, `hours.csv` y `report.json` en una subcarpeta
única. Cada PNG incluye Run ID, estado real, cobertura, fuentes, incompletitud y
aviso de que no es una gráfica científica completed/valid. Lee eventos parciales
o `SIMZ1_PROGRESS` del log de esa iteración; no mezcla iteraciones ni inventa
horas sin evidencia. Los deltas del log se asignan a la hora del fin de su
intervalo, sin interpolar. Carga/buses requieren IDs guardados de esa corrida;
salidas programadas requieren planes cuyo hash coincida. Sin evidencia suficiente,
omite esa métrica; sin métricas, escribe informe y termina 2, sin PNG ficticios.

## Archivos del cierre

Modificados: `python/simz1_balanced_execute.py`, `simz1_balanced_launch.py`,
`simz1_experiment_preflight.py`, `simz1_workflow_state.py`,
`test_simz1_balanced_launch.py`; `scripts/check_simz1_110k_balanced_gateway.ps1`,
`run_massive_z1_pasante_10it.ps1`, `run_massive_z1_pasante_1it.ps1`,
`run_simz1_110k_balanced_gateway.ps1`, `run_simz1_with_analysis.ps1`,
`simz1_workflow.ps1`, `watch_simz1_110k.ps1`; nota de actualización en FASE_6_110K.md.

Nuevos: `scripts/simz1_launch_contract.ps1`, `run_simz1_180k_balanced_gateway.ps1`;
`python/simz1_scale_contract.py`, `review_simz1_osm_perimeter.py`,
`simz1_diagnostic_plots.py`, `test_simz1_rescue_contracts.py`; esta guía y los
insumos/evidencias en `scenarios/zona1/od/balanced-gateway-v1/`.
