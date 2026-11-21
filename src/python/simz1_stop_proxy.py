"""Conservative stop proxies on individual native links, not surveyed platforms.

This does not reconstruct Java occupancy corridors. It uses the same published
nominal intersection-width model to require a complete bus body on one link.
"""
from collections import defaultdict
from copy import deepcopy
import math

POLICY = 'body_before_conflict_proxy_v1'
QUEUE_POLICY = 'service_original_endpoint_before_conflict_v1'
LEGACY_QUEUE_POLICY = 'preserve_imported_queue_splits'
NOMINAL_LANE_WIDTH_M = 3.
BASE_SETBACK_M = 2.
MINIMUM_GAP_M = .10


def _require(value, message):
    if not value: raise ValueError('TRANSIT_STOP_PROXY: '+message)


class StopGeometry:
    def __init__(self, links, nodes, lane_assignments=None):
        self.links, self.nodes = links, nodes
        self.lanes = lane_assignments or {}
        self.incident = defaultdict(list); self.cache = {}
        for link in links.values():
            if set(link.get('modes', 'car').split(',')) & {'car', 'bus'}:
                self.incident[link.get('from')].append(link)
                self.incident[link.get('to')].append(link)

    def direction(self, link):
        a, b = self.nodes[link.get('from')], self.nodes[link.get('to')]
        x, y = float(b.get('x'))-float(a.get('x')), float(b.get('y'))-float(a.get('y'))
        length = math.hypot(x, y)
        _require(math.isfinite(length) and length > 0, 'degenerate link '+link.get('id'))
        return x/length, y/length

    def setback(self, ident, *, entry=False):
        key = (ident, entry)
        if key in self.cache: return self.cache[key]
        link = self.links[ident]; ux, uy = self.direction(link); margin = 0.
        incident = self.incident[link.get('from') if entry else link.get('to')]
        for other in incident:
            if other is link: continue
            vx, vy = self.direction(other); cross = abs(ux*vy-uy*vx)
            if cross < .25: continue
            lanes = float(other.get('permlanes'))
            for reverse in incident:
                if reverse.get('from') == other.get('to') and reverse.get('to') == other.get('from'):
                    lanes += float(reverse.get('permlanes'))
            margin = max(margin, .5*NOMINAL_LANE_WIDTH_M*lanes/cross)
        value = BASE_SETBACK_M+margin; self.cache[key] = value
        return value

    def native_endpoint(self, ident):
        length = float(self.links[ident].get('length')); lanes = self.lanes.get(ident)
        if not lanes: return length, None, 'undivided_native_link_queue_endpoint'
        children = {child for lane in lanes.values() for child in lane['to_lanes']}
        roots = [key for key in lanes if key not in children]
        _require(len(roots) == 1, 'ambiguous receiving queue '+ident)
        root = roots[0]; downstream = lanes[root]['to_lanes']
        end = length-max(lanes[child]['start'] for child in downstream) if downstream else length
        return end, root, 'configured_native_receiving_queue_endpoint'

    def usable_front(self, ident):
        endpoint, _, _ = self.native_endpoint(ident)
        return min(endpoint, float(self.links[ident].get('length'))-self.setback(ident))

    def place(self, path, records, body_length, *, preserve_source_stops=False):
        records = sorted(deepcopy(records), key=lambda row: row['link_index'])
        _require(len({row['link_index'] for row in records}) == len(records), 'multiple source stops on one route index')
        eligible = [i for i in range(1, len(path)-1)
                    if self.usable_front(path[i])+1e-9 >= body_length+MINIMUM_GAP_M+self.setback(path[i], entry=True)]
        distances = []; distance = 0.
        for ident in path:
            distances.append(distance); distance += float(self.links[ident].get('length'))
        # Ordered assignment prevents one moved stop from stealing the only
        # feasible queue of its neighbour. New derived queues first preserve
        # source stops; historical policy first minimizes downstream moves.
        # Never drop/merge a source stop, including stations at route gateways.
        states = {-1: ((0, 0, 0., 0), [])}
        for row in records:
            original = row['link_index']
            _require(type(original) is int and 0 <= original < len(path), 'stop outside directed route')
            options = [original] if row.get('role') == 'gateway' else eligible
            prior = sorted(states.items()); pointer = 0; best = None; following = {}
            for candidate in options:
                while pointer < len(prior) and prior[pointer][0] < candidate:
                    value = prior[pointer][1]
                    if best is None or value[0] < best[0]: best = value
                    pointer += 1
                if best is None: continue
                displacement = abs(distances[candidate]+self.usable_front(path[candidate])-
                                   distances[original]-float(self.links[path[original]].get('length')))
                cost = (best[0][0]+int(preserve_source_stops and candidate != original),
                        best[0][1]+int(candidate > original), best[0][2]+displacement, best[0][3]+candidate)
                following[candidate] = (cost, best[1]+[candidate])
            _require(following, 'no body-safe ordered proxy assignment for '+row['stop_id'])
            states = following
        assigned = min(states.values(), key=lambda item:item[0])[1]
        result = []
        for row, chosen in zip(records, assigned):
            original = row['link_index']
            if row.get('role', 'passenger_stop') == 'gateway':
                result.append(row); continue
            ident = path[chosen]; link = self.links[ident]; length = float(link.get('length')); setback = self.setback(ident)
            a, b = self.nodes[link.get('from')], self.nodes[link.get('to')]
            endpoint, native_queue, endpoint_basis = self.native_endpoint(ident)
            fraction = max(0., min(1., self.usable_front(ident)/length))
            original_link = self.links[path[original]]; original_node = self.nodes[original_link.get('to')]
            row['link_index'] = chosen
            row['placement_basis'] = 'explicit_body_before_conflict_proxy_not_surveyed_platform'
            row['proxy_placement'] = dict(policy=POLICY, relocated=chosen != original,
                reason=('gateway_requires_nonstopping_endpoint' if original in (0,len(path)-1) else
                        'ordered_stop_sequence_requires_proxy' if original in eligible else
                        'source_link_cannot_hold_bus_before_conflict') if chosen != original else 'body_fits_source_link_before_conflict',
                selection=('ordered_assignment_minimum_relocations_then_downstream_moves_then_route_displacement'
                           if preserve_source_stops else 'ordered_assignment_minimum_downstream_moves_then_route_displacement'),
                original_stop_id=row['stop_id'], original_link_id=path[original], original_link_index=original,
                original_native_position_xy=[float(original_node.get('x')), float(original_node.get('y'))],
                source_position=row.get('source_position'), modeled_link_id=ident, modeled_link_index=chosen,
                modeled_front_fraction=fraction,
                modeled_front_position_xy=[float(a.get('x'))+(float(b.get('x'))-float(a.get('x')))*fraction,
                                           float(a.get('y'))+(float(b.get('y'))-float(a.get('y')))*fraction],
                body_length_m=body_length, minimum_gap_m=MINIMUM_GAP_M, link_length_m=length,
                end_setback_m=setback, entry_setback_m=self.setback(ident, entry=True),
                native_queue_id=native_queue, native_service_endpoint_m=endpoint,
                native_service_endpoint_basis=endpoint_basis, nominal_lane_width_m=NOMINAL_LANE_WIDTH_M,
                native_resolution='blocking_link_queue_not_continuous_stop_coordinate',
                empirical_platform_relocation=False)
            result.append(row)
        return result


