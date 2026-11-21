"""Small synthetic HUD checks; no sockets, native events, exports or QSim."""
import hashlib
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from serve_simz1_continuous import handler_for
from simz1_continuous_replay import ContinuousReplay, checked_hud, checked_native_run, json_bytes


class ContinuousHudTests(unittest.TestCase):
    def setUp(self):
        self.horizon = dict(start_seconds=0, end_seconds=90000)
        self.metrics = dict(start_seconds=0, end_seconds=90001)
        self.visible = dict(start_seconds=0, end_seconds=86400)
        self.run = dict(run_id='synthetic-179235', status='completed', validation=dict(status='valid'),
                        time_horizon=self.horizon, counts=dict(planned_persons=179235, planned_trips=179235),
                        results={'7': dict(observed_event_end_seconds=90001,
                            counts=dict(completed_legs=150000, pending_legs_at_horizon=29235))})
        self.identity = dict(run_id=self.run['run_id'], iteration=7,
                             run_manifest_sha256=hashlib.sha256(json_bytes(self.run)).hexdigest())
        self.source = dict(**self.identity, run_directory='synthetic',
                           replay_window=self.metrics, operational_counts_observation_end_seconds=90001,
                           planned_persons=179235, planned_trips=179235,
                           operational_counts=dict(self.run['results']['7']['counts']),
                           counts=dict(reconstructed_vehicles=170001, observed_vehicles=178999))
        self.manifest = dict(**self.identity, replay_window=self.visible, source_time_horizon=self.horizon,
                             metrics_window=self.metrics, source_export_sha256='source-hash',
                             planned_persons=179235, planned_trips=179235,
                             operational_counts=dict(self.source['operational_counts']),
                             counts=dict(self.source['counts']))
        self.config = dict(time_horizon=self.horizon, replay_window=self.visible,
                           hud=dict(**self.identity, planned_persons=179235, planned_trips=179235,
                                    reconstructed_vehicles=170001),
                           operational_counts=dict(self.source['operational_counts']),
                           continuous=dict(**self.identity, source_time_horizon=self.horizon,
                               metrics_window=self.metrics, total_reconstructed_vehicles=170001))

    def payload(self):
        return checked_hud(self.run, self.source, self.manifest, self.config)

    def replay(self):
        replay = object.__new__(ContinuousReplay)
        replay.identity, replay.manifest, replay.config = self.identity, self.manifest, self.config
        replay.source_manifest, replay.source_root = self.source, Path('synthetic')
        replay.root, replay.config_raw = Path('.'), json_bytes(self.config)
        return replay

    def test_global_counts_use_native_179235_and_label_both_horizons(self):
        payload = self.payload()
        self.assertEqual(payload['schema_version'], 1)
        self.assertEqual(payload['source_version'], self.manifest['source_export_sha256'])
        self.assertEqual({key: payload[key] for key in self.identity}, self.identity)
        self.assertEqual(payload['counts'], dict(persons_generated=179235, planned_trips=179235,
                         completed_trips=150000, pending_censored_trips=29235,
                         reconstructed_vehicles=170001, vehicles_with_events=178999))
        self.assertEqual(payload['replay_window']['end_seconds'], 86400)
        self.assertEqual(payload['source_time_horizon']['end_seconds'], 90000)
        self.assertEqual(payload['metrics_window']['end_seconds'], 90001)
        self.assertIsNone(payload['native_active_series'])
        self.assertIsNone(payload['vehicle_summary']['private_vehicles'], 'Person counts alone are not vehicle evidence')
        self.assertIsNone(payload['vehicle_summary']['public_vehicles'])

    def verify_private_fixture(self):
        n = self.run['counts']['planned_persons']
        self.run['population_generation'] = dict(verified=dict(persons=n, vehicles=n,
            unique_person_ids=n, references_valid=True))

    def test_private_one_to_one_proof_and_missing_or_incompatible_evidence(self):
        self.verify_private_fixture()
        self.assertEqual(self.payload()['vehicle_summary']['private_vehicles'],179235)
        proof = self.run['population_generation']['verified']
        proof['references_valid'] = False
        self.assertIsNone(self.payload()['vehicle_summary']['private_vehicles'])
        proof['references_valid'] = True
        proof['vehicles'] -= 1
        with self.assertRaisesRegex(ValueError,'Equivalencia'): self.payload()
        proof.pop('vehicles')
        self.assertIsNone(self.payload()['vehicle_summary']['private_vehicles'])

    def test_temporal_main_only_excludes_context_and_freight(self):
        self.verify_private_fixture()
        self.run['temporal_policy'] = dict(study_date='2026-10-23')
        self.run['counts'].update(principal_cohort_persons=150000,context_persons=29235,
            warmup_context_persons=15000,post_context_persons=14235,freight_vehicles_configured=12)
        proof = self.run['population_generation']['verified']
        self.assertIsNone(self.payload()['vehicle_summary']['private_vehicles'])
        proof.update(principal_cohort_persons=150000,context_persons=29235,
            context_persons_warmup=15000,context_persons_post=14235)
        before = json_bytes(self.run)
        self.assertEqual(self.payload()['vehicle_summary']['private_vehicles'],150000)
        self.assertEqual(json_bytes(self.run),before)
        proof['principal_cohort_persons'] -= 1
        with self.assertRaisesRegex(ValueError,'Cohorte'): self.payload()

    def test_legitimate_zero_and_absent_fleet_evidence(self):
        for record in (self.run['counts'],self.source,self.manifest,self.config['hud']):
            record.update(planned_persons=0,planned_trips=0)
        for record in (self.run['results']['7']['counts'],self.source['operational_counts'],
                       self.manifest['operational_counts'],self.config['operational_counts']):
            record.update(completed_legs=0,pending_legs_at_horizon=0)
        for record in (self.source['counts'],self.manifest['counts']):
            record.update(reconstructed_vehicles=0,observed_vehicles=0)
        self.config['hud']['reconstructed_vehicles'] = 0
        self.config['continuous']['total_reconstructed_vehicles'] = 0
        self.verify_private_fixture()
        self.run['public_transport'] = dict(enabled=False,public_transport_vehicles_configured=0)
        summary = self.payload()['vehicle_summary']
        self.assertEqual((summary['private_vehicles'],summary['public_vehicles']),(0,0))
        self.run['public_transport'] = dict(enabled=True,public_transport_vehicles_configured=120)
        self.assertIsNone(self.payload()['vehicle_summary']['public_vehicles'])

    def test_identity_and_iteration_mismatches_fail_closed(self):
        for target, key, wrong in ((self.source, 'run_id', 'other'), (self.source, 'iteration', 6),
                                   (self.source, 'run_manifest_sha256', 'other'),
                                   (self.config['hud'], 'run_id', 'other'),
                                   (self.config['continuous'], 'iteration', 6)):
            original = target[key]
            with self.subTest(key=key):
                target[key] = wrong
                with self.assertRaises(ValueError):
                    self.payload()
                target[key] = original
        self.run['results'] = {'6': {}}
        with self.assertRaisesRegex(ValueError, 'Iteracion'):
            self.payload()

    def test_dated_services_count_distinct_bus_ids_without_rewriting_manifest(self):
        self.run['public_transport'] = dict(enabled=True,
            public_transport_vehicles_configured=2, fleet_vehicle_ids=['a','b'],
            fleet_by_system=dict(transmetro=3,tubus=3),
            service_counts=[dict(system=system, configured_vehicle_ids=[bus])
                for day in range(3) for system,bus in [('transmetro','a'),('tubus','b')]])
        before = json_bytes(self.run)
        configured = self.payload()['public_transport']['configured']
        self.assertEqual(configured['fleet_by_system'], dict(transmetro=1,tubus=1))
        self.assertEqual(configured['declared_fleet_by_system'], dict(transmetro=3,tubus=3))
        self.assertEqual(self.payload()['vehicle_summary']['public_vehicles'],2)
        self.assertEqual(json_bytes(self.run), before)
        self.run['public_transport']['public_transport_vehicles_configured'] = 3
        with self.assertRaisesRegex(ValueError, 'Flota HUD'):
            self.payload()

    def test_horizon_and_existing_hud_count_mismatches_fail_closed(self):
        for target, key, wrong in ((self.config, 'time_horizon', self.visible),
                (self.source, 'operational_counts_observation_end_seconds', 86400),
                (self.config['continuous'], 'metrics_window', self.visible),
                (self.source, 'planned_persons', 1), (self.config['hud'], 'planned_trips', 1),
                (self.manifest['operational_counts'], 'completed_legs', 1),
                (self.manifest['counts'], 'reconstructed_vehicles', 1)):
            original = target[key]
            with self.subTest(key=key):
                target[key] = wrong
                with self.assertRaises(ValueError):
                    self.payload()
                target[key] = original

    def test_optional_counts_are_null_without_native_or_export_evidence(self):
        self.run['results']['7'].pop('counts')
        self.source['counts'] = {}
        payload = self.payload()
        for key in ('completed_trips', 'pending_censored_trips', 'reconstructed_vehicles', 'vehicles_with_events'):
            self.assertIsNone(payload['counts'][key])
        self.assertEqual(payload['counts']['persons_generated'], 179235)
        self.assertIsNone(payload['native_active_series'])
        self.run['counts'].pop('planned_persons')
        with self.assertRaisesRegex(ValueError, 'planned_persons'):
            self.payload()

    def test_native_manifest_bytes_hash_status_and_iteration_are_checked(self):
        with patch.object(Path, 'read_bytes', return_value=json_bytes(self.run)):
            self.assertEqual(checked_native_run(self.source), self.run)
            bad = dict(self.source, run_manifest_sha256='other')
            with self.assertRaisesRegex(ValueError, 'manifiesto nativo'):
                checked_native_run(bad)
            with self.assertRaisesRegex(ValueError, 'iteracion'):
                checked_native_run(dict(self.source, iteration=6))
        invalid = dict(self.run, status='failed')
        with patch.object(Path, 'read_bytes', return_value=json_bytes(invalid)):
            bad = dict(self.source, run_manifest_sha256=hashlib.sha256(json_bytes(invalid)).hexdigest())
            with self.assertRaisesRegex(ValueError, 'completada'):
                checked_native_run(bad)

    def test_endpoint_success_identity_window_errors_and_read_failure_without_sockets(self):
        replay = self.replay()
        with patch('serve_simz1_continuous.ContinuousReplay', return_value=replay), \
                patch('serve_simz1_continuous.application_html', return_value='<html></html>'):
            handler = handler_for('.')
        good = {**self.identity, **self.visible, 'source_version': 'source-hash'}
        cases = [(good, 200), ({**good, 'iteration': 6}, 400),
                 ({**good, 'source_version': 'old-source-hash'}, 400),
                 ({**good, 'source_version': 'source-hash'}, 200),
                 ({**good, 'end_seconds': 90000}, 400), ({**good, 'start_seconds': 'nan'}, 400),
                 ({**good, 'end_seconds': [86400, 86400]}, 400),
                 ({**good, 'source_version': ['source-hash','source-hash']}, 400),
                 ({key: value for key, value in good.items() if key != 'source_version'}, 400),
                 ({key: value for key, value in good.items() if key != 'end_seconds'}, 400)]
        for query, expected in cases:
            with self.subTest(query=query), patch('simz1_continuous_replay.digest', return_value='source-hash'), \
                    patch('simz1_continuous_replay.checked_native_run', return_value=self.run):
                status, payload = self.request(handler, query)
                self.assertEqual(status, expected)
                self.assertIn('counts' if expected == 200 else 'error', payload)
        with patch('simz1_continuous_replay.digest', return_value='source-hash'), \
                patch('simz1_continuous_replay.checked_native_run', side_effect=OSError('unavailable')):
            status, payload = self.request(handler, good)
            self.assertEqual(status, 500)
            self.assertIn('error', payload)
            self.assertNotIn('counts', payload)
        with patch('simz1_continuous_replay.digest', return_value='changed'):
            status, payload = self.request(handler, good)
            self.assertEqual(status, 400)
            self.assertNotIn('counts', payload)

    def fixed_day_freight(self):
        self.horizon['end_seconds'] = self.metrics['end_seconds'] = 86400
        self.source['operational_counts_observation_end_seconds'] = 86400
        result = self.run['results']['7']
        result['observed_event_end_seconds'] = 86400
        self.run['freight_transport'] = dict(enabled=True, vehicles_configured=4,
            departures_scheduled=4, fleet_vehicle_ids=['f1','f2','f3','f4'])
        result['freight_transport_events'] = dict(vehicles_observed=2, departures_observed=4,
            arrivals_observed=1, fleet_vehicle_ids=['f1','f2'], status='valid', technical_integrity='valid',
            day_observation_policy='fixed-day-24h-v1', active_in_traffic_at_cut=1,
            waiting_for_insertion=2, scheduled_not_departed_at_cut=0, censored_at_horizon=3,
            active_or_censored=3, missing_departures=0, aborted_expeditions=0,
            observed_traffic_entries={'f1':10,'f2':20}, observed_traffic_exits={'f1':30},
            terminal_events={'f1':dict(status='completed',time=31),
                             'f2':dict(status='aborted',time=86400)},
            completion_records=[dict(vehicle_id=f'f{i}', entry_seconds={1:10,2:20}.get(i),
                traffic_exit_seconds=30 if i==1 else None, arrival_seconds=31 if i==1 else None,
                trip_outcome='completed' if i==1 else 'censored_at_horizon') for i in range(1,5)])
        result['day_observation'] = dict(policy='fixed-day-24h-v1', execution='native_day_completed',
            technical_integrity='verified_precleanup_census', coverage_end_seconds=86400,
            groups=[dict(family='pesado', od='service', scheduled_hour=0, scheduled_requests=4,
                incorporations=2, real_arrivals=1, completed=1, active_at_cut=1,
                waiting_for_incorporation=2)])

    def test_fixed_day_subset_and_census_preserve_screening_and_native_records(self):
        self.fixed_day_freight()
        before = json_bytes(self.run)
        with patch('simz1_continuous_replay.checked_screening', return_value=dict(status='review_required')):
            payload = self.payload()
        self.assertEqual(payload['screening']['status'], 'review_required')
        self.assertEqual(payload['freight_transport']['configured']['vehicles_configured'], 4)
        self.assertEqual(payload['freight_transport']['observed']['vehicles_observed'], 2)
        self.assertEqual(payload['freight_transport']['observed']['arrivals_observed'], 1)
        self.assertEqual(json_bytes(self.run), before)
        # A not-yet-departed trip is censored, never silently counted as entered.
        observed = self.run['results']['7']['freight_transport_events']
        observed.update(departures_observed=3,waiting_for_insertion=1,
                        scheduled_not_departed_at_cut=1,missing_departures=1)
        self.run['results']['7']['day_observation']['groups'][0].update(
            waiting_for_incorporation=1,scheduled_not_departed=1)
        self.assertEqual(self.payload()['freight_transport']['observed']['vehicles_observed'], 2)

    def test_fixed_day_corruption_missing_duplicate_foreign_ids_and_balances_rejected(self):
        self.fixed_day_freight()
        original = deepcopy(self.run)
        cases = [
            ('too_many_entries', lambda c,o,d: o.update(vehicles_observed=5)),
            ('too_many_arrivals', lambda c,o,d: o.update(arrivals_observed=3)),
            ('negative', lambda c,o,d: o.update(waiting_for_insertion=-1)),
            ('bool_count', lambda c,o,d: o.update(active_in_traffic_at_cut=True)),
            ('missing_count', lambda c,o,d: o.pop('arrivals_observed')),
            ('missing_config_count', lambda c,o,d: c.pop('vehicles_configured')),
            ('missing_enabled', lambda c,o,d: c.pop('enabled')),
            ('false_enabled', lambda c,o,d: c.update(enabled=False)),
            ('duplicate_configured_id', lambda c,o,d: c['fleet_vehicle_ids'].__setitem__(1,'f1')),
            ('duplicate_observed_id', lambda c,o,d: o['fleet_vehicle_ids'].__setitem__(1,'f1')),
            ('foreign_observed_id', lambda c,o,d: o['fleet_vehicle_ids'].__setitem__(1,'other')),
            ('missing_day_policy', lambda c,o,d: d.pop('policy')),
            ('missing_observed_policy', lambda c,o,d: o.pop('day_observation_policy')),
            ('missing_day_groups', lambda c,o,d: d.pop('groups')),
            ('null_day_groups', lambda c,o,d: d.update(groups=None)),
            ('duplicate_day_group', lambda c,o,d: d['groups'].append(deepcopy(d['groups'][0]))),
            ('bad_day_balance', lambda c,o,d: d['groups'][0].update(waiting_for_incorporation=1)),
            ('missing_base_counter', lambda c,o,d: d['groups'][0].pop('incorporations')),
            ('foreign_entry_id', lambda c,o,d: o['observed_traffic_entries'].update(other=10)),
            ('corrupt_entry_time', lambda c,o,d: o['observed_traffic_entries'].update(f2='20')),
            ('exit_before_entry', lambda c,o,d: o['observed_traffic_exits'].update(f1=1)),
            ('duplicate_census_id', lambda c,o,d: o['completion_records'][1].update(vehicle_id='f1')),
            ('missing_census_time', lambda c,o,d: o['completion_records'][2].pop('entry_seconds')),
            ('fabricated_arrival', lambda c,o,d: o['completion_records'][1].update(arrival_seconds=50)),
            ('arrival_before_exit', lambda c,o,d: (o['terminal_events']['f1'].update(time=29),
                o['completion_records'][0].update(arrival_seconds=29))),
            ('missing_terminal', lambda c,o,d: o.pop('terminal_events')),
            ('early_abort', lambda c,o,d: o['terminal_events']['f2'].update(time=80000)),
            ('wrong_census_status', lambda c,o,d: o['completion_records'][1].update(trip_outcome='completed')),
            ('bad_censor_balance', lambda c,o,d: o.update(censored_at_horizon=2)),
        ]
        for name, mutate in cases:
            self.run = deepcopy(original)
            result = self.run['results']['7']
            mutate(self.run['freight_transport'], result['freight_transport_events'], result['day_observation'])
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.payload()
        self.run = deepcopy(original)
        self.run.pop('freight_transport')
        with self.assertRaises(ValueError): self.payload()
        self.run = deepcopy(original)
        observed = self.run['results']['7']['freight_transport_events']
        observed['observed_traffic_entries']['f1'] = 1
        observed['completion_records'][0]['entry_seconds'] = True
        with self.assertRaises(ValueError): self.payload()

    def test_historical_full_service_still_requires_all_freight(self):
        self.run['freight_transport'] = dict(enabled=True, vehicles_configured=10, departures_scheduled=10)
        observed = self.run['results']['7']['freight_transport_events'] = dict(
            vehicles_observed=10, departures_observed=10)
        self.assertEqual(self.payload()['freight_transport']['observed']['vehicles_observed'],10)
        for key in ('vehicles_observed','departures_observed'):
            observed[key] = 9
            with self.assertRaisesRegex(ValueError, 'histórico'): self.payload()
            observed[key] = 10
        observed['arrivals_observed'] = 11
        with self.assertRaisesRegex(ValueError, 'históricas'): self.payload()
        self.run['freight_transport'] = dict(enabled=False, vehicles_configured=False)
        self.run['results']['7'].pop('freight_transport_events')
        with self.assertRaises(ValueError): self.payload()
    def request(self, handler, query):
        request = object.__new__(handler)
        request.path = '/api/hud?' + urlencode(query, doseq=True)
        request.wfile, request.headers = io.BytesIO(), {}
        statuses, headers = [], {}
        request.send_response, request.send_header = statuses.append, headers.__setitem__
        request.end_headers = lambda: None
        request.log_error = lambda *args: None
        request.do_GET()
        self.assertEqual(headers['Cache-Control'], 'no-store')
        return statuses[0], json.loads(request.wfile.getvalue())


if __name__ == '__main__':
    unittest.main()
