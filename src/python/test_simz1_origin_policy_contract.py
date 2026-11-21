"""Opt-in origin-policy contracts in temporary fixtures; no QSim or real receipts."""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_montecarlo_z1 as generator
import simz1_scale_contract as contract
import simz1_workflow_state as workflow
import simz1_configuration_contract as configuration
from simz1_config_validation import validate_configuration, admission_execution_contract
from simz1_balanced_od_audit import check_config
from test_simz1_configuration_contract import fixture_config as retention_fixture_config, set_param
from test_simz1_freight_version import REQUIRED_FIXTURE_FILES


def fixture_config():
    # The retention fixture deliberately omits network inputs. Admission's
    # configuration validator also requires the enabled lanes to be declared.
    # This is an in-memory contract fixture; it never loads a network or QSim.
    root = retention_fixture_config()
    network = ET.SubElement(root, 'module', name='network')
    ET.SubElement(network, 'param', name='laneDefinitionsFile', value='synthetic-fixture-lanes.xml')
    return root


class OriginPolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = contract.PROJECT/contract.ORIGIN_SPEC
        cls.document = json.loads(cls.spec.read_bytes())
        cls.selections = {n: contract.experiment(cls.spec, 'run'+str(n))
                          for n in (1000, 10000, 55000, 110000)}

    def request(self, n=10000):
        return dict(launch_id='a'*32, dry_run=True, experiment=copy.deepcopy(self.selections[n]),
            minimum_non_public_vehicles=n, maximum_non_public_vehicles=n,
            demand_seed=20261023, matsim_seed=20261023, iterations=1,
            first_iteration=0, last_iteration=0, service_date='2026-10-23',
            public_vehicles=269, transmetro_vehicles=176, tubus_vehicles=93,
            od_mode='balanced-gateway-v1', postprocessing_policy='native_diagnostic_v1')

    def verify_preparation(self, request=None):
        request = self.request() if request is None else request
        with patch.object(workflow, 'fingerprint', return_value='1'*64):
            return workflow.verify_preparation_identity(self.spec, 'run10000', request, '1'*64)

    def test_exact_four_scales_same_policy_and_base_without_new_draw(self):
        self.assertEqual(self.document, contract.origin_specification())
        self.assertEqual(set(self.document['scenarios']), {'run'+str(n) for n in self.selections})
        identities = set()
        for n, selected in self.selections.items():
            with self.subTest(n=n):
                self.assertEqual(selected['composition'], dict(carro=n*44//100,
                    moto=n*55//100, pesado=n//100, public_transport=269))
                self.assertEqual(contract.require_scale(n, 20261023, 1, self.spec, selected['scenario']),
                                 selected['composition'])
                self.assertEqual((selected['iterations'], selected['observation_end_seconds'],
                                  selected['native_qsim_end_seconds']), (1, 86400, 86399))
                self.assertEqual(contract.origin_policy_for_selection(selected), contract.GAP_ORIGIN_POLICY)
                self.assertEqual(contract.launch_postprocessing_policy(selected), 'native_diagnostic_v1')
                identities.add(selected['base_scenario_identity'])
        self.assertEqual(len(identities), 1)
        with (patch.object(contract.secrets, 'token_hex', side_effect=AssertionError('No entropy')),
              patch.object(contract, '_exclusive_write', side_effect=AssertionError('No receipt'))):
            contract.origin_specification()

    def test_historical_v3_v5_documents_and_defaults_stay_unchanged(self):
        paths = [contract.PROJECT/contract.TRIAL_SPEC, contract.PROJECT/contract.DIAGNOSTIC_SPEC]
        before = {p:p.read_bytes() for p in paths}
        self.assertEqual(json.loads(before[paths[0]]), contract.trial_specification())
        self.assertEqual(json.loads(before[paths[1]]), contract.diagnostic_specification())
        old_trial = contract.experiment(paths[0], 'run1000')
        old_10k = contract.experiment(paths[1], 'run10000')
        self.assertEqual(old_trial['base_scenario_identity'], old_10k['base_scenario_identity'])
        self.assertNotEqual(old_trial['base_scenario_identity'], self.selections[1000]['base_scenario_identity'])
        for old in (None, old_trial, old_10k):
            self.assertEqual(contract.origin_policy_for_selection(old), contract.LEGACY_ORIGIN_POLICY)
        self.assertEqual({p:p.read_bytes() for p in paths}, before)
        self.assertEqual(contract.launch_postprocessing_policy(old_trial), 'automatic_replay_v1')
        with self.assertRaises(ValueError):
            contract.launch_postprocessing_policy(old_trial, 'native_diagnostic_v1')

    def test_specification_mutation_and_unrecognized_selector_rejected(self):
        variants = []
        for field, value in [('schema', 'unknown'), ('demand_seed', 7), ('public_vehicles', 270),
                             ('observation_end_seconds', 108000)]:
            changed = copy.deepcopy(self.document);changed[field] = value;variants.append(changed)
        changed = copy.deepcopy(self.document);changed['origin_admission_policy']['version'] = contract.LEGACY_ORIGIN_POLICY;variants.append(changed)
        changed = copy.deepcopy(self.document);changed['scenarios']['run10000']['composition']['carro'] += 1;variants.append(changed)
        changed = copy.deepcopy(self.document);changed['scenarios']['run10000']['iterations'] = True;variants.append(changed)
        changed = copy.deepcopy(self.document);changed['extra_override'] = 'ignored?';variants.append(changed)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mutant.json'
            for index, changed in enumerate(variants):
                with self.subTest(index=index):
                    path.write_text(json.dumps(changed), encoding='utf-8')
                    with self.assertRaises(ValueError):contract.experiment(path, 'run10000')
        with self.assertRaises(ValueError):contract.experiment(self.spec, 'half')

    def test_policy_content_mutation_and_absence_rejected(self):
        original = (contract.PROJECT/contract.ORIGIN_POLICY).read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);path = root/contract.ORIGIN_POLICY
            path.parent.mkdir(parents=True);path.write_bytes(original)
            with patch.object(contract, 'PROJECT', root):
                self.assertEqual(contract.origin_policy_identity()['policy_sha256'], hashlib.sha256(original).hexdigest())
                changed = json.loads(original);changed['minimum_body_gap_m'] = 0.09
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(ValueError):contract.origin_policy_identity()
                path.unlink()
                with self.assertRaises(FileNotFoundError):contract.origin_policy_identity()

    def test_policy_and_specification_are_required_fingerprint_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED_FIXTURE_FILES:
                path = root/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_text('fixture', encoding='utf-8')
            before = workflow.fingerprint(root)
            for name in (contract.ORIGIN_SPEC, contract.ORIGIN_POLICY):
                with self.subTest(name=name):
                    path=root/name;original=path.read_bytes();path.write_bytes(original+b'changed')
                    self.assertNotEqual(workflow.fingerprint(root), before)
                    path.unlink()
                    with self.assertRaisesRegex(ValueError, 'Required source absent'):workflow.fingerprint(root)
                    path.write_bytes(original);self.assertEqual(workflow.fingerprint(root), before)

    def test_generation_helper_preserves_legacy_absence_and_requires_opt_in(self):
        root = fixture_config();set_param(root, 'simz1Admission.originPolicy', None)
        original = ET.tostring(root)
        self.assertEqual(generator.apply_origin_admission_selection(root, None), contract.LEGACY_ORIGIN_POLICY)
        self.assertEqual(ET.tostring(root), original)
        generator.apply_origin_admission_selection(root, self.selections[10000])
        self.assertEqual(root.find("module[@name='simz1Admission']/param[@name='originPolicy']").get('value'), contract.GAP_ORIGIN_POLICY)
        with self.assertRaises(ValueError):generator.apply_origin_admission_selection(root, None)
        self.assertEqual(validate_configuration(root)['origin_admission_policy'], contract.GAP_ORIGIN_POLICY)

    def test_legacy_explicit_and_absent_have_equal_native_contracts(self):
        explicit = fixture_config();absent = copy.deepcopy(explicit)
        set_param(absent, 'simz1Admission.originPolicy', None)
        self.assertEqual(validate_configuration(absent), validate_configuration(explicit))
        self.assertEqual(configuration.normalize_configuration(absent), configuration.normalize_configuration(explicit))

    def test_invalid_policy_and_unsupported_physical_combinations_rejected(self):
        for key, value in [('simz1Admission.originPolicy','unknown'),
                           ('simz1Admission.storagePolicy','matsim15-native'),
                           ('simz1Admission.wholeVehicleReservation','false'),
                           ('qsim.numberOfThreads','2'), ('qsim.trafficDynamics','withHoles'),
                           ('qsim.linkDynamics','PassingQ')]:
            with self.subTest(key=key):
                root = fixture_config();set_param(root, 'simz1Admission.originPolicy', contract.GAP_ORIGIN_POLICY)
                validate_configuration(root)
                set_param(root, key, value)
                reason = 'originPolicy' if key == 'simz1Admission.originPolicy' else 'physical-gap-origin-v1'
                with self.assertRaisesRegex(ValueError, reason):validate_configuration(root)
        root = fixture_config();module=root.find("module[@name='simz1Admission']")
        ET.SubElement(module, 'param', name='originPolicy', value=contract.GAP_ORIGIN_POLICY)
        with self.assertRaises(ValueError):validate_configuration(root)
        with self.assertRaises(ValueError):generator.apply_origin_admission_selection(root, self.selections[1000])

    def test_enabled_lanes_still_require_their_input_declaration(self):
        root = fixture_config();generator.apply_origin_admission_selection(root, self.selections[1000])
        validate_configuration(root)
        set_param(root, 'network.laneDefinitionsFile', None)
        with self.assertRaisesRegex(ValueError, 'network.laneDefinitionsFile'):
            validate_configuration(root)

    def test_effective_config_cannot_lose_or_change_selected_origin_policy(self):
        requested=fixture_config();generator.apply_origin_admission_selection(requested, self.selections[1000])
        self.assertEqual(admission_execution_contract(requested, copy.deepcopy(requested))['origin_policy'], contract.GAP_ORIGIN_POLICY)
        changed=copy.deepcopy(requested);set_param(changed, 'simz1Admission.originPolicy', None)
        with self.assertRaisesRegex(ValueError, 'origin_admission_policy'):
            admission_execution_contract(requested, changed)
        expected=configuration.expected_from_selection(self.selections[1000])
        self.assertEqual(expected['physical']['simz1Admission.originPolicy'], contract.GAP_ORIGIN_POLICY)
        configuration.assert_configuration(configuration.normalize_configuration(requested), expected)
        with self.assertRaises(ValueError):configuration.assert_configuration(configuration.normalize_configuration(changed), expected)

    def test_balanced_audit_requires_the_selected_policy_not_just_valid_value(self):
        root=fixture_config()
        for key, value in [('global.randomSeed','20261023'), ('controler.enableLinkToLinkRouting','true')]:
            module,name=key.split('.');group=root.find(f"module[@name='{module}']")
            if group is None:group=ET.SubElement(root, 'module', name=module)
            ET.SubElement(group, 'param', name=name, value=value)
        generator.apply_origin_admission_selection(root, self.selections[1000])
        values={m.get('name')+'.'+p.get('name'):p.get('value') for m in root.findall('module') for p in m.findall('param')}
        check_config(values, origin_admission_policy=contract.GAP_ORIGIN_POLICY)
        with self.assertRaises(ValueError):check_config(values)
        values.pop('simz1Admission.originPolicy')
        with self.assertRaises(ValueError):check_config(values, origin_admission_policy=contract.GAP_ORIGIN_POLICY)

    def test_new_trial_identity_is_policy_bound_and_not_an_old_trial(self):
        selected = self.selections[1000]
        manifest=dict(experiment=selected, time_horizon=dict(start_seconds=0,end_seconds=86400),
            demand_seed=20261023,matsim_seed=20261023,
            iterations=dict(first=0,last=0,requested=1,completed=[0]))
        self.assertEqual(workflow.trial_experiment_identity(manifest, {'od_mode':'balanced-gateway-v1'}), selected['base_scenario_identity'])
        for mutate in ('policy','base','size'):
            changed=copy.deepcopy(manifest)
            if mutate=='policy':changed['experiment']['origin_admission_policy']['version']=contract.LEGACY_ORIGIN_POLICY
            elif mutate=='base':changed['experiment']['base_scenario_identity']='0'*64
            else:changed['experiment']=self.selections[10000]
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                workflow.trial_experiment_identity(changed, {'od_mode':'balanced-gateway-v1'})
        old=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC, 'run1000')
        manifest['experiment']=old
        self.assertEqual(workflow.trial_experiment_identity(manifest, {'od_mode':'balanced-gateway-v1'}), old['base_scenario_identity'])
        self.assertNotEqual(old['base_scenario_identity'], selected['base_scenario_identity'])

    def inspect_synthetic_trial(self, selection):
        """Exercise inspect's real dispatch, mocking prior native audit boundaries.

        This temporary metadata fixture contains no native events or simulation,
        and it is never recorded as an acceptance. Physical audits are covered
        by their own suites; this isolates the missing schema dispatch.
        """
        from simz1_agent_types import load_catalog
        from simz1_demand_composition import split
        catalog_source = contract.PROJECT/contract.BASE_INPUTS['agent_catalog']
        composition = split(1000, load_catalog(catalog_source))
        with tempfile.TemporaryDirectory(prefix='origin-inspect-dispatch-test-') as folder:
            run = Path(folder)
            def artifact(name, raw):
                target = run/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(raw)
                return dict(path=name, sha256=hashlib.sha256(raw).hexdigest())
            catalog = artifact('inputs/catalog.json', catalog_source.read_bytes())
            evidence = artifact('synthetic-audit-boundary.txt', b'Synthetic metadata boundary only; no native run.\n')
            run_id = 'synthetic-inspect-schema-dispatch-not-a-run'
            result = dict(events=evidence, plans=evidence, network=evidence,
                private_od_events=dict(evidence_status='closed_native_event_stream',
                                       source=dict(run_id=run_id, events=evidence)))
            manifest = dict(fixture_scope='synthetic dispatch only; native validation mocked; never trial approval',
                folder=str(run), run_id=run_id, status='completed', validation=dict(status='valid'),
                counts=dict(planned_persons=composition['private_vehicles'],
                    freight_vehicles_configured=composition['freight_vehicles'], non_public_vehicles_configured=1000),
                demand_composition=composition, agent_configuration=dict(catalog_artifact=catalog),
                iterations=dict(first=0, last=0, requested=1, completed=[0]), results={'0':result},
                experiment=copy.deepcopy(selection), time_horizon=dict(start_seconds=0, end_seconds=86400),
                demand_seed=20261023, matsim_seed=20261023)
            (run/'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            quality=run/'analysis/it.0/graficas_perfiles/calidad_resultados.json'
            quality.parent.mkdir(parents=True)
            quality.write_text(json.dumps(dict(run_id=run_id,iteration=0,status='screening_pass')),
                               encoding='utf-8')
            with ExitStack() as stack:
                stack.enter_context(patch('simz1_day_observation.enabled', return_value=False))
                stack.enter_context(patch('simz1_balanced_launch.manifest_identity', return_value={'od_mode':'balanced-gateway-v1'}))
                validate=stack.enter_context(patch.object(workflow, 'require_balanced_validation'))
                native=stack.enter_context(patch('simz1_balanced_od_audit.require_native_success'))
                audit=stack.enter_context(patch('simz1_balanced_od_audit.validate_manifest'))
                stack.enter_context(patch('revalidar_simz1.recovery_compatibility', return_value=None))
                record=workflow.inspect(run, expected_people=1000, require_transit=False)
                validate.assert_called_once();native.assert_called_once();audit.assert_called_once()
                self.assertEqual(record['acceptance_vehicles'],1000)
                self.assertEqual(record['acceptance_denominator'],'non_public_vehicles')
                self.assertFalse((run/'trial.json').exists())
                return record

    def test_inspect_dispatches_v6_trial_identity_after_native_audit_boundaries(self):
        record=self.inspect_synthetic_trial(self.selections[1000])
        self.assertEqual(record['base_scenario_identity'],self.selections[1000]['base_scenario_identity'])

    def test_inspect_preserves_v3_dispatch_and_rejects_v6_identity_changes(self):
        old=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,'run1000')
        self.assertEqual(self.inspect_synthetic_trial(old)['base_scenario_identity'],old['base_scenario_identity'])
        for field in ('origin_admission_policy','base_scenario_identity'):
            changed=copy.deepcopy(self.selections[1000])
            if field=='origin_admission_policy':changed[field]['version']=contract.LEGACY_ORIGIN_POLICY
            else:changed[field]='0'*64
            with self.subTest(field=field),self.assertRaises(ValueError):self.inspect_synthetic_trial(changed)

    def test_inspect_does_not_assign_a_trial_base_to_other_schemas(self):
        changed=copy.deepcopy(self.selections[1000]);changed['schema']='unknown-origin-experiment'
        record=self.inspect_synthetic_trial(changed)
        self.assertIsNone(record['base_scenario_identity'])

    def test_preparation_binds_policy_and_expected_configuration_without_run(self):
        with patch.object(generator, 'generar', side_effect=AssertionError('No population or run')):
            receipt=self.verify_preparation()
        self.assertEqual(receipt['experiment'], self.selections[10000])
        self.assertEqual(receipt['configuration']['physical']['simz1Admission.originPolicy'], contract.GAP_ORIGIN_POLICY)
        self.assertEqual(receipt['postprocessing_policy'], 'native_diagnostic_v1')
        for field,value in [('origin_admission_policy',{}),('base_scenario_identity','0'*64),('schema','simz1-final-experiments-v3')]:
            request=self.request();request['experiment'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.verify_preparation(request)

    def test_synthetic_dryrun_receipt_rejects_policy_configuration_and_size_mutations(self):
        # Temporary test document only; never a runtime/workflow or launch receipt.
        receipt=self.verify_preparation();request=self.request()
        state=dict(postprocessing_policy='native_diagnostic_v1')
        with tempfile.TemporaryDirectory(prefix='origin-policy-receipt-test-') as folder:
            path=Path(folder)/'preparation-identity.json'
            def verify(doc):
                path.write_text(json.dumps(doc), encoding='utf-8')
                state['preparation_identity_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                workflow.require_preparation_identity(folder,state,request,self.selections[10000],'1'*64)
            verify(receipt)
            changed=copy.deepcopy(receipt);changed['configuration']['physical']['simz1Admission.originPolicy']=contract.LEGACY_ORIGIN_POLICY
            with self.assertRaises(ValueError):verify(changed)
            changed=copy.deepcopy(receipt);changed['experiment']=self.selections[55000]
            with self.assertRaises(ValueError):verify(changed)
            changed=copy.deepcopy(receipt);changed['source_fingerprint']='2'*64
            with self.assertRaises(ValueError):verify(changed)

    def test_pinned_manifest_cannot_omit_origin_policy_provenance(self):
        selected=self.selections[1000];plans='1'*64;policy=selected['origin_admission_policy']
        manifest=dict(experiment=dict(selected,initial_population_sha256=plans,
            population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization'),
            origin_admission_policy=dict(policy,effective_policy=policy['version'],source='explicit versioned experiment',
                source_policy=contract.LEGACY_ORIGIN_POLICY,artifact=dict(path='inputs/origin-admission-policy.json',sha256=policy['policy_sha256'])),
            inputs=dict(plans=dict(path='plans.xml',sha256=plans)),iterations=dict(first=0,last=0,requested=1,completed=[]),
            demand_seed=20261023,matsim_seed=20261023,
            demand_composition=dict(total_non_public_vehicles=1000,family_counts=dict(carro=440,moto=550,pesado=10)),
            spatial_demand=dict(mode='balanced-gateway-v1'),counts=dict(public_transport_vehicles_configured=269))
        contract.validate_manifest_selection(manifest,selected)
        for field in ('origin_admission_policy','experiment'):
            changed=copy.deepcopy(manifest);changed[field].pop('policy_sha256' if field=='origin_admission_policy' else 'origin_admission_policy')
            with self.subTest(field=field),self.assertRaises(ValueError):contract.validate_manifest_selection(changed,selected)


if __name__ == '__main__':
    unittest.main()
