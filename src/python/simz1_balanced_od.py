"""Opt-in private OD contract; geometry and incorporation evidence are inputs.

No default boundary, mixture, access catalogue, network edits or service routes.
GatewayModel supplies the existing directed interior graph and reachability.
"""
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import heapq
import json
import math
from pathlib import Path

from simz1_gateway_od import load_gateway_model, _xml, boundary_geometry, Polygon, EPS
from simz1_od_policy import CLASS_BY_TYPE, LEGACY, named_percentages
from simz1_freight_gateways import GAP_M, MAX_EXTERNAL_ANCHOR_M
from simz1_sequence_contract import SequenceContract, SHA256 as SEQUENCE_SHA256

VARIANT = 'balanced-gateway-v1'
ORIGIN_POLICY = 'lane-length-access-v1'
ACCESS_SCHEMA = 'simz1-verified-private-access-v1'
METADATA_SCHEMA = 'simz1-private-gateway-trip-v1'
BOUNDARY_SCHEMA = 'simz1-verified-perimeter-v1'


class CapacityIncompatibility(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('Capacidad de acceso insuficiente o muestreo sin par admisible tras 1024 intentos: '
                         f"{diagnostic['od_class']}, hora {diagnostic['hour']}. "
                         'No se cambian N, clase ni hora; no se publica manifiesto preparado. '
                         'Consultar od-preflight-failure.json si se estaba escribiendo una carpeta nueva.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence(value, label):
    if (not isinstance(value, dict) or value.get('verified') is not True or
            any(not isinstance(value.get(k), str) or not value[k].strip()
                for k in ('version', 'source', 'reviewed_by', 'reviewed_at'))):
        raise ValueError(label + ': verified provenance/version/source/reviewer/date required')


def boundary_rate(row, role):
    """New catalogues name the boundary budget; retain the legacy field on old runs."""
    field = role + '_capacity_pcu_h'
    if row.get('flow_role') is not None:
        return row.get(field)
    return row.get(field, row.get('incorporation_capacity_pcu_h'))


def input_options(boundary, access, mix):
    for value, flag in ((boundary, '--zone-boundary'), (access, '--od-access-catalog')):
        if value is None or not Path(value).is_file():
            raise ValueError(f'{VARIANT} disabled: missing {flag} ({value}). Provide verified RFC7946 perimeter '
                             'and versioned access evidence with SHA256; no OSM bbox fallback')
    if mix is None:
        raise ValueError(f'{VARIANT} requires --od-mix: four named synthetic percentages totaling exactly 100')
    return named_percentages(mix)


def native_queue_ends(network, lanes):
    ends = {row.get('id'): float(row.get('length')) for row in _xml(network).findall('links/link')}
    if lanes is None:
        raise ValueError('Verified private OD requires the effective lane definitions')
    for assignment in _xml(lanes).findall('lanesToLinkAssignment'):
        key = assignment.get('linkIdRef')
        rows = {r.get('id'): r for r in assignment.findall('lane')}
        original = rows.get(key + '.original')
        if original is None:
            raise ValueError('Unrecognized native entry lane: ' + key)
        children = [r.get('refId') for r in original.findall('leadsTo/toLane')]
        if children:
            ends[key] -= max(float(rows[c].find('startsAt').get('meterFromLinkEnd')) for c in children)
        if not 0 < ends[key] <= float(original.find('startsAt').get('meterFromLinkEnd')):
            raise ValueError('Invalid native first queue endpoint: ' + key)
    return ends


def load_model(network, boundary, lanes, osm, access, crs='EPSG:32615'):
    document = json.loads(Path(access).read_text(encoding='utf-8'))
    if document.get('schema_version') != ACCESS_SCHEMA:
        raise ValueError('Unknown verified private access catalogue schema')
    evidence(document.get('review'), 'Private access catalogue')
    perimeter = document.get('perimeter', {})
    evidence(perimeter, 'Perimeter')
    if perimeter.get('schema_version') != BOUNDARY_SCHEMA or perimeter.get('sha256') != digest(boundary):
        raise ValueError('Verified perimeter hash/schema mismatch; cannot enable private OD')
    # Syntactically valid geometry alone is not a verification of provenance.
    Polygon(boundary_geometry(json.loads(Path(boundary).read_bytes())))
    for key, path in (('network_sha256', network), ('lanes_sha256', lanes), ('osm_sha256', osm)):
        if path is None or document.get(key) != digest(path):
            raise ValueError('Private access evidence does not match effective source: ' + key)
    # Also protect direct callers of load_model, before any private route is made.
    from simz1_od_policy import validate_osm_turns
    validate_osm_turns(osm, network, lanes)
    return model_from_document(network, boundary, lanes, osm, access, document, crs)


def model_from_document(network, boundary, lanes, osm, access, document, crs):
    """Construct after source fingerprints or the service derivation were verified."""
    base = load_gateway_model(network, boundary, lanes, crs)
    # Locate the boundary cut in the native metric path, not in degrees: the
    # latter distorts longitudinal fractions on bends with different bearings.
    from pyproj import Transformer
    project = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
    for link in base.links.values():
        link['metric_path'] = [project.transform(*xy, errcheck=True) for xy in link['path']]
    from simz1_osm_turn_audit import load_lanes
    model = BalancedGatewayModel(base, document, native_queue_ends(network, lanes), load_lanes(lanes))
    model.summary.update(boundary_sha256=digest(boundary), access_sha256=digest(access),
                         network_sha256=digest(network), lanes_sha256=digest(lanes), osm_sha256=digest(osm))
    return model


class BalancedGatewayModel:
    """Private trips use reviewed boundary sources or internal incorporation sites.

    Internal connectors remain in the route graph even if they cannot host an
    activity. Gateway anchors are existing exterior links, never interior proxies.
    Tests may construct this class from explicitly synthetic metric geometry;
    real file loading additionally requires verified hashes and provenance.
    """
    def __init__(self, base, document, queue_ends, lane_movements):
        self.base, self.document, self.queue_ends = base, document, queue_ends
        self.nodes, self.links = base.nodes, base.links
        self.boundary_document = base.boundary_document
        self.interior = set(base.eligible_links)
        self.successors = base.successors
        self.lane_movements = lane_movements
        self.sequences = SequenceContract()
        self.classification, self.crossing_m = {}, {}
        for key, link in self.links.items():
            if ('car' not in link.get('modes', []) or link.get('car_access', 'yes') not in ('yes', 'designated', 'permissive') or
                    any(not math.isfinite(link.get(k, 0)) or link.get(k, 0) <= 0
                        for k in ('length', 'lanes', 'capacity', 'freespeed'))):
                continue
            path = link['path']; intervals = base.polygon.path_intervals(path)
            start = base.polygon.contains(path[0], False); end = base.polygon.contains(path[-1], False)
            if key in self.interior:
                self.classification[key] = 'interior'
            elif not intervals and not base.polygon.contains(path[0]) and not base.polygon.contains(path[-1]):
                self.classification[key] = 'external_connected_candidate'
            elif len(intervals) == 1 and start != end:
                low, high = intervals[0]
                role = 'entry_crossing' if end and not base.polygon.contains(path[0]) else (
                    'exit_crossing' if start and not base.polygon.contains(path[-1]) else None)
                if role and (end and high >= len(path)-1-EPS or start and low <= EPS):
                    self.classification[key] = role
                    cut = low if end else high
                    metric = link.get('metric_path', path)  # Direct constructors are synthetic fixtures.
                    lengths = [math.dist(a, b) for a, b in zip(metric, metric[1:])]
                    i = min(int(cut), len(lengths)-1)
                    self.crossing_m[key] = link['length'] * (sum(lengths[:i]) + lengths[i]*(cut-i)) / sum(lengths)
        self.entry_gateways = self._gateways(document.get('entry_gateways', []), 'entry')
        self.exit_gateways = self._gateways(document.get('exit_gateways', []), 'exit')
        self.sites = {}
        for row in document.get('internal_origins', []):
            key = row.get('link_id')
            if key in self.sites or key not in self.interior:
                raise ValueError('Invalid/duplicate interior origin: ' + str(key))
            self._incorporation(row, key)
            self.sites[key] = dict(row)
        if not self.sites:
            raise ValueError('No verified interior incorporation sites; connectors are not implicit origins')
        self.internal_links = sorted(self.interior - set(base.entry_gateways) - set(base.exit_gateways))
        # Boundary-adjacent full interior links can be observation points but
        # not anonymous internal endpoints in this contract.
        if set(self.sites)-set(self.internal_links):
            raise ValueError('Interior origin is a gateway observation/proxy link')
        self.eligible_links = self.interior | {key for table in (self.entry_gateways, self.exit_gateways)
                                              for row in table.values() for key in row['link_ids']}
        self.summary = dict(schema_version=2, mode=VARIANT, origin_policy=ORIGIN_POLICY,
            boundary=base.polygon.geometry, allowed_links=sorted(self.eligible_links),
            internal_links=self.internal_links, internal_origins=self.sites,
            entry_gateways=self.entry_gateways, exit_gateways=self.exit_gateways,
            access_version=document.get('review', {}).get('version'),
            sequence_contract_version=1, sequence_contract_sha256=SEQUENCE_SHA256,
            perimeter_provenance=document.get('perimeter'), routing_scope='per_private_trip_validation; no_global_whitelist',
            gateway_semantics='real_crossing + interior_observation + existing_external_boundary_anchor',
            exterior_network_modeled='only_explicit_existing_anchor_chains', door_to_door_available=False,
            scope='observed_z1_and_declared_anchors_only', empirical_calibration=False)

    def _incorporation(self, row, key):
        evidence(row.get('review'), 'Incorporation ' + key)
        useful, rate = row.get('useful_length_m'), row.get('incorporation_capacity_pcu_h')
        if (type(useful) not in (int, float) or not math.isfinite(useful) or not 0 < useful <= min(self.links[key]['length'], self.queue_ends[key]) or
                type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate <= self.links[key]['capacity']):
            raise ValueError('Useful storage/incorporation capacity exceeds physical link or is missing: ' + key)
        if not row.get('capacity_basis') or row.get('activity_allowed') is not True:
            raise ValueError('Reviewed activity access/capacity basis required: ' + key)

    def _gateways(self, rows, role):
        table, identifiers, crossings = {}, set(), set()
        if not isinstance(rows, list):
            raise ValueError('Gateway catalogue must contain explicit lists')
        for row in rows:
            evidence(row.get('review'), role + ' gateway')
            name, path = row.get('id'), row.get('link_ids')
            if not name or name in identifiers or not isinstance(path, list) or len(path) < 3 or len(set(path)) != len(path):
                raise ValueError('Missing/duplicate gateway or invalid anchor chain')
            identifiers.add(name)
            anchor = path[0] if role == 'entry' else path[-1]
            observation = path[-1] if role == 'entry' else path[0]
            crossing = row.get('crossing_link')
            if crossing in crossings:
                raise ValueError('Duplicate physical gateway crossing: ' + str(crossing))
            crossings.add(crossing)
            if (anchor in table or row.get('anchor_link') != anchor or row.get('observation_link') != observation or
                    crossing not in path or self.classification.get(anchor) != 'external_connected_candidate' or
                    self.classification.get(observation) != 'interior'):
                raise ValueError('A gateway requires a real crossing, interior observation and existing external anchor')
            at = path.index(crossing)
            expected = (['external_connected_candidate']*at + ['entry_crossing'] + ['interior']*(len(path)-at-1)
                        if role == 'entry' else ['interior']*at + ['exit_crossing'] + ['external_connected_candidate']*(len(path)-at-1))
            if [self.classification.get(k) for k in path] != expected:
                raise ValueError('Gateway chain crosses/reenters incorrectly or uses an interior proxy as exterior')
            self.validate_route(path)
            outside = path[:at] if role == 'entry' else path[at+1:]
            if sum(self.links[k]['length'] for k in outside) > MAX_EXTERNAL_ANCHOR_M:
                raise ValueError('External anchors exceed the existing bounded 250m policy')
            # Boundary sources/sinks are synthetic flow conditions, not parking
            # activities. In particular a sink has no incorporation permission.
            useful, rate = row.get('useful_length_m'), boundary_rate(row, role)
            if (row.get('flow_role', 'boundary_' + role) != 'boundary_' + role or
                    not row.get('capacity_basis') or
                    type(useful) not in (int, float) or not math.isfinite(useful) or
                    not 0 < useful <= min(self.links[anchor]['length'], self.queue_ends[anchor]) or
                    type(rate) not in (int, float) or not math.isfinite(rate) or
                    not 0 < rate <= min(self.links[k]['capacity'] for k in path)):
                raise ValueError('Reviewed boundary storage/flow budget exceeds chain capacity or is missing: ' + anchor)
            crossing_at = sum(self.links[k]['length'] for k in path[:at]) + self.crossing_m[crossing]
            if role == 'entry' and self.queue_ends[anchor] > crossing_at+1e-8:
                raise ValueError('Native origin queue already passes the perimeter')
            table[anchor] = dict(row, evidence_crossing_links=[crossing], crossing_distance_m=crossing_at,
                                 role=role, arrival_requires_native_ledger_lower_bound=role == 'exit')
        return table

    def validate_route(self, path):
        if not path or any(k not in self.classification for k in path):
            raise ValueError('Route uses unavailable or inaccessible directed link')
        for a, b in zip(path, path[1:]):
            if (self.links[a]['to_node'] != self.links[b]['from_node'] or
                    a in self.lane_movements and b not in self.lane_movements[a]):
                raise ValueError('Disconnected route or forbidden lane direction: ' + a + ' -> ' + b)
        self.sequences.validate(path)

    @lru_cache(maxsize=128)
    def _tree(self, origin, prefix=()):
        progress = self.sequences.progress(prefix or (origin,))
        if progress is None or prefix and prefix[-1] != origin:
            raise ValueError('Illegal or mismatched routing prefix')
        initial = (origin, progress, (origin,) if origin in self.sequences.via_links else ())
        distance, previous, queue = {initial: 0.}, {}, [(0., initial)]
        while queue:
            cost, state = heapq.heappop(queue)
            if cost != distance[state]:
                continue
            current, progress, visited_vias = state
            for target in self.successors[current]:
                next_progress = self.sequences.advance(progress, target)
                if next_progress is None:
                    continue
                if target in visited_vias:
                    continue  # Do not clear sequence history by circling through a via.
                next_vias = tuple(sorted((*visited_vias, target))) if target in self.sequences.via_links else visited_vias
                target_state = (target, next_progress, next_vias)
                score = cost + self.links[target]['length']/self.links[target]['freespeed']
                if score < distance.get(target_state, math.inf):
                    distance[target_state], previous[target_state] = score, state
                    heapq.heappush(queue, (score, target_state))
        return distance, previous

    def route(self, origin, destination):
        first, last = self.entry_gateways.get(origin), self.exit_gateways.get(destination)
        a = first['observation_link'] if first else origin
        b = last['observation_link'] if last else destination
        prefix = tuple(first['link_ids']) if first else (a,)
        tail = last['link_ids'][1:] if last else []
        distance, previous = self._tree(a, prefix)
        arrivals = [state for state in distance if state[0] == b
                    and self.sequences.progress(tail, state[1]) is not None]
        if not arrivals:
            raise ValueError('Inaccessible destination respecting directed lane movements')
        state = min(arrivals, key=lambda s: (distance[s], s))
        path = [state[0]]
        while state in previous:
            state = previous[state]
            path.append(state[0])
        path.reverse()
        result = (first['link_ids'][:-1] if first else []) + path + (last['link_ids'][1:] if last else [])
        self.validate_route(result)
        return result

    def exit_clearance(self, key, body):
        row = self.exit_gateways[key]; path = row['link_ids']
        crossing_relative = row['crossing_distance_m'] - sum(self.links[k]['length'] for k in path[:-1])
        return self.queue_ends[key] - body - GAP_M - crossing_relative

    @lru_cache(maxsize=4096)
    def candidates(self, origin, kind, body):
        return tuple(self.iter_candidates(origin, kind, body))

    def iter_candidates(self, origin, kind, body):
        first = self.entry_gateways.get(origin)
        a = first['observation_link'] if first else origin
        destinations = self.exit_gateways if kind.endswith('external') else self.internal_links
        for key in destinations:
            last = self.exit_gateways.get(key); b = last['observation_link'] if last else key
            if key == origin or not self.base.reachable(a, b):
                continue
            if last and self.exit_clearance(key, body) < -1e-8:
                continue
            if not last and self.queue_ends[key]+1e-8 < body+GAP_M:
                continue  # A short connector stays routable, not a terminal stop.
            try:
                route = self.route(origin, key)
            except ValueError as error:
                if str(error) != 'Inaccessible destination respecting directed lane movements':
                    raise
                continue
            if first and last:
                if (first['id'] == last['id'] or first['crossing_link'] == last['crossing_link'] or
                        self.links[first['crossing_link']]['to_node'] == self.links[last['crossing_link']]['from_node']):
                    continue
                if not set(route) & set(self.internal_links):
                    continue
            yield key

    @lru_cache(maxsize=32)
    def origins(self, kind, body=4.5):
        rows = self.entry_gateways if kind.startswith('external') else self.sites
        return tuple(key for key in sorted(rows)
                     if min(rows[key]['useful_length_m'], self.queue_ends[key])+1e-8 >= body+GAP_M
                     and self.candidates(key, kind, body))

    def validate_shares(self, shares):
        for kind, share in shares.items():
            if share and not self.origins(kind):
                raise ValueError('No verified connected origin/exit with whole-body clearance for ' + kind +
                                 '; check exterior links separately from the perimeter GeoJSON')

    def sample(self, rng, kind, body=4.5):
        origins = self.origins(kind, body)
        if not origins:
            raise ValueError('No accessible incorporation site for ' + kind)
        rows = self.entry_gateways if kind.startswith('external') else self.sites
        weights = [rows[k]['useful_length_m']*self.links[k]['lanes'] for k in origins]
        origin = rng.choices(origins, weights=weights, k=1)[0]
        destinations = self.candidates(origin, kind, body)
        destination = rng.choices(destinations, weights=[self.links[k]['length']*self.links[k]['lanes'] for k in destinations], k=1)[0]
        first, last = self.entry_gateways.get(origin), self.exit_gateways.get(destination)
        path = self.route(origin, destination)
        return dict(od_type=kind, od_class=CLASS_BY_TYPE[kind], origin_link=origin, destination_link=destination,
            origin_xy=self.nodes[self.links[origin]['from_node']], destination_xy=self.nodes[self.links[destination]['to_node']],
            origin_gateway=origin if first else None, destination_gateway=destination if last else None,
            origin_zone=first['id'] if first else None, destination_zone=last['id'] if last else None,
            scope='observed_z1_and_declared_anchors_only', door_to_door_seconds=None, metadata_source=METADATA_SCHEMA,
            route_link_ids=path, body_length_m=body, minimum_gap_m=GAP_M,
            entry_crossing_link=first['crossing_link'] if first else None,
            exit_crossing_link=last['crossing_link'] if last else None,
            origin_observation_link=first['observation_link'] if first else None,
            destination_observation_link=last['observation_link'] if last else None)

    @lru_cache(maxsize=8192)
    def temporal_route(self, origin, destination, body, maximum_speed):
        from simz1_temporal_passage import repair_route
        return repair_route(self, origin, destination, body, maximum_speed)

    def validate_metadata(self, record, maximum_speed=None):
        required = {'od_type','od_class','origin_link','destination_link','origin_gateway','destination_gateway',
            'origin_zone','destination_zone','scope','door_to_door_seconds','metadata_source','route_link_ids',
            'body_length_m','minimum_gap_m','entry_crossing_link','exit_crossing_link',
            'origin_observation_link','destination_observation_link'}
        if not isinstance(record, dict) or set(record) != required or record.get('od_type') not in LEGACY:
            raise ValueError('Incomplete private gateway metadata')
        kind, origin, destination = record['od_type'], record['origin_link'], record['destination_link']
        body = record['body_length_m']
        if type(body) not in (int, float) or not math.isfinite(body) or body <= 0:
            raise ValueError('Invalid private body')
        if (origin not in self.origins(kind, body) or destination not in self.candidates(origin, kind, body) or
                record['od_class'] != CLASS_BY_TYPE[kind] or record['minimum_gap_m'] != GAP_M or
                record['scope'] != 'observed_z1_and_declared_anchors_only' or record['door_to_door_seconds'] is not None or
                record['metadata_source'] != METADATA_SCHEMA or record['route_link_ids'] != (
                    self.route(origin, destination) if maximum_speed is None else self.temporal_route(origin, destination, body, maximum_speed))):
            raise ValueError('Private route/class/scope differs from verified OD contract')
        for side, role, table in (('origin', 'entry', self.entry_gateways), ('destination', 'exit', self.exit_gateways)):
            row = table.get(record[side+'_link'])
            expected = {side+'_gateway': record[side+'_link'] if row else None,
                        side+'_zone': row['id'] if row else None, role+'_crossing_link': row['crossing_link'] if row else None,
                        side+'_observation_link': row['observation_link'] if row else None}
            if any(record[k] != v for k, v in expected.items()):
                raise ValueError('Interior observation is not a real exterior gateway')
        return record


class IncorporationBudget:
    """Documented scheduled PCU/hour upper bounds, no time shifting or quota cut."""
    def __init__(self, model, factor=1.):
        from simz1_od_policy import GatewayBudget
        self.gateway = GatewayBudget(model, factor)
        self.model, self.factor = model, factor
        self.used = defaultdict(float)
        self.rejected = Counter()

    def accept(self, record, hour, pcu):
        origin = record['origin_link']
        row = self.model.entry_gateways.get(origin) or self.model.sites[origin]
        rate = boundary_rate(row, 'entry') if origin in self.model.entry_gateways else row['incorporation_capacity_pcu_h']
        limit = rate*self.factor
        if self.used[hour, origin]+pcu > limit+1e-9:
            self.rejected['incorporation_capacity'] += 1
            return False
        # Include reviewed exit handling limits as well as native gateway/link
        # capacities. Exit time is unknown; this is a departure-cohort budget.
        destination = record['destination_gateway']
        if destination:
            limit_out = boundary_rate(self.model.exit_gateways[destination], 'exit')*self.factor
            if self.used[hour, 'exit:'+destination]+pcu > limit_out+1e-9:
                self.rejected['exit_cohort_capacity'] += 1
                return False
        if not self.gateway.accept(record, hour, pcu):
            self.rejected['gateway_link_capacity'] += 1
            return False
        self.used[hour, origin] += pcu
        if destination:
            self.used[hour, 'exit:'+destination] += pcu
        return True

    def summary(self):
        return dict(self.gateway.summary(), incorporation_policy=ORIGIN_POLICY,
                    rejected_pair_attempts=dict(self.rejected),
                    incorporation_usage=[dict(hour=h, resource=k, scheduled_pcu=v) for (h,k),v in sorted(self.used.items())],
                    limitation='Private scheduled load only; service routes unchanged; shared observed queues are not predicted')


def demand_report(model, composition, spatial, origin_counts, histogram, seed, buses=None):
    bins = Counter()
    for key, number in origin_counts.items():
        length = model.links[key]['length']
        bins[next(label for limit, label in ((2.1,'<2.1'),(4.5,'2.1..<4.5'),(10,'4.5..<10'),(20,'10..<20'),(math.inf,'>=20')) if length < limit)] += number
    return dict(schema_version=VARIANT, requested_non_public=composition['total_non_public_vehicles'],
        family_counts=composition['family_counts'], private_vehicles=composition['private_vehicles'],
        freight_vehicles=composition['freight_vehicles'], buses_additional=buses,
        private_class_counts=spatial['realized_class_counts'], configured_class_percentages=spatial['hypothesis']['percentages'],
        realized_class_percentages={k:100*v/composition['private_vehicles'] if composition['private_vehicles'] else 0 for k,v in spatial['realized_class_counts'].items()},
        gateway_entries=spatial['scheduled_gateway_entries'], gateway_exits=spatial['scheduled_gateway_exits'],
        origins_by_link_length=dict(bins), top_20_origins=[dict(link_id=k, count=v, length_m=model.links[k]['length'],
            role='external_anchor' if k in model.entry_gateways else 'reviewed_internal_origin') for k,v in origin_counts.most_common(20)],
        private_departures_by_hour=histogram, disconnected_routes=0, inaccessible_destinations=0,
        capacity_rejections=spatial['gateway_capacity']['rejected_pair_attempts'],
        integrity=model.summary, seed=seed, origin_policy=ORIGIN_POLICY,
        status='scheduled_input_only; QSim not observed',
        observed=dict(inserted=None, completed=None, waiting_to_insert=None, circulating=None, not_arrived=None),
        limitations=['Synthetic configurable OD percentages, not measured traffic counts.',
                     'Catalog departure samples preserved per person; no class-specific time reshaping.',
                     'Observation covers modeled interior and declared exterior anchors, never door-to-door time.',
                     'Gateway PCU budgets are upper bounds; no guarantee of actual insertion or discharge.',
                     'A finished simulation clock is not an arrival. Native body clearance required.'])
