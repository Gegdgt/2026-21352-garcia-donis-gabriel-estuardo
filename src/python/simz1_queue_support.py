"""External, sealed temporal support index for immutable replay segments.

Preparation streams the source once, retaining only one decoded segment and its
previous scalar row. Requests use link/time and native reservation indexes;
they never decode a complete network snapshot. This is an index, not a pose or
an acceptance checkpoint: all returned records still undergo native validation.
"""
import hashlib
import json
import inspect
import math
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import stat
import threading
import time
import uuid
import zlib


SCHEMA = 'native-causal-support-index-v2'
FIELDS = ('id', 'journey', 'vehicle', 'start', 'end', 'compressed_bytes',
          'decoded_bytes', 'link', 'hold', 'ordinal', 'corridor', 'slot',
          'transfer_known', 'transfer_corridor', 'transfer_slot', 'transfer_ordinal')


class AuxiliaryStorageExceeded(ValueError):
    pass


_active_storage_scope = None
_storage_scope_lock = threading.Lock()


class AuxiliaryStorageScope:
    """Observed file budget for one exclusively owned SQLite preparation.

    SQLite's temporary directory is process-global. The caller must establish
    this scope before opening concurrent readers; a second live scope is an
    ownership error. FILE storage stays on disk. This checks aggregate usage at
    explicit boundaries and periodically during SQL; it is not an OS/VFS quota
    or a claim to have sampled every transient byte between callbacks.
    """
    def __init__(self,root,max_disk_bytes,*,fixed_paths=(),progress_steps=20000,poll_seconds=.05):
        if type(max_disk_bytes) is not int or max_disk_bytes<=0:
            raise ValueError('Auxiliary storage budget must be positive')
        if type(progress_steps) is not int or progress_steps<=0 or not isinstance(poll_seconds,(int,float)) or poll_seconds<0:
            raise ValueError('Auxiliary storage polling bounds invalid')
        raw=Path(root).absolute()
        if raw.resolve()!=raw:raise ValueError('Auxiliary storage root has an indirect ancestor')
        if raw.exists() and self._indirect(raw):raise ValueError('Auxiliary storage root cannot be indirect')
        raw.mkdir(parents=True,exist_ok=True)
        self.root=raw.resolve(strict=True)
        self.root_identity=self._identity(self.root)
        self.max_disk_bytes=max_disk_bytes
        self.progress_steps,self.poll_seconds=progress_steps,poll_seconds
        self.fixed={};self.connections=[];self.control=None;self.active=False;self.previous_temp=None
        self.previous_temp_known=False
        self.failure=None;self.checks=0;self.last_poll=0.0;self.last_observed_bytes=0;self.peak_observed_bytes=0
        self.last_stage=None;self.temp_directory=None
        for path in fixed_paths:self.pin_file(path)

    @staticmethod
    def _indirect(path):
        info=path.lstat()
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))

    @staticmethod
    def _identity(path):
        info=path.stat()
        return info.st_dev,info.st_ino

    def pin_file(self,path):
        raw=Path(path).absolute()
        if self._indirect(raw):raise ValueError('Auxiliary fixed file cannot be indirect')
        resolved=raw.resolve(strict=True)
        if resolved!=raw:raise ValueError('Auxiliary fixed file has an indirect ancestor')
        if not resolved.is_file() or resolved.is_relative_to(self.root):
            raise ValueError('Auxiliary fixed file must be outside the owned directory')
        info=resolved.stat()
        identity=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        if resolved in self.fixed and self.fixed[resolved]!=identity:
            raise ValueError('Auxiliary fixed file cannot be repinned after mutation')
        self.fixed[resolved]=identity

    def _observed(self):
        if self._indirect(self.root) or self._identity(self.root)!=self.root_identity:
            raise ValueError('Auxiliary storage root identity changed')
        total=0;pending=[self.root]
        while pending:
            directory=pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:info=entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        # SQLite may remove a temporary file between directory
                        # enumeration and stat. Its prior bytes are not a new
                        # observation; earlier checks retain their high-water.
                        continue
                    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
                        raise ValueError('Auxiliary storage contains an indirect path')
                    item=Path(entry.path)
                    try:resolved=item.resolve(strict=True)
                    except FileNotFoundError:continue
                    if not resolved.is_relative_to(self.root):
                        raise ValueError('Auxiliary storage path escaped owned directory')
                    if stat.S_ISDIR(info.st_mode):pending.append(item)
                    elif stat.S_ISREG(info.st_mode):total+=info.st_size
                    else:raise ValueError('Auxiliary storage contains unsupported file type')
        for path,pinned in self.fixed.items():
            if self._indirect(path):raise ValueError('Auxiliary fixed file became indirect')
            info=path.stat()
            if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=pinned:
                raise ValueError('Auxiliary fixed file identity or bytes changed')
            total+=info.st_size
        return total

    def check(self,stage='manual',*,additional_bytes=0):
        if not self.active:raise ValueError('Auxiliary storage scope is not active')
        if type(additional_bytes) is not int or additional_bytes<0:
            raise ValueError('Auxiliary projected bytes invalid')
        self.raise_if_failed()
        try:
            observed=self._observed();self.checks+=1;self.last_stage=str(stage)
            self.last_observed_bytes=observed;self.peak_observed_bytes=max(self.peak_observed_bytes,observed)
            self.last_poll=time.monotonic()
            if observed+additional_bytes>self.max_disk_bytes:
                raise AuxiliaryStorageExceeded('Auxiliary storage budget exceeded at '+str(stage)+': '+
                    str(observed)+' observed + '+str(additional_bytes)+' projected > '+str(self.max_disk_bytes))
            return self.report()
        except Exception as error:
            self.failure=error;raise

    def raise_if_failed(self):
        if self.failure is not None:raise self.failure

    def report(self):
        return dict(schema='native-auxiliary-storage-observation-v1',budget_bytes=self.max_disk_bytes,
            observed_bytes=self.last_observed_bytes,peak_observed_bytes=self.peak_observed_bytes,
            checks=self.checks,last_stage=self.last_stage,root=str(self.root),
            fixed_paths=[str(path) for path in self.fixed],temp_directory=str(self.temp_directory) if self.temp_directory else None,
            observation_scope='explicit_boundaries_and_periodic_sql_callbacks_not_os_quota',
            breached=self.failure is not None,failure=str(self.failure) if self.failure else None)

    def __enter__(self):
        global _active_storage_scope
        with _storage_scope_lock:
            if _active_storage_scope is not None:raise ValueError('Another auxiliary SQLite temporary scope is active')
            _active_storage_scope=self
        try:
            self.control=sqlite3.connect(':memory:')
            prior=self.control.execute('PRAGMA temp_store_directory').fetchone()
            self.previous_temp=prior[0] if prior else ''
            self.previous_temp_known=True
            self.temp_directory=self.root/('sqlite-tmp-'+uuid.uuid4().hex)
            self.temp_directory.mkdir(exist_ok=False)
            value=self.temp_directory.as_posix().replace("'","''")
            self.control.execute("PRAGMA temp_store_directory='"+value+"'")
            actual=self.control.execute('PRAGMA temp_store_directory').fetchone()
            if actual is None or Path(actual[0]).resolve()!=self.temp_directory:
                raise ValueError('SQLite did not adopt the owned temporary directory')
            self.active=True;self.check('scope_enter');return self
        except BaseException:
            self.close();raise

    def attach(self,connection):
        if not self.active:raise ValueError('Auxiliary storage scope is not active')
        self.raise_if_failed()
        if connection in self.connections:return
        connection.execute('PRAGMA temp_store=FILE')
        if connection.execute('PRAGMA temp_store').fetchone()!=(1,):
            raise ValueError('Auxiliary SQLite temporary storage must remain FILE')
        def progress():
            if self.failure is not None:return 1
            if time.monotonic()-self.last_poll<self.poll_seconds:return 0
            try:self.check('sqlite_progress');return 0
            except Exception:return 1
        connection.set_progress_handler(progress,self.progress_steps)
        self.connections.append(connection);self.check('connection_attach')

    def detach(self,connection):
        if connection in self.connections:
            try:connection.set_progress_handler(None,0)
            except sqlite3.ProgrammingError as error:
                if 'closed' not in str(error).lower():raise
            self.connections.remove(connection)

    @contextmanager
    def work(self,stage):
        self.check(str(stage)+'_before')
        try:yield
        except BaseException:
            self.raise_if_failed();raise
        self.check(str(stage)+'_after')

    def commit(self,connection,stage='commit'):
        with self.work(stage):connection.commit()

    def close(self):
        global _active_storage_scope
        try:
            for connection in list(self.connections):self.detach(connection)
            if self.control is not None:
                prior=(self.previous_temp or '').replace("'","''")
                try:
                    if self.previous_temp_known:
                        self.control.execute("PRAGMA temp_store_directory='"+prior+"'")
                        actual=self.control.execute('PRAGMA temp_store_directory').fetchone()
                        if (actual[0] if actual else '')!=(self.previous_temp or ''):
                            raise ValueError('SQLite temporary directory was not restored')
                finally:self.control.close();self.control=None
        finally:
            self.active=False
            with _storage_scope_lock:
                if _active_storage_scope is self:_active_storage_scope=None

    def __exit__(self,kind,error,traceback):
        try:
            if kind is None:self.check('scope_exit')
        finally:self.close()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def contract(database, identity, source_sha256, visual_lanes):
    """The caller supplies the SHA from an already verified native source."""
    from simz1_queue_context import encoded, hold_time, QueueContext
    database = Path(database).resolve(strict=True)
    stat = database.stat()
    if not isinstance(source_sha256, str) or len(source_sha256) != 64 or any(c not in '0123456789abcdef' for c in source_sha256):
        raise ValueError('Support index requires verified SQLite SHA256')
    if (set(identity) != {'run_id','iteration','run_manifest_sha256'} or
            not isinstance(identity['run_id'],str) or not identity['run_id'] or
            type(identity['iteration']) is not int or identity['iteration'] < 0 or
            not isinstance(identity['run_manifest_sha256'],str) or len(identity['run_manifest_sha256']) != 64):
        raise ValueError('Support index run/iteration identity invalid')
    directory = Path(__file__).parent
    return dict(schema=SCHEMA, identity=dict(identity), database=str(database),
                database_bytes=stat.st_size, database_mtime_ns=stat.st_mtime_ns,
                database_sha256=source_sha256,
                geometry_sha256=hashlib.sha256(encoded(visual_lanes)).hexdigest(),
                sources={**{name: _sha(directory / name) for name in
                            ('simz1_visual_queues.js', 'simz1_visual_lanes.js')},
                         **{name:hashlib.sha256(inspect.getsource(fn).encode()).hexdigest() for name,fn in
                            [('hold_time',hold_time),('reservation_order',QueueContext._reservation_order),
                             ('transfer',_transfer),('spatial_support',_spatial_support),('temporal_bins',_temporal_bins),('scalar_rows',_scalar_rows)]}})


