"""Build a continuous SimZ1 viewer from a validated paged or SQLite source.

The original SQLite is opened read-only; motion is never recalculated.
Paged sources supply native side-data through HTML. Explicit SQLite recovery
can instead recover only complete signals/incidents from native events once.
"""
import argparse
from bisect import bisect_left
from collections import Counter, OrderedDict
from contextlib import closing
import gzip
import hashlib
import io
import json
import math
import mmap
from pathlib import Path
import sqlite3
import time
import threading
import zlib

from serve_simz1_replay import read_export
from simz1_paged_replay import peak_working_set, unpacked
from simz1_replay_work import checkpoint, cancellable_connection


IDENTITY_KEYS = ('run_id', 'iteration', 'run_manifest_sha256')
DAY_SECONDS = 86400


class RuntimeReadCache:
    """Bounded immutable results; payload/key byte estimates, not Python RSS."""
    def __init__(self, max_bytes=32*1024*1024, max_entries=20000):
        self.entries, self.bytes = OrderedDict(), 0
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.lock = threading.Lock()
        self.hits = self.misses = self.evictions = 0

    def get(self, key):
        with self.lock:
            item = self.entries.get(key)
            if item is not None:
                self.hits += 1
                self.entries.move_to_end(key)
                return True, item[0]
            self.misses += 1
            return False, None

    def put(self, key, value, size):
        with self.lock:
            old = self.entries.pop(key, None)
            if old is not None:
                self.bytes -= old[1]
            if size > self.max_bytes:
                return
            self.entries[key] = (value, size)
            self.bytes += size
            while self.bytes > self.max_bytes or len(self.entries) > self.max_entries:
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
                self.evictions += 1

    def summary(self):
        with self.lock:
            return dict(entries=len(self.entries), accounted_bytes=self.bytes, max_bytes=self.max_bytes,
                        max_entries=self.max_entries, hits=self.hits, misses=self.misses, evictions=self.evictions)


class ProfiledCursor:
    def __init__(self, cursor, metrics):
        self.cursor, self.metrics = cursor, metrics

    def fetchone(self):
        started = time.perf_counter()
        row = self.cursor.fetchone()
        self.metrics['sqlite'] += time.perf_counter()-started
        return row

    def __iter__(self):
        while True:
            started = time.perf_counter()
            rows = self.cursor.fetchmany(256)
            self.metrics['sqlite'] += time.perf_counter()-started
            if not rows:
                return
            yield from rows


def json_bytes(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def identity(manifest):
    return {key: manifest[key] for key in IDENTITY_KEYS}


def daily_window(config, manifest, source):
    """Restrict the served view, preserving source evidence and metric horizons.

    Explicit shorter fixtures keep their range. A historical 25-hour export is
    projected in memory; neither its JSON files nor its native records change.
    """
    original = manifest['replay_window']
    policy = config.get('temporal_policy')
    limit = policy['windows']['simulation']['end_seconds'] if policy else DAY_SECONDS
    experimental=config.get('experimental_observation')
    if experimental:
        from simz1_freight_completion import POLICY
        limits={POLICY:108000, 'fixed-day-24h-v1':86400}
        if (experimental.get('policy') not in limits or experimental.get('demand_end_seconds')!=86400 or
                experimental.get('observation_end_seconds')!=limits[experimental['policy']]):
            raise ValueError('Unknown experimental replay observation window')
        limit=experimental['observation_end_seconds']
    start, end = original['start_seconds'], min(original['end_seconds'], limit)
    seconds = manifest['window_seconds']
    if not all(math.isfinite(value) for value in (start, end, seconds)) or not 0 <= start < end or seconds <= 0:
        raise ValueError('Ventana diaria incompatible con el replay de origen')
    visible = dict(start_seconds=start, end_seconds=end)
    source_horizon = dict(config.get('time_horizon') or source['replay_window'])
    metrics_window = dict(start_seconds=source_horizon['start_seconds'],
        end_seconds=source.get('operational_counts_observation_end_seconds', source['replay_window']['end_seconds']))
    window_count = math.ceil((end-start)/seconds)
    metadata = dict(source_replay_window=dict(source['replay_window']),
                    source_time_horizon=source_horizon, metrics_window=metrics_window)
    manifest.update(replay_window=visible, window_count=window_count, **metadata)
    config['replay_window'] = dict(visible)
    config['continuous'].update(start_seconds=start, end_seconds=end,
        window_count=window_count, window_seconds=seconds,
        native_observed_end_seconds=source['replay_window']['end_seconds'], **metadata)
    # Older fixtures may carry a source endpoint beyond the slider endpoint.
    # The served terminal window now includes only the exact daily closing tick.
    config['continuous'].pop('data_end_seconds', None)


def application_html():
    templates = Path(__file__).parent
    template = (templates / 'visualizador_z1_continuous.html').read_text(encoding='utf-8')
    controls = (templates / 'visualizador_z1_controls.js').read_text(encoding='utf-8')
    loader = (templates / 'simz1_continuous_loader.js').read_text(encoding='utf-8')
    hud = (templates / 'simz1_continuous_hud.js').read_text(encoding='utf-8')
    aggregates = (templates / 'simz1_aggregate_view.js').read_text(encoding='utf-8')
    lanes = (templates / 'simz1_visual_lanes.js').read_text(encoding='utf-8')
    picking = (templates / 'simz1_vehicle_picking.js').read_text(encoding='utf-8')
    queues = (templates / 'simz1_visual_queues.js').read_text(encoding='utf-8')
    spatial = (templates / 'simz1_spatial_view.js').read_text(encoding='utf-8')
    signals = (templates / 'simz1_signal_geometry.js').read_text(encoding='utf-8')
    arrivals = (templates / 'simz1_arrival_effects.js').read_text(encoding='utf-8')
    incident_effects = (templates / 'simz1_incident_effects.js').read_text(encoding='utf-8')
    stops = (templates / 'simz1_transit_stops.js').read_text(encoding='utf-8')
    if any(template.count(marker) != 1 for marker in ('__CONTROLS__', '__LOADER__', '__HUD__', '__AGGREGATE_VIEW__', '__VISUAL_LANES__', '__VEHICLE_PICKING__', '__VISUAL_QUEUES__', '__SPATIAL_VIEW__', '__SIGNAL_GEOMETRY__', '__ARRIVAL_EFFECTS__', '__INCIDENT_EFFECTS__', '__TRANSIT_STOPS__')):
        raise ValueError('Plantilla continua incompleta')
    # Identify the source snapshot actually loaded by this client. This is not
    # the historical export's version and does not rewrite any run artifact.
    components = dict(template=template, controls=controls, loader=loader, hud=hud, aggregates=aggregates,
                      lanes=lanes, picking=picking, queues=queues, spatial=spatial, signals=signals, arrivals=arrivals,
                      incident_effects=incident_effects, stops=stops)
    hashes = {name: hashlib.sha256(value.encode('utf-8')).hexdigest() for name, value in components.items()}
    build = dict(schema_version=1, components=hashes,
                 source_sha256=hashlib.sha256(json_bytes(hashes)).hexdigest())
    document = (template.replace('__CONTROLS__', controls).replace('__LOADER__', loader)
            .replace('__HUD__', hud).replace('__AGGREGATE_VIEW__', aggregates).replace('__VISUAL_LANES__', lanes)
            .replace('__VEHICLE_PICKING__', picking).replace('__VISUAL_QUEUES__', queues)
            .replace('__SPATIAL_VIEW__', spatial).replace('__SIGNAL_GEOMETRY__', signals)
            .replace('__ARRIVAL_EFFECTS__', arrivals).replace('__INCIDENT_EFFECTS__', incident_effects).replace('__TRANSIT_STOPS__', stops))
    return document.replace('<head>', '<head>\n<script>window.simz1ClientBuild=Object.freeze(' +
                            json_bytes(build).decode('utf-8') + ');</script>', 1)


def refresh_application(directory):
    """Refresh only the new app shell after source fixes; preserve native data."""
    replay = ContinuousReplay(directory)
    target = replay.root / 'index.html'
    temporary = replay.root / 'index.html.tmp'
    temporary.write_text(application_html(), encoding='utf-8')
    temporary.replace(target)
    manifest = replay.stored_manifest
    manifest['application_bytes'] = target.stat().st_size + (replay.root / 'config.json').stat().st_size
    (replay.root / 'continuous-manifest.json').write_bytes(json_bytes(manifest))


def connect(database):
    connection = sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA cache_size=-8192')
    # Window queries materialize integer IDs only. Never spill a transient
    # sorter to the system drive when serving an immutable source.
    connection.execute('PRAGMA temp_store=MEMORY')
    return connection


def checked_native_run(manifest):
    run_manifest = Path(manifest['run_directory']) / 'run-manifest.json'
    raw = run_manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['run_manifest_sha256']:
        raise ValueError('El manifiesto nativo cambio o no pertenece al export validado')
    run = json.loads(raw)
    if run.get('status') != 'completed' or run.get('validation', {}).get('status') != 'valid':
        raise ValueError('Se requiere una corrida completada y validada')
    if run.get('run_id') != manifest['run_id'] or str(manifest['iteration']) not in run.get('results', {}):
        raise ValueError('Corrida o iteracion nativa incompatible con el replay')
    return run


def prepare_facility_support(run_directory, native_run, native_identity, source_sqlite_sha256):
    """Bind the complete blocking-facility scope to verified native inputs.

    Transit replay creates each stop's link and blocking flag from this exact
    schedule (load_transit/consume), not from the display map. This is a scope
    proof, not an observed position or permission to move a native body.
    """
    from simz1_queue_context import VerifiedFacilitySupport, validate_facility_support
    from simz1_run import checked_path
    from simz1_motion import elements
    directory=Path(run_directory).resolve(strict=True)
    raw=(directory/'run-manifest.json').read_bytes()
    if (hashlib.sha256(raw).hexdigest()!=native_identity['run_manifest_sha256'] or
            json.loads(raw)!=native_run or native_run.get('run_id')!=native_identity['run_id'] or
            str(native_identity['iteration']) not in native_run.get('results',{}) or
            native_run.get('status')!='completed' or native_run.get('validation',{}).get('status')!='valid'):
        raise ValueError('Facility support differs from the pinned native run')
    artifact=native_run.get('inputs',{}).get('transit_schedule')
    if artifact is None:return None
    schedule=checked_path(directory,artifact)
    facilities=set();blocking=set()
    with closing(elements(schedule,{'stopFacility'})) as rows:
        for row in rows:
            ident,link=row.get('id'),row.get('linkRefId')
            if not ident or not link or ident in facilities:
                raise ValueError('Facility support requires a complete unambiguous schedule')
            facilities.add(ident)
            if row.get('isBlocking')=='true':blocking.add(link)
    if not facilities:return None
    reader=Path(__file__).with_name('simz1_transit_replay.py')
    proof=VerifiedFacilitySupport(schema='native-blocking-facility-support-v1',
        identity=dict(native_identity),source_sqlite_sha256=source_sqlite_sha256,
        schedule_sha256=artifact['sha256'],reader_sha256=hashlib.sha256(reader.read_bytes()).hexdigest(),
        blocking_links=sorted(blocking))
    validate_facility_support(proof,native_identity,source_sqlite_sha256)
    return proof


def checked_screening(run, source):
    """Optional analysis evidence; missing screening never becomes a PASS."""
    if not source.get('run_directory'):
        return dict(status='not_evaluated',source=None)
    folder=Path(source['run_directory'])/'analysis'/f"it.{source['iteration']}"
    path=folder/'analysis-manifest.json'
    if not path.is_file():return dict(status='not_evaluated',source=None)
    report=json.loads(path.read_bytes())
    if (report.get('status')!='completed' or report.get('run_id')!=run['run_id'] or
            report.get('iteration')!=source['iteration']):
        return dict(status='unavailable',reason='analysis_identity_mismatch')
    quality=next((r for r in report.get('artifacts',[]) if r['path']=='graficas_perfiles/calidad_resultados.json'),None)
    if quality is None:return dict(status='not_evaluated',source=None)
    from simz1_run import checked_path
    data=json.loads(checked_path(folder,quality).read_bytes())
    if data.get('run_id')!=run['run_id'] or data.get('iteration')!=source['iteration']:
        raise ValueError('Screening identity differs from native replay')
    day=run['results'][str(source['iteration'])].get('day_observation')
    if day and report.get('specification',{}).get('day_observation')!=day:
        return dict(status='unavailable',reason='analysis_day_census_mismatch')
    return dict(data,source=dict(path=str(path),sha256=digest(path)))


def checked_freight_hud(configured, observed, day, horizon):
    """Reconcile fixed-day freight without equating departure with traffic entry.

    All evidence is from the pinned native manifest. No census/event rescan and
    no rewriting of the historical full-service or experimental acceptance.
    """
    def fail(detail):
        raise ValueError('Servicio de transporte pesado incompatible: ' + detail)

    if day is not None and not isinstance(day, dict):
        fail('censo diario inválido')
    groups = (day or {}).get('groups')
    required = isinstance(groups, list) and any(isinstance(row, dict) and row.get('family') == 'pesado'
        for row in groups)
    if configured is None and observed is None and not required:
        return
    if not isinstance(configured, dict) or type(configured.get('enabled')) is not bool:
        fail('configuración ausente/inválida')
    if not configured['enabled']:
        if (observed is not None or required or type(configured.get('vehicles_configured')) is not int or
                configured['vehicles_configured'] != 0):
            fail('servicio desactivado incompatible')
        return

    def count(record, key):
        value = record.get(key) if isinstance(record, dict) else None
        if type(value) is not int or not 0 <= value <= 9007199254740991:
            fail('contador ' + key)
        return value

    def ids(record, key, size, required):
        value = record.get(key) if isinstance(record, dict) else None
        if value is None and not required:
            return None
        if (not isinstance(value, list) or len(value) != size or
                any(not isinstance(item, str) or not item for item in value) or len(set(value)) != size):
            fail('IDs ' + key)
        return set(value)

    configured_n, scheduled = (count(configured, key) for key in ('vehicles_configured', 'departures_scheduled'))
    entered, departed = (count(observed, key) for key in ('vehicles_observed', 'departures_observed'))
    day = day or {}
    policy = 'fixed-day-24h-v1'
    fixed = day.get('policy') == policy or observed.get('day_observation_policy') == policy
    fleet = ids(configured, 'fleet_vehicle_ids', configured_n, fixed)
    seen = ids(observed, 'fleet_vehicle_ids', entered, fixed)
    if fleet is not None and seen is not None and not seen <= fleet:
        fail('flota observada ajena')
    if not fixed:
        if configured_n != entered or scheduled != departed:
            fail('servicio histórico incompleto')
        if observed.get('arrivals_observed') is not None and count(observed, 'arrivals_observed') > entered:
            fail('llegadas históricas incompatibles')
        return
    if (day.get('policy') != policy or observed.get('day_observation_policy') != policy or
            day.get('execution') != 'native_day_completed' or
            day.get('technical_integrity') != 'verified_precleanup_census' or
            day.get('coverage_end_seconds') != 86400 or
            horizon != dict(start_seconds=0, end_seconds=86400) or
            observed.get('technical_integrity') != 'valid' or observed.get('status') != 'valid'):
        fail('censo diario sin respaldo')
    arrived, active, waiting, unstarted, censored = (count(observed, key) for key in (
        'arrivals_observed', 'active_in_traffic_at_cut', 'waiting_for_insertion',
        'scheduled_not_departed_at_cut', 'censored_at_horizon'))
    if (not arrived <= entered <= departed <= scheduled == configured_n or
            entered != arrived + active or departed != entered + waiting or
            configured_n != departed + unstarted or censored != active + waiting + unstarted or
            count(observed, 'active_or_censored') != censored or
            count(observed, 'missing_departures') != unstarted or count(observed, 'aborted_expeditions') != 0):
        fail('balance de incorporaciones/llegadas/censura')

    def times(key, size, expected):
        values = observed.get(key)
        if (not isinstance(values, dict) or len(values) != size or not set(values) <= expected or
                any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 86400
                    for t in values.values())):
            fail('evidencia ' + key)
        return values

    entries = times('observed_traffic_entries', entered, seen)
    # exited_without_arrival fails the native valid-day census. Equal counts
    # do not imply equal VehicleLeavesTraffic and Arrival event times.
    exits = times('observed_traffic_exits', arrived, seen)
    if any(t < entries[key] for key, t in exits.items()):
        fail('salida anterior a incorporación')
    records = observed.get('completion_records')
    if not isinstance(records, list) or len(records) != configured_n:
        fail('censo individual ausente')
    terminals = observed.get('terminal_events')
    if not isinstance(terminals, dict) or not set(terminals) <= fleet:
        fail('terminales individuales incompatibles')
    recorded = set()
    completed_records = 0
    for row in records:
        if (not isinstance(row, dict) or row.get('vehicle_id') not in fleet or
                row['vehicle_id'] in recorded or any(key not in row for key in (
                    'entry_seconds', 'traffic_exit_seconds', 'arrival_seconds')) or
                any(row[key] is not None and type(row[key]) not in (int, float)
                    for key in ('entry_seconds', 'traffic_exit_seconds', 'arrival_seconds')) or
                row['entry_seconds'] != entries.get(row['vehicle_id']) or
                row['traffic_exit_seconds'] != exits.get(row['vehicle_id'])):
            fail('censo individual incompatible')
        recorded.add(row['vehicle_id'])
        terminal = terminals.get(row['vehicle_id'])
        if terminal is not None and (not isinstance(terminal, dict) or
                type(terminal.get('time')) not in (int, float) or not math.isfinite(terminal['time'])):
            fail('terminal individual inválido')
        complete = terminal is not None and terminal.get('status') == 'completed'
        if complete:
            if (not 0 <= terminal['time'] <= 86400 or row['arrival_seconds'] != terminal['time'] or
                    row['traffic_exit_seconds'] is None or row['traffic_exit_seconds'] > row['arrival_seconds']):
                fail('llegada/terminal individual incompatible')
        elif (row['arrival_seconds'] is not None or row['traffic_exit_seconds'] is not None or
                terminal is not None and (terminal.get('status') != 'aborted' or terminal['time'] < 86400)):
            fail('llegada/terminal individual incompatible')
        completed_records += complete
        if row.get('trip_outcome') != ('completed' if complete else 'censored_at_horizon'):
            fail('estado individual incompatible')
    if completed_records != arrived:
        fail('llegadas individuales')
    groups = day.get('groups')
    if not isinstance(groups, list) or any(not isinstance(row, dict) for row in groups):
        fail('grupos del censo ausentes')
    expected = dict(scheduled_requests=configured_n, incorporations=entered, real_arrivals=arrived,
        completed=arrived, active_at_cut=active, waiting_for_incorporation=waiting,
        scheduled_not_departed=unstarted, aborted_before_cut=0)
    totals = dict.fromkeys(expected, 0)
    unique_groups = set()
    for row in groups:
        if row.get('family') != 'pesado':
            continue
        hour = count(row, 'scheduled_hour')
        if not isinstance(row.get('od'), str) or not row['od'] or hour > 23:
            fail('grupo inválido')
        group = (row['family'], row['od'], hour)
        if group in unique_groups:
            fail('grupo duplicado')
        unique_groups.add(group)
        # simz1_day_observation.finish emits Counter status categories sparsely;
        # its three base counters are always explicit, including legitimate zero.
        values = {key: count(row, key) if key in row or key in (
            'scheduled_requests', 'incorporations', 'real_arrivals') else 0 for key in totals}
        if (values['real_arrivals'] != values['completed'] or
                values['incorporations'] != values['completed'] + values['active_at_cut'] or
                values['scheduled_requests'] != values['incorporations'] + values['waiting_for_incorporation'] +
                    values['scheduled_not_departed'] or values['aborted_before_cut'] != 0):
            fail('balance del grupo diario')
        for key in totals:
            totals[key] += values[key]
    if totals != expected:
        fail('conciliación del censo diario')


