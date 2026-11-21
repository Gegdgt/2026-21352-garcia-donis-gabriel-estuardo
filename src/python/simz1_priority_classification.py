"""Reproducible SimZ1 priority catalogue; no traffic simulation or surveyed signs.

The classification mirrors UnsignalizedPriority.classify. Overrides address an
individual directed link (optionally guarded by its destination intersection).
The input network is never rewritten by this command.
"""
import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET


MAJOR = {'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary',
         'primary_link', 'secondary', 'secondary_link'}
MINOR = {'tertiary', 'tertiary_link', 'residential', 'unclassified'}
SERVICE = {'service', 'living_street'}
MODES = {'osm-hierarchy', 'osm-name-orientation', 'orientation', 'explicit'}
OVERRIDE_FIELDS = ('link_id', 'to_node', 'priority_role', 'priority_control', 'source', 'rationale')


def attributes(element):
    return {a.get('name'): a.text or '' for a in element.findall('./attributes/attribute')}


def set_attribute(element, key, value):
    block = element.find('attributes')
    if block is None:
        block = ET.SubElement(element, 'attributes')
    entry = next((a for a in block.findall('attribute') if a.get('name') == key), None)
    if entry is None:
        entry = ET.SubElement(block, 'attribute', name=key, **{'class': 'java.lang.String'})
    entry.text = value


def classify(link, nodes, mode='osm-hierarchy'):
    if mode not in MODES:
        raise ValueError(f'Unknown classification {mode}')
    attrs = attributes(link)
    if 'simz1:priorityRole' in attrs:
        if attrs['simz1:priorityRole'] not in ('avenue', 'street'):
            raise ValueError(f'Invalid priority role: {link.get("id")}')
        return attrs['simz1:priorityRole'], 'network_attribute'
    if mode == 'explicit':
        raise ValueError(f'Missing explicit priority role: {link.get("id")}')
    highway = attrs.get('osm:highway', '').lower()
    if mode == 'osm-hierarchy':
        if highway in SERVICE:
            return 'street', 'osm_highway_service_assumption'
        if highway in MAJOR:
            return 'avenue', 'osm_highway_major_assumption'
    if mode in ('osm-hierarchy', 'osm-name-orientation'):
        name = ''.join(c for c in unicodedata.normalize('NFKD', attrs.get('osm:name', ''))
                       if not unicodedata.combining(c)).lower()
        words = set(re.split('[^a-z]+', name))
        avenue = bool(words & {'avenida', 'bulevar', 'boulevard', 'calzada'})
        street = 'calle' in words
        if avenue != street:
            return ('avenue' if avenue else 'street',
                    'osm_name_assumption' if mode == 'osm-hierarchy' else 'osm_name_synthetic_rule')
    if mode == 'osm-hierarchy' and highway in MINOR:
        return 'street', 'osm_highway_minor_assumption'
    start, end = nodes[link.get('from')], nodes[link.get('to')]
    horizontal = abs(float(end.get('x')) - float(start.get('x'))) > abs(float(end.get('y')) - float(start.get('y')))
    return 'street' if horizontal else 'avenue', 'orientation_approximation'


