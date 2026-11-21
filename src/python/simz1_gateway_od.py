"""Explicit, synthetic gateway OD on existing interior links; never an exterior network.

A gateway is an existing interior link incident to a polygon boundary node or
to the interior endpoint of a verified crossing link. Crossing links themselves
are excluded from the simulated domain. These are interior proxies, not a claim
that departure/arrival occurred on the administrative boundary.
"""
from collections import defaultdict, deque
from bisect import bisect_left
from functools import lru_cache
import gzip
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from simz1_od_policy import CLASS_BY_TYPE, CONTRACT

OD_TYPES = ('external-external', 'external-internal', 'internal-external', 'internal-internal')
EPS = 1e-12
METADATA_KEYS = {'od_type', 'origin_link', 'destination_link', 'origin_gateway', 'destination_gateway',
                 'origin_zone', 'destination_zone', 'scope', 'door_to_door_seconds', 'metadata_source'}


def normalize_shares(raw=None):
    try:
        if isinstance(raw, dict) and set(raw) != set(OD_TYPES):
            raise ValueError()
        values = ([1, 0, 0, 0] if raw is None else
                  [raw[k] for k in OD_TYPES] if isinstance(raw, dict) else
                  raw.split(',') if isinstance(raw, str) else list(raw))
        if len(values) != 4 or any(isinstance(v, bool) for v in values):
            raise ValueError()
        values = [float(v) for v in values]
        total = math.fsum(values)
        if any(not math.isfinite(v) or v < 0 for v in values) or not math.isfinite(total) or total <= 0:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('--od-shares requiere cuatro pesos finitos no negativos, con suma positiva: EE,EI,IE,II') from None
    return dict(zip(OD_TYPES, (v / total for v in values)))


def _cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def _sub(a, b):
    return (a[0]-b[0], a[1]-b[1])


def _on(a, b, p):
    return (abs(_cross(_sub(b, a), _sub(p, a))) <= EPS and
            min(a[0], b[0])-EPS <= p[0] <= max(a[0], b[0])+EPS and
            min(a[1], b[1])-EPS <= p[1] <= max(a[1], b[1])+EPS)


def _cuts(a, b, c, d):
    r, s, q = _sub(b, a), _sub(d, c), _sub(c, a)
    denominator = _cross(r, s)
    if abs(denominator) > EPS:
        t, u = _cross(q, s)/denominator, _cross(q, r)/denominator
        return [max(0., min(1., t))] if -EPS <= t <= 1+EPS and -EPS <= u <= 1+EPS else []
    if abs(_cross(q, r)) > EPS:
        return []
    squared = r[0]*r[0]+r[1]*r[1]
    if squared <= EPS*EPS:
        return [0.] if _on(c, d, a) else []
    t = [(p[0]-a[0])*r[0]/squared+(p[1]-a[1])*r[1]/squared for p in (c, d)]
    low, high = max(0., min(t)), min(1., max(t))
    return [low, high] if low <= high+EPS else []


def _in_ring(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y) and x < a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]):
            inside = not inside
    return inside


