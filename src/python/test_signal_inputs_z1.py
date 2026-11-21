"""Validate exported native signal coverage against the imported OSM network."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1] / 'scenarios/zona1'
NS = {'s': 'http://www.matsim.org/files/dtd'}


class SignalInputsTests(unittest.TestCase):
    def test_every_incoming_car_link_and_exclusive_phases(self):
        network = ET.parse(BASE/'network.xml')
        nodes = {n.get('id') for n in network.findall('nodes/node')
                 if n.findtext("attributes/attribute[@name='osm:highway']") == 'traffic_signals'}
        expected = {l.get('id'): l.get('to') for l in network.findall('links/link')
                    if l.get('to') in nodes and 'car' in l.get('modes','car').split(',')}
        assignments={a.get('linkIdRef') for a in ET.parse(BASE/'lanes.xml').findall('s:lanesToLinkAssignment',NS)}
        expected={link:node for link,node in expected.items() if link in assignments}
        systems = ET.parse(BASE/'signalSystems.xml')
        actual = {s.get('linkIdRef'): system.get('id')
                  for system in systems.findall('s:signalSystem',NS)
                  for s in system.findall('s:signals/s:signal',NS)}
        self.assertTrue(actual)
        self.assertEqual(actual, expected)
        groups = ET.parse(BASE/'signalGroups.xml')
        covered = []
        for system in groups.findall('s:signalSystem',NS):
            for group in system.findall('s:signalGroup',NS):
                covered.extend(s.get('refId') for s in group.findall('s:signal',NS))
        self.assertEqual(len(covered),len(set(covered)))
        self.assertEqual(set(covered),set(actual))
        controls = ET.parse(BASE/'signalControl.xml')
        self.assertEqual(len(controls.findall('s:signalSystem',NS)),len(set(actual.values())))
        for plan in controls.findall('.//s:signalPlan',NS):
            self.assertEqual(plan.find('s:cycleTime',NS).get('sec'),'80')
            phases = {}
            for group in plan.findall('s:signalGroupSettings',NS):
                phases[group.get('refId')] = set(range(int(group.find('s:onset',NS).get('sec')),
                                                     int(group.find('s:dropping',NS).get('sec'))))
            self.assertFalse(phases.get('avenida',set()) & phases.get('calle',set()))


if __name__ == '__main__':
    unittest.main()
