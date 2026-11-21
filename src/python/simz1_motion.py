"""Replay estimates from verified vehicle inputs and recorded speed changes.

QSim 15 evaluates speed when entering each queue, not by continuously integrating
acceleration. If an interval crosses speed changes and internal queue-entry
times are unavailable, preserve its full duration without inventing a wait.
"""
import gzip
import json
import math
import xml.etree.ElementTree as ET
from contextlib import closing
from procesar_eventos_z1 import movement_end_time


def elements(path, wanted):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start','end'))
        _, root = next(context)
        for action, element in context:
            element.tag = element.tag.rsplit('}',1)[-1]
            if action == 'end' and element.tag in wanted:
                yield element
                element.clear(); root.clear()


def read_vehicle_definitions(path, *, transit=False):
    """Read recorded types without guessing defaults or deriving geometry from PCU."""
    types, assignments = {}, {}
    with closing(elements(path, {'vehicleType','vehicle'})) as source:
        for element in source:
            ident = element.get('id')
            if not ident: raise ValueError('Vehiculo o tipo sin ID')
            if element.tag == 'vehicle':
                if ident in assignments: raise ValueError(f'Vehiculo duplicado: {ident}')
                assignments[ident] = element.get('type')
            else:
                if ident in types: raise ValueError(f'Tipo de vehiculo duplicado: {ident}')
                maximum = element.find('maximumVelocity')
                speed = float(maximum.get('meterPerSecond')) if maximum is not None else None
                if speed is not None and (not math.isfinite(speed) or speed <= 0):
                    raise ValueError(f'Limite de vehiculo invalido: {ident}')
                equivalent = element.find('passengerCarEquivalents')
                pcu = float(equivalent.get('pce')) if equivalent is not None else None
                if pcu is not None and (not math.isfinite(pcu) or pcu <= 0):
                    raise ValueError(f'PCU de vehiculo invalido: {ident}')
                types[ident] = dict(maximum_velocity_mps=speed, pcu=pcu)
                attrs = {a.get('name'): a.text for a in element.findall('attributes/attribute')}
                # A VehicleType records configured dimensions, independently of
                # the visual opt-in below and independently of queue PCU. An old
                # or incomplete XML may omit them: never guess a physical body.
                physical = configured_dimensions(element, attrs)
                if physical is not None:
                    types[ident]['physical_dimensions'] = physical
                # Keep the explicit visual opt-in separate from configured
                # VehicleType evidence. Existing SQLite payloads are untouched.
                if transit or attrs.get('simz1AgentSchema') == 'simz1-road-profiles-v1':
                    length, width = element.find('length'), element.find('width')
                    dimension_source = ('verified_transit_vehicles:' + attrs.get('simz1:dimensionsBasis', '')
                                        if transit else attrs.get('simz1DimensionsSource'))
                    mode = element.find('networkMode')
                    if transit and (mode is None or mode.get('networkMode') != 'bus' or
                                    not attrs.get('simz1:dimensionsBasis')):
                        raise ValueError(f'Tipo publico sin modo/dimensiones explicitos: {ident}')
                    if length is None or width is None or not dimension_source:
                        raise ValueError(f'Dimensiones/procedencia ausentes: {ident}')
                    length, width = float(length.get('meter')), float(width.get('meter'))
                    if not all(math.isfinite(v) and v > 0 for v in (length, width)):
                        raise ValueError(f'Dimensiones invalidas: {ident}')
                    types[ident]['dimensions'] = dict(length_m=length, width_m=width,
                        source=dimension_source, assumed=(attrs.get('simz1:dimensionsBasis') != 'verified' if transit
                            else attrs.get('simz1DimensionsAssumed') == 'true'),
                        **({'articulated': attrs.get('simz1:bodyModel') != 'rigid'} if transit else {}))
    if any(kind not in types for kind in assignments.values()):
        raise ValueError('Referencia a tipo de vehiculo desconocido')
    return types, assignments


