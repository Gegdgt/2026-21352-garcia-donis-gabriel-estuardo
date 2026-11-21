import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_osm_turn_audit import audit, inspect_restrictions, load_lanes, source_way_id


class OsmTurnAuditTest(unittest.TestCase):
    def test_native_gzip_and_nested_origids_preserve_node_and_way_restrictions(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = self.via_fixture(Path(folder))
            root = ET.parse(inputs[0]).getroot()
            root.append(ET.fromstring('''<relation id="8"><member type="way" ref="10" role="from"/>
                <member type="node" ref="b" role="via"/><member type="way" ref="20" role="to"/>
                <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>'''))
            inputs[0].write_bytes(ET.tostring(root))
            expected = inspect_restrictions(*inputs)
            native = ET.parse(inputs[1]).getroot()
            native.set('xmlns', 'urn:native-fixture')
            for link in native.findall('links/link'):
                way = link.attrib.pop('origid')
                ET.SubElement(ET.SubElement(link, 'attributes'), 'attribute', name='origid').text = way
            network, lanes = (Path(folder)/name for name in ('output_network.xml.gz', 'output_lanes.xml.gz'))
            network.write_bytes(gzip.compress(ET.tostring(native)))
            lanes.write_bytes(gzip.compress(inputs[2].read_bytes()))
            before = {p:p.read_bytes() for p in (network, lanes)}
            actual = inspect_restrictions(inputs[0], network, lanes)
            self.assertEqual(actual['rows'], expected['rows'])
            self.assertEqual(actual['summary']['mappable_lanes_admit'], 1)
            self.assertEqual(actual['summary']['via_way_lanes_admit'], 1)
            self.assertEqual(before, {p:p.read_bytes() for p in (network, lanes)})
            self.assertIsNone(source_way_id(ET.fromstring('<link id="osm_123_0_forward"/>')),
                              'An ID prefix alone must not manufacture source provenance')

    def via_fixture(self, folder, *, reverse=False, exclude=False, extra_tags=''):
        osm, network, lanes = [folder / name for name in ('map.osm', 'network.xml', 'lanes.xml')]
        osm.write_text('''<osm>
          <node id="a"/><node id="b"/><node id="c"/><node id="d"/><node id="e"/><node id="f"/>
          <way id="10"><nd ref="a"/><nd ref="b"/></way>
          <way id="20"><nd ref="b"/><nd ref="c"/><nd ref="d"/></way>
          <way id="30"><nd ref="d"/><nd ref="e"/></way>
          <way id="40"><nd ref="e"/><nd ref="f"/></way>
          <relation id="7"><member type="way" ref="10" role="from"/>
            <member type="way" ref="20" role="via"/><member type="way" ref="30" role="via"/>
            <member type="way" ref="40" role="to"/><tag k="type" v="restriction"/>
            <tag k="restriction" v="no_u_turn"/>''' + extra_tags + '</relation></osm>')
        network.write_text('''<network><nodes><node id="a"/><node id="b"/><node id="c"/>
          <node id="d"/><node id="e"/><node id="f"/></nodes><links>
          <link id="in" from="a" to="b" origid="10" modes="car"/>
          <link id="v1" from="b" to="c" origid="20" modes="car"/>
          <link id="v2" from="c" to="d" origid="20" modes="car"/>
          <link id="v3" from="''' + ('e" to="d' if reverse else 'd" to="e') + '''" origid="30" modes="car"/>
          <link id="out" from="e" to="f" origid="40" modes="car"/>
          <link id="alternative" from="e" to="a" origid="50" modes="car"/>
          </links></network>''')
        lanes.write_text('''<laneDefinitions><lanesToLinkAssignment linkIdRef="v3">
          <lane id="v3.terminal"><leadsTo><toLink refId="''' + ('alternative' if exclude else 'out') + '''"/>
          </leadsTo></lane></lanesToLinkAssignment></laneDefinitions>''')
        return osm, network, lanes

    def test_pure_inspection_keeps_ordered_multi_way_sequence_and_lane_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            inputs = self.via_fixture(folder)
            before = {path: path.read_bytes() for path in inputs}
            result = inspect_restrictions(*inputs)
            row = result['rows'][0]
            self.assertEqual(row['status'], 'via_way_unsupported')
            self.assertEqual(row['path_status'], 'mapped')
            self.assertEqual(json.loads(row['directed_sequences']), [['in', 'v1', 'v2', 'v3', 'out']])
            checks = json.loads(row['sequence_lane_checks'])[0]
            self.assertEqual(len(checks), 4)
            self.assertEqual(checks[-1]['terminal_lanes'], ['v3.terminal'])
            self.assertEqual(row['lanes_admit_sequence'], 'true')
            # A sequence is evidence, never flattened into a global v3>out ban.
            self.assertEqual(row['lanes_admit_prohibited_target'], 'not_evaluated')
            self.assertEqual(row['admitting_movements'], '')
            self.assertEqual(json.loads(row['missing_members']), [])
            self.assertEqual(set(folder.iterdir()), set(inputs))
            self.assertEqual(before, {path: path.read_bytes() for path in inputs})

    def test_via_way_direction_and_lane_exclusion_remain_distinct(self):
        for reverse, exclude, status, admission in (
                (True, False, 'no_directed_path', 'not_evaluated'),
                (False, True, 'mapped', 'false')):
            with self.subTest(reverse=reverse, exclude=exclude), tempfile.TemporaryDirectory() as folder:
                inputs = self.via_fixture(Path(folder), reverse=reverse, exclude=exclude)
                row = inspect_restrictions(*inputs)['rows'][0]
                self.assertEqual(row['path_status'], status)
                self.assertEqual(row['lanes_admit_sequence'], admission)

    def test_missing_conditional_and_exception_members_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = self.via_fixture(Path(folder), extra_tags='''<tag k="except" v="bus"/>
                <tag k="restriction:conditional" v="no_u_turn @ (Mo-Fr 07:00-09:00)"/>''')
            inputs[0].write_text(inputs[0].read_text().replace('<way id="30">', '<way id="300">'))
            result = inspect_restrictions(*inputs)
            row = result['rows'][0]
            self.assertEqual(row['path_status'], 'missing_osm_members')
            self.assertEqual(json.loads(row['missing_members']), [dict(type='way', ref='30', role='via')])
            self.assertEqual(row['semantics_review'], 'mode_exceptions;conditional')
            self.assertEqual(result['summary']['relations_with_missing_members'], 1)

    def test_deleted_relations_are_not_active_restrictions(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = self.via_fixture(Path(folder))
            inputs[0].write_text(inputs[0].read_text().replace('<relation id="7">', '<relation id="7" action="delete">'))
            result = inspect_restrictions(*inputs)
            self.assertEqual(result['rows'], [])
            self.assertEqual(result['summary']['deleted_relations_ignored'], 1)

    def test_direction_and_lane_reachability_detect_gap_without_changing_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            osm, network, lanes = [folder / name for name in ('map.osm', 'network.xml', 'lanes.xml')]
            osm.write_text('''<osm>
              <relation id="1"><member type="way" ref="10" role="from"/><member type="node" ref="j" role="via"/>
                <member type="way" ref="20" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>
              <relation id="2"><member type="way" ref="10" role="from"/><member type="node" ref="j" role="via"/>
                <member type="way" ref="30" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_right_turn"/></relation>
              <relation id="3"><member type="way" ref="10" role="from"/><member type="way" ref="99" role="via"/>
                <member type="way" ref="20" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_u_turn"/></relation>
              <relation id="4"><member type="way" ref="20" role="to"/><tag k="type" v="restriction"/></relation>
              <relation id="5"><member type="way" ref="99" role="from"/><member type="node" ref="j" role="via"/>
                <member type="way" ref="20" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>
              </osm>''')
            network.write_text('''<network><nodes><node id="a"/><node id="j"/><node id="b"/><node id="c"/></nodes><links>
              <link id="in" from="a" to="j" origid="10" modes="car"/>
              <link id="reverse" from="j" to="a" origid="10" modes="car"/>
              <link id="left" from="j" to="b" origid="20" modes="car"/>
              <link id="right" from="j" to="c" origid="30" modes="car"/>
              </links></network>''')
            lanes.write_text('''<laneDefinitions xmlns="urn:test"><lanesToLinkAssignment linkIdRef="in">
              <lane id="original"><leadsTo><toLane refId="terminal"/></leadsTo></lane>
              <lane id="terminal"><leadsTo><toLink refId="left"/></leadsTo></lane>
              </lanesToLinkAssignment></laneDefinitions>''')
            before = {path: path.read_bytes() for path in (osm, network, lanes)}
            summary = audit(osm, network, lanes, folder / 'reports')
            self.assertEqual(summary['statuses'], dict(mappable=2, via_way_unsupported=1,
                incomplete_or_unsupported_members=1, not_in_network=1))
            self.assertEqual((summary['mappable_lanes_admit'], summary['mappable_lanes_exclude']), (1, 1))
            with (folder / 'reports/osm-turn-restrictions.csv').open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['from_links'], 'in')
            self.assertEqual(rows[0]['admitting_movements'], 'in>left')
            self.assertEqual(rows[0]['admitting_terminal_lanes'], 'terminal')
            for path, data in before.items():
                self.assertEqual(path.read_bytes(), data)

    def test_lane_audit_rejects_disconnected_graph(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lanes.xml'
            path.write_text('''<laneDefinitions><lanesToLinkAssignment linkIdRef="in">
              <lane id="one"><leadsTo><toLink refId="out"/></leadsTo></lane>
              <lane id="unreachable"><leadsTo><toLink refId="out"/></leadsTo></lane>
              </lanesToLinkAssignment></laneDefinitions>''')
            with self.assertRaisesRegex(ValueError, 'single lane entry'):
                load_lanes(path)


if __name__ == '__main__':
    unittest.main()
