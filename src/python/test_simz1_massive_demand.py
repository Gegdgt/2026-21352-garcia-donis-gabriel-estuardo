"""Demand authorization/identity checks; at most ten generated persons per run, no QSim or subprocesses."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch
import xml.etree.ElementTree as ET

import ejecutar_simz1 as launcher
import generate_montecarlo_z1 as generator
import simz1_population as population
from simz1_run import MANIFEST, load_manifest, sha256


SOURCE_CONFIG = generator.SCENARIO / 'config-simz1.xml'


class MassiveDemandTests(unittest.TestCase):
    def test_default_is_ten_and_massive_default_is_an_explicit_inclusive_range(self):
        self.assertEqual((population.SAFE_DEFAULT_AGENTS, population.DEFAULT_MIN, population.DEFAULT_MAX),
                         (10, 150000, 250000))
        self.assertEqual(population.population_spec(),
                         dict(mode='montecarlo', kind='fixed', minimum=10, maximum=10))
        self.assertEqual(population.population_spec(massive=True),
                         dict(mode='montecarlo', kind='range', minimum=150000, maximum=250000))
        small = population.population_spec(min_agents=2, max_agents=5)
        self.assertEqual(small, dict(mode='montecarlo', kind='range', minimum=2, maximum=5))
        self.assertEqual(population.population_spec(agents=1)['minimum'], 1)

    def test_threshold_and_mode_authorization_do_not_allocate_people(self):
        self.assertEqual(population.MASSIVE_THRESHOLD, 150000)
        self.assertEqual(population.population_spec(agents=149999)['maximum'], 149999)
        self.assertEqual(population.population_spec(min_agents=1, max_agents=149999)['maximum'], 149999)
        for options in (dict(agents=150000), dict(agents=200000), dict(min_agents=1, max_agents=150000)):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, '--massive'):
                population.population_spec(**options)
            authorized = population.population_spec(**options, massive=True)
            self.assertGreaterEqual(authorized['maximum'], 150000)
        # The new default is 250k; the previous explicit range remains reproducible.
        self.assertEqual(population.population_spec(min_agents=150000, max_agents=200000, massive=True)['maximum'], 200000)
        for mode in ('debug', 'historical'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'montecarlo'):
                population.population_spec(mode=mode, massive=True)
        for value in (1, 'true', None):
            with self.subTest(massive=value), self.assertRaises(ValueError):
                population.population_spec(massive=value)

    def test_draw_uses_inclusive_endpoints_once_and_fixed_count_skips_rng(self):
        spec = population.population_spec(massive=True)
        for endpoint in (150000, 250000):
            rng = Mock()
            rng.randint.return_value = endpoint
            self.assertEqual(population.draw_population(spec, rng), endpoint)
            rng.randint.assert_called_once_with(150000, 250000)
        rng = Mock()
        self.assertEqual(population.draw_population(population.population_spec(), rng), 10)
        rng.randint.assert_not_called()

    def test_invalid_sizes_and_incomplete_or_conflicting_ranges_are_rejected_purely(self):
        cases = [dict(min_agents=3, max_agents=2), dict(min_agents=1), dict(max_agents=2),
                 dict(agents=1, min_agents=1, max_agents=2),
                 dict(agents=1, min_agents=1), dict(agents=1, max_agents=2)]
        for invalid in (0, -1, 1.5, True, '1'):
            cases.extend((dict(agents=invalid), dict(min_agents=invalid, max_agents=3),
                          dict(min_agents=1, max_agents=invalid)))
        # Pure validation precedes any population/configuration I/O, even when massive is authorized.
        for options in cases:
            for massive in (False, True):
                with self.subTest(options=options, massive=massive), self.assertRaises(ValueError):
                    population.population_spec(**options, massive=massive)

    def test_seed_repetition_is_reproducible_and_count_does_not_identify_a_run(self):
        spec = population.population_spec(massive=True)
        first, second = random.Random(20261004), random.Random(20261004)
        self.assertEqual(population.draw_population(spec, first), population.draw_population(spec, second))
        self.assertEqual(first.getstate(), second.getstate())
        # Different seeds can have the same N; this does not justify rerolling either seed.
        one_count = population.population_spec(min_agents=10, max_agents=10)
        distinct = [random.Random(seed) for seed in (17, 18)]
        self.assertEqual([population.draw_population(one_count, rng) for rng in distinct], [10, 10])
        self.assertNotEqual(distinct[0].getstate(), distinct[1].getstate())

    def test_automatic_seed_uses_53_bits_once_and_explicit_integer_is_unchanged(self):
        draws = [2**52 + 17, 2**53 - 1]
        with patch.object(population.secrets, 'randbits', side_effect=draws) as entropy:
            for expected in draws:
                self.assertEqual(population.resolve_demand_seed(), (expected, {'source': 'secrets.randbits(53)'}))
            self.assertEqual(entropy.call_args_list, [call(53), call(53)])
        with patch.object(population.secrets, 'randbits') as entropy:
            for seed in (0, -17, 2**52 + 17):
                self.assertEqual(population.resolve_demand_seed(seed), (seed, {'source': 'explicit'}))
            entropy.assert_not_called()
        for invalid in (True, False, 1.5, '17'):
            with self.subTest(seed=invalid), self.assertRaisesRegex(ValueError, 'semilla'):
                population.resolve_demand_seed(invalid)

    def test_unauthorized_size_and_boolean_seed_fail_before_config_or_directory_creation(self):
        for options in (dict(agents=150000), dict(min_agents=149999, max_agents=150000), dict(agents=1, seed=True)):
            with self.subTest(options=options), patch.object(generator.ET, 'parse') as read_config, \
                    patch.object(generator, 'create_run_directory') as create, \
                    patch.object(generator, 'synthetic_people') as people:
                with self.assertRaises(ValueError):
                    generator.generar('unread-config.xml', None, corridor_policy='redistribute', **options)
                read_config.assert_not_called()
                create.assert_not_called()
                people.assert_not_called()

    def test_shared_parser_and_both_clis_forward_massive_and_unresolved_seed(self):
        parser = argparse.ArgumentParser()
        generator.add_generation_options(parser)
        defaults = generator.generation_options(parser.parse_args([]))
        self.assertIs(defaults['massive'], False)
        self.assertIsNone(defaults['agents'])
        for module, script in ((generator, 'generate_montecarlo_z1.py'), (launcher, 'ejecutar_simz1.py')):
            for seed, seed_flags in ((None, []), (2**52 + 17, ['--seed', str(2**52 + 17)])):
                for size_flags, massive in ((['--agents', '10'], False), (['--massive'], True),
                                           (['--massive', '--min-agents', '150000', '--max-agents', '200000'], True)):
                    argv = [script, '--corridor-policy', 'redistribute', *size_flags, *seed_flags]
                    with self.subTest(script=script, seed=seed, flags=size_flags), \
                            patch.object(sys, 'argv', argv), \
                            patch.object(module, 'generar', return_value={'run_dir': 'mock generated run'}) as generate, \
                            patch.object(launcher, 'ejecutar') as execute, \
                            patch.object(population.secrets, 'randbits', side_effect=AssertionError('CLI must not draw seed')), \
                            contextlib.redirect_stdout(io.StringIO()):
                        module.main()
                    generate.assert_called_once()
                    positional, options = generate.call_args
                    self.assertIsNone(positional[1])
                    self.assertEqual(positional[2], seed)
                    self.assertIs(options['massive'], massive)
                    self.assertEqual((options['min_agents'], options['max_agents']),
                                     (150000, 200000) if '--min-agents' in size_flags else (None, None))
                    self.assertEqual(options['agents'], 10 if '--agents' in size_flags else None)
                    self.assertEqual(options['trips_per_person'], 1)
                    self.assertIsNone(options['temporal_profile'])
                    self.assertIsNone(options['drain_seconds'])
                    if module is launcher:
                        execute.assert_called_once_with(Path('mock generated run'), None, False, None)
                    else:
                        execute.assert_not_called()

    def test_ten_person_preparation_preserves_xml_hashes_and_reports_duplicate_without_reroll(self):
        # Reuse only the existing network/config inputs; generated XML has ten people per run.
        with tempfile.TemporaryDirectory(prefix='simz1 small demand ') as temporary:
            root = Path(temporary)
            seed = 2**52 + 17
            with patch.object(generator, 'SCENARIO', root/'empty scenario scopes'), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                first = generator.generar(SOURCE_CONFIG, root/'first', seed, agents=10,
                                          corridor_policy='redistribute')
                with patch.object(population.secrets, 'randbits', return_value=seed) as entropy:
                    second = generator.generar(SOURCE_CONFIG, root/'second', agents=10,
                                               corridor_policy='redistribute')
                entropy.assert_called_once_with(53)
            self.assertNotEqual(first['run_id'], second['run_id'])
            self.assertEqual(first['plans_sha256'], second['plans_sha256'])
            self.assertEqual(first['vehicles_sha256'], second['vehicles_sha256'])
            self.assertIn('sin cambiar semilla ni volver a sortear N', output.getvalue())
            for report, name, seed_source in ((first, 'first', 'explicit'), (second, 'second', 'secrets.randbits(53)')):
                directory = root/name
                manifest = load_manifest(directory)
                persisted = json.loads((directory/'montecarlo-report.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['demand_seed'], seed)
                self.assertEqual(report['demand_seed'], seed)
                self.assertEqual(report['seed_selection'], {'source': seed_source})
                self.assertIs(report['massive_authorized'], False)
                self.assertEqual(report['xml_verified_counts']['persons'], 10)
                self.assertEqual(report['xml_verified_counts']['trips'], 10)
                self.assertEqual(report['xml_verified_counts']['vehicles'], 10)
                self.assertEqual(len(ET.parse(directory/'plans.xml').findall('person')), 10)
                self.assertEqual(manifest['counts']['planned_persons'], 10)
                self.assertEqual(manifest['counts']['planned_trips'], 10)
                self.assertEqual(manifest['status'], 'prepared')
                self.assertEqual(manifest['validation']['status'], 'pending')
                self.assertEqual(manifest['iterations']['completed'], [])
                self.assertEqual(manifest['results'], {})
                self.assertFalse((directory/'output').exists())
                for field in ('seed_selection', 'massive_authorized', 'duplicate_population_check'):
                    self.assertEqual(persisted[field], report[field])
                    self.assertEqual(manifest['population_generation'][field], report[field])
                self.assertEqual(sha256(directory/'plans.xml'), report['plans_sha256'])
                self.assertEqual(sha256(directory/'inputs/vehicles.xml'), report['vehicles_sha256'])
            self.assertEqual(first['duplicate_population_check']['status'], 'none_found_in_scope')
            duplicate = second['duplicate_population_check']
            self.assertEqual(duplicate['status'], 'duplicates_found')
            self.assertEqual([match['run_id'] for match in duplicate['matches']], [first['run_id']])
            self.assertEqual(duplicate['matches'][0]['plans_sha256'], first['plans_sha256'])

    def test_failed_manifest_publication_keeps_diagnostics_without_publishing_prepared(self):
        with tempfile.TemporaryDirectory(prefix='simz1 failed publication ') as temporary:
            root = Path(temporary)
            directory = root/'failed run'
            with patch.object(generator, 'SCENARIO', root/'empty scenario scopes'), \
                    patch.object(generator, 'atomic_json', side_effect=OSError('publication failed')) as publish, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(OSError, 'publication failed'):
                    generator.generar(SOURCE_CONFIG, directory, 17, agents=1, corridor_policy='redistribute')
            publish.assert_called_once()
            self.assertFalse((directory/MANIFEST).exists())
            self.assertFalse((directory/'output').exists())
            for relative in ('plans.xml', 'config-simz1.xml', 'montecarlo-report.json', 'inputs/vehicles.xml'):
                self.assertTrue((directory/relative).is_file(), relative)


class DuplicatePopulationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='simz1 duplicate scope ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.scope = self.root/'scope'
        self.scope.mkdir()

    def run_fixture(self, directory, content=b'<population/>', recorded_hash=None):
        directory.mkdir(parents=True)
        plans = directory/'plans.xml'
        plans.write_bytes(content)
        manifest = dict(schema_version=1, folder=str(directory.resolve()), run_id=directory.name, demand_seed=17,
                        counts={'planned_persons': 10},
                        inputs={'plans': {'path': 'plans.xml', 'sha256': recorded_hash or sha256(plans)}})
        (directory/MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
        return manifest['inputs']['plans']['sha256']

    def test_matching_hash_requires_real_content_and_stays_in_declared_scope(self):
        target = self.scope/'current'
        fingerprint = self.run_fixture(target)
        self.run_fixture(self.scope/'matching')
        self.run_fixture(self.scope/'same count different plans', b'<population name="other"/>')
        self.run_fixture(self.root/'outside scope')
        self.run_fixture(self.scope/'nested'/'too deep')
        result = population.duplicate_population_check(target, [self.scope, self.scope], fingerprint)
        self.assertEqual(result['status'], 'duplicates_found')
        self.assertEqual(result['checked_manifests'], 2)
        self.assertEqual(result['search_roots'], [str(self.scope)])
        self.assertEqual(result['unverifiable_manifests'], [])
        self.assertEqual(result['matches'], [dict(run_id='matching', demand_seed=17,
                                                folder=str(self.scope/'matching'), plans_sha256=fingerprint)])

    def test_stale_hash_missing_plans_and_malformed_manifest_make_check_incomplete(self):
        fingerprint = self.run_fixture(self.scope/'valid match')
        self.run_fixture(self.scope/'stale hash', b'changed bytes', recorded_hash=fingerprint)
        missing = self.scope/'missing plans';missing.mkdir()
        (missing/MANIFEST).write_text(json.dumps(dict(schema_version=1, folder=str(missing), run_id='missing',
            inputs={'plans': {'path': 'absent.xml', 'sha256': fingerprint}})), encoding='utf-8')
        malformed = self.scope/'bad JSON';malformed.mkdir()
        (malformed/MANIFEST).write_text('{', encoding='utf-8')
        result = population.duplicate_population_check(self.scope/'future run', [self.scope], fingerprint)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual({Path(item['path']).parent.name for item in result['unverifiable_manifests']},
                         {'stale hash', 'missing plans', 'bad JSON'})
        self.assertTrue(all(item['reason'] for item in result['unverifiable_manifests']))

    def test_no_match_is_scoped_and_non_directory_root_is_incomplete(self):
        fingerprint = self.run_fixture(self.root/'elsewhere')
        self.run_fixture(self.scope/'different', b'<population name="different"/>')
        result = population.duplicate_population_check(self.scope/'future run',
                                                       [self.scope, self.root/'missing scope'], fingerprint)
        self.assertEqual(result['status'], 'none_found_in_scope')
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['unverifiable_manifests'], [])
        non_directory = self.root/'file';non_directory.write_text('not a directory', encoding='utf-8')
        result = population.duplicate_population_check(self.scope/'future run', [non_directory], fingerprint)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(len(result['unverifiable_manifests']), 1)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            population.duplicate_population_check(self.scope/'future run', [self.scope], 'bad-hash')

    def test_denied_directory_enumeration_reports_incomplete_instead_of_unique(self):
        with patch.object(Path, 'iterdir', side_effect=PermissionError('scope access denied')):
            result = population.duplicate_population_check(self.scope/'future run', [self.scope], 'a'*64)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['checked_manifests'], 0)
        self.assertEqual(len(result['unverifiable_manifests']), 1)
        self.assertEqual(result['unverifiable_manifests'][0]['path'], str(self.scope))
        self.assertIn('scope access denied', result['unverifiable_manifests'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
