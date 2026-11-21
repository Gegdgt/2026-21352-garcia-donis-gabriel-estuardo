"""Integration checks for the calibrated-scenario export, not measured accuracy."""
import ast
import csv
import gzip
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from visualize_network import load_network

OUTPUT = Path(os.environ.get('LAB07_OUTPUT', str(Path(__file__).resolve().parents[1]
                       / 'output/labs/07-calibrated-zona1')))


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / 'output_network.xml.gz').exists():
            raise unittest.SkipTest('Generate calibrated Lab07 first')
        _, cls.links = load_network(OUTPUT / 'output_network.xml.gz')
        with gzip.open(OUTPUT / 'output_network.xml.gz', 'rb') as f:
            root = ET.parse(f).getroot()
        cls.profile = ast.literal_eval(root.find("attributes/attribute[@name='demandProfile']").text)

    def test_demand_windows_and_sampled_population(self):
        bins = self.profile
        self.assertEqual(bins[0][0], 0)
        self.assertEqual(bins[-1][1], 24)
        for a, b in zip(bins, bins[1:]):
            self.assertEqual(a[1], b[0])
        self.assertIn([5.5, 8.75, 3.2], bins)
        self.assertIn([12, 14, 1.25], bins)
        self.assertIn([16.5, 20.5, 3.4], bins)
        counts = [0] * len(bins)
        with gzip.open(OUTPUT / 'output_plans.xml.gz', 'rb') as f:
            for _, elem in ET.iterparse(f):
                if elem.tag != 'person':
                    continue
                value = elem.find("plan[@selected='yes']/activity[@type='home']").get('end_time')
                parts = value.split(':')
                hour = sum(float(v) * scale for v, scale in zip(parts, (1, 1/60, 1/3600))) if len(parts) == 3 else float(value) / 3600
                for i, (start, end, weight) in enumerate(bins):
                    if start <= hour < end:
                        counts[i] += 1
                        break
                elem.clear()
        total = sum(counts)
        self.assertEqual(total, 72000)
        mass = sum((b-a)*w for a, b, w in bins)
        for observed, (a, b, w) in zip(counts, bins):
            expected = total * (b-a)*w/mass
            self.assertLess(abs(observed-expected), 6 * expected**.5)

    def test_effective_cost_and_capacity_are_exported_once(self):
        groups = set()
        for road in self.links.values():
            attrs = road['attributes']
            if 'hotspot' not in attrs:
                continue
            groups.add(attrs['hotspot'])
            nominal = float(attrs['nominalFreeSpeed'])
            self.assertAlmostEqual(road['freespeed'], nominal * float(attrs['frictionSpeedFactor']))
            self.assertAlmostEqual(road['capacity'], float(attrs['nominalCapacity']) * float(attrs['frictionCapacityFactor']))
            self.assertAlmostEqual(road['length']/road['freespeed'],
                                   road['length']/nominal + float(attrs['effectiveDelaySeconds']))
            self.assertGreater(road['capacity'], 0)
        self.assertEqual(groups, {'Congreso', 'Plaza-Catedral', 'Eje-A4', 'Eje-A7', 'Salida-perimetral-proxy'})

    def test_all_ten_iterations_drain_without_aborts(self):
        for iteration in range(10):
            with (OUTPUT / f'ITERS/it.{iteration}/{iteration}.legHistogram.txt').open() as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(sum(int(r['stuck_all']) for r in rows), 0, iteration)
            departed = sum(int(r['departures_all']) for r in rows)
            arrived = sum(int(r['arrivals_all']) for r in rows)
            self.assertEqual(departed, 144000, iteration)  # Two legs/person, including post-parking leg.
            self.assertEqual(arrived, departed, iteration)
            self.assertEqual(int(rows[-1]['en-route_all']), 0, iteration)


if __name__ == '__main__':
    unittest.main()
