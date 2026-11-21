import copy
from collections import Counter
import json
import unittest
import xml.etree.ElementTree as ET

from simz1_agent_types import (CANONICAL_TYPES, allocate_types, allocation_counts,
                              allows_link, catalog_manifest, execution_blockers,
                              load_catalog, profile_spec, require_executable,
                              road_vehicle_types, sample_departures, validate_catalog, vehicle_types_xml)


class SixCategoryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_six_types_exact_person_denominator_and_target_shares(self):
        self.assertEqual(self.catalog['denominator'], 'persons')
        self.assertEqual(list(self.catalog['profiles']), list(CANONICAL_TYPES))
        self.assertEqual([self.catalog['profiles'][n]['share_percent'] for n in CANONICAL_TYPES], [40, 25, 10, 10, 10, 5])
        self.assertEqual(sum(s['share_percent'] for s in self.catalog['profiles'].values()), 100)
        self.assertEqual(allocation_counts(100, self.catalog), dict(zip(CANONICAL_TYPES, (40, 25, 10, 10, 10, 5))))
        # Passenger share is not a bus count, and no road vehicle is assigned.
        pt = profile_spec('TransportePublico', self.catalog)
        self.assertEqual((pt['population_role'], pt['mode'], pt['vehicle_type'], pt['pcu']), ('passenger', 'pt', None, None))
        self.assertEqual(self.catalog['transit_service']['vehicle_type'], 'TransitBus')
        self.assertIsNone(self.catalog['transit_service']['fleet_size'])

    def test_integer_rounding_exact_small_counts_and_reproducible_seed(self):
        for count in (0, 1, 2, 3, 6, 7, 11, 19, 20, 99, 100, 101, 237):
            with self.subTest(count=count):
                first = allocate_types(count, 42, self.catalog)
                self.assertEqual(first, allocate_types(count, 42, self.catalog))
                self.assertEqual(len(first), count)
                counts = allocation_counts(count, self.catalog)
                self.assertEqual(sum(counts.values()), count)
                self.assertEqual(Counter(first), Counter({k: v for k, v in counts.items() if v}))
                self.assertEqual(Counter(first), Counter(allocate_types(count, 8, self.catalog)))
                for name, actual in counts.items():
                    self.assertLess(abs(actual-count*self.catalog['profiles'][name]['share_percent']/100), 1)
        self.assertNotEqual(allocate_types(100, 7, self.catalog), allocate_types(100, 8, self.catalog))
        # The 0.5 remainder tie between Liebre/Tortuga/PT uses canonical order.
        self.assertEqual(allocation_counts(5, self.catalog), dict(zip(CANONICAL_TYPES, (2, 1, 1, 1, 0, 0))))
        for invalid in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                allocate_types(invalid, 7, self.catalog)

    def test_vehicle_pcu_and_speed_no_fabricated_heavy_or_passenger_vehicle(self):
        actual = road_vehicle_types(self.catalog)
        for name, pcu, maximum in [('Normal', 1, 50), ('Motociclista', .25, 60), ('Liebre', 1, 90), ('Tortuga', 1, 25)]:
            self.assertEqual(actual[name]['pcu'], pcu)
            self.assertEqual(actual[name]['maximum_speed_kmh'], maximum)
            self.assertAlmostEqual(actual[name]['maximum_speed_m_s'], maximum/3.6)
        self.assertNotIn('TransportePesado', actual)
        self.assertNotIn('TransportePublico', actual)
        self.assertEqual(self.catalog['profiles']['TransportePesado']['pcu'], 3.5)
        self.assertIsNone(self.catalog['profiles']['TransportePesado']['maximum_speed_kmh'])
        self.assertEqual(self.catalog['transit_service']['pcu'], 3)

    def test_departures_reproducible_disjoint_person_streams_in_horizon(self):
        for name in CANONICAL_TYPES:
            times = sample_departures(name, 64, 3, 'person:one', self.catalog)
            self.assertEqual(times, sorted(set(times)))
            self.assertEqual(times, sample_departures(name, 64, 3, 'person:one', self.catalog))
            self.assertNotEqual(times, sample_departures(name, 64, 3, 'person:two', self.catalog))
            self.assertTrue(all(0 <= t < 86400 for t in times))
            intervals = profile_spec(name, self.catalog)['departure_intervals']
            self.assertTrue(all(any(i['start_seconds'] <= t < i['end_seconds'] for i in intervals) for t in times))
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            sample_departures('Bus', 1, 1, 'p', self.catalog)
        self.assertEqual(sample_departures('Normal', 0, 1, 'p', self.catalog), [])

    def test_peak_day_and_proposed_night_windows(self):
        normal = profile_spec('Normal', self.catalog)['departure_intervals']
        self.assertEqual([(i['start_seconds'], i['end_seconds']) for i in normal if i['weight'] == 4], [(21600, 30600), (61200, 70200)])
        turtle = sample_departures('Tortuga', 300, 42, 't', self.catalog)
        self.assertGreater(sum(21600 <= t < 64800 for t in turtle), 210)
        self.assertTrue(any(t < 21600 or t >= 64800 for t in turtle))
        heavy = sample_departures('TransportePesado', 300, 42, 'h', self.catalog)
        self.assertTrue(all(t < 18000 or 32400 <= t < 59400 or 75600 <= t < 86400 for t in heavy))
        self.assertTrue(any(t < 18000 for t in heavy))
        self.assertTrue(any(t >= 75600 for t in heavy))
        self.assertEqual(self.catalog['profiles']['TransportePesado']['access']['municipal_status'], 'unverified_assumption')

    def test_access_allowlist_cannot_grant_non_car_links(self):
        self.assertTrue(allows_link('Normal', 'forward', {'car'}, self.catalog))
        self.assertFalse(allows_link('Normal', 'walk', {'walk'}, self.catalog))
        self.assertFalse(allows_link('TransportePublico', 'forward', {'car', 'pt'}, self.catalog))
        self.assertFalse(allows_link('TransportePesado', 'forward', {'car'}, self.catalog))
        self.catalog['profiles']['TransportePesado']['access']['authorized_link_ids'] = ['forward']
        self.assertTrue(allows_link('TransportePesado', 'forward', {'car'}, self.catalog))
        self.assertFalse(allows_link('TransportePesado', 'reverse', {'car'}, self.catalog))
        self.assertFalse(allows_link('TransportePesado', 'forward', {'walk'}, self.catalog))
        # Sampling/allowlisting cannot claim enforcement of actual traversal times.
        self.assertTrue(any('traversal' in b for b in execution_blockers(['TransportePesado'], self.catalog)))

    def test_no_fabricated_fixed_transit_or_heavy_execution(self):
        require_executable(['Normal', 'Motociclista', 'Liebre', 'Tortuga'], self.catalog)
        for name in ('TransportePublico', 'TransportePesado'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                require_executable([name], self.catalog)
        service = self.catalog['transit_service']
        for key in ('schedule_file', 'vehicles_file', 'frequency', 'fleet_size'):
            self.assertIsNone(service[key])
        # Merely filling a path must not pretend that a validated adapter exists.
        service.update(schedule_file='schedule.xml', vehicles_file='vehicles.xml', route_source='survey', stop_source='survey', maximum_speed_kmh=40)
        self.assertTrue(any('adapter' in b for b in execution_blockers(['TransportePublico'], self.catalog)))

    def test_manifest_snapshot_is_serializable_stable_and_not_aliasing(self):
        first = catalog_manifest(self.catalog)
        second = catalog_manifest(json.loads(json.dumps(self.catalog)))
        self.assertEqual(first, second)
        self.assertEqual(len(first['sha256']), 64)
        self.assertEqual(first['catalog']['profiles']['Tortuga']['maximum_speed_kmh'], 25)
        self.catalog['profiles']['Tortuga']['departure_intervals'][1]['weight'] = 5
        self.assertEqual(first['catalog']['profiles']['Tortuga']['maximum_speed_kmh'], 25)
        self.assertEqual(first['catalog']['profiles']['Tortuga']['departure_intervals'][1]['weight'], 4)
        self.assertNotEqual(first['sha256'], catalog_manifest(self.catalog)['sha256'])

    def test_xml_v2_namespace_pce_and_explicit_schema_without_new_physics(self):
        root = ET.fromstring(ET.tostring(vehicle_types_xml(self.catalog)))
        ns = {'v': 'http://www.matsim.org/files/dtd'}
        self.assertEqual(root.tag, '{http://www.matsim.org/files/dtd}vehicleDefinitions')
        types = root.findall('v:vehicleType', ns)
        self.assertEqual([v.get('id') for v in types], ['Normal', 'Motociclista', 'Liebre', 'Tortuga'])
        for vehicle in types:
            expected = profile_spec(vehicle.get('id'), self.catalog)
            self.assertEqual(float(vehicle.find('v:passengerCarEquivalents', ns).get('pce')), expected['pcu'])
            self.assertEqual(float(vehicle.find('v:maximumVelocity', ns).get('meterPerSecond')), expected['maximum_speed_kmh']/3.6)
            self.assertEqual(vehicle.findtext("v:attributes/v:attribute[@name='simz1AgentSchema']", namespaces=ns), 'simz1-six-v1')
            self.assertIsNone(vehicle.find("v:attributes/v:attribute[@name='desiredAccelerationMps2']", ns))
            self.assertEqual(vehicle.find('v:networkMode', ns).get('networkMode'), 'car')
            self.assertEqual(vehicle.find('v:length', ns).get('meter'), '4.5')

    def test_road_only_variant_is_explicit_and_manifest_separates_unavailable_capabilities(self):
        shares = (50, 25, 15, 10, 0, 0)
        for name, share in zip(CANONICAL_TYPES, shares):
            self.catalog['profiles'][name]['share_percent'] = share
        manifest = catalog_manifest(self.catalog)
        self.assertEqual(manifest['execution_blockers'], [])
        self.assertTrue(manifest['unavailable_capabilities'])
        self.assertEqual(sum(allocation_counts(23, self.catalog).values()), 23)

    def test_catalog_rejects_ambiguous_units_unknown_types_bad_ranges(self):
        mutations = [lambda c: c.update(denominator='vehicles'),
                     lambda c: c['profiles']['Normal'].update(share_percent=41),
                     lambda c: c['profiles']['Normal'].update(share_percent=40.0),
                     lambda c: c['profiles']['Normal'].update(pcu=float('nan')),
                     lambda c: c['profiles']['Normal'].update(maximum_speed_kmh=0),
                     lambda c: c['profiles']['Normal'].update(maximum_speed_kmh=51),
                     lambda c: c['profiles']['Motociclista'].update(pcu=1),
                     lambda c: c['profiles']['Liebre'].update(routing_preference='ignore-red'),
                     lambda c: c['profiles']['TransportePesado'].update(pcu=2),
                     lambda c: c['profiles'].update(Bus=c['profiles']['Normal']),
                     lambda c: c['profiles']['TransportePublico'].update(vehicle_type='TransitBus'),
                     lambda c: c['profiles']['Normal']['departure_intervals'][0].update(end_seconds=21601),
                     lambda c: c['profiles']['Normal']['departure_intervals'][0].update(start_seconds=-1),
                     lambda c: c['profiles']['Normal']['departure_intervals'][-1].update(end_seconds=86401),
                     lambda c: c['profiles']['Motociclista']['departure_intervals'][0].update(weight=0),
                     lambda c: c['profiles']['Motociclista']['departure_intervals'][0].update(weight=1e308),
                     lambda c: [i.update(weight=3e303) for i in c['profiles']['Normal']['departure_intervals']],
                     lambda c: c['profiles']['TransportePesado']['access'].update(municipal_status='verified_source'),
                     lambda c: c['transit_service'].update(operation_end_seconds=70000)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                invalid = copy.deepcopy(self.catalog)
                mutate(invalid)
                with self.assertRaises(ValueError):
                    validate_catalog(invalid)


if __name__ == '__main__':
    unittest.main()
