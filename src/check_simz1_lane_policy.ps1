# Isolated contracts only. No Controler/QSim execution, historical writes or services.
[CmdletBinding()]
param(
    [string]$DependencyClasspathFile = 'target/simz1-storage-classpath.txt',
    [string]$JavaExecutable = 'java',
    [string]$JavacExecutable = 'javac',
    [string]$BuildRoot = 'target',
    [string]$EvidenceFile
)
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('admission', 'storage_diagnostics', 'lane_validation')) {
        & $simz1Python -B -m unittest discover -s python -p ('test_simz1_' + $simz1Test + '.py') -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed Python contract: ' + $simz1Test) }
    }
    Push-Location -LiteralPath (Join-Path $simz1Root 'python')
    try {
        # Explicit mocks: the process-tree interrupt test and simulation checks are excluded.
        & $simz1Python -B -m unittest -v `
            test_ejecutar_simz1.RunnerTests.test_failure_status_and_config_paths_with_spaces `
            test_ejecutar_simz1.RunnerTests.test_zero_exit_without_artifacts_is_failure `
            test_simz1_run.RunContractTests.test_replay_vehicle_limits_are_selected_and_fingerprinted
        if ($LASTEXITCODE -ne 0) { throw 'Failed mocked launcher contract' }
    } finally { Pop-Location }
    foreach ($simz1Test in @('queue_stoplines', 'queue_contract', 'visual_queues', 'visual_lanes',
                            'queue_head_fallback', 'native_queue_extent', 'queue_continuity')) {
        & node (Join-Path 'python' ('test_simz1_' + $simz1Test + '.cjs'))
        if ($LASTEXITCODE -ne 0) { throw ('Failed visual contract: ' + $simz1Test) }
    }
    if (-not (Test-Path -LiteralPath $DependencyClasspathFile -PathType Leaf)) {
        throw 'Prepare dependency jars offline: .\mvnw.cmd -o -q dependency:build-classpath -Dmdep.outputFile=target/simz1-storage-classpath.txt'
    }
    $simz1Dependencies = (Get-Content -LiteralPath $DependencyClasspathFile -Raw).Trim()
    foreach ($simz1Jar in $simz1Dependencies.Split([IO.Path]::PathSeparator)) {
        if (-not $simz1Jar.EndsWith('.jar') -or -not (Test-Path -LiteralPath $simz1Jar -PathType Leaf)) {
            throw ('Existing dependency jars only; no stale project classes: ' + $simz1Jar)
        }
    }
    $simz1Build = Join-Path $BuildRoot ('simz1-lane-policy-' + [Guid]::NewGuid().ToString('N'))
    $simz1Build = [IO.Path]::GetFullPath($simz1Build)
    $simz1Classes = Join-Path $simz1Build 'classes'
    New-Item -ItemType Directory -Path $simz1Classes | Out-Null
    # Compile against byte-for-byte local copies, preserving the Maven cache.
    # A Windows sandbox can still deny javac's ZipFS.toRealPath on close; report
    # that compiler failure instead of treating emitted classes as a valid build.
    $simz1LocalJars = Join-Path $simz1Build 'dependencies'
    New-Item -ItemType Directory -Path $simz1LocalJars | Out-Null
    $simz1JarPaths = @()
    $simz1JarHashes = [ordered]@{}
    foreach ($simz1Jar in $simz1Dependencies.Split([IO.Path]::PathSeparator)) {
        $simz1Copy = Join-Path $simz1LocalJars ('{0:D3}-{1}' -f $simz1JarPaths.Count, [IO.Path]::GetFileName($simz1Jar))
        Copy-Item -LiteralPath $simz1Jar -Destination $simz1Copy
        $simz1JarHash = (Get-FileHash -LiteralPath $simz1Jar -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($simz1JarHash -ne (Get-FileHash -LiteralPath $simz1Copy -Algorithm SHA256).Hash.ToLowerInvariant()) {
            throw ('Dependency copy mismatch: ' + $simz1Jar)
        }
        $simz1JarHashes[[IO.Path]::GetFileName($simz1Copy)] = $simz1JarHash
        $simz1JarPaths += $simz1Copy
    }
    $simz1Dependencies = $simz1JarPaths -join [IO.Path]::PathSeparator
    $simz1Sources = @()
    foreach ($simz1Directory in @('src/main/java/gt/edu/uvg/sim/zona1',
        'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine',
        'src/test/java/gt/edu/uvg/sim/zona1', 'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine')) {
        $simz1Sources += @(Get-ChildItem -LiteralPath $simz1Directory -Filter '*.java' -Recurse |
            ForEach-Object { $_.FullName })
    }
    $simz1Hashes = [ordered]@{}
    foreach ($simz1Source in $simz1Sources) {
        $simz1Hashes[$simz1Source.Substring($simz1Root.Length + 1).Replace('\', '/')] =
            (Get-FileHash -LiteralPath $simz1Source -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $simz1Arguments = @('--release', '25', '-encoding', 'UTF-8', '-g:none', '-proc:none', '-cp',
        ('"' + $simz1Dependencies.Replace('\', '/') + '"'), '-d',
        ('"' + $simz1Classes.Replace('\', '/') + '"'))
    $simz1Arguments += @($simz1Sources | ForEach-Object { '"' + $_.Replace('\', '/') + '"' })
    $simz1ArgFile = Join-Path $simz1Build 'javac.args'
    [IO.File]::WriteAllLines($simz1ArgFile, $simz1Arguments, [Text.UTF8Encoding]::new($false))
    $simz1CompilerLog = Join-Path $simz1Build 'javac-stderr.log'
    $simz1Compiler = Start-Process -FilePath $JavacExecutable -ArgumentList ('"@' + $simz1ArgFile + '"') `
        -WindowStyle Hidden -Wait -PassThru -RedirectStandardError $simz1CompilerLog `
        -RedirectStandardOutput (Join-Path $simz1Build 'javac-stdout.log')
    $simz1CompilerText = Get-Content -LiteralPath $simz1CompilerLog -Raw
    if ($simz1CompilerText) { Write-Host $simz1CompilerText }
    if ($simz1Compiler.ExitCode -ne 0 -or $simz1CompilerText -match 'An exception has occurred in the compiler|Exception:|error:') {
        throw 'Fresh compilation failed; inspect javac-stderr.log'
    }
    $simz1Classpath = $simz1Classes + [IO.Path]::PathSeparator + $simz1Dependencies
    [IO.File]::WriteAllText((Join-Path $simz1Build 'classpath.txt'), $simz1Classpath, [Text.UTF8Encoding]::new($false))
    $simz1Checks = @('gt.edu.uvg.sim.zona1.SimZ1LanePolicyCheck',
        'gt.edu.uvg.sim.zona1.SimZ1ConfigurationCheck', 'gt.edu.uvg.sim.zona1.PriorityContractCheck')
    $simz1Checks += @('SimZ1AdmissionCheck', 'SimZ1AdmissionConcurrencyCheck', 'SimZ1StorageBranchCheck',
        'PriorityRestrictionCheck', 'SimZ1StorageObservationCheck', 'Zona1NativeDecisionCheck',
        'PriorityBlockedRegression' | ForEach-Object { 'org.matsim.core.mobsim.qsim.qnetsimengine.' + $_ })
    foreach ($simz1Check in $simz1Checks) {
        & $JavaExecutable -cp $simz1Classpath $simz1Check
        if ($LASTEXITCODE -ne 0) { throw ('Failed isolated Java contract: ' + $simz1Check) }
    }
    foreach ($simz1Source in $simz1Sources) {
        $simz1Relative = $simz1Source.Substring($simz1Root.Length + 1).Replace('\', '/')
        if ($simz1Hashes[$simz1Relative] -ne (Get-FileHash -LiteralPath $simz1Source -Algorithm SHA256).Hash.ToLowerInvariant()) {
            throw ('Source changed during compilation/checks: ' + $simz1Relative)
        }
    }
    $simz1Manifest = [ordered]@{schema='simz1-lane-policy-check-v1'; simulation_executed=$false;
        microscopic_adapter_installed=$false; source_sha256=$simz1Hashes;
        dependency_sha256=$simz1JarHashes; checks=$simz1Checks}
    [IO.File]::WriteAllText((Join-Path $simz1Build 'checked-sources.json'),
        ($simz1Manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    if ($EvidenceFile) {
        if (Test-Path -LiteralPath $EvidenceFile) { throw 'EvidenceFile already exists; refusing to overwrite' }
        [IO.File]::WriteAllText([IO.Path]::GetFullPath($EvidenceFile),
            (([ordered]@{build=$simz1Build; manifest=(Join-Path $simz1Build 'checked-sources.json'); classes=$simz1Classes}) |
                ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    }
    Write-Host ('PASS: isolated admission/lane/visual contracts; no QSim run. Build: ' + $simz1Build)
} finally { Pop-Location }
