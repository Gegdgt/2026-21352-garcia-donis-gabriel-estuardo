"""Bounded fixtures for the weekday fleet. Never launches QSim/browser/server."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_weekday_transit import (HISTORICAL_DEFAULT as DEFAULT, load_policy, load_routes, prepared_network,
    build_plan, attach, preflight, verify_policy_chain, seconds, digest, text_fingerprint,
    schedule, validate_serialized_timetable)
from simz1_transit_accounting import planned_transit_counts
from simz1_transit_events import TransitEventAudit, verified_transit_contract, _attributes
from simz1_transit_stops import load_weekday_stops, load_stop_display
from simz1_lane_validation import audit_configuration
from simz1_run import sha256, checked_path, parameters

PROJECT=Path(__file__).resolve().parents[1]
BASE=PROJECT/'scenarios/zona1/network.xml'
CONFIG=PROJECT/'scenarios/zona1/config-simz1.xml'


def resolved_config():
    root=ET.parse(CONFIG).getroot()
    for mod in root.findall('module'):
        for p in mod.findall('param'):
            value=p.get('value')
            if value and (CONFIG.parent/value).is_file():p.set('value',str((CONFIG.parent/value).resolve()))
    return root

class HashCompatibilityTests(unittest.TestCase):
    def test_sha256_streaming_matches_reference_without_file_digest(self):
        # Python 3.10 does not implement hashlib.file_digest. More than one
        # read chunk must be processed without relying on that API.
        payload = b"simz1\x00" * 350000
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test-network.xml"
            path.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            with patch.object(hashlib, 'file_digest', side_effect=AssertionError(
                    'hashlib.file_digest must not be used'), create=True):
                self.assertEqual(digest(path), expected)
                path.write_bytes(payload + b"changed")
                self.assertNotEqual(digest(path), expected)


class CheckoutLineEndingTests(unittest.TestCase):
    def test_network_windows_crlf_hash_is_accepted(self):
        policy, policy_path = load_policy(DEFAULT, '2026-10-23', True)
        expected = json.loads((DEFAULT.parent/'route-bundle.json').read_text())['network_sha256']
        with tempfile.TemporaryDirectory() as folder:
            windows_network = Path(folder)/'network.xml'
            original = BASE.read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(original).hexdigest(), expected)
            windows_network.write_bytes(original.replace(b'\n', b'\r\n'))
            self.assertNotEqual(digest(windows_network), expected)
            self.assertEqual(text_fingerprint(windows_network,expected,'base network'), 'crlf_to_lf')
            routes, _ = load_routes(policy,policy_path,windows_network)
            self.assertEqual(routes['network_sha256'],expected)
            self.assertIsNotNone(prepared_network(windows_network,routes))

            # Any real road change must still be rejected even after CRLF conversion.
            changed = windows_network.read_bytes().replace(b'network name=', b'network version=', 1)
            windows_network.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, 'fingerprint differs beyond'):
                load_routes(policy,policy_path,windows_network)

    def test_bundle_sources_with_windows_checkout_line_endings(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)/'scenarios/zona1'
            paths = ('network.xml', 'map.osm',
                     'transit/weekday-v2/service.json', 'transit/weekday-v2/route-bundle.json',
                     'transit/review-2026-10-22/catalog.json',
                     'transit/review-2026-10-22/municipal-gis.json')
            for name in paths:
                source = PROJECT/'scenarios/zona1'/name
                target = base/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            policy, policy_path = load_policy(base/'transit/weekday-v2/service.json',
                                              '2026-10-23', True)
            bundle, _ = load_routes(policy, policy_path, base/'network.xml')
            self.assertEqual(bundle['network_sha256'],
                             json.loads((DEFAULT.parent/'route-bundle.json').read_text())['network_sha256'])
            # A real mutation in a source is not excused by its line endings.
            source = base/'transit/review-2026-10-22/catalog.json'
            source.write_bytes(source.read_bytes()+b'\r\n')
            with self.assertRaisesRegex(ValueError, 'fingerprint differs beyond'):
                load_routes(policy, policy_path, base/'network.xml')

    def test_source_crlf_only_and_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'source.json'
            contents=b'{\n  "a": 1\n}\n'
            expected=hashlib.sha256(contents).hexdigest()
            p.write_bytes(contents.replace(b'\n',b'\r\n'))
            self.assertEqual(text_fingerprint(p,expected,'source'),'crlf_to_lf')
            p.write_bytes(p.read_bytes().replace(b'1',b'2'))
            with self.assertRaisesRegex(ValueError,'fingerprint differs beyond'):
                text_fingerprint(p,expected,'source')


class WeekdayTransitTests(unittest.TestCase):
    def test_blocking_stop_policy_is_explicit_and_legacy_preserved(self):
        p=deepcopy(self.policy)
        self.assertEqual(p['stop_occupancy_policy'],'blocking_queue_v1')
        current=build_plan(p,self.bundle,self.network,1)
        self.assertTrue(all(s['blocking_lane'] for s in current['stops'] if s['role']!='gateway'))
        p.pop('stop_occupancy_policy')
        legacy=build_plan(p,self.bundle,self.network,1)
        self.assertTrue(any(not s['blocking_lane'] for s in legacy['stops'] if s['role']!='gateway'))

    @classmethod
    def setUpClass(cls):
        cls.policy,cls.pp=load_policy(DEFAULT,'2026-10-23',True)
        cls.bundle,cls.bp=load_routes(cls.policy,cls.pp,BASE)
        cls.network=prepared_network(BASE,cls.bundle)
        cls.plan=build_plan(cls.policy,cls.bundle,cls.network,1)
        cls.temp=tempfile.TemporaryDirectory()
        cls.directory=Path(cls.temp.name)/'space in run';cls.directory.mkdir()
        cls.config=resolved_config()
        cls.output=cls.directory/'inputs/transit-weekday'
        cls.summary=attach(cls.config,cls.output,1,DEFAULT,'2026-10-23',True)
        ET.ElementTree(cls.config).write(cls.directory/'config-simz1.xml')
        cls.schedule=ET.parse(cls.output/'transitSchedule.xml').getroot()
        def artifact(path):return dict(path=path.relative_to(cls.directory).as_posix(),sha256=sha256(path))
        cls.manifest=dict(run_id='fixture',validation={'status':'valid'},counts={'planned_persons':1},
            inputs={name:artifact(cls.output/file) for name,file in [('transit_schedule','transitSchedule.xml'),
                ('transit_vehicles','transitVehicles.xml'),('input:transit-weekday/roster.json','roster.json')]},
            public_transport=planned_transit_counts(cls.directory/'config-simz1.xml',1),
            effective_config=artifact(cls.directory/'config-simz1.xml'),
            results={'0':{'network':artifact(cls.output/'network.xml')}})
        cls.links={x.get('id'):float(x.get('length')) for x in cls.network.findall('./links/link')}
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_explicit_assumptions_gate_and_weekday(self):
        with self.assertRaisesRegex(ValueError,'explicitly'):load_policy(DEFAULT)
        for day in ('2026-10-24','2026-10-25'):
            with self.assertRaisesRegex(ValueError,'Monday-Friday'):load_policy(DEFAULT,day,True)
        self.assertEqual(load_policy(DEFAULT,'2026-10-26',True)[0]['service_date'],'2026-10-26')

    def test_n_independence_and_same_vehicle_ids(self):
        for n in (1,120,250000):
            plan=build_plan(self.policy,self.bundle,self.network,n)
            self.assertEqual(len(plan['vehicles']),120)
            self.assertEqual(plan['vehicles'],self.plan['vehicles'])
            self.assertEqual(plan['roster'],self.plan['roster'])
            self.assertEqual(plan['monte_carlo_persons'],n)
        self.assertEqual(self.policy['fleet_counts'],dict(transmetro=80,tubus=40))

    def test_exact_weekday_windows_and_finite_nonoverlapping_duties(self):
        expected={'transmetro_L1':(18000,72000),'transmetro_L12':(16200,79200),'transmetro_L18':(18000,75600)}
        for service in self.plan['services']:
            window=(service['opens_s'],service['closes_s'])
            self.assertEqual(window,expected.get(service['service_id'],window))
            if service['system']=='tubus':self.assertEqual(window,(19800,68400))
        by_bus={}
        for dep in self.plan['roster']:
            by_bus.setdefault(dep['vehicle_id'],[]).append(dep)
            service=next(x for x in self.plan['services'] if x['service_id']==dep['service_id'])
            self.assertGreaterEqual(dep['departure_time_s'],service['opens_s'])
            self.assertLess(dep['departure_time_s'],service['closes_s'])
            self.assertLessEqual(dep['end_time_s'],service['closes_s'])
        self.assertEqual(len(by_bus),120)
        for deps in by_bus.values():
            self.assertGreater(len(deps),1)
            for a,b in zip(deps,deps[1:]):
                self.assertGreaterEqual(b['departure_time_s']+1e-7,a['end_time_s']+a['transfer_after_seconds'])

    def test_serialized_duties_use_native_overlap_tolerance(self):
        """The old 1e-5 roster tolerance hid 1e-6 violations rejected by Java."""
        by_bus = {}
        for route in self.schedule.findall('./transitLine/transitRoute'):
            final_offset = float(route.findall('./routeProfile/stop')[-1].get('departureOffset'))
            for departure in route.findall('./departures/departure'):
                meta = _attributes(departure)
                start = float(departure.get('departureTime'))
                end = float(meta['simz1:endTimeSeconds'])
                self.assertLessEqual(abs(end - start - final_offset), 1e-7)
                ready = end + float(meta['simz1:terminalSeconds']) + float(meta['simz1:turnaroundSeconds'])
                by_bus.setdefault(departure.get('vehicleRefId'), []).append(
                    (start, ready, departure.get('id')))
        failures = []
        for bus, duties in sorted(by_bus.items()):
            duties.sort()
            for previous, following in zip(duties, duties[1:]):
                if following[0] + 1e-7 < previous[1]:
                    failures.append((bus, previous[2], following[2], previous[1] - following[0]))
        self.assertEqual(failures, [], 'Native timetable rejection: ' + str(failures[:3]))
        self.assertIn('ptbus_transmetro_L12_011', by_bus)
        self.assertEqual(sum(map(len, by_bus.values())), 6915)
        self.assertEqual(len(by_bus), 120)

    def test_serialized_end_is_the_same_as_roster_end(self):
        roster = {d['departure_id']: d for d in self.plan['roster']}
        for departure in self.schedule.findall('./transitLine/transitRoute/departures/departure'):
            duty = roster[departure.get('id')]
            self.assertEqual(float(departure.get('departureTime')), duty['departure_time_s'])
            self.assertEqual(float(_attributes(departure)['simz1:endTimeSeconds']), duty['end_time_s'])

    def test_timetable_generation_is_deterministic_for_multiple_weekdays(self):
        for day in ('2026-10-23', '2026-10-26'):
            policy = {**self.policy, 'service_date': day}
            first = build_plan(policy, self.bundle, self.network, 1000)
            second = build_plan(policy, self.bundle, self.network, 1000)
            self.assertEqual(first['roster'], second['roster'])
            report = validate_serialized_timetable(schedule(first, '0' * 64))
            self.assertEqual(report['checked_departures'], 6915)
            self.assertEqual(report['checked_vehicles'], 120)
            self.assertEqual(report['native_tolerance_seconds'], 1e-7)

    def test_minimum_fractional_transfer_is_never_rounded_down(self):
        bundle = deepcopy(self.bundle)
        for service in bundle['services']:
            for part in service['parts']:
                part['transfer_after']['minimum_seconds'] += 0.0000004
        plan = build_plan(self.policy, bundle, self.network, 1)
        report = validate_serialized_timetable(schedule(plan, '0' * 64))
        self.assertEqual(report['checked_vehicles'], 120)
        previous_by_bus = {}
        for duty in plan['roster']:
            previous = previous_by_bus.get(duty['vehicle_id'])
            if previous is not None:
                self.assertGreaterEqual(duty['departure_time_s'],
                                        previous['end_time_s'] + previous['transfer_after_seconds'])
            previous_by_bus[duty['vehicle_id']] = duty

    def invalid_overlap_plan(self, shortage=0.000001):
        plan = deepcopy(self.plan)
        selected = 'ptbus_transmetro_L12_011_d0056'
        for service in plan['services']:
            for route in service['routes']:
                for departure in route['departures']:
                    if departure['departure_id'] == selected:
                        departure['time_s'] -= shortage
                        return plan
        self.fail('Missing regression departure ' + selected)

    def test_true_overlaps_remain_rejected_at_native_precision(self):
        for shortage in (0.000001, 0.001, 1.0):
            with self.subTest(shortage=shortage):
                with self.assertRaisesRegex(ValueError, 'overlapping duty.*ptbus_transmetro_L12_011'):
                    schedule(self.invalid_overlap_plan(shortage), '0' * 64)

    def test_preflight_rejects_serialized_overlap_before_matsim(self):
        with patch('simz1_weekday_transit.build_plan', return_value=self.invalid_overlap_plan()):
            with self.assertRaisesRegex(ValueError, 'overlapping duty'):
                preflight(CONFIG, DEFAULT, '2026-10-23', True)

    def test_attach_rejects_overlap_without_publishing_partial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'not published'
            with patch('simz1_weekday_transit.build_plan', return_value=self.invalid_overlap_plan()):
                with self.assertRaisesRegex(ValueError, 'overlapping duty'):
                    attach(resolved_config(), destination, 1, DEFAULT, '2026-10-23', True)
            self.assertFalse(destination.exists())

    def test_serialized_end_and_operating_window_tampering_rejected(self):
        root = deepcopy(self.schedule)
        row = root.find('./transitLine/transitRoute/departures/departure')
        end = row.find("./attributes/attribute[@name='simz1:endTimeSeconds']")
        end.text = str(float(end.text) + 0.000001)
        with self.assertRaisesRegex(ValueError, 'endTimeSeconds must equal'):
            validate_serialized_timetable(ET.tostring(root))
        root = deepcopy(self.schedule)
        line = root.find('transitLine')
        first = line.find('./transitRoute/departures/departure')
        line.find("./attributes/attribute[@name='simz1:closesSeconds']").text = first.get('departureTime')
        with self.assertRaisesRegex(ValueError, 'outside operating window'):
            validate_serialized_timetable(ET.tostring(root))

    def test_fleet_sizes_are_metric_not_pcu_multiplication(self):
        types={x['type_id']:x for x in self.plan['vehicle_types']}
        self.assertEqual(types['Transmetro_RigidProxy']['length_m'],13.5)
        self.assertEqual(types['TuBus_RigidProxy']['length_m'],12)
        self.assertEqual(types['Transmetro_RigidProxy']['width_m'],2.5)
        self.assertNotEqual(types['TuBus_RigidProxy']['pcu'],12/4.5)

    def test_car_geometry_capacity_and_sources_unchanged(self):
        original={x.get('id'):x for x in ET.parse(BASE).getroot().findall('./links/link')}
        augmented={x.get('id'):x for x in self.network.findall('./links/link')}
        self.assertEqual(len(original),6183)
        for key,row in original.items():
            self.assertEqual({k:v for k,v in row.attrib.items() if k!='modes'},
                             {k:v for k,v in augmented[key].attrib.items() if k!='modes'})
            self.assertEqual(ET.tostring(row.find('attributes')),ET.tostring(augmented[key].find('attributes')))
        for key in augmented.keys()-original.keys():self.assertEqual(augmented[key].get('modes'),'bus')
        self.assertIn(text_fingerprint(BASE,self.bundle['network_sha256'],'base network'),('exact','crlf_to_lf'))
        self.assertEqual(audit_configuration(self.config)['use_lanes'],True)

    def test_routes_are_connected_source_based_and_not_certified(self):
        links={x.get('id'):x for x in self.network.findall('./links/link')}
        for service in self.bundle['services']:
            for part in service['parts']:
                for a,b in zip(part['link_ids'],part['link_ids'][1:]):self.assertEqual(links[a].get('to'),links[b].get('from'))
                self.assertGreater(part['transfer_after']['minimum_seconds'],0)
                self.assertTrue(part['direction_basis'])
        self.assertFalse(self.bundle['route_geometry_is_empirically_calibrated'])
        self.assertFalse(self.bundle['turn_audit_scope']['all_movements_legal_claim'])
        self.assertEqual(len(self.bundle['direction_assumptions']),4)
        self.assertFalse(any(s['service_id']=='tubus_305' for s in self.plan['services']))

    def test_preflight_same_B_and_does_not_write(self):
        result=preflight(CONFIG,DEFAULT,'2026-10-23',True)
        self.assertEqual(result['configured_buses'],120)
        self.assertEqual(result['timetable_validation'], 'serialized_timetable_pass')
        self.assertEqual(result['timetable_time_basis'], 'integer_microseconds_v1')
        self.assertEqual(result['scheduled_domain_passages'],len(self.plan['roster']))

    def test_attach_manifest_schedule_and_policy_chain(self):
        policy,bundle=verify_policy_chain(self.output/'transitSchedule.xml',_attributes(self.schedule),1)
        self.assertEqual(policy['configured_fleet_size'],120)
        self.assertEqual(bundle['schema_version'],'simz1-transit-route-bundle-v2')
        with self.assertRaisesRegex(ValueError,'N mismatch'):verify_policy_chain(self.output/'transitSchedule.xml',_attributes(self.schedule),2)
        self.assertEqual(self.manifest['public_transport']['road_demand_persons'],1)
        self.assertEqual(self.manifest['public_transport']['fleet_by_system'],dict(transmetro=80,tubus=40))
        contract=verified_transit_contract(self.directory,self.manifest,parameters(self.directory/'config-simz1.xml'),checked_path,{'road1'},self.links)
        self.assertEqual(len(contract['vehicle_modes']),120)
        self.assertEqual(len(contract['departures']),len(self.plan['roster']))

    def test_policy_tampering_rejected_and_no_overwrite(self):
        with self.assertRaisesRegex(ValueError,'output exists'):attach(self.config,self.output,1,DEFAULT,'2026-10-23',True)
        meta=_attributes(self.schedule);meta['simz1:weekdayPolicySha256']='0'*64
        with self.assertRaisesRegex(ValueError,'fingerprint'):verify_policy_chain(self.output/'transitSchedule.xml',meta,1)
        meta['simz1:weekdayPolicyFile']='../../../../../../etc/passwd'
        with self.assertRaises((ValueError,OSError)):verify_policy_chain(self.output/'transitSchedule.xml',meta,1)

    def test_native_stop_signs_exclude_gateways_and_keep_missing_evidence(self):
        ident=dict(run_id='fixture',iteration=0,run_manifest_sha256='f'*64)
        display=load_stop_display(self.directory,self.manifest,ident)
        self.assertTrue(display['available'],display)
        expected=[s for s in self.plan['stops'] if s['role']=='passenger_stop']
        self.assertEqual(len(display['records']),len(expected))
        self.assertEqual({s['services'][0]['system'] for s in display['records']},{'transmetro','tubus'})
        self.assertTrue(any(s['service']=='104' for s in display['pending']))
        self.assertFalse(any(s['services'][0]['service_id']=='tubus_104' for s in display['records']))
        self.assertTrue(all('gateway' not in s['stop_id'] for s in display['records']))

    def test_lane_namespace_stays_compatible_with_native_reader(self):
        data=(self.output/'lanes.xml').read_text()
        self.assertIn('<laneDefinitions ', data)
        self.assertNotIn('<ns0:', data)
        self.assertTrue(ET.fromstring(data).tag.endswith('}laneDefinitions'))

    def test_generator_one_road_person_and_b_fingerprinted(self):
        from generate_montecarlo_z1 import generar
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'tiny source fixture'
            generar(CONFIG,run,20261023,mode='montecarlo',agents=1,corridor_policy='redistribute',
                agent_catalog=PROJECT/'scenarios/zona1/agent-types-car-moto-v1.json',origin_policy='uniform-nodes-v1',
                transit_service=DEFAULT,transit_service_date='2026-10-23',accept_transit_route_assumptions=True)
            m=json.loads((run/'run-manifest.json').read_text())
            self.assertEqual(m['status'],'prepared')
            self.assertEqual(m['counts']['planned_persons'],1)
            self.assertEqual(m['counts']['public_transport_vehicles_configured'],120)
            self.assertEqual(m['counts']['transit_drivers_added_to_demand'],0)
            self.assertIn('input:transit-weekday/weekday-policy.json',m['inputs'])
            for record in m['inputs'].values():checked_path(run,record)
            self.assertEqual(len(ET.parse(run/'plans.xml').getroot().findall('person')),1)
            self.assertFalse((run/'output').exists())

class BoundaryEventTests(unittest.TestCase):
    def setUp(self):
        self.contract=dict(vehicle_modes={'b':'bus'},domain_scope='computational_network',domain_links={'a','z'},
            departures={('line','r','d1'):dict(vehicle='b',links=('a','z'),opens_seconds=100,closes_seconds=500,
                transfer_kind='exterior',transfer_seconds=30),
                ('line','r','d2'):dict(vehicle='b',links=('a','z'),opens_seconds=100,closes_seconds=500,
                transfer_kind='exterior',transfer_seconds=30)})
    def event(self,action,t,ready,dep='d1'):
        return dict(type='simz1TransitBoundary',vehicle='b',driver='driver',service='line',departure=dep,action=action,time=str(t),readyAt=str(ready))
    def test_minimum_off_network_time_and_closing(self):
        audit=TransitEventAudit(self.contract,{'road'})
        audit.consume(self.event('entry',100,100))
        audit.consume(self.event('outside_start',130,160))
        with self.assertRaisesRegex(ValueError,'readiness'):audit.consume(self.event('entry',159,159,'d2'))
        audit.consume(self.event('entry',160,160,'d2'))
        audit.consume(self.event('cancelled_remaining_after_closing',480,510,'d2'))
        with self.assertRaisesRegex(ValueError,'retirement'):audit.consume(self.event('entry',490,490,'d2'))
        self.assertEqual(audit.summary()['road_demand_persons'],1)
        self.assertEqual(audit.summary()['public_transport_vehicles_configured'],1)
    def test_no_event_time_fudging_identity_or_active_relocation(self):
        for event in (self.event('entry',99,99),self.event('entry',500,500),self.event('outside_start',130,131),
                      self.event('made-up',140,140),{**self.event('entry',100,100),'driver':'road'}):
            with self.assertRaises(ValueError):TransitEventAudit(self.contract,{'road'}).consume(event)
        audit=TransitEventAudit(self.contract,{'road'});audit.active.add('b')
        with self.assertRaisesRegex(ValueError,'Active'):audit.consume(self.event('outside_start',130,160))

if __name__=='__main__':unittest.main()
