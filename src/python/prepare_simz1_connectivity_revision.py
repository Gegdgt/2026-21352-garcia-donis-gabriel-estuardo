"""Prepare a SMALL, NON-RUNNABLE SimZ1 scenario revision proposal.

Only new JSON patch/provenance files are written, never network/lanes/population,
historical artifacts or executable config. OSM via-way constraints are retained
as sequences requiring a path-aware implementation, never flattened into turns.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_osm_turn_audit import inspect_restrictions, load_lanes
from simz1_run_directory import check_new_directory

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {'osm': 'map.osm', 'network': 'network.xml', 'lanes': 'lanes.xml',
          'signals': 'signalSystems.xml', 'groups': 'signalGroups.xml',
          'control': 'signalControl.xml', 'config': 'config-simz1.xml'}
OD_CASES = ['internal-internal', 'internal-external', 'external-internal', 'external-external']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def xml(path):
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    return root


def source(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    try:
        name = path.relative_to(ROOT).as_posix()
    except ValueError:
        name = str(path)
    return dict(path=name, bytes=len(raw), sha256=digest(raw), sha256_lf=digest(raw.replace(b'\r\n', b'\n')))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def build_revision(directory):
    """Read current inputs; return a declarative proposal, not corrected XML."""
    directory = Path(directory)
    paths = {key: directory / filename for key, filename in INPUTS.items()}
    inputs = {key: source(path) for key, path in paths.items()}
    tools = {key: source(ROOT / 'python' / filename) for key, filename in
             [('planner', 'prepare_simz1_connectivity_revision.py'),
              ('restriction_auditor', 'simz1_osm_turn_audit.py'),
              ('connectivity_reviewer', 'simz1_connectivity_review.py')]}
    report = inspect_restrictions(paths['osm'], paths['network'], paths['lanes'])
    network, lane_root, signals = xml(paths['network']), xml(paths['lanes']), xml(paths['signals'])
    links = {link.get('id'): link for link in network.findall('links/link')}
    assignments = {a.get('linkIdRef'): {lane.get('id'): lane for lane in a.findall('lane')}
                   for a in lane_root.findall('lanesToLinkAssignment')}
    exits = load_lanes(paths['lanes'])
    operations, unresolved, conflicts = [], [], []
    # Restrict only unique, unconditional car via-node relations for which
    # the auditor proves an admitted prohibited movement. Everything else
    # remains explicit evidence pending further implementation/source review.
    for row in report['rows']:
        tags = json.loads(row['osm_tags']) if isinstance(row['osm_tags'], str) else row['osm_tags']
        starts, ends = row['from_links'].split(';'), row['to_links'].split(';')
        simple = (row['status'] == 'mappable' and len(starts) == len(ends) == 1 and starts[0] and ends[0]
                  and row['restriction'].startswith('no_') and not row['via_ways']
                  and not json.loads(row.get('missing_members') or '[]') and not row.get('semantics_review')
                  and not any(key.startswith('restriction:') or key == 'except' for key in tags))
        if not simple or str(row['lanes_admit_prohibited_target']).lower() != 'true':
            unresolved.append(row)
            continue
        before, after = starts[0], ends[0]
        if before not in links or after not in links or links[before].get('to') != links[after].get('from'):
            raise ValueError('Audited movement lacks exact directed-node correspondence')
        terminals = sorted(exits.get(before, {}).get(after, ()))
        if not terminals:
            conflicts.append(dict(relation_id=row['relation_id'], reason='no_terminal_lane_mapping'))
            continue
        for lane_id in terminals:
            lane = assignments[before][lane_id]
            old = sorted(t.get('refId') for t in lane.findall('leadsTo/toLink'))
            if after not in old:
                raise ValueError('Audited target absent from terminal lane')
            operations.append(dict(relation_id=row['relation_id'], operation='remove_terminal_toLink', mode='car',
                link_id=before, lane_id=lane_id, target_link_id=after, via_node=links[before].get('to'),
                expected_targets=old, proposed_targets=[target for target in old if target != after],
                evidence=dict(osm_relation=row['relation_id'], restriction=row['restriction'],
                              from_way=row['from_ways'], to_way=row['to_ways'])))

    # Validate combined removals, not just each operation in isolation.
    proposed = {}
    for op in operations:
        key = (op['link_id'], op['lane_id'])
        proposed.setdefault(key, set(op['expected_targets'])).discard(op['target_link_id'])
    for (link_id, lane_id), targets in sorted(proposed.items()):
        if not targets:
            conflicts.append(dict(link_id=link_id, lane_id=lane_id, reason='would_empty_terminal_lane'))
    combined = [dict(link_id=link, lane_id=lane,
                    expected_targets=sorted(t.get('refId') for t in assignments[link][lane].findall('leadsTo/toLink')),
                    final_targets=sorted(targets),
                    relation_ids=sorted({op['relation_id'] for op in operations
                                         if (op['link_id'], op['lane_id']) == (link, lane)}, key=int))
                for (link, lane), targets in sorted(proposed.items())]
    signal_checks = []
    for system in signals.findall('signalSystem'):
        for signal in system.findall('signals/signal'):
            link_id = signal.get('linkIdRef')
            turning_moves = {m.get('refId') for m in signal.findall('turningMoveRestrictions/toLink')}
            if link_id not in links:
                conflicts.append(dict(reason='signal_link_missing', signal_id=signal.get('id'), link_id=link_id))
            for lane in signal.findall('lane'):
                lane_id = lane.get('refId')
                if lane_id not in assignments.get(link_id, {}):
                    conflicts.append(dict(reason='signal_lane_missing', signal_id=signal.get('id'), lane_id=lane_id))
                if (link_id, lane_id) in proposed:
                    removed = {t.get('refId') for t in assignments[link_id][lane_id].findall('leadsTo/toLink')} - proposed[link_id, lane_id]
                    if turning_moves & removed:
                        conflicts.append(dict(reason='signal_turning_move_requires_review',
                            system_id=system.get('id'), signal_id=signal.get('id'), lane_id=lane_id,
                            targets=sorted(turning_moves & removed)))
                    signal_checks.append(dict(system_id=system.get('id'), signal_id=signal.get('id'),
                        link_id=link_id, lane_id=lane_id, reference_preserved=True,
                        terminal_has_exit=bool(proposed[link_id, lane_id]),
                        turning_moves=sorted(turning_moves)))
            # A signal without lane references can still control specific turns.
            if not signal.findall('lane'):
                removed = {op['target_link_id'] for op in operations if op['link_id'] == link_id}
                if turning_moves & removed:
                    conflicts.append(dict(reason='signal_turning_move_requires_review',
                        system_id=system.get('id'), signal_id=signal.get('id'), link_id=link_id,
                        targets=sorted(turning_moves & removed)))
    # The present validator intentionally specifies the old all-exits lane
    # model. Do NOT weaken it to pass a proposed restriction. A future explicit
    # OSM-backed validation contract is required before executable publication.
    blockers = [dict(reason='native_path_restrictions_and_source_review_pending', relations=unresolved),
                dict(reason='current_lane_validation_requires_all_adjacent_car_exits',
                     source='python/simz1_lane_validation.py:audit_configuration',
                     required='new versioned OSM-backed contract; retain physical/storage validations'),
                dict(reason='approved_administrative_boundary_not_supplied',
                     required='reviewed boundary and provenance for all four OD cases; extract bbox is not approval')]
    blockers.extend(conflicts)
    input_key = digest(canonical({group: {k: v['sha256'] for k, v in rows.items()}
                                  for group, rows in [('inputs', inputs), ('tools', tools)]}))[:12]
    revision = dict(schema_version=1, version_id='simz1-connectivity-review-v1-' + input_key,
        status='review_only_blocked', runnable=False, target_matsim='15.0', inputs=inputs, tool_sources=tools,
        physical_network_changes=[], lane_movement_operations=len(operations),
        unique_via_node_relations=sorted({op['relation_id'] for op in operations}, key=int),
        patch_semantics='proposal_only; no changes applied to network, lanes, signals, demand or runs',
        id_correspondence=dict(network_nodes='identity', network_links='identity', lane_ids='identity',
            signal_ids='identity', added_ids=[], removed_ids=[],
            network_link_count=len(links), network_link_ids_sha256=digest(canonical(sorted(links))),
            modified_lane_ids=[dict(old=lane, new=lane, link_id=link) for link, lane in sorted(proposed)]),
        compatibility=dict(signal_references=signal_checks, conflicts=conflicts,
            physical_lane_parameters='unchanged', signal_groups_cycles_offsets='unchanged, source hashes pinned',
            native_routing_and_queue_validation='pending; proposal is not an executable scenario'),
        od=dict(required_cases=OD_CASES, retained=True, boundary_approved=False,
            administrative_boundary=None, exterior_travel_times='unknown'),
        blockers=blockers, audit_summary=report['summary'],
        preservation=dict(retain_all_components=True, proximity_connections=False,
                          bridge_tunnel_merges=False, historical_runs_modified=False))
    patch = dict(schema_version=1, version_id=revision['version_id'], apply_allowed=False,
        source_network_sha256=inputs['network']['sha256'], source_lanes_sha256=inputs['lanes']['sha256'],
        application_semantics='atomic removals from pinned base; combined_lane_targets is authoritative, never sequential target replacement',
        operations=operations, combined_lane_targets=combined, unresolved_restrictions=unresolved)
    return revision, patch


def write_new_proposal(output, revision, patch):
    """Claim a NEW directory. Never replace/reuse even an empty old folder."""
    output = check_new_directory(output)
    output.mkdir(parents=True, exist_ok=False)
    for filename, value in [('scenario-revision.json', revision), ('lane-movement-proposal.json', patch)]:
        with (output / filename).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=ROOT / 'scenarios/zona1')
    parser.add_argument('--output-new', type=Path, help='NEW directory for JSON proposal only; omit for stdout/read-only')
    parser.add_argument('--include-sector-review', action='store_true', help='Include focal per-link evidence, not network edits')
    args = parser.parse_args(argv)
    revision, patch = build_revision(args.scenario)
    if args.include_sector_review:
        from simz1_connectivity_review import analyze
        revision['sector_review'] = analyze(*(args.scenario / INPUTS[key] for key in ('osm', 'network', 'lanes')))
    output = write_new_proposal(args.output_new, revision, patch) if args.output_new else None
    print(json.dumps(dict(version_id=revision['version_id'], status=revision['status'], runnable=False,
        via_node_relations=revision['unique_via_node_relations'], operations=len(patch['operations']),
        unresolved_relations=[row['relation_id'] for row in patch['unresolved_restrictions']],
        compatibility=revision['compatibility'], output=str(output) if output else None), indent=2))


if __name__ == '__main__':
    main()
