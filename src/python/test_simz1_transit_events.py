"""Prepared synthetic event fixtures; no generator, native runtime or simulation."""
from contextlib import ExitStack
import copy
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_event_validation import MovementAudit
from simz1_run import artifact, checked_path, validate_outputs
from simz1_transit_events import TransitEventAudit, verified_transit_contract


def event(kind, time, **values):
    return ET.Element('event', type=kind, time=str(time), **values)


def attrs(parent, values):
    group = ET.SubElement(parent, 'attributes')
    for key, value in values.items():
        ET.SubElement(group, 'attribute', name='simz1:'+key).text = str(value)


class TransitEventsTest(unittest.TestCase):
    def test_event_cost_does_not_copy_demand_or_scan_unchanged_fleet(self):
        class NoUnion(frozenset):
            def __or__(self, other):
                raise AssertionError('Per-event union copies all N identities')

        class CountedActive(set):
            scans = 0
            def __iter__(self):
                self.scans += 1
                return super().__iter__()

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            audit = TransitEventAudit(contract, {'pt_real_road_person'}, {'freight-person'})
            audit.road_ids = NoUnion(audit.road_ids)
            audit.active = CountedActive()
            for item in self.events()[:5]:
                audit.consume(item)
            scans = audit.active.scans
            for _ in range(100):
                self.assertTrue(audit.consume(event('simz1OccupancyProgress', 2, vehicle='bus-a', link='ab')))
            self.assertEqual(audit.active.scans, scans, 'Unchanged fleet scanned on every diagnostic event')
            for item in self.events()[5:]:
                audit.consume(item)
            report = audit.summary()
            self.assertEqual(report['observed_expedition_starts'], 2)
            self.assertEqual(report['peak_active_public_vehicles_network'], 1)
            self.assertEqual(report['peak_public_vehicles_on_known_domain_links'], 1)
            self.assertEqual(report['active_public_vehicles_network'], 0)
            self.assertEqual(report['event_counts']['simz1OccupancyProgress'], 100)
            self.assertFalse(audit.consume(event('departure', 20, person='freight-person', link='road')))
            bad = self.events()[2]
            bad.set('driverId', 'freight-person')
            with self.assertRaisesRegex(ValueError, 'colliding'):
                audit.consume(bad)
            with self.assertRaisesRegex(ValueError, 'persona ajena'):
                audit.consume(event('departure', 20, person='unknown', link='road'))

    def fixture(self, directory):
        links = {'ab': ('a', 'b', {'bus'}), 'bc': ('b', 'c', {'bus'}),
                 'ca': ('c', 'a', {'bus'}), 'road': ('a', 'b', {'car'})}
        network = ET.Element('network')
        group = ET.SubElement(network, 'links')
        for name, (source, target, modes) in links.items():
            ET.SubElement(group, 'link', {'id': name, 'from': source, 'to': target, 'modes': ','.join(modes)})
        plans = ET.fromstring('<population><person id="pt_real_road_person"><plan selected="yes">'
                             '<activity type="home" link="road"/><leg mode="car"/>'
                             '<activity type="work" link="road"/></plan></person></population>')
        schedule = ET.Element('transitSchedule')
        attrs(schedule, {'fleetSchema': 'fixed-fleet-v1', 'passengersModeled': 'false',
                         'monteCarloPersons': '1', 'configuredFleetSize': '2', 'scheduledExpeditions': '4',
                         'purpose': 'synthetic_fixture', 'domainSynthetic': 'true', 'domainApproved': 'false',
                         'domainLinks': 'ab bc ca', 'domainSource': 'explicit synthetic fixture, not Zona 1'})
        line = ET.SubElement(schedule, 'transitLine', id='synthetic-service')
        for direction, path in [('out', ['ab', 'bc']), ('back', ['bc', 'ca', 'ab'])]:
            route = ET.SubElement(line, 'transitRoute', id=direction)
            attrs(route, {'routePolicy': 'fixed-v1'})
            path_node = ET.SubElement(route, 'route')
            for link in path:
                ET.SubElement(path_node, 'link', refId=link)
            departures = ET.SubElement(route, 'departures')
            for bus in ('bus-a', 'bus-b'):
                ET.SubElement(departures, 'departure', id=direction+'-'+bus, vehicleRefId=bus,
                              departureTime=str((2 if direction=='out' else 10)+(20 if bus=='bus-b' else 0)))
        vehicles = ET.Element('vehicleDefinitions', xmlns='http://www.matsim.org/files/dtd')
        kind = ET.SubElement(vehicles, 'vehicleType', id='synthetic-bus')
        ET.SubElement(kind, 'networkMode', networkMode='bus')
        for bus in ('bus-a', 'bus-b'):
            ET.SubElement(vehicles, 'vehicle', id=bus, type='synthetic-bus')
        config = ET.Element('config')
        params = {'transit.useTransit': 'true', 'transit.transitScheduleFile': 'schedule.xml',
                  'transit.vehiclesFile': 'vehicles.xml', 'network.inputNetworkFile': 'network.xml',
                  'plans.inputPlansFile': 'plans.xml', 'qsim.startTime': '0', 'qsim.endTime': '100',
                  'qsim.useLanes': 'false', 'signalsystems.useSignalsystems': 'false'}
        modules = {}
        for name, value in params.items():
            module, key = name.split('.', 1)
            if module not in modules:
                modules[module] = ET.SubElement(config, 'module', name=module)
            ET.SubElement(modules[module], 'param', name=key, value=value)
        for name, root in [('network.xml', network), ('plans.xml', plans), ('schedule.xml', schedule),
                           ('vehicles.xml', vehicles), ('config-simz1.xml', config)]:
            ET.ElementTree(root).write(directory/name)
        manifest = dict(run_id='synthetic-event-fixture', inputs={key: artifact(directory, directory/name)
            for key, name in [('network', 'network.xml'), ('plans', 'plans.xml'),
                              ('transit_schedule', 'schedule.xml'), ('transit_vehicles', 'vehicles.xml')]},
            iterations={'first': 0, 'last': 0}, configuration_overrides=[],
            public_transport=dict(enabled=True, road_demand_persons=1, fleet_vehicle_ids=['bus-a', 'bus-b'],
                                  public_transport_vehicles_configured=2, public_transport_departures_scheduled=4))
        output = directory/'output'
        output.mkdir()
        for name, root in [('network', network), ('plans', plans)]:
            with gzip.open(output/f'output_{name}.xml.gz', 'wb') as stream:
                stream.write(ET.tostring(root))
        ET.ElementTree(config).write(output/'output_config.xml')
        (output/'stopwatch.txt').write_text('Iteration\tEND iteration\n0\t00:00:01\n')
        return manifest, params, links

    def events(self):
        result = [event('departure', 0, person='pt_real_road_person', link='road', legMode='car'),
                  event('arrival', 1, person='pt_real_road_person', link='road', legMode='car')]
        for direction, start, path in [('out', 2, ['ab', 'bc']), ('back', 10, ['bc', 'ca', 'ab'])]:
            result += [event('TransitDriverStarts', start, driverId='native-no-prefix', vehicleId='bus-a',
                             transitLineId='synthetic-service', transitRouteId=direction, departureId=direction+'-bus-a'),
                       event('departure', start, person='native-no-prefix', link=path[0], legMode='car'),
                       event('vehicle enters traffic', start, person='native-no-prefix', vehicle='bus-a',
                             link=path[0], networkMode='car')]
            for index, (source, target) in enumerate(zip(path, path[1:]), 1):
                result += [event('left link', start+index, vehicle='bus-a', link=source),
                           event('entered link', start+index, vehicle='bus-a', link=target)]
            result += [event('vehicle leaves traffic', start+len(path), person='native-no-prefix',
                             vehicle='bus-a', link=path[-1]),
                       event('arrival', start+len(path), person='native-no-prefix', link=path[-1], legMode='car')]
        return result

    def validate(self, directory, manifest, events):
        root = ET.Element('events')
        root.extend(events)
        with gzip.open(directory/'output/output_events.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(root))
        baseline = dict(use_lanes=False, signals_enabled=False, baseline_parameters={},
                        signatures={'network': 'fixture', 'lanes': None, 'signals': None})
        # Isolate the real event loop from unrelated scenario/import validations.
        # Hashes, population IDs, raw chronology, modes and movement audit stay real.
        with ExitStack() as stack:
            stack.enter_context(patch('simz1_run.validate_configuration', return_value={'admission_policy':'matsim15-native'}))
            stack.enter_context(patch('simz1_run.audit_configuration', side_effect=lambda *a, **k: copy.deepcopy(baseline)))
            stack.enter_context(patch('simz1_gateway_od.validated_spatial_demand', return_value=None))
            stack.enter_context(patch('simz1_signal_replay.selected_groups', return_value=[]))
            validate_outputs(directory, manifest)

    def test_real_output_loop_keeps_N_and_audits_native_bus_movements(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, _, _ = self.fixture(directory)
            raw = self.events()
            self.validate(directory, manifest, raw)
            result = manifest['results']['0']
            self.assertEqual(result['counts']['planned_persons'], 1)
            self.assertEqual(result['counts']['observed_departures'], 1)
            self.assertEqual(result['counts']['observed_persons'], 1)
            self.assertEqual(result['counts']['physical_transitions'], 3)
            public = result['public_transport_events']
            self.assertEqual(public['public_transport_vehicles_configured'], 2)
            self.assertEqual(public['public_transport_departures_scheduled'], 4)
            self.assertEqual(public['observed_expedition_starts'], 2)
            self.assertEqual(public['transit_drivers_internal_observed'], 1)
            self.assertEqual(public['public_transport_vehicle_ids_observed'], ['bus-a'])
            self.assertEqual(public['public_transport_vehicle_ids_in_traffic'], ['bus-a'])
            self.assertEqual(public['trips']['departures'], 2)
            self.assertEqual(public['active_public_vehicles_inside_domain'], 0)
            self.assertTrue(all(e.get('networkMode') == 'car' for e in raw if e.get('type') == 'vehicle enters traffic'))

    def test_output_loop_still_rejects_backdated_or_unknown_actor_events(self):
        for extra, reason in [(event('arrival', 1, person='native-no-prefix', link='ab'), 'Tiempos invalidos'),
                              (event('departure', 20, person='pt_unknown_actor', link='road'), 'persona ajena')]:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                manifest, _, _ = self.fixture(directory)
                with self.assertRaisesRegex(ValueError, reason):
                    self.validate(directory, manifest, self.events()+[extra])

    def test_bus_mode_authority_preserves_forbidden_and_disconnected_checks(self):
        links = {'ab': ('a', 'b', {'bus'}), 'bc': ('b', 'c', {'bus'}),
                 'road': ('b', 'c', {'car'}), 'disconnected': ('z', 'y', {'bus'})}
        for target, reason in [('road', 'bus'), ('disconnected', 'toNode')]:
            audit = MovementAudit(links, registered_vehicle_modes={'registered-bus': 'bus'})
            raw = event('vehicle enters traffic', 0, vehicle='registered-bus', link='ab', networkMode='car')
            audit.consume(raw)
            audit.consume(event('left link', 1, vehicle='registered-bus', link='ab'))
            with self.assertRaisesRegex(ValueError, reason):
                audit.consume(event('entered link', 1, vehicle='registered-bus', link=target))
            self.assertEqual(raw.get('networkMode'), 'car')
        with self.assertRaisesRegex(ValueError, 'car'):
            MovementAudit(links).consume(event('vehicle enters traffic', 0, vehicle='pt_not_registered', link='ab'))

    def test_inputs_require_named_fingerprints_and_exact_roster(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            audit = TransitEventAudit(contract, {'pt_real_road_person'})
            wrong = self.events()[2]
            wrong.set('vehicleId', 'bus-b')
            with self.assertRaisesRegex(ValueError, 'assignment'):
                audit.consume(wrong)
            del manifest['inputs']['transit_vehicles']
            with self.assertRaisesRegex(ValueError, 'fingerprinted'):
                verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)

    def test_scheduled_times_are_exact_and_missing_is_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            manifest,params,links=self.fixture(directory)
            contract=verified_transit_contract(directory,manifest,params,checked_path,{'pt_real_road_person'},links)
            self.assertEqual(sorted(row['scheduled_departure'] for row in contract['departures'].values()),[2,10,22,30])
            path=directory/'schedule.xml'
            tree=ET.parse(path);departure=tree.find('.//departure')
            for value in (None,'nan','inf','-1'):
                if value is None:departure.attrib.pop('departureTime',None)
                else:departure.set('departureTime',value)
                tree.write(path)
                manifest['inputs']['transit_schedule']=artifact(directory,path)
                with self.assertRaisesRegex(ValueError,'scheduled departure time'):
                    verified_transit_contract(directory,manifest,params,checked_path,{'pt_real_road_person'},links)

    def test_duplicate_dispatch_and_demand_driver_collision_are_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            audit = TransitEventAudit(contract, {'pt_real_road_person'})
            start = self.events()[2]
            audit.consume(start)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                audit.consume(start)
            start.set('driverId', 'pt_real_road_person')
            with self.assertRaisesRegex(ValueError, 'colliding'):
                TransitEventAudit(contract, {'pt_real_road_person'}).consume(start)

    def test_fixed_route_rejects_a_topologically_valid_deviation(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            # The explicit fixture domain has another allowed street, but this
            # scheduled route does not include it. Nearness/connectivity is not a detour policy.
            links['bd'] = ('b', 'd', {'bus'})
            contract['domain_links'] = contract['domain_links'] | {'bd'}
            transit = TransitEventAudit(contract, {'pt_real_road_person'})
            movement = MovementAudit(links, registered_vehicle_modes=contract['vehicle_modes'])
            for item in self.events()[2:6]:
                transit.consume(item)
                movement.consume(item)
            deviation = event('entered link', 3, vehicle='bus-a', link='bd')
            movement.consume(deviation)  # It is connected and mode-permitted.
            with self.assertRaisesRegex(ValueError, 'fixed route sequence'):
                transit.consume(deviation)

    def test_bus_cannot_leave_explicit_domain_or_input_route_cross_it(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            audit = TransitEventAudit(contract, {'pt_real_road_person'})
            for item in self.events()[2:6]:
                audit.consume(item)
            with self.assertRaisesRegex(ValueError, 'outside its explicit domain'):
                audit.consume(event('entered link', 3, vehicle='bus-a', link='outside'))
            schedule = ET.parse(directory/'schedule.xml')
            schedule.find("attributes/attribute[@name='simz1:domainLinks']").text = 'ab bc'
            schedule.write(directory/'schedule.xml')
            manifest['inputs']['transit_schedule'] = artifact(directory, directory/'schedule.xml')
            with self.assertRaisesRegex(ValueError, 'route leaves its explicit domain'):
                verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)

    def test_abort_ends_activity_without_inventing_arrival(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            contract = verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            audit = TransitEventAudit(contract, {'pt_real_road_person'})
            for item in self.events()[2:5]:
                audit.consume(item)
            audit.consume(event('vehicle aborts', 100, vehicle='bus-a', link='ab'))
            summary = audit.summary()
            self.assertEqual(summary['active_public_vehicles_network'], 0)
            self.assertEqual(summary['event_counts']['vehicle aborts'], 1)
            self.assertNotIn('arrival', summary['event_counts'])

    def test_departure_ids_are_globally_unique_and_hash_changes_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest, params, links = self.fixture(directory)
            schedule = ET.parse(directory/'schedule.xml')
            departures = schedule.findall('.//departure')
            departures[-1].set('id', departures[0].get('id'))
            schedule.write(directory/'schedule.xml')
            with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
                verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)
            manifest['inputs']['transit_schedule'] = artifact(directory, directory/'schedule.xml')
            with self.assertRaisesRegex(ValueError, 'duplicate departure'):
                verified_transit_contract(directory, manifest, params, checked_path, {'pt_real_road_person'}, links)


if __name__ == '__main__':
    unittest.main()
