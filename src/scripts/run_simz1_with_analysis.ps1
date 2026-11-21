# Orquesta una corrida nueva y el analisis por perfiles; NO genera HTML masivo.
# -AnalysisOnly reintenta graficas exclusivamente de una corrida completed/valid.
# -PackageOnly recupera copias docs/graficas sin repetir analisis ni MATSim.
[CmdletBinding()]
param(
    [ValidateRange(0,250000)][int]$MinAgents = 180000,
    [ValidateRange(0,250000)][int]$MaxAgents = 220000,
    [int]$Seed = 0,
    [string]$SourceConfig = 'scenarios\zona1\config-simz1.xml',
    [string]$TransitService = 'scenarios\zona1\transit\weekday-v2\service-fleet-176-93-v1.json',
    [string]$ServiceDate = '2026-10-23',
    [string]$FreightService = 'scenarios\zona1\freight\weekday-v2\service-composition-v2.json',
    [string]$FreightServiceDate,
    [Nullable[int]]$FreightVehicles,
    [switch]$NoFreightTransport,
    [string]$TemporalPolicy,
    [Nullable[int]]$TemporalSeed,
    [switch]$NoPublicTransport,
    [switch]$AcceptTransitRouteAssumptions,
    [string]$AgentCatalog = 'scenarios\zona1\agent-types-nonpublic-v1.json',
    [ValidateSet('legacy-gaussian-v1','lane-length-destinations-v1')][string]$DestinationPolicy = 'legacy-gaussian-v1',
    [ValidateSet('uniform-nodes-v1','legacy-corridors','lane-length-access-v1')][string]$OriginPolicy = 'uniform-nodes-v1',
    [ValidateSet('network','balanced-gateway-v1')][string]$OdMode = 'network',
    [string]$ZoneBoundary,
    [string]$OdAccessCatalog,
    [string]$OdMixFile,
    [ValidateSet('strict-receiver-v1','matsim15-native')][string]$StoragePolicy = 'strict-receiver-v1',
    [switch]$LegacyPcuStorage,
    [ValidateSet('none','derive','derive-activity-v2')][string]$ShortLinkSignalCoordination = 'derive',
    [ValidateSet(1,4)][int]$QSimThreads = 1,
    [ValidateRange(0,1)][double]$MinCompletionRate = 0.90,
    [ValidateRange(1,50)][int]$Iterations = 1,
    [string]$RunDir,
    [string]$NewRunDir,
    [string]$ExperimentSpec,
    [string]$ExperimentScenario,
    [switch]$AnalysisOnly,
    [switch]$PackageOnly,
    [string]$ExpectedRunId,
    [switch]$DryRun,
    [ValidateRange(0,1000)][int]$MinFreeGiB = 10
)
$ErrorActionPreference = 'Stop'
if (-not $AnalysisOnly -and -not $PackageOnly -and (-not $ExperimentSpec -or -not $ExperimentScenario)) {
    throw 'Nueva corrida requiere -ExperimentSpec y -ExperimentScenario explicitos; use run_simz1_180k_balanced_gateway.ps1. Sin fallback network.'
}
if ($ExperimentSpec -and $OdMode -ne 'balanced-gateway-v1') { throw 'El experimento requiere balanced-gateway-v1 explicito.' }
. (Join-Path $PSScriptRoot 'simz1_launch_contract.ps1')
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $AnalysisOnly -and -not $PackageOnly) {
    Assert-SimZ1PipelineOwner -Project $project -DryRun ([bool]$DryRun) -ExperimentSpec $ExperimentSpec -ExperimentScenario $ExperimentScenario -NewRunDir $NewRunDir -MinAgents $MinAgents -MaxAgents $MaxAgents -Seed $Seed -Iterations $Iterations
}
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
if ($env:SIMZ1_LAUNCH_DIRECTORY) {
    & $python -B (Join-Path $project 'python\simz1_resource_monitor.py') --record-process $PID --launch-directory $env:SIMZ1_LAUNCH_DIRECTORY --launch-id $env:SIMZ1_LAUNCH_ID --role pipeline
    $identityExit=$LASTEXITCODE
    if ($identityExit -ne 0) { throw 'No se pudo persistir la identidad del ejecutor PowerShell.' }
}
$maven = Join-Path $project 'mvnw.cmd'
$config = if ([IO.Path]::IsPathRooted($SourceConfig)) { $SourceConfig } else { Join-Path $project $SourceConfig }
$launcher = Join-Path $project 'python\ejecutar_simz1.py'
$analyzer = Join-Path $project 'python\generar_graficas_z1.py'
$reportPackager = Join-Path $project 'python\simz1_report_package.py'
$preflight = Join-Path $project 'python\simz1_experiment_preflight.py'
$quality = Join-Path $project 'python\simz1_result_quality.py'
$configurationContract = Join-Path $project 'python\simz1_configuration_contract.py'
function Test-NativeConfiguration([string]$RunFolder) {
    # Historical runs keep their own horizon/contract and existing inspectors.
    if (-not $manifest.experiment.base_scenario_identity) { return }
    & $python -B $configurationContract verify-run --run-dir $RunFolder
    $configurationExit = $LASTEXITCODE
    if ($configurationExit -ne 0) { throw 'Native configuration/retention mismatch; preserve completed native evidence and repair closure before analysis.' }
}
if (-not $PSBoundParameters.ContainsKey('Seed')) { $Seed = Get-Random -Minimum 1 -Maximum 2147483647 }
function Test-ResultQuality([string]$RunFolder, [switch]$RequireSix, [switch]$ReturnCode) {
    $native = Get-Content -LiteralPath (Join-Path $RunFolder 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $rejected = $false
    foreach ($it in $native.iterations.completed) {
        $summary = Join-Path $RunFolder "analysis\it.$it\graficas_perfiles\resumen_perfiles.json"
        $qualityArgs = @('-B', $quality, '--summary', $summary, '--check', '--min-completion-rate', $MinCompletionRate.ToString([System.Globalization.CultureInfo]::InvariantCulture))
        if ($RequireSix) { $qualityArgs += '--require-six-profiles' }
        & $python @qualityArgs | Out-Host
        $qualityExit = $LASTEXITCODE
        if ($qualityExit -eq 3) { $rejected = $true }
        elseif ($qualityExit -ne 0) { throw 'Fallo al verificar calidad del analisis.' }
    }
    if ($ReturnCode) {
        if ($rejected) {
            Write-Warning "EMPAQUETADO COMPLETO | SCREENING review_required | MATSim y analisis conservados: $RunFolder"
            return 3
        }
        if ($native.demand_composition -and $native.demand_composition.total_non_public_vehicles -eq 0) {
            Write-Host 'EMPAQUETADO COMPLETO | SCREENING privado no aplicable: N=0'
        } else {
            Write-Host 'EMPAQUETADO COMPLETO | SCREENING screening_pass'
        }
        return 0
    }
    if ($rejected) {
        throw "MATSim y graficas CONSERVADOS; calidad requiere revision: $RunFolder. No interprete medias de llegados como toda la demanda ni repita una masiva sin diagnosticar."
    }
}
function Update-ExperimentalReports($RunFolder, $NativeManifest) {
    if ($NativeManifest.experiment) {
        foreach ($reportIteration in $NativeManifest.iterations.completed) {
            & $python -B (Join-Path $project 'python\simz1_balanced_launch_report.py') --run-dir $RunFolder --iteration $reportIteration
            $reportExit = $LASTEXITCODE
            if ($reportExit -ne 0) {throw "Balanced report failed for iteration $reportIteration; preserve native results and use AnalysisOnly"}
        }
    }
}
if ($AnalysisOnly -and $PackageOnly) { throw '-AnalysisOnly y -PackageOnly son excluyentes.' }
if ($ExpectedRunId -and -not ($AnalysisOnly -or $PackageOnly)) { throw '-ExpectedRunId requiere -AnalysisOnly o -PackageOnly.' }
$requiredFiles = if ($PackageOnly) { @($python, $reportPackager, $quality) } else { @($python, $maven, $config, $launcher, $analyzer, $reportPackager, $preflight, $quality) }
foreach ($required in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Falta archivo requerido: $required" }
}
if ($MinAgents -gt $MaxAgents) { throw '-MinAgents no puede superar -MaxAgents' }
if ($AnalysisOnly -or $PackageOnly) {
    if ($NewRunDir) { throw '-NewRunDir no se combina con -AnalysisOnly ni -PackageOnly.' }
    if (-not $RunDir) { throw '-AnalysisOnly/-PackageOnly requiere -RunDir con la carpeta existente de la corrida.' }
    $run = (Resolve-Path -LiteralPath $RunDir).Path
    $manifestPath = Join-Path $run 'run-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "No existe manifiesto: $manifestPath" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($ExpectedRunId -and $manifest.run_id -cne $ExpectedRunId) {
        throw "Identidad incompatible: esperado=$ExpectedRunId; observado=$($manifest.run_id); carpeta=$run"
    }
    if ($manifest.status -ne 'completed' -or $manifest.validation.status -ne 'valid') {
        throw "No se pueden generar estadisticas oficiales de una corrida no validada: $run (estado=$($manifest.status))"
    }
    if ($DryRun) {
        $operation = if ($PackageOnly) { 'solo empaquetado y screening' } else { 'analisis, empaquetado y screening' }
        Write-Host "DRY RUN: $operation | $run | run_id=$($manifest.run_id)"
        return
    }
    Test-NativeConfiguration $run
    if (-not $PackageOnly) {
        & $python -B $analyzer --run-dir $run --profiles-only --all-iterations
        if ($LASTEXITCODE -ne 0) { throw "analysis_failed: se conserva MATSim completed/valid; revisar $run\analysis" }
    }
    Update-ExperimentalReports $run $manifest
    $packageArgs = @('-u', '-B', $reportPackager, '--run-dir', $run, '--all-iterations')
    if ($ExpectedRunId) { $packageArgs += @('--expected-run-id', $ExpectedRunId) }
    & $python @packageArgs
    if ($LASTEXITCODE -ne 0) { throw "Empaquetado de docs/graficas fallido; MATSim y analysis siguen intactos: $run" }
    if ($PackageOnly) {
        $screeningCode = Test-ResultQuality -RunFolder $run -RequireSix:($manifest.counts.planned_persons -ge 6) -ReturnCode
        exit $screeningCode
    }
    Write-Host "GRAFICAS GENERADAS/REUTILIZADAS: $run\analysis" -ForegroundColor Green
    Write-Host "ENTREGABLE ORDENADO: $run\entregables" -ForegroundColor Cyan
    $screeningCode = Test-ResultQuality -RunFolder $run -RequireSix:($manifest.counts.planned_persons -ge 6) -ReturnCode
    exit $screeningCode
}
if ($RunDir) { throw 'Para una corrida nueva omite -RunDir. Con -AnalysisOnly o -PackageOnly, -RunDir selecciona una existente.' }
$catalog = (Resolve-Path -LiteralPath $AgentCatalog).Path
$preflightArgs = @('-B', $preflight, '--config', $config, '--agent-catalog', $catalog,
    '--min-agents', [string]$MinAgents, '--max-agents', [string]$MaxAgents,
    '--origin-policy', $OriginPolicy, '--destination-policy', $DestinationPolicy, '--storage-policy', $StoragePolicy)
