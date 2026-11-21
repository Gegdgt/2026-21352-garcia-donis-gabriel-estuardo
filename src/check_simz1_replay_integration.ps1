# User-run fixtures. No MATSim, population generation, server, browser or mass export.
[CmdletBinding()]
param([switch]$CpuBenchmark, [switch]$CopyBrowserBenchmark)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $simz1Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    # Validate the actual workspace and system temporary volume before tests create tiny fixtures.
    @'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, 'python')
from simz1_recovery_io import preflight_storage
for path in (Path.cwd(), Path(tempfile.gettempdir())):
    print(preflight_storage(path, required_bytes=64*1024**2, reserve_bytes=256*1024**2, probe_write=False))
'@ | & $simz1Python -B -
    if ($LASTEXITCODE -ne 0) { throw 'Storage/path preflight failed' }
    foreach ($simz1Test in @('test_simz1_replay_integration.py', 'test_simz1_motion.py',
                            'test_simz1_agent_metadata.py', 'test_simz1_road_profiles.py',
                            'test_simz1_transit_events.py', 'test_simz1_continuous_replay.py',
                            'test_simz1_visual_lanes.py', 'test_simz1_sqlite_source.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Fixture failed: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('test_simz1_transit_replay.cjs', 'test_simz1_continuous_replay.cjs',
                            'test_simz1_vehicle_card.cjs', 'test_simz1_continuous_bootstrap.cjs',
                            'test_simz1_render_performance.cjs', 'test_simz1_arrival_effects.cjs')) {
        & node (Join-Path 'python' $simz1Test)
        if ($LASTEXITCODE -ne 0) { throw ('Fixture failed: ' + $simz1Test) }
    }
    if ($CpuBenchmark) {
        $simz1ReportDirectory = Join-Path $PSScriptRoot ('runtime\replay-benchmark-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $simz1ReportDirectory -ErrorAction Stop | Out-Null
        $simz1Report = Join-Path $simz1ReportDirectory 'cpu-integration.json'
        & node --expose-gc scripts/validation/benchmark_simz1_integration.cjs --frames 30 --output $simz1Report
        if ($LASTEXITCODE -ne 0) { throw ('CPU benchmark failed; evidence retained: ' + $simz1Report) }
        Write-Output ('CPU report (not WebGL FPS): ' + $simz1Report)
    }
    if ($CopyBrowserBenchmark) {
        $simz1Build = @'
import json, sys
sys.path.insert(0, 'python')
from simz1_continuous_replay import application_html
document = application_html()
start = document.index('window.simz1ClientBuild=Object.freeze(') + len('window.simz1ClientBuild=Object.freeze(')
print(json.loads(document[start:document.index(');</script>', start)])['source_sha256'])
'@ | & $simz1Python -B -
        if ($LASTEXITCODE -ne 0) { throw 'Cannot fingerprint current sources' }
        $simz1BrowserScript = Get-Content -Raw -LiteralPath 'scripts\validation\benchmark_simz1_tab.js'
        $simz1Invocation = 'await runSimZ1IntegrationBenchmark({expectedBuild:"' + $simz1Build.Trim() + '",times:[28080,43200,64800],seconds:3});'
        Set-Clipboard -Value ($simz1BrowserScript + [Environment]::NewLine + $simz1Invocation)
        Write-Output 'Paste the clipboard into the already open continuous viewer console. It changes playback/selection temporarily and restores clock/rate/pause.'
        Write-Output 'Then copy(JSON.stringify(window.simz1IntegrationBenchmark,null,2)); no browser or server was started.'
    }
} finally { Pop-Location }
