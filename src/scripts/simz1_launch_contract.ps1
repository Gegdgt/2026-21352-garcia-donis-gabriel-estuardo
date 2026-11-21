# Pure launch contracts; dot sourcing never starts a process.
function Assert-SimZ1PipelineOwner {
    param([string]$Project, [bool]$DryRun, [string]$ExperimentSpec, [string]$ExperimentScenario,
          [string]$NewRunDir, [int]$MinAgents, [int]$MaxAgents, [int]$Seed, [int]$Iterations)
    if (-not $env:SIMZ1_LAUNCH_DIRECTORY -or $env:SIMZ1_LAUNCH_ID -notmatch '^[a-f0-9]{32}$' -or
        $env:SIMZ1_LAUNCH_PID -notmatch '^\d+$' -or -not $env:SIMZ1_LAUNCH_CREATED_UTC) {
        throw 'Use the versioned experiment launcher: missing identified launch owner; direct pipeline execution cannot bypass gates.'
    }
    $expected = [IO.Path]::GetFullPath((Join-Path $Project ('runtime\launches\'+$env:SIMZ1_LAUNCH_ID)))
    if ([IO.Path]::GetFullPath($env:SIMZ1_LAUNCH_DIRECTORY) -cne $expected) { throw 'Launch directory identity mismatch.' }
    $state = Get-Content -LiteralPath (Join-Path $expected 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $request = Get-Content -LiteralPath (Join-Path $expected 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedPhase = if ($DryRun) { 'configuration_preflight' } else { 'simulation_and_analysis' }
    if ($state.launch_id -cne $env:SIMZ1_LAUNCH_ID -or $state.process.pid -ne [int]$env:SIMZ1_LAUNCH_PID -or
        $state.process.created_utc -cne $env:SIMZ1_LAUNCH_CREATED_UTC -or
        $state.phase -cne $expectedPhase) { throw 'Launch owner/state is not authorized for this pipeline phase.' }
    if (-not $ExperimentSpec -or -not $NewRunDir -or $request.launch_id -cne $state.launch_id -or
        $request.experiment.scenario -cne $ExperimentScenario -or -not $request.experiment.base_scenario_identity -or
        $request.experiment.specification_sha256 -cne (Get-FileHash -LiteralPath $ExperimentSpec -Algorithm SHA256).Hash.ToLowerInvariant() -or
        [IO.Path]::GetFullPath($NewRunDir) -cne $state.run_directory -or $request.run_directory -cne $state.run_directory -or
        $MinAgents -ne $request.minimum_non_public_vehicles -or $MaxAgents -ne $request.maximum_non_public_vehicles -or
        $Seed -ne $request.demand_seed -or $Iterations -ne $request.iterations) {
        throw 'Pipeline request differs from its identified experiment/selector/population/directory.'
    }
    $owner = Get-CimInstance Win32_Process -Filter ('ProcessId='+$env:SIMZ1_LAUNCH_PID) -ErrorAction Stop
    if (-not $owner -or $owner.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ') -cne $state.process.created_utc -or
        $owner.ExecutablePath -cne $state.process.executable -or $owner.CommandLine -cne $state.process.command) {
        throw 'Launch owner is absent or PID was reused; no simulation starts.'
    }
    if ($state.phase -eq 'simulation_and_analysis' -and (-not $state.run_launch_eligible -or -not $state.source_fingerprint)) {
        throw 'Launch acceptance gates did not authorize Run.'
    }
}

function Add-SimZ1PathArguments {
    param([string[]]$Arguments, [Collections.IDictionary]$Paths)
    $result = [Collections.Generic.List[string]]::new()
    foreach ($argument in $Arguments) { $result.Add($argument) }
    foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile')) {
        if (-not $Paths[$key]) { throw "Missing -$key" }
        $result.Add('-' + $key)
        $result.Add([string]$Paths[$key])
    }
    Assert-SimZ1PathArguments -Arguments $result.ToArray() -Paths $Paths
    return $result.ToArray()
}

function Assert-SimZ1PathArguments {
    param([string[]]$Arguments, [Collections.IDictionary]$Paths)
    foreach ($key in $Paths.Keys) {
        $name = '-' + $key
        $positions = @(0..($Arguments.Count-1) | Where-Object { $Arguments[$_] -ceq $name })
        if ($positions.Count -ne 1 -or $positions[0]+1 -ge $Arguments.Count -or
            $Arguments[$positions[0]+1] -cne [string]$Paths[$key]) {
            throw "Invalid argv: $name and its exact value must be separate elements."
        }
    }
}

function Set-SimZ1LaunchOutcome {
    param([Collections.IDictionary]$State,
          [ValidateSet('PASSED','BLOCKED','FAILED','REVIEW_REQUIRED')][string]$Outcome)
    $State['outcome'] = $Outcome
    $State['exit_code'] = switch ($Outcome) { 'PASSED' { 0 }; 'REVIEW_REQUIRED' { 3 }; default { 1 } }
}

function Test-SimZ1FirstScaleTrial {
    param([Collections.IDictionary]$Options)
    if (-not $Options.FirstScaleTrial -and -not $Options.FirstScaleTrial110k) { return $false }
    if ($Options.ExperimentSchema -cin @('simz1-final-experiments-v3','simz1-final-experiments-v4','simz1-final-experiments-v5','simz1-final-experiments-v6','simz1-final-experiments-v7','simz1-final-experiments-v8')) {
        throw 'FirstScaleTrial is unavailable: the versioned run1000 must approve this base scenario before Run.'
    }
    $specified = $Options.ExperimentSpec -and $Options.ExperimentScenario
    if ($Options.OdMode -cne 'balanced-gateway-v1' -or (-not $specified -and $Options.MinAgents -notin @(110000,180000)) -or
        $Options.MaxAgents -ne $Options.MinAgents -or (-not $specified -and $Options.Iterations -ne 1) -or $Options.Seed -ne 20261023 -or
        ($Options.FirstScaleTrial110k -and $Options.MinAgents -ne 110000)) {
        throw '-FirstScaleTrial only applies to exact balanced 110000/180000, seed 20261023, iteration 0.'
    }
    return $true
}

function Get-SimZ1PipelineDisposition {
    param($Manifest, [int]$ExitCode)
    $valid = $Manifest -and $Manifest.status -ceq 'completed' -and $Manifest.validation.status -ceq 'valid'
    if (-not $valid) { throw "MATSim did not finish completed/valid (pipeline exit=$ExitCode)." }
    if ($ExitCode -notin @(0,3)) { throw "MATSim completed/valid; postprocessing failed (exit=$ExitCode). Preserve reports and retry analysis only." }
    return $(if ($ExitCode -eq 3) { 'review_required' } else { 'screening_pass' })
}
