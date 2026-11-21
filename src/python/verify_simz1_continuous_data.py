"""Compare bounded local or HTTP windows with existing SQLite/native evidence.

No simulation, interpolation, native writes or all-journey decoding. Default
probes cover day start, adjacent windows and the inclusive 24:00 closing frame.
"""
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from simz1_continuous_replay import (ContinuousReplay, checked_source, connect,
                                   html_parts, identity, source_manifest_path)
from simz1_paged_replay import unpacked


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    # Verification must not disappear when Python is launched with -O.
    if not condition:
        raise ValueError(message)


def fetch(base, endpoint, query=None):
    request = Request(base.rstrip('/') + endpoint + ('?' + urlencode(query) if query else ''),
                      headers={'Accept-Encoding': 'gzip'})
    with urlopen(request, timeout=120) as response:
        raw = response.read()
        if response.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return json.loads(raw)


DEFAULT_TIMES = (0, 7 * 3600 + 48 * 60, 12 * 3600, 23 * 3600 + 59 * 60, 24 * 3600)


def verify(directory, base=None, times=DEFAULT_TIMES, *, offline=False):
    started = time.perf_counter()
    times = tuple(times)
    require(bool(times) and all(type(value) in (int, float) and math.isfinite(value) for value in times),
            'La verificacion requiere al menos un tiempo finito explicito')
    folder = Path(directory).resolve(strict=True)
    # HTTP success cannot certify an unfinished local export. Validate the
    # local commit marker, config hash and immutable source in both modes.
    local_replay = ContinuousReplay(folder)
    manifest = local_replay.manifest
    native_root, old, database = checked_source(manifest['source_directory'])
    expected_identity = identity(manifest)
    expected_transport = {**expected_identity, 'source_version': manifest['source_export_sha256']}
    require(identity(old) == expected_identity, 'Identidad de fuente incompatible')
    require(hashlib.sha256(source_manifest_path(native_root, old).read_bytes()).hexdigest() == manifest['source_export_sha256'],
            'Hash del contrato de fuente incompatible')
    replay = local_replay if offline else None
    if not offline and base is None:
        raise ValueError('Se requiere --url, o --offline para no usar servidor')
    config = json.loads(replay.config_raw) if offline else fetch(base, '/api/config')
    require(identity(config['continuous']) == expected_identity, 'Identidad de configuracion incompatible')
    require(config['continuous'] == local_replay.config['continuous'],
            'Contrato continuo servido incompatible con el export local completo')
    require(config.get('replay_source') == local_replay.config.get('replay_source'),
            'Fuente de replay servida incompatible con el export local completo')
    require(config['hud']['planned_persons'] == old['planned_persons'], 'Cantidad de agentes incompatible')
    continuous = config['continuous']
    for probe in times:
        if not continuous['start_seconds'] <= probe <= continuous['end_seconds']:
            raise ValueError(f'Probe {probe} is outside the served replay window')
    direct_side = None
    if old.get('source_type') == 'sqlite-direct-v1':
        from simz1_sqlite_source import load_side_data
        direct_side = load_side_data(native_root, old)
    report = {'identity': expected_transport, 'status': 'running', 'windows': [],
              'mode': 'offline' if offline else 'http',
              'export_commit_status': 'complete',
              'source_type': old.get('source_type', 'paged-html-v1'),
              'all_journeys_decoded': False,
              'scope': 'Bounded windows plus one full selected journey; no complete-run motion decoding'}
    with closing(connect(database)) as connection:
        native_total = old['counts']['segments'] if offline else connection.execute('SELECT COUNT(*) FROM segments').fetchone()[0]
        require(native_total == old['counts']['segments'] == config['continuous']['total_segments'], 'Cantidad de segmentos incompatible')
        report['native_segment_count'] = native_total
        report['native_segment_count_source'] = 'validated source manifest; not recounted' if offline else 'SQLite COUNT(*)'
        report['planned_persons'] = config['hud']['planned_persons']
        lane_count = None if offline else connection.execute('SELECT COUNT(*) FROM lane_events').fetchone()[0]
        has_lanes = bool(connection.execute('SELECT EXISTS(SELECT 1 FROM lane_events LIMIT 1)').fetchone()[0])
        report['native_lane_event_count'] = lane_count
        report['native_lane_events_present'] = has_lanes
        journey_key = None
        for probe in times:
            window_started = time.perf_counter()
            index = max(0, min(continuous['window_count'] - 1,
                              math.floor((probe-continuous['start_seconds']) / continuous['window_seconds'])))
            payload = replay.window(index) if offline else fetch(base, '/api/window', {**expected_transport, 'index': index})
            require(identity(payload) == expected_identity, 'Identidad de ventana incompatible')
            require(payload.get('source_version') == expected_transport['source_version'], 'Version de fuente de ventana incompatible')
            start, end = payload['start_seconds'], payload['end_seconds']
            expected_start = continuous['start_seconds'] + index * continuous['window_seconds']
            require((start, end) == (expected_start, min(continuous['end_seconds'], expected_start + continuous['window_seconds'])),
                    'Limites temporales de ventana incompatibles')
            require(payload['index'] == index and payload['sample_rate'] == 1, 'Indice o muestreo de ventana incompatible')
            query_end = math.nextafter(end, math.inf) if index == continuous['window_count'] - 1 else end
            original_blocks = [block for block in old['blocks']
                               if block['start_seconds'] < query_end and block['end_seconds'] > start]
            candidate_ids = set()
            for block in original_blocks:
                candidate_ids.update(row[0] for row in connection.execute(
                    'SELECT segment FROM segment_blocks WHERE block=?', (block['index'],)))
            if start <= 86400 < query_end:
                candidate_ids.update(old.get('closing_segment_ids', []))
            expected_records, expected_trips, vehicles = Counter(), {}, set()
            native_min, native_max = math.inf, -math.inf
            # Batches bound SQL variable count and native Python object lifetime.
            ordered_ids = sorted(candidate_ids)
            for offset in range(0, len(ordered_ids), 500):
                batch = ordered_ids[offset:offset + 500]
                query = 'SELECT s.start,s.end,s.journey,s.payload,j.metadata FROM segments s JOIN journeys j ON s.journey=j.key WHERE s.id IN (' + ','.join('?' for _ in batch) + ')'
                for row_start, row_end, key, raw, raw_trip in connection.execute(query, batch):
                    if not row_start < query_end or not (row_end > start or row_end == row_start and row_start >= start):
                        continue
                    record = unpacked(raw)
                    require(record['timestamps'] == [row_start, row_end], 'Tiempo del payload nativo incompatible con SQLite')
                    expected_records[fingerprint(record)] += 1
                    expected_trips[key] = json.loads(raw_trip)
                    vehicles.add(record['vehicle'])
                    native_min, native_max = min(native_min, row_start), max(native_max, row_end)
                    journey_key = journey_key or key
            actual_records = Counter(fingerprint(record) for record in payload['segments'])
            require(actual_records == expected_records, f'Native segment or Motion_Plan mismatch at {probe}')
            require(payload['trips'] == expected_trips, f'Native trip metadata mismatch at {probe}')
            native_groups, native_incidents = {}, Counter()
            if direct_side is not None:
                native_groups = {(group['system_id'], group['group_id']): group['states']
                                 for group in direct_side['signal_replay']['series']}
                native_incidents.update(fingerprint(event) for event in direct_side['incidents']
                    if event['start'] < query_end and (event['end'] is None or event['end'] > start))
            else:
                for number, block in enumerate(original_blocks):
                    parts = html_parts(native_root / 'blocks' / block['url'])
                    for group in parts['signal_replay']['series']:
                        key = (group['system_id'], group['group_id'])
                        states = native_groups.setdefault(key, [])
                        states.extend(event for event in group['states']
                                      if number == 0 or event[0] >= block['start_seconds'])
                    # Adjacent blocks duplicate overlap copies, but identical
                    # native incident occurrences retain their multiplicity.
                    native_incidents |= Counter(fingerprint(event) for event in parts['incidents']
                        if event['start'] < query_end and (event['end'] is None or event['end'] > start))
            for key, states in native_groups.items():
                previous = [event for event in states if event[0] < start]
                native_groups[key] = previous[-1:] + [event for event in states if start <= event[0] < query_end]
            actual_groups = {(group['system_id'], group['group_id']): group['states']
                             for group in payload['signal_replay']['series']}
            require(actual_groups == native_groups, f'Native signal order/predecessor mismatch at {probe}')
            require(Counter(fingerprint(event) for event in payload['incidents']) == native_incidents,
                    f'Native incidents mismatch at {probe}')
            lanes = []
            if has_lanes:
                for vehicle in vehicles:
                    row = connection.execute('SELECT seq,payload FROM lane_events WHERE vehicle=? AND time<? ORDER BY time DESC,seq DESC LIMIT 1', (vehicle, start)).fetchone()
                    if row:
                        lanes.append((row[0], unpacked(row[1])))
                for seq, raw in connection.execute('SELECT seq,payload FROM lane_events WHERE time>=? AND time<? ORDER BY time,seq', (start, query_end)):
                    event = unpacked(raw)
                    if event['vehicle'] in vehicles:
                        lanes.append((seq, event))
                lanes.sort(key=lambda row: (row[1]['time'], row[0]))
            require(payload['lane_replay']['events'] == [row[1] for row in lanes], f'Native lanes mismatch at {probe}')
            report['windows'].append({'probe_seconds': probe, 'index': index,
                'start_seconds': start, 'end_seconds': end,
                'segments': sum(expected_records.values()), 'journeys': len(expected_trips),
                'vehicles': len(vehicles), 'native_min_timestamp': native_min if expected_records else None,
                'native_max_timestamp': native_max if expected_records else None,
                'native_signal_groups': len(native_groups),
                'native_signal_events': sum(len(events) for events in native_groups.values()),
                'lane_events': len(lanes), 'incidents': sum(native_incidents.values()),
                'every_native_field_equal': True, 'signals_predecessor_and_order_equal': True,
                'elapsed_seconds': time.perf_counter() - window_started})
            print(f'PASS native fields/window {index}: {sum(expected_records.values()):,} segments, {len(native_groups)} signal groups', flush=True)
            del payload, expected_records, expected_trips, actual_records, candidate_ids, ordered_ids
        if journey_key:
            payload = replay.journey(journey_key) if offline else fetch(base, '/api/journey', {**expected_transport, 'key': journey_key})
            require(identity(payload) == expected_identity, 'Identidad de viaje seleccionado incompatible')
            require(payload.get('source_version') == expected_transport['source_version'], 'Version de fuente de viaje incompatible')
            trip = json.loads(connection.execute('SELECT metadata FROM journeys WHERE key=?', (journey_key,)).fetchone()[0])
            records = []
            rows = list(connection.execute('SELECT start,end,id,payload FROM segments WHERE journey=?', (journey_key,)))
            rows.sort(key=lambda row: row[:3])
            for _, _, _, raw in rows:
                record = unpacked(raw)
                record['Trip'] = trip
                records.append(record)
            require(payload['records'] == records and payload['trip'] == trip, 'Viaje seleccionado no conserva datos nativos')
            report['selected_journey'] = {'key': journey_key, 'segments': len(records),
                                          'complete_native_fields_and_order_equal': True}
        else:
            report['selected_journey'] = {'status': 'not_observed_in_requested_windows'}
    report['status'] = 'passed'
    report['elapsed_seconds'] = time.perf_counter() - started
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8766')
    parser.add_argument('--offline', action='store_true', help='Compara ventanas localmente; no abre servidor ni navegador')
    parser.add_argument('--output', type=Path, help='Informe opcional; omitir imprime JSON sin escribir archivos')
    parser.add_argument('--times', type=float, nargs='+', default=list(DEFAULT_TIMES))
    args = parser.parse_args()
    report = verify(args.directory, args.url, args.times, offline=args.offline)
    raw = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output is None:
        print(raw)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding='utf-8')
        print(f'Native integrity report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
