<#
SimZ1 historical-network subset. Full requested physical feature set is BLOCKED.
Default: regressions, fresh isolated build, new demand, MATSim, full validation.
-PrepareOnly: the same preflight/build/regressions, then a launch plan; NO demand
generation or MATSim. Never resumes/deletes old runs or starts replay services.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 2500000)][int]$MinAgents = 150000,
    [ValidateRange(1, 2500000)][int]$MaxAgents = 250000,
    [ValidateRange(0, 2147483647)][int]$Seed = 20261022,
    [switch]$PrepareOnly,
    [ValidateRange(4, 100000)][double]$MinimumFreeGiB = 64
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$simz1Root = Split-Path $PSScriptRoot -Parent
$simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
$simz1Helper = Join-Path $PSScriptRoot 'validation\simz1_massive_contract.py'
$simz1Maven = Join-Path $simz1Root 'mvnw.cmd'
$simz1Master = Join-Path $simz1Root 'scenarios\zona1\config-simz1.xml'
$simz1Workspace = Join-Path $simz1Root ('scenarios\zona1\montecarlo\verified-' + [guid]::NewGuid().ToString('N'))
$simz1Run = Join-Path $simz1Workspace ('run-' + [guid]::NewGuid().ToString('N'))
$simz1Build = Join-Path $simz1Workspace 'build'
$simz1Verification = Join-Path $simz1Workspace 'verification'
$simz1StatePath = Join-Path $simz1Workspace 'verified-launch.json'
$simz1State = [ordered]@{
    schema = 'simz1-massive-launch-v1'; status = 'preflight'; full_requested_feature_set = 'BLOCKED'
    scenario_mode = 'historical-network-subset'; simulation_executed = $false
    min_agents = $MinAgents; max_agents = $MaxAgents; seed = $Seed; qsim_threads = 4
    run_directory = $simz1Run; workspace = $simz1Workspace; prepare_only = [bool]$PrepareOnly
    started_utc = [DateTime]::UtcNow.ToString('o'); minimum_free_gib = $MinimumFreeGiB
    physical_validity_proven = $false; paged_html_generated = $false
}
$simz1Lock = $null

function Write-LaunchState {
    $json = $simz1State | ConvertTo-Json -Depth 16
    [IO.File]::WriteAllText($simz1StatePath, $json, [Text.UTF8Encoding]::new($false))
}

