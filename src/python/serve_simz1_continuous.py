"""Serve an existing SimZ1 continuous viewer, read-only on loopback."""
import argparse
from collections import OrderedDict
from concurrent.futures import Future, TimeoutError as FutureTimeout
import gzip
import hashlib
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import select
import socket
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit, urlencode
import webbrowser

from simz1_continuous_replay import ContinuousReplay, application_html, json_bytes
from simz1_replay_work import ReadWork, WorkCancelled, checkpoint, work_scope


class ByteCache:
    """LRU with explicit byte and entry limits (compressed responses only)."""
    def __init__(self, max_bytes=64*1024*1024, max_entries=8):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries, self.bytes = OrderedDict(), 0
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            if key not in self.entries:
                self.misses += 1
                return None
            self.hits += 1
            self.entries.move_to_end(key)
            return self.entries[key]

    def put(self, key, value):
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous is not None:
                self.bytes -= len(previous)
            if len(value) > self.max_bytes:
                return
            self.entries[key] = value
            self.bytes += len(value)
            while self.bytes > self.max_bytes or len(self.entries) > self.max_entries:
                _, removed = self.entries.popitem(last=False)
                self.bytes -= len(removed)

    def summary(self):
        with self.lock:
            return dict(entries=len(self.entries), bytes=self.bytes, max_entries=self.max_entries,
                        max_bytes=self.max_bytes, hits=self.hits, misses=self.misses)


class ServerBusy(Exception):
    def __init__(self, message, code='server_busy'):
        super().__init__(message)
        self.code = code


class EncodedPayload(bytes):
    def __new__(cls, data, json_size, timings, sha256):
        value = super().__new__(cls, data)
        value.json_size, value.timings, value.sha256 = json_size, timings, sha256
        return value


