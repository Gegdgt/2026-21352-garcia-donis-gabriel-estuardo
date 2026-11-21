"""Prepared synthetic stop evidence tests; never generate demand or run a server.

All approved/verified values below belong to fabricated unit fixtures only.
No fixture is written into the real evidence catalog or loaded by the server.
"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from simz1_transit_stops import (SCHEMA, build_stop_display, load_stop_display, service_system,
                                build_catalog_annotations, read_json, transit_usage)
from simz1_transit_catalog import DEFAULT_DIRECTORY


class TransitStopTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(run_id='synthetic-only', iteration=0, run_manifest_sha256='a'*64)
        self.sources = {'sources': [dict(source_id='transmetro-stations-gis', url='https://example.invalid/fixture',
                                         license={'id': 'synthetic-only'}, accessed_on='2026-10-22')]}
        source = 'transmetro-stations-gis'
        self.catalog = dict(review_date='2026-10-22', production_enabled=False,
            domain=dict(approved=True, crs='EPSG:4326', link_ids=['east', 'west'],
                        geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}), services=[])
        for ident, line in [('transmetro-test','F1'),('tubus-test','F2')]:
            self.catalog['services'].append(dict(service_id=ident, line=line, operator='Same synthetic operator',
                record_kind='service_candidate', sources=[source],
                verification={'field_status':{'line':{'status':'verified'}}},
                coordinates=dict(artifact='municipal-gis.json',layer_source_id=source,feature_ids=[1,2])))
        self.artifacts = {'municipal-gis.json': {'layers': [dict(source_id=source,
            returned_coordinates='EPSG:4326; longitude,latitude', data={'features':[
                {'id':1,'geometry':{'type':'Point','coordinates':[.5,.51]}},
                {'id':2,'geometry':{'type':'Point','coordinates':[.5,.49]}}]})]}}
        self.network = dict(sha256='b'*64, links={
            'east':dict(from_node='a',to_node='b',path=[[.1,.5],[.9,.5]]),
            'west':dict(from_node='b',to_node='a',path=[[.9,.5],[.1,.5]])})
        self.mapping = dict(schema_version=SCHEMA, synthetic=False, catalog_sha256='c'*64,
                            network_sha256='b'*64, source_registry_sha256='d'*64, review_date='2026-10-22', stops=[])
        for ident, link, feature, service in [('e','east',1,'transmetro-test'),('w','west',2,'tubus-test')]:
            self.mapping['stops'].append(dict(stop_id=ident,name='Synthetic '+ident,
                access=dict(status='verified',sources=[source],link_id=link,from_node='a' if ident=='e' else 'b',
                            to_node='b' if ident=='e' else 'a',placement='roadside_platform',direction=link,path_segment_index=0),
                services=[dict(status='verified',sources=[source],service_id=service,direction=link,
                    coordinate_evidence=dict(artifact='municipal-gis.json',source_id=source,feature_id=feature))],
                transfer=None,opposed_stop_ids=['w' if ident=='e' else 'e'],
                opposed_evidence=dict(status='verified',sources=[source])))

    def build(self):
        return build_stop_display(self.catalog,self.sources,self.mapping,self.artifacts,self.network,self.identity,'c'*64,'d'*64)

    def test_service_not_operator_and_exact_source_points(self):
        result = self.build()
        self.assertEqual(len(result['records']),2)
        self.assertEqual([row['services'][0]['system'] for row in result['records']],['transmetro','tubus'])
        self.assertEqual([row['position'] for row in result['records']],[[.5,.51],[.5,.49]])
        self.assertEqual([row['bearing_degrees'] for row in result['records']],[90,270])
        self.assertEqual(result['records'][0]['opposed_stop_ids'],['w'])

    def test_tubus_cannot_be_relabelled_green(self):
        self.catalog['services'][1]['service_system']='transmetro'
        self.assertIn('contradictory_service_system',self.build()['counts']['reasons'])

    def test_all_blue_families_require_service_identity(self):
        for ident, explicit, expected in [('transurbano-test',None,'transurbano'),
                                         ('reviewed-urban','urbano','urbano'),('reviewed-regional','extraurbano','extraurbano')]:
            self.assertEqual(service_system(dict(service_id=ident,service_system=explicit,operator='Transmetro')),expected)
        with self.assertRaisesRegex(ValueError,'unknown_service_system'):
            service_system(dict(service_id='unknown',operator='Transmetro'))

    def test_invalid_direction_does_not_snap_to_opposite_road(self):
        self.mapping['stops'][0]['access']['link_id']='west'
        result=self.build()
        self.assertEqual(len(result['records']),1)
        self.assertIn('directed_access_mismatch',result['counts']['reasons'])

    def test_missing_direction_or_platform_review_rejected(self):
        for field,value in [('direction',None),('placement','intersection_center'),('status','pending'),('path_segment_index',5)]:
            with self.subTest(field=field):
                before=deepcopy(self.mapping)
                self.mapping['stops'][0]['access'][field]=value
                self.assertEqual(len(self.build()['records']),1)
                self.mapping=before

    def test_approved_domain_required_and_bbox_is_not_boundary(self):
        self.catalog['domain']=dict(approved=False,download_rectangle=[0,0,1,1])
        result=self.build()
        self.assertFalse(result['available']);self.assertFalse(result['records'])
        self.assertIn('approved_domain_missing',[item['reason'] for item in result['issues']])

    def test_outside_polygon_and_domain_link_rejected(self):
        self.artifacts['municipal-gis.json']['layers'][0]['data']['features'][0]['geometry']['coordinates']=[1.5,.51]
        self.assertIn('outside_approved_domain_position',self.build()['counts']['reasons'])
        self.catalog['domain']['link_ids']=['east']
        self.assertIn('outside_approved_domain_link',self.build()['counts']['reasons'])

    def test_no_point_or_source_or_membership(self):
        for mutation in ('geometry','sources','membership'):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation=='geometry':self.artifacts['municipal-gis.json']['layers'][0]['data']['features'][0]['geometry']['type']='LineString'
                elif mutation=='sources':self.mapping['stops'][0]['access']['sources']=[]
                else:self.catalog['services'][0]['coordinates']['feature_ids']=[]
                self.assertEqual(len(self.build()['records']),1)

    def test_transfer_only_with_explicit_evidence_and_same_platform(self):
        row=self.mapping['stops'][0]
        second=deepcopy(row['services'][0]);second['service_id']='tubus-test';row['services'].append(second)
        row['transfer']=dict(id='fixture-hub',name='Synthetic hub',status='verified',sources=['transmetro-stations-gis'])
        self.assertEqual(len(self.build()['records'][0]['services']),2)
        second['coordinate_evidence']['feature_id']=2
        self.assertIn('different_platform_coordinates_cannot_be_merged',self.build()['counts']['reasons'])

    def test_agency_and_unverified_blue_membership_are_not_stops(self):
        self.catalog['services'][1]['record_kind']='agency_lead_not_verified_service'
        self.mapping['stops'][0]['services'][0]['status']='pending'
        self.assertEqual(self.build()['records'],[])

    def test_changed_network_and_catalog_are_rejected(self):
        for key in ('network_sha256','catalog_sha256','source_registry_sha256'):
            with self.subTest(key=key):
                before=self.mapping[key];self.mapping[key]='e'*64
                with self.assertRaises(ValueError):self.build()
                self.mapping[key]=before

    def test_duplicate_stop_identity_rejected(self):
        self.mapping['stops'][1]['stop_id']='e'
        with self.assertRaisesRegex(ValueError,'duplicate_or_missing_stop_id'):self.build()

    def test_current_catalog_annotations_without_scanning_network_or_runs(self):
        with patch('simz1_transit_stops.effective_network',side_effect=AssertionError('Must not load native network')):
            result=load_stop_display(Path('not-a-run'),{},self.identity)
        self.assertEqual(len(result['records']),10)
        self.assertEqual(result['source_station_records'],52)
        self.assertIn('approved_domain_missing',[row['reason'] for row in result['native_mapping_issues']])
        self.assertEqual(result['simulation_usage']['status'],'unknown')
        self.assertEqual(result['issues'],[])
        self.assertTrue(all('Link_ID' not in row and 'bearing_degrees' not in row for row in result['records']))
        self.assertTrue(all(row['simulation_usage']['used_by_simulation'] is None for row in result['records']))
        self.assertEqual(len([r for r in result['records'] if r['services'][0]['system']=='transmetro']),9)
        self.assertEqual(len([r for r in result['records'] if r['services'][0]['system']=='tubus']),1)
        transfer=next(r for r in result['records'] if r['transfer'])
        self.assertEqual([s['line'] for s in transfer['services']],['L1','L2'])
        self.assertEqual(transfer['position'],[-90.5130566,14.6458228])
        blue=next(r for r in result['records'] if r['services'][0]['system']=='tubus')
        self.assertEqual(blue['position'],[-90.5072051,14.6397793])
        self.assertEqual(len(blue['services'][0]['directions']),2)

    def test_catalog_missing_coordinate_direction_official_source_and_conflict(self):
        root=Path(DEFAULT_DIRECTORY)
        catalog,ch=read_json(root/'catalog.json'); sources,sh=read_json(root/'sources.json')
        mapping,_=read_json(root/'catalog-display.json')
        artifacts={name:read_json(root/name)[0] for name in ('municipal-gis.json','osm-evidence.json')}
        for mutation in ('coordinate','direction','official','conflict','hash','duplicate'):
            with self.subTest(mutation=mutation):
                m,a=deepcopy(mapping),deepcopy(artifacts)
                stop=m['stops'][0];member=stop['services'][0]
                if mutation=='coordinate':
                    next(s for s in a['osm-evidence.json']['stops'] if s['stop_id']==stop['stop_id'])['coordinates']=None
                elif mutation=='direction':member['relation_ids']=['18672965']
                elif mutation=='official':member['official_stop_evidence']['sources']=['osm-snapshot']
                elif mutation=='conflict':
                    feature=next(f for l in a['municipal-gis.json']['layers'] if l['source_id']=='transmetro-stations-gis'
                                 for f in l['data']['features'] if f['id']==1)
                    feature['geometry']['coordinates'][0]+=.01
                elif mutation=='hash':m['catalog_sha256']='bad'
                else:m['stops'].append(deepcopy(stop))
                if mutation in ('hash','duplicate'):
                    with self.assertRaises(ValueError):build_catalog_annotations(catalog,sources,m,a,self.identity,ch,sh)
                else:
                    result=build_catalog_annotations(catalog,sources,m,a,self.identity,ch,sh)
                    self.assertEqual(len(result['records']),9)
                    self.assertEqual(len(result['issues']),1)

    def test_historical_run_without_public_transport_does_not_claim_stop_usage(self):
        run=dict(run_id=self.identity['run_id'],validation={'status':'valid'},
                 effective_config={'path':'synthetic.xml','sha256':'f'*64})
        for enabled,status,used in [('false','not_configured',False),('true','usage_not_established',None)]:
            with patch('simz1_run.checked_path',return_value=Path('synthetic.xml')), \
                 patch('simz1_run.parameters',return_value={'transit.useTransit':enabled}):
                result=transit_usage(Path('.'),run,self.identity)
            self.assertEqual(result['status'],status)
            self.assertIs(result['used_by_simulation'],used)


if __name__=='__main__':
    unittest.main()
