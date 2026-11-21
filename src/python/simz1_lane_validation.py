"""SimZ1 lane/input audit, pinned to MATSim 15 queue semantics.

This checks the parallel-queue model emitted by LanesGenerator, not a general
turn-restriction importer. Storage figures are baseline analytical queue limits,
not observed occupancy or evidence of physical stability.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_config_validation import ConfigurationError


def _fail(message):
    raise ConfigurationError('Configuracion invalida: coherencia de carriles: ' + message)


def _xml(path):
    path = Path(path)
    try:
        with (gzip.open(path, 'rb') if path.suffix == '.gz' else path.open('rb')) as stream:
            root = ET.parse(stream).getroot()
    except (OSError, ET.ParseError) as exc:
        _fail(f'no se puede leer {path}: {exc}')
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    return root


def _number(value, label, positive=True):
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(f'{label} no es numerico: {value}')
    if not math.isfinite(number) or positive and number <= 0:
        _fail(f'{label} debe ser finito' + (' y positivo' if positive else ''))
    return number


def _time(value, label='tiempo', positive=True):
    """MATSim reads numeric seconds but serializes time values as HH:mm:ss."""
    if ':' not in value:
        return _number(value, label, positive)
    try:
        h, m, s = map(float, value.split(':'))
    except (TypeError, ValueError):
        _fail(f'{label} debe ser segundos numericos o HH:mm:ss: {value}')
    return _number(h*3600+m*60+s, label, positive)


def _same(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _references(elements, label):
    refs = [element.get('refId') for element in elements]
    if any(not value for value in refs) or len(refs) != len(set(refs)):
        _fail(f'{label}: referencia ausente o duplicada')
    return sorted(refs)


def read_network(path):
    root = _xml(path)
    nodes = {}
    for e in root.findall('nodes/node'):
        ident = e.get('id')
        if not ident or ident in nodes:
            _fail(f'nodo ausente/duplicado: {ident}')
        nodes[ident] = (_number(e.get('x'), f'{ident}.x', False),
                        _number(e.get('y'), f'{ident}.y', False))
    links, outgoing = {}, {}
    container = root.find('links')
    if container is None:
        _fail('network sin links')
    period = _time(container.get('capperiod', '01:00:00'))
    cell = _number(container.get('effectivecellsize', '7.5'), 'effectivecellsize')
    for e in container.findall('link'):
        ident = e.get('id')
        if not ident or ident in links:
            _fail(f'enlace ausente/duplicado: {ident}')
        if e.get('from') not in nodes or e.get('to') not in nodes:
            _fail(f'enlace {ident} con nodo inexistente')
        links[ident] = dict(from_node=e.get('from'), to_node=e.get('to'),
                           length=_number(e.get('length'), f'{ident}.length'),
                           lanes=_number(e.get('permlanes'), f'{ident}.permlanes'),
                           capacity=_number(e.get('capacity'), f'{ident}.capacity'),
                           freespeed=_number(e.get('freespeed'), f'{ident}.freespeed'),
                           modes=sorted(e.get('modes', 'car').split(',')))
        if 'car' in links[ident]['modes']:
            outgoing.setdefault(e.get('from'), set()).add(ident)
    if not links:
        _fail('network vacio')
    signature = _digest(dict(nodes=nodes, links=links, capacity_period=period, cell_size=cell))
    return nodes, links, outgoing, period, cell, signature


def read_lanes(path):
    assignments = {}
    for assignment in _xml(path).findall('lanesToLinkAssignment'):
        link = assignment.get('linkIdRef')
        if not link or link in assignments:
            _fail(f'asignacion ausente/duplicada: {link}')
        lanes = {}
        for e in assignment.findall('lane'):
            ident = e.get('id')
            if not ident or ident in lanes:
                _fail(f'cola ausente/duplicada en {link}: {ident}')
            def attr(tag, key):
                child = e.find(tag)
                return child.get(key) if child is not None else None
            lanes[ident] = dict(start=_number(attr('startsAt', 'meterFromLinkEnd'), f'{ident}.start'),
                               represented=_number(attr('representedLanes', 'number'), f'{ident}.represented'),
                               capacity=_number(attr('capacity', 'vehiclesPerHour'), f'{ident}.capacity'),
                               alignment=_number(e.findtext('alignment', '0'), f'{ident}.alignment', False),
                               to_lanes=_references(e.findall('leadsTo/toLane'), ident+'.toLane'),
                               to_links=_references(e.findall('leadsTo/toLink'), ident+'.toLink'))
        assignments[link] = lanes
    return assignments


def read_signals(path):
    result = {}
    for system in _xml(path).findall('signalSystem'):
        system_id = system.get('id')
        if not system_id or system_id in result:
            _fail(f'sistema de señales ausente/duplicado: {system_id}')
        signals = {}
        for signal in system.findall('signals/signal'):
            ident = signal.get('id')
            if not ident or ident in signals:
                _fail(f'señal ausente/duplicada en {system_id}: {ident}')
            signals[ident] = dict(link=signal.get('linkIdRef'),
                                 lanes=_references(signal.findall('lane'), ident+'.lane'),
                                 turning_moves=_references(signal.findall('turningMoveRestrictions/toLink'), ident+'.turningMove'))
        result[system_id] = signals
    return result


def queue_storage(length, represented, capacity_hour, speed, cell, storage_factor, flow_factor, step, dynamics):
    """QueueWithBuffer.calculateStorageCapacity, excluding its separate buffer.

    Unit-PCU ceiling is admission with usedStorage < threshold, not a claim that
    vehicles or physical spaces always have unit size. Incident-time changes and
    driver-specific velocity/flow efficiency require runtime measurements.
    """
    geometric = length*represented/cell*storage_factor
    flow_step = capacity_hour/3600*flow_factor*step
    travel_limit = length/speed*capacity_hour/3600*flow_factor
    threshold = max(geometric, flow_step, travel_limit)
    if dynamics in ('withHoles', 'kinematicWaves'):
        hole_speed = 15/3.6
        threshold = max(threshold, length*flow_step*(speed+hole_speed)/speed/hole_speed)
    return dict(geometric_pcu=geometric, threshold_pcu=threshold,
                unit_pcu_admissions=math.ceil(threshold), buffer_pcu=flow_step,
                enlarged=threshold > geometric+1e-9)


def screen_storage(links, assignments, period, cell, storage, flow, step, dynamics, stuck_time):
    """Inspect active queues, including the shared receiving part of lane links.

    A flag is a calibration candidate, not a failed network or proof of a jam.
    Nominal 1-PCU headway excludes red, priority, profiles and downstream blocking.
    """
    counts, examples = Counter(), []
    for ident, link in links.items():
        if 'car' not in link['modes']:
            continue
        lanes = assignments.get(ident)
        if lanes:
            referenced = {key for lane in lanes.values() for key in lane['to_lanes']}
            root = next(key for key in lanes if key not in referenced)
            terminal_length = next(lane['start'] for lane in lanes.values() if lane['to_links'])
            queues = [(key, 'receiving' if key == root else 'terminal',
                       link['length']-terminal_length if key == root else lane['start'],
                       lane['represented'], lane['capacity']) for key, lane in lanes.items()]
        else:
            queues = [(ident, 'undivided', link['length'], link['lanes'], link['capacity']/period*3600)]
        for lane, role, length, represented, capacity in queues:
            limits = queue_storage(length, represented, capacity, link['freespeed'], cell, storage, flow, step, dynamics)
            headway = 3600/(capacity*flow)
            flags = []
            if limits['geometric_pcu'] < 1:
                flags.append('geometric_storage_below_one_pcu')
            if limits['threshold_pcu'] < 1:
                flags.append('native_threshold_below_one_pcu')
            if length/link['freespeed'] < step:
                flags.append('free_travel_below_one_step')
            if stuck_time is not None and headway > stuck_time:
                flags.append('nominal_headway_exceeds_stuck_time')
            counts['queues_screened'] += 1
            if flags:
                counts['flagged_queues'] += 1
                counts['flagged_'+role+'_queues'] += 1
                counts.update(flags)
                examples.append(dict(link=ident, lane=lane, role=role, effective_length_m=length,
                    geometric_pcu=limits['geometric_pcu'], threshold_pcu=limits['threshold_pcu'],
                    nominal_unit_pcu_headway_seconds=headway, flags=flags))
    return dict(status='screening_not_causal_proof', stuck_time_seconds=stuck_time, counts=dict(counts),
                examples=sorted(examples, key=lambda x: (
                    x['role'] != 'receiving', x['threshold_pcu'], x['link'], x['lane']))[:20],
                scope='Active baseline queues, excluding separate buffers; no demand/capacity adequacy claim. '
                      'Short links are not automatically invalid; do not enlarge them or capacities from these flags.')


def _turn_policy(base, network_file, lane_file, osm_path, transit_enabled):
    """Resolve reviewed context, then prove legal exclusions independently of lanes.

    Historical inputs deliberately retain their original topological audit. The
    reviewed source is selected by its contract location, not by observing lane
    omissions (nor by matching its map/network bytes, shared with history).
    Derived inputs must carry their copied, fingerprinted OSM source explicitly.
    """
    from simz1_sequence_contract import ROOT, SHA256, load_contract, reviewed_source_paths
    from simz1_od_policy import validate_osm_turns
    from simz1_osm_turn_audit import source_way_id
    try:
        locations = reviewed_source_paths()
        source_path = locations['isolated_source_osm']
        configured_sources = {locations['directed_mapping'], locations['ten_preserved_lane_corrections']}
        if osm_path is None:
            if base != source_path.parent and not {network_file, lane_file} & configured_sources:
                return {}, None
            osm_path = source_path
        contract = load_contract()
        osm_path = Path(osm_path).resolve(strict=True)
        # Include origid provenance in semantic output comparisons. MATSim moves
        # this value to an <attribute>; XML bytes are not a semantic signature.
        def provenance_for(path):
            return {link.get('id'): dict(source_way=source_way_id(link),
                    from_node=link.get('from'), to_node=link.get('to'))
                    for link in _xml(path).findall('links/link')
                    if 'car' in link.get('modes', 'car').split(',')}
        provenance = provenance_for(network_file)
        source_hash = hashlib.sha256(osm_path.read_bytes()).hexdigest()
        expected_hash = next(meta['sha256'] for meta in contract['sources'].values()
                             if meta['role'] == 'isolated_source_osm')
        if source_hash == expected_hash:
            mapping_path = next(ROOT/name for name, meta in contract['sources'].items()
                                if meta['role'] == 'directed_mapping')
            if provenance != provenance_for(mapping_path):
                raise ValueError('procedencia OSM car difiere del mapeo dirigido comprobado')
        validation = validate_osm_turns(osm_path, network_file, lane_file,
                                       allow_transit_bus_exits=transit_enabled)
        pairs = validation['pair_prohibitions']
        if pairs and source_hash != expected_hash:
            raise ValueError('OSM source evidence hash mismatch: pair exclusions require the pinned source')
        forbidden = {}
        for pair in pairs:
            forbidden.setdefault(pair['from_link'], set()).add(pair['to_link'])
        report = dict(source_osm=dict(path=str(osm_path), sha256=source_hash),
                      contract_sha256=SHA256, sequence_contract_version=validation['sequence_contract_version'],
                      pair_prohibitions=pairs, provenance_signature=_digest(provenance),
                      sequence_relations=[row for row in validation['relations']
                                          if row['status'] == 'enforced_by_shared_sequence_contract'],
                      source_treatments=[row for row in validation['relations']
                                         if row['status'] == 'MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER'])
        return forbidden, report
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        _fail('politica de giros OSM: ' + str(exc))


def audit_configuration(source, *, base_dir=None, network_path=None, lanes_path=None,
                        signals_path=None, allow_signal_lane_stripping=False, osm_path=None):
    """Validate configured files; overrides are for actual MATSim output files."""
    if isinstance(source, (str, Path)):
        source = Path(source).resolve()
        root, base = _xml(source), source.parent
    else:
        root, base = source, Path(base_dir or '.').resolve()
    values = {f"{m.get('name')}.{p.get('name')}": p.get('value')
              for m in root.findall('module') for p in m.findall('param')}
    use_lanes = values.get('qsim.useLanes', 'false') == 'true'
    use_signals = values.get('signalsystems.useSignalsystems', 'false') == 'true'
    def configured(key, explicit=None, required=False):
        value = str(explicit) if explicit is not None else values.get(key)
        if value in (None, '', 'null'):
            if required:
                _fail(f'falta {key}')
            return None
        return (base/value).resolve()
    network_file = configured('network.inputNetworkFile', network_path, True)
    lane_file = configured('network.laneDefinitionsFile', lanes_path, use_lanes)
    signal_file = configured('signalsystems.signalsystems', signals_path, use_signals)
    nodes, links, outgoing, period, cell, network_signature = read_network(network_file)
    assignments = read_lanes(lane_file) if lane_file is not None else {}
    signals = read_signals(signal_file) if signal_file is not None else {}
    forbidden, turn_policy = _turn_policy(base, network_file, lane_file, osm_path,
                                          values.get('transit.useTransit') == 'true')
    flow = _number(values.get('qsim.flowCapacityFactor', '1'), 'flowCapacityFactor')
    storage = _number(values.get('qsim.storageCapacityFactor', '1'), 'storageCapacityFactor')
    step = _time(values.get('qsim.timeStepSize', '1'), 'timeStepSize')
    dynamics = values.get('qsim.trafficDynamics', 'queue')
    if dynamics not in ('queue', 'withHoles', 'kinematicWaves'):
        _fail(f'trafficDynamics no soportada en auditoria: {dynamics}')
    metrics = Counter()
    comparison = []
    bus_outgoing = {}
    if values.get('transit.useTransit') == 'true':
        for key, target in links.items():
            if 'bus' in target['modes'] and 'car' not in target['modes']:
                bus_outgoing.setdefault(target['from_node'], set()).add(key)
    for link_id, lanes in assignments.items():
        link = links.get(link_id)
        if link is None or 'car' not in link['modes']:
            _fail(f'asignacion {link_id} sin enlace car')
        if nodes[link['from_node']] == nodes[link['to_node']]:
            _fail(f'asignacion {link_id} tiene extremos geometricos coincidentes')
        expected = outgoing.get(link['to_node'], set()) - forbidden.get(link_id, set())
        # Bus-only source extensions must never remove existing car exits, add a
        # disconnected turn, or grant car access. Only a transit-enabled receiver
        # with shared bus permission may be an additional lane exit.
        bus_extras = bus_outgoing.get(link['to_node'], set()) if 'bus' in link['modes'] else set()
        permitted = expected | bus_extras
        roots = []
        referenced = set()
        for ident, lane in lanes.items():
            if lane['to_lanes'] and lane['to_links']:
                _fail(f'{ident} mezcla toLane y toLink')
            if not lane['to_lanes'] and not lane['to_links']:
                _fail(f'{ident} no tiene salida')
            for target in lane['to_lanes']:
                if target not in lanes:
                    _fail(f'{ident}: toLane colgante {target}')
                referenced.add(target)
            for target in lane['to_links']:
                if target not in permitted:
                    _fail(f'{ident}: toLink desconectado o sin car {target}')
        roots = sorted(set(lanes)-referenced)
        if len(roots) != 1:
            _fail(f'{link_id}: se requiere una cola aguas arriba; encontradas {roots}')
        upstream = lanes[roots[0]]
        terminals = {key: value for key, value in lanes.items() if value['to_links']}
        if set(upstream['to_lanes']) != set(terminals) or len(lanes) != len(terminals)+1:
            _fail(f'{link_id}: grafo fuera del modelo SimZ1 de colas terminales paralelas; cola inalcanzable/ciclo')
        length, count = link['length'], link['lanes']
        capacity = link['capacity']/period*3600
        if not _same(upstream['start'], length) or not _same(upstream['represented'], count):
            _fail(f'{link_id}: origen de cola/numero representado no conserva enlace')
        if not _same(upstream['capacity'], capacity) or not _same(sum(t['capacity'] for t in terminals.values()), capacity):
            _fail(f'{link_id}: capacidad de flujo total no conservada')
        starts = {t['start'] for t in terminals.values()}
        if len(starts) != 1 or not 0 < next(iter(starts)) < length:
            _fail(f'{link_id}: longitudes efectivas ambiguas o no positivas')
        queue_length = next(iter(starts))
        if not _same(sum(t['represented'] for t in terminals.values()), count):
            _fail(f'{link_id}: carriles representados terminales no conservados')
        weighted_length = (length-queue_length)*upstream['represented'] + sum(t['start']*t['represented'] for t in terminals.values())
        if not _same(weighted_length, length*count):
            _fail(f'{link_id}: longitud efectiva ponderada no conservada')
        for ident, terminal in terminals.items():
            if not expected <= set(terminal['to_links']) or not set(terminal['to_links']) <= permitted:
                _fail(f'{ident}: movimientos car no alcanzables; no se inventan restricciones de giro')
            metrics['terminal_queues'] += 1
            metrics['terminal_represented_lanes'] += terminal['represented']
            metrics['reachable_terminal_movements'] += len(terminal['to_links'])
            metrics['uturn_terminal_movements'] += sum(links[t]['to_node'] == link['from_node'] for t in terminal['to_links'])
        one = queue_storage(length, count, capacity, link['freespeed'], cell, storage, flow, step, dynamics)
        parts = [queue_storage(length-queue_length, count, capacity, link['freespeed'], cell, storage, flow, step, dynamics)]
        parts += [queue_storage(t['start'], t['represented'], t['capacity'], link['freespeed'], cell, storage, flow, step, dynamics) for t in terminals.values()]
        for key in ('geometric_pcu', 'threshold_pcu', 'unit_pcu_admissions', 'buffer_pcu'):
            metrics['standard_'+key] += one[key]
            metrics['detailed_'+key] += sum(p[key] for p in parts)
        metrics['standard_enlarged_queues'] += one['enlarged']
        metrics['detailed_enlarged_queues'] += sum(p['enlarged'] for p in parts)
        metrics['detailed_queues_under_cell_length'] += sum(x < cell for x in [length-queue_length]+[t['start'] for t in terminals.values()])
        metrics['standard_free_time_under_step'] += length/link['freespeed'] < step
        metrics['detailed_free_time_under_step'] += sum(x/link['freespeed'] < step for x in [length-queue_length]+[t['start'] for t in terminals.values()])
        extra = sum(p['unit_pcu_admissions'] for p in parts)-one['unit_pcu_admissions']
        if extra > 0:
            metrics['links_with_extra_unit_pcu_admissions'] += 1
        comparison.append(dict(link=link_id, length_m=length, represented_lanes=count,
                               standard_threshold_pcu=one['threshold_pcu'],
                               detailed_threshold_pcu=sum(p['threshold_pcu'] for p in parts),
                               extra_unit_pcu_admissions=extra))
    signal_lane_references = 0
    stripped_references = 0
    for system_id, system in signals.items():
        for ident, signal in system.items():
            link = links.get(signal['link'])
            if link is None or 'car' not in link['modes']:
                _fail(f'señal {system_id}/{ident} refiere enlace car ausente')
            for lane_id in signal['lanes']:
                lane = assignments.get(signal['link'], {}).get(lane_id)
                if lane is None or not lane['to_links']:
                    _fail(f'señal {system_id}/{ident} refiere cola terminal inexistente {lane_id}')
                signal_lane_references += 1
            if use_signals and not use_lanes and signal['lanes']:
                if not allow_signal_lane_stripping:
                    _fail(f'señal {system_id}/{ident} tiene referencias de carril con useLanes=false')
                stripped_references += len(signal['lanes'])
            if not set(signal['turning_moves']).issubset(outgoing.get(link['to_node'], set())):
                _fail(f'señal {system_id}/{ident} tiene movimiento desconectado')
    car_links = {key: value for key, value in links.items() if 'car' in value['modes']}
    stuck_value = values.get('qsim.stuckTime')
    stuck_time = None if stuck_value is None else _time(stuck_value, 'stuckTime', positive=False)
    if stuck_time is not None and stuck_time < 0:
        _fail('stuckTime debe ser no negativo')
    return dict(status='valid', model='SimZ1 parallel terminal queues / MATSim 15.0',
                physical_stability_proven=False, use_lanes=use_lanes, signals_enabled=use_signals,
                turn_policy=turn_policy,
                signatures=dict(network=network_signature, lanes=_digest(assignments), signals=_digest(signals),
                                **({'osm_provenance': turn_policy['provenance_signature']} if turn_policy else {})),
                counts=dict(network_links=len(links), car_links=len(car_links), assignments=len(assignments),
                            active_detailed_assignments=len(assignments) if use_lanes else 0,
                            upstream_queues=len(assignments), all_lane_definitions=sum(map(len, assignments.values())),
                            car_links_without_assignment=len(set(car_links)-set(assignments)),
                            links_shorter_than_7_5m=sum(l['length'] < 7.5 for l in links.values()),
                            signals=sum(map(len, signals.values())), signal_lane_references=signal_lane_references,
                            planned_signal_lane_reference_removals=stripped_references),
                baseline_queue_metrics=dict(metrics),
                storage_screening=screen_storage(links, assignments if use_lanes else {}, period, cell,
                    storage, flow, step, dynamics, stuck_time),
                baseline_parameters=dict(effective_cell_size_m=cell, time_step_seconds=step,
                                         storage_factor=storage, flow_factor=flow, traffic_dynamics=dynamics),
                largest_discretization_examples=sorted(comparison, key=lambda x: (-x['extra_unit_pcu_admissions'], x['link']))[:10],
                scope=['Assignments are links with a lane graph, not independent physical lanes.',
                       'Every terminal queue permits every required car exit; exclusions require verified OSM pair evidence.',
                       'History-dependent OSM sequences remain in the shared routing automaton, never global pair bans.',
                       'Weighted effective lengths and hourly flow capacities are conserved before QSim discretization.',
                       'Queue thresholds exclude separate buffers; unit-PCU admission ceilings are analytical, not measured occupancy.',
                       'Serial queues add separate time-step discretization; per-queue sub-step counts are not trip delays.',
                       'Baseline excludes incident-time changes, profile-specific speed/flow efficiency and forced moves.',
                       'QSim lanes are queues, not continuous lateral motion or car-following.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--osm', type=Path, help='Fuente OSM comprobada para archivos derivados')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit_configuration(args.config, osm_path=args.osm)
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
