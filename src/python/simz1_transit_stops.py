"""Read-only, evidence-gated stop annotations; never creates services or bus demand.

stop-display.json is an optional reviewed mapping beside the Prompt 9 catalog.
It must name the exact effective network hash. No nearest-road matching, centroid,
OSM bbox boundary or source-coordinate relocation is performed here.
catalog-display.json is a separate, reviewed annotation contract: a platform
in a dated source is not a stop linked to, or used by, the native simulation.
"""
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_gateway_od import Polygon
from simz1_transit_catalog import DEFAULT_DIRECTORY

SCHEMA = 'simz1-stop-display-v1'
CATALOG_SCHEMA = 'simz1-catalog-stop-annotations-v1'
SYSTEMS = {'transmetro': 'Transmetro', 'tubus': 'TuBus', 'transurbano': 'Transurbano',
           'urbano': 'Urbano', 'extraurbano': 'Extraurbano'}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def point(value):
    return (isinstance(value, list) and len(value) == 2 and
            all(type(v) in (int, float) and math.isfinite(v) for v in value) and
            -180 <= value[0] <= 180 and -85 < value[1] < 85)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def refs(evidence, sources):
    require(isinstance(evidence, dict) and evidence.get('status') == 'verified', 'unverified_evidence')
    ids = evidence.get('sources')
    require(isinstance(ids, list) and ids and len(ids) == len(set(ids)) and
            all(ident in sources for ident in ids), 'missing_or_unknown_source')
    return ids


def service_system(service):
    # TuBus can share its operator with Transmetro: operator is NEVER consulted.
    ident = service['service_id']
    known = next((kind for kind in ('transmetro', 'tubus', 'transurbano')
                  if ident.startswith(kind + '-')), None)
    explicit = service.get('service_system')
    require(not known or explicit in (None, known), 'contradictory_service_system')
    result = known or explicit
    require(result in SYSTEMS, 'unknown_service_system')
    return result


def source_position(evidence, artifacts, service):
    name, source_id = evidence.get('artifact'), evidence.get('source_id')
    data = artifacts.get(name)
    require(data is not None, 'coordinate_artifact_missing')
    if name == 'municipal-gis.json':
        layer = next((row for row in data['layers'] if row['source_id'] == source_id), None)
        require(layer and layer.get('returned_coordinates', '').startswith('EPSG:4326;'), 'coordinate_crs_unknown')
        feature_id = evidence.get('feature_id')
        feature = next((row for row in layer['data']['features'] if row['id'] == feature_id), None)
        association = service.get('coordinates') or {}
        require(association.get('artifact') == name and association.get('layer_source_id') == source_id and
                feature_id in association.get('feature_ids', []), 'coordinate_service_membership_missing')
        require(feature and feature['geometry']['type'] == 'Point', 'not_a_stop_point')
        position = feature['geometry']['coordinates']
    elif name == 'osm-evidence.json':
        require(source_id == 'osm-snapshot', 'coordinate_source_mismatch')
        stop_id = evidence.get('stop_id')
        stop = next((row for row in data['stops'] if row['stop_id'] == stop_id), None)
        require(any(stop_id in seq.get('stops', []) for seq in service.get('stop_sequences') or []),
                'coordinate_service_membership_missing')
        require(stop and stop.get('crs') == 'EPSG:4326', 'coordinate_crs_unknown')
        position = stop['coordinates']
    else:
        raise ValueError('unsupported_coordinate_artifact')
    require(point(position), 'invalid_source_coordinates')
    return list(position)


