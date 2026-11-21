"""Native XML -> production replay -> published SQLite, without MATSim or mocks."""
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_paged_replay import unpacked
from simz1_run import artifact, sha256
from simz1_sqlite_export import export_sqlite_selected
from simz1_sqlite_source import FILE_NAME, checked_source, load_config
import test_simz1_transit_events as fixtures
from test_simz1_transit_events import event


def native_fixture(directory, *, shared_stop_link=False):
    """Explicit synthetic provenance; includes a bus-only implicit queue.

    Global lanes remain enabled. Only the shared link has a detailed assignment;
    no entered/left-lane event is added to the bus-only link to mask the defect.
    """
    helper = fixtures.TransitEventsTest()
    manifest, _, _ = helper.fixture(directory)
    network = ET.parse(directory/'network.xml').getroot()
    nodes = ET.Element('nodes')
    for ident, x, y in [('a', 768000, 1618000), ('b', 768020, 1618000), ('c', 768020, 1618020)]:
        ET.SubElement(nodes, 'node', id=ident, x=str(x), y=str(y))
    network.insert(0, nodes)
    for link in network.findall('links/link'):
        link.attrib.update(length='20', freespeed='10', permlanes='1', capacity='1800')
        if link.get('id') == 'bc':
            link.set('modes', 'car,bus')
        if link.get('id') == 'ab' and shared_stop_link:
            link.set('modes', 'car,bus')
    ET.ElementTree(network).write(directory/'network.xml')
    with gzip.open(directory/'output/output_network.xml.gz', 'wb') as stream:
        stream.write(ET.tostring(network))

    fleet_path = directory/'vehicles.xml'
    fleet = ET.parse(fleet_path).getroot()
    kind = fleet.find('{*}vehicleType')
    metadata = ET.SubElement(kind, 'attributes')
    ET.SubElement(metadata, 'attribute', name='simz1:dimensionsBasis').text = 'scenario_assumption'
    ET.SubElement(metadata, 'attribute', name='simz1:bodyModel').text = 'rigid'
    for name, attr, value in [('length', 'meter', '12'), ('width', 'meter', '2.5'),
                              ('maximumVelocity', 'meterPerSecond', '12'),
                              ('passengerCarEquivalents', 'pce', '2.5')]:
        ET.SubElement(kind, name, **{attr: value})
    ET.ElementTree(fleet).write(fleet_path)

    schedule = ET.parse(directory/'schedule.xml').getroot()
    stops = ET.Element('transitStops')
    ET.SubElement(stops, 'stopFacility', id='s', linkRefId='ab', x='768010', y='1618000', isBlocking='true')
    schedule.insert(1, stops)
    route = schedule.find("transitLine/transitRoute[@id='out']")
    profile = ET.Element('routeProfile')
    ET.SubElement(profile, 'stop', refId='s', arrivalOffset='00:00:03', departureOffset='00:00:08')
    route.insert(1, profile)
    ET.ElementTree(schedule).write(directory/'schedule.xml')

    # Namespace and leadsTo representation match MATSim lane definitions.
    (directory/'lanes.xml').write_text('''<laneDefinitions xmlns="http://www.matsim.org/files/dtd">
      <lanesToLinkAssignment linkIdRef="bc"><lane id="bc.ol">
        <startsAt meterFromLinkEnd="20"/><leadsTo><toLane refId="bc.end"/></leadsTo>
      </lane><lane id="bc.end"><startsAt meterFromLinkEnd="8"/>
        <leadsTo><toLink refId="ca"/></leadsTo></lane></lanesToLinkAssignment>
      </laneDefinitions>''', encoding='utf-8')
    # Production uses the engine's loaded output artifact, whose path/hash
    # differs from the requested input. It must remain a verified source.
    with gzip.open(directory/'output/output_lanes.xml.gz', 'wb') as stream:
        stream.write((directory/'lanes.xml').read_bytes())
    config = ET.parse(directory/'config-simz1.xml').getroot()
    config.find("module[@name='qsim']/param[@name='useLanes']").set('value', 'true')
    ET.SubElement(config.find("module[@name='network']"), 'param', name='laneDefinitionsFile', value='lanes.xml')
    for path in (directory/'config-simz1.xml', directory/'output/output_config.xml'):
        ET.ElementTree(config).write(path)

    events = [event('departure', 0, person='pt_real_road_person', link='road', legMode='car'),
              event('arrival', 1, person='pt_real_road_person', link='road', legMode='car')]
    for departure, start, path in [('out', 2, ['ab', 'bc']), ('back', 30, ['bc', 'ca', 'ab'])]:
        events.extend([
            event('TransitDriverStarts', start, vehicleId='bus-a', driverId='native-no-prefix',
                  transitLineId='synthetic-service', transitRouteId=departure, departureId=departure+'-bus-a'),
            event('departure', start, person='native-no-prefix', link=path[0], legMode='car'),
            event('vehicle enters traffic', start, vehicle='bus-a', person='native-no-prefix',
                  link=path[0], networkMode='car', relativePosition='0')])
        if departure == 'out':
            events.extend([event('VehicleArrivesAtFacility', start+3, vehicle='bus-a', facility='s'),
                           event('VehicleDepartsAtFacility', start+8, vehicle='bus-a', facility='s')])
        for index, (source, target) in enumerate(zip(path, path[1:]), 1):
            stamp = start + 10*index
            events.extend([event('left link', stamp, vehicle='bus-a', link=source),
                           event('entered link', stamp, vehicle='bus-a', link=target)])
        stamp = start + 10*len(path)
        events.extend([event('vehicle leaves traffic', stamp, vehicle='bus-a', person='native-no-prefix',
                             link=path[-1], networkMode='car', relativePosition='1'),
                       event('arrival', stamp, person='native-no-prefix', link=path[-1], legMode='car')])
    root = ET.Element('events', version='1.0'); root.extend(events)
    with gzip.open(directory/'output/output_events.xml.gz', 'wb') as stream:
        stream.write(ET.tostring(root))

    manifest['inputs'].update({name: artifact(directory, directory/path) for name, path in [
        ('network', 'network.xml'), ('transit_vehicles', 'vehicles.xml'),
        ('transit_schedule', 'schedule.xml'), ('config', 'config-simz1.xml'), ('lanes', 'lanes.xml')]})
    manifest.update(status='completed', validation={'status': 'valid'},
        demand_seed=7, matsim_seed=7, counts={'planned_persons': 1, 'planned_trips': 1},
        time_horizon={'start_seconds': 0, 'end_seconds': 100},
        effective_config=artifact(directory, directory/'output/output_config.xml'),
        effective_lane_configuration_validation={'loaded_artifacts': {
            'lanes': artifact(directory, directory/'output/output_lanes.xml.gz')}})
    manifest['results'] = {'0': dict(
        counts={'planned_persons': 1, 'planned_trips': 1, 'observed_persons': 1, 'observed_departures': 1},
        observed_event_end_seconds=60,
        **{name: artifact(directory, directory/f'output/output_{name}.xml.gz') for name in ('network', 'plans', 'events')})}
    (directory/'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return dict(directory=directory, manifest=manifest, iteration=0,
                **{name: directory/f'output/output_{name}.xml.gz' for name in ('network', 'plans', 'events')})


class TransitSqliteIntegrationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1-native-transit-sqlite-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.selection = native_fixture(self.root)
        self.source = self.root/'webgl-source'
        self.contract = self.source/'sqlite-source'
        self.protected = {path: sha256(path) for path in self.root.rglob('*') if path.is_file()}

    def export(self):
        return export_sqlite_selected(self.selection, self.source/'index.html',
            window_seconds=10, temp_dir=self.root/'scratch', reserve_bytes=0,
            database_budget_bytes=16*1024**2, scratch_budget_bytes=16*1024**2)

    def assert_native_unchanged(self):
        self.assertEqual({path: sha256(path) for path in self.protected}, self.protected)

    def assert_published_stop(self, published):
        _, checked, database = checked_source(self.contract)
        self.assertEqual(published['status'], 'complete')
        self.assertEqual(checked['run_id'], self.selection['manifest']['run_id'])
        self.assertEqual(checked['run_manifest_sha256'], sha256(self.root/'run-manifest.json'))
        self.assertEqual(checked['database_sha256'], sha256(database))
        self.assertEqual(checked['database_validation']['integrity'], 'quick_check+sha256')
        self.assertEqual(checked['counts']['observed_persons'], 1)
        self.assertEqual(checked['counts']['public_transport']['observed_expedition_starts'], 2)
        self.assertFalse(list(self.source.rglob('*.html')))
        with closing(sqlite3.connect(database)) as connection:
            journeys = [(key, json.loads(raw)) for key, raw in connection.execute('SELECT key,metadata FROM journeys')]
            self.assertEqual(len(journeys), 3)  # One private trip plus two public expeditions.
            journeys = [(key, trip) for key, trip in journeys if trip.get('Transit')]
            self.assertEqual(len(journeys), 2)
            first = min(journeys, key=lambda row: row[1]['Departure'])
            trip = first[1]
            stop = trip['Transit']['activity_intervals'][0]
            self.assertEqual((stop['facility_id'], stop['start'], stop['end'], stop['relative_position']), ('s', 5, 10, 1))
            self.assertTrue(stop['position_source'])
            self.assertIsNone(trip['Person_ID'])
            self.assertEqual(trip['Driver_ID'], 'native-no-prefix')
            records = [unpacked(row[0]) for row in connection.execute(
                'SELECT payload FROM segments WHERE journey=? ORDER BY id', (first[0],))]
            dwell = next(row for row in records if row['timestamps'] == [5, 10])
            self.assertEqual(dwell['Distance_m'], 0)
            self.assertEqual(dwell['path'][0], dwell['path'][1])
            self.assertTrue(any(row['timestamps'][0] >= 12 and row['Distance_m'] > 0 for row in records))
        config = load_config(self.contract)
        self.assertTrue(config['lane_replay']['use_lanes'])
        self.assert_native_unchanged()

    def test_gzip_implicit_bus_queue_publishes_real_sqlite_without_missing_lane_event(self):
        # The old implementation fails here with transit_stop_position_unknown.
        published = self.export()
        self.assert_published_stop(published)
        database_hash = sha256(self.source/'replay.sqlite')
        self.assertEqual(self.export(), published)
        self.assertEqual(sha256(self.source/'replay.sqlite'), database_hash)

    def test_shared_link_without_assignment_and_namespaced_detailed_endpoints(self):
        from simz1_motion import load_selected
        self.root = self.root/'shared'
        self.root.mkdir()
        self.source = self.root/'webgl-source'
        self.contract = self.source/'sqlite-source'
        self.selection = native_fixture(self.root, shared_stop_link=True)
        self.protected = {path: sha256(path) for path in self.root.rglob('*') if path.is_file()}
        motion = load_selected(self.selection)
        self.assertIn('ab', motion.transit_contract['single_queue_links'])
        self.assertNotIn('bc', motion.transit_contract['single_queue_links'])
        self.assertEqual(motion.transit_contract['lane_exit_fractions']['bc'], {'bc.ol': .6, 'bc.end': 1})
        self.assert_published_stop(self.export())

    def test_failed_publication_preserves_native_files_and_resumes_finalized_database(self):
        # Real incompatible pending metadata, not mocked extraction or publication.
        self.contract.mkdir(parents=True)
        conflicting = self.contract/'source-config.json'
        conflicting.write_text('{"foreign_fixture":true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Metadatos pendientes incompatibles'):
            self.export()
        self.assertFalse((self.contract/FILE_NAME).exists())
        self.assertTrue((self.source/'spool-ready.json.gz').is_file())
        original_hash = sha256(self.source/'replay.sqlite')
        conflicting.rename(self.contract/'source-config.failed-fixture.json')
        published = self.export()
        self.assertEqual(published['provenance']['kind'], 'finalized-spool-checkpoint')
        self.assertEqual(sha256(self.source/'replay.sqlite'), original_hash)
        self.assert_published_stop(published)

    def test_foreign_stop_lane_hash_remains_rejected(self):
        from copy import deepcopy
        from simz1_recover_paged import check_config
        published = self.export()
        config = load_config(self.contract)
        expected = {k: published[k] for k in ('run_id', 'iteration', 'run_manifest_sha256')}
        config['motion_sources']['transit_stop_lanes'] = deepcopy(config['motion_sources']['transit_stop_lanes'])
        config['motion_sources']['transit_stop_lanes']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'carriles de parada incompatible'):
            check_config(config, expected, self.selection['manifest'], config['pagination']['blocks'])


if __name__ == '__main__':
    unittest.main()
