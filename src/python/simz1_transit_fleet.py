"""Explicit SimZ1 transit fleet preparation; never invokes MATSim or Monte Carlo.

Real services must already be enabled in the evidence catalog. Synthetic fixtures
have no catalog service IDs and cannot activate a candidate service. This tool
only creates a new directory, after all validation, when explicitly run by a user.
"""
from __future__ import annotations

import argparse
from datetime import date
import gzip
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

SCHEMA = 'simz1-transit-fleet-v1'
DEFAULT_CATALOG = (Path(__file__).resolve().parents[1] / 'scenarios' / 'zona1'
                   / 'transit' / 'review-2026-10-22' / 'catalog.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, field):
    require(isinstance(value, str) and bool(value.strip()), f'{field}: text required')
    require(not any(c.isspace() for c in value) if field.endswith('_id') else True,
            f'{field}: whitespace is not allowed in IDs')
    return value


def number(value, field, minimum=0, *, positive=False):
    require(isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value), f'{field}: finite number required')
    require(value > minimum if positive else value >= minimum,
            f'{field}: outside allowed range')
    return value


def unique(items, field):
    require(isinstance(items, list), f'{field}: list required')
    result = {}
    for item in items:
        require(isinstance(item, dict), f'{field}: object required')
        key = text(item.get(field), field)
        require(key not in result, f'{field}: duplicate {key}')
        result[key] = item
    return result


def iso(value, field):
    text(value, field)
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, f'{field}: ISO date required')
    return parsed


def provenance(value, field, *, allow_synthetic=False):
    require(isinstance(value, dict), f'{field}: provenance required')
    allowed = {'verified', 'scenario_assumption'}
    if allow_synthetic:
        allowed.add('synthetic')
    require(value.get('status') in allowed, f'{field}: explicit evidence status required')
    text(value.get('source'), f'{field}.source')
    if value['status'] != 'verified':
        text(value.get('reason'), f'{field}.reason')


def read_network(path):
    """Read only node/link topology and attributes; never resolve external DTDs."""
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        root = ET.parse(stream).getroot()
    nodes = [{'node_id': n.attrib['id'], 'x': float(n.attrib['x']),
              'y': float(n.attrib['y'])} for n in root.findall('./nodes/node')]
    links = []
    for link in root.findall('./links/link'):
        attrs = link.attrib
        links.append({'link_id': attrs['id'], 'from_node': attrs['from'],
                      'to_node': attrs['to'], 'length_m': float(attrs['length']),
                      'free_speed_mps': float(attrs['freespeed']),
                      'capacity_per_hour': float(attrs['capacity']),
                      'lanes': float(attrs['permlanes']),
                      'modes': attrs.get('modes', 'car').split(',')})
    return {'nodes': nodes, 'links': links}


def calendar_active(calendar, service_date):
    require(isinstance(calendar, dict), 'calendar: explicit calendar required')
    start = iso(calendar.get('start_date'), 'calendar.start_date')
    end = iso(calendar.get('end_date'), 'calendar.end_date')
    require(start <= end, 'calendar: reversed date range')
    weekdays = calendar.get('weekdays')
    require(isinstance(weekdays, list) and all(type(d) is int and 0 <= d <= 6
                                              for d in weekdays),
            'calendar.weekdays: Monday=0 through Sunday=6 required')
    require(len(set(weekdays)) == len(weekdays), 'calendar: duplicate weekday')
    exceptions = {}
    for key in ('added_dates', 'removed_dates'):
        require(isinstance(calendar.get(key), list), f'calendar.{key}: list required')
        exceptions[key] = {iso(d, f'calendar.{key}') for d in calendar[key]}
        require(len(exceptions[key]) == len(calendar[key]), f'calendar.{key}: duplicate date')
    require(not exceptions['added_dates'] & exceptions['removed_dates'],
            'calendar: contradictory exception')
    if service_date in exceptions['removed_dates']:
        return False
    return (service_date in exceptions['added_dates'] or
            start <= service_date <= end and service_date.weekday() in weekdays)