def configured_dimensions(element, attrs):
    """Optional XML evidence; malformed legacy dimensions do not stop replay."""
    values = []
    for name in ('length', 'width'):
        nodes = element.findall(name)
        if len(nodes) != 1:
            return None
        try:
            value = float(nodes[0].get('meter'))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        values.append(value)
    assumed = {'true': True, 'false': False}.get(attrs.get('simz1DimensionsAssumed'))
    if attrs.get('simz1:dimensionsBasis') in ('scenario_assumption', 'verified'):
        assumed = attrs['simz1:dimensionsBasis'] == 'scenario_assumption'
    return dict(length_m=values[0], width_m=values[1], source='MATSim_VehicleType_XML',
                nature='configured', measurement_status='not_established_by_vehicle_type', assumed=assumed)


def physical_dimension_metadata(definition, kind, record, source):
    """Attach the exact verified XML artifact without claiming observed geometry."""
    return dict(definition['physical_dimensions'], provenance=dict(vehicle_type=kind,
        artifact_source=source, artifact_path=record['path'], artifact_sha256=record['sha256']))


def read_vehicles(path):
    """Keep the historical (speed-by-type, assignments) interface."""
    types, assignments = read_vehicle_definitions(path)
    return {kind: record['maximum_velocity_mps'] for kind, record in types.items()}, assignments


class MotionContext:
    def __init__(self, vehicle_speeds=None, profiles=None, persons=None, *, lanes=None, dynamic_known=True,
                 visual_settings=None):
        from simz1_visual_motion import normalize_settings
        self.vehicle_speeds = vehicle_speeds or {}
        self.profiles, self.persons = profiles or {}, persons or {}
        self.agent_types, self.agent_schemas, self.declared_vehicle_types = {}, {}, {}
        self.vehicle_types, self.vehicle_pcus = {}, {}
        self.vehicle_dimensions = {}
        self.vehicle_physical_dimensions = {}
        self.vehicle_metadata_source = None
        self.vehicle_sources, self.transit_drivers = {}, {}
        self.transit_contract = None
        self.lanes, self.dynamic_known = lanes, dynamic_known
        self.changes = {}
        self.sources = {}
        self.spatial_demand = None
        self.spatial_od = {}
        self.fixed_day = False
        self.visual_settings = normalize_settings(visual_settings)

    def metadata(self, person, vehicle=None):
        """Person category and recorded vehicle type are distinct identities.

        Missing person categories remain unknown, including historical profiles
        whose names happen to match a category in the new schema.
        """
        vehicle = vehicle or self.transit_drivers.get(person)
        recorded_type = self.vehicle_types.get(vehicle)
        declared_type = self.declared_vehicle_types.get(person)
        result = dict(Agent_Type=self.agent_types.get(person), Agent_Schema=self.agent_schemas.get(person),
                    Vehicle_Type=recorded_type if recorded_type is not None else declared_type,
                    Vehicle_Type_Source=self.vehicle_sources.get(vehicle, self.vehicle_metadata_source) if recorded_type is not None else
                        'person_attribute' if declared_type is not None else None,
                    Vehicle_PCU=self.vehicle_pcus.get(vehicle))
        if vehicle in self.vehicle_dimensions:
            result.update(Vehicle_Dimensions=self.vehicle_dimensions[vehicle], Driving_Profile=self.profiles.get(person))
        if vehicle in self.vehicle_physical_dimensions:
            result['Vehicle_Physical_Dimensions'] = self.vehicle_physical_dimensions[vehicle]
        if self.transit_contract and vehicle in self.transit_contract['vehicle_modes']:
            result.update(Vehicle_Family='bus', Driver_ID=person, Agent_Type=None, Agent_Schema=None, Driving_Profile=None)
        return result

    def change(self, link, time, speed):
        if not math.isfinite(time) or speed is not None and (not math.isfinite(speed) or speed <= 0):
            raise ValueError('Cambio temporal de velocidad invalido')
        series = self.changes.setdefault(link, [])
        if series and time < series[-1][0]: raise ValueError('Cambios de velocidad fuera de orden')
        series.append((time,speed))

    def estimate(self, vehicle, link_id, link, start, end, distance, *, inferred=False, waits=None, entry_change_count=None):
        if not all(math.isfinite(v) for v in (start,end,distance)) or end < start or distance < 0:
            raise ValueError('Intervalo o distancia invalida')
        speed = link.get('freespeed')
        changes = self.changes.get(link_id, [])
        changed_inside = False
        interval_speeds = []
        for index, (time, value) in enumerate(changes):
            # Equal timestamps retain event order: a change recorded after entry
            # cannot retroactively replace the entry speed of that queue.
            if time <= start and (entry_change_count is None or index < entry_change_count): speed = value
            elif time < end:
                changed_inside = True
                interval_speeds.append(value)
        cap = self.vehicle_speeds.get(vehicle)
        if any(value is not None and (not math.isfinite(value) or value <= 0) for value in (speed,cap)):
            raise ValueError('Limite de velocidad invalido')
        reason = ('inferred_interval' if inferred else 'unknown_vehicle_limit' if cap is None else
                  'unknown_link_speed' if speed is None else 'unregistered_network_changes' if not self.dynamic_known else
                  'speed_change_with_unknown_internal_queue_entry' if changed_inside and self.lanes is not False else None)
        move_end = end if reason else movement_end_time(start,end,distance,speed,vehicle_speed=cap)
        method = 'bounded_interval_fallback' if reason else 'minimum_link_vehicle_speed_at_queue_entry'
        evidence = 'none_estimated' if move_end == end else 'estimated_residual_unknown_cause'
        endpoint_waits = {key:value for key,value in (waits or {}).items()
                          if value.get('position_evidence', 'queue_exit') == 'queue_exit'}
        if endpoint_waits:
            # Native QNode WAIT locates the offered vehicle at the exit. Subsequent
            # residence here ends only at the actual link/traffic exit event.
            move_end = max(start,min(end,min(v['first'] for v in endpoint_waits.values())))
            method, evidence = 'native_queue_wait_boundary', 'native_wait_observation'
        elif waits:
            # The post-step queue diagnostic observes delay before the vehicle is
            # offered to the node. It cannot locate it at the end of the link.
            evidence = 'native_queue_delay_position_unknown'
        if distance == 0:
            move_end = start
            method, evidence = 'zero_distance_boundary', 'fixed_boundary_position'
        return dict(Movement_End=move_end,
                    Motion_Speed_kmh=3.6*distance/(move_end-start) if move_end > start else 0,
                    Wait_Evidence=evidence, Observed_Waits=waits or {},
                    Motion_Provenance=dict(method=method, fallback_reason=reason,
                        vehicle_limit_mps=cap, link_speed_at_entry_mps=speed,
                        minimum_link_speed_in_interval_mps=min([speed,*interval_speeds])
                            if speed is not None and all(value is not None for value in interval_speeds) else None,
                        changes_inside_interval=changed_inside, continuous_position_observed=False))


