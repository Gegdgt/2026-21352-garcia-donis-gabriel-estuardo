"""Tiny disposable SQLite: journey lane chronology; no server or run exports."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simz1_continuous_replay import ContinuousReplay
from simz1_paged_replay import packed


class JourneyLanes(unittest.TestCase):
    def test_indexed_journey_evidence_and_readonly_source(self):
        with tempfile.TemporaryDirectory(prefix='simz1-route-test-') as temporary:
            database = Path(temporary) / 'fixture.sqlite'
            key = 'a' * 64
            trip = {'Trip_ID': 'trip-a', 'Person_ID': 'person-a', 'Departure': 10, 'Arrival': 50}
            record = {'vehicle': 'vehicle-a', 'Link_ID': 'curve', 'timestamps': [10, 50]}
            events = [dict(vehicle=vehicle, time=at, type=kind, lane=lane, link='curve')
                      for vehicle, at, kind, lane in [
                          ('vehicle-a', 1, 'entered lane', 'old'),
                          ('vehicle-a', 9, 'left lane', 'old'),
                          ('vehicle-a', 10, 'entered lane', 'left'),
                          ('vehicle-a', 20, 'left lane', 'left'),
                          ('vehicle-a', 20, 'entered lane', 'right'),
                          ('vehicle-b', 25, 'entered lane', 'other'),
                          ('vehicle-a', 50, 'left lane', 'right')]]
            # The exporter preserves native traffic boundaries to clear lane
            # membership; they intentionally have no invented link/lane fields.
            events[6:6] = [dict(vehicle='vehicle-a', time=30, type='vehicle leaves traffic'),
                           dict(vehicle='vehicle-a', time=40, type='vehicle enters traffic')]
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript('''
                    CREATE TABLE journeys(key TEXT PRIMARY KEY,metadata TEXT);
                    CREATE TABLE segments(id INTEGER PRIMARY KEY,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                    CREATE INDEX segments_journey ON segments(journey,id);
                    CREATE TABLE lane_events(seq INTEGER PRIMARY KEY,vehicle TEXT,time REAL,payload BLOB);
                    CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);
                ''')
                connection.execute('INSERT INTO journeys VALUES (?,?)', (key, json.dumps(trip)))
                connection.execute('INSERT INTO segments VALUES (1,?,?,?,?,?)', (key, 'vehicle-a', 10, 50, packed(record)))
                connection.executemany('INSERT INTO lane_events VALUES (?,?,?,?)',
                    [(i, event['vehicle'], event['time'], packed(event)) for i, event in enumerate(events)])
            before = (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns)
            replay = ContinuousReplay.__new__(ContinuousReplay)
            replay.identity = {'run_id': 'synthetic-route-fixture', 'iteration': 0, 'run_manifest_sha256': 'b' * 64}
            # __new__ bypasses the constructor's validated export manifest;
            # the journey response still binds itself to that source version.
            replay.manifest = {'source_export_sha256': 'd' * 64}
            replay.connection = lambda: sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
            response = replay.journey(key)
            self.assertEqual(response['lane_replay']['events'],
                             [event for event in events if event['vehicle'] == 'vehicle-a' and 9 <= event['time'] < 50])
            self.assertEqual(response['records'], [{**record, 'Trip': trip}])
            self.assertEqual(response['run_id'], replay.identity['run_id'])
            self.assertEqual(response['source_version'], replay.manifest['source_export_sha256'])
            self.assertEqual(replay.journey(key), response, 'repeat query preserves equal-time order')
            self.assertEqual(before, (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns))
            with self.assertRaises(KeyError):
                replay.journey('c' * 64)
            with self.assertRaises(ValueError):
                replay.journey('not-a-key')
            # Invalid identity in a payload must be rejected, never reassigned.
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('UPDATE lane_events SET payload=? WHERE seq=2',
                                   (packed({**events[2], 'vehicle': 'other'}),))
            with self.assertRaisesRegex(ValueError, 'carril incompatible'):
                replay.journey(key)


if __name__ == '__main__':
    unittest.main()
