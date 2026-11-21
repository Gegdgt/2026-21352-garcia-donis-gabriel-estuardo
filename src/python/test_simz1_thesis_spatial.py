import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import matplotlib.pyplot as plt
from simz1_thesis_spatial import ab_hourly, candidate_pairs, read_network, render_spatial, load_indicators, _separate_annotations


class Sink:
    def __init__(self): self.items = []
    def save(self, fig, stem, rows, metadata):
        self.items.append((stem, rows, metadata))
        plt.close(fig)


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = self.root/'network.xml'
        self.network.write_text('<network><attributes><attribute name="coordinateReferenceSystem">EPSG:32615</attribute></attributes><nodes><node id="1" x="10" y="10"/><node id="2" x="20" y="20"/><node id="3" x="30" y="10"/></nodes><links><link id="a" from="1" to="2"/><link id="b" from="2" to="3"/><link id="c" from="3" to="1"/></links></network>')
        self.identity = {'run_id':'r', 'iteration':2, 'N_configured':55017, 'time_horizon':{'start_seconds':0, 'end_seconds':86400}}
        self.path = self.root/'trips.csv.gz'
        self.rows = [dict(run_id='r', iteration=2, departure_link='a', arrival_link='b', status='completed', departure=100, duration_seconds=60),
                     dict(run_id='r', iteration=2, departure_link='a', arrival_link='b', status='completed', departure=200, duration_seconds=180),
                     dict(run_id='r', iteration=2, departure_link='a', arrival_link='', status='censored', departure=300, duration_seconds=''),
                     dict(run_id='r', iteration=2, departure_link='b', arrival_link='c', status='completed', departure=4000, duration_seconds=120)]
        self.write()
        self.bundle={'identity':self.identity,'network_path':self.network,'trips_path':self.path}
    def write(self):
        with gzip.open(self.path,'wt',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(self.rows[0]));writer.writeheader();writer.writerows(self.rows)
    def ab(self):
        self.bundle['ab_definition']={'origin_link':'a','destination_link':'b','network_sha256':hashlib.sha256(self.network.read_bytes()).hexdigest(),'time_basis':'departure','duration_definition':'arrival_minus_departure'}
    def test_candidates_exact_counts_and_no_times(self):
        _,links,_=read_network(self.network)
        rows,stats=candidate_pairs(self.path,self.identity,links)
        self.assertEqual(rows[0]['completed_observations'],2)
        self.assertEqual(stats['excluded_observations'],1)
        self.assertNotIn('duration',json.dumps(rows))
    def test_ab_exact_endpoints_quantiles_empty_hours(self):
        self.ab();rows,stats=ab_hourly(self.bundle)
        self.assertEqual(rows[0]['median_minutes'],2)
        self.assertAlmostEqual(rows[0]['p95_minutes'],2.9)
        self.assertIsNone(rows[1]['mean_minutes'])
        self.assertEqual(len(rows),24)
        self.assertEqual(stats['excluded_observations'],2)
    def test_wrong_identity_rejected(self):
        self.rows[0]['run_id']='other';self.write()
        with self.assertRaisesRegex(ValueError,'Identidad'):
            candidate_pairs(self.path,self.identity,read_network(self.network)[1])
    def test_unknown_link_rejected(self):
        self.rows[0]['departure_link']='unknown';self.write()
        with self.assertRaisesRegex(ValueError,'ausente'):
            candidate_pairs(self.path,self.identity,read_network(self.network)[1])
    def test_ab_network_mismatch_rejected(self):
        self.ab();self.bundle['ab_definition']['network_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'otra red'):ab_hourly(self.bundle)
    def test_nonfinite_time_rejected(self):
        self.ab();self.rows[0]['duration_seconds']='nan';self.write()
        with self.assertRaisesRegex(ValueError,'no finito'):ab_hourly(self.bundle)
    def test_candidates_and_pending_are_not_flow_results(self):
        sink=Sink();result=render_spatial(self.bundle,sink)
        self.assertEqual([i[0] for i in sink.items],['candidatos_ab'])
        self.assertEqual({r['indicator'] for r in result['pending']},{'intersection_accumulation','corridor_flow','ab'})
    def test_ab_render(self):
        self.ab();sink=Sink();render_spatial(self.bundle,sink)
        self.assertEqual(sink.items[0][0],'tiempo_ab_por_hora')
    def test_multiple_iterations_reject_unselected_rows(self):
        self.rows[0]['iteration']=1;self.write()
        with self.assertRaisesRegex(ValueError,'Identidad'):
            candidate_pairs(self.path,self.identity,read_network(self.network)[1])
    def test_missing_inputs_pending(self):
        sink=Sink();result=render_spatial({'identity':self.identity},sink)
        self.assertEqual(result['pending'][-1]['status'],'pending');self.assertFalse(sink.items)

    def pack(self):
        self.identity['manifest_sha256']='m'*64
        self.bundle['manifest']={'results':{'2':{'events':{'sha256':'e'*64}}}}
        self.crossings=self.root/'crossings.csv'
        self.crossings.write_text('run_id,iteration,time_seconds,vehicle_id,link_id\nr,2,10,v1,a\nr,2,20,v1,a\nr,2,30,v2,a\nr,2,4000,v1,a\nr,2,5000,v1,c\n')
        self.occupancy=self.root/'occupancy.csv'
        self.occupancy.write_text('run_id,iteration,intersection_id,start_seconds,end_seconds,occupancy_vehicles\nr,2,i1,0,1800,2\nr,2,i1,1800,3600,4\nr,2,i1,3600,3700,1\n')
        self.pack_data={'schema':'simz1-thesis-indicators-v1','run_id':'r','iteration':2,
            'manifest_sha256':'m'*64,'network_sha256':hashlib.sha256(self.network.read_bytes()).hexdigest(),
            'source_events_sha256':'e'*64,'source_version':'fixture-v1','population_scope':'all_physical_vehicles',
            'coverage':{'start_seconds':0,'end_seconds':86400,'complete':True},
            'definitions':{'directed_sections':[{'id':'s1','label':'Sección 1','direction':'NE','boundary_links':['a']}],
                'intersection_occupancy':{'unit':'vehicles','method':'time_weighted_piecewise_constant',
                    'physical_definition':'Fixture: cuerpos dentro de dominio definido, no WAIT',
                    'intersections':[{'id':'i1','label':'Cruce 1','node_id':'2','link_ids':['a','b']}]}},
            'files':{'crossings':{'path':'crossings.csv','sha256':hashlib.sha256(self.crossings.read_bytes()).hexdigest()},
                     'occupancy':{'path':'occupancy.csv','sha256':hashlib.sha256(self.occupancy.read_bytes()).hexdigest()}}}
        self.pack_path=self.root/'indicators.json';self.save_pack()
    def save_pack(self):self.pack_path.write_text(json.dumps(self.pack_data),encoding='utf-8')
    def test_crossings_deduplicated_with_complete_coverage(self):
        self.pack();data=load_indicators(self.pack_path,self.bundle)
        self.assertEqual(data['section_hour'][0]['vehicles_per_hour'],2)
        self.assertEqual(data['section_hour'][1]['vehicles_per_hour'],1)
        self.assertEqual(data['section_hour'][2]['vehicles_per_hour'],0)
        self.assertEqual(data['section_statistics']['excluded_other_links'],1)
    def test_occupancy_time_weighted_missing_not_zero(self):
        self.pack();data=load_indicators(self.pack_path,self.bundle)
        self.assertEqual(data['occupancy_hour'][0]['mean_occupancy_vehicles'],3)
        self.assertIsNone(data['occupancy_hour'][1]['mean_occupancy_vehicles'])
        self.assertEqual(data['occupancy_hour'][1]['covered_seconds'],100)
        self.assertIsNone(data['occupancy_hour'][2]['mean_occupancy_vehicles'])
    def test_indicator_hash_mutation_rejected(self):
        self.pack();self.crossings.write_text(self.crossings.read_text()+'r,2,6000,v9,a\n')
        with self.assertRaisesRegex(ValueError,'modificado'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_manifest_identity_rejected(self):
        self.pack();self.pack_data['manifest_sha256']='wrong';self.save_pack()
        with self.assertRaisesRegex(ValueError,'manifest_sha256'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_missing_file_rejected(self):
        self.pack();self.pack_data['files']['crossings']['path']='absent.csv';self.save_pack()
        with self.assertRaisesRegex(ValueError,'ausente'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_wait_unit_rejected(self):
        self.pack();self.pack_data['definitions']['intersection_occupancy']['unit']='WAIT_attempts';self.save_pack()
        with self.assertRaisesRegex(ValueError,'WAIT'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_overlap_rejected(self):
        self.pack();self.occupancy.write_text(self.occupancy.read_text().replace('1800,3600,4','1700,3600,4'))
        self.pack_data['files']['occupancy']['sha256']=hashlib.sha256(self.occupancy.read_bytes()).hexdigest();self.save_pack()
        with self.assertRaisesRegex(ValueError,'superpuestos'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_rendered_and_no_false_pending(self):
        self.pack();self.bundle['indicators']=load_indicators(self.pack_path,self.bundle);sink=Sink()
        result=render_spatial(self.bundle,sink)
        self.assertEqual(result['figures'],['candidatos_ab','flujo_secciones','acumulacion_intersecciones'])
        self.assertEqual([p['indicator'] for p in result['pending']],['ab'])
    def test_indicator_half_hour_has_no_fake_hourly_flow(self):
        self.pack();self.pack_data['coverage']['end_seconds']=5400;self.save_pack()
        data=load_indicators(self.pack_path,self.bundle)
        self.assertEqual(data['section_hour'][1]['coverage_seconds'],1800)
        self.assertIsNone(data['section_hour'][1]['vehicles_per_hour'])
        self.assertIsNone(data['section_hour'][2]['distinct_vehicles'])
    def test_indicator_unknown_native_link_rejected_after_resigning(self):
        self.pack();self.crossings.write_text(self.crossings.read_text().replace('5000,v1,c','5000,v1,absent'))
        self.pack_data['files']['crossings']['sha256']=hashlib.sha256(self.crossings.read_bytes()).hexdigest();self.save_pack()
        with self.assertRaisesRegex(ValueError,'enlace ausente'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_iteration_type_rejected(self):
        self.pack();self.pack_data['iteration']=2.0;self.save_pack()
        with self.assertRaisesRegex(ValueError,'entero'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_missing_or_subset_scope_rejected(self):
        for scope in (None, 'cars_only'):
            self.pack()
            if scope is None: self.pack_data.pop('population_scope')
            else: self.pack_data['population_scope']=scope
            self.save_pack()
            with self.assertRaisesRegex(ValueError,'all_physical_vehicles'):load_indicators(self.pack_path,self.bundle)
    def test_indicator_formal_ab_selected(self):
        self.pack();self.pack_data['definitions']['ab']={'origin_link':'a','destination_link':'b','time_basis':'departure','duration_definition':'arrival_minus_departure'}
        self.save_pack();self.bundle['indicators']=load_indicators(self.pack_path,self.bundle);sink=Sink()
        result=render_spatial(self.bundle,sink)
        self.assertEqual(result['figures'][0],'tiempo_ab_por_hora')
        self.assertEqual(result['pending'],[])
    def test_candidate_shared_origin_one_label(self):
        class FigureSink(Sink):
            def save(inner,fig,stem,rows,metadata):
                labels=[t.get_text() for t in fig.axes[0].texts]
                self.assertIn('A1, A2',labels)
                self.assertNotIn('A1',labels)
                super(FigureSink,inner).save(fig,stem,rows,metadata)
        self.rows[3]['departure_link']='a';self.write()
        render_spatial(self.bundle,FigureSink())
    def test_close_labels_separate_without_moving_native_points(self):
        fig,ax=plt.subplots(figsize=(6,5));ax.set(xlim=(0,3),ylim=(0,3))
        anchors=[(1.45,2.6),(1.52,2.59)]
        labels=[ax.annotate(name,point,xytext=(7,8),textcoords='offset points',fontsize=10)
                for name,point in zip(['A2','A3'],anchors)]
        _separate_annotations(fig,ax,labels)
        fig.canvas.draw();renderer=fig.canvas.get_renderer()
        self.assertFalse(labels[0].get_window_extent(renderer).overlaps(labels[1].get_window_extent(renderer)))
        self.assertEqual([item.xy for item in labels],anchors)
        plt.close(fig)


if __name__ == '__main__':unittest.main()
