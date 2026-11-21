"""Read-only, focal OSM/network/lane connectivity evidence for SimZ1.

The inspection rectangle selects roads to review; it is not a district boundary.
Routes describe the configured network and reachable terminal lanes, not proof
that pending OSM turn relations have been enforced. Nothing is generated or fixed.
"""
import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path

from simz1_osm_turn_audit import load_lanes, load_xml, source_way_id


SECTOR_BOUNDS = (-90.5062, 14.6245, -90.5042, 14.6275)
ROAD_TYPES = frozenset(('motorway', 'motorway_link', 'trunk', 'trunk_link',
                       'primary', 'primary_link', 'secondary', 'secondary_link',
                       'tertiary', 'tertiary_link', 'residential', 'unclassified',
                       'living_street', 'service'))
ACCESS_KEYS = ('motorcar', 'motor_vehicle', 'vehicle', 'access')
ALLOWED_ACCESS = ('yes', 'permissive', 'designated')
DEFAULT_WITNESSES = (('412162798', '412162814'), ('412162798', '7295814876'),
                     ('412162909', '412162813'), ('412162813', '412162909'),
                     ('412162814', '7295814876'), ('412160765', '412162814'),
                     ('333831813', '412162814'), ('412162814', '333831813'),
                     ('412162798', '412163034'), ('412163034', '412162798'))


def _components(links, successors, mode):
    """Iterative weak/Kosaraju components of admitted configured transitions.

    Vertices are directed links, not junctions: two roads sharing a junction
    need not admit a turn. Pending OSM relations are NOT enforced here.
    """
    vertices = sorted(lid for lid, link in links.items() if mode in link['modes'])
    members = set(vertices)
    graph = {lid: sorted(target for target in successors[lid] if target in members) for lid in vertices}
    reverse = {lid: [] for lid in vertices}
    for lid, targets in graph.items():
        for target in targets:
            reverse[target].append(lid)

    def flood(start, adjacency, seen):
        pending, component = [start], []
        seen.add(start)
        while pending:
            lid = pending.pop()
            component.append(lid)
            for target in adjacency(lid):
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        return sorted(component)

    weak, seen = [], set()
    for lid in vertices:
        if lid not in seen:
            weak.append(flood(lid, lambda key: graph[key] + reverse[key], seen))
    seen, finish = set(), []
    for lid in vertices:
        if lid in seen:
            continue
        seen.add(lid)
        stack = [(lid, iter(graph[lid]))]
        while stack:
            current, targets = stack[-1]
            target = next(targets, None)
            if target is None:
                finish.append(current)
                stack.pop()
            elif target not in seen:
                seen.add(target)
                stack.append((target, iter(graph[target])))
    strong, seen = [], set()
    for lid in reversed(finish):
        if lid not in seen:
            strong.append(flood(lid, lambda key: reverse[key], seen))
    assignments, summaries = {}, {}
    for kind, groups in (('weak', weak), ('strong', strong)):
        rows, mapping = [], {}
        for group in sorted(groups, key=lambda group: (-len(group), group[0])):
            signature = hashlib.sha256('\n'.join(group).encode('utf-8')).hexdigest()[:16]
            component_id = f'{mode}:{kind}:{signature}'
            for lid in group:
                mapping[lid] = component_id
            rows.append({'component_id': component_id, 'link_count': len(group),
                         'representative_link': group[0]})
        assignments[kind] = mapping
        summaries[kind] = rows
    return {'graph': 'directed_links_and_reachable_terminal_lane_transitions',
            'scope': 'configured_movements_only; pending_OSM_restrictions_not_enforced',
            'link_count': len(vertices), 'movement_count': sum(map(len, graph.values())),
            'weak_component_count': len(weak), 'strong_component_count': len(strong),
            'weak_components': summaries['weak'], 'strong_components': summaries['strong']}, assignments


def _tags(element):
    return {tag.get('k'): tag.get('v') for tag in element.findall('tag')}


def _within(position, bounds):
    return bool(position is not None and bounds is not None and
                bounds[0] <= position[0] <= bounds[2] and
                bounds[1] <= position[1] <= bounds[3])


def _intersects_rectangle(a, b, bounds):
    if a is None or b is None:
        return False
    if _within(a, bounds) or _within(b, bounds):
        return True
    low, high = 0.0, 1.0
    for axis in (0, 1):
        delta = b[axis] - a[axis]
        if delta == 0:
            if not bounds[axis] <= a[axis] <= bounds[axis + 2]:
                return False
            continue
        left, right = sorted(((bounds[axis] - a[axis]) / delta,
                              (bounds[axis + 2] - a[axis]) / delta))
        low, high = max(low, left), min(high, right)
        if low > high:
            return False
    return True


