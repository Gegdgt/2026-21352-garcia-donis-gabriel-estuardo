"""Static freight-through validation against the saved OSM and native lane graph.

The OSM request bounds are a computational perimeter, not an administrative
boundary. This verifies the supplied data, not surveyed heavy-vehicle clearance,
swept paths, traffic capacity, signal timing, or successful queue drainage.
Historical weekday-v1 services do not opt into this additional contract.
"""
from collections import Counter
import hashlib
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

PRINCIPAL_CLASSES = frozenset(k + suffix for k in ('trunk', 'primary', 'secondary', 'tertiary')
                              for suffix in ('', '_link'))
ROUTE_IDS = frozenset(('west-east', 'west-east-reverse', 'south-north', 'south-north-reverse'))
PERIMETER_CONNECTOR_LIMIT_M = 250.0
BOUNDARY_TOLERANCE_DEGREES = 1e-9
_ACCESS = frozenset(('hgv', 'goods', 'motorcar', 'motor_vehicle', 'vehicle', 'access'))
_LIMITS = dict(maxweight=('gross_weight_tonnes', 't'), maxlength=('length_m', 'm'),
               maxwidth=('width_m', 'm'), maxheight=('height_m', 'm'),
               maxaxleload=('axle_load_tonnes', 't'))
_ALLOWED_ACCESS = frozenset(('yes', 'designated', 'permissive'))
_TURN_TYPES = frozenset(prefix + turn for prefix in ('no_', 'only_')
                         for turn in ('left_turn', 'right_turn', 'straight_on', 'u_turn'))


def _tags(element):
    return {t.get('k'): t.get('v') for t in element.findall('tag')}


def _attributes(element):
    return {a.get('name').removeprefix('osm:'): a.text or ''
            for a in element.findall('attributes/attribute') if a.get('name', '').startswith('osm:')}


def _positive(value, label):
    if isinstance(value, bool):
        raise ValueError('Freight invalid positive ' + label)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Freight invalid positive ' + label) from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Freight invalid positive ' + label)
    return number


def _fingerprints(path):
    raw = Path(path).read_bytes()
    lf = raw.replace(b'\r\n', b'\n')
    return {hashlib.sha256(data).hexdigest() for data in (raw, lf, lf.replace(b'\n', b'\r\n'))}


