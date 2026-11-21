"""Small offline extractor regressions; never open a historical run."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import inspect_simz1_conflicts as inspect


class FakeReplay:
    def __init__(self, root):
        self.root = Path(root)
        self.database = self.root/'sample.sqlite'
        self.identity = dict(run_id='test-only', iteration=0, run_manifest_sha256='a'*64)
        self.manifest = dict(replay_window=dict(start_seconds=0, end_seconds=240),
                             window_seconds=120, window_count=2, source_export_sha256='b'*64)
        self.source_manifest = dict(source_type='sqlite-direct-v1')
        self.config = dict(visual_lanes=dict(links={}))
        self.calls = []
        self.rows = [dict(vehicle='a', Agent_ID='person-a', Link_ID='link', Replay_Journey_Key='journey-a',
            timestamps=[0,60], path=[[0,0],[.001,0]], Motion_Plan=dict(status='constant')),
            dict(vehicle='b', Agent_ID='person-b', Link_ID='far-link', Replay_Journey_Key='journey-b',
            timestamps=[0,60], path=[[1,1],[1.001,1]], Motion_Plan=dict(status='constant'))]

    def connection(self):
        return sqlite3.connect(self.database.as_uri()+'?mode=ro&immutable=1', uri=True)

    def block_indexes(self, start, end):
        return [int(start//120)]

    def window(self, index):
        self.calls.append(index)
        return dict(index=index, start_seconds=index*120, end_seconds=(index+1)*120,
            segments=self.rows, trips={}, lane_replay=dict(events=[]), queue_context=None)

    def hud(self, query):
        return dict(**self.identity, counts=dict(persons_generated=2))


class ConflictInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.replay = FakeReplay(self.root)
        with closing(sqlite3.connect(self.replay.database)) as c:
            c.executescript('''CREATE TABLE segments(id INTEGER PRIMARY KEY,start REAL,end REAL,payload BLOB);
                CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                CREATE INDEX segments_block ON segment_blocks(block,segment);
                CREATE TABLE lane_events(seq INTEGER,time REAL);
                CREATE INDEX lanes_time ON lane_events(time,seq);''')
            c.executemany('INSERT INTO segments VALUES(?,?,?,?)', [(1,0,60,b'invalid-but-unread'),(2,0,60,b'also-unread')])
            c.executemany('INSERT INTO segment_blocks VALUES(0,?)', [(1,),(2,)])
            c.execute('INSERT INTO lane_events VALUES(1,10)')
            c.commit()

    def test_budget_reads_indexes_not_payload_and_preserves_database(self):
        before = hashlib.sha256(self.replay.database.read_bytes()).hexdigest()
        result = inspect.read_budget(self.replay,0,10,1024)
        self.assertEqual(result['movement_rows'],2)
        self.assertEqual(result['temporal_lane_rows'],1)
        self.assertTrue(any('segments_block' in line for line in result['segment_query_plan']))
        self.assertFalse(any('SCAN segments' in line for line in result['segment_query_plan']))
        self.assertEqual(hashlib.sha256(self.replay.database.read_bytes()).hexdigest(),before)
        with self.assertRaises(ValueError): inspect.read_budget(self.replay,0,1,1024)
        with self.assertRaises(ValueError): inspect.read_budget(self.replay,0,10,1)

    def test_output_exists_rejected_before_source_is_opened(self):
        with patch.object(inspect,'ContinuousReplay') as constructor:
            with self.assertRaises(FileExistsError): inspect.export('unused',self.root,[10])
            constructor.assert_not_called()

    def test_timestamps_indexes_and_budgets_rejected_without_windows(self):
        with patch.object(inspect,'ContinuousReplay',return_value=self.replay):
            for times,indexes in [([float('nan')],None),([-1],None),([240],None),([10],[1]),
                                  ([10],[-1]),([10],[True]),([10],[])]:
                with self.subTest(times=times,indexes=indexes), self.assertRaises(ValueError):
                    inspect.export(self.root,self.root/'out',times,indexes)
            with self.assertRaises(ValueError): inspect.export(self.root,self.root/'out',[10],max_rows=0)
        self.assertEqual(self.replay.calls,[])
        self.assertFalse((self.root/'out').exists())

    def test_complete_window_and_identity_preserved_without_focus_filter(self):
        before = json.dumps(self.replay.rows,sort_keys=True)
        with patch.object(inspect,'ContinuousReplay',return_value=self.replay):
            result = inspect.export(self.root,self.root/'out',[10],[0])
        saved = json.loads(Path(result['output']).read_text())
        self.assertEqual(saved['windows'][0]['segments'],self.replay.rows)
        self.assertEqual(saved['provenance']['run_id'],'test-only')
        self.assertEqual(saved['provenance']['active_native_intervals'][0]['unique_vehicle_ids'],2)
        self.assertEqual(json.dumps(self.replay.rows,sort_keys=True),before)
        self.assertEqual(self.replay.calls,[0])
        self.assertEqual(sorted(p.name for p in (self.root/'out').iterdir()),['frame-input.json','native-summary.json'])

    def test_nanosecond_fingerprint_is_serialized_as_exact_decimal_text(self):
        # This native-like value rounds when represented by a JS Number.
        timestamp = 1792508669790016400
        self.assertGreater(timestamp, 2**53-1)
        os.utime(self.replay.database, ns=(timestamp, timestamp))
        before = inspect.fingerprint(self.replay.database)
        self.assertIsInstance(before['mtime_ns'], int, 'internal comparison remains exact')
        self.assertEqual(before['mtime_ns'], timestamp)
        with patch.object(inspect,'ContinuousReplay',return_value=self.replay):
            result = inspect.export(self.root,self.root/'out',[10],[0])
        for filename in [Path(result['output']),self.root/'out'/'native-summary.json']:
            saved = json.loads(filename.read_text())['provenance']['database_fingerprint']
            self.assertEqual(saved['mtime_ns'], '1792508669790016400')
            self.assertIsInstance(saved['mtime_ns'], str)
        self.assertEqual(inspect.fingerprint(self.replay.database), before)

    def test_density_counts_native_lanes_and_duplicates_without_dropping_rows(self):
        row = self.replay.rows[0]
        window = self.replay.window(0)
        window['segments'] = [row,dict(row),self.replay.rows[1]]
        window['lane_replay']['events'] = [dict(vehicle='a',type='entered lane',time=0,link='link',lane='link.original')]
        result = inspect.native_frame_summary(self.replay.config,window,10,dict(center=[.0005,0],radius_m=1))
        self.assertEqual(result['active_intervals'],3)
        self.assertEqual(result['duplicate_active_vehicle_ids'],{'a':2})
        self.assertEqual(result['focus_active_intervals'],2,'segment crosses circle although endpoints are outside')
        self.assertEqual(result['density_by_link'][0]['native_lane_occupancy'],{'link.original':2})
        with self.assertRaises(ValueError): inspect.native_frame_summary(self.replay.config,window,120)

    def test_original_queue_domain_is_upstream_and_unknown_is_not_guessed(self):
        link = dict(length_m=10, native_lanes={
            'original':dict(start_m=10,to_lanes=['downstream']),
            'downstream':dict(start_m=8,to_links=['next'])})
        self.assertEqual(inspect.native_queue_domain(link,'original'),[0,2])
        self.assertEqual(inspect.native_queue_domain(link,'downstream'),[2,10])
        self.assertIsNone(inspect.native_queue_domain(link,'missing'))
        link['native_lanes']['original']['to_lanes']=['downstream','missing']
        self.assertIsNone(inspect.native_queue_domain(link,'original'))
        row = dict(Boundary_Provenance=dict(start_relative=0,end_relative=1),
            Motion_Plan=dict(distance_m=10,phases=[[0,10,0,1,0]]))
        self.assertEqual(inspect.raw_link_station(row,10,3),3)
        row['Boundary_Provenance']={}
        self.assertIsNone(inspect.raw_link_station(row,10,3))


if __name__ == '__main__':
    unittest.main()
