"""Checkpoint trust-boundary tests; synthetic certificates, never native runs.

These check the persisted wrapper, not the geometric correctness of its result.
The kernel/renderer equivalence tests provide that separate evidence.
"""
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import queue
import tempfile
import unittest
import zlib
from unittest.mock import patch
from types import SimpleNamespace

from simz1_queue_checkpoints import checkpoint_digest, seal_checkpoint, validate_checkpoint, encode_result_payload, decode_result_payload
from simz1_queue_checkpoint import CheckpointKernel, compact_component_packet, kernel_contract
from simz1_queue_context import encoded, interval_key
from simz1_queue_support import SCHEMA as SUPPORT_INDEX_SCHEMA


class CheckpointContractTests(unittest.TestCase):
    def setUp(self):
        self.key='["bus","journey","short-link",[5,30]]'
        self.child='["leader","previous-journey","upstream",[0,20]]'
        self.capsule=dict(schema='native-queue-phase-capsule-v1',complete=True,
            input='{}',prepared='{}',settings={},final=dict(anchor_m=1.25,turn_bounds=[]),release=None)
        self.expected=dict(identity=dict(run_id='synthetic-checkpoint',iteration=0,
            run_manifest_sha256='a'*64),source_sqlite_sha256='b'*64,index_sha256='c'*64,
            kernel_sha256='d'*64,geometry_sha256='e'*64,
            settings_sha256=hashlib.sha256(b'{}').hexdigest(),
            record_sha256=hashlib.sha256(b'{}').hexdigest(),candidate_digest='1'*64,
            graph_sha256='2'*64,generation=2,release_state_sha256='6'*64,
            key=self.key,role='final',epoch=10,stage=None,
            children=[dict(key=self.child,sha256='3'*64)],
            support_records=[dict(id=1,record_key=self.key,sha256=hashlib.sha256(b'{}').hexdigest())])

    def sealed(self,capsule=None,expected=None):
        wrapper=seal_checkpoint(self.capsule if capsule is None else capsule,
                                self.expected if expected is None else expected)
        return wrapper,checkpoint_digest(wrapper)

    def fifo(self,stage=None):
        # Deliberately synthetic geometry: this test checks trust binding only.
        stage=[100,self.key] if stage is None else stage
        capsule=deepcopy(self.capsule);capsule.pop('final')
        capsule['fifo']=[dict(epoch=10,stage=stage,result=dict(available=True,center_m=1.25,
            pose=dict(body=dict(position=[0,0],heading=0,length=13.5,width=2.5))))]
        return capsule,{**self.expected,'role':'fifo','stage':stage}

    def test_roundtrip_binds_expected_source_and_does_not_mutate_inputs(self):
        before=deepcopy((self.capsule,self.expected))
        wrapper,digest=self.sealed()
        self.assertEqual(wrapper['schema'],'native-causal-checkpoint-v1')
        self.assertIs(wrapper['complete'],True)
        self.assertEqual(validate_checkpoint(wrapper,self.expected,digest),self.capsule)
        self.assertEqual((self.capsule,self.expected),before)
        self.assertRegex(digest,r'^[0-9a-f]{64}$')

    def test_identity_iteration_and_all_source_hashes_are_exact(self):
        wrapper,digest=self.sealed()
        for field in ('source_sqlite_sha256','index_sha256','kernel_sha256','geometry_sha256',
                      'settings_sha256','record_sha256','candidate_digest','graph_sha256','release_state_sha256'):
            with self.subTest(field=field):
                other=deepcopy(self.expected);other[field]='4'*64
                with self.assertRaises(ValueError):validate_checkpoint(wrapper,other,digest)
        for field,value in (('run_id','other-run'),('iteration',1),('run_manifest_sha256','5'*64)):
            with self.subTest(field=field):
                other=deepcopy(self.expected);other['identity'][field]=value
                with self.assertRaises(ValueError):validate_checkpoint(wrapper,other,digest)

    def test_epoch_phase_key_and_fifo_stage_are_not_interchangeable(self):
        wrapper,digest=self.sealed()
        for field,value in (('key',self.child),('epoch',10.000001),('role','base'),
                            ('stage',[100,self.key]),('generation',1)):
            with self.subTest(field=field):
                other=deepcopy(self.expected);other[field]=value
                with self.assertRaises(ValueError):validate_checkpoint(wrapper,other,digest)
        fifo,expected=self.fifo()
        wrapper,digest=self.sealed(fifo,expected)
        self.assertEqual(validate_checkpoint(wrapper,expected,digest),fifo)
        for changed in ([101,self.key],[100,self.child]):
            with self.subTest(stage=changed):
                with self.assertRaises(ValueError):
                    validate_checkpoint(wrapper,{**expected,'stage':changed},digest)

    def test_self_rehashed_result_cannot_replace_independent_digest(self):
        wrapper,digest=self.sealed()
        forged=deepcopy(wrapper);forged['capsule']['final']['anchor_m']=1000
        forged['sha256']=checkpoint_digest(forged)
        with self.assertRaises(ValueError):validate_checkpoint(forged,self.expected,digest)
        # A random digest must never be treated as optional validation.
        with self.assertRaises(ValueError):validate_checkpoint(wrapper,self.expected,'0'*64)

    def test_complete_flags_and_required_phase_cannot_be_forged(self):
        wrapper,_=self.sealed()
        for name in ('wrapper_incomplete','capsule_incomplete','missing_final'):
            forged=deepcopy(wrapper)
            if name=='wrapper_incomplete':forged['complete']=False
            elif name=='capsule_incomplete':forged['capsule']['complete']=False
            else:forged['capsule'].pop('final')
            with self.subTest(case=name),self.assertRaises(ValueError):
                validate_checkpoint(forged,self.expected,checkpoint_digest(forged))
        capsule={**self.capsule,'complete':False}
        with self.assertRaises(ValueError):seal_checkpoint(capsule,self.expected)

    def test_resolved_unavailable_fifo_is_preserved_without_certifying_a_pose(self):
        fifo,expected=self.fifo()
        fifo['fifo'][0]['result']=dict(available=False,pose=None)
        wrapper,digest=self.sealed(fifo,expected)
        actual=validate_checkpoint(wrapper,expected,digest)
        self.assertEqual(actual['fifo'][0]['result'],dict(available=False,pose=None))
        forged=deepcopy(wrapper)
        forged['capsule']['fifo'][0]['result']=dict(available=True,center_m=5,pose=dict(body={}))
        with self.assertRaises(ValueError):validate_checkpoint(forged,expected,digest)
        incomplete=deepcopy(fifo);incomplete['complete']=False
        with self.assertRaises(ValueError):seal_checkpoint(incomplete,expected)

    def test_anchor_absence_requires_matching_native_geometry_epoch_and_private_parent_contract(self):
        proof=dict(schema='native-phase-absence-v1',reason='shared_upstream_without_blocking_facility',epoch=10,
            occupancy=dict(schema='native-occupancy-absence-v1',reason='native_policy_absent',
                raw_sha256=self.expected['record_sha256'],geometry_sha256=self.expected['geometry_sha256']),
            facility_support_sha256='7'*64,lane_event_sha256='8'*64)
        capsule={**deepcopy(self.capsule),'absence_proof':proof,
            'final':dict(available=False,anchor_m=None,pose=None,pose_available=False,
                         reason=proof['reason'])}
        expected={**self.expected,'absence_proof':proof}
        wrapper,digest=self.sealed(capsule,expected)
        self.assertEqual(validate_checkpoint(wrapper,expected,digest),capsule)
        for change in ('missing_contract','missing_capsule','epoch','raw','geometry','reason','anchor','pose','availability'):
            candidate=deepcopy(capsule);contract=deepcopy(expected)
            if change=='missing_contract':contract.pop('absence_proof')
            elif change=='missing_capsule':candidate.pop('absence_proof')
            elif change=='epoch':candidate['absence_proof']['epoch']=11;contract['absence_proof']['epoch']=11
            elif change in ('raw','geometry'):
                field='raw_sha256' if change=='raw' else 'geometry_sha256'
                candidate['absence_proof']['occupancy'][field]='9'*64;contract['absence_proof']['occupancy'][field]='9'*64
            elif change=='reason':candidate['absence_proof']['reason']='unreviewed';contract['absence_proof']['reason']='unreviewed'
            elif change=='anchor':candidate['final']['anchor_m']=0
            elif change=='pose':candidate['final']['pose']={}
            else:candidate['final']['available']=True
            with self.subTest(change=change),self.assertRaises(ValueError):seal_checkpoint(candidate,contract)
        forged=deepcopy(wrapper);forged['contract']['absence_proof']['lane_event_sha256']='9'*64
        forged['capsule']['absence_proof']['lane_event_sha256']='9'*64
        with self.assertRaises(ValueError):validate_checkpoint(forged,expected,digest)

    def test_interpolation_table_matches_one_exact_epoch(self):
        capsule=deepcopy(self.capsule);capsule.pop('final')
        result=dict(available=True,desired_start_m=0,desired_end_m=10,lower_m=-6,head_m=6)
        capsule['interpolate']=[dict(epoch=5,stage=None,result=result),dict(epoch=10,stage=None,result=result)]
        expected={**self.expected,'role':'interpolate'}
        wrapper,digest=self.sealed(capsule,expected)
        self.assertEqual(validate_checkpoint(wrapper,expected,digest),capsule)
        for changed in ([capsule['interpolate'][0]],capsule['interpolate']+[capsule['interpolate'][1]],
                        [dict(epoch=10,stage=[100,self.key],result=result)]):
            broken={**capsule,'interpolate':changed}
            with self.subTest(changed=changed),self.assertRaises(ValueError):seal_checkpoint(broken,expected)

    def test_projection_capsule_binds_exact_optional_stage_independently_of_fifo(self):
        result=dict(available=True,desired_start_m=0,desired_end_m=10,lower_m=-6,head_m=6)
        stages=(None,[100,self.key],[101,self.key])
        capsule={key:deepcopy(value) for key,value in self.capsule.items() if key!='final'}
        capsule['interpolate']=[dict(epoch=10,stage=stage,result=result) for stage in stages]
        for stage in stages:
            expected={**self.expected,'role':'interpolate','stage':stage}
            wrapper,digest=self.sealed(capsule,expected)
            self.assertEqual(validate_checkpoint(wrapper,expected,digest),capsule)
            for other in stages:
                if other==stage:continue
                with self.subTest(expected=stage,changed=other),self.assertRaises(ValueError):
                    validate_checkpoint(wrapper,{**expected,'stage':other},digest)
            missing=deepcopy(capsule)
            missing['interpolate']=[row for row in missing['interpolate'] if row['stage']!=stage]
            with self.assertRaises(ValueError):seal_checkpoint(missing,expected)
            forged=deepcopy(wrapper);forged['contract']['role']='fifo'
            with self.assertRaises(ValueError):validate_checkpoint(forged,expected,digest)
        for stage in ([],[True,self.key],[-1,self.key],[2**53,self.key],[100.5,self.key],[100,'']):
            with self.subTest(invalid_stage=stage),self.assertRaises(ValueError):
                seal_checkpoint(capsule,{**self.expected,'role':'interpolate','stage':stage})

    def test_missing_changed_or_duplicate_dependency_set_is_rejected(self):
        wrapper,_=self.sealed()
        for children in ([],[dict(key=self.child,sha256='9'*64)],
                         [dict(key=self.key,sha256='3'*64)]):
            with self.subTest(children=children):
                forged=deepcopy(wrapper);forged['contract']['children']=children
                with self.assertRaises(ValueError):
                    validate_checkpoint(forged,self.expected,checkpoint_digest(forged))
        duplicate=deepcopy(self.expected);duplicate['children']*=2
        with self.assertRaises(ValueError):seal_checkpoint(self.capsule,duplicate)

    def test_geometric_support_is_unique_and_covers_the_bound_native_record(self):
        own=self.expected['support_records'][0]
        for support in ([],[own,own],[{**own,'sha256':'9'*64}],
                        [{**own,'record_key':self.child}],
                        [own,{**own,'id':2}],
                        [own,dict(id=1,record_key=self.child,sha256='9'*64)]):
            with self.subTest(support=support),self.assertRaises(ValueError):
                seal_checkpoint(self.capsule,{**self.expected,'support_records':support})
        wrapper,digest=self.sealed()
        forged=deepcopy(wrapper);forged['contract']['support_records'][0]['sha256']='9'*64
        with self.assertRaises(ValueError):validate_checkpoint(forged,self.expected,checkpoint_digest(forged))
        zero='["auxiliary","other-journey","link",[10,10]]'
        support=[own,dict(id=2,record_key=zero,sha256='8'*64),dict(id=3,record_key=zero,sha256='9'*64)]
        # Native zero-duration boundary observations can share identity while
        # preserving distinct payloads; neither is an anchor or requested pose.
        expected={**self.expected,'support_records':support}
        wrapper,digest=self.sealed(expected=expected)
        self.assertEqual(validate_checkpoint(wrapper,expected,digest),self.capsule)
        self_zero={**self.expected,'key':zero,'support_records':[
            dict(id=2,record_key=zero,sha256=self.expected['record_sha256']),
            dict(id=3,record_key=zero,sha256='9'*64)]}
        with self.assertRaises(ValueError):seal_checkpoint(self.capsule,self_zero)

    def test_contract_rejects_missing_hashes_nonfinite_epochs_and_invalid_rank(self):
        for field in ('source_sqlite_sha256','index_sha256','kernel_sha256','candidate_digest','children',
                      'generation','release_state_sha256','support_records'):
            with self.subTest(missing=field):
                expected=deepcopy(self.expected);expected.pop(field)
                with self.assertRaises(ValueError):seal_checkpoint(self.capsule,expected)
        for epoch in (float('nan'),float('inf'),float('-inf'),True,'10'):
            with self.subTest(epoch=epoch),self.assertRaises(ValueError):
                seal_checkpoint(self.capsule,{**self.expected,'epoch':epoch})
        for generation in (-1,True,2.5,'2'):
            with self.subTest(generation=generation),self.assertRaises(ValueError):
                seal_checkpoint(self.capsule,{**self.expected,'generation':generation})
        for stage in ([float('inf'),self.key],[100],[-1,self.key],[True,self.key],
                      [2**53,self.key],[100.5,self.key]):
            fifo,expected=self.fifo(stage)
            with self.subTest(stage=stage),self.assertRaises(ValueError):
                seal_checkpoint(fifo,expected)

    def test_nonfinite_anchor_and_injected_nonjson_value_never_seal(self):
        for value in (float('nan'),float('inf'),float('-inf'),object()):
            capsule=deepcopy(self.capsule);capsule['final']['anchor_m']=value
            with self.subTest(value=type(value).__name__),self.assertRaises((ValueError,TypeError)):
                seal_checkpoint(capsule,self.expected)

    def test_storage_codec_preserves_the_decoded_certificate_digest(self):
        wrapper,digest=self.sealed()
        payload=encode_result_payload(wrapper)
        self.assertTrue(payload.startswith(b'QCP1'))
        decoded=decode_result_payload(payload)
        self.assertEqual(decoded,wrapper)
        self.assertEqual(checkpoint_digest(decoded),digest)
        self.assertEqual(decode_result_payload(json.dumps(wrapper)),wrapper,'explicit small TEXT fixtures remain readable')

    def test_storage_codec_rejects_corruption_trailing_bytes_and_decoded_bombs(self):
        payload=encode_result_payload(self.sealed()[0])
        corrupt=payload[:-1]+bytes([payload[-1]^255])
        for value in (b'wrong-header',payload[:-1],payload+b'trailing',corrupt):
            with self.subTest(size=len(value)),self.assertRaises((ValueError,zlib.error)):
                decode_result_payload(value)
        raw=json.dumps({'too_large':'x'*4096})
        with patch('simz1_queue_checkpoints.Limits',return_value=SimpleNamespace(max_decoded_bytes=128)):
            for value in (b'QCP1'+zlib.compress(raw.encode()),raw):
                with self.subTest(codec=type(value).__name__),self.assertRaises(ValueError):decode_result_payload(value)
            with self.assertRaises(ValueError):encode_result_payload({'too_large':'x'*4096})


class CheckpointBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='simz1-checkpoint-bridge-')
        self.addCleanup(self.temp.cleanup)
        self.identity=dict(run_id='synthetic-checkpoint-bridge',iteration=0,run_manifest_sha256='a'*64)
        self.settings=dict(gap_m=.1,lateral_clearance_m=.1,stop_line_setback_m=2)
        scale=6371008.8*math.pi/180
        self.geometry=dict(schema_version=1,available=True,links=dict(road=dict(
            path=[[0,0],[100/scale,0]],num_lanes=1,lane_width_m=3.5,opposing_lanes=0,
            offset_eligible=True,from_node='a',to_node='b',native_lanes={},allowed_to_links=[],
            movement_source='effective_car_node_adjacency',osm_tags={})),
            occupancy_corridors=dict(schema='corridor-length-v1',corridors=dict(road=dict(
                link_ids=['road'],represented_lanes=1))))
        self.records=[self.record('first',0,5,1),self.record('second',1,10,2),self.record('root',2,15,3)]
        key=interval_key(self.records[-1])
        self.packet=dict(records=self.records,phases={interval_key(row):'final' for row in self.records},
            checkpoints={},lane_events=[],requests=[dict(key=key,role=role,
                epoch=14 if role=='fifo' else 15,stage=[3,key] if role=='fifo' else None)
                for role in ('base','final','interpolate','fifo')])

    def record(self,vehicle,start,hold,ordinal):
        return dict(vehicle=vehicle,Agent_ID=vehicle,Replay_Journey_Key='journey-'+vehicle,
            Link_ID='road',timestamps=[start,50],path=self.geometry['links']['road']['path'],
            Vehicle_Type='bus',Vehicle_Dimensions=dict(length_m=12,width_m=2.5,
                source='synthetic_fixture',assumed=True),Trip=dict(Trip_ID='trip-'+vehicle),
            Native_Occupancy=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=ordinal),
            Boundary_Provenance=dict(start='entered link',end='left link',start_relative=0,end_relative=1),
            Motion_Plan=dict(version=1,status='kinematic',distance_m=100,hold_start=hold,native_wait_boundary=hold,
                phases=[[start,hold,0,100/(hold-start),0],[hold,50,100,0,0]]),
            Observed_Waits=dict(signal_red=dict(first=hold,last=49,position_evidence='queue_exit',
                sources=['MATSim15_QNode_native_branch'])))

    def kernel(self):
        return CheckpointKernel(self.identity,self.geometry,self.settings,
            log_path=Path(self.temp.name)/'kernel.stderr.log')

    def facility_proof(self,blocking_links=()):
        from simz1_queue_context import VerifiedFacilitySupport
        return VerifiedFacilitySupport(dict(schema='native-blocking-facility-support-v1',
            identity=deepcopy(self.identity),source_sqlite_sha256='b'*64,schedule_sha256='c'*64,
            reader_sha256='d'*64,blocking_links=list(blocking_links)))

    def absence_fixture(self):
        geometry=deepcopy(self.geometry)
        geometry['links']['road']['native_lanes']=dict(
            original=dict(index=None,represented_lanes=1,start_m=100,to_links=[],to_lanes=['terminal']),
            terminal=dict(index=0,represented_lanes=1,start_m=80,to_links=[],to_lanes=[]))
        record=self.record('absent',1,10,2);record.pop('Native_Occupancy');key=interval_key(record)
        packet=dict(records=[record],phases={key:'final'},checkpoints={},
            lane_events=[dict(vehicle=record['vehicle'],time=1,type='entered lane',link='road',lane='original')],
            requests=[dict(key=key,role=role,epoch=10,stage=[3,key] if role=='fifo' else None)
                      for role in ('base','final','fifo')])
        return geometry,packet

    def test_real_kernel_preserves_shared_upstream_absence_without_fabricating_a_root_pose(self):
        geometry,packet=self.absence_fixture();proof=self.facility_proof()
        with CheckpointKernel(self.identity,geometry,self.settings,log_path=Path(self.temp.name)/'absent-certified.log',
                facility_support=proof,source_sqlite_sha256='b'*64) as kernel:
            full=kernel.solve(packet)
            self.assertEqual(full['constraint_records'],0)
            self.assertEqual(full['geometry_records'],1,'The original observation must remain geometric evidence')
            for state in full['states']:
                self.assertIs(state['result']['available'],False);self.assertIsNone(state['result']['pose'])
            for state in full['states'][:2]:
                self.assertIsNone(state['result']['anchor_m']);self.assertIs(state['result']['pose_available'],False)
                self.assertEqual(state['result']['reason'],'shared_upstream_without_blocking_facility')
            self.assertEqual(full['states'][2]['result']['reason'],'native_occupancy_unavailable')
            # The private descriptor is copied at initialization, not shared as
            # a mutable policy input for subsequent geometry requests.
            proof['blocking_links'].append('road')
            self.assertEqual(kernel.facility_support['blocking_links'],[])
            self.assertEqual(kernel.solve(packet)['states'],full['states'])
            positive=deepcopy(packet)
            positive['records'][0]['Native_Occupancy']=dict(policy='corridor-length-v1',corridor_id='road',model_slot=0,ordinal=2)
            positive['requests']=positive['requests'][:2]
            self.assertTrue(all(state['result']['available'] for state in kernel.solve(positive)['states']))
        with CheckpointKernel(self.identity,geometry,self.settings,log_path=Path(self.temp.name)/'absent-no-proof.log') as kernel:
            with self.assertRaisesRegex(ValueError,'representable'):kernel.solve(packet)
            fifo=kernel.solve({**packet,'phases':{},'requests':packet['requests'][2:]})['states'][0]['result']
            self.assertEqual(fifo,dict(available=False,pose=None,reason='native_occupancy_unavailable'))
        with CheckpointKernel(self.identity,geometry,self.settings,log_path=Path(self.temp.name)/'absent-blocking.log',
                facility_support=self.facility_proof(('road',)),source_sqlite_sha256='b'*64) as kernel:
            with self.assertRaisesRegex(ValueError,'representable'):kernel.solve(packet)

    def test_real_classifier_observes_terminal_entry_before_hold_and_never_returns_a_pose(self):
        geometry,packet=self.absence_fixture();record=packet['records'][0];key=interval_key(record)
        packet['lane_events'] += [dict(vehicle=record['vehicle'],time=2,type='left lane',link='road',lane='original'),
                                  dict(vehicle=record['vehicle'],time=2,type='entered lane',link='road',lane='terminal')]
        classification={**packet,'constraint_keys':[key],
            'requests':[dict(key=key,epoch=10,role='classify',stage=None)]}
        with CheckpointKernel(self.identity,geometry,self.settings,log_path=Path(self.temp.name)/'terminal-classify.log',
                facility_support=self.facility_proof(),source_sqlite_sha256='b'*64) as kernel:
            state=kernel.classify(classification)['states'][0];value=state['classification']
            self.assertIs(value['complete'],True);self.assertIs(value['represented'],True)
            self.assertIs(value['native_entry'],True);self.assertIsNone(value['occupancy'])
            self.assertEqual(value['order_time'],2);self.assertEqual(json.loads(value['group_key']),['road',0])
            self.assertNotIn('result',state);self.assertNotIn('pose',value);self.assertNotIn('anchor_m',value)
            states=kernel.solve(packet)['states']
            self.assertTrue(all(state['result']['available'] for state in states[:2]))
            self.assertIs(states[2]['result']['available'],False)
            for state in states[:2]:self.assertEqual(json.loads(state['prepared'])['order'],2)
            incomplete_packet={**classification,'lane_events':classification['lane_events'][:1]}
            partial=kernel.classify(incomplete_packet)['states'][0]['classification']
            self.assertIs(partial['represented'],False)
            self.assertNotEqual(partial,value,'Omitting the intermediate terminal event changes the observed branch')
            self.assertEqual(kernel.classify(classification)['states'][0]['classification'],value,
                'A previous shared-upstream classification cannot poison a later complete timeline')
            self.assertEqual(kernel.classification_calls,3)
        with CheckpointKernel(self.identity,geometry,self.settings,log_path=Path(self.temp.name)/'terminal-unknown.log',
                source_sqlite_sha256='b'*64) as kernel:
            unknown=kernel.classify(incomplete_packet)['states'][0]['classification']
            self.assertIs(unknown['complete'],False)

    def test_classifier_rejects_pose_requests_unknown_coverage_and_expanded_budget(self):
        key=interval_key(self.records[-1]);request=dict(key=key,epoch=15,role='classify',stage=None)
        packet={**self.packet,'requests':[request]}
        bad=[{**packet,'checkpoints':{key:{}}},{**packet,'external_pass':True},
             {**packet,'records':[self.records[0]]*513},
             {**packet,'requests':[request,request]},
             {**packet,'requests':[{**request,'role':'final'}]},
             {**packet,'requests':[{**request,'stage':[3,key]}]},
             {**packet,'requests':[{**request,'epoch':50}]},
             {**packet,'constraint_keys':[key]},
             {**packet,'phases':{key:'base'}}]
        with self.kernel() as kernel:
            for value in bad:
                with self.subTest(packet=value),self.assertRaises(ValueError):kernel.classify(value)
            self.assertEqual(kernel.calls,0)
            # A different in-interval epoch still cannot stand in for the
            # source record's own queueHoldTime in the production helper.
            with self.assertRaises(ValueError):kernel.classify({**packet,'requests':[{**request,'epoch':14}]})
            old=kernel.max_decoded_bytes;kernel.max_decoded_bytes=128
            try:
                with self.assertRaisesRegex(ValueError,'expanded'):kernel.classify(packet)
            finally:kernel.max_decoded_bytes=old
            self.assertEqual(kernel.classify(packet)['status'],'classified')
        compact,expanded=compact_component_packet(packet,operation='classify')
        self.assertEqual(compact['op'],'classify')
        self.assertGreater(expanded,0)

    def test_classifier_metadata_requires_exact_identity_finite_order_and_native_group(self):
        kernel=object.__new__(CheckpointKernel);kernel.max_records=512;kernel.calls=kernel.classification_calls=0
        kernel.max_decoded_bytes=64*1024**2;kernel.max_expanded_request_bytes=0
        key=interval_key(self.records[-1]);request=dict(key=key,epoch=15,role='classify',stage=None)
        classification=dict(complete=True,represented=True,eligible=True,group_key='["road",0]',order_time=2,
            hold=15,start=2,end=50,native_entry=True,occupancy=None,departure=None,departure_complete=True,reason=None)
        original={**request,'input':'{}','classification':classification}
        mutations=[{'key':interval_key(self.records[0])},{'epoch':14},{'role':'final'},{'stage':[3,key]},
                   {'result':dict(available=True,anchor_m=0)}]
        for changes in ({'complete':1},{'group_key':None},{'order_time':None},{'order_time':float('nan')},
                        {'start':1},{'pose':{}},{'group_key':'["road",true]'},{'group_key':['road',0]},
                        {'departure_complete':False},{'departure_complete':1},
                        {'occupancy':dict(corridor='road',slot=0,ordinal=3)},
                        {'departure':dict(corridor='road',slot=0,ordinal=-1)}):
            mutations.append({'classification':{**classification,**changes}})
        for changes in mutations:
            state={**original,**changes}
            kernel._exchange=lambda packet,state=state:dict(op='classify',status='classified',states=[state],pose_requests=0)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                kernel.classify({**self.packet,'requests':[request]})
        for poses in (None,False,1):
            kernel._exchange=lambda packet,poses=poses:dict(op='classify',status='classified',states=[original],pose_requests=poses)
            with self.subTest(pose_requests=poses),self.assertRaises(ValueError):
                kernel.classify({**self.packet,'requests':[request]})
        kernel._exchange=lambda packet:dict(op='classify',status='classified',states=[original],pose_requests=0)
        self.assertEqual(kernel.classify({**self.packet,'requests':[request]})['states'],[original])

    def test_inactive_classification_cannot_hide_a_hold_or_native_reservation(self):
        record=self.record('moving-without-anchor',1,10,2)
        record['Motion_Plan']=dict(version=1,status='kinematic',distance_m=100,phases=[[1,50,0,100/49,0]])
        record['Observed_Waits']={};record['Native_Occupancy']['model_slot']=2
        key=interval_key(record);request=dict(key=key,epoch=1,role='classify',stage=None)
        packet=dict(records=[record],lane_events=[],phases={key:'final'},checkpoints={},requests=[request])
        with self.kernel() as kernel:
            original=kernel.classify(packet)['states'][0]
            value=original['classification']
            self.assertEqual(value['reason'],'inactive_context_without_occupancy_or_hold')
            self.assertIs(value['complete'],True);self.assertIs(value['represented'],False)
            self.assertIs(value['eligible'],False);self.assertIsNone(value['hold']);self.assertIsNone(value['occupancy'])
            self.assertNotIn('pose',value)
            native=deepcopy(record);native['Native_Occupancy']['model_slot']=0
            preserved=kernel.classify({**packet,'records':[native]})['states'][0]['classification']
            self.assertTrue(preserved['represented']);self.assertIsNotNone(preserved['occupancy'])
            self.assertNotEqual(preserved['reason'],value['reason'])
            held=self.record('moving-without-anchor',1,10,2);held['Native_Occupancy']['model_slot']=2
            # A source HOLD keeps its own epoch and cannot be silently replaced
            # by a classifier result from the moving observation's start.
            with self.assertRaises(ValueError):kernel.classify({**packet,'records':[held]})
        stub=object.__new__(CheckpointKernel);stub.max_records=512;stub.calls=stub.classification_calls=0
        stub.max_decoded_bytes=64*1024**2;stub.max_expanded_request_bytes=0
        changes=({'complete':False},{'represented':True},{'eligible':True},{'hold':10},
                 {'native_entry':True},{'order_time':1},{'group_key':'["road",0]'},
                 {'occupancy':dict(corridor='road',slot=0,ordinal=2),'departure_complete':False})
        for change in changes:
            forged={**original,'classification':{**value,**change}}
            stub._exchange=lambda packet,forged=forged:dict(op='classify',status='classified',states=[forged],pose_requests=0)
            with self.subTest(change=change),self.assertRaises(ValueError):stub.classify(packet)

    def test_facility_support_requires_private_authority_and_independent_native_source(self):
        from simz1_queue_context import VerifiedFacilitySupport
        proof=self.facility_proof(('a','z'))
        source=dict(schema=SUPPORT_INDEX_SCHEMA,identity=self.identity,database_sha256='b'*64,
            geometry_sha256=hashlib.sha256(encoded(self.geometry)).hexdigest())
        plain=kernel_contract(source,'a'*64,self.geometry,self.settings)
        self.assertNotIn('facility_support',plain)
        certified=kernel_contract(source,'a'*64,self.geometry,self.settings,facility_support=proof)
        self.assertEqual(certified['facility_support'],dict(proof))
        variants=[dict(proof)]  # A reopened JSON descriptor has no authority.
        for field,value in (('schema','unreviewed'),('source_sqlite_sha256','e'*64),
                            ('schedule_sha256','not-a-sha'),('reader_sha256','G'*64),
                            ('blocking_links',['z','a']),('blocking_links',['a','a']),
                            ('blocking_links',['']),('blocking_links','a')):
            variants.append(VerifiedFacilitySupport({**deepcopy(dict(proof)),field:value}))
        for field,value in (('run_id','foreign'),('iteration',1),('run_manifest_sha256','f'*64)):
            changed=deepcopy(dict(proof));changed['identity'][field]=value
            variants.append(VerifiedFacilitySupport(changed))
        for value in variants:
            with self.subTest(proof=value):
                with self.assertRaises(ValueError):
                    kernel_contract(source,'a'*64,self.geometry,self.settings,facility_support=value)
                with patch('simz1_queue_checkpoint.subprocess.Popen') as launch:
                    with self.assertRaises(ValueError):
                        CheckpointKernel(self.identity,self.geometry,self.settings,
                            log_path=Path(self.temp.name)/'rejected.stderr.log',
                            facility_support=value,source_sqlite_sha256='b'*64)
                    launch.assert_not_called()
        for missing_or_changed in (None,'e'*64,'invalid'):
            with self.subTest(expected_source=missing_or_changed),self.assertRaises(ValueError):
                CheckpointKernel(self.identity,self.geometry,self.settings,
                    log_path=Path(self.temp.name)/'source-rejected.stderr.log',
                    facility_support=proof,source_sqlite_sha256=missing_or_changed)
        altered=self.facility_proof(('a',))
        self.assertNotEqual(certified,kernel_contract(source,'a'*64,self.geometry,self.settings,facility_support=altered))

    def test_bridge_never_promotes_certified_absence_to_an_anchor_or_pose(self):
        kernel=object.__new__(CheckpointKernel);kernel.max_records=512;kernel.calls=0
        kernel.max_decoded_bytes=64*1024**2;kernel.max_expanded_request_bytes=0
        proof=dict(self.facility_proof());kernel.facility_support=proof
        request=self.packet['requests'][0]
        absence=dict(available=False,anchor_m=None,pose=None,pose_available=False,
            reason='shared_upstream_without_blocking_facility')
        kernel._exchange=lambda packet:dict(states=[{**request,'result':absence}])
        self.assertEqual(kernel.solve({**self.packet,'requests':[request]})['states'][0]['result'],absence)
        for change in ({'anchor_m':0},{'pose':{}},{'pose_available':True},{'reason':'unknown'},
                       {'anchor_m':'missing'},{'pose':'missing'}):
            value={**absence,**change}
            for field in ('anchor_m','pose'):
                if value[field]=='missing':value.pop(field)
            kernel._exchange=lambda packet,value=value:dict(states=[{**request,'result':value}])
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'absence'):
                kernel.solve({**self.packet,'requests':[request]})
        kernel._exchange=lambda packet:dict(states=[{**request,'result':absence}])
        for support in (None,{**proof,'blocking_links':['road']}):
            kernel.facility_support=support
            with self.subTest(support=support),self.assertRaisesRegex(ValueError,'absence'):
                kernel.solve({**self.packet,'requests':[request]})

    def test_real_kernel_reuses_capsule_with_identical_phase_results(self):
        original=deepcopy(self.packet)
        with self.kernel() as kernel:
            full=kernel.solve(self.packet)
            states={row['role']:row for row in full['states']}
            for row in states.values():self.assertIs(row['result']['available'],True)
            key=self.packet['requests'][0]['key']
            capsule=dict(schema='native-queue-phase-capsule-v1',complete=True,
                input=states['base']['input'],prepared=states['base']['prepared'],settings=self.settings,
                base=states['base']['result'],final=states['final']['result'],release=states['base']['release'],
                fifo=[dict(epoch=14,stage=[3,key],result=states['fifo']['result'])])
            bounded={**self.packet,'records':[self.records[-1]],'phases':{key:'final'},'checkpoints':{key:capsule}}
            result=kernel.solve(bounded)
            for before,after in zip(full['states'],result['states']):
                self.assertEqual(after,before,'The bridge must preserve all phase identities, bounds and poses')
            self.assertLessEqual(kernel.max_request_bytes,64*1024**2)
            self.assertLessEqual(kernel.max_response_bytes,64*1024**2)
            self.assertEqual(kernel.calls,2)
        self.assertIsNone(kernel.process)
        self.assertEqual(self.packet,original)

    def test_real_kernel_rejects_record_budget_and_invalid_stage(self):
        with self.kernel() as kernel:
            with self.assertRaisesRegex(ValueError,'record limit'):
                kernel.solve({**self.packet,'records':[self.records[0]]*513})
            for role,stage in (('fifo',None),('fifo',[1]),('fifo',['bad','key']),('base',[3,'key'])):
                request={**self.packet['requests'][0],'role':role,'stage':stage}
                with self.subTest(role=role,stage=stage),self.assertRaises(ValueError):
                    kernel.solve({**self.packet,'requests':[request]})
            # Rejection must leave the same owned helper usable.
            self.assertEqual(kernel.solve(self.packet)['status'],'resolved')

    def test_projection_stage_transports_exact_rank_without_turning_interpolation_into_fifo(self):
        key=interval_key(self.records[-1])
        requests=[dict(key=key,role='interpolate',epoch=14,stage=stage)
            for stage in (None,[3,key],[4,key])]
        with self.kernel() as kernel:
            states=kernel.solve({**self.packet,'requests':requests})['states']
        for request,state in zip(requests,states):
            self.assertEqual(state['stage'],request['stage'])
            self.assertEqual(state['role'],'interpolate')
        # Stage selects the trace's BASE/FINAL endpoint, never FIFO clamping of
        # the projection centre. The real JS consumer tests cover differing ends.
        self.assertEqual(len({state['result']['center_m'] for state in states}),1)

    def test_projection_rejects_missing_malformed_or_unreviewed_stages(self):
        key=interval_key(self.records[-1]);base=dict(key=key,role='interpolate',epoch=14,stage=None)
        malformed=[{name:value for name,value in base.items() if name!='stage'},
            {**base,'role':'project'},
            *[{**base,'stage':stage} for stage in ('none',[],[1],[1,key,'extra'],[True,key],[1.5,key],
                [-1,key],[9007199254740992,key],[1,'not-json'],[1,'[]'],[1,''])]]
        with self.kernel() as kernel:
            for request in malformed:
                with self.subTest(request=request),self.assertRaises(ValueError):
                    kernel.solve({**self.packet,'requests':[request]})
            self.assertEqual(kernel.calls,0)

    def test_projection_response_cannot_change_its_evaluation_stage(self):
        kernel=object.__new__(CheckpointKernel);kernel.max_records=512;kernel.calls=0
        kernel.max_decoded_bytes=64*1024**2;kernel.max_expanded_request_bytes=0
        key=interval_key(self.records[-1]);request=dict(key=key,role='interpolate',epoch=14,stage=[3,key])
        for replacement in (None,[4,key],[3,interval_key(self.records[0])]):
            state={**request,'stage':replacement,'result':dict(available=True,center_m=1)}
            kernel._exchange=lambda packet,state=state:dict(states=[state])
            with self.subTest(replacement=replacement),self.assertRaisesRegex(ValueError,'changed state identity'):
                kernel.solve({**self.packet,'requests':[request]})

    def test_causal_constraint_roster_requires_exact_phase_request_and_capsule_union(self):
        keys=[interval_key(row) for row in self.records]
        with self.kernel() as kernel:
            full=kernel.solve(self.packet)
            constrained=kernel.solve({**self.packet,'constraint_keys':list(reversed(keys))})
            self.assertEqual(constrained['states'],full['states'])
            extra=self.record('auxiliary',3,20,4);extra_key=interval_key(extra)
            rejected=[
                dict(constraint_keys=keys[:-1]),
                dict(constraint_keys=keys[1:]),
                dict(constraint_keys=keys+[keys[0]]),
                dict(constraint_keys=keys+[json.dumps(json.loads(keys[0]),indent=1)]),
                dict(constraint_keys=keys+[extra_key]),
                dict(records=self.records+[extra],constraint_keys=keys+[extra_key]),
                dict(phases={keys[-1]:'final'},checkpoints={keys[0]:{}},constraint_keys=[keys[-1]]),
                dict(constraint_keys='not-a-list'),
            ]
            zero=deepcopy(extra);zero['timestamps']=[20,20];zero_key=interval_key(zero)
            rejected.append(dict(records=self.records+[zero],phases={**self.packet['phases'],zero_key:'base'},
                                 constraint_keys=keys+[zero_key]))
            for changes in rejected:
                with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'[Cc]ausal'):
                    kernel.solve({**self.packet,**changes})
            self.assertEqual(kernel.calls,2,'Rejected membership cannot be sent to the geometry helper')
            self.assertEqual(kernel.solve({**self.packet,'constraint_keys':keys})['states'],full['states'])

    def test_kernel_contract_pins_all_executed_sources_and_geometry(self):
        source=dict(schema=SUPPORT_INDEX_SCHEMA,geometry_sha256=hashlib.sha256(encoded(self.geometry)).hexdigest())
        contract=kernel_contract(source,'a'*64,self.geometry,self.settings)
        required={'simz1_queue_checkpoint.cjs','simz1_visual_queues.js','simz1_visual_lanes.js',
                  'simz1_queue_checkpoint.py','simz1_continuous_loader.js','visualizador_z1_controls.js'}
        self.assertTrue(required.issubset(contract['kernels']))
        changed=deepcopy(self.geometry);changed['links']['road']['lane_width_m']=3.6
        with self.assertRaises(ValueError):kernel_contract(source,'a'*64,changed,self.settings)

    def test_finite_anchor_outside_storage_does_not_certify_a_pose(self):
        # Two 12 m bodies cannot fit in this 2 m isolated domain. The second
        # anchor is a valid scalar constraint, but must not become a pose.
        self.geometry['links']['road']['path'][1][0]/=50
        records=[self.records[0],self.records[-1]]
        for row in records:
            start,hold=row['timestamps'][0],row['Motion_Plan']['hold_start']
            row['Motion_Plan']['distance_m']=2
            row['Motion_Plan']['phases']=[[start,hold,0,2/(hold-start),0],[hold,50,2,0,0]]
        key=interval_key(records[-1])
        packet=dict(records=records,phases={interval_key(row):'final' for row in records},
            checkpoints={},lane_events=[],requests=[dict(key=key,role='final',epoch=15,stage=None)])
        with self.kernel() as kernel:state=kernel.solve(packet)['states'][0]
        result=state['result']
        self.assertTrue(math.isfinite(result['anchor_m']))
        self.assertLess(result['anchor_m'],result['lower_m'])
        self.assertIs(result['within_storage'],False)
        self.assertIs(result['pose_available'],False)
        self.assertIsNone(result['pose'])

    def test_bridge_rejects_nonfinite_protocol_and_changed_state_identity(self):
        for token in ('NaN','Infinity','1e999'):
            kernel=object.__new__(CheckpointKernel)
            kernel.max_decoded_bytes=64*1024**2;kernel.max_request_bytes=kernel.max_response_bytes=0
            kernel.timeout=1;kernel.process=SimpleNamespace(stdin=io.BytesIO())
            kernel.responses=queue.Queue();kernel.responses.put(('{"result":'+token+'}\n').encode())
            with self.subTest(token=token),self.assertRaises(ValueError):kernel._exchange({'op':'solve'})
        kernel=object.__new__(CheckpointKernel);kernel.max_records=512;kernel.calls=0
        kernel.max_decoded_bytes=64*1024**2;kernel.max_expanded_request_bytes=0
        request=self.packet['requests'][0]
        for state in ({**request,'key':'other','result':{'available':True}},
                      {**request,'epoch':16,'result':{'available':True}},
                      {**request,'result':{}}):
            kernel._exchange=lambda packet,state=state:dict(states=[state])
            with self.subTest(state=state),self.assertRaises(ValueError):
                kernel.solve({**self.packet,'requests':[request]})


if __name__=='__main__':unittest.main()
