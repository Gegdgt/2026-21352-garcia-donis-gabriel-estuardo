# Explicit experimental scenario, shared locking/preflight/acceptance/closure.
[CmdletBinding()]
param(
    [ValidateRange(0,220000)][int]$MinAgents = 220000,
    [ValidateRange(0,220000)][int]$MaxAgents = 220000,
    [ValidateSet('network','balanced-gateway-v1')][string]$OdMode = 'network',
    [string]$ZoneBoundary,
    [string]$OdAccessCatalog,
    [string]$OdMixFile,
    [string]$ExperimentSpec,
    [string]$ExperimentScenario,
    [string]$SourceConfig,
    [string]$FreightService,
    [ValidateRange(0,2147483647)][int]$Seed = 20261023,
    [string]$JavaHome = 'C:\Program Files\Java\jdk-17',
    [ValidateRange(1,1000)][int]$MinFreeGiB = 100,
    [ValidateRange(1,500)][int]$SQLiteBudgetGiB = 8,
    [ValidateRange(1,500)][int]$ScratchBudgetGiB = 4,
    [switch]$DryRun,
    [switch]$FirstScaleTrial110k,
    [switch]$FirstScaleTrial
)
if (-not $ExperimentSpec -or -not $ExperimentScenario) { throw 'Use explicit ExperimentSpec/ExperimentScenario; no generic experiment fallback.' }
if ($MinAgents -ne $MaxAgents) { throw 'One-iteration experiments require exact N from their versioned selector.' }
if ($MinAgents -eq 110000 -and $OdMode -ne 'balanced-gateway-v1') { throw '110000 requiere -OdMode balanced-gateway-v1; use run_simz1_110k_balanced_gateway.ps1.' }
if ($OdMode -eq 'network' -and ($ZoneBoundary -or $OdAccessCatalog -or $OdMixFile)) { throw 'Network no acepta opciones OD ignoradas.' }
$oneIterationOptions = @{
        MinAgents=$MinAgents; MaxAgents=$MaxAgents; Seed=$Seed; Iterations=1;
        JavaHome=$JavaHome; MinFreeGiB=$MinFreeGiB; SQLiteBudgetGiB=$SQLiteBudgetGiB;
        ScratchBudgetGiB=$ScratchBudgetGiB; DryRun=[bool]$DryRun; FirstScaleTrial110k=[bool]$FirstScaleTrial110k;
        FirstScaleTrial=[bool]$FirstScaleTrial;
        OdMode=$OdMode; ZoneBoundary=$ZoneBoundary; OdAccessCatalog=$OdAccessCatalog; OdMixFile=$OdMixFile;
        SourceConfig=$SourceConfig; FreightService=$FreightService;
        ExperimentSpec=$ExperimentSpec; ExperimentScenario=$ExperimentScenario;
        AgentCatalog=(Join-Path $PSScriptRoot '..\scenarios\zona1\agent-types-balanced-v1.json');
        DestinationPolicy='lane-length-destinations-v1'; ShortLinkSignalCoordination='derive-activity-v2'
    }
. (Join-Path $PSScriptRoot 'run_massive_z1_pasante_10it.ps1')
$script:SimZ1MassiveScriptPath = $PSCommandPath
try { $launchCode = Invoke-SimZ1MassiveLaunch -Options $oneIterationOptions; exit $launchCode } catch { Write-Error -Message $_.Exception.Message -ErrorAction Continue; exit 1 }
