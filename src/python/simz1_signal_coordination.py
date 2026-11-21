"""Derive auditable offsets for short, body-blocking signal passages.

This is a static, empty-queue feasibility check, not a green-wave or throughput
guarantee. Native admission still checks actual signals, flow debt, receivers
and conflicts. Only the isolated run's signal-control file may be written.
"""
from collections import defaultdict
from copy import deepcopy
import gzip
import hashlib
import itertools
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_lane_validation import read_lanes
from simz1_stop_proxy import StopGeometry

POLICY = 'short_body_passage_offsets_v1'
ACTIVITY_POLICY = 'short_body_passage_activity_offsets_v2'
AMBER_SECONDS = 4
MINIMUM_GAP_M = .10


def _require(condition, message):
    if not condition:
        raise ValueError('SIGNAL_COORDINATION: '+message)


def _xml(path):
    with (gzip.open if str(path).endswith('.gz') else open)(path, 'rb') as stream:
        tree = ET.parse(stream)
    for element in tree.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    return tree


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remaining_green(plan, group, time, offset):
    onset, dropping = plan['groups'][group]
    cycle = plan['cycle']; amber = (dropping-AMBER_SECONDS) % cycle
    phase = (time-offset) % cycle
    opened = onset <= phase < amber if onset < amber else phase >= onset or phase < amber
    return (amber-phase) % cycle if opened else 0


def feasible_starts(constraint, plans, offsets):
    """Integer native QSim ticks satisfying every deadline of this passage."""
    step = constraint['step_seconds']
    cycle = plans[constraint['signals'][0]['system']]['cycle']
    return [tick*step for tick in range(round(cycle/step))
            if all(remaining_green(plans[row['system']], row['group'], tick*step,
                                   offsets[row['system']]) > row['traversal_seconds']
                   for row in constraint['signals'])]


def solve_offsets(plans, constraints, *, maximum_assignments=1_000_000):
    """Exact finite search per connected component; preserve one original clock.

    The objective maximizes the smallest number of usable native entry ticks,
    then total ticks, then minimizes changed systems and circular offset change.
    Search exhaustion is explicit and never mislabeled as mathematical failure.
    """
    offsets = {sid: plan['offset'] for sid, plan in plans.items()}
    neighbours = defaultdict(set)
    for constraint in constraints:
        ids = {row['system'] for row in constraint['signals']}
        for sid in ids:
            neighbours[sid].update(ids-{sid})
    unseen = set(neighbours); components = []
    while unseen:
        pending = [min(unseen)]; component = set()
        while pending:
            sid = pending.pop()
            if sid in component: continue
            component.add(sid); pending.extend(neighbours[sid]-component)
        unseen -= component
        ids = sorted(component)
        relevant = [c for c in constraints if c['signals'][0]['system'] in component]
        cycles = {plans[sid]['cycle'] for sid in ids}
        _require(len(cycles) == 1, 'short passage has different signal cycles: '+','.join(ids))
        cycle = cycles.pop(); anchor = ids[0]; variable = ids[1:]
        _require(cycle**len(variable) <= maximum_assignments,
                 'exact offset search exceeds declared assignment limit: '+','.join(ids))
        best = None; best_offsets = None; examined = 0
        # Relative offsets make this cache independent of the anchored clock.
        cache = {}
        for values in itertools.product(range(cycle), repeat=len(variable)):
            candidate = dict(offsets); candidate.update(zip(variable, values)); examined += 1
            counts = []
            for index, constraint in enumerate(relevant):
                members = sorted({row['system'] for row in constraint['signals']})
                base = candidate[members[0]]
                key = index, tuple((candidate[s]-base) % cycle for s in members), base % constraint['step_seconds']
                if key not in cache:
                    cache[key] = len(feasible_starts(constraint, plans, candidate))
                counts.append(cache[key])
            changes = sum(candidate[sid] != plans[sid]['offset'] for sid in ids)
            distance = sum(min((candidate[sid]-plans[sid]['offset']) % cycle,
                               (plans[sid]['offset']-candidate[sid]) % cycle) for sid in ids)
            score = min(counts), sum(counts), -changes, -distance
            if best is None or score > best:
                best = score; best_offsets = candidate
        _require(best is not None and best[0] > 0,
                 'no feasible simultaneous green passage under any offsets: '+','.join(ids))
        offsets.update({sid: best_offsets[sid] for sid in ids})
        components.append(dict(systems=ids, anchor_system=anchor,
                               assignments_examined=examined, minimum_entry_ticks=best[0]))
    return offsets, components


