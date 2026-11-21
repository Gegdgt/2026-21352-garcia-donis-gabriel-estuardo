"""Prepared, not executed by the agent: tiny fixtures; no simulation/server/browser."""
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_agent_types import (allocate_types, allocation_counts, load_catalog, validate_catalog,
    active_types, execution_blockers, catalog_manifest, vehicle_types_xml, allows_link)
from simz1_agent_demand import person_attributes, validate_road_access, typed_people, verify_type_ledger, generation_catalog
from simz1_population import person_vehicle_type, write_population, verify_population
from simz1_motion import read_vehicle_definitions, load_selected
from simz1_run import sha256
from simz1_temporal import trip_id
from simz1_road_catalog import SCHEMA, MOTOS, TYPES, BASE
from prepare_simz1_agents import prepare_agents

CATALOG = Path(__file__).resolve().parents[1]/'scenarios/zona1/agent-types-road-v1.json'


class RoadProfilesTest(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CATALOG)

    def test_default_future_allocation_never_assigns_transit(self):
        self.assertEqual(allocation_counts(1, self.catalog)['TransportePesado'], 0)
        with self.assertRaisesRegex(ValueError, 'TransportePesado'):
            generation_catalog(CATALOG, mode='montecarlo', temporal_profile=None, hourly_weights=None, drain_seconds=None)
        with tempfile.TemporaryDirectory() as folder:
            manifest = prepare_agents(Path(folder)/'new-proposal', 90, 17)
            self.assertEqual(manifest['passenger_persons'], 0)
            self.assertEqual(manifest['allocated_persons'], 90)
            self.assertEqual(set(manifest['person_counts']), set(TYPES))
            self.assertEqual(manifest['agent_configuration']['schema_version'], SCHEMA)
            self.assertEqual(manifest['agent_configuration']['normalized_weights']['road_denominator'], 90)
            self.assertEqual(manifest['status'], 'blocked')
            self.assertFalse(manifest['runnable'])

    def test_exact_hierarchical_quotas_seed_and_no_transit(self):
        self.assertEqual(allocation_counts(360, self.catalog), dict(zip(TYPES, (160, 25, 50, 25, 40, 40, 20))))
        for count in (0, 1, 2, 5, 10, 90, 101, 360):
            allocated = allocate_types(count, 17, self.catalog)
            self.assertEqual(len(allocated), count)
            self.assertEqual({k: Counter(allocated)[k] for k in TYPES}, allocation_counts(count, self.catalog))
            self.assertEqual(allocated, allocate_types(count, 17, self.catalog))
            self.assertNotIn('TransportePublico', allocated)
            self.assertNotIn('TransitBus', allocated)
        self.assertNotEqual(allocate_types(360, 17, self.catalog), allocate_types(360, 18, self.catalog))
        changed = copy.deepcopy(self.catalog)
        changed['allocation']['motorcycle_weights'] = dict(zip(MOTOS, (1, 0, 0)))
        old, new = allocation_counts(90, self.catalog), allocation_counts(90, changed)
        self.assertEqual(new['MotocicletaLenta'], 25)
        for kind in set(BASE)-{'Motociclista'}:
            self.assertEqual(new[kind], old[kind], 'Subtype weights only reassign motorcycles')
        fractions = catalog_manifest(self.catalog)['normalized_weights']
        self.assertEqual(fractions['road_denominator'], 90)
        self.assertEqual(fractions['road_fractions'], dict(zip(BASE, ('4/9','5/18','1/9','1/9','1/18'))))

    def test_unknowns_nonfinite_dimensions_routing_and_order_rejected(self):
        for key, value in [('pcu', 0), ('maximum_speed_kmh', float('nan')), ('family', 'carro'),
                           ('routing_preference', 'ignore-signals')]:
            bad = copy.deepcopy(self.catalog)
            bad['profiles']['Motociclista'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_catalog(bad)
        for change in ('unknown', 'bus', 'dimensions', 'order', 'acceleration', 'weights'):
            bad = copy.deepcopy(self.catalog)
            if change == 'unknown': bad['profiles']['unknown'] = bad['profiles']['Normal']
            if change == 'bus': bad['allocation']['road_weights']['TransportePublico'] = 10
            if change == 'dimensions': bad['profiles']['Motociclista']['dimensions']['width_m'] = 0
            if change == 'order': bad['profiles'][MOTOS[2]]['maximum_speed_kmh'] = 20
            if change == 'acceleration': bad['profiles']['Normal']['acceleration']['m_s2'] = 3
            if change == 'weights': bad['allocation']['motorcycle_weights'][MOTOS[0]] = -1
            with self.subTest(change=change), self.assertRaises(ValueError): validate_catalog(bad)
        with self.assertRaises(ValueError): execution_blockers(['unknown'], self.catalog)
        self.assertFalse(allows_link('Motociclista', 'pedestrian', ['walk'], self.catalog))
        self.assertFalse(allows_link('TransportePesado', 'road', ['car'], self.catalog))
        self.assertIn('route access', execution_blockers(active_types(self.catalog), self.catalog)[0])

    def test_every_moto_subtype_keeps_access_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            network = Path(folder)/'network.xml'
            for kind in MOTOS:
                catalog = copy.deepcopy(self.catalog)
                catalog['allocation']['motorcycle_weights'] = {k: int(k == kind) for k in MOTOS}
                for tag in ('motorcycle', 'maxspeed:motorcycle', 'motorcycle:conditional'):
                    network.write_text('<network><nodes/><links><link id="restricted"><attributes>'
                        f'<attribute name="osm:{tag}">no</attribute></attributes></link></links></network>')
                    with self.subTest(kind=kind, tag=tag), self.assertRaises(ValueError):
                        validate_road_access(network, catalog)

    def test_effective_xml_dimensions_mapping_and_historical_compatibility(self):
        ns = '{http://www.matsim.org/files/dtd}'
        root = vehicle_types_xml(self.catalog)
        self.assertEqual({t.get('id') for t in root.findall(ns+'vehicleType')}, set(TYPES))
        for t in root.findall(ns+'vehicleType'):
            spec = self.catalog['profiles'][t.get('id')]
            self.assertEqual(float(t.find(ns+'length').get('meter')), spec['dimensions']['length_m'])
            self.assertEqual(float(t.find(ns+'width').get('meter')), spec['dimensions']['width_m'])
            self.assertAlmostEqual(float(t.find(ns+'maximumVelocity').get('meterPerSecond')), spec['maximum_speed_kmh']/3.6)
        self.assertLess(self.catalog['profiles']['Motociclista']['dimensions']['length_m'], self.catalog['profiles']['Normal']['dimensions']['length_m'])
        self.assertGreater(self.catalog['profiles']['TransportePesado']['dimensions']['length_m'], self.catalog['profiles']['Normal']['dimensions']['length_m'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'types.xml'
            ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
            definitions, assignments = read_vehicle_definitions(path)
            self.assertEqual(assignments, {})
            self.assertEqual(definitions['Motociclista']['dimensions']['width_m'], .8)
            self.assertTrue(definitions['Motociclista']['dimensions']['assumed'])
        for kind in TYPES:
            person = ET.Element('person', id='unchanged')
            person_attributes(person, kind, self.catalog)
            self.assertEqual(person_vehicle_type(person), kind)
            self.assertEqual(person.get('id'), 'unchanged')
        old = load_catalog()
        self.assertEqual(allocation_counts(20, old), dict(zip(old['canonical_order'], (8,5,2,2,2,1))))
        person = ET.fromstring('<person id="old"><attributes><attribute name="drivingProfile">Tortuga</attribute></attributes></person>')
        self.assertEqual(person_vehicle_type(person), 'Tortuga')
        types, _ = read_vehicle_definitions(CATALOG.parent/'vehicle-types.xml')
        self.assertEqual(set(types), {'Normal','Tortuga','Liebre'})
        self.assertAlmostEqual(types['Tortuga']['maximum_velocity_mps'], 20/3.6)

    def test_tiny_export_and_replay_keep_ids_dimensions_and_counts(self):
        # User-run integration fixture only, never writes into a historical run.
        catalog = copy.deepcopy(self.catalog)
        catalog['allocation']['road_weights']['TransportePesado'] = 0
        self.assertEqual(execution_blockers(active_types(catalog), catalog), [])
        def people():
            for i in range(17):
                p = ET.Element('person', id=f'p{i}')
                a = ET.SubElement(p, 'attributes')
                ET.SubElement(a, 'attribute', name='simz1Trips').text = json.dumps([dict(id=trip_id(f'p{i}', 1), index=1,
                    planned_departure=0, origin_link='a', destination_link='b')])
                plan = ET.SubElement(p, 'plan', selected='yes')
                ET.SubElement(plan, 'activity', type='home', link='a', end_time='0')
                leg = ET.SubElement(plan, 'leg', mode='car')
                attrs = ET.SubElement(leg, 'attributes')
                ET.SubElement(attrs, 'attribute', name='simz1TripId').text = trip_id(f'p{i}', 1)
                ET.SubElement(plan, 'activity', type='work', link='b')
                yield p
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            types, plans, vehicles, ledger = [folder/p for p in ('types.xml','plans.xml','vehicles.xml','types.jsonl')]
            ET.ElementTree(vehicle_types_xml(catalog)).write(types, encoding='utf-8', xml_declaration=True)
            report = {}
            write_population(plans, vehicles, typed_people(people(), report, catalog, 17, 17, 1, {}, ledger), types, 'synthetic fixture')
            self.assertEqual(verify_type_ledger(plans, ledger, catalog), allocation_counts(17, catalog))
            actual = verify_population(plans, vehicles, 17, {'a','b'}, expected_trips_per_person=1, require_trip_ids=True)
            self.assertEqual((actual['persons'],actual['vehicles']), (17,17))
            (folder/'config.xml').write_text('<config/>')
            record = lambda name: dict(path=name, sha256=sha256(folder/name))
            context = load_selected(dict(directory=folder, iteration=0, plans=plans, manifest=dict(
                effective_config=record('config.xml'), effective_vehicles=record('vehicles.xml'),
                results={'0': dict(plans=record('plans.xml'))})))
            for p in ET.parse(plans).getroot().findall('person'):
                ident = p.get('id'); kind = person_vehicle_type(p); spec = catalog['profiles'][kind]
                metadata = context.metadata(ident, ident)
                self.assertEqual(metadata['Vehicle_Type'], kind)
                self.assertEqual(metadata['Driving_Profile'], spec['driving_profile'])
                self.assertEqual(metadata['Vehicle_Dimensions']['length_m'], spec['dimensions']['length_m'])
                self.assertEqual(metadata['Vehicle_Dimensions']['provenance']['artifact_sha256'], sha256(vehicles))
                self.assertNotIn(metadata['Vehicle_Type'], ('TransitBus','TransportePublico'))


if __name__ == '__main__':
    unittest.main()
