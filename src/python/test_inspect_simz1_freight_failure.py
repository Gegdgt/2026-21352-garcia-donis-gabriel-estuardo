"""Read-only failed-run selection; never opens the historical massive event file."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from inspect_simz1_freight_failure import inspect_run


class ProducedIterationTests(unittest.TestCase):
    def fixture(self, root, last=9):
        saved = root/'inputs/freight-weekday'
        saved.mkdir(parents=True)
        manifest = dict(run_id='failed-at-zero', folder=str(root), status='failed',
                        iterations=dict(first=0, last=last, requested=last+1, completed=[]), inputs={})
        for name, document in {
                'roster.json': [dict(vehicle_id='truck', departure_seconds=0,
                                     route_id='synthetic', link_ids=['a', 'b'])],
                'service.json': dict(vehicles=1, allowed_windows_seconds=[[0, 18000]],
                                     residence_policy='fixture')}.items():
            raw = json.dumps(document).encode('utf-8')
            (saved/name).write_bytes(raw)
            manifest['inputs']['input:freight-weekday/'+name] = dict(
                path='inputs/freight-weekday/'+name, sha256=hashlib.sha256(raw).hexdigest())
        (root/'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.iteration(root, 0)
        return manifest

    def iteration(self, root, number, report=True):
        folder = root/'output/ITERS'/f'it.{number}'
        folder.mkdir(parents=True)
        (folder/f'{number}.events.xml.gz').write_bytes(gzip.compress(
            b'<events><event time="0" type="departure" person="truck" link="a"/>'
            b'<event time="86401" type="stuckAndAbort" person="truck" link="a"/></events>'))
        if report:
            (folder/f'{number}.simz1-freight-audit.csv').write_text(
                'vehicle,trip_outcome,schedule_compliance,violation_observed\n'
                'truck,aborted,no_violation_observed,\n', encoding='utf-8')

    def test_requested_ten_iterations_failed_at_zero_can_inspect_actual_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = inspect_run(root, 'failed-at-zero', 0, 100000, 5)
            self.assertEqual(result['iteration'], 0)
            self.assertTrue(result['extraction']['gzip_crc_and_xml_complete'])
            self.assertEqual(result['native_outcomes'], {'aborted': ['truck']})
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_automatic_selection_reports_requested_and_produced_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root)
            result = inspect_run(root, 'failed-at-zero', None, 100000, 5)
            self.assertEqual(result['iteration'], 0)
            self.assertEqual(result['last_requested_iteration'], 9)
            self.assertEqual(result['last_produced_iteration'], 0)

    def test_requested_but_absent_iteration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, 'latest produced'):
                inspect_run(root, 'failed-at-zero', 9, 100000, 5)

    def test_later_incomplete_iteration_does_not_fall_back_to_older_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root)
            self.iteration(root, 1, report=False)
            with self.assertRaisesRegex(ValueError, 'latest produced'):
                inspect_run(root, 'failed-at-zero', 0, 100000, 5)
            with self.assertRaisesRegex(ValueError, 'missing freight evidence'):
                inspect_run(root, 'failed-at-zero', None, 100000, 5)

    def test_out_of_range_outputs_are_explicit_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root, last=0)
            self.iteration(root, 1)
            with self.assertRaisesRegex(ValueError, 'outside requested'):
                inspect_run(root, 'failed-at-zero', None, 100000, 5)

    def test_no_produced_events_or_audit_is_an_explicit_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.fixture(root)
            for name in ('0.events.xml.gz', '0.simz1-freight-audit.csv'):
                (root/'output/ITERS/it.0'/name).unlink()
            with self.assertRaisesRegex(ValueError, 'No produced'):
                inspect_run(root, 'failed-at-zero', None, 100000, 5)


if __name__ == '__main__':
    unittest.main()
