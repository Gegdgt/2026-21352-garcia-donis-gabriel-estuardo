"""Small opt-in demand checks. No QSim, archived output, browser or server."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar, gateway_people, add_generation_options, generation_options, SCENARIO
from prepare_simz1_agents import prepare_agents
from simz1_agent_demand import generation_catalog, validate_road_access, typed_people, verify_type_ledger
from simz1_agent_types import load_catalog, allocation_counts, CANONICAL_TYPES, DEFAULT_CATALOG
from simz1_population import population_spec
from simz1_run import sha256, checked_path
from simz1_temporal import temporal_spec


def road_catalog():
    catalog = load_catalog()
    # Explicit test-only alternative. Production default stays 40/25/10/10/10/5.
    for name, share in zip(CANONICAL_TYPES, (40, 40, 10, 10, 0, 0)):
        catalog['profiles'][name]['share_percent'] = share
    return catalog


class AgentDemandTests(unittest.TestCase):
    def test_six_allocation_is_exact_reproducible_and_not_a_fake_run(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/name for name in ('first', 'second')]
            for path in paths:
                manifest = prepare_agents(path, 20, 17, trips_per_person=2, catalog_path=DEFAULT_CATALOG)
                records = [json.loads(line) for line in (path/'agent-types.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(len(records), 20)
                self.assertEqual(Counter(r['agent_type'] for r in records), dict(zip(CANONICAL_TYPES, (8, 5, 2, 2, 2, 1))))
                self.assertEqual(manifest['planned_trips'], 40)
                self.assertEqual(manifest['passenger_persons'], 2)
                self.assertIsNone(manifest['transit_service_vehicles'])
                self.assertEqual(manifest['instantiated_vehicles'], 0)
                self.assertFalse(manifest['runnable'])
                self.assertEqual(manifest['status'], 'blocked')
                self.assertTrue(all(r['effective_vehicle_type'] is None and r['vehicle_id'] is None for r in records))
                self.assertTrue(all(0 <= t < 86400 for r in records for t in r['planned_departures']))
                self.assertFalse((path/'plans.xml').exists())
                self.assertFalse((path/'config-simz1.xml').exists())
                for record in manifest['artifacts'].values():
                    self.assertEqual(record['sha256'], sha256(path/record['path']))
            self.assertEqual((paths[0]/'agent-types.jsonl').read_bytes(), (paths[1]/'agent-types.jsonl').read_bytes())
            with self.assertRaisesRegex(ValueError, 'carpeta nueva'):
                prepare_agents(paths[0], 20, 17)

    def test_complete_mix_fails_before_creating_directory_even_when_tiny(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'not-created'
            with self.assertRaisesRegex(ValueError, 'TransportePublico.*TransportePesado'):
                generar(SCENARIO/'config-simz1.xml', target, 17, agents=1,
                        corridor_policy='redistribute', agent_catalog=DEFAULT_CATALOG)
            self.assertFalse(target.exists())

    def test_catalog_cannot_change_historical_or_global_temporal_options(self):
        options = dict(mode='montecarlo', temporal_profile=None, hourly_weights=None, drain_seconds=None)
        for change in (dict(mode='historical'), dict(mode='debug'), dict(temporal_profile='peaks'),
                       dict(hourly_weights=[1]*24), dict(drain_seconds=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                generation_catalog(DEFAULT_CATALOG, **(options | change))
        parser = argparse.ArgumentParser()
        add_generation_options(parser)
        self.assertIsNone(generation_options(parser.parse_args([]))['agent_catalog'])
        self.assertEqual(generation_options(parser.parse_args(['--agent-catalog', str(DEFAULT_CATALOG)]))['agent_catalog'], DEFAULT_CATALOG)

    def test_motorcycle_specific_access_fails_closed_without_rewriting_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'network.xml'
            for key, value in (('motorcycle', 'no'), ('motorcycle:conditional', 'no @ (07:00-09:00)'),
                               ('maxspeed:motorcycle', '20'), ('restriction:motorcycle', 'no_left_turn')):
                xml = f'<network><nodes/><links><link id="restricted"><attributes><attribute name="osm:{key}">{value}</attribute></attributes></link></links></network>'
                path.write_text(xml, encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'motorcycle'):
                    validate_road_access(path, road_catalog())
                self.assertEqual(path.read_bytes(), before)
            path.write_text('<network><nodes/><links><link id="ok" modes="car"/></links></network>', encoding='utf-8')
            validate_road_access(path, road_catalog())

    def test_gateway_types_preserve_spatial_metadata_and_exact_range_draw(self):
        import random
        from simz1_population import draw_population
        from test_simz1_gateway_generation import TinyModel, KINDS
        catalog, model = road_catalog(), TinyModel()
        spec = population_spec(min_agents=3, max_agents=7)
        for seed in (-1, 0, 7):
            expected = draw_population(spec, random.Random(seed))
            temporal = temporal_spec()
            people, report, _ = gateway_people(model, seed, spec, dict.fromkeys(KINDS, .25), temporal)
            with tempfile.TemporaryDirectory() as folder:
                result = list(typed_people(people, report, catalog, expected, seed, 1, temporal, Path(folder)/'ledger.jsonl'))
                self.assertEqual(len(result), expected)
                self.assertEqual(report['agent_type_counts'], allocation_counts(expected, catalog))
                for person in result:
                    spatial = json.loads(person.findtext("attributes/attribute[@name='simz1SpatialOD']"))
                    for record in spatial.values():
                        model.validate_metadata(record)
                    self.assertEqual(person.find('plan/leg').get('mode'), 'car')

    def test_new_road_population_exact_types_vehicles_times_and_manifest(self):
        originals = {p: sha256(p) for p in (SCENARIO/'config-simz1.xml', SCENARIO/'vehicle-types.xml')}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            catalog = road_catalog()
            catalog_file = folder/'catalog.json'
            catalog_file.write_text(json.dumps(catalog), encoding='utf-8')
            hashes = []
            for run_name in ('a', 'b'):
                run = folder/run_name
                # Avoid scanning archived runs; every file generated here is tiny/new.
                with patch('generate_montecarlo_z1.duplicate_population_check', return_value={
                        'status': 'not_scanned_test', 'matches': [], 'unverifiable_manifests': []}):
                    report = generar(SCENARIO/'config-simz1.xml', run, 17, agents=20,
                                     corridor_policy='redistribute', trips_per_person=2, agent_catalog=catalog_file)
                self.assertEqual(report['xml_verified_counts']['persons'], 20)
                self.assertEqual(report['xml_verified_counts']['trips'], 40)
                self.assertEqual(report['xml_verified_counts']['vehicles'], 20)
                self.assertEqual(report['agent_type_counts'], allocation_counts(20, catalog))
                self.assertEqual(verify_type_ledger(run/'plans.xml', run/'inputs/agent-types.jsonl', catalog), report['agent_type_counts'])
                manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['temporal_demand']['profile'], 'by-agent-type')
                self.assertIsNone(manifest['temporal_demand']['hourly_probabilities'])
                self.assertEqual(manifest['agent_configuration']['realized_person_counts'], report['agent_type_counts'])
                self.assertNotIn('peak_mu_seconds', report)
                self.assertIn('input:agent-catalog.json', manifest['inputs'])
                self.assertIn('input:agent-types.jsonl', manifest['inputs'])
                record = manifest['agent_configuration']['person_type_artifact']
                self.assertEqual(record['sha256'], sha256(run/record['path']))
                ns = {'v': 'http://www.matsim.org/files/dtd'}
                vehicles = ET.parse(run/'inputs/vehicles.xml')
                turtle = vehicles.find("v:vehicleType[@id='Tortuga']/v:maximumVelocity", ns)
                self.assertAlmostEqual(float(turtle.get('meterPerSecond'))*3.6, 25)
                self.assertEqual(float(vehicles.find("v:vehicleType[@id='Motociclista']/v:passengerCarEquivalents", ns).get('pce')), .25)
                self.assertIsNone(vehicles.find("v:vehicleType[@id='TransitBus']", ns))
                self.assertEqual(len(vehicles.findall('v:vehicle', ns)), 20)
                for relative, source in (('inputs/network-inputNetworkFile.xml', SCENARIO/'network.xml'),
                                         ('inputs/network-laneDefinitionsFile.xml', SCENARIO/'lanes.xml'),
                                         ('inputs/signalsystems-signalsystems.xml', SCENARIO/'signalSystems.xml')):
                    self.assertEqual(sha256(run/relative), sha256(source))
                hashes.append(tuple(sha256(run/p) for p in ('plans.xml', 'inputs/vehicles.xml', 'inputs/agent-types.jsonl')))
                self.assertFalse((run/'output').exists())
                with self.assertRaisesRegex(ValueError, 'v2 requieren'):
                    generar(run/'config-simz1.xml', folder/(run_name+'-legacy'), 17, agents=1, corridor_policy='redistribute')
                self.assertFalse((folder/(run_name+'-legacy')).exists())
            self.assertEqual(hashes[0], hashes[1])
            records = folder/'a/inputs/agent-types.jsonl'
            records.write_text(records.read_text(encoding='utf-8').replace('Motociclista', 'Normal', 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'no coincide'):
                verify_type_ledger(folder/'a/plans.xml', records, catalog)
            saved = json.loads((folder/'a/run-manifest.json').read_text(encoding='utf-8'))
            with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
                checked_path(folder/'a', saved['inputs']['input:agent-types.jsonl'])
        self.assertEqual({p: sha256(p) for p in originals}, originals)


if __name__ == '__main__':
    unittest.main()
