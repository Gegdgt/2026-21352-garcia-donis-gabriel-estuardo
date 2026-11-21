import math
import unittest
import xml.etree.ElementTree as ET
from simz1_road_parameters import road_parameters
from prepare_simz1 import SCENARIO


class RoadParametersTests(unittest.TestCase):
    def params(self, tags, direction=1, directions=(1,), factor=1):
        return road_parameters(tags, direction, directions, 30, factor)

    def test_ideal_and_adjusted_capacity(self):
        p=self.params({'lanes':'3', 'maxspeed':'50'})
        self.assertEqual(p['permlanes'],3)
        self.assertEqual(p['capacity'],6000)
        self.assertAlmostEqual(p['freespeed'],50/3.6)
        self.assertEqual(self.params({'lanes':'3'},factor=.6)['capacity'],3600)
        for factor in (0,-1,1.1,math.nan,math.inf):
            with self.assertRaises(ValueError): self.params({},factor=factor)

    def test_directional_and_shared_lanes(self):
        t={'lanes':'4','lanes:forward':'2','lanes:backward':'1','lanes:both_ways':'1'}
        self.assertEqual(self.params(t,1,(1,-1))['permlanes'],2)
        self.assertEqual(self.params(t,-1,(1,-1))['permlanes'],1)
        t={'lanes':'3','lanes:forward':'2'}
        self.assertEqual(self.params(t,-1,(1,-1))['permlanes'],1)
        self.assertEqual(self.params({'lanes':'4'},1,(1,-1))['permlanes'],2)
        self.assertEqual(self.params({'lanes':'2','lanes:backward':'2'},-1,(-1,))['capacity'],4000)

    def test_ambiguous_or_invalid_lane_counts(self):
        for t in ({'lanes':'3'},{'lanes':'1'},{'lanes':'2.5'},
                  {'lanes':'2','lanes:forward':'2'},
                  {'lanes':'4','lanes:forward':'1','lanes:backward':'1'}):
            with self.subTest(tags=t), self.assertRaises(ValueError):
                self.params(t,1,(1,-1))
        with self.assertRaises(ValueError): self.params({'lanes':'2','lanes:backward':'1'})

    def test_speed_precedence_units_and_provenance(self):
        p=self.params({'maxspeed':'50','maxspeed:backward':'20 mph'},-1,(-1,))
        self.assertAlmostEqual(p['freespeed'],20*.44704)
        self.assertEqual(p['physical']['physical:speedSource'],'osm:maxspeed:backward')
        p=self.params({'maxspeed':'signals'})
        self.assertAlmostEqual(p['freespeed'],30/3.6)
        self.assertIn('physical:speedReview',p['physical'])
        self.assertTrue(self.params({})['physical']['physical:lanesSource'].startswith('assumed:'))

    def test_export_all_capacities_and_critical_avenue(self):
        root=ET.parse(SCENARIO/'network.xml').getroot()
        self.assertEqual(root.find('links').get('capperiod'),'01:00:00')
        critical=[]
        for link in root.findall('links/link'):
            lanes=float(link.get('permlanes'))
            self.assertEqual(lanes,int(lanes))
            self.assertAlmostEqual(float(link.get('capacity')),2000*lanes)
            attrs={a.get('name'):a.text for a in link.findall('attributes/attribute')}
            self.assertAlmostEqual(float(link.get('freespeed'))*3.6,float(attrs['physical:modeledMaxSpeedKmh']))
            if link.get('origid')=='30279769': critical.append(link)
        self.assertTrue(critical)
        self.assertTrue(all(float(l.get('capacity'))==4000 for l in critical))


if __name__=='__main__': unittest.main()
