"""Versioned public fleet regressions; temporary inputs only, no JVM or simulation."""
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from copy import deepcopy
from fractions import Fraction
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_agent_types import load_catalog
from simz1_demand_composition import split, main as preview
from simz1_run import artifact
from simz1_transit_accounting import planned_transit_counts, verified_weekday_fleet
from simz1_weekday_transit import (DEFAULT, HISTORICAL_DEFAULT, load_policy, load_routes,
    prepared_network, plan_with_service_queues, attach, schedule, validate_serialized_timetable)
from simz1_workflow_state import inspect
from test_simz1_weekday_transit import CONFIG, BASE, resolved_config

CATALOG = CONFIG.parent/'agent-types-nonpublic-v1.json'
QUOTAS = dict(transmetro_L1=18, transmetro_L2=11, transmetro_L6=26, transmetro_L7=26,
              transmetro_L12=44, transmetro_L13=22, transmetro_L18=29,
              tubus_104=28, tubus_105=19, tubus_802=28, tubus_R5=18)


def saved_fixture(directory, service_path, private=973):
    """Create actual saved XML/roster evidence using the existing attach mechanism."""
    directory.mkdir()
    config = resolved_config()
    output = directory/'inputs/transit-weekday'
    attach(config, output, private, service_path, '2026-10-23', True)
    ET.ElementTree(config).write(directory/'config-simz1.xml')
    public = planned_transit_counts(directory/'config-simz1.xml', private)
    return dict(public_transport=public, inputs={key: artifact(directory, output/name) for key, name in (
        ('transit_schedule', 'transitSchedule.xml'), ('transit_vehicles', 'transitVehicles.xml'),
        ('input:transit-weekday/roster.json', 'roster.json'))})


class PublicFleetVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.saved = {}
        for name, path in (('current', DEFAULT), ('historical', HISTORICAL_DEFAULT)):
            cls.saved[name] = saved_fixture(cls.root/name, path)

    def test_exact_quotas_largest_remainders_and_unchanged_service_physics(self):
        current, _ = load_policy(DEFAULT, '2026-10-23', True)
        old, _ = load_policy(HISTORICAL_DEFAULT, '2026-10-23', True)
        self.assertEqual(current['fleet_counts'], dict(transmetro=176, tubus=93))
        self.assertEqual(old['fleet_counts'], dict(transmetro=80, tubus=40))
        self.assertEqual({s['service_id']: s['buses'] for s in current['services']}, QUOTAS)
        for system, total in (('transmetro', 176), ('tubus', 93)):
            baseline = {s['service_id']: s['buses'] for s in old['services'] if s['system'] == system}
            exact = {k: Fraction(total * v, sum(baseline.values())) for k, v in baseline.items()}
            rounded = {k: int(v) for k, v in exact.items()}
            order = sorted(exact, key=lambda k: (-(exact[k] - rounded[k]), k))
            for key in order[:total-sum(rounded.values())]:
                rounded[key] += 1
            actual = {s['service_id']: s['buses'] for s in current['services'] if s['system'] == system}
            self.assertEqual(actual, rounded)
            self.assertEqual(sum(actual.values()), total)
        def operational(policy):
            return {k: ([{a: b for a, b in row.items() if a not in ('buses', 'allocation_basis')}
                         for row in value] if k == 'services' else value)
                    for k, value in policy.items() if k not in
                    ('scenario_version', 'fleet_counts', 'fleet_allocation', 'assumptions')}
        self.assertEqual(operational(current), operational(old))
        self.assertFalse(current['fleet_allocation']['empirical_calibration'])
        self.assertEqual(current['fleet_allocation']['tie_break'], 'service_id_ascending')

    def test_zero_and_1000_keep_same_unique_fleet_and_nonoverlapping_duties(self):
        policy, path = load_policy(DEFAULT, '2026-10-23', True)
        bundle, _ = load_routes(policy, path, BASE)
        previous = None
        for total in (0, 1000):
            with self.subTest(N=total):
                mix = split(total, load_catalog(CATALOG))
                plan, _ = plan_with_service_queues(policy, bundle, prepared_network(BASE, bundle),
                                                  mix['private_vehicles'], resolved_config(), BASE.parent)
                self.assertEqual(plan['monte_carlo_persons'], 0 if total == 0 else 973)
                self.assertEqual(mix['family_counts'], dict(carro=0, moto=0, pesado=0) if total == 0
                                 else dict(carro=432, moto=541, pesado=27))
                ids = [v['vehicle_id'] for v in plan['vehicles']]
                self.assertEqual(len(ids), 269)
                self.assertEqual(len(set(ids)), 269)
                self.assertEqual(total + len(ids), 269 if total == 0 else 1269)
                self.assertEqual(Counter({s['service_id']: len(s['vehicle_ids']) for s in plan['services']}), QUOTAS)
                by_bus = defaultdict(list)
                for row in plan['roster']:
                    by_bus[row['vehicle_id']].append(row)
                self.assertEqual(set(by_bus), set(ids))
                for duties in by_bus.values():
                    self.assertEqual(len({d['service_id'] for d in duties}), 1)
                    for row in duties:
                        self.assertLess(row['departure_time_s'], row['closes_s'])
                        self.assertLessEqual(row['end_time_s'], row['closes_s'])
                    for before, after in zip(duties, duties[1:]):
                        self.assertGreaterEqual(after['departure_time_s'] + 1e-7,
                                                before['end_time_s'] + before['transfer_after_seconds'])
                report = validate_serialized_timetable(schedule(plan, '0' * 64))
                self.assertEqual(report['checked_vehicles'], 269)
                if previous is not None:
                    self.assertEqual(plan['vehicles'], previous['vehicles'])
                    self.assertEqual(plan['roster'], previous['roster'])
                previous = plan

    def test_saved_current_and_explicit_historical_fleets(self):
        for name, counts in (('current', dict(transmetro=176, tubus=93)),
                             ('historical', dict(transmetro=80, tubus=40))):
            with self.subTest(service=name):
                saved = verified_weekday_fleet(self.root/name, self.saved[name], 973)
                self.assertEqual(saved['fleet_by_system'], counts)
                self.assertEqual(saved['public_transport_vehicles_configured'], sum(counts.values()))

    def test_preview_uses_new_service_and_explicit_historical_override(self):
        for total, path, counts in ((0, DEFAULT, dict(transmetro=176, tubus=93)),
                                    (1000, DEFAULT, dict(transmetro=176, tubus=93)),
                                    (1000, HISTORICAL_DEFAULT, dict(transmetro=80, tubus=40))):
            stream = io.StringIO()
            args = ['--agents', str(total)]
            if path == HISTORICAL_DEFAULT:
                args += ['--transit-service', str(path)]
            with redirect_stdout(stream):
                self.assertEqual(preview(args), 0)
            result = json.loads(stream.getvalue())
            self.assertEqual(result['public_fleet_configured'], counts)
            self.assertEqual(result['all_vehicles_configured'], total + sum(counts.values()))

    def test_generated_composition_manifest_xml_and_roster_agree(self):
        from generate_montecarlo_z1 import generar
        for total in (0, 1000):
            with self.subTest(N=total), tempfile.TemporaryDirectory() as td:
                run = Path(td)/'new-run'
                generar(CONFIG, run, 20261029, agents=total, mode='montecarlo',
                        corridor_policy='redistribute', origin_policy='uniform-nodes-v1',
                        agent_catalog=CATALOG, storage_policy='strict-receiver-v1',
                        transit_service=DEFAULT, transit_service_date='2026-10-23',
                        accept_transit_route_assumptions=True,
                        freight_service=CONFIG.parent/'freight/weekday-v1/service-composition-v1.json',
                        freight_service_date='2026-10-23')
                manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
                private = 0 if total == 0 else 973
                self.assertEqual(manifest['counts']['planned_persons'], private)
                self.assertEqual(manifest['counts']['freight_vehicles_configured'], 0 if total == 0 else 27)
                self.assertEqual(manifest['counts']['all_vehicles_configured'], total + 269)
                self.assertEqual(manifest['population_generation']['verified']['vehicles'], private)
                saved = verified_weekday_fleet(run, manifest, private)
                self.assertEqual(saved['fleet_by_system'], dict(transmetro=176, tubus=93))
                self.assertEqual(len(saved['fleet_vehicle_ids']), 269)

    def test_saved_declared_generated_roster_and_manifest_discrepancies_rejected(self):
        for mutation in ('declared', 'generated', 'roster', 'manifest'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                run = Path(td)/'run'
                shutil.copytree(self.root/'current', run)
                manifest = deepcopy(self.saved['current'])
                output = run/'inputs/transit-weekday'
                if mutation == 'declared':
                    policy_path = output/'weekday-policy.json'
                    policy = json.loads(policy_path.read_text(encoding='utf-8'))
                    policy['fleet_counts']['transmetro'] = 175
                    policy_path.write_text(json.dumps(policy), encoding='utf-8')
                    # Repin to exercise semantic consistency, not just hash rejection.
                    from simz1_weekday_transit import digest
                    tree = ET.parse(output/'transitSchedule.xml')
                    tree.find("./attributes/attribute[@name='simz1:weekdayPolicySha256']").text = digest(policy_path)
                    tree.write(output/'transitSchedule.xml')
                    manifest['inputs']['transit_schedule'] = artifact(run, output/'transitSchedule.xml')
                elif mutation == 'generated':
                    tree = ET.parse(output/'transitVehicles.xml')
                    tree.getroot().remove(tree.find('{*}vehicle'))
                    tree.write(output/'transitVehicles.xml')
                    manifest['inputs']['transit_vehicles'] = artifact(run, output/'transitVehicles.xml')
                elif mutation == 'roster':
                    roster = json.loads((output/'roster.json').read_text(encoding='utf-8'))
                    roster[0]['vehicle_id'] = 'unknown_bus'
                    (output/'roster.json').write_text(json.dumps(roster), encoding='utf-8')
                    manifest['inputs']['input:transit-weekday/roster.json'] = artifact(run, output/'roster.json')
                else:
                    manifest['public_transport']['fleet_by_system'] = dict(transmetro=175, tubus=94)
                with self.assertRaises(ValueError):
                    verified_weekday_fleet(run, manifest, 973)

    def test_acceptance_uses_saved_service_and_requires_every_distinct_bus_in_traffic(self):
        for name, total in (('current', 269), ('historical', 120)):
            with self.subTest(service=name), tempfile.TemporaryDirectory() as td:
                run = Path(td)/'run'
                shutil.copytree(self.root/name, run)
                manifest = deepcopy(self.saved[name])
                catalog = run/'catalog.json'; catalog.write_bytes(CATALOG.read_bytes())
                ids = manifest['public_transport']['fleet_vehicle_ids']
                observed = dict(road_demand_persons=973, public_transport_vehicles_configured=total,
                    transit_drivers_added_to_demand=0, transit_drivers_internal_observed=total,
                    observed_expedition_starts=total, public_transport_vehicle_ids_observed=ids,
                    public_transport_vehicle_ids_in_traffic=ids, peak_active_public_vehicles_network=1,
                    active_public_vehicles_network=0, trips=dict(completed_trips=total, aborted_before_horizon=0))
                manifest.update(status='completed', validation=dict(status='valid'), folder=str(run.resolve()),
                    run_id='synthetic-fleet-acceptance', iterations=dict(last=0), results={'0': dict(public_transport_events=observed)},
                    demand_composition=split(1000, load_catalog(CATALOG)),
                    agent_configuration=dict(catalog_artifact=artifact(run, catalog)),
                    counts=dict(planned_persons=973, freight_vehicles_configured=27, non_public_vehicles_configured=1000,
                                public_transport_vehicles_configured=total, all_vehicles_configured=1000+total))
                quality = run/'analysis/it.0/graficas_perfiles/calidad_resultados.json'
                quality.parent.mkdir(parents=True)
                quality.write_text(json.dumps(dict(run_id=manifest['run_id'], iteration=0, status='screening_pass')))
                manifest_path = run/'run-manifest.json'
                manifest_path.write_text(json.dumps(manifest))
                # No current default is consulted when validating an old snapshot.
                with patch('simz1_weekday_transit.load_policy', side_effect=AssertionError('live configuration read')):
                    self.assertEqual(inspect(run, 1000)['acceptance_vehicles'], 1000)
                # A historical summary without IDs must supply pinned native events.
                legacy = deepcopy(manifest)
                legacy_public = legacy['results']['0']['public_transport_events']
                del legacy_public['public_transport_vehicle_ids_observed']
                del legacy_public['public_transport_vehicle_ids_in_traffic']
                events = ET.Element('events')
                for ident in ids:
                    ET.SubElement(events, 'event', type='TransitDriverStarts', vehicleId=ident)
                    ET.SubElement(events, 'event', type='vehicle enters traffic', vehicle=ident)
                events_path = run/'events.xml'
                ET.ElementTree(events).write(events_path)
                legacy['results']['0']['events'] = artifact(run, events_path)
                manifest_path.write_text(json.dumps(legacy))
                self.assertEqual(inspect(run, 1000)['acceptance_vehicles'], 1000)
                events.remove(events[-1])
                ET.ElementTree(events).write(events_path)
                legacy['results']['0']['events'] = artifact(run, events_path)
                manifest_path.write_text(json.dumps(legacy))
                with self.assertRaisesRegex(ValueError, 'all buses must circulate'):
                    inspect(run, 1000)
                for field in ('public_transport_vehicles_configured', 'transit_drivers_internal_observed',
                              'observed_expedition_starts', 'public_transport_vehicle_ids_observed',
                              'public_transport_vehicle_ids_in_traffic'):
                    bad = deepcopy(manifest)
                    bad['results']['0']['public_transport_events'][field] = (
                        ids[:-1] if field.startswith('public_transport_vehicle_ids') else total-1)
                    manifest_path.write_text(json.dumps(bad))
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        inspect(run, 1000)


if __name__ == '__main__':
    unittest.main()
