"""Synthetic process readers: bounded parallelism, cancellation and failures."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
import sqlite3
import time
import unittest

from simz1_replay_workers import ReplayReadPool
from simz1_replay_work import ReadWork, WorkCancelled, checkpoint, cancellable_connection


class SyntheticReplay:
    response_identity={'run_id':'synthetic','iteration':0,'source_version':'fixture'}
    def __init__(self, _): pass
    def window_bytes(self,index):
        if index == 500: raise ValueError('synthetic persistent failure')
        if index == 503: raise TimeoutError('synthetic persistent timeout')
        if index == 999:
            with sqlite3.connect(':memory:') as connection:
                cancellable_connection(connection)
                connection.execute('WITH RECURSIVE t(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM t WHERE n<1000000000) SELECT sum(n) FROM t').fetchone()
        else:
            until=time.monotonic()+.35
            while time.monotonic()<until:
                checkpoint('synthetic_cpu')
        return json.dumps(dict(index=index,pid=os.getpid())).encode()


class PreparedSyntheticReplay(SyntheticReplay):
    def __init__(self, directory, *, spatial_preparation):
        if spatial_preparation!={'verified':'parent-only-fixture'}:raise ValueError('Preparation was not transferred intact')


class SupportedSyntheticReplay(PreparedSyntheticReplay):
    def __init__(self, directory, *, spatial_preparation, queue_support_preparation):
        super().__init__(directory, spatial_preparation=spatial_preparation)
        from simz1_continuous_replay import VerifiedQueueSupport
        if (not isinstance(queue_support_preparation, VerifiedQueueSupport) or
                queue_support_preparation.get('index_sha256') != 'a'*64):
            raise ValueError('Private parent support anchor was not transferred intact')


class CheckpointedSyntheticReplay(SupportedSyntheticReplay):
    response_identity={**SyntheticReplay.response_identity,'checkpoint_library_root':'b'*64}
    def __init__(self,directory,*,spatial_preparation,queue_support_preparation,queue_checkpoint_preparation):
        super().__init__(directory,spatial_preparation=spatial_preparation,
                         queue_support_preparation=queue_support_preparation)
        from simz1_queue_checkpoint_library import VerifiedCheckpointLibrary
        if (not isinstance(queue_checkpoint_preparation,VerifiedCheckpointLibrary) or
                queue_checkpoint_preparation.get('contract',{}).get('root_digest')!='b'*64):
            raise ValueError('Private parent checkpoint anchor was not transferred intact')


class WorkerTests(unittest.TestCase):
    def test_checkpoint_root_is_bound_to_worker_identity_and_private_transfer(self):
        from simz1_continuous_replay import VerifiedQueueSupport
        from simz1_queue_checkpoint_library import VerifiedCheckpointLibrary
        pool=ReplayReadPool('.',CheckpointedSyntheticReplay.response_identity,1,CheckpointedSyntheticReplay,
            spatial_preparation={'verified':'parent-only-fixture'},
            queue_support_preparation=VerifiedQueueSupport(index_sha256='a'*64),
            queue_checkpoint_preparation=VerifiedCheckpointLibrary(contract={'root_digest':'b'*64}))
        try:
            raw,*_=pool.read('window',7,ReadWork())
            self.assertNotEqual(json.loads(gzip.decompress(raw))['pid'],os.getpid())
        finally:pool.close()

    def test_support_anchor_keeps_its_private_type_across_process_boundary(self):
        from simz1_continuous_replay import VerifiedQueueSupport
        pool = ReplayReadPool('.', SyntheticReplay.response_identity, 1, SupportedSyntheticReplay,
            spatial_preparation={'verified':'parent-only-fixture'},
            queue_support_preparation=VerifiedQueueSupport(index_sha256='a'*64))
        try:
            raw, *_ = pool.read('window', 7, ReadWork())
            row = json.loads(gzip.decompress(raw))
            self.assertEqual(row['index'], 7)
            self.assertNotEqual(row['pid'], os.getpid())
        finally:
            pool.close()

    def test_preparation_reaches_the_bounded_worker_without_altering_response_identity(self):
        pool=ReplayReadPool('.',SyntheticReplay.response_identity,1,PreparedSyntheticReplay,
                           spatial_preparation={'verified':'parent-only-fixture'})
        try:
            raw,*_=pool.read('window',7,ReadWork())
            row=json.loads(gzip.decompress(raw))
            self.assertEqual(row['index'],7)
            self.assertNotEqual(row['pid'],os.getpid())
            self.assertEqual(pool.count,1)
        finally:pool.close()

    def test_parallel_readers_cancel_sql_recover_failure_and_close(self):
        pool=ReplayReadPool('.',SyntheticReplay.response_identity,2,SyntheticReplay)
        try:
            with ThreadPoolExecutor(2) as threads:
                jobs=[threads.submit(pool.read,'window',i,ReadWork()) for i in (1,2)]
                rows=[json.loads(gzip.decompress(job.result(timeout=15)[0])) for job in jobs]
                self.assertEqual(len({row['pid'] for row in rows}),2)
                self.assertNotIn(os.getpid(),{row['pid'] for row in rows})
                work=ReadWork()
                job=threads.submit(pool.read,'window',999,work)
                deadline=time.monotonic()+10
                while not work.snapshot().get('worker_checkpoints') and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertGreater(work.snapshot().get('worker_checkpoints',0),0)
                work.cancel('synthetic_seek')
                with self.assertRaises(WorkCancelled): job.result(timeout=5)
            for index,kind in ((500,ValueError),(503,TimeoutError)):
                with self.assertRaises(kind):pool.read('window',index,ReadWork())
            raw,*_=pool.read('window',3,ReadWork())
            self.assertEqual(json.loads(gzip.decompress(raw))['index'],3)
            self.assertEqual(pool.free.qsize(),2)
            self.assertEqual(pool.summary()['max_workers'],2)
        finally:pool.close()
        self.assertTrue(pool.summary()['closed'])


if __name__=='__main__':unittest.main()
