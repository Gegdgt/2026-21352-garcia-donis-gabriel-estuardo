"""Deterministic OSM -> MATSim SimZ1. No map downloads or edits to the input.

Road defaults and the one-person smoke demand are modeling assumptions, not counts.
Run: python python/prepare_simz1.py
"""
import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from pyproj import Transformer
from simz1_road_parameters import road_parameters, IDEAL_CAPACITY
from simz1_priority_classification import apply_overrides as apply_priority_overrides

SCENARIO = Path(__file__).resolve().parents[1] / 'scenarios' / 'zona1'
ROAD_SPEED = dict(motorway=80, motorway_link=40, trunk=60, trunk_link=40,
                  primary=40, primary_link=30, secondary=40, secondary_link=30,
                  tertiary=30, tertiary_link=30, residential=30, unclassified=30,
                  living_street=15, service=15)
ACCESS_KEYS = ('motorcar', 'motor_vehicle', 'vehicle', 'access')
CRITICAL = ('333831813', '333831774', '333831722')  # south -> north


def tags(element):
    return {t.get('k'): t.get('v') for t in element.findall('tag')}


def validate_turn_restrictions(root):
    """Future imports must not silently discard unsupported OSM movements.

    No link-level substitute is safe for via-way, conditional or incomplete
    relations. Even simple via-node restrictions need the lane/routing importer,
    which this converter does not implement. Reject before writing any output.
    """
    restrictions = [r.get('id', '<missing>') for r in root.findall('relation')
                    if r.get('action') != 'delete' and tags(r).get('type') == 'restriction']
    if restrictions:
        raise ValueError('OSM turn restrictions are not imported; generation stopped before writes. '
                         'Review/import native lane and routing restrictions first. Relations: '
                         + ', '.join(restrictions))


def access_reason(t):
    # Restrictive conditional rules are not silently ignored in a time-limited scenario.
    if any(k + ':conditional' in t for k in ACCESS_KEYS):
        return 'conditional_access_review'
    for key in ACCESS_KEYS:
        if key in t:
            return 'restricted_access' if t[key] not in ('yes', 'permissive', 'designated') else None
    return None


def road_reason(t):
    if t.get('highway') not in ROAD_SPEED or t.get('area') == 'yes':
        return 'non_car_highway_or_area'
    if any(k in t for k in ('construction', 'proposed', 'oneway:conditional')):
        return 'construction_or_conditional_direction'
    if t.get('oneway', '').lower() not in ('', 'yes', 'true', '1', '-1', 'no', 'false', '0'):
        return 'unsupported_direction'
    return access_reason(t)


def driving_directions(t):
    """Directions relative to OSM node order, after road_reason validation."""
    oneway = t.get('oneway', 'yes' if t.get('junction') == 'roundabout' else 'no').lower()
    return [-1] if oneway == '-1' else [1] if oneway in ('yes', '1', 'true') else [1, -1]


def components(links):
    adj, rev = defaultdict(list), defaultdict(list)
    for l in links:
        adj[l['from']].append(l['to']); rev[l['to']].append(l['from'])
    vertices = set(adj) | set(rev)
    visited, order = set(), []
    for n in sorted(vertices):
        if n in visited: continue
        stack = [(n, False)]
        while stack:
            v, done = stack.pop()
            if done: order.append(v); continue
            if v in visited: continue
            visited.add(v); stack.append((v, True))
            stack.extend((w, False) for w in adj[v] if w not in visited)
    visited, groups = set(), []
    for n in reversed(order):
        if n in visited: continue
        group, stack = set(), [n]
        while stack:
            v = stack.pop()
            if v in visited: continue
            visited.add(v); group.add(v); stack.extend(rev[v])
        groups.append(group)
    return sorted(groups, key=lambda g: (-len(g), min(g)))


def attributes(parent, values):
    block = ET.SubElement(parent, 'attributes')
    for key, value in sorted(values.items()):
        ET.SubElement(block, 'attribute', name=key, **{'class': 'java.lang.String'}).text = str(value)


def write_xml(path, root, dtd):
    ET.indent(root, space='  ')
    data = ET.tostring(root, encoding='unicode')
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                    f'<!DOCTYPE {root.tag} SYSTEM "http://www.matsim.org/files/dtd/{dtd}">\n'
                    + data + '\n', encoding='utf-8')
    temp.replace(path)


