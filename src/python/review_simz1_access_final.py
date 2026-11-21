"""Bounded static access review. No population, preflight, Java or simulation.

Reuses the saved evidence, preserves the original scenario and writes a versioned
copy with only the ten unambiguous node-turn corrections. Remaining restrictions
are reported, never waived. Reviewed means model eligibility, not field permission.
"""
from collections import Counter, defaultdict, deque
import copy
import csv
import json
import math
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from pyproj import Transformer
from simz1_balanced_od import BalancedGatewayModel, digest, native_queue_ends
from simz1_gateway_od import load_gateway_model
from simz1_osm_turn_audit import inspect_restrictions, load_lanes, load_xml
from simz1_od_policy import validate_osm_turns

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scenarios/zona1'
OUT = SOURCE / 'od/balanced-gateway-v1'
SCENARIO = OUT / 'access-review-v2'
VERSION = 'simz1-access-model-review-v2-20261101'
BODY, GAP = 4.5, .10


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def attestation():
    return dict(verified=True, version=VERSION,
                source='access-review.json; network-access-inventory.csv; geography-review.json; osm-turn-resolution.json',
                reviewed_by='Codex: static source, directed lane, storage and synthetic budget review',
                reviewed_at='2026-11-01', scope='model_eligibility_only; no observed flow or property permission')


def correct_lanes(raw, evidence):
    """Remove only individually proven prohibited terminal targets, byte preserving."""
    changes = []
    for row in evidence['rows']:
        if row['status'] != 'mappable' or row['lanes_admit_prohibited_target'] != 'true':
            continue
        if row['missing_members'] != '[]' or row['semantics_review']:
            raise ValueError('Unreviewed node restriction '+row['relation_id'])
        start, end = row['from_links'], row['to_links']
        if ';' in start+end or not row['restriction'].startswith('no_'):
            raise ValueError('Ambiguous node mapping')
        pattern = rb'<lanesToLinkAssignment linkIdRef="'+re.escape(start.encode())+rb'">.*?</lanesToLinkAssignment>'
        matches = list(re.finditer(pattern, raw, re.S))
        if len(matches) != 1:
            raise ValueError('Missing lane assignment '+start)
        match = matches[0]
        block, count = re.subn(rb'^[ \t]*<toLink refId="'+re.escape(end.encode())+rb'"\s*/>\r?\n',
                               b'', match.group(), flags=re.M)
        if count != len(row['admitting_terminal_lanes'].split(';')):
            raise ValueError('Terminal lane evidence differs')
        parsed = ET.fromstring(block)
        if any(len(lane.find('leadsTo')) == 0 for lane in parsed.findall('lane')):
            raise ValueError('Correction would strand a physical lane')
        raw = raw[:match.start()] + block + raw[match.end():]
        changes.append(dict(relation_id=row['relation_id'], from_link=start, to_link=end,
                            terminal_lanes=row['admitting_terminal_lanes'].split(';'), removed_targets=count))
    return raw, changes


def contains_sequence(path, sequence):
    return any(path[i:i+len(sequence)] == sequence for i in range(len(path)-len(sequence)+1))


