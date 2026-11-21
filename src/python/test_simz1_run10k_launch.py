"""Run10K must bind the same explicit DryRun, native trial and source revision."""
import subprocess
import unittest

import simz1_scale_contract as contract
import simz1_workflow_state as workflow
import test_simz1_random_launch as random_tests
import test_simz1_freight_version as freight_tests


class DiagnosticDryRunGateTests(random_tests.RandomDryRunGateTests):
    # Apply the same failure matrix to the fixed diagnostic selection. These
    # are temporary synthetic receipts, never runtime approvals or QSim.
    def setUp(self):
        super().setUp()
        self.selected = contract.experiment(contract.PROJECT/contract.DIAGNOSTIC_SPEC,
                                            contract.DIAGNOSTIC_SCENARIO)
        self.request.update(experiment=self.selected,minimum_non_public_vehicles=10000,
                            maximum_non_public_vehicles=10000)
        self.request['postprocessing_policy']='native_diagnostic_v1'
        self.state['postprocessing_policy']='native_diagnostic_v1'
        self.write_preparation_receipt()

    def test_v5_dryrun_without_preparation_boundary_proof_rejected(self):
        (self.directory/'preparation-identity.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_v5_dryrun_with_unbound_preparation_receipt_rejected(self):
        for value in (None, 'f'*64):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'receipt hash differs'):
                self.check(state=dict(self.state, preparation_identity_sha256=value))

    def test_first_scale_trial_cannot_bypass_diagnostic_contract(self):
        for schema in ('simz1-final-experiments-v5', 'simz1-final-experiments-v6'):
            with self.subTest(schema=schema):
                script = ". './scripts/simz1_launch_contract.ps1'; try { Test-SimZ1FirstScaleTrial @{FirstScaleTrial=$true; ExperimentSchema='"+schema+"'}; exit 9 } catch { if ($_.Exception.Message -notlike 'FirstScaleTrial is unavailable*') { throw }; exit 0 }"
                result = subprocess.run(['powershell.exe','-NoProfile','-Command',script],
                                        cwd=contract.PROJECT,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class DiagnosticFingerprintTests(unittest.TestCase):
    def test_spec_mutation_or_absence_invalidates_approval(self):
        helper = freight_tests.FreightVersionFingerprintTests()
        self.addCleanup(helper.doCleanups)
        root = helper._new_fixture_root()
        spec = root/contract.DIAGNOSTIC_SPEC
        original = spec.read_bytes()
        baseline = workflow.fingerprint(root)
        spec.write_bytes(b'changed diagnostic contract')
        self.assertNotEqual(workflow.fingerprint(root),baseline)
        spec.write_bytes(original)
        self.assertEqual(workflow.fingerprint(root),baseline)
        spec.unlink()
        with self.assertRaisesRegex(ValueError,'Required source absent'):
            workflow.fingerprint(root)


if __name__ == '__main__':
    unittest.main()
