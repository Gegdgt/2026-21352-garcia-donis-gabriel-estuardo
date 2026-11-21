"""Two bounded CPU readers for immutable replay data, with cooperative aborts.

Threads share Python's interpreter lock: running two speculative SQL/JSON
builds in threads did not provide two readers' processing throughput. Workers
own read-only connections/caches. They never generate or edit source data.
"""
from concurrent.futures import ProcessPoolExecutor, TimeoutError
import gzip
import hashlib
import json
import multiprocessing
import os
import queue
import threading
import time

from simz1_replay_work import ReadWork, WorkCancelled, work_scope


_replay = _cancels = _progress = None


def initialize(directory, identity, cancels, progress, factory, version, spatial_preparation=None,
               queue_support_preparation=None, queue_checkpoint_preparation=None, visual_policy=None):
    global _replay, _cancels, _progress
    _cancels, _progress = cancels, progress
    if version is not None:
        from simz1_window_cache import reader_version
        if reader_version()!=version:raise ValueError('Los lectores cambiaron: reinicie el servidor del replay')
    preparations = {}
    if visual_policy is not None:
        from simz1_continuous_replay import checked_visual_policy
        preparations['visual_policy']=checked_visual_policy(visual_policy)
    if spatial_preparation is not None:
        preparations['spatial_preparation'] = spatial_preparation
    if queue_support_preparation is not None:
        preparations['queue_support_preparation'] = queue_support_preparation
    if queue_checkpoint_preparation is not None:
        preparations['queue_checkpoint_preparation'] = queue_checkpoint_preparation
    _replay = factory(directory, **preparations)
    if _replay.response_identity != identity:
        raise ValueError('Worker de otra corrida, iteracion o fuente')


def build(slot, kind, argument):
    def report(snapshot):
        raw=json.dumps(dict(observed_at=time.monotonic(), **snapshot)).encode('utf-8')
        if len(raw) < len(_progress[slot]):
            _progress[slot].value=raw
    work=ReadWork(_cancels[slot].is_set, observer=report)
    started=time.perf_counter()
    with work_scope(work):
        work.check('worker_build')
        if kind == 'window':
            raw=_replay.window_bytes(argument)
        elif kind == 'journey':
            from simz1_continuous_replay import json_bytes
            raw=json_bytes(_replay.journey(argument))
        else:
            raise ValueError('Operacion de lector desconocida')
        work.check('worker_encoding')
        assembled=time.perf_counter()
        compressed=gzip.compress(raw, compresslevel=1, mtime=0)
        digest=hashlib.sha256(raw).hexdigest()
        work.check('worker_complete')
        caches={name: getattr(_replay,name).summary() for name in (
            'lookup_cache','temporal_cache','queue_context_cache','queue_record_cache',
            'queue_seed_cache','queue_dependency_cache','queue_index_cache') if hasattr(_replay,name)}
        return (compressed,len(raw),dict(build_ms=(assembled-started)*1000,
                gzip_ms=(time.perf_counter()-assembled)*1000),digest,os.getpid(),caches)


class ReplayReadPool:
    def __init__(self, directory, identity, count=2, factory=None, version=None, spatial_preparation=None,
                 queue_support_preparation=None, queue_checkpoint_preparation=None, visual_policy=None):
        if factory is None:
            from simz1_continuous_replay import ContinuousReplay
            factory=ContinuousReplay
        context=multiprocessing.get_context('spawn')
        self.cancels=[context.Event() for _ in range(count)]
        self.progress=[context.Array('c',16384) for _ in range(count)]
        self.free=queue.Queue(count)
        for slot in range(count): self.free.put(slot)
        self.pool=ProcessPoolExecutor(count,mp_context=context,initializer=initialize,
            initargs=(str(directory),identity,self.cancels,self.progress,factory,version,
                      spatial_preparation,queue_support_preparation,queue_checkpoint_preparation,visual_policy))
        self.count=count
        self.workers={}
        self.lock=threading.Lock()
        self.closed=False

    def read(self, kind, argument, work):
        slot=self.free.get_nowait()  # Server admission owns the same bound.
        flag=self.cancels[slot]
        flag.clear()
        self.progress[slot].value=b''
        future=None
        try:
            with self.lock:
                if self.closed: raise WorkCancelled('server_closed')
                future=self.pool.submit(build,slot,kind,argument)
            while True:
                status=self.progress[slot].value
                if status:
                    snapshot=json.loads(status)
                    work.check('worker:'+snapshot['phase'],worker_checkpoints=snapshot['checkpoints'],
                        worker_progress_age_seconds=time.monotonic()-snapshot['observed_at']+
                        snapshot['last_progress_age_seconds'])
                else:
                    work.check('worker_starting')
                try:
                    result=future.result(timeout=.05)
                    with self.lock:
                        self.workers[result[4]]=result[5]
                    return result[:4]
                except TimeoutError:
                    if future.done(): raise
                    continue
        except BaseException:
            flag.set()
            if future is not None:
                future.cancel()
                # Do not lend this slot to another job while the abandoned
                # SQL is still running. Its SQLite/Python checkpoints stop it.
                try: future.result()
                except BaseException: pass
            raise
        finally:
            self.free.put(slot)

    def summary(self):
        with self.lock:
            return dict(max_workers=self.count,workers=dict(self.workers),
                cache_accounted_bytes=sum(cache['accounted_bytes'] for worker in self.workers.values()
                    for cache in worker.values()),closed=self.closed)

    def close(self):
        with self.lock:
            self.closed=True
            for flag in self.cancels: flag.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
