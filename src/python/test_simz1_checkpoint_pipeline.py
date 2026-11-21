"""Synthetic SQLite -> actual Node kernel -> sealed library -> context tests."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_simz1_causal_support_graph as source_fixture
import test_simz1_checkpoint_contract as bridge_fixture
from simz1_queue_checkpoint import CheckpointKernel, kernel_contract, compact_component_packet, expanded_packet_bytes
from simz1_queue_checkpoints import CausalGraph, decode_result_payload, encode_result_payload, checkpoint_digest, state_key
from simz1_queue_checkpoint_library import CheckpointLibrary
from simz1_queue_context import hold_time, interval_key


class CheckpointPipelineTests(unittest.TestCase):
    def setUp(self):
        self.source=source_fixture.CausalSupportGraphTests();self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.bridge=bridge_fixture.CheckpointBridgeTests();self.bridge.setUp()
        self.addCleanup(self.bridge.doCleanups)

    def run_pipeline(self,rows,geometry,root_id,*,release=False,batch_size=8,name='pipeline',root_order=()):
        self.source.geometry=geometry
        self.source.blocks=[dict(index=0,start_seconds=0,end_seconds=60)]
        raw={i:{key:value for key,value in row.items() if key!='Trip'} for i,row in enumerate(rows,1)}
        if not self.source.database.exists():self.source.write_source(raw)
        else:self.assertEqual(self.source.rows,raw)
        root=raw[root_id];key=interval_key(root);epoch=hold_time(root)
        with self.source.graph(name) as graph:
            graph.root('target',root_id)
            for ident in root_order:graph.root('extra-'+str(ident),ident)
            fifo_epoch=epoch-.5
            stage=[root['Native_Occupancy']['ordinal'],key]
            fifo_node=graph.add(root_id,fifo_epoch,'fifo:'+json.dumps(stage,separators=(',',':')))
            graph.db.execute('INSERT INTO root VALUES (?,?)',('approach',fifo_node))
            graph.expand();graph.components()
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,self.bridge.settings)
            identity=graph.index.receipt['contract']['identity']
            with CheckpointKernel(identity,geometry,self.bridge.settings,
                    log_path=self.source.root/(name+'-kernel.stderr.log')) as kernel:
                actual_solve=kernel.solve
                def checked_solve(packet):
                    if packet.get('external_pass'):
                        exact=expanded_packet_bytes(packet)
                        self.assertLessEqual(exact,graph.last_batch_byte_upper_bound)
                        self.assertLessEqual(graph.last_batch_byte_upper_bound,64*1024**2)
                    return actual_solve(packet)
                kernel.solve=checked_solve
                outcome=graph.evaluate(kernel,contract,publish=True,batch_size=batch_size)
                self.assertTrue(outcome['complete']);self.assertTrue(outcome['converged']);self.assertTrue(outcome['published'])
                if release:self.assertGreaterEqual(outcome['contract']['generation'],1,'Native release default is not convergence')
                self.assertEqual(outcome['contract']['identity'],identity)
                hydrated=[{**row,'Trip':graph.context.trip(row['Replay_Journey_Key'])['trip']} for row in raw.values()]
                phases={interval_key(row):'final' for row in hydrated if hold_time(row) is not None}
                reference=dict(records=hydrated,phases=phases,checkpoints={},lane_events=[],requests=[
                    dict(key=key,role='final',epoch=epoch,stage=None),
                    dict(key=key,role='fifo',epoch=fifo_epoch,stage=stage)])
                full=kernel.solve(reference)
                transport,expanded=compact_component_packet(reference)
                self.assertEqual(transport['trips'],{row['Replay_Journey_Key']:row['Trip'] for row in hydrated})
                self.assertTrue(all('Trip' not in row for row in transport['records']))
                self.assertLessEqual(expanded,64*1024**2)
                with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                    final=library.state(root_id,epoch,'final',root)
                    fifo=library.state(root_id,fifo_epoch,'fifo:'+json.dumps(stage,separators=(',',':')),root)
                    self.assertIsNotNone(final);self.assertIsNotNone(fifo)
                    capsule=CausalGraph._merge_capsule(final,fifo)
                    self.assertEqual(capsule['final'],full['states'][0]['result'])
                    expected_fifo=next(row for row in capsule['fifo'] if row['epoch']==fifo_epoch and row['stage']==stage)
                    self.assertEqual(expected_fifo['result'],full['states'][1]['result'])
                    resolved=library.resolved_seed(graph.context,root_id,root)
                    self.assertTrue(resolved['complete'])
                    self.assertTrue(resolved['support_certificate']['converged'])
                    self.assertFalse(resolved['support_certificate']['poses_certified'])
                    graph.context.checkpoint_library=library
                    contextual=graph.context.resolve([(root_id,root)])
                    self.assertTrue(contextual['by_seed'][key]['complete'])
                    self.assertEqual(contextual['checkpoint_contract'],outcome['contract'])
                    # This tiny fixture also permits transport of the target's
                    # complete capsule without hydrating its FIFO ancestors.
                    bounded=dict(records=[next(row for row in hydrated if interval_key(row)==key)],
                        phases={key:'final'},checkpoints={key:capsule},lane_events=[],requests=reference['requests'])
                    if not release:
                        self.assertEqual(kernel.solve(bounded)['states'],full['states'])
                        for at in (epoch,epoch+.001,epoch+2,epoch+.001):
                            request=dict(key=key,role='fifo',epoch=at,stage=stage)
                            self.assertEqual(kernel.solve({**bounded,'requests':[request]})['states'],
                                             kernel.solve({**reference,'requests':[request]})['states'])
                self.assertLessEqual(kernel.max_request_bytes,64*1024**2)
                self.assertLessEqual(kernel.max_response_bytes,64*1024**2)
                self.assertLessEqual(kernel.max_expanded_request_bytes,64*1024**2)
                semantic=[]
                for node,payload in graph.db.execute('SELECT node,payload FROM result WHERE generation=? ORDER BY node',(outcome['contract']['generation'],)):
                    wrapper=decode_result_payload(payload);expected=wrapper['contract'];capsule=wrapper['capsule']
                    role=expected['role']
                    result=capsule[role] if role in ('base','final') else next(item['result'] for item in capsule[role]
                        if item['epoch']==expected['epoch'] and item['stage']==expected['stage'])
                    semantic.append((node,result,capsule['release']))
                summary=dict(states=semantic,generation=outcome['contract']['generation'],calls=kernel.calls)
            self.assertIsNone(kernel.process)
            return summary

    def release_chain(self):
        """Nine observed terminal records propagate four native service releases."""
        geometry=deepcopy(self.bridge.geometry);road=geometry['links']['road']
        scale=6371008.8*math.pi/180
        road.update(path=[[0,0],[100/scale,0]],length_m=100,from_node='a',to_node='b',
            native_lanes={},allowed_to_links=[],osm_tags={})
        rows=[]
        def common(vehicle,ordinal,start,end):
            return dict(vehicle=vehicle,Agent_ID=vehicle,Replay_Journey_Key='journey-'+vehicle,
                Link_ID='road',timestamps=[start,end],path=[[100/scale,0],[100/scale,0]],Vehicle_Type='bus',
                Vehicle_Dimensions=dict(length_m=12,width_m=2.5,source='synthetic_fixture',assumed=True),
                Native_Occupancy=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=ordinal),
                Motion_Plan=dict(version=1,status='stationary',distance_m=0,phases=[[start,end,0,0,0]]),
                Observed_Waits={})
        head=common('initial-head',1,0,2)
        head['Boundary_Provenance']=dict(start='entered link',end='left link',start_relative=1,end_relative=1)
        head['Motion_Plan'].update(hold_start=.5,native_wait_boundary=.5)
        head['Observed_Waits']=dict(signal_red=dict(first=.5,last=1,position_evidence='queue_exit',
            sources=['MATSim15_QNode_native_branch']))
        head['Trip']=dict(Trip_ID='head',Status='completed',Departure=0,Arrival=2);rows.append(head)
        for i in range(4):
            vehicle='service-'+str(i);arrive=1+i*10;depart=10+i*10;end=12+i*10
            stop=dict(start=arrive,end=depart,state='stop',source='native_facility_events',link_id='road',
                relative_position=1,position_source='MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment',
                facility_id='shared-terminal',is_blocking_lane=True)
            trip=dict(Trip_ID='trip-'+vehicle,Person_ID=vehicle,Status='completed',Departure=arrive,Arrival=end,
                Transit=dict(schema='simz1-transit-replay-v1',vehicle_id=vehicle,activity_intervals=[stop]))
            for start,finish,first,last in ((arrive,depart,'VehicleArrivesAtFacility','VehicleDepartsAtFacility'),
                    (depart,end,'VehicleDepartsAtFacility','left link')):
                row=common(vehicle,i+2,start,finish);row['Trip']=deepcopy(trip)
                row['Boundary_Provenance']=dict(start=first,end=last,start_relative=1,end_relative=1,distance='network_length_fraction')
                rows.append(row)
        return rows,geometry

    def evaluate_chain(self,name,*,retention=True,after_seal=None):
        rows,geometry=self.release_chain();self.source.geometry=geometry
        self.source.blocks=[dict(index=0,start_seconds=0,end_seconds=60)]
        raw={ident:{key:value for key,value in row.items() if key!='Trip'} for ident,row in enumerate(rows,1)}
        if not self.source.database.exists():
            self.source.write_source(raw)
            with closing(sqlite3.connect(self.source.database)) as db,db:
                for row in rows:db.execute('UPDATE journeys SET metadata=? WHERE key=?',
                    (json.dumps(row['Trip']),row['Replay_Journey_Key']))
            self.source.source_sha=hashlib.sha256(self.source.database.read_bytes()).hexdigest()
        with self.source.graph(name) as graph:
            requests=[]
            for ident,row in raw.items():
                graph.root('root-'+str(ident),ident)
                epoch=hold_time(row) if hold_time(row) is not None else row['timestamps'][0]
                for role in ('base','final'):
                    graph.add(ident,epoch,role)
                    requests.append(dict(key=interval_key(row),role=role,epoch=epoch,stage=None))
            root=raw[9];key=interval_key(root);stage=[99,key]
            graph.add(9,40,'fifo:'+json.dumps(stage,separators=(',',':')))
            requests.append(dict(key=key,role='fifo',epoch=40,stage=stage))
            graph.expand();graph.components()
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,self.bridge.settings)
            traces=[];sql=[];original_seal=graph.seal_generation
            def checked_seal(generation,changed):
                original_seal(generation,changed)
                values=[]
                for node,payload in graph.db.execute('SELECT node,payload FROM result WHERE generation=? ORDER BY node',(generation,)):
                    wrapper=decode_result_payload(payload);values.append((node,wrapper['capsule']))
                traces.append(dict(generation=generation,changed=changed,states=values))
                if after_seal is not None:after_seal(graph,generation)
            graph.seal_generation=checked_seal
            if not retention:
                graph.prune_generations=lambda generation:graph.verify_generation_chain()
            graph.db.set_trace_callback(sql.append)
            with CheckpointKernel(contract['source_contract']['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/(name+'-node.log')) as kernel:
                outcome=graph.evaluate(kernel,contract,publish=True)
                self.assertEqual(outcome['contract']['generation'],4)
                reference=kernel.solve(dict(records=rows,phases={interval_key(row):'final' for row in rows},
                    checkpoints={},lane_events=[],requests=requests))
                with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                    final=library.state(9,40,'final',root)
                    self.assertEqual(final['final'],reference['states'][-2]['result'])
                    self.assertTrue(final['final']['pose_available']);self.assertTrue(final['final']['within_storage'])
                    self.assertTrue(library.resolved_seed(graph.context,9,root)['complete'])
            graph.db.set_trace_callback(None)
            generations=[row[0] for row in graph.db.execute('SELECT DISTINCT generation FROM result ORDER BY generation')]
            if retention:
                self.assertEqual(generations,[3,4]);self.assertEqual(graph._digest_only,{3})
                self.assertEqual(graph.db.execute("SELECT count(*) FROM result WHERE generation=3 AND payload<>x''").fetchone()[0],0)
                self.assertEqual(graph.db.execute('SELECT generation FROM generation_archive ORDER BY generation').fetchall(),[(0,),(1,),(2,)])
                with self.assertRaisesRegex(ValueError,'retired'):graph._packet(0,3)
                cleanup=[line for line in sql if line.startswith('DELETE FROM')]
                self.assertTrue(cleanup);self.assertTrue(all('LIMIT 256' in line or 'generation_seal' in line for line in cleanup))
                self.assertFalse(any('VACUUM' in line.upper() for line in sql))
                plan=graph.db.execute('EXPLAIN QUERY PLAN SELECT node FROM result WHERE generation=? AND node>? ORDER BY node LIMIT 256',(3,'')).fetchall()
                self.assertIn('generation=? AND node>?',' '.join(str(row) for row in plan))
                self.assertTrue(any('node>' in line for line in sql if line.startswith('UPDATE result SET payload')))
            else:self.assertEqual(generations,list(range(5)))
            self.assertEqual(graph.verify_generation_chain()['last_completed'],4)
            if retention:
                with self.assertRaisesRegex(ValueError,'Premature'):graph.prune_generations(6)
            return traces

    def test_retention_and_digest_only_previous_generation_match_five_generation_reference(self):
        full=self.evaluate_chain('chain-full',retention=False)
        retained=self.evaluate_chain('chain-retained')
        self.assertEqual(retained,full)
        self.assertEqual([row['generation'] for row in retained],[0,1,2,3,4])
        self.assertTrue(all(row['changed']>0 for row in retained[:-1]))
        self.assertEqual(retained[-1]['changed'],0)

    def test_retention_rejects_mutated_previous_digest_payload_release_recipe_and_archive(self):
        def mutation(kind,seen):
            def after(graph,generation):
                if generation!=2:return
                seen.append(generation)
                if kind=='sentinel':graph.db.execute("UPDATE result SET payload=x'00' WHERE generation=1")
                elif kind=='digest':graph.db.execute('UPDATE result SET sha256=? WHERE generation=2',('f'*64,))
                elif kind=='payload':graph.db.execute("UPDATE result SET payload=x'00' WHERE generation=2")
                elif kind=='self_rehash':
                    from simz1_queue_result_trust import _leaf,_parent
                    node,payload=graph.db.execute('SELECT node,payload FROM result WHERE generation=2 ORDER BY node LIMIT 1').fetchone()
                    wrapper=decode_result_payload(payload);wrapper['capsule']['input']='forged'
                    digest=checkpoint_digest(wrapper)
                    graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=2 AND node=?',
                        (encode_result_payload(wrapper),digest,node))
                    leaves=[_leaf(2,key,sha) for key,sha in graph.db.execute('SELECT node,sha256 FROM result WHERE generation=2 ORDER BY node')]
                    level=0
                    while True:
                        for position,sha in enumerate(leaves):graph.db.execute(
                            'UPDATE result_trust_auth SET digest=? WHERE generation=2 AND level=? AND position=?',(sha,level,position))
                        if len(leaves)==1:break
                        leaves=[_parent(leaves[i],leaves[min(i+1,len(leaves)-1)]) for i in range(0,len(leaves),2)];level+=1

                elif kind in ('release_state','recipe'):
                    graph.db.execute('UPDATE '+kind+' SET payload=?,signature=? WHERE generation=2',('null','f'*64))
                elif kind=='archive':
                    value,=graph.db.execute('SELECT payload FROM generation_archive WHERE generation=0').fetchone()
                    forged=json.loads(value);forged['material']['changed']=999
                    payload=json.dumps(forged,sort_keys=True,separators=(',',':'))
                    graph.db.execute('UPDATE generation_archive SET payload=?,signature=? WHERE generation=0',
                        (payload,hashlib.sha256(payload.encode()).hexdigest()))
                elif kind=='archive_missing':graph.db.execute('DELETE FROM generation_archive WHERE generation=0')
                graph.commit('synthetic_adversary')
            return after
        for kind in ('sentinel','digest','payload','self_rehash','release_state','recipe','archive','archive_missing'):
            seen=[]
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.evaluate_chain('tamper-'+kind,after_seal=mutation(kind,seen))
                self.assertEqual(seen,[2],'The rejection must follow the intended adversarial mutation')

    def test_sealing_more_than_256_real_states_preserves_all_published_roots(self):
        geometry=dict(schema_version=1,available=True,links={},occupancy_corridors=dict(schema='corridor-length-v1',corridors={}))
        self.source.geometry=geometry;rows={}
        for ident in range(1,130):
            link='road-'+str(ident);x=ident*.01
            geometry['links'][link]=self.source.link('from-'+str(ident),'to-'+str(ident),[[x,0],[x+.001,0]],[])
            geometry['occupancy_corridors']['corridors'][link]=dict(link_ids=[link],represented_lanes=1)
            rows[ident]=self.source.record('vehicle-'+str(ident),link,0,30,1,hold=10)
        self.source.write_source(rows)
        with self.source.graph('sealing-258-states') as graph:
            for ident in rows:graph.root('root-'+str(ident),ident)
            graph.expand();graph.components()
            self.assertEqual(graph.db.execute('SELECT count(*) FROM node').fetchone()[0],258)
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,self.bridge.settings)
            stages=[];commit=graph.commit
            def observed_commit(stage='graph_commit'):stages.append(stage);return commit(stage)
            graph.commit=observed_commit
            with CheckpointKernel(contract['source_contract']['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/'sealing-258-node.log') as kernel:
                outcome=graph.evaluate(kernel,contract,publish=True)
            self.assertTrue('library_sealing_leaves' in stages,stages)
            with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                for ident,row in rows.items():
                    capsule=library.state(ident,10,'final',row)
                    self.assertTrue(capsule['final']['pose_available'])
                    self.assertTrue(library.resolved_seed(graph.context,ident,row)['complete'])
            self.assertEqual(graph.db.execute('SELECT count(*) FROM result').fetchone()[0],258)

    def test_post_facility_traffic_exit_requires_actual_hold_phases_for_fifo_and_projection(self):
        rows,geometry=self.release_chain();rows=rows[:3]
        rows[-1]['Boundary_Provenance']['end']='vehicle leaves traffic'
        self.source.geometry=geometry
        raw={ident:{key:value for key,value in row.items() if key!='Trip'} for ident,row in enumerate(rows,1)}
        self.source.write_source(raw)
        with closing(sqlite3.connect(self.source.database)) as db,db:
            for row in rows:db.execute('UPDATE journeys SET metadata=? WHERE key=?',
                (json.dumps(row['Trip']),row['Replay_Journey_Key']))
        self.source.source_sha=hashlib.sha256(self.source.database.read_bytes()).hexdigest()
        with self.source.graph('post-facility-traffic-exit') as graph:
            graph.root('facility',2)
            key=interval_key(raw[3]);stage=[99,key]
            project_role='project:'+json.dumps(stage,separators=(',',':'))
            fifo_role='fifo:'+json.dumps(stage,separators=(',',':'))
            for role in (project_role,fifo_role):
                node=graph.add(3,11,role);graph.db.execute('INSERT INTO root VALUES (?,?)',(role,node))
            graph.expand();graph.components()
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,self.bridge.settings)
            with CheckpointKernel(contract['source_contract']['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/'post-facility-traffic-exit-node.log') as kernel:
                outcome=graph.evaluate(kernel,contract,publish=True)
                self.assertTrue(outcome['converged'])
                self.assertEqual(graph.hold(graph.scalar(3)),10)
                for role in (project_role,fifo_role):
                    deps=graph.db.execute('SELECT target FROM edge WHERE source=? AND kind=?',
                        (state_key(3,11,role),'same_pass')).fetchall()
                    self.assertIn((state_key(3,10,'final'),),deps)
                requests=[dict(key=key,epoch=11,role='interpolate',stage=stage),dict(key=key,epoch=11,role='fifo',stage=stage)]
                reference=dict(records=rows,phases={interval_key(row):'final' for row in rows},checkpoints={},
                    lane_events=[],requests=requests)
                full=kernel.solve(reference)
                with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                    projected=library.state(3,11,project_role,raw[3]);fifo=library.state(3,11,fifo_role,raw[3])
                    self.assertEqual(next(row['result'] for row in projected['interpolate'] if row['epoch']==11 and row['stage']==stage),full['states'][0]['result'])
                    self.assertEqual(next(row['result'] for row in fifo['fifo'] if row['epoch']==11 and row['stage']==stage),full['states'][1]['result'])
                    self.assertTrue(library.resolved_seed(graph.context,3,raw[3])['complete'])
                missing=deepcopy(reference);del missing['phases'][key]
                with self.assertRaisesRegex(ValueError,'Interpolacion HOLD sin fase corporal certificada'):
                    kernel.solve(missing)

    def test_three_buses_actual_kernel_and_authenticated_library_are_equivalent(self):
        self.run_pipeline(deepcopy(self.bridge.records),deepcopy(self.bridge.geometry),3)

    def test_terminal_lane_classification_uses_complete_native_timeline_through_publication(self):
        # This native reservation cannot be represented across bridge/ground.
        # Its terminal entry still creates a visual fallback before HOLD; the
        # entry at t=0 alone is insufficient evidence for anchor absence.
        geometry=self.source.geometry
        geometry['links']['a']['osm_tags']={'bridge':'yes'}
        geometry['links']['b'].update(length_m=100,native_lanes={
            'original':dict(index=None,to_lanes=['terminal'],start_m=100,represented_lanes=1),
            'terminal':dict(index=0,to_lanes=[],start_m=90,represented_lanes=1)})
        raw={1:self.source.record('fallback','b',0,20,158573,hold=10),
             2:self.source.record('native-later','a',0,20,100,hold=8)}
        raw[1]['Native_Occupancy'].update(passage_links=['a'],passage_slots=[0],receipt_link='b')
        self.source.write_source(raw)
        events=[dict(type='entered lane',time=0,vehicle='fallback',link='b',lane='original'),
                dict(type='left lane',time=7,vehicle='fallback',link='b',lane='original'),
                dict(type='entered lane',time=7,vehicle='fallback',link='b',lane='terminal')]
        with closing(sqlite3.connect(self.source.database)) as database,database:
            for seq,event in enumerate(events,1):database.execute('INSERT INTO lane_events VALUES(?,?,?,?)',
                (seq,event['vehicle'],event['time'],source_fixture.packed(event)))
        self.source.source_sha=hashlib.sha256(self.source.database.read_bytes()).hexdigest()
        with self.source.graph('terminal-unclassified') as before:
            self.assertIn(2,{row[0] for row in before.dependencies(1,10,'final')[0]})
            proof=self.bridge.facility_proof()
            proof['identity']=before.index.receipt['contract']['identity']
            proof['source_sqlite_sha256']=self.source.source_sha
            contract=kernel_contract(before.index.receipt['contract'],before.index.receipt['sha256'],geometry,
                self.bridge.settings,facility_support=proof)
            with CheckpointKernel(proof['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/'terminal-classifier-pipeline.log',facility_support=proof,
                    source_sqlite_sha256=self.source.source_sha) as kernel:
                kwargs=dict(validate_segment=source_fixture.ContinuousReplay.validate_native_segment,
                    validate_trip=lambda trip:None,domains=source_fixture.queue_domains(geometry),visual_lanes=geometry,
                    support_index=before.index,facility_support=proof,phase_classifier=kernel,classifier_contract=contract)
                context=source_fixture.QueueContext(before.context.connection,self.source.blocks,**kwargs)
                for altered in ({**contract,'geometry_sha256':'0'*64},{**contract,'index_sha256':'0'*64}):
                    with self.subTest(contract=altered),self.assertRaisesRegex(ValueError,'classif'):
                        source_fixture.QueueContext(before.context.connection,self.source.blocks,
                            **{**kwargs,'classifier_contract':altered})
                with closing(CausalGraph(self.source.root/'terminal-classified.sqlite',context,storage=before.storage)) as graph:
                    consumer=graph.consumer(graph.scalar(1));key=interval_key(raw[1])
                    self.assertEqual(consumer['visual_order'],7);self.assertEqual(consumer['visual_group'],('b',0))
                    self.assertFalse(consumer['occupancy']);self.assertIsNone(graph.scalar(1)['ordinal'])
                    self.assertIsNone(context.phase_absence(raw[1],10,'final'))
                    self.assertIs(consumer['proof']['classification']['departure_complete'],True)
                    self.assertTrue(any(row['epoch']==10 and row['inclusive'] for row in consumer['proof']['lane_coverage']))
                    self.assertNotIn(2,{row[0] for row in graph.dependencies(1,10,'final')[0]})
                    self.assertEqual(kernel.classification_calls,1,'Repeated use must reuse source-bound classification')
                    graph.root('terminal-target',1);graph.expand();graph.components()
                    with self.assertRaisesRegex(ValueError,'classification'):
                        graph.evaluate(kernel,{**contract,'geometry_sha256':'0'*64},publish=True)
                    outcome=graph.evaluate(kernel,contract,publish=True)
                    self.assertTrue(outcome['complete']);self.assertTrue(outcome['converged']);self.assertTrue(outcome['published'])
                    hydrated=[{**row,'Trip':context.trip(row['Replay_Journey_Key'])['trip']} for row in raw.values()]
                    requests=[dict(key=key,epoch=10,role=role,stage=None) for role in ('base','final')]
                    reference=dict(records=hydrated,phases={interval_key(row):'final' for row in hydrated},
                        checkpoints={},lane_events=events,requests=requests)
                    full=kernel.solve(reference)
                    with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                        capsules=[]
                        for role,state in zip(('base','final'),full['states']):
                            capsule=library.state(1,10,role,raw[1]);capsules.append(capsule)
                            self.assertEqual(capsule[role],state['result'])
                            self.assertTrue(capsule[role]['available']);self.assertTrue(capsule[role]['pose_available'])
                            self.assertEqual(json.loads(capsule['prepared'])['order'],7)
                        capsule=CausalGraph._merge_capsule(*capsules)
                        resolved=library.resolved_seed(context,1,raw[1]);self.assertTrue(resolved['complete'])
                        self.assertFalse(resolved['support_certificate']['poses_certified'])
                        context.checkpoint_library=library
                        self.assertTrue(context.resolve([(1,raw[1])])['by_seed'][key]['complete'])
                        bounded={**reference,'records':hydrated[:1],'phases':{key:'final'},'checkpoints':{key:capsule}}
                        self.assertEqual(kernel.solve(bounded)['states'],full['states'])
                    self.assertLessEqual(kernel.max_expanded_request_bytes,64*1024**2)
            self.assertIsNone(kernel.process)
        self.assertEqual(hashlib.sha256(self.source.database.read_bytes()).hexdigest(),self.source.source_sha)

    def test_inactive_anchor_exclusion_preserves_source_and_published_hold_state(self):
        geometry=deepcopy(self.bridge.geometry);self.source.geometry=geometry
        self.source.blocks=[dict(index=0,start_seconds=0,end_seconds=60)]
        moving=self.bridge.record('visible-moving',1,10,1)
        moving['Motion_Plan']=dict(version=1,status='kinematic',distance_m=100,phases=[[1,50,0,100/49,0]])
        moving['Observed_Waits']={};moving['Native_Occupancy']['model_slot']=2
        held=self.bridge.record('held-target',2,15,3)
        raw={ident:{key:value for key,value in row.items() if key!='Trip'}
             for ident,row in enumerate((moving,held),1)}
        self.source.write_source(raw);key=interval_key(held)
        with self.source.graph('inactive-unclassified') as before:
            self.assertIn(1,{row[0] for row in before.dependencies(2,15,'base')[0]},
                'The former conservative branch requests an undefined moving interpolation state')
            contract=kernel_contract(before.index.receipt['contract'],before.index.receipt['sha256'],geometry,self.bridge.settings)
            with CheckpointKernel(before.index.receipt['contract']['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/'inactive-classifier-pipeline.log',source_sqlite_sha256=self.source.source_sha) as kernel:
                context=source_fixture.QueueContext(before.context.connection,self.source.blocks,
                    validate_segment=source_fixture.ContinuousReplay.validate_native_segment,validate_trip=lambda trip:None,
                    domains=source_fixture.queue_domains(geometry),visual_lanes=geometry,support_index=before.index,
                    phase_classifier=kernel,classifier_contract=contract)
                with closing(CausalGraph(self.source.root/'inactive-classified.sqlite',context,storage=before.storage)) as graph:
                    consumer=graph.consumer(graph.scalar(1))
                    self.assertEqual(consumer['scope'],'anchor_constraints_only')
                    self.assertIs(consumer['represented'],False);self.assertIs(consumer['eligible'],False)
                    self.assertEqual(consumer['proof']['classification']['reason'],'inactive_context_without_occupancy_or_hold')
                    self.assertIsNotNone(consumer['proof'].get('occupancy_absence'))
                    self.assertNotIn(1,{row[0] for row in graph.dependencies(2,15,'base')[0]})
                    self.assertNotIn(1,{row[0] for row in graph.dependencies(2,15,'final')[0]})
                    self.assertEqual(graph.record(1),raw[1],'Anchor exclusion cannot rewrite or remove an active observation')
                    self.assertEqual([row[0] for row in graph.context.connection.execute(
                        'SELECT id FROM segments WHERE start<=? AND end>? ORDER BY id',(14,14))],[1,2])
                    graph.root('held-target',2);graph.expand();graph.components()
                    outcome=graph.evaluate(kernel,contract,publish=True)
                    self.assertTrue(outcome['complete']);self.assertTrue(outcome['published']);self.assertTrue(outcome['converged'])
                    hydrated=[{**row,'Trip':context.trip(row['Replay_Journey_Key'])['trip']} for row in raw.values()]
                    requests=[dict(key=key,role=role,epoch=15,stage=None) for role in ('base','final')]
                    packet=dict(records=hydrated,phases={interval_key(row):'final' for row in hydrated},
                        checkpoints={},lane_events=[],requests=requests)
                    full=kernel.solve(packet)
                    without_anchor={**packet,'phases':{key:'final'},'constraint_keys':[key]}
                    self.assertEqual(kernel.solve(without_anchor)['states'],full['states'])
                    self.assertEqual(without_anchor['records'],hydrated,'Geometry and active source rows stay present')
                    with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                        for role,state in zip(('base','final'),full['states']):
                            self.assertEqual(library.state(2,15,role,raw[2])[role],state['result'])
                        self.assertTrue(library.resolved_seed(context,2,raw[2])['complete'])
                    self.assertLessEqual(kernel.max_expanded_request_bytes,64*1024**2)
                # A generic unavailable answer, a HOLD, or real native occupancy
                # cannot borrow the narrow no-anchor proof. These callback
                # mutations retain unknown dependencies rather than exclusions.
                original_classify=kernel.classify
                for name,changes in (('unknown_reason',{'reason':'unproven_context_entry'}),
                                     ('incomplete',{'complete':False}),('hold_present',{'hold':10}),
                                     ('eligible',{'eligible':True})):
                    def forged(packet,changes=changes):
                        response=original_classify(packet)
                        response['states'][0]['classification'].update(changes)
                        return response
                    context.classification_cache.clear();context.classification_bytes=0
                    with patch.object(kernel,'classify',side_effect=forged):
                        self.assertIsNone(context.classify_consumer(1,raw[1]),name)
                native=deepcopy(raw[1]);native['Native_Occupancy']['model_slot']=0
                with patch.object(kernel,'classify',side_effect=AssertionError('Valid occupancy must remain native')):
                    self.assertIsNone(context.classify_consumer(1,native))
                native_hold={name:value for name,value in self.bridge.record('visible-moving',1,10,1).items() if name!='Trip'}
                native_hold['Native_Occupancy']['model_slot']=2
                def forged_no_hold(packet):
                    request=packet['requests'][0]
                    return dict(states=[{**request,'classification':deepcopy(consumer['proof']['classification'])}])
                with patch.object(kernel,'classify',side_effect=forged_no_hold):
                    self.assertIsNone(context.classify_consumer(1,native_hold),
                        'The independent source HOLD refutes a forged no-HOLD classifier response')
            self.assertIsNone(kernel.process)
        self.assertEqual(hashlib.sha256(self.source.database.read_bytes()).hexdigest(),self.source.source_sha)

    def test_inactive_shared_upstream_reason_requires_live_facility_scope(self):
        geometry=self.source.geometry
        geometry['links']['b'].update(length_m=100,native_lanes={
            'original':dict(index=None,to_lanes=['terminal'],start_m=100,represented_lanes=1),
            'terminal':dict(index=0,to_lanes=[],start_m=80,represented_lanes=1)})
        raw={1:self.source.record('moving','a',0,1,1),
             2:self.source.record('moving','b',1,30,2),
             3:self.source.record('held','b',2,30,3,hold=15)}
        raw[2]['Native_Occupancy']['model_slot']=2
        self.source.write_source(raw)
        events=[dict(type='entered lane',time=1,vehicle='moving',link='b',lane='original'),
                dict(type='entered lane',time=7,vehicle='moving',link='b',lane='terminal')]
        with closing(sqlite3.connect(self.source.database)) as database,database:
            for seq,event in enumerate(events,1):database.execute('INSERT INTO lane_events VALUES(?,?,?,?)',
                (seq,event['vehicle'],event['time'],source_fixture.packed(event)))
        self.source.source_sha=hashlib.sha256(self.source.database.read_bytes()).hexdigest()
        with self.source.graph('inactive-shared-reference') as before:
            proof=self.bridge.facility_proof();proof['identity']=before.index.receipt['contract']['identity']
            proof['source_sqlite_sha256']=self.source.source_sha
            contract=kernel_contract(before.index.receipt['contract'],before.index.receipt['sha256'],geometry,
                self.bridge.settings,facility_support=proof)
            with CheckpointKernel(proof['identity'],geometry,self.bridge.settings,facility_support=proof,
                    source_sqlite_sha256=self.source.source_sha,log_path=self.source.root/'inactive-shared-kernel.log') as kernel:
                context=source_fixture.QueueContext(before.context.connection,self.source.blocks,
                    validate_segment=source_fixture.ContinuousReplay.validate_native_segment,validate_trip=lambda trip:None,
                    domains=source_fixture.queue_domains(geometry),visual_lanes=geometry,support_index=before.index,
                    facility_support=proof,phase_classifier=kernel,classifier_contract=contract)
                observed=[];actual=kernel.classify
                def capture(packet):
                    result=actual(packet);observed.append(deepcopy(result));return result
                with patch.object(kernel,'classify',side_effect=capture):consumer=context.classify_consumer(2,raw[2])
                value=observed[0]['states'][0]['classification']
                self.assertEqual(value['reason'],'shared_upstream_without_blocking_facility')
                self.assertIs(value['complete'],True);self.assertIs(value['represented'],False)
                self.assertIs(value['eligible'],False);self.assertIsNone(value['hold']);self.assertIsNone(value['occupancy'])
                self.assertIsNotNone(consumer,'A certified moving shared-upstream absence must use the same anchor-only scope')
                self.assertEqual(consumer['scope'],'anchor_constraints_only')
                with closing(CausalGraph(self.source.root/'inactive-shared-published.sqlite',context,storage=before.storage)) as graph:
                    self.assertNotIn(2,{row[0] for row in graph.dependencies(3,15,'base')[0]})
                    self.assertNotIn(2,{row[0] for row in graph.dependencies(3,15,'final')[0]})
                    graph.root('held',3);graph.expand();graph.components()
                    outcome=graph.evaluate(kernel,contract,publish=True)
                    self.assertTrue(outcome['published']);self.assertTrue(outcome['converged'])
                    hydrated=[{**row,'Trip':context.trip(row['Replay_Journey_Key'])['trip']} for row in raw.values()]
                    key=interval_key(raw[3]);requests=[dict(key=key,epoch=15,role=role,stage=None) for role in ('base','final')]
                    full=kernel.solve(dict(records=hydrated,phases={interval_key(row):'final' for row in hydrated},
                        checkpoints={},lane_events=events,requests=requests))
                    with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                        for role,state in zip(('base','final'),full['states']):
                            self.assertEqual(library.state(3,15,role,raw[3])[role],state['result'])
                    self.assertEqual(graph.record(2),raw[2])
                # An otherwise identical classifier result is not authoritative
                # after removal/change of the independently verified facility scope.
                original=context.facility_support
                for invalid in (None,{**original,'blocking_links':['b']}):
                    context.facility_support=invalid;context.classification_cache.clear();context.classification_bytes=0
                    try:
                        with patch.object(kernel,'classify',return_value=observed[0]):
                            self.assertIsNone(context.classify_consumer(2,raw[2]))
                    finally:context.facility_support=original
                for changed in ({'complete':False},{'eligible':True},{'hold':15},{'reason':'unproven_context_absence'}):
                    forged=deepcopy(observed[0]);forged['states'][0]['classification'].update(changed)
                    context.classification_cache.clear();context.classification_bytes=0
                    with patch.object(kernel,'classify',return_value=forged):
                        self.assertIsNone(context.classify_consumer(2,raw[2]))
                native=deepcopy(raw[2]);native['Native_Occupancy']['model_slot']=0
                with patch.object(kernel,'classify',side_effect=AssertionError('Valid occupancy must remain native')):
                    self.assertIsNone(context.classify_consumer(2,native))
                native_hold=self.source.record('moving','b',1,30,2,hold=15)
                native_hold['Native_Occupancy']['model_slot']=2
                forged=deepcopy(observed[0]);forged['states'][0]['epoch']=15
                with patch.object(kernel,'classify',return_value=forged):
                    self.assertIsNone(context.classify_consumer(2,native_hold),
                        'Shared-upstream reason cannot erase a source HOLD')
            self.assertIsNone(kernel.process)
        self.assertEqual(hashlib.sha256(self.source.database.read_bytes()).hexdigest(),self.source.source_sha)

    def test_source_certified_absence_remains_unavailable_through_real_published_library(self):
        geometry,packet=self.bridge.absence_fixture();self.source.geometry=geometry
        self.source.blocks=[dict(index=0,start_seconds=0,end_seconds=60)]
        raw={1:{key:value for key,value in packet['records'][0].items() if key!='Trip'}}
        self.source.write_source(raw)
        with closing(sqlite3.connect(self.source.database)) as database:
            event=packet['lane_events'][0]
            database.execute('INSERT INTO lane_events VALUES (?,?,?,?)',
                (1,event['vehicle'],event['time'],source_fixture.packed(event)))
            database.commit()
        self.source.source_sha=hashlib.sha256(self.source.database.read_bytes()).hexdigest()
        proof=self.bridge.facility_proof();proof['source_sqlite_sha256']=self.source.source_sha
        proof['identity']=dict(run_id='synthetic-causal-graph',iteration=0,run_manifest_sha256='a'*64)
        context_factory=source_fixture.QueueContext
        def certified_context(*args,**kwargs):return context_factory(*args,**kwargs,facility_support=proof)
        with patch.object(source_fixture,'QueueContext',side_effect=certified_context),self.source.graph('absence-library') as graph:
            graph.root('target',1)
            key=interval_key(raw[1]);stage=[3,key]
            graph.db.execute('INSERT INTO root VALUES (?,?)',('base',graph.add(1,10,'base')))
            fifo_role='fifo:'+json.dumps(stage,separators=(',',':'))
            graph.db.execute('INSERT INTO root VALUES (?,?)',('fifo',graph.add(1,10,fifo_role)))
            graph.expand();graph.components()
            self.assertEqual(graph.db.execute('SELECT count(*) FROM edge').fetchone()[0],0,
                'Certified terminal absences must not recursively request predecessor anchors')
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,
                self.bridge.settings,facility_support=proof)
            with CheckpointKernel(proof['identity'],geometry,self.bridge.settings,log_path=self.source.root/'absence-kernel.log',
                    facility_support=proof,source_sqlite_sha256=self.source.source_sha) as kernel:
                for altered in ({key:value for key,value in contract.items() if key!='facility_support'},
                                {**contract,'facility_support':{**contract['facility_support'],'blocking_links':['road']}}):
                    with self.subTest(mismatch='kernel_contract'),self.assertRaisesRegex(ValueError,'[Ff]acility'):
                        graph.evaluate(kernel,altered,publish=True)
                for name,owner in (('kernel',kernel),('context',graph.context)):
                    original_support=owner.facility_support
                    for altered in (None,{**original_support,'source_sqlite_sha256':'e'*64}):
                        owner.facility_support=altered
                        try:
                            with self.subTest(mismatch=name,proof=altered),self.assertRaisesRegex(ValueError,'[Ff]acility'):
                                graph.evaluate(kernel,contract,publish=True)
                        finally:owner.facility_support=original_support
                self.assertEqual(kernel.calls,0,'Mismatched exclusion authority must fail before any geometry evaluation')
                outcome=graph.evaluate(kernel,contract,publish=True)
                self.assertTrue(outcome['complete']);self.assertTrue(outcome['converged']);self.assertTrue(outcome['published'])
                reference=deepcopy(packet)
                reference['records'][0]['Trip']=graph.context.trip(raw[1]['Replay_Journey_Key'])['trip']
                full=kernel.solve(reference)
                with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                    for role,state in zip(('base','final',fifo_role),full['states']):
                        wrapper=library.state(1,10,role,raw[1],include_contract=True)
                        result=wrapper['capsule'][role] if role in ('base','final') else next(
                            row['result'] for row in wrapper['capsule']['fifo'] if row['epoch']==10 and row['stage']==stage)
                        self.assertEqual(result,state['result'])
                        self.assertIs(result['available'],False);self.assertIsNone(result['pose'])
                        if role in ('base','final'):
                            self.assertIsNone(result['anchor_m']);self.assertIs(result['pose_available'],False)
                            self.assertEqual(wrapper['contract']['absence_proof'],wrapper['capsule']['absence_proof'])
                    resolved=library.resolved_seed(graph.context,1,raw[1])
                    self.assertIs(resolved['complete'],False)
                    self.assertEqual(resolved['reason'],'native_visual_anchor_unavailable')
                    self.assertEqual(resolved['record_keys'],[])
                    self.assertNotIn('support_certificate',resolved)
                    graph.context.checkpoint_library=library
                    contextual=graph.context.resolve([(1,raw[1])])
                    self.assertIs(contextual['by_seed'][key]['complete'],False)
                    self.assertEqual(contextual['by_seed'][key]['reason'],'native_visual_anchor_unavailable')
            self.assertIsNone(kernel.process)

    def test_real_projection_states_survive_publication_with_exact_stage_and_private_root(self):
        geometry=deepcopy(self.bridge.geometry);self.source.geometry=geometry
        self.source.blocks=[dict(index=0,start_seconds=0,end_seconds=60)]
        raw={i:{key:value for key,value in row.items() if key!='Trip'}
             for i,row in enumerate(deepcopy(self.bridge.records),1)}
        self.source.write_source(raw)
        root=raw[3];key=interval_key(root);epoch=hold_time(root)-.5
        rank=root['Native_Occupancy']['ordinal']
        stages=(None,[rank,key],[rank+1,key])
        roles=['interpolate' if stage is None else 'project:'+json.dumps(stage,separators=(',',':')) for stage in stages]
        requests=[dict(key=key,role='interpolate',epoch=epoch,stage=stage) for stage in stages]
        with self.source.graph('project-library') as graph:
            graph.root('target',3)
            for index,role in enumerate(roles):
                node=graph.add(3,epoch,role)
                graph.db.execute('INSERT INTO root VALUES (?,?)',('project-'+str(index),node))
            graph.expand();graph.components()
            contract=kernel_contract(graph.index.receipt['contract'],graph.index.receipt['sha256'],geometry,self.bridge.settings)
            with CheckpointKernel(graph.index.receipt['contract']['identity'],geometry,self.bridge.settings,
                    log_path=self.source.root/'project-library-kernel.stderr.log') as kernel:
                outcome=graph.evaluate(kernel,contract,publish=True)
                self.assertTrue(outcome['complete']);self.assertTrue(outcome['converged']);self.assertTrue(outcome['published'])
                hydrated=[{**row,'Trip':graph.context.trip(row['Replay_Journey_Key'])['trip']} for row in raw.values()]
                full=kernel.solve(dict(records=hydrated,phases={interval_key(row):'final' for row in hydrated},
                    checkpoints={},lane_events=[],requests=requests))
                with CheckpointLibrary(graph.verified_preparation,expected=outcome['contract']) as library:
                    for role,request,state in zip(roles,requests,full['states']):
                        wrapper=library.state(3,epoch,role,root,include_contract=True)
                        self.assertEqual(wrapper['contract']['role'],'interpolate')
                        self.assertEqual(wrapper['contract']['stage'],request['stage'])
                        matching=[row for row in wrapper['capsule']['interpolate']
                                  if row['epoch']==epoch and row['stage']==request['stage']]
                        self.assertEqual(len(matching),1)
                        self.assertEqual(matching[0]['result'],state['result'])
                    self.assertIsNone(library.state(3,epoch,'project:'+json.dumps([rank+2,key],separators=(',',':')),root))
                generation=outcome['contract']['generation'];node=state_key(3,epoch,roles[1])
                original,digest=graph.db.execute('SELECT payload,sha256 FROM result WHERE generation=? AND node=?',
                                               (generation,node)).fetchone()
                # Mutate and self-rehash a completed state without modifying the
                # independently pinned Merkle root. File metadata is preserved
                # so rejection must come from authentication, not mtime alone.
                for mutation in ('stage','role'):
                    forged=decode_result_payload(original)
                    if mutation=='stage':
                        forged['contract']['stage']=[rank+1,key]
                        forged['capsule']['interpolate'][0]['stage']=[rank+1,key]
                    else:forged['contract']['role']='fifo'
                    graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=? AND node=?',
                        (encode_result_payload(forged),checkpoint_digest(forged),generation,node))
                    graph.db.commit();stat=graph.path.stat();preparation=graph.verified_preparation
                    self.assertEqual(stat.st_size,preparation['bytes'])
                    os.utime(graph.path,ns=(stat.st_atime_ns,preparation['mtime_ns']))
                    with self.subTest(mutation=mutation),CheckpointLibrary(preparation,expected=outcome['contract']) as library:
                        with self.assertRaisesRegex(ValueError,'root'):library.state(3,epoch,roles[1],root)
                    graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=? AND node=?',
                                     (original,digest,generation,node))
                    graph.db.commit()
            self.assertIsNone(kernel.process)

    def test_batching_and_root_permutation_preserve_all_evaluated_phase_states(self):
        rows=deepcopy(self.bridge.records);geometry=deepcopy(self.bridge.geometry)
        single=self.run_pipeline(rows,geometry,3,batch_size=1,name='single',root_order=(1,2,3))
        batched=self.run_pipeline(rows,geometry,3,batch_size=8,name='batched',root_order=(3,2,1))
        self.assertEqual(single['generation'],batched['generation'])
        self.assertEqual(single['states'],batched['states'])
        self.assertLess(batched['calls'],single['calls'])

    def spatial_release_rows(self,*,cross_x=45.6,cross_hold=14,cross_ordinal=50):
        """A native prefix supports a body well outside its short next link."""
        scale=6371008.8*math.pi/180;geometry=deepcopy(self.bridge.geometry);road=geometry['links'].pop('road')
        def link(start,end,from_node,to_node,targets):
            return {**deepcopy(road),'path':[[start[0]/scale,start[1]/scale],[end[0]/scale,end[1]/scale]],
                'from_node':from_node,'to_node':to_node,'allowed_to_links':targets}
        geometry['links']={
            'a':link((0,0),(100,0),'a0','join',['b']),
            'b':link((100,0),(102,0),'join','b1',[]),
            'cross':link((cross_x,-50),(cross_x,8),'c0','c1',[])}
        geometry['occupancy_corridors']['corridors']={key:dict(link_ids=[key],represented_lanes=1) for key in geometry['links']}
        def record(vehicle,link,start,hold,end,ordinal):
            row=self.bridge.record(vehicle,start,hold,ordinal);row['Link_ID']=link
            row['path']=geometry['links'][link]['path'];row['timestamps']=[start,end]
            row['Native_Occupancy']['corridor_id']=link
            length={'a':100,'b':2,'cross':58}[link]
            row['Motion_Plan']=dict(version=1,status='kinematic',distance_m=length,hold_start=hold,native_wait_boundary=hold,
                phases=[[start,hold,0,length/(hold-start),0],[hold,end,length,0,0]])
            row['Observed_Waits']['signal_red'].update(first=hold,last=end-1)
            return row
        rows=[]
        for i in range(5):
            rows.extend([record('bus-'+str(i),'a',0,1+i*.1,10+i,1+i),
                         record('bus-'+str(i),'b',10+i,10.5+i,50,100+i)])
        rows.append(record('cross-bus','cross',13.5,cross_hold,50,cross_ordinal))
        return rows,geometry

    def test_shifted_rear_support_keeps_geometric_hold_outside_current_link_domain(self):
        rows,geometry=self.spatial_release_rows(cross_x=51.4)
        # Complete source closure must include the cross HOLD at the current
        # epoch, despite its distance from the 2 m terminal reference link.
        self.run_pipeline(rows,geometry,10,release=True,name='spatial-release')

    def test_candidate_with_remote_reference_keeps_its_nearby_previous_body_support(self):
        rows,geometry=self.spatial_release_rows(cross_x=51.4,cross_hold=15,cross_ordinal=200)
        # Here the requested body is local. Its candidate's reference is remote,
        # while the candidate's released rear is on the nearby previous link.
        self.run_pipeline(rows,geometry,11,release=True,name='remote-candidate')

    def test_spatial_index_cannot_change_scope_membership_or_binding_by_self_rehash(self):
        rows,geometry=self.spatial_release_rows();self.source.geometry=geometry
        raw={ident:{key:value for key,value in row.items() if key!='Trip'} for ident,row in enumerate(rows,1)}
        self.source.write_source(raw)
        expected=source_fixture.contract(self.source.database,dict(run_id='synthetic-causal-graph',iteration=0,
            run_manifest_sha256='a'*64),self.source.source_sha,geometry)
        for mode in ('omit','amplify','temporal_scope'):
            directory=self.source.root/('scope-'+mode)
            with closing(source_fixture.connect(self.source.database)) as db,closing(source_fixture.SupportIndex.prepare(
                    directory,db,expected,validate_segment=source_fixture.ContinuousReplay.validate_native_segment,
                    visual_lanes=geometry)) as index:
                index_path=index.path
            with closing(sqlite3.connect(index_path)) as modified:
                scope=modified.execute('SELECT scope FROM support_scope WHERE record=10').fetchone()[0]
                if mode=='omit':modified.execute("DELETE FROM scope_link WHERE scope=? AND link='a'",(scope,))
                elif mode=='amplify':modified.execute("INSERT INTO scope_link VALUES (?,'cross')",(scope,))
                else:
                    other=modified.execute('SELECT scope FROM support_scope WHERE record=11').fetchone()[0]
                    self.assertNotEqual(scope,other)
                    modified.execute('UPDATE temporal_support SET scope=? WHERE record=10',(other,))
                modified.commit()
            receipt_path=index_path.with_suffix('.json');receipt=json.loads(receipt_path.read_text())
            receipt['sha256']=hashlib.sha256(index_path.read_bytes()).hexdigest()
            receipt_path.write_text(json.dumps(receipt),encoding='utf8')
            with self.subTest(mutation=mode),closing(source_fixture.connect(self.source.database)) as db,self.assertRaises(ValueError):
                with closing(source_fixture.SupportIndex.prepare(directory,db,expected,
                        validate_segment=source_fixture.ContinuousReplay.validate_native_segment,visual_lanes=geometry)):pass

    def test_removing_far_cross_hold_changes_position_even_with_all_geometry_present(self):
        rows,geometry=self.spatial_release_rows();key=interval_key(rows[9])
        packet=dict(records=rows,phases={interval_key(row):'final' for row in rows},checkpoints={},lane_events=[],
            requests=[dict(key=key,role='final',epoch=14.5,stage=None)])
        limited={**packet,'phases':{interval_key(row):'final' for row in rows if row['Link_ID']!='cross'}}
        limited['constraint_keys']=sorted(limited['phases'])
        with CheckpointKernel(self.bridge.identity,geometry,self.bridge.settings,
                log_path=self.source.root/'missing-cross-kernel.stderr.log') as kernel:
            full=kernel.solve(packet)['states'][0];omitted=kernel.solve(limited)['states'][0]
        self.assertAlmostEqual(omitted['result']['anchor_m']-full['result']['anchor_m'],2.0,places=7)
        self.assertEqual(omitted['release'],full['release'])
        self.assertTrue(full['result']['within_storage']);self.assertTrue(omitted['result']['within_storage'])
        self.assertNotEqual(full['result']['pose'],omitted['result']['pose'])

    def release_rows(self):
        geometry=deepcopy(self.bridge.geometry);road=geometry['links'].pop('road')
        scale=6371008.8*math.pi/180
        geometry['links']={
            'a':{**deepcopy(road),'path':[[0,0],[100/scale,0]],'from_node':'start','to_node':'join','allowed_to_links':['b']},
            'b':{**deepcopy(road),'path':[[100/scale,0],[200/scale,0]],'from_node':'join','to_node':'end'}}
        geometry['occupancy_corridors']['corridors']={name:dict(link_ids=[name],represented_lanes=1) for name in ('a','b')}
        def row(vehicle,link,start,hold,end,ordinal,f0=0):
            result=self.bridge.record(vehicle,start,hold if hold is not None else end,ordinal)
            result['Link_ID']=link;result['timestamps']=[start,end]
            result['Native_Occupancy']['corridor_id']=link
            path=geometry['links'][link]['path']
            result['path']=[[path[0][0]+f0*(path[1][0]-path[0][0]),0],path[1]]
            result['Boundary_Provenance']['start_relative']=f0
            stop=end if hold is None else hold;distance=100*(1-f0)
            result['Motion_Plan']=dict(version=1,status='kinematic',distance_m=distance,
                phases=[[start,stop,0,distance/(stop-start),0]]+([] if hold is None else [[hold,end,distance,0,0]]),
                **({} if hold is None else dict(hold_start=hold,native_wait_boundary=hold)))
            result['Observed_Waits']={} if hold is None else dict(signal_red=dict(first=hold,last=end-1,
                position_evidence='queue_exit',sources=['MATSim15_QNode_native_branch']))
            return result
        rows=[row('head','a',0,1,9,1),row('front','a',1,5,10,2),row('front','b',10,None,20,100),
              row('forming','a',8,15,30,3,.95),row('held','a',9,10,30,4)]
        return rows,geometry

    def test_deferred_release_requires_convergence_before_publication(self):
        rows,geometry=self.release_rows()
        self.run_pipeline(rows,geometry,5,release=True)

    def test_release_and_recipe_mutations_cannot_become_new_trusted_inputs(self):
        rows,geometry=self.release_rows();original=CausalGraph.next_releases
        for mode in ('release_state','recipe'):
            mutated=[]
            def mutate(graph,generation):
                def alter(table,field):
                    key,payload=graph.db.execute('SELECT key,payload FROM '+table+
                        " WHERE generation=? AND payload<>'null' ORDER BY key LIMIT 1",(generation,)).fetchone()
                    value=json.loads(payload)
                    self.assertIn(field,value,'The fixture must exercise a real setback dependency')
                    value[field]+=1
                    graph.db.execute('UPDATE '+table+' SET payload=? WHERE generation=? AND key=?',
                        (json.dumps(value,separators=(',',':')),generation,key))
                    mutated.append((generation,key))
                if generation==0 and mode=='recipe':alter('recipe','previous_offset_m')
                changed=original(graph,generation)
                if generation==0 and mode=='release_state':alter('release_state','setback_m')
                return changed
            with self.subTest(table=mode),patch.object(CausalGraph,'next_releases',mutate),self.assertRaisesRegex(ValueError,'Derived .* state'):
                self.run_pipeline(rows,geometry,5,release=True,name='mutated-'+mode)
            self.assertTrue(mutated,'The adversarial mutation must actually reach the producer')

    def test_rejected_kernel_error_survives_diagnostic_write_failure(self):
        sentinel=ValueError('synthetic kernel rejection remains authoritative')
        original_capture=CausalGraph.capture_rejected_packet;original_open=Path.open;captured=[]
        def capture_with_unwritable_destination(graph,*args):
            def fail_write(path,mode='r',*other,**kwargs):
                if mode=='xb' and path.name.startswith('rejected-'):
                    raise OSError('synthetic diagnostic destination is unwritable')
                return original_open(path,mode,*other,**kwargs)
            with patch.object(Path,'open',fail_write):original_capture(graph,*args)
            captured.append(dict(graph.last_rejection_diagnostic))
        with patch.object(CheckpointKernel,'solve',side_effect=sentinel),\
                patch.object(CausalGraph,'capture_rejected_packet',capture_with_unwritable_destination):
            with self.assertRaises(ValueError) as raised:
                self.run_pipeline(deepcopy(self.bridge.records),deepcopy(self.bridge.geometry),3,name='diagnostic-io-failure')
        self.assertIs(raised.exception,sentinel,'Diagnostic I/O must never replace the actual rejection')
        self.assertEqual(len(captured),1);self.assertEqual(captured[0]['status'],'not_written')
        self.assertIn('OSError',captured[0]['reason'])
        self.assertIn('unwritable',captured[0]['reason'])


if __name__=='__main__':unittest.main()
