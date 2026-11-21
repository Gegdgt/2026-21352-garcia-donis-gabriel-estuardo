"""Exercise sealed support through the real window reader on tiny native fixtures."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simz1_continuous_replay import RuntimeReadCache, VerifiedQueueSupport
from simz1_queue_context import interval_key, queue_domains
import test_simz1_queue_context as fixture_module


class SupportWindowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.QueueContextTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = Path(self.fixture.directory.name)
        geometry = self.fixture.native_geometry()
        geometry['links']['upstream'] = self.fixture.geometry_link('u', 'a', x=-.0001)
        geometry['occupancy_corridors']['corridors']['upstream'] = dict(
            link_ids=['upstream'], represented_lanes=1)
        self.replay = self.fixture.replay(RuntimeReadCache())
        self.replay.config = dict(visual_lanes=geometry)
        self.replay.database = self.fixture.database
        self.replay.source_manifest['database_sha256'] = self.fixture.native_hash
        self.replay.queue_domains = queue_domains(geometry)
        self.replay.prepare_queue_support(self.root/'external-support')

    def test_cold_forward_reverse_windows_preserve_complete_native_context(self):
        key = interval_key(self.fixture.records[4])
        first = self.replay.window(1)['queue_context']
        self.assertTrue(first['by_seed'][key]['complete'])
        for index in (2, 1, 2):
            other = self.replay.window(index)['queue_context']
            self.assertEqual(first['by_seed'][key], other['by_seed'][key])
            for field in ('segments', 'transition_segments', 'trips', 'lane_events'):
                self.assertEqual(first[field], other[field])
        self.assertEqual(hashlib.sha256(self.fixture.database.read_bytes()).hexdigest(), self.fixture.native_hash)

    def test_worker_reuse_does_not_rescan_source_records(self):
        target = self.replay.queue_support_path
        preparation = self.replay.queue_support_preparation()
        with patch.object(self.replay, 'validate_native_segment', side_effect=AssertionError('unexpected source scan')):
            self.replay.prepare_queue_support(self.root/'external-support', preparation)
        self.assertEqual(self.replay.queue_support_path, target)
        self.assertTrue(self.replay.window(1)['queue_context']['by_seed'][interval_key(self.fixture.records[4])]['complete'])

    def test_unverified_serialized_descriptor_cannot_replace_the_parent_anchor(self):
        preparation = self.replay.queue_support_preparation()
        with self.assertRaisesRegex(ValueError, 'private verified parent anchor'):
            self.replay.prepare_queue_support(self.root/'external-support', dict(preparation))
        bad = VerifiedQueueSupport(preparation)
        bad['index_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            self.replay.prepare_queue_support(self.root/'external-support', bad)

    def test_window_rejects_mutated_or_incomplete_index_before_certifying_pose(self):
        receipt = self.replay.queue_support_path.with_suffix('.json')
        raw = receipt.read_bytes()
        value = json.loads(raw)
        for change in (dict(complete=False), dict(sha256='0'*64)):
            with self.subTest(change=change):
                receipt.write_text(json.dumps(dict(value, **change)), encoding='utf8')
                with self.assertRaises(ValueError):
                    self.replay.window(1)
        receipt.write_bytes(raw)
        value['contract']['identity']['iteration'] = 1
        receipt.write_text(json.dumps(value), encoding='utf8')
        with self.assertRaises(ValueError):
            self.replay.window(1)

    def test_support_connections_are_not_shared_across_window_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        key = interval_key(self.fixture.records[4])
        with ThreadPoolExecutor(max_workers=2) as pool:
            payloads = list(pool.map(self.replay.window, (1, 2)))
        self.assertEqual(payloads[0]['queue_context']['by_seed'][key], payloads[1]['queue_context']['by_seed'][key])

    def test_checkpoint_installation_rejects_untrusted_json_descriptor(self):
        with self.assertRaisesRegex(ValueError,'verified parent'):
            self.replay.install_queue_checkpoint_library(dict(path='untrusted.sqlite',contract={}))
        self.assertIsNone(self.replay.queue_checkpoint_preparation)
        self.assertNotIn('checkpoint_library_root',self.replay.response_identity)

    def test_context_aggregation_cannot_mix_verified_library_roots(self):
        from simz1_queue_context import QueueContext
        with closing(self.replay.connection()) as connection:
            baseline=QueueContext(connection,self.replay.blocks,
                validate_segment=self.replay.validate_native_segment,validate_trip=lambda trip:None)
            class DistinctFixtureLibraries:
                # Contract-only injection: verifies the aggregator guard, not
                # checkpoint geometry or authentication (separate suites).
                def resolved_seed(inner,context,ident,record):
                    result=baseline.seed(ident,record)
                    result['checkpoints']={interval_key(record):{'fixture':ident}}
                    result['checkpoint_contract']={'root_digest':str(ident)}
                    return result
            resolver=QueueContext(connection,self.replay.blocks,
                validate_segment=self.replay.validate_native_segment,validate_trip=lambda trip:None,
                checkpoint_library=DistinctFixtureLibraries())
            with self.assertRaises(ValueError):
                resolver.resolve([(3,self.fixture.records[3]),(4,self.fixture.records[4])])


class FacilityScopeIntegrationTests(unittest.TestCase):
    def setUp(self):
        from simz1_continuous_replay import prepare_facility_support
        self.prepare=prepare_facility_support
        temporary=tempfile.TemporaryDirectory(prefix='simz1-facility-scope-')
        self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)
        self.schedule=self.directory/'schedule.xml'
        self.schedule.write_text('<transitSchedule><transitStops>'
            '<stopFacility id="ordinary" linkRefId="a" isBlocking="false"/>'
            '<stopFacility id="off-display" linkRefId="c" isBlocking="true"/>'
            '<stopFacility id="blocking" linkRefId="b" isBlocking="true"/>'
            '</transitStops></transitSchedule>',encoding='utf8')
        self.manifest=dict(run_id='fixture-facility-scope',status='completed',validation=dict(status='valid'),
            results={'0':{}},inputs={'transit_schedule':dict(path='schedule.xml',
                sha256=hashlib.sha256(self.schedule.read_bytes()).hexdigest())})
        self.pin()

    def pin(self):
        raw=json.dumps(self.manifest).encode()
        (self.directory/'run-manifest.json').write_bytes(raw)
        self.identity=dict(run_id=self.manifest['run_id'],iteration=0,
            run_manifest_sha256=hashlib.sha256(raw).hexdigest())

    def test_complete_schedule_scope_includes_facilities_outside_display_selection(self):
        from simz1_queue_context import VerifiedFacilitySupport
        proof=self.prepare(self.directory,self.manifest,self.identity,'a'*64)
        self.assertIsInstance(proof,VerifiedFacilitySupport)
        self.assertEqual(proof['blocking_links'],['b','c'])
        self.assertEqual(proof['schedule_sha256'],self.manifest['inputs']['transit_schedule']['sha256'])
        self.assertEqual(proof['source_sqlite_sha256'],'a'*64)
        self.assertEqual(proof['identity'],self.identity)

    def test_scope_rejects_mutated_schedule_foreign_manifest_and_iteration(self):
        with self.assertRaises(ValueError):
            self.prepare(self.directory,self.manifest,dict(self.identity,iteration=1),'a'*64)
        with self.assertRaises(ValueError):
            self.prepare(self.directory,dict(self.manifest,run_id='other'),self.identity,'a'*64)
        self.schedule.write_bytes(self.schedule.read_bytes().replace(b'linkRefId="c"',b'linkRefId="d"'))
        with self.assertRaisesRegex(ValueError,'Hash'):
            self.prepare(self.directory,self.manifest,self.identity,'a'*64)

    def test_missing_schedule_does_not_become_proof_of_no_stops(self):
        self.manifest['inputs']={};self.pin()
        self.assertIsNone(self.prepare(self.directory,self.manifest,self.identity,'a'*64))

    def test_duplicate_facilities_rejected_even_with_new_valid_artifact_hash(self):
        self.schedule.write_bytes(self.schedule.read_bytes().replace(b'id="off-display"',b'id="ordinary"'))
        self.manifest['inputs']['transit_schedule']['sha256']=hashlib.sha256(self.schedule.read_bytes()).hexdigest()
        self.pin()
        with self.assertRaisesRegex(ValueError,'unambiguous'):
            self.prepare(self.directory,self.manifest,self.identity,'a'*64)

    def test_metadata_cannot_add_an_unlisted_blocking_link(self):
        from simz1_continuous_replay import ContinuousReplay
        from simz1_transit_replay import transit_trip_id
        replay=object.__new__(ContinuousReplay)
        replay.native_run=dict(self.manifest)
        replay.native_run['inputs']=dict(self.manifest['inputs'],transit_vehicles={'sha256':'b'*64})
        replay.queue_facility_support=self.prepare(self.directory,self.manifest,self.identity,'a'*64)
        transit=dict(schema='simz1-transit-replay-v1',vehicle_id='bus',driver_id='driver',line_id='line',
            route_id='route',departure_id='d',domain_scope='synthetic_fixture',route_links=['a','b','c'],
            source=dict(schedule_sha256=self.manifest['inputs']['transit_schedule']['sha256'],vehicles_sha256='b'*64),
            activity_intervals=[dict(start=0,end=1,state='stop',source='native_facility_events',
                link_id='b',is_blocking_lane=True)])
        trip=dict(Person_ID=None,Driver_ID='driver',Trip_ID=transit_trip_id('bus','line','route','d'),Transit=transit)
        replay.validate_spatial_trip(trip)
        transit['activity_intervals'][0]['link_id']='a'
        with self.assertRaisesRegex(ValueError,'complete pinned native facility scope'):
            replay.validate_spatial_trip(trip)


if __name__ == '__main__':
    unittest.main()