class Polygon:
    """One simple Polygon with optional disjoint holes, in a common coordinate system."""
    def __init__(self, geometry):
        if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
            raise ValueError('Se requiere un unico GeoJSON Polygon explicito; no se infiere del bbox OSM')
        self.rings = []
        for raw in geometry.get('coordinates', []):
            if not isinstance(raw, (list, tuple)) or len(raw) < 4:
                raise ValueError('Anillo de poligono incompleto')
            ring = []
            for point in raw:
                if (not isinstance(point, (list, tuple)) or len(point) != 2 or
                        any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)):
                    raise ValueError('Coordenadas de poligono invalidas')
                ring.append(tuple(point))
            if ring[0] != ring[-1] or len(set(ring[:-1])) != len(ring)-1:
                raise ValueError('Anillo no cerrado o con vertices duplicados')
            edges = list(zip(ring, ring[1:]))
            if abs(sum(_cross(a, b) for a, b in edges)) <= EPS:
                raise ValueError('Poligono sin area')
            for i, (a, b) in enumerate(edges):
                for j in range(i+1, len(edges)):
                    if j == i+1 or i == 0 and j == len(edges)-1:
                        continue
                    if _cuts(a, b, *edges[j]):
                        raise ValueError('Poligono autointersectado')
            self.rings.append(ring)
        if not self.rings:
            raise ValueError('Poligono vacio')
        self.edges = [(a, b) for ring in self.rings for a, b in zip(ring, ring[1:])]
        for i, ring in enumerate(self.rings[1:], 1):
            if not _in_ring(ring[0], self.rings[0]):
                raise ValueError('Hueco fuera del poligono')
            for previous in self.rings[:i]:
                if any(_cuts(a, b, c, d) for a, b in zip(ring, ring[1:]) for c, d in zip(previous, previous[1:])):
                    raise ValueError('Anillos se tocan o cruzan')
            if any(_in_ring(ring[0], other) or _in_ring(other[0], ring) for other in self.rings[1:i]):
                raise ValueError('Huecos superpuestos')
        self.geometry = dict(type='Polygon', coordinates=[[list(p) for p in ring] for ring in self.rings])

    def contains(self, point, include_boundary=True):
        if any(_on(a, b, point) for a, b in self.edges):
            return include_boundary
        return _in_ring(point, self.rings[0]) and not any(_in_ring(point, ring) for ring in self.rings[1:])

    def clip_segment(self, a, b):
        cuts = sorted({0., 1., *(t for c, d in self.edges for t in _cuts(a, b, c, d))})
        result = []
        for low, high in zip(cuts, cuts[1:]):
            if high-low <= EPS:
                continue
            t = (low+high)/2
            if self.contains([a[i]+(b[i]-a[i])*t for i in (0, 1)]):
                if result and low-result[-1][1] <= EPS:
                    result[-1][1] = high
                else:
                    result.append([low, high])
        return result

    def path_intervals(self, path):
        result = []
        for i, (a, b) in enumerate(zip(path, path[1:])):
            for low, high in self.clip_segment(a, b):
                low, high = i+low, i+high
                if result and low-result[-1][1] <= EPS:
                    result[-1][1] = high
                else:
                    result.append([low, high])
        return result


def boundary_geometry(document):
    if not isinstance(document, dict) or document.get('crs') is not None:
        raise ValueError('GeoJSON debe usar coordenadas lon/lat WGS84 (RFC7946), sin CRS alternativo')
    geometry = document
    if document.get('type') == 'FeatureCollection':
        if not isinstance(document.get('features'), list) or len(document['features']) != 1:
            raise ValueError('Seleccione exactamente un poligono de Zona 1')
        geometry = document['features'][0]
    if not isinstance(geometry, dict) or geometry.get('crs') is not None:
        raise ValueError('Feature GeoJSON invalido o con CRS alternativo')
    if geometry.get('type') == 'Feature':
        geometry = geometry.get('geometry')
    if not isinstance(geometry, dict) or geometry.get('crs') is not None:
        raise ValueError('Geometria GeoJSON invalida o con CRS alternativo')
    polygon = Polygon(geometry)
    if any(not -180 <= x <= 180 or not -90 <= y <= 90 for ring in polygon.rings for x, y in ring):
        raise ValueError('Coordenadas GeoJSON fuera de lon/lat WGS84')
    return polygon.geometry


