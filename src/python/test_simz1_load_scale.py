"""Read-only preparation contracts for existing fixed load selectors."""
import copy
import contextlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

import generate_montecarlo_z1 as generator
import simz1_scale_contract as contract
import simz1_workflow_state as workflow
import test_simz1_random_experiment as random_tests


class FixedLoadSelectionTests(unittest.TestCase):
    def setUp(self):
        self.spec=contract.PROJECT/contract.TRIAL_SPEC
        self.selected=contract.experiment(self.spec,'half')

    def transported(self,selected=None):
        row=dict(selected or self.selected)
        row['composition']=contract.require_scale(row['total_non_public_vehicles'],row['demand_seed'],
            row['iterations'],row['specification_path'],row['scenario'])
        return row

    def request(self,selected=None):
        selected=selected or self.selected
        return dict(experiment=self.transported(selected),
            minimum_non_public_vehicles=selected['total_non_public_vehicles'],
            maximum_non_public_vehicles=selected['total_non_public_vehicles'],
            demand_seed=20261023,matsim_seed=20261023,iterations=selected['iterations'],
            first_iteration=0,last_iteration=selected['iterations']-1,
            service_date='2026-10-23',public_vehicles=269,transmetro_vehicles=176,tubus_vehicles=93,
            od_mode='balanced-gateway-v1')

    def test_half_exact_composition_and_same_native_base_as_trial(self):
        trial=contract.experiment(self.spec,'run1000')
        self.assertEqual(self.transported()['composition'],dict(carro=48400,moto=60500,pesado=1100,public_transport=269))
        self.assertEqual(self.selected['total_non_public_vehicles'],110000)
        for key in ('base_inputs','base_scenario_identity','demand_seed','service_date','public_vehicles',
                    'signal_variant','observation_policy','observation_end_seconds','native_qsim_end_seconds','iterations'):
            self.assertEqual(self.selected[key],trial[key],key)
        self.assertEqual((self.selected['observation_end_seconds'],self.selected['native_qsim_end_seconds']),
                         (86400,86399))

    def test_v3_cli_quotas_survive_real_binary_preparation_boundary(self):
        original=self.spec.read_bytes()
        request=self.request()
        contract.verify_launch_request(request,self.selected)
        with tempfile.TemporaryDirectory(prefix='simz1-half-pinning-') as temporary:
            destination=Path(temporary)/'experiment-specification.json'
            generator.pin_experiment_specification(self.spec,destination,request['experiment'])
            rebuilt=contract.experiment(destination,'half')
            contract.verify_launch_request(request,rebuilt)
            self.assertEqual(destination.read_bytes(),original)
            self.assertEqual(list(Path(temporary).iterdir()),[destination])
        self.assertEqual(self.spec.read_bytes(),original)

    def test_v3_cli_quotas_are_derived_not_trusted(self):
        for key,value in [('carro',48399),('moto',60501),('pesado',12),('public_transport',268),
                          ('carro',48400.0),('unknown',0)]:
            changed=self.transported();changed['composition'][key]=value
            with self.subTest(field=key,value=value),self.assertRaisesRegex(ValueError,'composition differs'):
                contract.verify_selection_identity(changed,self.selected)
        changed=self.transported();del changed['composition']['pesado']
        with self.assertRaisesRegex(ValueError,'composition differs'):
            contract.verify_selection_identity(changed,self.selected)

    def test_changed_half_identity_counts_seed_and_hash_rejected(self):
        for key,value in [('schema',contract.DIAGNOSTIC_SCHEMA),('scenario','max-test'),
                          ('total_non_public_vehicles',110001),('demand_seed',7),
                          ('specification_sha256','0'*64),('base_scenario_identity','0'*64),
                          ('source_fingerprint','0'*64)]:
            changed=self.transported();changed[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):
                contract.verify_selection_identity(changed,self.selected)
        for key,value in [('minimum_non_public_vehicles',10000),('maximum_non_public_vehicles',220000),
                          ('demand_seed',7),('matsim_seed',7),('first_iteration',1),('last_iteration',9),
                          ('iterations',10),('od_mode','network')]:
            request=self.request();request[key]=value
            with self.subTest(request_field=key),self.assertRaises(ValueError):
                contract.verify_launch_request(request,self.selected)

    def test_historical_trial_and_full_ten_iteration_transport_stay_supported(self):
        for selector,count in [('run1000',1),('full-10',10)]:
            selected=contract.experiment(self.spec,selector)
            request=self.request(selected)
            self.assertEqual(request['last_iteration'],count-1)
            contract.verify_launch_request(request,selected)
            for wrong in (-1,count):
                with self.subTest(selector=selector,last=wrong),self.assertRaises(ValueError):
                    contract.verify_launch_request(dict(request,last_iteration=wrong),selected)

    def test_v3_numeric_aliases_cannot_replace_exact_identity_or_request(self):
        for key,value in [('total_non_public_vehicles',110000.0),('iterations',True),('demand_seed',20261023.0)]:
            selected=self.transported();selected[key]=value
            with self.subTest(selection_field=key),self.assertRaisesRegex(ValueError,'selection identity differs'):
                contract.verify_selection_identity(selected,self.selected)
        for key,value in [('minimum_non_public_vehicles',110000.0),('maximum_non_public_vehicles',110000.0),
                          ('demand_seed',20261023.0),('matsim_seed',20261023.0),('iterations',True),
                          ('first_iteration',False),('last_iteration',False),('public_vehicles',269.0),
                          ('transmetro_vehicles',176.0),('tubus_vehicles',93.0)]:
            with self.subTest(request_field=key),self.assertRaisesRegex(ValueError,'must be integers'):
                contract.verify_launch_request(dict(self.request(),**{key:value}),self.selected)

    def test_existing_max_test_is_220k_and_no_fixed_180k_selector_is_invented(self):
        selected=contract.experiment(self.spec,'max-test')
        self.assertEqual(selected['total_non_public_vehicles'],220000)
        self.assertEqual(self.transported(selected)['composition'],dict(carro=96800,moto=121000,pesado=2200,public_transport=269))
        for selector in ('run180000','180000','run110000'):
            with self.subTest(selector=selector),self.assertRaises(ValueError):
                contract.experiment(self.spec,selector)

    def test_legacy_v1_v2_selection_comparison_is_not_reinterpreted(self):
        for filename in ('final-20261102-v1.json','final-20261103-24h-v2.json'):
            path=contract.PROJECT/'scenarios/zona1/experiments'/filename
            original=path.read_bytes();selected=contract.experiment(path,'half')
            numeric_alias=dict(selected,total_non_public_vehicles=float(selected['total_non_public_vehicles']))
            contract.verify_selection_identity(numeric_alias,selected)
            self.assertEqual(path.read_bytes(),original)


