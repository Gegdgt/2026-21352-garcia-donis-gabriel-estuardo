# Explicit versioned experiment entry point, including run1000. No implicit Run.
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Run,
    [switch]$FirstScaleTrial,
    [string]$ExperimentSpec,
    [string]$ExperimentScenario,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$DryRunLaunchId,
    [ValidateSet('automatic_replay_v1','native_diagnostic_v1')][string]$PostprocessingPolicy,
    [string]$SourceConfig = 'scenarios\zona1\od\balanced-gateway-v1\access-review-v2\config-l18-local-v1.xml',
    [string]$FreightService = 'scenarios\zona1\od\balanced-gateway-v1\access-review-v2\freight\service-composition-v3.json',
    [string]$ZoneBoundary = 'scenarios\zona1\od\balanced-gateway-v1\perimeter.geojson',
    [string]$OdAccessCatalog = 'scenarios\zona1\od\balanced-gateway-v1\access.json',
    [string]$OdMixFile = 'scenarios\zona1\od\balanced-gateway-v1\mix.json',
    [string]$JavaHome = 'C:\Program Files\Java\jdk-17',
    [ValidateRange(1,1000)][int]$MinFreeGiB = 100
)
$ErrorActionPreference = 'Stop'
if ($DryRun -and $Run) { throw '-DryRun y -Run son excluyentes.' }
if (-not $DryRun -and -not $Run) {
    Write-Host 'Use -DryRun or -Run with explicit -ExperimentSpec and its declared -ExperimentScenario. Run is manual.'
    exit 0
}
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ExperimentSpec -or -not $ExperimentScenario) {
    throw 'Seleccione explicitamente -ExperimentSpec y un -ExperimentScenario declarado en esa version; no hay fallback generico.'
}
foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile','SourceConfig','FreightService')) {
    $value = Get-Variable -Name $key -ValueOnly
    if (-not [IO.Path]::IsPathRooted($value)) { $value = Join-Path $project $value }
    Set-Variable -Name $key -Value $value
}
$selection=$null
if ($ExperimentSpec) {
    $ExperimentSpec=(Resolve-Path -LiteralPath $ExperimentSpec).Path
    $raw=& (Join-Path $project '.venv/Scripts/python.exe') -B (Join-Path $project 'python/simz1_scale_contract.py') --spec $ExperimentSpec --scenario $ExperimentScenario
    $code=$LASTEXITCODE
    if ($code -ne 0) {exit $code}
    $selection=($raw -join [Environment]::NewLine) | ConvertFrom-Json
} elseif ($ExperimentScenario) {throw 'ExperimentScenario requires ExperimentSpec'}
$options = @{
    MinAgents=180000; MaxAgents=180000; Seed=20261023; JavaHome=$JavaHome;
    MinFreeGiB=$MinFreeGiB; OdMode='balanced-gateway-v1'; ZoneBoundary=$ZoneBoundary;
    OdAccessCatalog=$OdAccessCatalog; OdMixFile=$OdMixFile; DryRun=[bool]$DryRun;
    FirstScaleTrial=[bool]$FirstScaleTrial
    SourceConfig=$SourceConfig; FreightService=$FreightService
}
$options.MinAgents=[int]$selection.total_non_public_vehicles; $options.MaxAgents=$options.MinAgents
$options.Iterations=[int]$selection.iterations
$options.ExperimentSpec=$ExperimentSpec; $options.ExperimentScenario=$ExperimentScenario
$options.DryRunLaunchId=$DryRunLaunchId
$options.PostprocessingPolicy=$PostprocessingPolicy
$options.SQLiteBudgetGiB=8; $options.ScratchBudgetGiB=4
$options.AgentCatalog=Join-Path $project 'scenarios/zona1/agent-types-balanced-v1.json'
. (Join-Path $PSScriptRoot 'run_massive_z1_pasante_10it.ps1')
$code=Invoke-SimZ1MassiveLaunch -Options $options
exit $code
