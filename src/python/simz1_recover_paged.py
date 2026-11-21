"""Recover an interrupted SimZ1 paged export without extracting trajectories.

Only the existing finalized replay.sqlite is used for movement and lanes. The
native events are read once for missing signal/incident side data, cached in an
explicit scratch directory. Original evidence and failed staging files survive.
"""
import argparse
import errno
from contextlib import contextmanager, closing
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

from simz1_paged_replay import (SqliteTrajectorySink, annotate_observation_times,
                              index_html, unpacked, windows)
from simz1_recovery_io import (atomic_json_preserve, atomic_copy_preserve,
                               ensure_space, inspect_block, write_block,
                               preflight_storage, StorageUnavailableError)
from simz1_run import sha256, checked_path

GIB = 1024 ** 3
IDENTITY_KEYS = ('run_id', 'iteration', 'run_manifest_sha256')
EXIT_CODES = dict(COMPLETE=0, INCOMPLETE=2, INVALID=3,
                  STORAGE_UNAVAILABLE=4, INSUFFICIENT_SPACE=5)


def failure_status(error):
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return 'INSUFFICIENT_SPACE'
    if isinstance(error, (StorageUnavailableError, PermissionError, FileNotFoundError)):
        return 'STORAGE_UNAVAILABLE'
    return 'INVALID'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def small_config(config):
    """Discard large window arrays before copying the small fixed template."""
    value = dict(config)
    value['layers'] = [dict(layer, data=[]) if layer['id'] in ('trips', 'incidents') else layer
                       for layer in config['layers']]
    if 'lane_replay' in config:
        value['lane_replay'] = dict(config['lane_replay'], events=[])
    if 'signal_replay' in config:
        value['signal_replay'] = dict(config['signal_replay'], series=[dict(group, states=[])
                                    for group in config['signal_replay'].get('series', [])])
    return deepcopy(value)


def stable_config(config):
    """Everything except explicitly window-local data is part of the contract."""
    value = small_config(config)
    value.pop('recovery_identity', None)
    value.pop('replay_window', None)
    value['hud'].pop('reconstructed_vehicles', None)
    for key in ('block_index', 'loaded_segments'):
        value['pagination'].pop(key, None)
    for key in ('lane_replay', 'signal_replay'):
        if key in value:
            for field in ('window', 'retained_events', 'retained_state_events', 'predecessor_policy'):
                value[key].pop(field, None)
    return value


def readonly_database(path, expected):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA temp_store=MEMORY')
        connection.execute('PRAGMA cache_size=-32768')
        actual = dict(connection.execute('SELECT key,value FROM export_identity'))
        wanted = {key: str(expected[key]) for key in IDENTITY_KEYS}
        if actual != wanted:
            raise ValueError('SQLite pertenece a otra corrida, iteracion o hash de manifiesto')
        required = {'segments_journey', 'segments_block', 'lanes_vehicle_time', 'lanes_time'}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        if not required <= indexes:
            raise ValueError('Spool sin indices finalizados; no se reconstruye ni modifica el original')
        return connection
    except BaseException:
        connection.close()
        raise


def ordered_records(connection, index):
    """Sort only (time,time,id) in RAM, then read original blobs by primary key.

    No SQL ORDER BY, temporary B-tree, trajectory extraction or motion solver.
    The tuple list is proportional to one block, not the entire simulation.
    """
    rows = list(connection.execute('''SELECT s.start,s.end,s.id FROM segment_blocks b
        JOIN segments s ON s.id=b.segment WHERE b.block=?''', (index,)))
    rows.sort()
    for _, _, ident in rows:
        row = connection.execute('''SELECT s.payload,j.metadata FROM segments s
            JOIN journeys j ON j.key=s.journey WHERE s.id=?''', (ident,)).fetchone()
        if row is None:
            raise ValueError(f'Segmento/viaje ausente del spool: {ident}')
        record = unpacked(row[0])
        if not isinstance(record.get('Motion_Plan'), dict):
            raise ValueError(f'Spool sin Motion_Plan finalizado: {ident}')
        record['Trip'] = json.loads(row[1])
        yield record


