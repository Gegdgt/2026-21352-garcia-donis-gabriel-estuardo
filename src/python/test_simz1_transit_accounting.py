"""Small prepared input-count fixtures; never generate a population or run MATSim."""
from pathlib import Path
import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_transit_accounting import distinct_fleet_by_system, planned_transit_counts


class TransitAccountingTest(unittest.TestCase):
    def write_fixture(self, directory, buses=2):
        config = ET.Element('config')
        module = ET.SubElement(config, 'module', name='transit')
        for name, value in [('useTransit', 'true'), ('transitScheduleFile', 'schedule.xml'),
                            ('vehiclesFile', 'vehicles.xml')]:
            ET.SubElement(module, 'param', name=name, value=value)
        schedule = ET.Element('transitSchedule')
        attrs = ET.SubElement(schedule, 'attributes')
        ET.SubElement(attrs, 'attribute', name='simz1:fleetSchema').text = 'fixed-fleet-v1'
        ET.SubElement(attrs, 'attribute', name='simz1:monteCarloPersons').text = '3'
        ET.SubElement(attrs, 'attribute', name='simz1:configuredFleetSize').text = str(buses)
        ET.SubElement(attrs, 'attribute', name='simz1:scheduledExpeditions').text = str(buses * 2)
        line = ET.SubElement(schedule, 'transitLine', id='synthetic-service')
        line_attrs = ET.SubElement(line, 'attributes')
        ET.SubElement(line_attrs, 'attribute', name='simz1:assignedVehicleIds').text = ' '.join(
            f'synthetic-bus-{index}' for index in range(buses))
        for direction, start in [('outbound', 100), ('inbound', 1000)]:
            route = ET.SubElement(line, 'transitRoute', id=direction)
            departures = ET.SubElement(route, 'departures')
            for index in range(buses):
                ET.SubElement(departures, 'departure', id=f'{direction}-{index}',
                              departureTime=str(start + index * 100),
                              vehicleRefId=f'synthetic-bus-{index}')
        vehicles = ET.Element('vehicleDefinitions', xmlns='http://www.matsim.org/files/dtd')
        for index in range(buses):
            ET.SubElement(vehicles, 'vehicle', id=f'synthetic-bus-{index}', type='synthetic-bus')
        for name, root in [('config', config), ('schedule', schedule), ('vehicles', vehicles)]:
            ET.ElementTree(root).write(directory / f'{name}.xml', encoding='utf-8')
        return directory / 'config.xml'

    def test_N_is_unchanged_when_B_changes_and_trips_reuse_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            small = planned_transit_counts(self.write_fixture(directory, 2), 3)
            larger = planned_transit_counts(self.write_fixture(directory, 4), 3)
        self.assertEqual(small['road_demand_persons'], larger['road_demand_persons'])
        self.assertEqual(small['public_transport_vehicles_configured'], 2)
        self.assertEqual(small['public_transport_departures_scheduled'], 4)
        self.assertEqual(larger['public_transport_vehicles_configured'], 4)
        self.assertEqual(larger['public_transport_departures_scheduled'], 8)
        self.assertEqual(larger['transit_drivers_added_to_demand'], 0)
        self.assertIsNone(larger['public_transport_active_inside_domain'])
        self.assertIsNone(larger['transit_drivers_internal_observed'])

    def test_N_cannot_include_B(self):
        with tempfile.TemporaryDirectory() as folder:
            config = self.write_fixture(Path(folder))
            with self.assertRaisesRegex(ValueError, 'never add B'):
                planned_transit_counts(config, 5)

    def test_no_transit_preserves_road_count_without_reading_fleet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.xml'
            path.write_text('<config/>', encoding='utf-8')
            result = planned_transit_counts(path, 229629)
        self.assertEqual(result['road_demand_persons'], 229629)
        self.assertEqual(result['public_transport_vehicles_configured'], 0)
        self.assertEqual(result['public_transport_departures_scheduled'], 0)

    def test_unregistered_bus_is_not_an_extra_generated_person(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            config = self.write_fixture(directory)
            vehicles = ET.parse(directory / 'vehicles.xml')
            vehicles.getroot().clear()
            vehicles.write(directory / 'vehicles.xml')
            with self.assertRaisesRegex(ValueError, 'registered fleet vehicle IDs'):
                planned_transit_counts(config, 3)

    def test_mismatched_fleet_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            config = self.write_fixture(directory)
            schedule = ET.parse(directory / 'schedule.xml')
            schedule.find("./attributes/attribute[@name='simz1:configuredFleetSize']").text = '999'
            schedule.write(directory / 'schedule.xml')
            with self.assertRaisesRegex(ValueError, 'metadata configuredFleetSize'):
                planned_transit_counts(config, 3)

    def test_departure_identity_is_global_across_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            config = self.write_fixture(directory)
            schedule = ET.parse(directory / 'schedule.xml')
            departures = schedule.findall('.//departure')
            departures[-1].set('id', departures[0].get('id'))
            schedule.write(directory / 'schedule.xml')
            with self.assertRaisesRegex(ValueError, 'global departure ID'):
                planned_transit_counts(config, 3)

    def test_two_and_three_days_reuse_same_bus_ids_in_native_input_counts(self):
        for days in (2, 3):
            with self.subTest(days=days), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                config = self.write_fixture(directory)
                schedule = ET.parse(directory/'schedule.xml')
                line = schedule.find('./transitLine')
                ET.SubElement(line.find('attributes'), 'attribute', name='simz1:serviceSystem').text = 'transmetro'
                for day in range(1, days):
                    repeated = copy.deepcopy(line)
                    repeated.set('id', line.get('id')+f'-day{day}')
                    for departure in repeated.findall('.//departure'):
                        departure.set('id', departure.get('id')+f'-day{day}')
                        departure.set('departureTime', str(float(departure.get('departureTime'))+day*86400))
                    schedule.getroot().append(repeated)
                schedule.find("./attributes/attribute[@name='simz1:scheduledExpeditions']").text = str(4*days)
                schedule.write(directory/'schedule.xml')
                result = planned_transit_counts(config, 3)
                self.assertEqual(result['fleet_by_system'], {'transmetro': 2})
                self.assertEqual(result['public_transport_vehicles_configured'], 2)
                self.assertEqual(result['public_transport_departures_scheduled'], 4*days)

    def test_distinct_system_counts_reject_conflicting_or_unknown_buses(self):
        rows = [dict(system='transmetro', configured_vehicle_ids=['a']),
                dict(system='tubus', configured_vehicle_ids=['a'])]
        with self.assertRaisesRegex(ValueError, 'two systems'):
            distinct_fleet_by_system(rows, ['a'])
        with self.assertRaisesRegex(ValueError, 'outside'):
            distinct_fleet_by_system([dict(system='transmetro', configured_vehicle_ids=['b'])], ['a'])
        with self.assertRaisesRegex(ValueError, 'whole configured fleet'):
            distinct_fleet_by_system([dict(system='transmetro', configured_vehicle_ids=['a'])], ['a', 'b'])

    def test_unknown_legacy_system_remains_unclassified_and_reserves_are_counted(self):
        rows = [dict(system=None, configured_vehicle_ids=['a', 'reserve'])]
        self.assertEqual(distinct_fleet_by_system(rows, ['a', 'reserve']), {})
        rows[0]['system'] = 'transmetro'
        rows.append(dict(system='transmetro', configured_vehicle_ids=['a', 'reserve']))
        rows.append(dict(system='tubus', configured_vehicle_ids=['b']))
        self.assertEqual(distinct_fleet_by_system(rows, ['a', 'reserve', 'b']), {'transmetro': 2, 'tubus': 1})

    def test_duplicate_bus_ids_are_invalid(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            distinct_fleet_by_system([], ['a', 'a'])
        with self.assertRaisesRegex(ValueError, 'unique'):
            distinct_fleet_by_system([dict(system='transmetro', configured_vehicle_ids=['a', 'a'])], ['a'])


if __name__ == '__main__':
    unittest.main()