class GatewayModel:
    def __init__(self, nodes, links, boundary, coordinates=None, lane_movements=None):
        self.nodes, self.links = nodes, links
        coordinates = nodes if coordinates is None else coordinates
        for mapping in (nodes, coordinates):
            if (set(mapping) != set(nodes) or any(not isinstance(k, str) or not k for k in mapping) or
                    any(not isinstance(p, (list, tuple)) or len(p) != 2 or
                        any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
                        for p in mapping.values())):
                raise ValueError('Nodos/coordenadas nativos o geograficos invalidos')
        self.polygon = Polygon(boundary)
        self.boundary_document = self.polygon.geometry
        self.eligible_links = set()
        entering, leaving = defaultdict(list), defaultdict(list)
        paths = {}
        for ident, link in links.items():
            if not isinstance(ident, str) or not ident or any(c.isspace() for c in ident):
                raise ValueError('ID de enlace incompatible con whitelist explicita')
            if 'car' not in link.get('modes', ['car']):
                continue
            if link.get('car_access', 'yes') not in ('yes', 'designated', 'permissive'):
                continue
            # Programmatic legacy fixtures may omit physics; file-backed models
            # always provide it. A zero/invalid-capacity link is never a gateway.
            if any(not math.isfinite(link[k]) or link[k] <= 0
                   for k in ('capacity', 'freespeed', 'lanes') if k in link):
                continue
            a, b = link['from_node'], link['to_node']
            if a not in nodes or b not in nodes:
                raise ValueError('Enlace con nodo inexistente')
            path = link.get('path', [coordinates[a], coordinates[b]])
            if (len(path) < 2 or tuple(path[0]) != tuple(coordinates[a]) or
                    tuple(path[-1]) != tuple(coordinates[b])):
                raise ValueError('Geometria de enlace no coincide con nodos dirigidos')
            if any(len(p) != 2 or any(not math.isfinite(v) for v in p) for p in path):
                raise ValueError('Geometria de enlace invalida')
            if all(math.dist(a, b) <= EPS for a, b in zip(path, path[1:])):
                raise ValueError('Enlace sin geometria longitudinal')
            paths[ident] = path
            intervals = self.polygon.path_intervals(path)
            end = len(path)-1
            whole = len(intervals) == 1 and intervals[0][0] <= EPS and intervals[0][1] >= end-EPS
            has_interior = any(self.polygon.contains([(a[i]+b[i])/2 for i in (0, 1)], False) for a, b in zip(path, path[1:]))
            if whole and has_interior:
                self.eligible_links.add(ident)
            elif len(intervals) == 1:
                low, high = intervals[0]
                if not self.polygon.contains(path[0]) and self.polygon.contains(path[-1], False) and high >= end-EPS:
                    entering[b].append(ident)
                if self.polygon.contains(path[0], False) and not self.polygon.contains(path[-1]) and low <= EPS:
                    leaving[a].append(ident)
        if not self.eligible_links:
            raise ValueError('El poligono no contiene enlaces car completos; no se modifica ni amplía la red')
        self.entry_gateways, self.exit_gateways = {}, {}
        outgoing = defaultdict(set)
        for ident in sorted(self.eligible_links):
            link = links[ident]
            outgoing[link['from_node']].add(ident)
            for table, node, evidence in ((self.entry_gateways, link['from_node'], entering),
                                          (self.exit_gateways, link['to_node'], leaving)):
                boundary_node = self.polygon.contains(coordinates[node]) and not self.polygon.contains(coordinates[node], False)
                crossing = [edge for edge in evidence[node] if lane_movements is None or
                    (ident in lane_movements.get(edge, {ident}) if table is self.entry_gateways else
                     edge in lane_movements.get(ident, {edge}))]
                if boundary_node or crossing:
                    table[ident] = dict(link_id=ident, node_id=node, evidence_crossing_links=sorted(crossing),
                        kind='boundary_node' if boundary_node else 'interior_proxy_adjacent_to_crossing')
        self.internal_links = sorted(self.eligible_links-set(self.entry_gateways)-set(self.exit_gateways))
        self.successors = {}
        for ident in sorted(self.eligible_links):
            possible = outgoing[links[ident]['to_node']]
            if lane_movements is not None and ident in lane_movements:
                possible = possible & set(lane_movements[ident])
            self.successors[ident] = sorted(possible)
        # Components over LINK movements, not a node SCC that silently ignores turns.
        from prepare_simz1 import components
        edges = [dict(**{'from': a, 'to': b}) for a, targets in self.successors.items() for b in [a, *targets]]
        groups = components(edges)
        self.component = {link: i for i, group in enumerate(groups) for link in group}
        graph = {i: set() for i in range(len(groups))}
        indegree = dict.fromkeys(graph, 0)
        for a, targets in self.successors.items():
            for b in targets:
                x, y = self.component[a], self.component[b]
                if x != y and y not in graph[x]:
                    graph[x].add(y); indegree[y] += 1
        queue = deque(sorted(i for i in graph if not indegree[i])); order = []
        while queue:
            current = queue.popleft(); order.append(current)
            for target in sorted(graph[current]):
                indegree[target] -= 1
                if not indegree[target]: queue.append(target)
        self.reach = {}
        for current in reversed(order):
            mask = 1 << current
            for target in graph[current]: mask |= self.reach[target]
            self.reach[current] = mask
        self.summary = dict(schema_version=1, mode='gateway-od', boundary=self.polygon.geometry,
            allowed_links=sorted(self.eligible_links), internal_links=self.internal_links,
            entry_gateways=self.entry_gateways, exit_gateways=self.exit_gateways,
            route_domain='existing_complete_interior_car_links', boundary_source='explicit_user_geojson',
            gateway_semantics='existing_interior_proxy; not an observed exterior trip or exact boundary time',
            movement_scope='configured_directed_links_and_lane_movements; unimported_OSM_restrictions_not_inferred',
            exterior_network_modeled=False, door_to_door_available=False)
        self._validation = dict(self.summary, allowed_links=self.eligible_links,
                                internal_links=set(self.internal_links))

    @lru_cache(maxsize=None)
    def through_destinations(self, origin):
        """All permitted routes for these pairs must visit a non-gateway link.

        This conservative subset keeps the guarantee under ordinary MATSim and
        within-day rerouting, without imposing a waypoint or changing physics.
        Only the small gateway-only graph is searched once per entry.
        """
        gateway_links = set(self.entry_gateways) | set(self.exit_gateways)
        seen, queue = {origin}, deque([origin])
        while queue:
            for target in self.successors[queue.popleft()]:
                if target in gateway_links and target not in seen:
                    seen.add(target); queue.append(target)
        node = self.entry_gateways[origin]['node_id']
        return tuple(d for d in self.destinations(self.component[origin], 'external-external')
                     if d not in seen and self.exit_gateways[d]['node_id'] != node)

    def reachable(self, origin, destination):
        return (origin in self.component and destination in self.component and
                bool(self.reach[self.component[origin]] & (1 << self.component[destination])))

    def pools(self, od_type):
        if od_type not in OD_TYPES:
            raise ValueError('Tipo OD desconocido')
        a, b = od_type.split('-')
        return (sorted(self.entry_gateways) if a == 'external' else self.internal_links,
                sorted(self.exit_gateways) if b == 'external' else self.internal_links)

    @lru_cache(maxsize=None)
    def destinations(self, component, od_type):
        return tuple(d for d in self.pools(od_type)[1] if self.reach[component] & (1 << self.component[d]))

    @lru_cache(maxsize=4)
    def origins(self, od_type):
        return tuple(o for o in self.pools(od_type)[0] if
                     (bool(self.through_destinations(o)) if od_type == 'external-external' else
                      any(d != o for d in self.destinations(self.component[o], od_type))))

    def validate_shares(self, shares):
        for kind, fraction in normalize_shares(shares).items():
            if fraction and not self.origins(kind):
                raise ValueError(f'No hay par OD distinto y alcanzable para {kind}; no se inventan gateways')

    def sample(self, rng, od_type):
        origins = self.origins(od_type)
        if not origins:
            raise ValueError(f'Gateway imposible: {od_type}')
        origin = rng.choice(origins)
        candidates = (self.through_destinations(origin) if od_type == 'external-external' else
                      self.destinations(self.component[origin], od_type))
        # Skip self in O(log n), without rebuilding a thousands-link list per person.
        position = bisect_left(candidates, origin)
        skip = position < len(candidates) and candidates[position] == origin
        index = rng.randrange(len(candidates) - int(skip))
        destination = candidates[index + int(skip and index >= position)]
        external_origin, external_destination = (v == 'external' for v in od_type.split('-'))
        return dict(od_type=od_type, origin_link=origin, destination_link=destination,
            origin_xy=self.nodes[self.links[origin]['from_node']], destination_xy=self.nodes[self.links[destination]['to_node']],
            origin_gateway=origin if external_origin else None, destination_gateway=destination if external_destination else None,
            origin_zone=f'synthetic-exterior-entry:{origin}' if external_origin else None,
            destination_zone=f'synthetic-exterior-exit:{destination}' if external_destination else None,
            scope='observed_z1_only', door_to_door_seconds=None, metadata_source='synthetic_gateway_od')

    def validate_metadata(self, record):
        self._validation['od_contract'] = self.summary.get('od_contract')
        validate_od_metadata(record, self._validation)
        if not self.reachable(record['origin_link'], record['destination_link']):
            raise ValueError('OD no alcanzable respetando sentidos y giros configurados')
        if record.get('od_class') == 'EXTERNAL_EXTERNAL_THROUGH' and record['destination_link'] not in self.through_destinations(record['origin_link']):
            raise ValueError('Viaje de paso no garantiza recorrido interior y accesos distintos durante reruteo')
        return record