def block_counts(connection, blocks):
    return [connection.execute('SELECT count(*) FROM segment_blocks WHERE block=?',
                               (block['index'],)).fetchone()[0] for block in blocks]


def check_config(config, expected, manifest, blocks):
    hud = config['hud']
    if hud['run_id'] != expected['run_id'] or hud['iteration'] != expected['iteration']:
        raise ValueError('HTML de otra corrida o iteracion')
    if config.get('recovery_identity', expected) != expected:
        raise ValueError('Hash de corrida incompatible en HTML recuperado')
    if config['pagination']['blocks'] != blocks or config['pagination']['block_count'] != len(blocks):
        raise ValueError('Configuracion de ventanas incompatible')
    if config['pagination']['sample_rate'] != 1:
        raise ValueError('No se recupera una exportacion muestreada')
    result = manifest['results'][str(expected['iteration'])]
    if config.get('operational_counts') != result['counts']:
        raise ValueError('Conteos operativos incompatibles con la corrida')
    if config.get('time_horizon') != manifest['time_horizon']:
        raise ValueError('Horizonte nativo incompatible')
    for name, value in manifest['counts'].items():
        if hud.get(name) != value:
            raise ValueError(f'Conteo HUD incompatible: {name}')
    if 'lane_replay' in config and config['lane_replay'].get('configuration_sha256') != manifest['effective_config']['sha256']:
        raise ValueError('Hash de configuracion de carriles incompatible')
    sources = config.get('motion_sources', {})
    if sources.get('plans') != result['plans']:
        raise ValueError('Hash de planes incompatible con los Motion_Plan existentes')
    if 'effective_vehicles' in sources and sources['effective_vehicles'] != manifest.get('effective_vehicles'):
        raise ValueError('Hash de vehiculos incompatible')
    effective_lanes = manifest.get('effective_lane_configuration_validation', {}).get('loaded_artifacts', {}).get('lanes')
    if 'transit_stop_lanes' in sources and (not effective_lanes or sources['transit_stop_lanes'] != effective_lanes):
        raise ValueError('Fuente/hash de carriles de parada incompatible con el artefacto efectivo')
    known_sources = [result.get(name) for name in ('plans', 'network', 'events')]
    known_sources.extend(manifest.get('inputs', {}).values())
    known_sources.append(manifest.get('effective_vehicles'))
    known_sources.append(effective_lanes)
    if any(isinstance(record, dict) and 'sha256' in record and record not in known_sources
           for record in sources.values()):
        raise ValueError('Fuente/hash de movimiento ajeno al manifiesto nativo')
    motion_summary = config.get('trajectory_stats', {}).get('visual_motion', {})
    if 'settings' in motion_summary and motion_summary['settings'] != config['visual_motion']['settings']:
        raise ValueError('Configuracion visual incompatible con el resumen del spool')


