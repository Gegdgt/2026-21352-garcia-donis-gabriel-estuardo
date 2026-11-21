"""Build compact freight from explicit multicarril source evidence, without QSim.

Pins the original OSM/network/lane bytes, preserves weekday-v2, and emits a
per-link road audit. No source lanes, widths, speeds or capacities are changed.
"""
import argparse
from collections import Counter, defaultdict, deque
import csv
import heapq
import json
import os
from pathlib import Path
import unicodedata
import xml.etree.ElementTree as ET

from simz1_freight import INDEPENDENT_BODY_CONTRACT, validate_through_config
from simz1_freight_multilane import POLICY, TAGGING_SOURCES, directional_lane_evidence
from simz1_freight_gateways import POLICY as NATIVE_GATEWAY_POLICY
from simz1_freight_routes import load_context, link_rejection, turn_rejection, validate_bundle, _inside, _gateway
from simz1_run import sha256

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'scenarios/zona1'
VERSION = 'weekday-compact-v3'
CORRIDORS = {
    'Avenida Elena': 'Anillo Periferico a Avenida Bolivar',
    'Avenida Bolivar': 'Acceso Aguilar Batres hacia 18-24 calle',
    '20 Calle': 'Bolivar a Avenida Elena',
    '24 Calle': 'Avenida Bolivar hacia zona 5',
    '6a Avenida': 'Calle Marti hacia el sur',
    '7a Avenida': 'Calle Marti hacia el sur',
    '8a Calle': 'Avenida Elena a 12 avenida',
    '9a Calle': 'Avenida Elena a 12 avenida',
    '10a Avenida': 'Calle Marti hacia zona 4',
    '11 Avenida': 'Calle Marti hacia zona 4',
}
# Three genuine opposite-side traversals and the independently available
# Elena -> north corridor. No verified west -> east exit exists in this source
# graph. These fixed synthetic routes are assumptions, not observed OD shares.
GATEWAYS = {
    'south-north-7avenida': ('osm_1467361288_0_forward', 'osm_1057741805_1_forward'),
    'north-south-2avenida': ('osm_65777805_24_forward', 'osm_762765906_3_forward'),
    'east-west-14calle': ('osm_64401484_2_forward', 'osm_384737905_41_forward'),
    'west-north-elena': ('osm_406654687_6_forward', 'osm_30279769_61_forward'),
}
EXTERNAL_ANCHORS = {
    'south-north-7avenida': ([], ['osm_1057741805_2_forward']),
    'north-south-2avenida': ([], ['osm_762765906_4_forward']),
    'east-west-14calle': ([], ['osm_384737905_42_forward']),
    'west-north-elena': (['osm_406654687_4_forward', 'osm_406654687_5_forward'], ['osm_30279769_62_forward']),
}


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)).lower()


def service_definition(source):
    service = json.loads(Path(source).read_text(encoding='utf-8'))
    service.update(service_version=VERSION, route_policy=POLICY, length_m=8.0, width_m=2.3,
        native_gateway_policy=NATIVE_GATEWAY_POLICY,
        outside_policy='Only bounded existing external activity anchors; actual perimeter crossing and whole body clearance are audited from native occupancy events.',
        body_contract=INDEPENDENT_BODY_CONTRACT,
        visual_size_policy='Saved 8.0 x 2.3 m freight body shared by native VehicleType and replay; independent of buses; user-defined scenario geometry, not a measurement.',
        route_access_basis='Every directed link requires explicit source-backed >1 usable motorised lane; no inferred lanes and no single-lane perimeter exception. OSM evidence, not surveyed clearance or legal certification.',
        route_preservation_basis='weekday-v2 remains historical. New shortest-distance routes use only verified directional multicarril links and native/OSM permitted turns.',
        corner_preference='Three opposite-side routes plus the verified Avenida Elena to north corridor. No unsupported west-to-east route is invented.',
        route_distribution_basis='Synthetic equal route quotas over four declared through routes; not measured freight OD shares.',
        dimension_change_basis='User-requested length 12 -> 8.0 m and width 2.5 -> 2.3 m only. PCU 3.5, weight 12 t, speed 40 km/h, dispatch, windows, clearance margin and network capacities preserved.')
    return service


def graph(ctx, service):
    reasons = {k: link_rejection(ctx, k, service) for k in ctx['links']}
    eligible = {k for k, reason in reasons.items() if reason is None}
    outgoing = defaultdict(list)
    all_outgoing = defaultdict(list)
    for ident, link in sorted(ctx['links'].items()):
        all_outgoing[link['from']].append(ident)
        if ident in eligible:
            outgoing[link['from']].append(ident)
    return eligible, outgoing, all_outgoing, reasons


