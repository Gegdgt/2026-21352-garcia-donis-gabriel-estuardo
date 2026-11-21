"""Validate the native corridor ledger, never infer microscopic coordinates.

Java defines the occupancy domains. This reader checks that their published
topology, metric capacities and atomic reservation receipts agree with the
loaded inputs and native traffic events. It does not recreate the grouping
algorithm or turn PCU into metres.
"""
from collections import Counter
import gzip
import math
import xml.etree.ElementTree as ET

POLICY = 'corridor-length-v1'
SOURCE = 'synchronous_QSim_corridor_ledger'
RECEIPT_ROUTE_POLICY = 'planned_contiguous_prefix_v1'
STOPPING_RECEIPT_ROUTE_POLICY = 'planned_stopping_prefix_v2'
SIGNAL_WINDOW_POLICY = 'fixed_plan_empty_native_queue_bound_v1'
MINIMUM_GAP = .10
EPSILON = 1e-6


def _require(condition, message):
    if not condition:
        raise ValueError('CORRIDOR_OCCUPANCY: '+message)


def _number(event, name, *, positive=False, nonnegative=False):
    try:
        value = float(event[name])
    except (KeyError, TypeError, ValueError):
        raise ValueError('CORRIDOR_OCCUPANCY: missing/non-numeric '+name) from None
    _require(math.isfinite(value) and (not positive or value > 0) and
             (not nonnegative or value >= 0), 'invalid '+name)
    return value


def _integer(event, name, *, minimum=0):
    try:
        text = str(event[name]); value = int(text)
    except (KeyError, TypeError, ValueError):
        raise ValueError('CORRIDOR_OCCUPANCY: missing/non-integer '+name) from None
    _require(str(value) == text and value >= minimum, 'invalid '+name)
    return value


def _same(a, b):
    return abs(a-b) <= EPSILON


def _stopping_geometry(network, all_links, nodes):
    """Independent projection of native incident widths onto each exit axis.

    Legacy input fixtures without coordinates remain readable. V2 receipts
    require the derived value and cannot substitute a published claim for it.
    """
    incident = {}
    for ident, link in all_links.items():
        for node in (link['from_node'], link['to_node']):
            incident.setdefault(node, []).append(ident)

    def direction(link):
        a, b = nodes.get(link['from_node']), nodes.get(link['to_node'])
        if a is None or b is None: return None
        x, y = b[0]-a[0], b[1]-a[1]
        length = math.hypot(x, y)
        return (x/length, y/length) if math.isfinite(length) and length > 0 else None

    for ident, link in network.items():
        u = direction(link)
        if u is None: continue
        margin = 0.; complete = True
        neighbours = incident[link['to_node']]
        for other_id in neighbours:
            if other_id == ident or other_id not in network: continue
            other = all_links[other_id]; v = direction(other)
            if v is None:
                complete = False; break
            cross = abs(u[0]*v[1]-u[1]*v[0])
            if cross < .25: continue
            # Java includes every inverse incident link in the width sum,
            # even when that inverse itself is not a road vehicle link.
            lanes = other['lanes'] + sum(all_links[r]['lanes'] for r in neighbours
                if all_links[r]['from_node'] == other['to_node'] and
                   all_links[r]['to_node'] == other['from_node'])
            margin = max(margin, .5*3.*lanes/cross)
        if complete: link['stop_setback_m'] = 2.+margin


def load_inputs(network_path, vehicle_paths):
    """Read physical dimensions from already verified artifacts, not current defaults."""
    opener = gzip.open if str(network_path).endswith('.gz') else open
    network = {}; nodes = {}; all_links = {}
    with opener(network_path, 'rb') as stream:
        for _, element in ET.iterparse(stream, events=('end',)):
            kind = element.tag.rsplit('}', 1)[-1]
            if kind == 'node':
                nodes[element.get('id')] = (float(element.get('x')), float(element.get('y')))
                element.clear()
            if kind != 'link':
                continue
            all_links[element.get('id')] = dict(from_node=element.get('from'), to_node=element.get('to'),
                                                lanes=float(element.get('permlanes', '1')))
            modes = frozenset(element.get('modes', 'car').split(','))
            if modes & {'car', 'bus'}:
                ident = element.get('id')
                _require(ident and ident not in network, 'duplicate/empty network link')
                lanes = _number(element.attrib, 'permlanes', positive=True)
                _require(lanes == int(lanes), 'native occupancy requires integer represented road lanes')
                network[ident] = dict(from_node=element.get('from'), to_node=element.get('to'),
                                      length_m=float(element.get('length')), modes=modes, represented_lanes=int(lanes))
            element.clear()
    _stopping_geometry(network, all_links, nodes)
    from simz1_motion import read_vehicle_definitions
    vehicles = {}
    for path in vehicle_paths:
        types, assignments = read_vehicle_definitions(path)
        for ident, kind in assignments.items():
            dimensions = types[kind].get('physical_dimensions')
            _require(dimensions is not None, 'native vehicle dimensions missing: '+ident)
            value = dict(length_m=dimensions['length_m'], width_m=dimensions['width_m'],
                         pcu=types[kind]['pcu'], vehicle_type=kind)
            _require(ident not in vehicles or vehicles[ident] == value,
                     'colliding native vehicle definition: '+ident)
            vehicles[ident] = value
    return network, vehicles


