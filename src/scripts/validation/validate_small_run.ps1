<#
Manual SimZ1 validation in three explicit stages; nothing runs when this file is read.
Run: exactly 10 people, 10 planned trips, iteration 0, fixed seeds and a 24-hour day.
Analyze: the existing graph CLI also exports events/trip metrics once.
Export: existing source exporter, continuous exporter, then launcher -CheckOnly.
No server/browser, cleanup, source-config edits or massive generation in this script.
Invoke each stage from PowerShell and review its result before continuing.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Run', 'Analyze', 'Export')]
    [string]$Stage,
    [Parameter(Mandatory = $true)]
    [string]$RunDir,
    [string]$Maven
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$simz1Project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$simz1Python = Join-Path $simz1Project '.venv\Scripts\python.exe'
$simz1Master = Join-Path $simz1Project 'scenarios\zona1\config-simz1.xml'
$simz1RunRoot = [IO.Path]::GetFullPath((Join-Path $simz1Project 'scenarios\zona1\montecarlo'))
$simz1ProtectedId = 'simz1-3dd8683a7d5e44c0944587feff4fe0c8'
$simz1Protected = Join-Path $simz1RunRoot 'run-052734f90d154b23bb8899cd0bbc3ef4'
$simz1ProtectedManifest = Join-Path $simz1Protected 'run-manifest.json'
$simz1ProtectedHash = 'a1a64936c5fe8f9115de85c850bca04953a5fb026c12c1d6986c18a8528ee03d'
$simz1Directory = if ([IO.Path]::IsPathRooted($RunDir)) {
    [IO.Path]::GetFullPath($RunDir)
} else {
    [IO.Path]::GetFullPath((Join-Path $simz1Project $RunDir))
}
$simz1Directory = $simz1Directory.TrimEnd([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar))

function Assert-NoReparsePath([string]$Path) {
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $entry = Get-Item -LiteralPath $current -Force
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point: $current. Detenerse; no se siguen enlaces."
            }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Read-LocalXml([string]$Path) {
    # Config files contain a MATSim DOCTYPE; do not resolve an external DTD here.
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Ignore
    $settings.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create($Path, $settings)
    try {
        $document = New-Object System.Xml.XmlDocument
        $document.XmlResolver = $null
        $document.Load($reader)
        return ,$document
    } finally { $reader.Dispose() }
}

function Get-ConfigValue($Document, [string]$Module, [string]$Name) {
    $node = $Document.SelectSingleNode("/config/module[@name='$Module']/param[@name='$Name']")
    if ($null -eq $node) { throw "Falta $Module.$Name en la configuracion." }
    return $node.GetAttribute('value')
}

function Get-TimeSeconds([string]$Value) {
    if ($Value -match '^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$') {
        return ([double]$Matches[1] * 3600 + [double]$Matches[2] * 60 +
            [double]::Parse($Matches[3], [Globalization.CultureInfo]::InvariantCulture))
    }
    return [double]::Parse($Value, [Globalization.CultureInfo]::InvariantCulture)
}

function Assert-Configuration([string]$Path, [switch]$Executed) {
    $document = Read-LocalXml $Path
    foreach ($pair in @(@('qsim','useLanes'), @('signalsystems','useSignalsystems'),
                       @('zona1Priority','enabled'), @('zona1WithinDayRouting','enabled'))) {
        if ((Get-ConfigValue $document $pair[0] $pair[1]) -ne 'true') {
            throw "Se requiere $($pair -join '.')=true; no se modifica el XML maestro."
        }
    }
    if ((Get-ConfigValue $document 'zona1WithinDayRouting' 'routingPolicy') -ne 'fastest-time') {
        throw 'Se requiere routingPolicy=fastest-time; no existe --routing-policy.'
    }
    if ((Get-TimeSeconds (Get-ConfigValue $document 'qsim' 'startTime')) -ne 0 -or
        (Get-TimeSeconds (Get-ConfigValue $document 'qsim' 'endTime')) -ne 86400) {
        throw 'QSim debe cubrir exactamente 0..86400 s.'
    }
    if ($Executed -and ((Get-ConfigValue $document 'controler' 'firstIteration') -ne '0' -or
                       (Get-ConfigValue $document 'controler' 'lastIteration') -ne '0')) {
        throw 'La copia efectiva debe tener solamente la iteracion 0.'
    }
}