def shortest_route(ctx, start, end, eligible, outgoing, service):
    if start not in eligible or end not in eligible:
        raise ValueError('Unverified freight gateway: '+str((start, end)))
    queue = [(ctx['links'][start]['length'], (start,))]
    visited = set()
    while queue:
        distance, path = heapq.heappop(queue)
        source = path[-1]
        if source in visited:
            continue
        visited.add(source)
        if source == end:
            return list(path)
        # Do not leave/reenter the model to manufacture a connection.
        if not _inside(ctx, ctx['links'][source]['to']):
            continue
        for target in outgoing[ctx['links'][source]['to']]:
            if target not in visited and not turn_rejection(ctx, source, target, service):
                heapq.heappush(queue, (distance+ctx['links'][target]['length'], path+(target,)))
    raise ValueError('No verified multicarril through route: '+start+' -> '+end)


def gateway_connectivity(ctx, eligible, outgoing, all_outgoing, reasons, service):
    entries = sorted(k for k in eligible if not _inside(ctx, ctx['links'][k]['from']) and _inside(ctx, ctx['links'][k]['to']))
    exits = {k for k in eligible if _inside(ctx, ctx['links'][k]['from']) and not _inside(ctx, ctx['links'][k]['to'])}
    report = []
    for entry in entries:
        queue, visited = deque([entry]), {entry}
        frontier, reached = [], []
        l = ctx['links'][entry]
        side = _gateway(ctx, l['from'], l['to'], entry)['side']
        entry_name = l.get('tags', {}).get('name')
        while queue:
            source = queue.popleft()
            if source in exits:
                l = ctx['links'][source]
                exit_side = _gateway(ctx, l['to'], l['from'], source)['side']
                reached.append(dict(link_id=source, side=exit_side, different_side=exit_side != side))
                continue
            allowed = []
            rejected = []
            for target in all_outgoing[ctx['links'][source]['to']]:
                reason = reasons[target] or turn_rejection(ctx, source, target, service)
                if reason:
                    rejected.append(dict(from_link=source, to_link=target, reason=reason))
                else:
                    allowed.append(target)
                    if target not in visited:
                        visited.add(target); queue.append(target)
            if not allowed:
                frontier.extend(rejected)
        report.append(dict(entry=entry, name=entry_name, side=side,
                           reachable_links=len(visited), exits=sorted(reached, key=lambda x:x['link_id']),
                           dead_end_frontier=frontier))
    return report


def audit(ctx, service, source_paths, bundle):
    eligible, outgoing, all_outgoing, reasons = graph(ctx, service)
    metadata = {w.get('id'): {k:w.get(k) for k in ('version', 'timestamp', 'changeset')}
                for w in ET.parse(source_paths['osm']).getroot().findall('way')}
    corridors = []
    flat = []
    for name, requested_extent in CORRIDORS.items():
        ways = []
        for ident, way in ctx['ways'].items():
            if normalize(way['tags'].get('name', '')) != normalize(name):
                continue
            linked = []
            for key, link in ctx['links'].items():
                if link['way'] != ident:
                    continue
                evidence = directional_lane_evidence(ctx, key)
                row = dict(evidence, corridor=name, route_rejection=reasons[key],
                           from_node=link['from'], to_node=link['to'], length_m=link['length'],
                           native_allowed_exits=sorted(ctx['lane_exits'].get(key, [])),
                           from_inside=_inside(ctx, link['from']), to_inside=_inside(ctx, link['to']),
                           on_selected_route=any(key in r['link_ids'] for r in bundle['routes']))
                linked.append(row); flat.append(row)
            coords = [ctx['osm_nodes'][n] for n in way['nodes'] if n in ctx['osm_nodes']]
            ways.append(dict(osm_way_id=ident, source_url='https://www.openstreetmap.org/way/'+ident,
                        source_revision=metadata[ident], tags=way['tags'],
                        node_ids=way['nodes'], modeled_links=linked,
                        lat_range=[min(n['lat'] for n in coords), max(n['lat'] for n in coords)],
                        lon_range=[min(n['lon'] for n in coords), max(n['lon'] for n in coords)],
                        modeled_car_links=len(linked),
                        note='No native car links: source pedestrian/access/mode or importer exclusion; not an authorized freight segment.' if not linked else None))
        rows = [row for way in ways for row in way['modeled_links']]
        corridors.append(dict(name=name, requested_extent=requested_extent,
            audited_extent='Saved OSM ways matching this exact name; computational rectangle only, not full named external corridor.',
            way_count=len(ways), link_count=len(rows),
            lane_status_counts=dict(Counter(r['status'] for r in rows)),
            eligible_link_count=sum(r['route_rejection'] is None for r in rows), ways=ways))
    old = json.loads((SCENARIO/'freight/weekday-v2/routes.json').read_text(encoding='utf-8'))
    historical = [dict(route_id=r['route_id'], first_rejected_link=next(
        (dict(link_id=k, reason=reasons[k], lanes=directional_lane_evidence(ctx, k))
         for k in r['link_ids'] if reasons[k]), None),
        rejected_links=[dict(link_id=k, reason=reasons[k]) for k in r['link_ids'] if reasons[k]]) for r in old['routes']]
    return dict(schema_version='simz1-freight-multilane-audit-v3',
        source_sha256={k:sha256(v) for k,v in source_paths.items()}, source_paths={k:str(v) for k,v in source_paths.items()},
        service_version=VERSION, route_policy=POLICY, tagging_sources=TAGGING_SOURCES,
        verification_basis='Saved OSM explicit lane/direction/access tags and effective MATSim lane movement graph. Not a current road survey, statutory authorization or geometric swept-path survey.',
        map_bounds=ctx['bounds'], total_native_links=len(ctx['links']), eligible_links=len(eligible),
        corridors=corridors, historical_v2_rejections=historical,
        gateways=gateway_connectivity(ctx, eligible, outgoing, all_outgoing, reasons, service),
        route_validation=validate_bundle(ctx, bundle, service)), flat


