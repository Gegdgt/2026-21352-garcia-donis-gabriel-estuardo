"""Small fixtures for selective cleanup; never use real simulation folders."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / 'scripts/maintenance/prune_simz1_runs.py'
SPEC = importlib.util.spec_from_file_location('selective_prune', MODULE)
prune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune)


class SelectivePruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).absolute()
        self.protected = self.root / 'runs/keep'
        self.old = self.root / 'runs/old'
        self.evidence = self.root / 'runtime/maintenance/evidence'
        self.evidence.mkdir(parents=True)
        self.protected.mkdir(parents=True)
        self.old.mkdir(parents=True)
        self.run_id = 'simz1-' + 'a' * 32
        self.old_id = 'simz1-' + 'b' * 32
        self.native = self.protected / 'run-manifest.json'
        self.write(self.native, dict(run_id=self.run_id, status='completed',
                   validation=dict(status='valid'), iterations=dict(completed=list(range(10))),
                   time_horizon=dict(start_seconds=0, end_seconds=86400)))
        self.write(self.old / 'run-manifest.json', dict(run_id=self.old_id,
                   folder=str(self.old), status='completed'))
        (self.old / 'events.xml.gz').write_bytes(b'old fixture native events')
        (self.protected / 'events.xml.gz').write_bytes(b'protected fixture native events')
        self.source = self.protected / 'webgl-source/sqlite-source'
        self.source.mkdir(parents=True)
        self.database = self.protected / 'webgl-source/replay.sqlite'
        self.database.write_bytes(b'fixture sqlite verified by proof gate')
        self.replay = self.protected / 'webgl-continuo'
        self.replay.mkdir()
        self.trial = self.root / 'runtime/workflow/trial.json'
        self.write(self.trial, dict(run_id=self.old_id, run_directory=str(self.old)))
        self.latest = self.root / 'runs/latest-successful.json'
        self.write(self.latest, dict(run_id=self.run_id, folder=str(self.protected)))
        self.finish_fixture()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def finish_fixture(self):
        stat = self.database.stat()
        common = dict(run_id=self.run_id, iteration=9, status='complete', sample_rate=1.0,
                      run_manifest_sha256=prune.digest(self.native), database=str(self.database),
                      database_bytes=stat.st_size, database_mtime_ns=stat.st_mtime_ns,
                      replay_window=dict(start_seconds=0, end_seconds=86400))
        self.source_manifest = self.source / 'sqlite-source-manifest.json'
        self.write(self.source_manifest, dict(common, run_directory=str(self.protected)))
        self.write(self.replay / 'continuous-manifest.json', dict(common,
                   source_directory=str(self.source), source_export_sha256=prune.digest(self.source_manifest)))
        rows = prune.snapshot(self.root, self.old)
        self.inventory = dict(root=str(self.root), protected=str(self.protected),
            protected_run_id=self.run_id, candidates=[dict(path=str(self.old), run_id=self.old_id,
            bytes=sum(x['bytes'] for x in rows), entries=rows,
            ownership_evidence=[dict(path=str(self.old / 'run-manifest.json'))])])
        self.baseline = dict(run_id=self.run_id, files=[])
        for row in prune.snapshot(self.root, self.protected):
            if not row['directory']:
                self.baseline['files'].append(dict(row, sha256=prune.digest(Path(row['path']))))
        self.proof = dict(status='passed', run_id=self.run_id, iteration=9,
            run_manifest_sha256=prune.digest(self.native),
            source_manifest_sha256=prune.digest(self.source_manifest),
            replay_manifest_sha256=prune.digest(self.replay / 'continuous-manifest.json'), checks={})
        for name in ('source', 'http', 'browser'):
            path = self.evidence / (name + '.json')
            self.write(path, dict(run_id=self.run_id, iteration=9, inspected=True))
            self.proof['checks'][name] = dict(passed=True, run_id=self.run_id, iteration=9,
                evidence_path=str(path), evidence_sha256=prune.digest(path))

    def validate(self, **kwargs):
        return prune.validate(self.root, self.inventory, self.proof, self.baseline,
                              git_files=kwargs.get('git_files', set()),
                              process_rows=kwargs.get('process_rows', []))

    def test_reuses_verified_source_and_removes_only_explicit_old_run(self):
        expected = self.latest.read_bytes()
        result = prune.apply(self.root, self.inventory, self.proof, self.baseline,
                             self.evidence / 'journal', git_files=set(), process_rows=[])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['removed_bytes'], self.inventory['candidates'][0]['bytes'])
        self.assertFalse(self.old.exists())
        self.assertTrue(self.protected.exists())
        self.assertEqual(self.latest.read_bytes(), expected)
        self.assertFalse(self.trial.exists())
        self.assertTrue((self.evidence / 'journal/trial.before.json').is_file())
        self.assertEqual(result['conservation_after']['status'], 'passed')
        self.assertTrue(result['backups'])

    def test_dry_validation_changes_nothing(self):
        self.assertEqual(self.validate()['status'], 'validated')
        self.assertTrue(self.old.exists())
        self.assertTrue(self.trial.exists())

    def test_long_nested_metadata_uses_compact_backup_mapping(self):
        nested = self.old / ('segment-' + 'a' * 45) / ('segment-' + 'b' * 45) / 'calidad_resultados.json'
        self.write(nested, dict(scientific_status='review_required', source='fixture'))
        original = nested.read_bytes()
        self.finish_fixture()
        journal = self.evidence / ('selective-cleanup-' + 'c' * 24)
        expanded_destination = journal / 'identity-backups' / nested.relative_to(self.root)
        self.assertGreater(len(str(expanded_destination)), 260)
        result = prune.apply(self.root, self.inventory, self.proof, self.baseline,
                             journal, git_files=set(), process_rows=[])
        self.assertEqual(result['status'], 'completed')
        saved = next(row for row in result['backups'] if row['original'] == str(nested))
        destination = Path(saved['saved'])
        self.assertEqual(destination.parent, journal / 'identity-backups')
        self.assertLessEqual(len(destination.name), 29)
        self.assertLess(len(str(destination)), 260)
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(saved['sha256'], prune.digest(destination))

    def test_protected_run_and_ancestors_are_refused(self):
        for path in (self.protected, self.protected.parent, self.protected / 'webgl-source'):
            with self.subTest(path=path), self.assertRaisesRegex(prune.Refused, 'Protected'):
                prune.protected_target(path, self.protected)

    def test_outside_workspace_and_parent_traversal_are_refused(self):
        for path in (self.root.parent, self.root / 'runs/../runs/old'):
            with self.subTest(path=path), self.assertRaises(prune.Refused):
                prune.safe_path(self.root, path)

    def test_symlink_is_not_traversed(self):
        link = self.root / 'linked'
        try:
            link.symlink_to(self.old, target_is_directory=True)
        except OSError:
            self.skipTest('Platform does not permit creating symlinks')
        with self.assertRaisesRegex(prune.Refused, 'Symlink'):
            prune.snapshot(self.root, link)

    def test_hardlink_is_refused(self):
        os.link(self.old / 'events.xml.gz', self.root / 'hardlink.gz')
        with self.assertRaisesRegex(prune.Refused, 'Hard-linked'):
            self.validate()

    def test_reparse_detection_prevents_traversal_without_symlink_privilege(self):
        original = prune.is_link
        with mock.patch.object(prune, 'is_link', side_effect=lambda p: p == self.old or original(p)):
            with self.assertRaisesRegex(prune.Refused, 'Symlink/junction/reparse'):
                prune.snapshot(self.root, self.old)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing-lock check')
    def test_active_file_handle_is_refused(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(self.old / 'events.xml.gz'), 0x80000000, 1, None, 3, 0x80, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            with self.assertRaisesRegex(prune.Refused, 'File in use'):
                self.validate()
        finally:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)

    def test_changed_inventory_is_refused(self):
        (self.old / 'events.xml.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(prune.Refused, 'Inventory changed'):
            self.validate()

    def test_new_file_is_refused(self):
        (self.old / 'unreviewed.txt').write_text('new', encoding='utf-8')
        with self.assertRaisesRegex(prune.Refused, 'Inventory changed'):
            self.validate()

    def test_candidate_in_use_is_refused_without_stopping_process(self):
        with self.assertRaisesRegex(prune.Refused, 'Candidate in use, PID=123'):
            self.validate(process_rows=[dict(ProcessId=123, CommandLine='python serve.py --directory ' + str(self.old))])

    def test_protected_process_is_allowed(self):
        self.assertEqual(self.validate(process_rows=[dict(ProcessId=123,
            CommandLine='python serve.py --directory ' + str(self.protected))])['status'], 'validated')

    def test_tracked_file_is_refused(self):
        with self.assertRaisesRegex(prune.Refused, 'Tracked/source'):
            self.validate(git_files={'runs/old/events.xml.gz'})

    def test_missing_browser_proof_is_refused(self):
        del self.proof['checks']['browser']
        with self.assertRaisesRegex(prune.Refused, 'browser'):
            self.validate()

    def test_evidence_replacement_is_refused(self):
        Path(self.proof['checks']['http']['evidence_path']).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(prune.Refused, 'Evidence fingerprint'):
            self.validate()

    def test_proof_for_another_replay_manifest_is_refused(self):
        self.proof['replay_manifest_sha256'] = '0' * 64
        with self.assertRaisesRegex(prune.Refused, 'current replay_manifest_sha256'):
            self.validate()

    def test_wrong_iteration_is_refused(self):
        self.proof['iteration'] = 8
        with self.assertRaisesRegex(prune.Refused, 'different identity'):
            self.validate()

    def test_incomplete_source_is_refused(self):
        source = prune.read_json(self.source_manifest)
        source['status'] = 'building'
        self.write(self.source_manifest, source)
        with self.assertRaisesRegex(prune.Refused, 'incomplete'):
            self.validate()

    def test_ambiguous_protected_dependency_is_refused(self):
        self.write(self.protected / 'dependency.json', dict(historical_reference=str(self.old / 'events.xml.gz')))
        with self.assertRaisesRegex(prune.Refused, 'ambiguous reference'):
            self.validate()

    def test_changed_native_file_is_refused(self):
        (self.protected / 'events.xml.gz').write_bytes(b'changed protected file')
        with self.assertRaisesRegex(prune.Refused, 'Protected baseline changed'):
            self.validate()

    def test_source_database_inside_candidate_is_refused(self):
        self.database = self.old / 'replay.sqlite'
        self.database.write_bytes(b'source dependency')
        self.finish_fixture()
        with self.assertRaisesRegex(prune.Refused, 'dependency|reference'):
            self.validate()

    def test_journal_cannot_be_inside_candidate(self):
        with self.assertRaisesRegex(prune.Refused, 'Journal overlaps'):
            prune.apply(self.root, self.inventory, self.proof, self.baseline,
                        self.old / 'journal', git_files=set(), process_rows=[])
        self.assertTrue(self.old.exists())


if __name__ == '__main__':
    unittest.main()
