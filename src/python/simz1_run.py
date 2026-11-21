"""Contrato de corridas SimZ1: procedencia, validacion y seleccion sin fallbacks."""
import csv
import gzip
import hashlib
import json
import math
import os
import sys
from pathlib import Path
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from simz1_event_validation import MovementAudit, enabled_lane_movements, unfinished_counts
from simz1_config_validation import validate_configuration, admission_execution_contract
from simz1_lane_validation import audit_configuration, read_lanes
from simz1_native_validation import NativeDecisionAudit
from simz1_trip_audit import TripAudit
from simz1_temporal import trip_id

PROJECT = Path(__file__).resolve().parents[1]
LATEST = PROJECT/'scenarios/zona1/montecarlo/latest-successful.json'
MANIFEST = 'run-manifest.json'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers can briefly deny DELETE sharing. Retry only the same
        # atomic rename; never delete/copy the destination or expose partial JSON.
        for attempt in range(21):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                if os.name != 'nt' or error.winerror not in (5,32) or attempt == 20: raise
                time.sleep(.01)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_atomic_json(path):
    for attempt in range(21):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except PermissionError as error:
            if os.name != 'nt' or getattr(error,'winerror',None) not in (None,5,32) or attempt == 20: raise
            time.sleep(.01)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def xml_elements(path, tag, root_tag):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        if root.tag != root_tag:
            raise ValueError(f'Raiz XML incorrecta: {path}; se esperaba {root_tag}')
        for action, element in context:
            if action == 'end' and element.tag == tag:
                yield element
                element.clear()
                root.clear()


def population(path, expected_trips_per_person=None, *, allow_empty=False):
    from simz1_freight import is_freight
    ids, trips, legs = set(), 0, 0
    freight_count = 0
    cohorts = {}
    for person in xml_elements(path, 'person', 'population'):
        ident = person.get('id')
        if not ident or ident in ids:
            raise ValueError(f'Persona sin ID o duplicada en {path}')
        ids.add(ident)
        if is_freight(person):
            freight_count += 1
            continue
        cohort = person.findtext("attributes/attribute[@name='simz1PopulationCohort']")
        cohorts[cohort] = cohorts.get(cohort, 0) + 1
        plans = person.findall('plan')
        selected = [p for p in plans if p.get('selected') == 'yes']
        if len(selected) == 1:
            plan = selected[0]
        elif len(plans) == 1:
            plan = plans[0]
        else:
            raise ValueError(f'Plan seleccionado ambiguo: {ident}')
        legs += len(plan.findall('leg'))
        if expected_trips_per_person is not None:
            ledger = json.loads(person.findtext("attributes/attribute[@name='simz1Trips']",'null'))
            if (not isinstance(ledger,list) or len(ledger)!=expected_trips_per_person or
                    [t.get('id') for t in ledger] != [trip_id(ident,i+1) for i in range(expected_trips_per_person)] or
                    len(plan.findall('leg')) != expected_trips_per_person):
                raise ValueError(f'Identidad/cantidad de viajes incompatible: {ident} en {path}')
            activities=[a for a in plan if a.tag in ('activity','act')]
            if len(activities)!=len(ledger)+1 or any(
                    t['origin_link']!=activities[i].get('link') or t['destination_link']!=activities[i+1].get('link')
                    for i,t in enumerate(ledger)):
                raise ValueError(f'OD de viajes incompatible: {ident} en {path}')
        main_activities = [a for a in plan if a.tag in ('act', 'activity')
                           and not a.get('type', '').endswith(' interaction')]
        trips += max(0, len(main_activities)-1)
    if not ids and not allow_empty:
        raise ValueError(f'Poblacion vacia: {path}')
    counts = dict(planned_persons=len(ids)-freight_count, planned_trips=trips, planned_legs=legs)
    if set(cohorts) != {None}:
        if not set(cohorts) <= {'main', 'warmup_context', 'post_context'}:
            raise ValueError('Poblacion con cohortes ausentes o desconocidas: '+str(path))
        counts.update(principal_cohort_persons=cohorts.get('main', 0),
                      warmup_context_persons=cohorts.get('warmup_context', 0),
                      post_context_persons=cohorts.get('post_context', 0),
                      context_persons=sum(n for key,n in cohorts.items() if key != 'main'),
                      all_private_persons=len(ids))
    return ids, counts


def parameters(path):
    root = ET.parse(path).getroot()
    return {f"{m.get('name')}.{p.get('name')}": p.get('value')
            for m in root.findall('module') for p in m.findall('param')}