def checked_hud(run, source, manifest, config):
    """Read global counters with their native horizon; never infer live QSim state."""
    expected_identity = identity(manifest)
    if (identity(source) != expected_identity or identity(config['continuous']) != expected_identity or
            run.get('run_id') != expected_identity['run_id'] or
            run.get('status') != 'completed' or run.get('validation', {}).get('status') != 'valid'):
        raise ValueError('Identidad HUD incompatible con la corrida validada')
    result = run.get('results', {}).get(str(expected_identity['iteration']))
    if not isinstance(result, dict):
        raise ValueError('Iteracion HUD ausente del manifiesto nativo')

    def window(value, label):
        if (not isinstance(value, dict) or any(type(value.get(key)) not in (int, float) or
                not math.isfinite(value[key]) for key in ('start_seconds', 'end_seconds')) or
                not 0 <= value['start_seconds'] < value['end_seconds']):
            raise ValueError(f'Horizonte HUD sin respaldo: {label}')
        return {key: value[key] for key in ('start_seconds', 'end_seconds')}

    horizon = window(run.get('time_horizon'), 'QSim nativo')
    visible = window(manifest.get('replay_window'), 'replay visible')
    metrics = window(config['continuous'].get('metrics_window'), 'indicadores')
    for value in (config.get('time_horizon'), manifest.get('source_time_horizon'),
                  config['continuous'].get('source_time_horizon')):
        if value is not None and value != horizon:
            raise ValueError('Horizonte HUD incompatible con el manifiesto nativo')
    if config.get('replay_window') != visible or manifest.get('metrics_window') != metrics:
        raise ValueError('Ventana HUD incompatible con el replay validado')
    observed_end = result.get('observed_event_end_seconds', horizon['end_seconds'])
    if (type(observed_end) not in (int, float) or not math.isfinite(observed_end) or
            metrics != dict(start_seconds=horizon['start_seconds'], end_seconds=observed_end) or
            source.get('operational_counts_observation_end_seconds', observed_end) != observed_end):
        raise ValueError('Horizonte de indicadores HUD incompatible con la observacion nativa')

    def count(record, key, *, required=False):
        value = record.get(key)
        if value is None and not required:
            return None
        if type(value) is not int or value < 0:
            raise ValueError(f'Contador HUD sin respaldo valido: {key}')
        return value

    def compare(record, key, expected):
        actual = count(record, key)
        if actual is not None and expected is not None and actual != expected:
            raise ValueError(f'Contador HUD incompatible con el manifiesto: {key}')

    native_counts, results_counts = run.get('counts', {}), result.get('counts', {})
    source_counts = source.get('counts', {})
    people = count(native_counts, 'planned_persons', required=True)
    principal = count(native_counts, 'principal_cohort_persons')
    planned = count(native_counts, 'planned_trips', required=True)
    completed = count(results_counts, 'completed_legs')
    pending = count(results_counts, 'pending_legs_at_horizon')
    reconstructed = count(source_counts, 'reconstructed_vehicles')
    observed = count(source_counts, 'observed_vehicles')
    for record in (source, manifest, config.get('hud', {})):
        compare(record, 'planned_persons', people)
        compare(record, 'planned_trips', planned)
    for record in (source.get('operational_counts', {}), manifest.get('operational_counts', {}),
                   config.get('operational_counts', {})):
        compare(record, 'completed_legs', completed)
        compare(record, 'pending_legs_at_horizon', pending)
    compare(manifest.get('counts', {}), 'reconstructed_vehicles', reconstructed)
    compare(manifest.get('counts', {}), 'observed_vehicles', observed)
    compare(config.get('hud', {}), 'reconstructed_vehicles', reconstructed)
    compare(config['continuous'], 'total_reconstructed_vehicles', reconstructed)
    for key, value in expected_identity.items():
        if key in config.get('hud', {}) and config['hud'][key] != value:
            raise ValueError('Identidad del HUD almacenado incompatible con la corrida')
    public_config = run.get('public_transport')
    public_vehicles = None
    public_basis = 'missing_unique_fleet_evidence'
    if public_config and public_config.get('enabled') is False:
        if public_config.get('public_transport_vehicles_configured', 0) != 0:
            raise ValueError('Flota HUD desactivada con vehiculos configurados')
        public_vehicles, public_basis = 0, 'explicitly_disabled'
    if public_config and public_config.get('enabled') and public_config.get('fleet_vehicle_ids') is not None:
        # Dated service allocations can reuse one physical bus. Preserve a
        # published manifest's scalar, but derive the displayed breakdown from
        # its validated explicit vehicle IDs, never from summed service counts.
        from simz1_transit_accounting import distinct_fleet_by_system
        fleet_ids = public_config['fleet_vehicle_ids']
        if len(fleet_ids) != public_config['public_transport_vehicles_configured']:
            raise ValueError('Flota HUD incompatible con IDs nativos')
        by_system = distinct_fleet_by_system(public_config['service_counts'], fleet_ids)
        public_config = dict(public_config,
            declared_fleet_by_system=public_config.get('fleet_by_system'),
            fleet_by_system=by_system,
            fleet_counting_basis='Unique native configured_vehicle_ids per system across dated services; published manifest unchanged')
        public_vehicles, public_basis = len(set(fleet_ids)), 'unique_configured_fleet_ids'
    # verify_population checks unique person/vehicle IDs, equality of their sets,
    # and PersonVehicles == {'car': person_id}. Its saved report is produced
    # BEFORE attach_freight; equal planned counts alone are not this proof.
    verified = (run.get('population_generation') or {}).get('verified') or {}
    temporal = run.get('temporal_policy') is not None or config.get('temporal_policy') is not None
    private_vehicles, private_basis = None, 'missing_one_to_one_xml_evidence'
    if verified.get('references_valid') is True and all(key in verified for key in ('persons','vehicles','unique_person_ids')):
        if any(count(verified, key, required=True) != people for key in ('persons','vehicles','unique_person_ids')):
            raise ValueError('Equivalencia persona/vehiculo HUD incompatible')
        if temporal:
            private_basis = 'missing_verified_main_cohort'
            cohort_keys = [('principal_cohort_persons','principal_cohort_persons'),
                          ('context_persons','context_persons'),
                          ('warmup_context_persons','context_persons_warmup'),
                          ('post_context_persons','context_persons_post')]
            if all(native_counts.get(a) is not None and verified.get(b) is not None for a,b in cohort_keys):
                for native_key, verified_key in cohort_keys:
                    if count(native_counts,native_key) != count(verified,verified_key):
                        raise ValueError('Cohorte de vehiculos HUD incompatible')
                if (principal + native_counts['context_persons'] != people or
                        native_counts['warmup_context_persons'] + native_counts['post_context_persons'] != native_counts['context_persons']):
                    raise ValueError('Balance de cohorte HUD incompatible')
                private_vehicles, private_basis = principal, 'verified_main_cohort_one_vehicle_per_person'
        else:
            private_vehicles, private_basis = verified['vehicles'], 'verified_private_one_vehicle_per_person'
    checked_freight_hud(run.get('freight_transport'), result.get('freight_transport_events'),
                       result.get('day_observation'), horizon)
    return dict(schema_version=1, **expected_identity,
                source_version=manifest['source_export_sha256'], replay_window=visible,
                source_time_horizon=horizon, metrics_window=metrics,
                vehicle_summary=dict(schema_version=1, private_vehicles=private_vehicles,
                    public_vehicles=public_vehicles, private_basis=private_basis, public_basis=public_basis,
                    temporal_policy=temporal, excludes=['freight','public_drivers','auxiliary_context']),
                run_details=dict(demand_seed=run.get('demand_seed'), matsim_seed=run.get('matsim_seed'),
                    study_date=(run.get('temporal_policy') or {}).get('study_date'),
                    public_service_date=(public_config or {}).get('service_date')),
                counts=dict(persons_generated=people, planned_trips=planned, completed_trips=completed,
                            **(dict(principal_cohort_persons=principal,
                            context_persons=count(native_counts, 'context_persons'),
                            warmup_context_persons=count(native_counts, 'warmup_context_persons'),
                            post_context_persons=count(native_counts, 'post_context_persons')) if principal is not None else {}),
                            pending_censored_trips=pending, reconstructed_vehicles=reconstructed,
                            vehicles_with_events=observed), native_active_series=None,
                freight_transport=dict(configured=run.get('freight_transport'),
                    observed=result.get('freight_transport_events')),
                day_observation=result.get('day_observation'),
                screening=checked_screening(run,source),
                public_transport=dict(configured=public_config,
                    observed=result.get('public_transport_events'),
                    note='N is road demand only; B, departures and internal drivers are separate. Observed totals are not live counts.'))