def load_context(network_path, lanes_path, osm_path):
    """Read immutable source inputs and validate structural lane reachability.

    Context is a plain dictionary; links expose from/to/length/freespeed/lanes,
    modes, way, direction and tags. lane_exits contains entry-reachable targets.
    No source file is written and no simulation is started.
    """
    root = ET.parse(network_path).getroot()
    if root.tag != 'network':
        raise ValueError('Freight expected network XML')
    nodes = {}
    for node in root.findall('nodes/node'):
        ident = node.get('id')
        if not ident or ident in nodes:
            raise ValueError('Freight missing/duplicate network node')
        x, y = float(node.get('x')), float(node.get('y'))
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Freight nonfinite network coordinates')
        nodes[ident] = dict(x=x, y=y, tags=_attributes(node))
    links = {}
    for link in root.findall('links/link'):
        ident = link.get('id')
        if not ident or ident in links or link.get('from') not in nodes or link.get('to') not in nodes:
            raise ValueError('Freight missing/duplicate link or dangling node: ' + str(ident))
        match = re.fullmatch(r'osm_(\d+)_(\d+)_(forward|backward)', ident)
        links[ident] = dict(from_node=link.get('from'), to_node=link.get('to'),
                           **{'from': link.get('from'), 'to': link.get('to')},
                           length=_positive(link.get('length'), ident+'.length'),
                           freespeed=_positive(link.get('freespeed'), ident+'.freespeed'),
                           lanes=_positive(link.get('permlanes'), ident+'.permlanes'),
                           modes=set(link.get('modes', 'car').split(',')), tags=_attributes(link),
                           way=link.get('origid') or (match[1] if match else None),
                           direction=match[3] if match else None,
                           segment=int(match[2]) if match else None)
    osm = ET.parse(osm_path).getroot()
    bounds_elements = osm.findall('bounds')
    if osm.tag != 'osm' or len(bounds_elements) != 1:
        raise ValueError('Freight requires one explicit OSM bounds perimeter')
    bounds = {key: float(bounds_elements[0].get(key)) for key in ('minlat', 'minlon', 'maxlat', 'maxlon')}
    if (not all(math.isfinite(v) for v in bounds.values()) or
            bounds['minlat'] >= bounds['maxlat'] or bounds['minlon'] >= bounds['maxlon']):
        raise ValueError('Freight invalid OSM bounds')
    osm_nodes, ways = {}, {}
    for node in osm.findall('node'):
        if node.get('action') == 'delete':
            continue
        ident = node.get('id')
        if not ident or ident in osm_nodes:
            raise ValueError('Freight missing/duplicate OSM node')
        lon, lat = float(node.get('lon')), float(node.get('lat'))
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError('Freight nonfinite OSM coordinates')
        osm_nodes[ident] = dict(lon=lon, lat=lat, tags=_tags(node))
    for way in osm.findall('way'):
        if way.get('action') == 'delete':
            continue
        ident = way.get('id')
        if not ident or ident in ways:
            raise ValueError('Freight missing/duplicate OSM way')
        ways[ident] = dict(tags=_tags(way), nodes=[n.get('ref') for n in way.findall('nd')])
    restrictions = []
    for relation in osm.findall('relation'):
        tags = _tags(relation)
        if relation.get('action') == 'delete' or tags.get('type') != 'restriction':
            continue
        members = [dict(m.attrib) for m in relation.findall('member')]
        restrictions.append(dict(id=relation.get('id'), tags=tags, members=members))
    context = dict(nodes=nodes, links=links, osm_nodes=osm_nodes, ways=ways, bounds=bounds,
                   restrictions=restrictions, lane_exits={}, lane_roots={}, native_entry_queue_end_m={},
                   source_fingerprints=dict(base_network_sha256=_fingerprints(network_path),
                                            osm_sha256=_fingerprints(osm_path)))
    if lanes_path is not None:
        context['source_fingerprints']['lanes_sha256'] = _fingerprints(lanes_path)
        _index_lanes(context, lanes_path)
    return context


def _index_lanes(ctx, path):
    from simz1_lane_validation import read_lanes
    for ident, lanes in read_lanes(path).items():
        if ident not in ctx['links'] or not lanes:
            raise ValueError('Freight missing link or empty lane assignment: ' + ident)
        link = ctx['links'][ident]
        referenced = {target for lane in lanes.values() for target in lane['to_lanes']}
        roots = set(lanes)-referenced
        if len(roots) != 1:
            raise ValueError('Freight lane graph must have one entry root: ' + ident)
        root = next(iter(roots))
        visited, visiting, cache = set(), set(), {}

        def exits(key):
            if key in visiting:
                raise ValueError('Freight lane cycle: ' + ident+'/'+key)
            if key in cache:
                return cache[key]
            if key not in lanes:
                raise ValueError('Freight dangling lane: ' + ident+'/'+key)
            lane = lanes[key]
            if lane['start'] > link['length']+1e-8:
                raise ValueError('Freight lane starts beyond link: ' + key)
            visiting.add(key)
            result = set()
            if lane['to_lanes']:
                if lane['to_links']:
                    raise ValueError('Freight lane mixes toLane and toLink: ' + key)
                for target in lane['to_lanes']:
                    if target in lanes and lanes[target]['start'] > lane['start']+1e-8:
                        raise ValueError('Freight upstream lane movement: ' + key)
                    result.update(exits(target))
            else:
                if not lane['to_links']:
                    raise ValueError('Freight terminal lane without exit: ' + key)
                for target in lane['to_links']:
                    other = ctx['links'].get(target)
                    if (other is None or other['from'] != link['to'] or
                            not (link['modes'] & other['modes'] & {'car', 'bus'})):
                        raise ValueError('Freight disconnected or mode-forbidden lane target: ' + target)
                    result.add(target)
            visiting.remove(key)
            visited.add(key)
            cache[key] = result
            return result

        targets = exits(root)
        if visited != set(lanes) or not math.isclose(lanes[root]['start'], link['length'], abs_tol=1e-8):
            raise ValueError('Freight unreachable lane or incomplete entry lane: ' + ident)
        ctx['lane_exits'][ident], ctx['lane_roots'][ident] = targets, root
        ctx['native_entry_queue_end_m'][ident] = link['length']-max(
            (lanes[child]['start'] for child in lanes[root]['to_lanes']), default=0.)