def config_changes(before, after, reason):
    return [dict(parameter=key, before=before.get(key), after=after.get(key), reason=reason)
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def seconds(value):
    if ':' not in value:
        return float(value)
    h, m, s = map(float, value.split(':'))
    return h*3600+m*60+s


def artifact(directory, path):
    path = Path(path).resolve()
    return dict(path=path.relative_to(directory).as_posix(), sha256=sha256(path))


def create_manifest(directory, demand_seed, overrides, *, publish=True, allow_empty=False):
    """Build verified provenance; generators can publish once after adding all demand metadata."""
    directory = Path(directory).resolve()
    config = directory/'config-simz1.xml'
    params = parameters(config)
    _, counts = population(directory/'plans.xml', allow_empty=allow_empty)
    from simz1_transit_accounting import planned_transit_counts
    transit = planned_transit_counts(config, counts['planned_persons'])
    # New manifests only: B and internal drivers must never inflate generated people.
    counts.update({key: transit[key] for key in (
        'road_demand_persons', 'public_transport_vehicles_configured',
        'public_transport_departures_scheduled', 'transit_drivers_added_to_demand')})
    first, last = (int(params[f'controler.{name}Iteration']) for name in ('first', 'last'))
    inputs = {name: artifact(directory, directory/params[key]) for name, key in (
        ('network', 'network.inputNetworkFile'), ('plans', 'plans.inputPlansFile'))}
    inputs['config'] = artifact(directory, config)
    if transit['enabled']:
        for name, key in [('transit_schedule', 'transit.transitScheduleFile'),
                          ('transit_vehicles', 'transit.vehiclesFile')]:
            path = Path(params[key])
            # artifact() also rejects paths outside this new run; never copy a historical input.
            inputs[name] = artifact(directory, path if path.is_absolute() else directory / path)
    # Freeze and fingerprint ancillary inputs as well (lanes, signals, vehicles, facilities).
    for path in sorted((directory/'inputs').rglob('*')):
        if path.is_symlink():
            raise ValueError('Un input de corrida no puede ser un enlace simbolico: '+str(path))
        if path.is_file():
            inputs['input:'+path.relative_to(directory/'inputs').as_posix()] = artifact(directory, path)
    result = dict(schema_version=1, run_id=f'simz1-{uuid.uuid4().hex}', folder=str(directory),
                  demand_seed=demand_seed, matsim_seed=int(params['global.randomSeed']),
                  counts=counts, public_transport=transit, inputs=inputs, configuration_overrides=overrides,
                  time_horizon=dict(start_seconds=seconds(params['qsim.startTime']),
                                    end_seconds=seconds(params['qsim.endTime'])),
                  iterations=dict(first=first, last=last, requested=last-first+1, completed=[]),
                  status='prepared', validation=dict(status='pending'), results={})
    if publish:
        atomic_json(directory/MANIFEST, result)
    return result


def checked_path(directory, record):
    path = (directory/record['path']).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f'Archivo ausente o fuera de la corrida: {path}')
    if sha256(path) != record['sha256']:
        raise ValueError(f'Hash no coincide; archivo cambiado o de otra corrida: {path}')
    return path


def load_manifest(directory):
    directory = Path(directory).resolve()
    path = directory/MANIFEST
    if not path.is_file():
        raise ValueError(f'No hay manifiesto SimZ1: {path}. Ejecute ejecutar_simz1.py; no se usan salidas historicas.')
    result = read_atomic_json(path)
    if result.get('schema_version') != 1 or Path(result['folder']).resolve() != directory:
        raise ValueError(f'Manifiesto incompatible con la carpeta: {directory}')
    return result


def lane_policy_source(directory, manifest):
    """Resolve the same fingerprinted OSM evidence at preparation/run/export."""
    record = manifest['inputs'].get('osm_turn_policy_source') or manifest['inputs'].get('od_source_osm')
    policy = manifest.get('lane_configuration_validation', {}).get('turn_policy')
    if record is None:
        if policy:
            raise ValueError('Falta el artefacto OSM de la politica de giros de esta corrida')
        return None
    path = checked_path(Path(directory).resolve(), record)
    if policy and record['sha256'] != policy['source_osm']['sha256']:
        raise ValueError('El artefacto OSM difiere de la politica de giros preparada')
    return path


def completed_iterations(output):
    with (Path(output)/'stopwatch.txt').open(encoding='utf-8-sig') as stream:
        return [int(row['Iteration']) for row in csv.DictReader(stream, delimiter='\t')
                if row.get('END iteration', '').strip()]


def metric_files(output):
    return [p for p in sorted(Path(output).rglob('*')) if p.is_file() and
            (p.name in ('scorestats.txt', 'stopwatch.txt', 'traveltimes.txt') or
             p.name.endswith(('.legdurations.txt', '.traveltimes.txt', '.legs.csv.gz')))]