def build_stop_display(catalog, sources, mapping, artifacts, network, identity, catalog_sha256, source_registry_sha256=None):
    """Pure adapter. Network paths are from the fingerprinted effective run, all modes."""
    result = dict(schema_version=SCHEMA, identity=dict(identity), available=False, records=[], issues=[],
                  catalog_sha256=catalog_sha256, review_date=catalog.get('review_date'),
                  scope='catalog_annotations_not_simulated_service_or_operational_authorization',
                  source_station_records=catalog.get('screening_summary', {}).get('station_records'),
                  counts={}, status='pending')
    if mapping is None:
        result['issues'].append(dict(reason='reviewed_stop_access_mapping_missing'))
    if catalog.get('domain', {}).get('approved') is not True:
        result['issues'].append(dict(reason='approved_domain_missing'))
    if result['issues']:
        return result
    require(mapping.get('schema_version') == SCHEMA and mapping.get('synthetic') is False, 'invalid_display_contract')
    require(mapping.get('catalog_sha256') == catalog_sha256, 'catalog_snapshot_changed')
    require(source_registry_sha256 and mapping.get('source_registry_sha256') == source_registry_sha256,
            'source_registry_snapshot_changed')
    require(mapping.get('network_sha256') == network['sha256'], 'effective_network_mismatch')
    date.fromisoformat(mapping['review_date'])
    domain = catalog['domain']
    require(domain.get('crs') == 'EPSG:4326', 'approved_domain_crs_missing')
    polygon = Polygon(domain.get('geometry'))
    allowed = set(domain.get('link_ids') or [])
    require(allowed and allowed <= network['links'].keys(), 'approved_directed_domain_links_missing')
    registry = {row['source_id']: row for row in sources['sources']}
    services = {row['service_id']: row for row in catalog['services']}
    records = mapping.get('stops')
    require(isinstance(records, list) and len(records) <= 2000, 'stop_mapping_size_invalid')
    ids = [row.get('stop_id') for row in records]
    require(all(text(ident) for ident in ids) and len(set(ids)) == len(ids), 'duplicate_or_missing_stop_id')
    for row in records:
        try:
            stop_id, name = row['stop_id'], row.get('name')
            require(text(name), 'stop_name_missing')
            access = row['access']
            source_ids = set(refs(access, registry))
            link_id = access['link_id']
            require(link_id in allowed, 'outside_approved_domain_link')
            link = network['links'][link_id]
            require(access.get('from_node') == link['from_node'] and access.get('to_node') == link['to_node'],
                    'directed_access_mismatch')
            require(access.get('placement') in ('roadside_platform', 'median_platform', 'terminal_bay'),
                    'platform_placement_unverified')
            require(text(access.get('direction')), 'access_direction_missing')
            index = access.get('path_segment_index')
            path = link['path']
            require(type(index) is int and 0 <= index < len(path)-1 and
                    point(path[index]) and point(path[index+1]), 'reviewed_access_segment_missing')
            a, b = path[index:index+2]
            dx, dy = (b[0]-a[0])*math.cos(math.radians(a[1])), b[1]-a[1]
            require(math.hypot(dx, dy) > 1e-12, 'access_segment_degenerate')
            memberships, position = [], None
            require(isinstance(row.get('services'), list) and row['services'], 'stop_services_missing')
            seen = set()
            for membership in row['services']:
                service_id = membership['service_id']
                require(service_id not in seen and service_id in services, 'unknown_or_duplicate_stop_service')
                seen.add(service_id)
                service = services[service_id]
                require(service.get('record_kind') in ('service_candidate', 'verified_service'), 'not_a_verified_service_record')
                require(service.get('verification', {}).get('field_status', {}).get('line', {}).get('status') == 'verified',
                        'service_line_unverified')
                cited = refs(membership, registry)
                require(set(cited) <= set(service['sources']) and text(membership.get('direction')),
                        'service_direction_evidence_missing')
                source_ids.update(cited)
                coordinate = membership['coordinate_evidence']
                require(coordinate.get('source_id') in registry, 'coordinate_source_missing')
                source_ids.add(coordinate['source_id'])
                candidate = source_position(coordinate, artifacts, service)
                require(position is None or candidate == position, 'different_platform_coordinates_cannot_be_merged')
                position = candidate
                kind = service_system(service)
                require(text(service.get('line')), 'service_line_missing')
                memberships.append(dict(service_id=service_id, system=kind, service=SYSTEMS[kind],
                                        line=service['line'], direction=membership['direction'],
                                        operator=service.get('operator')))
            require(polygon.contains(position, include_boundary=False), 'outside_approved_domain_position')
            transfer = row.get('transfer')
            if transfer is not None:
                source_ids.update(refs(transfer, registry))
                require(text(transfer.get('id')) and text(transfer.get('name')), 'transfer_identity_missing')
                transfer = dict(id=transfer['id'], name=transfer['name'])
            opposed = row.get('opposed_stop_ids', [])
            require(isinstance(opposed, list) and all(ident in ids and ident != stop_id for ident in opposed),
                    'opposed_stop_reference_invalid')
            if opposed:
                source_ids.update(refs(row.get('opposed_evidence'), registry))
            result['records'].append(dict(transit_stop=True, stop_id=stop_id, name=name, position=position,
                Link_ID=link_id, from_node=access['from_node'], to_node=access['to_node'],
                direction=access['direction'], bearing_degrees=math.degrees(math.atan2(dx, dy)) % 360,
                services=memberships, transfer=transfer, opposed_stop_ids=opposed,
                sources=[dict(source_id=ident, url=registry[ident]['url'],
                              license=registry[ident].get('license'), accessed_on=registry[ident].get('accessed_on'))
                         for ident in sorted(source_ids)], review_date=mapping['review_date']))
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            result['issues'].append(dict(stop_id=row.get('stop_id'), reason=str(error)))
    result.update(available=True, status='ready' if result['records'] else 'no_eligible_stops',
                  network_sha256=network['sha256'], source_registry_sha256=source_registry_sha256,
                  mapping_review_date=mapping['review_date'],
                  counts=dict(candidates=len(records), accepted=len(result['records']), rejected=len(result['issues']),
                              reasons=dict(Counter(item['reason'] for item in result['issues']))))
    return result


