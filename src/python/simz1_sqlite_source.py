"""Validated, unsampled SQLite sources for SimZ1 continuous playback.

``sqlite-direct-v1`` is independent of ``export-manifest.json``. Its ``blocks``
describe the existing segment_blocks index, NOT HTML files. Publication checks
the complete SQLite structure (quick_check) and hashes every database byte once;
it never extracts events or recomputes Motion_Plan. A legacy source additionally
needs one complete HTML anchor emitted after spool.finalize(), and complete,
provenance-bound signal/incident evidence. Runtime reads check immutable file
identity and the small hashed metadata; individual windows still validate their
payloads. No claim of a complete paged export is made.
"""
from contextlib import closing
from copy import deepcopy
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from simz1_paged_replay import unpacked, windows
from simz1_recovery_io import atomic_json_preserve, inspect_block, preflight_storage, _json_bytes
from simz1_run import sha256

SOURCE_TYPE = 'sqlite-direct-v1'
FILE_NAME = 'sqlite-source-manifest.json'
IDENTITY_KEYS = ('run_id', 'iteration', 'run_manifest_sha256')
MAX_METADATA_BYTES = 128 * 1024 * 1024
DEFAULT_RESERVE_BYTES = 64 * 1024 * 1024
INDEX_COLUMNS = {'segments_journey': ('journey', 'id'),
                 'segments_block': ('block', 'segment'),
                 'lanes_vehicle_time': ('vehicle', 'time', 'seq'),
                 'lanes_time': ('time', 'seq')}
TABLE_COLUMNS = {'segments': ('id', 'journey', 'vehicle', 'start', 'end', 'payload'),
                 'segment_blocks': ('block', 'segment'), 'journeys': ('key', 'metadata'),
                 'lane_events': ('seq', 'vehicle', 'time', 'payload'),
                 'export_identity': ('key', 'value')}


def identity(record):
    return {key: record[key] for key in IDENTITY_KEYS}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def file_identity(path):
    value = Path(path).stat()
    return dict(bytes=value.st_size, mtime_ns=value.st_mtime_ns)


