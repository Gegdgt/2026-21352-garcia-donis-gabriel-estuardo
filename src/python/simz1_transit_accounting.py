"""Separate planned road demand from scheduled transit, without running either.

These are input counters, not a claim that a bus entered the approved domain.
Internal transit drivers are observed by the native transit diagnostics and are
never added to N. Reading a historical manifest does not call this module.
"""
from pathlib import Path
import xml.etree.ElementTree as ET


def _attributes(element):
    return {a.get('name'): a.text for a in element.findall('./{*}attributes/{*}attribute')}


def distinct_fleet_by_system(service_counts, fleet_vehicle_ids):
    """Count stable native bus IDs once across services and civil dates.

    Old synthetic schedules may lack serviceSystem. Their unclassified IDs do
    not become an invented system; complete system coverage is required only
    when every service supplies that classification.
    """
    ids = list(fleet_vehicle_ids)
    if any(not isinstance(ident, str) or not ident for ident in ids) or len(ids) != len(set(ids)):
        raise ValueError('Configured fleet IDs must be unique nonempty strings')
    available, owner, by_system = set(ids), {}, {}
    complete = True
    for row in service_counts:
        assigned = row.get('configured_vehicle_ids')
        if not isinstance(assigned, (list, tuple, set, frozenset)):
            raise ValueError('Service fleet accounting requires explicit configured_vehicle_ids')
        if (any(not isinstance(ident, str) or not ident for ident in assigned)
                or len(assigned) != len(set(assigned))):
            raise ValueError('Service allocation needs unique nonempty bus IDs')
        assigned = set(assigned)
        if not assigned <= available:
            raise ValueError('Service references a bus outside the configured fleet')
        system = row.get('system')
        if system is None or system == '':
            complete = False
            continue
        if not isinstance(system, str) or not system.strip():
            raise ValueError('Service system must be a nonempty string when supplied')
        for ident in assigned:
            if ident in owner and owner[ident] != system:
                raise ValueError('A stable bus cannot belong to two systems: '+ident)
            owner[ident] = system
        by_system.setdefault(system, set()).update(assigned)
    if complete and set(owner) != available:
        raise ValueError('Classified service allocations must cover the whole configured fleet')
    return {system: len(assigned) for system, assigned in by_system.items()}


