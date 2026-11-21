"""Small recovery fixtures. No MATSim, population generation or live servers.

The integration tests run the real recovery coordinator against a tiny SQLite
spool and 96 tiny HTML windows. Only native side-data loading is replaced: that
path is independent of movement reuse and must never recompute Motion_Plan.
"""
from contextlib import ExitStack
from copy import deepcopy
import errno
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import simz1_recover_paged as recovery
import simz1_recovery_io as recovery_io
from simz1_paged_replay import packed, windows
from simz1_run import sha256


PREFIX = b'<!doctype html><html><head><title>SimZ1 fixture</title></head><body>' + recovery_io.REPLAY_MARKER
SUFFIX = b'</script><script>window.fixtureReady=true;</script></body></html>'
AMPLE_DISK = SimpleNamespace(total=2 * 10 ** 12, used=10 ** 12, free=10 ** 12)


def decode_html(path):
    raw = Path(path).read_bytes()
    body = raw.split(recovery_io.REPLAY_MARKER, 1)[1].split(b'</script>', 1)[0]
    return json.loads(body)


def movement_records(config):
    return next(layer['data'] for layer in config['layers'] if layer['id'] == 'trips')


class PagedRecoveryFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1-recovery-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run = self.root / 'run'
        self.source = self.run / 'webgl-source'
        self.scratch = self.root / 'external-scratch'
        (self.source / 'blocks').mkdir(parents=True)
        self.scratch.mkdir()
        self.blocks = windows(0, 960, 10)
        self.native_paths = []

        def artifact(name, text):
            path = self.run / name
            path.write_text(text, encoding='utf-8')
            self.native_paths.append(path)
            return dict(path=name, sha256=sha256(path))

        events = artifact('events.xml', '<events><event time="960" type="fixture"/></events>')
        network = artifact('network.xml', '<network><nodes/><links/></network>')
        plans = artifact('plans.xml', '<population><person id="p"/></population>')
        config = artifact('config.xml', '<config/>')
        self.counts = dict(planned_persons=1, planned_trips=1, planned_legs=1)
        operational = dict(observed_departures=1, completed_legs=1, pending_legs_at_horizon=0,
                           aborted_before_horizon=0, unstarted_legs=0)
        result = dict(events=events, network=network, plans=plans, counts=operational,
                      observed_event_end_seconds=960)
        self.manifest = dict(schema_version=1, run_id='simz1-recovery-fixture', folder=str(self.run),
            status='completed', validation=dict(status='valid'), counts=self.counts,
            time_horizon=dict(start_seconds=0, end_seconds=960),
            replay_window=dict(start_seconds=0, end_seconds=960), effective_config=config,
            inputs=dict(config=config, network=network, plans=plans), results={'0': result})
        self.manifest_path = self.run / 'run-manifest.json'
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.native_paths.append(self.manifest_path)
        self.identity = dict(run_id=self.manifest['run_id'], iteration=0,
                             run_manifest_sha256=sha256(self.manifest_path))
        self.key = 'a' * 64
        self.trip = dict(Trip_ID='p:trip:1', Departure=0, Arrival=952, Status='completed',
                         Observation_End=960)
        self.records = [dict(Agent_ID='p', vehicle='v', Replay_Journey_Key=self.key,
            timestamps=[start, end], path=[[-90.5, 14.6], [-90.501, 14.601]],
            Motion_Plan=dict(status='available', phases=[dict(start=start, end=end, speed=1.25)],
                             preserved_fixture='native-plan-' + str(index)),
            Speed_kmh=4.5, Max_Speed_kmh=4.5)
            for index, (start, end) in enumerate(((1, 2), (9, 11), (801, 802), (951, 952)), 1)]
        self.database = self.source / 'replay.sqlite'
        with sqlite3.connect(self.database) as connection:
            connection.executescript('''
                CREATE TABLE segments(id INTEGER PRIMARY KEY, journey TEXT, vehicle TEXT,
                                      start REAL, end REAL, payload BLOB);
                CREATE TABLE segment_blocks(block INTEGER, segment INTEGER);
                CREATE TABLE journeys(key TEXT PRIMARY KEY, metadata TEXT);
                CREATE TABLE lane_events(seq INTEGER PRIMARY KEY, vehicle TEXT, time REAL, payload BLOB);
                CREATE TABLE export_identity(key TEXT PRIMARY KEY, value TEXT);
                CREATE INDEX segments_journey ON segments(journey,id);
                CREATE INDEX segments_block ON segment_blocks(block,segment);
                CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);
                CREATE INDEX lanes_time ON lane_events(time,seq);
            ''')
            connection.executemany('INSERT INTO export_identity VALUES (?,?)',
                                   [(key, str(value)) for key, value in self.identity.items()])
            connection.execute('INSERT INTO journeys VALUES (?,?)', (self.key, json.dumps(self.trip)))
            for index, record in enumerate(self.records, 1):
                start, end = record['timestamps']
                connection.execute('INSERT INTO segments VALUES (?,?,?,?,?,?)',
                                   (index, self.key, 'v', start, end, packed(record)))
                for block in self.blocks:
                    if start < block['end_seconds'] and end > block['start_seconds']:
                        connection.execute('INSERT INTO segment_blocks VALUES (?,?)', (block['index'], index))
        self.global_stats = dict(segments=len(self.records), reconstructed_vehicles=1,
                                 pending_link_intervals=0, unclosed_intervals_at_abort=0)
        self.visual_counts = dict(reconstructed=1, with_representable_interval=1,
                                  without_representable_interval=0, only_unavailable_motion_plans=0)
        self.side = dict(signal_replay=dict(series=[], event_count=0), incidents=[])
        self.probe = dict(time_seconds=960, vehicles_with_closed_interval_active=0,
            representable_vehicles=0, visible_agents=0, unavailable_interval_vehicles=0,
            censored_journeys=0, censored_without_any_closed_interval=0,
            censored_without_closed_interval_at_observation_end=0, source='fixture native intervals')
        for index in range(81):
            self.write_fixture_block(index)
        self.protected = {path: sha256(path) for path in [*self.native_paths, self.database]}
        self.original_blocks = {path: sha256(path) for path in (self.source / 'blocks').glob('*.html')}

    def config_for(self, index, *, include_records=True):
        block = self.blocks[index]
        records = [dict(deepcopy(record), Trip=deepcopy(self.trip)) for record in self.records
                   if record['timestamps'][0] < block['end_seconds'] and record['timestamps'][1] > block['start_seconds']]
        vehicles = len({record['vehicle'] for record in records})
        return dict(layers=[
            {'@@type': 'LineLayer', 'data': [], 'id': 'roads'},
            {'@@type': 'ScatterplotLayer', 'data': records if include_records else [],
             'getFillColor': '@@=color', 'id': 'trips'},
            {'@@type': 'IconLayer', 'data': [], 'getIcon': '@@=icon', 'id': 'incidents'}],
            hud=dict(run_id=self.identity['run_id'], iteration=0, reconstructed_vehicles=vehicles, **self.counts),
            pagination=dict(block_index=index, block_count=96, window_seconds=10,
                blocks=deepcopy(self.blocks), loaded_segments=len(records), sample_rate=1.0,
                total_segments=len(self.records), total_reconstructed_vehicles=1,
                visual_vehicle_counts=deepcopy(self.visual_counts)),
            replay_window={key: block[key] for key in ('start_seconds', 'end_seconds')},
            time_horizon=deepcopy(self.manifest['time_horizon']), trajectory_stats=deepcopy(self.global_stats),
            motion_sources=dict(plans=deepcopy(self.manifest['results']['0']['plans'])),
            visual_motion=dict(settings=dict(enabled=True)), trajectories_only=True,
            operational_counts=deepcopy(self.manifest['results']['0']['counts']))

    def write_fixture_block(self, index, config=None):
        path = self.source / 'blocks' / self.blocks[index]['url']
        value = self.config_for(index) if config is None else config
        path.write_bytes(PREFIX + json.dumps(value, separators=(',', ':')).encode('utf-8') + SUFFIX)
        return path

    def patches(self, *, free=None):
        stack = ExitStack()
        stack.enter_context(patch('simz1_recovery_io.shutil.disk_usage',
                                 return_value=AMPLE_DISK if free is None else SimpleNamespace(total=100, used=100-free, free=free)))
        self.side_mock = stack.enter_context(patch('simz1_recovery_native.recover_side_data',
                                                   return_value=deepcopy(self.side)))
        stack.enter_context(patch('simz1_recovery_native.derive_observation_probe',
                                 return_value=deepcopy(self.probe)))
        return stack

    def recover(self, **kwargs):
        return recovery.recover(self.run, self.source, temp_dir=self.scratch,
                                reserve_bytes=0, expected_blocks=96, **kwargs)

    def assert_protected_unchanged(self):
        self.assertEqual({path: sha256(path) for path in self.protected}, self.protected)
        self.assertEqual({path: sha256(path) for path in self.original_blocks}, self.original_blocks)

    def test_manifest_absent_audit_is_read_only_and_finds_exact_missing_blocks(self):
        before = set(self.run.rglob('*'))
        result = self.recover(audit_only=True)
        self.assertEqual(result['valid_blocks'], 81)
        self.assertEqual(result['expected_blocks'], 96)
        self.assertEqual(result['missing_blocks'], list(range(81, 96)))
        self.assertEqual(result['invalid_blocks'], {})
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertFalse(result['complete'])
        self.assertEqual(before, set(self.run.rglob('*')))
        self.assertFalse((self.source / 'export-manifest.json').exists())
        self.assert_protected_unchanged()

    def test_all_96_html_without_manifest_are_still_incomplete(self):
        for index in range(81, 96):
            self.write_fixture_block(index)
        result = self.recover(audit_only=True)
        self.assertEqual(result['valid_blocks'], 96)
        self.assertEqual(result['missing_blocks'], [])
        self.assertEqual(result['final_manifest'], 'absent')
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertFalse(result['complete'])

    def test_final_verification_rejects_81_of_96_but_diagnostic_is_explicit(self):
        arguments = ['--run-dir', str(self.run), '--source', str(self.source), '--reserve-gib', '0']
        before = set(self.run.rglob('*'))
        for option in ('--audit-only', '--verify-final', '--diagnose'):
            with self.subTest(option=option), patch('builtins.print') as printed:
                code = recovery.main(arguments + [option])
                report = json.loads(printed.call_args.args[0])
            self.assertEqual(code, 0 if option == '--diagnose' else recovery.EXIT_CODES['INCOMPLETE'])
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertFalse(report['complete'])
            self.assertEqual(report['verification_requested'], option != '--diagnose')
            if option == '--diagnose':
                self.assertTrue(report['diagnostic_completed'])
                self.assertEqual(report['mode'], 'diagnostic')
        self.assertEqual(before, set(self.run.rglob('*')))
        self.assert_protected_unchanged()

    def test_storage_failures_stop_before_inspecting_any_html(self):
        before = set(self.run.rglob('*'))
        failures = [recovery_io.StorageUnavailableError(errno.ENOENT, 'Unidad inexistente'),
                    PermissionError(errno.EACCES, 'Destino no escribible'),
                    OSError(errno.ENOSPC, 'Disco sin espacio')]
        for error in failures:
            with self.subTest(error=error), patch.object(recovery, 'inventory') as inspected, \
                    patch.object(recovery, 'preflight_storage', side_effect=error), \
                    self.assertRaises(OSError):
                self.recover()
            inspected.assert_not_called()
        self.assertEqual(before, set(self.run.rglob('*')))
        self.assert_protected_unchanged()

    def test_cli_failure_status_and_nonzero_codes_are_explicit(self):
        arguments = ['--run-dir', str(self.run), '--source', str(self.source), '--audit-only']
        cases = [(recovery_io.StorageUnavailableError(errno.ENOENT, 'Unidad ausente'), 'STORAGE_UNAVAILABLE'),
                 (PermissionError(errno.EACCES, 'ACL'), 'STORAGE_UNAVAILABLE'),
                 (OSError(errno.ENOSPC, 'Lleno'), 'INSUFFICIENT_SPACE'),
                 (ValueError('Manifiesto incompatible'), 'INVALID'),
                 (sqlite3.DatabaseError('database disk image is malformed'), 'INVALID')]
        for error, state in cases:
            with self.subTest(state=state), patch.object(recovery, 'recover', side_effect=error), \
                    patch('builtins.print') as printed:
                code = recovery.main(arguments)
                report = json.loads(printed.call_args.args[0])
            self.assertEqual(code, recovery.EXIT_CODES[state])
            self.assertNotEqual(code, 0)
            self.assertEqual(report['status'], state)
            self.assertFalse(report['complete'])

    def test_complete_block_is_valid_and_reused_without_compilation(self):
        path = self.source / 'blocks' / '0000.html'
        info = recovery_io.inspect_block(path, expected_identity=self.identity,
                                         expected_window=self.blocks[0])
        self.assertEqual((info['segments'], info['vehicles']), (2, 1))
        self.assertEqual(info['sha256'], self.original_blocks[path])
        real_writer = recovery.write_block
        with self.patches(), patch.object(recovery, 'write_block', wraps=real_writer) as writer:
            result = self.recover()
        self.assertEqual(result['recovery']['reused_blocks'], 81)
        self.assertEqual([call.args[0].stem for call in writer.call_args_list],
                         [f'{index:04d}' for index in range(81, 96)])
        self.assert_protected_unchanged()

    def test_interruption_after_published_block_resumes_without_duplication(self):
        real_writer = recovery.write_block

        def interrupt_after_publish(path, *args, **kwargs):
            info = real_writer(path, *args, **kwargs)
            if Path(path).stem == '0082':
                raise OSError(errno.ENOSPC, 'fixture interruption after a complete block')
            return info

        with self.patches(), patch.object(recovery, 'write_block', side_effect=interrupt_after_publish):
            with self.assertRaises(OSError):
                self.recover()
        self.assertFalse((self.source / 'export-manifest.json').exists())
        self.assertEqual(json.loads((self.source / 'recovery-state.json').read_text())['status'], 'incomplete')
        completed = {self.source / 'blocks' / f'{index:04d}.html': sha256(self.source / 'blocks' / f'{index:04d}.html')
                     for index in (81, 82)}
        with self.patches(), patch.object(recovery, 'write_block', wraps=real_writer) as writer:
            result = self.recover()
        self.assertEqual([call.args[0].stem for call in writer.call_args_list],
                         [f'{index:04d}' for index in range(83, 96)])
        self.assertEqual(result['recovery']['reused_blocks'], 83)
        self.assertEqual({path: sha256(path) for path in completed}, completed)
        for block in result['blocks']:
            records = movement_records(decode_html(self.source / 'blocks' / block['url']))
            self.assertEqual(len(records), len({tuple(record['timestamps']) for record in records}))
            for record in records:
                original = next(value for value in self.records if value['timestamps'] == record['timestamps'])
                self.assertEqual(record['Motion_Plan'], original['Motion_Plan'])
        self.assert_protected_unchanged()

    def test_insufficient_space_fails_before_large_files_or_success_manifest(self):
        before = set(self.run.rglob('*'))
        with self.patches(free=0), patch.object(recovery, 'write_block') as writer:
            with self.assertRaises(OSError) as error:
                self.recover()
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        writer.assert_not_called()
        self.assertEqual(before, set(self.run.rglob('*')))
        self.assertFalse((self.source / 'export-manifest.json').exists())
        self.assert_protected_unchanged()

    def test_space_failure_during_write_keeps_partial_and_no_final_block(self):
        destination = self.root / 'new-export' / 'blocks' / '0095.html'
        config = self.config_for(95, include_records=False)
        records = movement_records(self.config_for(95))
        calls = 0

        def fail_staged_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise OSError(errno.ENOSPC, 'fixture disk filled after opening stage')
            return dict(free_bytes=10 ** 12)

        with patch.object(recovery_io, 'ensure_space', side_effect=fail_staged_write):
            with self.assertRaises(OSError):
                recovery_io.write_block(destination, config, iter(records), PREFIX, SUFFIX,
                                         self.scratch, reserve_bytes=0)
        self.assertFalse(destination.exists())
        self.assertTrue(list(self.scratch.glob('*.partial')))
        self.assertFalse((destination.parent.parent / 'export-manifest.json').exists())
        self.assert_protected_unchanged()

    def test_truncated_block_preserved_and_rebuilt_only_in_new_destination(self):
        truncated = self.source / 'blocks' / '0081.html'
        truncated.write_bytes(PREFIX + b'{"layers":[')
        original = truncated.read_bytes()
        with self.assertRaises(ValueError):
            recovery_io.inspect_block(truncated)
        audit = self.recover(audit_only=True)
        self.assertIn(81, audit['invalid_blocks'])
        self.assertEqual(audit['status'], 'INVALID')
        self.assertFalse(audit['complete'])
        with self.patches(), self.assertRaises(ValueError):
            self.recover()
        output = self.root / 'recovered-new-destination'
        with self.patches():
            result = self.recover(output=output)
        self.assertEqual(truncated.read_bytes(), original)
        self.assertEqual(result['recovery']['reused_blocks'], 81)
        self.assertEqual(recovery_io.inspect_block(output / 'blocks' / '0081.html')['segments'], 0)
        self.assertEqual(len(list((output / 'blocks').glob('*.html'))), 96)
        self.assertFalse((output / 'replay.sqlite').exists(), 'Original SQLite is referenced read-only, not copied')
        audited = self.recover(output=output, audit_only=True)
        self.assertEqual(audited['final_manifest'], 'verified')
        self.assertEqual(audited['valid_blocks'], 96)
        self.assertEqual(audited['status'], 'COMPLETE')
        self.assertTrue(audited['complete'])
        self.assertIn(81, audited['original_invalid_blocks'])
        self.assertEqual(truncated.read_bytes(), original)
        self.assert_protected_unchanged()

    def test_incompatible_run_manifest_hash_is_rejected_before_writes(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE export_identity SET value=? WHERE key='run_manifest_sha256'", ('0' * 64,))
        before = sha256(self.database)
        with self.patches(), self.assertRaisesRegex(ValueError, 'hash|corrida'):
            self.recover()
        self.assertEqual(sha256(self.database), before)
        self.assertFalse((self.source / 'recovery-state.json').exists())
        self.assertFalse((self.source / 'export-manifest.json').exists())

    def test_incompatible_visual_settings_are_rejected_before_writes(self):
        altered = self.config_for(1)
        altered['visual_motion']['settings']['enabled'] = False
        self.write_fixture_block(1, altered)
        with self.patches(), self.assertRaisesRegex(ValueError, 'configuraciones|configuracion'):
            self.recover()
        self.assertFalse((self.source / 'recovery-state.json').exists())
        self.assertFalse((self.source / 'export-manifest.json').exists())

    def test_foreign_run_id_in_one_block_is_rejected(self):
        altered = self.config_for(1)
        altered['hud']['run_id'] = 'different-native-run'
        self.write_fixture_block(1, altered)
        with self.patches(), self.assertRaisesRegex(ValueError, 'corrida'):
            self.recover()
        self.assertFalse((self.source / 'export-manifest.json').exists())

    def test_temp_on_another_volume_uses_copy_and_preserves_original_motion(self):
        destination = self.root / 'another-volume-output' / 'blocks' / '0095.html'
        config = self.config_for(95, include_records=False)
        records = movement_records(self.config_for(95))
        original_stat = Path.stat
        real_copy = recovery_io.atomic_copy_preserve
        scratch = self.scratch

        def different_device(path, *args, **kwargs):
            stat = original_stat(path, *args, **kwargs)
            if path == scratch or scratch in path.parents:
                return SimpleNamespace(st_dev=stat.st_dev + 1, st_size=stat.st_size,
                    st_mtime_ns=stat.st_mtime_ns, st_ino=stat.st_ino, st_mode=stat.st_mode,
                    st_atime=stat.st_atime, st_mtime=stat.st_mtime)
            return stat

        with patch('simz1_recovery_io.shutil.disk_usage', return_value=AMPLE_DISK), \
                patch.object(Path, 'stat', different_device), \
                patch.object(recovery_io, 'atomic_copy_preserve', wraps=real_copy) as copied:
            info = recovery_io.write_block(destination, config, iter(records), PREFIX, SUFFIX,
                                            self.scratch, reserve_bytes=0)
        copied.assert_called_once()
        self.assertEqual(copied.call_args.args[1], destination)
        self.assertEqual(info['segments'], 1)
        self.assertEqual(movement_records(decode_html(destination)), records)
        self.assertEqual(recovery_io.inspect_block(destination)['sha256'], sha256(destination))
        self.assert_protected_unchanged()

    def test_final_manifest_is_last_atomic_success_and_requires_96_of_96(self):
        real_atomic = recovery.atomic_json_preserve
        publications = []

        def observe_publication(path, value, *args, **kwargs):
            path = Path(path)
            publications.append(path.name)
            if path.name == 'export-manifest.json':
                self.assertEqual(len(value['blocks']), 96)
                self.assertEqual([block['index'] for block in value['blocks']], list(range(96)))
                self.assertTrue((self.source / 'index.html').is_file())
                for block in value['blocks']:
                    info = recovery_io.inspect_block(self.source / 'blocks' / block['url'])
                    self.assertEqual(info['sha256'], block['sha256'])
            return real_atomic(path, value, *args, **kwargs)

        with self.patches(), patch.object(recovery, 'atomic_json_preserve', side_effect=observe_publication):
            result = self.recover()
        self.assertEqual(publications[-1], 'export-manifest.json')
        final = json.loads((self.source / 'export-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(final, result)
        self.assertEqual(final['status'], 'complete')
        self.assertEqual(final['recovery']['verified_blocks'], 96)
        self.assertEqual(len(list((self.source / 'blocks').glob('*.html'))), 96)
        self.assertEqual(sum(block['segments'] for block in final['blocks']), 5,
                         'One native cross-window segment appears in both relevant windows only')
        self.assert_protected_unchanged()

    def test_failed_final_manifest_publication_resumes_all_96_without_recompiling(self):
        real_atomic = recovery.atomic_json_preserve

        def fail_final(path, value, *args, **kwargs):
            if Path(path).name == 'export-manifest.json':
                raise OSError(errno.ENOSPC, 'fixture final-manifest interruption')
            return real_atomic(path, value, *args, **kwargs)

        with self.patches(), patch.object(recovery, 'atomic_json_preserve', side_effect=fail_final):
            with self.assertRaises(OSError):
                self.recover()
        self.assertFalse((self.source / 'export-manifest.json').exists())
        self.assertEqual(len(list((self.source / 'blocks').glob('*.html'))), 96)
        before = {path: sha256(path) for path in (self.source / 'blocks').glob('*.html')}
        with self.patches(), patch.object(recovery, 'write_block') as writer:
            result = self.recover()
            self.side_mock.assert_not_called()
        writer.assert_not_called()
        self.assertEqual(result['recovery']['reused_blocks'], 96)
        self.assertEqual({path: sha256(path) for path in before}, before)
        self.assert_protected_unchanged()

    def test_checkpoint_fast_path_hashes_all_blocks_but_decodes_only_contract_block(self):
        with self.patches():
            self.recover()
        original_inspect, original_hash = recovery.inspect_block, recovery.sha256
        with patch.object(recovery, 'inspect_block', wraps=original_inspect) as inspected, \
                patch.object(recovery, 'sha256', wraps=original_hash) as hashed:
            audit = self.recover(audit_only=True)
        self.assertEqual(audit['final_manifest'], 'verified')
        self.assertEqual(audit['valid_blocks'], 96)
        self.assertEqual([Path(call.args[0]).name for call in inspected.call_args_list], ['0000.html'])
        hashed_blocks = {Path(call.args[0]).name for call in hashed.call_args_list
                         if Path(call.args[0]).parent == self.source / 'blocks'}
        self.assertEqual(hashed_blocks, {f'{index:04d}.html' for index in range(96)})
        self.assert_protected_unchanged()

    def test_checkpoint_fast_path_rejects_changed_block_instead_of_trusting_receipt(self):
        with self.patches():
            self.recover()
        final_path = self.source / 'export-manifest.json'
        final_before = final_path.read_bytes()
        changed = self.source / 'blocks' / '0002.html'
        changed.write_bytes(changed.read_bytes() + b' ')
        changed_before = changed.read_bytes()
        with self.assertRaisesRegex(ValueError, 'checkpoint|Hash'):
            self.recover(audit_only=True)
        self.assertEqual(changed.read_bytes(), changed_before)
        self.assertEqual(final_path.read_bytes(), final_before)

    def test_external_final_manifest_fails_if_destination_block_missing_even_with_source(self):
        output = self.root / 'external-export'
        with self.patches():
            self.recover(output=output)
        final_path = output / 'export-manifest.json'
        final_before = final_path.read_bytes()
        missing = output / 'blocks' / '0005.html'
        retained = output / 'blocks' / '0005.retained.partial'
        missing.rename(retained)  # Fixture-only interruption; keep every byte.
        self.assertTrue((self.source / 'blocks' / '0005.html').is_file())
        with self.assertRaisesRegex(ValueError, 'ausentes|destino|incompleto'):
            self.recover(output=output, audit_only=True)
        self.assertFalse(missing.exists())
        self.assertTrue(retained.is_file())
        self.assertEqual(final_path.read_bytes(), final_before)
        self.assert_protected_unchanged()

    def test_recovered_96_block_report_feeds_real_continuous_generator(self):
        import simz1_continuous_replay as continuous

        # Match the native writer's field order: html_parts deliberately reads
        # bounded side data using these adjacent keys, never the large trips.
        for index in range(81):
            old = self.config_for(index)
            reordered = dict(layers=old.pop('layers'), hud=old.pop('hud'),
                signal_replay=dict(series=[], event_count=0,
                    window=[self.blocks[index]['start_seconds'], self.blocks[index]['end_seconds']],
                    retained_state_events=0),
                trajectory_stats=old.pop('trajectory_stats'))
            window = old.pop('replay_window')
            reordered.update(old)
            reordered.update(replay_window=window, selection_warning=None)
            self.write_fixture_block(index, reordered)
        self.original_blocks = {path: sha256(path) for path in (self.source / 'blocks').glob('*.html')}
        with self.patches():
            recovered = self.recover()
        self.assertEqual(recovered['phases_seconds'], {})
        self.assertIsNone(recovered['process_peak_working_set_bytes'])
        self.assertIn('unavailable', recovered['historical_measurements_status'])
        output = self.root / 'webgl-continuo'
        source_manifest_before = sha256(self.source / 'export-manifest.json')
        with patch.object(continuous, 'application_html', return_value='<!doctype html><html>fixture</html>'):
            result = continuous.generate(self.source, output, window_seconds=10, start=0, end=960)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['source_blocks']), 96)
        self.assertEqual(len(result['temporal_files']), 96)
        self.assertEqual(result['old_phases_seconds'], {})
        self.assertIsNone(result['old_process_peak_working_set_bytes'])
        self.assertEqual(Path(result['database']), self.database)
        self.assertEqual(json.loads((output / 'continuous-manifest.json').read_text(encoding='utf-8')), result)
        self.assertEqual(sha256(self.source / 'export-manifest.json'), source_manifest_before)
        self.assert_protected_unchanged()


class StoragePreflightFixture(unittest.TestCase):
    def test_missing_volume_never_falls_back_to_current_disk(self):
        with patch.object(Path, 'exists', return_value=False), \
                patch.object(recovery_io, 'ensure_space') as space, \
                self.assertRaises(recovery_io.StorageUnavailableError):
            recovery_io.preflight_storage(Path.cwd() / 'missing-volume' / 'export')
        space.assert_not_called()

    def test_insufficient_space_and_unwritable_destination(self):
        with tempfile.TemporaryDirectory(prefix='simz1-storage-fixture-') as temporary:
            target = Path(temporary) / 'new-output'
            with patch.object(recovery_io.shutil, 'disk_usage', return_value=SimpleNamespace(free=99, total=100)), \
                    self.assertRaises(OSError) as raised:
                recovery_io.preflight_storage(target, required_bytes=80, reserve_bytes=20)
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            with patch.object(recovery_io.tempfile, 'TemporaryFile', side_effect=PermissionError(errno.EACCES, 'fixture ACL')), \
                    self.assertRaises(recovery_io.StorageUnavailableError):
                recovery_io.preflight_storage(target, reserve_bytes=0, probe_write=True)
            self.assertFalse(target.exists())

    def test_diagnostic_is_readonly_and_reports_actual_filesystem(self):
        with tempfile.TemporaryDirectory(prefix='simz1-storage-fixture-') as temporary:
            target = Path(temporary) / 'new-output'
            with patch.object(recovery_io.tempfile, 'TemporaryFile', side_effect=AssertionError('Readonly cannot probe')):
                report = recovery_io.preflight_storage(target, reserve_bytes=0)
            self.assertFalse(target.exists())
            self.assertFalse(report['writable_verified'])
            self.assertTrue(report['filesystem']['format'])
            self.assertGreater(report['total_bytes'], 0)

    def test_fat32_rejects_a_too_large_block_before_writes(self):
        filesystem = dict(format='FAT32', readonly=False, max_file_bytes=2 ** 32 - 1)
        with patch.object(recovery_io, 'filesystem_info', return_value=filesystem), \
                self.assertRaises(recovery_io.StorageUnavailableError) as raised:
            recovery_io.preflight_storage(Path.cwd(), reserve_bytes=0, largest_file_bytes=2 ** 32)
        self.assertEqual(raised.exception.errno, errno.EFBIG)

    def test_readonly_volume_can_be_audited_but_not_used_for_recovery(self):
        filesystem = dict(format='NTFS', readonly=True, max_file_bytes=None)
        with patch.object(recovery_io, 'filesystem_info', return_value=filesystem):
            report = recovery_io.preflight_storage(Path.cwd(), reserve_bytes=0)
            self.assertTrue(report['filesystem']['readonly'])
            with self.assertRaises(recovery_io.StorageUnavailableError):
                recovery_io.preflight_storage(Path.cwd(), reserve_bytes=0, probe_write=True)


class NativeRecoveryCacheFixture(unittest.TestCase):
    def test_real_native_signal_incident_cache_preserves_both_directions_and_skips_reparse(self):
        import simz1_recovery_native as native

        with tempfile.TemporaryDirectory(prefix='simz1-native-cache-fixture-') as temporary:
            root = Path(temporary).resolve()
            scratch = root / 'scratch'
            scratch.mkdir()

            def artifact(name, content):
                path = root / name
                path.write_text(content, encoding='utf-8')
                return dict(path=name, sha256=sha256(path))

            events = artifact('events.xml', '''<events>
<event time="0" type="signalGroupStateChangedEvent" signalSystemId="crossing" signalGroupId="east" signalGroupState="GREEN"/>
<event time="0" type="signalGroupStateChangedEvent" signalSystemId="crossing" signalGroupId="west" signalGroupState="RED"/>
<event time="1" type="simz1NativeDecision" reason="turn_go" link="east-link" nextLink="west-link" nativeHasGreen="true"/>
<event time="2" type="zona1IncidentStart" link="east-link" capacityPerHour="120" freespeedMps="2"/>
<event time="3" type="zona1IncidentStart" link="west-link" capacityPerHour="200" freespeedMps="3"/>
<event time="4" type="signalGroupStateChangedEvent" signalSystemId="crossing" signalGroupId="east" signalGroupState="RED"/>
<event time="4" type="signalGroupStateChangedEvent" signalSystemId="crossing" signalGroupId="west" signalGroupState="GREEN"/>
<event time="5" type="simz1NativeDecision" reason="turn_go" link="west-link" nextLink="east-link" nativeHasGreen="true"/>
<event time="6" type="zona1IncidentRecovered" link="east-link" freespeedMps="10"/>
<event time="8" type="zona1IncidentRecovered" link="west-link" freespeedMps="11"/>
<event time="9" type="departure" person="ignored-by-side-data" link="east-link"/>
</events>''')
            network = artifact('network.xml', '<network><nodes/><links/></network>')
            effective = artifact('config.xml', '<config/>')
            groups = [dict(system_id='crossing', group_id=direction,
                           signals=[dict(signal_id=direction + '-light', link=direction + '-link',
                                         lanes=[], turning_moves=[])]) for direction in ('east', 'west')]
            links = {'east-link': {'from': [0, 0], 'to': [2, 0], 'length': 2, 'freespeed': 10},
                     'west-link': {'from': [2, 0], 'to': [0, 0], 'length': 2, 'freespeed': 11}}
            summary = dict(event_count=4, state_counts=dict(GREEN=2, RED=2), groups=2,
                           groups_with_events=2, permitted_decisions_by_state=dict(GREEN=2), duplicate_events=0)
            manifest = dict(run_id='native-cache-two-directions', status='completed', validation=dict(status='valid'),
                effective_config=effective, inputs=dict(config=effective, network=network),
                results={'0': dict(events=events, network=network, signal_events=summary)})
            manifest_path = root / 'run-manifest.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            identity = dict(run_id=manifest['run_id'], iteration=0, run_manifest_sha256=sha256(manifest_path))
            # An original block only contains its window's states. Its summary
            # refers to the full native stream and must match the recovered one.
            replay_config = dict(trajectories_only=False,
                signal_replay=dict(summary, series=[dict(group, states=[[0, 'GREEN' if index == 0 else 'RED']])
                                                   for index, group in enumerate(groups)]))
            originals = {path: sha256(path) for path in (root / 'events.xml', root / 'network.xml',
                                                        root / 'config.xml', manifest_path)}
            with patch.object(native, '_network_geometry', return_value=links), \
                    patch('simz1_signal_replay.selected_groups', return_value=groups), \
                    patch('simz1_recovery_native.shutil.disk_usage', return_value=AMPLE_DISK):
                first = native.recover_side_data(root, manifest, 0, replay_config, scratch, identity, 0)
                by_direction = {group['group_id']: group['states'] for group in first['signal_replay']['series']}
                self.assertEqual(by_direction, dict(east=[[0.0, 'GREEN'], [4.0, 'RED']],
                                                    west=[[0.0, 'RED'], [4.0, 'GREEN']]))
                for key, expected in summary.items():
                    self.assertEqual(first['signal_replay'][key], expected)
                incidents = {incident['Link_ID']: incident for incident in first['incidents']}
                self.assertEqual(set(incidents), {'east-link', 'west-link'})
                self.assertEqual((incidents['east-link']['start'], incidents['east-link']['end']), (2, 6))
                self.assertEqual((incidents['west-link']['start'], incidents['west-link']['end']), (3, 8))
                self.assertAlmostEqual(incidents['east-link']['speed'], 7.2)
                self.assertAlmostEqual(incidents['west-link']['speed'], 10.8)
                self.assertEqual(incidents['east-link']['capacity'], 120)
                self.assertEqual(incidents['west-link']['capacity'], 200)
                self.assertEqual(incidents['east-link']['position'], [1, 0])
                self.assertEqual(incidents['west-link']['position'], [1, 0])
                caches = list(scratch.glob('simz1-native-side-data-*.json'))
                self.assertEqual(len(caches), 1)
                cache = caches[0]
                cache_before = cache.read_bytes()
                with patch('simz1_run.xml_elements', side_effect=AssertionError('Cache reuse must skip XML parsing')) as parsed:
                    second = native.recover_side_data(root, manifest, 0, replay_config, scratch, identity, 0)
                parsed.assert_not_called()
                self.assertEqual(first, second)
                self.assertEqual(cache.read_bytes(), cache_before)
                corrupt = b'{"schema_version":1,"content":{"truncated":true}}'
                cache.write_bytes(corrupt)  # Fixture only: preserve and reject corrupted cache.
                with patch('simz1_run.xml_elements', side_effect=AssertionError('Corrupt cache cannot silently rebuild')) as parsed:
                    with self.assertRaisesRegex(ValueError, 'Cache nativa'):
                        native.recover_side_data(root, manifest, 0, replay_config, scratch, identity, 0)
                parsed.assert_not_called()
                self.assertEqual(cache.read_bytes(), corrupt)
            self.assertEqual({path: sha256(path) for path in originals}, originals)


if __name__ == '__main__':
    unittest.main()
