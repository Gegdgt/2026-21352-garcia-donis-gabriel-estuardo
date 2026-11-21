# User-run small fixtures only. Never starts MATSim, a server, browser or export.
[CmdletBinding()]
param([switch]$InspectRunningViewer)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $simz1Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('test_simz1_transit_stops.py', 'test_simz1_client_identity.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed prepared test: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('test_simz1_transit_stops.cjs', 'test_simz1_continuous_bootstrap.cjs',
                            'test_simz1_vehicle_card.cjs', 'test_visualizador_z1_controls.cjs')) {
        & node (Join-Path 'python' $simz1Test)
        if ($LASTEXITCODE -ne 0) { throw ('Failed prepared test: ' + $simz1Test) }
    }
    if ($InspectRunningViewer) {
        # Read only the existing loopback service. This does not prove what a previously loaded tab has cached.
        $simz1Expected = @'
import json, sys
sys.path.insert(0, 'python')
from simz1_continuous_replay import application_html
document = application_html()
start = document.index('window.simz1ClientBuild=Object.freeze(') + len('window.simz1ClientBuild=Object.freeze(')
print(document[start:document.index(');</script>', start)])
'@ | & $simz1Python -B -
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read the current client fingerprint' }
        $simz1Expected = $simz1Expected | ConvertFrom-Json
        Add-Type -AssemblyName System.Net.Http
        $simz1Client = [System.Net.Http.HttpClient]::new()
        try {
            $simz1Client.Timeout = [TimeSpan]::FromSeconds(5)
            $simz1Client.MaxResponseContentBufferSize = 16MB
            $simz1Html = $simz1Client.GetStringAsync('http://127.0.0.1:8793/index.html').GetAwaiter().GetResult()
            $simz1Config = $simz1Client.GetStringAsync('http://127.0.0.1:8793/api/config').GetAwaiter().GetResult() | ConvertFrom-Json
        } finally { $simz1Client.Dispose() }
        $simz1Match = [regex]::Match($simz1Html, 'window\.simz1ClientBuild=Object\.freeze\((.*?)\);</script>', 'Singleline')
        if (-not $simz1Match.Success) { throw 'The server has no current client fingerprint' }
        $simz1Served = $simz1Match.Groups[1].Value | ConvertFrom-Json
        $simz1SameClient = $simz1Expected.source_sha256 -eq $simz1Served.source_sha256
        [ordered]@{
            run_id = $simz1Config.continuous.run_id
            iteration = $simz1Config.continuous.iteration
            run_manifest_sha256 = $simz1Config.continuous.run_manifest_sha256
            replay_source = $simz1Config.replay_source
            served_client_sha256 = $simz1Served.source_sha256
            current_client_matches = $simz1SameClient
            stop_component_sha256 = $simz1Served.components.stops
            stops = $simz1Config.transit_stops
            loaded_browser_client = 'not_observed'
        } | ConvertTo-Json -Depth 12
        if (-not $simz1SameClient) { throw 'Existing server serves an older client. Reloading an old static export is insufficient; no export is needed.' }
        if ($simz1Config.continuous.run_id -ne $simz1Config.hud.run_id -or
            $simz1Config.continuous.iteration -ne $simz1Config.hud.iteration) { throw 'Inconsistent run/HUD identity' }
        if ($simz1Config.transit_stops.schema_version -ne 'simz1-stop-display-v1') { throw 'Existing API/config lacks the current stop catalog contract' }
        foreach ($simz1Key in @('run_id', 'iteration', 'run_manifest_sha256')) {
            if ($simz1Config.transit_stops.identity.$simz1Key -ne $simz1Config.continuous.$simz1Key) {
                throw ('Stop catalog belongs to a different replay identity: ' + $simz1Key)
            }
        }
    }
    Write-Host 'Prepared stop checks completed. No production stop or service was enabled.'
} finally { Pop-Location }
