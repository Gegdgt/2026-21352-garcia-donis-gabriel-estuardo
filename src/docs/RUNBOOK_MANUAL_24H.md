# Estado vigente: seis DryRuns elegibles y Run1000 recuperada; Run exclusivamente manual

2026-11-05 23:55 Guatemala. Huella validada **`d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d`**,749 dependencias. Validate `balanced-launch-890908db581e4f7290fe2f191495da63` PASS0 y recuperación `b5666e151a3f41f5bcc8176f6a90aa38` PASS0. Run1000 existente `simz1-61974d8bfa6a4e5cb34739d9d76c0e3c` / LaunchId `1ec248b580a24c5fa933c57d17fcc56b` / it.0 está oficialmente aceptada para el siguiente ensayo de carga; conserva988 completados y2 censurados. No necesita otra QSim. [Avance y causa del defecto](SIMZ1_180000_AVANCE.md), [índice de recibos](../runtime/diagnostics/launcher-repair-20261105/final-status.json).

| Escenario | N | Contrato | Validate | DryRun | LaunchId DryRun | run_launch_eligible | Observaciones |
|---|---:|---|---|---|---|---|---|
| Run1000 | 1000 | v3 / `run1000` | PASS0 | PASS0 | `de24f4cec7834d39b0cb370c7ec15ed3` | true | 440 carros / 550 motos / 10 camiones; +269 buses |
| Run10000 | 10000 | v5 / `run10000` | PASS0 | PASS0 | `3c17e4f81421405a8d6c7fbb4a029c5e` | true | 4400 carros / 5500 motos / 100 camiones; +269 buses |
| Run55000 | 55000 | v3 / `quarter` | PASS0 | PASS0 | `d0d0694dc6534355aef253bcd6c5ce97` | true | 24200 carros / 30250 motos / 550 camiones; +269 buses |
| Run110000 | 110000 | v3 / `half` | PASS0 | PASS0 | `77fb528d35fc4d9bbfdc61b407eb3659` | true | 48400 carros / 60500 motos / 1100 camiones; +269 buses |
| Masiva aleatoria | 201381 | v4 / `random-full-1` | PASS0 | PASS0 | `4bea6d88762f4823abaeb351c2fa1a60` | true | 88608 carros / 110759 motos / 2014 camiones; +269 buses |
| Max-test | 220000 | v3 / `max-test` | PASS0 | PASS0 | `eb0f06364c25416299cf33e6c1659c08` | true | 96800 carros / 121000 motos / 2200 camiones; +269 buses |

Los seis aprobaron composición, huella, SHA/copias/reconstrucción, Java17, memoria, disco, exclusividad, retención y gate de aceptación correspondiente. Todos usan una iteración0, semilla20261023, servicio2026-10-23,24h físicas y269 buses adicionales. Retención: intervalos1/1, Until Java0/1 (no parámetros XML), eventos y planes it.0 más copias finales gzip. Piso100GiB o mayor cálculo; no bajar guardas. El Run revalida identidad, recursos y exclusividad en el momento real de arrancar.

La selección antigua de189834 es histórica e incompatible con esta huella. La selección vigente de201381 procede de un único sorteo oficial del candidato `2c694e9df27d464d94d30b2aa8ffb5ad`, selección `a17518bffee840818110232374a05b17`; usar su experiment.json exacto. No volver a sortear ese candidato, no editar el JSON y no reutilizar recibos históricos.

## Comprobación de lectura antes de elegir un escenario

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
$simz1Delivery = Get-Content -LiteralPath '.\runtime\diagnostics\launcher-repair-20261105\final-status.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Delivery.status -cne 'VALIDATED_RECOVERED_ALL_SIX_DRYRUNS_ELIGIBLE') { throw 'Revisar estado de entrega.' }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-balanced-validation
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Validate vigente rechazado: $rc" }
$simz1Fingerprint = & .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py fingerprint
$rc = $LASTEXITCODE
if ($rc -ne 0 -or $simz1Fingerprint.Trim() -cne $simz1Delivery.source_fingerprint) { throw 'La revision cambio; no reutilizar estos DryRuns.' }
$simz1Delivery.scenarios | Select-Object label,N,scenario,dryrun_launch_id,run_launch_eligible
```

## Comandos PowerShell5.1 separados por escenario

Los bloques siguientes son instrucciones para el usuario y **no fueron ejecutados por Codex**. Elegir sólo un bloque; no ejecutar la batería en cadena. Mantener fuentes e insumos congelados durante el Run. El lanzador exige el DryRunLaunchId real del mismo selector/política/huella y crea una identidad Run nueva; no reutiliza el Run ID recuperado. Código3 conserva review_required y sus informes; no representa aceptación del ensayo. Los demás errores se conservan y diagnostican sin reintento automático.

### Run1000 / run1000

Referencia para un ensayo futuro nuevo; la Run1000 actual ya está recuperada y no necesita repetirse.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -ExperimentScenario run1000 -DryRunLaunchId de24f4cec7834d39b0cb370c7ec15ed3 -PostprocessingPolicy automatic_replay_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run1000 fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

### Run10000 / run10000

10000 vehículos no públicos más269 buses; política native_diagnostic_v1.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261105-run10k-24h-v5.json -ExperimentScenario run10000 -DryRunLaunchId 3c17e4f81421405a8d6c7fbb4a029c5e -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run10000 fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

### Run55000 / quarter

55000 vehículos no públicos más269 buses; política automatic_replay_v1.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -ExperimentScenario quarter -DryRunLaunchId d0d0694dc6534355aef253bcd6c5ce97 -PostprocessingPolicy automatic_replay_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run55000 fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

### Run110000 / half

110000 vehículos no públicos más269 buses; política native_diagnostic_v1.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -ExperimentScenario half -DryRunLaunchId 77fb528d35fc4d9bbfdc61b407eb3659 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run110000 fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

### Masiva aleatoria / random-full-1

201381 vehículos no públicos más269 buses; política native_diagnostic_v1.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\runtime\experiment-selections\a17518bffee840818110232374a05b17\experiment.json -ExperimentScenario random-full-1 -DryRunLaunchId 4bea6d88762f4823abaeb351c2fa1a60 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Masiva aleatoria fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

### Max-test / max-test

220000 vehículos no públicos más269 buses; política native_diagnostic_v1.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -ExperimentScenario max-test -DryRunLaunchId eb0f06364c25416299cf33e6c1659c08 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Max-test fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes, sin promover la corrida.' }
```

## Seguimiento de solo lectura y recuperación

Después de iniciar manualmente el escenario elegido, copiar el **LaunchId nuevo del Run** que imprime LAUNCH EVIDENCE. En otra PowerShell, desde la raíz:

```powershell
$simz1LaunchId = Read-Host 'LaunchId REAL del Run que desea observar'
if ($simz1LaunchId -cnotmatch '^[a-f0-9]{32}$') { throw 'LaunchId invalido.' }
Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1LaunchId + '\state.json')) -Raw -Encoding UTF8
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $simz1LaunchId -Watch -Iteration 0
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Monitor: $rc" }
```

Para lectura puntual usar -Evidence en lugar de -Watch. No agregar -Events. Cerrar el observador no detiene la simulación. No usar el LaunchId del DryRun como si fuera el Run.

Si falla análisis/empaquetado después del cierre nativo, conservar completed/valid, eventos y estado histórico; diagnosticar y usar el mecanismo de recuperación con la identidad explícita y transición revisada cuando corresponda. La recuperación ya realizada está en `runtime/recoveries/b5666e151a3f41f5bcc8176f6a90aa38/recovery-receipt.json`; no volver a ejecutarla sin causa. Screening_pass y BUILD SUCCESS no sustituyen al inspector ni permiten fabricar aceptación.

DryRun no garantiza movilidad, descarga, runtime, memoria máxima, volumen de eventos ni finalización a mayor escala. Los presupuestos son estimaciones. No hubo inspección visual HTTP/UI; las tres omisiones históricas L12 siguen pendientes. No se modificaron generadores de gráficos ni visor. El contenido inferior se conserva sólo como historial; no ejecutar sus comandos ni reutilizar sus aprobaciones.

## Histórico: runbook de consolidación anterior al fallo de cierre

# Estado histórico: nueva Run1000 manual tras consolidación y arreglo físico

2026-11-05 Guatemala. El principal `matsim-guatemala` es la base de desarrollo. Las preparaciones Run10K/Run110K/masiva que aparecen más abajo son **históricas y no elegibles para la nueva revisión física**. No ejecutar esos bloques con los recibos anteriores. No se permite acreditar esta revisión con una Run1000 antigua.

El cierre de consolidación, la huella congelada, Validate y DryRun se registran en [avance activo](SIMZ1_180000_AVANCE.md) y `runtime/diagnostics/consolidacion-20261105/final-status.json`. Este runbook no sustituye esos recibos. La única ejecución futura preparada en esta entrega es **Run1000 manual**; Codex no la inicia.

Contrato oficial: `scenarios/zona1/experiments/final-20261104-24h-v3.json`, selector `run1000`; 1000 no públicos (440 carros,550 motos,10 carga) y269 buses adicionales; una iteración0, semilla20261023, servicio2026-10-23, observación24h (86400s; último paso QSim86399), balanced-gateway-v1, L18 revisada y compact-v3. La política del ensayo es `automatic_replay_v1`; no usar FirstScaleTrial ni cambiarla a `native_diagnostic_v1`.

