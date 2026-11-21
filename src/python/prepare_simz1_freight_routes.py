"""Generate the versioned principal-road freight through service.

Keep every principal link of weekday-v1 in its original order. Replace only
the intervening local-road sections, and extend gateways to links crossing
the supplied OSM bounds. These are computational map bounds, not surveyed
or administrative freight authorizations. No simulation is started here.
"""
import argparse
from collections import defaultdict
import heapq
import json
import os
from pathlib import Path

from simz1_run import sha256
from simz1_freight_routes import load_context, link_rejection, turn_rejection, validate_bundle


SCENARIO = Path(__file__).resolve().parents[1] / 'scenarios/zona1'
SERVICE_VERSION = 'weekday-v2'
ROUTE_POLICY = 'principal-through-v2'
PRINCIPAL_HIGHWAYS = frozenset(('motorway', 'motorway_link', 'trunk', 'trunk_link',
    'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link'))

# Intentional, reproducible gateway choices keep four directional corridors.
# The west-east v1 route was entirely residential. Its replacement follows
# the southwestern 19 Calle approach, 3a Avenida, 9a Calle and 7a Calle exit.
GATEWAYS = {
    'west-east': ('osm_381158292_0_forward', 'osm_1358273948_0_forward'),
    'west-east-reverse': ('osm_49009942_2_forward', 'osm_65792798_1_backward'),
    'south-north': ('osm_363667895_5_forward', 'osm_732305247_6_forward'),
    'south-north-reverse': ('osm_381097595_10_forward', 'osm_400843677_5_forward'),
}
# A terminal 186 m connector crosses the western map bound from Avenida
# Elena. It is never an internal destination or a general local-road permit.
PERIMETER_CONNECTORS = {'west-east-reverse': ('osm_65792798_1_backward',)}


def service_definition(historical_routes):
    source = Path(historical_routes).with_name('service-composition-v1.json')
    service = json.loads(source.read_text(encoding='utf-8'))
    service.update(service_version=SERVICE_VERSION, route_policy=ROUTE_POLICY,
        osm_file='../../map.osm', routes_file='routes.json',
        route_access_basis='Principal-road through corridors with explicit OSM-boundary crossings; OSM access and lane movements checked, not surveyed truck authorizations.',
        route_preservation_basis='All historical principal links retained in order; local internal sections replaced and map-boundary gateway links extended.',
        corner_preference='Prefer opposite map sides and a southwestern-to-northeastern west-east corridor; preserve the other valid historical principal trunks before imposing diagonal detours.')
    return service


def shortest_bridge(ctx, start, target, eligible, service, outgoing=None):
    """Deterministic minimum-distance bridge over legal directed movements."""
    if outgoing is None:
        outgoing = defaultdict(list)
        for ident in sorted(eligible):
            outgoing[ctx['links'][ident]['from']].append(ident)
    queue = [(0., (start,))]
    visited = set()
    while queue:
        cost, path = heapq.heappop(queue)
        a = path[-1]
        if a in visited:
            continue
        visited.add(a)
        if a == target:
            return list(path)
        for b in outgoing[ctx['links'][a]['to']]:
            if b in visited or turn_rejection(ctx, a, b, service):
                continue
            heapq.heappush(queue, (cost + ctx['links'][b]['length'], path + (b,)))
    raise ValueError(f'No principal freight bridge from {start} to {target}')


