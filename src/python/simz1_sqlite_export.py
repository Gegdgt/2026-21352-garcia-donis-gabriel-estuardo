"""One event extraction, durable SQLite source, no paged HTML duplication."""
from contextlib import closing
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

from simz1_paged_replay import SqliteTrajectorySink, LaneSink, ReplayPayload, windows
from simz1_recovery_io import preflight_storage, ensure_space
from simz1_run import sha256

MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024


def _bytes(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _checkpoint(path, payload, reserve):
    raw = _bytes(payload)
    envelope = _bytes(dict(sha256=hashlib.sha256(raw).hexdigest(), payload=payload))
    if len(envelope) > MAX_CHECKPOINT_BYTES:
        raise ValueError('Checkpoint excede 256 MiB; no se escribe un temporal sin limite')
    compressed = gzip.compress(envelope, compresslevel=1, mtime=0)
    ensure_space(path.parent, len(compressed), reserve)
    stage = path.with_name(path.name + '.partial')
    # Retain a failed stage for inspection. A later attempt uses a new name.
    if stage.exists():
        import uuid
        stage = path.with_name(path.name + '.partial.' + uuid.uuid4().hex)
    with stage.open('xb') as stream:
        stream.write(compressed)
        stream.flush()
        os.fsync(stream.fileno())
    stage.replace(path)


def export_sqlite_selected(selection, output=None, *, replay_start=None, replay_end=None,
                           trajectories_only=False, visual_settings=None, window_seconds=900,
                           temp_dir=None, database_budget_bytes=32*1024**3,
                           scratch_budget_bytes=32*1024**3, reserve_bytes=2*1024**3):
    """Export once; resume publication from a finalized spool checkpoint.

    An interrupted, unfinalized event/motion pass is rejected, never advertised
    as complete or silently repeated. Its original native MATSim run is intact.
    Budgets are storage limits, not predictions of scientific output size.
    """
    import visualizador_z1 as viewer
    from simz1_lane_replay import LaneEventReplay
    from simz1_motion import load_selected
    from simz1_signal_replay import SignalReplay, selected_groups
    from simz1_sqlite_source import publish_source, checked_source, FILE_NAME

    if viewer.SAMPLE_RATE != 1:
        raise ValueError('SQLite directo requiere SAMPLE_RATE=1')
    if any(type(value) is not int or value <= 0 for value in
           (database_budget_bytes, scratch_budget_bytes)) or reserve_bytes < 0:
        raise ValueError('Presupuestos de SQLite/scratch deben ser positivos')
    directory = Path(selection['directory']).resolve()
    destination = Path(output).resolve() if output else directory / 'webgl-source' / 'index.html'
    if destination.name != 'index.html':
        raise ValueError('--output requiere <fuente>/index.html (no se genera ese HTML)')
    folder, database = destination.parent, destination.parent / 'replay.sqlite'
    contract = folder / 'sqlite-source'
    checkpoint = folder / 'spool-ready.json.gz'
    manifest = selection['manifest']
    result = manifest['results'][str(selection['iteration'])]
    expected = dict(run_id=manifest['run_id'], iteration=selection['iteration'],
                    run_manifest_sha256=sha256(directory / 'run-manifest.json'))
    export_options = dict(replay_start=replay_start, replay_end=replay_end,
        window_seconds=window_seconds, trajectories_only=trajectories_only, visual_settings=visual_settings)
    if (contract / FILE_NAME).exists():
        _, published, saved_database = checked_source(contract)
        if (any(published[key] != value for key, value in expected.items()) or
                saved_database != database or Path(published['run_directory']) != directory):
            raise ValueError('La fuente publicada corresponde a otra corrida')
        if published.get('provenance', {}).get('export_options') != export_options:
            raise ValueError('Opciones diferentes a la exportacion publicada; no se reemplaza')
        return published
    if checkpoint.exists():
        with gzip.open(checkpoint, 'rb') as stream:
            raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
        if len(raw) > MAX_CHECKPOINT_BYTES:
            raise ValueError('Checkpoint excede el limite de lectura de 256 MiB')
        envelope = json.loads(raw)
        pending = envelope['payload']
        if (hashlib.sha256(_bytes(pending)).hexdigest() != envelope['sha256'] or
                pending['identity'] != expected):
            raise ValueError('Checkpoint SQLite incompatible; se conserva evidencia')
        if pending.get('export_options') != export_options:
            raise ValueError('Opciones diferentes al checkpoint; reanude con los mismos parametros')
        stat = database.stat()
        if pending['database_stat'] != [stat.st_size, stat.st_mtime_ns]:
            raise ValueError('SQLite cambio desde su finalizacion; no se reanuda')
        return publish_source(directory, database, contract, pending['config'], pending['side_data'],
            pending['blocks'], pending['counts'], iteration=selection['iteration'],
            provenance={'kind': 'finalized-spool-checkpoint', 'export_options': export_options}, reserve_bytes=reserve_bytes)
    if database.exists():
        raise ValueError('SQLite existente sin checkpoint finalizado: no se extrae otra vez. '
                         'Para fuente historica con HTML use simz1_continuous_replay.py --sqlite-direct')
    if temp_dir is None:
        raise ValueError('--temp-dir explicito requerido para indices SQLite; no se usa TEMP de C: implicitamente')
    scratch = Path(temp_dir).resolve()
    # Validate both volumes and summed budgets BEFORE reading events or writing SQLite.
    target_info = preflight_storage(folder, required_bytes=database_budget_bytes,
        reserve_bytes=reserve_bytes, probe_write=True, largest_file_bytes=database_budget_bytes)
    scratch_info = preflight_storage(scratch, required_bytes=scratch_budget_bytes,
        reserve_bytes=reserve_bytes, probe_write=True, largest_file_bytes=scratch_budget_bytes)
    if target_info['device'] == scratch_info['device']:
        ensure_space(folder, database_budget_bytes + scratch_budget_bytes, reserve_bytes)
    print(f'SQLite directo: limite base={database_budget_bytes:,} B; '
          f'presupuesto scratch={scratch_budget_bytes:,} B; reserva={reserve_bytes:,} B', flush=True)
    folder.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    chosen = dict(manifest.get('replay_window', manifest['time_horizon']))
    if replay_start is not None:
        chosen['start_seconds'] = replay_start
    if replay_end is not None:
        chosen['end_seconds'] = replay_end
    # Retain the native closing tick and observed drain; continuous projects the
    # visible daily clock to 86400 without modifying source times.
    chosen['end_seconds'] = max(chosen['end_seconds'], result.get('observed_event_end_seconds', 0))
    blocks = windows(chosen['start_seconds'], chosen['end_seconds'], window_seconds)

    def guard(indexes=False):
        ensure_space(folder, 64*1024**2, reserve_bytes)
        ensure_space(scratch, scratch_budget_bytes if indexes else 64*1024**2, reserve_bytes)

    motion = load_selected(selection, visual_settings=visual_settings)
    viewer.NETWORK_FILE, viewer.EVENTS_FILE = selection['network'], selection['events']
    links, signals = viewer.extraer_red()
    native_signals = SignalReplay(selected_groups(selection, links))
    incidents, stats = [], {}
    with closing(SqliteTrajectorySink(database, blocks, storage_guard=guard,
                 temp_dir=scratch, max_database_bytes=database_budget_bytes)) as store:
        store.set_identity(**dict(run_id=expected['run_id'], iteration=expected['iteration'],
                                 manifest_hash=expected['run_manifest_sha256']))
        lanes = None if trajectories_only else LaneEventReplay(links, event_sink=LaneSink(store))
        viewer.extraer_trayectorias(links, incidents, lanes, None if trajectories_only else native_signals,
            motion=motion, stats=stats, horizon=manifest['time_horizon']['end_seconds'], segment_sink=store)
        if not store.finalized:
            raise ValueError('Spool sin finalizacion: no se publica fuente')
        selected = dict(selection, trajectory_stats=stats, motion_sources=motion.sources,
                        trajectories_only=trajectories_only)
        config = viewer.generar_html_animado([], links, signals, [], selection=selected,
            lane_replay=None if lanes is None else ReplayPayload(dict(lanes.payload(), events=[])),
            replay_window=chosen, signal_replay=native_signals,
            visual_settings=motion.visual_settings, return_config=True,
            replay_extra=dict(operational_counts=result['counts'], pagination=dict(
                blocks=blocks, block_count=len(blocks), sample_rate=1.0, window_seconds=window_seconds,
                total_segments=stats['segments'], total_reconstructed_vehicles=stats['reconstructed_vehicles'],
                visual_vehicle_counts=dict(store.visual_vehicle_counts))))
        side = dict(signal_replay=native_signals.payload(), incidents=incidents)
        config['signal_replay'] = {**config['signal_replay'], 'series': [
            {**group, 'states': []} for group in config['signal_replay'].get('series', [])]}
        config['hud']['reconstructed_vehicles'] = stats['reconstructed_vehicles']
        config['visual_vehicle_counts'] = dict(store.visual_vehicle_counts)
        store.connection.commit()
    if sha256(directory / 'run-manifest.json') != expected['run_manifest_sha256']:
        raise ValueError('El manifiesto nativo cambio durante la exportacion')
    stat = database.stat()
    pending = dict(identity=expected, database_stat=[stat.st_size, stat.st_mtime_ns],
                   config=config, side_data=side, blocks=blocks, counts=stats, export_options=export_options)
    _checkpoint(checkpoint, pending, reserve_bytes)
    return publish_source(directory, database, contract, config, side, blocks, stats,
        iteration=selection['iteration'], provenance={'kind': 'single-event-extraction', 'export_options': export_options},
        reserve_bytes=reserve_bytes)
