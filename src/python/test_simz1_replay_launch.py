"""Tiny launcher contracts: no sockets, browser, subprocess, QSim or real exports."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1]/'scripts/replay/start_replay.py'
SPEC = importlib.util.spec_from_file_location('simz1_replay_launch_tested', SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode('utf-8')
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def config_for(selection):
    identity = {key: getattr(selection, key) for key in launcher.IDENTITY}
    provenance = {key: getattr(selection, key) for key in ('source_type', 'source_manifest_sha256',
        'replay_manifest_sha256', 'database_sha256', 'database_bytes', 'database_mtime_ns')}
    return dict(continuous=dict(identity, start_seconds=0, end_seconds=86400,
                                source_version=selection.source_manifest_sha256),
                replay_source=provenance,
                replay_window=dict(start_seconds=0, end_seconds=86400),
                hud=dict(run_id=selection.run_id, iteration=selection.iteration,
                         planned_persons=selection.planned_persons))


class ImmediateWatcher:
    """Run the readiness callback synchronously; no actual thread is created."""
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()

    def join(self, **kwargs):
        pass


class ReplayLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.run = self.project/'scenarios/zona1/montecarlo/run with spaces'
        self.manifest = dict(schema_version=1, folder=str(self.run), run_id='synthetic-23',
            status='completed', validation=dict(status='valid'),
            counts=dict(planned_persons=23, planned_trips=23),
            iterations=dict(first=0, last=2, completed=[0, 2]),
            results={'0': {}, '2': {'events': {'path': 'not-read.events.gz'}}})
        self.native_hash = write_json(self.run/'run-manifest.json', self.manifest)
        self.export = self.make_export('existing continuous')
        self.latest = self.project/'scenarios/zona1/montecarlo/latest-successful.json'
        write_json(self.latest, dict(folder=str(self.run), run_id=self.manifest['run_id'],
                                     manifest_sha256=self.native_hash))

    def make_export(self, name, iteration=2, end=90000, source_type=None):
        directory = self.run/name
        identity = dict(run_id=self.manifest['run_id'], iteration=iteration,
                        run_manifest_sha256=self.native_hash)
        source_dir = self.run/(name+' source')
        source_metadata = {'source_type': source_type} if source_type is not None else {}
        source_name = ('sqlite-source-manifest.json' if source_type == 'sqlite-direct-v1'
                       else 'export-manifest.json')
        source_hash = write_json(source_dir/source_name,
                                 dict(identity, run_directory=str(self.run), status='complete',
                                      sample_rate=1, **source_metadata))
        write_json(directory/'continuous-manifest.json', dict(identity,
            status='complete', sample_rate=1, source_directory=str(source_dir),
            source_export_sha256=source_hash,
            replay_window=dict(start_seconds=0, end_seconds=end), **source_metadata))
        return directory

    def selected(self, **kwargs):
        return launcher.resolve_selection(self.project, self.run, **kwargs)

    def components(self, selection):
        factory = Mock()
        handler = SimpleNamespace(replay=SimpleNamespace(config=config_for(selection)))
        return Mock(return_value=(factory, handler)), factory

    def test_explicit_run_uses_real_identity_last_iteration_and_no_events(self):
        selected = self.selected()
        self.assertEqual(selected.run_id, 'synthetic-23')
        self.assertEqual(selected.iteration, 2)
        self.assertEqual(selected.replay_directory, str(self.export))
        self.assertEqual(selected.run_manifest_sha256, self.native_hash)
        self.assertEqual(selected.selection_source, 'explicit-run')
        self.assertFalse((self.run/'not-read.events.gz').exists())

    def test_latest_requires_exact_id_hash_and_never_selects_a_fallback(self):
        selected = launcher.resolve_selection(self.project)
        self.assertEqual(selected.selection_source, 'latest-successful')
        for key, value in [('run_id', 'different'), ('manifest_sha256', '0'*64)]:
            reference = dict(folder=str(self.run), run_id=self.manifest['run_id'],
                             manifest_sha256=self.native_hash)
            reference[key] = value
            write_json(self.latest, reference)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'no hay fallback'):
                launcher.resolve_selection(self.project)

    def test_direct_sqlite_selects_its_own_manifest_without_paged_html_or_data_reads(self):
        direct = self.make_export('direct continuous', source_type='sqlite-direct-v1')
        selected = self.selected(replay_dir=direct)
        self.assertEqual(selected.replay_directory, str(direct))
        source_dir = self.run/'direct continuous source'
        self.assertFalse((source_dir/'export-manifest.json').exists())
        self.assertFalse((source_dir/'replay.sqlite').exists())
        self.assertFalse((source_dir/'blocks').exists())
        # The metadata stage must reject an altered source before the production
        # ContinuousReplay validator opens SQLite read-only in check/serve.
        source_path = source_dir/'sqlite-source-manifest.json'
        source = json.loads(source_path.read_text())
        write_json(source_path, dict(source, iteration=0))
        with self.assertRaisesRegex(ValueError, 'export fuente'):
            self.selected(replay_dir=direct)

    def test_unknown_or_inconsistent_source_type_is_rejected_without_fallback(self):
        direct = self.make_export('direct continuous', source_type='sqlite-direct-v1')
        manifest_path = direct/'continuous-manifest.json'
        original = json.loads(manifest_path.read_text())
        write_json(manifest_path, dict(original, source_type='unknown-v2'))
        with self.assertRaisesRegex(ValueError, 'Tipo de fuente'):
            self.selected(replay_dir=direct)
        source_path = Path(original['source_directory'])/'sqlite-source-manifest.json'
        source = json.loads(source_path.read_text())
        source_hash = write_json(source_path, dict(source, source_type='paged-html-v1'))
        write_json(manifest_path, dict(original, source_export_sha256=source_hash))
        with self.assertRaisesRegex(ValueError, 'export fuente'):
            self.selected(replay_dir=direct)

    def test_absent_latest_does_not_scan_other_runs(self):
        with self.assertRaises(FileNotFoundError):
            launcher.resolve_selection(self.project/'another project')

    def test_invalid_status_folder_or_schema_are_rejected(self):
        for change in [dict(status='failed'), dict(validation={'status': 'invalid'}),
                       dict(folder=str(self.project)), dict(schema_version=2)]:
            write_json(self.run/'run-manifest.json', dict(self.manifest, **change))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.selected()

    def test_iteration_requires_validated_result_no_silent_fallback(self):
        for iteration in (-1, 1, 3, True, 2.0):
            with self.subTest(iteration=iteration), self.assertRaisesRegex(ValueError, 'iteracion'):
                self.selected(iteration=iteration)
        with self.assertRaisesRegex(ValueError, 'No existe'):
            self.selected(iteration=0)
        early = self.make_export('iteration zero', iteration=0)
        self.assertEqual(self.selected(iteration=0).replay_directory, str(early))

    def test_ambiguous_exports_require_explicit_replay_directory(self):
        other = self.make_export('second continuous')
        with self.assertRaisesRegex(ValueError, 'ReplayDir'):
            self.selected()
        self.assertEqual(self.selected(replay_dir=other).replay_directory, str(other))

    def test_partial_or_incompatible_export_is_never_regenerated(self):
        partial = self.make_export('partial', end=600)
        with self.assertRaisesRegex(ValueError, 'jornada completa'):
            self.selected(replay_dir=partial)
        file = self.export/'continuous-manifest.json'
        original = json.loads(file.read_text())
        for change in [dict(status='incomplete'), dict(sample_rate=.5),
                       dict(run_id='other'), dict(run_manifest_sha256='0'*64)]:
            write_json(file, dict(original, **change))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'no coincide'):
                self.selected(replay_dir=self.export)
        self.assertFalse((self.export/'replay.sqlite').exists())

    def test_source_hash_and_native_directory_must_match(self):
        file = self.export/'continuous-manifest.json'
        export = json.loads(file.read_text())
        write_json(file, dict(export, source_export_sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'export fuente'):
            self.selected()
        source_file = Path(export['source_directory'])/'export-manifest.json'
        source = json.loads(source_file.read_text())
        source_hash = write_json(source_file, dict(source, run_directory=str(self.project)))
        write_json(file, dict(export, source_export_sha256=source_hash))
        with self.assertRaisesRegex(ValueError, 'export fuente'):
            self.selected()

    def test_api_identity_and_exact_day_are_checked_before_opening(self):
        selected = self.selected()
        self.assertEqual(launcher.validate_api_config(config_for(selected), selected)['replay_window']['end_seconds'], 86400)
        for section, field, value in [('continuous', 'run_id', 'other'),
                ('continuous', 'iteration', False), ('continuous', 'run_manifest_sha256', '0'*64),
                ('continuous', 'start_seconds', 1), ('continuous', 'end_seconds', 90000),
                ('replay_window', 'end_seconds', 86401), ('hud', 'run_id', 'other')]:
            config = config_for(selected)
            config[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                launcher.validate_api_config(config, selected)

    def test_check_only_validates_existing_components_without_socket_or_browser(self):
        selected = self.selected()
        components, factory = self.components(selected)
        probe, browser = Mock(), Mock()
        result = launcher.serve_selected(selected, 8792, check_only=True,
            components=components, probe=probe, open_browser=browser)
        self.assertEqual(result, 'checked')
        components.assert_called_once_with(str(self.export))
        factory.assert_not_called(); probe.assert_not_called(); browser.assert_not_called()

    def test_port_probe_only_treats_connection_refusal_as_available(self):
        opener = Mock()
        with patch.object(launcher, 'build_opener', return_value=opener):
            opener.open.side_effect = launcher.URLError(ConnectionRefusedError())
            self.assertIsNone(launcher.read_api_config('http://127.0.0.1:8792'))
            for error in [launcher.URLError(TimeoutError('occupied or unresponsive')),
                          launcher.HTTPError('http://127.0.0.1:8792/api/config', 404, 'other service', {}, None)]:
                opener.open.side_effect = error
                with self.subTest(error=error), self.assertRaises(ValueError):
                    launcher.read_api_config('http://127.0.0.1:8792')

    def test_reuse_is_explicitly_not_owned_and_never_stops_existing_server(self):
        selected = self.selected()
        components, factory = self.components(selected)
        browser, record = Mock(), Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            result = launcher.serve_selected(selected, 8792, components=components,
                probe=Mock(return_value=config_for(selected)), open_browser=browser, record=record)
        self.assertEqual(result, 'reused')
        self.assertIn('consola original', output.getvalue())
        factory.assert_not_called()
        address = launcher.viewer_url('http://127.0.0.1:8792', selected)
        browser.assert_called_once_with(address)
        record.assert_called_once_with('reused', url=address, owns_server=False)

    def test_incompatible_listener_never_binds_or_opens_browser(self):
        selected = self.selected()
        components, factory = self.components(selected)
        bad = config_for(selected); bad['continuous']['run_id'] = 'other'
        browser = Mock()
        with self.assertRaises(ValueError):
            launcher.serve_selected(selected, 8792, components=components,
                                   probe=Mock(return_value=bad), open_browser=browser)
        factory.assert_not_called(); browser.assert_not_called()

    def test_foreground_confirms_api_then_ctrl_c_closes_only_owned_server(self):
        selected = self.selected()
        for no_browser in (False, True):
            components, factory = self.components(selected)
            server = factory.return_value
            server.serve_forever.side_effect = KeyboardInterrupt
            probe = Mock(side_effect=[None, config_for(selected)])
            browser, record = Mock(), Mock()
            with self.subTest(no_browser=no_browser), patch.object(launcher.threading, 'Thread', ImmediateWatcher), redirect_stdout(io.StringIO()):
                result = launcher.serve_selected(selected, 8792, no_browser=no_browser,
                    components=components, probe=probe, open_browser=browser, record=record)
            self.assertEqual(result, 'stopped')
            self.assertEqual(probe.call_count, 2)
            server.server_close.assert_called_once_with()
            server.shutdown.assert_not_called()
            if no_browser:
                browser.assert_not_called()
            else:
                browser.assert_called_once_with(launcher.viewer_url('http://127.0.0.1:8792', selected))
            self.assertEqual([call.args[0] for call in record.call_args_list], ['ready', 'stopped'])

    def test_failed_readiness_stops_only_new_server_without_opening(self):
        selected = self.selected()
        components, factory = self.components(selected)
        bad = config_for(selected); bad['continuous']['end_seconds'] = 90000
        browser = Mock()
        with patch.object(launcher.threading, 'Thread', ImmediateWatcher), self.assertRaisesRegex(ValueError, 'No se abrio'):
            launcher.serve_selected(selected, 8792, components=components,
                probe=Mock(side_effect=[None, bad]), open_browser=browser)
        factory.return_value.shutdown.assert_called_once_with()
        factory.return_value.server_close.assert_called_once_with()
        browser.assert_not_called()

    def test_cli_propagates_selection_flags_and_writes_new_runtime_receipt(self):
        selected = self.selected()
        with patch.object(launcher, 'PROJECT', self.project), patch.object(launcher, 'resolve_selection', return_value=selected) as resolve, patch.object(launcher, 'serve_selected', return_value='checked') as serve, redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            status = launcher.main(['--run-dir', str(self.run), '--iteration', '2',
                '--replay-dir', str(self.export), '--port', '8793', '--no-browser', '--check-only'])
        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), '')
        resolve.assert_called_once_with(self.project, self.run, 2, self.export)
        self.assertEqual(serve.call_args.args, (selected, 8793))
        self.assertTrue(serve.call_args.kwargs['no_browser'])
        self.assertTrue(serve.call_args.kwargs['check_only'])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload['status'], 'checked')
        self.assertEqual(Path(payload['receipt']).parent, self.project/'runtime/replay')
        records = [json.loads(line) for line in Path(payload['receipt']).read_text().splitlines()]
        self.assertEqual(records[0]['run_manifest_sha256'], self.native_hash)

    def test_source_incomplete_cannot_be_reused_even_with_matching_hash(self):
        manifest_file = self.export/'continuous-manifest.json'
        export = json.loads(manifest_file.read_text())
        source_file = Path(export['source_directory'])/'export-manifest.json'
        source = json.loads(source_file.read_text())
        for change in (dict(status='spooling'), dict(sample_rate=.5)):
            source_hash = write_json(source_file, dict(source, **change))
            write_json(manifest_file, dict(export, source_export_sha256=source_hash))
            with self.assertRaisesRegex(ValueError, 'export fuente'):
                self.selected(replay_dir=self.export)

    def test_same_run_wrong_sqlite_or_population_is_not_reused(self):
        selected = self.selected()
        for section, field, value in [('continuous', 'source_version', 'different'),
                ('replay_source', 'source_manifest_sha256', 'different'),
                ('replay_source', 'database_sha256', 'different'),
                ('replay_source', 'database_bytes', 42),
                ('replay_source', 'database_mtime_ns', 42),
                ('replay_source', 'replay_manifest_sha256', 'different'),
                ('hud', 'planned_persons', 100)]:
            bad = config_for(selected); bad[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                launcher.validate_api_config(bad, selected)

    def test_http_probe_reads_hud_with_full_contract_and_validates_population(self):
        selected = self.selected()
        config = config_for(selected)
        hud = dict(**{key: getattr(selected, key) for key in launcher.IDENTITY},
            source_version=selected.source_manifest_sha256,
            replay_window=config['replay_window'], counts=dict(persons_generated=23))
        responses = []
        for value in (config, hud):
            response = Mock()
            response.__enter__ = Mock(return_value=io.StringIO(json.dumps(value)))
            response.__exit__ = Mock(return_value=False)
            responses.append(response)
        opener = Mock(); opener.open.side_effect = responses
        with patch.object(launcher, 'build_opener', return_value=opener):
            actual = launcher.read_api_config('http://127.0.0.1:8793')
        request = opener.open.call_args_list[1].args[0]
        self.assertIn('/api/hud?', request)
        for token in ('iteration=2', 'start_seconds=0', 'end_seconds=86400', 'source_version='):
            self.assertIn(token, request)
        launcher.validate_api_config(actual, selected)
        actual['_http_hud']['counts']['persons_generated'] = 100
        with self.assertRaisesRegex(ValueError, 'HUD HTTP'):
            launcher.validate_api_config(actual, selected)

    def test_replacement_only_after_requested_components_validate(self):
        selected = self.selected()
        components, factory = self.components(selected)
        old = config_for(selected); old['continuous']['run_id'] = 'older-run'
        replacement, browser = Mock(), Mock()
        factory.return_value.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(launcher.threading, 'Thread', ImmediateWatcher), redirect_stdout(io.StringIO()):
            result = launcher.serve_selected(selected, 8793, components=components,
                probe=Mock(side_effect=[old, None, config_for(selected)]), open_browser=browser,
                replace_existing=True, replace=replacement)
        self.assertEqual(result, 'stopped')
        replacement.assert_called_once()
        browser.assert_called_once()
        components.return_value[1].replay.config['continuous']['iteration'] = 0
        replacement.reset_mock(); browser.reset_mock()
        with self.assertRaises(ValueError):
            launcher.serve_selected(selected, 8793, components=components,
                probe=Mock(return_value=old), open_browser=browser,
                replace_existing=True, replace=replacement)
        replacement.assert_not_called(); browser.assert_not_called()

    def test_current_process_command_and_start_must_match_before_stop(self):
        selected = self.selected()
        command = f'python.exe "{self.project / "python/serve_simz1_continuous.py"}" --directory "{self.export}" --port 8793'
        process = dict(pid=123, command=command, started='2026-10-25T01:02:03Z', executable='python.exe')
        stop = Mock()
        launcher.replace_simz1_listener(8793, config_for(selected),
            snapshot=Mock(return_value=process), stop=stop, project=self.project)
        stop.assert_called_once_with(process)
        stop.reset_mock()
        with self.assertRaisesRegex(ValueError, 'cambio'):
            launcher.replace_simz1_listener(8793, config_for(selected),
                snapshot=Mock(side_effect=[process, dict(process, started='different')]),
                stop=stop, project=self.project)
        stop.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'no pertenece'):
            launcher.replace_simz1_listener(8793, config_for(selected),
                snapshot=Mock(return_value=dict(process, command='python.exe other-service.py')),
                stop=stop, project=self.project)
        stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
