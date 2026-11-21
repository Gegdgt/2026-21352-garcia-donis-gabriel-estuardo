"""Prepared synthetic revision tests; no network/population generation or MATSim."""
import json
from pathlib import Path
import tempfile
import unittest

from prepare_simz1_connectivity_revision import build_revision, write_new_proposal


class ConnectivityRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1-connectivity-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenario = self.root / 'inputs'
        self.scenario.mkdir()
        files = {
            'map.osm': '''<osm><node id="1" lat="0" lon="0"/><node id="2" lat="0" lon="1"/>
              <node id="3" lat="0" lon="2"/><node id="4" lat="1" lon="1"/>
              <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
              <way id="20"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way>
              <way id="30"><nd ref="2"/><nd ref="4"/><tag k="highway" v="residential"/></way>
              <relation id="100"><member type="way" role="from" ref="10"/>
                <member type="node" role="via" ref="2"/><member type="way" role="to" ref="20"/>
                <tag k="type" v="restriction"/><tag k="restriction" v="no_right_turn"/></relation></osm>''',
            'network.xml': '''<network><nodes><node id="1"/><node id="2"/><node id="3"/><node id="4"/></nodes>
              <links><link id="F" from="1" to="2" origid="10" modes="car"/>
                <link id="T" from="2" to="3" origid="20" modes="car"/>
                <link id="A" from="2" to="4" origid="30" modes="car"/></links></network>''',
            'lanes.xml': '''<laneDefinitions><lanesToLinkAssignment linkIdRef="F">
              <lane id="F.original"><leadsTo><toLane refId="F.lane.0"/></leadsTo></lane>
              <lane id="F.lane.0"><leadsTo><toLink refId="T"/><toLink refId="A"/></leadsTo>
                <capacity vehiclesPerHour="2000"/><representedLanes number="1"/>
                <startsAt meterFromLinkEnd="8"/></lane></lanesToLinkAssignment></laneDefinitions>''',
            'signalSystems.xml': '''<signalSystems><signalSystem id="system"><signals>
              <signal id="signal" linkIdRef="F"><lane refId="F.lane.0"/></signal>
              </signals></signalSystem></signalSystems>''',
            'signalGroups.xml': '<signalGroups/>', 'signalControl.xml': '<signalControl/>',
            'config-simz1.xml': '<config/>'}
        for name, text in files.items():
            (self.scenario / name).write_text(text, encoding='utf-8')

    def test_proposal_preserves_inputs_ids_signal_references_and_four_od_cases(self):
        before = {p.name: p.read_bytes() for p in self.scenario.iterdir()}
        revision, patch = build_revision(self.scenario)
        self.assertEqual({p.name: p.read_bytes() for p in self.scenario.iterdir()}, before)
        self.assertEqual(revision['status'], 'review_only_blocked')
        self.assertFalse(revision['runnable'])
        self.assertFalse(patch['apply_allowed'])
        self.assertEqual(revision['unique_via_node_relations'], ['100'])
        self.assertEqual(revision['physical_network_changes'], [])
        self.assertEqual(patch['operations'][0]['expected_targets'], ['A', 'T'])
        self.assertEqual(patch['operations'][0]['proposed_targets'], ['A'])
        self.assertEqual(patch['combined_lane_targets'][0]['final_targets'], ['A'])
        self.assertEqual(revision['id_correspondence']['modified_lane_ids'],
                         [dict(old='F.lane.0', new='F.lane.0', link_id='F')])
        self.assertTrue(revision['compatibility']['signal_references'][0]['reference_preserved'])
        self.assertTrue(revision['compatibility']['signal_references'][0]['terminal_has_exit'])
        self.assertEqual(len(revision['od']['required_cases']), 4)
        self.assertFalse(revision['od']['boundary_approved'])
        self.assertTrue(revision['preservation']['retain_all_components'])
        self.assertEqual(revision, build_revision(self.scenario)[0], 'deterministic provenance')

    def test_only_new_small_json_package_never_xml_or_existing_directory(self):
        revision, patch = build_revision(self.scenario)
        output = self.root / 'new-version'
        write_new_proposal(output, revision, patch)
        self.assertEqual({p.name for p in output.iterdir()}, {'scenario-revision.json', 'lane-movement-proposal.json'})
        self.assertFalse(json.loads((output / 'scenario-revision.json').read_text(encoding='utf-8'))['runnable'])
        with self.assertRaisesRegex(ValueError, 'carpeta nueva'):
            write_new_proposal(output, revision, patch)
        with self.assertRaisesRegex(ValueError, 'carpeta nueva'):
            write_new_proposal(self.scenario, revision, patch)

    def test_empty_terminal_is_a_blocker_never_deleted_or_assigned_fictional_exit(self):
        path = self.scenario / 'lanes.xml'
        path.write_text(path.read_text(encoding='utf-8').replace('<toLink refId="A"/>', ''), encoding='utf-8')
        revision, patch = build_revision(self.scenario)
        self.assertEqual(patch['operations'][0]['proposed_targets'], [])
        self.assertTrue(any(row['reason'] == 'would_empty_terminal_lane' for row in revision['blockers']))
        self.assertFalse(revision['runnable'])

    def test_incomplete_restriction_stays_explicit_without_guessed_members(self):
        path = self.scenario / 'map.osm'
        path.write_text(path.read_text(encoding='utf-8').replace('<member type="way" role="from" ref="10"/>', ''), encoding='utf-8')
        revision, patch = build_revision(self.scenario)
        self.assertEqual(patch['operations'], [])
        self.assertEqual([row['relation_id'] for row in patch['unresolved_restrictions']], ['100'])
        self.assertFalse(revision['runnable'])

    def test_combined_removals_cannot_reintroduce_a_previous_prohibition(self):
        path = self.scenario / 'map.osm'
        text = path.read_text(encoding='utf-8')
        second = '''<relation id="101"><member type="way" role="from" ref="10"/>
          <member type="node" role="via" ref="2"/><member type="way" role="to" ref="30"/>
          <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>'''
        path.write_text(text.replace('</osm>', second + '</osm>'), encoding='utf-8')
        revision, patch = build_revision(self.scenario)
        self.assertEqual(len(patch['operations']), 2)
        self.assertEqual(patch['combined_lane_targets'][0]['final_targets'], [])
        self.assertEqual(patch['combined_lane_targets'][0]['relation_ids'], ['100', '101'])
        self.assertTrue(any(row['reason'] == 'would_empty_terminal_lane' for row in revision['blockers']))

    def test_signal_turn_reference_requires_review_without_cycle_changes(self):
        path = self.scenario / 'signalSystems.xml'
        path.write_text(path.read_text(encoding='utf-8').replace('</signal>',
            '<turningMoveRestrictions><toLink refId="T"/></turningMoveRestrictions></signal>'), encoding='utf-8')
        before = path.read_bytes()
        revision, _ = build_revision(self.scenario)
        self.assertTrue(any(row['reason'] == 'signal_turning_move_requires_review' for row in revision['blockers']))
        self.assertEqual(before, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
