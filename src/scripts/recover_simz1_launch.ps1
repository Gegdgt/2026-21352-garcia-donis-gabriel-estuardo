# Recover only closure/postprocessing of an explicit failed launch. Never QSim.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$LaunchId,
    [Parameter(Mandatory=$true)][string]$ReviewedTransition,
    [switch]$ResumeNativeValidation
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'run_massive_z1_pasante_10it.ps1')
$mutex = New-SimZ1MassiveLock $project
$held = $false
try {
    try { $held=$mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $held=$true }
    if (-not $held) { throw 'Another SimZ1 launch/recovery owns the mutex.' }
    if (@(Get-SimZ1MassiveWriters).Count) { throw 'An existing native/preparation writer is active; no process was stopped.' }
    $prior = Get-Content -LiteralPath (Join-Path $project "runtime\launches\$LaunchId\state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $requiredGiB = [Math]::Max(100, [double]$prior.required_free_gib)
    if ((Get-SimZ1MassiveFreeBytes $project) -lt ($requiredGiB * 1GB)) { throw 'Recovery disk guard rejected; retain evidence.' }
    $action = if ($ResumeNativeValidation) { 'recover-pending' } else { 'recover' }
    & (Join-Path $project '.venv\Scripts\python.exe') -B (Join-Path $project 'python\simz1_launch_recovery.py') $action --launch-id $LaunchId --reviewed-transition $ReviewedTransition
    $rc=$LASTEXITCODE
    exit $rc
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
