# User-run checks only. No QSim/Controler, server, browser or historical artifacts.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$simz1Root = $PSScriptRoot
Push-Location -LiteralPath $simz1Root
try {
    $simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
    $simz1CheckDir = Join-Path $simz1Root ('runtime\validation\road-profiles-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $simz1CheckDir -ErrorAction Stop | Out-Null
    $simz1VehicleTypes = Join-Path $simz1CheckDir 'vehicle-types.xml'
    @'
import json, sys
import xml.etree.ElementTree as ET
sys.path.insert(0, 'python')
from simz1_agent_types import load_catalog, vehicle_types_xml, catalog_manifest
catalog = load_catalog('scenarios/zona1/agent-types-road-v1.json')
with open(sys.argv[1], 'xb') as stream:
    ET.ElementTree(vehicle_types_xml(catalog)).write(stream, encoding='utf-8', xml_declaration=True)
print(json.dumps(catalog_manifest(catalog), ensure_ascii=False, indent=2))
'@ | & $simz1Python - $simz1VehicleTypes
    if ($LASTEXITCODE -ne 0) { throw 'Catalog/XML preparation failed' }
    & $simz1Python -m unittest discover -s python -p 'test_simz1_road_profiles.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Future road contract failed' }
    foreach ($simz1Test in @('test_simz1_agent_types.py', 'test_simz1_agent_demand.py', 'test_simz1_agent_metadata.py', 'test_simz1_motion.py', 'test_simz1_four_od.py')) {
        & $simz1Python -m unittest discover -s python -p $simz1Test -v
        if ($LASTEXITCODE -ne 0) { throw ('Regression failed: ' + $simz1Test) }
    }
    foreach ($simz1Test in @('test_simz1_road_presentation.cjs', 'test_simz1_vehicle_presentation.cjs')) {
        & node (Join-Path 'python' $simz1Test)
        if ($LASTEXITCODE -ne 0) { throw ('Presentation failed: ' + $simz1Test) }
    }
    & .\mvnw.cmd -o -q test-compile '-DskipTests'
    if ($LASTEXITCODE -ne 0) { throw 'Java compilation failed; requires JDK 25 and cached Maven dependencies' }
    & .\mvnw.cmd -o -q exec:java '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.RoadVehicleProfilesCheck' ('-Dexec.args="' + $simz1VehicleTypes + '"')
    if ($LASTEXITCODE -ne 0) { throw 'Road Java/XML contract failed' }
    & .\mvnw.cmd -o -q exec:java '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.SixTypeProfilesCheck'
    if ($LASTEXITCODE -ne 0) { throw 'Historical six-type Java contract failed' }
    Write-Host ('Checks completed. Small fixture retained in ' + $simz1CheckDir)
} finally {
    Pop-Location
}
