"""Dense cache -> slider -> scatter -> hover integration, with a synthetic fixture."""
import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent
from matplotlib.colors import to_rgba
from microscopic_traffic import DayFrameCache, Sample, PlaybackClock, position, speed_color
from visualize_network import create_traffic_figure, PlaybackControls, render_agents, AgentInspector


class DensePlaybackTests(unittest.TestCase):
    def test_dense_cache_random_seek_hover_and_colors(self):
        road = dict(length=60000,lanes=4,lane_width=3.2,**{'from':(0,0),'to':(60000,0)})
        def frame(t):
            return {str(i): Sample('l',i%4,32*i+t*5,5,'drive','fixture',t,t*5,5,5)
                    for i in range(1500)}
        cache = DayFrameCache([(t,frame(t)) for t in (0,4,8)], duration=8, spacing=4)
        fig,ax,_ = create_traffic_figure('dense','fixture',controls=True)
        ax.set_xlim(0,60000)
        ax.set_ylim(-20000,20000)
        points = ax.scatter([],[])
        inspector = AgentInspector(ax,points,fig._traffic_panel)
        clock = PlaybackClock(now=lambda:0)
        def render(t):
            # Repeat an 8s fixture to exercise day-scale seeking without
            # pretending that this fixture represents the complete demand.
            samples = cache.at(t%8)
            render_agents(points,samples,{'l':road})
            inspector.update(t,samples)
            return [points,inspector.text]
        controls = PlaybackControls(fig,clock,render)
        try:
            for t in (0,64803,18002,86399,1,43206,64803):
                controls.slider.set_val(t)
                fig.canvas.draw()
                self.assertEqual(inspector.time,t)
                self.assertEqual(clock.time,t)
                expected = frame(t%8)
                np.testing.assert_allclose(points.get_offsets(),[position(road,s.distance,s.lane) for s in expected.values()])
                np.testing.assert_allclose(points.get_facecolors(),[to_rgba(speed_color(s.speed)) for s in expected.values()])
                pixels = ax.transData.transform(points.get_offsets())
                event = MouseEvent('motion_notify_event',fig.canvas,*pixels[700])
                fig.canvas.callbacks.process('motion_notify_event',event)
                nearest = np.argmin(np.sum((pixels-(event.x,event.y))**2,axis=1))
                self.assertEqual(inspector.selected_id,str(nearest))
                selected = expected[str(nearest)]
                self.assertIn(f'{selected.speed*3.6:.2f} km/h',inspector.text.get_text())
                self.assertIn(f'{selected.mean_speed*3.6:.2f} km/h',inspector.text.get_text())
            self.assertEqual(cache.at(3),frame(3))
        finally:
            controls.close()
            inspector.disconnect()
            plt.close(fig)


if __name__ == '__main__':
    unittest.main()
