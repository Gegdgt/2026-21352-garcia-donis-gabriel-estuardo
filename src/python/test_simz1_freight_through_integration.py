"""Versioned through-freight input regressions; no JVM, QSim, or event replay."""
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar
from simz1_agent_types import load_catalog
from simz1_demand_composition import freight_options, split, validate_manifest
from simz1_freight import is_freight, permitted, prepare, verified_contract
from simz1_run import parameters, population, sha256
from simz1_transit_accounting import verified_weekday_fleet


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/zona1'
CONFIG = SCENARIO / 'config-simz1.xml'
CATALOG = SCENARIO / 'agent-types-nonpublic-v1.json'
HISTORICAL = SCENARIO / 'freight/weekday-v1/service-composition-v1.json'
CURRENT = SCENARIO / 'freight/weekday-v2/service-composition-v2.json'
PUBLIC = SCENARIO / 'transit/weekday-v2/service-fleet-176-93-v1.json'
SERVICE_DATE = '2026-10-23'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def generate_inputs(run, service, total, **generation_options):
    """Prepare small temporary inputs using the public entry point, never simulate."""
    with redirect_stdout(io.StringIO()):
        generar(CONFIG, run, 20261030, agents=total, mode='montecarlo',
                corridor_policy='redistribute', origin_policy='uniform-nodes-v1',
                agent_catalog=CATALOG, storage_policy='strict-receiver-v1',
                transit_service=PUBLIC, transit_service_date=SERVICE_DATE,
                accept_transit_route_assumptions=True,
                freight_service=service, freight_service_date=SERVICE_DATE,
                **generation_options)
    return read_json(run / 'run-manifest.json')


class ThroughFreightContractTests(unittest.TestCase):
    def test_new_service_preserves_physics_windows_and_dispatch_contract(self):
        old, new = read_json(HISTORICAL), read_json(CURRENT)
        invariant = ('schema_version', 'service_date', 'vehicles', 'gross_weight_tonnes',
                     'pcu', 'maximum_speed_kmh', 'length_m', 'width_m', 'body_contract',
                     'allowed_windows_seconds', 'residence_policy', 'departure_slots_seconds',
                     'dispatch_spacing_seconds', 'clearance_margin_seconds', 'dispatch_policy',
                     'empirical_calibration')
        self.assertEqual({k: new[k] for k in invariant}, {k: old[k] for k in invariant})
        self.assertEqual((new['length_m'], new['width_m'], new['pcu'],
                          new['gross_weight_tonnes'], new['maximum_speed_kmh']),
                         (12, 2.5, 3.5, 12, 40))
        self.assertEqual(new['schema_version'], 'simz1-freight-weekday-v1')
        self.assertEqual(new['service_version'], 'weekday-v2')
        self.assertEqual(new['route_policy'], 'principal-through-v2')

    def test_N_quota_and_four_route_balance_survive_service_change(self):
        catalog = load_catalog(CATALOG)
        values = parameters(CONFIG)
        network = ET.parse(CONFIG.parent / values['network.inputNetworkFile']).getroot()
        links = {row.get('id'): row for row in network.findall('links/link')}
        for total, expected_trucks in ((1000, 27), (200000, 5405)):
            mix = split(total, catalog)
            self.assertEqual(mix['freight_vehicles'], expected_trucks)
            self.assertEqual(mix['private_vehicles'] + expected_trucks, total)
            rosters = []
            for source in (HISTORICAL, CURRENT):
                with self.subTest(N=total, service=source.parent.name):
                    selected, day, count, disabled = freight_options(
                        mix, source, SERVICE_DATE, None, False)
                    self.assertFalse(disabled)
                    service, bundle, roster = prepare(CONFIG, selected, day, count)
                    self.assertEqual(len(roster), expected_trucks)
                    self.assertEqual(len({r['vehicle_id'] for r in roster}), expected_trucks)
                    route_ids = {r['route_id'] for r in bundle['routes']}
                    self.assertEqual(len(route_ids), 4)
                    counts = Counter(r['route_id'] for r in roster)
                    self.assertEqual(set(counts), route_ids)
                    self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
                    minimum = {r['route_id']: sum(float(links[k].get('length')) /
                               min(float(links[k].get('freespeed')), service['maximum_speed_kmh']/3.6)
                               for k in r['link_ids']) for r in bundle['routes']}
                    for row in roster:
                        end = (row['departure_seconds'] + minimum[row['route_id']] +
                               service['clearance_margin_seconds'])
                        self.assertTrue(permitted(row['departure_seconds'], end,
                                                  windows=service['allowed_windows_seconds']))
                        self.assertLess(end, 86400)
                    rosters.append(roster)
            self.assertEqual([r['vehicle_id'] for r in rosters[0]],
                             [r['vehicle_id'] for r in rosters[1]])


class GeneratedThroughFreightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.runs = {}
        # N=148 yields 64 cars, 80 motorcycles and one truck on each of four routes.
        for label, service in (('historical', HISTORICAL), ('current', CURRENT)):
            run = cls.root / label
            cls.runs[label] = (run, generate_inputs(run, service, 148))

    def test_switching_freight_preserves_private_plans_types_and_all_269_buses(self):
        snapshots = []
        for run, manifest in self.runs.values():
            self.assertEqual(manifest['status'], 'prepared')
            self.assertEqual(manifest['demand_composition']['family_counts'],
                             dict(carro=64, moto=80, pesado=4))
            self.assertEqual(manifest['counts']['planned_persons'], 144)
            self.assertEqual(manifest['counts']['all_vehicles_configured'], 417)
            public = verified_weekday_fleet(run, manifest, 144)
            self.assertEqual(public['fleet_by_system'], dict(transmetro=176, tubus=93))
            self.assertEqual(len(set(public['fleet_vehicle_ids'])), 269)
            people = ET.parse(run / 'plans.xml').getroot()
            private = {p.get('id'): ET.tostring(p) for p in people.findall('person') if not is_freight(p)}
            vehicles = ET.parse(run / 'inputs/vehicles.xml').getroot()
            private_types = {t.get('id'): ET.tostring(t) for t in vehicles.findall('{*}vehicleType')
                             if t.get('id') != 'FreightTruck'}
            private_vehicles = {v.get('id'): v.get('type') for v in vehicles.findall('{*}vehicle')
                                if v.get('type') != 'FreightTruck'}
            public_files = {name: (run / 'inputs/transit-weekday' / name).read_bytes()
                            for name in ('transitSchedule.xml', 'transitVehicles.xml',
                                         'roster.json', 'weekday-policy.json')}
            self.assertEqual(len(private), 144)
            self.assertEqual(len(private_vehicles), 144)
            snapshots.append((private, private_types, private_vehicles, public_files))
        self.assertEqual(*snapshots)

    def test_each_truck_has_only_external_entry_one_leg_and_external_exit(self):
        for label, (run, manifest) in self.runs.items():
            with self.subTest(service=label):
                contract = verified_contract(run, manifest)
                ids, counts = population(run / 'plans.xml')
                validate_manifest(run, manifest, ids - contract.keys(), contract)
                self.assertEqual(len(contract), 4)
                self.assertEqual(counts['planned_persons'], 144)
                people = ET.parse(run / 'plans.xml').getroot()
                for person in people.findall('person'):
                    if not is_freight(person):
                        continue
                    plans = person.findall('plan')
                    self.assertEqual(len(plans), 1)
                    self.assertEqual(plans[0].get('selected'), 'yes')
                    self.assertEqual([node.tag for node in plans[0]], ['activity', 'leg', 'activity'])
                    entry, leg, exit_activity = list(plans[0])
                    self.assertEqual((entry.get('type'), exit_activity.get('type')),
                                     ('freight_external', 'freight_external'))
                    self.assertNotEqual(entry.get('link'), exit_activity.get('link'))
                    self.assertEqual(leg.get('mode'), 'car')
                    row = contract[person.get('id')]
                    route = leg.find('route')
                    self.assertIsNotNone(route)
                    from simz1_route_xml import validate_link_route
                    path = validate_link_route(route, row['link_ids'], origin=entry.get('link'),
                        destination=exit_activity.get('link'), vehicle_id=person.get('id'))
                    self.assertEqual(path, row['link_ids'])
                    self.assertEqual((entry.get('link'), exit_activity.get('link')), (path[0], path[-1]))
                    self.assertEqual(float(entry.get('end_time')), row['departure_seconds'])
                    self.assertIsNone(exit_activity.get('end_time'))

    def test_generated_native_truck_body_and_saved_version_match_service(self):
        for label, (run, manifest) in self.runs.items():
            with self.subTest(service=label):
                service = read_json(run / 'inputs/freight-weekday/service.json')
                body = ET.parse(run / 'inputs/vehicles.xml').getroot().find(
                    "{*}vehicleType[@id='FreightTruck']")
                self.assertIsNotNone(body)
                for tag, attribute, expected in (('length', 'meter', 12), ('width', 'meter', 2.5),
                                                 ('passengerCarEquivalents', 'pce', 3.5),
                                                 ('maximumVelocity', 'meterPerSecond', 40/3.6)):
                    self.assertAlmostEqual(float(body.find('{*}' + tag).get(attribute)), expected)
                self.assertEqual(service['vehicles'], 4)
                self.assertEqual(service['allowed_windows_seconds'],
                                 read_json(HISTORICAL)['allowed_windows_seconds'])
                if label == 'current':
                    self.assertEqual(service['service_version'], 'weekday-v2')
                    self.assertEqual(service['route_policy'], 'principal-through-v2')
                    self.assertEqual(manifest['freight_transport']['service_version'], 'weekday-v2')
                    self.assertEqual(manifest['freight_transport']['route_policy'], 'principal-through-v2')
                    base_network = CONFIG.parent / parameters(CONFIG)['network.inputNetworkFile']
                    effective_network = run / parameters(run / 'config-simz1.xml')['network.inputNetworkFile']
                    self.assertNotEqual(sha256(base_network), sha256(effective_network),
                                        'The transit fixture must exercise a distinct effective network')

    def test_zero_N_disables_freight_and_keeps_269_public_vehicles(self):
        run = self.root / 'zero'
        manifest = generate_inputs(run, CURRENT, 0)
        self.assertEqual(manifest['status'], 'prepared')
        self.assertEqual(manifest['counts']['non_public_vehicles_configured'], 0)
        self.assertEqual(manifest['counts']['freight_vehicles_configured'], 0)
        self.assertEqual(manifest['counts']['all_vehicles_configured'], 269)
        self.assertFalse(manifest.get('freight_transport', {}).get('enabled'))
        self.assertEqual(verified_contract(run, manifest), {})
        self.assertEqual(population(run / 'plans.xml', allow_empty=True)[0], set())
        public = verified_weekday_fleet(run, manifest, 0)
        self.assertEqual(public['fleet_by_system'], dict(transmetro=176, tubus=93))
        self.assertEqual(len(set(public['fleet_vehicle_ids'])), 269)

    def test_route_signal_audit_is_refreshed_after_coordination_changes_control(self):
        self.coordination_refresh('derive')

    def test_route_signal_audit_is_refreshed_for_activity_coordination_v2(self):
        self.coordination_refresh('derive-activity-v2')

    def coordination_refresh(self, policy):
        run = self.root / ('coordinated-' + policy)
        observed = {}

        def change_offset(config, base_dir, *, write=False, activity_origins=False):
            self.assertTrue(write)
            self.assertEqual(activity_origins, policy == 'derive-activity-v2')
            param = config.find("module[@name='signalsystems']/param[@name='signalcontrol']")
            control = Path(base_dir) / param.get('value')
            observed['before'] = sha256(control)
            tree = ET.parse(control)
            plan = tree.getroot().find('.//{*}signalPlan')
            offset, cycle = plan.find('{*}offset'), int(plan.find('{*}cycleTime').get('sec'))
            offset.set('sec', str((int(offset.get('sec')) + 1) % cycle))
            tree.write(control, encoding='utf-8', xml_declaration=True)
            observed['after'] = sha256(control)
            return dict(enabled=True, policy='derive', test_fixture='offset-change-only')

        with patch('simz1_signal_coordination.coordinate', side_effect=change_offset) as coordinator:
            manifest = generate_inputs(run, CURRENT, 37, short_link_signal_coordination=policy,
                                       whole_vehicle_reservation=True, qsim_threads=1)
        coordinator.assert_called_once()
        self.assertNotEqual(observed['before'], observed['after'])
        report = read_json(run / 'inputs/freight-weekday/route-validation.json')
        self.assertEqual(report['signals']['signal_file_sha256']['signalcontrol'], observed['after'])
        self.assertEqual(sha256(run / 'inputs/signal-control-before-coordination.xml'), observed['before'])
        control = run / parameters(run / 'config-simz1.xml')['signalsystems.signalcontrol']
        self.assertEqual(sha256(control), observed['after'])
        self.assertEqual(len(verified_contract(run, manifest)), 1)


if __name__ == '__main__':
    unittest.main()
