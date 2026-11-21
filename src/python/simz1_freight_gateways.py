"""Native activity anchors and event-backed freight perimeter clearance.

QSim activity insertion/arrival may occur at the end of the first queue, before
the end of a MATSim link. A link ID or relativePosition=1 is not exit evidence.
The event audit uses the native ledger's modeled front LOWER bound instead.
"""
import math

POLICY = 'native-queue-perimeter-clearance-v1'
GAP_M = 0.10
MAX_EXTERNAL_ANCHOR_M = 250.0
EPS = 1e-7


def validate_native_gateways(ctx, route, service):
    from simz1_freight_routes import _inside, _gateway
    if service.get('native_gateway_policy') != POLICY:
        raise ValueError('Freight compact service requires native perimeter clearance policy')
    path = route['link_ids']
    if (route.get('boundary_basis') != 'osm_bounds_crossing_with_native_external_anchors' or
            route.get('activity_origin_link') != path[0] or route.get('activity_destination_link') != path[-1]):
        raise ValueError('Freight native activity anchors differ from route endpoints')
    transitions = []
    for i, key in enumerate(path):
        link = ctx['links'][key]
        a, b = _inside(ctx, link['from']), _inside(ctx, link['to'])
        if a != b:
            transitions.append((i, a, b))
        elif not a:
            # An exterior-to-exterior chord may still cut across the rectangle.
            p, q, bounds = ctx['osm_nodes'][link['from']], ctx['osm_nodes'][link['to']], ctx['bounds']
            lo, hi = 0., 1.
            for coordinate, minimum, maximum in (('lon', 'minlon', 'maxlon'), ('lat', 'minlat', 'maxlat')):
                delta = q[coordinate]-p[coordinate]
                if delta == 0:
                    if not bounds[minimum] < p[coordinate] < bounds[maximum]:
                        lo, hi = 1., 0.; break
                else:
                    first, second = sorted(((bounds[minimum]-p[coordinate])/delta,
                                            (bounds[maximum]-p[coordinate])/delta))
                    lo, hi = max(lo, first), min(hi, second)
            if hi > lo+1e-10:
                raise ValueError('Freight exterior anchor crosses or reenters the perimeter: '+key)
    if [(a,b) for _,a,b in transitions] != [(False,True),(True,False)]:
        raise ValueError('Freight requires one directed perimeter entry and exit without reentry')
    entry_index, exit_index = transitions[0][0], transitions[1][0]
    entry_key, exit_key = path[entry_index], path[exit_index]
    if route.get('entry_gateway') != entry_key or route.get('exit_gateway') != exit_key:
        raise ValueError('Freight declared gateway differs from real perimeter crossing link')
    prefix, suffix = path[:entry_index], path[exit_index+1:]
    if route.get('external_origin_links') != prefix or route.get('external_exit_links') != suffix:
        raise ValueError('Freight exterior activity-anchor links are not declared exactly')
    prefix_m = sum(ctx['links'][key]['length'] for key in prefix)
    suffix_m = sum(ctx['links'][key]['length'] for key in suffix)
    if prefix_m+suffix_m > MAX_EXTERNAL_ANCHOR_M+EPS:
        raise ValueError('Freight external activity anchors exceed the bounded 250 m connector policy')
    entry_link, exit_link = ctx['links'][entry_key], ctx['links'][exit_key]
    entry = _gateway(ctx, entry_link['from'], entry_link['to'], entry_key)
    exit = _gateway(ctx, exit_link['to'], exit_link['from'], exit_key)
    if entry['side'] == exit['side'] or math.hypot(entry['lon']-exit['lon'], entry['lat']-exit['lat']) <= 1e-8:
        raise ValueError('Freight requires distinct through-perimeter sides')
    offsets, at = {}, 0.
    for key in path:
        offsets[key] = at
        at += ctx['links'][key]['length']

    def distance(link, crossing):
        p, q = ctx['osm_nodes'][link['from']], ctx['osm_nodes'][link['to']]
        coordinate = 'lat' if crossing['side'] in ('north','south') else 'lon'
        return (crossing[coordinate]-p[coordinate])/(q[coordinate]-p[coordinate])*link['length']

    entry_at = offsets[entry_key]+distance(entry_link, entry)
    exit_at = offsets[exit_key]+distance(exit_link, exit)
    original_ends = ctx.get('native_entry_queue_end_m', {})
    origin_end = original_ends.get(path[0], ctx['links'][path[0]]['length'])
    destination_end = original_ends.get(path[-1], ctx['links'][path[-1]]['length'])
    native_arrival_upper = offsets[path[-1]]+destination_end
    footprint = float(service['length_m'])+GAP_M
    if origin_end > entry_at+EPS:
        raise ValueError('Freight native origin insertion occurs after perimeter entry')
    if native_arrival_upper-footprint < exit_at-EPS:
        raise ValueError('Freight native destination queue ends before whole body clears perimeter')
    return dict(policy=POLICY, entry=entry, exit=exit,
        activity_origin_link=path[0], activity_destination_link=path[-1],
        external_origin_links=prefix, external_exit_links=suffix,
        external_origin_length_m=prefix_m, external_exit_length_m=suffix_m,
        entry_distance_from_route_start_m=entry_at, exit_distance_from_route_start_m=exit_at,
        origin_first_queue_end_m=origin_end, destination_first_queue_end_m=destination_end,
        native_arrival_front_upper_bound_from_route_start_m=native_arrival_upper,
        static_rear_plus_gap_clearance_upper_bound_m=native_arrival_upper-footprint-exit_at,
        body_length_m=float(service['length_m']), minimum_gap_m=GAP_M,
        route_link_start_m=offsets, route_link_length_m={key:ctx['links'][key]['length'] for key in path},
        arrival_requires_native_ledger_lower_bound=True,
        position_basis='OSM rectangle straight-segment crossing scaled to saved native lengths; first-queue upper bound only; actual ledger may be reduced by domain cap or preceding bodies')