def read_json(path, maximum=2_000_000):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum+1)
    require(len(raw) <= maximum, 'stop_evidence_file_too_large')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def transit_usage(directory, run, identity):
    """Small fingerprinted config only. Never infer native usage from a catalog."""
    from simz1_run import checked_path, parameters
    try:
        require(run.get('run_id') == identity['run_id'] and
                run.get('validation', {}).get('status') == 'valid', 'run_identity_unverified')
        config = parameters(checked_path(Path(directory).resolve(), run['effective_config']))
        enabled = config.get('transit.useTransit')
        require(enabled in ('true', 'false'), 'transit_configuration_missing')
        return dict(status='not_configured' if enabled == 'false' else 'usage_not_established',
                    used_by_simulation=False if enabled == 'false' else None,
                    effective_config_sha256=run['effective_config']['sha256'])
    except (KeyError, ValueError, OSError, ET.ParseError) as error:
        return dict(status='unknown', used_by_simulation=None, reason=str(error))


def build_catalog_annotations(catalog, sources, mapping, artifacts, identity, catalog_hash, source_hash):
    """Exact source platforms with source-specific directions, WITHOUT native links.

    The download rectangle is never treated as an approved transit domain.
    Review pairs named municipal stations with OSM platforms; proximity alone
    cannot create a membership. The 25 m consistency limit rejects conflicts,
    and never snaps, averages or relocates either source's coordinates.
    """
    require(mapping.get('schema_version') == CATALOG_SCHEMA and mapping.get('synthetic') is False,
            'invalid_catalog_annotation_contract')
    require(mapping.get('catalog_sha256') == catalog_hash, 'catalog_snapshot_changed')
    require(mapping.get('source_registry_sha256') == source_hash, 'source_registry_snapshot_changed')
    date.fromisoformat(mapping['review_date'])
    registry = {row['source_id']: row for row in sources['sources']}
    services = {row['service_id']: row for row in catalog['services']}
    osm = artifacts['osm-evidence.json']
    platforms = {row['stop_id']: row for row in osm['stops']}
    routes = {row['relation_id']: row for row in osm['routes']}
    rows = mapping.get('stops')
    require(isinstance(rows, list) and len(rows) <= 2000, 'stop_mapping_size_invalid')
    ids = [row.get('stop_id') for row in rows]
    require(all(text(ident) for ident in ids) and len(set(ids)) == len(ids), 'duplicate_or_missing_stop_id')
    records, issues = [], []
    for row in rows:
        try:
            stop_id = row['stop_id']
            platform = platforms.get(stop_id)
            require(platform and platform.get('tags', {}).get('public_transport') == 'platform',
                    'source_platform_missing')
            require(text(row.get('name')), 'stop_name_missing')
            members, source_ids, seen = [], {'osm-snapshot'}, set()
            require(isinstance(row.get('services'), list) and row['services'], 'stop_services_missing')
            for member in row['services']:
                ident = member['service_id']
                require(ident in services and ident not in seen, 'unknown_or_duplicate_stop_service')
                seen.add(ident)
                service = services[ident]
                fields = service.get('verification', {}).get('field_status', {})
                require(service.get('record_kind') in ('service_candidate', 'verified_service') and
                        all(fields.get(key, {}).get('status') == 'verified' for key in ('line', 'operator')),
                        'service_identity_unverified')
                cited = refs(member.get('official_stop_evidence'), registry)
                require(set(cited) <= set(service['sources']) and
                        all(registry[key].get('kind') in ('municipal_article', 'municipal_open_data') for key in cited),
                        'official_stop_evidence_missing')
                require(text(member.get('review_note')), 'stop_identity_review_missing')
                source_ids.update(cited)
                position = source_position(dict(artifact='osm-evidence.json', source_id='osm-snapshot',
                                                stop_id=stop_id), artifacts, service)
                kind = service_system(service)
                require(platform['tags'].get('network') == SYSTEMS[kind], 'platform_service_system_mismatch')
                corroboration = member.get('municipal_feature_id')
                separation = None
                if kind == 'transmetro':
                    municipal = source_position(dict(artifact='municipal-gis.json', source_id='transmetro-stations-gis',
                                                     feature_id=corroboration), artifacts, service)
                    separation = math.hypot((position[0]-municipal[0])*111320*math.cos(math.radians(position[1])),
                                            (position[1]-municipal[1])*110574)
                    require(separation <= 25, 'municipal_osm_position_conflict')
                    source_ids.add('transmetro-stations-gis')
                relation_ids = member.get('relation_ids')
                require(isinstance(relation_ids, list) and relation_ids and len(set(relation_ids)) == len(relation_ids),
                        'source_direction_missing')
                directions = []
                for ident in relation_ids:
                    route = routes.get(ident)
                    sequence = next((seq for seq in service.get('stop_sequences') or [] if seq['relation_id'] == ident), None)
                    require(route and sequence and stop_id in sequence['stops'] and
                            route.get('line') == member.get('osm_line', service['line']) and
                            any(item['stop_id'] == stop_id and item['role'].startswith('platform')
                                for item in route['stop_sequence']) and
                            text(route.get('from_stop')) and text(route.get('to_stop')) and
                            sequence.get('from') == route['from_stop'] and sequence.get('to') == route['to_stop'] and
                            sequence.get('relation_version') == route['version'], 'source_direction_mismatch')
                    directions.append(dict(relation_id=ident, version=route['version'], timestamp=route['timestamp'],
                                           origin=route['from_stop'], destination=route['to_stop']))
                members.append(dict(service_id=service['service_id'], system=kind, service=SYSTEMS[kind],
                                    line=service['line'], operator=service['operator'],
                                    direction=' / '.join(d['origin']+' → '+d['destination'] for d in directions),
                                    direction_scope='osm_relation_snapshot_not_native_access', directions=directions,
                                    municipal_separation_m=round(separation, 2) if separation is not None else None))
            transfer = row.get('transfer')
            if transfer:
                cited = refs(transfer, registry)
                require(len(members) > 1 and text(transfer.get('id')) and text(transfer.get('name')) and
                        all(registry[key].get('kind') == 'municipal_article' for key in cited), 'transfer_evidence_missing')
                source_ids.update(cited)
                transfer = dict(id=transfer['id'], name=transfer['name'])
            records.append(dict(transit_stop=True, stop_id=stop_id, name=row['name'], position=position,
                annotation_kind='catalog_only', native_access_status='unmapped',
                operational_validity='not_confirmed_for_replay_date',
                coordinate_evidence=dict(source_id='osm-snapshot', element=stop_id,
                                         version=platform['version'], timestamp=platform['timestamp']),
                services=members, transfer=transfer, opposed_stop_ids=[], review_date=mapping['review_date'],
                sources=[dict(source_id=key, url=registry[key]['url'], published_on=registry[key].get('published_on'),
                              accessed_on=registry[key].get('accessed_on'), license=registry[key].get('license'))
                         for key in sorted(source_ids)]))
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            issues.append(dict(stop_id=row.get('stop_id'), reason=str(error)))
    return dict(schema_version=SCHEMA, identity=dict(identity), available=True, status='catalog_annotations',
                scope='catalog_annotations_not_simulated_service_or_operational_authorization',
                records=records, issues=issues, pending=mapping.get('pending', []),
                catalog_sha256=catalog_hash, source_registry_sha256=source_hash, review_date=mapping['review_date'],
                source_station_records=catalog.get('screening_summary', {}).get('station_records'),
                counts=dict(candidates=len(rows), accepted=len(records), rejected=len(issues)))


