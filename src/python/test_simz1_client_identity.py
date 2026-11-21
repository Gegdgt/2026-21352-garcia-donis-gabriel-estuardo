"""Prepared metadata/client checks; no real HTTP, browser, SQLite or MATSim.

All files are minimal synthetic metadata inside TemporaryDirectory. Tests read
the current frontend sources but never rewrite a run or generate replay data.
"""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import inspect_simz1_client as inspector
from simz1_continuous_replay import application_html


def encoded(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def client_build(document):
    marker = 'window.simz1ClientBuild=Object.freeze('
    start = document.index(marker) + len(marker)
    return json.loads(document[start:document.index(');</script>', start)])


class Response(io.BytesIO):
    headers = {'Cache-Control': 'no-store'}


class ClientIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='simz1-client-fixture-')
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.native, self.source, self.viewer = (root / name for name in ('native', 'source', 'viewer'))
        for directory in (self.native, self.source, self.viewer):
            directory.mkdir()
        native = encoded({'run_id': 'synthetic-client-fixture', 'results': {'0': {}}})
        (self.native / 'run-manifest.json').write_bytes(native)
        self.identity = dict(run_id='synthetic-client-fixture', iteration=0, run_manifest_sha256=digest(native))
        source = encoded({**self.identity, 'run_directory': str(self.native)})
        (self.source / 'sqlite-source-manifest.json').write_bytes(source)
        self.replay_source = dict(source_type='sqlite-direct-v1', source_manifest_sha256=digest(source))
        self.config = dict(continuous={**self.identity, 'source_version': digest(source)}, hud={**self.identity, 'planned_persons': 3})
        config = encoded(self.config)
        (self.viewer / 'config.json').write_bytes(config)
        manifest = {**self.identity, 'source_type': 'sqlite-direct-v1', 'source_directory': str(self.source),
                    'source_export_sha256': digest(source), 'config_sha256': digest(config)}
        (self.viewer / 'continuous-manifest.json').write_bytes(encoded(manifest))
        self.replay_source.update(database_sha256=None, database_bytes=None, database_mtime_ns=None,
                                  replay_manifest_sha256=digest(encoded(manifest)))
        self.current = application_html().encode('utf-8')
        (self.viewer / 'index.html').write_bytes(self.current)

    def test_build_hashes_actual_sources_and_changes_with_controls(self):
        directory = Path(__file__).parent
        files = dict(template='visualizador_z1_continuous.html', controls='visualizador_z1_controls.js',
                     loader='simz1_continuous_loader.js', hud='simz1_continuous_hud.js',
                     aggregates='simz1_aggregate_view.js',
                     lanes='simz1_visual_lanes.js', picking='simz1_vehicle_picking.js',
                     queues='simz1_visual_queues.js', spatial='simz1_spatial_view.js', signals='simz1_signal_geometry.js',
                     arrivals='simz1_arrival_effects.js', incident_effects='simz1_incident_effects.js',
                     stops='simz1_transit_stops.js')
        expected = {key: digest((directory / filename).read_text(encoding='utf-8').encode('utf-8'))
                    for key, filename in files.items()}
        build = client_build(self.current.decode('utf-8'))
        self.assertEqual(build['schema_version'], 1)
        self.assertEqual(build['components'], expected)
        self.assertEqual(build['source_sha256'], digest(encoded(expected)))
        original_read = Path.read_text

        def changed_controls(path, *args, **kwargs):
            value = original_read(path, *args, **kwargs)
            return value + '\n// synthetic in-memory fingerprint probe\n' if path.name == files['controls'] else value

        with patch.object(Path, 'read_text', changed_controls):
            changed = application_html()
        replacement = client_build(changed)
        self.assertIn('// synthetic in-memory fingerprint probe', changed)
        self.assertNotEqual(replacement['components']['controls'], build['components']['controls'])
        self.assertNotEqual(replacement['source_sha256'], build['source_sha256'])
        for component in files.keys() - {'controls'}:
            self.assertEqual(replacement['components'][component], build['components'][component])

    def test_metadata_only_identity_is_bounded_and_detects_source_mutation(self):
        paths = list(Path(self.temporary.name).rglob('*'))
        before = {str(path): digest(path.read_bytes()) for path in paths if path.is_file()}
        with patch.object(inspector, 'build_opener') as forbidden_http:
            report = inspector.inspect(self.viewer)
        forbidden_http.assert_not_called()
        self.assertEqual({key: report[key] for key in inspector.IDENTITY}, self.identity)
        self.assertEqual(report['source_type'], 'sqlite-direct-v1')
        self.assertEqual(report['planned_persons'], 3)
        self.assertTrue(report['stored_application_matches_current'])
        self.assertEqual(report['loaded_browser_client'], 'not_observed')
        self.assertIsNone(report['http'])
        self.assertEqual(before, {str(path): digest(path.read_bytes()) for path in paths if path.is_file()})
        source_file = self.source / 'sqlite-source-manifest.json'
        source_file.write_bytes(source_file.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'Source manifest identity/hash mismatch'):
            inspector.inspect(self.viewer)

    def test_mock_http_reports_current_identity_and_each_mismatch(self):
        current_config = {**self.config, 'replay_source': self.replay_source}
        cases = [
            ('current', self.current, current_config, (True, True, True)),
            ('stale_client', b'<html>synthetic older client</html>', current_config, (False, True, True)),
            ('other_run', self.current, {**current_config, 'continuous': {**self.config['continuous'], 'run_id': 'other'}}, (True, False, True)),
            ('other_source', self.current, {**current_config, 'replay_source': {**self.replay_source, 'source_manifest_sha256': 'f' * 64}}, (True, True, False)),
            ('other_source_version', self.current, {**current_config, 'continuous': {**self.config['continuous'], 'source_version': 'f' * 64}}, (True, True, False)),
            ('extended_source_fields', self.current, {**current_config, 'replay_source': {**self.replay_source, 'future_field': True}}, (True, True, True)),
        ]
        for label, html, config, expected in cases:
            with self.subTest(case=label):
                opener = Mock()
                responses = {'http://127.0.0.1:8793/index.html': html,
                             'http://127.0.0.1:8793/api/config': encoded(config)}
                opener.open.side_effect = lambda url, timeout: Response(responses[url])
                with patch.object(inspector, 'build_opener', return_value=opener):
                    report = inspector.inspect(self.viewer, 'http://127.0.0.1:8793/')
                observed = report['http']
                self.assertEqual(observed['status'], 'read')
                self.assertEqual(observed['cache_control'], 'no-store')
                self.assertEqual(tuple(observed[key] for key in ('application_matches_current', 'identity_matches', 'source_matches')), expected)
                self.assertEqual(report['loaded_browser_client'], 'not_observed',
                                 'HTTP identity cannot establish what a previously opened tab loaded')
                self.assertEqual(opener.open.call_args_list, [
                    call('http://127.0.0.1:8793/index.html', timeout=3),
                    call('http://127.0.0.1:8793/api/config', timeout=3)])


if __name__ == '__main__':
    unittest.main()
