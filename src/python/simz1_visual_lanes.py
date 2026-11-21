"""Read-only visual lane metadata from hashed effective SimZ1 artifacts.

Indices describe the reviewed parallel-queue alignment, not measured lateral
positions. The shared upstream queue never identifies one physical lane.
"""
from collections import defaultdict
import gzip
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

IDENTITY_KEYS = ('run_id', 'iteration', 'run_manifest_sha256')
NOMINAL_WIDTH_M = 3.0
ROAD_TAGS = ('oneway', 'lanes', 'lanes:forward', 'lanes:backward', 'lanes:both_ways',
             'highway', 'motorcar', 'motor_vehicle', 'vehicle', 'access',
             'bridge', 'tunnel', 'layer', 'width', 'name')


def visual_landmarks(facilities, transform):
    """Small context selection from recorded OSM nodes, never proxy centroids."""
    useful = re.compile(r'\b(museo|catedral|palacio|biblioteca|teatro|mercado|parque|hospital)\b', re.I)
    rows = []
    for facility in facilities.findall('facility'):
        ident = facility.get('id', '')
        tags = {a.get('name'): a.text for a in facility.findall('attributes/attribute')}
        name = (tags.get('name') or '').strip()
        if (not ident.startswith('osm_node_') or not useful.search(name) or
                not (tags.get('source') or '').startswith('OSM activity proxy')):
            continue
        x, y = _number(facility.get('x')), _number(facility.get('y'))
        position = _position(x, y, transform) if x is not None and y is not None else None
        if position is not None:
            rows.append(dict(id=ident, name=name, position=position, source='recorded_osm_node'))
    return sorted(rows, key=lambda row: (row['name'], row['id']))[:24]


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _xml(path):
    with (gzip.open(path, 'rb') if Path(path).suffix == '.gz' else Path(path).open('rb')) as stream:
        root = ET.parse(stream).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    return root


def _width(value):
    # Only unambiguous metres; ranges, feet, lane lists and unknown units stay estimates.
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:m)?\s*', value or '')
    width = _number(match[1]) if match else None
    return width if width is not None and width > 0 else None


def _position(x, y, transform):
    try:
        raw = transform(x, y)
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            return None
        point = [_number(value) for value in raw]
        return point if all(value is not None for value in point) and -180 <= point[0] <= 180 and -90 <= point[1] <= 90 else None
    except (ValueError, TypeError, RuntimeError, OverflowError):
        return None


def _path(metadata, start, end, transform):
    """MATSim 15 NetworkUtils.ORIG_GEOM stores ordered intermediate id,x,y nodes."""
    original = metadata.get('origgeom')
    geometry = metadata.get('geometry')
    if not original and not geometry:
        return [start, end], 'effective_link_chord', True
    try:
        if original:
            parts = [point.split(',') for point in original.split()]
            if any(len(point) != 3 for point in parts):
                raise ValueError('origgeom invalido')
            points = [start] + [list(transform(float(point[1]), float(point[2]))) for point in parts] + [end]
            source = 'effective_origgeom'
        else:
            match = re.fullmatch(r'\s*LINESTRING\s*\(([^()]+)\)\s*', geometry, re.IGNORECASE)
            if not match:
                raise ValueError('geometry no reconocida')
            pairs = [point.split() for point in match[1].split(',')]
            if any(len(point) != 2 for point in pairs):
                raise ValueError('geometry invalida')
            points = [list(transform(float(point[0]), float(point[1]))) for point in pairs]
            if not points or any(not math.isclose(a, b, abs_tol=1e-8, rel_tol=0)
                                 for actual, expected in ((points[0], start), (points[-1], end))
                                 for a, b in zip(actual, expected)):
                raise ValueError('geometry tiene direccion incompatible')
            source = 'effective_geometry_wkt'
        if any(len(point) != 2 or any(_number(value) is None for value in point) or
               not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90 for point in points):
            raise ValueError('Coordenadas invalidas')
        points = [point for index, point in enumerate(points) if index == 0 or point != points[index-1]]
        if len(points) < 2:
            raise ValueError('Geometria vacia')
        return points, source, True
    except (ValueError, TypeError, RuntimeError, OverflowError):
        return [start, end], 'effective_link_chord_invalid_geometry', False


