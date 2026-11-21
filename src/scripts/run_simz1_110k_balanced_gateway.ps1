# Manual entry point. No operation is implied by a missing switch.
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Run,
    [switch]$FirstScaleTrial110k,
    [string]$ZoneBoundary = 'scenarios\zona1\od\balanced-gateway-v1\perimeter.geojson',
    [string]$OdAccessCatalog = 'scenarios\zona1\od\balanced-gateway-v1\access.json',
    [string]$OdMixFile = 'scenarios\zona1\od\balanced-gateway-v1\mix.json',
    [string]$JavaHome = 'C:\Program Files\Java\jdk-17',
    [ValidateRange(1,1000)][int]$MinFreeGiB = 100
)
$ErrorActionPreference = 'Stop'
if ($DryRun -and $Run) { throw '-DryRun y -Run son excluyentes.' }
if (-not $DryRun -and -not $Run) {
    Write-Host 'No se inicio ninguna operacion. Use -DryRun para preflight o -Run para autorizar 110000.'
    Write-Host 'Requiere insumos OD reales y Validate. -FirstScaleTrial110k registra la decision explicita de no hacer Run1000 previo.'
    exit 0
}
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
foreach ($key in @('ZoneBoundary','OdAccessCatalog','OdMixFile')) {
    $value = (Get-Variable -Name $key -ValueOnly)
    if (-not [IO.Path]::IsPathRooted($value)) { $value = Join-Path $project $value }
    Set-Variable -Name $key -Value $value
}
$launchOptions = @{
    MinAgents=110000; MaxAgents=110000; Seed=20261023; JavaHome=$JavaHome;
    MinFreeGiB=$MinFreeGiB; OdMode='balanced-gateway-v1'; ZoneBoundary=$ZoneBoundary;
    OdAccessCatalog=$OdAccessCatalog; OdMixFile=$OdMixFile; DryRun=[bool]$DryRun;
    FirstScaleTrial110k=[bool]$FirstScaleTrial110k
}
# The shared launcher retains its mutex, JDK17, memory/disk, source, trial,
# preflight and native acceptance gates. It never auto-runs after -DryRun.
& (Join-Path $PSScriptRoot 'run_massive_z1_pasante_1it.ps1') @launchOptions
exit $LASTEXITCODE
