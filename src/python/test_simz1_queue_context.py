"""Prepared tiny SQLite fixtures; no HTTP, MATSim, browser or historical data."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simz1_continuous_replay import ContinuousReplay, RuntimeReadCache, connect
from simz1_paged_replay import packed
from simz1_queue_context import Limits, QueueContext, interval_key, hold_time, queue_domains


class QueueContextTests(unittest.TestCase):
    @staticmethod
    def geometry_link(start, end, x=0.0, y=0.0, tags=None):
        return dict(from_node=start,to_node=end,path=[[x,y],[x+.0001,y]],
                    num_lanes=1,opposing_lanes=0,lane_width_m=3.2,osm_tags=tags or {})

    def test_effective_domains_use_nodes_level_body_bounds_and_explicit_corridor(self):
        links=dict(road=self.geometry_link('a','b'),
                   adjacent=self.geometry_link('b','c',x=.001),
                   nearby=self.geometry_link('d','e',y=.0001),
                   remote=self.geometry_link('f','g',x=.01),
                   bridge=self.geometry_link('b','h',tags={'layer':'1'}))
        metadata=dict(available=True,links=links)
        domains=queue_domains(metadata)
        self.assertEqual(domains['road'],frozenset(('road','adjacent','nearby')))
        self.assertEqual(domains['remote'],frozenset(('remote',)))
        self.assertEqual(domains['bridge'],frozenset(('bridge',)))
        metadata['occupancy_corridors']=dict(schema='corridor-length-v1',corridors=dict(
            corridor=dict(link_ids=['road','remote'],length_m=100,represented_lanes=1)))
        corridor_domains=queue_domains(metadata)
        self.assertIn('remote',corridor_domains['road'])
        self.assertIn('adjacent',corridor_domains['remote'])
        self.assertNotIn('bridge',corridor_domains['remote'])
        del links['road']['from_node']
        self.assertIsNone(queue_domains(metadata))
        self.assertIsNone(queue_domains(dict(available=False)))

    def test_independent_streets_do_not_poison_transitive_adjacent_queue_closure(self):
        # Interleaved city-wide waits exhaust a bounded unscoped roster;
        # only the source-backed road A/B/C can constrain this seed.
        links=dict(road_a=self.geometry_link('a','b'),road_b=self.geometry_link('b','c',x=.001),
                   road_c=self.geometry_link('c','d',x=.002),remote=self.geometry_link('x','y',x=.01),
                   upstream=self.geometry_link('u','a',x=-.001))
        domains=queue_domains(dict(available=True,links=links))
        with closing(sqlite3.connect(self.database)) as db:
            for ident,link in ((2,'road_a'),(3,'road_b'),(4,'road_c')):
                self.records[ident]['Link_ID']=link
                db.execute('UPDATE segments SET payload=? WHERE id=?',(packed(self.records[ident]),ident))
            for i in range(Limits().max_records+12):
                vehicle='remote-'+str(i);start=.01*i;end=100;hold=start+3
                row={**self.records[4],'vehicle':vehicle,'Agent_ID':vehicle,'Link_ID':'remote',
                     'Replay_Journey_Key':vehicle,'timestamps':[start,end],
                     'Motion_Plan':dict(version=1,status='kinematic',distance_m=10,hold_start=hold,
                         phases=[[start,hold,0,10/(hold-start),0],[hold,end,10,0,0]])}
                ident=100+i
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(ident,vehicle,vehicle,start,end,packed(row)))
                for block in self.blocks:db.execute('INSERT INTO segment_blocks VALUES(?,?)',(block['index'],ident))
                db.execute('INSERT INTO journeys VALUES(?,?)',(vehicle,json.dumps(dict(
                    Person_ID=vehicle,Trip_ID=vehicle,Departure=start,Arrival=end,Status='completed'))))
            db.commit()
        original=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            cache=RuntimeReadCache(max_bytes=8*1024*1024,max_entries=512)
            scoped=self.resolver(db,cache,domains=domains).resolve([(4,self.records[4])])
            status=scoped['by_seed'][interval_key(self.records[4])]
            self.assertTrue(status['complete'])
            self.assertEqual(status['missing_topology_links'],[])
            self.assertEqual({row['vehicle'] for row in scoped['segments']},{'A','B','C'})
            self.assertEqual(scoped['transition_segments'],[self.records[1]])
            # A domain change cannot reuse the scoped closure cache entry.
            fallback=self.resolver(db,cache).resolve([(4,self.records[4])])
            fallback_status=fallback['by_seed'][interval_key(self.records[4])]
            self.assertFalse(fallback_status['complete'])
            self.assertEqual(fallback_status['reason'],'record_limit')
            self.assertIn('road_c',fallback_status['missing_topology_links'])
            self.assertEqual(fallback['segments'],[])
            warm=self.resolver(db,cache,domains=domains).resolve([(4,self.records[4])])
            self.assertEqual(warm['by_seed'],scoped['by_seed'])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),original)

    def test_large_historical_bucket_keeps_bounded_active_epoch_and_transitive_closure(self):
        with closing(sqlite3.connect(self.database)) as db:
            for i in range(5300):
                active=i>=5000; vehicle=('active-' if active else 'departed-')+str(i)
                start,end,hold=(4,12,7) if active else (0,1,.5)
                row={**self.records[4], 'vehicle':vehicle, 'Agent_ID':vehicle,
                     'Replay_Journey_Key':vehicle, 'timestamps':[start,end],
                     'Motion_Plan':dict(version=1,status='kinematic',distance_m=10,hold_start=hold,
                         phases=[[start,hold,0,10/(hold-start),0],[hold,end,10,0,0]])}
                ident=i+100
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
                           (ident,vehicle,vehicle,start,end,packed(row)))
                db.execute('INSERT INTO segment_blocks VALUES(0,?)',(ident,))
                db.execute('INSERT INTO journeys VALUES(?,?)',(vehicle,json.dumps(dict(
                    Person_ID=vehicle,Trip_ID=vehicle,Departure=start,Arrival=end,Status='completed'))))
            db.commit()
        original=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            cache=RuntimeReadCache(max_bytes=8*1024*1024,max_entries=512)
            resolver=self.resolver(db,cache)
            # Both epochs share source bucket zero but must not share snapshots.
            later=resolver.bucket(0,11)
            earlier=resolver.bucket(0,5)
            self.assertIsNone(later['reason']);self.assertIsNone(earlier['reason'])
            self.assertEqual(len(later['records']),302)
            self.assertEqual(len(earlier['records']),302)
            self.assertNotEqual({r[0] for r in later['records']},{r[0] for r in earlier['records']})
            result=resolver.resolve([(4,self.records[4])])
            status=result['by_seed'][interval_key(self.records[4])]
            self.assertTrue(status['complete'])
            self.assertEqual(len(result['segments']),303)
            self.assertTrue({'A','B','C'}.issubset({r['vehicle'] for r in result['segments']}))
            self.assertFalse(any(r['vehicle'].startswith('departed-') for r in result['segments']))
            repeated=self.resolver(db,cache).resolve([(4,self.records[4])])
            self.assertEqual(repeated['by_seed'],result['by_seed'])
            limited=self.resolver(db,limits=replace(Limits(),max_rows=40)).resolve([(4,self.records[4])])
            self.assertEqual(limited['by_seed'][interval_key(self.records[4])]['reason'],'row_limit')
            self.assertEqual(limited['segments'],[])
            old_record_limit=self.resolver(db,limits=replace(Limits(),max_records=256)).resolve([(4,self.records[4])])
            self.assertEqual(old_record_limit['by_seed'][interval_key(self.records[4])]['reason'],'record_limit')
            self.assertEqual(old_record_limit['segments'],[])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),original)

    def test_native_facility_is_retained_as_temporal_context_without_inventing_a_lane(self):
        row=dict(timestamps=[10,125],Motion_Plan=dict(status='stationary',distance_m=0),
                 Boundary_Provenance=dict(start='VehicleArrivesAtFacility',end='VehicleDepartsAtFacility'))
        self.assertEqual(hold_time(row),10)
        row['Boundary_Provenance']['end']='left link'
        self.assertIsNone(hold_time(row))

    def test_stationary_post_service_interval_is_context_without_a_wait_event(self):
        row=dict(timestamps=[20,21],Motion_Plan=dict(status='stationary',distance_m=0),
                 Boundary_Provenance=dict(start='VehicleDepartsAtFacility',end='left link',
                                          start_relative=1,end_relative=1))
        self.assertEqual(hold_time(row),20)
        row['Boundary_Provenance']['end_relative']=.5
        self.assertIsNone(hold_time(row))
        row['Boundary_Provenance']['end_relative']=1
        row['Motion_Plan']['distance_m']=1
        self.assertIsNone(hold_time(row))

    def native_geometry(self):
        return dict(schema_version=1,available=True,links=dict(road=self.geometry_link('a','b')),
                    occupancy_corridors=dict(schema='corridor-length-v1',corridors=dict(road=dict(link_ids=['road'],represented_lanes=1))))

    def test_causal_native_order_retains_predecessors_and_falls_back_for_unknown_geometry(self):
        metadata=self.native_geometry()
        for ident,ordinal in ((2,10),(3,20),(4,30)):
            self.records[ident]['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=ordinal)
        later={**self.records[2],'vehicle':'later','Agent_ID':'later','Replay_Journey_Key':'later',
               'Native_Occupancy':dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=40),
               'timestamps':[0,100], 'Motion_Plan':dict(version=1,status='kinematic',distance_m=10,hold_start=90,
                       phases=[[0,90,0,10/90,0],[90,100,10,0,0]])}
        with closing(sqlite3.connect(self.database)) as db:
            for ident in (2,3,4):db.execute('UPDATE segments SET payload=? WHERE id=?',(packed(self.records[ident]),ident))
            db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(5,'later','later',0,100,packed(later)))
            for block in self.blocks:db.execute('INSERT INTO segment_blocks VALUES(?,5)',(block['index'],))
            db.execute('INSERT INTO journeys VALUES(?,?)',('later',json.dumps(dict(Person_ID='later',Departure=0,Arrival=100,Status='completed'))))
            db.commit()
        before=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            cache=RuntimeReadCache()
            def resolve(geometry):
                return QueueContext(db,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
                    validate_trip=lambda trip:None,cache=cache,domains={'road':{'road'}},visual_lanes=geometry).resolve([(4,self.records[4])])
            result=resolve(metadata)
            self.assertTrue(result['by_seed'][interval_key(self.records[4])]['complete'])
            self.assertEqual({r['vehicle'] for r in result['segments']},{'A','B','C'})
            self.assertEqual(resolve(metadata)['by_seed'],result['by_seed'])
            # Missing topology cannot certify that a record has native FIFO order.
            fallback=resolve(None)
            self.assertIn('later',{r['vehicle'] for r in fallback['segments']})
            resolver=QueueContext(db,self.blocks,validate_segment=lambda *a:None,validate_trip=lambda t:None,visual_lanes=metadata)
            self.assertEqual(resolver.reservation_order(later),40)
            for change in ({'model_slot':99},{'ordinal':True},{'ordinal':-1},{'corridor_id':'missing'},
                           {'passage_links':['missing'],'passage_slots':[0],'receipt_link':'road'}):
                invalid={**later,'Native_Occupancy':{**later['Native_Occupancy'],**change}}
                self.assertIsNone(resolver.reservation_order(invalid))
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),before)

    def test_bounded_native_predecessor_chain_can_exceed_old_128_record_limit(self):
        metadata=self.native_geometry()
        blocks=[dict(index=i,start_seconds=i*100,end_seconds=(i+1)*100) for i in range(182)]
        chain=[]
        with closing(sqlite3.connect(self.database)) as db:
            for table in ('segment_blocks','segments','journeys','lane_events'):db.execute('DELETE FROM '+table)
            for i in range(180):
                start,hold,end=i*100,i*100+50,i*100+151
                vehicle='chain-'+str(i)
                row={**self.records[4],'vehicle':vehicle,'Agent_ID':vehicle,'Replay_Journey_Key':vehicle,
                     'timestamps':[start,end], 'Native_Occupancy':dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=i+1),
                     'Motion_Plan':dict(version=1,status='kinematic',distance_m=10,hold_start=hold,
                                       phases=[[start,hold,0,.2,0],[hold,end,10,0,0]])}
                chain.append((i+1,row))
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(i+1,vehicle,vehicle,start,end,packed(row)))
                for block in blocks:
                    if start<block['end_seconds'] and end>block['start_seconds']:
                        db.execute('INSERT INTO segment_blocks VALUES(?,?)',(block['index'],i+1))
                db.execute('INSERT INTO journeys VALUES(?,?)',(vehicle,json.dumps(dict(Person_ID=vehicle,Departure=start,Arrival=end,Status='completed'))))
            db.commit()
        with closing(connect(self.database)) as db:
            def resolve(limits=None):
                return QueueContext(db,blocks,validate_segment=ContinuousReplay.validate_native_segment,
                    validate_trip=lambda t:None,limits=limits,domains={'road':{'road'}},visual_lanes=metadata).resolve([chain[-1]])
            result=resolve();status=result['by_seed'][interval_key(chain[-1][1])]
            self.assertTrue(status['complete'])
            self.assertEqual(status['metrics']['depth'],179)
            self.assertEqual(status['metrics']['buckets'],180)
            self.assertEqual(len(result['segments']),180)
            for limits,reason in ((replace(Limits(),max_depth=8),'depth_limit'),
                                  (replace(Limits(),max_buckets=4),'bucket_limit'),
                                  (replace(Limits(),max_records=128),'record_limit')):
                rejected=resolve(limits)
                self.assertEqual(rejected['by_seed'][interval_key(chain[-1][1])]['reason'],reason)
                self.assertEqual(rejected['segments'],[])

    def test_transferred_moving_leader_remains_context_despite_newer_receiver_ordinal(self):
        metadata=self.native_geometry()
        metadata['links']['receiver']=self.geometry_link('b','c',x=.0001)
        metadata['occupancy_corridors']['corridors']['receiver']=dict(link_ids=['receiver'],represented_lanes=1)
        source=self.records[1]
        source['Link_ID']='road'
        source['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=20)
        leading=self.records[3]
        leading['Link_ID']='receiver'
        leading['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='receiver',model_slot=0,ordinal=40)
        leading['Motion_Plan']=dict(version=1,status='constant',distance_m=10,phases=[[1,20,0,10/19,0]])
        leading['Observed_Waits']={}
        follower=self.records[4]
        follower['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=30)
        with closing(sqlite3.connect(self.database)) as db:
            for ident in (1,3,4):db.execute('UPDATE segments SET payload=? WHERE id=?',(packed(self.records[ident]),ident))
            db.commit()
        before=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            resolver=QueueContext(db,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
                validate_trip=lambda t:None,domains=queue_domains(metadata),visual_lanes=metadata)
            result=resolver.resolve([(4,follower)])
        status=result['by_seed'][interval_key(follower)]
        self.assertTrue(status['complete'])
        self.assertEqual(status['record_keys'],[interval_key(follower)])
        self.assertEqual(result['segments'],[follower])
        self.assertIn(leading,result['transition_segments'])
        self.assertIn(source,result['transition_segments'])
        self.assertIsNone(hold_time(leading))
        self.assertEqual(set(result['trips']),{'B-journey','C-journey'})
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),before)

    def test_historical_moving_neighbor_resolves_its_departed_fifo_release_predecessors(self):
        metadata=self.native_geometry()
        metadata['links']['receiver']=self.geometry_link('b','c',x=.0001)
        metadata['occupancy_corridors']['corridors']['receiver']=dict(link_ids=['receiver'],represented_lanes=1)
        prior=self.records[1]
        prior.update(Link_ID='road',timestamps=[0,8],Native_Occupancy=dict(
            policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=20),
            Motion_Plan=dict(version=1,status='kinematic',distance_m=10,hold_start=5,
                             phases=[[0,5,0,2,0],[5,8,10,0,0]]))
        departed=self.records[2]
        departed.update(timestamps=[0,6],Native_Occupancy=dict(
            policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=10),
            Motion_Plan=dict(version=1,status='kinematic',distance_m=10,hold_start=3,
                             phases=[[0,3,0,10/3,0],[3,6,10,0,0]]))
        leading=self.records[3]
        leading.update(Link_ID='receiver',timestamps=[8,20],Observed_Waits={},Native_Occupancy=dict(
            policy='corridor-length-v1',corridor_id='receiver',model_slot=0,ordinal=40),
            Motion_Plan=dict(version=1,status='constant',distance_m=10,phases=[[8,20,0,10/12,0]]))
        follower=self.records[4]
        follower['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=30)
        with closing(sqlite3.connect(self.database)) as db:
            for ident in (1,2,3,4):
                row=self.records[ident]
                db.execute('UPDATE segments SET start=?,end=?,payload=? WHERE id=?',(*row['timestamps'],packed(row),ident))
            db.commit()
        with closing(connect(self.database)) as db:
            result=QueueContext(db,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
                validate_trip=lambda t:None,domains=queue_domains(metadata),visual_lanes=metadata).resolve([(4,follower)])
        status=result['by_seed'][interval_key(follower)]
        self.assertTrue(status['complete'])
        self.assertEqual(set(status['record_keys']),{interval_key(row) for row in (departed,prior,follower)})
        self.assertIn(leading,result['transition_segments'])
        self.assertIsNone(hold_time(leading))
        self.assertLess(departed['timestamps'][1],hold_time(follower))

    def test_future_wait_anchor_used_by_approach_keeps_its_recorded_dependencies(self):
        leading=self.records[3]
        leading['Motion_Plan']=dict(version=1,status='kinematic',distance_m=10,hold_start=18,
                                   phases=[[1,18,0,10/17,0],[18,20,10,0,0]])
        leading['Observed_Waits']['storage_wait']['first']=18
        future={**self.records[4],'vehicle':'future','Agent_ID':'future','Replay_Journey_Key':'future',
                'timestamps':[15,25], 'Motion_Plan':dict(version=1,status='kinematic',distance_m=10,
                    hold_start=16,phases=[[15,16,0,10,0],[16,25,10,0,0]])}
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE segments SET payload=? WHERE id=3',(packed(leading),))
            db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(5,'future','future',15,25,packed(future)))
            db.execute('INSERT INTO segment_blocks VALUES(0,5)')
            db.execute('INSERT INTO journeys VALUES(?,?)',('future',json.dumps(dict(
                Person_ID='future',Departure=15,Arrival=25,Status='completed'))))
            db.commit()
        before=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            cache=RuntimeReadCache()
            resolver=self.resolver(db,cache)
            payload=resolver.resolve([(4,self.records[4])])
            status=payload['by_seed'][interval_key(self.records[4])]
            self.assertTrue(status['complete'])
            # Replay interpolation caps the moving approach by its known future
            # anchor. That anchor must be resolved from recorded dependencies;
            # classifying B as an auxiliary moving row would falsely certify it.
            self.assertEqual(set(status['record_keys']),{interval_key(row) for row in
                             (self.records[4],leading,future)})
            self.assertEqual(status['metrics']['hold_records'],3)
            self.assertEqual(status['metrics']['moving_records'],0)
            self.assertIn(leading,payload['segments'])
            self.assertIn(future,payload['segments'])
            self.assertEqual(resolver.resolve([(4,self.records[4])])['by_seed'],payload['by_seed'])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),before)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='simz1-queue-context-fixture-')
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'fixture.sqlite'
        self.blocks = [dict(index=i, start_seconds=i * 30, end_seconds=(i + 1) * 30) for i in range(4)]

        def record(vehicle, link, start, end, hold=None):
            distance = 10
            phases = [[start, end, 0, distance / (end - start), 0]] if hold is None else [
                [start, hold, 0, distance / (hold - start), 0], [hold, end, distance, 0, 0]]
            return dict(vehicle=vehicle, Agent_ID=vehicle + '-person', Link_ID=link,
                        Replay_Journey_Key=vehicle + '-journey', timestamps=[start, end],
                        path=[[0, 0], [.0001, 0]], Motion_Plan=dict(version=1, status='kinematic',
                        distance_m=distance, phases=phases, hold_start=hold),
                        Observed_Waits={} if hold is None else {'storage_wait': dict(first=hold,
                            position_evidence='queue_exit', sources=['MATSim15_QNode_native_branch'])})

        # A is already gone at C's hold; it still fixed B's slot at B's hold.
        # The non-hold predecessor is geometry-only, never part of the roster.
        self.records = {1: record('B', 'upstream', 0, 1), 2: record('A', 'road', 0, 8, 5),
                        3: record('B', 'road', 1, 20, 7), 4: record('C', 'road', 9, 100, 11)}
        self.events = [dict(vehicle=vehicle, time=time, type='entered lane', link='road', lane='native-0')
                       for vehicle, time in [('A', 0), ('B', 1), ('C', 9)]]
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('''CREATE TABLE segments(id INTEGER PRIMARY KEY,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                CREATE INDEX segments_journey ON segments(journey,id);
                CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                CREATE INDEX segments_block ON segment_blocks(block,segment);
                CREATE TABLE journeys(key TEXT PRIMARY KEY,metadata TEXT);
                CREATE TABLE lane_events(seq INTEGER PRIMARY KEY,vehicle TEXT,time REAL,payload BLOB);
                CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);
                CREATE INDEX lanes_time ON lane_events(time,seq);''')
            for ident, row in self.records.items():
                start, end = row['timestamps']
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
                           (ident, row['Replay_Journey_Key'], row['vehicle'], start, end, packed(row)))
                for block in self.blocks:
                    if start < block['end_seconds'] and end > block['start_seconds']:
                        db.execute('INSERT INTO segment_blocks VALUES(?,?)', (block['index'], ident))
                trip = dict(Person_ID=row['Agent_ID'], Trip_ID=row['Agent_ID'] + ':trip:0001', Departure=start,
                            Arrival=100 if row['vehicle'] == 'C' else 20 if row['vehicle'] == 'B' else 8, Status='completed')
                db.execute('INSERT OR IGNORE INTO journeys VALUES(?,?)', (row['Replay_Journey_Key'], json.dumps(trip)))
            for seq, event in enumerate(self.events, 1):
                db.execute('INSERT INTO lane_events VALUES(?,?,?,?)', (seq, event['vehicle'], event['time'], packed(event)))
            db.commit()
        self.native_hash = hashlib.sha256(self.database.read_bytes()).hexdigest()

    def resolver(self, db, cache=None, limits=None, domains=None):
        return QueueContext(db, self.blocks, validate_segment=ContinuousReplay.validate_native_segment,
                            validate_trip=lambda trip: None, cache=cache, limits=limits, domains=domains)

    def replay(self, cache):
        replay = ContinuousReplay.__new__(ContinuousReplay)
        replay.identity = dict(run_id='synthetic-context', iteration=0, run_manifest_sha256='a' * 64)
        replay.manifest = dict(window_count=4, window_seconds=30, replay_window=dict(start_seconds=0, end_seconds=120))
        replay.source_manifest = dict(source_type='sqlite-direct-v1')
        replay.blocks, replay.block_ends = self.blocks, [block['end_seconds'] for block in self.blocks]
        replay.connection = lambda: connect(self.database)
        replay.temporal = lambda *args: ({'series': []}, [])
        replay.queue_context_cache = cache
        return replay

    def test_transitive_departed_leader_and_native_lane_evidence_are_complete(self):
        fractional = {**self.records[4], 'timestamps': [0.00001, 130.0]}
        self.assertEqual(interval_key(fractional), '["C","C-journey","road",[0.00001,130]]')
        with closing(connect(self.database)) as db:
            payload = self.resolver(db).resolve([(4, self.records[4])])
        status = payload['by_seed'][interval_key(self.records[4])]
        self.assertTrue(status['complete'])
        self.assertEqual(set(status['record_keys']), {interval_key(self.records[i]) for i in (2, 3, 4)})
        self.assertEqual({row['vehicle'] for row in payload['segments']}, {'A', 'B', 'C'})
        self.assertEqual(payload['transition_segments'], [self.records[1]])
        self.assertEqual(payload['lane_events'], self.events)
        self.assertEqual(set(payload['trips']), {'A-journey', 'B-journey', 'C-journey'})
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.native_hash)

    def test_same_seed_has_identical_closure_in_two_windows_cold_warm_and_reverse(self):
        cache = RuntimeReadCache(max_bytes=1024 * 1024, max_entries=128)
        replay = self.replay(cache)
        first = replay.window(1)['queue_context']
        successor = replay.window(2)['queue_context']
        reverse = replay.window(1)['queue_context']
        cold = self.replay(RuntimeReadCache(max_bytes=1024 * 1024, max_entries=128)).window(2)['queue_context']
        key = interval_key(self.records[4])
        for other in (successor, reverse, cold):
            self.assertEqual(other['by_seed'][key], first['by_seed'][key])
            for field in ('segments', 'transition_segments', 'trips', 'lane_events'):
                self.assertEqual(other[field], first[field])
        self.assertTrue(first['by_seed'][key]['complete'])
        self.assertGreater(successor['metrics']['cache_hits'], 0)
        self.assertEqual(successor['metrics']['sql_queries'], 0)
        self.assertLessEqual(cache.summary()['accounted_bytes'], cache.max_bytes)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.native_hash)

    def test_released_vehicle_keeps_predecessor_hold_closure_after_window_change(self):
        # C's current interval is moving; its preceding hold was fixed behind B,
        # whose slot was itself fixed behind departed A. All three are needed to
        # reconstruct the release origin on a cold seek after the source hold.
        prior = self.records[4]
        prior['timestamps'][1] = 80
        prior['Motion_Plan']['phases'][-1][1] = 80
        released = {**prior, 'Link_ID': 'downstream', 'timestamps': [80, 120],
                    'Motion_Plan': dict(version=1, status='constant', distance_m=10,
                                        phases=[[80,120,0,.25,0]]), 'Observed_Waits': {}}
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE segments SET end=80,payload=? WHERE id=4', (packed(prior),))
            db.execute('DELETE FROM segment_blocks WHERE segment=4 AND block=3')
            db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
                       (5, released['Replay_Journey_Key'], 'C', 80, 120, packed(released)))
            for index in (2,3): db.execute('INSERT INTO segment_blocks VALUES(?,5)', (index,))
            db.commit()
        original = hashlib.sha256(self.database.read_bytes()).hexdigest()
        cache = RuntimeReadCache(max_bytes=1024*1024, max_entries=128)
        replay = self.replay(cache)
        earlier = replay.window(2)
        later = replay.window(3)
        reverse = replay.window(2)
        cold = self.replay(RuntimeReadCache(max_bytes=1024*1024, max_entries=128)).window(3)
        self.assertEqual(later['segments'], [released])
        self.assertEqual(later['context_segments'], [prior])
        key = interval_key(prior)
        for payload in (earlier, later, reverse, cold):
            closure = payload['queue_context']
            self.assertTrue(closure['by_seed'][key]['complete'])
            self.assertEqual({row['vehicle'] for row in closure['segments']}, {'A','B','C'})
            self.assertEqual(closure['by_seed'][key], earlier['queue_context']['by_seed'][key])
        self.assertNotIn(interval_key(released), later['queue_context']['by_seed'], 'moving interval is not a fabricated HOLD')
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), original)

    def test_budget_failure_never_exposes_partial_roster_and_cache_does_not_expand_budget(self):
        for limits, reason in [(replace(Limits(), max_records=1), 'record_limit'),
                               (replace(Limits(), max_rows=1), 'row_limit'),
                               (replace(Limits(), max_depth=0), 'depth_limit')]:
            with self.subTest(reason=reason), closing(connect(self.database)) as db:
                cache = RuntimeReadCache(max_bytes=1024 * 1024, max_entries=128)
                cold = self.resolver(db, cache, limits).resolve([(4, self.records[4])])
                warm = self.resolver(db, cache, limits).resolve([(4, self.records[4])])
                key = interval_key(self.records[4])
                self.assertEqual(cold['by_seed'][key], warm['by_seed'][key])
                self.assertFalse(cold['by_seed'][key]['complete'])
                self.assertEqual(cold['by_seed'][key]['reason'], reason)
                self.assertEqual(cold['by_seed'][key]['record_keys'], [])
                for field in ('segments', 'transition_segments', 'lane_events'):
                    self.assertEqual(cold[field], [])
                self.assertEqual(cold['trips'], {})
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.native_hash)


class CompactQueueContextTests(QueueContextTests):
    """Run the same native closure/budget contracts through compact caching."""
    def setUp(self):
        super().setUp()
        self.compact_records=RuntimeReadCache(1024*1024,1024)
        self.compact_seeds=RuntimeReadCache(1024*1024,1024)
        self.compact_dependencies=RuntimeReadCache(1024*1024,1024)
        self.compact_index=RuntimeReadCache(1024*1024,16)

    def resolver(self, db, cache=None, limits=None, domains=None):
        resolver=super().resolver(db,cache,limits,domains)
        resolver.record_cache=self.compact_records
        resolver.seed_cache=self.compact_seeds
        resolver.dependency_cache=self.compact_dependencies
        resolver.index_cache=self.compact_index
        return resolver

    def replay(self, cache):
        replay=super().replay(cache)
        replay.queue_record_cache=self.compact_records
        replay.queue_seed_cache=self.compact_seeds
        replay.queue_dependency_cache=self.compact_dependencies
        replay.queue_index_cache=self.compact_index
        return replay

    def test_many_distinct_epochs_decode_each_record_once_and_keep_exact_budgets(self):
        with closing(connect(self.database)) as db:
            reference=QueueContextTests.resolver(self,db)
            compact=self.resolver(db,RuntimeReadCache(1024*1024,1024))
            for at in [10+i*.1 for i in range(80)]:
                self.assertEqual(reference.bucket(0,at),compact.bucket(0,at))
            self.assertGreater(reference.metrics['decoded_records'],100)
            self.assertLessEqual(compact.metrics['decoded_records'],3)
            for limits in [replace(Limits(),max_rows=1),replace(Limits(),max_compressed_bytes=1),
                           replace(Limits(),max_decoded_bytes=1),replace(Limits(),max_record_bytes=1)]:
                baseline=QueueContextTests.resolver(self,db,limits=limits).bucket(0,11)
                bounded=self.resolver(db,RuntimeReadCache(),limits=limits).bucket(0,11)
                self.assertEqual(baseline,bounded)
            self.assertLessEqual(self.compact_records.summary()['accounted_bytes'],1024*1024)

    def test_compact_full_closure_matches_uncached_reference(self):
        with closing(connect(self.database)) as db:
            seeds=[(i,self.records[i]) for i in (2,3,4)]
            reference=QueueContextTests.resolver(self,db).resolve(seeds)
            compact=self.resolver(db,RuntimeReadCache()).resolve(seeds)
            reference.pop('metrics');compact.pop('metrics')
            self.assertEqual(reference,compact)
            for _ in range(2):
                warm=self.resolver(db,RuntimeReadCache()).resolve(seeds)
                warm.pop('metrics')
                self.assertEqual(reference,warm)
            self.assertLessEqual(self.compact_seeds.summary()['accounted_bytes'],1024*1024)


if __name__ == '__main__':
    unittest.main()
