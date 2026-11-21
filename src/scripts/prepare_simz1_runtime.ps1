# Clean only regenerable compiled class folders; never runs or source data.
[CmdletBinding()]
param([switch]$RunSmoke)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Falta el Python del entorno .venv.' }
# Do not rebuild while a native SimZ1 process is using the same working tree.
$active = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^java(w)?\.exe$' -and $_.CommandLine -and
    ($_.CommandLine -match 'gt\.edu\.uvg\.sim\.zona1|exec:exec@simz1-fork|exec:java')
})
if ($active.Count) { throw 'Hay una JVM de simulacion activa. Cierra tu corrida antes de recompilar.' }
foreach ($relative in @('target\classes', 'target\test-classes')) {
    $folder = Join-Path $project $relative
    if (Test-Path -LiteralPath $folder) {
        $items = @((Get-Item -LiteralPath $folder -Force)) + @(Get-ChildItem -LiteralPath $folder -Recurse -Force)
        if (@($items | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }).Count) {
            throw "No se toca un directorio con enlaces/reparse points: $folder"
        }
        Remove-Item -LiteralPath $folder -Recurse -Force
    }
}
& .\mvnw.cmd --batch-mode --no-transfer-progress '-DskipTests' test-compile
if ($LASTEXITCODE -ne 0) { throw 'Fallo test-compile. No se ejecuta QSim ni se borran corridas.' }
& .\mvnw.cmd --batch-mode --no-transfer-progress dependency:build-classpath '-Dmdep.outputFile=target/simz1-runtime-classpath.txt' '-Dmdep.includeScope=test'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el classpath de dependencias.' }
$cpFile = Join-Path $project 'target\simz1-runtime-classpath.txt'
& $python -B .\python\simz1_runtime_check.py --classpath-file $cpFile
if ($LASTEXITCODE -ne 0) { throw 'El bytecode o las dependencias no pasaron la verificacion.' }
$java = 'java.exe'
if ($env:JAVA_HOME) { $java = Join-Path $env:JAVA_HOME 'bin\java.exe' }
$dependencies = [System.IO.File]::ReadAllText($cpFile).Trim()
$cp = (Join-Path $project 'target\test-classes') + ';' + (Join-Path $project 'target\classes') + ';' + $dependencies
# java @argfile also works with paths containing spaces; avoids Windows command-line length limits.
$launch = Join-Path $project ('target\simz1-check-' + [guid]::NewGuid().ToString('N') + '.args')
$cpEscaped = $cp.Replace('\','\\').Replace('"','\"')
$javaText = '-Xmx2G' + [Environment]::NewLine + '-classpath' + [Environment]::NewLine + '"' + $cpEscaped + '"' + [Environment]::NewLine
[System.IO.File]::WriteAllText($launch, $javaText, [System.Text.UTF8Encoding]::new($false))
foreach ($name in @('SimZ1FailureReportCheck','SimZ1FreightCheck','SimZ1TransitTimingCheck','SimZ1TransitAccessCheck','RouteSafetyCheck','SimZ1TransitFleetCheck','SimZ1TransitDiagnosticsCheck','TripReconciliationCheck','PriorityContractCheck')) {
    & $java ("@$launch") "gt.edu.uvg.sim.zona1.$name"
    if ($LASTEXITCODE -ne 0) { throw "Fallo $name; no se permite una corrida masiva." }
}
& $java ("@$launch") 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1VehicleReservationCheck'
if ($LASTEXITCODE -ne 0) { throw 'Fallo la reserva historica de vehiculos.' }
& $java ("@$launch") 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1CorridorOccupancyCheck'
if ($LASTEXITCODE -ne 0) { throw 'Fallo la reserva fisica por corredor.' }
foreach ($name in @('SimZ1CrossingClearanceCheck', 'SimZ1LaneHeadArbitrationCheck', 'SimZ1PassageTimerCheck', 'SimZ1PriorityReceiverCheck', 'SimZ1PriorityLookaheadCheck', 'SimZ1ParallelPassagePriorityCheck', 'SimZ1ParallelOriginalFifoCheck', 'SimZ1ParallelOriginalRingCheck', 'SimZ1PassageFairnessCheck', 'SimZ1SignalCycleRouteCheck', 'SimZ1ShortOriginCheck', 'SimZ1InteriorTurnCheck', 'SimZ1InteriorRerouteCheck', 'SimZ1TerminalTurnCheck')) {
    & $java ("@$launch") "org.matsim.core.mobsim.qsim.qnetsimengine.$name"
    if ($LASTEXITCODE -ne 0) { throw "Fallo la regresion de circulacion: $name" }
}
& $java ("@$launch") 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1BlockingStopCheck'
if ($LASTEXITCODE -ne 0) { throw 'Fallo la cola detras de bus detenido con semaforo nativo.' }
# Corrections 1-4 remain part of the integrated revision gate. Receiver,
# Lookahead and Fairness already ran above; do not omit any existing check.
foreach ($name in @('SimZ1TenthStreetReceptionCheck','PriorityBlockedRegression',
    'SimZ1OpposedReturnRerouteCheck','SimZ1ReturnSignalRerouteCheck',
    'SimZ1TransitPassageReleaseCheck','SimZ1TransitPassageNativeCheck',
    'SimZ1DownstreamStorageCheck','SimZ1IndependentLaneDischargeCheck',
    'SimZ1OriginalTravelHeadCheck','SimZ1OriginalTravelSlotCheck','SimZ1OrdinaryReceiptClearanceCheck')) {
    & $java ("@$launch") "org.matsim.core.mobsim.qsim.qnetsimengine.$name"
    if ($LASTEXITCODE -ne 0) { throw "Fallo la validacion integrada: $name" }
}
& $java ("@$launch") 'gt.edu.uvg.sim.zona1.SimZ1PhysicalGap20261027Check'
if ($LASTEXITCODE -ne 0) { throw 'Fallo el contrato de separacion minima de 0.10 m.' }
& $java ("@$launch") 'gt.edu.uvg.sim.zona1.Zona1SignalGreenWindowCheck'
if ($LASTEXITCODE -ne 0) { throw 'Fallo el contrato de ventana verde para despejar cruces.' }
if ($RunSmoke) {
    $fixture = Join-Path $project ('runtime\validation\transit-startup-' + [guid]::NewGuid().ToString('N'))
    & $python -B .\python\simz1_transit_fleet.py --config .\python\fixtures\simz1-transit-fleet-synthetic.json --output $fixture
    if ($LASTEXITCODE -ne 0) { throw 'Fallo preparar fixture aislado N=3/B=2.' }
    & $java ("@$launch") gt.edu.uvg.sim.zona1.SimZ1TransitFixture $fixture --simulate
    if ($LASTEXITCODE -ne 0) { throw "Fallo QSim sintetico; conservar $fixture" }
    Write-Host "QSIM SINTETICO N=3/B=2 APROBADO: $fixture" -ForegroundColor Green
}
Write-Host 'CLASES Y REGRESIONES JAVA VERIFICADAS; no certifica una corrida real de Zona 1.' -ForegroundColor Green
