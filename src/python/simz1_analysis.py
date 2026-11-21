"""Official SimZ1 profile postprocessing, independent of MATSim's lifecycle.

Only validated, completed runs are eligible. Products are built in a staging
directory, fingerprinted and published with a recoverable journal. Neither a
failed analysis nor a retry edits the scientific run manifest or native output.
"""
from __future__ import annotations

from datetime import datetime, timezone
import errno
import csv
import hashlib
from importlib import metadata as package_metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid

from procesar_eventos_z1 import metadata_for_selection
from simz1_run import atomic_json, checked_path, select_run, sha256
from simz1_trip_distributions import plot_profile_analysis
from simz1_trip_table import DEFINITION, export_table, iteration_selection
from simz1_occupancy_audit import report_summary as occupancy_report_summary


SCHEMA_VERSION = 1
STATUS_NAME = 'analysis-status.json'
MANIFEST_NAME = 'analysis-manifest.json'
JOURNAL_NAME = '.analysis-publication.json'
MIN_FREE_BYTES = 64 * 1024 * 1024
REQUIRED_PROFILE_FILES = (
    'carros_por_hora.png', 'motos_por_hora.png',
    'comparacion_familias_por_hora.png', 'comparacion_global_perfiles.png',
    'completitud_por_hora.png', 'duration_distribution.png',
    'estadisticas_por_perfil_hora.csv', 'estadisticas_por_familia_hora.csv',
    'estadisticas_globales.csv', 'categorias_separadas.csv',
    'categorias_separadas_por_hora.csv', 'resumen_perfiles.json',
)
MANAGED_NAMES = ('trips.csv.gz', 'trips.csv.provenance.json',
                 'graficas_perfiles', MANIFEST_NAME)
