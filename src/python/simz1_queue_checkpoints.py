"""Disk-backed causal task graph for incremental replay anchor preparation.

This graph is evidence preparation, not an HTTP context and not a pose. Every
node has a complete indexed candidate query, its evaluation phase/epoch and all
dependency edges. Source payloads remain in immutable native SQLite; the working
graph and traversal stacks live in an external SQLite with bounded page cache.
"""
from collections import OrderedDict
from functools import wraps
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import secrets
import time
import zlib

from simz1_queue_context import Limits, encoded, hold_time, interval_key, scalar_interval_key, base_predecessor, js_key_before, phase_relations, native_consumer, consumer_base_predecessor, consumer_relations
from simz1_queue_support import FIELDS, AuxiliaryStorageScope


POLICY='native-causal-component-graph-v1'
CHECKPOINT_FIELDS=frozenset(('identity','source_sqlite_sha256','index_sha256','kernel_sha256',
    'geometry_sha256','settings_sha256','record_sha256','candidate_digest','graph_sha256',
    'key','role','epoch','stage','children','generation','release_state_sha256','support_records'))


def bounded_storage(method):
    @wraps(method)
    def bounded(self,*args,**kwargs):
        with self.storage.work('graph.'+method.__name__):return method(self,*args,**kwargs)
    return bounded


def encode_result_payload(wrapper):
    raw=encoded(wrapper)
    if len(raw)>Limits().max_decoded_bytes:raise ValueError('Checkpoint result decoded byte limit')
    return b'QCP1'+zlib.compress(raw,6)


def decode_result_payload(payload):
    # TEXT is supported for small historical fixtures only; normal production
    # persists canonical JSON losslessly compressed and hashes decoded bytes.
    if isinstance(payload,str):
        if len(payload.encode('utf8'))>Limits().max_decoded_bytes:raise ValueError('Checkpoint result storage decoded limit')
        return json.loads(payload)
    if not isinstance(payload,bytes) or not payload.startswith(b'QCP1'):
        raise ValueError('Checkpoint result storage codec invalid')
    inflater=zlib.decompressobj();raw=inflater.decompress(payload[4:],Limits().max_decoded_bytes+1)
    if len(raw)>Limits().max_decoded_bytes or inflater.unconsumed_tail or not inflater.eof or inflater.unused_data:
        raise ValueError('Checkpoint result storage decoded limit or trailing bytes')
    return json.loads(raw)


def checkpoint_digest(wrapper):
    return hashlib.sha256(encoded(wrapper)).hexdigest()


def _checkpoint_contract(expected):
    if not isinstance(expected,dict) or set(expected)-{'absence_proof'}!=CHECKPOINT_FIELDS:
        raise ValueError('Checkpoint contract fields incomplete or unknown')
    identity=expected['identity']
    if (not isinstance(identity,dict) or set(identity)!={'run_id','iteration','run_manifest_sha256'} or
        not isinstance(identity['run_id'],str) or not identity['run_id'] or
        type(identity['iteration']) is not int or identity['iteration']<0):
        raise ValueError('Checkpoint native identity invalid')
    hashes=[identity['run_manifest_sha256']]+[expected[key] for key in CHECKPOINT_FIELDS if key.endswith('_sha256') or key=='candidate_digest']
    if any(not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value) for value in hashes):
        raise ValueError('Checkpoint source/input hash invalid')
    if not isinstance(expected['key'],str) or not expected['key']:
        raise ValueError('Checkpoint record key missing')
    if expected['role'] not in ('base','final','fifo','interpolate'):
        raise ValueError('Checkpoint evaluation phase invalid')
    if type(expected['generation']) is not int or expected['generation']<0:
        raise ValueError('Checkpoint generation invalid')
    if type(expected['epoch']) not in (int,float) or not math.isfinite(expected['epoch']):
        raise ValueError('Checkpoint epoch invalid')
    stage=expected['stage']
    if expected['role']=='fifo' or expected['role']=='interpolate' and stage is not None:
        if (not isinstance(stage,list) or len(stage)!=2 or type(stage[0]) is not int or
            not 0<=stage[0]<=9007199254740991 or not isinstance(stage[1],str) or not stage[1]):
            raise ValueError('Checkpoint phase evaluation stage missing')
    elif stage is not None:raise ValueError('Checkpoint unranked phase stage must be absent')
    children=expected['children']
    if not isinstance(children,list) or any(not isinstance(row,dict) or set(row)!={'key','sha256'} for row in children):
        raise ValueError('Checkpoint dependency certificates missing')
    keys=[]
    for row in children:
        if not isinstance(row['key'],str) or not row['key'] or not isinstance(row['sha256'],str) or len(row['sha256'])!=64 or any(c not in '0123456789abcdef' for c in row['sha256']):
            raise ValueError('Checkpoint dependency certificate invalid')
        keys.append(row['key'])
    if len(set(keys))!=len(keys):raise ValueError('Checkpoint duplicate dependency')
    support=expected['support_records']
    if not isinstance(support,list) or not 1<=len(support)<=Limits().max_records:
        raise ValueError('Checkpoint geometric support missing or exceeds guard')
    ids=set();own=False;support_keys=set()
    for row in support:
        if (not isinstance(row,dict) or set(row)!={'id','record_key','sha256'} or type(row['id']) is not int or row['id']<0 or row['id'] in ids or
            not isinstance(row['record_key'],str) or not row['record_key'] or not isinstance(row['sha256'],str) or len(row['sha256'])!=64 or
            any(c not in '0123456789abcdef' for c in row['sha256'])):
            raise ValueError('Checkpoint geometric support identity invalid')
        ids.add(row['id'])
        if row['record_key'] in support_keys:
            try:times=json.loads(row['record_key'])[3]
            except (ValueError,IndexError,TypeError):raise ValueError('Duplicate checkpoint support identity is not a native instantaneous barrier')
            if (row['record_key']==expected['key'] or not isinstance(times,list) or len(times)!=2 or
                any(type(value) not in (int,float) or not math.isfinite(value) for value in times) or times[0]!=times[1]):
                raise ValueError('Duplicate checkpoint support identity is not auxiliary instantaneous evidence')
        support_keys.add(row['record_key'])
        own|=row['record_key']==expected['key'] and row['sha256']==expected['record_sha256']
    if not own:raise ValueError('Checkpoint geometric support omits own record')
    if 'absence_proof' in expected:
        proof=expected['absence_proof'];occupancy=proof.get('occupancy') if isinstance(proof,dict) else None
        fields={'schema','reason','epoch','occupancy','facility_support_sha256','lane_event_sha256'}
        if (not isinstance(proof,dict) or set(proof)!=fields or proof['schema']!='native-phase-absence-v1' or
            expected['role'] not in ('base','final') or proof['epoch']!=expected['epoch'] or
            proof['reason']!='shared_upstream_without_blocking_facility' or not isinstance(occupancy,dict) or
            set(occupancy)!={'schema','reason','raw_sha256','geometry_sha256'} or
            occupancy['schema']!='native-occupancy-absence-v1' or not isinstance(occupancy['reason'],str) or not occupancy['reason'] or
            occupancy['raw_sha256']!=expected['record_sha256'] or occupancy['geometry_sha256']!=expected['geometry_sha256']):
            raise ValueError('Checkpoint absence proof does not certify its exact input/phase')
        for name in ('facility_support_sha256','lane_event_sha256'):
            value=proof[name]
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Checkpoint absence proof source digest invalid')
    encoded(expected)


def seal_checkpoint(capsule,expected):
    """Package an actually evaluated capsule; this does not evaluate geometry."""
    _checkpoint_contract(expected)
    if (not isinstance(capsule,dict) or capsule.get('schema')!='native-queue-phase-capsule-v1' or
        capsule.get('complete') is not True):
        raise ValueError('Checkpoint capsule is incomplete')
    role=expected['role']
    if role in ('base','final'):
        result=capsule.get(role)
        if 'absence_proof' in expected:
            if (capsule.get('absence_proof')!=expected['absence_proof'] or not isinstance(result,dict) or
                result.get('available') is not False or result.get('anchor_m') is not None or result.get('pose') is not None or
                result.get('pose_available') is not False or result.get('reason')!=expected['absence_proof']['reason']):
                raise ValueError('Checkpoint certified absence cannot contain an anchor/pose')
        elif ('absence_proof' in capsule or not isinstance(result,dict) or type(result.get('anchor_m')) not in (int,float) or not math.isfinite(result['anchor_m'])):
            raise ValueError('Checkpoint anchor is unresolved')
    elif role=='fifo':
        matching=[row for row in capsule.get('fifo',[]) if isinstance(row,dict) and row.get('epoch')==expected['epoch'] and row.get('stage')==expected['stage']]
        if len(matching)!=1 or type(matching[0].get('result',{}).get('available')) is not bool:
            raise ValueError('Checkpoint FIFO pose is unresolved or belongs to another epoch/stage')
        result=matching[0]['result']
        if result['available'] is False and (result.get('center_m') is not None or result.get('pose') is not None):
            raise ValueError('Unavailable FIFO state cannot contain a fabricated pose')
    elif role=='interpolate':
        matching=[row for row in capsule.get('interpolate',[]) if isinstance(row,dict) and row.get('epoch')==expected['epoch'] and row.get('stage')==expected['stage']]
        if len(matching)!=1 or not isinstance(matching[0].get('result'),dict):
            raise ValueError('Checkpoint interpolation input is unresolved')
    encoded(capsule)
    return dict(schema='native-causal-checkpoint-v1',complete=True,contract=expected,capsule=capsule)


