"""Synthetic HTTP/SQLite work fixtures, independent of native run files."""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from serve_simz1_continuous import ContinuousServer, handler_for
from simz1_replay_work import checkpoint, cancellable_connection


class ReplayFixture:
    root = '.'
    manifest = dict(window_count=1000)
    response_identity = dict(run_id='synthetic', iteration=0, run_manifest_sha256='a'*64, source_version='b'*64)
    config = {'continuous': response_identity}
    config_raw = b'{}'

    def __init__(self, _):
        self.calls = []
        self.release = threading.Event()
        self.started = threading.Event()
        self.mode = 'slow'
        self.slow_indices = {161}

    def check_identity(self, query):
        if query.get('wrong'):
            raise ValueError('identity mismatch')

    def window_bytes(self, index):
        self.calls.append(index)
        if index in self.slow_indices:
            self.started.set()
            if self.mode == 'error':
                raise sqlite3.OperationalError('synthetic SQL failure')
            if self.mode == 'sql':
                with sqlite3.connect(':memory:') as connection:
                    cancellable_connection(connection)
                    connection.execute('WITH RECURSIVE t(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM t WHERE n<1000000000) SELECT sum(n) FROM t').fetchone()
            if self.mode == 'finite_sql':
                with sqlite3.connect(':memory:') as connection:
                    cancellable_connection(connection)
                    result=connection.execute('WITH RECURSIVE t(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM t WHERE n<1000000) SELECT sum(n) FROM t').fetchone()[0]
                    assert result == 500000500000
                self.release.set()
            while not self.release.wait(.01):
                checkpoint('synthetic_slow_python')
        return json.dumps(dict(**self.response_identity, index=index, segments=[], trips={})).encode()


