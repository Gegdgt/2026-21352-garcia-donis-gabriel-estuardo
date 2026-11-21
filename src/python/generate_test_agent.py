"""Un auditor, 40 viajes largos y paradas de 5 minutos; horizonte 00:00..24:00."""
import argparse
import heapq
import json
from pathlib import Path
import random
import xml.etree.ElementTree as ET

from generate_demand_z1 import principal_links
from prepare_simz1 import SCENARIO, write_xml


def generate(config_path=SCENARIO/'config-simz1.xml', run_dir=SCENARIO/'audit-24h', seed=20261006):
    config_path, run_dir = Path(config_path).resolve(), Path(run_dir).resolve()
    if run_dir.exists():
        raise ValueError(f'Usar una carpeta nueva para preservar corridas: {run_dir}')
    config = ET.parse(config_path).getroot()

    def param(module, name, value=None):
        mod = config.find(f"module[@name='{module}']")
        if mod is None:
            mod = ET.SubElement(config, 'module', name=module)
        item = mod.find(f"param[@name='{name}']")
        if item is None:
            item = ET.SubElement(mod, 'param', name=name)
        if value is not None:
            item.set('value', str(value))
        return item.get('value')

    # Preserve all input references when relocating the configuration.
    inputs = [('network','inputNetworkFile'), ('network','laneDefinitionsFile'),
              ('facilities','inputFacilitiesFile'), ('vehicles','vehiclesFile')]
    inputs += [('signalsystems', n) for n in ('signalsystems','signalgroups','signalcontrol',
               'ambertimes','intergreentimes','conflictingDirections')]
    for module, name in inputs:
        item = config.find(f"module[@name='{module}']/param[@name='{name}']")
        if item is not None and item.get('value') not in (None, '', 'null'):
            path = (config_path.parent/item.get('value')).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            item.set('value', str(path))
    network_path = Path(param('network','inputNetworkFile'))
    _, eligible, _, _ = principal_links(network_path)
    network = ET.parse(network_path)
    eligible = set(eligible)
    links = {l.get('id'): l.attrib for l in network.findall('links/link') if l.get('id') in eligible}
    nodes = {n.get('id'): (float(n.get('x')),float(n.get('y'))) for n in network.findall('nodes/node')}
    outgoing = {}
    for ident, link in links.items():
        outgoing.setdefault(link['from'], []).append(ident)
    for ids in outgoing.values():
        ids.sort()
    controlled = sorted({s.get('linkIdRef') for s in ET.parse(param('signalsystems','signalsystems')).findall('.//{*}signal')} & eligible)
    if len(controlled) < 2:
        raise ValueError('Se necesitan enlaces semaforizados conectados')

    def travel_time(ident):
        link = links[ident]
        return float(link['length'])/float(link['freespeed'])

    def connect(source_link, target_link):
        start, end = links[source_link]['to'], links[target_link]['from']
        queue, costs, previous = [(0, start)], {start:0}, {}
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != costs[node]:
                continue
            if node == end:
                break
            for ident in outgoing.get(node, []):
                dest = links[ident]['to']
                candidate = cost + travel_time(ident)
                if candidate < costs.get(dest, float('inf')):
                    costs[dest] = candidate
                    previous[dest] = (node, ident)
                    heapq.heappush(queue, (candidate, dest))
        if end not in costs:
            raise ValueError('Destino no alcanzable')
        path, node = [], end
        while node != start:
            node, ident = previous[node]
            path.append(ident)
        return list(reversed(path)) + [target_link]

    rng = random.Random(seed)
    root = ET.Element('population', desc='Single 24-hour signal auditor; synthetic explicit routes')
    person = ET.SubElement(root, 'person', id='agente_auditor')
    plan = ET.SubElement(person, 'plan', selected='yes')
    current = rng.choice(controlled)
    ET.SubElement(plan, 'activity', type='audit_stop', link=current, end_time='00:00:00')
    reports = []
    # 40 short OD trips would finish early; extend each route via random crossings.
    minimum_motion = (86400 - 39*300)/40 + 30
    for index in range(40):
        route = [current]
        moving = 0
        while moving < minimum_motion:
            x,y = nodes[links[current]['to']]
            distant = [ident for ident in controlled if ident != current and
                       sum((a-b)**2 for a,b in zip(nodes[links[ident]['from']], (x,y))) >= 800**2]
            target = rng.choice(distant or [ident for ident in controlled if ident != current])
            route.extend(connect(current, target))
            current = target
            # Only internal links count toward the conservative driving-time budget.
            moving = sum(travel_time(ident) for ident in route[1:-1])
        leg = ET.SubElement(plan, 'leg', mode='car')
        element = ET.SubElement(leg, 'route', type='links', start_link=route[0], end_link=route[-1],
                                distance=str(sum(float(links[i]['length']) for i in route)))
        # MATSim's route description includes both endpoints, even with attributes.
        element.text = ' '.join(route)
        activity = ET.SubElement(plan, 'activity', type='audit_stop', link=current)
        if index < 39:
            activity.set('max_dur', '00:05:00')
        reports.append({'trip':index+1, 'origin':route[0], 'destination':route[-1],
                        'minimum_driving_seconds':moving, 'links':len(route)})
    for module, name, value in [
        ('plans','inputPlansFile','plans.xml'), ('qsim','startTime','00:00:00'),
        ('qsim','endTime','24:00:00'), ('qsim','useLanes','true'),
        ('qsim','usingFastCapacityUpdate','false'), ('qsim','numberOfThreads','1'),
        ('qsim','simStarttimeInterpretation','onlyUseStarttime'),
        ('qsim','simEndtimeInterpretation','onlyUseEndtime'),
        ('controler','enableLinkToLinkRouting','true'), ('controler','firstIteration','0'),
        ('controler','lastIteration','0'), ('controler','writeEventsInterval','1'),
        ('controler','outputDirectory',run_dir/'output'),
        ('controler','overwriteFiles','failIfDirectoryExists'),
        ('travelTimeCalculator','maxTime','86400'),
        ('travelTimeCalculator','calculateLinkToLinkTravelTimes','true'),
        ('signalsystems','useSignalsystems','true'), ('signalsystems','useAmbertimes','true'),
        ('zona1WithinDayRouting','enabled','false'), ('global','randomSeed',seed)]:
        param(module, name, value)
    if config.find("module[@name='simz1Admission']/param[@name='storagePolicy']") is None:
        param('simz1Admission', 'storagePolicy', 'strict-receiver-v1')
    param('plans','activityDurationInterpretation','tryEndTimeThenDuration')
    score = config.find("module[@name='planCalcScore']")
    activity_params = ET.SubElement(score, 'parameterset', type='activityParams')
    for name,value in [('activityType','audit_stop'),('typicalDuration','00:05:00'),('scoringThisActivityAtAll','false')]:
        ET.SubElement(activity_params,'param',name=name,value=value)
    strategy = config.find("module[@name='strategy']")
    if strategy is not None:
        config.remove(strategy)
    strategy = ET.SubElement(config,'module',name='strategy')
    setting = ET.SubElement(strategy,'parameterset',type='strategysettings')
    ET.SubElement(setting,'param',name='strategyName',value='KeepLastSelected')
    ET.SubElement(setting,'param',name='weight',value='1.0')
    report = {'agents':1, 'person':'agente_auditor', 'trips':40, 'seed':seed,
              'activity_duration_seconds':300, 'horizon_seconds':[0,86400],
              'minimum_planned_seconds':sum(r['minimum_driving_seconds'] for r in reports)+39*300,
              'routes':reports,
              'note':'Long explicit routes retain random signal waypoints. QSim stops at 24:00; remaining trips may be unfinished.'}
    run_dir.mkdir(parents=True)
    write_xml(run_dir/'plans.xml',root,'population_v6.dtd')
    write_xml(run_dir/'config-simz1.xml',config,'config_v2.dtd')
    (run_dir/'audit-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=SCENARIO/'config-simz1.xml')
    parser.add_argument('--run-dir',type=Path,default=SCENARIO/'audit-24h')
    parser.add_argument('--seed',type=int,default=20261006)
    args = parser.parse_args()
    report = generate(args.config,args.run_dir,args.seed)
    print(f"Generado: {args.run_dir}; {report['agents']} agente, {report['trips']} viajes")