def planned_transit_counts(config_path, road_persons):
    if type(road_persons) is not int or road_persons < 0:
        raise ValueError('Road demand N must be a nonnegative integer')
    config_path = Path(config_path)
    root = ET.parse(config_path).getroot()
    params = {f"{module.get('name')}.{param.get('name')}": param.get('value')
              for module in root.findall('module') for param in module.findall('param')}
    use_transit = params.get('transit.useTransit', 'false')
    if use_transit not in ('true', 'false'):
        raise ValueError('transit.useTransit must be true or false')
    result = dict(enabled=use_transit == 'true', road_demand_persons=road_persons,
                  public_transport_vehicles_configured=0,
                  public_transport_departures_scheduled=0,
                  transit_drivers_added_to_demand=0,
                  transit_drivers_internal_observed=None,
                  public_transport_active_inside_domain=None,
                  active_count_status='not_observed', service_counts=[],
                  counter_basis='scenario inputs; N excludes transit fleet and internal drivers')
    if use_transit == 'false':
        return result

    def read_input(key, expected_root):
        name = params.get(key)
        if not name or name == 'null':
            raise ValueError(f'Missing explicit fixed fleet input: {key}')
        path = Path(name)
        if not path.is_absolute():
            path = config_path.parent / path
        document = ET.parse(path).getroot()
        if document.tag.split('}')[-1] != expected_root:
            raise ValueError(f'Wrong root for {key}: {document.tag}')
        return document

    schedule = read_input('transit.transitScheduleFile', 'transitSchedule')
    vehicles = read_input('transit.vehiclesFile', 'vehicleDefinitions')
    metadata = _attributes(schedule)
    if metadata.get('simz1:fleetSchema') != 'fixed-fleet-v1':
        raise ValueError('Transit accounting requires an explicit SimZ1 fixed fleet contract')
    declared_n = metadata.get('simz1:monteCarloPersons')
    if declared_n != str(road_persons):
        raise ValueError('Transit fixture N does not match the road population; never add B to N')
    ids = [vehicle.get('id') for vehicle in vehicles.findall('{*}vehicle')]
    if any(not ident for ident in ids) or len(ids) != len(set(ids)):
        raise ValueError('Transit vehicles need unique nonempty vehicle_id')
    available = set(ids)
    lines, all_departure_ids, allocated_fleet = set(), set(), set()
    for line in schedule.findall('{*}transitLine'):
        line_id = line.get('id')
        if not line_id or line_id in lines:
            raise ValueError('Duplicate or missing transit line ID')
        lines.add(line_id)
        line_metadata = _attributes(line)
        service_id = line_metadata.get('simz1:serviceId', line_id)
        assigned = (line_metadata.get('simz1:assignedVehicleIds') or '').split()
        if not assigned or len(assigned) != len(set(assigned)) or not set(assigned) <= available:
            raise ValueError('Service needs an explicit allocation of registered fleet vehicle IDs')
        allocated_fleet.update(assigned)
        used, departures = set(), 0
        for route in line.findall('{*}transitRoute'):
            for departure in route.findall('./{*}departures/{*}departure'):
                departure_id, vehicle_id = departure.get('id'), departure.get('vehicleRefId')
                if not departure_id or departure_id in all_departure_ids:
                    raise ValueError('Duplicate or missing global departure ID')
                all_departure_ids.add(departure_id)
                if vehicle_id not in available:
                    raise ValueError('Departure references a bus outside the configured fixed fleet')
                if vehicle_id not in assigned:
                    raise ValueError('Departure bus is not allocated to this service')
                used.add(vehicle_id)
                departures += 1
        result['service_counts'].append(dict(system=line_metadata.get('simz1:serviceSystem'),service_id=service_id, line_id=line_id,
                                             configured_vehicle_ids=sorted(assigned),
                                             configured_buses=len(assigned),
                                             used_vehicle_ids=sorted(used),
                                             distinct_used_buses=len(used),
                                             scheduled_expeditions=departures))
        result['public_transport_departures_scheduled'] += departures
    if allocated_fleet != available:
        raise ValueError('Every configured bus, including reserves, needs an explicit service allocation')
    result['public_transport_vehicles_configured'] = len(ids)
    for key, actual in [('configuredFleetSize', len(ids)),
                        ('scheduledExpeditions', result['public_transport_departures_scheduled'])]:
        if metadata.get('simz1:' + key) != str(actual):
            raise ValueError(f'Fixed fleet metadata {key} does not match native XML counts')
    result['fleet_by_system'] = distinct_fleet_by_system(result['service_counts'], ids)
    result['domain_scope'] = 'computational_network' if metadata.get('simz1:purpose')=='weekday_scenario_v2' else metadata.get('simz1:purpose')
    result['scenario_version'] = metadata.get('simz1:scenarioVersion')
    result['service_date'] = metadata.get('simz1:serviceDate')
    result['purpose'] = metadata.get('simz1:purpose')
    result['fleet_vehicle_ids'] = sorted(ids)
    result['service_bus_counts_are_not_additive'] = True
    return result