class NativeGatewayAudit:
    """Small additional audit in the SAME event pass as CorridorOccupancyAudit.

    The existing corridor auditor independently verifies event chronology,
    domains, body sizes, reservation identity, leader order and progress bounds.
    This class maps that lower bound onto the declared freight route and checks
    the map crossing. It never substitutes a link event or a free-flow estimate.
    """
    def __init__(self, contract):
        self.contract = {key:row['native_gateway'] for key,row in contract.items() if row.get('native_gateway')}
        self.domains, self.active, self.last_front = {}, {}, {}
        self.departure_proofs, self.arrival_proofs = {}, {}

    @staticmethod
    def _number(event, field):
        try:
            value = float(event.get(field))
        except (TypeError, ValueError) as exc:
            raise ValueError('Freight native gateway missing ledger '+field) from exc
        if not math.isfinite(value):
            raise ValueError('Freight native gateway nonfinite ledger '+field)
        return value

    def consume(self, event):
        kind = event.get('type')
        if kind == 'simz1OccupancyDomain' and self.contract:
            link, corridor = event.get('link'), event.get('corridor')
            if not link or not corridor or link in self.domains:
                raise ValueError('Freight native gateway duplicate/missing occupancy domain')
            self.domains[link] = dict(corridor=corridor,
                offset=self._number(event, 'linkOffsetMeters'), length=self._number(event, 'linkLengthMeters'))
            return
        ident = event.get('person') or event.get('vehicle')
        if ident not in self.contract:
            return
        geometry = self.contract[ident]
        if kind == 'simz1OccupancyReservation':
            action = event.get('action')
            if action == 'WAIT':
                return
            if action == 'EXIT':
                self.active.pop(ident, None); self.last_front.pop(ident, None)
                return
            if action not in ('ENTER','TRANSFER'):
                raise ValueError('Freight native gateway unsupported reservation action')
            body = self._number(event, 'bodyLengthMeters')
            footprint = self._number(event, 'footprintMeters')
            if abs(body-geometry['body_length_m']) > EPS or abs(footprint-body-GAP_M) > EPS:
                raise ValueError('Freight native gateway body/footprint differs from saved service')
            self.active[ident] = dict(corridor=event.get('corridor'), link=event.get('link'),
                passage_kind=event.get('passageKind'), receipt=event.get('receiptLink'),
                exit_from=event.get('exitFromLink'),
                passage_links=(event.get('exitLinks') or event.get('passageLinks') or '').split(','),
                ordinal=event.get('reservationOrdinal'))
            # A transfer can change the native coordinate basis. Only a new
            # progress record in that basis is acceptable for a later arrival.
            self.last_front.pop(ident, None)
        elif kind == 'simz1OccupancyProgress':
            state = self.active.get(ident)
            if state is None or event.get('corridor') != state['corridor']:
                raise ValueError('Freight native gateway progress lacks a matching reservation')
            link, corridor = event.get('link'), state['corridor']
            if self.domains.get(link, {}).get('corridor') == corridor:
                anchor = link
            elif link in state['passage_links']:
                anchor = state['exit_from'] if state['passage_kind'] == 'boundary_exit' else state['receipt']
            else:
                raise ValueError('Freight native gateway progress lies outside reserved domain/passage')
            mapping = self.domains.get(anchor)
            if mapping is None or mapping['corridor'] != corridor or anchor not in geometry['route_link_start_m']:
                raise ValueError('Freight native gateway missing route/domain coordinate anchor')
            front = geometry['route_link_start_m'][anchor]-mapping['offset']+self._number(event, 'modeledFrontLowerBoundMeters')
            self.last_front[ident] = dict(front_from_route_start_m=front, time=self._number(event,'time'),
                link=link, corridor=corridor, anchor_link=anchor, reservation_ordinal=state['ordinal'],
                modeled_front_lower_bound_m=self._number(event,'modeledFrontLowerBoundMeters'))
        elif kind == 'vehicle enters traffic':
            proof = self.last_front.get(ident)
            if proof is None:
                raise ValueError('Freight native gateway insertion lacks physical ledger evidence: '+ident)
            if proof['front_from_route_start_m'] > geometry['entry_distance_from_route_start_m']+EPS:
                raise ValueError('Freight native insertion already inside perimeter: '+ident)
            self.departure_proofs[ident] = dict(proof)
        elif kind in ('vehicle leaves traffic','arrival'):
            proof = self.last_front.get(ident)
            if proof is None or ident not in self.active:
                raise ValueError('Freight arrival lacks active native physical gateway evidence: '+ident)
            rear = proof['front_from_route_start_m']-geometry['body_length_m']-geometry['minimum_gap_m']
            clearance = rear-geometry['exit_distance_from_route_start_m']
            if clearance < -EPS:
                raise ValueError('Freight arrival before full body and 0.10 m gap clear real perimeter: '+ident)
            self.arrival_proofs[ident] = dict(proof, observed_terminal_time=self._number(event,'time'),
                exit_distance_from_route_start_m=geometry['exit_distance_from_route_start_m'],
                body_length_m=geometry['body_length_m'], minimum_gap_m=geometry['minimum_gap_m'],
                rear_plus_gap_clearance_m=clearance)

    def summary(self):
        return dict(policy=POLICY, required_vehicles=len(self.contract),
            entry_evidence_count=len(self.departure_proofs), exit_evidence_count=len(self.arrival_proofs),
            complete=set(self.arrival_proofs) == set(self.contract),
            position_basis='validated_native_occupancy_modeled_front_lower_bound',
            entries=self.departure_proofs, exits=self.arrival_proofs)
