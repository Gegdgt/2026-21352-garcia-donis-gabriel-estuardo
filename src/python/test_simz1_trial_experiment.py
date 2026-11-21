"""Small contract regressions: no generation, Validate, DryRun or QSim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
import sys
import contextlib
import io
import xml.etree.ElementTree as ET
from unittest.mock import patch

import simz1_scale_contract as contract
import simz1_workflow_state as workflow

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT/'scenarios/zona1/experiments/final-20261104-24h-v3.json'


class FixedDayStepRepresentationTests(unittest.TestCase):
    """Exercise the real manifest boundary guard before expensive network I/O."""
    def check_boundary(self, step, *, values=None):
        import simz1_balanced_od_audit as audit
        from simz1_day_observation import policy_document
        from simz1_run import artifact

        class BoundaryAccepted(Exception):
            pass

        selected = contract.experiment(SPEC, 'run1000')
        values = dict(values or {'qsim.endTime':'23:59:59',
                               'simz1Observation.policy':selected['observation_policy']})
        values['qsim.timeStepSize'] = step
        with tempfile.TemporaryDirectory(prefix='fixed-day-step-') as td:
            folder = Path(td)
            root = ET.Element('config'); modules = {}
            for key, value in values.items():
                module, name = key.split('.', 1)
                if module not in modules: modules[module] = ET.SubElement(root, 'module', name=module)
                ET.SubElement(modules[module], 'param', name=name, value=str(value))
            config = folder/'config.xml'
            ET.ElementTree(root).write(config, encoding='utf-8')
            implementation = folder/'implementation.json'
            implementation.write_text(json.dumps(audit.implementation_signature()), encoding='utf-8')
            specification = folder/'specification.json'; specification.write_bytes(SPEC.read_bytes())
            policy = folder/'day-policy.json'
            policy.write_text(json.dumps(policy_document()), encoding='utf-8')
            manifest = dict(
                balanced_od=dict(variant=audit.VARIANT, implementation=artifact(folder, implementation)),
                spatial_demand=dict(mode=audit.VARIANT), experiment=selected,
                demand_composition=dict(total_non_public_vehicles=1000),
                temporal_demand=dict(demand_window=dict(start_seconds=0,end_seconds=86400,end_exclusive=True),
                                     observation_policy=selected['observation_policy']),
                inputs={'config':artifact(folder,config),
                        'input:experiment-specification.json':artifact(folder,specification),
                        'input:day-observation-policy.json':artifact(folder,policy)})
            # This sentinel proves only that the temporal guard accepts/rejects
            # the real XML parameters. It never approves a complete run.
            with patch.object(audit, 'check_config', side_effect=BoundaryAccepted):
                try:
                    audit.validate_manifest(folder, manifest)
                except BoundaryAccepted:
                    return True
        self.fail('Temporal guard did not reach the next validation stage')

    def test_numeric_one_second_is_accepted(self):
        self.assertTrue(self.check_boundary('1'))

    def test_native_clock_one_second_is_accepted(self):
        self.assertTrue(self.check_boundary('00:00:01'))

    def test_two_seconds_remains_rejected(self):
        for value in ('2', '00:00:02'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.check_boundary(value)

    def test_zero_seconds_remains_rejected(self):
        for value in ('0', '00:00:00'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.check_boundary(value)

    def test_malformed_step_remains_rejected(self):
        for value in ('', 'not-a-time', '00:00', '00:00:01:00'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.check_boundary(value)

    def test_nonfinite_step_remains_rejected(self):
        for value in ('nan', 'inf', '-inf', '00:00:nan', '00:00:inf'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.check_boundary(value)


class ImplementationCompatibilityTests(unittest.TestCase):
    def setUp(self):
        from simz1_balanced_od_audit import validate_implementation_signature
        self.validate = validate_implementation_signature
        names = ('simz1_balanced_od_audit.py','simz1_run.py','simz1_temporal_passage.py')
        self.old = dict(version='balanced-gateway-v1',sequence_contract_sha256='c'*64,
                        source_sha256={**dict.fromkeys(names,'a'*64),'unchanged.py':'d'*64})
        self.new = copy.deepcopy(self.old)
        for name in names:self.new['source_sha256'][name] = 'b'*64
        self.proof = dict(schema='fixed-day-step-time-format-v1',
                          transitions={name:dict(before='a'*64,after='b'*64) for name in names})

    def test_default_requires_exact_equality(self):
        self.validate(self.old,copy.deepcopy(self.old))
        with self.assertRaisesRegex(ValueError,'fingerprints differ'):self.validate(self.old,self.new)

    def test_only_explicit_exact_three_transitions_are_accepted(self):
        self.validate(self.old,self.new,self.proof)
        self.assertEqual(self.old['source_sha256']['simz1_run.py'],'a'*64)

    def test_missing_additional_and_unknown_compatibility_rejected(self):
        variants=[]
        value=copy.deepcopy(self.proof);value['transitions'].pop('simz1_run.py');variants.append(value)
        value=copy.deepcopy(self.proof);value['transitions']['unchanged.py']=dict(before='d'*64,after='e'*64);variants.append(value)
        value=copy.deepcopy(self.proof);value['schema']='another-repair';variants.append(value)
        value=copy.deepcopy(self.proof);value['allow_anything']=True;variants.append(value)
        for value in variants:
            with self.subTest(proof=value),self.assertRaises(ValueError):self.validate(self.old,self.new,value)

    def test_wrong_before_after_and_malformed_hashes_rejected(self):
        for key,value in [('before','f'*64),('after','f'*64),('before','short'),
                          ('after',None),('before','A'*64),('after','a'*64)]:
            proof=copy.deepcopy(self.proof);proof['transitions']['simz1_run.py'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.validate(self.old,self.new,proof)

    def test_other_sources_version_and_sequence_remain_bound(self):
        variants=[]
        value=copy.deepcopy(self.new);value['source_sha256']['unchanged.py']='e'*64;variants.append(value)
        value=copy.deepcopy(self.new);value['source_sha256'].pop('unchanged.py');variants.append(value)
        value=copy.deepcopy(self.new);value['source_sha256']['extra.py']='e'*64;variants.append(value)
        value=copy.deepcopy(self.new);value['version']='other-version';variants.append(value)
        value=copy.deepcopy(self.new);value['sequence_contract_sha256']='e'*64;variants.append(value)
        for value in variants:
            with self.subTest(signature=value),self.assertRaises(ValueError):self.validate(self.old,value,self.proof)

    def test_recovery_keyword_cannot_enable_postprocessing_bypass(self):
        import simz1_balanced_od_audit as audit
        from simz1_run import artifact
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);saved=folder/'implementation.json'
            saved.write_text(json.dumps(self.old),encoding='utf-8')
            manifest=dict(balanced_od=dict(variant=audit.VARIANT,implementation=artifact(folder,saved)),
                          spatial_demand=dict(mode=audit.VARIANT))
            with self.assertRaisesRegex(ValueError,'postprocessing bypass'):
                audit.validate_manifest(folder,manifest,postprocessing=True,implementation_compatibility=self.proof)


class TrialExperimentTests(unittest.TestCase):
    def manifest_selection_fixture(self, selected):
        # In-memory identity fixture only; never native completed/valid evidence.
        counts=contract.require_scale(selected['total_non_public_vehicles'],selected['demand_seed'],
            selected['iterations'],selected['specification_path'],selected['scenario'])
        return dict(experiment=dict(selected,initial_population_sha256='a'*64,
                population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization'),
            inputs={'plans':dict(path='plans.xml',sha256='a'*64)},
            iterations=dict(first=0,last=selected['iterations']-1,requested=selected['iterations'],completed=[]),
            demand_seed=selected['demand_seed'],matsim_seed=selected['demand_seed'],
            counts=dict(public_transport_vehicles_configured=269),
            demand_composition=dict(total_non_public_vehicles=selected['total_non_public_vehicles'],
                family_counts={k:counts[k] for k in ('carro','moto','pesado')}),
            spatial_demand=dict(mode='balanced-gateway-v1'))

    def test_manifest_identity_uses_authorized_iteration_count_without_running_full10(self):
        selected=contract.experiment(SPEC,'full-10')
        native=self.manifest_selection_fixture(selected)
        for completed in ([],[0],[0,1,2],list(range(10))):
            with self.subTest(completed=completed):
                native['iterations']['completed']=completed
                contract.validate_manifest_selection(native,selected)
        self.assertNotIn('status',native)
        self.assertNotIn('validation',native)

    def test_manifest_rejects_wrong_authorized_range_and_noncontiguous_completion(self):
        cases=[contract.experiment(SPEC,'full-10'),contract.experiment(SPEC,'run1000'),
               contract.experiment(ROOT/contract.DIAGNOSTIC_SPEC,'run10000')]
        for selected in cases:
            native=self.manifest_selection_fixture(selected)
            expected_count=selected['iterations']
            changes=[('first',1),('last',expected_count),('requested',expected_count+1),
                     ('completed',[expected_count]),('completed',[0,0]),('completed',[0,2]),
                     ('completed',[True]),('completed',[0.0])]
            for key,value in changes:
                changed=copy.deepcopy(native);changed['iterations'][key]=value
                with self.subTest(selector=selected['scenario'],field=key,value=value),self.assertRaises(ValueError):
                    contract.validate_manifest_selection(changed,selected)

    def test_explicit_trial_is_same_day_base(self):
        trial = contract.experiment(SPEC, 'run1000')
        full = contract.experiment(SPEC, 'full-1')
        self.assertEqual((trial['total_non_public_vehicles'], trial['iterations']), (1000, 1))
        self.assertEqual((full['total_non_public_vehicles'], full['iterations']), (204186, 1))
        for key in ('base_scenario_identity', 'base_inputs', 'demand_seed', 'service_date',
                    'public_vehicles', 'observation_policy', 'observation_end_seconds',
                    'native_qsim_end_seconds', 'signal_variant'):
            self.assertEqual(trial[key], full[key], key)
        self.assertEqual(trial['public_vehicles'], 269)
        self.assertEqual(contract.require_scale(1000, experiment_spec=SPEC, experiment_scenario='run1000'),
                         dict(carro=440, moto=550, pesado=10, public_transport=269))

    def test_historical_selectors_preserved_and_provenance(self):
        new = json.loads(SPEC.read_bytes())
        old_path = ROOT/new['derived_from']['path']
        old = json.loads(old_path.read_bytes())
        self.assertEqual(new['derived_from']['sha256'], workflow.sha(old_path))
        self.assertEqual(new['draw'], old['draw'])
        for key, value in old['scenarios'].items():
            self.assertEqual(new['scenarios'][key], value)
        self.assertNotIn('run1000', old['scenarios'])

    def test_mutated_or_missing_base_is_rejected(self):
        doc = json.loads(SPEC.read_bytes())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'mutation.json'
            for change in ('seed', 'size', 'policy', 'input', 'provenance'):
                value = copy.deepcopy(doc)
                if change == 'seed': value['demand_seed'] = 1
                if change == 'size': value['scenarios']['full-1']['total_non_public_vehicles'] = 220000
                if change == 'policy': value['native_qsim_end_seconds'] = 86400
                if change == 'input': value['base_inputs']['source_config'] = 'scenarios/zona1/config-simz1.xml'
                if change == 'provenance': value['derived_from']['sha256'] = '0'*64
                path.write_text(json.dumps(value))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    contract.experiment(path, 'full-1')
        with patch.object(Path, 'is_file', return_value=False), self.assertRaises(ValueError):
            contract.base_identity(doc)

    def test_trial_identity_requires_native_day_and_balanced_experiment(self):
        trial = contract.experiment(SPEC, 'run1000')
        m = dict(experiment=trial, time_horizon=dict(start_seconds=0, end_seconds=86400),
                 iterations=dict(first=0,last=0,requested=1,completed=[0]),
                 demand_seed=20261023, matsim_seed=20261023)
        identity = dict(od_mode='balanced-gateway-v1')
        self.assertEqual(workflow.trial_experiment_identity(m, identity), trial['base_scenario_identity'])
        for variant in (dict(m, experiment=None), dict(m, experiment=contract.experiment(SPEC, 'full-1')),
                        dict(m, time_horizon=dict(start_seconds=0,end_seconds=108000)), dict(m, matsim_seed=7),
                        dict(m,iterations=dict(first=0,last=9,requested=10,completed=[0,9]))):
            with self.assertRaises(ValueError): workflow.trial_experiment_identity(variant, identity)
        with self.assertRaises(ValueError): workflow.trial_experiment_identity(m, dict(od_mode='network'))

    def test_trial_receipt_cannot_approve_different_base_or_revision(self):
        full = contract.experiment(SPEC, 'full-1')
        current = dict(run_id='fixture-only',manifest_sha256='fixture',quality_sha256='fixture',
                       base_scenario_identity=full['base_scenario_identity'])
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)/'fixture.json'
            state.write_text(json.dumps(dict(current,run_directory=td,source_fingerprint='fixture-revision')))
            argv = ['require-trial','--state',str(state),'--experiment-spec',str(SPEC),'--experiment-scenario','full-1']
            for revision, identity, code in [('fixture-revision',full['base_scenario_identity'],0),
                                            ('other-revision',full['base_scenario_identity'],1),
                                            ('fixture-revision',None,1),('fixture-revision','other-base',1)]:
                with self.subTest(revision=revision,identity=identity), patch.object(workflow,'fingerprint',return_value=revision), \
                     patch.object(workflow,'inspect',return_value=dict(current,base_scenario_identity=identity)), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(workflow.main(argv), code)

    def test_base_inputs_reject_generic_catalog_config_freight_and_missing(self):
        selected = contract.experiment(SPEC, 'run1000')
        inputs = {k: ROOT/v for k,v in selected['base_inputs'].items()}
        contract.require_base_inputs(selected, **inputs)
        for key, value in [('source_config',ROOT/'scenarios/zona1/config-simz1.xml'),
                           ('agent_catalog',ROOT/'scenarios/zona1/agent-types-nonpublic-v1.json'),
                           ('freight_service',ROOT/'scenarios/zona1/freight/weekday-v2/service-composition-v2.json'),
                           ('transit_service',None)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.require_base_inputs(selected, **dict(inputs, **{key:value}))

    def test_preflight_rejects_contradictions_before_network_or_generation(self):
        from simz1_experiment_preflight import check
        with patch('simz1_experiment_preflight.audit_configuration', side_effect=AssertionError('must reject before network IO')):
            for kwargs in [dict(od_mode='network'), dict(od_mode='balanced-gateway-v1')]:
                with self.assertRaises(ValueError):
                    check(ROOT/'scenarios/zona1/config-simz1.xml', ROOT/'scenarios/zona1/agent-types-nonpublic-v1.json',
                          1000,1000,'uniform-nodes-v1','strict-receiver-v1',experiment_spec=SPEC,
                          experiment_scenario='run1000', **kwargs)

    def test_missing_and_mutated_contract_and_inputs_bind_fingerprint(self):
        original_sha = workflow.sha
        original_is_file = Path.is_file
        baseline = workflow.fingerprint()
        for relative in [contract.TRIAL_SPEC, *contract.BASE_INPUTS.values()]:
            target = ROOT/relative
            with self.subTest(file=relative), patch.object(workflow, 'sha', side_effect=lambda p: '0'*64 if Path(p)==target else original_sha(p)):
                self.assertNotEqual(workflow.fingerprint(), baseline)
            with self.subTest(missing=relative), patch.object(Path, 'is_file', lambda p: False if p==target else original_is_file(p)):
                with self.assertRaises(ValueError): workflow.fingerprint()


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class TrialLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='trial contract ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scripts = self.root/'scripts'; self.scripts.mkdir()
        for name in ('run_simz1_with_analysis.ps1','run_simz1_180k_balanced_gateway.ps1',
                     'check_simz1_110k_balanced_gateway.ps1','simz1_workflow.ps1',
                     'simz1_launch_contract.ps1','run_massive_z1_pasante_10it.ps1'):
            shutil.copyfile(ROOT/'scripts'/name,self.scripts/name)

    def ps(self, source):
        script = self.root/'test.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n"+source,encoding='utf-8-sig')
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],
                              cwd=self.root,capture_output=True,text=True,timeout=30)

    def test_implicit_pipeline_and_incomplete_selector_never_reach_tools(self):
        for invocation in ('run_simz1_with_analysis.ps1', 'run_simz1_180k_balanced_gateway.ps1 -Run',
                           'check_simz1_110k_balanced_gateway.ps1 -Action Run1000',
                           'simz1_workflow.ps1 -Action RunMassive'):
            with self.subTest(invocation=invocation):
                r = self.ps('& ./scripts/'+invocation)
                self.assertNotEqual(r.returncode,0,r.stdout)
                self.assertIn('Experiment',r.stderr)
        self.assertFalse((self.root/'runtime').exists())

    def test_direct_pipeline_even_with_spec_cannot_bypass_owner_and_gates(self):
        r = self.ps("$env:SIMZ1_LAUNCH_DIRECTORY=$null\n& ./scripts/run_simz1_with_analysis.ps1 -ExperimentSpec '"+str(SPEC)+"' -ExperimentScenario full-1 -OdMode balanced-gateway-v1")
        self.assertNotEqual(r.returncode,0)
        self.assertIn('launch owner',r.stderr)
        self.assertFalse((self.root/'runtime').exists())

    def test_trial_dryrun_routes_same_selector_without_run(self):
        (self.scripts/'run_simz1_180k_balanced_gateway.ps1').write_text("""param($ExperimentSpec,$ExperimentScenario,$JavaHome,$ZoneBoundary,$OdAccessCatalog,$OdMixFile,[switch]$Run,[switch]$DryRun)
