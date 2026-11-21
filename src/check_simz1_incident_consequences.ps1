# Pure contract checks. Never runs Controler/QSim, servers or browsers.
[CmdletBinding()]
param(
    [string]$DependencyClasspathFile = 'target/simz1-storage-classpath.txt',
    [string]$JavaExecutable = 'java',
    [string]$JavacExecutable = 'javac'
)
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('test_simz1_incident_configuration.py', 'test_simz1_incident_design.py',
                            'test_simz1_incident_replay.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed Python contract: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('incident_effects', 'continuous_bootstrap', 'queue_window_controls', 'vehicle_picking')) {
        & node (Join-Path 'python' ('test_simz1_' + $simz1Test + '.cjs'))
        if ($LASTEXITCODE -ne 0) { throw ('Failed visual contract: ' + $simz1Test) }
    }
    # Dependency jars only: never reuse target/classes or stale project bytecode.
    if (-not (Test-Path -LiteralPath $DependencyClasspathFile -PathType Leaf)) {
        throw 'Missing dependency classpath. Prepare it offline: .\mvnw.cmd -o -q dependency:build-classpath -Dmdep.outputFile=target/simz1-storage-classpath.txt'
    }
    $simz1Dependencies = (Get-Content -LiteralPath $DependencyClasspathFile -Raw).Trim()
    foreach ($simz1Jar in $simz1Dependencies.Split([IO.Path]::PathSeparator)) {
        if (-not $simz1Jar.EndsWith('.jar') -or -not (Test-Path -LiteralPath $simz1Jar -PathType Leaf)) {
            throw ('Dependency classpath must contain existing jars only: ' + $simz1Jar)
        }
    }
    $simz1Build = Join-Path $simz1Root ('target\simz1-incident-consequences-' + [Guid]::NewGuid().ToString('N'))
    $simz1Classes = Join-Path $simz1Build 'classes'
    New-Item -ItemType Directory -Path $simz1Classes -Force | Out-Null
    $simz1Sources = @(Get-ChildItem -LiteralPath 'src/main/java/gt/edu/uvg/sim/zona1' -Filter '*.java' -Recurse |
        ForEach-Object { $_.FullName })
    $simz1Sources += @(Get-ChildItem -LiteralPath 'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine' -Filter '*.java' -Recurse |
        ForEach-Object { $_.FullName })
    $simz1Checks = @('gt.edu.uvg.sim.zona1.SimZ1IncidentLaneCheck',
                     'gt.edu.uvg.sim.zona1.SimZ1ConfigurationCheck',
                     'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1AdmissionCheck',
                     'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1AdmissionConcurrencyCheck',
                     'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageBranchCheck')
    foreach ($simz1Check in $simz1Checks) {
        $simz1Sources += Join-Path $simz1Root ('src/test/java/' + $simz1Check.Replace('.', '/') + '.java')
    }
    $simz1Hashes = [ordered]@{}
    foreach ($simz1Source in $simz1Sources) {
        $simz1Hashes[$simz1Source.Substring($simz1Root.Length + 1).Replace('\', '/')] =
            (Get-FileHash -LiteralPath $simz1Source -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    # javac argfile quoting is separate from shell quoting. Paths use forward
    # slashes so backslashes cannot escape quotes in javac's own parser.
    $simz1Args = @('--release', '25', '-encoding', 'UTF-8', '-proc:none', '-cp',
        ('"' + $simz1Dependencies.Replace('\', '/') + '"'), '-d',
        ('"' + $simz1Classes.Replace('\', '/') + '"'))
    $simz1Args += @($simz1Sources | ForEach-Object { '"' + $_.Replace('\', '/') + '"' })
    $simz1ArgFile = Join-Path $simz1Build 'javac.args'
    [IO.File]::WriteAllLines($simz1ArgFile, $simz1Args, [Text.UTF8Encoding]::new($false))
    $simz1CompilerLog = Join-Path $simz1Build 'javac-stderr.log'
    $simz1Compiler = Start-Process -FilePath $JavacExecutable -ArgumentList ('"@' + $simz1ArgFile + '"') `
        -WindowStyle Hidden -Wait -PassThru -RedirectStandardError $simz1CompilerLog `
        -RedirectStandardOutput (Join-Path $simz1Build 'javac-stdout.log')
    $simz1CompilerText = Get-Content -LiteralPath $simz1CompilerLog -Raw
    if ($simz1CompilerText) { Write-Host $simz1CompilerText }
    if ($simz1Compiler.ExitCode -ne 0 -or $simz1CompilerText -match 'An exception has occurred in the compiler|Exception:|error:') {
        throw 'Fresh Java compilation failed; inspect javac-stderr.log. Do not accept an internal compiler exception even with exit code zero.'
    }
    $simz1Classpath = $simz1Classes + [IO.Path]::PathSeparator + $simz1Dependencies
    [IO.File]::WriteAllText((Join-Path $simz1Build 'classpath.txt'), $simz1Classpath, [Text.UTF8Encoding]::new($false))
    foreach ($simz1Check in $simz1Checks) {
        if ($simz1Check.EndsWith('.SimZ1IncidentLaneCheck')) {
            & $JavaExecutable -cp $simz1Classpath $simz1Check (Join-Path $simz1Build 'fixture-events.xml')
        } else {
            & $JavaExecutable -cp $simz1Classpath $simz1Check
        }
        if ($LASTEXITCODE -ne 0) { throw ('Failed Java contract: ' + $simz1Check) }
    }
    & $simz1Python -B python/check_simz1_incident_wire.py (Join-Path $simz1Build 'fixture-events.xml')
    if ($LASTEXITCODE -ne 0) { throw 'Java/Python fixture wire mismatch' }
    foreach ($simz1Source in $simz1Sources) {
        $simz1Relative = $simz1Source.Substring($simz1Root.Length + 1).Replace('\', '/')
        if ($simz1Hashes[$simz1Relative] -ne (Get-FileHash -LiteralPath $simz1Source -Algorithm SHA256).Hash.ToLowerInvariant()) {
            throw ('Source changed during compilation/checks: ' + $simz1Relative)
        }
    }
    $simz1Manifest = [ordered]@{schema='simz1-incident-consequences-check-v1';
        simulation_executed=$false; native_adapter_installed=$false;
        source_sha256=$simz1Hashes; checks=$simz1Checks}
    [IO.File]::WriteAllText((Join-Path $simz1Build 'checked-sources.json'),
        ($simz1Manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Write-Host ('PASS: isolated contracts only; no physical lane closure enabled. Build: ' + $simz1Build)
} finally {
    Pop-Location
}