function Assert-NoReparsePath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point en destino: $current. No se siguen enlaces hacia otras corridas."
            }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Assert-NoDestinationUsers([string[]]$Paths) {
    # Fail closed if Windows does not permit inspecting command lines. Never kill
    # an existing process. The GUID and exclusive lock additionally prevent reuse.
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($process in $processes) {
        if ($process.ProcessId -eq $PID) { continue }
        if (-not $process.CommandLine) {
            if ($process.Name -match '^(javaw?|pythonw?|mvn|maven)(\.exe)?$') {
                throw "No se puede inspeccionar el proceso $($process.ProcessId) ($($process.Name)); destinos no verificados."
            }
            continue
        }
        foreach ($path in $Paths) {
            if ($process.CommandLine.IndexOf($path, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                $process.CommandLine.Replace('/', '\').IndexOf($path.Replace('/', '\'), [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                throw "El proceso $($process.ProcessId) ($($process.Name)) utiliza el destino $path."
            }
        }
    }
}

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$Log) {
    $null = Get-Command $File -ErrorAction Stop
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell wraps native stderr as ErrorRecord even for successful
        # java -version. Exit code, not stderr presence, is the success criterion.
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = 0
        & $File @Arguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log | Out-Host
        $code = $global:LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($null -eq $code -or $code -ne 0) { throw "Fallo ($code): $File. Revisar $Log" }
    if ((Get-Content -LiteralPath $Log -Raw) -match 'An exception has occurred in the compiler') {
        throw "Excepcion interna de javac; no se aceptan clases parciales. Revisar $Log"
    }
}

function Invoke-Contract([string[]]$Arguments, [string]$Output) {
    $text = & $simz1Python -B $simz1Helper @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Contrato SimZ1 rechazado: $($Arguments[0])" }
    $json = $text -join [Environment]::NewLine
    $parsed = $json | ConvertFrom-Json
    [IO.File]::WriteAllText($Output, $json, [Text.UTF8Encoding]::new($false))
    return $parsed
}

function Get-ActualDiskSpace([string[]]$Paths) {
    # Query the volume that actually contains each path, including the TEMP and
    # dependency-cache locations. No assumed C:/D: drive layout or size estimate.
    if (-not ('SimZ1Volume.Native' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace SimZ1Volume {
 public static class Native {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool GetVolumePathName(string path, StringBuilder volume, uint length);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool GetDiskFreeSpaceEx(string path, out ulong available, out ulong total, out ulong free);
 }
}
'@
    }
    foreach ($path in ($Paths | Select-Object -Unique)) {
        $existing = [IO.Path]::GetFullPath($path)
        while (-not (Test-Path -LiteralPath $existing)) { $existing = [IO.Path]::GetDirectoryName($existing) }
        if (Test-Path -LiteralPath $existing -PathType Leaf) { $existing = [IO.Path]::GetDirectoryName($existing) }
        $volume = New-Object Text.StringBuilder 1024
        [UInt64]$available = 0; [UInt64]$total = 0; [UInt64]$free = 0
        if (-not [SimZ1Volume.Native]::GetVolumePathName($existing, $volume, 1024) -or
            -not [SimZ1Volume.Native]::GetDiskFreeSpaceEx($existing, [ref]$available, [ref]$total, [ref]$free)) {
            throw "No se pudo comprobar espacio real de $existing"
        }
        [pscustomobject]@{path=$path; actual_volume=$volume.ToString(); available_bytes=$available; total_bytes=$total}
    }
}

function Assert-DiskReserve($Volumes) {
    foreach ($group in ($Volumes | Group-Object actual_volume)) {
        $volume = $group.Group | Sort-Object available_bytes | Select-Object -First 1
        Write-Host ('Disco {0}: {1:N1} GiB libres ({2} rutas comprobadas)' -f $volume.actual_volume, ($volume.available_bytes / 1GB), $group.Count)
        if ($volume.available_bytes -lt ($MinimumFreeGiB * 1GB)) {
            throw "Espacio insuficiente en $($volume.actual_volume): reserva minima $MinimumFreeGiB GiB."
        }
    }
}

if ($MinAgents -gt $MaxAgents) { throw 'MinAgents debe ser <= MaxAgents.' }
foreach ($file in @($simz1Python, $simz1Helper, $simz1Maven, $simz1Master)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Archivo requerido ausente: $file" }
}
Assert-NoReparsePath $simz1Workspace
if (Test-Path -LiteralPath $simz1Workspace) { throw 'El destino GUID ya existe; no se reanuda.' }
Assert-NoDestinationUsers @($simz1Workspace, $simz1Run, $simz1Build)
New-Item -ItemType Directory -Path $simz1Verification | Out-Null
Push-Location -LiteralPath $simz1Root
try {
    $simz1Lock = [IO.File]::Open((Join-Path $simz1Workspace '.launch.lock'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    Write-LaunchState
    Write-Warning 'BLOCKED: conjunto fisico completo. Se prepara solo network historico, motos/carros, strict, semaforos y carriles configurados.'
    Write-Warning 'Desactivados: accidentes, bloqueo1800s, pesados, flota publica y cambios fisicos de carril. Giros OSM y limites no acreditados.'
    if ($MaxAgents -gt 250000) { Write-Warning 'Escala experimental >250000: sin garantia de RAM, disco, duracion, estabilidad o finalizacion de viajes.' }
    if ([string]::IsNullOrWhiteSpace($env:JAVA_HOME)) { throw 'JAVA_HOME debe apuntar a JDK 25.' }
    $simz1Java = Join-Path $env:JAVA_HOME 'bin\java.exe'
    $simz1Javac = Join-Path $env:JAVA_HOME 'bin\javac.exe'
    foreach ($file in @($simz1Java, $simz1Javac)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "JDK incompleto: $file" }
    }
    if ((Get-Content -LiteralPath (Join-Path $env:JAVA_HOME 'release') -Raw) -notmatch '(?m)^JAVA_VERSION="25(?:[.\-+][^"]*)?"') {
        throw 'Se requiere JDK 25 exacto (version principal).'
    }
    Invoke-Checked $simz1Java @('-version') (Join-Path $simz1Verification 'java-version.log')
    Invoke-Checked $simz1Javac @('-version') (Join-Path $simz1Verification 'javac-version.log')
    Invoke-Checked $simz1Maven @('--offline', '--version') (Join-Path $simz1Verification 'maven-version.log')
    if ((Get-Content -LiteralPath (Join-Path $simz1Verification 'maven-version.log') -Raw) -notmatch 'Java version: 25(?:[.,\s])') {
        throw 'Maven no esta usando JDK 25.'
    }
    $simz1Node = (Get-Command node.exe -ErrorAction Stop).Source
    Invoke-Checked $simz1Node @('--version') (Join-Path $simz1Verification 'node-version.log')
    Invoke-Checked $simz1Python @('-B', '-c', 'import sys,sqlite3,numpy,pandas,matplotlib; assert sys.prefix != sys.base_prefix; print(sys.version); print(sys.executable); print(sqlite3.sqlite_version)') (Join-Path $simz1Verification 'python-version.log')
    $simz1State['initial_volumes'] = @(Get-ActualDiskSpace @($simz1Workspace, [IO.Path]::GetTempPath()))
    Assert-DiskReserve $simz1State.initial_volumes
    Invoke-Checked 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'validation\test_simz1_massive_launcher.ps1')) (Join-Path $simz1Verification 'powershell-contracts.log')
    $build = Invoke-Contract @('build-files', '--directory', $simz1Build, '--maven', $simz1Maven) (Join-Path $simz1Verification 'build-files.json')
    $preflightPath = Join-Path $simz1Verification 'preflight.json'
    $preflight = Invoke-Contract @('preflight', '--config', $simz1Master, '--agent-catalog', $build.catalog, '--min-agents', "$MinAgents", '--max-agents', "$MaxAgents", '--seed', "$Seed", '--qsim-threads', '4') $preflightPath
    $simz1State['preflight'] = $preflight
    $simz1State['build'] = $build
    $simz1State['status'] = 'regressions'
    Write-LaunchState
    $classpathFile = Join-Path $simz1Verification 'dependencies.txt'
    Invoke-Checked $build.wrapper @('--offline', '--batch-mode', '--no-transfer-progress', 'dependency:build-classpath', "-Dmdep.outputFile=$classpathFile") (Join-Path $simz1Verification 'dependencies.log')
    $dependencyPaths = (Get-Content -LiteralPath $classpathFile -Raw).Trim().Split([IO.Path]::PathSeparator)
    $simz1State['dependency_volumes'] = @(Get-ActualDiskSpace $dependencyPaths)
    Assert-DiskReserve $simz1State.dependency_volumes
    Invoke-Checked $build.wrapper @('--offline', '--batch-mode', '--no-transfer-progress', 'compile') (Join-Path $simz1Verification 'fresh-compile.log')
    $regressionEvidence = Join-Path $simz1Verification 'regression-build.json'
    Invoke-Checked 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $simz1Root 'check_simz1_lane_policy.ps1'), '-DependencyClasspathFile', $classpathFile, '-JavaExecutable', $simz1Java, '-JavacExecutable', $simz1Javac, '-BuildRoot', $simz1Verification, '-EvidenceFile', $regressionEvidence) (Join-Path $simz1Verification 'regressions.log')
    $evidence = Get-Content -LiteralPath $regressionEvidence -Raw | ConvertFrom-Json
    $receipt = Get-Content -LiteralPath $evidence.manifest -Raw | ConvertFrom-Json
    if ($receipt.simulation_executed -ne $false -or $receipt.checks -notcontains 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1AdmissionConcurrencyCheck') {
        throw 'Falta comprobante exitoso de concurrencia; no se habilitan cuatro hilos.'
    }
    # The launcher's Maven build must contain byte-identical production classes
    # to the independent fresh build used by the native regression fixtures.
    $simz1ClassHashes = [ordered]@{}
    foreach ($prefix in @('gt\edu\uvg\sim\zona1', 'org\matsim\core\mobsim\qsim\qnetsimengine')) {
        foreach ($class in (Get-ChildItem -LiteralPath (Join-Path $build.classes $prefix) -Filter '*.class' -Recurse)) {
            $relative = $class.FullName.Substring($build.classes.Length + 1)
            $tested = Join-Path $evidence.classes $relative
            $hash = (Get-FileHash -LiteralPath $class.FullName -Algorithm SHA256).Hash
            if (-not (Test-Path -LiteralPath $tested -PathType Leaf) -or $hash -ne (Get-FileHash -LiteralPath $tested -Algorithm SHA256).Hash) {
                throw "Las clases del launcher difieren de las probadas: $relative"
            }
            $simz1ClassHashes[$relative] = $hash.ToLowerInvariant()
        }
    }
    if ($simz1ClassHashes.Count -eq 0) { throw 'No se compilaron clases SimZ1.' }
    $simz1State['production_class_sha256'] = $simz1ClassHashes
    $simz1State['regression_receipt'] = $evidence.manifest
    foreach ($suite in @('simz1_massive_contract', 'simz1_road_profiles', 'simz1_incident_configuration', 'simz1_replay_launch', 'simz1_sqlite_source', 'simz1_journey_lanes')) {
        Invoke-Checked $simz1Python @('-B', '-m', 'unittest', 'discover', '-s', 'python', '-p', "test_$suite.py", '-v') (Join-Path $simz1Verification "$suite.log")
        if ((Get-Content -LiteralPath (Join-Path $simz1Verification "$suite.log") -Raw) -match 'Ran 0 tests') { throw "Suite vacia: $suite" }
    }
    foreach ($suite in @('arrival_effects', 'signal_geometry', 'vehicle_dimensions', 'body_spacing', 'selected_route', 'continuous_replay')) {
        Invoke-Checked $simz1Node @("python/test_simz1_$suite.cjs") (Join-Path $simz1Verification "$suite.log")
    }
    $null = Invoke-Contract @('verify-sources', '--preflight', $preflightPath) (Join-Path $simz1Verification 'sources-before-launch.json')
    $simz1Arguments = @('-B', 'python/ejecutar_simz1.py') + @($preflight.launcher_arguments) +
        @('--maven', $build.wrapper, '--offline', '--run-dir', $simz1Run)
    $simz1State['executable'] = $simz1Python
    $simz1State['arguments'] = $simz1Arguments
    $simz1State['prelaunch_volumes'] = @(Get-ActualDiskSpace @($simz1Workspace, [IO.Path]::GetTempPath()))
    Assert-DiskReserve $simz1State.prelaunch_volumes
    Assert-NoDestinationUsers @($simz1Run, $simz1Build)
    if (Test-Path -LiteralPath $simz1Run) { throw 'La carpeta de corrida ya existe; no se reanuda.' }
    Write-Host 'Nativo: strict WAIT, cuatro hilos probados, semaforos/carriles configurados, perfiles moto/carro. Incidentes OFF.'
    Write-Host 'Visual al exportar replay: parada/separacion reconstruidas y llegada5000ms reales. Sin prueba de seguimiento fisico continuo.'
    if ($PrepareOnly) {
        $simz1State['status'] = 'prepared_verified_plan'
        Write-Host "Plan verificado sin generar poblacion ni ejecutar MATSim: $simz1StatePath"
    } else {
        $simz1State['status'] = 'running'
        $simz1State['simulation_executed'] = $true
        Write-LaunchState
        Invoke-Checked $simz1Python $simz1Arguments (Join-Path $simz1Workspace 'launcher.log')
        $simz1State['status'] = 'validating'
        Write-LaunchState
        $simz1State['result_validation'] = Invoke-Contract @('verify-run', '--run-dir', $simz1Run, '--preflight', $preflightPath) (Join-Path $simz1Verification 'result.json')
        $null = Invoke-Contract @('verify-sources', '--preflight', $preflightPath) (Join-Path $simz1Verification 'sources-after-launch.json')
        $simz1State['status'] = 'completed_validated_subset'
        Write-Host "Subconjunto historico validado: $simz1Run. Conjunto fisico completo: BLOCKED."
    }
} catch {
    $simz1State['status'] = 'failed'
    $simz1State['error'] = $_.Exception.Message
    throw
} finally {
    $simz1State['finished_utc'] = [DateTime]::UtcNow.ToString('o')
    Write-LaunchState
    if ($null -ne $simz1Lock) { $simz1Lock.Dispose() }
    Pop-Location
}
