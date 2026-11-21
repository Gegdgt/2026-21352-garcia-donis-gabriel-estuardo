"""Small in-memory gateway generation/metadata checks; no QSim, subprocesses or file cleanup."""
import argparse
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_montecarlo_z1 as generator
from simz1_population import _verify_population, population_spec
from simz1_temporal import temporal_spec, trip_id


KINDS = ('external-external', 'external-internal', 'internal-external', 'internal-internal')


class TinyModel:
    eligible_links = {'entry', 'inside', 'exit'}
    summary = {'scope': 'observed_z1_only'}
    links = {key: {'capacity': 1000} for key in ('entry', 'inside', 'exit')}
    entry_gateways = {'entry': {'evidence_crossing_links': []}}
    exit_gateways = {'exit': {'evidence_crossing_links': []}}

    def validate_shares(self, shares):
        if set(shares) != set(KINDS):
            raise ValueError('Invalid shares')

    def sample(self, rng, od_type):
        external_origin, external_destination = [part == 'external' for part in od_type.split('-')]
        origin = 'entry' if external_origin else 'inside'
        destination = 'exit' if external_destination else 'inside'
        if origin == destination:
            destination = 'entry'
        return dict(od_type=od_type, origin_link=origin, destination_link=destination,
                    origin_xy=(1, 2), destination_xy=(3, 4),
                    origin_gateway='entry' if external_origin else None,
                    destination_gateway='exit' if external_destination else None,
                    origin_zone='synthetic-exterior-entry:entry' if external_origin else None,
                    destination_zone='synthetic-exterior-exit:exit' if external_destination else None,
                    scope='observed_z1_only', door_to_door_seconds=None, metadata_source='synthetic_gateway_od')

    def validate_metadata(self, record):
        if record.get('scope') != 'observed_z1_only' or record.get('door_to_door_seconds') is not None:
            raise ValueError('Invalid scope')
        expected = self.sample(None, record['od_type'])
        expected = {key: value for key, value in expected.items() if not key.endswith('_xy')}
        from simz1_od_policy import CLASS_BY_TYPE
        expected['od_class'] = CLASS_BY_TYPE[record['od_type']]
        if record != expected:
            raise ValueError('Invalid metadata')


def generated(count=4, seed=17):
    model = TinyModel()
    shares = dict.fromkeys(KINDS, .25)
    people, report, allowed = generator.gateway_people(model, seed, population_spec(agents=count), shares, temporal_spec())
    return model, list(people), report, allowed


def verify_people(people, model):
    root = ET.Element('population')
    namespace = 'http://www.matsim.org/files/dtd'
    vehicles = ET.Element(f'{{{namespace}}}vehicleDefinitions')
    for profile in ('Normal', 'Tortuga', 'Liebre'):
        ET.SubElement(vehicles, 'vehicleType', id=profile)
    for person in copy.deepcopy(people):
        ident = person.get('id')
        ET.SubElement(person.find('attributes'), 'attribute', name='vehicles',
                      **{'class': 'org.matsim.vehicles.PersonVehicles'}).text = json.dumps({'car': ident})
        profile = person.findtext("attributes/attribute[@name='drivingProfile']")
        ET.SubElement(vehicles, 'vehicle', id=ident, type=profile)
        root.append(person)
    return _verify_population(io.BytesIO(ET.tostring(root)), io.BytesIO(ET.tostring(vehicles)),
                              len(people), model.eligible_links, 1, True, spatial_model=model)


