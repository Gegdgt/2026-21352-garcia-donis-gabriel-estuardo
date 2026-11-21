"""Small day-boundary checks: no population generation or MATSim execution."""
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_temporal import DAY, DepartureSampler, temporal_spec


class DailyDefaultsTests(unittest.TestCase):
    def test_normal_modes_have_one_day_and_explicit_zero_drain(self):
        for mode in ('historical', 'montecarlo'):
            for drain in (None, 0):
                with self.subTest(mode=mode, drain=drain):
                    spec = temporal_spec(mode=mode, drain=drain)
                    self.assertEqual(spec['profile'], 'full-day')
                    self.assertEqual(spec['demand_window'], dict(
                        start_seconds=0, end_seconds=DAY, end_exclusive=True))
                    self.assertEqual(spec['simulation_window'], dict(
                        start_seconds=0, end_seconds=DAY))
                    self.assertEqual(spec['drain_seconds'], 0)

    def test_explicit_experiment_preserves_its_different_horizon(self):
        spec = temporal_spec(drain=3600)
        self.assertEqual(spec['simulation_window']['end_seconds'], 90000)
        self.assertEqual(spec['drain_seconds'], 3600)
        self.assertEqual(spec['demand_window']['end_seconds'], DAY)
        self.assertIsNone(temporal_spec(mode='debug'))

    def test_departure_sampler_includes_zero_and_excludes_day_end(self):
        sampler = DepartureSampler(1, [1 / 24] * 24)
        with patch.object(sampler.rng, 'random', return_value=0), \
                patch.object(sampler.rng, 'randrange', return_value=0):
            self.assertEqual(sampler.sample(), [0])
        with patch.object(sampler.rng, 'random', return_value=math.nextafter(1., 0.)), \
                patch.object(sampler.rng, 'randrange', return_value=3599):
            last = sampler.sample()[0]
        self.assertGreaterEqual(last, DAY - 1)
        self.assertLess(last, DAY)

    def test_master_qsim_starts_and_closes_exactly_at_day_boundaries(self):
        source = Path(__file__).resolve().parents[1] / 'scenarios/zona1/config-simz1.xml'
        root = ET.parse(source).getroot()
        expected = {'startTime': '00:00:00', 'endTime': '24:00:00',
                    'simStarttimeInterpretation': 'onlyUseStarttime',
                    'simEndtimeInterpretation': 'onlyUseEndtime'}
        qsim = {p.get('name'): p.get('value') for p in root.findall("module[@name='qsim']/param")}
        for name, value in expected.items():
            self.assertEqual(qsim[name], value)
        self.assertEqual(root.find("module[@name='travelTimeCalculator']/param[@name='maxTime']").get('value'), '86400')


if __name__ == '__main__':
    unittest.main()