$PSBoundParameters | ConvertTo-Json | Set-Content -Encoding UTF8 captured.json
if ($Run -or -not $DryRun) { throw 'Not a dry request' }
exit 3
""",encoding='utf-8')
        r = self.ps("& ./scripts/check_simz1_110k_balanced_gateway.ps1 -Action Run1000 -ExperimentSpec '"+str(SPEC)+"' -DryRun\nexit $LASTEXITCODE")
        self.assertEqual(r.returncode,3,r.stderr)
        captured=json.loads((self.root/'captured.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(captured['ExperimentScenario'],'run1000')
        self.assertEqual(captured['ExperimentSpec'],str(SPEC))
        self.assertTrue(captured['DryRun']['IsPresent'])
        self.assertNotIn('Run',captured)

    def test_trial_run_forwards_explicit_dryrun_identity_without_starting_native_tools(self):
        (self.scripts/'run_simz1_180k_balanced_gateway.ps1').write_text("""param($ExperimentSpec,$ExperimentScenario,$JavaHome,$ZoneBoundary,$OdAccessCatalog,$OdMixFile,$DryRunLaunchId,[switch]$Run,[switch]$DryRun)
$PSBoundParameters | ConvertTo-Json | Set-Content -Encoding UTF8 captured.json
if (-not $Run -or $DryRun -or $DryRunLaunchId -cne ('a'*32)) { throw 'Lost explicit Run preparation identity' }
exit 3
""",encoding='utf-8')
        r=self.ps("& ./scripts/check_simz1_110k_balanced_gateway.ps1 -Action Run1000 -ExperimentSpec '"+str(SPEC)+"' -DryRunLaunchId "+'a'*32+"\nexit $LASTEXITCODE")
        self.assertEqual(r.returncode,3,r.stdout+r.stderr)
        captured=json.loads((self.root/'captured.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(captured['DryRunLaunchId'],'a'*32)
        self.assertEqual(captured['ExperimentScenario'],'run1000')
        self.assertTrue(captured['Run']['IsPresent'])
        self.assertNotIn('DryRun',captured)
        self.assertFalse((self.root/'runtime').exists())

    def test_trial_missing_dryrun_identity_rejected_before_selection_or_native_tools(self):
        for launch_id in (None,''):
            with self.subTest(launch_id=launch_id), \
                    patch('simz1_scale_contract.experiment',side_effect=AssertionError('No selection work before missing-ID rejection')), \
                    self.assertRaisesRegex(ValueError,'Run requires an explicit DryRun LaunchId'):
                workflow.require_experiment_dry_run(SPEC,'run1000',launch_id)
        self.assertFalse((self.root/'runtime').exists())

    def test_first_scale_rejected_for_version_with_trial(self):
        r = self.ps("""
