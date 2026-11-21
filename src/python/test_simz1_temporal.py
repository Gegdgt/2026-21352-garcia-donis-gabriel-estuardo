import gzip
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar, SCENARIO
from simz1_temporal import temporal_spec, DepartureSampler, hourly_fit, trip_id
from simz1_run import parameters, sha256
from simz1_run import population
from simz1_population import verify_population
from generate_demand_z1 import principal_links
from procesar_eventos_z1 import read_trips


class TemporalTests(unittest.TestCase):
    def test_persistent_trip_identity_survives_replaced_leg_but_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'output_plans.xml'
            root=ET.fromstring('''<population><person id="p"><attributes>
              <attribute name="simz1Trips" class="java.lang.String"/></attributes>
              <plan selected="yes"><activity link="a"/><leg mode="car"><attributes>
              <attribute name="routingMode" class="java.lang.String">car</attribute>
              </attributes></leg><activity link="b"/></plan></person></population>''')
            ledger=root.find('person/attributes/attribute')
            expected=[dict(id=trip_id('p',1),index=1,planned_departure=86399,origin_link='a',destination_link='b')]
            ledger.text=json.dumps(expected)
            ET.ElementTree(root).write(path)
            self.assertEqual(population(path,1)[1]['planned_trips'],1)
            for text in ('null',json.dumps([dict(expected[0],id='wrong')]),
                         json.dumps([dict(expected[0],destination_link='different')])):
                ledger.text=text;ET.ElementTree(root).write(path)
                with self.subTest(text=text),self.assertRaisesRegex(ValueError,'incompatible'):
                    population(path,1)

    def test_sampling_multiple_seeds_and_binomial_tolerances(self):
        spec=temporal_spec()
        probabilities=spec['hourly_probabilities']
        self.assertAlmostEqual(sum(probabilities),1)
        self.assertTrue(all(p>0 for p in probabilities))
        for seed in (1,20261015,20261004):
            sampler=DepartureSampler(seed, probabilities)
            counts=[0]*24; boundaries=0
            for _ in range(100000):
                value=sampler.sample()[0]
                self.assertTrue(0 <= value < 86400)
                counts[int(value//3600)] += 1
                boundaries += value%3600 < 1
            self.assertTrue(all(row['within_tolerance'] for row in hourly_fit(counts,probabilities)))
            self.assertLess(boundaries,100)  # Expected ~27.8; no mass at h:00:00.
        a,b=DepartureSampler(7,probabilities),DepartureSampler(7,probabilities)
        self.assertEqual(a.sample(100),b.sample(100))
        self.assertEqual(len(DepartureSampler(7,probabilities).sample(1)),1)  # No forced 24-hour coverage.

    def test_invalid_options_and_policy_do_not_create_a_run(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'new temporal run'
            for options in (dict(hourly_weights=[1]*23),dict(hourly_weights=[0]*24),
                            dict(hourly_weights=[1]*23+[float('nan')]),dict(hourly_weights=[1]*23+[-1]),
                            dict(temporal_profile='peaks',hourly_weights=[1]*24),
                            dict(temporal_profile='peaks',trips_per_person=2),
                            dict(trips_per_person=0),dict(drain_seconds=-1),dict(drain_seconds=1.5)):
                with self.subTest(options=options),self.assertRaises(ValueError):
                    generar(SCENARIO/'config-simz1.xml',run,1,agents=1,corridor_policy='redistribute',**options)
                self.assertFalse(run.exists())
            with self.assertRaisesRegex(ValueError,'corridor-policy'):
                generar(SCENARIO/'config-simz1.xml',run,1,agents=1,temporal_profile='full-day')
            with self.assertRaisesRegex(ValueError,'Politica fail'):
                generar(SCENARIO/'config-simz1.xml',run,1,agents=1,corridor_policy='fail',temporal_profile='full-day')
            self.assertFalse(run.exists())
            with self.assertRaisesRegex(ValueError,'debug'):
                generar(SCENARIO/'config-simz1.xml',run,1,mode='debug',temporal_profile='full-day')

    def test_repeated_people_xml_ids_times_vehicle_and_source_isolation(self):
        source=SCENARIO/'config-simz1.xml'; before=sha256(source)
        _,eligible,_,_=principal_links(SCENARIO/'network.xml')
        with tempfile.TemporaryDirectory(prefix='temporal spaces ') as folder:
            hashes=[]
            for suffix in ('one','repeat'):
                run=Path(folder)/suffix
                report=generar(source,run,7,agents=3,corridor_policy='redistribute',
                    temporal_profile='full-day',trips_per_person=3,drain_seconds=7200,
                    use_lanes=True,within_day_routing=False)
                self.assertEqual(report['xml_verified_counts']['persons'],3)
                self.assertEqual(report['xml_verified_counts']['trips'],9)
                self.assertEqual(report['xml_verified_counts']['vehicles'],3)
                self.assertEqual(report['departures_by_hour'],report['xml_verified_counts']['departures_by_hour'])
                params=parameters(run/'config-simz1.xml')
                self.assertEqual(params['qsim.startTime'],'00:00:00')
                self.assertEqual(params['qsim.endTime'],'26:00:00')
                self.assertEqual(params['qsim.useLanes'],'true')
                self.assertEqual(params['zona1WithinDayRouting.enabled'],'false')
                for person in ET.parse(run/'plans.xml').findall('person'):
                    acts=person.findall('plan/activity');legs=person.findall('plan/leg')
                    times=[float(a.get('end_time')) for a in acts[:-1]]
                    self.assertEqual(times,sorted(set(times)))
                    self.assertTrue(all(0<=t<86400 for t in times))
                    self.assertEqual([l.findtext("attributes/attribute[@name='simz1TripId']") for l in legs],
                                     [trip_id(person.get('id'),i) for i in (1,2,3)])
                    ledger=json.loads(person.findtext("attributes/attribute[@name='simz1Trips']"))
                    self.assertEqual([t['planned_departure'] for t in ledger],times)
                    self.assertEqual(ledger[1]['origin_link'],ledger[0]['destination_link'])
                hashes.append(sha256(run/'plans.xml'))
                manifest=json.loads((run/'run-manifest.json').read_text())
                self.assertEqual(manifest['counts']['planned_trips'],9)
                self.assertEqual(manifest['demand_window']['end_seconds'],86400)
                self.assertEqual(manifest['replay_window']['end_seconds'],93600)
                self.assertEqual(manifest['inputs']['demand_report']['sha256'],sha256(run/'montecarlo-report.json'))
                # Direct XML corruption must not pass an asserted requested count.
                root=ET.parse(run/'plans.xml')
                root.find('person/plan/activity').set('end_time','86400')
                root.write(run/'plans.xml')
                with self.assertRaisesRegex(ValueError,'Horario'):
                    verify_population(run/'plans.xml',run/'inputs/vehicles.xml',3,eligible)
            self.assertEqual(*hashes)
        self.assertEqual(sha256(source),before)

    def test_launcher_propagates_temporal_flags(self):
        import ejecutar_simz1 as launcher
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'launcher with spaces'
            args=['ejecutar_simz1.py','--run-dir',str(run),'--agents','10','--seed','15',
                  '--iterations','1','--corridor-policy','redistribute','--temporal-profile','full-day',
                  '--trips-per-person','2','--drain-seconds','600','--hourly-weights',','.join(['1']*24),
                  '--no-use-lanes','--no-within-day-routing']
            with patch.object(sys,'argv',args),patch.object(launcher,'ejecutar') as execute:
                launcher.main()
            execute.assert_called_once_with(run,None,False,1)
            m=json.loads((run/'run-manifest.json').read_text())
            self.assertEqual(m['counts']['planned_persons'],10)
            self.assertEqual(m['counts']['planned_trips'],20)
            self.assertEqual(m['time_horizon'],dict(start_seconds=0,end_seconds=87000))
            self.assertEqual(m['temporal_demand']['hourly_probabilities'],[1/24]*24)

    def test_midnight_repeated_trips_censoring_and_hour_cohorts(self):
        with tempfile.TemporaryDirectory() as folder:
            events=Path(folder)/'events.xml.gz'
            with gzip.open(events,'wt') as f:
                f.write('''<events>
                <event type="departure" person="a" time="3600.5"/>
                <event type="arrival" person="a" time="3700.5"/>
                <event type="departure" person="b" time="85000"/>
                <event type="stuckAndAbort" person="b" time="85010"/>
                <event type="departure" person="a" time="86399"/>
                <event type="departure" person="c" time="86399.5"/>
                <event type="arrival" person="a" time="86500"/>
                <event type="stuckAndAbort" person="c" time="87001"/>
                </events>''')
            df,stats=read_trips(events,horizon=87000)
            self.assertEqual(df.Trip_ID.tolist(),[trip_id('a',1),trip_id('a',2),trip_id('b',1),trip_id('c',1)])
            self.assertEqual(df.Arrival_Time.iloc[1],'24:01:40')
            self.assertEqual(df.Status.tolist(),['completed','completed','aborted','censored'])
            self.assertTrue(math.isnan(df.Arrival_Seconds.iloc[-1]))
            self.assertTrue(math.isnan(df.Travel_Time_Minutes.iloc[-1]))
            self.assertEqual(stats['by_departure_hour']['23'],dict(departures=3,completed=1,
                aborted_before_horizon=1,censored=1,horizon_abort_events=1))
            self.assertEqual(stats['by_event_hour']['24']['arrivals'],1)
            self.assertEqual(stats['by_event_hour']['24']['departures'],0)


if __name__=='__main__':unittest.main()
