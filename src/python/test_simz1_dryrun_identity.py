"""The DryRun preparation boundary, with no population or native run artifacts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generate_montecarlo_z1 as generator
import simz1_scale_contract as contract
import simz1_workflow_state as workflow
import test_simz1_random_launch as launch_fixtures


class PreparationDryRunIdentityTests(unittest.TestCase):
    def setUp(self):
        self.spec = contract.PROJECT/contract.DIAGNOSTIC_SPEC
        self.selected = contract.experiment(self.spec, 'run10000')
        self.fingerprint = '1'*64
        self.request = dict(launch_id='a'*32, dry_run=True, experiment=self.selected,
            minimum_non_public_vehicles=10000, maximum_non_public_vehicles=10000,
            demand_seed=20261023, matsim_seed=20261023, iterations=1,
            first_iteration=0, last_iteration=0, service_date='2026-10-23',
            public_vehicles=269, transmetro_vehicles=176, tubus_vehicles=93,
            od_mode='balanced-gateway-v1',postprocessing_policy='native_diagnostic_v1')

    def verify(self, request=None, spec=None, source_fingerprint=None):
        with patch.object(workflow, 'fingerprint', return_value=self.fingerprint):
            return workflow.verify_preparation_identity(spec or self.spec, 'run10000',
                self.request if request is None else request,
                self.fingerprint if source_fingerprint is None else source_fingerprint)

    def test_correct_run10k_uses_real_pin_and_removes_only_temporary_spec(self):
        destinations = []
        original = generator.pin_experiment_specification

        def capture(source, destination, selection):
            destinations.append(Path(destination))
            result = original(source, destination, selection)
            self.assertEqual(list(Path(destination).parent.iterdir()), [Path(destination)])
            return result

        with patch.object(generator, 'pin_experiment_specification', side_effect=capture) as pin, \
                patch.object(generator, 'generar', side_effect=AssertionError('No population generation')):
            receipt = self.verify()
        pin.assert_called_once()
        self.assertFalse(destinations[0].parent.exists())
        self.assertEqual(receipt['status'], 'verified')
        self.assertEqual(receipt['copied_specification_sha256'], self.selected['specification_sha256'])
        self.assertEqual(receipt['experiment'], self.selected)
        self.assertEqual(receipt['source_fingerprint'], self.fingerprint)

    def test_preparation_rejects_changed_or_missing_postprocessing_scope(self):
        for value in (None,'automatic_replay_v1','unknown'):
            with self.subTest(policy=value),self.assertRaisesRegex(ValueError,'postprocessing policy differs'):
                self.verify(request=dict(self.request,postprocessing_policy=value))

    def test_receipt_explicitly_binds_native_scope_with_version_two(self):
        receipt=self.verify()
        self.assertEqual(receipt['schema'],'simz1-preparation-identity-v2')
        self.assertEqual(receipt['postprocessing_policy'],'native_diagnostic_v1')

    def test_original_crlf_reserialization_fails_same_identity_comparison(self):
        def legacy_serializer(source, destination, selection):
            # The pre-fix atomic_json path, explicitly modeling Windows CRLF.
            doc = json.loads(Path(source).read_text(encoding='utf-8-sig'))
            raw = (json.dumps(doc, indent=2, ensure_ascii=False)+'\n').replace('\n', '\r\n').encode('utf-8')
            Path(destination).write_bytes(raw)
            return Path(destination)

        with patch.object(generator, 'pin_experiment_specification', side_effect=legacy_serializer), \
                self.assertRaisesRegex(ValueError, '^Experiment selection identity differs$'):
            self.verify()
        self.assertEqual(self.verify()['status'], 'verified')

    def test_transport_mutations_are_rejected_before_preparation(self):
        mutations = dict(schema='simz1-final-experiments-v4', scenario='run1000',
            total_non_public_vehicles=10001, demand_seed=7,
            specification_sha256='f'*64, iterations=2, service_date='2026-10-24',
            observation_end_seconds=108000, base_scenario_identity='f'*64)
        for key, value in mutations.items():
            request = copy.deepcopy(self.request)
            request['experiment'][key] = value
            with self.subTest(field=key), \
                    patch.object(generator, 'pin_experiment_specification') as pin, \
                    self.assertRaisesRegex(ValueError, 'selection identity differs'):
                self.verify(request=request)
            pin.assert_not_called()

    def test_source_fingerprint_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source fingerprint differs'):
            self.verify(source_fingerprint='2'*64)

    def test_sources_changing_during_verification_are_rejected(self):
        with patch.object(workflow, 'fingerprint', side_effect=[self.fingerprint, '2'*64]), \
                self.assertRaisesRegex(ValueError, 'sources changed during verification'):
            workflow.verify_preparation_identity(self.spec, 'run10000', self.request, self.fingerprint)

    def test_specification_same_json_different_sha_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='simz1-dryrun-sha-') as temporary:
            alternate = Path(temporary)/'specification.json'
            alternate.write_bytes(self.spec.read_bytes()+b' ')
            self.assertEqual(json.loads(alternate.read_bytes()), json.loads(self.spec.read_bytes()))
            with self.assertRaisesRegex(ValueError, 'selection identity differs'):
                self.verify(spec=alternate)

    def test_schema_change_in_source_document_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='simz1-dryrun-schema-') as temporary:
            alternate = Path(temporary)/'specification.json'
            changed = json.loads(self.spec.read_bytes())
            changed['schema'] = contract.RANDOM_SCHEMA
            alternate.write_bytes(contract._json_bytes(changed))
            with self.assertRaises(ValueError):
                self.verify(spec=alternate)

    def test_v3_and_v4_selection_cannot_replace_v5(self):
        v3 = contract.experiment(contract.PROJECT/contract.TRIAL_SPEC, 'run1000')
        v4 = dict(self.selected, schema=contract.RANDOM_SCHEMA,
            scenario=contract.RANDOM_SCENARIO, selection_sha256='f'*64,
            selection=dict(selection_id='f'*32, source_fingerprint=self.fingerprint))
        for selected in (v3, v4):
            with self.subTest(schema=selected['schema']), \
                    self.assertRaisesRegex(ValueError, 'selection identity differs'):
                self.verify(request=dict(self.request, experiment=selected))

    def test_dryrun_to_run_requires_receipt_bound_to_selection_and_sources(self):
        receipt = self.verify()
        with tempfile.TemporaryDirectory(prefix='simz1-dryrun-receipt-') as temporary:
            directory = Path(temporary)
            path = directory/'preparation-identity.json'

            def check(value, selected=None):
                path.write_bytes(contract._json_bytes(value))
                state = dict(preparation_identity_sha256=workflow.sha(path),postprocessing_policy='native_diagnostic_v1')
                workflow.require_preparation_identity(directory, state, self.request,
                    self.selected if selected is None else selected, self.fingerprint)

            check(receipt)
            changed = dict(self.selected, total_non_public_vehicles=10001)
            with self.assertRaisesRegex(ValueError, 'selection identity differs'):
                check(receipt, selected=changed)
            for key, value in dict(schema='legacy-receipt', source_fingerprint='2'*64,
                    launch_id='b'*32, dry_run=False, copied_specification_sha256='f'*64,
                    verification='skipped',postprocessing_policy='automatic_replay_v1').items():
                with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'receipt differs'):
                    check(dict(receipt, **{key:value}))
            with self.assertRaisesRegex(ValueError, 'receipt differs'):
                check(dict(receipt, dry_run=1))
            substituted = copy.deepcopy(receipt)
            substituted['experiment']['schema'] = contract.RANDOM_SCHEMA
            with self.assertRaisesRegex(ValueError, 'selection identity differs'):
                check(substituted)

    def test_missing_or_modified_preparation_receipt_rejected(self):
        receipt = self.verify()
        with tempfile.TemporaryDirectory(prefix='simz1-dryrun-receipt-') as temporary:
            directory = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                workflow.require_preparation_identity(directory, dict(postprocessing_policy='native_diagnostic_v1'), self.request,
                    self.selected, self.fingerprint)
            path = directory/'preparation-identity.json'
            path.write_bytes(contract._json_bytes(receipt))
            state = dict(preparation_identity_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         postprocessing_policy='native_diagnostic_v1')
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'receipt hash differs'):
                workflow.require_preparation_identity(directory, state, self.request,
                    self.selected, self.fingerprint)


class VersionedLoadDryRunGateTests(unittest.TestCase):
    def fixture(self, selector):
        case=launch_fixtures.RandomDryRunGateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.selected=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,selector)
        case.request.update(experiment=case.selected,
            minimum_non_public_vehicles=case.selected['total_non_public_vehicles'],
            maximum_non_public_vehicles=case.selected['total_non_public_vehicles'],
            iterations=case.selected['iterations'],last_iteration=case.selected['iterations']-1)
        if selector == 'run1000':
            case.state['prior_trial_status']='not_applicable_this_is_trial'
        case.write_preparation_receipt()
        return case

    def test_half_and_max_test_require_their_own_verified_dryrun(self):
        for selector,total in [('half',110000),('max-test',220000)]:
            with self.subTest(selector=selector):
                case=self.fixture(selector)
                self.assertEqual(case.selected['total_non_public_vehicles'],total)
                self.assertEqual(case.check(),case.launch_id)
                case.request['postprocessing_policy']='native_diagnostic_v1'
                case.state['postprocessing_policy']='native_diagnostic_v1'
                case.write_preparation_receipt()
                self.assertEqual(case.check(postprocessing_policy='native_diagnostic_v1'),case.launch_id)
                with self.assertRaisesRegex(ValueError,'postprocessing policy differs'):
                    case.check(postprocessing_policy='automatic_replay_v1')
                changed=dict(case.selected,scenario='run1000')
                with self.assertRaises(ValueError):
                    case.check(request=dict(case.request,experiment=changed))

    def test_all_official_v3_selectors_share_the_gate(self):
        for selector,total in [('run1000',1000),('quarter',55000),('buses',0),('full-1',204186),('full-10',204186)]:
            with self.subTest(selector=selector):
                case=self.fixture(selector)
                self.assertEqual(case.selected['total_non_public_vehicles'],total)
                self.assertEqual(case.check(),case.launch_id)

    def test_trial_and_quarter_reject_stale_unapproved_or_unbound_preparation(self):
        for selector in ('run1000','quarter'):
            case=self.fixture(selector)
            for key,value in [('source_fingerprint','stale-revision'),('run_launch_eligible',False),
                              ('prior_trial_status','pending_not_approved'),('status','preflight'),
                              ('phase','acceptance_gates'),('outcome','BLOCKED'),('exit_code',1),
                              ('dry_run',False),('run_id','simz1-not-a-dryrun')]:
                with self.subTest(selector=selector,state_field=key),self.assertRaises(ValueError):
                    case.check(state=dict(case.state,**{key:value}))
            wrong_prior=('accepted_same_base_and_revision' if selector=='run1000'
                         else 'not_applicable_this_is_trial')
            with self.subTest(selector=selector,wrong_trial_scope=True),self.assertRaises(ValueError):
                case.check(state=dict(case.state,prior_trial_status=wrong_prior))
            with self.subTest(selector=selector,missing_id=True),self.assertRaises(ValueError):
                case.check(launch_id='')
            (case.directory/'preparation-identity.json').unlink()
            with self.subTest(selector=selector,missing_proof=True),self.assertRaises(FileNotFoundError):
                case.check()

    def test_trial_and_quarter_cannot_change_selection_sha_or_policy_after_dryrun(self):
        for selector in ('run1000','quarter'):
            case=self.fixture(selector)
            for key,value in [('scenario','half'),('specification_sha256','f'*64),
                              ('total_non_public_vehicles',110000),('iterations',2),
                              ('demand_seed',7),('observation_end_seconds',108000)]:
                request=copy.deepcopy(case.request)
                request['experiment'][key]=value
                with self.subTest(selector=selector,selection_field=key),self.assertRaises(ValueError):
                    case.check(request=request)
            with self.subTest(selector=selector,policy=True),self.assertRaises(ValueError):
                case.check(postprocessing_policy='native_diagnostic_v1')
            self.assertEqual(case.check(postprocessing_policy='automatic_replay_v1'),case.launch_id)

    def test_authorized_ten_iterations_cannot_change_count_after_dryrun(self):
        case=self.fixture('full-10')
        self.assertEqual(case.selected['iterations'],10)
        self.assertEqual(case.check(),case.launch_id)
        for key,value in [('iterations',1),('first_iteration',1),('last_iteration',0)]:
            with self.subTest(field=key),self.assertRaises(ValueError):
                case.check(request=dict(case.request,**{key:value}))


if __name__ == '__main__':
    unittest.main()
