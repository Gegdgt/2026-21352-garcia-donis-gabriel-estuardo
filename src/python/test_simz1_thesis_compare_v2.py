"""Focused tests for comparison calculations, independent of production runs."""
import unittest
from simz1_thesis_compare_v2 import active_metrics, family, statistics, observed_hour, select_flow_sections


class ComparisonCalculations(unittest.TestCase):
    def test_quantiles_individual_samples(self):
        stats=statistics([0,60,120,180])
        self.assertEqual(stats['n'],4)
        self.assertEqual(stats['mean_minutes'],1.5)
        self.assertEqual(stats['median_minutes'],1.5)
        self.assertAlmostEqual(stats['p90_minutes'],2.7)
        self.assertAlmostEqual(stats['p95_minutes'],2.85)

    def test_absent_measurement_not_zero(self):
        self.assertIsNone(statistics([])['mean_minutes'])
        for values in [[-1],[float('nan')],[float('inf')]]:
            with self.assertRaises(ValueError):statistics(values)

    def test_physical_peak_and_integral(self):
        observed=active_metrics([('bus1',0,1800),('bus1',1800,3600),('car',900,2700)])
        self.assertEqual(observed['physical_vehicles_observed'],2)
        self.assertEqual(observed['peak_active'],2)
        self.assertEqual(observed['peak_time_seconds'],900)
        self.assertEqual(observed['mean_by_hour'][0],1.5)
        self.assertEqual(observed['mean_by_hour'][1],0)

    def test_ties_are_half_open(self):
        self.assertEqual(active_metrics([('a',0,10),('b',10,20)])['peak_active'],1)

    def test_duplicate_vehicle_overlap_rejected(self):
        with self.assertRaises(ValueError):active_metrics([('bus',0,20),('bus',10,30)])

    def test_censored_interval_integrates_only_observed_day(self):
        self.assertAlmostEqual(active_metrics([('a',86300,86400)])['mean_by_hour'][23],100/3600)
        with self.assertRaises(ValueError):active_metrics([('a',86300,86401)])

    def test_transit_units_and_unknown_family(self):
        self.assertEqual(family(dict(family='bus',trip_id='bus:transmetro_L12:trip')),'transmetro')
        self.assertEqual(family(dict(family='bus',trip_id='bus:tubus_104:trip')),'tubus')
        with self.assertRaises(ValueError):family(dict(family='bus',trip_id='bus:unknown:trip'))

    def test_hour_boundaries_and_absence(self):
        self.assertIsNone(observed_hour(None))
        self.assertEqual(observed_hour(3599.9),0)
        self.assertEqual(observed_hour(3600),1)
        self.assertEqual(observed_hour(86400),23)
        with self.assertRaises(ValueError):observed_hour(86401)

    def test_sections_are_distinct_named_streets(self):
        a={k:dict(entries=v) for k,v in [('a',10),('b',9),('c',8),('d',7),('e',5)]}
        b={k:dict(entries=v) for k,v in [('a',10),('b',9),('c',8),('d',7),('e',5)]}
        names=dict(a='Avenida 1',b='Avenida 1',c='',d='Calle 2',e='Avenida 3')
        self.assertEqual(select_flow_sections([a,b],names,3),['a','d','e'])
        with self.assertRaises(ValueError):select_flow_sections([a,b],names,4)

    def test_section_ties_are_lexicographic(self):
        table={k:dict(entries=1) for k in ['b','a']}
        self.assertEqual(select_flow_sections([table,table],dict(a='A',b='B'),2),['a','b'])


if __name__=='__main__':unittest.main()
