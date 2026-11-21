# SimZ1: accesos sobre la derivación efectiva del transporte

Fecha: 2026-11-01. Alcance: preparación Python, sin simulación.

**Estado: LISTO PARA VALIDATE/PREFLIGHT.** La preparación balanceada pequeña
terminó; Validate y DryRun 180K quedan pendientes de ejecución manual.

## Causa y cambio

`generar()` construía el modelo OD con `network.xml` y `lanes.xml` fuente,
escribía los particulares, y después llamaba a `attach_transit()`. El servicio
existente mueve la división entre cola receptora y terminal mediante
`service_original_endpoint_before_conflict_v1`. La comparación final detectaba
correctamente que las pruebas de accesos correspondían a otros extremos.

Ahora el orden balanceado es: auditoría fuente, copias aisladas, una sola llamada
a `attach`, auditoría efectiva, reconstrucción y comprobación de la derivación,
revisión física efectiva, modelo y demanda OD, carga, guardas finales y creación
normal del manifiesto. La flota no depende de que `plans.xml` ya exista; recibe
la cuota de 99 particulares, separada del camión y de los buses.

`derive_geometry()` contiene el bloque existente de derivación, extraído de
`attach` sin cambiar las fórmulas ni la selección de paradas. Se reutiliza para
reconstruir la transformación declarada. No hay otra transformación para DryRun.
No se eliminó ni se amplió la tolerancia de `check_effective_network()`.

## Código

- `python/generate_montecarlo_z1.py`: `generar()` adelanta el servicio balanceado
  y construye el OD con su configuración efectiva. Conserva la llamada tardía
  para modalidades ajenas al experimento balanceado.
- `python/simz1_weekday_transit.py`: extracción de `derive_geometry()`; `attach()`
  conserva sus archivos, horarios, flota y protección contra sobrescritura.
- `python/simz1_effective_access.py`: `prepare()` y `review()` compartidos;
  comparaciones semánticas, reconstrucción y evidencia de recursos efectivos.
- `python/simz1_balanced_od.py`: constructor reutilizable después de comprobar
  fuentes; `iter_candidates()` reutiliza exactamente el filtro de destinos para
  comprobar conectividad sin enumerar innecesariamente todas sus alternativas.
- `python/simz1_balanced_od_audit.py`: `validate_manifest()` reconstruye la revisión
  efectiva desde los artefactos fijados; amplía la firma de implementación.
- `python/simz1_balanced_launch.py` y `python/simz1_experiment_preflight.py`:
  usan `prepare()` con los servicios configurados, en una carpeta temporal que
  se elimina; no escriben población ni publican una corrida.
- `python/test_simz1_effective_access.py`: integración real N=100 y regresiones.
- `python/test_simz1_lane_policy_integration.py`: reemplaza la expectativa de
  rechazo histórico por preparación efectiva; ya no sobrescribe su evidencia.

## Trazabilidad y límites

El catálogo `access.json` se copia sin modificarlo. Sus hashes siguen apuntando
a las fuentes revisadas. La nueva evidencia `inputs/effective-access-review.json`
es un artefacto independiente, fijado por el manifiesto. Registra fuentes,
catálogo, perímetro, OSM, servicio original copiado, bundle, implementación,
política, ajustes reconstruidos, archivos efectivos y firmas semánticas.

Se distinguen expresamente los hashes de archivos, las firmas numéricas y
estructurales de los XML, y la identidad de la transformación. Una serialización
legítima puede tener bytes diferentes; un extremo, capacidad, longitud o
movimiento distinto de la derivación reconstruida se rechaza.

La revisión vuelve a comprobar cadenas y egresos, movimientos, secuencias,
carrocería y separación de 0.10 m, extremos nativos, despeje exterior y presupuestos
por enlaces y terminales únicos. Conserva las longitudes útiles aprobadas y sus
presupuestos; no amplía permisos por disponer de una cola más larga. No suma
longitudes de segmentos que comparten espacio ni presupuestos de alternativas.
El libro de recursos compartidos del OD permanece vigente.

