"""Revalidate approved private access on the existing transit derivation.

This is preparation evidence, never an approval receipt or a simulation result.
The source catalogue stays immutable; useful storage and budgets are not enlarged.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from simz1_balanced_od import digest, load_model, model_from_document, GAP_M, LEGACY
from simz1_lane_validation import audit_configuration, read_network, read_lanes
from simz1_gateway_od import _xml


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def network_semantics(path):
    """Numeric graph plus all source/access/path attributes, independent of XML layout."""
    from simz1_osm_turn_audit import source_way_id
    root = _xml(path)
    attributes = {}
    for row in root.findall('links/link'):
        attrs = {a.get('name'): a.text for a in row.findall('attributes/attribute')}
        # MATSim may serialize the XML origid as an attribute element.
        origid = source_way_id(row)
        attrs.pop('origid', None)
        attributes[row.get('id')] = dict(attributes=attrs, origid=origid)
    return dict(graph=read_network(path)[-1], attributes=attributes)


def review(source_network, source_lanes, network, lanes, boundary, osm, access,
           service_directory, crs='EPSG:32615'):
    """Replay the SAME pure derivation, then check every approved physical resource."""
    from simz1_weekday_transit import derive_geometry, verify_policy_chain, load_policy
    from simz1_stop_proxy import QUEUE_POLICY
    from simz1_od_policy import validate_osm_turns
    source = load_model(source_network, boundary, source_lanes, osm, access, crs)
    service_directory = Path(service_directory)
    policy_path = service_directory/'weekday-policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    source_service = service_directory/'source-service.json'
    original_policy, _ = load_policy(source_service, policy['service_date'], policy['route_assumptions_accepted'])
    if any(policy.get(key) != value for key, value in original_policy.items()):
        raise ValueError('Effective access: service policy differs from its preserved source')
    bundle_path = service_directory/'route-bundle.json'
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    if (policy.get('stop_queue_policy') != QUEUE_POLICY or
            policy.get('base_network_sha256') != digest(source_network) or
            policy.get('source_bundle_sha256') != digest(bundle_path)):
        raise ValueError('Effective access: service source/policy identity mismatch')
    config = ET.Element('config')
    net = ET.SubElement(config, 'module', name='network')
    ET.SubElement(net, 'param', name='inputNetworkFile', value=str(Path(source_network).resolve()))
    ET.SubElement(net, 'param', name='laneDefinitionsFile', value=str(Path(source_lanes).resolve()))
    ET.SubElement(ET.SubElement(config, 'module', name='qsim'), 'param', name='useLanes', value='true')
    expected_net, plan, expected_lanes = derive_geometry(config, Path.cwd(), policy, bundle,
                                                        policy['road_demand_persons'])
    # Never infer authorization from the list of changed links in a prior run.
    expected_queues = plan['stop_queue_summary']
    recorded_queues = dict(policy['stop_queue_summary'])
    recorded_queues.pop('generated_lanes_sha256', None)
    if recorded_queues != expected_queues:
        raise ValueError('Effective access: declared queue adjustments differ from service derivation')
    with tempfile.TemporaryDirectory(prefix='simz1-derivation-check-') as folder:
        expected_network_path, expected_lane_path = (Path(folder)/name for name in ('network.xml', 'lanes.xml'))
        ET.ElementTree(expected_net).write(expected_network_path, encoding='utf-8')
        ET.ElementTree(expected_lanes).write(expected_lane_path, encoding='utf-8')
        if network_semantics(network) != network_semantics(expected_network_path):
            raise ValueError('Effective access: undeclared network geometry/capacity/access change')
        actual_lanes, intended_lanes = read_lanes(lanes), read_lanes(expected_lane_path)
        if actual_lanes != intended_lanes:
            changed = sorted(k for k in set(actual_lanes) | set(intended_lanes)
                             if actual_lanes.get(k) != intended_lanes.get(k))
            raise ValueError('Effective access: undeclared lane endpoint/capacity/movement change: '+', '.join(changed))
    schedule_path = service_directory/'transitSchedule.xml'
    metadata = {row.get('name'): row.text for row in _xml(schedule_path).findall('attributes/attribute')}
    verify_policy_chain(schedule_path, metadata, policy['road_demand_persons'])
    restrictions = validate_osm_turns(osm, network, lanes, allow_transit_bus_exits=True)
    model = model_from_document(network, boundary, lanes, osm, access, deepcopy(source.document), crs)
    resources = []
    facilities = set()
    # Recompute bottlenecks from unique terminal queues. Alternative paths never
    # add budgets; the scheduled GatewayBudget continues to share link IDs.
    for role, rows in (('entry', model.entry_gateways), ('exit', model.exit_gateways), ('internal', model.sites)):
        for key, row in sorted(rows.items()):
            path = row.get('link_ids', row.get('egress_link_ids'))
            if not path:
                raise ValueError('Effective access: missing reviewed resource path: '+key)
            model.validate_route(path)
            link_budgets = [dict(link_id=k, capacity_pcu_h=model.links[k]['capacity']) for k in path]
            movement_budgets = []
            for a, b in zip(path, path[1:]):
                if a not in actual_lanes:
                    continue
                terminal_ids = sorted(k for k, lane in actual_lanes[a].items() if b in lane['to_links'])
                movement_budgets.append(dict(from_link=a, to_link=b, terminal_lanes=terminal_ids,
                    capacity_pcu_h=math.fsum(actual_lanes[a][k]['capacity'] for k in terminal_ids)))
            basis = row['capacity_basis']
            if basis['link_budgets'] != link_budgets or basis['movement_budgets'] != movement_budgets:
                raise ValueError('Effective access: reviewed resource budgets changed: '+key)
            limit = min(r['capacity_pcu_h'] for r in link_budgets+movement_budgets)
            rate = row['incorporation_capacity_pcu_h'] if role == 'internal' else row[role+'_capacity_pcu_h']
            if rate > limit or row['useful_length_m'] > model.queue_ends[key]:
                raise ValueError('Effective access: reviewed storage/budget invalid: '+key)
            if role == 'internal':
                component = row['facility_component']
                if component in facilities:
                    raise ValueError('Effective access: duplicate shared facility: '+component)
                facilities.add(component)
            body = row['storage_basis']['body_m']
            if row['useful_length_m'] < body+GAP_M:
                raise ValueError('Effective access: whole body plus 0.10m does not fit: '+key)
            clearance = model.exit_clearance(key, body) if role == 'exit' else None
            if clearance is not None and clearance < -1e-8:
                raise ValueError('Effective access: exterior clearance invalid: '+key)
            resources.append(dict(role=role, id=row.get('id', key), link_id=key,
                source_native_endpoint_m=source.queue_ends[key], effective_native_endpoint_m=model.queue_ends[key],
                reviewed_useful_length_m=row['useful_length_m'], useful_length_m=row['useful_length_m'],
                body_m=body, minimum_gap_m=GAP_M, whole_slots_per_lane=math.floor(row['useful_length_m']/(body+GAP_M)),
                budget_pcu_h=rate, recomputed_bottleneck_pcu_h=limit, exterior_clearance_m=clearance,
                physical_link_resources=sorted(set(path))))
    eligibility = {}
    for body in (2.1, 4.5):
        eligible = sorted(k for k in model.internal_links if model.queue_ends[k]+1e-8 >= body+GAP_M)
        before = {k for k in source.internal_links if source.queue_ends[k]+1e-8 >= body+GAP_M}
        for kind in LEGACY:
            def connected_origins(candidate):
                rows = candidate.entry_gateways if kind.startswith('external') else candidate.sites
                return {key for key, row in rows.items()
                        if min(row['useful_length_m'], candidate.queue_ends[key])+1e-8 >= body+GAP_M
                        and next(candidate.iter_candidates(key, kind, body), None) is not None}
            previous, current = connected_origins(source), connected_origins(model)
            if previous != current:
                raise ValueError('Effective access: approved origin connectivity/clearance changed: '+kind+' '+str(sorted(previous ^ current)))
        eligibility[str(body)] = dict(eligible_links=eligible, added=sorted(set(eligible)-before),
                                     removed=sorted(before-set(eligible)))
    changed = []
    for key in sorted(source.queue_ends):
        if source.queue_ends[key] == model.queue_ends[key]:
            continue
        changed.append(dict(link_id=key, source_m=source.queue_ends[key], effective_m=model.queue_ends[key],
            gateway_chains=[r['id'] for table in (model.entry_gateways, model.exit_gateways)
                            for r in table.values() if key in r['link_ids']],
            internal_origin=key in model.sites,
            internal_egress=[k for k, r in model.sites.items() if key in r['egress_link_ids']],
            eligible_destination_for_body_m=[float(body) for body, row in eligibility.items() if key in row['eligible_links']],
            private_route_domain=key in model.eligible_links))
    sources = dict(network=digest(source_network), lanes=digest(source_lanes), osm=digest(osm),
                   access=digest(access), boundary=digest(boundary), route_bundle=digest(bundle_path),
                   service=digest(source_service))
    implementation = {name: digest(Path(__file__).with_name(name)) for name in
                      ('simz1_weekday_transit.py', 'simz1_stop_proxy.py')}
    service = {k: v for k, v in policy.items() if k not in (
        'road_demand_persons', 'stop_queue_summary', 'stop_proxy_summary', 'stop_proxy_manifest_file',
        'stop_proxy_manifest_sha256', 'configured_fleet_size')}
    evidence = dict(schema_version='simz1-effective-access-v1', status='accepted_for_preparation',
        source_sha256=sources, service_policy=policy['stop_queue_policy'],
        transformation_implementation_sha256=implementation,
        transformation_identity=signature(dict(sources=sources, service=service, implementation=implementation)),
        effective_sha256=dict(network=digest(network), lanes=digest(lanes)),
        semantic_signatures=dict(network=signature(network_semantics(network)), lanes=signature(actual_lanes)),
        verified_adjustments=expected_queues['adjustments'], changed_endpoints=changed,
        access_resources=resources, destination_eligibility=eligibility,
        approval_scope='existing model permissions and budgets retained; effective physical properties rechecked; no simulation',
        shared_space_policy='one native receiving queue per link; terminal segments not added; existing shared-link budget ledger',
        restriction_preflight=restrictions)
    model.summary['effective_access'] = dict(status=evidence['status'],
        transformation_identity=evidence['transformation_identity'],
        source_sha256=sources, effective_sha256=evidence['effective_sha256'])
    return model, evidence


def prepare(config, base_directory, output, road_persons, service, day, accept_assumptions,
            boundary, osm, access):
    """Shared by real preparation and both preflights; attach exactly once."""
    from simz1_weekday_transit import attach
    base_directory, output = Path(base_directory), Path(output)
    paths = {}
    for name in ('inputNetworkFile', 'laneDefinitionsFile'):
        param = config.find(f"module[@name='network']/param[@name='{name}']")
        paths[name] = (base_directory/param.get('value')).resolve(strict=True)
        param.set('value', str(paths[name]))
    metadata = attach(config, output, road_persons, service, day, accept_assumptions)
    shutil.copyfile(service, output/'source-service.json')
    audit = audit_configuration(config, base_dir=base_directory, osm_path=osm)
    # Fixed-service impossibility can be established immediately on the actual
    # attached geometry. Do it before the more expensive private access trees.
    from simz1_temporal_passage import TemporalPassage, fixed_transit_audit, require_fixed_transit
    temporal = TemporalPassage(config, base_directory)
    temporal_report = fixed_transit_audit(temporal, output/'transitSchedule.xml', output/'transitVehicles.xml')
    (output/'temporal-passage-audit.json').write_text(json.dumps(temporal_report, indent=2)+'\n', encoding='utf-8')
    require_fixed_transit(temporal_report)
    model, evidence = review(paths['inputNetworkFile'], paths['laneDefinitionsFile'],
        output/'network.xml', output/'lanes.xml', boundary, osm, access, output,
        config.find("module[@name='global']/param[@name='coordinateSystem']").get('value'))
    evidence['source_service_sha256'] = digest(service)
    model.temporal = temporal
    evidence['temporal_passage'] = temporal_report
    return model, evidence, metadata, audit