def catalog_snapshot_bytes(catalog):
    """Exact bytes retained for the native production gate; never changes source data."""
    return (json.dumps(catalog, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def validate_fleet(plan, catalog, network=None):
    """Return a deterministic roster and separate counts without writing files."""
    require(isinstance(plan, dict) and plan.get('schema_version') == SCHEMA,
            'unsupported fleet schema')
    require(isinstance(catalog, dict), 'catalog: object required')
    text(plan.get('scenario_version'), 'scenario_version')
    synthetic = plan.get('synthetic')
    require(type(synthetic) is bool, 'synthetic: explicit boolean required')
    if synthetic:
        text(plan.get('synthetic_reason'), 'synthetic_reason')
    n = plan.get('monte_carlo_persons')
    require(type(n) is int and (0 <= n <= 250000 if synthetic else 150000 <= n <= 250000),
            'monte_carlo_persons: production N must be 150000..250000')
    require(plan.get('model_passengers') is False,
            'passenger modelling is not implemented by this fixed-fleet preparer')
    provenance(plan.get('dwell_provenance'), 'dwell_provenance')
    require(plan['dwell_provenance']['status'] == 'scenario_assumption',
            'without passengers, dwell must be an explicit scenario assumption')
    provenance(plan.get('fleet_provenance'), 'fleet_provenance')
    service_date = iso(plan.get('service_date'), 'service_date')
    text(plan.get('network_crs'), 'network_crs')
    day_end = number(plan.get('service_day_end_s'), 'service_day_end_s', positive=True)
    require(day_end <= 86400, 'service_day_end_s: this preparation covers one day only')
    domain = plan.get('domain')
    require(isinstance(domain, dict) and domain.get('approved') is (not synthetic),
            'domain: production requires approval; synthetic domain must not claim real approval')
    require(domain.get('synthetic') is synthetic,
            'domain: synthetic approval is only valid for a synthetic fixture')
    text(domain.get('source'), 'domain.source')
    require(isinstance(domain.get('link_ids'), list) and domain['link_ids'],
            'domain.link_ids: explicit membership required')

    services = unique(plan.get('services'), 'service_id')
    require(services, 'services: at least one explicit service required')
    catalog_services = unique(catalog.get('services'), 'service_id')
    enabled = {key: s for key, s in catalog_services.items() if s.get('production_enabled') is True}
    if not synthetic:
        require(len(catalog_snapshot_bytes(catalog)) <= 1_000_000,
                'catalog: native production gate accepts at most 1000000 bytes')
        require(catalog.get('production_enabled') is True
                and catalog.get('domain', {}).get('approved') is True,
                'catalog: production is disabled or domain is not approved')
        catalog_domain = catalog['domain'].get('link_ids')
        require(isinstance(catalog_domain, list) and len(catalog_domain) == len(set(catalog_domain))
                and set(catalog_domain) == set(domain['link_ids']),
                'catalog: approved domain link mapping must exactly match scenario domain')
    for service in services.values():
        catalog_id = service.get('catalog_service_id')
        if synthetic:
            require(catalog_id is None,
                    'synthetic fixtures must not impersonate a real catalog service')
        else:
            require(catalog_id in enabled,
                    f'catalog: service {catalog_id!r} is not production enabled')
            verification = enabled[catalog_id].get('verification', {})
            require(verification.get('status') == 'verified' and verification.get('blockers') == [],
                    'catalog: enabled service still has unresolved verification or blockers')
        text(service.get('operator'), 'operator')

    if network is None:
        require(synthetic and isinstance(plan.get('synthetic_network'), dict),
                'network: explicit actual network XML required outside synthetic fixtures')
        network = plan['synthetic_network']
    nodes = unique(network.get('nodes'), 'node_id')
    links = unique(network.get('links'), 'link_id')
    require(nodes and links, 'network: nodes and directed links required')
    for node in nodes.values():
        number(node.get('x'), 'node.x', minimum=-math.inf)
        number(node.get('y'), 'node.y', minimum=-math.inf)
    for link in links.values():
        require(link.get('from_node') in nodes and link.get('to_node') in nodes,
                f'link {link["link_id"]}: endpoint not found')
        for key in ('length_m', 'free_speed_mps', 'capacity_per_hour', 'lanes'):
            number(link.get(key), f'link.{key}', positive=True)
        require(isinstance(link.get('modes'), list) and link['modes'], 'link modes required')
    require(len(set(domain['link_ids'])) == len(domain['link_ids'])
            and set(domain['link_ids']) <= links.keys(), 'domain: unknown or duplicate link')
    types = unique(plan.get('vehicle_types'), 'type_id')
    vehicles = unique(plan.get('vehicles'), 'vehicle_id')
    require(types and vehicles, 'fleet: explicit types and bus IDs required')
    for kind in types.values():
        for key in ('length_m', 'width_m', 'pcu', 'max_speed_mps'):
            number(kind.get(key), f'type.{key}', positive=True)
        for key in ('seats', 'standing'):
            require(type(kind.get(key)) is int and kind[key] >= 0,
                    f'type.{key}: nonnegative integer required')
        require(kind['seats'] + kind['standing'] > 0, 'type: positive passenger capacity required')
        provenance(kind.get('dimensions_provenance'), 'dimensions_provenance')
        provenance(kind.get('physics_provenance'), 'physics_provenance')
        require(kind.get('body_model') == 'rigid',
                'type: only explicit rigid bodies supported; articulated buses need another model')
    for vehicle in vehicles.values():
        require(vehicle.get('type_id') in types, 'vehicle: unknown type')
    assigned_union = set()
    for service in services.values():
        assigned = service.get('vehicle_ids')
        require(isinstance(assigned, list) and assigned,
                'service.vehicle_ids: explicit configured buses including reserves required')
        require(all(isinstance(vehicle_id, str) and vehicle_id in vehicles for vehicle_id in assigned),
                'service.vehicle_ids: assigned bus is outside the configured fleet')
        require(len(assigned) == len(set(assigned)), 'service.vehicle_ids: duplicate assignment')
        assigned_union.update(assigned)
    require(assigned_union == vehicles.keys(),
            'fleet: every configured bus, including reserves, must be assigned explicitly to a service')
    stops = unique(plan.get('stops'), 'stop_id')
    require(stops, 'stops: explicit facilities required')
    for stop in stops.values():
        require(stop.get('link_id') in links, 'stop: unknown link')
        require('bus' in links[stop['link_id']]['modes'], 'stop: bus mode not allowed')
        for axis in ('x', 'y'):
            number(stop.get(axis), f'stop.{axis}', minimum=-math.inf)
        require(stop.get('stop_kind') in {'bay', 'in_lane'}, 'stop: bay or in_lane required')
        require(type(stop.get('blocking_lane')) is bool, 'stop.blocking_lane: boolean required')
        require(stop['stop_kind'] != 'bay' or stop['blocking_lane'] is False,
                'stop: bay may not block its link in this representation')
        require(stop['stop_kind'] != 'in_lane' or stop['blocking_lane'] is True,
                'stop: in_lane requires explicit native blocking')
        require(stop['stop_kind'] != 'in_lane' or links[stop['link_id']]['lanes'] == 1,
                'unsupported_multilane_in_lane_stop: native stop blocks an aggregate queue without lane assignment')
        number(stop.get('dwell_seconds'), 'stop.dwell_seconds')

    roster, route_ids, departure_ids = [], set(), set()
    outside_domain_links = set()
    for service in services.values():
        active = calendar_active(service.get('calendar'), service_date)
        routes = unique(service.get('routes'), 'route_id')
        require(routes, 'service: directed routes required')
        for route_id, route in routes.items():
            require(route_id not in route_ids, 'route_id: globally unique IDs required')
            route_ids.add(route_id)
            text(route.get('direction'), 'route.direction')
            path = route.get('link_ids')
            require(isinstance(path, list) and len(path) >= 2, 'route: at least two directed links required')
            require(all(link in links for link in path), f'route {route_id}: unknown link')
            outside_domain_links.update(set(path) - set(domain['link_ids']))
            require(all('bus' in links[link]['modes'] for link in path), 'route: bus access forbidden')
            require(all(links[a]['to_node'] == links[b]['from_node'] for a, b in zip(path, path[1:])),
                    f'route {route_id}: disconnected or reversed links')
            regime = route.get('traffic_regime')
            require(regime in {'mixed', 'segregated'}, 'route: explicit traffic_regime required')
            if regime == 'segregated':
                require(all('car' not in links[link]['modes'] for link in path),
                        'segregated route: link still permits cars; dedicated network representation required')
            visits = route.get('stops')
            require(isinstance(visits, list) and len(visits) >= 2, 'route: at least two stop visits required')
            previous_index, previous_departure = -1, 0
            previous_stop_link = None
            for visit in visits:
                require(visit.get('stop_id') in stops, 'route: unknown stop')
                index = visit.get('link_index')
                require(type(index) is int and previous_index <= index < len(path) and index >= 0,
                        'route: stop link_index must follow directed route order')
                require(stops[visit['stop_id']]['link_id'] == path[index],
                        'route: stop is on wrong directed link')
                stop_link = stops[visit['stop_id']]['link_id']
                require(stop_link != previous_stop_link,
                        'route: native MATSim cannot distinguish consecutive stops on repeated same link')
                native_index = next(i for i in range(max(0, previous_index), len(path))
                                    if path[i] == stop_link)
                require(native_index == index,
                        'route: stop occurrence is ambiguous in native MATSim; link_index cannot skip first occurrence')
                arrival = number(visit.get('arrival_offset_s'), 'stop.arrival_offset_s')
                departure = number(visit.get('departure_offset_s'), 'stop.departure_offset_s')
                require(previous_departure <= arrival <= departure,
                        'route: stop offsets reverse time or overlap dwell')
                require(abs(departure - arrival - stops[visit['stop_id']]['dwell_seconds']) < 1e-7,
                        'route: dwell must match explicit stop assumption')
                previous_index, previous_departure, previous_stop_link = index, departure, stop_link
            require(visits[0]['link_index'] == 0 and visits[-1]['link_index'] == len(path) - 1,
                    'route: first and last stop must be on route endpoint links')
            require(visits[0]['arrival_offset_s'] == 0, 'route: first arrival offset must be zero')
            terminal = number(route.get('terminal_time_s'), 'route.terminal_time_s')
            turn = number(route.get('turnaround_time_s'), 'route.turnaround_time_s')
            departures = unique(route.get('departures'), 'departure_id')
            for dep_id, dep in departures.items():
                require(dep_id not in departure_ids, 'departure_id: globally unique IDs required')
                departure_ids.add(dep_id)
                require(dep.get('vehicle_id') in vehicles,
                        'departure: explicit vehicle_id absent from configured fleet (insufficient fleet)')
                require(dep['vehicle_id'] in service['vehicle_ids'],
                        'departure: bus is not explicitly assigned to this service')
                start = number(dep.get('time_s'), 'departure.time_s')
                end = start + visits[-1]['departure_offset_s']
                require(start < day_end and end <= day_end, 'departure: outside service day')
                if active:
                    roster.append({'vehicle_id': dep['vehicle_id'], 'service_id': service['service_id'],
                                   'route_id': route_id, 'departure_id': dep_id,
                                   'departure_time_s': start, 'arrival_time_s': start + visits[-1]['arrival_offset_s'],
                                   'end_time_s': end, 'terminal_time_s': terminal, 'turnaround_time_s': turn,
                                   'available_time_s': end + terminal + turn,
                                   'origin_stop_id': visits[0]['stop_id'],
                                   'destination_stop_id': visits[-1]['stop_id']})
    roster.sort(key=lambda row: (row['vehicle_id'], row['departure_time_s'], row['departure_id']))
    transfers = plan.get('transfers')
    require(isinstance(transfers, list), 'transfers: explicit list required')
    transfer_map = {}
    by_departure = {row['departure_id']: row for row in roster}
    for transfer in transfers:
        require(transfer.get('kind') == 'exterior', 'transfer: only explicit exterior ledger supported')
        a, b = transfer.get('from_departure_id'), transfer.get('to_departure_id')
        require(a in by_departure and b in by_departure, 'transfer: unknown or inactive departure')
        require((a, b) not in transfer_map, 'transfer: duplicate')
        require(transfer.get('vehicle_id') == by_departure[a]['vehicle_id'] == by_departure[b]['vehicle_id'],
                'transfer: identity changes between exit and return')
        number(transfer.get('duration_s'), 'transfer.duration_s', positive=True)
        provenance(transfer.get('evidence'), 'transfer.evidence', allow_synthetic=True)
        require(transfer['evidence']['status'] != 'synthetic' or synthetic,
                'transfer: synthetic exterior movement requires a synthetic scenario')
        transfer_map[(a, b)] = transfer
    used_transfers = set()
    for previous, following in zip(roster, roster[1:]):
        if previous['vehicle_id'] != following['vehicle_id']:
            continue
        pair = (previous['departure_id'], following['departure_id'])
        transfer = transfer_map.get(pair)
        required_time = previous['available_time_s'] + (transfer['duration_s'] if transfer else 0)
        require(following['departure_time_s'] >= required_time,
                f'vehicle {previous["vehicle_id"]}: overlap or insufficient terminal/turnaround/exterior time')
        if transfer:
            used_transfers.add(pair)
        else:
            require(previous['destination_stop_id'] == following['origin_stop_id'],
                    f'vehicle {previous["vehicle_id"]}: disconnected terminal; explicit transfer required, no teleport')
    require(used_transfers == transfer_map.keys(), 'transfer: must connect consecutive trips of one bus')
    return {'schema_version': 'simz1-transit-fleet-manifest-v1',
            'scenario_version': plan['scenario_version'], 'synthetic': synthetic,
            'service_date': plan['service_date'], 'model_passengers': False,
            'counts': {'road_demand_persons': n, 'public_transport_vehicles_configured': len(vehicles),
                       'public_transport_departures_scheduled': len(roster),
                       'transit_drivers_added_to_demand': 0, 'internal_transit_drivers': None,
                       'active_inside_domain': None},
            'fleet_vehicle_ids': sorted(vehicles), 'domain': domain,
            'service_counts': [{'service_id': service_id,
                                'configured_vehicle_ids': sorted(service['vehicle_ids']),
                                'configured_buses': len(service['vehicle_ids']),
                                'scheduled_expeditions': sum(row['service_id'] == service_id for row in roster)}
                               for service_id, service in services.items()],
            'service_bus_counts_are_not_additive': True,
            'compatibility': ('blocked_exterior_runtime_not_implemented' if transfers or outside_domain_links
                              else 'inactive_service_date' if not roster else 'native_ready_for_user_validation'),
            'outside_domain_links': sorted(outside_domain_links),
            'enabled_catalog_source': hashlib.sha256(catalog_snapshot_bytes(catalog)).hexdigest(),
            'actual_availability_policy': 'reject_on_actual_violation; scheduled validation cannot guarantee no delays',
            'dwell_provenance': plan['dwell_provenance'], 'fleet_provenance': plan['fleet_provenance'],
            'transfers': transfers, 'roster': roster}


def attributes(parent, values):
    node = ET.SubElement(parent, 'attributes')
    for key, value in values.items():
        child = ET.SubElement(node, 'attribute', {'name': key, 'class': 'java.lang.String'})
        child.text = str(value).lower() if isinstance(value, bool) else str(value)


def xml_bytes(root, doctype=None):
    ET.indent(root, space='  ')
    declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    if doctype:
        declaration += f'<!DOCTYPE {doctype}>\n'.encode('utf-8')
    return declaration + ET.tostring(root, encoding='utf-8') + b'\n'


def clock_time(seconds):
    # MATSim 15 Time.parseTime accepts numeric seconds (including exponents).
    # Python's float string round-trips without quantizing source timestamps.
    return str(seconds)


def schedule_xml(plan, manifest):
    root = ET.Element('transitSchedule')
    metadata = {'simz1:fleetSchema': 'fixed-fleet-v1',
                      'simz1:scenarioVersion': plan['scenario_version'],
                      'simz1:serviceDate': plan['service_date'],
                      'simz1:purpose': 'synthetic_fixture' if plan['synthetic'] else 'production',
                      'simz1:passengersModeled': False,
                      'simz1:minimumTurnPolicy': 'reject_on_actual_violation',
                      'simz1:domainLinks': ' '.join(plan['domain']['link_ids']),
                      'simz1:domainApproved': plan['domain']['approved'],
                      'simz1:domainSource': plan['domain']['source'],
                      'simz1:domainSynthetic': plan['domain']['synthetic'],
                      'simz1:monteCarloPersons': plan['monte_carlo_persons'],
                      'simz1:configuredFleetSize': manifest['counts']['public_transport_vehicles_configured'],
                'simz1:scheduledExpeditions': manifest['counts']['public_transport_departures_scheduled']}
    if not plan['synthetic']:
        metadata.update({'simz1:catalogFile': 'enabled-catalog.json',
                         'simz1:catalogSha256': manifest['enabled_catalog_source']})
    attributes(root, metadata)
    facilities = ET.SubElement(root, 'transitStops')
    for stop in plan['stops']:
        node = ET.SubElement(facilities, 'stopFacility', {'id': stop['stop_id'], 'x': str(stop['x']),
                             'y': str(stop['y']), 'linkRefId': stop['link_id'],
                             'isBlocking': str(stop['blocking_lane']).lower()})
        attributes(node, {'simz1:stopPlacement': stop['stop_kind'],
                          'simz1:dwellBasis': 'explicit_scenario_assumption',
                          'simz1:dwellSeconds': stop['dwell_seconds']})
    roster = {row['departure_id']: row for row in manifest['roster']}
    for service in plan['services']:
        line = ET.SubElement(root, 'transitLine', {'id': service['service_id']})
        attributes(line, {'simz1:serviceId': service['service_id'],
                          'simz1:productionEnabled': not plan['synthetic'],
                          'simz1:enabledCatalogSource': manifest['enabled_catalog_source'],
                          'simz1:assignedVehicleIds': ' '.join(service['vehicle_ids']),
                          'simz1:serviceActiveOnDate': calendar_active(service['calendar'], iso(plan['service_date'], 'service_date')),
                          'simz1:operator': service['operator'],
                          'simz1:catalogServiceId': service['catalog_service_id'] or 'synthetic_fixture'})
        if not calendar_active(service['calendar'], iso(plan['service_date'], 'service_date')):
            continue  # Keep explicit ownership/reserves; MATSim 15 permits a line with no routes.
        for route in service['routes']:
            node = ET.SubElement(line, 'transitRoute', {'id': route['route_id']})
            attributes(node, {'simz1:routePolicy': 'fixed-v1',
                              'simz1:runningWay': route['traffic_regime'],
                              'simz1:direction': route['direction']})
            ET.SubElement(node, 'transportMode').text = 'bus'
            profile = ET.SubElement(node, 'routeProfile')
            for visit in route['stops']:
                ET.SubElement(profile, 'stop', {'refId': visit['stop_id'],
                              'arrivalOffset': clock_time(visit['arrival_offset_s']),
                              'departureOffset': clock_time(visit['departure_offset_s']),
                              'awaitDeparture': 'true'})
            path = ET.SubElement(node, 'route')
            for link_id in route['link_ids']:
                ET.SubElement(path, 'link', {'refId': link_id})
            departures = ET.SubElement(node, 'departures')
            for departure in route['departures']:
                if departure['departure_id'] not in roster:
                    continue
                row = roster[departure['departure_id']]
                dep = ET.SubElement(departures, 'departure', {'id': departure['departure_id'],
                                    'departureTime': clock_time(departure['time_s']),
                                    'vehicleRefId': departure['vehicle_id']})
                attributes(dep, {'simz1:endTimeSeconds': row['end_time_s'],
                                 'simz1:terminalSeconds': row['terminal_time_s'],
                                 'simz1:turnaroundSeconds': row['turnaround_time_s']})
    return xml_bytes(root, 'transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd"')


def vehicles_xml(plan):
    root = ET.Element('vehicleDefinitions', {'xmlns': 'http://www.matsim.org/files/dtd',
                      'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                      'xsi:schemaLocation': 'http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd'})
    for kind in plan['vehicle_types']:
        node = ET.SubElement(root, 'vehicleType', {'id': kind['type_id']})
        attributes(node, {'simz1:family': 'public_transport', 'simz1:bodyModel': kind['body_model'],
                          'simz1:dimensionsBasis': kind['dimensions_provenance']['status'],
                          'simz1:physicsBasis': kind['physics_provenance']['status']})
        ET.SubElement(node, 'capacity', {'seats': str(kind['seats']), 'standingRoomInPersons': str(kind['standing'])})
        ET.SubElement(node, 'length', {'meter': str(kind['length_m'])})
        ET.SubElement(node, 'width', {'meter': str(kind['width_m'])})
        ET.SubElement(node, 'maximumVelocity', {'meterPerSecond': str(kind['max_speed_mps'])})
        ET.SubElement(node, 'passengerCarEquivalents', {'pce': str(kind['pcu'])})
        ET.SubElement(node, 'networkMode', {'networkMode': 'bus'})
        ET.SubElement(node, 'flowEfficiencyFactor', {'factor': '1.0'})
    for vehicle in plan['vehicles']:
        ET.SubElement(root, 'vehicle', {'id': vehicle['vehicle_id'], 'type': vehicle['type_id']})
    return xml_bytes(root)


def network_xml(network):
    root = ET.Element('network')
    nodes = ET.SubElement(root, 'nodes')
    for node in network['nodes']:
        ET.SubElement(nodes, 'node', {'id': node['node_id'], 'x': str(node['x']), 'y': str(node['y'])})
    links = ET.SubElement(root, 'links', {'capperiod': '01:00:00', 'effectivecellsize': '7.5', 'effectivelanewidth': '3.75'})
    for link in network['links']:
        ET.SubElement(links, 'link', {'id': link['link_id'], 'from': link['from_node'], 'to': link['to_node'],
                      'length': str(link['length_m']), 'freespeed': str(link['free_speed_mps']),
                      'capacity': str(link['capacity_per_hour']), 'permlanes': str(link['lanes']),
                      'modes': ','.join(link['modes'])})
    return xml_bytes(root, 'network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd"')


def prepare(plan, catalog, output, network=None):
    manifest = validate_fleet(plan, catalog, network)
    require(manifest['compatibility'] != 'blocked_exterior_runtime_not_implemented',
            'blocked_exterior_runtime_not_implemented: exterior timing is validated, but no executable native output is safe')
    require(manifest['compatibility'] != 'inactive_service_date',
            'inactive_service_date: no departures on this date; leave transit disabled')
    output = Path(output).resolve()
    require(not output.exists(), 'output directory already exists; historical and prior outputs are never overwritten')
    files = {'transitSchedule.xml': schedule_xml(plan, manifest),
             'transitVehicles.xml': vehicles_xml(plan),
             'roster.json': (json.dumps(manifest['roster'], ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
             'fleet-config.json': (json.dumps(plan, ensure_ascii=False, indent=2) + '\n').encode('utf-8')}
    if network is None:
        files['synthetic-network.xml'] = network_xml(plan['synthetic_network'])
    if not plan['synthetic']:
        files['enabled-catalog.json'] = catalog_snapshot_bytes(catalog)
    manifest = {key: value for key, value in manifest.items() if key != 'roster'}
    manifest['artifacts'] = [{'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                             for name, data in sorted(files.items())]
    files['transit-fleet-manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output.mkdir(parents=False, exist_ok=False)
    for name, data in files.items():
        with (output / name).open('xb') as stream:
            stream.write(data)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--network', type=Path)
    parser.add_argument('--output', type=Path, help='New directory; omission performs read-only validation')
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.config.read_text(encoding='utf-8-sig'))
        catalog = json.loads(args.catalog.read_text(encoding='utf-8-sig'))
        network = read_network(args.network) if args.network else None
        result = (prepare(plan, catalog, args.output, network) if args.output
                  else validate_fleet(plan, catalog, network))
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as error:
        parser.exit(2, f'Fixed fleet blocked: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
