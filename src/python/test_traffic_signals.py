import unittest
from traffic_signals import FixedTimeSignals


class SignalsTests(unittest.TestCase):
    def test_red_priority_approach_does_not_block_street_green(self):
        from microscopic_traffic import Vehicle,Profile,Operation,intersection_clear
        plan = FixedTimeSignals(43,25,4,2)
        base = dict(length=100,lanes=1,lane_width=3.8,stop_setback=15)
        links = {'s':dict(base,from_id='w',to_id='j'),
                 'a':dict(base,from_id='n',to_id='j',right_of_way=True,signal_plan=plan,signal_group='avenue'),
                 'out':dict(base,from_id='j',to_id='e')}
        v = Vehicle('f',[Operation('s',0,0),Operation('out',0,0)],Profile(1,0),visible=True)
        other = Vehicle('a',[Operation('a',0,0)],Profile(1,0),visible=True,distance=85)
        active = {'f':v,'a':other}
        self.assertFalse(intersection_clear(v,active,links,time=0))
        self.assertTrue(intersection_clear(v,active,links,time=49))
        other.distance=99
        self.assertFalse(intersection_clear(v,active,links,time=49))

    def test_exported_signals_follow_gui_seek(self):
        from pathlib import Path
        from unittest.mock import patch
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.colors import to_rgba
        from visualize_network import load_network, animate_simulation, signal_colors
        output = Path(__file__).resolve().parents[1]/'output/labs/08-zona1-signals'
        if not (output/'output_events.xml.gz').exists():
            self.skipTest('Generate signal export first')
        _, links = load_network(output/'output_network.xml.gz')
        roads = [r for r in links.values() if r.get('signal_plan')]
        self.assertTrue(roads)
        self.assertEqual({r['signal_group'] for r in roads},{'avenue','street'})
        self.assertTrue(all(r['signal_plan'].cycle==80 for r in roads))
        from visualize_network import load_map_registration
        if load_map_registration(output/'output_network.xml.gz') != 'EPSG:32615':
            with self.assertRaisesRegex(ValueError,'regenerate'):
                animate_simulation(output/'output_network.xml.gz',output/'output_events.xml.gz',
                                   'legacy',dt=.5,daily=True,focal=True)
            plt.close('all')
            return
        with patch.object(plt,'show'), patch('visualize_network.ctx.add_basemap'):
            animate_simulation(output/'output_network.xml.gz',output/'output_events.xml.gz','signals test',
                               dt=.5,daily=True,focal=True,playback_speed=120)
        fig = plt.gcf()
        try:
            for t in (0,43,47,49,74,78,80,10):
                fig._playback_controls.slider.set_val(t)
                active = signal_colors(roads,t)
                for lamp,color in zip(fig._traffic_signals.lamps,('#FF4545','#FFC107','#00D66B')):
                    np.testing.assert_allclose(lamp.get_facecolors(),
                        [to_rgba(color if c==color else '#333333') for c in active])
                self.assertEqual(fig._agent_inspector.time,t)
                self.assertEqual(len(fig._day_cache.at(t)),1)
        finally:
            fig._playback_controls.close()
            plt.close(fig)

    def test_approved_eighty_second_plan(self):
        plan = FixedTimeSignals(43,25,4,2)
        plan.validate_cycle(80)
        self.assertEqual((plan.avenue_red,plan.street_red),(33,51))
        expected = {0:('green','red'),43:('yellow','red'),47:('red','red'),
                    49:('red','green'),74:('red','yellow'),78:('red','red'),80:('green','red')}
        for t,colors in expected.items():
            self.assertEqual(plan.states(t),colors)
            self.assertEqual(plan.states(86400+t),colors)

    def test_red_holds_car_and_green_releases_it(self):
        from microscopic_traffic import MicroscopicPlayback, Operation
        plan = FixedTimeSignals(43,25,4,2)
        road = dict(length=100,lanes=1,capacity=800,freespeed=10,lane_width=3.8,
                    from_id='a',to_id='b',signal_plan=plan,signal_group='street',stop_setback=10.85,
                    **{'from':(0,0),'to':(100,0)})
        after = dict(length=100,lanes=1,capacity=800,freespeed=10,lane_width=3.8,
                     from_id='b',to_id='c',**{'from':(100,0),'to':(200,0)})
        engine = MicroscopicPlayback({'f':[Operation('a',0,0),Operation('b',0,0)]},
                                     {'a':road,'b':after},dt=.5,synthetic_stops=False)
        frames = list(engine.frames(start_time=0,end_time=180))
        waiting = [s for t,f in frames for s in f.values() if s.state=='signal']
        self.assertTrue(waiting)
        self.assertTrue(all(s.speed==0 and abs(s.distance-89.15)<1e-6 for s in waiting))
        self.assertTrue(all(s.link=='a' and s.distance<=89.15+1e-8 for t,f in frames if t<49 for s in f.values()))
        self.assertTrue(any(s.link=='b' for t,f in frames if t>=49 for s in f.values()))
        self.assertEqual(engine.completed,1)

    def test_transitions_and_both_clearances(self):
        plan = FixedTimeSignals(6,4,2,1)
        expected = {0:('green','red'), 5.99:('green','red'), 6:('yellow','red'),
                    8:('red','red'), 9:('red','green'),13:('red','yellow'),
                    15:('red','red'),16:('green','red')}
        for t,colors in expected.items():
            self.assertEqual(plan.states(t),colors)
            self.assertEqual(plan.states(t+1600),colors)
        self.assertEqual(plan.avenue_red,8)
        self.assertEqual(plan.street_red,10)

    def test_rejects_inconsistent_requested_cycle(self):
        plan = FixedTimeSignals(43,27,4,2)
        self.assertEqual(plan.cycle,82)
        with self.assertRaises(ValueError):
            plan.validate_cycle(80)

    def test_no_conflicting_greens_and_random_seek(self):
        plan = FixedTimeSignals(6,4,2,1,offset=3)
        for t in (0,3,8,10,16,86400,5,0):
            self.assertNotEqual(plan.states(t),('green','green'))
        self.assertEqual(plan.states(0), plan.states(160))


if __name__ == '__main__':
    unittest.main()
