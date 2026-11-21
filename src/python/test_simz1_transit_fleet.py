"""Small synthetic fixed-fleet checks; no simulation and no real populations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_transit_fleet import (DEFAULT_CATALOG, SCHEMA, prepare, schedule_xml,
                                 validate_fleet, vehicles_xml)
from simz1_transit_accounting import planned_transit_counts

FIXTURE = Path(__file__).parent / 'fixtures' / 'simz1-transit-fleet-synthetic.json'


class FixedFleetTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.catalog = json.loads(DEFAULT_CATALOG.read_text(encoding='utf-8'))

    def validate(self):
        return validate_fleet(self.plan, self.catalog)

    def routes(self):
        return self.plan['services'][0]['routes']

    def exterior(self, duration=60):
        """A later outbound trip needs an explicit B-to-A exterior movement."""
        outbound, inbound = self.routes()
        outbound['departures'].append({'departure_id': 'synthetic_out_03',
                                       'time_s': 400, 'vehicle_id': 'synthetic_bus_01'})
        inbound['departures'] = [d for d in inbound['departures']
                                if d['vehicle_id'] != 'synthetic_bus_01']
        self.plan['transfers'] = [{'vehicle_id': 'synthetic_bus_01', 'kind': 'exterior',
                                  'from_departure_id': 'synthetic_out_01',
                                  'to_departure_id': 'synthetic_out_03', 'duration_s': duration,
                                  'evidence': {'status': 'synthetic', 'source': 'test fixture',
                                               'reason': 'Explicit invented time, not geographic travel evidence'}}]

    def production_gate_fixture(self):
        """An isolated fake catalog for gate tests; never enables a real service."""
        self.plan['synthetic'] = False
        self.plan['monte_carlo_persons'] = 150000  # Count metadata only; no persons are generated.
        self.plan['domain']['approved'] = True
        self.plan['domain']['synthetic'] = False
        self.plan['services'][0]['catalog_service_id'] = 'unit-test-evidence-service'
        self.catalog = {
            'schema_version': 'simz1-transit-evidence-v1', 'production_enabled': True,
            'test_only': 'Invented catalog isolated in memory; no actual service is enabled.',
            'domain': {'approved': True, 'link_ids': deepcopy(self.plan['domain']['link_ids'])},
            'services': [{'service_id': 'unit-test-evidence-service', 'production_enabled': True,
                          'verification': {'status': 'verified', 'blockers': []}}]}
        return deepcopy(self.plan['synthetic_network'])

    def partial_calendar_services(self):
        """Two configured services, one inactive today; their buses stay in B."""
        first = self.plan['services'][0]
        other = deepcopy(first)
        other['service_id'] = 'synthetic_inactive_service'
        other['vehicle_ids'] = ['synthetic_bus_02']
        other['calendar']['removed_dates'] = ['2026-10-22']
        first['vehicle_ids'] = ['synthetic_bus_01']
        for service in (first, other):
            for route in service['routes']:
                route['departures'] = [d for d in route['departures'] if d['vehicle_id'] in service['vehicle_ids']]
                if service is other:
                    route['route_id'] += '_inactive'
                    for dep in route['departures']:
                        dep['departure_id'] += '_inactive'
        self.plan['services'].append(other)
        return first, other

    def test_two_buses_reused_for_four_expeditions(self):
        result = self.validate()
        self.assertEqual(result['counts']['road_demand_persons'], 3)
        self.assertEqual(result['counts']['public_transport_vehicles_configured'], 2)
        self.assertEqual(result['counts']['public_transport_departures_scheduled'], 4)
        self.assertEqual([r['vehicle_id'] for r in result['roster']].count('synthetic_bus_01'), 2)
        self.assertEqual(result['counts']['transit_drivers_added_to_demand'], 0)
        self.assertIsNone(result['counts']['active_inside_domain'])
        self.assertIsNone(result['counts']['internal_transit_drivers'])

    def test_changing_b_does_not_change_n(self):
        before = self.validate()
        self.plan['vehicles'].append({'vehicle_id': 'synthetic_reserve_03', 'type_id': 'synthetic_rigid_bus'})
        self.plan['services'][0]['vehicle_ids'].append('synthetic_reserve_03')
        after = self.validate()
        self.assertEqual(before['counts']['road_demand_persons'], after['counts']['road_demand_persons'])
        self.assertEqual(after['counts']['public_transport_vehicles_configured'], 3)
        self.assertEqual(after['counts']['public_transport_departures_scheduled'], 4)
        self.assertEqual(after['service_counts'][0]['configured_buses'], 3)
        self.assertIn('synthetic_reserve_03', after['service_counts'][0]['configured_vehicle_ids'])

    def test_every_reserve_requires_explicit_service_assignment(self):
        self.plan['vehicles'].append({'vehicle_id': 'synthetic_reserve_03', 'type_id': 'synthetic_rigid_bus'})
        with self.assertRaisesRegex(ValueError, 'including reserves, must be assigned'):
            self.validate()

    def test_departure_cannot_use_another_services_bus_without_assignment(self):
        first, _ = self.partial_calendar_services()
        first['routes'][0]['departures'][0]['vehicle_id'] = 'synthetic_bus_02'
        with self.assertRaisesRegex(ValueError, 'not explicitly assigned to this service'):
            self.validate()

    def test_shared_bus_counts_are_global_union_not_service_sum(self):
        other = deepcopy(self.plan['services'][0])
        other['service_id'] = 'synthetic_later_service'
        for route in other['routes']:
            route['route_id'] += '_later'
            for departure in route['departures']:
                departure['departure_id'] += '_later'
                departure['time_s'] += 500
        self.plan['services'].append(other)
        result = self.validate()
        self.assertEqual(result['counts']['public_transport_vehicles_configured'], 2)
        self.assertEqual(result['counts']['public_transport_departures_scheduled'], 8)
        self.assertEqual([row['configured_buses'] for row in result['service_counts']], [2, 2])
        self.assertTrue(result['service_bus_counts_are_not_additive'])

    def test_partial_calendar_retains_assigned_fleet_and_inactive_line(self):
        self.partial_calendar_services()
        result = self.validate()
        self.assertEqual(result['counts']['public_transport_vehicles_configured'], 2)
        self.assertEqual(result['counts']['public_transport_departures_scheduled'], 2)
        self.assertEqual([row['scheduled_expeditions'] for row in result['service_counts']], [2, 0])
        root = ET.fromstring(schedule_xml(self.plan, result))
        lines = root.findall('transitLine')
        self.assertEqual(len(lines), 2)
        self.assertFalse(lines[1].findall('transitRoute'))
        attrs = {a.attrib['name']: a.text for a in lines[1].findall('./attributes/attribute')}
        self.assertEqual(attrs['simz1:assignedVehicleIds'], 'synthetic_bus_02')
        self.assertEqual(attrs['simz1:serviceActiveOnDate'], 'false')

    def test_ida_vuelta_not_closed_routes(self):
        for route in self.routes():
            self.assertNotEqual(route['link_ids'][0], route['link_ids'][-1])
        roster = self.validate()['roster']
        bus = [row for row in roster if row['vehicle_id'] == 'synthetic_bus_01']
        self.assertEqual(bus[0]['destination_stop_id'], bus[1]['origin_stop_id'])
        self.assertEqual(bus[0]['available_time_s'], 140)

    def test_same_bus_cannot_overlap(self):
        self.routes()[1]['departures'][0]['time_s'] = 50
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.validate()

    def test_terminal_and_turnaround_not_ignored(self):
        self.routes()[1]['departures'][0]['time_s'] = 139
        with self.assertRaisesRegex(ValueError, 'terminal/turnaround'):
            self.validate()

    def test_exact_availability_is_allowed(self):
        self.routes()[1]['departures'][0]['time_s'] = 140
        self.validate()

    def test_overlap_between_different_services(self):
        other = deepcopy(self.plan['services'][0])
        other['service_id'] = 'synthetic_other_service'
        for route in other['routes']:
            route['route_id'] += '_other'
            for dep in route['departures']:
                dep['departure_id'] += '_other'
        self.plan['services'].append(other)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.validate()

    def test_fleet_insufficient_does_not_invent_vehicle(self):
        self.plan['vehicles'].pop()
        self.plan['services'][0]['vehicle_ids'].pop()
        with self.assertRaisesRegex(ValueError, 'insufficient fleet'):
            self.validate()

    def test_unknown_type_rejected(self):
        self.plan['vehicles'][0]['type_id'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'unknown type'):
            self.validate()

    def test_dimensions_independent_of_pcu(self):
        before = vehicles_xml(self.plan)
        self.plan['vehicle_types'][0]['pcu'] = 9
        after = vehicles_xml(self.plan)
        ns = {'m': 'http://www.matsim.org/files/dtd'}
        for data in (before, after):
            kind = ET.fromstring(data).find('m:vehicleType', ns)
            self.assertEqual(kind.find('m:length', ns).attrib['meter'], '12')
            self.assertEqual(kind.find('m:width', ns).attrib['meter'], '2.5')

    def test_wrong_directed_stop_link_rejected(self):
        self.routes()[0]['stops'][1]['stop_id'] = 'synthetic_terminal_a'
        with self.assertRaisesRegex(ValueError, 'wrong directed link'):
            self.validate()

    def test_disconnected_route_rejected(self):
        self.routes()[0]['link_ids'][1] = 'b_to_a'
        with self.assertRaisesRegex(ValueError, 'disconnected or reversed'):
            self.validate()

    def test_bus_forbidden_access_rejected(self):
        self.plan['synthetic_network']['links'][1]['modes'] = ['car']
        with self.assertRaisesRegex(ValueError, 'bus access forbidden'):
            self.validate()

    def test_segregation_not_inferred_from_label(self):
        self.routes()[0]['traffic_regime'] = 'segregated'
        with self.assertRaisesRegex(ValueError, 'still permits cars'):
            self.validate()

    def test_bay_does_not_block_link(self):
        self.plan['stops'][0]['blocking_lane'] = True
        with self.assertRaisesRegex(ValueError, 'bay may not block'):
            self.validate()

    def test_dwell_assumption_and_xml_stops(self):
        root = ET.fromstring(schedule_xml(self.plan, self.validate()))
        stops = root.findall('./transitStops/stopFacility')
        self.assertEqual([s.attrib['isBlocking'] for s in stops], ['false', 'true'])
        for stop in stops:
            attrs = {a.attrib['name']: a.text for a in stop.findall('./attributes/attribute')}
            self.assertEqual(attrs['simz1:dwellBasis'], 'explicit_scenario_assumption')
            self.assertEqual(attrs['simz1:dwellSeconds'], '10')

    def test_submillisecond_times_survive_xml_without_rounding(self):
        route = self.routes()[0]
        departure = route['departures'][0]
        departure['time_s'] = 0.123456789
        final_stop = route['stops'][-1]
        final_stop['arrival_offset_s'] = 100.000000123456
        final_stop['departure_offset_s'] = 110.000000123456
        result = self.validate()
        root = ET.fromstring(schedule_xml(self.plan, result))
        xml_route = root.find("./transitLine/transitRoute[@id='synthetic_outbound']")
        xml_departure = xml_route.find("./departures/departure[@id='synthetic_out_01']")
        xml_stop = xml_route.findall('./routeProfile/stop')[-1]
        self.assertEqual(float(xml_departure.attrib['departureTime']), departure['time_s'])
        self.assertEqual(float(xml_stop.attrib['arrivalOffset']), final_stop['arrival_offset_s'])
        self.assertEqual(float(xml_stop.attrib['departureOffset']), final_stop['departure_offset_s'])
        metadata = {a.attrib['name']: a.text for a in xml_departure.findall('./attributes/attribute')}
        self.assertEqual(float(metadata['simz1:endTimeSeconds']),
                         float(xml_departure.attrib['departureTime']) + float(xml_stop.attrib['departureOffset']))
        row = next(row for row in result['roster'] if row['departure_id'] == departure['departure_id'])
        self.assertEqual(float(metadata['simz1:endTimeSeconds']), row['end_time_s'])

    def test_dwell_cannot_claim_observed_boarding_without_passengers(self):
        self.plan['dwell_provenance']['status'] = 'verified'
        with self.assertRaisesRegex(ValueError, 'dwell must be an explicit scenario assumption'):
            self.validate()

    def test_dwell_offsets_match_facility_assumption(self):
        self.routes()[0]['stops'][0]['departure_offset_s'] = 9
        with self.assertRaisesRegex(ValueError, 'dwell must match'):
            self.validate()

    def test_service_ends_and_removed_date_has_no_expeditions(self):
        self.plan['services'][0]['calendar']['removed_dates'] = ['2026-10-22']
        result = self.validate()
        self.assertEqual(result['counts']['public_transport_vehicles_configured'], 2)
        self.assertEqual(result['counts']['public_transport_departures_scheduled'], 0)
        root = ET.fromstring(schedule_xml(self.plan, result))
        self.assertFalse(root.findall('./transitLine/transitRoute/departures/departure'))
        self.assertEqual(len(root.findall('transitLine')), 1)  # Keeps configured ownership, including reserves.

    def test_after_calendar_end_no_expeditions(self):
        self.plan['service_date'] = '2026-10-23'
        self.assertEqual(self.validate()['counts']['public_transport_departures_scheduled'], 0)

    def test_departure_after_24_hours_rejected(self):
        self.routes()[1]['departures'][0]['time_s'] = 86350
        with self.assertRaisesRegex(ValueError, 'outside service day'):
            self.validate()

    def test_exterior_duration_retained_but_runtime_blocked(self):
        self.exterior()
        result = self.validate()
        self.assertEqual(result['compatibility'], 'blocked_exterior_runtime_not_implemented')
        self.assertEqual(result['transfers'][0]['duration_s'], 60)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new_fleet'
            with self.assertRaisesRegex(ValueError, 'blocked_exterior_runtime_not_implemented'):
                prepare(self.plan, self.catalog, output)
            self.assertFalse(output.exists())

    def test_exterior_insufficient_time_rejected(self):
        self.exterior(duration=261)
        with self.assertRaisesRegex(ValueError, 'insufficient terminal/turnaround/exterior'):
            self.validate()

    def test_exterior_source_required(self):
        self.exterior()
        self.plan['transfers'][0]['evidence']['source'] = None
        with self.assertRaisesRegex(ValueError, 'provenance|source'):
            self.validate()

    def test_no_implicit_return_teleport(self):
        self.exterior()
        self.plan['transfers'] = []
        with self.assertRaisesRegex(ValueError, 'no teleport'):
            self.validate()

    def test_exterior_vehicle_identity_preserved(self):
        self.exterior()
        self.plan['transfers'][0]['vehicle_id'] = 'synthetic_bus_02'
        with self.assertRaisesRegex(ValueError, 'identity changes'):
            self.validate()

    def test_real_catalog_blocked_before_writing(self):
        self.plan['synthetic'] = False
        self.plan['monte_carlo_persons'] = 150000
        self.plan['domain']['synthetic'] = False
        self.plan['domain']['approved'] = True
        self.plan['services'][0]['catalog_service_id'] = 'transmetro-l1'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new_fleet'
            with self.assertRaisesRegex(ValueError, 'catalog: production is disabled'):
                prepare(self.plan, self.catalog, output)
            self.assertFalse(output.exists())

    def test_synthetic_fixture_cannot_enable_real_candidate(self):
        self.plan['services'][0]['catalog_service_id'] = 'transmetro-l1'
        before = deepcopy(self.catalog)
        with self.assertRaisesRegex(ValueError, 'must not impersonate'):
            self.validate()
        self.assertEqual(self.catalog, before)
        self.assertTrue(all(not s['production_enabled'] for s in self.catalog['services']))

    def test_non_synthetic_n_range(self):
        self.plan['synthetic'] = False
        with self.assertRaisesRegex(ValueError, 'production N must be 150000..250000'):
            self.validate()

    def test_domain_must_be_explicit(self):
        self.plan['domain']['approved'] = True
        with self.assertRaisesRegex(ValueError, 'synthetic domain must not claim real approval'):
            self.validate()

    def test_link_outside_domain_blocks_native_preparation(self):
        self.plan['domain']['link_ids'].remove('a_to_b')
        result = self.validate()
        self.assertEqual(result['compatibility'], 'blocked_exterior_runtime_not_implemented')
        self.assertEqual(result['outside_domain_links'], ['a_to_b'])

    def test_in_lane_requires_explicit_native_blocking(self):
        self.plan['stops'][1]['blocking_lane'] = False
        with self.assertRaisesRegex(ValueError, 'in_lane requires explicit native blocking'):
            self.validate()

    def test_no_new_output_on_inactive_service_date(self):
        self.plan['service_date'] = '2026-10-23'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new_fleet'
            with self.assertRaisesRegex(ValueError, 'inactive_service_date'):
                prepare(self.plan, self.catalog, output)
            self.assertFalse(output.exists())

    def test_multilane_stop_not_falsely_claimed_as_one_lane_block(self):
        self.plan['synthetic_network']['links'][2]['lanes'] = 2
        with self.assertRaisesRegex(ValueError, 'unsupported_multilane_in_lane_stop'):
            self.validate()

    def test_native_xml_and_manifest_accounting_contract(self):
        manifest = self.validate()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'transitSchedule.xml').write_bytes(schedule_xml(self.plan, manifest))
            (folder / 'transitVehicles.xml').write_bytes(vehicles_xml(self.plan))
            (folder / 'config.xml').write_text(
                '<config><module name="transit"><param name="useTransit" value="true"/>'
                '<param name="transitScheduleFile" value="transitSchedule.xml"/>'
                '<param name="vehiclesFile" value="transitVehicles.xml"/></module></config>',
                encoding='utf-8')
            accounting = planned_transit_counts(folder / 'config.xml', 3)
        for field in ('road_demand_persons', 'public_transport_vehicles_configured',
                      'public_transport_departures_scheduled', 'transit_drivers_added_to_demand'):
            self.assertEqual(accounting[field], manifest['counts'][field])

    def test_future_production_catalog_snapshot_matches_native_metadata(self):
        network = self.production_gate_fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new_fleet'
            manifest = prepare(self.plan, self.catalog, output, network)
            raw = (output / 'enabled-catalog.json').read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(json.loads(raw), self.catalog)
            self.assertEqual(manifest['enabled_catalog_source'], digest)
            record = next(item for item in manifest['artifacts'] if item['path'] == 'enabled-catalog.json')
            self.assertEqual(record['sha256'], digest)
            root = ET.parse(output / 'transitSchedule.xml').getroot()
            attrs = {a.attrib['name']: a.text for a in root.findall('./attributes/attribute')}
            self.assertEqual(attrs['simz1:catalogFile'], 'enabled-catalog.json')
            self.assertEqual(attrs['simz1:catalogSha256'], digest)
            line = root.find('transitLine')
            attrs = {a.attrib['name']: a.text for a in line.findall('./attributes/attribute')}
            self.assertEqual(attrs['simz1:enabledCatalogSource'], digest)
            self.assertEqual(attrs['simz1:catalogServiceId'], 'unit-test-evidence-service')

    def test_future_enabled_service_must_still_be_verified(self):
        network = self.production_gate_fixture()
        self.catalog['services'][0]['verification']['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'unresolved verification'):
            validate_fleet(self.plan, self.catalog, network)

    def test_future_approved_domain_mapping_must_match_catalog(self):
        network = self.production_gate_fixture()
        self.catalog['domain']['link_ids'].pop()
        with self.assertRaisesRegex(ValueError, 'approved domain link mapping'):
            validate_fleet(self.plan, self.catalog, network)

    def test_existing_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'existing.txt'
            sentinel.write_text('preserve', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                prepare(self.plan, self.catalog, directory)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve')

    def test_user_preparation_artifacts_and_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new_fleet'
            manifest = prepare(self.plan, self.catalog, output)
            self.assertEqual(manifest['counts']['road_demand_persons'], 3)
            self.assertEqual({row['path'] for row in manifest['artifacts']},
                             {'transitSchedule.xml', 'transitVehicles.xml', 'roster.json',
                              'fleet-config.json', 'synthetic-network.xml'})
            root = ET.parse(output / 'transitSchedule.xml').getroot()
            departures = root.findall('./transitLine/transitRoute/departures/departure')
            self.assertEqual(len(departures), 4)
            self.assertEqual({d.attrib['vehicleRefId'] for d in departures},
                             {'synthetic_bus_01', 'synthetic_bus_02'})
            self.assertEqual(json.loads((output / 'fleet-config.json').read_text(encoding='utf-8'))['schema_version'], SCHEMA)


if __name__ == '__main__':
    unittest.main()
