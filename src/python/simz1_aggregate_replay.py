"""Native link association and origin demand; deliberately contains no positions.

Build explicitly from a completed, pinned SQLite replay and native day census.
Neither startup nor a time query scans the original replay/events. Intervals
describe link membership, not body occupancy, speed, queue location or deadlock.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

VERSION = 'native-aggregate-link-association-v1'
IDENTITY = ('run_id', 'iteration', 'run_manifest_sha256', 'source_version')
FAMILIES = ('carro', 'moto', 'pesado', 'bus')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def pin(path, sha=None):
    path = Path(path).resolve(strict=True)
    st = path.stat()
    return dict(path=str(path), bytes=st.st_size, mtime_ns=st.st_mtime_ns,
                ctime_ns=st.st_ctime_ns, sha256=sha or digest(path))


def number(value, nullable=True):
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not a native time')
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid native time')
    return value


class HashReader(io.RawIOBase):
    def __init__(self, stream):
        self.stream, self.hasher = stream, hashlib.sha256()
    def readable(self):
        return True
    def readinto(self, target):
        data = self.stream.read(len(target))
        self.hasher.update(data)
        target[:len(data)] = data
        return len(data)


def census_rows(path, expected_hash, expected):
    """Single decompression pass; hash compressed bytes as they are consumed."""
    with Path(path).open('rb') as raw:
        hashed = HashReader(raw)
        with gzip.GzipFile(fileobj=io.BufferedReader(hashed)) as zipped:
            with io.TextIOWrapper(zipped, encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if any(row.get(key) != expected[key] for key in ('run_id', 'iteration')):
                        raise ValueError('Native census identity differs')
                    yield row
        if hashed.hasher.hexdigest() != expected_hash:
            raise ValueError('Native census hash differs')


def validate_census_report(report, native, expected):
    if (report.get('run_id') != expected['run_id'] or report.get('iteration') != expected['iteration'] or
            report.get('manifest_sha256') != expected['run_manifest_sha256'] or
            report.get('census') != native['results'][str(expected['iteration'])]['day_observation']['census']):
        raise ValueError('Native census report provenance differs from run manifest')


def check_pins(items):
    for item in items:
        path = Path(item['path'])
        st = path.stat()
        if (st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (item['bytes'], item['mtime_ns'], item['ctime_ns']):
            raise ValueError('Aggregate pinned source changed: ' + path.name)
        for suffix in ('-wal', '-shm', '-journal'):
            companion = Path(str(path) + suffix)
            if path.suffix == '.sqlite' and companion.exists() and companion.stat().st_size:
                raise ValueError('Aggregate source database has an active journal')
        # Large immutable files use the full-hash publication receipt and file
        # identity; a time request does not hash multi-GB databases again.
        if path.suffix == '.json' and digest(path) != item['sha256']:
            raise ValueError('Aggregate source identity content changed')


def create_schema(db):
    db.executescript('''
        CREATE TABLE identity(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE trips(id TEXT PRIMARY KEY,vehicle TEXT NOT NULL,family TEXT NOT NULL,
          origin TEXT,scheduled REAL NOT NULL,requested REAL,entered REAL,arrival REAL,
          exited REAL,retired REAL,journey TEXT UNIQUE);
        CREATE TABLE raw_presence(journey TEXT NOT NULL,link TEXT NOT NULL,start REAL NOT NULL,
          end REAL NOT NULL,entry_observed INTEGER NOT NULL,leave_observed INTEGER NOT NULL);
        CREATE TABLE deltas(link TEXT,family TEXT,time REAL,delta INTEGER,entry INTEGER,leave INTEGER);
        CREATE TABLE series(link TEXT,family TEXT,time REAL,count INTEGER,last_change REAL,
          latest_entry REAL,latest_leave REAL,entries INTEGER,leaves INTEGER,
          link_enters INTEGER,link_leaves INTEGER,PRIMARY KEY(link,family,time));
        CREATE TABLE link_families(link TEXT,family TEXT,PRIMARY KEY(link,family));
        ''')


def populate(db, rows, journeys, segments, expected, horizon, progress=None):
    """Streaming native adapters; tests exercise the same builder as publication."""
    create_schema(db)
    db.executemany('INSERT INTO identity VALUES(?,?)',
                   [(k, encode(expected[k])) for k in IDENTITY] + [('version', encode(VERSION))])
    counts, bus_routes, seen_journeys, journey_bounds = Counter(), {}, set(), {}
    for row in rows:
        family = row['family']
        if family not in FAMILIES or row.get('cut_seconds') != horizon:
            raise ValueError('Unsupported census family/cut')
        times = [number(row.get(k), k != 'scheduled_departure') for k in
                 ('scheduled_departure', 'departure', 'traffic_entry', 'arrival', 'traffic_exit',
                  'abort_before_cleanup')]
        scheduled, requested, entered, arrival, exited, retired = times
        if scheduled >= horizon or any(v is not None and v > horizon for v in times[1:]):
            raise ValueError('Census event outside observation')
        if (requested is not None and requested < scheduled or
                entered is not None and (requested is None or entered < requested) or
                arrival is not None and (entered is None or arrival < entered) or
                exited is not None and (entered is None or exited < entered)):
            raise ValueError('Census chronology differs from native lifecycle')
        od = row.get('od') or {}
        if isinstance(od, str):
            od = json.loads(od) if od else {}
        origin = od.get('origin_link')
        if origin is None and od:
            candidates = {item.get('origin_link') for item in od.values() if isinstance(item, dict)}
            if len(candidates) == 1:
                origin = next(iter(candidates))
        db.execute('INSERT INTO trips VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',
                   (row['trip_id'], row['vehicle_id'], family, origin, *times))
        counts['scheduled_' + family] += 1
    db.execute('CREATE INDEX trip_vehicle_request ON trips(vehicle,requested)')
    for key, trip in journeys:
        transit, freight = trip.get('Transit') or {}, trip.get('Freight') or {}
        if transit:
            trip_id = 'bus:' + ':'.join(transit[k] for k in ('line_id', 'route_id', 'departure_id'))
        elif freight:
            trip_id = freight['vehicle_id']
        else:
            trip_id = trip['Trip_ID']
            # The native day census identifies a private actor, whereas the
            # replay uses an episode Trip_ID. Match the actual person/request,
            # requiring uniqueness; never truncate a string to guess identity.
            if db.execute('SELECT 1 FROM trips WHERE id=?', (trip_id,)).fetchone() is None:
                matches = db.execute('SELECT id FROM trips WHERE vehicle=? AND requested=?',
                                     (trip.get('Person_ID'), trip.get('Departure'))).fetchall()
                if len(matches) != 1:
                    raise ValueError('Replay private episode is not uniquely mapped to census')
                trip_id = matches[0][0]
        record = db.execute('SELECT vehicle,family,origin,requested,entered,arrival,exited,retired FROM trips WHERE id=?',
                            (trip_id,)).fetchone()
        if record is None:
            raise ValueError('Replay journey absent from complete native census: ' + trip_id)
        vehicle, family, origin, requested, entered, arrival, exited, retired = record
        if (requested, entered, arrival) != (trip.get('Departure'), trip.get('Traffic_Entry'), trip.get('Arrival')):
            raise ValueError('Replay/census lifecycle mismatch: ' + trip_id)
        if key in seen_journeys:
            raise ValueError('Duplicate journey')
        seen_journeys.add(key)
        journey_bounds[key] = (family, entered,
            min((v for v in (arrival,exited,retired) if v is not None), default=math.nextafter(horizon,math.inf)))
        links = (transit.get('route_links') or freight.get('route_link_ids') or
                 (trip.get('OD') or {}).get('route_link_ids') or [])
        resolved_origin = (trip.get('OD') or {}).get('origin_link') or (links[0] if links else None)
        if origin and resolved_origin and origin != resolved_origin:
            raise ValueError('Replay/census origin mismatch')
        origin = origin or resolved_origin
        if transit and origin:
            route_key = (transit['line_id'], transit['route_id'])
            if route_key in bus_routes and bus_routes[route_key] != origin:
                raise ValueError('Bus route origin is not unique')
            bus_routes[route_key] = origin
        db.execute('UPDATE trips SET journey=?,origin=? WHERE id=?', (key, origin, trip_id))
        for tail in trip.get('Unrepresented_Traffic_Intervals', []):
            start, end = number(tail['start'], False), number(tail['end'], False)
            inclusive = trip.get('Status') == 'censored' and end == horizon
            native_start = tail.get('presence_source') in ('vehicle enters traffic', 'entered link',
                'VehicleArrivesAtFacility', 'VehicleDepartsAtFacility')
            if not native_start or end < start or end > horizon or tail.get('vehicle') != vehicle:
                raise ValueError('Unsupported unrepresented native interval')
            if inclusive:
                end = math.nextafter(end, math.inf)
            if end > start:
                entry_flag = {'vehicle enters traffic':1,'entered link':2}.get(tail['presence_source'],0)
                db.execute('INSERT INTO raw_presence VALUES(?,?,?,?,?,?)',
                           (key, tail['link'], start, end, entry_flag, 0))
                if entry_flag:
                    db.execute('INSERT INTO deltas VALUES(?,?,?,?,?,?)',
                               (tail['link'], family, start, 0, entry_flag, 0))
                counts['unrepresented_native_tails'] += 1
        counts['journeys'] += 1
    # Scheduled bus expeditions have no replay journey until an actual departure.
    # Only an exact line/route observed in metadata supplies their origin.
    for trip_id, in db.execute("SELECT id FROM trips WHERE family='bus' AND origin IS NULL").fetchall():
        parts = trip_id.split(':')
        if len(parts) == 4 and parts[0] == 'bus':
            origin = bus_routes.get((parts[1], parts[2]))
            if origin:
                db.execute('UPDATE trips SET origin=? WHERE id=?', (origin, trip_id))
    if db.execute('SELECT count(*) FROM trips WHERE requested IS NOT NULL AND journey IS NULL').fetchone()[0]:
        raise ValueError('Requested census trips missing from replay metadata')
    db.commit()
    for key, payload in segments:
        if key not in seen_journeys:
            raise ValueError('Segment belongs to unknown journey')
        row = json.loads(zlib.decompress(payload)) if isinstance(payload, bytes) else payload
        boundary = row.get('Boundary_Provenance') or {}
        if boundary.get('start') not in ('vehicle enters traffic', 'entered link', 'native_queue_exit_observed',
                                         'VehicleArrivesAtFacility', 'VehicleDepartsAtFacility'):
            counts['excluded_non_native_association_segments'] += 1
            continue
        start, end = [number(t, False) for t in row['timestamps']]
        if end < start or end > horizon:
            raise ValueError('Invalid replay native interval')
        family, entered, terminal = journey_bounds[key]
        if entered is None or start < entered or end > terminal:
            raise ValueError('Native boundary outside traffic lifetime')
        # A final observation boundary retains association at the pre-cleanup cut.
        end_event = boundary.get('end')
        entry_flag = {'vehicle enters traffic':1, 'entered link':2}.get(boundary['start'],0)
        leave_flag = {'left link':1, 'vehicle leaves traffic':2, 'arrival':3}.get(end_event,0)
        if entry_flag or leave_flag:
            if entry_flag:
                db.execute('INSERT INTO deltas VALUES(?,?,?,?,?,?)', (row['Link_ID'],family,start,0,entry_flag,0))
            if leave_flag:
                db.execute('INSERT INTO deltas VALUES(?,?,?,?,?,?)', (row['Link_ID'],family,end,0,0,leave_flag))
        if end == horizon and end_event in ('observation_end', 'event_stream_observation_end'):
            end = math.nextafter(end, math.inf)
        if end > start:
            db.execute('INSERT INTO raw_presence VALUES(?,?,?,?,?,?)',
                       (key, row['Link_ID'], start, end,
                        entry_flag, leave_flag))
        counts['segments_read'] += 1
        if counts['segments_read'] % 100000 == 0:
            db.commit()
            if progress:
                progress(dict(stage='segments', count=counts['segments_read']))
    db.commit()
    previous_vehicle, previous_journey, latest_end = None, None, None
    for vehicle, journey, start, end, entered, exited, retired, arrival in db.execute('''
        SELECT t.vehicle,p.journey,p.start,p.end,t.entered,t.exited,t.retired,t.arrival
        FROM raw_presence p JOIN trips t ON t.journey=p.journey ORDER BY t.vehicle,p.start,p.end'''):
        terminal = min((v for v in (exited, retired, arrival) if v is not None), default=math.nextafter(horizon, math.inf))
        if entered is None or start < entered or end > terminal:
            raise ValueError('Association interval outside native traffic lifetime')
        if vehicle == previous_vehicle and journey != previous_journey and start < latest_end:
            raise ValueError('Physical vehicle belongs to overlapping journeys')
        if vehicle != previous_vehicle or latest_end is None or end >= latest_end:
            previous_vehicle, previous_journey, latest_end = vehicle, journey, end
    # Merge split queue-head intervals before counting; no duplicate body/person.
    pending = None
    def flush(record):
        if record is None:
            return
        journey, link, start, end, entry, leave, family = record
        db.execute('INSERT INTO deltas VALUES(?,?,?,?,?,?)', (link, family, start, 1, 0, 0))
        if end <= horizon:
            db.execute('INSERT INTO deltas VALUES(?,?,?,?,?,?)', (link, family, end, -1, 0, 0))
        counts['native_association_intervals'] += 1
    cursor = db.execute('''SELECT p.journey,p.link,p.start,p.end,p.entry_observed,p.leave_observed,t.family
          FROM raw_presence p JOIN trips t ON t.journey=p.journey ORDER BY p.journey,p.start,p.end''')
    for record in cursor:
        if pending and record[0] == pending[0]:
            if (record[1] == pending[1] and record[2] <= pending[3]
                    and (record[2] < pending[3] or record[4] == 0)):
                if record[3] >= pending[3]:
                    pending = (*pending[:3], record[3], pending[4], record[5], pending[6])
                continue
            if record[2] < pending[3]:
                raise ValueError('Overlapping native association on different links')
        flush(pending)
        pending = record
    flush(pending)
    db.executescript('''
      INSERT INTO series
      SELECT link,family,time,
        SUM(delta) OVER(PARTITION BY link,family ORDER BY time),
        MAX(CASE WHEN delta<>0 OR entry>0 OR leave>0 THEN time END) OVER(PARTITION BY link,family ORDER BY time),
        MAX(CASE WHEN entry>0 THEN time END) OVER(PARTITION BY link,family ORDER BY time),
        MAX(CASE WHEN leave>0 THEN time END) OVER(PARTITION BY link,family ORDER BY time),
        SUM(entry) OVER(PARTITION BY link,family ORDER BY time),
        SUM(leave) OVER(PARTITION BY link,family ORDER BY time),
        SUM(link_enter) OVER(PARTITION BY link,family ORDER BY time),
        SUM(link_leave) OVER(PARTITION BY link,family ORDER BY time)
      FROM (SELECT link,family,time,SUM(delta) delta,SUM(entry>0) entry,SUM(leave>0) leave,
          SUM(entry=2) link_enter,SUM(leave=1) link_leave
        FROM deltas GROUP BY link,family,time);
      INSERT INTO link_families SELECT DISTINCT link,family FROM series;
      CREATE INDEX trips_origin ON trips(origin,family);
      DROP TABLE raw_presence;
      DROP TABLE deltas;
      ''')
    if db.execute('SELECT count(*) FROM series WHERE count<0').fetchone()[0]:
        raise ValueError('Negative association stock')
    counts['unknown_origin_trips'] = db.execute('SELECT count(*) FROM trips WHERE origin IS NULL').fetchone()[0]
    counts['links'] = db.execute('SELECT count(DISTINCT link) FROM link_families').fetchone()[0]
    db.commit()
    return dict(counts)


def build(source_directory, output, progress=None):
    """Explicit offline publication; original source files remain immutable."""
    from simz1_sqlite_source import checked_source, readonly_database, FILE_NAME, DEFAULT_RESERVE_BYTES
    from simz1_recovery_io import preflight_storage, atomic_json_preserve
    started = time.perf_counter()
    producer_sha256 = digest(__file__)
    source_directory, output = Path(source_directory).resolve(), Path(output).resolve()
    source_root, source, database = checked_source(source_directory)
    source_path = source_root / FILE_NAME
    expected = {key: source[key] for key in IDENTITY[:3]}
    expected['source_version'] = digest(source_path)
    if source.get('sample_rate') != 1 or source.get('status') != 'complete':
        raise ValueError('Aggregate requires complete unsampled replay')
    run_directory = Path(source['run_directory'])
    native_path = run_directory / 'run-manifest.json'
    if digest(native_path) != expected['run_manifest_sha256']:
        raise ValueError('Native run manifest changed')
    report_path = run_directory / 'analysis' / ('it.' + str(expected['iteration'])) / 'balanced-launch/report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    validate_census_report(report, json.loads(native_path.read_text(encoding='utf-8')), expected)
    census_path = run_directory / report['census']['path']
    horizon = source['replay_window']['end_seconds']
    source_pins = [pin(source_path), pin(native_path), pin(report_path),
                  pin(census_path, report['census']['sha256']), pin(database, source['database_sha256'])]
    preflight_storage(output, source['counts']['segments']*2048, DEFAULT_RESERVE_BYTES, probe_write=True)
    output.mkdir(parents=True, exist_ok=True)
    target, manifest_path = output / 'aggregate.sqlite', output / 'aggregate-manifest.json'
    if target.exists() or manifest_path.exists():
        raise FileExistsError('Preserve existing aggregate; choose a new instance')
    source_connection = readonly_database(database, expected)
    try:
        with sqlite3.connect(target) as db:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('PRAGMA cache_size=-32768')
            counts = populate(db, census_rows(census_path, report['census']['sha256'], expected),
                ((key, json.loads(metadata)) for key, metadata in source_connection.execute('SELECT key,metadata FROM journeys')),
                source_connection.execute('SELECT journey,payload FROM segments ORDER BY id'), expected, horizon, progress)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Aggregate SQLite quick_check failed')
    finally:
        source_connection.close()
    check_pins(source_pins)
    manifest = dict(schema_version=1, version=VERSION, status='complete', identity=expected,
        producer_sha256=producer_sha256,
        replay_window=source['replay_window'], no_positions=True, counts=counts,
        database=pin(target), sources=source_pins,
        wall_seconds=time.perf_counter()-started,
        semantics=['Native link association is not body occupancy or position.',
                   'Departure request differs from traffic entry.',
                   'Bus counts are expeditions; active link associations refer to vehicles in traffic.',
                   'Intervals are start-inclusive/end-exclusive; censored tails include the pre-cleanup cut.',
                   'Missing association remains unknown; it is never placed on an invented link.'])
    atomic_json_preserve(manifest_path, manifest, reserve_bytes=DEFAULT_RESERVE_BYTES, overwrite=False)
    return manifest


class AggregateReplay:
    def __init__(self, directory, expected_identity):
        self.root = Path(directory).resolve()
        self.path = self.root / 'aggregate-manifest.json'
        self.manifest_hash = digest(self.path)
        self.manifest = json.loads(self.path.read_text(encoding='utf-8'))
        m = self.manifest
        if (m.get('schema_version') != 1 or m.get('version') != VERSION or m.get('status') != 'complete'
                or any(m.get('identity', {}).get(key) != expected_identity.get(key) for key in IDENTITY)):
            raise ValueError('Aggregate identity/version mismatch')
        self.identity = dict(expected_identity)
        self.database = Path(m['database']['path'])
        if self.database.resolve() != self.root / 'aggregate.sqlite':
            raise ValueError('Aggregate database is outside its instance')
        self.check_source_files()
        with closing(self.connection()) as db:
            actual = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM identity')}
        if actual != {**m['identity'], 'version': VERSION}:
            raise ValueError('Aggregate SQLite identity mismatch')

    def connection(self):
        db = sqlite3.connect(self.database.as_uri() + '?mode=ro&immutable=1', uri=True)
        db.execute('PRAGMA query_only=ON')
        return db

    def check_source_files(self):
        if digest(self.path) != self.manifest_hash:
            raise ValueError('Aggregate manifest changed')
        check_pins([self.manifest['database'], *self.manifest['sources']])

    def metadata(self):
        return dict(schema_version=1, version=VERSION, no_positions=True,
            producer_sha256=self.manifest.get('producer_sha256'), manifest_sha256=self.manifest_hash,
            database_sha256=self.manifest['database']['sha256'],
            replay_window=self.manifest['replay_window'], counts=self.manifest['counts'],
            origin_scope='all_census_origins; private and freight separate; unknown origins explicit',
            position_available=False, time_semantics='state after native events at requested time; pre-cleanup at cut')

    def snapshot(self, requested_time):
        self.check_source_files()
        t = number(requested_time, False)
        window = self.manifest['replay_window']
        if not window['start_seconds'] <= t <= window['end_seconds']:
            raise ValueError('Aggregate time outside native coverage')
        with closing(self.connection()) as db:
            origins = []
            groups = defaultdict(list)
            for origin, family, scheduled, requested, entered, arrival, exited, retired in db.execute(
                    'SELECT origin,family,scheduled,requested,entered,arrival,exited,retired FROM trips'):
                groups[(origin, family)].append((scheduled, requested, entered, arrival, exited, retired))
            totals = {family: Counter() for family in FAMILIES}
            for (origin, family), rows in sorted(groups.items(), key=lambda x: (x[0][0] or '', x[0][1])):
                record = dict(origin_link=origin, family=family, scheduled_total=len(rows), scheduled_due=0,
                    requested=0, entered=0, waiting_admission=0, arrived=0, active_origin_cohort=0,
                    active_in_traffic=0, retired_before_arrival=0, retired_waiting=0,
                    oldest_pending_request=None, latest_entry=None,
                    hourly=[dict(hour=h, scheduled=0, requested=0, entered=0, arrived=0,
                                 waiting_admission_end=None, as_of_seconds=min(t,(h+1)*3600),
                                 end_inclusive=t<(h+1)*3600 or (h+1)*3600>=window['end_seconds'])
                            for h in range(math.ceil(window['end_seconds']/3600))],
                    coverage=dict(origin_known=origin is not None, position_available=False, time_seconds=t,
                                  lifecycle='complete_native_census', first_insertion_attempt='unavailable'))
                for scheduled, request, entry, arrival, exited, retired in rows:
                    values = [('scheduled', scheduled), ('requested', request), ('entered', entry), ('arrived', arrival)]
                    for name, value in values:
                        if value is not None and value <= t:
                            record['hourly'][min(int(value//3600), len(record['hourly'])-1)][name] += 1
                    record['scheduled_due'] += scheduled <= t
                    record['requested'] += request is not None and request <= t
                    record['entered'] += entry is not None and entry <= t
                    record['arrived'] += arrival is not None and arrival <= t
                    is_retired = retired is not None and retired <= t
                    waiting = request is not None and request <= t and (entry is None or entry > t) and not is_retired
                    active = entry is not None and entry <= t and (arrival is None or arrival > t) and not is_retired
                    record['waiting_admission'] += waiting
                    record['active_origin_cohort'] += active
                    record['active_in_traffic'] += active and (exited is None or exited > t)
                    record['retired_before_arrival'] += is_retired and (arrival is None or arrival > t)
                    record['retired_waiting'] += is_retired and request is not None and request<=t and (entry is None or entry>t)
                    if waiting:
                        previous = record['oldest_pending_request']
                        record['oldest_pending_request'] = request if previous is None else min(previous, request)
                    if entry is not None and entry <= t:
                        previous = record['latest_entry']
                        record['latest_entry'] = entry if previous is None else max(previous, entry)
                record['no_request_due'] = record['scheduled_due'] - record['requested']
                for hourly in record['hourly']:
                    if hourly['hour']*3600 <= t:
                        cutoff = hourly['as_of_seconds']
                        # Last native instant of completed half-open hours; at the
                        # requested instant and final horizon the boundary is inclusive.
                        if not hourly['end_inclusive']:
                            cutoff = math.nextafter(cutoff, -math.inf)
                        hourly['waiting_admission_end'] = sum(request is not None and request<=cutoff and
                            (entry is None or entry>cutoff) and (retired is None or retired>cutoff)
                            for _,request,entry,_,_,retired in rows)
                record['pending_wait_seconds_oldest'] = None if record['oldest_pending_request'] is None else t-record['oldest_pending_request']
                for key in ('scheduled_total','scheduled_due','requested','entered','waiting_admission','arrived',
                            'active_origin_cohort','active_in_traffic','retired_before_arrival','retired_waiting','no_request_due'):
                    totals[family][key] += record[key]
                origins.append(record)
            links, associated = {}, Counter()
            query = '''SELECT s.link,s.family,s.count,s.last_change,s.latest_entry,s.latest_leave,
                s.entries,s.leaves,s.link_enters,s.link_leaves
              FROM link_families f CROSS JOIN series s ON s.link=f.link AND s.family=f.family
              AND s.time=(SELECT max(time) FROM series x WHERE x.link=f.link AND x.family=f.family AND x.time<=?)'''
            for link, family, count, change, entry, leave, entries, leaves, link_enters, link_leaves in db.execute(query, (t,)):
                record = links.setdefault(link, dict(link_id=link, active_count=0, families={f:0 for f in FAMILIES},
                    last_change_time=None, latest_entry=None, latest_leave=None, time_since_change=None,
                    entry_count=0, leave_count=0, native_link_enter_count=0, native_link_leave_count=0,
                    entry_families={f:0 for f in FAMILIES}, leave_families={f:0 for f in FAMILIES},
                    coverage=dict(time_seconds=t, position_available=False, basis='native_link_membership_intervals',
                                  absent_associations='reported_in_global_coverage',
                                  count_kind='membership: traffic entry or LinkEnter; observed LinkLeave/traffic exit/arrival; censor excluded')))
                record['families'][family] = count
                record['active_count'] += count
                associated[family] += count
                record['entry_count'] += entries
                record['leave_count'] += leaves
                record['native_link_enter_count'] += link_enters
                record['native_link_leave_count'] += link_leaves
                record['entry_families'][family] = entries
                record['leave_families'][family] = leaves
                for name, value in [('last_change_time',change),('latest_entry',entry),('latest_leave',leave)]:
                    if value is not None:
                        previous = record[name]
                        record[name] = value if previous is None else max(previous, value)
            for record in links.values():
                if record['last_change_time'] is not None:
                    record['time_since_change'] = t-record['last_change_time']
            unknown = {f:totals[f]['active_in_traffic']-associated[f] for f in FAMILIES}
            if any(value < 0 for value in unknown.values()):
                raise ValueError('Link association exceeds native active traffic')
            return dict(schema_version=1, version=VERSION, identity=self.identity, time=t, time_seconds=t,
                no_positions=True, origins=origins, links=list(links.values()), totals=totals,
                coverage=dict(time_seconds=t, position_available=False,
                    associated_active={f:associated[f] for f in FAMILIES},
                    unassociated_active=unknown, complete_link_association=not any(unknown.values()),
                    body_positions='not_inferred', movement_within_link='unknown',
                    wait_attempts='not_seconds_or_unique_vehicles',
                    horizon_end_inclusive=True, source='native_census_and_sqlite_native_boundaries'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = build(args.source, args.output, lambda item: print(encode(item), flush=True))
    print(encode(result))