def _access_reason(tags):
    if any(key + ':conditional' in tags for key in ACCESS_KEYS):
        return 'conditional_access_review'
    for key in ACCESS_KEYS:
        if key in tags:
            return None if tags[key] in ALLOWED_ACCESS else 'restricted_access'
    return None


def _import_reason(tags):
    """Mirror the current converter's admission contract, without invoking it."""
    if tags.get('highway') not in ROAD_TYPES or tags.get('area') == 'yes':
        return 'non_car_highway_or_area'
    if any(key in tags for key in ('construction', 'proposed', 'oneway:conditional')):
        return 'construction_or_conditional_direction'
    if tags.get('oneway', '').lower() not in ('', 'yes', 'true', '1', '-1', 'no', 'false', '0'):
        return 'unsupported_direction'
    return _access_reason(tags)


def _directions(tags):
    oneway = tags.get('oneway', 'yes' if tags.get('junction') == 'roundabout' else 'no').lower()
    return (-1,) if oneway == '-1' else (1,) if oneway in ('yes', '1', 'true') else (1, -1)


def _source_access(tags):
    answer = {}
    for mode, keys in {'car': ACCESS_KEYS,
                       'bus': ('bus', 'psv', 'motor_vehicle', 'vehicle', 'access'),
                       'bike': ('bicycle', 'vehicle', 'access'),
                       'walk': ('foot', 'access')}.items():
        selected = next((key for key in keys if key in tags), None)
        answer[mode] = {'key': selected, 'value': tags.get(selected),
                        'conditional': {key: value for key, value in tags.items()
                                        if key in tuple(k + ':conditional' for k in keys)},
                        'unspecified_is_not_permission': True}
    return answer


def _expected_pairs(way, positions, blocked_nodes):
    pairs = set()
    for a, b in zip(way['refs'], way['refs'][1:]):
        if a in blocked_nodes or b in blocked_nodes or a not in positions or b not in positions or positions[a] == positions[b]:
            continue
        pairs.update((a, b) if direction == 1 else (b, a) for direction in _directions(way['tags']))
    return pairs


def _global_import_check(ways, positions, blocked_nodes, links, nodes):
    """Linear source/import comparison, independent of the focal rectangle."""
    actual, by_way = defaultdict(list), defaultdict(list)
    for lid, link in links.items():
        if 'car' in link['modes']:
            actual[(link['way_id'], link['from'], link['to'])].append(lid)
            by_way[link['way_id']].append(lid)
    expected, missing, inconsistent, exclusions = {}, [], [], Counter()
    for wid, way in ways.items():
        reason = _import_reason(way['tags'])
        if reason:
            exclusions[reason] += 1
            continue
        expected[wid] = _expected_pairs(way, positions, blocked_nodes)
        for a, b in sorted(expected[wid]):
            if (wid, a, b) not in actual:
                missing.append({'way_id': wid, 'from_node': a, 'to_node': b,
                                'classification': 'segmento_admisible_ausente_revisar_importacion'})
    for (wid, a, b), ids in sorted(actual.items(), key=lambda item: str(item[0])):
        reason = ('missing_source_way' if wid not in ways else
                  _import_reason(ways[wid]['tags']) or
                  ('directed_segment_not_admitted_by_source' if (a, b) not in expected[wid] else None))
        if reason:
            inconsistent.append({'way_id': wid, 'from_node': a, 'to_node': b,
                                 'link_ids': sorted(ids), 'reason': reason})
    duplicate_edges = [{'way_id': wid, 'from_node': a, 'to_node': b, 'link_ids': sorted(ids)}
                       for (wid, a, b), ids in actual.items() if len(ids) > 1]
    return {'scope': 'all_source_highway_ways_and_car_links; import_contract_not_turn_legality',
            'source_highway_ways': len(ways), 'admissible_source_ways': len(expected),
            'expected_directed_segments': sum(map(len, expected.values())),
            'network_car_links': sum(map(len, actual.values())),
            'missing_admissible_directed_segments': len(missing),
            'inconsistent_source_access_or_direction_links': sum(len(row['link_ids']) for row in inconsistent),
            'duplicate_source_directed_edges': len(duplicate_edges),
            'missing_segments': missing, 'inconsistent_links': inconsistent, 'duplicate_edges': duplicate_edges,
            'source_exclusion_counts': dict(exclusions),
            'declared_noexit': {
                'ways': [{'way_id': wid, 'name': way['tags'].get('name'), 'link_ids': sorted(by_way[wid])}
                         for wid, way in sorted(ways.items()) if way['tags'].get('noexit') == 'yes'],
                'nodes': [{'node_id': nid, 'position_lon_lat': list(positions[nid])}
                          for nid, node in sorted(nodes.items()) if _tags(node).get('noexit') == 'yes']},
            'connections_changed': 0}