def validate_outputs(directory, manifest, *, implementation_compatibility=None):
    """Solo tras exit=0: XML completo, identidad de poblacion/red y END iteration."""
    if manifest.get('balanced_od') is not None:
        from simz1_balanced_od_audit import require_native_success
        require_native_success(manifest)
    directory = Path(directory).resolve()
    for record in manifest['inputs'].values():
        checked_path(directory, record)
    output = directory/'output'
    required = ['output_network.xml.gz', 'output_events.xml.gz', 'output_plans.xml.gz',
                'output_config.xml', 'stopwatch.txt']
    missing = [name for name in required if not (output/name).is_file()]
    if missing:
        raise RuntimeError(f'MATSim termino sin salidas esperadas: {missing}')
    completed = completed_iterations(output)
    manifest['iterations']['completed'] = completed
    expected = list(range(manifest['iterations']['first'], manifest['iterations']['last']+1))
    if completed != expected:
        raise ValueError(f'Iteraciones incompletas: esperadas {expected}; completadas {completed}')
    effective = parameters(output/'output_config.xml')
    # Pin the vehicle definitions actually loaded by QSim for future replay.
    if (output/'output_vehicles.xml.gz').is_file():
        from simz1_motion import read_vehicles
        read_vehicles(output/'output_vehicles.xml.gz')
        manifest['effective_vehicles'] = artifact(directory, output/'output_vehicles.xml.gz')
    requested = parameters(directory/'config-simz1.xml')
    if requested.get('simz1Admission.wholeVehicleReservation', 'false') != effective.get('simz1Admission.wholeVehicleReservation', 'false'):
        raise ValueError('MATSim cambio el contrato simz1Admission.wholeVehicleReservation')
    manifest['effective_configuration_validation'] = validate_configuration(output/'output_config.xml')
    if 'admission_execution' in manifest:
        manifest['admission_execution'] = admission_execution_contract(
            directory/'config-simz1.xml', output/'output_config.xml',
            expected_receipt_route_coverage_policy=manifest['admission_execution'].get('expected_receipt_route_coverage_policy'))
    # Check the actual serialized Scenario, not only ID connectivity. MATSim
    # exports the loaded lane graph even when its use in QSim is disabled.
    osm_source = lane_policy_source(directory, manifest)
    requested_lane_audit = audit_configuration(directory/'config-simz1.xml', osm_path=osm_source)
    actual_lane_file = output/'output_lanes.xml.gz'
    actual_signal_file = output/'output_signal_systems_v2.0.xml.gz'
    if requested_lane_audit['use_lanes'] and not actual_lane_file.is_file():
        raise ValueError('MATSim termino sin output_lanes.xml.gz para carriles habilitados')
    if requested_lane_audit['signals_enabled'] and not actual_signal_file.is_file():
        raise ValueError('MATSim termino sin output_signal_systems_v2.0.xml.gz para señales habilitadas')
    for key in ('network.inputNetworkFile', 'network.laneDefinitionsFile',
                'transit.transitScheduleFile', 'transit.vehiclesFile',
                'signalsystems.signalsystems', 'signalsystems.signalgroups', 'signalsystems.signalcontrol',
                'signalsystems.ambertimes', 'signalsystems.intergreentimes', 'signalsystems.conflictingDirections'):
        before, after = requested.get(key), effective.get(key)
        if before not in (None, '', 'null') and (after in (None, '', 'null') or
                (directory/before).resolve() != (directory/after).resolve()):
            raise ValueError(f'MATSim cargo una referencia de otra corrida: {key}')
    actual_lane_audit = audit_configuration(output/'output_config.xml',
                                          network_path=output/'output_network.xml.gz',
                                          lanes_path=actual_lane_file if actual_lane_file.is_file() else None,
                                          signals_path=actual_signal_file if actual_signal_file.is_file() else None,
                                          osm_path=osm_source)
    if actual_lane_audit['baseline_parameters'] != requested_lane_audit['baseline_parameters']:
        raise ValueError('QSim cambio parametros de discretizacion/almacenamiento/flujo de esta corrida')
    for kind in ('network', 'lanes', 'signals'):
        if requested_lane_audit['signatures'][kind] != actual_lane_audit['signatures'][kind]:
            raise ValueError(f'El {kind} cargado por MATSim no coincide con esta corrida (geometria/colas/señales)')
    if requested_lane_audit['signatures'].get('osm_provenance') != actual_lane_audit['signatures'].get('osm_provenance'):
        raise ValueError('La procedencia OSM cargada por MATSim difiere de la politica de giros de esta corrida')
    actual_lane_audit['loaded_artifacts'] = {
        kind: artifact(directory, path) for kind, path in
        (('network', output/'output_network.xml.gz'), ('lanes', actual_lane_file), ('signals', actual_signal_file))
        if path.is_file()}
    manifest['effective_lane_configuration_validation'] = actual_lane_audit
    for key in ('global.randomSeed', 'controler.firstIteration', 'controler.lastIteration',
                'qsim.useLanes', 'zona1WithinDayRouting.enabled', 'zona1WithinDayRouting.agentShare'):
        if effective.get(key) != requested.get(key):
            raise ValueError(f'MATSim cambio una opcion explicita: {key}')
    budget_key = 'zona1WithinDayRouting.maxReroutesPerStep'
    if budget_key in requested and effective.get(budget_key) != requested[budget_key]:
        raise ValueError(f'MATSim cambio una opcion explicita: {budget_key}')
    for key in ('signalsystems.useSignalsystems', 'zona1Diagnostics.incidentsEnabled',
                'transit.useTransit',
                'zona1WithinDayRouting.routingPolicy',
                'zona1Priority.enabled', 'zona1Priority.classification', 'zona1Priority.conflicts',
                'simz1Admission.storagePolicy', 'simz1Admission.wholeVehicleReservation',
                'qsim.numberOfThreads', 'qsim.removeStuckVehicles',
                'qsim.usingFastCapacityUpdate',
                'travelTimeCalculator.calculateLinkToLinkTravelTimes', 'travelTimeCalculator.separateModes',
                'controler.enableLinkToLinkRouting'):
        if key in requested and effective.get(key) != requested[key]:
            raise ValueError(f'MATSim cambio una opcion explicita: {key}')
    if 'qsim.stuckTime' in requested and seconds(effective['qsim.stuckTime']) != seconds(requested['qsim.stuckTime']):
        raise ValueError('MATSim cambio una opcion explicita: qsim.stuckTime')
    for key in ('zona1Priority.stopSeconds', 'zona1Priority.maxYieldSeconds'):
        if key in requested and float(effective[key]) != float(requested[key]):
            raise ValueError(f'MATSim cambio una opcion explicita: {key}')
    for key in ('qsim.startTime', 'qsim.endTime'):
        if seconds(effective[key]) != seconds(requested[key]):
            raise ValueError(f'El horizonte efectivo difiere: {key}')
    if manifest.get('temporal_demand'):
        if effective.get('qsim.simEndtimeInterpretation') != 'onlyUseEndtime':
            raise ValueError('MATSim cambio el corte temporal explicito')
        window = manifest['temporal_demand']['simulation_window']
        from simz1_day_observation import enabled as fixed_day
        if window != manifest['time_horizon'] or any(seconds(effective['qsim.'+key]) != window[field]-(1 if fixed_day(manifest) and key=='endTime' else 0)
                for key,field in [('startTime','start_seconds'),('endTime','end_seconds')]):
            raise ValueError('Horizonte temporal incompatible con el manifiesto')
    manifest['configuration_overrides'] += config_changes(requested, effective, 'MATSim effective config')
    manifest['effective_config'] = artifact(directory, output/'output_config.xml')
    from simz1_gateway_od import validated_spatial_demand, validate_od_metadata
    from simz1_balanced_od_audit import validate_manifest as validate_balanced_od, PrivateODAudit
    balanced_od = validate_balanced_od(directory, manifest, implementation_compatibility=implementation_compatibility)
    spatial = None if balanced_od is not None else validated_spatial_demand(directory, manifest)
    spatial_links = set(spatial['allowed_links']) if spatial is not None else None
    empty_composition = manifest.get('demand_composition', {}).get('total_non_public_vehicles') == 0
    input_ids, _ = population(checked_path(directory, manifest['inputs']['plans']), allow_empty=empty_composition)
    input_trip_ledgers = None
    input_spatial = None
    expected_day={}
    if manifest.get('temporal_demand'):
        input_trip_ledgers = {p.get('id'):p.findtext("attributes/attribute[@name='simz1Trips']")
            for p in xml_elements(checked_path(directory,manifest['inputs']['plans']),'person','population')}
        from simz1_day_observation import enabled as fixed_day
        if fixed_day(manifest):
            for p in xml_elements(checked_path(directory,manifest['inputs']['plans']),'person','population'):
                attrs={a.get('name'):a.text for a in p.findall('attributes/attribute')}
                freight_person='simz1FreightService' in attrs
                expected_day[p.get('id')]=dict(vehicle_id=p.get('id'),
                    scheduled_departure=float(attrs['simz1FreightDeparture']) if freight_person else json.loads(attrs['simz1Trips'])[0]['planned_departure'],
                    family='pesado' if freight_person else attrs['simz1VehicleFamily'],
                    od=attrs.get('simz1SpatialOD'),profile=attrs.get('drivingProfile'))
    if spatial is not None:
        input_spatial = {}
        for person in xml_elements(checked_path(directory,manifest['inputs']['plans']),'person','population'):
            ident = person.get('id')
            records = json.loads(person.findtext("attributes/attribute[@name='simz1SpatialOD']", 'null'))
            ledger = json.loads(person.findtext("attributes/attribute[@name='simz1Trips']", 'null'))
            if (not isinstance(records, dict) or not isinstance(ledger, list) or len(ledger) != 1 or
                    set(records) != {trip_id(ident, 1)}):
                raise ValueError('Identidad/metadatos de viaje gateway incompatibles')
            for trip in ledger:
                record = validate_od_metadata(records[trip['id']], spatial)
                if any(record[side+'_link'] != trip[side+'_link'] for side in ('origin','destination')):
                    raise ValueError('OD espacial distinto del plan efectivo')
            input_spatial[ident] = records
    def network_links(path):
        return {e.get('id'): (e.get('from'), e.get('to'), frozenset(e.get('modes', 'car').split(',')))
                for e in xml_elements(path, 'link', 'network')}
    links = network_links(output/'output_network.xml.gz')
    if not links or links != network_links(checked_path(directory, manifest['inputs']['network'])):
        raise ValueError('La red resultante no coincide con la red de esta corrida')
    from simz1_transit_events import verified_transit_contract, TransitEventAudit
    from simz1_freight import verified_contract, FreightAudit
    freight_contract = verified_contract(directory, manifest)
    private_ids = input_ids - freight_contract.keys()
    from simz1_demand_composition import validate_manifest as validate_composition
    validate_composition(directory, manifest, private_ids, freight_contract)
    transit_contract = verified_transit_contract(directory, manifest, requested, checked_path, private_ids, links)
    blocking_facility_links={}
    if transit_contract['vehicle_modes']:
        schedule_path = checked_path(directory, manifest['inputs']['transit_schedule'])
        schedule_root = ET.parse(schedule_path).getroot()
        blocking_facility_links={row.get('id'):row.get('linkRefId')
            for row in schedule_root.findall('./{*}transitStops/{*}stopFacility') if row.get('isBlocking')=='true'}
        schedule_metadata = {row.get('name'): row.text for row in schedule_root.findall('./{*}attributes/{*}attribute')}
        if schedule_metadata.get('simz1:purpose') == 'weekday_scenario_v2':
            from simz1_weekday_transit import verify_policy_chain
            saved_policy, _ = verify_policy_chain(schedule_path, schedule_metadata, len(private_ids))
            if saved_policy.get('stop_proxy_summary'):
                manifest['public_transport']['stop_proxy'] = saved_policy['stop_proxy_summary']
                manifest['public_transport']['stop_proxy_manifest'] = artifact(directory,
                    schedule_path.parent/saved_policy['stop_proxy_manifest_file'])
            if saved_policy.get('stop_queue_summary'):
                manifest['public_transport']['stop_queues'] = saved_policy['stop_queue_summary']
    from simz1_occupancy_audit import CorridorOccupancyAudit, load_inputs as load_occupancy_inputs
    occupancy_enabled = effective.get('simz1Admission.wholeVehicleReservation', 'false') == 'true'
    occupancy_inputs = {}
    if occupancy_enabled:
        if not manifest.get('effective_vehicles'):
            raise ValueError('CORRIDOR_OCCUPANCY: enabled native policy requires loaded output_vehicles.xml.gz')
        vehicle_paths = [checked_path(directory, manifest['effective_vehicles'])]
        if transit_contract['vehicle_modes']:
            vehicle_paths.append(checked_path(directory, manifest['inputs']['transit_vehicles']))
        occupancy_network, occupancy_vehicles = load_occupancy_inputs(output/'output_network.xml.gz', vehicle_paths)
        occupancy_inputs = dict(network=occupancy_network, vehicles=occupancy_vehicles)
    lane_movements = None
    lane_definitions = {}
    if requested.get('qsim.useLanes') == 'true':
        lane_path = requested.get('network.laneDefinitionsFile')
        if not lane_path or lane_path == 'null':
            raise ValueError('Carriles habilitados sin definiciones para validar movimientos')
        lane_movements = enabled_lane_movements(directory/lane_path)
        lane_definitions = read_lanes(actual_lane_file)
    from simz1_blocking_occupancy import single_lane_queues
    single_stop_queues=(single_lane_queues(output/'output_network.xml.gz',actual_lane_file)
                       if requested.get('qsim.useLanes') == 'true' and blocking_facility_links else ())
    horizon = seconds(effective['qsim.endTime'])
    from simz1_day_observation import enabled as fixed_day
    if fixed_day(manifest):
        if horizon!=86399 or effective.get('simz1Observation.policy')!='fixed-day-24h-v1':raise ValueError('Native fixed-day boundary changed')
        horizon=manifest['time_horizon']['end_seconds']
    from simz1_signal_replay import SignalReplay, selected_groups, signal_groups, control_signature
    groups = selected_groups(dict(directory=directory,manifest=manifest),links)
    coordination = manifest.get('short_link_signal_coordination', {})
    if coordination.get('enabled'):
        from simz1_signal_coordination import validate_report
        archived = json.loads(checked_path(directory, coordination['artifact']).read_text(encoding='utf-8'))
        if archived != {key:value for key,value in coordination.items() if key != 'artifact'}:
            raise ValueError('La coordinacion semaforica archivada no coincide con el manifiesto')
        validate_report(directory/'config-simz1.xml', directory, archived,
                        control_before_path=directory/'inputs/signal-control-before-coordination.xml')
    if effective.get('signalsystems.useSignalsystems') == 'true':
        actual_control = output/'output_signal_control_v2.0.xml.gz'
        actual_groups = output/'output_signal_groups_v2.0.xml.gz'
        if control_signature(directory/requested['signalsystems.signalcontrol']) != control_signature(actual_control):
            raise ValueError('MATSim cambio el plan semaforico persistido (incluidos offsets)')
        loaded_groups = signal_groups(actual_signal_file,actual_groups,links,
                                     actual_lane_file if requested.get('qsim.useLanes') == 'true' else None)
        if loaded_groups != groups:
            raise ValueError('Los grupos semaforicos cargados no coinciden con esta corrida')
        manifest['effective_signal_artifacts'] = {name:artifact(directory,path) for name,path in
            [('control',actual_control),('groups',actual_groups),('systems',actual_signal_file)]}

    from simz1_priority_context import build_bus_context
    priority_context = build_bus_context(directory, manifest, effective, transit_contract)

    def validate_pair(plans, events, iteration):
        from simz1_freight import verify_effective
        if freight_contract:
            verify_effective(directory, plans, output/'output_vehicles.xml.gz', freight_contract)
        ids, counts = population(plans, manifest.get('temporal_demand',{}).get('trips_per_person'), allow_empty=empty_composition)
        if ids != input_ids:
            raise ValueError(f'Personas de planes ajenas a la corrida: {plans}')
        if manifest.get('temporal_policy'):
            for key in ('principal_cohort_persons', 'warmup_context_persons', 'post_context_persons', 'all_private_persons'):
                if counts.get(key) != manifest['counts'].get(key):
                    raise ValueError('MATSim cambio la cohorte temporal: '+key)
            for person in xml_elements(plans, 'person', 'population'):
                planned = float(person.findtext("attributes/attribute[@name='simz1PlannedDepartureSeconds']", 'nan'))
                original = json.loads(input_trip_ledgers[person.get('id')])[0]['planned_departure']
                policy = manifest['temporal_policy']
                cohort = person.findtext("attributes/attribute[@name='simz1PopulationCohort']")
                period = {'main': 'study', 'warmup_context': 'warmup', 'post_context': 'post_demand'}.get(cohort)
                if (period is None or planned != original or
                        float(person.findtext("attributes/attribute[@name='simz1StudyStartSeconds']",'nan')) != policy['windows']['study']['start_seconds'] or
                        not policy['windows'][period]['start_seconds'] <= planned < policy['windows'][period]['end_seconds']):
                    raise ValueError('Cohorte/salida temporal distinta del ledger original: '+person.get('id'))
                selected = [plan for plan in person.findall('plan') if plan.get('selected') == 'yes']
                if not selected and len(person.findall('plan')) == 1:
                    selected = person.findall('plan')
                if len(selected) != 1:
                    raise ValueError('Plan temporal seleccionado ambiguo')
                first = next((a for a in selected[0] if a.tag in ('act', 'activity')), None)
                # MATSim15 PopulationWriter serializes activity times at whole
                # seconds (floor), while the persistent ledger keeps the exact
                # planned fraction. A native one-second QSim step may depart at
                # ceil(planned); neither effect is an adaptation strategy.
                serialized = seconds(first.get('end_time','nan')) if first is not None else math.nan
                if not math.isfinite(planned) or not any(abs(serialized-t) <= 1e-6 for t in (planned, math.floor(planned))):
                    raise ValueError('La politica fixed no permite cambiar la salida planificada: '+person.get('id'))
        if input_trip_ledgers is not None:
            actual_ledgers = {p.get('id'):p.findtext("attributes/attribute[@name='simz1Trips']")
                for p in xml_elements(plans,'person','population')}
            if actual_ledgers != input_trip_ledgers:
                raise ValueError('MATSim cambio las identidades/horarios/OD de viajes persistentes')
        if input_spatial is not None:
            actual_spatial = {p.get('id'):json.loads(p.findtext("attributes/attribute[@name='simz1SpatialOD']", 'null'))
                for p in xml_elements(plans,'person','population')}
            if actual_spatial != input_spatial:
                raise ValueError('MATSim cambio los metadatos OD/gateways persistentes')
        if balanced_od is not None:
            from simz1_freight import is_freight
            model, records = balanced_od
            for person in xml_elements(plans,'person','population'):
                if is_freight(person):
                    continue
                ident = person.get('id')
                raw = json.loads(person.findtext("attributes/attribute[@name='simz1SpatialOD']",'null'))
                expected = {k:v for k,v in records[ident].items() if k != 'planned_departure'}
                if raw != {trip_id(ident,1):expected}:
                    raise ValueError('MATSim changed the private OD contract')
        departures = arrivals = completed_legs = 0
        pending, aborted, observed_persons = {}, {}, set()
        movement = MovementAudit(links, lane_movements,
                                 expected_budget=int(effective.get(budget_key,100)),
                                 expected_enabled=effective.get('zona1WithinDayRouting.enabled') == 'true',
                                 registered_vehicle_modes=transit_contract['vehicle_modes'])
        transit = TransitEventAudit(transit_contract, private_ids, freight_contract)
        from simz1_blocking_occupancy import BlockingStopAudit
        stop_occupancy = BlockingStopAudit(transit_contract.get('blocking_facilities', []),
            single_queue_links=single_stop_queues,facility_links=blocking_facility_links)
        corridor_occupancy = CorridorOccupancyAudit(enabled=occupancy_enabled,
            expected_receipt_route_coverage_policy=manifest.get('admission_execution', {}).get('expected_receipt_route_coverage_policy'),
            **occupancy_inputs)
        freight = FreightAudit(freight_contract,fixed_day=fixed_day(manifest))
        transit_temporal = TripAudit(horizon,fixed_day=fixed_day(manifest))
        native = NativeDecisionAudit(expected_admission_policy=manifest['effective_configuration_validation']['admission_policy'])
        from simz1_priority_audit import PriorityAudit
        priority = PriorityAudit(legacy_bus_context=priority_context)
        temporal = TripAudit(horizon,fixed_day=fixed_day(manifest))
        day=None
        if fixed_day(manifest):
            from simz1_day_observation import DayAudit
            schedule=dict(expected_day)
            for key,r in transit_contract['departures'].items():
                schedule['bus:'+':'.join(key)]=dict(vehicle_id=r['vehicle'],family='bus',scheduled_departure=r['scheduled_departure'])
            day=DayAudit(output/'ITERS'/f'it.{iteration}'/f'{iteration}.simz1-day-census.jsonl.gz',manifest['run_id'],iteration,schedule,
                bus_ids=transit_contract['vehicle_modes'])
        private_od = PrivateODAudit(*balanced_od) if balanced_od is not None else None
        signal_replay = SignalReplay(groups,retain_series=False)
        abort_events = 0
        lane_entries = lane_exits = 0
        observed_lane_vehicles = set()
        previous = -math.inf
        for event in xml_elements(events, 'event', 'events'):
            time = float(event.get('time', 'nan'))
            if not math.isfinite(time) or time < previous:
                raise ValueError(f'Tiempos invalidos en {events}')
            previous = time
            if day:
                day.consume(event.attrib)
                if event.get('type')=='simz1DayCut':transit_temporal.consume(event.attrib)
            if event.get('link') is not None and event.get('link') not in links:
                raise ValueError(f'Evento con enlace ajeno a la corrida: {event.get("link")}')
            is_transit = transit.consume(event)
            stop_occupancy.consume(event.attrib)
            corridor_occupancy.consume(event.attrib)
            is_freight_event = freight.consume(event)
            if private_od is not None:
                private_od.consume(event.attrib)
            if (not is_transit and not is_freight_event and spatial_links is not None and event.get('type') in
                    ('departure','arrival','entered link','left link','vehicle enters traffic','vehicle leaves traffic',
                     'entered lane','left lane') and event.get('link') not in spatial_links):
                raise ValueError(f'Movimiento observado fuera del dominio interior Z1: {event.get("link")}')
            if not is_transit and event.get('person') is not None and event.get('person') not in ids:
                raise ValueError(f'Evento con persona ajena a la corrida: {event.get("person")}')
            if event.get('type') in ('entered lane', 'left lane'):
                if not requested_lane_audit['use_lanes']:
                    raise ValueError('Evento de carril con useLanes=false; resultados incompatibles')
                if event.get('lane') not in lane_definitions.get(event.get('link'), {}):
                    raise ValueError(f'Evento con cola ajena a la corrida: {event.get("link")}/{event.get("lane")}')
                if not event.get('vehicle'):
                    raise ValueError('Evento de carril sin vehiculo')
                lane_entries += event.get('type') == 'entered lane'
                lane_exits += event.get('type') == 'left lane'
                observed_lane_vehicles.add(event.get('vehicle'))
            movement.consume(event)
            native.consume(event)
            priority.consume(event.attrib, verified_transit=is_transit)
            signal_replay.add(event.attrib)
            if is_transit:
                # Drivers are observed service actors, never additional road demand.
                # All native movement, lane, chronology and signal checks above still run.
                transit_temporal.consume(event.attrib)
                continue
            if is_freight_event:
                continue
            closed_trip = temporal.consume(event.attrib)
            departures += event.get('type') == 'departure'
            arrivals += event.get('type') == 'arrival'
            if event.get('type') in ('departure', 'arrival'):
                person = event.get('person')
                if not person:
                    raise ValueError(f'Viaje sin persona en {events}')
                if event.get('type') == 'departure':
                    # A terminal abort closes that leg; a later departure is a new one.
                    if person in aborted:
                        pending.pop(person,None)
                    if person in pending:
                        raise ValueError(f'Departure duplicado sin arrival: {person}')
                    pending[person] = time
                    aborted.pop(person, None)
                    observed_persons.add(person)
                else:
                    if person not in pending:
                        raise ValueError(f'Arrival sin departure: {person}')
                    pending.pop(person)
                    aborted.pop(person, None)
                    completed_legs += 1
            elif event.get('type') in ('stuckAndAbort','vehicle aborts'):
                abort_events += 1
                if closed_trip is not None:
                    pending.pop(closed_trip['person'],None)
        if temporal.stats['unmatched_arrivals']:
            raise ValueError('Arrival sin departure activo (incluida llegada posterior a aborto)')
        if transit_temporal.stats['unmatched_arrivals']:
            raise ValueError('Llegada de conductor de transporte publico sin departure activo')
        if not departures and private_ids:
            raise ValueError(f'No hay viajes registrados en {events}')
        if stop_occupancy.violations:
            raise ValueError('Follower exited native queue during blocking bus dwell: '+str(stop_occupancy.violations[0]))
        unfinished = temporal.summary()
        if input_trip_ledgers is not None and any(n > manifest['temporal_demand']['trips_per_person']
                                                 for n in temporal.ordinals.values()):
            raise ValueError('Se observaron mas viajes por persona que los planificados')
        event_artifact = artifact(directory, events)
        private_result = (dict(private_od.finish(),source=dict(run_id=manifest['run_id'],events=event_artifact))
                          if private_od is not None else None)
        day_result=day.finish() if day else None
        if day:
            day_result['census']=artifact(directory,day.path)
            freight.day_census={k:r for k,r in day.frozen.items() if r['family']=='pesado'}
        return dict(network=artifact(directory, output/'output_network.xml.gz'),
                    plans=artifact(directory, plans), events=event_artifact,
                    rerouting=movement.summary(),
                    native_qsim=native.summary(),
                    priority_events=priority.summary(),
                    temporal_events=temporal.summary(),
                    public_transport_events=dict(**transit.summary(), trips=transit_temporal.summary()),
                    freight_transport_events=freight.summary(),
                    **({'day_observation':day_result} if day else {}),
                    **({'private_od_events':private_result} if private_result is not None else {}),
                    blocking_stop_occupancy=stop_occupancy.result(),
                    corridor_occupancy=corridor_occupancy.summary(),
                    signal_events=signal_replay.summary(),
                    observed_event_end_seconds=previous,
                    lane_events=dict(entered_lane_events=lane_entries, left_lane_events=lane_exits,
                                     vehicles_with_events=len(observed_lane_vehicles),
                                     lane_references_validated=True, observed_fields=['time', 'vehicle', 'link', 'lane'],
                                     longitudinal_position_observed=False, lateral_position_observed=False),
                    counts=dict(**counts, observed_departures=departures, observed_arrivals=arrivals,
                                observed_persons=len(observed_persons), completed_legs=completed_legs,
                                incomplete_legs=unfinished['incomplete_trips'],
                                pending_legs_at_horizon=unfinished['pending_trips_at_horizon'],
                                aborted_legs=unfinished['aborted_trips'],
                                aborted_before_horizon=unfinished['aborted_before_horizon'],
                                horizon_abort_events=unfinished['horizon_abort_events'],
                                observed_abort_events=abort_events,
                                unstarted_legs=max(0, counts['planned_legs']-departures),
                                **movement.counts))

    last = manifest['iterations']['last']
    results = {str(last): validate_pair(output/'output_plans.xml.gz', output/'output_events.xml.gz',last)}
    for iteration in completed:
        if iteration == last:
            continue
        folder = output/'ITERS'/f'it.{iteration}'
        plans, events = folder/f'{iteration}.plans.xml.gz', folder/f'{iteration}.events.xml.gz'
        if plans.is_file() and events.is_file():
            results[str(iteration)] = validate_pair(plans, events,iteration)
    manifest['results'] = results
    from simz1_trip_table import validate_compact
    products = {}
    for iteration in completed:
        folder=output/'ITERS'/f'it.{iteration}'
        product={name:artifact(directory,path) for name,path in
            [('native_legs',folder/f'{iteration}.legs.csv.gz'),('native_trips',folder/f'{iteration}.trips.csv.gz')]
            if path.is_file()}
        compact,summary=folder/f'{iteration}.simz1-trips.csv.gz',folder/f'{iteration}.simz1-trip-summary.json'
        if manifest.get('trip_export_schema') == 1 or compact.exists() or summary.exists():
            if not compact.is_file() or not summary.is_file(): raise ValueError(f'Falta producto compacto completo de iteracion {iteration}')
            counts=validate_compact(compact,manifest['run_id'],iteration,input_ids,horizon,fixed_day=fixed_day(manifest))
            metadata=json.loads(summary.read_text(encoding='utf-8'))
            if (metadata.get('schema_version')!=1 or metadata.get('run_id')!=manifest['run_id'] or
                metadata.get('iteration')!=iteration or any(metadata['counts'].get(k,0)!=counts[k] for k in ('rows','completed','aborted','censored'))):
                raise ValueError('Resumen compacto incompatible con CSV/corrida')
            if any(metadata.get('anomalies',{}).get(k,0) for k in ('duplicate_departures','duplicate_arrivals','unmatched_arrivals','arrival_after_abort','abort_after_arrival')):
                raise ValueError('Anomalias de emparejamiento en exportador compacto')
            if transit_contract['vehicle_modes'] and (
                    metadata.get('demand_persons_N') != len(private_ids) or
                    metadata.get('configured_public_vehicles_B') != len(transit_contract['vehicle_modes'])):
                raise ValueError('Resumen compacto mezcla N con la flota publica')
            if str(iteration) in results:
                observed=results[str(iteration)]['temporal_events']
                expected=dict(rows=observed['departures'],completed=observed['completed_trips'],
                              aborted=observed['aborted_before_horizon'],censored=observed['pending_trips_at_horizon'])
                if any(counts[k]!=v for k,v in expected.items()):raise ValueError('CSV compacto difiere de eventos XML')
                public = results[str(iteration)]['public_transport_events']
                if transit_contract['vehicle_modes'] and metadata.get('observed_internal_transit_drivers') != public['transit_drivers_internal_observed']:
                    raise ValueError('Conductores internos del resumen compacto difieren de eventos XML')
            product.update(compact=artifact(directory,compact),summary=artifact(directory,summary),counts=counts)
        products[str(iteration)]=product
    manifest['trip_products']=products
    from simz1_freight import require_approved_results
    require_approved_results(manifest)
    # The plotting CLI also checks hashes; it cannot read a different run's stale Excel.
    manifest['metrics'] = [artifact(directory, p) for p in metric_files(output)]
    manifest['validation'] = dict(status='valid', checks=['hashes', 'complete_xml', 'population',
                                 'network', 'effective_options', 'completed_iterations',
                                 'physical_transitions', 'enabled_lane_movements', 'route_failure_events',
                                 'persisted_signal_plans', 'native_signal_events'])
    if freight_contract:
        manifest['validation']['checks'] += ['freight_identity_files_counts', 'freight_fixed_route', 'freight_weekday_residence_windows']
    if balanced_od is not None:
        manifest['validation']['checks'] += ['balanced_private_od_manifest_and_schedules',
            'per_private_trip_gateway_chain', 'private_native_exterior_body_clearance', 'private_event_stream_closure']
    if occupancy_enabled:
        manifest['validation']['checks'] += ['native_corridor_domain_geometry', 'native_body_length_reservations',
                                            'native_corridor_slot_capacity', 'native_reservation_lifecycle']
    forced_moves = sum(result['native_qsim']['forced_storage_moves'] for result in results.values())
    storage_removals = sum(result['native_qsim']['storage_stuck_removals'] for result in results.values())
    interventions = forced_moves + storage_removals
    manifest['validation']['physical_stability'] = dict(
        status='not_demonstrated' if interventions else
               'no_interventions_observed' if any(r['native_qsim']['decisions'] for r in results.values()) else
               'not_instrumented', proven=False, interventions=interventions,
        forced_storage_moves=forced_moves, storage_stuck_removals=storage_removals,
        counting_unit='native_decisions_across_iterations_not_unique_vehicles')


