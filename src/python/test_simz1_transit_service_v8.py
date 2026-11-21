"""V8 serial-stop offer: real planning components, no QSim or event scan.

Optional SIMZ1_V8_CANDIDATE_ROOT lets an isolated candidate run these same
checks before integration. Production paths remain the default.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import simz1_weekday_transit as transit

PROJECT = Path(transit.__file__).resolve().parents[1]
CANDIDATES = Path(os.environ.get('SIMZ1_V8_CANDIDATE_ROOT', PROJECT))
REL = Path('scenarios/zona1/transit/weekday-v2')


def serial_loads(plan):
    """Aggregate by native queue, never by facility ID or direction label."""
    loads = defaultdict(float)
    members = defaultdict(list)
    stops = {s['stop_id']: s for s in plan['stops']}
    for service in plan['services']:
        cycle = sum(r['stops'][-1]['departure_offset_s'] +
                    r['transfer_after']['minimum_seconds'] for r in service['routes'])
        frequency = 3600 * service['buses'] / cycle
        for route in service['routes']:
            for visit in route['stops']:
                stop = stops[visit['stop_id']]
                if stop['role'] == 'gateway':
                    continue
                queue = stop.get('proxy_placement', {}).get('native_queue_id') or stop['link_id']
                loads[queue] += frequency
                members[queue].append((service['service_id'], route['route_id'], stop['stop_id']))
    return dict(loads), dict(members)


class TransitServiceV8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old_path = PROJECT / REL / 'service-fleet-176-93-v1.json'
        new_path = CANDIDATES / REL / 'service-fleet-176-93-v8.json'
        cls.old_policy, _ = transit.load_policy(old_path, '2026-10-23', True)
        cls.new_policy, _ = transit.load_policy(new_path, '2026-10-23', True)
        config_path = PROJECT / 'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/config-l18-local-v1.xml'
        cls.config = ET.parse(config_path).getroot()
        cls.base = config_path.parent
        cls.old_bundle, _ = transit.load_routes(cls.old_policy, old_path, cls.base / 'network.xml')
        cls.new_bundle = transit.read_json(new_path.parent / cls.new_policy['routes_file'])
        cls.old_net, cls.old_plan, cls.old_lanes = transit.derive_geometry(
            cls.config, cls.base, cls.old_policy, cls.old_bundle, 1000)
        cls.new_net, cls.new_plan, cls.new_lanes = transit.derive_geometry(
            cls.config, cls.base, cls.new_policy, cls.new_bundle, 1000)
        cls.new_xml = transit.schedule(cls.new_plan, transit.digest(new_path))

    def test_only_authorized_policy_fields_and_l12_transfers_change(self):
        old, new = deepcopy(self.old_policy), deepcopy(self.new_policy)
        for key in ('scenario_version', 'routes_file', 'assumptions', 'timetable_revision'):
            old.pop(key, None)
            new.pop(key, None)
        self.assertEqual(old, new)
        old, new = deepcopy(self.old_bundle), deepcopy(self.new_bundle)
        new.pop('timetable_revision')
        affected = []
        for service in new['services']:
            if service['service_id'] != 'transmetro_L12':
                continue
            for part in service['parts']:
                prior = next(s for s in old['services'] if s['service_id'] == 'transmetro_L12')
                original = next(p for p in prior['parts'] if p['part_id'] == part['part_id'])
                self.assertEqual(part['transfer_after']['minimum_seconds'], 400)
                self.assertEqual(part['transfer_after']['kind'], 'terminal')
                self.assertEqual(original['transfer_after']['minimum_seconds'], 180)
                affected.append(part['part_id'])
                part['transfer_after'] = original['transfer_after']
        self.assertEqual(len(affected), 2)
        self.assertEqual(old, new)

    def test_network_lanes_stops_dimensions_and_all_vehicle_ids_preserved(self):
        self.assertEqual(ET.tostring(self.old_net), ET.tostring(self.new_net))
        self.assertEqual(ET.tostring(self.old_lanes), ET.tostring(self.new_lanes))
        for key in ('stops', 'vehicles', 'vehicle_types', 'fleet_counts', 'domain_links'):
            self.assertEqual(self.old_plan[key], self.new_plan[key], key)
        self.assertEqual(len(self.new_plan['vehicles']), 269)
        self.assertEqual(self.new_policy['dwell_seconds'], 25)

    def test_plaza_is_one_direction_one_serial_native_queue(self):
        loads, members = serial_loads(self.new_plan)
        queue = 'osm_1057486080_1_forward.original'
        self.assertEqual(members[queue], [('transmetro_L12', 'L12_14106867_part1',
                                         'gis_station_41_L12_14106867_part1')])
        old, _ = serial_loads(self.old_plan)
        self.assertGreater(old[queue], 3600 / 25)
        self.assertLess(loads[queue], 3600 / 25)
        # No queue's summed ideal scheduled demand exceeds serial dwell capacity.
        self.assertTrue(all(rate <= 3600 / 25 for rate in loads.values()))
        self.assertAlmostEqual(3600 / loads[queue], 30.08895734090909, places=7)

    def test_other_services_and_their_shared_queue_loads_are_unchanged(self):
        old = {s['service_id']: s for s in self.old_plan['services']}
        new = {s['service_id']: s for s in self.new_plan['services']}
        for key in old.keys() - {'transmetro_L12'}:
            self.assertEqual(old[key], new[key], key)
        old_counts = Counter(row['service_id'] for row in self.old_plan['roster'])
        new_counts = Counter(row['service_id'] for row in self.new_plan['roster'])
        self.assertEqual(old_counts['transmetro_L12'], 6224)
        self.assertEqual(new_counts['transmetro_L12'], 4149)
        self.assertEqual(len(self.old_plan['roster']), 15336)
        self.assertEqual(len(self.new_plan['roster']), 13261)

    def test_l12_nominal_stop_service_windows_do_not_overlap(self):
        stops = {s['stop_id']: s for s in self.new_plan['stops']}
        l12 = next(s for s in self.new_plan['services'] if s['service_id'] == 'transmetro_L12')
        for route in l12['routes']:
            for visit in route['stops']:
                stop = stops[visit['stop_id']]
                if stop['role'] == 'gateway':
                    continue
                arrivals = sorted(d['time_s'] + visit['arrival_offset_s'] for d in route['departures'])
                self.assertTrue(all(b - a >= 30 for a, b in zip(arrivals, arrivals[1:])))
                self.assertTrue(all(b >= a + stop['dwell_seconds'] for a, b in zip(arrivals, arrivals[1:])))

    def test_serialized_roster_and_reuse_are_valid(self):
        result = transit.validate_serialized_timetable(self.new_xml)
        self.assertEqual(result['checked_vehicles'], 269)
        self.assertEqual(result['checked_departures'], 13261)
        for service in self.new_plan['services']:
            for row in self.new_plan['roster']:
                if row['service_id'] == service['service_id']:
                    self.assertLess(row['departure_time_s'], service['closes_s'])
                    self.assertLessEqual(row['end_time_s'], service['closes_s'])

    def test_negative_serialized_same_bus_overlap_is_rejected(self):
        root = ET.fromstring(self.new_xml)
        line = root.find("transitLine[@id='transmetro_L12']")
        rows = [d for d in line.findall('./transitRoute/departures/departure')
                if d.get('vehicleRefId') == 'ptbus_transmetro_L12_001']
        rows.sort(key=lambda d: float(d.get('departureTime')))
        first, second = rows[:2]
        start = float(first.get('departureTime'))
        duration = float(second.find("./attributes/attribute[@name='simz1:endTimeSeconds']").text) - float(second.get('departureTime'))
        second.set('departureTime', str(start))
        second.find("./attributes/attribute[@name='simz1:endTimeSeconds']").text = str(start + duration)
        with self.assertRaisesRegex(ValueError, 'overlapping duty'):
            transit.validate_serialized_timetable(ET.tostring(root))

    def test_negative_reverting_transfer_recreates_serial_overload(self):
        mutated = deepcopy(self.new_plan)
        l12 = next(s for s in mutated['services'] if s['service_id'] == 'transmetro_L12')
        for route in l12['routes']:
            route['transfer_after']['minimum_seconds'] = 180
        loads, _ = serial_loads(mutated)
        self.assertGreater(loads['osm_1057486080_1_forward.original'], 3600 / 25)

    def test_new_inputs_mutation_and_absence_fail_closed(self):
        for name in ('service-fleet-176-93-v8.json', 'route-bundle-service-v8.json'):
            source = CANDIDATES / REL / name
            expected = transit.digest(source)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / name
                path.write_bytes(source.read_bytes())
                self.assertEqual(transit.text_fingerprint(path, expected, name), 'exact')
                path.write_bytes(path.read_bytes() + b'\n ')
                with self.assertRaisesRegex(ValueError, 'fingerprint differs'):
                    transit.text_fingerprint(path, expected, name)
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    transit.text_fingerprint(path, expected, name)


if __name__ == '__main__':
    unittest.main()