def effective_network(directory, run, identity):
    # Includes dedicated bus links omitted from the road-body/lane renderer.
    from pyproj import Transformer
    from simz1_run import checked_path, parameters
    from simz1_visual_lanes import _xml, _path
    require(run['run_id'] == identity['run_id'] and run['validation']['status'] == 'valid', 'run_identity_mismatch')
    config = parameters(checked_path(directory, run['effective_config']))
    require(config.get('global.coordinateSystem') == 'EPSG:32615', 'effective_network_crs_unknown')
    record = run['results'][str(identity['iteration'])]['network']
    root = _xml(checked_path(directory, record))
    transform = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True).transform
    nodes = {row.get('id'): list(transform(float(row.get('x')), float(row.get('y')), errcheck=True))
             for row in root.findall('nodes/node')}
    links = {}
    for row in root.findall('links/link'):
        entry = dict(from_node=row.get('from'), to_node=row.get('to'), path=[])
        links[row.get('id')] = entry
        if not {'car', 'bus'} & set(row.get('modes', 'car').split(',')):
            continue
        metadata = {item.get('name'): item.text for item in row.findall('attributes/attribute')}
        path, _, valid = _path(metadata, nodes[row.get('from')], nodes[row.get('to')],
                              lambda x, y: list(transform(x, y, errcheck=True)))
        if valid:
            entry['path'] = path
    return dict(sha256=record['sha256'], links=links)



