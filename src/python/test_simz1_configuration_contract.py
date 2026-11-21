"""Small configuration fixtures and the real MATSim API; never starts QSim."""
import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import simz1_configuration_contract as contract

ROOT = Path(__file__).resolve().parents[1]


def fixture_config(*, iterations=1, published=False):
    values = {'controler.'+key: str(value) for key, value in contract.NATIVE_DEFAULTS.items()}
    values.update(contract.PHYSICAL)
    if published:
        values['vspExperimental.writingOutputEvents'] = 'true'
    values.update({'controler.firstIteration': '0', 'controler.lastIteration': str(iterations-1),
                   'controler.writeEventsInterval': '1', 'controler.writePlansInterval': '1',
                   'qsim.startTime': '00:00:00', 'qsim.endTime': '23:59:59', 'qsim.timeStepSize': '1'})
    if not published:
        for key in ('eventsFileFormat', 'compressionType', 'cleanItersAtEnd', 'dumpDataAtEnd'):
            values.pop('controler.'+key)
    root = ET.Element('config')
    for key, value in values.items():
        module, name = key.split('.')
        group = root.find(f"module[@name='{module}']")
        if group is None:
            group = ET.SubElement(root, 'module', name=module)
        ET.SubElement(group, 'param', name=name, value=value)
    return root


def set_param(root, key, value):
    module, name = key.split('.')
    group = root.find(f"module[@name='{module}']")
    node = group.find(f"param[@name='{name}']")
    if value is None:
        group.remove(node)
    elif node is None:
        ET.SubElement(group, 'param', name=name, value=value)
    else:
        node.set('value', value)


