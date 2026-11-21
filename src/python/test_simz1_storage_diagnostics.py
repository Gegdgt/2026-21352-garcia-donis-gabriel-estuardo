"""Tiny in-memory events and queue inputs; no run, population or historical files."""
import unittest
import xml.etree.ElementTree as ET

from simz1_native_validation import NativeDecisionAudit
from simz1_lane_validation import screen_storage


def decision(reason, **changes):
    values = dict(type='simz1NativeDecision', time='11', link='in', lane='in.0', nextLink='out',
        vehicle='v1', reason=reason, decision={'storage_wait': 'WAIT', 'storage_forced_move': 'FORCE',
            'storage_stuck_removal': 'ABORT'}.get(reason, 'WAIT'), waitSeconds='11', stuckTime='10',
        removeStuckVehicles='true' if reason == 'storage_stuck_removal' else 'false',
        signalState='GREEN', nativeHasGreen='true')
    values.update(changes)
    return ET.Element('event', {key: str(value) for key, value in values.items()})


def observation(reason='storage_forced_move', **changes):
    values = dict(storageObservationVersion='1', receivingLane='out.original',
        receiverAcceptedAtDecision='false', storageSnapshot='sampled_wait' if reason == 'storage_wait' else 'intervention',
        receivingQueueType='QueueWithBuffer', receivingLoadIndicator='1', receivingLoadSemantics='pcu_excluding_buffer',
        receivingStorageCapacityPcu='1', receivingFlowCapacityPcuPerStep='.05', vehicleSizePcu='1',
        receiverExitQueues='2', receiverExitQueuesRejecting='2', receiverExitQueuesOffering='2',
        receiverExitHeadsSignalBlocked='1', snapshotConsistency='non_atomic_read_only')
    values.update(changes)
    return decision(reason, **values)