def checked_source(directory):
    from simz1_sqlite_source import FILE_NAME, checked_source as checked_sqlite_source
    if (Path(directory) / FILE_NAME).exists():
        return checked_sqlite_source(directory)
    root, manifest, database = read_export(directory)
    checked_native_run(manifest)
    blocks = manifest['blocks']
    for index, block in enumerate(blocks):
        if (block['index'] != index or block['end_seconds'] <= block['start_seconds'] or
                (index and block['start_seconds'] != blocks[index - 1]['end_seconds'])):
            raise ValueError('Bloques de origen incompletos o fuera de orden')
        path = (root / 'blocks' / block['url']).resolve(strict=True)
        if path.parent != root / 'blocks':
            raise ValueError('Ruta de bloque fuera de su export')
    return root, manifest, database


def source_manifest_path(directory, manifest):
    from simz1_sqlite_source import FILE_NAME
    return Path(directory) / (FILE_NAME if manifest.get('source_type') == 'sqlite-direct-v1' else 'export-manifest.json')


def html_parts(path, *, config=False):
    """Extract bounded side data, using only markers emitted by our exporter.

    mmap.find/rfind run in native code and never materialize the HTML string.
    JSON parsing then validates every extracted object. The large trips array
    is skipped as bytes; no movement or Motion_Plan is decoded here.
    """
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        marker = b'<script id="replay-data" type="application/json">'
        start = data.find(marker)
        if start < 0:
            raise ValueError(f'Payload de replay no encontrado: {path}')
        start += len(marker)
        stop = data.rfind(b'</script>', start)
        # The replay script precedes executable controls. Find its closing tag
        # from a small known tail, avoiding a forward scan through all trips.
        controls = data.rfind(b'<script>', start)
        if controls >= 0:
            stop = data.rfind(b'</script>', start, controls)
        if stop < 0:
            raise ValueError('Payload de replay incompleto')
        if config:
            trips_id = data.rfind(b'"id":"trips"', start, stop)
            layer_start = data.find(b'{"@@type":"ScatterplotLayer","data":', start, trips_id)
            movements_start = data.find(b'"data":', layer_start, trips_id) + len(b'"data":')
            movements_stop = data.rfind(b'],"getFillColor":', movements_start, trips_id) + 1
            if min(trips_id, layer_start) < 0 or movements_start < len(b'"data":') or movements_stop <= movements_start:
                raise ValueError('Formato de capa trips no reconocido; no se omiten datos a ciegas')
            result = json.loads(data[start:movements_start] + b'[]' + data[movements_stop:stop])
            if next(layer for layer in result['layers'] if layer['id'] == 'trips')['data'] != []:
                raise ValueError('La geometria fija contiene movimientos')
            return result
        # Side data lives after the large trips array. Locate it backwards and
        # never locate/scan the movement layer for these 301 temporal extracts.
        signal_start = data.rfind(b',"signal_replay":', start, stop)
        if signal_start >= 0:
            signal_start += len(b',"signal_replay":')
            signal_stop = data.find(b',"lane_replay":', signal_start, stop)
            if signal_stop < 0:
                signal_stop = data.find(b',"trajectory_stats":', signal_start, stop)
            if signal_stop < 0:
                raise ValueError('Limite signal_replay no reconocido')
            signals = json.loads(data[signal_start:signal_stop])
        else:
            signals = {'series': []}
        incident_id = data.rfind(b'"id":"incidents"', start, signal_start if signal_start >= 0 else stop)
        incident_layer = data.rfind(b'{"@@type":', start, incident_id)
        incident_start = data.find(b'"data":', incident_layer, incident_id) + len(b'"data":')
        incident_stop = data.find(b'],"getIcon":', incident_start, incident_id) + 1
        if incident_id < 0 or incident_layer < 0 or incident_stop <= incident_start:
            raise ValueError('Formato de incidentes no reconocido')
        incidents = json.loads(data[incident_start:incident_stop])
        def tail_object(name, following):
            marker = (',"' + name + '":').encode('ascii')
            search_stop = signal_start if name == 'hud' and signal_start >= 0 else stop
            begin = data.rfind(marker, start, search_stop)
            if begin < 0:
                raise ValueError(f'Identidad temporal ausente: {name}')
            begin += len(marker)
            finish = data.find((',"' + following + '":').encode('ascii'), begin, stop)
            if finish < 0:
                raise ValueError(f'Limite temporal ausente: {name}')
            return json.loads(data[begin:finish])
        hud = tail_object('hud', 'signal_replay' if signal_start >= 0 else 'lane_replay')
        replay_window = tail_object('replay_window', 'selection_warning')
        return {'signal_replay': signals, 'incidents': incidents,
                'source_hud': {'run_id': hud['run_id'], 'iteration': hud['iteration']},
                'source_replay_window': replay_window}


