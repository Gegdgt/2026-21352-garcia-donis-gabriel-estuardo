import copy
import gzip
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import xml.etree.ElementTree as ET

import visualizador_z1 as viewer
from simz1_lane_replay import LaneEventReplay
from simz1_motion import MotionContext
from simz1_paged_replay import SqliteTrajectorySink,LaneSink,windows,signal_window,export_paged_selected,annotate_observation_times
from simz1_signal_replay import SignalReplay
from simz1_trajectories import extract
from serve_simz1_replay import handler_for,journey_payload


LINKS={'a':dict(length=100,freespeed=10,from_node='n0',to_node='n1',**{'from':[0,0],'to':[.001,0]}),
       'b':dict(length=100,freespeed=10,from_node='n1',to_node='n2',**{'from':[.001,0],'to':[.002,0]})}
GROUPS=[dict(system_id='s',group_id='g',signals=[dict(signal_id='light',link='a',lanes=[],turning_moves=[])])]
EVENTS='''<events>
<event type="signalGroupStateChangedEvent" time="86380" signalSystemId="s" signalGroupId="g" signalGroupState="GREEN"/>
<event type="departure" time="86390" person="p" link="a"/>
<event type="vehicle enters traffic" time="86390" person="p" vehicle="v" link="a" relativePosition="0"/>
<event type="entered lane" time="86390" vehicle="v" link="a" lane="a.original"/>
<event type="signalGroupStateChangedEvent" time="86399" signalSystemId="s" signalGroupId="g" signalGroupState="RED"/>
<event type="simz1NativeDecision" time="86400" vehicle="v" link="a" decision="WAIT" reason="signal_red" source="MATSim15_QNode_native_branch"/>
<event type="signalGroupStateChangedEvent" time="86405" signalSystemId="s" signalGroupId="g" signalGroupState="GREEN"/>
<event type="left lane" time="86405" vehicle="v" link="a" lane="a.original"/>
<event type="left link" time="86405" vehicle="v" link="a"/>
<event type="entered link" time="86405" vehicle="v" link="b"/>
<event type="entered lane" time="86405" vehicle="v" link="b" lane="b.original"/>
<event type="vehicle leaves traffic" time="86420" person="p" vehicle="v" link="b" relativePosition="1"/>
<event type="arrival" time="86420" person="p" link="b"/>
</events>'''


def events():
    return [dict(event.attrib) for event in ET.fromstring(EVENTS)]


def context():
    return MotionContext({'v':10},{'p':'Normal'})


def decoded(path):
    text=Path(path).read_text(encoding='utf-8')
    return json.loads(text.split('<script id="replay-data" type="application/json">')[1].split('</script>')[0])


