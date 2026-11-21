"""Generate exactly one early, fixed trip for temporary microscopic debugging.

Seed and sigma arguments are retained for command compatibility only.
MATSim 15 uses population_v6.dtd (not population_v15.dtd).
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from prepare_simz1 import SCENARIO, components, write_xml

START, END = 7*3600+59*60, 15*3600
DEBUG_ORIGIN = 'osm_30262980_15_forward'
DEBUG_APPROACH = 'osm_1174627094_0_forward'
DEBUG_DESTINATION = 'osm_384746799_0_forward'
DEBUG_DEPARTURE = 8*3600
DEBUG_PERSON = 'agente_prueba_01'


def principal_links(network_path, expected_nodes=None):
    root = ET.parse(network_path).getroot()
    if root.tag != 'network':
        raise ValueError('Expected MATSim network XML')
    nodes = [n.get('id') for n in root.findall('nodes/node')]
    if len(set(nodes)) != len(nodes) or None in nodes:
        raise ValueError('Missing or duplicate node IDs')
    node_ids = set(nodes)
    links, ids = [], set()
    for element in root.findall('links/link'):
        link = element.attrib
        if not link.get('id') or link['id'] in ids:
            raise ValueError('Missing or duplicate link IDs')
        ids.add(link['id'])
        if link.get('from') not in node_ids or link.get('to') not in node_ids:
            raise ValueError(f"Dangling endpoint on link {link['id']}")
        if 'car' in {mode.strip() for mode in link.get('modes', 'car').split(',')}:
            links.append(link)
    groups = components(links)
    if not groups:
        raise ValueError('No directed car component found')
    if expected_nodes is not None:
        if type(expected_nodes) is not int or expected_nodes < 1:
            raise ValueError('Expected component size must be a positive integer')
        if len(groups[0]) != expected_nodes:
            raise ValueError(f'Expected principal car component of {expected_nodes} nodes; found {len(groups[0])}')
    if len(groups) > 1 and len(groups[0]) == len(groups[1]):
        raise ValueError('Ambiguous principal component (equal sizes)')
    core = groups[0]
    eligible = sorted((l['id'] for l in links if l['from'] in core and l['to'] in core))
    if len(eligible) < 2:
        raise ValueError('At least two internal car links required')
    return core, eligible, len(ids), len(groups)


def debug_population(network_path, expected_nodes=None, signals_path=None):
    """Build the fixed signal-debug trip, independently of scalable population modes."""
    network_path = Path(network_path)
    core, links, total, groups = principal_links(network_path, expected_nodes)
    if DEBUG_ORIGIN == DEBUG_DESTINATION or not {DEBUG_ORIGIN, DEBUG_APPROACH, DEBUG_DESTINATION} <= set(links):
        raise ValueError('Debug OD must be distinct links inside the principal car component')
    network = ET.parse(network_path)
    by_id = {l.get('id'): l for l in network.findall('links/link')}
    origin, approach, destination = (by_id[i] for i in (DEBUG_ORIGIN, DEBUG_APPROACH, DEBUG_DESTINATION))
    exits = {l.get('id') for l in by_id.values() if l.get('from') == origin.get('to')
             and 'car' in {m.strip() for m in l.get('modes', 'car').split(',')}}
    signal_node = network.find(f"nodes/node[@id='{approach.get('to')}']")
    if (exits != {DEBUG_APPROACH} or approach.get('to') != destination.get('from') or
            signal_node.findtext("attributes/attribute[@name='osm:highway']") != 'traffic_signals'):
        raise ValueError('Debug trip must force passage through a traffic_signals node')
    controlled = {s.get('linkIdRef') for s in ET.parse(signals_path or network_path.with_name('signalSystems.xml')).findall('.//{*}signal')}
    if DEBUG_APPROACH not in controlled:
        raise ValueError('Debug approach must have an active signal definition')
    # This explicit debug mode never sets a limit on the scalable generator.
    root = ET.Element('population', desc='SimZ1 temporary single-agent microscopic debugging')
    person = ET.SubElement(root, 'person', id=DEBUG_PERSON)
    plan = ET.SubElement(person, 'plan', selected='yes')
    ET.SubElement(plan, 'activity', type='home', link=DEBUG_ORIGIN, end_time='08:00:00')
    ET.SubElement(plan, 'leg', mode='car')
    ET.SubElement(plan, 'activity', type='work', link=DEBUG_DESTINATION)
    report = dict(mode='debug', agents=1, trips=1, network_sha256=hashlib.sha256(network_path.read_bytes()).hexdigest(),
                  core_nodes=len(core), eligible_links=len(links), excluded_links=total-len(links),
                  car_strong_components=groups, departure_distribution='fixed debug departure',
                  debug_agent=DEBUG_PERSON, origin_link=DEBUG_ORIGIN, destination_link=DEBUG_DESTINATION,
                  controlled_approach=DEBUG_APPROACH, traffic_signal_node=approach.get('to'),
                  window_seconds=[START, END], departure_min=DEBUG_DEPARTURE, departure_max=DEBUG_DEPARTURE,
                  sampled_mean_seconds=DEBUG_DEPARTURE, departures_by_hour={'08:00':1},
                  od_distribution='fixed distinct directed links inside the largest car SCC',
                  dtd='population_v6.dtd (MATSim 15)',
                  limitations=['Departure window does not guarantee arrival before 15:00',
                               'Graph reachability excludes unimplemented turn restrictions',
                               'Temporary debug demand; seed and sigma do not affect the fixed trip'])
    return root, report


def generate(network_path, output_path, count=1, seed=20261002,
             sigma_seconds=3600.0, expected_nodes=None):
    network_path, output_path = Path(network_path), Path(output_path)
    if network_path.resolve() == output_path.resolve():
        raise ValueError('Output must not overwrite the network')
    if output_path.exists() or output_path.with_suffix('.report.json').exists():
        raise ValueError('Output/report already exists; debug must not overwrite a saved scenario')
    if type(count) is not int or count != 1:
        raise ValueError('Explicit debug mode requires exactly 1 agent')
    if not math.isfinite(sigma_seconds) or sigma_seconds <= 0:
        raise ValueError('Sigma must be positive and finite')
    root, report = debug_population(network_path, expected_nodes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_xml(output_path, root, 'population_v6.dtd')
    # Count the actual XML, not the requested count.
    actual = ET.parse(output_path).findall('person')
    if len(actual) != 1 or actual[0].get('id') != DEBUG_PERSON:
        raise ValueError('Debug population verification failed')
    report.update(seed=seed, plans_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest())
    output_path.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', type=Path, default=SCENARIO/'network.xml')
    parser.add_argument('--output', type=Path, required=True, help='Archivo nuevo; nunca sobrescribe planes guardados')
    parser.add_argument('--mode', choices=['debug'], default='debug')
    parser.add_argument('--agents', type=int, choices=[1], default=1)
    parser.add_argument('--seed', type=int, default=20261002)
    parser.add_argument('--sigma-hours', type=float, default=1.0)
    parser.add_argument('--expected-core-nodes', type=int, help='Comprobacion opcional de un snapshot; no es una invariante topologica')
    args = parser.parse_args()
    try:
        report = generate(args.network, args.output, args.agents, args.seed,
                          args.sigma_hours*3600, args.expected_core_nodes)
    except (ValueError, OSError, ET.ParseError) as exc:
        parser.exit(1, f'Demand generation failed: {exc}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