def _native_lanes(assignment, link, links, modes=('car',)):
    lanes = {}
    try:
        for lane in assignment.findall('lane'):
            ident = lane.get('id')
            start = _number(lane.find('startsAt').get('meterFromLinkEnd'))
            represented = _number(lane.find('representedLanes').get('number'))
            alignment = _number(lane.findtext('alignment'))
            if (not ident or ident in lanes or start is None or not 0 < start <= link['length_m'] or
                    represented is None or represented <= 0 or alignment is None):
                return {}
            lanes[ident] = dict(index=None, represented_lanes=represented, start_m=start,
                               alignment=alignment,
                               to_lanes=[e.get('refId') for e in lane.findall('leadsTo/toLane')],
                               to_links=[e.get('refId') for e in lane.findall('leadsTo/toLink')])
    except AttributeError:
        return {}
    count = link['num_lanes']
    upstream = [(ident, lane) for ident, lane in lanes.items() if lane['to_lanes']]
    terminal = sorted(((ident, lane) for ident, lane in lanes.items() if not lane['to_lanes']),
                      key=lambda item: item[1]['alignment'])
    if len(upstream) != 1 or len(terminal) != count:
        return {}
    _, original = upstream[0]
    if (original['represented_lanes'] != count or original['alignment'] != 0 or
            not math.isclose(original['start_m'], link['length_m']) or original['to_links'] or
            len(original['to_lanes']) != count or set(original['to_lanes']) != {key for key, _ in terminal}):
        return {}
    starts = {lane['start_m'] for _, lane in terminal}
    if len(starts) != 1 or not 0 < next(iter(starts)) < link['length_m']:
        return {}
    for index, (_, lane) in enumerate(terminal):
        exits = lane['to_links']
        if (lane['represented_lanes'] != 1 or lane['alignment'] != 2 * index - (count - 1) or
                not exits or len(exits) != len(set(exits)) or any(
                    ident not in links or links[ident].get('from') != link['to_node'] or
                    not set(modes).intersection(links[ident].get('modes', 'car').split(',')) for ident in exits)):
            return {}
        lane['index'] = index
    # Distinct terminal destinations encode native turn permissions, not extra
    # physical lanes. Keep them without inventing movements at visual crossings.
    return {ident: {key: lane[key] for key in ('index', 'represented_lanes', 'start_m', 'to_links', 'to_lanes')}
            for ident, lane in lanes.items()}


