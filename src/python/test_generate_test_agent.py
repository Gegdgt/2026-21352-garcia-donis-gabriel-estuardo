import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
from generate_test_agent import generate, SCENARIO


class AuditAgentTests(unittest.TestCase):
    def test_single_vehicle_full_day_routes_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/'run'
            report=generate(run_dir=directory)
            people=E.parse(directory/'plans.xml').findall('person')
            self.assertEqual([p.get('id') for p in people],['agente_auditor'])
            plan=people[0].find('plan')
            self.assertEqual(len(plan.findall('leg')),40)
            activities=plan.findall('activity')
            self.assertEqual(len(activities),41)
            self.assertEqual(activities[0].get('end_time'),'00:00:00')
            self.assertTrue(all(a.get('max_dur')=='00:05:00' for a in activities[1:-1]))
            self.assertGreaterEqual(report['minimum_planned_seconds'],86400)
            links={l.get('id'):l for l in E.parse(SCENARIO/'network.xml').findall('links/link')}
            controlled={s.get('linkIdRef') for s in E.parse(SCENARIO/'signalSystems.xml').findall('.//{*}signal')}
            for i,leg in enumerate(plan.findall('leg')):
                r=leg.find('route')
                ids=r.text.split()
                self.assertEqual((ids[0],ids[-1]),(r.get('start_link'),r.get('end_link')))
                self.assertEqual(ids[0],activities[i].get('link'))
                self.assertEqual(ids[-1],activities[i+1].get('link'))
                self.assertTrue(controlled.intersection(ids[1:-1]))
                for a,b in zip(ids,ids[1:]):
                    self.assertEqual(links[a].get('to'),links[b].get('from'))
            config=E.parse(directory/'config-simz1.xml')
            self.assertEqual(config.find("module[@name='qsim']/param[@name='endTime']").get('value'),'24:00:00')
            with self.assertRaises(ValueError): generate(run_dir=directory)


if __name__=='__main__': unittest.main()
