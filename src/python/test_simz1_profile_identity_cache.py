"""Identity/cache fixtures only: no simulator and no historical run mutations."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from procesar_eventos_z1 import read_person_metadata, read_profiles, metadata_for_selection
from simz1_road_catalog import IDENTITIES, SCHEMA
from simz1_run import artifact, sha256
from simz1_trip_table import export_table, rows, write_events, DEFINITION


class ProfileIdentityCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1 identity cache ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()

    def plans(self, people, *, compressed=False):
        root = ET.Element('population')
        for ident, attrs, modes in people:
            person = ET.SubElement(root, 'person', id=ident)
            attributes = ET.SubElement(person, 'attributes')
            for name, value in attrs.items():
                ET.SubElement(attributes, 'attribute', name=name).text = value
            plan = ET.SubElement(person, 'plan', selected='yes')
            for mode in modes:
                ET.SubElement(plan, 'leg', mode=mode)
        path = self.directory / ('plans.xml.gz' if compressed else 'plans.xml')
        data = ET.tostring(root)
        path.write_bytes(gzip.compress(data) if compressed else data)
        return path

    def selection(self):
        plans = self.plans([('person-id', {'drivingProfile': 'Normal'}, ['car'])])
        events = self.directory / 'events.xml.gz'
        with gzip.open(events, 'wt') as stream:
            stream.write('''<events>
              <event type="departure" person="person-id" legMode="car" time="3590"/>
              <event type="vehicle enters traffic" person="person-id" vehicle="distinct-vehicle" time="3591"/>
              <event type="arrival" person="person-id" legMode="car" time="3650"/>
              <event type="departure" person="person-id" legMode="car" time="7200"/>
            </events>''')
        result = {name: artifact(self.directory, path) for name, path in [('plans', plans), ('events', events)]}
        manifest = dict(run_id='fixture-run', time_horizon=dict(end_seconds=86400),
                        results={'3': result}, inputs={'plans': result['plans']})
        return dict(directory=self.directory, manifest=manifest, iteration=3, plans=plans, events=events)

    def test_six_profiles_use_effective_types_and_keep_actual_planned_modes(self):
        people = []
        types = ('Normal', 'Tortuga', 'Liebre', 'Motociclista', 'MotocicletaLenta', 'MotocicletaRapida')
        for index, kind in enumerate(types):
            family, driving, _ = IDENTITIES[kind]
            attrs = dict(simz1AgentSchema=SCHEMA, simz1AgentType=kind, effectiveVehicleType=kind,
                         simz1VehicleFamily=family, drivingProfile=driving)
            # Mode is deliberately not guessed from vehicle family.
            people.append(('person-' + kind, attrs, ['motorcycle' if index >= 3 else 'car', 'walk']))
        plans = self.plans(people, compressed=True)
        metadata = read_person_metadata(plans)
        self.assertEqual({p['profile'] for p in metadata.values()}, set(types))
        self.assertEqual(metadata['person-MotocicletaLenta']['label'], 'Moto tortuga')
        self.assertEqual(metadata['person-MotocicletaLenta']['planned_modes'], ['motorcycle', 'walk'])
        self.assertEqual(metadata['person-Tortuga']['family'], 'carro')
        self.assertEqual(read_profiles(plans)['person-Tortuga'], 'tortuga')
        self.assertTrue(all(p['monte_carlo_eligible'] and not p['internal_transit_driver'] for p in metadata.values()))

    def test_historical_profiles_and_explicit_effective_moto_without_speed_inference(self):
        plans = self.plans([
            ('slow-name', {'drivingProfile': 'Liebre', 'simz1MaximumVelocityMps': '100'}, ['car']),
            ('fast-name', {'drivingProfile': 'Tortuga'}, ['car']),
            ('plain', {'drivingProfile': 'Normal'}, ['car']),
            ('recorded-moto', {'drivingProfile': 'Motociclista', 'effectiveVehicleType': 'Motociclista'}, ['car']),
            ('unproven', {'drivingProfile': 'Motociclista', 'simz1MaximumVelocityMps': '100'}, ['car']),
            ('pt_ordinary_person', {'drivingProfile': 'Normal'}, ['car']),
        ])
        metadata = read_person_metadata(plans)
        self.assertEqual(metadata['slow-name']['family'], 'carro')
        self.assertEqual(metadata['fast-name']['profile'], 'Tortuga')
        self.assertEqual(metadata['recorded-moto']['family'], 'moto')
        self.assertEqual(metadata['unproven']['profile'], 'unknown')
        self.assertTrue(metadata['pt_ordinary_person']['monte_carlo_eligible'])
        self.assertNotIn('native-transit-driver', metadata)

    def test_passenger_and_heavy_are_separate_from_car_and_bus_fleet(self):
        plans = self.plans([
            ('passenger', dict(simz1AgentSchema='simz1-six-v1', simz1AgentType='TransportePublico'), ['pt']),
            ('heavy', dict(simz1AgentSchema='simz1-six-v1', simz1AgentType='TransportePesado',
                           effectiveVehicleType='TransportePesado', drivingProfile='TransportePesado'), ['truck'])])
        metadata = read_person_metadata(plans)
        self.assertEqual(metadata['passenger']['population_role'], 'passenger')
        self.assertIsNone(metadata['passenger']['effective_vehicle_type'])
        self.assertEqual(metadata['heavy']['family'], 'pesado')
        self.assertEqual(metadata['heavy']['planned_modes'], ['truck'])

    def test_contradictory_new_identity_is_rejected(self):
        attrs = dict(simz1AgentSchema=SCHEMA, simz1AgentType='Motociclista',
                     effectiveVehicleType='Normal', drivingProfile='normal', simz1VehicleFamily='moto')
        with self.assertRaisesRegex(ValueError, 'efectivo inconsistente'):
            read_person_metadata(self.plans([('bad', attrs, ['car'])]))

    def test_metadata_selection_requires_fingerprinted_plans_and_preserves_input_fallback(self):
        selection = self.selection()
        metadata, source = metadata_for_selection(selection)
        self.assertEqual(source['origin'], 'iteration_plans')
        self.assertEqual(metadata['person-id']['profile'], 'Normal')
        selection['manifest']['results'] = {}
        selection.pop('plans')
        _, source = metadata_for_selection(selection)
        self.assertEqual(source['origin'], 'frozen_input_plans')
        (self.directory / 'plans.xml').write_text('<population/>')
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            metadata_for_selection(selection)

    def test_valid_canonical_cache_is_not_rewritten_or_replayed(self):
        selection = self.selection()
        path, report = export_table(selection)
        sidecar = path.with_suffix('.provenance.json')
        before = [(item.read_bytes(), item.stat().st_mtime_ns) for item in (path, sidecar)]
        with patch('simz1_trip_table.write_events', side_effect=AssertionError('must reuse canonical table')):
            again, provenance = export_table(selection)
        self.assertEqual((again, provenance), (path, report))
        self.assertEqual(before, [(item.read_bytes(), item.stat().st_mtime_ns) for item in (path, sidecar)])
        records = list(rows(path))
        self.assertEqual(records[0]['vehicle_id'], 'distinct-vehicle')
        self.assertEqual(records[0]['departure'], 3590)
        self.assertEqual(records[0]['duration_seconds'], 60)
        self.assertIsNone(records[1]['duration_seconds'])

    def test_valid_legacy_sidecar_without_horizon_is_reused(self):
        selection = self.selection()
        path, report = export_table(selection)
        report.pop('time_horizon_seconds')
        sidecar = path.with_suffix('.provenance.json')
        sidecar.write_text(json.dumps(report), encoding='utf-8')
        before = sidecar.read_bytes()
        with patch('simz1_trip_table.write_events', side_effect=AssertionError('must reuse v1')):
            export_table(selection)
        self.assertEqual(sidecar.read_bytes(), before)

    def test_external_destination_reuses_valid_canonical_without_event_replay_or_source_change(self):
        selection = self.selection()
        canonical, report = export_table(selection)
        sidecar = canonical.with_suffix('.provenance.json')
        before = [(item.read_bytes(), item.stat().st_mtime_ns) for item in (canonical, sidecar)]
        external_root = tempfile.TemporaryDirectory(prefix='simz1 external thesis analysis ')
        self.addCleanup(external_root.cleanup)
        external = Path(external_root.name) / 'it.3' / 'trips.csv.gz'
        with patch('simz1_trip_table.write_events', side_effect=AssertionError('must copy validated canonical')):
            output, copied_report = export_table(selection, external)
        self.assertEqual(output, external)
        self.assertEqual(copied_report, report)
        self.assertEqual(external.read_bytes(), canonical.read_bytes())
        self.assertEqual(sha256(external), report['csv_sha256'])
        self.assertEqual(json.loads(external.with_suffix('.provenance.json').read_text(encoding='utf-8')), report)
        self.assertEqual(before, [(item.read_bytes(), item.stat().st_mtime_ns) for item in (canonical, sidecar)])

    def test_stale_provenance_and_corrupt_bytes_are_recreated_from_validated_sources(self):
        selection = self.selection()
        path, report = export_table(selection)
        for key, invalid in [('run_id', 'other-run'), ('iteration', 99), ('definition', 'link segment'),
                             ('sources', {}), ('csv_sha256', 'wrong')]:
            broken = dict(report, **{key: invalid})
            path.with_suffix('.provenance.json').write_text(json.dumps(broken), encoding='utf-8')
            with self.subTest(key=key), patch('simz1_trip_table.write_events', wraps=write_events) as writer:
                _, fresh = export_table(selection)
                self.assertEqual(writer.call_count, 1)
                self.assertEqual(fresh['definition'], DEFINITION)
        path.write_bytes(b'corrupt')
        _, fresh = export_table(selection)
        self.assertEqual(fresh['csv_sha256'], sha256(path))
        self.assertEqual(len(list(rows(path))), 2)

    def test_changed_source_is_rejected_even_when_canonical_cache_exists(self):
        selection = self.selection()
        path, _ = export_table(selection)
        before = path.read_bytes()
        selection['events'].write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            export_table(selection)
        self.assertEqual(path.read_bytes(), before)

    def test_native_compact_cache_does_not_copy_again(self):
        selection = self.selection()
        native = self.directory / 'native.csv.gz'
        write_events(selection['events'], native, 'fixture-run', 3, {'person-id': 'Normal'}, 86400)
        summary = self.directory / 'native-summary.json'
        summary.write_text('{}')
        selection['manifest']['trip_products'] = {'3': dict(compact=artifact(self.directory, native),
                                                          summary=artifact(self.directory, summary))}
        path, report = export_table(selection)
        self.assertEqual(report['source_kind'], 'native_compact')
        with patch('shutil.copyfile', side_effect=AssertionError('must reuse native-derived table')):
            self.assertEqual(export_table(selection)[0], path)


if __name__ == '__main__':
    unittest.main()