def publish_success(directory, manifest, latest_path=None):
    if manifest['status'] != 'completed' or manifest['validation']['status'] != 'valid':
        raise ValueError('Solo se publican corridas completadas y validadas')
    atomic_json(latest_path or LATEST, dict(run_id=manifest['run_id'], folder=str(Path(directory).resolve()),
                                          manifest_sha256=sha256(Path(directory)/MANIFEST)))


def register_attempt(directory, manifest, latest_path=None):
    """A reference only: lifecycle state still lives in the one run manifest."""
    path = Path(latest_path or LATEST).with_name('latest-attempt.json')
    atomic_json(path, dict(run_id=manifest['run_id'], folder=str(Path(directory).resolve())))


def selection_warning(manifest, latest_path=None):
    reference_path = Path(latest_path or LATEST).with_name('latest-attempt.json')
    if reference_path.exists():
        reference = json.loads(reference_path.read_text(encoding='utf-8'))
        if isinstance(reference,dict) and reference.get('status')=='invalidated_by_authorized_cleanup':
            return ('Referencia historica retirada por limpieza autorizada; no hay reemplazo automatico. '
                    f"La corrida seleccionada {manifest['run_id']} se valido con sus propios artefactos.")
        if not isinstance(reference,dict) or any(not isinstance(reference.get(k),str) or not reference[k] for k in ('folder','run_id')):
            raise ValueError('latest-attempt sin identidad/carpeta verificable')
        attempt = load_manifest(reference['folder'])
        if attempt['run_id'] != reference['run_id']:
            raise ValueError('latest-attempt no coincide con su manifiesto')
    else:
        # Compatibility with attempts made before latest-attempt existed. Inspect
        # metadata only for a warning; NEVER select their network/plans/events.
        candidates = [load_manifest(p.parent) for p in reference_path.parent.glob('*/'+MANIFEST)]
        attempt = max(candidates, key=lambda m: m.get('started_utc', ''), default=manifest)
    if (attempt['run_id'] == manifest['run_id'] or
            attempt.get('started_utc', '') < manifest.get('started_utc', '')):
        return None
    return (f"RESULTADOS ANTERIORES: se muestra {manifest['run_id']} ({manifest['folder']}). "
            f"El intento mas reciente es {attempt['run_id']} ({attempt['folder']}), "
            f"estado={attempt['status']}, fase={attempt.get('failure_phase', attempt.get('phase', 'no registrada'))}, "
            f"causa={attempt.get('error', 'sin error registrado')}. "
            "Estos resultados no pertenecen a ese intento.")