def _route(start, end, mode, links, outgoing, successors, max_visits):
    queue, previous = deque(), {}
    for link_id in sorted(outgoing.get(start, ())):
        if mode in links[link_id]['modes']:
            previous[link_id] = None
            queue.append(link_id)
    visits, terminal = 0, None
    while queue and visits < max_visits:
        link_id = queue.popleft()
        visits += 1
        if links[link_id]['to'] == end:
            terminal = link_id
            break
        for target in successors[link_id]:
            if mode in links[target]['modes'] and target not in previous:
                previous[target] = link_id
                queue.append(target)
    path = []
    if terminal is not None:
        while terminal is not None:
            path.append(terminal)
            terminal = previous[terminal]
        path.reverse()
    return {'from_node': start, 'to_node': end, 'mode': mode,
            'status': 'configured_path' if path else 'search_limit' if queue else 'no_configured_path',
            'absence_proven': not path and not queue, 'visited_links': visits, 'links': path,
            'scope': 'network_and_reachable_terminal_lanes; OSM restriction audit required'}


def _crossing(a, b, c, d):
    """Strict segment crossing only; no near endpoints are snapped together."""
    vx, vy, wx, wy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    denominator = vx * wy - vy * wx
    if abs(denominator) < 1e-18:
        return False
    dx, dy = c[0] - a[0], c[1] - a[1]
    t, u = (dx * wy - dy * wx) / denominator, (dx * vy - dy * vx) / denominator
    return 0 < t < 1 and 0 < u < 1


