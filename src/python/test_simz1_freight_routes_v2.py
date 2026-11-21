"""Static source/route regressions; these tests never launch QSim."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight_routes import load_context, validate_route, validate_bundle, link_rejection, turn_rejection

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'scenarios/zona1'
SERVICE = dict(length_m=12, width_m=2.5, gross_weight_tonnes=12, maximum_speed_kmh=40, pcu=3.5)


def link(way):
    return 'osm_'+str(way)+'_0_forward'


class FreightRouteValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        coords = {'0': (-1, 5), '1': (1, 5), '2': (5, 5), '3': (9, 5), '4': (11, 5), '5': (5, 7)}
        self.osm = ET.Element('osm')
        ET.SubElement(self.osm, 'bounds', minlat='0', minlon='0', maxlat='10', maxlon='10')
        network = ET.Element('network')
        nblock, lblock = ET.SubElement(network, 'nodes'), ET.SubElement(network, 'links')
        for ident, (x, y) in coords.items():
            ET.SubElement(self.osm, 'node', id=ident, lon=str(x), lat=str(y))
            ET.SubElement(nblock, 'node', id=ident, x=str(x*10), y=str(y*10))
        for way, a, b, length in ((11, '0', '1', 20), (12, '1', '2', 4),
                                   (13, '2', '3', 40), (14, '3', '4', 20), (15, '2', '5', 20)):
            item = ET.SubElement(self.osm, 'way', id=str(way))
            ET.SubElement(item, 'nd', ref=a); ET.SubElement(item, 'nd', ref=b)
            ET.SubElement(item, 'tag', k='highway', v='primary')
            ET.SubElement(item, 'tag', k='oneway', v='yes')
            ET.SubElement(lblock, 'link', id=link(way), **{'from': a, 'to': b}, length=str(length),
                          freespeed='10', capacity='2000', permlanes='1', modes='car', origid=str(way))
        self.network = network
        self.lanes = ET.Element('laneDefinitions')
        assignment = ET.SubElement(self.lanes, 'lanesToLinkAssignment', linkIdRef=link(12))
        for ident, start, kind, targets in (('root', 4, 'toLane', ['terminal']),
                                            ('terminal', 2, 'toLink', [link(13), link(15)])):
            lane = ET.SubElement(assignment, 'lane', id=ident)
            ET.SubElement(lane, 'startsAt', meterFromLinkEnd=str(start))
            ET.SubElement(lane, 'representedLanes', number='1')
            ET.SubElement(lane, 'capacity', vehiclesPerHour='2000')
            leads = ET.SubElement(lane, 'leadsTo')
            for target in targets:
                ET.SubElement(leads, kind, refId=target)
        self.route = dict(route_id='west-east', link_ids=[link(k) for k in (11, 12, 13, 14)],
                          entry_gateway='west-in', exit_gateway='east-out', boundary_basis='osm_bounds_crossing')

    def tearDown(self):
        self.temporary.cleanup()

    def context(self):
        for name, tree in (('network.xml', self.network), ('lanes.xml', self.lanes), ('map.osm', self.osm)):
            ET.ElementTree(tree).write(self.folder/name)
        return load_context(self.folder/'network.xml', self.folder/'lanes.xml', self.folder/'map.osm')

    def relation(self, kind='no_left_turn', source='12', via='2', target='13', **tags):
        item = ET.SubElement(self.osm, 'relation', id='r1')
        for role, category, ref in (('from', 'way', source), ('via', 'node', via), ('to', 'way', target)):
            ET.SubElement(item, 'member', role=role, type=category, ref=ref)
        for key, value in dict(type='restriction', restriction=kind, **tags).items():
            ET.SubElement(item, 'tag', k=key, v=value)
        return item

    def test_actual_boundary_crossings_metrics_and_short_links_are_not_rejected(self):
        report = validate_route(self.context(), self.route, SERVICE)
        self.assertEqual(report['distance_m'], 84)
        self.assertAlmostEqual(report['free_flow_s'], 8.4)
        self.assertEqual((report['entry']['side'], report['exit']['side']), ('west', 'east'))
        self.assertEqual(report['links_shorter_than_truck'], 1)
        self.assertTrue(report['opposite_perimeter_sides'])
        self.assertFalse(report['swept_path_verified'])
        self.assertFalse(report['queue_drainage_proven'])

    def test_interior_origin_same_gateway_and_repeated_path_fail(self):
        ctx = self.context()
        ctx['osm_nodes']['0']['lon'] = 0.5
        with self.assertRaisesRegex(ValueError, 'perimeter entry'):
            validate_route(ctx, self.route, SERVICE)
        with self.assertRaisesRegex(ValueError, 'perimeter entry'):
            validate_route(self.context(), dict(self.route, exit_gateway='west-in'), SERVICE)
        with self.assertRaisesRegex(ValueError, 'repeated'):
            validate_route(self.context(), dict(self.route, link_ids=self.route['link_ids']+[link(12)]), SERVICE)

    def test_principal_roads_and_bounded_explicit_residential_gateway_exception(self):
        ctx = self.context()
        ctx['ways']['11']['tags']['highway'] = 'residential'
        with self.assertRaisesRegex(ValueError, 'nonprincipal'):
            validate_route(ctx, self.route, SERVICE)
        route = dict(self.route, perimeter_connector_links=[link(11)])
        self.assertEqual(validate_route(ctx, route, SERVICE)['perimeter_connector_m'], 20)
        ctx['links'][link(11)]['length'] = 251
        with self.assertRaisesRegex(ValueError, 'exceeds 250'):
            validate_route(ctx, route, SERVICE)
        ctx = self.context(); ctx['ways']['12']['tags']['highway'] = 'residential'
        with self.assertRaisesRegex(ValueError, 'route ends'):
            validate_route(ctx, dict(self.route, perimeter_connector_links=[link(12)]), SERVICE)
        for highway in ('service', 'living_street', 'unclassified'):
            ctx = self.context(); ctx['ways']['11']['tags']['highway'] = highway
            self.assertIn('nonprincipal', link_rejection(ctx, link(11), SERVICE, True))

    def test_missing_disconnected_wrongway_and_source_segment_fail(self):
        ctx = self.context()
        self.assertIn('missing', link_rejection(ctx, 'absent', SERVICE))
        self.assertIn('disconnected', turn_rejection(ctx, link(11), link(14)))
        ctx['ways']['12']['tags']['oneway'] = '-1'
        self.assertIn('wrong OSM direction', link_rejection(ctx, link(12), SERVICE))
        ctx = self.context(); ctx['links'][link(12)]['to'] = '3'
        self.assertIn('segment/node mismatch', link_rejection(ctx, link(12), SERVICE))

    def test_access_limits_on_source_way_network_and_nodes_fail_closed(self):
        denied = [('hgv', 'no'), ('hgv', 'delivery'), ('access', 'private'), ('motor_vehicle', 'destination'),
                  ('hgv:conditional', 'yes @ (00:00-05:00)'), ('maxweight', '11'),
                  ('maxweight', '11000 kg'), ('maxlength', '11.9 m'), ('maxwidth', '2.4'),
                  ('maxheight', '4'), ('maxaxleload', '4'), ('maxweight', 'unknown'),
                  ('maxwidth:conditional', '3 @ (night)'), ('barrier', 'bollard'), ('oneway:conditional', 'yes')]
        for source in ('way', 'network', 'osm_node', 'network_node'):
            for key, value in denied:
                with self.subTest(source=source, key=key, value=value):
                    ctx = self.context()
                    target = {'way': ctx['ways']['12']['tags'], 'network': ctx['links'][link(12)]['tags'],
                              'osm_node': ctx['osm_nodes']['2']['tags'], 'network_node': ctx['nodes']['2']['tags']}[source]
                    target[key] = value
                    self.assertIsNotNone(link_rejection(ctx, link(12), SERVICE))
        for key, value in (('hgv', 'designated'), ('maxweight', '12 t'), ('maxweight', '12000 kg'),
                           ('maxlength', '12 m'), ('maxwidth', '2.5'), ('maxweight:backward', '1')):
            ctx = self.context(); ctx['ways']['12']['tags'][key] = value
            self.assertIsNone(link_rejection(ctx, link(12), SERVICE), (key, value))

    def test_lane_graph_rejects_unreachable_cycle_dangling_and_mixed_targets(self):
        original = deepcopy(self.lanes)
        for mutation in ('unreachable', 'cycle', 'dangling', 'mixed', 'upstream'):
            with self.subTest(mutation=mutation):
                self.lanes = deepcopy(original)
                assignment = self.lanes.find('lanesToLinkAssignment')
                terminal = assignment.find("lane[@id='terminal']")
                if mutation == 'unreachable':
                    orphan = deepcopy(terminal); orphan.set('id', 'orphan'); assignment.append(orphan)
                elif mutation in ('cycle', 'dangling'):
                    leads = terminal.find('leadsTo'); leads.clear()
                    ET.SubElement(leads, 'toLane', refId='terminal' if mutation == 'cycle' else 'missing')
                elif mutation == 'mixed':
                    ET.SubElement(terminal.find('leadsTo'), 'toLane', refId='root')
                else:
                    terminal.find('startsAt').set('meterFromLinkEnd', '5')
                with self.assertRaises(ValueError):
                    self.context()

    def test_declared_but_forbidden_lane_movement_fails(self):
        leads = self.lanes.find("lanesToLinkAssignment/lane[@id='terminal']/leadsTo")
        leads.remove(leads.find("toLink[@refId='"+link(13)+"']"))
        with self.assertRaisesRegex(ValueError, 'lane turn'):
            validate_route(self.context(), self.route, SERVICE)

    def test_via_node_no_only_and_heavy_vehicle_exception(self):
        self.relation()
        with self.assertRaisesRegex(ValueError, 'forbidden OSM'):
            validate_route(self.context(), self.route, SERVICE)
        self.osm.remove(self.osm.find('relation'))
        self.relation(kind='only_right_turn', target='15')
        with self.assertRaisesRegex(ValueError, 'forbidden OSM'):
            validate_route(self.context(), self.route, SERVICE)
        ET.SubElement(self.osm.find('relation'), 'tag', k='except', v='bus;hgv')
        validate_route(self.context(), self.route, SERVICE)

    def test_general_vehicle_restriction_applies_and_general_exception_is_honored(self):
        for suffix in ('motor_vehicle', 'vehicle', 'hgv'):
            with self.subTest(suffix=suffix):
                if self.osm.find('relation') is not None:
                    self.osm.remove(self.osm.find('relation'))
                item = self.relation()
                item.find("tag[@k='restriction']").set('k', 'restriction:'+suffix)
                with self.assertRaisesRegex(ValueError, 'forbidden OSM'):
                    validate_route(self.context(), self.route, SERVICE)
                ET.SubElement(item, 'tag', k='except', v='motor_vehicle')
                validate_route(self.context(), self.route, SERVICE)
        item.find("tag[@k='except']").set('v', 'bus;goods;motorcar')
        with self.assertRaisesRegex(ValueError, 'forbidden OSM'):
            validate_route(self.context(), self.route, SERVICE)

    def test_explicit_road_width_is_shared_across_directional_lanes(self):
        ctx = self.context()
        ctx['ways']['12']['tags']['width'] = '4 m'
        ctx['links']['reverse'] = dict(ctx['links'][link(12)], **{'from': '2', 'to': '1'})
        self.assertIn('width per modeled lane', link_rejection(ctx, link(12), SERVICE))
        ctx['ways']['12']['tags']['width'] = '5 m'
        self.assertIsNone(link_rejection(ctx, link(12), SERVICE))

    def test_turn_arrows_apply_at_way_end_and_must_have_compatible_lane(self):
        ctx = self.context()
        ctx['ways']['12']['tags']['turn:lanes'] = 'right'
        self.assertIn('no OSM turn:lanes', turn_rejection(ctx, link(12), link(13)))
        ctx['ways']['12']['tags']['turn:lanes'] = 'through;right'
        self.assertIsNone(turn_rejection(ctx, link(12), link(13)))
        # Same source way has another segment ahead: the straight intermediate
        # MATSim subdivision must not inherit arrows for the last junction.
        ctx['ways']['12']['nodes'].append('3')
        ctx['ways']['12']['tags']['turn:lanes'] = 'right'
        ctx['links'][link(13)]['way'] = '12'
        self.assertIsNone(turn_rejection(ctx, link(12), link(13)))
        ctx['ways']['12']['tags']['turn:lanes:conditional'] = 'through @ (night)'
        self.assertIn('unsupported turn-lane', link_rejection(ctx, link(12), SERVICE))

    def test_turn_arrow_direction_and_lane_count_fail_closed(self):
        ctx = self.context()
        ctx['ways']['12']['tags']['turn:lanes'] = 'through|right'
        self.assertIn('count differs', turn_rejection(ctx, link(12), link(13)))
        ctx['ways']['12']['tags']['turn:lanes'] = 'unknown'
        self.assertIn('unsupported', turn_rejection(ctx, link(12), link(13)))
        ctx['ways']['12']['tags']['oneway'] = 'no'
        ctx['ways']['12']['tags']['turn:lanes'] = 'through'
        self.assertIn('ambiguous', turn_rejection(ctx, link(12), link(13)))
        ctx['ways']['12']['tags']['turn:lanes:forward'] = 'through'
        self.assertIsNone(turn_rejection(ctx, link(12), link(13)))

    def test_unsupported_relevant_relation_rejected_unrelated_relation_tolerated(self):
        item = self.relation()
        item.find("member[@role='via']").set('type', 'way')
        item.find("member[@role='via']").set('ref', '15')
        with self.assertRaisesRegex(ValueError, 'unsupported relevant'):
            validate_route(self.context(), self.route, SERVICE)
        for member in item.findall('member'):
            member.set('ref', '999')
        validate_route(self.context(), self.route, SERVICE)
        self.osm.remove(item)
        item = self.relation(); item.remove(item.find("member[@role='from']"))
        with self.assertRaisesRegex(ValueError, 'unsupported relevant'):
            validate_route(self.context(), self.route, SERVICE)

    def test_no_u_turn_on_same_osm_way_does_not_prohibit_continuation(self):
        ctx = self.context()
        ctx['links'][link(13)]['way'] = '12'
        ctx['restrictions'] = [dict(id='u', tags=dict(type='restriction', restriction='no_u_turn'), members=[
            dict(type='way', role='from', ref='12'), dict(type='node', role='via', ref='2'),
            dict(type='way', role='to', ref='12')])]
        self.assertIsNone(turn_rejection(ctx, link(12), link(13)))
        ctx['links'][link(13)]['to'] = '1'
        self.assertIn('U-turn', turn_rejection(ctx, link(12), link(13)))


class CurrentFreightRouteTests(unittest.TestCase):
    def test_current_v2_routes_have_four_distinct_connected_perimeter_corridors(self):
        from simz1_freight import prepare
        service_path = SCENARIO/'freight/weekday-v2/service-composition-v2.json'
        service, bundle, roster = prepare(SCENARIO/'config-simz1.xml', service_path, vehicles=17)
        ctx = load_context(SCENARIO/'network.xml', SCENARIO/'lanes.xml', SCENARIO/'map.osm')
        report = validate_bundle(ctx, bundle, service)
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(len(report['routes']), 4)
        self.assertTrue(all(r['opposite_perimeter_sides'] for r in report['routes']))
        self.assertEqual(sum(bool(r['perimeter_connector_m']) for r in report['routes']), 1)
        self.assertEqual(sorted(sum(row['route_id'] == route['id'] for row in roster) for route in report['routes']), [4, 4, 4, 5])
        self.assertEqual((service['length_m'], service['width_m'], service['pcu'], service['gross_weight_tonnes']), (12, 2.5, 3.5, 12))
        # These are static checks, not an assertion that the known queue defects vanished.
        self.assertFalse(report['physical_stability_proven'])

    def test_generator_preserves_principal_anchors_and_is_deterministic(self):
        from prepare_simz1_freight_routes import build
        from simz1_freight_routes import PRINCIPAL_CLASSES
        ctx = load_context(SCENARIO/'network.xml', SCENARIO/'lanes.xml', SCENARIO/'map.osm')
        old = json.loads((SCENARIO/'freight/weekday-v1/routes.json').read_text(encoding='utf-8'))
        new = build(SCENARIO/'network.xml', SCENARIO/'lanes.xml')
        repeated = build(SCENARIO/'network.xml', SCENARIO/'lanes.xml')
        self.assertEqual(new, repeated)
        self.assertEqual([r['link_ids'] for r in new['routes']],
                         [r['link_ids'] for r in json.loads((SCENARIO/'freight/weekday-v2/routes.json').read_text(encoding='utf-8'))['routes']])
        retained = 0
        for before, after in zip(old['routes'], new['routes']):
            anchors = [k for k in before['link_ids'] if ctx['ways'][ctx['links'][k]['way']]['tags']['highway'] in PRINCIPAL_CLASSES]
            positions = [after['link_ids'].index(k) for k in anchors]
            self.assertEqual(positions, sorted(positions))
            retained += len(anchors)
        self.assertEqual(retained, 203)

    def test_bundle_identity_mismatch_is_not_silently_accepted(self):
        ctx = load_context(SCENARIO/'network.xml', SCENARIO/'lanes.xml', SCENARIO/'map.osm')
        bundle = json.loads((SCENARIO/'freight/weekday-v2/routes.json').read_text(encoding='utf-8'))
        service = json.loads((SCENARIO/'freight/weekday-v2/service-composition-v2.json').read_text(encoding='utf-8'))
        for field in ('service_version', 'route_policy'):
            for target in ('service', 'bundle'):
                with self.subTest(field=field, target=target):
                    b, s = deepcopy(bundle), deepcopy(service)
                    del (b if target == 'bundle' else s)[field]
                    with self.assertRaisesRegex(ValueError, 'version or route policy'):
                        validate_bundle(ctx, b, s)


if __name__ == '__main__':
    unittest.main()
