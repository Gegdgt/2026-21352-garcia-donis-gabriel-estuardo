"""Read-only comparison of OSM restriction relations with SimZ1 links and lanes.

Writes audit reports only. A lane admission proves a configuration gap, not that
a vehicle executed the maneuver. Relations with via ways are not flattened.
"""
import argparse
import csv
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


FIELDS = ('relation_id', 'restriction', 'status', 'detail', 'from_ways', 'via_nodes',
          'via_ways', 'to_ways', 'from_links', 'to_links', 'lanes_admit_prohibited_target',
          'admitting_movements', 'admitting_terminal_lanes', 'lane_check', 'osm_tags',
          'missing_members', 'semantics_review', 'path_status', 'directed_sequences',
          'sequence_lane_checks', 'lanes_admit_sequence')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def load_xml(path):
    """Read source XML or native MATSim .xml.gz without rewriting either."""
    path = Path(path)
    with (gzip.open(path, 'rb') if path.suffix == '.gz' else path.open('rb')) as stream:
        root = ET.parse(stream).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    return root


def source_way_id(link):
    # MATSim's writer moves the legacy origid XML attribute into attributes.
    # Do not guess from an ID prefix when provenance is absent.
    values = {value for value in [link.get('origid')] +
              [row.text for row in link.findall("attributes/attribute[@name='origid']")]
              if value is not None}
    if len(values) > 1:
        raise ValueError('Contradictory OSM origid provenance: ' + str(link.get('id')))
    return next(iter(values), None)


def _movement(start, end, lanes):
    if start not in lanes:
        return dict(from_link=start, to_link=end, admitted=True,
                    check='no_lane_assignment_connected_graph_admits', terminal_lanes=[])
    return dict(from_link=start, to_link=end, admitted=end in lanes[start],
                check='reachable_terminal_lane_admits' if end in lanes[start] else 'lane_graph_excludes',
                terminal_lanes=sorted(lanes[start].get(end, set())))


def _via_way_sequences(from_way, via_ways, to_way, ways, links, limit=128):
    """Follow ordered OSM via members and contiguous native directed segments.

    A sequence includes the incoming from-link and outgoing to-link. Every via
    member contributes at least one link. No nearest-endpoint join, node shortcut,
    pairwise enforcement, or reverse/backtracking within a way is invented.
    Ambiguous/large relations remain explicit, with bounded traversal.
    """
    by_edge, from_links, to_links = defaultdict(list), [], defaultdict(list)
    for link in links:
        way = source_way_id(link)
        a, b, lid = (link.get(key) for key in ('from', 'to', 'id'))
        by_edge[(way, a, b)].append(lid)
        if way == from_way:
            from_links.append((lid, b))
        if way == to_way:
            to_links[a].append(lid)
    paths, truncated, work = set(), False, 0

    def visit(stage, entry, prefix):
        nonlocal truncated, work
        work += 1
        if work > 10000 or len(paths) >= limit:
            truncated = True
            return
        if stage == len(via_ways):
            for tail in sorted(to_links[entry]):
                if len(paths) >= limit:
                    truncated = True
                    return
                paths.add(tuple(prefix + [tail]))
            return
        way = via_ways[stage]
        refs = [node.get('ref') for node in ways[way].findall('nd')]
        for index, node in enumerate(refs):
            if node != entry:
                continue
            for direction in (1, -1):
                prefixes = [prefix]
                cursor = index
                while 0 <= cursor + direction < len(refs):
                    next_cursor = cursor + direction
                    candidates = sorted(by_edge[(way, refs[cursor], refs[next_cursor])])
                    if not candidates:
                        break
                    next_prefixes = []
                    for previous in prefixes:
                        for candidate in candidates:
                            if len(next_prefixes) >= limit:
                                truncated = True
                                break
                            extension = previous + [candidate]
                            next_prefixes.append(extension)
                            visit(stage + 1, refs[next_cursor], extension)
                            if truncated:
                                return
                    prefixes = next_prefixes
                    cursor = next_cursor

    for lid, node in sorted(from_links):
        visit(0, node, [lid])
        if truncated:
            break
    return [list(path) for path in sorted(paths)], truncated


def load_lanes(path):
    root = load_xml(path)
    assignments = {}
    for assignment in root.findall('lanesToLinkAssignment'):
        lane_map = {lane.get('id'): lane for lane in assignment.findall('lane')}
        referenced = {next_lane.get('refId') for lane in lane_map.values()
                      for next_lane in lane.findall('./leadsTo/toLane')}
        entries = set(lane_map) - referenced
        if len(entries) != 1:
            raise ValueError(f'Cannot identify a single lane entry: {assignment.get("linkIdRef")}')
        visiting, reached, terminals = set(), set(), defaultdict(set)

        def visit(lane_id):
            if lane_id in visiting:
                raise ValueError(f'Lane cycle: {lane_id}')
            if lane_id in reached:
                return
            if lane_id not in lane_map:
                raise ValueError(f'Unknown lane: {lane_id}')
            visiting.add(lane_id)
            lane = lane_map[lane_id]
            downstream = lane.findall('./leadsTo/toLane')
            targets = lane.findall('./leadsTo/toLink')
            if downstream and targets:
                raise ValueError(f'Mixed lane/link destinations: {lane_id}')
            for target in targets:
                terminals[target.get('refId')].add(lane_id)
            for child in downstream:
                visit(child.get('refId'))
            visiting.remove(lane_id)
            reached.add(lane_id)

        visit(next(iter(entries)))
        if reached != set(lane_map):
            raise ValueError(f'Unreachable lanes: {assignment.get("linkIdRef")}')
        assignments[assignment.get('linkIdRef')] = dict(terminals)
    return assignments