$occupancyArgs = @('--qsim-threads', [string]$QSimThreads)
if ($LegacyPcuStorage) { $occupancyArgs += '--no-whole-vehicle-reservation' }
else { $occupancyArgs += '--whole-vehicle-reservation' }
$preflightArgs += $occupancyArgs
$odArgs = @('--od-mode', $OdMode)
if ($OdMode -eq 'balanced-gateway-v1') {
    if ($Seed -ne 20261023 -or (-not $ExperimentSpec -and $Iterations -ne 1) -or $MinAgents -ne $MaxAgents -or
        (-not $ExperimentSpec -and $MinAgents -notin @(1000,110000,180000)) -or $OriginPolicy -ne 'lane-length-access-v1' -or
        $ShortLinkSignalCoordination -ne 'none' -or $LegacyPcuStorage -or $TemporalPolicy -or
        $NoPublicTransport -or $NoFreightTransport) { throw 'Balanced OD: N=1000/110000/180000 exacto, seed=20261023, iteracion 0, origen revisado, semaforos preservados y servicios obligatorios.' }
    foreach ($odInput in @(@('-ZoneBoundary',$ZoneBoundary), @('-OdAccessCatalog',$OdAccessCatalog), @('-OdMixFile',$OdMixFile))) {
        if (-not $odInput[1] -or -not (Test-Path -LiteralPath $odInput[1] -PathType Leaf)) {
            throw "balanced-gateway-v1 BLOQUEADO: falta $($odInput[0]) = '$($odInput[1])'. Requiere insumo real verificado; sin bbox ni fallback network."
        }
    }
    $ZoneBoundary = (Resolve-Path -LiteralPath $ZoneBoundary).Path
    $OdAccessCatalog = (Resolve-Path -LiteralPath $OdAccessCatalog).Path
    $OdMixFile = (Resolve-Path -LiteralPath $OdMixFile).Path
    # Transfer a file path, not embedded JSON through Windows native quoting.
    $launcher = Join-Path $project 'python\simz1_balanced_execute.py'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "Falta $launcher" }
    $odArgs += @('--zone-boundary',$ZoneBoundary,'--od-access-catalog',$OdAccessCatalog,
        '--od-osm',(Join-Path (Split-Path -Parent $config) 'map.osm'),'--od-mix-file',$OdMixFile)
    $preflightArgs += @('--zone-boundary',$ZoneBoundary,'--od-access-catalog',$OdAccessCatalog,'--od-mix-file',$OdMixFile,'--seed',[string]$Seed)
} elseif ($ZoneBoundary -or $OdAccessCatalog -or $OdMixFile -or $OriginPolicy -eq 'lane-length-access-v1') {
    throw 'Las opciones de gateways requieren -OdMode balanced-gateway-v1; no se ignoran.'
}
$preflightArgs += @('--od-mode',$OdMode,'--iterations',[string]$Iterations)
if ($ExperimentSpec) {
    $ExperimentSpec=(Resolve-Path -LiteralPath $ExperimentSpec).Path
    $preflightArgs += @('--experiment-spec',$ExperimentSpec,'--experiment-scenario',$ExperimentScenario)
    $odArgs += @('--experiment-spec',$ExperimentSpec,'--experiment-scenario',$ExperimentScenario)
} elseif ($ExperimentScenario) {throw 'ExperimentScenario requires ExperimentSpec'}
$transitArgs = @()
$freightArgs = @('--no-freight-transport')
if (-not $NoFreightTransport) {
    $freightPath = (Resolve-Path -LiteralPath $FreightService).Path
    if (-not $FreightServiceDate) { $FreightServiceDate = $ServiceDate }
    $freightArgs = @('--freight-service', $freightPath, '--freight-service-date', $FreightServiceDate)
    if ($PSBoundParameters.ContainsKey('FreightVehicles')) { $freightArgs += @('--freight-vehicles', [string]$FreightVehicles) }
} elseif ($PSBoundParameters.ContainsKey('FreightVehicles') -or $FreightServiceDate -or $PSBoundParameters.ContainsKey('FreightService')) {
    throw '-NoFreightTransport no se combina con opciones del servicio de carga.'
}
$preflightArgs += $freightArgs
$temporalArgs = @()
if ($TemporalPolicy) {
    $temporalPath = (Resolve-Path -LiteralPath $TemporalPolicy).Path
    $temporalArgs = @('--temporal-policy', $temporalPath)
    if ($PSBoundParameters.ContainsKey('TemporalSeed')) { $temporalArgs += @('--temporal-seed', [string]$TemporalSeed) }
    if (-not $PSBoundParameters.ContainsKey('ServiceDate')) {
        $temporalSettings = Get-Content -LiteralPath $temporalPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $ServiceDate = $temporalSettings.study_date
    }
    $preflightArgs += $temporalArgs
} elseif ($PSBoundParameters.ContainsKey('TemporalSeed')) { throw '-TemporalSeed requiere -TemporalPolicy.' }
if (-not $NoPublicTransport) {
    $transitPath = (Resolve-Path -LiteralPath $TransitService).Path
    $transitArgs = @('--transit-service', $transitPath, '--transit-service-date', $ServiceDate)
    if ($AcceptTransitRouteAssumptions) { $transitArgs += '--accept-transit-route-assumptions' }
    $preflightArgs += $transitArgs
}
if ($OdMode -eq 'balanced-gateway-v1') {
    $pythonPaths = @{'-zone-boundary'=$ZoneBoundary;'-od-access-catalog'=$OdAccessCatalog;'-od-mix-file'=$OdMixFile}
    Assert-SimZ1PathArguments $preflightArgs $pythonPaths
}
& $python @preflightArgs
if ($LASTEXITCODE -ne 0) { throw 'Fallo preflight de perfiles; no se inicia MATSim.' }
$run = Join-Path $project ('scenarios\zona1\montecarlo\run-mc-verified-' + [guid]::NewGuid().ToString('N'))
if ($NewRunDir) {
    if ([System.IO.Path]::IsPathRooted($NewRunDir)) {
        $run = [System.IO.Path]::GetFullPath($NewRunDir)
    } else {
        $run = [System.IO.Path]::GetFullPath((Join-Path $project $NewRunDir))
    }
    $allowedParent = Join-Path $project 'scenarios\zona1\montecarlo'
    if ((Split-Path $run -Parent) -ne $allowedParent -or (Split-Path $run -Leaf) -notlike 'run-*') {
        throw '-NewRunDir debe ser un hijo run-* dentro de scenarios/zona1/montecarlo.'
    }
    if (Test-Path -LiteralPath $run) { throw "No se sobrescribe una corrida: $run" }
}
$drive = [System.IO.Path]::GetPathRoot($run)
$driveInfo = Get-PSDrive -Name $drive.Substring(0,1) -PSProvider FileSystem -ErrorAction Stop
$freeGiB = [math]::Round($driveInfo.Free / 1GB, 2)
Write-Host "NUEVA CORRIDA: $run" -ForegroundColor Cyan
Write-Host "N solicitadas: $MinAgents..$MaxAgents | seed: $Seed | iteraciones: $Iterations | libre: $freeGiB GiB"
if ($driveInfo.Free -lt ($MinFreeGiB * 1GB)) {
    throw "Espacio menor que $MinFreeGiB GiB. La comprobacion no garantiza capacidad suficiente; libera espacio o cambia el volumen del repositorio."
}
$arguments = @(
    '-B', $launcher, '--config', $config, '--maven', $maven,
    '--run-dir', $run, '--mode', 'montecarlo',
    '--agent-catalog', $catalog, '--origin-policy', $OriginPolicy, '--destination-policy', $DestinationPolicy, '--storage-policy', $StoragePolicy,
    '--min-agents', [string]$MinAgents, '--max-agents', [string]$MaxAgents,
    '--seed', [string]$Seed, '--matsim-seed', [string]$Seed,
    '--iterations', [string]$Iterations, '--qsim-threads', [string]$QSimThreads,
    '--trips-per-person', '1',
    '--signal-offset-policy', 'preserve',
    '--no-incidents'
)
$arguments += $odArgs
if ($OdMode -eq 'network') { $arguments += @('--corridor-policy','redistribute') }
$arguments += $transitArgs
$arguments += $freightArgs
$arguments += $temporalArgs
if ($LegacyPcuStorage) { $arguments += '--no-whole-vehicle-reservation' }
else {
    if ($QSimThreads -ne 1) { throw 'La reserva fisica por corredor requiere -QSimThreads 1.' }
    $arguments += '--whole-vehicle-reservation'
}
if ($LegacyPcuStorage -and -not $PSBoundParameters.ContainsKey('ShortLinkSignalCoordination')) {
    $ShortLinkSignalCoordination = 'none'
}
$arguments += @('--short-link-signal-coordination', $ShortLinkSignalCoordination)
if (-not $TemporalPolicy -and -not $ExperimentSpec) { $arguments += @('--drain-seconds','0') }
if ($MaxAgents -ge 150000) { $arguments += '--massive' }
$catalogSettings = Get-Content -LiteralPath $catalog -Raw -Encoding UTF8 | ConvertFrom-Json
if ($catalogSettings.non_public_demand) {
    Write-Warning "COMPOSICION: N incluye carros, motos y pesados segun el catalogo explicito $AgentCatalog; buses fijos adicionales. No agregar 12 camiones. Supuesto sintetico, no aforo. Admision=$StoragePolicy. Sin accidentes; FIFO sin filtrado."
} else {
    Write-Warning "CATALOGO LEGACY: N solo particulares; servicio publico y carga adicionales. Admision=$StoragePolicy. No se reinterpretan resultados historicos."
}

