"""Small synthetic event/log observations; no JVM, QSim or historical event scan."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_native_validation import NativeDecisionAudit, STORAGE_WAIT_REASONS, native_wait_category
from simz1_priority_audit import PriorityAudit
from simz1_operational_report import progress_attributes, progress_log


def decision(reason='receiver_storage_or_terminal_slot', **changes):
    values = dict(type='simz1NativeDecision', reason=reason, decision='WAIT', vehicle='v1',
                  waitCategoryVersion='2', waitCategory=native_wait_category(reason),
                  attemptUnit='native_decision_event', waitSeconds='17.5',
                  waitSecondsBasis='head_age_since_last_movement_not_reason_duration')
    values.update(changes)
    return ET.Element('event', values)


class NativeWaitObservationTests(unittest.TestCase):
    def test_receiving_reasons_remain_raw_and_classify_as_storage(self):
        native, priority = NativeDecisionAudit(), PriorityAudit()
        for reason in sorted(STORAGE_WAIT_REASONS):
            native.consume(decision(reason))
            priority.consume(decision(reason).attrib)
        self.assertEqual(native.summary()['reasons'], {reason:1 for reason in STORAGE_WAIT_REASONS})
        self.assertEqual(native.summary()['wait_categories'], {'insufficient_storage':7})
        self.assertEqual(priority.summary()['native_wait_causes'], {'insufficient_storage':7})
        self.assertEqual(priority.summary()['executed_crossings'], 0)

    def test_attempts_distinct_vehicles_and_age_are_not_the_same_measure(self):
        native = NativeDecisionAudit()
        for vehicle, age in (('v1', 17.5), ('v1', 21), ('v2', 2)):
            native.consume(decision(vehicle=vehicle, waitSeconds=str(age)))
        native.consume(ET.Element('event', type='simz1Priority', decision='WAIT', reason='priority_stop'))
        native.consume(ET.Element('event', type='simz1Reservation', decision='WAIT', reason='receiver_storage_or_terminal_slot'))
        native.consume(decision('turn_go', decision='GO'))
        data = native.summary()['wait_observation_v2']
        self.assertEqual(data['attempts_by_category'], {'insufficient_storage':3})
        self.assertEqual(data['distinct_vehicles'], 2)
        self.assertEqual(data['maximum_observed_age_seconds_by_category'], {'insufficient_storage':21})
        self.assertIn('not_summed_attempts', data['age_basis'])

    def test_missing_age_and_vehicle_are_unknown_coverage(self):
        event = decision()
        for key in ('vehicle', 'waitSeconds', 'waitSecondsBasis'): event.attrib.pop(key)
        native = NativeDecisionAudit(); native.consume(event)
        data = native.summary()['wait_observation_v2']
        self.assertEqual(data['distinct_vehicles'], 0)
        self.assertEqual(data['attempts_without_vehicle_by_category'], {'insufficient_storage':1})
        self.assertEqual(data['attempts_without_age_by_category'], {'insufficient_storage':1})
        self.assertEqual(data['maximum_observed_age_seconds_by_category'], {})

    def test_unknown_is_versioned_and_known_reason_cannot_hide_as_unknown(self):
        native, priority = NativeDecisionAudit(), PriorityAudit()
        event = decision('new_observed_wait')
        native.consume(event); priority.consume(event.attrib)
        self.assertEqual(native.summary()['wait_categories'], {'unknown':1})
        self.assertEqual(priority.summary()['native_wait_causes'], {'unknown':1})
        for changes in ({'waitCategoryVersion':'3'}, {'waitCategoryVersion':'1'},
                        {'waitCategoryVersion':None}, {'attemptUnit':'seconds'},
                        {'reason':'receiver_storage_or_terminal_slot'}, {'waitCategory':'none'}):
            event = decision('new_observed_wait')
            event.attrib.update({k:v for k,v in changes.items() if v is not None})
            if changes.get('waitCategoryVersion', '') is None: event.attrib.pop('waitCategoryVersion')
            for audit in (NativeDecisionAudit(), PriorityAudit()):
                with self.subTest(changes=changes, audit=type(audit).__name__), self.assertRaises(ValueError):
                    audit.consume(event if isinstance(audit, NativeDecisionAudit) else event.attrib)

    def test_pre_version_observation_is_preserved_not_rewritten(self):
        event = ET.Element('event', type='simz1NativeDecision', reason='receiver_storage_or_terminal_slot',
                           decision='WAIT', waitCategory='none')
        native, priority = NativeDecisionAudit(), PriorityAudit()
        native.consume(event); priority.consume(event.attrib)
        self.assertEqual(native.summary()['wait_categories'], {'none':1})
        self.assertEqual(native.summary()['wait_observation_v2']['attempts_by_category'], {})
        self.assertEqual(priority.summary()['native_wait_causes'], {'insufficient_storage':1})

    def test_abort_is_not_a_wait_attempt_v2_and_does_not_disable_invalid_turn_guard(self):
        native, priority = NativeDecisionAudit(), PriorityAudit()
        event = decision('other_abort', decision='ABORT')
        native.consume(event); priority.consume(event.attrib)
        self.assertEqual(native.summary()['wait_categories'], {})
        self.assertEqual(native.summary()['wait_observation_v2']['abort_events_by_category'], {'unknown':1})
        self.assertEqual(priority.summary()['native_wait_causes'], {})
        with self.assertRaisesRegex(ValueError, 'ABORT nativo'):
            NativeDecisionAudit().consume(decision('turn_abort_missing_route', decision='ABORT'))

    def test_red_and_receiver_intervention_guards_remain(self):
        for fields in ({'signalState':'RED'}, {'nativeHasGreen':'false'}):
            with self.assertRaisesRegex(ValueError, 'Movimiento'):
                NativeDecisionAudit().consume(decision('turn_go', decision='GO', **fields))
        with self.assertRaisesRegex(ValueError, 'rama de almacenamiento'):
            NativeDecisionAudit().consume(decision('storage_forced_move', decision='WAIT'))
        audit = NativeDecisionAudit()
        audit.consume(decision('storage_forced_move', decision='FORCE'))
        self.assertEqual(audit.summary()['forced_storage_moves'], 1)
        self.assertFalse(audit.summary()['physical_stability']['proven'])

    def test_invalid_age_cannot_become_zero(self):
        for changes in ({'waitSeconds':'-1'}, {'waitSeconds':'nan'}, {'waitSeconds':'inf'},
                        {'waitSecondsBasis':'sum_of_wait_attempts'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'Edad observada'):
                NativeDecisionAudit().consume(decision(**changes))


class ProgressMapTests(unittest.TestCase):
    @staticmethod
    def event(**changes):
        result = dict(time='60', iteration='0', elapsedSimSeconds='60', stepCount='61',
            processCpuNanos='10', wallNanos='20', linkTransitions='1', arrivals='0',
            activeVehicles='2', rerouteCalculations='0', waitSignal='1', waitStorage='2',
            waitPriority='0', forcedMoves='0', threadDeadlocks='0',
            classification='progress_observed', waitAttemptsUnit='native_decision_events_in_interval',
            waitAttempts='3', waitAttemptsByCategory='{insufficient_storage=2, signal=1}',
            waitingDistinctVehicles='2', waitingDistinctVehiclesByCategory='{insufficient_storage=1, signal=1}',
            maximumObservedWaitAgeSecondsByCategory='{insufficient_storage=20.0, signal=8.0}',
            waitDurationBasis='maximum_native_head_age_gauge_not_summed_attempts_or_reason_duration',
            waitUnknown='0', waitCongestion='0', turnRestrictions='0', storageStuckRemovals='0')
        result.update(changes)
        return result

    def test_nested_maps_preserve_following_fields_and_manifest_reconciliation(self):
        event = self.event()
        audit = NativeDecisionAudit(); audit.record_progress(ET.Element('event', event))
        fields = ', '.join(f'{key}={value}' for key,value in event.items() if key != 'time')
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'progress.log'
            log.write_text('INFO SIMZ1_PROGRESS simulatedTime=60 {'+fields+'}\n', encoding='utf8')
            rows, source = progress_log(log, 0, audit.summary())
        self.assertTrue(source['reconciled'])
        self.assertEqual(rows[0]['wait_congestion'], 0)
        self.assertEqual(rows[0]['wait_observation']['waitUnknown'], '0')
        self.assertEqual(rows[0]['wait_observation']['waitAttemptsByCategory'], event['waitAttemptsByCategory'])
        self.assertEqual(rows[0]['wait_observation']['maximumObservedWaitAgeSecondsByCategory'],
                         event['maximumObservedWaitAgeSecondsByCategory'])

    def test_legacy_flat_map_and_empty_nested_map(self):
        self.assertEqual(progress_attributes('iteration=0, waitStorage=2'), {'iteration':'0','waitStorage':'2'})
        self.assertEqual(progress_attributes('nested={}, next=3'), {'nested':'{}','next':'3'})

    def test_malformed_duplicate_or_unbalanced_map_is_rejected(self):
        for text in ('iteration=0, iteration=1', 'field={nested=1', 'field=nested=1}', 'field', '=value'):
            with self.subTest(text=text), self.assertRaises(ValueError): progress_attributes(text)

    def test_truncated_log_line_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'progress.log'
            log.write_text('INFO SIMZ1_PROGRESS simulatedTime=60 {iteration=0, nested={key=2}\n', encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'truncad'):
                progress_log(log, 0, dict(progress_samples=0, progress={}))


if __name__ == '__main__': unittest.main()
