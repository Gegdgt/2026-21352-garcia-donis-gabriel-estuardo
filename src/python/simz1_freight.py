"""Independent weekday freight service. Quantities/routes are scenario assumptions.

One vehicle/driver performs one boundary-to-boundary expedition per service day.
No exterior travel is drawn or included in travel times. Native traffic residence,
including queues after insertion, must fit one permitted interval. Compliance
findings survive terminal events and reject validation after the stream closes.
"""
from datetime import date
import json
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET

SCHEMA = 'simz1-freight-weekday-v1'
BODY_CONTRACT = 'shared-physical-visual-v1'
INDEPENDENT_BODY_CONTRACT = 'shared-physical-visual-independent-v2'
WINDOWS = [[0, 18000], [32400, 57600], [75600, 104400]]
LEGACY_WINDOWS = [[0, 18000], [32400, 57600], [75600, 86400]]
OVERNIGHT_POLICY = 'weekday_overnight_until_05_v2'
LEGACY_RESIDENCE_POLICY = 'legacy_horizon_clip_v1'
THROUGH_ROUTE_POLICY = 'principal-through-v2'
COMPACT_ROUTE_POLICY = 'verified-multilane-through-v3'


def route_version(service):
    """Keep the actor schema stable while versioning the routing contract."""
    version, policy = service.get('service_version'), service.get('route_policy')
    if version is None and policy is None:
        return {}
    if (version, policy) not in (('weekday-v2', THROUGH_ROUTE_POLICY),
                                  ('weekday-compact-v3', COMPACT_ROUTE_POLICY)):
        raise ValueError('Freight unsupported service version/route policy')
    return dict(service_version=version, route_policy=policy)


def validate_through_config(config_path, osm_path, bundle, service):
    """Check the actual graph, including isolated transit lane adjustments."""
    from simz1_run import parameters, sha256
    from simz1_freight_routes import load_context, validate_bundle
    config_path = Path(config_path).resolve()
    values = parameters(config_path)
    if values.get('qsim.useLanes') != 'true':
        raise ValueError('Freight weekday-v2 requires explicit native lanes')
    network_path = config_path.parent / values['network.inputNetworkFile']
    lanes_path = config_path.parent / values['network.laneDefinitionsFile']
    context = load_context(network_path, lanes_path, osm_path)
    report = validate_bundle(context, bundle, service)
    report['effective_input_sha256'] = dict(network=sha256(network_path), lanes=sha256(lanes_path),
                                           osm=sha256(osm_path))
    report.update(route_version(service))
    from simz1_freight_signals import audit as audit_signals
    report['signals'] = audit_signals(config_path, bundle)
    from simz1_temporal_passage import TemporalPassage, COMPATIBLE, POLICY
    temporal = TemporalPassage(config_path, config_path.parent)
    report['temporal_passages'] = dict(policy=POLICY, effective_input_sha256=temporal.hashes, routes=[])
    for route in bundle['routes']:
        status, _, reason = temporal.query(tuple(route['link_ids']), service['length_m'], service['maximum_speed_kmh']/3.6)
        report['temporal_passages']['routes'].append(dict(route=route['route_id'], status=status, reason=reason))
        if status != COMPATIBLE:
            raise ValueError('TEMPORAL_FIXED_FREIGHT_INCOMPATIBLE: '+route['route_id']+' '+status+' '+reason)
    return report


def refresh_through_validation(run):
    """Refresh evidence after optional coordination changes effective offsets."""
    from simz1_run import atomic_json
    run = Path(run)
    folder = run/'inputs/freight-weekday'
    service = json.loads((folder/'service.json').read_text(encoding='utf-8'))
    if not route_version(service):
        return
    bundle = json.loads((folder/'routes.json').read_text(encoding='utf-8'))
    report = validate_through_config(run/'config-simz1.xml', folder/service['osm_file'], bundle, service)
    atomic_json(folder/'route-validation.json', report)


def residence_contract(service):
    windows = service.get('allowed_windows_seconds')
    policy = service.get('residence_policy')
    if windows == WINDOWS and policy == OVERNIGHT_POLICY:
        return policy, WINDOWS
    if windows == LEGACY_WINDOWS and policy in (None, LEGACY_RESIDENCE_POLICY):
        return LEGACY_RESIDENCE_POLICY, LEGACY_WINDOWS
    raise ValueError('Freight: unsupported weekday service/windows/residence policy')


def presentation_dimensions(service, public_dimensions=None):
    """Resolve one saved service body, preserving the historical separate override.

    New services use the same explicit dimensions for QSim and presentation.
    A custom public service must agree with that saved body; silently replacing
    the physical size with today's bus dimensions would break its occupancy.
    """
    policy = service.get('body_contract')
    public = ({key: public_dimensions[key] for key in ('length_m', 'width_m')}
              if public_dimensions is not None else dict(length_m=12., width_m=2.5))
    if policy is None:
        return dict(**public, source='freight_visual_matches_TuBus_RigidProxy', assumed=True)
    if policy not in (BODY_CONTRACT, INDEPENDENT_BODY_CONTRACT):
        raise ValueError('Freight unsupported body_contract')
    body = {key: service.get(key) for key in ('length_m', 'width_m')}
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
           for value in body.values()):
        raise ValueError('Freight invalid shared physical/visual body')
    if policy == BODY_CONTRACT and public_dimensions is not None and any(abs(body[key]-public[key]) > 1e-9 for key in body):
        raise ValueError('Freight shared body differs from configured TuBus_RigidProxy; align the service dimensions explicitly')
    return dict(**body, source='freight_shared_physical_visual_body', assumed=True,
                provenance=(dict(body_contract=BODY_CONTRACT, reference_public_type='TuBus_RigidProxy')
                            if policy == BODY_CONTRACT else
                            dict(body_contract=INDEPENDENT_BODY_CONTRACT, reference='saved_freight_service_dimensions')))


def is_freight(person):
    return person.findtext("attributes/attribute[@name='simz1FreightService']") == SCHEMA