function Invoke-SimZ1Python([string[]]$Arguments) {
    & $simz1Python -B @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Etapa fallida (codigo $LASTEXITCODE). Conservar $simz1Directory y detenerse."
    }
}

function Get-ValidatedSmallRun {
    $manifest = Get-Content -LiteralPath (Join-Path $simz1Directory 'run-manifest.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($manifest.run_id -eq $simz1ProtectedId -or $manifest.run_id -notmatch '^simz1-[0-9a-f]{32}$' -or
        [IO.Path]::GetFullPath($manifest.folder) -ne $simz1Directory) {
        throw 'Identidad o directorio de corrida incompatible.'
    }
    if ($manifest.status -ne 'completed' -or $manifest.validation.status -ne 'valid') {
        throw 'Se requiere completed/valid; no se reanuda una corrida fallida.'
    }
    if ($manifest.counts.planned_persons -ne 10 -or $manifest.counts.planned_trips -ne 10 -or
        $manifest.demand_seed -ne 20261016 -or $manifest.matsim_seed -ne 20261016) {
        throw 'Se requieren 10 personas, 10 viajes y ambas semillas 20261016.'
    }
    if ($manifest.time_horizon.start_seconds -ne 0 -or $manifest.time_horizon.end_seconds -ne 86400 -or
        $manifest.demand_window.start_seconds -ne 0 -or $manifest.demand_window.end_seconds -ne 86400 -or
        $manifest.demand_window.end_exclusive -ne $true -or
        $manifest.temporal_demand.profile -ne 'full-day' -or $manifest.temporal_demand.drain_seconds -ne 0 -or
        $manifest.temporal_demand.trips_per_person -ne 1) {
        throw 'Contrato temporal distinto de demanda [0,86400), drain=0 y un viaje por persona.'
    }
    if ($manifest.iterations.first -ne 0 -or $manifest.iterations.last -ne 0 -or
        $manifest.iterations.requested -ne 1 -or @($manifest.iterations.completed).Count -ne 1 -or
        $manifest.iterations.completed[0] -ne 0) {
        throw 'Se requiere exactamente una iteracion completada: 0.'
    }
    Assert-Configuration (Join-Path $simz1Directory 'config-simz1.xml') -Executed
    Assert-Configuration (Join-Path $simz1Directory 'output\output_config.xml') -Executed
    return $manifest
}

