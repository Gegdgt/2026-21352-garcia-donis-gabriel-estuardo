"""Additive fixed-fleet replay metadata; no private plans or invented bus legs."""
from collections import Counter
import json
import math
import re

SCHEMA = 'simz1-transit-replay-v1'


def transit_trip_id(vehicle, line, route, departure):
    return 'transit:' + json.dumps([vehicle, line, route, departure], ensure_ascii=False, separators=(',', ':'))


def validate_transit_trip(trip):
    data = trip.get('Transit')
    fields = ('vehicle_id', 'driver_id', 'line_id', 'route_id', 'departure_id')
    if (not isinstance(data, dict) or data.get('schema') != SCHEMA or
            any(not isinstance(data.get(key), str) or not data[key] for key in fields) or
            trip.get('Person_ID') is not None or trip.get('Driver_ID') != data['driver_id'] or
            trip.get('Trip_ID') != transit_trip_id(*(data[key] for key in ('vehicle_id', 'line_id', 'route_id', 'departure_id'))) or
            data.get('domain_scope') not in ('approved_domain', 'synthetic_fixture', 'computational_network') or
            not isinstance(data.get('source'), dict) or
            any(not isinstance(data['source'].get(key), str) or not re.fullmatch('[0-9a-f]{64}', data['source'][key])
                for key in ('schedule_sha256', 'vehicles_sha256')) or
            not isinstance(data.get('route_links'), list) or not data['route_links'] or
            any(not isinstance(link, str) or not link for link in data['route_links'])):
        raise ValueError('Identidad/procedencia de expedicion publica incompatible')
    if not isinstance(data.get('activity_intervals'), list):
        raise ValueError('Actividades publicas ausentes')
    previous = -math.inf
    for interval in data.get('activity_intervals', []):
        start, end = interval.get('start'), interval.get('end')
        if (type(start) not in (int, float) or not math.isfinite(start) or start < previous or
                end is not None and (type(end) not in (int, float) or not math.isfinite(end) or end < start) or
                interval.get('state') not in ('stop', 'terminal') or not interval.get('source')):
            raise ValueError('Intervalo de actividad publica incompatible')
        previous = end if end is not None else math.inf
    return data


