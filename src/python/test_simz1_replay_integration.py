"""Tiny synthetic native-event/SQLite/API fixtures. Never runs MATSim."""
import copy
import json
from pathlib import Path
import tempfile
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from simz1_motion import MotionContext, read_vehicle_definitions
from simz1_trajectories import extract
from simz1_paged_replay import SqliteTrajectorySink, journey_key, unpacked, windows
from simz1_continuous_replay import ContinuousReplay
from simz1_transit_replay import validate_transit_trip


def fixture():
    links = {'a': dict(length=20, freespeed=10, **{'from': [0, 0], 'to': [.00018, 0]}),
             'b': dict(length=20, freespeed=10, **{'from': [.00018, 0], 'to': [0, 0]})}
    motion = MotionContext(vehicle_speeds={'bus': 12}, profiles={'road-person': 'Normal'}, lanes=False)
    motion.vehicle_types = {'bus': 'custom-effective-type'}
    motion.vehicle_dimensions = {'bus': dict(length_m=12, width_m=2.5, source='synthetic-fixture', assumed=True)}
    motion.transit_contract = dict(vehicle_modes={'bus': 'bus'}, departures={
        ('line', 'route', 'd1'): dict(vehicle='bus', links=('a', 'b'), stops=['s'], operator='fixture', service_id='fixture'),
        ('line', 'route', 'd2'): dict(vehicle='bus', links=('b', 'a'), stops=[], operator='fixture', service_id='fixture')},
        domain_links=frozenset(links), domain_scope='synthetic_fixture', facilities={'s': 'a'},
        source=dict(schedule_sha256='a'*64, vehicles_sha256='b'*64))
    def e(kind, time, **kw): return dict(type=kind, time=str(time), **kw)
    events = [e('departure', 0, person='road-person', link='a'), e('arrival', 1, person='road-person', link='a')]
    for departure, time, first, last in [('d1', 2, 'a', 'b'), ('d2', 30, 'b', 'a')]:
        events += [e('TransitDriverStarts', time, vehicleId='bus', driverId='internal-driver',
                     transitLineId='line', transitRouteId='route', departureId=departure),
                   e('departure', time, person='internal-driver', link=first),
                   e('vehicle enters traffic', time, vehicle='bus', person='internal-driver', link=first, relativePosition='0')]
        if departure == 'd1':
            events += [e('VehicleArrivesAtFacility', time+3, vehicle='bus', facility='s'),
                       e('VehicleDepartsAtFacility', time+8, vehicle='bus', facility='s')]
        events += [e('left link', time+10, vehicle='bus', link=first),
                   e('entered link', time+10, vehicle='bus', link=last),
                   e('vehicle leaves traffic', time+15, vehicle='bus', person='internal-driver', link=last, relativePosition='1'),
                   e('arrival', time+15, person='internal-driver', link=last)]
    return links, motion, events


def replay(sink=None, events_override=None):
    links, motion, events = fixture()
    stats = {}
    rows = extract(events_override or events, links, lambda v: True, lambda v: [1, 2, 3],
        SimpleNamespace(inv=lambda *args: (0, 0, 20)), motion=motion, stats=stats, horizon=100, segment_sink=sink)
    return rows, stats


