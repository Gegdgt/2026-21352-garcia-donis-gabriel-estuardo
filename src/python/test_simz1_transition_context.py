"""Three SQLite records only; no server, MATSim or export regeneration."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simz1_continuous_replay import ContinuousReplay, RuntimeReadCache, connect
from simz1_paged_replay import packed


class TransitionContext(unittest.TestCase):
    def test_read_only_neighbours_preserve_records_at_window_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'fixture.sqlite'
            key = 'a' * 64
            records = [dict(vehicle='v', Agent_ID='p', Link_ID=str(i), Replay_Journey_Key=key,
                            timestamps=[start, end], path=[[0, 0], [.001, 0]],
                            Motion_Plan=dict(version=1, phases=[[start, end, 0, 1, 0]]))
                       for i, (start, end) in enumerate(((118, 120), (120, 121), (121, 125)))]
            events = [dict(vehicle='v', time=t, type='entered lane', link=str(i), lane=f'lane-{i}')
                      for i, t in enumerate((118, 120, 121))]
            with sqlite3.connect(database) as db:
                db.executescript('''CREATE TABLE segments(id INTEGER PRIMARY KEY,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                    CREATE INDEX segments_journey ON segments(journey,id);
                    CREATE TABLE journeys(key TEXT PRIMARY KEY,metadata TEXT);
                    CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                    CREATE TABLE lane_events(seq INTEGER PRIMARY KEY,vehicle TEXT,time REAL,payload BLOB);
                    CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);''')
                db.execute('INSERT INTO journeys VALUES (?,?)', (key, json.dumps({'Trip_ID': 'trip'})))
                for i, record in enumerate(records):
                    db.execute('INSERT INTO segments VALUES (?,?,?,?,?,?)', (i, key, 'v', *record['timestamps'], packed(record)))
                    db.execute('INSERT INTO segment_blocks VALUES (0,?)', (i,))
                    db.execute('INSERT INTO lane_events VALUES (?,?,?,?)', (i, 'v', events[i]['time'], packed(events[i])))
            db.close()  # sqlite3 transaction context does not close Windows file handles.
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            replay = ContinuousReplay.__new__(ContinuousReplay)
            replay.manifest = dict(window_count=2, window_seconds=120, replay_window=dict(start_seconds=0, end_seconds=240))
            replay.identity = dict(run_id='fixture', iteration=0, run_manifest_sha256='b'*64)
            replay.connection = lambda: connect(database)
            replay.block_indexes = lambda start, end: [0]
            replay.temporal = lambda indexes, start, end: ({'series': []}, [])
            replay.lookup_cache = RuntimeReadCache(max_bytes=8192, max_entries=32)
            left, right = replay.window(0), replay.window(1)
            self.assertEqual(left['segments'], records[:1])
            self.assertEqual(left['context_segments'], records[1:2])
            self.assertEqual(right['segments'], records[1:])
            self.assertEqual(right['context_segments'], records[:1])
            self.assertEqual(left['lane_replay']['events'], events[:1])
            self.assertEqual(left['context_lane_events'], events[1:2])
            self.assertEqual(right['context_lane_events'], events[:1])
            repeated = replay.window(1)
            self.assertEqual(repeated['segments'], right['segments'])
            self.assertEqual(repeated['context_segments'], right['context_segments'])
            self.assertEqual(repeated['lane_replay'], right['lane_replay'])
            self.assertGreater(repeated['query_counters']['lookup_cache_hits'], 0)
            self.assertLess(repeated['query_counters']['sql_queries'], right['query_counters']['sql_queries'])
            for phase in ('sqlite', 'zlib_decompress', 'connection_validation', 'assembly_and_metadata'):
                self.assertGreaterEqual(repeated['timings_seconds'][phase], 0)
            self.assertLessEqual(replay.lookup_cache.bytes, 8192)
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
