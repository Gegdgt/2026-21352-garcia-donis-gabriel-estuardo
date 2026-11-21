"""Tiny partial-view fixtures: no real server, historical scan, or simulation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

import simz1_continuous_replay as replay_module
from simz1_continuous_replay import ContinuousReplay, RuntimeReadCache
import simz1_replay_workers as workers
from simz1_queue_context import interval_key
from simz1_window_cache import WindowCache
import test_simz1_queue_context as queue_fixtures
import test_simz1_continuous_replay as replay_fixtures

ROOT=Path(__file__).resolve().parents[1]
POLICY='partial-native-v1'


def launcher_module():
    # Reuse the staged module supplied by the isolated review runner, if any.
    if 'simz1_partial_launcher_fixture' in sys.modules:
        return sys.modules['simz1_partial_launcher_fixture']
    spec=importlib.util.spec_from_file_location('simz1_partial_launcher_fixture',ROOT/'scripts/replay/start_replay.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


class PartialWindowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=queue_fixtures.QueueContextTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.replay=self.fixture.replay(RuntimeReadCache())
        self.replay.database=self.fixture.database

    def test_partial_windows_preserve_native_evidence_and_never_resolve_support(self):
        baseline=self.replay.window(1)
        self.replay.visual_policy=POLICY
        self.replay.queue_facility_support={'fixture':'must not instantiate unindexed resolver'}
        with patch('simz1_queue_context.QueueContext.resolve',side_effect=AssertionError('no closure')), \
                patch('simz1_queue_support.SupportIndex.prepare',side_effect=AssertionError('no index')):
            for index in (1,2,1):
                current=self.replay.window(index)
                self.assertEqual(current['visual_policy'],POLICY)
                pending=current['queue_context']['by_seed'][interval_key(self.fixture.records[4])]
                self.assertIs(pending['complete'],False)
                self.assertIs(pending['body_position_available'],False)
                self.assertEqual(pending['reason'],'reconstruction_pending')
                self.assertEqual(pending['record_keys'],[])
                self.assertEqual(current['queue_context']['segments'],[])
                self.assertEqual(current['queue_context']['metrics']['sql_queries'],0)
                if index==1:
                    for key in ('segments','context_segments','trips','lane_replay','context_lane_events','signal_replay','incidents'):
                        self.assertEqual(current[key],baseline[key],key)
        self.assertEqual(hashlib.sha256(self.fixture.database.read_bytes()).hexdigest(),self.fixture.native_hash)

    def test_pending_states_do_not_certify_or_replace_moving_native_records(self):
        self.replay.visual_policy=POLICY
        current=self.replay.window(0)
        moving=self.fixture.records[1]
        self.assertIn(moving,current['segments'])
        self.assertNotIn(interval_key(moving),current['queue_context']['by_seed'])
        self.assertEqual(current['segments'][0],moving)

    def test_partial_mode_rejects_corrupt_native_record_instead_of_hiding_it(self):
        self.replay.visual_policy=POLICY
        with sqlite3.connect(self.fixture.database) as db:
            db.execute('UPDATE segments SET payload=? WHERE id=4',(b'invalid-compressed-evidence',))
        with self.assertRaisesRegex(ValueError,'SQLite corrupto'):
            self.replay.window(1)

    def test_partial_queries_cannot_mix_normal_or_other_visual_policy(self):
        query={k:[str(v)] for k,v in self.replay.identity.items()}
        self.replay.visual_policy=POLICY
        with self.assertRaisesRegex(ValueError,'politica visual'):
            self.replay.check_identity(query)
        self.replay.check_identity(dict(query,visual_policy=[POLICY]))
        with self.assertRaisesRegex(ValueError,'politica visual'):
            self.replay.check_identity(dict(query,visual_policy=['other']))
        self.replay.visual_policy=None
        with self.assertRaisesRegex(ValueError,'politica visual'):
            self.replay.check_identity(dict(query,visual_policy=[POLICY]))
        self.replay.check_identity(query)

    def test_partial_cache_namespace_cannot_reuse_normal_windows(self):
        root=Path(self.fixture.directory.name)/'cache'
        baseline=WindowCache(root,self.replay.response_identity,self.replay.manifest,version='fixture')
        self.replay.visual_policy=POLICY
        partial=WindowCache(root,self.replay.response_identity,self.replay.manifest,version='fixture')
        self.assertNotEqual(baseline.namespace,partial.namespace)

    def test_support_and_checkpoint_installation_are_disabled_only_by_explicit_mode(self):
        self.replay.visual_policy=POLICY
        with patch('simz1_queue_support.SupportIndex.prepare',side_effect=AssertionError('no source scan')):
            self.replay.prepare_queue_support()
        self.assertIsNone(self.replay.queue_support_preparation())
        self.replay.install_queue_checkpoint_library(None)
        with self.assertRaisesRegex(ValueError,'Partial visual mode'):
            self.replay.prepare_queue_support(preparation={'unverified':'receipt'})
        with self.assertRaisesRegex(ValueError,'Partial visual mode'):
            self.replay.install_queue_checkpoint_library({'unverified':'receipt'})


class PartialInitializationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=replay_fixtures.ContinuousFixture('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_constructor_keeps_native_validation_and_adds_only_partial_transport_scope(self):
        with patch('simz1_queue_support.SupportIndex.prepare',side_effect=AssertionError('no index')):
            reader=ContinuousReplay(self.fixture.output,visual_policy=POLICY)
        self.assertEqual(reader.identity,self.fixture.replay.identity)
        self.assertEqual(reader.config['continuous']['visual_policy'],POLICY)
        descriptor=reader.config['partial_visual_policy']
        self.assertEqual(descriptor['native_status'],'completed')
        self.assertEqual(descriptor['native_validation'],'valid')
        self.assertIs(descriptor['body_position_available'],False)
        self.assertIsNone(reader.queue_support_preparation())
        self.assertNotIn('checkpoint_library_root',reader.response_identity)
        self.assertNotIn('partial_visual_policy',self.fixture.replay.config)
        observed=reader.journey(self.fixture.key)
        self.assertEqual(observed['trip'],self.fixture.trip)
        self.assertEqual(observed['records'],self.fixture.replay.journey(self.fixture.key)['records'])
        self.assertEqual(observed['visual_policy'],POLICY)

    def test_constructor_rejects_config_or_native_manifest_mutation_in_partial_mode(self):
        for path in (self.fixture.output/'config.json',self.fixture.root/'run-manifest.json'):
            raw=path.read_bytes()
            try:
                path.write_bytes(raw+b' ')
                with self.subTest(path=path.name),self.assertRaises(ValueError):
                    ContinuousReplay(self.fixture.output,visual_policy=POLICY)
            finally:
                path.write_bytes(raw)

    def test_unknown_mode_or_checkpoint_plan_rejected_before_reader_initialization(self):
        import serve_simz1_continuous as server
        with patch.object(server,'ContinuousReplay',side_effect=AssertionError('must reject first')):
            with self.assertRaisesRegex(ValueError,'Unsupported'):
                server.handler_for(self.fixture.output,visual_policy='skip-validation')
            with self.assertRaisesRegex(ValueError,'checkpoint plan'):
                server.handler_for(self.fixture.output,visual_policy=POLICY,checkpoint_plan=Path('unused'))
        with self.assertRaisesRegex(ValueError,'cannot install'):
            ContinuousReplay(self.fixture.output,visual_policy=POLICY,queue_checkpoint_preparation={})

    def test_od_integrity_failure_is_not_a_partial_visual_availability(self):
        with patch('simz1_gateway_od.validated_spatial_demand',side_effect=ValueError('fixture invalid OD contract')):
            with self.assertRaisesRegex(ValueError,'invalid OD contract'):
                ContinuousReplay(self.fixture.output,visual_policy=POLICY)


class PartialDirectInitializationTests(unittest.TestCase):
    def test_direct_sqlite_constructor_and_window_never_prepare_global_support(self):
        import test_simz1_sqlite_source as direct_fixtures
        fixture=direct_fixtures.SqliteSourceTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.publish()
        output=fixture.fixture.root/'partial-continuous'
        replay_module.generate(fixture.output,output,end=960,reserve_bytes=0)
        protected=fixture.fixture.database
        before=(protected.stat().st_mtime_ns,hashlib.sha256(protected.read_bytes()).hexdigest())
        with patch('simz1_queue_context.queue_domains',return_value={'native-fixture':frozenset(('native-fixture',))}), \
                patch('simz1_queue_support.SupportIndex.prepare',side_effect=AssertionError('no global index')), \
                patch('simz1_queue_context.QueueContext.resolve',side_effect=AssertionError('no closure')), \
                patch('simz1_queue_checkpoints.CausalGraph',side_effect=AssertionError('no graph')):
            reader=ContinuousReplay(output,visual_policy=POLICY)
            self.assertEqual(reader.source_manifest['source_type'],'sqlite-direct-v1')
            data=reader.window(0)
            self.assertEqual(data['segments'],fixture.fixture.records[:2])
            self.assertEqual(data['trips'][fixture.fixture.key],fixture.fixture.trip)
        self.assertEqual(before,(protected.stat().st_mtime_ns,hashlib.sha256(protected.read_bytes()).hexdigest()))


class PartialWorkerAndLauncherTests(unittest.TestCase):
    def test_worker_initializer_propagates_visual_policy_without_support(self):
        captured={}
        identity=dict(run_id='tiny-worker',iteration=0,source_version='fixture',visual_policy=POLICY)
        def factory(directory,**kwargs):
            captured.update(kwargs)
            self.assertNotIn('queue_support_preparation',kwargs)
            self.assertNotIn('queue_checkpoint_preparation',kwargs)
            return type('Reader',(),{'response_identity':identity})()
        with patch.object(workers,'_replay',None):
            workers.initialize('.',identity,[],[],factory,None,visual_policy=POLICY)
            self.assertEqual(captured,dict(visual_policy=POLICY))
            with self.assertRaisesRegex(ValueError,'Worker de otra'):
                workers.initialize('.',dict(identity,visual_policy='other'),[],[],factory,None,visual_policy=POLICY)

    def test_process_pool_initializer_arguments_keep_mode(self):
        with patch.object(workers,'ProcessPoolExecutor') as executor:
            pool=workers.ReplayReadPool('.',{},count=1,visual_policy=POLICY)
            self.assertEqual(executor.call_args.kwargs['initargs'][-1],POLICY)
            pool.close()

    def test_partial_launcher_requires_explicit_identity_and_binds_url(self):
        launch=launcher_module()
        with self.assertRaisesRegex(ValueError,'explicit run'):
            launch.resolve_selection(ROOT,visual_policy=POLICY)
        selection=launch.Selection('run','replay','id',0,'a'*64,'explicit-run','sqlite-direct-v1',
            'b'*64,'c'*64,'d'*64,10,20,1,visual_policy=POLICY)
        self.assertIn('visual_policy=partial-native-v1',launch.viewer_url('http://127.0.0.1:1',selection))

    def test_partial_api_reuse_rejects_changed_policy_or_unverified_native_claim(self):
        launch=launcher_module()
        selection=launch.Selection('run','replay','id',0,'a'*64,'explicit-run','sqlite-direct-v1',
            'b'*64,'c'*64,'d'*64,10,20,1,visual_policy=POLICY)
        identity={key:getattr(selection,key) for key in launch.IDENTITY}
        config=dict(continuous=dict(identity,source_version='b'*64,visual_policy=POLICY,start_seconds=0,end_seconds=86400),
            replay_window=dict(start_seconds=0,end_seconds=86400),hud=dict(run_id='id',iteration=0,planned_persons=1),
            replay_source={key:getattr(selection,key) for key in ('source_type','source_manifest_sha256',
                'replay_manifest_sha256','database_sha256','database_bytes','database_mtime_ns')},
            partial_visual_policy=dict(policy=POLICY,pending_reason='reconstruction_pending',body_position_available=False,
                native_status='completed',native_validation='valid'))
        launch.validate_api_config(config,selection)
        for field,value in [('policy','other'),('native_validation','failed'),('body_position_available',True)]:
            changed=copy.deepcopy(config)
            changed['partial_visual_policy'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                launch.validate_api_config(changed,selection)
        changed=copy.deepcopy(config);changed['continuous'].pop('visual_policy')
        with self.assertRaisesRegex(ValueError,'otra politica visual'):
            launch.validate_api_config(changed,selection)


if __name__=='__main__':
    unittest.main()
