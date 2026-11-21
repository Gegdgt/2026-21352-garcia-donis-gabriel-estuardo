"""Inspect SimZ1 source, native topology, restrictions and rendered paths offline.

No server, browser, simulation, population or SQLite read. Default is stdout;
--output-new writes evidence JSON only into a new directory. --strict is a
static preflight, never permission to run or certification of current OSM.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess

from simz1_connectivity_review import analyze
from simz1_osm_turn_audit import inspect_restrictions, load_lanes, load_xml, source_way_id
from simz1_run import checked_path
from simz1_run_directory import check_new_directory

ROOT = Path(__file__).resolve().parents[1]
OD_CASES = ('internal-internal', 'internal-external', 'external-internal', 'external-external')
NODE_POSITION_TOLERANCE_M = 1e-4


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_configuration(config, network, lanes):
    """Reject unsupported effective inputs before claiming a lane-aware graph."""
    config = Path(config).resolve()
    root = load_xml(config)
    params = {f"{module.get('name')}.{param.get('name')}": param.get('value')
              for module in root.findall('module') for param in module.findall('param')}
    required = {'qsim.useLanes': 'true', 'global.coordinateSystem': 'EPSG:32615',
                'controler.enableLinkToLinkRouting': 'true'}
    for key, expected in required.items():
        if params.get(key) != expected:
            raise ValueError(f'Unsupported configuration: {key} must be {expected}; '
                             f'found {params.get(key)!r}. No effective graph was certified.')
    resolved = {}
    for key, expected in (('network.inputNetworkFile', network), ('network.laneDefinitionsFile', lanes)):
        value = params.get(key)
        if not value or value == 'null':
            raise ValueError(f'Effective artifact missing from configuration: {key}')
        path = (config.parent/value).resolve()
        if path != Path(expected).resolve() or not path.is_file():
            raise ValueError(f'Effective artifact mismatch: {key} resolves to {path}; '
                             f'expected {Path(expected).resolve()}. No substitute was inspected.')
        resolved[key] = str(path)
    return dict(path=str(config), required_parameters=required, resolved_artifacts=resolved,
                status='configured_lane_graph_and_EPSG32615_verified')


def source_geometry_check(osm_path, network_path):
    """Match native node IDs/coordinates to source; never infer missing nodes."""
    from pyproj import Transformer
    from pyproj.exceptions import ProjError
    osm, network = load_xml(osm_path), load_xml(network_path)
    source_nodes = {node.get('id'): node for node in osm.findall('node') if node.get('action') != 'delete'}
    native_nodes = network.findall('nodes/node')
    native_ids, issues, distances = set(), [], []
    transform = Transformer.from_crs('EPSG:4326', 'EPSG:32615', always_xy=True)
    for node in native_nodes:
        nid = node.get('id')
        if not nid or nid in native_ids:
            issues.append(dict(node_id=nid, reason='missing_or_duplicate_network_node_id'))
            continue
        native_ids.add(nid)
        if nid not in source_nodes:
            issues.append(dict(node_id=nid, reason='network_node_without_OSM_source'))
            continue
        try:
            x, y = float(node.get('x')), float(node.get('y'))
            source = source_nodes[nid]
            lon, lat = float(source.get('lon')), float(source.get('lat'))
            if not all(math.isfinite(value) for value in (x, y, lon, lat)) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError('Non-finite or invalid coordinates')
            sx, sy = transform.transform(lon, lat, errcheck=True)
            distance = math.hypot(x-sx, y-sy)
        except (TypeError, ValueError, ProjError):
            issues.append(dict(node_id=nid, reason='invalid_source_or_network_coordinates'))
            continue
        distances.append(distance)
        if distance > NODE_POSITION_TOLERANCE_M:
            issues.append(dict(node_id=nid, reason='network_position_differs_from_OSM', distance_m=distance))
    missing_native = [dict(link_id=link.get('id'), role=key, node_id=link.get(key))
                      for link in network.findall('links/link') for key in ('from', 'to')
                      if link.get(key) not in native_ids]
    missing_source = sorted({(way.get('id'), ref.get('ref')) for way in osm.findall('way')
                             if way.get('action') != 'delete' and way.find("tag[@k='highway']") is not None
                             for ref in way.findall('nd') if ref.get('ref') not in source_nodes}, key=str)
    return dict(scope='OSM node identity and EPSG4326_to_EPSG32615 position; not field survey verification',
                tolerance_m=NODE_POSITION_TOLERANCE_M, network_nodes=len(native_nodes),
                compared_nodes=len(distances), maximum_position_error_m=max(distances, default=None),
                node_issues=issues, missing_network_link_nodes=missing_native,
                missing_highway_node_references=[dict(way_id=wid, node_id=nid) for wid, nid in missing_source],
                valid=bool(native_nodes) and not (issues or missing_native or missing_source))


def witness_blockers(routes):
    if not routes:
        return ['witness_routes_empty']
    blockers = []
    if any(row['status'] == 'missing_network_endpoint' for row in routes):
        blockers.append('witness_network_endpoint_missing')
    if any(row['status'] == 'search_limit' for row in routes):
        blockers.append('witness_search_incomplete')
    if any(row['status'] not in ('configured_path', 'no_configured_path', 'search_limit', 'missing_network_endpoint') for row in routes):
        blockers.append('witness_status_unknown')
    return blockers


def route_restriction_exposure(routes, restrictions):
    """Annotate full occurrences; a via-way sequence is never a final-turn ban."""
    prohibited = []
    for row in restrictions['rows']:
        if row['semantics_review'] or not row['restriction'].startswith('no_'):
            continue
        if row['status'] == 'mappable':
            for movement in row['admitting_movements'].split(';'):
                if movement:
                    prohibited.append((row['relation_id'], movement.split('>')))
        elif row['status'] == 'via_way_unsupported' and row['path_status'] == 'mapped':
            prohibited.extend((row['relation_id'], sequence) for sequence in json.loads(row['directed_sequences']))
    result = []
    for route in routes:
        path = route['links']
        violations = [dict(relation_id=ident, sequence=sequence, offset=index)
                      for ident, sequence in prohibited for index in range(len(path)-len(sequence)+1)
                      if path[index:index+len(sequence)] == sequence]
        result.append({**route, 'mapped_prohibition_occurrences': violations,
                       'legally_certified': False,
                       'restriction_scope': 'configured path only; unresolved/source-incomplete OSM relations remain pending'})
    return result


def topology_signature(path):
    root = load_xml(path)
    # Native writer changes XML representation, not necessarily native edges.
    nodes = sorted((n.get('id'), float(n.get('x')), float(n.get('y'))) for n in root.findall('nodes/node'))
    links = sorted((l.get('id'), l.get('from'), l.get('to'), source_way_id(l),
                    tuple(sorted(l.get('modes', 'car').split(','))),
                    *(float(l.get(key)) for key in ('length', 'freespeed', 'capacity', 'permlanes')))
                   for l in root.findall('links/link'))
    return dict(nodes=len(nodes), links=len(links),
                sha256=hashlib.sha256(json.dumps([nodes, links], separators=(',', ':')).encode()).hexdigest())


def source_context(review):
    car = review['components_by_mode'].get('car', {})
    weak = car.get('weak_components', [])
    focal = Counter(row['component_ids_by_mode']['car']['weak'] for row in review['links'] if 'car' in row['modes'])
    outside = [row for row in review['endpoints'] if row['classification'] == 'limite_del_extracto_continuacion_desconocida']
    main = weak[0]['component_id'] if weak else None
    return dict(focal_weak_components=dict(focal), main_weak_component=main,
                focal_links_outside_main=sum(count for ident, count in focal.items() if ident != main),
                source_endpoints_outside_extract=outside,
                expanded_source_needed_to_review_external_continuity=bool(outside and any(ident != main for ident in focal)),
                policy='Fetch complete connecting ways/nodes/restriction members for a future source version; '
                       'no fixed buffer guarantees completeness; no proximity links or invented administrative boundary')


def inspect(scenario, run_directory=None, iteration=0, node='node', approved_boundary=None):
    scenario = Path(scenario).resolve()
    osm, network, lanes, config = (scenario/name for name in ('map.osm', 'network.xml', 'lanes.xml', 'config-simz1.xml'))
    watched = {path: digest(path) for path in (osm, network, lanes, config)}
    configuration = checked_configuration(config, network, lanes)
    tool_sources = {name: digest(ROOT/'python'/name) for name in
                    ('inspect_simz1_connectivity.py', 'inspect_simz1_visual_connectivity.cjs',
                     'simz1_connectivity_review.py', 'simz1_osm_turn_audit.py', 'simz1_visual_lanes.py',
                     'simz1_visual_lanes.js', 'simz1_spatial_view.js')}
    base = analyze(osm, network, lanes)
    geometry = source_geometry_check(osm, network)
    restrictions = inspect_restrictions(osm, network, lanes)
    base['witness_routes'] = route_restriction_exposure(base['witness_routes'], restrictions)
    blockers = []
    if not geometry['valid']:
        blockers.append('source_node_geometry_or_references_mismatch')
    if base['summary']['invalid_lane_targets'] or any(base['global_import_check'][key] for key in
            ('missing_admissible_directed_segments', 'inconsistent_source_access_or_direction_links',
             'duplicate_source_directed_edges')):
        blockers.append('source_or_directed_topology_mismatch')
    # This converter has no native OSM relation import contract. Do not silently
    # promote either an excluded relation or the old declarative proposal.
    if restrictions['summary']['relations']:
        blockers.append('native_OSM_restriction_import_contract_pending')
    blockers.extend(witness_blockers(base['witness_routes']))
    od = dict(required_cases=list(OD_CASES), status='approved_boundary_not_supplied', changed=False)
    if approved_boundary:
        from simz1_gateway_od import load_gateway_model
        boundary = Path(approved_boundary).resolve()
        watched[boundary] = digest(boundary)
        model = load_gateway_model(network, boundary, lanes)
        od.update(status='explicit_boundary_directed_gateways_inspected', boundary_sha256=watched[boundary],
                  boundary_approval='caller_supplied; not independently certified by this tool',
                  entry_gateways=model.entry_gateways, exit_gateways=model.exit_gateways,
                  eligible_origins_by_case={kind: len(model.origins(kind)) for kind in OD_CASES})
        if any(not count for count in od['eligible_origins_by_case'].values()):
            blockers.append('one_or_more_OD_cases_without_configured_route')
    else:
        blockers.append('approved_boundary_and_directed_gateway_review_pending')
    report = dict(schema='simz1-connectivity-inspection-v2', read_only=True, physical_network_changes=[],
                  tool_sources_sha256=tool_sources,
                  configuration=configuration, source_geometry=geometry,
                  base=base, restrictions=restrictions, context=source_context(base), od=od,
                  preflight=dict(status='blocked' if blockers else 'static_checks_passed', blockers=blockers,
                                 scope='static source/topology preflight; lane-physics and native execution validation remain separate'),
                  historical=None, visual=None)
    if run_directory:
        from simz1_gateway_od import validated_spatial_demand
        from simz1_visual_lanes import load_visual_lanes
        directory = Path(run_directory).resolve()
        manifest = directory/'run-manifest.json'
        watched[manifest] = digest(manifest)
        run = json.loads(manifest.read_text(encoding='utf-8'))
        if run.get('status') != 'completed' or run.get('validation', {}).get('status') != 'valid':
            raise ValueError('Historical run must already be completed and validated')
        identity = dict(run_id=run['run_id'], iteration=iteration, run_manifest_sha256=watched[manifest])
        native_network = checked_path(directory, run['results'][str(iteration)]['network'])
        native_lanes = checked_path(directory, run['effective_lane_configuration_validation']['loaded_artifacts']['lanes'])
        native_config = checked_path(directory, run['effective_config'])
        native_input_network = checked_path(directory, run['inputs']['network'])
        lane_parameter = load_xml(native_config).find("module[@name='network']/param[@name='laneDefinitionsFile']")
        lane_value = lane_parameter.get('value') if lane_parameter is not None else None
        if not lane_value or lane_value == 'null':
            raise ValueError('Historical effective config lacks network.laneDefinitionsFile')
        configured_lane_path = (native_config.parent/lane_value).resolve()
        lane_record = next((record for record in run['inputs'].values()
                            if (directory/record['path']).resolve() == configured_lane_path), None)
        if lane_record is None:
            raise ValueError('Historical configured lanes have no hashed input record')
        native_input_lanes = checked_path(directory, lane_record)
        native_configuration = checked_configuration(native_config, native_input_network, native_input_lanes)
        native_configuration['loaded_lane_artifact'] = str(native_lanes)
        native_configuration['input_output_lane_movements_equal'] = load_lanes(native_input_lanes) == load_lanes(native_lanes)
        for path in (native_network, native_lanes, native_config, native_input_network, native_input_lanes):
            watched[path] = digest(path)
        historical = analyze(osm, native_network, native_lanes)
        native_restrictions = inspect_restrictions(osm, native_network, native_lanes)
        historical['witness_routes'] = route_restriction_exposure(historical['witness_routes'], native_restrictions)
        report['historical'] = dict(identity=identity, configuration=native_configuration,
            source_geometry=source_geometry_check(osm, native_network), review=historical, restrictions=native_restrictions,
            normalized_network_equal=topology_signature(network) == topology_signature(native_network),
            focal_links_equal=base['links'] == historical['links'],
            restriction_rows_equal=restrictions['rows'] == native_restrictions['rows'],
            source_scope='Current local OSM compared with hashed effective native network; historical manifest does not pin original OSM')
        metadata = load_visual_lanes(directory, run, identity)
        if not metadata['available']:
            raise ValueError(metadata.get('reason', 'Effective visual metadata unavailable'))
        spatial = validated_spatial_demand(directory, run)
        result = subprocess.run([node, str(ROOT/'python/inspect_simz1_visual_connectivity.cjs')],
            input=json.dumps(dict(visual_lanes=metadata, focus_link_ids=[row['id'] for row in historical['links']],
                                  spatial_demand=spatial)), encoding='utf-8', capture_output=True, timeout=45, check=True)
        report['visual'] = json.loads(result.stdout)
    if any(digest(path) != before for path, before in watched.items()):
        raise ValueError('An inspected input changed during the review; results must not be published')
    report['preservation'] = dict(inputs_unchanged=True, hashes={str(path): value for path, value in watched.items()},
                                  historical_runs_modified=False, demand_or_events_read=False)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=ROOT/'scenarios/zona1')
    parser.add_argument('--run-dir', type=Path, help='Optional existing historical run; metadata/XML reads only')
    parser.add_argument('--iteration', type=int, default=0)
    parser.add_argument('--node', default='node')
    parser.add_argument('--approved-boundary', type=Path, help='Explicit reviewed GeoJSON; never the OSM download rectangle')
    parser.add_argument('--output-new', type=Path, help='NEW directory for JSON evidence only; existing directories are refused')
    parser.add_argument('--strict', action='store_true', help='Exit 2 for preflight blockers; never starts MATSim')
    args = parser.parse_args(argv)
    output = check_new_directory(args.output_new) if args.output_new else None
    report = inspect(args.scenario, args.run_dir, args.iteration, args.node, args.approved_boundary)
    content = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    if output:
        output.mkdir(parents=True, exist_ok=False)
        with (output/'connectivity-inspection.json').open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        print(json.dumps(dict(output=str(output), preflight=report['preflight'],
                              sector=report['base']['summary'], restrictions=report['restrictions']['summary']['statuses'])))
    else:
        print(content)
    return 2 if args.strict and report['preflight']['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
