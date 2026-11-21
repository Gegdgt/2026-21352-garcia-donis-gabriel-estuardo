"""Tiny argv/status/scale/evidence contracts. No Validate, preflight or QSim.

PowerShell integration uses temporary script copies with inert doubles. The only
real launcher path exercised stops on missing fixture inputs before native tools.
"""
import gzip
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from simz1_scale_contract import require_scale
from simz1_population import population_spec
from simz1_demand_composition import split
from simz1_agent_types import load_catalog
from simz1_diagnostic_plots import collect, generate
from simz1_workflow_state import main as workflow

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'
SHELL=shutil.which('powershell.exe')


class ScaleContracts(unittest.TestCase):
    def test_180000_uses_existing_generator_size_and_exact_composition(self):
        spec=population_spec('montecarlo',min_agents=180000,max_agents=180000,massive=True)
        self.assertEqual((spec['minimum'],spec['maximum']),(180000,180000))
        expected=require_scale(180000)
        actual=split(180000,load_catalog(ROOT/'scenarios/zona1/agent-types-balanced-v1.json'))
        self.assertEqual(actual['family_counts'],{k:expected[k] for k in ('carro','moto','pesado')})
        self.assertEqual(actual['private_vehicles'],178200)
        self.assertEqual(expected,dict(carro=79200,moto=99000,pesado=1800,public_transport=269))

    def test_unrequested_size_seed_or_iterations_rejected(self):
        for args in ((220000,), (180000,7), (180000,20261023,10)):
            with self.subTest(args=args),self.assertRaises(ValueError):require_scale(*args)

    def test_first_scale_validation_does_not_read_or_record_trial(self):
        with patch('simz1_workflow_state.require_balanced_validation') as validate,patch('simz1_workflow_state.inspect',side_effect=AssertionError('No trial')):
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(workflow(['require-balanced-validation']),0)
            validate.assert_called_once_with()


