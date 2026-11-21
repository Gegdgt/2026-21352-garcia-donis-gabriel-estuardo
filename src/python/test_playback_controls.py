import unittest
from unittest.mock import patch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent
from microscopic_traffic import (PlaybackClock, PeriodicFrameCache, MicroscopicPlayback,
                                 Operation, GAP)
from visualize_network import create_traffic_figure, PlaybackControls


class MediaTests(unittest.TestCase):
    def test_clock_pause_seek_rates_and_midnight(self):
        now = [100.0]
        clock = PlaybackClock(now=lambda: now[0])
        self.assertEqual(clock.tick(), 0)
        now[0] += 30
        self.assertEqual(clock.tick(), 3600)
        clock.set_rate(0)
        now[0] += 100
        self.assertEqual(clock.tick(), 3600)
        clock.seek_day(86399)
        clock.set_rate(2)
        now[0] += 1
        self.assertEqual(clock.tick(), 86639)
        clock.set_rate(-1.5)
        now[0] += 2
        self.assertEqual(clock.tick(), 86279)
        clock.seek(86400 + 10)
        clock.seek_day(18 * 3600)
        self.assertEqual(clock.time, 86400 + 64800)
        clock.seek(0)
        now[0] += 2
        self.assertEqual(clock.tick(), 0)

    def test_default_clock_runs_multiple_days_without_wrapping(self):
        now = [0.0]
        clock = PlaybackClock(now=lambda: now[0])
        clock.tick()
        for real, simulated in ((30,3600),(720,86400),(720.5,86460),(1440,172800)):
            now[0] = real
            self.assertEqual(clock.tick(), simulated)

    def test_widgets_mouse_click_pause_and_seek_are_synchronous(self):
        fig, ax, text = create_traffic_figure('test', 'controls', controls=True)
        now = [0.0]
        clock = PlaybackClock(now=lambda:now[0])
        rendered = []
        controls = PlaybackControls(fig, clock, lambda t: rendered.append(t) or [])
        def click(index):
            fig.canvas.draw()
            x,y = controls.buttons[index].ax.transAxes.transform((.5,.5))
            for kind in ('button_press_event','button_release_event'):
                fig.canvas.callbacks.process(kind, MouseEvent(kind,fig.canvas,x,y,button=1))
        try:
            self.assertEqual(len(controls.buttons),6)
            controls.slider.set_val(64800)
            for index,scale in enumerate((1,6,60,120),start=1):
                click(index)
                self.assertEqual(clock.base_speed,scale)
                before = clock.time
                now[0] += 1
                controls.tick()
                self.assertEqual(clock.time,before+scale)
                self.assertEqual(rendered[-1],clock.time)
            click(5)
            self.assertEqual(clock.base_speed,240)
            click(5)
            self.assertEqual(clock.base_speed,120)
            click(0)
            self.assertEqual(clock.rate,0)
            before = clock.time
            now[0] += 10
            click(2)
            self.assertEqual(clock.base_speed,6)
            self.assertEqual(clock.time,before)
            self.assertEqual(clock.rate,0)
            self.assertEqual(controls.buttons[0].label.get_text(),'Reanudar')
            click(0)
            now[0] += 10
            controls.tick()
            self.assertEqual(clock.time,before+60)
            for size in ((16,12),(9,7)):
                fig.set_size_inches(*size)
                fig.canvas.draw()
                box = ax.get_window_extent()
                slider = fig._slider_axes.get_window_extent()
                self.assertAlmostEqual(slider.x0,box.x0,places=5)
                self.assertAlmostEqual(slider.x1,box.x1,places=5)
                self.assertLess(slider.y1,box.y0)
                self.assertGreater(fig._traffic_panel.get_window_extent().x0,box.x1)
                for button in controls.buttons:
                    self.assertLess(button.ax.get_window_extent().x1,box.x0)
                    self.assertLess(button.ax.get_window_extent().y1,fig._legend_axes.get_window_extent().y0)
        finally:
            controls.close()
            plt.close(fig)

    def test_scale_change_settles_old_time_without_jump(self):
        now = [0.0]
        clock = PlaybackClock(base_speed=1,now=lambda:now[0])
        clock.tick()
        now[0]=10
        clock.set_scale(120)
        self.assertEqual(clock.time,10)
        now[0]=11
        self.assertEqual(clock.tick(),130)
        for invalid in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): clock.set_scale(invalid)

    def test_joint_cycles_keep_trip_identity_and_gap_across_midnight(self):
        roads = {'l': dict(length=100, freespeed=10, capacity=1200, lanes=1,
                           **{'from': (0, 0), 'to': (100, 0)})}
        # Late vehicle continues into next day, early vehicle shares the lane.
        routes = {'late': [Operation('l', 56, 56)], 'early': [Operation('l', 2, 2)]}
        engine = MicroscopicPlayback(routes, roads, dt=.5, synthetic_stops=False)
        cache = PeriodicFrameCache(engine, period=60, spacing=1)
        before, after = cache.at(59), cache.at(61)
        self.assertIn('D1:late', before)
        self.assertIn('D1:late', after)
        self.assertGreater(after['D1:late'].distance, before['D1:late'].distance)
        self.assertEqual(cache.at(59), before)  # reverse/random access
        self.assertIn('D1001:late', cache.at(60059))
        for t in range(180):
            distances = sorted(s.distance for s in cache.at(t).values())
            self.assertTrue(all(b-a >= GAP-1e-8 for a,b in zip(distances,distances[1:])))

    def test_saturated_cycle_is_rejected_without_erasing_vehicles(self):
        roads = {'l': dict(length=100, freespeed=1, capacity=1, lanes=1,
                           **{'from': (0, 0), 'to': (100, 0)})}
        engine = MicroscopicPlayback({'a': [Operation('l', 0, 0)]}, roads,
                                     dt=.5, synthetic_stops=False)
        with self.assertRaisesRegex(RuntimeError, 'no se vacia'):
            PeriodicFrameCache(engine, period=20, spacing=1)


if __name__ == '__main__':
    unittest.main()
