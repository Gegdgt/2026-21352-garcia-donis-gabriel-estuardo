"""Four-class fixtures only: no MATSim, archived output or replay regeneration."""
from collections import Counter
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import gateway_people, generar, SCENARIO
from simz1_gateway_od import GatewayModel, normalize_shares, validated_spatial_demand
from simz1_od_policy import (CLASSES, CLASS_BY_TYPE, CONTRACT, allocate, named_mix,
                             hourly_profiles, ClassDepartureSampler, GatewayBudget, validate_osm_turns)
from simz1_population import population_spec, draw_population
from simz1_temporal import temporal_spec
from test_simz1_gateway_od import fixture, SQUARE, metadata


def model(changes=None, movements=None):
    nodes, links, coordinates = fixture()
    for link in links.values():
        link.update(capacity=1000., freespeed=10., lanes=1.)
    if changes:
        changes(nodes, links, coordinates)
    return GatewayModel(nodes, links, SQUARE, coordinates, movements)


class FourODTests(unittest.TestCase):
    def test_exact_counts_range_draw_named_classes_and_seeded_people(self):
        shares = named_mix(dict(zip(CLASSES, (1, 2, 3, 4))))
        spec = population_spec(min_agents=101, max_agents=109)
        seed = 19
        number = draw_population(spec, random.Random(seed))
        snapshots = []
        for _ in range(2):
            graph = model()
            people, report, allowed = gateway_people(graph, seed, spec, shares, temporal_spec())
            people = list(people)
            self.assertEqual(len(people), number)
            counts = report['spatial_demand']['realized_class_counts']
            self.assertEqual(sum(counts.values()), number)
            self.assertEqual(counts, report['spatial_demand']['target_class_counts'])
            for p in people:
                record = next(iter(json.loads(p.findtext("attributes/attribute[@name='simz1SpatialOD']")).values()))
                graph.validate_metadata(record)
                self.assertEqual(record['od_class'], CLASS_BY_TYPE[record['od_type']])
                self.assertIsNone(record['door_to_door_seconds'])
            snapshots.append(([ET.tostring(p) for p in people], report))
        self.assertEqual(*snapshots)
        first, counts = allocate(103, shares, 1)
        second, other = allocate(103, shares, 2)
        self.assertEqual(counts, other)
        self.assertNotEqual(first, second)
        self.assertEqual(Counter(first), counts)

    def test_through_cannot_use_border_only_shortcut_or_same_access(self):
        def add_shortcut(nodes, links, coords):
            links['border-exit'] = dict(from_node='a', to_node='east', capacity=1000., modes=['car'])
        graph = model(add_shortcut)
        # entry -> border-exit is connected but never visits a non-gateway link.
        self.assertTrue(graph.reachable('entry', 'border-exit'))
        self.assertNotIn('border-exit', graph.through_destinations('entry'))
        self.assertEqual(graph.through_destinations('entry'), ('exit',))
        record = metadata(graph.sample(random.Random(1), 'external-external'))
        record.update(od_class='EXTERNAL_EXTERNAL_THROUGH', destination_link='border-exit',
                      destination_gateway='border-exit', destination_zone='synthetic-exterior-exit:border-exit')
        with self.assertRaisesRegex(ValueError, 'recorrido interior'):
            graph.validate_metadata(record)
        graph.exit_gateways['exit']['node_id'] = graph.entry_gateways['entry']['node_id']
        graph.through_destinations.cache_clear()
        self.assertFalse(graph.through_destinations('entry'))

    def test_one_way_forbidden_turn_dead_end_disconnection_and_grade(self):
        graph = model()
        self.assertFalse(graph.reachable('exit', 'entry'))
        forbidden = model(movements={'middle1': set()})
        self.assertFalse(forbidden.reachable('entry', 'exit'))
        with self.assertRaises(ValueError):
            forbidden.validate_shares(normalize_shares())
        def additions(nodes, links, coords):
            # The two levels share coordinates, NOT node identity. No connection
            # may be inferred between their geometrically crossing roads.
            for key, xy in [('overpass-a', (4, 5)), ('overpass-b', (6, 5)), ('dead', (5, 6))]:
                coords[key] = xy; nodes[key] = (500000+1000*xy[0], 1600000+1000*xy[1])
            links['bridge'] = dict(from_node='overpass-a', to_node='overpass-b', modes=['car'])
            links['culdesac'] = dict(from_node='b', to_node='dead', modes=['car'])
        graph = model(additions)
        self.assertFalse(graph.reachable('entry', 'bridge'))
        self.assertTrue(graph.reachable('entry', 'culdesac'))
        self.assertFalse(graph.reachable('culdesac', 'exit'))
        self.assertNotIn('culdesac', graph.origins('internal-external'))
        before = graph.destinations.cache_info().misses
        for _ in range(500):
            graph.sample(random.Random(_), 'external-internal')
        self.assertLessEqual(graph.destinations.cache_info().misses-before, 2)

    def test_gateways_require_capacity_permission_direction_and_shared_budgets(self):
        for change in ({'capacity': 0}, {'capacity': float('nan')}, {'car_access': 'no'}, {'modes': ['walk']}):
            with self.subTest(change=change):
                graph = model(lambda nodes, links, coords: links['cross-in'].update(change))
                self.assertFalse(graph.entry_gateways)
        graph = model(lambda nodes, links, coords: links['cross-in'].update(capacity=1.))
        sample = graph.sample(random.Random(1), 'external-external')
        budget = GatewayBudget(graph)
        for _ in range(4):
            self.assertTrue(budget.accept(sample, 7, .25))
        self.assertFalse(budget.accept(sample, 7, .25))
        self.assertTrue(budget.accept(sample, 8, 1))
        self.assertEqual(budget.summary()['usage'][0]['hour'], 7)

    def test_hourly_profiles_peaks_valleys_and_capacity_failure_do_not_reduce_N(self):
        with self.assertRaisesRegex(ValueError, 'horizonte 00:00-24:00'):
            gateway_people(model(), 5, population_spec(agents=4), normalize_shares([1]*4), temporal_spec(drain=60))
        profiles = {}
        for kind, hour in zip(CLASS_BY_TYPE, (2, 7, 17, 23)):
            profiles[kind] = [int(h == hour) for h in range(24)]
        people, report, _ = gateway_people(model(), 5, population_spec(agents=40), normalize_shares([1]*4),
                                           temporal_spec(), class_profiles=profiles)
        self.assertEqual(len(list(people)), 40)
        for kind, hour in zip(CLASS_BY_TYPE, (2, 7, 17, 23)):
            self.assertEqual(report['spatial_demand']['departures_by_class_hour'][CLASS_BY_TYPE[kind]][f'{hour:02}:00'], 10)
        limited = model(lambda nodes, links, coords: links['cross-in'].update(capacity=1.))
        people, report, _ = gateway_people(limited, 1, population_spec(agents=2), normalize_shares(),
                                           temporal_spec(weights=[1]+[0]*23))
        with self.assertRaisesRegex(ValueError, 'No se cambian N'):
            list(people)
        self.assertNotIn('realized_counts', report['spatial_demand'])

    def test_hourly_profile_file_and_agent_schedule_intersection(self):
        document = dict(source='synthetic', profiles={k: [int(h == 7) for h in range(24)] for k in CLASSES})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'hours.json'; path.write_text(json.dumps(document), encoding='utf-8')
            profiles, source = hourly_profiles(path, temporal_spec())
            self.assertEqual(source['document'], document)
            for kind in profiles:
                self.assertTrue(7*3600 <= ClassDepartureSampler(3, profiles).sample(kind) < 8*3600)
            document['source'] = 'municipal-measured-without-evidence'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                hourly_profiles(path, temporal_spec())
        from test_simz1_agent_demand import road_catalog
        from simz1_agent_demand import typed_people, verify_type_ledger
        catalog = road_catalog()
        temporal = temporal_spec()
        people, report, _ = gateway_people(model(), 17, population_spec(agents=20), normalize_shares([1]*4), temporal,
                                           class_profiles=profiles, catalog=catalog)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'types.jsonl'
            persons = list(typed_people(people, report, catalog, 20, 17, 1, temporal, path, preserve_departures=True))
            root = ET.Element('population'); root.extend(persons)
            plans = Path(directory)/'plans.xml'; ET.ElementTree(root).write(plans)
            self.assertEqual(verify_type_ledger(plans, path, catalog), report['agent_type_counts'])
            self.assertTrue(all(7*3600 <= float(p.find('plan/activity').get('end_time')) < 8*3600 for p in persons))
            self.assertEqual(sum(report['spatial_demand']['realized_class_counts'].values()), 20)