class StorageDiagnosticsTests(unittest.TestCase):
    def test_wait_force_and_removal_are_separate_not_unique_vehicles(self):
        audit = NativeDecisionAudit()
        for event in (observation('storage_wait', waitSeconds='10'), observation(), observation(time='21'),
                      observation('storage_stuck_removal', vehicle='v2')):
            audit.consume(event)
        # Descriptions of the same crossing must not count again.
        audit.consume(decision('storage_forced_move', type='simz1Priority'))
        result = audit.summary()
        self.assertEqual(result['forced_storage_moves'], 2)
        self.assertEqual(result['storage_stuck_removals'], 1)
        storage = result['storage_diagnostics']
        self.assertEqual(storage['unique_intervention_vehicles']['storage_forced_move'], 1)
        self.assertEqual(storage['unique_vehicles_any_intervention'], 2)
        self.assertEqual(storage['coverage']['intervention_snapshots'], 3)
        self.assertEqual(storage['top_movements'][0]['receiving_lane'], 'out.original')
        self.assertFalse(result['physical_stability']['proven'])

    def test_receiving_storage_and_terminal_pressure_are_observations(self):
        audit = NativeDecisionAudit()
        audit.consume(observation())
        # Concurrent readings may see a lower load after the recorded rejection.
        # That is retained as evidence, not relabeled as a proven capacity bug.
        audit.consume(observation(receivingLoadIndicator='.5', receiverExitHeadsSignalBlocked='0'))
        counts = audit.summary()['storage_diagnostics']['snapshots_by_branch']['storage_forced_move']
        self.assertEqual(counts['receiver_at_or_above_storage_threshold'], 1)
        self.assertEqual(counts['receiver_below_storage_threshold'], 1)
        self.assertEqual(counts['receiver_has_rejecting_exit_queue'], 2)
        self.assertEqual(counts['receiver_has_signal_blocked_exit_head'], 1)

    def test_old_events_do_not_invent_occupancy_or_missing_vehicle_ids(self):
        audit = NativeDecisionAudit()
        event = decision('storage_forced_move')
        del event.attrib['vehicle']
        audit.consume(event)
        result = audit.summary()['storage_diagnostics']
        self.assertEqual(result['coverage']['legacy_events_without_receiver_observation'], 1)
        self.assertEqual(result['snapshots_by_branch'], {})
        self.assertIsNone(result['unique_vehicles_any_intervention'])

    def test_parallel_unavailable_head_keeps_storage_counts_and_source_identity(self):
        audit = NativeDecisionAudit()
        for reason in ('storage_wait', 'storage_forced_move', 'storage_stuck_removal'):
            audit.consume(observation(reason, storageObservationVersion='2',
                receiverExitHeadObservation='unavailable_parallel_qsim', receiverExitHeadsSignalBlocked='unknown'))
        result = audit.summary()
        self.assertEqual(result['forced_storage_moves'], 1)
        self.assertEqual(result['storage_stuck_removals'], 1)
        storage = result['storage_diagnostics']
        self.assertEqual(storage['unique_vehicles_any_intervention'], 1)
        self.assertEqual(storage['coverage']['unavailable_parallel_qsim'], 3)
        for branch in storage['snapshots_by_branch'].values():
            self.assertEqual(branch['receiver_exit_head_signal_unavailable'], 1)
            self.assertEqual(branch['receiver_at_or_above_storage_threshold'], 1)
            self.assertNotIn('receiver_has_signal_blocked_exit_head', branch)

    def test_serial_observed_and_unavailable_v2_are_distinct(self):
        audit = NativeDecisionAudit()
        audit.consume(observation(storageObservationVersion='2', receiverExitHeadObservation='observed_serial'))
        audit.consume(observation(storageObservationVersion='2', receiverExitHeadObservation='unavailable_head',
                                  receiverExitHeadsSignalBlocked='unknown'))
        result = audit.summary()['storage_diagnostics']
        branch = result['snapshots_by_branch']['storage_forced_move']
        self.assertEqual(branch['receiver_has_signal_blocked_exit_head'], 1)
        self.assertEqual(branch['receiver_exit_head_signal_unavailable'], 1)
        self.assertEqual(result['coverage']['unavailable_head'], 1)
        for status, blocked in [('unavailable_head', '0'), ('unavailable_parallel_qsim', '1'),
                                ('observed_serial', 'unknown'), ('unrecognized', 'unknown')]:
            with self.subTest(status=status, blocked=blocked), self.assertRaises(ValueError):
                NativeDecisionAudit().consume(observation(storageObservationVersion='2',
                    receiverExitHeadObservation=status, receiverExitHeadsSignalBlocked=blocked))

    def test_unsampled_v2_keeps_waits_without_inventing_observations(self):
        audit = NativeDecisionAudit()
        audit.consume(decision('storage_wait', waitSeconds='10', storageObservationVersion='2',
            receivingLane='out.original', receiverAcceptedAtDecision='false', storageSnapshot='not_sampled'))
        result = audit.summary()['storage_diagnostics']
        self.assertEqual(result['counts']['storage_wait'], 1)
        self.assertEqual(result['snapshots_by_branch'], {})

    def test_normal_red_priority_and_flow_waits_are_not_storage_interventions(self):
        audit = NativeDecisionAudit()
        for reason, category in [('signal_red', 'signal'), ('priority_stop', 'mandatory_stop'),
                ('priority_yield_conflict', 'yield'), ('congestion_queue', 'congestion')]:
            audit.consume(decision(reason, waitCategory=category, waitSeconds='30'))
        audit.consume(observation('storage_wait', waitSeconds='10'))
        audit.consume(decision('storage_wait', waitSeconds='10', storageObservationVersion='1',
            receivingLane='out.original', receiverAcceptedAtDecision='false', storageSnapshot='not_sampled'))
        result = audit.summary()
        self.assertEqual(result['forced_storage_moves'], 0)
        self.assertEqual(result['storage_stuck_removals'], 0)
        self.assertEqual(result['storage_diagnostics']['coverage']['sampled_wait_snapshots'], 1)
        self.assertEqual(result['wait_categories']['signal'], 1)
        self.assertEqual(result['wait_categories']['yield'], 1)

    def test_inconsistent_branch_or_snapshot_is_rejected(self):
        for changes in (dict(waitSeconds='10'), dict(removeStuckVehicles='true'),
                        dict(receiverAcceptedAtDecision='true'), dict(storageSnapshot='not_sampled'),
                        dict(receiverExitHeadsSignalBlocked='3'), dict(receivingLoadIndicator='NaN'),
                        dict(decision='WAIT')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                NativeDecisionAudit().consume(observation(**changes))

    def test_progress_removal_deltas_do_not_double_count_native_events(self):
        audit = NativeDecisionAudit()
        progress = dict(type='simz1Progress', time='60', elapsedSimSeconds='60', stepCount='61',
            wallNanos='100', processCpuNanos='50', linkTransitions='0', arrivals='0', activeVehicles='1',
            rerouteCalculations='0', waitSignal='0', waitStorage='2', waitPriority='0', forcedMoves='0',
            storageStuckRemovals='1', threadDeadlocks='0', classification='traffic_wait_observed')
        audit.consume(ET.Element('event', progress))
        audit.consume(observation('storage_stuck_removal'))
        result = audit.summary()
        self.assertEqual(result['progress']['storage_stuck_removals'], 1)
        self.assertEqual(result['storage_stuck_removals'], 1)
        self.assertEqual(result['decisions'], 1)

    def test_short_receiving_queue_low_flow_and_unsplit_baseline_are_distinct(self):
        links = {'x': dict(modes=['car'], length=6., lanes=1., capacity=180., freespeed=10.)}
        lanes = {'x': {'x.original': dict(start=6., represented=1., capacity=180., to_lanes=['x.0'], to_links=[]),
                       'x.0': dict(start=4.8, represented=1., capacity=180., to_lanes=[], to_links=['y'])}}
        detailed = screen_storage(links, lanes, 3600, 7.5, 1, 1, 1, 'queue', 10)
        self.assertEqual(detailed['counts']['queues_screened'], 2)
        self.assertEqual(detailed['counts']['nominal_headway_exceeds_stuck_time'], 2)
        self.assertEqual(detailed['examples'][0]['role'], 'receiving')
        self.assertAlmostEqual(detailed['examples'][0]['effective_length_m'], 1.2)
        self.assertAlmostEqual(detailed['examples'][0]['threshold_pcu'], .16)
        undivided = screen_storage(links, {}, 3600, 7.5, 1, 1, 1, 'queue', 10)
        self.assertEqual(undivided['counts']['queues_screened'], 1)
        self.assertEqual(undivided['examples'][0]['role'], 'undivided')
        self.assertEqual(links['x']['capacity'], 180.)
        self.assertEqual(detailed['status'], 'screening_not_causal_proof')


if __name__ == '__main__':
    unittest.main()
