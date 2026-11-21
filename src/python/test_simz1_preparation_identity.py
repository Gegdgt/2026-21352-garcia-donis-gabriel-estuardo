"""Preparation identity boundary without a population, manifest or simulation."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generate_montecarlo_z1 as generator
import simz1_scale_contract as contract


class PreparationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.source=contract.PROJECT/contract.DIAGNOSTIC_SPEC
        self.selected=contract.experiment(self.source,contract.DIAGNOSTIC_SCENARIO)

    def test_real_preparation_helper_rebuilds_v5_and_calls_strict_comparison(self):
        with tempfile.TemporaryDirectory(prefix='simz1-preparation-identity-') as folder:
            destination=Path(folder)/'experiment-specification.json'
            with patch.object(contract,'verify_selection_identity',
                              wraps=contract.verify_selection_identity) as compare:
                self.assertEqual(generator.pin_experiment_specification(
                    self.source,destination,self.selected),destination)
            compare.assert_called_once()
            recorded,rebuilt=compare.call_args.args
            self.assertEqual(recorded,self.selected)
            self.assertEqual(rebuilt['schema'],contract.DIAGNOSTIC_SCHEMA)
            self.assertEqual(rebuilt['scenario'],'run10000')
            self.assertEqual(rebuilt['specification_sha256'],self.selected['specification_sha256'])
            self.assertEqual(destination.read_bytes(),self.source.read_bytes())
            self.assertEqual(list(Path(folder).iterdir()),[destination])

    def test_preparation_rejects_changed_selection_before_publication(self):
        mutations=dict(schema='simz1-final-experiments-v4',scenario='run1000',
            total_non_public_vehicles=10001,demand_seed=7,service_date='2026-10-24',
            iterations=2,observation_end_seconds=108000,native_qsim_end_seconds=107999,
            base_scenario_identity='0'*64,specification_sha256='0'*64,
            population_group='run1000')
        for field,value in mutations.items():
            with self.subTest(field=field),tempfile.TemporaryDirectory(prefix='simz1-preparation-reject-') as folder:
                destination=Path(folder)/'experiment-specification.json'
                destination.write_bytes(b'previous-copy-preserved')
                selected=copy.deepcopy(self.selected);selected[field]=value
                with self.assertRaises(ValueError):
                    generator.pin_experiment_specification(self.source,destination,selected)
                self.assertEqual(destination.read_bytes(),b'previous-copy-preserved')
                self.assertEqual(list(Path(folder).iterdir()),[destination])

    def test_preparation_rejects_v3_and_v4_substitution_even_with_v5_sha(self):
        v3=contract.experiment(contract.PROJECT/contract.TRIAL_SPEC,'run1000')
        v3.update(specification_sha256=self.selected['specification_sha256'],scenario='run10000')
        v4=copy.deepcopy(self.selected);v4['schema']=contract.RANDOM_SCHEMA
        for replacement in (v3,v4):
            with self.subTest(schema=replacement['schema']),tempfile.TemporaryDirectory(prefix='simz1-preparation-legacy-') as folder:
                destination=Path(folder)/'experiment-specification.json'
                with self.assertRaisesRegex(ValueError,'Experiment selection identity differs'):
                    generator.pin_experiment_specification(self.source,destination,replacement)
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(folder).iterdir()),[])

    def test_preparation_rejects_an_added_source_fingerprint_as_unexpected_identity(self):
        # A fixed v5 selection has no fingerprint field: the revision is bound
        # by the launch state and preparation receipt, never silently ignored.
        replacement=dict(self.selected,source_fingerprint='0'*64)
        with tempfile.TemporaryDirectory(prefix='simz1-preparation-extra-') as folder:
            destination=Path(folder)/'experiment-specification.json'
            with self.assertRaisesRegex(ValueError,'Experiment selection identity differs'):
                generator.pin_experiment_specification(self.source,destination,replacement)
            self.assertFalse(destination.exists())


if __name__=='__main__':unittest.main()
