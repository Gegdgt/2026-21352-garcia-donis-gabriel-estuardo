from pathlib import Path
import unittest
import xml.etree.ElementTree as E

BASE=Path(__file__).resolve().parents[1]/'scenarios/zona1'
NS={'s':'http://www.matsim.org/files/dtd'}

class LaneTests(unittest.TestCase):
    def test_counts_capacities_connectivity_and_signals(self):
        links={l.get('id'):l for l in E.parse(BASE/'network.xml').findall('links/link')}
        assignments={a.get('linkIdRef'):a for a in E.parse(BASE/'lanes.xml').findall('s:lanesToLinkAssignment',NS)}
        terminals={}
        for ident,a in assignments.items():
            link=links[ident]
            lanes=a.findall('s:lane',NS)
            end=[l for l in lanes if l.find('s:leadsTo/s:toLink',NS) is not None]
            start=[l for l in lanes if l.find('s:leadsTo/s:toLane',NS) is not None]
            terminals[ident]={l.get('id') for l in end}
            self.assertEqual(len(start),1)
            self.assertEqual(len(end),int(float(link.get('permlanes'))))
            self.assertAlmostEqual(sum(float(l.find('s:capacity',NS).get('vehiclesPerHour')) for l in end),float(link.get('capacity')))
            self.assertEqual({v.get('refId') for v in start[0].findall('s:leadsTo/s:toLane',NS)},terminals[ident])
            for lane in end:
                self.assertEqual(float(lane.find('s:representedLanes',NS).get('number')),1)
                self.assertTrue(0<float(lane.find('s:startsAt',NS).get('meterFromLinkEnd'))<float(link.get('length')))
                for dest in lane.findall('s:leadsTo/s:toLink',NS):
                    self.assertEqual(links[dest.get('refId')].get('from'),link.get('to'))
        for signal in E.parse(BASE/'signalSystems.xml').findall('.//s:signal',NS):
            ident=signal.get('linkIdRef')
            enabled=E.parse(BASE/'config-simz1.xml').find("module[@name='qsim']/param[@name='useLanes']").get('value')=='true'
            if enabled:
                self.assertIn(ident,terminals)
                self.assertTrue(signal.findall('s:lane',NS))
                self.assertEqual({l.get('refId') for l in signal.findall('s:lane',NS)},terminals[ident])
            elif not enabled:
                self.assertFalse(signal.findall('s:lane',NS))

if __name__=='__main__':unittest.main()