def permitted(start, end=None, *, windows=WINDOWS):
    end = start if end is None else end
    return (math.isfinite(start) and math.isfinite(end) and end >= start and
            any(a <= start <= end < b for a, b in windows))


def stratified_departures(number, minimum_route_seconds, windows, margin):
    """Synthetic route-balanced departures within feasible one-day windows.

    A minimum free-flow clearance check is not a promise of arrival in traffic.
    Native residence audits remain authoritative if congestion delays a truck.
    """
    if type(number) is not int or not 1 <= number <= 100000 or not minimum_route_seconds:
        raise ValueError('Invalid stratified freight quantity/routes')
    if type(margin) not in (int, float) or not math.isfinite(margin) or margin < 0:
        raise ValueError('Invalid freight clearance margin')
    if any(not math.isfinite(t) or t < 0 for t in minimum_route_seconds):
        raise ValueError('Invalid freight route free-flow duration')
    starts = [None] * number
    route_count = len(minimum_route_seconds)
    for route_index, minimum in enumerate(minimum_route_seconds):
        indices = range(route_index, number, route_count)
        n = len(indices)
        if not n:
            continue
        # Endpoints are exclusive. The midpoint never lands on the closing time.
        intervals = [(float(a), min(86400., float(b))-minimum-margin) for a, b in windows
                     if float(a) < min(86400., float(b))-minimum-margin]
        width = math.fsum(b-a for a, b in intervals)
        if not width:
            raise ValueError('Freight route cannot fit any allowed window with clearance margin')
        for rank, index in enumerate(indices):
            distance = (rank + .5) * width / n
            for start, end in intervals:
                if distance < end-start:
                    starts[index] = start + distance
                    break
                distance -= end-start
            if starts[index] is None:
                raise ValueError('Freight departure allocation exceeded its feasible intervals')
    return starts


def check_base_network_fingerprint(path, expected):
    """Allow only Git LF/CRLF differences in the source network fingerprint.

    The supplied route bundle was made from a CRLF checkout; exported ZIP sources
    use LF. This check does not change the map, bundle or per-run raw byte hashes.
    Actual graph/content changes still reject the bundle.
    """
    raw, lf, crlf = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    with Path(path).open('rb') as stream:
        for line in stream:
            raw.update(line)
            normalized = line.replace(b'\r\n', b'\n')
            lf.update(normalized)
            crlf.update(normalized.replace(b'\n', b'\r\n'))
    if raw.hexdigest() == expected:
        return 'exact'
    if expected in (lf.hexdigest(), crlf.hexdigest()):
        return 'lf_crlf_source_equivalence_only'
    raise ValueError('Freight route bundle does not match base network beyond LF/CRLF checkout conversion')


