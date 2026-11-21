# Pure checks only: this script never starts Controler, QSim, a server or a browser.
[CmdletBinding()]
param(
    [string]$CompiledClasspathFile = '',
    [string]$JavaExecutable = 'java'
)
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('test_simz1_admission.py', 'test_simz1_storage_diagnostics.py',
                            'test_simz1_visual_motion.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed Python fixture: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('visual_lanes', 'visual_queues', 'queue_contract', 'queue_safety',
                            'queue_window_controls', 'queue_continuity', 'rigid_vehicles',
                            'spatial_view', 'vehicle_picking', 'continuous_bootstrap',
                            'conflict_diagnostics', 'native_queue_extent', 'queue_stoplines', 'queue_head_fallback')) {
        & node (Join-Path 'python' ('test_simz1_' + $simz1Test + '.cjs'))
        if ($LASTEXITCODE -ne 0) { throw ('Failed visual fixture: ' + $simz1Test) }
    }
    if ($CompiledClasspathFile) {
        # Reusing a compilation is allowed only if both its inputs and bytecode
        # still match its manifest. Never silently run stale target/classes.
        $simz1CpFile = (Resolve-Path -LiteralPath $CompiledClasspathFile).Path
        $simz1Build = Split-Path -Parent $simz1CpFile
        $simz1Manifest = Get-Content -LiteralPath (Join-Path $simz1Build 'compiled-sources.json') -Raw | ConvertFrom-Json
        if ($simz1Manifest.schema -ne 'simz1-admission-compiled-sources-v1' -or
            (Get-FileHash -LiteralPath $simz1CpFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $simz1Manifest.classpath_sha256) {
            throw 'Unrecognized or changed compiled classpath manifest'
        }
        foreach ($simz1Entry in $simz1Manifest.source_sha256.PSObject.Properties) {
            if ((Get-FileHash -LiteralPath (Join-Path $simz1Root $simz1Entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $simz1Entry.Value) {
                throw ('Changed source; recompile before running checks: ' + $simz1Entry.Name)
            }
        }
        foreach ($simz1Entry in $simz1Manifest.compiled_class_sha256.PSObject.Properties) {
            if ((Get-FileHash -LiteralPath (Join-Path (Join-Path $simz1Build 'classes') $simz1Entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $simz1Entry.Value) {
                throw ('Changed bytecode; recompile before running checks: ' + $simz1Entry.Name)
            }
        }
        $simz1Classpath = (Get-Content -LiteralPath $simz1CpFile -Raw).Trim()
    } else {
        $simz1CpFile = Join-Path $simz1Root ('target\simz1-admission-deps-' + [Guid]::NewGuid().ToString('N') + '.txt')
        & .\mvnw.cmd -o -q test-compile dependency:build-classpath '-DskipTests' ('-Dmdep.outputFile=' + $simz1CpFile)
        if ($LASTEXITCODE -ne 0) { throw 'Offline compilation failed: JDK 25 and cached Maven dependencies are required' }
        $simz1Classpath = (Join-Path $simz1Root 'target\test-classes') + ';' +
                          (Join-Path $simz1Root 'target\classes') + ';' + (Get-Content -LiteralPath $simz1CpFile -Raw).Trim()
    }
    $simz1NativeChecks = @('SimZ1AdmissionCheck', 'SimZ1AdmissionConcurrencyCheck', 'SimZ1StorageBranchCheck',
                           'PriorityRestrictionCheck', 'SimZ1StorageObservationCheck', 'Zona1NativeDecisionCheck',
                           'PriorityBlockedRegression')
    $simz1Classes = @($simz1NativeChecks | ForEach-Object { 'org.matsim.core.mobsim.qsim.qnetsimengine.' + $_ })
    $simz1Classes += @('gt.edu.uvg.sim.zona1.PriorityContractCheck',
                       'gt.edu.uvg.sim.zona1.SimZ1ConfigurationCheck')
    foreach ($simz1Class in $simz1Classes) {
        & $JavaExecutable -cp $simz1Classpath $simz1Class
        if ($LASTEXITCODE -ne 0) { throw ('Failed native branch fixture: ' + $simz1Class) }
    }
    Write-Host 'PASS: pure SimZ1 admission/queue checks. No MATSim simulation was executed.'
} finally {
    Pop-Location
}