def coordinate(config_root, base_dir, *, write=False, activity_origins=False):
    """Return proposal/evidence; write=True updates only referenced signalcontrol.

    Caller owns policy selection and must call on a newly isolated run after
    attaching all services, before publishing the input hashes and manifest.
    """
    base_dir = Path(base_dir).resolve()
    policy = ACTIVITY_POLICY if activity_origins else POLICY
    if isinstance(config_root, (str, Path)):
        config_root = _xml(config_root).getroot()
    elif isinstance(config_root, ET.ElementTree):
        config_root = config_root.getroot()
    def param(module, name, default=None):
        element = config_root.find(f"module[@name='{module}']/param[@name='{name}']")
        return element.get('value') if element is not None else default
    def file(module, name):
        value = param(module, name)
        _require(value not in (None, '', 'null'), 'missing '+module+'.'+name)
        return (base_dir/value).resolve()
    if param('signalsystems', 'useSignalsystems', 'false').lower() != 'true':
        return dict(policy=policy, enabled=False, reason='signals_disabled')
    paths = {key: file(module, name) for key, module, name in (
        ('network', 'network', 'inputNetworkFile'), ('lanes', 'network', 'laneDefinitionsFile'),
        ('systems', 'signalsystems', 'signalsystems'), ('groups', 'signalsystems', 'signalgroups'),
        ('control', 'signalsystems', 'signalcontrol'), ('vehicles', 'vehicles', 'vehiclesFile'))}
    if param('transit', 'useTransit', 'false').lower() == 'true':
        paths['transit_vehicles'] = file('transit', 'vehiclesFile')
    hashes = {key: dict(path=str(path), sha256=_sha(path)) for key, path in paths.items()}
    _require(not write or paths['control'].is_relative_to(base_dir),
             'refusing to modify signalcontrol outside isolated run directory')
    step = float(param('qsim', 'timeStepSize', '1'))
    _require(math.isfinite(step) and step > 0, 'invalid native time step')
    network = _xml(paths['network']); nodes = {e.get('id'): e for e in network.findall('nodes/node')}
    links = {e.get('id'): e for e in network.findall('links/link')
             if set(e.get('modes', 'car').split(',')) & {'car', 'bus'}}
    lanes = read_lanes(paths['lanes']); geometry = StopGeometry(links, nodes, lanes)
    outgoing = defaultdict(list); incoming = defaultdict(list)
    for ident, link in links.items():
        outgoing[link.get('from')].append(ident); incoming[link.get('to')].append(ident)
    def attributes(element):
        return {a.get('name'): a.text for a in element.findall('attributes/attribute')}
    def turns(ident, mode):
        allowed = {target for lane in lanes.get(ident, {}).values() for target in lane['to_links']}
        choices = allowed if allowed else outgoing[links[ident].get('to')]
        return sorted(target for target in choices if target in links and mode in links[target].get('modes', 'car').split(','))
    control = _xml(paths['control']); plans = {}; plan_elements = {}
    for system in control.getroot().findall('signalSystem'):
        sid = system.get('refId'); candidates = system.findall('.//signalPlan')
        _require(len(candidates) == 1 and system.findtext('.//controllerIdentifier') == 'Zona1FixedTime',
                 'requires one Zona1FixedTime plan: '+str(sid))
        element = candidates[0]; cycle = int(element.find('cycleTime').get('sec'))
        offset = int(element.find('offset').get('sec'))
        _require(all(element.find(tag) is not None and element.find(tag).get('daytime') == '00:00:00'
                     for tag in ('start', 'stop')), 'requires an all-day fixed plan: '+sid)
        _require(cycle > 0 and 0 <= offset < cycle and abs(cycle/step-round(cycle/step)) < 1e-8,
                 'invalid cycle, offset or cycle/time-step ratio: '+sid)
        groups = {g.get('refId'): (int(g.find('onset').get('sec')), int(g.find('dropping').get('sec')))
                  for g in element.findall('signalGroupSettings')}
        _require(all(0 <= a < cycle and 0 <= b < cycle and (b-a) % cycle > AMBER_SECONDS
                     for a, b in groups.values()), 'invalid phase duration: '+sid)
        plans[sid] = dict(cycle=cycle, offset=offset, groups=groups); plan_elements[sid] = element
    membership = {}
    for system in _xml(paths['groups']).getroot().findall('signalSystem'):
        for group in system.findall('signalGroup'):
            for signal in group.findall('signal'):
                key = system.get('refId'), signal.get('refId')
                _require(key not in membership, 'duplicate signal group membership')
                membership[key] = group.get('id')
    signals = defaultdict(list)
    for system in _xml(paths['systems']).getroot().findall('signalSystem'):
        sid = system.get('id')
        for signal in system.findall('signals/signal'):
            group = membership.get((sid, signal.get('id')))
            _require(sid in plans and group in plans[sid]['groups'], 'signal missing plan/group')
            signals[signal.get('linkIdRef')].append(dict(system=sid, group=group,
                lanes={e.get('refId') for e in signal.findall('lane')},
                turns={e.get('refId') for e in signal.findall('turningMoveRestrictions/toLink')}))
    controlled = {links[ident].get('to') for ident in signals if ident in links}
    # Same safe straight continuation criterion as native corridor grouping.
    continuation = {}
    for ident, link in links.items():
        node = link.get('to'); attrs = attributes(nodes[node]); own = attributes(link)
        if node in controlled or any(attrs.get(k) in ('traffic_signals', 'stop', 'give_way') for k in ('osm:highway', 'highway')) or own.get('simz1:priorityControl') in ('stop', 'yield'):
            continue
        neighbours = {links[x].get('from') for x in incoming[node]} | {links[x].get('to') for x in outgoing[node]}
        successors = [x for x in outgoing[node] if links[x].get('to') != link.get('from')]
        if len(neighbours) != 2 or len(successors) != 1: continue
        following = links[successors[0]]; other = attributes(following)
        if float(link.get('permlanes')) != float(following.get('permlanes')) or set(link.get('modes', 'car').split(',')) != set(following.get('modes', 'car').split(',')):
            continue
        if any(own.get(k) != other.get(k) for k in ('osm:layer', 'osm:bridge', 'osm:tunnel')): continue
        u, v = geometry.direction(link), geometry.direction(following)
        if sum(a*b for a, b in zip(u, v)) >= .95: continuation[ident] = successors[0]
    profiles = {}
    for key in ('vehicles', 'transit_vehicles'):
        if key not in paths: continue
        definitions = _xml(paths[key]); used = {v.get('type') for v in definitions.findall('vehicle')}
        for element in definitions.findall('vehicleType'):
            if element.get('id') not in used: continue
            mode = element.find('networkMode'); mode = mode.get('networkMode') if mode is not None else 'car'
            if mode not in ('car', 'bus'): continue
            length = element.find('length'); speed = element.find('maximumVelocity')
            _require(length is not None and speed is not None, 'active type lacks length/speed')
            length, speed = float(length.get('meter')), float(speed.get('meterPerSecond'))
            _require(all(math.isfinite(x) and x > 0 for x in (length, speed)), 'invalid active body profile')
            profiles[(mode, length, speed)] = element.get('id')
    _require(profiles, 'no active road vehicle profiles')
    def lane_order(name):
        suffix = name.rsplit('.lane.', 1)
        _require(len(suffix) == 2 and suffix[1].isdigit(), 'unsupported terminal model-slot name: '+name)
        return int(suffix[1]), name
    def selected_lane(ident, target):
        eligible = sorted((name for name, lane in lanes.get(ident, {}).items() if target in lane['to_links']), key=lane_order)
        return eligible[0] if eligible else None
    def phase_rows(ident, target, budget):
        selected = selected_lane(ident, target)
        return [dict(system=s['system'], group=s['group'], link=ident, traversal_seconds=budget)
                for s in signals.get(ident, ()) if (not s['lanes'] or selected in s['lanes']) and
                (not s['turns'] or target in s['turns'])]
    def traversal(ident, target, speed, activity_buffer=False):
        speed = min(speed, float(links[ident].get('freespeed'))); assignment = lanes.get(ident, {})
        if not assignment: lengths = [float(links[ident].get('length'))]
        else:
            terminal = selected_lane(ident, target)
            _require(terminal is not None, 'no terminal lane for permitted movement')
            children = {child for row in assignment.values() for child in row['to_lanes']}
            roots = [name for name in assignment if name not in children]
            _require(len(roots) == 1 and terminal in assignment[roots[0]]['to_lanes'],
                     'unsupported native queue chain on '+ident)
            lengths = [float(links[ident].get('length'))-assignment[terminal]['start'], assignment[terminal]['start']]
        # This is the empty/debt-free component of QueueWithBuffer's bound.
        # Activity starts enter the first queue's buffer, but still traverse
        # the selected terminal queue. Match the native bound, including its
        # two processing steps per queue; never waive a signal clearance.
        return sum(step*((0 if activity_buffer and index == 0 else
                          math.ceil(max(0, length)/speed/step))+2)
                   for index, length in enumerate(lengths))
    constraints = {}; explored = 0; excluded_cycles = set()
    for (mode, body, speed), profile in sorted(profiles.items()):
        for source in sorted(signals):
            if source not in links or mode not in links[source].get('modes', 'car').split(','): continue
            for first in turns(source, mode):
                # A source already owns its native slot. Unlike a connector's
                # minimum compatible slot, that source choice is not known here.
                # Refuse unsupported lane-dependent phases instead of claiming
                # feasibility for only the first of several real source slots.
                source_slots = [name for name, lane in lanes.get(source, {}).items() if first in lane['to_links']]
                signatures = {tuple(sorted((s['system'], s['group']) for s in signals[source]
                                           if (not s['lanes'] or name in s['lanes']) and
                                           (not s['turns'] or first in s['turns']))) for name in source_slots}
                _require(len(signatures) <= 1, 'unsupported lane-dependent source phases: '+source+' -> '+first)
                entry_budget = 0.
                need = body+MINIMUM_GAP_M+geometry.setback(source, entry=True)-2
                if activity_origins and float(links[source].get('length'))-geometry.setback(source) < need-1e-9:
                    # A short activity origin requires a passage before it can
                    # enter traffic. Unlike a vehicle already at the stop line,
                    # it has not traversed the source queues. This stronger
                    # constraint also covers the ordinary stop-line entry.
                    entry_budget = traversal(source, first, speed, activity_buffer=True)
                origin = phase_rows(source, first, entry_budget)
                if not origin: continue
                pending = [(first, [], origin, entry_budget, set())]
                while pending:
                    target, connectors, phases, budget, visited = pending.pop(); explored += 1
                    _require(explored <= 250_000, 'static passage expansion exceeded declared limit')
                    if target in visited: continue  # a repeated link cannot be a native passage receipt
                    chain = []; current = target; distance = 0.
                    need = body+MINIMUM_GAP_M+geometry.setback(target, entry=True)-2
                    while current not in visited and current not in chain:
                        chain.append(current); distance += float(links[current].get('length'))
                        # Interior route exits remain distinct paths even inside a straight domain.
                        branches = turns(current, mode)
                        following = continuation.get(current)
                        end_front = distance-geometry.setback(current)
                        if end_front >= need-1e-9:
                            if len({(p['system'], p['group']) for p in phases}) > 1:
                                row = dict(source_link=source, connector_links=connectors,
                                           receipt_link=target, vehicle_profile=profile, body_length_m=body,
                                           maximum_velocity_mps=speed, step_seconds=step, signals=phases)
                                key = tuple((p['system'], p['group'], p['traversal_seconds']) for p in phases)
                                constraints.setdefault(key, row)
                            break
                        prior_nodes = {links[source].get('to')} | {links[x].get('to') for x in visited} | {links[x].get('from') for x in chain}
                        if links[current].get('to') in prior_nodes:
                            # An offset cannot coordinate incompatible phases of
                            # one intersection visited twice without stopping.
                            # Do not reject a run for an unplanned graph cycle.
                            excluded_cycles.add(tuple([source]+connectors+chain))
                            break
                        for destination in branches:
                            if destination == following: continue
                            updated = budget; updated_phases = list(phases)
                            for index, link_id in enumerate(chain):
                                to = chain[index+1] if index+1 < len(chain) else destination
                                updated += traversal(link_id, to, speed)
                                updated_phases += phase_rows(link_id, to, updated)
                            pending.append((destination, connectors+chain, updated_phases, updated, visited|set(chain)))
                        if following is None or following not in branches: break
                        current = following
                    _require(len(connectors)+len(chain) <= 64, 'short passage exceeded declared link limit')
    constraints = list(constraints.values()); before = {sid: p['offset'] for sid, p in plans.items()}
    after, components = solve_offsets(plans, constraints)
    for constraint in constraints:
        constraint['entry_ticks_before'] = len(feasible_starts(constraint, plans, before))
        constraint['entry_ticks_after'] = len(feasible_starts(constraint, plans, after))
    changes = [dict(system_id=sid, before=before[sid], after=after[sid]) for sid in sorted(plans) if before[sid] != after[sid]]
    if write and changes:
        # Preserve original namespace and all non-offset XML data.
        original = ET.parse(paths['control']); ns = original.getroot().tag.split('}')[0]+'}' if '}' in original.getroot().tag else ''
        for system in original.getroot().findall(ns+'signalSystem'):
            system.find('.//'+ns+'offset').set('sec', str(after[system.get('refId')]))
        if ns: ET.register_namespace('', ns[1:-1])
        original.write(paths['control'], encoding='utf-8', xml_declaration=True)
    return dict(policy=policy, enabled=True, status='static_empty_queue_feasible',
                empirical_calibration=False, physics_changed=bool(changes and write),
                assumption='Synthetic offset coordination; unchanged groups, phase durations and amber clearance',
                scope='Simple lane-permitted short-body paths from controlled source links for active vehicle types; no repeated conflict node'+
                      ('; includes activity-buffer starts in sources too short to store the body' if activity_origins else ''),
                limitation='Empty queues and zero flow debt only; native admission rechecks actual green, debt, storage and conflicts. Does not guarantee completion.',
                budget_basis='Sum over original and selected terminal queues of step*(ceil(length/min(vehicle_maximum,link_freespeed)/step)+2); no empirical timing'+
                             ('; activity entry omits only original-queue travel, retaining processing and terminal traversal' if activity_origins else ''),
                input_hashes=hashes, control_sha256_after=_sha(paths['control']), written=bool(write),
                profiles=[dict(mode=m, length_m=l, maximum_velocity_mps=s, type=p) for (m,l,s),p in sorted(profiles.items())],
                constraints=constraints, impossible_before=sum(c['entry_ticks_before'] == 0 for c in constraints),
                components=components, changes=changes, explored_paths=explored,
                excluded_repeated_node_paths=[list(path) for path in sorted(excluded_cycles)])


