"""Small census/event fixtures only; these tests never start MATSim."""
import copy
import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simz1_day_observation import POLICY, classify
from simz1_balanced_launch_report import fixed_day_rows, fixed_day_tables, report_fixed_day
from simz1_continuous_replay import daily_window, checked_screening
from simz1_result_quality import assess
from simz1_run import sha256
from simz1_trip_table import write_events, validate_compact, rows
from simz1_motion import MotionContext
from simz1_trajectories import extract


def census(ident, family='carro', scheduled=86340, departure=86340, entry=86340, **extra):
    row=dict(run_id='fixture',iteration=0,policy=POLICY,trip_id=ident,vehicle_id=ident,
        family=family,scheduled_departure=scheduled,departure=departure,traffic_entry=entry,
        traffic_exit=None,arrival=None,abort_before_cleanup=None,last_transition=entry,
        last_link='a',cleanup_abort_events=2,od=None,**extra)
    return classify(row)


def summary(records):
    tables=fixed_day_tables(records,269)
    return dict(policy=POLICY,execution='native_day_completed',technical_integrity='verified_precleanup_census',
        coverage_end_seconds=86400,counts=tables['counts'],pending_classifications=tables['pending'],
        scheduled_trips=len(records),completion_rate=tables['counts'].get('completed',0)/len(records),
        groups=[{k:v for k,v in r.items() if k!='last_transition_seconds'} for r in tables['groups']])


class FixedDayReportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='simz1-fixed-day-report-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def test_census_reports_keep_recent_old_request_freight_bus_and_boundary_arrival(self):
        records=[census('recent'),census('old',scheduled=100,departure=100,entry=86399),
            census('prolonged',scheduled=80000,departure=80000,entry=80000),
            census('exact',scheduled=82800,departure=82800,entry=82800),
            census('truck',family='pesado',scheduled=75600,departure=75600,entry=75600),
            census('bus',family='bus'),census('waiting',scheduled=100,departure=100,entry=None),
            census('not-departed',departure=None,entry=None)]
        complete=census('arrived');complete.update(arrival=86400,traffic_exit=86400);records.append(classify(complete))
        data=fixed_day_tables(records,269)
        self.assertEqual(data['counts']['completed'],1)
        self.assertEqual(data['pending']['prolonged_traffic_review_required'],1)
        self.assertEqual(data['pending']['recent_entry_old_request'],1)
        self.assertEqual(data['pending']['horizon_censored_no_private_duration_threshold'],2)
        self.assertEqual(data['hours'][23]['real_arrivals'],1)
        self.assertEqual(data['hours'][23]['active_public_vehicles'],1)
        self.assertEqual(data['hours'][23]['active_bus_expeditions'],1)
        self.assertEqual(data['hours'][23]['waiting_non_public'],1)
        self.assertEqual(records[1]['request_age_seconds'],86300)
        self.assertEqual(records[1]['observed_traffic_seconds'],1)
        self.assertTrue(all(r['arrival'] is None and r['complete_duration_seconds'] is None for r in records[:-1]))
        truck=next(r for r in data['durations'] if r['family']=='pesado')
        self.assertEqual(truck['observed_traffic_seconds_sum_seconds'],10800)
        self.assertIsNone(truck['complete_duration_seconds_sum_seconds'])

    def make_native(self):
        records=[census('prolonged',scheduled=80000,departure=80000,entry=80000),census('bus',family='bus')]
        path=self.root/'census.jsonl.gz'
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            for row in records:stream.write(json.dumps(row)+'\n')
        day=summary(records);day['census']=dict(path=path.name,sha256=sha256(path))
        manifest=dict(run_id='fixture',counts=dict(public_transport_vehicles_configured=269),
            experiment=dict(observation_policy=POLICY),results={'0':dict(day_observation=day,
            events=dict(path='never-read.xml.gz',sha256='not-a-file'),freight_transport_events={},public_transport_events={})})
        (self.root/'run-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return manifest,records

    def heterogeneous_native(self, reverse=False, extra_field=False):
        # Native bus templates omit person-only profile/OD; lexical bus: keys
        # precede road people in the Java TreeMap census writer.
        first=census('bus:line:route:expedition-1',family='bus')
        first.pop('od');first['vehicle_id']='same-native-bus'
        second=census('bus:line:route:expedition-2',family='bus',scheduled=100,departure=100,entry=100)
        second.pop('od');second.update(vehicle_id='same-native-bus',arrival=200,traffic_exit=200)
        second=classify(second)
        records=[first,second]
        for index,od in enumerate(('INTERNAL_INTERNAL','INTERNAL_EXTERNAL','EXTERNAL_INTERNAL','EXTERNAL_EXTERNAL_THROUGH')):
            row=census('road-'+str(index),family='carro' if index<2 else 'moto',
                       profile='Normal' if index<2 else 'Motociclista')
            row['od']=json.dumps({'0':dict(od_class=od,person_id=row['trip_id'])})
            records.append(row)
        records.append(census('truck',family='pesado',profile='TransportePesado'))
        if extra_field:records[-1]['unexpected_native_column']='must never disappear'
        if reverse:records.reverse()
        path=self.root/'heterogeneous-census.jsonl.gz'
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            for row in records:stream.write(json.dumps(row)+'\n')
        day=summary(records);day['census']=dict(path=path.name,sha256=sha256(path))
        manifest=dict(run_id='fixture',counts=dict(public_transport_vehicles_configured=269),
            experiment=dict(observation_policy=POLICY),results={'0':dict(day_observation=day,
            events=dict(path='events-must-not-be-read.xml.gz',sha256='not-a-file'),
            freight_transport_events={},public_transport_events={})})
        (self.root/'run-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return manifest,records

    def test_lifecycle_csv_keeps_bus_person_profile_od_and_expedition_identities(self):
        original_headers=None
        for reverse in (False,True):
            manifest,records=self.heterogeneous_native(reverse=reverse)
            expected_fields=sorted({key for row in records for key in row})
            original=copy.deepcopy(records);census_hash=sha256(self.root/'heterogeneous-census.jsonl.gz')
            manifest_hash=sha256(self.root/'run-manifest.json');output=self.root/('forward' if not reverse else 'reverse')
            output=self.root/'analysis/it.0'/output.name
            with patch('simz1_balanced_launch_report.manifest_identity',return_value={}),patch(
                    'simz1_balanced_launch_report.xml_elements',side_effect=AssertionError('No XML replay')):
                report_fixed_day(self.root,manifest,0,manifest_hash,output)
            exported=json.loads((output/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(exported['lifecycle_csv_schema']['version'],'simz1-fixed-day-lifecycle-csv-v1')
            self.assertEqual(exported['lifecycle_csv_schema']['fields'],expected_fields)
            self.assertEqual(exported['lifecycle_csv_schema']['optional_person_fields'],['profile','od'])
            self.assertEqual(records,original)
            self.assertEqual(sha256(self.root/'heterogeneous-census.jsonl.gz'),census_hash)
            self.assertEqual(sha256(self.root/'run-manifest.json'),manifest_hash)
            outputs={};headers=[]
            for name in ('day-lifecycle.csv','nonpublic-lifecycle.csv','bus-expeditions.csv'):
                with (output/name).open(encoding='utf-8',newline='') as stream:
                    reader=csv.DictReader(stream);outputs[name]=list(reader);headers.append(reader.fieldnames)
            self.assertTrue(all(h==expected_fields for h in headers))
            self.assertEqual(headers[0],sorted(headers[0]))
            if original_headers is not None:self.assertEqual(headers,original_headers)
            original_headers=headers
            all_rows={row['trip_id']:row for row in outputs['day-lifecycle.csv']}
            self.assertEqual(set(all_rows),{row['trip_id'] for row in records})
            self.assertEqual(len(all_rows),len(records))
            for row in records:
                for key in expected_fields:
                    value=row.get(key)
                    expected='' if value is None else json.dumps(value,sort_keys=True) if isinstance(value,(dict,list)) else str(value)
                    self.assertEqual(all_rows[row['trip_id']][key],expected,(row['trip_id'],key))
            buses=outputs['bus-expeditions.csv']
            self.assertEqual({r['vehicle_id'] for r in buses},{'same-native-bus'})
            self.assertEqual(len({r['trip_id'] for r in buses}),2)
            self.assertTrue(all(r['profile']=='' and r['od']=='' for r in buses))
            road=outputs['nonpublic-lifecycle.csv']
            self.assertEqual(len(road),5)
            od_classes={next(iter(json.loads(r['od']).values()))['od_class'] for r in road if r['od']}
            self.assertEqual(od_classes,{'INTERNAL_INTERNAL','INTERNAL_EXTERNAL','EXTERNAL_INTERNAL','EXTERNAL_EXTERNAL_THROUGH'})

    def test_lifecycle_csv_rejects_unknown_columns_without_publishing_a_report(self):
        for reverse in (False,True):
            manifest,records=self.heterogeneous_native(extra_field=True,reverse=reverse)
            original=sha256(self.root/'run-manifest.json');output=self.root/'analysis/it.0/balanced-launch'
            with self.assertRaisesRegex(ValueError,'unexpected_native_column'):
                report_fixed_day(self.root,manifest,0,original,output)
            self.assertFalse((output/'report.json').exists())
            self.assertEqual(sha256(self.root/'run-manifest.json'),original)

    def test_official_products_reuse_census_and_keep_review_without_reading_events(self):
        manifest,records=self.make_native();output=self.root/'analysis/it.0/balanced-launch'
        with patch('simz1_balanced_launch_report.manifest_identity',return_value={}),patch(
                'simz1_balanced_launch_report.xml_elements',side_effect=AssertionError('No XML replay')):
            report_fixed_day(self.root,manifest,0,sha256(self.root/'run-manifest.json'),output)
        report=json.loads((output/'report.json').read_text())
        self.assertEqual(report['screening_warning'],'review_required')
        self.assertEqual(report['scheduled_trips_denominator'],2)
        self.assertEqual(report['raw_completion_rate'],0)
        self.assertIsNone(report['followup_window'])
        with (output/'day-lifecycle.csv').open(encoding='utf-8',newline='') as stream:data=list(csv.DictReader(stream))
        self.assertEqual(len(data),2);self.assertTrue(all(r['arrival']=='' for r in data))
        self.assertNotIn('followup-24-30.csv',report['files'])
        self.assertTrue(all((output/name).is_file() for name in report['files']))
        manifest['results']['0']['day_observation']['counts']={'completed':2}
        with self.assertRaisesRegex(ValueError,'totals'):list(fixed_day_rows(self.root,manifest,0))

    def test_screening_retains_original_rate_and_adds_all_scheduled_denominator(self):
        day=summary([census('old',scheduled=100,departure=None,entry=None)])
        report=dict(run_id='fixture',iteration=0,counts=dict(selected_rows=1,completed=1,aborted=0,censored=0),
            provenance=dict(day_observation=day,freight_transport_observed=dict(
                completion_policy='freight-close-plus3600-v1',experimental_acceptance='not_evaluable')))
        quality=assess(report)
        self.assertEqual(quality['completion_rate'],1)
        self.assertEqual(quality['scheduled_private_completion_rate'],0)
        self.assertEqual(quality['status'],'review_required')
        self.assertIn('scheduled_private_completion_below_declared_target',quality['reasons'])
        self.assertNotIn('freight_completion_tolerance_not_satisfied',quality['reasons'])
        report['provenance']['day_observation']=summary([census('long',scheduled=0,departure=0,entry=0)])
        self.assertIn('private_pending_traffic_exceeds_3600_seconds_at_cut',assess(report)['reasons'])

    def test_analysis_caller_transfers_validated_census_to_screening(self):
        # Exercise the production caller with an explicitly supplied accepted
        # census fixture. Native census/event equivalence is tested separately.
        from test_simz1_analysis import AnalysisLifecycleTests, fixture_renderer
        from simz1_run import atomic_json, artifact, load_manifest
        fixture=AnalysisLifecycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        run=fixture.make_run(profiles=('Normal',)*6)
        manifest=load_manifest(run)
        path=run/'accepted-census-fixture.jsonl.gz'
        record=census('pending',scheduled=100,departure=100,entry=100)
        with gzip.open(path,'wt') as stream:stream.write(json.dumps(record)+'\n')
        day=summary([record]);day['census']=artifact(run,path)
        manifest['results']['0']['day_observation']=day
        atomic_json(run/'run-manifest.json',manifest)
        def renderer(*args,**kwargs):
            report=fixture_renderer(*args,**kwargs)
            report['result_quality']=assess(report)
            atomic_json(Path(args[1])/'resumen_perfiles.json',report)
            return report
        with patch('simz1_analysis.plot_profile_analysis',side_effect=renderer):
            result=fixture.analyze(run)
        self.assertEqual(result['status'],'completed')
        report=fixture.report(run)
        self.assertEqual(report['provenance'].get('day_observation'),day)
        quality=report['result_quality']
        self.assertIn('private_pending_traffic_exceeds_3600_seconds_at_cut',quality['reasons'])
        self.assertIn('required_profiles_missing',quality['reasons'])

    def test_analysis_only_preserves_required_profiles_screening_code(self):
        from test_simz1_package_launcher import PackageLauncherTests, PROJECT
        import sys
        fixture=PackageLauncherTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.make_analysis_dependencies()
        # All six observed legs arrived, but five required profiles are absent.
        # The real screening CLI must return 3 only with the retained guard.
        (fixture.python/'simz1_result_quality.py').write_text(
            'import sys\nsys.path.insert(0,'+repr(str(PROJECT/'python'))+')\n'
            'from simz1_result_quality import main\nsys.exit(main())\n',encoding='utf-8')
        for iteration in (0,1):
            path=fixture.run/f'analysis/it.{iteration}/graficas_perfiles/resumen_perfiles.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(run_id=fixture.run_id,iteration=iteration,
                counts=dict(selected_rows=6,completed=6,aborted=0,censored=0),profiles=[dict(profile='Normal',n_total=6)])))
        result=fixture.invoke('-AnalysisOnly')
        self.assertEqual(result.returncode,3,result.stdout+result.stderr)
        self.assertIn('required_profiles_missing',result.stdout)

    def test_exit_without_arrival_is_review_and_residence_ends_at_observed_exit(self):
        row=census('exit',scheduled=80000,departure=80000,entry=80000)
        row.update(traffic_exit=85000);row=classify(row)
        self.assertEqual(row['status'],'exited_without_arrival')
        self.assertEqual(row['observed_traffic_seconds'],5000)
        self.assertEqual(row['observed_traffic_end_seconds'],85000)
        self.assertEqual(row['observed_traffic_end_basis'],'traffic_exit')
        quality=assess(dict(counts=dict(selected_rows=1,completed=1,aborted=0,censored=0),
            provenance=dict(day_observation=summary([row]))))
        self.assertIn('traffic_exit_without_arrival_requires_review',quality['reasons'])

    def test_new_and_historical_replay_windows_are_distinct(self):
        for policy,limit in ((POLICY,86400),('freight-close-plus3600-v1',108000)):
            config=dict(continuous={},time_horizon=dict(start_seconds=0,end_seconds=limit),
                experimental_observation=dict(policy=policy,demand_end_seconds=86400,observation_end_seconds=limit))
            manifest=dict(replay_window=dict(start_seconds=0,end_seconds=limit),window_seconds=120)
            source=copy.deepcopy(manifest);daily_window(config,manifest,source)
            self.assertEqual(manifest['replay_window']['end_seconds'],limit)
            self.assertEqual(manifest['source_time_horizon']['end_seconds'],limit)
        config['experimental_observation']['policy']=POLICY
        with self.assertRaisesRegex(ValueError,'Unknown experimental'):daily_window(config,manifest,source)

    def test_replay_screening_uses_verified_same_iteration_analysis(self):
        run=dict(run_id='fixture',results={'0':{}});source=dict(run_directory=str(self.root),iteration=0)
        self.assertEqual(checked_screening(run,source)['status'],'not_evaluated')
        directory=self.root/'analysis/it.0';quality=directory/'graficas_perfiles/calidad_resultados.json'
        quality.parent.mkdir(parents=True)
        quality.write_text(json.dumps(dict(run_id='fixture',iteration=0,status='review_required',reasons=['low_completion'])))
        manifest=directory/'analysis-manifest.json'
        manifest.write_text(json.dumps(dict(run_id='fixture',iteration=0,status='completed',artifacts=[dict(
            path='graficas_perfiles/calidad_resultados.json',sha256=sha256(quality))])))
        self.assertEqual(checked_screening(run,source)['status'],'review_required')
        quality.write_text('{}')
        with self.assertRaises(ValueError):checked_screening(run,source)

    def test_fixed_day_package_keeps_review_and_requires_matching_census(self):
        # Reuse the existing small package fixture: six 4x4 PNGs, no QSim.
        from test_simz1_report_package import PackageTests, save_json
        import simz1_report_package as package
        fixture=PackageTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        native=package.read_json(fixture.run/'run-manifest.json')
        day=summary([census('pending')])
        native.update(experiment=dict(observation_policy=POLICY),results={'0':dict(
            events=dict(path='output/events.xml',sha256=package.file_sha(fixture.run/'output/events.xml')),day_observation=day)})
        save_json(fixture.run/'run-manifest.json',native);fixture.native_before=fixture.snapshot_native()
        balanced=fixture.analysis/'balanced-launch';balanced.mkdir()
        (balanced/'day.csv').write_text('status\nactive_at_cut\n')
        report=dict(run_id='simz1-fixture',iteration=0,manifest_sha256=package.file_sha(fixture.run/'run-manifest.json'),
            events=native['results']['0']['events'],day_observation=day,postprocessor_version='balanced-report-fixed-day-v1',
            followup_window=None,observation_coverage_seconds=86400,files={'day.csv':package.file_sha(balanced/'day.csv')})
        save_json(balanced/'report.json',report)
        _,_,_,products=package._source_files(fixture.run,0)
        self.assertIn('docs/balanced-launch/day.csv',products)
        self.assertEqual(package.read_json(products['docs/calidad_resultados.json'])['status'],'review_required')
        report['observation_coverage_seconds']=108000;save_json(balanced/'report.json',report)
        with self.assertRaisesRegex(ValueError,'Fixed-day evidence'):package._source_files(fixture.run,0)

    def test_compact_abortion_at_T_requires_explicit_fixed_day_and_marker_censors_once(self):
        source=self.root/'events.xml.gz';destination=self.root/'table.csv.gz'
        events='''<events><event type="departure" time="86340" person="real" legMode="car"/>
          <event type="departure" time="86340" person="cleanup" legMode="car"/>
          <event type="departure" time="86340" person="arrived" legMode="car"/>
          <event type="stuckAndAbort" time="86400" person="real"/>
          <event type="arrival" time="86400" person="arrived"/>
          <event type="simz1DayCut" time="86400"/>
          <event type="stuckAndAbort" time="86400" person="cleanup"/></events>'''
        with gzip.open(source,'wt') as stream:stream.write(events)
        write_events(source,destination,'fixture',0,{},86400,fixed_day=True)
        self.assertEqual(validate_compact(destination,'fixture',0,horizon=86400,fixed_day=True),
            dict(rows=3,completed=1,aborted=1,censored=1,persons=3))
        with self.assertRaisesRegex(ValueError,'Aborto incompatible'):validate_compact(destination,'fixture',0,horizon=86400)
        self.assertEqual([r['status'] for r in rows(destination)],['aborted','completed','censored'])

    def test_replay_keeps_physical_arrival_T_and_rejects_postcut_motion(self):
        context=MotionContext({'v':10});context.fixed_day=True
        links={'a':dict(length=100,freespeed=10,from_node='n0',to_node='n1',**{'from':[0,0],'to':[.001,0]})}
        def ev(kind,time,**attrs):return dict(type=kind,time=str(time),**attrs)
        start=[ev('departure',86340,person='p',link='a'),ev('vehicle enters traffic',86340,person='p',vehicle='v',link='a',relativePosition='0')]
        finish=[ev('vehicle leaves traffic',86400,person='p',vehicle='v',link='a',relativePosition='1'),ev('arrival',86400,person='p',link='a')]
        def replay(events):return extract(events,links,lambda _:True,lambda _:[0,0,0],None,motion=context,horizon=86400)
        result=replay(start+finish+[ev('simz1DayCut',86400)])
        self.assertEqual(result[0]['Trip']['Status'],'completed');self.assertEqual(result[0]['Trip']['Arrival'],86400)
        with self.assertRaisesRegex(ValueError,'Physical replay'):replay(start+[ev('entered link',86401,vehicle='v',link='a')])
        with self.assertRaisesRegex(ValueError,'Physical replay'):replay(start+[ev('simz1DayCut',86400),*finish])


if __name__=='__main__':unittest.main()
