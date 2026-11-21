"""Small synthetic metadata checks; no events, populations, exports or QSim."""
import copy
from pathlib import Path
import unittest
from unittest.mock import call, patch
import xml.etree.ElementTree as ET

from simz1_visual_lanes import load_visual_lanes, visual_lane_metadata, visual_landmarks


class VisualLanesTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(run_id='visual-lanes-fixture', iteration=0, run_manifest_sha256='native-hash')

    def network(self, count=2, opposite=None, *, origin_as_metadata=False):
        root = ET.fromstring('''<network><nodes>
          <node id="a" x="-90.5" y="14.6"/><node id="b" x="-90.49" y="14.6"/>
          <node id="c" x="-90.48" y="14.6"/></nodes><links/></network>''')
        links = root.find('links')
        forward = ET.SubElement(links, 'link', id='forward', **{'from': 'a', 'to': 'b'},
                                length='100', permlanes=str(count), modes='car')
        ET.SubElement(links, 'link', id='exit', **{'from': 'b', 'to': 'c'}, length='100', permlanes='1')
        records = [forward]
        if opposite is not None:
            records.append(ET.SubElement(links, 'link', id='reverse', **{'from': 'b', 'to': 'a'},
                                         length='100', permlanes=str(opposite), modes='car'))
        for record in records:
            if origin_as_metadata:
                self.attribute(record, 'origid', 'way-1')
            else:
                record.set('origid', 'way-1')
        return root

    def attribute(self, record, name, value):
        parent = record.find('attributes')
        if parent is None:
            parent = ET.SubElement(record, 'attributes')
        ET.SubElement(parent, 'attribute', name=name).text = value

    def lanes(self, count):
        root = ET.Element('laneDefinitions')
        assignment = ET.SubElement(root, 'lanesToLinkAssignment', linkIdRef='forward')
        for index in range(count):
            lane = ET.SubElement(assignment, 'lane', id=f'queue-{count-index}')
            ET.SubElement(lane, 'startsAt', meterFromLinkEnd='80')
            ET.SubElement(lane, 'representedLanes', number='1')
            ET.SubElement(lane, 'alignment').text = str(2*index-(count-1))
            ET.SubElement(ET.SubElement(lane, 'leadsTo'), 'toLink', refId='exit')
        original = ET.SubElement(assignment, 'lane', id='shared-upstream')
        ET.SubElement(original, 'startsAt', meterFromLinkEnd='100')
        ET.SubElement(original, 'representedLanes', number=str(count))
        ET.SubElement(original, 'alignment').text = '0'
        leads = ET.SubElement(original, 'leadsTo')
        for index in range(count):
            ET.SubElement(leads, 'toLane', refId=f'queue-{count-index}')
        return root

    def metadata(self, network, lanes=None):
        return visual_lane_metadata(network, lanes, lambda x, y: (x, y), self.identity)

    def test_names_come_from_osm_and_landmarks_use_only_recorded_nodes(self):
        network = self.network()
        self.attribute(network.find('links/link'), 'osm:name', '7a Avenida')
        before = ET.tostring(network)
        metadata = self.metadata(network)
        self.assertEqual(metadata['links']['forward']['osm_tags']['name'], '7a Avenida')
        self.assertNotIn('name', metadata['links']['exit']['osm_tags'])
        self.assertEqual(before, ET.tostring(network))
        facilities = ET.Element('facilities')
        for ident, name, x in [('osm_node_1', 'Museo de prueba', '-90.5'),
                               ('osm_way_2', 'Palacio de prueba', '-90.51'),
                               ('osm_node_3', 'Hospital de prueba', 'nan'),
                               ('smoke_home', 'Parque de prueba', '-90.52'),
                               ('osm_node_4', 'Parqueo de prueba', '-90.53')]:
            row = ET.SubElement(facilities, 'facility', id=ident, x=x, y='14.6')
            self.attribute(row, 'name', name)
            self.attribute(row, 'source', 'OSM activity proxy; opening hours/capacity not inferred')
        original = ET.tostring(facilities)
        landmarks = visual_landmarks(facilities, lambda x, y: (x, y))
        self.assertEqual(landmarks, [dict(id='osm_node_1', name='Museo de prueba',
                                         position=[-90.5, 14.6], source='recorded_osm_node')])
        self.assertEqual(original, ET.tostring(facilities))
        self.assertEqual(visual_landmarks(ET.Element('facilities'), lambda x, y: (x, y)), [])

    def test_one_two_three_lanes_keep_directional_counts_and_alignment_order(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                result = self.metadata(self.network(count), self.lanes(count))
                link = result['links']['forward']
                self.assertEqual(link['num_lanes'], count)
                self.assertTrue(link['offset_eligible'])
                self.assertEqual(link['geometry_source'], 'effective_link_chord')
                self.assertEqual(link['lane_width_m'], 3)
                self.assertIsNone(link['native_lanes']['shared-upstream']['index'])
                self.assertEqual(link['native_lanes']['shared-upstream']['represented_lanes'], count)
                self.assertEqual(link['native_lanes'][f'queue-{count}']['index'], 0)
                self.assertEqual(link['native_lanes']['queue-1']['index'], count-1)
                self.assertEqual(link['native_lanes']['queue-1']['start_m'], 80)
                self.assertEqual(result['start_reference'], 'link_end')

    def test_reverse_links_use_effective_orig_id_without_doubling_lanes(self):
        result = self.metadata(self.network(2, 1, origin_as_metadata=True))
        forward, reverse = result['links']['forward'], result['links']['reverse']
        self.assertEqual((forward['num_lanes'], forward['opposing_lanes']), (2, 1))
        self.assertEqual((reverse['num_lanes'], reverse['opposing_lanes']), (1, 2))
        self.assertEqual(forward['reverse_link'], 'reverse')
        self.assertEqual(reverse['path'], list(reversed(forward['path'])))

    def test_effective_count_wins_over_osm_totals_and_preserves_missing_evidence(self):
        network = self.network(2, 1)
        for record in network.findall('links/link'):
            if record.get('id') not in ('forward', 'reverse'):
                continue
            self.attribute(record, 'osm:oneway', 'no')
            self.attribute(record, 'osm:lanes', '3')
            self.attribute(record, 'osm:lanes:forward', '2')
            self.attribute(record, 'osm:lanes:backward', '1')
        before = ET.tostring(network)
        result = self.metadata(network)['links']
        self.assertEqual((result['forward']['num_lanes'], result['reverse']['num_lanes']), (2, 1))
        self.assertEqual(result['forward']['lane_count_source'], 'effective_network_permlanes')
        self.assertEqual(result['forward']['osm_tags']['lanes'], '3')
        self.assertIn('layer', result['forward']['missing_osm_tags'])
        self.assertNotIn('layer', result['forward']['osm_tags'])
        self.assertEqual(ET.tostring(network), before)

    def test_non_car_reverse_does_not_disable_one_way_lanes(self):
        network = self.network(2, 1)
        network.find("links/link[@id='reverse']").set('modes', 'walk,bike')
        forward = network.find("links/link[@id='forward']")
        self.attribute(forward, 'osm:oneway', 'yes')
        result = self.metadata(network)['links']
        self.assertNotIn('reverse', result)
        self.assertEqual(result['forward']['num_lanes'], 2)
        self.assertEqual(result['forward']['opposing_lanes'], 0)
        self.assertTrue(result['forward']['offset_eligible'])

    def test_separate_carriageways_keep_their_own_axis(self):
        network = self.network(2, 2)
        for ident, x in (('d', '-90.5'), ('e', '-90.49')):
            ET.SubElement(network.find('nodes'), 'node', id=ident, x=x, y='14.6001')
        reverse = network.find("links/link[@id='reverse']")
        reverse.set('from', 'e'); reverse.set('to', 'd'); reverse.set('origid', 'way-2')
        result = self.metadata(network)['links']
        for ident in ('forward', 'reverse'):
            self.assertTrue(result[ident]['offset_eligible'])
            self.assertEqual(result[ident]['num_lanes'], 2)
            self.assertEqual(result[ident]['opposing_lanes'], 0)
            self.assertIsNone(result[ident]['reverse_link'])
        self.assertNotEqual(result['forward']['path'], list(reversed(result['reverse']['path'])))

    def test_lane_specific_turns_retain_membership_without_extra_lanes(self):
        network, lanes = self.network(2), self.lanes(2)
        ET.SubElement(network.find('links'), 'link', id='other-exit', **{'from': 'b', 'to': 'c'},
                      length='100', permlanes='1', modes='car')
        lanes.find(".//lane[@id='queue-1']/leadsTo/toLink").set('refId', 'other-exit')
        before = (ET.tostring(network), ET.tostring(lanes))
        link = self.metadata(network, lanes)['links']['forward']
        self.assertEqual(link['num_lanes'], 2)  # shared upstream is not a third lane
        self.assertEqual(link['native_lanes']['queue-2']['index'], 0)
        self.assertEqual(link['native_lanes']['queue-2']['to_links'], ['exit'])
        self.assertEqual(link['native_lanes']['queue-1']['to_links'], ['other-exit'])
        self.assertEqual(link['allowed_to_links'], ['exit', 'other-exit'])
        self.assertEqual(link['movement_source'], 'effective_lane_definitions')
        self.assertEqual((ET.tostring(network), ET.tostring(lanes)), before)
        network.find("links/link[@id='other-exit']").set('modes', 'walk')
        self.assertEqual(self.metadata(network, lanes)['links']['forward']['native_lanes'], {})

    def test_movement_metadata_uses_topology_and_never_fills_invalid_lane_permissions(self):
        network = self.network(2)
        ET.SubElement(network.find('links'), 'link', id='pedestrian', **{'from': 'b', 'to': 'c'},
                      length='100', permlanes='1', modes='walk')
        link = self.metadata(network)['links']['forward']
        self.assertEqual(link['source_way'], 'way-1')
        self.assertEqual(link['allowed_to_links'], ['exit'])
        self.assertEqual(link['movement_source'], 'effective_car_node_adjacency')
        lanes = self.lanes(2)
        lanes.find('lanesToLinkAssignment/lane/alignment').text = '0'
        link = self.metadata(network, lanes)['links']['forward']
        self.assertIsNone(link['allowed_to_links'])
        self.assertEqual(link['movement_source'], 'unavailable_lane_mapping')

    def test_grade_crossing_preserves_node_ids_without_visual_connection(self):
        network = self.network(1)
        nodes = network.find('nodes')
        for ident, x, y in [('d', '-90.495', '14.595'), ('e', '-90.495', '14.605')]:
            ET.SubElement(nodes, 'node', id=ident, x=x, y=y)
        lower = ET.SubElement(network.find('links'), 'link', id='lower', **{'from': 'd', 'to': 'e'},
                              length='100', permlanes='1', modes='car', origid='lower-way')
        upper = network.find("links/link[@id='forward']")
        self.attribute(upper, 'osm:bridge', 'yes'); self.attribute(upper, 'osm:layer', '1')
        self.attribute(lower, 'osm:tunnel', 'yes'); self.attribute(lower, 'osm:layer', '-1')
        links = self.metadata(network)['links']
        self.assertEqual(set(links), {'forward', 'exit', 'lower'})
        self.assertEqual(links['forward']['osm_tags']['layer'], '1')
        self.assertEqual(links['lower']['osm_tags']['layer'], '-1')
        self.assertTrue({links['forward'][k] for k in ('from_node', 'to_node')}.isdisjoint(
            {links['lower'][k] for k in ('from_node', 'to_node')}))
        self.assertIsNone(links['lower']['reverse_link'])

    def test_incompatible_levels_never_pair_even_with_coincident_geometry(self):
        network = self.network(1, 1)
        self.attribute(network.find("links/link[@id='forward']"), 'osm:layer', '1')
        self.attribute(network.find("links/link[@id='reverse']"), 'osm:layer', '-1')
        result = self.metadata(network)
        for ident in ('forward', 'reverse'):
            self.assertIsNone(result['links'][ident]['reverse_link'])
            self.assertFalse(result['links'][ident]['offset_eligible'])
            self.assertEqual(result['links'][ident]['opposing_lanes'], 0)
        network.find('links')[:] = list(reversed(list(network.find('links'))))
        self.assertEqual(self.metadata(network), result)

    def test_unknown_fractional_count_and_ambiguous_reverse_retain_centreline_only(self):
        network = self.network('1.5')
        link = self.metadata(network)['links']['forward']
        self.assertIsNone(link['num_lanes'])
        self.assertFalse(link['offset_eligible'])
        self.assertEqual(len(link['path']), 2)
        network = self.network(2, 1)
        duplicate = copy.deepcopy(network.find("links/link[@id='reverse']"))
        duplicate.set('id', 'ambiguous-reverse')
        network.find('links').append(duplicate)
        result = self.metadata(network)
        self.assertFalse(result['links']['forward']['offset_eligible'])
        self.assertFalse(result['links']['reverse']['offset_eligible'])
        self.assertIsNone(result['links']['forward']['reverse_link'])

    def test_native_alignment_and_upstream_graph_are_required_no_suffix_guess(self):
        for field, value in (('alignment', '0'), ('representedLanes', '2'), ('startsAt', '100')):
            lanes = self.lanes(2)
            first = lanes.find('lanesToLinkAssignment/lane')
            first.set('id', 'forward.lane.0')
            # Fix the graph reference: the misleading suffix itself proves nothing.
            lanes.find(".//toLane[@refId='queue-2']").set('refId', 'forward.lane.0')
            element = first.find(field)
            if field == 'alignment':
                element.text = value
            else:
                element.set('number' if field == 'representedLanes' else 'meterFromLinkEnd', value)
            with self.subTest(field=field):
                self.assertEqual(self.metadata(self.network(), lanes)['links']['forward']['native_lanes'], {})

    def test_effective_curves_and_road_width_keep_provenance(self):
        network = self.network(2, 1)
        forward = network.find("links/link[@id='forward']")
        self.attribute(forward, 'origgeom', 'mid,-90.495,14.601')
        self.attribute(network.find("links/link[@id='reverse']"), 'origgeom', 'mid,-90.495,14.601')
        for record in network.findall('links/link'):
            self.attribute(record, 'osm:width', '9 m')
        link = self.metadata(network)['links']['forward']
        self.assertEqual(len(link['path']), 3)
        self.assertEqual(link['geometry_source'], 'effective_origgeom')
        self.assertEqual(link['lane_width_m'], 3)
        self.assertEqual(link['width_source'], 'osm:width_per_directional_lane')
        forward.find("attributes/attribute[@name='origgeom']").text = 'mid,nan,14.6'
        link = self.metadata(network)['links']['forward']
        self.assertFalse(link['offset_eligible'])
        self.assertEqual(link['geometry_source'], 'effective_link_chord_invalid_geometry')

    def test_paired_width_missing_or_conflicting_and_unpaired_curve_fail_closed(self):
        network = self.network(2, 1)
        forward = network.find("links/link[@id='forward']")
        reverse = network.find("links/link[@id='reverse']")
        self.attribute(forward, 'osm:width', '6 m')
        result = self.metadata(network)
        self.assertEqual(result['links']['forward']['lane_width_m'], 2)
        self.assertEqual(result['links']['reverse']['lane_width_m'], 2)
        self.attribute(reverse, 'osm:width', '9 m')
        result = self.metadata(network)
        for ident in ('forward', 'reverse'):
            self.assertEqual(result['links'][ident]['lane_width_m'], 2)
            self.assertEqual(result['links'][ident]['width_source'], 'osm:width_conservative_conflict')
        self.attribute(forward, 'origgeom', 'mid,-90.495,14.601')
        result = self.metadata(network)
        self.assertFalse(result['links']['forward']['offset_eligible'])
        self.assertFalse(result['links']['reverse']['offset_eligible'])

    def test_invalid_transform_disables_metadata_without_inventing_positions(self):
        def invalid(x, y):
            raise ValueError('coordinate transform unavailable')
        for transform in (invalid, lambda x, y: (float('nan'), y), lambda x, y: None):
            result = visual_lane_metadata(self.network(), None, transform, self.identity)
            self.assertFalse(result['available'])
            self.assertEqual(result['links'], {})

    def test_effective_artifacts_are_hashed_missing_or_changed_metadata_disables_offsets(self):
        folder = Path('synthetic-visual-lanes').resolve()
        config_record = dict(path='effective.xml', sha256='validated-config-hash')
        network_record = dict(path='effective-network.xml', sha256='validated-network-hash')
        effective = {'global.coordinateSystem': 'EPSG:32615', 'qsim.useLanes': 'false'}
        network = self.network(2)
        for index, node in enumerate(network.findall('nodes/node')):
            node.set('x', str(770000+index*100))
            node.set('y', '1610000')
        run = dict(run_id=self.identity['run_id'], status='completed', validation=dict(status='valid'),
                   effective_config=config_record, results={'0': dict(network=network_record)})
        # Exercise integration with the repository's hash-checking gate in memory.
        # No test file/directory is created, overwritten or automatically deleted.
        with patch('simz1_run.checked_path', side_effect=lambda directory, record: directory / record['path']) as checked, \
                patch('simz1_run.parameters', return_value=effective), \
                patch('simz1_visual_lanes._xml', return_value=network):
            self.assertTrue(load_visual_lanes(folder, run, self.identity)['available'])
            self.assertEqual(checked.call_args_list, [call(folder, config_record), call(folder, network_record)])
            checked.side_effect = ValueError('Hash no coincide; archivo cambiado')
            metadata = load_visual_lanes(folder, run, self.identity)
            self.assertFalse(metadata['available'])
            self.assertEqual(metadata['links'], {})
            run.pop('effective_config')
            self.assertFalse(load_visual_lanes(folder, run, self.identity)['available'])


if __name__ == '__main__':
    unittest.main()
