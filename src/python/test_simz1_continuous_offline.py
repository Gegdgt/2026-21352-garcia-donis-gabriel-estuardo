"""Independent local-window validation with six tiny SQLite fixture records."""
from copy import deepcopy
import json
import sys
import unittest
from unittest.mock import patch

import verify_simz1_continuous_data as verifier
import test_simz1_sqlite_source as source_fixtures


class OfflineIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = source_fixtures.SqliteSourceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.replay, _ = self.fixture.daily_source()

    def test_default_daily_probes_use_no_http_html_or_full_count_queries(self):
        queries = []
        connect = verifier.connect

        def trace(database):
            connection = connect(database)
            connection.set_trace_callback(queries.append)
            return connection

        with patch.object(verifier, 'fetch', side_effect=AssertionError('Offline cannot use HTTP')), \
                patch.object(verifier, 'html_parts', side_effect=AssertionError('Direct source cannot require HTML')), \
                patch.object(verifier, 'connect', side_effect=trace):
            report = verifier.verify(self.replay.root, offline=True)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['mode'], 'offline')
        self.assertEqual([row['probe_seconds'] for row in report['windows']], list(verifier.DEFAULT_TIMES))
        self.assertEqual(report['native_segment_count'], 6)
        self.assertEqual(report['native_segment_count_source'], 'validated source manifest; not recounted')
        self.assertIsNone(report['native_lane_event_count'])
        self.assertTrue(report['native_lane_events_present'])
        self.assertFalse(any('count(' in query.lower() for query in queries))
        self.assertEqual(report['windows'][-1]['segments'], 2)
        self.assertTrue(all(row['every_native_field_equal'] for row in report['windows']))
        self.assertTrue(report['selected_journey']['complete_native_fields_and_order_equal'])

    def test_independent_comparison_rejects_changed_motion_payload(self):
        original = verifier.ContinuousReplay.window

        def altered(replay, index):
            payload = deepcopy(original(replay, index))
            payload['segments'][0]['Motion_Plan']['native_fixture_number'] = 'changed-after-query'
            return payload

        with patch.object(verifier.ContinuousReplay, 'window', altered), \
                self.assertRaisesRegex(ValueError, 'Motion_Plan mismatch'):
            verifier.verify(self.replay.root, times=[0], offline=True)

    def test_offline_cli_prints_report_without_creating_output_files(self):
        before = set(self.fixture.fixture.root.rglob('*'))
        with patch.object(sys, 'argv', ['verify_simz1_continuous_data.py',
                '--directory', str(self.replay.root), '--offline']), \
                patch.object(verifier, 'fetch', side_effect=AssertionError('Offline cannot use HTTP')), \
                patch('builtins.print') as printed:
            verifier.main()
        report = json.loads(printed.call_args.args[0])
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['mode'], 'offline')
        self.assertEqual(before, set(self.fixture.fixture.root.rglob('*')))


if __name__ == '__main__':
    unittest.main()