def _native_run(run_dir, iteration=None, expected=None):
    directory = Path(run_dir).resolve(strict=True)
    raw = (directory / 'run-manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('SQLite directo requiere corrida completed/valid')
    if iteration is None:
        results = list(manifest.get('results', {}))
        if len(results) != 1:
            raise ValueError('Seleccione explicitamente la iteracion de la fuente SQLite')
        iteration = int(results[0])
    if str(iteration) not in manifest.get('results', {}):
        raise ValueError('Iteracion SQLite ausente del manifiesto nativo')
    actual = dict(run_id=manifest['run_id'], iteration=iteration,
                  run_manifest_sha256=hashlib.sha256(raw).hexdigest())
    if expected is not None and actual != expected:
        raise ValueError('Identidad de corrida/iteracion/hash incompatible con SQLite directo')
    return directory, manifest, actual


def _closed_database(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('SQLite debe ser un archivo regular existente')
    for suffix in ('-wal', '-shm', '-journal'):
        companion = path.with_name(path.name + suffix)
        if companion.exists() and companion.stat().st_size:
            raise ValueError(f'SQLite no cerrado: {companion}; no se elimina ni recupera automaticamente')
    with path.open('rb') as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b'SQLite format 3\0':
        raise ValueError('Cabecera SQLite corrupta o truncada')
    page_size = int.from_bytes(header[16:18], 'big')
    page_size = 65536 if page_size == 1 else page_size
    pages = int.from_bytes(header[28:32], 'big')
    if page_size < 512 or page_size & (page_size - 1) or not pages or pages * page_size != path.stat().st_size:
        raise ValueError('SQLite truncado o longitud de paginas incompatible')
    return path


def readonly_database(path, expected):
    path = _closed_database(path)
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA temp_store=MEMORY')
        connection.execute('PRAGMA cache_size=-32768')
        actual = dict(connection.execute('SELECT key,value FROM export_identity'))
        if actual != {key: str(expected[key]) for key in IDENTITY_KEYS}:
            raise ValueError('Identidad SQLite de otra corrida, iteracion o manifiesto')
        for table, columns in TABLE_COLUMNS.items():
            observed = tuple(row[1] for row in connection.execute(f'PRAGMA table_info({table})'))
            if observed != columns:
                raise ValueError(f'Esquema SQLite incompatible: {table}')
        for name, columns in INDEX_COLUMNS.items():
            observed = tuple(row[2] for row in connection.execute(f'PRAGMA index_info({name})'))
            if observed != columns:
                raise ValueError(f'Indice SQLite ausente/incompatible: {name}')
        return connection
    except BaseException:
        connection.close()
        raise


def _blocks(blocks):
    if not blocks:
        raise ValueError('Falta el contrato temporal del indice SQLite')
    cleaned = [{key: block[key] for key in ('index', 'start_seconds', 'end_seconds', 'url')}
               for block in blocks]
    seconds = cleaned[0]['end_seconds'] - cleaned[0]['start_seconds']
    if cleaned != windows(cleaned[0]['start_seconds'], cleaned[-1]['end_seconds'], seconds):
        raise ValueError('Contrato temporal SQLite incompleto o irregular')
    return cleaned


def _validate_memberships(connection, blocks):
    """Prove exact temporal membership with scalar/index reads, no BLOB decode.

    Every membership must be valid and unique. Equality of its total to the
    exact expected interval-overlap total then rules out missing memberships.
    Integer casts implement floor/ceil without optional SQLite math extensions.
    """
    origin, end = blocks[0]['start_seconds'], blocks[-1]['end_seconds']
    duration = float(blocks[0]['end_seconds'] - origin)
    if connection.execute('SELECT 1 FROM segments WHERE start IS NULL OR end IS NULL OR '
            'start<0 OR end<start OR abs(start)>1e308 OR abs(end)>1e308 LIMIT 1').fetchone():
        raise ValueError('Intervalos escalares SQLite invalidos')
    if connection.execute('SELECT 1 FROM segment_blocks INDEXED BY segments_block '
            'GROUP BY block,segment HAVING count(*)<>1 LIMIT 1').fetchone():
        raise ValueError('Indice temporal SQLite contiene pertenencias duplicadas')
    if connection.execute('SELECT 1 FROM segment_blocks b INDEXED BY segments_block '
            'JOIN segments s ON s.id=b.segment '
            'WHERE s.start>=min(?,?+(b.block+1)*?) OR '
            '(s.end<=?+b.block*? AND NOT(s.end=s.start AND s.start>=?+b.block*?)) LIMIT 1',
            (end, origin, duration, origin, duration, origin, duration)).fetchone():
        raise ValueError('Indice temporal SQLite contiene una pertenencia fuera de su ventana')
    expected = connection.execute('''WITH ratios AS (
            SELECT start,end,(start-?)/? AS a,(end-?)/? AS z FROM segments),
        bounds AS (SELECT max(0,CAST(a AS INTEGER)-(a<CAST(a AS INTEGER))) AS lo,
            min(?,CASE WHEN end>start THEN CAST(z AS INTEGER)+(z>CAST(z AS INTEGER))-1
                     ELSE CAST(z AS INTEGER)-(z<CAST(z AS INTEGER)) END) AS hi FROM ratios)
        SELECT coalesce(sum(max(0,hi-lo+1)),0) FROM bounds''',
        (origin, duration, origin, duration, len(blocks)-1)).fetchone()[0]
    actual = connection.execute('SELECT count(*) FROM segment_blocks').fetchone()[0]
    if expected != actual:
        raise ValueError('Indice temporal SQLite incompleto: faltan pertenencias de segmentos')
    return actual


def validate_database(database, expected, counts, blocks, *, full=True, closing_seconds=86400):
    """Full publication validation; never reruns movement reconstruction.

    quick_check and SHA256 are sequential read-only I/O, with a 32 MiB SQLite
    cache and RAM temporary storage. They run only on explicit publication,
    never when opening a viewer or serving a window.
    """
    database = _closed_database(database)
    before = file_identity(database)
    with closing(readonly_database(database, expected)) as connection:
        if full:
            print(f'SQLite directo: quick_check de {before["bytes"]:,} bytes; solo lectura, '
                  'sin recalcular Motion_Plan', flush=True)
            check = connection.execute('PRAGMA quick_check(1)').fetchone()
            if check != ('ok',):
                raise ValueError(f'Integridad SQLite invalida: {check}')
            total = connection.execute('SELECT count(*) FROM segments').fetchone()[0]
            if total != counts.get('segments'):
                raise ValueError('Cantidad de segmentos SQLite incompatible con el spool finalizado')
            if connection.execute('SELECT key FROM journeys WHERE metadata IS NULL LIMIT 1').fetchone():
                raise ValueError('SQLite contiene viajes sin metadatos finalizados')
            if connection.execute('SELECT 1 FROM segments s INDEXED BY segments_journey '
                    'LEFT JOIN journeys j ON j.key=s.journey WHERE j.key IS NULL LIMIT 1').fetchone():
                raise ValueError('SQLite contiene segmentos con referencias a viajes ausentes')
            if connection.execute('SELECT 1 FROM segment_blocks b INDEXED BY segments_block '
                    'LEFT JOIN segments s ON s.id=b.segment WHERE s.id IS NULL LIMIT 1').fetchone():
                raise ValueError('Indice temporal SQLite contiene referencias a segmentos ausentes')
        else:
            total = counts['segments']
        maximum = connection.execute('SELECT max(id) FROM segments').fetchone()[0]
        minimum = connection.execute('SELECT min(id) FROM segments').fetchone()[0]
        if (total and (minimum != 1 or maximum != total)) or (not total and maximum is not None):
            raise ValueError('Secuencia de segmentos SQLite incompleta')
        last = connection.execute('SELECT block FROM segment_blocks ORDER BY block DESC LIMIT 1').fetchone()
        first = connection.execute('SELECT block FROM segment_blocks ORDER BY block LIMIT 1').fetchone()
        if (last and last[0] >= len(blocks)) or (first and first[0] < 0):
            raise ValueError('Indice SQLite fuera del contrato temporal')
        if full:
            print('SQLite directo: verificando referencias e integridad del indice temporal '
                  '(columnas escalares, sin decodificar trayectorias completas)', flush=True)
        occurrences = _validate_memberships(connection, blocks) if full else None
        # Index probes sample the beginning/end of every temporal bucket. They
        # do not parse millions of BLOBs or create a second trajectory store.
        samples = set()
        for block in blocks:
            for direction in ('ASC', 'DESC'):
                row = connection.execute('SELECT segment FROM segment_blocks WHERE block=? '
                    f'ORDER BY segment {direction} LIMIT 1', (block['index'],)).fetchone()
                if row:
                    samples.add(row[0])
        # Legacy exclusive block indexes omit evidence starting exactly at the
        # configured closing tick. Read scalar columns once during publication, then
        # runtime can retrieve only these preserved original records by PK.
        closing_ids = ([row[0] for row in connection.execute('SELECT id FROM segments WHERE start=?', (closing_seconds,))]
                       if full and blocks[-1]['end_seconds'] >= closing_seconds else [])
        samples.update(closing_ids)
        for ident in samples:
            row = connection.execute('SELECT s.journey,s.vehicle,s.start,s.end,s.payload,j.metadata '
                'FROM segments s LEFT JOIN journeys j ON j.key=s.journey WHERE s.id=?', (ident,)).fetchone()
            if row is None or row[5] is None:
                raise ValueError('Segmento SQLite sin viaje finalizado')
            record, trip = unpacked(row[4]), json.loads(row[5])
            if (record.get('Replay_Journey_Key') != row[0] or record.get('vehicle') != row[1] or
                    record.get('timestamps') != list(row[2:4]) or
                    not isinstance(record.get('Motion_Plan'), dict) or not isinstance(trip, dict)):
                raise ValueError('Payload SQLite sin identidad/Motion_Plan/metadatos finalizados')
    if full:
        print('SQLite directo: SHA256 secuencial de la base original; sin copiarla', flush=True)
    digest = sha256(database) if full else None
    if file_identity(database) != before:
        raise ValueError('SQLite cambio durante la validacion; no se publica fuente')
    return dict(**before, sha256=digest, integrity='quick_check+sha256' if full else 'identity+structure',
                sampled_segments=len(samples), segments=total, closing_segment_ids=closing_ids,
                block_memberships=occurrences)


def _validate_side(data, config, native_result):
    from simz1_recovery_native import _validate_payload
    from simz1_signal_replay import STATES
    _validate_payload(data, config, native_result)
    signal = data['signal_replay']
    total, seen, state_counts = 0, set(), Counter()
    for group in signal['series']:
        key = (group['system_id'], group['group_id'])
        if key in seen:
            raise ValueError('Series semaforicas duplicadas')
        seen.add(key)
        previous = -math.inf
        for stamp, state in group['states']:
            if not math.isfinite(stamp) or stamp < previous or state not in STATES:
                raise ValueError('Serie semaforica invalida o incompleta')
            previous = stamp
            total += 1
            state_counts[state] += 1
    if total != signal.get('event_count'):
        raise ValueError('Cobertura semaforica incompleta: faltan estados del total nativo')
    if 'state_counts' in signal and dict(state_counts) != signal['state_counts']:
        raise ValueError('Conteos de estados semaforicos incompatibles')
    if 'groups' in signal and signal['groups'] != len(seen):
        raise ValueError('Conteos de grupos semaforicos incompatibles')
    reference = config.get('signal_replay', {}).get('series')
    if reference is not None and [{key: value for key, value in group.items() if key != 'states'}
            for group in signal['series']] != [{key: value for key, value in group.items() if key != 'states'}
                                             for group in reference]:
        raise ValueError('Identidad de grupos semaforicos incompatible')
    for incident in data['incidents']:
        if (not math.isfinite(incident['start']) or incident['start'] < 0 or
                (incident['end'] is not None and
                 (not math.isfinite(incident['end']) or incident['end'] < incident['start']))):
            raise ValueError('Cronologia nativa de incidentes invalida')


def _load_cache(path, run, expected, config):
    from simz1_recovery_native import _signature
    if Path(path).stat().st_size > MAX_METADATA_BYTES:
        raise ValueError('Cache nativa excede el limite de metadatos; no se carga sin limite')
    envelope = json.loads(Path(path).read_text(encoding='utf-8'))
    content = envelope['content']
    result = run['results'][str(expected['iteration'])]
    wanted = dict(identity=expected, configuration_sha256=_signature(config)[0],
        sources=dict(events=result['events'], network=result['network'],
                     effective_config=run['effective_config'], inputs=run['inputs']))
    if (envelope.get('schema_version') != 1 or envelope.get('sha256') != _signature(content)[0]
            or content.get('provenance') != wanted):
        raise ValueError('Cache nativa de otra corrida/configuracion o hash invalido')
    _validate_side(content['data'], config, result)
    return content['data']


def _write_metadata(path, value, reserve_bytes):
    raw = encoded(value)
    if len(_json_bytes(value)) + 1 > MAX_METADATA_BYTES:
        raise ValueError('Metadatos SQLite exceden el limite de 128 MiB')
    if path.exists():
        if path.stat().st_size > MAX_METADATA_BYTES:
            raise ValueError('Metadatos pendientes exceden el limite de 128 MiB')
        if encoded(json.loads(path.read_bytes())) != raw:
            raise ValueError(f'Metadatos pendientes incompatibles; se conservan: {path}')
    else:
        # Preserve helper owns atomic publication and leaves failed stages.
        atomic_json_preserve(path, value, reserve_bytes=reserve_bytes, overwrite=False)
        # atomic_json_preserve uses different deterministic JSON whitespace;
        # its exact bytes, not the in-memory encoding, define this contract.
    return dict(file=path.name, sha256=sha256(path), bytes=path.stat().st_size)


def publish_source(run_dir, database, output, config, side_data, blocks, counts, *,
                   iteration=None, provenance=None, reserve_bytes=DEFAULT_RESERVE_BYTES):
    """Publish a complete direct contract from an already finalized spool.

    The caller supplies complete native side-data, never a window excerpt.
    Source files are external references; output contains only small metadata.
    Interrupted identical metadata is reusable; the manifest is written last.
    """
    started = time.perf_counter()
    output = Path(output).resolve()
    preflight_storage(output, 1024 * 1024, reserve_bytes, probe_write=True)
    directory, run, expected = _native_run(run_dir, iteration)
    database = Path(database).resolve(strict=True)
    blocks = _blocks(blocks)
    result = run['results'][str(expected['iteration'])]
    config = deepcopy(config)
    from simz1_recover_paged import check_config, small_config
    check_config(config, expected, run, blocks)
    if counts != config.get('trajectory_stats') or counts.get('segments') != config['pagination']['total_segments']:
        raise ValueError('Resumen de trayectorias incompatible con el spool')
    if counts.get('reconstructed_vehicles') != config['pagination']['total_reconstructed_vehicles']:
        raise ValueError('Cantidad de vehiculos incompatible con el spool')
    _validate_side(side_data, config, result)
    fixed = small_config(config)
    side = dict(**expected, coverage='complete-native-event-stream',
                replay_window=dict(start_seconds=blocks[0]['start_seconds'],
                                   end_seconds=blocks[-1]['end_seconds']), data=side_data)
    config_size, side_size = len(_json_bytes(fixed)) + 1, len(_json_bytes(side)) + 1
    required = config_size + side_size + 64 * 1024
    if required > MAX_METADATA_BYTES * 2:
        raise ValueError('Metadatos directos demasiado grandes')
    preflight_storage(output, required * 2, reserve_bytes, probe_write=True,
                      largest_file_bytes=max(config_size, side_size))
    if (output / FILE_NAME).exists():
        _, previous, _ = checked_source(output)
        if (identity(previous) != expected or Path(previous['database']) != database or
                previous['blocks'] != blocks or previous['counts'] != counts or
                load_config(output, previous) != fixed or load_side_data(output, previous) != side_data):
            raise ValueError('El destino contiene otra fuente SQLite')
        return previous
    closing_seconds = (run['temporal_policy']['windows']['simulation']['end_seconds']
                       if run.get('temporal_policy') else 86400)
    receipt = validate_database(database, expected, counts, blocks, closing_seconds=closing_seconds)
    _native_run(directory, expected['iteration'], expected)
    output.mkdir(parents=True, exist_ok=True)
    config_file = _write_metadata(output / 'source-config.json', fixed, reserve_bytes)
    side_file = _write_metadata(output / 'source-side.json', side, reserve_bytes)
    manifest = dict(schema_version=1, source_type=SOURCE_TYPE, status='complete',
        **expected, run_directory=str(directory), sample_rate=1.0,
        planned_persons=run['counts']['planned_persons'], planned_trips=run['counts']['planned_trips'],
        database=str(database), database_external=True, database_bytes=receipt['bytes'],
        database_mtime_ns=receipt['mtime_ns'], database_sha256=receipt['sha256'],
        database_validation=receipt, config_file=config_file, side_file=side_file,
        closing_segment_ids=receipt['closing_segment_ids'],
        replay_window=side['replay_window'], window_seconds=blocks[0]['end_seconds']-blocks[0]['start_seconds'],
        blocks=blocks, block_contract='SQLite segment_blocks temporal index; no HTML presence asserted',
        counts=counts, operational_counts=result['counts'],
        visual_vehicle_counts=config['pagination'].get('visual_vehicle_counts'),
        sources={**config.get('motion_sources', {}), **{key: result[key] for key in ('events', 'network', 'plans')}},
        native_signal_summary={key: value for key, value in side_data['signal_replay'].items() if key != 'series'},
        trajectories_only=config.get('trajectories_only', False), html_bytes=0,
        phases_seconds={'source_validation': time.perf_counter()-started},
        provenance=provenance or {'kind': 'fresh-finalized-spool'},
        source_time_horizon=run['time_horizon'], metadata_bytes=config_file['bytes']+side_file['bytes'])
    manifest['operational_counts_observation_end_seconds'] = result['observed_event_end_seconds']
    if file_identity(database) != {key: receipt[key] for key in ('bytes', 'mtime_ns')}:
        raise ValueError('SQLite cambio antes de publicar fuente')
    _native_run(directory, expected['iteration'], expected)
    atomic_json_preserve(output / FILE_NAME, manifest, reserve_bytes=reserve_bytes, overwrite=False)
    return manifest


def build_source(run_dir, source, output, *, iteration=None, anchor=None, side_cache=None,
                 allow_native_side_scan=False, temp_dir=None, reserve_bytes=DEFAULT_RESERVE_BYTES):
    """Recover only direct metadata, preserving every original file.

    Native XML is read only if ``allow_native_side_scan`` is explicitly true.
    That pass extracts signals/incidents, not trajectories. It needs an explicit
    scratch directory and refuses incomplete window-local side-data.
    """
    output = Path(output).resolve()
    preflight_storage(output, 1024 * 1024, reserve_bytes, probe_write=True)
    temporary = None
    if allow_native_side_scan and side_cache is None:
        if temp_dir is None:
            raise ValueError('Indique --temp-dir para recuperar senales/incidentes nativos')
        temporary = Path(temp_dir).resolve()
        preflight_storage(temporary, MAX_METADATA_BYTES, reserve_bytes, probe_write=True,
                          largest_file_bytes=MAX_METADATA_BYTES)
    source = Path(source).resolve(strict=True)
    directory, run, expected = _native_run(run_dir, iteration)
    if (output / FILE_NAME).exists():
        _, previous, database = checked_source(output)
        if identity(previous) != expected or database != source / 'replay.sqlite':
            raise ValueError('Fuente SQLite previamente publicada incompatible')
        return previous
    candidates = sorted((source / 'blocks').glob('*.html'), key=lambda path: path.stat().st_size)
    anchor = Path(anchor).resolve(strict=True) if anchor is not None else (candidates[0] if candidates else None)
    if anchor is None:
        raise ValueError('Falta un HTML completo que pruebe finalizacion del spool historico')
    print(f'SQLite directo: verificando HTML ancla {anchor} ({anchor.stat().st_size:,} bytes); '
          'no se copian ni regeneran los bloques', flush=True)
    info = inspect_block(anchor, expected_identity=expected)
    from simz1_recover_paged import check_config, check_record_samples, small_config
    blocks = _blocks(info['config']['pagination']['blocks'])
    check_config(info['config'], expected, run, blocks)
    index = info['config']['pagination']['block_index']
    if type(index) is not int or not 0 <= index < len(blocks) or info['config']['replay_window'] != {
            key: blocks[index][key] for key in ('start_seconds', 'end_seconds')}:
        raise ValueError('Ventana del HTML ancla incompatible con SQLite')
    database = source / 'replay.sqlite'
    with closing(readonly_database(database, expected)) as connection:
        check_record_samples(connection, info['sample_records'])
    config = small_config(info['config'])
    if side_cache is not None:
        side = _load_cache(side_cache, run, expected, config)
        side_origin = dict(kind='verified-native-cache', path=str(Path(side_cache).resolve()), sha256=sha256(side_cache))
    elif allow_native_side_scan:
        temporary.mkdir(parents=True, exist_ok=True)
        from simz1_recovery_native import recover_side_data
        side = recover_side_data(directory, run, expected['iteration'], config, temporary, expected, reserve_bytes,
                                 max_cache_bytes=MAX_METADATA_BYTES)
        side_origin = dict(kind='native-side-event-pass', events=run['results'][str(expected['iteration'])]['events'])
    else:
        raise ValueError('Faltan senales/incidentes de cobertura completa: indique --side-cache verificada '
                         'o autorice --allow-native-side-scan; no se extrapolan los HTML faltantes')
    provenance = dict(kind='legacy-finalized-html-anchor', anchor=str(anchor),
        anchor_sha256=info['sha256'], anchor_bytes=info['html_bytes'], anchor_window=info['config']['replay_window'],
        side=side_origin, guarantee='Complete anchor emitted only after native spool finalization; '
        'SQLite quick_check and SHA256; complete native side data; window payloads validated on demand')
    return publish_source(directory, database, output, config, side, blocks, config['trajectory_stats'],
                          iteration=expected['iteration'], provenance=provenance, reserve_bytes=reserve_bytes)


def _metadata(directory, entry):
    root = Path(directory).resolve(strict=True)
    path = (root / entry['file']).resolve(strict=True)
    if path.parent != root or path.stat().st_size != entry['bytes'] or entry['bytes'] > MAX_METADATA_BYTES:
        raise ValueError('Ruta/tamano de metadatos SQLite incompatible')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Hash de metadatos SQLite incompatible')
    return json.loads(raw)


def load_config(directory, manifest=None):
    if manifest is None:
        _, manifest, _ = checked_source(directory)
    return _metadata(directory, manifest['config_file'])


def load_side_data(directory, manifest=None):
    if manifest is None:
        _, manifest, _ = checked_source(directory)
    envelope = _metadata(directory, manifest['side_file'])
    if (identity(envelope) != identity(manifest) or envelope.get('coverage') != 'complete-native-event-stream'
            or envelope.get('replay_window') != manifest['replay_window']):
        raise ValueError('Cobertura/identidad nativa SQLite incompleta')
    return envelope['data']


def checked_source(directory):
    root = Path(directory).resolve(strict=True)
    manifest = json.loads((root / FILE_NAME).read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != 1 or manifest.get('source_type') != SOURCE_TYPE or
            manifest.get('status') != 'complete' or manifest.get('sample_rate') != 1):
        raise ValueError('Fuente SQLite directa incompleta o formato incompatible')
    _, run, expected = _native_run(manifest['run_directory'], manifest['iteration'], identity(manifest))
    database = Path(manifest['database']).resolve(strict=True)
    if file_identity(database) != dict(bytes=manifest['database_bytes'], mtime_ns=manifest['database_mtime_ns']):
        raise ValueError('SQLite cambio despues de publicar la fuente')
    receipt = manifest['database_validation']
    if (receipt.get('integrity') != 'quick_check+sha256' or receipt.get('sha256') != manifest.get('database_sha256')
            or not isinstance(receipt.get('sha256'), str) or len(receipt['sha256']) != 64 or
            receipt.get('bytes') != manifest['database_bytes'] or
            receipt.get('mtime_ns') != manifest['database_mtime_ns'] or
            receipt.get('segments') != manifest['counts']['segments'] or
            receipt.get('closing_segment_ids') != manifest.get('closing_segment_ids')):
        raise ValueError('Fuente SQLite sin comprobante completo de integridad')
    blocks = _blocks(manifest['blocks'])
    config = load_config(root, manifest)
    from simz1_recover_paged import check_config
    check_config(config, expected, run, blocks)
    if manifest['counts'] != config.get('trajectory_stats'):
        raise ValueError('Conteos SQLite incompatibles con la configuracion')
    result = run['results'][str(expected['iteration'])]
    if (any(manifest.get(key) != run['counts'][key] for key in ('planned_persons', 'planned_trips')) or
            manifest.get('operational_counts') != result['counts'] or
            manifest.get('operational_counts_observation_end_seconds') != result['observed_event_end_seconds'] or
            manifest['window_seconds'] != blocks[0]['end_seconds'] - blocks[0]['start_seconds']):
        raise ValueError('Metricas/horizonte SQLite incompatibles con la corrida')
    if manifest['replay_window'] != dict(start_seconds=blocks[0]['start_seconds'], end_seconds=blocks[-1]['end_seconds']):
        raise ValueError('Cobertura SQLite no coincide con el indice temporal')
    with closing(readonly_database(database, expected)):
        pass
    side = load_side_data(root, manifest)
    _validate_side(side, config, run['results'][str(expected['iteration'])])
    return root, manifest, database