def report_summary(record):
    """Keep aggregate evidence in reports; full geometry stays in run-manifest."""
    if record is None:
        return None
    result = {key: value for key, value in record.items() if key != 'geometry'}
    if record.get('enabled'):
        geometry = record['geometry']
        result.update(corridor_domains=len(geometry['corridors']), domain_links=len(geometry['links']),
                      geometry_reference='run-manifest.json/results/<iteration>/corridor_occupancy/geometry')
    return result


class CorridorOccupancyAudit:
    def __init__(self, *, enabled=False, network=None, vehicles=None, expected_receipt_route_coverage_policy=None):
        self.enabled = enabled
        _require(expected_receipt_route_coverage_policy in (None,RECEIPT_ROUTE_POLICY,STOPPING_RECEIPT_ROUTE_POLICY),
                 'unknown requested receipt route coverage policy')
        self.expected_receipt_route_coverage_policy=expected_receipt_route_coverage_policy
        self.network = network or {}
        self.vehicles = vehicles or {}
        self.corridors, self.links = {}, {}
        self.active, self.used, self.slot_used = {}, {}, {}
        self.slot_order = {}; self.progress_sources = set()
        self.receipt_route_policies = set()
        self.signal_window_policies = set()
        self.counts = Counter()
        self.observed_vehicles = set()
        self.last_ordinal = 0
        self.peak_active = 0
        self.peak_locked_nodes = 0
        self.current_time = None
        self.step_coverage, self.step_exits = set(), set()
        self.pending_entries, self.pending_exits = [], []
        self.passages, self.node_locks, self.pending_passages = {}, {}, {}
        self.step_exit_ordinals, self.pending_passage_releases = set(), []
        self.domains_checked = False

    def _flush_time(self):
        for vehicle, link in self.pending_entries:
            _require((vehicle, link) in self.step_coverage,
                     'native traffic entry without a corridor reservation: '+vehicle)
        for vehicle in self.pending_exits:
            _require(vehicle in self.step_exits, 'native traffic exit without releasing reservation: '+vehicle)
        _require(not self.pending_passages, 'connector entry without acquiring passage locks at same timestamp')
        for key, bound, threshold, minimum_time, released_at, reason in self.pending_passage_releases:
            current = self.active.get(key[0])
            if current is not None and current['ordinal'] == key[1]:
                bound = max(bound, current['front_bound'])
            if reason == 'reservation_exit':
                _require(key in self.step_exit_ordinals, 'passage exit release lacks same-time reservation EXIT')
            else:
                _require(released_at+EPSILON >= minimum_time and bound+EPSILON >= threshold,
                         'passage locks released before modeled body cleared the receiving node or minimum time')
        self.pending_entries.clear(); self.pending_exits.clear()
        self.step_coverage.clear(); self.step_exits.clear()
        self.step_exit_ordinals.clear(); self.pending_passage_releases.clear()

    def _at(self, event):
        time = _number(event, 'time')
        if self.current_time is not None:
            _require(time >= self.current_time, 'non-monotone native ledger time')
        if time != self.current_time:
            self._flush_time(); self.current_time = time

    def _domain(self, event):
        _require(not self.domains_checked and not self.counts['ENTER'], 'domain published after reservations began')
        _require(event.get('policy') == POLICY and event.get('positionsObserved') == 'false',
                 'domain policy or position provenance mismatch')
        route_policy=event.get('receiptRouteCoveragePolicy')
        _require(route_policy in (None,RECEIPT_ROUTE_POLICY,STOPPING_RECEIPT_ROUTE_POLICY), 'unknown receipt route coverage policy')
        _require(self.expected_receipt_route_coverage_policy is None or
                 route_policy==self.expected_receipt_route_coverage_policy,
                 'native emitter omitted requested receipt route coverage policy')
        self.receipt_route_policies.add(route_policy)
        _require(len(self.receipt_route_policies)==1, 'inconsistent receipt route coverage policy across native domains')
        corridor, link = event.get('corridor'), event.get('link')
        _require(corridor and link and link in self.network and link not in self.links,
                 'unknown/duplicate domain link')
        ordered = event.get('links', '').split(',')
        _require(ordered and ordered[0] == corridor and link in ordered and
                 len(ordered) == len(set(ordered)) and all(k in self.network for k in ordered),
                 'invalid corridor membership')
        length = _number(event, 'corridorLengthMeters', positive=True)
        lanes = _integer(event, 'representedLanes', minimum=1)
        _require(lanes == self.network[link]['represented_lanes'], 'domain lanes differ from loaded network')
        gap = _number(event, 'minimumGapMeters', positive=True)
        setback = _number(event, 'endSetbackMeters', nonnegative=True)
        if route_policy == STOPPING_RECEIPT_ROUTE_POLICY:
            expected = self.network.get(ordered[-1], {}).get('stop_setback_m')
            _require(expected is not None and _same(setback, expected),
                     'domain stopping setback differs from loaded geometry')
        lane_capacity = _number(event, 'laneCapacityMeters', nonnegative=True)
        capacity = _number(event, 'capacityMeters', nonnegative=True)
        _require(gap == MINIMUM_GAP, 'minimum gap differs from 0.10 m')
        _require(_same(lane_capacity, max(0, length-setback)) and _same(capacity, lane_capacity*lanes),
                 'domain capacity differs from geometry')
        description = dict(link_ids=ordered, length_m=length, represented_lanes=lanes,
                           minimum_gap_m=gap, end_setback_m=setback,
                           lane_capacity_m=lane_capacity, capacity_m=capacity)
        _require(corridor not in self.corridors or self.corridors[corridor] == description,
                 'inconsistent repeated corridor description')
        self.corridors[corridor] = description
        self.used.setdefault(corridor, 0.)
        self.slot_used.setdefault(corridor, [0.]*lanes)
        self.slot_order.setdefault(corridor, [[] for _ in range(lanes)])
        offset = _number(event, 'linkOffsetMeters', nonnegative=True)
        link_length = _number(event, 'linkLengthMeters', positive=True)
        _require(_same(link_length, self.network[link]['length_m']), 'domain changed loaded link length')
        self.links[link] = dict(corridor_id=corridor, offset_m=offset, length_m=link_length)
        self.counts['domain_link_events'] += 1

    def _check_domains(self):
        if self.domains_checked:
            return
        _require(set(self.links) == set(self.network) and bool(self.links), 'incomplete native occupancy domain coverage')
        for ident, description in self.corridors.items():
            offset = 0.; previous = None
            for link in description['link_ids']:
                mapping = self.links[link]
                _require(mapping['corridor_id'] == ident and _same(mapping['offset_m'], offset),
                         'non-contiguous corridor offsets/membership')
                if previous is not None:
                    _require(self.network[previous]['to_node'] == self.network[link]['from_node'],
                             'disconnected corridor links')
                offset += mapping['length_m']; previous = link
            _require(_same(offset, description['length_m']), 'corridor length differs from its links')
        self.domains_checked = True

    def _passage_metadata(self, event, corridor):
        _require(event.get('passageKind') in (None, 'downstream_receipt', 'boundary_exit'), 'unsupported passage kind')
        exit_kind = event.get('passageKind') == 'boundary_exit'
        text = event.get('exitLinks' if exit_kind else 'passageLinks', '')
        if not text:
            _require(not event.get('passageSlots') and not event.get('exitLinks') and not event.get('exitSlots') and
                     event.get('passageKind') is None,
                     'passage slots/kind without connector links')
            return None
        links = text.split(','); raw_slots = event.get('exitSlots' if exit_kind else 'passageSlots', '').split(',')
        _require(len(links) == len(raw_slots) and len(links) == len(set(links)) and
                 all(link in self.links and self.links[link]['corridor_id'] != corridor for link in links),
                 'unknown/duplicate/incompatible passage connectors')
        slots = [_integer(dict(slot=value), 'slot') for value in raw_slots]
        _require(all(slot < self.corridors[self.links[link]['corridor_id']]['represented_lanes']
                     for link, slot in zip(links, slots)), 'passage connector slot outside loaded domain')
        receipt = None if exit_kind else event.get('receiptLink')
        exit_from = event.get('exitFromLink') if exit_kind else None
        if exit_kind:
            _require(not event.get('passageLinks') and not event.get('receiptLink') and exit_from in self.links and
                     self.links[exit_from]['corridor_id'] == corridor, 'invalid boundary exit origin')
            chain = [exit_from]+links
        else:
            _require(receipt in self.links and self.links[receipt]['corridor_id'] == corridor,
                     'passage receipt outside receiving corridor')
            chain = links+[receipt]
        _require(all(self.network[first]['to_node'] == self.network[second]['from_node']
                     for first, second in zip(chain, chain[1:])), 'disconnected passage connector chain')
        # A route may return through a node on distinct links (e.g. an activity
        # U-turn). Java retains one exclusive lock until the whole body clears;
        # its LinkedHashSet publishes the order of first visit, not duplicates.
        nodes = list(dict.fromkeys(self.network[link]['from_node'] for link in (links if exit_kind else chain)))
        return dict(links=links, slots=slots, receipt=receipt, nodes=nodes,
                    kind='boundary_exit' if exit_kind else 'downstream_receipt', exit_from=exit_from)

    def _initial_front_bound(self, link, passage):
        if passage is not None and link in passage['links']:
            if passage['kind'] == 'boundary_exit':
                origin = self.links[passage['exit_from']]
                preceding = passage['links'][:passage['links'].index(link)]
                return origin['offset_m']+origin['length_m']+sum(self.links[item]['length_m'] for item in preceding)
            remaining = passage['links'][passage['links'].index(link):]
            return self.links[passage['receipt']]['offset_m']-sum(self.links[item]['length_m'] for item in remaining)
        # Java has not observed a buffer arrival yet. An activity may start in
        # an internal subdivision; do not claim it has reached that offset.
        return 0.

    def _reservation(self, event):
        self._check_domains()
        _require(event.get('policy') == POLICY and event.get('source') == SOURCE and event.get('laneObserved') == 'false',
                 'reservation policy/source/lane provenance mismatch')
        action, vehicle = event.get('action'), event.get('vehicle')
        _require(action in ('ENTER', 'TRANSFER', 'EXIT', 'WAIT') and vehicle in self.vehicles,
                 'unknown action or unregistered vehicle')
        corridor, link = event.get('corridor'), event.get('link')
        _require(corridor in self.corridors and link in self.links,
                 'reservation link/corridor mismatch')
        passage = self._passage_metadata(event, corridor)
        # activity() may reject a downstream candidate before enter(): its
        # requested link and candidate corridor are prospective, not an occupied
        # position. Older emitters did not serialize that rejected passage.
        # This exception supplies neither an active reservation nor traffic
        # coverage; all null identity/body/load checks still apply below.
        prospective_activity_wait = (action == 'WAIT' and
            event.get('reason') == 'activity_requires_empty_model_slot' and passage is None)
        if prospective_activity_wait:
            _require(vehicle not in self.active and _integer(event,'previousModelSlot',minimum=-1)==-1,
                     'prospective activity WAIT changed a live reservation')
        _require(prospective_activity_wait or self.links[link]['corridor_id'] == corridor or
                 passage is not None and link in passage['links'],
                 'reservation outside domain without explicit connected passage')
        description = self.corridors[corridor]
        body = _number(event, 'bodyLengthMeters', positive=True)
        footprint = _number(event, 'footprintMeters', positive=True)
        _require(_same(body, self.vehicles[vehicle]['length_m']), 'reservation body differs from loaded VehicleType')
        _require(_same(footprint, body+MINIMUM_GAP), 'reservation must use body length plus 0.10 m, not PCU')
        _require(_number(event, 'minimumGapMeters', positive=True) == MINIMUM_GAP,
                 'reservation minimum gap differs from 0.10 m')
        slot = _integer(event, 'modelSlot', minimum=-1)
        ordinal = _integer(event, 'reservationOrdinal')
        _require(_same(_number(event, 'capacityMeters', nonnegative=True), description['capacity_m']) and
                 _same(_number(event, 'laneCapacityMeters', nonnegative=True), description['lane_capacity_m']),
                 'reservation capacity differs from domain')
        if action == 'WAIT':
            _require(slot == -1 and ordinal == 0, 'WAIT fabricated a reservation identity/slot')
        else:
            _require(0 <= slot < description['represented_lanes'] and ordinal > 0, 'invalid reservation slot/ordinal')
            if action == 'ENTER':
                _require(vehicle not in self.active, 'duplicate vehicle reservation')
                _require(ordinal > self.last_ordinal, 'reservation ordinal is not globally increasing')
                if passage is not None:
                    _require(passage['kind'] != 'boundary_exit', 'boundary exit cannot fabricate a new receiver reservation')
                    _require(link == passage['links'][0], 'passage must reserve before its first connector')
                    self.pending_passages[(vehicle, ordinal)] = passage
                self.last_ordinal = ordinal
                self.active[vehicle] = dict(corridor=corridor, link=link, slot=slot, ordinal=ordinal,
                                           footprint=footprint, body=body, front_bound=self._initial_front_bound(link, passage),
                                           passage=passage, progress_initialized=False, native_front_bound=None)
                self.used[corridor] += footprint; self.slot_used[corridor][slot] += footprint
                self.slot_order[corridor][slot].append(vehicle)
                self.observed_vehicles.add(vehicle)
            else:
                current = self.active.get(vehicle)
                _require(current is not None and current['corridor'] == corridor and current['ordinal'] == ordinal and
                         _same(current['footprint'], footprint) and _same(current['body'], body),
                         'transfer/release without matching live reservation')
                if passage != current['passage']:
                    key = (vehicle, ordinal)
                    _require(action == 'TRANSFER' and passage is not None and passage['kind'] == 'boundary_exit' and
                             passage['exit_from'] == current['link'] and link == passage['links'][0] and
                             key not in self.passages and key not in self.pending_passages,
                             'reservation changed connector passage metadata without completed old passage and boundary exit')
                    current['passage'] = passage; current['front_bound'] = self._initial_front_bound(link, passage)
                    self.pending_passages[key] = passage
                if action == 'TRANSFER':
                    previous = _integer(event, 'previousModelSlot')
                    _require(previous == current['slot'], 'TRANSFER changed the wrong source slot')
                    _require(slot == previous, 'TRANSFER changed the stable model slot inside corridor')
                    current['slot'] = slot; current['link'] = link
                else:
                    _require(slot == current['slot'], 'EXIT changed the reserved slot')
                    _require(link == current['link'], 'EXIT changed the last reserved link')
                    _require(event.get('reason') in ('arrival', 'node_transfer', 'abort', 'clear'), 'unknown release reason')
                    self.used[corridor] -= footprint; self.slot_used[corridor][slot] -= footprint
                    self.slot_order[corridor][slot].remove(vehicle)
                    del self.active[vehicle]; self.step_exits.add(vehicle)
                    self.step_exit_ordinals.add((vehicle, ordinal))
            if action in ('ENTER', 'TRANSFER'):
                self.step_coverage.add((vehicle, link))
        _require(_same(_number(event, 'usedMeters', nonnegative=True), max(0., self.used[corridor])),
                 'reported corridor load differs from ledger')
        actual_slot_load = 0. if action == 'WAIT' else max(0., self.slot_used[corridor][slot])
        _require(_same(_number(event, 'slotUsedMeters', nonnegative=True), actual_slot_load),
                 'reported slot load differs from ledger')
        _require(-EPSILON <= self.used[corridor] <= description['capacity_m']+EPSILON and
                 all(-EPSILON <= load <= description['lane_capacity_m']+EPSILON for load in self.slot_used[corridor]),
                 'corridor/slot capacity exceeded')
        self.peak_active = max(self.peak_active, len(self.active))
        if prospective_activity_wait and self.links[link]['corridor_id'] != corridor:
            self.counts['prospective_activity_waits_without_passage_metadata'] += 1
        self.counts[action] += 1

    def _progress(self, event):
        source = event.get('source')
        _require(event.get('policy') == POLICY and event.get('positionsObserved') == 'false' and
                 source in ('native_buffer_arrival_and_reservation_order', 'native_queue_endpoint_and_leader_reservation_order'),
                 'progress policy/source/position provenance mismatch')
        current = self.active.get(event.get('vehicle'))
        _require(current is not None and current['corridor'] == event.get('corridor') and
                 current['link'] == event.get('link') and bool(event.get('nativeQueue')),
                 'progress without matching active reservation/link/queue')
        bound = _number(event, 'modeledFrontLowerBoundMeters')
        new_model = source == 'native_queue_endpoint_and_leader_reservation_order'
        if new_model:
            reason = event.get('reason')
            _require(reason in ('queue_entry', 'buffer_arrival', 'leader_release', 'native_earliest_exit_reached', 'leader_progress'),
                     'unknown queue progress reason')
            if reason == 'native_earliest_exit_reached':
                _require(_number(event, 'nativeEarliestLinkExitTime') <= self.current_time+EPSILON,
                         'queue progress precedes native earliest exit time')
                self.counts['native_earliest_exit_checks'] += 1
            if reason == 'leader_progress':
                trigger = self.active.get(event.get('triggerVehicle'))
                _require(trigger is not None and trigger['corridor'] == current['corridor'] and
                         trigger['slot'] == current['slot'] and (trigger['ordinal'] < current['ordinal'] or
                         current['progress_initialized'] and _same(bound,current['front_bound'])),
                         'leader progress changed without a preceding active trigger')
            native_bound = _number(event, 'nativeFrontBoundMeters')
            _require(current['native_front_bound'] is None or native_bound+EPSILON >= current['native_front_bound'],
                     'native queue endpoint regressed')
            order = self.slot_order[current['corridor']][current['slot']]
            index = order.index(event['vehicle']); leader_id = order[index-1] if index else None
            _require((event.get('leaderVehicle') or None) == leader_id, 'progress does not identify immediate reserved leader')
            expected = native_bound
            if leader_id:
                leader = self.active[leader_id]
                _require(leader['progress_initialized'] and
                         _same(_number(event, 'leaderFrontLowerBoundMeters'), leader['front_bound']) and
                         _same(_number(event, 'leaderFootprintMeters', positive=True), leader['footprint']),
                         'progress leader geometry differs from published reservation state')
                expected = min(native_bound, leader['front_bound']-leader['footprint'])
            _require(_same(bound, expected), 'progress differs from native endpoint and leader footprint bound')
            current['native_front_bound'] = native_bound
        upper = self.corridors[current['corridor']]['length_m']
        passage = current.get('passage')
        if passage is not None and passage['kind'] == 'boundary_exit':
            upper = self._initial_front_bound(passage['links'][-1], passage)+self.links[passage['links'][-1]]['length_m']
        if new_model:
            native_upper = upper if passage is not None and passage['kind'] == 'boundary_exit' else self.corridors[current['corridor']]['lane_capacity_m']
            _require(native_bound <= native_upper+EPSILON, 'native queue progress exceeds the modeled conflict setback')
        _require((new_model and not current['progress_initialized'] or current['front_bound']-EPSILON <= bound) and bound <= upper+EPSILON,
                 'non-monotone/out-of-domain modeled progress bound')
        current['front_bound'] = bound; current['progress_initialized'] = True
        self.progress_sources.add(source)
        self.counts['modeled_progress_events'] += 1

    def _passage(self, event):
        _require(event.get('policy') == POLICY and event.get('positionsObserved') == 'false' and
                 event.get('laneObserved') == 'false' and event.get('source') == SOURCE,
                 'passage policy/source/position provenance mismatch')
        vehicle, corridor = event.get('vehicle'), event.get('corridor')
        ordinal = _integer(event, 'reservationOrdinal', minimum=1)
        _require(corridor in self.corridors and vehicle in self.vehicles, 'unknown passage corridor/vehicle')
        metadata = self._passage_metadata(event, corridor)
        _require(metadata is not None and event.get('lockedNodes', '').split(',') == metadata['nodes'],
                 'passage locks do not cover exact connector nodes')
        key = (vehicle, ordinal); action = event.get('action')
        current = self.active.get(vehicle)
        minimum_time = _number(event, 'minimumReleaseTime')
        threshold = _number(event, 'clearanceFrontMeters', positive=True)
        route_coverage=None
        route_policy=next(iter(self.receipt_route_policies),None)
        _require(event.get('receiptRouteCoveragePolicy')==route_policy,
                 'passage receipt route coverage policy differs from domains')
        signal_proof=None
        signal_policy=event.get('passageSignalWindowPolicy')
        signal_fields=('passageSignalLinks','passageSignalGreenSeconds','passageSignalTraversalSeconds')
        if route_policy in (RECEIPT_ROUTE_POLICY,STOPPING_RECEIPT_ROUTE_POLICY) or signal_policy is not None:
            _require(signal_policy==SIGNAL_WINDOW_POLICY and all(key in event for key in signal_fields),
                     'missing/unknown passage signal window proof')
            raw=[event[key].split(',') if event[key] else [] for key in signal_fields]
            signal_links,greens,travel=raw
            connectors=metadata['links'][:-1] if metadata['kind']=='boundary_exit' else metadata['links']
            _require(len(signal_links)==len(greens)==len(travel) and len(signal_links)==len(set(signal_links)) and
                     all(link in connectors for link in signal_links) and
                     signal_links==[link for link in connectors if link in signal_links],
                     'signal window links are not ordered connector movements')
            bounds=[]
            for green,duration in zip(greens,travel):
                available=_number(dict(value=green),'value',nonnegative=True)
                required=_number(dict(value=duration),'value',nonnegative=True)
                _require(available>required, 'passage signal window cannot clear the modeled traversal bound')
                bounds.append((available,required))
            signal_proof=(tuple(signal_links),tuple(bounds))
            self.signal_window_policies.add(signal_policy)
        else:
            _require(not any(event.get(key) for key in signal_fields), 'signal window values without a policy')
        if metadata['kind'] != 'boundary_exit':
            _require(threshold+EPSILON >= self.links[metadata['receipt']]['offset_m']+self.vehicles[vehicle]['length_m']+MINIMUM_GAP,
                     'passage clearance threshold omits receiver offset, body or gap')
            if route_policy in (RECEIPT_ROUTE_POLICY,STOPPING_RECEIPT_ROUTE_POLICY):
                path=event.get('receiptPathLinks','').split(',')
                ordered=self.corridors[corridor]['link_ids']; start=ordered.index(metadata['receipt'])
                _require(path and path==ordered[start:start+len(path)],
                         'receipt route is not a contiguous native domain prefix from receiptLink')
                reachable=_number(event,'receiptReachableFrontMeters',positive=True)
                last=self.links[path[-1]]
                expected=min(self.corridors[corridor]['lane_capacity_m'],last['offset_m']+last['length_m'])
                following = None; setback = None
                if route_policy == STOPPING_RECEIPT_ROUTE_POLICY:
                    _require('receiptFollowingLink' in event, 'missing receipt following link evidence')
                    following = event['receiptFollowingLink']
                    if following:
                        _require(following in self.network and following not in ordered and
                                 self.network[following]['from_node'] == self.network[path[-1]]['to_node'],
                                 'receipt following link is not a connected exit from its domain')
                        derived = self.network[path[-1]].get('stop_setback_m')
                        _require(derived is not None, 'missing loaded stopping geometry for receipt exit')
                    else:
                        derived = 0.  # native final activity, no subsequent junction stop
                    setback = _number(event,'receiptStoppingSetbackMeters',nonnegative=True)
                    _require(_same(setback,derived), 'receipt stopping setback differs from loaded geometry')
                    expected=min(self.corridors[corridor]['lane_capacity_m'],last['offset_m']+last['length_m']-setback)
                _require(_same(reachable,expected) and reachable+EPSILON>=threshold,
                         'receipt route leaves domain before body can clear the conflict area')
                route_coverage=(tuple(path),reachable,following,setback)
        if action == 'ACQUIRE':
            _require(current is not None and current['corridor'] == corridor and current['ordinal'] == ordinal and
                     self.pending_passages.get(key) == metadata and key not in self.passages,
                     'passage acquisition without matching new reservation')
            _require(all(node not in self.node_locks for node in metadata['nodes']), 'passage node locked by multiple bodies')
            expected_reason = 'authorized_native_traffic_exit' if metadata['kind'] == 'boundary_exit' else 'authorized_downstream_receipt'
            _require(event.get('reason') == expected_reason and minimum_time >= self.current_time,
                     'invalid passage acquisition reason/minimum release time')
            if signal_proof is not None:
                self.counts['passage_signal_window_proofs_checked']+=1
                self.counts['signal_window_bounds_checked']+=len(signal_proof[0])
            if metadata['kind'] != 'boundary_exit':
                _require(route_policy is None or event.get('admissionBasis')=='modeled_free_entry_interval',
                         'route-aware receipt lacks free entry interval evidence')
                if route_coverage is not None:self.counts['receipt_route_coverage_checked']+=1
                if event.get('admissionBasis') is not None:
                    _require(event['admissionBasis'] == 'modeled_free_entry_interval', 'unknown receipt interval admission basis')
                    free = _number(event, 'receiptFreeFrontMeters')
                    prior = [self.active[other] for other in self.slot_order[corridor][current['slot']] if other != vehicle]
                    # Match Java freeFront: an exiting body's projected rear
                    # can pass the origin boundary while its reservation is
                    # still held. It cannot extend that corridor's capacity.
                    actual_free = min([self.corridors[corridor]['lane_capacity_m']] +
                                      [leader['front_bound']-leader['footprint'] for leader in prior])
                    _require(_same(free, actual_free) and free+EPSILON >= threshold,
                             'passage admitted without enough published free entry interval')
                    self.counts['receipt_free_intervals_checked'] += 1
                else:
                    self.counts['legacy_receipt_acquisitions_without_interval'] += 1
            for node in metadata['nodes']: self.node_locks[node] = key
            self.peak_locked_nodes = max(self.peak_locked_nodes, len(self.node_locks))
            self.passages[key] = dict(metadata=metadata, corridor=corridor, bound=current['front_bound'],
                                      threshold=threshold, minimum_time=minimum_time,route_coverage=route_coverage,
                                      signal_proof=signal_proof)
            del self.pending_passages[key]
        elif action == 'RELEASE':
            held = self.passages.get(key)
            _require(held is not None and held['metadata'] == metadata and held['corridor'] == corridor and
                     all(self.node_locks.get(node) == key for node in metadata['nodes']),
                     'passage release without matching exclusive locks')
            _require(_same(minimum_time, held['minimum_time']) and _same(threshold, held['threshold']) and
                     event.get('reason') in ('body_clearance', 'reservation_exit'),
                     'passage release changed threshold/time/reason')
            _require(held['route_coverage']==route_coverage, 'passage release changed receipt route coverage')
            _require(held['signal_proof']==signal_proof, 'passage release changed signal window proof')
            _require(metadata['kind'] != 'boundary_exit' or event.get('reason') == 'reservation_exit',
                     'boundary exit must retain locks until native traffic exit')
            bound = current['front_bound'] if current is not None and current['ordinal'] == ordinal else held['bound']
            self.pending_passage_releases.append((key, bound, threshold, minimum_time, self.current_time, event['reason']))
            for node in metadata['nodes']: del self.node_locks[node]
            del self.passages[key]
        else:
            _require(False, 'unknown passage action')
        self.counts['passage_'+action] += 1

    def consume(self, event):
        kind = event.get('type')
        custom = kind in ('simz1OccupancyDomain', 'simz1OccupancyReservation', 'simz1OccupancyProgress', 'simz1OccupancyPassage')
        if not self.enabled:
            _require(not custom, 'native occupancy events present while policy disabled')
            return False
        if not custom and kind not in ('vehicle enters traffic', 'entered link', 'vehicle leaves traffic'):
            return False
        self._at(event)
        if kind == 'simz1OccupancyDomain':
            self._domain(event)
        elif kind == 'simz1OccupancyReservation':
            self._reservation(event)
        elif kind == 'simz1OccupancyProgress':
            self._progress(event)
        elif kind == 'simz1OccupancyPassage':
            self._passage(event)
        else:
            vehicle = event.get('vehicle') or event.get('vehicleId')
            # Native road/pt movement must be tied to a configured body. No
            # prefix-based inference or fabricated unknown dimensions.
            _require(vehicle in self.vehicles, 'native traffic vehicle lacks configured body: '+str(vehicle))
            if kind == 'vehicle leaves traffic':
                self.pending_exits.append(vehicle)
            else:
                self._check_domains()
                link = event.get('link')
                _require(link in self.links, 'native traffic entry outside published domains')
                # MATSim can emit LinkEnter immediately before the synchronous
                # commit. Match the whole timestamp, but demand the exact link;
                # an old reservation in that corridor cannot mask a lost transfer.
                if kind == 'entered link':
                    held = self.node_locks.get(self.network[link]['from_node'])
                    _require(held is None or held[0] == vehicle, 'native entry crosses another body passage lock')
                self.pending_entries.append((vehicle, link))
                self.counts['native_entries_checked'] += 1
        return custom

    def summary(self):
        if not self.enabled:
            return dict(enabled=False, status='not_applicable', policy=None, continuous_positions_observed=False)
        self._flush_time(); self._check_domains()
        _require(not self.active, 'live reservations remained after completed native events')
        _require(not self.passages and not self.node_locks, 'passage locks remained after completed native events')
        _require('native_queue_endpoint_and_leader_reservation_order' not in self.progress_sources or
                 self.counts['legacy_receipt_acquisitions_without_interval'] == 0,
                 'leader-bound policy omitted receipt free-interval evidence')
        _require(self.counts['ENTER'] > 0 and self.counts['native_entries_checked'] > 0,
                 'expected native occupancy service missing')
        return dict(enabled=True, status='verified_native_aggregate_ledger', policy=POLICY,
                    source=SOURCE, continuous_positions_observed=False, lateral_positions_observed=False,
                    body_geometry_source='loaded_VehicleType_dimensions', minimum_gap_m=MINIMUM_GAP,
                    domain_geometry_source='simz1OccupancyDomain_events',
                    progress_scope='modeled lower bound from native queue endpoints, elapsed queue times and leader footprints; not continuous observed coordinates',
                    progress_sources=sorted(self.progress_sources),
                    receipt_route_coverage_policy=next(iter(self.receipt_route_policies),None),
                    passage_signal_window_policies=sorted(self.signal_window_policies),
                    gap_scope='longitudinal reservation footprint, not continuous measured intervehicle distance',
                    counters=dict(self.counts), vehicles_with_reservations=len(self.observed_vehicles),
                    peak_reserved_vehicles=self.peak_active, reservations_remaining=0, violations=0,
                    peak_exclusive_passage_node_locks=self.peak_locked_nodes, passage_locks_remaining=0,
                    geometry=dict(schema=POLICY, corridors=self.corridors, links=self.links,
                                  positions_observed=False, lane_assignment_observed=False,
                                  intersection_setbacks_source='modeled_nominal_crossing_width_not_measured'))