def inventory(source, expected, manifest, checkpoint=None):
    valid, invalid, config, contract, shell = {}, {}, None, None, None
    for path in sorted((source / 'blocks').glob('*.html')):
        if not path.stem.isdigit():
            raise ValueError(f'Bloque ajeno al esquema numerado: {path}')
        index = int(path.stem)
        receipt = (checkpoint or {}).get('blocks', {}).get(str(index))
        if receipt:
            if path.stat().st_size != receipt['html_bytes'] or sha256(path) != receipt['sha256']:
                raise ValueError(f'Hash de bloque distinto del checkpoint verificado: {path}')
            if config is not None:
                if index >= len(blocks) or any(receipt.get(k) != v for k, v in blocks[index].items()):
                    raise ValueError('Checkpoint con contrato de bloque incompatible')
                valid[index] = {k: receipt[k] for k in ('sha256', 'html_bytes', 'segments', 'vehicles')}
                valid[index].update(path=str(path), sample_records=[])
                print(f'Reutilizable por SHA256 verificado: {index + 1}/{len(blocks)}', flush=True)
                continue
        try:
            info = inspect_block(path)
        except (ValueError, UnicodeError) as exc:
            invalid[index] = dict(path=str(path), reason=str(exc))
            continue
        current = info['config']
        if config is None:
            config, shell = small_config(current), (info['prefix'], info['suffix'])
            raw_blocks = current['pagination']['blocks']
            if not raw_blocks:
                raise ValueError('Export sin contrato de ventanas')
            blocks = windows(raw_blocks[0]['start_seconds'], raw_blocks[-1]['end_seconds'],
                             current['pagination']['window_seconds'])
            if blocks != raw_blocks:
                raise ValueError('Contrato de ventanas incompleto o irregular')
            contract = fingerprint(stable_config(config))
            if checkpoint and checkpoint.get('configuration_sha256') != contract:
                raise ValueError('Configuracion incompatible con el checkpoint')
        check_config(current, expected, manifest, blocks)
        if fingerprint(stable_config(current)) != contract:
            raise ValueError(f'Mezcla de configuraciones/hashes entre bloques: {path}')
        if index >= len(blocks) or index in valid or current['pagination']['block_index'] != index:
            raise ValueError(f'Indice de bloque incompatible: {path}')
        if current['replay_window'] != {k: blocks[index][k] for k in ('start_seconds', 'end_seconds')}:
            raise ValueError(f'Ventana HTML incompatible: {path}')
        if shell != (info['prefix'], info['suffix']):
            raise ValueError(f'Mezcla de plantillas/controles entre bloques: {path}')
        valid[index] = {k: info[k] for k in ('sha256', 'html_bytes', 'segments', 'vehicles')}
        valid[index]['path'] = str(path)
        valid[index]['sample_records'] = info.get('sample_records', [])
        print(f'Integridad HTML: {index + 1}/{len(blocks)}', flush=True)
    if config is None:
        raise ValueError('No hay bloque completo para recuperar el contrato legacy; se conserva todo')
    if any(index >= len(blocks) for index in invalid):
        raise ValueError('Archivos parciales fuera del contrato de bloques')
    return config, blocks, valid, invalid, contract, shell


def check_record_samples(connection, records):
    """Bind legacy HTML to the original finalized payload, including motion.

    Legacy exports had no saved block digests. Full JSON/count/window checks
    plus endpoint comparisons establish reusable evidence; new receipts bind
    every byte from this recovery forward. This is not an invented old hash.
    """
    for record in records:
        key = record.get('Replay_Journey_Key')
        if not key:
            raise ValueError('Bloque sin clave de viaje del spool original')
        candidates = connection.execute('''SELECT s.payload,j.metadata FROM segments s
            JOIN journeys j ON j.key=s.journey WHERE s.journey=? AND s.vehicle=?
            AND s.start=? AND s.end=?''', (key, record['vehicle'], *record['timestamps']))
        found = False
        for raw, trip in candidates:
            expected_record = unpacked(raw)
            expected_record['Trip'] = json.loads(trip)
            if expected_record == record:
                found = True
                break
        if not found:
            raise ValueError('HTML no corresponde a los Motion_Plan originales del SQLite')


def estimate_space(valid, counts, missing, *, copy_bytes=0):
    # Conservative empirical ceiling, with headroom for variable trip metadata,
    # lanes and signals. It is a forecast, not a guarantee; writer checks again.
    per_segment = max((v['html_bytes'] / v['segments'] for v in valid.values() if v['segments']), default=8192)
    fixed = max((v['html_bytes'] for v in valid.values() if not v['segments']), default=4 * 1024 ** 2)
    sizes = {index: math.ceil((counts[index] * per_segment + fixed) * 1.35) for index in missing}
    largest = max(sizes.values(), default=0)
    return dict(missing_blocks=len(missing), predicted_block_bytes=sizes,
                additional_html_bytes=sum(sizes.values()), copy_existing_html_bytes=copy_bytes,
                destination_required_bytes=copy_bytes + sum(sizes.values()) + largest,
                scratch_required_bytes=largest + 512 * 1024 ** 2,
                assumptions='1.35 x largest observed bytes/segment, 4MiB fixed/block, one staging block; reserve additional')


def file_identity(path):
    stat = path.stat()
    return dict(bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)


@contextmanager
def recovery_lock(folder):
    """OS lock releases on crash; the tiny lock file is deliberately retained."""
    path = folder / '.recovery.lock'
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def copy_block(source, target, reserve_bytes):
    """Copy verified bytes without compilation, retaining a failed copy."""
    atomic_copy_preserve(source, target, reserve_bytes=reserve_bytes)