class SupportIndex:
    def __init__(self, path, expected, *, expected_sha256,storage_scope=None):
        if Path(path).is_symlink() or Path(path).with_suffix('.json').is_symlink():
            raise ValueError('Support index paths must not be symlinks')
        self.path = Path(path).resolve(strict=True)
        receipt = json.loads(self.path.with_suffix('.json').read_text(encoding='utf8'))
        if receipt.get('contract') != expected or receipt.get('complete') is not True:
            raise ValueError('Support index identity/source/completeness mismatch')
        if receipt.get('sha256') != expected_sha256 or expected_sha256 != _sha(self.path):
            raise ValueError('Support index bytes changed')
        self.connection = sqlite3.connect(self.path.as_uri() + '?mode=ro&immutable=1', uri=True)
        self.connection.execute('PRAGMA query_only=ON')
        self.connection.execute('PRAGMA cache_size=-8192')
        self.connection.execute('PRAGMA temp_store=FILE')
        # Constructor coverage queries may themselves use a disk sort. Adopt
        # the sole live preparation scope before executing any of those reads.
        scoped=storage_scope or _active_storage_scope
        if scoped is not None:
            try:scoped.attach(self.connection)
            except BaseException:self.connection.close();raise
        metadata = dict(self.connection.execute('SELECT key,value FROM metadata'))
        if metadata.get('contract') != _json(expected) or metadata.get('complete') != 'true':
            self.connection.close()
            raise ValueError('Support index internal contract mismatch')
        count = self.connection.execute('SELECT count(*) FROM support').fetchone()[0]
        if count != receipt.get('records') or str(count) != metadata.get('records'):
            self.connection.close()
            raise ValueError('Support index coverage mismatch')
        self.receipt = receipt
        self.source_links = frozenset(row[0] for row in self.connection.execute('SELECT DISTINCT link FROM support'))
        if self.connection.execute('SELECT count(*) FROM support_scope').fetchone()[0]!=count:
            self.connection.close();raise ValueError('Support spatial coverage mismatch')

    def close(self):
        self.connection.close()

    @classmethod
    def prepare(cls, directory, source, expected, *, validate_segment, visual_lanes,
                max_record_bytes=1024 * 1024, max_disk_bytes=4 * 1024**3, progress=None,storage_scope=None):
        from simz1_report_package import PackageLock
        main=next((row[2] for row in source.execute('PRAGMA database_list') if row[1]=='main'),None)
        if main is None or Path(main).resolve()!=Path(expected['database']).resolve():
            raise ValueError('Support index source connection is not the contracted native database')
        if source.execute('PRAGMA query_only').fetchone()!=(1,):
            raise ValueError('Support index source connection must be query-only')
        directory=Path(directory).resolve()
        directory.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(_json(expected).encode()).hexdigest()
        with PackageLock(directory/(key+'.lock')) as lock:
            if not lock.acquired:
                raise ValueError('Another writer owns support index preparation')
            target=directory/(key+'.sqlite')
            fixed=tuple(path for path in (target,target.with_suffix('.json')) if path.exists())
            workspace=(storage_scope.root if storage_scope is not None else directory)/('build-'+uuid.uuid4().hex[:16])
            workspace.mkdir(exist_ok=False)
            def prepare(scoped):
                scoped.attach(source)
                for path in fixed:
                    if not path.resolve().is_relative_to(scoped.root):scoped.pin_file(path)
                try:
                    return cls._prepare_locked(directory,source,expected,validate_segment=validate_segment,
                        visual_lanes=visual_lanes,max_record_bytes=max_record_bytes,max_disk_bytes=max_disk_bytes,
                        progress=progress,storage_scope=scoped,workspace=workspace)
                except BaseException:
                    scoped.raise_if_failed();raise
            if storage_scope is not None:
                if not storage_scope.active:raise ValueError('Support index storage scope is not active')
                result=prepare(storage_scope);result.storage_report=storage_scope.report();return result
            with AuxiliaryStorageScope(workspace,max_disk_bytes) as scoped:result=prepare(scoped)
            result.storage_report=scoped.report()
            if progress:progress(dict(auxiliary_storage=result.storage_report))
            return result

    @classmethod
    def _prepare_locked(cls, directory, source, expected, *, validate_segment, visual_lanes,
                max_record_bytes=1024 * 1024, max_disk_bytes=4 * 1024**3, progress=None,
                storage_scope=None,workspace=None):
        """Atomic preparation; an interrupted build is never a reusable index.

        Source must be the existing immutable/query-only connection. SQLite
        sorting and pages spill to disk; decoded payload retention is one row,
        bounded by the same 1 MiB source-record guard as a request.
        """
        from simz1_queue_context import QueueContext, hold_time
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(_json(expected).encode()).hexdigest()
        target = directory / (key + '.sqlite')
        if storage_scope is None or not storage_scope.active or workspace is None:
            raise ValueError('Support preparation requires its owned auxiliary storage scope')
        storage_scope.check('support_prepare_before')
        if target.exists():
            # The receipt is not an authority for exclusions. Before pinning its
            # digest for workers, independently compare EVERY scalar row to the
            # immutable source, including absent, extra and altered rows.
            receipt=json.loads(target.with_suffix('.json').read_text(encoding='utf8'))
            checked=cls(target,expected,expected_sha256=receipt.get('sha256'))
            try:
                storage_scope.attach(checked.connection)
                actual=iter(checked.connection.execute('SELECT '+','.join(FIELDS)+' FROM support ORDER BY journey,id'))
                count=0
                for values,spatial in _scalar_rows(source,validate_segment,visual_lanes,max_record_bytes,with_spatial=True):
                    if next(actual,None)!=values:
                        raise ValueError('Support index derived scalar rows differ from native source')
                    if checked.spatial_links(values[0])!=spatial:
                        raise ValueError('Support index derived spatial support differs from native source')
                    scope=checked.connection.execute('SELECT scope FROM support_scope WHERE record=?',(values[0],)).fetchone()[0]
                    actual_bins=tuple(checked.connection.execute(
                        'SELECT bin,scope FROM temporal_support WHERE record=? ORDER BY bin',(values[0],)))
                    if actual_bins!=tuple((bucket,scope) for bucket in _temporal_bins(values[3],values[4])):
                        raise ValueError('Support index derived temporal coverage differs from native source')
                    count+=1
                    if progress and count%4096==0:progress(dict(records=count,total=receipt['records'],verifying=True))
                if next(actual,None) is not None or count!=receipt['records']:
                    raise ValueError('Support index derived coverage differs from native source')
                _source_unchanged(expected)
                storage_scope.check('support_reuse_verified')
                return checked
            except BaseException:
                checked.close()
                raise
        temporary = Path(workspace)/'index.sqlite'
        connection = sqlite3.connect(temporary)
        try:
            storage_scope.attach(connection)
            connection.execute('PRAGMA cache_size=-8192')
            connection.execute('PRAGMA temp_store=FILE')
            connection.execute('PRAGMA journal_mode=DELETE')
            storage_scope.check('support_schema_before')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            connection.execute('''CREATE TABLE support(
                id INTEGER PRIMARY KEY,journey TEXT NOT NULL,vehicle TEXT NOT NULL,
                start REAL NOT NULL,end REAL NOT NULL,compressed_bytes INTEGER NOT NULL,
                decoded_bytes INTEGER NOT NULL,link TEXT NOT NULL,hold REAL,ordinal INTEGER,
                corridor TEXT,slot INTEGER,transfer_known INTEGER NOT NULL,
                transfer_corridor TEXT,transfer_slot INTEGER,transfer_ordinal INTEGER)''')
            schema='''CREATE TABLE scope(id INTEGER PRIMARY KEY,signature TEXT NOT NULL UNIQUE);
                CREATE TABLE scope_link(scope INTEGER NOT NULL,link TEXT NOT NULL,PRIMARY KEY(scope,link));
                CREATE INDEX scope_link_inverse ON scope_link(link,scope);
                CREATE TABLE support_scope(record INTEGER PRIMARY KEY,scope INTEGER NOT NULL);
                CREATE INDEX support_scope_inverse ON support_scope(scope,record);
                CREATE TABLE temporal_support(bin INTEGER NOT NULL,record INTEGER NOT NULL,scope INTEGER NOT NULL,PRIMARY KEY(bin,record));
                CREATE INDEX temporal_support_record ON temporal_support(record,bin);'''
            for statement in schema.split(';'):
                if statement.strip():connection.execute(statement)
            storage_scope.check('support_schema_after')
            links = visual_lanes.get('links') or {}
            count = decoded_total = compressed_total = 0
            started = time.perf_counter()
            source_count = source.execute('SELECT count(*) FROM segments').fetchone()[0]
            _source_unchanged(expected)
            for values,spatial in _scalar_rows(source,validate_segment,visual_lanes,max_record_bytes,with_spatial=True):
                connection.execute('INSERT INTO support VALUES (' + ','.join('?' for _ in FIELDS) + ')', values)
                signature=hashlib.sha256(_json(spatial).encode()).hexdigest()
                found=connection.execute('SELECT id FROM scope WHERE signature=?',(signature,)).fetchone()
                if found is None:
                    scope=connection.execute('INSERT INTO scope(signature) VALUES (?)',(signature,)).lastrowid
                    connection.executemany('INSERT INTO scope_link VALUES (?,?)',((scope,link) for link in spatial))
                else:scope=found[0]
                connection.execute('INSERT INTO support_scope VALUES (?,?)',(values[0],scope))
                connection.executemany('INSERT INTO temporal_support VALUES (?,?,?)',
                    ((bucket,values[0],scope) for bucket in _temporal_bins(values[3],values[4])))
                count += 1
                decoded_total += values[6]
                compressed_total += values[5]
                if count % 4096 == 0:
                    storage_scope.commit(connection,'support_records_commit')
                    if progress:
                        progress(dict(records=count, total=source_count, seconds=time.perf_counter()-started))
            if count != source_count:
                raise ValueError('Support index source coverage incomplete')
            _source_unchanged(expected)
            connection.execute('CREATE INDEX support_link_time ON support(link,start,end,id)')
            connection.execute('CREATE INDEX support_group_time ON support(corridor,slot,start,end,id)')
            connection.execute('CREATE INDEX support_journey ON support(journey,id)')
            unknown_links = sorted(row[0] for row in connection.execute('SELECT DISTINCT link FROM support') if row[0] not in links)
            connection.executemany('INSERT INTO metadata VALUES (?,?)',
                [('contract', _json(expected)), ('records', str(count)), ('complete', 'true')])
            storage_scope.commit(connection,'support_complete_commit')
            if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise ValueError('Support index integrity failure')
            connection.close()
            storage_scope.check('support_closed')
            receipt = dict(contract=expected, complete=True, records=count, bytes=temporary.stat().st_size,
                           source_decoded_bytes=decoded_total, source_compressed_bytes=compressed_total,
                           peak_decoded_records=1, max_record_bytes=max_record_bytes,
                           sqlite_cache_bytes=8*1024**2, unknown_links=unknown_links,
                           sha256=_sha(temporary), seconds=time.perf_counter()-started,
                           auxiliary_storage=storage_scope.report())
            # A second preparer is an ownership error, not permission to replace.
            if target.exists():
                raise ValueError('Support index was published by another writer')
            os.rename(temporary, target)
            if not target.is_relative_to(storage_scope.root):storage_scope.pin_file(target)
            receipt_raw=_json(receipt).encode('utf8')
            storage_scope.check('support_receipt_before',additional_bytes=len(receipt_raw))
            with target.with_suffix('.json').open('xb') as handle:
                handle.write(receipt_raw);handle.flush();os.fsync(handle.fileno())
            if not target.is_relative_to(storage_scope.root):storage_scope.pin_file(target.with_suffix('.json'))
            storage_scope.check('support_publication_after')
            return cls(target, expected, expected_sha256=receipt['sha256'])
        except BaseException:
            connection.close()
            raise

    def spatial_links(self,ident):
        values=tuple(row[0] for row in self.connection.execute('SELECT link FROM support_scope s JOIN scope_link l ON l.scope=s.scope WHERE s.record=? ORDER BY link',(ident,)))
        if not values:raise ValueError('Support index lacks observed spatial support')
        return values

    def domains_for(self,ident,domains):
        links=self.spatial_links(ident)
        if any(link not in domains for link in links):return None
        return frozenset().union(*(domains[link] for link in links))

    def candidates(self, at, links, limit, *, group=None, order=None, role='hold', link=None, known_links=None):
        # The receipt cannot hide an unknown source link. Source membership is
        # derived from the independently pinned index; geometry membership is
        # supplied by the verified request, never by receipt-controlled text.
        links = set(links) | (self.source_links - set(known_links or ()))
        if not links:
            return []
        # Unknown topology must remain conservative. Callers with a missing
        # domain use the legacy path; known requests additionally retain rows
        # whose source link is outside the verified geometry.
        placeholders = ','.join('?' for _ in links)
        predicate=''
        arguments=[math.floor(at/120),at,at]
        if group is not None and order is not None:
            # Only a supported ordinal certifies a native group. BASE never
            # reads transfers, so an unknown transfer cannot connect otherwise
            # certified foreign groups. Unknown ordinals stay conservative.
            predicate=' AND (ordinal IS NULL'+(' OR transfer_known=0' if role!='base' else '')+''' OR
                (corridor=? AND slot=? AND ordinal<=?)'''
            arguments.extend([*group,order])
            if role!='base':
                predicate+=' OR (transfer_corridor=? AND transfer_slot=? AND transfer_ordinal<?)'
                arguments.extend([*group,order])
            if role in ('hold','final'):
                predicate+=' OR (hold>=start AND hold<end AND hold<=? AND ordinal<=?)'
                arguments.extend([at,order])
            predicate+=')'
        # Without this optimization fence SQLite evaluates the spatial EXISTS
        # for every bin row before it joins support, even when WHERE text puts
        # the exact time/precedence predicates first. Materialize only those
        # scalar candidates, then test the same spatial relation. The final
        # order and limit apply after both filters, exactly as before. Temporary
        # storage retains this connection's FILE policy and 8 MiB page cache.
        rows = self.connection.execute(
            'WITH filtered AS MATERIALIZED (SELECT s.*,t.scope AS spatial_scope'
            ' FROM temporal_support t JOIN support s ON s.id=t.record'
            ' WHERE t.bin=? AND start<=? AND end>?'+predicate+') SELECT '+
            ','.join('s.'+field for field in FIELDS)+' FROM filtered s WHERE EXISTS '
            f'(SELECT 1 FROM scope_link l WHERE l.scope=s.spatial_scope AND l.link IN ({placeholders}))'
            ' ORDER BY s.id LIMIT ?', (*arguments,*sorted(links),limit))
        return [dict(zip(FIELDS, row)) for row in rows]


