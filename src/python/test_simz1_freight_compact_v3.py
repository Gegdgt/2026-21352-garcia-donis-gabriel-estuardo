"""Compact freight routing/body regressions; no MATSim process is started."""
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight import prepare, presentation_dimensions, verified_contract
from simz1_freight_multilane import directional_lane_evidence
from simz1_freight_routes import load_context, validate_bundle, link_rejection
from simz1_run import sha256

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'scenarios/zona1'
SERVICE = SCENARIO/'freight/weekday-compact-v3/service-composition-v3.json'


def jsonfile(path):
    return json.loads(path.read_text(encoding='utf-8'))


class LaneEvidenceTests(unittest.TestCase):
    def evidence(self, tags, direction='forward', native=2):
        return directional_lane_evidence(dict(links={'a':dict(way='10', direction=direction, lanes=native)},
                                             ways={'10':dict(tags=tags)}), 'a')

    def test_default_one_lane_is_unknown_not_verified_narrow_road(self):
        row = self.evidence(dict(oneway='yes'), native=1)
        self.assertEqual(row['status'], 'unverified')
        self.assertIsNone(row['directional_lanes'])

    def test_oneway_direction_and_count_are_both_required(self):
        self.assertEqual(self.evidence(dict(lanes='2', oneway='yes'))['status'], 'verified_multilane')
        self.assertEqual(self.evidence(dict(lanes='2', oneway='yes'), 'backward')['status'], 'prohibited')
        self.assertEqual(self.evidence(dict(lanes='2', oneway='-1'), 'backward')['status'], 'verified_multilane')
        self.assertEqual(self.evidence(dict(lanes='1', oneway='yes'), native=1)['status'], 'prohibited')

    def test_bidirectional_total_never_invents_directional_lanes(self):
        for total in ('2', '4', '6'):
            self.assertEqual(self.evidence(dict(lanes=total, oneway='no'))['status'], 'unverified')
        good = {'lanes':'4', 'lanes:forward':'2', 'lanes:backward':'2'}
        self.assertEqual(self.evidence(good)['status'], 'verified_multilane')
        self.assertEqual(self.evidence(dict(good, lanes='3'))['status'], 'unverified')

    def test_reserved_and_conditional_lanes_are_not_freight_space(self):
        self.assertEqual(self.evidence({'lanes':'2','oneway':'yes','lanes:bus':'1'})['status'], 'prohibited')
        reserved = self.evidence({'lanes':'3','oneway':'yes','lanes:bus':'1'}, native=3)
        self.assertEqual(reserved['usable_directional_lanes'], 2)
        self.assertEqual(reserved['status'], 'unverified')
        for extra in ({'lanes:bus:conditional':'1 @ (Mo-Fr 07:00-19:00)'}, {'bus:lanes':'yes|designated'},
                      {'access:lanes':'yes|no'}, {'busway:right':'lane'}):
            self.assertEqual(self.evidence(dict(lanes='2', oneway='yes', **extra))['status'], 'unverified')

    def test_native_graph_cannot_claim_missing_physical_lanes(self):
        self.assertEqual(self.evidence(dict(lanes='2', oneway='yes'), native=1)['status'], 'incompatible')
        self.assertEqual(self.evidence(dict(lanes='2', oneway='yes'), native=3)['status'], 'incompatible')
        self.assertEqual(self.evidence(dict(lanes='1', oneway='yes'), native=3)['status'], 'prohibited')
        self.assertEqual(self.evidence(dict(lanes='2', oneway='yes'), native=2.5)['status'], 'incompatible')


class CompactFreightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = jsonfile(SERVICE)
        cls.bundle = jsonfile(SERVICE.with_name('routes.json'))
        cls.ctx = load_context(SCENARIO/'network.xml', SCENARIO/'lanes.xml', SCENARIO/'map.osm')

    def test_only_body_dimensions_and_declared_version_routing_metadata_change(self):
        old = jsonfile(SCENARIO/'freight/weekday-v2/service-composition-v2.json')
        invariant = ('schema_version','service_date','vehicles','gross_weight_tonnes','pcu','maximum_speed_kmh',
                     'allowed_windows_seconds','residence_policy','departure_slots_seconds',
                     'dispatch_spacing_seconds','clearance_margin_seconds','dispatch_policy','empirical_calibration')
        self.assertEqual({k:old[k] for k in invariant}, {k:self.service[k] for k in invariant})
        self.assertEqual((self.service['length_m'],self.service['width_m']), (8., 2.3))
        self.assertEqual((old['length_m'],old['width_m']), (12, 2.5))
        body = presentation_dimensions(self.service, dict(length_m=12, width_m=2.5))
        self.assertEqual((body['length_m'], body['width_m']), (8., 2.3))
        self.assertGreater(body['length_m'], 4.5)
        with self.assertRaisesRegex(ValueError, 'differs from configured'):
            presentation_dimensions(old, dict(length_m=8, width_m=2.3))

    def test_every_route_link_has_explicit_multilane_direction_and_no_connector_exception(self):
        report = validate_bundle(self.ctx, self.bundle, self.service)
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(len(report['routes']), 4)
        self.assertTrue(all(r['minimum_verified_usable_directional_lanes'] >= 2 for r in report['routes']))
        self.assertTrue(all(r['entry']['side'] != r['exit']['side'] for r in report['routes']))
        # A deliberately lowered source count must invalidate the route even
        # if the native imported count and the route bundle remain unchanged.
        ctx = deepcopy(self.ctx)
        link = self.bundle['routes'][0]['link_ids'][0]
        ctx['ways'][ctx['links'][link]['way']]['tags']['lanes'] = '1'
        with self.assertRaisesRegex(ValueError, 'at most one'):
            validate_bundle(ctx, self.bundle, self.service)

    def test_historical_routes_cannot_silently_pass_the_new_rule(self):
        old = jsonfile(SCENARIO/'freight/weekday-v2/routes.json')
        self.assertTrue(all(any(link_rejection(self.ctx, k, self.service) for k in r['link_ids']) for r in old['routes']))

    def test_exact_truck_quantities_and_allowed_departures_for_massive_runs(self):
        for total, trucks in ((180000, 1800), (220000, 2200)):
            service, bundle, roster = prepare(SCENARIO/'config-simz1.xml', SERVICE, vehicles=trucks)
            self.assertEqual(len(roster), total//100)
            self.assertEqual(set(Counter(r['route_id'] for r in roster).values()), {trucks//4})
            self.assertTrue(all(any(a <= r['departure_seconds'] < b for a,b in service['allowed_windows_seconds']) for r in roster))

    def test_generated_native_vehicle_replay_contract_and_all_269_buses_agree(self):
        from generate_montecarlo_z1 import generar
        from simz1_transit_accounting import verified_weekday_fleet
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            run = Path(folder)/'run'
            generar(SCENARIO/'config-simz1.xml', run, 20261030, agents=400, mode='montecarlo',
                corridor_policy='redistribute', origin_policy='uniform-nodes-v1', destination_policy='lane-length-destinations-v1',
                agent_catalog=SCENARIO/'agent-types-balanced-v1.json', storage_policy='strict-receiver-v1',
                transit_service=SCENARIO/'transit/weekday-v2/service-fleet-176-93-v1.json',
                transit_service_date='2026-10-23', accept_transit_route_assumptions=True,
                freight_service=SERVICE, freight_service_date='2026-10-23')
            manifest = jsonfile(run/'run-manifest.json')
            contract = verified_contract(run, manifest)
            self.assertEqual(len(contract), 4)
            self.assertEqual(manifest['demand_composition']['family_counts'], dict(carro=176,moto=220,pesado=4))
            self.assertEqual(manifest['freight_transport']['source_service_sha256'], sha256(SERVICE))
            native = ET.parse(run/'inputs/vehicles.xml').getroot().find("{*}vehicleType[@id='FreightTruck']")
            self.assertEqual(float(native.find('{*}length').get('meter')), 8.)
            self.assertEqual(float(native.find('{*}width').get('meter')), 2.3)
            self.assertEqual(float(native.find('{*}passengerCarEquivalents').get('pce')), 3.5)
            public = verified_weekday_fleet(run, manifest, 396)
            self.assertEqual(public['fleet_by_system'], dict(transmetro=176, tubus=93))
            self.assertEqual(manifest['counts']['all_vehicles_configured'], 669)


if __name__ == '__main__':
    unittest.main()