def check_final_manifest(folder, expected, blocks, valid, database, database_stat, database_hash=None):
    path = folder / 'export-manifest.json'
    if not path.exists():
        return 'absent'
    report = json.loads(path.read_text(encoding='utf-8'))
    if (report.get('status') != 'complete' or report.get('sample_rate') != 1 or
            any(report.get(key) != expected[key] for key in IDENTITY_KEYS) or
            len(report.get('blocks', [])) != len(blocks) or len(valid) != len(blocks)):
        raise ValueError('Manifiesto final incompatible/incompleto; no se declara recuperado')
    for expected_block, actual in zip(blocks, report['blocks']):
        index = expected_block['index']
        target = folder / 'blocks' / expected_block['url']
        if Path(valid[index]['path']) != target or not target.is_file():
            raise ValueError('Manifiesto final con bloques ausentes en su destino')
        if any(actual.get(k) != v for k, v in expected_block.items()) or any(
                actual.get(k) != valid[index][k] for k in ('sha256', 'html_bytes', 'segments', 'vehicles')):
            raise ValueError('El manifiesto final no coincide con los bloques verificados')
    wanted_db = (folder / report['database']).resolve()
    if wanted_db != database or report.get('database_bytes') != database_stat['bytes']:
        raise ValueError('SQLite incompatible con el manifiesto final')
    if report.get('database_sha256') != (database_hash or sha256(database)):
        raise ValueError('Hash SQLite incompatible con el manifiesto final')
    return 'verified'


def window_config(config, block, count, vehicles, connection, side, expected):
    from bisect import bisect_left
    result = deepcopy(config)
    start, end = block['start_seconds'], block['end_seconds']
    result['replay_window'] = dict(start_seconds=start, end_seconds=end)
    result['recovery_identity'] = expected
    result['pagination'].update(block_index=block['index'], loaded_segments=count)
    result['hud']['reconstructed_vehicles'] = len(vehicles)
    for layer in result['layers']:
        if layer['id'] == 'incidents':
            layer['data'] = [item for item in side['incidents'] if item['start'] < end and
                             (item['end'] is None or item['end'] > start)]
    if 'lane_replay' in result:
        # The existing indexed lane reader has no large BLOB sorter.
        store = object.__new__(SqliteTrajectorySink)
        store.connection = connection
        events = store.block_lanes(start, end, vehicles)
        result['lane_replay'].update(events=events, retained_events=len(events), window=[start, end])
    if 'signal_replay' in result:
        series = []
        for group in side['signal_replay']['series']:
            states = group['states']
            first = bisect_left(states, start, key=lambda state: state[0])
            last = bisect_left(states, end, key=lambda state: state[0])
            series.append(dict(group, states=states[max(0, first - 1):last]))
        result['signal_replay'].update(series=series, window=[start, end],
            retained_state_events=sum(len(group['states']) for group in series))
    return result