def prepare(source, output, capacity_factor=1.0, priority_overrides=None):
    if not math.isfinite(capacity_factor) or not 0 < capacity_factor <= 1:
        raise ValueError("capacity_factor must be finite and in (0, 1]")
    root = ET.parse(source).getroot()
    if root.tag != 'osm': raise ValueError('Expected OSM XML')
    validate_turn_restrictions(root)
    raw_nodes = {n.get('id'): n for n in root.findall('node') if n.get('action') != 'delete'}
    transform = Transformer.from_crs(4326, 32615, always_xy=True)
    coords = {i: transform.transform(float(n.get('lon')), float(n.get('lat')), errcheck=True)
              for i, n in raw_nodes.items()}
    links, exclusions, warnings = [], Counter(), Counter()
    accepted_ways = set()
    blocked_nodes = {i for i, n in raw_nodes.items() if access_reason(tags(n)) or
                     (tags(n).get('barrier') in ('bollard', 'block', 'cycle_barrier') and
                      not any(tags(n).get(k) in ('yes', 'permissive') for k in ACCESS_KEYS[:2]))}
    for w in root.findall('way'):
        t, wid = tags(w), w.get('id')
        if w.get('action') == 'delete': continue
        reason = road_reason(t)
        if reason: exclusions[reason] += 1; continue
        refs = [n.get('ref') for n in w.findall('nd')]
        if len(refs) < 2 or any(n not in coords for n in refs):
            raise ValueError(f'Incomplete drivable way {wid}')
        directions = driving_directions(t)
        if 'lanes' not in t: warnings['ways_default_lanes'] += 1
        if 'maxspeed' not in t: warnings['ways_default_speed'] += 1
        try:
            parameters = {d: road_parameters(t, d, directions, ROAD_SPEED[t['highway']], capacity_factor)
                          for d in directions}
        except ValueError as exc:
            raise ValueError(f'Way {wid}: {exc}') from exc
        for index, (a,b) in enumerate(zip(refs,refs[1:])):
            if a in blocked_nodes or b in blocked_nodes:
                exclusions['segments_blocked_node'] += 1; continue
            length = math.dist(coords[a],coords[b])
            if length < .01: exclusions['zero_length_segments'] += 1; continue
            for direction in directions:
                key = 'forward' if direction == 1 else 'backward'
                physical = parameters[direction]
                src,dst = (a,b) if direction == 1 else (b,a)
                links.append(dict(id=f'osm_{wid}_{index}_{key}', **{'from':src,'to':dst},
                                  length=length, **physical, oneway='1', modes='car', origid=wid,
                                  osm_tags=t))
                accepted_ways.add(wid)
    if not links: raise ValueError('No drivable links')
    used = {l[k] for l in links for k in ('from','to')}
    groups = components(links)
    core = groups[0]
    critical_check = 'not_in_input'
    if all(n in raw_nodes for n in CRITICAL):
        if not set(CRITICAL) <= core: raise ValueError('3a Avenida critical crossings left the routable core')
        avenue = next(w for w in root.findall('way') if w.get('id') == '30279769')
        refs = [n.get('ref') for n in avenue.findall('nd')]
        a,b = refs.index(CRITICAL[0]), refs.index(CRITICAL[-1])
        edges = {(l['from'],l['to']) for l in links if l['origid']=='30279769'}
        if a >= b or any(pair not in edges for pair in zip(refs[a:b],refs[a+1:b+1])):
            raise ValueError('3a Avenida 14 -> 12 continuity lost')
        critical_check = 'shared nodes and continuous northbound route retained'
    network = ET.Element('network',name='SimZ1 OSM vehicle network')
    attributes(network,dict(visualProjection='EPSG:32615',coordinateReferenceSystem='EPSG:32615',
                            source='OpenStreetMap; geometry preserved, traffic defaults uncalibrated'))
    nblock = ET.SubElement(network,'nodes')
    for i in sorted(used):
        x,y=coords[i];n=ET.SubElement(nblock,'node',id=i,x=f'{x:.6f}',y=f'{y:.6f}')
        attributes(n,{'osm:'+k:v for k,v in tags(raw_nodes[i]).items()})
    lblock=ET.SubElement(network,'links',capperiod='01:00:00')
    for link in links:
        el=ET.SubElement(lblock,'link',**{k:str(v) for k,v in link.items() if k not in ('osm_tags', 'physical')})
        attributes(el, {**{'osm:'+k:v for k,v in link['osm_tags'].items()}, **link['physical']})
    priority_override_count = apply_priority_overrides(network, priority_overrides) if priority_overrides else 0
    # Retain all permitted geometry; do not silently erase services and dead ends via SCC cleaning.
    facilities=ET.Element('facilities',name='SimZ1 OSM activity proxies')
    starts=np.array([coords[l['from']] for l in links]);ends=np.array([coords[l['to']] for l in links])
    vectors=ends-starts;norm=(vectors*vectors).sum(axis=1)
    facility_count=0
    for el in list(raw_nodes.values())+root.findall('way'):
        t=tags(el)
        activity = ('shop' if 'shop' in t else 'education' if t.get('amenity') in ('school','college','university','kindergarten')
                    else 'work' if 'office' in t or t.get('amenity') in ('hospital','clinic','bank','townhall')
                    else 'home' if t.get('building') in ('house','residential','apartments') else None)
        if activity is None: continue
        if el.tag=='node': point=np.array(coords[el.get('id')])
        else:
            refs=[n.get('ref') for n in el.findall('nd')]
            if refs and refs[0]==refs[-1]: refs=refs[:-1]
            if not refs or any(n not in coords for n in refs): continue
            point=np.mean([coords[n] for n in refs],axis=0)
        fraction=np.clip(((point-starts)*vectors).sum(axis=1)/norm,0,1)
        distances=np.linalg.norm(point-(starts+fraction[:,None]*vectors),axis=1)
        idx=int(np.argmin(distances))
        if distances[idx]>100: warnings['facilities_beyond_100m_skipped']+=1;continue
        f=ET.SubElement(facilities,'facility',id=f'osm_{el.tag}_{el.get("id")}',
                        x=str(point[0]),y=str(point[1]),linkId=links[idx]['id'])
        ET.SubElement(f,'activity',type=activity)
        attributes(f,dict(source='OSM activity proxy; opening hours/capacity not inferred',
                          name=t.get('name',''),snapDistanceM=f'{distances[idx]:.3f}'))
        facility_count+=1
    # An explicit one-person smoke plan makes the scaffold executable; not a demand calibration.
    candidates=[l for l in links if l['from'] in core and l['to'] in core]
    pair=[candidates[0],candidates[len(candidates)//2]]
    for name,link,activity in zip(('smoke_home','smoke_work'),pair,('home','work')):
        x,y=coords[link['from']]
        f=ET.SubElement(facilities,'facility',id=name,x=str(x),y=str(y),linkId=link['id'])
        act=ET.SubElement(f,'activity',type=activity)
        ET.SubElement(act,'opentime',day='wk',start_time='09:00:00',end_time='15:00:00')
        attributes(f,dict(source='synthetic smoke-test facility'))
    population=ET.Element('population')
    person=ET.SubElement(population,'person',id='simz1_smoke');plan=ET.SubElement(person,'plan',selected='yes')
    ET.SubElement(plan,'activity',type='home',link=pair[0]['id'],facility='smoke_home',end_time='09:01:00')
    ET.SubElement(plan,'leg',mode='car')
    ET.SubElement(plan,'activity',type='work',link=pair[1]['id'],facility='smoke_work')
    config=ET.Element('config')
    modules={'global':dict(coordinateSystem='EPSG:32615',randomSeed='20261002'),
             'network':dict(inputNetworkFile='network.xml',laneDefinitionsFile='lanes.xml'),
             'facilities':dict(inputFacilitiesFile='facilities.xml'),
             'plans':dict(inputPlansFile='population-smoke.xml'),
             'controler':dict(outputDirectory='output/simz1-cycle2',lastIteration='0',overwriteFiles='failIfDirectoryExists',
                              enableLinkToLinkRouting='true'),
             'qsim':dict(startTime='00:00:00',endTime='24:00:00',useLanes='true',usingFastCapacityUpdate='false',
                         simStarttimeInterpretation='onlyUseStarttime',simEndtimeInterpretation='onlyUseEndtime',
                         flowCapacityFactor='1.0',storageCapacityFactor='1.0'),
             'travelTimeCalculator':dict(calculateLinkTravelTimes='true',calculateLinkToLinkTravelTimes='true',
                                         separateModes='false',maxTime='86400'),
             'zona1WithinDayRouting':dict(routingPolicy='fastest-time'),
             'simz1Admission':dict(storagePolicy='strict-receiver-v1'),
             'zona1Priority':dict(enabled='true',stopSeconds='5',maxYieldSeconds='30',
                                  classification='osm-hierarchy',conflicts='geometric'),
             # LanesGenerator exports these inputs after the OSM network is prepared.
             'signalsystems':dict(useSignalsystems='true',useAmbertimes='true',signalsystems='signalSystems.xml',
                                  signalgroups='signalGroups.xml',signalcontrol='signalControl.xml')}
    for name,params in modules.items():
        mod=ET.SubElement(config,'module',name=name)
        for k,v in params.items(): ET.SubElement(mod,'param',name=k,value=v)
    score=ET.SubElement(config,'module',name='planCalcScore')
    for activity in ('home','work'):
        ps=ET.SubElement(score,'parameterset',type='activityParams')
        for k,v in dict(activityType=activity,typicalDuration='06:00:00',scoringThisActivityAtAll='false').items():
            ET.SubElement(ps,'param',name=k,value=v)
    output.mkdir(parents=True,exist_ok=True)
    for name,el,dtd in [('network.xml',network,'network_v2.dtd'),('facilities.xml',facilities,'facilities_v1.dtd'),
                        ('population-smoke.xml',population,'population_v6.dtd'),('config-simz1.xml',config,'config_v2.dtd')]:
        # Preserve the reviewed master configuration when regenerating road inputs.
        if name == 'config-simz1.xml' and (output/name).exists():
            continue
        write_xml(output/name,el,dtd)
    with (output/'road-parameters.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ['link_id', 'osm_way', 'name', 'highway', 'lanes', 'speed_kmh', 'capacity_veh_h', 'lanes_source', 'speed_source', 'review']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for link in links:
            meta = link['physical']
            writer.writerow(dict(link_id=link['id'], osm_way=link['origid'],
                name=link['osm_tags'].get('name',''), highway=link['osm_tags']['highway'],
                lanes=link['permlanes'], speed_kmh=meta['physical:modeledMaxSpeedKmh'],
                capacity_veh_h=link['capacity'], lanes_source=meta['physical:lanesSource'],
                speed_source=meta['physical:speedSource'], review=meta.get('physical:speedReview','')))
    restrictions=[r.get('id') for r in root.findall('relation') if tags(r).get('type')=='restriction']
    report=dict(ideal_capacity_per_lane_veh_h=IDEAL_CAPACITY, capacity_factor=capacity_factor,
                priority_override_count=priority_override_count,
                priority_override_sha256=hashlib.sha256(Path(priority_overrides).read_bytes()).hexdigest() if priority_overrides else None,
                lane_sources=dict(Counter(l['physical']['physical:lanesSource'] for l in links)),
                speed_sources=dict(Counter(l['physical']['physical:speedSource'] for l in links)),
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),crs='EPSG:32615',
                source_bounds=root.find('bounds').attrib if root.find('bounds') is not None else None,
                nodes=len(used),links=len(links),accepted_ways=len(accepted_ways),exclusions=dict(exclusions),
                warnings=dict(warnings),strong_components=len(groups),largest_component_nodes=len(core),
                critical_3a_avenida=critical_check,osm_facilities=facility_count,synthetic_facilities=2,
                ignored_turn_restriction_relations=restrictions,
                limitations=['No inferred signal plans; OSM traffic_signals retained as metadata',
                             'Turn restrictions are reported, not enforced by the link graph',
                             'Facilities use node positions / mean of way vertices; relations not converted',
                             'Facility hours and capacities unknown; no real demand supplied',
                             'Speed, capacity and missing lane counts use explicit modeling defaults',
                             'All accepted components retained; smoke demand uses largest directed component'])
    (output/'processing-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=SCENARIO/'map.osm')
    parser.add_argument('--output-dir',type=Path,default=SCENARIO)
    parser.add_argument('--capacity-factor', type=float, default=1.0,
                        help='Multiplier of 2000 veh/h/lane, in (0,1]; default ideal, not calibrated')
    parser.add_argument('--priority-overrides', type=Path,
                        help='Reviewed directed-link CSV: link_id,to_node,priority_role,priority_control,source,rationale')
    args=parser.parse_args()
    print(json.dumps(prepare(args.input,args.output_dir,args.capacity_factor,args.priority_overrides),indent=2,ensure_ascii=False))


if __name__=='__main__': main()
