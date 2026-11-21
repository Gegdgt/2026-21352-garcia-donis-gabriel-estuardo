"""Execute the Windows recovery launcher with tiny CLI stubs; never run MATSim."""
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
STUB = '''from pathlib import Path
import json
import sys
root = Path(__file__).resolve().parents[1]
name = Path(__file__).stem
with (root / 'calls.jsonl').open('a', encoding='utf-8') as stream:
    stream.write(json.dumps({'name': name, 'args': sys.argv[1:]}) + '\\n')
codes = json.loads((root / 'codes.json').read_text(encoding='utf-8'))
print(json.dumps({'phase': name, 'status': 'fixture'}), flush=True)
sys.exit(codes[name])
'''


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Requires real Windows PowerShell')
class PackageLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='SimZ1 package launcher ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        shutil.copy2(PROJECT/'scripts/simz1_launch_contract.ps1',self.scripts/'simz1_launch_contract.ps1')
        self.python = self.root / 'python'
        self.python.mkdir()
        self.script = self.scripts / 'run_simz1_with_analysis.ps1'
        original = (PROJECT / 'scripts' / self.script.name).read_text(encoding='utf-8')
        assignment = "$python = Join-Path $project '.venv\\Scripts\\python.exe'"
        self.assertEqual(original.count(assignment), 1)
        # Keep the production launcher body; only relocate its interpreter to
        # the real repository environment instead of creating another venv.
        self.script.write_text(original.replace(
            assignment, "$python = '" + sys.executable.replace("'", "''") + "'"), encoding='utf-8')
        self.run = self.root / 'run-fixture'
        self.run.mkdir()
        self.run_id = 'simz1-launcher-fixture'
        (self.run / 'run-manifest.json').write_text(json.dumps({
            'run_id': self.run_id, 'status': 'completed', 'validation': {'status': 'valid'},
            'iterations': {'completed': [0, 1]}, 'counts': {'planned_persons': 6},
            'experiment': {'base_scenario_identity': 'synthetic-orchestration-fixture-only'},
        }), encoding='utf-8')
        # These doubles prove orchestration and failure ordering only. The real
        # configuration semantics and closure are exercised by their own fixtures.
        for name in ('simz1_configuration_contract', 'simz1_balanced_launch_report',
                     'simz1_report_package', 'simz1_result_quality', 'generar_graficas_z1'):
            (self.python / (name + '.py')).write_text(STUB, encoding='utf-8')
        self.codes = dict(simz1_configuration_contract=0, simz1_report_package=0,
                          simz1_result_quality=0, generar_graficas_z1=0, simz1_balanced_launch_report=0)
        self.save_codes()

    def save_codes(self):
        (self.root / 'codes.json').write_text(json.dumps(self.codes), encoding='utf-8')

    def calls(self):
        path = self.root / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def invoke(self, *options, expected=None):
        command = [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.script),
                   '-RunDir', str(self.run), '-ExpectedRunId', expected or self.run_id, *options]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=30)
        self.assertFalse((self.root / 'MATSim-called').exists(), result.stdout + result.stderr)
        return result

    def make_analysis_dependencies(self):
        # AnalysisOnly historically checks these dependencies. They deliberately
        # fail if called; the tested branch may call only analyzer/package/quality.
        (self.root / 'mvnw.cmd').write_text('@echo off\necho forbidden>MATSim-called\nexit /b 91\n')
        config = self.root / 'scenarios' / 'zona1' / 'config-simz1.xml'
        config.parent.mkdir(parents=True)
        config.write_text('<fixture/>')
        for name in ('ejecutar_simz1.py', 'simz1_experiment_preflight.py'):
            (self.python / name).write_text(
                "from pathlib import Path\nPath('MATSim-called').write_text('forbidden')\nraise SystemExit(91)\n")

    def test_package_only_needs_no_matsim_dependencies_and_forwards_identity(self):
        result = self.invoke('-PackageOnly')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual([item['name'] for item in calls],
                         ['simz1_configuration_contract', 'simz1_balanced_launch_report',
                          'simz1_balanced_launch_report', 'simz1_report_package',
                          'simz1_result_quality', 'simz1_result_quality'])
        self.assertEqual(calls[0]['args'], ['verify-run', '--run-dir', str(self.run)])
        for number, call in enumerate(calls[1:3]):
            self.assertEqual(call['args'], ['--run-dir', str(self.run), '--iteration', str(number)])
        self.assertIn('--all-iterations', calls[3]['args'])
        self.assertEqual(calls[3]['args'][-2:], ['--expected-run-id', self.run_id])
        for number, call in enumerate(calls[4:]):
            self.assertIn('--require-six-profiles', call['args'])
            self.assertIn('it.' + str(number), call['args'][call['args'].index('--summary') + 1])

    def test_review_required_is_code_three_after_complete_package(self):
        self.codes['simz1_result_quality'] = 3
        self.save_codes()
        result = self.invoke('-PackageOnly')
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('EMPAQUETADO COMPLETO', result.stdout)
        self.assertIn('review_required', result.stdout)
        self.assertEqual(len(self.calls()), 6)

    def test_package_failure_is_nonzero_and_does_not_run_quality(self):
        self.codes['simz1_report_package'] = 1
        self.save_codes()
        result = self.invoke('-PackageOnly')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([call['name'] for call in self.calls()],
                         ['simz1_configuration_contract', 'simz1_balanced_launch_report',
                          'simz1_balanced_launch_report', 'simz1_report_package'])
        self.assertNotIn('EMPAQUETADO COMPLETO', result.stdout)

    def test_wrong_run_identity_rejected_before_any_cli(self):
        result = self.invoke('-PackageOnly', expected='wrong-run')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Identidad incompatible', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_dry_run_invokes_no_cli(self):
        result = self.invoke('-PackageOnly', '-DryRun')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [])

    def test_switches_are_exclusive(self):
        result = self.invoke('-PackageOnly', '-AnalysisOnly')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_quality_error_is_nonzero_not_screening_review(self):
        self.codes['simz1_result_quality'] = 1
        self.save_codes()
        result = self.invoke('-PackageOnly')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.calls()), 5)
        self.assertNotIn('EMPAQUETADO COMPLETO', result.stdout)

    def test_analysis_only_keeps_analyzer_reuse_branch_without_matsim(self):
        self.make_analysis_dependencies()
        result = self.invoke('-AnalysisOnly')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call['name'] for call in self.calls()], [
            'simz1_configuration_contract', 'generar_graficas_z1',
            'simz1_balanced_launch_report', 'simz1_balanced_launch_report', 'simz1_report_package',
            'simz1_result_quality', 'simz1_result_quality'])
        self.assertIn('--all-iterations', self.calls()[1]['args'])

    def test_analysis_failure_does_not_package_or_run_matsim(self):
        self.make_analysis_dependencies()
        self.codes['generar_graficas_z1'] = 2
        self.save_codes()
        result = self.invoke('-AnalysisOnly')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([call['name'] for call in self.calls()],
                         ['simz1_configuration_contract', 'generar_graficas_z1'])

    def test_configuration_failure_blocks_analysis_and_package_preserving_native_manifest(self):
        self.make_analysis_dependencies()
        self.codes['simz1_configuration_contract'] = 2
        self.save_codes()
        manifest = self.run / 'run-manifest.json'
        original = manifest.read_bytes()
        for option in ('-AnalysisOnly','-PackageOnly'):
            with self.subTest(option=option):
                call_log = self.root / 'calls.jsonl'
                if call_log.exists():
                    call_log.unlink()
                result = self.invoke(option)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('Native configuration/retention mismatch', result.stderr)
                self.assertEqual([call['name'] for call in self.calls()], ['simz1_configuration_contract'])
                self.assertEqual(manifest.read_bytes(), original)
                self.assertNotIn('EMPAQUETADO COMPLETO', result.stdout)

    def test_historical_run_without_experiment_keeps_its_existing_package_contract(self):
        manifest = self.run / 'run-manifest.json'
        native = json.loads(manifest.read_text(encoding='utf-8'))
        del native['experiment']
        manifest.write_text(json.dumps(native), encoding='utf-8')
        original = manifest.read_bytes()
        result = self.invoke('-PackageOnly')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call['name'] for call in self.calls()],
                         ['simz1_report_package', 'simz1_result_quality', 'simz1_result_quality'])
        self.assertEqual(manifest.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