def validate_checkpoint(wrapper,expected,trusted_digest):
    """The digest comes from the verified parent, never from this wrapper."""
    _checkpoint_contract(expected)
    if not isinstance(trusted_digest,str) or len(trusted_digest)!=64 or checkpoint_digest(wrapper)!=trusted_digest:
        raise ValueError('Checkpoint differs from independently pinned digest')
    if (not isinstance(wrapper,dict) or wrapper.get('schema')!='native-causal-checkpoint-v1' or
        wrapper.get('complete') is not True or wrapper.get('contract')!=expected):
        raise ValueError('Checkpoint identity/phase/dependency contract mismatch')
    canonical=seal_checkpoint(wrapper.get('capsule'),expected)
    if wrapper!=canonical:raise ValueError('Checkpoint unrecognized envelope fields')
    return wrapper['capsule']


def state_key(segment, epoch, role):
    if type(epoch) in (int,float) and math.isfinite(epoch) and int(epoch)==epoch:epoch=int(epoch)
    return json.dumps([segment,epoch,role],separators=(',',':'),allow_nan=False)


def decode_state_role(role):
    for prefix,kind in (('fifo:','fifo'),('project:','interpolate')):
        if role.startswith(prefix):
            stage=json.loads(role[len(prefix):])
            if (not isinstance(stage,list) or len(stage)!=2 or type(stage[0]) is not int or
                not 0<=stage[0]<=9007199254740991 or not isinstance(stage[1],str) or not stage[1]):
                raise ValueError('Causal state has an invalid evaluation stage')
            return kind,stage
    if role not in ('base','final','interpolate'):raise ValueError('Unknown causal state role')
    return role,None