if ([IO.Path]::GetDirectoryName($simz1Directory) -ne $simz1RunRoot -or
    [IO.Path]::GetFileName($simz1Directory) -notlike 'run-*' -or
    $simz1Directory -eq $simz1Protected) {
    throw 'Usar una carpeta run-* nueva directamente bajo scenarios/zona1/montecarlo; nunca la protegida.'
}
Assert-NoReparsePath $simz1Directory
Assert-NoReparsePath $simz1ProtectedManifest
if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { throw 'Preparar .venv antes de continuar.' }
$simz1HasProtectedFixture = Test-Path -LiteralPath $simz1ProtectedManifest -PathType Leaf
if ($simz1HasProtectedFixture -and
    (Get-FileHash -LiteralPath $simz1ProtectedManifest -Algorithm SHA256).Hash -ne $simz1ProtectedHash) {
    throw 'El manifiesto protegido difiere de la referencia revisada; detenerse.'
}
if (-not $simz1HasProtectedFixture) {
    Write-Warning 'Fixture 100k ausente: esta prueba pequena no acredita su conservacion ni lo regenera.'
}
$simz1MasterHash = (Get-FileHash -LiteralPath $simz1Master -Algorithm SHA256).Hash
Push-Location -LiteralPath $simz1Project
try {
    if ($Stage -eq 'Run') {
        if (Test-Path -LiteralPath $simz1Directory) { throw 'La carpeta ya existe; no se sobrescribe ni reanuda.' }
        Assert-Configuration $simz1Master
        if ([string]::IsNullOrWhiteSpace($env:JAVA_HOME)) { throw 'Configurar JAVA_HOME con JDK 25.' }
        $release = Get-Content -LiteralPath (Join-Path $env:JAVA_HOME 'release') -Raw
        if ($release -notmatch '(?m)^JAVA_VERSION="25(?:[.\-+][^"]*)?"') { throw 'JAVA_HOME debe apuntar a JDK 25.' }
        if (-not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\javac.exe') -PathType Leaf)) {
            throw 'Falta javac.exe: se necesita JDK, no solamente JRE.'
        }
        if (-not $Maven) {
            $Maven = if (Test-Path -LiteralPath '.\.mvn\wrapper\maven-wrapper.jar') {
                (Resolve-Path -LiteralPath '.\mvnw.cmd').Path
            } else { (Get-Command mvn.cmd -ErrorAction Stop).Source }
        }
        $Maven = (Resolve-Path -LiteralPath $Maven).Path
        Write-Host "Corrida nueva: $simz1Directory"
        Invoke-SimZ1Python -Arguments @(
            'python/ejecutar_simz1.py', '--config', $simz1Master, '--maven', $Maven,
            '--run-dir', $simz1Directory, '--mode', 'montecarlo', '--od-mode', 'network',
            '--agents', '10', '--trips-per-person', '1', '--iterations', '1',
            '--seed', '20261016', '--matsim-seed', '20261016',
            '--corridor-policy', 'redistribute', '--temporal-profile', 'full-day', '--drain-seconds', '0',
            '--use-lanes', '--signals', '--unsignalized-priority', '--within-day-routing',
            '--signal-offset-policy', 'preserve'
        )
    }
    $manifest = Get-ValidatedSmallRun
    if ($Stage -eq 'Analyze') {
        $analysis = Join-Path $simz1Directory 'analysis'
        Assert-NoReparsePath $analysis
        if (Test-Path -LiteralPath $analysis) {
            throw 'Ya existe analysis; conservarlo y revisar antes de repetir esta etapa.'
        }
        # This CLI already processes events/compact trip products and draws distributions.
        Invoke-SimZ1Python -Arguments @('python/generar_graficas_z1.py', '--run-dir', $simz1Directory,
                            '--iteration', '0', '--mode', 'car')
        foreach ($name in @('trips.csv.gz', 'trips.csv.provenance.json', 'duration_distribution.png',
                           'profile_hour_distribution.png', 'percentiles_profile_hour.csv', 'distribution_summary.json')) {
            if (-not (Test-Path -LiteralPath (Join-Path $simz1Directory "analysis\it.0\$name") -PathType Leaf)) {
                throw "Falta producto esperado: $name. Detenerse."
            }
        }
    }
    if ($Stage -eq 'Export') {
        $source = Join-Path $simz1Directory 'webgl'
        $continuous = Join-Path $simz1Directory 'webgl-continuo'
        if ((Test-Path -LiteralPath $source) -or (Test-Path -LiteralPath $continuous)) {
            throw 'Ya existe un export; conservarlo y revisar antes de repetir esta etapa.'
        }
        # 24 internal source blocks, reused by one continuous page with 720 API windows.
        Invoke-SimZ1Python -Arguments @('python/visualizador_z1.py', '--run-dir', $simz1Directory,
                            '--iteration', '0', '--paged', '--output', (Join-Path $source 'index.html'),
                            '--window-seconds', '3600', '--replay-start', '0', '--replay-end', '86400')
        Invoke-SimZ1Python -Arguments @('python/simz1_continuous_replay.py', '--source', $source,
                            '--output', $continuous, '--window-seconds', '120', '--start', '0', '--end', '86400')
        # The existing generic launcher validates identity and hashes without serving.
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\replay\start_replay.ps1' `
            -RunDir $simz1Directory -Iteration 0 -ReplayDir $continuous -CheckOnly
        if ($LASTEXITCODE -ne 0) { throw 'Replay incompatible; detenerse y conservar los exports.' }
    }
    [pscustomobject]@{
        Stage = $Stage; RunId = $manifest.run_id; RunDir = $simz1Directory
        Persons = $manifest.counts.planned_persons; Trips = $manifest.counts.planned_trips
        DemandSeed = $manifest.demand_seed; MatsimSeed = $manifest.matsim_seed
        HorizonSeconds = '0..86400'; Iteration = 0
    } | Format-List
    if ($Stage -eq 'Run') {
        Write-Host 'El launcher publica latest-successful para esta nueva corrida; la carpeta 100k se conserva.'
    }
} finally {
    Pop-Location
    if ((Get-FileHash -LiteralPath $simz1Master -Algorithm SHA256).Hash -ne $simz1MasterHash -or
        ($simz1HasProtectedFixture -and
         (Get-FileHash -LiteralPath $simz1ProtectedManifest -Algorithm SHA256).Hash -ne $simz1ProtectedHash)) {
        throw 'Cambio inesperado de configuracion maestra o manifiesto protegido. Detenerse y reportar.'
    }
}
