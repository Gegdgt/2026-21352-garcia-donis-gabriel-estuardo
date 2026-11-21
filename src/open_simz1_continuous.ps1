# Compatibility path only. All selection, validation and serving live in scripts/replay.
param(
    [string]$RunDir,
    [Nullable[int]]$Iteration,
    [string]$ReplayDir,
    [ValidateRange(1,65535)][int]$Port = 8792,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts/replay/start_replay.ps1') @PSBoundParameters
