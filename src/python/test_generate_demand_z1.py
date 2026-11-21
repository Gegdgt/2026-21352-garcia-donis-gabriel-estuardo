import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from generate_demand_z1 import generate, principal_links, SCENARIO, START, END


class DemandTests(unittest.TestCase):
    def test_directed_car_component_not_weak_or_pedestrian(self):
        xml='''<network><nodes><node id="a"/><node id="b"/><node id="c"/><node id="d"/></nodes>
        <links><link id="ab" from="a" to="b" modes="car"/>
        <link id="bc" from="b" to="c" modes="car"/>
        <link id="ca" from="c" to="a" modes="car"/>
        <link id="cd" from="c" to="d" modes="car"/>
        <link id="da" from="d" to="a" modes="walk"/></links></network>'''
        with tempfile.TemporaryDirectory() as folder:
            network=Path(folder)/'network.xml';network.write_text(xml)
            core,links,_,_=principal_links(network)
            self.assertEqual(core,{'a','b','c'})
            self.assertEqual(set(links),{'ab','bc','ca'})
            output=Path(folder)/'plans.xml'
            with self.assertRaisesRegex(ValueError,'3470'):
                principal_links(network,expected_nodes=3470)
            self.assertFalse(output.exists())

    def test_single_debug_agent_structure_and_repeatability(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=Path(folder)/'a.xml',Path(folder)/'b.xml'
            report=generate(SCENARIO/'network.xml',a)
            generate(SCENARIO/'network.xml',b,seed=42)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(report['core_nodes'],3470)
            self.assertEqual(report['agents'],1)
            self.assertEqual(report['traffic_signal_node'],'579787183')
            self.assertEqual(report['controlled_approach'],'osm_1174627094_0_forward')
            config=ET.parse(SCENARIO/'config-simz1.xml')
            self.assertLess(config.find("module[@name='qsim']/param[@name='startTime']").get('value'),'08:00:00')
            _,eligible,_,_=principal_links(SCENARIO/'network.xml')
            eligible=set(eligible)
            people=ET.parse(a).getroot().findall('person')
            self.assertEqual(len(people),1)
            self.assertEqual(people[0].get('id'),'agente_prueba_01')
            for person in people:
                plans=person.findall('plan');self.assertEqual(len(plans),1)
                origin,leg,destination=list(plans[0])
                self.assertEqual([origin.tag,leg.tag,destination.tag],['activity','leg','activity'])
                self.assertEqual(leg.get('mode'),'car')
                self.assertIn(origin.get('link'),eligible)
                self.assertIn(destination.get('link'),eligible)
                self.assertNotEqual(origin.get('link'),destination.get('link'))
                self.assertEqual(origin.get('link'),'osm_30262980_15_forward')
                self.assertEqual(destination.get('link'),'osm_384746799_0_forward')
                self.assertEqual(origin.get('end_time'),'08:00:00')
                h,m,s=map(int,origin.get('end_time').split(':'))
                self.assertTrue(START <= h*3600+m*60+s < END)
            self.assertEqual(report['departures_by_hour'],{'08:00':1})

    def test_invalid_arguments_preserve_input(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'plans.xml'
            for sigma in (0,-1,float('nan'),float('inf')):
                with self.assertRaises(ValueError):
                    generate(SCENARIO/'network.xml',output,sigma_seconds=sigma)
            with self.assertRaisesRegex(ValueError,'exactly 1'):
                generate(SCENARIO/'network.xml',output,count=10000)
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError,'overwrite'):
                generate(SCENARIO/'network.xml',SCENARIO/'network.xml')


if __name__=='__main__': unittest.main()
