# Launch explicitly; never manufacture a new Validate/Run1000 approval.
# -DryRun performs the real read-only gates/preflight and records its request,
# but creates no simulation directory, private population, QSim or replay.
[CmdletBinding()]
param(
    [ValidateRange(0,220000)][int]$MinAgents = 180000,
    [ValidateRange(0,220000)][int]$MaxAgents = 220000,
    [ValidateRange(0,2147483647)][int]$Seed = 20261023,
    [string]$JavaHome,
    [string]$ExperimentSpec,
    [string]$ExperimentScenario,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$DryRunLaunchId,
    [ValidateSet('automatic_replay_v1','native_diagnostic_v1')][string]$PostprocessingPolicy,
    [ValidateSet('network','balanced-gateway-v1')][string]$OdMode='network',
    [string]$ZoneBoundary,
    [string]$OdAccessCatalog,
    [string]$OdMixFile,
    [string]$SourceConfig,
    [string]$FreightService,
    [switch]$FirstScaleTrial,
    [ValidateRange(1,1000)][int]$MinFreeGiB = 100,
    [ValidateRange(1,500)][int]$SQLiteBudgetGiB = 8,
    [ValidateRange(1,500)][int]$ScratchBudgetGiB = 4,
    [switch]$DryRun
)
$script:SimZ1MassiveScriptPath = $PSCommandPath
. (Join-Path $PSScriptRoot 'simz1_launch_contract.ps1')

function Write-SimZ1MassiveJson([string]$Path, $Value) {
    if (-not ('SimZ1MassiveAtomicFileV1' -as [type])) {
        Add-Type -TypeDefinition @'
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class SimZ1MassiveAtomicFileV1 {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileExW(string source, string destination, uint flags);
    public static void Publish(string source, string destination) {
        // Same-directory rename; replace existing + write through. No delete,
        // retry or copy fallback can expose a partially published state.
        if (!MoveFileExW(source, destination, 0x1u | 0x8u)) {
            int error = Marshal.GetLastWin32Error();
            throw new Win32Exception(error, "Atomic state publication failed (Win32 " + error + "): " + destination);
        }
    }
}
'@ -ErrorAction Stop
    }
    $temporary = $Path + '.tmp'
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    [SimZ1MassiveAtomicFileV1]::Publish($temporary, $Path)
}

function Invoke-SimZ1MassiveTool {
    param([string]$Executable, [string[]]$Arguments, [string]$LogPath,
          [switch]$CaptureOutput, [switch]$AllowFailure, [scriptblock]$OnOutput)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Missing executable: $Executable" }
    $lines = [Collections.Generic.List[string]]::new()
    $writer = [IO.StreamWriter]::new($LogPath, $false, [Text.UTF8Encoding]::new($false))
    $previousPreference = $ErrorActionPreference
    $previousExitCodeVariable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    $previousExitCode = if ($null -ne $previousExitCodeVariable) { $previousExitCodeVariable.Value } else { $null }
    try {
        # Windows PowerShell represents native stderr as ErrorRecord even when
        # java -version succeeds. The actual exit code is checked below.
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = $null
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            $writer.WriteLine($line); $writer.Flush()
            if ($OnOutput) { & $OnOutput $line }
            if ($CaptureOutput) { $lines.Add($line) }
            Write-Host $line
        }
        $code = $global:LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
        if ($null -ne $previousExitCodeVariable) { $global:LASTEXITCODE = $previousExitCode }
        else { Remove-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
        $writer.Dispose()
    }
    if ($null -eq $code) { throw "No exit code from $Executable; see $LogPath" }
    if ($code -ne 0 -and -not $AllowFailure) { throw "Command failed (exit=$code); preserving evidence: $LogPath" }
    return [pscustomobject]@{ ExitCode = $code; Output = @($lines) }
}

function Read-SimZ1MassiveChildManifest {
    param([string]$RunDirectory, [int]$ChildExitCode, [string]$ChildLog)
    $manifestPath = Join-Path $RunDirectory 'run-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        $cause = if (Test-Path -LiteralPath $ChildLog -PathType Leaf) {
            (Get-Content -LiteralPath $ChildLog -Tail 30 -Encoding UTF8) -join [Environment]::NewLine
        } else { 'Child log unavailable; no manifest was produced.' }
        throw "Child stopped before run-manifest.json (exit=$ChildExitCode). Original output retained: $ChildLog`n$cause"
    }
    return [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
}

