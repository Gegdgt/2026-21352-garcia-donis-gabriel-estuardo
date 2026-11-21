"""Small admission/config/export contracts. No Maven, QSim or historical writes."""
import copy
import argparse
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar, SCENARIO, add_generation_options, generation_options
from simz1_admission_validation import AdmissionAudit
from simz1_config_validation import ConfigurationError, validate_configuration, admission_execution_contract
from simz1_native_validation import NativeDecisionAudit
from simz1_priority_audit import PriorityAudit
from simz1_run import load_manifest, parameters, sha256
from simz1_trajectories import extract
from simz1_motion import MotionContext
from simz1_visual_motion import _endpoint_wait


def event(reason='storage_wait', decision='WAIT', **extra):
    attrs = dict(type='simz1NativeDecision', time='11', vehicle='v', person='p', link='in', lane='in.0',
        nextLink='out', reason=reason, decision=decision, waitCategory='insufficient_storage',
        source='SimZ1_QNode_strict_receiver_v1', admissionPolicy='strict-receiver-v1', admissionPolicyVersion='1',
        receiverAcceptedAtDecision='false', receivingLane='out.original',
        waitSeconds='11', stuckTime='10', storageTimeoutExceeded='true',
        signalState='GREEN', nativeHasGreen='true', removeStuckVehicles='false')
    attrs.update(extra)
    return ET.Element('event', attrs)


