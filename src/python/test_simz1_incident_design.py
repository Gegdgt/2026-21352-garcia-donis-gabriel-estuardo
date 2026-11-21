"""Pure synthetic fixtures: no MATSim, historical replay, browser or server.

The frequency check tests hash sampling, not an empirical accident rate.
Registry coordinates/hashes and all vehicle identities are explicitly invented
test data, accepted only by the prototype's fixture-only contract.
"""
import copy
from decimal import Decimal
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import unittest

from simz1_incident_design import (
    DAY_US, HASH_FIELDS, IncidentDesignConfig, canonical, draw, evaluate,
    opportunity_key, validate_registry,
)


FIXTURE = (Path(__file__).resolve().parents[1] / 'scenarios' / 'zona1' /
           'versions' / 'incident-design-2026-10-22' / 'fixture.json')


class IncidentDesignTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.registry = self.request['registry']
        self.rows = self.request['observations']

    def run_design(self, rows=None, *, registry=None, config=None, **experiment):
        arguments = dict(replication_key='pure-fixture-test', iteration=0,
                         start_us=0, end_us=2 * DAY_US, complete_until_us=2 * DAY_US)
        arguments.update(experiment)
        return evaluate(config or IncidentDesignConfig(enabled=True, incident_seed=20261022,
                                                       probability_per_opportunity=1),
                        self.registry if registry is None else registry,
                        self.rows if rows is None else rows, **arguments)

    def at(self, index=0, *, time=100, visit=0, suffix=''):
        row = copy.deepcopy(self.rows[index])
        row['time_us'] = time
        for participant in row['participants']:
            participant['entered_queue_us'] = max(0, time - 1)
            participant['visit_index'] = visit
            participant['vehicle_id'] += suffix
            participant['trip_id'] += suffix
        return row

    def independent_places(self, count, *, time=100):
        """Small analytic crossing clones, with disjoint fixture identities."""
        registry = copy.deepcopy(self.registry)
        rows = []
        for index in range(count):
            suffix = f'-independent-{index:03d}'
            row = self.at(time=time, suffix=suffix)
            old_zone = registry['zones'][row['zone_id']]
            zone = copy.deepcopy(old_zone)
            row['zone_id'] += suffix
            row['node_id'] += suffix
            zone['node_id'] = row['node_id']
            zone['place_id'] += suffix
            zone['movement_ids'] = []
            for participant in row['participants']:
                old_id = participant['movement_id']
                ident = old_id + suffix
                movement = copy.deepcopy(registry['movements'][old_id])
                movement['node_id'] = row['node_id']
                for field in ('in_link', 'out_link', 'lane_id', 'receiving_lane_id'):
                    movement[field] += suffix
                participant.update(movement_id=ident, link_id=movement['in_link'], lane_id=movement['lane_id'])
                registry['movements'][ident] = movement
                zone['movement_ids'].append(ident)
            registry['zones'][row['zone_id']] = zone
            rows.append(row)
        return registry, rows

    def assert_rejected(self, row, reason=None):
        result = self.run_design([row])
        self.assertEqual(result['counts']['trials'], 0)
        self.assertEqual(result['incidents'], [])
        self.assertEqual(len(result['rejected']), 1)
        if reason is not None:
            self.assertEqual(result['rejected'][0]['reason'], reason)
        # Rejections must remain exportable, including nonfinite/structural input.
        canonical(result)
        return result

    def test_fixture_default_probability_and_three_synthetic_encounters(self):
        self.assertEqual(self.request['config']['probability_per_opportunity'], .00001)
        self.assertEqual(self.request['config']['incident_seed'], 20261022)
        self.assertIs(self.request['config']['enabled'], True)
        result = evaluate(IncidentDesignConfig(**self.request['config']), self.registry,
                          self.rows, **self.request['experiment'])
        self.assertEqual(result['counts']['unique_eligible'], 3)
        self.assertEqual(result['counts']['rejected'], 0)
        self.assertEqual({p['family'] for r in self.rows for p in r['participants']},
                         {'car', 'motorcycle', 'bus'})
        self.assertEqual({o['risk_type'] for o in result['opportunities']},
                         {'crossing_demand', 'merge_demand'})
        self.assertTrue(all(p['vehicle_id'].startswith('fixture-')
                            for row in self.rows for p in row['participants']))
        self.assertFalse(result['manifest']['collision_detection_available'])
        self.assertEqual(result['physics_effect'], 'none')
        self.assertEqual(result['manifest']['scope'], 'fixture_only')

    def test_disabled_does_not_consume_input_load_registry_or_change_global_prng(self):
        class Unreadable:
            def __iter__(self):
                raise AssertionError('disabled detector consumed observations')
        before = random.getstate()
        result = evaluate(IncidentDesignConfig(), object(), Unreadable())
        self.assertEqual(random.getstate(), before)
        self.assertEqual(result['counts']['trials'], 0)
        self.assertEqual(result['counts']['observations_received'], 0)

    def test_configuration_bounds_boolean_nan_and_independent_zero_seed(self):
        for kwargs in (
            dict(enabled=1), dict(enabled=True), dict(incident_seed=True),
            dict(incident_seed=1.0), dict(incident_seed=2**63), dict(incident_seed=-(2**63)-1),
            dict(probability_per_opportunity=True), dict(probability_per_opportunity='0.1'),
            dict(probability_per_opportunity=float('nan')), dict(probability_per_opportunity=float('inf')),
            dict(probability_per_opportunity=-.1), dict(probability_per_opportunity=1.0001),
            dict(probability_per_opportunity=10**1000),
            dict(daily_cap=True), dict(daily_cap=-1), dict(daily_cap=6), dict(daily_cap=1.0),
            dict(active_duration_us=True), dict(active_duration_us=0), dict(active_duration_us=-1),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                IncidentDesignConfig(**kwargs)
        for seed in (0, -(2**63), 2**63-1):
            config = IncidentDesignConfig(enabled=True, incident_seed=seed)
            self.assertEqual(config.manifest()['incident_seed'], str(seed))
        self.assertFalse(IncidentDesignConfig().enabled)

    def test_probability_zero_one_and_threshold_exact(self):
        for probability in (0, 1):
            with self.subTest(probability=probability):
                result = self.run_design(config=IncidentDesignConfig(
                    enabled=True, incident_seed=0, probability_per_opportunity=probability))
                self.assertEqual(result['counts']['trials'], 3)
                self.assertEqual(result['counts']['draw_successes'], 3 * probability)
                self.assertEqual(result['counts']['incidents'], 3 * probability)
                self.assertTrue(all(o['threshold_decimal'] == str(probability * 2**64)
                                    for o in result['opportunities']))
        result = self.run_design(config=IncidentDesignConfig(
            enabled=True, incident_seed=0, probability_per_opportunity=.00001))
        self.assertTrue(all(o['threshold_decimal'] == str(int(Decimal('.00001') * 2**64))
                            for o in result['opportunities']))

    def test_repeat_seed_reordered_input_and_unrelated_rows_do_not_change_draw(self):
        before = random.getstate()
        first = self.run_design()
        self.assertEqual(first, self.run_design(list(reversed(self.rows))))
        self.assertEqual(random.getstate(), before)
        different = self.run_design(config=IncidentDesignConfig(
            enabled=True, incident_seed=20261023, probability_per_opportunity=1))
        self.assertNotEqual([r['draw_hex'] for r in first['opportunities']],
                            [r['draw_hex'] for r in different['opportunities']])
        single = self.run_design([self.rows[0]])
        self.assertEqual(single['opportunities'][0]['draw_hex'], first['opportunities'][0]['draw_hex'])

    def test_probability_changes_preserve_draws_and_nested_pre_exclusion_selection(self):
        registry, rows = self.independent_places(32)
        selected = []
        draws = []
        for probability in (0, .25, .75, 1):
            result = self.run_design(rows, registry=registry, config=IncidentDesignConfig(
                enabled=True, incident_seed=0, probability_per_opportunity=probability, daily_cap=0))
            selected.append({o['opportunity_id'] for o in result['opportunities'] if o['selected_before_exclusions']})
            draws.append([o['draw_hex'] for o in result['opportunities']])
        self.assertTrue(all(a <= b for a, b in zip(selected, selected[1:])))
        self.assertTrue(all(value == draws[0] for value in draws))

    def test_hash_frequency_smoke_does_not_impose_real_accident_rate_or_minimum(self):
        threshold = 2**62  # p=.25; independent synthetic keys, not simulated traffic.
        count = sum(draw(20261022, 'hash-smoke', 0, 'a'*64, f'fixture-{index}') < threshold
                    for index in range(20000))
        self.assertGreater(count, 4600)
        self.assertLess(count, 5400)  # A broad deterministic implementation smoke bound.
        self.assertEqual(self.run_design(config=IncidentDesignConfig(
            enabled=True, incident_seed=0, probability_per_opportunity=0))['incidents'], [])

    def test_fixed_hash_vector_for_cross_language_port(self):
        # Literal protocol bytes: independent of the module's canonical helper.
        material = (
            b'["simz1-synthetic-incident-design-v1","incident-draw","0","golden-fixture",3,'
            b'"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            b'"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]'
        )
        digest = 'e709e337c6ead59f3f4c1e57d0b898a20d6356509b65efdf9a6c0d9cb28ded99'
        self.assertEqual(hashlib.sha256(material).hexdigest(), digest)
        self.assertEqual(f'{draw(0, "golden-fixture", 3, "a"*64, "b"*64):016x}', 'e709e337c6ead59f')

    def test_repeat_wait_reverse_pair_and_reentry_draw_once_per_visit_pair(self):
        first = self.at(time=100)
        repeated = copy.deepcopy(first)
        repeated['time_us'] = 101
        reversed_pair = copy.deepcopy(first)
        reversed_pair['participants'].reverse()
        reentry = self.at(time=200, visit=1)
        self.assertEqual(opportunity_key(first, self.registry), opportunity_key(reversed_pair, self.registry))
        self.assertNotEqual(opportunity_key(first, self.registry), opportunity_key(reentry, self.registry))
        result = self.run_design([reentry, repeated, first, reversed_pair], config=IncidentDesignConfig(
            enabled=True, incident_seed=0, probability_per_opportunity=1, active_duration_us=1))
        self.assertEqual(result['counts']['trials'], 2)
        self.assertEqual(result['counts']['duplicate_observations'], 2)
        self.assertEqual([o['time_us'] for o in result['opportunities']], [100, 200])

    def test_multiple_zones_at_same_place_do_not_reroll_encounter(self):
        registry = copy.deepcopy(self.registry)
        registry['zones']['fixture-alias-zone'] = copy.deepcopy(registry['zones']['fixture-cross-zone'])
        alias = self.at(time=101)
        alias['zone_id'] = 'fixture-alias-zone'
        result = self.run_design([alias, self.at(time=100)], registry=registry)
        self.assertEqual(result['counts']['trials'], 1)
        self.assertEqual(result['counts']['duplicate_observations'], 1)

    def test_four_producer_shards_have_identical_complete_batch_ledger(self):
        registry, rows = self.independent_places(8)
        rows.extend([copy.deepcopy(rows[0]), copy.deepcopy(rows[3])])
        shards = [rows[index::4] for index in range(4)]
        expected = canonical(self.run_design(rows, registry=registry))
        for permutation in itertools.permutations(range(4)):
            delivered = [row for index in permutation for row in reversed(shards[index])]
            self.assertEqual(canonical(self.run_design(delivered, registry=registry)), expected)

    def test_daily_cap_zero_through_five_resets_by_simulated_day(self):
        registry, first_day = self.independent_places(6)
        next_day = copy.deepcopy(first_day)
        for row in next_day:
            row['time_us'] += DAY_US
            for p in row['participants']:
                p['visit_index'] += 1
                p['entered_queue_us'] += DAY_US
        for cap in range(6):
            with self.subTest(cap=cap):
                result = self.run_design(next_day + first_day, registry=registry, config=IncidentDesignConfig(
                    enabled=True, incident_seed=0, probability_per_opportunity=1,
                    daily_cap=cap, active_duration_us=1))
                self.assertEqual(result['counts']['draw_successes'], 12)
                self.assertEqual(len(result['incidents']), 2 * cap)
                self.assertEqual(result['counts']['daily_cap_suppressed'], 12 - 2 * cap)
                self.assertEqual(result['counts']['incidents_by_day'], {'0': cap, '1': cap} if cap else {})

    def test_active_interval_expiry_exact_and_no_reroll_after_suppression(self):
        first = self.at(time=100)
        blocked = self.at(time=109, visit=1, suffix='-next')
        retry = copy.deepcopy(blocked)
        retry['time_us'] = 110
        at_end = self.at(time=110, visit=2, suffix='-third')
        result = self.run_design([first, blocked, retry, at_end], config=IncidentDesignConfig(
            enabled=True, incident_seed=0, probability_per_opportunity=1, active_duration_us=10))
        self.assertEqual([r['time_us'] for r in result['incidents']], [100, 110])
        self.assertEqual(result['counts']['active_suppressed'], 1)
        self.assertEqual(result['counts']['duplicate_observations'], 1)

    def test_active_vehicle_at_other_place_and_place_with_other_vehicles(self):
        first = self.at(time=100)
        same_vehicle = self.at(index=1, time=101)
        same_vehicle['participants'][0]['vehicle_id'] = first['participants'][0]['vehicle_id']
        same_place = self.at(time=102, suffix='-other')
        result = self.run_design([same_place, same_vehicle, first])
        self.assertEqual(len(result['incidents']), 1)
        self.assertEqual(result['counts']['active_suppressed'], 2)
        self.assertEqual(result['counts']['draw_successes'], 3)

    def test_active_reservation_survives_midnight_and_expires_at_exact_boundary(self):
        rows = [self.at(time=DAY_US-5), self.at(time=DAY_US+1, visit=1, suffix='-other'),
                self.at(time=DAY_US+5, visit=2, suffix='-later')]
        result = self.run_design(rows, config=IncidentDesignConfig(
            enabled=True, incident_seed=0, probability_per_opportunity=1, active_duration_us=10))
        self.assertEqual([i['time_us'] for i in result['incidents']], [DAY_US-5, DAY_US+5])
        self.assertEqual(result['counts']['incidents_by_day'], {'0': 1, '1': 1})
        self.assertEqual(result['counts']['active_suppressed'], 1)

    def test_horizon_marks_scheduled_annotation_censored_without_fake_recovery_event(self):
        result = self.run_design([self.at(time=100)], end_us=105, complete_until_us=105,
            config=IncidentDesignConfig(enabled=True, incident_seed=0, probability_per_opportunity=1,
                                        active_duration_us=10))
        self.assertEqual(result['incidents'][0]['scheduled_annotation_end_us'], 110)
        self.assertEqual(result['incidents'][0]['annotation_status_at_horizon'], 'censored')
        self.assertEqual(len(result['incidents']), 1)
        self.assertFalse(result['incidents'][0]['collision_detected'])
        self.assertFalse(result['incidents'][0]['observed_violation'])
        self.assertEqual(result['incidents'][0]['physics_effect'], 'none')

    def test_completed_watermark_and_half_open_horizon(self):
        for watermark in (None, True, -1, 100, 201):
            with self.subTest(watermark=watermark), self.assertRaises(ValueError):
                self.run_design([], end_us=200, complete_until_us=watermark)
        rows = [self.at(time=99), self.at(time=100, visit=1), self.at(time=200, visit=2),
                self.at(time=201, visit=3)]
        result = self.run_design(rows, start_us=100, end_us=200, complete_until_us=200)
        self.assertEqual(result['counts']['trials'], 1)
        self.assertEqual(result['opportunities'][0]['time_us'], 100)
        self.assertEqual(result['counts']['rejection_reasons'], {'invalid_or_unclosed_chronology': 3})
        self.assert_rejected(dict(self.at(), step_complete=False), 'paired_native_evidence_missing')

    def test_input_and_registry_are_unchanged(self):
        before = copy.deepcopy((self.registry, self.rows))
        self.run_design()
        self.assertEqual((self.registry, self.rows), before)

    def test_experiment_identity_and_horizon_are_typed_and_valid(self):
        for arguments in (dict(replication_key=''), dict(iteration=True), dict(iteration=-1),
                          dict(start_us=True), dict(start_us=-1), dict(end_us=0),
                          dict(end_us=True), dict(start_us=100, end_us=100)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.run_design([], **arguments)

    def test_person_identity_is_optional_preserved_and_never_invented(self):
        for person in (None, 'fixture-person-A'):
            row = self.at()
            row['participants'][0]['person_id'] = person
            result = self.run_design([row])
            participants = result['opportunities'][0]['participants']
            actual = next(p for p in participants if p['vehicle_id'] == row['participants'][0]['vehicle_id'])
            self.assertEqual(actual['person_id'], person)
            other = next(p for p in participants if p['vehicle_id'] != actual['vehicle_id'])
            self.assertNotIn('person_id', other)
        for person in ('', [], False):
            row = self.at()
            row['participants'][0]['person_id'] = person
            self.assert_rejected(row, 'person_identity_invalid')

    def test_unknown_route_family_or_dimensions_never_defaults_to_car_bus_or_motorcycle(self):
        for family in ('car', 'bus', 'motorcycle'):
            for field, value, reason in (
                ('route_known', False, 'route_or_vehicle_family_unknown'),
                ('family', None, 'route_or_vehicle_family_unknown'),
                ('family', 'unknown', 'route_or_vehicle_family_unknown'),
                ('dimensions', None, 'configured_dimensions_missing_no_car_fallback'),
                ('dimensions', {}, 'configured_dimensions_missing_no_car_fallback'),
            ):
                with self.subTest(family=family, field=field, value=value):
                    row = self.at()
                    row['participants'][0]['family'] = family
                    row['participants'][0][field] = value
                    self.assert_rejected(row, reason)
        for field, value in (('length_m', 0), ('width_m', -1), ('length_m', True),
                             ('length_m', float('nan')), ('width_m', float('inf')),
                             ('nature', 'inferred'), ('source', ''), ('artifact_sha256', 'a'*64)):
            with self.subTest(field=field, value=value):
                row = self.at()
                row['participants'][0]['dimensions'][field] = value
                reason = ('non_json_or_nonfinite_input' if isinstance(value, float) and not math.isfinite(value)
                          else 'configured_dimensions_missing_no_car_fallback')
                self.assert_rejected(row, reason)
        row = self.at()
        row['participants'][0]['dimensions']['length_m'] = 10**1000
        self.assert_rejected(row)

    def test_lane_link_hash_and_family_permissions_are_required(self):
        for field in HASH_FIELDS:
            with self.subTest(hash=field):
                row = self.at()
                row['artifact_sha256'][field] = '0'*64
                self.assert_rejected(row, 'artifact_identity_mismatch')
        for field, value in (('lane_id', 'fixture-other-lane'), ('link_id', 'fixture-other-link')):
            row = self.at()
            row['participants'][0][field] = value
            self.assert_rejected(row, 'lane_link_or_family_permission_mismatch')
        registry = copy.deepcopy(self.registry)
        registry['movements']['fixture-cross-a']['families'] = ['bus']
        result = self.run_design([self.at()], registry=registry)
        self.assertEqual(result['rejected'][0]['reason'], 'lane_link_or_family_permission_mismatch')

    def test_forbidden_unresolved_ambiguous_or_wrong_grade_registry_fails_closed(self):
        changes = (
            ('movements', 'fixture-cross-a', 'turn_verified', False),
            ('movements', 'fixture-cross-a', 'level', '1'),
            ('movements', 'fixture-cross-a', 'families', ['unknown']),
            ('movements', 'fixture-cross-a', 'chord_xy', [[-10, 11], [10, 11]]),
            ('movements', 'fixture-cross-a', 'chord_xy', [[-10**1000, 0], [10, 0]]),
            ('zones', 'fixture-cross-zone', 'review_status', 'conflicting_or_ambiguous'),
            ('zones', 'fixture-cross-zone', 'restrictions_resolved', False),
            ('zones', 'fixture-cross-zone', 'proof', 'conservative_priority_boolean'),
            ('zones', 'fixture-merge-zone', 'proof', 'shared_out_link_only'),
            ('movements', 'fixture-merge-a', 'receiving_lane_id', 'fixture-parallel-other-lane'),
        )
        for section, ident, field, value in changes:
            with self.subTest(section=section, ident=ident, field=field):
                registry = copy.deepcopy(self.registry)
                registry[section][ident][field] = value
                with self.assertRaises(ValueError):
                    self.run_design(registry=registry)

    def test_production_and_renderer_input_are_refused(self):
        for key, value in (('scope', 'production'), ('geometry_source', 'webgl')):
            registry = copy.deepcopy(self.registry)
            registry[key] = value
            with self.assertRaises(ValueError):
                self.run_design(registry=registry)
        for key in ('visual_body', 'webglOverlap', 'hitbox', 'screen_position', 'pixel_width'):
            with self.subTest(key=key):
                row = self.at()
                row['participants'][0][key] = {'a': 1}
                self.assert_rejected(row, 'visual_evidence_forbidden')
        self.assert_rejected(dict(self.at(), source='historical_decision_event'), 'paired_native_evidence_missing')

    def test_equal_but_unknown_levels_do_not_prove_same_grade(self):
        for level in ('unknown', 'not_recorded', 'nan', 'inf', ''):
            registry = copy.deepcopy(self.registry)
            for movement in registry['movements'].values():
                movement['level'] = level
            with self.subTest(level=level), self.assertRaises(ValueError):
                self.run_design(registry=registry)

    def test_requires_admission_receipt_and_conflicting_demand_not_storage_or_two_admissions(self):
        for field, value, reason in (
            ('receiver_accepted', False, 'admission_receipt_missing'),
            ('reason', 'unknown', 'admission_receipt_missing'),
        ):
            row = self.at()
            row['participants'][0][field] = value
            self.assert_rejected(row, reason)
        row = self.at()
        row['participants'][1]['reason'] = 'receiver_full'
        self.assert_rejected(row, 'wait_without_traffic_conflict')
        row = self.at()
        row['participants'][1].update(decision='ADMITTED', reason='native_admitted', receiver_accepted=True)
        self.assert_rejected(row, 'requires_one_admitted_and_one_conflicting_demand')

    def test_force_and_abort_are_separate_and_never_generate_incidents(self):
        force = self.at()
        force['participants'][0].update(decision='FORCE', reason='storage_force', receiver_accepted=False)
        abort = self.at(index=1)
        abort['participants'][0].update(decision='ABORT', reason='stuck_abort')
        result = self.run_design([force, abort])
        self.assertEqual(result['counts']['trials'], 0)
        self.assertEqual(result['incidents'], [])
        self.assertEqual(result['forced_transitions'], [force])
        self.assertEqual(result['counts']['rejection_reasons'],
                         {'aborted_transition_excluded': 1, 'forced_transition_excluded': 1})

    def test_contradictory_force_and_admission_for_same_encounter_cannot_launder_a_draw(self):
        valid = self.at()
        force = copy.deepcopy(valid)
        force['participants'][0].update(decision='FORCE', reason='storage_force', receiver_accepted=False)
        for rows in ([valid, force], [force, valid]):
            with self.subTest(order=[row['participants'][0]['decision'] for row in rows]):
                result = self.run_design(rows)
                self.assertEqual(result['counts']['trials'], 0)
                self.assertEqual(result['incidents'], [])
                self.assertEqual(result['forced_transitions'], [force])
                self.assertIn('contradictory_native_evidence', result['counts']['rejection_reasons'])

    def test_later_copy_cannot_launder_contradiction_but_a_new_visit_can_draw(self):
        valid = self.at(time=100)
        force = copy.deepcopy(valid)
        force['participants'][0].update(decision='FORCE', reason='storage_force', receiver_accepted=False)
        later_copy = copy.deepcopy(valid)
        later_copy['time_us'] = 101
        new_visit = self.at(time=200, visit=1)
        for rows in ([valid, force, later_copy], [later_copy, force, valid]):
            with self.subTest(order=[row['time_us'] for row in rows]):
                blocked = self.run_design(rows)
                self.assertEqual(blocked['counts']['trials'], 0)
                self.assertEqual(blocked['incidents'], [])
                self.assertEqual(blocked['forced_transitions'], [force])
                self.assertEqual(blocked['counts']['rejection_reasons']['contradictory_native_evidence'], 2)
                fresh = self.run_design([new_visit, *rows])
                self.assertEqual(fresh['counts']['trials'], 1)
                self.assertEqual([o['time_us'] for o in fresh['opportunities']], [200])
                self.assertEqual([i['time_us'] for i in fresh['incidents']], [200])
                self.assertEqual(fresh['forced_transitions'], [force])

    def test_malformed_structures_reject_without_type_or_key_errors(self):
        cases = [None, [], 0]
        for field, value in (('zone_id', []), ('node_id', {}), ('participants', None),
                             ('participants', [None, {}]), ('time_us', True),
                             ('time_us', float('nan')), ('artifact_sha256', [])):
            row = self.at()
            row[field] = value
            cases.append(row)
        for field, value in (('movement_id', []), ('vehicle_id', []), ('family', []),
                             ('decision', None), ('visit_index', True), ('entered_queue_us', 101)):
            row = self.at()
            row['participants'][0][field] = value
            cases.append(row)
        row = self.at()
        del row['participants'][0]['decision']
        cases.append(row)
        for index, row in enumerate(cases):
            with self.subTest(index=index):
                self.assert_rejected(row)
        for registry in (None, [], {'schema': 'simz1-conflict-registry-design-v1', 'scope': 'fixture_only'},
                         dict(self.registry, movements=[]), dict(self.registry, zones=[]),
                         dict(self.registry, artifact_sha256=[])):
            with self.subTest(registry=registry), self.assertRaises(ValueError):
                validate_registry(registry)


if __name__ == '__main__':
    unittest.main()