def main():
    original = OUT/'source/access-candidates-v1.json'
    if not original.exists():
        shutil.copyfile(OUT/'access.json', original)
    document = json.loads(original.read_bytes())
    evidence = json.loads((OUT/'osm-turn-evidence.json').read_bytes())
    geography = json.loads((OUT/'geography-review.json').read_bytes())
    with (OUT/'network-access-inventory.csv').open(encoding='utf-8') as stream:
        inventory = {r['link_id']: r for r in csv.DictReader(stream)}
    for key, name in [('network','network.xml'), ('lanes','lanes.xml'), ('osm','map.osm')]:
        if digest(SOURCE/name) != evidence['summary']['hashes'][key] or digest(SOURCE/name) != document[key+'_sha256']:
            raise ValueError('Original evidence no longer matches '+name)
    if digest(OUT/'perimeter.geojson') != document['perimeter']['sha256']:
        raise ValueError('Perimeter evidence changed')
    SCENARIO.mkdir(exist_ok=True)
    # These are exactly the XML inputs named by config plus the OSM source.
    names = ['config-simz1.xml','network.xml','map.osm','facilities.xml','plans.xml',
             'vehicle-types.xml','signalSystems.xml','signalGroups.xml','signalControl.xml']
    for name in names:
        target = SCENARIO/name
        if target.exists() and digest(target) != digest(SOURCE/name):
            raise ValueError('Refuse to overwrite an edited isolated input '+name)
        shutil.copyfile(SOURCE/name, target)
    corrected, changes = correct_lanes((SOURCE/'lanes.xml').read_bytes(), evidence)
    target = SCENARIO/'lanes.xml'
    if target.exists() and target.read_bytes() != corrected:
        raise ValueError('Refuse to overwrite another lane revision')
    target.write_bytes(corrected)
    after = inspect_restrictions(SCENARIO/'map.osm',SCENARIO/'network.xml',target)
    after_by_id = {r['relation_id']:r for r in after['rows']}
    moves = load_lanes(target)
    nodes = load_xml(SCENARIO/'network.xml')
    native = {r.get('id'):r for r in nodes.findall('links/link')}
    osm = load_xml(SCENARIO/'map.osm')
    ways = {r.get('id'):r for r in osm.findall('way')}
    tags = {k:{t.get('k'):t.get('v') for t in w.findall('tag')} for k,w in ways.items()}
    lane_xml = load_xml(target)
    lane_caps = {r.get('id'):float(r.find('capacity').get('vehiclesPerHour')) for r in lane_xml.findall('lanesToLinkAssignment/lane')}
    forbidden = [seq for r in after['rows'] for seq in json.loads(r['directed_sequences']) if r['restriction'].startswith('no_')]
    unresolved_links = {k for k,v in native.items() if v.get('origid') == '34993910'}
    resolution = []
    changed = {c['relation_id']:c for c in changes}
    for before in evidence['rows']:
        ident = before['relation_id']
        if ident not in changed and ident not in ('17478998','17884471'):
            continue
        row = dict(before=before, after=after_by_id[ident])
        if ident in changed:
            assert after_by_id[ident]['lanes_admit_prohibited_target'] == 'false'
            row.update(status='RESOLVED_IN_ISOLATED_COPY', correction=changed[ident])
        elif ident == '17478998':
            via = 'osm_1270930401_0_forward'
            row.update(status='BLOCKED', reason='History-dependent via-way prohibition; pair removal would also ban another approach.',
                       via_predecessors=sorted(k for k,v in moves.items() if via in v),
                       required='Exact path-aware enforcement; no safe lane-only equivalence in this graph')
        else:
            relation = next(r for r in osm.findall('relation') if r.get('id') == ident)
            row.update(status='BLOCKED', reason='Local OSM v2 contains only to=34993910; from and via are absent, target exists in car network.',
                       members=[m.attrib for m in relation.findall('member')], affected_to_links=sorted(unresolved_links),
                       required='Complete authoritative relation members; turn and lanes cannot be identified from this source')
        resolution.append(row)
    try:
        validate_osm_turns(SCENARIO/'map.osm',SCENARIO/'network.xml',target)
        raise AssertionError('Unresolved restrictions must fail closed')
    except ValueError as exc:
        turn_blocker = str(exc)
    save(OUT/'osm-turn-resolution.json', dict(version=VERSION, source_hashes=evidence['summary']['hashes'],
         effective_hashes=after['summary']['hashes'], changes=changes, relations=resolution,
         unchanged_copied_files={name:digest(SCENARIO/name) for name in names}, validation_error=turn_blocker))

    base = load_gateway_model(SCENARIO/'network.xml', OUT/'perimeter.geojson', target)
    project = Transformer.from_crs('EPSG:4326','EPSG:32615',always_xy=True)
    for link in base.links.values():
        link['metric_path'] = [project.transform(*xy) for xy in link['path']]
    ends = native_queue_ends(SCENARIO/'network.xml',target)
    # Static constructor is used only for individual geometry checks; production
    # load_model rejects the two unresolved restrictions before exposing routes.
    first_site = document['candidate_internal_origins'][0]['link_id']
    bootstrap = dict(entry_gateways=[],exit_gateways=[],internal_origins=[dict(link_id=first_site,
        review=attestation(),useful_length_m=ends[first_site],incorporation_capacity_pcu_h=1,
        activity_allowed=True,capacity_basis='temporary static constructor, never saved as approval')])
    model = BalancedGatewayModel(base,bootstrap,ends,moves)

    def validate_path(path):
        missing = [k for k in path if k not in model.classification]
        if missing:
            detail = [dict(link_id=k,inventory_classification=inventory[k]['classification'],
                           intervals=base.polygon.path_intervals(base.links[k]['path']),
                           start_inside=base.polygon.contains(base.links[k]['path'][0],False),
                           end_inside=base.polygon.contains(base.links[k]['path'][-1],False)) for k in missing]
            raise ValueError('Unclassified in effective boundary contract: '+json.dumps(detail,sort_keys=True))
        model.validate_route(path)
        if unresolved_links.intersection(path):
            raise ValueError('Uses target of incomplete relation 17884471')
        if any(contains_sequence(path,seq) for seq in forbidden):
            raise ValueError('Violates via-way restriction 17478998')
        for key in path:
            element = native[key]; way = element.get('origid')
            if way not in ways or inventory[key]['osm_way'] != way:
                raise ValueError('Missing/mismatched OSM provenance')
            refs = [n.get('ref') for n in ways[way].findall('nd')]
            edge = (element.get('from'),element.get('to'))
            directed = set(zip(refs,refs[1:]))
            if edge not in directed and edge[::-1] not in directed:
                raise ValueError('Link endpoints are not consecutive source OSM nodes')
            oneway = tags[way].get('oneway')
            if (oneway in ('yes','1','true') and edge not in directed) or (oneway == '-1' and edge[::-1] not in directed):
                raise ValueError('Source OSM direction violated')
            access = next((tags[way][k] for k in ('motorcar','motor_vehicle','vehicle','access') if k in tags[way]), 'yes')
            if access not in ('yes','designated','permissive'):
                raise ValueError('Explicit OSM access restriction')

    def capacity(path):
        values = [dict(link_id=k,capacity_pcu_h=model.links[k]['capacity']) for k in path]
        turns = [dict(from_link=a,to_link=b,terminal_lanes=sorted(moves[a][b]),
                      capacity_pcu_h=sum(lane_caps[l] for l in moves[a][b])) for a,b in zip(path,path[1:]) if a in moves]
        limit = min(r['capacity_pcu_h'] for r in values+turns)
        return limit,dict(kind='synthetic_model_budget_not_observed',formula='min(existing link capacities, reachable terminal lane capacities for each movement)',
            link_budgets=values,movement_budgets=turns,observed_pcu_h=None,
            limitation='Nominal scheduled PCU ceiling; no measured saturation, insertion, signal discharge or reserved service headroom')

    # Four preserved freight routes: only rebind their pinned lane hash after
    # checking every directed movement against this copy. No dispatch/rerouting.
    freight_source=SOURCE/'freight/weekday-compact-v3'
    freight=json.loads((freight_source/'routes.json').read_bytes())
    freight_checks=[]
    for route in freight['routes']:
        path=route['link_ids']
        if (any(native[a].get('to') != native[b].get('from') or
                (a in moves and b not in moves[a]) for a,b in zip(path,path[1:])) or
                unresolved_links.intersection(path) or any(contains_sequence(path,s) for s in forbidden)):
            raise ValueError('Cannot rebind unchanged freight route '+route['route_id'])
        freight_checks.append(dict(route_id=route['route_id'],links=len(path),directed_movements_pass=True))
    freight['lanes_sha256']=digest(target)
    service_config=json.loads((freight_source/'service-composition-v3.json').read_bytes())
    service_config['osm_file']='../map.osm'
    freight_dir=SCENARIO/'freight'; freight_dir.mkdir(exist_ok=True)
    save(freight_dir/'routes.json',freight)
    save(freight_dir/'service-composition-v3.json',service_config)
    transit=json.loads((SOURCE/'transit/weekday-v2/route-bundle.json').read_bytes())
    removed_pairs={(c['from_link'],c['to_link']) for c in changes}
    transit_checks=[]
    for service in transit['services']:
        for part in service['parts']:
            path=part['link_ids']
            transit_checks.append(dict(service_id=service['service_id'],part_id=part['part_id'],
                conflicts_with_removed_movements=sorted(removed_pairs.intersection(zip(path,path[1:]))),
                forbidden_via_sequence=any(contains_sequence(path,s) for s in forbidden),
                incomplete_relation_target_links=sorted(unresolved_links.intersection(path))))

    decisions = []
    for role in ('entry','exit'):
        candidates = []
        for old in document['candidate_'+role+'_gateways']:
            row = copy.deepcopy(old)
            decision = dict(role=role,id=row['id'],anchor_link=row['anchor_link'],crossing_link=row['crossing_link'])
            try:
                validate_path(row['link_ids'])
                key = row['anchor_link']
                if ends[key]+1e-8 < BODY+GAP:
                    raise ValueError('Native initial queue cannot hold maximum private body + 0.10 m')
                rate,basis = capacity(row['link_ids'])
                row.update(flow_role='boundary_'+role, useful_length_m=ends[key], capacity_basis=basis,
                           review=attestation(),activity_allowed=None,incorporation_capacity_pcu_h=None,
                           **{role+'_capacity_pcu_h':rate})
                row['activity_basis'] = 'Not applicable: modeled boundary source/sink, no parking or property permission claimed'
                row['storage_basis'] = dict(native_first_queue_m=ends[key],body_m=BODY,gap_m=GAP,
                                           whole_private_slots_per_lane=math.floor(ends[key]/(BODY+GAP)))
                row['source_evidence'] = [dict(link_id=k,osm_way=native[k].get('origid'),osm_tags=tags[native[k].get('origid')]) for k in row['link_ids']]
                model._gateways([row],role)
                candidates.append((row,decision))
            except ValueError as exc:
                decision.update(status='REJECTED',reason=str(exc))
                decisions.append(decision)
        # One chain per physical directed crossing. Prefer storage, then shorter
        # existing exterior chain, then ID; never add capacities of alternatives.
        chosen,anchors = {},set()
        for row,decision in sorted(candidates,key=lambda pair:(-pair[0]['useful_length_m'],pair[0]['exterior_length_m'],pair[0]['anchor_link'])):
            cross,key = row['crossing_link'],row['anchor_link']
            if cross in chosen or key in anchors:
                decision.update(status='REJECTED',reason='Alternative of an already selected physical crossing/anchor; no additional capacity')
                if cross in chosen: decision['selected_anchor'] = chosen[cross]['anchor_link']
            else:
                chosen[cross]=row; anchors.add(key)
                decision.update(status='APPROVED_MODEL_ONLY',useful_length_m=row['useful_length_m'],budget_pcu_h=row[role+'_capacity_pcu_h'])
            decisions.append(decision)
        document[role+'_gateways'] = sorted(chosen.values(),key=lambda r:r['id'])

    # Coalesce connected service aisles/driveways (including opposite directions)
    # into a single synthetic source, avoiding multiple sources in one facility.
    service = {k for k in model.interior if inventory[k]['service'] in ('parking_aisle','driveway')}
    neighbors = defaultdict(set)
    at_node = defaultdict(list)
    for k in service:
        at_node[native[k].get('from')].append(k); at_node[native[k].get('to')].append(k)
    for group in at_node.values():
        for k in group: neighbors[k].update(group)
    components = {}
    for k in sorted(service):
        if k in components: continue
        todo=[k]; components[k]=k
        while todo:
            for nxt in neighbors[todo.pop()]:
                if nxt not in components: components[nxt]=k; todo.append(nxt)

    def egress(key):
        queue = deque([[key]]); seen={key}
        while queue:
            path = queue.popleft()
            if len(path)>1 and path[-1] not in service:
                validate_path(path)
                return path
            for nxt in base.successors[path[-1]]:
                if nxt not in seen and nxt not in unresolved_links:
                    extension=path+[nxt]
                    if not any(contains_sequence(extension,s) for s in forbidden):
                        seen.add(nxt); queue.append(extension)
        raise ValueError('No directed interior path from this service component to the street network')

    sites = {}; site_decisions=[]
    for old in sorted(document['candidate_internal_origins'], key=lambda r:(-ends[r['link_id']],r['link_id'])):
        key=old['link_id']; decision=dict(role='internal_origin',link_id=key)
        try:
            if key not in model.internal_links: raise ValueError('Gateway observation cannot be an internal activity')
            if ends[key]+1e-8 < BODY+GAP: raise ValueError('Insufficient useful queue storage')
            path=egress(key); rate,basis=capacity(path)
            component=components[key]
            decision['component']=component
            if component in sites:
                decision.update(status='REJECTED',reason='Same connected service facility; only one modeled origin/budget',selected_link=sites[component]['link_id'])
            else:
                row=dict(old,review=attestation(),flow_role='internal_incorporation',activity_allowed=True,
                         useful_length_m=ends[key],incorporation_capacity_pcu_h=rate,capacity_basis=basis,
                         facility_component=component,egress_link_ids=path,
                         activity_basis='Synthetic pre-positioned private vehicles in mapped service facility; no explicit OSM denial; not property permission or observed parking availability',
                         eligibility_assumptions=['Existing native width/lanes accepted as model assumptions, not surveyed clearance',
                            'Available first queue can hold a 4.5 m car or 2.1 m motorcycle plus 0.10 m gap',
                            'One source per connected service facility; native physical admission remains authoritative'],
                         storage_basis=dict(native_first_queue_m=ends[key],body_m=BODY,gap_m=GAP,
                             whole_private_slots_per_lane=math.floor(ends[key]/(BODY+GAP))),
                         source_evidence=[dict(link_id=k,osm_way=native[k].get('origid'),osm_tags=tags[native[k].get('origid')]) for k in path])
                model._incorporation(row,key); sites[component]=row
                decision.update(status='APPROVED_MODEL_ONLY',budget_pcu_h=rate,useful_length_m=ends[key])
        except ValueError as exc:
            decision.update(status='REJECTED',reason=str(exc))
        site_decisions.append(decision)
    document['internal_origins']=sorted(sites.values(),key=lambda r:r['link_id'])
    document.update(review=attestation(),lanes_sha256=digest(target),
        status='BLOCKED',reason=turn_blocker,budget_contract='boundary-source-sink-and-internal-incorporation-v2',
        effective_scenario='access-review-v2/config-simz1.xml',
        evidence='access-review.json + osm-turn-resolution.json; original candidates preserved in source/access-candidates-v1.json',
        model_assumptions=dict(empirical_calibration=False,observed_flow_available=False,property_permissions_available=False,
            approval_scope='Individual geometry/direction/storage and explicit synthetic eligibility; not whole-network OSM or 180K acceptance',
            boundary='Incoming/outgoing modeled traffic conditions, not parking generation',
            exits='Budget applies to departure cohort hour; actual exit hour cannot be inferred before QSim',
            internal='Synthetic available vehicles; public/property authorization is not asserted',
            capacity='Existing modeled bottlenecks, never observed counts; no physical QSim capacity modified'))
    for key in ('candidate_entry_gateways','candidate_exit_gateways','candidate_internal_origins'):
        document.pop(key,None)
    graph=BalancedGatewayModel(base,document,ends,moves)
    usable_entries=set().union(*(set(graph.origins(kind,body))
        for kind in ('external-external','external-internal') for body in (4.5,2.1)))
    usable_exits=set()
    for kind in ('external-external','internal-external'):
        for body in (4.5,2.1):
            for origin in graph.origins(kind,body):
                usable_exits.update(graph.candidates(origin,kind,body))
    for role,usable in (('entry',usable_entries),('exit',usable_exits)):
        unused_crossings={r['crossing_link'] for r in document[role+'_gateways'] if r['anchor_link'] not in usable}
        for decision in decisions:
            if decision['role']==role and decision['status']=='APPROVED_MODEL_ONLY' and decision['anchor_link'] not in usable:
                decision.update(status='REJECTED',reason='Local chain exists but no whole-body connected OD pair from/to the modeled interior')
            elif decision['role']==role and decision.get('selected_anchor') and decision['crossing_link'] in unused_crossings:
                decision.update(reason='Alternative of a crossing with no whole-body connected OD pair; no additional capacity')
                decision.pop('selected_anchor')
        document[role+'_gateways']=[r for r in document[role+'_gateways'] if r['anchor_link'] in usable]
    graph=BalancedGatewayModel(base,document,ends,moves)
    save(OUT/'access.json',document)
    class_eligibility=[]
    for kind in ('external-external','external-internal','internal-external','internal-internal'):
        for body in (4.5,2.1):
            origins=graph.origins(kind,body)
            class_eligibility.append(dict(od_type=kind,body_m=body,eligible_origin_links=list(origins),
                destination_counts={k:len(graph.candidates(k,kind,body)) for k in origins},
                scope='Directed lane reachability and whole body only; global OSM guard remains BLOCKED'))
    pair_audit=[]
    for entry in document['entry_gateways']:
        for leave in document['exit_gateways']:
            a,b=entry['anchor_link'],leave['anchor_link']
            try:
                if b not in graph.candidates(a,'external-external',BODY):
                    raise ValueError('No whole-body eligible directed through pair')
                path=graph.route(a,b); validate_path(path)
                pair_audit.append(dict(entry=a,exit=b,status='static_shortest_path_admissible',links=len(path)))
            except ValueError as exc:
                pair_audit.append(dict(entry=a,exit=b,status='REJECTED',reason=str(exc)))
    # Pure quota/probability arithmetic (24 bins), NOT 178200 scheduled requests.
    catalog=json.loads((SOURCE/'agent-types-balanced-v1.json').read_bytes())
    weights=catalog['temporal_demand']['hourly_weights']; total=sum(weights)
    hourly=[dict(hour=h,probability=w/total,expected_private_vehicles=178200*w/total,
                expected_private_pcu=(79200+99000*.25)*w/total,
                expected_entry_pcu=.7*(79200+99000*.25)*w/total,
                expected_exit_cohort_pcu=.7*(79200+99000*.25)*w/total,
                expected_internal_origin_pcu=.3*(79200+99000*.25)*w/total) for h,w in enumerate(weights)]
    totals={role:sum(r[role+'_capacity_pcu_h'] for r in document[role+'_gateways']) for role in ('entry','exit')}
    totals['internal_origin']=sum(r['incorporation_capacity_pcu_h'] for r in document['internal_origins'])
    audit=dict(version=VERSION,status='BLOCKED',reason=turn_blocker,
        source_evidence_hashes={n:digest(OUT/n) for n in ('geography-review.json','network-access-inventory.csv','osm-turn-evidence.json','perimeter.geojson')},
        access_sha256=digest(OUT/'access.json'),effective_hashes=after['summary']['hashes'],
        preserved_freight_route_checks=freight_checks,
        preserved_transit_route_checks=transit_checks,
        class_eligibility=class_eligibility,
        copied_freight_changes=['routes.json: lanes_sha256 only','service-composition-v3.json: relative osm_file only'],
        decisions=sorted(decisions,key=lambda r:(r['role'],r['id'],r['anchor_link'])),
        internal_origin_decisions=sorted(site_decisions,key=lambda r:r['link_id']),
        original_blocked_crossings=geography['blocked_crossings'],entry_exit_pairs=pair_audit,
        fixed_experiment=dict(N=180000,cars=79200,motorcycles=99000,compact_freight=1800,buses_additional=269,
            private=178200,seed=20261023,iteration=0,OD_percent=dict(EE=50,EI=20,IE=20,II=10),
            OD_counts=dict(EE=89100,EI=35640,IE=35640,II=17820)),
        budget_totals_pcu_h=totals,hourly_expectations=hourly,
        hourly_expectation_basis='Analytical probabilities only; not seeded scheduled requests. Aggregate sums are ceilings and shared links remain common constraints.',
        scheduled_requests_per_gateway_hour=None,insufficient_scheduled_budgets=None,
        scheduled_exit_concentration=None,
        schedule_status='NOT_GENERATED: unresolved OSM restrictions; massive DryRun/population prohibited by user',
        observed_dependencies=dict(flow_counts=None,merge_rates=None,property_permissions=None,surveyed_storage=None),
        observed_dependencies_scope='Not prerequisites for explicitly synthetic eligibility; cannot claim field calibration or actual insertion/discharge',
        production_model_available=False,simulation_started=False)
    save(OUT/'access-review.json',audit)
    with (OUT/'gateway-hour-budgets.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['role','gateway_id','anchor_link','hour','model_budget_pcu_h','scheduled_requests','scheduled_pcu','status'])
        writer.writeheader()
        for role in ('entry','exit'):
            for row in document[role+'_gateways']:
                for hour in range(24):
                    writer.writerow(dict(role=role,gateway_id=row['id'],anchor_link=row['anchor_link'],hour=hour,
                        model_budget_pcu_h=row[role+'_capacity_pcu_h'],scheduled_requests='',scheduled_pcu='',status='NOT_SCHEDULED_OSM_BLOCKED'))
        for row in document['internal_origins']:
            for hour in range(24):
                writer.writerow(dict(role='internal_origin',gateway_id=row['facility_component'],anchor_link=row['link_id'],hour=hour,
                    model_budget_pcu_h=row['incorporation_capacity_pcu_h'],scheduled_requests='',scheduled_pcu='',status='NOT_SCHEDULED_OSM_BLOCKED'))
    print(json.dumps(dict(status='BLOCKED',approved={k:len(document[k]) for k in ('entry_gateways','exit_gateways','internal_origins')},
        corrected_relations=len(changes),removed_terminal_targets=sum(r['removed_targets'] for r in changes),
        pair_statuses=dict(Counter(r['status'] for r in pair_audit)),budgets=totals,reason=turn_blocker),indent=2))


if __name__=='__main__':
    main()
