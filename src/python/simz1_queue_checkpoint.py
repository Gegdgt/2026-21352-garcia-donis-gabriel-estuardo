"""Bounded bridge to the production JavaScript queue geometry kernel.

This process only evaluates supplied, source-validated dependency components.
It cannot grant graph completeness or native acceptance. The persistent graph
producer must verify all dependencies and pin the returned capsules separately.
"""
import hashlib
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import threading


SCHEMA = 'native-queue-checkpoint-kernel-v1'
KERNEL_FILES = ('simz1_queue_checkpoint.cjs', 'simz1_visual_queues.js',
                'simz1_visual_lanes.js', 'simz1_queue_checkpoint.py',
                'simz1_continuous_loader.js', 'visualizador_z1_controls.js')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                      sort_keys=True, allow_nan=False).encode('utf8')


def compact_component_packet(packet, *, operation='solve'):
    """Lossless Trip interning plus the exact expanded JSON byte count."""
    if operation not in ('solve','classify'):raise ValueError('Unknown checkpoint kernel operation')
    trips={};trip_bytes={};compact=[];record_bytes=0
    records=packet['records']
    for record in records:
        journey=record.get('Replay_Journey_Key');trip=record.get('Trip')
        if not isinstance(journey,str) or not isinstance(trip,dict):
            raise ValueError('Checkpoint record lacks native journey metadata')
        raw_trip=trip_bytes[journey] if trips.get(journey) is trip else _encoded(trip)
        if journey in trip_bytes and trip_bytes[journey]!=raw_trip:
            raise ValueError('Contradictory checkpoint journey metadata')
        trips[journey]=trip;trip_bytes[journey]=raw_trip
        row={key:value for key,value in record.items() if key!='Trip'}
        compact.append(row)
        record_bytes+=len(_encoded(row))+8+len(raw_trip)  # comma + "Trip":
    expanded=len(_encoded({**packet,'op':operation,'records':[]}))+record_bytes+max(0,len(records)-1)+1
    return {**packet,'op':operation,'records':compact,'trips':trips},expanded


def expanded_packet_bytes(packet):
    return compact_component_packet(packet)[1]


def settings_contract(settings):
    expected = {'gap_m': 2, 'lateral_clearance_m': .1, 'stop_line_setback_m': 2}
    if not isinstance(settings, dict) or set(settings)-set(expected):
        raise ValueError('Unknown checkpoint visual settings')
    expected.update(settings)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in expected.values()):
        raise ValueError('Non-finite checkpoint settings')
    if not (.1 <= expected['gap_m'] <= 10 and 0 <= expected['lateral_clearance_m'] <= 1
            and expected['stop_line_setback_m'] >= 0):
        raise ValueError('Checkpoint settings outside renderer contract')
    return expected


def kernel_contract(source_contract, index_sha256, visual_lanes, settings, facility_support=None):
    from simz1_queue_support import SCHEMA as INDEX_SCHEMA
    if source_contract.get('schema') != INDEX_SCHEMA:
        raise ValueError('Checkpoint requires verified native support contract')
    if (not isinstance(index_sha256, str) or len(index_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in index_sha256)):
        raise ValueError('Checkpoint requires independent support digest')
    geometry_sha = hashlib.sha256(_encoded(visual_lanes)).hexdigest()
    # Use the index codec for its geometry digest (the bridge codec also permits
    # Unicode without escapes, so these serializations need not be identical).
    from simz1_queue_context import encoded
    if hashlib.sha256(encoded(visual_lanes)).hexdigest() != source_contract['geometry_sha256']:
        raise ValueError('Checkpoint geometry differs from verified index')
    directory = Path(__file__).parent
    from simz1_window_cache import reader_version
    result=dict(schema=SCHEMA, source_contract=json.loads(_encoded(source_contract)), index_sha256=index_sha256,
                geometry_sha256=geometry_sha, settings=settings_contract(settings),
                reader_version=reader_version(),
                kernels={name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                         for name in KERNEL_FILES})
    if facility_support is not None:
        from simz1_queue_context import validate_facility_support
        result['facility_support']=validate_facility_support(facility_support,
            source_contract['identity'],source_contract['database_sha256'])
    return result


