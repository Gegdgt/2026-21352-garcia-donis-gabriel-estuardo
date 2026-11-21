import gzip
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from serve_simz1_continuous import ByteCache, ContinuousServer, handler_for
from simz1_continuous_replay import ContinuousReplay, VerifiedWorkerSpatial, connect, digest, generate, html_parts, json_bytes
from simz1_paged_replay import packed


class ContinuousFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'webgl'
        self.source.mkdir()
        (self.source / 'blocks').mkdir()
        self.output = self.root / 'webgl-continuo'
        run = {'run_id': 'simz1-fixture', 'status': 'completed', 'validation': {'status': 'valid'}, 'results': {'0': {}}}
        plans=self.root/'plans.xml';plans.write_text('<population><person id="native-person"/></population>')
        run['inputs']={'plans':{'path':'plans.xml','sha256':digest(plans)}}
        (self.root / 'run-manifest.json').write_bytes(json_bytes(run))
        self.identity = {'run_id': run['run_id'], 'iteration': 0, 'run_manifest_sha256': digest(self.root / 'run-manifest.json')}
        blocks = [{'index': i, 'start_seconds': start, 'end_seconds': end, 'url': f'{i:04d}.html'}
                  for i, (start, end) in enumerate(((0, 300), (300, 600), (600, 601)))]
        self.key = 'a' * 64
        self.trip = {'Trip_ID': 'native-trip', 'Departure': 0, 'Arrival': 601, 'Status': 'completed'}
        self.records = [{'Agent_ID': 'native-person', 'Replay_Journey_Key': self.key, 'vehicle': 'v',
                         'timestamps': [start, end], 'path': [[-90.5, 14.6], [-90.51, 14.61]],
                         'Motion_Plan': {'status': 'available', 'phases': [{'start': start, 'end': end, 'speed': 1.23}]},
                         'Speed_kmh': 4.428, 'Max_Speed_kmh': 8.8}
                        for start, end in ((110, 130), (290, 310), (599, 600), (600, 601))]
        database = self.source / 'replay.sqlite'
        with sqlite3.connect(database) as db:
            db.executescript('''CREATE TABLE segments(id INTEGER PRIMARY KEY,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                CREATE INDEX segments_block ON segment_blocks(block,segment);
                CREATE INDEX segments_journey ON segments(journey,id);
                CREATE TABLE journeys(key TEXT PRIMARY KEY,metadata TEXT);
                CREATE TABLE lane_events(seq INTEGER PRIMARY KEY,vehicle TEXT,time REAL,payload BLOB);
                CREATE INDEX lanes_time ON lane_events(time,seq);
                CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);
                CREATE TABLE export_identity(key TEXT PRIMARY KEY,value TEXT);''')
            db.executemany('INSERT INTO export_identity VALUES (?,?)', [(k, str(v)) for k, v in self.identity.items()])
            db.execute('INSERT INTO journeys VALUES (?,?)', (self.key, json.dumps(self.trip)))
            for index, record in enumerate(self.records):
                start, end = record['timestamps']
                db.execute('INSERT INTO segments VALUES (?,?,?,?,?,?)', (index, self.key, 'v', start, end, packed(record)))
                for block in blocks:
                    if start < block['end_seconds'] and end > block['start_seconds']:
                        db.execute('INSERT INTO segment_blocks VALUES (?,?)', (block['index'], index))
            for seq, time in enumerate((10, 115, 125, 300, 600)):
                event = {'vehicle': 'v', 'time': time, 'type': 'entered lane', 'lane': 'native-lane', 'link': 'native-link'}
                db.execute('INSERT INTO lane_events VALUES (?,?,?,?)', (seq, 'v', time, packed(event)))
        for block in blocks:
            states = [[[0, 'RED'], [120, 'GREEN']], [[120, 'GREEN'], [300, 'RED']], [[300, 'RED'], [600, 'GREEN']]][block['index']]
            config = {'layers': [
                {'@@type': 'LineLayer', 'data': [{'from': [0, 0], 'to': [1, 1]}], 'id': 'roads'},
                {'@@type': 'ScatterplotLayer', 'data': self.records, 'getFillColor': '@@=color', 'id': 'trips'},
                {'@@type': 'IconLayer', 'data': [{'start': 295, 'end': 305, 'position': [0, 0]}], 'getIcon': '@@=icon', 'id': 'incidents'}],
                'hud': {'run_id': self.identity['run_id'], 'iteration': 0},
                'signal_replay': {'series': [{'system_id': 's', 'group_id': 'g', 'states': states}]},
                'lane_replay': {'events': []}, 'trajectory_stats': {},
                'replay_window': {'start_seconds': block['start_seconds'], 'end_seconds': block['end_seconds']},
                'selection_warning': None}
            document = b'<script id="replay-data" type="application/json">' + json_bytes(config) + b'</script><script>/* controls */</script>'
            (self.source / 'blocks' / block['url']).write_bytes(document)
        old = {**self.identity, 'status': 'complete', 'sample_rate': 1, 'run_directory': str(self.root),
               'database': 'replay.sqlite', 'blocks': blocks, 'replay_window': {'start_seconds': 0, 'end_seconds': 601},
               'counts': {'reconstructed_vehicles': 1, 'segments': len(self.records)}, 'planned_persons': 1,
               'planned_trips': 1, 'phases_seconds': {'total': 1}, 'html_bytes': 5000}
        (self.source / 'export-manifest.json').write_bytes(json_bytes(old))
        self.before = (digest(database), database.stat().st_mtime_ns, database.stat().st_size)
        generate(self.source, self.output, end=600)
        self.replay = ContinuousReplay(self.output)

    def tearDown(self):
        self.temporary.cleanup()

    def test_worker_spatial_reuse_preserves_proofs_and_rejects_input_or_identity_changes(self):
        # A synthetic result stands in for the parent's expensive completed
        # validation; the worker must still verify every pinned source byte.
        spatial=VerifiedWorkerSpatial(mode='balanced-gateway-v1',native_field='original')
        spatial.metadata_hashes={'native-person':'b'*64}
        spatial.postprocessor_version='balanced-replay-contract-v1'
        self.replay.spatial=spatial
        self.replay.native_run['spatial_demand']=dict(spatial)
        preparation=self.replay.spatial_preparation()
        restored=self.replay.checked_spatial_preparation(preparation,self.replay.source_manifest)
        self.assertEqual(restored,spatial)
        self.assertEqual(restored.metadata_hashes,spatial.metadata_hashes)
        self.assertEqual(restored.postprocessor_version,spatial.postprocessor_version)
        from unittest.mock import patch
        with patch('simz1_continuous_replay.MAX_SPATIAL_PREPARATION_BYTES',1):
            self.assertIsNone(self.replay.spatial_preparation(),'oversized preparation uses full worker validation')
            with self.assertRaises(ValueError):self.replay.checked_spatial_preparation(preparation,self.replay.source_manifest)
        import copy
        for field,value in [('identity',{}),('source_version','other'),('spatial',dict(spatial,native_field='mutated')),
                            ('postprocessor_version','unverified')]:
            altered=copy.deepcopy(preparation);altered['payload'][field]=value
            # Even a new envelope checksum cannot change its native identity
            # or contract. Metadata corruption without a new checksum also fails.
            altered['sha256']=hashlib.sha256(json_bytes(altered['payload'])).hexdigest()
            with self.assertRaises(ValueError):self.replay.checked_spatial_preparation(altered,self.replay.source_manifest)
        altered=copy.deepcopy(preparation);altered['payload']['metadata_hashes']['native-person']='c'*64
        with self.assertRaises(ValueError):self.replay.checked_spatial_preparation(altered,self.replay.source_manifest)
        plans=self.root/'plans.xml';original=plans.read_bytes()
        plans.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.replay.checked_spatial_preparation(preparation,self.replay.source_manifest)
        plans.unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):self.replay.checked_spatial_preparation(preparation,self.replay.source_manifest)

    def test_unavailable_optional_cache_falls_back_to_full_validation(self):
        from unittest.mock import patch
        run=dict(self.replay.native_run,spatial_demand={'mode':'balanced-gateway-v1'})
        for error in (OSError('unavailable cache directory'), ValueError('cache root symlink')):
            with patch('simz1_continuous_replay.checked_native_run',return_value=run), \
                    patch('simz1_replay_spatial_cache.SpatialPreparationCache',side_effect=error), \
                    patch('simz1_workflow_state.fingerprint',return_value='fixture'), \
                    patch('simz1_gateway_od.validated_spatial_demand',return_value=None) as full:
                reader=ContinuousReplay(self.output,spatial_cache_root=self.root/'optional-cache')
                full.assert_called_once()
                self.assertEqual(reader.initialization['spatial_mode'],'full_spatial_validation')
                self.assertIsNone(reader.initialization['spatial_cache'])
                self.assertIn(str(error),reader.initialization['spatial_cache_error'])
        with patch('simz1_continuous_replay.checked_native_run',return_value=run), \
                patch('simz1_replay_spatial_cache.SpatialPreparationCache',side_effect=RuntimeError('bug')), \
                patch('simz1_workflow_state.fingerprint',return_value='fixture'), \
                patch('simz1_gateway_od.validated_spatial_demand') as full:
            with self.assertRaisesRegex(RuntimeError,'bug'):
                ContinuousReplay(self.output,spatial_cache_root=self.root/'optional-cache')
            full.assert_not_called()

    def test_internal_boundary_preserves_complete_native_segment_and_motion(self):
        first, second = self.replay.window(0), self.replay.window(1)
        self.assertEqual(first['segments'][0], self.records[0])
        self.assertEqual(second['segments'][0], self.records[0])
        self.assertEqual(second['segments'][0]['timestamps'], [110, 130])
        self.assertNotIn('Trip', second['segments'][0])
        self.assertEqual(second['trips'][self.key], self.trip)

    def test_native_signal_lane_predecessors_and_original_block_crossing(self):
        second = self.replay.window(1)
        self.assertEqual(second['signal_replay']['series'][0]['states'], [[0, 'RED'], [120, 'GREEN']])
        self.assertEqual([e['time'] for e in second['lane_replay']['events']], [115, 125])
        cross = self.replay.window(2)
        self.assertEqual(cross['signal_replay']['series'][0]['states'], [[120, 'GREEN'], [300, 'RED']])
        self.assertEqual(len(cross['incidents']), 1)

    def test_terminal_snapshot_includes_native_entries_and_signal_at_exact_end(self):
        final = self.replay.window(4)
        self.assertEqual(final['end_seconds'], 600)
        self.assertIn(self.records[-1], final['segments'])
        self.assertEqual(final['signal_replay']['series'][0]['states'][-1], [600, 'GREEN'])
        self.assertEqual(final['lane_replay']['events'][-1]['time'], 600)

    def test_complete_journey_is_independent_from_loaded_window(self):
        journey = self.replay.journey(self.key)
        self.assertEqual(len(journey['records']), 4)
        self.assertEqual(journey['run_manifest_sha256'], self.identity['run_manifest_sha256'])
        for actual, expected in zip(journey['records'], self.records):
            self.assertEqual(actual, {**expected, 'Trip': self.trip})

    def test_geometry_extraction_and_sqlite_are_read_only(self):
        config = html_parts(self.source / 'blocks' / '0000.html', config=True)
        self.assertEqual(config['layers'][1]['data'], [])
        database = self.source / 'replay.sqlite'
        self.assertEqual((digest(database), database.stat().st_mtime_ns, database.stat().st_size), self.before)
        connection = connect(database)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('DELETE FROM segments')
        finally:
            connection.close()

    def test_current_application_is_served_without_refreshing_existing_export(self):
        # Exercise the real HTTP handler without opening a socket. A stale shell
        # must not hide current geometry, HUD or camera fixes behind an old export.
        shell = self.output / 'index.html'
        shell.write_bytes(b'<html>historical fixture shell</html>')
        protected = [shell, self.output / 'continuous-manifest.json',
                     self.output / 'config.json', self.source / 'export-manifest.json',
                     self.source / 'replay.sqlite', self.root / 'run-manifest.json']
        before = {path: digest(path) for path in protected}
        handler = handler_for(self.output)
        request = object.__new__(handler)
        request.path = '/index.html'
        request.wfile = io.BytesIO()
        statuses, headers = [], {}
        request.send_response = lambda status: statuses.append(status)
        request.send_header = lambda name, value: headers.update({name: value})
        request.end_headers = lambda: None
        request.serve_static(head=False)
        document = request.wfile.getvalue().decode('utf-8')
        self.assertEqual(statuses, [200])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('historical fixture shell', document)
        for filename in ('simz1_continuous_loader.js', 'simz1_continuous_hud.js',
                         'simz1_visual_lanes.js', 'simz1_visual_queues.js',
                         'simz1_vehicle_picking.js', 'simz1_spatial_view.js',
                         'visualizador_z1_controls.js'):
            self.assertEqual(document.count(Path(__file__).with_name(filename).read_text(encoding='utf-8')), 1,
                             filename + ' must be current and included exactly once')
        self.assertEqual(before, {path: digest(path) for path in protected})

    def test_reject_wrong_identity_source_mutation_and_completed_overwrite(self):
        with self.assertRaises(ValueError):
            self.replay.check_identity({'run_id': ['other'], 'iteration': ['0']})
        with self.assertRaises(ValueError):
            generate(self.source, self.output, end=600, resume_incomplete=True)
        with sqlite3.connect(self.source / 'replay.sqlite') as db:
            db.execute("UPDATE export_identity SET value='wrong' WHERE key='run_id'")
        with self.assertRaises(ValueError):
            ContinuousReplay(self.output)

    def test_temporal_corruption_fails_closed_and_indices_are_bounded(self):
        for index in (-1, 5, 0.5, True):
            with self.assertRaises(ValueError):
                self.replay.window(index)
        (self.output / 'temporal' / '0000.json.gz').write_bytes(b'corruption')
        with self.assertRaises(ValueError):
            self.replay.window(0)

    def test_reject_mixed_run_html_even_when_database_identity_matches(self):
        path = self.source / 'blocks' / '0001.html'
        path.write_bytes(path.read_bytes().replace(b'"run_id":"simz1-fixture"', b'"run_id":"another-run"'))
        with self.assertRaisesRegex(ValueError, 'HTML temporal de otra corrida'):
            generate(self.source, self.root / 'mixed-html-rejected', end=600)

    def test_reject_html_for_wrong_native_time_window(self):
        path = self.source / 'blocks' / '0001.html'
        path.write_bytes(path.read_bytes().replace(b'"start_seconds":300', b'"start_seconds":301'))
        with self.assertRaisesRegex(ValueError, 'HTML temporal de otra corrida'):
            generate(self.source, self.root / 'mixed-time-rejected', end=600)

    def test_duplicate_native_incidents_keep_multiplicity_across_parent_blocks(self):
        for index in (0, 1):
            path = self.output / 'temporal' / f'{index:04d}.json.gz'
            payload = json.loads(gzip.decompress(path.read_bytes()))
            payload['incidents'].append(dict(payload['incidents'][0]))
            raw = gzip.compress(json_bytes(payload))
            path.write_bytes(raw)
            self.replay.manifest['temporal_files'][index]['sha256'] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(len(self.replay.window(2)['incidents']), 2)

    def test_http_identity_gzip_errors_concurrency_and_private_files(self):
        handler = handler_for(self.output, cache_bytes=4096, max_queries=1)
        server = ContinuousServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        suffix = '?' + urlencode(self.identity)
        try:
            with urlopen(base + '/api/config') as response:
                served = json.load(response)
                self.assertEqual(served['continuous']['window_count'], 5)
                version = served['continuous']['source_version']
                self.assertEqual(version, self.replay.manifest['source_export_sha256'])
                self.assertEqual(served['replay_source']['replay_manifest_sha256'],
                                 digest(self.output / 'continuous-manifest.json'))
                self.assertEqual(served['replay_source']['database_bytes'], self.replay.database.stat().st_size)
            request = Request(base + '/api/window' + suffix + '&index=0', headers={'Accept-Encoding': 'gzip'})
            with urlopen(request) as response:
                self.assertEqual(response.headers['Content-Encoding'], 'gzip')
                payload = json.loads(gzip.decompress(response.read()))
                self.assertEqual(payload['index'], 0)
                self.assertEqual(payload['source_version'], version)
            # Even a cached window must reject the preceding export version.
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + '/api/window' + suffix + '&index=0&source_version=' + 'f'*64)
            self.assertEqual(caught.exception.code, 400)
            with urlopen(base + '/api/window' + suffix + '&index=0&source_version=' + version) as response:
                self.assertEqual(json.load(response)['source_version'], version)
            for path, status in (('/api/window?index=0', 400), ('/api/window'+suffix+'&index=-1', 400),
                                 ('/api/journey'+suffix+'&key='+'f'*64, 404), ('/replay.sqlite', 403),
                                 ('/../webgl/replay.sqlite', 403), ('/api/missing'+suffix, 404)):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base + path)
                self.assertEqual(caught.exception.code, status)
            handler.queries.acquire()
            try:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base + '/api/window' + suffix + '&index=1')
                self.assertEqual(caught.exception.code, 503)
                # Actual HTTP handler, socket and SQLite fixture: journey uses
                # the same bounded server work slot, with retryable identity.
                for _ in range(2):
                    with self.assertRaises(HTTPError) as busy:
                        urlopen(base + '/api/journey' + suffix + '&key=' + self.key)
                    self.assertEqual(busy.exception.code, 503)
                    self.assertEqual(busy.exception.headers['Retry-After'], '2')
                    failure = json.load(busy.exception)
                    self.assertTrue(failure['retryable'])
                    self.assertEqual(failure['run_id'], self.identity['run_id'])
                    self.assertEqual(failure['iteration'], self.identity['iteration'])
            finally:
                handler.queries.release()
            with urlopen(base + '/api/journey' + suffix + '&key=' + self.key) as response:
                self.assertEqual(response.status, 200)
                journey = json.load(response)
                self.assertEqual(journey['key'], self.key)
                self.assertEqual(len(journey['records']), 4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_duplicate_http_windows_share_work_and_leave_slot_for_selection(self):
        handler = handler_for(self.output, max_queries=2)
        original = handler.replay.window_bytes
        started, release, calls = threading.Event(), threading.Event(), []

        def delayed(index):
            calls.append(index)
            started.set()
            if not release.wait(5):
                raise RuntimeError('Test did not release the delayed query')
            return original(index)

        handler.replay.window_bytes = delayed
        server = ContinuousServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        suffix = '?' + urlencode(self.identity)

        def fetch_window():
            with urlopen(base + '/api/window' + suffix + '&index=0', timeout=5) as response:
                return json.load(response)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    first = pool.submit(fetch_window)
                    self.assertTrue(started.wait(2))
                    second = pool.submit(fetch_window)
                    deadline = time.monotonic() + 2
                    while handler.query_summary()['coalesced_requests'] == 0 and time.monotonic() < deadline:
                        release.wait(0.01)
                    self.assertEqual(handler.query_summary()['coalesced_requests'], 1)
                    # A duplicate temporal request must not consume the slot
                    # required to fetch the selected complete native journey.
                    with urlopen(base + '/api/journey' + suffix + '&key=' + self.key, timeout=2) as response:
                        self.assertEqual(len(json.load(response)['records']), 4)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=2)['index'], 0)
                self.assertEqual(second.result(timeout=2)['index'], 0)
            self.assertEqual(calls, [0])
            self.assertLessEqual(handler.query_summary()['peak_distinct_queries'], 2)
            self.assertEqual(handler.query_summary()['active_distinct_queries'], 0)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_aborted_connection_during_headers_does_not_send_second_response(self):
        handler = handler_for(self.output)
        for endpoint in ('/api/config', '/api/window?' + urlencode(self.identity) + '&index=0'):
            with self.subTest(endpoint=endpoint):
                request = object.__new__(handler)
                request.path = endpoint
                request.headers = {'Accept-Encoding': 'gzip'}
                request.wfile = io.BytesIO()
                responses = []
                request.send_response = lambda status, *args: responses.append(status)
                request.send_header = lambda *args: None

                def canceled_headers():
                    raise ConnectionResetError('Browser aborted before headers flushed')

                request.end_headers = canceled_headers
                request.do_GET()
                self.assertEqual(responses, [200])
                self.assertEqual(request.wfile.getvalue(), b'')


class CacheTests(unittest.TestCase):
    def test_cache_byte_limit_lru_and_oversized_response(self):
        cache = ByteCache(max_bytes=10, max_entries=2)
        cache.put(1, b'12345')
        cache.put(2, b'67890')
        self.assertEqual(cache.get(1), b'12345')
        cache.put(3, b'abcd')
        self.assertIsNone(cache.get(2))
        cache.put(4, b'x' * 11)
        self.assertIsNone(cache.get(4))
        self.assertLessEqual(cache.summary()['bytes'], 10)


if __name__ == '__main__':
    unittest.main()
