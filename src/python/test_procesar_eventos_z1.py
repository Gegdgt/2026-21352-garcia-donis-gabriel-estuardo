import gzip
from pathlib import Path
import tempfile
import tracemalloc
import unittest
import pandas as pd
from openpyxl import load_workbook
from procesar_eventos_z1 import read_trips, export_trips, COLUMNS, movement_end_time

class EventProcessingTests(unittest.TestCase):
    def test_pending_at_horizon_is_not_an_earlier_abort(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.xml.gz'
            self.write(path,'''<event type="departure" person="active" time="1"/>
            <event type="departure" person="earlier" time="2"/>
            <event type="departure" person="horizon" time="3"/>
            <event type="stuckAndAbort" person="earlier" time="10"/>
            <event type="stuckAndAbort" person="horizon" time="100"/>''')
            frame,stats=read_trips(path,horizon=100)
            self.assertEqual(len(frame),3)
            self.assertEqual(stats['incomplete_trips'],3)
            self.assertEqual(stats['aborted_trips'],2)
            self.assertEqual(stats['aborted_before_horizon'],1)
            self.assertEqual(stats['horizon_abort_events'],1)
            self.assertEqual(stats['pending_trips_at_horizon'],2)

    def test_free_flow_movement_then_wait(self):
        self.assertEqual(movement_end_time(10,70,100,10,vehicle_speed=20),20)
        self.assertEqual(movement_end_time(10,15,100,10,vehicle_speed=20),15)
        self.assertEqual(movement_end_time(10,21,100,10,vehicle_speed=20),21)
        self.assertEqual(movement_end_time(10,22,100,10,vehicle_speed=20),22)
        self.assertEqual(movement_end_time(10,22.001,100,10,vehicle_speed=20),20)
        self.assertEqual(movement_end_time(10,70,100,None,vehicle_speed=20),70)
        for speed in (0,-1,float('nan')):
            with self.assertRaises(ValueError): movement_end_time(10,70,100,speed,vehicle_speed=20)

    def test_profiles_json(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); events=folder/'events.gz'; plans=folder/'plans.xml'
            plans.write_text('<population><person id="a"><attributes><attribute name="drivingProfile" class="java.lang.String">Liebre</attribute></attributes></person></population>')
            self.write(events,'<event type="departure" person="a" time="0"/><event type="arrival" person="a" time="60"/>')
            export_trips(events,folder/'trips.xlsx',plans,folder/'trips.json')
            records=json.loads((folder/'trips.json').read_text())
            self.assertEqual(records[0]['Profile'],'Liebre')
            self.assertEqual(records[0]['Travel_Time_Minutes'],1)
    def test_all_24_hours_export_without_time_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'events.xml.gz'
            dest = Path(folder)/'trips.xlsx'
            events = []
            for hour in range(24):
                start = hour*3600
                events.append(f'<event type="departure" person="p{hour}" time="{start}"/>')
                events.append(f'<event type="arrival" person="p{hour}" time="{start+60}"/>')
            events.extend(['<event type="departure" person="midnight" time="86399"/>',
                           '<event type="arrival" person="midnight" time="86460"/>'])
            self.write(source, ''.join(events))
            stats = export_trips(source, dest)
            self.assertEqual(stats['completed_trips'], 25)
            frame = pd.read_excel(dest)
            self.assertEqual(len(frame), 25)
            self.assertEqual(frame.Hour_Block.iloc[:24].tolist(),
                             [f'{h:02}:00-{h+1:02}:00' for h in range(24)])
            self.assertEqual(frame.Arrival_Time.iloc[-1], '24:01:00')

    def write(self, path, content):
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            stream.write('<events>'+content+'</events>')

    def test_multiple_trips_boundaries_and_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.xml.gz'
            self.write(path, '''<event type="departure" person="a" time="35999"/>
            <event type="entered link" vehicle="a" time="36000"/>
            <event type="arrival" person="a" time="36059"/>
            <event type="departure" person="a" time="36060"/>
            <event type="arrival" person="a" time="36180"/>
            <event type="departure" person="b" time="54000"/>
            <event type="stuckAndAbort" person="b" time="54001"/>
            <event type="arrival" person="unknown" time="54002"/>''')
            df,stats=read_trips(path)
            self.assertEqual(list(df.columns),COLUMNS)
            self.assertEqual(df.Travel_Time_Minutes.iloc[:2].tolist(),[1.,2.])
            self.assertEqual(df.Hour_Block.tolist(),['09:00-10:00','10:00-11:00','15:00-16:00'])
            self.assertTrue(pd.isna(df.Travel_Time_Minutes.iloc[2]))
            self.assertEqual(stats['incomplete_trips'],1)
            self.assertEqual(stats['unmatched_arrivals'],1)

    def test_excel_literal_ids_and_fractional_time(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'events.xml.gz';dest=Path(folder)/'trips.xlsx'
            self.write(source, '<event type="departure" person="=1+1" time="90000.5"/>'
                       '<event type="arrival" person="=1+1" time="90030.5"/>')
            export_trips(source,dest)
            wb=load_workbook(dest);sheet=wb['Viajes']
            self.assertEqual(sheet['A2'].value,'=1+1');self.assertEqual(sheet['A2'].data_type,'s')
            self.assertEqual(sheet['B2'].value,'25:00:00.5')
            self.assertEqual(sheet['D2'].value,.5)
            wb.close()

    def test_invalid_pair_fails(self):
        for events in (
            '<event type="departure" person="a" time="2"/><event type="arrival" person="a" time="1"/>',
            '<event type="departure" person="a" time="1"/><event type="departure" person="a" time="2"/>'):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'events.xml.gz';self.write(path,events)
                with self.assertRaises(ValueError):read_trips(path)

    def test_ignored_events_do_not_accumulate_xml_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.xml.gz'
            self.write(path,'<event type="entered link" time="10" vehicle="a"/>'*50000)
            tracemalloc.start()
            frame,stats=read_trips(path)
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            self.assertEqual(len(frame),0)
            self.assertEqual(stats['ignored_events'],50000)
            self.assertLess(peak,8*1024*1024)

if __name__=='__main__':unittest.main()
