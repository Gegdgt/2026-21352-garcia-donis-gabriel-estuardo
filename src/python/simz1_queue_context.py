"""Bounded read-only closure of native hold observations, independent of windows.

There is no link/hold index in the historical SQLite schema. Each seed therefore
uses complete, bounded time-bucket reads. A budget failure returns no partial
roster. Cache hits incur the same logical budget as cold reads.
"""
from bisect import bisect_right
from collections import deque, OrderedDict
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import math
import zlib
from simz1_replay_work import checkpoint


POLICY = 'native-hold-closure-v1'
DEPENDENCY_POLICY = 'native-slot-predecessors-and-moving-neighbors-v1'


class VerifiedFacilitySupport(dict):
    """Private parent-produced schedule coverage; never restore from JSON."""


def validate_facility_support(scope, identity, source_sha256):
    fields={'schema','identity','source_sqlite_sha256','schedule_sha256','reader_sha256','blocking_links'}
    if not isinstance(scope,VerifiedFacilitySupport) or set(scope)!=fields:
        raise ValueError('Facility support lacks privately verified coverage')
    if (scope['schema']!='native-blocking-facility-support-v1' or scope['identity']!=identity or
        scope['source_sqlite_sha256']!=source_sha256 or not isinstance(identity,dict) or
        set(identity)!={'run_id','iteration','run_manifest_sha256'} or
        not isinstance(identity['run_id'],str) or not identity['run_id'] or
        type(identity['iteration']) is not int or identity['iteration']<0):
        raise ValueError('Facility support native identity differs')
    hashes=[identity['run_manifest_sha256'],source_sha256,scope['schedule_sha256'],scope['reader_sha256']]
    if any(not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value) for value in hashes):
        raise ValueError('Facility support source hash is invalid')
    links=scope['blocking_links']
    if (not isinstance(links,list) or any(not isinstance(link,str) or not link for link in links) or
        links!=sorted(set(links))):
        raise ValueError('Facility support links must be sorted and unique')
    return json.loads(encoded(scope))


def occupancy_absence(record, visual_lanes, *, geometry_sha256=None):
    """Prove selected exact rejection branches of VisualLanes.occupancy.

    None means unknown or supported, never absence. This is deliberately a
    subset of the JS rejection predicate; it does not guess geometry, lanes or
    an ordinal from a failed conservative reservation_order query.
    """
    if not isinstance(visual_lanes,dict) or visual_lanes.get('schema_version')!=1:
        return None
    links=visual_lanes.get('links');data=visual_lanes.get('occupancy_corridors') or {}
    if not isinstance(links,dict) or data.get('schema')!='corridor-length-v1' or not isinstance(data.get('corridors'),dict):
        return None
    native=record.get('Native_Occupancy')
    def integer(value):return type(value) in (int,float) and math.isfinite(value) and value==int(value) and 0<=value<=9007199254740991
    reason=None
    if not isinstance(native,dict) or native.get('policy')!='corridor-length-v1':reason='native_policy_absent'
    elif not integer(native.get('ordinal')):reason='native_ordinal_invalid'
    else:
        corridor=data['corridors'].get(native.get('corridor_id'))
        slot=native.get('model_slot')
        if not isinstance(corridor,dict):reason='reserved_corridor_absent'
        elif not integer(slot):reason='native_slot_invalid'
        else:
            members=corridor.get('link_ids')
            if isinstance(members,list) and members:
                first=links.get(members[0]) or {}
                limits=(corridor.get('represented_lanes'),first.get('num_lanes'))
                if any(type(value) in (int,float) and math.isfinite(value) and slot>=value for value in limits):
                    reason='native_slot_outside_corridor'
                # A proved level/node mismatch is sufficient for connects to
                # return false regardless of endpoint rounding or path caches.
                def incompatible(sequence):
                    sentinel=object()
                    for left_id,right_id in zip(sequence,sequence[1:]):
                        left,right=links.get(left_id),links.get(right_id)
                        if not isinstance(left,dict) or not isinstance(right,dict):return 'native_link_absent'
                        a,b=left.get('to_node',sentinel),right.get('from_node',sentinel)
                        numeric=type(a) in (int,float) and type(b) in (int,float)
                        if a is None or a is sentinel or (type(a)!=type(b) and not numeric) or a!=b:return 'native_connection_node_mismatch'
                        for field in ('bridge','tunnel','layer'):
                            a=(left.get('osm_tags') or {}).get(field,sentinel);b=(right.get('osm_tags') or {}).get(field,sentinel)
                            numeric=type(a) in (int,float) and type(b) in (int,float)
                            if (type(a)!=type(b) and not numeric) or a!=b:return 'native_connection_level_mismatch'
                    return None
                reason=reason or incompatible(members)
                exits=native.get('exit_links')
                if reason is None and isinstance(exits,list) and record.get('Link_ID') in exits:
                    exit_from=native.get('exit_from_link')
                    if native.get('passage_kind')!='boundary_exit' or exit_from not in members:reason='native_exit_receipt_invalid'
                    else:reason=incompatible([exit_from,*exits])
                passage=native.get('passage_links')
                # Membership in the reserved corridor is sufficient to enter
                # the JS passage branch if that corridor exists; otherwise JS
                # already returns null at its earlier reserved-corridor guard.
                if reason is None and isinstance(passage,list) and (record.get('Link_ID') in passage or record.get('Link_ID') in members):
                    receipt=native.get('receipt_link')
                    if receipt not in members:reason='native_passage_receipt_invalid'
                    else:reason=incompatible([*passage,receipt])
    if reason is None:return None
    return dict(schema='native-occupancy-absence-v1',reason=reason,
        raw_sha256=hashlib.sha256(encoded(record)).hexdigest(),
        geometry_sha256=geometry_sha256 or hashlib.sha256(encoded(visual_lanes)).hexdigest())


def queue_domains(visual_lanes, *, max_body_length_m=18.0, max_body_width_m=2.5):
    """Possible interacting bodies from effective topology and source geometry.

    Same-level shared nodes, expanded geometry bounds, and explicit native
    corridors form a conservative candidate domain; they assert no position.
    Unknown/missing topology keeps the conservative, diagnosed fallback.
    """
    if not isinstance(visual_lanes, dict) or not visual_lanes.get('available'):
        return None
    links=visual_lanes.get('links')
    if not isinstance(links, dict) or not links:
        return None
    if not all(math.isfinite(x) and x>0 for x in (max_body_length_m,max_body_width_m)):
        raise ValueError('Invalid configured body bound for queue domains')
    by_node={}
    for ident,link in links.items():
        if not isinstance(link,dict) or link.get('from_node') is None or link.get('to_node') is None:
            return None
        for node in (link.get('from_node'),link.get('to_node')):
            by_node.setdefault(node,set()).add(ident)
    result={}
    for ident,link in links.items():
        level=tuple(link.get('osm_tags',{}).get(key) for key in ('bridge','tunnel','layer'))
        neighbors={ident}
        for node in (link.get('from_node'),link.get('to_node')):
            for other in by_node.get(node,()):
                if tuple(links[other].get('osm_tags',{}).get(key) for key in ('bridge','tunnel','layer'))==level:
                    neighbors.add(other)
        result[ident]=neighbors
    # Conservative metric bounds include the maximum configured body, maximum
    # supported visual margins (gap 10 m/lateral 1 m) and every lane offset.
    # The index only narrows candidate pairs; it never changes source geometry.
    points=[]
    for link in links.values():
        path=link.get('path')
        if not isinstance(path,(list,tuple)) or len(path)<2:return None
        for point in path:
            if not isinstance(point,(list,tuple)) or len(point)!=2:return None
            if not all(type(x) in (int,float) and math.isfinite(x) for x in point):return None
            points.append(point)
    latitude=sum(p[1] for p in points)/len(points)
    yscale=6371008.8*math.pi/180; xscale=yscale*math.cos(latitude*math.pi/180)
    origin=points[0]; cells={};bounds={};cell=100.0
    for ident,link in links.items():
        path=link.get('path')
        if not path:return None
        count=link.get('num_lanes'); opposite=link.get('opposing_lanes',0);width=link.get('lane_width_m')
        if not all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in (count,opposite,width)):
            return None
        margin=(max_body_length_m+10)/2+max_body_width_m/2+1+width*max(1,count+opposite)
        xs=[(p[0]-origin[0])*xscale for p in path];ys=[(p[1]-origin[1])*yscale for p in path]
        box=(min(xs)-margin,min(ys)-margin,max(xs)+margin,max(ys)+margin)
        level=tuple(link.get('osm_tags',{}).get(key) for key in ('bridge','tunnel','layer'))
        candidates=set()
        keys=[(x,y) for x in range(math.floor(box[0]/cell),math.floor(box[2]/cell)+1)
              for y in range(math.floor(box[1]/cell),math.floor(box[3]/cell)+1)]
        for key in keys:candidates.update(cells.get(key,()))
        for other in candidates:
            before,other_level=bounds[other]
            if level==other_level and box[0]<=before[2] and before[0]<=box[2] and box[1]<=before[3] and before[1]<=box[3]:
                result[ident].add(other);result[other].add(ident)
        bounds[ident]=(box,level)
        for key in keys:cells.setdefault(key,set()).add(ident)
    corridor_data=visual_lanes.get('occupancy_corridors') or {}
    if not isinstance(corridor_data,dict) or not isinstance(corridor_data.get('corridors',{}),dict):return None
    for corridor in corridor_data.get('corridors',{}).values():
        if not isinstance(corridor,dict):return None
        members=corridor.get('link_ids',[])
        if not isinstance(members,list):return None
        if any(ident not in result for ident in members):return None
        # A body's reference may be in any member; all source-backed neighbors
        # of that corridor can constrain its position as well.
        shared=set().union(*(result[ident] for ident in members)) if members else set()
        for ident in members:result[ident].update(shared)
        for other in shared:result[other].update(members)
    return {ident:frozenset(neighbors) for ident,neighbors in result.items()}


