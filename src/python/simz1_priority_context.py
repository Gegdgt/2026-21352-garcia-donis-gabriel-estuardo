"""Read-only policy evidence for historical car-only priority instrumentation.

Never recover policy from the decision being checked or from an ID prefix.
Only a verified fixed-fleet bus on a bus-only link may use this compatibility
path. All ordinary HEAD/GO/CROSS and native movement checks remain mandatory.
"""
from collections import defaultdict
import gzip
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_priority_classification import attributes, classify, MODES

VERSION = 'verified-bus-priority-context-v1'
PRIORITY_ATTRIBUTES = ('simz1:priorityRole', 'simz1:priorityControl', 'osm:name', 'osm:highway')


def _document(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        root = ET.parse(stream).getroot()
    # MATSim output may use an XML namespace; never rewrite the source file.
    for row in root.iter():
        row.tag = row.tag.rsplit('}', 1)[-1]
    return root


def _network(root):
    if root.tag != 'network':
        raise ValueError('Priority context: network XML root required')
    nodes, links = {}, {}
    for row in root.findall('./nodes/node'):
        key = row.get('id')
        if not key or key in nodes:
            raise ValueError('Priority context: missing or duplicate node')
        xy = tuple(float(row.get(k, 'nan')) for k in ('x', 'y'))
        if not all(math.isfinite(value) for value in xy):
            raise ValueError('Priority context: nonfinite node coordinates')
        nodes[key] = row
    for row in root.findall('./links/link'):
        key = row.get('id')
        if not key or key in links or row.get('from') not in nodes or row.get('to') not in nodes:
            raise ValueError('Priority context: invalid directed link or missing node')
        links[key] = row
    return nodes, links


def _signature(nodes, links):
    return (
        {key: (float(row.get('x')), float(row.get('y')),
               tuple(attributes(row).get(k, '') for k in ('osm:highway', 'highway')))
         for key, row in nodes.items()},
        {key: (row.get('from'), row.get('to'), _modes(row),
               tuple(attributes(row).get(k, '') if k.startswith('osm:') else attributes(row).get(k)
                     for k in PRIORITY_ATTRIBUTES))
         for key, row in links.items()},
    )


def _modes(link):
    return frozenset(value.strip() for value in link.get('modes', 'car').split(','))


def build_bus_context(directory, manifest, effective, contract):
    """Derive effective policies from this run's hashed inputs, not today's map.

    An absent priority module does NOT get guessed defaults. In that situation
    the regular event-only audit stays strict and rejects an unregistered policy.
    validate_outputs verifies configuration and signals before calling this.
    """
    if not contract['vehicle_modes'] or not any(k.startswith('zona1Priority.') for k in effective):
        return None
    from simz1_run import checked_path, parameters, sha256
    directory = Path(directory).resolve()
    for record in manifest['inputs'].values():
        checked_path(directory, record)
    keys = ('enabled', 'classification', 'stopSeconds', 'conflicts', 'maxYieldSeconds')
    if any('zona1Priority.'+key not in effective for key in keys):
        raise ValueError('Priority context: incomplete effective priority configuration')
    requested = parameters(directory/'config-simz1.xml')
    settings = {key: effective['zona1Priority.'+key] for key in keys}
    if settings['enabled'] not in ('true', 'false') or settings['classification'] not in MODES:
        raise ValueError('Priority context: invalid enabled/classification setting')
    if settings['conflicts'] not in ('geometric', 'conservative', 'verified-node-table'):
        raise ValueError('Priority context: invalid conflict policy')
    for key in ('stopSeconds', 'maxYieldSeconds'):
        value = float(settings[key])
        if not math.isfinite(value) or value < 0:
            raise ValueError('Priority context: invalid '+key)
        settings[key] = value
    for key in keys:
        name = 'zona1Priority.'+key
        if name in requested:
            value = float(requested[name]) if key in ('stopSeconds', 'maxYieldSeconds') else requested[name]
            if value != settings[key]:
                raise ValueError('Priority context: requested/effective setting differs: '+name)
    network = checked_path(directory, manifest['inputs']['network'])
    nodes, links = _network(_document(network))
    output_network = directory/'output/output_network.xml.gz'
    actual_nodes, actual_links = _network(_document(output_network))
    if _signature(nodes, links) != _signature(actual_nodes, actual_links):
        raise ValueError('Priority context: loaded priority attributes/topology differ from fingerprinted network')
    enabled_signals = effective.get('signalsystems.useSignalsystems')
    if enabled_signals not in ('true', 'false'):
        raise ValueError('Priority context: effective signal activation unavailable')
    controlled = set()
    signals = directory/'output/output_signal_systems_v2.0.xml.gz'
    if enabled_signals == 'true':
        if not signals.is_file():
            raise ValueError('Priority context: loaded signals unavailable')
        for row in _document(signals).iter():
            ref = (row.get('refId') if row.tag == 'linkId' else
                   row.get('linkIdRef') if row.tag == 'signal' else None)
            if ref is not None:
                if ref not in links:
                    raise ValueError('Priority context: signal references unknown link')
                controlled.add(links[ref].get('to'))
    road = {key: row for key, row in links.items() if _modes(row) & {'car', 'bus'}}
    roles = {key: classify(row, nodes, settings['classification']) for key, row in road.items()}
    incoming = defaultdict(list)
    for key, row in road.items():
        incoming[row.get('to')].append(key)
    policies, bus_only = {}, {}
    for node, ids in incoming.items():
        node_attrs = attributes(nodes[node])
        eligible = (settings['enabled'] == 'true' and node not in controlled and
                    node_attrs.get('osm:highway') != 'traffic_signals' and
                    node_attrs.get('highway') != 'traffic_signals' and
                    {roles[key][0] for key in ids} == {'street', 'avenue'})
        for key in ids:
            row = road[key]
            role, source = roles[key]
            explicit = attributes(row).get('simz1:priorityControl')
            if explicit is not None and (explicit not in ('stop', 'yield') or role != 'street'):
                raise ValueError('Priority context: invalid stop/yield control on '+key)
            control = (explicit or 'stop') if role == 'street' else 'free'
            policy = dict(node=node, link=key, enabled=settings['enabled'], eligible=str(eligible).lower(),
                controlled=str(node in controlled).lower(), role=role, classificationSource=source,
                stopSeconds=str(settings['stopSeconds']), conflictPolicy=settings['conflicts'],
                control=control, controlSource='network_attribute' if explicit is not None else 'modeled_default',
                appliedStopSeconds=str(max(5., settings['stopSeconds']) if eligible and control == 'stop' else 0.),
                maxYieldSeconds=str(settings['maxYieldSeconds']))
            policies[(node, key)] = policy
            if 'bus' in _modes(row) and 'car' not in _modes(row) and key in contract['domain_links']:
                bus_only[key] = policy
    evidence = dict(version=VERSION, basis='fingerprinted_run_inputs_and_matching_loaded_network',
        input_network_sha256=sha256(network), output_network_sha256=sha256(output_network),
        effective_config_sha256=sha256(directory/'output/output_config.xml'),
        effective_signals_sha256=sha256(signals) if enabled_signals == 'true' else None,
        events_modified=False, physics_changed=False)
    return dict(expected=policies, bus_only=bus_only, vehicle_modes=dict(contract['vehicle_modes']),
                evidence=evidence)
