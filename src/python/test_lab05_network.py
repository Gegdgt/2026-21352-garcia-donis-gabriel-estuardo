"""Validate the recreated Lab05 export, including actual QSim parking events."""
import gzip
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

OUTPUT = Path(os.environ.get('LAB05_OUTPUT', str(Path(__file__).resolve().parents[1]
                         / 'output/labs/05-mini-city-recreated')))


def xml(name):
    with gzip.open(OUTPUT / f'output_{name}.xml.gz', 'rb') as source:
        return ET.parse(source).getroot()


class MiniCityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / 'output_network.xml.gz').exists():
            raise unittest.SkipTest('Run Lab05 first; LAB05_OUTPUT selects the export')
        root = xml('network')
        cls.nodes = {n.get('id'): (float(n.get('x')), float(n.get('y'))) for n in root.findall('nodes/node')}
        cls.links = {l.get('id'): l.attrib for l in root.findall('links/link')}

    def test_grid_parity_roundabout_and_speeds(self):
        self.assertEqual(len(self.nodes), 186)
        self.assertEqual(len(self.links), 376)
        for x in range(11):
            for y in range(11):
                if (x, y) != (5, 5):
                    self.assertEqual(self.nodes[f'G_{x}_{y}'], (x*1000, y*1000))
        self.assertNotIn('G_5_5', self.nodes)
        for key, link in self.links.items():
            a, b = self.nodes[link['from']], self.nodes[link['to']]
            self.assertGreater(float(link['length']), 0)
            if key.startswith(('H_', 'V_')):
                axis, x, y = key.split('_')
                coordinate = 0 if axis == 'H' else 1
                parity = int(y if axis == 'H' else x)
                self.assertGreater((b[coordinate]-a[coordinate])*(1 if parity%2 == 0 else -1), 0)
                self.assertEqual(float(link['freespeed']), 8.33)
            if key.startswith('BYPASS_'):
                self.assertEqual(float(link['freespeed']), 22.22)
                self.assertTrue(link['from'].startswith('B_') and link['to'].startswith('B_'))
            if key.startswith('ROUND_'):
                cross = (a[0]-5000)*(b[1]-5000)-(a[1]-5000)*(b[0]-5000)
                self.assertLess(cross, 0)  # Clockwise with north-positive Y.
                self.assertEqual(float(link['freespeed']), 5.56)

    def test_connectivity_no_reverse_duplicates_and_reflected_wings(self):
        pairs = {(l['from'], l['to']) for l in self.links.values()}
        self.assertEqual(len(pairs), len(self.links))
        for a, b in pairs:
            self.assertNotIn((b, a), pairs)
        for reverse in (False, True):
            reached, pending = set(), [next(iter(self.nodes))]
            while pending:
                node = pending.pop()
                if node in reached:
                    continue
                reached.add(node)
                pending.extend((a if reverse else b) for a,b in pairs if (b if reverse else a) == node)
            self.assertEqual(reached, set(self.nodes))
        for key, left in self.links.items():
            if not key.startswith('WING_LEFT_'):
                continue
            right = self.links[key.replace('LEFT', 'RIGHT')]
            for end in ('from', 'to'):
                x, y = self.nodes[left[end]]
                rx, ry = self.nodes[right[end]]
                self.assertAlmostEqual(rx, 10000-x)
                self.assertAlmostEqual(ry, y)
                self.assertTrue(0 <= x <= 3000 and 2000 <= y <= 4000)

    def test_population_parking_and_all_iteration_arrivals(self):
        persons = xml('plans').findall('person')
        self.assertTrue(250 <= len(persons) <= 500)
        ids = {p.get('id') for p in persons}
        for person in persons:
            activities = person.findall("plan[@selected='yes']/activity")
            self.assertEqual([a.get('type') for a in activities], ['home', 'parking', 'work'])
            for activity in (activities[0], activities[-1]):
                self.assertTrue(activity.get('link').startswith('BYPASS_'))
        for iteration in range(10):
            arrived, parked, ended = set(), {}, set()
            with gzip.open(OUTPUT / 'ITERS' / f'it.{iteration}' / f'{iteration}.events.xml.gz', 'rb') as source:
                for _, event in ET.iterparse(source):
                    if event.tag == 'event':
                        kind, person = event.get('type'), event.get('person')
                        self.assertNotEqual(kind, 'stuckAndAbort')
                        if kind == 'actstart' and event.get('actType') == 'work':
                            arrived.add(person)
                        if kind == 'actstart' and event.get('actType') == 'parking':
                            parked[person] = float(event.get('time'))
                        if kind == 'actend' and event.get('actType') == 'parking':
                            self.assertEqual(float(event.get('time'))-parked[person], 3.0)
                            ended.add(person)
                        event.clear()
            self.assertEqual(arrived, ids)
            self.assertEqual(ended, ids)


if __name__ == '__main__':
    unittest.main()
