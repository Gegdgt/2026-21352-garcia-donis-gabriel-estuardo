"""Tiny XML/event/SQLite fixtures; no simulation or historical data modification."""
import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from simz1_motion import load_selected, read_vehicle_definitions
from simz1_paged_replay import SqliteTrajectorySink, unpacked, windows
from simz1_run import sha256
from simz1_trajectories import extract


class PhysicalDimensionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1-dimensions-')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        (self.folder/'config.xml').write_text('<config/>')
        (self.folder/'plans.xml').write_text('''<population><person id="p"><attributes>
          <attribute name="drivingProfile">Normal</attribute>
          <attribute name="vehicles">{"car":"v"}</attribute>
          <attribute name="effectiveVehicleType">not-the-recorded-type</attribute>
          </attributes></person></population>''')

    def vehicles(self, dimensions='<length meter="4.7"/><width meter="1.9"/>', *, attributes='', zipped=False, pcu='3'):
        content = f'''<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd">
          <vehicleType id="recorded-type"><attributes>{attributes}</attributes>{dimensions}
          <maximumVelocity meterPerSecond="13"/><passengerCarEquivalents pce="{pcu}"/>
          </vehicleType><vehicle id="v" type="recorded-type"/></vehicleDefinitions>'''.encode()
        path = self.folder/('vehicles.xml.gz' if zipped else 'vehicles.xml')
        path.write_bytes(gzip.compress(content) if zipped else content)
        return path

    def selection(self, path):
        record = lambda p: dict(path=p.name, sha256=sha256(p))
        return dict(directory=self.folder, plans=self.folder/'plans.xml', iteration=0,
            manifest=dict(effective_config=record(self.folder/'config.xml'), effective_vehicles=record(path),
                          results={'0': dict(plans=record(self.folder/'plans.xml'))}))

    def export(self, context, sink=None):
        links = {'l': dict(length=100, freespeed=10, from_node='a', to_node='b',
            **{'from': [0, 0], 'to': [.001, 0]})}
        events = [dict(type='departure', time='0', person='p', link='l'),
                  dict(type='vehicle enters traffic', time='0', person='p', vehicle='v', link='l', relativePosition='0'),
                  dict(type='vehicle leaves traffic', time='20', person='p', vehicle='v', link='l', relativePosition='1'),
                  dict(type='arrival', time='20', person='p', link='l')]
        return extract(events, links, lambda _: True, lambda _: [1, 2, 3],
            SimpleNamespace(inv=lambda *args: (0, 0, 100)), motion=context, segment_sink=sink, horizon=100)

    def test_standard_legacy_xml_and_gzip_keep_configured_dimensions_with_exact_provenance(self):
        for zipped in (False, True):
            with self.subTest(zipped=zipped):
                path = self.vehicles(zipped=zipped)
                context = load_selected(self.selection(path))
                row = context.metadata('p', 'v')
                self.assertEqual(row['Vehicle_Type'], 'recorded-type')
                self.assertNotIn('Vehicle_Dimensions', row)
                physical = row['Vehicle_Physical_Dimensions']
                self.assertEqual((physical['length_m'], physical['width_m']), (4.7, 1.9))
                self.assertEqual(physical['source'], 'MATSim_VehicleType_XML')
                self.assertEqual(physical['nature'], 'configured')
                self.assertEqual(physical['measurement_status'], 'not_established_by_vehicle_type')
                self.assertIsNone(physical['assumed'])
                self.assertEqual(physical['provenance'], dict(vehicle_type='recorded-type',
                    artifact_source='effective_vehicles', artifact_path=path.name, artifact_sha256=sha256(path)))

    def test_missing_malformed_or_ambiguous_legacy_dimensions_are_not_fabricated(self):
        cases = ['', '<length meter="4.7"/>', '<length meter="4.7"/><width/>',
                 '<length meter="4.7"/><width meter="1.9"/><width meter="2"/>']
        cases += [f'<length meter="{value}"/><width meter="1.9"/>'
                  for value in ('0', '-1', 'nan', 'inf', '-inf', 'bad')]
        for value in cases:
            with self.subTest(dimensions=value):
                path = self.vehicles(value)
                types, assignments = read_vehicle_definitions(path)
                self.assertNotIn('physical_dimensions', types['recorded-type'])
                self.assertEqual(assignments, {'v': 'recorded-type'})
                context = load_selected(self.selection(path))
                rows = self.export(context)
                self.assertTrue(rows)
                self.assertNotIn('Vehicle_Physical_Dimensions', rows[0])

    def test_versioned_visual_dimensions_remain_separate_and_unchanged(self):
        attrs = '''<attribute name="simz1AgentSchema">simz1-road-profiles-v1</attribute>
          <attribute name="simz1DimensionsSource">synthetic fixture</attribute>
          <attribute name="simz1DimensionsAssumed">true</attribute>'''
        path = self.vehicles(attributes=attrs)
        row = load_selected(self.selection(path)).metadata('p', 'v')
        visual, physical = row['Vehicle_Dimensions'], row['Vehicle_Physical_Dimensions']
        self.assertEqual(visual['source'], 'synthetic fixture')
        self.assertTrue(visual['assumed'])
        self.assertTrue(physical['assumed'])
        self.assertEqual(physical['source'], 'MATSim_VehicleType_XML')
        self.assertNotEqual(visual['provenance'], physical['provenance'])

    def test_pcu_and_person_identity_do_not_define_body_dimensions_or_motion(self):
        path = self.vehicles(pcu='.25')
        context = load_selected(self.selection(path))
        first = self.export(context)[0]
        context.vehicle_pcus['v'] = 9
        context.declared_vehicle_types['p'] = 'arbitrary-bus-label'
        second = self.export(context)[0]
        for field in ('Vehicle_Physical_Dimensions', 'Vehicle_Type', 'path', 'timestamps', 'Distance_m', 'Motion_Plan'):
            self.assertEqual(first[field], second[field])
        self.assertEqual(first['Vehicle_Physical_Dimensions']['length_m'], 4.7)
        self.assertEqual(first['Vehicle_PCU'], .25)
        self.assertEqual(second['Vehicle_PCU'], 9)

    def test_payload_and_sqlite_preserve_physical_evidence_without_schema_migration(self):
        path = self.vehicles()
        context = load_selected(self.selection(path))
        expected = context.metadata('p', 'v')['Vehicle_Physical_Dimensions']
        sink = SqliteTrajectorySink(self.folder/'tiny.sqlite', windows(0, 100, 10))
        try:
            self.export(context, sink)
            row = unpacked(sink.connection.execute('SELECT payload FROM segments LIMIT 1').fetchone()[0])
            self.assertEqual(row['Vehicle_Physical_Dimensions'], expected)
            self.assertEqual(json.loads(json.dumps(row))['Vehicle_Physical_Dimensions'], expected)
            self.assertNotIn('Vehicle_Dimensions', row)
        finally:
            sink.close()

    def test_artifact_changed_after_manifest_is_rejected(self):
        path = self.vehicles()
        selection = self.selection(path)
        path.write_bytes(path.read_bytes().replace(b'4.7', b'5.7'))
        with self.assertRaises((ValueError, RuntimeError)):
            load_selected(selection)

    def test_vehicles_of_same_type_share_one_provenance_record(self):
        path = self.vehicles()
        path.write_bytes(path.read_bytes().replace(b'</vehicleDefinitions>',
            b'<vehicle id="second" type="recorded-type"/></vehicleDefinitions>'))
        context = load_selected(self.selection(path))
        self.assertIs(context.vehicle_physical_dimensions['v'], context.vehicle_physical_dimensions['second'])


if __name__ == '__main__':
    unittest.main()
