"""The acceptance fingerprint must include historical and current freight inputs."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import simz1_workflow_state as workflow
from simz1_workflow_state import fingerprint


PROBE = ('scenarios/zona1/od/balanced-gateway-v1/access-review-v2/'
         'osm-evidence/Restriction17478998Probe.java')
from simz1_history_fixtures import REQUIRED_HISTORY_FILES
from simz1_scale_contract import BASE_INPUTS, TRIAL_SPEC, RANDOM_POLICY, DIAGNOSTIC_SPEC, ORIGIN_SPEC, ORIGIN_POLICY, FREIGHT_SPEC, FREIGHT_POLICY, TRANSIT_SPEC, TRANSIT_SERVICE, TRANSIT_BUNDLE
REQUIRED_FIXTURE_FILES = REQUIRED_HISTORY_FILES + (
    'src/main/resources/simz1/freight-completion-v1.json',
    'scenarios/zona1/experiments/final-20261102-v1.json',
    'src/main/resources/simz1/day-observation-v1.json',
    'scenarios/zona1/experiments/final-20261103-24h-v2.json',
    'pom.xml', 'scenarios/zona1/config-simz1.xml',
    'scenarios/zona1/network.xml',
    'scenarios/zona1/agent-types-car-moto-v1.json', PROBE,
    'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/config-l18-local-v1.xml',
    'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/signalControl-l18-local-v1.xml',
    'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/l18-local-v1.json',
) + tuple(BASE_INPUTS.values()) + (TRIAL_SPEC, RANDOM_POLICY, DIAGNOSTIC_SPEC, ORIGIN_SPEC, ORIGIN_POLICY, FREIGHT_SPEC, FREIGHT_POLICY, TRANSIT_SPEC, TRANSIT_SERVICE, TRANSIT_BUNDLE)


class FreightVersionFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.root = self._new_fixture_root()

    def _new_fixture_root(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in REQUIRED_FIXTURE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # Validate compiles the real probe, so its bytes bind approval too.
            # These controlled bytes are only hashed; no Java runs in this fixture.
            content = 'final class Restriction17478998Probe {}\n' if relative == PROBE else 'fixture'
            path.write_text(content, encoding='utf-8')
        return root

    def test_routes_and_service_changes_in_either_version_invalidate_acceptance(self):
        for version in ('v1', 'v2', 'compact-v3'):
            for name in ('routes.json', f'service-composition-{version}.json'):
                with self.subTest(version=version, file=name):
                    path = self.root / f'scenarios/zona1/freight/weekday-{version}' / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('{"fixture":1}', encoding='utf-8')
                    accepted = fingerprint(self.root)
                    path.write_text('{"fixture":2}', encoding='utf-8')
                    self.assertNotEqual(accepted, fingerprint(self.root))
                    path.write_text('{"fixture":1}', encoding='utf-8')
                    self.assertEqual(accepted, fingerprint(self.root))

    def test_adding_versioned_routes_invalidates_an_older_acceptance(self):
        accepted = fingerprint(self.root)
        path = self.root / 'scenarios/zona1/freight/weekday-v2/routes.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"routes":[]}', encoding='utf-8')
        self.assertNotEqual(accepted, fingerprint(self.root))

    def test_trial_must_have_used_exact_compact_service(self):
        current = dict(manifest_sha256='manifest', quality_sha256='quality', run_id='trial',
                       freight_service_version='weekday-compact-v3', freight_service_sha256='compact')
        state = self.root/'trial.json'
        state.write_text(json.dumps(dict(current, run_directory=str(self.root), source_fingerprint='revision')))
        args = ['require-trial', '--state', str(state)]
        with patch.object(workflow, 'fingerprint', return_value='revision'), patch.object(workflow, 'inspect', return_value=current):
            self.assertEqual(workflow.main(args+['--freight-service-version', 'weekday-compact-v3', '--freight-service-sha256', 'compact']), 0)
            self.assertEqual(workflow.main(args+['--freight-service-version', 'weekday-v2']), 1)
            self.assertEqual(workflow.main(args+['--freight-service-sha256', 'different']), 1)

    def test_required_sources_bind_acceptance_and_cannot_be_absent(self):
        accepted = fingerprint(self.root)
        for relative in REQUIRED_FIXTURE_FILES:
            with self.subTest(file=relative):
                path = self.root / relative
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\nchanged fixture\n')
                    self.assertNotEqual(accepted, fingerprint(self.root))
                    path.unlink()
                    with self.assertRaises(ValueError) as error:
                        fingerprint(self.root)
                    self.assertEqual(str(error.exception), 'Required source absent: ' + str(path))
                finally:
                    path.write_bytes(original)
                self.assertEqual(accepted, fingerprint(self.root))

    def test_osm_sequence_contract_and_declared_source_bind_acceptance(self):
        # Exercise the production manifest path with small synthetic bytes only.
        source = self.root / 'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/map.osm'
        source.write_text('<osm version="0.6"/>\n', encoding='utf-8')
        contract = self.root / 'src/main/resources/simz1/osm-sequences-v1.json'
        contract.parent.mkdir(parents=True,exist_ok=True)
        document = dict(schema='simz1-osm-sequences', version=1,
                        sources={source.relative_to(self.root).as_posix(): dict(sha256=workflow.sha(source))},
                        restrictions=[dict(relation_id='fixture', modes=['car'], exceptions=[],
                                           sequences=[['fixture_from', 'fixture_to']])])
        contract.write_text(json.dumps(document), encoding='utf-8')
        accepted = fingerprint(self.root)
        document['restrictions'][0]['sequences'][0][-1] = 'fixture_other_to'
        for path, changed in ((contract, json.dumps(document).encode('utf-8')),
                              (source, b'<osm version="0.6"><node id="1"/></osm>\n')):
            with self.subTest(file=path.relative_to(self.root).as_posix(), change='content'):
                original = path.read_bytes()
                try:
                    path.write_bytes(changed)
                    self.assertNotEqual(accepted, fingerprint(self.root))
                finally:
                    path.write_bytes(original)
                self.assertEqual(accepted, fingerprint(self.root))
        with self.subTest(file=source.relative_to(self.root).as_posix(), change='missing'):
            source.unlink()
            with self.assertRaises(ValueError) as error:
                fingerprint(self.root)
            self.assertEqual(str(error.exception), 'Required source absent: ' + str(source))

    def test_fixture_roots_are_independent_and_reproducible(self):
        accepted = fingerprint(self.root)
        freight = self.root / 'scenarios/zona1/freight/weekday-v2/routes.json'
        freight.parent.mkdir(parents=True)
        freight.write_text('{"routes":[]}', encoding='utf-8')
        (self.root / PROBE).unlink()
        fresh = self._new_fixture_root()
        self.assertNotEqual(fresh, self.root)
        self.assertEqual({p.relative_to(fresh).as_posix() for p in fresh.rglob('*') if p.is_file()},
                         set(REQUIRED_FIXTURE_FILES))
        self.assertEqual(accepted, fingerprint(fresh))
        self.assertFalse((self.root / PROBE).exists())
        self.assertTrue(freight.is_file())

    def test_experiment_policy_and_specification_cannot_disappear_or_mutate(self):
        for name in ('src/main/resources/simz1/freight-completion-v1.json',
                     'scenarios/zona1/experiments/final-20261102-v1.json',
                     'src/main/resources/simz1/day-observation-v1.json',
                     'scenarios/zona1/experiments/final-20261103-24h-v2.json', ORIGIN_SPEC, ORIGIN_POLICY):
            path=self.root/name;original=path.read_bytes();before=fingerprint(self.root)
            path.write_bytes(original+b'changed');self.assertNotEqual(before,fingerprint(self.root))
            path.unlink()
            with self.assertRaisesRegex(ValueError,'Required source absent'):fingerprint(self.root)
            path.write_bytes(original);self.assertEqual(before,fingerprint(self.root))


if __name__ == '__main__':
    unittest.main()