Se conserva la auditoría OSM previa: 10 restricciones de pares, 22 referencias
retiradas, la secuencia 17478998 y el tratamiento exacto de 17884471. La advertencia
de fuente malformada de 17884471 continúa apareciendo. No se reinterpretó como
permiso para un movimiento. Java de movimiento, semáforos, prioridades, FIFO,
reservas, dimensiones, servicios y recibos de aprobación permanecen intactos.

## Revisión efectiva

Se aceptan los 44 recursos existentes: 10 entradas, 12 salidas y 22 orígenes
interiores. Ninguno de los 46 extremos modificados intersecta sus cadenas o
egresos. Los 46 son enlaces interiores del dominio de rutas y destinos; la
evidencia enumera la intersección por enlace, no una whitelist.

Para `osm_384762167_1_forward` se comprueban 10.488502634659277 m en la fuente y
50.44251317329641 m efectivos, con longitud 52.44251317329641 m conservada. Su
terminal queda en 2.0 m. Los carriles efectivos conservan el hash observado:
`a09fe2aa1534c6a1980f3b054807a346c26fae89b8fb5daf9120c270235d1c00`.

No se pierde ningún destino elegible. El cambio físico declarado hace elegible
para carrocería de 4.5 m más 0.10 m al enlace `osm_51770227_9_forward`, cuyo
extremo pasa de 3.6555319678805507 a 16.277659839402755 m. Para 2.1 m no cambia
el conjunto. Es una consecuencia explícita de la derivación existente, sin
editar destinos ni cuotas para evitar un rechazo.

En la preparación final N=100, 22 de esos enlaces aparecen en rutas privadas,
uno es destino de un viaje privado y ninguno es origen. Los 46 aparecen en
partes de rutas del transporte público. El detalle por enlace y viaje está en
`runtime/effective-access-repair/prepared-route-intersections.json`, vinculado
por hash a la revisión efectiva del primer preparado final.

## Preparación y pruebas

Los resultados y los intentos de desarrollo se conservan bajo
`runtime/effective-access-repair/`. La evidencia histórica de
`runtime/lane-policy-repair/` permanece sin cambios. La comparación inicial de
fuentes, Java, recursos, recibos y documentos está en `before-sha256.json`.

La preparación usa N=100, semilla 20261023, 44 carros, 55 motos, 1 camión compacto
y 269 buses adicionales. Los particulares son 99: EE=49, EI=20, IE=20, II=10.
Se conservan los horarios de catálogo y las 15336 expediciones del servicio.
Los dos manifiestos finales quedaron `prepared`, validación `pending`, iteración
solicitada 0 y ninguna iteración completada. Esto no acredita resultados QSim.

Resultados definitivos: `runtime/effective-access-repair/final-tests/`.
`prepared-100-1/run-manifest.json` tiene ID
`simz1-956a601ddcd546489967b8a07844f7c7`; `prepared-100-2/run-manifest.json`,
`simz1-5a44e260cef14a35a1aa326d5f8a4896`. El generador normal escribió ambos
manifiestos después de sus validadores reales. Sus 42 registros de entrada
están presentes y coinciden con sus hashes; los XML son legibles.
Planes, red, carriles, flota, paradas y horarios coinciden entre ambas
preparaciones. `attach` se invocó una vez por preparación; adjuntarlo otra vez
en la misma carpeta se rechaza sin sobrescribirla.

Resumen: `final-tests/integration-evidence.json`. Cierre con códigos, hashes de
logs, manifiestos e integridad de fuentes: `closure.json` en el directorio de
evidencia. Los resultados nunca se promueven a `completed/valid`.

La paridad invoca ambos preflights con sus parámetros reales y detiene la prueba
antes de recorrer la demanda masiva. Se compara el modelo efectivo obtenido con
el de la preparación completa N=100. No se considera un DryRun 180K aprobado.

