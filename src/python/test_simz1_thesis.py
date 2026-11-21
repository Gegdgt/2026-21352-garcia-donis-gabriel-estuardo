"""Small publication/identity fixtures; no MATSim, replay or native events."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import matplotlib.pyplot as plt

from simz1_thesis import (Publisher, compatibility, comparison_rows, configured_n,
    csv_rows, generate_comparison, load_bundle, reconcile_intervals, safe_output, compare_spatial, attach_indicators,
    sha, style, write_json)


def fixture(root, name='fixture-a', n=12345, iterations=(0,)):
    run=root/name;run.mkdir()
    native=dict(schema_version=1,run_id=name,folder=str(run.resolve()),
        status='completed',validation={'status':'valid'},counts={'non_public_vehicles_configured':n},
        iterations={'first':min(iterations),'last':max(iterations),'requested':len(iterations),'completed':list(iterations)},
        time_horizon={'start_seconds':0,'end_seconds':86400},demand_seed=42,matsim_seed=42,
        inputs={},results={str(i):{'observed_event_end_seconds':86400} for i in iterations})
    write_json(run/'run-manifest.json',native)
    for it in iterations:
        d=run/'analysis'/f'it.{it}';(d/'graficas_perfiles').mkdir(parents=True)
        report=dict(run_id=name,iteration=it,metric_definition='arrival-departure /60',
            canonical_definition='departure_arrival_leg',filters={'cohort':'observed'},
            counts=dict(selected_rows=3,completed=2,aborted=0,censored=1),
            distribution=dict(n_complete=2,mean_minutes=3.,median_minutes=3.,p95_minutes=3.9))
        p=d/'graficas_perfiles/resumen_perfiles.json';write_json(p,report)
        artifact=dict(path='graficas_perfiles/resumen_perfiles.json',sha256=sha(p),size_bytes=p.stat().st_size)
        am=dict(status='completed',run_id=name,iteration=it,fingerprint='fixture-analysis',sources={},artifacts=[artifact])
        write_json(d/'analysis-manifest.json',am)
        write_json(d/'analysis-status.json',dict(status='completed',run_id=name,iteration=it,
            fingerprint='fixture-analysis',manifest_sha256=sha(d/'analysis-manifest.json')))
    return run


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);style()
    def tearDown(self): self.temp.cleanup()
    def rewrite(self,run,key,value):
        path=run/'run-manifest.json';data=json.loads(path.read_text());data[key]=value;write_json(path,data)

    def test_arbitrary_n_and_multiple_iterations(self):
        run=fixture(self.root,n=197321,iterations=(0,3,9))
        for it in (0,3,9):
            self.assertEqual(load_bundle(run,it)['identity']['N_configured'],197321)
        with self.assertRaisesRegex(ValueError,'no completada'):load_bundle(run,1)

    def test_no_closed_n_list(self):
        for n in (7,55000,181173,219999,350001):
            self.assertEqual(configured_n({'counts':{'non_public_vehicles_configured':n}}),n)

    def test_manifest_wrong_folder(self):
        run=fixture(self.root);self.rewrite(run,'folder',str(self.root/'foreign'))
        with self.assertRaisesRegex(ValueError,'carpeta'):load_bundle(run,0)

    def test_analysis_wrong_run_id(self):
        run=fixture(self.root);p=run/'analysis/it.0/analysis-status.json'
        s=json.loads(p.read_text());s['run_id']='wrong';write_json(p,s)
        with self.assertRaisesRegex(ValueError,'Run ID'):load_bundle(run,0)

    def test_mutated_manifest_receipt(self):
        run=fixture(self.root);p=run/'analysis/it.0/analysis-manifest.json'
        data=json.loads(p.read_text());data['fingerprint']='altered';write_json(p,data)
        with self.assertRaisesRegex(ValueError,'Huella'):load_bundle(run,0)

    def test_mutated_or_missing_summary(self):
        run=fixture(self.root);p=run/'analysis/it.0/graficas_perfiles/resumen_perfiles.json'
        p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'SHA256'):load_bundle(run,0)
        p.unlink()
        with self.assertRaisesRegex(ValueError,'ausente'):load_bundle(run,0)

    def test_failed_only_diagnostic_prefix(self):
        run=fixture(self.root);self.rewrite(run,'status','failed')
        with self.assertRaisesRegex(ValueError,'completed/valid'):load_bundle(run,0)
        bundle=load_bundle(run,0,True)
        self.assertEqual(bundle['identity']['publication_status'],'diagnostic_prefix')

    def test_active_excluded_even_diagnostic(self):
        run=fixture(self.root);self.rewrite(run,'status','running')
        with self.assertRaisesRegex(ValueError,'activas'):load_bundle(run,0,True)

    def test_missing_coverage_diagnostic(self):
        run=fixture(self.root);self.rewrite(run,'status','failed');self.rewrite(run,'results',{'0':{}})
        with self.assertRaisesRegex(ValueError,'cobertura'):load_bundle(run,0,True)

    def test_output_protected(self):
        run=fixture(self.root);b=load_bundle(run,0)
        with self.assertRaisesRegex(ValueError,'fuera'):safe_output(run/'analysis/new',[b])

    def test_variable_n_compare_two_four(self):
        bundles=[load_bundle(fixture(self.root,name=f'fixture-{n}',n=n),0) for n in (7,19999,55000,220002)]
        self.assertEqual(len(compatibility(bundles)['identities']),4)
        self.assertEqual(comparison_rows(bundles)[0]['completion_percent'],200/3)
        # counts do not scale with configured N
        self.assertEqual({r['completed'] for r in comparison_rows(bundles)},{2})
        path=generate_comparison(bundles[:2],self.root/'out')
        self.assertTrue((path/'comparacion_escenarios_absolutos.svg').is_file())
        with self.assertRaises(FileExistsError):generate_comparison(bundles[:2],self.root/'out')

    def test_no_invented_missing_scenario(self):
        b=load_bundle(fixture(self.root),0)
        with self.assertRaisesRegex(ValueError,'dos'):compatibility([b])
        with self.assertRaises(FileNotFoundError):load_bundle(self.root/'missing',0)

    def test_duplicate_run_rejected(self):
        b=load_bundle(fixture(self.root),0)
        with self.assertRaisesRegex(ValueError,'repetida'):compatibility([b,b])

    def test_exact_completed_iterations_compare(self):
        run=fixture(self.root,iterations=(0,1,2))
        self.assertEqual(len(compatibility([load_bundle(run,0),load_bundle(run,2)])['identities']),2)

    def test_incompatible_horizon_definition_units(self):
        a=load_bundle(fixture(self.root),0);b=load_bundle(fixture(self.root,'fixture-b'),0)
        for section,key,value in [('manifest','time_horizon',{'start_seconds':0,'end_seconds':108000}),
                                   ('profile_report','canonical_definition','unrelated_unit')]:
            c=copy.deepcopy(b);c[section][key]=value
            with self.assertRaisesRegex(ValueError,'incompatibles'):compatibility([a,c])

    def test_seed_difference_explicit(self):
        a=load_bundle(fixture(self.root),0);b=load_bundle(fixture(self.root,'fixture-b'),0)
        b['identity']['seeds']['demand']=43
        self.assertTrue(compatibility([a,b])['seeds_differ'])

    def test_no_completed_duration_zero(self):
        b=load_bundle(fixture(self.root),0);p=b['profile_report']
        p['counts'].update(completed=0,censored=3)
        p['distribution'].update(n_complete=0,mean_minutes=None,median_minutes=None,p95_minutes=None)
        row=comparison_rows([b])[0]
        self.assertIsNone(row['mean_minutes']);self.assertEqual(row['completion_percent'],0)

    def test_nonfinite_rejected(self):
        p=self.root/'bad.csv';p.write_text('hour,value\n1,nan\n')
        with self.assertRaisesRegex(ValueError,'finito'):csv_rows(p)
        p.write_text('hour,value\n1,1e309\n')
        with self.assertRaisesRegex(ValueError,'finito'):csv_rows(p)
        with self.assertRaisesRegex(ValueError,'finito'):write_json(self.root/'bad.json',{'x':float('inf')})

    def test_operational_native_totals(self):
        op={'native':{'progress':{'link_transitions':3}}}
        rows=[{'time':0,'link_transitions':0},{'time':60,'link_transitions':3}]
        reconcile_intervals(rows,op)
        rows[1]['link_transitions']=4
        with self.assertRaisesRegex(ValueError,'contradice'):reconcile_intervals(rows,op)

    def test_publisher_no_duplicate_and_source_preservation(self):
        run=fixture(self.root);before={str(p):sha(p) for p in run.rglob('*') if p.is_file()}
        b=load_bundle(run,0);pub=Publisher(self.root/'new',[b['identity']],b['sources'])
        fig,ax=plt.subplots();ax.bar([0],[2])
        pub.save(fig,'figure',[{'value':2}],{'units':'viajes','observations':2})
        fig,ax=plt.subplots()
        with self.assertRaisesRegex(ValueError,'repetido'):pub.save(fig,'figure',[],{})
        plt.close(fig);pub.finish()
        self.assertEqual(before,{str(p):sha(p) for p in run.rglob('*') if p.is_file()})
        rows=csv_rows(self.root/'new/figure.csv');self.assertEqual(rows,[{'value':2}])

    def test_spatial_comparison_equivalence_and_denominators(self):
        a=load_bundle(fixture(self.root),0);b=load_bundle(fixture(self.root,'fixture-b',n=170001),0)
        for bundle in (a,b):
            bundle['identity']['counts']['all_vehicles_configured']=bundle['identity']['N_configured']+19
            bundle['indicators']={'comparison_contract':{'definition':'fixture-directed-boundary'},
                'section_hour':[dict(section_id='section-A',hour=0,vehicles_per_hour=3,coverage_seconds=3600)],
                'occupancy_hour':[dict(intersection_id='node-A',hour=0,mean_occupancy_vehicles=2,covered_seconds=3600)]}
        pub=Publisher(self.root/'spatial',[a['identity'],b['identity']],[])
        compare_spatial([a,b],pub)
        self.assertEqual(len(pub.figures),2)
        data=json.loads((pub.directory/'comparacion_flujo_secciones.json').read_text())
        self.assertEqual(data['rows'][0]['vehicles_per_hour'],3)
        self.assertAlmostEqual(data['rows'][1]['per_1000_physical_configured'],3000/170020)
        b['indicators']['comparison_contract']={'definition':'OTHER-section'}
        with self.assertRaisesRegex(ValueError,'incompatibles'):compare_spatial([a,b],pub)

    def test_wrong_indicator_identity_and_no_revalidation_of_events(self):
        b=load_bundle(fixture(self.root),0);path=self.root/'wrong-pack.json'
        write_json(path,dict(run_id='other',iteration=0))
        with self.assertRaisesRegex(ValueError,'selección'):attach_indicators([b],[path])

    def test_source_mutation_during_publication_rejected(self):
        path=self.root/'source.json';write_json(path,{'a':1})
        pub=Publisher(self.root/'publication',[],[{'path':str(path),'sha256':sha(path)}])
        write_json(path,{'a':2})
        with self.assertRaisesRegex(ValueError,'cambió'):pub.finish()
        self.assertFalse((pub.directory/'figures-manifest.json').exists())


if __name__=='__main__':unittest.main()