CODE_FILES = (
    'simz1_analysis.py', 'simz1_trip_table.py', 'simz1_trip_audit.py',
    'simz1_trip_distributions.py', 'simz1_profile_plots.py', 'simz1_result_quality.py',
    'procesar_eventos_z1.py', 'simz1_agent_types.py', 'simz1_road_catalog.py',
    'simz1_temporal_metrics.py', 'simz1_occupancy_audit.py', 'simz1_demand_composition.py',
    'simz1_freight_completion.py', 'simz1_day_observation.py',
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _json_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


class AnalysisLock:
    """Nonblocking kernel lock; automatically released when the process dies.

    The lock file remains in place deliberately: deleting it would permit two
    processes to lock different inodes. A stale PID is never used as a lock.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        try:
            self.stream.seek(0, os.SEEK_END)
            if self.stream.tell() == 0:
                self.stream.write(b'\0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError as exc:
            self.stream.close()
            self.stream = None
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            try:
                if self.acquired:
                    self.stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None
                self.acquired = False


def _validate_selection(selection, min_sample):
    manifest = selection['manifest']
    if manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('El analisis requiere una corrida MATSim completed/valid')
    if selection['iteration'] not in manifest['iterations']['completed']:
        raise ValueError(f"Iteracion no completada: {selection['iteration']}")
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) or min_sample < 1:
        raise ValueError('--min-sample debe ser un entero positivo')


def _destination(selection, analysis_dir):
    run = Path(selection['directory']).resolve()
    root = Path(analysis_dir).resolve() if analysis_dir is not None else run / 'analysis'
    destination = (root / f"it.{selection['iteration']}").resolve()
    for native in ('output', 'inputs'):
        protected = (run / native).resolve()
        if destination.is_relative_to(protected):
            raise ValueError('El analisis no puede escribirse sobre output ni inputs de MATSim')
    return destination


def _sources(selection):
    """Only event-leg and identity inputs, never Motion_Plan or visual products."""
    manifest, iteration = selection['manifest'], selection['iteration']
    product = manifest.get('trip_products', {}).get(str(iteration), {})
    result = manifest.get('results', {}).get(str(iteration), {})
    if 'compact' in product:
        records = {name: product[name] for name in ('compact', 'summary')}
        kind = 'native_compact'
    elif 'events' in result:
        records = {name: result[name] for name in ('events', 'plans')}
        kind = 'events'
    else:
        raise ValueError(f'Iteracion {iteration} sin eventos ni tabla compacta validados')
    identity = result.get('plans', manifest.get('inputs', {}).get('plans'))
    if identity is None:
        raise ValueError('No hay planes identificados para los perfiles')
    records['identity_plans'] = identity
    if result.get('day_observation'):
        records['day_census'] = result['day_observation']['census']
    if result.get('corridor_occupancy', {}).get('enabled'):
        if 'events' not in result:
            raise ValueError('La ocupacion nativa requiere eventos validados de la misma iteracion')
        records['corridor_occupancy_events'] = result['events']
        if manifest.get('inputs', {}).get('transit_vehicles'):
            records['corridor_occupancy_public_bodies'] = manifest['inputs']['transit_vehicles']
    if manifest.get('temporal_policy'):
        if 'events' not in result:
            raise ValueError('Las metricas temporales requieren eventos nativos de la misma iteracion')
        records['temporal_events'] = result['events']
        public_schedule = manifest.get('inputs', {}).get('transit_schedule')
        if public_schedule is not None:
            records['temporal_public_schedule'] = public_schedule
    for name in ('effective_vehicles', 'effective_config'):
        if manifest.get(name):
            records[name] = manifest[name]
    # A caller of analyze_selection must get the same guarantees as select_run.
    unique = {}
    for record in records.values():
        unique[(record['path'], record['sha256'])] = record
    for record in unique.values():
        checked_path(Path(selection['directory']).resolve(), record)
    return kind, records


def _specification(selection, min_sample):
    kind, sources = _sources(selection)
    code_root = Path(__file__).resolve().parent
    versions = {}
    for name in ('numpy', 'matplotlib', 'Pillow'):
        try:
            versions[name] = package_metadata.version(name)
        except package_metadata.PackageNotFoundError:
            versions[name] = 'not-installed'
    manifest = selection['manifest']
    return dict(
        schema_version=SCHEMA_VERSION, run_id=manifest['run_id'],
        iteration=selection['iteration'], source_kind=kind, sources=sources,
        parameters=dict(min_sample=min_sample, departure_hours=list(range(24)),
                        modes='all recorded modes; identities from effective scenario types'),
        metric_definition=DEFINITION, time_horizon=manifest['time_horizon'],
        temporal_policy=manifest.get('temporal_policy'),
        day_observation=manifest.get('results', {}).get(str(selection['iteration']), {}).get('day_observation'),
        population_counts=manifest.get('counts', {}),
        demand_composition=manifest.get('demand_composition'),
        public_transport_configured=manifest.get('public_transport', {}),
        freight_transport_configured=manifest.get('freight_transport', {}),
        freight_transport_observed=manifest.get('results', {}).get(str(selection['iteration']), {}).get('freight_transport_events'),
        public_transport_observed=manifest.get('results', {}).get(str(selection['iteration']), {}).get('public_transport_events'),
        corridor_occupancy=occupancy_report_summary(manifest.get('results', {}).get(str(selection['iteration']), {}).get('corridor_occupancy')),
        implementation=dict(code_sha256={name: sha256(code_root / name) for name in CODE_FILES},
                            python=platform.python_version(), dependencies=versions),
    )


def preflight_space(destination, selection):
    """Conservative staging budget, including a canonical copy and bounded plots.

    Disk space can change after this check; every write is still covered by the
    ENOSPC handler. Existing scientific files are never deleted to free space.
    """
    destination = Path(destination)
    probe = destination
    while not probe.exists():
        if probe == probe.parent:
            raise OSError(f'No existe el volumen del analisis: {destination}')
        probe = probe.parent
    manifest, iteration = selection['manifest'], selection['iteration']
    product = manifest.get('trip_products', {}).get(str(iteration), {})
    record = product.get('compact') or manifest.get('results', {}).get(str(iteration), {}).get('events')
    source_size = (Path(selection['directory']) / record['path']).stat().st_size if record else 0
    existing = destination / 'trips.csv.gz'
    table_size = existing.stat().st_size if existing.is_file() else 0
    required = MIN_FREE_BYTES + max(2 * source_size, 2 * table_size)
    free = shutil.disk_usage(probe).free
    if free < required:
        raise OSError(errno.ENOSPC,
                      f'Espacio insuficiente para analisis en {probe}: '
                      f'disponibles {free:,} bytes; reserva estimada {required:,} bytes. '
                      'Los resultados cientificos y analiticos anteriores se conservan.')
    return dict(free_bytes=free, estimated_required_bytes=required)


def _artifact_records(stage):
    paths = [stage / 'trips.csv.gz', stage / 'trips.csv.provenance.json']
    paths.extend(stage / 'graficas_perfiles' / name for name in REQUIRED_PROFILE_FILES)
    for path in paths:
        if not path.is_file():
            raise ValueError(f'Producto analitico incompleto: falta {path.name}')
    # Include any additional analytical CSV/JSON/PNG emitted by the renderer.
    paths = sorted(set(paths) | {p for p in (stage / 'graficas_perfiles').rglob('*') if p.is_file()})
    return [dict(path=p.relative_to(stage).as_posix(), size_bytes=p.stat().st_size,
                 sha256=sha256(p)) for p in paths]


def _valid_manifest(destination, fingerprint):
    path = destination / MANIFEST_NAME
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
        if (report.get('schema_version') != SCHEMA_VERSION or report.get('status') != 'completed'
                or report.get('fingerprint') != fingerprint
                or _json_digest(report['specification']) != fingerprint
                or report['run_id'] != report['specification']['run_id']
                or report['iteration'] != report['specification']['iteration']):
            return None
        required = {'trips.csv.gz', 'trips.csv.provenance.json'} | {
            'graficas_perfiles/' + name for name in REQUIRED_PROFILE_FILES}
        records = report['artifacts']
        if not required.issubset({item['path'] for item in records}):
            return None
        for item in records:
            product = (destination / item['path']).resolve()
            if (not product.is_relative_to(destination) or not product.is_file()
                    or product.stat().st_size != item['size_bytes'] or sha256(product) != item['sha256']):
                return None
        status_path = destination / STATUS_NAME
        if status_path.is_file():
            try:
                status = json.loads(status_path.read_text(encoding='utf-8'))
            except ValueError:
                status = {}
            if not isinstance(status, dict):
                status = {}
            recorded_hash = status.get('manifest_sha256')
            if (status.get('status') == 'completed' and status.get('fingerprint') == fingerprint
                    and recorded_hash and recorded_hash != sha256(path)):
                return None
        return report
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _transaction_path(destination, value):
    path = (destination / value).resolve()
    if not path.is_relative_to(destination) or path == destination:
        raise ValueError('Journal analitico fuera de la carpeta de la iteracion')
    return path


def _recover_publication(destination):
    """Rollback a publication interrupted at any rename; preserve both versions."""
    journal_path = destination / JOURNAL_NAME
    if not journal_path.is_file():
        return None
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    if journal.get('names') != list(MANAGED_NAMES):
        raise ValueError('Journal analitico incompatible; no se modifica ningun producto')
    stage = _transaction_path(destination, journal['stage'])
    archive = _transaction_path(destination, journal['archive'])
    abandoned = _transaction_path(destination, journal['abandoned'])
    previous = set(journal['previous'])
    if not previous.issubset(MANAGED_NAMES):
        raise ValueError('Journal analitico con productos desconocidos')
    for name in reversed(MANAGED_NAMES):
        target, saved, staged = destination / name, archive / name, stage / name
        # New product is visible only after its staged name has been moved.
        new_visible = target.exists() and not staged.exists() and (name not in previous or saved.exists())
        if new_visible:
            abandoned.mkdir(parents=True, exist_ok=True)
            if (abandoned / name).exists():
                raise ValueError('Recuperacion analitica ambigua; se conservan ambas versiones')
            target.replace(abandoned / name)
        if saved.exists():
            if target.exists():
                raise ValueError('Recuperacion analitica no puede sobrescribir un producto existente')
            saved.replace(target)
    journal_path.unlink()
    return journal['transaction_id']



def validate_windows_paths(destination, transaction_id, *, windows=None):
    """Fail before copying events if PNG, staged or revision paths will be too long.

    Windows Python/matplotlib deployments can still reject paths longer than
    259 characters even when the OS has long-path support. Reserve headroom
    for temporary file names and preserve the user's original run directory.
    """
    if windows is None:
        windows = os.name == 'nt'
    if not windows:
        return
    destination = Path(destination).resolve()
    suffixes = tuple(Path('graficas_perfiles') / name for name in REQUIRED_PROFILE_FILES)
    for prefix in ('.stg', '.rev', '.abn'):
        for suffix in suffixes:
            candidate = destination / prefix / transaction_id / suffix
            if len(str(candidate)) >= 248:
                raise OSError(errno.ENAMETOOLONG,
                              f'Ruta temporal demasiado larga ({len(str(candidate))} caracteres): {candidate}. '
                              'Use --analysis-dir con una ruta corta en una unidad existente y escribible.')


def _publish(stage, destination, transaction_id):
    # Keep the staging/journal transaction below Windows MAX_PATH. The former
    # .analysis-staging/YYYYMMDD-UUID scheme produced 261-character figure
    # filenames in ordinary SimZ1 run folders (ENAMETOOLONG on Windows).
    archive = destination / '.rev' / transaction_id
    abandoned = destination / '.abn' / transaction_id
    journal = dict(transaction_id=transaction_id, names=list(MANAGED_NAMES),
                   previous=[name for name in MANAGED_NAMES if (destination / name).exists()],
                   stage=stage.relative_to(destination).as_posix(),
                   archive=archive.relative_to(destination).as_posix(),
                   abandoned=f'.abn/{transaction_id}')
    atomic_json(destination / JOURNAL_NAME, journal)
    if journal['previous']:
        archive.mkdir(parents=True, exist_ok=True)
    # Reserve recovery directories before the first mutation. A disk-full
    # failure during publication must not need new directories for rollback.
    abandoned.mkdir(parents=True, exist_ok=True)
    for name in MANAGED_NAMES:
        target = destination / name
        if name in journal['previous']:
            target.replace(archive / name)
        (stage / name).replace(target)
    # No old product is removed: revisions remain available for inspection.
    (destination / JOURNAL_NAME).unlink()
    try:
        stage.rmdir()
    except OSError:
        pass
    try:
        abandoned.rmdir()
    except OSError:
        pass
    return archive if journal['previous'] else None


def _status(destination, value):
    """Status writes are advisory: disk-full must not hide the original error."""
    try:
        atomic_json(destination / STATUS_NAME, value)
        return None
    except OSError as exc:
        return f'No se pudo registrar {STATUS_NAME}: {exc}'


def _status_generation(destination):
    """Identify a status writer without relying on PID reuse or clock precision."""
    try:
        data = (destination / STATUS_NAME).read_bytes()
    except FileNotFoundError:
        return None, None
    try:
        attempt = json.loads(data).get('attempt_id')
    except (ValueError, AttributeError):
        attempt = None
    return hashlib.sha256(data).hexdigest(), attempt


def analyze_selection(selection, *, analysis_dir=None, min_sample=30):
    """Analyze one completed iteration; return status without changing MATSim.

    Invalid run selections raise ValueError before writing anything. Operational
    failures return analysis_failed, including KeyboardInterrupt. A concurrent
    process returns analysis_running and does not touch the owner's status.
    """
    _validate_selection(selection, min_sample)
    destination = _destination(selection, analysis_dir)
    manifest = selection['manifest']
    base = dict(run_id=manifest['run_id'], iteration=selection['iteration'],
                directory=str(destination), matsim_status='completed', matsim_validation='valid')
    started = utc_now()
    attempt_id = uuid.uuid4().hex
    prior_status_version = None
    specification = None
    stage = None
    lock_path = destination.parent / f'.it.{selection["iteration"]}.analysis.lock'
    lock = AnalysisLock(lock_path)
    try:
        with lock:
            if not lock.acquired:
                return dict(base, status='analysis_running', reused=False,
                            error='Otro proceso tiene el bloqueo de analisis para esta iteracion')
            prior_status_version, _ = _status_generation(destination)
            recovered = _recover_publication(destination)
            specification = _specification(selection, min_sample)
            fingerprint = _json_digest(specification)
            previous = _valid_manifest(destination, fingerprint)
            if previous is not None:
                result = dict(base, status='completed', reused=True,
                              generated_utc=previous['generated_utc'],
                              manifest=str(destination / MANIFEST_NAME), fingerprint=fingerprint,
                              manifest_sha256=sha256(destination / MANIFEST_NAME),
                              sources=specification['sources'])
                try:
                    current_status = json.loads((destination / STATUS_NAME).read_text(encoding='utf-8'))
                except (FileNotFoundError, ValueError):
                    current_status = {}
                if not isinstance(current_status, dict):
                    current_status = {}
                if any(current_status.get(key) != result[key] for key in
                       ('status', 'run_id', 'iteration', 'fingerprint', 'manifest_sha256')):
                    warning = _status(destination, dict(result, attempt_id=attempt_id,
                                                        updated_utc=utc_now(), recovered_status=True))
                    if warning:
                        result['status_warning'] = warning
                        print(warning, file=sys.stderr)
                return result
            space = preflight_space(destination, selection)
            destination.mkdir(parents=True, exist_ok=True)
            # A short, collision-resistant transaction ID keeps all of the
            # five PNG and CSV paths inside Windows' legacy MAX_PATH limit.
            # Keep science artifacts and interrupted previous stages untouched.
            transaction_id = uuid.uuid4().hex[:16]
            stage = destination / '.stg' / transaction_id
            validate_windows_paths(destination, transaction_id)
            stage.mkdir(parents=True, exist_ok=False)
            _status(destination, dict(base, status='analysis_running', started_utc=started,
                                      attempt_id=attempt_id,
                                      updated_utc=utc_now(), pid=os.getpid(), sources=specification['sources'],
                                      fingerprint=fingerprint, staging_directory=str(stage),
                                      recovered_transaction=recovered))
            table, provenance = export_table(selection, stage / 'trips.csv.gz')
            metadata, identity_source = metadata_for_selection(selection)
            report = plot_profile_analysis(
                table, stage / 'graficas_perfiles', manifest['run_id'], selection['iteration'],
                metadata, min_sample=min_sample,
                **({'temporal_policy': manifest['temporal_policy']} if manifest.get('temporal_policy') else {}),
                provenance=dict(table=provenance, identities=identity_source,
                    source_run_directory=str(Path(selection['directory']).resolve()),
                    selection_warning=selection.get('selection_warning'),
                    population_counts=manifest.get('counts', {}),
                    demand_composition=manifest.get('demand_composition'),
                    public_transport_configured=manifest.get('public_transport', {}),
                    freight_transport_configured=manifest.get('freight_transport', {}),
                    freight_transport_observed=specification['freight_transport_observed'],
                    public_transport_observed=specification['public_transport_observed'],
                    day_observation=specification['day_observation'],
                    internal_drivers='Public fleet/internal drivers are outside N. Freight belongs to non-public N only when demand_composition declares it; private profile statistics keep their private denominator. Absent observations are not zero.'))
            composition = manifest.get('demand_composition')
            if composition is not None:
                atomic_json(stage/'graficas_perfiles/composicion_demanda.json', dict(
                    run_id=manifest['run_id'], iteration=selection['iteration'],
                    demand_composition=composition, counts=manifest['counts'],
                    counting_basis='configured vehicles; not simultaneous occupancy nor completed trips'))
                with (stage/'graficas_perfiles/composicion_demanda.csv').open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['family', 'configured_vehicles', 'included_in_N', 'target_fraction'])
                    for family, amount in composition['family_counts'].items():
                        writer.writerow([family, amount, True, composition['family_fractions'][family]])
                    writer.writerow(['publico', manifest['counts']['public_transport_vehicles_configured'], False, ''])
            temporal_metrics = None
            if (specification.get('corridor_occupancy') or {}).get('enabled'):
                atomic_json(stage/'graficas_perfiles/corridor_occupancy.json', dict(
                    run_id=manifest['run_id'], iteration=selection['iteration'],
                    corridor_occupancy=specification['corridor_occupancy']))
            if manifest.get('freight_transport', {}).get('enabled'):
                freight_observed = specification['freight_transport_observed']
                durations = freight_observed['completed_duration_seconds']
                atomic_json(stage/'graficas_perfiles/freight_service.json', dict(
                    run_id=manifest['run_id'], iteration=selection['iteration'],
                    configured=manifest['freight_transport'], observed=freight_observed,
                    mean_duration_seconds=sum(durations)/len(durations) if durations else None,
                    duration_scope='Native boundary-to-boundary expedition, including queues; excludes exterior travel',
                    private_demand_denominator_unchanged=True, empirical_calibration=False))
            if manifest.get('temporal_policy'):
                from simz1_temporal_metrics import analyze_temporal, scheduled_public_departures
                public_schedule = specification['sources'].get('temporal_public_schedule')
                public_departures = (scheduled_public_departures(checked_path(
                    Path(selection['directory']).resolve(), public_schedule))
                    if public_schedule is not None else None)
                temporal_metrics = analyze_temporal(
                    Path(selection['directory']) / specification['sources']['temporal_events']['path'],
                    table, metadata, manifest['temporal_policy'], stage / 'graficas_perfiles',
                    manifest['run_id'], selection['iteration'], public_schedule=public_departures)
            # Detect a source or implementation changed while the plots were built.
            if _json_digest(_specification(selection, min_sample)) != fingerprint:
                raise ValueError('Las fuentes o el codigo cambiaron durante el analisis; no se publica')
            generated = utc_now()
            products = dict(schema_version=SCHEMA_VERSION, status='completed',
                run_id=manifest['run_id'], iteration=selection['iteration'],
                generated_utc=generated, started_utc=started, fingerprint=fingerprint,
                specification=specification, sources=specification['sources'],
                artifacts=_artifact_records(stage), counts=report.get('counts', {}),
                result_quality=report.get('result_quality', {}),
                temporal_conservation=temporal_metrics.get('conservation') if temporal_metrics else None,
                distribution=report.get('distribution', {}), disk_preflight=space)
            atomic_json(stage / MANIFEST_NAME, products)
            archive = _publish(stage, destination, transaction_id)
            result = dict(base, status='completed', reused=False, generated_utc=generated,
                          attempt_id=attempt_id,
                          started_utc=started, updated_utc=utc_now(), fingerprint=fingerprint,
                          sources=specification['sources'], manifest=str(destination / MANIFEST_NAME),
                          manifest_sha256=sha256(destination / MANIFEST_NAME),
                          previous_revision=str(archive) if archive else None)
            warning = _status(destination, result)
            if warning:
                result['status_warning'] = warning
                print(warning, file=sys.stderr)
            return result
    except (Exception, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        full = isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or getattr(exc, 'winerror', None) == 112)
        message = ('Analisis interrumpido; puede reintentarse.' if interrupted else
                   'Espacio insuficiente para el analisis; resultados cientificos conservados. ' + str(exc)
                   if full else str(exc))
        result = dict(base, status='analysis_failed', reused=False, started_utc=started,
                      attempt_id=attempt_id,
                      updated_utc=utc_now(), error=message, error_type=type(exc).__name__,
                      interrupted=interrupted, disk_full=full,
                      staging_directory=str(stage) if stage is not None else None)
        if specification is not None:
            result['sources'] = specification['sources']
            result['fingerprint'] = _json_digest(specification)
        # Reacquire after the context released its lock; do not overwrite a retry
        # that has already started in another process.
        try:
            with AnalysisLock(lock_path) as recovery_lock:
                if recovery_lock.acquired:
                    current_version, current_attempt = _status_generation(destination)
                    if current_version == prior_status_version or current_attempt == attempt_id:
                        try:
                            _recover_publication(destination)
                        except (OSError, ValueError, KeyError) as recovery_error:
                            result['recovery_error'] = str(recovery_error)
                        warning = _status(destination, result)
                        if warning:
                            result['status_warning'] = warning
                    else:
                        result['status_warning'] = 'Otro intento actualizo el analisis; se conserva su estado.'
        except OSError as lock_error:
            result['status_warning'] = f'No se pudo registrar el fallo del analisis: {lock_error}'
        print(f"analysis_failed | {base['run_id']} | it.{base['iteration']} | {message}", file=sys.stderr)
        if result.get('status_warning'):
            print(result['status_warning'], file=sys.stderr)
        return result


def analyze_run(run_dir=None, iteration=None, *, all_iterations=False,
                analysis_dir=None, min_sample=30, latest_path=None):
    """Select the validated run once, then analyze the requested iteration(s)."""
    if all_iterations and iteration is not None:
        raise ValueError('--all-iterations no se combina con --iteration')
    selection = select_run(run_dir, iteration, latest_path=latest_path, require_events=False)
    iterations = sorted(selection['manifest']['iterations']['completed']) if all_iterations else [selection['iteration']]
    results = []
    for number in iterations:
        chosen = selection if number == selection['iteration'] else iteration_selection(selection, number)
        result = analyze_selection(chosen, analysis_dir=analysis_dir, min_sample=min_sample)
        results.append(result)
        if result.get('interrupted'):
            break
    return dict(status='completed' if all(r['status'] == 'completed' for r in results) else 'analysis_failed',
                run_id=selection['manifest']['run_id'], directory=str(selection['directory']), iterations=results)