def build(network, lanes, osm=None, historical_routes=None, service=None):
    network, lanes = Path(network), Path(lanes)
    osm = Path(osm) if osm is not None else network.with_name('map.osm')
    historical_routes = Path(historical_routes) if historical_routes is not None else network.parent / 'freight/weekday-v1/routes.json'
    service = dict(service) if service is not None else service_definition(historical_routes)
    ctx = load_context(network, lanes, osm)
    historical = json.loads(historical_routes.read_text(encoding='utf-8'))
    if {r['route_id'] for r in historical['routes']} != set(GATEWAYS):
        raise ValueError('Expected the four historical weekday-v1 corridors')
    routes = []
    for original in historical['routes']:
        name = original['route_id']
        entry, exit_link = GATEWAYS[name]
        connectors = set(PERIMETER_CONNECTORS.get(name, ()))
        eligible = {ident for ident in ctx['links']
                    if not link_rejection(ctx, ident, service, allow_perimeter_connector=ident in connectors)}
        outgoing = defaultdict(list)
        for ident in sorted(eligible):
            outgoing[ctx['links'][ident]['from']].append(ident)
        preserved = []
        for ident in original['link_ids']:
            if ident not in ctx['links']:
                raise ValueError(f'Historical link disappeared: {ident}')
            if ctx['links'][ident]['tags'].get('highway') in PRINCIPAL_HIGHWAYS:
                if ident not in eligible:
                    raise ValueError(f'Historical principal link requires review: {ident}')
                preserved.append(ident)
        anchors = []
        for ident in [entry, *preserved, exit_link]:
            if ident not in eligible:
                raise ValueError(f'Invalid freight gateway/anchor: {ident}')
            if not anchors or anchors[-1] != ident:
                anchors.append(ident)
        path = [anchors[0]]
        for a, b in zip(anchors, anchors[1:]):
            path.extend(shortest_bridge(ctx, a, b, eligible, service, outgoing)[1:])
        routes.append(dict(original, link_ids=path, boundary_basis='osm_bounds_crossing',
                     perimeter_connector_links=sorted(connectors), preserved_principal_links=preserved))
    bundle = dict(base_network_sha256=sha256(network), osm_sha256=sha256(osm),
        lanes_sha256=sha256(lanes), historical_routes_sha256=sha256(historical_routes),
        service_version=SERVICE_VERSION, route_policy=ROUTE_POLICY, empirical_calibration=False,
        map_bounds=ctx['bounds'],
        route_basis='Synthetic principal-road through corridors; all weekday-v1 principal links preserved, minimum-distance legal bridges, explicit OSM-boundary gateways; not observed freight routes.',
        principal_highways=sorted(PRINCIPAL_HIGHWAYS), routes=routes)
    validate_bundle(ctx, bundle, service)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', type=Path, default=SCENARIO / 'network.xml')
    parser.add_argument('--lanes', type=Path, default=SCENARIO / 'lanes.xml')
    parser.add_argument('--osm', type=Path, default=SCENARIO / 'map.osm')
    parser.add_argument('--historical-routes', type=Path, default=SCENARIO / 'freight/weekday-v1/routes.json')
    parser.add_argument('--output-dir', type=Path, default=SCENARIO / 'freight/weekday-v2')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    historical_dir = args.historical_routes.resolve().parent
    canonical_history = (SCENARIO / 'freight/weekday-v1').resolve()
    if any(output == previous or previous in output.parents
           for previous in (historical_dir, canonical_history)):
        raise ValueError('Refusing to overwrite the historical freight service')
    service = service_definition(args.historical_routes)
    service['osm_file'] = Path(os.path.relpath(args.osm.resolve(), output)).as_posix()
    bundle = build(args.network, args.lanes, args.osm, args.historical_routes, service)
    encoded = {name: json.dumps(document, indent=2, ensure_ascii=False) + '\n'
               for name, document in {'routes.json': bundle, 'service-composition-v2.json': service}.items()}
    # A different result needs a new version, not an overwrite of an existing one.
    for name, data in encoded.items():
        destination = output / name
        if destination.exists() and destination.read_text(encoding='utf-8') != data:
            raise ValueError(f'Existing version differs; choose a new --output-dir: {destination}')
    output.mkdir(parents=True, exist_ok=True)
    for name, data in encoded.items():
        (output / name).write_text(data, encoding='utf-8')
    print(f'Generated {len(bundle["routes"])} freight through routes in {output}')


if __name__ == '__main__':
    main()