def analyze(osm_path, network_path, lanes_path, *, sector_bounds=SECTOR_BOUNDS,
            witness_pairs=None, max_route_visits=25000):
    """Return JSON-compatible evidence; read inputs only and write no artifacts."""
    if max_route_visits < 1:
        raise ValueError('max_route_visits must be positive')
    if len(sector_bounds) != 4 or not (sector_bounds[0] < sector_bounds[2] and sector_bounds[1] < sector_bounds[3]):
        raise ValueError('Expected west,south,east,north review bounds')
    osm, network = load_xml(osm_path), load_xml(network_path)
    network_nodes = {node.get('id') for node in network.findall('./nodes/node')}
    nodes = {node.get('id'): node for node in osm.findall('node') if node.get('action') != 'delete'}
    positions = {nid: (float(node.get('lon')), float(node.get('lat')))
                 for nid, node in nodes.items()}
    ways = {way.get('id'): {'tags': _tags(way), 'refs': [n.get('ref') for n in way.findall('nd')]}
            for way in osm.findall('way') if way.get('action') != 'delete' and _tags(way).get('highway')}
    bounds_element = osm.find('bounds')
    bounds = ((float(bounds_element.get('minlon')), float(bounds_element.get('minlat')),
               float(bounds_element.get('maxlon')), float(bounds_element.get('maxlat')))
              if bounds_element is not None else None)
    selected = {wid: way for wid, way in ways.items()
                if any(_within(positions.get(nid), sector_bounds) for nid in way['refs']) or
                any(_intersects_rectangle(positions.get(a), positions.get(b), sector_bounds)
                    for a, b in zip(way['refs'], way['refs'][1:]))}
    membership = defaultdict(set)
    for wid, way in ways.items():
        for nid in way['refs']:
            membership[nid].add(wid)
    links = {link.get('id'): {'id': link.get('id'), 'from': link.get('from'), 'to': link.get('to'),
                              'way_id': source_way_id(link),
                              'modes': sorted(m.strip() for m in link.get('modes', 'car').split(',') if m.strip()),
                              'length_m': float(link.get('length', '0'))}
             for link in network.findall('./links/link')}
    lanes = load_lanes(lanes_path)
    incoming, outgoing, by_way = defaultdict(list), defaultdict(list), defaultdict(list)
    for lid, link in links.items():
        incoming[link['to']].append(lid)
        outgoing[link['from']].append(lid)
        by_way[link['way_id']].append(lid)
    successors, predecessors, invalid_lane_targets = {}, defaultdict(list), []
    for lid, link in links.items():
        connected = set(outgoing[link['to']])
        admitted = connected if lid not in lanes else connected.intersection(lanes[lid])
        successors[lid] = sorted(admitted)
        for target in admitted:
            predecessors[target].append(lid)
        for target in sorted(set(lanes.get(lid, {})) - connected):
            invalid_lane_targets.append({'from_link': lid, 'to_link': target,
                                         'reason': 'unknown_or_nonadjacent_target'})
    modes = sorted({mode for link in links.values() for mode in link['modes']})
    components, component_ids = {}, {}
    for mode in modes:
        components[mode], component_ids[mode] = _components(links, successors, mode)
    blocked_nodes = {nid for nid, node in nodes.items() if _access_reason(_tags(node)) or
                     (_tags(node).get('barrier') in ('bollard', 'block', 'cycle_barrier') and
                      not any(_tags(node).get(key) in ('yes', 'permissive') for key in ACCESS_KEYS[:2]))}
    global_import_check = _global_import_check(ways, positions, blocked_nodes, links, nodes)
    rows, source_rows, endpoints, missing = [], [], {}, []
    for wid, way in sorted(selected.items()):
        tags, refs, reason = way['tags'], way['refs'], _import_reason(way['tags'])
        source_rows.append({'way_id': wid, 'name': tags.get('name'), 'tags': tags,
                            'source_access_by_mode': _source_access(tags),
                            'car_import_exclusion': reason, 'links': sorted(by_way[wid]),
                            'classification': ('acceso_restringido' if reason == 'restricted_access' else
                                               'modo_o_acceso_no_modelado' if reason else 'via_importada')})
        actual = {(links[lid]['from'], links[lid]['to']) for lid in by_way[wid]}
        if reason is None:
            for pair in sorted(_expected_pairs(way, positions, blocked_nodes) - actual):
                missing.append({'way_id': wid, 'from_node': pair[0], 'to_node': pair[1],
                                'classification': 'segmento_admisible_ausente_revisar_importacion'})
        for nid in (refs[:1] + refs[-1:]):
            if nid not in positions:
                continue
            isolated_source_end = len(membership[nid]) == 1
            outside = bounds is not None and not _within(positions[nid], bounds)
            tags_at_node = _tags(nodes[nid])
            endpoints[nid] = {'node_id': nid, 'position_lon_lat': list(positions[nid]),
                              'tags': tags_at_node, 'source_ways': sorted(membership[nid]),
                              'outside_extract_rectangle': outside,
                              'classification': ('limite_del_extracto_continuacion_desconocida' if outside and isolated_source_end else
                                                 'callejon_declarado_osm' if tags_at_node.get('noexit') == 'yes' or tags.get('noexit') == 'yes' else
                                                 'extremo_osm_sin_conexion_causa_real_no_confirmada' if isolated_source_end else
                                                 'nodo_compartido'),
                              'directed_degree_by_mode': {mode: {
                                  'incoming': sum(mode in links[lid]['modes'] for lid in incoming[nid]),
                                  'outgoing': sum(mode in links[lid]['modes'] for lid in outgoing[nid])}
                                  for mode in modes}}
        for lid in sorted(by_way[wid]):
            link = links[lid]
            classifications = []
            if len(_directions(tags)) == 1:
                classifications.append('sentido_unico')
            if tags.get('bridge') not in (None, 'no') or tags.get('tunnel') not in (None, 'no') or tags.get('layer', '0') != '0':
                classifications.append('desnivel_declarado_no_inferir_cruce')
            if reason:
                classifications.append('acceso_o_importacion_requiere_revision')
            constrained = sorted(set(outgoing[link['to']]) - set(successors[lid]))
            if constrained:
                classifications.append('movimiento_restringido_por_carril')
            if not incoming[link['from']] or not outgoing[link['to']]:
                classifications.append('extremo_dirigido_consultar_fuente')
            if bounds is not None and any(not _within(positions.get(link[key]), bounds) for key in ('from', 'to')):
                classifications.append('tramo_fuera_rectangulo_extracto')
            movements = {}
            for mode in link['modes']:
                movements[mode] = {'successors': [
                    {'link_id': target, 'terminal_lanes': sorted(lanes.get(lid, {}).get(target, set())),
                     'basis': 'reachable_terminal_lane' if lid in lanes else 'network_without_lane_assignment'}
                    for target in successors[lid] if mode in links[target]['modes']],
                    'predecessors': [
                        {'link_id': prior, 'terminal_lanes': sorted(lanes.get(prior, {}).get(lid, set()))}
                        for prior in sorted(predecessors[lid]) if mode in links[prior]['modes']]}
            rows.append({**link, 'name': tags.get('name'), 'source_tags': tags,
                         'classification': classifications or ['conectividad_dirigida_importada'],
                         'component_ids_by_mode': {mode: {kind: mapping[lid] for kind, mapping in component_ids[mode].items()}
                                                   for mode in link['modes']},
                         'movements_by_mode': movements, 'lane_excluded_successors': constrained,
                         'visual_clipping': 'not_evaluated_by_network_inspection'})
    segments = [(wid, a, b) for wid, way in selected.items() for a, b in zip(way['refs'], way['refs'][1:])
                if a in positions and b in positions]
    crossings = []
    for index, (wid, a, b) in enumerate(segments):
        for other, c, d in segments[index + 1:]:
            if wid == other or {a, b}.intersection((c, d)):
                continue
            if _crossing(positions[a], positions[b], positions[c], positions[d]):
                evidence = {key: {k: selected[key]['tags'][k] for k in ('layer', 'bridge', 'tunnel')
                                  if k in selected[key]['tags']} for key in (wid, other)}
                crossings.append({'way_ids': [wid, other], 'node_pairs': [[a, b], [c, d]],
                                  'classification': 'cruce_geometrico_sin_nodo_compartido',
                                  'grade_tags': evidence, 'connection_added': False,
                                  'resolution': 'preserve_source; grade_or_missing_OSM_topology_needs_review'})
    witness_pairs = DEFAULT_WITNESSES if witness_pairs is None else witness_pairs
    witnesses = []
    for index, (a, b) in enumerate(witness_pairs, start=1):
        for mode in modes:
            missing_nodes = [nid for nid in (a, b) if nid not in network_nodes]
            route = ({'from_node': a, 'to_node': b, 'mode': mode, 'status': 'missing_network_endpoint',
                      'absence_proven': False, 'missing_nodes': missing_nodes, 'visited_links': 0, 'links': []}
                     if missing_nodes else _route(a, b, mode, links, outgoing, successors, max_route_visits))
            witnesses.append({'witness_id': f'W{index:02d}', **route})
    return {'schema': 'simz1-connectivity-review-v1', 'read_only': True,
            'sources': {name: {'path': str(Path(path)), 'sha256_bytes': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                        for name, path in (('osm', osm_path), ('network', network_path), ('lanes', lanes_path))},
            'review_rectangle': list(sector_bounds), 'extract_rectangle': list(bounds) if bounds else None,
            'administrative_boundary': 'not_approved; neither rectangle is an administrative boundary',
            'mode_counts': dict(Counter(mode for link in links.values() for mode in link['modes'])),
            'components_by_mode': components,
            'global_import_check': global_import_check,
            'unrepresented_modes': [mode for mode in ('car', 'bike', 'walk', 'pt') if mode not in modes],
            'summary': {'selected_ways': len(selected), 'selected_links': len(rows),
                        'missing_admissible_directed_segments': len(missing),
                        'invalid_lane_targets': len(invalid_lane_targets), 'connections_changed': 0},
            'links': rows, 'source_ways': source_rows, 'endpoints': list(endpoints.values()),
            'missing_segments': missing, 'invalid_lane_targets': invalid_lane_targets,
            'crossings_without_shared_nodes': crossings, 'witness_routes': witnesses,
            'limitations': ['Degree one does not prove a real dead end.',
                            'Unspecified OSM access is not a measured permission.',
                            'Routes use configured lane movements; inspect OSM relations separately, including via-way history.',
                            'Renderer clipping cannot be classified from these three inputs.',
                            'No source endpoints were joined and no component was removed.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--osm', type=Path, default=Path('scenarios/zona1/map.osm'))
    parser.add_argument('--network', type=Path, default=Path('scenarios/zona1/network.xml'))
    parser.add_argument('--lanes', type=Path, default=Path('scenarios/zona1/lanes.xml'))
    parser.add_argument('--bounds', nargs=4, type=float, default=SECTOR_BOUNDS, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    parser.add_argument('--witness', nargs=2, action='append', metavar=('FROM_NODE', 'TO_NODE'),
                        help='Repeat to replace the ten default directed witness routes')
    parser.add_argument('--max-route-visits', type=int, default=25000)
    args = parser.parse_args(argv)
    print(json.dumps(analyze(args.osm, args.network, args.lanes, sector_bounds=args.bounds,
                            witness_pairs=args.witness, max_route_visits=args.max_route_visits),
                     indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