def validate_od_metadata(record, spatial, *, person_id=None):
    if spatial.get('mode')=='balanced-gateway-v1':
        # Metadata is bound to this person's pinned initial plan. Replanned
        # routes remain native results and never replace the original OD.
        import hashlib
        proofs=getattr(spatial,'metadata_hashes',None)
        if proofs is None or person_id not in proofs:
            raise ValueError('Balanced replay metadata lacks verified person identity')
        actual=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if actual!=proofs[person_id]:raise ValueError('Balanced replay OD differs from the pinned native person')
        return record
    if not isinstance(record, dict) or set(record) not in (METADATA_KEYS, METADATA_KEYS | {'od_class'}) or record.get('od_type') not in OD_TYPES:
        raise ValueError('Metadatos OD espaciales incompletos o con coordenadas/campos exteriores no admitidos')
    if ('od_class' in record and record['od_class'] != CLASS_BY_TYPE[record['od_type']] or
            spatial.get('od_contract') == CONTRACT and 'od_class' not in record):
        raise ValueError('Clase OD explicita incompatible con el contrato')
    if (record['scope'] != 'observed_z1_only' or record['metadata_source'] != 'synthetic_gateway_od' or
            record['door_to_door_seconds'] is not None or record['origin_link'] == record['destination_link']):
        raise ValueError('Alcance OD o tiempo exterior invalido')
    if any(not isinstance(record[side+'_link'], str) for side in ('origin', 'destination')):
        raise ValueError('Enlaces OD invalidos')
    for side, kind in zip(('origin', 'destination'), record['od_type'].split('-')):
        link = record[side+'_link']
        if link not in spatial['allowed_links']:
            raise ValueError('OD fuera del dominio interior validado')
        if kind == 'external':
            role = 'entry' if side == 'origin' else 'exit'
            if (record[side+'_gateway'] != link or link not in spatial[role+'_gateways'] or
                    record[side+'_zone'] != f'synthetic-exterior-{role}:{link}'):
                raise ValueError('Gateway/zona exterior no corresponde al catalogo dirigido')
        elif (link not in spatial['internal_links'] or record[side+'_gateway'] is not None or record[side+'_zone'] is not None):
            raise ValueError('OD interno con metadatos exteriores')
    return record


