"""Read-only fixed-time signal checks for through-freight movements.

Positive GREEN on each eligible native lane movement is necessary, not a guarantee of a
compound passage, receiver space, queue drainage or capacity under demand.
"""
from collections import defaultdict
import math
import xml.etree.ElementTree as ET

from simz1_lane_validation import read_lanes, read_signals
from simz1_run import parameters, sha256
from simz1_signal_coordination import AMBER_SECONDS, remaining_green


def _xml(path):
    root = ET.parse(path).getroot()
    for row in root.iter():
        row.tag = row.tag.rsplit('}', 1)[-1]
    return root


def audit(config_path, bundle):
    values = parameters(config_path)
    if values.get('signalsystems.useSignalsystems') != 'true':
        return dict(enabled=False, basis='effective_config_signals_disabled')
    paths = {key: config_path.parent / values['signalsystems.' + key]
             for key in ('signalsystems', 'signalgroups', 'signalcontrol')}
    systems = read_signals(paths['signalsystems'])
    lanes = read_lanes(config_path.parent / values['network.laneDefinitionsFile'])
    membership = {}
    for system in _xml(paths['signalgroups']).findall('signalSystem'):
        sid = system.get('refId')
        for group in system.findall('signalGroup'):
            for signal in group.findall('signal'):
                key = sid, signal.get('refId')
                if key in membership or key[1] not in systems.get(sid, {}):
                    raise ValueError('Freight duplicate or missing signal group member')
                membership[key] = group.get('id')
    plans = {}
    for system in _xml(paths['signalcontrol']).findall('signalSystem'):
        sid = system.get('refId')
        candidates = system.findall('.//signalPlan')
        if len(candidates) != 1 or system.findtext('.//controllerIdentifier') != 'Zona1FixedTime':
            raise ValueError('Freight requires one all-day Zona1FixedTime signal plan: '+str(sid))
        plan = candidates[0]
        if any(plan.find(tag) is None or plan.find(tag).get('daytime') != '00:00:00' for tag in ('start', 'stop')):
            raise ValueError('Freight requires an all-day signal plan: '+sid)
        cycle, offset = int(plan.find('cycleTime').get('sec')), int(plan.find('offset').get('sec'))
        groups = {g.get('refId'): (int(g.find('onset').get('sec')), int(g.find('dropping').get('sec')))
                  for g in plan.findall('signalGroupSettings')}
        if cycle <= 0 or not 0 <= offset < cycle or any(
                not (0 <= a < cycle and 0 <= b < cycle and (b-a) % cycle > AMBER_SECONDS)
                for a, b in groups.values()):
            raise ValueError('Freight signal has no positive GREEN interval: '+sid)
        plans[sid] = dict(cycle=cycle, offset=offset, groups=groups)
    by_link = defaultdict(list)
    for sid, signals in systems.items():
        for ident, signal in signals.items():
            group = membership.get((sid, ident))
            if sid not in plans or group not in plans[sid]['groups']:
                raise ValueError('Freight signal missing group/phase: '+sid+'/'+ident)
            if not set(signal['lanes']) <= lanes.get(signal['link'], {}).keys():
                raise ValueError('Freight signal references missing native lane: '+ident)
            by_link[signal['link']].append(dict(signal, system=sid, group=group, id=ident))
    step = float(values.get('qsim.timeStepSize', '1'))
    if not math.isfinite(step) or step <= 0:
        raise ValueError('Freight invalid signal time step')
    routes = []
    for route in bundle['routes']:
        rows = []
        for source, target in zip(route['link_ids'], route['link_ids'][1:]):
            terminals = sorted(name for name, lane in lanes.get(source, {}).items() if target in lane['to_links'])
            # The occupancy ledger may retain an existing model slot or select
            # by available space. Validate every entry-reachable terminal, not
            # just the first lane. The route validator establishes reachability.
            for native_lane in terminals or [None]:
                applicable = [s for s in by_link[source] if (not s['lanes'] or native_lane in s['lanes']) and
                              (not s['turning_moves'] or target in s['turning_moves'])]
                if not applicable:
                    continue
                cycle = math.lcm(*(plans[s['system']]['cycle'] for s in applicable))
                if cycle/step > 100000 or abs(cycle/step-round(cycle/step)) > 1e-8:
                    raise ValueError('Freight unsupported signal cycle/time-step combination')
                greens = [tick*step for tick in range(round(cycle/step)) if all(
                    remaining_green(plans[s['system']], s['group'], tick*step,
                                    plans[s['system']]['offset']) > 0 for s in applicable)]
                if not greens:
                    raise ValueError('Freight native lane movement never has GREEN: '+source+' -> '+target+' / '+str(native_lane))
                rows.append(dict(from_link=source, to_link=target, native_lane=native_lane,
                                 signals=[s['system']+'/'+s['id'] for s in applicable],
                                 green_ticks_per_common_cycle=len(greens), common_cycle_seconds=cycle))
        routes.append(dict(route_id=route['route_id'],
                           controlled_movements=len({(r['from_link'], r['to_link']) for r in rows}),
                           controlled_lane_movements=len(rows), movements=rows))
    return dict(enabled=True, basis='effective_fixed_time_all_reachable_lane_movements_positive_green',
                signal_file_sha256={key: sha256(path) for key, path in paths.items()},
                routes=routes, compound_passage_feasibility_proven=False, queue_drainage_proven=False)
