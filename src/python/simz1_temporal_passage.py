"""Read-only periodic feasibility of the native whole-body passage contract.

No signal edits, resampling, occupancy predictions or Java process per person.
An instance owns one effective configuration (after attach_transit). Cache keys
include the physical parameters, native source lane and occurrence prefix.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
import heapq
import itertools
import json
import math
from pathlib import Path

from simz1_lane_validation import _xml, read_lanes
from simz1_signal_coordination import remaining_green
from simz1_stop_proxy import StopGeometry

COMPATIBLE, IMPOSSIBLE, UNKNOWN = 'COMPATIBLE', 'IMPOSSIBLE', 'UNKNOWN'
POLICY = 'periodic-native-body-passage-v1'
MAX_PERIOD_TICKS = 100_000


class TemporalPassage:
    def __init__(self, config, base_dir):
        if isinstance(config, (str, Path)):
            config = _xml(config)
        self.config, self.base_dir = config, Path(base_dir)
        def param(module, key, default=None):
            row = config.find(f"module[@name='{module}']/param[@name='{key}']")
            return default if row is None else row.get('value')
        self.enabled = param('simz1Admission', 'wholeVehicleReservation', 'false') == 'true'
        from simz1_run import seconds
        self.step = seconds(param('qsim', 'timeStepSize', '1'))
        self.hashes = {}
        def file(module, key):
            value = param(module, key)
            if value in (None, '', 'null'):
                raise ValueError('TEMPORAL_PASSAGE: missing '+module+'.'+key)
            path = (self.base_dir/value).resolve(strict=True)
            self.hashes[module+'.'+key] = hashlib.sha256(path.read_bytes()).hexdigest()
            return path
        network = _xml(file('network', 'inputNetworkFile'))
        self.nodes = {e.get('id'): e for e in network.findall('nodes/node')}
        self.links = {e.get('id'): e for e in network.findall('links/link')
                      if set(e.get('modes', 'car').split(',')) & {'car', 'bus'}}
        self.lanes = read_lanes(file('network', 'laneDefinitionsFile')) if param('qsim', 'useLanes', 'false') == 'true' else {}
        self.geometry = StopGeometry(self.links, self.nodes, self.lanes)
        self.signals, self.plans = defaultdict(list), {}
        if param('signalsystems', 'useSignalsystems', 'false') == 'true':
            control = _xml(file('signalsystems', 'signalcontrol'))
            for system in control.findall('signalSystem'):
                candidates = system.findall('.//signalPlan'); sid = system.get('refId')
                if (len(candidates) != 1 or system.findtext('.//controllerIdentifier') != 'Zona1FixedTime' or
                        any(candidates[0].find(tag) is None or candidates[0].find(tag).get('daytime') != '00:00:00' for tag in ('start', 'stop'))):
                    self.plans[sid] = None
                    continue
                plan = candidates[0]
                self.plans[sid] = dict(cycle=int(plan.find('cycleTime').get('sec')), offset=int(plan.find('offset').get('sec')),
                    groups={g.get('refId'): (int(g.find('onset').get('sec')), int(g.find('dropping').get('sec')))
                            for g in plan.findall('signalGroupSettings')})
            membership = {}
            for system in _xml(file('signalsystems', 'signalgroups')).findall('signalSystem'):
                for group in system.findall('signalGroup'):
                    for signal in group.findall('signal'):
                        membership[system.get('refId'), signal.get('refId')] = group.get('id')
            for system in _xml(file('signalsystems', 'signalsystems')).findall('signalSystem'):
                for signal in system.findall('signals/signal'):
                    sid = system.get('id'); group = membership.get((sid, signal.get('id')))
                    self.signals[signal.get('linkIdRef')].append((sid, group,
                        frozenset(x.get('refId') for x in signal.findall('lane')),
                        frozenset(x.get('refId') for x in signal.findall('turningMoveRestrictions/toLink'))))
        controlled = {self.links[k].get('to') for k in self.signals if k in self.links}
        incoming, outgoing = defaultdict(list), defaultdict(list)
        for key, link in self.links.items():
            incoming[link.get('to')].append(key); outgoing[link.get('from')].append(key)
        def attrs(element): return {a.get('name'): a.text for a in element.findall('attributes/attribute')}
        following, previous = {}, {}
        for key, link in sorted(self.links.items()):
            node = link.get('to'); own = attrs(link); node_attrs = attrs(self.nodes[node])
            if node in controlled or own.get('simz1:priorityControl') in ('stop', 'yield') or any(
                    node_attrs.get(k) in ('traffic_signals', 'stop', 'give_way') for k in ('osm:highway', 'highway')):
                continue
            neighbours = {self.links[k].get('from') for k in incoming[node]} | {self.links[k].get('to') for k in outgoing[node]}
            targets = [k for k in outgoing[node] if self.links[k].get('to') != link.get('from')]
            if len(neighbours) != 2 or len(targets) != 1: continue
            other = self.links[targets[0]]; other_attrs = attrs(other)
            if (float(link.get('permlanes')) != float(other.get('permlanes')) or
                    set(link.get('modes', 'car').split(',')) != set(other.get('modes', 'car').split(',')) or
                    any(own.get(k) != other_attrs.get(k) for k in ('osm:layer', 'osm:bridge', 'osm:tunnel')) or
                    sum(a*b for a, b in zip(self.geometry.direction(link), self.geometry.direction(other))) < .95): continue
            following[key] = targets[0]; previous[targets[0]] = key
        self.domain, self.offsets, self.capacity = {}, {}, {}
        for start in sorted(set(self.links)-set(previous)) + sorted(self.links):
            if start in self.domain: continue
            key = start; distance = 0.; chain = []
            while key is not None and key not in self.domain:
                self.domain[key] = start; self.offsets[key] = distance; chain.append(key)
                distance += float(self.links[key].get('length')); key = following.get(key)
            self.capacity[start] = max(0., distance-self.geometry.setback(chain[-1]))

    def movement_lanes(self, source, target):
        rows = [(int(name.rsplit('.lane.', 1)[1]), name) for name, row in self.lanes.get(source, {}).items()
                if '.lane.' in name and target in row['to_links']]
        return tuple(name for _, name in sorted(rows)) or (None,)

    @lru_cache(maxsize=32768)
    def traversal(self, source, lane, speed):
        speed = min(speed, float(self.links[source].get('freespeed')))
        if not math.isfinite(speed) or speed <= 0 or self.step <= 0: return math.inf
        assignment = self.lanes.get(source, {})
        if not assignment: lengths = [float(self.links[source].get('length'))]
        elif lane is None or lane not in assignment: return math.inf
        else:
            lengths = [row['start']-max((assignment[k]['start'] for k in row['to_lanes']), default=0.)
                       for name, row in assignment.items() if name.endswith('.original') or name == lane]
        return sum(self.step*(math.floor(length/speed/self.step)+2) for length in lengths)

    @lru_cache(maxsize=32768)
    def windows(self, requirements):
        period = 1; rows = []
        if not math.isfinite(self.step) or self.step <= 0: return UNKNOWN
        for source, lane, target, deadline, initial in requirements:
            if not math.isfinite(deadline) or deadline < 0: return UNKNOWN
            for sid, group, lanes, turns in self.signals.get(source, ()):
                if turns and target not in turns: continue
                if lanes and lane is None: return UNKNOWN
                if lanes and lane not in lanes: continue
                plan = self.plans.get(sid)
                if plan is None or group not in plan['groups']: return UNKNOWN
                ticks = plan['cycle']/self.step
                if not 1 <= ticks <= MAX_PERIOD_TICKS or abs(ticks-round(ticks)) > 1e-8: return UNKNOWN
                period = math.lcm(period, round(ticks))
                if period > MAX_PERIOD_TICKS: return UNKNOWN
                rows.append((plan, group, deadline, initial))
        for tick in range(period):
            opened = True
            for plan, group, deadline, initial in rows:
                if initial:
                    onset, dropping = plan['groups'][group]
                    allowed = (tick*self.step-plan['offset']-onset) % plan['cycle'] < (dropping-onset) % plan['cycle']
                else: allowed = remaining_green(plan, group, tick*self.step, plan['offset']) > deadline
                if not allowed:
                    opened = False; break
            if opened: return COMPATIBLE
        return IMPOSSIBLE

    @lru_cache(maxsize=32768)
    def passage(self, path, start, body, speed, lane=None, complete=True):
        """Physical requirements for ONE passage, independent of signal phase.

        Used by route queries and the bounded local coordination audit. A receipt
        index is returned even when the current phases are incompatible.
        """
        source_lanes = (lane,) if start == 0 and lane is not None and '.lane.' in lane else self.movement_lanes(path[start], path[start+1])
        requirements, used, budget, pending, receipt = [], set(), 0., False, None
        i = start+1
        while i < len(path):
            key = path[i]; domain = self.domain[key]; end = i+1
            while end < len(path) and self.domain[path[end]] == domain: end += 1
            last = path[end-1]; front = self.offsets[last]+float(self.links[last].get('length'))
            if end < len(path) or not complete: front -= self.geometry.setback(last)
            front = min(self.capacity[domain], front)
            need = body+.1+self.geometry.setback(key, entry=True)-2
            if domain not in used and front-self.offsets[key] >= need:
                receipt = i; break
            if not complete and end == len(path): pending = True; break
            used.add(domain)
            for j in range(i, min(end, len(path)-1)):
                selected = self.movement_lanes(path[j], path[j+1])[0]
                budget += self.traversal(path[j], selected, speed)
                requirements.append((path[j], selected, path[j+1], budget, False))
            i = end
        options = tuple(((path[start], choice, path[start+1], 0., True), *requirements) for choice in source_lanes)
        return options, receipt, pending

    @lru_cache(maxsize=32768)
    def query(self, path, body, speed, lane=None, complete=True):
        if not self.enabled: return COMPATIBLE, (path[-1],), 'body_passages_disabled'
        if not path or not all(math.isfinite(x) and x > 0 for x in (body, speed)):
            return UNKNOWN, path, 'physical_parameters_unavailable'
        status, last_receipt = COMPATIBLE, 0
        for start in range(len(path)-1):
            if path[start] not in self.domain or path[start+1] not in self.domain: return UNKNOWN, path, 'nonroad_geometry'
            if self.domain[path[start]] == self.domain[path[start+1]]: continue
            options, receipt, pending = self.passage(path, start, body, speed, lane, complete)
            if receipt is not None: last_receipt = max(last_receipt, receipt)
            outcomes = [self.windows(requirements) for requirements in options]
            if all(x == IMPOSSIBLE for x in outcomes):
                return IMPOSSIBLE, path, 'no_periodic_passage_window:'+path[start]+'->'+path[start+1]
            if COMPATIBLE not in outcomes or pending: status = UNKNOWN
        return status, path[last_receipt:], 'empty_queue_periodic_window' if status == COMPATIBLE else 'incomplete_or_unsupported_passage'


def repair_route(model, origin, destination, body, speed):
    """Keep the already drawn OD pair. Only a proved impossible route is repaired.

    No random calls, global turn deletions, altered departure, or cost penalty.
    The search product retains the OSM DFA, mandatory gateway chains and pending
    physical passage. The existing interior graph excludes unrelated gateways.
    """
    original = model.route(origin, destination)
    temporal = getattr(model, 'temporal', None)
    if temporal is None: return original
    status, _, reason = temporal.query(tuple(original), body, speed)
    if status == COMPATIBLE: return original
    if status == UNKNOWN: raise ValueError('TEMPORAL_ROUTE_UNKNOWN: '+origin+' -> '+destination+' / '+reason)
    entry, exit = model.entry_gateways.get(origin), model.exit_gateways.get(destination)
    prefix = tuple(entry['link_ids']) if entry else (origin,)
    end = exit['observation_link'] if exit else destination
    tail = tuple(exit['link_ids'][1:]) if exit else ()
    progress = model.sequences.progress(prefix)
    initial_check = temporal.query(prefix, body, speed, complete=False)
    if progress is None or initial_check[0] == IMPOSSIBLE:
        raise ValueError('TEMPORAL_ROUTE_NO_ALTERNATIVE: mandatory origin chain / '+reason)
    initial = prefix[-1], progress, tuple(sorted(set(prefix)&model.sequences.via_links)), initial_check[1]
    serial = itertools.count(); queue = [(0., next(serial), initial)]; best, previous = {initial: 0.}, {}
    while queue:
        cost, _, state = heapq.heappop(queue)
        if best[state] != cost: continue
        current, progress, visited, context = state
        if current == end and model.sequences.progress(tail, progress) is not None:
            path = [current]; prior = state
            while prior in previous:
                prior = previous[prior]; path.append(prior[0])
            result = list(prefix[:-1])+list(reversed(path))+list(tail)
            if temporal.query(tuple(result), body, speed)[0] == COMPATIBLE:
                model.validate_route(result)
                return result
        for target in model.successors[current]:
            advanced = model.sequences.advance(progress, target)
            if advanced is None or target in visited or target in context: continue
            checked = temporal.query(context+(target,), body, speed, complete=False)
            if checked[0] == IMPOSSIBLE: continue
            vias = tuple(sorted((*visited, target))) if target in model.sequences.via_links else visited
            updated = target, advanced, vias, checked[1]
            score = cost+model.links[target]['length']/model.links[target]['freespeed']
            if score < best.get(updated, math.inf):
                best[updated], previous[updated] = score, state
                heapq.heappush(queue, (score, next(serial), updated))
        if len(best) > 1_000_000:
            raise ValueError('TEMPORAL_ROUTE_UNKNOWN: bounded state search exhausted; fixed OD pair retained')
    raise ValueError('TEMPORAL_ROUTE_NO_ALTERNATIVE: '+origin+' -> '+destination+' / '+reason)


def fixed_transit_audit(temporal, schedule, vehicles):
    definitions = _xml(vehicles)
    types = {e.get('id'): (float(e.find('length').get('meter')), float(e.find('maximumVelocity').get('meterPerSecond')))
             for e in definitions.findall('vehicleType')}
    bindings = {e.get('id'): types[e.get('type')] for e in definitions.findall('vehicle')}
    rows = []
    for line in _xml(schedule).findall('transitLine'):
        for route in line.findall('transitRoute'):
            path = tuple(e.get('refId') for e in route.findall('route/link'))
            departures = route.findall('departures/departure')
            for body, speed in sorted({bindings[e.get('vehicleRefId')] for e in departures}):
                status, _, reason = temporal.query(path, body, speed)
                rows.append(dict(line=line.get('id'), route=route.get('id'), body_m=body, maximum_speed_mps=speed,
                    status=status, reason=reason, route_link_ids=path,
                    stops=[dict(e.attrib) for e in route.findall('routeProfile/stop')],
                    configured_vehicle_ids=sorted({e.get('vehicleRefId') for e in departures if bindings[e.get('vehicleRefId')] == (body, speed)}),
                    expeditions=sum(bindings[e.get('vehicleRefId')] == (body, speed) for e in departures)))
    return dict(policy=POLICY, effective_input_sha256=temporal.hashes, routes=rows,
                status='compatible' if all(r['status'] == COMPATIBLE for r in rows) else 'blocked_fixed_service',
                scope='static empty-queue periodic passage; service stop placement checked by existing attach_transit audits; no queue-drainage claim')


def require_fixed_transit(report):
    failures = [r for r in report['routes'] if r['status'] != COMPATIBLE]
    if failures:
        raise ValueError('TEMPORAL_FIXED_SERVICE_INCOMPATIBLE: '+json.dumps(
            [{k:r[k] for k in ('line','route','body_m','status','reason','expeditions','configured_vehicle_ids')} for r in failures], sort_keys=True))