class PagedReplayTests(unittest.TestCase):
    def test_disk_spool_matches_monolithic_motion_and_final_trip_metadata(self):
        baseline={}
        original=extract(events(),LINKS,lambda _:True,viewer.color_velocidad,viewer.GEOD,
                         motion=context(),stats=baseline,horizon=86440)
        with tempfile.TemporaryDirectory() as folder:
            store=SqliteTrajectorySink(Path(folder)/'replay.sqlite',windows(86380,86440,20))
            try:
                stats={};lanes=LaneEventReplay(LINKS,event_sink=LaneSink(store))
                returned=extract(events(),LINKS,lambda _:True,viewer.color_velocidad,viewer.GEOD,
                    motion=context(),stats=stats,horizon=86440,segment_sink=store,lane_replay=lanes)
                self.assertIs(returned,store)
                self.assertEqual(stats,baseline)
                self.assertFalse(store._trips,'metadata references are released after finalization')
                first,middle,last=[store.block_records(index) for index in range(3)]
                self.assertEqual([len(first),len(middle),len(last)],[1,2,0])
                self.assertEqual(first[0],middle[0],'the crossing interval keeps exact phases at midnight')
                self.assertEqual(middle[-1]['Trip']['Arrival'],86420)
                self.assertEqual(middle[-1]['Trip']['Destination_Position'],LINKS['b']['to'])
                for actual,expected in zip(middle,original):
                    actual=copy.deepcopy(actual)
                    actual.pop('Replay_Journey_Key');actual.pop('Max_Speed_kmh')
                    self.assertEqual(actual,expected)
                carry=store.block_lanes(86400,86420,{'v'})
                self.assertEqual(carry[0]['time'],86390)
                self.assertEqual(carry[0]['type'],'entered lane')
                self.assertEqual([row['time'] for row in carry],[86390,86405,86405])
                complete=journey_payload(store.path,middle[0]['Replay_Journey_Key'],dict(run_id='run',iteration=0))
                self.assertEqual(complete['records'],middle)
            finally:store.close()

    def test_signal_predecessor_exact_edge_and_unknown_before_first_event(self):
        replay=SignalReplay(GROUPS)
        for event in events():replay.add(event)
        self.assertEqual(signal_window(replay,86370,86380).payload()['series'][0]['states'],[])
        self.assertEqual(signal_window(replay,86400,86405).payload()['series'][0]['states'],[[86399,'RED']])
        self.assertEqual(signal_window(replay,86405,86420).payload()['series'][0]['states'],[[86399,'RED'],[86405,'GREEN']])

    def test_zero_duration_and_window_validation(self):
        for args in [(0,0,900),(10,0,900),(0,100,0),(0,100,float('inf'))]:
            with self.assertRaises(ValueError):windows(*args)
        with tempfile.TemporaryDirectory() as folder:
            store=SqliteTrajectorySink(Path(folder)/'replay.sqlite',windows(0,40,20))
            try:
                trip=dict(Trip_ID='p:trip:1',Departure=0,Arrival=30)
                record=dict(vehicle='v',Agent_ID='p',Trip=trip,path=[[0,0],[0,0]],timestamps=[20,20],Distance_m=0)
                store.append(record)
                store.append(dict(record,vehicle='v2',Agent_ID='p2',Trip=dict(trip,Trip_ID='p2:trip:1'),
                                  path=[[0,0],[1,0]],Distance_m=100))
                store.append(dict(record,vehicle='v3',Agent_ID='p3',Trip=dict(trip,Trip_ID='p3:trip:1'),timestamps=[21,25]))
                store.finalize(settings=None,observation_end=40)
                self.assertEqual(len(store.block_records(0)),0)
                self.assertEqual(len(store.block_records(1)),3)
                self.assertEqual(store.visual_vehicle_counts,dict(reconstructed=3,with_representable_interval=1,
                    without_representable_interval=2,only_unavailable_motion_plans=1))
            finally:store.close()

    def test_aborted_and_pending_trips_without_closed_link_keep_metadata_only(self):
        source=[dict(type='departure',time='0',person='aborted',link='a'),
                dict(type='vehicle enters traffic',time='0',person='aborted',vehicle='va',link='a',relativePosition='0'),
                dict(type='departure',time='1',person='pending',link='a'),
                dict(type='vehicle enters traffic',time='1',person='pending',vehicle='vp',link='a',relativePosition='0'),
                dict(type='stuckAndAbort',time='10',person='aborted',vehicle='va',link='a')]
        with tempfile.TemporaryDirectory() as folder:
            store=SqliteTrajectorySink(Path(folder)/'replay.sqlite',windows(0,20,10))
            try:
                stats={}
                extract(source,LINKS,lambda _:True,viewer.color_velocidad,viewer.GEOD,
                        stats=stats,horizon=20,segment_sink=store)
                self.assertEqual(stats['observed_departures'],2)
                self.assertEqual(stats['reconstructed_vehicles'],0)
                self.assertEqual(stats['pending_link_intervals'],1)
                self.assertEqual(store.count,0)
                self.assertEqual([len(store.block_records(i)) for i in (0,1)],[0,0])
                rows=store.connection.execute('SELECT key,metadata FROM journeys').fetchall()
                metadata={json.loads(raw)['Person_ID']:(key,json.loads(raw)) for key,raw in rows}
                self.assertEqual(set(metadata),{'aborted','pending'})
                self.assertEqual(metadata['aborted'][1]['Status'],'aborted')
                self.assertEqual(metadata['aborted'][1]['Abort'],10)
                self.assertEqual(metadata['pending'][1]['Status'],'censored')
                self.assertEqual(metadata['pending'][1]['Observation_End'],20)
                payload=journey_payload(store.path,metadata['pending'][0],dict(run_id='fixture',iteration=0))
                self.assertEqual(payload['records'],[])
                self.assertEqual(payload['trip']['Person_ID'],'pending')
                self.assertEqual(store.observation_end_probe['time_seconds'],20)
                self.assertEqual(store.observation_end_probe['visible_agents'],0)
                self.assertEqual(store.observation_end_probe['censored_journeys'],1)
                self.assertEqual(store.observation_end_probe['censored_without_any_closed_interval'],1)
                self.assertEqual(store.observation_end_probe['censored_without_closed_interval_at_observation_end'],1)
            finally:store.close()

    def test_partial_final_bucket_keeps_terminal_record_only_in_native_store(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SqliteTrajectorySink(Path(folder) / 'replay.sqlite', windows(0, 25, 20))
            try:
                store.append(dict(vehicle='v', Agent_ID='p', timestamps=[25, 25],
                    path=[[0, 0], [0, 0]], Trip={'Trip_ID': 'p:trip:1', 'Departure': 25}))
                self.assertEqual(store.connection.execute('SELECT count(*) FROM segments').fetchone()[0], 1)
                self.assertEqual(store.connection.execute('SELECT count(*) FROM segment_blocks').fetchone()[0], 0)
                self.assertEqual(store.outside_window, 1)
            finally:
                store.close()

    def test_full_export_native_windows_identity_and_read_only_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            network=root/'network.xml.gz';event_path=root/'events.xml.gz';config=root/'config.xml'
            with gzip.open(network,'wt') as stream:
                stream.write('''<network><nodes><node id="n0" x="770000" y="1619000"/><node id="n1" x="770100" y="1619000"/><node id="n2" x="770200" y="1619000"/></nodes><links><link id="a" from="n0" to="n1" length="100" freespeed="10"/><link id="b" from="n1" to="n2" length="100" freespeed="10"/></links></network>''')
            with gzip.open(event_path,'wt') as stream:stream.write(EVENTS)
            config.write_text('<config><module name="qsim"><param name="useLanes" value="true"/></module></config>',encoding='utf-8')
            from simz1_run import sha256
            record=lambda path:dict(path=path.name,sha256=sha256(path))
            result=dict(events=record(event_path),network=record(network),plans={'path':'plans.xml','sha256':'fixture'},
                counts={'observed_departures':1},observed_event_end_seconds=86420)
            manifest=dict(run_id='paged-fixture',demand_seed=17,matsim_seed=23,
                counts=dict(planned_persons=1,planned_trips=1),results={'0':result},
                effective_config=record(config),time_horizon=dict(start_seconds=0,end_seconds=86440),
                replay_window=dict(start_seconds=86380,end_seconds=86440),demand_window=dict(start_seconds=0,end_seconds=86400))
            (root/'run-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            selection=dict(directory=root,manifest=manifest,iteration=0,network=network,events=event_path)
            destination=root/'webgl'/'index.html'
            with patch('simz1_motion.load_selected',return_value=context()),patch('simz1_signal_replay.selected_groups',return_value=GROUPS):
                report=export_paged_selected(selection,destination,window_seconds=20)
            self.assertEqual(report['counts']['selected_vehicles'],1)
            self.assertEqual(report['sample_rate'],1)
            self.assertEqual(report['run_id'],'paged-fixture')
            self.assertEqual([block['segments'] for block in report['blocks']],[1,2,0])
            block=decoded(destination.parent/'blocks/0001.html')
            self.assertEqual(block['hud']['run_id'],'paged-fixture')
            self.assertEqual(block['hud']['planned_persons'],1)
            self.assertEqual(block['pagination']['block_index'],1)
            self.assertEqual(block['replay_window'],dict(start_seconds=86400,end_seconds=86420))
            self.assertEqual(block['signal_replay']['series'][0]['states'],[[86399,'RED'],[86405,'GREEN']])
            self.assertEqual(block['lane_replay']['events'][0]['time'],86390)
            key=next(layer['data'] for layer in block['layers'] if layer['id']=='trips')[0]['Replay_Journey_Key']
            database_hash=sha256(destination.parent/'replay.sqlite')
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(destination.parent))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with urlopen(base+'/index.html') as response:self.assertIn(b'paged-fixture',response.read())
                query=urlencode(dict(key=key,run_id='paged-fixture',iteration=0))
                with urlopen(Request(base+'/api/journey?'+query,headers={'Accept-Encoding':'gzip'})) as response:
                    complete=json.loads(gzip.decompress(response.read()))
                self.assertEqual(len(complete['records']),2)
                self.assertEqual(complete['key'],key)
                for path,status in [('/replay.sqlite',403),('/%2e%2e/config.xml',403),
                    ('/api/journey?'+query.replace('paged-fixture','wrong-run'),400),('/api/journey?broken',400),
                    ('/api/journey?'+query.replace(key,'0'*64),404)]:
                    with self.assertRaises(HTTPError) as raised:urlopen(base+path)
                    self.assertEqual(raised.exception.code,status)
            finally:server.shutdown();thread.join();server.server_close()
            self.assertEqual(sha256(destination.parent/'replay.sqlite'),database_hash)
            wrong=dict(report,run_id='other-run')
            (destination.parent/'export-manifest.json').write_text(json.dumps(wrong),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'otra corrida'):
                handler_for(destination.parent)


class ObservationClocksTest(unittest.TestCase):
    def test_terminal_cleanup_counts_do_not_replace_exact_horizon_snapshot(self):
        report=dict(run_id='r',iteration=0,run_manifest_sha256='same',
            operational_counts=dict(pending_legs_at_horizon=12593),
            observation_end_probe=dict(time_seconds=90000,native_pending_trips_at_horizon=12593))
        operational=dict(run_id='r',iteration=0,manifest_sha256='same',
            pending=dict(active_snapshot_seconds=90000,active_vehicles_snapshot=12595),
            source_records=dict(progress_log=dict(sha256='log',reconciled=True)))
        annotate_observation_times(report,90001,operational)
        probe=report['observation_end_probe']
        self.assertEqual(probe['native_active_vehicles_at_probe_time'],12595)
        self.assertEqual(probe['native_pending_trips_at_stream_end'],12593)
        self.assertEqual(probe['native_pending_reference_time_seconds'],90001)
        self.assertNotIn('native_pending_trips_at_horizon',probe)
        self.assertEqual(report['operational_counts']['pending_legs_at_horizon'],12593)
        with self.assertRaisesRegex(ValueError,'no corresponde'):
            annotate_observation_times(report,90001,dict(operational,run_id='other'))


if __name__=='__main__':unittest.main()
