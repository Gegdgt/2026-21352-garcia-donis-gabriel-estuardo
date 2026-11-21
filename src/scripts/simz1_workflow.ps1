# Local workflow; no Downloads/patch dependency and no automatic massive run.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Validate','Clean','Run1000','RunMassive','View')][string]$Action,
    [string]$ExperimentSpec,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$DryRunLaunchId,
    [switch]$DryRun,
    [int]$Seed = 20261023,
    [string]$ServiceDate = '2026-10-23',
    [string]$AgentCatalog = 'scenarios\zona1\agent-types-nonpublic-v1.json',
    [ValidateSet('legacy-gaussian-v1','lane-length-destinations-v1')][string]$DestinationPolicy = 'legacy-gaussian-v1',
    [ValidateSet('network','balanced-gateway-v1')][string]$OdMode = 'network',
    [string]$ZoneBoundary,
    [string]$OdAccessCatalog,
    [string]$OdMixFile,
    [switch]$AcceptTransitRouteAssumptions,
    [string]$FreightService = 'scenarios\zona1\freight\weekday-v2\service-composition-v2.json',
    [string]$FreightServiceDate,
    [Nullable[int]]$FreightVehicles,
    [switch]$NoFreightTransport,
    [ValidateSet('none','derive','derive-activity-v2')][string]$ShortLinkSignalCoordination = 'derive',
    [string]$RunDir,
    [Nullable[int]]$Iteration,
    [switch]$NoBrowser,
    [ValidateRange(1,65535)][int]$Port = 8793,
    [ValidateRange(1,500)][int]$SQLiteBudgetGiB = 8,
    [ValidateRange(1,500)][int]$ScratchBudgetGiB = 4
)
$ErrorActionPreference = 'Stop'
if ($Action -eq 'RunMassive') { throw 'Use run_simz1_180k_balanced_gateway.ps1 with explicit ExperimentSpec/ExperimentScenario. No generic massive run.' }
if ($DryRun -and $Action -ne 'Run1000') { throw '-DryRun requires -Action Run1000.' }
if ($Action -eq 'Run1000') {
    if (-not $ExperimentSpec) { throw 'Run1000 requires the versioned 24h ExperimentSpec; no network acceptance fallback.' }
    $allowedTrialArguments = @('Action','ExperimentSpec','DryRun','DryRunLaunchId')
    foreach ($key in $PSBoundParameters.Keys) {
        if ($key -notin $allowedTrialArguments) { throw "Use check_simz1_110k_balanced_gateway.ps1 for the canonical trial; unsupported override: $key" }
    }
    $trialForward = @{Action='Run1000'; ExperimentSpec=$ExperimentSpec; DryRun=[bool]$DryRun}
    if ($DryRunLaunchId) { $trialForward.DryRunLaunchId=$DryRunLaunchId }
    & (Join-Path $PSScriptRoot 'check_simz1_110k_balanced_gateway.ps1') @trialForward
    $trialExit=$LASTEXITCODE
    exit $trialExit
}
. (Join-Path $PSScriptRoot 'simz1_launch_contract.ps1')
if ($NoFreightTransport -and ($PSBoundParameters.ContainsKey('FreightService') -or
    $PSBoundParameters.ContainsKey('FreightServiceDate') -or $PSBoundParameters.ContainsKey('FreightVehicles'))) {
    throw '-NoFreightTransport no se combina con opciones del servicio de carga.'
}
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Falta .venv\Scripts\python.exe.' }
if ($Action -eq 'Validate') {
    if ($OdMode -eq 'balanced-gateway-v1') {
        $validationStartFingerprint = & $python -B .\python\simz1_workflow_state.py fingerprint
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo identificar la revision antes de Validate.' }
        foreach ($name in @('run_simz1_110k_balanced_gateway.ps1','check_simz1_110k_balanced_gateway.ps1',
            'watch_simz1_110k.ps1','run_massive_z1_pasante_1it.ps1','run_massive_z1_pasante_10it.ps1',
            'run_simz1_with_analysis.ps1','simz1_workflow.ps1','prepare_simz1_runtime.ps1',
            'simz1_launch_contract.ps1','run_simz1_180k_balanced_gateway.ps1','recover_simz1_launch.ps1')) {
            $parseTokens = $null; $parseErrors = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name),[ref]$parseTokens,[ref]$parseErrors)
            if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
        }
    }
    & .\scripts\prepare_simz1_runtime.ps1 -RunSmoke
    # prepare_simz1_runtime throws on every failure; no unsafe success continuation.
    # The same configuration/closure code is exercised with tiny synthetic
    # artifacts, without a scale launch, before publishing this revision.
    foreach ($suite in @('test_simz1_configuration_contract.py','test_simz1_launch_recovery.py',
        'test_simz1_package_launcher.py','test_simz1_report_package.py','test_simz1_child_failure.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        $closureExit = $LASTEXITCODE
        if ($closureExit -ne 0) { throw "Fallo contrato de configuracion/cierre/recuperacion: $suite" }
    }
    $arrivalJava = (Get-Command java.exe -ErrorAction Stop).Source
    $arrivalCp = @('target\classes','target\test-classes','src\main\resources',
        (Get-Content -LiteralPath 'target\simz1-runtime-classpath.txt' -Raw).Trim()) -join [IO.Path]::PathSeparator
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1ArrivalClearanceCheck'
    if ($LASTEXITCODE -ne 0) { throw 'Fallo llegada nativa: despeje corporal, FIFO o descarga del carril independiente.' }
    $dischargeCheck = Join-Path $project ('runtime\validation\discharge-arrival-' + [guid]::NewGuid().ToString('N'))
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1DischargeArrivalCheck' $dischargeCheck '--require-native-storage'
    $dischargeExit = $LASTEXITCODE
    if ($dischargeExit -ne 0) { throw 'Fallo fixture de seis actores: llegadas OD/carga/bus, ultima parada o PCU nativos.' }
    $dischargeDayCheck = Join-Path $project ('runtime\validation\discharge-day-cycle-' + [guid]::NewGuid().ToString('N'))
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1DischargeArrivalCheck' $dischargeDayCheck '--day-cycle'
    $dischargeDayExit = $LASTEXITCODE
    if ($dischargeDayExit -ne 0) { throw 'Fallo ciclo de diez actores: carros/motos por OD, carga/bus, reservas o censo nativo.' }
    # Explicit origin-policy variant: existing legacy checks above stay intact.
    $originChecks = Join-Path $project ('runtime\validation\origin-gap-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $originChecks | Out-Null
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1OriginPolicyCheck' (Join-Path $project 'scenarios\zona1') (Join-Path $originChecks 'components.json') '10000'
    $originExit = $LASTEXITCODE
    if ($originExit -ne 0) { throw 'Fallo variante de origen: ancla, conectividad, FIFO, reservas, negativos o equivalencia de observacion.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1DischargeArrivalCheck' (Join-Path $originChecks 'day-cycle') '--day-cycle' '--origin-policy' 'physical-gap-origin-v1'
    $originDayExit = $LASTEXITCODE
    if ($originDayExit -ne 0) { throw 'Fallo QSim focal de nueva politica: OD, carga/bus, despeje, PCU o censo diario.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'gt.edu.uvg.sim.zona1.SimZ1FreightCompletionCheck'
    $completionExit = $LASTEXITCODE
    if ($completionExit -ne 0) { throw 'Fallo politica experimental de carga, fronteras o evidencia corporal.' }
    & $arrivalJava '-Xmx1g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1FreightOriginAdmissionCheck' (Join-Path $originChecks 'freight-admission.json')
    $freightAdmissionExit = $LASTEXITCODE
    if ($freightAdmissionExit -ne 0) { throw 'Fallo autorizacion de carga antes de reserva/extraccion FIFO; no se permite una entrada vencida.' }
    & $arrivalJava '-Xmx1g' '-cp' $arrivalCp 'gt.edu.uvg.sim.zona1.SimZ1FreightAdmissionQSimCheck' (Join-Path $originChecks 'freight-admission-qsim')
    $freightQsimExit = $LASTEXITCODE
    if ($freightQsimExit -ne 0) { throw 'Fallo micro-QSim de carga: entrada tolerada, despeje real o retencion tras vencimiento.' }
    & $python -B -m unittest discover -s python -p 'test_simz1_freight_admission.py' -v
    $freightContractExit = $LASTEXITCODE
    if ($freightContractExit -ne 0) { throw 'Fallo contrato versionado de incorporacion de carga.' }
    # Bounded component checks and tiny native fixtures only; never a scale trial.
    $dayChecks = Join-Path $project ('runtime\validation\day-boundary-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $dayChecks | Out-Null
    foreach ($name in @('gt.edu.uvg.sim.zona1.SimZ1DayObservationCheck',
        'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1ClosureCirculationCheck')) {
        & $arrivalJava '-Xmx2g' '-cp' $arrivalCp $name
        $dayExit = $LASTEXITCODE
        if ($dayExit -ne 0) { throw "Fallo componente de cierre/circulacion: $name" }
    }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1ArrivalClearanceCheck' '--fixed-day-only'
    $dayExit = $LASTEXITCODE
    if ($dayExit -ne 0) { throw 'Fallo QSim focal de frontera: un camion, dos iteraciones por caso.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'gt.edu.uvg.sim.zona1.SimZ1DayTransitCheck' (Join-Path $dayChecks 'transit')
    $dayExit = $LASTEXITCODE
    if ($dayExit -ne 0) { throw 'Fallo QSim focal de bus: N=3/B=2, dos expediciones, dos iteraciones.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'gt.edu.uvg.sim.zona1.SimZ1DiagnosticsPhaseCheck' (Join-Path $dayChecks 'diagnostics')
    $dayExit = $LASTEXITCODE
    if ($dayExit -ne 0) { throw 'Fallo identidad del callback/pila completa o fases monotonicamente medidas.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1AdmissionAttributionCheck'
    $attributionExit=$LASTEXITCODE
    if ($attributionExit -ne 0) { throw 'Fallo atribucion nativa/corporal de admision: rechazos, corto circuito o movimiento confirmado.' }
    & $arrivalJava '-Xmx2g' '-cp' $arrivalCp 'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1InternalSplitBackpressureCheck'
    $splitBackpressureExit=$LASTEXITCODE
    if ($splitBackpressureExit -ne 0) { throw 'Fallo admision entre split interno y terminal: contrapresion fisica, FIFO o descarga tras liberar capacidad.' }
    $savedIdentityEnvironment = @{}
    foreach ($key in @('SIMZ1_CONFIG','SIMZ1_RUN_ID','SIMZ1_LAUNCH_ID')) {
        $savedIdentityEnvironment[$key] = [Environment]::GetEnvironmentVariable($key,'Process')
    }
    try {
        $env:SIMZ1_CONFIG = Join-Path $dayChecks 'inert-config-not-loaded.xml'
        $env:SIMZ1_RUN_ID = 'inert-native-identity-check'
        $env:SIMZ1_LAUNCH_ID = 'inert-identity-check'
        & $arrivalJava '-Xmx256m' '-cp' $arrivalCp 'gt.edu.uvg.sim.zona1.SimZ1ProcessIdentityCheck'
        $dayExit = $LASTEXITCODE
        if ($dayExit -ne 0) { throw 'Fallo identidad atomica de JVM inerte; no QSim.' }
    } finally {
        foreach ($key in $savedIdentityEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($key,$savedIdentityEnvironment[$key],'Process')
        }
    }
    foreach ($suite in @('test_simz1_process_lifecycle.py','test_simz1_day_observation.py',
        'test_simz1_performance_observations.py','test_simz1_fixed_day_reports.py','test_simz1_continuous_replay.py',
        'test_simz1_replay_spatial_cache.py','test_simz1_replay_workers.py','test_simz1_replay_navigation_server.py',
        'test_simz1_partial_replay.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        $dayExit = $LASTEXITCODE
        if ($dayExit -ne 0) { throw "Fallo contrato 24h/procesos/observabilidad: $suite" }
    }
    foreach ($suite in @('test_simz1_transit_service_v8.py','test_simz1_v8_physical.py','test_simz1_v8_experiment.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        $v8Exit = $LASTEXITCODE
        if ($v8Exit -ne 0) { throw "Fallo contrato v8: $suite" }
    }
    & $python -B -m unittest discover -s python -p test_simz1_final_experiment.py -v
    $completionExit = $LASTEXITCODE
    if ($completionExit -ne 0) { throw 'Fallo especificacion/politica experimental Python.' }
    & $python -B -m unittest discover -s python -p test_simz1_trial_experiment.py -v
    $trialContractExit=$LASTEXITCODE
    if ($trialContractExit -ne 0) { throw 'Fallo alineacion versionada de Run1000/full-1 o guardas de lanzamiento.' }
    foreach ($suite in @('test_simz1_random_experiment.py','test_simz1_random_launch.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        $randomContractExit=$LASTEXITCODE
        if ($randomContractExit -ne 0) { throw "Fallo contrato de seleccion aleatoria: $suite" }
    }
    foreach ($suite in @('test_simz1_run10k_experiment.py','test_simz1_run10k_diagnostic.py','test_simz1_run10k_launch.py',
        'test_simz1_preparation_identity.py','test_simz1_dryrun_identity.py','test_simz1_load_scale.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        $diagnosticContractExit=$LASTEXITCODE
        if ($diagnosticContractExit -ne 0) { throw "Fallo contrato diagnostico Run10K: $suite" }
    }
    foreach ($suite in @('test_simz1_spatial_view.cjs','test_simz1_midnight_replay.cjs','test_simz1_continuous_replay.cjs','test_simz1_fixed_day_replay.cjs',
        'test_simz1_queue_anchor_propagation.cjs','test_simz1_causal_queue_context.cjs',
        'test_simz1_window_identity.cjs','test_simz1_queue_checkpoints.cjs',
        'test_simz1_checkpoint_loader.cjs','test_simz1_partial_visual.cjs')) {
        & node (Join-Path $project ('python/' + $suite))
        $presentationExit=$LASTEXITCODE
        if ($presentationExit -ne 0) { throw "Fallo replay/identidad/horizonte: $suite" }
    }
    & node (Join-Path $project 'python/test_simz1_journey_recovery.cjs')
    $journeyExit=$LASTEXITCODE
    if ($journeyExit -ne 0) { throw 'Fallo recuperacion 503, identidad o cancelacion de recorrido.' }
    & node (Join-Path $project 'python/test_simz1_journey_recovery.cjs') geometry
    $journeyExit=$LASTEXITCODE
    if ($journeyExit -ne 0) { throw 'Fallo continuidad de itinerario sin posicion reconstruible.' }
    & $python -B .\python\test_simz1_route_xml.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo el intercambio XML Python/MATSim 15 (sin simulacion).' }
    & $python -B .\python\test_simz1_failure_cleanup.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo cierre de carga/causa propagada (componentes sin simulacion).' }
    & $python -B .\python\test_simz1_passage_cycle.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo C529-A: ciclos de prioridad entre pasajes (colas nativas sin simulacion).' }
    & $python -B .\python\test_simz1_native_od.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo C529-B: contrato OD por viaje en routing nativo (sin simulacion).' }
    & $python -B .\python\test_simz1_active_retention.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo C529-C: retencion activa sin observaciones frescas (colas nativas sin simulacion).' }
    & $python -B .\python\test_simz1_retention_phases.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo C529-D: retencion entre fases e instalacion nativa OD/reservas (sin simulacion).' }
    & $python -B .\python\test_simz1_temporal_passage.py --preflights
    if ($LASTEXITCODE -ne 0) { throw 'Fallo factibilidad temporal, instalacion nativa o rechazo auditable de servicios fijos incompatibles.' }
    & $python -B .\python\test_simz1_l18_coordination.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo coordinacion sintetica local L18, paso nativo o paridad de servicios.' }
    & $python -B .\python\test_simz1_temporal_population.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo lectura serializada de rutas reparadas y sus parametros fisicos.' }
    & $python -B -m unittest discover -s python -p test_simz1_runtime_restart.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron regresiones de arranque/limpieza.' }
    & $python -B -m unittest discover -s python -p test_simz1_weekday_transit.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron regresiones de transporte entre semana.' }
    & $python -B -m unittest discover -s python -p test_simz1_freight.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo las pruebas de transporte pesado.' }
    foreach ($suite in @('test_simz1_freight_routes_v2.py', 'test_simz1_freight_version.py', 'test_simz1_freight_compact_v3.py', 'test_simz1_freight_gateways.py', 'test_simz1_compact_motion.py',
                        'test_simz1_freight_through_integration.py', 'test_simz1_freight_signals.py',
                        'test_inspect_simz1_freight_failure.py', 'test_simz1_freight_closure.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        if ($LASTEXITCODE -ne 0) { throw "Fallo el servicio de carga versionado: $suite" }
    }
    & $python -B -m unittest discover -s python -p test_simz1_blocking_occupancy.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la auditoria de bloqueo de paradas.' }
    & $python -B -m unittest discover -s python -p test_simz1_blocking_occupancy_indexed.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo equivalencia de indices de parada.' }
    & $python -B -m unittest discover -s python -p test_simz1_blocking_occupancy_single_queue.py -v
    $singleQueueExit=$LASTEXITCODE
    if ($singleQueueExit -ne 0) { throw 'Fallo reconstruccion FIFO de cola unica y sus controles negativos.' }
    & node python/test_simz1_blocking_occupancy.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la geometria de ocupacion y separacion.' }
    & node python/test_simz1_corridor_occupancy.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la continuidad de cuerpos y corredores.' }
    & node python/test_simz1_corridor_boundary.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la ocupacion entre corredores y las transiciones de parada.' }
    & node python/test_simz1_lane_body.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la reconstruccion del cuerpo completo en curvas y cambios de carriles.' }
    foreach ($suite in @('test_simz1_freight_replay.cjs', 'test_simz1_transit_replay.cjs', 'test_simz1_vehicle_card.cjs')) {
        & node (Join-Path $project ('python\' + $suite))
        if ($LASTEXITCODE -ne 0) { throw "Fallo dimensiones/etiquetas del replay: $suite" }
    }
    foreach ($suite in @('test_simz1_occupancy_audit.py','test_simz1_occupancy_replay.py',
                        'test_simz1_occupancy_reporting.py','test_simz1_physical_contract_20261027.py',
                        'test_simz1_queue_context.py','test_simz1_queue_support.py',
                        'test_simz1_causal_support_graph.py',
                        'test_simz1_checkpoint_contract.py','test_simz1_window_cache.py',
                        'test_simz1_checkpoint_library.py',
                        'test_simz1_queue_result_trust.py',
                        'test_simz1_checkpoint_pipeline.py',
                        'test_simz1_queue_component_schedule.py',
                        'test_simz1_queue_support_integration.py','test_simz1_stop_proxy.py',
                        'test_simz1_stop_queue_refinement.py','test_simz1_freight_midnight.py','test_simz1_signal_coordination.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        if ($LASTEXITCODE -ne 0) { throw "Fallo ocupacion fisica: $suite" }
    }
    foreach ($suite in @('test_simz1_transit_events.py', 'test_simz1_transit_xml.py', 'test_simz1_priority.py',
                        'test_simz1_priority_transit.py', 'test_simz1_priority_passage.py', 'test_simz1_revalidate.py')) {
        & $python -B -m unittest discover -s python -p $suite -v
        if ($LASTEXITCODE -ne 0) { throw "Fallo validacion de eventos/revalidacion: $suite" }
    }
    & $python -B -m unittest discover -s python -p test_simz1_demand_composition.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la composicion de vehiculos.' }
    & $python -B -m unittest discover -s python -p test_simz1_public_fleet_version.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la flota publica versionada.' }
    & $python -B -m unittest discover -s python -p test_simz1_balanced_demand.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la variante balanceada versionada.' }
    if ($OdMode -eq 'balanced-gateway-v1') {
        & $python -B -m unittest discover -s python -p test_simz1_origin_policy_contract.py -v -f
        $originContractExit = $LASTEXITCODE
        if ($originContractExit -ne 0) { throw 'Fallo identidad de variante de incorporacion, configuracion, huellas o ensayo compatible.' }
        & $python -B -m unittest discover -s python -p test_simz1_balanced_gateway_od.py -v -f
        if ($LASTEXITCODE -ne 0) { throw 'Fallo la validacion OD integrada de la nueva revision.' }
        & $python -B .\python\test_simz1_sequence_contract.py
        if ($LASTEXITCODE -ne 0) { throw 'Fallo el contrato OSM por secuencias o la evidencia exacta de fuente.' }
        & $python -B -m unittest discover -s python -p test_simz1_balanced_launch.py -v -f
        if ($LASTEXITCODE -ne 0) { throw 'Fallo el contrato nuevo de lanzamiento.' }
        & $python -B -m unittest discover -s python -p test_simz1_rescue_contracts.py -v -f
        if ($LASTEXITCODE -ne 0) { throw 'Fallo el contrato de argumentos/estados del rescate.' }
    }
    $fp = & $python -B .\python\simz1_workflow_state.py fingerprint
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo identificar la revision.' }
    if ($OdMode -eq 'balanced-gateway-v1' -and ($fp | Out-String).Trim() -cne ($validationStartFingerprint | Out-String).Trim()) {
        throw 'Las fuentes cambiaron durante Validate; no se publica aprobacion.'
    }
    $dir = Join-Path $project 'runtime\workflow'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $dir 'validated-source.txt'), ($fp | Out-String).Trim(), [System.Text.UTF8Encoding]::new($false))
    if ($OdMode -eq 'balanced-gateway-v1') {
        $receipt = @{schema_version=1; od_mode=$OdMode; source_fingerprint=($fp | Out-String).Trim();
            status='integrated_validate_pass'; completed_utc=[DateTime]::UtcNow.ToString('o')}
        [System.IO.File]::WriteAllText((Join-Path $dir 'validated-balanced-gateway-v1.json'),
            ($receipt | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
    }
    Write-Host 'VALIDACION DE ARRANQUE APROBADA. Solo componentes y QSim focales pequenos; ninguna masiva.' -ForegroundColor Green
    exit 0
}
$validated = Join-Path $project 'runtime\workflow\validated-source.txt'
if ($Action -in @('Clean','Run1000','RunMassive')) {
    if (-not (Test-Path -LiteralPath $validated)) { throw 'Ejecuta primero -Action Validate. No se borra ni simula nada.' }
    $fp = & $python -B .\python\simz1_workflow_state.py fingerprint
    if ($LASTEXITCODE -ne 0 -or [System.IO.File]::ReadAllText($validated).Trim() -ne ($fp | Out-String).Trim()) {
        throw 'La revision cambio desde Validate. Vuelve a verificarla antes de limpiar o simular.'
    }
}
if ($Action -eq 'Clean') {
    $plan = 'runtime/maintenance/reset-' + [guid]::NewGuid().ToString('N') + '.json'
    & $python -B .\scripts\maintenance\reset_simz1_runs.py --plan $plan
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo inventariar; no se borra nada.' }
    $reviewedPlanHash = (Get-FileHash -LiteralPath $plan -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Plan para revisar: $plan | SHA256: $reviewedPlanHash"
    Write-Warning 'Se eliminaran eventos, SQLite, PNG y CSV de las corridas LISTADAS. Solo se conservan sus manifiestos. Las omitidas y las fuentes permanecen.'
    $answer = Read-Host 'Revisa la lista. Escribe BORRAR CORRIDAS SIMZ1 para aplicar, o Enter para cancelar'
    if ($answer -cne 'BORRAR CORRIDAS SIMZ1') { Write-Host 'Cancelado; ningun resultado eliminado.'; return }
    & $python -B .\scripts\maintenance\reset_simz1_runs.py --plan $plan --apply --confirm $answer --plan-sha256 $reviewedPlanHash
    if ($LASTEXITCODE -ne 0) { throw 'Limpieza detenida; revisar el registro. No iniciar otra corrida automaticamente.' }
    Write-Host 'LIMPIEZA TERMINADA. Las carpetas omitidas NO fueron borradas.' -ForegroundColor Green
    return
}
if ($Action -in @('Run1000','RunMassive')) {
    if ($OdMode -eq 'balanced-gateway-v1' -and $Action -ne 'Run1000') {
        throw 'Use run_simz1_110k_balanced_gateway.ps1 para el lanzamiento de 110000; sin fallback de rango historico.'
    }
    if ($OdMode -eq 'balanced-gateway-v1') {
        $receiptPath = Join-Path $project 'runtime\workflow\validated-balanced-gateway-v1.json'
        $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($receipt.status -ne 'integrated_validate_pass' -or $receipt.od_mode -ne $OdMode -or
            $receipt.source_fingerprint -cne ($fp | Out-String).Trim()) { throw 'Falta Validate integrado de esta revision OD.' }
    }
    if (-not $AcceptTransitRouteAssumptions) { throw 'Se requiere -AcceptTransitRouteAssumptions para los supuestos documentados de buses.' }
    & $python -B .\python\simz1_runtime_check.py --classpath-file .\target\simz1-runtime-classpath.txt
    if ($LASTEXITCODE -ne 0) { throw 'Clases ausentes/incompatibles; repetir Validate.' }
    if ($Action -eq 'RunMassive') {
        & $python -B .\python\simz1_workflow_state.py require-trial
        if ($LASTEXITCODE -ne 0) { throw 'La prueba de 1000 no acredita este codigo. No se inicia la masiva.' }
        $minimum = 180000; $maximum = 220000; $free = 30
    } else { $minimum = 1000; $maximum = 1000; $free = 10 }
    $prefix = if ($Action -eq 'Run1000') { 'run-1000-' } else { 'run-massive-' }
    $run = Join-Path $project ('scenarios\zona1\montecarlo\' + $prefix + [guid]::NewGuid().ToString('N'))
    $parameters = @('-NoProfile','-ExecutionPolicy','Bypass','-File', (Join-Path $PSScriptRoot 'run_simz1_with_analysis.ps1'),
        '-MinAgents', [string]$minimum, '-MaxAgents', [string]$maximum, '-Seed',[string]$Seed, '-Iterations','1',
        '-ServiceDate',$ServiceDate,'-AcceptTransitRouteAssumptions','-MinFreeGiB',[string]$free,'-NewRunDir',$run,
        '-TransitService',(Join-Path $project 'scenarios\zona1\transit\weekday-v2\service-fleet-176-93-v1.json'),
        '-ShortLinkSignalCoordination',$ShortLinkSignalCoordination, '-AgentCatalog',$AgentCatalog, '-DestinationPolicy',$DestinationPolicy)
    if ($OdMode -eq 'balanced-gateway-v1') {
        $parameters += @('-OdMode',$OdMode,'-OriginPolicy','lane-length-access-v1',
            '-ZoneBoundary',$ZoneBoundary,'-OdAccessCatalog',$OdAccessCatalog,'-OdMixFile',$OdMixFile)
        Assert-SimZ1PathArguments $parameters @{ZoneBoundary=$ZoneBoundary;OdAccessCatalog=$OdAccessCatalog;OdMixFile=$OdMixFile}
    } elseif ($ZoneBoundary -or $OdAccessCatalog -or $OdMixFile) { throw 'Network no puede ignorar insumos de gateways.' }
    Write-Host "RESULTADOS DE ESTA EJECUCION: $run" -ForegroundColor Cyan
    if ($NoFreightTransport) { $parameters += '-NoFreightTransport' }
    else {
        $parameters += @('-FreightService', $FreightService)
        if ($FreightServiceDate) { $parameters += @('-FreightServiceDate', $FreightServiceDate) }
        if ($PSBoundParameters.ContainsKey('FreightVehicles')) { $parameters += @('-FreightVehicles', [string]$FreightVehicles) }
    }
    & powershell.exe @parameters -DryRun
    if ($LASTEXITCODE -ne 0) { throw 'Fallo preflight; no se ejecuta MATSim.' }
    & powershell.exe @parameters
    if ($LASTEXITCODE -ne 0) { throw "La corrida o su calidad requieren revision; conservar $run" }
    if ($Action -eq 'Run1000') {
        if ($OdMode -eq 'balanced-gateway-v1') {
            $afterTrial = & $python -B .\python\simz1_workflow_state.py fingerprint
            if ($LASTEXITCODE -ne 0 -or ($afterTrial | Out-String).Trim() -cne ($fp | Out-String).Trim()) {
                throw 'Las fuentes cambiaron durante Run1000; no se registra aprobacion.'
            }
        }
        $recordArgs = @('-B','.\python\simz1_workflow_state.py','record-trial','--run-dir',$run)
        if ($OdMode -eq 'balanced-gateway-v1') { $recordArgs += @('--state','runtime\workflow\trial-balanced-gateway-v1.json') }
        & $python @recordArgs
        if ($LASTEXITCODE -ne 0) { throw 'Los archivos quedaron guardados, pero la flota/calidad NO autorizan escalar.' }
    }
    Write-Host "CORRIDA Y GRAFICAS TERMINADAS: $run" -ForegroundColor Green
    if ($OdMode -eq 'balanced-gateway-v1') {
        Write-Host "Reportes OD: .venv\Scripts\python.exe -B python\simz1_balanced_launch_report.py --run-dir '$run'. Replay historico no habilitado."
    } else { Write-Host "Para ver esta corrida: .\scripts\simz1_workflow.ps1 -Action View -RunDir '$run'" }
    return
}
# View: explicit folder or the exact successful 1000-person trial, never newest directory by date.
if (-not $RunDir) {
    $RunDir = & $python -B .\python\simz1_workflow_state.py path
    if ($LASTEXITCODE -ne 0) { throw 'Indica -RunDir de una corrida valida o completa Run1000.' }
}
$run = (Resolve-Path -LiteralPath $RunDir).Path
$manifest = Get-Content -LiteralPath (Join-Path $run 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.status -ne 'completed' -or $manifest.validation.status -ne 'valid') { throw 'No se abre un resultado fallido o incompleto.' }
$selectedIteration = if ($PSBoundParameters.ContainsKey('Iteration')) { [int]$Iteration } else { [int]$manifest.iterations.last }
$replay = Join-Path $run 'webgl-continuo'
# Validates sqlite-source-manifest.json even when it already exists, protects an
# active exporter, and resumes only finalized compatible checkpoints.
& $python -B .\scripts\replay\prepare_replay.py --run-dir $run --iteration $selectedIteration --sqlite-budget-gib $SQLiteBudgetGiB --scratch-budget-gib $ScratchBudgetGiB
if ($LASTEXITCODE -ne 0) { throw 'Preparacion visual detenida; conservar parciales. La URL anterior no acredita la corrida solicitada.' }
Write-Host "Inicio del servidor y comprobacion HTTP: $($manifest.run_id), iteracion $selectedIteration, puerto $Port" -ForegroundColor Cyan
& .\scripts\replay\start_replay.ps1 -RunDir $run -Iteration $selectedIteration -ReplayDir $replay -Port $Port -ReplaceSimZ1 -NoBrowser:$NoBrowser