def generate(source, output, *, window_seconds=120, start=0, end=DAY_SECONDS, resume_incomplete=False,
             sqlite_direct=False, run_dir=None, iteration=None, allow_native_side_scan=False,
             temp_dir=None, side_cache=None, reserve_bytes=64*1024*1024):
    if not all(math.isfinite(value) for value in (window_seconds, start, end)) or not 0 <= start < end or window_seconds <= 0:
        raise ValueError('Rango temporal o duracion de ventana invalido')
    started = time.perf_counter()
    output = Path(output).resolve()
    initial_source = Path(source).resolve()
    if output == initial_source or output.is_relative_to(initial_source):
        raise ValueError('El visor continuo necesita una carpeta distinta del export anterior')
    if output.exists() and any(output.iterdir()) and not resume_incomplete:
        raise ValueError('La carpeta de destino ya contiene archivos; no se sobrescribe evidencia')
    from simz1_recovery_io import preflight_storage
    preflight_storage(output, 4*1024*1024, reserve_bytes, probe_write=True)
    if sqlite_direct:
        from simz1_sqlite_source import FILE_NAME, build_source
        if not (Path(source) / FILE_NAME).exists():
            if run_dir is None:
                raise ValueError('--sqlite-direct requiere --run-dir para una fuente historica')
            direct_root = output / 'sqlite-source'
            if (direct_root / FILE_NAME).exists():
                if not resume_incomplete:
                    raise ValueError('Fuente preparada existente; use --resume-incomplete')
                _, prepared, prepared_database = checked_source(direct_root)
                if (Path(prepared['run_directory']).resolve() != Path(run_dir).resolve() or
                        prepared_database != (Path(source).resolve() / 'replay.sqlite') or
                        (iteration is not None and prepared['iteration'] != iteration)):
                    raise ValueError('La fuente pendiente corresponde a otra corrida/base/iteracion')
            else:
                build_source(run_dir, source, direct_root, iteration=iteration,
                    side_cache=side_cache, allow_native_side_scan=allow_native_side_scan,
                    temp_dir=temp_dir, reserve_bytes=reserve_bytes)
            source = direct_root
    source_root, old, database = checked_source(source)
    if ((run_dir is not None and Path(old['run_directory']).resolve() != Path(run_dir).resolve()) or
            (iteration is not None and old['iteration'] != iteration)):
        raise ValueError('La fuente no corresponde a la corrida/iteracion solicitada')
    direct = old.get('source_type') == 'sqlite-direct-v1'
    source_export_hash = digest(source_manifest_path(source_root, old))
    source_database_stat = database.stat()
    output = Path(output).resolve()
    if output == source_root or output.is_relative_to(source_root):
        raise ValueError('El visor continuo necesita una carpeta distinta del export anterior')
    if output.exists() and any(output.iterdir()):
        owned_source_only = direct and set(path.name for path in output.iterdir()) == {'sqlite-source'}
        if (not resume_incomplete and not owned_source_only) or (output / 'continuous-manifest.json').exists():
            raise ValueError('La carpeta de destino ya contiene archivos; no se sobrescribe evidencia')
        if any(path.name not in ('temporal', 'config.json', 'index.html', 'sqlite-source') for path in output.iterdir()):
            raise ValueError('La carpeta incompleta contiene archivos ajenos al visor')
    if start < old['replay_window']['start_seconds'] or end > old['replay_window']['end_seconds']:
        raise ValueError('El rango solicitado excede el replay validado')
    application_html()  # Fail before extracting if any frontend source is absent.
    output.mkdir(parents=True, exist_ok=True)
    side_directory = output / 'temporal'
    if not direct:
        side_directory.mkdir(exist_ok=resume_incomplete)
    if direct:
        from simz1_sqlite_source import load_config
        config = load_config(source_root, old)
    else:
        config = html_parts(source_root / 'blocks' / old['blocks'][0]['url'], config=True)
    if config.get('hud', {}).get('run_id') != old['run_id'] or config.get('hud', {}).get('iteration') != old['iteration']:
        raise ValueError('La geometria HTML no pertenece a esta corrida/iteracion')
    native = checked_native_run(old)
    from simz1_freight_completion import observation_contract
    experimental=observation_contract(native)
    if experimental:config['experimental_observation']=experimental
    elif config.get('experimental_observation'):raise ValueError('Replay observation option absent in native manifest')
    if native.get('temporal_policy'):
        config['temporal_policy'] = native['temporal_policy']
        config['study_window'] = native['temporal_policy']['windows']['study']
    fixed_started = time.perf_counter()
    side_bytes = 0
    side_files = []
    resumed_files = 0
    for block in ([] if direct else old['blocks']):
        filename = f'{block["index"]:04d}.json.gz'
        destination = side_directory / filename
        if resume_incomplete and destination.is_file():
            raw = destination.read_bytes()
            previous = json.loads(gzip.decompress(raw))
            if identity(previous) != identity(old) or previous['index'] != block['index']:
                raise ValueError('El archivo temporal pendiente pertenece a otro export')
            if 'source_hud' not in previous:
                parts = html_parts(source_root / 'blocks' / block['url'])
                previous.update(parts)
                raw = gzip.compress(json_bytes(previous), compresslevel=1, mtime=0)
                destination.write_bytes(raw)
            payload = previous
            resumed_files += 1
        else:
            parts = html_parts(source_root / 'blocks' / block['url'])
            payload = {**identity(old), 'index': block['index'], **parts}
            raw = gzip.compress(json_bytes(payload), compresslevel=1, mtime=0)
            destination.write_bytes(raw)
        if payload['source_hud'] != {'run_id': old['run_id'], 'iteration': old['iteration']} or payload['source_replay_window'] != {
                'start_seconds': block['start_seconds'], 'end_seconds': block['end_seconds']}:
            raise ValueError('HTML temporal de otra corrida, iteracion o franja')
        side_files.append({'file': filename, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        side_bytes += len(raw)
        if block['index'] % 50 == 0:
            print(f'Evidencia temporal recuperada: {block["index"] + 1}/{len(old["blocks"])} bloques; sin decodificar viajes', flush=True)
    temporal_seconds = time.perf_counter() - fixed_started
    for layer in config['layers']:
        if layer['id'] in ('trips', 'incidents'):
            layer['data'] = []
    if 'signal_replay' in config:
        for series in config['signal_replay'].get('series', []):
            series['states'] = []
    if 'lane_replay' in config:
        config['lane_replay']['events'] = []
    config.pop('pagination', None)
    config['replay_window'] = dict(start_seconds=start, end_seconds=end)
    config['hud']['reconstructed_vehicles'] = old['counts']['reconstructed_vehicles']
    config['continuous'] = {**identity(old), 'source_version': source_export_hash, 'window_seconds': window_seconds,
        'start_seconds': start, 'end_seconds': end, 'window_count': math.ceil((end-start)/window_seconds),
        'window_endpoint': '/api/window', 'journey_endpoint': '/api/journey', 'sample_rate': 1.0,
        'cache_windows': 3, 'cache_bytes': 128 * 1024 * 1024,
        'total_segments': old['counts']['segments'], 'total_reconstructed_vehicles': old['counts']['reconstructed_vehicles'],
        'visual_vehicle_counts': old.get('visual_vehicle_counts'),
        'native_observed_end_seconds': old['replay_window']['end_seconds']}
    view = dict(replay_window=config['replay_window'], window_seconds=window_seconds)
    daily_window(config, view, old)
    config_bytes = json_bytes(config)
    preflight_storage(output, len(config_bytes) + len(application_html().encode('utf-8')),
                      reserve_bytes, probe_write=True)
    (output / 'config.json').write_bytes(config_bytes)
    # Source edits during a long cold-disk extraction must not publish an older
    # UI snapshot; the actual delivered artifact uses current checked sources.
    document = application_html()
    (output / 'index.html').write_text(document, encoding='utf-8')
    # Recheck after the potentially long extraction before publishing a commit
    # marker. Neither the native manifest nor the original database may change.
    checked_source(source_root)
    stat = database.stat()
    if digest(source_manifest_path(source_root, old)) != source_export_hash or (
            stat.st_size, stat.st_mtime_ns) != (source_database_stat.st_size, source_database_stat.st_mtime_ns):
        raise ValueError('El export de origen cambio durante la preparacion continua')
    manifest = {**identity(old), 'schema_version': 1, 'status': 'complete', 'sample_rate': 1.0,
        'source_type': old.get('source_type', 'paged-html-v1'),
        'source_directory': str(source_root), 'source_export_sha256': source_export_hash,
        'database': str(database), 'database_bytes': stat.st_size, 'database_mtime_ns': stat.st_mtime_ns,
        'replay_window': config['replay_window'], 'window_seconds': window_seconds,
        'window_count': config['continuous']['window_count'], 'source_blocks': old['blocks'],
        **{key: view[key] for key in ('source_replay_window', 'source_time_horizon', 'metrics_window')},
        'temporal_files': side_files, 'config_sha256': hashlib.sha256(config_bytes).hexdigest(),
        'planned_persons': old['planned_persons'], 'planned_trips': old['planned_trips'],
        'counts': old['counts'], 'operational_counts': old.get('operational_counts', {}),
        'old_phases_seconds': old.get('phases_seconds', {}), 'old_html_bytes': old.get('html_bytes', 0),
        'old_process_peak_working_set_bytes': old.get('process_peak_working_set_bytes'),
        'phases_seconds': {'source_validation_and_fixed_geometry': fixed_started-started,
                           'recover_native_signals_and_incidents': temporal_seconds,
                           'total': time.perf_counter()-started},
        'process_peak_working_set_bytes': peak_working_set(), 'temporal_bytes': side_bytes,
        'reused_incomplete_temporal_files': resumed_files,
        'application_bytes': (output / 'index.html').stat().st_size + len(config_bytes),
        'note': 'Read-only reuse; original evidence retained. Replay follows the validated observation window; source counts retain their explicitly recorded metric horizon.'}
    # The manifest is the commit marker; an interrupted export cannot be served.
    from simz1_run import atomic_json
    atomic_json(output / 'continuous-manifest.json', manifest)
    print(f'Visor continuo generado: {output / "index.html"} ({manifest["phases_seconds"]["total"]:.2f}s)', flush=True)
    return manifest


MAX_SPATIAL_PREPARATION_BYTES = 32 * 1024 * 1024


class VerifiedWorkerSpatial(dict):
    """Picklable result of the server's complete spatial verification."""
    pass


class VerifiedQueueSupport(dict):
    """Private, picklable anchor produced after checking the index derivation."""
    pass


PARTIAL_VISUAL_POLICY = 'partial-native-v1'


def checked_visual_policy(value):
    if value is not None and value != PARTIAL_VISUAL_POLICY:
        raise ValueError('Unsupported partial visual policy')
    return value


def pending_queue_context(seeds):
    """Declare unavailable visual support; never resolve or certify a pose."""
    from dataclasses import asdict
    from simz1_queue_context import POLICY, DEPENDENCY_POLICY, Limits, interval_key
    by_seed={}
    for _,record in seeds:
        key=interval_key(record)
        by_seed[key]=dict(complete=False,reason='reconstruction_pending',
            body_position_available=False,metrics={},record_keys=[],missing_topology_links=[])
    return dict(schema_version=1,policy=POLICY,dependency_policy=DEPENDENCY_POLICY,
        visual_policy=PARTIAL_VISUAL_POLICY,availability='not_reconstructed',
        limits=asdict(Limits()),by_seed=by_seed,domain_scope='unresolved_partial_visual',
        segments=[],transition_segments=[],trips={},lane_events=[],
        metrics=dict(sql_queries=0,decoded_records=0,pending_seeds=len(by_seed)))


class ContinuousReplay:
    def __init__(self, directory, *, spatial_preparation=None, spatial_cache_root=None,
                 queue_support_root=None, queue_support_preparation=None,
                 queue_checkpoint_preparation=None, visual_policy=None):
        self.visual_policy=checked_visual_policy(visual_policy)
        if self.visual_policy is not None and (queue_support_preparation is not None or queue_checkpoint_preparation is not None):
            raise ValueError('Partial visual mode cannot install causal support or checkpoints')
        initialization_started=time.perf_counter()
        initialization_stages={}
        stage_started=initialization_started
        def stage(name):
            nonlocal stage_started
            now=time.perf_counter();initialization_stages[name]=now-stage_started;stage_started=now
        self.root = Path(directory).resolve(strict=True)
        self.stored_manifest = json.loads((self.root / 'continuous-manifest.json').read_text(encoding='utf-8'))
        self.manifest = dict(self.stored_manifest)
        self.identity = identity(self.manifest)
        if self.manifest.get('status') != 'complete' or self.manifest.get('sample_rate') != 1:
            raise ValueError('El visor continuo no esta completo o tiene muestreo')
        source, old, self.database = checked_source(self.manifest['source_directory'])
        if identity(old) != self.identity or digest(source_manifest_path(source, old)) != self.manifest['source_export_sha256']:
            raise ValueError('La identidad del export original cambio')
        if (self.manifest['source_blocks'] != old['blocks'] or
                Path(self.manifest['database']).resolve() != self.database or
                self.manifest.get('source_type', 'paged-html-v1') != old.get('source_type', 'paged-html-v1')):
            raise ValueError('El contrato temporal/base del visor difiere de su fuente validada')
        stat = self.database.stat()
        if stat.st_size != self.manifest['database_bytes'] or stat.st_mtime_ns != self.manifest['database_mtime_ns']:
            raise ValueError('El SQLite original cambio despues de preparar el visor continuo')
        stage('source_manifests_sqlite_and_side_validation')
        self.config_raw = (self.root / 'config.json').read_bytes()
        if hashlib.sha256(self.config_raw).hexdigest() != self.manifest['config_sha256']:
            raise ValueError('La geometria/configuracion fija cambio')
        self.config = json.loads(self.config_raw)
        continuous = self.config['continuous']
        if (identity(continuous) != self.identity or
                self.config['replay_window'] != self.manifest['replay_window'] or
                any(continuous[key] != self.manifest['replay_window'][key] for key in ('start_seconds', 'end_seconds')) or
                any(continuous[key] != self.manifest[key] for key in ('window_count', 'window_seconds'))):
            raise ValueError('La configuracion y el manifiesto continuo no comparten identidad/ventana')
        self.native_run = checked_native_run(old)
        if self.visual_policy is not None:
            continuous['visual_policy']=self.visual_policy
            self.config['partial_visual_policy']=dict(policy=self.visual_policy,
                pending_reason='reconstruction_pending',body_position_available=False,
                native_status=self.native_run['status'],native_validation=self.native_run['validation']['status'])
        from simz1_freight_completion import observation_contract
        experimental=observation_contract(self.native_run)
        if experimental:self.config['experimental_observation']=experimental
        elif self.config.get('experimental_observation'):raise ValueError('Replay observation option absent in native manifest')
        if self.native_run.get('temporal_policy'):
            self.config['temporal_policy'] = self.native_run['temporal_policy']
            self.config['study_window'] = self.native_run['temporal_policy']['windows']['study']
        daily_window(self.config, self.manifest, old)
        stage('fixed_config_and_native_manifest')
        from simz1_visual_lanes import load_visual_lanes
        from simz1_gateway_od import validated_spatial_demand
        spatial_cache=None
        spatial_cache_error=None
        spatial_mode='worker_preparation'
        if spatial_preparation is None:
            self.spatial=None
            if spatial_cache_root is not False and self.native_run.get('spatial_demand',{}).get('mode')=='balanced-gateway-v1':
                from simz1_replay_spatial_cache import SpatialPreparationCache
                from simz1_workflow_state import fingerprint
                from simz1_window_cache import reader_version
                cache_root=spatial_cache_root or Path(__file__).resolve().parents[1]/'runtime/replay/spatial-cache'
                try:
                    spatial_cache=SpatialPreparationCache(cache_root,{**self.identity,'source_version':self.manifest['source_export_sha256']},self.manifest,
                        version=reader_version()+':'+fingerprint())
                    self.spatial=spatial_cache.load(lambda preparation:self.checked_persistent_spatial_preparation(preparation,old))
                except (OSError,ValueError) as error:
                    # Optional storage cannot prevent ordinary full validation.
                    # Programming errors still propagate; no input is accepted
                    # here and the full spatial validator remains mandatory.
                    spatial_cache_error=type(error).__name__+': '+str(error)
                    spatial_cache=None
            spatial_mode='verified_persistent_preparation' if self.spatial is not None else 'full_spatial_validation'
            if self.spatial is None:
                self.spatial = validated_spatial_demand(Path(old['run_directory']), self.native_run)
        else:
            self.spatial = self.checked_spatial_preparation(spatial_preparation,old)
        stage('spatial_validation_or_verified_reuse')
        from simz1_freight import verified_contract
        self.freight_contract=verified_contract(Path(old['run_directory']),self.native_run)
        self.config['postprocessor_contract_version']='balanced-replay-contract-v1'
        if getattr(self, 'spatial', None) is not None:
            self.config['spatial_demand'] = dict(self.spatial, validated=True, identity=self.identity)
        elif self.config.get('spatial_demand') is not None:
            raise ValueError('Dominio espacial sin respaldo en la corrida nativa')
        self.config['visual_lanes'] = load_visual_lanes(old['run_directory'], self.native_run, self.identity)
        from simz1_queue_context import queue_domains
        # Include the configured long bodies in proximity bounds. Family
        # fallback maxima include the catalog's 18 x 2.5 m articulated bus.
        from simz1_motion import elements
        from simz1_run import checked_path
        body_length,body_width=18.0,2.5
        seen_vehicle_files=set()
        for key in ('transit_vehicles','input:vehicles-vehiclesFile.xml','input:vehicles.xml'):
            record=self.native_run.get('inputs',{}).get(key)
            if record is None:continue
            vehicle_file=checked_path(Path(old['run_directory']),record)
            if vehicle_file in seen_vehicle_files:continue
            seen_vehicle_files.add(vehicle_file)
            with closing(elements(vehicle_file,{'vehicleType','vehicle'})) as definitions:
                for definition in definitions:
                    if definition.tag!='vehicleType':continue
                    for tag in ('length','width'):
                        value=definition.find(tag)
                        if value is None:continue
                        number=float(value.get('meter','nan'))
                        if not math.isfinite(number) or number<=0:raise ValueError('Invalid configured vehicle body bound')
                        if tag=='length':body_length=max(body_length,number)
                        else:body_width=max(body_width,number)
        self.queue_domains=queue_domains(self.config['visual_lanes'],max_body_length_m=body_length,max_body_width_m=body_width)
        from simz1_queue_context import QueueContext
        self.queue_namespace=QueueContext.namespace(self.queue_domains,self.config['visual_lanes'])
        from simz1_transit_stops import load_stop_display
        self.config['transit_stops'] = load_stop_display(Path(old['run_directory']), self.native_run, self.identity)
        stage('freight_network_geometry_queue_domains_and_stops')
        self.config['continuous']['hud_endpoint'] = '/api/hud'
        # The native identity alone does not distinguish two compatible exports
        # of the same iteration. Keep this transport version out of SQLite's
        # historical export_identity table and bind every new client to it.
        self.config['continuous']['source_version'] = self.manifest['source_export_sha256']
        self.source_manifest = old
        self.source_root = source
        self.queue_facility_support=(prepare_facility_support(old['run_directory'],self.native_run,
            self.identity,old['database_sha256']) if old.get('source_type')=='sqlite-direct-v1' else None)
        if self.queue_facility_support is not None:
            self.config['continuous']['queue_facility_support']=dict(self.queue_facility_support)
        self.config['replay_source'] = dict(source_type=self.manifest.get('source_type', 'paged-html-v1'),
            source_manifest_sha256=self.manifest['source_export_sha256'],
            database_sha256=old.get('database_sha256'),
            database_bytes=self.manifest['database_bytes'],
            database_mtime_ns=self.manifest['database_mtime_ns'],
            replay_manifest_sha256=digest(self.root / 'continuous-manifest.json'))
        if old.get('source_type') == 'sqlite-direct-v1':
            # Two bounded readers prepare two successors in parallel; retain
            # the same source/API windows and every native timestamp.
            self.config['continuous']['playback'] = dict(prefetch_ahead=2)
        self.config_raw = json_bytes(self.config)
        self.blocks = self.manifest['source_blocks']
        self.block_ends = [block['end_seconds'] for block in self.blocks]
        self.lookup_cache = RuntimeReadCache()
        self.temporal_cache = RuntimeReadCache(8*1024*1024, 4)
        self.queue_context_cache = RuntimeReadCache(8*1024*1024, 4096)
        self.queue_record_cache = RuntimeReadCache(64*1024*1024, 16384)
        self.queue_seed_cache = RuntimeReadCache(8*1024*1024, 8192)
        self.queue_dependency_cache = RuntimeReadCache(8*1024*1024, 16384)
        self.queue_index_cache = RuntimeReadCache(8*1024*1024, 16)
        self.direct_side = None
        if old.get('source_type') == 'sqlite-direct-v1':
            from simz1_sqlite_source import load_side_data
            self.direct_side = load_side_data(source, old)
        stage('auxiliary_indexes_and_side_data')
        self.prepare_queue_support(queue_support_root, queue_support_preparation)
        self.install_queue_checkpoint_library(queue_checkpoint_preparation)
        stage('causal_support_unavailable_partial' if self.visual_policy is not None else 'verified_causal_support_index')
        # Aggregate evidence is prepared offline from the pinned census/export.
        # Never rebuild it, scan native events, or change historical data while
        # opening a viewer. Old exports remain usable without the optional index.
        self.aggregate_replay = None
        if (self.root / 'aggregate-manifest.json').is_file():
            from simz1_aggregate_replay import AggregateReplay
            self.aggregate_replay = AggregateReplay(self.root, self.response_identity)
            self.config['aggregate_view'] = {
                **self.aggregate_replay.metadata(), 'available': True,
                'endpoint': '/api/aggregate',
            }
        else:
            self.config['aggregate_view'] = dict(available=False, reason='aggregate_index_not_prepared')
        self.config_raw = json_bytes(self.config)
        stage('aggregate_evidence_index')
        # Only a fully initialized reader may publish its spatial preparation.
        # Reuse still rechecks the original manifest and every pinned input.
        if spatial_cache is not None and spatial_mode=='full_spatial_validation':
            preparation=self.spatial_preparation()
            if preparation is not None:spatial_cache.store(preparation)
        stage('publish_verified_preparation')
        self.initialization=dict(seconds=initialization_stages,total_seconds=time.perf_counter()-initialization_started,
            spatial_mode=spatial_mode,spatial_cache=spatial_cache.summary() if spatial_cache is not None else None,
            spatial_cache_error=spatial_cache_error,
            scope='process initialization; no window prepared and no operating-system cache flush')

    def spatial_preparation(self):
        """Share already verified spatial data only with this server's workers.

        No public API can supply this object. Workers and the optional private
        on-disk cache still hash every pinned input and check the original
        native identity; only a previously verified pure OD derivation is
        reused. Window/trip validation and per-person hashes remain unchanged.
        """
        spatial=getattr(self,'spatial',None)
        if spatial is None or spatial.get('mode')!='balanced-gateway-v1':return None
        payload=dict(identity=self.identity,source_directory=str(self.source_root),
            source_version=self.manifest['source_export_sha256'],spatial=dict(spatial),
            metadata_hashes=dict(spatial.metadata_hashes),
            postprocessor_version=spatial.postprocessor_version)
        raw=json_bytes(payload)
        if len(raw)>MAX_SPATIAL_PREPARATION_BYTES:
            # An oversized transfer falls back to the ordinary full worker
            # validation; never truncate people, proofs or spatial metadata.
            return None
        return dict(payload=payload,sha256=hashlib.sha256(raw).hexdigest())

    def checked_spatial_preparation(self, preparation, source):
        from simz1_run import checked_path
        payload=preparation.get('payload')
        raw=json_bytes(payload)
        if (len(raw)>MAX_SPATIAL_PREPARATION_BYTES or not isinstance(payload,dict) or
                hashlib.sha256(raw).hexdigest()!=preparation.get('sha256') or
                payload.get('identity')!=self.identity or payload.get('source_version')!=self.manifest['source_export_sha256'] or
                Path(payload.get('source_directory','')).resolve()!=Path(self.manifest['source_directory']).resolve() or
                payload.get('spatial',{}).get('mode')!='balanced-gateway-v1' or
                self.native_run.get('spatial_demand',{}).get('mode')!='balanced-gateway-v1' or
                payload.get('postprocessor_version')!='balanced-replay-contract-v1'):
            raise ValueError('Worker spatial preparation identity/content mismatch')
        if any(payload['spatial'].get(key)!=value for key,value in self.native_run['spatial_demand'].items()):
            raise ValueError('Worker spatial preparation differs from the native spatial contract')
        directory=Path(source['run_directory'])
        # Inputs include source and effective network/lanes, plans, OSM, the
        # service derivation, OD catalogue, policy and experiment specification.
        records=list(self.native_run['inputs'].values())
        if self.native_run.get('effective_config'):records.append(self.native_run['effective_config'])
        records.extend(value for value in self.native_run.get('balanced_od',{}).values()
                       if isinstance(value,dict) and 'path' in value and 'sha256' in value)
        checked=set()
        for record in records:
            key=(record['path'],record['sha256'])
            if key not in checked:
                checked_path(directory,record);checked.add(key)
        result=VerifiedWorkerSpatial(payload['spatial'])
        result.metadata_hashes=payload['metadata_hashes']
        result.postprocessor_version=payload['postprocessor_version']
        return result

    def checked_persistent_spatial_preparation(self, preparation, source):
        result=self.checked_spatial_preparation(preparation,source)
        # Unlike an object just transferred to a private worker, a disk entry
        # must independently reproduce all derived fields. A self-consistent
        # edited checksum is not proof of the per-person or visual-link data.
        from simz1_replay_spatial_cache import validate_derived_preparation
        validate_derived_preparation(preparation,Path(source['run_directory']),self.native_run)
        return result

    def check_identity(self, query):
        if any(query.get(key) != [str(value)] for key, value in self.identity.items()):
            raise ValueError('La consulta no corresponde a la corrida, iteracion y manifiesto validados')
        # Legacy inspection tools may still use the native triple. Current
        # clients always send this version and reject responses without it.
        if 'source_version' in query and query['source_version'] != [self.manifest['source_export_sha256']]:
            raise ValueError('La version de fuente solicitada no corresponde al replay validado')
        visual_policy=getattr(self,'visual_policy',None)
        if (visual_policy is not None and query.get('visual_policy') != [visual_policy] or
                visual_policy is None and 'visual_policy' in query):
            raise ValueError('La politica visual solicitada no corresponde a esta sesion')
        if 'checkpoint_library_root' in query and query['checkpoint_library_root'] != [self.response_identity.get('checkpoint_library_root')]:
            raise ValueError('La biblioteca de soporte solicitada no corresponde al replay verificado')

    @property
    def response_identity(self):
        result={**self.identity, 'source_version': self.manifest.get('source_export_sha256')}
        if getattr(self,'visual_policy',None) is not None:result['visual_policy']=self.visual_policy
        preparation=getattr(self,'queue_checkpoint_preparation',None)
        if preparation is not None:result['checkpoint_library_root']=preparation['contract']['root_digest']
        return result

    def hud(self, query):
        self.check_identity(query)
        if query.get('source_version') != [self.manifest['source_export_sha256']]:
            raise ValueError('Se requiere la versión exacta de la fuente para consultar el HUD')
        for key, value in self.manifest['replay_window'].items():
            raw = query.get(key, [])
            if len(raw) != 1:
                raise ValueError('Se requiere la ventana visible completa para consultar el HUD')
            try:
                actual = float(raw[0])
            except (ValueError, TypeError):
                raise ValueError('Ventana HUD invalida') from None
            if not math.isfinite(actual) or actual != value:
                raise ValueError('La ventana HUD no corresponde al replay visible')
        if digest(source_manifest_path(self.source_root, self.source_manifest)) != self.manifest['source_export_sha256']:
            raise ValueError('El export validado cambio durante la consulta HUD')
        result=checked_hud(checked_native_run(self.source_manifest), self.source_manifest,
                           self.manifest, self.config)
        if getattr(self,'visual_policy',None) is not None:result['visual_policy']=self.visual_policy
        return result

    def aggregate_time(self, query):
        self.check_identity(query)
        if query.get('source_version') != [self.manifest['source_export_sha256']]:
            raise ValueError('Se requiere la version exacta de la fuente para consultar agregados')
        if self.aggregate_replay is None:
            raise ValueError('Indice agregado no preparado para este replay')
        self.check_source_files()
        self.aggregate_replay.check_source_files()
        raw = query.get('time', [])
        if len(raw) != 1:
            raise ValueError('Se requiere exactamente un instante agregado')
        try:
            instant = float(raw[0])
        except (ValueError, TypeError):
            raise ValueError('Instante agregado invalido') from None
        window = self.manifest['replay_window']
        if not math.isfinite(instant) or not window['start_seconds'] <= instant <= window['end_seconds']:
            raise ValueError('Instante agregado fuera del replay')
        return instant

    def aggregate_snapshot(self, instant):
        self.check_source_files()
        if self.aggregate_replay is None:
            raise ValueError('Indice agregado no preparado para este replay')
        return {**self.aggregate_replay.snapshot(instant), **self.response_identity}

    def check_source_files(self):
        if getattr(self, 'spatial', None) is not None:
            from simz1_run import checked_path
            checked_native_run(self.source_manifest)
            checked_path(Path(self.source_manifest['run_directory']), self.native_run['inputs']['zone_boundary'])
        stat = self.database.stat()
        if (stat.st_size, stat.st_mtime_ns) != (self.manifest['database_bytes'], self.manifest['database_mtime_ns']):
            raise ValueError('El SQLite original cambio durante la sesion')

    def connection(self):
        self.check_source_files()
        if getattr(self, 'source_manifest', {}).get('source_type') == 'sqlite-direct-v1':
            from simz1_sqlite_source import readonly_database
            return cancellable_connection(readonly_database(self.database, self.identity))
        connection = connect(self.database)
        actual = dict(connection.execute('SELECT key,value FROM export_identity'))
        if actual != {key: str(value) for key, value in self.identity.items()}:
            connection.close()
            raise ValueError('El SQLite ya no corresponde a la corrida validada')
        return cancellable_connection(connection)

    def validate_spatial_trip(self, trip):
        if isinstance(trip, dict) and trip.get('Transit') is not None:
            from simz1_transit_replay import validate_transit_trip
            data = validate_transit_trip(trip)
            inputs = getattr(self, 'native_run', {}).get('inputs', {})
            for field, artifact in [('schedule_sha256', 'transit_schedule'), ('vehicles_sha256', 'transit_vehicles')]:
                if inputs.get(artifact, {}).get('sha256') != data['source'][field]:
                    raise ValueError('Expedicion publica ajena a las entradas verificadas de esta corrida')
            if data['source'].get('lanes_sha256') is not None and data['source']['lanes_sha256'] != (
                    getattr(self, 'native_run', {}).get('effective_lane_configuration_validation', {})
                    .get('loaded_artifacts', {}).get('lanes', {}).get('sha256')):
                raise ValueError('Posicion de parada ajena a los carriles efectivos verificados')
            scope=getattr(self,'queue_facility_support',None)
            if scope is not None and any(interval.get('state')=='stop' and interval.get('is_blocking_lane') is True and
                    interval.get('link_id') not in scope['blocking_links'] for interval in data['activity_intervals']):
                raise ValueError('Blocking stop lies outside the complete pinned native facility scope')
            if getattr(self, 'spatial', None) is not None and self.spatial.get('mode')!='balanced-gateway-v1' and not set(data['route_links']) <= set(self.spatial['allowed_links']):
                raise ValueError('Ruta publica fuera del dominio espacial validado')
            return
        if isinstance(trip,dict) and trip.get('Person_ID') in getattr(self,'freight_contract',{}):
            row=self.freight_contract[trip['Person_ID']]
            expected=dict(vehicle_id=trip['Person_ID'],route_id=row['route_id'],planned_departure=row['departure_seconds'],
                route_link_ids=row['link_ids'],roster_source=self.native_run['inputs']['input:freight-weekday/roster.json'])
            if trip.get('Freight')!=expected or trip.get('Trip_Index')!=1 or trip.get('Trip_ID')!=trip['Person_ID']+':trip:0001':
                raise ValueError('Freight replay identity/route/source differs from the native roster')
            return
        if isinstance(trip,dict) and trip.get('Freight') is not None:raise ValueError('Unknown freight actor in replay')
        if getattr(self, 'spatial', None) is None:
            return
        from simz1_gateway_od import validate_od_metadata
        from simz1_temporal import trip_id
        if (not isinstance(trip, dict) or not isinstance(trip.get('Person_ID'), str) or
                type(trip.get('Trip_Index')) is not int or trip['Trip_Index'] < 1 or
                trip.get('Trip_ID') != trip_id(trip['Person_ID'], trip['Trip_Index'])):
            raise ValueError('Identidad de viaje espacial incompatible')
        validate_od_metadata(trip.get('OD'), self.spatial,person_id=trip['Person_ID'])

    @staticmethod
    def validate_native_segment(decoded, key, vehicle, start, end):
        """Validate only requested records, without modifying native bytes."""
        from simz1_recovery_io import _loads
        record = _loads(decoded)
        stamps = record.get('timestamps') if isinstance(record, dict) else None
        if (not isinstance(record, dict) or record.get('Replay_Journey_Key') != key or
                not isinstance(vehicle, str) or not vehicle or record.get('vehicle') != vehicle or
                not isinstance(stamps, list) or stamps != [start, end] or
                any(type(value) not in (int, float) for value in stamps) or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)) or
                start > end or not isinstance(record.get('Motion_Plan'), dict)):
            raise ValueError('Movimiento SQLite incompatible con identidad, tiempos o Motion_Plan')
        return record

    def block_indexes(self, start, end):
        first = bisect_left(self.block_ends, start)
        if first < len(self.blocks) and self.block_ends[first] == start:
            first += 1
        result = []
        for index in range(first, len(self.blocks)):
            if self.blocks[index]['start_seconds'] >= end:
                break
            result.append(index)
        return result

    def temporal(self, indexes, start, end):
        if getattr(self, 'direct_side', None) is not None:
            # Complete native series are loaded once from the hashed source.
            # Bisect each group; never scan all state events for a window.
            signal = self.direct_side['signal_replay']
            series = []
            for group in signal.get('series', []):
                states = group['states']
                first = bisect_left(states, start, key=lambda state: state[0])
                last = bisect_left(states, end, key=lambda state: state[0])
                series.append({**group, 'states': states[max(0, first-1):last]})
            return {**signal, 'series': series, 'window': [start, end],
                'retained_state_events': sum(len(group['states']) for group in series)}, [
                incident for incident in self.direct_side['incidents'] if
                incident['start'] < end and (incident['end'] is None or incident['end'] > start)]
        groups, incidents, incident_counts = {}, {}, Counter()
        summary = {}
        for number, index in enumerate(indexes):
            entry = self.manifest['temporal_files'][index]
            path = self.root / 'temporal' / entry['file']
            stat = path.stat()
            cache_key = (index, entry['sha256'], stat.st_size, stat.st_mtime_ns)
            cache = getattr(self, 'temporal_cache', None)
            found, payload = cache.get(cache_key) if cache else (False, None)
            if not found:
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('La evidencia temporal cambio')
                decoded = gzip.decompress(raw)
                payload = json.loads(decoded)
                if identity(payload) != self.identity or payload['index'] != index:
                    raise ValueError('Evidencia temporal de otra corrida o bloque')
                if cache:
                    cache.put(cache_key, payload, len(decoded))
            signals = payload['signal_replay']
            summary = {key: value for key, value in signals.items() if key not in ('series', 'window', 'retained_state_events')}
            for series in signals.get('series', []):
                key = (series['system_id'], series['group_id'])
                if key not in groups:
                    groups[key] = {**series, 'states': []}
                groups[key]['states'].extend(state for state in series['states']
                    if number == 0 or state[0] >= self.blocks[index]['start_seconds'])
            block_incident_counts = Counter()
            for incident in payload['incidents']:
                if incident['start'] < end and (incident['end'] is None or incident['end'] > start):
                    key = json_bytes(incident)
                    incidents[key] = incident
                    block_incident_counts[key] += 1
            # Overlap copies from adjacent parent blocks are redundant, but
            # identical native incidents within one block retain multiplicity.
            incident_counts |= block_incident_counts
        for group in groups.values():
            states = group['states']
            first = bisect_left(states, start, key=lambda state: state[0])
            last = bisect_left(states, end, key=lambda state: state[0])
            group['states'] = states[max(0, first-1):last]
        return {**summary, 'series': list(groups.values()), 'window': [start, end],
            'retained_state_events': sum(len(group['states']) for group in groups.values())}, [
                incident for key, incident in incidents.items() for _ in range(incident_counts[key])]

    def prepare_queue_support(self, root=None, preparation=None):
        """Prepare once before serving; workers reuse the sealed external index.

        No index is written inside the native run. A window opens its own
        read-only connection, so the parent/server never shares SQLite handles
        between worker processes or HTTP threads. Legacy sources retain their
        existing conservative reader.
        """
        self.queue_support_path = self.queue_support_contract = None
        self.queue_support_sha256 = None
        if getattr(self,'visual_policy',None) is not None:
            if preparation is not None:raise ValueError('Partial visual mode cannot install causal support')
            return
        if (root is False or self.source_manifest.get('source_type') != 'sqlite-direct-v1'
                or self.queue_domains is None):
            if preparation is not None:
                raise ValueError('Worker causal support does not apply to this source/geometry')
            return
        from simz1_queue_support import SupportIndex, contract
        expected = contract(self.database, self.identity,
                            self.source_manifest.get('database_sha256'), self.config['visual_lanes'])
        if preparation is not None:
            if (not isinstance(preparation, VerifiedQueueSupport) or
                    set(preparation) != {'path', 'contract', 'index_sha256'} or
                    preparation['contract'] != expected):
                raise ValueError('Worker causal support lacks the private verified parent anchor')
            with closing(SupportIndex(preparation['path'], expected,
                                      expected_sha256=preparation['index_sha256'])) as support:
                self.queue_support_path = support.path
                self.queue_support_contract = expected
                self.queue_support_sha256 = preparation['index_sha256']
            return
        directory = root or Path(__file__).resolve().parents[1]/'runtime/replay/queue-support'
        with closing(self.connection()) as source:
            with closing(SupportIndex.prepare(directory, source, expected,
                    validate_segment=self.validate_native_segment,
                    visual_lanes=self.config['visual_lanes'])) as support:
                self.queue_support_path = support.path
                self.queue_support_contract = expected
                self.queue_support_sha256 = support.receipt['sha256']

    def queue_support_preparation(self):
        if getattr(self, 'queue_support_path', None) is None:
            return None
        return VerifiedQueueSupport(path=str(self.queue_support_path),
                                    contract=self.queue_support_contract,
                                    index_sha256=self.queue_support_sha256)

    def install_queue_checkpoint_library(self, preparation):
        """Install only a descriptor produced by live semantic verification.

        This intentionally has no path/JSON receipt fallback. An independent
        parent must verify/evaluate persisted state before starting its readers.
        """
        self.queue_checkpoint_preparation=None
        self.queue_checkpoint_expected=None
        if preparation is None:return
        if getattr(self,'visual_policy',None) is not None:
            raise ValueError('Partial visual mode cannot install checkpoints')
        from simz1_queue_checkpoint_library import CheckpointLibrary, VerifiedCheckpointLibrary
        from simz1_queue_checkpoint import kernel_contract
        if not isinstance(preparation,VerifiedCheckpointLibrary) or self.queue_support_path is None:
            raise ValueError('Queue checkpoint library requires verified parent/index preparation')
        contract=kernel_contract(self.queue_support_contract,self.queue_support_sha256,
                                 self.config['visual_lanes'],preparation['contract']['settings'],
                                 facility_support=getattr(self,'queue_facility_support',None))
        expected=dict(identity=self.identity,index_sha256=self.queue_support_sha256,
            source_sqlite_sha256=self.source_manifest['database_sha256'],
            geometry_sha256=self.queue_support_contract['geometry_sha256'],settings=contract['settings'])
        # Use the producer's canonical codec, rather than relying on equivalent
        # JSON encodings to have identical byte hashes.
        from simz1_queue_context import encoded
        expected['kernel_sha256']=hashlib.sha256(encoded(contract)).hexdigest()
        with closing(CheckpointLibrary(preparation,expected=expected)):
            self.queue_checkpoint_preparation=preparation
            self.queue_checkpoint_expected=expected
        self.config['continuous']['checkpoint_library_root']=preparation['contract']['root_digest']
        self.config['continuous']['checkpoint_settings']=preparation['contract']['settings']
        self.config_raw=json_bytes(self.config)

    def resolve_queue_context(self, connection, seeds):
        if getattr(self,'visual_policy',None) is not None:return pending_queue_context(seeds)
        from simz1_queue_context import QueueContext
        options = dict(validate_segment=self.validate_native_segment,
            validate_trip=self.validate_spatial_trip,
            cache=getattr(self, 'queue_context_cache', None),
            record_cache=getattr(self, 'queue_record_cache', None),
            seed_cache=getattr(self, 'queue_seed_cache', None),
            dependency_cache=getattr(self, 'queue_dependency_cache', None),
            index_cache=getattr(self, 'queue_index_cache', None),
            namespace=getattr(self, 'queue_namespace', None),
            domains=getattr(self, 'queue_domains', None),
            visual_lanes=getattr(self, 'config', {}).get('visual_lanes'),
            facility_support=getattr(self,'queue_facility_support',None))
        if getattr(self, 'queue_support_path', None) is not None:
            from simz1_queue_support import SupportIndex
            with closing(SupportIndex(self.queue_support_path, self.queue_support_contract,
                                      expected_sha256=self.queue_support_sha256)) as support:
                if getattr(self,'queue_checkpoint_preparation',None) is not None:
                    from simz1_queue_checkpoint_library import CheckpointLibrary
                    options['namespace']=(options['namespace'],self.queue_checkpoint_preparation['contract']['root_digest'])
                    with closing(CheckpointLibrary(self.queue_checkpoint_preparation,
                            expected=self.queue_checkpoint_expected)) as library:
                        return QueueContext(connection,self.blocks,support_index=support,
                                            checkpoint_library=library,**options).resolve(seeds)
                return QueueContext(connection, self.blocks, support_index=support, **options).resolve(seeds)
        return QueueContext(connection, self.blocks, **options).resolve(seeds)

    def window(self, index):
        """Inspection/test convenience; the HTTP hot path uses window_bytes."""
        return json.loads(self.window_bytes(index))

    def window_bytes(self, index, *, seconds=None):
        """Reuse validated serialized movements without rebuilding their tree.

        The original zlib payload is already JSON with complete Motion_Plan and
        no duplicated Trip. Keeping those bytes avoids two million-object
        parse/serialize passes and preserves numbers/fields exactly.
        """
        seconds=self.manifest['window_seconds'] if seconds is None else seconds
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0:
            raise ValueError('Duracion de ventana de transporte invalida')
        window_count=math.ceil((self.manifest['replay_window']['end_seconds']-self.manifest['replay_window']['start_seconds'])/seconds)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < window_count:
            raise ValueError('Indice de ventana fuera del replay')
        started = time.perf_counter()
        profile = dict(sqlite=0.0, zlib_decompress=0.0, connection_validation=0.0, validation=0.0)
        counters = dict(sql_queries=0, lookup_cache_hits=0, decoded_records=0)
        direct = getattr(self, 'source_manifest', {}).get('source_type') == 'sqlite-direct-v1'
        queue_seeds = []
        def decompress(raw, *, segment=None, lane_time=None, queue_seed_id=None):
            checkpoint(decoded_records=counters['decoded_records'])
            tick = time.perf_counter()
            try:
                decoded = zlib.decompress(raw)
            except zlib.error as exc:
                raise ValueError('Registro comprimido SQLite corrupto') from exc
            profile['zlib_decompress'] += time.perf_counter()-tick
            counters['decoded_records'] += 1
            if direct:
                validation_start = time.perf_counter()
                if segment is not None:
                    native = self.validate_native_segment(decoded, *segment)
                    if queue_seed_id is not None:
                        from simz1_queue_context import hold_time
                        if hold_time(native) is not None:
                            queue_seeds.append((queue_seed_id, native))
                elif lane_time is not None:
                    from simz1_recovery_io import _loads
                    event = _loads(decoded)
                    if (not isinstance(event, dict) or event.get('time') != lane_time or
                            type(event.get('time')) not in (int, float) or
                            event.get('vehicle') not in vehicles):
                        raise ValueError('Evento de carril incompatible con la ventana SQLite')
                profile['validation'] += time.perf_counter()-validation_start
            return decoded
        start = self.manifest['replay_window']['start_seconds'] + index * seconds
        end = min(self.manifest['replay_window']['end_seconds'], start + seconds)
        # The global terminal instant is drawable (24:00), unlike internal
        # exclusive window endpoints. Include native evidence at exactly end
        # without shifting or extending any segment/event timestamp.
        query_end = math.nextafter(end, math.inf) if index == window_count-1 else end
        indexes = self.block_indexes(start, query_end)
        placeholders = ','.join('?' for _ in indexes)
        output = io.BytesIO()
        output.write(b'{"segments":[')
        trips, vehicles, count, edges = {}, set(), 0, {}
        connection_started = time.perf_counter()
        with closing(self.connection()) as connection:
            profile['connection_validation'] = time.perf_counter()-connection_started
            def execute(sql, args):
                checkpoint('window_records', sql_queries=counters['sql_queries'])
                tick = time.perf_counter()
                cursor = connection.execute(sql, args)
                profile['sqlite'] += time.perf_counter()-tick
                counters['sql_queries'] += 1
                return ProfiledCursor(cursor, profile)

            def lookup(sql, args):
                # Exact immutable predecessor lookups recur across adjacent
                # windows, especially during long recorded holds. Identity and
                # file fingerprint were checked before using this shared cache.
                cache = getattr(self, 'lookup_cache', None)
                key = (sql, args)
                found, row = cache.get(key) if cache else (False, None)
                if found:
                    counters['lookup_cache_hits'] += 1
                    return row
                row = execute(sql, args).fetchone()
                if cache:
                    size = len(sql.encode('utf-8'))+sum(len(str(value).encode('utf-8')) for value in args)+64
                    size += sum(len(v.encode('utf-8')) if isinstance(v, str) else len(v) if isinstance(v, bytes) else 16 for v in row or ())
                    cache.put(key, row, size)
                return row
            closing_ids = getattr(self, 'source_manifest', {}).get('closing_segment_ids', []) if end == self.manifest['replay_window']['end_seconds'] else []
            if any(type(value) is not int or value < 1 for value in closing_ids):
                raise ValueError('Identificadores de cierre SQLite incompatibles')
            # Legacy bucket indexes exclude native entries at exactly their
            # terminal endpoint. The source contract preserves those IDs after
            # a scalar publication check; reuse them by PK at 24:00 only.
            closing_sql = (' UNION SELECT id FROM segments WHERE id IN (' +
                           ','.join(str(value) for value in closing_ids) + ')') if closing_ids else ''
            query = f'''SELECT s.journey,s.payload,j.metadata,s.vehicle,s.id,s.start,s.end FROM segments s
                JOIN journeys j ON j.key=s.journey
                WHERE s.id IN (SELECT segment FROM segment_blocks WHERE block IN ({placeholders}){closing_sql})
                AND s.start < ? AND (s.end > ? OR (s.end=s.start AND s.start>=?))
                ORDER BY s.id'''
            for key, raw, trip, vehicle, segment_id, native_start, native_end in execute(query, (*indexes, query_end, start, start)):
                if key not in trips:
                    if direct or getattr(self, 'spatial', None) is not None:
                        from simz1_recovery_io import _loads
                        native_trip = _loads(trip)
                        if not isinstance(native_trip, dict):
                            raise ValueError('Viaje SQLite sin metadatos finalizados')
                        self.validate_spatial_trip(native_trip)
                    trips[key] = trip
                if count:
                    output.write(b',')
                output.write(decompress(raw, segment=(key, vehicle, native_start, native_end), queue_seed_id=segment_id))
                count += 1
                vehicles.add(vehicle)
                if key not in edges:
                    edges[key] = [segment_id, segment_id]
                edges[key][1] = segment_id
            # Two indexed neighbours per journey, separate from active segments.
            # Read-only context crosses a window border without rebuilding plans
            # or fetching a complete journey for every visible vehicle.
            output.write(b'],"context_segments":[')
            context_lanes, context_count = {}, 0
            for key, (first, last) in edges.items():
                for operator, order, bound, lane_operator in (('<', 'DESC', first, '<'), ('>', 'ASC', last, '<=')):
                    row = lookup(f'''SELECT id,payload,vehicle,start,end FROM segments
                        WHERE journey=? AND id {operator} ? ORDER BY id {order} LIMIT 1''', (key, bound))
                    if row is None:
                        continue
                    context_id, raw, vehicle, context_start, context_end = row
                    if context_count:
                        output.write(b',')
                    # A moving interval can begin at a preceding FIFO hold.
                    # Reconstruct that immutable release anchor after a window
                    # change using the same bounded historical closure as an
                    # active hold. A future neighbour cannot seed past occupancy.
                    output.write(decompress(raw, segment=(key, vehicle, context_start, context_end),
                        queue_seed_id=context_id if operator == '<' else None))
                    context_count += 1
                    at = context_end if operator == '<' else context_start
                    event = lookup(f'''SELECT seq,time,payload FROM lane_events
                        WHERE vehicle=? AND time {lane_operator} ? ORDER BY time DESC,seq DESC LIMIT 1''', (vehicle, at))
                    if event:
                        context_lanes[event[0]] = event
            segments_done = time.perf_counter()
            output.write(b'],"trips":{')
            for number, (key, trip) in enumerate(trips.items()):
                if number:
                    output.write(b',')
                output.write(json_bytes(key))
                output.write(b':')
                output.write(trip.encode('utf-8'))
            output.write(b'},')
            del trips
            lanes = []
            # Preserve exactly the latest native predecessor for every vehicle
            # represented in this window, followed by its native transitions.
            predecessors = []
            for vehicle in sorted(vehicles):
                # Covering-index reads in vehicle order avoid alternating random
                # index and table pages for thousands of active vehicles.
                row = lookup('SELECT seq FROM lane_events WHERE vehicle=? AND time<? ORDER BY time DESC,seq DESC LIMIT 1', (vehicle, start))
                if row:
                    predecessors.append(row[0])
            predecessors.sort()
            for offset in range(0, len(predecessors), 500):
                batch = predecessors[offset:offset+500]
                parameters = ','.join('?' for _ in batch)
                lanes.extend(execute(f'SELECT seq,time,payload FROM lane_events WHERE seq IN ({parameters}) ORDER BY seq', batch))
            for seq, native_time, vehicle, raw in execute('SELECT seq,time,vehicle,payload FROM lane_events WHERE time>=? AND time<? ORDER BY time,seq', (start, query_end)):
                if vehicle in vehicles:
                    lanes.append((seq, native_time, raw))
            output.write(b'"context_lane_events":[')
            for number, (_, native_time, raw) in enumerate(sorted(context_lanes.values(), key=lambda row: (row[1], row[0]))):
                if number:
                    output.write(b',')
                output.write(decompress(raw, lane_time=native_time))
            output.write(b'],')
            lanes.sort(key=lambda row: (row[1], row[0]))
            output.write(b'"lane_replay":{"events":[')
            for number, (_, native_time, raw) in enumerate(lanes):
                if number:
                    output.write(b',')
                output.write(decompress(raw, lane_time=native_time))
            output.write(b'],"window":')
            output.write(json_bytes([start, end]))
            output.write(b'},')
            del lanes
            queue_context = None
            queue_context_started = time.perf_counter()
            if direct:
                checkpoint('queue_context', seeds_total=len(queue_seeds))
                queue_context = self.resolve_queue_context(connection, queue_seeds)
            profile['queue_context'] = time.perf_counter()-queue_context_started
        lanes_done = time.perf_counter()
        checkpoint('temporal_metadata')
        signals, incidents = self.temporal(indexes, start, query_end)
        signals['window'] = [start, end]
        metadata = {**self.response_identity, 'index': index, 'start_seconds': start, 'end_seconds': end,
            'signal_replay': signals, 'incidents': incidents, 'sample_rate': 1.0,
            'timings_seconds': {'segments': segments_done-started, 'lanes': lanes_done-segments_done,
                                'temporal': time.perf_counter()-lanes_done, **profile,
                                'assembly_and_metadata': max(0, lanes_done-started-sum(profile.values()))},
            'query_counters': counters, 'queue_context': queue_context}
        output.write(json_bytes(metadata)[1:])
        return output.getvalue()

    def journey(self, key):
        import re
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('Clave de viaje invalida')
        with closing(self.connection()) as connection:
            row = connection.execute('SELECT metadata FROM journeys WHERE key=?', (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            trip, records = json.loads(row[0]), []
            self.validate_spatial_trip(trip)
            rows = list(connection.execute('SELECT start,end,id,payload,vehicle FROM segments WHERE journey=?', (key,)))
            rows.sort(key=lambda row: row[:3])
            for start, end, _, raw, vehicle in rows:
                checkpoint('journey', records=len(records))
                if getattr(self, 'source_manifest', {}).get('source_type') == 'sqlite-direct-v1':
                    try:
                        record = self.validate_native_segment(zlib.decompress(raw), key, vehicle, start, end)
                    except zlib.error as exc:
                        raise ValueError('Registro comprimido SQLite corrupto') from exc
                else:
                    record = unpacked(raw)
                record['Trip'] = trip
                records.append(record)
            # Indexed reads for this journey only; preserve native equal-time
            # ordering and its immediate predecessor, as the window API does.
            bounds, lane_rows = {}, []
            for start, end, _, _, vehicle in rows:
                first, last = bounds.get(vehicle, (start, end))
                bounds[vehicle] = (min(first, start), max(last, end))
            for vehicle, (start, end) in bounds.items():
                predecessor = connection.execute('''SELECT seq,time,payload FROM lane_events
                    WHERE vehicle=? AND time<? ORDER BY time DESC,seq DESC LIMIT 1''', (vehicle, start)).fetchone()
                native_rows = ([predecessor] if predecessor else []) + list(connection.execute('''
                    SELECT seq,time,payload FROM lane_events WHERE vehicle=? AND time>=? AND time<?
                    ORDER BY time,seq''', (vehicle, start, end)))
                for seq, at, raw in native_rows:
                    try:
                        event = unpacked(raw)
                    except zlib.error as exc:
                        raise ValueError('Evento de carril comprimido corrupto') from exc
                    if (not isinstance(event, dict) or event.get('vehicle') != vehicle or event.get('time') != at or
                            type(event.get('time')) not in (int, float) or not math.isfinite(event['time']) or
                            event.get('type') not in ('entered lane', 'left lane',
                                                      'vehicle enters traffic', 'vehicle leaves traffic') or
                            (event.get('type') in ('entered lane', 'left lane') and
                             (not isinstance(event.get('link'), str) or not event['link'] or
                              not isinstance(event.get('lane'), str) or not event['lane']))):
                        raise ValueError('Evento de carril incompatible con el viaje')
                    lane_rows.append((at, seq, event))
            lane_rows.sort(key=lambda row: row[:2])
        return {**self.response_identity, 'key': key, 'trip': trip, 'records': records,
                'lane_replay': {'events': [row[2] for row in lane_rows]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Export paginado validado, con replay.sqlite')
    parser.add_argument('--output', type=Path, required=True, help='Carpeta nueva, por ejemplo webgl-continuo')
    parser.add_argument('--window-seconds', type=float, default=120)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--end', type=float, default=DAY_SECONDS, help='Fin absoluto visible; la politica validada determina el horizonte permitido')
    parser.add_argument('--resume-incomplete', action='store_true', help='Reutilizar solo evidencia temporal de esta misma identidad en una preparacion incompleta')
    parser.add_argument('--sqlite-direct', action='store_true', help='Preparar contrato SQLite sin completar ni copiar HTML historicos')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--iteration', type=int)
    parser.add_argument('--allow-native-side-scan', action='store_true', help='Recuperar solo senales/incidentes nativos si no hay cache verificada')
    parser.add_argument('--temp-dir', type=Path)
    parser.add_argument('--side-cache', type=Path)
    args = parser.parse_args()
    try:
        generate(args.source, args.output, window_seconds=args.window_seconds, start=args.start, end=args.end,
                 resume_incomplete=args.resume_incomplete, sqlite_direct=args.sqlite_direct,
                 run_dir=args.run_dir, iteration=args.iteration, allow_native_side_scan=args.allow_native_side_scan,
                 temp_dir=args.temp_dir, side_cache=args.side_cache)
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f'No se pudo preparar el visor continuo: {exc}\n')


if __name__ == '__main__':
    main()