def handler_for(directory, *, cache_bytes=64*1024*1024, max_queries=None, checkpoint_plan=None, visual_policy=None):
    from simz1_continuous_replay import checked_visual_policy
    checked_visual_policy(visual_policy)
    if visual_policy is not None and checkpoint_plan is not None:
        raise ValueError('Partial visual mode cannot prepare a checkpoint plan')
    replay = ContinuousReplay(directory,**({'visual_policy':visual_policy} if visual_policy is not None else {}))
    if checkpoint_plan is not None:
        from simz1_queue_checkpoint_library import prepare_checkpoint_plan
        prepare_checkpoint_plan(replay,checkpoint_plan,
            progress=lambda value:print(json.dumps(value,ensure_ascii=False),flush=True))
    if getattr(replay,'initialization',None) is not None:
        print(json.dumps({'replay_initialization':replay.initialization},ensure_ascii=False),flush=True)
    use_workers = getattr(replay, 'source_manifest', {}).get('source_type') == 'sqlite-direct-v1'
    if max_queries is None: max_queries=2
    if use_workers:
        ahead=min(3,max_queries)
        replay.config['continuous']['playback']=dict(prefetch_ahead=ahead,cache_windows=ahead+1,max_requests=ahead)
        replay.config_raw=json_bytes(replay.config)
    application = application_html().encode('utf-8')
    cache = ByteCache(cache_bytes)
    disk_cache=None
    if use_workers:
        from simz1_window_cache import WindowCache
        disk_cache=WindowCache(Path(__file__).resolve().parents[1]/'runtime/replay-cache',
                               replay.response_identity,replay.manifest)
    queries = threading.BoundedSemaphore(max_queries)
    flights = {}
    flights_lock = threading.Lock()
    work_metrics = {'coalesced_requests': 0, 'peak_distinct_queries': 0, 'responses': 0,
                    'cancelled_queries': 0, 'preempted_queries': 0, 'failed_queries': 0}
    samples = []
    work_samples = []
    # Separate interpreters give CPU-bound JSON/closure work real concurrency.
    # Initialization is lazy: checking/reusing a launcher never starts workers.
    read_pool = None
    pool_lock = threading.Lock()

    def get_pool():
        nonlocal read_pool
        with pool_lock:
            if read_pool is None:
                from simz1_replay_workers import ReplayReadPool
                read_pool=ReplayReadPool(replay.root,replay.response_identity,max_queries,
                                        version=disk_cache.contract['reader_version'],
                                        spatial_preparation=replay.spatial_preparation(),
                                        queue_support_preparation=replay.queue_support_preparation(),
                                        queue_checkpoint_preparation=getattr(replay,'queue_checkpoint_preparation',None),
                                        visual_policy=getattr(replay,'visual_policy',None))
            return read_pool

    def close_workers():
        with pool_lock:
            if read_pool is not None: read_pool.close()

    def compressed_payload(key, get_payload, request_metrics, connected, priority):
        # A browser can abort HTTP while SQLite is still reading. A replacement
        # request for the same immutable window shares that original work,
        # rather than occupying another SQL slot and rejecting a selection.
        owner = object()
        with flights_lock:
            cached = cache.get(key)
            if cached is not None:
                request_metrics['cache'] = 'hit'
                return cached
            if disk_cache is not None and key[1][0]=='window':
                stored=disk_cache.get(key[1][1])
                if stored is not None:
                    cached=EncodedPayload(*stored)
                    cache.put(key,cached)
                    request_metrics['cache']='disk_hit'
                    return cached
            flight = flights.get(key)
            leader = flight is None
            if leader:
                # Speculation must leave capacity for a seek or a selection.
                if not use_workers and priority == 'prefetch' and len(flights) >= max_queries-1:
                    raise ServerBusy('Precarga aplazada para dar prioridad a la navegacion', 'prefetch_deferred')
                if not queries.acquire(blocking=False):
                    if priority == 'demand':
                        for other in flights.values():
                            if other['priority'] == 'prefetch':
                                other['work'].cancel('demand_priority')
                    raise ServerBusy('Servidor ocupado; reintente la ventana')
                flight = {'future': Future(), 'followers': 0, 'owners': {owner: connected}, 'priority': priority}
                def abandoned():
                    with flights_lock:
                        return not any(alive() for alive in flight['owners'].values())
                flight['work'] = ReadWork(abandoned)
                flights[key] = flight
                work_metrics['peak_distinct_queries'] = max(work_metrics['peak_distinct_queries'], len(flights))
            else:
                if flight['followers'] >= 8:
                    raise ServerBusy('Demasiadas peticiones pendientes para esta ventana')
                flight['followers'] += 1
                flight['owners'][owner] = connected
                if priority == 'demand':
                    flight['priority'] = 'demand'
                work_metrics['coalesced_requests'] += 1
            request_metrics['cache'] = 'miss' if leader else 'coalesced'
        if not leader:
            try:
                # A live follower can wait for minutes. Time spent computing
                # is not failure; a closed client must release its ownership.
                while True:
                    if not connected():
                        raise ConnectionAbortedError('Peticion compartida cancelada')
                    try:
                        return flight['future'].result(timeout=.2)
                    except FutureTimeout:
                        continue
            finally:
                with flights_lock:
                    flight['followers'] -= 1
                    flight['owners'].pop(owner, None)
        try:
            started = time.perf_counter()
            with work_scope(flight['work']):
                checkpoint('building')
                if use_workers and key[1][0] in ('window', 'journey'):
                    compressed=EncodedPayload(*get_pool().read(*key[1],flight['work']))
                else:
                    payload = get_payload()
                    checkpoint('encoding')
                    raw = payload if isinstance(payload, bytes) else json_bytes(payload)
                    del payload
                    assembled = time.perf_counter()
                    compressed = EncodedPayload(gzip.compress(raw, compresslevel=1, mtime=0), len(raw),
                                                dict(build_ms=(assembled-started)*1000,
                                                     gzip_ms=(time.perf_counter()-assembled)*1000), hashlib.sha256(raw).hexdigest())
                    del raw
                checkpoint('complete')
            cache.put(key, compressed)
            if disk_cache is not None and key[1][0]=='window':
                try:
                    disk_cache.put(key[1][1],compressed,compressed.json_size,compressed.timings,compressed.sha256)
                except OSError as error:
                    # The response remains complete even if disposable cache
                    # storage fails. Expose the failure instead of hiding it.
                    request_metrics['disk_cache_error']=str(error)
            flight['future'].set_result(compressed)
            return compressed
        except Exception as exc:
            if isinstance(exc, WorkCancelled) or flight['work'].cancelled.is_set():
                reason = flight['work'].reason
                with flights_lock:
                    work_metrics['cancelled_queries'] += 1
                    if reason == 'demand_priority':
                        work_metrics['preempted_queries'] += 1
                exc = ServerBusy('Trabajo cancelado: '+str(reason)+'; reintente si aun necesita esta ventana', 'work_cancelled')
            else:
                with flights_lock:
                    work_metrics['failed_queries'] += 1
            flight['future'].set_exception(exc)
            raise exc
        finally:
            with flights_lock:
                work_samples.append(dict(kind=key[1][0], key=key[1][1], **flight['work'].snapshot()))
                del work_samples[:-32]
                flights.pop(key, None)
                queries.release()

    def query_summary():
        with flights_lock:
            return {**work_metrics, 'active_distinct_queries': len(flights),
                    'waiting_duplicate_requests': sum(flight['followers'] for flight in flights.values()),
                    'active_work': [dict(kind=key[1][0], key=key[1][1], priority=flight['priority'],
                                         clients=len(flight['owners']), **flight['work'].snapshot()) for key, flight in flights.items()],
                    'recent_work': list(work_samples),
                    'recent_responses': list(samples)}

    class ContinuousHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(replay.root), **kwargs)

        def connected(self):
            connection = getattr(self, 'connection', None)
            if connection is None:  # In-process handler fixtures have no socket.
                return True
            try:
                ready, _, _ = select.select([connection], [], [], 0)
                return not ready or bool(connection.recv(1, socket.MSG_PEEK))
            except (OSError, ValueError):
                return False

        def send_json(self, status, value, *, retry=False):
            raw = json_bytes(value)
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(raw)))
                if retry:
                    self.send_header('Retry-After', '2')
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # AbortController deliberately closes obsolete requests.

        def do_GET(self):
            request = urlsplit(self.path)
            if not request.path.startswith('/api/'):
                try:
                    self.serve_static(head=False)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            try:
                query = parse_qs(request.query, strict_parsing=True) if request.query else {}
                if request.path == '/api/config':
                    self.send_json(HTTPStatus.OK, replay.config)
                    return
                replay.check_identity(query)
                if request.path == '/api/hud':
                    self.send_json(HTTPStatus.OK, replay.hud(query))
                    return
                if request.path == '/api/metrics':
                    self.send_json(HTTPStatus.OK, {**replay.response_identity, 'cache': cache.summary(), 'max_queries': max_queries,
                                                  'read_caches': {name: getattr(replay, name).summary() for name in
                                                                  ('lookup_cache', 'temporal_cache', 'queue_context_cache', 'queue_record_cache', 'queue_seed_cache', 'queue_dependency_cache', 'queue_index_cache') if hasattr(replay, name)},
                                                  'queries': query_summary(),
                                                  'read_workers': self.worker_summary(),
                                                  'disk_cache': disk_cache.summary() if disk_cache is not None else None})
                    return
                if request.path == '/api/aggregate':
                    instant = replay.aggregate_time(query)
                    key = ('aggregate', instant)
                    get_payload = lambda: replay.aggregate_snapshot(instant)
                elif request.path == '/api/window':
                    values = query.get('index', [])
                    if len(values) != 1:
                        raise ValueError('Se requiere exactamente un indice')
                    index = int(values[0])
                    if str(index) != values[0] or not 0 <= index < replay.manifest['window_count']:
                        raise ValueError('Indice de ventana fuera del replay')
                    key = ('window', index)
                    get_payload = lambda: replay.window_bytes(index)
                elif request.path == '/api/journey':
                    values = query.get('key', [])
                    if len(values) != 1:
                        raise ValueError('Se requiere exactamente una clave de viaje')
                    key = ('journey', values[0])
                    get_payload = lambda: replay.journey(values[0])
                else:
                    self.send_json(HTTPStatus.NOT_FOUND, {'error': 'API no encontrada'})
                    return
                request_started = time.perf_counter()
                if use_workers: replay.check_source_files()
                request_metrics = {'kind': key[0], 'key': key[1]}
                namespace = tuple(replay.response_identity.items())
                priority = query.get('priority', ['demand'])
                if priority not in (['demand'], ['prefetch']):
                    raise ValueError('Prioridad de consulta invalida')
                compressed = compressed_payload((namespace, key), get_payload, request_metrics, self.connected, priority[0])
                payload_ready = time.perf_counter()
                use_gzip = 'gzip' in self.headers.get('Accept-Encoding', '')
                data = compressed if use_gzip else gzip.decompress(compressed)
                transport_ready = time.perf_counter()
                request_metrics.update(json_bytes=compressed.json_size, gzip_bytes=len(compressed),
                                       wait_or_build_ms=(payload_ready-request_started)*1000,
                                       response_decompress_ms=(transport_ready-payload_ready)*1000,
                                       cached_build_profile=compressed.timings)
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Vary', 'Accept-Encoding')
                self.send_header('X-SimZ1-JSON-Bytes', str(compressed.json_size))
                self.send_header('X-SimZ1-JSON-SHA256', compressed.sha256)
                self.send_header('Server-Timing', 'payload;dur=%.3f, response_decode;dur=%.3f, cache;desc="%s"' % (
                    request_metrics['wait_or_build_ms'], request_metrics['response_decompress_ms'], request_metrics['cache']))
                if use_gzip:
                    self.send_header('Content-Encoding', 'gzip')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    request_metrics['client_disconnected'] = True
                finally:
                    request_metrics['write_ms'] = (time.perf_counter()-transport_ready)*1000
                    with flights_lock:
                        work_metrics['responses'] += 1
                        samples.append(request_metrics)
                        del samples[:-32]
            except ServerBusy as exc:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {**replay.response_identity,
                    'error': str(exc), 'code': exc.code, 'retryable': True}, retry=True)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            except KeyError:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Viaje no encontrado'})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Aborts can occur while flushing headers, before wfile.write.
                # A second HTTP response cannot be sent on a closed connection.
                pass
            except (OSError, sqlite3.Error) as exc:
                self.log_error('No se pudo leer evidencia: %s', exc)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': 'No se pudo leer evidencia validada: '+str(exc),
                    'code': type(exc).__name__, 'retryable': False})
            except Exception as exc:
                self.log_error('Fallo del procesamiento del replay: %s: %s', type(exc).__name__, exc)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': str(exc),
                    'code': type(exc).__name__, 'retryable': False})

        def do_HEAD(self):
            try:
                self.serve_static(head=True)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def serve_static(self, *, head):
            relative = unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            # Explicit allowlist: never expose SQLite, native evidence or paths.
            if relative not in ('index.html', 'config.json'):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            # Serve current code and the daily projection without rewriting a
            # historical export, its manifest, config, events or SQLite.
            data = application if relative == 'index.html' else replay.config_raw
            content_type = 'text/html' if relative == 'index.html' else 'application/json'
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def list_directory(self, path):
            self.send_error(HTTPStatus.FORBIDDEN)
            return None

    ContinuousHandler.replay = replay
    ContinuousHandler.cache = cache
    ContinuousHandler.queries = queries
    ContinuousHandler.query_summary = staticmethod(query_summary)
    ContinuousHandler.close_workers = staticmethod(close_workers)
    ContinuousHandler.worker_summary = staticmethod(lambda: read_pool.summary() if read_pool is not None else None)
    return ContinuousHandler


class ContinuousServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def server_close(self):
        super().server_close()
        close=getattr(self.RequestHandlerClass,'close_workers',None)
        if close is not None: close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open', action='store_true', help='Abrir el navegador predeterminado')
    parser.add_argument('--checkpoint-plan',type=Path,help='Reconstruir y verificar soporte causal antes de abrir HTTP')
    parser.add_argument('--visual-policy',choices=('partial-native-v1',),help='Abrir evidencia nativa sin reconstruccion causal; ocultar cuerpos pendientes')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port debe estar entre 1 y 65535')
    try:
        server = ContinuousServer(('127.0.0.1', args.port), handler_for(args.directory,checkpoint_plan=args.checkpoint_plan,visual_policy=args.visual_policy))
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f'No se pudo abrir el visor continuo: {exc}\n')
    address = f'http://127.0.0.1:{args.port}/index.html'
    if args.visual_policy is not None:
        address += '?' + urlencode(server.RequestHandlerClass.replay.response_identity)
    print(f'SimZ1 continuo (SQLite read-only): {address}', flush=True)
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