def verified_weekday_fleet(directory, manifest, road_persons):
    """Derive B only from this run's pinned policy, native XML and roster."""
    from collections import Counter
    import json
    from simz1_run import checked_path
    from simz1_weekday_transit import verify_policy_chain, validate_serialized_timetable

    def require(ok, message):
        if not ok:
            raise ValueError('Saved public fleet: ' + message)

    schedule_path = checked_path(directory, manifest['inputs']['transit_schedule'])
    schedule = ET.parse(schedule_path).getroot()
    metadata = _attributes(schedule)
    policy, _ = verify_policy_chain(schedule_path, metadata, road_persons)
    services = {s['service_id']: s for s in policy['services']}
    require(len(services) == len(policy['services']), 'duplicate service')
    declared = Counter()
    for service in services.values():
        require(type(service['buses']) is int and service['buses'] > 0, 'invalid service quota')
        declared[service['system']] += service['buses']
    require(dict(declared) == policy['fleet_counts'], 'policy system quotas disagree')
    total = sum(declared.values())
    require(total == policy['configured_fleet_size'], 'policy total disagrees')
    fleet = ET.parse(checked_path(directory, manifest['inputs']['transit_vehicles'])).getroot()
    vehicles = {v.get('id'): v.get('type') for v in fleet.findall('{*}vehicle')}
    require(len(vehicles) == len(fleet.findall('{*}vehicle')) == total and all(vehicles),
            'generated XML fleet differs from declared unique fleet')
    allocations, owners, duties = {}, {}, {}
    for line in schedule.findall('{*}transitLine'):
        lm = _attributes(line)
        line_id = lm['simz1:serviceId']
        # The existing continuous calendar reuses a fleet with dated service IDs.
        service_id = line_id.rsplit('__', 1)[0] if 'temporal_calendar' in policy else line_id
        require(line.get('id') == line_id and service_id in services, 'unknown XML service')
        service = services[service_id]
        assigned = lm['simz1:assignedVehicleIds'].split()
        require(len(assigned) == len(set(assigned)) == service['buses'] and
                lm['simz1:serviceSystem'] == service['system'], 'XML service quota/system differs')
        if service_id in allocations:
            require(allocations[service_id] == set(assigned), 'dated service changes fleet IDs')
        allocations[service_id] = set(assigned)
        for ident in assigned:
            require(ident in vehicles and vehicles[ident] == service['vehicle_type'], 'XML bus type differs')
            require(ident not in owners or owners[ident] == service_id, 'bus allocated to two services')
            owners[ident] = service_id
        for route in line.findall('{*}transitRoute'):
            for dep in route.findall('./{*}departures/{*}departure'):
                key = (line_id, route.get('id'), dep.get('id'))
                require(key not in duties and dep.get('vehicleRefId') in assigned, 'duplicate/unassigned XML duty')
                duties[key] = (dep.get('vehicleRefId'), float(dep.get('departureTime')),
                               float(_attributes(dep)['simz1:endTimeSeconds']))
    require(set(allocations) == set(services) and set(owners) == set(vehicles), 'incomplete XML service fleet')
    roster_path = schedule_path.parent/'roster.json'
    records = [record for record in manifest['inputs'].values()
               if (Path(directory)/record['path']).resolve() == roster_path.resolve()]
    require(len(records) == 1, 'roster is not uniquely fingerprinted')
    roster = json.loads(checked_path(directory, records[0]).read_text(encoding='utf-8'))
    roster_duties = {(r['service_id'], r['route_id'], r['departure_id']):
                    (r['vehicle_id'], r['departure_time_s'], r['end_time_s']) for r in roster}
    require(len(roster_duties) == len(roster) and roster_duties.keys() == duties.keys(),
            'roster differs from native timetable')
    for key, (vehicle, start, end) in duties.items():
        recorded = roster_duties[key]
        require(recorded[0] == vehicle and abs(recorded[1] - start) <= 1e-7 and
                abs(recorded[2] - end) <= 1e-7, 'roster differs from native timetable')
    validate_serialized_timetable(schedule_path.read_bytes())
    expected = dict(enabled=True, road_demand_persons=road_persons, fleet_by_system=dict(declared),
                    fleet_vehicle_ids=sorted(vehicles), public_transport_vehicles_configured=total,
                    public_transport_departures_scheduled=len(duties))
    require(all(manifest['public_transport'].get(k) == v for k, v in expected.items()),
            'manifest differs from saved policy/XML/roster')
    require(metadata['simz1:scheduledExpeditions'] == str(len(duties)), 'XML departure count differs')
    return expected
