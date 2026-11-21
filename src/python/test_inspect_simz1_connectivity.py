"""Offline inspection contracts, tiny fixtures only; no native simulation."""
from contextlib import redirect_stdout
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from inspect_simz1_connectivity import (checked_configuration, digest, inspect, main, route_restriction_exposure,
                                      source_geometry_check, topology_signature, witness_blockers)


class ConnectivityInspectionTests(unittest.TestCase):
    def fixture(self, directory):
        from pyproj import Transformer
        transform = Transformer.from_crs('EPSG:4326', 'EPSG:32615', always_xy=True)
        osm, network = ET.Element('osm'), ET.Element('network')
        nodes, links = ET.SubElement(network, 'nodes'), ET.SubElement(network, 'links')
        for nid, lon, lat in [('a', -90.5051, 14.6260), ('b', -90.5051, 14.6261)]:
            ET.SubElement(osm, 'node', id=nid, lon=str(lon), lat=str(lat))
            x, y = transform.transform(lon, lat)
            ET.SubElement(nodes, 'node', id=nid, x=str(x), y=str(y))
        way = ET.SubElement(osm, 'way', id='123')
        for nid in ('a', 'b'):
            ET.SubElement(way, 'nd', ref=nid)
        for key, value in [('highway', 'residential'), ('oneway', 'yes')]:
            ET.SubElement(way, 'tag', k=key, v=value)
        ET.SubElement(links, 'link', id='ab', **{'from': 'a', 'to': 'b', 'origid': '123',
                      'modes': 'car', 'length': '11.1', 'freespeed': '3', 'capacity': '100', 'permlanes': '1'})
        config = ET.Element('config')
        for module, values in [('qsim', {'useLanes': 'true'}), ('global', {'coordinateSystem': 'EPSG:32615'}),
                               ('controler', {'enableLinkToLinkRouting': 'true'}),
                               ('network', {'inputNetworkFile': 'network.xml', 'laneDefinitionsFile': 'lanes.xml'})]:
            block = ET.SubElement(config, 'module', name=module)
            for key, value in values.items():
                ET.SubElement(block, 'param', name=key, value=value)
        for name, root in [('map.osm', osm), ('network.xml', network), ('lanes.xml', ET.Element('laneDefinitions')),
                           ('config-simz1.xml', config)]:
            (directory/name).write_bytes(ET.tostring(root))
        return directory/'map.osm', directory/'network.xml', directory/'lanes.xml', directory/'config-simz1.xml'

    def test_path_restriction_requires_complete_contiguous_history(self):
        restriction = dict(relation_id='7', semantics_review='', restriction='no_u_turn',
                           status='via_way_unsupported', path_status='mapped',
                           directed_sequences=json.dumps([['in', 'via', 'out']]))
        routes = [dict(links=path) for path in [['in','via','out'], ['elsewhere','via','out'],
                                                ['in','detour','via','out'], []]]
        before = deepcopy(routes)
        result = route_restriction_exposure(routes, {'rows':[restriction]})
        self.assertEqual([len(r['mapped_prohibition_occurrences']) for r in result], [1,0,0,0])
        self.assertTrue(all(r['legally_certified'] is False for r in result))
        self.assertEqual(routes, before)

    def test_node_prohibitions_and_unresolved_semantics_are_not_confused(self):
        row = dict(relation_id='8', semantics_review='', restriction='no_left_turn',
                   status='mappable', admitting_movements='a>b')
        other = {**row, 'relation_id':'9', 'semantics_review':'conditional'}
        result = route_restriction_exposure([dict(links=['a','b','a','b'])], {'rows':[row,other]})[0]
        self.assertEqual([r['offset'] for r in result['mapped_prohibition_occurrences']], [0,2])
        self.assertEqual({r['relation_id'] for r in result['mapped_prohibition_occurrences']}, {'8'})
        self.assertFalse(result['legally_certified'])

    def test_native_xml_format_does_not_change_topology_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            raw = b'''<network><nodes><node id="a" x="1" y="2"/><node id="b" x="2" y="2"/></nodes>
              <links><link id="L" from="a" to="b" origid="123" modes="car" length="1"
                freespeed="3" capacity="100" permlanes="1"/></links></network>'''
            base, native = folder/'network.xml', folder/'native.xml.gz'
            base.write_bytes(raw)
            native.write_bytes(gzip.compress(raw.replace(b' origid="123"', b'').replace(b'permlanes="1"/>',
                b'permlanes="1"><attributes><attribute name="origid">123</attribute></attributes></link>')))
            self.assertEqual(topology_signature(base), topology_signature(native))

    def test_strict_blockers_and_existing_output_cannot_modify_a_run(self):
        report = dict(preflight=dict(status='blocked', blockers=['OSM_pending']),
                      base={'summary':{}}, restrictions={'summary':{'statuses':{}}})
        with tempfile.TemporaryDirectory() as folder, patch('inspect_simz1_connectivity.inspect', return_value=report) as inspect:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--strict']), 2)
                self.assertEqual(main([]), 0)
                target = Path(folder)/'new-evidence'
                self.assertEqual(main(['--strict','--output-new',str(target)]), 2)
            self.assertEqual({p.name for p in target.iterdir()}, {'connectivity-inspection.json'})
            saved = (target/'connectivity-inspection.json').read_bytes()
            inspect.reset_mock()
            with self.assertRaisesRegex(ValueError,'carpeta nueva'):
                main(['--output-new',str(target)])
            inspect.assert_not_called()
            self.assertEqual((target/'connectivity-inspection.json').read_bytes(), saved)

    def test_configuration_is_effective_and_rejects_substituted_artifacts_before_graph(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            _, network, lanes, config = self.fixture(folder)
            self.assertEqual(checked_configuration(config, network, lanes)['status'],
                             'configured_lane_graph_and_EPSG32615_verified')
            original = config.read_bytes()
            for module, key, value in [('qsim', 'useLanes', 'false'), ('global', 'coordinateSystem', 'EPSG:4326'),
                                       ('controler', 'enableLinkToLinkRouting', 'false'),
                                       ('network', 'inputNetworkFile', 'other.xml'),
                                       ('network', 'laneDefinitionsFile', 'other-lanes.xml')]:
                with self.subTest(key=key):
                    root = ET.fromstring(original)
                    root.find(f"module[@name='{module}']/param[@name='{key}']").set('value', value)
                    config.write_bytes(ET.tostring(root))
                    (folder/'other.xml').write_bytes(network.read_bytes())
                    (folder/'other-lanes.xml').write_bytes(lanes.read_bytes())
                    with patch('inspect_simz1_connectivity.analyze') as analyze:
                        with self.assertRaisesRegex(ValueError, 'Unsupported configuration|Effective artifact mismatch'):
                            inspect(folder)
                        analyze.assert_not_called()

    def test_source_geometry_detects_shift_nonfinite_positions_and_incomplete_highways(self):
        with tempfile.TemporaryDirectory() as folder:
            osm, network, _, _ = self.fixture(Path(folder))
            self.assertTrue(source_geometry_check(osm, network)['valid'])
            original = network.read_bytes()
            for value, reason in [('nan', 'invalid_source_or_network_coordinates'),
                                   (str(float(ET.fromstring(original).find('nodes/node').get('x')) + .01),
                                    'network_position_differs_from_OSM')]:
                with self.subTest(value=value):
                    root = ET.fromstring(original)
                    root.find('nodes/node').set('x', value)
                    network.write_bytes(ET.tostring(root))
                    result = source_geometry_check(osm, network)
                    self.assertFalse(result['valid'])
                    self.assertEqual(result['node_issues'][0]['reason'], reason)
            network.write_bytes(original)
            root = ET.parse(osm)
            ET.SubElement(root.getroot().find('way'), 'nd', ref='missing-source-node')
            root.write(osm)
            result = source_geometry_check(osm, network)
            self.assertFalse(result['valid'])
            self.assertEqual(result['missing_highway_node_references'],
                             [dict(way_id='123', node_id='missing-source-node')])
            self.assertIn('source_node_geometry_or_references_mismatch', inspect(Path(folder))['preflight']['blockers'])

    def test_missing_empty_and_limited_witnesses_block_strict_inspection(self):
        self.assertEqual(witness_blockers([]), ['witness_routes_empty'])
        self.assertEqual(witness_blockers([dict(status='search_limit')]), ['witness_search_incomplete'])
        self.assertEqual(witness_blockers([dict(status='configured_path'), dict(status='no_configured_path')]), [])
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fixture(folder)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['--scenario', str(folder), '--strict']), 2)
            report = json.loads(output.getvalue())
            self.assertIn('witness_network_endpoint_missing', report['preflight']['blockers'])
            with patch('inspect_simz1_connectivity.analyze', return_value={**report['base'], 'witness_routes': []}):
                self.assertIn('witness_routes_empty', inspect(folder)['preflight']['blockers'])

    def test_historical_config_input_and_native_gzip_lanes_are_distinct_hashed_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            _, network, lanes, config = self.fixture(folder)
            native_network, native_lanes = folder/'output_network.xml.gz', folder/'output_lanes.xml.gz'
            native_network.write_bytes(gzip.compress(network.read_bytes()))
            native_lanes.write_bytes(gzip.compress(lanes.read_bytes()))
            record = lambda path: dict(path=path.name, sha256=digest(path))
            manifest = dict(run_id='test-historical', status='completed', validation=dict(status='valid'),
                            inputs={'network': record(network), 'input:network-laneDefinitionsFile.xml': record(lanes)},
                            effective_config=record(config), results={'0': {'network': record(native_network)}},
                            effective_lane_configuration_validation={'loaded_artifacts': {
                                'network': record(native_network), 'lanes': record(native_lanes)}})
            (folder/'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch('inspect_simz1_connectivity.subprocess.run', return_value=SimpleNamespace(stdout='{}')):
                report = inspect(folder, folder)
            configuration = report['historical']['configuration']
            self.assertEqual(configuration['resolved_artifacts']['network.laneDefinitionsFile'], str(lanes.resolve()))
            self.assertEqual(configuration['loaded_lane_artifact'], str(native_lanes.resolve()))
            self.assertTrue(configuration['input_output_lane_movements_equal'])
            self.assertTrue(report['historical']['normalized_network_equal'])
            self.assertTrue(report['preservation']['inputs_unchanged'])


if __name__ == '__main__':
    unittest.main()
