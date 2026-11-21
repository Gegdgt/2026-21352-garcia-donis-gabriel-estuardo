"""Tiny XML-attribute fixtures only; never start MATSim, a server or a browser."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_incident_replay import (EVENT_SCHEMA, MAX_SAFE_US, LaneIncidentReplay, NativeIncidentAdapterUnavailable,
                                  parse_incident_events, reject_uninstalled_native_incident)


class IncidentReplayTests(unittest.TestCase):
    def event(self, state='active', *, start=100, time=None, ident='fixture-incident', **changes):
        kinds = dict(active='simz1LaneIncidentStart', resolved='simz1LaneIncidentResolved',
                     censored='simz1LaneIncidentCensored')
        until = Decimal(str(start)) + 1800
        row = dict(schema=EVENT_SCHEMA, type=kinds[state], scope='fixture_only', physicsEffect='none',
                   intendedPhysicsEffect='independent_lane_hold', adapterEvidence='fixture_gate_only_not_native',
                   adapterVersion='uninstalled', incidentId=ident, opportunityId='fixture-opportunity',
                   runId='fixture-run', iteration='0', link='fixture-link', lane='fixture-link.lane.0',
                   vehicle1='fixture-bus', vehicle2='fixture-moto', person1='fixture-person',
                   vehicleType1='fixture-bus-type', vehicleType2='fixture-moto-type',
                   startTime=str(start), scheduledEndTime=str(until), durationSeconds='1800',
                   evidenceRef='analytic-fixture:gate', state=state,
                   time=str((start if state == 'active' else until) if time is None else time))
        row.update(changes)
        return row

    def parse(self, events, *, horizon=2000, allow_fixture=True):
        return parse_incident_events(events, run_id='fixture-run', iteration=0,
                                     horizon_seconds=horizon, allow_fixture=allow_fixture)

    def assert_rejected(self, events, reason, **kwargs):
        result = self.parse(events, **kwargs)
        self.assertEqual(result['records'], [])
        self.assertIn(reason, result['counts']['reasons'])
        json.dumps(result, allow_nan=False)
        return result

    def test_exact_resolved_fixture_preserves_ids_lane_and_native_duration(self):
        start, end = self.event(), self.event('resolved')
        result = self.parse([start, end])
        record, = result['records']
        self.assertEqual(record['vehicles'], ['fixture-bus', 'fixture-moto'])
        self.assertEqual(record['lane'], 'fixture-link.lane.0')
        self.assertEqual((record['start_seconds'], record['scheduled_end_seconds'], record['end_seconds']), (100, 1900, 1900))
        self.assertEqual(record['duration_seconds'], 1800)
        self.assertEqual(record['status'], 'resolved')
        self.assertIsNone(record['censored_seconds'])
        self.assertIsNone(record['participants'][1]['person_id'])
        self.assertEqual(record['participants'][0]['person_id'], 'fixture-person')
        self.assertTrue(all(p['link_id'] == record['link_id'] and p['lane'] == record['lane'] for p in record['participants']))
        self.assertEqual(record['provenance']['start_event'], start)
        self.assertEqual(record['provenance']['terminal_event'], end)
        self.assertNotIn('position', record)
        self.assertEqual(result['scope'], 'fixture_only')
        self.assertFalse(result['adapter_installed'])

    def test_censored_horizon_never_becomes_early_recovery(self):
        result = self.parse([self.event(), self.event('censored', time=200)], horizon=200)
        record, = result['records']
        self.assertEqual(record['status'], 'censored')
        self.assertEqual(record['censored_seconds'], 200)
        self.assertEqual(record['scheduled_end_seconds'], 1900)
        self.assertIsNone(record['end_seconds'])
        self.assertEqual(record['physics_effect'], 'none')

    def test_no_terminal_event_is_diagnostic_not_invented_censorship(self):
        result = self.assert_rejected([self.event()], 'missing_terminal_event')
        self.assertEqual(result['diagnostics'][0]['event'], self.event())

    def test_default_refuses_fixtures_and_native_is_never_manually_enabled(self):
        self.assert_rejected([self.event()], 'fixture_opt_in_required', allow_fixture=False)
        for opt_in in (True, False):
            with self.subTest(allow_fixture=opt_in):
                self.assert_rejected([self.event(scope='native', adapterVersion='claimed-installed',
                    adapterEvidence='claimed-adapter', physicsEffect='independent_lane_hold')],
                    'adapter_not_installed', allow_fixture=opt_in)
        self.assert_rejected([self.event(scope='native', decision='FORCE')], 'adapter_not_installed')
        with self.assertRaises(TypeError):
            LaneIncidentReplay('fixture-run', 0, 2000, acceptsNative=True)

    def test_unrecognized_type_and_schema_preserve_raw_evidence_without_color(self):
        for changes in (dict(type='simz1LaneIncidentUnexpected'), dict(schema='future-v9')):
            row = self.event(**changes)
            result = self.assert_rejected([row], 'unknown_incident_type_or_schema')
            self.assertEqual(result['diagnostics'][0]['event'], row)

    def test_legacy_design_and_force_never_enter_colored_records(self):
        rows = [dict(type='zona1IncidentStart', time='100', link='legacy-link'),
                dict(type='simz1SyntheticIncidentDesign', time='100'),
                dict(type='simz1NativeDecision', time='100', decision='FORCE', vehicle='fixture-car')]
        result = self.parse(rows)
        self.assertEqual(result['records'], [])
        self.assertEqual(set(result['counts']['reasons']),
                         {'legacy_incident_excluded', 'design_annotation_excluded', 'forced_transition_excluded'})

    def test_exact_duplicate_is_idempotent_but_contradiction_invalidates_record(self):
        start, end = self.event(), self.event('resolved')
        result = self.parse([start, deepcopy(start), end, deepcopy(end)])
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['counts']['duplicate_events'], 2)
        different = self.event(vehicle2='fixture-other')
        self.assert_rejected([start, different, end], 'contradictory_duplicate_event')

    def test_participant_permutation_preserves_association(self):
        end = self.event('resolved')
        for prefix in ('vehicle', 'vehicleType'):
            end[prefix+'1'], end[prefix+'2'] = end[prefix+'2'], end[prefix+'1']
        del end['person1']
        end['person2'] = 'fixture-person'
        result = self.parse([self.event(), end])
        self.assertEqual(result['records'][0]['participants'][0]['person_id'], 'fixture-person')

    def test_two_distinct_exact_participants_and_same_lane_required(self):
        for changes, reason in (
            (dict(vehicle2='fixture-bus'), 'two_distinct_vehicles_required'),
            (dict(vehicle3='fixture-extra'), 'exactly_two_participants_required'),
            (dict(vehicle2=None), 'missing_exact_identity_or_lane'),
            (dict(vehicleType2=None), 'missing_exact_identity_or_lane'),
            (dict(lane2='fixture-parallel-lane'), 'participants_not_on_exact_same_lane'),
            (dict(link2='fixture-other-link'), 'participants_not_on_exact_same_lane'),
            (dict(person2=''), 'invalid_optional_person'),
        ):
            with self.subTest(changes=changes):
                self.assert_rejected([self.event(**changes)], reason)

    def test_terminal_cannot_replace_identity_lane_or_participants(self):
        for changes in (dict(lane='fixture-parallel-lane'), dict(link='fixture-other-link'),
                        dict(vehicle2='fixture-other'), dict(person1='fixture-other-person'),
                        dict(evidenceRef='another-evidence'), dict(opportunityId='another-opportunity')):
            with self.subTest(changes=changes):
                self.assert_rejected([self.event(), self.event('resolved', **changes)],
                                     'terminal_identity_or_participants_mismatch')

    def test_duration_exact_not_any_early_or_late_recovery(self):
        for changes, reason in ((dict(durationSeconds='1799'), 'duration_must_be_exactly_1800_seconds'),
                                (dict(scheduledEndTime='1899'), 'duration_must_be_exactly_1800_seconds'),
                                (dict(time='1899'), 'invalid_lifecycle_boundary'),
                                (dict(time='1901'), 'invalid_lifecycle_boundary')):
            with self.subTest(changes=changes):
                self.assert_rejected([self.event(), self.event('resolved', **changes)], reason)
        for cutoff in (199, 201, 1900):
            self.assert_rejected([self.event(), self.event('censored', time=cutoff)],
                                 'event_outside_observed_horizon' if cutoff == 201 else 'invalid_lifecycle_boundary',
                                 horizon=2000 if cutoff == 1900 else 200)

    def test_chronology_horizon_and_state_fail_closed(self):
        self.assert_rejected([self.event('resolved')], 'terminal_without_start')
        self.assert_rejected([self.event('resolved'), self.event()], 'non_monotonic_incident_chronology')
        self.assert_rejected([self.event(state='active', time=101)], 'invalid_lifecycle_boundary')
        self.assert_rejected([self.event(type='simz1LaneIncidentResolved')], 'event_type_state_mismatch')
        self.assert_rejected([self.event(start=2000)], 'event_outside_observed_horizon')

    def test_bad_provenance_identity_and_numbers_are_diagnostics(self):
        for changes, reason in ((dict(runId='different-run'), 'run_identity_mismatch'),
                                (dict(iteration='1'), 'run_identity_mismatch'),
                                (dict(adapterEvidence=''), 'fixture_adapter_provenance_mismatch'),
                                (dict(physicsEffect='independent_lane_hold'), 'fixture_adapter_provenance_mismatch'),
                                (dict(time=True), 'invalid_timestamp'), (dict(time='NaN'), 'invalid_timestamp')):
            with self.subTest(changes=changes):
                self.assert_rejected([self.event(**changes)], reason)
        row = self.event()
        row['time'] = float('nan')
        self.assert_rejected([row], 'non_json_or_nonfinite_input')

    def test_timestamps_are_exact_microseconds_bounded_for_javascript(self):
        for value in ('-1e999999', '1e999999', '100.0000001', str(MAX_SAFE_US), '1e999999999999999999999999'):
            with self.subTest(value=value):
                self.assert_rejected([self.event(time=value)], 'invalid_timestamp')
        rows = [self.event(start=100.000001), self.event('resolved', start=100.000001)]
        self.assertEqual(len(self.parse(rows)['records']), 1)

    def test_overlapping_lane_and_vehicle_invalidate_both_incidents(self):
        for second_fields, reason in (
            (dict(vehicle1='fixture-other-1', vehicle2='fixture-other-2'), 'overlapping_incidents_on_exact_lane'),
            (dict(link='fixture-other-link', lane='fixture-other-lane'), 'overlapping_incidents_for_vehicle'),
        ):
            rows = [self.event(), self.event(start=101, ident='fixture-second', opportunityId='fixture-second-opportunity', **second_fields),
                    self.event('resolved'), self.event('resolved', start=101, ident='fixture-second',
                        opportunityId='fixture-second-opportunity', **second_fields)]
            self.assert_rejected(rows, reason)

    def test_exact_expiry_permits_next_incident_but_opportunity_never_repeats(self):
        rows = [self.event(), self.event('resolved'), self.event(start=1900, ident='fixture-second',
                    opportunityId='fixture-next-opportunity'),
                self.event('resolved', start=1900, ident='fixture-second', opportunityId='fixture-next-opportunity')]
        self.assertEqual(len(self.parse(rows, horizon=4000)['records']), 2)
        for row in rows[2:]:
            row['opportunityId'] = 'fixture-opportunity'
        self.assert_rejected(rows, 'repeated_opportunity_across_incident_ids', horizon=4000)

    def test_force_for_same_incident_invalidates_but_unrelated_native_force_does_not(self):
        start, end = self.event(), self.event('resolved')
        forced = self.event(decision='FORCE')
        self.assert_rejected([start, forced, end], 'forced_transition_excluded')
        native = dict(type='simz1NativeDecision', decision='FORCE', incidentId='fixture-incident', time='100')
        self.assertEqual(len(self.parse([start, native, end])['records']), 1)

    def test_payload_is_repeatable_and_independent_of_input_mutation(self):
        start, end = self.event(), self.event('resolved')
        replay = LaneIncidentReplay('fixture-run', 0, 2000, allow_fixture=True)
        replay.consume(start); replay.consume(end)
        first = replay.payload()
        start['vehicle1'] = 'mutated'; first['records'][0]['participants'][0]['vehicle_id'] = 'mutated'
        self.assertEqual(replay.payload()['records'][0]['vehicles'], ['fixture-bus', 'fixture-moto'])
        self.assertEqual(replay.payload(), replay.payload())

    def test_export_guard_has_no_bypass_and_preserves_diagnostic_event(self):
        for row in (self.event(), self.event(scope='native'), self.event(type='simz1LaneIncidentUnknown')):
            with self.assertRaises(NativeIncidentAdapterUnavailable) as caught:
                reject_uninstalled_native_incident(row)
            self.assertEqual(caught.exception.diagnostic, dict(reason='adapter_not_installed', event=row))
        for row in (dict(type='zona1IncidentStart'), dict(type='simz1NativeDecision', decision='FORCE'),
                    dict(type='entered link')):
            reject_uninstalled_native_incident(row)

    def test_trajectory_export_calls_guard_before_ignoring_new_event(self):
        from simz1_trajectories import extract
        with self.assertRaises(NativeIncidentAdapterUnavailable):
            extract([self.event()], {}, lambda _: True, lambda _: [], None)

    def test_recovery_export_calls_guard_and_does_not_write_cache(self):
        from simz1_recovery_native import recover_side_data
        with tempfile.TemporaryDirectory(prefix='simz1-incident-guard-fixture-') as temporary:
            root = Path(temporary)
            for name in ('events.xml', 'network.xml', 'config.xml', 'run-manifest.json'):
                (root / name).write_text('unchanged fixture', encoding='utf-8')
            source = lambda name: dict(path=name, sha256='fixture-sha')
            manifest = dict(run_id='fixture-run', status='completed', validation={'status': 'valid'},
                effective_config=source('config.xml'), inputs={}, results={'0': dict(
                    events=source('events.xml'), network=source('network.xml'))})
            identity = dict(run_id='fixture-run', iteration=0, run_manifest_sha256='fixture-sha')
            with patch('simz1_run.sha256', return_value='fixture-sha'), \
                 patch('simz1_run.checked_path', side_effect=lambda directory, item: directory / item['path']), \
                 patch('simz1_run.xml_elements', return_value=iter([ET.Element('event', self.event())])), \
                 patch('simz1_recovery_native._network_geometry', return_value={}), \
                 patch('simz1_signal_replay.selected_groups', return_value=[]):
                with self.assertRaises(NativeIncidentAdapterUnavailable):
                    recover_side_data(root, manifest, 0, {'signal_replay': {'series': []}}, root, identity, 0)
            self.assertEqual(len(list(root.iterdir())), 4)
            self.assertTrue(all(path.read_text(encoding='utf-8') == 'unchanged fixture' for path in root.iterdir()))


if __name__ == '__main__':
    unittest.main()
