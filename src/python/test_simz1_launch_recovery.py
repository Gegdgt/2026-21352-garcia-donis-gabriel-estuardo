"""Synthetic two-person native-validator/analysis/package/closure cycle; no QSim.

Only the native process is replaced by the existing fake_matsim fixture. The
real output validator publishes completed/valid; no test assigns that status.
No fixture is published as experimental acceptance.
"""
import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import simz1_launch_recovery as recovery
import simz1_configuration_contract as config
import simz1_workflow_state as workflow
from test_simz1_run import fake_matsim
from generate_montecarlo_z1 import generar, SCENARIO
from ejecutar_simz1 import ejecutar
from simz1_run import atomic_json, load_manifest, sha256
from simz1_analysis import analyze_run
from simz1_result_quality import assess
from simz1_report_package import pack


class ClosureCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='simz1-synthetic-closure-')
        cls.root=Path(cls.temp.name);cls.directory=cls.root/'synthetic-two-person-no-qsim'
        source=ET.parse(SCENARIO/'config-simz1.xml')
        qsim=source.find("module[@name='qsim']")
        step=qsim.find("param[@name='timeStepSize']")
        if step is None:step=ET.SubElement(qsim,'param',name='timeStepSize')
        step.set('value','1')
        # Resolve source references before relocating this configuration.
        for module in source.findall('module'):
            for param in module.findall('param'):
                value=param.get('value','')
                if value.endswith(('.xml','.xml.gz')) and not Path(value).is_absolute():
                    param.set('value',str((SCENARIO/value).resolve()))
        source_path=cls.root/'synthetic-source.xml';source.write(source_path)
        with redirect_stdout(io.StringIO()):
            generar(source_path,cls.directory,31,agents=2,corridor_policy='redistribute',drain_seconds=0)
        prepared=load_manifest(cls.directory)
        prepared['fixture_provenance']='synthetic test_simz1_run.fake_matsim; no native simulation executed'
        atomic_json(cls.directory/'run-manifest.json',prepared)
        maven=cls.root/'fake-maven.cmd';maven.write_text('')
        def output_fixture(*args,**kwargs):
            result=fake_matsim(*args,**kwargs)
            path=cls.directory/'output/output_config.xml';doc=ET.parse(path)
            controller=doc.find("module[@name='controler']")
            for name,value in config.NATIVE_DEFAULTS.items():
                if controller.find(f"param[@name='{name}']") is None:
                    ET.SubElement(controller,'param',name=name,value=str(value))
            vsp=doc.find("module[@name='vspExperimental']")
            if vsp is None:vsp=ET.SubElement(doc.getroot(),'module',name='vspExperimental')
            if vsp.find("param[@name='writingOutputEvents']") is None:
                ET.SubElement(vsp,'param',name='writingOutputEvents',value='true')
            doc.write(path)
            return result
        with patch.dict(os.environ,{'SIMZ1_LAUNCH_ID':'e'*32}),redirect_stdout(io.StringIO()), \
                patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=output_fixture):
            ejecutar(cls.directory,maven,iterations=2,latest_path=cls.root/'synthetic-reference.json')
        cls.manifest=load_manifest(cls.directory)
        if cls.manifest['validation']['status']!='valid':raise AssertionError('Real validator did not approve synthetic fixture')
        request=dict(launch_id='e'*32,dry_run=False,run_directory=str(cls.directory),od_mode='network',
                     first_iteration=0,last_iteration=1,iterations=2,
                     demand_seed=cls.manifest['demand_seed'],matsim_seed=cls.manifest['matsim_seed'])
        cls.request=cls.root/'synthetic-request.json';atomic_json(cls.request,request)
        with redirect_stdout(io.StringIO()):
            result=analyze_run(cls.directory,all_iterations=True,min_sample=1)
            if result['status']!='completed':raise AssertionError(result)
            for iteration in (0,1):
                summary=recovery.read(cls.directory/'analysis'/f'it.{iteration}'/'graficas_perfiles/resumen_perfiles.json')
                quality=assess(summary,0.9,False)
                if quality['status']!='screening_pass':raise AssertionError(quality)
                pack(cls.directory,iteration=iteration)
        cls.native_before=sha256(cls.directory/'run-manifest.json')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def tearDown(self):
        self.assertEqual(sha256(self.directory/'run-manifest.json'),self.native_before)

    def test_real_validator_analysis_screening_package_and_shared_closure(self):
        result=recovery.validate_launch_closure(self.root,self.request,self.directory)
        self.assertEqual(result['status'],'verified')
        self.assertEqual([x['iteration'] for x in result['products']],[0,1])
        self.assertEqual(result['configuration']['configuration']['retention']['writeEventsUntilIteration'],0)
        self.assertEqual(result['configuration']['configuration']['retention']['writePlansUntilIteration'],1)
        self.assertIn('synthetic',self.manifest['fixture_provenance'])
        self.assertFalse((self.root/'runtime/workflow').exists())

    def test_original_absent_java_only_parameter_passes_not_fictitious_xml(self):
        path=self.directory/'output/output_config.xml';old=path.read_bytes()
        self.assertNotIn(b'writeEventsUntilIteration',old)
        self.assertEqual(recovery.validate_launch_closure(self.root,self.request,self.directory)['status'],'verified')
        try:
            doc=ET.fromstring(old)
            ET.SubElement(doc.find("module[@name='controler']"),'param',name='writeEventsUntilIteration',value='0')
            path.write_bytes(ET.tostring(doc))
            with self.assertRaisesRegex(ValueError,'Unsupported MATSim 15 XML'):
                recovery.validate_launch_closure(self.root,self.request,self.directory)
        finally:path.write_bytes(old)

    def test_required_published_parameter_absence_rejected(self):
        path=self.directory/'output/output_config.xml';old=path.read_bytes()
        try:
            doc=ET.fromstring(old);controller=doc.find("module[@name='controler']")
            controller.remove(controller.find("param[@name='writePlansInterval']"));path.write_bytes(ET.tostring(doc))
            with self.assertRaisesRegex(ValueError,'Missing published configuration'):
                recovery.validate_launch_closure(self.root,self.request,self.directory)
        finally:path.write_bytes(old)

    def test_analysis_and_package_failure_preserve_native_validity(self):
        paths=[self.directory/'analysis/it.1/analysis-status.json',
               self.directory/'entregables'/(self.directory.name+'-it.1')/'docs/reporte-manifest.json']
        for path in paths:
            old=path.read_bytes()
            try:
                path.write_text('{}')
                with self.assertRaises(ValueError):recovery.validate_launch_closure(self.root,self.request,self.directory)
                self.assertEqual(load_manifest(self.directory)['validation']['status'],'valid')
                self.assertEqual(load_manifest(self.directory)['status'],'completed')
            finally:path.write_bytes(old)

    def test_iteration_and_run_substitution_rejected(self):
        old=self.request.read_bytes()
        try:
            for name,value in [('last_iteration',0),('launch_id','f'*32),('dry_run',True)]:
                bad=json.loads(old);bad[name]=value;atomic_json(self.request,bad)
                with self.assertRaises(ValueError):recovery.validate_launch_closure(self.root,self.request,self.directory)
        finally:self.request.write_bytes(old)


class RecoveryGatesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.launch_id='a'*32;self.directory=self.root/'run'
        self.launch=self.root/'runtime/launches'/self.launch_id;self.launch.mkdir(parents=True);self.directory.mkdir()
        # This identity-only fixture cannot pass the output inspector or closure.
        self.request=dict(launch_id=self.launch_id,dry_run=False,run_directory=str(self.directory))
        self.state=dict(launch_id=self.launch_id,dry_run=False,run_directory=str(self.directory),run_id='synthetic',
                        status='postprocessing_failed',native_status='completed',native_validation='valid')
        self.manifest=dict(launch_id=self.launch_id,run_id='synthetic',status='completed',validation=dict(status='valid'))
        atomic_json(self.launch/'request.json',self.request);atomic_json(self.launch/'state.json',self.state)
        atomic_json(self.directory/'run-manifest.json',self.manifest)

    def test_recovery_identity_cannot_reclassify_failed_mobility_or_other_run(self):
        recovery.recovery_identity(self.launch_id,root=self.root)
        for owner,name,value in [('state','status','failed'),('state','native_validation','invalid'),
                                 ('manifest','run_id','other'),('manifest','status','failed'),
                                 ('request','dry_run',True)]:
            old=copy.deepcopy(getattr(self,owner));bad=dict(old);bad[name]=value
            path=(self.directory/'run-manifest.json' if owner=='manifest' else self.launch/(owner+'.json'))
            atomic_json(path,bad)
            with self.assertRaises(ValueError):recovery.recovery_identity(self.launch_id,root=self.root)
            atomic_json(path,old)

    def test_complete_inventory_transition_rejects_mutation_omission_and_physics(self):
        paths=[self.root/'python/simz1_workflow_state.py',self.root/'src/main/java/Physics.java']
        for path in paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_text('old')
        before={p.relative_to(self.root).as_posix():workflow.sha(p) for p in paths}
        paths[0].write_text('reviewed launcher change')
        after={p.relative_to(self.root).as_posix():workflow.sha(p) for p in paths}
        review=dict(schema='simz1-launch-closure-reviewed-transition-v1',
                    native_source_fingerprint=recovery.inventory_digest(before,self.root),
                    current_source_fingerprint=recovery.inventory_digest(after,self.root),before=before,after=after)
        path=self.root/'review.json';atomic_json(path,review)
        with patch.object(recovery,'fingerprint_files',return_value=paths):
            recovery.reviewed_transition(path,review['native_source_fingerprint'],root=self.root)
            paths[0].write_text('unreviewed')
            with self.assertRaises(ValueError):recovery.reviewed_transition(path,review['native_source_fingerprint'],root=self.root)
            paths[0].write_text('reviewed launcher change')
            bad=copy.deepcopy(review);bad['before'].pop('src/main/java/Physics.java');atomic_json(path,bad)
            with self.assertRaises(ValueError):recovery.reviewed_transition(path,review['native_source_fingerprint'],root=self.root)
            paths[1].write_text('changed physics');bad=copy.deepcopy(review)
            bad['after']['src/main/java/Physics.java']=workflow.sha(paths[1])
            bad['current_source_fingerprint']=recovery.inventory_digest(bad['after'],self.root);atomic_json(path,bad)
            with self.assertRaisesRegex(ValueError,'Unreviewed physical'):
                recovery.reviewed_transition(path,review['native_source_fingerprint'],root=self.root)

    def test_official_trial_publisher_requires_inspector_success(self):
        destination=self.root/'trial.json'
        with patch.object(workflow,'fingerprint',return_value='a'*64), \
                patch.object(workflow,'inspect',side_effect=ValueError('native audit rejected')):
            with self.assertRaisesRegex(ValueError,'native audit rejected'):
                workflow.record_trial(self.directory,destination)
        self.assertFalse(destination.exists())

    def test_official_trial_publication_rejects_evidence_or_source_race(self):
        quality=self.directory/'analysis/it.0/graficas_perfiles/calidad_resultados.json'
        atomic_json(quality,{'synthetic':'only publication guard fixture'})
        record=dict(run_directory=str(self.directory),iteration=0,
                    manifest_sha256=workflow.sha(self.directory/'run-manifest.json'),
                    quality_sha256=workflow.sha(quality))
        destination=self.root/'trial.json'
        with patch.object(workflow,'fingerprint',return_value='b'*64):
            with self.assertRaisesRegex(ValueError,'changed before publication'):
                workflow._publish_inspected_trial(record,destination,'a'*64)
        quality.write_text('changed quality')
        with patch.object(workflow,'fingerprint',return_value='a'*64):
            with self.assertRaisesRegex(ValueError,'changed before publication'):
                workflow._publish_inspected_trial(record,destination,'a'*64)
        self.assertFalse(destination.exists())

    def test_recovered_trial_requires_immutable_receipt_and_original_evidence(self):
        recovery_id='b'*32;receipt_path=self.root/'runtime/recoveries'/recovery_id/'recovery-receipt.json'
        transition=self.root/'reviewed-transition.json';atomic_json(transition,{'synthetic':'receipt anchor only'})
        manifest_sha=workflow.sha(self.directory/'run-manifest.json')
        trial=dict(run_id='synthetic',run_directory=str(self.directory),manifest_sha256=manifest_sha,
                   source_fingerprint='c'*64)
        receipt=dict(schema='simz1-launch-recovery-v1',status='closure_recovered',recovery_id=recovery_id,
            run_id=trial['run_id'],run_directory=trial['run_directory'],original_launch_id=self.launch_id,
            source_transition=dict(current_source_fingerprint=trial['source_fingerprint'],path=str(transition),sha256=workflow.sha(transition)),
            closure=dict(manifest_sha256=manifest_sha),native_execution_repeated=False,
            native_artifacts_modified=False,historical_launch_modified=False,
            protected_artifacts={str(p):workflow.sha(p) for p in
                (self.launch/'request.json',self.launch/'state.json',self.directory/'run-manifest.json')})
        atomic_json(receipt_path,receipt)
        trial['launch_recovery']=dict(path=str(receipt_path),sha256=workflow.sha(receipt_path),recovery_id=recovery_id)
        recovery.require_recovery_receipt(trial,root=self.root)
        receipt_path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'receipt missing, indirect or changed'):
            recovery.require_recovery_receipt(trial,root=self.root)
        atomic_json(receipt_path,receipt)
        state_path=self.launch/'state.json';old=state_path.read_bytes();state_path.write_bytes(old+b' ')
        with self.assertRaisesRegex(ValueError,'original launch/native evidence changed'):
            recovery.require_recovery_receipt(trial,root=self.root)
        state_path.write_bytes(old);receipt_path.unlink()
        with self.assertRaises(OSError):recovery.require_recovery_receipt(trial,root=self.root)


