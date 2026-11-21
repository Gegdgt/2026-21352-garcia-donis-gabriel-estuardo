"""Filter the Zona 1 OSM extract for JOSM/MATSim, validating critical junctions.

This writes a local scenario copy, never an OSM upload or edits to the source.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from prepare_simz1 import SCENARIO, ACCESS_KEYS, access_reason, road_reason, tags, components

AVENUE = '30279769'
# Street, shared signal node, transverse OSM way (this specific source extract).
CROSSINGS = (('14', '333831813', '420120096'),
             ('13', '333831774', '384762193'),
             ('12', '333831722', '384737905'))


def validate_critical(nodes, ways):
    """Fail closed: coincident coordinates are never a substitute for shared IDs."""
    avenue = ways.get(AVENUE)
    if avenue is None:
        raise ValueError(f'Missing critical 3a Avenida way {AVENUE}')
    refs = [nd.get('ref') for nd in avenue.findall('nd')]
    edges = []
    for wid, way in ways.items():
        t = tags(way)
        sequence = [nd.get('ref') for nd in way.findall('nd')]
        direction = t.get('oneway', 'yes' if t.get('junction') == 'roundabout' else 'no').lower()
        for a, b in zip(sequence, sequence[1:]):
            if direction not in ('-1',): edges.append({'from': a, 'to': b, 'way': wid})
            if direction not in ('yes', 'true', '1'): edges.append({'from': b, 'to': a, 'way': wid})
    core = components(edges)[0] if edges else set()
    result = []
    for street, nid, wid in CROSSINGS:
        if nid not in nodes or nid not in refs or wid not in ways:
            raise ValueError(f'Missing critical junction A3/C{street}: node {nid}, way {wid}')
        if tags(nodes[nid]).get('highway') != 'traffic_signals':
            raise ValueError(f'Missing traffic_signals at A3/C{street}: {nid}')
        cross_refs = [nd.get('ref') for nd in ways[wid].findall('nd')]
        if nid not in cross_refs:
            raise ValueError(f'Unshared node at A3/C{street}: {nid}')
        if nid not in core:
            raise ValueError(f'Critical node outside strongly connected core: {nid}')
        # Each road must have an approach and a departure at the actual shared node.
        for road in (AVENUE, wid):
            if not any(e['way'] == road and e['to'] == nid for e in edges) or not any(
                    e['way'] == road and e['from'] == nid for e in edges):
                raise ValueError(f'Incomplete approach/departure at {nid}, way {road}')
        result.append({'street': street, 'node': nid, 'crossing_way': wid, 'signal': True})
    indices = [refs.index(nid) for _, nid, _ in CROSSINGS]
    if indices != sorted(indices) or len(set(indices)) != len(indices):
        raise ValueError('Critical crossings not ordered C14 -> C13 -> C12')
    avenue_edges = {(e['from'], e['to']) for e in edges if e['way'] == AVENUE}
    segment = refs[indices[0]:indices[-1]+1]
    if any(pair not in avenue_edges for pair in zip(segment, segment[1:])):
        raise ValueError('3a Avenida northbound continuity lost between C14 and C12')
    return {'crossings': result, 'continuous_segment_nodes': segment,
            'largest_component_nodes': len(core)}


def filter_osm(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Output must differ from the original OSM')
    root = ET.parse(source).getroot()
    if root.tag != 'osm': raise ValueError('Expected OSM XML')
    nodes = {n.get('id'): n for n in root.findall('node') if n.get('action') != 'delete'}
    ways, excluded = {}, {}
    for way in root.findall('way'):
        wid, t = way.get('id'), tags(way)
        reason = 'deleted' if way.get('action') == 'delete' else road_reason(t)
        if reason:
            excluded[wid] = reason
            continue
        refs = [nd.get('ref') for nd in way.findall('nd')]
        if len(refs) < 2 or any(nid not in nodes for nid in refs):
            raise ValueError(f'Incomplete drivable way {wid}')
        # Conservative removal avoids splitting IDs and invalidating restriction relations.
        blocked = any(access_reason(tags(nodes[nid])) or (
            tags(nodes[nid]).get('barrier') in ('bollard', 'block', 'cycle_barrier') and
            not any(tags(nodes[nid]).get(k) in ('yes', 'permissive') for k in ACCESS_KEYS[:2]))
            for nid in refs)
        if blocked:
            excluded[wid] = 'way_with_restricted_node'
            continue
        ways[wid] = way
    validation = validate_critical(nodes, ways)
    used = {nd.get('ref') for w in ways.values() for nd in w.findall('nd')}
    # Keep complete restrictions only. Never serialize dangling relation members.
    relations, omitted = [], []
    for relation in root.findall('relation'):
        if relation.get('action') == 'delete': continue
        members = relation.findall('member')
        if tags(relation).get('type') == 'restriction' and members and all(
                m.get('ref') in (used if m.get('type') == 'node' else ways if m.get('type') == 'way' else {})
                for m in members):
            relations.append(relation)
        else:
            omitted.append(relation.get('id'))
    filtered = ET.Element('osm', version='0.6', generator='SimZ1 vehicle filter', upload='never')
    bounds = root.find('bounds')
    if bounds is not None: filtered.append(deepcopy(bounds))
    for node in nodes.values():
        if node.get('id') in used: filtered.append(deepcopy(node))
    for way in ways.values(): filtered.append(deepcopy(way))
    for relation in relations: filtered.append(deepcopy(relation))
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(filtered, space='  ')
    temporary = destination.with_suffix('.osm.tmp')
    ET.ElementTree(filtered).write(temporary, encoding='utf-8', xml_declaration=True)
    temporary.replace(destination)
    report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'nodes': len(used), 'ways': len(ways), 'restriction_relations': len(relations),
              'excluded_by_reason': dict(Counter(excluded.values())), 'excluded_ways': excluded,
              'omitted_relations': omitted, 'critical_validation': validation,
              'signal_nodes': sorted(nid for nid in used if tags(nodes[nid]).get('highway') == 'traffic_signals'),
              'note': 'OSM WGS84 for JOSM; retained restriction tags do not install MATSim turn/signal controllers'}
    destination.with_suffix('.report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=SCENARIO/'map.osm')
    parser.add_argument('--output', type=Path, default=SCENARIO/'map-vehicles.osm')
    args = parser.parse_args()
    try:
        report = filter_osm(args.input, args.output)
    except (ValueError, ET.ParseError, OSError) as exc:
        parser.exit(1, f'Validation failed: {exc}\n')
    print(f"Validated: {report['nodes']} nodes, {report['ways']} ways; output: {args.output}")


if __name__ == '__main__': main()
