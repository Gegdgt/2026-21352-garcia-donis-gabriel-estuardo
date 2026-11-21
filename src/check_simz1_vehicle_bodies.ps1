# Pure metric/XML/replay fixtures only. No browser, server, simulation or historical writes.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    foreach ($simz1Test in @('test_simz1_physical_dimensions.py', 'test_simz1_agent_metadata.py',
                            'test_simz1_motion.py', 'test_simz1_road_profiles.py',
                            'test_simz1_replay_integration.py')) {
        & $simz1Python -B -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Failed Python fixture: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('visual_lanes', 'visual_queues', 'vehicle_presentation', 'vehicle_dimensions',
                            'road_presentation', 'rigid_vehicles', 'body_spacing', 'vehicle_picking',
                            'vehicle_picking_dimensions', 'vehicle_focus', 'vehicle_card', 'queue_contract',
                            'queue_safety', 'queue_window_controls', 'queue_continuity', 'native_queue_extent',
                            'queue_stoplines', 'queue_head_fallback', 'conflict_diagnostics', 'spatial_view',
                            'continuous_bootstrap')) {
        & node (Join-Path 'python' ('test_simz1_' + $simz1Test + '.cjs'))
        if ($LASTEXITCODE -ne 0) { throw ('Failed visual fixture: ' + $simz1Test) }
    }
    Write-Host 'PASS: SimZ1 vehicle body regression (5 Python modules, 21 Node suites). No simulation executed.'
} finally {
    Pop-Location
}