class AdmissionTests(unittest.TestCase):
    def test_legacy_missing_policy_is_not_relabelled_strict(self):
        config = ET.fromstring('<config/>'); original = ET.tostring(config)
        self.assertEqual(validate_configuration(config)['admission_policy'], 'matsim15-native')
        self.assertEqual(ET.tostring(config), original)
        legacy = event('storage_forced_move','FORCE')
        for key in ('admissionPolicy','admissionPolicyVersion','storageTimeoutExceeded'):
            legacy.attrib.pop(key)
        audit = NativeDecisionAudit(); audit.consume(legacy)
        self.assertEqual(audit.summary()['forced_storage_moves'], 1)
        self.assertEqual(audit.summary()['admission_diagnostics']['native_decisions_by_policy'], {'legacy_unattributed':1})
        with self.assertRaisesRegex(ValueError,'politica estricta'):
            NativeDecisionAudit('strict-receiver-v1').consume(legacy)
        with self.assertRaisesRegex(ValueError,'configuracion efectiva'):
            NativeDecisionAudit(validate_configuration(config)['admission_policy']).consume(event())

    def test_strict_configuration_rejects_removal_and_unknown_policy(self):
        root = ET.fromstring('<config><module name="simz1Admission"><param name="storagePolicy" value="strict-receiver-v1"/></module>'
                            '<module name="qsim"><param name="removeStuckVehicles" value="false"/></module></config>')
        self.assertEqual(validate_configuration(root)['admission_policy'], 'strict-receiver-v1')
        root.find("module[@name='qsim']/param").set('value','true')
        with self.assertRaisesRegex(ConfigurationError,'incompatible'):
            validate_configuration(root)
        self.assertEqual(root.find("module[@name='qsim']/param").get('value'),'true')
        root.find("module[@name='simz1Admission']/param").set('value','invented')
        with self.assertRaisesRegex(ConfigurationError,'desconocida'):
            validate_configuration(root)

    def test_future_launcher_requires_explicit_policy_but_history_remains_native(self):
        root = ET.fromstring('<config/>')
        with self.assertRaisesRegex(ConfigurationError, 'explicita'):
            admission_execution_contract(root)
        self.assertEqual(validate_configuration(root)['admission_policy'], 'matsim15-native')

    def test_four_threads_contract_is_verified_only_against_effective_config(self):
        root = ET.fromstring('<config><module name="simz1Admission"><param name="storagePolicy" value="strict-receiver-v1"/></module>'
                            '<module name="qsim"><param name="numberOfThreads" value="4"/>'
                            '<param name="removeStuckVehicles" value="false"/><param name="stuckTime" value="10"/></module></config>')
        requested = admission_execution_contract(root)
        self.assertEqual(requested['qsim_threads'], 4)
        self.assertEqual(requested['receiver_rejection'], 'WAIT')
        self.assertFalse(requested['force_after_stuck_time'])
        self.assertEqual(requested['verification'], 'requested_config_only')
        effective = copy.deepcopy(root)
        effective.find("module[@name='qsim']/param[@name='stuckTime']").set('value', '00:00:10')
        verified = admission_execution_contract(root, effective)
        self.assertEqual(verified['verification'], 'effective_config_matches')
        self.assertFalse(verified['native_execution_proven'])
        for module, key, value in [('simz1Admission', 'storagePolicy', 'matsim15-native'),
                                   ('qsim', 'numberOfThreads', '1'), ('qsim', 'stuckTime', '11')]:
            changed = copy.deepcopy(effective)
            changed.find(f"module[@name='{module}']/param[@name='{key}']").set('value', value)
            with self.subTest(key=key), self.assertRaisesRegex(ConfigurationError, 'contrato de admision'):
                admission_execution_contract(root, changed)

    def test_duplicate_or_misspelled_policy_is_rejected(self):
        for body in ['<param name="storagePolicy" value="strict-receiver-v1"/><param name="storagePolicy" value="matsim15-native"/>',
                     '<param name="storagePolcy" value="strict-receiver-v1"/>']:
            with self.subTest(body=body), self.assertRaisesRegex(ConfigurationError, 'duplicados o desconocidos'):
                validate_configuration(ET.fromstring(f'<config><module name="simz1Admission">{body}</module></config>'))
        with self.assertRaisesRegex(ConfigurationError, 'duplicado'):
            validate_configuration(ET.fromstring('<config><module name="simz1Admission"/><module name="simz1Admission"/></config>'))

    def test_receipt_route_requirement_is_explicit_and_not_added_to_history(self):
        root = ET.fromstring('<config><module name="simz1Admission">'
            '<param name="storagePolicy" value="strict-receiver-v1"/>'
            '<param name="wholeVehicleReservation" value="true"/></module>'
            '<module name="qsim"><param name="numberOfThreads" value="1"/></module></config>')
        original = ET.tostring(root)
        historical = admission_execution_contract(root, root)
        self.assertIsNone(historical['expected_receipt_route_coverage_policy'])
        policy = 'planned_contiguous_prefix_v1'
        requested = admission_execution_contract(root, expected_receipt_route_coverage_policy=policy)
        verified = admission_execution_contract(root, root,
            expected_receipt_route_coverage_policy=requested['expected_receipt_route_coverage_policy'])
        self.assertEqual(verified['expected_receipt_route_coverage_policy'], policy)
        self.assertEqual(ET.tostring(root), original)
        for invalid in ('unknown',):
            with self.assertRaises(ConfigurationError):
                admission_execution_contract(root, expected_receipt_route_coverage_policy=invalid)
        root.find("module[@name='simz1Admission']/param[@name='wholeVehicleReservation']").set('value','false')
        with self.assertRaises(ConfigurationError):
            admission_execution_contract(root, expected_receipt_route_coverage_policy=policy)

    def test_lane_policy_default_disabled_and_native_adapter_required(self):
        missing = validate_configuration(ET.fromstring('<config/>'))['lane_policy']
        disabled = ET.fromstring('<config><module name="simz1LanePolicy"><param name="enabled" value="false"/></module></config>')
        self.assertEqual(validate_configuration(disabled)['lane_policy'], missing)
        self.assertFalse(missing['installed'])
        disabled.find('module/param').set('value', 'true')
        with self.assertRaisesRegex(ConfigurationError, 'LANE_POLICY_UNAVAILABLE'):
            validate_configuration(disabled)
        for name, value in [('minimumGapM', 'NaN'), ('minimumAdvanceM', '0'), ('lookaheadSeconds', '-1'), ('unknown', '1')]:
            root = ET.fromstring(f'<config><module name="simz1LanePolicy"><param name="{name}" value="{value}"/></module></config>')
            with self.subTest(name=name), self.assertRaises(ConfigurationError):
                validate_configuration(root)

    def test_storage_policy_cli_is_explicit_and_preserves_native_comparison(self):
        parser = argparse.ArgumentParser()
        add_generation_options(parser)
        self.assertIsNone(generation_options(parser.parse_args([]))['storage_policy'])
        self.assertEqual(generation_options(parser.parse_args(['--storage-policy', 'matsim15-native']))['storage_policy'],
                         'matsim15-native')
        source = SCENARIO/'config-simz1.xml'; before = sha256(source)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'native comparison'
            generar(source, destination, 20261022, agents=1, corridor_policy='redistribute',
                    qsim_threads=4, storage_policy='matsim15-native')
            manifest = load_manifest(destination)
            self.assertEqual(manifest['admission_policy_selection']['source'], '--storage-policy')
            contract = admission_execution_contract(destination/'config-simz1.xml')
            self.assertEqual(contract['storage_policy'], 'matsim15-native')
            self.assertTrue(contract['force_after_stuck_time'])
            self.assertFalse((destination/'output').exists())
        self.assertEqual(sha256(source), before)

    def test_new_one_person_run_persists_strict_without_changing_master(self):
        source = SCENARIO/'config-simz1.xml'; before = sha256(source)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'new isolated run'
            generar(source,destination,20261022,agents=1,corridor_policy='redistribute',qsim_threads=4)
            options = parameters(destination/'config-simz1.xml')
            self.assertEqual(options['simz1Admission.storagePolicy'],'strict-receiver-v1')
            self.assertEqual(options['qsim.numberOfThreads'],'4')
            self.assertEqual(options['qsim.removeStuckVehicles'],'false')
            manifest = load_manifest(destination)
            self.assertEqual(manifest['status'],'prepared')
            self.assertEqual(manifest['configuration_validation']['admission_policy'],'strict-receiver-v1')
            self.assertEqual(manifest['admission_policy_selection']['source'], 'future-run default')
            self.assertTrue(any(row['parameter']=='simz1Admission.storagePolicy' and row['before'] is None
                                for row in manifest['configuration_overrides']))
            self.assertFalse((destination/'output').exists())
        self.assertEqual(sha256(source),before)

    def test_prolonged_wait_is_not_force_and_timeout_is_strict(self):
        audit = NativeDecisionAudit('strict-receiver-v1')
        audit.consume(event(waitSeconds='10',storageTimeoutExceeded='false'))
        audit.consume(event(waitSeconds='86400',time='86400'))
        result = audit.summary()
        self.assertEqual(result['forced_storage_moves'],0)
        self.assertEqual(result['storage_stuck_removals'],0)
        self.assertEqual(result['admission_diagnostics']['storage_waits_beyond_stuck_time'],1)
        self.assertFalse(result['physical_stability']['proven'])
        for changes in (dict(storageTimeoutExceeded='false'),dict(waitSeconds='NaN'),dict(receiverAcceptedAtDecision='true')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AdmissionAudit().consume(event(**changes))

    def test_force_and_removal_fail_under_strict_even_with_green(self):
        for reason, decision in [('storage_forced_move','FORCE'),('storage_stuck_removal','ABORT')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError,'incompatible'):
                NativeDecisionAudit('strict-receiver-v1').consume(event(reason,decision))

    def test_explicit_policy_and_version_must_match(self):
        for changes in (dict(admissionPolicy='invented'),dict(admissionPolicyVersion='2'),dict(admissionPolicy='matsim15-native')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AdmissionAudit('strict-receiver-v1').consume(event(**changes))

    def test_receipt_is_distinct_from_turn_permission_and_wait(self):
        audit = NativeDecisionAudit('strict-receiver-v1')
        audit.consume(event('turn_go','GO',waitCategory='none'))
        audit.consume(event())
        self.assertEqual(audit.summary()['admission_diagnostics']['confirmed_receiver_admissions'],0)
        receipt = event('receiver_accepted','GO',type='simz1Admission',receiverAcceptedAtDecision='true',node='j')
        audit.consume(receipt)
        self.assertEqual(audit.summary()['decisions'],2)
        self.assertEqual(audit.summary()['admission_diagnostics']['confirmed_receiver_admissions'],1)
        for changes in (dict(receiverAcceptedAtDecision='false'),dict(time='NaN'),dict(node=''),dict(decision='WAIT')):
            broken = copy.deepcopy(receipt);broken.attrib.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                AdmissionAudit().consume(broken)

    def test_conflict_wait_retains_queue_exit_evidence(self):
        conflict = event('admission_conflict_executed',waitCategory='yield')
        audit = NativeDecisionAudit('strict-receiver-v1');audit.consume(conflict)
        self.assertEqual(audit.summary()['admission_diagnostics']['conflict_wait_attempts'],1)
        priority = PriorityAudit();priority.consume(conflict)
        self.assertEqual(priority.wait_causes['yield'],1)
        record = dict(Observed_Waits={'admission_conflict_executed':dict(first=11,sources=['SimZ1_QNode_strict_receiver_v1'])})
        self.assertEqual(_endpoint_wait(record),11)
        record['Observed_Waits']['admission_conflict_executed']['position_evidence']='unknown_queue_position'
        self.assertIsNone(_endpoint_wait(record))

    def test_trajectory_export_keeps_wait_and_recorded_exit_time(self):
        events = [dict(time='0',type='departure',person='p',link='in',legMode='car'),
                  dict(time='0',type='vehicle enters traffic',person='p',vehicle='v',link='in',relativePosition='0'),
                  dict(event('admission_conflict_executed',waitCategory='yield').attrib),
                  dict(time='20',type='left link',vehicle='v',link='in'),
                  dict(time='20',type='vehicle leaves traffic',person='p',vehicle='v',link='in',relativePosition='1'),
                  dict(time='20',type='arrival',person='p',link='in',legMode='car')]
        links={'in':dict(length=100,freespeed=10,from_node='a',to_node='b',**{'from':[0,0],'to':[.001,0]})}
        rows = extract(events,links,lambda vehicle:True,lambda speed:[255,0,0],None,
                       motion=MotionContext({'v':10},{'p':'Normal'},{'v':'p'}),horizon=20)
        self.assertEqual(rows[0]['timestamps'],[0,20])
        wait = rows[0]['Observed_Waits']['admission_conflict_executed']
        self.assertEqual(wait['position_evidence'],'queue_exit')
        self.assertEqual(wait['sources'],['SimZ1_QNode_strict_receiver_v1'])


if __name__ == '__main__':
    unittest.main()
