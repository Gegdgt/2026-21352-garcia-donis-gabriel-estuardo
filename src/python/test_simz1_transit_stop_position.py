"""Queue endpoint regression including the unmodified historical bus events."""
import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile

from simz1_motion import MotionContext
from simz1_trajectories import extract
from simz1_transit_replay import TransitReplay
from test_simz1_replay_integration import fixture
from visualizador_z1 import elementos, GEOD


class TransitStopPositionTest(unittest.TestCase):
    def test_real_gzip_expedition_retains_stops_and_gateway_exit(self):
        base = Path(__file__).parent/'fixtures/simz1-transit-stop-native'
        data = json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
        contract = data['contract']
        contract['departures'] = {tuple(row['key']): row['value'] for row in contract['departures']}
        motion = MotionContext(vehicle_speeds={data['vehicle']: data['vehicle_speed']}, lanes=True)
        motion.vehicle_dimensions = {data['vehicle']: data['vehicle_dimensions']}
        motion.transit_contract = contract
        with tempfile.TemporaryDirectory(prefix='simz1-native-stop-events-') as folder:
            compressed = Path(folder)/'events.xml.gz'
            compressed.write_bytes(gzip.compress(base.with_suffix('.xml').read_bytes(), mtime=0))
            events = [row for _, row in elementos(compressed, {'event'})]
        bad_link = 'transit_osm_1274975829_0_forward'
        self.assertFalse(any(e['type'] == 'entered lane' and e.get('link') == bad_link for e in events))
        rows = extract(events, data['links'], lambda _: True, lambda _: [1, 2, 3], GEOD,
                       motion=motion, horizon=86400)
        trip = rows[0]['Trip']
        stops = trip['Transit']['activity_intervals']
        failed = next(s for s in stops if s['link_id'] == bad_link)
        self.assertEqual((failed['start'], failed['end'], failed['relative_position']), (16308, 16333, 1))
        self.assertIn('verified_no_lane_assignment', failed['position_source'])
        dwell = next(r for r in rows if r['timestamps'] == [16308, 16333])
        self.assertEqual(dwell['path'][0], dwell['path'][1])
        self.assertEqual(dwell['Distance_m'], 0)
        self.assertEqual(len(stops), 5)
        self.assertEqual(trip['Status'], 'completed')
        self.assertTrue(all(r['timestamps'][-1] <= trip['Arrival'] for r in rows))
        self.assertFalse(any(s['state'] == 'terminal' for s in stops))  # Exterior is not drawable.
        # Proves the original failure on precisely the native sequence, not on
        # an enriched fixture that invents the lane event missing in production.
        motion.transit_contract = copy.deepcopy(contract)
        motion.transit_contract.pop('single_queue_links')
        with self.assertRaisesRegex(ValueError, 'transit_stop_position_unknown'):
            extract(events, data['links'], lambda _: True, lambda _: [1, 2, 3], GEOD,
                    motion=motion, horizon=86400)

    def test_original_intermediate_and_terminal_observed_lanes(self):
        for lane, endpoint in [('original', .3), ('middle', .7), ('terminal', 1)]:
            with self.subTest(lane=lane):
                links, motion, events = fixture()
                motion.lanes = True
                motion.transit_contract['lane_exit_fractions'] = {'a': {lane: endpoint}}
                # Native order: lane entry, arrival, departure, lane exit;
                # equal timestamps preserve delivery order without sorting.
                events.insert(5, dict(type='entered lane', time='5', vehicle='bus', link='a', lane=lane))
                events.insert(8, dict(type='left lane', time='10', vehicle='bus', link='a', lane=lane))
                rows = extract(events, links, lambda _: True, lambda _: [1, 2, 3],
                               SimpleNamespace(inv=lambda *a: (0, 0, 20)), motion=motion, horizon=100)
                dwell = next(r for r in rows if r['timestamps'] == [5, 10])
                stop = dwell['Trip']['Transit']['activity_intervals'][0]
                self.assertEqual(stop['relative_position'], endpoint)
                self.assertEqual(stop['lane_id'], lane)
                self.assertEqual(dwell['Distance_m'], 0)

    def test_missing_or_already_left_lane_remains_ambiguous(self):
        for ended in (False, True):
            links, motion, events = fixture()
            motion.lanes = True
            motion.transit_contract['lane_exit_fractions'] = {'a': {'original': .3, 'terminal': 1}}
            if ended:
                events[5:5] = [dict(type='entered lane', time='4', vehicle='bus', link='a', lane='original'),
                               dict(type='left lane', time='5', vehicle='bus', link='a', lane='original')]
            with self.assertRaisesRegex(ValueError, 'transit_stop_position_unknown'):
                extract(events, links, lambda _: True, lambda _: [1, 2, 3],
                        SimpleNamespace(inv=lambda *a: (0, 0, 20)), motion=motion, horizon=100)

    def test_dispatch_clears_previous_lane_membership(self):
        _, motion, events = fixture()
        replay = TransitReplay(motion)
        replay.live_lanes['bus'] = ('a', 'previous-expedition')
        replay.consume(events[2], 2)
        self.assertNotIn('bus', replay.live_lanes)


if __name__ == '__main__':
    unittest.main()
