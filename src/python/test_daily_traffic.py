import unittest
from unittest.mock import patch
from microscopic_traffic import (
    day_time, daily_operations, DayFrameCache, Sample, Operation,
    MicroscopicPlayback, desired_speed, Profile, GAP,
)


class DailyTests(unittest.TestCase):
    def test_animation_uses_wall_clock_not_callback_count(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import visualize_network as view
        road = dict(length=50, lanes=1, capacity=600, freespeed=8,
                    **{'from': (0, 0), 'to': (50, 0)})
        with patch.object(view, 'load_network', return_value=({}, {'l': road})), \
             patch.object(view, 'load_special_areas', return_value=[]), \
             patch.object(view, 'load_points_of_interest', return_value=[]), \
             patch.object(view, 'read_operations', return_value={'a': [Operation('l', 5, 10)]}), \
             patch.object(view, 'PeriodicFrameCache') as cache, patch.object(plt, 'show'), \
             patch.object(view.wall_time, 'perf_counter', side_effect=[100, 130, 820]):
            cache.return_value.at.return_value = {}
            try:
                view.animate_simulation('network', 'events', 'Test', dt=.5,
                                        daily=True, playback_speed=120)
                fig = plt.gcf()
                animation = fig._traffic_animation
                animation._func(0)
                animation._func(1)
                self.assertIn('01:00:00', fig._clock_text.get_text())
                animation._func(2)
                self.assertEqual([c.args[0] for c in cache.return_value.at.call_args_list][-3:],
                                 [0, 3600, 86400])
            finally:
                plt.close('all')

    def test_wall_clock_mapping(self):
        self.assertEqual(day_time(30), 3600)
        self.assertEqual(day_time(720), 86400)
        self.assertEqual(day_time(1600), 86400)
        self.assertEqual(day_time(165), 19800)  # 05:30
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                day_time(value)

    def test_daily_release_and_activity_duration(self):
        result = daily_operations({'a': [Operation('l', 50, 90),
                                        Operation('l', 90, 93, 1, 1, 'parking')]})['a']
        self.assertEqual(result[0].start, 50)
        self.assertEqual(result[0].end, 50)
        self.assertEqual(result[1].end - result[1].start, 3)

    def test_night_speed_is_explicit_and_time_dependent(self):
        road = dict(freespeed=12.5, night_freespeed=75 / 3.6)
        self.assertAlmostEqual(desired_speed(Profile(1, 0), road, time=0)*3.6, 75)
        self.assertEqual(desired_speed(Profile(1, 0), road, time=5*3600), 12.5)
        self.assertEqual(desired_speed(Profile(1, 0), road, False, time=0), 12.5)
        self.assertEqual(desired_speed(Profile(1, 0), dict(freespeed=7), time=0), 7)

    def test_cache_interpolates_motion_and_preserves_transition_gaps(self):
        start = {'leader': Sample('l', 0, 20, 4, 'drive'),
                 'follower': Sample('l', 0, 12, 4, 'drive')}
        end = {'leader': Sample('l', 0, 40, 0, 'queued'),
               'follower': Sample('l', 0, 30, 4, 'drive')}
        cache = DayFrameCache([(0, start), (4, end)], duration=4)
        for t in (0, 1, 2, 3, 4):
            frame = cache.at(t)
            self.assertGreaterEqual(frame['leader'].distance - frame['follower'].distance, GAP)
        moving = DayFrameCache([(0, {'a': start['leader']}),
                               (4, {'a': Sample('l', 0, 40, 4, 'drive', elapsed_time=4,
                                                travelled_distance=20)})], duration=4)
        self.assertEqual(moving.at(2)['a'].distance, 30)
        self.assertEqual(moving.at(2)['a'].travelled_distance, 10)
        with self.assertRaises(ValueError):
            DayFrameCache([(1, start), (5, end)], duration=4)

    def test_full_window_includes_empty_times_after_completion(self):
        links = {'l': dict(length=5, lanes=1, capacity=3600, freespeed=5,
                           **{'from': (0, 0), 'to': (5, 0)})}
        engine = MicroscopicPlayback({'a': [Operation('l', 2, 2)]}, links,
                                     dt=.5, synthetic_stops=False, daily=True)
        frames = list(engine.frames(start_time=0, end_time=20))
        self.assertEqual(frames[0], (0, {}))
        self.assertEqual(frames[-1], (20, {}))
        self.assertEqual(engine.completed, 1)


if __name__ == '__main__':
    unittest.main()
