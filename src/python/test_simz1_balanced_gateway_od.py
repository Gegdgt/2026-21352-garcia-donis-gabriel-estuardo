"""Correction 5: synthetic unit fixtures only; no JVM or large population.

The square and gateway attestations below are TEST DATA, never Zona 1 evidence.
Large N tests perform quota arithmetic only; generated fixtures contain <=99
private persons. This file has been prepared for manual execution by the user.
"""
from collections import Counter
import argparse
import copy
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_agent_types import load_catalog, sample_departures, vehicle_types_xml
from simz1_agent_demand import typed_people, verify_type_ledger
from simz1_demand_composition import split, freight_options
from simz1_gateway_od import GatewayModel, Polygon
from simz1_balanced_od import (BalancedGatewayModel, IncorporationBudget, input_options,
    load_model, digest, native_queue_ends, VARIANT, ORIGIN_POLICY, ACCESS_SCHEMA, BOUNDARY_SCHEMA)
from simz1_balanced_od_audit import (PrivateODAudit, check_config, validate_manifest,
    validate_scheduled_report, require_native_success, implementation_signature)
from simz1_od_policy import CLASSES, LEGACY, CLASS_BY_TYPE, named_percentages, percentage_document, allocate, validate_osm_turns
from simz1_temporal import temporal_spec, trip_id
from generate_montecarlo_z1 import gateway_people, generar, spatial_options, add_generation_options, generation_options

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT/'scenarios/zona1/agent-types-balanced-v1.json'
SEED = 20261023
MIX = dict(zip(CLASSES, (25, 25, 25, 25)))  # Test hypothesis, NOT traffic counts.
SQUARE = {'type':'Polygon', 'coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
CHAIN = ['anchor-in','cross-in','observe-in','short','origin-a','origin-b',
         'observe-out','cross-out','anchor-out']


def reviewed():
    return dict(verified=True, version='synthetic-test-v1', source='UNIT TEST ONLY',
                reviewed_by='unit-test-fixture', reviewed_at='2026-10-31')


def fixture(*, exit_near_boundary=False):
    coordinates = dict(zip(('w0','w1','a','b','c','d','f','e','e0','e1'),
        [(-4,5),(-2,5),(2,5),(4,5),(4.2,5),(6,5),(6.6,5),(8,5),(12,5),(14,5)]))
    if exit_near_boundary:
        coordinates.update(e=(9.9,5),e0=(10.1,5),e1=(10.7,5))
    node_ids = list(coordinates)
    nodes = {key:(x*10,y*10) for key,(x,y) in coordinates.items()}
    links = {key:dict(from_node=a,to_node=b,path=[coordinates[a],coordinates[b]],
                      length=math.dist(nodes[a],nodes[b]),lanes=1.,capacity=10000.,freespeed=10.,
                      modes=['car'],car_access='yes')
             for key,a,b in zip(CHAIN,node_ids,node_ids[1:])}
    moves = {a:{b} for a,b in zip(CHAIN,CHAIN[1:])}
    base = GatewayModel(nodes,links,SQUARE,coordinates,moves)

    def activity(key):
        return dict(review=reviewed(),useful_length_m=links[key]['length'],
                    activity_allowed=True,incorporation_capacity_pcu_h=10000.,
                    capacity_basis='Synthetic fixture upper bound, not a street capacity edit')

    document = dict(schema_version=ACCESS_SCHEMA,review=reviewed(),
        perimeter=dict(reviewed(),schema_version=BOUNDARY_SCHEMA),
        entry_gateways=[dict(activity('anchor-in'),id='west-in',anchor_link='anchor-in',
                            crossing_link='cross-in',observation_link='observe-in',link_ids=CHAIN[:3])],
        exit_gateways=[dict(activity('anchor-out'),id='east-out',anchor_link='anchor-out',
                           crossing_link='cross-out',observation_link='observe-out',link_ids=CHAIN[-3:])],
        internal_origins=[dict(activity(key),link_id=key) for key in ('origin-a','origin-b')])
    ends = {key:row['length'] for key,row in links.items()}
    return base,document,ends,moves


def model():
    return BalancedGatewayModel(*fixture())


def record(kind='external-external', body=4.5):
    selected = model().sample(random.Random(SEED),kind,body)
    return {k:v for k,v in selected.items() if k not in ('origin_xy','destination_xy')}


def config():
    return {'qsim.useLanes':'true','qsim.numberOfThreads':'1',
        'simz1Admission.storagePolicy':'strict-receiver-v1','simz1Admission.wholeVehicleReservation':'true',
        'controler.enableLinkToLinkRouting':'true','controler.firstIteration':'0','controler.lastIteration':'0',
        'global.randomSeed':str(SEED)}


def write_verified_test_inputs(folder):
    """Tiny projected fixture with synthetic provenance, never production inputs."""
    from pyproj import Transformer
    base,doc,_,_ = fixture()
    transform = Transformer.from_crs('EPSG:32615','EPSG:4326',always_xy=True)
    nodes = {key:(500000+x,1600000+y) for key,(x,y) in base.nodes.items()}
    network = ET.Element('network'); ns = ET.SubElement(network,'nodes')
    for key,(x,y) in nodes.items(): ET.SubElement(ns,'node',id=key,x=str(x),y=str(y))
    ls = ET.SubElement(network,'links',capperiod='01:00:00')
    osm = ET.Element('osm',version='0.6')
    for index,(key,row) in enumerate(base.links.items(),1):
        ET.SubElement(ls,'link',id=key,**{'from':row['from_node'],'to':row['to_node'],
            'length':str(row['length']),'capacity':str(row['capacity']),'freespeed':'10','permlanes':'1','modes':'car','origid':str(index)})
        ET.SubElement(osm,'way',id=str(index))
    paths = {key:folder/(key+suffix) for key,suffix in
             (('network','.xml'),('lanes','.xml'),('osm','.osm'),('boundary','.geojson'),('access','.json'))}
    ET.ElementTree(network).write(paths['network'],encoding='utf-8')
    ET.ElementTree(osm).write(paths['osm'],encoding='utf-8')
    paths['lanes'].write_text('<laneDefinitions/>',encoding='utf-8')
    boundary = dict(type='Polygon',coordinates=[[list(transform.transform(500000+10*x,1600000+10*y)) for x,y in SQUARE['coordinates'][0]]])
    paths['boundary'].write_text(json.dumps(boundary),encoding='utf-8')
    doc['perimeter']['sha256'] = digest(paths['boundary'])
    doc.update(**{key+'_sha256':digest(paths[key]) for key in ('network','lanes','osm')})
    paths['access'].write_text(json.dumps(doc),encoding='utf-8')
    return paths


class BalancedQuotaTests(unittest.TestCase):
    def test_large_requested_totals_are_arithmetic_not_populations(self):
        catalog = load_catalog(CATALOG)
        for n,expected in ((110000,(48400,60500,1100)),(220000,(96800,121000,2200))):
            with self.subTest(n=n):
                result = split(n,catalog)
                self.assertEqual(result['family_counts'],dict(zip(('carro','moto','pesado'),expected)))
                self.assertEqual(result['private_vehicles'],sum(expected[:2]))
                self.assertEqual(result['private_vehicles']+result['freight_vehicles'],n)
                self.assertFalse(result['public_transport_in_total'])
                self.assertEqual(result['private_profile_counts']['TransportePesado'],0)
        service = json.loads((ROOT/'scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(service['fleet_counts'],dict(transmetro=176,tubus=93))
        self.assertEqual(sum(s['buses'] for s in service['services']),269)

    def test_freight_is_reserved_once_not_added_to_N(self):
        composition = split(100,load_catalog(CATALOG))
        self.assertEqual(composition['family_counts'],dict(carro=44,moto=55,pesado=1))
        self.assertEqual(freight_options(composition,'unchanged-service','2026-10-23',None,False),
                         ('unchanged-service','2026-10-23',1,False))
        with self.assertRaises(ValueError):
            freight_options(composition,'unchanged-service','2026-10-23',2,False)
        with self.assertRaises(ValueError):
            freight_options(composition,None,None,None,True)

    def test_exact_percentages_and_four_small_class_quotas(self):
        shares = named_percentages(MIX)
        assignments,counts = allocate(40,shares,SEED)
        self.assertEqual(set(assignments),set(LEGACY))
        self.assertEqual(counts,dict.fromkeys(LEGACY,10))
        decimal = dict(zip(CLASSES,('33.3','33.3','33.3','0.1')))
        self.assertAlmostEqual(sum(named_percentages(decimal).values()),1.)
        self.assertEqual(percentage_document(json.dumps(decimal)),decimal)
        for invalid in ({},dict(MIX,INTERNAL_INTERNAL=24),dict(MIX,INTERNAL_INTERNAL=-25),
                        dict(MIX,INTERNAL_INTERNAL=True),dict(MIX,INTERNAL_INTERNAL='nan')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                named_percentages(invalid)
        alternative = named_percentages(dict(zip(CLASSES,(10,20,30,40))))
        self.assertEqual(allocate(10,alternative,SEED)[1],dict(zip(LEGACY,(1,2,3,4))))


class GatewayContractTests(unittest.TestCase):
    def test_four_classes_directed_connected_and_real_crossings(self):
        graph = model()
        graph.validate_shares(named_percentages(MIX))
        for kind in LEGACY:
            with self.subTest(kind=kind):
                row = record(kind)
                graph.validate_metadata(row)
                graph.validate_route(row['route_link_ids'])
                self.assertTrue(set(row['route_link_ids']) & set(graph.internal_links))
                self.assertEqual(row['od_class'],CLASS_BY_TYPE[kind])
                self.assertEqual(bool(row['origin_gateway']),kind.startswith('external'))
                self.assertEqual(bool(row['destination_gateway']),kind.endswith('external'))
        through = record()
        self.assertEqual(through['route_link_ids'],CHAIN)
        self.assertNotEqual(through['entry_crossing_link'],through['exit_crossing_link'])
        self.assertEqual(graph.classification['observe-out'],'interior')
        self.assertEqual(graph.classification['cross-out'],'exit_crossing')
        self.assertEqual(graph.classification['anchor-out'],'external_connected_candidate')
        self.assertIsNone(through['door_to_door_seconds'])

    def test_no_interior_proxy_is_accepted_as_real_exit(self):
        base,doc,ends,moves = fixture()
        doc['exit_gateways'][0].update(anchor_link='observe-out',link_ids=['observe-out'])
        with self.assertRaises(ValueError):
            BalancedGatewayModel(base,doc,ends,moves)
        row = record()
        row['destination_link'] = 'observe-out'
        with self.assertRaises(ValueError):
            model().validate_metadata(row)

    def test_no_missing_external_continuation_is_invented(self):
        base,doc,ends,moves = fixture()
        doc['exit_gateways'][0]['link_ids'][-1] = 'invented-exterior'
        with self.assertRaises(ValueError):
            BalancedGatewayModel(base,doc,ends,moves)
        base,doc,ends,moves = fixture()
        doc['exit_gateways'] = []
        graph = BalancedGatewayModel(base,doc,ends,moves)
        with self.assertRaisesRegex(ValueError,'exterior links separately'):
            graph.validate_shares(named_percentages(MIX))

    def test_through_gateways_must_be_distinct_even_with_different_link_ids(self):
        base,doc,ends,moves = fixture()
        doc['exit_gateways'][0]['id'] = doc['entry_gateways'][0]['id']
        graph = BalancedGatewayModel(base,doc,ends,moves)
        self.assertEqual(graph.candidates('anchor-in','external-external',4.5),())

    def test_forbidden_lane_direction_and_disconnection_fail(self):
        graph = model()
        with self.assertRaises(ValueError):
            graph.validate_route(['origin-b','origin-a'])
        base,doc,ends,moves = fixture()
        moves['cross-in'] = set()
        with self.assertRaisesRegex(ValueError,'forbidden lane direction'):
            BalancedGatewayModel(base,doc,ends,moves)
        base,doc,ends,moves = fixture()
        base.successors['origin-a'] = []
        # The production constructor recomputes reachability from these lanes.
        coordinates = {k:(x/10,y/10) for k,(x,y) in base.nodes.items()}
        moves['origin-a'] = set()
        base = GatewayModel(base.nodes,base.links,SQUARE,coordinates,moves)
        graph = BalancedGatewayModel(base,doc,ends,moves)
        with self.assertRaises(ValueError):
            graph.validate_shares(named_percentages(MIX))

    def test_only_reviewed_origins_short_connectors_remain_routable(self):
        graph = model()
        self.assertIn('short',graph.route('anchor-in','anchor-out'))
        self.assertNotIn('short',graph.origins('internal-external'))
        self.assertIn('origin-b',graph.origins('internal-external'))
        self.assertLess(graph.links['origin-b']['length'],10)
        before = copy.deepcopy(graph.links)
        class Capture:
            def __init__(self): self.calls = []
            def choices(self, values, *, weights, k):
                self.calls.append((values,weights)); return [values[0]]
        rng = Capture()
        graph.sample(rng,'internal-external')
        values,weights = rng.calls[0]
        self.assertEqual(weights,[graph.sites[k]['useful_length_m']*graph.links[k]['lanes'] for k in values])
        self.assertEqual(before,graph.links)
        self.assertNotIn('short',graph.candidates('anchor-in','external-internal',4.5))

    def test_unreviewed_activity_and_inflated_capacity_rejected(self):
        for key,value in (('activity_allowed',False),('useful_length_m',999),
                          ('incorporation_capacity_pcu_h',20000),('review',dict(reviewed(),verified=False))):
            base,doc,ends,moves = fixture()
            doc['internal_origins'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                BalancedGatewayModel(base,doc,ends,moves)

    def test_body_clearance_and_native_storage_not_silently_enlarged(self):
        base,doc,ends,moves = fixture()
        # Physically insufficient tail clearance even with a valid crossing.
        base.links['cross-out']['length'] = .1
        base.links['anchor-out']['length'] = 1.98
        doc['exit_gateways'][0]['useful_length_m'] = 1.98
        ends['anchor-out'] = 1.98
        graph = BalancedGatewayModel(base,doc,ends,moves)
        self.assertLess(graph.exit_clearance('anchor-out',4.5),0)
        self.assertEqual(graph.candidates('anchor-in','external-external',4.5),())
        self.assertEqual(base.links['anchor-out']['length'],1.98)

    def test_capacity_rejection_preserves_hour_class_and_metadata(self):
        base,doc,ends,moves = fixture()
        doc['entry_gateways'][0]['incorporation_capacity_pcu_h'] = 1
        graph = BalancedGatewayModel(base,doc,ends,moves)
        budget = IncorporationBudget(graph)
        row = record(); before = copy.deepcopy(row)
        self.assertTrue(budget.accept(row,7,1))
        self.assertFalse(budget.accept(row,7,1))
        self.assertEqual(row,before)
        self.assertEqual(budget.used[7,'anchor-in'],1)
        self.assertEqual(budget.summary()['rejected_pair_attempts'],{'incorporation_capacity':1})

    def test_native_queue_endpoint_is_not_link_length_when_split(self):
        with tempfile.TemporaryDirectory() as td:
            network,lanes = Path(td)/'network.xml',Path(td)/'lanes.xml'
            network.write_text('<network><links><link id="s" length="6"/></links></network>',encoding='utf-8')
            lanes.write_text('<laneDefinitions><lanesToLinkAssignment linkIdRef="s">'
                '<lane id="s.original"><startsAt meterFromLinkEnd="6"/><leadsTo><toLane refId="s.lane.0"/></leadsTo></lane>'
                '<lane id="s.lane.0"><startsAt meterFromLinkEnd="4.02"/></lane>'
                '</lanesToLinkAssignment></laneDefinitions>',encoding='utf-8')
            self.assertAlmostEqual(native_queue_ends(network,lanes)['s'],1.98)


class PerimeterInputTests(unittest.TestCase):
    def test_file_loader_verified_synthetic_geometry_provenance_and_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            paths = write_verified_test_inputs(Path(td))
            graph = load_model(paths['network'],paths['boundary'],paths['lanes'],paths['osm'],paths['access'])
            graph.validate_shares(named_percentages(MIX))
            self.assertEqual(graph.route('anchor-in','anchor-out'),CHAIN)
            self.assertEqual(graph.summary['boundary_sha256'],digest(paths['boundary']))
            self.assertEqual(graph.summary['access_version'],'synthetic-test-v1')
            self.assertAlmostEqual(graph.crossing_m['cross-out'],20,places=3)
            paths['lanes'].write_text('<laneDefinitions><!--changed--></laneDefinitions>',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'lanes_sha256'):
                load_model(paths['network'],paths['boundary'],paths['lanes'],paths['osm'],paths['access'])

    def test_missing_inputs_fail_before_creating_any_run(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)/'not-created'
            with self.assertRaisesRegex(ValueError,'disabled: missing --zone-boundary'):
                generar(Path(td)/'no-config.xml',target,SEED,od_mode=VARIANT)
            self.assertFalse(target.exists())
            with self.assertRaises(ValueError):
                input_options(None,None,MIX)

    def test_geojson_bbox_bad_polygon_and_hashes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            paths = {k:folder/k for k in ('network','lanes','osm','boundary','access')}
            for path in paths.values(): path.write_text('{}',encoding='utf-8')
            doc = fixture()[1]
            doc.update(network_sha256=digest(paths['network']),lanes_sha256=digest(paths['lanes']),osm_sha256=digest(paths['osm']))
            def attempt(boundary, mutate=None):
                paths['boundary'].write_text(json.dumps(boundary),encoding='utf-8')
                candidate = copy.deepcopy(doc)
                candidate['perimeter']['sha256'] = digest(paths['boundary'])
                if mutate: mutate(candidate)
                paths['access'].write_text(json.dumps(candidate),encoding='utf-8')
                return load_model(paths['network'],paths['boundary'],paths['lanes'],paths['osm'],paths['access'])
            for bad in ({'bbox':[0,0,10,10]}, {'type':'Polygon','coordinates':[]}):
                with self.subTest(bad=bad), self.assertRaises(ValueError): attempt(bad)
            with self.assertRaisesRegex(ValueError,'perimeter hash'):
                attempt(SQUARE,lambda d:d['perimeter'].update(sha256='0'*64))
            with self.assertRaisesRegex(ValueError,'verified provenance'):
                attempt(SQUARE,lambda d:d['perimeter'].update(verified=False))
            with self.assertRaisesRegex(ValueError,'network_sha256'):
                attempt(SQUARE,lambda d:d.update(network_sha256='0'*64))
            with self.assertRaisesRegex(ValueError,'Private access catalogue'):
                attempt(SQUARE,lambda d:d['review'].update(verified=False))


class SmallGenerationTests(unittest.TestCase):
    def generate(self, folder, graph=None):
        catalog = load_catalog(CATALOG)
        composition = split(100,catalog)
        temporal = temporal_spec()
        people,report,_ = gateway_people(graph or model(),SEED,dict(mode='montecarlo',kind='fixed',minimum=99,maximum=99),
            named_percentages(MIX),temporal,catalog=catalog,balanced_composition=composition,balanced_percentages=MIX)
        people = list(typed_people(people,report,catalog,99,SEED,1,temporal,folder/'types.jsonl',
                                  preserve_departures=True,preserve_catalog_departures=True))
        return people,report

    def test_reproducible_private_generation_routes_times_and_audit(self):
        with tempfile.TemporaryDirectory() as td:
            a,b = Path(td)/'a',Path(td)/'b'; a.mkdir(); b.mkdir()
            people,report = self.generate(a)
            again,other = self.generate(b)
            self.assertEqual([ET.tostring(p) for p in people],[ET.tostring(p) for p in again])
            self.assertEqual(report,other)
            self.assertEqual(len({p.get('id') for p in people}),99)
            self.assertEqual(Counter(p.findtext("attributes/attribute[@name='simz1VehicleFamily']") for p in people),
                             dict(carro=44,moto=55))
            catalog = load_catalog(CATALOG)
            for p in people:
                kind = p.findtext("attributes/attribute[@name='simz1AgentType']")
                expected = sample_departures(kind,1,SEED,p.get('id'),catalog)[0]
                self.assertEqual(float(p.find('plan/activity').get('end_time')),expected)
                raw = json.loads(p.findtext("attributes/attribute[@name='simz1SpatialOD']"))
                row = raw[trip_id(p.get('id'),1)]
                model().validate_metadata(row)
                route = p.find('plan/leg/route')
                from simz1_route_xml import validate_link_route
                self.assertEqual(validate_link_route(route, row['route_link_ids'],
                    origin=row['origin_link'], destination=row['destination_link'], vehicle_id=p.get('id')), row['route_link_ids'])
            population = ET.Element('population'); population.extend(people)
            ET.ElementTree(population).write(a/'plans.xml',encoding='utf-8',xml_declaration=True)
            verify_type_ledger(a/'plans.xml',a/'types.jsonl',catalog)
            audit = report['balanced_od_audit']
            self.assertEqual(audit['requested_non_public'],100)
            self.assertEqual(audit['private_vehicles'],99)
            self.assertEqual(audit['freight_vehicles'],1)
            self.assertEqual(set(audit['private_class_counts']),set(CLASSES))
            self.assertEqual(sum(audit['origins_by_link_length'].values()),99)
            self.assertEqual(sum(audit['private_departures_by_hour'].values()),99)
            self.assertEqual(audit['disconnected_routes'],0)
            self.assertEqual(audit['inaccessible_destinations'],0)
            self.assertTrue(all(v is None for v in audit['observed'].values()))
            self.assertEqual(len(report['spatial_demand']['hypothesis']['sha256']),64)
            records = {}
            for p in people:
                row = json.loads(p.findtext("attributes/attribute[@name='simz1SpatialOD']"))[trip_id(p.get('id'),1)]
                records[p.get('id')] = dict(row,planned_departure=float(p.find('plan/activity').get('end_time')))
            validate_scheduled_report(model(),split(100,catalog),report['spatial_demand'],records,audit)
            for key,value in (('private_departures_by_hour',{}),('origins_by_link_length',{}),
                              ('gateway_exits',{}),('top_20_origins',[]),('seed',0)):
                changed = copy.deepcopy(audit); changed[key] = value
                with self.subTest(key=key), self.assertRaisesRegex(ValueError,'report differs from plans'):
                    validate_scheduled_report(model(),split(100,catalog),report['spatial_demand'],records,changed)

    def test_capacity_failure_never_retimes_drops_or_relabels_persons(self):
        base,doc,ends,moves = fixture()
        doc['entry_gateways'][0]['incorporation_capacity_pcu_h'] = .00001
        graph = BalancedGatewayModel(base,doc,ends,moves)
        catalog = load_catalog(CATALOG)
        people,report,_ = gateway_people(graph,SEED,dict(mode='montecarlo',kind='fixed',minimum=1,maximum=1),
            dict(zip(LEGACY,(0,0,0,1))),temporal_spec(),catalog=catalog,balanced_composition=split(1,catalog),
            balanced_percentages=dict(zip(CLASSES,(0,0,0,100))))
        with self.assertRaisesRegex(ValueError,'No se cambian N, clase ni hora'):
            list(people)
        self.assertNotIn('balanced_od_audit',report)

    def test_pair_retries_preserve_type_class_schedule_and_N(self):
        graph = model(); catalog = load_catalog(CATALOG)
        sampled, accepted = [], []
        original_sample = graph.sample
        def sample(rng,kind,body):
            sampled.append((kind,body)); return original_sample(rng,kind,body)
        original_accept = IncorporationBudget.accept
        def accept(budget,row,hour,pcu):
            accepted.append((row['od_class'],hour,pcu))
            return False if len(accepted) % 2 else original_accept(budget,row,hour,pcu)
        with tempfile.TemporaryDirectory() as td, patch.object(graph,'sample',side_effect=sample), \
                patch.object(IncorporationBudget,'accept',new=accept):
            people,report = self.generate(Path(td),graph)
        self.assertEqual(len(people),99)
        self.assertEqual(len(sampled),198)
        for i in range(0,198,2):
            self.assertEqual(sampled[i],sampled[i+1])
            self.assertEqual(accepted[i],accepted[i+1])
        for p in people:
            kind = p.findtext("attributes/attribute[@name='simz1AgentType']")
            self.assertEqual(float(p.find('plan/activity').get('end_time')),sample_departures(kind,1,SEED,p.get('id'),catalog)[0])
        self.assertEqual(report['balanced_od_audit']['requested_non_public'],100)

    def test_network_mode_remains_explicit_and_new_options_do_not_leak(self):
        self.assertIsNone(spatial_options('network',None,None,mode='montecarlo',trips_per_person=1,
                                        temporal_profile=None,corridor_policy='redistribute'))
        self.assertIsNone(validate_manifest(Path('.'),{'spatial_demand':None}))
        with self.assertRaisesRegex(ValueError,'require balanced-gateway-v1'):
            generar('unused.xml','unused',SEED,od_mode='network',origin_policy=ORIGIN_POLICY)
        check_config(config())
        with self.assertRaisesRegex(ValueError,'global spatial whitelist'):
            check_config(dict(config(),**{'zona1SpatialRouting.allowedLinks':'origin-a'}))
        with self.assertRaises(ValueError):
            check_config(dict(config(),**{'qsim.removeStuckVehicles':'true'}))

    def test_cli_selects_variant_without_changing_network_defaults(self):
        parser = argparse.ArgumentParser()
        add_generation_options(parser)
        self.assertEqual(generation_options(parser.parse_args([]))['od_mode'],'network')
        options = generation_options(parser.parse_args(['--od-mode',VARIANT,'--origin-policy',ORIGIN_POLICY,
            '--destination-policy','lane-length-destinations-v1','--od-access-catalog','review.json',
            '--od-mix',json.dumps(MIX)]))
        self.assertEqual(options['od_mode'],VARIANT)
        self.assertEqual(options['od_access_catalog'],Path('review.json'))
        self.assertIsNone(options['od_hourly_profiles'])

    def test_prepared_xml_manifest_and_report_are_connected(self):
        from simz1_population import write_population, verify_population
        from simz1_run import artifact
        from simz1_freight import SCHEMA as FREIGHT_SCHEMA
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td); paths = write_verified_test_inputs(folder)
            graph = load_model(paths['network'],paths['boundary'],paths['lanes'],paths['osm'],paths['access'])
            people,report = self.generate(folder,graph)
            catalog = load_catalog(CATALOG)
            ET.ElementTree(vehicle_types_xml(catalog)).write(folder/'types.xml',encoding='utf-8')
            write_population(folder/'plans.xml',folder/'vehicles.xml',people,folder/'types.xml','Synthetic unit fixture')
            verified = verify_population(folder/'plans.xml',folder/'vehicles.xml',99,graph.eligible_links,
                                         expected_trips_per_person=1,require_trip_ids=True,spatial_model=graph)
            self.assertEqual(verified['scope'],'observed_z1_and_declared_anchors_only')
            self.assertEqual(verified['routing_scope'],'per_private_trip; no_global_whitelist')
            original_plans = (folder/'plans.xml').read_bytes()
            tampered = ET.fromstring(original_plans)
            tampered.find('person/plan/leg/route').set('vehicleRefId','another-vehicle')
            ET.ElementTree(tampered).write(folder/'plans.xml',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Explicit links XML'):
                verify_population(folder/'plans.xml',folder/'vehicles.xml',99,graph.eligible_links,
                                  expected_trips_per_person=1,require_trip_ids=True,spatial_model=graph)
            for attribute in ('start_link','end_link'):
                tampered = ET.fromstring(original_plans)
                tampered.find('person/plan/leg/route').set(attribute,'contradictory-link')
                ET.ElementTree(tampered).write(folder/'plans.xml',encoding='utf-8')
                with self.subTest(attribute=attribute), self.assertRaisesRegex(ValueError,'Explicit links XML'):
                    verify_population(folder/'plans.xml',folder/'vehicles.xml',99,graph.eligible_links,
                                      expected_trips_per_person=1,require_trip_ids=True,spatial_model=graph)
            (folder/'plans.xml').write_bytes(original_plans)
            # Dedicated freight is only a typed identity in this unit contract.
            # Its routes/buses are still checked by their existing independent
            # validators in real preparation/QSim; no synthetic service is approved.
            population = ET.parse(folder/'plans.xml')
            freight = ET.SubElement(population.getroot(),'person',id='freight_000001')
            attrs = ET.SubElement(freight,'attributes')
            ET.SubElement(attrs,'attribute',name='simz1FreightService').text = FREIGHT_SCHEMA
            population.write(folder/'plans.xml',encoding='utf-8')
            values = dict(config(),**{'global.coordinateSystem':'EPSG:32615',
                'network.inputNetworkFile':str(paths['network']),'network.laneDefinitionsFile':str(paths['lanes'])})
            cfg = ET.Element('config'); modules = {}
            for key,value in values.items():
                name,param = key.split('.',1)
                if name not in modules: modules[name] = ET.SubElement(cfg,'module',name=name)
                ET.SubElement(modules[name],'param',name=param,value=value)
            ET.ElementTree(cfg).write(folder/'config.xml',encoding='utf-8')
            (folder/'catalog.json').write_text(json.dumps(catalog),encoding='utf-8')
            (folder/'implementation.json').write_text(json.dumps(implementation_signature()),encoding='utf-8')
            audit = report['balanced_od_audit']; audit['buses_additional'] = dict(total=269,transmetro=176,tubus=93)
            (folder/'audit.json').write_text(json.dumps(audit),encoding='utf-8')
            spatial = report['spatial_demand']
            spatial['restriction_preflight'] = validate_osm_turns(paths['osm'],paths['network'],paths['lanes'])
            manifest = dict(demand_seed=SEED,matsim_seed=SEED,
                demand_composition=split(100,catalog),counts=dict(public_transport_vehicles_configured=269),
                spatial_demand=spatial,agent_configuration=dict(catalog_artifact=artifact(folder,folder/'catalog.json')),
                inputs={key:artifact(folder,path) for key,path in dict(config=folder/'config.xml',plans=folder/'plans.xml',
                    network=paths['network'],lanes=paths['lanes'],zone_boundary=paths['boundary'],od_source_osm=paths['osm']).items()},
                balanced_od=dict(variant=VARIANT,source_network=artifact(folder,paths['network']),
                    source_lanes=artifact(folder,paths['lanes']),access_catalog=artifact(folder,paths['access']),
                    implementation=artifact(folder,folder/'implementation.json'),audit=artifact(folder,folder/'audit.json')))
            _,records = validate_manifest(folder,manifest)
            self.assertEqual(len(records),99)
            self.assertNotIn('freight_000001',records)
            valid_plans = (folder/'plans.xml').read_bytes()
            for attribute in ('start_link','end_link','vehicleRefId'):
                tampered = ET.fromstring(valid_plans)
                tampered.find('person/plan/leg/route').set(attribute,'contradiction')
                ET.ElementTree(tampered).write(folder/'plans.xml',encoding='utf-8')
                altered = copy.deepcopy(manifest)
                altered['inputs']['plans'] = artifact(folder,folder/'plans.xml')
                with self.subTest(auditor_attribute=attribute), self.assertRaisesRegex(ValueError,'Explicit links XML'):
                    validate_manifest(folder,altered)
            (folder/'plans.xml').write_bytes(valid_plans)
            # Even replacing the file hash cannot make an incorrect report pass.
            audit['private_departures_by_hour']['07:00'] += 1
            (folder/'audit.json').write_text(json.dumps(audit),encoding='utf-8')
            manifest['balanced_od']['audit'] = artifact(folder,folder/'audit.json')
            with self.assertRaisesRegex(ValueError,'report differs from plans'):
                validate_manifest(folder,manifest)
            broken = copy.deepcopy(manifest); broken.pop('balanced_od')
            with self.assertRaisesRegex(ValueError,'Missing balanced OD'):
                validate_manifest(folder,broken)


class NativePrivateAuditTests(unittest.TestCase):
    def audit(self, kind='external-external'):
        row = dict(record(kind),planned_departure=0.)
        return PrivateODAudit(model(),{'private':row}),row

    def evidence(self, audit, link, front, action='TRANSFER'):
        time = max(0.,audit.last_time+1)
        if link not in audit.domains:
            audit.consume(dict(type='simz1OccupancyDomain',link=link,corridor=link,linkOffsetMeters='0'))
        if audit.active.get('private',{}).get('corridor') != link:
            audit.consume(dict(type='simz1OccupancyReservation',vehicle='private',action=action,
                               corridor=link,link=link,bodyLengthMeters='4.5',footprintMeters='4.6',time=str(time)))
        audit.consume(dict(type='simz1OccupancyProgress',vehicle='private',corridor=link,link=link,
                           modeledFrontLowerBoundMeters=str(front),time=str(time)))

    def travel(self, audit, row):
        audit.consume(dict(type='departure',person='private',link=row['origin_link'],time='0'))
        self.evidence(audit,row['origin_link'],5,'ENTER')
        audit.consume(dict(type='vehicle enters traffic',person='private',vehicle='private',link=row['origin_link'],time='1'))
        # The native optional origin event must not add a second origin link.
        audit.consume(dict(type='entered link',vehicle='private',link=row['origin_link'],time='1'))
        for index,(previous,link) in enumerate(zip(row['route_link_ids'],row['route_link_ids'][1:]),2):
            audit.consume(dict(type='left link',vehicle='private',link=previous,time=str(index)))
            audit.consume(dict(type='entered link',vehicle='private',link=link,time=str(index)))

    def test_no_clock_end_or_link_entry_fabricates_an_arrival(self):
        audit,row = self.audit()
        self.assertEqual(audit.summary()['never_incorporated'],1)
        self.assertEqual(audit.summary()['never_observed'],1)
        self.assertEqual(audit.summary()['waiting_to_incorporate'],0)  # No departure evidence yet.
        self.travel(audit,row)
        self.assertEqual(audit.summary()['circulating'],1)
        self.assertEqual(audit.summary()['completed'],0)
        audit.consume(dict(type='clock-end',time='86400'))
        self.assertEqual(audit.summary()['not_arrived'],1)
        with self.assertRaises(ValueError):
            audit.consume(dict(type='arrival',person='private',link=row['destination_link'],time='20'))

    def test_full_native_body_clearance_is_required_for_exterior_arrival(self):
        graph = BalancedGatewayModel(*fixture(exit_near_boundary=True))
        row = graph.sample(random.Random(SEED),'external-external')
        row = {k:v for k,v in row.items() if k not in ('origin_xy','destination_xy')}
        row['planned_departure'] = 0.
        audit = PrivateODAudit(graph,{'private':row})
        self.travel(audit,row)
        gateway = audit.model.exit_gateways['anchor-out']
        cut = gateway['crossing_distance_m']-sum(audit.model.links[k]['length'] for k in gateway['link_ids'][:-1])
        self.assertGreater(cut+4.6-.01,0)
        self.assertLess(cut+4.6,graph.queue_ends['anchor-out'])
        self.evidence(audit,'anchor-out',cut+4.6-.01)
        with self.assertRaisesRegex(ValueError,'whole-body'):
            audit.consume(dict(type='vehicle leaves traffic',vehicle='private',link='anchor-out',time='100'))
        self.evidence(audit,'anchor-out',cut+4.6)
        audit.consume(dict(type='vehicle leaves traffic',vehicle='private',link='anchor-out',time='101'))
        self.assertEqual(audit.summary()['completed'],0)
        audit.consume(dict(type='arrival',person='private',link='anchor-out',time='101'))
        self.assertEqual(audit.summary()['completed'],1)
        self.assertEqual(audit.summary()['not_arrived'],0)
        self.assertIn('private',audit.summary()['external_clearance_proofs'])
        audit.consume(dict(type='simz1OccupancyReservation',vehicle='private',action='EXIT',time='101'))
        self.assertEqual(audit.finish()['verified_exterior_arrivals'],1)
        self.assertEqual(audit.summary()['internal_destination_arrivals'],0)

    def test_freight_transmetro_tubus_are_not_subject_to_private_whitelist(self):
        audit,_ = self.audit()
        for ident in ('freight_001','transmetro_001','tubus_001'):
            audit.consume(dict(type='entered link',vehicle=ident,link='legitimate-service-only-link'))
            audit.consume(dict(type='arrival',person=ident,link='legitimate-service-only-link'))
        self.assertEqual(audit.summary()['incorporated'],0)
        self.assertEqual(audit.summary()['completed'],0)

    def test_duplicate_insertion_repeated_crossing_and_wrong_gateway_rejected(self):
        audit,row = self.audit()
        self.travel(audit,row)
        with self.assertRaises(ValueError):
            audit.consume(dict(type='vehicle enters traffic',vehicle='private',link=row['origin_link'],time='20'))
        for path in (CHAIN+['cross-out'],CHAIN[:-1],['observe-in']+CHAIN[3:]):
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit.validate_observed_route('private',path,complete=True)

    def test_optional_initial_link_event_is_not_an_extra_movement(self):
        audit,row = self.audit()
        self.travel(audit,row)
        self.assertEqual(audit.paths['private'],row['route_link_ids'])
        self.assertEqual(audit.summary()['observed_link_transitions'],len(row['route_link_ids'])-1)
        with self.assertRaisesRegex(ValueError,'preceding LinkLeave'):
            audit.consume(dict(type='entered link',vehicle='private',link='anchor-out',time='20'))

    def test_other_vehicle_cannot_supply_private_clearance_evidence(self):
        audit,row = self.audit()
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            audit.consume(dict(type='vehicle enters traffic',person='private',vehicle='another-vehicle',
                               link=row['origin_link'],time='0'))
        with self.assertRaisesRegex(ValueError,'native insertion'):
            audit.consume(dict(type='vehicle enters traffic',person='private',vehicle='private',
                               link=row['origin_link'],time='0'))  # No departure.

    def test_departure_before_incorporation_is_not_an_arrival(self):
        audit,row = self.audit()
        audit.consume(dict(type='departure',person='private',link=row['origin_link'],time='0'))
        self.assertEqual(audit.summary()['waiting_to_incorporate'],1)
        self.assertEqual(audit.summary()['never_observed'],0)
        self.assertEqual(audit.summary()['completed'],0)
        with self.assertRaisesRegex(ValueError,'Duplicate/wrong private departure'):
            audit.consume(dict(type='departure',person='private',link=row['origin_link'],time='0'))

    def test_missing_release_or_arrival_prevents_event_acceptance(self):
        audit,row = self.audit()
        with self.assertRaisesRegex(ValueError,'Incomplete private event evidence'):
            audit.finish()
        self.travel(audit,row)
        with self.assertRaisesRegex(ValueError,'Incomplete private event evidence'):
            audit.finish()
        self.evidence(audit,'anchor-out',5)
        audit.consume(dict(type='vehicle leaves traffic',person='private',vehicle='private',link='anchor-out',time='20'))
        audit.consume(dict(type='simz1OccupancyReservation',vehicle='private',action='EXIT',time='20'))
        with self.assertRaisesRegex(ValueError,'Incomplete private event evidence'):
            audit.finish()  # Native departure from road is not PersonArrival.
        self.assertFalse(audit.finalized)
        self.assertEqual(audit.summary()['completed'],0)

    def test_native_cleanup_preserves_an_incomplete_trip(self):
        audit,row = self.audit()
        self.travel(audit,row)
        audit.consume(dict(type='simz1OccupancyReservation',vehicle='private',action='EXIT',time='86400'))
        result = audit.finish()
        self.assertEqual(result['completed'],0)
        self.assertEqual(result['not_arrived'],1)
        self.assertEqual(result['circulating'],1)
        self.assertEqual(result['verified_exterior_arrivals'],0)
        self.assertEqual(result['evidence_status'],'closed_native_event_stream')

    def test_interior_arrival_is_reported_separately(self):
        audit,row = self.audit('internal-internal')
        self.travel(audit,row)
        audit.consume(dict(type='vehicle leaves traffic',person='private',vehicle='private',link=row['destination_link'],time='20'))
        audit.consume(dict(type='arrival',person='private',link=row['destination_link'],time='20'))
        audit.consume(dict(type='simz1OccupancyReservation',vehicle='private',action='EXIT',time='20'))
        result = audit.finish()
        self.assertEqual(result['internal_destination_arrivals'],1)
        self.assertEqual(result['verified_exterior_arrivals'],0)
        self.assertEqual(result['external_clearance_proofs'],{})

    def test_truncated_xml_never_reaches_finalization(self):
        from simz1_run import xml_elements, checked_path, artifact
        audit,row = self.audit()
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            path = folder/'events.xml'
            event = ET.Element('event',type='departure',person='private',link=row['origin_link'],time='0')
            path.write_bytes(b'<events>'+ET.tostring(event))  # Missing closing events.
            with self.assertRaises(ET.ParseError):
                for e in xml_elements(path,'event','events'):
                    audit.consume(e.attrib)
                audit.finish()
            self.assertFalse(audit.finalized)
            record = artifact(folder,path)
            path.write_bytes(b'<events/>')
            with self.assertRaisesRegex(ValueError,'Hash no coincide'):
                checked_path(folder,record)
        self.assertEqual(audit.summary()['completed'],0)

    def test_failed_execution_is_not_promoted_by_a_prepared_quota(self):
        from simz1_run import validate_outputs
        for status,code,origin in (('failed',0,'natural_exit'),('failed',1,'natural_exit'),
                                   ('running',None,'pending'),('prepared',0,'natural_exit')):
            state = dict(status=status,returncode=code,returncode_origin=origin,balanced_od=dict(variant=VARIANT))
            before = copy.deepcopy(state)
            with self.subTest(state=state), self.assertRaisesRegex(ValueError,'successful native execution'):
                validate_outputs(Path('unused'),state)
            self.assertEqual(state,before)
        require_native_success(dict(status='running',returncode=0,returncode_origin='natural_exit'))


if __name__ == '__main__':
    unittest.main()
