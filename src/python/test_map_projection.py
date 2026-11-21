import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pyproj import Transformer
from visualize_network import (map_to_web_mercator,configure_zona1_projection,
    load_map_registration,load_network,map_coordinates,draw_road,SignalDisplay,
    render_agents,add_zona1_basemap,OSM_TILE_URL,DARK_TILE_URL)
from microscopic_traffic import Sample,position
from traffic_signals import FixedTimeSignals

class ProjectionTests(unittest.TestCase):
    def test_direct_projection_shape_and_validation(self):
        forward=Transformer.from_crs(4326,32615,always_xy=True)
        expected=Transformer.from_crs(4326,3857,always_xy=True)
        point=forward.transform(-90.518,14.646)
        np.testing.assert_allclose(map_to_web_mercator(point),expected.transform(-90.518,14.646),atol=1e-6)
        self.assertEqual(map_to_web_mercator(np.empty((0,2))).shape,(0,2))
        self.assertEqual(map_to_web_mercator(np.array([[point,point]])).shape,(1,2,2))
        for bad in ([1,2,3],[float('nan'),0],1):
            with self.assertRaises(ValueError): map_to_web_mercator(bad)

    def test_reject_legacy_instead_of_silently_deforming(self):
        fig,ax=plt.subplots()
        try:
            with self.assertRaisesRegex(ValueError,'regenerate'):
                configure_zona1_projection(ax,{'a':(0,0)})
        finally: plt.close(fig)

    def test_java_warp_export_and_projection(self):
        path=Path(__file__).resolve().parents[1]/'target/lab08-utm-fixture.xml'
        self.assertTrue(path.exists(),'Run Lab08ProjectionCheck first')
        nodes,links=load_network(path)
        self.assertEqual(load_map_registration(path),'EPSG:32615')
        inverse=Transformer.from_crs(32615,4326,always_xy=True)
        np.testing.assert_allclose(inverse.transform(*nodes['A2_C4']),[-90.518,14.646],atol=1e-8,rtol=0)
        west=np.linalg.norm(np.array(nodes['A3_C4'])-nodes['A2_C4'])
        east=np.linalg.norm(np.array(nodes['A12_C4'])-nodes['A11_C4'])
        self.assertGreater(east,west+10)
        a,b,c=[np.array(nodes[k]) for k in ('A2_C9','A7_C9','A12_C9')]
        ab,ac=b-a,c-a
        self.assertGreater(abs(ab[0]*ac[1]-ab[1]*ac[0]),1000)
        self.assertEqual((len(nodes),len(links)),(166,345))
        from visualize_network import load_special_areas,load_points_of_interest
        self.assertEqual(load_special_areas(path),[])
        self.assertEqual(load_points_of_interest(path),[])
        fig,ax=plt.subplots()
        try:
            configure_zona1_projection(ax,nodes,'EPSG:32615')
            road=next(r for r in links.values() if r.get('signal_plan'))
            draw_road(ax,road)
            signals=SignalDisplay(ax,[road])
            points=ax.scatter([],[]);points._focal=True
            sample=Sample('a',0,10,2,'drive')
            render_agents(points,{'f':sample},{'a':road})
            np.testing.assert_allclose(points.get_offsets(),[map_to_web_mercator(position(road,10,0))])
            self.assertEqual(len(signals.artists),4)
            with patch('visualize_network.ctx.add_basemap',side_effect=[ValueError('invalid'),None]) as add:
                with self.assertWarns(UserWarning): add_zona1_basemap(ax)
                self.assertEqual([c.kwargs['source'] for c in add.call_args_list],[DARK_TILE_URL,OSM_TILE_URL])
        finally: plt.close(fig)

    def test_runtime_utm_gui(self):
        from visualize_network import animate_simulation
        output=Path(__file__).resolve().parents[1]/'output/labs/08-zona1-warped'
        if not (output/'output_events.xml.gz').exists(): self.skipTest('Run Lab08Zona1Network first')
        with patch('visualize_network.ctx.add_basemap'),patch.object(plt,'show'):
            animate_simulation(output/'output_network.xml.gz',output/'output_events.xml.gz',
                               'UTM test',dt=.5,daily=True,focal=True)
        fig=plt.gcf()
        try:
            controls=fig._playback_controls
            for t in (0,60,10):
                controls.slider.set_val(t)
                inspector=fig._agent_inspector
                self.assertEqual(inspector.time,t)
                self.assertEqual(len(inspector.points.get_offsets()),1)
                self.assertTrue(np.isfinite(inspector.points.get_offsets()).all())
        finally:
            fig._playback_controls.close();plt.close(fig)
