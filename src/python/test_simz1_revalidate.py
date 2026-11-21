"""Post-run repair tests using native-shaped fixture files, never a simulation."""
from contextlib import ExitStack
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import revalidar_simz1 as repair
from simz1_run import artifact, atomic_json, load_manifest
import test_simz1_transit_events as fixture_tools


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root/'run-fixture'
        self.run.mkdir()
        fixture = fixture_tools.TransitEventsTest()
        self.state, _, _ = fixture.fixture(self.run)
        self.state.update(schema_version=1, folder=str(self.run), status='failed', phase='validating',
            failure_phase='validating', failure_category='output_validation_error', exception_type='TypeError',
            error=repair.ERROR_TEXT, exception_traceback='File "simz1_transit_events.py", in consume\nTypeError: '+repair.ERROR_TEXT,
            validation=dict(status='invalid', error=repair.ERROR_TEXT), returncode=0, returncode_origin='natural_exit',
            started_utc='2026-10-23T23:35:00-06:00', finished_utc='2026-10-23T23:36:34-06:00',
            demand_seed=20261023, matsim_seed=20261023)
        self.state['inputs']['config'] = artifact(self.run, self.run/'config-simz1.xml')
        self.write_events(fixture.events())
        atomic_json(self.run/repair.MANIFEST, self.state)
        self.pointer = self.root/'latest-successful.json'
        self.pointer.write_text('{"unrelated_previous_run":true}', encoding='utf-8')
        baseline = dict(use_lanes=False, signals_enabled=False, baseline_parameters={},
                        signatures={'network': 'fixture', 'lanes': None, 'signals': None})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('simz1_run.validate_configuration', return_value={'admission_policy':'matsim15-native'}))
        self.stack.enter_context(patch('simz1_run.audit_configuration', side_effect=lambda *a, **k: copy.deepcopy(baseline)))
        self.stack.enter_context(patch('simz1_gateway_od.validated_spatial_demand', return_value=None))
        self.stack.enter_context(patch('simz1_signal_replay.selected_groups', return_value=[]))
        # A revalidator must never start any external program, even in a fixture.
        self.stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('unexpected subprocess')))
        self.stack.enter_context(patch('os.system', side_effect=AssertionError('unexpected shell')))

    def write_events(self, rows):
        root = ET.Element('events')
        root.extend(rows)
        with gzip.open(self.run/'output/output_events.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(root))

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_read_only_audit_does_not_publish_or_write(self):
        before = self.files()
        result = repair.revalidate(self.run)
        self.assertEqual(result['status'], 'revalidation_pass_not_published')
        self.assertEqual(result['results']['0']['counts']['observed_persons'], 1)
        self.assertEqual(before, self.files())

    def pending_orphan(self):
        for key in repair.FAILURE_FIELDS:self.state.pop(key,None)
        self.state.update(status='running',phase='validating',validation={'status':'pending'})
        atomic_json(self.run/repair.MANIFEST,self.state)
        folder=self.run/'output/ITERS/it.0';folder.mkdir(parents=True,exist_ok=True)
        for kind in ('events','plans'):
            (folder/f'0.{kind}.xml.gz').write_bytes((self.run/f'output/output_{kind}.xml.gz').read_bytes())
        return dict(source_transition={'fixture':'reviewed'},native_execution={'fixture':'natural_exit'},
                    validated_source_receipt={'fixture':'prior'},observation={'fixture':'absent'})

    def test_explicit_orphan_mode_uses_full_validator_and_preserves_original(self):
        context=self.pending_orphan();original=(self.run/repair.MANIFEST).read_bytes()
        with self.assertRaisesRegex(ValueError,'Not a supported'):
            repair.revalidate(self.run,apply=True)
        with patch('simz1_launch_recovery.orphan_validation_context',return_value=context) as gate:
            result=repair.revalidate(self.run,apply=True,orphan_launch_id='a'*32,reviewed_transition='fixture')
        saved=load_manifest(self.run)
        self.assertEqual(gate.call_count,2)
        self.assertEqual(saved['validation']['status'],'valid')
        self.assertEqual(saved['revalidation']['operation'],'resume_orphaned_native_validation_v1')
        self.assertEqual(Path(result['manifest_backup']).read_bytes(),original)
        self.assertEqual(saved['returncode_origin'],'natural_exit')
        self.assertFalse(result['matsim_executed'])

    def test_orphan_corrupt_xml_or_iteration_substitution_never_publishes(self):
        context=self.pending_orphan();original=(self.run/repair.MANIFEST).read_bytes()
        final=self.run/'output/output_events.xml.gz';iteration=self.run/'output/ITERS/it.0/0.events.xml.gz'
        original_events=final.read_bytes()
        for matched in (False,True):
            final.write_bytes(b'not a gzip stream')
            iteration.write_bytes(final.read_bytes() if matched else original_events)
            with patch('simz1_launch_recovery.orphan_validation_context',return_value=context):
                with self.assertRaises((ValueError,OSError)):
                    repair.revalidate(self.run,apply=True,orphan_launch_id='a'*32,reviewed_transition='fixture')
            self.assertEqual((self.run/repair.MANIFEST).read_bytes(),original)

    def test_orphan_provenance_mutation_at_final_gate_prevents_publication(self):
        context=self.pending_orphan();original=(self.run/repair.MANIFEST).read_bytes()
        changed=copy.deepcopy(context);changed['source_transition']={'fixture':'mutated'}
        with patch('simz1_launch_recovery.orphan_validation_context',side_effect=[context,changed]):
            with self.assertRaisesRegex(ValueError,'provenance changed'):
                repair.revalidate(self.run,apply=True,orphan_launch_id='a'*32,reviewed_transition='fixture')
        self.assertEqual((self.run/repair.MANIFEST).read_bytes(),original)

    def test_orphan_iteration_plans_may_precede_scoring_but_must_preserve_population(self):
        context=self.pending_orphan()
        plans=self.run/'output/ITERS/it.0/0.plans.xml.gz'
        with gzip.open(plans,'rb') as stream:doc=ET.fromstring(stream.read())
        for plan in doc.iter('plan'):plan.attrib.pop('score',None)
        with gzip.open(plans,'wb') as stream:stream.write(ET.tostring(doc))
        with patch('simz1_launch_recovery.orphan_validation_context',return_value=context):
            result=repair.revalidate(self.run,orphan_launch_id='a'*32,reviewed_transition='fixture')
            self.assertEqual(result['status'],'revalidation_pass_not_published')
            doc.find('person').set('id','substituted-person')
            with gzip.open(plans,'wb') as stream:stream.write(ET.tostring(doc))
            with self.assertRaisesRegex(ValueError,'population identity'):
                repair.revalidate(self.run,orphan_launch_id='a'*32,reviewed_transition='fixture')

    def test_apply_runs_full_validator_preserves_native_files_and_exact_backup(self):
        before = self.files()
        original = (self.run/repair.MANIFEST).read_bytes()
        result = repair.revalidate(self.run, apply=True)
        saved = load_manifest(self.run)
        self.assertEqual(result['status'], 'completed_valid_revalidated')
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['validation']['status'], 'valid')
        self.assertEqual(saved['finished_utc'], self.state['finished_utc'])
        self.assertEqual(saved['demand_seed'], self.state['demand_seed'])
        self.assertNotIn('error', saved)
        self.assertEqual(saved['revalidation']['original_failure']['error'], repair.ERROR_TEXT)
        self.assertEqual(Path(result['manifest_backup']).read_bytes(), original)
        for name, content in before.items():
            if name != 'run-fixture/'+repair.MANIFEST:
                self.assertEqual((self.root/name).read_bytes(), content)
        self.assertFalse(result['matsim_executed'])
        self.assertFalse(result['trial_authorized'])
        self.assertFalse((self.run/'.simz1-revalidation.lock').exists())

    def test_apply_is_idempotent_and_rechecks_native_files(self):
        repair.revalidate(self.run, apply=True)
        before = self.files()
        result = repair.revalidate(self.run, apply=True)
        self.assertEqual(result['status'], 'already_valid_rechecked_no_metadata_change')
        self.assertEqual(before, self.files())

    def test_refresh_valid_rechecks_and_backs_up_but_never_repairs_failure(self):
        with self.assertRaisesRegex(ValueError,'cannot repair'):
            repair.revalidate(self.run, apply=True, refresh_valid=True)
        repair.revalidate(self.run, apply=True)
        original=(self.run/repair.MANIFEST).read_bytes()
        result=repair.revalidate(self.run, apply=True, refresh_valid=True)
        self.assertEqual(Path(result['manifest_backup']).read_bytes(),original)
        saved=load_manifest(self.run)
        self.assertEqual(saved['revalidation']['operation'],'refresh_valid_metadata')
        self.assertFalse(saved['revalidation']['native_artifacts_modified'])

    def test_runtime_failure_interruption_and_nonzero_exit_are_rejected(self):
        changes = [{'status':'running'}, {'status':'interrupted'}, {'returncode':1},
                   {'returncode':None}, {'returncode':False}, {'returncode_origin':'pending'},
                   {'phase':'shutdown'}, {'exception_type':'ValueError'}, {'error':'something else'},
                   {'exception_traceback':'different file'}, {'failure_category':'runtime_exception'}]
        for change in changes:
            with self.subTest(change=change):
                atomic_json(self.run/repair.MANIFEST, {**self.state, **change})
                before = self.files()
                with self.assertRaises(ValueError):
                    repair.revalidate(self.run, apply=True)
                self.assertEqual(before, self.files())

    def test_incomplete_iterations_are_not_certified(self):
        (self.run/'output/stopwatch.txt').write_text('Iteration\tEND iteration\n0\t\n', encoding='utf-8')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Iteraciones incompletas'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_supported_request_error_still_requires_full_validator_and_preserves_backup(self):
        self.state.update(exception_type='ValueError', error=repair.OCCUPANCY_WAIT_ERROR,
            exception_traceback='File "simz1_occupancy_audit.py", in _reservation\nValueError: '+repair.OCCUPANCY_WAIT_ERROR)
        atomic_json(self.run/repair.MANIFEST,self.state)
        original=(self.run/repair.MANIFEST).read_bytes()
        with patch.object(repair,'validate_outputs',side_effect=ValueError('actual ENTER violation')):
            with self.assertRaisesRegex(ValueError,'actual ENTER'):
                repair.revalidate(self.run,apply=True)
        self.assertEqual((self.run/repair.MANIFEST).read_bytes(),original)
        result=repair.revalidate(self.run,apply=True)
        self.assertEqual(Path(result['manifest_backup']).read_bytes(),original)
        self.assertEqual(load_manifest(self.run)['revalidation']['operation'],'repair_supported_occupancy_request_error')

    def coordination_import_failure(self):
        module_path=Path(repair.__file__).with_name('simz1_signal_coordination.py').resolve()
        validator_path=Path(repair.__file__).with_name('simz1_run.py').resolve()
        message=repair.COORDINATION_IMPORT_ERROR+' ('+str(module_path)+')'
        return {**self.state, 'exception_type':'ImportError', 'error':message,
            'exception_traceback':f'Traceback (most recent call last):\n  File "{validator_path}", line 378, in validate_outputs\n    from simz1_signal_coordination import validate_report\nImportError: {message}\n',
            'validation':dict(status='invalid',error=message)}

    def fixed_day_step_failure(self):
        validator = Path(repair.__file__).with_name('simz1_run.py').resolve()
        auditor = Path(repair.__file__).with_name('simz1_balanced_od_audit.py').resolve()
        message = "could not convert string to float: '00:00:01'"
        trace = (f'Traceback (most recent call last):\n  File "{validator}", line 349, in validate_outputs\n'
                 '    balanced_od = validate_balanced_od(directory, manifest)\n'
                 f'  File "{auditor}", line 167, in validate_manifest\n'
                 "    float(config.get('qsim.timeStepSize','1'))!=1):raise ValueError('Native fixed-day boundary contract mismatch')\n"
                 f'ValueError: {message}\n')
        return {**self.state, 'exception_type': 'ValueError', 'error': message,
                'exception_traceback': trace, 'validation': dict(status='invalid', error=message),
                'experiment': dict(observation_policy='fixed-day-24h-v1', native_qsim_end_seconds=86399,
                                   observation_end_seconds=86400),
                'time_horizon': dict(start_seconds=0, end_seconds=86400),
                'iterations': dict(first=0, last=0, requested=1, completed=[0]),
                'last_completed_step': dict(seconds=86400, source='native_after_step_log')}

    def test_fixed_day_step_serialization_is_an_exact_supported_recovery(self):
        self.assertEqual(repair._eligible(self.fixed_day_step_failure()), 'repairable_fixed_day_step_format')

    def test_fixed_day_step_recovery_rejects_other_errors_interruption_and_partial_days(self):
        state = self.fixed_day_step_failure()
        changes = [{'error': "could not convert string to float: '00:00:02'"},
                   {'exception_type': 'TypeError'}, {'returncode': 1}, {'returncode': False},
                   {'returncode': None}, {'returncode_origin': 'terminated'}, {'status': 'interrupted'},
                   {'failure_category': 'runtime_exception'}, {'phase': 'running'},
                   {'validation': dict(status='invalid', error='another failure')},
                   {'exception_traceback': state['exception_traceback'].replace('in validate_manifest', 'in generate')},
                   {'exception_traceback': state['exception_traceback'].replace('simz1_balanced_od_audit.py', 'other.py')},
                   {'exception_traceback': state['exception_traceback'].replace('qsim.timeStepSize', 'qsim.stuckTime')},
                   {'iterations': dict(first=0, last=0, requested=1, completed=[])},
                   {'iterations': dict(first=0, last=0, requested=True, completed=[0])},
                   {'last_completed_step': dict(seconds=86399, source='native_after_step_log')},
                   {'last_completed_step': dict(seconds=86400, source='inferred')},
                   {'time_horizon': dict(start_seconds=0, end_seconds=108000)},
                   {'experiment': dict(state['experiment'], native_qsim_end_seconds=86400)}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                repair._eligible(dict(state, **change))

    def step_recovery_fixture(self):
        """Small synthetic provenance fixture; never a real trial/launch receipt."""
        from simz1_balanced_od_audit import implementation_signature
        state = self.fixed_day_step_failure()
        state['launch_id'] = '1'*32
        state['counts'] = dict(planned_persons=1)
        # This fixture models the historical parser revision, not whichever
        # postprocessor happens to be checked out while the test is running.
        historical = implementation_signature()
        for name, transition in repair.STEP_FORMAT_TRANSITIONS.items():
            historical['source_sha256'][name] = transition['after']
        self.stack.enter_context(patch('simz1_balanced_od_audit.implementation_signature',
            side_effect=lambda: copy.deepcopy(historical)))
        actual_sha = repair.sha256
        historical_paths = {Path(repair.__file__).with_name(name).resolve(): transition['after']
                            for name, transition in repair.STEP_FORMAT_TRANSITIONS.items()}
        self.stack.enter_context(patch.object(repair, 'sha256', side_effect=lambda path:
            historical_paths.get(Path(path).resolve()) or actual_sha(path)))
        signature = copy.deepcopy(historical)
        for name, transition in repair.STEP_FORMAT_TRANSITIONS.items():
            signature['source_sha256'][name] = transition['before']
        code = self.run/'od-implementation.json'
        atomic_json(code, signature)
        state['balanced_od'] = dict(variant='balanced-gateway-v1', implementation=artifact(self.run, code))
        state['inputs']['input:od-implementation.json'] = artifact(self.run, code)
        for relative, step in [('config-simz1.xml', '1'), ('output/output_config.xml', '00:00:01')]:
            path = self.run/relative
            root = ET.parse(path).getroot()
            qsim = root.find("module[@name='qsim']")
            qsim.find("param[@name='endTime']").set('value', '86399')
            ET.SubElement(qsim, 'param', name='timeStepSize', value=step)
            ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
        state['inputs']['config'] = artifact(self.run, self.run/'config-simz1.xml')
        state['effective_config'] = artifact(self.run, self.run/'output/output_config.xml')
        launch_path = self.root/'runtime/launches'/state['launch_id']/'state.json'
        launch_path.parent.mkdir(parents=True)
        atomic_json(launch_path, dict(launch_id=state['launch_id'], run_id=state['run_id'],
            run_directory=str(self.run), source_fingerprint=repair.STEP_FORMAT_EXECUTION_FINGERPRINT,
            dry_run=False, status='failed'))
        self.stack.enter_context(patch.object(repair, 'PROJECT', self.root))
        atomic_json(self.run/repair.MANIFEST, state)
        return state, launch_path

    def step_validator_boundary(self, directory, candidate, *, implementation_compatibility):
        # Tests the transaction boundary; native acceptance is intentionally not
        # claimed by this synthetic callback. Actual output checks have separate
        # native-shaped regressions below and the real full revalidation.
        self.assertEqual(load_manifest(directory)['status'], 'failed')
        self.assertEqual(candidate['status'], 'running')
        self.assertEqual(candidate['validation']['status'], 'pending')
        self.assertEqual(implementation_compatibility['transitions'], repair.STEP_FORMAT_TRANSITIONS)
        candidate['validation'] = dict(status='valid')
        candidate['results'] = {'0': dict(counts=dict(observed_persons=1))}

    def publish_step_fixture(self):
        state, launch = self.step_recovery_fixture()
        with patch.object(repair, 'validate_outputs', side_effect=self.step_validator_boundary) as validator:
            outcome = repair.revalidate(self.run, apply=True)
        validator.assert_called_once()
        return state, launch, outcome, load_manifest(self.run)

    def test_fixed_day_recovery_keeps_failure_on_disk_until_full_validation_returns(self):
        state, launch = self.step_recovery_fixture()
        before = self.files()
        with patch.object(repair, 'validate_outputs', side_effect=self.step_validator_boundary):
            result = repair.revalidate(self.run)
        self.assertEqual(before, self.files())
        self.assertEqual(result['status'], 'revalidation_pass_not_published')
        self.assertEqual(result['native_execution']['source_fingerprint'], repair.STEP_FORMAT_EXECUTION_FINGERPRINT)
        self.assertNotEqual(result['original_implementation_signature'], result['validator_implementation_signature'])
        with patch.object(repair, 'validate_outputs', side_effect=ValueError('actual native violation')):
            with self.assertRaisesRegex(ValueError, 'actual native violation'):
                repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_fixed_day_recovery_publishes_provenance_and_exact_backup_only_after_pass(self):
        state, launch, result, saved = self.publish_step_fixture()
        original = json.loads(Path(result['manifest_backup']).read_bytes())
        self.assertEqual(original, state)
        self.assertEqual(saved['revalidation']['operation'], repair.STEP_FORMAT_OPERATION)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['validation']['status'], 'valid')
        self.assertEqual(json.loads(launch.read_bytes())['status'], 'failed')
        for key in repair.NATIVE_IDENTITY_FIELDS:
            self.assertEqual(saved.get(key), original.get(key), key)
        self.assertFalse(result['matsim_executed'])
        self.assertFalse(result['trial_authorized'])
        self.assertEqual(repair.recovery_compatibility(self.run, saved),
                         saved['revalidation']['implementation_compatibility'])
        self.assertEqual(saved['revalidation']['validator_sources']['simz1_run.py'],
                         repair.STEP_FORMAT_TRANSITIONS['simz1_run.py']['after'])

    def test_fixed_day_recovery_does_not_skip_native_iteration_completion(self):
        self.step_recovery_fixture()
        (self.run/'output/stopwatch.txt').write_text('Iteration\tEND iteration\n0\t\n', encoding='utf-8')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Iteraciones incompletas'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_fixed_day_recovered_receipt_is_rechecked_and_refresh_keeps_original_failure(self):
        state, launch, first, saved = self.publish_step_fixture()
        before = self.files()
        def recheck(directory, candidate, *, implementation_compatibility):
            self.assertEqual(candidate['status'], 'completed')
            self.assertEqual(candidate['validation']['status'], 'valid')
            self.assertEqual(implementation_compatibility, saved['revalidation']['implementation_compatibility'])
        with patch.object(repair, 'validate_outputs', side_effect=recheck):
            again = repair.revalidate(self.run, apply=True)
            self.assertEqual(again['status'], 'already_valid_rechecked_no_metadata_change')
            self.assertEqual(before, self.files())
            refreshed = repair.revalidate(self.run, apply=True, refresh_valid=True)
        latest = load_manifest(self.run)
        self.assertEqual(latest['revalidation']['original_manifest'], saved['revalidation']['original_manifest'])
        self.assertEqual(latest['revalidation']['operation'], repair.STEP_FORMAT_OPERATION)
        self.assertEqual(repair.recovery_compatibility(self.run, latest), saved['revalidation']['implementation_compatibility'])
        self.assertEqual(json.loads(Path(first['manifest_backup']).read_bytes()), state)
        self.assertEqual(json.loads(Path(refreshed['manifest_backup']).read_bytes()), saved)

    def test_fixed_day_recovery_rejects_unidentified_launch_and_missing_signed_input(self):
        state, launch = self.step_recovery_fixture()
        original_launch = json.loads(launch.read_bytes())
        for key, value in [('run_id','other-run'), ('run_directory',str(self.root/'other-run')),
                           ('source_fingerprint','0'*64), ('dry_run',True), ('status','running')]:
            with self.subTest(key=key):
                atomic_json(launch, dict(original_launch, **{key:value}))
                with self.assertRaisesRegex(ValueError, 'Launch identity/revision'):
                    repair._step_format_context(self.run, state)
        atomic_json(launch, original_launch)
        for launch_id in ('../other', None, ''):
            with self.subTest(launch_id=launch_id), self.assertRaises(ValueError):
                repair._step_format_context(self.run, dict(state, launch_id=launch_id))
        (self.run/'od-implementation.json').unlink()
        with self.assertRaises(ValueError): repair._step_format_context(self.run, state)

    def test_fixed_day_recovery_rejects_step_horizon_and_source_mutations(self):
        state, launch = self.step_recovery_fixture()
        path = self.run/'output/output_config.xml'
        original = path.read_bytes()
        for key, value in [('timeStepSize','2'), ('timeStepSize','0'), ('timeStepSize','nan'),
                           ('timeStepSize','00:00:02'), ('timeStepSize','invalid'), ('endTime','86400')]:
            with self.subTest(key=key, value=value):
                path.write_bytes(original)
                xml = ET.parse(path)
                xml.getroot().find(f"module[@name='qsim']/param[@name='{key}']").set('value', value)
                xml.write(path, encoding='utf-8', xml_declaration=True)
                # Even an updated artifact hash cannot excuse a changed physical value.
                modified = dict(state, effective_config=artifact(self.run, path))
                with self.assertRaises(ValueError): repair._step_format_context(self.run, modified)
        path.write_bytes(original)
        from simz1_balanced_od_audit import implementation_signature
        current = implementation_signature()
        for name in current['source_sha256']:
            changed = copy.deepcopy(current)
            changed['source_sha256'][name] = '0'*64
            with self.subTest(source=name), patch('simz1_balanced_od_audit.implementation_signature', return_value=changed):
                with self.assertRaises(ValueError): repair._step_format_context(self.run, state)
        code = self.run/'od-implementation.json'
        code.write_bytes(code.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            repair._step_format_context(self.run, state)

    def test_fixed_day_receipt_rejects_metadata_backup_native_identity_and_source_changes(self):
        state, launch, result, saved = self.publish_step_fixture()
        for key, value in [('execution_repeated', True), ('native_artifacts_modified', True),
                           ('version', 'unknown'), ('original_manifest_sha256', '0'*64),
                           ('implementation_compatibility', {}), ('native_execution', {}),
                           ('original_implementation_signature', {}), ('validator_implementation_signature', {}),
                           ('validator_sources', {}), ('native_artifacts_sha256', {})]:
            bad = copy.deepcopy(saved); bad['revalidation'][key] = value
            with self.subTest(receipt=key), self.assertRaises(ValueError):
                repair.recovery_compatibility(self.run, bad)
        for key in repair.NATIVE_IDENTITY_FIELDS:
            bad = copy.deepcopy(saved); bad[key] = 'changed-native-identity'
            with self.subTest(identity=key), self.assertRaises(ValueError):
                repair.recovery_compatibility(self.run, bad)
        backup = Path(result['manifest_backup'])
        original = backup.read_bytes(); backup.write_bytes(original+b'\n')
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            repair.recovery_compatibility(self.run, saved)
        backup.write_bytes(original)
        launch_original = launch.read_bytes()
        launch.write_bytes(launch_original+b'\n')
        with self.assertRaisesRegex(ValueError, 'provenance receipt changed'):
            repair.recovery_compatibility(self.run, saved)
        launch.write_bytes(launch_original)
        actual_sha = repair.sha256
        with patch.object(repair, 'sha256', side_effect=lambda p: '0'*64 if Path(p).name=='simz1_workflow_state.py' else actual_sha(p)):
            with self.assertRaisesRegex(ValueError, 'sources changed'):
                repair.recovery_compatibility(self.run, saved)
        with patch.object(repair, 'sha256', side_effect=lambda p: (_ for _ in ()).throw(FileNotFoundError('missing validator')) if Path(p).name=='simz1_workflow_state.py' else actual_sha(p)):
            with self.assertRaises(FileNotFoundError): repair.recovery_compatibility(self.run, saved)

    def test_other_revalidation_operations_do_not_enable_compatibility(self):
        for receipt in ({}, {'operation':'refresh_valid_metadata'}, {'operation':'repair_supported_transit_error'}):
            self.assertIsNone(repair.recovery_compatibility(self.run, dict(revalidation=receipt)))

    def test_workflow_verifies_recovery_before_od_and_keeps_quality_and_validate_gates(self):
        import simz1_workflow_state as workflow
        state, launch, result, saved = self.publish_step_fixture()
        evidence = dict(events=artifact(self.run, self.run/'output/output_events.xml.gz'),
                        plans=saved['inputs']['plans'], network=saved['inputs']['network'])
        evidence['private_od_events'] = dict(evidence_status='closed_native_event_stream',
            source=dict(run_id=saved['run_id'], events=evidence['events']))
        saved['results']['0'].update(evidence)
        atomic_json(self.run/repair.MANIFEST, saved)
        quality = self.run/'analysis/it.0/graficas_perfiles/calidad_resultados.json'
        quality.parent.mkdir(parents=True)
        quality_data = dict(run_id=saved['run_id'], iteration=0, status='screening_pass')
        atomic_json(quality, quality_data)
        with patch.object(workflow, 'require_balanced_validation') as integrated, \
             patch('simz1_balanced_launch.manifest_identity', return_value=dict(od_mode='balanced-gateway-v1')), \
             patch('simz1_day_observation.enabled', return_value=False), \
             patch('simz1_balanced_od_audit.validate_manifest') as audit, \
             patch.object(repair, 'recovery_compatibility', wraps=repair.recovery_compatibility) as receipt:
            inspected = workflow.inspect(self.run, expected_people=1, require_transit=False)
            receipt.assert_called_once()
            self.assertEqual(audit.call_args.kwargs['implementation_compatibility'],
                             saved['revalidation']['implementation_compatibility'])
            self.assertEqual(inspected['run_id'], saved['run_id'])
            self.assertFalse((self.root/'runtime/workflow/trial.json').exists())
            receipt.reset_mock(); audit.reset_mock()
            atomic_json(quality, dict(quality_data, status='review_required'))
            with self.assertRaisesRegex(ValueError, 'Road quality does not pass'):
                workflow.inspect(self.run, expected_people=1, require_transit=False)
            receipt.assert_not_called(); audit.assert_not_called()
            atomic_json(quality, quality_data)
            integrated.side_effect = ValueError('current Validate absent')
            with self.assertRaisesRegex(ValueError, 'current Validate absent'):
                workflow.inspect(self.run, expected_people=1, require_transit=False)
            receipt.assert_not_called(); audit.assert_not_called()
            integrated.side_effect = None
            saved['revalidation']['implementation_compatibility']['transitions']['simz1_run.py']['after'] = '0'*64
            atomic_json(self.run/repair.MANIFEST, saved)
            with self.assertRaisesRegex(ValueError, 'compatibility/provenance'):
                workflow.inspect(self.run, expected_people=1, require_transit=False)
            audit.assert_not_called()

    def interval_cap_failure(self):
        return {**self.state, 'exception_type':'ValueError', 'error':repair.OCCUPANCY_INTERVAL_ERROR,
            'exception_traceback':'File "simz1_occupancy_audit.py", line 477, in _passage\nValueError: '+repair.OCCUPANCY_INTERVAL_ERROR,
            'validation':dict(status='invalid',error=repair.OCCUPANCY_INTERVAL_ERROR)}

    def test_interval_cap_repair_preserves_evidence_and_still_rejects_actual_violation(self):
        # Synthetic native-shaped fixture; the real interval regression is in
        # test_simz1_occupancy_audit. Eligibility never replaces full validation.
        state=self.interval_cap_failure();atomic_json(self.run/repair.MANIFEST,state)
        before=self.files();original=(self.run/repair.MANIFEST).read_bytes()
        with patch.object(repair,'validate_outputs',side_effect=ValueError(repair.OCCUPANCY_INTERVAL_ERROR)):
            with self.assertRaisesRegex(ValueError,'free entry interval'):repair.revalidate(self.run,apply=True)
        self.assertEqual(before,self.files())
        actual_validate=repair.validate_outputs
        with patch.object(repair,'validate_outputs',wraps=actual_validate) as validator:
            result=repair.revalidate(self.run,apply=True)
            validator.assert_called_once()
        saved=load_manifest(self.run)
        self.assertEqual(saved['revalidation']['operation'],'repair_supported_occupancy_interval_cap')
        self.assertEqual(Path(result['manifest_backup']).read_bytes(),original)
        self.assertFalse(result['matsim_executed']);self.assertFalse(result['trial_authorized'])
        for name,content in before.items():
            if name!='run-fixture/'+repair.MANIFEST:self.assertEqual((self.root/name).read_bytes(),content)

    def test_interval_cap_repair_rejects_different_errors_and_incomplete_execution(self):
        state=self.interval_cap_failure()
        for change in ({'error':'FREIGHT_NOT_APPROVED'}, {'exception_type':'TypeError'},
                       {'exception_traceback':'another_validator.py, in _passage\n'},
                       {'exception_traceback':'simz1_occupancy_audit.py, in _reservation\n'},
                       {'phase':'running'}, {'failure_phase':'running'}, {'failure_category':'runtime_exception'},
                       {'returncode':1}, {'returncode':False}, {'returncode':None}, {'returncode_origin':'pending'}):
            with self.subTest(change=change):
                atomic_json(self.run/repair.MANIFEST,{**state,**change});before=self.files()
                with self.assertRaises(ValueError):repair.revalidate(self.run,apply=True)
                self.assertEqual(before,self.files())

    def test_coordination_import_repair_runs_full_validator_and_fingerprints_module(self):
        state=self.coordination_import_failure();atomic_json(self.run/repair.MANIFEST,state)
        before=self.files();original=(self.run/repair.MANIFEST).read_bytes()
        actual_validate=repair.validate_outputs
        with patch.object(repair,'validate_outputs',wraps=actual_validate) as validator:
            result=repair.revalidate(self.run,apply=True)
            validator.assert_called_once()
        saved=load_manifest(self.run)
        self.assertEqual(saved['revalidation']['operation'],'repair_supported_coordination_validator_import')
        self.assertEqual(saved['validation']['status'],'valid')
        self.assertEqual(Path(result['manifest_backup']).read_bytes(),original)
        self.assertEqual(saved['revalidation']['original_failure']['error'],state['error'])
        self.assertEqual(saved['revalidation']['validator_sources']['simz1_signal_coordination.py'],
                         repair.sha256(Path(repair.__file__).with_name('simz1_signal_coordination.py')))
        self.assertEqual(saved['revalidation']['native_artifacts_sha256']['output/output_events.xml.gz'],
                         repair.sha256(self.run/'output/output_events.xml.gz'))
        for name,content in before.items():
            if name!='run-fixture/'+repair.MANIFEST:self.assertEqual((self.root/name).read_bytes(),content)

    def test_coordination_import_eligibility_is_exact_and_never_certifies_interruptions(self):
        state=self.coordination_import_failure()
        changes=[{'error':repair.COORDINATION_IMPORT_ERROR},
                 {'error':state['error'].replace('validate_report','different_symbol')},
                 {'error':state['error'].replace('simz1_signal_coordination.py','another_module.py')},
                 {'exception_type':'ModuleNotFoundError'},
                 {'exception_traceback':state['exception_traceback'].replace('in validate_outputs','in ejecutar')},
                 {'exception_traceback':state['exception_traceback'].replace('simz1_run.py','another_validator.py')},
                 {'exception_traceback':state['exception_traceback'].replace('import validate_report','import coordinate')},
                 {'phase':'running'},{'failure_phase':'running'},{'failure_category':'runtime_exception'},
                 {'returncode':1},{'returncode':False},{'returncode':None},{'returncode_origin':'pending'}]
        for change in changes:
            with self.subTest(change=change):
                atomic_json(self.run/repair.MANIFEST,{**state,**change});before=self.files()
                with self.assertRaises(ValueError):repair.revalidate(self.run,apply=True)
                self.assertEqual(before,self.files())

    def test_coordination_import_does_not_bypass_actual_output_failure(self):
        atomic_json(self.run/repair.MANIFEST,self.coordination_import_failure())
        (self.run/'output/stopwatch.txt').write_text('Iteration\tEND iteration\n0\t\n',encoding='utf-8')
        before=self.files()
        with self.assertRaisesRegex(ValueError,'Iteraciones incompletas'):
            repair.revalidate(self.run,apply=True)
        self.assertEqual(before,self.files())

    def test_changed_fingerprinted_input_is_not_accepted(self):
        with (self.run/'network.xml').open('a') as stream:
            stream.write('\n')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_missing_output_and_truncated_xml_fail_without_metadata_changes(self):
        path = self.run/'output/output_events.xml.gz'
        path.unlink()
        before = self.files()
        with self.assertRaisesRegex(RuntimeError, 'sin salidas esperadas'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())
        with gzip.open(path, 'wb') as stream:
            stream.write(b'<events><event')
        before = self.files()
        with self.assertRaises(ET.ParseError):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_actual_backdated_event_is_not_sorted_or_ignored(self):
        self.write_events(fixture_tools.TransitEventsTest().events()+[
            fixture_tools.event('arrival', 0, person='native-no-prefix', link='ab')])
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Tiempos invalidos'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_artifact_change_during_validation_prevents_publication(self):
        actual_validate = repair.validate_outputs
        def changed(directory, manifest):
            actual_validate(directory, manifest)
            (directory/'output/new-unexpected.txt').write_text('concurrent writer')
        original = (self.run/repair.MANIFEST).read_bytes()
        with patch.object(repair, 'validate_outputs', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during validation'):
                repair.revalidate(self.run, apply=True)
        self.assertEqual(original, (self.run/repair.MANIFEST).read_bytes())
        self.assertFalse((self.run/'validation-history').exists())

    def test_existing_lock_is_not_removed_or_ignored(self):
        lock = self.run/'.simz1-revalidation.lock'
        lock.write_text('another operation')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'preserved lock'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())

    def test_manifest_publication_failure_preserves_original_and_backup(self):
        original = (self.run/repair.MANIFEST).read_bytes()
        with patch.object(repair, 'atomic_json', side_effect=OSError('simulated disk full')):
            with self.assertRaises(OSError):
                repair.revalidate(self.run, apply=True)
        self.assertEqual(original, (self.run/repair.MANIFEST).read_bytes())
        backups = list((self.run/'validation-history').glob('*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertFalse((self.run/'.simz1-revalidation.lock').exists())

    def test_cli_returns_nonzero_and_never_success_on_failure(self):
        (self.run/'output/output_events.xml.gz').unlink()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            code = repair.main(['--run-dir', str(self.run), '--apply'])
        self.assertEqual(code, 1)
        self.assertNotIn('completed_valid_revalidated', stdout.getvalue())
        self.assertIn('Traceback', stderr.getvalue())
        self.assertEqual(load_manifest(self.run)['status'], 'failed')

    def test_folder_identity_mismatch_is_not_repaired(self):
        atomic_json(self.run/repair.MANIFEST, {**self.state, 'folder':str(self.root/'another-run')})
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'Manifiesto incompatible'):
            repair.revalidate(self.run, apply=True)
        self.assertEqual(before, self.files())


class ReviewedPostprocessingTests(unittest.TestCase):
    """Complete tiny source inventories and receipts, wholly inside a temp tree.

    No real approval policy/receipt is generated or patched. The production
    restoration and compatibility functions run unchanged against this fixture.
    """
    def setUp(self):
        import simz1_workflow_state as workflow
        self.workflow=workflow
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.run=self.root/'run-fixture';self.run.mkdir()
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('subprocess.Popen',side_effect=AssertionError('unexpected subprocess')))
        self.stack.enter_context(patch('os.system',side_effect=AssertionError('unexpected shell')))
        self.source_names={'python/'+name for name in repair.VALIDATOR_SOURCES}
        self.source_names.update({'src/main/java/Physical.java','scenarios/zona1/network.xml',
                                  'python/generate_montecarlo_z1.py'})
        for name in self.source_names:self.write(name,('fixture baseline '+name+'\n').encode())
        self.base={name:repair.sha256(self.root/name) for name in self.source_names}
        self.transitions={name:dict(before=self.hash_bytes(('native '+name).encode()),
                                    after=self.base['python/'+name]) for name in repair.STEP_FORMAT_TRANSITIONS}
        self.native=dict(self.base)
        for name,pair in self.transitions.items():self.native['python/'+name]=pair['before']
        self.base_fingerprint=self.digest(self.base);self.native_fingerprint=self.digest(self.native)
        self.stack.enter_context(patch.object(repair,'PROJECT',self.root))
        self.stack.enter_context(patch.object(workflow,'PROJECT',self.root))
        self.stack.enter_context(patch.object(repair,'__file__',str(self.root/'python/revalidar_simz1.py')))
        self.stack.enter_context(patch.object(repair,'POSTPROCESS_BASE_FINGERPRINT',self.base_fingerprint))
        self.stack.enter_context(patch.object(repair,'STEP_FORMAT_EXECUTION_FINGERPRINT',self.native_fingerprint))
        self.stack.enter_context(patch.object(repair,'STEP_FORMAT_TRANSITIONS',copy.deepcopy(self.transitions)))
        self.stack.enter_context(patch('simz1_balanced_od_audit.implementation_signature',side_effect=self.signature))

        requested=self.run/'config.xml';effective=self.run/'output-config.xml'
        requested.write_text('<config><module name="qsim"><param name="timeStepSize" value="1"/>'
            '<param name="endTime" value="86399"/></module></config>')
        effective.write_text(requested.read_text().replace('value="1"','value="00:00:01"'))
        signed=self.signature()
        for name,pair in self.transitions.items():signed['source_sha256'][name]=pair['before']
        code=self.run/'implementation.json';atomic_json(code,signed)
        message=repair.STEP_FORMAT_ERROR
        trace=(f'Traceback (most recent call last):\n  File "{self.root / "python/simz1_run.py"}", line 349, in validate_outputs\n'
            '    balanced_od = validate_balanced_od(directory, manifest)\n'
            f'  File "{self.root / "python/simz1_balanced_od_audit.py"}", line 167, in validate_manifest\n'
            "    float(config.get('qsim.timeStepSize','1'))!=1):raise ValueError('Native fixed-day boundary contract mismatch')\n"
            f'ValueError: {message}\n')
        original=dict(schema_version=1,folder=str(self.run),run_id='simz1-fixture-only',launch_id='a'*32,
            status='failed',phase='validating',failure_phase='validating',failure_category='output_validation_error',
            exception_type='ValueError',error=message,exception_traceback=trace,
            validation=dict(status='invalid',error=message),returncode=0,returncode_origin='natural_exit',
            inputs=dict(config=artifact(self.run,requested),implementation=artifact(self.run,code)),
            effective_config=artifact(self.run,effective),balanced_od=dict(implementation=artifact(self.run,code)),
            experiment=dict(observation_policy='fixed-day-24h-v1',native_qsim_end_seconds=86399,observation_end_seconds=86400),
            time_horizon=dict(start_seconds=0,end_seconds=86400),iterations=dict(first=0,last=0,requested=1,completed=[0]),
            last_completed_step=dict(seconds=86400,source='native_after_step_log'))
        self.launch=self.root/'runtime/launches'/original['launch_id']/'state.json'
        atomic_json(self.launch,dict(launch_id=original['launch_id'],run_id=original['run_id'],
            run_directory=str(self.run),source_fingerprint=self.native_fingerprint,dry_run=False,status='failed'))
        backup=self.run/'validation-history/original.json';atomic_json(backup,original)
        context=repair._step_format_context(self.run,original)
        native_hashes={r['path']:r['sha256'] for r in original['inputs'].values()}
        native_hashes[original['effective_config']['path']]=original['effective_config']['sha256']
        receipt=dict(operation=repair.STEP_FORMAT_OPERATION,version=repair.REPAIR_VERSION,
            execution_repeated=False,native_artifacts_modified=False,original_manifest=backup.relative_to(self.run).as_posix(),
            original_manifest_sha256=repair.sha256(backup),native_artifacts_sha256=native_hashes,
            validator_sources={name:self.base['python/'+name] for name in repair.VALIDATOR_SOURCES},**context)
        self.saved=dict(original,status='completed',validation=dict(status='valid'),revalidation=receipt)
        atomic_json(self.run/repair.MANIFEST,self.saved)
        changes={}
        for name in ('python/simz1_run.py','python/simz1_balanced_od_audit.py','python/generate_montecarlo_z1.py'):
            self.write(name,(self.root/name).read_bytes()+b'# reviewed postprocessor\n')
            changes[name]=dict(before=self.base[name],after=repair.sha256(self.root/name))
        self.added='python/test_simz1_blocking_occupancy_single_queue.py'
        self.write(self.added,b'# fixture new negative regression\n')
        self.policy=dict(schema='simz1-run1000-postprocessing-compatibility-v1',
            base_source_fingerprint=self.base_fingerprint,native_source_fingerprint=self.native_fingerprint,
            run_id=self.saved['run_id'],manifest_sha256=repair.sha256(self.run/repair.MANIFEST),
            base_file_count=len(self.base),changes=changes,additions={self.added:repair.sha256(self.root/self.added)},
            previous_native_changes={'python/'+name:pair for name,pair in self.transitions.items()})
        self.policy_path=self.root/repair.POSTPROCESS_POLICY;atomic_json(self.policy_path,self.policy)
        # Explicit fixture inventory contains every synthetic source/input and
        # the new policy. fingerprint() itself remains the real production code.
        self.inventory=set(self.source_names)|{self.added,repair.POSTPROCESS_POLICY}
        def inventory(root):
            self.assertEqual(Path(root).resolve(),self.root)
            return sorted(self.root/name for name in self.inventory)
        self.stack.enter_context(patch.object(workflow,'fingerprint_files',side_effect=inventory))

    @staticmethod
    def hash_bytes(raw):return hashlib.sha256(raw).hexdigest()

    def write(self,name,raw):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

    def digest(self,records):
        digest=hashlib.sha256()
        for path in sorted(self.root/name for name in records):
            name=path.relative_to(self.root).as_posix()
            digest.update(name.encode()+b'\0'+records[name].encode()+b'\n')
        return digest.hexdigest()

    def signature(self):
        return dict(version='balanced-gateway-v1',sequence_contract_sha256='c'*64,
            source_sha256={name:repair.sha256(self.root/'python'/name)
                           for name in (*self.transitions,'generate_montecarlo_z1.py')})

    def files(self):return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def proof(self):return repair.reviewed_postprocessing_revision(self.run,self.saved)

    def publish_policy(self,policy=None):atomic_json(self.policy_path,self.policy if policy is None else policy)

    def test_complete_fingerprints_restored_read_only_without_live_exclusions(self):
        before=self.files();proof=self.proof()
        self.assertEqual(proof['reconstructed_base_fingerprint'],self.base_fingerprint)
        self.assertEqual(proof['reconstructed_native_fingerprint'],self.native_fingerprint)
        self.assertEqual(proof['historical_sources'],self.base)
        self.assertEqual(proof['current_source_fingerprint'],self.workflow.fingerprint(self.root))
        self.assertNotEqual(proof['current_source_fingerprint'],self.base_fingerprint)
        self.assertEqual(before,self.files())

    def test_java_and_physical_input_mutations_or_absence_are_rejected(self):
        for name in ('src/main/java/Physical.java','scenarios/zona1/network.xml'):
            path=self.root/name;original=path.read_bytes()
            for absent in (False,True):
                with self.subTest(name=name,absent=absent):
                    if absent:path.unlink()
                    else:path.write_bytes(original+b'changed physical behavior')
                    with self.assertRaises(ValueError):self.proof()
                    path.write_bytes(original)

    def test_live_extra_source_and_missing_inventory_member_are_rejected(self):
        name='python/extra_unreviewed.py';self.write(name,b'new source');self.inventory.add(name)
        with self.assertRaisesRegex(ValueError,'baseline fingerprint'):self.proof()
        self.inventory.remove(name)
        for name in ('python/simz1_run.py','src/main/java/Physical.java',self.added,repair.POSTPROCESS_POLICY):
            with self.subTest(omitted=name):
                self.inventory.remove(name)
                with self.assertRaises(ValueError):self.proof()
                self.inventory.add(name)

    def test_exact_after_and_added_file_hashes_are_required(self):
        for name in ('python/simz1_run.py','python/generate_montecarlo_z1.py',self.added):
            path=self.root/name;original=path.read_bytes()
            for absent in (False,True):
                with self.subTest(name=name,absent=absent):
                    if absent:path.unlink()
                    else:path.write_bytes(original+b'mutation')
                    with self.assertRaises(ValueError):self.proof()
                    path.write_bytes(original)

    def test_policy_identity_schema_pairs_counts_and_native_chain_are_exact(self):
        mutations=[]
        for key,value in [('schema','other'),('base_source_fingerprint','0'*64),('native_source_fingerprint','0'*64),
                          ('run_id','other-run'),('manifest_sha256','0'*64),('base_file_count',len(self.base)+1)]:
            p=copy.deepcopy(self.policy);p[key]=value;mutations.append((key,p))
        for stage in ('changes','previous_native_changes'):
            for side in ('before','after'):
                p=copy.deepcopy(self.policy);p[stage]['python/simz1_run.py'][side]='0'*64
                mutations.append((stage+' '+side,p))
        p=copy.deepcopy(self.policy);p['unexpected_field']=True;mutations.append(('extra policy field',p))
        p=copy.deepcopy(self.policy);p['changes']={};mutations.append(('no changes',p))
        p=copy.deepcopy(self.policy);p['previous_native_changes']={};mutations.append(('no chain',p))
        p=copy.deepcopy(self.policy);p['additions'][self.added]='0'*64;mutations.append(('addition sha',p))
        p=copy.deepcopy(self.policy);p['additions']['python/simz1_run.py']='0'*64;mutations.append(('overlap',p))
        for name,p in mutations:
            with self.subTest(mutation=name):
                self.publish_policy(p)
                with self.assertRaises(ValueError):self.proof()
        self.publish_policy()

    def test_whitelisted_scope_never_expands_to_java_or_physical_input(self):
        for name in ('src/main/java/Physical.java','scenarios/zona1/network.xml'):
            with self.subTest(name=name):
                path=self.root/name;original=path.read_bytes();path.write_bytes(original+b'mutation')
                policy=copy.deepcopy(self.policy)
                policy['changes'][name]=dict(before=self.base[name],after=repair.sha256(path))
                self.publish_policy(policy)
                with self.assertRaisesRegex(ValueError,'scope'):self.proof()
                path.write_bytes(original)
        self.publish_policy()

    def test_absent_policy_and_changed_manifest_or_supplied_identity_reject(self):
        original=self.policy_path.read_bytes();self.policy_path.unlink()
        with self.assertRaisesRegex(ValueError,'policy absent'):self.proof()
        self.policy_path.write_bytes(original)
        manifest_path=self.run/repair.MANIFEST;original=manifest_path.read_bytes()
        manifest_path.write_bytes(original+b'\n')
        with self.assertRaisesRegex(ValueError,'identity/policy'):self.proof()
        manifest_path.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'identity/policy'):
            repair.reviewed_postprocessing_revision(self.run,dict(self.saved,run_id='different'))

    def test_indirect_policy_is_rejected_without_reading_target(self):
        original_is_symlink=Path.is_symlink
        with patch.object(Path,'is_symlink',lambda p: p==self.policy_path or original_is_symlink(p)):
            with self.assertRaisesRegex(ValueError,'policy absent or indirect'):self.proof()

    def test_opt_in_composes_only_reviewed_transitions_without_changing_receipt(self):
        before=self.files()
        with patch.object(repair,'reviewed_postprocessing_revision',wraps=repair.reviewed_postprocessing_revision) as checked:
            for kwargs in ({},{'allow_reviewed_postprocessing':False}):
                with self.subTest(opt_in=kwargs),self.assertRaises(ValueError):
                    repair.recovery_compatibility(self.run,self.saved,**kwargs)
                checked.assert_not_called()
            compatibility=repair.recovery_compatibility(self.run,self.saved,allow_reviewed_postprocessing=True)
            checked.assert_called_once()
        self.assertEqual(compatibility['schema'],'fixed-day-preparation-identity-audit-v1')
        self.assertEqual(set(compatibility['transitions']),set(self.transitions)|{'generate_montecarlo_z1.py'})
        for name,pair in compatibility['transitions'].items():
            expected_before = (self.base['python/'+name] if name == 'generate_montecarlo_z1.py'
                               else self.transitions[name]['before'])
            self.assertEqual(pair['before'],expected_before)
            self.assertEqual(pair['after'],self.signature()['source_sha256'][name])
        self.assertEqual(self.saved['revalidation']['implementation_compatibility']['schema'],repair.STEP_FORMAT_SCHEMA)
        self.assertEqual(before,self.files())

    def test_preparation_compatibility_requires_exact_version_and_source_pairs(self):
        from simz1_balanced_od_audit import validate_implementation_signature
        compatibility=repair.recovery_compatibility(self.run,self.saved,allow_reviewed_postprocessing=True)
        current=self.signature()
        original=self.saved['revalidation']['original_implementation_signature']
        validate_implementation_signature(original,current,compatibility)
        mutations=[]
        for schema in ('fixed-day-postprocessing-audit-v1','fixed-day-step-time-format-v1','other'):
            bad=copy.deepcopy(compatibility);bad['schema']=schema;mutations.append(bad)
        for side in ('before','after'):
            bad=copy.deepcopy(compatibility)
            bad['transitions']['generate_montecarlo_z1.py'][side]='0'*64;mutations.append(bad)
        bad=copy.deepcopy(compatibility);del bad['transitions']['generate_montecarlo_z1.py'];mutations.append(bad)
        bad=copy.deepcopy(compatibility);bad['transitions']['simz1_population.py']=dict(before='1'*64,after='2'*64);mutations.append(bad)
        for bad in mutations:
            with self.subTest(compatibility=bad),self.assertRaises(ValueError):
                validate_implementation_signature(original,current,bad)
        for side in ('saved','current'):
            changed=copy.deepcopy(original if side=='saved' else current)
            changed['source_sha256']['generate_montecarlo_z1.py']='0'*64
            with self.subTest(signature=side),self.assertRaises(ValueError):
                validate_implementation_signature(changed if side=='saved' else original,
                                                 changed if side=='current' else current,compatibility)

    def test_opt_in_preserves_original_receipt_and_native_identity_checks(self):
        for key,value in [('execution_repeated',True),('native_artifacts_modified',True),('version','other'),
                          ('implementation_compatibility',{}),('native_execution',{}),
                          ('validator_implementation_signature',{}),('validator_sources',{}),('native_artifacts_sha256',{})]:
            with self.subTest(receipt_field=key):
                bad=copy.deepcopy(self.saved);bad['revalidation'][key]=value
                atomic_json(self.run/repair.MANIFEST,bad)
                p=copy.deepcopy(self.policy);p['manifest_sha256']=repair.sha256(self.run/repair.MANIFEST);self.publish_policy(p)
                with self.assertRaises(ValueError):
                    repair.recovery_compatibility(self.run,bad,allow_reviewed_postprocessing=True)
        atomic_json(self.run/repair.MANIFEST,self.saved);self.publish_policy()
        for key in repair.NATIVE_IDENTITY_FIELDS:
            with self.subTest(native_identity=key):
                bad=copy.deepcopy(self.saved);bad[key]='changed-native-identity'
                with self.assertRaises(ValueError):
                    repair.recovery_compatibility(self.run,bad,allow_reviewed_postprocessing=True)

    def test_current_validate_receipt_binds_full_policy_bytes_and_all_sources(self):
        original_fingerprint=self.workflow.fingerprint
        receipt=self.root/'runtime/workflow/validated-balanced-gateway-v1.json'
        atomic_json(receipt,dict(status='integrated_validate_pass',od_mode='balanced-gateway-v1',
            source_fingerprint=original_fingerprint(self.root)))
        with patch.object(self.workflow,'fingerprint',side_effect=lambda:original_fingerprint(self.root)):
            self.workflow.require_balanced_validation()
            # Semantically identical JSON is still part of the live fingerprint.
            self.policy_path.write_bytes(self.policy_path.read_bytes()+b'\n')
            self.proof()
            with self.assertRaisesRegex(ValueError,'Falta Validate'):self.workflow.require_balanced_validation()
            self.publish_policy()
            self.workflow.require_balanced_validation()
            receipt.unlink()
            with self.assertRaises(FileNotFoundError):self.workflow.require_balanced_validation()


if __name__ == '__main__':
    unittest.main()
