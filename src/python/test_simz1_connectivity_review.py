"""Small read-only connectivity fixtures; invoke explicitly, no MATSim required."""
import gzip
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_connectivity_review import DEFAULT_WITNESSES, analyze


class ConnectivityReviewTest(unittest.TestCase):
    def fixture(self, folder, nodes, ways, links, lane_xml='<laneDefinitions/>', bounds=(0, 0, 10, 10)):
        osm = ET.Element('osm')
        ET.SubElement(osm, 'bounds', minlon=str(bounds[0]), minlat=str(bounds[1]),
                      maxlon=str(bounds[2]), maxlat=str(bounds[3]))
        for nid, (x, y) in nodes.items():
            ET.SubElement(osm, 'node', id=nid, lon=str(x), lat=str(y))
        for wid, refs, tags in ways:
            way = ET.SubElement(osm, 'way', id=wid)
            for nid in refs:
                ET.SubElement(way, 'nd', ref=nid)
            for key, value in tags.items():
                ET.SubElement(way, 'tag', k=key, v=value)
        network, nblock, lblock = ET.Element('network'), ET.Element('nodes'), ET.Element('links')
        network.extend([nblock, lblock])
        for nid in nodes:
            ET.SubElement(nblock, 'node', id=nid)
        for lid, a, b, wid, modes in links:
            ET.SubElement(lblock, 'link', id=lid, **{'from': a, 'to': b, 'origid': wid,
                                                   'modes': modes, 'length': '10'})
        paths = tuple(Path(folder) / name for name in ('map.osm', 'network.xml', 'lanes.xml'))
        paths[0].write_bytes(ET.tostring(osm))
        paths[1].write_bytes(ET.tostring(network))
        paths[2].write_text(lane_xml, encoding='utf-8')
        return paths

    def test_direction_modes_and_lane_movements_are_used_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'j': (2, 1), 'b': (3, 1), 'c': (2, 2)},
                [('10', ['a', 'j'], {'highway': 'residential', 'oneway': 'yes'}),
                 ('20', ['j', 'b'], {'highway': 'residential', 'oneway': 'yes'}),
                 ('30', ['j', 'c'], {'highway': 'footway', 'foot': 'yes'})],
                [('in', 'a', 'j', '10', 'car,walk'), ('east', 'j', 'b', '20', 'car'),
                 ('north', 'j', 'c', '30', 'walk')],
                '<laneDefinitions><lanesToLinkAssignment linkIdRef="in"><lane id="entry">'
                '<leadsTo><toLane refId="out"/></leadsTo></lane><lane id="out"><leadsTo>'
                '<toLink refId="east"/></leadsTo></lane></lanesToLinkAssignment></laneDefinitions>')
            before = {path: path.read_bytes() for path in paths}
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4),
                             witness_pairs=[('a', 'b'), ('b', 'a'), ('a', 'c')])
            routes = {(row['from_node'], row['to_node'], row['mode']): row for row in result['witness_routes']}
            self.assertEqual(routes['a', 'b', 'car']['links'], ['in', 'east'])
            self.assertTrue(routes['b', 'a', 'car']['absence_proven'])
            self.assertTrue(routes['a', 'c', 'walk']['absence_proven'])
            incoming = next(row for row in result['links'] if row['id'] == 'in')
            self.assertEqual(incoming['lane_excluded_successors'], ['north'])
            self.assertEqual(incoming['movements_by_mode']['car']['successors'][0]['terminal_lanes'], ['out'])
            self.assertEqual(result['unrepresented_modes'], ['bike', 'pt'])
            for path, content in before.items():
                self.assertEqual(content, path.read_bytes())

    def test_near_endpoints_are_not_joined_or_called_real_dead_ends(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'b': (2, 1), 'c': (2.000001, 1), 'd': (3, 1)},
                [('10', ['a', 'b'], {'highway': 'residential', 'oneway': 'yes'}),
                 ('20', ['c', 'd'], {'highway': 'residential', 'oneway': 'yes'})],
                [('first', 'a', 'b', '10', 'car'), ('second', 'c', 'd', '20', 'car')])
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'd')])
            self.assertTrue(result['witness_routes'][0]['absence_proven'])
            endpoint = next(row for row in result['endpoints'] if row['node_id'] == 'b')
            self.assertEqual(endpoint['classification'], 'extremo_osm_sin_conexion_causa_real_no_confirmada')
            self.assertEqual(result['summary']['connections_changed'], 0)
            self.assertEqual(len(result['links']), 2)

    def test_access_bridge_and_extract_are_distinct_and_do_not_add_edges(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder,
                {'a': (-1, 2), 'b': (5, 2), 'c': (2, 1), 'd': (2, 3), 'p': (1, 1), 'q': (1, 3)},
                [('10', ['a', 'b'], {'highway': 'residential', 'oneway': 'yes', 'bridge': 'yes', 'layer': '1'}),
                 ('20', ['c', 'd'], {'highway': 'residential', 'oneway': 'yes', 'layer': '0'}),
                 ('30', ['p', 'q'], {'highway': 'service', 'access': 'private'})],
                [('bridge', 'a', 'b', '10', 'car'), ('surface', 'c', 'd', '20', 'car')], bounds=(0, 0, 4, 4))
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'd')])
            self.assertTrue(result['witness_routes'][0]['absence_proven'])
            self.assertTrue(any(row['way_ids'] == ['10', '20'] for row in result['crossings_without_shared_nodes']))
            self.assertTrue(all(not row['connection_added'] for row in result['crossings_without_shared_nodes']))
            private = next(row for row in result['source_ways'] if row['way_id'] == '30')
            self.assertEqual(private['car_import_exclusion'], 'restricted_access')
            self.assertEqual(result['missing_segments'], [])
            self.assertEqual(next(row for row in result['endpoints'] if row['node_id'] == 'a')['classification'],
                             'limite_del_extracto_continuacion_desconocida')
            self.assertIn('not_approved', result['administrative_boundary'])

    def test_reverse_direction_missing_segment_and_bounded_route(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'b': (2, 1), 'c': (3, 1)},
                [('10', ['a', 'b', 'c'], {'highway': 'residential', 'oneway': '-1'})],
                [('back2', 'c', 'b', '10', 'car'), ('back1', 'b', 'a', '10', 'car')])
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('c', 'a')], max_route_visits=1)
            self.assertEqual(result['witness_routes'][0]['status'], 'search_limit')
            self.assertFalse(result['witness_routes'][0]['absence_proven'])
            self.assertEqual(result['missing_segments'], [])
            network = ET.parse(paths[1])
            block = network.getroot().find('links')
            block.remove(block.findall('link')[1])
            network.write(paths[1])
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[])
            self.assertEqual([(row['from_node'], row['to_node']) for row in result['missing_segments']], [('b', 'a')])

    def test_components_use_lane_movements_not_shared_junctions(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'b': (2, 1), 'c': (3, 1), 'x': (1, 3), 'y': (2, 3)},
                [('10', ['a', 'b'], {'highway': 'residential'}),
                 ('20', ['b', 'c'], {'highway': 'residential'}),
                 ('30', ['x', 'y'], {'highway': 'residential', 'oneway': 'yes'})],
                [('ab', 'a', 'b', '10', 'car'), ('ba', 'b', 'a', '10', 'car'),
                 ('bc', 'b', 'c', '20', 'car'), ('cb', 'c', 'b', '20', 'car'),
                 ('xy', 'x', 'y', '30', 'car')],
                '<laneDefinitions><lanesToLinkAssignment linkIdRef="ab"><lane id="ab-lane"><leadsTo>'
                '<toLink refId="ba"/></leadsTo></lane></lanesToLinkAssignment>'
                '<lanesToLinkAssignment linkIdRef="cb"><lane id="cb-lane"><leadsTo>'
                '<toLink refId="bc"/></leadsTo></lane></lanesToLinkAssignment></laneDefinitions>')
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'c'), ('c', 'a')])
            graph = result['components_by_mode']['car']
            self.assertEqual(graph['weak_component_count'], 3)
            self.assertEqual(graph['strong_component_count'], 3)
            self.assertEqual(sorted(row['link_count'] for row in graph['strong_components']), [1, 2, 2])
            ids = {row['id']: row['component_ids_by_mode']['car'] for row in result['links']}
            self.assertEqual(ids['ab'], ids['ba'])
            self.assertNotEqual(ids['ab']['weak'], ids['bc']['weak'])
            self.assertEqual(ids['bc'], ids['cb'])
            self.assertTrue(all(row['absence_proven'] for row in result['witness_routes']))

    def test_gzip_matsim_output_origid_attribute_matches_plain_input(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'b': (2, 1)},
                [('10', ['a', 'b'], {'highway': 'residential', 'oneway': 'yes'})],
                [('ab', 'a', 'b', '10', 'car')])
            original = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'b')])
            output = ET.parse(paths[1])
            link = output.getroot().find('links/link')
            way = link.attrib.pop('origid')
            ET.SubElement(ET.SubElement(link, 'attributes'), 'attribute', name='origid').text = way
            payloads = (paths[0].read_bytes(), ET.tostring(output.getroot()), paths[2].read_bytes())
            compressed = tuple(Path(str(path) + '.gz') for path in paths)
            for path, payload in zip(compressed, payloads):
                path.write_bytes(gzip.compress(payload))
            before = {path: path.read_bytes() for path in compressed}
            result = analyze(*compressed, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'b')])
            for key in ('summary', 'links', 'missing_segments', 'components_by_mode', 'global_import_check', 'witness_routes'):
                self.assertEqual(result[key], original[key], key)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_ten_defaults_and_missing_witness_is_explicit_not_dropped(self):
        self.assertEqual(len(DEFAULT_WITNESSES), 10)
        self.assertEqual(len(set(DEFAULT_WITNESSES)), 10)
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (1, 1), 'b': (2, 1)},
                [('10', ['a', 'b'], {'highway': 'residential', 'oneway': 'yes'})],
                [('ab', 'a', 'b', '10', 'car,walk')])
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[('a', 'missing')])
            self.assertEqual(len(result['witness_routes']), 2)
            self.assertTrue(all(row['status'] == 'missing_network_endpoint' for row in result['witness_routes']))
            self.assertTrue(all(not row['absence_proven'] for row in result['witness_routes']))
            self.assertEqual(set(result['components_by_mode']), {'car', 'walk'})

    def test_global_import_check_finds_outside_sector_direction_access_and_source_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(folder, {'a': (20, 20), 'b': (21, 20), 'p': (20, 21), 'q': (21, 21)},
                [('10', ['a', 'b'], {'highway': 'residential', 'oneway': 'yes', 'noexit': 'yes'}),
                 ('20', ['p', 'q'], {'highway': 'service', 'access': 'private'})],
                [('wrong_direction', 'b', 'a', '10', 'car'), ('private', 'p', 'q', '20', 'car'),
                 ('unknown_source', 'a', 'q', 'missing-way', 'car')])
            osm = ET.parse(paths[0])
            ET.SubElement(osm.getroot().find("node[@id='b']"), 'tag', k='noexit', v='yes')
            osm.write(paths[0])
            result = analyze(*paths, sector_bounds=(0, 0, 4, 4), witness_pairs=[])
            self.assertEqual(result['summary']['selected_links'], 0)
            audit = result['global_import_check']
            self.assertEqual(audit['missing_admissible_directed_segments'], 1)
            self.assertEqual(audit['inconsistent_source_access_or_direction_links'], 3)
            self.assertEqual({row['reason'] for row in audit['inconsistent_links']},
                             {'directed_segment_not_admitted_by_source', 'restricted_access', 'missing_source_way'})
            self.assertEqual(audit['declared_noexit']['ways'][0]['way_id'], '10')
            self.assertEqual(audit['declared_noexit']['nodes'][0]['node_id'], 'b')


if __name__ == '__main__':
    unittest.main()