def _source_unchanged(expected):
    stat=Path(expected['database']).stat()
    if stat.st_size!=expected['database_bytes'] or stat.st_mtime_ns!=expected['database_mtime_ns']:
        raise ValueError('Support index native source changed during preparation')


def _temporal_bins(start,end):
    # Half-open native intervals: exactly one narrow temporal lookup per query.
    # These are scalar index bins, independent of viewer window numbering.
    return range(math.floor(start/120),math.ceil(end/120)) if end>start else range(0)


def _scalar_rows(source, validate_segment, visual_lanes, max_record_bytes,*,with_spatial=False):
    from simz1_queue_context import QueueContext,hold_time
    helper=QueueContext(source,[],validate_segment=validate_segment,validate_trip=lambda row:None,visual_lanes=visual_lanes)
    links=visual_lanes.get('links') or {}
    corridors=visual_lanes.get('occupancy_corridors',{}).get('corridors',{})
    previous=None
    for ident,journey,vehicle,start,end,raw in source.execute(
            'SELECT id,journey,vehicle,start,end,payload FROM segments INDEXED BY segments_journey ORDER BY journey,id'):
        inflater=zlib.decompressobj()
        decoded=inflater.decompress(raw,max_record_bytes+1)
        if len(decoded)>max_record_bytes or inflater.unconsumed_tail or not inflater.eof or inflater.unused_data:
            raise ValueError('Support index source record exceeds guard or has invalid compression')
        record=validate_segment(decoded,journey,vehicle,start,end)
        native,boundary=record.get('Native_Occupancy') or {},record.get('Boundary_Provenance') or {}
        if any(native.get(field) is not None and (not isinstance(native[field],list) or
            any(not isinstance(value,str) or not value for value in native[field])) for field in ('passage_links','exit_links')):
            raise ValueError('Native extended occupancy support is malformed')
        link=record.get('Link_ID')
        if not isinstance(link,str) or not link:raise ValueError('Support index source link missing')
        ordinal=helper.reservation_order(record)
        current=dict(journey=journey,vehicle=vehicle,start=start,end=end,link=link,ordinal=ordinal,
            corridor=native.get('corridor_id'),slot=native.get('model_slot'),agent=record.get('Agent_ID'),
            extra_links=tuple(value for field in ('passage_links','exit_links') for value in (native.get(field) or [])),
            start_relative=boundary.get('start_relative'),end_relative=boundary.get('end_relative'),transfer=(1,None,None,None))
        if previous is not None and previous['journey']==journey:
            if (start,end)<(previous['start'],previous['end']):
                raise ValueError('Support source order differs from renderer temporal neighbor order')
            current['transfer']=_transfer(previous,current,links)
        current['spatial_support']=_spatial_support(current,previous,links,corridors)
        values=(ident,journey,vehicle,start,end,len(raw),len(decoded),link,hold_time(record),ordinal,
               current['corridor'],current['slot'],*current['transfer'])
        yield (values,current['spatial_support']) if with_spatial else values
        previous=current