def _access_rejection(tags, direction, service):
    """Conservative checks: unsupported relevant qualifications are not waived."""
    for key, value in tags.items():
        parts = key.split(':')
        base = parts[0]
        if base not in _ACCESS and base not in _LIMITS and base not in ('width', 'oneway', 'restriction'):
            continue
        if 'forward' in parts and direction != 'forward' or 'backward' in parts and direction != 'backward':
            continue
        if any(part not in ('forward', 'backward') for part in parts[1:]):
            return 'unsupported restriction '+key+'='+value
        if base in _ACCESS and value not in _ALLOWED_ACCESS:
            return 'restricted access '+key+'='+value
        if base in _LIMITS or base == 'width':
            field, unit = _LIMITS.get(base, ('width_m', 'm'))
            match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(m|t|tonnes?|kg)?\s*', value)
            if not match or (match[2] and match[2] not in ({'m'} if unit == 'm' else {'t', 'ton', 'tons', 'tonne', 'tonnes', 'kg'})):
                return 'unsupported dimensional restriction '+key+'='+value
            limit = float(match[1])/(1000 if match[2] == 'kg' else 1)
            if limit <= 0 or field not in service:
                return 'unknown vehicle dimension for '+key
            if _positive(service[field], field) > limit+1e-9:
                return 'vehicle exceeds '+key+'='+value
    barrier = tags.get('barrier')
    if barrier and barrier not in ('no', 'entrance', 'kerb'):
        return 'barrier requires reviewed heavy-vehicle clearance: '+barrier
    return None


def _restriction_rule(ctx, relation):
    tags = relation['tags']
    if {'hgv', 'motor_vehicle', 'vehicle'} & {v.strip() for v in tags.get('except', '').split(';')}:
        return None, None
    kind = next((tags[key] for key in ('restriction:hgv',
                                      'restriction:motor_vehicle', 'restriction:vehicle', 'restriction') if key in tags), None)
    if kind is None and not any('conditional' in k for k in tags):
        return None, None  # Restrictions explicitly for other vehicle classes.
    members = relation['members']
    source = [m['ref'] for m in members if m.get('role') == 'from' and m.get('type') == 'way']
    target = [m['ref'] for m in members if m.get('role') == 'to' and m.get('type') == 'way']
    via = [m['ref'] for m in members if m.get('role') == 'via' and m.get('type') == 'node']
    if (kind not in _TURN_TYPES or any('conditional' in k for k in tags) or
            len(members) != 3 or len(source) != 1 or len(target) != 1 or len(via) != 1 or
            source[0] not in ctx['ways'] or target[0] not in ctx['ways'] or via[0] not in ctx['osm_nodes']):
        return None, 'unsupported relevant OSM restriction '+str(relation['id'])
    return (kind, source[0], via[0], target[0]), None


def _relation_intersects(relation, link):
    return any((m.get('type') == 'way' and m.get('ref') == link['way']) or
               (m.get('type') == 'node' and m.get('ref') in (link['from'], link['to']))
               for m in relation['members'])