class ConfigurationContractTests(unittest.TestCase):
    def test_original_absent_java_only_parameters_are_valid_in_both_xmls(self):
        expected = contract.planned_configuration(fixture_config())
        for published in (False, True):
            value = contract.normalize_configuration(fixture_config(published=published), published=published)
            contract.assert_configuration(value, expected)
            self.assertEqual(value['retention']['writeEventsUntilIteration'], 0)
            self.assertEqual(value['retention']['writePlansUntilIteration'], 1)

    def test_java_only_parameters_must_not_be_added_to_xml_even_with_default(self):
        for key, default in contract.JAVA_ONLY_DEFAULTS.items():
            for value in (str(default), '99'):
                root = fixture_config()
                set_param(root, 'controler.'+key, value)
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'Java API only'):
                    contract.normalize_configuration(root)

    def test_native_optional_interval_defaults_are_50_but_input_policy_is_explicit_1(self):
        root = fixture_config()
        for key in ('writeEventsInterval', 'writePlansInterval'):
            set_param(root, 'controler.'+key, None)
        normalized = contract.normalize_configuration(root)
        self.assertEqual(normalized['retention']['writeEventsInterval'], 50)
        self.assertEqual(normalized['retention']['writePlansInterval'], 50)
        with self.assertRaisesRegex(ValueError, 'retention'):
            contract.assert_configuration(normalized, contract.planned_configuration(root))

    def test_published_supported_fields_are_required_not_silently_defaulted(self):
        for name in contract.NATIVE_DEFAULTS:
            root = fixture_config(published=True)
            set_param(root, 'controler.'+name, None)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Missing published'):
                contract.normalize_configuration(root, published=True)

    def test_invalid_or_disabled_retention_rejected_before_qsim(self):
        for name, value in [('writeEventsInterval', '0'), ('writePlansInterval', '-1'),
                            ('writePlansInterval', '1.5'), ('compressionType', 'none'),
                            ('eventsFileFormat', 'json'), ('cleanItersAtEnd', 'delete'),
                            ('dumpDataAtEnd', 'false'), ('runId', 'unexpected-prefix')]:
            root = fixture_config(published=True)
            set_param(root, 'controler.'+name, value)
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                contract.planned_configuration(root)
        root = fixture_config(published=True)
        set_param(root, 'vspExperimental.writingOutputEvents', 'false')
        with self.assertRaises(ValueError):
            contract.planned_configuration(root)

    def test_configuration_mutations_physics_horizon_and_retention_rejected(self):
        expected = contract.planned_configuration(fixture_config())
        for key, value in [('qsim.numberOfThreads', '4'), ('qsim.removeStuckVehicles', 'true'),
                            ('simz1Admission.wholeVehicleReservation', 'false'), ('qsim.endTime', '30:00:00'),
                            ('qsim.timeStepSize', '2'), ('controler.lastIteration', '9'),
                            ('controler.writeEventsInterval', '2'), ('controler.writePlansInterval', '2')]:
            root = fixture_config(published=True)
            set_param(root, key, value)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'configuration differs'):
                contract.assert_configuration(contract.normalize_configuration(root, published=True), expected)

    def test_duplicate_and_missing_physical_values_fail_closed(self):
        root = fixture_config()
        group = root.find("module[@name='controler']")
        ET.SubElement(group, 'param', name='writeEventsInterval', value='1')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            contract.normalize_configuration(root)
        root = fixture_config()
        set_param(root, 'simz1Admission.storagePolicy', None)
        with self.assertRaisesRegex(ValueError, 'physical'):
            contract.assert_configuration(contract.normalize_configuration(root), contract.planned_configuration(root))

    def test_same_retention_for_every_scale_and_iteration_count(self):
        for iterations in (1, 10):
            reference = None
            for n in (1000, 10000, 55000, 110000, 180000, 189834, 220000):
                with self.subTest(n=n, iterations=iterations):
                    # N belongs to demand, not to configuration interpretation.
                    value = contract.planned_configuration(fixture_config(), 0, iterations-1)
                    schedule = contract.retained_iterations(value)
                    self.assertEqual(schedule['native_event_iterations'], list(range(iterations)))
                    self.assertEqual(schedule['native_plan_iterations'], list(range(iterations)))
                    self.assertEqual(schedule['native_event_files_including_final_copy'], iterations+1)
                    self.assertEqual(value, reference or value)
                    reference = value

    def test_sparse_native_schedule_preserves_early_plans_and_final_events(self):
        root = fixture_config(iterations=10)
        set_param(root, 'controler.writeEventsInterval', '5')
        set_param(root, 'controler.writePlansInterval', '5')
        result = contract.retained_iterations(contract.normalize_configuration(root))
        self.assertEqual(result['native_event_iterations'], [0, 5, 9])
        self.assertEqual(result['native_plan_iterations'], [0, 1, 5])

    def test_retained_files_input_output_and_final_copies_share_closure(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-config-closure-') as temp:
            run = Path(temp)
            (run/'output/ITERS/it.0').mkdir(parents=True)
            (run/'run-manifest.json').write_text(json.dumps({'run_id': 'synthetic-config-fixture-only'}))
            ET.ElementTree(fixture_config()).write(run/'config-simz1.xml')
            ET.ElementTree(fixture_config(published=True)).write(run/'output/output_config.xml')
            paths = ['output/ITERS/it.0/0.events.xml.gz', 'output/ITERS/it.0/0.plans.xml.gz',
                     'output/output_events.xml.gz', 'output/output_plans.xml.gz']
            for name in paths:
                (run/name).write_bytes(gzip.compress(b'<synthetic-fixture/>'))
            expected = contract.planned_configuration(fixture_config())
            result = contract.validate_run_configuration(run, expected)
            self.assertEqual(len(result['files']), 4)
            for name in paths:
                content = (run/name).read_bytes()
                (run/name).unlink()
                with self.subTest(missing=name), self.assertRaises(FileNotFoundError):
                    contract.validate_run_configuration(run, expected)
                (run/name).write_bytes(b'not gzip')
                with self.assertRaisesRegex(ValueError, 'not gzip'):
                    contract.validate_run_configuration(run, expected)
                (run/name).write_bytes(content)
            self.assertNotIn('completed', (run/'run-manifest.json').read_text())

    def test_actual_matsim15_defaults_and_non_serialized_java_fields(self):
        java_home = Path(os.environ.get('JAVA_HOME', r'C:\Program Files\Java\jdk-17'))
        java = java_home/'bin/java.exe'
        classpath = (ROOT/'target/simz1-runtime-classpath.txt').read_text().strip()
        source = '''import org.matsim.core.config.groups.ControlerConfigGroup;
import org.matsim.core.config.groups.VspExperimentalConfigGroup;
public class RetentionApiProbe {
 public static void main(String[] args) {
  ControlerConfigGroup c = new ControlerConfigGroup();
  if(c.getFirstIteration()!=0 || c.getLastIteration()!=1000 || c.getRunId()!=null ||
     c.getWriteEventsInterval()!=50 || c.getWritePlansInterval()!=50 ||
     c.getWriteEventsUntilIteration()!=0 || c.getWritePlansUntilIteration()!=1)
   throw new AssertionError("MATSim retention defaults changed");
  for(String key : new String[]{"writeEventsUntilIteration","writePlansUntilIteration"}) {
   if(c.getParams().containsKey(key)) throw new AssertionError("Java-only field is serialized");
   boolean rejected=false;
   try { c.addParam(key,"0"); } catch(RuntimeException e) { rejected=true; }
   if(!rejected) throw new AssertionError("Java-only field accepted as XML parameter");
  }
  if(!c.getParams().get("eventsFileFormat").equals("xml") ||
     !c.getCompressionType().name().equals("gzip") || !c.getDumpDataAtEnd() ||
     !c.getCleanItersAtEnd().name().equals("keep")) throw new AssertionError("Retention defaults changed");
  if(!new VspExperimentalConfigGroup().isWritingOutputEvents()) throw new AssertionError("Final event copy default changed");
  System.out.println("MATSIM15_RETENTION_API_PASS");
 }
}'''
        with tempfile.TemporaryDirectory(prefix='matsim-api-no-qsim-') as temp:
            path = Path(temp)/'RetentionApiProbe.java'
            path.write_text(source, encoding='utf-8')
            result = subprocess.run([str(java), '--class-path', classpath, str(path)],
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('MATSIM15_RETENTION_API_PASS', result.stdout)
        for source in (ROOT/'src/main/java').rglob('*.java'):
            self.assertNotIn('setWriteEventsUntilIteration(', source.read_text(encoding='utf-8'), str(source))
            self.assertNotIn('setWritePlansUntilIteration(', source.read_text(encoding='utf-8'), str(source))

    def test_powershell_storage_floor_and_larger_budget_remain_enforced(self):
        command = r'''. './scripts/run_massive_z1_pasante_10it.ps1'
$ErrorActionPreference='Stop'
$rows=@()
foreach($iterations in @(1,10)) {
 $plan=[pscustomobject]@{configuration=@{retention=@{}};native_event_iterations=@(0..($iterations-1));
   native_plan_iterations=@(0..($iterations-1));native_event_files_including_final_copy=($iterations+1);
   native_plan_files_including_final_copy=($iterations+1)}
 foreach($n in @(1000,10000,55000,110000,180000,220000)) {
  $budget=Get-SimZ1MassiveStorageBudget $plan $n 86400 100 8 4 7
  if($budget.minimum_free_gib -lt 100 -or $budget.ancillary_and_uncertainty_margin_gib -ne 20 -or
     $budget.pagefile_growth_reserve_gib -ne 7 -or $budget.sqlite_gib -ne 8 -or $budget.scratch_gib -ne 4 -or
     $budget.replay_reserve_gib -ne 2 -or $budget.native_plan_files_including_final_copy -ne ($iterations+1)) {throw 'Reserve reduced'}
  $rows += [pscustomobject]@{n=$n;iterations=$iterations;required=$budget.minimum_free_gib;scale=$budget.demand_and_observation_scale}
 }
 if((Get-SimZ1MassiveStorageBudget $plan 220000 86400 500 8 4 7).minimum_free_gib -lt 500) {throw 'Requested floor reduced'}
}
$rows | ConvertTo-Json -Compress
'''
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 12)
        self.assertGreater(rows[-1]['required'], 100)
        self.assertGreater(rows[-1]['scale'], rows[-2]['scale'])


if __name__ == '__main__':
    unittest.main()
