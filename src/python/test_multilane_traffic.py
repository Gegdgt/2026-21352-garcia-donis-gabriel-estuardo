import unittest
from unittest.mock import patch
from collections import defaultdict
from microscopic_traffic import (Vehicle, Profile, Operation, lane_change_candidate,
                                 MicroscopicPlayback, desired_speed, position, GAP)
from traffic_routing import balanced_routes


def road(lanes=2):
    return dict(length=400, lanes=lanes, capacity=lanes*800, freespeed=20,
                lane_changing=True, **{'from': (0, 0), 'to': (400, 0)})


class MultiLaneTests(unittest.TestCase):
    def test_checkpoint_resume_preserves_motion_waiting_and_telemetry(self):
        import pickle
        from benchmark_traffic import capture_state
        roads = {'l': dict(road(2),length=100,lane_width=3.2,max_active=6)}
        routes = {str(i): [Operation('l',i/2,i/2)] for i in range(30)}
        engine = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        stream = engine.frames(start_time=0,end_time=60)
        for t,frame in stream:
            if t == 10:
                saved = pickle.dumps((engine,capture_state(engine,stream)))
                break
        expected = [(t,dict(f)) for t,f in stream]
        restored,state = pickle.loads(saved)
        self.assertEqual([(t,dict(f)) for t,f in restored.frames(start_time=0,end_time=60,resume_state=state)],expected)
        self.assertEqual(restored.completed,engine.completed)
        self.assertEqual(restored.lane_change_log,engine.lane_change_log)

    def test_spillback_before_link_endpoint_is_certified_exactly(self):
        roads = {str(i): dict(road(1),length=16,max_active=6,lane_width=3.2,
                              from_id=str(i),to_id=str((i+1)%3)) for i in range(3)}
        routes = {f'{i}-{d}': [Operation(str(i),0,0,first=d/16),Operation(str((i+1)%3),0,0)]
                  for i in range(3) for d in (0,8)}
        with patch('microscopic_traffic.absorbing_gridlock',return_value=False):
            expected = [(t,dict(f)) for t,f in MicroscopicPlayback(routes,roads,.5,synthetic_stops=False).frames(start_time=0,end_time=120)]
        engine = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        self.assertEqual([(t,dict(f)) for t,f in engine.frames(start_time=0,end_time=120)],expected)
        self.assertEqual(engine.gridlock_time,0)

    def test_certified_gridlock_matches_every_unoptimized_frame(self):
        roads = {str(i): dict(road(1), length=16, max_active=9, lane_width=3.2,
                              from_id=str(i), to_id=str((i+1)%3)) for i in range(3)}
        routes = {f'{i}-{d}': [Operation(str(i),0,0,first=d/16),
                              Operation(str((i+1)%3),0,0)]
                  for i in range(3) for d in (0,8,16)}
        routes['later'] = [Operation('0',61,61)]
        baseline = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        with patch('microscopic_traffic.absorbing_gridlock',return_value=False):
            expected = [(t,dict(f)) for t,f in baseline.frames(start_time=0,end_time=120)]
        engine = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        actual = [(t,dict(f)) for t,f in engine.frames(start_time=0,end_time=120)]
        self.assertEqual(actual,expected)
        self.assertEqual(engine.gridlock_time,0)
        self.assertEqual(engine.completed,0)
        self.assertNotIn('later',actual[-1][1])
        self.assertEqual(len(actual[-1][1]),9)

    def test_future_release_prevents_gridlock_certificate(self):
        from microscopic_traffic import absorbing_gridlock
        roads = {'l': dict(road(1), lane_width=3.2)}
        v = Vehicle('v',[Operation('l',0,100)],Profile(1,0),distance=400)
        self.assertFalse(absorbing_gridlock({'v':v},{('l',0):[v]},roads,{},10,1,True,True))

    def test_check_rejects_valid_frames_that_never_drain(self):
        import io
        from contextlib import redirect_stdout
        import visualize_network as visual
        roads = {str(i): dict(road(1), length=16, max_active=9, lane_width=3.2,
                              from_id=str(i), to_id=str((i+1)%3)) for i in range(3)}
        routes = {f'{i}-{d}': [Operation(str(i),0,0,first=d/16),Operation(str((i+1)%3),0,0)]
                  for i in range(3) for d in (0,8,16)}
        with patch.object(visual,'load_network',return_value=({},roads)), \
             patch.object(visual,'load_special_areas',return_value=[]), \
             patch.object(visual,'read_operations',return_value=routes), \
             patch.object(visual,'DAY_SECONDS',120), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'Validacion de descarga fallida'):
                visual.animate_simulation('fixture','fixture','test',dt=.5,synthetic_stops=False,
                                           check=True,daily=True,playback_speed=600,routing='observed')

    def test_blocked_departure_after_parking_matches_reference(self):
        roads = {str(i): dict(road(1), length=16, max_active=9, lane_width=3.2,
                              from_id=str(i), to_id=str((i+1)%3)) for i in range(3)}
        routes = {f'{i}-{d}': [Operation(str(i),0,0,first=d/16),
                              Operation(str((i+1)%3),0,0)]
                  for i in range(3) for d in (0,8,16)}
        routes['0-16'][0] = Operation('0',0,3,1,1,'parking')
        with patch('microscopic_traffic.absorbing_gridlock',return_value=False):
            expected = [(t,dict(f)) for t,f in MicroscopicPlayback(routes,roads,.5,synthetic_stops=False).frames(start_time=0,end_time=120)]
        engine = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        self.assertEqual([(t,dict(f)) for t,f in engine.frames(start_time=0,end_time=120)],expected)
        self.assertEqual(engine.gridlock_time,60)

    def test_index_matches_linear_search_after_sequential_reservations(self):
        from microscopic_traffic import LaneIndex
        vehicles = [Vehicle(str(i), [Operation('l', 0, 0)], Profile(1, 0),
                            lane=i%4, distance=20+(i//4)*11+i%4, speed=i%13)
                    for i in range(100)]
        occupied = defaultdict(list)
        for vehicle in vehicles:
            occupied['l', vehicle.lane].append(vehicle)
        index = LaneIndex(occupied)
        for vehicle in sorted(vehicles, key=lambda v: -v.distance):
            expected = lane_change_candidate(vehicle, road(4), occupied, 10, 20)
            actual = lane_change_candidate(vehicle, road(4), occupied, 10, 20, index)
            self.assertEqual(actual, expected)
            if actual is not None:
                old = vehicle.lane
                index.move(vehicle, old, actual)
                occupied['l', old].remove(vehicle)
                vehicle.lane = actual
                occupied['l', actual].append(vehicle)

    def test_blocked_entry_preserves_fifo_without_starving_other_entry(self):
        links = {key: dict(road(1), length=60, lane_width=3.2) for key in ('a', 'b')}
        routes = {'blocker': [Operation('a', 0, 30, 0, 0, kind='parking')]}
        routes.update({f'wait{i:03}': [Operation('a', 1, 1)] for i in range(80)})
        routes['free'] = [Operation('b', 2, 2)]
        engine = MicroscopicPlayback(routes, links, .5, synthetic_stops=False)
        first_seen = {}
        for time, frame in engine.frames(start_time=0):
            for agent in frame:
                first_seen.setdefault(agent, time)
        self.assertEqual(first_seen['free'], 2)
        self.assertGreaterEqual(first_seen['wait000'], 30)
        self.assertEqual(sorted((time, agent) for agent, time in first_seen.items()
                                if agent.startswith('wait')),
                         [(first_seen[f'wait{i:03}'], f'wait{i:03}') for i in range(80)])
        self.assertEqual(engine.completed, len(routes))

    def test_marker_width_stays_inside_lane_when_zooming(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from visualize_network import render_agents
        from microscopic_traffic import Sample
        fig, ax = plt.subplots()
        links = {'l': dict(road(4), lane_width=3.2)}
        points = ax.scatter([], [])
        try:
            for extent in (2000, 200):
                ax.set_xlim(0, extent)
                ax.set_ylim(0, extent)
                ax.set_aspect('equal')
                fig.canvas.draw()
                render_agents(points, {'v': Sample('l', 1, 100, 10, 'drive', 'test')}, links)
                diameter = points.get_sizes()[0] ** .5 * fig.dpi / 72
                origin, edge = ax.transData.transform([(0, 0), (3.2, 0)])
                self.assertLess(diameter, edge[0] - origin[0])
                self.assertGreater(diameter, 0)
        finally:
            plt.close(fig)

    def test_batched_routing_preserves_od_connectivity_and_determinism(self):
        links = {str(i): dict(road(), from_id=str(i), to_id=str((i+1) % 4)) for i in range(4)}
        routes = {str(i): [Operation('0', i, i+1), Operation('1', i+1, i+2)] for i in range(24)}
        first = balanced_routes(routes, links, batch_size=4)
        self.assertEqual(first, balanced_routes(routes, links, batch_size=4))
        for ops in first.values():
            self.assertEqual(ops[0].link, '0')
            self.assertEqual(ops[-1].link, '1')
            for a, b in zip(ops, ops[1:]):
                self.assertEqual(links[a.link]['to_id'], links[b.link]['from_id'])

    def test_incentive_front_rear_gap_and_cooldown(self):
        fast = Vehicle('fast', [Operation('l', 0, 0)], Profile(1, 0),
                       distance=60, speed=12)
        slow = Vehicle('slow', fast.ops, Profile(.3, 0), distance=80, speed=4)
        occupied = {('l', 0): [fast, slow], ('l', 1): []}
        self.assertEqual(lane_change_candidate(fast, road(), occupied, 10, 20), 1)
        rear = Vehicle('rear', fast.ops, Profile(1, 0), lane=1, distance=40, speed=20)
        occupied['l', 1] = [rear]
        self.assertIsNone(lane_change_candidate(fast, road(), occupied, 10, 20))
        rear.distance = 65
        self.assertIsNone(lane_change_candidate(fast, road(), occupied, 10, 20))
        occupied['l', 1] = []
        fast.last_lane_change = 8
        self.assertIsNone(lane_change_candidate(fast, road(), occupied, 10, 20))
        fast.last_lane_change = 0
        self.assertIsNone(lane_change_candidate(fast, road(1), occupied, 10, 20))

    def test_faster_vehicle_changes_lane_and_overtakes_without_overlap(self):
        routes = {'slow': [Operation('l', 0, 0, .25)],
                  'fast': [Operation('l', 0, 0, .18)]}
        engine = MicroscopicPlayback(routes, {'l': road()}, dt=.2, synthetic_stops=False)
        overtook = False
        with patch('microscopic_traffic.lane_for', return_value=0), \
             patch('microscopic_traffic.agent_profile', side_effect=lambda a: Profile(.3 if a=='slow' else 1, 0)):
            for time, frame in engine.frames():
                by_lane = defaultdict(list)
                for sample in frame.values():
                    by_lane[sample.lane].append(sample.distance)
                for distances in by_lane.values():
                    distances.sort()
                    self.assertTrue(all(b-a >= GAP-1e-8 for a,b in zip(distances, distances[1:])))
                if 'fast' in frame and 'slow' in frame:
                    overtook |= frame['fast'].distance > frame['slow'].distance
        self.assertTrue(overtook)
        self.assertGreater(len(engine.lane_change_log), 0)
        self.assertEqual(engine.completed, 2)

    def test_width_and_night_multiplier(self):
        r = dict(road(4), lane_width=3.2, extreme_night=True)
        offsets = [position(r, 100, lane)[1] for lane in range(4)]
        self.assertEqual(len(set(offsets)), 4)
        self.assertTrue(all(abs(y) < 6.4 for y in offsets))
        p = Profile(.7, 0, night_factor=2)
        self.assertEqual(desired_speed(p, r, time=0), 40)
        self.assertEqual(desired_speed(p, r, time=5*3600), 14)
        self.assertEqual(desired_speed(p, r, aggressive=False, time=0), 14)

    def test_active_limit_keeps_unadmitted_demand(self):
        r = dict(road(3), lane_width=3.2, max_active=3)
        routes = {str(i): [Operation('l', 0, 0)] for i in range(12)}
        engine = MicroscopicPlayback(routes, {'l': r}, dt=.5, synthetic_stops=False)
        for _, frame in engine.frames():
            self.assertLessEqual(len(frame), 3)
        self.assertEqual(engine.completed, 12)
        self.assertEqual(engine.peak_active, 3)

    def test_three_to_one_lane_merge_shares_receiving_space(self):
        roads = {'a': dict(road(3), length=50, lane_width=3.2, from_id='n0', to_id='n1'),
                 'b': dict(road(1), length=60, lane_width=3.2, from_id='n1', to_id='n2')}
        routes = {str(i): [Operation('a', 0, 0), Operation('b', 0, 0)] for i in range(30)}
        engine = MicroscopicPlayback(routes, roads, dt=.5, synthetic_stops=False)
        entered_lanes = set()
        for _, frame in engine.frames():
            lanes = defaultdict(list)
            for sample in frame.values():
                lanes[sample.link, sample.lane].append(sample.distance)
                if sample.link == 'a':
                    entered_lanes.add(sample.lane)
                else:
                    self.assertEqual(sample.lane, 0)
            for distances in lanes.values():
                distances.sort()
                self.assertTrue(all(b-a >= GAP-1e-8 for a,b in zip(distances,distances[1:])))
        self.assertEqual(entered_lanes, {0, 1, 2})
        self.assertEqual(engine.completed, 30)


if __name__ == '__main__':
    unittest.main()
