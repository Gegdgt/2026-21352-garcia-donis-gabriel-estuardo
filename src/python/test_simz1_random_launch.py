"""Isolated launch-gate fixtures. Never generate a real draw or run MATSim."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import simz1_scale_contract as contract
import simz1_workflow_state as workflow

ROOT = Path(__file__).resolve().parents[1]


class RandomDryRunGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1-random-gate-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launch_id = 'a' * 32
        self.directory = self.root/'runtime/launches'/self.launch_id
        self.directory.mkdir(parents=True)
        self.selected = dict(schema=contract.RANDOM_SCHEMA,scenario=contract.RANDOM_SCENARIO,
            specification_sha256='b'*64,specification_path='fixture-only.json',
            total_non_public_vehicles=200001,iterations=1,demand_seed=20261023,
            service_date='2026-10-23',selection_sha256='c'*64,
            base_scenario_identity='d'*64,selection=dict(seed='e'*64))
        self.request = dict(launch_id=self.launch_id,dry_run=True,experiment=self.selected,
            minimum_non_public_vehicles=200001,maximum_non_public_vehicles=200001,
            demand_seed=20261023,matsim_seed=20261023,iterations=1,first_iteration=0,last_iteration=0,
            service_date='2026-10-23',public_vehicles=269,transmetro_vehicles=176,tubus_vehicles=93,
            od_mode='balanced-gateway-v1',postprocessing_policy='automatic_replay_v1')
        self.state = dict(launch_id=self.launch_id,dry_run=True,status='dry_run_pass',phase='completed',
            outcome='PASSED',exit_code=0,run_launch_eligible=True,
            prior_trial_status='accepted_same_base_and_revision',source_fingerprint='fixture-revision',run_id=None,
            postprocessing_policy='automatic_replay_v1')
        self.write_preparation_receipt()

    def write_preparation_receipt(self):
        # Isolated gate fixture only; the real producer is covered separately.
        receipt = dict(schema='simz1-preparation-identity-v2',status='verified',
            launch_id=self.launch_id,dry_run=True,source_fingerprint='fixture-revision',
            experiment=self.selected,copied_specification_sha256=self.selected['specification_sha256'],
            postprocessing_policy=self.request['postprocessing_policy'],
            verification='generator_pin_and_rebuild_full_selection_v1')
        path=self.directory/'preparation-identity.json'
        path.write_bytes(contract._json_bytes(receipt))
        self.state['preparation_identity_sha256']=workflow.sha(path)

    def check(self, request=None, state=None, launch_id=None, postprocessing_policy=None):
        (self.directory/'request.json').write_text(json.dumps(request or self.request),encoding='utf-8')
        (self.directory/'state.json').write_text(json.dumps(state or self.state),encoding='utf-8')
        with patch.object(workflow,'PROJECT',self.root), \
             patch.object(workflow,'fingerprint',return_value='fixture-revision'), \
             patch.object(contract,'experiment',return_value=self.selected) as select:
            result = workflow.require_experiment_dry_run('fixture-only.json',self.selected['scenario'],
                                                        self.launch_id if launch_id is None else launch_id,
                                                        postprocessing_policy)
            select.assert_called_once_with('fixture-only.json',self.selected['scenario'])
            return result

    def test_postprocessing_policy_cannot_change_between_dryrun_and_run(self):
        other = ('automatic_replay_v1' if self.request['postprocessing_policy'] == 'native_diagnostic_v1'
                 else 'native_diagnostic_v1')
        with self.assertRaises(ValueError):
            self.check(postprocessing_policy=other)
        with self.assertRaises(ValueError):
            self.check(request=dict(self.request,postprocessing_policy=other))
        with self.assertRaises(ValueError):
            self.check(state=dict(self.state,postprocessing_policy=other))

    def test_explicit_native_postprocessing_is_bound(self):
        self.request['postprocessing_policy']='native_diagnostic_v1'
        self.state['postprocessing_policy']='native_diagnostic_v1'
        self.write_preparation_receipt()
        self.assertEqual(self.check(postprocessing_policy='native_diagnostic_v1'),self.launch_id)

    def test_legacy_preparation_receipt_cannot_approve_new_scope(self):
        path=self.directory/'preparation-identity.json'
        receipt=json.loads(path.read_bytes())
        receipt['schema']='simz1-preparation-identity-v1'
        receipt.pop('postprocessing_policy')
        path.write_bytes(contract._json_bytes(receipt))
        self.state['preparation_identity_sha256']=workflow.sha(path)
        with self.assertRaisesRegex(ValueError,'receipt differs'):
            self.check()

    def test_missing_preparation_proof_rejected(self):
        (self.directory/'preparation-identity.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_exact_explicit_successful_dry_run(self):
        self.assertEqual(self.check(),self.launch_id)

    def test_pending_failure_run_or_other_revision_rejected(self):
        mutations = dict(status='preflight',phase='acceptance_gates',outcome='BLOCKED',exit_code=1,
            run_launch_eligible=False,prior_trial_status='pending_not_approved',dry_run=False,
            source_fingerprint='other-revision',run_id='simz1-not-a-dry-run',launch_id='f'*32)
        for key,value in mutations.items():
            with self.subTest(field=key),self.assertRaises(ValueError):
                self.check(state=dict(self.state,**{key:value}))

    def test_request_population_seed_iteration_fleet_and_identity_rejected(self):
        mutations = dict(minimum_non_public_vehicles=200002,maximum_non_public_vehicles=200002,
            demand_seed=7,matsim_seed=7,iterations=10,first_iteration=1,last_iteration=9,
            service_date='2026-10-24',public_vehicles=270,transmetro_vehicles=175,tubus_vehicles=94,
            od_mode='network',dry_run=False,launch_id='f'*32)
        for key,value in mutations.items():
            with self.subTest(field=key),self.assertRaises(ValueError):
                self.check(request=dict(self.request,**{key:value}))

    def test_coherently_changed_selection_still_cannot_reuse_dry_run(self):
        for key,value in [('specification_sha256','f'*64),('selection_sha256','f'*64),
                          ('base_scenario_identity','f'*64),('selection',dict(seed='f'*64))]:
            request=copy.deepcopy(self.request)
            request['experiment'][key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):self.check(request=request)

    def test_explicit_launch_id_required(self):
        for value in ('','latest-successful','../elsewhere','F'*32):
            with self.subTest(value=value),self.assertRaises(ValueError):self.check(launch_id=value)

    def test_missing_receipt_rejected(self):
        with self.assertRaises(FileNotFoundError):self.check(launch_id='b'*32)

    def test_auditor_cannot_skip_random_identity_by_downgrading_manifest_schema(self):
        import simz1_balanced_od_audit as audit
        import simz1_run
        dummy=self.root/'fixture.json'
        dummy.write_text('{}',encoding='utf-8')
        manifest=dict(balanced_od=dict(variant='balanced-gateway-v1',implementation={}),
            spatial_demand=dict(mode='balanced-gateway-v1'),
            inputs={'config':{},'input:experiment-specification.json':{}},
            experiment=dict(self.selected,schema='simz1-final-experiments-v3'))
        with patch.object(simz1_run,'checked_path',return_value=dummy), \
             patch.object(simz1_run,'parameters',return_value={}), \
             patch.object(audit,'validate_implementation_signature'), \
             patch.object(contract,'experiment',return_value=self.selected), \
             self.assertRaisesRegex(ValueError,'selection identity'):
            audit.validate_manifest(self.root,manifest)


class RandomPowerShellGateTests(unittest.TestCase):
    def test_first_scale_trial_cannot_bypass_random_contract(self):
        script = ". './scripts/simz1_launch_contract.ps1'; try { Test-SimZ1FirstScaleTrial @{FirstScaleTrial=$true; ExperimentSchema='simz1-final-experiments-v4'}; exit 9 } catch { if ($_.Exception.Message -notlike 'FirstScaleTrial is unavailable*') { throw }; exit 0 }"
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],cwd=ROOT,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
