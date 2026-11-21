"""Read-only recovery of native side data for an interrupted SimZ1 replay.

No function in this module reconstructs a trajectory or evaluates Motion_Plan.
The reusable cache belongs to the caller's temporary directory; failed cache
writes remain available for inspection and never replace a completed cache.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import uuid
from simz1_incident_replay import reject_uninstalled_native_incident


def _encoded(value):
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False)
    for chunk in encoder.iterencode(value):
        yield chunk.encode('utf-8')


def _signature(value):
    digest = hashlib.sha256()
    size = 0
    for chunk in _encoded(value):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _space(directory, required, reserve):
    free = shutil.disk_usage(directory).free
    if free < required + reserve:
        raise OSError(28, f'Espacio insuficiente para cache nativa en {directory}: '
                      f'{free:,} bytes libres; requiere {required + reserve:,}')


def _write_cache(path, envelope, reserve, *, max_cache_bytes=None):
    """Publish only a complete file; retain a partial file after every failure."""
    _, size = _signature(envelope)
    if max_cache_bytes is not None and size > max_cache_bytes:
        raise ValueError(f'Cache nativa excede el limite explicito de {max_cache_bytes} bytes')
    _space(path.parent, size, reserve)
    stage = path.with_name(path.name + '.partial.' + uuid.uuid4().hex)
    with stage.open('xb') as stream:
        buffer = bytearray()
        for chunk in _encoded(envelope):
            buffer.extend(chunk)
            if len(buffer) >= 1024 * 1024:
                _space(path.parent, len(buffer), reserve)
                stream.write(buffer)
                buffer.clear()
        if buffer:
            _space(path.parent, len(buffer), reserve)
            stream.write(buffer)
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        raise FileExistsError(f'La cache aparecio durante la recuperacion; se conserva {stage}')
    stage.rename(path)


def _network_geometry(path):
    # Identical endpoint projection to visualizador_z1.extraer_red(). The roads
    # HTML layer intentionally lacks IDs, so it cannot identify native links.
    from pyproj import Transformer
    from simz1_run import xml_elements
    transformer = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True)
    nodes = {e.get('id'): list(transformer.transform(float(e.get('x')), float(e.get('y')), errcheck=True))
             for e in xml_elements(path, 'node', 'network')}
    return {e.get('id'): {'from': nodes[e.get('from')], 'to': nodes[e.get('to')],
                          'length': float(e.get('length')),
                          'freespeed': float(e.get('freespeed')) if e.get('freespeed') is not None else None}
            for e in xml_elements(path, 'link', 'network')}


def _validate_payload(data, replay_config, native_result):
    if not isinstance(data, dict) or not isinstance(data.get('incidents'), list):
        raise ValueError('Cache nativa sin incidentes validos')
    signal = data.get('signal_replay')
    if not isinstance(signal, dict) or not isinstance(signal.get('series'), list):
        raise ValueError('Cache nativa sin series semaforicas validas')
    fields = ('event_count', 'state_counts', 'groups', 'groups_with_events',
              'permitted_decisions_by_state', 'duplicate_events')
    reference = replay_config.get('signal_replay', {})
    for key in fields:
        if key in reference and signal.get(key) != reference[key]:
            raise ValueError(f'Resumen semaforico diferente del bloque original: {key}')
    if not replay_config.get('trajectories_only', False):
        for key in fields:
            native = native_result.get('signal_events', {})
            if key in native and signal.get(key) != native[key]:
                raise ValueError(f'Resumen semaforico diferente de la corrida validada: {key}')


def recover_side_data(run_dir, manifest, iteration, config, temp_dir, identity, reserve_bytes, *, max_cache_bytes=None):
    """Recover full signals/incidents once, without recalculating movements.

    The event stream is hashed and read only when this function is explicitly
    called. A verified cache skips XML parsing on subsequent recovery attempts.
    All settings, source hashes and run identity participate in its signature.
    """
    from simz1_run import checked_path, sha256, xml_elements
    from simz1_signal_replay import EVENT_TYPE, SignalReplay, selected_groups

    directory = Path(run_dir).resolve()
    temporary = Path(temp_dir).resolve()
    if not temporary.is_dir():
        raise ValueError(f'El directorio temporal no existe: {temporary}')
    if not isinstance(reserve_bytes, int) or reserve_bytes < 0:
        raise ValueError('La reserva de espacio debe ser un entero no negativo')
    expected_identity = dict(run_id=manifest['run_id'], iteration=iteration,
                             run_manifest_sha256=sha256(directory / 'run-manifest.json'))
    if identity != expected_identity:
        raise ValueError('Identidad incompatible al recuperar series nativas')
    if manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('La recuperacion nativa requiere una corrida completed/valid')
    result = manifest['results'][str(iteration)]
    print('Recuperacion: verificando hashes de eventos y fuentes nativas; solo lectura', flush=True)
    events = checked_path(directory, result['events'])
    network = checked_path(directory, result['network'])
    checked_path(directory, manifest['effective_config'])
    links = _network_geometry(network)
    selection = dict(directory=directory, manifest=manifest, iteration=iteration)
    groups = selected_groups(selection, links)
    saved_groups = [{key: value for key, value in group.items() if key != 'states'}
                    for group in config.get('signal_replay', {}).get('series', [])]
    if groups != saved_groups:
        raise ValueError('Grupos semaforicos incompatibles con el bloque original')
    configuration_hash, _ = _signature(config)
    provenance = dict(identity=expected_identity, configuration_sha256=configuration_hash,
                      sources=dict(events=result['events'], network=result['network'],
                                   effective_config=manifest['effective_config'], inputs=manifest['inputs']))
    cache_key, _ = _signature(provenance)
    cache = temporary / ('simz1-native-side-data-' + cache_key + '.json')
    if cache.exists():
        if max_cache_bytes is not None and cache.stat().st_size > max_cache_bytes:
            raise ValueError(f'Cache nativa excede el limite explicito de {max_cache_bytes} bytes')
        try:
            envelope = json.loads(cache.read_text(encoding='utf-8'))
            content = envelope['content']
            actual_hash, _ = _signature(content)
            if (envelope.get('schema_version') != 1 or actual_hash != envelope['sha256'] or
                    content['provenance'] != provenance):
                raise ValueError('Hash o procedencia de cache incompatible')
            _validate_payload(content['data'], config, result)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f'Cache nativa incompleta/incompatible; se conserva: {cache}') from error
        print(f'Recuperacion: reutilizando cache nativa validada {cache}', flush=True)
        return content['data']

    _space(temporary, 1024 * 1024, reserve_bytes)
    signal_replay = SignalReplay(groups)
    incidents, open_incidents = [], {}
    use_signals = not config.get('trajectories_only', False)
    previous = -math.inf
    event_stat = events.stat()
    before = (event_stat.st_size, event_stat.st_mtime_ns)
    progress_time = time.monotonic()
    print('Recuperacion: leyendo eventos para senales/incidentes; sin reconstruir trayectorias', flush=True)
    for number, event in enumerate(xml_elements(events, 'event', 'events'), 1):
        attrs = event.attrib
        reject_uninstalled_native_incident(attrs)
        kind = attrs.get('type')
        # Inspect the clock only for relevant side-data observations. The source
        # hash ties all other events to the already validated native run.
        if kind == EVENT_TYPE or (kind == 'simz1NativeDecision' and attrs.get('reason') == 'turn_go'):
            if use_signals:
                signal_replay.add(attrs)
        elif kind in ('zona1IncidentStart', 'zona1IncidentRecovered'):
            observed = float(attrs['time'])
            if not math.isfinite(observed) or observed < previous:
                raise ValueError('Cronologia de incidentes nativos invalida')
            previous = observed
            link_id = attrs.get('link')
            if link_id not in links:
                raise ValueError(f'Incidente en enlace desconocido: {link_id}')
            speed = float(attrs['freespeedMps']) if 'freespeedMps' in attrs else None
            if speed is not None and not math.isfinite(speed):
                raise ValueError('Velocidad nativa de incidente no finita')
            if kind == 'zona1IncidentStart':
                if link_id in open_incidents:
                    raise ValueError('Incidente duplicado sin recuperacion')
                capacity = float(attrs['capacityPerHour'])
                if not math.isfinite(capacity):
                    raise ValueError('Capacidad nativa de incidente no finita')
                link = links[link_id]
                record = dict(incident=True, Link_ID=link_id, start=observed, end=None,
                              capacity=capacity, speed=None if speed is None else speed * 3.6,
                              position=[(a + b) / 2 for a, b in zip(link['from'], link['to'])], icon='crash')
                incidents.append(record)
                open_incidents[link_id] = record
            else:
                if link_id not in open_incidents:
                    raise ValueError('Recuperacion sin inicio compatible')
                open_incidents.pop(link_id)['end'] = observed
        if number % 100000 == 0 and time.monotonic() - progress_time >= 20:
            print(f'Recuperacion nativa: {number:,} eventos leidos; '
                  f'{signal_replay.event_count:,} senales; {len(incidents):,} incidentes', flush=True)
            progress_time = time.monotonic()
    after = events.stat()
    if before != (after.st_size, after.st_mtime_ns) or sha256(events) != result['events']['sha256']:
        raise ValueError('El archivo nativo cambio durante la lectura; no se publica cache')
    if sha256(directory / 'run-manifest.json') != expected_identity['run_manifest_sha256']:
        raise ValueError('El manifiesto nativo cambio durante la lectura; no se publica cache')
    data = dict(signal_replay=signal_replay.payload(), incidents=incidents)
    _validate_payload(data, config, result)
    content = dict(provenance=provenance, data=data)
    digest, _ = _signature(content)
    _write_cache(cache, dict(schema_version=1, sha256=digest, content=content), reserve_bytes,
                 max_cache_bytes=max_cache_bytes)
    return data


def derive_observation_probe(connection, observation_end):
    """Derive the original report's exact probe from immutable SQLite payloads."""
    from simz1_paged_replay import unpacked
    if not isinstance(observation_end, (int, float)) or not math.isfinite(observation_end):
        raise ValueError('Instante de observacion invalido')
    active, active_journeys = {}, set()
    for journey, start, end, segment_id, journey_order, raw in connection.execute(
            '''SELECT s.journey,s.start,s.end,s.id,j.rowid,s.payload
               FROM segments s JOIN journeys j ON j.key=s.journey
               WHERE s.start<=? AND s.end>?''',
            (observation_end, observation_end)):
        record = unpacked(raw)
        active_journeys.add(journey)
        previous = active.get(record['vehicle'])
        # finalize() visited journeys in insertion order, then each journey's
        # segments by (start,end,id), replacing equal-start observations. The
        # journeys rowid records that insertion order. Compare scalar keys in
        # Python so reproducing ties never creates a temporary BLOB sorter.
        order = (start, journey_order, end, segment_id)
        if previous is None or previous[0] <= order:
            active[record['vehicle']] = (order, record.get('Agent_ID'),
                                         record['Motion_Plan']['status'] != 'unavailable')
    censored = without_closed = without_active = 0
    for key, raw in connection.execute('SELECT key,metadata FROM journeys'):
        trip = json.loads(raw)
        if trip and trip.get('Status') == 'censored':
            censored += 1
            without_closed += connection.execute(
                'SELECT 1 FROM segments WHERE journey=? LIMIT 1', (key,)).fetchone() is None
            without_active += key not in active_journeys
    return dict(time_seconds=observation_end,
                vehicles_with_closed_interval_active=len(active),
                representable_vehicles=sum(value[2] for value in active.values()),
                visible_agents=len({value[1] for value in active.values() if value[2] and value[1] is not None}),
                unavailable_interval_vehicles=sum(not value[2] for value in active.values()),
                censored_journeys=censored, censored_without_any_closed_interval=without_closed,
                censored_without_closed_interval_at_observation_end=without_active,
                source='Exact native interval membership and exported Motion_Plan availability; no extrapolation; not browser FPS')