def load_weekday_stops(directory, run, identity):
    """Native stops of this run, not source catalog candidates. Gateways are hidden."""
    from simz1_run import checked_path
    from simz1_transit_events import _attributes
    from simz1_weekday_transit import verify_policy_chain
    record=run.get('inputs',{}).get('transit_schedule')
    if record is None: return None
    path=checked_path(Path(directory),record)
    schedule=ET.parse(path).getroot()
    meta=_attributes(schedule)
    if meta.get('simz1:purpose')!='weekday_scenario_v2': return None
    policy,bundle=verify_policy_chain(path,meta,run['counts']['planned_persons'])
    network=effective_network(directory,run,identity)
    records=[]
    for facility in schedule.findall('./{*}transitStops/{*}stopFacility'):
        a=_attributes(facility)
        if a.get('simz1:stopRole')=='gateway': continue
        require(a.get('simz1:stopRole')=='passenger_stop','unknown_native_stop_role')
        link=network['links'].get(facility.get('linkRefId'))
        require(link and len(link['path'])>=2, 'native_stop_link_without_geometry')
        has_source='simz1:sourceLongitude' in a and 'simz1:sourceLatitude' in a
        # Never invent a surveyed platform coordinate. Link endpoint is a labeled proxy.
        original_position=[float(a['simz1:sourceLongitude']),float(a['simz1:sourceLatitude'])] if has_source else list(link['path'][-1])
        position=original_position
        proxy=json.loads(a['simz1:stopProxy']) if a.get('simz1:stopProxy') else None
        if proxy is not None:
            fraction=proxy['modeled_front_fraction']
            require(proxy['policy']=='body_before_conflict_proxy_v1' and proxy['modeled_link_id']==facility.get('linkRefId') and
                    type(fraction) in (int,float) and math.isfinite(fraction) and 0<=fraction<=1,'invalid_native_stop_proxy')
            segments=[math.hypot((b[0]-a[0])*math.cos(math.radians((a[1]+b[1])/2)),b[1]-a[1])
                      for a,b in zip(link['path'],link['path'][1:])]
            remaining=sum(segments)*fraction
            for start,end,length in zip(link['path'],link['path'][1:],segments):
                if remaining<=length and length>0:
                    position=[start[i]+(end[i]-start[i])*remaining/length for i in (0,1)];break
                remaining-=length
        require(point(position),'invalid_native_stop_position')
        x,y=link['path'][-2:]
        bearing=math.degrees(math.atan2((y[0]-x[0])*math.cos(math.radians(y[1])),y[1]-x[1]))%360
        system=a['simz1:serviceSystem']; require(system in SYSTEMS,'unknown_native_stop_system')
        records.append(dict(transit_stop=True,stop_id=facility.get('id'),name=facility.get('name'),
            position=position,Link_ID=facility.get('linkRefId'),bearing_degrees=bearing,
            direction=a['simz1:serviceDirection'],annotation_kind='native_weekday_scenario_stop',
            native_access_status='mapped_to_fingerprinted_native_schedule',
            operational_validity='scenario_assumption_not_current_operator_certification',
            coordinate_evidence=dict(source_id=a['simz1:source'],basis=a['simz1:placementBasis'],
                native_stop_position='body_before_conflict_queue_proxy' if proxy else 'link_endpoint_proxy',
                source_position_available=has_source, source_position=original_position if has_source else None,
                **({'proxy':proxy} if proxy else {})),
            services=[dict(service_id=a['simz1:serviceId'],system=system,service=SYSTEMS[system],
                line=a['simz1:serviceLine'],operator=SYSTEMS[system],direction=a['simz1:serviceDirection'])],
            sources=[dict(source_id=a['simz1:source'],schedule_sha256=record['sha256'])],
            simulation_usage=dict(enabled=True,scope='weekday_scenario_v2',service_date=policy['service_date'])))
    return dict(schema_version=SCHEMA,identity=dict(identity),available=True,status='native_weekday_scenario',
        scope='configured_native_stops; not administrative domain or current timetable certification',
        records=records,issues=[],pending=bundle.get('unmapped_stop_evidence',[]),
        mapping_sha256=record['sha256'],network_sha256=network['sha256'],
        counts=dict(accepted=len(records)),simulation_usage=dict(enabled=True,scope='weekday_scenario_v2'))