def load_transit(context, selection, effective):
    from simz1_motion import elements, read_vehicle_definitions, physical_dimension_metadata
    from simz1_run import checked_path, parameters
    from simz1_transit_events import verified_transit_contract, _attributes
    from contextlib import closing
    import gzip
    import xml.etree.ElementTree as ET
    directory, manifest = selection['directory'], selection['manifest']
    enabled = effective.get('transit.useTransit', 'false')
    if enabled not in ('true', 'false'):
        raise ValueError('transit.useTransit invalido')
    if enabled == 'false':
        if manifest.get('public_transport', {}).get('enabled') is True:
            raise ValueError('Flota habilitada contradice la configuracion efectiva')
        return
    requested = parameters(checked_path(directory, manifest['inputs']['config']))
    if requested.get('transit.useTransit', 'false') != 'true':
        raise ValueError('Transporte efectivo sin configuracion de entrada verificada')
    with closing(elements(selection['network'], {'link'})) as rows:
        links = {row.get('id'): float(row.get('length')) for row in rows}
    freight_ids = set(manifest.get('freight_transport', {}).get('fleet_vehicle_ids', []))
    contract = verified_transit_contract(directory, manifest, requested, checked_path, set(context.profiles)-freight_ids, links)
    schedule_record, fleet_record = (manifest['inputs'][key] for key in ('transit_schedule', 'transit_vehicles'))
    path = checked_path(directory, schedule_record)
    with (gzip.open if str(path).endswith('.gz') else open)(path, 'rb') as stream:
        root = ET.parse(stream).getroot()
    facilities = {row.get('id'): row.get('linkRefId') for row in root.findall('./{*}transitStops/{*}stopFacility')}
    facility_details = {row.get('id'): dict(placement=_attributes(row).get('simz1:stopPlacement'),
        dwell_basis=_attributes(row).get('simz1:dwellBasis'), is_blocking_lane=row.get('isBlocking') == 'true')
        for row in root.findall('./{*}transitStops/{*}stopFacility')}
    for line in root.findall('{*}transitLine'):
        metadata = _attributes(line)
        for route in line.findall('{*}transitRoute'):
            stops = [row.get('refId') for row in route.findall('./{*}routeProfile/{*}stop')]
            if any(stop not in facilities or facilities[stop] not in links for stop in stops):
                raise ValueError('Parada publica sin enlace verificado')
            for departure in route.findall('./{*}departures/{*}departure'):
                row = contract['departures'][(line.get('id'), route.get('id'), departure.get('id'))]
                row.update(operator=metadata.get('simz1:operator'), service_id=metadata.get('simz1:serviceId'), stops=stops)
    types, assignments = read_vehicle_definitions(checked_path(directory, fleet_record), transit=True)
    if set(assignments) & set(context.persons):
        raise ValueError('Un vehiculo publico tambien pertenece a un plan privado')
    physical_types = {kind: physical_dimension_metadata(definition, kind, fleet_record, 'verified_transit_vehicles')
        for kind, definition in types.items() if 'physical_dimensions' in definition}
    for vehicle, kind in assignments.items():
        definition = types[kind]
        context.vehicle_speeds[vehicle] = definition['maximum_velocity_mps']
        context.vehicle_types[vehicle] = kind
        context.vehicle_pcus[vehicle] = definition['pcu']
        context.vehicle_dimensions[vehicle] = dict(definition['dimensions'], provenance=dict(
            vehicle_type=kind, artifact_source='verified_transit_vehicles', artifact_sha256=fleet_record['sha256']))
        if kind in physical_types:
            context.vehicle_physical_dimensions[vehicle] = physical_types[kind]
        context.vehicle_sources[vehicle] = 'verified_transit_vehicles'
    contract.update(facilities=facilities, facility_details=facility_details,
        source=dict(schedule_sha256=schedule_record['sha256'], vehicles_sha256=fleet_record['sha256']))
    contract['lane_exit_fractions'] = {}
    if context.lanes is True:
        lane_record = manifest.get('effective_lane_configuration_validation', {}).get('loaded_artifacts', {}).get('lanes')
        if lane_record is None:
            raise ValueError('Flota con carriles sin definiciones efectivas verificadas')
        lane_path = checked_path(directory, lane_record)
        with (gzip.open if str(lane_path).endswith('.gz') else open)(lane_path, 'rb') as stream:
            lane_root = ET.parse(stream).getroot()
        if lane_root.tag.split('}')[-1] != 'laneDefinitions':
            raise ValueError('Inventario efectivo de carriles incompatible')
        assigned_links = set()
        for assignment in lane_root.findall('{*}lanesToLinkAssignment'):
            link = assignment.get('linkIdRef')
            if link not in links or link in assigned_links:
                raise ValueError('Asignacion de carril duplicada o fuera de la red verificada')
            assigned_links.add(link)
            rows = {lane.get('id'): lane for lane in assignment.findall('{*}lane')}
            exits = contract['lane_exit_fractions'].setdefault(link, {})
            for lane_id, lane in rows.items():
                targets = [row.get('refId') for row in lane.findall('./{*}leadsTo/{*}toLane')]
                if targets:
                    if any(target not in rows for target in targets):
                        raise ValueError('Salida de carril desconocida')
                    starts = {float(rows[target].find('{*}startsAt').get('meterFromLinkEnd')) for target in targets}
                    if len(starts) != 1:
                        continue  # Ambiguous lane endpoint: never invent a stop position.
                    fraction = 1-next(iter(starts))/links[link]
                else:
                    fraction = 1
                if math.isfinite(fraction) and 0 <= fraction <= 1:
                    exits[lane_id] = fraction
        context.sources['transit_stop_lanes'] = lane_record
        contract['source']['lanes_sha256'] = lane_record['sha256']
        # MATSim 15 QLanesNetworkFactory delegates links without an assignment
        # to QLinkImpl. QueueWithBuffer handles a stop at that single queue's
        # exit, without emitting lane membership events. Absence is evidence
        # only after reading the complete, fingerprint-checked lane inventory.
        contract['single_queue_links'] = set(links) - assigned_links
    context.transit_contract = contract
    context.sources.update(transit_schedule=schedule_record, transit_vehicles=fleet_record)


