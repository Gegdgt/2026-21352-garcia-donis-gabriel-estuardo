"""Small XML/event fixtures; no simulation, population generation, or run rewrite."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from simz1_motion import load_selected, read_vehicles, read_vehicle_definitions
from simz1_run import sha256
from simz1_trajectories import extract


class AgentMetadataTests(unittest.TestCase):
    categories = ('Normal', 'Motociclista', 'Liebre', 'Tortuga', 'TransportePublico', 'TransportePesado')
    # Recorded fixture values, not a claim that the proposed service is available.
    vehicle_values = {'Normal': (50 / 3.6, 1), 'Motociclista': (60 / 3.6, .25),
                      'Liebre': (90 / 3.6, 1), 'Tortuga': (25 / 3.6, 1),
                      'TransportePesado': (40 / 3.6, 3.5)}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        plans = ET.Element('population')
        vehicles = ET.Element('vehicleDefinitions', xmlns='http://www.matsim.org/files/dtd')
        for kind in self.categories:
            person = ET.SubElement(plans, 'person', id=kind)
            attributes = ET.SubElement(person, 'attributes')
            for name, value in [('simz1AgentSchema', 'simz1-six-v1'), ('simz1AgentType', kind)]:
                ET.SubElement(attributes, 'attribute', name=name).text = value
            if kind in self.vehicle_values:
                for name, value in [('drivingProfile', kind), ('effectiveVehicleType', kind),
                                    ('vehicles', json.dumps({'car': 'v_' + kind}))]:
                    ET.SubElement(attributes, 'attribute', name=name).text = value
                speed, pcu = self.vehicle_values[kind]
                vehicle_type = ET.SubElement(vehicles, 'vehicleType', id=kind)
                ET.SubElement(vehicle_type, 'maximumVelocity', meterPerSecond=str(speed))
                ET.SubElement(vehicle_type, 'passengerCarEquivalents', pce=str(pcu))
                ET.SubElement(vehicles, 'vehicle', id='v_' + kind, type=kind)
        # Old people deliberately retain matching names but have no new schema.
        for kind in ('Normal', 'Liebre', 'Tortuga'):
            person = ET.SubElement(plans, 'person', id='old_' + kind)
            attributes = ET.SubElement(person, 'attributes')
            ET.SubElement(attributes, 'attribute', name='drivingProfile').text = kind
        ET.ElementTree(plans).write(self.directory / 'plans.xml')
        ET.ElementTree(vehicles).write(self.directory / 'vehicles.xml')
        (self.directory / 'config.xml').write_text('<config/>')

    def selection(self):
        def record(name):
            return {'path': name, 'sha256': sha256(self.directory / name)}
        return dict(directory=self.directory, iteration=0, plans=self.directory / 'plans.xml',
                    manifest=dict(effective_config=record('config.xml'),
                                  effective_vehicles=record('vehicles.xml'),
                                  results={'0': {'plans': record('plans.xml')}}))

    def test_all_six_person_categories_survive_without_turning_passengers_into_buses(self):
        context = load_selected(self.selection())
        self.assertEqual(set(context.agent_types.values()), set(self.categories))
        for kind in self.categories:
            metadata = context.metadata(kind, 'v_' + kind)
            self.assertEqual(metadata['Agent_Type'], kind)
            self.assertEqual(metadata['Agent_Schema'], 'simz1-six-v1')
        passenger = context.metadata('TransportePublico')
        self.assertIsNone(passenger['Vehicle_Type'])
        self.assertIsNone(passenger['Vehicle_PCU'])
        self.assertNotIn('TransportePublico', context.profiles.values())

    def test_recorded_vehicle_values_and_legacy_speed_reader_contract(self):
        context = load_selected(self.selection())
        speeds, assignments = read_vehicles(self.directory / 'vehicles.xml')
        for kind, (speed, pcu) in self.vehicle_values.items():
            self.assertEqual(speeds[kind], speed)
            self.assertEqual(assignments['v_' + kind], kind)
            metadata = context.metadata(kind, 'v_' + kind)
            self.assertEqual(metadata['Vehicle_Type'], kind)
            self.assertEqual(metadata['Vehicle_PCU'], pcu)
            self.assertEqual(metadata['Vehicle_Type_Source'], 'effective_vehicles')
        context.declared_vehicle_types['Motociclista'] = 'unverified-person-attribute'
        self.assertEqual(context.metadata('Motociclista', 'v_Motociclista')['Vehicle_Type'], 'Motociclista')

    def test_old_profiles_do_not_gain_new_agent_categories(self):
        context = load_selected(self.selection())
        for kind in ('Normal', 'Liebre', 'Tortuga'):
            ident = 'old_' + kind
            self.assertEqual(context.profiles[ident], kind)
            self.assertIsNone(context.metadata(ident)['Agent_Type'])
            self.assertIsNone(context.metadata(ident)['Agent_Schema'])

    def test_pcu_is_optional_and_invalid_values_fail(self):
        path = self.directory / 'minimal.xml'
        path.write_text('<vehicleDefinitions><vehicleType id="old"/></vehicleDefinitions>')
        definitions, _ = read_vehicle_definitions(path)
        self.assertIsNone(definitions['old']['pcu'])
        for value in ('0', '-1', 'nan', 'inf'):
            path.write_text('<vehicleDefinitions><vehicleType id="bad">'
                           f'<passengerCarEquivalents pce="{value}"/>'
                           '</vehicleType></vehicleDefinitions>')
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'PCU'):
                read_vehicle_definitions(path)

    def test_export_and_visual_fallback_preserve_identity_without_using_pcu_as_geometry(self):
        context = load_selected(self.selection())
        kind, vehicle = 'Motociclista', 'v_Motociclista'
        links = {'l': dict(length=100, freespeed=10, from_node='a', to_node='b',
                           **{'from': [0, 0], 'to': [.001, 0]})}
        events = [dict(type='departure', time='0', person=kind, link='l'),
                  dict(type='vehicle enters traffic', time='0', person=kind, vehicle=vehicle,
                       link='l', relativePosition='0'),
                  dict(type='vehicle leaves traffic', time='20', person=kind, vehicle=vehicle,
                       link='l', relativePosition='1'),
                  dict(type='arrival', time='20', person=kind, link='l')]
        def export():
            return extract(events, links, lambda _: True, lambda _: [1, 2, 3],
                           SimpleNamespace(inv=lambda *args: (0, 0, 100)), motion=context)[0]
        segment = export()
        self.assertEqual(segment['Agent_Type'], kind)
        self.assertEqual(segment['Trip']['Agent_Type'], kind)
        self.assertEqual(segment['Vehicle_PCU'], .25)
        self.assertEqual(segment['Motion_Plan']['recorded_profile'], kind)
        self.assertEqual(segment['Motion_Plan']['profile_source'], 'default_visual_reference')
        self.assertEqual(segment['Motion_Plan']['rate_model'], 'visual_interpolation_only_not_qsim_acceleration')
        context.vehicle_pcus[vehicle] = 4
        changed = export()
        for field in ('path', 'timestamps', 'Distance_m', 'Motion_Plan', 'Speed_kmh'):
            self.assertEqual(segment[field], changed[field])
        # These payloads are exactly what the JSON and paged exporters preserve.
        self.assertEqual(json.loads(json.dumps(segment))['Agent_Type'], kind)


if __name__ == '__main__':
    unittest.main()
