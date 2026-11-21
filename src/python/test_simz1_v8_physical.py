"""V8 physical scope: preserve the mixed Plaza model, never invent segregation.

These are input/connectivity tests. Native movement, dwell FIFO and reservation
regressions remain the responsibility of the integrated Java validation.
"""
from copy import deepcopy
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from simz1_weekday_transit import derive_geometry, load_policy, prepared_network, read_json


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scenarios/zona1/od/balanced-gateway-v1/access-review-v2'
POLICY = ROOT / 'scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v8.json'
PLAZA = 'osm_1057486080_1_forward'
PLAZA_STOP = 'gis_station_41_L12_14106867_part1'


class V8PhysicalScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, policy_path = load_policy(POLICY, '2026-10-23', True)
        cls.bundle = read_json(policy_path.parent / cls.policy['routes_file'])
        config = ET.parse(SOURCE / 'config-l18-local-v1.xml').getroot()
        cls.network, cls.plan, cls.lane_root = derive_geometry(
            config, SOURCE, cls.policy, cls.bundle, 1000)
        cls.links = {x.get('id'): x for x in cls.network.findall('./links/link')}
        cls.assignments = {x.get('linkIdRef'): x for x in
                           cls.lane_root.findall('{*}lanesToLinkAssignment')}

    def test_plaza_retains_three_mixed_slots_and_total_capacity(self):
        link = self.links[PLAZA]
        self.assertEqual(set(link.get('modes').split(',')), {'bus', 'car'})
        self.assertEqual(float(link.get('permlanes')), 3)
        self.assertEqual(float(link.get('capacity')), 6000)
        lanes = self.assignments[PLAZA].findall('{*}lane')
        originals = [x for x in lanes if x.findall('{*}leadsTo/{*}toLane')]
        terminals = [x for x in lanes if x.findall('{*}leadsTo/{*}toLink')]
        self.assertEqual(len(originals), 1)
        self.assertEqual(len(terminals), 3)
        original = originals[0]
        self.assertEqual(original.get('id'), PLAZA + '.original')
        self.assertEqual(float(original.find('{*}representedLanes').get('number')), 3)
        self.assertEqual(float(original.find('{*}capacity').get('vehiclesPerHour')), 6000)
        self.assertEqual(sum(float(x.find('{*}representedLanes').get('number'))
                             for x in terminals), 3)
        self.assertEqual(sum(float(x.find('{*}capacity').get('vehiclesPerHour'))
                             for x in terminals), 6000)
        for lane in terminals:
            self.assertEqual([x.get('refId') for x in lane.findall('{*}leadsTo/{*}toLink')],
                             ['osm_1057486080_2_forward'])
            self.assertAlmostEqual(float(lane.find('{*}startsAt').get('meterFromLinkEnd')), 2)

    def test_all_bus_routes_remain_directed_and_have_native_terminal_access(self):
        for service in self.plan['services']:
            for route in service['routes']:
                for a, b in zip(route['link_ids'], route['link_ids'][1:]):
                    with self.subTest(service=service['service_id'], route=route['route_id'], a=a, b=b):
                        self.assertEqual(self.links[a].get('to'), self.links[b].get('from'))
                        self.assertIn('bus', self.links[a].get('modes').split(','))
                        self.assertIn('bus', self.links[b].get('modes').split(','))
                        assignment = self.assignments.get(a)
                        if assignment is not None:
                            exits = {x.get('refId') for x in assignment.findall(
                                '{*}lane/{*}leadsTo/{*}toLink')}
                            self.assertIn(b, exits)

    def test_plaza_is_one_blocking_original_queue_with_unchanged_body_and_gap(self):
        stops = [s for s in self.plan['stops'] if s['link_id'] == PLAZA and s['role'] != 'gateway']
        self.assertEqual([s['stop_id'] for s in stops], [PLAZA_STOP])
        stop = stops[0]
        self.assertTrue(stop['blocking_lane'])
        self.assertEqual(stop['dwell_seconds'], 25)
        self.assertEqual(stop['occupancy_basis'], 'scenario_blocking_native_queue_not_microscopic_lane')
        proxy = stop['proxy_placement']
        self.assertEqual(proxy['native_queue_id'], PLAZA + '.original')
        self.assertEqual(proxy['body_length_m'], 13.5)
        self.assertEqual(proxy['minimum_gap_m'], 0.10)
        self.assertAlmostEqual(proxy['native_service_endpoint_m'], float(self.links[PLAZA].get('length')) - 2)
        route = next(r for s in self.plan['services'] for r in s['routes']
                     if r['route_id'] == 'L12_14106867_part1')
        self.assertEqual(route['running_way'], 'mixed')

    def test_private_road_geometry_flow_and_access_are_preserved(self):
        source = ET.parse(SOURCE / 'network.xml').getroot()
        for original in source.findall('./links/link'):
            current = self.links[original.get('id')]
            with self.subTest(link=original.get('id')):
                for field in ('from', 'to', 'length', 'permlanes', 'capacity', 'freespeed'):
                    self.assertEqual(current.get(field), original.get(field))
                self.assertTrue(set(original.get('modes', 'car').split(',')) <=
                                set(current.get('modes', 'car').split(',')))

    def test_production_builder_rejects_disconnected_l12_mutation(self):
        bundle = deepcopy(self.bundle)
        part = next(p for s in bundle['services'] if s['service_id'] == 'transmetro_L12'
                    for p in s['parts'] if p['part_id'] == 'L12_14106867_part1')
        index = part['link_ids'].index(PLAZA)
        part['link_ids'][index] = part['link_ids'][index - 1]
        with self.assertRaisesRegex(ValueError, 'disconnected native route L12_14106867_part1'):
            prepared_network(SOURCE / 'network.xml', bundle)

    def test_production_builder_rejects_missing_l12_link_mutation(self):
        bundle = deepcopy(self.bundle)
        part = next(p for s in bundle['services'] if s['service_id'] == 'transmetro_L12'
                    for p in s['parts'] if p['part_id'] == 'L12_14106867_part1')
        part['link_ids'][part['link_ids'].index(PLAZA)] = 'invented_plaza_connector'
        with self.assertRaisesRegex(ValueError, 'missing/too short directed route'):
            prepared_network(SOURCE / 'network.xml', bundle)


if __name__ == '__main__':
    unittest.main()