class CausalGraph:
    """One writer. Published results require a separate JS evaluation phase."""
    def __init__(self,path,context,*,max_disk_bytes=4*1024**3,storage=None):
        self.path=Path(path).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():raise ValueError('Causal graph destination already exists')
        self.context=context
        self._metadata_cache()
        self.index=context.support_index
        if self.index is None or context.domains is None:raise ValueError('Causal graph requires sealed support and geometry')
        self.max_disk_bytes=max_disk_bytes
        self._owns_storage=storage is None
        self.storage=storage if storage is not None else AuxiliaryStorageScope(self.path.parent,max_disk_bytes)
        self.db=None
        try:
            if self._owns_storage:self.storage.__enter__()
            self.db=sqlite3.connect(self.path)
            self.db.execute('PRAGMA cache_size=-8192')
            self.storage.attach(self.db)
            self.storage.attach(context.connection)
            self.storage.attach(self.index.connection)
            self.disk_guard('graph_create.before')
            self.schema('''
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE node(key TEXT PRIMARY KEY,segment INTEGER NOT NULL,epoch REAL NOT NULL,role TEXT NOT NULL,
                    expanded INTEGER NOT NULL DEFAULT 0,candidate_digest TEXT,component INTEGER,finish INTEGER,visited INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX node_pending ON node(expanded,key);
                CREATE INDEX node_component ON node(component,key);
                CREATE TABLE edge(source TEXT NOT NULL,target TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'same_pass',PRIMARY KEY(source,target,kind));
                CREATE INDEX edge_target ON edge(target,source);
                CREATE TABLE root(label TEXT PRIMARY KEY,node TEXT NOT NULL);
                CREATE TABLE stack(position INTEGER PRIMARY KEY,node TEXT NOT NULL,after INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE component(id INTEGER PRIMARY KEY,members INTEGER NOT NULL,status TEXT NOT NULL);
                CREATE TABLE result(node TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL);
            ''')
            self.cache=OrderedDict();self.cache_bytes=0
            self.metrics=dict(expanded_states=0,edges=0,source_payload_reads=0,source_decoded_bytes=0,
                              support_queries=0,support_rows=0,peak_cached_bytes=0,maximum_direct_records=0)
            self.contract=dict(policy=POLICY,source=self.index.receipt['contract'],index_sha256=self.index.receipt['sha256'],
                limits=dict(max_component_records=Limits().max_records,max_component_decoded_bytes=Limits().max_decoded_bytes),
                sources={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in
                         ('simz1_queue_checkpoints.py','simz1_queue_result_trust.py','simz1_queue_component_schedule.py',
                          'simz1_queue_context.py','simz1_queue_support.py','simz1_visual_queues.js','simz1_visual_lanes.js')})
            if self.context.facility_support is not None:self.contract['facility_support']=json.loads(encoded(self.context.facility_support))
            if self.context.classifier_contract is not None:self.contract['classifier_contract']=json.loads(encoded(self.context.classifier_contract))
            self.db.execute('INSERT INTO metadata VALUES (?,?)',('contract',encoded(self.contract).decode()))
            self.commit('graph_create')
        except BaseException:
            self.close();raise

    def close(self):
        try:
            if self.db is not None:
                self.storage.detach(self.db);self.db.close();self.db=None
        finally:
            if self._owns_storage:self.storage.close()

    def schema(self,script):
        # Static DDL only: executescript would implicitly commit pending work.
        self.disk_guard('graph_schema.before')
        if not self.db.in_transaction:self.db.execute('BEGIN')
        for statement in script.split(';'):
            if statement.strip():self.db.execute(statement)
        self.disk_guard('graph_schema.after')

    def commit(self,stage='graph_commit'):
        return self.storage.commit(self.db,stage)

    def _metadata_cache(self):
        if self.context.cache is None:
            from simz1_continuous_replay import RuntimeReadCache
            self.context.cache=RuntimeReadCache(max_bytes=8*1024**2,max_entries=20000)

    def scalar(self,ident):
        row=self.index.connection.execute('SELECT '+','.join(FIELDS)+' FROM support WHERE id=?',(ident,)).fetchone()
        if row is None:raise ValueError('Causal graph source reference missing')
        return dict(zip(FIELDS,row))

    def record(self,ident):
        if ident in self.cache:
            self.cache.move_to_end(ident);return self.cache[ident][0]
        row=self.context.query('SELECT journey,vehicle,start,end,payload FROM segments WHERE id=?',(ident,)).fetchone()
        if row is None:raise ValueError('Causal graph native record missing')
        journey,vehicle,start,end,raw=row
        decoded=self.context.decode(raw)
        record=self.context.validate_segment(decoded,journey,vehicle,start,end)
        cost=len(decoded)*4+512
        while self.cache and self.cache_bytes+cost>8*1024**2:
            _,(_,size)=self.cache.popitem(last=False);self.cache_bytes-=size
        if cost<=8*1024**2:self.cache[ident]=(record,cost);self.cache_bytes+=cost
        self.metrics['source_payload_reads']+=1
        self.metrics['source_decoded_bytes']+=len(decoded)
        self.metrics['peak_cached_bytes']=max(self.metrics['peak_cached_bytes'],self.cache_bytes)
        return record

    def previous(self,scalar):
        row=self.index.connection.execute('SELECT id FROM support INDEXED BY support_journey '
            'WHERE journey=? AND id<? ORDER BY id DESC LIMIT 1',(scalar['journey'],scalar['id'])).fetchone()
        return self.scalar(row[0]) if row else None

    def consumer(self,scalar):
        known=native_consumer(scalar)
        if known is not None:return known
        if self.context.phase_classifier is None:return None
        return self.context.classify_consumer(scalar['id'],self.record(scalar['id']))

    @staticmethod
    def hold(scalar):
        value=scalar['hold']
        return value if value is not None and scalar['start']<=value<scalar['end'] else None

    def add(self,ident,epoch,role):
        key=state_key(ident,epoch,role)
        self.db.execute('INSERT OR IGNORE INTO node(key,segment,epoch,role) VALUES (?,?,?,?)',(key,ident,epoch,role))
        return key

    def root(self,label,ident):
        scalar=self.scalar(ident);at=self.hold(scalar)
        if at is None:raise ValueError('Causal root has no valid HOLD epoch')
        key=self.add(ident,at,'final')
        self.db.execute('INSERT INTO root VALUES (?,?)',(label,key));self.commit()

    def dependencies(self,ident,at,role):
        # The independently verified support index already fixes every field
        # used for dependency identities. Supported native orders expand from
        # scalars only. Unsupported orders may need one bounded source-backed
        # absence proof; evaluation independently validates their JS predicate.
        own=self.scalar(ident);own_key=scalar_interval_key(own)
        if not own['start']<=at<own['end']:raise ValueError('Causal node epoch outside observed interval')
        own_consumer=self.consumer(own)
        group=(own['corridor'],own['slot']);native_order=own['ordinal']
        order=own_consumer['visual_order'] if own_consumer is not None and own_consumer['represented'] else native_order
        fifo=role.startswith('fifo:');project=role.startswith('project:');scope='fifo' if fifo else role
        rank,stage_key=json.loads(role.split(':',1)[1]) if fifo or project else (order,own_key)
        if native_order is None and (fifo or role in ('base','final')):
            absence=self.context.phase_absence(self.record(ident),at,role)
            if absence is not None:
                return [],hashlib.sha256(encoded(dict(epoch=at,role=role,absence=absence))).hexdigest()
        neighbors=self.index.domains_for(ident,self.context.domains)
        if neighbors is None:raise ValueError('Causal node lacks verified spatial domain')
        query_group=group if own_consumer is None or own_consumer['occupancy'] else (None,None)
        rows=[] if role=='interpolate' or project else self.index.candidates(at,neighbors,Limits().max_rows+1,
            group=query_group,order=order,role=scope,link=own['link'],known_links=self.context.domains)
        self.metrics['support_queries']+=role!='interpolate' and not project
        self.metrics['support_rows']+=len(rows)
        if len(rows)>Limits().max_rows:raise ValueError('Direct causal candidate query exceeds row guard')
        required=set();classifications={}
        if own_consumer is not None and own_consumer.get('proof') is not None:classifications[own['id']]=own_consumer['proof']
        def edge(number,epoch,phase,kind='same_pass'):required.add((number,epoch,phase,kind))
        def release(scalar):
            prior=self.previous(scalar)
            if prior is not None and prior['end']==scalar['start'] and self.hold(prior) is not None:
                edge(prior['id'],self.hold(prior),'final','release')
        if role=='final':edge(ident,at,'base')
        for other in rows:
            if other['id']==ident:continue
            other_consumer=self.consumer(other)
            if other_consumer is not None and other_consumer.get('proof') is not None:classifications[other['id']]=other_consumer['proof']
            unknown,same,transfer,geometric=consumer_relations(own_consumer,own,own_key,other_consumer,other,scope,at)
            needed=(consumer_base_predecessor(own_consumer,own_key,other_consumer,scalar_interval_key(other)) if scope=='base' else
                unknown or same or transfer or geometric)
            if not needed:continue
            hold=self.hold(other)
            if scope=='base':
                if hold is not None:edge(other['id'],hold,'base')
                if hold is None or at<hold:
                    edge(other['id'],at,'interpolate');release(other)
            else:
                other_key=scalar_interval_key(other)
                visual_order=other_consumer['visual_order'] if other_consumer is not None and other_consumer['represented'] else other['ordinal']
                earlier=(rank is None or visual_order is None or visual_order<rank or
                         visual_order==rank and js_key_before(other_key,stage_key))
                phase='final' if earlier else 'base'
                if hold is not None:edge(other['id'],hold,phase)
                if hold is None or at<hold:
                    stage=json.dumps([rank,stage_key],separators=(',',':'))
                    if unknown or same or fifo and transfer:edge(other['id'],at,'fifo:'+stage)
                    if role=='final' and (unknown or transfer):edge(other['id'],at,'project:'+stage)
        hold=self.hold(own)
        if (fifo or project) and hold is not None:
            earlier=(order is None or rank is None or order<rank or order==rank and js_key_before(own_key,stage_key))
            edge(ident,hold,'final' if earlier else 'base')
        if role=='interpolate' and hold is not None:edge(ident,hold,'base')
        # All phase signatures and body poses use desiredStart/lower, even when
        # the anchor itself does not move. The release is a previous-generation
        # input, never an artificial same-generation reciprocal edge.
        release(own)
        direct_records=len({item[0] for item in required}|{ident})
        self.metrics['maximum_direct_records']=max(self.metrics['maximum_direct_records'],direct_records)
        if direct_records>Limits().max_records:raise ValueError('Direct causal component exceeds record guard')
        evidence=dict(epoch=at,role=role,group=group,native_ordinal=native_order,visual_order=order,
            classifications=classifications,links=sorted(neighbors),rows=rows)
        return sorted(required),hashlib.sha256(encoded(evidence)).hexdigest()

    @bounded_storage
    def expand(self,progress=None):
        from simz1_replay_work import checkpoint
        started=time.perf_counter()
        while True:
            row=self.db.execute('SELECT key,segment,epoch,role FROM node WHERE expanded=0 ORDER BY key LIMIT 1').fetchone()
            if row is None:break
            key,ident,epoch,role=row
            dependencies,digest=self.dependencies(ident,epoch,role)
            for item in dependencies:
                number,at,phase=item[:3]
                kind=item[3] if len(item)>3 else 'same_pass'
                target=self.add(number,at,phase)
                self.db.execute('INSERT OR IGNORE INTO edge(source,target,kind) VALUES (?,?,?)',(key,target,kind))
            self.db.execute('UPDATE node SET expanded=1,candidate_digest=? WHERE key=?',(digest,key))
            self.metrics['expanded_states']+=1
            if self.metrics['expanded_states']%256==0:
                checkpoint('queue_checkpoint_graph',states=self.metrics['expanded_states'])
                self.commit()
                # The complete edge count is measured once after expansion;
                # its initial placeholder is not an observed zero in progress.
                if progress:progress(dict({name:value for name,value in self.metrics.items() if name!='edges'},
                    seconds=time.perf_counter()-started))
        self.metrics['edges']=self.db.execute('SELECT count(*) FROM edge').fetchone()[0]
        self.db.execute('INSERT INTO metadata VALUES (?,?)',('graph_complete','true'))
        self.db.execute('INSERT INTO metadata VALUES (?,?)',('metrics',encoded(self.metrics).decode()))
        self.commit()
        return self.metrics

    def disk_guard(self,stage='graph_disk_guard'):
        return self.storage.check(stage)

    def capture_rejected_packet(self,packet,generation,components,kernel_contract,error):
        """Best-effort bounded evidence. It never changes the rejected result.

        max_disk_bytes is the remaining auxiliary budget after the immutable
        index. Count the entire owned graph directory, including journals and
        older diagnostics. The packet is losslessly compacted by the same
        bridge codec; its expanded native budget still applies.
        """
        from simz1_queue_checkpoint import compact_component_packet
        self.last_rejection_diagnostic=dict(status='not_written')
        temporary=None
        try:
            directory=self.path.parent
            def remaining():
                report=self.storage.check('rejected_packet')
                return self.storage.max_disk_bytes-report['observed_bytes']
            wire,expanded=compact_component_packet(packet)
            if len(packet.get('records',[]))>Limits().max_records or expanded>Limits().max_decoded_bytes:
                raise ValueError('Rejected diagnostic packet exceeds original component guard')
            metadata=dict(schema='native-queue-rejected-component-v1',accepted=False,generation=generation,
                components=components,requests=packet.get('requests',[]),expanded_packet_bytes=expanded,
                source_contract=self.contract,kernel_contract=kernel_contract,
                source_snapshot={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                    for name in self.contract.get('sources',{})},
                exception=dict(type=type(error).__name__,message=str(error)[:4096]))
            stem='rejected-g'+str(generation)+'-'+secrets.token_hex(12)
            encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
            for full in (True,False):
                available=remaining()
                if available<1024:break
                envelope=dict(metadata,packet=wire) if full else dict(metadata,packet=None,packet_omitted='remaining_auxiliary_budget')
                temporary=directory/(stem+('.packet' if full else '.metadata')+'.json.gz.tmp')
                destination=temporary.with_suffix('')
                compressed=zlib.compressobj(6,zlib.DEFLATED,31);logical=written=0
                try:
                    with temporary.open('xb') as handle:
                        for fragment in encoder.iterencode(envelope):
                            raw=fragment.encode('utf8');logical+=len(raw)
                            if logical>Limits().max_decoded_bytes:raise ValueError('Diagnostic envelope decoded guard')
                            chunk=compressed.compress(raw)
                            if written+len(chunk)>available:raise ValueError('Diagnostic auxiliary disk guard')
                            handle.write(chunk);written+=len(chunk)
                        chunk=compressed.flush()
                        if written+len(chunk)>available:raise ValueError('Diagnostic auxiliary disk guard')
                        handle.write(chunk);written+=len(chunk);handle.flush();os.fsync(handle.fileno())
                    if remaining()<0:raise ValueError('Diagnostic auxiliary disk guard')
                    # rename is exclusive on Windows, and the random destination
                    # was never an input/receipt or a prior diagnostic.
                    if destination.exists():raise ValueError('Diagnostic destination already exists')
                    temporary.rename(destination);temporary=None
                    self.last_rejection_diagnostic=dict(status='packet' if full else 'metadata',path=str(destination),
                        compressed_bytes=written,decoded_bytes=logical,expanded_packet_bytes=expanded)
                    return
                except (OSError,ValueError):
                    if temporary.exists():temporary.unlink()
                    temporary=None
                    if not full:raise
            self.last_rejection_diagnostic=dict(status='not_written',reason='remaining_auxiliary_budget')
        except Exception as diagnostic_error:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
            self.last_rejection_diagnostic=dict(status='not_written',reason=type(diagnostic_error).__name__+': '+str(diagnostic_error)[:512])

    @bounded_storage
    def components(self,progress=None):
        """Kosaraju with both DFS stacks and membership on disk, not objects."""
        self.require_complete_graph()
        finish=0
        for (root,) in self.db.execute('SELECT key FROM node ORDER BY key'):
            if self.db.execute('SELECT visited FROM node WHERE key=?',(root,)).fetchone()[0]:continue
            self.db.execute('INSERT INTO stack(node,after) VALUES (?,0)',(root,))
            while True:
                row=self.db.execute('SELECT position,node,after FROM stack ORDER BY position DESC LIMIT 1').fetchone()
                if row is None:break
                position,node,after=row
                self.db.execute('DELETE FROM stack WHERE position=?',(position,))
                if after:
                    finish+=1;self.db.execute('UPDATE node SET finish=? WHERE key=?',(finish,node));continue
                if self.db.execute('SELECT visited FROM node WHERE key=?',(node,)).fetchone()[0]:continue
                self.db.execute('UPDATE node SET visited=1 WHERE key=?',(node,))
                self.db.execute('INSERT INTO stack(node,after) VALUES (?,1)',(node,))
                self.db.execute('INSERT INTO stack(node,after) SELECT target,0 FROM edge JOIN node n ON n.key=edge.target '
                    "WHERE source=? AND edge.kind='same_pass' AND n.visited=0 ORDER BY target DESC",(node,))
            self.commit()
        component=0;maximum=0
        for (root,) in self.db.execute('SELECT key FROM node ORDER BY finish DESC'):
            if self.db.execute('SELECT component FROM node WHERE key=?',(root,)).fetchone()[0] is not None:continue
            component+=1;members=0
            self.db.execute('UPDATE node SET component=? WHERE key=?',(component,root))
            self.db.execute('INSERT INTO stack(node) VALUES (?)',(root,))
            while True:
                row=self.db.execute('SELECT position,node FROM stack ORDER BY position DESC LIMIT 1').fetchone()
                if row is None:break
                position,node=row;self.db.execute('DELETE FROM stack WHERE position=?',(position,));members+=1
                self.db.execute('INSERT INTO stack(node) SELECT source FROM edge JOIN node n ON n.key=edge.source '
                    "WHERE target=? AND edge.kind='same_pass' AND n.component IS NULL ORDER BY source",(node,))
                self.db.execute('UPDATE node SET component=? WHERE component IS NULL AND key IN (SELECT node FROM stack)',(component,))
            # Several phases/epochs of one record are states, not extra bodies.
            records=self.db.execute('SELECT count(DISTINCT segment) FROM node WHERE component=?',(component,)).fetchone()[0]
            if records>Limits().max_records:raise ValueError('Reciprocal causal component exceeds original record guard')
            maximum=max(maximum,records)
            self.db.execute('INSERT INTO component VALUES (?,?,?)',(component,members,'unevaluated'))
            if component%256==0:
                self.commit()
                if progress:progress(dict(components=component,maximum_records=maximum))
        summary=dict(count=component,maximum_records=maximum,
                     cyclic_components=self.db.execute('SELECT count(*) FROM component c WHERE members>1 OR EXISTS('
                         'SELECT 1 FROM node n JOIN edge e ON e.source=n.key AND e.target=n.key '
                         "WHERE n.component=c.id AND e.kind='same_pass')").fetchone()[0])
        self.db.execute('INSERT INTO metadata VALUES (?,?)',('components',encoded(summary).decode()))
        self.commit();return summary

    def ready_components(self):
        # Dependencies have greater Kosaraju ids with this source->dependency
        # graph. Query explicitly nonetheless; never infer an arbitrary order.
        self.require_complete_graph()
        if self.db.execute("SELECT 1 FROM metadata WHERE key='components'").fetchone() is None:
            raise ValueError('Causal components have not been completely verified')
        return self.db.execute('''SELECT c.id FROM component c WHERE c.status='unevaluated' AND NOT EXISTS(
            SELECT 1 FROM node n JOIN edge e ON e.source=n.key JOIN node child ON child.key=e.target
            JOIN component dependency ON dependency.id=child.component
            WHERE n.component=c.id AND e.kind='same_pass' AND child.component<>c.id AND dependency.status<>'resolved') ORDER BY c.id DESC''')

    def require_complete_graph(self):
        if (self.db.execute("SELECT value FROM metadata WHERE key='graph_complete'").fetchone()!=('true',) or
                self.db.execute('SELECT 1 FROM node WHERE expanded<>1 OR candidate_digest IS NULL LIMIT 1').fetchone()):
            raise ValueError('Causal graph candidate coverage is incomplete')

    @bounded_storage
    def structural_digest(self):
        self.require_complete_graph()
        if self.db.execute('SELECT 1 FROM edge e LEFT JOIN node a ON a.key=e.source LEFT JOIN node b ON b.key=e.target '
                           'WHERE a.key IS NULL OR b.key IS NULL LIMIT 1').fetchone():
            raise ValueError('Causal graph contains a dangling dependency')
        if self.db.execute('SELECT 1 FROM root r LEFT JOIN node n ON n.key=r.node WHERE n.key IS NULL LIMIT 1').fetchone():
            raise ValueError('Causal graph root missing')
        if self.db.execute('SELECT 1 FROM node WHERE component IS NULL LIMIT 1').fetchone():
            raise ValueError('Causal graph component partition incomplete')
        if self.db.execute('SELECT 1 FROM component c WHERE members<>(SELECT count(*) FROM node n WHERE n.component=c.id) LIMIT 1').fetchone():
            raise ValueError('Causal component membership mismatch')
        digest=hashlib.sha256()
        for label,sql in [('contract',"SELECT key,value FROM metadata WHERE key='contract'"),
            ('root','SELECT label,node FROM root ORDER BY label'),
            ('node','SELECT key,segment,epoch,role,candidate_digest,component FROM node ORDER BY key'),
            ('edge','SELECT source,target,kind FROM edge ORDER BY source,target,kind')]:
            digest.update(label.encode())
            for row in self.db.execute(sql):digest.update(encoded(row));digest.update(b'\n')
        return digest.hexdigest()

    @classmethod
    def open_graph(cls,path,context,expected_digest,*,storage=None):
        """Open only a caller-pinned graph; untrusted receipts are insufficient."""
        result=cls.__new__(cls)
        result.path=Path(path).resolve(strict=True);result.context=context;result.index=context.support_index
        result._metadata_cache()
        result.max_disk_bytes=4*1024**3
        result._owns_storage=storage is None
        result.storage=storage if storage is not None else AuxiliaryStorageScope(result.path.parent,result.max_disk_bytes)
        result.db=None
        try:
            if result._owns_storage:result.storage.__enter__()
            result.db=sqlite3.connect(result.path)
            result.db.execute('PRAGMA cache_size=-8192');result.storage.attach(result.db)
            result.storage.attach(context.connection);result.storage.attach(result.index.connection)
            result.contract=json.loads(result.db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
            result.metrics=json.loads(result.db.execute("SELECT value FROM metadata WHERE key='metrics'").fetchone()[0])
            result.cache=OrderedDict();result.cache_bytes=0
            if result.contract['index_sha256']!=result.index.receipt['sha256'] or result.structural_digest()!=expected_digest:
                raise ValueError('Causal graph differs from independent verified input')
            return result
        except BaseException:
            result.close();raise

    @bounded_storage
    def _evaluation_schema(self):
        if not self.db.in_transaction:self.db.execute('BEGIN')
        columns=[row[1] for row in self.db.execute('PRAGMA table_info(result)')]
        if 'generation' not in columns:
            if self.db.execute('SELECT 1 FROM result LIMIT 1').fetchone():
                raise ValueError('Legacy evaluation results cannot be silently migrated')
            self.db.execute('ALTER TABLE result RENAME TO empty_legacy_result')
            self.db.execute('CREATE TABLE result(generation INTEGER NOT NULL,node TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(generation,node))')
        self.schema('''CREATE TABLE IF NOT EXISTS evaluation(generation INTEGER,component INTEGER,status TEXT,PRIMARY KEY(generation,component));
            CREATE TABLE IF NOT EXISTS release_state(generation INTEGER,key TEXT,payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(generation,key));
            CREATE TABLE IF NOT EXISTS recipe(generation INTEGER,key TEXT,payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(generation,key));
            CREATE TABLE IF NOT EXISTS native_key(segment INTEGER PRIMARY KEY,key TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS observation_limit(node TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(node,reason));
            CREATE TABLE IF NOT EXISTS generation(number INTEGER PRIMARY KEY,status TEXT,release_digest TEXT,changed INTEGER,metrics TEXT);
            CREATE TABLE IF NOT EXISTS generation_seal(generation INTEGER PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS generation_archive(generation INTEGER PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL);''')
        self.commit()

    def _seal_signature(self,payload):
        if not hasattr(self,'_retention_secret'):raise ValueError('Generation retention has no live producer authority')
        return hmac.new(self._retention_secret,b'generation-seal-v1\0'+payload.encode(),hashlib.sha256).hexdigest()

    def _checked_seal(self,generation,payload,signature):
        if not hmac.compare_digest(self._seal_signature(payload),signature):
            raise ValueError('Generation seal differs from private producer HMAC')
        value=json.loads(payload)
        if value.get('schema')!='native-causal-generation-seal-v1' or value.get('generation')!=generation:
            raise ValueError('Generation seal identity differs')
        return value

    def verify_generation_chain(self):
        previous='0'*64;expected=0;archived=-1;archive_tip='0'*64
        for generation,payload,signature,kind in self.db.execute(
                "SELECT generation,payload,signature,'live' FROM generation_seal UNION ALL "
                "SELECT generation,payload,signature,'archive' FROM generation_archive ORDER BY generation"):
            value=self._checked_seal(generation,payload,signature)
            if generation!=expected or value.get('previous_seal_sha256')!=previous:
                raise ValueError('Generation archive chain is missing, reordered or self-rehashed')
            previous=hashlib.sha256(payload.encode()).hexdigest();expected+=1
            if kind=='archive':
                if generation!=archived+1:raise ValueError('Archived generations are not a contiguous prefix')
                archived=generation;archive_tip=previous
        if (expected!=self._last_completed+1 or previous!=self._seal_tip or
                archived!=self._last_archived or archive_tip!=self._archive_tip):
            raise ValueError('Generation chain differs from independent live frontier')
        return dict(last_completed=self._last_completed,seal_tip=self._seal_tip,
            archived_through=self._last_archived,archive_tip=self._archive_tip)

    def _generation_material(self,generation,*,verify_payloads=False):
        trust=self.result_trust.get(generation);schedule=self._schedules.get(generation)
        if trust is None or schedule is None:raise ValueError('Generation has no live result/schedule authority')
        header=self.db.execute('SELECT status,release_digest,changed FROM generation WHERE number=?',(generation,)).fetchone()
        if (header is None or header[0]!='resolved' or header[1]!=self.release_digests.get(generation) or
                type(header[2]) is not int or header[2]<0):raise ValueError('Generation barrier is not resolved')
        barrier=schedule.verify_complete()
        if (self.db.execute('SELECT count(*) FROM evaluation WHERE generation=?',(generation,)).fetchone()[0]!=barrier['components'] or
                self.db.execute("SELECT 1 FROM evaluation e LEFT JOIN component c ON c.id=e.component WHERE e.generation=? AND (e.status<>'resolved' OR c.id IS NULL) LIMIT 1",(generation,)).fetchone()):
            raise ValueError('Generation component publication coverage differs')
        def results():
            for node,payload,digest in self.db.execute('SELECT node,payload,sha256 FROM result WHERE generation=? ORDER BY node',(generation,)):
                if generation in self._digest_only:
                    if payload!=b'':raise ValueError('Digest-only generation payload sentinel changed')
                elif verify_payloads:
                    wrapper=decode_result_payload(payload)
                    if checkpoint_digest(wrapper)!=digest or wrapper['contract']['generation']!=generation:
                        raise ValueError('Archived generation result payload differs from verified digest')
                yield node,digest
        result_seal=trust.seal_complete(results())
        counts={};digests={}
        expected=self.db.execute('SELECT count(DISTINCT segment) FROM node').fetchone()[0]
        for table in ('recipe','release_state'):
            stream=hashlib.sha256((table+'-generation-v1\0').encode());count=0
            for key,payload,signature in self.db.execute('SELECT key,payload,signature FROM '+table+' WHERE generation=? ORDER BY key',(generation,)):
                self._derived_value(table,generation,key,(payload,signature))
                stream.update(encoded((key,payload)));stream.update(b'\n');count+=1
                if count%256==0:self.disk_guard('generation_material.'+table)
            if count!=expected:raise ValueError('Generation '+table+' coverage differs')
            counts[table]=count;digests[table]=stream.hexdigest()
        return dict(generation=generation,graph_sha256=self.evaluation_static['graph_sha256'],
            source_contract_sha256=hashlib.sha256(encoded(self.contract)).hexdigest(),
            input_release_sha256=header[1],changed=header[2],results=result_seal,
            barrier=barrier,counts=counts,digests=digests)

    def seal_generation(self,generation,changed):
        if generation!=self._last_completed+1:raise ValueError('Generation seal is not at the synchronous barrier')
        self.verify_generation_chain()
        material=self._generation_material(generation)
        if material['changed']!=changed:raise ValueError('Generation changed counter differs from evaluated release barrier')
        value=dict(schema='native-causal-generation-seal-v1',generation=generation,
            previous_seal_sha256=self._seal_tip,material=material)
        payload=encoded(value).decode();signature=self._seal_signature(payload)
        self.db.execute('INSERT INTO generation_seal VALUES (?,?,?)',(generation,payload,signature))
        self.commit('generation_seal')
        self._last_completed=generation;self._seal_tip=hashlib.sha256(payload.encode()).hexdigest()

    @bounded_storage
    def prune_generations(self,current_generation):
        """At entry to g, retain g-1 and remove only verified generations <=g-2."""
        if (type(current_generation) is not int or current_generation<0 or
                current_generation!=self._last_completed+1):
            raise ValueError('Premature generation cleanup before the synchronous barrier')
        self.verify_generation_chain()
        target=current_generation-2
        if current_generation==0:return
        # The required previous generation must remain authenticated. Checking
        # its scalar results does not grant trust to its payloads: every future
        # payload read still checks its digest against that private result root.
        previous=self.db.execute('SELECT payload,signature FROM generation_seal WHERE generation=?',(current_generation-1,)).fetchone()
        if previous is None:raise ValueError('Previous generation seal is missing')
        previous_seal=self._checked_seal(current_generation-1,*previous)
        if self._generation_material(current_generation-1,verify_payloads=True)!=previous_seal['material']:
            raise ValueError('Previous generation changed before retention cleanup')
        tables=('result','evaluation','recipe','release_state','result_trust_auth','result_trust_leaf',
                'result_trust_generation','component_schedule_dependency','component_schedule_node','component_schedule_generation')
        for generation in range(self._last_archived+1,target+1):
            row=self.db.execute('SELECT payload,signature FROM generation_seal WHERE generation=?',(generation,)).fetchone()
            if row is None:raise ValueError('Generation scheduled for cleanup has no authenticated seal')
            seal=self._checked_seal(generation,*row)
            if self._generation_material(generation,verify_payloads=True)!=seal['material']:
                raise ValueError('Old generation changed before authenticated archive')
            self.db.execute('INSERT INTO generation_archive VALUES (?,?,?)',(generation,*row))
            self.db.execute('DELETE FROM generation_seal WHERE generation=?',(generation,))
            self.commit('generation_archive.publish')
            for table in tables:
                while True:
                    deleted=self.db.execute('DELETE FROM '+table+' WHERE rowid IN (SELECT rowid FROM '+table+' WHERE generation=? LIMIT 256)',(generation,)).rowcount
                    self.commit('generation_archive.delete.'+table)
                    if deleted<256:break
            self.db.execute("UPDATE generation SET status='archived' WHERE number=?",(generation,))
            self.commit('generation_archive.finished')
            self.result_trust.pop(generation);self.release_digests.pop(generation);self._schedules.pop(generation)
            self._digest_only.discard(generation)
            self._last_archived=generation;self._archive_tip=hashlib.sha256(row[0].encode()).hexdigest()
        # Previous-generation consumers use only authenticated result digests
        # and the HMAC release/recipe maps. Payloads have just been verified in
        # full and cannot be read by same-pass consumers in the new generation.
        previous_generation=current_generation-1
        cursor=''
        while True:
            rows=self.db.execute('SELECT node FROM result WHERE generation=? AND node>? ORDER BY node LIMIT 256',
                (previous_generation,cursor)).fetchall()
            if not rows:break
            upper=rows[-1][0]
            changed=self.db.execute("UPDATE result SET payload=x'' WHERE generation=? AND node>? AND node<=?",
                (previous_generation,cursor,upper)).rowcount
            if changed!=len(rows):raise ValueError('Generation payload coverage changed during retirement')
            self.commit('generation_retention.payloads');cursor=upper
        self._digest_only.add(previous_generation)
        state=self.verify_generation_chain()
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('generation_retention',encoded(state).decode()))
        self.commit('generation_retention.metadata')

    def _native_key(self,number):
        row=self.db.execute('SELECT key FROM native_key WHERE segment=?',(number,)).fetchone()
        if row:return row[0]
        key=interval_key(self.record(number));self.db.execute('INSERT INTO native_key VALUES (?,?)',(number,key));return key

    def _derived_signature(self,table,generation,key,payload):
        if not hasattr(self,'derived_secret'):raise ValueError('Derived state lacks private producer authentication')
        return hmac.new(self.derived_secret,encoded((table,generation,key,payload)),hashlib.sha256).hexdigest()

    def _derived_value(self,table,generation,key,row):
        if row is None:raise ValueError('Required derived '+table+' state is absent')
        payload,signature=row
        if not hmac.compare_digest(self._derived_signature(table,generation,key,payload),signature):
            raise ValueError('Derived '+table+' state differs from the live producer')
        return json.loads(payload)

    def _release_for(self,key,generation):
        if generation==0:return None
        row=self.db.execute('SELECT payload,signature FROM release_state WHERE generation=? AND key=?',(generation-1,key)).fetchone()
        return self._derived_value('release_state',generation-1,key,row)

    def _release_digest(self,generation):
        digest=hashlib.sha256(b'native-release-state-v1\n')
        if generation:
            for key,payload,signature in self.db.execute('SELECT key,payload,signature FROM release_state WHERE generation=? ORDER BY key',(generation-1,)):
                self._derived_value('release_state',generation-1,key,(payload,signature))
                digest.update(encoded((key,payload)));digest.update(b'\n')
        return digest.hexdigest()

    @staticmethod
    def _merge_capsule(target,addition):
        if not target:return json.loads(encoded(addition))
        for name in ('schema','complete','input','settings','prepared','release'):
            if target.get(name)!=addition.get(name):raise ValueError('Checkpoint phase inputs differ within one generation: '+name)
        for name in ('base','final'):
            if name in addition:
                if name in target and target[name]!=addition[name]:raise ValueError('Conflicting checkpoint '+name)
                target[name]=addition[name]
        for name in ('fifo','interpolate'):
            values={(row['epoch'],encoded(row['stage'])):row for row in target.get(name,[])}
            for row in addition.get(name,[]):
                key=(row['epoch'],encoded(row['stage']))
                if key in values and values[key]!=row:raise ValueError('Conflicting checkpoint '+name+' epoch')
                values[key]=row
            if values:target[name]=list(values.values())
        return target

    def _packet(self,component,generation):
        if generation in getattr(self,'_digest_only',set()):
            raise ValueError('Previous generation payloads were retired after authenticated sealing')
        nodes=self.db.execute('SELECT key,segment,epoch,role,candidate_digest FROM node WHERE component=? ORDER BY key',(component,)).fetchall()
        if len(nodes)>Limits().max_records:raise ValueError('Causal SCC evaluation state limit')
        direct=self.db.execute('SELECT DISTINCT child.key,child.segment FROM node parent JOIN edge e ON e.source=parent.key '
            "JOIN node child ON child.key=e.target WHERE parent.component=? AND child.component<>? AND e.kind='same_pass' ORDER BY child.key",(component,component)).fetchall()
        capsules={};child_rows={}
        for key,number in direct:
            row=self.db.execute('SELECT payload,sha256 FROM result WHERE generation=? AND node=?',(generation,key)).fetchone()
            if row is None:raise ValueError('Topological evaluation is missing a same-generation dependency')
            if not hasattr(self,'result_trust') or generation not in self.result_trust:
                raise ValueError('Checkpoint producer has no private result authoring root')
            self.result_trust[generation].verify(key,row[1])
            wrapper=decode_result_payload(row[0])
            node=self.db.execute('SELECT epoch,role,candidate_digest FROM node WHERE key=?',(key,)).fetchone()
            kind,stage=decode_state_role(node[1])
            expected=dict(wrapper['contract'])
            expected.update(self.evaluation_static,generation=generation,release_state_sha256=self.release_digests[generation],
                record_sha256=hashlib.sha256(encoded(self.record(number))).hexdigest(),key=self._native_key(number),
                epoch=node[0],role=kind,stage=stage,candidate_digest=node[2])
            if 'absence_proof' in expected:
                expected['absence_proof']=self.context.phase_absence(self.record(number),node[0],node[1])
            capsule=validate_checkpoint(wrapper,expected,row[1])
            marker_key=self._native_key(number)
            if 'absence_proof' not in expected:
                capsules[marker_key]=self._merge_capsule(capsules.get(marker_key),capsule)
            child_rows[key]=row[1]
        primary={row[1] for row in nodes}|{row[1] for row in direct}
        records={number:self.record(number) for number in primary}
        # Children already carry their geometric pose/trace; only adjacent
        # identity rows are needed to check their prepared boundary signatures.
        for number in sorted(primary):
            scalar=self.scalar(number)
            for operator,order in (('<','DESC'),('>','ASC')):
                row=self.index.connection.execute('SELECT id FROM support INDEXED BY support_journey '
                    f'WHERE journey=? AND id{operator}? ORDER BY id {order} LIMIT 1',(scalar['journey'],number)).fetchone()
                if row is not None:records[row[0]]=self.record(row[0])
        # Fresh component members have no stored rigid rear yet. Preserve their
        # actual observed prefixes; this never makes auxiliary HOLDs certified.
        journeys={}
        for _,number,_,_,_ in nodes:
            scalar=self.scalar(number);journeys[scalar['journey']]=max(journeys.get(scalar['journey'],0),number)
        for journey,last in sorted(journeys.items()):
            for (number,) in self.index.connection.execute('SELECT id FROM support INDEXED BY support_journey WHERE journey=? AND id<=? ORDER BY id',(journey,last)):
                if len(records)>=Limits().max_records and number not in records:raise ValueError('Component geometric support record limit')
                records[number]=self.record(number)
        trips={};events={};output=[]
        for number,record in sorted(records.items()):
            journey=record['Replay_Journey_Key']
            if journey not in trips:trips[journey]=self.context.trip(journey)['trip']
            output.append({**record,'Trip':trips[journey]})
            times={(record['timestamps'][0],True),(record['timestamps'][1],False)}
            hold=hold_time(record)
            if hold is not None and record['timestamps'][0]<=hold<record['timestamps'][1]:times.add((hold,True))
            for at,inclusive in sorted(times):
                value=self.context.lane(record['vehicle'],at,inclusive)
                if value['event'] is not None:events[value['event'][0]]=value['event'][1]
        phases={key:('final' if capsule.get('final') is not None else 'base') for key,capsule in capsules.items()
                if capsule.get('base') is not None or capsule.get('final') is not None}
        requests=[]
        for key,number,epoch,role,_ in nodes:
            marker_key=self._native_key(number)
            kind,stage=decode_state_role(role)
            requests.append(dict(key=marker_key,role=kind,epoch=epoch,stage=stage))
            if kind in ('base','final'):
                if kind=='final' or marker_key not in phases:phases[marker_key]=kind
        constraint_keys=sorted(set(capsules)|set(phases)|{request['key'] for request in requests})
        packet=dict(records=output,phases=phases,checkpoints=capsules,
            lane_events=[row for _,row in sorted(events.items(),key=lambda item:(item[1]['time'],item[0]))],requests=requests,
            constraint_keys=constraint_keys,
            external_pass=True,generation=generation,
            release_states={interval_key(record):(self._release_for(interval_key(record),generation)
                if interval_key(record) in constraint_keys else None) for record in output})
        from simz1_queue_checkpoint import expanded_packet_bytes
        self.packet_expanded_bytes=expanded_packet_bytes(packet)
        if self.packet_expanded_bytes>Limits().max_decoded_bytes:raise ValueError('Component decoded byte limit')
        self.packet_support_records=[dict(id=number,record_key=interval_key(record),sha256=hashlib.sha256(encoded(record)).hexdigest())
            for number,record in sorted(records.items())]
        return nodes,child_rows,packet

    def _batch_packet(self,components,generation):
        """Fuse only independently ready SCCs; no dependency is evaluated early."""
        from simz1_queue_checkpoint import expanded_packet_bytes
        selected=[];nodes=[];node_components={};support_by_component={}
        records={};capsules={};phases={};events={};requests=[];releases={}
        packet=None;upper_bound=0
        for component in components:
            own,_,candidate=self._packet(component,generation)
            candidate_bytes=self.packet_expanded_bytes
            refs=list(self.packet_support_records)
            next_records=dict(records)
            for reference,record in zip(refs,candidate['records']):
                number=reference['id']
                if number in next_records and next_records[number]!=record:
                    raise ValueError('Independent components disagree on immutable native record')
                next_records[number]=record
            if selected and (len(next_records)>Limits().max_records or len(requests)+len(candidate['requests'])>Limits().max_records):break
            next_capsules=dict(capsules)
            for key,value in candidate['checkpoints'].items():
                next_capsules[key]=self._merge_capsule(dict(next_capsules[key]) if key in next_capsules else None,value)
            next_phases=dict(phases)
            for key,value in candidate['phases'].items():
                if value=='final' or key not in next_phases:next_phases[key]=value
            next_events=dict(events)
            for row in candidate['lane_events']:next_events[encoded(row)]=row
            next_releases=dict(releases)
            old_constraints=set(capsules)|set(phases)|{request['key'] for request in requests}
            candidate_constraints=set(candidate['constraint_keys'])
            for key,value in candidate['release_states'].items():
                if key in next_releases and next_releases[key]!=value:
                    if key in old_constraints and key not in candidate_constraints:continue
                    if not (key in candidate_constraints and key not in old_constraints):
                        raise ValueError('Mixed release generations in component batch')
                next_releases[key]=value
            proposed=dict(records=[value for _,value in sorted(next_records.items())],checkpoints=next_capsules,
                phases=next_phases,lane_events=sorted(next_events.values(),key=lambda row:row['time']),
                requests=requests+candidate['requests'],external_pass=True,generation=generation,release_states=next_releases)
            proposed['constraint_keys']=sorted(set(next_capsules)|set(next_phases)|{request['key'] for request in proposed['requests']})
            # Union only removes duplicate records/fields and shared framing.
            # A sum of complete packet byte sizes is a proved upper bound;
            # materialize an exact count only when that bound is insufficient.
            proposed_bound=upper_bound+candidate_bytes
            if proposed_bound>Limits().max_decoded_bytes:proposed_bound=expanded_packet_bytes(proposed)
            if proposed_bound>Limits().max_decoded_bytes:
                if not selected:raise ValueError('Single component exceeds original decoded guard')
                break
            records,capsules,phases,events,requests,releases=next_records,next_capsules,next_phases,next_events,proposed['requests'],next_releases
            packet=proposed;selected.append(component);nodes.extend(own);support_by_component[component]=refs
            upper_bound=proposed_bound
            node_components.update((row[0],component) for row in own)
        if not selected:raise ValueError('No bounded independently ready component could be scheduled')
        self.last_batch_byte_upper_bound=upper_bound
        return selected,nodes,node_components,support_by_component,packet

    @bounded_storage
    def evaluate(self,kernel,kernel_contract,*,progress=None,max_components=None,publish=False,batch_size=8):
        """Synchronous release generations; never substitute an in-place sweep."""
        from simz1_replay_work import checkpoint
        from simz1_queue_result_trust import IncrementalResultTrust
        from simz1_queue_component_schedule import ComponentSchedule
        if type(batch_size) is not int or not 1<=batch_size<=32:raise ValueError('Component batch size outside bounded preparation contract')
        facility=self.context.facility_support
        if (kernel_contract.get('facility_support')!=facility or getattr(kernel,'facility_support',None)!=facility or
            self.contract.get('facility_support')!=facility):
            raise ValueError('Causal graph/kernel facility coverage differs')
        if self.context.classifier_contract is not None and (self.context.phase_classifier is not kernel or
            self.context.classifier_contract!=kernel_contract or self.contract.get('classifier_contract')!=kernel_contract):
            raise ValueError('Causal graph classification evaluator differs from pose evaluator')
        self._evaluation_schema();graph_sha=self.structural_digest()
        if publish:
            from simz1_queue_support import contract as support_contract
            expected_support=support_contract(Path(self.index.receipt['contract']['database']),
                self.index.receipt['contract']['identity'],self.index.receipt['contract']['database_sha256'],self.context.visual_lanes)
            if expected_support!=self.index.receipt['contract']:
                raise ValueError('Cannot publish an index prepared under another source revision')
            if any(hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=digest for name,digest in self.contract['sources'].items()):
                raise ValueError('Cannot publish a graph prepared under another source revision')
        kernel_sha=hashlib.sha256(encoded(kernel_contract)).hexdigest()
        settings=kernel_contract['settings'];settings_sha=hashlib.sha256(encoded(settings)).hexdigest()
        self.evaluation_static=dict(identity=self.index.receipt['contract']['identity'],
            source_sqlite_sha256=self.index.receipt['contract']['database_sha256'],index_sha256=self.index.receipt['sha256'],
            kernel_sha256=kernel_sha,geometry_sha256=self.index.receipt['contract']['geometry_sha256'],
            settings_sha256=settings_sha,graph_sha256=graph_sha)
        self.result_trust={}
        self.release_digests={}
        self.derived_secret=secrets.token_bytes(32)
        if self.db.execute('SELECT 1 FROM generation_seal UNION ALL SELECT 1 FROM generation_archive LIMIT 1').fetchone():
            raise ValueError('Stored generation seals cannot restore private producer authority')
        self._retention_secret=secrets.token_bytes(32);self._last_completed=-1;self._last_archived=-1
        self._seal_tip=self._archive_tip='0'*64;self._schedules={};self._digest_only=set()
        evaluation_metrics=dict(maximum_packet_records=0,maximum_packet_states=0,maximum_heap_bytes=0,
            maximum_rss_bytes=0,maximum_expanded_request_bytes=0,maximum_wire_request_bytes=0)
        generation=0;completed=0;started=time.perf_counter()
        maximum_generations=self.db.execute('SELECT count(DISTINCT segment) FROM node').fetchone()[0]+1
        while generation<=maximum_generations:
            self.prune_generations(generation)
            release_digest=self._release_digest(generation)
            self.release_digests[generation]=release_digest
            self.result_trust[generation]=IncrementalResultTrust(self.db,generation,
                (row[0] for row in self.db.execute('SELECT key FROM node ORDER BY key')),storage=self.storage)
            self.db.execute('INSERT INTO generation VALUES (?,?,?,?,?)',(generation,'evaluating',release_digest,None,None));self.commit()
            schedule=ComponentSchedule(self.db,generation,storage=self.storage);self._schedules[generation]=schedule
            while True:
                ready=list(schedule.ready(batch_size))
                if not ready:break
                checkpoint('queue_checkpoint_components',generation=generation,completed=completed)
                selected,nodes,node_components,support_by_component,packet=self._batch_packet(ready,generation)
                self.last_packet=packet;self.last_component=selected
                try:
                    self.disk_guard('kernel.before')
                    response=kernel.solve(packet)
                    self.disk_guard('kernel.after')
                except Exception as error:
                    try:self.capture_rejected_packet(packet,generation,selected,kernel_contract,error)
                    except Exception as diagnostic_error:
                        self.last_rejection_diagnostic=dict(status='not_written',reason=type(diagnostic_error).__name__)
                    raise
                memory=response.get('memory',{})
                for name,value in dict(maximum_packet_records=len(packet['records']),maximum_packet_states=len(packet['requests']),
                    maximum_heap_bytes=memory.get('heap_used_bytes',0),maximum_rss_bytes=memory.get('max_rss_bytes',0),
                    maximum_expanded_request_bytes=getattr(kernel,'max_expanded_request_bytes',0),maximum_wire_request_bytes=kernel.max_request_bytes).items():
                    evaluation_metrics[name]=max(evaluation_metrics[name],value)
                component_digests={component:hashlib.sha256(encoded(dict(states=[state for node,state in zip(nodes,response['states'])
                    if node_components[node[0]]==component],generation=generation))).hexdigest() for component in selected}
                for node,state in zip(nodes,response['states']):
                    key,number,epoch,role,candidate_digest=node
                    component=node_components[key]
                    marker_key=self._native_key(number);kind=state['role'];stage=state['stage']
                    capsule=dict(schema='native-queue-phase-capsule-v1',complete=True,input=state['input'],
                        settings=settings,prepared=state['prepared'],release=state.get('release'))
                    if kind in ('base','final'):capsule[kind]=state['result']
                    else:capsule[kind]=[dict(epoch=epoch,stage=stage,result=state['result'])]
                    capsule=self._merge_capsule(packet['checkpoints'].get(marker_key),capsule)
                    dependencies=[]
                    for (target,edge_kind) in self.db.execute('SELECT target,kind FROM edge WHERE source=? ORDER BY target,kind',(key,)):
                        target_generation=generation if edge_kind=='same_pass' else generation-1
                        row=self.db.execute('SELECT sha256 FROM result WHERE generation=? AND node=?',(target_generation,target)).fetchone()
                        if edge_kind=='same_pass' and self.db.execute('SELECT component FROM node WHERE key=?',(target,)).fetchone()[0]==component:
                            dependencies.append(dict(key='component:'+target,sha256=component_digests[component]))
                        elif row is not None:
                            self.result_trust[target_generation].verify(target,row[0])
                            dependencies.append(dict(key=str(target_generation)+':'+target,sha256=row[0]))
                        elif edge_kind=='release' and generation==0:
                            dependencies.append(dict(key='native-default:'+target,sha256=hashlib.sha256(b'native-default-release').hexdigest()))
                        else:raise ValueError('Missing checkpoint dependency result')
                    expected=dict(identity=self.index.receipt['contract']['identity'],
                        source_sqlite_sha256=self.index.receipt['contract']['database_sha256'],index_sha256=self.index.receipt['sha256'],
                        kernel_sha256=kernel_sha,geometry_sha256=self.index.receipt['contract']['geometry_sha256'],settings_sha256=settings_sha,
                        record_sha256=hashlib.sha256(encoded(self.record(number))).hexdigest(),candidate_digest=candidate_digest,
                        graph_sha256=graph_sha,key=marker_key,role=kind,epoch=epoch,stage=stage,children=dependencies,
                        generation=generation,release_state_sha256=release_digest,support_records=support_by_component[component])
                    if kind in ('base','final') and state['result'].get('available') is False:
                        absence=self.context.phase_absence(self.record(number),epoch,role)
                        if absence is None:raise ValueError('Kernel anchor absence lacks independently derived source proof')
                        expected['absence_proof']=absence;capsule['absence_proof']=absence
                    wrapper=seal_checkpoint(capsule,expected);digest=checkpoint_digest(wrapper)
                    self.db.execute('INSERT INTO result VALUES (?,?,?,?)',(generation,key,encode_result_payload(wrapper),digest))
                    self.result_trust[generation].publish(key,digest)
                    recipe=state.get('release_recipe')
                    if state.get('result',{}).get('available') is False:
                        self.db.execute('INSERT OR IGNORE INTO observation_limit VALUES (?,?)',
                            (key,state['result'].get('reason') or 'native_renderer_unavailable'))
                    prior=self.db.execute('SELECT payload,signature FROM recipe WHERE generation=? AND key=?',(generation,marker_key)).fetchone()
                    if prior is not None and self._derived_value('recipe',generation,marker_key,prior)!=recipe:
                        raise ValueError('Release recipe differs between phases')
                    raw_recipe=encoded(recipe).decode()
                    self.db.execute('INSERT OR IGNORE INTO recipe VALUES (?,?,?,?)',
                        (generation,marker_key,raw_recipe,self._derived_signature('recipe',generation,marker_key,raw_recipe)))
                for component in selected:
                    self.db.execute('INSERT INTO evaluation VALUES (?,?,?)',(generation,component,'resolved'))
                    schedule.resolved(component)
                before=completed;completed+=len(selected)
                if before//64!=completed//64:
                    self.commit()
                    if progress:progress(dict(generation=generation,components=completed,seconds=time.perf_counter()-started,
                        kernel_calls=kernel.calls,**evaluation_metrics))
                if max_components is not None and completed>=max_components:
                    self.commit();return dict(complete=False,reason='diagnostic_component_cutoff',components=completed,metrics=evaluation_metrics)
            if self.db.execute('SELECT count(*) FROM evaluation WHERE generation=?',(generation,)).fetchone()[0]!=self.db.execute('SELECT count(*) FROM component').fetchone()[0]:
                raise ValueError('Topological scheduler left unresolved required components')
            changed=self.next_releases(generation)
            self.db.execute('UPDATE generation SET status=?,changed=?,metrics=? WHERE number=?',
                ('resolved',changed,encoded(evaluation_metrics).decode(),generation));self.commit()
            self.seal_generation(generation,changed)
            if not changed:
                retention=self.verify_generation_chain()
                roots=[dict(label=label,node=node,sha256=self.db.execute('SELECT sha256 FROM result WHERE generation=? AND node=?',(generation,node)).fetchone()[0])
                       for label,node in self.db.execute('SELECT label,node FROM root ORDER BY label')]
                contract=dict(identity=self.index.receipt['contract']['identity'],index_sha256=self.index.receipt['sha256'],
                    kernel_sha256=kernel_sha,geometry_sha256=self.index.receipt['contract']['geometry_sha256'],settings=settings,
                    graph_sha256=graph_sha,generation=generation,root_digest=hashlib.sha256(encoded(roots)).hexdigest())
                self.db.executemany('INSERT INTO metadata VALUES (?,?)',
                    [('converged_generation',str(generation)),('checkpoint_contract',encoded(contract).decode()),('roots',encoded(roots).decode()),
                     ('storage_observation',encoded(self.storage.report()).decode())])
                self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('generation_retention',encoded(retention).decode()))
                self.commit()
                if publish:
                    if self.structural_digest()!=graph_sha or any(
                        hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=digest
                        for name,digest in self.contract['sources'].items()):
                        raise ValueError('Verified graph or source revision changed during evaluation')
                    self.verification_complete=True
                    from simz1_queue_checkpoint_library import seal_verified_library
                    self.verified_preparation=seal_verified_library(self)
                    contract=self.verified_preparation['contract']
                return dict(complete=True,converged=True,published=publish,contract=contract,roots=roots,components=completed,
                    metrics=dict(evaluation_metrics,observational_absences=self.db.execute('SELECT count(*) FROM observation_limit').fetchone()[0],
                        seconds=time.perf_counter()-started,native_queries=self.context.metrics['sql_queries'],
                        native_cache=self.context.cache.summary() if hasattr(self.context.cache,'summary') else None,
                        storage=self.storage.report(),retention=retention))
            generation+=1
        raise ValueError('Release generations did not converge within native renderer refinement bound')

    @bounded_storage
    def next_releases(self,generation):
        changed=0
        if self.db.execute('SELECT count(*) FROM recipe WHERE generation=?',(generation,)).fetchone()[0]!=self.db.execute('SELECT count(DISTINCT segment) FROM node').fetchone()[0]:
            raise ValueError('Release recipe coverage is incomplete')
        for key,raw,signature in self.db.execute('SELECT key,payload,signature FROM recipe WHERE generation=? ORDER BY key',(generation,)):
            recipe=self._derived_value('recipe',generation,key,(raw,signature));value=None
            if recipe is not None:
                previous=self.db.execute("SELECT n.key FROM native_key k JOIN node n ON n.segment=k.segment WHERE k.key=? AND n.role='final'",
                    (recipe['previous_key'],)).fetchone()
                row=self.db.execute('SELECT payload FROM result WHERE generation=? AND node=?',(generation,previous[0])).fetchone() if previous else None
                if row is None:raise ValueError('Release recipe lacks its required previous FINAL result')
                if row is not None:
                    digest=self.db.execute('SELECT sha256 FROM result WHERE generation=? AND node=?',(generation,previous[0])).fetchone()[0]
                    self.result_trust[generation].verify(previous[0],digest)
                    envelope=decode_result_payload(row[0])
                    if checkpoint_digest(envelope)!=digest:raise ValueError('Previous release result bytes changed')
                    anchor=envelope['capsule']['final']
                    if anchor.get('within_storage') is True:
                        if recipe['kind']=='continuation':value=dict(previous_key=recipe['previous_key'],anchor_m=anchor['anchor_m'])
                        elif recipe['kind']=='setback':value=dict(previous_key=recipe['previous_key'],previous_anchor_m=anchor['anchor_m'],
                            setback_m=max(0,recipe['previous_offset_m']+recipe['previous_link_length_m']-anchor['anchor_m']-recipe['previous_half_m']))
                        else:raise ValueError('Unknown release recipe from native renderer')
            before=self._release_for(key,generation)
            if not release_equal(before,value):changed+=1
            payload=encoded(value).decode()
            self.db.execute('INSERT INTO release_state VALUES (?,?,?,?)',
                (generation,key,payload,self._derived_signature('release_state',generation,key,payload)))
        return changed


def release_equal(left,right):
    if left is None or right is None:return left is right
    if not isinstance(left,dict) or not isinstance(right,dict) or set(left)!=set(right):return False
    for key,value in left.items():
        other=right[key]
        if type(value) in (int,float) and type(other) in (int,float):
            if not math.isfinite(value) or not math.isfinite(other) or abs(value-other)>1e-7:return False
        elif value!=other:return False
    return True