def _xml(path):
    with (gzip.open(path, 'rb') if str(path).endswith('.gz') else open(path, 'rb')) as stream:
        root = ET.parse(stream).getroot()
    for element in root.iter(): element.tag = element.tag.rsplit('}', 1)[-1]
    return root


def load_gateway_model(network_path, boundary_path, lanes_path=None, crs='EPSG:32615'):
    if crs != 'EPSG:32615':
        raise ValueError('Gateway OD requiere CRS de red explicito EPSG:32615; no se adivina la proyeccion')
    from pyproj import Transformer
    from simz1_visual_lanes import _path
    from simz1_osm_turn_audit import load_lanes
    raw = Path(boundary_path).read_bytes()
    document = json.loads(raw)
    boundary = boundary_geometry(document)
    transform = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    root = _xml(network_path)
    period = root.find('links').get('capperiod', '01:00:00')
    if period not in ('01:00:00', '1:00:00', '3600', '3600.0'):
        raise ValueError('Gateway OD requiere capacidades horarias capperiod=01:00:00')
    nodes = {}
    for node in root.findall('nodes/node'):
        ident = node.get('id')
        if not ident or ident in nodes:
            raise ValueError('Nodo ausente o duplicado en red gateway')
        nodes[ident] = (float(node.get('x')), float(node.get('y')))
    coordinates = {ident: list(transform.transform(*xy, errcheck=True)) for ident, xy in nodes.items()}
    links = {}
    for link in root.findall('links/link'):
        ident, a, b = link.get('id'), link.get('from'), link.get('to')
        if ident in links or a not in nodes or b not in nodes:
            raise ValueError('ID duplicado o nodos ausentes en red gateway')
        attributes = {e.get('name'): e.text for e in link.findall('attributes/attribute')}
        access = next((attributes['osm:'+k] for k in ('motorcar', 'motor_vehicle', 'vehicle', 'access') if 'osm:'+k in attributes), 'yes')
        if any(k.startswith('osm:') and ':conditional' in k and any(mode in k for mode in ('access', 'motorcar', 'motor_vehicle', 'vehicle')) for k in attributes):
            raise ValueError(f'Acceso condicional requiere ruteo especifico: {ident}')
        path, source, valid = _path(attributes, coordinates[a], coordinates[b],
            lambda x, y: transform.transform(x, y, errcheck=True))
        if not valid:
            raise ValueError(f'Geometria efectiva ambigua en {ident}; no se clasifica contra el poligono')
        try:
            physics = {key: float(link.get(attribute)) for key, attribute in
                       (('capacity', 'capacity'), ('freespeed', 'freespeed'), ('lanes', 'permlanes'))}
        except (TypeError, ValueError):
            raise ValueError(f'Faltan capacidad/velocidad/carriles verificables: {ident}') from None
        links[ident] = dict(from_node=a, to_node=b, modes=link.get('modes', 'car').split(','), path=path, car_access=access,
                            length=float(link.get('length')), **physics)
    movements = {a: set(targets) for a, targets in load_lanes(lanes_path).items()} if lanes_path else None
    model = GatewayModel(nodes, links, boundary, coordinates, movements)
    model.boundary_document = document
    model.summary.update(boundary_sha256=hashlib.sha256(raw).hexdigest(), network_crs=crs)
    return model


