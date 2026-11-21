"""Export bounded, read-only replay windows for the offline frame inspector.

The input is the production ContinuousReplay payload, including every vehicle,
lane event, signal state and queue context in each requested window. Focus is
metadata for the report; it never filters the renderer's input. This does not
start a server/browser, replay MATSim or scan/hash the complete SQLite database.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path

from simz1_continuous_replay import ContinuousReplay


DEFAULT_REPLAY = Path('runtime/simz1-227187-direct/webgl-continuo')
# Source OSM node 579747165 belongs to Avenida Elena way 381667651 and
# 15 Calle way 406843605. This identifies the inspection area, not a new map.
FOCUS = dict(center=[-90.5227778, 14.6348508], radius_m=100,
             source='scenarios/zona1/map.osm', osm_node='579747165',
             osm_ways=['381667651', '406843605'], vehicle_ids=[])


def fingerprint(path):
    stat = path.stat()
    return dict(bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)


def read_budget(replay, index, max_rows, max_compressed_bytes):
    """Charge indexed metadata reads before decoding any movement payload."""
    start = replay.manifest['replay_window']['start_seconds'] + index * replay.manifest['window_seconds']
    end = min(replay.manifest['replay_window']['end_seconds'], start + replay.manifest['window_seconds'])
    indexes = replay.block_indexes(start, end)
    slots = ','.join('?' for _ in indexes)
    sql = f'''SELECT s.id,length(s.payload) FROM segments s
        WHERE s.id IN (SELECT segment FROM segment_blocks INDEXED BY segments_block
          WHERE block IN ({slots}))
        AND s.start<? AND (s.end>? OR (s.end=s.start AND s.start>=?))
        ORDER BY s.id LIMIT ?'''
    args = (*indexes, end, start, start, max_rows + 1)
    with closing(replay.connection()) as connection:
        rows = list(connection.execute(sql, args))
        query_plan = [row[3] for row in connection.execute('EXPLAIN QUERY PLAN ' + sql, args)]
        lane_count = connection.execute('''SELECT count(*) FROM
            (SELECT seq FROM lane_events INDEXED BY lanes_time WHERE time>=? AND time<? LIMIT ?)''',
            (start, end, max_rows + 1)).fetchone()[0]
    size = sum(row[1] for row in rows)
    if len(rows) > max_rows or lane_count > max_rows or size > max_compressed_bytes:
        raise ValueError('Requested window exceeds the offline inspection budget')
    return dict(index=index, start_seconds=start, end_seconds=end,
                movement_rows=len(rows), compressed_movement_bytes=size,
                temporal_lane_rows=lane_count, segment_query_plan=query_plan)


def native_frame_summary(config, window, time, focus=FOCUS):
    """Summarize native intervals independently of inferred body positions."""
    if not window['start_seconds'] <= time < window['end_seconds']:
        raise ValueError('Summary time lies outside the loaded window')
    active = [r for r in window['segments'] if r['timestamps'][0] <= time < r['timestamps'][1]]
    latest_lane = {}
    for event in window['lane_replay']['events']:
        if event['time'] <= time:
            latest_lane[event['vehicle']] = event
    cx, cy = focus['center']
    xscale = 6371008.8 * math.pi / 180 * math.cos(math.radians(cy))
    yscale = 6371008.8 * math.pi / 180

    def nearby(path):
        xy = [((p[0]-cx)*xscale, (p[1]-cy)*yscale) for p in path]
        for a, b in zip(xy, xy[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            denom = dx*dx+dy*dy
            fraction = max(0, min(1, -(a[0]*dx+a[1]*dy)/denom)) if denom else 0
            if math.hypot(a[0]+fraction*dx, a[1]+fraction*dy) <= focus['radius_m']:
                return True
        return False

    grouped = {}
    for row in active:
        if nearby(row['path']):
            grouped.setdefault(row['Link_ID'], []).append(row)
    density, selected = [], {}
    geometry = config.get('visual_lanes', {}).get('links', {})
    for link, rows in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        description = geometry.get(link, {})
        lane_counts = Counter()
        outside_queue = []
        for row in rows:
            lane = latest_lane.get(row['vehicle'])
            key = lane['lane'] if lane and lane['type'] == 'entered lane' and lane['link'] == link else 'unknown'
            lane_counts[key] += 1
            domain = native_queue_domain(description, key)
            station = raw_link_station(row, description.get('length_m'), time)
            if domain is not None and station is not None and not domain[0]-1e-7 <= station <= domain[1]+1e-7:
                outside_queue.append(dict(vehicle_id=row['vehicle'], lane_id=key,
                    native_lane_event=lane, raw_motion_station_m=station, native_queue_domain_m=domain,
                    scope='Unadjusted interpolation outside observed serial queue; not outside MATSim link'))
        holds = [r['Motion_Plan'].get('hold_start') for r in rows]
        holds = [h for h in holds if h is not None]
        density.append(dict(link_id=link, active_intervals=len(rows),
            unique_vehicle_ids=len({r['vehicle'] for r in rows}),
            length_m=description.get('length_m'), effective_lanes=description.get('num_lanes'),
            nominal_visual_lane_width_m=description.get('lane_width_m'),
            native_lane_occupancy=dict(lane_counts), native_lanes=description.get('native_lanes'),
            raw_motion_outside_observed_queue=len(outside_queue),
            queue_domain_mismatch_examples=outside_queue[:3],
            entry_range=[min(r['timestamps'][0] for r in rows), max(r['timestamps'][0] for r in rows)],
            exit_range=[min(r['timestamps'][1] for r in rows), max(r['timestamps'][1] for r in rows)],
            hold_range=[min(holds),max(holds)] if holds else None,
            observed_hold_active=sum(h <= time for h in holds)))
        if len(density) <= 4:
            for row in [rows[0], rows[len(rows)//2], rows[-1]]:
                selected[row['vehicle']] = row
    samples = []
    for row in selected.values():
        trip = window['trips'].get(row['Replay_Journey_Key'], {})
        samples.append(dict(vehicle_id=row['vehicle'], person_id=trip.get('Person_ID', row.get('Agent_ID')),
            trip_id=trip.get('Trip_ID'), time=time, link_id=row['Link_ID'],
            latest_native_lane_event=latest_lane.get(row['vehicle']),
            timestamps=row['timestamps'], vehicle_type=row.get('Vehicle_Type'), pcu=row.get('Vehicle_PCU'),
            motion_plan=row['Motion_Plan'], observed_waits=row.get('Observed_Waits'),
            boundary_provenance=row.get('Boundary_Provenance'),
            position_origin='inferred_from_native_link_boundaries_and_motion_plan_not_continuous_observation'))
    vehicles = Counter(r['vehicle'] for r in active)
    queue = window.get('queue_context') or {}
    return dict(time=time, scope='Native interval occupancy; not measured bodies, crashes or QSim geometric capacity',
        active_intervals=len(active), unique_vehicle_ids=len(vehicles),
        duplicate_active_vehicle_ids={k:v for k,v in vehicles.items() if v > 1},
        focus=focus, focus_active_intervals=sum(len(rows) for rows in grouped.values()),
        raw_motion_outside_observed_queue=sum(row['raw_motion_outside_observed_queue'] for row in density),
        density_by_link=density, samples=samples,
        queue_context_status=dict(Counter('complete' if v.get('complete') else v.get('reason', 'unknown')
                                         for v in queue.get('by_seed', {}).values())))


def native_queue_domain(description, lane_id):
    """MATSim LanesUtils ModelLane longitudinal domain, only when unambiguous.

    startsAtMeterFromLinkEnd measures backwards from the link's downstream end.
    An original lane ends where its immediate toLanes begin. That original
    queue is upstream storage, not another parallel lane across the whole link.
    """
    lanes = description.get('native_lanes') or {}
    lane = lanes.get(lane_id)
    length = description.get('length_m')
    if not lane or not isinstance(length, (int, float)) or not math.isfinite(length):
        return None
    start = lane.get('start_m')
    if not isinstance(start, (int, float)) or not math.isfinite(start):
        return None
    targets = lane.get('to_lanes') or []
    if targets:
        ends = [lanes.get(key, {}).get('start_m') for key in targets]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in ends):
            return None
        if max(ends)-min(ends) > 1e-7:
            return None
        end = ends[0]
    elif lane.get('to_links'):
        end = 0
    else:
        return None
    result = [length-start, length-end]
    return result if -1e-7 <= result[0] <= result[1] <= length+1e-7 else None


def raw_link_station(record, length, time):
    """Unadjusted Motion_Plan station in the recorded link, when supported."""
    if not isinstance(length, (int, float)) or not math.isfinite(length):
        return None
    boundary = record.get('Boundary_Provenance') or {}
    a, b = boundary.get('start_relative'), boundary.get('end_relative')
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in (a,b)):
        return None
    plan = record.get('Motion_Plan') or {}
    distance = plan.get('distance_m')
    if distance == 0:
        return a*length if a == b else None
    if not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < 0:
        return None
    for phase in plan.get('phases', []):
        if len(phase) >= 5 and phase[0] <= time <= phase[1]:
            dt = time-phase[0]
            station = phase[2]+phase[3]*dt+phase[4]*dt*dt/2
            return (a+(b-a)*station/distance)*length
    return None


def export(replay_dir, output_new, times, indexes=None, max_rows=200000,
           max_compressed_bytes=256 * 1024 * 1024):
    output_new = Path(output_new).resolve()
    if output_new.exists():
        raise FileExistsError(f'Inspection output already exists: {output_new}')
    if not times or any(not math.isfinite(t) for t in times):
        raise ValueError('Finite inspection timestamps are required')
    if max_rows < 1 or max_compressed_bytes < 1:
        raise ValueError('Positive offline inspection budgets are required')
    replay = ContinuousReplay(replay_dir)
    before = fingerprint(replay.database)
    start = replay.manifest['replay_window']['start_seconds']
    end = replay.manifest['replay_window']['end_seconds']
    if any(not start <= t < end for t in times):
        raise ValueError('Inspection timestamps must lie inside the replay')
    requested = indexes if indexes is not None else [
        int((t-start)//replay.manifest['window_seconds']) for t in times]
    selected = sorted(set(requested))
    if not selected or len(selected) > 3 or any(type(i) is not int or not 0 <= i < replay.manifest['window_count'] for i in selected):
        raise ValueError('Select one to three valid replay windows')
    if any(int((t-start)//replay.manifest['window_seconds']) not in selected for t in times):
        raise ValueError('Every inspection timestamp must have a requested window')
    budgets = [read_budget(replay, i, max_rows, max_compressed_bytes) for i in selected]
    windows = [replay.window(i) for i in selected]
    snapshots = []
    for t in times:
        window = next(w for w in windows if w['start_seconds'] <= t < w['end_seconds'])
        active = [r for r in window['segments'] if r['timestamps'][0] <= t < r['timestamps'][1]]
        vehicles = Counter(r['vehicle'] for r in active)
        snapshots.append(dict(time=t, active_segments=len(active), unique_vehicle_ids=len(vehicles),
            duplicate_active_vehicle_ids={k:v for k,v in vehicles.items() if v > 1},
            motion_status=dict(Counter(r['Motion_Plan'].get('status', 'unknown') for r in active)),
            position_observation='QSim link/lane boundary events; continuous body positions are inferred'))
    if fingerprint(replay.database) != before:
        raise ValueError('Historical SQLite changed during inspection')
    hud_query = {key:[str(value)] for key,value in replay.identity.items()}
    hud_query.update({key:[str(value)] for key,value in replay.manifest['replay_window'].items()})
    evidence = dict(schema='simz1-offline-frame-input-v1', config=replay.config, hud=replay.hud(hud_query),
        windows=windows, times=times, focus=FOCUS,
        provenance=dict(**replay.identity, replay_directory=str(replay.root), database=str(replay.database),
            # Nanosecond timestamps exceed JavaScript's safe integer range.
            # Keep comparisons above exact Python integers, but transport this
            # value as decimal text so the Node inspector cannot round it.
            database_fingerprint={**before, 'mtime_ns':str(before['mtime_ns'])},
            source_type=replay.source_manifest['source_type'],
            source_manifest_sha256=replay.manifest['source_export_sha256'],
            extractor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            scope='Complete production window payloads; immutable indexed SQLite reads; no full DB scan',
            budgets=budgets, active_native_intervals=snapshots))
    # No existing replay artifact is overwritten. The directory is the commit
    # boundary for this disposable inspection input, not a published replay.
    output_new.mkdir(parents=True, exist_ok=False)
    destination = output_new / 'frame-input.json'
    destination.write_text(json.dumps(evidence, separators=(',', ':'), allow_nan=False)+'\n', encoding='utf-8')
    summaries = [native_frame_summary(replay.config,
        next(w for w in windows if w['start_seconds'] <= t < w['end_seconds']), t) for t in times]
    (output_new/'native-summary.json').write_text(json.dumps(dict(provenance=evidence['provenance'],frames=summaries),
        indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return dict(output=str(destination), bytes=destination.stat().st_size,
                budgets=budgets, active_native_intervals=snapshots)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-dir', type=Path, default=DEFAULT_REPLAY)
    parser.add_argument('--output-new', type=Path, required=True)
    parser.add_argument('--time', type=float, action='append', dest='times')
    parser.add_argument('--window', type=int, action='append', dest='indexes')
    args = parser.parse_args(argv)
    result = export(args.replay_dir, args.output_new, args.times or [28987.0], args.indexes)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
