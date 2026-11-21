"""Read-only transport for a library verified by the live parent producer.

Per-result Merkle proofs bind requests to the independent parent root. Neither
the SQLite's own checksum column nor its self-declared metadata grants trust.
Restarting requires the producer to verify/evaluate the library again.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from simz1_queue_context import encoded, interval_key, hold_time, Incomplete
from simz1_queue_checkpoints import checkpoint_digest, state_key, validate_checkpoint, decode_state_role


def _decoded_result(payload):
    # The producer keeps repeated state results compressed in its bounded
    # external SQLite. Legacy text fixtures remain explicit through its codec.
    from simz1_queue_checkpoints import decode_result_payload
    return decode_result_payload(payload)


class VerifiedCheckpointLibrary(dict):
    """Private, picklable parent-to-worker anchor; never parsed from JSON."""


def _leaf(node, digest):
    return hashlib.sha256(b'leaf\0'+node.encode()+b'\0'+digest.encode()).hexdigest()


def _parent(left, right):
    return hashlib.sha256(b'node\0'+bytes.fromhex(left)+bytes.fromhex(right)).hexdigest()


def _root(contract, merkle):
    return hashlib.sha256(encoded(dict(contract={k:v for k,v in contract.items() if k!='root_digest'},
                                      merkle_root=merkle))).hexdigest()


class _MerkleFrontier:
    """Private logarithmic witness; committed SQLite rows cannot grant trust."""
    def __init__(self):
        self.levels={}
        self.count=0

    def add(self,leaf):
        level=0
        while level in self.levels:
            leaf=_parent(self.levels.pop(level),leaf)
            level+=1
        self.levels[level]=leaf
        self.count+=1

    def finish(self):
        if not self.count:raise ValueError('Empty private library Merkle witness')
        levels=sorted(self.levels)
        level=levels[0];root=self.levels[level]
        for next_level in levels[1:]:
            while level<next_level:
                root=_parent(root,root)
                level+=1
            root=_parent(self.levels[next_level],root)
            level+=1
        return root


def prepare_checkpoint_plan(replay,plan_path,*,progress=None):
    """Recompute a requested library in this live parent, never trust a receipt.

    A plan selects native observations only. It grants no completeness, carries
    no stored poses, and is checked against the explicit run and SQLite source.
    The existing server can use the resulting private descriptor immediately.
    """
    from simz1_continuous_replay import RuntimeReadCache
    from simz1_queue_context import QueueContext
    from simz1_queue_support import SupportIndex, AuxiliaryStorageScope
    from simz1_queue_checkpoints import CausalGraph
    from simz1_queue_checkpoint import CheckpointKernel,kernel_contract,settings_contract
    from simz1_report_package import PackageLock
    plan_path=Path(plan_path)
    if plan_path.is_symlink() or plan_path.stat().st_size>1024*1024:
        raise ValueError('Checkpoint plan is indirect or exceeds its byte budget')
    plan=json.loads(plan_path.read_bytes())
    if (not isinstance(plan,dict) or set(plan)!={'schema','identity','source_sqlite_sha256','settings','roots'} or
            plan['schema']!='native-causal-checkpoint-plan-v1' or plan['identity']!=replay.identity or
            plan['source_sqlite_sha256']!=replay.source_manifest['database_sha256'] or
            not isinstance(plan['roots'],list) or not 1<=len(plan['roots'])<=512):
        raise ValueError('Checkpoint plan differs from the native run/source')
    settings=settings_contract(plan['settings'])
    directory=Path(__file__).resolve().parents[1]/'runtime/replay/queue-checkpoints'
    directory.mkdir(parents=True,exist_ok=True)
    notify=progress or (lambda value:None)
    with PackageLock(directory/'.writer.lock') as writer:
        if not writer.acquired:raise ValueError('A checkpoint producer already owns the external store')
        output=directory/uuid.uuid4().hex;output.mkdir()
        fixed_support=(Path(replay.queue_support_path),Path(replay.queue_support_path).with_suffix('.json'))
        with AuxiliaryStorageScope(output,4*1024**3,fixed_paths=fixed_support) as storage, \
                closing(replay.connection()) as source, closing(SupportIndex(
                replay.queue_support_path,replay.queue_support_contract,
                expected_sha256=replay.queue_support_sha256)) as index:
            storage.attach(source)
            storage.attach(index.connection)
            contract=kernel_contract(index.receipt['contract'],index.receipt['sha256'],replay.config['visual_lanes'],settings,
                facility_support=getattr(replay,'queue_facility_support',None))
            # The same persistent native renderer classifies uncertain phases
            # before expansion and later evaluates every complete component.
            with CheckpointKernel(replay.identity,replay.config['visual_lanes'],settings,
                                  log_path=output/'kernel.stderr.log',
                                  facility_support=getattr(replay,'queue_facility_support',None),
                                  source_sqlite_sha256=replay.source_manifest['database_sha256']) as kernel:
                context=QueueContext(source,replay.blocks,validate_segment=replay.validate_native_segment,
                    validate_trip=replay.validate_spatial_trip,domains=replay.queue_domains,
                    visual_lanes=replay.config['visual_lanes'],support_index=index,
                    cache=RuntimeReadCache(8*1024*1024,4096),
                    facility_support=getattr(replay,'queue_facility_support',None),
                    phase_classifier=kernel,classifier_contract=contract)
                # Index and graph share the original external preparation budget;
                # separate per-file limits must not silently double that allowance.
                index_bytes=Path(replay.queue_support_path).stat().st_size
                graph_budget=4*1024**3-index_bytes
                if graph_budget<=0:raise ValueError('Support index exhausts checkpoint preparation budget')
                with closing(CausalGraph(output/'library.sqlite',context,max_disk_bytes=graph_budget,storage=storage)) as graph:
                    selected=set()
                    for root in plan['roots']:
                        if not isinstance(root,dict) or set(root)!={'vehicle','journey','link','start','end'}:
                            raise ValueError('Checkpoint plan root identity incomplete')
                        rows=index.connection.execute('SELECT id FROM support WHERE journey=? AND vehicle=? AND link=? AND start=? AND end=? LIMIT 2',
                            (root['journey'],root['vehicle'],root['link'],root['start'],root['end'])).fetchall()
                        if len(rows)!=1 or rows[0][0] in selected:raise ValueError('Checkpoint root is absent, ambiguous or repeated')
                        ident=rows[0][0];selected.add(ident)
                        record=graph.record(ident)
                        graph.root(interval_key(record),ident)
                    notify(dict(phase='checkpoint_graph',directory=str(output),roots=len(selected)))
                    graph.expand(lambda value:notify(dict(phase='checkpoint_graph',**value)))
                    graph.components(lambda value:notify(dict(phase='checkpoint_components',**value)))
                    outcome=graph.evaluate(kernel,contract,publish=True,
                        progress=lambda value:notify(dict(phase='checkpoint_evaluation',**value)))
                    if outcome.get('complete') is not True or outcome.get('converged') is not True:
                        raise ValueError('Checkpoint producer did not verify global convergence')
                    preparation=getattr(graph,'verified_preparation',None)
                    if not isinstance(preparation,VerifiedCheckpointLibrary):
                        raise ValueError('Checkpoint producer did not publish its private verified anchor')
                    replay.install_queue_checkpoint_library(preparation)
                    storage.check('checkpoint_library_installed')
                    notify(dict(phase='checkpoint_verified',directory=str(output),contract=preparation['contract'],
                                auxiliary_storage=storage.report()))
                    return preparation


def seal_verified_library(graph):
    """Called by the sole producer only AFTER semantic convergence checks."""
    from simz1_queue_checkpoints import CausalGraph
    if not isinstance(graph,CausalGraph) or getattr(graph,'verification_complete',False) is not True:
        raise ValueError('Library requires the live verified producer')
    graph.require_complete_graph()
    metadata=dict(graph.db.execute('SELECT key,value FROM metadata'))
    contract=json.loads(metadata['checkpoint_contract'])
    contract['source_sqlite_sha256']=graph.index.receipt['contract']['database_sha256']
    generation=int(metadata['converged_generation'])
    if contract.get('generation')!=generation:
        raise ValueError('Library convergence generation mismatch')
    trust=getattr(graph,'result_trust',{}).get(generation)
    if trust is None:raise ValueError('Library lacks independently authenticated evaluated results')
    if graph.db.execute('SELECT 1 FROM node WHERE key NOT IN (SELECT node FROM result WHERE generation=?) LIMIT 1',
                        (generation,)).fetchone():
        raise ValueError('Library omits required evaluated states')
    graph.commit('library_before_sealing')
    graph.db.executescript('''
        CREATE TABLE result_leaf(node TEXT PRIMARY KEY,position INTEGER UNIQUE NOT NULL);
        CREATE TABLE result_auth(level INTEGER NOT NULL,position INTEGER NOT NULL,digest TEXT NOT NULL,
                                 PRIMARY KEY(level,position));
    ''')
    count=0
    private_merkle=_MerkleFrontier()
    for node,payload,digest in graph.db.execute('SELECT node,payload,sha256 FROM result WHERE generation=? ORDER BY node',
                                               (generation,)):
        trust.verify(node,digest)
        wrapper=_decoded_result(payload)
        if checkpoint_digest(wrapper)!=digest or wrapper['contract']['generation']!=generation:
            raise ValueError('Library result changed before sealing')
        validate_checkpoint(wrapper,wrapper['contract'],digest)
        leaf=_leaf(node,digest)
        private_merkle.add(leaf)
        graph.db.execute('INSERT INTO result_leaf VALUES (?,?)',(node,count))
        graph.db.execute('INSERT INTO result_auth VALUES (0,?,?)',(count,leaf))
        count+=1
        if count%256==0:
            graph.commit('library_sealing_leaves')
    if count==0:
        raise ValueError('Empty checkpoint library')
    level,width=0,count
    while width>1:
        for position in range(0,width,2):
            rows=graph.db.execute('SELECT digest FROM result_auth WHERE level=? AND position BETWEEN ? AND ? ORDER BY position',
                                 (level,position,min(position+1,width-1))).fetchall()
            graph.db.execute('INSERT INTO result_auth VALUES (?,?,?)',
                             (level+1,position//2,_parent(rows[0][0],rows[-1][0])))
            if position%4096==0:
                graph.commit('library_sealing_merkle')
        level+=1;width=(width+1)//2
    merkle=graph.db.execute('SELECT digest FROM result_auth WHERE level=? AND position=0',(level,)).fetchone()[0]
    if merkle!=private_merkle.finish():
        raise ValueError('Library publication tree differs from independently verified results')
    contract['root_digest']=_root(contract,merkle)
    graph.db.execute("UPDATE metadata SET value=? WHERE key='checkpoint_contract'",(encoded(contract).decode(),))
    graph.commit('library_sealed')
    stat=graph.path.stat()
    return VerifiedCheckpointLibrary(path=str(graph.path),contract=contract,merkle_root=merkle,
                                     leaf_count=count,bytes=stat.st_size,mtime_ns=stat.st_mtime_ns)


class CheckpointLibrary:
    def __init__(self, preparation, *, expected):
        if (not isinstance(preparation,VerifiedCheckpointLibrary) or
                set(preparation)!={'path','contract','merkle_root','leaf_count','bytes','mtime_ns'}):
            raise ValueError('Checkpoint library lacks private verified parent anchor')
        self.preparation=preparation
        self.contract=preparation['contract']
        if any(self.contract.get(key)!=value for key,value in expected.items()):
            raise ValueError('Checkpoint library source/geometry/kernel identity mismatch')
        if _root(self.contract,preparation['merkle_root'])!=self.contract.get('root_digest'):
            raise ValueError('Checkpoint library independent root mismatch')
        self.path=Path(preparation['path'])
        if self.path.is_symlink():raise ValueError('Checkpoint library cannot be indirect')
        self.path=self.path.resolve(strict=True)
        self.check_unchanged()
        self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro&immutable=1',uri=True)
        self.db.execute('PRAGMA query_only=ON');self.db.execute('PRAGMA cache_size=-8192')
        metadata=dict(self.db.execute("SELECT key,value FROM metadata WHERE key IN ('checkpoint_contract','converged_generation','graph_complete')"))
        if (metadata.get('graph_complete')!='true' or
                json.loads(metadata.get('checkpoint_contract','null'))!=self.contract or
                int(metadata.get('converged_generation',-1))!=self.contract['generation']):
            self.close()
            raise ValueError('Checkpoint library metadata changed after verification')

    def check_unchanged(self):
        stat=self.path.stat()
        if (stat.st_size,stat.st_mtime_ns)!=(self.preparation['bytes'],self.preparation['mtime_ns']):
            raise ValueError('Checkpoint library changed after parent verification')

    def state(self,ident,epoch,role,record,*,include_contract=False):
        self.check_unchanged()
        kind,stage=decode_state_role(role)
        node=state_key(ident,epoch,role)
        row=self.db.execute('SELECT r.payload,r.sha256,l.position FROM result r JOIN result_leaf l ON l.node=r.node '
                            'WHERE r.generation=? AND r.node=?',(self.contract['generation'],node)).fetchone()
        if row is None:return None
        payload,digest,position=row
        wrapper=_decoded_result(payload)
        if checkpoint_digest(wrapper)!=digest:raise ValueError('Checkpoint result bytes changed')
        witness=_leaf(node,digest);width=self.preparation['leaf_count'];level=0
        if type(position) is not int or not 0<=position<width:raise ValueError('Checkpoint leaf position invalid')
        while width>1:
            sibling=position-1 if position%2 else min(position+1,width-1)
            proof=self.db.execute('SELECT digest FROM result_auth WHERE level=? AND position=?',(level,sibling)).fetchone()
            if proof is None:raise ValueError('Checkpoint authentication path missing')
            witness=_parent(proof[0],witness) if position%2 else _parent(witness,proof[0])
            position//=2;width=(width+1)//2;level+=1
        if witness!=self.preparation['merkle_root']:
            raise ValueError('Checkpoint differs from independently pinned library root')
        expected=wrapper['contract']
        for key in ('identity','index_sha256','kernel_sha256','geometry_sha256','graph_sha256','generation'):
            if expected.get(key)!=self.contract[key]:raise ValueError('Checkpoint state contract differs: '+key)
        if self.contract.get('source_sqlite_sha256') is not None and expected['source_sqlite_sha256']!=self.contract['source_sqlite_sha256']:
            raise ValueError('Checkpoint native SQLite differs')
        if (expected['record_sha256']!=hashlib.sha256(encoded(record)).hexdigest() or
                expected['key']!=interval_key(record) or expected['epoch']!=epoch or
                expected['role']!=kind):
            raise ValueError('Checkpoint state differs from native record/epoch/phase')
        if expected['stage']!=stage:
            raise ValueError('Checkpoint evaluation stage differs')
        if expected['settings_sha256']!=hashlib.sha256(encoded(self.contract['settings'])).hexdigest():
            raise ValueError('Checkpoint visual settings differ')
        capsule=validate_checkpoint(wrapper,expected,digest)
        return wrapper if include_contract else capsule

    def resolved_seed(self,context,ident,seed):
        """Hydrate only authenticated geometry references; never build a graph."""
        at=hold_time(seed)
        if at is None or not seed['timestamps'][0]<=at<seed['timestamps'][1]:return None
        envelope=self.state(ident,at,'final',seed,include_contract=True)
        if envelope is None:return None
        final_state=envelope['capsule'].get('final',{})
        if final_state.get('available') is False:
            # A certified absence is never a pose or a complete active seed.
            return dict(complete=False,reason='native_visual_anchor_unavailable',
                metrics=dict(checkpoint_states=1),record_keys=[],missing_topology_links=[],
                segments=[],transition_segments=[],trips={},lane_events=[],
                observational_absence=dict(reason=final_state.get('reason'),
                    root_digest=self.contract['root_digest'],record_key=interval_key(seed)))
        references=envelope['contract'].get('support_records')
        if not isinstance(references,list) or not references:
            raise ValueError('Checkpoint lacks authenticated geometric support references')
        counts=dict(logical_rows=0,decoded_bytes=0,compressed_bytes=0,records=0,
                    hold_records=0,moving_records=0,checkpoint_states=0)
        records={};trips={};events={};capsules={};phases={}
        def charge(cost):
            for name,limit in (('logical_rows',context.limits.max_rows),
                               ('decoded_bytes',context.limits.max_decoded_bytes),
                               ('compressed_bytes',context.limits.max_compressed_bytes)):
                counts[name]+=cost.get(name,0)
                if counts[name]>limit:raise Incomplete('checkpoint_'+name+'_limit')
        for reference in references:
            if (not isinstance(reference,dict) or set(reference)!={'id','record_key','sha256'} or
                    type(reference['id']) is not int or reference['id'] in records):
                raise ValueError('Checkpoint geometric support references ambiguous')
            if len(records)>=context.limits.max_records:raise Incomplete('record_limit')
            row=context.query('SELECT journey,vehicle,start,end,payload FROM segments WHERE id=?',(reference['id'],)).fetchone()
            if row is None:raise ValueError('Checkpoint geometric source record absent')
            journey,vehicle,start,end,raw=row;decoded=context.decode(raw)
            charge(dict(logical_rows=1,decoded_bytes=len(decoded),compressed_bytes=len(raw)))
            record=context.validate_segment(decoded,journey,vehicle,start,end)
            if (interval_key(record)!=reference['record_key'] or
                    hashlib.sha256(encoded(record)).hexdigest()!=reference['sha256']):
                raise ValueError('Checkpoint geometric source record changed')
            records[reference['id']]=record
            if journey not in trips:
                value=context.trip(journey);charge(value['costs']);trips[journey]=value['trip']
            times={(start,True),(end,False)}
            hold=hold_time(record)
            if hold is not None and start<=hold<end:times.add((hold,True))
            for epoch,inclusive in sorted(times):
                value=context.lane(vehicle,epoch,inclusive);charge(value['costs'])
                if value['event'] is not None:events[value['event'][0]]=value['event'][1]
        if records.get(ident)!=seed:raise ValueError('Checkpoint geometry does not include its native root')
        from simz1_queue_checkpoints import CausalGraph
        for number,record in records.items():
            epoch=hold_time(record)
            if epoch is None or not record['timestamps'][0]<=epoch<record['timestamps'][1]:continue
            base=self.state(number,epoch,'base',record)
            if base is None:continue
            if base.get('base',{}).get('available') is False:continue
            final=self.state(number,epoch,'final',record)
            if final is not None and final.get('final',{}).get('available') is False:
                # Keep its native record as geometry; no null anchor enters
                # the renderer's constraint roster or an active marker.
                continue
            capsule=CausalGraph._merge_capsule(base,final) if final is not None else base
            capsule.setdefault('fifo',[])
            key=interval_key(record);capsules[key]=capsule;phases[key]='final' if final is not None else 'base'
            counts['checkpoint_states']+=1+(final is not None)
        if phases.get(interval_key(seed))!='final':raise ValueError('Checkpoint root lacks complete base/final support')
        held=[record for record in records.values() if interval_key(record) in capsules]
        auxiliary=[record for record in records.values() if interval_key(record) not in capsules]
        counts.update(records=len(records),hold_records=len(held),moving_records=len(auxiliary))
        result=dict(complete=True,reason=None,metrics=counts,missing_topology_links=[],
            record_keys=list(capsules),segments=held,transition_segments=auxiliary,trips=trips,
            lane_events=[[seq,row] for seq,row in sorted(events.items(),key=lambda item:(item[1]['time'],item[0]))],
            checkpoints=capsules,checkpoint_contract=self.contract,
            support_certificate=dict(policy='native-causal-epochs-v1',complete=True,poses_certified=False,
                converged=True,generation=self.contract['generation'],graph_sha256=self.contract['graph_sha256'],
                root_digest=self.contract['root_digest'],phase_keys=phases))
        if len(encoded(result))>context.limits.max_decoded_bytes:raise Incomplete('decoded_byte_limit')
        return result

    def close(self):
        self.db.close()

    def __enter__(self):return self

    def __exit__(self,*unused):self.close()