class GatewayGenerationTests(unittest.TestCase):
    def test_network_default_never_requires_a_boundary_file(self):
        with patch.object(generator.Path, 'is_file') as check:
            self.assertIsNone(generator.spatial_options('network', None, None, mode='montecarlo',
                trips_per_person=1, temporal_profile=None, corridor_policy='redistribute'))
            check.assert_not_called()

    def test_missing_boundary_is_explicit_before_config_or_population_io(self):
        for mode in ('gateway-od', 'through-traffic'):
            for boundary in (None, Path('not-configured.geojson')):
                with self.subTest(mode=mode, boundary=boundary), \
                        patch.object(generator.Path, 'is_file', return_value=False), \
                        patch.object(generator.ET, 'parse') as read_config, \
                        patch.object(generator, 'load_gateway_model') as load_model, \
                        patch.object(generator, 'gateway_people') as people, \
                        patch.object(generator, 'create_run_directory') as create:
                    with self.assertRaisesRegex(ValueError, 'Falta configurar --zone-boundary'):
                        generator.generar('unread-config.xml', None, 17, agents=1,
                                          od_mode=mode, zone_boundary=boundary)
                    read_config.assert_not_called()
                    load_model.assert_not_called()
                    people.assert_not_called()
                    create.assert_not_called()

    def test_cli_defaults_alias_and_shared_forwarding(self):
        parser = argparse.ArgumentParser()
        generator.add_generation_options(parser)
        self.assertEqual(generator.generation_options(parser.parse_args([]))['od_mode'], 'network')
        args = parser.parse_args(['--od-mode', 'through-traffic', '--zone-boundary', 'zone.geojson', '--od-shares', '1,2,3,4'])
        options = generator.generation_options(args)
        self.assertEqual(options['od_mode'], 'through-traffic')
        self.assertEqual(options['zone_boundary'], Path('zone.geojson'))
        self.assertEqual(options['od_shares'], '1,2,3,4')

    def test_incompatible_options_fail_before_inputs_or_directory_creation(self):
        cases = [dict(od_mode='gateway-od'),
                 dict(od_mode='gateway-od', zone_boundary='zone.geojson', mode='debug'),
                 dict(od_mode='gateway-od', zone_boundary='zone.geojson', trips_per_person=2),
                 dict(od_mode='gateway-od', zone_boundary='zone.geojson', temporal_profile='peaks'),
                 dict(od_mode='gateway-od', zone_boundary='zone.geojson', corridor_policy='redistribute'),
                 dict(od_mode='network', zone_boundary='zone.geojson'),
                 dict(od_mode='network', od_shares='1,0,0,0')]
        for options in cases:
            with self.subTest(options=options), patch.object(generator, 'create_run_directory') as create:
                with self.assertRaises(ValueError):
                    generator.generar('unread-config.xml', None, 17, **options)
                create.assert_not_called()

    def test_reproducible_single_trip_preserves_ledger_and_scope(self):
        model, people, report, allowed = generated()
        _, repeated, repeated_report, _ = generated()
        self.assertEqual([ET.tostring(p) for p in people], [ET.tostring(p) for p in repeated])
        self.assertEqual(report, repeated_report)
        self.assertEqual(sum(report['spatial_demand']['realized_counts'].values()), 4)
        self.assertEqual(set(report['spatial_demand']['allowed_links']), allowed)
        for person in people:
            ledger = json.loads(person.findtext("attributes/attribute[@name='simz1Trips']"))
            spatial = json.loads(person.findtext("attributes/attribute[@name='simz1SpatialOD']"))
            self.assertEqual(len(ledger), 1)
            self.assertEqual(set(ledger[0]), {'id', 'index', 'planned_departure', 'origin_link', 'destination_link'})
            self.assertEqual(set(spatial), {trip_id(person.get('id'), 1)})
            self.assertFalse({'origin_xy', 'destination_xy'} & set(next(iter(spatial.values()))))
            self.assertGreaterEqual(ledger[0]['planned_departure'], 0)
            self.assertLess(ledger[0]['planned_departure'], 86400)
        verified = verify_people(people, model)
        self.assertNotIn('directed_car_scc', verified)
        self.assertTrue(verified['directed_car_turn_reachability'])
        self.assertEqual(verified['spatial_od_counts'], report['spatial_demand']['realized_counts'])

    def test_spatial_configuration_rejected_before_directory_creation(self):
        for value in (None, 'false'):
            config = ET.ElementTree(ET.Element('config'))
            values = {} if value is None else {'controler.enableLinkToLinkRouting': value}
            with self.subTest(link_to_link=value), patch.object(generator.ET, 'parse', return_value=config), \
                    patch.object(generator.Path, 'is_file', return_value=True), \
                    patch.object(generator, 'parameters', return_value=values), \
                    patch.object(generator, 'create_run_directory') as create:
                with self.assertRaisesRegex(ValueError, 'enableLinkToLinkRouting=true'):
                    generator.generar('config.xml', None, 17, agents=1, od_mode='gateway-od', zone_boundary='zone.geojson')
                create.assert_not_called()
        for value in (None, 'network', 'gateway-od'):
            config = ET.ElementTree(ET.Element('config'))
            module = ET.SubElement(config.getroot(), 'module', name='zona1SpatialRouting')
            if value is not None:
                ET.SubElement(module, 'param', name='mode', value=value)
            with self.subTest(spatial_mode=value), patch.object(generator.ET, 'parse', return_value=config), \
                    patch.object(generator, 'parameters', return_value={}), \
                    patch.object(generator, 'create_run_directory') as create:
                with self.assertRaisesRegex(ValueError, 'modulo zona1SpatialRouting preexistente'):
                    generator.generar('config.xml', None, 17, agents=1, corridor_policy='redistribute')
                create.assert_not_called()

    def test_verifier_rejects_changed_effective_od_and_fabricated_external_time(self):
        model, people, _, _ = generated(count=1)
        for field, value in (('origin_link', 'outside'), ('door_to_door_seconds', 90), ('scope', 'door_to_door')):
            damaged = copy.deepcopy(people)
            attribute = damaged[0].find("attributes/attribute[@name='simz1SpatialOD']")
            metadata = json.loads(attribute.text)
            next(iter(metadata.values()))[field] = value
            attribute.text = json.dumps(metadata)
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_people(damaged, model)
        damaged = copy.deepcopy(people)
        activities = damaged[0].findall('plan/activity')
        activities[0].set('link', 'entry' if activities[0].get('link') != 'entry' else 'inside')
        with self.assertRaises(ValueError):
            verify_people(damaged, model)


if __name__ == '__main__':
    unittest.main()
