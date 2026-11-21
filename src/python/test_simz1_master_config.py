import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
from prepare_simz1 import prepare, SCENARIO

class MasterConfigTests(unittest.TestCase):
    def test_master_modules_and_exactly_fifty_runs(self):
        root=ET.parse(SCENARIO/'config-simz1.xml').getroot()
        modules={m.get('name'):{p.get('name'):p.get('value') for p in m.findall('param')} for m in root.findall('module')}
        self.assertEqual(modules['plans']['inputPlansFile'],'plans.xml')
        self.assertEqual(int(modules['controler']['lastIteration'])-int(modules['controler']['firstIteration'])+1,50)
        self.assertEqual(modules['network']['timeVariantNetwork'],'true')
        self.assertEqual(modules['qsim']['startTime'],'00:00:00')
        self.assertEqual(modules['qsim']['endTime'],'24:00:00')
        self.assertEqual(modules['global']['numberOfThreads'],'12')
        self.assertEqual(modules['travelTimeCalculator']['calculateLinkTravelTimes'],'true')
        self.assertEqual(modules['travelTimeCalculator']['travelTimeBinSize'],'60')
        self.assertEqual(modules['zona1WithinDayRouting']['routingPolicy'],'fastest-time')
        car=root.find("module[@name='planCalcScore']/parameterset/param[@name='marginalUtilityOfTraveling_util_hr']")
        self.assertIsNotNone(car)
        self.assertLess(float(car.get('value')),0)
        strategies={s.find("param[@name='strategyName']").get('value'):float(s.find("param[@name='weight']").get('value')) for s in root.findall("module[@name='strategy']/parameterset")}
        self.assertEqual(strategies,{'ChangeExpBeta':.8,'ReRoute':.2})

    def test_regeneration_preserves_master_config(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            target=folder/'config-simz1.xml'
            master=(SCENARIO/'config-simz1.xml').read_bytes()
            target.write_bytes(master)
            prepare(SCENARIO/'map.osm',folder)
            self.assertEqual(target.read_bytes(),master)

if __name__=='__main__': unittest.main()
