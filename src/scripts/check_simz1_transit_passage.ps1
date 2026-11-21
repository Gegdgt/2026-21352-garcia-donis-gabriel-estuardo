# Correction 3 only. Execute manually; never calls Validate or a simulation workflow.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$simz1Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$simz1Build = Join-Path $simz1Project ('target\correction3-' + [guid]::NewGuid().ToString('N'))
Push-Location -LiteralPath $simz1Project
try {
    Write-Host "Isolated compilation: $simz1Build"
    & .\mvnw.cmd --batch-mode --no-transfer-progress "-Dsimz1.buildDirectory=$simz1Build" '-DskipTests' test-compile
    if ($LASTEXITCODE -ne 0) { throw 'Correction 3 compilation failed; no checks executed.' }
    foreach ($simz1Check in @('SimZ1TransitPassageReleaseCheck', 'SimZ1TransitPassageNativeCheck')) {
        & .\mvnw.cmd --batch-mode --no-transfer-progress "-Dsimz1.buildDirectory=$simz1Build" '-Dexec.classpathScope=test' "-Dexec.mainClass=org.matsim.core.mobsim.qsim.qnetsimengine.$simz1Check" exec:java
        if ($LASTEXITCODE -ne 0) { throw "Correction 3 failed: $simz1Check" }
    }
    Write-Host 'PASS: both Correction 3 fixtures. No controller, massive run or previous regression suite executed.'
} finally {
    Pop-Location
}