def validated_spatial_demand(directory, manifest):
    """Verify spatial scope against fingerprinted inputs/effective config; legacy is explicit absence."""
    spatial = manifest.get('spatial_demand')
    if spatial is None:
        return None
    directory = Path(directory).resolve()
    from simz1_run import checked_path, parameters
    if isinstance(spatial,dict) and spatial.get('mode')=='balanced-gateway-v1':
        from simz1_balanced_od_audit import validate_manifest
        import hashlib
        model,records=validate_manifest(directory,manifest,postprocessing=True)
        class VerifiedSpatial(dict):pass
        result=VerifiedSpatial(spatial)
        result.metadata_hashes={ident:hashlib.sha256(json.dumps({k:v for k,v in row.items() if k!='planned_departure'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
            for ident,row in records.items()}
        result.postprocessor_version='balanced-replay-contract-v1'
        # Presentation covers the pinned native network, including service and
        # anchor links. This does not expand the private routing eligibility.
        result.update(visual_link_ids=sorted(model.links),
            visual_scope='full_native_network_preserving_anchors_and_services',
            postprocessor_contract_version=result.postprocessor_version)
        from simz1_freight_completion import observation_contract
        observation=observation_contract(manifest)
        result['observation_end_seconds']=observation['observation_end_seconds'] if observation else 86400
        return result
    if not isinstance(spatial, dict) or spatial.get('schema_version') != 1 or spatial.get('mode') != 'gateway-od':
        raise ValueError('Contrato de dominio espacial desconocido')
    boundary = checked_path(directory, manifest['inputs']['zone_boundary'])
    geometry = boundary_geometry(json.loads(boundary.read_bytes()))
    if geometry != spatial.get('boundary') or spatial.get('boundary_sha256') != manifest['inputs']['zone_boundary']['sha256']:
        raise ValueError('Poligono espacial no coincide con el insumo de esta corrida')
    config = parameters(checked_path(directory, manifest.get('effective_config', manifest['inputs']['config'])))
    if config.get('controler.enableLinkToLinkRouting', '').lower() != 'true':
        raise ValueError('gateway-od requiere controler.enableLinkToLinkRouting=true')
    allowed = spatial.get('allowed_links')
    if (not isinstance(allowed, list) or not allowed or any(not isinstance(v, str) or not v for v in allowed) or
            allowed != sorted(set(allowed)) or config.get('zona1SpatialRouting.mode') != 'gateway-od' or
            config.get('zona1SpatialRouting.allowedLinks', '').split() != allowed):
        raise ValueError('Dominio de routing distinto del dominio espacial declarado')
    network = checked_path(directory, manifest['inputs']['network'])
    configured = config.get('network.laneDefinitionsFile')
    lane_record = next((v for v in manifest['inputs'].values()
        if configured and (Path(directory)/v['path']).resolve() == (Path(directory)/configured).resolve()), None)
    if configured not in (None, '', 'null') and lane_record is None:
        raise ValueError('Carriles espaciales sin huella validada')
    model = load_gateway_model(network, boundary, checked_path(directory, lane_record) if lane_record else None,
                               config.get('global.coordinateSystem'))
    if spatial.get('od_contract') is not None:
        from simz1_od_policy import validate_osm_turns
        if spatial['od_contract'] != CONTRACT:
            raise ValueError('Contrato de cuatro clases OD desconocido')
        source = checked_path(directory, manifest['inputs']['od_source_osm'])
        audit = validate_osm_turns(source, network, checked_path(directory, lane_record) if lane_record else None)
        if audit != spatial.get('restriction_preflight'):
            raise ValueError('Restricciones espaciales incompatibles con los insumos de la corrida')
    for field in ('allowed_links', 'internal_links', 'entry_gateways', 'exit_gateways'):
        if spatial.get(field) != model.summary[field]:
            raise ValueError(f'Catalogo espacial incompatible con red/carriles: {field}')
    return dict(spatial)
