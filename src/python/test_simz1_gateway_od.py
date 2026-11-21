"""Small spatial fixtures: no OSM snapshot, population generation or QSim."""
import copy
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_gateway_od import (GatewayModel, Polygon, boundary_geometry, normalize_shares,
                             load_gateway_model, validated_spatial_demand)


TYPES = ('external-external', 'external-internal', 'internal-external', 'internal-internal')
SQUARE = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}


def fixture():
    coordinates = {'outside-west': (-2, 5), 'west': (2, 5), 'a': (4, 5),
                   'b': (5, 5), 'c': (6, 5), 'east': (8, 5), 'outside-east': (12, 5)}
    nodes = {key: (500000 + x * 1000, 1600000 + y * 1000) for key, (x, y) in coordinates.items()}
    edges = [('cross-in', 'outside-west', 'west'), ('entry', 'west', 'a'),
             ('middle1', 'a', 'b'), ('middle2', 'b', 'c'), ('exit', 'c', 'east'),
             ('cross-out', 'east', 'outside-east')]
    links = {key: {'from_node': start, 'to_node': end, 'modes': ['car'],
                   'path': [coordinates[start], coordinates[end]]} for key, start, end in edges}
    return nodes, links, coordinates


def metadata(record):
    return {key: value for key, value in record.items() if key not in ('origin_xy', 'destination_xy')}


