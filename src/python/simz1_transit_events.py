"""Observe fixed-fleet events separately from Monte Carlo demand; no event edits."""
from collections import Counter
import gzip
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def _attributes(element):
    return {item.get('name'): item.text for item in element.findall('./{*}attributes/{*}attribute')}


def _event_seconds(event, name):
    """Read a required XML attribute or mapping field without indexing children.

    Production supplies ElementTree elements; small fixtures may supply mappings.
    Both implement get(). Neither the source event nor its timestamp is changed.
    """
    try:
        value = float(event.get(name))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid transit event timing: {name} missing or non-numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid transit event timing: {name} must be finite and nonnegative")
    return value


def verified_transit_contract(directory, manifest, requested, checked_path, road_ids, links):
    """Accept only schedule/fleet files already fingerprinted in this run manifest."""
    enabled = requested.get('transit.useTransit', 'false')
    if enabled not in ('true', 'false'):
        raise ValueError('Invalid transit.useTransit')
    empty = dict(vehicle_modes={}, departures={}, domain_links=None, domain_scope='unknown')
    if enabled == 'false':
        if manifest.get('public_transport', {}).get('public_transport_vehicles_configured', 0):
            raise ValueError('Disabled transit contradicts configured fleet manifest')
        return empty
    directory = Path(directory).resolve()
    def input_document(key, root_name, artifact_key):
        value = requested.get(key)
        if not value or value == 'null':
            raise ValueError(f'Missing fixed-fleet input: {key}')
        path = (directory / value).resolve()
        record = manifest['inputs'].get(artifact_key)
        if record is None or checked_path(directory, record).resolve() != path:
            raise ValueError(f'Transit input is not fingerprinted in the run manifest: {key}')
        opener = gzip.open if str(path).endswith('.gz') else open
        with opener(path, 'rb') as stream:
            root = ET.parse(stream).getroot()
        if root.tag.split('}')[-1] != root_name:
            raise ValueError(f'Wrong transit XML root for {key}')
        return root

    schedule = input_document('transit.transitScheduleFile', 'transitSchedule', 'transit_schedule')
    fleet = input_document('transit.vehiclesFile', 'vehicleDefinitions', 'transit_vehicles')
    metadata = _attributes(schedule)
    if (metadata.get('simz1:fleetSchema') != 'fixed-fleet-v1' or
            metadata.get('simz1:passengersModeled') != 'false' or
            metadata.get('simz1:monteCarloPersons') != str(len(road_ids))):
        raise ValueError('Transit schedule lacks the fixed-fleet, passengerless, separate-N contract')
    purpose = metadata.get('simz1:purpose')
    if purpose == 'synthetic_fixture' and metadata.get('simz1:domainSynthetic') == 'true':
        scope = 'synthetic_fixture'
    elif purpose == 'production' and metadata.get('simz1:domainApproved') == 'true':
        scope = 'approved_domain'
    elif (purpose == 'weekday_scenario_v2' and metadata.get('simz1:domainApproved')=='false' and
          metadata.get('simz1:domainSynthetic')=='false' and metadata.get('simz1:minimumTurnPolicy')=='delay_until_ready_v2' and
          metadata.get('simz1:weekdayPolicySha256')):
        scope = 'computational_network'
        from simz1_weekday_transit import verify_policy_chain
        schedule_path = checked_path(directory, manifest['inputs']['transit_schedule'])
        verify_policy_chain(schedule_path, metadata, len(road_ids))
        from simz1_transit_accounting import verified_weekday_fleet
        verified_weekday_fleet(directory, manifest, len(road_ids))
    else:
        raise ValueError('Transit domain is neither approved nor explicitly synthetic')
    domain = frozenset((metadata.get('simz1:domainLinks') or '').split())
    if not domain or not domain <= links.keys() or not metadata.get('simz1:domainSource'):
        raise ValueError('Transit domain links/source are absent or outside this run network')
    types = {}
    for kind in fleet.findall('{*}vehicleType'):
        name = kind.get('id')
        mode = kind.find('{*}networkMode')
        if not name or name in types or mode is None or mode.get('networkMode') != 'bus':
            raise ValueError('Fixed public fleet requires unique explicit bus networkMode types')
        types[name] = 'bus'
    modes = {}
    for vehicle in fleet.findall('{*}vehicle'):
        name, kind = vehicle.get('id'), vehicle.get('type')
        if not name or name in modes or kind not in types:
            raise ValueError('Unknown/duplicate transit vehicle or VehicleType')
        modes[name] = types[kind]
    departures = {}
    global_departure_ids = set()
    lines = set()
    for line in schedule.findall('{*}transitLine'):
        line_id = line.get('id')
        if not line_id or line_id in lines:
            raise ValueError('Unknown/duplicate transit line')
        lines.add(line_id)
        routes = set()
        for route in line.findall('{*}transitRoute'):
            route_id = route.get('id')
            if not route_id or route_id in routes or _attributes(route).get('simz1:routePolicy') != 'fixed-v1':
                raise ValueError('Unknown/duplicate transit route or missing fixed policy')
            routes.add(route_id)
            route_links = [entry.get('refId') for entry in route.findall('./{*}route/{*}link')]
            if not route_links or any(link not in links for link in route_links):
                raise ValueError('Transit route references an unknown network link')
            if not set(route_links) <= domain:
                raise ValueError('Transit route leaves its explicit domain; exterior runtime is blocked')
            for departure in route.findall('./{*}departures/{*}departure'):
                key = (line_id, route_id, departure.get('id'))
                vehicle = departure.get('vehicleRefId')
                if not key[2] or key[2] in global_departure_ids or vehicle not in modes:
                    raise ValueError('Unknown/duplicate departure or unregistered bus')
                global_departure_ids.add(key[2])
                from simz1_run import seconds
                if departure.get('departureTime') is None:
                    raise ValueError('Missing scheduled departure time: '+key[2])
                scheduled=seconds(departure.get('departureTime'))
                if not math.isfinite(scheduled) or scheduled<0:
                    raise ValueError('Invalid scheduled departure time: '+key[2])
                departures[key] = dict(vehicle=vehicle, links=tuple(route_links), scheduled_departure=scheduled)
                if scope=='computational_network':
                    lm,rm=_attributes(line),_attributes(route)
                    departures[key].update(opens_seconds=float(lm['simz1:opensSeconds']),
                        closes_seconds=float(lm.get('simz1:departureCutoffSeconds',lm['simz1:closesSeconds'])),
                        civil_closes_seconds=float(lm['simz1:closesSeconds']),
                        transfer_kind=rm['simz1:transferKind'],transfer_seconds=float(rm['simz1:transferSeconds']))
    accounting = manifest.get('public_transport', {})
    if (metadata.get('simz1:configuredFleetSize') != str(len(modes)) or
            metadata.get('simz1:scheduledExpeditions') != str(len(departures)) or
            accounting.get('enabled') is not True or
            accounting.get('road_demand_persons') != len(road_ids) or
            accounting.get('fleet_vehicle_ids') != sorted(modes) or
            accounting.get('public_transport_vehicles_configured') != len(modes) or
            accounting.get('public_transport_departures_scheduled') != len(departures)):
        raise ValueError('Transit N/B/departure metadata differs from fingerprinted inputs')
    return dict(vehicle_modes=modes, departures=departures, domain_links=domain, domain_scope=scope,
                blocking_facilities=[s.get('id') for s in schedule.findall('./transitStops/stopFacility')
                                     if s.get('isBlocking')=='true'])


