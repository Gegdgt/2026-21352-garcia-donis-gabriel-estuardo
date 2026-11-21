"""Aggregate transport gates, bounded cache and unchanged legacy replay paths."""
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from serve_simz1_continuous import ContinuousServer, handler_for
from simz1_continuous_replay import ContinuousReplay


IDENTITY = dict(run_id='aggregate-fixture', iteration=0,
                run_manifest_sha256='a' * 64, source_version='b' * 64,
                visual_policy='partial-native-v1')


class EvidenceFixture:
    def __init__(self):
        self.integrity_valid = True

    def check_source_files(self):
        if not self.integrity_valid:
            raise ValueError('Aggregate source mutated')


class AggregateFixture:
    root = '.'
    config = {'continuous': IDENTITY}
    config_raw = b'{}'
    identity = {key: IDENTITY[key] for key in ('run_id', 'iteration', 'run_manifest_sha256')}
    response_identity = IDENTITY
    visual_policy = 'partial-native-v1'
    manifest = dict(source_export_sha256=IDENTITY['source_version'], window_count=720,
                    replay_window=dict(start_seconds=0, end_seconds=86400))
    aggregate_time = ContinuousReplay.aggregate_time
    check_identity = ContinuousReplay.check_identity

    def __init__(self, _, **kwargs):
        self.aggregate_replay = EvidenceFixture()
        self.calls = []
        self.integrity_valid = True

    def check_source_files(self):
        if not self.integrity_valid:
            raise ValueError('Native source mutated')

    def aggregate_snapshot(self, instant):
        self.calls.append(instant)
        return dict(**IDENTITY, time_seconds=instant, origins=[], links=[],
                    coverage={'body_positions': False})

    def window_bytes(self, index):
        return json.dumps(dict(**IDENTITY, index=index, segments=[])).encode()


class AggregateServerTests(unittest.TestCase):
    def setUp(self):
        with patch('serve_simz1_continuous.ContinuousReplay', AggregateFixture), \
                patch('serve_simz1_continuous.application_html', return_value='<html></html>'):
            handler = handler_for('.', visual_policy='partial-native-v1', max_queries=1)
        self.replay = handler.replay
        self.server = ContinuousServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get(self, query, path='/api/aggregate'):
        address = f'http://127.0.0.1:{self.server.server_port}{path}?{urlencode(query, doseq=True)}'
        with urlopen(address, timeout=3) as response:
            return json.load(response)

    def test_exact_time_identity_and_coalesced_cache_namespace(self):
        for instant in (240, 23400, 30600, 33300, 37800, 72300, 82800, 86400):
            query = dict(IDENTITY, time=instant)
            for _ in range(2):
                result = self.get(query)
                self.assertEqual(result['time_seconds'], instant)
                self.assertEqual({k: result[k] for k in IDENTITY}, IDENTITY)
        self.assertEqual(len(self.replay.calls), 8)
        window = self.get(dict(IDENTITY, index=0), '/api/window')
        self.assertEqual(window['segments'], [])

    def test_identity_time_absence_and_mutation_reject_before_snapshot(self):
        invalid = [dict(IDENTITY, time=x) for x in ('nan', 'inf', '-1', '86401', ['1', '2'])]
        invalid += [dict(IDENTITY), dict(IDENTITY, time=240, run_id='other'),
                    dict(IDENTITY, time=240, iteration=1),
                    dict(IDENTITY, time=240, source_version='wrong'),
                    dict(IDENTITY, time=240, visual_policy='wrong')]
        missing = dict(IDENTITY, time=240)
        del missing['source_version']
        invalid.append(missing)
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                self.get(query)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.replay.calls, [])
        self.replay.aggregate_replay = None
        with self.assertRaises(HTTPError):
            self.get(dict(IDENTITY, time=240))

    def test_cached_snapshot_does_not_hide_source_mutation(self):
        self.get(dict(IDENTITY, time=240))
        for source in (self.replay, self.replay.aggregate_replay):
            source.integrity_valid = False
            with self.assertRaises(HTTPError):
                self.get(dict(IDENTITY, time=240))
            source.integrity_valid = True
        self.assertEqual(self.replay.calls, [240])


if __name__ == '__main__':
    unittest.main()