. ./scripts/simz1_launch_contract.ps1
$o=@{FirstScaleTrial=$true;ExperimentSchema='simz1-final-experiments-v3';MinAgents=204186;MaxAgents=204186;Iterations=1;Seed=20261023;OdMode='balanced-gateway-v1'}
try { $null=Test-SimZ1FirstScaleTrial $o } catch { if ($_.Exception.Message -match 'versioned run1000') {exit 0}; throw }
throw 'Accepted bypass'
""")
        self.assertEqual(r.returncode,0,r.stderr)

    def test_live_owner_cannot_turn_preflight_into_run_or_change_selector(self):
        r = self.ps("""
. ./scripts/simz1_launch_contract.ps1
$env:SIMZ1_LAUNCH_ID='b'*32
$env:SIMZ1_LAUNCH_DIRECTORY=Join-Path $PWD ('runtime/launches/'+$env:SIMZ1_LAUNCH_ID)
$null=New-Item -ItemType Directory $env:SIMZ1_LAUNCH_DIRECTORY -Force
$owner=Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
$env:SIMZ1_LAUNCH_PID=[string]$PID
$env:SIMZ1_LAUNCH_CREATED_UTC=$owner.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
$planned=Join-Path $PWD 'inert-no-run-created'
$spec=Join-Path $PWD 'fixture-spec.json'
[IO.File]::WriteAllText($spec,'fixture-only-not-an-executable-experiment')
$state=@{launch_id=$env:SIMZ1_LAUNCH_ID;phase='configuration_preflight';run_directory=$planned;run_launch_eligible=$false;
 process=@{pid=$PID;created_utc=$env:SIMZ1_LAUNCH_CREATED_UTC;executable=$owner.ExecutablePath;command=$owner.CommandLine}}
