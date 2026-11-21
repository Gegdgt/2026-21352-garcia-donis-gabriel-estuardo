"""Small causal-graph counterexamples; synthetic SQLite only, never native runs."""
from contextlib import closing, contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from simz1_continuous_replay import ContinuousReplay, connect
from simz1_paged_replay import packed
from simz1_queue_context import QueueContext, Limits, dependency_components, interval_key, queue_domains
from simz1_queue_support import SupportIndex, contract
from simz1_queue_checkpoints import CausalGraph, checkpoint_digest, decode_result_payload, encode_result_payload
from simz1_queue_checkpoint import kernel_contract


class CausalSupportGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1-causal-graph-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root/'synthetic.sqlite'
        self.blocks = [dict(index=0,start_seconds=0,end_seconds=40)]
        self.geometry = dict(schema_version=1,available=True,links={
            'a':self.link('left','join',[[0,0],[.001,0]],['b']),
            'b':self.link('join','right',[[.001,0],[.002,0]],[])},
            occupancy_corridors=dict(schema='corridor-length-v1',corridors={
                name:dict(link_ids=[name],represented_lanes=1) for name in ('a','b')}))

    @staticmethod
    def link(start,end,path,targets):
        return dict(from_node=start,to_node=end,path=path,num_lanes=1,opposing_lanes=0,
                    lane_width_m=3.5,native_lanes={},allowed_to_links=targets,osm_tags={})

    def record(self,vehicle,link,start,end,ordinal,*,hold=None,f0=0,f1=1):
        path=self.geometry['links'][link]['path']
        point=lambda f:[path[0][i]+f*(path[-1][i]-path[0][i]) for i in (0,1)]
        distance=self.geometry['links'][link].get('length_m',100)*(f1-f0);stop=end if hold is None else hold
        phases=[[start,stop,0,distance/(stop-start),0]]
        if hold is not None:phases.append([hold,end,distance,0,0])
        return dict(vehicle=vehicle,Agent_ID=vehicle+'-person',Replay_Journey_Key=vehicle+'-journey',
            Link_ID=link,timestamps=[start,end],path=[point(f0),point(f1)],
            Vehicle_Dimensions=dict(length_m=13.5,width_m=2.5,source='synthetic_fixture',assumed=True),
            Native_Occupancy=dict(policy='corridor-length-v1',corridor_id=link,model_slot=0,ordinal=ordinal),
            Boundary_Provenance=dict(start='entered link',end='left link',start_relative=f0,end_relative=f1),
            Motion_Plan=dict(version=1,status='kinematic',distance_m=distance,phases=phases,
                             **({} if hold is None else dict(hold_start=hold,native_wait_boundary=hold))),
            Observed_Waits={} if hold is None else dict(storage_wait=dict(first=hold,last=end-1,
                position_evidence='queue_exit',sources=['MATSim15_QNode_native_branch'])))

    def write_source(self,rows):
        self.rows=rows
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('''CREATE TABLE segments(id INTEGER PRIMARY KEY,journey TEXT,vehicle TEXT,start REAL,end REAL,payload BLOB);
                CREATE INDEX segments_journey ON segments(journey,id);
                CREATE TABLE segment_blocks(block INTEGER,segment INTEGER);
                CREATE INDEX segments_block ON segment_blocks(block,segment);
                CREATE TABLE journeys(key TEXT PRIMARY KEY,metadata TEXT);
                CREATE TABLE lane_events(seq INTEGER PRIMARY KEY,vehicle TEXT,time REAL,payload BLOB);
                CREATE INDEX lanes_vehicle_time ON lane_events(vehicle,time,seq);''')
            for ident,row in sorted(rows.items()):
                db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',
                    (ident,row['Replay_Journey_Key'],row['vehicle'],*row['timestamps'],packed(row)))
                db.execute('INSERT INTO segment_blocks VALUES(0,?)',(ident,))
                trip=dict(Person_ID=row['Agent_ID'],Trip_ID=row['Agent_ID']+':trip:0001',
                          Departure=0,Arrival=40,Status='completed')
                db.execute('INSERT OR IGNORE INTO journeys VALUES(?,?)',
                    (row['Replay_Journey_Key'],json.dumps(trip)))
        self.source_sha=hashlib.sha256(self.database.read_bytes()).hexdigest()

    def resolve(self,seed,limits=None):
        expected=contract(self.database,dict(run_id='synthetic-causal-graph',iteration=0,
            run_manifest_sha256='a'*64),self.source_sha,self.geometry)
        with closing(connect(self.database)) as source, closing(SupportIndex.prepare(self.root/'support',source,expected,
                validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry)) as index:
            resolver=QueueContext(source,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
                validate_trip=lambda trip:None,domains=queue_domains(self.geometry),visual_lanes=self.geometry,
                support_index=index,limits=limits)
            result=resolver.resolve([(seed,self.rows[seed])])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),self.source_sha)
        return result

    @contextmanager
    def graph(self,name):
        expected=contract(self.database,dict(run_id='synthetic-causal-graph',iteration=0,
            run_manifest_sha256='a'*64),self.source_sha,self.geometry)
        with closing(connect(self.database)) as source, closing(SupportIndex.prepare(self.root/'support',source,expected,
                validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry)) as index:
            context=QueueContext(source,self.blocks,validate_segment=ContinuousReplay.validate_native_segment,
                validate_trip=lambda trip:None,domains=queue_domains(self.geometry),visual_lanes=self.geometry,
                support_index=index)
            with closing(CausalGraph(self.root/(name+'.sqlite'),context)) as graph:
                yield graph

    @staticmethod
    def retained(result):
        return {interval_key(row):row for kind in ('segments','transition_segments') for row in result[kind]}

    def test_transfer_through_three_moving_fragments_keeps_entire_observed_chain(self):
        # B3's old reservation belongs to A, but the renderer must walk B2/B1
        # before reaching A. A scalar transfer label cannot replace those rows.
        rows={1:self.record('leader','a',0,5,1),
              2:self.record('leader','b',5,7,10,f1=.2),
              3:self.record('leader','b',7,9,10,f0=.2,f1=.4),
              4:self.record('leader','b',9,30,10,f0=.4),
              5:self.record('root','a',8,30,2,hold=10)}
        self.write_source(rows)
        result=self.resolve(5)
        self.assertTrue(result['by_seed'][interval_key(rows[5])]['complete'])
        retained=self.retained(result)
        for ident in (1,2,3,4,5):
            self.assertEqual(retained.get(interval_key(rows[ident])),rows[ident],
                'Every observed transition to the old reservation must be delivered, including '+str(ident))
        self.assertEqual(result['by_seed'],self.resolve(5)['by_seed'])

    def test_required_transferred_leader_keeps_its_new_corridor_fifo_at_same_epoch(self):
        rows={1:self.record('transfer','a',0,10,1,hold=5),
              2:self.record('transfer','b',10,20,100),
              3:self.record('foreign-moving','b',9,30,50),
              4:self.record('forming','a',8,30,2,hold=15,f0=.95),
              5:self.record('root','a',9,30,3,hold=10)}
        self.write_source(rows)
        result=self.resolve(5)
        status=result['by_seed'][interval_key(rows[5])]
        self.assertTrue(status['complete'])
        retained=self.retained(result)
        self.assertEqual(retained[interval_key(rows[3])],rows[3],
                         'The moving body in B constrains transfer at root HOLD even though it never occupied A')
        self.assertIn(interval_key(rows[4]),status['record_keys'],
                      'A forming predecessor keeps its future HOLD as a distinct dependency')
        self.assertIn(interval_key(rows[1]),status['record_keys'])
        limited=self.resolve(5,replace(Limits(),max_records=2))
        self.assertFalse(limited['by_seed'][interval_key(rows[5])]['complete'])
        self.assertEqual(limited['segments'],[])
        self.assertEqual(limited['transition_segments'],[])

    def test_long_body_on_two_metre_terminal_keeps_multiple_prior_domains(self):
        # A 13.5 m rigid body cannot be backed by the 2 m terminal plus one
        # 2 m predecessor. Keep the observed 2+2+2 m chain to its long support.
        metres_per_degree=6371008.8*3.141592653589793/180
        def road(name,start,end,x0,x1,next_link):
            return dict(self.link(start,end,[[x0/metres_per_degree,0],[x1/metres_per_degree,0]],next_link),
                        length_m=x1-x0)
        self.geometry['links']={
            'upstream':road('upstream','n0','n1',0,100,['b']),
            'b':road('b','n1','n2',100,102,['c']),
            'c':road('c','n2','n3',102,104,['a']),
            'a':road('a','n3','n4',104,106,[])}
        self.geometry['occupancy_corridors']['corridors']={
            name:dict(link_ids=[name],represented_lanes=1) for name in self.geometry['links']}
        rows={1:self.record('bus','upstream',0,5,1),2:self.record('bus','b',5,7,2),
              3:self.record('bus','c',7,9,3),4:self.record('bus','a',9,30,4,hold=10)}
        self.write_source(rows)
        result=self.resolve(4)
        self.assertTrue(result['by_seed'][interval_key(rows[4])]['complete'])
        self.assertEqual(set(self.retained(result)),{interval_key(row) for row in rows.values()},
            'A complete context must carry enough observed links for the full 13.5 m body')

    def test_reciprocal_transfer_candidates_preserve_actual_renderer_stage_order(self):
        # A directed two-link loop supplies two reciprocal old-domain rears.
        # This is a synthetic dependency fixture, not native traffic evidence.
        self.geometry['links']['b']=self.link('join','left',[[.001,0],[0,0]],['a'])
        rows={1:self.record('A','b',0,5,1),2:self.record('A','a',5,30,100,hold=10),
              3:self.record('B','a',0,5,2),4:self.record('B','b',5,30,101,hold=10)}
        self.write_source(rows)
        forward=self.resolve(2);reverse=self.resolve(4)
        for seed,result in ((2,forward),(4,reverse)):
            status=result['by_seed'][interval_key(rows[seed])]
            self.assertTrue(status['complete'])
            self.assertEqual(set(self.retained(result)),{interval_key(row) for row in rows.values()})
            proof=status['support_certificate']
            self.assertFalse(proof['poses_certified'],'Closing graph evidence cannot certify a cyclic pose')
            # The final pass processes reservation 100 before 101. A's final
            # anchor therefore uses B's BASE anchor; B's final uses A's FINAL
            # anchor. These reciprocal candidates are a DAG of actual stages,
            # not a cycle that can be broken by discarding one candidate.
            expected={interval_key(rows[2]):'final',
                      interval_key(rows[4]):'base' if seed==2 else 'final'}
            self.assertEqual(proof['phase_keys'],expected)
            self.assertEqual(proof['components']['cyclic'],[])
        first=forward['by_seed'][interval_key(rows[2])]['support_certificate']
        second=reverse['by_seed'][interval_key(rows[4])]['support_certificate']
        self.assertNotEqual(first['graph_sha256'],second['graph_sha256'])
        self.assertGreater(second['states'],first['states'])

    def test_strong_components_keep_reciprocal_epochs_and_self_edges(self):
        a=(1,10,'final');b=(2,10,'fifo:100');c=(3,10,'base')
        later=(1,20,'final');isolated=(4,10,'base')
        nodes=[a,b,c,later,isolated]
        edges=[(a,b),(b,c),(c,a),(c,later),(later,later)]
        forward=dependency_components(nodes,edges)
        reverse=dependency_components(list(reversed(nodes)),list(reversed(edges)))
        expected={frozenset((a,b,c)),frozenset((later,))}
        for result in (forward,reverse):
            self.assertEqual({frozenset(map(tuple,component)) for component in result['cyclic']},expected)
            self.assertEqual(result['count'],3)
            self.assertEqual(result['maximum_size'],3)
        self.assertEqual(forward['partition_sha256'],reverse['partition_sha256'])

    def test_source_connection_cannot_claim_another_database_identity(self):
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        foreign=self.root/'other-source.sqlite'
        shutil.copyfile(self.database,foreign)
        with closing(sqlite3.connect(foreign)) as db, db:
            db.execute('DELETE FROM segments')
        expected=contract(self.database,dict(run_id='synthetic-causal-graph',iteration=0,
            run_manifest_sha256='a'*64),self.source_sha,self.geometry)
        with closing(connect(foreign)) as wrong_source:
            with self.assertRaisesRegex(ValueError,'[Ss]ource.*(connection|database|identity)'):
                with closing(SupportIndex.prepare(self.root/'support',wrong_source,expected,
                        validate_segment=ContinuousReplay.validate_native_segment,visual_lanes=self.geometry)):
                    pass
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),self.source_sha)

    def test_persisted_graph_cannot_publish_components_before_candidate_closure(self):
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        for method in ('components','ready_components'):
            with self.subTest(method=method),self.graph('premature-'+method) as graph:
                graph.root('root',1)
                with self.assertRaisesRegex(ValueError,'(complete|expanded|closure|expansion)'):
                    result=getattr(graph,method)()
                    if method=='ready_components':list(result)

    def test_persisted_graph_classifies_self_dependency_as_cyclic_component(self):
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        with self.graph('self-cycle') as graph:
            graph.root('root',1)
            # Test the persisted SCC algorithm independently of the geometric
            # evaluator. A deliberate self dependency must remain explicit.
            with patch.object(graph,'dependencies',side_effect=lambda ident,epoch,role: ([(ident,epoch,role)],'f'*64)):
                graph.expand()
            summary=graph.components()
            self.assertEqual(summary['count'],1)
            self.assertEqual(summary['maximum_records'],1)
            self.assertEqual(summary['cyclic_components'],1)
            self.assertEqual(graph.db.execute('SELECT count(*) FROM edge WHERE source=target').fetchone(),(1,))

    def test_evaluated_child_rehash_cannot_change_native_identity(self):
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        class ContractOnlyKernel:
            # No geometric claim: this deterministic stub isolates trust in
            # persisted child envelopes from the renderer's separate tests.
            calls=0;max_request_bytes=0
            def solve(self,packet):
                self.calls+=1
                return dict(states=[dict(request,result=dict(available=True,anchor_m=1,
                    within_storage=True,pose=None,pose_available=False,turn_bounds=[]),
                    input='{}',prepared='{}',release=None,release_recipe=None)
                    for request in packet['requests']])
        with self.graph('tampered-child') as graph:
            graph.root('root',1);graph.expand();graph.components()
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],self.geometry,{})
            outcome=graph.evaluate(ContractOnlyKernel(),contract)
            self.assertTrue(outcome['converged'],'Only the synthetic dependency envelope was evaluated')
            key,raw=graph.db.execute("SELECT n.key,r.payload FROM node n JOIN result r ON r.node=n.key WHERE n.role='base' AND r.generation=0").fetchone()
            wrapper=decode_result_payload(raw);wrapper['contract']['identity']['run_id']='forged-run'
            graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=0 AND node=?',
                (encode_result_payload(wrapper),checkpoint_digest(wrapper),key));graph.db.commit()
            component=graph.db.execute("SELECT component FROM node WHERE role='final'").fetchone()[0]
            with self.assertRaises(ValueError):graph._packet(component,0)

    def test_release_recipe_cannot_turn_missing_previous_result_into_convergence(self):
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        with self.graph('missing-release') as graph:
            graph.root('root',1);graph.expand();graph.components();graph._evaluation_schema()
            recipe=dict(kind='continuation',previous_key='["missing","missing-journey","a",[0,10]]')
            graph.derived_secret=b'synthetic-test-producer-key-only'
            key=interval_key(self.rows[1]);payload=json.dumps(recipe)
            signature=graph._derived_signature('recipe',0,key,payload)
            graph.db.execute('INSERT INTO recipe VALUES (?,?,?,?)',(0,key,payload,signature))
            with self.assertRaises(ValueError):graph.next_releases(0)

    def test_constructor_and_reopen_failures_restore_owned_sqlite_scope(self):
        from simz1_queue_support import AuxiliaryStorageScope, AuxiliaryStorageExceeded
        self.write_source({1:self.record('root','a',0,30,1,hold=10)})
        with self.graph('constructor-context') as graph:
            context=graph.context;graph.close()
            with self.assertRaises(AuxiliaryStorageExceeded):
                CausalGraph(self.root/'constructor-budget'/'budget-failure.sqlite',context,max_disk_bytes=1)
            self.assertTrue((self.root/'constructor-budget'/'budget-failure.sqlite').exists(),
                'The failure must occur after opening the database, not before scope entry')
            with AuxiliaryStorageScope(self.root,1024**3) as scope:
                self.assertTrue(scope.active)
            # DDL writes with a normal budget still fail closed on malformed
            # graph metadata; failure must release the process-global scope.
            bad=self.root/'bad-reopen.sqlite'
            with closing(sqlite3.connect(bad)) as db:db.execute('CREATE TABLE different(value)')
            with self.assertRaises(sqlite3.OperationalError):CausalGraph.open_graph(bad,context,'0'*64)
            with AuxiliaryStorageScope(self.root,1024**3) as scope:self.assertTrue(scope.active)


if __name__=='__main__':unittest.main()