def apply_overrides(network, path):
    """Validate all rows before applying a precise, documented directed-link table."""
    links = {link.get('id'): link for link in network.findall('./links/link')}
    nodes = {node.get('id'): node for node in network.findall('./nodes/node')}
    rows, seen = [], set()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(OVERRIDE_FIELDS):
            raise ValueError('Override columns must be ' + ','.join(OVERRIDE_FIELDS))
        for line, raw in enumerate(reader, 2):
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f'Malformed override row {line}')
            row = {key: value.strip() for key, value in raw.items()}
            key = row['link_id']
            if key in seen or key not in links:
                raise ValueError(f'Unknown/duplicate override link {key!r} at row {line}')
            seen.add(key)
            link = links[key]
            if 'car' not in link.get('modes', 'car').split(','):
                raise ValueError(f'Override link is not drivable: {key}')
            if row['to_node'] and row['to_node'] != link.get('to'):
                raise ValueError(f'Override intersection mismatch: {key}')
            if row['priority_role'] not in ('', 'avenue', 'street') or row['priority_control'] not in ('', 'stop', 'yield'):
                raise ValueError(f'Invalid override role/control: {key}')
            if not (row['priority_role'] or row['priority_control']) or not row['source'] or not row['rationale']:
                raise ValueError(f'Override requires a change, source and rationale: {key}')
            role = row['priority_role'] or classify(link, nodes)[0]
            control = row['priority_control'] or attributes(link).get('simz1:priorityControl', '')
            if control and role != 'street':
                raise ValueError(f'Stop/yield only applies to a secondary approach: {key}')
            rows.append(row)
    for row in rows:
        link = links[row['link_id']]
        for field, key in (('priority_role', 'simz1:priorityRole'), ('priority_control', 'simz1:priorityControl'),
                           ('source', 'simz1:priorityOverrideSource'), ('rationale', 'simz1:priorityOverrideRationale')):
            if row[field]:
                set_attribute(link, key, row[field])
    return len(rows)


def signal_nodes(signals, links):
    controlled = set()
    if signals is not None:
        for element in ET.parse(signals).getroot().iter():
            local_name = element.tag.rsplit('}', 1)[-1]
            if local_name == 'linkId' or (local_name == 'signal' and element.get('linkIdRef')):
                link_id = element.get('linkIdRef') if local_name == 'signal' else element.get('refId')
                if link_id not in links:
                    raise ValueError(f'Signal references absent link: {link_id}')
                controlled.add(links[link_id].get('to'))
    return controlled