class CheckpointKernel:
    """One owned Node process, one bounded request/response at a time."""
    def __init__(self, identity, visual_lanes, settings, *, log_path,
                 max_records=512, max_decoded_bytes=64*1024*1024, timeout=60,
                 facility_support=None, source_sqlite_sha256=None):
        self.identity = dict(identity)
        if (set(identity) != {'run_id', 'iteration', 'run_manifest_sha256'} or
                not isinstance(identity['run_id'], str) or not identity['run_id'] or
                type(identity['iteration']) is not int or identity['iteration'] < 0 or
                not isinstance(identity['run_manifest_sha256'], str) or
                len(identity['run_manifest_sha256']) != 64 or
                any(c not in '0123456789abcdef' for c in identity['run_manifest_sha256'])):
            raise ValueError('Invalid checkpoint kernel native identity')
        self.facility_support=None
        if source_sqlite_sha256 is not None and (not isinstance(source_sqlite_sha256,str) or
                len(source_sqlite_sha256)!=64 or any(c not in '0123456789abcdef' for c in source_sqlite_sha256)):
            raise ValueError('Invalid independent checkpoint SQLite digest')
        self.source_sqlite_sha256=source_sqlite_sha256
        self.geometry_sha256=hashlib.sha256(_encoded(visual_lanes)).hexdigest()
        if facility_support is not None:
            from simz1_queue_context import validate_facility_support
            self.facility_support=validate_facility_support(facility_support,identity,source_sqlite_sha256)
        if not (0 < max_records <= 512 and 0 < max_decoded_bytes <= 64*1024*1024):
            raise ValueError('Checkpoint kernel cannot expand request budgets')
        self.max_records, self.max_decoded_bytes = max_records, max_decoded_bytes
        self.timeout = timeout
        self.settings = settings_contract(settings)
        self.calls = self.max_request_bytes = self.max_response_bytes = 0
        self.classification_calls = 0
        self.max_expanded_request_bytes = 0
        node = shutil.which('node')
        if not node:
            raise ValueError('Node is required for the verified renderer kernel')
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open('xb')
        self.process = None
        self.responses = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        try:
            self.process = subprocess.Popen(
                [node, '--max-old-space-size=192', str(Path(__file__).with_suffix('.cjs'))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            initialization=dict(op='init',identity=self.identity,visual_lanes=visual_lanes,settings=self.settings)
            if self.facility_support is not None:initialization['facility_support']=self.facility_support
            response = self._exchange(initialization)
            if response.get('status') != 'ready':
                raise ValueError('Checkpoint geometry kernel did not initialize')
        except BaseException:
            self.close()
            raise

    def _read(self):
        def deliver(value):
            if self.stopping.is_set():
                return False
            try:
                self.responses.put(value,timeout=1)
                return True
            except queue.Full:
                return False
        try:
            while not self.stopping.is_set():
                raw = self.process.stdout.readline(self.max_decoded_bytes+2)
                if not raw:
                    deliver(EOFError('Checkpoint kernel closed; inspect '+str(self.log_path)))
                    return
                if len(raw) > self.max_decoded_bytes or not raw.endswith(b'\n'):
                    deliver(ValueError('Checkpoint kernel response byte limit'))
                    return
                if not deliver(raw):
                    return
        except BaseException as error:
            deliver(error)

    def _exchange(self, payload):
        raw = _encoded(payload)+b'\n'
        if len(raw) > self.max_decoded_bytes:
            raise ValueError('Checkpoint kernel request byte limit')
        self.max_request_bytes = max(self.max_request_bytes, len(raw))
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        try:
            response = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            self.close()
            raise TimeoutError('Checkpoint kernel timeout; log '+str(self.log_path)) from error
        if isinstance(response, BaseException):
            raise response
        self.max_response_bytes = max(self.max_response_bytes, len(response))
        result = json.loads(response, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError('Non-finite kernel response: '+value)))
        _encoded(result)  # Also rejects overflowing JSON exponents such as 1e999.
        if not isinstance(result, dict) or result.get('error'):
            raise ValueError('Checkpoint kernel rejected component: '+str(result))
        return result

    def solve(self, packet):
        if not isinstance(packet, dict) or set(packet)-{'records','phases','checkpoints','lane_events','requests',
                                                       'external_pass','generation','release_states','constraint_keys'}:
            raise ValueError('Unknown checkpoint component fields')
        records, requests = packet.get('records'), packet.get('requests')
        if not isinstance(records, list) or not isinstance(requests, list) or not requests:
            raise ValueError('Checkpoint component records/requests absent')
        if len(records) > self.max_records or len(requests) > self.max_records:
            raise ValueError('Checkpoint kernel record limit')
        def parsed_key(raw):
            value=json.loads(raw)
            if not isinstance(value,list) or len(value)!=4 or not isinstance(value[3],list) or len(value[3])!=2:
                raise ValueError('Invalid checkpoint interval key')
            return (value[0],value[1],value[2],tuple(value[3]))
        protected={parsed_key(raw) for raw in (list(packet.get('phases',{}))+list(packet.get('checkpoints',{})))}
        protected.update(parsed_key(request['key']) for request in requests)
        keys = set()
        for record in records:
            key = (record['vehicle'],record.get('Replay_Journey_Key',''),
                   record['Link_ID'],tuple(record['timestamps']))
            if key in keys:
                # Distinct zero-duration observations are ordered barriers, not
                # selectable poses. Preserve both exactly; never bridge across
                # them or choose one as an anchor/FIFO request.
                if record['timestamps'][0]!=record['timestamps'][1] or key in protected:
                    raise ValueError('Duplicate checkpoint native record')
            keys.add(key)
        if 'constraint_keys' in packet:
            causal = packet['constraint_keys']
            if (not isinstance(causal, list) or any(not isinstance(key, str) for key in causal)
                    or len(causal) != len(set(causal))):
                raise ValueError('Invalid causal constraint keys')
            causal_keys = {parsed_key(key) for key in causal}
            if (len(causal_keys) != len(causal) or causal_keys != protected
                    or not causal_keys.issubset(keys)
                    or any(key[3][0] == key[3][1] for key in causal_keys)):
                raise ValueError('Causal constraint coverage differs from verified phases')
        for request in requests:
            key = parsed_key(request['key'])
            if (not isinstance(request, dict) or set(request) != {'key','role','epoch','stage'} or
                    request['role'] not in ('base','final','fifo','interpolate') or key not in keys or
                    type(request['epoch']) not in (int,float) or not math.isfinite(request['epoch'])):
                raise ValueError('Invalid checkpoint state request')
            stage=request['stage']
            if request['role']=='fifo' or request['role']=='interpolate' and stage is not None:
                if (not isinstance(stage,list) or len(stage)!=2 or type(stage[0]) is not int or
                        not 0 <= stage[0] <= 9007199254740991 or not isinstance(stage[1],str) or not stage[1]):
                    raise ValueError('Invalid checkpoint evaluation stage')
                # An interpolation stage chooses the trace's anchor endpoint;
                # it does not authorize a different role or FIFO-clamped centre.
                # The consumer may be outside this bounded component, so check
                # its interval identity without requiring roster membership.
                parsed_key(stage[1])
            elif stage is not None:
                raise ValueError('Checkpoint stage only applies to FIFO or projection')
        if 'external_pass' in packet:
            if (packet['external_pass'] is not True or type(packet.get('generation')) is not int or
                    packet['generation'] < 0 or not isinstance(packet.get('release_states'), dict)):
                raise ValueError('Invalid external checkpoint generation')
            release_keys = set()
            for raw in packet['release_states']:
                value = json.loads(raw)
                release_keys.add((value[0],value[1],value[2],tuple(value[3])))
            if not keys.issubset(release_keys):
                raise ValueError('External checkpoint generation omits release states')
        # Trip metadata is shared by all observations of a journey. Keep the
        # original logical byte guard, but send that immutable object once.
        # This codec changes neither a source field nor dependency membership.
        wire,expanded=compact_component_packet(packet)
        if expanded>self.max_decoded_bytes:raise ValueError('Checkpoint expanded request byte limit')
        self.max_expanded_request_bytes=max(self.max_expanded_request_bytes,expanded)
        result = self._exchange(wire)
        if packet.get('external_pass') is True and (result.get('external_pass') is not True or
                result.get('generation') != packet['generation'] or
                not isinstance(result.get('releases_next'), dict) or type(result.get('release_changed')) is not bool):
            raise ValueError('Checkpoint kernel generation or release coverage changed')
        states = result.get('states')
        if not isinstance(states, list) or len(states) != len(requests):
            raise ValueError('Incomplete checkpoint kernel results')
        for request, state in zip(requests, states):
            if (not isinstance(state, dict) or
                    any(state.get(name) != request[name] for name in ('key','role','epoch','stage')) or
                    not isinstance(state.get('result'), dict) or type(state['result'].get('available')) is not bool):
                raise ValueError('Checkpoint kernel changed state identity or omitted availability')
            value=state['result']
            if value['available'] is False and request['role'] in ('base','final'):
                proof=getattr(self,'facility_support',None)
                if (proof is None or parsed_key(request['key'])[2] in proof['blocking_links'] or
                        value.get('reason')!='shared_upstream_without_blocking_facility' or
                        'anchor_m' not in value or value['anchor_m'] is not None or
                        'pose' not in value or value['pose'] is not None or value.get('pose_available') is not False):
                    raise ValueError('Unavailable anchor lacks verified facility absence or contains a fabricated pose')
            if value['available'] is False and request['role']=='fifo' and (
                    value.get('pose') is not None or value.get('center_m') is not None or
                    value.get('reason')=='native_occupancy_unavailable' and 'pose' not in value):
                raise ValueError('Unavailable FIFO state contains a fabricated pose')
        self.calls += 1
        return result

    execute = solve

    def classify(self, packet):
        """Obtain source-bound entry metadata; this never returns a pose capsule."""
        if (not isinstance(packet,dict) or set(packet)-{'records','lane_events','requests','phases','checkpoints','constraint_keys'} or
                packet.get('checkpoints',{})!={}):
            raise ValueError('Unknown classification fields or pose checkpoints supplied')
        records,requests=packet.get('records'),packet.get('requests')
        if (not isinstance(records,list) or not isinstance(requests,list) or not requests or
                len(records)>self.max_records or len(requests)>self.max_records):
            raise ValueError('Classification record/request budget or coverage invalid')
        def parsed_key(raw):
            value=json.loads(raw)
            if (not isinstance(value,list) or len(value)!=4 or not isinstance(value[3],list) or len(value[3])!=2 or
                    any(type(t) not in (int,float) or not math.isfinite(t) for t in value[3])):
                raise ValueError('Invalid classification interval identity')
            return value[0],value[1],value[2],tuple(value[3])
        phases=packet.get('phases',{})
        if not isinstance(phases,dict) or any(value!='final' for value in phases.values()):
            raise ValueError('Classification requires exact final preparation phases')
        protected={parsed_key(key) for key in phases}
        requested=set()
        for request in requests:
            if (not isinstance(request,dict) or set(request)!={'key','role','epoch','stage'} or
                    request['role']!='classify' or request['stage'] is not None or
                    type(request['epoch']) not in (int,float) or not math.isfinite(request['epoch'])):
                raise ValueError('Invalid entry classification request')
            key=parsed_key(request['key'])
            if key in requested or not key[3][0]<=request['epoch']<key[3][1]:
                raise ValueError('Duplicate classification or epoch outside source interval')
            requested.add(key)
        protected.update(requested)
        keys=set()
        for record in records:
            key=(record['vehicle'],record.get('Replay_Journey_Key',''),record['Link_ID'],tuple(record['timestamps']))
            if key in keys and (key[3][0]!=key[3][1] or key in protected):
                raise ValueError('Duplicate classification source record')
            keys.add(key)
        if not protected.issubset(keys):raise ValueError('Classification source coverage incomplete')
        if 'constraint_keys' in packet:
            constraints=packet['constraint_keys']
            if (not isinstance(constraints,list) or any(not isinstance(key,str) for key in constraints) or
                    len(constraints)!=len(set(constraints)) or
                    {parsed_key(key) for key in constraints}!=protected or
                    len({parsed_key(key) for key in constraints})!=len(constraints)):
                raise ValueError('Classification constraint coverage differs')
        wire,expanded=compact_component_packet(packet,operation='classify')
        if expanded>self.max_decoded_bytes:raise ValueError('Classification expanded request byte limit')
        self.max_expanded_request_bytes=max(self.max_expanded_request_bytes,expanded)
        response=self._exchange(wire)
        if (response.get('op')!='classify' or response.get('status')!='classified' or
                type(response.get('pose_requests')) is not int or response['pose_requests']!=0 or
                not isinstance(response.get('states'),list) or len(response['states'])!=len(requests)):
            raise ValueError('Incomplete entry classification response')
        fields={'complete','represented','eligible','group_key','order_time','hold','start','end','native_entry',
                'occupancy','departure','departure_complete','reason'}
        def number(value):return type(value) in (int,float) and math.isfinite(value)
        def safe_integer(value):return type(value) is int and 0<=value<=9007199254740991
        for request,state in zip(requests,response['states']):
            if (not isinstance(state,dict) or set(state)!={'key','epoch','role','stage','input','classification'} or
                    any(state.get(name)!=request[name] for name in ('key','epoch','role','stage')) or
                    not isinstance(state.get('input'),str)):
                raise ValueError('Classification changed native request identity or returned a pose state')
            value=state['classification'];times=parsed_key(request['key'])[3]
            if (not isinstance(value,dict) or set(value)!=fields or
                    any(type(value[name]) is not bool for name in ('complete','represented','eligible','native_entry','departure_complete')) or
                    not number(value['start']) or not number(value['end']) or
                    (value['start'],value['end'])!=times or
                    any(value[name] is not None and not number(value[name]) for name in ('order_time','hold')) or
                    value['reason'] is not None and (not isinstance(value['reason'],str) or not value['reason'])):
                raise ValueError('Invalid entry classification metadata')
            group=value['group_key']
            if group is not None:
                if not isinstance(group,str):raise ValueError('Invalid classified queue group')
                group=json.loads(group)
                if (not isinstance(group,list) or len(group)!=2 or not isinstance(group[0],str) or not group[0] or
                        not safe_integer(group[1])):raise ValueError('Invalid classified queue group')
            if value['complete'] and value['represented'] and (group is None or value['order_time'] is None):
                raise ValueError('Complete represented classification lacks exact order/group')
            for name in ('occupancy','departure'):
                relation=value[name]
                if relation is not None and (not isinstance(relation,dict) or set(relation)!={'corridor','slot','ordinal'} or
                        not isinstance(relation['corridor'],str) or not relation['corridor'] or
                        not safe_integer(relation['slot']) or not safe_integer(relation['ordinal'])):
                    raise ValueError('Invalid classified native occupancy relation')
            if value['represented'] and value['occupancy'] is not None:
                native=value['occupancy']
                if group!=['corridor:'+native['corridor'],native['slot']] or value['order_time']!=native['ordinal']:
                    raise ValueError('Classified group/order differs from native occupancy')
            if (value['occupancy'] is not None and value['departure_complete'] or
                    value['occupancy'] is None and (not value['departure_complete'] or value['departure'] is not None)):
                raise ValueError('Classification incorrectly certifies departure prefix coverage')
            if value['reason']=='inactive_context_without_occupancy_or_hold' and (
                    value['complete'] is not True or value['represented'] is not False or
                    value['eligible'] is not False or value['native_entry'] is not False or
                    value['hold'] is not None or value['occupancy'] is not None or
                    value['group_key'] is not None or value['order_time'] is not None):
                raise ValueError('Inactive anchor classification contradicts native phase evidence')
        self.calls+=1
        self.classification_calls+=1
        return response

    def close(self):
        if getattr(self,'stopping',None) is not None:
            self.stopping.set()
        process = getattr(self, 'process', None)
        if process is not None:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Popen retains the exact Windows process handle we created;
                # this never searches or terminates another process by name.
                process.terminate()
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            self.process = None
        if getattr(self, 'log', None) is not None:
            self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