class LaunchPostprocessingPolicyTests(unittest.TestCase):
    def test_v3_load_selectors_keep_default_and_native_requires_explicit_opt_in(self):
        path=contract.PROJECT/contract.TRIAL_SPEC;raw=path.read_bytes()
        for selector in ('half','max-test'):
            selected=contract.experiment(path,selector)
            self.assertNotIn('postprocessing',selected)
            self.assertEqual(contract.launch_postprocessing_policy(selected),'automatic_replay_v1')
            self.assertEqual(contract.launch_postprocessing_policy(selected,'automatic_replay_v1'),'automatic_replay_v1')
            self.assertEqual(contract.launch_postprocessing_policy(selected,'native_diagnostic_v1'),'native_diagnostic_v1')
        self.assertEqual(path.read_bytes(),raw)

    def test_v5_retains_intrinsic_native_policy_and_cannot_request_automatic_replay(self):
        selected=contract.experiment(contract.PROJECT/contract.DIAGNOSTIC_SPEC,'run10000')
        for requested in (None,'native_diagnostic_v1'):
            self.assertEqual(contract.launch_postprocessing_policy(selected,requested),'native_diagnostic_v1')
        with self.assertRaises(ValueError):contract.launch_postprocessing_policy(selected,'automatic_replay_v1')
        changed=copy.deepcopy(selected);changed['postprocessing']['policy']='automatic_replay_v1'
        with self.assertRaises(ValueError):contract.launch_postprocessing_policy(changed)

    def test_v4_scope_is_explicit_and_invalid_modes_or_selectors_rejected(self):
        # Policy resolution assumes experiment() already validated the selection;
        # full immutable candidate coverage is in test_simz1_random_experiment.
        selected=dict(schema=contract.RANDOM_SCHEMA,scenario=contract.RANDOM_SCENARIO)
        self.assertEqual(contract.launch_postprocessing_policy(selected),'automatic_replay_v1')
        self.assertEqual(contract.launch_postprocessing_policy(selected,'native_diagnostic_v1'),'native_diagnostic_v1')
        for mode in ('','native',False,'automatic_replay_v2'):
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                contract.launch_postprocessing_policy(selected,mode)
        with self.assertRaises(ValueError):
            contract.launch_postprocessing_policy(dict(selected,scenario='other'),'native_diagnostic_v1')

    def test_native_opt_in_does_not_extend_to_other_legacy_selectors(self):
        for selector in ('run1000','buses','quarter','full-1','full-10'):
            selected=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,selector)
            self.assertEqual(contract.launch_postprocessing_policy(selected),'automatic_replay_v1')
            with self.subTest(selector=selector),self.assertRaises(ValueError):
                contract.launch_postprocessing_policy(selected,'native_diagnostic_v1')
        with self.assertRaises(ValueError):
            contract.launch_postprocessing_policy(dict(schema='unrecognized',scenario='half'))


