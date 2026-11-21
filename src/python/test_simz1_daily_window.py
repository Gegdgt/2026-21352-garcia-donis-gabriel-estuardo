"""Small daily-view checks using native records in memory, never the 100k run."""
import copy
import io
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from serve_simz1_continuous import handler_for
from simz1_continuous_replay import ContinuousReplay, application_html, daily_window, json_bytes
from simz1_paged_replay import packed


class DailyWindowTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(run_id='daily-fixture', iteration=0, run_manifest_sha256='fixture')
        self.source = dict(replay_window=dict(start_seconds=0, end_seconds=90001),
                           operational_counts_observation_end_seconds=90001)
        self.manifest = dict(replay_window=dict(start_seconds=0, end_seconds=90000),
                             window_seconds=120, window_count=750)
        self.config = dict(time_horizon=dict(start_seconds=0, end_seconds=90000),
                           continuous=dict(self.identity, data_end_seconds=90001),
                           operational_counts=dict(completed_legs=7, pending_legs_at_horizon=3))
        self.original_source = copy.deepcopy(self.source)
        daily_window(self.config, self.manifest, self.source)

    def test_daily_bounds_keep_original_metrics_explicit_and_source_unchanged(self):
        self.assertEqual(self.config['replay_window'], dict(start_seconds=0, end_seconds=86400))
        self.assertEqual(self.manifest['window_count'], 720)
        self.assertEqual(self.config['continuous']['end_seconds'], 86400)
        self.assertNotIn('data_end_seconds', self.config['continuous'])
        self.assertEqual(self.config['continuous']['source_time_horizon']['end_seconds'], 90000)
        self.assertEqual(self.config['continuous']['metrics_window']['end_seconds'], 90001)
        self.assertEqual(self.config['operational_counts'], dict(completed_legs=7, pending_legs_at_horizon=3))
        self.assertEqual(self.source, self.original_source)

    def test_short_explicit_fixture_and_invalid_post_day_range(self):
        self.manifest['replay_window'] = dict(start_seconds=0, end_seconds=600)
        daily_window(self.config, self.manifest, self.source)
        self.assertEqual(self.manifest['window_count'], 5)
        self.manifest['replay_window'] = dict(start_seconds=86400, end_seconds=90000)
        with self.assertRaises(ValueError):
            daily_window(self.config, self.manifest, self.source)

    def replay(self):
        replay = object.__new__(ContinuousReplay)
        replay.identity, replay.manifest, replay.config = self.identity, self.manifest, self.config
        replay.root, replay.config_raw = Path('.'), json_bytes(self.config)
        replay.blocks = [dict(start_seconds=0, end_seconds=86400),
                         dict(start_seconds=86400, end_seconds=90001)]
        replay.block_ends = [86400, 90001]
        replay.temporal = lambda *args: (dict(series=[]), [])
        trip = dict(Departure=86390, Arrival=86430, Status='completed')
        key = 'a' * 64
        records = [dict(timestamps=[start, end], vehicle='v', Replay_Journey_Key=key)
                   for start, end in ((0, 1), (110, 130), (86390, 86430), (86400, 86410), (86430, 86440))]

        def connection():
            db = sqlite3.connect(':memory:')
            db.executescript('''CREATE TABLE segments(id INTEGER,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                CREATE TABLE journeys(key TEXT,metadata TEXT);
                CREATE TABLE lane_events(seq INTEGER,vehicle TEXT,time REAL,payload BLOB);''')
            db.execute('INSERT INTO journeys VALUES (?,?)', (key, json_bytes(trip).decode()))
            for number, record in enumerate(records):
                start, end = record['timestamps']
                db.execute('INSERT INTO segments VALUES (?,?,?,?,?,?)', (number, key, 'v', start, end, packed(record)))
                for block, bounds in enumerate(replay.blocks):
                    if start < bounds['end_seconds'] and end > bounds['start_seconds']:
                        db.execute('INSERT INTO segment_blocks VALUES (?,?)', (block, number))
            db.commit()
            db.execute('PRAGMA query_only=ON')
            return db

        replay.connection = connection
        return replay, records, trip, key

    def test_endpoints_internal_window_and_native_cross_midnight_records(self):
        replay, records, trip, key = self.replay()
        first, second, last = replay.window(0), replay.window(1), replay.window(719)
        self.assertEqual(first['start_seconds'], 0)
        self.assertIn(records[0], first['segments'])
        self.assertIn(records[1], first['segments'])
        self.assertIn(records[1], second['segments'])
        self.assertEqual(last['end_seconds'], 86400)
        self.assertEqual(last['segments'], records[2:4])
        # Arrival after midnight remains native metadata; UI derives censored
        # status for its daily window, never rewrites arrival or Motion_Plan.
        self.assertEqual(last['trips'][key], trip)
        self.assertEqual(last['segments'][0]['timestamps'], [86390, 86430])
        for index in (-1, 720, 749):
            with self.assertRaises(ValueError):
                replay.window(index)

    def test_current_application_and_daily_config_served_without_socket_or_export(self):
        replay, _, _, _ = self.replay()
        with patch('serve_simz1_continuous.ContinuousReplay', return_value=replay):
            handler = handler_for('.')
        for route, expected in (('/index.html', application_html().encode()),
                                ('/config.json', replay.config_raw), ('/api/config', replay.config_raw)):
            for head in (False, True) if route != '/api/config' else (False,):
                with self.subTest(route=route, head=head):
                    request = object.__new__(handler)
                    request.path, request.wfile, request.headers = route, io.BytesIO(), {}
                    statuses, headers = [], {}
                    request.send_response = statuses.append
                    request.send_header = headers.__setitem__
                    request.end_headers = lambda: None
                    request.do_HEAD() if head else request.do_GET()
                    self.assertEqual(statuses, [200])
                    self.assertEqual(headers['Cache-Control'], 'no-store')
                    self.assertEqual(int(headers['Content-Length']), len(expected))
                    self.assertEqual(request.wfile.getvalue(), b'' if head else expected)


if __name__ == '__main__':
    unittest.main()
