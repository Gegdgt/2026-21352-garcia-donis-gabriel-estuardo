[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Restore
)
$ErrorActionPreference = 'Stop'
if ($CheckOnly -and $Restore) { throw 'Use -CheckOnly o -Restore, no ambos.' }
$simz1Root = [IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$simz1BackupPath = Join-Path $simz1Root 'evidence/maintenance/replay-tools-rollback.json'
$simz1Backup = Get-Content -LiteralPath $simz1BackupPath -Raw | ConvertFrom-Json
$simz1Allowed = @(
    'open_simz1_continuous.ps1',
    'python/simz1_priority_classification.py',
    'python/simz1_osm_turn_audit.py',
    'python/test_simz1_visual_motion_integration.py',
    'python/check_simz1_continuous_browser.cjs'
)
if ($simz1Backup.schema_version -ne 1 -or
    $simz1Backup.kind -ne 'simz1_replay_tools_migration_rollback' -or
    $simz1Backup.status -ne 'ready_pending_user_validation' -or
    @($simz1Backup.files).Count -ne $simz1Allowed.Count) {
    throw 'Respaldo incompleto o incompatible; no se restaura nada.'
}
$simz1Prepared = @()
$simz1Seen = @{}
foreach ($entry in $simz1Backup.files) {
    if ($entry.path -cnotin $simz1Allowed -or $simz1Seen.ContainsKey($entry.path)) {
        throw 'Ruta inesperada o repetida en el respaldo; no se restaura nada.'
    }
    $simz1Seen[$entry.path] = $true
    $destination = [IO.Path]::GetFullPath((Join-Path $simz1Root $entry.path))
    if (-not $destination.StartsWith($simz1Root + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Destino fuera del proyecto; no se restaura nada.'
    }
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        throw "Falta $($entry.path); no se restaura nada."
    }
    $ancestor = Get-Item -LiteralPath $destination -Force
    while ($null -ne $ancestor) {
        if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Destino con enlace o junction; revisar manualmente antes de restaurar.'
        }
        $ancestor = if ($ancestor -is [IO.FileInfo]) { $ancestor.Directory } else { $ancestor.Parent }
    }
    $bytes = [Convert]::FromBase64String($entry.before_base64)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $beforeHash = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    if ($beforeHash -ne $entry.before_sha256 -or $bytes.Length -ne $entry.before_bytes) {
        throw "Respaldo corrupto de $($entry.path); no se restaura nada."
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $entry.after_sha256) {
        throw "Cambio posterior en $($entry.path); detenerse para no sobrescribir trabajo nuevo."
    }
    $simz1Prepared += [pscustomobject]@{ Path = $destination; RelativePath = $entry.path; Bytes = $bytes }
}
# Every destination and backup is checked before the first write. No deletion,
# Git operation, process termination, audit/run change or new-file cleanup.
if (-not $Restore) {
    Write-Output "Rollback disponible para $($simz1Prepared.Count) archivos; solo lectura. Use -Restore para aplicar."
    $simz1Prepared | Select-Object RelativePath
    return
}
foreach ($entry in $simz1Prepared) {
    [IO.File]::WriteAllBytes($entry.Path, $entry.Bytes)
    Write-Output "Restaurado: $($entry.RelativePath)"
}
Write-Output 'Restaurados los cinco originales. Archivos nuevos, audits y corridas conservados.'
