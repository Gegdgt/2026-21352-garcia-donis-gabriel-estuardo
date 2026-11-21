# Observations only. Never generates demand, launches MATSim or changes status.
[CmdletBinding()]
param(
    [switch]$List,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$LaunchId,
    [switch]$Watch,
    [switch]$Events,
    [switch]$Reports,
    [switch]$Evidence,
    [ValidateRange(0,9)][int]$Iteration = 0
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launchRoot = Join-Path $project 'runtime\launches'
if ($List) {
    if (Test-Path -LiteralPath $launchRoot) {
        Get-ChildItem -LiteralPath $launchRoot -Directory | ForEach-Object {
            $requestPath = Join-Path $_.FullName 'request.json'
            $statePath = Join-Path $_.FullName 'state.json'
            if ((Test-Path -LiteralPath $requestPath) -and (Test-Path -LiteralPath $statePath)) {
                $request = Get-Content -LiteralPath $requestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($request.od_mode -eq 'balanced-gateway-v1') {
                    $entry = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
                    [pscustomobject]@{LaunchId=$entry.launch_id;Status=$entry.status;DryRun=$entry.dry_run;Run=$entry.run_directory}
                }
            }
        } | Format-List
    }
    return
}
if (-not $LaunchId) { throw 'Use -List y seleccione -LaunchId explicito. Nunca se elige latest automaticamente.' }
if (([int][bool]$Watch + [int][bool]$Events + [int][bool]$Reports + [int][bool]$Evidence) -gt 1) { throw 'Watch, Events, Reports y Evidence son excluyentes.' }
$launch = Join-Path $launchRoot $LaunchId
$request = Get-Content -LiteralPath (Join-Path $launch 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $project '.venv\Scripts\python.exe'
if ($request.od_mode -ne 'balanced-gateway-v1' -or $request.maximum_non_public_vehicles -ne $request.minimum_non_public_vehicles) { throw 'No es un lanzamiento balanced-gateway-v1 de N exacto.' }
if ($request.experiment) {
    $selectionArgs = @('-B', (Join-Path $project 'python\simz1_scale_contract.py'), '--spec',
        $request.experiment.specification_path, '--scenario', $request.experiment.scenario)
    if ($request.experiment.schema -cin @('simz1-final-experiments-v4','simz1-final-experiments-v5','simz1-final-experiments-v6','simz1-final-experiments-v7','simz1-final-experiments-v8')) {
        $selectionArgs += @('--launch-request', (Join-Path $launch 'request.json'))
    }
    $selected = & $python @selectionArgs
    $contractExit = $LASTEXITCODE
    if ($contractExit -ne 0) {throw 'Especificacion experimental invalida'}
    $selected = $selected | ConvertFrom-Json
    if ($selected.schema -cne $request.experiment.schema) { throw 'El schema del lanzamiento difiere de la especificacion verificada.' }
    if ($selected.total_non_public_vehicles -ne $request.minimum_non_public_vehicles -or $selected.iterations -ne $request.iterations -or $selected.specification_sha256 -ne $request.experiment.specification_sha256) {throw 'Identidad experimental distinta'}
} elseif ($request.minimum_non_public_vehicles -notin @(110000,180000)) {throw 'Escala historica no autorizada'}
if ($Iteration -ge $request.iterations) {throw 'Iteracion fuera de la seleccion explicita'}
do {
    $state = Get-Content -LiteralPath (Join-Path $launch 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $run = [IO.Path]::GetFullPath($state.run_directory)
    $expected = Join-Path $project ('scenarios\zona1\montecarlo\run-bg' + [string]($request.minimum_non_public_vehicles / 1000) + '-' + $LaunchId)
    if ($run -ine $expected) { throw 'La carpeta no coincide con la identidad del lanzamiento.' }
    $manifestPath = Join-Path $run 'run-manifest.json'
    $manifest = if (Test-Path -LiteralPath $manifestPath) { Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    if ($manifest -and $request.experiment.schema -cin @('simz1-final-experiments-v4','simz1-final-experiments-v5','simz1-final-experiments-v6','simz1-final-experiments-v7','simz1-final-experiments-v8')) {
        $null = & $python @selectionArgs --run-manifest $manifestPath
        $selectionManifestExit = $LASTEXITCODE
        if ($selectionManifestExit -ne 0) { throw 'El manifiesto no coincide con la seleccion experimental autorizada; observacion rechazada.' }
    }
    $state | ConvertTo-Json -Depth 6 | Write-Host
    if ($manifest) {
        [pscustomobject]@{run_id=$manifest.run_id;status=$manifest.status;phase=$manifest.phase;
            validation=$manifest.validation;first_causal_error=$manifest.first_causal_error;error=$manifest.error} | ConvertTo-Json -Depth 8 | Write-Host
    }
    $observation = & $python -B (Join-Path $project 'python\simz1_resource_monitor.py') --observe-launch $launch
    $observationExit=$LASTEXITCODE
    if ($observationExit -ne 0) { throw 'No se pudo conciliar; estado observado desconocido.' }
    $observation | Write-Host
    $observed = ($observation -join "`n") | ConvertFrom-Json
    if ($Evidence) {
        Write-Host "EVIDENCIAS: $launch"
        Get-ChildItem -LiteralPath $launch -File | Select-Object FullName,Length | Format-Table -AutoSize
        foreach ($log in @((Join-Path $run 'matsim-run.log'),(Join-Path $launch '06-simulation-and-analysis.log'),(Join-Path $launch '05-preflight.log'))) {
            if (Test-Path -LiteralPath $log) {
                Write-Host "ULTIMAS LINEAS: $log"
                Get-Content -LiteralPath $log -Tail 60 -Encoding UTF8 | Write-Host
            }
        }
        return
    }
    if ($Reports) {
        if (-not $manifest -or $manifest.status -ne 'completed' -or $manifest.validation.status -ne 'valid') {
            throw 'No existe completed/valid; use -Evidence. No se promueve el manifiesto.'
        }
        & $python -B (Join-Path $project 'python\simz1_balanced_launch_report.py') --run-dir $run --iteration $Iteration
        $reportExit = $LASTEXITCODE
        if ($reportExit -ne 0) { throw 'Fallo la comprobacion de eventos/OD/informes; no se acredita exito.' }
        Write-Host "NATIVO completed/valid | informes: $run\analysis\it.$Iteration\balanced-launch"
        Write-Host "Graficas existentes: $run\analysis | entregables: $run\entregables"
        if ($state.status -ne 'completed') {
            Write-Warning 'El lanzamiento completo no figura completed; revisar analisis/screening/estado sin repetir MATSim.'
        }
        return
    }
    if ($Events -and $manifest -and $manifest.spatial_demand.mode -eq 'balanced-gateway-v1') {
        & $python -B (Join-Path $project 'python\simz1_balanced_launch_report.py') --run-dir $run --watch --iteration $Iteration
        $watchExit = $LASTEXITCODE
        if ($watchExit -ne 0) { throw 'Monitoreo detenido; revisar evidencia (no se modifica MATSim).' }
        return
    }
    if ($observed.observed_status -eq 'orphaned/incomplete') { return }
    if ($state.status -in @('completed','failed','blocked','dry_run_pass','review_required','postprocessing_failed')) { return }
    if ($Watch) { Start-Sleep -Seconds 10 }
} while ($Watch)
