# User-run checks only. QSim is run ONLY with the explicit -RunSyntheticSimulation switch.
# Prepared fleet/QSim outputs stay in a fresh UUID directory; checks also use temporary test folders.
[CmdletBinding()]
param([switch]$RunSyntheticSimulation)
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('test_simz1_transit_catalog.py', 'test_simz1_transit_fleet.py',
                            'test_simz1_transit_accounting.py', 'test_simz1_transit_events.py',
                            'test_simz1_event_validation.py', 'test_simz1_massive_demand.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed fixture: ' + $simz1Test) }
    }
    # The preparer validates first and exclusively creates the new directory itself.
    $simz1ValidationDir = Join-Path $simz1Root 'runtime\validation'
    if (-not (Test-Path -LiteralPath $simz1ValidationDir -PathType Container)) {
        New-Item -ItemType Directory -Path $simz1ValidationDir -ErrorAction Stop | Out-Null
    }
    $simz1FixtureDir = Join-Path $simz1ValidationDir ('transit-fleet-' + [Guid]::NewGuid().ToString('N'))
    & $simz1Python -B python/simz1_transit_fleet.py --config python/fixtures/simz1-transit-fleet-synthetic.json --output $simz1FixtureDir
    if ($LASTEXITCODE -ne 0) { throw 'Fixed fleet fixture preparation failed' }
    & .\mvnw.cmd -o -q test-compile '-DskipTests'
    if ($LASTEXITCODE -ne 0) { throw 'Requires JDK 25 and cached Maven dependencies; compilation failed' }
    foreach ($simz1Class in @('SimZ1TransitFleetCheck', 'SimZ1TransitDiagnosticsCheck')) {
        & .\mvnw.cmd -o -q exec:java '-Dexec.classpathScope=test' ('-Dexec.mainClass=gt.edu.uvg.sim.zona1.' + $simz1Class)
        if ($LASTEXITCODE -ne 0) { throw ('Native API fixture failed: ' + $simz1Class) }
    }
    $simz1FixtureArgs = '"' + $simz1FixtureDir + '"'
    & .\mvnw.cmd -o -q exec:java '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.SimZ1TransitFixture' ('-Dexec.args=' + $simz1FixtureArgs)
    if ($LASTEXITCODE -ne 0) { throw 'Native XML round-trip or fleet preflight failed' }
    if ($RunSyntheticSimulation) {
        & .\mvnw.cmd -o -q exec:java '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.SimZ1TransitFixture' ('-Dexec.args=' + $simz1FixtureArgs + ' --simulate')
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic N=3/B=2 simulation failed; inspect retained diagnostics' }
    }
    Write-Host ('Checks completed; synthetic fixture retained in ' + $simz1FixtureDir)
    Write-Host 'No production service was enabled. Real services remain gated by the transit catalog.'
} finally {
    Pop-Location
}
