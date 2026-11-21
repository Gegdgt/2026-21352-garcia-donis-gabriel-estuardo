"""Regression checks for the OSM converter and the delivered SimZ1 artifacts."""
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from pyproj import Transformer
from prepare_simz1 import SCENARIO, access_reason, road_reason, prepare, components


class SimZ1Tests(unittest.TestCase):
    def test_vehicle_filter_and_specific_access(self):
        for kind in ('footway', 'pedestrian', 'steps', 'cycleway', 'path', 'busway'):
            self.assertIsNotNone(road_reason({'highway': kind}))
        self.assertIsNone(road_reason({'highway': 'tertiary', 'name': '3a Avenida'}))
        self.assertIsNone(access_reason({'access': 'no', 'motorcar': 'yes'}))
        self.assertIsNotNone(access_reason({'access': 'yes', 'motorcar': 'private'}))
        self.assertIsNotNone(access_reason({'access:conditional': 'no @ (09:00-15:00)'}))

    def test_direction_projection_and_incomplete_input(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder/'input.osm'
            xml = '''<osm><node id="1" lon="-90.518" lat="14.646"/>
            <node id="2" lon="-90.517" lat="14.646"/>
            <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="tertiary"/>
            <tag k="oneway" v="-1"/></way>
            <way id="11"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>'''
            source.write_text(xml)
            prepare(source, folder/'out')
            config = ET.parse(folder/'out/config-simz1.xml')
            for module, name in [('qsim','useLanes'), ('controler','enableLinkToLinkRouting'),
                                 ('travelTimeCalculator','calculateLinkToLinkTravelTimes'),
                                 ('signalsystems','useSignalsystems')]:
                self.assertEqual(config.find(f"module[@name='{module}']/param[@name='{name}']").get('value'),'true')
            self.assertEqual(config.find("module[@name='network']/param[@name='laneDefinitionsFile']").get('value'),'lanes.xml')
            for name in ('flowCapacityFactor', 'storageCapacityFactor'):
                self.assertEqual(config.find(f"module[@name='qsim']/param[@name='{name}']").get('value'), '1.0')
            net = ET.parse(folder/'out/network.xml').getroot()
            link = net.find("links/link[@origid='10']")
            self.assertEqual((link.get('from'), link.get('to')), ('2', '1'))
            node = net.find("nodes/node[@id='1']")
            lon, lat = Transformer.from_crs(32615, 4326, always_xy=True).transform(float(node.get('x')), float(node.get('y')))
            self.assertAlmostEqual(lon, -90.518, places=8)
            self.assertAlmostEqual(lat, 14.646, places=8)
            source.write_text(xml.replace('<nd ref="2"/>', '<nd ref="999"/>'))
            with self.assertRaisesRegex(ValueError, 'Incomplete drivable way'):
                prepare(source, folder/'bad')

    def test_exported_connectivity_and_facilities(self):
        net = ET.parse(SCENARIO/'network.xml').getroot()
        nodes = {n.get('id') for n in net.find('nodes')}
        links = [l.attrib for l in net.find('links')]
        used = {l[key] for l in links for key in ('from', 'to')}
        self.assertEqual(nodes, used)
        self.assertTrue(all(float(l['length']) > 0 for l in links))
        core = components(links)[0]
        self.assertTrue({'333831813', '333831774', '333831722'} <= core)
        road = [l for l in links if l.get('origid') == '30279769']
        adjacency = {l['from']: l['to'] for l in road}
        current = '333831813'
        visited = set()
        while current != '333831722' and current not in visited:
            visited.add(current)
            current = adjacency.get(current)
        self.assertEqual(current, '333831722')
        self.assertIn('333831774', visited)
        ids = {l['id'] for l in links}
        for facility in ET.parse(SCENARIO/'facilities.xml').getroot():
            self.assertIn(facility.get('linkId'), ids)

    def test_cycle2_config(self):
        root = ET.parse(SCENARIO/'config-simz1.xml').getroot()
        values = {m.get('name'): {p.get('name'): p.get('value') for p in m.findall('param')}
                  for m in root.findall('module')}
        self.assertEqual(values['global']['coordinateSystem'], 'EPSG:32615')
        self.assertEqual(values['qsim']['startTime'], '07:59:00')
        self.assertEqual(values['qsim']['endTime'], '15:00:00')
        for name in ('flowCapacityFactor', 'storageCapacityFactor'):
            self.assertEqual(float(values['qsim'][name]), 1.0)
        for mod, key in [('network', 'inputNetworkFile'), ('facilities', 'inputFacilitiesFile'), ('plans', 'inputPlansFile')]:
            self.assertTrue((SCENARIO/values[mod][key]).is_file())


if __name__ == '__main__':
    unittest.main()