class TransitEventAudit:
    """Classify by verified fleet plus native dispatch identity, never by pt_ prefix."""
    def __init__(self, contract, road_ids, service_ids=()):
        self.contract = contract
        self.road_ids = frozenset(road_ids)
        self.other_service_ids = frozenset(service_ids)
        if self.road_ids & self.other_service_ids:
            raise ValueError('Service identities overlap private demand')
        self.fleet = frozenset(contract['vehicle_modes'])
        self.drivers = {}
        self.vehicle_departures = {}
        self.starts = set()
        self.started_boundary_duties = set()
        self.active = set()
        self.vehicles_in_traffic = set()
        self.locations = {}
        self.route_positions = {}
        self.event_counts = Counter()
        self.peak_active = 0
        self.peak_inside = 0
        self.boundary_ready = {}
        self.boundary_drivers = {}
        self.boundary_retired = set()
        self.boundary_cancelled_duties = set()
        self.boundary_duties = {(key[0], key[2]): row for key,row in contract['departures'].items()}

    def consume(self, event):
        kind = event.get('type')
        person = event.get('person')
        vehicle = event.get('vehicle') or event.get('vehicleId')
        if kind == 'simz1TransitBoundary':
            if self.contract['domain_scope']!='computational_network' or vehicle not in self.fleet:
                raise ValueError('Unregistered boundary bus event')
            driver, action = event.get('driver'), event.get('action')
            if not driver or driver in self.road_ids or driver in self.other_service_ids:
                raise ValueError('Boundary driver missing or collides with N')
            now, ready = _event_seconds(event, 'time'), _event_seconds(event, 'readyAt')
            if not math.isfinite(now) or not math.isfinite(ready) or now < 0 or ready < now:
                raise ValueError('Invalid boundary event timing')
            planned = self.boundary_duties.get((event.get('service'), event.get('departure')))
            if planned is None or planned['vehicle'] != vehicle:
                raise ValueError('Boundary event differs from configured duty')
            if driver in self.boundary_drivers and self.boundary_drivers[driver] != vehicle:
                raise ValueError('Boundary driver changed stable bus identity')
            self.boundary_drivers[driver] = vehicle
            if action == 'entry':
                if (event.get('service'), event.get('departure')) in self.boundary_cancelled_duties:
                    raise ValueError('Boundary entry of an explicitly cancelled duty')
                if vehicle in self.boundary_retired or vehicle in self.active or now+1e-6 < self.boundary_ready.get(vehicle, 0):
                    raise ValueError('Bus entered before exterior readiness or after retirement')
                if not planned['opens_seconds'] <= now < planned['closes_seconds']:
                    raise ValueError('Boundary entry outside service hours')
            elif action in ('outside_start', 'terminal_start'):
                if vehicle in self.active:
                    raise ValueError('Active native bus cannot be relocated outside network')
                expected = 'exterior' if action == 'outside_start' else 'terminal'
                if planned['transfer_kind'] != expected or ready+1e-6 < now+planned['transfer_seconds']:
                    raise ValueError('Missing minimum exterior/terminal interval')
                self.boundary_ready[vehicle] = ready
            elif action == 'cancelled_duty_after_closing':
                duty_key = (event.get('service'), event.get('departure'))
                if ready < planned['closes_seconds'] or vehicle in self.active:
                    raise ValueError('Premature duty cancellation or active bus retirement')
                if duty_key in self.boundary_cancelled_duties:
                    raise ValueError('Duplicate explicit duty cancellation')
                if duty_key in self.started_boundary_duties:
                    raise ValueError('Started duty cannot be cancelled as an unstarted expedition')
                self.boundary_cancelled_duties.add(duty_key)
                # A parked bus may have valid duties on a later civil day.
                # Keep its readiness and stable identity; do not retire the fleet.
            elif action in ('cancelled_after_closing', 'cancelled_remaining_after_closing', 'service_finished'):
                if action != 'service_finished' and ready < planned['closes_seconds']:
                    raise ValueError('Premature closing cancellation')
                self.boundary_retired.add(vehicle)
            else:
                raise ValueError('Unknown boundary action')
            self.event_counts['boundary_'+action] += 1
            return True
        if kind == 'TransitDriverStarts':
            driver = event.get('driverId')
            key = (event.get('transitLineId'), event.get('transitRouteId'), event.get('departureId'))
            planned = self.contract['departures'].get(key)
            if not driver or driver in self.road_ids or driver in self.other_service_ids or vehicle not in self.fleet:
                raise ValueError('Native transit driver missing, colliding with N, or using an unregistered bus')
            if planned is None or planned['vehicle'] != vehicle:
                raise ValueError('TransitDriverStarts does not match the fixed departure/vehicle assignment')
            if 'opens_seconds' in planned and not (planned['opens_seconds'] <= _event_seconds(event, 'time') < planned['closes_seconds']):
                raise ValueError('Actual public departure outside operating hours')
            if key in self.starts or vehicle in self.active:
                raise ValueError('Duplicate transit dispatch or simultaneous service on an active bus')
            if (key[0], key[2]) in self.boundary_cancelled_duties:
                raise ValueError('Transit dispatch of an explicitly cancelled duty')
            if driver in self.drivers and self.drivers[driver] != vehicle:
                raise ValueError('Native driver changed stable fleet vehicle identity')
            self.drivers[driver] = vehicle
            self.starts.add(key)
            self.started_boundary_duties.add((key[0], key[2]))
            self.vehicle_departures[vehicle] = key
            self.event_counts[kind] += 1
            return True
        native_driver = person in self.drivers
        registered_bus = vehicle in self.fleet
        # Membership in the two frozen sets is sufficient. A union here copies
        # all N identities for each event, including diagnostics from buses.
        if person is not None and person not in self.road_ids and person not in self.other_service_ids and not native_driver:
            raise ValueError(f'Evento con persona ajena a la corrida: {person}')
        if not native_driver and not registered_bus:
            return False
        if person in self.road_ids or person in self.other_service_ids:
            raise ValueError('Road demand person used the fixed public fleet in passengerless mode')
        if vehicle is not None and native_driver and self.drivers[person] != vehicle:
            raise ValueError('Transit event driver/vehicle identity differs from native dispatch')
        vehicle = vehicle or self.drivers.get(person)
        if vehicle not in self.vehicle_departures:
            raise ValueError('Transit movement before a verified native TransitDriverStarts event')
        link = event.get('link')
        if link is not None and link not in self.contract['domain_links']:
            raise ValueError(f'Transit movement outside its explicit domain: vehicle={vehicle} link={link} time={event.get("time")}; exterior runtime is blocked')
        path = self.contract['departures'][self.vehicle_departures[vehicle]]['links']
        if kind in ('zona1WithinDayReroute', 'zona1RerouteRejected', 'zona1InvalidCurrentRoute'):
            raise ValueError('Generic road rerouting touched a fixed-route public vehicle')
        if kind == 'vehicle enters traffic':
            if vehicle in self.active or not native_driver or event.get('networkMode', 'car') not in ('car', 'bus'):
                raise ValueError('Invalid transit traffic entry or duplicate active bus')
            if link != path[0]:
                raise ValueError(f'Transit traffic entry differs from fixed route start: vehicle={vehicle} expected={path[0]} observed={link}')
            self.active.add(vehicle)
            self.vehicles_in_traffic.add(vehicle)
            self.locations[vehicle] = link
            self.route_positions[vehicle] = dict(index=0, initial_enter=True, awaiting_enter=False)
        elif kind == 'vehicle leaves traffic':
            if vehicle not in self.active:
                raise ValueError('Transit traffic leave without active fleet vehicle')
            if self.route_positions[vehicle]['index'] != len(path)-1 or link != path[-1]:
                raise ValueError(f'Transit traffic leave before fixed route end: vehicle={vehicle} observed={link} expected={path[-1]}')
            self.active.remove(vehicle)
            self.locations.pop(vehicle, None)
            self.route_positions.pop(vehicle, None)
        elif kind == 'vehicle aborts':
            # Native cleanup/removal is an abort or censoring, never an arrival.
            self.active.discard(vehicle)
            self.locations.pop(vehicle, None)
            self.route_positions.pop(vehicle, None)
        elif kind == 'entered link':
            if vehicle not in self.active:
                raise ValueError('Transit link entry without traffic entry')
            position = self.route_positions[vehicle]
            if position['initial_enter'] and not position['awaiting_enter'] and link == path[0]:
                position['initial_enter'] = False
            else:
                index = position['index']+1
                if not position['awaiting_enter'] or index >= len(path) or link != path[index]:
                    expected = path[index] if index < len(path) else 'route_already_completed'
                    raise ValueError(f'Transit movement differs from fixed route sequence: vehicle={vehicle} expected={expected} observed={link} time={event.get("time")}')
                position.update(index=index, initial_enter=False, awaiting_enter=False)
            self.locations[vehicle] = link
        elif kind == 'left link':
            if vehicle not in self.active:
                raise ValueError('Transit link leave without traffic entry')
            position = self.route_positions[vehicle]
            if position['awaiting_enter'] or link != path[position['index']]:
                raise ValueError(f'Transit link leave differs from fixed route occurrence: vehicle={vehicle} observed={link}')
            position.update(initial_enter=False, awaiting_enter=True)
            self.locations.pop(vehicle, None)
        self.event_counts[kind] += 1
        self.peak_active = max(self.peak_active, len(self.active))
        domain = self.contract['domain_links']
        # Only these events mutate active/locations. All events still pass the
        # identity, route and domain checks above and retain their counters.
        if domain is not None and kind in ('vehicle enters traffic', 'vehicle leaves traffic', 'vehicle aborts', 'entered link', 'left link'):
            self.peak_inside = max(self.peak_inside, sum(self.locations.get(bus) in domain for bus in self.active))
        return True

    def summary(self):
        domain = self.contract['domain_links']
        unknown = sum(bus not in self.locations for bus in self.active)
        inside = None if domain is None or unknown else sum(self.locations[bus] in domain for bus in self.active)
        return dict(road_demand_persons=len(self.road_ids), public_transport_vehicles_configured=len(self.fleet),
                    public_transport_departures_scheduled=len(self.contract['departures']),
                    observed_expedition_starts=len(self.starts), transit_drivers_internal_observed=len(self.drivers),
                    public_transport_vehicle_ids_observed=sorted(set(self.drivers.values())),
                    public_transport_vehicle_ids_in_traffic=sorted(self.vehicles_in_traffic),
                    transit_drivers_added_to_demand=0, active_public_vehicles_network=len(self.active),
                    active_public_vehicles_inside_domain=inside, active_public_vehicle_location_unknown=unknown,
                    peak_active_public_vehicles_network=self.peak_active,
                    peak_public_vehicles_on_known_domain_links=None if domain is None else self.peak_inside,
                    domain_counter_scope=self.contract['domain_scope'],
                    counting_basis='native traffic events; parked fleet is not active; no inferred boundary',
                    network_mode_basis='fingerprinted transit VehicleType; native event attributes retained',
                    event_counts=dict(self.event_counts))
