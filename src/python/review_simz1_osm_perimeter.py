"""Offline OSM boundary assembly and read-only network comparison. Never runs QSim.

Input is the saved official relation/full response. No downloading, network edits,
population generation, or automatic approval of incorporation sites.
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from pyproj import Geod, Transformer
from simz1_gateway_od import Polygon
from simz1_visual_lanes import _path
from simz1_osm_turn_audit import load_lanes
from simz1_balanced_od import native_queue_ends

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'scenarios/zona1'
DEST = SCENARIO/'od/balanced-gateway-v1'
URL = 'https://api.openstreetmap.org/api/0.6/relation/9283360/full'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, data):
    path = DEST/name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return path


def assemble(root):
    relation = next(r for r in root.findall('relation') if r.get('id') == '9283360')
    tags = {t.get('k'): t.get('v') for t in relation.findall('tag')}
    if any(tags.get(k) != v for k, v in dict(name='Zona 1', boundary='administrative',
                                           admin_level='8', type='boundary').items()):
        raise ValueError('Unexpected relation identity/tags')
    nodes = {n.get('id'): [float(n.get('lon')), float(n.get('lat'))] for n in root.findall('node')}
    if any(not -180 <= x <= 180 or not -90 <= y <= 90 for x,y in nodes.values()):
        raise ValueError('OSM coordinates outside RFC7946 WGS84 longitude/latitude range')
    ways = {w.get('id'): [n.get('ref') for n in w.findall('nd')] for w in root.findall('way')}
    members = [m.get('ref') for m in relation.findall('member') if m.get('type') == 'way' and m.get('role') == 'outer']
    if len(members) != len(set(members)) or not members:
        raise ValueError('Duplicate/empty outer membership')
    if any(m.get('type') == 'way' and m.get('role') != 'outer' for m in relation.findall('member')):
        raise ValueError('New inner/unknown role requires explicit review; do not discard it')
    ends = defaultdict(list)
    for wid in members:
        if wid not in ways or len(ways[wid]) < 2 or any(n not in nodes for n in ways[wid]):
            raise ValueError('Missing way/nodes: '+wid)
        for node in (ways[wid][0], ways[wid][-1]):
            ends[node].append(wid)
    if any(len(v) != 2 for v in ends.values()):
        raise ValueError('Open/branching outer ring')
    remaining = set(members); rings = []
    while remaining:
        wid = min(remaining); remaining.remove(wid)
        chain = list(ways[wid])
        while chain[0] != chain[-1]:
            choices = [w for w in ends[chain[-1]] if w in remaining]
            if len(choices) != 1:
                raise ValueError('Ambiguous/incomplete ring')
            wid = choices[0]; remaining.remove(wid)
            segment = ways[wid]
            if segment[-1] == chain[-1]: segment = segment[::-1]
            chain.extend(segment[1:])
        ring = [nodes[n] for n in chain]
        area, _ = Geod(ellps='WGS84').polygon_area_perimeter(*zip(*ring))
        if area < 0: ring.reverse()
        Polygon(dict(type='Polygon', coordinates=[ring]))  # closure and self-intersections
        rings.append(ring)
    if len(rings) != 1:
        raise ValueError('Multiple outer polygons require multi-part contract review; no parts discarded')
    geometry = dict(type='Polygon', coordinates=rings)
    return relation, tags, members, geometry


def main():
    source = DEST/'source/relation-9283360-full.osm'
    relation, tags, members, geometry = assemble(ET.parse(source).getroot())
    forward = Transformer.from_crs('EPSG:4326','EPSG:32615',always_xy=True)
    reverse = Transformer.from_crs('EPSG:32615','EPSG:4326',always_xy=True)
    metric = dict(type='Polygon', coordinates=[[list(forward.transform(*p)) for p in ring] for ring in geometry['coordinates']])
    polygon = Polygon(metric)
    perimeter = save('perimeter.geojson',dict(type='FeatureCollection',features=[dict(type='Feature',
        properties=dict(osm_relation=9283360, name=tags['name'], admin_level=8,
                        source=URL, attribution='© OpenStreetMap contributors', license='ODbL-1.0'),geometry=geometry)]))
    net = ET.parse(SCENARIO/'network.xml').getroot()
    nodes = {n.get('id'): (float(n.get('x')),float(n.get('y'))) for n in net.findall('nodes/node')}
    lanes = load_lanes(SCENARIO/'lanes.xml')
    queue_ends = native_queue_ends(SCENARIO/'network.xml', SCENARIO/'lanes.xml')
    rows, paths = [], {}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for link in net.findall('links/link'):
        ident, a, b = link.get('id'),link.get('from'),link.get('to')
        attrs = {v.get('name'):v.text for v in link.findall('attributes/attribute')}
        geo, _, valid = _path(attrs, list(reverse.transform(*nodes[a])), list(reverse.transform(*nodes[b])), reverse.transform)
        if not valid: raise ValueError('Ambiguous native geometry '+ident)
        path = [forward.transform(*xy) for xy in geo]; paths[ident] = path
        intervals = polygon.path_intervals(path)
        inside_a, inside_b = polygon.contains(path[0],False), polygon.contains(path[-1],False)
        whole = len(intervals)==1 and intervals[0][0] <= 1e-10 and intervals[0][1] >= len(path)-1-1e-10
        kind = ('interior' if whole and inside_a and inside_b else
                'external' if not intervals and not inside_a and not inside_b else
                'entry_crossing' if not inside_a and inside_b and len(intervals)==1 else
                'exit_crossing' if inside_a and not inside_b and len(intervals)==1 else 'complex_or_boundary')
        rows.append(dict(link_id=ident,from_node=a,to_node=b,classification=kind,
            length_m=float(link.get('length')),lanes=float(link.get('permlanes')),
            capacity_pcu_h=float(link.get('capacity')),native_queue_end_m=queue_ends[ident],
            osm_way=link.get('origid'),highway=attrs.get('osm:highway'),service=attrs.get('osm:service'),
            car_access=next((attrs['osm:'+k] for k in ('motorcar','motor_vehicle','vehicle','access') if 'osm:'+k in attrs),'yes'),
            lane_source=attrs.get('physical:lanesSource'),capacity_model=attrs.get('physical:capacityModel'),
            capacity_basis='Unchanged network.xml model parameter; not measured incorporation flow',
            activity_access_verified=False))
        outgoing[a].append(ident); incoming[b].append(ident)
    byid = {r['link_id']:r for r in rows}
    for row in rows:
        key = row['link_id']
        row['allowed_successors'] = sorted(k for k in outgoing[row['to_node']] if key not in lanes or k in lanes[key])
        row['allowed_predecessors'] = sorted(k for k in incoming[row['from_node']] if k not in lanes or key in lanes[k])
    crossings = []
    for row in rows:
        kind = row['classification']
        if kind not in ('entry_crossing','exit_crossing'): continue
        exterior = row['allowed_predecessors'] if kind=='entry_crossing' else row['allowed_successors']
        interior = row['allowed_successors'] if kind=='entry_crossing' else row['allowed_predecessors']
        crossings.append(dict(row, existing_exterior_links=[k for k in exterior if byid[k]['classification']=='external'],
            interior_observation_links=[k for k in interior if byid[k]['classification']=='interior']))
    local = ET.parse(SCENARIO/'map.osm').getroot()
    local_ways = {w.get('id') for w in local.findall('way')}
    area,_ = Geod(ellps='WGS84').polygon_area_perimeter(*zip(*geometry['coordinates'][0]))
    hashes = {name:sha(SCENARIO/name) for name in ('network.xml','lanes.xml','map.osm')}
    coords = [p for ring in geometry['coordinates'] for p in ring]
    bbox = [min(p[i] for p in coords) for i in (0,1)]+[max(p[i] for p in coords) for i in (0,1)]
    counts = dict(Counter(r['classification'] for r in rows))
    from simz1_od_policy import validate_osm_turns
    try:
        turns = validate_osm_turns(SCENARIO/'map.osm',SCENARIO/'network.xml',SCENARIO/'lanes.xml')
    except ValueError as error:
        turns = dict(checked=False,error=str(error))
    from simz1_osm_turn_audit import inspect_restrictions
    restriction_detail = inspect_restrictions(SCENARIO/'map.osm',SCENARIO/'network.xml',SCENARIO/'lanes.xml')
    save('osm-turn-evidence.json',restriction_detail)
    catalog=json.loads((SCENARIO/'agent-types-balanced-v1.json').read_text())
    body=max(p['dimensions']['length_m'] for p in catalog['profiles'].values() if p['family'] in ('carro','moto'))
    candidates={'entry':{},'exit':{}};blocked=[]
    for cross in crossings:
        role='entry' if cross['classification']=='entry_crossing' else 'exit'
        observations=cross['interior_observation_links']
        if not observations:
            blocked.append(dict(link_id=cross['link_id'],reason='No immediately connected interior observation respecting lanes'));continue
        # Search real exterior chains up to the existing 250 m contract, never
        # extend the network. A shortest eligible chain is retained per anchor.
        stack=[([k],byid[k]['length_m']) for k in cross['existing_exterior_links']]
        found=0
        while stack:
            chain,length=stack.pop();anchor=chain[-1];row=byid[anchor]
            if length>250:continue
            if row['car_access'] not in ('yes','permissive','designated'):continue
            if row['native_queue_end_m']>=body+0.1:
                path=list(reversed(chain))+[cross['link_id'],observations[0]] if role=='entry' else [observations[0],cross['link_id']]+chain
                record=dict(id=role+'-'+cross['link_id'],anchor_link=anchor,crossing_link=cross['link_id'],
                    observation_link=observations[0],link_ids=path,exterior_length_m=length,
                    useful_length_upper_bound_m=row['native_queue_end_m'],native_capacity_upper_bound_pcu_h=row['capacity_pcu_h'],
                    native_lanes=row['lanes'],lane_source=row['lane_source'],
                    verified_geometry_and_lane_connectivity=True,activity_allowed=None,
                    incorporation_capacity_pcu_h=None,review=dict(verified=False,reason='Activity/incorporation evidence unavailable; through-link capacity is only an upper bound'))
                old=candidates[role].get(anchor)
                if not old or length<old['exterior_length_m']:candidates[role][anchor]=record
                found+=1
                continue
            neighbors=row['allowed_predecessors'] if role=='entry' else row['allowed_successors']
            for k in neighbors:
                if k not in chain and byid[k]['classification']=='external':stack.append((chain+[k],length+byid[k]['length_m']))
        if not found:blocked.append(dict(link_id=cross['link_id'],from_node=cross['from_node'],to_node=cross['to_node'],
            reason='No existing permitted exterior chain <=250 m with native first queue >= body + 0.10 m',
            exterior_links=cross['existing_exterior_links'],allowed_predecessors=cross['allowed_predecessors'],allowed_successors=cross['allowed_successors']))
    # Directed reachability uses only interior links and permitted lane movements.
    connected=[]
    for origin in candidates['entry'].values():
        reached={origin['observation_link']};todo=list(reached)
        while todo:
            key=todo.pop()
            for nxt in byid[key]['allowed_successors']:
                if nxt not in reached and byid[nxt]['classification']=='interior':reached.add(nxt);todo.append(nxt)
        connected.append(dict(entry_anchor=origin['anchor_link'],reachable_interior_links=len(reached),
            reachable_exit_anchors=sorted(r['anchor_link'] for r in candidates['exit'].values() if r['observation_link'] in reached)))
    site_candidates=[dict(link_id=r['link_id'],osm_way=r['osm_way'],service=r['service'],
        useful_length_upper_bound_m=r['native_queue_end_m'],native_capacity_upper_bound_pcu_h=r['capacity_pcu_h'],
        activity_allowed=None,incorporation_capacity_pcu_h=None,review=dict(verified=False,reason='Mapped driveway/parking aisle is a candidate, not permission or measured incorporation flow'))
        for r in rows if r['classification']=='interior' and r['service'] in ('parking_aisle','driveway') and
        r['car_access'] in ('yes','permissive','designated') and r['native_queue_end_m']>=body+0.1]
    # This review supplies geometry/physics evidence, never invents permission to
    # originate activity on a link or field-observed incorporation capacity.
    report = dict(review_date='2026-11-01',generated_utc=datetime.now(timezone.utc).isoformat(),
        source=URL,relation=dict(relation.attrib),tags=tags,outer_ways=len(members),
        missing_outer_ways_in_download=[],missing_outer_ways_in_local_extract=sorted(set(members)-local_ways),
        geometry_valid=True,rfc7946=True,area_km2=area/1e6,bbox=bbox,
        local_osm_bounds=local.find('bounds').attrib,network_node_count=len(nodes),link_counts=counts,
        crossing_links=crossings,possible_entry_chains=sum(bool(r['existing_exterior_links'] and r['interior_observation_links']) for r in crossings if r['classification']=='entry_crossing'),
        possible_exit_chains=sum(bool(r['existing_exterior_links'] and r['interior_observation_links']) for r in crossings if r['classification']=='exit_crossing'),
        perimeter_sha256=sha(perimeter),source_sha256=sha(source),input_sha256=hashes,
        source_file_hashes={p.name:sha(p) for p in sorted((DEST/'source').iterdir()) if p.is_file()},
        status='BLOCKED',reason='No approved incorporation sites. See directed crossing/continuation inventory; no artificial exterior connectors.',
        attribution='© OpenStreetMap contributors; https://www.openstreetmap.org/copyright; ODbL 1.0',
        qualification='OSM administrative boundary v34, not cadastral/legal municipal certification. Traffic physics remain uncalibrated model parameters.')
    report.update(directed_turn_review=turns,private_max_body_m=body,entry_anchor_candidates=list(candidates['entry'].values()),
        exit_anchor_candidates=list(candidates['exit'].values()),blocked_crossings=blocked,interior_access_candidates=site_candidates,
        directed_connectivity=connected,eligible_entry_anchor_count=len(candidates['entry']),eligible_exit_anchor_count=len(candidates['exit']),
        possible_entry_chains=len(candidates['entry']),possible_exit_chains=len(candidates['exit']),
        connected_entry_exit_pairs=sum(len(r['reachable_exit_anchors']) for r in connected),
        missing_conditions=['Document activity permission and incorporation capacity for specific external anchors and internal sites.',
                            'Resolve OSM turn restrictions in a separately authorized network/lane revision; see osm-turn-evidence.json.',
                            'Native through-link capacities/assumed lanes are not measured incorporation capacities.',
                            'User must run integrated Validate and real 180000 preflight; neither was executed.',
                            'Completed/valid, body-clearance, actual traffic completion and screening require a real run.'])
    save('geography-review.json',report)
    with (DEST/'network-access-inventory.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    review=dict(verified=True,version='osm-9283360-v'+relation.get('version'),source=URL,
                reviewed_by='Codex: complete membership, ring topology, WGS84 and metric network comparison',reviewed_at='2026-11-01')
    save('access.json',dict(schema_version='simz1-verified-private-access-v1',
        review=dict(review,verified=False),perimeter=dict(review,schema_version='simz1-verified-perimeter-v1',sha256=sha(perimeter)),
        network_sha256=hashes['network.xml'],lanes_sha256=hashes['lanes.xml'],osm_sha256=hashes['map.osm'],
        entry_gateways=[],exit_gateways=[],internal_origins=[],
        candidate_entry_gateways=list(candidates['entry'].values()),candidate_exit_gateways=list(candidates['exit'].values()),
        candidate_internal_origins=site_candidates,
        evidence='geography-review.json + network-access-inventory.csv',status='BLOCKED',
        reason='Unverified access catalogue; no permission/capacity evidence manufactured.'))
    save('mix.json',dict(EXTERNAL_EXTERNAL_THROUGH=50,EXTERNAL_INTERNAL=20,INTERNAL_EXTERNAL=20,INTERNAL_INTERNAL=10))
    save('mix-provenance.json',dict(version='synthetic-ee50-ei20-ie20-ii10-v1',empirical_calibration=False,
        source='Explicit user-authorized experimental assumption; not Guatemala observed traffic counts',
        scope='Private road demand only; freight and 269 buses retain their services and schedules',
        mix_sha256=sha(DEST/'mix.json'),date='2026-11-01'))
    print(json.dumps({k:report[k] for k in ('area_km2','outer_ways','link_counts','possible_entry_chains','possible_exit_chains','perimeter_sha256','status')},indent=2))


if __name__=='__main__':main()
