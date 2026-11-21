"""Small native-event fixtures; no historical gzip scan, server or MATSim."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from inspect_simz1_native_sample import inspect, inspect_failed, main, scan


class NativeSampleTests(unittest.TestCase):
    def mechanism_rows(self):
        # Entirely synthetic, including IDs, geometry and timings. No real run.
        return [
            dict(time=0, type='simz1OccupancyDomain', link='in', corridor='upstream'),
            dict(time=0, type='simz1OccupancyDomain', link='out', corridor='downstream'),
            dict(time=1, type='entered lane', vehicle='leader', link='out', lane='out.lane.0'),
            dict(time=1, type='simz1OccupancyReservation', action='ENTER', vehicle='leader', link='out',
                 corridor='downstream', reservationOrdinal=1, footprintMeters=4.6),
            dict(time=2, type='entered lane', vehicle='truck', link='in', lane='in.lane.0'),
            dict(time=2, type='simz1OccupancyReservation', action='ENTER', vehicle='truck', link='in',
                 corridor='upstream', reservationOrdinal=2, footprintMeters=12.1),
            dict(time=3, type='simz1NativeDecision', vehicle='truck', link='in', nextLink='out',
                 decision='GO', reason='turn_go'),
            dict(time=3, type='simz1OccupancyReservation', action='WAIT', vehicle='truck', link='out',
                 corridor='downstream', reservationOrdinal=0, reason='capacity_or_terminal_slot'),
            dict(time=3, type='simz1NativeDecision', vehicle='truck', link='in', nextLink='out',
                 decision='WAIT', reason='storage_wait', receivingLoadIndicator=0,
                 receivingStorageCapacityPcu=0.5765927802304195, receiverAcceptedAtDecision='false'),
            dict(time=4, type='simz1OccupancyReservation', action='TRANSFER', vehicle='leader', link='out',
                 corridor='downstream', reservationOrdinal=1, footprintMeters=4.6),
            dict(time=4, type='entered lane', vehicle='night', link='in', lane='in.original'),
            dict(time=5, type='simz1Priority', vehicle='truck', link='in', nextLink='out',
                 action='WAIT', reason='priority_fairness', reservationVehicle='synthetic_priority_owner'),
            dict(time=5, type='simz1NativeDecision', vehicle='truck', link='in', nextLink='out',
                 decision='WAIT', reason='priority_fairness'),
            dict(time=6, type='left lane', vehicle='leader', link='out', lane='out.lane.0'),
            dict(time=6, type='simz1OccupancyReservation', action='EXIT', vehicle='leader', link='out',
                 corridor='downstream', reservationOrdinal=1),
            dict(time=7, type='left lane', vehicle='truck', link='in', lane='in.lane.0'),
            dict(time=7, type='simz1OccupancyReservation', action='EXIT', vehicle='truck', link='in',
                 corridor='upstream', reservationOrdinal=2),
            dict(time=7, type='simz1OccupancyReservation', action='ENTER', vehicle='truck', link='out',
                 corridor='downstream', reservationOrdinal=3, footprintMeters=12.1),
            dict(time=7, type='entered lane', vehicle='truck', link='out', lane='out.original'),
            dict(time=7, type='simz1Admission', vehicle='truck', link='in', nextLink='out', reason='receiver_accepted'),
            dict(time=8, type='simz1OccupancyReservation', action='TRANSFER', vehicle='truck', link='out',
                 corridor='downstream', reservationOrdinal=3, footprintMeters=12.1),
            dict(time=9, type='simz1OccupancyReservation', action='EXIT', vehicle='truck', link='out',
                 corridor='downstream', reservationOrdinal=3),
            dict(time=9, type='left lane', vehicle='truck', link='out', lane='out.original'),
            dict(time=10, type='unrelated')]

    def test_mechanism_go_rejection_membership_priority_and_single_reservation_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), self.mechanism_rows())
            original = path.read_bytes()
            result = scan(path, ['truck', 'night'], 0, 9, mechanism_context=True,
                          context_links=['in', 'out'], snapshot_times=[3, 4, 5, 6, 8, 9])
            frames = {r['time']: r for r in result['snapshots'] if isinstance(r['trigger'], str)}
            self.assertEqual(frames[3]['emitted_reservations']['truck']['attributes']['corridor'], 'upstream')
            self.assertEqual(set(frames[4]['emitted_reservations']), {'truck', 'leader'})
            self.assertEqual(frames[4]['emitted_reservations']['leader']['attributes']['reservationOrdinal'], '1')
            self.assertEqual(frames[4]['lane_membership']['night']['attributes']['lane'], 'in.original')
            self.assertNotIn('leader', frames[6]['emitted_reservations'])
            self.assertNotIn('leader', frames[6]['lane_membership'])
            self.assertEqual(frames[8]['emitted_reservations']['truck']['attributes']['reservationOrdinal'], '3')
            self.assertEqual(frames[9]['emitted_reservations'], {})
            # Zero native queue load does not remove the observed lane member or
            # prove whether that member is in the buffer. No leader is invented.
            self.assertIn('leader', frames[3]['lane_membership'])
            self.assertIn('not observable', frames[3]['buffer_membership'])
            priorities = [r['attributes'] for r in frames[5]['latest_actor_evidence']
                          if r['attributes']['type'] == 'simz1Priority']
            self.assertEqual(priorities[0]['reservationVehicle'], 'synthetic_priority_owner')
            admissions = [r for r in result['records'] if r['attributes']['type'] == 'simz1Admission']
            self.assertEqual([r['time'] for r in admissions], [7])
            self.assertFalse(any(a['vehicle'] == 'night' for a in result['selected_attempts']))
            self.assertEqual(path.read_bytes(), original)

    def test_mechanism_repeated_attempts_bounded_and_incomplete_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), [
                dict(time=0, type='simz1OccupancyDomain', link='in', corridor='upstream'),
                *[dict(time=t, type='simz1NativeDecision', vehicle='v', link='in', nextLink='out',
                       reason='storage_wait', decision='WAIT') for t in range(1, 1001)],
                dict(time=1001, type='unrelated')])
            result = scan(path, ['v'], 0, 1000, mechanism_context=True, context_links=['in'], max_records=20)
            self.assertEqual(len(result['selected_attempts']), 1)
            self.assertEqual(result['selected_attempts'][0]['count'], 1000)
            self.assertEqual(result['selected_attempts'][0]['first']['time'], 1)
            self.assertEqual(result['selected_attempts'][0]['last']['time'], 1000)
            self.assertEqual(len(result['snapshots']), 1)
            with self.assertRaisesRegex(ValueError, 'max_records'):
                scan(path, ['v'], 0, 1000, mechanism_context=True, context_links=['in'], max_records=1)
            with self.assertRaisesRegex(ValueError, 'max_events'):
                scan(path, ['v'], 0, 1000, mechanism_context=True, context_links=['in'], max_events=10)
            with self.assertRaisesRegex(ValueError, 'corridor metadata'):
                scan(path, ['v'], 0, 1000, mechanism_context=True, context_links=['missing'])
            with self.assertRaisesRegex(ValueError, 'start=0'):
                scan(path, ['v'], 1, 1000, mechanism_context=True, context_links=['in'])

    def source(self, folder, rows):
        root = ET.Element('events')
        for row in rows:
            ET.SubElement(root, 'event', **{k: str(v) for k, v in row.items()})
        path = folder/'events.xml.gz'
        path.write_bytes(gzip.compress(ET.tostring(root)))
        return path

    def test_selected_identity_and_force_snapshot_survive_without_double_counting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), [
                dict(time=0, type='vehicle enters traffic', vehicle='v', person='p'),
                dict(time=1, type='simz1NativeDecision', vehicle='v', person='p', decision='WAIT', reason='storage_wait'),
                dict(time=2, type='simz1NativeDecision', vehicle='v', decision='FORCE', reason='storage_forced_move',
                     link='in', lane='in.0', nextLink='out', receivingLane='out.original', receiverAcceptedAtDecision='false'),
                dict(time=2, type='simz1Priority', vehicle='v', action='CROSS', reason='storage_forced_move'),
                dict(time=2, type='arrival', person='p'), dict(time=3, type='left link', vehicle='other')])
            result = scan(path, ['v'], 1, 2)
            self.assertEqual(result['observed_person_ids'], {'v': ['p']})
            self.assertEqual(result['record_count'], 4)
            self.assertEqual(result['selected_native_reasons']['storage_forced_move'], 1)
            self.assertEqual(result['global_native_reasons']['storage_forced_move'], 1)
            force = result['records'][1]
            self.assertEqual(force['seq'], 3)
            self.assertEqual(force['attributes']['receivingLane'], 'out.original')
            self.assertEqual(result['scan']['first_excluded_event'], dict(seq=6, time=3))

    def test_focus_force_windows_capture_other_vehicles_only_where_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), [dict(time=t, type='simz1NativeDecision', vehicle='other',
                decision='FORCE', reason='storage_forced_move', nextLink='out') for t in (0, 1, 2, 3, 4)])
            result = scan(path, ['selected'], 1, 3, global_window=(2, 3), focus_links=['out'], focus_windows=[(0, 0), (3, 3)])
            self.assertEqual([r['time'] for r in result['records']], [0, 3])
            self.assertTrue(all(r['selection'] == 'focus_link_force' for r in result['records']))
            self.assertEqual(result['global_native_reasons'], {'storage_forced_move': 2})

    def test_nonmonotone_prefix_and_read_limits_fail_without_partial_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = self.source(folder, [dict(time=t, type='left link', vehicle='v') for t in (0, 2, 1, 4)])
            with self.assertRaisesRegex(ValueError, 'Non-monotone'):
                scan(path, ['v'], 0, 3)
            path = self.source(folder, [dict(time=t, type='left link', vehicle='v') for t in (0, 1, 2, 4)])
            with self.assertRaisesRegex(ValueError, 'max_records'):
                scan(path, ['v'], 0, 3, max_records=1)
            with self.assertRaisesRegex(ValueError, 'max_events'):
                scan(path, ['v'], 0, 3, max_events=1)
            with self.assertRaisesRegex(ValueError, 'ended before'):
                scan(path, ['v'], 0, 5)

    def test_manifest_identity_and_compressed_size_are_checked_before_scanning(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = self.source(folder, [dict(time=t, type='left link', vehicle='v') for t in (0, 2)])
            manifest = dict(run_id='r', status='completed', validation=dict(status='valid'),
                            results={'0': {'events': {'path': path.name, 'sha256': 'a'*64}}})
            raw = json.dumps(manifest).encode()
            (folder/'run-manifest.json').write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            with patch('inspect_simz1_native_sample.scan') as scan_mock:
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    inspect(folder, 0, 'r', 'b'*64, path.stat().st_size, ['v'], 0, 1)
                with self.assertRaisesRegex(ValueError, 'caller-pinned size'):
                    inspect(folder, 0, 'r', sha, path.stat().st_size+1, ['v'], 0, 1)
                scan_mock.assert_not_called()
            result = inspect(folder, 0, 'r', sha, path.stat().st_size, ['v'], 0, 1)
            self.assertFalse(result['source']['content_hash_recomputed'])
            self.assertEqual(result['source']['expected_sha256'], 'a'*64)

    def test_existing_output_is_refused_before_inspection(self):
        with tempfile.TemporaryDirectory() as folder, patch('inspect_simz1_native_sample.inspect') as inspect_mock:
            with self.assertRaisesRegex(ValueError, 'carpeta nueva'):
                main(['--run-dir', folder, '--run-id', 'r', '--manifest-sha256', 'a'*64,
                      '--events-bytes', '1', '--vehicle', 'v', '--start', '0', '--end', '1', '--output-new', folder])
            inspect_mock.assert_not_called()

    def test_failed_diagnostic_includes_known_driver_before_insertion_and_link_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            iteration = folder/'output/ITERS/it.0'
            iteration.mkdir(parents=True)
            generated = self.source(iteration, [
                dict(time=34320,type='departure',person='h',link='a'),
                dict(time=34321,type='left link',vehicle='candidate',link='a'),
                dict(time=34322,type='vehicle enters traffic',person='h',vehicle='h',link='a'),
                dict(time=34323,type='left link',vehicle='other',link='b')])
            path = iteration/'0.events.xml.gz'
            path.write_bytes(generated.read_bytes())
            raw = json.dumps(dict(run_id='failed-r',status='failed',validation=dict(status='invalid'))).encode()
            (folder/'run-manifest.json').write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError,'completed/valid'):
                inspect(folder,0,'failed-r',sha,path.stat().st_size,['h'],34320,34322)
            result = inspect_failed(folder,0,'failed-r',sha,path.stat().st_size,['h'],34320,34322,
                person_ids=['h'],context_links=['a'],max_events=10,max_records=4)
            self.assertTrue(result['diagnostic_only'])
            self.assertEqual(result['evidence']['record_count'],3)
            self.assertEqual(result['evidence']['records'][0]['attributes']['type'],'departure')
            self.assertEqual(result['evidence']['records'][1]['selection'],'context_link')
            self.assertIn('unknown',result['evidence']['scan']['suffix_order'])
            self.assertNotIn('expected_sha256',result['source'])
            self.assertEqual((folder/'run-manifest.json').read_bytes(),raw)
            with patch('inspect_simz1_native_sample.scan') as scan_mock:
                with self.assertRaisesRegex(ValueError,'identity/hash'):
                    inspect_failed(folder,0,'other',sha,path.stat().st_size,['h'],34320,34322)
                scan_mock.assert_not_called()

    def test_no_diagnostic_output_inside_protected_source(self):
        with tempfile.TemporaryDirectory() as temporary, patch('inspect_simz1_native_sample.inspect_failed') as reader:
            with self.assertRaisesRegex(ValueError,'outside the source run'):
                main(['--run-dir',temporary,'--run-id','r','--manifest-sha256','a'*64,
                      '--events-bytes','1','--vehicle','h','--person','h','--failed-diagnostic',
                      '--start','34320','--end','34500','--output-new',str(Path(temporary)/'diagnostic')])
            reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
