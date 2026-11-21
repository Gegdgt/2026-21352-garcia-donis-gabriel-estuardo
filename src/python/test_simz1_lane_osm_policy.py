"""Read-only reviewed lane audit and bounded XML mutations; never run QSim."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET

from simz1_config_validation import ConfigurationError
from simz1_lane_validation import audit_configuration, read_lanes
from simz1_osm_turn_audit import load_xml, source_way_id
from simz1_od_policy import validate_osm_turns
from simz1_sequence_contract import ROOT, load_contract


REVIEWED = ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2'
ORIGINAL = ROOT/'scenarios/zona1'
A = 'osm_1273145789_0_forward'
V = 'osm_1270930401_0_forward'
B = 'osm_1273145790_0_forward'
INCOMING = 'osm_1272828335_0_forward'
FORBIDDEN = 'osm_1272828334_0_forward'


class ReviewedLanePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lanes_xml = load_xml(REVIEWED/'lanes.xml')
        cls.lanes = read_lanes(REVIEWED/'lanes.xml')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            cls.report = audit_configuration(REVIEWED/'config-simz1.xml')

    def audit(self, **overrides):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return audit_configuration(REVIEWED/'config-simz1.xml',
                                       osm_path=REVIEWED/'map.osm', **overrides)

    def mutated_lanes(self, mutation, message):
        root = copy.deepcopy(self.lanes_xml)
        mutation(root)
        with tempfile.TemporaryDirectory(prefix='simz1-lane-policy-') as folder:
            path = Path(folder)/'lanes.xml'
            ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
            with self.assertRaisesRegex(ConfigurationError, message):
                self.audit(lanes_path=path)

    def test_all_ten_pairs_22_references_21_terminals_and_only_exits_changed(self):
        self.assertEqual(self.report['status'], 'valid')
        policy = self.report['turn_policy']
        expected = {(rule['relation_id'], *seq) for rule in load_contract()['restrictions']
                    for seq in rule['sequences'] if len(seq) == 2}
        actual = {(row['relation_id'], row['from_link'], row['to_link'])
                  for row in policy['pair_prohibitions']}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 10)
        original = read_lanes(ORIGINAL/'lanes.xml')
        differences, terminals, links = [], set(), set()
        self.assertEqual(original.keys(), self.lanes.keys())
        for link, lanes in original.items():
            self.assertEqual(lanes.keys(), self.lanes[link].keys())
            for lane, before in lanes.items():
                after = self.lanes[link][lane]
                self.assertEqual({k: v for k, v in before.items() if k != 'to_links'},
                                 {k: v for k, v in after.items() if k != 'to_links'})
                self.assertFalse(set(after['to_links']) - set(before['to_links']))
                for target in set(before['to_links']) - set(after['to_links']):
                    self.assertIn((link, target), {(a, b) for _, a, b in actual})
                    differences.append((lane, target)); terminals.add(lane); links.add(link)
        self.assertEqual((len(differences), len(terminals), len(links)), (22, 21, 9))
        self.assertEqual(self.report['counts']['assignments'], 6148)
        self.assertEqual(self.report['baseline_queue_metrics']['terminal_queues'], 7468)

    def test_original_remains_historical_and_reviewed_has_explicit_source_treatment(self):
        with patch('simz1_sequence_contract.load_contract', side_effect=AssertionError('historical source dependency')):
            self.assertIsNone(audit_configuration(ORIGINAL/'config-simz1.xml')['turn_policy'])
        treatment, = self.report['turn_policy']['source_treatments']
        self.assertEqual(treatment['relation_id'], '17884471')
        self.assertFalse(treatment['unrestricted_access_verified'])

    def test_reintroduced_17475192_is_rejected(self):
        def restore(root):
            leads = root.find(f".//lane[@id='{INCOMING}.lane.0']/leadsTo")
            ET.SubElement(leads, 'toLink', refId=FORBIDDEN)
        self.mutated_lanes(restore, '17475192')

    def test_legal_exits_and_each_pair_of_via_sequence_remain_required(self):
        for start, target in ((A, V), (V, B)):
            def remove(root):
                leads = root.find(f".//lane[@id='{start}.lane.0']/leadsTo")
                leads.remove(leads.find(f"toLink[@refId='{target}']"))
            with self.subTest(start=start, target=target):
                self.mutated_lanes(remove, 'movimientos car no alcanzables')
        sequence, = self.report['turn_policy']['sequence_relations']
        self.assertEqual(sequence['relation_id'], '17478998')
        self.assertEqual(sequence['sequences'], [[A, V, B]])

    def test_physical_and_structural_rejections_survive_osm_context(self):
        cases = [
            ('capacity', 'vehiclesPerHour', '9000', 'capacidad de flujo'),
            ('representedLanes', 'number', '3', 'representados terminales'),
            ('startsAt', 'meterFromLinkEnd', '9999', 'longitudes efectivas'),
            ('leadsTo/toLink', 'refId', 'missing-link', 'desconectado'),
        ]
        for child, key, value, message in cases:
            def change(root):
                root.find(f".//lane[@id='{INCOMING}.lane.0']/{child}").set(key, value)
            with self.subTest(child=child):
                self.mutated_lanes(change, message)
        def cycle(root):
            lane = root.find(f".//lane[@id='{INCOMING}.lane.0']")
            leads = lane.find('leadsTo')
            leads.clear()
            ET.SubElement(leads, 'toLane', refId=INCOMING+'.original')
        self.mutated_lanes(cycle, 'single lane entry|cycle|ciclo|cola aguas arriba')

    def test_missing_or_changed_car_provenance_is_rejected(self):
        for value in (None, '1272828334'):
            root = load_xml(REVIEWED/'network.xml')
            link = root.find(f"links/link[@id='{INCOMING}']")
            if value is None:
                link.attrib.pop('origid')
            else:
                link.set('origid', value)
            with tempfile.TemporaryDirectory(prefix='simz1-provenance-') as folder:
                path = Path(folder)/'network.xml'
                ET.ElementTree(root).write(path, encoding='utf-8')
                with self.subTest(value=value), self.assertRaisesRegex(ConfigurationError, 'procedencia OSM'):
                    self.audit(network_path=path)

    def test_conflicting_legacy_and_matsim_origids_are_rejected(self):
        link = ET.fromstring('<link id="a" origid="1"><attributes>'
                            '<attribute name="origid">2</attribute></attributes></link>')
        with self.assertRaisesRegex(ValueError, 'Contradictory OSM origid'):
            source_way_id(link)

    def test_copied_relation_in_unpinned_source_cannot_authorize_pair_exclusion(self):
        network = load_xml(REVIEWED/'network.xml')
        chosen = {INCOMING, FORBIDDEN, 'osm_381158266_0_forward'}
        for link in list(network.find('links')):
            if link.get('id') not in chosen:
                network.find('links').remove(link)
        ways = {link.get('origid') for link in network.findall('links/link')}
        osm = load_xml(REVIEWED/'map.osm')
        for element in list(osm):
            if not ((element.tag == 'relation' and element.get('id') == '17475192') or
                    (element.tag == 'way' and element.get('id') in ways)):
                osm.remove(element)
        lanes = ET.Element('laneDefinitions')
        lanes.append(copy.deepcopy(self.lanes_xml.find(f"lanesToLinkAssignment[@linkIdRef='{INCOMING}']")))
        with tempfile.TemporaryDirectory(prefix='simz1-unpinned-source-') as folder:
            folder = Path(folder)
            for name, root in (('network.xml', network), ('lanes.xml', lanes), ('map.osm', osm)):
                ET.ElementTree(root).write(folder/name, encoding='utf-8')
            with self.assertRaisesRegex(ConfigurationError, 'pair exclusions require the pinned source'):
                audit_configuration(REVIEWED/'config-simz1.xml', network_path=folder/'network.xml',
                                    lanes_path=folder/'lanes.xml', osm_path=folder/'map.osm')

    def test_20224473_bus_only_node_does_not_grant_car_access(self):
        root = load_xml(REVIEWED/'network.xml')
        first = root.find('links/link')
        ET.SubElement(root.find('nodes'), 'node', id='13568832045', x='0', y='0')
        extension = ET.SubElement(root.find('links'), 'link', dict(
            id='test_bus_extension', **{'from': first.get('from'), 'to': '13568832045'},
            origid=first.get('origid'), modes='bus', length='10', permlanes='1',
            capacity='1000', freespeed='10'))
        with tempfile.TemporaryDirectory(prefix='simz1-car-provenance-') as folder:
            path = Path(folder)/'network.xml'
            ET.ElementTree(root).write(path, encoding='utf-8')
            report = self.audit(network_path=path)
            self.assertEqual(report['signatures']['osm_provenance'], self.report['signatures']['osm_provenance'])
            self.assertEqual(report['turn_policy']['source_treatments'], self.report['turn_policy']['source_treatments'])
            extension.set('modes', 'car,bus')
            ET.ElementTree(root).write(path, encoding='utf-8')
            with self.assertRaisesRegex(ConfigurationError, 'procedencia OSM'):
                self.audit(network_path=path)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                with self.assertRaisesRegex(ValueError, '20224473'):
                    validate_osm_turns(REVIEWED/'map.osm', path, REVIEWED/'lanes.xml')


if __name__ == '__main__':
    unittest.main()