def _spatial_support(current,previous,links,corridors):
    """Envelope of every observed path a body/release may legitimately inherit.

    It is intentionally a candidate envelope, not a claim that the body fills
    its prefix. Both operands are indexed by this envelope; indexing only the
    root's current link would miss a remote reference with an upstream body.
    """
    own={current['link']}
    own.update(current.get('extra_links',()))
    corridor=corridors.get(current['corridor'])
    if isinstance(corridor,dict):own.update(corridor.get('link_ids') or [])
    connected=(previous is not None and previous['journey']==current['journey'] and
        previous['vehicle']==current['vehicle'] and previous['agent']==current['agent'] and
        previous['end']==current['start'] and previous['end']>previous['start'] and current['end']>current['start'])
    if connected:
        left,right=links.get(previous['link']),links.get(current['link'])
        if (previous['link']!=current['link'] and isinstance(left,dict) and isinstance(right,dict) and
            left.get('to_node') is not None and right.get('from_node') is not None and left['to_node']!=right['from_node']):
            connected=False
    if connected:own.update(previous['spatial_support'])
    return tuple(sorted(own))


def _transfer(previous, current, links):
    """Conservative superset of renderer departureBoundary, without payloads.

    1/None is proved absence; 0 is unknown and therefore cannot exclude an edge.
    Matching topology may overinclude a renderer relation, never delete one.
    """
    absent, unknown = (1,None,None,None), (0,None,None,None)
    if previous['end'] != current['start']:
        return absent
    if (previous['end'] <= previous['start'] or current['end'] <= current['start'] or
            previous['vehicle'] != current['vehicle'] or previous['agent'] != current['agent'] or
            previous['ordinal'] is None or current['ordinal'] is None):
        return unknown
    left, right = links.get(previous['link']), links.get(current['link'])
    if not isinstance(left, dict) or not isinstance(right, dict):
        return unknown
    if previous['link'] == current['link']:
        if previous['end_relative'] is None or current['start_relative'] is None:
            return unknown
        if previous['end_relative'] != current['start_relative']:
            # A self-loop can be a new observed 1 -> 0 occurrence of the same
            # link. Without proving that connection impossible, retain it.
            return unknown
    else:
        if left.get('to_node') is None or right.get('from_node') is None:
            return unknown
        if left['to_node'] != right['from_node']:
            return absent
    if previous['corridor'] != current['corridor']:
        return (1, previous['corridor'], previous['slot'], previous['ordinal'])
    if previous['ordinal'] != current['ordinal'] or previous['slot'] != current['slot']:
        return absent
    return previous['transfer']
