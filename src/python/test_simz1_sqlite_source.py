"""Tiny direct-source contracts; never access the massive historical run."""
from contextlib import closing
from copy import deepcopy
import errno
import gzip
import json
import math
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import simz1_sqlite_source as direct
from simz1_recover_paged import small_config
from simz1_recovery_native import _signature
from simz1_run import sha256
from simz1_paged_replay import packed, windows
import test_simz1_paged_recovery as recovery_fixture


class SqliteSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recovery_fixture.PagedRecoveryFixture('test_manifest_absent_audit_is_read_only_and_finds_exact_missing_blocks')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.output = self.fixture.root / 'direct'
        self.config = small_config(self.fixture.config_for(0))
        self.side = deepcopy(self.fixture.side)

    def publish(self, **kwargs):
        fixture = self.fixture
        return direct.publish_source(fixture.run, fixture.database, self.output,
            self.config, self.side, fixture.blocks, fixture.global_stats,
            reserve_bytes=0, **kwargs)

    def cache(self, *, side=None):
        fixture = self.fixture
        result = fixture.manifest['results']['0']
        provenance = dict(identity=fixture.identity, configuration_sha256=_signature(self.config)[0],
            sources=dict(events=result['events'], network=result['network'],
                         effective_config=fixture.manifest['effective_config'], inputs=fixture.manifest['inputs']))
        content = dict(provenance=provenance, data=self.side if side is None else side)
        envelope = dict(schema_version=1, sha256=_signature(content)[0], content=content)
        path = fixture.scratch / 'native-side.json'
        path.write_text(json.dumps(envelope), encoding='utf-8')
        return path

    def test_valid_database_source_uses_no_html_copy_and_preserves_all_native_evidence(self):
        manifest = self.publish()
        self.assertEqual(manifest['source_type'], 'sqlite-direct-v1')
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['database_sha256'], sha256(self.fixture.database))
        root, checked, database = direct.checked_source(self.output)
        self.assertEqual(database, self.fixture.database)
        self.assertEqual(checked['counts'], self.fixture.global_stats)
        self.assertEqual(len(checked['blocks']), 96)
        self.assertEqual(checked['database_validation']['integrity'], 'quick_check+sha256')
        self.assertFalse((self.output / 'export-manifest.json').exists())
        self.assertEqual(sorted(p.name for p in root.iterdir()),
                         sorted([direct.FILE_NAME, 'source-config.json', 'source-side.json']))
        self.assertEqual(direct.load_side_data(root), self.side)
        self.fixture.assert_protected_unchanged()

    def test_viewer_cannot_replace_the_verified_source_bucket_contract(self):
        from simz1_continuous_replay import ContinuousReplay
        replay, _ = self.daily_source()
        path = replay.root / 'continuous-manifest.json'
        changed = json.loads(path.read_bytes())
        changed['source_blocks'][0]['index'] = 71
        path.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'contrato temporal/base'):
            ContinuousReplay(replay.root)

    def test_boolean_timestamp_cannot_masquerade_as_native_numeric_time(self):
        from simz1_continuous_replay import ContinuousReplay, json_bytes
        record = deepcopy(self.fixture.records[0])
        record['timestamps'][0] = True
        with self.assertRaisesRegex(ValueError, 'Movimiento SQLite incompatible'):
            ContinuousReplay.validate_native_segment(json_bytes(record), self.fixture.key, 'v', 1, 2)

    def test_81_of_96_html_and_no_export_manifest_are_valid_direct_source_with_native_cache(self):
        fixture = self.fixture
        cache = self.cache()
        with patch('simz1_recovery_native.recover_side_data') as extractor:
            result = direct.build_source(fixture.run, fixture.source, self.output,
                anchor=fixture.source / 'blocks' / '0000.html', side_cache=cache, reserve_bytes=0)
        extractor.assert_not_called()
        self.assertEqual(result['provenance']['kind'], 'legacy-finalized-html-anchor')
        self.assertEqual(len(list((fixture.source / 'blocks').glob('*.html'))), 81)
        self.assertFalse((fixture.source / 'export-manifest.json').exists())
        self.assertEqual(direct.load_config(self.output)['trajectory_stats'], fixture.global_stats)
        fixture.assert_protected_unchanged()

    def test_missing_complete_side_evidence_does_not_publish_or_scan_events(self):
        with patch('simz1_recovery_native.recover_side_data') as extractor:
            with self.assertRaisesRegex(ValueError, 'cobertura completa'):
                direct.build_source(self.fixture.run, self.fixture.source, self.output, reserve_bytes=0)
        extractor.assert_not_called()
        self.assertFalse((self.output / direct.FILE_NAME).exists())

    def test_window_signal_excerpt_cannot_claim_complete_coverage(self):
        self.side['signal_replay'] = dict(event_count=2, series=[
            dict(system_id='s', group_id='g', states=[[0, 'GREEN']])])
        with self.assertRaisesRegex(ValueError, 'Cobertura semaforica incompleta'):
            self.publish()
        self.assertFalse(self.output.exists())

    def test_wrong_run_identity_is_rejected_before_any_manifest(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute("UPDATE export_identity SET value='foreign' WHERE key='run_id'")
        with self.assertRaisesRegex(ValueError, 'Identidad SQLite'):
            self.publish()
        self.assertFalse(self.output.exists())

    def test_truncated_sqlite_is_rejected_without_repair(self):
        with self.fixture.database.open('r+b') as stream:
            stream.truncate(self.fixture.database.stat().st_size - 1)
        with self.assertRaisesRegex(ValueError, 'truncado'):
            self.publish()
        self.assertFalse(self.output.exists())

    def test_corrupt_sqlite_page_is_rejected(self):
        with sqlite3.connect(self.fixture.database) as connection:
            rootpage = connection.execute("SELECT rootpage FROM sqlite_master WHERE name='segments'").fetchone()[0]
            page_size = connection.execute('PRAGMA page_size').fetchone()[0]
        with self.fixture.database.open('r+b') as stream:
            stream.seek((rootpage - 1) * page_size)
            stream.write(b'\xff')
        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            self.publish()
        self.assertFalse(self.output.exists())

    def test_open_journal_is_not_deleted_or_recovered(self):
        journal = self.fixture.database.with_name('replay.sqlite-journal')
        journal.write_bytes(b'unfinished native transaction')
        with self.assertRaisesRegex(ValueError, 'SQLite no cerrado'):
            self.publish()
        self.assertEqual(journal.read_bytes(), b'unfinished native transaction')

    def test_orphan_journey_cannot_disappear_silently_from_window_join(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute("UPDATE segments SET journey='missing' WHERE id=3")
        with self.assertRaisesRegex(ValueError, 'viajes ausentes'):
            self.publish()

    def test_orphan_temporal_index_is_rejected(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute('INSERT INTO segment_blocks VALUES(95, 999)')
        with self.assertRaisesRegex(ValueError, 'segmentos ausentes'):
            self.publish()

    def test_missing_temporal_membership_cannot_hide_a_preserved_segment(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute('DELETE FROM segment_blocks WHERE block=0 AND segment=2')
        with self.assertRaisesRegex(ValueError, 'faltan pertenencias'):
            self.publish()

    def test_duplicate_temporal_membership_is_rejected(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute('INSERT INTO segment_blocks VALUES(0,2)')
        with self.assertRaisesRegex(ValueError, 'duplicadas'):
            self.publish()

    def test_misplaced_temporal_membership_is_rejected(self):
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute('UPDATE segment_blocks SET block=5 WHERE block=0 AND segment=2')
        with self.assertRaisesRegex(ValueError, 'fuera de su ventana'):
            self.publish()

    def test_database_change_after_publication_is_rejected(self):
        self.publish()
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute("UPDATE export_identity SET value='foreign' WHERE key='run_id'")
        with self.assertRaisesRegex(ValueError, 'SQLite cambio'):
            direct.checked_source(self.output)

    def test_changed_small_metadata_is_rejected(self):
        self.publish()
        path = self.output / 'source-side.json'
        path.write_bytes(path.read_bytes().replace(b'complete-native-event-stream', b'partial-native-event-stream'))
        with self.assertRaises(ValueError):
            direct.checked_source(self.output)

    def test_insufficient_space_fails_before_reading_anchor_or_sqlite(self):
        with patch('simz1_recovery_io.shutil.disk_usage', return_value=SimpleNamespace(total=1, used=1, free=0)), \
                patch.object(direct, 'inspect_block') as inspect, patch.object(direct, 'validate_database') as validate:
            with self.assertRaises(OSError) as error:
                direct.build_source(self.fixture.run, self.fixture.source, self.output, reserve_bytes=0)
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        inspect.assert_not_called()
        validate.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_interruption_before_commit_is_unservable_and_metadata_resume_is_exact(self):
        real_writer = direct.atomic_json_preserve
        def interrupted(path, *args, **kwargs):
            if Path(path).name == direct.FILE_NAME:
                raise OSError(errno.ENOSPC, 'fixture interruption before commit marker')
            return real_writer(path, *args, **kwargs)
        with patch.object(direct, 'atomic_json_preserve', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.publish()
        with self.assertRaises(FileNotFoundError):
            direct.checked_source(self.output)
        hashes = {p.name: sha256(p) for p in self.output.iterdir()}
        self.publish()
        self.assertEqual({name: sha256(self.output / name) for name in hashes}, hashes)
        direct.checked_source(self.output)
        self.fixture.assert_protected_unchanged()

    def test_runtime_open_never_rehashes_large_database_or_reruns_quick_check(self):
        self.publish()
        with patch.object(direct, 'validate_database', side_effect=AssertionError('full validation repeated')), \
                patch.object(direct, 'sha256', side_effect=AssertionError('database hash repeated')):
            _, manifest, database = direct.checked_source(self.output)
            self.assertEqual(manifest['counts']['segments'], 4)
            with closing(direct.readonly_database(database, self.fixture.identity)) as connection:
                rows = connection.execute('SELECT id,payload FROM segments ORDER BY id').fetchall()
                self.assertEqual(len(rows), 4)
                for (_, raw), original in zip(rows, self.fixture.records):
                    self.assertEqual(direct.unpacked(raw), original)

    def daily_source(self, *, middle_corruption=False, lane_event_type='entered lane'):
        fixture = self.fixture
        fixture.blocks = windows(0, 86400, 900)
        fixture.manifest['time_horizon'] = dict(start_seconds=0, end_seconds=86400)
        fixture.manifest['replay_window'] = dict(fixture.manifest['time_horizon'])
        fixture.manifest['results']['0']['observed_event_end_seconds'] = 86400
        fixture.manifest_path.write_text(json.dumps(fixture.manifest), encoding='utf-8')
        fixture.identity['run_manifest_sha256'] = sha256(fixture.manifest_path)
        fixture.trip.update(Departure=0, Arrival=86400, Observation_End=86400,
                            Agent_Type=None, Schema=None, Vehicle_Type=None, PCU=None)
        intervals = ((0, 130), (120, 240), (28079, 28180), (43190, 43230),
                     (86330, 86400), (86400, 86400))
        template = fixture.records[0]
        fixture.records = []
        for number, (start, end) in enumerate(intervals):
            record = deepcopy(template)
            record['timestamps'] = [start, end]
            record['Motion_Plan'] = dict(status='available', native_fixture_number=number,
                                        phases=[dict(start=start, end=end, speed=1.25)])
            fixture.records.append(record)
        if middle_corruption:
            extra = deepcopy(fixture.records[0])
            extra['timestamps'] = [1, 3]
            extra['Motion_Plan'] = dict(status='available', phases=[dict(start=1, end=3, speed=1)])
            fixture.records.append(extra)
        fixture.global_stats['segments'] = len(fixture.records)
        lanes = [dict(vehicle='v', time=stamp, type=lane_event_type,
                      lane='native-' + str(index), link='fixture-link')
                 for index, stamp in enumerate((0, 120, 28080, 43200, 86340, 86400))]
        states = [[0, 'RED'], [120, 'GREEN'], [28080, 'YELLOW'], [43200, 'GREEN'],
                  [86340, 'RED'], [86400, 'GREEN']]
        self.side = dict(signal_replay=dict(event_count=6,
            state_counts=dict(RED=2, GREEN=3, YELLOW=1), groups=1,
            series=[dict(system_id='fixture-system', group_id='fixture-group', signals=[], states=states)]),
            incidents=[dict(start=28070, end=28100, Link_ID='fixture-link', position=[-90.5, 14.6])])
        with sqlite3.connect(fixture.database) as connection:
            connection.execute('DELETE FROM segments')
            connection.execute('DELETE FROM segment_blocks')
            connection.execute('DELETE FROM lane_events')
            connection.execute('UPDATE journeys SET metadata=? WHERE key=?', (json.dumps(fixture.trip), fixture.key))
            connection.execute("UPDATE export_identity SET value=? WHERE key='run_manifest_sha256'",
                               (fixture.identity['run_manifest_sha256'],))
            for number, record in enumerate(fixture.records, 1):
                start, end = record['timestamps']
                connection.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
                    (number, fixture.key, 'v', start, end,
                     packed(dict(record, vehicle='foreign') if middle_corruption and number == 2 else record)))
                for block in fixture.blocks:
                    if start < block['end_seconds'] and (end > block['start_seconds'] or
                            (start == end and start >= block['start_seconds'])):
                        connection.execute('INSERT INTO segment_blocks VALUES(?,?)', (block['index'], number))
            connection.executemany('INSERT INTO lane_events VALUES(?,?,?,?)',
                [(index, 'v', lane['time'], packed(lane)) for index, lane in enumerate(lanes, 1)])
        self.config = small_config(fixture.config_for(0))
        self.config['signal_replay'] = deepcopy(self.side['signal_replay'])
        self.config['signal_replay']['series'][0]['states'] = []
        self.config['lane_replay'] = dict(configuration_sha256=fixture.manifest['effective_config']['sha256'], events=[])
        self.publish()
        from simz1_continuous_replay import generate, ContinuousReplay
        continuous = fixture.root / 'continuous'
        generate(self.output, continuous, reserve_bytes=0)
        return ContinuousReplay(continuous), lanes

    def test_direct_daily_windows_and_seek_preserve_original_trajectories_trips_lanes_and_signals(self):
        replay, lanes = self.daily_source()
        fixture = self.fixture
        seen = {}
        # 24:00 deliberately selects the final 23:58--24:00 window, matching UI.
        for time_seconds in (0, 28080, 43200, 86340, 86400, 28080, 0, 120):
            index = min(719, int(time_seconds // 120))
            payload = replay.window(index)
            start, end = index * 120, min(86400, (index + 1) * 120)
            query_end = math.nextafter(end, math.inf) if index == 719 else end
            expected = [record for record in fixture.records if record['timestamps'][0] < query_end and
                (record['timestamps'][1] > start or (record['timestamps'][0] == record['timestamps'][1] and
                                                   record['timestamps'][0] >= start))]
            self.assertEqual(payload['segments'], expected)
            self.assertEqual(payload['trips'], {fixture.key: fixture.trip})
            for key, value in fixture.identity.items():
                self.assertEqual(payload[key], value)
            predecessors = [event for event in lanes if event['time'] < start]
            expected_lanes = predecessors[-1:] + [event for event in lanes if start <= event['time'] < query_end]
            self.assertEqual(payload['lane_replay']['events'], expected_lanes)
            native_states = self.side['signal_replay']['series'][0]['states']
            previous_states = [state for state in native_states if state[0] < start]
            expected_states = previous_states[-1:] + [state for state in native_states if start <= state[0] < query_end]
            self.assertEqual(payload['signal_replay']['series'][0]['states'], expected_states)
            comparable = {key: payload[key] for key in ('segments', 'trips', 'lane_replay', 'signal_replay', 'incidents')}
            if index in seen:
                self.assertEqual(comparable, seen[index])
            seen[index] = comparable
        self.assertEqual(replay.source_manifest['closing_segment_ids'], [6])
        self.assertIn(fixture.records[-1], seen[719]['segments'])
        complete_trip = replay.journey(fixture.key)
        self.assertEqual(complete_trip['trip'], fixture.trip)
        self.assertEqual(complete_trip['records'], [dict(record, Trip=fixture.trip) for record in fixture.records])
        self.assertEqual(complete_trip['lane_replay']['events'], lanes[:-1])
        for field in ('Agent_Type', 'Schema', 'Vehicle_Type', 'PCU'):
            self.assertIsNone(complete_trip['trip'][field])
        self.assertEqual(replay.manifest['counts']['reconstructed_vehicles'], 1)
        self.assertFalse((replay.root / 'temporal').exists())
        self.assertFalse((replay.root / 'replay.sqlite').exists())

    def test_journey_rejects_non_native_lane_event_type(self):
        replay, _ = self.daily_source(lane_event_type='invented-lane-change')
        with self.assertRaisesRegex(ValueError, 'Evento de carril incompatible con el viaje'):
            replay.journey(self.fixture.key)

    def test_complete_continuous_viewer_refuses_a_missing_source_commit_marker(self):
        replay, _ = self.daily_source()
        marker = self.output / direct.FILE_NAME
        marker.rename(self.output / (direct.FILE_NAME + '.interrupted-fixture'))
        from simz1_continuous_replay import ContinuousReplay
        with self.assertRaises((ValueError, FileNotFoundError)):
            ContinuousReplay(replay.root)

    def test_native_side_cache_explicit_bound_prevents_unbounded_write(self):
        from simz1_recovery_native import _write_cache
        path = self.fixture.scratch / 'oversized-cache.json'
        with self.assertRaisesRegex(ValueError, 'limite explicito'):
            _write_cache(path, {'data': 'fixture'}, 0, max_cache_bytes=1)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob('oversized-cache.json.partial.*')), [])

    def test_semantically_corrupt_non_probed_payload_is_rejected_on_its_window(self):
        replay, _ = self.daily_source(middle_corruption=True)
        with self.assertRaisesRegex(ValueError, 'identidad|Identidad|vehicle|vehiculo|Vehiculo'):
            replay.window(1)

    def test_unavailable_scratch_is_rejected_before_anchor_is_inspected(self):
        from simz1_recovery_io import StorageUnavailableError
        scratch = self.fixture.root / 'unavailable-volume'
        original = direct.preflight_storage
        def unavailable(path, *args, **kwargs):
            if Path(path) == scratch:
                raise StorageUnavailableError(errno.ENOENT, 'fixture unavailable volume')
            return original(path, *args, **kwargs)
        with patch.object(direct, 'preflight_storage', side_effect=unavailable), \
                patch.object(direct, 'inspect_block') as inspect:
            with self.assertRaises(StorageUnavailableError):
                direct.build_source(self.fixture.run, self.fixture.source, self.output,
                    allow_native_side_scan=True, temp_dir=scratch, reserve_bytes=0)
        inspect.assert_not_called()

    def test_new_export_api_extracts_fixture_once_and_publishes_continuous_without_html(self):
        import test_simz1_paged_replay as original_fixture
        from simz1_sqlite_export import export_sqlite_selected
        from simz1_continuous_replay import generate, ContinuousReplay
        from simz1_trajectories import extract
        import visualizador_z1 as viewer
        directory = self.fixture.root / 'new-native-run'
        directory.mkdir()
        network = directory / 'network.xml.gz'
        with gzip.open(network, 'wt', encoding='utf-8') as stream:
            stream.write('''<network><nodes>
            <node id="n0" x="770000" y="1619000"/><node id="n1" x="770100" y="1619000"/>
            <node id="n2" x="770200" y="1619000"/></nodes><links>
            <link id="a" from="n0" to="n1" length="100" freespeed="10"/>
            <link id="b" from="n1" to="n2" length="100" freespeed="10"/></links></network>''')
        events = directory / 'events.xml.gz'
        with gzip.open(events, 'wt', encoding='utf-8') as stream:
            stream.write(original_fixture.EVENTS)
        plans = directory / 'plans.xml'
        plans.write_text('<population><person id="p"/></population>', encoding='utf-8')
        effective = directory / 'effective-config.xml'
        effective.write_text('<config><module name="qsim"><param name="useLanes" value="true"/></module></config>',
                             encoding='utf-8')
        def record(path):
            return dict(path=path.name, sha256=sha256(path))
        result = dict(events=record(events), network=record(network), plans=record(plans),
            counts=dict(observed_departures=1, completed_legs=1, pending_legs_at_horizon=0),
            observed_event_end_seconds=86420)
        manifest = dict(run_id='new-sqlite-native-fixture', status='completed', validation=dict(status='valid'),
            demand_seed=17, matsim_seed=23, counts=dict(planned_persons=1, planned_trips=1),
            effective_config=record(effective), results={'0': result}, inputs=dict(network=record(network), plans=record(plans)),
            time_horizon=dict(start_seconds=0, end_seconds=86440), replay_window=dict(start_seconds=0, end_seconds=86440),
            demand_window=dict(start_seconds=0, end_seconds=86400))
        (directory / 'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        selection = dict(directory=directory, manifest=manifest, iteration=0, network=network, events=events)
        source = self.fixture.root / 'new-source'
        motion = original_fixture.context()
        motion.sources = dict(plans=result['plans'])
        options = dict(temp_dir=self.fixture.scratch, database_budget_bytes=8*1024**2,
                       scratch_budget_bytes=8*1024**2, reserve_bytes=0)
        with patch('simz1_motion.load_selected', return_value=motion) as loaded, \
                patch('simz1_signal_replay.selected_groups', return_value=original_fixture.GROUPS):
            report = export_sqlite_selected(selection, source / 'index.html', **options)
            resumed = export_sqlite_selected(selection, source / 'index.html', **options)
        loaded.assert_called_once()
        self.assertEqual(report, resumed)
        self.assertEqual(report['source_type'], 'sqlite-direct-v1')
        self.assertEqual(report['counts']['segments'], 2)
        self.assertEqual(report['counts']['reconstructed_vehicles'], 1)
        self.assertEqual(report['planned_persons'], 1)
        self.assertFalse((source / 'index.html').exists())
        self.assertFalse((source / 'blocks').exists())
        self.assertTrue((source / 'spool-ready.json.gz').is_file())
        native = {path: sha256(path) for path in (network, events, plans, effective, source / 'replay.sqlite')}
        continuous = self.fixture.root / 'new-continuous'
        generate(source / 'sqlite-source', continuous, reserve_bytes=0)
        replay = ContinuousReplay(continuous)
        terminal = replay.window(719)
        self.assertEqual(len(terminal['segments']), 1)
        key = terminal['segments'][0]['Replay_Journey_Key']
        complete = replay.journey(key)
        self.assertEqual(len(complete['records']), 2)
        self.assertEqual(complete['trip']['Arrival'], 86420)
        self.assertEqual(terminal['segments'][0]['Motion_Plan'], complete['records'][0]['Motion_Plan'])
        links, _ = viewer.extraer_red()
        baseline = extract(original_fixture.events(), links, lambda _: True, viewer.color_velocidad,
                           viewer.GEOD, motion=original_fixture.context(), stats={}, horizon=86440)
        for original, actual in zip(baseline, complete['records']):
            retained = dict(actual)
            retained.pop('Replay_Journey_Key')
            retained.pop('Max_Speed_kmh')
            self.assertEqual(retained, original)
        self.assertEqual(terminal['signal_replay']['series'][0]['states'], [[86380, 'GREEN'], [86399, 'RED']])
        self.assertEqual(terminal['lane_replay']['events'][0]['time'], 86390)
        self.assertEqual({path: sha256(path) for path in native}, native)


if __name__ == '__main__':
    unittest.main()