class ReplayIntegrationTest(unittest.TestCase):
    def test_fingerprinted_fleet_loads_without_a_private_vehicle_plan(self):
        from test_simz1_transit_events import TransitEventsTest
        from simz1_motion import load_selected
        from simz1_run import artifact
        import gzip
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory(prefix='simz1-fleet-input-fixture-') as folder:
            directory = Path(folder)
            helper = TransitEventsTest('test_real_output_loop_keeps_N_and_audits_native_bus_movements')
            manifest, _, _ = helper.fixture(directory)
            fleet_path = directory/'vehicles.xml'
            fleet = ET.parse(fleet_path).getroot()
            kind = fleet.find('{*}vehicleType')
            metadata = ET.SubElement(kind, 'attributes')
            ET.SubElement(metadata, 'attribute', name='simz1:dimensionsBasis').text = 'scenario_assumption'
            ET.SubElement(metadata, 'attribute', name='simz1:bodyModel').text = 'rigid'
            for name, attribute, value in [('length','meter','12'), ('width','meter','2.5'),
                                          ('maximumVelocity','meterPerSecond','12'), ('passengerCarEquivalents','pce','2.5')]:
                ET.SubElement(kind, name, **{attribute:value})
            ET.ElementTree(fleet).write(fleet_path)
            network = ET.parse(directory/'network.xml').getroot()
            for link in network.findall('links/link'): link.set('length', '20')
            with gzip.open(directory/'output/output_network.xml.gz', 'wb') as stream: stream.write(ET.tostring(network))
            manifest['inputs']['transit_vehicles'] = artifact(directory, fleet_path)
            manifest['inputs']['config'] = artifact(directory, directory/'config-simz1.xml')
            manifest['effective_config'] = artifact(directory, directory/'output/output_config.xml')
            manifest['results'] = {'0': {'plans': artifact(directory, directory/'output/output_plans.xml.gz')}}
            selection = dict(directory=directory, manifest=manifest, iteration=0,
                plans=directory/'output/output_plans.xml.gz', network=directory/'output/output_network.xml.gz')
            motion = load_selected(selection)
            self.assertNotIn('bus-a', motion.persons)
            self.assertEqual(motion.vehicle_speeds['bus-a'], 12)
            self.assertEqual(motion.vehicle_dimensions['bus-a']['length_m'], 12)
            physical = motion.metadata('internal-driver', 'bus-a')['Vehicle_Physical_Dimensions']
            self.assertEqual((physical['length_m'], physical['width_m']), (12, 2.5))
            self.assertEqual(physical['nature'], 'configured')
            self.assertEqual(physical['provenance']['artifact_source'], 'verified_transit_vehicles')
            self.assertEqual(physical['provenance']['artifact_sha256'], manifest['inputs']['transit_vehicles']['sha256'])
            self.assertEqual(len(motion.transit_contract['departures']), 4)
            fleet_path.write_bytes(fleet_path.read_bytes()+b' ')
            with self.assertRaises((ValueError, RuntimeError)): load_selected(selection)

    def test_native_dispatch_stop_terminal_and_separate_person_count(self):
        rows, stats = replay()
        trips = {row['Trip']['Trip_ID']: row['Trip'] for row in rows}
        self.assertEqual(len(trips), 2)
        first, last = sorted(trips.values(), key=lambda trip: trip['Departure'])
        self.assertEqual(stats['observed_persons'], 1)
        self.assertEqual(stats['observed_departures'], 1)
        self.assertEqual(stats['public_transport']['observed_expedition_starts'], 2)
        self.assertTrue(all(row['Agent_ID'] is None and row['Driver_ID'] == 'internal-driver' for row in rows))
        self.assertEqual(first['Transit']['activity_intervals'][0]['start'], 5)
        self.assertEqual(first['Transit']['activity_intervals'][0]['end'], 10)
        self.assertEqual(first['Transit']['activity_intervals'][-1]['end'], 30)
        self.assertEqual(first['Transit']['terminal_status'], 'between_services')
        self.assertFalse(first['Transit']['service_end_confirmed'])
        self.assertTrue(last['Transit']['service_end_confirmed'])
        self.assertTrue(all(not (row['timestamps'][0] < 30 and row['timestamps'][1] > 17) for row in rows))
        stop = next(row for row in rows if row['timestamps'] == [5, 10])
        self.assertEqual(stop['path'][0], stop['path'][1])
        self.assertEqual(stop['Distance_m'], 0)
        self.assertEqual(stop['Vehicle_Dimensions']['length_m'], 12)
        for trip in trips.values(): validate_transit_trip(trip)

    def test_sqlite_and_full_journey_keep_optional_metadata_and_order(self):
        with tempfile.TemporaryDirectory(prefix='simz1-replay-fixture-') as temporary:
            sink = SqliteTrajectorySink(Path(temporary)/'tiny.sqlite', windows(0, 100, 10))
            try:
                replay(sink)
                values = list(sink.connection.execute('SELECT key,metadata FROM journeys'))
                public = [(key, json.loads(raw)) for key, raw in values if json.loads(raw).get('Transit')]
                self.assertEqual(len(public), 2)
                api = object.__new__(ContinuousReplay)
                api.spatial = None
                api.identity = dict(run_id='synthetic-replay', iteration=0, run_manifest_sha256='c'*64)
                api.manifest = dict(source_export_sha256='d'*64)
                api.source_manifest = dict(source_type='sqlite-direct-v1')
                api.connection = lambda: sqlite3.connect(sink.path.as_uri()+'?mode=ro', uri=True)
                api.native_run = dict(inputs={'transit_schedule': {'sha256': 'a'*64}, 'transit_vehicles': {'sha256': 'b'*64}})
                for key, trip in public:
                    api.validate_spatial_trip(trip)
                    response = api.journey(key)
                    self.assertEqual(response['source_version'], 'd'*64)
                    self.assertEqual(response['trip'], trip)
                    self.assertTrue(all(row['Trip'] == trip for row in response['records']))
                    rows = [unpacked(row[0]) for row in sink.connection.execute('SELECT payload FROM segments WHERE journey=? ORDER BY id', (key,))]
                    self.assertTrue(rows)
                    for row in rows:
                        self.assertEqual(row['Replay_Journey_Key'], key)
                        self.assertEqual(journey_key(dict(row, Trip=trip)), key)
                broken = copy.deepcopy(public[0][1]);broken['Driver_ID'] = 'wrong'
                with self.assertRaises(ValueError): api.validate_spatial_trip(broken)
            finally: sink.close()

    def test_abort_and_censor_never_become_arrivals(self):
        _, _, events = fixture()
        for terminal in [dict(type='vehicle aborts', time='13', vehicle='bus'), None]:
            prefix = [row for row in events if float(row['time']) < 13]
            if terminal: prefix.append(terminal)
            rows, _ = replay(events_override=prefix)
            self.assertTrue(rows)
            self.assertTrue(all(row['Trip']['Arrival'] is None for row in rows))
            self.assertTrue(all(not row['Trip']['Transit']['service_end_confirmed'] for row in rows))

    def test_effective_bus_dimensions_are_not_derived_from_pcu(self):
        xml = '''<vehicleDefinitions><vehicleType id="effective-custom"><attributes>
          <attribute name="simz1:dimensionsBasis">scenario_assumption</attribute>
          <attribute name="simz1:bodyModel">rigid</attribute></attributes>
          <length meter="11.8"/><width meter="2.45"/><networkMode networkMode="bus"/>
          <maximumVelocity meterPerSecond="13"/><passengerCarEquivalents pce="2.3"/>
          </vehicleType><vehicle id="fixed-bus" type="effective-custom"/></vehicleDefinitions>'''
        with tempfile.TemporaryDirectory(prefix='simz1-type-fixture-') as folder:
            path = Path(folder)/'vehicles.xml';path.write_text(xml, encoding='utf-8')
            types, assignments = read_vehicle_definitions(path, transit=True)
            self.assertEqual(assignments['fixed-bus'], 'effective-custom')
            self.assertEqual(types['effective-custom']['dimensions']['length_m'], 11.8)
            self.assertEqual(types['effective-custom']['pcu'], 2.3)
            self.assertTrue(types['effective-custom']['dimensions']['assumed'])
            path.write_text(xml.replace('type="effective-custom"', 'type="unknown"'), encoding='utf-8')
            with self.assertRaises(ValueError): read_vehicle_definitions(path, transit=True)

    def test_internal_lane_stop_needs_native_membership_not_link_end_guess(self):
        links, motion, events = fixture()
        motion.lanes = True
        motion.transit_contract['lane_exit_fractions'] = {'a': {'upstream': .6}}
        events.insert(5, dict(type='entered lane', time='4', vehicle='bus', link='a', lane='upstream'))
        rows = extract(events, links, lambda v: True, lambda v: [1,2,3],
            SimpleNamespace(inv=lambda *args: (0,0,20)), motion=motion, horizon=100)
        stopped = next(row for row in rows if row['timestamps'] == [5,10])
        self.assertEqual(stopped['Boundary_Provenance']['start_relative'], .6)
        self.assertEqual(stopped['Distance_m'], 0)
        links, motion, events = fixture();motion.lanes = True
        with self.assertRaisesRegex(ValueError, 'transit_stop_position_unknown'):
            extract(events, links, lambda v: True, lambda v: [1,2,3], SimpleNamespace(inv=lambda *args: (0,0,20)), motion=motion, horizon=100)

    def test_bus_only_geometry_is_opt_in_and_does_not_connect_car_only_access(self):
        from simz1_visual_lanes import visual_lane_metadata
        import xml.etree.ElementTree as ET
        network = ET.fromstring('''<network><nodes><node id="a" x="0" y="0"/>
          <node id="b" x="0.001" y="0"/><node id="c" x="0.002" y="0"/></nodes><links>
          <link id="bus-in" from="a" to="b" length="100" permlanes="1" modes="bus"/>
          <link id="bus-out" from="b" to="c" length="100" permlanes="1" modes="bus"/>
          <link id="car-out" from="b" to="c" length="100" permlanes="1" modes="car"/>
          </links></network>''')
        identity = dict(run_id='synthetic', iteration=0, run_manifest_sha256='c'*64)
        historic = visual_lane_metadata(network, None, lambda x,y: (x,y), identity)
        future = visual_lane_metadata(network, None, lambda x,y: (x,y), identity, modes=('car','bus'))
        self.assertNotIn('bus-in', historic['links'])
        self.assertEqual(future['links']['bus-in']['allowed_to_links'], ['bus-out'])

    def test_storage_checks_happen_before_any_acl_temporary(self):
        import simz1_recovery_io as io
        with patch.object(io, 'ensure_space', side_effect=OSError('fixture no space')), \
             patch.object(io.tempfile, 'TemporaryFile') as probe:
            with self.assertRaises(OSError): io.preflight_storage(Path.cwd(), probe_write=True)
            probe.assert_not_called()

    def test_http_verifier_cannot_certify_incomplete_local_export(self):
        import verify_simz1_continuous_data as verify
        with tempfile.TemporaryDirectory(prefix='simz1-verifier-fixture-') as folder:
            with patch.object(verify, 'ContinuousReplay', side_effect=ValueError('incomplete')), patch.object(verify, 'fetch') as fetch:
                with self.assertRaisesRegex(ValueError, 'incomplete'): verify.verify(folder, 'http://127.0.0.1:8793')
                fetch.assert_not_called()
            for times in [[], [float('nan')], [float('inf')]]:
                with self.assertRaises(ValueError): verify.verify(folder, times=times, offline=True)


if __name__ == '__main__': unittest.main()