def verify_sequence_mapping(osm, links, rule):
    """Verify the contract against directed source geometry, independent of lanes.

    This proves the mapping only. Enforcement belongs to the shared routing DFA;
    removing either pair of a via-way sequence is never used as a substitute.
    """
    members = rule['relation']['members']
    starts = [m['ref'] for m in members if m['role'] == 'from' and m['type'] == 'way']
    vias = [m['ref'] for m in members if m['role'] == 'via' and m['type'] == 'way']
    ends = [m['ref'] for m in members if m['role'] == 'to' and m['type'] == 'way']
    if len(starts) != 1 or len(ends) != 1 or not vias:
        raise ValueError('Unsupported sequence contract mapping')
    mapped, truncated = _via_way_sequences(starts[0], vias, ends[0],
        {w.get('id'): w for w in osm.findall('way')}, list(links))
    if truncated or mapped != rule['sequences']:
        raise ValueError(rule['relation_id'] + ' directed mapping differs from sequence contract')
    return mapped


def inspect_restrictions(osm_path, network_path, lanes_path):
    """Return {rows, summary} without writing files or changing supplied XML.

    CSV-compatible rows keep the legacy fields. New JSON-valued fields retain
    complete path occurrences and lane evidence; via-way status stays unsupported
    because proving reachability does not implement a history-dependent policy.
    """
    osm = load_xml(osm_path)
    network = load_xml(network_path)
    links = [link for link in network.findall('./links/link')
             if 'car' in link.get('modes', 'car').split(',')]
    nodes = {node.get('id') for node in network.findall('./nodes/node')}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for link in links:
        incoming[(source_way_id(link), link.get('to'))].append(link.get('id'))
        outgoing[(source_way_id(link), link.get('from'))].append(link.get('id'))
    lanes = load_lanes(lanes_path)
    ways = {way.get('id'): way for way in osm.findall('way') if way.get('action') != 'delete'}
    source_nodes = {node.get('id') for node in osm.findall('node') if node.get('action') != 'delete'}
    rows = []
    deleted = 0
    for relation in osm.findall('relation'):
        tags = {tag.get('k'): tag.get('v') for tag in relation.findall('tag')}
        if tags.get('type') != 'restriction':
            continue
        if relation.get('action') == 'delete':
            deleted += 1
            continue
        members = defaultdict(list)
        for member in relation.findall('member'):
            members[(member.get('role'), member.get('type'))].append(member.get('ref'))
        from_ways, to_ways = members[('from', 'way')], members[('to', 'way')]
        via_nodes, via_ways = members[('via', 'node')], members[('via', 'way')]
        missing = [dict(type=member.get('type'), ref=member.get('ref'), role=member.get('role'))
                   for member in relation.findall('member')
                   if (member.get('type') == 'way' and member.get('ref') not in ways)
                   or (member.get('type') == 'node' and member.get('ref') not in source_nodes)]
        semantics = []
        if 'except' in tags:
            semantics.append('mode_exceptions')
        if any(key.endswith(':conditional') for key in tags):
            semantics.append('conditional')
        if any(key.startswith('restriction:') and key != 'restriction:conditional' for key in tags):
            semantics.append('mode_specific_restriction')
        if tags.get('restriction', '') not in ('no_left_turn', 'no_right_turn', 'no_straight_on',
                'no_u_turn', 'no_entry', 'no_exit', 'only_left_turn', 'only_right_turn', 'only_straight_on'):
            semantics.append('unknown_restriction')
        row = dict.fromkeys(FIELDS, '')
        row.update(relation_id=relation.get('id'), restriction=tags.get('restriction', ''),
                   from_ways=';'.join(from_ways), to_ways=';'.join(to_ways),
                   via_nodes=';'.join(via_nodes), via_ways=';'.join(via_ways),
                   lanes_admit_prohibited_target='not_evaluated',
                   osm_tags=_json(tags), missing_members=_json(missing), semantics_review=';'.join(semantics),
                   directed_sequences='[]', sequence_lane_checks='[]', lanes_admit_sequence='not_evaluated')
        if via_ways:
            row.update(status='via_way_unsupported', detail='Requires a path-aware restriction; no node shortcut inferred')
            if len(from_ways) != 1 or len(to_ways) != 1 or via_nodes:
                row['path_status'] = 'unsupported_member_structure'
            elif missing:
                row['path_status'] = 'missing_osm_members'
            else:
                sequences, truncated = _via_way_sequences(from_ways[0], via_ways, to_ways[0], ways, links)
                checks = [[_movement(a, b, lanes) for a, b in zip(sequence, sequence[1:])]
                          for sequence in sequences]
                row.update(path_status='search_limit' if truncated else 'mapped' if sequences else 'no_directed_path',
                           directed_sequences=_json(sequences), sequence_lane_checks=_json(checks),
                           from_links=';'.join(sorted({path[0] for path in sequences})),
                           to_links=';'.join(sorted({path[-1] for path in sequences})))
                if sequences and not truncated:
                    row['lanes_admit_sequence'] = str(any(all(check['admitted'] for check in path)
                                                        for path in checks)).lower()
        elif len(from_ways) != 1 or len(to_ways) != 1 or len(via_nodes) != 1:
            row.update(status='incomplete_or_unsupported_members', detail='Expected one from way, via node and to way in supplied OSM')
        else:
            via = via_nodes[0]
            starts = sorted(incoming[(from_ways[0], via)])
            ends = sorted(outgoing[(to_ways[0], via)])
            row.update(from_links=';'.join(starts), to_links=';'.join(ends))
            if via not in nodes or not starts or not ends:
                missing = ['via_node'] if via not in nodes else []
                if not starts:
                    missing.append('incoming_from_way')
                if not ends:
                    missing.append('outgoing_to_way')
                row.update(status='not_in_network', detail='Missing directed network representation: ' + ','.join(missing))
            else:
                row.update(status='mappable', detail='Directed from/to links share the OSM via node')
                if len(starts) != 1 or len(ends) != 1:
                    row['lane_check'] = 'ambiguous_directed_mapping_requires_review'
                elif not row['restriction'].startswith('no_') or semantics:
                    row['lane_check'] = 'restriction_semantics_require_review'
                else:
                    admitted, terminal_lanes, checks = [], set(), set()
                    for start in starts:
                        for end in ends:
                            if start not in lanes:
                                admitted.append(start + '>' + end)
                                checks.add('no_lane_assignment_connected_graph_admits')
                            elif end in lanes[start]:
                                admitted.append(start + '>' + end)
                                terminal_lanes.update(lanes[start][end])
                                checks.add('reachable_terminal_lane_admits')
                            else:
                                checks.add('lane_graph_excludes')
                    row.update(lanes_admit_prohibited_target=str(bool(admitted)).lower(),
                               admitting_movements=';'.join(admitted),
                               admitting_terminal_lanes=';'.join(sorted(terminal_lanes)),
                               lane_check=';'.join(sorted(checks)))
        rows.append(row)
    rows.sort(key=lambda row: int(row['relation_id']))
    summary = dict(relations=len(rows), statuses=dict(Counter(row['status'] for row in rows)),
                   deleted_relations_ignored=deleted,
                   mappable_lanes_admit=sum(row['status'] == 'mappable' and row['lanes_admit_prohibited_target'] == 'true' for row in rows),
                   mappable_lanes_exclude=sum(row['status'] == 'mappable' and row['lanes_admit_prohibited_target'] == 'false' for row in rows),
                   via_way_paths=dict(Counter(row['path_status'] for row in rows if row['via_ways'])),
                   via_way_lanes_admit=sum(row['lanes_admit_sequence'] == 'true' for row in rows),
                   relations_with_missing_members=sum(bool(json.loads(row['missing_members'])) for row in rows),
                   semantics_review=dict(Counter(reason for row in rows for reason in row['semantics_review'].split(';') if reason)),
                   hashes={name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                           for name, path in [('osm', osm_path), ('network', network_path), ('lanes', lanes_path)]},
                   hashes_lf={name: hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                              for name, path in [('osm', osm_path), ('network', network_path), ('lanes', lanes_path)]},
                   scope='Static car link/lane reachability with useLanes=true; not a simulation or proof of an executed forbidden turn',
                   limitation='prepare_simz1 has no OSM relation conversion and blocks new imports containing restrictions. Lane reachability is audited separately; via-way path reachability is not path-aware enforcement.')
    return dict(rows=rows, summary=summary)


def audit(osm_path, network_path, lanes_path, output_dir):
    result = inspect_restrictions(osm_path, network_path, lanes_path)
    rows, summary = result['rows'], result['summary']
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'osm-turn-restrictions.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (output / 'osm-turn-restrictions-summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--osm', type=Path, default=Path('scenarios/zona1/map.osm'))
    parser.add_argument('--network', type=Path, default=Path('scenarios/zona1/network.xml'))
    parser.add_argument('--lanes', type=Path, default=Path('scenarios/zona1/lanes.xml'))
    parser.add_argument('--output-dir', type=Path, default=Path('runtime/validation/osm-turns'))
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.osm, args.network, args.lanes, args.output_dir), indent=2))


if __name__ == '__main__':
    main()
