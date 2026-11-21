"""Small contracts for continuous calendar, population and replay windows."""
from copy import deepcopy
import importlib.util
import sys
import tempfile
from pathlib import Path
import unittest

from simz1_temporal import load_temporal_policy
from simz1_temporal_transit import continuous_plan
from simz1_run import population

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('temporal_launch_tested', ROOT/'scripts/replay/start_replay.py')
launch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch
SPEC.loader.exec_module(launch)


class TemporalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_temporal_policy(ROOT/'scenarios/zona1/temporal/weekday-continuous-v1.json')

    def base_plan(self):
        deps=[dict(departure_id='trip'+str(i),vehicle_id='bus1',time_s=t)
              for i,t in enumerate((14400,21600,67200))]
        return dict(service_date='2026-10-28',vehicles=[dict(vehicle_id='bus1')],
            services=[dict(service_id='service',opens_s=14400,closes_s=79200,
                routes=[dict(route_id='route',departures=deps)])],
            roster=[dict(departure_id=d['departure_id'],vehicle_id='bus1',
                         departure_time_s=d['time_s'],end_time_s=d['time_s']+60,
                         service_id='service',route_id='route',closes_s=79200) for d in deps])

    def test_one_fleet_unique_dated_duties_and_no_drain_departures(self):
        base=self.base_plan();result=continuous_plan(base,self.policy)
        self.assertEqual(result['vehicles'],base['vehicles'])
        self.assertEqual(len(result['roster']),5)
        ids=[r['departure_id'] for r in result['roster']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(0<=r['departure_time_s']<129600 for r in result['roster']))
        self.assertTrue(any(r['departure_time_s']>108000 for r in result['roster']))
        self.assertTrue(any(r['departure_time_s']<21600 for r in result['roster']))
        self.assertEqual(base,self.base_plan())

    def test_weekend_is_not_silently_given_weekday_service(self):
        policy=deepcopy(self.policy);policy['study_date']='2026-10-30'
        base=self.base_plan();base['service_date']=policy['study_date']
        result=continuous_plan(base,policy)
        self.assertFalse(result['temporal_calendar']['days'][-1]['enabled'])
        self.assertFalse(any(r['departure_time_s']>=108000 for r in result['roster']))

    def test_departure_before_drain_may_finish_in_drain(self):
        base=self.base_plan()
        dep=base['services'][0]['routes'][0]['departures'][1]
        dep['time_s']=21590
        base['roster'][1].update(departure_time_s=21590,end_time_s=21650)
        result=continuous_plan(base,self.policy)
        crossing=[r for r in result['roster'] if r['departure_time_s']<129600<r['end_time_s']]
        self.assertEqual(len(crossing),1)
        self.assertEqual(crossing[0]['departure_cutoff_s'],129600)
        self.assertGreater(crossing[0]['closes_s'],crossing[0]['end_time_s'])

    def test_transit_date_mismatch_rejected(self):
        base=self.base_plan();base['service_date']='2026-10-23'
        with self.assertRaises(ValueError):continuous_plan(base,self.policy)

    def test_expected_replay_covers_context_and_midnight_without_wrapping(self):
        manifest=dict(temporal_policy=self.policy,time_horizon=self.policy['windows']['simulation'])
        self.assertEqual(launch.expected_replay_window(manifest),dict(start_seconds=0,end_seconds=136800))
        self.assertEqual(launch.expected_replay_window({}),dict(start_seconds=0,end_seconds=86400))
        manifest['time_horizon']=dict(start_seconds=0,end_seconds=86400)
        with self.assertRaises(ValueError):launch.expected_replay_window(manifest)

    def test_population_separates_main_and_context_preserving_xml_total(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plans.xml'
            rows=[]
            for ident,cohort in [('main','main'),('pre','warmup_context'),('post','post_context')]:
                rows.append(f'<person id="{ident}"><attributes><attribute name="simz1PopulationCohort">{cohort}</attribute></attributes><plan selected="yes"><act/><leg/><act/></plan></person>')
            p.write_text('<population>'+''.join(rows)+'</population>',encoding='utf-8')
            _,counts=population(p)
            self.assertEqual(counts['planned_persons'],3)
            self.assertEqual(counts['principal_cohort_persons'],1)
            self.assertEqual(counts['context_persons'],2)


if __name__=='__main__':unittest.main()
