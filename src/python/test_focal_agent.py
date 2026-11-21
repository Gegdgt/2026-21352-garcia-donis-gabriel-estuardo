import unittest
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET
from unittest.mock import patch
from microscopic_traffic import (MicroscopicPlayback, Operation, Profile,
                                 desired_speed, random_focal_profile, PlaybackClock)


class FocalTests(unittest.TestCase):
    def test_persistence_crosses_midnight_without_reset(self):
        from microscopic_traffic import FocalContinuousCache
        roads = {
            'a': dict(length=100, lanes=1, lane_width=3.8, freespeed=10, capacity=800,
                      from_id='a', to_id='b', **{'from':(0,0), 'to':(100,0)}),
            'b': dict(length=100, lanes=1, lane_width=3.8, freespeed=10, capacity=800,
                      from_id='b', to_id='a', **{'from':(100,0), 'to':(0,0)})}
        engine = MicroscopicPlayback({'focal':[Operation('a',0,0)]}, roads, dt=.5,
                                     focal=True, persistent=True)
        cache = FocalContinuousCache(engine)
        beginning = cache.at(0)
        before = cache.at(86399.5)['focal']
        after = cache.at(86400.5)['focal']
        self.assertEqual(after.elapsed_time-before.elapsed_time, 1)
        self.assertGreater(after.travelled_distance, before.travelled_distance)
        self.assertGreaterEqual(after.max_speed, before.max_speed)
        self.assertEqual(engine.completed, 0)
        self.assertEqual(cache.at(0), beginning)
        self.assertTrue(all(set(frame)=={'focal'} for frame in cache.history))

    def test_fractional_interpolation_preserves_history(self):
        from types import SimpleNamespace
        from microscopic_traffic import Sample, FocalContinuousCache
        a = Sample('a', 0, 0, 2, 'drive', elapsed_time=0, min_speed=0, max_speed=2)
        b = Sample('a', 0, 2, 6, 'drive', elapsed_time=.5, min_speed=0, max_speed=6)
        c = Sample('b', 0, 0, 6, 'drive', elapsed_time=1, min_speed=0, max_speed=6)
        engine = SimpleNamespace(dt=.5, frames=lambda **kw: iter([(0,{'f':a}),(.5,{'f':b}),(1,{'f':c})]))
        cache = FocalContinuousCache(engine)
        mid = cache.at(.25)['f']
        self.assertEqual((mid.distance,mid.speed,mid.elapsed_time),(1,4,.25))
        self.assertEqual(mid.max_speed,4)
        self.assertEqual(cache.at(.75)['f'],b)
        self.assertEqual(cache.at(0)['f'],a)
        self.assertEqual(cache.at(.25)['f'],mid)

    def test_physical_geometry_and_swept_obstacles(self):
        import math
        from microscopic_traffic import vehicle_hitbox, polygons_overlap
        road = dict(length=200, lanes=1, lane_width=3.2, freespeed=10,
                    **{'from': (0, 0), 'to': (200, 0)})
        box = vehicle_hitbox(road, 50, 0)
        self.assertAlmostEqual(math.dist(box[0], box[1]), 4.5)
        self.assertAlmostEqual(math.dist(box[1], box[2]), 1.8)
        self.assertTrue(polygons_overlap(box, vehicle_hitbox(road, 52, 0)))
        self.assertFalse(polygons_overlap(box, vehicle_hitbox(road, 60, 0)))
        route = {'focal': [Operation('a', 0, 0)]}
        with self.assertRaisesRegex(ValueError, 'hitbox'):
            MicroscopicPlayback(route, {'a': road}, focal=True, obstacles=[[99.99,-1,100.01,1]])
        MicroscopicPlayback(route, {'a': road}, focal=True, obstacles=[[90,20,91,21]])

    def test_extrema_and_clock_survive_seek(self):
        from microscopic_traffic import Sample, DayFrameCache
        a = Sample('a', 0, 0, 5, 'drive', elapsed_time=3661, min_speed=0, max_speed=9)
        b = Sample('a', 0, 10, 10, 'drive', elapsed_time=3662, min_speed=0, max_speed=10)
        cache = DayFrameCache([(0, {'f': a}), (1, {'f': b})], duration=1, spacing=1)
        self.assertEqual(a.elapsed_clock, '01:01:01')
        self.assertEqual(cache.at(1)['f'].max_speed, 10)
        self.assertEqual(cache.at(0)['f'].max_speed, 9)
        self.assertEqual(cache.at(.5)['f'].max_speed, 9)

    def test_export_and_daily_interface(self):
        output = Path(__file__).resolve().parents[1] / 'output/labs/08-zona1-historic'
        if not (output / 'output_events.xml.gz').exists():
            self.skipTest('Generate Lab08 first')
        with gzip.open(output / 'output_plans.xml.gz', 'rb') as stream:
            people = ET.parse(stream).getroot().findall('person')
        self.assertEqual(len(people), 1)
        with gzip.open(output / 'output_network.xml.gz', 'rb') as stream:
            network = ET.parse(stream).getroot()
        nodes = network.findall('nodes/node')
        self.assertEqual(len(nodes), 166)
        expected = {f'A{a}_C{c}' for a in range(2,13) for c in range(4,19)} - {'A7_C7'}
        self.assertEqual({n.get('id') for n in nodes}, expected | {'D_7_13','D_9_14'})
        pairs = {(l.get('from'),l.get('to')) for l in network.findall('links/link')}
        for a in range(5,9):
            self.assertNotIn((f'A{a}_C7',f'A{a+1}_C7'),pairs)
            self.assertNotIn((f'A{a+1}_C7',f'A{a}_C7'),pairs)
        for name in ('palacio','plaza','colon'):
            self.assertIsNotNone(network.find(f"attributes/attribute[@name='visualArea.{name}']"))
        for link in network.findall('links/link'):
            if link.get('id').startswith('PASSAGE_'):
                self.assertEqual(link.get('modes'), 'walk')
                continue
            self.assertIn(float(link.get('permlanes')), (2,3,4))
            self.assertEqual(float(link.find("attributes/attribute[@name='laneWidth']").text), 3.8)
        self.assertIn(people[0].find("attributes/attribute[@name='drivingProfile']").text,
                      ('normal', 'tortuga', 'liebre'))
        with gzip.open(output / 'output_events.xml.gz', 'rb') as stream:
            events = ET.parse(stream).getroot().findall('event')
        self.assertTrue(all(float(e.get('time')) >= 86400 for e in events if e.get('type') == 'stuckAndAbort'))
        self.assertEqual(sum(e.get('type') == 'actstart' and e.get('actType') == 'work' for e in events), 0)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from visualize_network import animate_simulation
        from visualize_network import load_map_registration
        if load_map_registration(output/'output_network.xml.gz') != 'EPSG:32615':
            with self.assertRaisesRegex(ValueError,'regenerate'):
                animate_simulation(output/'output_network.xml.gz',output/'output_events.xml.gz',
                                   'legacy',dt=.5,daily=True,focal=True)
            plt.close('all')
            return
        with patch.object(plt, 'show'), patch('visualize_network.ctx.add_basemap'):
            animate_simulation(output / 'output_network.xml.gz', output / 'output_events.xml.gz',
                               'Lab08 test', dt=.5, daily=True, focal=True, playback_speed=120)
        fig = plt.gcf()
        controls = fig._playback_controls
        for t in (0, 60, 64800, 10):
            controls.slider.set_val(t)
            self.assertEqual(fig._agent_inspector.time, t)
            self.assertLessEqual(len(fig._day_cache.at(t)), 1)
        controls.close()
        plt.close(fig)

    def test_uniform_choices_and_temporal_independence(self):
        for kind in ('normal', 'tortuga', 'liebre'):
            with patch('microscopic_traffic.random.SystemRandom') as source:
                source.return_value.choice.return_value = kind
                source.return_value.gauss.return_value = 1.0
                profile = random_focal_profile()
                source.return_value.choice.assert_called_once_with(('normal', 'tortuga', 'liebre'))
            expected = dict(normal=10, tortuga=3, liebre=15)[kind]
            for hour in (0, 3, 6, 12, 18, 23):
                self.assertEqual(desired_speed(profile, dict(freespeed=10, extreme_night=True), time=hour*3600), expected)

    def test_one_draw_per_run_and_safe_arrival_for_all_profiles(self):
        road = dict(length=200, lanes=1, capacity=600, freespeed=10,
                    **{'from': (0, 0), 'to': (200, 0)})
        for kind in ('normal', 'tortuga', 'liebre'):
            profile = Profile(1.5 if kind == 'liebre' else 1, 0, kind=kind)
            with patch('microscopic_traffic.random_focal_profile', return_value=profile) as draw:
                engine = MicroscopicPlayback({'focal': [Operation('a', 0, 0)]}, {'a': road}, focal=True)
                frames = list(engine.frames(start_time=0, end_time=180))
                draw.assert_called_once_with()
            self.assertEqual(engine.completed, 1)
            self.assertEqual(engine.peak_active, 1)
            self.assertTrue(any(frame for _, frame in frames))
            for _, frame in frames:
                self.assertLessEqual(len(frame), 1)
                for sample in frame.values():
                    self.assertTrue(0 <= sample.distance <= 200)
                    self.assertTrue(0 <= sample.speed <= desired_speed(profile, road))
            with self.assertRaises(ValueError):
                list(engine.frames(cycles=2, repeat_period=86400))

    def test_clock_30_real_seconds_per_simulated_hour(self):
        now = [0]
        clock = PlaybackClock(now=lambda: now[0])
        clock.tick()
        now[0] = 30
        clock.tick()
        self.assertEqual(clock.time / 3600, 1)

    def test_rejects_multiple_agents(self):
        with self.assertRaises(ValueError):
            MicroscopicPlayback({'a': [], 'b': []}, {}, focal=True)


if __name__ == '__main__':
    unittest.main()
