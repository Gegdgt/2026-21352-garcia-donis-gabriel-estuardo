"""Random experiment contract: isolated receipts only, no native run or real draw."""
import copy
import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import uuid

import simz1_scale_contract as contract


class RandomExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='simz1-random-fixture-')
        self.root = Path(self.temporary.name)
        self.addCleanup(self.cleanup)
        for mocked in (
                patch.object(contract,'SELECTION_ROOT',self.root),
                patch('simz1_workflow_state.fingerprint',return_value='1'*64),
                patch.object(contract,'physical_source_inventory',return_value={'fixture/native.java':'2'*64}),
                patch.object(contract.secrets,'token_hex',return_value='a'*64),
                patch.object(contract.uuid,'uuid4',return_value=uuid.UUID('12345678-1234-4234-8234-123456789abc'))):
            mocked.start()
            self.addCleanup(mocked.stop)

    def cleanup(self):
        for path in self.root.rglob('*'):
            if path.is_file():path.chmod(stat.S_IREAD|stat.S_IWRITE)
        self.temporary.cleanup()

    def create(self):
        self.selected = contract.create_random_selection()
        self.path = Path(self.selected['specification_path'])
        self.doc = json.loads(self.path.read_bytes())
        return self.selected

    def overwrite(self,path,value):
        path.chmod(stat.S_IREAD|stat.S_IWRITE)
        path.write_bytes(contract._json_bytes(value))

    def request(self,selected):
        return dict(experiment=copy.deepcopy(selected),
            minimum_non_public_vehicles=selected['total_non_public_vehicles'],
            maximum_non_public_vehicles=selected['total_non_public_vehicles'],
            demand_seed=20261023,matsim_seed=20261023,iterations=1,first_iteration=0,last_iteration=0,
            service_date='2026-10-23',public_vehicles=269,transmetro_vehicles=176,tubus_vehicles=93,
            od_mode='balanced-gateway-v1')

    def manifest(self,selected):
        mix=selected['selection']['composition']
        contract.claim_selection(selected,'a'*32)
        generated=copy.deepcopy(selected)
        generated.update(initial_population_sha256='d'*64,
            population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization')
        return dict(status='running',experiment=generated,launch_id='a'*32,demand_seed=20261023,matsim_seed=20261023,
            inputs=dict(plans=dict(path='plans.xml',sha256='d'*64)),
            iterations=dict(first=0,last=0,requested=1,completed=[]),
            demand_composition=dict(total_non_public_vehicles=selected['total_non_public_vehicles'],
                                    family_counts={k:mix[k] for k in ('carro','moto','pesado')}),
            counts=dict(public_transport_vehicles_configured=269),spatial_demand=dict(mode='balanced-gateway-v1'))

    def test_policy_preserves_historical_draw_and_exact_base(self):
        old_raw=(contract.PROJECT/contract.TRIAL_SPEC).read_bytes()
        policy=json.loads((contract.PROJECT/contract.RANDOM_POLICY).read_bytes())
        self.assertEqual(policy,contract.random_policy_specification())
        selected=self.create()
        trial=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,'run1000')
        self.assertEqual(selected['base_scenario_identity'],trial['base_scenario_identity'])
        for key in ('base_inputs','demand_seed','service_date','public_vehicles','observation_policy',
                    'native_qsim_end_seconds','observation_end_seconds','signal_variant'):
            self.assertEqual(selected[key],trial[key],key)
        self.assertEqual((contract.PROJECT/contract.TRIAL_SPEC).read_bytes(),old_raw)
        self.assertEqual(json.loads(old_raw)['scenarios']['full-1']['total_non_public_vehicles'],204186)
        with self.assertRaises(ValueError):contract.experiment(contract.PROJECT/contract.RANDOM_POLICY,contract.RANDOM_SCENARIO)

    def test_entropy_is_requested_once_and_readers_never_redraw(self):
        with patch.object(contract.secrets,'token_hex',return_value='b'*64) as entropy:
            selected=self.create()
            self.assertEqual(entropy.call_args.args,(32,))
            for _ in range(2):
                current=contract.experiment(self.path,contract.RANDOM_SCENARIO)
                self.assertEqual(current,selected)
            self.assertEqual(entropy.call_count,1)
        receipt=selected['selection']
        n,draw=contract.draw_total(receipt['seed'])
        self.assertEqual(n,selected['total_non_public_vehicles'])
        self.assertEqual(draw['counter'],receipt['rejection_attempts'])
        self.assertEqual(sum(receipt['composition'][k] for k in ('carro','moto','pesado')),n)
        self.assertEqual(receipt['composition']['public_transport'],269)
        self.assertEqual(receipt['demand_seed'],20261023)

    def test_rejection_sampler_retains_uniform_inclusive_endpoints(self):
        class Digest:
            def __init__(self,value):self.value=value
            def hexdigest(self):return f'{self.value:064x}'
        for value,total in [(0,180000),(40000,220000)]:
            with patch.object(contract.hashlib,'sha256',return_value=Digest(value)):
                self.assertEqual(contract.draw_total('fixture')[0],total)
        with patch.object(contract.hashlib,'sha256',side_effect=[Digest(2**256-1),Digest(1)]):
            n,draw=contract.draw_total('fixture')
            self.assertEqual((n,draw['counter']),(180001,1))

    def test_second_draw_is_rejected_before_requesting_new_entropy(self):
        with patch.object(contract.secrets,'token_hex',side_effect=['a'*64,'b'*64]) as entropy, \
             patch.object(contract.uuid,'uuid4',side_effect=[uuid.UUID('12345678-1234-4234-8234-123456789abc'),uuid.UUID('22345678-1234-4234-8234-123456789abc')]):
            first=self.create()
            with self.assertRaises(FileExistsError):contract.create_random_selection()
        self.assertEqual(entropy.call_count,1)
        self.assertEqual(contract.experiment(self.path,contract.RANDOM_SCENARIO),first)

    def test_interrupted_draw_cannot_silently_generate_a_second_seed(self):
        with patch.object(contract.secrets,'token_hex',side_effect=RuntimeError('fixture interruption')) as entropy:
            with self.assertRaisesRegex(RuntimeError,'fixture interruption'):contract.create_random_selection()
            with self.assertRaises(FileExistsError):contract.create_random_selection()
        self.assertEqual(entropy.call_count,1)

    def test_draw_intent_missing_tampered_or_different_revision_is_rejected(self):
        self.create()
        intent=contract._draw_intent_path(); raw=intent.read_bytes()
        intent.chmod(stat.S_IREAD|stat.S_IWRITE);intent.unlink()
        with self.assertRaises(FileNotFoundError):contract.experiment(self.path,contract.RANDOM_SCENARIO)
        value=json.loads(raw);value['selection_id']='f'*32
        intent.write_bytes(contract._json_bytes(value))
        with self.assertRaisesRegex(ValueError,'exclusive policy draw intent'):
            contract.experiment(self.path,contract.RANDOM_SCENARIO)
        intent.write_bytes(raw)
        with patch('simz1_workflow_state.fingerprint',return_value='9'*64), \
             patch.object(contract.secrets,'token_hex') as entropy:
            with self.assertRaises(FileExistsError):contract.create_random_selection()
            entropy.assert_not_called()

    def test_collision_cannot_overwrite_an_existing_selection(self):
        first=self.create();before=self.path.read_bytes()
        with self.assertRaises(FileExistsError):contract.create_random_selection()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(contract.experiment(self.path,contract.RANDOM_SCENARIO),first)

    def test_single_field_mutations_are_rejected(self):
        self.create()
        mutators={
            'N':lambda d:d['scenarios'][contract.RANDOM_SCENARIO].update(total_non_public_vehicles=180000),
            'seed':lambda d:d['selection'].update(seed='b'*64),
            'demand_seed':lambda d:d.update(demand_seed=7),
            'receipt_demand_seed':lambda d:d['selection'].update(demand_seed=7),
            'range':lambda d:d['selection'].update(inclusive_range=[179999,220000]),
            'iterations':lambda d:d['scenarios'][contract.RANDOM_SCENARIO].update(iterations=10),
            'receipt_iterations':lambda d:d['selection'].update(iterations=10),
            'policy':lambda d:d['random_policy'].update(sha256='0'*64),
            'sources':lambda d:d['selection'].update(source_fingerprint='0'*64),
            'physical_sources':lambda d:d['selection']['physical_sources'].update({'fixture/native.java':'3'*64}),
            'selection_sha':lambda d:d.update(selection_sha256='0'*64),
            'algorithm':lambda d:d['selection'].update(algorithm='random-modulo'),
            'extra':lambda d:d.update(allow_mutation=True),
            'draw_id':lambda d:d['selection'].update(selection_id='a'*32),
            'rejections':lambda d:d['selection'].update(rejection_attempts=4),
        }
        mutation=self.root/'mutation.json'
        for name,mutate in mutators.items():
            doc=copy.deepcopy(self.doc);mutate(doc);mutation.write_bytes(contract._json_bytes(doc))
            with self.subTest(name=name),self.assertRaises(ValueError):contract.experiment(mutation,contract.RANDOM_SCENARIO)

    def test_missing_external_receipt_and_checksum_rejected(self):
        self.create()
        for name in ('selection.json','selection.sha256','experiment.json'):
            path=self.path.parent/name; raw=path.read_bytes();path.chmod(stat.S_IREAD|stat.S_IWRITE);path.unlink()
            pinned=self.root/'pinned.json';pinned.write_bytes(contract._json_bytes(self.doc))
            with self.subTest(name=name),self.assertRaises(FileNotFoundError):contract.experiment(pinned,contract.RANDOM_SCENARIO)
            path.write_bytes(raw)

    def test_tampered_external_receipt_and_checksum_rejected(self):
        self.create();folder=self.path.parent
        for name in ('selection.json','selection.sha256'):
            path=folder/name;raw=path.read_bytes();path.chmod(stat.S_IREAD|stat.S_IWRITE);path.write_bytes(raw+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):contract.experiment(self.path,contract.RANDOM_SCENARIO)
            path.write_bytes(raw)

    def test_physical_and_complete_revision_changes_rejected(self):
        self.create()
        with patch('simz1_workflow_state.fingerprint',return_value='9'*64),self.assertRaisesRegex(ValueError,'Sources changed'):
            contract.experiment(self.path,contract.RANDOM_SCENARIO)
        with patch.object(contract,'physical_source_inventory',return_value={'fixture/native.java':'9'*64}),self.assertRaisesRegex(ValueError,'Physical sources changed'):
            contract.experiment(self.path,contract.RANDOM_SCENARIO)

    def test_pin_copy_allowed_but_request_full_identity_required(self):
        selected=self.create();pinned=self.root/'pinned.json';pinned.write_bytes(self.path.read_bytes())
        rebuilt=contract.experiment(pinned,contract.RANDOM_SCENARIO)
        contract.verify_selection_identity(selected,rebuilt)
        contract.verify_launch_request(self.request(selected),rebuilt)
        for field,value in [('minimum_non_public_vehicles',1),('maximum_non_public_vehicles',1),('iterations',10),
                            ('demand_seed',1),('matsim_seed',1),('last_iteration',9),('public_vehicles',270),
                            ('service_date','2026-10-24'),('od_mode','network')]:
            request=self.request(selected);request[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):contract.verify_launch_request(request,rebuilt)
        for field in ('draw','selection','selection_sha256','specification_sha256','base_scenario_identity'):
            request=self.request(selected);request['experiment'].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):contract.verify_launch_request(request,rebuilt)

    def test_manifest_identity_iterations_N_seed_and_fleet_are_bound(self):
        selected=self.create();manifest=self.manifest(selected)
        contract.validate_manifest_selection(manifest,selected)
        mutators=[lambda m:m['iterations'].update(last=9,requested=10),
                  lambda m:m['iterations'].update(completed=[0,1]),
                  lambda m:m['demand_composition'].update(total_non_public_vehicles=180000),
                  lambda m:m.update(demand_seed=0),lambda m:m.update(matsim_seed=0),
                  lambda m:m['spatial_demand'].update(mode='network'),
                  lambda m:m['experiment'].update(selection_sha256='0'*64),
                  lambda m:m['experiment']['selection'].update(seed='b'*64),
                  lambda m:m['demand_composition']['family_counts'].update(carro=1),
                  lambda m:m['counts'].update(public_transport_vehicles_configured=268),
                  lambda m:m.update(launch_id='b'*32),lambda m:m.pop('launch_id'),
                  lambda m:m['experiment'].update(initial_population_sha256='e'*64),
                  lambda m:m['experiment'].update(population_identity_basis='invented'),
                  lambda m:m['experiment'].pop('initial_population_sha256'),
                  lambda m:m['inputs']['plans'].update(sha256='e'*64),
                  lambda m:m['inputs']['plans'].update(path='other-plans.xml')]
        for i,mutate in enumerate(mutators):
            changed=copy.deepcopy(manifest);mutate(changed)
            with self.subTest(case=i),self.assertRaises(ValueError):contract.validate_manifest_selection(changed,selected)

    def test_one_run_claim_only_and_no_receipt_modification(self):
        selected=self.create();raw=self.path.read_bytes()
        claim=contract.claim_selection(selected,'a'*32)
        self.assertEqual(contract.validate_run_claim(selected,'a'*32),claim)
        self.assertEqual(claim['selection_sha256'],selected['selection_sha256'])
        for launch_id in ('a'*32,'b'*32):
            with self.assertRaises(FileExistsError):contract.claim_selection(selected,launch_id)
        self.assertEqual(self.path.read_bytes(),raw)
        with self.assertRaises(ValueError):contract.claim_selection(selected,'invalid')

    def test_native_and_monitor_reject_missing_or_tampered_run_claim(self):
        selected=self.create();request=dict(self.request(selected),dry_run=False,launch_id='a'*32)
        # The monitor may observe preflight before the claim exists. A native
        # manifest, once available, is additionally checked by the same CLI.
        contract.verify_launch_request(request,selected)
        with self.assertRaises(FileNotFoundError):contract.validate_run_claim(selected,'a'*32)
        manifest=self.manifest(selected)
        contract.verify_launch_request(request,selected)
        path=self.path.parent/'run-claim.json';claim=json.loads(path.read_bytes())
        for field,value in [('launch_id','b'*32),('selection_sha256','b'*64),
                            ('source_fingerprint','c'*64),('created_utc','not-a-time')]:
            self.overwrite(path,dict(claim,**{field:value}))
            with self.subTest(field=field),self.assertRaises(ValueError):
                contract.validate_run_claim(selected,'a'*32)
            with self.subTest(manifest_field=field),self.assertRaises(ValueError):
                contract.validate_manifest_selection(manifest,selected)
        self.overwrite(path,claim)
        contract.validate_manifest_selection(manifest,selected)
        prepared=dict(manifest,status='prepared');prepared.pop('launch_id')
        path.chmod(stat.S_IREAD|stat.S_IWRITE);path.unlink()
        contract.validate_manifest_selection(prepared,selected)
        for status in ('running','completed','failed'):
            with self.subTest(status=status),self.assertRaises(ValueError):
                contract.validate_manifest_selection(dict(prepared,status=status),selected)

    def test_v3_trial_can_only_approve_same_v4_base_and_current_revision(self):
        import simz1_workflow_state as workflow
        selected=self.create()
        trial=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,'run1000')
        self.assertEqual(trial['base_scenario_identity'],selected['base_scenario_identity'])
        current=dict(run_id='fixture-only',manifest_sha256='fixture-manifest',quality_sha256='fixture-quality',
                     base_scenario_identity=trial['base_scenario_identity'])
        state=self.root/'trial.json'
        state.write_text(json.dumps(dict(current,run_directory=str(self.root),source_fingerprint='1'*64)))
        argv=['require-trial','--state',str(state),'--experiment-spec',str(self.path),
              '--experiment-scenario',contract.RANDOM_SCENARIO]
        for base,revision,code in [(trial['base_scenario_identity'],'1'*64,0),
                                   ('other-base','1'*64,1),(None,'1'*64,1),
                                   (trial['base_scenario_identity'],'9'*64,1)]:
            with self.subTest(base=base,revision=revision), \
                 patch.object(workflow,'inspect',return_value=dict(current,base_scenario_identity=base)), \
                 patch.object(workflow,'fingerprint',return_value=revision), \
                 contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(workflow.main(argv),code)


if __name__=='__main__':unittest.main()