def build(network, lanes, osm, historical_service):
    service = service_definition(historical_service)
    ctx = load_context(network, lanes, osm)
    eligible, outgoing, _, _ = graph(ctx, service)
    routes = []
    for name, (entry, exit_link) in GATEWAYS.items():
        path = shortest_route(ctx, entry, exit_link, eligible, outgoing, service)
        prefix, suffix = EXTERNAL_ANCHORS[name]
        path = prefix + path + suffix
        routes.append(dict(route_id=name, link_ids=path, entry_gateway=entry, exit_gateway=exit_link,
                           boundary_basis='osm_bounds_crossing_with_native_external_anchors', perimeter_connector_links=[],
                           activity_origin_link=path[0], activity_destination_link=path[-1],
                           external_origin_links=prefix, external_exit_links=suffix))
    bundle = dict(service_version=VERSION, route_policy=POLICY, routes=routes,
        native_gateway_policy=NATIVE_GATEWAY_POLICY,
        base_network_sha256=sha256(network), lanes_sha256=sha256(lanes), osm_sha256=sha256(osm),
        map_bounds=ctx['bounds'], empirical_calibration=False,
        route_basis='Synthetic shortest-distance verified multicarril directed routes between declared perimeter gateways; no one-lane links or exterior detours; not observed freight OD.')
    validate_bundle(ctx, bundle, service)
    return service, bundle, ctx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', type=Path, default=SCENARIO/'network.xml')
    parser.add_argument('--lanes', type=Path, default=SCENARIO/'lanes.xml')
    parser.add_argument('--osm', type=Path, default=SCENARIO/'map.osm')
    parser.add_argument('--config', type=Path, default=SCENARIO/'config-simz1.xml')
    parser.add_argument('--historical-service', type=Path, default=SCENARIO/'freight/weekday-v2/service-composition-v2.json')
    parser.add_argument('--output-dir', type=Path, default=SCENARIO/'freight/weekday-compact-v3')
    parser.add_argument('--audit-dir', type=Path, default=ROOT/'runtime/diagnostics/freight-compact-v3')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    history = args.historical_service.resolve().parent
    if output == history or history in output.parents or output == (SCENARIO/'freight/weekday-v1').resolve():
        raise ValueError('Refusing to overwrite historical freight service')
    service, bundle, ctx = build(args.network, args.lanes, args.osm, args.historical_service)
    service['osm_file'] = Path(os.path.relpath(args.osm.resolve(), output)).as_posix()
    report, rows = audit(ctx, service, dict(network=args.network, lanes=args.lanes, osm=args.osm), bundle)
    report['effective_config_validation'] = validate_through_config(args.config, args.osm, bundle, service)
    documents = {'service-composition-v3.json': service, 'routes.json': bundle}
    output.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        data = json.dumps(document, ensure_ascii=False, indent=2)+'\n'
        dest = output/name
        if dest.exists() and dest.read_text(encoding='utf-8') != data:
            raise ValueError('Existing version differs; choose new --output-dir: '+str(dest))
        dest.write_text(data, encoding='utf-8')
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    report['service_sha256'] = sha256(output/'service-composition-v3.json')
    report['route_bundle_sha256'] = sha256(output/'routes.json')
    current_check = args.audit_dir/'osm-current-source-check.json'
    if current_check.is_file():
        report['external_read_only_source_check'] = json.loads(current_check.read_text(encoding='utf-8'))
    (args.audit_dir/'corridors.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    fields = ['corridor', 'link_id', 'osm_way_id', 'direction', 'from_node', 'to_node', 'length_m',
              'native_permlanes', 'directional_lanes', 'reserved_lanes', 'usable_directional_lanes', 'status',
              'reason', 'route_rejection', 'source_url', 'on_selected_route', 'from_inside', 'to_inside']
    with (args.audit_dir/'corridor-links.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
    lines = ['# Auditoria de carga compacta v3', '',
             'Estado: rutas verificadas contra las etiquetas explicitas del OSM guardado y el grafo nativo. No es cartografia GIS ni inspeccion vial actual verificada.', '',
             'El informe JSON conserva cada way, revision OSM, tags, nodos, enlaces MATSim, carriles efectivos, permisos y bloqueos; CSV permite revisar enlace por enlace.', '',
             '| Corredor | Ways | Enlaces | Multicarril explicito | No verificados | Prohibidos | Elegibles |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for c in report['corridors']:
        s = c['lane_status_counts']
        lines.append(f"| {c['name']} | {c['way_count']} | {c['link_count']} | {s.get('verified_multilane', 0)} | {s.get('unverified', 0)} | {s.get('prohibited', 0)} | {c['eligible_link_count']} |")
    lines.extend(['', 'Los nombres no autorizan corredores completos. Un tramo sin lanes sigue sin verificar aunque permlanes=1. Los tramos peatonales y los sentidos contrarios no se convierten en conectores.', '',
                  '## Rutas nuevas', '', '| Ruta | Entrada | Salida | Distancia m | Carriles utilizables minimos |', '|---|---|---|---:|---:|'])
    for r in report['route_validation']['routes']:
        lines.append(f"| {r['id']} | {r['entry']['link']} ({r['entry']['side']}) | {r['exit']['link']} ({r['exit']['side']}) | {r['distance_m']:.1f} | {r['minimum_verified_usable_directional_lanes']} |")
    lines.extend(['', 'La distribucion equitativa entre estas cuatro rutas es sintetica. Las ventanas, PCU, peso, velocidad, margen y cantidad porcentual no se cambian. No hay un corredor oeste-este completo verificado en esta fuente; el cuarto servicio usa Elena a norte, declarado como tal.', '',
                  'Los diez tramos solicitados incluyen extremos externos a los limites de este mapa; no se afirma cobertura de Anillo Periferico, Aguilar Batres, Calle Marti o zona 5 donde el modelo no la contiene.', '',
                  '## Primeros bloqueos de rutas historicas v2 bajo la regla nueva', ''])
    for r in report['historical_v2_rejections']:
        b = r['first_rejected_link']
        lines.append(f"- {r['route_id']}: {b['link_id']}: {b['reason']}" if b else f"- {r['route_id']}: sin rechazo")
    lines.extend(['', '## Fuentes y hashes', '', *[f'- {k}: `{v}`' for k,v in report['source_sha256'].items()],
                  f"- Servicio: `{report['service_sha256']}`", f"- Rutas: `{report['route_bundle_sha256']}`", '',
                  *[f'- [{url}]({url})' for url in TAGGING_SOURCES], '',
                  'No se verifico un barrido geometrico medido de giros. Las condiciones nativas de paso, reserva de cuerpo completo, receptor, semaforos y separacion deben aprobarse en QSim; esta auditoria no certifica drenaje ni capacidad.', ''])
    current = report.get('external_read_only_source_check', {})
    if current.get('status') == 'fetched':
        lines.extend(['## Contraste con la API publica OSM', '',
            f"Consulta guardada en osm-current-source-check.json a {current['retrieved_utc']}. Los {len(current['checks'])} ways usados por las rutas se descargaron de la API oficial sin editar el escenario.",
            f"Tags iguales al snapshot: {current['all_source_tags_equal']}; nodos iguales: {current['all_source_nodes_equal']}. Esto confirma la fuente actual, no sustituye un levantamiento de campo.",
            f"XML: osm-current-selected-ways.xml; SHA-256 `{current['download_sha256']}`.", ''])
    (args.audit_dir/'CORREDORES.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(service=str(output), audit=str(args.audit_dir), routes=len(bundle['routes']),
                         eligible_links=report['eligible_links'], route_links=sum(len(r['link_ids']) for r in bundle['routes']),
                         status='static_valid_not_simulated')))


if __name__ == '__main__':
    main()