$request=@{launch_id=$env:SIMZ1_LAUNCH_ID;run_directory=$planned;minimum_non_public_vehicles=1000;maximum_non_public_vehicles=1000;demand_seed=20261023;iterations=1;
 experiment=@{scenario='run1000';base_scenario_identity='fixture';specification_sha256=(Get-FileHash $spec).Hash.ToLowerInvariant()}}
$state|ConvertTo-Json -Depth 5|Set-Content -Encoding UTF8 (Join-Path $env:SIMZ1_LAUNCH_DIRECTORY 'state.json')
$request|ConvertTo-Json -Depth 5|Set-Content -Encoding UTF8 (Join-Path $env:SIMZ1_LAUNCH_DIRECTORY 'request.json')
$args=@{Project=$PWD.Path;DryRun=$true;ExperimentSpec=$spec;ExperimentScenario='run1000';NewRunDir=$planned;MinAgents=1000;MaxAgents=1000;Seed=20261023;Iterations=1}
Assert-SimZ1PipelineOwner @args
$args.DryRun=$false
try {Assert-SimZ1PipelineOwner @args;throw 'accepted preflight as Run'} catch {if($_.Exception.Message -notmatch 'pipeline phase'){throw}}
$args.DryRun=$true;$args.ExperimentScenario='full-1'
try {Assert-SimZ1PipelineOwner @args;throw 'accepted another selector'} catch {if($_.Exception.Message -notmatch 'request differs'){throw}}
$args.ExperimentScenario='run1000';$args.Seed=7
try {Assert-SimZ1PipelineOwner @args;throw 'accepted another seed'} catch {if($_.Exception.Message -notmatch 'request differs'){throw}}
$args.Seed=20261023
$state.process.created_utc='2000-01-01T00:00:00.000Z';$env:SIMZ1_LAUNCH_CREATED_UTC=$state.process.created_utc
$state|ConvertTo-Json -Depth 5|Set-Content -Encoding UTF8 (Join-Path $env:SIMZ1_LAUNCH_DIRECTORY 'state.json')
try {Assert-SimZ1PipelineOwner @args;throw 'accepted reused PID'} catch {if($_.Exception.Message -notmatch 'PID was reused'){throw}}
if(Test-Path -LiteralPath $planned){throw 'A simulation directory was created'}
""")
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)


if __name__ == '__main__': unittest.main()