if ($DryRun) {
    if ($OdMode -eq 'balanced-gateway-v1') { Assert-SimZ1PathArguments $arguments $pythonPaths }
    Write-Host "DRY RUN (no se ejecuta MATSim): $python $($arguments -join ' ')"
    exit 0
}
if ($OdMode -eq 'balanced-gateway-v1') { Assert-SimZ1PathArguments $arguments $pythonPaths }
# Preparation may fail before the run directory or its manifest exists. Keep
# the complete child output independently of those artifacts, including stderr.
$childLogDirectory = Join-Path $project 'runtime\launches'
New-Item -ItemType Directory -Path $childLogDirectory -Force | Out-Null
$childLog = Join-Path $childLogDirectory ((Split-Path $run -Leaf) + '-preparation-' + [guid]::NewGuid().ToString('N') + '.log')
$childWriter = [IO.StreamWriter]::new($childLog, $false, [Text.UTF8Encoding]::new($false))
$previousPreference = $ErrorActionPreference
try {
    # Windows PowerShell wraps native stderr in ErrorRecord. Do not terminate
    # on that wrapper before recording the child's own exit code and traceback.
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    & $python @arguments 2>&1 | ForEach-Object {
        $line = $_.ToString()
        $childWriter.WriteLine($line); $childWriter.Flush()
        Write-Host $line
    }
    $exitCode = $global:LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousPreference
    $childWriter.Dispose()
}
$manifestPath = Join-Path $run 'run-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    $cause = (Get-Content -LiteralPath $childLog -Tail 30 -Encoding UTF8) -join [Environment]::NewLine
    Write-Error -Message "El proceso hijo termino antes del manifiesto (codigo=$exitCode). Log conservado: $childLog. Salida original:`n$cause" -ErrorAction Continue
    if ($null -ne $exitCode -and $exitCode -ne 0) { exit $exitCode }
    exit 1
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$valid = ($manifest.status -eq 'completed' -and $manifest.validation.status -eq 'valid')
if ($valid -and $exitCode -ne 0) {
    throw "La etapa de ejecucion/analisis termino con codigo $exitCode. MATSim completed/valid y la evidencia se conservan en $run. No se reintenta automaticamente."
}
if (-not $valid) {
    Write-Warning "MATSim no validado. Estado=$($manifest.status); fase=$($manifest.phase); causa=$($manifest.error)"
    $events = Join-Path $run 'output\output_events.xml.gz'
    if (-not (Test-Path -LiteralPath $events)) {
        Write-Warning 'Falta output_events.xml.gz. No se puede producir el analisis cientifico oficial; revisar output_config.xml y logs.'
        Get-ChildItem -LiteralPath (Join-Path $run 'output') -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like '*events*' } | Select-Object -First 15 -ExpandProperty FullName | Out-Host
    }
    throw "La simulacion no termino completed/valid. No se generan graficas oficiales. Diagnostico separado: python/simz1_diagnostic_plots.py --run-dir '$run' --expected-run-id '$($manifest.run_id)'. Log: $run\matsim-run.log"
}
if (-not $NoPublicTransport) {
    if ($manifest.public_transport.enabled -ne $true -or
        $manifest.public_transport.public_transport_vehicles_configured -le 0 -or
        $manifest.public_transport.road_demand_persons -ne $manifest.counts.planned_persons) {
        throw 'La corrida no incluye la flota publica separada solicitada. No se acepta fallback solo carros/motos.'
    }
    Write-Host "FLOTA PUBLICA CONFIGURADA (no activos simultaneos): $($manifest.public_transport.public_transport_vehicles_configured) | N vial: $($manifest.counts.planned_persons)" -ForegroundColor Cyan
}
Test-NativeConfiguration $run
Write-Host "MATSim completed/valid | particulares: $($manifest.counts.planned_persons) | run_id: $($manifest.run_id)" -ForegroundColor Green
if ($manifest.demand_composition) {
    Write-Host "N no publico: $($manifest.counts.non_public_vehicles_configured) | carga incluida: $($manifest.counts.freight_vehicles_configured) | buses adicionales: $($manifest.counts.public_transport_vehicles_configured)" -ForegroundColor Cyan
}
# El launcher ya intenta generar las graficas tras validar MATSim.
# Repetir el CLI es seguro: verifica hashes y reutiliza el entregable completo.
& $python -B $analyzer --run-dir $run --profiles-only --all-iterations
$analysisExit = $LASTEXITCODE
if ($analysisExit -ne 0) {
    throw "MATSim COMPLETED/VALID pero analysis_failed. No repitas MATSim; reintenta: .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir `"$run`""
}
Update-ExperimentalReports $run $manifest
& $python -u -B $reportPackager --run-dir $run --all-iterations
if ($LASTEXITCODE -ne 0) {
    throw "MATSim completed/valid y analysis completed, pero empaquetado fallido. Reintenta -PackageOnly -RunDir `"$run`" -ExpectedRunId `"$($manifest.run_id)`""
}
$reportDir = Join-Path (Join-Path $run 'entregables') (Split-Path $run -Leaf)
Write-Host "INTEGRIDAD VALIDADA | GRAFICAS GENERADAS: $run\analysis" -ForegroundColor Green
Write-Host "ENTREGABLE: $reportDir" -ForegroundColor Green
Write-Host "Para abrir graficas: explorer.exe `"$(Join-Path $reportDir 'graficas')`""

# Separate gate: files can be valid while the traffic experiment is inconclusive.
$screeningCode = Test-ResultQuality -RunFolder $run -RequireSix:($manifest.counts.planned_persons -ge 6) -ReturnCode
exit $screeningCode
