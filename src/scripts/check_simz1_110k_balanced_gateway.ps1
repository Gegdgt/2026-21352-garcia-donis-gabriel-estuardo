# Manual integrated validation/trial. This script cannot start a massive run.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Validate','Run1000')][string]$Action,
    [string]$ExperimentSpec,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$DryRunLaunchId,
    [switch]$DryRun,
    [string]$ZoneBoundary = 'scenarios\zona1\od\balanced-gateway-v1\perimeter.geojson',
    [string]$OdAccessCatalog = 'scenarios\zona1\od\balanced-gateway-v1\access.json',
    [string]$OdMixFile = 'scenarios\zona1\od\balanced-gateway-v1\mix.json',
    [string]$JavaHome = 'C:\Program Files\Java\jdk-17'
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ($DryRun -and $Action -ne 'Run1000') { throw '-DryRun applies only to the explicit Run1000 preparation.' }
if ($Action -eq 'Run1000') {
    if (-not $ExperimentSpec) { throw 'Run1000 requires explicit -ExperimentSpec with the versioned run1000 selector.' }
    $trialOptions = @{ExperimentSpec=$ExperimentSpec; ExperimentScenario='run1000'; JavaHome=$JavaHome;
        ZoneBoundary=$ZoneBoundary; OdAccessCatalog=$OdAccessCatalog; OdMixFile=$OdMixFile}
    if ($DryRunLaunchId) { $trialOptions.DryRunLaunchId=$DryRunLaunchId }
    if ($DryRun) { $trialOptions.DryRun=$true } else { $trialOptions.Run=$true }
    & (Join-Path $PSScriptRoot 'run_simz1_180k_balanced_gateway.ps1') @trialOptions
    $trialExit=$LASTEXITCODE
    exit $trialExit
}
$requestedJavaHome = $JavaHome
. (Join-Path $PSScriptRoot 'run_massive_z1_pasante_10it.ps1')
$evidence = Join-Path $project ('runtime\validation\balanced-launch-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $evidence | Out-Null
Write-Host "VALIDATION EVIDENCE: $evidence"
$oldJava = $env:JAVA_HOME; $oldPath = $env:PATH
$lock = New-SimZ1MassiveLock $project
$held = $false
$state = [ordered]@{action=$Action;status='running';outcome=$null;exit_code=$null}
$exitCode = 1
try {
    try { $held = $lock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'Otro lanzador/validador posee el workspace.' }
    if (@(Get-SimZ1MassiveWriters).Count) { throw 'Hay procesos SimZ1 activos. No se recompila ni inicia Run1000.' }
    $env:JAVA_HOME = Resolve-SimZ1MassiveJavaHome $requestedJavaHome
    $env:PATH = (Join-Path $env:JAVA_HOME 'bin') + ';' + $oldPath
    $shell = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $project 'scripts\simz1_workflow.ps1'),
        '-Action',$Action,'-OdMode','balanced-gateway-v1','-Seed','20261023',
        '-AgentCatalog',(Join-Path $project 'scenarios\zona1\agent-types-balanced-v1.json'),
        '-DestinationPolicy','lane-length-destinations-v1','-ShortLinkSignalCoordination','none',
        '-FreightService',(Join-Path $project 'scenarios\zona1\freight\weekday-compact-v3\service-composition-v3.json'),
        '-FreightServiceDate','2026-10-23','-ServiceDate','2026-10-23','-AcceptTransitRouteAssumptions')
    if ($Action -eq 'Run1000') {
        $python = Join-Path $project '.venv\Scripts\python.exe'
        $null = Invoke-SimZ1MassiveTool -Executable $python -Arguments @('-B',(Join-Path $project 'python\simz1_massive_resources.py'),'--output',(Join-Path $evidence 'memory.json')) -LogPath (Join-Path $evidence 'memory.log')
        $paths = @{}
        foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile')) {
            $value = Get-Variable -Name $key -ValueOnly
            if (-not [IO.Path]::IsPathRooted($value)) { $value = Join-Path $project $value }
            $paths[$key] = $value
        }
        $arguments = @(Add-SimZ1PathArguments -Arguments $arguments -Paths $paths)
    }
    Write-SimZ1MassiveJson (Join-Path $evidence 'request.json') ([ordered]@{action=$Action;arguments=$arguments;java_home=$env:JAVA_HOME})
    $null = Invoke-SimZ1MassiveTool -Executable $shell -Arguments $arguments -LogPath (Join-Path $evidence ($Action + '.log'))
    $state.status = 'completed'; Set-SimZ1LaunchOutcome $state 'PASSED'; $exitCode = 0
} catch {
    Write-Host "FAIL $Action | $($_.Exception.Message) | $evidence" -ForegroundColor Red
    $state.status = 'failed'; $state.error = $_.Exception.Message
    Set-SimZ1LaunchOutcome $state 'FAILED'
} finally {
    $env:JAVA_HOME = $oldJava; $env:PATH = $oldPath
    if ($held) { $lock.ReleaseMutex() }
    $lock.Dispose()
    Write-SimZ1MassiveJson (Join-Path $evidence 'state.json') $state
}
if ($exitCode -eq 0) { Write-Host "PASS $Action | $evidence" -ForegroundColor Green }
exit $exitCode
