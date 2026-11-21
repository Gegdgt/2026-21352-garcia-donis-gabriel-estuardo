"""SimZ1 preflight using MATSim 15.0 defaults; never repairs invalid options."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

SIMZ1_LAUNCH_MAIN_CLASS = 'gt.edu.uvg.sim.zona1.RunZona1Simulation'


class ConfigurationError(ValueError):
    """A rejected simulation configuration, before QSim starts."""


def admission_execution_contract(requested, effective=None, *, expected_receipt_route_coverage_policy=None):
    """Verify a future launcher configuration, not evidence of a running QSim.

    Generic validation still interprets missing historical policies as native.
    A launch must materialize its policy so different Java entry-point defaults
    cannot change the requested behavior. No historical configuration is edited.
    """
    def inspect(source):
        root = ET.parse(source).getroot() if isinstance(source, (str, Path)) else source
        policy = root.find("module[@name='simz1Admission']/param[@name='storagePolicy']")
        if policy is None:
            raise ConfigurationError('Configuracion invalida: el launcher requiere simz1Admission.storagePolicy '
                                     'explicita; prepare una corrida nueva con --storage-policy')
        return validate_configuration(root)

    requested_audit = inspect(requested)
    audit = requested_audit if effective is None else inspect(effective)
    for key in ('admission_policy', 'origin_admission_policy', 'qsim_threads', 'remove_stuck_vehicles', 'stuck_time_seconds', 'whole_vehicle_reservation'):
        if audit[key] != requested_audit[key]:
            raise ConfigurationError(f'MATSim cambio el contrato de admision: {key}')
    strict = audit['admission_policy'] == 'strict-receiver-v1'
    if expected_receipt_route_coverage_policy not in (None, 'planned_contiguous_prefix_v1', 'planned_stopping_prefix_v2') or (
            expected_receipt_route_coverage_policy is not None and not audit['whole_vehicle_reservation']):
        raise ConfigurationError('Contrato de alcance de ruta incompatible con la reserva solicitada')
    return dict(schema_version='simz1-admission-execution-v1',
                entry_point=SIMZ1_LAUNCH_MAIN_CLASS,
                storage_policy=audit['admission_policy'], policy_explicit=True,
                origin_policy=audit['origin_admission_policy'],
                qsim_threads=audit['qsim_threads'], remove_stuck_vehicles=audit['remove_stuck_vehicles'],
                stuck_time_seconds=audit['stuck_time_seconds'],
                receiver_rejection='WAIT' if strict else 'native-timeout-policy',
                force_after_stuck_time=not strict and not audit['remove_stuck_vehicles'],
                verification='effective_config_matches' if effective is not None else 'requested_config_only',
                native_execution_proven=False,
                occupancy_policy='corridor-length-v1' if audit['whole_vehicle_reservation'] else 'native-pcu',
                expected_receipt_route_coverage_policy=expected_receipt_route_coverage_policy,
                positionsObserved=False,
                evidence='output_config.xml' if effective is not None else 'config-simz1.xml',
                note='La configuracion no demuestra seguimiento continuo, ejecucion sin deadlock ni rendimiento con cuatro hilos')


def validate_configuration(source):
    try:
        root = ET.parse(source).getroot() if isinstance(source, (str, Path)) else source
    except ET.ParseError as exc:
        raise ConfigurationError(f'Configuracion invalida: XML de configuracion mal formado: {exc}') from exc
    values = {f"{m.get('name')}.{p.get('name')}": p.get('value')
              for m in root.findall('module') for p in m.findall('param')}

    def boolean(key, default):
        value = values.get(key, default)
        if value not in ('true', 'false'):
            raise ConfigurationError(f'Configuracion invalida: {key} debe ser true o false: {value!r}')
        return value == 'true'

    calculate = boolean('travelTimeCalculator.calculateLinkToLinkTravelTimes', 'false')
    separate_modes = boolean('travelTimeCalculator.separateModes', 'true')
    routing = boolean('controler.enableLinkToLinkRouting', 'false')
    remove = boolean('qsim.removeStuckVehicles', 'false')
    lanes = boolean('qsim.useLanes', 'false')
    signals = boolean('signalsystems.useSignalsystems', 'false')
    fast_capacity = boolean('qsim.usingFastCapacityUpdate', 'true')
    incidents = boolean('zona1Diagnostics.incidentsEnabled', 'true')
    # This is a different module from legacy whole-link perturbations. The
    # Prompt 7 detector is fixture-only and no lane-residency adapter is installed.
    # Reject activation before preparing/running a scenario, never silently
    # downgrade a requested physical closure to a graphical indicator.
    consequence_modules = root.findall("module[@name='simz1IncidentConsequences']")
    if len(consequence_modules) > 1:
        raise ConfigurationError('Configuracion invalida: simz1IncidentConsequences duplicado')
    if consequence_modules:
        params = consequence_modules[0].findall('param')
        names = [p.get('name') for p in params]
        if len(set(names)) != len(names) or set(names) - {'enabled', 'durationSeconds'}:
            raise ConfigurationError('Configuracion invalida: parametros de simz1IncidentConsequences duplicados o desconocidos')
    consequences = boolean('simz1IncidentConsequences.enabled', 'false')
    duration = values.get('simz1IncidentConsequences.durationSeconds', '1800')
    if duration != '1800':
        raise ConfigurationError('Configuracion invalida: simz1IncidentConsequences.durationSeconds debe ser 1800')
    if consequences:
        raise ConfigurationError('INCIDENT_CONSEQUENCES_UNAVAILABLE: faltan el adaptador nativo de carril, '
                                 'el observador de parejas y el catalogo verificado; no se habilita un bloqueo grafico')
    lane_modules = root.findall("module[@name='simz1LanePolicy']")
    lane_settings = {'minimumAdvanceM': 8, 'minimumGapM': 2, 'slowSpeedMps': 8.33, 'lookaheadSeconds': 5}
    if len(lane_modules) > 1:
        raise ConfigurationError('Configuracion invalida: simz1LanePolicy duplicado')
    if lane_modules:
        names = [p.get('name') for p in lane_modules[0].findall('param')]
        if len(set(names)) != len(names) or set(names) - {'enabled', *lane_settings}:
            raise ConfigurationError('Configuracion invalida: parametros de simz1LanePolicy duplicados o desconocidos')
    lane_policy_enabled = boolean('simz1LanePolicy.enabled', 'false')
    for key, default in lane_settings.items():
        try:
            value = float(values.get('simz1LanePolicy.'+key, str(default)))
            if not math.isfinite(value) or value <= 0:
                raise ValueError()
            if key == 'minimumGapM' and value < .10:
                raise ConfigurationError('Configuracion invalida: simz1LanePolicy.minimumGapM debe ser al menos 0.10 m')
            lane_settings[key] = value
        except (TypeError, ValueError):
            raise ConfigurationError(f'Configuracion invalida: simz1LanePolicy.{key} debe ser finito y positivo') from None
    if lane_policy_enabled:
        raise ConfigurationError('LANE_POLICY_UNAVAILABLE: faltan estado microscopico nativo de carriles, '
                                 'almacenamiento por vehiculo, reserva y transferencia atomicas de envolvente, '
                                 'reglas de carril importadas y eventos de cambio confirmados; '
                                 'la politica aislada no puede mover vehiculos QSim')
    priority = dict(enabled=boolean('zona1Priority.enabled', 'true'),
                    classification=values.get('zona1Priority.classification', 'osm-hierarchy'),
                    conflicts=values.get('zona1Priority.conflicts', 'geometric'))
    # Missing in historical XML means the former native branch, not the new
    # SimZ1 entry point's future default. Never relabel an old run as strict.
    admission_modules = root.findall("module[@name='simz1Admission']")
    if len(admission_modules) > 1:
        raise ConfigurationError('Configuracion invalida: simz1Admission duplicado')
    if admission_modules:
        names = [p.get('name') for p in admission_modules[0].findall('param')]
        if len(set(names)) != len(names) or set(names) - {'storagePolicy', 'wholeVehicleReservation', 'originPolicy'}:
            raise ConfigurationError('Configuracion invalida: parametros de simz1Admission duplicados o desconocidos')
    admission = values.get('simz1Admission.storagePolicy', 'matsim15-native')
    from simz1_scale_contract import LEGACY_ORIGIN_POLICY, GAP_ORIGIN_POLICY
    origin_admission = values.get('simz1Admission.originPolicy', LEGACY_ORIGIN_POLICY)
    if origin_admission not in (LEGACY_ORIGIN_POLICY, GAP_ORIGIN_POLICY):
        raise ConfigurationError('Configuracion invalida: simz1Admission.originPolicy desconocida')
    if origin_admission == GAP_ORIGIN_POLICY and (
            admission != 'strict-receiver-v1' or
            values.get('simz1Admission.wholeVehicleReservation', 'false') != 'true' or
            values.get('qsim.numberOfThreads', '1') != '1' or
            values.get('qsim.trafficDynamics', 'queue') != 'queue' or
            values.get('qsim.linkDynamics', 'FIFO') != 'FIFO'):
        raise ConfigurationError('physical-gap-origin-v1 requires strict receiver, whole-body reservation, one QSim thread, queue dynamics and FIFO')
    if values.get('simz1Admission.wholeVehicleReservation', 'false') not in ('true', 'false'):
        raise ConfigurationError('Configuracion invalida: wholeVehicleReservation debe ser booleano')
    if values.get('simz1Admission.wholeVehicleReservation') == 'true' and values.get('qsim.numberOfThreads','1') != '1':
        raise ConfigurationError('wholeVehicleReservation requiere qsim.numberOfThreads=1 para reserva atomica')
    if values.get('simz1Admission.wholeVehicleReservation') == 'true' and admission != 'strict-receiver-v1':
        raise ConfigurationError('wholeVehicleReservation requiere strict-receiver-v1')
    if admission not in ('matsim15-native', 'strict-receiver-v1'):
        raise ConfigurationError('Configuracion invalida: simz1Admission.storagePolicy desconocida')
    if admission == 'strict-receiver-v1' and remove:
        raise ConfigurationError('Configuracion invalida: strict-receiver-v1 es incompatible con '
                                 'removeStuckVehicles=true; el receptor bloqueado debe mantener WAIT')
    if priority['classification'] not in ('osm-hierarchy', 'osm-name-orientation', 'orientation', 'explicit') or priority['conflicts'] not in ('geometric','conservative','verified-node-table'):
        raise ConfigurationError('Configuracion invalida: politica zona1Priority desconocida')
    try:
        priority['stop_seconds'] = float(values.get('zona1Priority.stopSeconds', '5'))
        if not math.isfinite(priority['stop_seconds']) or priority['stop_seconds'] < 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigurationError('Configuracion invalida: priority stopSeconds debe ser finito y no negativo') from None
    try:
        priority['max_yield_seconds'] = float(values.get('zona1Priority.maxYieldSeconds', '30'))
        if not math.isfinite(priority['max_yield_seconds']) or priority['max_yield_seconds'] < 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigurationError('Configuracion invalida: priority maxYieldSeconds debe ser finito y no negativo') from None
    boolean('zona1WithinDayRouting.enabled', 'true')
    if calculate and remove:
        raise ConfigurationError('Configuracion invalida: calculateLinkToLinkTravelTimes=true es incompatible '
                                 'con removeStuckVehicles=true en MATSim 15.0; no se cambian automaticamente')
    if calculate and separate_modes:
        raise ConfigurationError('Configuracion invalida: calculateLinkToLinkTravelTimes=true es incompatible '
                                 'con travelTimeCalculator.separateModes=true en MATSim 15.0')
    if routing and not calculate:
        raise ConfigurationError('Configuracion invalida: enableLinkToLinkRouting=true requiere '
                                 'calculateLinkToLinkTravelTimes=true')
    if lanes and values.get('network.laneDefinitionsFile') in (None, '', 'null'):
        raise ConfigurationError('Carriles activados sin network.laneDefinitionsFile')
    threads = values.get('qsim.numberOfThreads', '1')
    try:
        if str(int(threads)) != threads or int(threads) <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigurationError('Configuracion invalida: qsim.numberOfThreads debe ser un entero positivo') from None
    stuck = values.get('qsim.stuckTime', '10')
    try:
        parts = list(map(float, stuck.split(':')))
        stuck_seconds = parts[0] if len(parts) == 1 else sum(v * f for v, f in zip(parts, (3600, 60, 1)))
        if len(parts) not in (1, 3) or not math.isfinite(stuck_seconds) or stuck_seconds < 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigurationError('Configuracion invalida: qsim.stuckTime debe ser un tiempo finito no negativo') from None
    return dict(status='valid', matsim_version='15.0', use_lanes=lanes, signals_enabled=signals,
                incidents_enabled=incidents, qsim_threads=int(threads), remove_stuck_vehicles=remove,
                incident_consequences=dict(requested_enabled=False, installed=False,
                    implementation='fixture_only', duration_seconds=1800,
                    physics_effect='none', production_activation='rejected',
                    pending=['native_lane_residency_adapter', 'native_paired_observer', 'verified_conflict_registry']),
                lane_policy=dict(requested_enabled=False, installed=False, implementation='isolated_decision_component',
                    production_activation='rejected', parameters=lane_settings,
                    pending=['native_microscopic_lane_state', 'vehicle_aware_storage',
                             'atomic_swept_envelope_reservation_and_transfer', 'network_lane_rule_import',
                             'committed_lane_change_events']),
                unsignalized_priority=priority,
                admission_policy=admission,
                origin_admission_policy=origin_admission,
                whole_vehicle_reservation=values.get('simz1Admission.wholeVehicleReservation','false') == 'true',
                using_fast_capacity_update=fast_capacity,
                stuck_time_seconds=stuck_seconds, link_to_link_routing=routing,
                calculate_link_to_link_travel_times=calculate,
                separate_travel_time_modes=separate_modes,
                physical_stability_proven=False,
                note=('strict-receiver-v1 conserva WAIT cuando el receptor rechaza; stuckTime no autoriza FORCE. '
                      if admission == 'strict-receiver-v1' else
                      'En matsim15-native, removeStuckVehicles=false no impide FORCE al superar stuckTime. ')
                     + 'La consistencia de configuracion no demuestra distancias continuas ni ausencia de gridlock')
