"""Small immutable SQLite fixtures for causal support; never read native runs."""
from contextlib import closing
from dataclasses import replace
import hashlib
import gzip
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from simz1_continuous_replay import ContinuousReplay, connect
from simz1_paged_replay import packed
from simz1_queue_context import QueueContext, Limits, interval_key, hold_time, queue_domains, scalar_interval_key, occupancy_absence, VerifiedFacilitySupport, validate_facility_support
from simz1_queue_support import SupportIndex, FIELDS, contract, _transfer, _temporal_bins
from simz1_queue_support import AuxiliaryStorageScope,AuxiliaryStorageExceeded
import test_simz1_queue_context as fixture


class SupportTests(unittest.TestCase):
    def setUp(self):
        fixture.QueueContextTests.setUp(self)
        self.geometry = dict(schema_version=1, available=True, links={
            'road': fixture.QueueContextTests.geometry_link('a','b'),
            'upstream': fixture.QueueContextTests.geometry_link('z','a',x=-.0001)},
            occupancy_corridors=dict(schema='corridor-length-v1', corridors={}))
        self.identity = dict(run_id='synthetic-support',iteration=0,run_manifest_sha256='a'*64)

    def prepare(self, db):
        expected = contract(self.database,self.identity,self.native_hash,self.geometry)
        return SupportIndex.prepare(self.database.parent/'support',db,expected,
            validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry)

    def resolve(self, db, index=None, limits=None):
        return QueueContext(db,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
            validate_trip=lambda trip:None,visual_lanes=self.geometry,domains=queue_domains(self.geometry),
            support_index=index,limits=limits).resolve([(4,self.records[4])])

    def test_complete_small_reference_equivalence_and_source_preserved(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            old, new = self.resolve(db), self.resolve(db,index)
            self.assertTrue(new['by_seed'][interval_key(self.records[4])]['complete'])
            for name in ('segments','transition_segments'):
                self.assertEqual(sorted(old[name],key=interval_key),sorted(new[name],key=interval_key))
            for name in ('trips','lane_events'):
                self.assertEqual(old[name],new[name])
            self.assertEqual(index.receipt['records'],4)
            self.assertEqual(index.receipt['peak_decoded_records'],1)
            self.assertEqual(index.receipt['unknown_links'],[])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),self.native_hash)

    def test_worker_open_uses_independent_digest_without_source_decode(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            expected=index.receipt['contract']
            with closing(SupportIndex(index.path,expected,expected_sha256=index.receipt['sha256'])) as reopened:
                self.assertEqual(reopened.path,index.path)

    def test_support_build_rejects_aggregate_budget_without_publishing(self):
        directory=self.database.parent/'too-small-support'
        expected=contract(self.database,self.identity,self.native_hash,self.geometry)
        with closing(connect(self.database)) as db,self.assertRaises(AuxiliaryStorageExceeded):
            SupportIndex.prepare(directory,db,expected,validate_segment=ContinuousReplay.validate_native_segment,
                visual_lanes=self.geometry,max_disk_bytes=1)
        self.assertFalse(list(directory.glob('*.sqlite')))
        self.assertFalse(list(directory.glob('*.json')))
        self.assertTrue(list(directory.glob('build-*')),'Incomplete owned build is preserved for diagnosis')
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),self.native_hash)

    def test_support_reuse_counts_fixed_index_without_counting_other_history(self):
        with closing(connect(self.database)) as db,closing(self.prepare(db)) as index:
            expected=index.receipt['contract'];path=index.path
        history=path.parent/'preserved-other-index.bin';history.write_bytes(b'H'*1024*1024)
        historical_hash=hashlib.sha256(history.read_bytes()).hexdigest()
        fixed_bytes=path.stat().st_size+path.with_suffix('.json').stat().st_size
        with closing(connect(self.database)) as db,closing(SupportIndex.prepare(path.parent,db,expected,
                validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry,
                max_disk_bytes=fixed_bytes+32768)) as index:
            self.assertGreaterEqual(index.storage_report['observed_bytes'],fixed_bytes)
            self.assertLessEqual(index.storage_report['peak_observed_bytes'],fixed_bytes+32768)
        with closing(connect(self.database)) as db,self.assertRaises(AuxiliaryStorageExceeded):
            SupportIndex.prepare(path.parent,db,expected,validate_segment=ContinuousReplay.validate_native_segment,
                visual_lanes=self.geometry,max_disk_bytes=fixed_bytes-1)
        self.assertEqual(hashlib.sha256(history.read_bytes()).hexdigest(),historical_hash)

    def test_support_can_borrow_the_single_live_storage_scope(self):
        expected=contract(self.database,self.identity,self.native_hash,self.geometry)
        with AuxiliaryStorageScope(self.database.parent/'borrowed',4*1024**2) as scope:
            with closing(connect(self.database)) as db,closing(SupportIndex.prepare(scope.root/'indices',db,expected,
                    validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry,storage_scope=scope)) as index:
                self.assertEqual(index.storage_report['root'],str(scope.root))
                self.assertTrue(scope.active)
                self.assertGreater(scope.check('borrowed_after')['observed_bytes'],index.path.stat().st_size)

    def test_changed_index_bytes_rejected(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            path, expected, checksum = index.path, index.receipt['contract'], index.receipt['sha256']
        with path.open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'):
            SupportIndex(path,expected,expected_sha256=checksum)

    def test_identity_geometry_and_source_revision_are_not_interchangeable(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            path, expected=index.path,index.receipt['contract']
            for field,value in (('identity',{**self.identity,'iteration':1}),('geometry_sha256','c'*64),
                                ('database_sha256','b'*64),('sources',{})):
                with self.assertRaisesRegex(ValueError,'identity/source/completeness'):
                    SupportIndex(path,{**expected,field:value},expected_sha256=index.receipt['sha256'])

    def test_incomplete_or_forged_coverage_rejected(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            path, expected=index.path,index.receipt['contract']
            receipt=json.loads(path.with_suffix('.json').read_text())
            for changed in ({**receipt,'complete':False},{**receipt,'records':3}):
                path.with_suffix('.json').write_text(json.dumps(changed))
                with self.assertRaises(ValueError):SupportIndex(path,expected,expected_sha256=receipt['sha256'])
            path.with_suffix('.json').write_text(json.dumps(receipt))

    def test_index_and_receipt_rehashed_forgery_cannot_omit_dependencies(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            path, expected, checksum=index.path,index.receipt['contract'],index.receipt['sha256']
        with closing(sqlite3.connect(path)) as changed:
            changed.execute("UPDATE support SET link='forged' WHERE link='road'");changed.commit()
        receipt=json.loads(path.with_suffix('.json').read_text())
        receipt['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix('.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'bytes changed'):
            SupportIndex(path,expected,expected_sha256=checksum)
        with closing(connect(self.database)) as db:
            with self.assertRaisesRegex(ValueError,'derived scalar'):
                self.prepare(db)

    def test_original_request_limits_still_reject_without_partial_context(self):
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            for limits,reason in ((replace(Limits(),max_rows=2),'row_limit'),
                                  (replace(Limits(),max_records=1),'record_limit'),
                                  (replace(Limits(),max_decoded_bytes=100),'decoded_byte_limit')):
                result=self.resolve(db,index,limits)
                self.assertEqual(result['by_seed'][interval_key(self.records[4])]['reason'],reason)
                self.assertEqual(result['segments'],[])

    def test_unknown_link_is_never_filtered_from_temporal_query(self):
        with closing(sqlite3.connect(self.database)) as db:
            row={**self.records[2],'Link_ID':'not-in-geometry'}
            db.execute('UPDATE segments SET payload=? WHERE id=2',(packed(row),));db.commit()
        self.native_hash=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db, closing(self.prepare(db)) as index:
            self.assertEqual(index.receipt['unknown_links'],['not-in-geometry'])
            self.assertIn(2,{row['id'] for row in index.candidates(7,{'road'},100)})

    def test_transfer_proof_retains_potential_predecessor_and_unknowns(self):
        links={'a':dict(to_node='join'),'b':dict(from_node='join')}
        prior=dict(journey='x',vehicle='x',agent='x',start=0,end=10,link='a',ordinal=3,
                   corridor='A',slot=0,end_relative=1,transfer=(1,None,None,None))
        current=dict(journey='x',vehicle='x',agent='x',start=10,end=20,link='b',ordinal=9,
                     corridor='B',slot=0,start_relative=0)
        self.assertEqual(_transfer(prior,current,links),(1,'A',0,3))
        self.assertEqual(_transfer(prior,{**current,'start':11},links),(1,None,None,None))
        self.assertEqual(_transfer(prior,{**current,'ordinal':None},links),(0,None,None,None))
        self.assertEqual(_transfer(prior,current,{}),(0,None,None,None))

    def test_source_id_order_cannot_claim_a_different_temporal_predecessor(self):
        with closing(sqlite3.connect(self.database)) as db:
            rows=db.execute('SELECT id,journey,start,end,payload FROM segments ORDER BY id').fetchall()
            # A minimal independent source preserves valid payloads but gives
            # two consecutive observations reversed ids in one journey.
            journey=rows[0][1]
            same=[row for row in rows if row[1]==journey]
            if len(same)<2:self.fail('Fixture requires consecutive observations')
            first,last=same[0],same[-1]
            db.execute('UPDATE segments SET id=-100 WHERE id=?',(first[0],))
            db.execute('UPDATE segments SET id=? WHERE id=?',(first[0],last[0]))
            db.execute('UPDATE segments SET id=? WHERE id=-100',(last[0],));db.commit()
        self.native_hash=hashlib.sha256(self.database.read_bytes()).hexdigest()
        with closing(connect(self.database)) as db:
            with self.assertRaisesRegex(ValueError,'temporal neighbor order'):self.prepare(db)


class IndexedReleaseTests(unittest.TestCase):
    def test_final_hold_requires_previous_release_final_but_not_across_a_gap(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        for gap in (0,1):
            with self.subTest(gap=gap):
                source=CausalSupportGraphTests();source.setUp()
                try:
                    rows={1:source.record('bus','a',0,5,1,hold=4),
                          2:source.record('bus','b',5+gap,20,2,hold=10)}
                    source.write_source(rows)
                    result=source.resolve(2)
                    status=result['by_seed'][interval_key(rows[2])]
                    self.assertTrue(status['complete'])
                    phases=status['support_certificate']['phase_keys']
                    if gap==0:
                        self.assertEqual(phases.get(interval_key(rows[1])),'final',
                            'The previous native HOLD controls the new lower/release pose even for a FINAL root')
                    else:self.assertNotIn(interval_key(rows[1]),phases)
                finally:source.doCleanups()


class CandidateQueryTests(unittest.TestCase):
    """The optimization fence must preserve exclusions and conservative rows."""
    def setUp(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE support ('+','.join('id INTEGER PRIMARY KEY' if name=='id' else name for name in FIELDS)+')')
        db.execute('CREATE TABLE temporal_support (bin,record,scope,PRIMARY KEY(bin,record))')
        db.execute('CREATE TABLE scope_link (scope,link,PRIMARY KEY(scope,link))')
        db.executemany('INSERT INTO scope_link VALUES (?,?)',[(1,'road'),(2,'far'),(3,'mystery')])
        rows={
            1:dict(), 2:dict(corridor='B',ordinal=2,link='foreign',hold=5),
            3:dict(corridor='B',ordinal=9,link='foreign',hold=5),
            4:dict(corridor='B',ordinal=9,link='remote',transfer_corridor='A',transfer_slot=0,transfer_ordinal=2),
            5:dict(ordinal=None,link='remote'),6:dict(corridor='B',ordinal=9,link='remote',transfer_known=0),
            7:dict(link='far'),8:dict(end=120),9:dict(start=120,end=121),
            10:dict(start=120,end=120),11:dict(corridor='B',ordinal=9),
            12:dict(link='mystery'),13:dict(start=120,end=240,ordinal=8),
            14:dict(corridor='B',ordinal=7,link='remote',hold=240)}
        for ident,overrides in rows.items():
            row=dict(id=ident,journey='j'+str(ident),vehicle='v'+str(ident),start=0,end=240,
                compressed_bytes=1,decoded_bytes=1,link='road',hold=None,ordinal=1,corridor='A',slot=0,
                transfer_known=1,transfer_corridor=None,transfer_slot=None,transfer_ordinal=None)
            row.update(overrides)
            db.execute('INSERT INTO support VALUES ('+','.join('?' for _ in FIELDS)+')',tuple(row[name] for name in FIELDS))
            scope=2 if row['link']=='far' else 3 if row['link']=='mystery' else 1
            db.executemany('INSERT INTO temporal_support VALUES (?,?,?)',
                [(number,ident,scope) for number in _temporal_bins(row['start'],row['end'])])
        self.index=SupportIndex.__new__(SupportIndex);self.index.connection=db
        self.index.source_links=frozenset(row[0] for row in db.execute('SELECT DISTINCT link FROM support'))
        self.known={'road','far','foreign','remote'}

    def legacy(self,at,limit,role,group=('A',0),order=8):
        # Unfenced SQL independently checks the materialization optimization.
        links=sorted({'road'}|(self.index.source_links-self.known))
        args=[math.floor(at/120),at,at,*links];predicate=''
        if group is not None and order is not None:
            predicate=' AND (ordinal IS NULL'+(' OR transfer_known=0' if role!='base' else '')+' OR (corridor=? AND slot=? AND ordinal<=?)'
            args.extend([*group,order])
            if role!='base':
                predicate+=' OR (transfer_corridor=? AND transfer_slot=? AND transfer_ordinal<?)'
                args.extend([*group,order])
            if role in ('hold','final'):
                predicate+=' OR (hold>=start AND hold<end AND hold<=? AND ordinal<=?)';args.extend([at,order])
            predicate+=')'
        sql='SELECT '+','.join('s.'+name for name in FIELDS)+' FROM temporal_support t JOIN support s ON s.id=t.record '
        sql+='WHERE t.bin=? AND start<=? AND end>? AND EXISTS (SELECT 1 FROM scope_link l WHERE l.scope=t.scope AND l.link IN ('
        sql+=','.join('?' for _ in links)+'))'+predicate+' ORDER BY s.id LIMIT ?'
        return [dict(zip(FIELDS,row)) for row in self.index.connection.execute(sql,(*args,limit))]

    def test_materialized_query_preserves_all_rows_order_and_post_filter_limit(self):
        for at in (0,119.999,120,121,239.999,240):
            for role in ('base','fifo','hold','final'):
                for limit in (0,1,3,100):
                    with self.subTest(at=at,role=role,limit=limit):
                        actual=self.index.candidates(at,{'road'},limit,group=('A',0),order=8,
                            role=role,link='road',known_links=self.known)
                        self.assertEqual(actual,self.legacy(at,limit,role))
        self.assertEqual(self.index.candidates(120,{'road'},100,known_links=self.known),
                         self.legacy(120,100,'hold',None,None))

    def test_time_spatial_precedence_and_unknown_controls_remain_effective(self):
        expected={'base':[1,5,9,12,13],'fifo':[1,4,5,6,9,12,13],
                  'final':[1,2,4,5,6,9,12,13]}
        for role,ids in expected.items():
            with self.subTest(role=role):
                rows=self.index.candidates(120,{'road'},100,group=('A',0),order=8,
                    role=role,link='road',known_links=self.known)
                self.assertEqual([row['id'] for row in rows],ids)
        self.assertEqual(self.index.candidates(240,{'road'},100,known_links=self.known),[])


class BasePhaseDependencyTests(unittest.TestCase):
    def source(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        result=CausalSupportGraphTests();result.setUp();self.addCleanup(result.doCleanups)
        return result

    def test_unknown_transfer_does_not_connect_certified_foreign_base_groups(self):
        source=self.source()
        prior=source.record('foreign','b',0,1,2)
        prior.update(timestamps=[0,0],Motion_Plan=dict(version=1,status='stationary',distance_m=0,phases=[]))
        rows={1:prior,2:source.record('foreign','b',0,20,2,hold=5),
              3:source.record('root','a',0,20,3,hold=10)}
        source.write_source(rows)
        with source.graph('foreign-base') as graph:
            self.assertEqual(graph.scalar(2)['transfer_known'],0)
            base,_=graph.dependencies(3,10,'base')
            final,_=graph.dependencies(3,10,'final')
            self.assertNotIn(2,{row[0] for row in base})
            self.assertIn(2,{row[0] for row in final},'Geometric FINAL still consumes an intersecting earlier HOLD')

    def test_base_keeps_unknown_group_future_hold_and_moving_predecessors(self):
        source=self.source()
        unknown=source.record('unknown','b',0,20,1,hold=5)
        unknown['Native_Occupancy']['policy']='unknown-fixture-policy'
        rows={1:unknown,2:source.record('future','a',0,20,2,hold=15),
              3:source.record('moving','a',0,20,3),4:source.record('root','a',0,20,4,hold=10)}
        source.write_source(rows)
        with source.graph('base-negatives') as graph:
            required,_=graph.dependencies(4,10,'base')
            required=[row[:3] for row in required]
            self.assertIn((1,5,'base'),required)
            self.assertIn((2,15,'base'),required)
            self.assertIn((2,10,'interpolate'),required)
            self.assertIn((3,10,'interpolate'),required)

    def test_base_tied_ordinal_follows_js_utf16_key_order_without_reciprocity(self):
        # JS orders the leading astral surrogate before U+E000; Python code
        # point ordering does the opposite. Both native ordinals are tied.
        source=self.source()
        rows={1:source.record('\U00010000','a',0,20,1,hold=5),
              2:source.record('\ue000','a',0,20,1,hold=5)}
        source.write_source(rows)
        with source.graph('base-tie') as graph:
            first,_=graph.dependencies(1,5,'base')
            second,_=graph.dependencies(2,5,'base')
            self.assertNotIn(2,{row[0] for row in first})
            self.assertIn((1,5,'base'),[row[:3] for row in second])

    def test_graph_expansion_uses_only_verified_scalars_not_native_payloads(self):
        source=self.source()
        rows={1:source.record('\U00010000','a',0,20,1,hold=5),
              2:source.record('\ue000','a',0,20,2,hold=10)}
        source.write_source(rows)
        with source.graph('scalar-only-expansion') as graph:
            for ident,row in rows.items():self.assertEqual(scalar_interval_key(graph.scalar(ident)),interval_key(row))
            graph.root(interval_key(rows[2]),2)
            with patch.object(graph,'record',side_effect=AssertionError('Native payload read during scalar expansion')):
                result=graph.expand()
            self.assertEqual(result['source_payload_reads'],0)
            self.assertGreater(result['expanded_states'],1)

    def test_final_departed_uses_projection_but_forming_fifo_keeps_recursive_transfer(self):
        source=self.source()
        rows={1:source.record('transfer','a',0,5,1),2:source.record('transfer','b',5,20,10),
              3:source.record('forming','a',2,20,2,hold=15),4:source.record('root','a',3,20,3,hold=10)}
        source.write_source(rows)
        stage=json.dumps([3,interval_key(rows[4])],separators=(',',':'))
        with source.graph('final-project') as graph:
            final,_=graph.dependencies(4,10,'final')
            forming,_=graph.dependencies(3,10,'fifo:'+stage)
            self.assertIn((2,10,'project:'+stage),[row[:3] for row in final])
            self.assertNotIn((2,10,'fifo:'+stage),[row[:3] for row in final])
            self.assertIn((3,10,'fifo:'+stage),[row[:3] for row in final])
            self.assertIn((2,10,'fifo:'+stage),[row[:3] for row in forming])

    def test_same_link_alone_does_not_add_fifo_across_verified_slots(self):
        source=self.source()
        source.geometry['links']['a']['num_lanes']=2
        source.geometry['occupancy_corridors']['corridors']['a']['represented_lanes']=2
        rows={1:source.record('parallel-moving','a',0,20,1),2:source.record('parallel-hold','a',0,20,2,hold=5),
              3:source.record('root','a',0,20,3,hold=10)}
        rows[1]['Native_Occupancy']['model_slot']=1;rows[2]['Native_Occupancy']['model_slot']=1
        source.write_source(rows)
        stage=json.dumps([3,interval_key(rows[3])],separators=(',',':'))
        with source.graph('parallel-slot-consumers') as graph:
            final,_=graph.dependencies(3,10,'final')
            fifo,_=graph.dependencies(3,5,'fifo:'+stage)
            self.assertNotIn(1,{row[0] for row in final})
            self.assertIn((2,5,'final'),[row[:3] for row in final],
                'A prior HOLD still participates in the spatial SAT branch across slots')
            self.assertNotIn(1,{row[0] for row in fifo})
            self.assertNotIn(2,{row[0] for row in fifo})


class PostFacilityHoldTests(unittest.TestCase):
    @staticmethod
    def post_service(end='vehicle leaves traffic'):
        return dict(timestamps=[20,22],Motion_Plan=dict(status='stationary',distance_m=0,
            hold_start=None,native_wait_boundary=None,phases=[[20,22,0,0,0]]),
            Boundary_Provenance=dict(start='VehicleDepartsAtFacility',end=end,start_relative=1,end_relative=1))

    def test_native_post_service_hold_is_independent_of_next_event_name(self):
        for end in ('left link','vehicle leaves traffic'):
            with self.subTest(end=end):self.assertEqual(hold_time(self.post_service(end)),20)

    def test_post_service_temporal_candidate_keeps_stationary_and_boundary_controls(self):
        import copy
        for change in ('moving','distance','different_fraction','unlocated_fraction','other_start'):
            row=copy.deepcopy(self.post_service())
            if change=='moving':row['Motion_Plan']['status']='kinematic'
            elif change=='distance':row['Motion_Plan']['distance_m']=.01
            elif change=='different_fraction':row['Boundary_Provenance']['end_relative']=.5
            elif change=='unlocated_fraction':row['Boundary_Provenance'].update(start_relative=None,end_relative=None)
            else:row['Boundary_Provenance']['start']='entered link'
            with self.subTest(change=change):self.assertIsNone(hold_time(row))

    def test_index_and_each_consumer_role_retain_native_post_service_anchor(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        source=CausalSupportGraphTests();source.setUp();self.addCleanup(source.doCleanups)
        post=source.record('post-service','a',20,22,10,f0=1,f1=1)
        post.update(self.post_service())
        rows={1:post,2:source.record('root','a',20,30,20,hold=21)}
        source.write_source(rows)
        after=json.dumps([20,interval_key(rows[2])],separators=(',',':'))
        before=json.dumps([5,interval_key(rows[2])],separators=(',',':'))
        with source.graph('post-service-traffic-exit') as graph:
            self.assertEqual(graph.scalar(1)['hold'],20)
            final,_=graph.dependencies(2,21,'final')
            self.assertIn((1,20,'final'),[row[:3] for row in final])
            self.assertNotIn((1,21,'fifo:'+after),[row[:3] for row in final])
            for role,phase in (('interpolate','base'),('fifo:'+after,'final'),
                               ('project:'+after,'final'),('fifo:'+before,'base'),('project:'+before,'base')):
                with self.subTest(role=role):
                    required,_=graph.dependencies(1,21,role)
                    self.assertIn((1,20,phase),[row[:3] for row in required])
        result=source.resolve(2)
        status=result['by_seed'][interval_key(rows[2])]
        self.assertTrue(status['complete'])
        self.assertEqual(status['support_certificate']['phase_keys'][interval_key(post)],'final')


class OccupancyAbsenceTests(unittest.TestCase):
    def source(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        source=CausalSupportGraphTests();source.setUp();self.addCleanup(source.doCleanups)
        return source

    @staticmethod
    def scope(index,blocking=()):
        return VerifiedFacilitySupport(schema='native-blocking-facility-support-v1',
            identity=index.receipt['contract']['identity'],source_sqlite_sha256=index.receipt['contract']['database_sha256'],
            schedule_sha256='b'*64,reader_sha256='c'*64,blocking_links=list(blocking))

    def test_occupancy_level_rejection_does_not_treat_unknown_as_absent(self):
        import copy
        source=self.source();row=source.record('body','b',0,20,10,hold=10)
        row['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        self.assertIsNone(occupancy_absence(row,source.geometry))
        source.geometry['links']['a']['osm_tags']={'bridge':'yes','layer':'1'}
        self.assertEqual(occupancy_absence(row,source.geometry)['reason'],'native_connection_level_mismatch')
        matching=copy.deepcopy(source.geometry);matching['links']['b']['osm_tags']={'bridge':'yes','layer':'1'}
        self.assertIsNone(occupancy_absence(row,matching),'An independently valid corridor must not be pruned')
        self.assertIsNone(occupancy_absence(row,{}),'Missing metadata is not proof of absence')
        invalid=copy.deepcopy(row);invalid['Native_Occupancy']['model_slot']=2
        self.assertEqual(occupancy_absence(invalid,matching)['reason'],'native_slot_outside_corridor')
        invalid=copy.deepcopy(row);invalid['Native_Occupancy']['corridor_id']='absent'
        self.assertEqual(occupancy_absence(invalid,matching)['reason'],'reserved_corridor_absent')
        floating=copy.deepcopy(row);floating['Native_Occupancy']['ordinal']=10.0
        self.assertIsNone(occupancy_absence(floating,matching),'JS accepts integral numeric ordinals')

    def test_fifo_absence_is_terminal_without_discarding_raw_observation(self):
        source=self.source();rows={1:source.record('unknown','b',0,20,1,hold=10),2:source.record('root','a',0,20,2,hold=12)}
        source.geometry['links']['a']['osm_tags']={'bridge':'yes'}
        rows[1]['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        source.write_source(rows)
        with source.graph('fifo-absence') as graph:
            stage=json.dumps([2,interval_key(rows[2])],separators=(',',':'))
            required,digest=graph.dependencies(1,5,'fifo:'+stage)
            self.assertEqual(required,[])
            self.assertEqual(graph.record(1),rows[1])
            self.assertEqual(graph.context.phase_absence(rows[1],5,'fifo:'+stage)['reason'],'native_occupancy_unavailable')
            self.assertEqual(len(digest),64)
            self.assertIsNone(graph.context.phase_absence(rows[1],10,'final'),'No schedule coverage: retain conditional fallback')

    def test_shared_upstream_anchor_absence_requires_complete_schedule_and_lane_proof(self):
        source=self.source();rows={1:source.record('body','b',0,20,1,hold=10),2:source.record('other','a',0,20,2,hold=12)}
        source.geometry['links']['a']['osm_tags']={'bridge':'yes'}
        source.geometry['links']['b']['native_lanes']={'shared':dict(index=None,to_lanes=['terminal'])}
        rows[1]['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        source.write_source(rows)
        event=dict(type='entered lane',time=0,vehicle='body',link='b',lane='shared')
        with closing(sqlite3.connect(source.database)) as db,db:
            db.execute('INSERT INTO lane_events VALUES(1,?,?,?)',('body',0,packed(event)))
        source.source_sha=hashlib.sha256(source.database.read_bytes()).hexdigest()
        with source.graph('anchor-absence') as graph:
            context=graph.context
            self.assertIsNone(context.phase_absence(rows[1],10,'final'))
            context.facility_support=self.scope(graph.index)
            proof=context.phase_absence(rows[1],10,'final')
            self.assertEqual(proof['reason'],'shared_upstream_without_blocking_facility')
            self.assertEqual(graph.dependencies(1,10,'final')[0],[])
            context.facility_support=self.scope(graph.index,['b'])
            self.assertIsNone(context.phase_absence(rows[1],10,'final'))
            context.facility_support=self.scope(graph.index)
            with patch.object(context,'lane',return_value=dict(event=None)):
                self.assertIsNone(context.phase_absence(rows[1],10,'final'))
            self.assertIsNone(context.phase_absence(rows[1],9,'final'))

    def test_facility_authority_rejects_plain_json_and_changes_cache_namespace(self):
        source=self.source();source.write_source({1:source.record('body','a',0,20,1,hold=10)})
        with source.graph('facility-authority') as graph:
            proof=self.scope(graph.index)
            identity=graph.index.receipt['contract']['identity'];sha=source.source_sha
            self.assertEqual(validate_facility_support(proof,identity,sha),proof)
            with self.assertRaises(ValueError):validate_facility_support(dict(proof),identity,sha)
            with self.assertRaises(ValueError):validate_facility_support(proof,{**identity,'iteration':1},sha)
            with self.assertRaises(ValueError):validate_facility_support(proof,identity,'d'*64)
            options=dict(validate_segment=ContinuousReplay.validate_native_segment,validate_trip=lambda x:None,
                domains=queue_domains(source.geometry),visual_lanes=source.geometry,support_index=graph.index)
            one=QueueContext(graph.context.connection,source.blocks,facility_support=proof,**options)
            two=QueueContext(graph.context.connection,source.blocks,facility_support=self.scope(graph.index,['a']),**options)
            self.assertNotEqual(one.cache_namespace,two.cache_namespace)


class RendererConsumerClassificationTests(unittest.TestCase):
    def test_moving_without_occupancy_is_excluded_only_from_anchor_constraints(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        from simz1_queue_checkpoints import CausalGraph
        from simz1_queue_checkpoint import CheckpointKernel,kernel_contract
        source=CausalSupportGraphTests();source.setUp();self.addCleanup(source.doCleanups)
        source.geometry['links']['a']['osm_tags']={'bridge':'yes'}
        source.geometry['links']['b'].update(length_m=100,native_lanes={
            'terminal':dict(index=0,to_lanes=[],start_m=100,represented_lanes=1)})
        rows={1:source.record('moving','b',0,20,158573),
              2:source.record('root','b',0,20,100,hold=10)}
        rows[1]['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        source.write_source(rows)
        event=dict(type='entered lane',time=0,vehicle='moving',link='b',lane='terminal')
        with closing(sqlite3.connect(source.database)) as db,db:
            db.execute('INSERT INTO lane_events VALUES(?,?,?,?)',(1,'moving',0,packed(event)))
        source.source_sha=hashlib.sha256(source.database.read_bytes()).hexdigest()
        with source.graph('moving-unclassified') as before:
            self.assertIn(1,{row[0] for row in before.dependencies(2,10,'base')[0]})
            scope=OccupancyAbsenceTests.scope(before.index,['b'])
            settings=dict(gap_m=.1,lateral_clearance_m=.1,stop_line_setback_m=2)
            pinned=kernel_contract(before.index.receipt['contract'],before.index.receipt['sha256'],source.geometry,settings,facility_support=scope)
            with CheckpointKernel(before.index.receipt['contract']['identity'],source.geometry,settings,
                    log_path=source.root/'moving-classifier.stderr.log',facility_support=scope,source_sqlite_sha256=source.source_sha) as kernel:
                context=QueueContext(before.context.connection,source.blocks,
                    validate_segment=ContinuousReplay.validate_native_segment,validate_trip=lambda x:None,
                    visual_lanes=source.geometry,domains=queue_domains(source.geometry),support_index=before.index,
                    facility_support=scope,phase_classifier=kernel,classifier_contract=pinned)
                with closing(CausalGraph(source.root/'moving-classified.sqlite',context,storage=before.storage)) as graph:
                    effective=graph.consumer(graph.scalar(1))
                    self.assertIsNotNone(effective)
                    self.assertEqual(effective['scope'],'anchor_constraints_only')
                    self.assertFalse(effective['represented'])
                    self.assertEqual(effective['proof']['classification']['reason'],'inactive_context_without_occupancy_or_hold')
                    for role in ('base','final','fifo:'+json.dumps([100,interval_key(rows[2])],separators=(',',':'))):
                        self.assertNotIn(1,{row[0] for row in graph.dependencies(2,10,role)[0]})
                    self.assertEqual(graph.record(1),rows[1],'Observation remains intact for active rendering and geometry')
                    for changes in (dict(complete=False),dict(reason='missing_geometry'),
                                    dict(reason='shared_upstream_without_blocking_facility'),dict(eligible=True),
                                    dict(departure_complete=False),dict(hold=5)):
                        context.classification_cache.clear();context.classification_bytes=0
                        uncertain={**effective['proof']['classification'],**changes}
                        with patch.object(kernel,'classify',return_value=dict(states=[dict(key=interval_key(rows[1]),epoch=0,classification=uncertain)])):
                            self.assertIsNone(context.classify_consumer(1,rows[1]))
                    held=source.record('moving','b',0,20,158573,hold=10)
                    held['Native_Occupancy']=rows[1]['Native_Occupancy']
                    context.classification_cache.clear();context.classification_bytes=0
                    with patch.object(kernel,'classify',return_value=dict(states=[dict(key=interval_key(held),epoch=10,
                            classification=effective['proof']['classification'])])):
                        self.assertIsNone(context.classify_consumer(1,held),'A real HOLD may constrain anchors')
                    supported={**rows[1],'Native_Occupancy':dict(policy='corridor-length-v1',corridor_id='b',model_slot=0,ordinal=158573)}
                    with patch.object(kernel,'classify',side_effect=AssertionError('Valid occupancy remains a native constraint')):
                        self.assertIsNone(context.classify_consumer(1,supported))

    def test_terminal_change_before_own_hold_uses_visual_order_without_native_fifo(self):
        from test_simz1_causal_support_graph import CausalSupportGraphTests
        from simz1_queue_checkpoints import CausalGraph
        from simz1_queue_checkpoint import CheckpointKernel,kernel_contract
        source=CausalSupportGraphTests();source.setUp();self.addCleanup(source.doCleanups)
        source.geometry['links']['a']['osm_tags']={'bridge':'yes'}
        source.geometry['links']['b'].update(length_m=100,native_lanes={
            'original':dict(index=None,to_lanes=['terminal'],start_m=100,represented_lanes=1),
            'terminal':dict(index=0,to_lanes=[],start_m=90,represented_lanes=1)})
        rows={1:source.record('fallback','b',0,20,158573,hold=10),
              2:source.record('native-later','a',0,20,100,hold=8)}
        rows[1]['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        source.write_source(rows)
        events=[dict(type='entered lane',time=0,vehicle='fallback',link='b',lane='original'),
                dict(type='entered lane',time=7,vehicle='fallback',link='b',lane='terminal')]
        with closing(sqlite3.connect(source.database)) as db,db:
            for seq,event in enumerate(events,1):db.execute('INSERT INTO lane_events VALUES(?,?,?,?)',(seq,event['vehicle'],event['time'],packed(event)))
        source.source_sha=hashlib.sha256(source.database.read_bytes()).hexdigest()
        with source.graph('unclassified-reference') as before:
            self.assertIn(2,{row[0] for row in before.dependencies(1,10,'final')[0]})
            scope=OccupancyAbsenceTests.scope(before.index)
            settings=dict(gap_m=.1,lateral_clearance_m=.1,stop_line_setback_m=2)
            pinned=kernel_contract(before.index.receipt['contract'],before.index.receipt['sha256'],source.geometry,settings,facility_support=scope)
            with CheckpointKernel(before.index.receipt['contract']['identity'],source.geometry,settings,
                    log_path=source.root/'classifier.stderr.log',facility_support=scope,source_sqlite_sha256=source.source_sha) as kernel:
                context=QueueContext(before.context.connection,source.blocks,
                    validate_segment=ContinuousReplay.validate_native_segment,validate_trip=lambda x:None,
                    visual_lanes=source.geometry,domains=queue_domains(source.geometry),support_index=before.index,
                    facility_support=scope,phase_classifier=kernel,classifier_contract=pinned)
                with closing(CausalGraph(source.root/'classified.sqlite',context,storage=before.storage)) as graph:
                    effective=graph.consumer(graph.scalar(1))
                    self.assertEqual(effective['visual_order'],7)
                    self.assertEqual(effective['visual_group'],('b',0))
                    self.assertFalse(effective['occupancy'])
                    self.assertEqual(rows[1]['Native_Occupancy']['ordinal'],158573)
                    self.assertIsNone(graph.scalar(1)['ordinal'])
                    final,_=graph.dependencies(1,10,'final')
                    self.assertNotIn(2,{row[0] for row in final},'Later native HOLD is not an earlier fallback visual anchor')
                    self.assertIn((1,10,'base'),[row[:3] for row in final])
                    self.assertIsNone(context.phase_absence(rows[1],10,'final'),'Terminal at HOLD refutes stale entry-lane absence')
                    calls=kernel.classification_calls
                    self.assertEqual(graph.consumer(graph.scalar(1)),effective)
                    self.assertEqual(kernel.classification_calls,calls,'Bounded cache uses exact immutable source and HOLD coverage')
                    proof=effective['proof']
                    self.assertTrue(any(row['epoch']==10 and row['inclusive'] for row in proof['lane_coverage']))
                    # An inactive/partial packet's absence or eligibility
                    # failure is not a universal dependency exclusion.
                    for changes in (dict(represented=False),dict(eligible=False),dict(native_entry=False)):
                        context.classification_cache.clear();context.classification_bytes=0
                        uncertain={**proof['classification'],**changes}
                        with patch.object(kernel,'classify',return_value=dict(states=[dict(key=interval_key(rows[1]),epoch=10,classification=uncertain)])):
                            self.assertIsNone(context.classify_consumer(1,rows[1]))
                    context.classification_cache.clear();context.classification_bytes=0
                    self.assertEqual(context.classify_consumer(1,rows[1])['visual_order'],7)
                    no_epoch={**rows[1],'Motion_Plan':dict(status='unavailable',phases=[],distance_m=100),'Native_Occupancy':dict(policy='unsupported')}
                    with patch.object(kernel,'classify',side_effect=AssertionError('Unknown queueHoldTime is not a classification epoch')):
                        self.assertIsNone(context.classify_consumer(1,no_epoch))


class RejectedPacketEvidenceTests(unittest.TestCase):
    def setUp(self):
        from simz1_queue_checkpoints import CausalGraph
        self.temp=tempfile.TemporaryDirectory(prefix='simz1-rejected-packet-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.graph=CausalGraph.__new__(CausalGraph)
        self.graph.path=Path(self.temp.name)/'library.sqlite'
        self.graph.path.write_bytes(b'preserved-graph-fixture')
        self.graph.max_disk_bytes=1024*1024
        self.graph.storage=AuxiliaryStorageScope(self.graph.path.parent,self.graph.max_disk_bytes)
        self.graph.storage.__enter__();self.addCleanup(self.graph.storage.close)
        self.graph.contract=dict(sources={'simz1_queue_checkpoints.py':hashlib.sha256(
            (Path(__file__).parent/'simz1_queue_checkpoints.py').read_bytes()).hexdigest()})
        self.packet=dict(records=[dict(vehicle='moving',Replay_Journey_Key='journey',Link_ID='road',timestamps=[0,20],
            Trip=dict(Person_ID='person',Departure=0))],requests=[dict(key='fixture-key',role='interpolate',epoch=10,stage=None)],
            phases={},checkpoints={},lane_events=[])

    def test_lossless_bounded_packet_is_exclusive_and_keeps_source_snapshot(self):
        before=self.graph.path.read_bytes()
        self.graph.capture_rejected_packet(self.packet,2,[7,8],{'fixture':'kernel'},ValueError('original rejection'))
        result=self.graph.last_rejection_diagnostic
        self.assertEqual(result['status'],'packet')
        with gzip.open(result['path'],'rt',encoding='utf8') as handle:value=json.load(handle)
        self.assertFalse(value['accepted']);self.assertEqual(value['generation'],2)
        self.assertEqual(value['requests'],self.packet['requests'])
        restored=[{**row,'Trip':value['packet']['trips'][row['Replay_Journey_Key']]} for row in value['packet']['records']]
        self.assertEqual(restored,self.packet['records'])
        self.assertEqual(value['source_snapshot'],self.graph.contract['sources'])
        self.assertEqual(value['exception']['message'],'original rejection')
        self.graph.capture_rejected_packet(self.packet,2,[7,8],{'fixture':'kernel'},ValueError('second rejection'))
        self.assertNotEqual(self.graph.last_rejection_diagnostic['path'],result['path'])
        self.assertEqual(self.graph.path.read_bytes(),before)
        self.assertFalse(list(self.graph.path.parent.glob('*.tmp')))

    def test_disk_budget_uses_metadata_fallback_and_never_masks_io_failure(self):
        self.packet['records'][0]['uncompressible_fixture']=''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(500))
        self.graph.max_disk_bytes=self.graph.path.stat().st_size+2048
        self.graph.storage.max_disk_bytes=self.graph.max_disk_bytes
        self.graph.capture_rejected_packet(self.packet,0,[1],{},ValueError('rejection'))
        result=self.graph.last_rejection_diagnostic
        self.assertEqual(result['status'],'metadata')
        with gzip.open(result['path'],'rt',encoding='utf8') as handle:value=json.load(handle)
        self.assertIsNone(value['packet']);self.assertEqual(value['requests'],self.packet['requests'])
        self.assertLessEqual(sum(p.stat().st_size for p in self.graph.path.parent.iterdir()),self.graph.max_disk_bytes)
        with patch.object(Path,'open',side_effect=PermissionError('fixture no write')):
            self.graph.capture_rejected_packet(self.packet,0,[1],{},ValueError('still original'))
        self.assertEqual(self.graph.last_rejection_diagnostic['status'],'not_written')
        self.assertFalse(list(self.graph.path.parent.glob('*.tmp')))

    def test_original_component_guards_prevent_diagnostic_expansion(self):
        self.packet['records']*=513
        self.graph.capture_rejected_packet(self.packet,0,[1],{},ValueError('rejection'))
        self.assertEqual(self.graph.last_rejection_diagnostic['status'],'not_written')
        self.assertFalse(list(self.graph.path.parent.glob('*.gz')))
        self.packet['records']=self.packet['records'][:1]
        with patch('simz1_queue_checkpoint.compact_component_packet',return_value=(self.packet,64*1024**2+1)):
            self.graph.capture_rejected_packet(self.packet,0,[1],{},ValueError('rejection'))
        self.assertEqual(self.graph.last_rejection_diagnostic['status'],'not_written')
        self.assertFalse(list(self.graph.path.parent.glob('*.gz')))


class AuxiliaryStorageScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='simz1-storage-scope-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    @staticmethod
    def temporary_setting():
        with closing(sqlite3.connect(':memory:')) as db:
            row=db.execute('PRAGMA temp_store_directory').fetchone()
            return row[0] if row else ''

    def test_real_rollback_journal_is_rejected_before_commit(self):
        path=self.root/'owned'/'library.sqlite';path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA cache_size=-128')
            db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,payload BLOB)')
            db.executemany('INSERT INTO sample VALUES (?,?)',((i,b'A'*1024) for i in range(400)));db.commit()
            before=hashlib.sha256(path.read_bytes()).hexdigest();main=path.stat().st_size
            prior=self.temporary_setting();scope=AuxiliaryStorageScope(path.parent,main+32768)
            with self.assertRaisesRegex(AuxiliaryStorageExceeded,'before'):
                with scope:
                    scope.attach(db);db.execute('UPDATE sample SET payload=?',(b'B'*1024,))
                    self.assertLess(path.stat().st_size,scope.max_disk_bytes)
                    self.assertGreater(sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file()),scope.max_disk_bytes)
                    scope.commit(db,'journal_transaction')
            self.assertTrue(db.in_transaction,'A rejected pre-commit guard must not commit the changed fixture')
            db.rollback();self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            self.assertGreater(scope.report()['peak_observed_bytes'],scope.max_disk_bytes)
            self.assertEqual(self.temporary_setting(),prior)

    def test_file_temporaries_and_fixed_index_are_counted_and_restored(self):
        fixed=self.root/'immutable-index.sqlite';fixed.write_bytes(b'index'*128)
        directory=self.root/'owned';prior=self.temporary_setting()
        with AuxiliaryStorageScope(directory,4*1024**2,fixed_paths=(fixed,)) as scope:
            with closing(sqlite3.connect(directory/'library.sqlite')) as db:
                scope.attach(db)
                self.assertEqual(db.execute('PRAGMA temp_store').fetchone(),(1,))
                self.assertEqual(Path(self.temporary_setting()),scope.temp_directory)
                db.execute('PRAGMA temp.cache_size=-128')
                db.execute('CREATE TEMP TABLE scratch(id INTEGER PRIMARY KEY,payload BLOB)')
                db.executemany('INSERT INTO scratch VALUES (?,?)',((i,b'C'*1024) for i in range(768)))
                actual=sum(path.stat().st_size for path in directory.rglob('*') if path.is_file())+fixed.stat().st_size
                self.assertTrue(list(scope.temp_directory.iterdir()),'Real FILE temporaries must be observable in the owned directory')
                report=scope.check('temporary_fixture')
                self.assertEqual(report['observed_bytes'],actual)
                scope.commit(db,'temporary_commit')
                scope.detach(db)
        self.assertEqual(self.temporary_setting(),prior)
        self.assertGreater(scope.report()['peak_observed_bytes'],fixed.stat().st_size)
        self.assertEqual(scope.report()['observation_scope'],'explicit_boundaries_and_periodic_sql_callbacks_not_os_quota')

    def test_periodic_sql_callback_stops_after_observed_overrun(self):
        with closing(sqlite3.connect(':memory:')) as db:
            scope=AuxiliaryStorageScope(self.root/'owned',8192,progress_steps=10,poll_seconds=0)
            with self.assertRaises(AuxiliaryStorageExceeded):
                with scope:
                    scope.attach(db)
                    (scope.root/'unexpected-growth.bin').write_bytes(b'x'*8193)
                    with self.assertRaisesRegex(sqlite3.OperationalError,'interrupted'):
                        db.execute('WITH RECURSIVE sequence(n) AS (VALUES(0) UNION ALL SELECT n+1 FROM sequence WHERE n<10000) SELECT sum(n) FROM sequence').fetchone()
                    scope.raise_if_failed()
            self.assertEqual(scope.report()['last_stage'],'sqlite_progress')
            self.assertTrue(scope.report()['breached'])

    def test_fixed_file_mutation_and_nested_scope_are_rejected(self):
        fixed=self.root/'fixed.sqlite';fixed.write_bytes(b'unchanged')
        prior=self.temporary_setting()
        with self.assertRaisesRegex(ValueError,'identity or bytes changed'):
            with AuxiliaryStorageScope(self.root/'owned',1024*1024,fixed_paths=(fixed,)) as scope:
                with self.assertRaisesRegex(ValueError,'Another auxiliary'):
                    with AuxiliaryStorageScope(self.root/'other',1024*1024):pass
                fixed.write_bytes(b'changed source')
                scope.check('mutation')
        self.assertEqual(self.temporary_setting(),prior)

    def test_failed_scope_entry_restores_existing_process_temporary_setting(self):
        original=self.temporary_setting();previous=self.root/'previous-temp';previous.mkdir()
        directory=self.root/'oversized';directory.mkdir();(directory/'existing.bin').write_bytes(b'12345')
        with closing(sqlite3.connect(':memory:')) as control:
            control.execute("PRAGMA temp_store_directory='"+previous.as_posix().replace("'","''")+"'")
            try:
                with self.assertRaises(AuxiliaryStorageExceeded):
                    with AuxiliaryStorageScope(directory,4):pass
                self.assertEqual(Path(self.temporary_setting()),previous)
                with AuxiliaryStorageScope(self.root/'valid-after-error',4096):pass
                self.assertEqual(Path(self.temporary_setting()),previous)
            finally:control.execute("PRAGMA temp_store_directory='"+original.replace("'","''")+"'")

    def test_failed_read_of_previous_setting_does_not_reset_process_state(self):
        class UnreadableControl:
            def __init__(self):self.statements=[];self.closed=False
            def execute(self,statement):
                self.statements.append(statement)
                raise sqlite3.OperationalError('synthetic prior-setting read failure')
            def close(self):self.closed=True
        prior=self.temporary_setting();control=UnreadableControl()
        scope=AuxiliaryStorageScope(self.root/'unreadable-prior',4096)
        with patch('simz1_queue_support.sqlite3.connect',return_value=control):
            with self.assertRaisesRegex(sqlite3.OperationalError,'prior-setting read failure'):
                with scope:pass
        self.assertEqual(control.statements,['PRAGMA temp_store_directory'])
        self.assertTrue(control.closed);self.assertFalse(scope.active)
        self.assertEqual(self.temporary_setting(),prior)
        with AuxiliaryStorageScope(self.root/'valid-after-prior-read-error',4096):pass

    def test_own_root_identity_and_indirect_paths_are_rejected(self):
        scope=AuxiliaryStorageScope(self.root/'owned',1024*1024)
        with self.assertRaisesRegex(ValueError,'root identity changed'):
            with scope:
                scope.root.rename(self.root/'original-owned')
                scope.root.mkdir()
                scope.check('replaced_root')
        with patch.object(AuxiliaryStorageScope,'_indirect',return_value=True):
            with self.assertRaisesRegex(ValueError,'cannot be indirect'):
                AuxiliaryStorageScope(self.root,1024*1024)


if __name__=='__main__':unittest.main()