def recover(run_dir, source, *, output=None, temp_dir=None, iteration=None,
            reserve_bytes=2 * GIB, audit_only=False, expected_blocks=None):
    run_dir, source = Path(run_dir).resolve(strict=True), Path(source).resolve(strict=True)
    output = Path(output).resolve() if output else source
    temporary = Path(temp_dir).resolve() if temp_dir else output / '.recovery-temp'
    if temporary in (output, source, output / 'blocks', source / 'blocks'):
        raise ValueError('--temp-dir requiere una carpeta propia, por ejemplo scratch o .recovery-temp')
    if not math.isfinite(reserve_bytes) or reserve_bytes < 0:
        raise ValueError('Reserva de espacio invalida')
    reserve_bytes = int(reserve_bytes)
    # Detect nonexistent drives, incompatible directories and write failures
    # before the many-gigabyte HTML inventory. Read-only verification never
    # creates probes and does not require free space to inspect existing bytes.
    storage = dict(destination=preflight_storage(output,
        reserve_bytes=0 if audit_only else reserve_bytes, probe_write=not audit_only),
        scratch=preflight_storage(temporary,
            reserve_bytes=0 if audit_only else reserve_bytes, probe_write=not audit_only))
    manifest_path = run_dir / 'run-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('Se requiere corrida completed/valid; nunca se ejecuta MATSim')
    database = source / 'replay.sqlite'
    if not database.is_file():
        raise ValueError('Falta el spool original; no se regeneran trayectorias automaticamente')
    if iteration is None:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            iteration = int(dict(connection.execute('SELECT key,value FROM export_identity'))['iteration'])
    expected = dict(run_id=manifest['run_id'], iteration=iteration, run_manifest_sha256=sha256(manifest_path))
    if str(iteration) not in manifest['results']:
        raise ValueError('Iteracion ausente de la corrida validada')
    initial_database = file_identity(database)
    state_path = output / 'recovery-state.json'
    checkpoint = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else None
    if checkpoint and (checkpoint.get('identity') != expected or checkpoint.get('database') != str(database) or
                       checkpoint.get('database_stat') != initial_database):
        raise ValueError('Checkpoint de otra corrida, hash o SQLite')
    with closing(readonly_database(database, expected)) as connection:
        source_checkpoint = checkpoint
        if checkpoint and output != source:
            # Repaired output bytes must never masquerade as a receipt for an
            # intentionally preserved truncated original at the same index.
            source_checkpoint = dict(checkpoint, blocks=checkpoint.get('source_blocks', {}))
        config, blocks, valid, invalid, contract, shell = inventory(source, expected, manifest, source_checkpoint)
        source_receipts = {str(index): dict(blocks[index], **{k: info[k] for k in
            ('sha256', 'html_bytes', 'segments', 'vehicles')}) for index, info in valid.items()}
        if expected_blocks is not None and len(blocks) != expected_blocks:
            raise ValueError(f'Se esperaban {expected_blocks} bloques; contrato contiene {len(blocks)}')
        source_invalid = dict(invalid)
        if output != source and output.exists():
            allowed = {'blocks', '.recovery-temp', '.recovery.lock', 'recovery-state.json',
                       'export-manifest.json', 'index.html'}
            if temporary.is_relative_to(output):
                allowed.add(temporary.relative_to(output).parts[0])
            if any(p.name not in allowed and not p.name.endswith(('.partial', '.tmp')) for p in output.iterdir()):
                raise ValueError('Destino con archivos ajenos a recuperacion; use una carpeta propia')
            if any((output / 'blocks').glob('*.html')):
                other, other_blocks, other_valid, other_invalid, other_contract, other_shell = inventory(output, expected, manifest, checkpoint)
                if other_blocks != blocks or other_contract != contract or other_shell != shell:
                    raise ValueError('Destino de otra configuracion/plantilla de exportacion')
                if other_invalid:
                    raise ValueError('Destino con HTML truncados; se conservan, use otra carpeta de destino')
                valid.update(other_valid)
                invalid = {k: v for k, v in invalid.items() if k not in other_valid}
        counts = block_counts(connection, blocks)
        maximum = connection.execute('SELECT max(id) FROM segments').fetchone()[0] or 0
        segment_count = connection.execute('SELECT count(*) FROM segments').fetchone()[0]
        if maximum != config['trajectory_stats']['segments'] or segment_count != maximum:
            raise ValueError('Spool incompleto frente al total de segmentos original')
        for index, info in valid.items():
            if info['segments'] != counts[index]:
                raise ValueError(f'Cantidad de registros incompatible con SQLite: bloque {index}')
            check_record_samples(connection, info['sample_records'])
        missing = [block['index'] for block in blocks if block['index'] not in valid]
        if output == source and invalid and not audit_only:
            raise ValueError('Hay HTML truncados; use --output en una carpeta nueva para conservar los originales: ' + str(invalid))
        copy_bytes = sum(v['html_bytes'] for v in valid.values()
                         if Path(v['path']).parent != output / 'blocks')
        estimate = estimate_space(valid, counts, missing, copy_bytes=copy_bytes)
        same_volume = storage['destination']['device'] == storage['scratch']['device']
        # All sizes remain estimates: native JSON and the missing signal cache
        # cannot be known exactly until serialization. Show the actual free
        # bytes and the complete per-volume threshold (including reserve).
        estimate['same_volume'] = same_volume
        estimate['required_free_bytes'] = (dict(shared=estimate['destination_required_bytes'] +
            512 * 1024 ** 2 + reserve_bytes) if same_volume else
            dict(destination=estimate['destination_required_bytes'] + reserve_bytes,
                 scratch=estimate['scratch_required_bytes'] + reserve_bytes))
        audit = dict(identity=expected, valid_blocks=len(valid), expected_blocks=len(blocks),
                     missing_blocks=missing, invalid_blocks=invalid, original_invalid_blocks=source_invalid, space=estimate,
                     source=str(source), output=str(output), temp_dir=str(temporary),
                     database=str(database), database_storage='original read-only; no copy',
                     storage=storage, complete=False)
        if audit_only:
            verified_hash = sha256(database) if checkpoint else None
            if checkpoint and checkpoint.get('database_sha256') != verified_hash:
                raise ValueError('Hash SQLite incompatible con el checkpoint de integridad')
            audit['final_manifest'] = check_final_manifest(output, expected, blocks, valid, database, initial_database, verified_hash)
            audit['status'] = ('INVALID' if invalid else 'COMPLETE' if
                not missing and audit['final_manifest'] == 'verified' else 'INCOMPLETE')
            audit['complete'] = audit['status'] == 'COMPLETE'
            return audit
        # A completed manifest is never replaced by an incomplete recovery.
        if (output / 'export-manifest.json').exists():
            raise ValueError('Destino con manifiesto final: use --audit-only para verificarlo, u otra carpeta')
        largest = max(estimate['predicted_block_bytes'].values(), default=0)
        largest_copy = max((info['html_bytes'] for info in valid.values()
                           if Path(info['path']).parent != output / 'blocks'), default=0)
        preflight_storage(output, estimate['destination_required_bytes'], reserve_bytes,
                          largest_file_bytes=max(largest, largest_copy))
        preflight_storage(temporary, estimate['scratch_required_bytes'], reserve_bytes,
                          largest_file_bytes=largest)
        # When both paths share a volume their budgets add; never double-count free space.
        if same_volume:
            ensure_space(output, estimate['destination_required_bytes'] + 512 * 1024 ** 2, reserve_bytes)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'blocks').mkdir(exist_ok=True)
        temporary.mkdir(parents=True, exist_ok=True)
        with recovery_lock(output):
            return finish_recovery(connection, run_dir, manifest, expected, source, output, temporary,
                database, initial_database, config, blocks, valid, counts, contract, shell, audit, reserve_bytes,
                source_receipts)


