"""Serve one completed SimZ1 paged replay, read-only and bound to 127.0.0.1."""
import argparse
import gzip
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs,unquote,urlsplit
from simz1_paged_replay import unpacked


def read_export(directory):
    root=Path(directory).resolve(strict=True)
    manifest=json.loads((root/'export-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status')!='complete' or manifest.get('sample_rate')!=1:
        raise ValueError('Se requiere un export paginado completo y sin muestreo')
    database=(root/manifest['database']).resolve(strict=True)
    if manifest.get('database_external'):
        # Recovery on an external drive can reuse the original 23+ GiB spool.
        # This explicit binding is written only after full recovery validation.
        original=Path(manifest.get('recovery',{}).get('original_database','')).resolve()
        stat=database.stat()
        if (not Path(manifest['database']).is_absolute() or database!=original or
                database.name!='replay.sqlite' or not manifest.get('database_sha256') or
                stat.st_size!=manifest.get('database_bytes') or stat.st_mtime_ns!=manifest.get('database_mtime_ns')):
            raise ValueError('Referencia externa read-only incompatible con la recuperacion')
    elif database.parent!=root or database.name!='replay.sqlite':
        raise ValueError('La base de replay debe pertenecer a esta carpeta')
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
        identity=dict(connection.execute('SELECT key,value FROM export_identity'))
    expected=dict(run_id=manifest['run_id'],iteration=str(manifest['iteration']),
                  run_manifest_sha256=manifest['run_manifest_sha256'])
    if identity!=expected:
        raise ValueError('La base de replay pertenece a otra corrida, iteracion o manifiesto')
    blocks=manifest.get('blocks',[])
    from simz1_paged_replay import windows
    window=manifest['replay_window']
    if not blocks:
        raise ValueError('Manifiesto incompleto: faltan todos los bloques de replay')
    duration=manifest.get('window_seconds',blocks[0]['end_seconds']-blocks[0]['start_seconds'])
    expected_blocks=windows(window['start_seconds'],window['end_seconds'],duration)
    if len(blocks)!=len(expected_blocks):
        raise ValueError('Manifiesto incompleto: faltan bloques de replay')
    for block,expected_block in zip(blocks,expected_blocks):
        path=(root/'blocks'/block['url']).resolve(strict=True)
        if (any(block.get(k)!=v for k,v in expected_block.items()) or path.parent!=root/'blocks' or
                ('html_bytes' in block and path.stat().st_size!=block['html_bytes'])):
            raise ValueError('Bloques ausentes, truncados o incompatibles con el manifiesto')
    return root,manifest,database


def journey_payload(database,key,manifest):
    if not re.fullmatch('[0-9a-f]{64}',key):
        raise ValueError('Clave de viaje invalida')
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
        trip=connection.execute('SELECT metadata FROM journeys WHERE key=?',(key,)).fetchone()
        if trip is None:
            raise KeyError(key)
        metadata=json.loads(trip[0]);records=[]
        for row in connection.execute('SELECT payload FROM segments WHERE journey=? ORDER BY start,end,id',(key,)):
            record=unpacked(row[0]);record['Trip']=metadata;records.append(record)
    return dict(run_id=manifest['run_id'],iteration=manifest['iteration'],key=key,trip=metadata,records=records)


def handler_for(directory):
    root,manifest,database=read_export(directory)
    class ReplayHandler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(root),**kwargs)

        def do_GET(self):
            request=urlsplit(self.path)
            if request.path=='/api/journey':
                try:query=parse_qs(request.query,strict_parsing=True)
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST,'Consulta invalida');return
                if (query.get('run_id')!=[manifest['run_id']] or
                        query.get('iteration')!=[str(manifest['iteration'])] or len(query.get('key',[]))!=1):
                    self.send_error(HTTPStatus.BAD_REQUEST,'La consulta no corresponde a esta corrida e iteracion')
                    return
                try:
                    payload=journey_payload(database,query['key'][0],manifest)
                except ValueError as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST,str(exc));return
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND,'Viaje no encontrado en este replay');return
                data=json.dumps(payload,separators=(',',':'),allow_nan=False).encode('utf-8')
                compressed='gzip' in self.headers.get('Accept-Encoding','')
                if compressed:data=gzip.compress(data,compresslevel=1)
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                if compressed:self.send_header('Content-Encoding','gzip')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
                return
            self.serve_static(head=False)

        def do_HEAD(self):
            self.serve_static(head=True)

        def serve_static(self,*,head):
            relative=unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            # Reject traversal explicitly; do not silently normalize to another
            # file. The SQLite database is accessible only through exact keys.
            if '\\' in relative or any(part in ('.','..') for part in relative.split('/')):
                self.send_error(HTTPStatus.FORBIDDEN);return
            candidate=(root/relative).resolve()
            if not candidate.is_relative_to(root) or candidate.suffix.lower() not in ('.html','.json','.css','.js','.png','.svg','.ico'):
                self.send_error(HTTPStatus.FORBIDDEN);return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND);return
            if head:super().do_HEAD()
            else:super().do_GET()

        def list_directory(self,path):
            self.send_error(HTTPStatus.FORBIDDEN,'El indice del replay es index.html')
            return None

    return ReplayHandler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='Carpeta del index.html y export-manifest.json de la corrida explicita')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('--port debe estar entre 1 y 65535')
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(args.directory))
    except (OSError,ValueError,KeyError,sqlite3.Error) as exc:
        parser.exit(1,f'No se pudo abrir el replay: {exc}\n')
    print(f'Replay SimZ1 read-only: http://127.0.0.1:{args.port}/index.html',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
