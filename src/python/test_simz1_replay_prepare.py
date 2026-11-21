"""Preparation regression fixtures: no real source, writer or simulation."""
from contextlib import contextmanager, redirect_stdout
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts/replay'))
import prepare_replay as prepare


@contextmanager
def no_lock(*args):
    yield


class ReplayPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)/'run selected'
        self.run.mkdir()
        self.manifest = dict(schema_version=1, folder=str(self.run), run_id='fixture-massive', status='completed',
            validation=dict(status='valid'), counts=dict(planned_persons=23),
            iterations=dict(first=0, last=9, completed=list(range(10))),
            results={str(index): {} for index in range(10)})
        (self.run/'run-manifest.json').write_text(json.dumps(self.manifest))

    def published_replay(self, source_name='webgl-source'):
        source = self.run/source_name/'sqlite-source'; source.mkdir(parents=True)
        expected = prepare.validate_native(self.run, 9)[1]
        actual = dict(**expected, run_directory=str(self.run), source_type='sqlite-direct-v1',
                      status='complete', sample_rate=1,
                      replay_window=dict(start_seconds=0, end_seconds=86401))
        source_file = source/'sqlite-source-manifest.json'
        source_file.write_text(json.dumps(actual))
        replay = self.run/'webgl-continuo'; replay.mkdir()
        exported = dict(**expected, source_directory=str(source), source_type='sqlite-direct-v1',
                        source_export_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
                        status='complete', sample_rate=1,
                        replay_window=dict(start_seconds=0, end_seconds=86400))
        (replay/'continuous-manifest.json').write_text(json.dumps(exported))
        return source, actual, replay

    def test_active_exporter_blocks_all_writes_and_keeps_partial(self):
        source = self.run/'webgl-source'; source.mkdir()
        partial = source/'replay.sqlite-wal'; partial.write_bytes(b'active fixture')
        execute = Mock()
        processes = [dict(ProcessId=123, CommandLine='python.exe visualizador_z1.py --run-dir selected')]
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'ya activa'):
                prepare.prepare(self.run, 9, writers=Mock(return_value=processes), execute=execute)
        execute.assert_not_called()
        self.assertEqual(partial.read_bytes(), b'active fixture')

    def test_unfinalized_sqlite_fails_before_native_reads_or_another_export(self):
        source = self.run/'webgl-source'; source.mkdir()
        files = [source/name for name in ('replay.sqlite', 'replay.sqlite-wal', 'replay.sqlite-shm')]
        for path in files:
            path.write_bytes(b'interrupted fixture '+path.name.encode())
        original = {path: path.read_bytes() for path in files}
        execute = Mock()
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                'simz1_run.select_run') as native_select:
            with self.assertRaisesRegex(ValueError, 'SQLite parcial sin finalizacion acreditada') as failure:
                prepare.prepare(self.run, 9, writers=Mock(return_value=[]), execute=execute)
        execute.assert_not_called()
        native_select.assert_not_called()
        self.assertIn('fixture-massive', str(failure.exception))
        self.assertIn("'iteration': 9", str(failure.exception))
        self.assertIn(str(source/'replay.sqlite'), str(failure.exception))
        self.assertIn('No hay reanudacion verificada', str(failure.exception))
        self.assertEqual({path: path.read_bytes() for path in files}, original)

    def test_process_identity_uses_exact_run_path(self):
        output = self.run/'webgl-source/index.html'
        processes = [dict(ProcessId=1, CommandLine=f'python.exe visualizador_z1.py --run-dir "{self.run}"'),
                     dict(ProcessId=2, CommandLine=f'python.exe visualizador_z1.py --run-dir "{self.run}-other"'),
                     dict(ProcessId=3, CommandLine=f'python.exe unrelated.py --run-dir "{self.run}"')]
        self.assertEqual([item['ProcessId'] for item in prepare.active_writers(self.run, output, processes=processes)], [1])

    def test_wrong_iteration_never_falls_back_to_last(self):
        for iteration in (-1, 10, True):
            with self.subTest(iteration=iteration), self.assertRaisesRegex(ValueError, 'iteracion no validada'):
                prepare.validate_native(self.run, iteration)
        self.assertEqual(prepare.validate_native(self.run, 9)[1]['iteration'], 9)

    def test_source_incompatibility_never_starts_export_or_server(self):
        source = self.run/'webgl-source/sqlite-source'; source.mkdir(parents=True)
        (source/'sqlite-source-manifest.json').write_text('{}')
        execute = Mock()
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                'simz1_sqlite_source.checked_source', return_value=(source, dict(run_id='other', iteration=9), None)):
            with self.assertRaisesRegex(ValueError, 'Fuente SQLite incompatible'):
                prepare.prepare(self.run, 9, writers=Mock(return_value=[]), execute=execute)
        execute.assert_not_called()

    def test_compatible_publication_is_reused_without_export(self):
        source, actual, replay = self.published_replay()
        execute = Mock()
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                'simz1_sqlite_source.checked_source', return_value=(source, actual, None)) as checked:
            selection = prepare.prepare(self.run, 9, writers=Mock(return_value=[]), execute=execute)
        execute.assert_not_called()
        checked.assert_called_once_with(str(source))
        self.assertEqual(selection.replay_directory, str(replay))
        self.assertEqual(selection.iteration, 9)

    def test_published_alternate_source_preserves_unfinalized_canonical_sqlite(self):
        partial = self.run/'webgl-source/replay.sqlite'; partial.parent.mkdir()
        partial.write_bytes(b'unfinalized canonical source must remain unchanged')
        before = (partial.read_bytes(), partial.stat().st_mtime_ns)
        source, actual, replay = self.published_replay('webgl-source-recovery-fixture')
        execute = Mock()
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                'simz1_sqlite_source.checked_source', return_value=(source, actual, None)) as checked:
            selection = prepare.prepare(self.run, 9, writers=Mock(return_value=[]), execute=execute)
        execute.assert_not_called()
        checked.assert_called_once_with(str(source))
        self.assertEqual(selection.replay_directory, str(replay))
        self.assertEqual((partial.read_bytes(), partial.stat().st_mtime_ns), before)

    def test_active_writer_is_checked_before_reusing_published_alternate_source(self):
        self.published_replay('webgl-source-recovery-fixture')
        execute = Mock()
        writer = dict(ProcessId=123, CommandLine='python.exe visualizador_z1.py --run-dir selected')
        with patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                'simz1_sqlite_source.checked_source') as checked:
            with self.assertRaisesRegex(ValueError, 'ya activa'):
                prepare.prepare(self.run, 9, writers=Mock(return_value=[writer]), execute=execute)
        checked.assert_not_called()
        execute.assert_not_called()

    def test_published_source_wrong_directory_or_horizon_fails_without_fallback(self):
        source, actual, _ = self.published_replay('webgl-source-recovery-fixture')
        execute = Mock()
        for change in (dict(run_directory=str(self.run.parent)),
                       dict(replay_window=dict(start_seconds=0, end_seconds=600))):
            with self.subTest(change=change), patch.object(prepare, 'preparation_lock', no_lock), redirect_stdout(io.StringIO()), patch(
                    'simz1_sqlite_source.checked_source', return_value=(source, dict(actual, **change), None)):
                with self.assertRaisesRegex(ValueError, 'Fuente del replay publicado incompatible'):
                    prepare.prepare(self.run, 9, writers=Mock(return_value=[]), execute=execute)
        execute.assert_not_called()

    def test_partial_replay_requires_native_and_source_identity(self):
        replay = self.run/'webgl-continuo'; replay.mkdir()
        config_file = replay/'config.json'
        expected = prepare.validate_native(self.run, 9)[1]
        config = dict(continuous=dict(**expected, source_version='source-hash',
                      window_seconds=120, sample_rate=1),
                      replay_window=dict(start_seconds=0, end_seconds=86400))
        config_file.write_text(json.dumps(config))
        prepare.validate_partial_replay(replay, expected, 'source-hash')
        for change in (dict(iteration=8), dict(source_version='other'), dict(source_version=None)):
            config['continuous'] = dict(expected, source_version='source-hash', window_seconds=120,
                                        sample_rate=1)
            config['continuous'].update(change)
            original = json.dumps(config)
            config_file.write_text(original)
            with self.assertRaisesRegex(ValueError, 'parcial incompatible'):
                prepare.validate_partial_replay(replay, expected, 'source-hash')
            self.assertEqual(config_file.read_text(), original)


if __name__ == '__main__':
    unittest.main()