def validate_report(config_root, base_dir, report, *, control_before_path=None):
    """Recompute the static contract against the effective isolated inputs.

    A preserved pre-coordination control file additionally proves the reported
    before state and the deterministic offset choice. No input is changed.
    """
    _require(isinstance(report, dict) and report.get('policy') in (POLICY, ACTIVITY_POLICY) and
             report.get('enabled') is True and report.get('written') is True and
             report.get('status') == 'static_empty_queue_feasible', 'invalid persisted coordination report')
    activity_origins = report['policy'] == ACTIVITY_POLICY
    current = coordinate(config_root, base_dir, write=False, activity_origins=activity_origins)
    _require(current.get('enabled') is True, 'persisted coordination requires effective signals')
    _require(report.get('control_sha256_after') == current['input_hashes']['control']['sha256'],
             'effective signalcontrol differs from coordinated artifact')
    _require(set(report.get('input_hashes', {})) == set(current['input_hashes']), 'coordination input set changed')
    for key, artifact in current['input_hashes'].items():
        if key != 'control':
            _require(report['input_hashes'][key].get('sha256') == artifact['sha256'],
                     'coordination input changed: '+key)
    _require(report.get('profiles') == current['profiles'] and
             report.get('excluded_repeated_node_paths') == current['excluded_repeated_node_paths'],
             'coordination geometry/profile scope changed')
    def after_rows(rows):
        return [{key:value for key,value in row.items() if key != 'entry_ticks_before'} for row in rows]
    _require(after_rows(report.get('constraints', [])) == after_rows(current['constraints']),
             'coordination passage constraints or resulting windows changed')
    _require(current['impossible_before'] == 0 and not current['changes'],
             'effective offsets are not the persisted feasible optimum')
    _require(report.get('physics_changed') == bool(report.get('changes')),
             'coordination physical-change declaration disagrees with offsets')
    checks = ['effective_input_hashes', 'effective_control_hash', 'active_profiles',
              'static_passage_constraints', 'resulting_green_windows', 'offset_idempotence']
    if control_before_path is not None:
        original_path = Path(control_before_path).resolve()
        _require(_sha(original_path) == report['input_hashes']['control']['sha256'],
                 'preserved original control differs from before hash')
        if isinstance(config_root, (str, Path)):
            original_config = _xml(config_root).getroot()
        elif isinstance(config_root, ET.ElementTree):
            original_config = deepcopy(config_root.getroot())
        else:
            original_config = deepcopy(config_root)
        original_config.find("module[@name='signalsystems']/param[@name='signalcontrol']").set('value', str(original_path))
        original = coordinate(original_config, base_dir, write=False, activity_origins=activity_origins)
        for key in ('constraints', 'components', 'changes', 'impossible_before', 'profiles',
                    'explored_paths', 'excluded_repeated_node_paths'):
            _require(report.get(key) == original[key], 'reported before-state/derivation differs: '+key)
        checks.append('preserved_before_control_and_deterministic_derivation')
    return dict(policy=report['policy'], status='valid', checks=checks,
                constraints=len(current['constraints']), empirical_calibration=False,
                limitation=current['limitation'])