def summary(stops, enabled):
    proxies = [row['proxy_placement'] for row in stops if row.get('proxy_placement')]
    return dict(enabled=enabled, policy=POLICY if enabled else 'legacy_endpoint_proxy',
                passenger_stops_checked=len(proxies), relocated_stops=sum(row['relocated'] for row in proxies),
                scope='configured individual-link body capacity before nominal conflict area; not observed microscopic positions')


def lane_assignments(root):
    """Read an in-memory copy; never overwrite the dated base lane definitions."""
    result = {}
    for row in root.findall('{*}lanesToLinkAssignment'):
        result[row.get('linkIdRef')] = {lane.get('id'): dict(
            start=float(lane.find('{*}startsAt').get('meterFromLinkEnd')),
            to_lanes=[x.get('refId') for x in lane.findall('{*}leadsTo/{*}toLane')],
            to_links=[x.get('refId') for x in lane.findall('{*}leadsTo/{*}toLink')])
            for lane in row.findall('{*}lane')}
    return result


def adjust_service_queues(root, network_root, stops):
    """Move the original/terminal split in a new snapshot, not the physical link.

    Only a simple receiving queue -> terminal queues graph is supported. IDs,
    movements, represented lanes and flow limits are left byte-for-byte intact
    within each element. Physical body capacity remains the native corridor
    ledger's responsibility, including a body spanning this internal split.
    """
    links={row.get('id'):row for row in network_root.findall('./links/link')}
    nodes={row.get('id'):row for row in network_root.findall('./nodes/node')}
    geometry=StopGeometry(links,nodes,lane_assignments(root))
    assignments={row.get('linkIdRef'):row for row in root.findall('{*}lanesToLinkAssignment')}
    selected=defaultdict(list)
    for stop in stops:
        if stop.get('role') != 'gateway': selected[stop['link_id']].append(stop)
    changes=[]
    for ident, records in sorted(selected.items()):
        if ident not in assignments: continue  # Undivided link has no queue split to adjust.
        lanes=geometry.lanes[ident]; old_endpoint,original,_=geometry.native_endpoint(ident)
        terminals=lanes[original]['to_lanes']
        _require(terminals and len(terminals)==len(lanes)-1 and not lanes[original]['to_links'] and
                 all(not lanes[child]['to_lanes'] for child in terminals), 'unsupported split graph '+ident)
        length=float(links[ident].get('length')); setback=geometry.setback(ident)
        _require(0 < setback < length, 'invalid terminal split length '+ident)
        _require(abs(lanes[original]['start']-length) < 1e-7, 'original queue does not span native link '+ident)
        new_endpoint=length-setback
        _require(all(new_endpoint+1e-9 >= row['proxy_placement']['body_length_m']+MINIMUM_GAP_M+
                     geometry.setback(ident,entry=True) for row in records), 'body cannot fit selected stop link '+ident)
        before={child:lanes[child]['start'] for child in terminals}
        elements={row.get('id'):row for row in assignments[ident].findall('{*}lane')}
        for child in terminals:
            elements[child].find('{*}startsAt').set('meterFromLinkEnd',repr(setback))
        changes.append(dict(link_id=ident,original_queue_id=original,terminal_queue_ids=sorted(terminals),
            stop_ids=sorted(row['stop_id'] for row in records),link_length_m=length,
            old_native_service_endpoint_m=old_endpoint,new_native_service_endpoint_m=new_endpoint,
            old_terminal_starts_m=before,new_terminal_starts_m={child:setback for child in terminals},
            end_setback_m=setback,entry_setback_m=geometry.setback(ident,entry=True),
            maximum_bus_body_m=max(row['proxy_placement']['body_length_m'] for row in records)))
    return dict(enabled=True,policy=QUEUE_POLICY,adjusted_links=len(changes),adjustments=changes,
        scope='new_run_snapshot_only; queue_split_not_link_geometry_or_observed_lane',
        preserved=['link_length','lane_ids','leads_to','represented_lanes','flow_capacity','alignment'],
        body_capacity_basis='native_corridor_length_reservation_across_internal_queues',
        nominal_lane_width_m=NOMINAL_LANE_WIDTH_M)