function Resolve-SimZ1MassiveJavaHome([string]$Requested) {
    $candidates = if ($Requested) { @($Requested) } else {
        @($env:JAVA_HOME, 'C:\Program Files\Java\jdk-17') | Where-Object { $_ }
    }
    foreach ($candidate in $candidates) {
        $release = Join-Path $candidate 'release'
        if ((Test-Path -LiteralPath $release -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'bin\java.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'bin\javac.exe') -PathType Leaf)) {
            $metadata = [IO.File]::ReadAllText($release)
            if ($metadata -match '(?m)^JAVA_VERSION="17(?:[.\-+]|"|$)') {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
    }
    throw 'A complete Java 17 JDK is required. Pass -JavaHome; no download or Java-version fallback is performed.'
}

function Get-SimZ1MassiveWriters {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $unknown = @($processes | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -match '^(java|python)(w)?\.exe$' -and
        [string]::IsNullOrWhiteSpace($_.CommandLine)
    })
    if ($unknown.Count) {
        throw ('Cannot identify an active Java/Python process; no absence of SimZ1 writers can be established. PIDs: ' + (($unknown | ForEach-Object { $_.ProcessId }) -join ','))
    }
    return @($processes | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and (
            ($_.Name -match '^java(w)?\.exe$' -and $_.CommandLine -match 'SimZ1|gt\.edu\.uvg\.sim\.zona1|exec:exec@simz1-fork|exec:java') -or
            ($_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'ejecutar_simz1\.py|generate_montecarlo_z1\.py|simz1_balanced_execute\.py')
        )
    } | Select-Object ProcessId, Name, CommandLine)
}

function New-SimZ1MassiveLock([string]$Project) {
    $canonical = [IO.Path]::GetFullPath($Project).TrimEnd('\', '/').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical)) }
    finally { $sha.Dispose() }
    $suffix = ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    return [Threading.Mutex]::new($false, ('Global\SimZ1Massive-' + $suffix))
}

function Get-SimZ1MassiveFreeBytes([string]$Project) {
    return [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Project)).AvailableFreeSpace
}

function Get-SimZ1MassiveStorageBudget {
    param($ConfigurationPlan, [int]$MaximumAgents, [int]$ObservationEndSeconds,
          [int]$MinimumFreeGiB, [int]$SQLiteBudgetGiB, [int]$ScratchBudgetGiB,
          [double]$PagefileGrowthReserveGiB)
    if ($MaximumAgents -lt 0 -or $ObservationEndSeconds -le 0 -or $MinimumFreeGiB -lt 1 -or
        $SQLiteBudgetGiB -lt 1 -or $ScratchBudgetGiB -lt 1 -or $PagefileGrowthReserveGiB -lt 0) {
        throw 'Invalid storage planning inputs.'
    }
    $eventCopies = [int]$ConfigurationPlan.native_event_files_including_final_copy
    if ($eventCopies -lt 2 -or $eventCopies -ne (@($ConfigurationPlan.native_event_iterations).Count + 1)) {
        throw 'Unknown native event retention for storage planning.'
    }
    # Preserved phase-1 reference, never a guaranteed bound on future volume.
    $historicalEventBytes = [long]16200887988
    $volumeScale = [math]::Max(1.0, ([double]$MaximumAgents / 180000) * ([double]$ObservationEndSeconds / 86400))
    $referenceEventsGiB = $historicalEventBytes * [double]$eventCopies * $volumeScale / 1GB
    $estimateGiB = $referenceEventsGiB + $SQLiteBudgetGiB + $ScratchBudgetGiB + 2 + 20 + $PagefileGrowthReserveGiB
    return [ordered]@{
        policy = $ConfigurationPlan.configuration.retention;
        native_event_iterations = @($ConfigurationPlan.native_event_iterations);
        native_event_files_including_final_copy = $eventCopies;
        native_plan_iterations = @($ConfigurationPlan.native_plan_iterations);
        native_plan_files_including_final_copy = $ConfigurationPlan.native_plan_files_including_final_copy;
        historical_event_bytes = $historicalEventBytes; historical_reference_gib = $referenceEventsGiB;
        demand_and_observation_scale = $volumeScale;
        sqlite_gib = $SQLiteBudgetGiB; scratch_gib = $ScratchBudgetGiB;
        pagefile_growth_reserve_gib = $PagefileGrowthReserveGiB;
        replay_reserve_gib = 2; ancillary_and_uncertainty_margin_gib = 20;
        plans_budget_basis = 'Shared 20 GiB ancillary/uncertainty reserve, not a measured bound; retained plan copies enumerated explicitly';
        minimum_free_gib = [math]::Max(100, [math]::Max([double]$MinimumFreeGiB, [math]::Ceiling($estimateGiB)));
        note = 'Historical planning estimate, not a bound on future event or plan volume. No retention/capacity setting is changed.'
    }
}

function Get-SimZ1MassiveXmlValue($Document, [string]$Module, [string]$Name, [string]$Default) {
    $node = $Document.SelectSingleNode("/config/module[@name='$Module']/param[@name='$Name']")
    if ($null -eq $node) {
        if ($null -ne $Default -and $Default -ne '') { return $Default }
        throw "Missing configuration parameter: $Module.$Name"
    }
    return [string]$node.value
}

function Test-SimZ1MassiveFleet($Services, [string]$CountProperty) {
    $totals = @{ transmetro = 0; tubus = 0 }
    foreach ($service in $Services) {
        if (-not $totals.ContainsKey([string]$service.system)) { throw 'Unexpected public transport system.' }
        $count = $service.$CountProperty
        if ($null -eq $count -or [double]$count -lt 0 -or [double]$count -ne [math]::Floor([double]$count)) {
            throw 'Invalid configured public fleet count.'
        }
        $totals[[string]$service.system] += [int]$count
    }
    if ($totals.transmetro -ne 176 -or $totals.tubus -ne 93) {
        throw 'The public fleet must retain exactly 176 Transmetro and 93 TuBus vehicles.'
    }
}

function Test-SimZ1MassiveGates([string]$Project, [string]$Python, [string]$LogDirectory, [string]$TrialState, [bool]$ValidationOnly = $false) {
    $validated = Join-Path $Project 'runtime\workflow\validated-source.txt'
    if (-not (Test-Path -LiteralPath $validated -PathType Leaf)) {
        throw 'Missing Validate approval. Run check_simz1_110k_balanced_gateway.ps1 -Action Validate for balanced OD; no massive run was started.'
    }
    $workflow = Join-Path $Project 'python\simz1_workflow_state.py'
    $result = Invoke-SimZ1MassiveTool -Executable $Python -Arguments @('-B', $workflow, 'fingerprint') -CaptureOutput -LogPath (Join-Path $LogDirectory '02-fingerprint.log')
    $fingerprint = ($result.Output -join "`n").Trim()
    if ($fingerprint -notmatch '^[a-f0-9]{64}$' -or [IO.File]::ReadAllText($validated).Trim() -cne $fingerprint) {
        throw 'Source fingerprint changed since Validate (new launcher/tests also count). Repeat Validate; do not copy or replace approval hashes.'
    }
    $trialArgs = if ($ValidationOnly) { @('-B', $workflow, 'require-balanced-validation') } else { @('-B', $workflow, 'require-trial') }
    if ($TrialState -and -not $ValidationOnly) { $trialArgs += @('--state',$TrialState) }
    $gateLog = if ($ValidationOnly) { '03-integrated-validation.log' } else { '03-require-trial.log' }
    $null = Invoke-SimZ1MassiveTool -Executable $Python -Arguments $trialArgs -LogPath (Join-Path $LogDirectory $gateLog)
    $null = Invoke-SimZ1MassiveTool -Executable $Python -Arguments @('-B', (Join-Path $Project 'python\simz1_runtime_check.py'), '--classpath-file', (Join-Path $Project 'target\simz1-runtime-classpath.txt')) -LogPath (Join-Path $LogDirectory '04-runtime-check.log')
    return $fingerprint
}

function Invoke-SimZ1MassiveLaunch {
    param([Collections.IDictionary]$Options)
    $ErrorActionPreference = 'Stop'
    $project = (Resolve-Path -LiteralPath (Join-Path (Split-Path $script:SimZ1MassiveScriptPath -Parent) '..')).Path
    $iterationCount = if ($Options.Contains('Iterations')) { [int]$Options.Iterations } else { 10 }
    $balanced = $Options.OdMode -ceq 'balanced-gateway-v1'
    $selection=$null
    if (-not $Options.ExperimentSpec -or -not $Options.ExperimentScenario) { throw 'Explicit versioned ExperimentSpec/ExperimentScenario required; no generic fallback.' }
    if ($Options.ExperimentSpec) {
        if (-not $balanced) {throw 'Experiment requires balanced-gateway-v1'}
        $raw=& (Join-Path $project '.venv/Scripts/python.exe') -B (Join-Path $project 'python/simz1_scale_contract.py') --spec $Options.ExperimentSpec --scenario $Options.ExperimentScenario
        $selectionCode=$LASTEXITCODE
        if ($selectionCode -ne 0) {throw 'Experiment specification rejected'}
        $selection=($raw -join [Environment]::NewLine) | ConvertFrom-Json
        if ($Options.MinAgents -ne $selection.total_non_public_vehicles -or $Options.MaxAgents -ne $Options.MinAgents -or $iterationCount -ne $selection.iterations -or $Options.Seed -ne $selection.demand_seed) {throw 'Requested launch differs from experiment specification'}
    } elseif ($Options.ExperimentScenario) {throw 'Experiment scenario without specification'}
    if (-not $selection.base_scenario_identity) { throw 'Use the versioned 24h successor with run1000 and base scenario identity; historical experiments are read-only.' }
    $Options.ExperimentSchema = $selection.schema
    $firstScale = Test-SimZ1FirstScaleTrial $Options
    $isTrial = $selection.scenario -ceq 'run1000'
    $postprocessingPolicy = [string]$Options.PostprocessingPolicy
    if (-not $postprocessingPolicy) {
        $postprocessingPolicy = if ($selection.schema -cin @('simz1-final-experiments-v5','simz1-final-experiments-v6','simz1-final-experiments-v7','simz1-final-experiments-v8')) { 'native_diagnostic_v1' } else { 'automatic_replay_v1' }
    }
    $isDiagnostic = $postprocessingPolicy -ceq 'native_diagnostic_v1'
    if ($Options.MinAgents -eq 110000 -or $Options.MaxAgents -eq 110000 -or $balanced) {
        if (-not $balanced -or (-not $selection -and ($iterationCount -ne 1 -or $Options.MinAgents -notin @(110000,180000))) -or
            $Options.MaxAgents -ne $Options.MinAgents -or $Options.Seed -ne 20261023) {
            throw 'Balanced scale requires exact 110000/180000, seed=20261023 and iteration 0.'
        }
    }
    if ($iterationCount -notin @(1,10)) { throw 'Only one or ten iterations are supported.' }
    $lastIteration = $iterationCount - 1
    $destinationPolicy = if ($Options.DestinationPolicy) { [string]$Options.DestinationPolicy } else { 'lane-length-destinations-v1' }
    $coordination = if ($Options.ShortLinkSignalCoordination) { [string]$Options.ShortLinkSignalCoordination } else { 'derive-activity-v2' }
    if ($coordination -notin @('derive','derive-activity-v2')) { throw 'Unsupported signal coordination policy.' }
    if ($balanced) { $coordination = 'none' }
    $coordinationPolicy = if ($balanced) { 'none' } elseif ($coordination -eq 'derive-activity-v2') { 'short_body_passage_activity_offsets_v2' } else { 'short_body_passage_offsets_v1' }
    $launchId = [guid]::NewGuid().ToString('N')
    $launch = Join-Path $project ('runtime\launches\' + $launchId)
    # The report package repeats the run basename. Keep the new one-iteration
    # path short enough for Windows; retain the historical ten-iteration name.
    $runName = if ($iterationCount -eq 1) { 'run-z1-1it-' + $launchId } else { 'run-massive-pasante-10it-' + $launchId }
    if ($balanced) { $runName = 'run-bg' + [string]($Options.MinAgents / 1000) + '-' + $launchId }
    $run = Join-Path $project ('scenarios\zona1\montecarlo\' + $runName)
    New-Item -ItemType Directory -Path $launch -Force | Out-Null
    $statePath = Join-Path $launch 'state.json'
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    $ownerIdentity = [ordered]@{pid=$PID;parent_pid=[int]$owner.ParentProcessId;
        created_utc=$owner.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ');
        executable=$owner.ExecutablePath;command=$owner.CommandLine;role='launcher';launch_id=$launchId;run_id=$null}
    $state = [ordered]@{ schema_version = 1; launch_id = $launchId; status = 'preflight'; phase = 'request';
        dry_run = [bool]$Options.DryRun; run_directory = $run; started_utc = [DateTime]::UtcNow.ToString('o');
        outcome = $null; exit_code = $null; native_status = $null; native_validation = $null; screening = $null;
        finished_utc = $null; source_fingerprint = $null; java_home = $null; free_bytes = $null;
        required_free_gib = $null; run_id = $null; error = $null;
        child_exit_code = $null; child_log = $null; process=$ownerIdentity }
    $request = [ordered]@{ schema_version = 1; launch_id = $launchId; project = $project; run_directory = $run;
        minimum_non_public_vehicles = $Options.MinAgents; maximum_non_public_vehicles = $Options.MaxAgents;
        demand_seed = $Options.Seed; matsim_seed = $Options.Seed; iterations = $iterationCount; first_iteration = 0; last_iteration = $lastIteration; destination_policy = $destinationPolicy;
        service_date = '2026-10-23'; public_vehicles = 269; transmetro_vehicles = 176; tubus_vehicles = 93; freight_service_version = 'weekday-compact-v3';
        population_selection = 'one seeded N for the whole run, unchanged across iterations';
        quantity_policy = 'explicit versioned catalog; N excludes the 269 buses';
        qsim_threads = 1; storage_policy = 'strict-receiver-v1'; whole_vehicle_reservation = $true;
        signals = $true; short_link_signal_coordination = $coordination; dry_run = [bool]$Options.DryRun;
        od_mode = $(if ($balanced) { 'balanced-gateway-v1' } else { 'network' });
        minimum_free_gib_requested = $Options.MinFreeGiB; sqlite_budget_gib = $Options.SQLiteBudgetGiB;
        scratch_budget_gib = $Options.ScratchBudgetGiB; requested_java_home = $Options.JavaHome }
    $request.prior_trial_policy = if ($isTrial) { 'this_is_the_versioned_acceptance_trial' } elseif ($Options.DryRun) { 'checked_if_present; required_before_Run' } else { 'require_accepted_1000_same_base_and_revision' }
    $request.first_scale_trial = $firstScale
    $request.experiment = $selection
    $request.dry_run_launch_id = $Options.DryRunLaunchId
    $request.postprocessing_policy = $postprocessingPolicy
    $state.postprocessing_policy = $postprocessingPolicy
    if ($isDiagnostic) {
        $state.replay_status = 'manual_after_native_validation'
        $state.visual_acceptance = 'not_certified'
        $request.acceptance_scope = $postprocessingPolicy
    }
    Write-SimZ1MassiveJson (Join-Path $launch 'request.json') $request
    Write-SimZ1MassiveJson $statePath $state
    Write-Host "LAUNCH EVIDENCE: $launch"
    Write-Host "PLANNED NEW RUN: $run"
    $mutex = $null; $held = $false
    $oldJavaHome = $env:JAVA_HOME; $oldPath = $env:PATH; $oldLocation = Get-Location
    $oldLaunchId=$env:SIMZ1_LAUNCH_ID; $oldLaunchPid=$env:SIMZ1_LAUNCH_PID; $oldLaunchCreated=$env:SIMZ1_LAUNCH_CREATED_UTC
    $oldLaunchDirectory=$env:SIMZ1_LAUNCH_DIRECTORY
    $env:SIMZ1_LAUNCH_ID=$launchId; $env:SIMZ1_LAUNCH_PID=[string]$PID
    $env:SIMZ1_LAUNCH_CREATED_UTC=$ownerIdentity.created_utc
    $env:SIMZ1_LAUNCH_DIRECTORY=$launch
    try {
        if ($Options.MinAgents -gt $Options.MaxAgents) { throw '-MinAgents cannot exceed -MaxAgents.' }
        if (Test-Path -LiteralPath $run) { throw "Refusing to reuse an existing run: $run" }
        Set-Location -LiteralPath $project
        if ($balanced) {
            foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile')) {
                if (-not $Options[$key] -or -not (Test-Path -LiteralPath $Options[$key] -PathType Leaf)) {
                    throw "balanced-gateway-v1 BLOQUEADO: falta -$key '$($Options[$key])'. Sin bbox ni fallback network."
                }
                $request[$key] = (Resolve-Path -LiteralPath $Options[$key]).Path
                $request[$key + '_sha256'] = (Get-FileHash -LiteralPath $request[$key] -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            Write-SimZ1MassiveJson (Join-Path $launch 'request.json') $request
        }
        $state.phase = 'exclusive_launch'; Write-SimZ1MassiveJson $statePath $state
        $mutex = New-SimZ1MassiveLock $project
        try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw 'Another massive launcher owns this workspace; no second writer is started.' }
        $writers = @(Get-SimZ1MassiveWriters)
        if ($writers.Count) {
            Write-SimZ1MassiveJson (Join-Path $launch 'active-writers.json') $writers
            throw 'An existing SimZ1 Java/generation process is active; it was not stopped. See active-writers.json.'
        }
        $python = Join-Path $project '.venv\Scripts\python.exe'
        $wrapper = Join-Path $project 'scripts\run_simz1_with_analysis.ps1'
        $replay = Join-Path $project 'scripts\replay\prepare_replay.py'
        $requiredTools = @($python, $wrapper)
        $requiredTools += $replay
        foreach ($path in $requiredTools) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing tool: $path" }
        }
        if ($balanced) {
            $state.phase = 'od_input_identity'; Write-SimZ1MassiveJson $statePath $state
            $odIdentity = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_balanced_launch.py'),
                '--boundary',$request.ZoneBoundary,'--access',$request.OdAccessCatalog,'--mix-file',$request.OdMixFile) -CaptureOutput -LogPath (Join-Path $launch '00-od-input-identity.log')
            $request.od_identity = ($odIdentity.Output -join "`n") | ConvertFrom-Json
            Write-SimZ1MassiveJson (Join-Path $launch 'request.json') $request
        }
        $state.phase = 'java17'
        $state.java_home = Resolve-SimZ1MassiveJavaHome $Options.JavaHome
        $env:JAVA_HOME = $state.java_home
        $env:PATH = (Join-Path $state.java_home 'bin') + ';' + $oldPath
        $version = Invoke-SimZ1MassiveTool -Executable (Join-Path $state.java_home 'bin\java.exe') -Arguments @('-version') -CaptureOutput -LogPath (Join-Path $launch '01-java-version.log')
        if (($version.Output -join "`n") -notmatch '(?m)^(?:openjdk|java) version "17(?:[.\-+]|"|$)') { throw 'The selected executable did not report Java 17.' }
        $state.phase = 'memory_preflight'; Write-SimZ1MassiveJson $statePath $state
        $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_massive_resources.py'), '--output', (Join-Path $launch 'memory.json')) -LogPath (Join-Path $launch '01b-memory.log')
        $memory = [IO.File]::ReadAllText((Join-Path $launch 'memory.json')) | ConvertFrom-Json
        $state.phase = 'configuration_and_space'; Write-SimZ1MassiveJson $statePath $state

        $configPath = if ($Options.SourceConfig) { (Resolve-Path -LiteralPath $Options.SourceConfig).Path } else { Join-Path $project 'scenarios\zona1\config-simz1.xml' }
        [xml]$baseConfig = [IO.File]::ReadAllText($configPath)
        $catalogPath = if ($Options.AgentCatalog) { (Resolve-Path -LiteralPath $Options.AgentCatalog).Path } else { Join-Path $project 'scenarios\zona1\agent-types-balanced-v1.json' }
        $catalog = [IO.File]::ReadAllText($catalogPath) | ConvertFrom-Json
        $weights = $catalog.non_public_demand.family_weights
        if ($destinationPolicy -cne 'lane-length-destinations-v1' -or
            (-not $balanced -and $coordination -cne 'derive-activity-v2')) { throw 'Massive experiments require the balanced catalog and their versioned signal policy.' }
        $expectedWeights = @(44,55,1)
        if ($weights.carro -ne $expectedWeights[0] -or $weights.moto -ne $expectedWeights[1] -or $weights.pesado -ne $expectedWeights[2] -or $catalog.non_public_demand.public_transport_in_total -ne $false) { throw 'Explicit catalog weights do not match the requested experimental scenario.' }
        $declaredDestination = if ($catalog.destination_policy) { $catalog.destination_policy } else { 'legacy-gaussian-v1' }
        if ($declaredDestination -cne $destinationPolicy) { throw 'Catalog destination policy mismatch.' }
        $request.agent_catalog = $catalogPath
        $request.agent_catalog_sha256 = (Get-FileHash -LiteralPath $catalogPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $request.family_weights = $weights
        $freightPath = if ($Options.FreightService) { (Resolve-Path -LiteralPath $Options.FreightService).Path } else { Join-Path $project 'scenarios\zona1\freight\weekday-compact-v3\service-composition-v3.json' }
        $freightService = [IO.File]::ReadAllText($freightPath) | ConvertFrom-Json
        if ($freightService.length_m -ne 8.0 -or $freightService.width_m -ne 2.3) { throw 'Compact freight must retain its 8.0 x 2.3 m body.' }
        $request.freight_service = $freightPath
        $request.freight_service_sha256 = (Get-FileHash -LiteralPath $freightPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-SimZ1MassiveJson (Join-Path $launch 'request.json') $request
        $transitPath = (Resolve-Path -LiteralPath (Join-Path $project $selection.base_inputs.transit_service)).Path
        $request.transit_service = $transitPath
        $request.transit_service_sha256 = (Get-FileHash -LiteralPath $transitPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $transitPolicy = [IO.File]::ReadAllText($transitPath) | ConvertFrom-Json
        if ($transitPolicy.fleet_counts.transmetro -ne 176 -or $transitPolicy.fleet_counts.tubus -ne 93) {
            throw 'The approved service must declare 176 Transmetro and 93 TuBus vehicles.'
        }
        Test-SimZ1MassiveFleet $transitPolicy.services 'buses'
        Write-SimZ1MassiveJson (Join-Path $launch 'request.json') $request
        if ((Get-SimZ1MassiveXmlValue $baseConfig 'signalsystems' 'useSignalsystems') -cne 'true' -or
            (Get-SimZ1MassiveXmlValue $baseConfig 'qsim' 'useLanes') -cne 'true') {
            throw 'The approved base configuration must retain native signals and lanes enabled.'
        }
        $configurationPlanPath = Join-Path $launch 'configuration-plan.json'
        $configurationResult = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B',
            (Join-Path $project 'python\simz1_configuration_contract.py'), 'plan', '--base-config', $configPath,
            '--iterations', [string]$iterationCount, '--native-end-seconds', [string]$selection.native_qsim_end_seconds,
            '--experiment-spec', [string]$selection.specification_path, '--experiment-scenario', [string]$selection.scenario,
            '--output', $configurationPlanPath) -CaptureOutput -LogPath (Join-Path $launch '01c-configuration-contract.log')
        $configurationPlan = ($configurationResult.Output -join "`n") | ConvertFrom-Json
        $retention = $configurationPlan.configuration.retention
        $eventIterations = @($configurationPlan.native_event_iterations)
        $storageBudget = Get-SimZ1MassiveStorageBudget -ConfigurationPlan $configurationPlan -MaximumAgents $Options.MaxAgents `
            -ObservationEndSeconds $selection.observation_end_seconds -MinimumFreeGiB $Options.MinFreeGiB `
            -SQLiteBudgetGiB $Options.SQLiteBudgetGiB -ScratchBudgetGiB $Options.ScratchBudgetGiB `
            -PagefileGrowthReserveGiB $memory.pagefile_growth_reserve_gib
        $referenceEventsGiB = $storageBudget.historical_reference_gib
        $requiredGiB = $storageBudget.minimum_free_gib
        $state.free_bytes = Get-SimZ1MassiveFreeBytes $project
        $state.required_free_gib = $requiredGiB
        $storageBudget.available_free_bytes = $state.free_bytes
        Write-SimZ1MassiveJson (Join-Path $launch 'retention-and-space.json') $storageBudget
        Write-Host ("RETENTION: native events [{0}] plus final copy; reference {1:N2} GiB; required free {2} GiB; available {3:N2} GiB" -f ($eventIterations -join ','), $referenceEventsGiB, $requiredGiB, ($state.free_bytes / 1GB))
        if ($state.free_bytes -lt $requiredGiB * 1GB) { throw "Insufficient disk space for the declared planning budget ($requiredGiB GiB); no run was created." }

        $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $wrapper,
            '-SourceConfig', $configPath,
            '-MinAgents', [string]$Options.MinAgents, '-MaxAgents', [string]$Options.MaxAgents,
            '-Seed', [string]$Options.Seed, '-Iterations', [string]$iterationCount, '-ServiceDate', '2026-10-23',
            '-FreightServiceDate', '2026-10-23', '-FreightService', $freightPath,
            '-TransitService', $transitPath,
            '-AgentCatalog', $catalogPath, '-DestinationPolicy', $destinationPolicy,
            '-AcceptTransitRouteAssumptions', '-QSimThreads', '1', '-StoragePolicy', 'strict-receiver-v1',
            '-OriginPolicy', $(if ($balanced) { 'lane-length-access-v1' } else { 'uniform-nodes-v1' }), '-ShortLinkSignalCoordination', $coordination,
            '-MinCompletionRate', '0.90', '-MinFreeGiB', [string][int]$requiredGiB, '-NewRunDir', $run)
        if ($selection) {$arguments += @('-ExperimentSpec',$selection.specification_path,'-ExperimentScenario',$selection.scenario)}
        $trialState = $null
        $odGateArgs = @()
        if ($balanced) {
            $arguments += @('-OdMode','balanced-gateway-v1','-ZoneBoundary',$request.ZoneBoundary,
                '-OdAccessCatalog',$request.OdAccessCatalog,'-OdMixFile',$request.OdMixFile)
            Assert-SimZ1PathArguments $arguments @{ZoneBoundary=$request.ZoneBoundary;OdAccessCatalog=$request.OdAccessCatalog;OdMixFile=$request.OdMixFile}
            $trialState = Join-Path $project 'runtime\workflow\trial-balanced-gateway-v1.json'
            $odGateArgs = @('--state',$trialState,'--od-mode','balanced-gateway-v1',
                '--zone-boundary',$request.ZoneBoundary,'--od-access-catalog',$request.OdAccessCatalog,'--od-mix-file',$request.OdMixFile)
        }
        $replayArguments = @('-B', $replay, '--run-dir', $run, '--iteration', [string]$lastIteration,
            '--sqlite-budget-gib', [string]$Options.SQLiteBudgetGiB, '--scratch-budget-gib', [string]$Options.ScratchBudgetGiB)
        $commandRecord = [ordered]@{ wrapper = $arguments; replay = $replayArguments; replay_starts_server_or_browser = $false }
        if ($balanced) {
            $commandRecord.hourly_report = @('-B',(Join-Path $project 'python\simz1_balanced_launch_report.py'),'--run-dir',$run,'--iteration',[string]$lastIteration)
            $commandRecord.replay_status = 'prepare_after_native_validation'
            if ($isDiagnostic) { $commandRecord.replay_status = 'manual_after_native_validation' }
        }
        Write-SimZ1MassiveJson (Join-Path $launch 'commands.json') $commandRecord
        $powershell = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
        $state.phase = 'configuration_preflight'; Write-SimZ1MassiveJson $statePath $state
        $null = Invoke-SimZ1MassiveTool -Executable $powershell -Arguments ($arguments + '-DryRun') -LogPath (Join-Path $launch '05-preflight.log')
        if (Test-Path -LiteralPath $run) { throw 'Read-only preflight unexpectedly created the requested run directory; preserve it and investigate.' }
        # Read-only integration can be checked with a stale approval, but both
        # DryRun success and any real simulation still require the exact gates.
        $state.phase = 'acceptance_gates'; Write-SimZ1MassiveJson $statePath $state
        $validationOnly = $isTrial -or [bool]$Options.DryRun
        $state.source_fingerprint = Test-SimZ1MassiveGates $project $python $launch $trialState $validationOnly
        $state.phase = 'preparation_identity'; Write-SimZ1MassiveJson $statePath $state
        $identityArgs = @('-B', (Join-Path $project 'python\simz1_workflow_state.py'),
            'verify-preparation-identity', '--experiment-spec', $selection.specification_path,
            '--experiment-scenario', $selection.scenario, '--launch-request', (Join-Path $launch 'request.json'),
            '--source-fingerprint', $state.source_fingerprint, '--postprocessing-policy', $postprocessingPolicy)
        $identityResult = Invoke-SimZ1MassiveTool -Executable $python -Arguments $identityArgs -CaptureOutput -LogPath (Join-Path $launch '05b-preparation-identity.log')
        $identityReceipt = ($identityResult.Output -join "`n") | ConvertFrom-Json
        $identityPath = Join-Path $launch 'preparation-identity.json'
        Write-SimZ1MassiveJson $identityPath $identityReceipt
        $state.preparation_identity_sha256 = (Get-FileHash -LiteralPath $identityPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $state.phase = 'acceptance_gates'; Write-SimZ1MassiveJson $statePath $state
        $state.prior_trial_status = if ($isTrial) { 'not_applicable_this_is_trial' } else { 'pending_not_approved' }
        $state.run_launch_eligible = $isTrial
        if (-not $isTrial -and (-not $Options.DryRun -or (Test-Path -LiteralPath $trialState))) {
            $trialGate = @('-B', (Join-Path $project 'python\simz1_workflow_state.py'), 'require-trial', '--catalog-sha256', $request.agent_catalog_sha256, '--destination-policy', $destinationPolicy, '--signal-coordination-policy', $coordinationPolicy, '--freight-service-version', 'weekday-compact-v3', '--freight-service-sha256', $request.freight_service_sha256, '--experiment-spec', $selection.specification_path, '--experiment-scenario', $selection.scenario) + $odGateArgs
            $trialResult = Invoke-SimZ1MassiveTool -Executable $python -Arguments $trialGate -LogPath (Join-Path $launch '04b-same-scenario.log') -AllowFailure:([bool]$Options.DryRun)
            if ($trialResult.ExitCode -eq 0) {
                $state.prior_trial_status = 'accepted_same_base_and_revision'; $state.run_launch_eligible = $true
            } else { $state.prior_trial_status = 'existing_trial_rejected; required_before_Run' }
        }
        if ($balanced) {
            foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile')) {
                if ((Get-FileHash -LiteralPath $request[$key] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $request[$key + '_sha256']) {
                    throw "El insumo $key cambio durante preflight; no se inicia la corrida."
                }
            }
        }
        if ($Options.DryRun) {
            $state.status = 'dry_run_pass'; $state.phase = 'completed';
            Set-SimZ1LaunchOutcome $state 'PASSED'
            Write-Host "DRY RUN PASSED: no simulation directory, private population, QSim or replay created. Evidence: $launch"
            if (-not $state.run_launch_eligible) { Write-Host 'RUN REMAINS BLOCKED: complete the versioned run1000 and its acceptance first.' }
            return 0
        }
        if ($selection) {
            $dryGate = @('-B', (Join-Path $project 'python\simz1_workflow_state.py'),
                'require-experiment-dry-run', '--experiment-spec', $selection.specification_path,
                '--experiment-scenario', $selection.scenario, '--dry-run-launch-id', [string]$Options.DryRunLaunchId,
                '--postprocessing-policy', $postprocessingPolicy)
            $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments $dryGate -LogPath (Join-Path $launch '04c-same-selection-dry-run.log')
        }
        if ($selection.schema -ceq 'simz1-final-experiments-v4') {
            $claimArgs = @('-B', (Join-Path $project 'python\simz1_scale_contract.py'), '--spec', $selection.specification_path,
                '--scenario', $selection.scenario, '--claim-launch-id', $launchId)
            $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments $claimArgs -LogPath (Join-Path $launch '04d-selection-claim.log')
        }
        $state.status = 'running'; $state.phase = 'simulation_and_analysis'; Write-SimZ1MassiveJson $statePath $state
        $state.child_log = Join-Path $launch '06-simulation-and-analysis.log'
        $pipeline = Invoke-SimZ1MassiveTool -Executable $powershell -Arguments $arguments -LogPath $state.child_log -AllowFailure -OnOutput {
            if (-not $state.run_id -and (Test-Path -LiteralPath (Join-Path $run 'run-manifest.json'))) {
                $created = [IO.File]::ReadAllText((Join-Path $run 'run-manifest.json')) | ConvertFrom-Json
                $state.run_id=$created.run_id; $state.process.run_id=$created.run_id
                Write-SimZ1MassiveJson $statePath $state
            }
        }
        $state.child_exit_code = $pipeline.ExitCode
        Write-SimZ1MassiveJson $statePath $state
        $manifest = Read-SimZ1MassiveChildManifest -RunDirectory $run -ChildExitCode $pipeline.ExitCode -ChildLog $state.child_log
        $state.phase = 'verify_result'; Write-SimZ1MassiveJson $statePath $state
        $state.run_id = $manifest.run_id
        $state.process.run_id = $manifest.run_id
        $state.native_status = $manifest.status; $state.native_validation = $manifest.validation.status
        $state.screening = Get-SimZ1PipelineDisposition $manifest $pipeline.ExitCode
        if ($manifest.status -cne 'completed' -or $manifest.validation.status -cne 'valid' -or
            [IO.Path]::GetFullPath($manifest.folder) -ine $run -or $manifest.iterations.first -ne 0 -or
            $manifest.iterations.last -ne $lastIteration -or $manifest.iterations.requested -ne $iterationCount -or
            $manifest.demand_seed -ne $Options.Seed -or $manifest.matsim_seed -ne $Options.Seed -or
            (@($manifest.iterations.completed) -join ',') -cne (@(0..$lastIteration) -join ',') -or $null -eq $manifest.results.([string]$lastIteration) -or $manifest.destination_policy -cne $destinationPolicy -or $manifest.short_link_signal_coordination.policy -cne $coordinationPolicy) {
            throw 'The exact requested run did not validate all requested iterations; no replay or retry is started.'
        }
        $counts = $manifest.counts; $mix = $manifest.demand_composition
        if ($balanced -and ($manifest.spatial_demand.mode -cne 'balanced-gateway-v1' -or
            $manifest.origin_policy -cne 'lane-length-access-v1' -or $mix.family_counts.carro -ne $(if ($selection) {$selection.composition.carro} else {$Options.MinAgents * 44 / 100}) -or
            $mix.family_counts.moto -ne $(if ($selection) {$selection.composition.moto} else {$Options.MinAgents * 55 / 100}) -or $mix.freight_vehicles -ne $(if ($selection) {$selection.composition.pesado} else {$Options.MinAgents / 100}))) { throw 'El resultado no es la composicion OD solicitada.' }
        if ($balanced -and ($manifest.inputs.zone_boundary.sha256 -cne $request.ZoneBoundary_sha256 -or
            $manifest.balanced_od.access_catalog.sha256 -cne $request.OdAccessCatalog_sha256 -or
            $manifest.spatial_demand.hypothesis.sha256 -cne $request.od_identity.hypothesis_sha256)) {
            throw 'La corrida no uso los insumos OD comprobados antes de iniciar.'
        }
        Test-SimZ1MassiveFleet $manifest.public_transport.service_counts 'configured_buses'
        $freightMatches = if ($null -ne $mix -and $mix.freight_vehicles -eq 0) {
            -not $manifest.freight_transport.enabled -and $counts.freight_vehicles_configured -eq 0
        } else {
            $manifest.freight_transport.enabled -and $manifest.freight_transport.service_version -ceq 'weekday-compact-v3'
        }
        if ($null -eq $mix -or $mix.total_non_public_vehicles -lt $Options.MinAgents -or $mix.total_non_public_vehicles -gt $Options.MaxAgents -or
            $counts.non_public_vehicles_configured -ne $mix.total_non_public_vehicles -or
            $counts.planned_persons -ne $mix.private_vehicles -or $counts.freight_vehicles_configured -ne $mix.freight_vehicles -or
            $counts.public_transport_vehicles_configured -ne 269 -or $counts.all_vehicles_configured -ne ($mix.total_non_public_vehicles + 269) -or
            -not $freightMatches) {
            throw 'Composition, passing freight version or the 269 public buses differ from the requested run.'
        }
        $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B',
            (Join-Path $project 'python\simz1_configuration_contract.py'), 'verify-run', '--run-dir', $run,
            '--expected', $configurationPlanPath, '--output', (Join-Path $launch 'configuration-verification.json')) -LogPath (Join-Path $launch '07-configuration-verification.log')
        $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B',
            (Join-Path $project 'python\simz1_launch_recovery.py'), 'verify-closure', '--request', (Join-Path $launch 'request.json'),
            '--run-dir', $run, '--output', (Join-Path $launch 'closure-verification.json')) -LogPath (Join-Path $launch '07-closure-verification.log')
        $finalFingerprint = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_workflow_state.py'), 'fingerprint') -CaptureOutput -LogPath (Join-Path $launch '07-final-fingerprint.log')
        if (($finalFingerprint.Output -join "`n").Trim() -cne $state.source_fingerprint) { throw 'Sources changed while the run executed; preserve outputs and review before replay.' }
        foreach ($reportIteration in $eventIterations) {
            $state.phase = "operational_report_iteration_$reportIteration"; Write-SimZ1MassiveJson $statePath $state
            $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_operational_report.py'), '--run-dir', $run, '--iteration', [string]$reportIteration) -LogPath (Join-Path $launch "07b-operations-iteration-$reportIteration.log")
            if ($balanced) {
                $state.phase = "hourly_balanced_evidence_$reportIteration"; Write-SimZ1MassiveJson $statePath $state
                $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_balanced_launch_report.py'), '--run-dir',$run,'--iteration',[string]$reportIteration) -LogPath (Join-Path $launch "08-hourly-balanced-$reportIteration.log")
            }
        }
        if ($isDiagnostic) {
            $state.replay_status = 'manual_after_native_validation'
            $state.visual_acceptance = 'not_certified'
        } else {
            $state.phase = "prepare_replay_iteration_$lastIteration"; Write-SimZ1MassiveJson $statePath $state
            $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments $replayArguments -LogPath (Join-Path $launch "08-replay-iteration-$lastIteration.log")
        }
        $state.status = 'completed'; $state.phase = 'completed'
        if ($state.screening -eq 'review_required') {
            $state.status = 'review_required'; Set-SimZ1LaunchOutcome $state 'REVIEW_REQUIRED'
            Write-Host "MATSim completed/valid; screening review_required; evidence retained: $run"
            return 3
        }
        if ($isTrial) {
            $trialFingerprint = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_workflow_state.py'), 'fingerprint') -CaptureOutput -LogPath (Join-Path $launch '09-trial-final-fingerprint.log')
            if (($trialFingerprint.Output -join "`n").Trim() -cne $state.source_fingerprint) { throw 'Sources changed during trial postprocessing; no acceptance is recorded.' }
            $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B', (Join-Path $project 'python\simz1_workflow_state.py'), 'record-trial', '--run-dir', $run, '--state', $trialState) -LogPath (Join-Path $launch '09-record-versioned-trial.log')
        }
        Set-SimZ1LaunchOutcome $state 'PASSED'
        if ($isDiagnostic) {
            Write-Host "NATIVE DIAGNOSTIC COMPLETED: $run | run_id=$($state.run_id) | replay manual; visual acceptance pending"
        } else { Write-Host "$iterationCount ITERATIONS AND REPLAY $lastIteration PREPARED: $run | run_id=$($state.run_id)" }
        Write-Host "Launch evidence: $launch"
        return 0
    } catch {
        $state.status = if (Test-Path -LiteralPath $run) { 'failed' } else { 'blocked' }
        if ($state.native_status -eq 'completed' -and $state.native_validation -eq 'valid') { $state.status = 'postprocessing_failed' }
        Set-SimZ1LaunchOutcome $state $(if ($state.status -eq 'blocked') { 'BLOCKED' } else { 'FAILED' })
        $state.error = $_.Exception.Message
        Write-Host "LAUNCH STOPPED: $($state.error)"
        Write-Host "No automatic retry or cleanup. Evidence retained: $launch"
        if ($null -ne $state.child_exit_code -and $state.child_exit_code -ne 0 -and
            -not (Test-Path -LiteralPath (Join-Path $run 'run-manifest.json') -PathType Leaf)) {
            # The caller already propagates returned codes. Keep preparation's
            # actual failure code instead of replacing it with the generic 1.
            $state.exit_code = [int]$state.child_exit_code
            return $state.exit_code
        }
        throw
    } finally {
        $state.finished_utc = [DateTime]::UtcNow.ToString('o')
        $env:SIMZ1_LAUNCH_ID=$oldLaunchId; $env:SIMZ1_LAUNCH_PID=$oldLaunchPid; $env:SIMZ1_LAUNCH_CREATED_UTC=$oldLaunchCreated
        $env:SIMZ1_LAUNCH_DIRECTORY=$oldLaunchDirectory
        try { Write-SimZ1MassiveJson $statePath $state }
        finally {
            $env:JAVA_HOME = $oldJavaHome; $env:PATH = $oldPath
            try { Set-Location -LiteralPath $oldLocation.Path }
            finally {
                try { if ($held) { $mutex.ReleaseMutex() } }
                finally { if ($null -ne $mutex) { $mutex.Dispose() } }
            }
        }
    }
}

# Dot sourcing only defines helpers so negative-path tests can supply isolated
# process/gate doubles without executing the launcher on a real workspace.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        $launchCode = Invoke-SimZ1MassiveLaunch -Options @{
            MinAgents = $MinAgents; MaxAgents = $MaxAgents; Seed = $Seed; JavaHome = $JavaHome;
            MinFreeGiB = $MinFreeGiB; SQLiteBudgetGiB = $SQLiteBudgetGiB;
            ScratchBudgetGiB = $ScratchBudgetGiB; DryRun = [bool]$DryRun; Iterations=10;
            ExperimentSpec=$ExperimentSpec; ExperimentScenario=$ExperimentScenario; OdMode=$OdMode;
            DryRunLaunchId=$DryRunLaunchId; PostprocessingPolicy=$PostprocessingPolicy;
            ZoneBoundary=$ZoneBoundary; OdAccessCatalog=$OdAccessCatalog; OdMixFile=$OdMixFile;
            SourceConfig=$SourceConfig; FreightService=$FreightService; FirstScaleTrial=[bool]$FirstScaleTrial
        }
        exit $launchCode
    } catch {
        Write-Error -Message $_.Exception.Message -ErrorAction Continue
        exit 1
    }
}
