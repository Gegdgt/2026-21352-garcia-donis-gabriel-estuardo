"""V8 gateway identity and negative controls; no scale simulation or real receipts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import simz1_scale_contract as scale
import simz1_workflow_state as workflow
import generate_montecarlo_z1 as generator
from simz1_configuration_contract import expected_from_selection
from test_simz1_freight_version import REQUIRED_FIXTURE_FILES


class V8ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = scale.PROJECT/scale.TRANSIT_SPEC
        cls.doc = json.loads(cls.path.read_bytes())
        cls.selected = {n: scale.experiment(cls.path, 'run'+str(n)) for n in (1000,10000,55000)}

    def request(self, n=1000):
        return dict(launch_id='1'*32, dry_run=True, experiment=self.selected[n],
            postprocessing_policy='native_diagnostic_v1', minimum_non_public_vehicles=n,
            maximum_non_public_vehicles=n, iterations=1, demand_seed=20261023, matsim_seed=20261023,
            first_iteration=0,last_iteration=0,public_vehicles=269,transmetro_vehicles=176,tubus_vehicles=93,
            service_date='2026-10-23',od_mode='balanced-gateway-v1')

    def test_exact_successor_preserves_private_demand_and_historical_v7(self):
        old = scale.freight_specification()
        self.assertEqual(json.loads((scale.PROJECT/scale.FREIGHT_SPEC).read_bytes()), old)
        self.assertEqual(self.doc, scale.transit_specification())
        self.assertEqual(self.doc['derived_from'], dict(path=scale.FREIGHT_SPEC,
            sha256=hashlib.sha256((scale.PROJECT/scale.FREIGHT_SPEC).read_bytes()).hexdigest()))
        self.assertEqual(set(self.doc['scenarios']), {'run1000','run10000','run55000'})
        for key in ('demand_seed','service_date','public_vehicles','freight_completion_policy',
                    'demand_end_seconds','observation_end_seconds','native_qsim_end_seconds',
                    'signal_variant','origin_admission_policy','freight_timing_policy','postprocessing'):
            self.assertEqual(self.doc[key],old[key],key)
        for name, selection in self.doc['scenarios'].items():
            self.assertEqual(selection,old['scenarios'][name])
        expected = dict(old['base_inputs'],transit_service=scale.TRANSIT_SERVICE)
        self.assertEqual(self.doc['base_inputs'],expected)

    def test_only_authorized_scales_and_exact_values(self):
        for n, selected in self.selected.items():
            self.assertEqual(scale.require_scale(n,20261023,1,self.path,'run'+str(n)),selected['composition'])
            self.assertEqual(scale.origin_policy_for_selection(selected),scale.GAP_ORIGIN_POLICY)
            self.assertEqual(scale.launch_postprocessing_policy(selected),'native_diagnostic_v1')
        for name in ('run110000','full-1','full-10','run180000'):
            with self.subTest(name=name),self.assertRaises(ValueError):scale.experiment(self.path,name)
        for key,value in [('demand_seed',1),('public_vehicles',268),('observation_end_seconds',108000),
                          ('base_inputs',scale.BASE_INPUTS),('origin_admission_policy',{}),
                          ('freight_timing_policy',{})]:
            changed=copy.deepcopy(self.doc);changed[key]=value
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'changed.json';path.write_text(json.dumps(changed),encoding='utf-8')
                with self.subTest(key=key),self.assertRaises(ValueError):scale.experiment(path,'run1000')

    def test_trial_base_is_same_for_three_scales_and_distinct_from_v7(self):
        self.assertEqual(len({s['base_scenario_identity'] for s in self.selected.values()}),1)
        old=scale.experiment(scale.PROJECT/scale.FREIGHT_SPEC,'run1000')
        self.assertNotEqual(old['base_scenario_identity'],self.selected[1000]['base_scenario_identity'])
        manifest=dict(experiment=self.selected[1000],time_horizon=dict(start_seconds=0,end_seconds=86400),
            demand_seed=20261023,matsim_seed=20261023,iterations=dict(first=0,last=0,requested=1,completed=[0]))
        self.assertEqual(workflow.trial_experiment_identity(manifest,dict(od_mode='balanced-gateway-v1')),
                         self.selected[1000]['base_scenario_identity'])
        changed=copy.deepcopy(manifest);changed['experiment']=old
        changed['experiment']['schema']=scale.TRANSIT_SCHEMA
        with self.assertRaises(ValueError):workflow.trial_experiment_identity(changed,dict(od_mode='balanced-gateway-v1'))
        with self.assertRaises(ValueError):scale.verify_selection_identity(old,self.selected[1000])

    def test_v7_service_and_other_scale_cannot_be_substituted(self):
        scale.require_base_inputs(self.selected[1000],transit_service=scale.PROJECT/scale.TRANSIT_SERVICE)
        with self.assertRaises(ValueError):scale.require_base_inputs(self.selected[1000],transit_service=scale.PROJECT/scale.BASE_INPUTS['transit_service'])
        scale.verify_launch_request(self.request(),self.selected[1000])
        with self.assertRaises(ValueError):scale.verify_launch_request(self.request(10000),self.selected[1000])
        with self.assertRaises(ValueError):scale.launch_postprocessing_policy(self.selected[1000],'automatic_replay_v1')

    def test_pin_rebuild_preserves_full_v8_identity_without_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            pinned=generator.pin_experiment_specification(self.path,Path(folder)/'spec.json',self.selected[1000])
            rebuilt=scale.experiment(pinned,'run1000')
            scale.verify_launch_request(self.request(),rebuilt)
        physical=expected_from_selection(self.selected[1000])
        self.assertEqual(physical['physical']['simz1Admission.originPolicy'],scale.GAP_ORIGIN_POLICY)

    def test_new_inputs_are_mandatory_fingerprint_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in REQUIRED_FIXTURE_FILES:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture',encoding='utf-8')
            before=workflow.fingerprint(root)
            for name in (scale.TRANSIT_SPEC,scale.TRANSIT_SERVICE,scale.TRANSIT_BUNDLE):
                p=root/name;raw=p.read_bytes();p.write_bytes(raw+b'mutation')
                self.assertNotEqual(workflow.fingerprint(root),before)
                p.unlink()
                with self.assertRaisesRegex(ValueError,'Required source absent'):workflow.fingerprint(root)
                p.write_bytes(raw)
                self.assertEqual(workflow.fingerprint(root),before)

    def test_preparation_and_dryrun_bind_new_service_and_configuration(self):
        with patch.object(workflow,'fingerprint',return_value='1'*64):
            receipt=workflow.verify_preparation_identity(self.path,'run1000',self.request(),'1'*64,
                                                  'native_diagnostic_v1')
        with tempfile.TemporaryDirectory(prefix='v8-inert-receipt-') as folder:
            path=Path(folder)/'preparation-identity.json'
            def verify(doc):
                path.write_text(json.dumps(doc),encoding='utf-8')
                state=dict(postprocessing_policy='native_diagnostic_v1',preparation_identity_sha256=workflow.sha(path))
                workflow.require_preparation_identity(folder,state,self.request(),self.selected[1000],'1'*64)
            verify(receipt)
            for key,value in [('source_fingerprint','2'*64),('experiment',self.selected[10000]),('configuration',{})]:
                changed=copy.deepcopy(receipt);changed[key]=value
                with self.subTest(key=key),self.assertRaises(ValueError):verify(changed)


if __name__ == '__main__':unittest.main()