def visual_lane_metadata(network, lanes, transform, identity, *, modes=('car',)):
    """Build bounded geometry metadata; transform follows the current viewer CRS."""
    nodes, raw, links = {}, {}, {}
    by_endpoints = defaultdict(list)
    for node in network.findall('nodes/node'):
        ident = node.get('id')
        if not ident or ident in nodes:
            raise ValueError('Nodo visual ausente o duplicado')
        x, y = _number(node.get('x')), _number(node.get('y'))
        nodes[ident] = _position(x, y, transform) if x is not None and y is not None else None
    for element in network.findall('links/link'):
        ident = element.get('id')
        if not ident or ident in raw:
            raise ValueError('Link visual ausente o duplicado')
        record = dict(element.attrib)
        record['metadata'] = {e.get('name'): e.text for e in element.findall('attributes/attribute')}
        raw[ident] = record
        if set(modes).intersection(record.get('modes', 'car').split(',')):
            by_endpoints[record.get('from'), record.get('to')].append(ident)
        count, length = _number(record.get('permlanes')), _number(record.get('length'))
        start, end = nodes.get(record.get('from')), nodes.get(record.get('to'))
        if (length is None or length <= 0 or start is None or end is None or start == end or
                not set(modes).intersection(record.get('modes', 'car').split(','))):
            continue  # No trustworthy road geometry is available for this link.
        count = int(count) if count is not None and count >= 1 and count.is_integer() else None
        path, geometry_source, geometry_valid = _path(record['metadata'], start, end,
                                                      lambda x, y: _position(x, y, transform))
        links[ident] = dict(num_lanes=count, path=path, geometry_source=geometry_source, length_m=length,
                            from_node=record['from'], to_node=record['to'], native_lanes={},
                            source_way=record.get('origid') or record['metadata'].get('origid') or record['metadata'].get('osm:way'),
                            reverse_link=None, opposing_lanes=0, offset_eligible=count is not None and geometry_valid,
                            lane_width_m=NOMINAL_WIDTH_M, width_source='nominal_visual_estimate',
                            lane_count_source='effective_network_permlanes',
                            lane_import_source=record['metadata'].get('physical:lanesSource'),
                            osm_tags={key: record['metadata']['osm:'+key] for key in ROAD_TAGS
                                      if 'osm:'+key in record['metadata']},
                            missing_osm_tags=[key for key in ROAD_TAGS if 'osm:'+key not in record['metadata']],
                            pairing='unpaired_directed_link')
    # Eligibility must be independent of XML link order.
    initial_eligible = {ident: link['offset_eligible'] for ident, link in links.items()}
    for ident, link in links.items():
        record = raw[ident]
        opposite = by_endpoints.get((record['to'], record['from']), [])
        same = by_endpoints[record['from'], record['to']]
        if opposite:
            origin = record.get('origid') or record['metadata'].get('origid') or record['metadata'].get('osm:way')
            if (len(opposite) != 1 or len(same) != 1 or not origin or opposite[0] not in links or
                    not initial_eligible[opposite[0]] or not initial_eligible[ident] or
                    link['path'] != list(reversed(links[opposite[0]]['path'])) or
                    any(link['osm_tags'].get(key) != links[opposite[0]]['osm_tags'].get(key)
                        for key in ('bridge', 'tunnel', 'layer')) or
                    origin != (raw[opposite[0]].get('origid') or raw[opposite[0]]['metadata'].get('origid') or
                               raw[opposite[0]]['metadata'].get('osm:way'))):
                link['offset_eligible'] = False
                link['pairing'] = 'ambiguous_reverse_centerline'
                continue
            link['reverse_link'] = opposite[0]
            link['opposing_lanes'] = links[opposite[0]]['num_lanes']
            link['pairing'] = 'shared_axis_reverse_pair'
        width = _width(record['metadata'].get('osm:width'))
        other = _width(raw[link['reverse_link']]['metadata'].get('osm:width')) if link['reverse_link'] else None
        if width is not None and other is not None and not math.isclose(width, other):
            link['lane_width_m'] = min(width, other) / (link['num_lanes'] + link['opposing_lanes'])
            link['width_source'] = 'osm:width_conservative_conflict'
        elif link['num_lanes'] is not None and (width is not None or other is not None):
            # A paired road uses one total width for both directions, including
            # the case where only one serialized link retains the source tag.
            width = min(width, other) if width is not None and other is not None else width or other
            link['lane_width_m'] = width / (link['num_lanes'] + link['opposing_lanes'])
            link['width_source'] = 'osm:width_per_directional_lane'
    assignments = set()
    if lanes is not None:
        for assignment in lanes.findall('lanesToLinkAssignment'):
            ident = assignment.get('linkIdRef')
            if ident in assignments:
                raise ValueError('Asignacion de carriles visuales duplicada')
            assignments.add(ident)
            if ident in links and links[ident]['num_lanes'] is not None:
                links[ident]['native_lanes'] = _native_lanes(assignment, links[ident], raw,
                    set(modes).intersection(raw[ident].get('modes', 'car').split(',')))
    outgoing = defaultdict(list)
    for ident, record in raw.items():
        if set(modes).intersection(record.get('modes', 'car').split(',')):
            outgoing[record.get('from')].append(ident)
    for ident, link in links.items():
        if ident in assignments:
            link['movement_source'] = 'effective_lane_definitions' if link['native_lanes'] else 'unavailable_lane_mapping'
            link['allowed_to_links'] = sorted({target for lane in link['native_lanes'].values()
                                              for target in lane['to_links']}) if link['native_lanes'] else None
        else:
            link['movement_source'] = 'effective_car_node_adjacency' if modes == ('car',) else 'effective_mode_node_adjacency'
            link['allowed_to_links'] = sorted(target for target in outgoing[link['to_node']] if
                set(modes).intersection(raw[ident].get('modes', 'car').split(','), raw[target].get('modes', 'car').split(',')))
    return dict(schema_version=1, identity={key: identity[key] for key in IDENTITY_KEYS}, available=bool(links),
                lane_width_m=NOMINAL_WIDTH_M, start_reference='link_end', links=links,
                omitted_links=len(raw)-len(links),
                note='Separacion lateral solo visual; ancho nominal estimado de 3 m si no hay ancho OSM valido. '
                     'Anchos discordantes usan el menor declarado como estimacion conservadora. '
                     'Sin geometria curva efectiva, se aproxima por la cuerda entre nodos del link. '
                     'No describe posiciones laterales medidas ni modifica QSim.')