## Comprobación de preparación sin iniciar QSim

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Delivery = Get-Content -LiteralPath '.\runtime\diagnostics\consolidacion-20261105\final-status.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Delivery.status -cne 'READY_FOR_MANUAL_RUN1000') { throw 'Entrega no preparada; revisar el bloqueo registrado.' }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-balanced-validation
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Validate vigente rechazado: $rc" }
$simz1CurrentFingerprint = & .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py fingerprint
$rc = $LASTEXITCODE
if ($rc -ne 0 -or $simz1CurrentFingerprint.Trim() -cne $simz1Delivery.source_fingerprint) { throw 'La revision cambio despues de la entrega.' }
$simz1DryState = Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1Delivery.dryrun_launch_id + '\state.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
$simz1DryRequest = Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1Delivery.dryrun_launch_id + '\request.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1DryState.launch_id -cne $simz1Delivery.dryrun_launch_id -or $simz1DryState.dry_run -ne $true -or $simz1DryState.status -cne 'dry_run_pass' -or $simz1DryState.phase -cne 'completed' -or $simz1DryState.outcome -cne 'PASSED' -or $simz1DryState.exit_code -ne 0 -or $simz1DryState.source_fingerprint -cne $simz1Delivery.source_fingerprint -or $simz1DryRequest.launch_id -cne $simz1DryState.launch_id -or $simz1DryRequest.dry_run -ne $true -or $simz1DryRequest.experiment.scenario -cne 'run1000') { throw 'DryRun no corresponde a la revision preparada.' }
$simz1DryState
```

El DryRun oficial del ensayo se hace con `check_simz1_110k_balanced_gateway.ps1 -Action Run1000 -DryRun -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -JavaHome 'C:\Program Files\Java\jdk-17'`. No repetirlo si el cierre ya lo acredita. Su LaunchId identifica preparación, no simulación. El wrapper Run1000 no recibe DryRunLaunchId; el lanzador vuelve a comprobar Validate, identidad, recursos y exclusividad. `require-experiment-dry-run` corresponde a otros selectores y no se amplía para este ensayo.

## Ejecución exclusivamente manual en PowerShell externa

Ejecutar sólo tras aprobar el bloque anterior, manteniendo las fuentes congeladas. Este bloque no ha sido ejecutado por Codex.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Run1000 -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -JavaHome 'C:\Program Files\Java\jdk-17'
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run1000 fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Screening review_required; conservar informes. No equivale a aceptacion del ensayo.' }
```

## Observar el LaunchId real futuro

Copiar el nuevo LaunchId de `LAUNCH EVIDENCE` del Run anterior, nunca el de DryRun. En otra PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Delivery = Get-Content -LiteralPath '.\runtime\diagnostics\consolidacion-20261105\final-status.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$simz1LaunchId = Read-Host 'LaunchId REAL del nuevo Run1000'
if ($simz1LaunchId -cnotmatch '^[a-f0-9]{32}$') { throw 'LaunchId invalido.' }
$simz1Request = Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1LaunchId + '\request.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
$simz1State = Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1LaunchId + '\state.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Request.launch_id -cne $simz1LaunchId -or $simz1State.launch_id -cne $simz1LaunchId -or $simz1Request.dry_run -ne $false -or $simz1State.dry_run -ne $false -or $simz1State.source_fingerprint -cne $simz1Delivery.source_fingerprint -or $simz1Request.experiment.scenario -cne 'run1000' -or $simz1Request.minimum_non_public_vehicles -ne 1000 -or $simz1Request.maximum_non_public_vehicles -ne 1000) { throw 'No es la nueva Run1000 de esta revision. Si sigue en preflight sin huella, leer state.json y esperar sin relanzar.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $simz1LaunchId -Watch -Iteration 0
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Monitor: $rc" }
```

Para una lectura puntual sustituir `-Watch` por `-Evidence`. No agregar `-Events`. Cerrar el observador no detiene la simulación.

## Auditoría y aceptación posteriores

El lanzador ejecuta auditorías nativas, OD, cuerpos/reservas, carga, buses, horizonte, informes operacionales/balanced, screening y replay, y sólo al aprobar registra el trial de **esa nueva corrida**. Contrastar el Run ID real, it.0, manifiesto completed/valid, state, logs, huella y `runtime/workflow/trial-balanced-gateway-v1.json`. Un código0 aislado, el reloj o algunas llegadas no sustituyen esos controles. Código3 conserva review_required y no acredita el trial.

Después del cierre, comprobar que `run_id` y `run_directory` del recibo trial coincidan con el manifiesto del LaunchId real nuevo y que su `source_fingerprint` sea el de esta entrega. Sólo entonces ejecutar la comprobación de lectura `& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial --state .\runtime\workflow\trial-balanced-gateway-v1.json`, capturando inmediatamente `$rc = $LASTEXITCODE` y deteniéndose si no es0. Esta comprobación no crea aceptación ni inicia Run10K.

Si falla sólo el análisis o replay, diagnosticar y reutilizar el posproceso del RunDir explícito; no repetir QSim. No ejecutar ahora record-trial ni sustituir el RunDir por el de una histórica. Run10K permanece no elegible hasta la aceptación requerida del nuevo ensayo y su DryRun posterior. Los L12 históricos L12_029/d0024, L12_020/d0024 y L12_015/d0040 siguen sin certificar; esta tarea no reconstruye su replay global.

---

## Histórico: runbook previo al arreglo de parada bloqueante y consolidación

Todo lo que sigue conserva procedencia histórica; sus aprobaciones y comandos no representan la revisión vigente.

# Estado vigente: Run10K, Run110K y candidato N=189834 preparados para ejecución manual

2026-11-05 Guatemala. **Validate05, aceptación oficial de Run1000 y los cuatro DryRuns finales aprobaron con código 0**, misma huella `6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`, 736 dependencias. Validate: `balanced-launch-57d99330d7f24d208e4987401bce448b`, Java 17. Run1000 acreditada: `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, sin repetir QSim. Cada DryRun final verificó copia/reconstrucción de identidad y política explícita, `run_launch_eligible=true` y `accepted_same_base_and_revision`. Las tres preparaciones solicitadas están listas para ejecución manual; el extremo 220K sólo se comprobó mediante DryRun, sin solicitar su Run. La [verificación final](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/delivery-verification-05.json) también aprobó: cuatro gates, fuentes/evidencias preservadas y 178.7868 GiB libres al cierre.

**Codex no inició ninguna simulación completa.** No existe Run10K nueva ni Run ID nuevo. Los IDs de esta tabla son exclusivamente DryRuns: el intento Run10K `4fdb670675594543bbdd76a8eb68dbde` quedó fallido antes del manifiesto y de MATSim, íntegramente conservado.

| Preparación | Especificación / selector | DryRunLaunchId aprobado | GiB libres observados |
|---|---|---|---:|
| Run10K | `scenarios/zona1/experiments/final-20261105-run10k-24h-v5.json` / `run10000` | `b8178068f7044364b775449175409a6e` | 179.25 |
| Run110K | `scenarios/zona1/experiments/final-20261104-24h-v3.json` / `half` | `6f693c82bf30455dab9cda467019d693` | 179.24 |
| Candidato masivo N=189834 | `runtime/experiment-selections/32fd3de8aa86485586f84c2e0f0348b7/experiment.json` / `random-full-1` | `892f0111a70d45de8c789aafd01d8a39` | 179.23 |
| Extremo fijo 220K, sólo DryRun | V3 anterior / `max-test` | `aede6a37e6a14c428c660eeda45d939e` | 178.79 |

Los cuatro DryRuns mantienen piso de 100 GiB, memoria `planning_budget_pass`, heap QSim de 12 GiB, SQLite de 8 GiB y scratch de 4 GiB. Son comprobaciones de planificación; el lanzador vuelve a comprobar recursos, exclusividad y huella al iniciar cada Run. No repetir DryRuns válidos ni modificar fuentes entre esas fases.

Todos conservan una iteración, índice 0, horizonte de 24 h, semilla 20261023, servicio 2026-10-23, `balanced-gateway-v1`, L18 revisada, carga compact-v3 y 176 Transmetro + 93 TuBus adicionales. No se alteraron FIFO, señales, reservas ni restricciones OSM. N=180000 quedó cubierto por pruebas de contrato; no se inventó un selector fijo.

| Selección | Carros | Motos | Camiones incluidos en N | N no públicos | Buses | Total físico configurado |
|---|---:|---:|---:|---:|---:|---:|
| Run10K | 4400 | 5500 | 100 | 10000 | 269 | 10269 |
| Run110K | 48400 | 60500 | 1100 | 110000 | 269 | 110269 |
| Candidato masivo | 83527 | 104409 | 1898 | 189834 | 269 | 190103 |
| Extremo 220K, sólo DryRun | 96800 | 121000 | 2200 | 220000 | 269 | 220269 |

El candidato v4 se sorteó **una sola vez**, después de Validate y aceptación: candidato `bac5f258d6d24935a24bdde0888a157a`, selección `32fd3de8aa86485586f84c2e0f0348b7`. Su redondeo es `largest_remainder_private_freight_then_families_then_profiles`. SHA de especificación `21e34a957bad28646ce2c3525a5422c532c6c22b1f37075e48e6046248b6886d`; SHA de selección `c2b2766babfe035a6bc375a14d05e7d72b2b449406b778d750eca2ec1d51b88e`. DryRun y Run usan ese mismo archivo inmutable. **Run no crea candidatos ni vuelve a sortear.** No existe claim de Run al preparar esta entrega.

El fallo original fue `specification_sha256`: la copia de la especificación cambió 50 LF por CRLF, de 1980 a 2030 bytes, SHA `d5f2dc6ea1cbbb66b483c4ddece83c661afcd0302c573faf7e7bc13c59a7157e` → `fb08ee333c09b9fd44d6d581a53087063c8d10063b5ef25d9052168d705090d4`. Se corrigió la copia binaria, conservando el comparador estricto. DryRun ahora ejecuta la misma copia/reconstrucción con archivo temporal, sin población ni corrida simulada, y liga su recibo v2 a selección, huella y política. Los DryRuns históricos `ec5321930d3c4afbbbb2e6ec3491b787` y `975c94c53b0a436aadc3d4e806936c2b` no se reutilizan. El warning OSM `MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER` conserva su tratamiento y no fue la causa fatal.

Pruebas y preservación: 99 de contratos/gates, 38 de replay parcial/lanzador, 43 de compatibilidad, 7 fixtures de huella, 25 JavaScript afectadas y frontend Node PASS0; las 22 pruebas de Parte 2 están incluidas en las 99. Validate04 falló por una fixture que omitía el helper real; su corrección no cambió producción y Validate05 aprobó. Se conservan 126 fuentes físicas, 373 archivos nativos y 41 del intento fallido. [Informe técnico y evidencias](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/IDENTIDAD-TECNICA.md), [avance](SIMZ1_180000_AVANCE.md).

## Bloque A: comprobar los gates de una preparación

