"""Weekday fixed-fleet scenario. B is independent of road demand N.

This is an explicitly assumed operational scenario, not an operator-certified
schedule. Directed routes and stop provenance are supplied in a fingerprinted
route bundle. Exterior travel is an off-network timed activity; no imaginary
road connects gateways. Historical scenarios are never edited.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_transit_fleet import attributes, vehicles_xml, xml_bytes

SCHEMA = 'simz1-weekday-transit-v2'
ROUTES_SCHEMA = 'simz1-transit-route-bundle-v2'
HISTORICAL_DEFAULT = Path(__file__).resolve().parents[1]/'scenarios/zona1/transit/weekday-v2/service.json'
DEFAULT = HISTORICAL_DEFAULT.with_name('service-fleet-176-93-v1.json')

# Keep the six-decimal timetable precision, but never accumulate float duties.
TIMETABLE_UNITS_PER_SECOND = 1_000_000
TIMETABLE_TIME_BASIS = 'integer_microseconds_v1'
# Same EPS as SimZ1TransitFleet.java; this is NOT a relaxed overlap tolerance.
NATIVE_DUTY_EPS = 1e-7


def require(ok, message):
    if not ok:
        raise ValueError('TRANSIT_WEEKDAY: ' + message)


def digest(path):
    """Compute the same SHA-256 on Python 3.10+ without loading the file into RAM."""
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def text_fingerprint(path, expected, label):
    """Validate fingerprint, allowing *only* LF vs CRLF checkout conversion.

    Git on Windows may checkout a fingerprinted XML/OSM/JSON text source
    with CRLF even though the bundle was made from the LF version.
    Accept the original digest or the digest after replacing CRLF with LF.
    Other byte changes (including changes to nodes, routes, coordinates,
    or stray carriage returns) still fail closed. Run artifacts continue
    using digest() with their actual, unmodified bytes.
    """
    if digest(path) == expected:
        return 'exact'
    normalized = hashlib.sha256()
    # Binary iteration yields complete newline-terminated records and avoids
    # loading an OSM/network master into memory or splitting CRLF across chunks.
    with Path(path).open('rb') as stream:
        for line in stream:
            normalized.update(line.replace(b'\r\n', b'\n'))
    require(normalized.hexdigest() == expected,
            label + ' fingerprint differs beyond LF/CRLF conversion; review source before running')
    return 'crlf_to_lf'


def read_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate JSON key: ' + k)
            result[k] = v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON: '+x)))


def seconds(value):
    require(isinstance(value, str) and len(value.split(':')) == 2, 'time must be HH:MM')
    h, m = map(int, value.split(':'))
    require(0 <= h <= 24 and 0 <= m < 60 and (h != 24 or m == 0), 'invalid time: '+value)
    return h*3600 + m*60


def finite(value, label, minimum=0, positive=False):
    require(type(value) in (int, float) and math.isfinite(value) and
            (value > minimum if positive else value >= minimum), 'invalid '+label)
    return value


def _timetable_units(value, label, *, round_up=False):
    """Convert an input once; ceil minimum transfers so they are never shortened."""
    finite(value, label)
    scaled = Decimal(str(value)) * TIMETABLE_UNITS_PER_SECOND
    rounding = ROUND_CEILING if round_up else ROUND_HALF_EVEN
    return int(scaled.to_integral_value(rounding=rounding))


def _timetable_seconds(units):
    return units / TIMETABLE_UNITS_PER_SECOND


def validate_serialized_timetable(data):
    """Check the actual XML values with the existing Java duty constraints.

    No XML rewriting, timestamp repair or tolerance enlargement is performed.
    This is a schedule check, not a substitute for native QSim validation.
    """
    root = ET.fromstring(data)
    def metadata(element):
        return {a.get('name'): a.text for a in element.findall('./attributes/attribute')}
    def number(value, label):
        return finite(float(value), label)
    by_vehicle = {}
    seen = set()
    for line in root.findall('transitLine'):
        lm = metadata(line)
        opens = number(lm['simz1:opensSeconds'], 'opening time')
        closes = number(lm['simz1:closesSeconds'], 'closing time')
        cutoff = number(lm.get('simz1:departureCutoffSeconds', closes), 'departure cutoff')
        for route in line.findall('transitRoute'):
            stops = route.findall('./routeProfile/stop')
            require(stops, 'missing serialized route stops: ' + route.get('id', '?'))
            offset = number(stops[-1].get('departureOffset'), 'final departureOffset')
            for departure in route.findall('./departures/departure'):
                dep_id, bus = departure.get('id'), departure.get('vehicleRefId')
                require(dep_id and bus and dep_id not in seen, 'missing/duplicate serialized departure identity')
                seen.add(dep_id)
                dm = metadata(departure)
                start = number(departure.get('departureTime'), 'departure time')
                end = number(dm['simz1:endTimeSeconds'], 'end time')
                terminal = number(dm['simz1:terminalSeconds'], 'terminal time')
                transfer = number(dm['simz1:turnaroundSeconds'], 'return time')
                require(opens <= cutoff <= closes and start >= opens and start < cutoff and end <= closes + NATIVE_DUTY_EPS,
                        'serialized departure outside operating window: ' + dep_id)
                require(abs(end - start - offset) <= NATIVE_DUTY_EPS,
                        'serialized endTimeSeconds must equal departure + final departureOffset: ' + dep_id)
                ready = number(end + terminal + transfer, 'ready time')
                by_vehicle.setdefault(bus, []).append((start, ready, dep_id))
    require(seen, 'no serialized departures')
    for bus, duties in sorted(by_vehicle.items()):
        duties.sort(key=lambda row: row[0])
        for previous, following in zip(duties, duties[1:]):
            require(following[0] + NATIVE_DUTY_EPS >= previous[1],
                    'overlapping duty or insufficient terminal/return time: '
                    f'{bus}; previous={previous[2]}; next={following[2]}; '
                    f'next_start={following[0]:.12f}; ready_at={previous[1]:.12f}; '
                    f'deficit_seconds={previous[1] - following[0]:.12g}')
    return dict(status='serialized_timetable_pass', checked_departures=len(seen),
                checked_vehicles=len(by_vehicle), native_tolerance_seconds=NATIVE_DUTY_EPS)


def load_policy(path=DEFAULT, service_date=None, accept_route_assumptions=False):
    path = Path(path).resolve(strict=True)
    p = read_json(path)
    require(p.get('schema_version') == SCHEMA, 'unsupported service schema')
    require(accept_route_assumptions or not p.get('route_assumptions_require_explicit_cli_acceptance', True),
            'review service.json assumptions, then explicitly pass --accept-transit-route-assumptions; no silent fallback without buses')
    require(p.get('scenario_assumptions_acknowledged') is True,
            'fleet sizes, dwell, exterior times and timetable assumptions must be acknowledged')
    day = date.fromisoformat(service_date or p['service_date'])
    require(day.weekday() < 5, 'this scenario represents Monday-Friday, not a weekend/holiday calendar')
    require(p.get('passengers_modeled') is False, 'passengers are not modeled by the fixed fleet')
    require(p.get('closing_policy') == 'no_new_departures_finish_active', 'unsupported service closing policy')
    require(p.get('outside_policy') == 'timed_off_network_v2', 'outside travel must be explicit')
    require(p.get('domain_scope') == 'computational_network', 'not an approved administrative boundary')
    finite(p['dwell_seconds'], 'dwell_seconds')
    require(p.get('stop_occupancy_policy', 'legacy_explicit') in ('legacy_explicit', 'blocking_queue_v1'),
            'unsupported stop occupancy policy')
    require(p.get('stop_placement_policy', 'legacy_endpoint_proxy') in ('legacy_endpoint_proxy', 'body_before_conflict_proxy_v1'),
            'unsupported stop placement policy')
    from simz1_stop_proxy import QUEUE_POLICY, LEGACY_QUEUE_POLICY, POLICY as STOP_POLICY
    require(p.get('stop_queue_policy', LEGACY_QUEUE_POLICY) in (LEGACY_QUEUE_POLICY, QUEUE_POLICY),
            'unsupported native stop queue policy')
    require(p.get('stop_queue_policy') != QUEUE_POLICY or p.get('stop_placement_policy') == STOP_POLICY,
            'native stop queue adjustment requires explicit body-safe stop policy')
    seen = set(); fleet = Counter()
    for s in p['services']:
        ident = s['service_id']
        require(isinstance(ident, str) and ident and ident not in seen, 'duplicate/invalid service')
        seen.add(ident)
        require(s['system'] in ('transmetro', 'tubus'), 'unsupported operator system')
        require(type(s['buses']) is int and s['buses'] > 0, 'each included service must have a fixed fleet')
        require(0 <= seconds(s['opens']) < seconds(s['closes']) <= 86400, 'invalid operating window')
        require(s.get('hours_basis') and s.get('allocation_basis'), 'timetable/allocation provenance required')
        fleet[s['system']] += s['buses']
    require(dict(fleet) == p['fleet_counts'], 'per-service allocations do not sum to fixed fleet_counts')
    require(all(type(n) is int and n > 0 for n in fleet.values()), 'empty fleet')
    types = {t['type_id']: t for t in p['vehicle_types']}
    require(len(types) == len(p['vehicle_types']), 'duplicate vehicle type')
    for t in types.values():
        for key in ('length_m', 'width_m', 'pcu', 'max_speed_mps'):
            finite(t[key], key, positive=True)
        require(t['body_model'] == 'rigid', 'this version uses a rigid bus envelope, not an articulated simulation')
    require(all(s['vehicle_type'] in types for s in p['services']), 'unknown bus type')
    p = deepcopy(p); p['service_date'] = day.isoformat(); p['route_assumptions_accepted'] = bool(accept_route_assumptions)
    return p, path


def load_routes(policy, policy_path, base_network):
    bundle_path = (policy_path.parent/policy['routes_file']).resolve(strict=True)
    b = read_json(bundle_path)
    require(b.get('schema_version') == ROUTES_SCHEMA, 'unsupported route bundle')
    text_fingerprint(base_network, b.get('network_sha256'), 'base network')
    require(b.get('route_geometry_is_empirically_calibrated') is False, 'do not label source map-matching as calibration')
    # Source fingerprints make a cached bundle reproducible, rather than accepting
    # stale routes merely because a JSON file exists.
    for source in b.get('sources', []):
        local = (policy_path.parent/source['path']).resolve(strict=True)
        text_fingerprint(local, source['sha256'], 'route source '+source['path'])
    services = {s['service_id']: s for s in b['services']}
    require(len(services) == len(b['services']), 'duplicate bundled service')
    for s in policy['services']:
        require(s['service_id'] in services, 'no directed route for '+s['service_id'])
        route = services[s['service_id']]
        require(route.get('parts') and route.get('sources') and route.get('mapping_basis'), 'route evidence missing')
        require(not route.get('blockers'), 'unresolved route mapping: '+s['service_id']+' '+str(route.get('blockers')))
    return b, bundle_path


def prepared_network(base_network, bundle):
    """Add bus access only on explicitly mapped paths; preserve every car attribute."""
    root = ET.parse(base_network).getroot()
    nodes = {n.get('id'): n for n in root.findall('./nodes/node')}
    links = {l.get('id'): l for l in root.findall('./links/link')}
    for n in bundle.get('additional_nodes', []):
        ident = n['id']
        if ident in nodes:
            require(all(abs(float(nodes[ident].get(a))-float(n[a])) < 1e-5 for a in ('x','y')), 'node conflict '+ident)
        else:
            row = ET.SubElement(root.find('nodes'), 'node', {k: str(v) for k,v in n.items() if k in ('id','x','y')})
            nodes[ident] = row
    for l in bundle.get('additional_links', []):
        ident = l['id']
        require(ident not in links and l['modes'] == 'bus', 'bus-only extension ID/modes conflict')
        require(l.get('source_way_id') and l.get('access_basis'), 'bus-only extension without OSM provenance')
        row = ET.SubElement(root.find('links'), 'link', {k:str(v) for k,v in l.items()
            if k in ('id','from','to','length','freespeed','capacity','permlanes','modes','origid')})
        attributes(row, {'osm:origid':l['source_way_id'], 'simz1:transitAccessBasis':l['access_basis'],
            'simz1:transitSourceExtension':'true', 'osm:name':l.get('name',''),
            'simz1:physicalParameterBasis':'explicit_bus_network_assumption_not_observed_capacity'})
        links[ident] = row
    for s in bundle['services']:
        for part in s['parts']:
            path = part['link_ids']
            require(len(path) >= 2 and all(x in links for x in path), 'missing/too short directed route')
            require(all(links[a].get('to') == links[z].get('from') for a,z in zip(path,path[1:])),
                    'disconnected native route '+part['part_id'])
            require(part.get('direction_basis') and part.get('transfer_after'), 'direction/transfer provenance missing')
            transfer = part['transfer_after']
            require(transfer['kind'] in ('exterior','terminal'), 'unmodeled transfer')
            finite(transfer['minimum_seconds'], 'transfer time', positive=True)
            require(transfer.get('basis'), 'exterior travel needs a declared assumption/source')
            for ident in path:
                row = links[ident]
                require(row.get('from') in nodes and row.get('to') in nodes, 'missing node')
                modes = set(row.get('modes','car').split(',')); modes.add('bus')
                row.set('modes', ','.join(sorted(modes)))
    return root


def stop_proxy_lanes(config, base_directory):
    enabled=config.find("module[@name='qsim']/param[@name='useLanes']")
    if enabled is None or enabled.get('value') != 'true': return {}
    lane=config.find("module[@name='network']/param[@name='laneDefinitionsFile']")
    require(lane is not None and lane.get('value') not in (None,'','null'), 'native stop proxy needs configured lane definitions')
    from simz1_lane_validation import read_lanes
    return read_lanes(Path(base_directory)/lane.get('value'))


def build_plan(policy, bundle, network_root, road_persons, lane_assignments=None):
    require(type(road_persons) is int and road_persons >= 0, 'Private N must be nonnegative and excludes buses')
    nodes = {n.get('id'):n for n in network_root.findall('./nodes/node')}
    links = {l.get('id'):l for l in network_root.findall('./links/link')}
    templates = {s['service_id']:s for s in bundle['services']}
    types = {t['type_id']:t for t in policy['vehicle_types']}
    fleet, roster, services, stops = [], [], [], {}
    from simz1_stop_proxy import StopGeometry, POLICY as STOP_PROXY_POLICY, QUEUE_POLICY, summary as stop_proxy_summary
    proxy_enabled = policy.get('stop_placement_policy') == STOP_PROXY_POLICY
    stop_geometry = StopGeometry(links, nodes, lane_assignments) if proxy_enabled else None
    for service in policy['services']:
        template = templates[service['service_id']]
        opening, closing = seconds(service['opens']), seconds(service['closes'])
        kind = types[service['vehicle_type']]
        visits_by_part, durations = {}, []
        for part in template['parts']:
            path = part['link_ids']
            stop_records = (stop_geometry.place(path, part.get('stops', []), kind['length_m'],
                            preserve_source_stops=policy.get('stop_queue_policy') == QUEUE_POLICY)
                            if proxy_enabled else part.get('stops', []))
            stop_at = {v['link_index']:dict(v) for v in stop_records}
            # Native driver needs explicit endpoint facilities. They are not
            # passenger stops and are never added to the visible bus-stop layer.
            for idx, side in ((0, 'entry'), (len(path)-1, 'exit')):
                stop_at.setdefault(idx, dict(stop_id=part['part_id']+'_'+side, link_index=idx,
                                             role='gateway', name=side))
            elapsed=0.0; visits=[]
            for i, ident in enumerate(path):
                l=links[ident]
                if i:
                    elapsed += float(l.get('length'))/min(float(l.get('freespeed')), kind['max_speed_mps'])
                if i not in stop_at: continue
                item=stop_at[i]; sid=item['stop_id']+'_'+part['part_id']
                dwell=0.0 if item.get('role')=='gateway' else float(policy['dwell_seconds'])
                end_node=nodes[l.get('to')]
                # With QSim lanes a native in-lane stop can block an aggregate
                # queue. Do not claim lane-specific bay geometry without data.
                aggregate_blocking=policy.get('stop_occupancy_policy') == 'blocking_queue_v1'
                blocking=(item.get('role','passenger_stop') != 'gateway') if aggregate_blocking else item.get('blocking_lane',False)
                require(not blocking or float(l.get('permlanes'))==1 or aggregate_blocking,
                        'unsupported multi-lane blocking stop')
                stops[sid]=dict(stop_id=sid, link_id=ident, x=float(end_node.get('x')),y=float(end_node.get('y')),
                    source_position=item.get('source_position'), name=item.get('name',sid),
                    role=item.get('role','passenger_stop'), blocking_lane=blocking,
                    occupancy_basis='scenario_blocking_native_queue_not_microscopic_lane' if aggregate_blocking else 'legacy_explicit',
                    placement_basis=item.get('placement_basis','native_link_endpoint_proxy'),
                    system=service['system'], line=service['line'], direction=part['part_id'],
                    service_id=service['service_id'], source=item.get('source',template['sources'][0]),
                    dwell_seconds=dwell)
                if item.get('proxy_placement'):
                    proxy = item['proxy_placement']; stops[sid]['proxy_placement'] = proxy
                    stops[sid]['x'], stops[sid]['y'] = proxy['modeled_front_position_xy']
                visits.append(dict(stop_id=sid, link_index=i, arrival_offset_s=round(elapsed,6),
                                   departure_offset_s=round(elapsed+dwell,6)))
                elapsed += dwell
            require(all(path[a['link_index']] != path[b['link_index']] for a,b in zip(visits,visits[1:])), 'consecutive stops on same native link are ambiguous')
            require(visits[0]['link_index']==0 and visits[-1]['link_index']==len(path)-1, 'unanchored route')
            visits_by_part[part['part_id']]=visits
            # Runtime durations may exceed this free-flow+dwell planning time.
            durations.append(visits[-1]['departure_offset_s'])
        # Route offsets are already serialized to six decimals. Use that SAME
        # duration in every later departure/end/ready calculation.
        duration_units = [_timetable_units(d, 'route duration') for d in durations]
        transfer_units = [_timetable_units(part['transfer_after']['minimum_seconds'],
                                          'minimum transfer', round_up=True)
                          for part in template['parts']]
        period_units = sum(d + r for d, r in zip(duration_units, transfer_units))
        require(period_units > 0, 'empty service cycle')
        opening_units = opening * TIMETABLE_UNITS_PER_SECOND
        closing_units = closing * TIMETABLE_UNITS_PER_SECOND
        initial_units = _timetable_units(template.get('initial_exterior_seconds', 0),
                                         'initial exterior time', round_up=True)
        ids=[]; routes=[]
        for part in template['parts']:
            routes.append(dict(route_id=part['part_id'], direction=part['part_id'], link_ids=part['link_ids'],
                stops=visits_by_part[part['part_id']], departures=[], direction_basis=part['direction_basis'],
                sources=template['sources'], running_way=part.get('running_way','mixed'),
                transfer_after=part['transfer_after']))
        for v in range(service['buses']):
            vid=f"ptbus_{service['service_id']}_{v+1:03d}"
            ids.append(vid);fleet.append(dict(vehicle_id=vid,type_id=service['vehicle_type']))
            # Same B/IDs/phases for N=1 and N=250000. No road-demand RNG is consumed.
            # Ceiling the fractional initial phase delays it by less than one
            # microsecond. Subsequent duties never accumulate float round-off.
            phase_units = (v * period_units + service['buses'] - 1) // service['buses']
            time_units = opening_units + phase_units + initial_units
            count=0
            while time_units < closing_units:
                for i,route in enumerate(routes):
                    end_units = time_units + duration_units[i]
                    if end_units > closing_units: break
                    depid=f"{vid}_d{count+1:04d}"
                    dep=dict(departure_id=depid,vehicle_id=vid,time_s=_timetable_seconds(time_units))
                    route['departures'].append(dep)
                    roster.append(dict(vehicle_id=vid,departure_id=depid,service_id=service['service_id'],
                        route_id=route['route_id'],departure_time_s=dep['time_s'],
                        end_time_s=_timetable_seconds(end_units),
                        transfer_after_seconds=route['transfer_after']['minimum_seconds'],
                        transfer_kind=route['transfer_after']['kind'],closes_s=closing))
                    time_units = end_units + transfer_units[i]
                    count += 1
                else: continue
                break
            require(count>0, f'bus has no feasible service inside operating hours: {vid}')
        services.append(dict(**service,vehicle_ids=ids,routes=routes,opens_s=opening,closes_s=closing))
    require(len(fleet)==sum(policy['fleet_counts'].values()), 'fleet total changed')
    return dict(schema_version=SCHEMA,scenario_version=policy['scenario_version'],
        timetable_time_basis=TIMETABLE_TIME_BASIS,
        service_date=policy['service_date'],monte_carlo_persons=road_persons,vehicles=fleet,
        vehicle_types=policy['vehicle_types'],services=services,stops=list(stops.values()),
        roster=sorted(roster,key=lambda x:(x['vehicle_id'],x['departure_time_s'])),
        domain_links=sorted(links),fleet_counts=policy['fleet_counts'],
        stop_proxy_summary=stop_proxy_summary(stops.values(), proxy_enabled),
        assumptions=policy['assumptions'],hours_policy=policy['closing_policy'])


def plan_with_service_queues(policy, bundle, network_root, road_persons, config, base_directory):
    """Prepare an isolated native lane tree; no edits to the imported base map."""
    from simz1_stop_proxy import QUEUE_POLICY, LEGACY_QUEUE_POLICY, adjust_service_queues, lane_assignments
    lane_param=config.find("module[@name='network']/param[@name='laneDefinitionsFile']")
    lane_path=(Path(base_directory)/lane_param.get('value')).resolve(strict=True) if (
        lane_param is not None and lane_param.get('value') not in (None,'','null')) else None
    lane_root=ET.parse(lane_path).getroot() if lane_path else None
    enabled=config.find("module[@name='qsim']/param[@name='useLanes']")
    uses_lanes=enabled is not None and enabled.get('value') == 'true'
    summary=dict(enabled=False,policy=LEGACY_QUEUE_POLICY)
    if policy.get('stop_queue_policy') != QUEUE_POLICY or not uses_lanes:
        plan=build_plan(policy,bundle,network_root,road_persons,lane_assignments(lane_root) if uses_lanes and lane_root is not None else {})
    else:
        require(lane_root is not None,'native stop queue adjustment needs configured lanes')
        provisional=build_plan(policy,bundle,network_root,road_persons,{})
        summary=adjust_service_queues(lane_root,network_root,provisional['stops'])
        summary.update(source_lanes_sha256=digest(lane_path),generated_lanes_file='lanes.xml')
        plan=build_plan(policy,bundle,network_root,road_persons,lane_assignments(lane_root))
        require({s['stop_id']:s['link_id'] for s in provisional['stops']} ==
                {s['stop_id']:s['link_id'] for s in plan['stops']}, 'native queue refinement changed selected stop links')
    plan['stop_queue_summary']=summary
    return plan,lane_root


def schedule(plan, policy_sha256):
    root=ET.Element('transitSchedule')
    attributes(root, {'simz1:fleetSchema':'fixed-fleet-v1','simz1:purpose':'weekday_scenario_v2',
        'simz1:scenarioVersion':plan['scenario_version'],'simz1:serviceDate':plan['service_date'],
        'simz1:passengersModeled':False,'simz1:minimumTurnPolicy':'delay_until_ready_v2',
        'simz1:domainLinks':' '.join(plan['domain_links']),'simz1:domainApproved':False,
        'simz1:domainSynthetic':False,'simz1:domainSource':'fingerprinted computational network, not administrative Zona 1',
        'simz1:monteCarloPersons':plan['monte_carlo_persons'],'simz1:configuredFleetSize':len(plan['vehicles']),
        'simz1:scheduledExpeditions':len(plan['roster']),
        'simz1:timetableTimeBasis':TIMETABLE_TIME_BASIS, 'simz1:weekdayPolicyFile':'weekday-policy.json',
        'simz1:weekdayPolicySha256':policy_sha256})
    facilities=ET.SubElement(root,'transitStops')
    for s in plan['stops']:
        row=ET.SubElement(facilities,'stopFacility',{'id':s['stop_id'],'x':str(s['x']),'y':str(s['y']),
            'linkRefId':s['link_id'],'isBlocking':str(s['blocking_lane']).lower(),'name':s['name']})
        attributes(row, {'simz1:stopPlacement':'in_lane' if s['blocking_lane'] else 'nonblocking_proxy',
            'simz1:stopOccupancyBasis':s['occupancy_basis'],
            'simz1:dwellBasis':'explicit_scenario_assumption','simz1:dwellSeconds':s['dwell_seconds'],
            'simz1:stopRole':s['role'],'simz1:serviceSystem':s['system'],'simz1:source':s['source'],
            'simz1:placementBasis':s['placement_basis'], 'simz1:serviceId':s['service_id'],
            'simz1:serviceLine':s['line'], 'simz1:serviceDirection':s['direction'],
            **({'simz1:sourceLongitude':s['source_position'][0],
                'simz1:sourceLatitude':s['source_position'][1]} if s['source_position'] else {}),
            **({'simz1:stopProxy':json.dumps(s['proxy_placement'],sort_keys=True,separators=(',', ':'))}
               if s.get('proxy_placement') else {}),
            **({'simz1:gatewayPositionBasis':'native_traffic_exit_no_wait' if s['name']=='exit' else 'native_traffic_entry'}
               if s['role']=='gateway' else {})})
    for s in plan['services']:
        line=ET.SubElement(root,'transitLine',{'id':s['service_id']})
        attributes(line, {'simz1:serviceId':s['service_id'],'simz1:productionEnabled':False,
            'simz1:assignedVehicleIds':' '.join(s['vehicle_ids']),'simz1:operator':s['system'],
            'simz1:serviceSystem':s['system'],'simz1:opensSeconds':s['opens_s'],
            'simz1:closesSeconds':s['closes_s'],'simz1:hoursBasis':s['hours_basis'],
            **({'simz1:departureCutoffSeconds':s['departure_cutoff_s'],
                'simz1:civilServiceDate':s['service_date']} if 'departure_cutoff_s' in s else {})})
        for route in s['routes']:
            if not route['departures']:continue
            row=ET.SubElement(line,'transitRoute',{'id':route['route_id']})
            attributes(row, {'simz1:routePolicy':'fixed-v1','simz1:runningWay':route['running_way'],
                'simz1:direction':route['direction'],'simz1:directionBasis':route['direction_basis'],
                'simz1:transferKind':route['transfer_after']['kind'],
                'simz1:transferSeconds':route['transfer_after']['minimum_seconds'],
                'simz1:transferBasis':route['transfer_after']['basis']})
            ET.SubElement(row,'transportMode').text='bus'
            profile=ET.SubElement(row,'routeProfile')
            for visit in route['stops']:
                ET.SubElement(profile,'stop',{'refId':visit['stop_id'],
                    'arrivalOffset':str(visit['arrival_offset_s']),'departureOffset':str(visit['departure_offset_s']),
                    'awaitDeparture':'false'})
            path=ET.SubElement(row,'route')
            for ident in route['link_ids']:ET.SubElement(path,'link',{'refId':ident})
            deps=ET.SubElement(row,'departures')
            for dep in route['departures']:
                node=ET.SubElement(deps,'departure',{'id':dep['departure_id'],
                    'departureTime':str(dep['time_s']),'vehicleRefId':dep['vehicle_id']})
                end_units = (_timetable_units(dep['time_s'], 'departure time') +
                             _timetable_units(route['stops'][-1]['departure_offset_s'], 'route duration'))
                attributes(node, {'simz1:endTimeSeconds':_timetable_seconds(end_units),
                    'simz1:terminalSeconds':0,'simz1:turnaroundSeconds':route['transfer_after']['minimum_seconds']})
    data = xml_bytes(root,'transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd"')
    # Validate the persisted representation, not only the pre-rounding roster.
    validate_serialized_timetable(data)
    return data


def derive_geometry(config, base_directory, policy, bundle, road_persons, temporal_policy=None):
    """The single service derivation used by attach and effective-access review.

    All mutations are confined to new XML trees; no files or fleet are attached.
    """
    network_path=Path(base_directory)/config.find("module[@name='network']/param[@name='inputNetworkFile']").get('value')
    net=prepared_network(network_path,bundle)
    plan,lane_root=plan_with_service_queues(policy,bundle,net,road_persons,config,base_directory)
    if temporal_policy is not None:
        from simz1_temporal_transit import continuous_plan
        plan=continuous_plan(plan,temporal_policy)
    if lane_root is not None:
        assignments={row.get('linkIdRef'):row for row in lane_root.findall('{*}lanesToLinkAssignment')}
        for service in bundle['services']:
            for part in service['parts']:
                for a,b in zip(part['link_ids'],part['link_ids'][1:]):
                    assignment=assignments.get(a)
                    if assignment is None:continue
                    terminal=[lane for lane in assignment.findall('{*}lane') if not lane.findall('{*}leadsTo/{*}toLane')]
                    if any(x.get('refId')==b for lane in terminal for x in lane.findall('{*}leadsTo/{*}toLink')):continue
                    # Only add a movement into a newly sourced bus-only link.
                    # Existing turn restrictions are never relaxed between road links.
                    require(any(x['id']==b for x in bundle.get('additional_links',[])),
                            'existing native lane graph forbids mapped bus movement: '+a+' -> '+b)
                    require(terminal,'no terminal lane for bus-only access')
                    for lane in terminal:
                        tag=lane.tag.replace('lane','toLink') if '}' not in lane.tag else lane.tag.split('}')[0]+'}toLink'
                        ET.SubElement(lane.find('{*}leadsTo'),tag,{'refId':b})
    return net,plan,lane_root


def attach(config, output, road_persons, policy_path=DEFAULT, service_date=None, accept_route_assumptions=False,
           temporal_policy=None):
    """Write only new per-run inputs. Returns metadata; never calls QSim."""
    output=Path(output)
    require(not output.exists(), 'output exists; never overwrite a prepared/historical fleet')
    p, pp=load_policy(policy_path,service_date,accept_route_assumptions)
    network_param=config.find("module[@name='network']/param[@name='inputNetworkFile']")
    require(network_param is not None, 'missing source network')
    network_path=Path(network_param.get('value')).resolve(strict=True)
    bundle,bundle_path=load_routes(p,pp,network_path)
    net,plan,lane_root=derive_geometry(config,network_path.parent,p,bundle,road_persons,temporal_policy)
    policy=dict(p,road_demand_persons=road_persons,configured_fleet_size=len(plan['vehicles']),
                source_bundle_sha256=digest(bundle_path),base_network_sha256=digest(network_path),
                route_bundle_file='route-bundle.json',empirical_calibration=False,
                timetable_time_basis=TIMETABLE_TIME_BASIS)
    stops_bytes=(json.dumps(plan['stops'],ensure_ascii=False,indent=2)+'\n').encode()
    if plan['stop_proxy_summary']['enabled']:
        policy.update(stop_proxy_summary=plan['stop_proxy_summary'], stop_proxy_manifest_file='stops.json',
                      stop_proxy_manifest_sha256=hashlib.sha256(stops_bytes).hexdigest())
    policy['stop_queue_summary']=plan['stop_queue_summary']
    if temporal_policy is not None:
        policy['temporal_calendar']=plan['temporal_calendar']
        policy['temporal_policy']=temporal_policy
    files={'route-bundle.json':bundle_path.read_bytes(),
           'transitVehicles.xml':vehicles_xml(plan),
           'network.xml':xml_bytes(net,'network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd"'),
           'roster.json':(json.dumps(plan['roster'],ensure_ascii=False,indent=2)+'\n').encode(),
           'stops.json':stops_bytes}
    lane_param=config.find("module[@name='network']/param[@name='laneDefinitionsFile']")
    if lane_root is not None:
        # Keep the default MATSim namespace: its SAX reader expects unprefixed
        # element names. ElementTree otherwise writes ns0:laneDefinitions.
        if lane_root.tag.startswith('{'):
            ET.register_namespace('', lane_root.tag[1:].split('}', 1)[0])
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        files['lanes.xml']=xml_bytes(lane_root)
        if policy['stop_queue_summary']['enabled']:
            policy['stop_queue_summary']['generated_lanes_sha256']=hashlib.sha256(files['lanes.xml']).hexdigest()
        lane_param.set('value',str((output/'lanes.xml').resolve()))
    pb=(json.dumps(policy,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    files['weekday-policy.json']=pb
    files['transitSchedule.xml']=schedule(plan,hashlib.sha256(pb).hexdigest())
    output.mkdir(parents=True,exist_ok=False)
    for name,data in files.items():(output/name).write_bytes(data)
    def set_param(module,name,value):
        mod=config.find(f"module[@name='{module}']")
        if mod is None:mod=ET.SubElement(config,'module',name=module)
        row=mod.find(f"param[@name='{name}']")
        if row is None:row=ET.SubElement(mod,'param',name=name)
        row.set('value',str(value))
    network_param.set('value',str((output/'network.xml').resolve()))
    for name,value in [('useTransit','true'),('usingTransitInMobsim','true'),('transitModes','pt'),
                       ('transitScheduleFile',str((output/'transitSchedule.xml').resolve())),
                       ('vehiclesFile',str((output/'transitVehicles.xml').resolve()))]:set_param('transit',name,value)
    main=config.find("module[@name='qsim']/param[@name='mainMode']")
    if main is None:main=config.find("module[@name='qsim']/param[@name='mainModes']")
    # MATSim 15 QSimConfigGroup uses mainMode (singular serialized key).
    modes=set((main.get('value') if main is not None else 'car').split(','));modes.add('bus')
    set_param('qsim','mainMode',','.join(sorted(modes)))
    summary=dict(schema_version=SCHEMA,road_demand_persons=road_persons,
        public_transport_vehicles_configured=len(plan['vehicles']),fleet_by_system=p['fleet_counts'],
        public_transport_departures_scheduled=len(plan['roster']),transit_drivers_added_to_demand=0,
        service_date=p['service_date'],empirical_calibration=False,
        stop_proxy=plan['stop_proxy_summary'],stop_proxy_manifest_sha256=hashlib.sha256(stops_bytes).hexdigest(),
        stop_queues=plan['stop_queue_summary'],
        artifacts=[dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)) for name,data in files.items()])
    if temporal_policy is not None:
        summary['temporal_calendar']=plan['temporal_calendar']
    (output/'transit-fleet-manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


def preflight(config_path, policy_path=DEFAULT, service_date=None, accept_route_assumptions=False,
              temporal_policy=None):
    root=ET.parse(config_path).getroot()
    net=root.find("module[@name='network']/param[@name='inputNetworkFile']")
    require(net is not None,'missing network input')
    network=(Path(config_path).resolve().parent/net.get('value')).resolve(strict=True)
    p,pp=load_policy(policy_path,service_date,accept_route_assumptions);b,bp=load_routes(p,pp,network)
    plan,_=plan_with_service_queues(p,b,prepared_network(network,b),1,root,Path(config_path).resolve().parent)
    if temporal_policy is not None:
        from simz1_temporal_transit import continuous_plan
        plan=continuous_plan(plan,temporal_policy)
    # B and timetable are independent of N. Serialize in memory only; checking
    # hashes/routes alone previously missed overlaps introduced by rounding.
    schedule(plan, '0' * 64)
    return dict(status='transit_preflight_pass',fleet_by_system=p['fleet_counts'],
        stop_proxy=plan['stop_proxy_summary'],
        stop_queues=plan['stop_queue_summary'],
        timetable_validation='serialized_timetable_pass',
        timetable_time_basis=TIMETABLE_TIME_BASIS,
        configured_buses=len(plan['vehicles']),scheduled_domain_passages=len(plan['roster']),
        service_date=p['service_date'],scope='computational_network; timed exterior; scenario assumptions',
        routes_sha256=digest(bp),network_sha256=digest(network),
        route_bundle_network_sha256=b['network_sha256'],
        network_fingerprint_basis=text_fingerprint(network,b['network_sha256'],'base network'))



def verify_policy_chain(schedule_path, metadata, road_persons=None):
    """Read bounded, fingerprinted per-run policy; no approval of raw source claims."""
    parent=Path(schedule_path).resolve(strict=True).parent
    def bounded(name, expected, maximum):
        relative=Path(name)
        require(not relative.is_absolute(), 'policy asset must be relative')
        path=(parent/relative).resolve(strict=True)
        require(path.is_relative_to(parent) and path.is_file(), 'policy asset outside schedule directory')
        require(path.stat().st_size <= maximum, 'policy asset too large')
        require(digest(path)==expected, 'policy asset fingerprint mismatch: '+name)
        return read_json(path)
    p=bounded(metadata['simz1:weekdayPolicyFile'], metadata['simz1:weekdayPolicySha256'], 1_000_000)
    require(p.get('schema_version')==SCHEMA and p.get('route_assumptions_accepted') is True and
            p.get('scenario_assumptions_acknowledged') is True and p.get('empirical_calibration') is False and
            p.get('passengers_modeled') is False and p.get('domain_scope')=='computational_network' and
            p.get('outside_policy')=='timed_off_network_v2' and
            p.get('closing_policy')=='no_new_departures_finish_active', 'invalid run policy contract')
    day=date.fromisoformat(p['service_date'])
    require(day.weekday()<5 and p['service_date']==metadata['simz1:serviceDate'], 'invalid weekday/date')
    if road_persons is not None:
        require(p['road_demand_persons']==road_persons, 'policy road N mismatch')
    require(str(p['configured_fleet_size'])==metadata['simz1:configuredFleetSize'], 'policy fleet B mismatch')
    bundle=bounded(p['route_bundle_file'],p['source_bundle_sha256'],8_000_000)
    require(bundle.get('schema_version')==ROUTES_SCHEMA, 'invalid run route schema')
    if p.get('stop_placement_policy') == 'body_before_conflict_proxy_v1':
        stops=bounded(p['stop_proxy_manifest_file'],p['stop_proxy_manifest_sha256'],2_000_000)
        facilities={row.get('id'):row for row in ET.parse(schedule_path).getroot().findall('./transitStops/stopFacility')}
        for row in stops:
            proxy=row.get('proxy_placement')
            if proxy is None: continue
            actual=facilities.get(row['stop_id'])
            require(actual is not None and actual.get('linkRefId') == row['link_id'] and
                    float(actual.get('x')) == row['x'] and float(actual.get('y')) == row['y'], 'stop proxy differs from pinned native schedule')
            serialized=actual.findtext("attributes/attribute[@name='simz1:stopProxy']")
            require(serialized and json.loads(serialized)==proxy, 'stop proxy provenance differs from pinned manifest')
    queues=p.get('stop_queue_summary',{})
    if queues.get('enabled'):
        from simz1_stop_proxy import QUEUE_POLICY, lane_assignments
        require(p.get('stop_queue_policy')==QUEUE_POLICY and queues.get('policy')==QUEUE_POLICY,
                'native stop queue policy mismatch')
        relative=Path(queues['generated_lanes_file']); generated=(parent/relative).resolve(strict=True)
        require(not relative.is_absolute() and generated.is_relative_to(parent) and
                digest(generated)==queues['generated_lanes_sha256'], 'native stop queue lane fingerprint mismatch')
        assignments=lane_assignments(ET.parse(generated).getroot())
        require(queues['adjusted_links']==len(queues['adjustments']), 'native stop queue count mismatch')
        for row in queues['adjustments']:
            actual=assignments[row['link_id']]
            require(sorted(actual[row['original_queue_id']]['to_lanes'])==row['terminal_queue_ids'],
                    'native stop queue graph mismatch')
            for child,start in row['new_terminal_starts_m'].items():
                require(actual[child]['start']==start, 'native stop queue endpoint mismatch')
    return p, bundle


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--service',type=Path,default=DEFAULT)
    p.add_argument('--service-date')
    p.add_argument('--accept-transit-route-assumptions',action='store_true')
    args=p.parse_args(argv)
    try:print(json.dumps(preflight(args.config,args.service,args.service_date,args.accept_transit_route_assumptions),ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as e:p.exit(2,str(e)+'\n')

if __name__=='__main__':raise SystemExit(main())