class CandidateSelectionTests(unittest.TestCase):
    FIRST='aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa'
    SECOND='bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb'

    def setUp(self):
        # Reuse the existing wholly isolated receipt tree and source/entropy
        # mocks. No candidate under runtime/experiment-selections is touched.
        fixture=random_tests.RandomExperimentTests('test_entropy_is_requested_once_and_readers_never_redraw')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.root=fixture.root

    def create(self,candidate_id=FIRST):
        self.selected=contract.create_random_selection(candidate_id)
        self.path=Path(self.selected['specification_path'])
        self.doc=json.loads(self.path.read_bytes())
        return self.selected

    def test_v2_candidate_intent_and_readers_do_not_redraw(self):
        with patch.object(contract.secrets,'token_hex',return_value='b'*64) as entropy:
            selected=self.create();receipt=selected['selection']
            self.assertEqual(receipt['schema'],'simz1-random-selection-v2')
            self.assertEqual(receipt['candidate_id'],self.FIRST)
            intent=contract._draw_intent_path(self.FIRST)
            self.assertEqual(intent,self.root/'candidates'/(self.FIRST+'.draw-intent.json'))
            self.assertEqual(json.loads(intent.read_bytes())['schema'],'simz1-random-draw-intent-v2')
            self.assertFalse(contract._draw_intent_path().exists())
            for _ in range(2):self.assertEqual(contract.experiment(self.path,contract.RANDOM_SCENARIO),selected)
            self.assertEqual(entropy.call_count,1)
        self.assertEqual(contract.launch_postprocessing_policy(selected),'automatic_replay_v1')
        self.assertEqual(contract.launch_postprocessing_policy(selected,'native_diagnostic_v1'),'native_diagnostic_v1')

    def test_candidate_v2_real_preparation_dryrun_binding_and_single_claim(self):
        selected=self.create();policy='native_diagnostic_v1';launch_id='d'*32;run_id='e'*32
        originals={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        request=dict(self.fixture.request(selected),launch_id=launch_id,dry_run=True,postprocessing_policy=policy)
        with patch.object(generator,'pin_experiment_specification',wraps=generator.pin_experiment_specification) as pin:
            receipt=workflow.verify_preparation_identity(self.path,contract.RANDOM_SCENARIO,request,'1'*64,policy)
            self.assertEqual(pin.call_count,1,'exercise the actual generator binary-copy/rebuild boundary')
            self.assertFalse(Path(pin.call_args.args[1]).exists(),'temporary specification is removed after verification')
            self.assertEqual(receipt['schema'],'simz1-preparation-identity-v2')
            self.assertEqual(receipt['experiment']['selection']['schema'],'simz1-random-selection-v2')
            self.assertEqual(receipt['experiment']['selection']['candidate_id'],self.FIRST)
            self.assertEqual(receipt['copied_specification_sha256'],contract._sha_bytes(self.path.read_bytes()))
            for field,value in [('candidate_id',self.SECOND),('selection_id','f'*32)]:
                changed=copy.deepcopy(request);changed['experiment']['selection'][field]=value
                with self.subTest(preparation_field=field),self.assertRaises(ValueError):
                    workflow.verify_preparation_identity(self.path,contract.RANDOM_SCENARIO,changed,'1'*64,policy)
            self.assertEqual(pin.call_count,1,'changed transported identities stop before the copy')

        fixture_project=self.root/'workflow-fixture';directory=fixture_project/'runtime/launches'/launch_id
        directory.mkdir(parents=True)
        state=dict(launch_id=launch_id,dry_run=True,status='dry_run_pass',phase='completed',outcome='PASSED',
            exit_code=0,run_launch_eligible=True,prior_trial_status='accepted_same_base_and_revision',
            source_fingerprint='1'*64,run_id=None,postprocessing_policy=policy)

        def gate(request_value=None,receipt_value=None,state_value=None,explicit_id=launch_id):
            # These are isolated fixture files, never production launch receipts.
            active_request=copy.deepcopy(request if request_value is None else request_value)
            active_receipt=copy.deepcopy(receipt if receipt_value is None else receipt_value)
            active_state=copy.deepcopy(state if state_value is None else state_value)
            receipt_path=directory/'preparation-identity.json'
            receipt_path.write_bytes(contract._json_bytes(active_receipt))
            active_state['preparation_identity_sha256']=workflow.sha(receipt_path)
            (directory/'request.json').write_bytes(contract._json_bytes(active_request))
            (directory/'state.json').write_bytes(contract._json_bytes(active_state))
            with patch.object(workflow,'PROJECT',fixture_project):
                return workflow.require_experiment_dry_run(self.path,contract.RANDOM_SCENARIO,explicit_id,policy)

        self.assertEqual(gate(),launch_id)
        claim_path=self.path.parent/'run-claim.json'
        self.assertFalse(claim_path.exists(),'DryRun preparation and gate do not consume the candidate')
        for field,value in [('candidate_id',self.SECOND),('selection_id','f'*32)]:
            changed=copy.deepcopy(request);changed['experiment']['selection'][field]=value
            with self.subTest(request_field=field),self.assertRaises(ValueError):gate(request_value=changed)
            changed_receipt=copy.deepcopy(receipt);changed_receipt['experiment']['selection'][field]=value
            with self.subTest(receipt_field=field),self.assertRaises(ValueError):gate(receipt_value=changed_receipt)
        for field,value in [('selection_sha256','f'*64),('specification_sha256','f'*64)]:
            changed=copy.deepcopy(request);changed['experiment'][field]=value
            with self.subTest(selection_field=field),self.assertRaises(ValueError):gate(request_value=changed)
        for field,value in [('launch_id','a'*32),('dry_run',False),('source_fingerprint','f'*64)]:
            changed_receipt=dict(receipt,**{field:value})
            with self.subTest(dryrun_receipt_field=field),self.assertRaises(ValueError):gate(receipt_value=changed_receipt)
        for field,value in [('launch_id','a'*32),('dry_run',False)]:
            with self.subTest(dryrun_request_field=field),self.assertRaises(ValueError):
                gate(request_value=dict(request,**{field:value}))
        with self.assertRaises(FileNotFoundError):gate(explicit_id='b'*32)
        with self.assertRaises(ValueError):gate(state_value=dict(state,source_fingerprint='f'*64))
        self.assertFalse(claim_path.exists(),'every rejected gate leaves the fixture candidate unconsumed')

        for field,value in [('candidate_id',self.SECOND),('selection_id','f'*32)]:
            changed=copy.deepcopy(selected);changed['selection'][field]=value
            with self.subTest(claim_selection_field=field),self.assertRaises(ValueError):
                contract.claim_selection(changed,run_id)
        self.assertFalse(claim_path.exists())
        self.assertEqual(gate(),launch_id)
        claim=contract.claim_selection(selected,run_id)
        self.assertEqual(contract.validate_run_claim(selected,run_id),claim)
        self.assertEqual(claim['selection_sha256'],selected['selection_sha256'])
        saved_claim=claim_path.read_bytes()
        for another_run in (run_id,'f'*32):
            with self.subTest(second_claim=another_run),self.assertRaises(FileExistsError):
                contract.claim_selection(selected,another_run)
        with self.assertRaises(ValueError):contract.validate_run_claim(selected,'f'*32)
        self.assertEqual(claim_path.read_bytes(),saved_claim)
        for path,raw in originals.items():self.assertEqual(path.read_bytes(),raw)

    def test_same_candidate_rejected_after_success_interruption_and_source_revision(self):
        identities=('12345678-1234-4234-8234-123456789abc','22345678-1234-4234-8234-123456789abc')
        for index,interrupt in enumerate((False,True)):
            candidate=(self.FIRST,self.SECOND)[index]
            with patch.object(contract.uuid,'uuid4',return_value=uuid.UUID(identities[index])), \
                 patch.object(contract.secrets,'token_hex',return_value='a'*64,
                     side_effect=RuntimeError('fixture interruption') if interrupt else None) as entropy:
                if interrupt:
                    with self.assertRaisesRegex(RuntimeError,'fixture interruption'):
                        contract.create_random_selection(candidate)
                else:contract.create_random_selection(candidate)
                with patch('simz1_workflow_state.fingerprint',return_value='9'*64),self.assertRaises(FileExistsError):
                    contract.create_random_selection(candidate)
                self.assertEqual(entropy.call_count,1)

    def test_independent_candidates_preserve_each_other_and_global_legacy_intent(self):
        identities=[uuid.UUID(value) for value in ('12345678-1234-4234-8234-123456789abc',
            '22345678-1234-4234-8234-123456789abc','32345678-1234-4234-8234-123456789abc')]
        with patch.object(contract.uuid,'uuid4',side_effect=identities), \
             patch.object(contract.secrets,'token_hex',side_effect=['a'*64,'b'*64,'c'*64]) as entropy:
            legacy=contract.create_random_selection();legacy_intent=contract._draw_intent_path().read_bytes()
            first=contract.create_random_selection(self.FIRST);first_intent=contract._draw_intent_path(self.FIRST).read_bytes()
            second=contract.create_random_selection(self.SECOND)
            self.assertEqual(entropy.call_count,3)
        self.assertEqual(contract._draw_intent_path().read_bytes(),legacy_intent)
        self.assertEqual(contract._draw_intent_path(self.FIRST).read_bytes(),first_intent)
        self.assertEqual(legacy['selection']['schema'],'simz1-random-selection-v1')
        self.assertNotIn('candidate_id',legacy['selection'])
        self.assertNotEqual(first['selection']['selection_id'],second['selection']['selection_id'])
        self.assertNotEqual(first['selection']['seed'],second['selection']['seed'])
        # Equal N from independent entropy is possible; it never justifies redrawing.
        for selected in (legacy,first,second):
            self.assertEqual(contract.experiment(selected['specification_path'],contract.RANDOM_SCENARIO),selected)

    def test_invalid_candidate_rejected_before_io_or_entropy(self):
        for candidate in ('',True,'latest-successful','../candidate','a'*32,
                self.FIRST.upper(),'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'):
            with self.subTest(candidate=candidate),patch.object(contract.secrets,'token_hex') as entropy, \
                 self.assertRaisesRegex(ValueError,'Candidate identity'):
                contract.create_random_selection(candidate)
            entropy.assert_not_called()
        self.assertEqual(list(self.root.iterdir()),[])

    def test_candidate_receipt_identity_schema_and_sources_cannot_be_substituted(self):
        selected=self.create()
        for key,value in [('schema','simz1-random-selection-v1'),('candidate_id',self.SECOND),
                          ('candidate_id','a'*32),('source_fingerprint','f'*64),('demand_seed',7)]:
            changed=copy.deepcopy(self.doc);changed['selection'][key]=value
            # Recomputing the public digest cannot replace original intent/receipt.
            changed['selection_sha256']=contract._sha_bytes(contract._json_bytes(changed['selection']))
            path=self.root/'mutated.json';path.write_bytes(contract._json_bytes(changed))
            error = FileNotFoundError if key=='candidate_id' and value==self.SECOND else ValueError
            with self.subTest(field=key,value=value),self.assertRaises(error):
                contract.experiment(path,contract.RANDOM_SCENARIO)
        changed=copy.deepcopy(selected['selection']);del changed['candidate_id']
        with self.assertRaises(ValueError):contract._validate_receipt(changed,selected['selection']['policy_sha256'])

    def test_v4_numeric_aliases_cannot_replace_exact_identity_or_request(self):
        selected=self.create()
        for key,value in [('total_non_public_vehicles',float(selected['total_non_public_vehicles'])),
                          ('iterations',True),('demand_seed',20261023.0)]:
            changed=dict(selected,**{key:value})
            with self.subTest(selection_field=key),self.assertRaisesRegex(ValueError,'selection identity differs'):
                contract.verify_selection_identity(changed,selected)
        request=self.fixture.request(selected)
        for key,value in [('minimum_non_public_vehicles',float(selected['total_non_public_vehicles'])),
                          ('maximum_non_public_vehicles',float(selected['total_non_public_vehicles'])),
                          ('demand_seed',20261023.0),('matsim_seed',20261023.0),('iterations',True),
                          ('first_iteration',False),('last_iteration',False),('public_vehicles',269.0),
                          ('transmetro_vehicles',176.0),('tubus_vehicles',93.0)]:
            with self.subTest(request_field=key),self.assertRaisesRegex(ValueError,'must be integers'):
                contract.verify_launch_request(dict(request,**{key:value}),selected)

    def test_candidate_intent_missing_or_substituted_is_rejected(self):
        self.create();path=contract._draw_intent_path(self.FIRST);raw=path.read_bytes()
        path.chmod(stat.S_IREAD|stat.S_IWRITE);path.unlink()
        with self.assertRaises(FileNotFoundError):contract.experiment(self.path,contract.RANDOM_SCENARIO)
        changed=json.loads(raw);changed['candidate_id']=self.SECOND
        path.write_bytes(contract._json_bytes(changed))
        with self.assertRaisesRegex(ValueError,'exclusive policy draw intent'):
            contract.experiment(self.path,contract.RANDOM_SCENARIO)
        path.write_bytes(raw)
        self.assertEqual(contract.experiment(self.path,contract.RANDOM_SCENARIO),self.selected)

    def test_full_contract_real_sampler_accepts_exact_180k_and_220k_endpoints(self):
        # Precomputed deterministic fixture entropy, never a production draw.
        cases=[('00000000000000000000000000000000000000000000000000000000000123ac',180000,
                dict(carro=79200,moto=99000,pesado=1800,public_transport=269),self.FIRST),
               ('00000000000000000000000000000000000000000000000000000000000006e4',220000,
                dict(carro=96800,moto=121000,pesado=2200,public_transport=269),self.SECOND)]
        identities=[uuid.UUID(value) for value in ('12345678-1234-4234-8234-123456789abc',
                                                   '22345678-1234-4234-8234-123456789abc')]
        with patch.object(contract.uuid,'uuid4',side_effect=identities):
            for seed,total,composition,candidate in cases:
                with self.subTest(total=total),patch.object(contract.secrets,'token_hex',return_value=seed):
                    selected=self.create(candidate)
                    self.assertEqual(selected['total_non_public_vehicles'],total)
                    self.assertEqual(selected['selection']['composition'],composition)
                    contract.verify_launch_request(self.fixture.request(selected),selected)
                    self.assertEqual(selected['iterations'],1)
                    self.assertEqual(selected['observation_end_seconds'],86400)

    def test_candidate_cli_requires_draw_and_cannot_replace_existing_selection(self):
        with patch.object(sys,'argv',['simz1_scale_contract.py','--candidate-id',self.FIRST,
                '--spec',str(contract.PROJECT/contract.TRIAL_SPEC),'--scenario','half']), \
             patch.object(contract.secrets,'token_hex') as entropy, \
             contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as stopped:
            contract.main()
        self.assertEqual(stopped.exception.code,2)
        entropy.assert_not_called()


if __name__=='__main__':unittest.main()