def load_stop_display(directory, run, identity, catalog_directory=DEFAULT_DIRECTORY):
    """Called once at continuous server construction; never writes historical config."""
    try:
        weekday = load_weekday_stops(directory, run, identity)
        if weekday is not None:
            return weekday
        root = Path(catalog_directory)
        catalog, catalog_hash = read_json(root/'catalog.json')
        mapping_path = root/'stop-display.json'
        mapping, mapping_hash = read_json(mapping_path) if mapping_path.is_file() else (None, None)
        annotation_path = root/'catalog-display.json'
        native_ready = mapping is not None and catalog.get('domain', {}).get('approved') is True
        if not native_ready and not annotation_path.is_file():
            return build_stop_display(catalog, {}, mapping, {}, {}, identity, catalog_hash)
        sources, source_hash = read_json(root/'sources.json')
        artifacts = {}
        for record in catalog['artifacts']:
            require(record['path'] in ('municipal-gis.json', 'osm-evidence.json'), 'unknown_coordinate_artifact')
            data, digest = read_json(root/record['path'])
            require(digest == record['sha256'], 'coordinate_artifact_hash_mismatch')
            artifacts[record['path']] = data
        if not native_ready:
            annotation, annotation_hash = read_json(annotation_path)
            result = build_catalog_annotations(catalog, sources, annotation, artifacts, identity, catalog_hash, source_hash)
            result['mapping_sha256'] = annotation_hash
            result['native_mapping_issues'] = build_stop_display(catalog, {}, mapping, {}, {}, identity, catalog_hash)['issues']
        else:
            result = build_stop_display(catalog, sources, mapping, artifacts,
                                        effective_network(directory, run, identity), identity, catalog_hash, source_hash)
            result['mapping_sha256'] = mapping_hash
        result['simulation_usage'] = transit_usage(directory, run, identity)
        for record in result['records']:
            record['simulation_usage'] = result['simulation_usage']
        return result
    except (KeyError, ValueError, TypeError, AttributeError, OSError, RuntimeError, OverflowError, ET.ParseError) as error:
        return dict(schema_version=SCHEMA, identity=dict(identity), available=False, records=[],
                    status='invalid_stop_evidence', issues=[dict(reason=str(error))])