class RestrictionPreflightTests(unittest.TestCase):
    def fixture(self, folder, via_way=False):
        osm = ET.Element('osm')
        for ident in ('w1', 'w2', 'w3', 'w4', 'w5'):
            ET.SubElement(osm, 'way', id=ident)
        relation = ET.SubElement(osm, 'relation', id='r')
        ET.SubElement(relation, 'tag', k='type', v='restriction')
        ET.SubElement(relation, 'tag', k='restriction', v='no_u_turn' if via_way else 'no_left_turn')
        for role, kind, ref in [('from', 'way', 'w1'), ('via', 'way' if via_way else 'node', 'w2' if via_way else 'b'), ('to', 'way', 'w3' if via_way else 'w2')]:
            ET.SubElement(relation, 'member', role=role, type=kind, ref=ref)
        network = ET.Element('network'); ls = ET.SubElement(network, 'links')
        for ident, start, end, way in [('a','a','b','w1'), ('b','b','c','w2'), ('c','c','d','w3'), ('alt1','b','e','w4'), ('alt2','c','f','w5')]:
            ET.SubElement(ls, 'link', id=ident, origid=way, **{'from': start, 'to': end})
        paths = [Path(folder)/name for name in ('map.osm', 'network.xml', 'lanes.xml')]
        ET.ElementTree(osm).write(paths[0]); ET.ElementTree(network).write(paths[1])
        return paths

    def test_forbidden_pair_and_via_way_are_rejected_without_flattening(self):
        for via in (False, True):
            with self.subTest(via_way=via), tempfile.TemporaryDirectory() as folder:
                osm, network, lanes = self.fixture(folder, via)
                before = (osm.read_bytes(), network.read_bytes())
                with self.assertRaisesRegex(ValueError, 'Restricciones OSM pendientes.*r'):
                    validate_osm_turns(osm, network, None)
                # An existing, permitted alternative is not invented. A lane
                # exclusion fixture demonstrates that the preflight honors lanes.
                lanes.write_text('<laneDefinitions><lanesToLinkAssignment linkIdRef="b"><lane id="b.1"><leadsTo><toLink refId="alt2"/></leadsTo></lane></lanesToLinkAssignment><lanesToLinkAssignment linkIdRef="a"><lane id="a.1"><leadsTo><toLink refId="alt1"/></leadsTo></lane></lanesToLinkAssignment></laneDefinitions>', encoding='utf-8')
                self.assertTrue(validate_osm_turns(osm, network, lanes)['checked'])
                self.assertEqual((osm.read_bytes(), network.read_bytes()), before)


