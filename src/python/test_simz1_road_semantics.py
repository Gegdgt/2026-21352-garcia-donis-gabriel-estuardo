"""In-memory road semantics only: no populations, exports, servers or QSim."""
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from prepare_simz1 import driving_directions, prepare, road_reason, validate_turn_restrictions
from simz1_road_parameters import lane_count


class RoadSemanticsTests(unittest.TestCase):
    def test_oneway_and_directional_lane_counts(self):
        cases = [
            ({'oneway': 'yes', 'lanes': '1'}, [1], [1]),
            ({'oneway': 'yes', 'lanes': '2'}, [1], [2]),
            ({'oneway': '-1', 'lanes': '2', 'lanes:backward': '2'}, [-1], [2]),
            ({'oneway': 'no', 'lanes': '2'}, [1, -1], [1, 1]),
            ({'oneway': 'no', 'lanes': '3', 'lanes:forward': '2', 'lanes:backward': '1'},
             [1, -1], [2, 1]),
        ]
        for tags, directions, counts in cases:
            with self.subTest(tags=tags):
                self.assertEqual(driving_directions(tags), directions)
                self.assertEqual([lane_count(tags, d, directions)[0] for d in directions], counts)
        # A shared bidirectional lane cannot be silently duplicated as 1+1.
        with self.assertRaisesRegex(ValueError, 'alternating-flow'):
            lane_count({'oneway': 'no', 'lanes': '1'}, 1, [1, -1])

    def test_car_access_precedence_and_unknowns(self):
        base = {'highway': 'service'}
        self.assertIsNone(road_reason({**base, 'access': 'no', 'motor_vehicle': 'yes'}))
        self.assertIsNotNone(road_reason({**base, 'access': 'yes', 'motorcar': 'no'}))
        self.assertIsNotNone(road_reason({**base, 'motor_vehicle': 'no'}))
        self.assertIsNotNone(road_reason({**base, 'oneway': 'reversible'}))
        self.assertIsNotNone(road_reason({**base, 'oneway:conditional': 'yes @ (08:00-09:00)'}))
        self.assertEqual(lane_count({}, 1, [1]), (1, 'assumed:one_lane'))

    def test_imported_directions_separate_carriageways_and_grade_crossing(self):
        root = ET.fromstring('''<osm>
          <node id="1" lon="-90.520" lat="14.640"/>
          <node id="2" lon="-90.519" lat="14.640"/>
          <node id="3" lon="-90.520" lat="14.6401"/>
          <node id="4" lon="-90.519" lat="14.6401"/>
          <node id="5" lon="-90.5195" lat="14.639"/>
          <node id="6" lon="-90.5195" lat="14.641"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/>
            <tag k="oneway" v="yes"/><tag k="lanes" v="2"/>
            <tag k="bridge" v="yes"/><tag k="layer" v="1"/></way>
          <way id="11"><nd ref="3"/><nd ref="4"/><tag k="highway" v="primary"/>
            <tag k="oneway" v="-1"/><tag k="lanes" v="1"/></way>
          <way id="12"><nd ref="5"/><nd ref="6"/><tag k="highway" v="service"/>
            <tag k="oneway" v="no"/><tag k="lanes" v="2"/>
            <tag k="tunnel" v="yes"/><tag k="layer" v="-1"/></way>
        </osm>''')
        captured = []

        class NetworkCaptured(Exception):
            pass

        def capture(network, _):
            captured.append(network)
            raise NetworkCaptured()

        # Existing override hook is after network assembly and before any
        # facilities/population/output. Stop there, without calling the override.
        with patch('prepare_simz1.ET.parse', return_value=ET.ElementTree(root)), \
                patch('prepare_simz1.apply_priority_overrides', side_effect=capture), \
                patch('prepare_simz1.write_xml') as write:
            with self.assertRaises(NetworkCaptured):
                prepare('in-memory.osm', None, priority_overrides='capture-only')
            write.assert_not_called()
        network = captured[0]
        links = {el.get('id'): el for el in network.findall('links/link')}
        expected = {'osm_10_0_forward': ('1', '2', '2'),
                    'osm_11_0_backward': ('4', '3', '1'),
                    'osm_12_0_forward': ('5', '6', '1'),
                    'osm_12_0_backward': ('6', '5', '1')}
        self.assertEqual({ident: tuple(el.get(k) for k in ('from', 'to', 'permlanes'))
                          for ident, el in links.items()}, expected)
        self.assertEqual({n.get('id') for n in network.findall('nodes/node')}, set('123456'))
        self.assertEqual(links['osm_10_0_forward'].findtext("attributes/attribute[@name='osm:layer']"), '1')
        self.assertEqual(links['osm_12_0_forward'].findtext("attributes/attribute[@name='osm:layer']"), '-1')

    def test_restrictions_stop_future_generation_before_any_output(self):
        for members in (
            '<member type="way" role="from" ref="10"/><member type="node" role="via" ref="2"/>'
            '<member type="way" role="to" ref="11"/>',
            '<member type="way" role="via" ref="12"/>',
            '',
        ):
            root = ET.fromstring('<osm><relation id="6008781">' + members +
                                 '<tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>'
                                 '</relation></osm>')
            # prepare is intentionally stopped before projection, network building
            # or the population/export code; the XML fixture stays in memory.
            with self.subTest(members=members), \
                    patch('prepare_simz1.ET.parse', return_value=ET.ElementTree(root)), \
                    patch('prepare_simz1.Transformer.from_crs') as transform, \
                    patch('prepare_simz1.write_xml') as write:
                with self.assertRaisesRegex(ValueError, 'before writes.*6008781'):
                    prepare('in-memory.osm', None)
                transform.assert_not_called()
                write.assert_not_called()
        validate_turn_restrictions(ET.fromstring('<osm/>'))
        validate_turn_restrictions(ET.fromstring(
            '<osm><relation id="deleted" action="delete"><tag k="type" v="restriction"/></relation></osm>'))


if __name__ == '__main__':
    unittest.main()