class TransitReplay:
    def __init__(self, motion):
        from simz1_transit_events import TransitEventAudit
        self.motion, self.contract = motion, motion.transit_contract
        self.audit = TransitEventAudit(self.contract, set(motion.profiles)-getattr(motion, 'freight_ids', set()),
                                       getattr(motion, 'freight_ids', set()))
        self.trips, self.ordinals, self.previous, self.open_stops = {}, Counter(), {}, {}
        self.completed, self.live_lanes = set(), {}
        self.remaining = Counter(row['vehicle'] for row in self.contract['departures'].values())

    def consume(self, event, time):
        public = self.audit.consume(event)
        self.motion.transit_drivers = self.audit.drivers
        if not public:
            return
        vehicle = event.get('vehicle') or event.get('vehicleId') or self.audit.drivers.get(event.get('person'))
        kind = event.get('type')
        if kind == 'simz1TransitBoundary':
            # Exterior activities carry no drawable coordinate; never prolong a
            # terminal marker. A cancelled remainder ends the service, not a trip
            # that was never started, and must not fabricate another arrival.
            previous = self.previous.get(vehicle)
            if event.get('action') == 'cancelled_duty_after_closing':
                self.remaining[vehicle] -= 1
                if self.remaining[vehicle] < 0:
                    raise ValueError('Public duty cancellations exceed the configured roster')
                # No trip or arrival is generated for a duty that never started.
                return
            if previous is not None and event.get('action') in (
                    'service_finished', 'cancelled_remaining_after_closing', 'cancelled_after_closing'):
                previous['Transit'].update(terminal_status='service_finished',
                    service_end_confirmed=True,
                    service_end_source='native_boundary_service_end', service_end_time=time)
            return
        if kind == 'entered lane':
            self.live_lanes[vehicle] = (event.get('link'), event.get('lane'))
        elif kind in ('left lane', 'vehicle leaves traffic', 'vehicle aborts'):
            self.live_lanes.pop(vehicle, None)
        if kind == 'TransitDriverStarts':
            self.live_lanes.pop(vehicle, None)
            previous = self.previous.get(vehicle)
            if previous is not None and previous['Transit']['terminal_status'] == 'between_services' and previous['Transit']['activity_intervals'] and previous['Transit']['activity_intervals'][-1].get('state')=='terminal':
                previous['Transit']['activity_intervals'][-1]['end'] = time
            return
        trip = self.trips.get(vehicle)
        if trip is None:
            return
        trip['Last_Observed_Time'] = time
        data = trip['Transit']
        if kind == 'VehicleArrivesAtFacility':
            facility = event.get('facility')
            if facility not in data['stop_ids'] or vehicle in self.open_stops:
                raise ValueError('Parada publica desconocida o espera duplicada')
            row = dict(start=time, end=None, state='stop', facility_id=facility,
                       source='native_facility_events', link_id=self.contract['facilities'][facility],
                       **self.contract.get('facility_details', {}).get(facility, {}))
            data['activity_intervals'].append(row)
            self.open_stops[vehicle] = row
        elif kind == 'VehicleDepartsAtFacility':
            row = self.open_stops.pop(vehicle, None)
            if row is None or row['facility_id'] != event.get('facility'):
                raise ValueError('Salida de parada sin llegada nativa compatible')
            row['end'] = time
        elif kind in ('vehicle aborts', 'stuckAndAbort'):
            data.update(terminal_status='aborted_or_censored', service_end_confirmed=False)
            self.open_stops.pop(vehicle, None)
            self.trips.pop(vehicle, None)

    def departure(self, driver, time, link, base):
        vehicle = self.audit.drivers[driver]
        key = self.audit.vehicle_departures[vehicle]
        planned = self.contract['departures'][key]
        if link != planned['links'][0] or vehicle in self.trips:
            raise ValueError('Salida publica duplicada o fuera de su ruta fija')
        self.ordinals[vehicle] += 1
        data = dict(schema=SCHEMA, vehicle_id=vehicle, driver_id=driver, line_id=key[0], route_id=key[1],
                    departure_id=key[2], operator=planned.get('operator'), service_id=planned.get('service_id'),
                    domain_scope=self.contract['domain_scope'], source=self.contract['source'],
                    route_links=list(planned['links']), stop_ids=planned.get('stops', []), activity_intervals=[],
                    terminal_status='in_service', service_end_confirmed=False)
        base.update(Person_ID=None, Driver_ID=driver, Trip_ID=transit_trip_id(vehicle, *key),
                    Trip_Index=self.ordinals[vehicle], Transit=data)
        self.trips[vehicle] = base
        return base

    def arrival(self, driver, time, link):
        vehicle = self.audit.drivers[driver]
        trip = self.trips.pop(vehicle)
        data = trip['Transit']
        if link != data['route_links'][-1] or vehicle in self.audit.active or vehicle in self.open_stops:
            raise ValueError('Llegada publica sin salida de trafico o parada cerrada')
        key = (data['line_id'], data['route_id'], data['departure_id'])
        self.completed.add(key)
        self.remaining[vehicle] -= 1
        remaining = self.remaining[vehicle] > 0
        data.update(terminal_status='between_services' if remaining else 'service_finished', service_end_confirmed=not remaining,
                    completion_source='native_driver_arrival_after_traffic_exit')
        if remaining and self.contract['domain_scope'] != 'computational_network':
            data['activity_intervals'].append(dict(start=time, end=None, state='terminal',
                source='native_arrival_until_next_dispatch', facility_id=None, link_id=link))
        self.previous[vehicle] = trip
        return trip

    def stop_fraction(self, vehicle, entry, kind):
        if kind == 'VehicleDepartsAtFacility':
            return entry['fraction']
        if entry['fraction'] == 1 or self.motion.lanes is False:
            fraction, source = 1, 'MATSim15_single_queue_exit_or_native_traffic_entry'
        elif entry['link'] in self.contract.get('single_queue_links', ()):
            fraction, source = 1, 'MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment'
        else:
            observed = self.live_lanes.get(vehicle)
            fraction = (self.contract.get('lane_exit_fractions', {}).get(entry['link'], {}).get(observed[1])
                        if observed and observed[0] == entry['link'] else None)
            source = 'native_lane_membership_and_verified_lane_endpoint'
        if fraction is None or entry['fraction'] is not None and fraction < entry['fraction']:
            raise ValueError('transit_stop_position_unknown: no native lane/end-position evidence; source remains unpublished')
        self.open_stops[vehicle]['position_source'] = source
        self.open_stops[vehicle]['relative_position'] = fraction
        observed = self.live_lanes.get(vehicle)
        if observed and observed[0] == entry['link']:
            self.open_stops[vehicle]['lane_id'] = observed[1]
        return fraction
