"""Real PowerShell negative paths with tiny child stubs; no simulation tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe')


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Requires Windows PowerShell')
class ChildFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='SimZ1 child failure ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        self.python = self.root / 'python'
        self.python.mkdir()
        for name in ('simz1_launch_contract.ps1', 'run_massive_z1_pasante_10it.ps1'):
            shutil.copyfile(PROJECT / 'scripts' / name, self.scripts / name)
        original = (PROJECT / 'scripts/run_simz1_with_analysis.ps1').read_text(encoding='utf-8')
        # This suite exercises the real child-error handler below launch admission.
        # Its historical N=0/network child doubles are intentionally not an
        # authorized experiment. Isolate the admission layer in this temporary
        # copy only; test_simz1_trial_experiment covers the real guards separately.
        # No production file or approval receipt is changed by this fixture.
        guards = ["""if (-not $AnalysisOnly -and -not $PackageOnly -and (-not $ExperimentSpec -or -not $ExperimentScenario)) {
    throw 'Nueva corrida requiere -ExperimentSpec y -ExperimentScenario explicitos; use run_simz1_180k_balanced_gateway.ps1. Sin fallback network.'
}
if ($ExperimentSpec -and $OdMode -ne 'balanced-gateway-v1') { throw 'El experimento requiere balanced-gateway-v1 explicito.' }
""", """if (-not $AnalysisOnly -and -not $PackageOnly) {
    Assert-SimZ1PipelineOwner -Project $project -DryRun ([bool]$DryRun) -ExperimentSpec $ExperimentSpec -ExperimentScenario $ExperimentScenario -NewRunDir $NewRunDir -MinAgents $MinAgents -MaxAgents $MaxAgents -Seed $Seed -Iterations $Iterations
}
"""]
        for guard in guards:
            self.assertEqual(original.count(guard), 1)
            original = original.replace(guard, '# Admission isolated in this inert child-error fixture.\n')
        assignment = "$python = Join-Path $project '.venv\\Scripts\\python.exe'"
        self.assertEqual(original.count(assignment), 1)
        (self.scripts / 'run_simz1_with_analysis.ps1').write_text(original.replace(
            assignment, "$python = '" + sys.executable.replace("'", "''") + "'"), encoding='utf-8')
        self.run = self.root / 'scenarios/zona1/montecarlo/run-child-fixture'
        self.run.parent.mkdir(parents=True)
        (self.root / 'scenarios/zona1/config-simz1.xml').write_text('<config/>')
        (self.root / 'scenarios/zona1/agent-types-nonpublic-v1.json').write_text('{}')
        (self.root / 'mvnw.cmd').write_text('@echo off\nexit /b 99\n')
        (self.python / 'simz1_experiment_preflight.py').write_text('raise SystemExit(0)\n')
        for name in ('generar_graficas_z1.py', 'simz1_report_package.py', 'simz1_result_quality.py'):
            (self.python / name).write_text("raise AssertionError('Unexpected postprocessing')\n")

    def invoke(self, script, *arguments):
        return subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', str(script), *arguments], cwd=self.root,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=30)

    def wrapper(self, code, create_run=False, trailing_lines=0):
        (self.python / 'ejecutar_simz1.py').write_text(
            'import sys\nfrom pathlib import Path\n'
            + ("Path(sys.argv[sys.argv.index('--run-dir') + 1]).mkdir()\n" if create_run else '')
            + "print('fixture: structural audit failed on a required legal turn', file=sys.stderr)\n"
            + f"for i in range({trailing_lines}): print('fixture trailing context', i, file=sys.stderr)\n"
            + f'raise SystemExit({code})\n')
        return self.invoke(self.scripts / 'run_simz1_with_analysis.ps1',
                           '-MinAgents', '0', '-MaxAgents', '0', '-NoPublicTransport',
                           '-NoFreightTransport', '-MinFreeGiB', '0', '-NewRunDir', str(self.run))

    def assert_original_failure(self, result, expected_code):
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, expected_code, output)
        self.assertIn('structural audit failed on a required legal turn', output)
        self.assertNotIn('Cannot find path', output)
        self.assertNotIn('Could not find', output)
        self.assertFalse((self.run / 'run-manifest.json').exists())
        logs = list((self.root / 'runtime/launches').glob('*-preparation-*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('structural audit failed on a required legal turn', logs[0].read_text(encoding='utf-8'))

    def test_wrapper_retains_original_code_and_stderr_without_run_directory(self):
        result = self.wrapper(37)
        self.assert_original_failure(result, 37)
        self.assertFalse(self.run.exists())

    def test_wrapper_retains_original_code_with_partial_directory(self):
        result = self.wrapper(38, create_run=True)
        self.assert_original_failure(result, 38)
        self.assertTrue(self.run.exists())
        self.assertEqual(list(self.run.iterdir()), [])

    def test_success_exit_without_manifest_still_rejects(self):
        result = self.wrapper(0)
        self.assert_original_failure(result, 1)
        self.assertIn('codigo=0', result.stderr)

    def test_massive_child_guard_preserves_cause_code_log_and_no_identity(self):
        # Dot sourcing only defines production functions. Run the actual small
        # wrapper child, then the production manifest guard, never the launcher.
        self.wrapper(37)
        child = self.root / 'guard.ps1'
        child.write_text(r'''
$ErrorActionPreference = 'Stop'
. ./scripts/run_massive_z1_pasante_10it.ps1
$args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    './scripts/run_simz1_with_analysis.ps1', '-MinAgents', '0', '-MaxAgents', '0',
    '-NoPublicTransport', '-NoFreightTransport', '-MinFreeGiB', '0',
    '-NewRunDir', './scenarios/zona1/montecarlo/run-child-fixture')
$result = Invoke-SimZ1MassiveTool -Executable (Get-Command powershell.exe).Source `
    -Arguments $args -LogPath './child.log' -AllowFailure
try {
    $null = Read-SimZ1MassiveChildManifest -RunDirectory './scenarios/zona1/montecarlo/run-child-fixture' `
        -ChildExitCode $result.ExitCode -ChildLog './child.log'
    throw 'Missing manifest was accepted'
} catch {
    @{ child_exit_code = $result.ExitCode; error = $_.Exception.Message } |
        ConvertTo-Json | Set-Content './failure.json' -Encoding UTF8
}
''', encoding='utf-8')
        result = self.invoke(child)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        failure = json.loads((self.root / 'failure.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(failure['child_exit_code'], 37)
        self.assertIn('exit=37', failure['error'])
        self.assertIn('child.log', failure['error'])
        self.assertIn('structural audit failed on a required legal turn', failure['error'])
        self.assertNotIn('Could not find', failure['error'])
        self.assertFalse(self.run.exists())
        self.assertIn('structural audit failed on a required legal turn',
                      (self.root / 'child.log').read_text(encoding='utf-8'))

    def test_long_log_keeps_initial_cause_and_massive_catch_returns_original_code(self):
        self.assert_original_failure(self.wrapper(47, trailing_lines=80), 47)
        child = self.root / 'long-failure.ps1'
        child.write_text(r'''
$ErrorActionPreference = 'Stop'
. ./scripts/run_massive_z1_pasante_10it.ps1
# Import only the production failure handler, never the launch body. The
# fixture enters it through the real manifest guard with the small child result.
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path './scripts/run_massive_z1_pasante_10it.ps1').Path, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Parse failure' }
$definition = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Invoke-SimZ1MassiveLaunch'
}, $false)
$outerTry = @($definition.Body.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.TryStatementAst]
})
if ($outerTry.Count -ne 1) { throw 'Unexpected launcher failure-handler shape' }
$catchBody = $outerTry[0].CatchClauses[0].Body.Extent.Text
$fixture = @'
function Invoke-FixtureFailure {
    $run = Join-Path $PWD 'scenarios/zona1/montecarlo/run-child-fixture'
    $launch = $PWD.Path
    $state = [ordered]@{ status='running'; phase='simulation_and_analysis'; run_id=$null;
        native_status=$null; native_validation=$null; child_exit_code=$null; child_log='./long-child.log';
        outcome=$null; exit_code=$null; error=$null }
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        './scripts/run_simz1_with_analysis.ps1', '-MinAgents', '0', '-MaxAgents', '0',
        '-NoPublicTransport', '-NoFreightTransport', '-MinFreeGiB', '0', '-NewRunDir', $run)
    try {
        $result = Invoke-SimZ1MassiveTool -Executable (Get-Command powershell.exe).Source `
            -Arguments $args -LogPath $state.child_log -AllowFailure
        $state.child_exit_code = $result.ExitCode
        $null = Read-SimZ1MassiveChildManifest $run $result.ExitCode $state.child_log
        throw 'Missing manifest was accepted'
    } catch CATCH_BODY finally {
        $state | ConvertTo-Json | Set-Content './long-state.json' -Encoding UTF8
    }
}
exit (Invoke-FixtureFailure)
'@
Invoke-Expression $fixture.Replace('CATCH_BODY', $catchBody)
''', encoding='utf-8')
        result = self.invoke(child)
        self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
        state = json.loads((self.root / 'long-state.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(state['child_exit_code'], 47)
        self.assertEqual(state['exit_code'], 47)
        self.assertEqual(state['outcome'], 'BLOCKED')
        self.assertIsNone(state['run_id'])
        self.assertIn('exit=47', state['error'])
        complete_log = (self.root / 'long-child.log').read_text(encoding='utf-8')
        self.assertIn('structural audit failed on a required legal turn', complete_log)
        self.assertIn('fixture trailing context 79', complete_log)
        self.assertFalse(self.run.exists())

    def test_existing_manifest_retains_real_identity(self):
        self.run.mkdir()
        native = {'run_id': 'real-fixture-id', 'status': 'failed'}
        manifest = self.run / 'run-manifest.json'
        manifest.write_text(json.dumps(native))
        original = manifest.read_bytes()
        probe = self.root / 'existing.ps1'
        probe.write_text(r'''
$ErrorActionPreference = 'Stop'
. ./scripts/run_massive_z1_pasante_10it.ps1
Read-SimZ1MassiveChildManifest './scenarios/zona1/montecarlo/run-child-fixture' 37 './child.log' |
    ConvertTo-Json
''', encoding='utf-8')
        result = self.invoke(probe)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), native)
        self.assertEqual(manifest.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
