[CmdletBinding()]
param(
    [string]$RunDir,
    [Nullable[int]]$Iteration,
    [string]$ReplayDir,
    [ValidateSet('partial-native-v1')][string]$VisualPolicy,
    [ValidateRange(1,65535)][int]$Port = 8792,
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$ReplaceSimZ1
)
$ErrorActionPreference = 'Stop'
$simz1Project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$simz1Python = Join-Path $simz1Project '.venv/Scripts/python.exe'
$simz1Launcher = Join-Path $PSScriptRoot 'start_replay.py'
if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) {
    throw 'Falta .venv/Scripts/python.exe del proyecto; no se instala ni genera nada automaticamente.'
}
$simz1Arguments = @('-B', $simz1Launcher, '--port', [string]$Port)
if ($RunDir) { $simz1Arguments += @('--run-dir', $RunDir) }
if ($PSBoundParameters.ContainsKey('Iteration')) {
    $simz1Arguments += @('--iteration', [string]$Iteration)
}
if ($ReplayDir) { $simz1Arguments += @('--replay-dir', $ReplayDir) }
if ($VisualPolicy) { $simz1Arguments += @('--visual-policy', $VisualPolicy) }
if ($NoBrowser) { $simz1Arguments += '--no-browser' }
if ($CheckOnly) { $simz1Arguments += '--check-only' }
if ($ReplaceSimZ1) { $simz1Arguments += '--replace-simz1' }
# Foreground only: Python owns its server object and closes it on Ctrl+C.
# ReplaceSimZ1 additionally verifies the current PID/command/start time and
# served manifest before replacing a different local SimZ1 listener.
& $simz1Python @simz1Arguments
$simz1ExitCode=$LASTEXITCODE
if ($simz1ExitCode -ne 0) {
    throw "El launcher termino con codigo $simz1ExitCode; conservar runtime/replay y revisar el error."
}
