"""Fixed Run10K identity fixtures; no draw, population generation or native run."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import stat
import xml.etree.ElementTree as ET
from unittest.mock import patch

import simz1_scale_contract as contract


class Run10KExperimentTests(unittest.TestCase):
    def setUp(self):
        self.path = contract.PROJECT/contract.DIAGNOSTIC_SPEC
        self.selected = contract.experiment(self.path, contract.DIAGNOSTIC_SCENARIO)
        self.doc = json.loads(self.path.read_bytes())

    def check_document(self, document):
        with tempfile.TemporaryDirectory(prefix='simz1-run10k-contract-') as folder:
            path = Path(folder)/'copied-experiment.json'
            path.write_bytes(contract._json_bytes(document))
            return contract.experiment(path, contract.DIAGNOSTIC_SCENARIO)

    def request(self):
        return dict(experiment=copy.deepcopy(self.selected),
            minimum_non_public_vehicles=10000, maximum_non_public_vehicles=10000,
            demand_seed=20261023, matsim_seed=20261023, iterations=1, first_iteration=0, last_iteration=0,
            service_date='2026-10-23', public_vehicles=269, transmetro_vehicles=176, tubus_vehicles=93,
            od_mode='balanced-gateway-v1')

    def manifest(self):
        generated = copy.deepcopy(self.selected)
        generated.update(initial_population_sha256='d'*64,
            population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization')
        return dict(status='prepared', experiment=generated, demand_seed=20261023, matsim_seed=20261023,
            inputs=dict(plans=dict(path='plans.xml', sha256='d'*64)),
            iterations=dict(first=0, last=0, requested=1, completed=[]),
            demand_composition=dict(total_non_public_vehicles=10000,
                                    family_counts=dict(carro=4400, moto=5500, pesado=100)),
            counts=dict(public_transport_vehicles_configured=269), spatial_demand=dict(mode='balanced-gateway-v1'))

    def test_exact_fixed_policy_same_physical_base_and_original_trial_size(self):
        trial = contract.experiment(contract.PROJECT/contract.TRIAL_SPEC, 'run1000')
        self.assertEqual(self.doc, contract.diagnostic_specification())
        self.assertEqual(set(self.doc['scenarios']), {'run10000'})
        self.assertEqual(self.selected['composition'], dict(carro=4400,moto=5500,pesado=100,public_transport=269))
        for key in ('base_scenario_identity','base_inputs','demand_seed','service_date','public_vehicles',
                    'observation_policy','native_qsim_end_seconds','observation_end_seconds','signal_variant'):
            self.assertEqual(self.selected[key], trial[key], key)
        self.assertEqual(self.selected['acceptance_trial_scenario'], 'run1000')
        self.assertEqual(trial['total_non_public_vehicles'], 1000)
        self.assertEqual(self.selected['postprocessing'],dict(policy='native_diagnostic_v1',
            replay_preparation='manual_after_native_validation',
            visual_acceptance='separate_not_certified_by_native_gate'))
        self.assertNotIn('postprocessing',trial)
        self.assertEqual((self.selected['iterations'], self.selected['observation_end_seconds'],
                          self.selected['native_qsim_end_seconds']), (1,86400,86399))

    def test_no_entropy_receipt_or_claim_and_historical_documents_preserved(self):
        historical = {name:(contract.PROJECT/name).read_bytes()
                      for name in (contract.TRIAL_SPEC,contract.RANDOM_POLICY)}
        with patch.object(contract.secrets,'token_hex',side_effect=AssertionError('No entropy authorized')), \
             patch.object(contract.uuid,'uuid4',side_effect=AssertionError('No selection identity authorized')), \
             patch.object(contract,'_exclusive_write',side_effect=AssertionError('No receipt authorized')):
            selected = contract.experiment(self.path,'run10000')
            composition = contract.require_scale(10000,20261023,1,self.path,'run10000')
        self.assertEqual(selected['draw'],dict(algorithm='fixed-no-draw-v1',selected_non_public_vehicles=10000))
        self.assertFalse({'selection','selection_sha256','selection_path'} & set(selected))
        self.assertEqual(composition, selected['composition'])
        with self.assertRaisesRegex(ValueError,'random experiment'):
            contract.claim_selection(selected,'a'*32)
        for name,raw in historical.items():self.assertEqual((contract.PROJECT/name).read_bytes(),raw)
        self.assertEqual(hashlib.sha256(historical[contract.TRIAL_SPEC]).hexdigest(),
                         'e60478c6bc3a89e541de00e40487401d72a7bd2aee852cdc7df1084947306b38')

    def test_explicit_contract_required_and_no_other_selector_is_authorized(self):
        self.assertEqual(contract.require_scale(10000,20261023,1,self.path,'run10000'), self.selected['composition'])
        with self.assertRaises(ValueError):contract.require_scale(10000)
        for selector in ('run1000','full-1','random-full-1','max-test',None):
            with self.subTest(selector=selector),self.assertRaises(ValueError):
                contract.experiment(self.path,selector)
        for n,seed,iterations in ((9999,20261023,1),(10001,20261023,1),(10000,7,1),
                (10000,20261023,10),(10000,20261023,0),(10000.0,20261023,1),
                (10000,20261023.0,1),(10000,20261023,True)):
            with self.subTest(n=n,seed=seed,iterations=iterations),self.assertRaises(ValueError):
                contract.require_scale(n,seed,iterations,self.path,'run10000')

    def test_mutated_policy_cannot_become_another_fixed_or_random_experiment(self):
        changes = [lambda d:d.update(demand_seed=7),lambda d:d.update(service_date='2026-10-24'),
            lambda d:d.update(public_vehicles=270),lambda d:d.update(observation_end_seconds=108000),
            lambda d:d.update(native_qsim_end_seconds=86400),lambda d:d.update(signal_variant='other'),
            lambda d:d['base_inputs'].update(source_config='other.xml'),
            lambda d:d['derived_from'].update(sha256='e'*64),lambda d:d.update(acceptance_trial_scenario='run10000'),
            lambda d:d.update(selection={}),lambda d:d['draw'].update(seed='fictional'),
            lambda d:d['postprocessing'].update(replay_preparation='automatic'),
            lambda d:d['postprocessing'].update(visual_acceptance='approved'),
            lambda d:d.pop('postprocessing'),
            lambda d:d['draw'].update(selected_non_public_vehicles=10001),
            lambda d:d['scenarios']['run10000'].update(total_non_public_vehicles=10001),
            lambda d:d['scenarios']['run10000'].update(iterations=10),
            lambda d:d['scenarios']['run10000'].update(iterations=True),
            lambda d:d['scenarios']['run10000'].update(total_non_public_vehicles=10000.0),
            lambda d:d['scenarios']['run10000']['composition'].update(carro=4401),
            lambda d:d['scenarios'].update(run1000=dict(total_non_public_vehicles=1000,iterations=1))]
        for index,change in enumerate(changes):
            document=copy.deepcopy(self.doc);change(document)
            with self.subTest(index=index),self.assertRaises(ValueError):self.check_document(document)

    def test_pinned_copy_preserves_identity(self):
        copied=self.check_document(self.doc)
        contract.verify_selection_identity(copied,self.selected)
        self.assertEqual(copied['specification_sha256'],self.selected['specification_sha256'])
        for name,value in [('composition',dict(carro=4401,moto=5499,pesado=100,public_transport=269)),
                           ('base_scenario_identity','e'*64),('iterations',10),('iterations',True),
                           ('demand_seed',7),('total_non_public_vehicles',10000.0)]:
            changed=copy.deepcopy(copied);changed[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):
                contract.verify_selection_identity(changed,self.selected)
        for name in ('composition','postprocessing'):
            changed=copy.deepcopy(copied);changed.pop(name)
            with self.subTest(missing=name),self.assertRaises(ValueError):
                contract.verify_selection_identity(changed,self.selected)

    def test_actual_catalog_cannot_silently_change_fixed_quotas(self):
        with patch('simz1_demand_composition.split',return_value=dict(family_counts=dict(carro=4401,moto=5499,pesado=100))), \
             self.assertRaisesRegex(ValueError,'fixed quotas'):
            contract.require_scale(10000,20261023,1,self.path,'run10000')

    def test_launch_request_binds_counts_seed_fleet_iteration_and_selection(self):
        request=self.request();contract.verify_launch_request(request,self.selected)
        for name,value in dict(minimum_non_public_vehicles=9999,maximum_non_public_vehicles=10001,
                demand_seed=7,matsim_seed=7,iterations=10,first_iteration=1,last_iteration=1,
                service_date='2026-10-24',public_vehicles=268,transmetro_vehicles=175,tubus_vehicles=94,
                od_mode='network').items():
            changed=copy.deepcopy(request);changed[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):contract.verify_launch_request(changed,self.selected)
        for name,value in [('iterations',True),('first_iteration',False),('maximum_non_public_vehicles',10000.0)]:
            changed=copy.deepcopy(request);changed[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):contract.verify_launch_request(changed,self.selected)

    def test_manifest_population_identity_prepared_and_started_need_no_random_claim(self):
        manifest=self.manifest()
        with patch.object(contract,'validate_run_claim',side_effect=AssertionError('No random claim for fixed Run10K')):
            contract.validate_manifest_selection(manifest,self.selected)
            manifest.update(status='running',launch_id='a'*32)
            contract.validate_manifest_selection(manifest,self.selected)
        self.assertNotIn('selection',manifest['experiment'])

    def test_manifest_rejects_population_seed_iteration_composition_and_plans_mutations(self):
        changes = [lambda m:m.update(demand_seed=7),lambda m:m.update(matsim_seed=7),
            lambda m:m['demand_composition'].update(total_non_public_vehicles=9999),
            lambda m:m['demand_composition']['family_counts'].update(carro=4401),
            lambda m:m['demand_composition']['family_counts'].update(moto=5500.0),
            lambda m:m['counts'].update(public_transport_vehicles_configured=268),
            lambda m:m['iterations'].update(first=1),lambda m:m['iterations'].update(last=1),
            lambda m:m['iterations'].update(requested=10),lambda m:m['iterations'].update(requested=True),
            lambda m:m['iterations'].update(completed=[1]),lambda m:m['iterations'].update(completed=[False]),
            lambda m:m['spatial_demand'].update(mode='network'),
            lambda m:m['experiment'].update(initial_population_sha256='e'*64),
            lambda m:m['experiment'].pop('initial_population_sha256'),
            lambda m:m['experiment'].update(population_identity_basis='other'),
            lambda m:m['inputs']['plans'].update(path='other.xml'),
            lambda m:m['inputs']['plans'].update(sha256='e'*64)]
        for index,change in enumerate(changes):
            manifest=self.manifest();change(manifest)
            with self.subTest(index=index),self.assertRaises(ValueError):
                contract.validate_manifest_selection(manifest,self.selected)

    def test_auditor_cannot_skip_v5_identity_by_downgrading_manifest_schema(self):
        import simz1_balanced_od_audit as audit
        import simz1_run
        with tempfile.TemporaryDirectory(prefix='simz1-run10k-audit-') as directory:
            dummy=Path(directory)/'fixture.json';dummy.write_text('{}',encoding='utf-8')
            manifest=dict(balanced_od=dict(variant='balanced-gateway-v1',implementation={}),
                spatial_demand=dict(mode='balanced-gateway-v1'),
                inputs={'config':{},'input:experiment-specification.json':{}},
                experiment=dict(self.selected,schema='simz1-final-experiments-v3'))
            with patch.object(simz1_run,'checked_path',return_value=dummy), \
                 patch.object(simz1_run,'parameters',return_value={}), \
                 patch.object(audit,'validate_implementation_signature'), \
                 patch.object(contract,'experiment',return_value=self.selected), \
                 self.assertRaisesRegex(ValueError,'selection identity'):
                audit.validate_manifest(Path(directory),manifest)


class NativeBoundaryReached(Exception):
    """Selection/pinned-input guards passed; native/network audit not performed."""


class ExperimentPinningTests(unittest.TestCase):
    def audit_boundary(self, directory, selected):
        import simz1_balanced_od_audit as audit
        from simz1_day_observation import policy_document
        from simz1_run import artifact, atomic_json, sha256
        directory=Path(directory).resolve()
        inputs=directory/'inputs';inputs.mkdir(exist_ok=True)
        plans=directory/'plans.xml';plans.write_bytes(b'<plans/>\n')
        config=directory/'config.xml';root=ET.Element('config')
        for name,values in [('qsim',{'endTime':'23:59:59','timeStepSize':'00:00:01'}),
                            ('simz1Observation',{'policy':'fixed-day-24h-v1'})]:
            module=ET.SubElement(root,'module',name=name)
            for key,value in values.items():ET.SubElement(module,'param',name=key,value=value)
        ET.ElementTree(root).write(config,encoding='utf-8')
        implementation=inputs/'od-implementation.json';atomic_json(implementation,audit.implementation_signature())
        day=inputs/'day-observation-policy.json';atomic_json(day,policy_document())
        mix=contract.require_scale(selected['total_non_public_vehicles'],selected['demand_seed'],selected['iterations'],
                                   selected['specification_path'],selected['scenario'])
        native=copy.deepcopy(selected)
        native.update(initial_population_sha256=sha256(plans),
            population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization')
        manifest=dict(status='prepared',experiment=native,demand_seed=20261023,matsim_seed=20261023,
            iterations=dict(first=0,last=0,requested=1,completed=[]),
            balanced_od=dict(variant=audit.VARIANT,implementation=artifact(directory,implementation)),
            spatial_demand=dict(mode=audit.VARIANT),
            demand_composition=dict(total_non_public_vehicles=selected['total_non_public_vehicles'],
                                    family_counts={k:mix[k] for k in ('carro','moto','pesado')}),
            counts=dict(public_transport_vehicles_configured=269),
            temporal_demand=dict(demand_window=dict(start_seconds=0,end_seconds=86400,end_exclusive=True),
                                 observation_policy='fixed-day-24h-v1'),
            inputs={'config':artifact(directory,config),'plans':artifact(directory,plans),
                    'input:experiment-specification.json':artifact(directory,inputs/'experiment-specification.json'),
                    'input:day-observation-policy.json':artifact(directory,day)})
        with patch.object(audit,'check_config',side_effect=NativeBoundaryReached):
            audit.validate_manifest(directory,manifest)
        self.fail('Expected explicit native-audit boundary')

    def test_exact_bytes_lf_crlf_bom_and_unicode_reach_real_auditor_boundary(self):
        import generate_montecarlo_z1 as generator
        original=(contract.PROJECT/contract.DIAGNOSTIC_SPEC).read_bytes()
        # Escaped Unicode is legal JSON whitespace-free spelling of an existing
        # key; no contract value or authorized scenario changes.
        variants=[original,original.replace(b'\n',b'\r\n'),b'\xef\xbb\xbf'+original,
                  original.replace(b'"schema"',b'"\\u0073chema"')]
        for index,raw in enumerate(variants):
            with self.subTest(index=index),tempfile.TemporaryDirectory(prefix='simz1-pin-boundary-') as temp:
                directory=Path(temp);source=directory/'source.json';source.write_bytes(raw)
                selected=contract.experiment(source,'run10000')
                pinned=directory/'inputs'/'experiment-specification.json'
                generator.pin_experiment_specification(source,pinned,selected)
                with self.assertRaises(NativeBoundaryReached):self.audit_boundary(directory,selected)
                self.assertEqual(pinned.read_bytes(),raw)
                self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),selected['specification_sha256'])

    def test_source_change_rejected_before_publication(self):
        import generate_montecarlo_z1 as generator
        with tempfile.TemporaryDirectory(prefix='simz1-pin-change-') as temp:
            directory=Path(temp);source=directory/'source.json'
            source.write_bytes((contract.PROJECT/contract.DIAGNOSTIC_SPEC).read_bytes())
            selected=contract.experiment(source,'run10000');source.write_bytes(source.read_bytes()+b' ')
            pinned=directory/'inputs'/'experiment-specification.json'
            with self.assertRaisesRegex(ValueError,'specification.*changed'):
                generator.pin_experiment_specification(source,pinned,selected)
            self.assertFalse(pinned.exists())

    def test_pinned_copy_tamper_still_rejected_by_actual_auditor(self):
        import generate_montecarlo_z1 as generator
        for mutation in ('whitespace','N','seed','iterations'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory(prefix='simz1-pin-tamper-') as temp:
                directory=Path(temp);source=contract.PROJECT/contract.DIAGNOSTIC_SPEC
                selected=contract.experiment(source,'run10000')
                pinned=directory/'inputs'/'experiment-specification.json'
                generator.pin_experiment_specification(source,pinned,selected)
                if mutation=='whitespace':pinned.write_bytes(pinned.read_bytes()+b' ')
                else:
                    doc=json.loads(pinned.read_bytes())
                    if mutation=='N':doc['scenarios']['run10000']['total_non_public_vehicles']=10001
                    elif mutation=='seed':doc['demand_seed']=7
                    else:doc['scenarios']['run10000']['iterations']=10
                    pinned.write_bytes(contract._json_bytes(doc))
                # artifact() sees the changed copy, so this also proves that
                # recomputing its self-declared hash cannot replace source identity.
                with self.assertRaises(ValueError):self.audit_boundary(directory,selected)

    def test_atomic_publication_failure_preserves_existing_copy(self):
        import generate_montecarlo_z1 as generator
        with tempfile.TemporaryDirectory(prefix='simz1-pin-atomic-') as temp:
            directory=Path(temp);source=contract.PROJECT/contract.DIAGNOSTIC_SPEC
            selected=contract.experiment(source,'run10000');pinned=directory/'experiment.json'
            pinned.write_bytes(b'prior-diagnostic-copy')
            with patch('os.replace',side_effect=OSError('fixture publication failure')),self.assertRaises(OSError):
                generator.pin_experiment_specification(source,pinned,selected)
            self.assertEqual(pinned.read_bytes(),b'prior-diagnostic-copy')
            self.assertEqual(list(directory.iterdir()),[pinned])

    def test_historical_v3_binary_copy_preserves_identity(self):
        import generate_montecarlo_z1 as generator
        source=contract.PROJECT/contract.TRIAL_SPEC
        selected=contract.experiment(source,'run1000')
        with tempfile.TemporaryDirectory(prefix='simz1-pin-v3-') as temp:
            directory=Path(temp);pinned=directory/'inputs'/'experiment-specification.json'
            generator.pin_experiment_specification(source,pinned,selected)
            self.assertEqual(pinned.read_bytes(),source.read_bytes())
            with self.assertRaises(NativeBoundaryReached):self.audit_boundary(directory,selected)

    def test_isolated_v4_selection_copy_reaches_real_auditor_without_consuming_claim(self):
        import generate_montecarlo_z1 as generator
        with tempfile.TemporaryDirectory(prefix='simz1-pin-v4-') as temp:
            directory=Path(temp);receipts=directory/'fixture-receipts'
            try:
                with patch.object(contract,'SELECTION_ROOT',receipts), \
                     patch('simz1_workflow_state.fingerprint',return_value='1'*64), \
                     patch.object(contract,'physical_source_inventory',return_value={'fixture/native.java':'2'*64}), \
                     patch.object(contract.secrets,'token_hex',return_value='a'*64), \
                     patch.object(contract.uuid,'uuid4',return_value=uuid.UUID('12345678-1234-4234-8234-123456789abc')):
                    selected=contract.create_random_selection() # Isolated deterministic fixture only.
                    source=Path(selected['specification_path'])
                    pinned=directory/'inputs'/'experiment-specification.json'
                    generator.pin_experiment_specification(source,pinned,selected)
                    self.assertEqual(pinned.read_bytes(),source.read_bytes())
                    with self.assertRaises(NativeBoundaryReached):self.audit_boundary(directory,selected)
                    self.assertFalse((source.parent/'run-claim.json').exists())
            finally:
                for path in receipts.rglob('*'):
                    if path.is_file():path.chmod(stat.S_IREAD|stat.S_IWRITE)


if __name__=='__main__':unittest.main()
