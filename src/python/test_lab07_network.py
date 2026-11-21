from pathlib import Path
from collections import Counter
import gzip
import os
import unittest
import xml.etree.ElementTree as ET
from visualize_network import load_network

OUTPUT = Path(os.environ.get('LAB07_OUTPUT', str(Path(__file__).resolve().parents[1] / 'output/labs/07-multilane-zona1')))


class Lab07ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / 'output_network.xml.gz').is_file():
            raise unittest.SkipTest('Generate Lab07 first')
        cls.nodes, cls.links = load_network(OUTPUT / 'output_network.xml.gz')

    def test_sections_capacities_widths_and_lane_definitions(self):
        for r in self.links.values():
            axis = r['attributes']['roadId'].split('_')[0]
            expected = (4 if axis == 'A6' else 3 if axis in ('A7', 'A9', 'C12')
                        else 2 if axis.startswith('A') else 1 if axis == 'D'
                        else 2 if int(axis[1:]) % 2 == 0 else 1)
            self.assertEqual(r['lanes'], expected)
            self.assertEqual(r['lane_width'], 3.2)
            self.assertAlmostEqual(float(r['attributes']['roadWidth']), 3.2 * expected)
            kind = r['attributes']['roadClass']
            self.assertAlmostEqual(r['capacity'], expected * {'principal': 800, 'hospital': 400, 'local': 600}[kind]
                                   * float(r['attributes'].get('frictionCapacityFactor', 1)))
            self.assertEqual(r['extreme_night'], axis != 'D')
        with gzip.open(OUTPUT / 'output_lanes.xml.gz', 'rb') as f:
            lanes = ET.parse(f).getroot()
        for assignment in lanes.findall('{*}lanesToLinkAssignment'):
            road = self.links[assignment.get('linkIdRef')]
            self.assertEqual(float(assignment.find('.//{*}representedLanes').get('number')), road['lanes'])

    def test_complete_final_population_and_legal_routes(self):
        with gzip.open(OUTPUT / 'output_plans.xml.gz', 'rb') as f:
            people = ET.parse(f).getroot().findall('person')
        self.assertEqual(len(people), 72000)
        for person in people:
            for route in person.findall("plan[@selected='yes']/leg/route"):
                keys = (route.text or '').split()
                for a, b in zip(keys, keys[1:]):
                    self.assertEqual(self.links[a]['to_id'], self.links[b]['from_id'])
        arrived, stuck = set(), 0
        with gzip.open(OUTPUT / 'output_events.xml.gz', 'rb') as f:
            for _, event in ET.iterparse(f):
                if event.tag == 'event':
                    if event.get('type') == 'actstart' and event.get('actType') == 'work':
                        arrived.add(event.get('person'))
                    stuck += event.get('type') == 'stuckAndAbort'
                    event.clear()
        self.assertEqual(stuck, 0)
        self.assertEqual(len(arrived), len(people))


if __name__ == '__main__':
    unittest.main()
