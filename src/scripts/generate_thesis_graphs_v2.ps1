[CmdletBinding()]
param(
    [switch]$ForceFigures,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Falta .venv\Scripts\python.exe' }
$logs = Join-Path $project 'graficas_tesis_v2\logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $logs "collection-$stamp.log"
$argsList = @('-X', 'utf8', '-B', '-u', (Join-Path $project 'python\simz1_thesis_collection_v2.py'))
if ($ForceFigures) { $argsList += '--force-figures' }
if ($VerifyOnly) { $argsList += '--verify-only' }
Push-Location -LiteralPath $project
try {
    $ErrorActionPreference = 'Continue'
    & $python @argsList 2>&1 | Tee-Object -FilePath $log
    $collectionExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $collectionExit | Set-Content -LiteralPath (Join-Path $logs "collection-$stamp.exit.txt")
    if ($collectionExit -ne 0) { throw "Colección rechazada ($collectionExit). Revisar $log. No ejecutar simulación." }
    Write-Host "Colección disponible: $project\graficas_tesis_v2\INDICE_GENERAL.md"
} finally {
    Pop-Location
}
