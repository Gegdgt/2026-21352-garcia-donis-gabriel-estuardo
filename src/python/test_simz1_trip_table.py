import csv
import gzip
import json
import math
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch
from simz1_trip_table import write_events,rows,validate_compact,export_table,inventory
from simz1_trip_distributions import distributions,plot_distributions,follow_person
from procesar_eventos_z1 import export_bounded_excel


class TripTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='trip table with spaces ');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def table(self,events,iteration=0,horizon=90000):
        source=self.root/f'{iteration}.events.xml.gz';target=self.root/f'{iteration}.csv.gz'
        with gzip.open(source,'wt') as stream:stream.write('<events>'+events+'</events>')
        stats=write_events(source,target,'run',iteration,{'p':'Tortuga','q':'Normal'},horizon)
        return target,list(rows(target)),stats

    def test_repeated_trips_abort_restart_midnight_and_vehicle_identity(self):
        path,records,stats=self.table('''
          <event type="departure" time="10" person="p" legMode="car"/>
          <event type="vehicle enters traffic" time="10" person="p" vehicle="v-other"/>
          <event type="vehicle aborts" time="20" vehicle="v-other"/>
          <event type="stuckAndAbort" time="20" person="p" legMode="car"/>
          <event type="departure" time="30" person="p" legMode="car"/>
          <event type="vehicle enters traffic" time="30" person="p" vehicle="new-vehicle"/>
          <event type="arrival" time="90" person="p" legMode="car"/>
          <event type="departure" time="86399" person="q" legMode="walk"/>
          <event type="arrival" time="86410" person="q" legMode="walk"/>
          <event type="departure" time="89999" person="p" legMode="car"/>
          <event type="departure" time="89999" person="r" legMode="car"/>
          <event type="stuckAndAbort" time="90001" person="p" legMode="car"/>''')
        self.assertEqual([r['status'] for r in records],['aborted','completed','completed','censored','censored'])
        self.assertEqual(records[0]['vehicle_id'],'v-other');self.assertEqual(records[1]['person_id'],'p')
        self.assertEqual(records[1]['trip_index'],2);self.assertEqual(records[1]['duration_seconds'],60)
        self.assertEqual(records[2]['arrival'],86410);self.assertEqual(records[2]['duration_seconds'],11)
        self.assertEqual(records[2]['vehicle_id'],'');self.assertEqual(records[2]['mode'],'walk')
        self.assertTrue(all(r['duration_seconds'] is None for r in records if r['status']!='completed'))
        self.assertEqual(records[-1]['profile'],'unknown')
        self.assertAlmostEqual(stats['completion_rate'],2/5)
        self.assertEqual(stats['terminal_reconciliation']['paired_terminal_events'],1)
        self.assertNotIn('duplicate_terminal_events',stats['anomalies'])
        self.assertEqual(validate_compact(path,'run',0,horizon=90000)['rows'],5)
        _,_,summary,report=distributions(path)
        self.assertEqual(report['n_complete'],1);self.assertEqual(report['n_excluded'],4)
        self.assertEqual(report['n_other_mode'],1)
        self.assertAlmostEqual(report['completion_rate'],.25)
        self.assertEqual(next(r for r in summary if r['view']=='profile')['p50_seconds'],60)

    def test_duplicates_orphans_and_unknown_modes_are_reported(self):
        path,records,stats=self.table('''<event type="arrival" person="q" time="0"/>
        <event type="departure" person="p" time="1"/>
        <event type="departure" person="p" time="1"/>
        <event type="arrival" person="p" time="2"/>
        <event type="arrival" person="p" time="2"/>''')
        self.assertEqual(len(records),1);self.assertEqual(records[0]['mode'],'unknown')
        self.assertEqual(stats['anomalies'],dict(unmatched_arrivals=1,duplicate_departures=1,duplicate_arrivals=1))
        self.assertEqual(distributions(path)[3]['n_complete'],0)
        self.assertEqual(distributions(path,'all')[3]['n_complete'],1)

    def test_abort_after_arrival_is_not_a_paired_terminal_event(self):
        _,records,stats=self.table('''<event type="departure" person="p" time="1" legMode="car"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" time="1"/>
        <event type="arrival" person="p" time="2" legMode="car"/>
        <event type="vehicle aborts" vehicle="v" time="3"/>
        <event type="stuckAndAbort" person="p" time="3"/>''')
        self.assertEqual(len(records),1)
        self.assertEqual(stats['anomalies'],dict(abort_after_arrival=2))

    def test_identity_units_score_independence_and_bounded_excel(self):
        path,records,_=self.table('<event type="departure" person="=1+1" time="90000.5" legMode="car"/>'
                                  '<event type="arrival" person="=1+1" time="90030.5" legMode="car"/>')
        self.assertEqual(records[0]['duration_seconds'],30)
        before=distributions(path)[3]
        (self.root/'scorestats.txt').write_text('ITERATION\tavg. EXECUTED\n0\t99999999\n')
        self.assertEqual(before,distributions(path)[3])
        (self.root/'scorestats.txt').unlink();self.assertEqual(before,distributions(path)[3])
        dest=self.root/'bounded.xlsx';export_bounded_excel(path,dest,1)
        from openpyxl import load_workbook
        with dest.open('rb') as stream:
            book=load_workbook(stream);self.assertEqual(book['Viajes']['C2'].data_type,'s');book.close()
        path2,_,_=self.table('<event type="departure" person="p" time="1"/>'
                           '<event type="arrival" person="p" time="2"/>'
                           '<event type="departure" person="p" time="3"/>',iteration=1)
        with self.assertRaisesRegex(ValueError,'excel-max-rows'):export_bounded_excel(path2,self.root/'too-large.xlsx',1)
        self.assertFalse((self.root/'too-large.xlsx').exists())

    def test_invalid_duration_run_and_duplicate_key_rejected(self):
        path,records,_=self.table('<event type="departure" person="p" time="1"/><event type="arrival" person="p" time="2"/>')
        with self.assertRaisesRegex(ValueError,'otra corrida'):validate_compact(path,'other',0)
        from simz1_trip_table import COLUMNS
        for change in ('duration','duplicate','censored'):
            target=self.root/f'bad-{change}.csv.gz';raw=dict(records[0])
            if change=='duration':raw['duration_seconds']=60
            if change=='censored':raw['status']='censored'
            with gzip.open(target,'wt',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader();writer.writerow(raw)
                if change=='duplicate':writer.writerow(raw)
            with self.assertRaises(ValueError):validate_compact(target,'run',0)

    def test_streaming_many_trips_of_one_person_does_not_retain_all_rows(self):
        events=self.root/'many.xml.gz';target=self.root/'many.csv.gz'
        with gzip.open(events,'wt') as stream:
            stream.write('<events>')
            for i in range(20000):stream.write(f'<event type="departure" person="p" time="{2*i}" legMode="car"/><event type="arrival" person="p" time="{2*i+1}" legMode="car"/>')
            stream.write('</events>')
        tracemalloc.start()
        try:
            stats=write_events(events,target,'stream',0,{'p':'Normal'})
            peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertEqual(stats['completed_trips'],20000);self.assertLess(peak,8*1024**2)

    def test_distribution_views_include_counts_with_no_complete_trips(self):
        path,_,_=self.table('<event type="departure" person="p" time="86399" legMode="car"/>')
        report=plot_distributions(path,self.root/'plots','run / iteration 0')
        self.assertEqual(report['n_complete'],0);self.assertEqual(report['n_excluded'],1)
        self.assertEqual(len(list((self.root/'plots').glob('*.png'))),2)

    def test_history_keeps_missing_iteration_gap_without_score_fallback(self):
        p0,_,_=self.table('<event type="departure" person="p" time="0" legMode="car"/><event type="arrival" person="p" time="60" legMode="car"/>')
        p2,_,_=self.table('<event type="departure" person="p" time="0" legMode="car"/><event type="arrival" person="p" time="30" legMode="car"/>',iteration=2)
        selection=dict(directory=self.root,iteration=2,manifest=dict(run_id='run',iterations=dict(completed=[0,1,2]),results={'0':{},'2':{}}))
        report=follow_person(selection,'p',1,self.root/'history',exported={0:p0,2:p2})
        self.assertEqual(report['n_complete'],2);self.assertEqual(report['n_excluded'],1)
        self.assertEqual(report['missing_iterations'],[1])
        with (self.root/'history/individual_evolution.csv').open() as stream:history=list(csv.DictReader(stream))
        self.assertEqual(history[1]['status'],'missing_iteration_data');self.assertEqual(history[1]['duration_seconds'],'')

    def test_native_java_contract_products_match_python_schema(self):
        evidence=Path('target/prompt8-native-evidence.txt')
        if not evidence.exists():self.skipTest('Run TripTableCheck for cross-language fixture')
        root=Path(evidence.read_text())
        for iteration in range(3):
            counts=validate_compact(root/f'native/ITERS/it.{iteration}/{iteration}.simz1-trips.csv.gz',
                                    'native-three-iterations',iteration,horizon=200)
            self.assertEqual(counts,dict(rows=3,completed=2,aborted=0,censored=1,persons=2))
        for iteration in range(2):
            counts=validate_compact(root/f'contract-{iteration}/{iteration}.simz1-trips.csv.gz','edge-contract',iteration,horizon=90000)
            self.assertEqual(counts,dict(rows=5,completed=2,aborted=1,censored=2,persons=4))

    def prepare_run(self,name):
        from generate_montecarlo_z1 import generar,SCENARIO
        directory=self.root/name
        generar(SCENARIO/'config-simz1.xml',directory,81,agents=2,corridor_policy='redistribute')
        maven=self.root/'fake maven.cmd';maven.write_text('')
        return directory,maven

    def test_validated_compact_iteration_without_xml_and_consumer_clis(self):
        from test_simz1_run import fake_matsim
        from ejecutar_simz1 import ejecutar
        from simz1_run import select_run
        import subprocess,sys
        directory,maven=self.prepare_run('compact run with spaces');latest=self.root/'latest-successful.json'
        def intermediate(*args,**kwargs):
            fake_matsim(*args,**kwargs)
            for name in ('1.events.xml.gz','1.plans.xml.gz'):(directory/'output/ITERS/it.1'/name).unlink()
            return 0
        with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=intermediate):
            state=ejecutar(directory,maven,iterations=3,latest_path=latest)
        self.assertEqual(set(state['results']),{'0','2'})
        with self.assertRaisesRegex(ValueError,'sin planes y eventos'):select_run(directory,1)
        selection=select_run(directory,1,require_events=False)
        path,report=export_table(selection)
        self.assertEqual(report['source_kind'],'native_compact');self.assertEqual(len(list(rows(path))),2)
        self.assertTrue(inventory(selection)[1]['compact_validated'])
        for script in ('procesar_eventos_z1.py','generar_graficas_z1.py'):
            cmd=[sys.executable,str(Path(__file__).parent/script),'--run-dir',str(directory),'--iteration','1']
            if script.startswith('generar_'):cmd+=['--person','z1_00001','--trip-index','1','--mode','all']
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(len(list((directory/'analysis/it.1').glob('*.png'))),3)
        source=directory/'output/ITERS/it.1/1.simz1-trips.csv.gz';source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Hash no coincide'):select_run(directory,1,require_events=False)

    def test_missing_compact_rejects_completed_run_and_retains_reference(self):
        from test_simz1_run import fake_matsim
        from ejecutar_simz1 import ejecutar
        from simz1_run import atomic_json,load_manifest
        directory,maven=self.prepare_run('missing compact');latest=self.root/'latest-successful.json'
        atomic_json(latest,dict(run_id='previous'));original=latest.read_bytes()
        def missing(*args,**kwargs):
            fake_matsim(*args,**kwargs)
            (directory/'output/ITERS/it.1/1.simz1-trips.csv.gz').unlink()
            return 0
        with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=missing),self.assertRaisesRegex(ValueError,'Falta producto compacto'):
            ejecutar(directory,maven,iterations=2,latest_path=latest)
        self.assertEqual(latest.read_bytes(),original)
        self.assertEqual(load_manifest(directory)['validation']['status'],'invalid')


if __name__=='__main__':unittest.main()