class OrphanAdmissionTests(unittest.TestCase):
    """Admission-only synthetic records; never an acceptance of a native run."""
    def setUp(self):
        from contextlib import ExitStack
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32;self.run_id='simz1-'+'b'*32
        self.run=self.root/'scenarios/zona1/montecarlo'/('run-bg10-'+self.ident)
        self.run.mkdir(parents=True);self.launch=self.root/'runtime/launches'/self.ident
        self.launch.mkdir(parents=True)
        self.request=dict(launch_id=self.ident,dry_run=False,run_directory=str(self.run),
            minimum_non_public_vehicles=10000,postprocessing_policy='native_diagnostic_v1',
            od_mode='balanced-gateway-v1',first_iteration=0,last_iteration=0,iterations=1,
            demand_seed=31,matsim_seed=31,experiment={'scenario':'run10000'})
        self.state=dict(launch_id=self.ident,run_id=self.run_id,dry_run=False,run_directory=str(self.run),
            status='running',phase='simulation_and_analysis',source_fingerprint='c'*64)
        self.manifest=dict(launch_id=self.ident,run_id=self.run_id,folder=str(self.run),
            status='running',phase='validating',validation={'status':'pending'},returncode=0,
            returncode_origin='natural_exit',process={'returncode':0,'returncode_origin':'natural_exit'},
            iterations=dict(first=0,last=0,requested=1,completed=[]),
            time_horizon=dict(start_seconds=0,end_seconds=86400),
            last_completed_step=dict(seconds=86400,source='native_after_step_log'),
            demand_seed=31,matsim_seed=31,inputs={'input:experiment-specification.json':{}},experiment={})
        self.receipt=self.root/'runtime/workflow/validated-balanced-gateway-v1.json'
        atomic_json(self.receipt,dict(status='integrated_validate_pass',od_mode='balanced-gateway-v1',source_fingerprint='c'*64))
        self.observation=dict(enumeration_complete=True,tree_absent=True,stream_final=True,writer_alive=False,
            live_processes=[],ambiguous_pids=[],observed_status='orphaned/incomplete',run_id=self.run_id,launch_id=self.ident)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('simz1_run.checked_path',return_value=self.run/'pinned.json'))
        self.stack.enter_context(patch('simz1_run.completed_iterations',return_value=[0]))
        self.stack.enter_context(patch('simz1_scale_contract.experiment',return_value={}))
        self.stack.enter_context(patch('simz1_scale_contract.verify_launch_request'))
        self.stack.enter_context(patch('simz1_scale_contract.verify_selection_identity'))
        self.transition=self.stack.enter_context(patch.object(recovery,'reviewed_transition',return_value={'changed':[]}))
        self.observe=self.stack.enter_context(patch('simz1_resource_monitor.observe_launch',side_effect=lambda _:self.observation))

    def check(self):
        atomic_json(self.launch/'request.json',self.request);atomic_json(self.launch/'state.json',self.state)
        atomic_json(self.run/'run-manifest.json',self.manifest)
        return recovery.orphan_validation_context(self.run,self.manifest,self.ident,'fixture',root=self.root)

    def test_only_explicit_pending_natural_completion_is_admitted(self):
        result=self.check();self.assertEqual(result['native_execution']['run_id'],self.run_id)
        for key,value in [('returncode',None),('returncode',False),('returncode',1),
                          ('returncode_origin','observed_after_exception'),('phase','running'),
                          ('status','interrupted'),('validation',{'status':'invalid'}),
                          ('run_id','simz1-'+'f'*32),('last_completed_step',{'seconds':86399}),
                          ('time_horizon',{'start_seconds':0,'end_seconds':108000}),
                          ('process',{'returncode':0,'returncode_origin':'pending'})]:
            with self.subTest(key=key,value=value):
                old=copy.deepcopy(self.manifest);self.manifest[key]=value
                with self.assertRaises(ValueError):self.check()
                self.manifest=old

    def test_incomplete_or_live_process_observation_is_rejected(self):
        for key,value in [('enumeration_complete',False),('tree_absent',None),('stream_final',False),
                          ('writer_alive',True),('live_processes',[{'pid':12}]),('ambiguous_pids',[12]),
                          ('observed_status','unknown')]:
            old=copy.deepcopy(self.observation);self.observation[key]=value
            with self.assertRaisesRegex(ValueError,'process absence'):self.check()
            self.observation=old

    def test_physical_transition_or_unrelated_validation_receipt_is_rejected(self):
        self.transition.return_value={'changed':['python/simz1_run.py']}
        with self.assertRaisesRegex(ValueError,'only recovery'):self.check()
        self.transition.return_value={'changed':[]}
        atomic_json(self.receipt,dict(status='integrated_validate_pass',od_mode='balanced-gateway-v1',source_fingerprint='d'*64))
        with self.assertRaisesRegex(ValueError,'original integrated'):self.check()

    def test_review_required_closure_is_retained_without_trial_or_simulation(self):
        from types import SimpleNamespace
        self.check()
        self.transition.return_value={'changed':[],'current_source_fingerprint':'d'*64}
        protected={p:p.read_bytes() for p in (self.launch/'state.json',self.launch/'request.json',self.receipt)}
        # This orchestration fixture substitutes only the revalidator result;
        # RevalidationTests exercise the real XML validator separately.
        def validated_fixture(*args,**kwargs):
            state=copy.deepcopy(self.manifest)
            state.update(status='completed',validation={'status':'valid'},revalidation={'native_artifacts_sha256':{}})
            atomic_json(self.run/'run-manifest.json',state)
            return {'status':'synthetic-orchestration-fixture'}
        with patch('revalidar_simz1.revalidate',side_effect=validated_fixture), \
                patch('revalidar_simz1._native_snapshot',return_value={}), \
                patch.object(recovery,'fingerprint',return_value='d'*64), \
                patch.object(recovery,'validate_launch_closure',return_value={'products':[{'screening':'review_required'}]}), \
                patch.object(recovery.subprocess,'run',side_effect=[SimpleNamespace(returncode=3),SimpleNamespace(returncode=0)]) as execute, \
                redirect_stdout(io.StringIO()):
            result=recovery.recover_pending(self.ident,'fixture',root=self.root)
        self.assertEqual(result['exit_code'],3);self.assertEqual(result['status'],'closure_recovered')
        self.assertFalse(result['trial_authorized']);self.assertFalse(result['native_execution_repeated'])
        self.assertFalse((self.root/'runtime/workflow/trial-balanced-gateway-v1.json').exists())
        self.assertEqual(execute.call_count,2)
        self.assertIn('-AnalysisOnly',execute.call_args_list[0].args[0])
        self.assertIn('simz1_operational_report.py',' '.join(execute.call_args_list[1].args[0]))
        for path,content in protected.items():self.assertEqual(path.read_bytes(),content)


if __name__=='__main__':unittest.main()