def catalogue(network, signals=None, mode='osm-hierarchy'):
    nodes = {node.get('id'): node for node in network.findall('./nodes/node')}
    links = {link.get('id'): link for link in network.findall('./links/link')
             if 'car' in link.get('modes', 'car').split(',')}
    controlled = signal_nodes(signals, links)
    incoming, outgoing = defaultdict(list), Counter()
    roles = {key: classify(link, nodes, mode) for key, link in links.items()}
    previous = {key: classify(link, nodes, 'osm-name-orientation') for key, link in links.items()}
    for key, link in links.items():
        incoming[link.get('to')].append(key)
        outgoing[link.get('from')] += 1
    node_rows, link_rows = [], []
    eligible_nodes, before_nodes = set(), set()
    for key, node in sorted(nodes.items()):
        approaches = sorted(incoming[key])
        attrs = attributes(node)
        tagged_signal = attrs.get('osm:highway') == 'traffic_signals' or attrs.get('highway') == 'traffic_signals'
        excluded = 'native_signals' if key in controlled else 'osm_traffic_signals' if tagged_signal else ''
        mixed = {roles[link][0] for link in approaches} == {'street', 'avenue'}
        before_mixed = {previous[link][0] for link in approaches} == {'street', 'avenue'}
        eligible = mixed and not excluded
        before = before_mixed and not excluded
        if eligible:
            eligible_nodes.add(key)
        if before:
            before_nodes.add(key)
        node_rows.append(dict(node_id=key, x=node.get('x'), y=node.get('y'),
            incoming_car=len(approaches), outgoing_car=outgoing[key],
            eligible=str(eligible).lower(), eligible_before=str(before).lower(), excluded=excluded,
            priority_links=';'.join(link for link in approaches if roles[link][0] == 'avenue'),
            secondary_links=';'.join(link for link in approaches if roles[link][0] == 'street'),
            orientation_links=';'.join(link for link in approaches if roles[link][1] == 'orientation_approximation'),
            sources=';'.join(sorted({roles[link][1] for link in approaches}))))
        for link_id in approaches:
            link, (role, source) = links[link_id], roles[link_id]
            link_attrs = attributes(link)
            control = link_attrs.get('simz1:priorityControl', 'stop') if role == 'street' else 'free'
            if 'simz1:priorityControl' in link_attrs and (control not in ('stop', 'yield') or role != 'street'):
                raise ValueError(f'Invalid priority control: {link_id}')
            effective_control = control if eligible else 'not_applied'
            link_rows.append(dict(node_id=key, link_id=link_id, from_node=link.get('from'),
                osm_way=link.get('origid', ''), osm_name=link_attrs.get('osm:name', ''),
                osm_highway=link_attrs.get('osm:highway', ''), role=role, classification_source=source,
                role_before=previous[link_id][0], source_before=previous[link_id][1],
                control_before=('stop' if previous[link_id][0] == 'street' else 'free') if before else 'not_applied',
                eligible=str(eligible).lower(), excluded=excluded, configured_control=control,
                effective_control=effective_control,
                stop_seconds=5 if effective_control == 'stop' else 0,
                control_source='network_attribute' if 'simz1:priorityControl' in link_attrs else 'modeled_default',
                override_source=link_attrs.get('simz1:priorityOverrideSource', ''),
                override_rationale=link_attrs.get('simz1:priorityOverrideRationale', '')))
    summary = dict(classification=mode, baseline_classification='osm-name-orientation',
        stop_seconds_assumption=5, native_signal_input_provided=signals is not None,
        nodes=len(nodes), car_links=len(links), native_signal_nodes=len(controlled),
        eligible_nodes=len(eligible_nodes), eligible_nodes_before=len(before_nodes),
        no_longer_eligible=sorted(before_nodes - eligible_nodes), newly_eligible=sorted(eligible_nodes - before_nodes),
        classification_sources=dict(Counter(row['classification_source'] for row in link_rows)),
        roles=dict(Counter(row['role'] for row in link_rows)),
        role_changes=sum(row['role'] != row['role_before'] for row in link_rows),
        effective_controls=dict(Counter(row['effective_control'] for row in link_rows)),
        previous_controls=dict(Counter(row['control_before'] for row in link_rows)),
        orientation_fallback_nodes=sorted({row['node_id'] for row in link_rows if row['classification_source'] == 'orientation_approximation'}),
        orientation_fallback_eligible_nodes=sorted({row['node_id'] for row in link_rows if row['classification_source'] == 'orientation_approximation' and row['eligible'] == 'true'}),
        limitations=['Priority and default five-second stops are configured modeling assumptions, not surveyed signs.',
                     'Avenue denotes the priority role, including OSM primary/secondary arterial calles.',
                     'No changes to directions, permitted turns, signals, speed, lanes or capacity.',
                     'Eligibility is a static policy inventory, not evidence of vehicles waiting or crossing.'])
    return link_rows, node_rows, summary


def export(network_path, output, signals=None, mode='osm-hierarchy', overrides=None):
    network = ET.parse(network_path).getroot()
    override_count = apply_overrides(network, overrides) if overrides else 0
    link_rows, node_rows, summary = catalogue(network, signals, mode)
    summary.update(network_sha256=hashlib.sha256(Path(network_path).read_bytes()).hexdigest(),
                   overrides_applied=override_count)
    if signals:
        summary['signals_sha256'] = hashlib.sha256(Path(signals).read_bytes()).hexdigest()
    if overrides:
        summary['overrides_sha256'] = hashlib.sha256(Path(overrides).read_bytes()).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (('priority-links.csv', link_rows), ('priority-intersections.csv', node_rows)):
        with (output / filename).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (output / 'classification-summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', type=Path, default=Path('scenarios/zona1/network.xml'))
    parser.add_argument('--signals', type=Path, default=Path('scenarios/zona1/signalSystems.xml'))
    parser.add_argument('--output-dir', type=Path, default=Path('runtime/validation/priority-classification'))
    parser.add_argument('--classification', choices=sorted(MODES), default='osm-hierarchy')
    parser.add_argument('--overrides', type=Path)
    args = parser.parse_args(argv)
    summary = export(args.network, args.output_dir, args.signals, args.classification, args.overrides)
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ('no_longer_eligible', 'newly_eligible')}, indent=2))


if __name__ == '__main__':
    main()
