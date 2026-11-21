"""Negative publication-contract fixtures; no simulation and no real file edits."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import simz1_viewers_readonly as viewer


class ReadOnlyContractTests(unittest.TestCase):
    def fixture(self, name):
        identity = viewer.expected_identity(name)
        native = dict(run_id=identity['run_id'], status='completed', validation={'status': 'valid'}, results={'0': {}})
        state = dict(identity, status='completed', outcome='PASSED')
        receipt = dict(run_id=identity['run_id'], original_launch_id=identity['launch_id'], status='closure_recovered',
            native_validation_exit_code=0, context={'source_transition': {'native_source_fingerprint': viewer.PRODUCER}})
        return native, state, receipt

    def test_both_native_closures_are_accepted(self):
        for name in viewer.RUNS:
            viewer.check_native(name, *self.fixture(name))

    def test_historical_run10k_running_requires_valid_recovery(self):
        native, state, receipt = self.fixture('run10k')
        state['status'] = 'running'
        state['outcome'] = None
        viewer.check_native('run10k', native, state, receipt)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            viewer.check_native('run10k', native, state)

    def test_native_incomplete_or_invalid_rejected(self):
        for field, value in [('status', 'running'), ('validation', {'status': 'invalid'}), ('results', {'1': {}})]:
            native, state, receipt = self.fixture('run1000')
            native[field] = value
            with self.assertRaisesRegex(ValueError, 'completed/valid'):
                viewer.check_native('run1000', native, state, receipt)

    def test_wrong_native_identity_and_launch_rejected(self):
        for target, key in [('native', 'run_id'), ('state', 'run_id'), ('state', 'launch_id'), ('state', 'source_fingerprint')]:
            native, state, receipt = self.fixture('run1000')
            (native if target == 'native' else state)[key] = 'foreign'
            with self.assertRaisesRegex(ValueError, 'identity'):
                viewer.check_native('run1000', native, state, receipt)

    def test_run1000_missing_accepted_closure_rejected(self):
        native, state, receipt = self.fixture('run1000')
        state['outcome'] = None
        with self.assertRaisesRegex(ValueError, 'closure'):
            viewer.check_native('run1000', native, state, receipt)

    def test_recovery_negative_controls(self):
        for key, value in [('run_id', 'foreign'), ('original_launch_id', 'foreign'),
                           ('status', 'incomplete'), ('native_validation_exit_code', 1), ('context', {})]:
            native, state, receipt = self.fixture('run10k')
            receipt[key] = value
            with self.assertRaisesRegex(ValueError, 'recovery'):
                viewer.check_native('run10k', native, state, receipt)

    def test_hash_accepts_exact_and_rejects_mutation_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'artifact.json'
            path.write_bytes(b'approved')
            expected = hashlib.sha256(b'approved').hexdigest()
            self.assertEqual(viewer.checked_hash(path, expected), expected)
            path.write_bytes(b'mutated')
            with self.assertRaisesRegex(ValueError, 'changed'):
                viewer.checked_hash(path, expected)
            with self.assertRaises(FileNotFoundError):
                viewer.checked_hash(path.with_name('absent'), expected)

    def test_wrong_replay_policy_iteration_and_source_rejected(self):
        expected = viewer.expected_identity('run10k')
        for key in ('run_id', 'iteration', 'run_manifest_sha256', 'source_version', 'visual_policy'):
            bad = dict(expected, **{key: 'wrong'})
            with self.assertRaisesRegex(ValueError, key):
                viewer.check_identity(bad, expected, expected)

    def test_prepared_evidence_checksum_and_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'data').mkdir()
            path = root / 'data/buses.json.gz'
            row = copy.deepcopy(viewer.RUNS['run1000'])
            raw = json.dumps({'identity': viewer.expected_identity('run1000'), 'trips': []}).encode()
            path.write_bytes(gzip.compress(raw))
            row['evidence_sha256'] = hashlib.sha256(raw).hexdigest()
            with patch.dict(viewer.RUNS, run1000=row):
                proof = viewer.check_evidence('run1000', SimpleNamespace(HERE=root))
                self.assertEqual(proof['sha256'], row['evidence_sha256'])
                path.write_bytes(gzip.compress(raw + b' '))
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    viewer.check_evidence('run1000', SimpleNamespace(HERE=root))
                raw_bad = json.dumps({'identity': dict(viewer.expected_identity('run1000'), run_id='foreign')}).encode()
                path.write_bytes(gzip.compress(raw_bad))
                row['evidence_sha256'] = hashlib.sha256(raw_bad).hexdigest()
                with self.assertRaisesRegex(ValueError, 'identity'):
                    viewer.check_evidence('run1000', SimpleNamespace(HERE=root))

    def test_verification_stops_before_reader_if_manifest_changed(self):
        with patch.object(viewer, 'checked_hash', side_effect=ValueError('manifest changed')), patch.object(viewer, 'load_backend') as backend:
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                viewer.verify('run1000')
            backend.assert_not_called()

    def test_existing_replay_config_window_and_database_mutations(self):
        from simz1_sqlite_source import FILE_NAME
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            directory = run / 'webgl-continuo-it.0'
            source = run / 'webgl-source-it.0/sqlite-source'
            directory.mkdir()
            source.mkdir(parents=True)
            database = source.parent / 'replay.sqlite'
            database.write_bytes(b'fixture; not a production database')
            identity = viewer.expected_identity('run1000')
            blocks = [{'index': 0, 'start_seconds': 0, 'end_seconds': 86400}]
            source_manifest = dict(identity, blocks=blocks)
            raw = json.dumps(source_manifest).encode()
            (source / FILE_NAME).write_bytes(raw)
            row = dict(viewer.RUNS['run1000'], source_version=hashlib.sha256(raw).hexdigest())
            identity['source_version'] = row['source_version']
            continuous = dict(identity, start_seconds=0, end_seconds=86400, window_seconds=120, window_count=720)
            config = dict(continuous=continuous, replay_window={'start_seconds': 0, 'end_seconds': 86400})
            config_raw = json.dumps(config).encode()
            (directory / 'config.json').write_bytes(config_raw)
            manifest = dict(identity, status='complete', sample_rate=1, source_directory=str(source),
                source_export_sha256=row['source_version'], source_blocks=blocks, database=str(database),
                source_type='sqlite-direct-v1', database_bytes=database.stat().st_size,
                database_mtime_ns=database.stat().st_mtime_ns, config_sha256=hashlib.sha256(config_raw).hexdigest(),
                replay_window=config['replay_window'], window_count=720, window_seconds=120)
            manifest_path = directory / 'continuous-manifest.json'
            manifest_path.write_text(json.dumps(manifest))
            # Native SQLite validator is independently responsible for full
            # metadata/identity validation; this fixture isolates the continuous
            # layer's binding to its output, without constructing real replays.
            with patch.dict(viewer.RUNS, run1000=row), patch('simz1_sqlite_source.checked_source', return_value=(source, source_manifest, database)) as checked:
                self.assertEqual(viewer.check_replay('run1000', run), (directory, database))
                checked.assert_called_once_with(str(source))
                bad = dict(manifest, replay_window={'start_seconds': 0, 'end_seconds': 108000})
                manifest_path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, '24-hour'):
                    viewer.check_replay('run1000', run)
                manifest_path.write_text(json.dumps(manifest))
                (directory / 'config.json').write_bytes(config_raw + b' ')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    viewer.check_replay('run1000', run)
                (directory / 'config.json').write_bytes(config_raw)
                database.write_bytes(b'changed size')
                with self.assertRaisesRegex(ValueError, 'size/mtime'):
                    viewer.check_replay('run1000', run)

    def test_original_source_validator_rejection_is_preserved(self):
        with patch.object(viewer, 'read_json', return_value=dict(viewer.expected_identity('run10k'),
                status='complete', sample_rate=1, source_directory='fixture')), \
                patch('simz1_sqlite_source.checked_source', side_effect=ValueError('SQLite identity rejected')):
            with self.assertRaisesRegex(ValueError, 'SQLite identity rejected'):
                viewer.check_replay('run10k', Path('fixture'))


if __name__ == '__main__':
    unittest.main()