class FourODIntegrationTests(unittest.TestCase):
    def inputs(self, folder):
        from pyproj import Transformer
        transform = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True)
        nodes, links, coords = fixture()
        network = ET.Element('network'); ns = ET.SubElement(network, 'nodes'); ls = ET.SubElement(network, 'links', capperiod='01:00:00')
        osm = ET.Element('osm')
        for ident, (x, y) in nodes.items():
            ET.SubElement(ns, 'node', id=ident, x=str(x), y=str(y))
            lon, lat = transform.transform(x, y)
            ET.SubElement(osm, 'node', id=ident, lon=str(lon), lat=str(lat))
        for ident, link in links.items():
            ET.SubElement(ls, 'link', id=ident, origid=ident, length='1000', capacity='1000', freespeed='10', permlanes='1', modes='car',
                          **{'from': link['from_node'], 'to': link['to_node']})
            way = ET.SubElement(osm, 'way', id=ident)
            for node in (link['from_node'], link['to_node']):
                ET.SubElement(way, 'nd', ref=node)
        for filename, root in [('network.xml', network), ('map.osm', osm), ('lanes.xml', ET.Element('laneDefinitions')),
                               ('facilities.xml', ET.Element('facilities'))]:
            ET.ElementTree(root).write(folder/filename)
        boundary = dict(type='Polygon', coordinates=[[list(transform.transform(500000+x*1000, 1600000+y*1000))
                                                      for x, y in SQUARE['coordinates'][0]]])
        (folder/'zone.geojson').write_text(json.dumps(boundary), encoding='utf-8')
        config = ET.parse(SCENARIO/'config-simz1.xml')
        root = config.getroot()
        root.find("module[@name='vehicles']/param[@name='vehiclesFile']").set('value', str((SCENARIO/'vehicle-types.xml').resolve()))
        root.find("module[@name='qsim']/param[@name='useLanes']").set('value', 'false')
        signals = root.find("module[@name='signalsystems']")
        signals.clear(); signals.set('name', 'signalsystems')
        ET.SubElement(signals, 'param', name='useSignalsystems', value='false')
        config.write(folder/'config.xml')

    def test_small_future_run_manifest_and_legacy_source_files_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); self.inputs(folder)
            original = {p.name: p.read_bytes() for p in folder.iterdir()}
            kwargs = dict(agents=12, od_mode='gateway-od', od_mix=json.dumps(dict.fromkeys(CLASSES, 1)),
                          zone_boundary=folder/'zone.geojson', od_osm=folder/'map.osm')
            hashes = []
            for name in ('a', 'b'):
                with patch('generate_montecarlo_z1.duplicate_population_check', return_value=dict(matches=[], unverifiable_manifests=[])):
                    report = generar(folder/'config.xml', folder/name, 7, **kwargs)
                manifest = json.loads((folder/name/'run-manifest.json').read_text())
                spatial = validated_spatial_demand(folder/name, manifest)
                self.assertEqual(spatial['od_contract'], CONTRACT)
                self.assertEqual(spatial['realized_class_counts'], dict.fromkeys(CLASSES, 3))
                self.assertEqual(report['xml_verified_counts']['persons'], 12)
                self.assertFalse((folder/name/'output').exists())
                hashes.append((folder/name/'plans.xml').read_bytes())
            self.assertEqual(*hashes)
            self.assertEqual({name: (folder/name).read_bytes() for name in original}, original)
            # A newly introduced unimported restriction fails BEFORE mkdir.
            osm = ET.parse(folder/'map.osm'); relation = ET.SubElement(osm.getroot(), 'relation', id='unsafe')
            for key, value in [('type','restriction'), ('restriction','no_straight_on')]:
                ET.SubElement(relation, 'tag', k=key, v=value)
            for role, kind, ref in [('from','way','middle1'), ('via','node','b'), ('to','way','middle2')]:
                ET.SubElement(relation, 'member', role=role, type=kind, ref=ref)
            osm.write(folder/'map.osm')
            with self.assertRaisesRegex(ValueError, 'Restricciones OSM pendientes'):
                generar(folder/'config.xml', folder/'rejected', 7, **kwargs)
            self.assertFalse((folder/'rejected').exists())


if __name__ == '__main__':
    unittest.main()