class NavigationServerTests(unittest.TestCase):
    def setUp(self):
        self.open_server()

    def open_server(self, max_queries=1):
        with patch('serve_simz1_continuous.ContinuousReplay', ReplayFixture), patch('serve_simz1_continuous.application_html', return_value='<html></html>'):
            self.handler = handler_for('.', max_queries=max_queries)
        self.server = ContinuousServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.handler.replay.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def fetch(self, index, priority='demand'):
        with urlopen(self.base+f'/api/window?index={index}&priority={priority}', timeout=5) as response:
            return json.load(response)

    def abandoned(self, *, mode='slow'):
        self.handler.replay.mode = mode
        client = socket.create_connection(('127.0.0.1', self.server.server_port))
        client.sendall(b'GET /api/window?index=161 HTTP/1.1\r\nHost: localhost\r\n\r\n')
        self.assertTrue(self.handler.replay.started.wait(2))
        return client

    def wait_idle(self):
        deadline = time.monotonic()+3
        while self.handler.query_summary()['active_distinct_queries'] and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(self.handler.query_summary()['active_distinct_queries'], 0)

    def test_abandoned_python_query_releases_budget(self):
        self.abandoned().close()
        self.wait_idle()
        self.assertEqual(self.fetch(162)['index'],162)

    def test_abandoned_sql_query_is_interrupted_without_mutation(self):
        self.abandoned(mode='sql').close()
        self.wait_idle()
        self.assertEqual(self.fetch(162)['index'],162)

    def test_duplicate_waiter_keeps_shared_query_alive(self):
        first = self.abandoned()
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(self.fetch, 161)
            deadline=time.monotonic()+2
            while not self.handler.query_summary()['coalesced_requests'] and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.handler.query_summary()['coalesced_requests'],1)
            first.close()
            time.sleep(.2)
            self.assertEqual(self.handler.query_summary()['active_distinct_queries'],1)
            self.handler.replay.release.set()
            self.assertEqual(second.result()['index'],161)
        self.assertEqual(self.handler.replay.calls,[161])
        self.wait_idle()

    def test_busy_is_retryable_but_sql_failure_is_not(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(self.fetch,161)
            self.assertTrue(self.handler.replay.started.wait(2))
            with self.assertRaises(HTTPError) as caught: self.fetch(162)
            self.assertEqual(caught.exception.code,503)
            self.assertTrue(json.load(caught.exception)['retryable'])
            self.handler.replay.release.set()
            self.assertEqual(job.result()['index'],161)
        self.assertEqual(self.fetch(162)['index'],162)
        self.handler.cache.entries.clear()
        self.handler.cache.bytes=0
        self.handler.replay.mode='error'
        with self.assertRaises(HTTPError) as caught: self.fetch(161)
        self.assertEqual(caught.exception.code,500)
        error=json.load(caught.exception)
        self.assertIn('synthetic SQL failure',error['error'])
        self.assertFalse(error['retryable'])

    def test_long_live_sql_finishes_without_deadline(self):
        self.handler.replay.mode='finite_sql'
        self.assertEqual(self.fetch(161)['index'],161)
        self.assertEqual(self.handler.query_summary()['cancelled_queries'],0)
        self.assertGreater(self.handler.query_summary()['recent_work'][-1]['checkpoints'],100)

    def test_prefetch_leaves_demand_capacity_and_can_be_preempted(self):
        self.tearDown()
        self.open_server(max_queries=2)
        self.handler.replay.slow_indices={161,187}
        with ThreadPoolExecutor(max_workers=2) as pool:
            speculative=pool.submit(self.fetch,161,'prefetch')
            self.assertTrue(self.handler.replay.started.wait(2))
            with self.assertRaises(HTTPError) as caught: self.fetch(162,'prefetch')
            self.assertEqual(caught.exception.code,503)
            self.assertEqual(json.load(caught.exception)['code'],'prefetch_deferred')
            self.assertEqual(self.fetch(162)['index'],162)
            demand=pool.submit(self.fetch,187)
            deadline=time.monotonic()+2
            while self.handler.query_summary()['active_distinct_queries']<2 and time.monotonic()<deadline: time.sleep(.01)
            with self.assertRaises(HTTPError) as caught: self.fetch(188)
            self.assertEqual(caught.exception.code,503)
            with self.assertRaises(HTTPError) as cancelled: speculative.result(timeout=3)
            self.assertEqual(cancelled.exception.code,503)
            self.assertEqual(self.fetch(188)['index'],188)
            self.handler.replay.release.set()
            self.assertEqual(demand.result()['index'],187)
        self.wait_idle()
        summary=self.handler.query_summary()
        self.assertEqual(summary['preempted_queries'],1)
        self.assertLessEqual(summary['peak_distinct_queries'],2)

    def test_duplicate_waiters_and_response_cache_are_bounded(self):
        with ThreadPoolExecutor(max_workers=9) as pool:
            futures=[pool.submit(self.fetch,161) for _ in range(9)]
            try:
                deadline=time.monotonic()+3
                while self.handler.query_summary()['waiting_duplicate_requests']<8 and time.monotonic()<deadline: time.sleep(.01)
                self.assertEqual(self.handler.query_summary()['waiting_duplicate_requests'],8)
                with self.assertRaises(HTTPError) as caught: self.fetch(161)
                self.assertEqual(caught.exception.code,503)
                with urlopen(self.base+'/api/config',timeout=1) as response: self.assertEqual(response.status,200)
            finally:
                self.handler.replay.release.set()
            for future in futures: self.assertEqual(future.result()['index'],161)
        self.assertEqual(self.handler.replay.calls,[161])
        for index in range(12): self.fetch(index)
        cache=self.handler.cache.summary()
        self.assertLessEqual(cache['entries'],cache['max_entries'])
        self.assertLessEqual(cache['bytes'],cache['max_bytes'])
        self.wait_idle()

    def test_identity_error_does_not_start_or_reuse_work(self):
        self.assertEqual(self.fetch(0)['index'],0)
        with self.assertRaises(HTTPError) as caught: urlopen(self.base+'/api/window?index=0&wrong=1')
        self.assertEqual(caught.exception.code,400)
        self.assertEqual(self.handler.replay.calls,[0])


if __name__ == '__main__': unittest.main()