Regresiones relacionadas ejecutadas con `.venv/Scripts/python.exe -B`:

| Selección unittest | Casos | Salida | Log en `runtime/effective-access-repair/` |
| --- | ---: | ---: | --- |
| `test_simz1_balanced_gateway_od`, `test_simz1_stop_queue_refinement`, `test_simz1_balanced_launch.LaunchContracts` | 43 | 0 | `related-tests.log` |
| Preparación `network` de seis particulares y paridad negativa de auditorías fuente | 2 | 0 | `source-gates-regression.log` |
| `test_simz1_effective_access.NonBalancedInputCompatibilityTests` | 1 | 0 | `null-lane-regression-3.log` |
| `test_simz1_effective_access.EffectiveAccessTests`: dos preparaciones normales N=100, paridad, secuencia, mutaciones, serialización, repetibilidad y fuentes | 11 | 0 | `final-tests.log` |

**57 pruebas focalizadas aprobadas.** La suite final tardó 784.077 s. Las líneas
`Timeout (0:03:00)` de ese log son instantáneas periódicas de diagnóstico de
`faulthandler`, no fallos ni terminaciones: el resultado es `OK`, `EXIT_CODE 0`.
No se sustituyeron generador, transporte ni validadores por éxitos simulados;
los observadores de pruebas llaman a las funciones reales y conservan sus
resultados. La creación de procesos hijos está bloqueada durante preparación.

Para reproducir únicamente las 12 pruebas del nuevo módulo, en un directorio
de evidencia nuevo (sin borrar ni reutilizar resultados):

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$env:PYTHONPATH = Join-Path (Get-Location) 'python'
$env:SIMZ1_EFFECTIVE_TEST_EVIDENCE = Join-Path (Get-Location) ('runtime\effective-access-repair\recheck-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -B -m unittest -v test_simz1_effective_access
$testExit = $LASTEXITCODE
if ($testExit -ne 0) { throw "Pruebas detenidas: codigo $testExit" }
```

Se conservan los intentos de desarrollo: una llamada incorrecta al verificador
de metadatos falló antes de población; otra revisión redundante se detuvo para
usar el filtro compartido de candidatos. Dos preparaciones completas previas
quedaron archivadas en `tests-1`, sin reescribir sus firmas tras la corrección
de compatibilidad de entradas `null`. La prueba de compatibilidad usó primero
una fixture inapropiada: quitar los carriles del escenario revisado elimina
sus restricciones y se rechaza correctamente. Su prueba positiva final usa una
copia temporal del modo histórico sin archivos de carriles ni señales activos;
no modifica la configuración balanceada.

No se ejecutaron Validate integrado, DryRun masivo, Run1000, Maven, Java, MATSim,
QSim, visor, replay ni generación masiva. Las pruebas de preparación impiden
crear procesos hijos. No se utilizaron subagentes.

## Comandos manuales

Ejecutar por separado y en orden. Los cambios requieren un Validate nuevo;
no se modifican los recibos existentes. N=180000 conserva 79200 carros,
99000 motos, 1800 camiones compactos y 269 buses adicionales. OD sobre 178200
particulares: EE=50 %, EI=20 %, IE=20 %, II=10 %. Semilla 20261023, JDK17,
una iteración con índice 0 y primera escala explícita.

Validate:

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
$validationExit = $LASTEXITCODE
if ($validationExit -ne 0) { throw "Validate detenido: codigo $validationExit" }
```

DryRun 180K:

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
$preflightExit = $LASTEXITCODE
if ($preflightExit -ne 0) { throw "DryRun detenido: codigo $preflightExit" }
```

Lanzamiento 180K, después de aprobar los dos pasos anteriores:

```powershell
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
$launchExit = $LASTEXITCODE
if ($launchExit -ne 0) { throw "Lanzamiento detenido para revision: codigo $launchExit. Consulte state.json y logs." }
```