def link_rejection(ctx, ident, service, allow_perimeter_connector=False):
    """Return None for an eligible directed heavy-vehicle link, else a reason."""
    link = ctx['links'].get(ident)
    if link is None or 'car' not in link['modes']:
        return 'missing link or no car access: '+str(ident)
    if link['lanes'] < 1 or link['lanes'] != int(link['lanes']):
        return 'unsupported fractional physical lane count: '+ident
    way = ctx['ways'].get(link['way'])
    if way is None or link['direction'] is None or any(n not in ctx['osm_nodes'] for n in (link['from'], link['to'])):
        return 'missing directed OSM source: '+ident
    index = link['segment']
    segment = way['nodes'][index:index+2]
    if link['direction'] == 'backward':
        segment = list(reversed(segment))
    if segment != [link['from'], link['to']]:
        return 'OSM segment/node mismatch: '+ident
    tags = way['tags']
    for key in tags:
        if key.startswith('turn:lanes:') and key not in ('turn:lanes:forward', 'turn:lanes:backward'):
            return 'unsupported turn-lane restriction '+key+': '+ident
    highway = tags.get('highway')
    if highway not in PRINCIPAL_CLASSES and not (allow_perimeter_connector and highway == 'residential'):
        return 'nonprincipal highway '+str(highway)+': '+ident
    if tags.get('area') == 'yes' or any(k in tags for k in ('construction', 'proposed')):
        return 'nonoperational road: '+ident
    direction = tags.get('oneway', 'yes' if tags.get('junction') == 'roundabout' else 'no').lower()
    if direction not in ('yes', '1', 'true', '-1', 'no', '0', 'false', ''):
        return 'unsupported OSM direction: '+ident
    if direction in ('yes', '1', 'true') and link['direction'] != 'forward' or direction == '-1' and link['direction'] != 'backward':
        return 'wrong OSM direction: '+ident
    if service.get('route_policy') == 'verified-multilane-through-v3':
        from simz1_freight_multilane import directional_lane_evidence
        evidence = directional_lane_evidence(ctx, ident)
        if evidence['status'] != 'verified_multilane':
            return evidence['reason']+': '+ident
    for values in (tags, link['tags'], *(ctx['osm_nodes'][n]['tags'] for n in (link['from'], link['to'])),
                   *(ctx['nodes'][n]['tags'] for n in (link['from'], link['to']))):
        reason = _access_rejection(values, link['direction'], service)
        if reason:
            return reason+': '+ident
    # A supplied total roadway width cannot be treated as the width of each
    # directional lane. This is a conservative data constraint, not a survey.
    if 'width' in tags:
        width = float(re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*m?\s*', tags['width'])[1])
        opposite = [other['lanes'] for other in ctx['links'].values()
                    if other['way'] == link['way'] and other['from'] == link['to'] and other['to'] == link['from']]
        if len(opposite) > 1:
            return 'ambiguous opposing width allocation: '+ident
        if width/(link['lanes']+sum(opposite)) < float(service['width_m'])-1e-9:
            return 'vehicle exceeds explicit width per modeled lane: '+ident
    for relation in ctx['restrictions']:
        if _relation_intersects(relation, link):
            _, reason = _restriction_rule(ctx, relation)
            if reason:
                return reason+': '+ident
    return None


def turn_rejection(ctx, a, b, service=None):
    first, second = ctx['links'].get(a), ctx['links'].get(b)
    if first is None or second is None or first['to'] != second['from']:
        return 'disconnected turn '+str(a)+' -> '+str(b)
    if 'car' not in first['modes'] or 'car' not in second['modes']:
        return 'turn without car access'
    if a in ctx['lane_exits'] and b not in ctx['lane_exits'][a]:
        return 'forbidden entry-reachable lane turn '+a+' -> '+b
    if first['from'] == second['to']:
        return 'immediate U-turn is unsuitable for through freight'
    lane_reason = _turn_lane_rejection(ctx, a, b)
    if lane_reason:
        return lane_reason
    for relation in ctx['restrictions']:
        if not (_relation_intersects(relation, first) or _relation_intersects(relation, second)):
            continue
        rule, error = _restriction_rule(ctx, relation)
        if error:
            return error
        if rule is None:
            continue
        kind, source, via, target = rule
        if first['way'] != source or first['to'] != via:
            continue
        matches = second['way'] == target
        if kind.endswith('u_turn'):
            matches = matches and first['from'] == second['to']
        if kind.startswith('no_') and matches or kind.startswith('only_') and not matches:
            return 'forbidden OSM turn restriction '+str(relation['id'])
    return None


def _turn_angle(ctx, first, second):
    x, y, z = (ctx['nodes'][k] for k in (first['from'], first['to'], second['to']))
    u, v = (y['x']-x['x'], y['y']-x['y']), (z['x']-y['x'], z['y']-y['y'])
    return math.degrees(math.atan2(u[0]*v[1]-u[1]*v[0], u[0]*v[0]+u[1]*v[1]))


def _turn_lane_rejection(ctx, a, b):
    """Check existence of an OSM arrow-compatible lane at the directed way end.

    OSM ways are split into many MATSim links: applying end-of-way arrows at
    every such subdivision would wrongly forbid straight progress within a way.
    This does not turn the native parallel queues into measured turn pockets.
    """
    first, second = ctx['links'][a], ctx['links'][b]
    way = ctx['ways'].get(first['way'])
    if way is None or not way['nodes']:
        return 'missing source way for lane arrows'
    direction = first['direction']
    end = way['nodes'][-1 if direction == 'forward' else 0]
    if first['to'] != end:
        return None
    tags = way['tags']
    key = 'turn:lanes:'+str(direction)
    if key not in tags:
        key = 'turn:lanes'
    if key not in tags:
        return None
    if key == 'turn:lanes' and tags.get('oneway', 'yes' if tags.get('junction') == 'roundabout' else 'no') not in ('yes', '1', 'true', '-1'):
        return 'ambiguous bidirectional turn:lanes; directional review required'
    lanes = tags[key].split('|')
    if len(lanes) != first['lanes']:
        return 'turn:lanes count differs from effective directional lanes'
    angle = _turn_angle(ctx, first, second)
    def compatible(arrow):
        return (arrow == 'none' or arrow == 'through' and abs(angle) <= 30 or
                arrow == 'slight_left' and 15 <= angle <= 60 or
                arrow == 'left' and 30 <= angle <= 150 or
                arrow == 'sharp_left' and 90 <= angle <= 175 or
                arrow == 'slight_right' and -60 <= angle <= -15 or
                arrow == 'right' and -150 <= angle <= -30 or
                arrow == 'sharp_right' and -175 <= angle <= -90 or
                arrow == 'reverse' and abs(angle) >= 150)
    known = {'none', 'through', 'slight_left', 'left', 'sharp_left', 'slight_right', 'right', 'sharp_right', 'reverse'}
    arrows = [arrow.strip() for lane in lanes for arrow in lane.split(';')]
    if any(arrow not in known for arrow in arrows):
        return 'unsupported turn:lanes arrow'
    if not any(compatible(arrow) for arrow in arrows):
        return 'no OSM turn:lanes arrow compatible with outgoing turn'
    return None


def eligible_link(ctx, ident, service, allow_perimeter_connector=False):
    return link_rejection(ctx, ident, service, allow_perimeter_connector) is None


def allowed_turn(ctx, a, b, service=None):
    return turn_rejection(ctx, a, b, service) is None


def _inside(ctx, ident):
    node, bounds, tol = ctx['osm_nodes'][ident], ctx['bounds'], BOUNDARY_TOLERANCE_DEGREES
    return (bounds['minlat']-tol <= node['lat'] <= bounds['maxlat']+tol and
            bounds['minlon']-tol <= node['lon'] <= bounds['maxlon']+tol)


def _gateway(ctx, outside, inside, link):
    first, second, bounds = ctx['osm_nodes'][outside], ctx['osm_nodes'][inside], ctx['bounds']
    crossings = []
    for coordinate, low, high, names in (('lon', 'minlon', 'maxlon', ('west', 'east')),
                                       ('lat', 'minlat', 'maxlat', ('south', 'north'))):
        start, finish = first[coordinate], second[coordinate]
        for key, side in zip((low, high), names):
            if start != finish:
                t = (bounds[key]-start)/(finish-start)
                if 0 <= t <= 1:
                    lon = first['lon']+t*(second['lon']-first['lon'])
                    lat = first['lat']+t*(second['lat']-first['lat'])
                    if bounds['minlon']-1e-9 <= lon <= bounds['maxlon']+1e-9 and bounds['minlat']-1e-9 <= lat <= bounds['maxlat']+1e-9:
                        crossings.append((t, side, lon, lat))
    if not crossings:
        raise ValueError('Freight missing OSM bounds crossing')
    _, side, lon, lat = min(crossings)
    return dict(link=link, outside_node=outside, inside_node=inside, side=side, lon=lon, lat=lat)


def validate_route(ctx, route, service):
    ident, path = route.get('route_id'), route.get('link_ids')
    if not ident or not isinstance(path, list) or len(path) < 3 or len(set(path)) != len(path):
        raise ValueError('Freight missing/short/repeated route links: '+str(ident))
    for key in ('length_m', 'width_m', 'gross_weight_tonnes', 'maximum_speed_kmh'):
        _positive(service.get(key), key)
    connectors = route.get('perimeter_connector_links', [])
    if not isinstance(connectors, list) or len(set(connectors)) != len(connectors) or not set(connectors) <= set(path):
        raise ValueError('Freight invalid perimeter connector declaration')
    # A residential exception may only be a contiguous prefix/suffix at a gateway.
    middle = [i for i, link in enumerate(path) if link not in connectors]
    if not middle or any(path[i] in connectors for i in range(min(middle), max(middle)+1)):
        raise ValueError('Freight perimeter connector must be at route ends')
    for link in path:
        reason = link_rejection(ctx, link, service, link in connectors)
        if reason:
            raise ValueError('Freight '+str(ident)+': '+reason)
    if any(ctx['ways'][ctx['links'][k]['way']]['tags'].get('highway') != 'residential' for k in connectors):
        raise ValueError('Freight perimeter connector exception must be residential')
    connector_length = sum(ctx['links'][k]['length'] for k in connectors)
    if connector_length > PERIMETER_CONNECTOR_LIMIT_M+1e-8:
        raise ValueError('Freight perimeter connector exceeds 250 m')
    for a, b in zip(path, path[1:]):
        reason = turn_rejection(ctx, a, b, service)
        if reason:
            raise ValueError('Freight '+str(ident)+': '+reason)
    first, last = ctx['links'][path[0]], ctx['links'][path[-1]]
    native_gateway = None
    if service.get('route_policy') == 'verified-multilane-through-v3':
        from simz1_freight_gateways import validate_native_gateways
        native_gateway = validate_native_gateways(ctx, route, service)
        entry, exit = native_gateway['entry'], native_gateway['exit']
    else:
        if (route.get('boundary_basis') != 'osm_bounds_crossing' or not route.get('entry_gateway') or
            not route.get('exit_gateway') or route['entry_gateway'] == route['exit_gateway'] or
            _inside(ctx, first['from']) or not _inside(ctx, first['to']) or
            not _inside(ctx, last['from']) or _inside(ctx, last['to'])):
            raise ValueError('Freight requires distinct directed OSM perimeter entry and exit')
        if any(not _inside(ctx, ctx['links'][k]['to']) for k in path[:-1]):
            raise ValueError('Freight route leaves and reenters OSM perimeter')
        entry = _gateway(ctx, first['from'], first['to'], path[0])
        exit = _gateway(ctx, last['to'], last['from'], path[-1])
    if math.hypot(entry['lon']-exit['lon'], entry['lat']-exit['lat']) <= 1e-8:
        raise ValueError('Freight entry and exit are the same perimeter point')
    if entry['side'] == exit['side']:
        raise ValueError('Freight through route must use different perimeter sides')
    angles = [abs(_turn_angle(ctx, ctx['links'][a], ctx['links'][b])) for a, b in zip(path, path[1:])]
    speed = _positive(service['maximum_speed_kmh'], 'maximum_speed_kmh')/3.6
    return dict(id=ident, link_count=len(path), distance_m=sum(ctx['links'][k]['length'] for k in path),
                **({'native_gateway':native_gateway} if native_gateway is not None else {}),
                free_flow_s=sum(ctx['links'][k]['length']/min(ctx['links'][k]['freespeed'], speed) for k in path),
                entry=entry, exit=exit, highway_link_counts=dict(Counter(ctx['ways'][ctx['links'][k]['way']]['tags']['highway'] for k in path)),
                perimeter_connector_m=connector_length, max_turn_degrees=max(angles),
                links_shorter_than_truck=sum(ctx['links'][k]['length'] < float(service['length_m']) for k in path),
                opposite_perimeter_sides=frozenset((entry['side'], exit['side'])) in (frozenset(('west', 'east')), frozenset(('north', 'south'))),
                swept_path_verified=False, queue_drainage_proven=False)


def validate_bundle(ctx, bundle, service):
    """Validate all four versioned corridors; return a JSON-serializable report."""
    # prepare() verifies pinned source fingerprints separately. The same route
    # checks must also accept the effective network with bus-only extensions.
    contract = service.get('service_version'), service.get('route_policy')
    if (contract not in (('weekday-v2', 'principal-through-v2'),
                         ('weekday-compact-v3', 'verified-multilane-through-v3')) or
            contract != (bundle.get('service_version'), bundle.get('route_policy'))):
        raise ValueError('Freight service/bundle version or route policy mismatch')
    routes = bundle.get('routes', [])
    if contract[0] == 'weekday-v2' and (len(routes) != 4 or {r.get('route_id') for r in routes} != ROUTE_IDS):
        raise ValueError('Freight v2 requires four distinct historical corridor IDs')
    if not routes or len({r.get('route_id') for r in routes}) != len(routes) or len({tuple(r.get('link_ids', [])) for r in routes}) != len(routes):
        raise ValueError('Freight corridors must have distinct IDs and routes')
    if contract[0] == 'weekday-compact-v3' and any(r.get('perimeter_connector_links') for r in routes):
        raise ValueError('Freight compact service has no one-lane or residential connector exception')
    if contract[0] == 'weekday-compact-v3':
        from simz1_freight_gateways import POLICY as NATIVE_GATEWAY_POLICY
        if service.get('native_gateway_policy') != NATIVE_GATEWAY_POLICY or bundle.get('native_gateway_policy') != NATIVE_GATEWAY_POLICY:
            raise ValueError('Freight compact native gateway policy missing or inconsistent')
    reports = [validate_route(ctx, route, service) for route in routes]
    if contract[0] == 'weekday-compact-v3':
        from simz1_freight_multilane import directional_lane_evidence
        for route, report in zip(routes, reports):
            report['directional_lane_evidence'] = [directional_lane_evidence(ctx, k) for k in route['link_ids']]
            report['minimum_verified_usable_directional_lanes'] = min(e['usable_directional_lanes'] for e in report['directional_lane_evidence'])
    return dict(status='valid', route_policy=contract[1], routes=reports,
                osm_restrictions_checked=len(ctx['restrictions']), boundary=ctx['bounds'],
                physical_stability_proven=False,
                limitations=['OSM bounds are the source request perimeter, not a surveyed administrative boundary.',
                             'Missing OSM weight/dimension data is not heavy-vehicle legal authorization.',
                             'Lanes are native queue reachability, not measured turn pockets or swept paths.',
                             'OSM turn arrows are checked at directed way ends; native queues do not certify observed lane choice.',
                             'The native nominal lane width is 3 m versus the saved scenario truck width; actual lateral clearance is unverified.',
                             'Short links require native corridor/passage checks; length alone is not a rejection.',
                             'Free-flow times exclude signal, priority, queue and reservation delays.'])
