"""Contracts for preparing future runs; no Java/Maven/QSim process is started."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('simz1_massive_contract', PROJECT / 'scripts/validation/simz1_massive_contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class MassiveContractTests(unittest.TestCase):
    def setUp(self):
        (PROJECT / 'target').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='simz1-massive-contract-test-', dir=PROJECT / 'target')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def build(self):
        return contract.build_files(self.folder / 'isolated', PROJECT / 'mvnw.cmd')

    def test_fresh_build_only_and_scenario_scope(self):
        receipt = self.build()
        self.assertFalse(receipt['simulation_executed'])
        self.assertFalse(Path(receipt['compile_classes']).exists())
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        root = ET.parse(receipt['pom']).getroot()
        build = root.find('m:build', ns)
        self.assertEqual(str(PROJECT / 'src/main/java').replace('\\', '/'), build.findtext('m:sourceDirectory', namespaces=ns))
        self.assertTrue(Path(build.findtext('m:directory', namespaces=ns)).is_relative_to(self.folder))
        patterns = build.findall("m:plugins/m:plugin[m:artifactId='maven-compiler-plugin']/m:configuration/m:includes/m:include", ns)
        self.assertEqual(['gt/edu/uvg/sim/zona1/**/*.java', 'org/matsim/core/mobsim/qsim/qnetsimengine/**/*.java'],
                         [element.text for element in patterns])
        compiler_args = build.findall("m:plugins/m:plugin[m:artifactId='maven-compiler-plugin']/m:configuration/m:compilerArgs/m:arg", ns)
        self.assertIn('-g:none', [element.text for element in compiler_args])
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            contract.build_files(self.folder / 'isolated', PROJECT / 'mvnw.cmd')

    def test_outside_build_destination_rejected(self):
        with self.assertRaisesRegex(ValueError, 'must be new below'):
            contract.build_files(PROJECT / 'scenarios/zona1/unapproved-build', PROJECT / 'mvnw.cmd')

    def test_derived_catalog_keeps_seven_definitions_and_six_active_profiles(self):
        before = contract.sha256(contract.SCENARIO / 'agent-types-road-v1.json')
        receipt = self.build()
        catalog = contract.load_catalog(receipt['catalog'])
        self.assertEqual(7, len(catalog['profiles']))
        self.assertEqual(0, catalog['allocation']['road_weights']['TransportePesado'])
        self.assertEqual(6, len(contract.active_types(catalog)))
        self.assertEqual(before, contract.sha256(contract.SCENARIO / 'agent-types-road-v1.json'))
        contract.validate_road_access(contract.SCENARIO / 'network.xml', catalog)

    def test_real_launcher_parser_accepts_small_and_massive_ranges(self):
        import ejecutar_simz1
        class ParsedWithoutGenerating(BaseException):
            pass
        for lower, upper in [(10, 10), (100, 100), (1000, 1000), (150000, 250000), (150000, 2500000)]:
            arguments = contract.launcher_arguments(contract.SCENARIO / 'config-simz1.xml', self.folder / 'catalog.json',
                                                     lower, upper, 20261022)
            with patch.object(sys, 'argv', ['ejecutar_simz1.py', *arguments]), \
                    patch.object(ejecutar_simz1, 'generar', side_effect=ParsedWithoutGenerating) as generate:
                with self.assertRaises(ParsedWithoutGenerating):
                    ejecutar_simz1.main()
                self.assertTrue(generate.call_args.kwargs['massive'])
                self.assertEqual(lower, generate.call_args.kwargs['min_agents'])
                self.assertEqual(upper, generate.call_args.kwargs['max_agents'])
                self.assertIsNone(generate.call_args.kwargs['temporal_profile'])
                self.assertFalse(generate.call_args.kwargs['incidents'])

    def test_invalid_range_seed_and_threads_rejected(self):
        for lower, upper, seed, threads in [(100, 10, 1, 4), (0, 10, 1, 4), (10, 10, -1, 4),
                                             (10, 10, 2147483648, 4), (10, 10, 1, 3)]:
            with self.assertRaises(ValueError):
                contract.launcher_arguments('config.xml', 'catalog.json', lower, upper, seed, threads)

    def test_batch_wrapper_path_injection_rejected(self):
        for unsafe in ('bad%PATH%', 'bad!PATH!', 'bad"quote', 'bad\nline'):
            with self.assertRaises(ValueError):
                contract._safe_cmd_path(self.folder / unsafe)

    def test_real_readonly_preflight_discloses_blockers_and_pins_inputs(self):
        build = self.build()
        receipt = contract.preflight(contract.SCENARIO / 'config-simz1.xml', build['catalog'], 150000, 250000, 20261022, 4)
        self.assertEqual('ready_for_disclosed_subset', receipt['status'])
        self.assertEqual('BLOCKED', receipt['full_requested_suite'])
        self.assertFalse(receipt['simulation_executed'])
        self.assertFalse(receipt['physical']['incidents'])
        self.assertFalse(receipt['physical']['fixed_public_fleet'])
        self.assertEqual('strict-receiver-v1', receipt['configuration_validation']['admission_policy'])
        self.assertGreater(receipt['turn_restriction_audit']['mappable_lanes_admit'], 0)
        self.assertIn(str(contract.SCENARIO / 'network.xml'), receipt['source_sha256'])
        self.assertIn(build['catalog'], receipt['source_sha256'])
        self.assertTrue(receipt['concurrency_test_required'])

    def test_new_network_or_uncommitted_historical_geometry_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Only the existing'):
            contract.preflight(self.folder / 'config.xml', self.folder / 'catalog.json', 10, 10, 1, 4)
        with patch.object(contract, '_git', return_value='scenarios/zona1/network.xml'):
            with self.assertRaisesRegex(ValueError, 'differ from HEAD'):
                contract.preflight(contract.SCENARIO / 'config-simz1.xml', self.folder / 'catalog.json', 10, 10, 1, 4)

    def test_changed_input_fails_source_pin(self):
        file = self.folder / 'source'
        file.write_text('before')
        receipt = {'source_sha256': {str(file): contract.sha256(file)}}
        self.assertEqual('valid', contract.verify_sources(receipt)['status'])
        file.write_text('after')
        with self.assertRaisesRegex(ValueError, 'changed after preflight'):
            contract.verify_sources(receipt)

    def fixture_run(self):
        folder = self.folder / 'run'
        folder.mkdir()
        (folder / 'output').mkdir()
        root = ET.Element('config')
        for key, value in contract.EXPECTED.items():
            contract._set(root, key, value)
        contract._set(root, 'zona1Priority.stopSeconds', '5.0')
        ET.ElementTree(root).write(folder / 'output/output_config.xml', encoding='utf-8')
        manifest = dict(schema_version=1, folder=str(folder), run_id='test-run', status='completed',
                        validation={'status': 'valid'}, demand_seed=1, matsim_seed=1,
                        counts={'planned_persons': 10}, iterations={'completed': [0]},
                        admission_execution={'verification': 'effective_config_matches', 'force_after_stuck_time': False})
        (folder / 'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        receipt = dict(source_sha256={}, minimum=10, maximum=10, demand_seed=1, matsim_seed=1,
                       expected_configuration=contract.EXPECTED)
        return folder, receipt, manifest

    def test_new_source_requires_fresh_regressions(self):
        receipt = {'code_inventory': ['old.java'], 'source_sha256': {}}
        with patch.object(contract, 'source_hashes', return_value={'old.java': 'x', 'new.java': 'y'}):
            with self.assertRaisesRegex(ValueError, 'Source inventory changed'):
                contract.verify_sources(receipt)

    def test_verify_run_revalidates_outputs_without_rewriting_manifest(self):
        folder, receipt, _ = self.fixture_run()
        before = (folder / 'run-manifest.json').read_bytes()
        def validated(_directory, manifest):
            manifest['effective_configuration_validation'] = {'status': 'valid'}
        with patch.object(contract, 'validate_outputs', side_effect=validated) as validate:
            result = contract.verify_run(folder, receipt)
            self.assertEqual('completed_and_revalidated', result['status'])
            validate.assert_called_once()
        self.assertEqual(before, (folder / 'run-manifest.json').read_bytes())

    def test_completed_label_alone_is_insufficient(self):
        folder, receipt, manifest = self.fixture_run()
        manifest['validation']['status'] = 'pending'
        (folder / 'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with patch.object(contract, 'validate_outputs') as validate:
            with self.assertRaisesRegex(ValueError, 'not completed and validated'):
                contract.verify_run(folder, receipt)
            validate.assert_not_called()

    def test_invalid_effective_policy_and_full_validation_failure_stop_flow(self):
        folder, receipt, _ = self.fixture_run()
        with patch.object(contract, 'validate_outputs', side_effect=ValueError('events truncated')):
            with self.assertRaisesRegex(ValueError, 'events truncated'):
                contract.verify_run(folder, receipt)
        root = ET.parse(folder / 'output/output_config.xml').getroot()
        contract._set(root, 'zona1Diagnostics.incidentsEnabled', 'true')
        ET.ElementTree(root).write(folder / 'output/output_config.xml', encoding='utf-8')
        with patch.object(contract, 'validate_outputs'):
            with self.assertRaisesRegex(ValueError, 'Effective configuration mismatch'):
                contract.verify_run(folder, receipt)

    def test_changed_road_catalog_and_unexpected_sample_fail_validation(self):
        folder, receipt, _ = self.fixture_run()
        receipt['predicted_persons'] = 11
        with self.assertRaisesRegex(ValueError, 'seeded inclusive range'):
            contract.verify_run(folder, receipt)
        receipt['predicted_persons'] = 10
        receipt['expected_catalog'] = {'scenario_version': contract.SUBSET_VERSION}
        with patch.object(contract, 'validate_outputs'):
            with self.assertRaisesRegex(ValueError, 'catalog/version differs'):
                contract.verify_run(folder, receipt)


if __name__ == '__main__':
    unittest.main()