@dataclass(frozen=True)
class Limits:
    # Verified V7/V8 closures exceed 256 primary records and 16 MiB compressed.
    # Keep explicit resource limits with measured headroom;
    # failure still returns no partial roster. These are resource assumptions,
    # not vehicle counts, calibrated physics or permission to omit evidence.
    max_buckets: int = 256
    max_rows: int = 16384
    max_compressed_bytes: int = 32 * 1024 * 1024
    max_decoded_bytes: int = 64 * 1024 * 1024
    max_record_bytes: int = 1024 * 1024
    max_depth: int = 255
    max_records: int = 512


def encoded(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')


def hold_time(record):
    plan = record.get('Motion_Plan') or {}
    boundary = record.get('Boundary_Provenance') or {}
    if (plan.get('status') == 'stationary' and plan.get('distance_m') == 0 and
            boundary.get('start') == 'VehicleArrivesAtFacility' and boundary.get('end') == 'VehicleDepartsAtFacility'):
        # Include immutable facility intervals as candidate predecessors. The
        # renderer still verifies trip identity, blocking status and geometry;
        # this temporal closure never asserts a lane or a physical coordinate.
        return record['timestamps'][0]
    if (plan.get('status') == 'stationary' and plan.get('distance_m') == 0 and
            boundary.get('start') == 'VehicleDepartsAtFacility' and
            type(boundary.get('start_relative')) in (int, float) and
            boundary.get('start_relative') == boundary.get('end_relative') and
            0 <= boundary['start_relative'] <= 1):
        # The native post-service interval is still stationary even without a
        # separate WAIT event, including a terminal vehicle-leaves-traffic
        # boundary. The renderer's nativeDeparture predicate does not inspect
        # the following event name. Keep candidate temporal evidence here;
        # the renderer separately verifies native occupancy/facility and lane.
        return record['timestamps'][0]
    value = plan.get('hold_start')
    if value is None:
        value = plan.get('native_wait_boundary')
    return value if type(value) in (int, float) and math.isfinite(value) else None


def interval_key(record):
    # JSON.stringify formats 130.0 as 130 and 1e-5 as 0.00001. Native simulation
    # seconds fit its ordinary-decimal range. Only the identity text is formatted;
    # record timestamps themselves remain unchanged.
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Queue context identity has a non-finite timestamp')
        if value == 0:
            return '0'
        if 1e-6 <= abs(value) < 1e21:
            return str(int(value)) if int(value) == value else format(Decimal(str(value)), 'f')
        mantissa, exponent = repr(float(value)).split('e')
        if mantissa.endswith('.0'):
            mantissa = mantissa[:-2]
        exponent = int(exponent)
        return mantissa + 'e' + ('+' if exponent >= 0 else '-') + str(abs(exponent))
    prefix = json.dumps([record['vehicle'], record.get('Replay_Journey_Key') or '', record['Link_ID']],
                        separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return prefix[:-1] + ',[' + ','.join(number(value) for value in record['timestamps']) + ']]'


def js_key_before(left,right):
    """JSON.stringify identity tie-break in JavaScript UTF-16 code units."""
    return left.encode('utf-16-be','surrogatepass')<right.encode('utf-16-be','surrogatepass')


def scalar_interval_key(row):
    return interval_key(dict(vehicle=row['vehicle'],Replay_Journey_Key=row['journey'],
        Link_ID=row['link'],timestamps=[row['start'],row['end']]))


def base_predecessor(own_order,own_group,own_key,other):
    """BASE reads earlier members of its own verified renderer group only.

    A missing supported ordinal means the renderer group is not certified, so
    retain the candidate. Transfer knowledge is immaterial to BASE: that phase
    does not inspect departedByGroup or the cross-group HOLD spatial index.
    """
    order=other['ordinal']
    if own_order is None or order is None:return True
    if own_group!=(other['corridor'],other['slot']):return False
    return order<own_order or order==own_order and js_key_before(scalar_interval_key(other),own_key)


def phase_relations(own_order,own_group,own_vehicle,own_key,other,scope,at):
    """Conservative consumers of FIFO/FINAL, preserving uncertain groups."""
    order=other['ordinal'];known=own_order is not None and order is not None
    same=known and own_group==(other['corridor'],other['slot'])
    different=own_vehicle!=other['vehicle']
    unknown=different and (not known or not same and not other['transfer_known'])
    earlier=different and same and order<own_order
    transfer=(different and known and not same and other['transfer_known'] and
        own_group==(other['transfer_corridor'],other['transfer_slot']) and
        other['transfer_ordinal'] is not None and other['transfer_ordinal']<own_order)
    hold=other['hold']
    geometric=(scope=='final' and hold is not None and other['start']<=hold<=at<other['end'] and
        (not known or order<own_order or order==own_order and js_key_before(scalar_interval_key(other),own_key)))
    return unknown,earlier,transfer,geometric


def native_consumer(scalar):
    """Native index fields remain native; visual comparison has its own keys."""
    if scalar['ordinal'] is None:return None
    return dict(complete=True,represented=True,occupancy=True,visual_order=scalar['ordinal'],
        visual_group=('corridor:'+scalar['corridor'],scalar['slot']),eligible=None,proof=None)


def consumer_base_predecessor(own,own_key,other,other_key):
    if other is not None and not other['represented']:return False
    if own is None or other is None:return True
    if own['visual_group']!=other['visual_group']:return False
    return other['visual_order']<own['visual_order'] or (other['visual_order']==own['visual_order'] and js_key_before(other_key,own_key))


def consumer_relations(own,own_scalar,own_key,other,other_scalar,scope,at):
    if other is not None and not other['represented']:return False,False,False,False
    unknown,same,transfer,geometric=phase_relations(own_scalar['ordinal'],
        (own_scalar['corridor'],own_scalar['slot']),own_scalar['vehicle'],own_key,other_scalar,scope,at)
    if own is not None and other is not None:
        # The renderer's native precedes predicate requires occupancy on BOTH
        # entries. A terminal-lane fallback is a visual entry, not a native
        # reservation and never acquires a fabricated FIFO ordinal.
        if not own['occupancy'] or not other['occupancy']:unknown=same=transfer=False
        if scope=='final':
            hold=other_scalar['hold'];order=other['visual_order'];rank=own['visual_order']
            geometric=(other.get('eligible') is not False and hold is not None and
                other_scalar['start']<=hold<=at<other_scalar['end'] and
                (order<rank or order==rank and js_key_before(scalar_interval_key(other_scalar),own_key)))
    return unknown,same,transfer,geometric


class Incomplete(Exception):
    pass


class ScalarIntervals:
    """Immutable in-memory index; the source SQLite stays read-only."""
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda row: (row[3], row[0]))
        self.starts = [row[3] for row in self.rows]
        self.size = 1 << max(0, (len(rows)-1).bit_length())
        self.ends = [float('-inf')] * (2*self.size)
        for i, row in enumerate(self.rows):
            self.ends[self.size+i] = row[4]
        for i in range(self.size-1, 0, -1):
            self.ends[i] = max(self.ends[2*i], self.ends[2*i+1])
        self.accounted_bytes = len(encoded(rows)) + len(rows)*128 + len(self.ends)*32 + 256

    def at(self, at, limit):
        stop = bisect_right(self.starts, at)
        stack, result = [(1, 0, self.size)], []
        while stack:
            node, left, right = stack.pop()
            if left >= stop or self.ends[node] <= at:
                continue
            if right-left == 1:
                result.append(self.rows[left])
            else:
                middle = (left+right)//2
                stack.extend(((node*2+1, middle, right), (node*2, left, middle)))
        # Match SQL ordering and LIMIT, including its over-budget sentinel.
        return sorted(result, key=lambda row: row[0])[:limit]


class QueueContext:
    def __init__(self, connection, blocks, *, validate_segment, validate_trip, cache=None, limits=None, domains=None,
                 visual_lanes=None, record_cache=None, seed_cache=None, dependency_cache=None,
                 index_cache=None, namespace=None, support_index=None, checkpoint_library=None, facility_support=None,
                 phase_classifier=None, classifier_contract=None):
        self.connection, self.blocks = connection, blocks
        self.ends = [block['end_seconds'] for block in blocks]
        self.validate_segment, self.validate_trip = validate_segment, validate_trip
        self.cache, self.limits = cache, limits or Limits()
        self.domains=domains
        self.visual_lanes = visual_lanes
        self.record_cache = record_cache
        self.seed_cache = seed_cache
        self.dependency_cache = dependency_cache if dependency_cache is not None else seed_cache
        self.index_cache = index_cache
        self.support_index = support_index
        self.checkpoint_library = checkpoint_library
        self.facility_support = None
        if facility_support is not None:
            if support_index is None:raise ValueError('Facility support requires independently verified source index')
            native=support_index.receipt['contract']
            self.facility_support=VerifiedFacilitySupport(validate_facility_support(facility_support,native['identity'],native['database_sha256']))
        self.order_cache = OrderedDict()
        self.phase_classifier=phase_classifier;self.classifier_contract=None
        self.classification_cache=OrderedDict();self.classification_bytes=0
        if phase_classifier is not None:
            from simz1_queue_checkpoint import kernel_contract
            if support_index is None:raise ValueError('Phase classification requires verified native index')
            expected=kernel_contract(support_index.receipt['contract'],support_index.receipt['sha256'],visual_lanes,
                phase_classifier.settings,facility_support=self.facility_support)
            if (classifier_contract!=expected or phase_classifier.identity!=support_index.receipt['contract']['identity'] or
                phase_classifier.geometry_sha256!=expected['geometry_sha256'] or
                phase_classifier.source_sqlite_sha256!=support_index.receipt['contract']['database_sha256'] or
                phase_classifier.facility_support!=self.facility_support):
                raise ValueError('Phase classifier is not bound to verified source/geometry/facility scope')
            self.classifier_contract=json.loads(encoded(expected))
        elif classifier_contract is not None:raise ValueError('Phase classification contract has no private evaluator')
        self.absence_geometry_sha256=hashlib.sha256(encoded(visual_lanes)).hexdigest()
        self.cache_namespace = namespace or self.namespace(domains, visual_lanes, self.limits)
        if support_index is not None:
            self.cache_namespace = hashlib.sha256(encoded((self.cache_namespace, support_index.receipt['sha256']))).hexdigest()
        if self.facility_support is not None:
            self.cache_namespace=hashlib.sha256(encoded((self.cache_namespace,self.facility_support))).hexdigest()
        if self.classifier_contract is not None:
            self.cache_namespace=hashlib.sha256(encoded((self.cache_namespace,self.classifier_contract))).hexdigest()
        self.metrics = dict(cache_hits=0, cache_misses=0, sql_queries=0, decoded_records=0,
                            decoded_bytes=0, compressed_bytes=0)

    def classify_consumer(self,ident,record):
        if self.phase_classifier is None:return None
        raw_sha=hashlib.sha256(encoded(record)).hexdigest();cache_key=(ident,raw_sha)
        if cache_key in self.classification_cache:
            self.classification_cache.move_to_end(cache_key);return self.classification_cache[cache_key][0]
        # Native-positive index entries need no second renderer query. An
        # unsupported native order is classified only when occupancy rejection
        # itself is proved; otherwise retain the conservative unknown branch.
        occupancy_proof=occupancy_absence(record,self.visual_lanes,geometry_sha256=self.absence_geometry_sha256)
        if occupancy_proof is None:return None
        at=hold_time(record)
        if at is None:
            if (record.get('Native_Occupancy') or {}).get('policy')!='corridor-length-v1':return None
            at=record['timestamps'][0]
        if not record['timestamps'][0]<=at<record['timestamps'][1]:return None
        records={ident:record}
        for before in (True,False):
            row=self.neighbour(ident,record['Replay_Journey_Key'],before)['record']
            if row is not None:records[row[0]]=row[1]
        trips={};output=[];events={};lane_coverage=[]
        for number,row in sorted(records.items()):
            journey=row['Replay_Journey_Key']
            if journey not in trips:trips[journey]=self.trip(journey)['trip']
            output.append({**row,'Trip':trips[journey]})
            times={(row['timestamps'][0],True),(row['timestamps'][1],False)}
            hold=hold_time(row)
            if hold is not None and row['timestamps'][0]<=hold<row['timestamps'][1]:times.add((hold,True))
            if number==ident:times.add((at,True))
            for epoch,inclusive in sorted(times):
                value=self.lane(row['vehicle'],epoch,inclusive)['event']
                lane_coverage.append(dict(vehicle=row['vehicle'],epoch=epoch,inclusive=inclusive,
                    result_sha256=hashlib.sha256(encoded(value)).hexdigest()))
                if value is not None:events[value[0]]=value[1]
        key=interval_key(record)
        packet=dict(records=output,lane_events=[value for _,value in sorted(events.items(),key=lambda item:(item[1]['time'],item[0]))],
            requests=[dict(key=key,epoch=at,role='classify',stage=None)],phases={key:'final'},checkpoints={})
        response=self.phase_classifier.classify(packet)
        states=response.get('states')
        if not isinstance(states,list) or len(states)!=1 or states[0].get('key')!=key or states[0].get('epoch')!=at:
            raise ValueError('Renderer classification differs from requested native epoch')
        value=states[0]['classification'];consumer=None
        # A partial geometry packet may omit an entry or its anchor support.
        # Positive terminal-lane classification supplies effective group/order.
        # The one negative below concerns anchor constraints ONLY: no HOLD and
        # independently rejected occupancy cannot enter BASE's anchors, FINAL's
        # eligible roster, native FIFO or departed precedence. The observation
        # may still draw an active moving body and remains geometric evidence.
        # The helper prioritizes a proven shared-upstream reason even for that
        # same moving observation; accept it only with our private schedule proof.
        if value['complete'] is True and value['represented'] is True and value['eligible'] is True and value['native_entry'] is True:
            if value.get('occupancy') is not None:raise ValueError('Renderer classification contradicts source-backed occupancy absence')
            order=value.get('order_time');group=json.loads(value['group_key'])
            # Current stages are safe integer ordinals/ticks. Unsupported
            # fractional fallback times stay unknown; never round them.
            if type(order) in (int,float) and math.isfinite(order) and order==int(order) and 0<=order<=9007199254740991:
                consumer=dict(complete=True,represented=True,occupancy=False,visual_order=int(order),
                    visual_group=tuple(group),eligible=value['eligible'])
        elif (value['complete'] is True and value['represented'] is False and value['eligible'] is False and
              value.get('occupancy') is None and value.get('departure_complete') is True and value.get('departure') is None and
              (value.get('reason')=='inactive_context_without_occupancy_or_hold' or
               value.get('reason')=='shared_upstream_without_blocking_facility' and self.facility_support is not None and
               record['Link_ID'] not in self.facility_support['blocking_links']) and
              value.get('hold') is None and hold_time(record) is None):
            consumer=dict(complete=True,represented=False,occupancy=False,visual_order=None,
                visual_group=None,eligible=False,scope='anchor_constraints_only')
        if consumer is not None:
            consumer['proof']=dict(schema='native-visual-consumer-classification-v1',record_sha256=raw_sha,epoch=at,
                classifier_sha256=hashlib.sha256(encoded(self.classifier_contract)).hexdigest(),occupancy_absence=occupancy_proof,
                support_records=[dict(id=number,sha256=hashlib.sha256(encoded(row)).hexdigest()) for number,row in sorted(records.items())],
                lane_coverage=lane_coverage,classification=value)
        size=len(encoded(consumer))+512
        while self.classification_cache and self.classification_bytes+size>8*1024*1024:
            _,(_,cost)=self.classification_cache.popitem(last=False);self.classification_bytes-=cost
        if size<=8*1024*1024:self.classification_cache[cache_key]=(consumer,size);self.classification_bytes+=size
        return consumer

    def phase_absence(self,record,at,role):
        """Only source-backed terminal absence, never an accepted vehicle pose."""
        proof=occupancy_absence(record,self.visual_lanes,geometry_sha256=self.absence_geometry_sha256)
        if proof is None:return None
        if role.startswith('fifo:'):
            return dict(schema='native-phase-absence-v1',reason='native_occupancy_unavailable',epoch=at,occupancy=proof)
        if role not in ('base','final') or self.facility_support is None:return None
        if record.get('Link_ID') in self.facility_support['blocking_links']:return None
        start,end=record['timestamps'];hold=hold_time(record)
        if hold is None or at!=hold or not start<=at<end:return None
        link=(self.visual_lanes.get('links') or {}).get(record.get('Link_ID'))
        if not isinstance(link,dict) or link.get('offset_eligible') is False:return None
        lanes=link.get('num_lanes');opposing=link.get('opposing_lanes',0)
        if (type(lanes) is not int or not 1<=lanes<=12 or type(opposing) is not int or not 0<=opposing<=12 or
            opposing and not isinstance(link.get('reverse_link'),str)):return None
        # A strict subset of compatiblePath and a non-degenerate local rigid
        # body. Exact geometry and fraction are independently rechecked by JS.
        path,base=record.get('path'),link.get('path')
        valid=lambda points:isinstance(points,list) and len(points)>=2 and all(isinstance(p,list) and len(p)==2 and
            all(type(v) in (int,float) and math.isfinite(v) for v in p) and abs(p[0])<=180 and abs(p[1])<85 for p in points)
        if not valid(path) or not valid(base):return None
        if any(abs(path[i][axis]-base[i][axis])>1e-9 for i in (0,-1) for axis in (0,1)):return None
        if math.hypot(base[0][0]-base[-1][0],base[0][1]-base[-1][1])<1e-7:return None
        dimensions=record.get('Vehicle_Dimensions') or record.get('Vehicle_Physical_Dimensions')
        if not isinstance(dimensions,dict) or not isinstance(dimensions.get('source'),str) or not dimensions['source'].strip():return None
        if any(type(dimensions.get(key)) not in (int,float) or not math.isfinite(dimensions[key]) or dimensions[key]<=0 for key in ('length_m','width_m')):return None
        plan=record.get('Motion_Plan') or {}
        if plan.get('status')=='unavailable' or not isinstance(plan.get('phases'),list):return None
        if not any(isinstance(p,list) and len(p)==5 and all(type(v) in (int,float) and math.isfinite(v) for v in p) and
            p[0]<=at<=p[1] and p[1]>=end and p[3]==p[4]==0 and p[2]==plan.get('distance_m') for p in plan['phases']):return None
        observed=self.lane(record['vehicle'],at,True)['event']
        event=observed[1] if observed else None
        if (not isinstance(event,dict) or event.get('type')!='entered lane' or event.get('vehicle')!=record['vehicle'] or
            event.get('link')!=record['Link_ID'] or type(event.get('time')) not in (int,float) or not start<=event['time']<=at):return None
        lane=(link.get('native_lanes') or {}).get(event.get('lane'))
        if not isinstance(lane,dict) or lane.get('index') is not None or not isinstance(lane.get('to_lanes'),list) or not lane['to_lanes']:return None
        return dict(schema='native-phase-absence-v1',reason='shared_upstream_without_blocking_facility',epoch=at,
            occupancy=proof,facility_support_sha256=hashlib.sha256(encoded(self.facility_support)).hexdigest(),
            lane_event_sha256=hashlib.sha256(encoded(event)).hexdigest())

    @staticmethod
    def namespace(domains, visual_lanes, limits=None):
        domain_signature=hashlib.sha256(encoded({key:sorted(value) for key,value in sorted(domains.items())})).hexdigest() if domains is not None else None
        geometry_signature=hashlib.sha256(encoded(visual_lanes)).hexdigest() if visual_lanes is not None else None
        signature=(DEPENDENCY_POLICY,tuple(asdict(limits or Limits()).items()),domain_signature,geometry_signature)
        return hashlib.sha256(encoded(signature)).hexdigest()

    def snapshot_rows(self, index, at):
        if self.index_cache is not None:
            key=(POLICY,self.cache_namespace,'scalar_index',index)
            found, intervals=self.index_cache.get(key)
            if not found:
                # Bound both construction and retention. Dense blocks which
                # exceed this optional index use the original complete SQL.
                rows=list(self.query('''SELECT s.id,s.journey,s.vehicle,s.start,s.end,length(s.payload)
                    FROM segment_blocks b INDEXED BY segments_block JOIN segments s ON s.id=b.segment
                    WHERE b.block=? ORDER BY b.segment LIMIT 32769''',(index,)))
                intervals=ScalarIntervals(rows) if len(rows)<=32768 else None
                if intervals is not None and intervals.accounted_bytes>self.index_cache.max_bytes:
                    intervals=None
                self.index_cache.put(key,intervals,intervals.accounted_bytes if intervals is not None else 256)
            if intervals is not None:
                return intervals.at(at,self.limits.max_rows+1)
        return list(self.query('''SELECT s.id,s.journey,s.vehicle,s.start,s.end,length(s.payload)
            FROM segment_blocks b INDEXED BY segments_block JOIN segments s ON s.id=b.segment
            WHERE b.block=? AND s.start<=? AND s.end>? ORDER BY b.segment LIMIT ?''',
            (index,at,at,self.limits.max_rows+1)))

    def reservation_order(self, record):
        native = record.get('Native_Occupancy') or {}
        fields = ('policy', 'corridor_id', 'model_slot', 'ordinal', 'passage_kind',
                  'receipt_link', 'exit_from_link', 'passage_links', 'passage_slots', 'exit_links', 'exit_slots')
        try:
            key = (record.get('Link_ID'), *(tuple(native[name]) if isinstance(native.get(name), list)
                                          else native.get(name) for name in fields))
            hash(key)
        except TypeError:
            return self._reservation_order(record)
        if key in self.order_cache:
            self.order_cache.move_to_end(key)
            return self.order_cache[key]
        result = self._reservation_order(record)
        self.order_cache[key] = result
        if len(self.order_cache) > 4096:
            self.order_cache.popitem(last=False)
        return result

    def _reservation_order(self, record):
        """Return only a supported native FIFO ordinal, never a guessed order.

        A later reservation in the same corridor/slot cannot determine an
        earlier anchor. Across domains, a leading vehicle can have a newer
        ordinal after transfer while its rear still constrains the old domain.
        Missing or incompatible topology keeps the conservative closure.
        """
        metadata = self.visual_lanes or {}
        links = metadata.get('links') or {}
        corridors = (metadata.get('occupancy_corridors') or {}).get('corridors') or {}
        native = record.get('Native_Occupancy') or {}
        ordinal, slot = native.get('ordinal'), native.get('model_slot')
        corridor = corridors.get(native.get('corridor_id'))
        if (metadata.get('schema_version') != 1 or not metadata.get('available') or
                (metadata.get('occupancy_corridors') or {}).get('schema') != 'corridor-length-v1' or
                native.get('policy') != 'corridor-length-v1' or
                type(ordinal) is not int or not 0 <= ordinal <= 9007199254740991 or
                type(slot) is not int or slot < 0 or not isinstance(corridor, dict)):
            return None
        members = corridor.get('link_ids')
        represented = corridor.get('represented_lanes')
        if (not isinstance(members, list) or not members or type(represented) is not int or
                slot >= represented):
            return None

        def lane_ok(ident, index):
            link = links.get(ident) or {}
            lanes = link.get('num_lanes')
            opposing, path = link.get('opposing_lanes', 0), link.get('path')
            if (type(index) is not int or index < 0 or type(lanes) is not int or not 1 <= lanes <= 12 or
                    index >= lanes or link.get('offset_eligible') is False or type(opposing) is not int or
                    not 0 <= opposing <= 12 or opposing and not isinstance(link.get('reverse_link'), str) or
                    link.get('from_node') is None or link.get('to_node') is None or
                    not isinstance(path, list) or len(path) < 2):
                return False
            if not all(isinstance(point, list) and len(point) >= 2 and
                       all(type(v) in (int, float) and math.isfinite(v) for v in point[:2]) and
                       abs(point[0]) <= 180 and abs(point[1]) < 85 for point in path):
                return False
            # Conservative subset of the renderer's nondegenerate geometry.
            # Unknown or enormous shapes retain the unfiltered closure.
            distances = [math.hypot(a[0]-b[0], a[1]-b[1])*111196 for a,b in zip(path,path[1:])]
            return max(distances) > 1e-5 and max(distances) < 100000

        def connected(sequence):
            for first, second in zip(sequence, sequence[1:]):
                a, b = links[first], links[second]
                if a['to_node'] != b['from_node'] or a['path'][-1][:2] != b['path'][0][:2] or any(
                        a.get('osm_tags', {}).get(k) != b.get('osm_tags', {}).get(k) for k in ('bridge', 'tunnel', 'layer')):
                    return False
            return True

        if not all(lane_ok(ident, slot) for ident in members) or not connected(members):
            return None
        supported = set(members)
        for name, slots_name, receipt in (('passage_links', 'passage_slots', 'receipt_link'),
                                          ('exit_links', 'exit_slots', 'exit_from_link')):
            sequence = native.get(name)
            if sequence is None:
                continue
            slots = native.get(slots_name)
            if (not isinstance(sequence, list) or not sequence or not isinstance(slots, list) or
                    len(slots) != len(sequence) or native.get(receipt) not in members or
                    not all(lane_ok(ident, index) for ident, index in zip(sequence, slots))):
                return None
            if name == 'exit_links':
                if native.get('passage_kind') != 'boundary_exit' or not connected([native[receipt], *sequence]):
                    return None
            elif not connected([*sequence, native[receipt]]):
                return None
            supported.update(sequence)
        return ordinal if record.get('Link_ID') in supported else None

    def query(self, sql, args):
        checkpoint(queue_sql_queries=self.metrics['sql_queries'])
        self.metrics['sql_queries'] += 1
        return self.connection.execute(sql, args)

    def cached(self, key, create):
        checkpoint()
        key = (POLICY, self.cache_namespace, *key)
        found, value = self.cache.get(key) if self.cache is not None else (False, None)
        if found:
            self.metrics['cache_hits'] += 1
            return value
        self.metrics['cache_misses'] += 1
        value = create()
        if self.cache is not None:
            # Cached objects are only read; payload hydration happens in JS after
            # serialization. No window-specific state is stored in this cache.
            self.cache.put(key, value, len(encoded(value)) + 256)
        return value

    def decode(self, raw):
        if len(raw) > self.limits.max_compressed_bytes:
            raise Incomplete('compressed_byte_limit')
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(raw, self.limits.max_record_bytes + 1)
        if len(decoded) > self.limits.max_record_bytes or inflater.unconsumed_tail:
            raise Incomplete('record_byte_limit')
        if not inflater.eof or inflater.unused_data:
            raise ValueError('Native queue context contains invalid compressed JSON')
        self.metrics['decoded_records'] += 1
        self.metrics['decoded_bytes'] += len(decoded)
        self.metrics['compressed_bytes'] += len(raw)
        return decoded

    def bucket(self, index, at):
        if self.record_cache is not None:
            return self.compact_bucket(index, at)
        def read():
            # Bound the active snapshot BEFORE LIMIT. A wide source bucket can
            # contain thousands of departed records but only a few simultaneous
            # vehicles. Historical rows are not queue predecessors at this epoch.
            # Filtering scalar start/end through the covering block index avoids
            # decoding them; byte/row limits still apply to the real snapshot.
            rows = list(self.query('''SELECT s.id,s.journey,s.vehicle,s.start,s.end,length(s.payload)
                FROM segment_blocks b INDEXED BY segments_block JOIN segments s ON s.id=b.segment
                WHERE b.block=? AND s.start<=? AND s.end>? ORDER BY b.segment LIMIT ?''',
                (index, at, at, self.limits.max_rows + 1)))
            costs = dict(logical_rows=len(rows), compressed_bytes=sum(row[5] for row in rows), decoded_bytes=0)
            if len(rows) > self.limits.max_rows:
                return dict(reason='row_limit', costs=costs, records=[])
            if costs['compressed_bytes'] > self.limits.max_compressed_bytes:
                return dict(reason='compressed_byte_limit', costs=costs, records=[])
            expected = {row[0]: row for row in rows}
            result = []
            try:
                for ident, raw in self.query('''SELECT s.id,s.payload FROM segment_blocks b INDEXED BY segments_block
                    JOIN segments s ON s.id=b.segment
                    WHERE b.block=? AND s.start<=? AND s.end>? ORDER BY b.segment LIMIT ?''',
                    (index, at, at, self.limits.max_rows + 1)):
                    row = expected[ident]
                    decoded = self.decode(raw)
                    costs['decoded_bytes'] += len(decoded)
                    if costs['decoded_bytes'] > self.limits.max_decoded_bytes:
                        raise Incomplete('decoded_byte_limit')
                    record = self.validate_segment(decoded, row[1], row[2], row[3], row[4])
                    result.append([ident, record])
            except Incomplete as error:
                return dict(reason=str(error), costs=costs, records=[])
            return dict(reason=None, costs=costs, records=result)
        return self.cached(('bucket', index, at), read)

    def compact_bucket(self, index, at):
        """Cache scalar snapshots and each validated record independently.

        Neighboring hold epochs overlap heavily. Caching entire decoded
        snapshots duplicates the same records, evicts useful entries and then
        repeatedly decompresses them. Logical budgets still charge every row
        and every native byte, including cache hits, exactly as before.
        """
        rows = self.cached(('bucket_rows', index, at), lambda: self.snapshot_rows(index, at))
        costs = dict(logical_rows=len(rows), compressed_bytes=sum(row[5] for row in rows), decoded_bytes=0)
        if len(rows) > self.limits.max_rows:
            return dict(reason='row_limit', costs=costs, records=[])
        if costs['compressed_bytes'] > self.limits.max_compressed_bytes:
            return dict(reason='compressed_byte_limit', costs=costs, records=[])
        result=[]
        try:
            # Bounded batches avoid one query per record while retaining no
            # more compressed data than the original full snapshot did.
            for offset in range(0,len(rows),256):
                batch=rows[offset:offset+256]
                ready, missing={},[]
                for row in batch:
                    key=(POLICY,self.cache_namespace,'record',row[0])
                    found,value=self.record_cache.get(key)
                    if found:
                        self.metrics['cache_hits']+=1
                        ready[row[0]]=value
                    else:
                        self.metrics['cache_misses']+=1
                        missing.append(row[0])
                raw_by_id={}
                if missing:
                    raw_by_id=dict(self.query('SELECT id,payload FROM segments WHERE id IN ('+
                                             ','.join('?' for _ in missing)+')',missing))
                for ident,journey,vehicle,start,end,compressed_bytes in batch:
                    value=ready.get(ident)
                    if value is None:
                        raw=raw_by_id.pop(ident)
                        if len(raw)!=compressed_bytes: raise ValueError('Native queue record size changed')
                        decoded=self.decode(raw)
                        record=self.validate_segment(decoded,journey,vehicle,start,end)
                        value=(record,len(decoded))
                        self.record_cache.put((POLICY,self.cache_namespace,'record',ident),value,len(decoded)+256)
                    record,decoded_bytes=value
                    costs['decoded_bytes']+=decoded_bytes
                    if costs['decoded_bytes']>self.limits.max_decoded_bytes:
                        raise Incomplete('decoded_byte_limit')
                    result.append([ident,record])
        except Incomplete as error:
            return dict(reason=str(error),costs=costs,records=[])
        return dict(reason=None,costs=costs,records=result)

    def neighbour(self, ident, journey, before):
        def read():
            operator, order = ('<', 'DESC') if before else ('>', 'ASC')
            row = self.query(f'''SELECT id,payload,vehicle,start,end FROM segments INDEXED BY segments_journey
                WHERE journey=? AND id {operator} ? ORDER BY id {order} LIMIT 1''', (journey, ident)).fetchone()
            if row is None:
                return dict(record=None, costs=dict(logical_rows=0, compressed_bytes=0, decoded_bytes=0))
            number, raw, vehicle, start, end = row
            decoded = self.decode(raw)
            record = self.validate_segment(decoded, journey, vehicle, start, end)
            if self.record_cache is not None:
                self.record_cache.put((POLICY,self.cache_namespace,'record',number),(record,len(decoded)),len(decoded)+256)
            return dict(record=[number, record], costs=dict(logical_rows=1, compressed_bytes=len(raw), decoded_bytes=len(decoded)))
        return self.cached(('neighbour', ident, journey, before), read)

    def lane(self, vehicle, at, inclusive):
        def read():
            operator = '<=' if inclusive else '<'
            row = self.query(f'''SELECT seq,time,payload FROM lane_events INDEXED BY lanes_vehicle_time
                WHERE vehicle=? AND time {operator} ? ORDER BY time DESC,seq DESC LIMIT 1''', (vehicle, at)).fetchone()
            if row is None:
                return dict(event=None, costs=dict(logical_rows=0, compressed_bytes=0, decoded_bytes=0))
            seq, time, raw = row
            decoded = self.decode(raw)
            event = json.loads(decoded)
            if not isinstance(event, dict) or event.get('vehicle') != vehicle or event.get('time') != time:
                raise ValueError('Native queue context lane identity/time mismatch')
            if self.seed_cache is not None and self.cache is not None:
                self.cache.put((POLICY,self.cache_namespace,'lane_seq',seq),event,len(encoded(event))+256)
            return dict(event=[seq, event], costs=dict(logical_rows=1, compressed_bytes=len(raw), decoded_bytes=len(decoded)))
        return self.cached(('lane', vehicle, at, inclusive), read)

    def trip(self, journey):
        def read():
            row = self.query('SELECT metadata FROM journeys WHERE key=?', (journey,)).fetchone()
            if row is None:
                raise ValueError('Native queue context journey has no metadata')
            raw = row[0].encode('utf-8') if isinstance(row[0], str) else row[0]
            if len(raw) > self.limits.max_record_bytes:
                raise Incomplete('record_byte_limit')
            trip = json.loads(raw)
            self.validate_trip(trip)
            return dict(trip=trip, costs=dict(logical_rows=1, compressed_bytes=0, decoded_bytes=len(raw)))
        return self.cached(('trip', journey), read)

    def native_record(self, ident):
        key=(POLICY,self.cache_namespace,'record',ident)
        found,value=self.record_cache.get(key) if self.record_cache is not None else (False,None)
        if not found:
            row=self.query('SELECT journey,vehicle,start,end,payload FROM segments WHERE id=?',(ident,)).fetchone()
            if row is None:raise ValueError('Native cached closure record is missing')
            journey,vehicle,start,end,raw=row
            decoded=self.decode(raw)
            value=(self.validate_segment(decoded,journey,vehicle,start,end),len(decoded))
            if self.record_cache is not None:self.record_cache.put(key,value,len(decoded)+256)
        return value[0]

    def dependencies(self, ident, record, block, hold):
        """Memoize the immutable edges, not a root's traversal or its budget.

        Every root still visits its native dependency graph in the original
        order and charges the original snapshot/neighbour costs. The expensive
        global snapshot and geometric predicates are evaluated once per node.
        """
        key=(POLICY,self.cache_namespace,'dependencies',ident)
        found,result=self.dependency_cache.get(key) if self.dependency_cache is not None else (False,None)
        if found:
            self.metrics['cache_hits']+=1
            return result
        snapshot=self.bucket(block,hold)
        missing=set()
        neighbors=self.domains.get(record['Link_ID']) if self.domains is not None else None
        if neighbors is None:missing.add(record['Link_ID'])
        candidates=[]
        if not snapshot['reason']:
            own_order=self.reservation_order(record)
            own_native=record.get('Native_Occupancy') or {}
            for other_id,other in snapshot['records']:
                related=neighbors is None or other['Link_ID'] in neighbors or other['Link_ID'] not in self.domains
                if self.domains is None or other['Link_ID'] not in self.domains:missing.add(other['Link_ID'])
                if not related:continue
                other_order=self.reservation_order(other) if own_order is not None else None
                other_native=other.get('Native_Occupancy') or {}
                same_slot=(own_native.get('corridor_id'),own_native.get('model_slot')) == (
                    other_native.get('corridor_id'),other_native.get('model_slot'))
                causal=not same_slot or own_order is None or other_order is None or other_order<=own_order
                if causal and other['timestamps'][0]<=hold<other['timestamps'][1]:candidates.append(other_id)
        result=dict(costs=snapshot['costs'],reason=snapshot['reason'],candidates=candidates,
                    missing_topology_links=sorted(missing))
        if self.dependency_cache is not None:self.dependency_cache.put(key,result,len(encoded(result))+256)
        return result

    def seed(self, ident, seed):
        if self.checkpoint_library is not None:
            try:
                prepared=self.checkpoint_library.resolved_seed(self,ident,seed)
                if prepared is not None:return prepared
            except Incomplete as error:
                return dict(complete=False,reason=str(error),metrics={},record_keys=[],missing_topology_links=[],
                    segments=[],transition_segments=[],trips={},lane_events=[])
        if self.support_index is not None and self.domains is not None:
            return self.indexed_seed(ident, seed)
        def resolve():
            counts = dict(logical_rows=0, compressed_bytes=0, decoded_bytes=0, buckets=0, depth=0,
                          records=0, hold_records=0, moving_records=0)
            visited, records, moving, transitions, trips, events, charged = set(), {}, {}, {}, {}, {}, set()
            missing_topology=set()

            def charge(value, key):
                if key in charged:
                    return
                charged.add(key)
                for field, limit in (('logical_rows', 'max_rows'), ('compressed_bytes', 'max_compressed_bytes'),
                                     ('decoded_bytes', 'max_decoded_bytes')):
                    counts[field] += value['costs'][field]
                    if counts[field] > getattr(self.limits, limit):
                        raise Incomplete({'logical_rows': 'row_limit', 'compressed_bytes': 'compressed_byte_limit',
                                          'decoded_bytes': 'decoded_byte_limit'}[field])

            try:
                pending = deque([(ident, seed, 0)])
                scheduled = {ident}
                while pending:
                    checkpoint(queue_resolved_records=len(records))
                    number, record, depth = pending.popleft()
                    if number in records:
                        continue
                    counts['depth'] = max(counts['depth'], depth)
                    if depth > self.limits.max_depth:
                        raise Incomplete('depth_limit')
                    if len(records) + len(moving) >= self.limits.max_records:
                        raise Incomplete('record_limit')
                    records[number] = record
                    counts['records'] = len(records) + len(moving)
                    counts['hold_records'] = len(records)
                    hold = hold_time(record)
                    if hold is None or not record['timestamps'][0] <= hold < record['timestamps'][1]:
                        raise Incomplete('invalid_hold_interval')
                    block = bisect_right(self.ends, hold)
                    if block >= len(self.blocks) or hold < self.blocks[block]['start_seconds']:
                        raise Incomplete('hold_outside_source_coverage')
                    if block not in visited:
                        if len(visited) >= self.limits.max_buckets:
                            raise Incomplete('bucket_limit')
                        visited.add(block)
                        counts['buckets'] = len(visited)
                    snapshot = self.dependencies(number,record,block,hold) if self.seed_cache is not None else self.bucket(block, hold)
                    charge(snapshot, ('bucket', block, hold))
                    if snapshot['reason']:
                        raise Incomplete(snapshot['reason'])
                    # Only a backed road domain can constrain this anchor.
                    # Without topology retain the old conservative closure;
                    # never certify missing geometry by silently excluding it.
                    neighbors=self.domains.get(record['Link_ID']) if self.domains is not None else None
                    own_order = self.reservation_order(record) if self.seed_cache is None else None
                    if neighbors is None:missing_topology.add(record['Link_ID'])
                    if self.seed_cache is not None:
                        missing_topology.update(snapshot['missing_topology_links'])
                        candidates=((other_id,self.native_record(other_id)) for other_id in snapshot['candidates']
                                    if other_id not in scheduled and other_id not in moving)
                    else:
                        candidates=snapshot['records']
                    for other_id, other in candidates:
                        related=(neighbors is None or other['Link_ID'] in neighbors or other['Link_ID'] not in self.domains)
                        if self.domains is None or other['Link_ID'] not in self.domains:missing_topology.add(other['Link_ID'])
                        # These exclusions were already required below. Apply
                        # them before recomputing geometry/FIFO eligibility for
                        # unrelated or previously visited native records.
                        if not related or other_id in scheduled or other_id in moving:
                            continue
                        other_order = self.reservation_order(other) if own_order is not None else None
                        own_native, other_native = record.get('Native_Occupancy') or {}, other.get('Native_Occupancy') or {}
                        same_slot = (own_native.get('corridor_id'), own_native.get('model_slot')) == (
                            other_native.get('corridor_id'), other_native.get('model_slot'))
                        causal = not same_slot or own_order is None or other_order is None or other_order <= own_order
                        if related and causal and other['timestamps'][0] <= hold < other['timestamps'][1] and other_id not in scheduled and other_id not in moving:
                            if len(scheduled) + len(moving) >= self.limits.max_records:
                                raise Incomplete('record_limit')
                            if hold_time(other) is None:
                                # A leading body can already be moving into the
                                # receiver when a following hold starts. Keep its
                                # native interval and neighbors without inventing
                                # a hold or recursively assigning it an anchor.
                                moving[other_id] = other
                                counts['records'] = len(records) + len(moving)
                                counts['moving_records'] = len(moving)
                                prior = self.neighbour(other_id, other['Replay_Journey_Key'], True)
                                charge(prior, ('neighbour', other_id, True))
                                if prior['record'] is not None:
                                    prior_id, prior_record = prior['record']
                                    if (prior_record['timestamps'][1] == other['timestamps'][0] and
                                            hold_time(prior_record) is not None and prior_id not in scheduled):
                                        # A historical moving body's release can
                                        # start behind a now-departed leader.
                                        # Resolve that actual predecessor HOLD
                                        # just as for a visible moving interval.
                                        if len(scheduled) + len(moving) >= self.limits.max_records:
                                            raise Incomplete('record_limit')
                                        scheduled.add(prior_id)
                                        pending.append((prior_id, prior_record, depth + 1))
                            else:
                                scheduled.add(other_id)
                                pending.append((other_id, other, depth + 1))

                transitions.update(moving)
                primary = {**records, **moving}
                for number, record in sorted(primary.items()):
                    for before in (True, False):
                        value = self.neighbour(number, record['Replay_Journey_Key'], before)
                        charge(value, ('neighbour', number, before))
                        if value['record'] is not None:
                            neighbour_id, neighbour = value['record']
                            if neighbour_id not in primary:
                                transitions[neighbour_id] = neighbour
                all_records = {**records, **transitions}
                keys = {}
                for number, record in sorted(all_records.items()):
                    key = interval_key(record)
                    if key in keys and keys[key] != record:
                        raise Incomplete('contradictory_interval_identity')
                    keys[key] = record
                    journey = record['Replay_Journey_Key']
                    if journey not in trips:
                        value = self.trip(journey)
                        charge(value, ('trip', journey))
                        trips[journey] = value['trip']
                    at_times = [(record['timestamps'][0], True), (record['timestamps'][1], False)]
                    if hold_time(record) is not None:
                        at_times.append((hold_time(record), True))
                    for at, inclusive in at_times:
                        value = self.lane(record['vehicle'], at, inclusive)
                        charge(value, ('lane', record['vehicle'], at, inclusive))
                        if value['event'] is not None:
                            seq, event = value['event']
                            events[seq] = event
                result = dict(complete=True, reason=None, metrics=counts, missing_topology_links=sorted(missing_topology),
                            record_keys=list(dict.fromkeys(interval_key(row) for _, row in sorted(records.items()))),
                            segments=list(records.values()), transition_segments=list(transitions.values()), trips=trips,
                            lane_events=[[seq, row] for seq, row in sorted(events.items(), key=lambda item: (item[1]['time'], item[0]))])
                if self.seed_cache is not None:
                    # References preserve order, not copies of the full native
                    # trees. Every reference is hydrated from this same source.
                    result['_refs'] = dict(segments=list(records), transitions=list(transitions),
                                           trips=list(trips), events=[seq for seq,_ in result['lane_events']])
                return result
            except Incomplete as error:
                return dict(complete=False, reason=str(error), metrics=counts, missing_topology_links=sorted(missing_topology),record_keys=[],
                            segments=[], transition_segments=[], trips={}, lane_events=[])
        # Full closures duplicate references to many snapshots and crowd out
        # compact lookups. With independent record caching, assemble closures
        # from those immutable records rather than retaining duplicate trees.
        if self.seed_cache is not None:
            key=(POLICY,self.cache_namespace,'seed_refs',ident)
            found,compact=self.seed_cache.get(key)
            if found:
                self.metrics['cache_hits']+=1
                return self.hydrate_seed(compact)
            self.metrics['cache_misses']+=1
            result=resolve()
            references=result.pop('_refs',None)
            compact={key:value for key,value in result.items() if key not in ('segments','transition_segments','trips','lane_events')}
            compact['_refs']=references
            self.seed_cache.put(key,compact,len(encoded(compact))+256)
            return result
        return resolve() if self.record_cache is not None else self.cached(('seed', ident), resolve)

    def indexed_seed(self, ident, seed):
        """Resolve roles at their actual epochs using the sealed support index.

        HOLD anchors and forming FIFO poses are distinct graph nodes. A moving
        predecessor is expanded at the caller's epoch, including its own
        predecessors after a corridor transfer. Repeated nodes are memoized;
        reciprocal nodes remain in the graph rather than losing an edge.
        """
        counts = dict(logical_rows=0, compressed_bytes=0, decoded_bytes=0, buckets=0,
                      depth=0, records=0, hold_records=0, moving_records=0,
                      support_queries=0, dependency_states=0, dependency_edges=0)
        primary, auxiliary, trips, events, missing = {}, {}, {}, {}, set()
        loaded, scheduled, visited, edges = {}, set(), set(), set()
        buckets, lane_visited = set(), set()
        support_queries = {}
        absence_proofs = {}
        pending = deque()
        source = self.support_index

        def valid_hold(row):
            value=hold_time(row)
            return value if value is not None and row['timestamps'][0]<=value<row['timestamps'][1] else None

        def charge(rows=0, compressed=0, decoded=0):
            for key, value, limit, reason in (
                ('logical_rows', rows, self.limits.max_rows, 'row_limit'),
                ('compressed_bytes', compressed, self.limits.max_compressed_bytes, 'compressed_byte_limit'),
                ('decoded_bytes', decoded, self.limits.max_decoded_bytes, 'decoded_byte_limit')):
                counts[key] += value
                if counts[key] > limit:
                    raise Incomplete(reason)

        def load(number):
            if number not in loaded:
                row = self.query('SELECT journey,vehicle,start,end,payload FROM segments WHERE id=?', (number,)).fetchone()
                if row is None:
                    raise ValueError('Indexed support record missing from native source')
                journey, vehicle, start, end, raw = row
                decoded = self.decode(raw)
                charge(1, len(raw), len(decoded))
                loaded[number] = self.validate_segment(decoded, journey, vehicle, start, end)
            return loaded[number]

        def schedule(number, record, epoch, role, depth, parent=None):
            state = (number, epoch, role)
            if parent is not None:
                edges.add((parent, state))
                counts['dependency_edges'] = len(edges)
            if number not in primary:
                if len(primary) >= self.limits.max_records:
                    raise Incomplete('record_limit')
                primary[number] = record
            if state not in scheduled:
                if depth > self.limits.max_depth:
                    raise Incomplete('depth_limit')
                scheduled.add(state)
                pending.append((state, record, depth))
                counts['depth'] = max(counts['depth'], depth)
            counts['records'] = len(primary)

        def neighbour_once(number, record, before):
            key = (number, before)
            if key not in neighbour_cache:
                operator, order = ('<', 'DESC') if before else ('>', 'ASC')
                row = self.query('SELECT id,journey,vehicle,start,end,payload FROM segments INDEXED BY segments_journey WHERE journey=? AND id ' +
                    operator + ' ? ORDER BY id ' + order + ' LIMIT 1', (record['Replay_Journey_Key'], number)).fetchone()
                if row is None:
                    neighbour_cache[key]=None
                else:
                    adjacent_id,journey,vehicle,start,end,raw=row
                    charge(1)
                    if adjacent_id not in loaded:
                        decoded=self.decode(raw)
                        charge(compressed=len(raw),decoded=len(decoded))
                        loaded[adjacent_id]=self.validate_segment(decoded,journey,vehicle,start,end)
                    neighbour_cache[key]=(adjacent_id,loaded[adjacent_id])
            return neighbour_cache[key]

        neighbour_cache = {}
        try:
            # Charge and validate the seed as a real source read, just like every
            # dependency; do not trust a client-provided interval as an index key.
            record = load(ident)
            if record != seed:
                raise ValueError('Queue seed differs from indexed native source')
            at = valid_hold(record)
            if at is None:
                raise Incomplete('invalid_hold_interval')
            schedule(ident, record, at, 'final', 0)
            while pending:
                state, record, depth = pending.popleft()
                if state in visited:
                    continue
                visited.add(state)
                number, at, role = state
                is_fifo=role.startswith('fifo:');is_project=role.startswith('project:')
                stage_order,stage_key=json.loads(role.split(':',1)[1]) if is_fifo or is_project else (self.reservation_order(record),interval_key(record))
                scope='fifo' if is_fifo else role
                counts['dependency_states'] = len(visited)
                checkpoint(queue_resolved_records=len(primary))
                if not record['timestamps'][0] <= at < record['timestamps'][1]:
                    raise Incomplete('invalid_dependency_epoch')
                block = bisect_right(self.ends, at)
                if block >= len(self.blocks) or at < self.blocks[block]['start_seconds']:
                    raise Incomplete('hold_outside_source_coverage')
                buckets.add(block)
                counts['buckets'] = len(buckets)
                if len(buckets) > self.limits.max_buckets:
                    raise Incomplete('bucket_limit')
                own_order = self.reservation_order(record)
                if own_order is None and (is_fifo or role in ('base','final')):
                    absence=self.phase_absence(record,at,role)
                    if absence is not None:
                        # Source-backed absence terminates this consumer only;
                        # the raw interval remains in geometry/observations.
                        absence_proofs[str(state)]=absence
                        continue
                if role=='final':
                    schedule(number,record,at,'base',depth+1,state)
                native = record.get('Native_Occupancy') or {}
                own_group = (native.get('corridor_id'), native.get('model_slot'))
                neighbors = source.domains_for(number,self.domains)
                if neighbors is None:
                    raise Incomplete('support_topology_missing')
                query_key=(at,tuple(sorted(neighbors)),own_group,own_order,scope,record['Link_ID'])
                if role=='interpolate' or is_project:
                    support_queries[query_key]=[]
                if query_key not in support_queries:
                    rows=source.candidates(at,neighbors,self.limits.max_rows+1,
                        group=own_group,order=own_order,role=scope,link=record['Link_ID'],known_links=self.domains)
                    counts['support_queries'] += 1
                    charge(len(rows))
                    support_queries[query_key]=rows
                rows=support_queries[query_key]
                for scalar in rows:
                    other_id = scalar['id']
                    if other_id == number:
                        continue
                    unknown,same,transfer,geometric_hold=phase_relations(own_order,own_group,
                        record['vehicle'],interval_key(record),scalar,scope,at)
                    if scope=='base':
                        required=base_predecessor(own_order,own_group,interval_key(record),scalar)
                    else:
                        required=unknown or same or transfer or geometric_hold
                    if not required:
                        continue
                    other = load(other_id)
                    other_hold = valid_hold(other)
                    if scope=='base':
                        if other_hold is not None:
                            schedule(other_id,other,other_hold,'base',depth+1,state)
                        if other_hold is None or at<other_hold:
                            schedule(other_id,other,at,'interpolate',depth+1,state)
                            # baseAnchors uses unconstrained interpolation. Its
                            # release origin may still depend on a previous
                            # final anchor; it does not invoke fifoPoseAt here.
                            anchor_prior=neighbour_once(other_id,other,True)
                            if anchor_prior is not None and anchor_prior[1]['timestamps'][1]==other['timestamps'][0]:
                                prior_hold=valid_hold(anchor_prior[1])
                                if prior_hold is not None:
                                    schedule(anchor_prior[0],anchor_prior[1],prior_hold,'final',depth+1,state)
                    else:
                        rank=stage_order
                        earlier=(rank is None or scalar['ordinal'] is None or scalar['ordinal']<rank or
                            scalar['ordinal']==rank and js_key_before(interval_key(other),stage_key))
                        anchor_role='final' if earlier else 'base'
                        if other_hold is not None:
                            schedule(other_id,other,other_hold,anchor_role,depth+1,state)
                        if other_hold is None or at<other_hold:
                            stage=json.dumps([rank,stage_key],separators=(',',':'))
                            if unknown or same or is_fifo and transfer:
                                schedule(other_id,other,at,'fifo:'+stage,depth+1,state)
                            if role=='final' and (unknown or transfer):
                                schedule(other_id,other,at,'project:'+stage,depth+1,state)
                # Future anchors and release anchors are immutable dependencies
                # even when the requested pose precedes its own HOLD epoch.
                own_hold = valid_hold(record)
                if (is_fifo or is_project) and own_hold is not None:
                    earlier=(own_order is None or stage_order is None or own_order<stage_order or
                        own_order==stage_order and js_key_before(interval_key(record),stage_key))
                    anchor_role='final' if earlier else 'base'
                    schedule(number,record,own_hold,anchor_role,depth+1,state)
                if role=='interpolate' and own_hold is not None:
                    schedule(number,record,own_hold,'base',depth+1,state)
                prior = neighbour_once(number, record, True)
                if prior is not None:
                    prior_id, previous = prior
                    auxiliary[prior_id] = previous
                    previous_hold = valid_hold(previous)
                    # BASE/FINAL also consume the previous release in lower,
                    # desiredStart and the rigid pose; an auxiliary raw row is
                    # not a certificate for that previous FINAL anchor.
                    if previous['timestamps'][1] == record['timestamps'][0] and previous_hold is not None:
                        schedule(prior_id,previous,previous_hold,'final',depth+1,state)
            for number, record in sorted(primary.items()):
                for before in (True, False):
                    adjacent = neighbour_once(number, record, before)
                    if adjacent is not None and adjacent[0] not in primary:
                        auxiliary[adjacent[0]] = adjacent[1]
            # Scalar transfer labels identify candidates; they are never a
            # substitute for the observed route consumed by departureBoundary
            # and the rigid rear reconstruction. Retain each required journey's
            # recorded prefix once, without assigning HOLD anchors to auxiliary
            # intervals. The original row/byte guards apply to every real read.
            # This also covers several consecutive short domains, not just the
            # immediate previous interval of a long vehicle on a 2 m link.
            journeys={}
            for number,record in primary.items():
                journey=record['Replay_Journey_Key']
                journeys[journey]=max(journeys.get(journey,0),number)
            for journey,last in sorted(journeys.items()):
                for row in self.query('SELECT id,vehicle,start,end,payload FROM segments INDEXED BY segments_journey '
                        'WHERE journey=? AND id<=? ORDER BY id',(journey,last)):
                    number,vehicle,start,end,raw=row
                    charge(1)
                    if number not in loaded:
                        decoded=self.decode(raw)
                        charge(compressed=len(raw),decoded=len(decoded))
                        loaded[number]=self.validate_segment(decoded,journey,vehicle,start,end)
                    if number not in primary:auxiliary[number]=loaded[number]
            all_records = {**auxiliary, **primary}
            for number, record in sorted(all_records.items()):
                journey = record['Replay_Journey_Key']
                if journey not in trips:
                    value = self.trip(journey)
                    cost = value['costs']
                    charge(cost['logical_rows'], cost['compressed_bytes'], cost['decoded_bytes'])
                    trips[journey] = value['trip']
                at_times = [(record['timestamps'][0], True), (record['timestamps'][1], False)]
                if hold_time(record) is not None:
                    at_times.append((hold_time(record), True))
                for epoch, inclusive in at_times:
                    key = (record['vehicle'], epoch, inclusive)
                    if key in lane_visited:
                        continue
                    lane_visited.add(key)
                    value = self.lane(*key)
                    cost = value['costs']
                    charge(cost['logical_rows'], cost['compressed_bytes'], cost['decoded_bytes'])
                    if value['event'] is not None:
                        seq, event = value['event']
                        events[seq] = event
            holds = {key: row for key, row in primary.items() if valid_hold(row) is not None}
            transitions = {**auxiliary, **{key: row for key, row in primary.items() if key not in holds}}
            counts['hold_records'], counts['moving_records'] = len(holds), len(primary)-len(holds)
            phase_keys={interval_key(row):('final' if any(node[0]==key and node[2]=='final' for node in visited) else 'base')
                        for key,row in holds.items()}
            return dict(complete=True, reason=None, metrics=counts, missing_topology_links=sorted(missing),
                        record_keys=[interval_key(row) for _, row in sorted(holds.items())],
                        segments=list(holds.values()), transition_segments=list(transitions.values()), trips=trips,
                        lane_events=[[seq, row] for seq, row in sorted(events.items(), key=lambda item: (item[1]['time'], item[0]))],
                        support_certificate=dict(policy='native-causal-epochs-v1', index_sha256=source.receipt['sha256'],
                            source_contract=source.receipt['contract'], complete=True, poses_certified=False,
                            phase_keys=phase_keys,
                            states=len(visited), edges=len(edges), components=dependency_components(visited,edges),
                            absence_proofs=absence_proofs,
                            facility_support_sha256=(hashlib.sha256(encoded(self.facility_support)).hexdigest() if self.facility_support is not None else None),
                            graph_sha256=hashlib.sha256(encoded(dict(edges=sorted(edges),absence_proofs=absence_proofs))).hexdigest()))
        except Incomplete as error:
            return dict(complete=False, reason=str(error), metrics=counts, missing_topology_links=sorted(missing),
                        record_keys=[], segments=[], transition_segments=[], trips={}, lane_events=[])

    def hydrate_seed(self, compact):
        result={key:value for key,value in compact.items() if key!='_refs'}
        refs=compact['_refs']
        if refs is None:
            return dict(result,segments=[],transition_segments=[],trips={},lane_events=[])
        records={}
        for ident in dict.fromkeys(refs['segments']+refs['transitions']):
            checkpoint('queue_context_cached')
            records[ident]=self.native_record(ident)
        events=[]
        for seq in refs['events']:
            def read_event():
                row=self.query('SELECT time,payload FROM lane_events WHERE seq=?',(seq,)).fetchone()
                if row is None:raise ValueError('Native cached closure lane event is missing')
                at,raw=row;event=json.loads(self.decode(raw))
                if not isinstance(event,dict) or event.get('time')!=at:
                    raise ValueError('Native cached closure lane event time mismatch')
                return event
            events.append([seq,self.cached(('lane_seq',seq),read_event)])
        return dict(result,segments=[records[ident] for ident in refs['segments']],
                    transition_segments=[records[ident] for ident in refs['transitions']],
                    trips={key:self.trip(key)['trip'] for key in refs['trips']},lane_events=events)

    def resolve(self, seeds):
        by_seed, segments, transitions, trips, events = {}, {}, {}, {}, {}
        capsules={};capsule_contract=None
        for ident, record in sorted(seeds, key=lambda pair: pair[0]):
            checkpoint('queue_context', seeds_completed=len(by_seed), seeds_total=len(seeds))
            key = interval_key(record)
            resolved = self.seed(ident, record)
            by_seed[key] = {name: resolved[name] for name in ('complete', 'reason', 'metrics', 'record_keys','missing_topology_links')}
            if 'support_certificate' in resolved:
                by_seed[key]['support_certificate']=resolved['support_certificate']
            if not resolved['complete']:
                continue
            for row in resolved['segments']:
                segments[interval_key(row)] = row
            for row in resolved['transition_segments']:
                # Two instantaneous native observations may share interval
                # identity while carrying different boundary evidence. Preserve
                # both; they are auxiliary barriers and never active poses.
                transitions[(interval_key(row),hashlib.sha256(encoded(row)).hexdigest())] = row
            if resolved.get('checkpoints'):
                if capsule_contract is not None and capsule_contract!=resolved['checkpoint_contract']:
                    raise ValueError('Cannot combine checkpoint libraries from different verified contracts')
                capsule_contract=resolved['checkpoint_contract']
                from simz1_queue_checkpoints import CausalGraph
                for capsule_key,capsule in resolved['checkpoints'].items():
                    capsules[capsule_key]=CausalGraph._merge_capsule(capsules.get(capsule_key),capsule)
            trips.update(resolved['trips'])
            events.update(resolved['lane_events'])
        result=dict(schema_version=1, policy=POLICY, dependency_policy='native-causal-epochs-v1' if self.support_index is not None else DEPENDENCY_POLICY, limits=asdict(self.limits), by_seed=by_seed,
                    domain_scope='effective_geometry_node_corridor_same_level' if self.domains is not None else 'unknown_global_conservative',
                    segments=list(segments.values()), transition_segments=list(transitions.values()), trips=trips,
                    lane_events=[row for _, row in sorted(events.items(), key=lambda item: (item[1]['time'], item[0]))],
                    metrics=self.metrics)
        if capsules:result.update(checkpoints=capsules,checkpoint_contract=capsule_contract)
        return result


def dependency_components(nodes, edges):
    """Exact SCC partition; reciprocal roles keep every edge and every member."""
    forward={node:[] for node in nodes};reverse={node:[] for node in nodes}
    for left,right in edges:
        forward.setdefault(left,[]).append(right);reverse.setdefault(right,[]).append(left)
        forward.setdefault(right,[]);reverse.setdefault(left,[])
    seen=set();order=[]
    for root in sorted(forward):
        if root in seen:continue
        stack=[(root,False)]
        while stack:
            node,done=stack.pop()
            if done:order.append(node);continue
            if node in seen:continue
            seen.add(node);stack.append((node,True))
            stack.extend((other,False) for other in forward[node] if other not in seen)
    seen=set();components=[]
    for root in reversed(order):
        if root in seen:continue
        component=[];stack=[root];seen.add(root)
        while stack:
            node=stack.pop();component.append(node)
            for other in reverse[node]:
                if other not in seen:seen.add(other);stack.append(other)
        components.append(sorted(component))
    cyclic=[component for component in components if len(component)>1 or (component[0],component[0]) in edges]
    return dict(count=len(components),cyclic=cyclic,maximum_size=max(map(len,components),default=0),
                partition_sha256=hashlib.sha256(encoded(sorted(components))).hexdigest())