def select_run(run_dir=None, iteration=None, latest_path=None, *, require_events=True):
    reference = None
    if run_dir is None:
        path = Path(latest_path or LATEST)
        if not path.is_file():
            raise ValueError(f'No hay latest-successful validado: {path}. Ejecute primero ejecutar_simz1.py.')
        reference = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(reference,dict) or reference.get('status')=='invalidated_by_authorized_cleanup' or
                any(not isinstance(reference.get(k),str) or not reference[k] for k in ('folder','run_id','manifest_sha256'))):
            raise ValueError('No hay latest-successful validado; referencia retirada o incompleta, sin fallback historico')
        run_dir = reference['folder']
    directory = Path(run_dir).resolve()
    manifest = load_manifest(directory)
    if reference and (reference['run_id'] != manifest['run_id'] or
                      reference['manifest_sha256'] != sha256(directory/MANIFEST)):
        raise ValueError('latest-successful no coincide con el manifiesto; no hay fallback historico')
    if manifest['status'] != 'completed' or manifest['validation']['status'] != 'valid':
        raise ValueError(f"Corrida no valida: {manifest['run_id']} ({manifest['status']})")
    selected = manifest['iterations']['last'] if iteration is None else iteration
    result = manifest['results'].get(str(selected))
    if result is None and (require_events or selected not in manifest['iterations']['completed']):
        raise ValueError(f'Iteracion {selected} sin planes y eventos validados juntos; disponibles: {list(manifest["results"])}')
    for record in [*manifest['inputs'].values(), manifest['effective_config'], *manifest['metrics']]:
        checked_path(directory, record)
    for record in manifest.get('effective_lane_configuration_validation', {}).get('loaded_artifacts', {}).values():
        checked_path(directory, record)
    for record in manifest.get('effective_signal_artifacts', {}).values():
        checked_path(directory, record)
    if manifest.get('effective_vehicles'):
        checked_path(directory, manifest['effective_vehicles'])
    if {p.relative_to(directory).as_posix() for p in metric_files(directory/'output')} != {
            record['path'] for record in manifest['metrics']}:
        raise ValueError('Las metricas difieren del inventario validado de esta corrida')
    for product in manifest.get('trip_products',{}).values():
        for name in ('compact','summary','native_legs','native_trips'):
            if name in product:checked_path(directory,product[name])
    paths = {name: checked_path(directory, result[name]) for name in ('network', 'plans', 'events')} if result else {}
    print(f"Corrida: {manifest['run_id']} | demanda={manifest['demand_seed']} MATSim={manifest['matsim_seed']} "
          f"| iteracion={selected} | {directory}")
    warning = selection_warning(manifest, latest_path)
    if warning:
        print(warning, file=sys.stderr, flush=True)
    return dict(directory=directory, manifest=manifest, iteration=selected, selection_warning=warning, **paths)
