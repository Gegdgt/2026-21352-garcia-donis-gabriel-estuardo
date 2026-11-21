"""Small exporter lifecycle tests; no agents, MATSim, servers or real events."""
from contextlib import ExitStack
from copy import deepcopy
import errno
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import simz1_sqlite_export as exporter
from simz1_run import sha256


class SqliteExportLifecycle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1-sqlite-export-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run = self.root / 'run'
        self.run.mkdir()
        self.folder = self.root / 'source'
        self.database = self.folder / 'replay.sqlite'
        self.manifest = dict(run_id='sqlite-export-fixture', status='completed',
            validation=dict(status='valid'), time_horizon=dict(start_seconds=0, end_seconds=120),
            results={'0': dict(counts={}, observed_event_end_seconds=120)})
        (self.run / 'run-manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.selection = dict(directory=self.run, manifest=self.manifest, iteration=0,
                              network=self.run / 'network.fixture', events=self.run / 'events.fixture')
        self.identity = dict(run_id=self.manifest['run_id'], iteration=0,
                             run_manifest_sha256=sha256(self.run / 'run-manifest.json'))
        self.viewer = SimpleNamespace(SAMPLE_RATE=1, extraer_red=Mock(return_value=({}, [])),
            extraer_trayectorias=Mock(), generar_html_animado=Mock(return_value=dict(
                signal_replay=dict(series=[]), hud={}, layers=[])))
        self.published = dict(self.identity, status='complete', run_directory=str(self.run))
        self.export_options = dict(replay_start=None, replay_end=None, window_seconds=900,
                                   trajectories_only=True, visual_settings=None)
        self.published['provenance'] = dict(export_options=self.export_options)

    def mocks(self):
        stack = ExitStack()
        stack.enter_context(patch.dict(sys.modules, {'visualizador_z1': self.viewer}))
        self.publish = stack.enter_context(patch('simz1_sqlite_source.publish_source', return_value=self.published))
        self.checked = stack.enter_context(patch('simz1_sqlite_source.checked_source',
            return_value=(self.folder / 'sqlite-source', self.published, self.database)))
        self.motion = stack.enter_context(patch('simz1_motion.load_selected',
            return_value=SimpleNamespace(sources={}, visual_settings={})))
        stack.enter_context(patch('simz1_signal_replay.selected_groups', return_value=[]))
        stack.enter_context(patch.object(exporter, 'ensure_space'))
        stack.enter_context(patch.object(exporter, 'preflight_storage', return_value=dict(device=1)))
        return stack

    def export(self):
        return exporter.export_sqlite_selected(self.selection, self.folder / 'index.html',
            trajectories_only=True, temp_dir=self.root / 'scratch',
            database_budget_bytes=1024, scratch_budget_bytes=1024, reserve_bytes=0)

    def write_checkpoint(self):
        self.folder.mkdir()
        self.database.write_bytes(b'finalized fixture; publisher validation is mocked')
        stat = self.database.stat()
        pending = dict(identity=self.identity, database_stat=[stat.st_size, stat.st_mtime_ns],
            config={'fixture': 'config'}, side_data={'fixture': 'native-side-data'},
            blocks=[dict(index=0, start_seconds=0, end_seconds=120, url='0000.html')], counts={'segments': 0},
            export_options=self.export_options)
        exporter._checkpoint(self.folder / 'spool-ready.json.gz', pending, 0)
        return pending

    def test_no_space_stops_before_network_events_or_sqlite_creation(self):
        with self.mocks(), patch.object(exporter, 'preflight_storage',
                side_effect=OSError(errno.ENOSPC, 'fixture budget unavailable')), \
                patch.object(exporter, 'SqliteTrajectorySink') as sink, self.assertRaises(OSError):
            self.export()
        sink.assert_not_called()
        self.motion.assert_not_called()
        self.viewer.extraer_red.assert_not_called()
        self.viewer.extraer_trayectorias.assert_not_called()
        self.publish.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_finalized_checkpoint_resumes_only_publication(self):
        pending = self.write_checkpoint()
        original = self.database.read_bytes()
        with self.mocks():
            result = self.export()
        self.assertEqual(result, self.published)
        self.assertEqual(self.publish.call_args.args[3:6],
            (pending['config'], pending['side_data'], pending['blocks']))
        self.motion.assert_not_called()
        self.viewer.extraer_trayectorias.assert_not_called()
        self.assertEqual(self.database.read_bytes(), original)

    def test_complete_source_skips_event_extraction_and_republication(self):
        from simz1_sqlite_source import FILE_NAME
        contract = self.folder / 'sqlite-source'
        contract.mkdir(parents=True)
        (contract / FILE_NAME).write_text('{}', encoding='utf-8')
        with self.mocks():
            self.assertEqual(self.export(), self.published)
        self.checked.assert_called_once_with(contract)
        self.publish.assert_not_called()
        self.motion.assert_not_called()
        self.viewer.extraer_trayectorias.assert_not_called()

    def test_existing_unfinalized_database_is_preserved_and_never_reextracted(self):
        self.folder.mkdir()
        original = b'fixture interrupted spool'
        self.database.write_bytes(original)
        with self.mocks(), self.assertRaisesRegex(ValueError, 'sin checkpoint'):
            self.export()
        self.assertEqual(self.database.read_bytes(), original)
        self.viewer.extraer_trayectorias.assert_not_called()
        self.publish.assert_not_called()

    def test_changed_options_cannot_silently_reuse_finalized_checkpoint(self):
        self.write_checkpoint()
        with self.mocks(), self.assertRaisesRegex(ValueError, 'Opciones diferentes'):
            exporter.export_sqlite_selected(self.selection, self.folder / 'index.html',
                trajectories_only=True, window_seconds=120, reserve_bytes=0)
        self.publish.assert_not_called()
        self.viewer.extraer_trayectorias.assert_not_called()

    def test_corrupt_checkpoint_is_preserved_and_never_reextracted(self):
        self.write_checkpoint()
        path = self.folder / 'spool-ready.json.gz'
        original = path.read_bytes()[:-8]
        path.write_bytes(original)
        with self.mocks(), self.assertRaises((EOFError, ValueError, OSError)):
            self.export()
        self.assertEqual(path.read_bytes(), original)
        self.viewer.extraer_trayectorias.assert_not_called()
        self.publish.assert_not_called()

    def fake_store(self):
        fixture = self

        class Store:
            def __init__(self, database, blocks, **kwargs):
                Path(database).write_bytes(b'fixture finalizable spool')
                self.finalized = False
                self.closed = False
                self.connection = SimpleNamespace(commit=Mock())
                self.visual_vehicle_counts = dict(reconstructed=1)
                fixture.store = self

            def set_identity(self, **kwargs):
                self.identity = kwargs

            def close(self):
                self.closed = True

        return Store

    def test_unfinalized_extraction_closes_store_and_does_not_publish(self):
        with self.mocks(), patch.object(exporter, 'SqliteTrajectorySink', self.fake_store()), \
                self.assertRaisesRegex(ValueError, 'sin finalizacion'):
            self.export()
        self.assertTrue(self.store.closed)
        self.assertFalse((self.folder / 'spool-ready.json.gz').exists())
        self.publish.assert_not_called()

    def test_publication_interruption_resumes_without_second_extraction(self):
        def extract(*args, segment_sink, stats, **kwargs):
            segment_sink.finalized = True
            stats.update(segments=0, reconstructed_vehicles=1)

        self.viewer.extraer_trayectorias.side_effect = extract
        with self.mocks(), patch.object(exporter, 'SqliteTrajectorySink', self.fake_store()):
            self.publish.side_effect = RuntimeError('fixture publication interruption')
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                self.export()
            self.assertTrue(self.store.closed)
            self.assertTrue((self.folder / 'spool-ready.json.gz').is_file())
            self.publish.side_effect = None
            self.assertEqual(self.export(), self.published)
        self.viewer.extraer_trayectorias.assert_called_once()
        self.assertEqual(self.publish.call_count, 2)


if __name__ == '__main__':
    unittest.main()