def finish_recovery(connection, run_dir, manifest, expected, source, output, temporary,
                    database, initial_database, config, blocks, valid, counts, contract, shell, audit, reserve,
                    source_receipts):
    from simz1_recovery_native import recover_side_data, derive_observation_probe
    started = time.perf_counter()
    print('Verificando SQLite read-only (quick_check y SHA256); no se recalculan trayectorias', flush=True)
    if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite no supera quick_check; se conserva sin modificar')
    database_hash = sha256(database)
    state_path = output / 'recovery-state.json'
    state_identity = dict(identity=expected, configuration_sha256=contract,
        database=str(database), database_sha256=database_hash, database_stat=initial_database)
    old_state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else None
    if old_state and any(old_state.get(key) != value for key, value in state_identity.items()):
        raise ValueError('Checkpoint de otra corrida, configuracion o SQLite; no se mezclan exportaciones')
    # Verify native source hashes, without parsing plans or constructing motion.
    result = manifest['results'][str(expected['iteration'])]
    verified_sources = set()
    for record in [result['events'], result['plans'], result['network'], manifest['effective_config'], *config.get('motion_sources', {}).values()]:
        if isinstance(record, dict) and 'path' in record and 'sha256' in record:
            pair = (record['path'], record['sha256'])
            if pair not in verified_sources:
                checked_path(run_dir, record)
                verified_sources.add(pair)
    state = dict(schema_version=1, status='incomplete', **state_identity, blocks={},
                 source_blocks=source_receipts, estimate=audit['space'])
    # Keep old verified receipts until their replacements have been validated.
    # The state is never the consumer-facing success marker.
    if old_state:
        state['blocks'] = old_state.get('blocks', {})
    atomic_json_preserve(state_path, state, reserve_bytes=reserve)
    final_blocks, pending = [], []
    for block in blocks:
        index = block['index']
        target = output / 'blocks' / block['url']
        if index in valid and Path(valid[index]['path']) == target:
            info = valid[index]
        elif target.exists():
            info = inspect_block(target, expected_identity=expected,
                expected_window={k: block[k] for k in ('start_seconds', 'end_seconds')})
            check_config(info['config'], expected, manifest, blocks)
            if fingerprint(stable_config(info['config'])) != contract or info['segments'] != counts[index]:
                raise ValueError(f'Bloque de destino incompatible: {target}')
            if (info['prefix'],info['suffix']) != shell:
                raise ValueError(f'Plantilla de destino incompatible: {target}')
            check_record_samples(connection, info.get('sample_records', []))
        elif index in valid:
            copy_block(Path(valid[index]['path']), target, reserve)
            info = valid[index]
        else:
            pending.append(block)
            continue
        final_blocks.append(dict(block, **{k: info[k] for k in ('sha256', 'html_bytes', 'segments', 'vehicles')}, reused=True))
    state['blocks'] = {str(item['index']): item for item in final_blocks}
    atomic_json_preserve(state_path, state, reserve_bytes=reserve)
    side = recover_side_data(run_dir, manifest, expected['iteration'], config, temporary, expected, reserve) if pending else None
    for block in pending:
        index = block['index']
        ensure_space(output, audit['space']['predicted_block_bytes'].get(index, 0), reserve)
        vehicles = {row[0] for row in connection.execute('''SELECT s.vehicle FROM segment_blocks b
            JOIN segments s ON s.id=b.segment WHERE b.block=?''', (index,))}
        current = window_config(config, block, counts[index], vehicles, connection, side, expected)
        info = write_block(output / 'blocks' / block['url'], current, ordered_records(connection, index),
            shell[0], shell[1], temporary, reserve_bytes=reserve)
        if info['segments'] != counts[index] or fingerprint(stable_config(info['config'])) != contract:
            raise ValueError('Bloque escrito incompatible; no se publica manifiesto')
        item = dict(block, **{k: info[k] for k in ('sha256', 'html_bytes', 'segments', 'vehicles')}, reused=False)
        final_blocks.append(item)
        state['blocks'][str(index)] = item
        atomic_json_preserve(state_path, state, reserve_bytes=reserve)
        print(f'Recuperado {index + 1}/{len(blocks)}; Motion_Plan original', flush=True)
    final_blocks.sort(key=lambda block: block['index'])
    if [block['index'] for block in final_blocks] != list(range(len(blocks))):
        raise ValueError('Faltan bloques; no se publica manifiesto')
    probe = derive_observation_probe(connection, manifest['time_horizon']['end_seconds'])
    probe.update(pending_link_intervals_after_event_stream=config['trajectory_stats'].get('pending_link_intervals', 0),
                 unclosed_intervals_removed_at_abort=config['trajectory_stats'].get('unclosed_intervals_at_abort', 0))
    report = dict(schema_version=1, status='complete', **expected, run_directory=str(run_dir),
        planned_persons=manifest['counts']['planned_persons'], planned_trips=manifest['counts']['planned_trips'],
        sample_rate=1.0, window_seconds=config['pagination']['window_seconds'],
        replay_window=dict(start_seconds=blocks[0]['start_seconds'], end_seconds=blocks[-1]['end_seconds']),
        blocks=final_blocks, counts=config['trajectory_stats'], operational_counts=result['counts'],
        visual_vehicle_counts=config['pagination']['visual_vehicle_counts'], observation_end_probe=probe,
        block_segment_occurrences=sum(counts), segments_outside_replay_window=None,
        sources={**config.get('motion_sources', {}), **{k: result[k] for k in ('events', 'network', 'plans')}},
        database='replay.sqlite' if source == output else str(database), database_external=source != output,
        database_bytes=initial_database['bytes'], database_mtime_ns=initial_database['mtime_ns'], database_sha256=database_hash,
        html_bytes=sum(b['html_bytes'] for b in final_blocks), trajectories_only=config.get('trajectories_only', False),
        # The failed exporter never persisted its historical measurements.
        # Keep the consumer's schema without inventing original elapsed time.
        phases_seconds={}, process_peak_working_set_bytes=None,
        historical_measurements_status='unavailable: interrupted legacy export had no manifest',
        visual_motion=dict(config['visual_motion'], summary=config['trajectory_stats'].get('visual_motion', {})),
        native_signal_summary={k: v for k, v in config.get('signal_replay', {}).items()
                               if k not in ('series', 'window', 'retained_state_events', 'predecessor_policy')},
        recovery=dict(source=str(source), configuration_sha256=contract, reused_blocks=sum(b['reused'] for b in final_blocks),
                      generated_blocks=len(pending), verified_blocks=len(final_blocks), original_database=str(database),
                      elapsed_seconds=time.perf_counter() - started),
        note='Recovered from finalized read-only SQLite; original Motion_Plan; no MATSim or population generation')
    annotate_observation_times(report, result['observed_event_end_seconds'])
    # Validate every final file against its verified receipt AFTER all lengthy
    # reads, including reused files. The success marker is the last write.
    for block in final_blocks:
        path = output / 'blocks' / block['url']
        if path.stat().st_size != block['html_bytes'] or sha256(path) != block['sha256']:
            raise ValueError(f'Bloque cambio antes de publicar: {path}')
    if sha256(run_dir / 'run-manifest.json') != expected['run_manifest_sha256'] or file_identity(database) != initial_database:
        raise ValueError('La evidencia original cambio durante la recuperacion')
    # Write the small index using the same preserve-on-failure atomic policy.
    import tempfile
    target = output / 'index.html'
    payload = index_html(report).encode('utf-8')
    ensure_space(output, len(payload), reserve)
    fd, staging = tempfile.mkstemp(prefix='index.', suffix='.tmp', dir=output)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.replace(staging, target)
    # A verified block checkpoint is not a complete export: publishing the
    # manifest can still fail (for example ENOSPC). Only the final manifest
    # marks completion, so a crash here remains explicitly incomplete.
    state.update(status='incomplete', phase='all_blocks_verified_pending_manifest',
                 blocks={str(b['index']): b for b in final_blocks})
    atomic_json_preserve(state_path, state, reserve_bytes=reserve)
    atomic_json_preserve(output / 'export-manifest.json', report, reserve_bytes=reserve, overwrite=False)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True, help='webgl-source interrumpido con replay.sqlite')
    parser.add_argument('--output', type=Path, help='Carpeta destino; omitir reanuda en source')
    parser.add_argument('--temp-dir', type=Path, help='Scratch, incluso otra unidad; defecto destino/.recovery-temp')
    parser.add_argument('--iteration', type=int)
    parser.add_argument('--expected-blocks', type=int, help='Falla si el contrato no tiene exactamente esta cantidad')
    parser.add_argument('--reserve-gib', type=float, default=2.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--audit-only', '--verify-final', dest='audit_only', action='store_true',
        help='Verificacion final solo lectura; salida no cero si faltan bloques/manifiesto o son invalidos')
    mode.add_argument('--diagnose', action='store_true',
        help='Informe solo lectura; 0 significa diagnostico obtenido, nunca exportacion completa')
    args = parser.parse_args(argv)
    readonly = args.audit_only or args.diagnose
    operation = 'diagnostic' if args.diagnose else 'final_verification' if readonly else 'recovery'
    try:
        result = recover(args.run_dir, args.source, output=args.output, temp_dir=args.temp_dir,
            iteration=args.iteration, expected_blocks=args.expected_blocks,
            reserve_bytes=args.reserve_gib * GIB, audit_only=readonly)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        status = failure_status(exc)
        print(json.dumps(dict(mode=operation, status=status, complete=False,
            diagnostic_completed=False, error=str(exc)), indent=2, ensure_ascii=False))
        return EXIT_CODES[status]
    report = dict(result) if readonly else dict(status='COMPLETE', complete=True,
        blocks=len(result['blocks']), manifest=str(Path(args.output or args.source) / 'export-manifest.json'))
    report.update(mode=operation, verification_requested=bool(args.audit_only))
    if args.diagnose:
        report['diagnostic_completed'] = True
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if args.diagnose else EXIT_CODES[report['status']]


if __name__ == '__main__':
    sys.exit(main())