def load_visual_lanes(directory, run, identity):
    """A missing or changed artifact disables offsets, never substitutes master inputs."""
    empty = dict(schema_version=1, identity={key: identity[key] for key in IDENTITY_KEYS},
                 available=False, lane_width_m=NOMINAL_WIDTH_M, start_reference='link_end', links={})
    try:
        from pyproj import Transformer
        from simz1_run import checked_path, parameters
        if (run.get('run_id') != identity['run_id'] or run.get('status') != 'completed' or
                run.get('validation', {}).get('status') != 'valid'):
            raise ValueError('Identidad de corrida incompatible')
        result = run['results'][str(identity['iteration'])]
        directory = Path(directory).resolve()
        config_path = checked_path(directory, run['effective_config'])
        effective = parameters(config_path)
        if effective.get('global.coordinateSystem') != 'EPSG:32615':
            raise ValueError('Proyeccion efectiva incompatible con el visor actual')
        network_path = checked_path(directory, result['network'])
        loaded = run.get('effective_lane_configuration_validation', {}).get('loaded_artifacts', {})
        if 'network' in loaded and loaded['network']['sha256'] != result['network']['sha256']:
            raise ValueError('Red efectiva incompatible con la iteracion')
        use_lanes = effective.get('qsim.useLanes')
        if use_lanes not in ('true', 'false'):
            raise ValueError('Uso efectivo de carriles sin respaldo')
        lane_path = checked_path(directory, loaded['lanes']) if use_lanes == 'true' else None
        transformer = Transformer.from_crs('EPSG:32615', 'EPSG:4326', always_xy=True)
        metadata = visual_lane_metadata(_xml(network_path), _xml(lane_path) if lane_path else None,
            lambda x, y: transformer.transform(x, y, errcheck=True), identity,
            modes=('car', 'bus') if run.get('public_transport', {}).get('enabled') is True else ('car',))
        metadata['native_lanes_enabled'] = use_lanes == 'true'
        metadata['whole_vehicle_reservation'] = effective.get('simz1Admission.wholeVehicleReservation') == 'true'
        occupancy = result.get('corridor_occupancy', {})
        if metadata['whole_vehicle_reservation']:
            if occupancy.get('status') != 'verified_native_aggregate_ledger' or occupancy.get('geometry', {}).get('schema') != 'corridor-length-v1':
                raise ValueError('Reserva fisica sin geometria/eventos nativos validados')
            metadata['occupancy_corridors'] = occupancy['geometry']
        metadata['sources'] = dict(network_sha256=result['network']['sha256'],
                                  configuration_sha256=run['effective_config']['sha256'],
                                  lanes_sha256=loaded['lanes']['sha256'] if lane_path else None)
        # Optional context is independently checked and stays in memory. A
        # missing/changed facilities input cannot substitute today's map.osm.
        metadata['landmarks'] = []
        metadata['landmarks_note'] = 'Sin referencias verificables de nodos OSM en las instalaciones de esta corrida.'
        facilities = run.get('inputs', {}).get('input:facilities-inputFacilitiesFile.xml')
        if facilities:
            try:
                metadata['landmarks'] = visual_landmarks(_xml(checked_path(directory, facilities)),
                    lambda x, y: transformer.transform(x, y, errcheck=True))
                metadata['sources']['landmarks_sha256'] = facilities['sha256']
                if metadata['landmarks']:
                    metadata['landmarks_note'] = 'Nodos OSM del insumo guardado; contexto aproximado, no cartografia GIS verificada.'
            except (KeyError, ValueError, TypeError, RuntimeError, OSError, ET.ParseError):
                pass
        return metadata
    except (KeyError, ValueError, TypeError, RuntimeError, OSError, ET.ParseError) as exc:
        return dict(empty, reason=f'Metadatos efectivos no verificables: {exc}')