class ShareTests(unittest.TestCase):
    def test_default_through_traffic_and_explicit_weights(self):
        self.assertEqual(normalize_shares(), dict(zip(TYPES, (1, 0, 0, 0))))
        expected = dict(zip(TYPES, (0.5, 0.25, 0.125, 0.125)))
        self.assertEqual(normalize_shares('4,2,1,1'), expected)
        self.assertEqual(normalize_shares([4, 2, 1, 1]), expected)
        self.assertEqual(normalize_shares(dict(zip(TYPES, (4, 2, 1, 1)))), expected)

    def test_bad_share_inputs_fail_before_sampling(self):
        for raw in ('1,0,0', '0,0,0,0', '1,0,-1,1', 'nan,1,0,0', 'inf,0,0,0',
                    [True, 0, 0, 0], {'external-external': 1}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_shares(raw)


class PolygonTests(unittest.TestCase):
    def assertIntervals(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for actual_pair, expected_pair in zip(actual, expected):
            self.assertEqual(len(actual_pair), 2)
            for value, target in zip(actual_pair, expected_pair):
                self.assertAlmostEqual(value, target, places=9)

    def test_boundary_and_directed_segment_clipping(self):
        polygon = Polygon(SQUARE)
        self.assertTrue(polygon.contains((5, 5)))
        self.assertFalse(polygon.contains((-1, 5)))
        self.assertTrue(polygon.contains((0, 5), include_boundary=True))
        self.assertFalse(polygon.contains((0, 5), include_boundary=False))
        self.assertIntervals(polygon.clip_segment((-5, 5), (15, 5)), [(0.25, 0.75)])
        self.assertIntervals(polygon.clip_segment((15, 5), (-5, 5)), [(0.25, 0.75)])
        self.assertIntervals(polygon.clip_segment((1, 1), (9, 9)), [(0, 1)])
        self.assertIntervals(polygon.clip_segment((-5, -5), (-1, -1)), [])

    def test_concavity_and_holes_do_not_accept_a_chord_leaving_the_domain(self):
        concave = Polygon({'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10],
            [7, 10], [7, 3], [3, 3], [3, 10], [0, 10], [0, 0]]]})
        self.assertTrue(concave.contains((1, 5)))
        self.assertTrue(concave.contains((9, 5)))
        self.assertFalse(concave.contains((5, 5)))
        self.assertIntervals(concave.clip_segment((1, 5), (9, 5)), [(0, 0.25), (0.75, 1)])
        geometry = copy.deepcopy(SQUARE)
        geometry['coordinates'].append([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]])
        hole = Polygon(geometry)
        self.assertFalse(hole.contains((5, 5)))
        self.assertTrue(hole.contains((2, 5)))
        self.assertIntervals(hole.clip_segment((2, 5), (8, 5)), [(0, 1 / 3), (2 / 3, 1)])

    def test_invalid_geometry_fails_instead_of_substituting_a_bbox(self):
        for geometry in ({'type': 'MultiPolygon', 'coordinates': []},
                         {'type': 'Polygon', 'coordinates': []},
                         {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1], [0, 0]]]},
                         {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, float('nan')], [0, 0]]]}):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                Polygon(geometry)

    def test_geojson_requires_one_explicit_wgs84_polygon(self):
        self.assertEqual(boundary_geometry({'type': 'Feature', 'properties': {}, 'geometry': SQUARE}), SQUARE)
        self.assertEqual(boundary_geometry({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {}, 'geometry': SQUARE}]}), SQUARE)
        for document in ({**SQUARE, 'crs': {'type': 'name', 'properties': {'name': 'EPSG:32615'}}},
                         {'bbox': [0, 0, 10, 10]},
                         {'type': 'FeatureCollection', 'features': []},
                         {'type': 'FeatureCollection', 'features': [None]},
                         {'type': 'Feature', 'geometry': None},
                         {'type': 'Feature', 'geometry': {**SQUARE, 'crs': {'name': 'EPSG:32615'}}},
                         {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': SQUARE}] * 2},
                         {'type': 'Polygon', 'coordinates': [[[500000, 0], [500010, 0], [500010, 10], [500000, 0]]]}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                boundary_geometry(document)


class GatewayModelTests(unittest.TestCase):
    def test_network_perimeter_is_not_promoted_to_an_administrative_gateway(self):
        nodes, links, coordinates = fixture()
        enclosing = {'type': 'Polygon', 'coordinates': [[[-5, -5], [15, -5], [15, 15], [-5, 15], [-5, -5]]]}
        model = GatewayModel(nodes, links, enclosing, coordinates=coordinates)
        self.assertEqual(model.eligible_links, set(links))
        self.assertEqual(model.entry_gateways, {})
        self.assertEqual(model.exit_gateways, {})
        with self.assertRaisesRegex(ValueError, 'No hay par OD distinto y alcanzable'):
            model.validate_shares(normalize_shares())
        self.assertTrue(model.reachable('entry', 'exit'))

    def test_invalid_native_coordinates_fail_before_sampling(self):
        nodes, links, coordinates = fixture()
        nodes['a'] = (float('nan'), 1600000)
        with self.assertRaisesRegex(ValueError, 'Nodos/coordenadas'):
            GatewayModel(nodes, links, SQUARE, coordinates=coordinates)

    def test_four_types_use_real_directed_links_and_preserve_native_coordinates(self):
        nodes, links, coordinates = fixture()
        before = copy.deepcopy((nodes, links, coordinates, SQUARE))
        model = GatewayModel(nodes, links, SQUARE, coordinates=coordinates)
        self.assertEqual(set(model.eligible_links), {'entry', 'middle1', 'middle2', 'exit'})
        model.validate_shares({kind: 0.25 for kind in TYPES})
        for kind in TYPES:
            with self.subTest(kind=kind):
                record = model.sample(random.Random(42), kind)
                self.assertEqual(record['od_type'], kind)
                origin, destination = record['origin_link'], record['destination_link']
                self.assertIn(origin, model.eligible_links)
                self.assertIn(destination, model.eligible_links)
                self.assertNotEqual(origin, destination)
                self.assertEqual(tuple(record['origin_xy']), nodes[links[origin]['from_node']])
                self.assertEqual(tuple(record['destination_xy']), nodes[links[destination]['to_node']])
                external_origin, external_destination = kind.split('-')
                self.assertEqual(record['origin_gateway'], origin if external_origin == 'external' else None)
                self.assertEqual(record['destination_gateway'], destination if external_destination == 'external' else None)
                self.assertEqual(record['origin_zone'], 'synthetic-exterior-entry:' + origin if external_origin == 'external' else None)
                self.assertEqual(record['destination_zone'], 'synthetic-exterior-exit:' + destination if external_destination == 'external' else None)
                self.assertEqual(record['scope'], 'observed_z1_only')
                self.assertIsNone(record['door_to_door_seconds'])
                self.assertEqual(record['metadata_source'], 'synthetic_gateway_od')
                model.validate_metadata(metadata(record))
        self.assertEqual((nodes, links, coordinates, SQUARE), before)

    def test_seed_reproducibility_and_no_phantom_gateways_from_reversed_crossings(self):
        nodes, links, coordinates = fixture()
        model = GatewayModel(nodes, links, SQUARE, coordinates=coordinates)
        a, b = random.Random(77), random.Random(77)
        self.assertEqual([model.sample(a, kind) for kind in TYPES * 3],
                         [model.sample(b, kind) for kind in TYPES * 3])
        reversed_links = copy.deepcopy(links)
        crossing = reversed_links['cross-in']
        crossing['from_node'], crossing['to_node'] = crossing['to_node'], crossing['from_node']
        crossing['path'].reverse()
        reversed_model = GatewayModel(nodes, reversed_links, SQUARE, coordinates=coordinates)
        with self.assertRaises(ValueError):
            reversed_model.validate_shares({'external-external': 1, 'external-internal': 0,
                                           'internal-external': 0, 'internal-internal': 0})

    def test_exact_boundary_nodes_are_directional_gateways_without_external_network(self):
        nodes, links, coordinates = fixture()
        coordinates['west'], coordinates['east'] = (0, 5), (10, 5)
        nodes['west'], nodes['east'] = (500000, 1605000), (510000, 1605000)
        interior = {key: copy.deepcopy(value) for key, value in links.items()
                    if key not in ('cross-in', 'cross-out')}
        for link in interior.values():
            link['path'] = [coordinates[link['from_node']], coordinates[link['to_node']]]
        model = GatewayModel(nodes, interior, SQUARE, coordinates=coordinates)
        record = model.sample(random.Random(1), 'external-external')
        self.assertEqual((record['origin_gateway'], record['destination_gateway']), ('entry', 'exit'))
        self.assertEqual(set(model.eligible_links), set(interior))

    def test_entire_polyline_and_car_mode_are_required_not_only_inside_endpoints(self):
        nodes, links, coordinates = fixture()
        links['escaped'] = {'from_node': 'a', 'to_node': 'c', 'modes': ['car'],
                            'path': [coordinates['a'], (12, 5), coordinates['c']]}
        links['pedestrian'] = {'from_node': 'a', 'to_node': 'b', 'modes': ['walk'],
                              'path': [coordinates['a'], coordinates['b']]}
        model = GatewayModel(nodes, links, SQUARE, coordinates=coordinates)
        self.assertNotIn('escaped', model.eligible_links)
        self.assertNotIn('pedestrian', model.eligible_links)
        self.assertEqual(model.sample(random.Random(1), 'external-external')['origin_gateway'], 'entry')

    def test_missing_exit_and_forbidden_turn_reject_unreachable_external_pairs(self):
        nodes, links, coordinates = fixture()
        missing_exit = {key: value for key, value in links.items() if key != 'cross-out'}
        model = GatewayModel(nodes, missing_exit, SQUARE, coordinates=coordinates)
        with self.assertRaises(ValueError):
            model.sample(random.Random(1), 'external-external')
        blocked = GatewayModel(nodes, links, SQUARE, coordinates=coordinates,
                               lane_movements={'middle1': set()})
        with self.assertRaises(ValueError):
            blocked.sample(random.Random(1), 'external-external')
        allowed = GatewayModel(nodes, links, SQUARE, coordinates=coordinates,
                               lane_movements={'middle1': {'middle2'}})
        self.assertEqual(allowed.sample(random.Random(1), 'external-external')['destination_gateway'], 'exit')
        for restrictions in ({'cross-in': set()}, {'exit': set()}):
            with self.subTest(restrictions=restrictions):
                blocked_gateway = GatewayModel(nodes, links, SQUARE, coordinates=coordinates,
                                               lane_movements=restrictions)
                with self.assertRaises(ValueError):
                    blocked_gateway.sample(random.Random(1), 'external-external')

    def test_metadata_rejects_changed_gateway_or_unobserved_door_to_door_time(self):
        nodes, links, coordinates = fixture()
        model = GatewayModel(nodes, links, SQUARE, coordinates=coordinates)
        record = metadata(model.sample(random.Random(1), 'external-external'))
        for patch in ({'origin_link': 'cross-in'}, {'origin_gateway': 'middle1'},
                      {'door_to_door_seconds': 100}, {'scope': 'door_to_door'},
                      {'invented_field': True}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                model.validate_metadata({**record, **patch})
        internal = metadata(model.sample(random.Random(1), 'internal-internal'))
        internal['origin_link'], internal['destination_link'] = internal['destination_link'], internal['origin_link']
        with self.assertRaises(ValueError):
            model.validate_metadata(internal)


class SpatialManifestTests(unittest.TestCase):
    def test_fingerprinted_polygon_network_and_effective_router_must_agree(self):
        from pyproj import Transformer
        transform = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True)
        nodes, links, _ = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            boundary, network, config = (directory/name for name in ('zone.geojson', 'network.xml', 'config.xml'))
            geometry = dict(type='Polygon', coordinates=[[list(transform.transform(500000+x*1000, 1600000+y*1000))
                                                         for x, y in SQUARE['coordinates'][0]]])
            boundary.write_text(json.dumps(geometry), encoding='utf-8')
            root = ET.Element('network'); ns = ET.SubElement(root, 'nodes'); ls = ET.SubElement(root, 'links')
            for ident, (x, y) in nodes.items():
                ET.SubElement(ns, 'node', id=ident, x=str(x), y=str(y))
            for ident, link in links.items():
                import math
                ET.SubElement(ls, 'link', id=ident, length=str(math.dist(nodes[link['from_node']],nodes[link['to_node']])), capacity='1000', freespeed='10', permlanes='1', **{'from': link['from_node'], 'to': link['to_node'], 'modes': 'car'})
            ET.ElementTree(root).write(network, encoding='utf-8')
            model = load_gateway_model(network, boundary)
            self.assertEqual(model.entry_gateways.keys(), {'entry'})
            self.assertEqual(model.exit_gateways.keys(), {'exit'})
            root = ET.Element('config')
            for module, values in {'global': {'coordinateSystem': 'EPSG:32615'},
                                   'controler': {'enableLinkToLinkRouting': 'true'},
                                   'zona1SpatialRouting': {'mode': 'gateway-od', 'allowedLinks': ' '.join(sorted(model.eligible_links))}}.items():
                parent = ET.SubElement(root, 'module', name=module)
                for name, value in values.items():
                    ET.SubElement(parent, 'param', name=name, value=value)
            def artifact(path):
                return dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            def save_config():
                ET.ElementTree(root).write(config, encoding='utf-8')
                manifest['inputs']['config'] = artifact(config)
            manifest = dict(spatial_demand=model.summary, inputs={'network': artifact(network), 'zone_boundary': artifact(boundary)})
            save_config()
            self.assertEqual(validated_spatial_demand(directory, manifest), model.summary)
            altered = copy.deepcopy(manifest); altered['spatial_demand']['entry_gateways'] = {}
            with self.assertRaisesRegex(ValueError, 'Catalogo espacial'):
                validated_spatial_demand(directory, altered)
            option = root.find("module[@name='controler']/param[@name='enableLinkToLinkRouting']")
            option.set('value', 'false'); save_config()
            with self.assertRaisesRegex(ValueError, 'enableLinkToLinkRouting=true'):
                validated_spatial_demand(directory, manifest)
            option.set('value', 'true'); save_config()
            option = root.find("module[@name='zona1SpatialRouting']/param[@name='allowedLinks']")
            option.set('value', option.get('value')+' cross-out'); save_config()
            with self.assertRaisesRegex(ValueError, 'Dominio de routing'):
                validated_spatial_demand(directory, manifest)
            option.set('value', ' '.join(sorted(model.eligible_links))); save_config()
            boundary.write_text(json.dumps(geometry)+'\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
                validated_spatial_demand(directory, manifest)


if __name__ == '__main__':
    unittest.main()