@unittest.skipUnless(SHELL,'Windows PowerShell contract')
class PowerShellContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='simz1 contract spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.scripts=self.root/'scripts';self.scripts.mkdir()
        for name in ('simz1_launch_contract.ps1','run_massive_z1_pasante_10it.ps1','run_massive_z1_pasante_1it.ps1',
                     'run_simz1_110k_balanced_gateway.ps1','run_simz1_180k_balanced_gateway.ps1'):
            shutil.copyfile(SCRIPTS/name,self.scripts/name)

    def ps(self,text):
        path=self.root/'contract.ps1';path.write_text("$ErrorActionPreference='Stop'\n"+text,encoding='utf-8-sig')
        return subprocess.run([SHELL,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(path)],cwd=self.root,
                              capture_output=True,text=True,timeout=30)

    def test_native_child_receives_three_independent_paths_with_spaces(self):
        child=self.root/'capture.ps1'
        child.write_text('param([string]$ZoneBoundary,[string]$OdAccessCatalog,[string]$OdMixFile)\n@($ZoneBoundary,$OdAccessCatalog,$OdMixFile)|ConvertTo-Json -Compress\nexit 0',encoding='utf-8')
        r=self.ps(r"""
. ./scripts/simz1_launch_contract.ps1
$paths=@{ZoneBoundary='C:\a b\perimeter.geojson';OdAccessCatalog='C:\c d\access.json';OdMixFile='C:\e f\mix.json'}
$argv=@(Add-SimZ1PathArguments @('-NoProfile','-File','./capture.ps1') $paths)
& powershell.exe @argv
exit $LASTEXITCODE
""")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),[r'C:\a b\perimeter.geojson',r'C:\c d\access.json',r'C:\e f\mix.json'])

    def test_combined_parameter_value_is_rejected(self):
        r=self.ps(". ./scripts/simz1_launch_contract.ps1\nAssert-SimZ1PathArguments @('-ZoneBoundary C:\\a b\\p.json') @{ZoneBoundary='C:\\a b\\p.json'}")
        self.assertNotEqual(r.returncode,0)
        self.assertIn('separate elements',r.stderr)

    def test_outcomes_and_review_required_keep_distinct_codes(self):
        r=self.ps("""
. ./scripts/simz1_launch_contract.ps1
$records=@();foreach($outcome in @('PASSED','BLOCKED','FAILED','REVIEW_REQUIRED')) {
 $state=[ordered]@{};Set-SimZ1LaunchOutcome $state $outcome;$records += $state
}
$records|ConvertTo-Json -Compress
""")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual([r['exit_code'] for r in json.loads(r.stdout)],[0,1,1,3])

    def test_nested_wrappers_propagate_every_child_exit(self):
        # Versioned entrypoint and one-iteration adapter propagate the real child code.
        import sys
        wrapper=self.scripts/'run_simz1_180k_balanced_gateway.ps1'
        source=wrapper.read_text(encoding='utf-8')
        source=source.replace("(Join-Path $project '.venv/Scripts/python.exe')", "'"+sys.executable.replace("'","''")+"'")
        source=source.replace("(Join-Path $project 'python/simz1_scale_contract.py')", "'"+str(ROOT/'python/simz1_scale_contract.py').replace("'","''")+"'")
        wrapper.write_text(source,encoding='utf-8-sig')
        spec=ROOT/'scenarios/zona1/experiments/final-20261104-24h-v3.json'
        shared=self.scripts/'run_massive_z1_pasante_10it.ps1'
        for code in (0,1,3):
            shared.write_text(f'function Invoke-SimZ1MassiveLaunch {{ param($Options) return {code} }}',encoding='utf-8')
            for name,flag in (('run_simz1_180k_balanced_gateway.ps1','-Run'),('run_massive_z1_pasante_1it.ps1','-MinAgents 204186 -MaxAgents 204186')):
                with self.subTest(code=code,script=name):
                    r=self.ps(f"& ./scripts/{name} {flag} -ExperimentSpec '{spec}' -ExperimentScenario full-1\nexit $LASTEXITCODE")
                    self.assertEqual(r.returncode,code,r.stderr)

    def test_real_missing_input_guard_is_blocked_no_native_tools(self):
        r=self.ps('& ./scripts/run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial\nexit $LASTEXITCODE')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        states=list((self.root/'runtime/launches').glob('*/state.json'))
        self.assertEqual(states,[])
        self.assertIn('ExperimentSpec',r.stderr)
        self.assertNotIn('PASSED',r.stdout)
        self.assertFalse((self.root/'scenarios').exists())

    def test_selected_experiments_preserve_exact_N_iterations_and_exit_code(self):
        import sys
        wrapper=self.scripts/'run_simz1_180k_balanced_gateway.ps1'
        original=wrapper.read_text(encoding='utf-8')
        original=original.replace("(Join-Path $project '.venv/Scripts/python.exe')", "'"+sys.executable.replace("'","''")+"'")
        original=original.replace("(Join-Path $project 'python/simz1_scale_contract.py')", "'"+str(ROOT/'python/simz1_scale_contract.py').replace("'","''")+"'")
        wrapper.write_text(original,encoding='utf-8-sig')
        (self.scripts/'run_massive_z1_pasante_10it.ps1').write_text(
            'function Invoke-SimZ1MassiveLaunch { param($Options) $Options | ConvertTo-Json -Compress; return 3 }',encoding='utf-8')
        # Write-Output would mix JSON with the returned exit. Persist the captured arguments instead.
        (self.scripts/'run_massive_z1_pasante_10it.ps1').write_text(
            "function Invoke-SimZ1MassiveLaunch { param($Options) $Options | ConvertTo-Json | Set-Content -Encoding UTF8 captured.json; return 3 }",encoding='utf-8')
        from simz1_scale_contract import specification
        spec=self.root/'selection with spaces.json';spec.write_text(json.dumps(specification()))
        for key,row in specification()['scenarios'].items():
            r=self.ps("& ./scripts/run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -ExperimentSpec '"+str(spec)+"' -ExperimentScenario "+key+"\nexit $LASTEXITCODE")
            self.assertEqual(r.returncode,3,r.stdout+r.stderr)
            captured=json.loads((self.root/'captured.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(captured['MinAgents'],row['total_non_public_vehicles'])
            self.assertEqual(captured['MaxAgents'],captured['MinAgents'])
            self.assertEqual(captured['Iterations'],row['iterations'])
            self.assertTrue(captured['FirstScaleTrial']);self.assertTrue(captured['DryRun'])

    def test_first_scale_switch_is_exact_and_optional(self):
        r=self.ps("""
. ./scripts/simz1_launch_contract.ps1
$o=@{FirstScaleTrial=$true;MinAgents=180000;MaxAgents=180000;Iterations=1;Seed=20261023;OdMode='balanced-gateway-v1'}
if (-not (Test-SimZ1FirstScaleTrial $o)) {throw 'Expected explicit first scale'}
$o.FirstScaleTrial=$false
if (Test-SimZ1FirstScaleTrial $o) {throw 'Implicit first scale'}
$o.FirstScaleTrial=$true;$o.MinAgents=220000;$o.MaxAgents=220000
try { $null=Test-SimZ1FirstScaleTrial $o } catch { exit 0 }
throw 'Accepted wrong scale'
""")
        self.assertEqual(r.returncode,0,r.stderr)

    def test_valid_native_review_is_not_matsim_failure(self):
        r=self.ps("""
. ./scripts/simz1_launch_contract.ps1
$m=[pscustomobject]@{status='completed';validation=@{status='valid'}}
if ((Get-SimZ1PipelineDisposition $m 3) -ne 'review_required') {throw 'Lost review'}
$m.status='failed'
try {$null=Get-SimZ1PipelineDisposition $m 3} catch {exit 0}
throw 'Accepted failed MATSim'
""")
        self.assertEqual(r.returncode,0,r.stderr)

    def test_native_tool_nonzero_cannot_be_reported_success(self):
        (self.root/'child.ps1').write_text("Write-Output 'fixture failure';exit 7",encoding='utf-8')
        r=self.ps("""
. ./scripts/run_massive_z1_pasante_10it.ps1
try { $null=Invoke-SimZ1MassiveTool (Get-Command powershell.exe).Source @('-NoProfile','-File','./child.ps1') './child.log' } catch {exit 0}
throw 'Native exit code was lost'
""")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('fixture failure',(self.root/'child.log').read_text())

    def test_first_scale_still_requires_validation_fingerprint_and_runtime(self):
        r=self.ps("""
. ./scripts/run_massive_z1_pasante_10it.ps1
$fp='a'*64;$script:called=@()
function Invoke-SimZ1MassiveTool { param($Executable,$Arguments,$LogPath,[switch]$CaptureOutput)
 $script:called += ($Arguments -join ' ')
 return [pscustomobject]@{ExitCode=0;Output=@($fp)}
}
try { $null=Test-SimZ1MassiveGates $PWD 'inert' $PWD '' $true;throw 'Missing approval accepted' }
catch { if($_.Exception.Message -notlike 'Missing Validate*'){throw} }
$null=New-Item -ItemType Directory ./runtime/workflow -Force
[IO.File]::WriteAllText((Join-Path $PWD 'runtime/workflow/validated-source.txt'),$fp)
$null=Test-SimZ1MassiveGates $PWD 'inert' $PWD '' $true
if(($script:called -join ',') -notmatch 'require-balanced-validation' -or ($script:called -join ',') -notmatch 'simz1_runtime_check.py') {throw 'Required check missing'}
if(($script:called -join ',') -match 'require-trial') {throw 'Unexpected trial gate'}
[IO.File]::WriteAllText((Join-Path $PWD 'runtime/workflow/validated-source.txt'),'stale')
try {$null=Test-SimZ1MassiveGates $PWD 'inert' $PWD '' $true} catch {exit 0}
throw 'Stale fingerprint accepted'
""")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse((self.root/'runtime/workflow/trial-balanced-gateway-v1.json').exists())

    def test_checker_failure_is_nonzero_and_never_prints_pass(self):
        shutil.copyfile(SCRIPTS/'check_simz1_110k_balanced_gateway.ps1',self.scripts/'check_simz1_110k_balanced_gateway.ps1')
        (self.scripts/'run_massive_z1_pasante_10it.ps1').write_text("""
. (Join-Path $PSScriptRoot 'simz1_launch_contract.ps1')
function New-SimZ1MassiveLock { return [Threading.Mutex]::new($false) }
function Get-SimZ1MassiveWriters { return @() }
function Resolve-SimZ1MassiveJavaHome {return 'C:\\fixture-jdk'}
function Write-SimZ1MassiveJson($Path,$Value) { [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 20)) }
function Invoke-SimZ1MassiveTool { throw 'Inert fixture failure; no validator invoked' }
""",encoding='utf-8')
        r=self.ps('& ./scripts/check_simz1_110k_balanced_gateway.ps1 -Action Validate\nexit $LASTEXITCODE')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertNotIn('PASS',r.stdout)
        state=json.loads(next((self.root/'runtime/validation').glob('*/state.json')).read_text())
        self.assertEqual((state['outcome'],state['exit_code']),('FAILED',1))

    def test_all_modified_wrappers_parse_and_check_path_contracts(self):
        names=('run_simz1_180k_balanced_gateway.ps1','run_simz1_110k_balanced_gateway.ps1','run_massive_z1_pasante_1it.ps1',
               'run_massive_z1_pasante_10it.ps1','check_simz1_110k_balanced_gateway.ps1','simz1_workflow.ps1',
               'run_simz1_with_analysis.ps1','watch_simz1_110k.ps1','simz1_launch_contract.ps1')
        for name in names:shutil.copyfile(SCRIPTS/name,self.scripts/name)
        r=self.ps("""
foreach($file in Get-ChildItem ./scripts -Filter *.ps1) {
 $t=$null;$e=$null;$null=[System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$t,[ref]$e)
 if($e.Count){throw ($e|Out-String)}
}
""")
        self.assertEqual(r.returncode,0,r.stderr)
        for name in ('run_massive_z1_pasante_10it.ps1','simz1_workflow.ps1','run_simz1_with_analysis.ps1'):
            self.assertIn('Assert-SimZ1PathArguments',(SCRIPTS/name).read_text(encoding='utf-8-sig'))


class DiagnosticEvidenceContracts(unittest.TestCase):
    def test_truncated_fixture_reports_observations_without_freight_or_fake_schedules(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);out=run/'output/ITERS/it.0';out.mkdir(parents=True)
            xml=b'<events><event time="0" type="vehicle enters traffic" vehicle="a" link="x"/><event time="1" type="entered link" vehicle="a" link="x"/><event time="2" type="entered link" vehicle="a" link="y"/><event time="3" type="simz1NativeDecision" reason="storage_wait"/><event time="4" type="arrival" person="a"/></events>'
            (out/'0.events.xml.gz').write_bytes(gzip.compress(xml)[:-8])
            data=collect(run,{'status':'failed'},0)
            self.assertFalse(data['stream']['complete'])
            self.assertEqual(data['rows'][0]['transitions'],1)
            self.assertEqual(data['rows'][0]['arrivals'],1)
            self.assertEqual(data['rows'][0]['storage_wait_attempts'],1)
            self.assertNotIn('scheduled_departures',data['metrics'])
            self.assertNotIn('freight_active',data['metrics'])

    def test_diagnostic_identity_refuses_other_run_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);p=run/'run-manifest.json';p.write_text(json.dumps(dict(run_id='actual',status='failed')))
            before=p.read_bytes()
            with self.assertRaisesRegex(ValueError,'Run ID'):generate(run,'other')
            self.assertEqual(p.read_bytes(),before)
            self.assertFalse((run/'analysis').exists())

    def test_small_log_fixture_exports_provisional_png_without_modifying_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);p=run/'run-manifest.json';p.write_text(json.dumps(dict(run_id='tiny-fixture',status='failed',validation={'status':'invalid'})))
            log=run/'matsim-run.log'
            log.write_text('SIMZ1_PROGRESS simulatedTime=60.0 {iteration=0, elapsedSimSeconds=60.0, arrivals=1, activeVehicles=2, linkTransitions=3, waitStorage=4}\n')
            before={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (p,log)}
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(generate(run,'tiny-fixture'),0)
            output=next((run/'analysis/diagnostico-provisional').iterdir())
            report=json.loads((output/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['manifest_status'],'failed')
            self.assertEqual(len(report['png_files']),4)
            self.assertTrue(report['incomplete_data'])
            self.assertEqual(before,{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (p,log)})


if __name__=='__main__':unittest.main()
