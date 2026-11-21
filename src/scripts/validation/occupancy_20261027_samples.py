"""Bounded sample plan from one explicitly identified live replay; read-only.

Usage: python scripts/validation/occupancy_20261027_samples.py --url URL
       --run-id EXPECTED_NEW_RUN --output samples.json [--max-frames 100]
The output feeds occupancy_20261027_browser_audit.cjs. No historical run,
SQLite mutation, invented trajectory, or empirical calibration is involved.
"""
import argparse
import json
import math
from pathlib import Path
import time as monotonic_clock
import urllib.parse
import urllib.request


IDENTITY_FIELDS = ('run_id', 'iteration', 'run_manifest_sha256', 'source_version')
CATEGORIES = ('truck_wait', 'truck', 'bus_dwell', 'wait', 'boundary', 'motorcycle', 'car', 'bus')


def read_json(url):
    with urllib.request.urlopen(url, timeout=240) as response:
        raw = response.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError('Replay response exceeds the bounded 64 MiB sample budget')
    return json.loads(raw)


def checked_identity(value, expected):
    if any(value.get(field) != expected[field] for field in IDENTITY_FIELDS):
        raise ValueError('Sample source identity does not match the requested replay')


def spread(values, limit):
    if limit <= 0:
        return []
    if len(values) <= limit:
        return values
    return [values[(index * (len(values) - 1)) // (limit - 1)] for index in range(limit)] if limit > 1 else [values[len(values) // 2]]


def family_of(record, trips):
    family = record.get('Vehicle_Family')
    if family in ('car', 'motorcycle', 'bus', 'truck'):
        return family
    trip = record.get('Trip') or trips.get(record.get('Replay_Journey_Key'), {})
    transit = trip.get('Transit') or {}
    if transit.get('schema') == 'simz1-transit-replay-v1' and transit.get('vehicle_id') == record.get('vehicle'):
        return 'bus'
    name = str(record.get('Vehicle_Type') or record.get('Agent_Type') or record.get('Profile') or '').lower()
    if name in ('transportepesado', 'freighttruck', 'truck'):
        return 'truck'
    if 'moto' in name:
        return 'motorcycle'
    if name in ('car', 'normal', 'liebre', 'tortuga', 'carro'):
        return 'car'
    if name in ('transitbus', 'bus'):
        return 'bus'
    return 'unknown'


def sample_candidates(window, horizon):
    """Keep only native intervals and boundaries inside the returned window."""
    rows = window.get('segments', [])
    if len(rows) > 4096:
        raise ValueError('Sample window exceeds 4096 native segments; use a smaller replay window')
    lower = max(horizon['start_seconds'], window['start_seconds'])
    upper = min(horizon['end_seconds'], window['end_seconds'])
    pools = {category: [] for category in CATEGORIES}
    for row in rows:
        times = row.get('timestamps')
        if not isinstance(times, list) or len(times) != 2 or not all(type(t) in (int, float) and math.isfinite(t) for t in times):
            raise ValueError('Native interval has invalid timestamps')
        start, end = times
        if start >= end:
            continue
        inside_start, inside_end = max(start, lower), min(end, upper)
        if inside_start >= inside_end:
            continue
        family = family_of(row, window.get('trips', {}))
        plan, boundary = row.get('Motion_Plan') or {}, row.get('Boundary_Provenance') or {}
        dwell = family == 'bus' and plan.get('status') == 'stationary' and boundary.get('start') == 'VehicleArrivesAtFacility' and boundary.get('end') == 'VehicleDepartsAtFacility'
        base = dict(vehicle=row.get('vehicle'), link_id=row.get('Link_ID'), family=family,
                    native_interval=times, window_index=window['index'],
                    occupancy_policy=(row.get('Native_Occupancy') or {}).get('policy'))

        def add(category, at, reason):
            if category in pools and lower <= at < upper and start <= at < end:
                pools[category].append(dict(base, time=at, reason=reason, category=category))

        midpoint = (inside_start + inside_end) / 2
        add('bus_dwell' if dwell else family, midpoint, 'native_facility_dwell_midpoint' if dwell else 'native_active_interval_midpoint')
        hold = plan.get('hold_start')
        if hold is None:
            hold = plan.get('native_wait_boundary')
        if type(hold) in (int, float) and math.isfinite(hold):
            add('wait', max(inside_start, hold) + min(.001, (inside_end - max(inside_start, hold)) / 2), 'native_hold_boundary_after')
            if hold < inside_end:
                add('wait', (max(inside_start, hold) + inside_end) / 2, 'native_hold_midpoint')
                if family == 'truck':
                    add('truck_wait', (max(inside_start, hold) + inside_end) / 2, 'native_freight_hold_midpoint')
        # Sample both sides of service/native interval changes without assigning
        # an unobserved coordinate. Browser queries retain the native event times.
        for at, reason in ((start, 'native_interval_start'), (start + .001, 'native_interval_start_after'),
                           (end - .001, 'native_interval_end_before')):
            add('boundary', at, reason)
    for category, values in pools.items():
        pools[category] = spread(sorted(values, key=lambda row: (row['time'], str(row['vehicle']))), 32)
    return pools


def select_samples(pools, maximum):
    chosen, used = [], set()
    nonempty = [name for name in CATEGORIES if pools[name]]
    # Allocate a bounded quota BEFORE spreading each category over its complete
    # time range. Taking the first few items from a 100-item spread previously
    # audited only the early morning despite reading day-wide source windows.
    quotas = {name: maximum // len(nonempty) + (i < maximum % len(nonempty))
              for i, name in enumerate(nonempty)} if nonempty else {}
    ordered = {name: spread(sorted(pools[name], key=lambda row: (row['time'], str(row['vehicle']))), quotas[name])
               if quotas.get(name, 0) else [] for name in CATEGORIES}
    indexes = {name: 0 for name in CATEGORIES}
    while len(chosen) < maximum:
        progressed = False
        for name in CATEGORIES:
            while indexes[name] < len(ordered[name]):
                row = ordered[name][indexes[name]]
                indexes[name] += 1
                if row['time'] in used:
                    continue
                chosen.append(row); used.add(row['time']); progressed = True
                break
            if len(chosen) == maximum:
                break
        if not progressed:
            break
    remaining = {}
    for name in CATEGORIES:
        for row in pools[name]:
            if row['time'] not in used:
                remaining.setdefault(row['time'], row)
    chosen.extend(spread(sorted(remaining.values(), key=lambda row: row['time']), maximum-len(chosen)))
    return sorted(chosen, key=lambda row: row['time'])


def create_plan(url, run_id, maximum=100, max_windows=32):
    config = read_json(url.rstrip('/') + '/api/config')
    continuous = config['continuous']
    identity = {field: continuous[field] for field in IDENTITY_FIELDS}
    if identity['run_id'] != run_id:
        raise ValueError('Server run_id differs from --run-id; refusing to sample another run')
    horizon = config['replay_window']
    start, end = horizon['start_seconds'], horizon['end_seconds']
    seconds, count = continuous['window_seconds'], continuous['window_count']
    query = dict(identity, **horizon)
    hud = read_json(url.rstrip('/') + '/api/hud?' + urllib.parse.urlencode(query))
    checked_identity(hud, identity)
    freight = (hud.get('freight_transport') or {}).get('observed') or {}
    probes = []
    for expedition in freight.get('expeditions', []):
        departure, arrival = expedition.get('departure_seconds'), expedition.get('arrival_seconds')
        if type(departure) in (int, float) and type(arrival) in (int, float) and departure < arrival:
            probes.extend((departure + min(1, (arrival - departure) / 2), (departure + arrival) / 2))
    indexes = []
    for time in probes:
        if start <= time < end:
            index = min(count - 1, int((time - start) // seconds))
            if index not in indexes:
                indexes.append(index)
    indexes = spread(indexes, max_windows)
    ordinary = []
    for i in range(16):
        time = start + (end - start) * (i + .5) / 16
        index = min(count - 1, int((time - start) // seconds))
        if index not in indexes and index not in ordinary:
            ordinary.append(index)
    remaining = max_windows - len(indexes)
    if remaining:
        indexes.extend(spread(ordinary, remaining))
    pools = {name: [] for name in CATEGORIES}
    window_timings, truck_journeys, journey_probes = [], set(), []
    for index in indexes:
        tick = monotonic_clock.perf_counter()
        window = read_json(url.rstrip('/') + '/api/window?' + urllib.parse.urlencode(dict(identity, index=index)))
        checked_identity(window, identity)
        if window['index'] != index:
            raise ValueError('Server returned another window')
        for name, rows in sample_candidates(window, horizon).items():
            pools[name].extend(rows)
        truck_journeys.update(row['Replay_Journey_Key'] for row in window.get('segments', [])
                             if family_of(row,window.get('trips',{}))=='truck' and row.get('Replay_Journey_Key'))
        elapsed = monotonic_clock.perf_counter()-tick
        window_timings.append(dict(index=index,seconds=elapsed))
        print(json.dumps(dict(window_index=index,seconds=round(elapsed,3))),flush=True)
    if not pools['truck_wait']:
        # Entry/mid-trip windows may miss a short native red-light stop near the
        # end of a freight trip. Read at most12 already observed freight journeys
        # through the identity-checked API; never invent a wait to obtain a shot.
        for key in sorted(truck_journeys)[:12]:
            journey=read_json(url.rstrip('/')+'/api/journey?'+urllib.parse.urlencode(dict(identity,key=key)))
            checked_identity(journey,identity)
            if journey.get('key')!=key:raise ValueError('Server returned another freight journey')
            rows=journey.get('records',[])
            if len(rows)>4096:raise ValueError('Freight journey exceeds bounded4096 sample records')
            candidates=sample_candidates(dict(index=None,start_seconds=start,end_seconds=end,segments=rows),horizon)['truck_wait']
            for row in candidates:row['window_index']=min(count-1,int((row['time']-start)//seconds))
            pools['truck_wait'].extend(candidates)
            journey_probes.append(dict(key=key,records=len(rows),native_wait_candidates=len(candidates)))
            if candidates:break
    boundary_count = 2 if maximum >= 3 else 0
    samples = select_samples(pools, maximum-boundary_count)
    if not samples:
        raise ValueError('No native active samples were found in the bounded probes')
    if boundary_count:
        # Include the first and last replay windows even if no vehicle has an
        # eligible body at a boundary. These are clock probes, never fabricated
        # native vehicle intervals or claims of observed positions.
        samples.extend(dict(time=at, category='replay_boundary', reason=reason,
                            native_replay_window=[start,end])
                       for at,reason in ((start,'native_replay_start'),
                                         (math.nextafter(end,start),'native_replay_end_before'))
                       if at not in {sample['time'] for sample in samples})
        samples.sort(key=lambda row:row['time'])
    sampled_hours=sorted({int(row['time']//3600) for row in samples})
    required_hours=8 if maximum>=16 and end-start>=8*3600 else 1
    if len(sampled_hours)<required_hours:
        raise ValueError('Bounded native samples do not cover the required distinct clock hours')
    return dict(schema='simz1-native-occupancy-sample-plan-v1', identity=identity, replay_window=horizon,
                scope='Bounded samples from the explicitly requested replay; no global microscopic certificate',
                max_frames=maximum, max_windows=max_windows, windows_read=indexes,
                read_timeout_seconds=240, window_timings=window_timings,
                freight_wait_journey_probes=journey_probes, freight_wait_available=bool(pools['truck_wait']),
                coverage=dict(clock_hour_bins=sampled_hours,minimum_hour_bins=required_hours,
                              first_time_seconds=samples[0]['time'],last_time_seconds=samples[-1]['time'],
                              boundary_clock_probes=boundary_count),
                candidate_counts={name: len(rows) for name, rows in pools.items()},
                times=[row['time'] for row in samples], samples=samples)


def self_test():
    identity = dict(run_id='synthetic-only', iteration=0, run_manifest_sha256='a' * 64, source_version='b' * 64)
    checked_identity(dict(identity), identity)
    try:
        checked_identity(dict(identity, run_id='wrong'), identity)
    except ValueError:
        pass
    else:
        raise AssertionError('Wrong replay identity accepted')
    window = dict(index=0, start_seconds=0, end_seconds=120, segments=[
        dict(vehicle='truck', Link_ID='a', Vehicle_Family='truck', timestamps=[10, 90], Motion_Plan=dict(hold_start=60), Native_Occupancy=dict(policy='corridor-length-v1')),
        dict(vehicle='bus', Link_ID='b', Vehicle_Family='bus', timestamps=[20, 40], Motion_Plan=dict(status='stationary'),
             Boundary_Provenance=dict(start='VehicleArrivesAtFacility', end='VehicleDepartsAtFacility')),
        dict(vehicle='moto', Link_ID='c', Vehicle_Family='motorcycle', timestamps=[30, 80], Motion_Plan=dict(hold_start=50)),
        dict(vehicle='car', Link_ID='d', Vehicle_Family='car', timestamps=[40, 100], Motion_Plan={})])
    original = json.dumps(window, sort_keys=True)
    pools = sample_candidates(window, dict(start_seconds=0, end_seconds=120))
    selected = select_samples(pools, 100)
    assert {'truck_wait', 'truck', 'bus_dwell', 'wait', 'boundary', 'motorcycle', 'car'} <= {row['category'] for row in selected}
    assert len(selected) == len({row['time'] for row in selected})
    assert all(row['native_interval'][0] <= row['time'] < row['native_interval'][1] for row in selected)
    assert json.dumps(window, sort_keys=True) == original
    assert len(select_samples(pools, 3)) == 3
    wide = {name: [dict(time=100*i+j, vehicle=name, category=name) for i in range(300)]
            for j, name in enumerate(CATEGORIES)}
    full_day = select_samples(wide, 100)
    assert len(full_day) == 100 and len({row['time'] for row in full_day}) == 100
    for name in CATEGORIES:
        times = [row['time'] for row in full_day if row['category'] == name]
        assert min(times) < 10 and max(times) >= 29900
    assert len(select_samples(wide, 1)) == 1
    assert select_samples(wide, 0) == []
    from unittest.mock import patch
    from contextlib import redirect_stdout
    import io
    config=dict(continuous=dict(identity,window_seconds=120,window_count=1),
                replay_window=dict(start_seconds=0,end_seconds=120))
    def fixture_response(url):
        if '/api/config' in url:return config
        if '/api/hud?' in url:return dict(identity)
        return dict(window,**identity)
    with patch(__name__+'.read_json',side_effect=fixture_response),redirect_stdout(io.StringIO()):
        plan=create_plan('http://synthetic.invalid','synthetic-only',maximum=20)
    assert plan['times'][0]==0 and plan['times'][-1]==math.nextafter(120,0)
    assert len(plan['times'])<=20 and plan['window_timings'][0]['index']==0
    sparse_window=json.loads(json.dumps(window))
    sparse_window['segments'][0].update(Motion_Plan={},Replay_Journey_Key='c'*64)
    def journey_response(url):
        if '/api/journey?' in url:return dict(identity,key='c'*64,records=[window['segments'][0]])
        if '/api/window?' in url:return dict(sparse_window,**identity)
        return fixture_response(url)
    with patch(__name__+'.read_json',side_effect=journey_response),redirect_stdout(io.StringIO()):
        journey_plan=create_plan('http://synthetic.invalid','synthetic-only',maximum=20)
    assert journey_plan['freight_wait_available'] and len(journey_plan['freight_wait_journey_probes'])==1
    assert any(row.get('category')=='truck_wait' for row in journey_plan['samples'])
    print('PASS: synthetic sampler identity, native dwell/heavy/WAIT/four-family times, bounds, uniqueness and immutable inputs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-frames', type=int, default=100)
    parser.add_argument('--max-windows', type=int, default=32)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test(); return
    if not all((args.url, args.run_id, args.output)) or not 1 <= args.max_frames <= 100 or not 1 <= args.max_windows <= 32:
        parser.error('Require --url, --run-id, --output, 1-100 frames and 1-32 windows')
    plan = create_plan(args.url, args.run_id, args.max_frames, args.max_windows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), identity=plan['identity'], frames=len(plan['times']), windows=len(plan['windows_read']))))


if __name__ == '__main__':
    main()