def load_selected(selection, *, visual_settings=None):
    from simz1_run import checked_path, parameters
    from simz1_gateway_od import validated_spatial_demand, validate_od_metadata
    from simz1_temporal import trip_id
    directory, manifest = selection['directory'], selection['manifest']
    params = parameters(checked_path(directory,manifest['effective_config']))
    context = MotionContext(lanes={'true':True,'false':False}.get(params.get('qsim.useLanes')),
        dynamic_known=params.get('network.inputChangeEventsFile') in (None,'','null'),
        visual_settings=visual_settings)
    context.spatial_demand = validated_spatial_demand(directory, manifest)
    from simz1_day_observation import enabled
    context.fixed_day = enabled(manifest)
    record = manifest.get('effective_vehicles')
    source_kind = 'effective_vehicles'
    if record is None:
        # Older manifests: only use an already fingerprinted input. Never load
        # an arbitrary output_vehicles.xml or another run's vehicle definitions.
        requested = parameters(checked_path(directory,manifest['inputs']['config']))
        wanted = (directory/requested.get('vehicles.vehiclesFile','missing')).resolve()
        record = next((v for v in manifest['inputs'].values() if (directory/v['path']).resolve() == wanted), None)
        source_kind = 'verified_input_vehicles_legacy'
    if record is not None:
        types, assignments = read_vehicle_definitions(checked_path(directory,record))
        context.vehicle_speeds = {vehicle:types[kind]['maximum_velocity_mps'] for vehicle,kind in assignments.items()}
        context.vehicle_types = assignments
        context.vehicle_pcus = {vehicle:types[kind]['pcu'] for vehicle,kind in assignments.items()}
        context.vehicle_dimensions = {vehicle: dict(types[kind]['dimensions'], provenance=dict(
            vehicle_type=kind, artifact_source=source_kind, artifact_sha256=record['sha256']))
            for vehicle, kind in assignments.items() if 'dimensions' in types[kind]}
        # Reuse immutable-by-convention type evidence across all assigned cars;
        # a large legacy run need not allocate one provenance dict per vehicle.
        physical_types = {kind: physical_dimension_metadata(definition, kind, record, source_kind)
            for kind, definition in types.items() if 'physical_dimensions' in definition}
        context.vehicle_physical_dimensions = {vehicle: physical_types[kind]
            for vehicle, kind in assignments.items() if kind in physical_types}
        context.vehicle_metadata_source = source_kind
        context.sources[source_kind] = record
    with closing(elements(selection['plans'], {'person'})) as source:
        for person in source:
            ident = person.get('id')
            spatial_text = person.findtext("attributes/attribute[@name='simz1SpatialOD']")
            from simz1_freight import is_freight
            if context.spatial_demand is not None and not is_freight(person):
                ledger = json.loads(person.findtext("attributes/attribute[@name='simz1Trips']", default='null'))
                spatial = json.loads(spatial_text or 'null')
                if (not isinstance(ledger, list) or not ledger or not isinstance(spatial, dict) or
                        set(spatial) != {trip_id(ident, index) for index in range(1, len(ledger)+1)}):
                    raise ValueError(f'Metadatos OD espaciales ausentes o incompatibles: {ident}')
                for index, planned in enumerate(ledger, 1):
                    key = trip_id(ident, index)
                    od = spatial[key]
                    validate_od_metadata(od, context.spatial_demand,person_id=ident)
                    if (planned.get('id') != key or planned.get('index') != index or
                            planned.get('origin_link') != od['origin_link'] or
                            planned.get('destination_link') != od['destination_link']):
                        raise ValueError(f'OD espacial no corresponde al viaje planificado: {key}')
                    if key in context.spatial_od:
                        raise ValueError(f'Identidad OD espacial duplicada: {key}')
                    context.spatial_od[key] = dict(od)
            elif spatial_text is not None:
                raise ValueError('Planes con OD espacial sin dominio validado en el manifiesto')
            context.profiles[ident] = person.findtext("attributes/attribute[@name='drivingProfile']",default='No disponible')
            for attribute, destination in (('simz1AgentType', context.agent_types),
                                           ('simz1AgentSchema', context.agent_schemas),
                                           ('effectiveVehicleType', context.declared_vehicle_types)):
                value = person.findtext(f"attributes/attribute[@name='{attribute}']")
                if value not in (None, '', 'null'):
                    destination[ident] = value
            raw = person.findtext("attributes/attribute[@name='vehicles']")
            vehicles = set(json.loads(raw).values()) if raw else set()
            vehicles.update(route.get('vehicleRefId') for route in person.findall('.//route')
                            if route.get('vehicleRefId') not in (None,'null'))
            for vehicle in vehicles:
                # Vehicle reuse is possible; native enters-traffic is authoritative.
                if vehicle in context.persons and context.persons[vehicle] != ident: context.persons[vehicle] = None
                else: context.persons[vehicle] = ident
    context.sources['plans'] = manifest['results'][str(selection['iteration'])]['plans']
    from simz1_transit_replay import load_transit
    load_transit(context, selection, params)
    freight = manifest.get('freight_transport', {})
    if freight.get('enabled'):
        from simz1_freight import verified_contract, presentation_dimensions
        contract = verified_contract(directory, manifest)
        context.freight_ids = frozenset(contract)
        context.freight_contract=contract
        context.freight_roster_source=manifest['inputs']['input:freight-weekday/roster.json']
        # New snapshots declare one native/presentation body. Historical
        # snapshots retain their separately recorded physical and visual sizes.
        public_type = next((v for k,v in context.vehicle_dimensions.items()
                            if context.vehicle_types.get(k) == 'TuBus_RigidProxy'), None)
        service_path=checked_path(directory, manifest['inputs']['input:freight-weekday/service.json'])
        service=json.loads(service_path.read_text(encoding='utf-8'))
        size = presentation_dimensions(service, public_type)
        for ident in contract:
            context.vehicle_dimensions[ident] = dict(size)
    return context