def prepare(config_path, service_path, service_date=None, vehicles=None):
    from simz1_run import parameters, sha256
    from simz1_event_validation import enabled_lane_movements
    config_path, service_path = Path(config_path).resolve(), Path(service_path).resolve()
    service = json.loads(service_path.read_text(encoding='utf-8'))
    if service.get('schema_version') != SCHEMA:
        raise ValueError('Freight: unsupported weekday service/windows')
    version = route_version(service)
    residence_policy, windows = residence_contract(service)
    service['residence_policy'] = residence_policy
    service['service_date'] = service_date or service['service_date']
    if date.fromisoformat(service['service_date']).weekday() >= 5:
        raise ValueError('Freight requires a Monday-Friday date')
    if vehicles is not None:
        service['vehicles'] = vehicles
    n = service['vehicles']
    if type(n) is not int or not 1 <= n <= 100000:
        raise ValueError('Freight vehicles must be an integer in 1..100000; disable explicitly')
    for key in ('gross_weight_tonnes', 'pcu', 'maximum_speed_kmh', 'length_m', 'width_m'):
        v = service.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
            raise ValueError('Freight invalid '+key)
    if service['gross_weight_tonnes'] <= 3.5 or service.get('empirical_calibration') is not False:
        raise ValueError('Freight requires PBV > 3.5 t and explicit non-calibration')
    presentation_dimensions(service)
    values = parameters(config_path)
    network_path = (config_path.parent / values['network.inputNetworkFile']).resolve()
    net = ET.parse(network_path).getroot()
    links = {r.get('id'): r for r in net.findall('./links/link')}
    lanes = enabled_lane_movements(config_path.parent / values['network.laneDefinitionsFile']) if values.get('qsim.useLanes') == 'true' else {}
    bundle_path = service_path.parent / service['routes_file']
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    service['network_fingerprint_basis'] = check_base_network_fingerprint(network_path, bundle.get('base_network_sha256'))
    if version:
        osm_path = (service_path.parent / service['osm_file']).resolve()
        check_base_network_fingerprint(osm_path, bundle.get('osm_sha256'))
        check_base_network_fingerprint(config_path.parent / values['network.laneDefinitionsFile'],
                                       bundle.get('lanes_sha256'))
        validate_through_config(config_path, osm_path, bundle, service)
    routes = bundle['routes']
    if not routes or len({r['route_id'] for r in routes}) != len(routes):
        raise ValueError('Freight missing/duplicate routes')
    if not version:
        from generate_demand_z1 import principal_links
        _, eligible, _, _ = principal_links(network_path)
        nodes = {n.get('id'):(float(n.get('x')),float(n.get('y'))) for n in net.findall('./nodes/node')}
    for route in routes if not version else ():
        path = route['link_ids']
        if len(path) < 3 or any(x not in links or 'car' not in links[x].get('modes', 'car').split(',') for x in path):
            raise ValueError('Freight invalid car-access route')
        if not route.get('entry_gateway') or not route.get('exit_gateway') or path[0] == path[-1]:
            raise ValueError('Freight missing distinct boundary gateways')
        axis, reverse = route.get('axis'), route.get('reverse')
        if axis not in (0,1) or type(reverse) is not bool or route.get('boundary_basis') != 'outer_10_percent_computational_extent':
            raise ValueError('Freight boundary proxy provenance missing')
        coords = [nodes[links[k].get('from')][axis] for k in eligible]
        low, high = min(coords), max(coords)
        entry, leave = nodes[links[path[0]].get('from')][axis], nodes[links[path[-1]].get('to')][axis]
        if not ((entry >= high-.1*(high-low) and leave <= low+.1*(high-low)) if reverse else
                (entry <= low+.1*(high-low) and leave >= high-.1*(high-low))):
            raise ValueError('Freight endpoints are not opposite boundary proxies')
        for a, b in zip(path, path[1:]):
            if links[a].get('to') != links[b].get('from') or a in lanes and b not in lanes[a]:
                raise ValueError('Freight disconnected/forbidden turn: '+a+' -> '+b)
        for ident in path:
            attrs = {a.get('name'): a.text for a in links[ident].findall('attributes/attribute')}
            for key, value in attrs.items():
                if 'hgv' in key or 'maxweight' in key:
                    if key.endswith('hgv') and value in ('yes', 'designated', 'permissive'):
                        continue
                    raise ValueError('Freight route has an unsupported access restriction: '+ident+' '+key)
    roster = []
    slots = service['departure_slots_seconds']
    if not slots or any(type(t) not in (int, float) or not 0 <= t < 86400 or not permitted(t, windows=windows) for t in slots):
        raise ValueError('Freight departure slots outside permitted windows')
    margin = service['clearance_margin_seconds']
    if type(margin) not in (int, float) or not math.isfinite(margin) or margin < 0:
        raise ValueError('Freight clearance margin must be finite and nonnegative')
    spacing = service['dispatch_spacing_seconds']
    if type(spacing) not in (int, float) or not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Freight dispatch spacing must be positive')
    dispatch = service.get('dispatch_policy', 'legacy-fixed-spacing-v1')
    if dispatch not in ('legacy-fixed-spacing-v1', 'stratified-feasible-windows-v1'):
        raise ValueError('Freight unsupported dispatch policy')
    minima = [sum(float(links[x].get('length')) / min(float(links[x].get('freespeed')),
                  service['maximum_speed_kmh']/3.6) for x in r['link_ids']) for r in routes]
    starts = (stratified_departures(n, minima, windows, margin)
              if dispatch == 'stratified-feasible-windows-v1' else None)
    for i in range(n):
        route = routes[i % len(routes)]
        start = starts[i] if starts is not None else slots[i % len(slots)] + (i // len(slots)) * spacing
        minimum = minima[i % len(routes)]
        if start >= 86400 or not permitted(start, start + minimum + service['clearance_margin_seconds'], windows=windows):
            raise ValueError('Freight expedition cannot fit permitted interval with clearance margin')
        ident = f'freight_{i+1:06d}'
        from simz1_temporal import trip_id
        roster.append(dict(vehicle_id=ident, driver_id=ident, departure_id=trip_id(ident, 1),
                           departure_seconds=start, route_id=route['route_id'], link_ids=route['link_ids'],
                           entry_gateway=route['entry_gateway'], exit_gateway=route['exit_gateway']))
    return service, bundle, roster


def preflight(config, service, service_date=None, vehicles=None, temporal_policy=None):
    if temporal_policy is not None:
        raise ValueError('Freight weekday-v1 supports one civil day only; continuous multi-day policy requires a dated freight calendar')
    p, _, roster = prepare(config, service, service_date, vehicles)
    return dict(enabled=True, schema_version=SCHEMA, service_date=p['service_date'],
                **route_version(p),
                vehicles_configured=p['vehicles'], departures_scheduled=len(roster),
                independent_of_private_demand=True, empirical_calibration=False,
                allowed_windows_seconds=p['allowed_windows_seconds'], residence_policy=p['residence_policy'],
                body_contract=p.get('body_contract'), dispatch_policy=p.get('dispatch_policy', 'legacy-fixed-spacing-v1'),
                native_dimensions_m=dict(length_m=p['length_m'], width_m=p['width_m']))


def attach(run, base_config, service_path, service_date=None, vehicles=None, completion_policy=None):
    """Append service actors after private-demand verification; preserve private XML bytes."""
    from simz1_run import atomic_json
    from simz1_temporal import trip_id
    run = Path(run)
    service, bundle, roster = prepare(base_config, service_path, service_date, vehicles)
    if completion_policy is not None:
        from simz1_freight_completion import EXPERIMENTAL_POLICIES, policy_document, assigned_window
        if completion_policy not in EXPERIMENTAL_POLICIES or service['residence_policy'] != OVERNIGHT_POLICY:
            raise ValueError('Unsupported experimental freight completion selection')
        policy_document(completion_policy)
        service['completion_policy'] = completion_policy
        for row in roster:
            row['assigned_window_seconds'] = list(assigned_window(row['departure_seconds']))
            row['completion_policy'] = completion_policy
    version = route_version(service)
    if version:
        # Validate before any actor/vehicle writes. Buses may derive a different
        # network/receiving-lane snapshot while retaining the same link IDs.
        osm_path = (Path(service_path).resolve().parent / service['osm_file']).resolve()
        effective_config = run/'config-simz1.xml'
        if not effective_config.is_file():
            raise ValueError('Freight weekday-v2 requires the effective run config before attachment')
        route_report = validate_through_config(effective_config, osm_path, bundle, service)
    folder = run/'inputs/freight-weekday'
    folder.mkdir()
    if version:
        import shutil
        shutil.copyfile(osm_path, folder/'map.osm')
        service['osm_file'] = 'map.osm'
        atomic_json(folder/'route-validation.json', route_report)
    for name, value in [('service.json', service), ('routes.json', bundle), ('roster.json', roster)]:
        atomic_json(folder/name, value)
    persons = []
    for row in roster:
        ident, path, dep = row['driver_id'], row['link_ids'], row['departure_seconds']
        person = ET.Element('person', id=ident)
        attrs = ET.SubElement(person, 'attributes')
        ledger = [dict(id=trip_id(ident, 1), index=1, planned_departure=dep,
                       origin_link=path[0], destination_link=path[-1])]
        for key, value in dict(simz1FreightService=SCHEMA, simz1AgentType='TransportePesado',
                drivingProfile='TransportePesado', effectiveVehicleType='FreightTruck',
                simz1FreightRoute=' '.join(path), simz1FreightDeparture=str(dep),
                simz1FreightResidencePolicy=service['residence_policy'],
                simz1GrossWeightTonnes=str(service['gross_weight_tonnes']),
                simz1Trips=json.dumps(ledger, separators=(',', ':'))).items():
            ET.SubElement(attrs, 'attribute', name=key, **{'class':'java.lang.String'}).text = value
        if completion_policy is not None:
            geometry = next(r['native_gateway'] for r in route_report['routes'] if r['id'] == row['route_id'])
            for key,value in dict(simz1FreightCompletionPolicy=completion_policy,
                    simz1FreightAssignedWindow=json.dumps(row['assigned_window_seconds']),
                    simz1FreightGateway=json.dumps(geometry,sort_keys=True)).items():
                ET.SubElement(attrs,'attribute',name=key,**{'class':'java.lang.String'}).text=value
        ET.SubElement(attrs, 'attribute', name='vehicles', **{'class':'org.matsim.vehicles.PersonVehicles'}).text = json.dumps({'car':ident})
        plan = ET.SubElement(person, 'plan', selected='yes')
        ET.SubElement(plan, 'activity', type='freight_external', link=path[0], end_time=str(dep))
        leg = ET.SubElement(plan, 'leg', mode='car')
        ET.SubElement(leg, 'route', type='links', start_link=path[0], end_link=path[-1], vehicleRefId=ident).text = ' '.join(path)
        ET.SubElement(plan, 'activity', type='freight_external', link=path[-1])
        persons.append(ET.tostring(person, encoding='utf-8'))
    # Streaming copy keeps 250k-person preparation bounded in memory.
    plans = run/'plans.xml'
    with plans.open('rb') as src, plans.with_suffix('.freight.tmp').open('wb') as dst:
        for line in src:
            if b'</population>' in line:
                dst.write(b'\n'.join(persons)+b'\n')
            dst.write(line)
    plans.with_suffix('.freight.tmp').replace(plans)
    vehicles_path = run/'inputs/vehicles.xml'
    ns = 'http://www.matsim.org/files/dtd'
    ET.register_namespace('', ns)
    root = ET.parse(vehicles_path).getroot()
    if any(t.get('id') == 'FreightTruck' for t in root.findall('{*}vehicleType')):
        raise ValueError('Freight service cannot share the private catalog heavy VehicleType')
    kind = ET.Element('{'+ns+'}vehicleType', id='FreightTruck')
    attrs = ET.SubElement(kind, '{'+ns+'}attributes')
    ET.SubElement(attrs, '{'+ns+'}attribute', name='simz1FreightService', **{'class':'java.lang.String'}).text = SCHEMA
    ET.SubElement(attrs, '{'+ns+'}attribute', name='simz1FreightResidencePolicy', **{'class':'java.lang.String'}).text = service['residence_policy']
    if service.get('body_contract'):
        ET.SubElement(attrs, '{'+ns+'}attribute', name='simz1FreightBodyContract', **{'class':'java.lang.String'}).text = service['body_contract']
    for tag, attr, value in [('length','meter',service['length_m']), ('width','meter',service['width_m']),
                           ('maximumVelocity','meterPerSecond',service['maximum_speed_kmh']/3.6),
                           ('passengerCarEquivalents','pce',service['pcu']), ('networkMode','networkMode','car')]:
        ET.SubElement(kind, '{'+ns+'}'+tag, {attr:str(value)})
    root.insert(len(root.findall('{*}vehicleType')), kind)
    for row in roster:
        ET.SubElement(root, '{'+ns+'}vehicle', id=row['vehicle_id'], type='FreightTruck')
    ET.ElementTree(root).write(vehicles_path, encoding='utf-8', xml_declaration=True)
    return dict(enabled=True, schema_version=SCHEMA, service_date=service['service_date'],
                **({'completion_policy':completion_policy} if completion_policy is not None else {}),
                **version,
                source_service_sha256=hashlib.sha256(Path(service_path).read_bytes()).hexdigest(),
                vehicles_configured=len(roster), departures_scheduled=len(roster),
                fleet_vehicle_ids=[r['vehicle_id'] for r in roster],
                independent_of_private_demand=True, empirical_calibration=False,
                allowed_windows_seconds=service['allowed_windows_seconds'], residence_policy=service['residence_policy'],
                body_contract=service.get('body_contract'), dispatch_policy=service.get('dispatch_policy', 'legacy-fixed-spacing-v1'),
                native_dimensions_m=dict(length_m=service['length_m'], width_m=service['width_m']))


def verified_contract(directory, manifest):
    from simz1_run import checked_path, xml_elements
    expected = manifest.get('freight_transport', {})
    plans = checked_path(directory, manifest['inputs']['plans'])
    actors = {p.get('id'): dict(route=p.findtext("attributes/attribute[@name='simz1FreightRoute']"),
                              departure=p.findtext("attributes/attribute[@name='simz1FreightDeparture']"))
              for p in xml_elements(plans, 'person', 'population') if is_freight(p)}
    if not expected.get('enabled'):
        if actors:
            raise ValueError('Freight actors present without expected service')
        return {}
    records = {}
    for name in ('service.json', 'routes.json', 'roster.json'):
        key = 'input:freight-weekday/'+name
        if key not in manifest['inputs']:
            raise ValueError('Missing freight artifact: '+name)
        records[name] = json.loads(checked_path(directory, manifest['inputs'][key]).read_text(encoding='utf-8'))
    roster = records['roster.json']
    service = records['service.json']
    version = route_version(service)
    if version:
        if any(expected.get(key) != value for key, value in version.items()):
            raise ValueError('Freight saved service version differs from manifest')
        if service.get('osm_file') != 'map.osm':
            raise ValueError('Freight saved OSM must resolve inside its service snapshot')
        bundle = records['routes.json']
        if any(bundle.get(key) != value for key, value in version.items()):
            raise ValueError('Freight saved route bundle version differs from service')
        for name in ('map.osm', 'route-validation.json'):
            record = manifest['inputs'].get('input:freight-weekday/'+name)
            if record is None:
                raise ValueError('Missing weekday-v2 freight evidence: '+name)
            saved_path = checked_path(directory, record)
            if name == 'map.osm':
                check_base_network_fingerprint(saved_path, bundle.get('osm_sha256'))
        configured_routes = {row['route_id']: row for row in bundle['routes']}
        for row in roster:
            configured = configured_routes.get(row['route_id'], {})
            if any(row.get(key) != configured.get(key) for key in ('link_ids', 'entry_gateway', 'exit_gateway')):
                raise ValueError('Freight roster differs from versioned through route')
    residence_policy, windows = residence_contract(service)
    from simz1_freight_completion import EXPERIMENTAL_POLICIES, HISTORICAL, assigned_window
    completion_policy=service.get('completion_policy',HISTORICAL)
    if completion_policy not in (*EXPERIMENTAL_POLICIES,HISTORICAL) or expected.get('completion_policy',HISTORICAL)!=completion_policy:
        raise ValueError('Freight completion policy differs from saved service')
    if completion_policy in EXPERIMENTAL_POLICIES:
        from simz1_freight_completion import policy_document
        if json.loads(checked_path(directory,manifest['inputs']['input:freight-completion-policy.json']).read_bytes())!=policy_document(completion_policy):
            raise ValueError('Freight completion resource differs from pinned policy')
        for row in roster:
            if row.get('completion_policy')!=completion_policy or row.get('assigned_window_seconds')!=list(assigned_window(row['departure_seconds'])):
                raise ValueError('Freight assigned window changed from original roster')
    presentation_dimensions(service)
    if service.get('body_contract') and (expected.get('body_contract') != service['body_contract'] or
            expected.get('native_dimensions_m') != {key:service[key] for key in ('length_m','width_m')}):
        raise ValueError('Freight saved physical/visual body contract differs from manifest')
    if service.get('body_contract'):
        vehicle_record=manifest['inputs'].get('input:vehicles.xml')
        if vehicle_record is None:
            raise ValueError('Freight shared body requires fingerprinted native vehicle definitions')
        native=ET.parse(checked_path(directory,vehicle_record)).getroot().find("{*}vehicleType[@id='FreightTruck']")
        if (native is None or native.find('{*}length') is None or native.find('{*}width') is None or
                any(abs(float(native.find('{*}'+tag).get('meter','nan'))-service[field])>1e-9 or
                    not math.isfinite(float(native.find('{*}'+tag).get('meter','nan')))
                    for tag,field in [('length','length_m'),('width','width_m')]) or
                native.findtext("{*}attributes/{*}attribute[@name='simz1FreightBodyContract']") != service['body_contract']):
            raise ValueError('Freight native VehicleType differs from shared body contract')
    if (service.get('schema_version') != SCHEMA or expected.get('schema_version') != SCHEMA or
            service.get('service_date') != expected.get('service_date') or
            expected.get('allowed_windows_seconds') != windows or
            expected.get('residence_policy', LEGACY_RESIDENCE_POLICY) != residence_policy or
            date.fromisoformat(service['service_date']).weekday() >= 5):
        raise ValueError('Freight service identity/date/windows mismatch')
    ids = [r['vehicle_id'] for r in roster]
    if (len(ids) != len(set(ids)) or set(ids) != set(actors) or sorted(ids) != sorted(expected['fleet_vehicle_ids']) or
            len(ids) != expected['vehicles_configured'] or len(roster) != expected['departures_scheduled'] or
            len(ids) != records['service.json']['vehicles']):
        raise ValueError('Freight configured fleet/expedition/identity mismatch')
    for r in roster:
        if actors[r['vehicle_id']] != dict(route=' '.join(r['link_ids']), departure=str(r['departure_seconds'])):
            raise ValueError('Freight plan differs from roster')
    for person in xml_elements(plans, 'person', 'population'):
        if is_freight(person) and person.findtext("attributes/attribute[@name='simz1FreightResidencePolicy']", LEGACY_RESIDENCE_POLICY) != residence_policy:
            raise ValueError('Freight native person residence policy differs from saved service')
        if is_freight(person):
            if person.findtext("attributes/attribute[@name='simz1FreightCompletionPolicy']",HISTORICAL)!=completion_policy:
                raise ValueError('Freight native completion policy changed')
            if completion_policy in EXPERIMENTAL_POLICIES:
                dep=float(actors[person.get('id')]['departure'])
                if json.loads(person.findtext("attributes/attribute[@name='simz1FreightAssignedWindow']",'null'))!=list(assigned_window(dep)):
                    raise ValueError('Freight native assigned window changed')
            plans_for_actor = person.findall('plan')
            if len(plans_for_actor) != 1:
                raise ValueError('Freight through actor must have one plan')
            elements = list(plans_for_actor[0])
            if ([e.tag for e in elements] != ['activity', 'leg', 'activity'] or
                    any(elements[i].get('type') != 'freight_external' for i in (0, 2)) or
                    elements[1].get('mode') != 'car'):
                raise ValueError('Freight through plan cannot include internal activities/deliveries')
            path = actors[person.get('id')]['route'].split()
            from simz1_route_xml import validate_link_route
            validate_link_route(elements[1].find('route'), path, origin=elements[0].get('link'),
                destination=elements[2].get('link'), vehicle_id=person.get('id'))
            if float(elements[0].get('end_time', 'nan')) != float(actors[person.get('id')]['departure']):
                raise ValueError('Freight executable departure differs from roster')
    gateway_geometry = {}
    if service.get('native_gateway_policy'):
        # Recompute from pinned effective geometry; do not trust a copied report.
        report = validate_through_config(Path(directory)/'config-simz1.xml',
            checked_path(directory, manifest['inputs']['input:freight-weekday/map.osm']), records['routes.json'], service)
        gateway_geometry = {r['id']:r['native_gateway'] for r in report['routes']}
    if completion_policy in EXPERIMENTAL_POLICIES:
        for person in xml_elements(plans,'person','population'):
            if is_freight(person):
                row=next(r for r in roster if r['vehicle_id']==person.get('id'))
                if json.loads(person.findtext("attributes/attribute[@name='simz1FreightGateway']",'null'))!=gateway_geometry.get(row['route_id']):
                    raise ValueError('Freight native gateway geometry differs from verified inputs')
    return {r['vehicle_id']:dict(r, allowed_windows_seconds=windows, residence_policy=residence_policy,
        **({'completion_policy':completion_policy} if completion_policy in EXPERIMENTAL_POLICIES else {}),
        **({'native_gateway':gateway_geometry[r['route_id']]} if gateway_geometry else {})) for r in roster}


def verify_effective(directory, plans, vehicles, contract):
    """Verify service attributes and actual loaded vehicle assignments, not prefixes."""
    from simz1_run import xml_elements
    from simz1_motion import read_vehicle_definitions
    expected = {p.get('id'): {a.get('name'):a.text for a in p.findall('attributes/attribute')
                            if a.get('name') in ('simz1FreightService','simz1FreightRoute','simz1FreightDeparture',
                                                 'simz1GrossWeightTonnes','simz1AgentType','effectiveVehicleType','simz1FreightResidencePolicy','simz1FreightCompletionPolicy','simz1FreightAssignedWindow','simz1FreightGateway')}
                for p in xml_elements(Path(directory)/'plans.xml','person','population') if is_freight(p)}
    actual = {p.get('id'): {a.get('name'):a.text for a in p.findall('attributes/attribute')
                          if a.get('name') in ('simz1FreightService','simz1FreightRoute','simz1FreightDeparture',
                                               'simz1GrossWeightTonnes','simz1AgentType','effectiveVehicleType','simz1FreightResidencePolicy','simz1FreightCompletionPolicy','simz1FreightAssignedWindow','simz1FreightGateway')}
              for p in xml_elements(plans,'person','population') if is_freight(p)}
    if set(actual) != set(contract) or actual != expected:
        raise ValueError('Freight output plan identity/attributes changed')
    if not contract: return
    expected_types, expected_ids = read_vehicle_definitions(Path(directory)/'inputs/vehicles.xml')
    actual_types, actual_ids = read_vehicle_definitions(vehicles)
    if any(actual_ids.get(k) != expected_ids[k] for k in contract) or actual_types.get('FreightTruck') != expected_types.get('FreightTruck'):
        raise ValueError('Freight effective vehicles/physical parameters changed')


class FreightAudit:
    def __init__(self, contract, *, fixed_day=False):
        self.contract = contract
        self.fixed_day=fixed_day
        from simz1_freight_completion import EXPERIMENTAL_POLICIES, HISTORICAL
        policies={r.get('completion_policy',HISTORICAL) for r in contract.values()}
        if not policies.issubset({*EXPERIMENTAL_POLICIES,HISTORICAL}) or len(policies)>1:raise ValueError('Mixed/unknown freight completion policies')
        self.completion_policy=next(iter(policies),HISTORICAL)
        self.experimental=self.completion_policy in EXPERIMENTAL_POLICIES
        if self.experimental and any(not r.get('native_gateway') for r in contract.values()):
            raise ValueError('Experimental freight requires the native body-clearance contract')
        self.reset()

    def reset(self):
        """A fresh iteration; terminal events never erase this iteration's findings."""
        from simz1_freight_gateways import NativeGatewayAudit
        self.gateway = NativeGatewayAudit(self.contract)
        self.started, self.finished, self.active = set(), set(), {}
        self.seen, self.positions, self.durations = set(), {}, []
        self.expeditions, self.violations = [], {}
        self.traffic, self.terminals, self.last_times = {}, {}, {}
        self.entries, self.exits = {}, {}
        self.admission_rejections = {}
        self.day_census=None
        self.day_cut=None

    def _residence(self, ident, time, kind):
        start = self.traffic.get(ident)
        row = self.contract[ident]
        if start is not None and not permitted(start, time, windows=row.get('allowed_windows_seconds', WINDOWS)):
            self.violations.setdefault(ident, dict(vehicle_id=ident, entry_seconds=start,
                observed_seconds=time, event_type=kind, residence_policy=row.get('residence_policy', OVERNIGHT_POLICY),
                evidence='terminal_residence' if kind in ('arrival', 'stuckAndAbort', 'vehicle aborts') else 'traffic_residence'))

    def consume(self, event):
        if event.get('type')=='simz1DayCut' and self.fixed_day:
            if self.day_cut is not None or float(event.get('time'))!=86400:raise ValueError('Invalid freight day cut')
            self.day_cut=86400
            return False
        self.gateway.consume(event)
        ident = event.get('person') or event.get('vehicle')
        if ident not in self.contract:
            return False
        row, kind, t = self.contract[ident], event.get('type'), float(event.get('time'))
        movement = ('vehicle enters traffic','vehicle leaves traffic','entered link','left link','entered lane','left lane')
        abort = kind in ('stuckAndAbort','vehicle aborts')
        if kind not in (*movement, 'departure', 'arrival', 'stuckAndAbort', 'vehicle aborts', 'simz1NativeDecision', 'simz1FreightAdmissionRejected'):
            return True
        if not math.isfinite(t) or t < self.last_times.get(ident, -math.inf):
            raise ValueError('Freight invalid/non-monotone event time: '+ident)
        self.last_times[ident] = t
        path = row['link_ids']
        if kind == 'simz1FreightAdmissionRejected':
            from simz1_freight_completion import assigned_window, entry_permitted, TOLERATED_ENTRY_POLICY
            a,b=assigned_window(row['departure_seconds'])
            inclusive=self.completion_policy==TOLERATED_ENTRY_POLICY
            latest=b+3600 if inclusive else b
            reason=('before_scheduled_departure' if t<max(a,row['departure_seconds']-1.01) else
                    'assigned_entry_deadline_expired' if inclusive else 'assigned_nominal_window_closed')
            numeric=dict(scheduledDeparture=row['departure_seconds'],assignedWindowStart=a,
                         assignedWindowClose=b,latestEntryTime=latest,completionDeadline=b+3600)
            if (not self.experimental or ident not in self.active or ident in self.seen
                    or event.get('vehicle')!=ident or event.get('link')!=path[0]
                    or entry_permitted(row['departure_seconds'],t,self.completion_policy)
                    or event.get('reason')!=reason or self.admission_rejections.get(ident,{}).get('reason')==reason
                    or event.get('latestEntryInclusive')!=str(inclusive).lower()
                    or event.get('completionPolicy')!=self.completion_policy
                    or event.get('entryPolicy')!=('assigned_window_close_plus3600_inclusive' if inclusive else 'original_assigned_nominal_window_only')
                    or any(float(event.get(k,'nan'))!=v for k,v in numeric.items())):
                raise ValueError('Invalid/duplicate freight admission rejection: '+ident)
            self.admission_rejections[ident]=dict(reason=reason,time=t,latest_entry_time=latest,
                latest_entry_inclusive=inclusive,status='authorization_expired_not_admitted' if t>=b else 'waiting_for_incorporation')
            return True
        if kind == 'departure':
            if ident in self.started or abs(t-row['departure_seconds']) > 1.01 or event.get('link') != path[0]:
                raise ValueError('Freight duplicate/late/incorrect departure: '+ident)
            self.started.add(ident); self.active[ident] = t
        if kind in ('departure','arrival',*movement):
            if event.get('link') not in path:
                raise ValueError('Freight outside configured route: '+ident)
        if kind in (*movement, 'arrival') and ident not in self.active:
            raise ValueError('Freight movement/arrival without active departure: '+ident)
        if kind in movement and kind != 'vehicle enters traffic' and ident not in self.traffic:
            raise ValueError('Freight movement without traffic entry: '+ident)
        if kind == 'vehicle enters traffic':
            if ident in self.seen or event.get('vehicle') != ident or event.get('link') != path[0]:
                raise ValueError('Freight vehicle/driver identity mismatch')
            if self.experimental:
                from simz1_freight_completion import entry_permitted
                if not entry_permitted(row['departure_seconds'],t,self.completion_policy):
                    raise ValueError('Freight entry outside its assigned authorization: '+ident)
            self.seen.add(ident); self.positions[ident] = 0
            self.traffic[ident] = t
            self.entries[ident] = t
        self._residence(ident, t, kind)
        if kind == 'entered link':
            index = self.positions.get(ident, -1)+1
            if index >= len(path) or event.get('link') != path[index]:
                raise ValueError('Freight route sequence mismatch: '+ident)
            self.positions[ident] = index
        if kind == 'vehicle leaves traffic':
            self.traffic.pop(ident)
            self.exits[ident] = t
        if kind == 'arrival':
            if self.positions.get(ident) != len(path)-1 or event.get('link') != path[-1]:
                raise ValueError('Freight incomplete route/arrival: '+ident)
            start = self.active.pop(ident)
            self.durations.append(t-start); self.finished.add(ident)
            self.expeditions.append(dict(vehicle_id=ident, departure_seconds=start, arrival_seconds=t,
                                         duration_seconds=t-start, route_id=row.get('route_id')))
            self.terminals[ident] = dict(status='completed', time=t, sources={kind})
        if abort:
            terminal = self.terminals.get(ident)
            if terminal is not None:
                if terminal['status'] != 'aborted' or terminal['time'] != t or kind in terminal['sources']:
                    raise ValueError('Freight conflicting/duplicate terminal event: '+ident)
                terminal['sources'].add(kind)  # MATSim may emit both person and vehicle abort.
            else:
                never_started=ident not in self.started and self.fixed_day and self.day_cut is not None and t>=self.day_cut
                if ident not in self.active and not never_started:
                    raise ValueError('Freight abort without departure: '+ident)
                self.terminals[ident] = dict(status='aborted', time=t, sources={kind})
                self.active.pop(ident,None)
        if kind == 'arrival' or abort:
            self.traffic.pop(ident, None)
            self.positions.pop(ident, None)
        return True

    def summary(self):
        complete = self.finished == set(self.contract) and not self.active
        compliance = 'violated' if self.violations else 'undetermined' if self.active or self.started != set(self.contract) else 'no_violation_observed'
        result = dict(audit_version=2, residence_basis='vehicle_enters_until_leaves_or_terminal',
                    native_gateway=self.gateway.summary(),
                    technical_integrity='valid', schedule_compliance=compliance,
                    trip_outcome='completed' if complete else 'incomplete',
                    status='valid' if complete and not self.violations else 'invalid',
                    vehicles_observed=len(self.seen), departures_observed=len(self.started),
                    arrivals_observed=len(self.finished), fleet_vehicle_ids=sorted(self.seen),
                    restricted_window_violations=len(self.violations),
                    violations=[self.violations[k] for k in sorted(self.violations)],
                    aborted_expeditions=sum(t['status'] == 'aborted' for t in self.terminals.values()),
                    active_or_censored=len(self.active), waiting_for_insertion=len(set(self.active)-self.seen),
                    missing_departures=len(set(self.contract)-self.started),
                    observed_traffic_entries=dict(sorted(self.entries.items())),
                    observed_traffic_exits=dict(sorted(self.exits.items())),
                    admission_rejections=dict(sorted(self.admission_rejections.items())),
                    terminal_events={k: dict(v, sources=sorted(v['sources'])) for k,v in sorted(self.terminals.items())},
                    completed_duration_seconds=self.durations,
                    residence_window_policies=sorted({row.get('residence_policy', OVERNIGHT_POLICY) for row in self.contract.values()}),
                    expeditions=sorted(self.expeditions,key=lambda r:r['vehicle_id']))
        if self.experimental:
            from simz1_freight_completion import evaluate
            from collections import Counter
            rows=[]
            for ident,row in sorted(self.contract.items()):
                terminal=self.terminals.get(ident,{})
                rows.append(evaluate(row,entry=self.entries.get(ident),traffic_exit=self.exits.get(ident),
                    arrival=terminal.get('time') if terminal.get('status')=='completed' else None,
                    clearance=self.gateway.arrival_proofs.get(ident),aborted=terminal.get('status')=='aborted',
                    nominal_violation=ident in self.violations))
            counts=Counter(r['classification'] for r in rows)
            accepted=complete and all(r['classification'] in ('nominal','tolerated') for r in rows)
            technical=all(r['technical_integrity']=='valid' for r in rows) and self.gateway.summary()['complete']
            result.update(audit_version=3,completion_policy=self.completion_policy,
                status='valid' if complete and technical else 'invalid',
                technical_integrity='valid' if technical else 'not_evaluable_or_invalid',
                experimental_acceptance='satisfied' if accepted else 'not_satisfied' if counts['excess_tolerance'] else 'not_evaluable',
                completion_classifications={key:counts[key] for key in ('nominal','tolerated','excess_tolerance','pending_not_evaluable','technical_physical_error')},
                completion_records=rows)
            if self.day_census is not None:
                censored={k for k,r in self.day_census.items() if r['status'] in
                    ('active_at_cut','waiting_for_incorporation','scheduled_not_departed')}
                if set(self.day_census)!=set(self.contract):raise ValueError('Day census freight roster mismatch')
                completed={r['vehicle_id'] for r in rows if r['trip_outcome']=='completed' and r['technical_integrity']=='valid'}
                technical=((completed|censored)==set(self.contract) and completed==set(self.gateway.arrival_proofs)
                    and self.seen==set(self.gateway.departure_proofs) and
                    all(r['classification']!='technical_physical_error' for r in rows))
                for r in rows:
                    if r['vehicle_id'] in censored and r['classification']!='technical_physical_error':
                        r.update(trip_outcome='censored_at_horizon',classification='pending_not_evaluable',
                            technical_integrity='valid_censored_prefix',deadline_evaluable_at_cut=r['deadline_seconds']<=86400,
                            observed_traffic_seconds=self.day_census[r['vehicle_id']]['observed_traffic_seconds'],
                            window_close_observed_at_cut=r['window_close_seconds']<=86400,
                            observed_delay_since_window_close_lower_bound_seconds=max(0,86400-r['window_close_seconds']),
                            delay_observation_at_seconds=86400,
                            delay_observation_basis='unfinished_at_cut;elapsed_since_assigned_window_close;'
                                'not_trip_duration_or_imputed_arrival')
                counts=Counter(r['classification'] for r in rows)
                real_aborts=sum(r['status']=='aborted_before_cut' for r in self.day_census.values())
                result.update(status='valid' if technical else 'invalid',technical_integrity='valid' if technical else 'invalid',
                    trip_outcome='completed' if complete else 'incomplete_with_real_aborts' if real_aborts else 'censored_at_horizon',
                    censored_at_horizon=len(censored),day_observation_policy='fixed-day-24h-v1',
                    active_or_censored=len(censored),
                    waiting_for_insertion=sum(r['status']=='waiting_for_incorporation' for r in self.day_census.values()),
                    active_in_traffic_at_cut=sum(r['status']=='active_at_cut' for r in self.day_census.values()),
                    scheduled_not_departed_at_cut=sum(r['status']=='scheduled_not_departed' for r in self.day_census.values()),
                    administrative_cleanup_abort_events=sum(self.day_census[k].get('cleanup_abort_events',0) for k in censored),
                    aborted_expeditions=real_aborts,
                    completion_classifications={key:counts[key] for key in ('nominal','tolerated','excess_tolerance','pending_not_evaluable','technical_physical_error')},
                    experimental_acceptance='satisfied' if accepted else 'not_satisfied' if counts['excess_tolerance'] else 'not_evaluable',
                    historical_close_plus3600_indicator_only=self.completion_policy=='freight-close-plus3600-v1',
                    completion_deadline_is_indicator_not_removal=True,
                    entry_authorization_policy=('assigned_window_close_plus3600_inclusive'
                        if self.completion_policy=='freight-entry-and-completion-close-plus3600-v2'
                        else 'original_assigned_nominal_window_only'))
        return result


def require_approved_results(manifest):
    """Called after event streams close and their evidence is retained in results."""
    rejected = {iteration: result['freight_transport_events'] for iteration, result in manifest['results'].items()
                if result['freight_transport_events']['status'] != 'valid'}
    if rejected:
        manifest['freight_validation'] = dict(status='invalid', iterations=rejected)
        manifest['validation'] = dict(status='invalid', error='Freight service not approved')
        raise ValueError('Freight service not approved: '+', '.join(sorted(rejected)))
    experimental={it:r['freight_transport_events'].get('experimental_acceptance') for it,r in manifest['results'].items()
                  if r['freight_transport_events'].get('completion_policy')}
    if experimental:
        values=set(experimental.values())
        if not values.issubset({'satisfied','not_satisfied','not_evaluable'}):
            raise ValueError('Unknown freight experimental acceptance state')
        aggregate=('not_satisfied' if 'not_satisfied' in values else
                   'not_evaluable' if 'not_evaluable' in values else 'satisfied')
        manifest['freight_validation']=dict(status='valid',experimental_acceptance=aggregate,iterations=experimental,
            nominal_violations_retained=True,timing_excess_does_not_invalidate_native_integrity=True)
