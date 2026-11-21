"""Bounded, disposable HTTP windows outside immutable scientific artifacts.

Every namespace binds the source/run/iteration, complete replay manifest and
reader implementation. Files are verified before reuse. Reaching a disk budget
disables additional writes; it never drops source records or removes old runs.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import zlib
from simz1_report_package import PackageLock


def reader_version():
    digest=hashlib.sha256()
    # Queue capsules are evaluated by the production JS kernel as well as
    # Python. A renderer change must invalidate every persisted HTTP window.
    directory=Path(__file__).parent
    for path in sorted(path for pattern in ('*.py','*.js','*.cjs') for path in directory.glob(pattern)):
        if path.name.startswith('test_'): continue
        digest.update(path.name.encode()+b'\0'+path.read_bytes()+b'\n')
    return digest.hexdigest()


class WindowCache:
    def __init__(self, root, identity, manifest, *, version=None, max_bytes=2*1024**3, total_max_bytes=8*1024**3):
        self.root=Path(root).resolve()
        self.contract=dict(identity=identity,manifest=manifest,reader_version=version or reader_version(),format=1)
        self.namespace=hashlib.sha256(json.dumps(self.contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.directory=self.root/self.namespace
        self.max_bytes,self.total_max_bytes=max_bytes,total_max_bytes
        self.lock=threading.Lock()
        self.hits=self.misses=self.invalid=self.writes=self.budget_skips=0

    def paths(self,index):
        if type(index) is not int or index<0:raise ValueError('Indice de cache invalido')
        return self.directory/f'window-{index}.cache'

    def get(self,index):
        data_path=self.paths(index)
        with self.lock:
            try:
                with data_path.open('rb') as stream:
                    header=stream.readline(65536)
                    if not header.endswith(b'\n'):raise ValueError('Cabecera de cache truncada')
                    meta=json.loads(header)
                    if not 0<=meta['compressed_bytes']<=64*1024**2 or not 0<=meta['json_bytes']<=512*1024**2:
                        raise ValueError('Presupuesto de cache incompatible')
                    data=stream.read(meta['compressed_bytes']+1)
                if meta['namespace']!=self.namespace or meta['index']!=index:raise ValueError('Identidad de cache incompatible')
                if len(data)!=meta['compressed_bytes'] or hashlib.sha256(data).hexdigest()!=meta['compressed_sha256']:
                    raise ValueError('Cache comprimida corrupta')
                decoder=zlib.decompressobj(31)
                raw=decoder.decompress(data,meta['json_bytes']+1)
                if not decoder.eof or decoder.unused_data or len(raw)!=meta['json_bytes'] or hashlib.sha256(raw).hexdigest()!=meta['json_sha256']:
                    raise ValueError('Integridad de ventana en cache incompatible')
                self.hits+=1
                return data,len(raw),meta['timings'],meta['json_sha256']
            except FileNotFoundError:
                self.misses+=1
            except (OSError,ValueError,KeyError,EOFError,TypeError,zlib.error):
                self.invalid+=1
                self.misses+=1
            return None

    @staticmethod
    def atomic(path,data):
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)

    def put(self,index,data,json_size,timings,sha256):
        if len(data)>64*1024**2 or json_size>512*1024**2:
            self.budget_skips+=1
            return False
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True)
            for _ in range(100):
                with PackageLock(self.root/'.writer.lock') as writer:
                    if writer.acquired:return self._put_locked(index,data,json_size,timings,sha256)
                time.sleep(.01)
            self.budget_skips+=1
            return False

    def _put_locked(self,index,data,json_size,timings,sha256):
        data_path=self.paths(index)
        own=sum(path.stat().st_size for path in self.directory.iterdir() if path.is_file())
        total=sum(path.stat().st_size for directory in self.root.iterdir() if directory.is_dir()
                  for path in directory.iterdir() if path.is_file())
        old=data_path.stat().st_size if data_path.is_file() else 0
        added=len(data)+2048-old
        if own+added>self.max_bytes or total+added>self.total_max_bytes or shutil.disk_usage(self.root).free<added+256*1024**2:
            self.budget_skips+=1
            return False
        meta=dict(namespace=self.namespace,index=index,compressed_bytes=len(data),
            compressed_sha256=hashlib.sha256(data).hexdigest(),json_bytes=json_size,
            json_sha256=sha256,timings=timings)
        self.atomic(data_path,json.dumps(meta,sort_keys=True).encode()+b'\n'+data)
        self.writes+=1
        return True

    def summary(self):
        with self.lock:
            return dict(namespace=self.namespace,directory=str(self.directory),max_bytes=self.max_bytes,
                total_max_bytes=self.total_max_bytes,hits=self.hits,misses=self.misses,
                invalid_entries=self.invalid,writes=self.writes,budget_skips=self.budget_skips)