Copiar el bloque completo en PowerShell 5.1. Elegir `10k`, `110k` o `masiva`. Comprueba Validate, aceptación oficial y el DryRun exacto; no inicia QSim. `require-trial` puede tardar al verificar artefactos nativos.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Type = Read-Host 'Preparacion: 10k / 110k / masiva'
switch ($simz1Type) {
    '10k' {
        $simz1Spec = '.\scenarios\zona1\experiments\final-20261105-run10k-24h-v5.json'
        $simz1Selector = 'run10000'
        $simz1DryRunId = 'b8178068f7044364b775449175409a6e'
    }
    '110k' {
        $simz1Spec = '.\scenarios\zona1\experiments\final-20261104-24h-v3.json'
        $simz1Selector = 'half'
        $simz1DryRunId = '6f693c82bf30455dab9cda467019d693'
    }
    'masiva' {
        $simz1Spec = '.\runtime\experiment-selections\32fd3de8aa86485586f84c2e0f0348b7\experiment.json'
        $simz1Selector = 'random-full-1'
        $simz1DryRunId = '892f0111a70d45de8c789aafd01d8a39'
    }
    default { throw 'Preparacion invalida.' }
}
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-balanced-validation
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Validate vigente rechazado: $rc" }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial --state .\runtime\workflow\trial-balanced-gateway-v1.json --experiment-spec $simz1Spec --experiment-scenario $simz1Selector
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Aceptacion nativa Run1000 rechazada: $rc" }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-experiment-dry-run --experiment-spec $simz1Spec --experiment-scenario $simz1Selector --dry-run-launch-id $simz1DryRunId --postprocessing-policy native_diagnostic_v1
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun o prueba de identidad rechazados: $rc" }
$simz1DryDir = Join-Path '.\runtime\launches' $simz1DryRunId
$simz1DryState = Get-Content -LiteralPath (Join-Path $simz1DryDir 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$simz1Proof = Get-Content -LiteralPath (Join-Path $simz1DryDir 'preparation-identity.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1DryState.source_fingerprint -cne '6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023') { throw 'No es la revision aprobada en esta entrega.' }
$simz1FreeGiB = (Get-PSDrive -Name C).Free / 1GB
if ($simz1FreeGiB -lt 100) { throw "Espacio actual menor de 100 GiB: $simz1FreeGiB" }
[pscustomobject]@{
    Selector = $simz1Selector
    DryRunLaunchId = $simz1DryRunId
    RunLaunchEligible = $simz1DryState.run_launch_eligible
    SourceFingerprint = $simz1DryState.source_fingerprint
    PreparationIdentity = $simz1Proof.status
    Policy = $simz1Proof.postprocessing_policy
    FreeGiBNow = [math]::Round($simz1FreeGiB, 2)
}
```

## Bloques B: iniciar una corrida manualmente

**Elegir sólo el bloque de la corrida que se va a ejecutar. No encadenar estos tres bloques ni ejecutarlos en paralelo.** Cada uno es independiente; se mantiene abierta su PowerShell externa hasta terminar preparación, QSim, auditorías y análisis. Codex no ejecutó ninguno. No hay comando Run para el extremo 220K.

**B1 — Run10K.**

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261105-run10k-24h-v5.json -ExperimentScenario run10000 -DryRunLaunchId b8178068f7044364b775449175409a6e -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run10K fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Cierre nativo valido con screening review_required: revisar informes conservados.' }
```

**B2 — Run110K.**

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261104-24h-v3.json -ExperimentScenario half -DryRunLaunchId 6f693c82bf30455dab9cda467019d693 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Run110K fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Cierre nativo valido con screening review_required: revisar informes conservados.' }
```

**B3 — candidato masivo N=189834 ya seleccionado.** Este comando consume esa selección para un único Run; no sortea. Un intento fallido conserva su claim y requiere diagnóstico, no un nuevo candidato automático.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\runtime\experiment-selections\32fd3de8aa86485586f84c2e0f0348b7\experiment.json -ExperimentScenario random-full-1 -DryRunLaunchId 892f0111a70d45de8c789aafd01d8a39 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Corrida masiva fallo: $rc. Conservar evidencia y claim; no volver a sortear." }
if ($rc -eq 3) { Write-Warning 'Cierre nativo valido con screening review_required: revisar informes conservados.' }
```

Copiar el **LaunchId nuevo de Run** impreso en `LAUNCH EVIDENCE`. Su Run ID aparece cuando se publica el manifiesto. No usar el DryRunLaunchId como si fuera una simulación ni repetir el bloque B para comprobar si arrancó.

## Bloque C: observar el LaunchId real y leer el log en vivo

Usar otra PowerShell. Elegir `10k`, `110k` o `masiva` y pegar el LaunchId real de Run. Elegir `monitor`, `log` o `estado`. Para monitor y log simultáneos, usar una consola observadora para cada modo. Copiar completa la estructura condicional; no separar `else`.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Type = Read-Host 'Corrida: 10k / 110k / masiva'
switch ($simz1Type) {
    '10k' {
        $simz1Expected = @{ DryRun='b8178068f7044364b775449175409a6e'; Schema='simz1-final-experiments-v5'; Selector='run10000'; N=10000; SpecSha='d5f2dc6ea1cbbb66b483c4ddece83c661afcd0302c573faf7e7bc13c59a7157e' }
    }
    '110k' {
        $simz1Expected = @{ DryRun='6f693c82bf30455dab9cda467019d693'; Schema='simz1-final-experiments-v3'; Selector='half'; N=110000; SpecSha='e60478c6bc3a89e541de00e40487401d72a7bd2aee852cdc7df1084947306b38' }
    }
    'masiva' {
        $simz1Expected = @{ DryRun='892f0111a70d45de8c789aafd01d8a39'; Schema='simz1-final-experiments-v4'; Selector='random-full-1'; N=189834; SpecSha='21e34a957bad28646ce2c3525a5422c532c6c22b1f37075e48e6046248b6886d' }
    }
    default { throw 'Corrida invalida.' }
}
$simz1LaunchId = Read-Host 'LaunchId REAL de Run, impreso en LAUNCH EVIDENCE'
if ($simz1LaunchId -cnotmatch '^[a-f0-9]{32}$') { throw 'LaunchId invalido.' }
$simz1LaunchDir = Join-Path '.\runtime\launches' $simz1LaunchId
$simz1Request = Get-Content -LiteralPath (Join-Path $simz1LaunchDir 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Request.dry_run -ne $false -or $simz1Request.launch_id -cne $simz1LaunchId -or $simz1Request.dry_run_launch_id -cne $simz1Expected.DryRun -or $simz1Request.postprocessing_policy -cne 'native_diagnostic_v1' -or $simz1Request.experiment.schema -cne $simz1Expected.Schema -or $simz1Request.experiment.scenario -cne $simz1Expected.Selector -or $simz1Request.experiment.specification_sha256 -cne $simz1Expected.SpecSha -or $simz1Request.minimum_non_public_vehicles -ne $simz1Expected.N -or $simz1Request.maximum_non_public_vehicles -ne $simz1Expected.N -or $simz1Request.od_mode -cne 'balanced-gateway-v1') { throw 'No es el Run solicitado con su DryRun, especificacion y politica aprobados.' }
$simz1Mode = Read-Host 'monitor / log / estado'
if ($simz1Mode -notin @('monitor','log','estado')) { throw 'Modo invalido.' }
if ($simz1Mode -eq 'monitor') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $simz1LaunchId -Watch -Iteration 0
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Monitor rechazo la identidad: $rc" }
} else {
    if ($simz1Mode -eq 'estado') {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $simz1LaunchId -Evidence -Iteration 0
        $rc = $LASTEXITCODE
        if ($rc -ne 0) { throw "Observacion rechazada: $rc" }
    } else {
        do {
            $simz1State = Get-Content -LiteralPath (Join-Path $simz1LaunchDir 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($simz1State.launch_id -cne $simz1LaunchId -or $simz1State.dry_run -ne $false -or $simz1State.run_directory -cne $simz1Request.run_directory) { throw 'La identidad del estado difiere del request.' }
            $simz1Log = Join-Path $simz1State.run_directory 'matsim-run.log'
            $simz1LogReady = Test-Path -LiteralPath $simz1Log -PathType Leaf
            if (-not $simz1LogReady) {
                if ($simz1State.finished_utc -or $simz1State.status -eq 'failed') { throw "El lanzamiento termino sin log nativo: $($simz1State.status). Revisar $simz1LaunchDir" }
                Write-Host "Preparacion en curso; esperando $simz1Log"
                Start-Sleep -Seconds 3
            }
        } while (-not $simz1LogReady)
        Get-Content -LiteralPath $simz1Log -Encoding UTF8 -Tail 40 -Wait
    }
}
```

No agregar `-Events` para este seguimiento. `Ctrl+C` en la consola observadora termina su lectura, no la simulación de la otra consola. CPU/reloj avanzando no demuestran descarga; el éxito nativo no demuestra calibración o capacidad de atender toda la demanda. Si falla sólo el análisis, reutilizar el posproceso de esa corrida, sin repetir QSim.

## Visor parcial y límites pendientes

Después del cierre nativo válido de la Run10K real, seguir el [procedimiento actualizado](../runtime/diagnostics/run10k-manual-20261105/viewer/PROCEDIMIENTO.md): RunDir, Run ID, it.0 y ReplayDir explícitos; `--visual-policy partial-native-v1` tanto en comprobación como apertura. No seleccionar la Run1000 de referencia como sustituto de resultados Run10K. Este modo conserva mapa/rutas/itinerarios, pausa, navegación temporal y selección de otros vehículos, evitando índice/grafo causal global; conserva las validaciones nativas/espaciales obligatorias.

**Los tres L12 históricos siguen SIN CERTIFICAR.** El modo parcial puede ocultar más cuerpos dependientes conservadoramente; no reutiliza coordenadas anteriores ni trata un cuerpo pendiente como espacio libre. La comprobación HTTP04 sobre Run1000 aprobó seis ventanas y tres itinerarios, con identidades alteradas rechazadas; servidor cerrado. Los valores pendientes 135/350/405/444/312/3 son semillas de soporte, no cuerpos ocultos ni vehículos distintos. **No se realizó inspección visual real en UI porque el host de navegador no estuvo disponible.** La aceptación visual global permanece incompleta. [Evidencia HTTP](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/partial-http-smoke-result-04.json), [revisión independiente](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/partial-frontend-staging/independent-review-final.json).


## Histórico: encabezado y comandos anteriores a la validación de la corrección

# Estado vigente: Run10K detenida en preparación; no reutilizar el DryRun anterior

2026-11-05 Guatemala. El intento manual `4fdb670675594543bbdd76a8eb68dbde` falló antes del manifiesto y de QSim por un cambio de SHA al copiar la especificación. La corrección está en curso. Los comandos inferiores pertenecen a la entrega anterior; no ejecutarlos hasta renovar las validaciones para la revisión corregida. Se conserva el intento fallido. [Estado y evidencia](SIMZ1_180000_AVANCE.md).

## Histórico: comandos anteriores al fallo de copia de especificación

# Estado vigente: Run10K lista para ejecución manual; Codex no inició Run

2026-11-05 Guatemala. La reparación L12 terminó por decisión del usuario; no ejecutar preparación09 ni otra expansión global. Los tres casos históricos siguen SIN CERTIFICAR. Se preservan sus datos y la Run1000 nativa. El objetivo vigente es validar `scenarios/zona1/experiments/final-20261105-run10k-24h-v5.json`, selector `run10000`:10000 no públicos(4400 carros/5500 motos/100 camiones)+269 buses,24h,it.0,semilla20261023 y servicio2026-10-23. V3 y modalidad aleatoria v4 quedan intactas e inactivas para esta tarea.

Validate integrado **PASS0**, `balanced-launch-91a46198972d44e78a8483266b39c2f9`, Java17, huella `bbcca8d739a8dd0258aec12e4949deea5877b73d9ee043b5ca0680d031ff8a58`,731 dependencias. Inspector/record-trial oficial **PASS0**, reutilizando Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af` sin repetirla. Único DryRun **PASS0**: `ec5321930d3c4afbbbb2e6ec3491b787`, `run_launch_eligible=true`, mismo contrato/base/huella; memoria aprobada y180.88GiB libres frente a100GiB requeridos. [Recibos y evidencia](../runtime/diagnostics/run10k-manual-20261105/RESULTADOS.md).

No existe Run ID ni LaunchId de ejecución Run10K: el ID anterior corresponde sólo al DryRun, que no creó carpeta de simulación. El usuario iniciará la corrida desde PowerShell externa. El nombre180k del lanzador es histórico; la especificación determina N10000. Los bloques siguientes no repiten DryRun ni cambian N fuera del contrato. Mantener las fuentes congeladas; Run vuelve a comprobar gates y recursos actuales.

La aceptación del diagnóstico conserva auditoría nativa, OD, reservas, buses y screening. La especificación v5 separa el replay manual posterior y su aceptación visual pendiente; no convierte las omisiones L12 en violaciones físicas ni las declara resueltas. [Procedimiento posterior al cierre nativo](../runtime/diagnostics/run10k-manual-20261105/viewer/PROCEDIMIENTO.md), sin checkpoint-plan ni otra investigación L12. [Estado](SIMZ1_180000_AVANCE.md).

**1. Comprobar aprobación y DryRun existentes, sin QSim ni nuevo DryRun.**

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$spec = '.\scenarios\zona1\experiments\final-20261105-run10k-24h-v5.json'
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-balanced-validation
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Validate vigente rechazado: $rc" }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial --state .\runtime\workflow\trial-balanced-gateway-v1.json --experiment-spec $spec --experiment-scenario run10000
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Aceptacion nativa Run1000 rechazada: $rc" }
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-experiment-dry-run --experiment-spec $spec --experiment-scenario run10000 --dry-run-launch-id ec5321930d3c4afbbbb2e6ec3491b787
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun incompatible o no elegible: $rc" }
```

`require-trial` vuelve a comprobar la evidencia nativa histórica y puede tardar; no inicia simulación. Una huella distinta requiere revisar y validar esa revisión, no editar recibos.

**2. Iniciar manualmente Run10K, en una PowerShell externa que se mantendrá abierta. Este bloque no fue ejecutado por Codex.**

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261105-run10k-24h-v5.json -ExperimentScenario run10000 -DryRunLaunchId ec5321930d3c4afbbbb2e6ec3491b787 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento fallo: $rc. Conservar evidencia; no reintentar automaticamente." }
if ($rc -eq 3) { Write-Warning 'Cierre nativo valido con screening review_required; revisar sus informes.' }
```

Copiar el **nuevo** LaunchId impreso en `LAUNCH EVIDENCE`. Su carpeta exacta se guarda en `runtime/launches/<nuevo LaunchId>/state.json`; el Run ID se publica al aparecer el manifiesto. No ejecutar dos veces este bloque para comprobar el primero. Mantener esta ventana abierta durante generación, QSim, auditoría y análisis. El comando no declara llegada de toda la demanda ni aprobación del visor.

**3. Observar ese LaunchId real desde otra PowerShell. Elegir `monitor`, `log` o `estado`; para ver monitor y log simultáneamente, usar una consola para cada modo. `estado` sirve también mañana y no detiene la corrida.**

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$launchId = Read-Host 'LaunchId REAL impreso por tu Run10K (no el DryRun)'
if ($launchId -cnotmatch '^[a-f0-9]{32}$') { throw 'LaunchId invalido.' }
$launchDir = Join-Path 'runtime\launches' $launchId
$request = Get-Content -LiteralPath (Join-Path $launchDir 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($request.dry_run -or $request.launch_id -cne $launchId -or $request.experiment.schema -cne 'simz1-final-experiments-v5' -or $request.experiment.scenario -cne 'run10000' -or $request.minimum_non_public_vehicles -ne 10000 -or $request.maximum_non_public_vehicles -ne 10000) { throw 'No es una ejecucion Run10K v5.' }
$modo = Read-Host 'monitor / log / estado'
if ($modo -notin @('monitor','log','estado')) { throw 'Modo invalido.' }
if ($modo -eq 'monitor') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Watch -Iteration 0
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Monitor rechazo la identidad: $rc" }
} else {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Evidence -Iteration 0
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Observacion rechazada: $rc" }
    if ($modo -eq 'log') {
        $state = Get-Content -LiteralPath (Join-Path $launchDir 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $log = Join-Path $state.run_directory 'matsim-run.log'
        if (-not (Test-Path -LiteralPath $log -PathType Leaf)) { throw 'Log nativo aun no creado; usar monitor durante preparacion.' }
        Get-Content -LiteralPath $log -Encoding UTF8 -Tail 40 -Wait
    }
}
```

No agregar `-Events`: estos modos no crean lectores pesados de eventos. El log conserva `SIMZ1_PROGRESS`, llegadas, transiciones, activos, esperas y errores según los registros nativos disponibles. Un monitor código0 acredita su consulta, no el éxito final de la simulación.

Después del cierre, seguir el [procedimiento completo del visor](../runtime/diagnostics/run10k-manual-20261105/viewer/PROCEDIMIENTO.md): comprobar manifiesto/eventos y Run ID exacto; recuperar análisis sólo si falta; preparar SQLite/replay de it.0; abrir servidor propio; seleccionar Transmetro/TuBus y comparar itinerario programado, observado y posición a05:00/07:00/12:00/17:00/20:00/23:00, hacia delante y atrás. Registrar desapariciones, superposiciones, poses ausentes y discontinuidades. No repetir QSim por fallo gráfico. Los seis bloques de ese procedimiento están comprobados por sintaxis, no ejecutados en esta entrega.

## Histórico: autorización anterior sustituida por Run10K manual

# Estado vigente: implementación autorizada, lanzamiento aún condicionado

2026-11-05 Guatemala. Se trabaja en la arquitectura L12 y el contrato aleatorio v4 bajo la nueva autorización del usuario. Todavía no hay selección real, Validate de esta revisión, trial nuevo, DryRun ni Run. El cierre anterior y sus comandos quedan históricos; no ejecutar sus bloques como lanzamiento vigente. Estado/evidencias y siguiente fase en [SIMZ1_180000_AVANCE.md](SIMZ1_180000_AVANCE.md).

La futura masiva deberá usar la selección única persistida, el mismo recibo en DryRun/Run, gate oficial y PowerShell externa visible. El principal registrará el comando y las identidades reales después de aprobar los tres L12, regresiones, Validate, inspector/record-trial y require-trial. Las guardas originales permanecen.

## Histórico: encabezado previo preservado

# Estado vigente: LANZAMIENTO BLOQUEADO — NO SE INICIÓ MATSim

2026-11-05 Guatemala. La nueva autorización condicionada no pudo ejecutarse: los tres contextos L12 siguen sin resolución certificada. [Evidencias](../runtime/diagnostics/l12-final-20261105/RESULTADOS.md) y [estado completo](SIMZ1_180000_AVANCE.md). No se sorteó N, no se publicó trial y no se ejecutaron Validate integrado, DryRun ni Run nuevos. No hay consola nocturna ni LaunchId nuevo.

Se conserva la preparación `final-20261105-random-24h-v4.json/random-full-1`, con contrato de entropía independiente de la semilla de demanda, selección inmutable y gate de DryRun explícito. Está probada en fixtures, **pendiente de validación integrada y compatibilidad oficial**. La huella actual `2c21b0e1944e3f2855dc6dc8ebbe8909a7cfe98606727123c3b82d8bcd636ca5` (709 dependencias) no está validada; no reutilizar recibos de f4cf. El contrato v3 y las fuentes físicas originales permanecen intactos.

Antes de cualquier fase de lanzamiento futura deben cerrarse los tres L12, revisar las transiciones exactas de fuentes, renovar validación y obtener la aceptación oficial de Run1000. Los bloques inferiores son históricos, no instrucciones de ejecución vigentes. No se proporciona una orden Run habilitada para esta revisión.

Consulta de solo lectura, sin eventos ni QSim:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
Get-Content -LiteralPath '.\runtime\diagnostics\l12-final-20261105\RESULTADOS.md' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\final-launch-20261105\native-preservation.json' -Encoding UTF8
```

## Histórico: estado y comandos anteriores conservados

# Estado vigente: Run1000 nativamente válida; full-1 bloqueada

**REQUIERE REVISIÓN.** La Run1000 conserva completed/valid y screening_pass. Se corrigieron la cobertura FIFO, la repetición de preparación espacial y un solape visual independiente; siguen abiertas las tres omisiones corporales L12 a12:00/17:00. No se publica el recibo de ensayo ni se entrega una orden ejecutable de Run de full-1. Los bloques de lanzamiento que permanecen más abajo son históricos y no deben ejecutarse como instrucciones vigentes.

Revisión actual `f4cf50840216a1772b89f2a24536e5d5be7d9940c9e69660f6966066de2082df`,706 dependencias, compatible con la revisión nativa290af1. Validate0 `balanced-launch-629dafda90554187b901fd483a98bba7`; DryRun run1000=0 `22069874cc144e5fbf2e101a0010a621`; DryRun full-1=0 `675dd849c6dc438683f639ed04c5581b`. El DryRun de full-1 mantiene `run_launch_eligible=false` y `pending_not_approved`; código0 significa preparación válida, no autorización para Run. [Informe definitivo](../runtime/diagnostics/run1000-closure-20261104/RESULTADOS.md).

El contrato inalterado es `final-20261104-24h-v3.json/full-1`:204186 no públicos+269 buses, una iteración(it.0),24h, semilla20261023, servicio2026-10-23, balanced-gateway-v1, L18 revisada y compact-v3. El lanzador correcto sigue siendo `run_simz1_180k_balanced_gateway.ps1`; el nombre180k no determinaN cuando se usa el selector. No usar el lanzador genérico, defaultslegacy ni FirstScaleTrial.

## Comprobación de revisión

Bloque independiente; no inicia simulación. La última comprobación rechazará el ensayo pendiente y conserva esa protección.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$simz1Spec = (Resolve-Path -LiteralPath '.\scenarios\zona1\experiments\final-20261104-24h-v3.json').Path
$simz1Base = (Get-Content -LiteralPath $simz1Spec -Raw -Encoding UTF8 | ConvertFrom-Json).base_inputs
& $simz1Python -B '.\python\simz1_workflow_state.py' require-balanced-validation
$validateGateExit = $LASTEXITCODE
if ($validateGateExit -ne 0) { throw 'Validate no acredita las fuentes actuales.' }
& $simz1Python -B '.\python\simz1_workflow_state.py' require-trial --state '.\runtime\workflow\trial-balanced-gateway-v1.json' --experiment-spec $simz1Spec --experiment-scenario full-1 --od-mode balanced-gateway-v1 --zone-boundary $simz1Base.zone_boundary --od-access-catalog $simz1Base.od_access_catalog --od-mix-file $simz1Base.od_mix_file
$trialGateExit = $LASTEXITCODE
if ($trialGateExit -ne 0) { throw 'Ensayo aún no aprobado: full-1 sigue bloqueada.' }
```

## DryRun run1000

Comprobación independiente; no repetir la corrida. Reutiliza las variables del bloque anterior y no encadena Run.

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\run_simz1_180k_balanced_gateway.ps1' -DryRun -ExperimentSpec $simz1Spec -ExperimentScenario run1000 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$dryTrialExit = $LASTEXITCODE
if ($dryTrialExit -ne 0) { throw 'DryRun run1000 rechazado; conservar el LaunchId.' }
```

## DryRun full-1

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\run_simz1_180k_balanced_gateway.ps1' -DryRun -ExperimentSpec $simz1Spec -ExperimentScenario full-1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$dryFullExit = $LASTEXITCODE
if ($dryFullExit -ne 0) { throw 'DryRun full-1 rechazado; conservar el LaunchId.' }
```

Run permanece retenido hasta cerrar el replay y pasar los mecanismos oficiales. No hay una instrucción de Run vigente en este encabezado.

## Resultados y reapertura de la Run1000 existente

Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, it.0. Consulta sin QSim:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run1000-closure-20261104\RESULTADOS.md' -Encoding UTF8
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\watch_simz1_110k.ps1' -LaunchId 9d73afe94f0b438d934e6c7870a24b82 -Evidence -Iteration 0
$evidenceExit = $LASTEXITCODE
if ($evidenceExit -ne 0) { throw 'No se pudo conciliar la evidencia de Run1000.' }
```

Comprobar la reapertura, sin abrir navegador ni iniciar QSim:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\runtime\diagnostics\run1000-acceptance-20261104-2c0e2340\reabrir-resultados.ps1' -CheckOnly
$checkReplayExit = $LASTEXITCODE
if ($checkReplayExit -ne 0) { throw 'Replay rechazado; conservar su log.' }
```

Abrir resultados y visor, acción separada:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\runtime\diagnostics\run1000-acceptance-20261104-2c0e2340\reabrir-resultados.ps1'
$openReplayExit = $LASTEXITCODE
if ($openReplayExit -ne 0) { throw 'No se pudo abrir el replay verificado.' }
```

URL comprobada: http://127.0.0.1:59203/index.html?run_id=simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af&iteration=0&run_manifest_sha256=750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596&source_version=70e464d009b85480aef9483507852e9c42edc4785dbbfa0c371b2abbffad7e0c

Servicio final comprobado en HTTP con fuentes f4cf: launcher28920→servidor44120→worker38240, recibo `runtime/replay/launch-dace6d0b7c474176b7e2c62e594dea78.jsonl`. Primera apertura sin preparación:115.24 s; reinicio verificado:13.42 s hasta HTTP. Inspección de navegador real no disponible. La identidad nativa de un servidor no acredita por sí sola su versión de código; tras un cambio futuro, comprobar el build cargado antes de reutilizarlo. `--replace-simz1` no fuerza reinicio si el servidor tiene la misma identidad. No detener procesos ajenos ni usar latest-successful.

Gráficas existentes: `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82/entregables/run-bg1-9d73afe94f0b438d934e6c7870a24b82/graficas`; análisis `analysis/it.0` y `analysis/prompt13/it.0` dentro de esa corrida. No se repitió AnalysisOnly/PackageOnly porque sus entregas permanecen íntegras. El lanzador versionado conserva análisis, gráficas y empaquetado posteriores para un futuro Run autorizado; el visor se abre separadamente con RunDir e iteración explícitos.

## Monitoreo para una futura corrida autorizada

No hay ninguna full-1 ejecutándose por esta tarea. Solo después de una aprobación futura, usar el LaunchId impreso por ese Run —nunca el de un DryRun ni el más reciente—:

```powershell
$simz1LaunchId = 'REEMPLAZAR_POR_EL_LAUNCHID_EXPLICITO_DEL_RUN_FUTURO'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\watch_simz1_110k.ps1' -LaunchId $simz1LaunchId -Watch -Iteration 0
$watchExit = $LASTEXITCODE
if ($watchExit -ne 0) { throw 'Observación rechazada; conservar evidencia.' }
```

Para seguir descarga sin abrir eventos, obtener el directorio de ese mismo state.json y leer el log:

```powershell
$simz1State = Get-Content -LiteralPath (Join-Path '.\runtime\launches' ($simz1LaunchId + '\state.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
$simz1Run = $simz1State.run_directory
Get-Content -LiteralPath (Join-Path $simz1Run 'matsim-run.log') -Tail 120 -Wait -Encoding UTF8 |
    Select-String 'SIMZ1_PROGRESS|SIMZ1_TRANSIT_COUNTERS|SIMZ1_WATCHDOG|SIMZ1_CAUSE'
```

Reloj/CPU no prueban descarga. Revisar llegadas, transiciones, stock activo, incorporación y edad máxima. WAIT cuenta intentos. Si hace falta el censo privado/carga, iniciar una sola vez `watch_simz1_110k.ps1 -Events -LaunchId $simz1LaunchId -Iteration 0`: su lease impide lectores incompatibles y muestra cobertura/atraso. No reiniciar repetidamente el lector ni duplicarlo con un auditor.

No existe una alarma automática de descarga persistente en este monitor. Criterio operativo de revisión humana: comparar tres ventanas completas consecutivas de5min simulados; investigar si no aumentan completados privados/carga con demanda activa o vencida, contrastando transiciones y esperas. Intervalos parciales, lector atrasado, demanda futura y cambio de servicio exigen registrar incertidumbre. Un intervalo sin llegadas no autoriza parada; la persistencia tampoco autoriza retirar cuerpos, liberar reservas o inventar llegadas. Las llegadas de buses no sustituyen descarga privada. Mantener abierta la consola propietaria y Windows activo; los logs no son checkpoints de QSim.

## Histórico: los encabezados y comandos siguientes no son instrucciones vigentes

# Run1000 v3 ya ejecutada: reabrir resultados sin QSim

Estado activo 2026-11-04 Guatemala. MATSim completed/valid, screening_pass y resultados recuperados sin repetir simulacion. Aceptacion completa **REQUIERE REVISION** por limites comprobados del visor, cobertura FIFO y rendimiento del servicio publico. No ejecutar de nuevo los comandos historicos de Run que siguen mas abajo; full-1 no esta autorizado ni tiene aprobacion oficial del ensayo.

Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`, it.0. Los manifiestos y recibos distinguen la huella de QSim290af1... de la revision de posprocesado c13e4f...; no se editan resultados nativos para hacerlos coincidir. Validate final y ambos DryRun terminaron0 sobrec13; un DryRun no es una nueva corrida ni una aprobacion de escala.

Reapertura explicita de las graficas y del mismo visor en Edge (no QSim, no generacion, no latest-successful):

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\runtime\diagnostics\run1000-acceptance-20261104-2c0e2340\reabrir-resultados.ps1'
$openExit = $LASTEXITCODE
if ($openExit -ne 0) { throw "Reapertura rechazada: $openExit. Revisar los logs conservados." }
```

El script verifica manifiesto, iteracion, procedencia SQLite y huellas antes de abrir; usa el lanzador oficial, conserva errores y no reemplaza servicios ajenos. Su sintaxis paso; la apertura de Edge no pudo comprobarse por falta del host de navegador. El arranque puede tardar unos minutos. Para solo comprobar sin abrir, agregar `-CheckOnly` al script. Si falta el replay, se detiene; no ejecuta MATSim ni lo regenera silenciosamente.

URL real comprobada por HTTP y conservada (servidor propio dejado activo):

http://127.0.0.1:59203/index.html?run_id=simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af&iteration=0&run_manifest_sha256=750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596&source_version=70e464d009b85480aef9483507852e9c42edc4785dbbfa0c371b2abbffad7e0c

Graficas empaquetadas: `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82/entregables/run-bg1-9d73afe94f0b438d934e6c7870a24b82/graficas`. Complementos: `analysis/it.0` y `analysis/prompt13/it.0` de la misma corrida. No repetir AnalysisOnly ni PackageOnly sin una causa nueva: ambas entregas estan integras y los complementos no forman parte del contrato actual de empaquetado.

Informe completo y limites: [RESULTADOS](../runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/RESULTADOS.md). Tres omisiones por limite de contexto corporal, posiciones no reconstruibles, solapes graficos, inspeccion visual pendiente; no aprobar full-1 a partir del screening privado ni subir guardas para ocultarlo. La causa global del atasco de la masiva anterior sigue abierta. Una Run1000 no acredita capacidad de204186.

## Historico: estado anterior, no instrucciones vigentes de lanzamiento

# SimZ1: Run1000 ya ejecutada; recuperar resultados sin repetir QSim

Estado activo 2026-11-04 Guatemala. El usuario autorizo una Run1000 v3 y se ejecuto una sola: LaunchId `9d73afe94f0b438d934e6c7870a24b82`, Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. El cierre nativo fue natural0 a24h; el lector del paso temporal fallo despues y sus resultados se conservan. La reparacion del posvalidador paso Validate y ambos DryRun; su auditoria integral esta en curso. Aun no se afirma completed/valid, screening ni replay listo.

No volver a ejecutar los bloques historicos de lanzamiento que siguen abajo. El mecanismo vigente de recuperacion es `python/revalidar_simz1.py --run-dir <esta carpeta> --apply`, ya en ejecucion por el principal; no iniciar otro lector. Al concluir PASS se utilizara `scripts/run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir <esta carpeta> -ExpectedRunId <este ID>` y el replay expreso de iteracion0. Los comandos definitivos de reapertura se publicaran con identidad y URL verificadas despues del cierre.

Evidencia activa: `runtime/diagnostics/run1000-acceptance-20261104-2c0e2340`. Avance y limites en [SIMZ1_180000_AVANCE.md](SIMZ1_180000_AVANCE.md). full-1 no se ejecuto ni esta autorizado; su DryRun nuevo conserva la guarda de ensayo pendiente. No usar FirstScaleTrial ni regenerar demanda para corregir un fallo de presentacion.

## Historico: preparacion manual anterior a la Run1000 ya ejecutada
# SimZ1: Run1000 v3 validada para ejecución manual

Estado 2026-11-05T00:10:33.919530+00:00: **LISTO PARA RUN1000**, en el repositorio principal `C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala`. Validate0 `balanced-launch-d40629c5651f47879a9fd2a5cf63822b`, DryRun run1000=0 `51866fe06196430984d0781896da1f5c`, DryRun full-1=0 `2c43ccf1add644f7a5318e0dfd870ad7`. Huella `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`. La JVM nocturna terminó por interrupción autorizada; su evidencia failed/invalid se conserva. No se inició Run1000 ni full-1.

`full-1` permanece pendiente de aceptación real del ensayo y de revisión del diagnóstico global. Este runbook no propone iniciar la masiva ahora ni la encadena a ningún paso. Las guardas de recursos, propietarios y huellas se vuelven a ejecutar en el lanzamiento. No usar el pipeline genérico ni `-FirstScaleTrial`.

Informe y limitaciones: [RESULTADOS.md](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/completion/RESULTADOS.md). El bloqueo local está documentado; no se declara reparada la descarga global. Las gráficas y el visor se abrirán solo para la identidad que el ensayo realmente produzca y acepte.

## Contrato vigente


`final-20261104-24h-v3.json` es sucesor explícito de `final-20261103-24h-v2.json`: conserva el sorteo y los seis selectores históricos y agrega `run1000`. El v2 permanece intacto. No usar `-FirstScaleTrial`: la revisión nueva requiere aprobación real de su ensayo equivalente.

| Parámetro | run1000 | full-1 |
|---|---:|---:|
| No públicos | 1000 | 204186 |
| Carros / motos / camiones | 440 / 550 / 10 | 89842 / 112302 / 2042 |
| Transmetro / TuBus adicionales | 176 / 93 | 176 / 93 |
| Iteraciones | 1, it.0 | 1, it.0 |
| Semilla | 20261023 | 20261023 |
| Fecha de servicio | 2026-10-23 | 2026-10-23 |
| OD | balanced-gateway-v1 | balanced-gateway-v1 |
| Último paso físico / endTime | 86400 / 86399 | 86400 / 86399 |

Pesos OD privados: EXTERNAL_EXTERNAL_THROUGH 50%, EXTERNAL_INTERNAL 20%, INTERNAL_EXTERNAL 20%, INTERNAL_INTERNAL 10%. Son tipos de viaje. N cambia las cuotas enteras, no las reglas. Misma configuración `access-review-v2/config-l18-local-v1.xml`, catálogo `agent-types-balanced-v1.json`, servicio `service-fleet-176-93-v1.json`, carga revisada `access-review-v2/freight/service-composition-v3.json`, red, restricciones OSM, señales, prioridades, FIFO y reservas corporales. Geometría aproximada y coordinación sintética: no se presenta como GIS ni calibración verificada.

Demanda `[0,86400)`, paso de 1 s y `onlyUseEndtime`; MATSim 15 ejecuta el último paso físico en 86400 con `endTime=86399`. Censo anterior al cleanup obligatorio. Pendientes, entradas tardías y abortos administrativos se distinguen. El indicador de carga conserva cierre +3600 s; no se amplía automáticamente ni retira vehículos por timeout.



## Recibos y recursos preparados

Ambos DryRun terminaron sin carpeta de simulación, población escrita ni QSim. El de full-1 conserva `run_launch_eligible=false`. Piso de disco 100 GiB, SQLite8, scratch4, replay2, margen20 y reserva pagefile3; heap QSim12, Maven2, nativo2 y OS4 GiB. Son presupuestos medidos/calculados en los recibos, no consumo máximo garantizado. No volver a ejecutar Validate sin causa ni cambiar la revisión después para eludir su recibo.

## Bloque 1: futura Run1000 manual

Validate y ambos DryRun de esta revisión terminaron con código 0. Estos comandos todavía NO se ejecutaron. Mantener abierta la consola propietaria y ejecutar cada bloque manualmente.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$spec = (Resolve-Path -LiteralPath '.\scenarios\zona1\experiments\final-20261104-24h-v3.json').Path
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$fingerprint = & $python -B .\python\simz1_workflow_state.py fingerprint
$fingerprintExit = $LASTEXITCODE
if ($fingerprintExit -ne 0 -or ($fingerprint -join '').Trim() -cne '290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1') { throw 'La revisión difiere de la validada.' }
$dry = Get-Content -LiteralPath '.\runtime\launches\51866fe06196430984d0781896da1f5c\state.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if ($dry.status -ne 'dry_run_pass' -or $dry.exit_code -ne 0 -or $dry.source_fingerprint -cne ($fingerprint -join '').Trim()) { throw 'DryRun de Run1000 incompatible.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Run1000 -ExperimentSpec $spec -JavaHome 'C:\Program Files\Java\jdk-17'
$runExit = $LASTEXITCODE
if ($runExit -ne 0) { throw "Run1000 no aprobada; codigo $runExit. Conservar el LaunchId mostrado." }
```

Esta orden selecciona 1000 vehiculos no publicos, 269 buses adicionales, una iteracion, semilla 20261023, servicio 2026-10-23, OD balanced-gateway-v1 y la base fisica v3. No utiliza el modo network del lanzador generico.

## Bloque 2: seleccionar exclusivamente el recibo aprobado y comprobar replay

En la misma consola, despues del codigo 0. `require-trial` reabre la corrida exacta, exige screening, integridad, huellas y escenario base; `path` por si solo solo comprueba que la carpeta exista y no sirve como aprobacion. Aqui se contrasta contra `full-1` para acreditar la misma base de la futura masiva.

```powershell
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$trialState = '.\runtime\workflow\trial-balanced-gateway-v1.json'
$base = (Get-Content -LiteralPath $spec -Raw -Encoding UTF8 | ConvertFrom-Json).base_inputs
& $python -B .\python\simz1_workflow_state.py require-trial --state $trialState --experiment-spec $spec --experiment-scenario full-1 --od-mode balanced-gateway-v1 --zone-boundary $base.zone_boundary --od-access-catalog $base.od_access_catalog --od-mix-file $base.od_mix_file
$trialExit = $LASTEXITCODE
if ($trialExit -ne 0) { throw 'El recibo no aprueba esta revision/base experimental.' }
$trial = Get-Content -LiteralPath $trialState -Raw -Encoding UTF8 | ConvertFrom-Json
$run = (Resolve-Path -LiteralPath $trial.run_directory).Path
if ($trial.iteration -ne 0) { throw 'Iteracion inesperada en el ensayo.' }
$nativeHash = (Get-FileHash -LiteralPath (Join-Path $run 'run-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($nativeHash -cne $trial.manifest_sha256) { throw 'El manifiesto cambio respecto del recibo.' }
$rawCheck = & $python -B .\scripts\replay\start_replay.py --run-dir $run --iteration 0 --check-only
$checkExit = $LASTEXITCODE
if ($checkExit -ne 0) { throw 'Replay completo compatible ausente; revisar el posproceso de ese LaunchId.' }
$checked = ($rawCheck -join [Environment]::NewLine) | ConvertFrom-Json
if ($checked.status -ne 'checked' -or $checked.run_id -cne $trial.run_id -or $checked.iteration -ne 0 -or $checked.run_manifest_sha256 -cne $nativeHash) { throw 'Identidad inesperada del replay.' }
$checked | Select-Object run_directory, run_id, iteration, run_manifest_sha256, source_manifest_sha256, replay_manifest_sha256, database_sha256, replay_directory, receipt
```

`--check-only` valida un replay ya existente y escribe su recibo de comprobacion; no inicia HTTP, navegador ni QSim. Si hay varios exports compatibles exige `--replay-dir`; seleccionar uno por su manifiesto explicito, no por fecha. Los presupuestos canonicos de preparacion son SQLite 8 GiB y scratch 4 GiB, con sus guardas reales; abrirlo no autoriza reducirlos ni regenerar fuentes parciales. `prepare_replay.py --run-dir $run --iteration 0 --sqlite-budget-gib 8 --scratch-budget-gib 4` es recuperacion de posproceso solo si se diagnostico necesaria, no un paso que deba repetirse automaticamente despues de este Run aceptado.

## Bloque 3: abrir dos graficas verificadas en Edge

Los nombres provienen de `REQUIRED_IMAGES` del empaquetador y la carpeta del paquete se deriva del run seleccionado. Puede usarse la carpeta `graficas` impresa para consultar las restantes. Edge no debe confundirse con el navegador predeterminado de Python.

```powershell
$edge = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $edge) { throw 'No se encontro Edge en sus rutas instaladas habituales.' }
$package = Join-Path (Join-Path $run 'entregables') (Split-Path $run -Leaf)
$report = Get-Content -LiteralPath (Join-Path $package 'docs\reporte-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($report.run_id -cne $trial.run_id -or $report.iteration -ne 0 -or $report.run_manifest_sha256 -cne $nativeHash) { throw 'Paquete grafico de otra identidad.' }
foreach ($name in @('completitud_por_hora.png', 'comparacion_familias_por_hora.png')) {
    $entry = @($report.files | Where-Object { $_.path -ceq ('graficas/' + $name) })
    if ($entry.Count -ne 1) { throw "Grafica ausente o ambigua: $name" }
    $graph = Join-Path $package $entry[0].path
    if ((Get-FileHash -LiteralPath $graph -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[0].sha256) { throw "Huella grafica distinta: $name" }
    Start-Process -FilePath $edge -ArgumentList @('--new-tab', ('"' + ([Uri]$graph).AbsoluteUri + '"'))
}
Write-Host (Join-Path $package 'graficas')
```

## Bloques 4 y 5: servidor en primer plano y URL real en Edge

En la consola anterior iniciar el servidor con identidad explicita. No se usa `--replace-simz1`, por lo que un puerto ocupado por otra identidad produce rechazo; no termina servidores ajenos. El script acepta 1..65535, **no acepta puerto 0 ni elige un puerto dinamico automaticamente**. El 8792 es su valor predeterminado. La consola imprime `Registro: <ruta exacta>` y, cuando la API confirma identidad, la URL real. Ctrl+C cierra solamente el servidor que esta consola haya creado.

```powershell
& $python -B .\scripts\replay\start_replay.py --run-dir $run --iteration 0 --replay-dir $checked.replay_directory --port 8792 --no-browser
$serverExit = $LASTEXITCODE
if ($serverExit -ne 0) { throw "El servidor termino con codigo $serverExit; conservar su recibo." }
```

Mientras el servidor permanece activo, abrir **otra PowerShell** y ejecutar el bloque siguiente. La ruta solicitada es la linea `Registro:` de esa invocacion concreta; no escoger el archivo mas reciente. El recibo `--check-only` anterior contiene `checked`, no `ready`, y sera rechazado por este bloque.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$serverReceipt = Read-Host 'Pega la ruta exacta mostrada despues de Registro por el servidor activo'
$records = @(Get-Content -LiteralPath $serverReceipt -Encoding UTF8 | ForEach-Object { $_ | ConvertFrom-Json })
$selected = $records | Where-Object event -eq 'selected' | Select-Object -Last 1
$ready = $records | Where-Object { $_.event -in @('ready','reused') } | Select-Object -Last 1
$trial = Get-Content -LiteralPath '.\runtime\workflow\trial-balanced-gateway-v1.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $selected -or -not $ready -or -not $ready.url -or $selected.check_only -or $selected.run_id -cne $trial.run_id -or $selected.iteration -ne 0 -or $selected.run_manifest_sha256 -cne $trial.manifest_sha256) { throw 'El recibo no acredita el servidor de este ensayo.' }
if ($records.event -contains 'stopped' -or $records.event -contains 'failed' -or $records.event -contains 'readiness_failed') { throw 'El recibo registra cierre o fallo; no acredita un servidor activo.' }
$address = [Uri]$ready.url
if ($address.Scheme -ne 'http' -or $address.Host -ne '127.0.0.1') { throw 'URL local inesperada.' }
$live = Invoke-RestMethod -Uri ($address.GetLeftPart([UriPartial]::Authority) + '/api/config') -TimeoutSec 10
if ($live.continuous.run_id -cne $selected.run_id -or $live.continuous.iteration -ne 0 -or $live.continuous.run_manifest_sha256 -cne $selected.run_manifest_sha256 -or $live.replay_source.replay_manifest_sha256 -cne $selected.replay_manifest_sha256 -or $live.replay_source.database_sha256 -cne $selected.database_sha256) { throw 'El servidor actual cambió de identidad o huellas.' }
$edge = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $edge) { throw 'No se encontro Edge.' }
Start-Process -FilePath $edge -ArgumentList @('--new-window', ('"' + $ready.url + '"'))
```

`ready` se escribe despues de comprobar la identidad de `/api/config` y HUD; `reused` solo corresponde a un servidor cuya identidad coincida. La URL se toma del campo `url`, con sus parametros de corrida/iteracion/huellas. El recibo historico no es un sondeo permanente de disponibilidad: el servidor debe seguir activo en su consola. Ninguna URL hardcodeada acredita por si sola la corrida.

Campos exactos del recibo de ensayo: `run_directory`, `run_id`, `iteration`, `manifest_sha256`, `quality_sha256`, `source_fingerprint`, `base_scenario_identity`, `od_identity`, `status`. Campos del check/replay: `run_directory`, `replay_directory`, `run_id`, `iteration`, `run_manifest_sha256`, `source_manifest_sha256`, `replay_manifest_sha256`, `database_sha256`, `database_bytes`, `database_mtime_ns`, `receipt`. El registro `selected` del servidor incluye esos campos y `port`/`check_only`; `ready` o `reused` aporta `url`/`owns_server`.


## Recuperación y seguimiento sin repetir QSim

Con LaunchId real impreso por el Run, usar `scripts/watch_simz1_110k.ps1 -LaunchId $launchId -Watch -Iteration 0` en otra consola y capturar `$LASTEXITCODE` al terminar. Es seguimiento ligero; no añadir `-Events` ni crear lectores repetidos del gzip. Los estados `prepared`, `preflight` y `running` no equivalen a `completed/valid`.

Si el Run retorna distinto de cero, detener la secuencia de apertura y revisar ese LaunchId. Código3 conserva nativa válida con `review_required`, pero no crea aceptación del ensayo. Los mecanismos existentes `scripts/run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $run -ExpectedRunId $runId` y `-PackageOnly` recuperan solamente el posproceso correspondiente; no son razones para repetir QSim. Antes de usarlos, exigir identidad explícita y manifiesto completed/valid. Un resultado parcial solo admite diagnóstico provisional.

## Histórico conservado; no ejecutar los bloques siguientes como instrucciones vigentes

El contenido anterior se conserva literalmente por procedencia. Sus avisos de JVM activa, bloqueo pendiente, v2, FirstScaleTrial o max-test fueron superados; no autorizan ningún lanzamiento actual.

# SimZ1: reparación preparada en copia aislada; validación integrada pendiente

Estado al 2026-11-04T20:46:38.507429+00:00: **BLOQUEADO para Run1000**. La JVM original 40484 sigue identificada por creación, padre, ejecutable y comando. No se detuvo ni se inició Run1000/masiva. Correcciones y comandos completos en [runbook de la copia aislada](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/docs/RUNBOOK_MANUAL_24H.md) e [informe técnico](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/RESULTADOS.md). Las fuentes originales siguen intactas; este aviso no acredita Validate ni autoriza detener procesos.

## Histórico anterior; no copiar estos comandos para la revisión nueva

# SimZ1 — ejecución manual de un día

Esta revisión usa `scenarios/zona1/experiments/final-20261103-24h-v2.json` y `src/main/resources/simz1/day-observation-v1.json`. La demanda permanece en `[0,86400)` y el último paso físico permitido es `86400`, inclusive. MATSim 15 con `onlyUseEndtime` ejecuta el paso siguiente al parámetro `endTime`: por eso la política declara explícitamente `native_qsim_end_seconds=86399`, con paso de un segundo. El cleanup posterior es administrativo. Las preparaciones, recibos y resultados históricos de 30 h conservan su identidad y horizonte.

Los bloques siguientes son operaciones independientes. El usuario inicia Run manualmente; no hay encadenamiento automático de Validate o DryRun a Run. Un Validate/DryRun aprobado acredita sus comprobaciones, no el desempeño de 220000 vehículos. No se ejecutaron aquí las masivas descritas.

## Preparación de la consola propietaria

Abra **PowerShell por su cuenta fuera de VS Code/Codex**. Ejecute allí:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$jdk17 = 'C:\Program Files\Java\jdk-17'
$spec24 = 'scenarios\zona1\experiments\final-20261103-24h-v2.json'
```

Mantenga disponibles esta consola propietaria y el equipo durante ejecución y posproceso. El lanzador existente conserva el mutex, los escritores exclusivos, el build aislado y las guardas de recursos. Un cliente de observación puede cerrarse sin controlar al escritor. No se promete supervivencia al cierre de la consola propietaria, suspensión, reinicio o apagado de Windows; no se instalaron servicios ni tareas programadas.

## 1. Validate, sin Run

```powershell
& .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome $jdk17
$validateExit = $LASTEXITCODE
Write-Host "Validate exit=$validateExit"
if ($validateExit -ne 0) { throw 'Validate rechazado: conservar su evidencia y corregir antes de otra fase.' }
```

El lanzador imprime `VALIDATION EVIDENCE`. El recibo pertenece a la huella comprobada; cualquier cambio posterior de dependencias requiere el mecanismo normal de validación. No use `Run1000` para suplirlo.

## 2. DryRun real de max-test, sin QSim

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario max-test -JavaHome $jdk17 -MinFreeGiB 100
$dryRunExit = $LASTEXITCODE
Write-Host "DryRun exit=$dryRunExit"
if ($dryRunExit -ne 0) { throw 'DryRun rechazado: no iniciar Run.' }
```

`-FirstScaleTrial` registra la decisión explícita de ensayar sin Run1000 anterior; conserva Validate, huella, preflight y guardas. `MinFreeGiB=100` es un piso: `retention-and-space.json` puede exigir más por volumen/iteraciones, SQLite, scratch y reserva de memoria. Los recursos se miden otra vez en cada lanzamiento. No reduzca el piso, la retención o el presupuesto para forzar el inicio.

## 3. Run manual de 220000 × 1 — solo el usuario

Este bloque inicia la masiva. Ejecútelo únicamente como una acción manual separada, con Validate y DryRun vigentes y después de revisar sus evidencias.

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario max-test -JavaHome $jdk17 -MinFreeGiB 100
$runExit = $LASTEXITCODE
Write-Host "Run exit=$runExit"
```

La composición de max-test es 96800 carros, 121000 motos y 2200 camiones; los 269 buses son adicionales. Conserve los valores impresos `LAUNCH EVIDENCE`, `PLANNED NEW RUN` y `run_id`. No elija una carpeta por ser la más reciente ni por `latest-successful`.

## 4. Monitor ligero en otra consola

Copie **el LaunchId concreto del Run** en `$launchId`. El valor siguiente es un marcador que debe reemplazarse, no una selección automática.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$launchId = 'REEMPLAZAR_POR_EL_LAUNCHID_DE_32_HEX'
& .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Watch -Iteration 0
$monitorExit = $LASTEXITCODE
Write-Host "Monitor exit=$monitorExit"
```

`-Watch` concilia procesos y lee metadatos; no abre el gzip de eventos ni inicia otro lector pesado. `Ctrl+C` cierra solo este cliente. Una consulta sin bucle y la cola acotada de logs están disponibles mediante:

```powershell
& .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Evidence -Iteration 0
$evidenceExit = $LASTEXITCODE
Write-Host "Evidence exit=$evidenceExit"
```

`-Events` es una operación pesada explícita, exclusiva por corrida/iteración; no se inicia automáticamente desde `-Watch`. Puede leer un prefijo grande desde el principio. Reutilice observaciones existentes antes de solicitarla; no hace falta para el seguimiento normal. Su EOF es provisional mientras exista el escritor. Tras acreditar el fin del escritor, consume el prefijo disponible y informa cierre íntegro o truncamiento, sin reparar el archivo.

Las identidades distinguen launcher, pipeline, ejecutor, Maven y JVM; incluyen PID, creación UTC, ejecutable, comando, padre y asociación a LaunchId/run_id. La actividad de CPU, el último paso nativo, la fecha/tamaño de eventos y la cobertura del lector son evidencias distintas. Un heartbeat o CPU activa no prueban descarga.

## 5. Estado y códigos de la misma corrida

```powershell
$launch = Join-Path 'runtime\launches' $launchId
$launchState = Get-Content -LiteralPath (Join-Path $launch 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runDir = $launchState.run_directory
$native = Get-Content -LiteralPath (Join-Path $runDir 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedRunId = $native.run_id
$launchState | Select-Object launch_id,run_id,status,phase,outcome,exit_code,child_exit_code,native_status,native_validation,screening | Format-List
$native | Select-Object run_id,status,phase,returncode,returncode_origin,validation,time_horizon | Format-List
& .\.venv\Scripts\python.exe -B .\python\simz1_resource_monitor.py --observe-launch $launch
$observationExit = $LASTEXITCODE
Write-Host "Observation exit=$observationExit"
```

Si aún no existe manifiesto, consulte `-Evidence` y el estado del lanzamiento: preparado/preflight no significa QSim iniciado. El estado observado se mantiene separado del persistido:

| Observación | Interpretación |
|---|---|
| `writer_alive` | JVM nativa identificada; puede estar sin avance simulado. |
| `supervisor_alive` | Supervisor/ejecutor identificado; no acredita JVM ni circulación. |
| `postprocessing_alive` | JVM ausente y ejecución de validación/análisis identificada. |
| `orphaned/incomplete` | Árbol ausente, sin cierre persistido; no inventa código ni hora de muerte. |
| `unknown` | Acceso, enumeración o identidad insuficientes; no acredita muerte. |
| `terminal_persisted` | Hay estado terminal guardado y no hay escritor identificado. |

`exit_code=0` del lanzador corresponde a sus fases terminadas; `3` conserva ejecución nativa `completed/valid` con screening `review_required`; `1` indica bloqueo/fallo técnico del lanzador. `child_exit_code` conserva el código realmente recibido del pipeline. El `returncode` del manifiesto es el observado del hijo del ejecutor/Maven; no sustituye un código de salida de la JVM que no se haya observado. Un supervisor desaparecido deja códigos y hora de muerte desconocidos. No rellene esos campos manualmente.

Una corrida técnicamente íntegra de 24 h puede contener censurados y conservar `review_required`. Compruebe por separado cobertura completa del día, integridad física, viajes terminados, ventanas y screening. Un prefijo detenido en `59159` no es un día completo.

## 6. Análisis y replay sin repetir QSim

Solo para **la misma corrida** `completed/valid`, con `$runDir` y `$expectedRunId` explícitos obtenidos y revisados arriba:

```powershell
& .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runDir -ExpectedRunId $expectedRunId
$analysisExit = $LASTEXITCODE
Write-Host "Analysis exit=$analysisExit"
if ($analysisExit -notin @(0,3)) { throw 'Fallo de posproceso: conservar la corrida y reparar/repetir solo el análisis.' }
```

Si únicamente falta empaquetar resultados ya generados, use en su lugar `-PackageOnly` con los mismos `-RunDir` y `-ExpectedRunId`. Ninguno de estos modos inicia QSim. No relance la simulación por un fallo de informes, empaquetado o visor.

Preparación/verificación de replay de la iteración explícita:

```powershell
& .\.venv\Scripts\python.exe -B .\scripts\replay\prepare_replay.py --run-dir $runDir --iteration 0 --sqlite-budget-gib 8 --scratch-budget-gib 4
$prepareReplayExit = $LASTEXITCODE
Write-Host "Prepare replay exit=$prepareReplayExit"
if ($prepareReplayExit -ne 0) { throw 'Preparación de replay rechazada; no repetir QSim ni borrar SQLite/WAL/SHM.' }
```

```powershell
& .\.venv\Scripts\python.exe -B .\scripts\replay\start_replay.py --run-dir $runDir --iteration 0 --check-only
$checkReplayExit = $LASTEXITCODE
Write-Host "Replay check exit=$checkReplayExit"
if ($checkReplayExit -ne 0) { throw 'Replay incompatible o incompleto.' }
```

Para abrirlo manualmente, ejecute `start_replay.py --run-dir $runDir --iteration 0` sin `--check-only`, capture `$LASTEXITCODE` al retornar y mantenga abierta esa consola del visor. Si hay más de un export compatible, indique `--replay-dir` con el directorio explícito verificado. Para full-10, la última iteración es `9`; las otras se seleccionan expresamente. El visor debe conservar run_id/iteración/huellas y mostrar el horizonte del manifiesto, nunca transformar censurados en llegadas.

Los prefijos truncados requieren diagnóstico provisional separado; estos comandos oficiales los rechazan. El intento histórico `9da9ec50b78b45fe86550f81a558fa06` no debe promoverse ni reanudarse desde un log.

## Otros cinco escenarios manuales

Los selectores son los nombres reales del contrato. Todos conservan semilla de demanda `20261023`, fechas, flota, OD y variantes físicas aprobadas. `full-1` y `full-10` conservan N fijo `204186` y la misma población inicial; cambiar iteraciones no autoriza otro sorteo. La procedencia/hash de esa identidad debe comprobarse por el flujo normal, sin reutilizar recibos históricos de 30 h.

Antes de **cada** Run, ejecute un DryRun separado con el mismo selector y revise su presupuesto propio. Ejemplo para full-10, sin ejecución de QSim:

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario full-10 -JavaHome $jdk17 -MinFreeGiB 100
$scenarioDryExit = $LASTEXITCODE
Write-Host "full-10 DryRun exit=$scenarioDryExit"
if ($scenarioDryExit -ne 0) { throw 'Guardas del escenario rechazadas; no iniciar su Run.' }
```

Seleccione manualmente un único bloque de Run cuando corresponda; no pegue todos como una batería automática.

**buses-only: N=0 no públicos, 269 buses, una iteración.**

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario buses -JavaHome $jdk17 -MinFreeGiB 100
$scenarioRunExit = $LASTEXITCODE
Write-Host "buses Run exit=$scenarioRunExit"
```

**55000 no públicos, una iteración.**

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario quarter -JavaHome $jdk17 -MinFreeGiB 100
$scenarioRunExit = $LASTEXITCODE
Write-Host "quarter Run exit=$scenarioRunExit"
```

**110000 no públicos, una iteración.**

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario half -JavaHome $jdk17 -MinFreeGiB 100
$scenarioRunExit = $LASTEXITCODE
Write-Host "half Run exit=$scenarioRunExit"
```

**full-1: 204186 no públicos, una iteración.**

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario full-1 -JavaHome $jdk17 -MinFreeGiB 100
$scenarioRunExit = $LASTEXITCODE
Write-Host "full-1 Run exit=$scenarioRunExit"
```

**full-10: la misma población inicial, diez iteraciones.**

```powershell
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -ExperimentSpec $spec24 -ExperimentScenario full-10 -JavaHome $jdk17 -MinFreeGiB 100
$scenarioRunExit = $LASTEXITCODE
Write-Host "full-10 Run exit=$scenarioRunExit"
```

Diez iteraciones tienen presupuesto y retención propios; el PASS de un escenario de una iteración no los acredita. No modifique capacidades, cuerpos, señales, umbrales o retención para convertir rechazo técnico o screening en aprobación.
