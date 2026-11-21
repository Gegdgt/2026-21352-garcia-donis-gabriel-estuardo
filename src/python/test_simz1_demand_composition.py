"""User-run regressions for non-public N and fixed public fleet; no MATSim/JVM."""
from collections import Counter
import copy
from fractions import Fraction
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_agent_types import load_catalog, allocation_counts, allocate_types, validate_catalog
from simz1_demand_composition import SCHEMA, contract, split, freight_options, validate_manifest
from simz1_freight import stratified_departures, permitted, WINDOWS, prepare
from simz1_population import population_spec, draw_population
from simz1_result_quality import assess

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'scenarios/zona1'
CATALOG = SCENARIO/'agent-types-nonpublic-v1.json'
OLD_CATALOG = SCENARIO/'agent-types-car-moto-v1.json'
SERVICE = SCENARIO/'freight/weekday-v1/service-composition-v1.json'
CONFIG = SCENARIO/'config-simz1.xml'
PUBLIC = SCENARIO/'transit/weekday-v2/service-fleet-176-93-v1.json'


class DemandCompositionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CATALOG)

    def test_exact_counts_and_nonpublic_denominator(self):
        expected = {
            0: (0, 0, 0), 1000: (432, 541, 27), 50000: (21622, 27027, 1351),
            180000: (77838, 97297, 4865), 200000: (86487, 108108, 5405),
            220000: (95135, 118919, 5946),
        }
        for total, values in expected.items():
            with self.subTest(total=total):
                result = split(total, self.catalog)
                self.assertEqual(result['family_counts'], dict(zip(('carro', 'moto', 'pesado'), values)))
                self.assertEqual(sum(result['family_counts'].values()), total)
                self.assertEqual(result['private_vehicles'] + result['freight_vehicles'], total)
                self.assertFalse(result['public_transport_in_total'])
                self.assertFalse(result['empirical_calibration'])
                self.assertEqual(sum(map(Fraction, result['family_fractions'].values())), 1)
                self.assertEqual(result['private_profile_counts']['TransportePesado'], 0)

    def test_family_profiles_and_versioned_public_configuration(self):
        # 444 gives exact family and internal profile quotas without rounding.
        result = split(444, self.catalog)
        self.assertEqual(result['private_profile_counts'], dict(
            Normal=128, Liebre=32, Tortuga=32, MotocicletaLenta=60,
            Motociclista=120, MotocicletaRapida=60, TransportePesado=0))
        old = load_catalog(OLD_CATALOG)
        self.assertEqual(self.catalog['profiles'], old['profiles'])
        self.assertEqual(self.catalog['temporal_demand'], old['temporal_demand'])
        public = json.loads(PUBLIC.read_text(encoding='utf-8'))
        self.assertEqual(public['fleet_counts'], dict(transmetro=176, tubus=93))
        self.assertEqual(sum(s['buses'] for s in public['services']), 269)

    def test_legacy_catalog_does_not_acquire_new_total_semantics(self):
        legacy = load_catalog(OLD_CATALOG)
        self.assertIsNone(contract(legacy))
        self.assertEqual(allocation_counts(120, legacy), dict(
            Normal=57, MotocicletaLenta=9, Motociclista=17,
            MotocicletaRapida=9, Liebre=14, Tortuga=14, TransportePesado=0))
        with self.assertRaises(ValueError):
            population_spec(agents=0)
        spec = population_spec(agents=0, allow_empty=True)
        self.assertEqual(draw_population(spec, random.Random(5)), 0)

    def test_invalid_counts_contract_and_double_freight_rejected(self):
        for total in (-1, True, 1.5, 250001):
            with self.subTest(total=total), self.assertRaises(ValueError):
                split(total, self.catalog)
        for field, value in (('public_transport_in_total', True), ('empirical_calibration', True)):
            catalog = copy.deepcopy(self.catalog)
            catalog['non_public_demand'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_catalog(catalog)
        mix = split(200000, self.catalog)
        with self.assertRaisesRegex(ValueError, 'expected 5405'):
            freight_options(mix, SERVICE, '2026-10-23', 12, False)
        with self.assertRaises(ValueError):
            freight_options(mix, SERVICE, '2026-10-23', None, True)
        with self.assertRaises(ValueError):
            freight_options(mix, None, None, None, False)
        self.assertEqual(freight_options(mix, SERVICE, '2026-10-23', None, False),
                         (SERVICE, '2026-10-23', 5405, False))
        self.assertEqual(freight_options(split(0, self.catalog), SERVICE, '2026-10-23', None, False),
                         (None, None, None, True))

    def test_reproducible_single_total_draw_and_profile_shuffle(self):
        spec = population_spec(min_agents=180000, max_agents=220000, massive=True)
        a = split(draw_population(spec, random.Random(20261029)), self.catalog)
        b = split(draw_population(spec, random.Random(20261029)), self.catalog)
        self.assertEqual(a, b)
        self.assertTrue(180000 <= a['total_non_public_vehicles'] <= 220000)
        kinds = allocate_types(973, 123, self.catalog)
        self.assertEqual(kinds, allocate_types(973, 123, self.catalog))
        self.assertNotEqual(kinds, allocate_types(973, 456, self.catalog))
        self.assertEqual(Counter(kinds), Counter({k: n for k, n in allocation_counts(973, self.catalog).items() if n}))

    def test_scaled_freight_schedule_preserves_windows_and_horizon(self):
        minima = [100., 240., 500., 700.]
        starts = stratified_departures(5946, minima, WINDOWS, 1800)
        self.assertEqual(starts, stratified_departures(5946, minima, WINDOWS, 1800))
        self.assertEqual(len(starts), 5946)
        for i, t in enumerate(starts):
            self.assertTrue(permitted(t, t + minima[i % 4] + 1800))
            self.assertLess(t + minima[i % 4] + 1800, 86400)
        for r in range(4):
            route_starts = starts[r::4]
            self.assertEqual(len(route_starts), len(set(route_starts)))
            self.assertEqual(route_starts, sorted(route_starts))
        self.assertTrue(any(t < 18000 for t in starts))
        self.assertTrue(any(32400 <= t < 57600 for t in starts))
        self.assertTrue(any(t >= 75600 for t in starts))
        with self.assertRaises(ValueError):
            stratified_departures(3, [200000.], WINDOWS, 1800)

    def test_preflight_bounds_and_zero_use_composed_quota(self):
        from simz1_experiment_preflight import check
        with patch('simz1_freight.preflight') as freight:
            freight.side_effect = lambda cfg, path, day, number, temporal: dict(
                enabled=True, vehicles_configured=number, departures_scheduled=number)
            result = check(CONFIG, CATALOG, 180000, 220000, 'uniform-nodes-v1', 'strict-receiver-v1',
                           freight_service=SERVICE, freight_service_date='2026-10-23')
            self.assertEqual([call.args[3] for call in freight.call_args_list], [4865, 5946])
            self.assertEqual(result['N_denominator'], 'non_public_vehicles')
            self.assertEqual(sum(result['minimum_allocation'].values()), 175135)
            freight.reset_mock()
            empty = check(CONFIG, CATALOG, 0, 0, 'uniform-nodes-v1', 'strict-receiver-v1',
                          freight_service=SERVICE, freight_service_date='2026-10-23')
            freight.assert_not_called()
            self.assertFalse(empty['freight_transport']['enabled'])
            self.assertEqual(sum(empty['minimum_allocation'].values()), 0)

    def test_new_service_scales_on_existing_routes_without_editing_sources(self):
        service, bundle, roster = prepare(CONFIG, SERVICE, vehicles=5405)
        self.assertEqual(len(roster), 5405)
        self.assertEqual(len({r['vehicle_id'] for r in roster}), 5405)
        self.assertEqual(service['dispatch_policy'], 'stratified-feasible-windows-v1')
        self.assertEqual(service['allowed_windows_seconds'], WINDOWS)
        for row in roster:
            self.assertTrue(permitted(row['departure_seconds']))
        # Explicit legacy service keeps the previous first dispatch unchanged.
        _, _, legacy = prepare(CONFIG, SERVICE.parent/'service.json', vehicles=12)
        self.assertEqual(legacy[0]['departure_seconds'], 3600)
        self.assertEqual(legacy[4]['departure_seconds'], 34320)

    def test_generate_inputs_zero_and_small_total_without_matsim(self):
        from generate_montecarlo_z1 import generar
        from simz1_run import population
        from simz1_freight import verified_contract
        for total in (0, 37):
            with self.subTest(total=total), tempfile.TemporaryDirectory() as td:
                run = Path(td)/'run-composition'
                generar(CONFIG, run, 20261029, agents=total, mode='montecarlo',
                        corridor_policy='redistribute', origin_policy='uniform-nodes-v1',
                        agent_catalog=CATALOG, freight_service=SERVICE,
                        freight_service_date='2026-10-23', storage_policy='strict-receiver-v1')
                manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
                mix = manifest['demand_composition']
                ids, counts = population(run/'plans.xml', allow_empty=total == 0)
                freight = verified_contract(run, manifest)
                validate_manifest(run, manifest, ids-freight.keys(), freight)
                self.assertEqual(len(ids), total)
                self.assertEqual(counts['planned_persons'], mix['private_vehicles'])
                self.assertEqual(manifest['counts']['non_public_vehicles_configured'], total)
                self.assertEqual(manifest['status'], 'prepared')
                with self.assertRaises(ValueError):
                    modified = copy.deepcopy(manifest)
                    modified['demand_composition']['total_non_public_vehicles'] = total + 1
                    validate_manifest(run, modified, ids-freight.keys(), freight)

    def test_freight_source_fingerprint_only_accepts_line_endings(self):
        import hashlib
        from simz1_freight import check_base_network_fingerprint
        lf = b'<network>\n<nodes/>\n</network>\n'
        crlf = lf.replace(b'\n', b'\r\n')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'network.xml'
            for payload, counterpart in ((lf, crlf), (crlf, lf)):
                path.write_bytes(payload)
                self.assertEqual(check_base_network_fingerprint(path, hashlib.sha256(payload).hexdigest()), 'exact')
                self.assertEqual(check_base_network_fingerprint(path, hashlib.sha256(counterpart).hexdigest()),
                                 'lf_crlf_source_equivalence_only')
            path.write_bytes(lf.replace(b'<nodes/>', b'<nodes><node id="changed"/></nodes>'))
            with self.assertRaises(ValueError):
                check_base_network_fingerprint(path, hashlib.sha256(crlf).hexdigest())

    def test_zero_private_transit_plan_keeps_fixed_public_service(self):
        from simz1_weekday_transit import (load_policy, load_routes, prepared_network,
                                         plan_with_service_queues)
        from simz1_stop_proxy import StopGeometry, lane_assignments, QUEUE_POLICY
        from simz1_run import parameters
        values = parameters(CONFIG)
        network = (CONFIG.parent/values['network.inputNetworkFile']).resolve()
        config = ET.parse(CONFIG).getroot()
        lane_path = (CONFIG.parent/values['network.laneDefinitionsFile']).resolve()
        # Verify source bytes even if a later assertion fails; only trees in memory change.
        for source in (network, lane_path):
            original = source.read_bytes()
            self.addCleanup(lambda source=source, original=original:
                            self.assertEqual(source.read_bytes(), original, str(source)))
        policy, path = load_policy(PUBLIC, '2026-10-23', True)
        bundle, _ = load_routes(policy, path, network)
        # Match attach()/preflight(): mapped bus extensions, then derived service queues.
        prepared = prepared_network(network, bundle)
        plan, lane_root = plan_with_service_queues(policy, bundle, prepared, 0, config, CONFIG.parent)
        self.assertEqual(plan['monte_carlo_persons'], 0)
        self.assertEqual(plan['fleet_counts'], dict(transmetro=176, tubus=93))
        self.assertEqual(len(plan['vehicles']), 269)
        vehicle_ids = [vehicle['vehicle_id'] for vehicle in plan['vehicles']]
        self.assertEqual(len(set(vehicle_ids)), 269)
        self.assertEqual({row['vehicle_id'] for row in plan['roster']}, set(vehicle_ids))
        departure_ids = [row['departure_id'] for row in plan['roster']]
        self.assertEqual(len(set(departure_ids)), len(departure_ids))
        expected_services = {service['service_id']: service for service in policy['services']}
        self.assertCountEqual([service['service_id'] for service in plan['services']], expected_services)
        self.assertCountEqual([vid for service in plan['services'] for vid in service['vehicle_ids']],
                              vehicle_ids)

        links = {link.get('id'): link for link in prepared.findall('./links/link')}
        base_links = {link.get('id') for link in ET.parse(network).getroot().findall('./links/link')}
        extensions = {link['id'] for link in bundle['additional_links']}
        self.assertNotIn('transit_osm_231755973_0_forward', base_links)
        self.assertIn('transit_osm_231755973_0_forward', extensions)
        self.assertEqual(set(links), base_links | extensions)
        self.assertEqual(set(plan['domain_links']), set(links))
        stops = {stop['stop_id']: stop for stop in plan['stops']}
        self.assertEqual(len(stops), len(plan['stops']))
        templates = {service['service_id']: service for service in bundle['services']}
        visited_stops = set()
        for service in plan['services']:
            expected = expected_services[service['service_id']]
            self.assertEqual(len(service['vehicle_ids']), expected['buses'])
            self.assertEqual(service['system'], expected['system'])
            parts = {part['part_id']: part for part in templates[service['service_id']]['parts']}
            self.assertCountEqual([route['route_id'] for route in service['routes']], parts)
            for route in service['routes']:
                part = parts[route['route_id']]
                self.assertEqual(route['link_ids'], part['link_ids'])
                self.assertTrue(set(route['link_ids']) <= set(links))
                self.assertTrue(route['departures'])
                visit_ids = [visit['stop_id'] for visit in route['stops']]
                self.assertEqual(len(visit_ids), len(set(visit_ids)))
                for source_stop in part['stops']:
                    self.assertIn(source_stop['stop_id'] + '_' + part['part_id'], visit_ids)
                for visit in route['stops']:
                    stop = stops[visit['stop_id']]
                    self.assertIn(stop['link_id'], links)
                    self.assertEqual(stop['link_id'], route['link_ids'][visit['link_index']])
                    visited_stops.add(stop['stop_id'])
        self.assertEqual(visited_stops, set(stops))

        self.assertIsNotNone(lane_root)
        self.assertTrue(plan['stop_proxy_summary']['enabled'])
        self.assertTrue(plan['stop_queue_summary']['enabled'])
        self.assertEqual(plan['stop_queue_summary']['policy'], QUEUE_POLICY)
        geometry = StopGeometry(links, {node.get('id'): node for node in prepared.findall('./nodes/node')},
                                lane_assignments(lane_root))
        for stop in plan['stops']:
            if stop['role'] != 'gateway':
                self.assertAlmostEqual(stop['proxy_placement']['native_service_endpoint_m'],
                                       geometry.native_endpoint(stop['link_id'])[0])

        # An absent reference is still rejected, rather than fabricated or skipped.
        broken_bundle = copy.deepcopy(bundle)
        missing = 'transit_missing_link_regression'
        self.assertNotIn(missing, links)
        broken_bundle['services'][0]['parts'][0]['link_ids'][1] = missing
        with self.assertRaisesRegex(ValueError, 'missing/too short directed route'):
            prepared_network(network, broken_bundle)

    def test_empty_quality_is_explicit_not_false_completion_or_legacy_pass(self):
        report = dict(counts=dict(selected_rows=0, completed=0, aborted=0, censored=0), profiles=[])
        self.assertEqual(assess(report)['status'], 'review_required')
        report['provenance'] = dict(demand_composition=split(0, self.catalog),
                                    population_counts=dict(planned_persons=0))
        result = assess(report, require_six=True)
        self.assertEqual(result['status'], 'not_applicable_no_private_demand')
        self.assertIsNone(result['completion_rate'])
        report['provenance']['population_counts']['planned_persons'] = 1
        self.assertEqual(assess(report)['status'], 'review_required')


if __name__ == '__main__':
    unittest.main()
