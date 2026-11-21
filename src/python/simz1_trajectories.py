"""Boundary-preserving trajectory reconstruction, separate from full trip analysis."""
from collections import Counter
import math
from simz1_motion import MotionContext
from simz1_visual_motion import apply_visual_motion
from simz1_temporal import trip_id
from simz1_incident_replay import reject_uninstalled_native_incident


def extract(events, links, choose, color, geod, *, motion=None, incidents=None,
            lane_replay=None, signal_replay=None, stats=None, horizon=None, segment_sink=None):
    """Keep trip lifetime distinct from the intervals with drawable geometry.

    Arrival and Abort are observed terminal events, never reconstructed link
    endpoints. Observation_End is the supplied run horizon, or, when unavailable,
    the end of the input event stream. Last_Observed_Time belongs to this trip;
    unrelated events cannot extend the last measured position of its vehicle.
    """
    if horizon is not None and (not math.isfinite(horizon) or horizon < 0):
        raise ValueError('Horizonte de observacion invalido')
    motion = motion or MotionContext()
    from simz1_transit_replay import TransitReplay
    transit = TransitReplay(motion) if motion.transit_contract else None
    public_person = lambda person: transit is not None and person in transit.audit.drivers
    # A disk sink snapshots each interval immediately, retains only shared Trip
    # metadata, then evaluates one complete journey at a time after the stream.
    # The ordinary list path remains the default for small standalone exports.
    pending, agents, selected, segments = {}, {}, {}, [] if segment_sink is None else segment_sink
    trips, vehicle_trips, ordinals, final_positions = {}, {}, {}, {}
    person_vehicles = {}
    observed_vehicle_people = {}
    occupancy = {}
    persons, reconstructed, drawable = set(), set(), set()
    open_incidents, traffic_closed = {}, set()
    counts = Counter()
    previous = -math.inf
    day_cut = False

    def position(link, fraction):
        return [a+(b-a)*fraction for a,b in zip(link['from'],link['to'])]

    def relative(event):
        value = event.get('relativePosition')
        if value is None: return None
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1: raise ValueError('relativePosition fuera de [0,1]')
        return value

    def emit(vehicle, entry, end, fraction, boundary, inferred=False):
        link_id, start, person, initial, origin = entry['link'],entry['time'],entry['person'],entry['fraction'],entry['boundary']
        if end < start: raise ValueError(f'Intervalo negativo: {vehicle}')
        link = links[link_id]
        known = initial is not None and fraction is not None
        f0, f1 = (0 if initial is None else initial), (1 if fraction is None else fraction)
        if f1 < f0: raise ValueError(f'Posicion relativa retrocede dentro del enlace: {vehicle}')
        distance = link['length']*(f1-f0)
        inferred = inferred or not known
        measured = 3.6*distance/(end-start) if end > start and not inferred else None
        # simz1Priority is a fallback for files lacking native decision events;
        # do not double-count a WAIT emitted by both instrumentation layers.
        waits = {**entry.get('priority_waits', {}), **entry['waits']}
        estimate = motion.estimate(vehicle,link_id,link,start,end,distance,inferred=inferred,waits=waits,
                                   entry_change_count=entry['speed_version'])
        path = [position(link,f0),position(link,f1)]
        if path[0] == path[1]:
            estimate.update(Movement_End=start,Motion_Speed_kmh=0,Wait_Evidence='fixed_visual_geometry')
        segment = dict(vehicle=vehicle,Agent_ID=None if public_person(person) else person,Link_ID=link_id,Trip=vehicle_trips.get(vehicle),
            Profile=motion.profiles.get(person,'No disponible'),Speed_kmh=measured,**motion.metadata(person,vehicle),
            color=color(measured if measured is not None else estimate['Motion_Speed_kmh']),
            path=path,timestamps=[start,end],Inferred=inferred,Distance_m=distance,
            Boundary_Provenance=dict(start=origin,end=boundary,start_relative=initial,end_relative=fraction,
                                     distance='network_length_fraction' if known else 'assumed_endpoints'),**estimate)
        if path[0] == path[1]: segment['color'] = [255,255,255]
        if entry.get('occupancy') is not None:
            segment['Native_Occupancy'] = dict(entry['occupancy'])
        if entry.get('occupancy_progress'):
            segment['Native_Occupancy_Progress'] = [dict(row) for row in entry['occupancy_progress']]
        segments.append(segment);reconstructed.add(vehicle)
        if end > start: drawable.add(vehicle)
        counts['inferred_segments' if inferred else 'observed_boundary_segments'] += 1
        counts['zero_duration_intervals'] += end == start
        final_positions[person] = (vehicle,path[-1],end)

    def finish_observed_tail(vehicle, entry, end, boundary):
        """Keep a native queue-head observation without inventing an exit.

        A QNode WAIT proves presence at this link's downstream queue exit.
        Until a recorded link leave, that head cannot move to another link.
        A queued follower has no such position proof and remains metadata only.
        """
        if entry is None:
            return
        end = min(end, horizon) if horizon is not None else end
        if end <= entry['time']:
            return
        trip = vehicle_trips.get(vehicle)
        native_sources = {'MATSim15_QNode_native_branch', 'SimZ1_QNode_strict_receiver_v1'}
        anchors = [record['first'] for record in entry['waits'].values()
                   if record.get('position_evidence') == 'queue_exit'
                   and native_sources.intersection(record.get('sources', ()))
                   and entry['time'] <= record['first'] < end]
        if not anchors:
            if trip is not None:
                trip.setdefault('Unrepresented_Traffic_Intervals', []).append(dict(
                    vehicle=vehicle, link=entry['link'], start=entry['time'], end=end,
                    reason='open_link_without_observed_queue_exit_position',
                    presence_source=entry['boundary'], terminal_boundary=boundary))
            counts['unrepresented_open_link_intervals'] += 1
            return
        anchor = min(anchors)
        # The interpolation before the observed queue head uses two actual
        # spatial boundaries. It does not claim continuous positions were measured.
        if anchor > entry['time']:
            # Keep decision attempts only on their hold interval; do not duplicate
            # a whole native wait history on the preceding motion interval.
            approach = dict(entry, waits={}, priority_waits={})
            emit(vehicle, approach, anchor, 1, 'native_queue_exit_observed')
        held = dict(entry, time=anchor, fraction=1, boundary='native_queue_exit_observed')
        emit(vehicle, held, end, 1, boundary)
        counts['native_queue_hold_intervals'] += 1

    def close_traffic_interval(trip, vehicle, time, reason):
        if trip is not None:
            for interval in reversed(trip.get('Traffic_Intervals', ())):
                if interval['vehicle'] == vehicle and interval['end'] is None:
                    interval.update(end=time, end_event=reason)
                    return True
        return False

    for attrs in events:
        reject_uninstalled_native_incident(attrs)
        kind, time = attrs.get('type'), float(attrs['time'])
        if not math.isfinite(time) or time < previous: raise ValueError('Eventos fuera de orden temporal')
        previous = time
        if motion.fixed_day:
            from simz1_day_observation import PHYSICAL
            if kind=='simz1DayCut':
                if day_cut or time!=86400:raise ValueError('Invalid fixed-day replay cut')
                day_cut=True
            if kind in PHYSICAL and (time>86400 or day_cut):
                raise ValueError('Physical replay event after fixed-day cut')
        if kind == 'simz1OccupancyProgress':
            entry = pending.get(attrs.get('vehicle'))
            if entry and entry['link'] == attrs.get('link'):
                record = dict(time=time, front_lower_bound_m=float(attrs['modeledFrontLowerBoundMeters']),
                    source=attrs['source'], positions_observed=False, reason=attrs.get('reason'))
                for native, exported in [('nativeFrontBoundMeters','native_front_bound_m'),
                                         ('leaderFrontLowerBoundMeters','leader_front_lower_bound_m'),
                                         ('leaderFootprintMeters','leader_footprint_m'),
                                         ('nativeEarliestLinkExitTime','native_earliest_link_exit_time')]:
                    if attrs.get(native) is not None: record[exported] = float(attrs[native])
                if attrs.get('leaderVehicle'): record['leader_vehicle'] = attrs['leaderVehicle']
                if attrs.get('triggerVehicle'): record['trigger_vehicle'] = attrs['triggerVehicle']
                entry.setdefault('occupancy_progress', []).append(record)
            continue
        if kind == 'simz1OccupancyReservation':
            vehicle, action = attrs.get('vehicle'), attrs.get('action')
            if action in ('ENTER', 'TRANSFER'):
                if attrs.get('policy') != 'corridor-length-v1':
                    raise ValueError('Politica nativa de ocupacion desconocida')
                record = dict(policy='corridor-length-v1', corridor_id=attrs['corridor'],
                    model_slot=int(attrs['modelSlot']), ordinal=int(attrs['reservationOrdinal']),
                    body_length_m=float(attrs['bodyLengthMeters']), footprint_m=float(attrs['footprintMeters']),
                    event_time=time, event_action=action, link_id=attrs['link'],
                    positions_observed=False, source=attrs['source'])
                if attrs.get('passageLinks'):
                    record.update(passage_links=attrs['passageLinks'].split(','),
                                  passage_slots=[int(value) for value in attrs['passageSlots'].split(',')],
                                  receipt_link=attrs['receiptLink'])
                if attrs.get('exitLinks'):
                    record.update(exit_links=attrs['exitLinks'].split(','),
                                  exit_slots=[int(value) for value in attrs['exitSlots'].split(',')],
                                  exit_from_link=attrs['exitFromLink'], passage_kind='boundary_exit')
                occupancy[vehicle] = record
                entry = pending.get(vehicle)
                if entry and entry['link'] == attrs['link'] and (entry.get('occupancy') is None or
                        entry['occupancy']['link_id'] != attrs['link'] or entry['time'] == time):
                    # A later same-link transfer cannot date the original slot
                    # assignment in the future. LinkEnter can precede this hook
                    # at the same step, so that boundary is completed here.
                    entry['occupancy'] = dict(record)
            elif action == 'EXIT':
                occupancy.pop(vehicle, None)
            continue
        if transit is not None:
            transit.consume(attrs, time)
        event_vehicle = attrs.get('vehicle')
        event_person = attrs.get('person') or observed_vehicle_people.get(event_vehicle)
        if kind == 'vehicle enters traffic' and event_vehicle and event_person:
            previous_person = observed_vehicle_people.get(event_vehicle)
            if previous_person is not None and previous_person != event_person:
                if event_vehicle in pending:
                    raise ValueError(f'Vehiculo reasignado con intervalo abierto: {event_vehicle}')
                # A traffic exit can precede its person's arrival. Reusing that
                # vehicle transfers ownership, so the old arrival/abort must not
                # close the new owner's pending segment or observation mapping.
                previous_vehicles = person_vehicles.get(previous_person)
                if previous_vehicles is not None:
                    previous_vehicles.discard(event_vehicle)
                    if not previous_vehicles: person_vehicles.pop(previous_person,None)
                final = final_positions.get(previous_person)
                if final is not None and final[0] == event_vehicle:
                    final_positions.pop(previous_person,None)
            observed_vehicle_people[event_vehicle] = event_person
            person_vehicles.setdefault(event_person,set()).add(event_vehicle)
        observed_trip = trips.get(event_person)
        if observed_trip is not None:
            observed_trip['Last_Observed_Time'] = time
        if signal_replay is not None: signal_replay.add(attrs)
        if kind in ('zona1IncidentStart','zona1IncidentRecovered'):
            link_id = attrs.get('link')
            if link_id not in links: raise ValueError(f'Incidente en enlace desconocido: {link_id}')
            speed = float(attrs['freespeedMps']) if 'freespeedMps' in attrs else None
            motion.change(link_id,time,speed)
            if kind == 'zona1IncidentStart':
                if link_id in open_incidents: raise ValueError('Incidente duplicado sin recuperacion')
                link = links[link_id]
                record = dict(incident=True,Link_ID=link_id,start=time,end=None,
                    capacity=float(attrs['capacityPerHour']),speed=None if speed is None else speed*3.6,
                    position=[(a+b)/2 for a,b in zip(link['from'],link['to'])],icon='crash')
                open_incidents[link_id] = record
                if incidents is not None: incidents.append(record)
            else:
                if link_id not in open_incidents: raise ValueError('Recuperacion sin inicio compatible')
                open_incidents.pop(link_id)['end'] = time
            continue
        if kind in ('stuckAndAbort','vehicle aborts'):
            trip = trips.pop(event_person,None)
            if trip is not None:
                administrative=day_cut if motion.fixed_day else horizon is not None and time>=horizon
                trip.update(Abort=time,Status='censored' if administrative else 'aborted')
                # An abort proves a lifetime boundary, never movement or arrival.
                # Preserve only positions independently observed by a native WAIT.
                for vehicle in person_vehicles.pop(event_person,()):
                    entry = pending.pop(vehicle,None)
                    counts['unclosed_intervals_at_abort'] += entry is not None
                    finish_observed_tail(vehicle, entry, time, 'observation_end' if trip['Status']=='censored' else kind)
                    if close_traffic_interval(trip, vehicle, time, kind):
                        trip.update(Traffic_Retirement=time, Traffic_Retirement_Reason=kind)
                    agents.pop(vehicle,None);vehicle_trips.pop(vehicle,None)
                    observed_vehicle_people.pop(vehicle,None)
                final_positions.pop(event_person,None)
                if event_vehicle: observed_vehicle_people.pop(event_vehicle,None)
                counts['observed_public_trip_aborts' if public_person(event_person) else 'observed_trip_aborts'] += 1
            continue
        if kind in ('departure','arrival'):
            person = attrs.get('person')
            is_public = public_person(person)
            if not is_public: persons.add(person)
            link = links.get(attrs.get('link'), {})
            if kind == 'departure':
                counts['observed_public_departures' if is_public else 'observed_departures'] += 1
                final_positions.pop(person,None)
                ordinals[person] = ordinals.get(person,0)+1
                trips[person] = dict(Departure=time,Trip_ID=trip_id(person,ordinals[person]),
                    Person_ID=person,Trip_Index=ordinals[person],Status='censored',Abort=None,
                    Last_Observed_Time=time,Observation_End=horizon,
                    Observation_End_Provenance='configured_horizon' if horizon is not None else 'last_event_in_stream',
                    Origin_Node=link.get('from_node'),Destination_Node=None,Arrival=None,
                    Origin_Position=link.get('from'),Destination_Position=None,
                    Traffic_Entry=None,Traffic_Exit=None,Traffic_Retirement=None,
                    Traffic_Intervals=[],**motion.metadata(person))
                if is_public:
                    transit.departure(person, time, attrs.get('link'), trips[person])
                elif person in getattr(motion,'freight_ids',()):
                    row=motion.freight_contract[person]
                    if attrs.get('link')!=row['link_ids'][0] or abs(time-row['departure_seconds'])>1.01:
                        raise ValueError('Freight replay departure differs from verified original roster')
                    trips[person]['Freight']=dict(vehicle_id=person,route_id=row['route_id'],
                        planned_departure=row['departure_seconds'],route_link_ids=row['link_ids'],
                        roster_source=motion.freight_roster_source)
                elif motion.spatial_demand is not None:
                    key = trips[person]['Trip_ID']
                    od = motion.spatial_od.get(key)
                    if od is None or od['origin_link'] != attrs.get('link'):
                        raise ValueError(f'Salida sin OD espacial compatible: {key}')
                    trips[person]['OD'] = dict(od)
                    if od.get('od_class'):
                        trips[person].update(System_Entry=None, System_Exit=None, Observed_Duration_Seconds=None,
                                             Duration_Scope='native_vehicle_traffic_events_in_model; exterior_unknown')
                if segment_sink is not None:
                    segment_sink.register_trip(trips[person],None if is_public else person)
            elif person in trips:
                trip = trips.pop(person)
                if is_public:
                    transit.arrival(person, time, attrs.get('link'))
                if trip.get('OD') and trip['OD']['destination_link'] != attrs.get('link'):
                    raise ValueError(f'Llegada fuera del destino OD espacial: {trip["Trip_ID"]}')
                trip.update(Arrival=time,Status='completed')
                if trip['Destination_Position'] is None:
                    trip.update(Destination_Node=link.get('to_node'),Destination_Position=link.get('to'))
                final = final_positions.pop(person,None)
                # A complete traffic-exit boundary needs no fabricated movement
                # between leaves-traffic and arrival (which may be later).
                vehicles = person_vehicles.pop(person, ())
                for vehicle in vehicles:
                    entry = pending.pop(vehicle,None)
                    if entry is not None and entry['link'] == attrs.get('link'):
                        emit(vehicle,entry,time,None,'arrival',True)
                        final = None
                    elif entry is not None:
                        counts['unclosed_intervals_at_arrival'] += 1
                        final = None  # Unknown intervening route: do not draw a shortcut.
                if final is not None and final[0] not in traffic_closed and link.get('to') is not None and time > final[2]:
                    vehicle, start_position, start = final
                    distance = geod.inv(*start_position,*link['to'])[2]
                    estimate = motion.estimate(vehicle,attrs.get('link'),link,start,time,distance,inferred=True)
                    if start_position == link['to']: estimate.update(Movement_End=start,Motion_Speed_kmh=0)
                    segments.append(dict(vehicle=vehicle,Agent_ID=None if is_public else person,Link_ID=attrs.get('link'),Trip=trip,
                        Profile=motion.profiles.get(person,'No disponible'),Speed_kmh=None,**motion.metadata(person,vehicle),
                        color=color(estimate['Motion_Speed_kmh']),path=[start_position,link['to']],timestamps=[start,time],
                        Inferred=True,Distance_m=distance,Boundary_Provenance=dict(start='last_known_position',end='arrival',distance='geodesic_connector_not_observed_route'),**estimate))
                    reconstructed.add(vehicle);drawable.add(vehicle);counts['inferred_segments'] += 1
                final_positions.pop(person,None)
                for vehicle in vehicles:
                    agents.pop(vehicle,None);vehicle_trips.pop(vehicle,None)
                    observed_vehicle_people.pop(vehicle,None)
            continue
        vehicle = attrs.get('vehicle')
        if transit is not None and kind in ('VehicleArrivesAtFacility', 'VehicleDepartsAtFacility'):
            vehicle = attrs.get('vehicle') or attrs.get('vehicleId')
            entry = pending.get(vehicle)
            facility_link = transit.contract['facilities'].get(attrs.get('facility'))
            if entry is not None:
                if entry['link'] != facility_link:
                    raise ValueError('Parada nativa fuera del enlace abierto del bus')
                # MATSim 15 processes the stop at its current queue exit. With
                # lanes that can be internal to the link: require observed lane
                # membership and verified endpoint geometry, never snap stop XY.
                fraction = transit.stop_fraction(vehicle, entry, kind)
                emit(vehicle, entry, time, fraction, kind)
                pending[vehicle] = dict(link=facility_link, time=time, person=entry['person'], fraction=fraction,
                    boundary=kind, waits={}, occupancy=entry.get('occupancy'), speed_version=len(motion.changes.get(facility_link, ())))
            continue
        if kind not in ('vehicle enters traffic','vehicle leaves traffic','entered link','left link','entered lane','left lane','simz1NativeDecision','simz1Priority') or not vehicle:
            continue
        if vehicle not in selected: selected[vehicle] = choose(vehicle)
        if attrs.get('person') and not public_person(attrs['person']): persons.add(attrs['person'])
        if not selected[vehicle]: continue
        if lane_replay is not None and kind in ('entered lane','left lane','vehicle enters traffic','vehicle leaves traffic'):
            lane_replay.add(attrs)
        if kind in ('simz1NativeDecision', 'simz1Priority'):
            entry = pending.get(vehicle)
            if entry and entry['link'] == attrs.get('link') and attrs.get('decision',attrs.get('action')) == 'WAIT':
                reason = attrs.get('reason','unknown')
                source = attrs.get('source', kind)
                endpoint = (source in ('MATSim15_QNode_native_branch','SimZ1_QNode_strict_receiver_v1') or kind == 'simz1Priority' or
                            reason.startswith('priority_') or reason in ('storage_wait','intersection_conflict',
                            'signal_red','signal_redyellow','signal_not_green','admission_conflict_executed'))
                if source == 'MATSim15_queue_post_step' or reason in ('congestion_queue','signal_queue_not_green'):
                    endpoint = False
                records = entry['waits'] if kind == 'simz1NativeDecision' else entry.setdefault('priority_waits',{})
                record = records.setdefault(reason,dict(first=time,last=time,attempts=0,sources=[],
                    position_evidence='queue_exit' if endpoint else 'unknown_queue_position'))
                record['last'] = time;record['attempts'] += 1
                if source not in record['sources']: record['sources'].append(source)
                if attrs.get('waitCategory'): record['wait_category'] = attrs['waitCategory']
            continue
        if kind in ('entered lane','left lane'): continue
        link_id = attrs.get('link')
        if link_id not in links: raise ValueError(f'Enlace desconocido: {link_id}')
        person = attrs.get('person') or agents.get(vehicle) or motion.persons.get(vehicle)
        if person and not public_person(person): persons.add(person)
        if kind == 'vehicle enters traffic':
            agents[vehicle] = person
            person_vehicles.setdefault(person,set()).add(vehicle)
            vehicle_trips[vehicle] = trips.get(person)
            traffic_closed.discard(vehicle)
            fraction = relative(attrs)
            trip = vehicle_trips[vehicle]
            if trip is not None:
                if trip['Traffic_Entry'] is None: trip['Traffic_Entry'] = time
                trip['Traffic_Intervals'].append(dict(vehicle=vehicle,start=time,end=None,
                    start_event=kind,end_event=None,entry_link=link_id))
            if trip and trip.get('OD', {}).get('od_class'):
                if trip['System_Entry'] is not None or link_id != trip['OD']['origin_link']:
                    raise ValueError('Entrada al sistema duplicada o fuera del gateway/origen OD')
                trip['System_Entry'] = time
            if fraction is not None and trip:
                trip['Origin_Position'] = position(links[link_id],fraction)
                trip['Origin_Node'] = links[link_id].get('to_node') if fraction == 1 else links[link_id].get('from_node') if fraction == 0 else None
            if fraction is not None:
                pending[vehicle] = dict(link=link_id,time=time,person=person,fraction=fraction,boundary=kind,waits={},
                                       occupancy=occupancy.get(vehicle), speed_version=len(motion.changes.get(link_id,())))
            else: counts['traffic_entries_without_position'] += 1
        elif kind == 'entered link':
            entry = pending.get(vehicle)
            if entry and not (entry['boundary'] == 'vehicle enters traffic' and entry['time'] == time and entry['link'] == link_id):
                raise ValueError(f'Entrada sin salida previa: {vehicle}')
            pending[vehicle] = dict(link=link_id,time=time,person=person,fraction=0,boundary=kind,waits={},
                                   occupancy=occupancy.get(vehicle), speed_version=len(motion.changes.get(link_id,())))
            final_positions[person] = (vehicle,links[link_id]['from'],time)
        else:
            entry = pending.pop(vehicle,None)
            if entry is not None:
                if entry['link'] != link_id: raise ValueError(f'Eventos incompatibles para {vehicle}')
                emit(vehicle,entry,time,1 if kind == 'left link' else relative(attrs),kind)
            elif kind == 'left link': counts['unpaired_exits'] += 1
            if kind == 'vehicle leaves traffic':
                traffic_closed.add(vehicle)
                if entry is None: counts['unpaired_traffic_exits'] += 1
                trip = vehicle_trips.get(vehicle)
                if trip is not None:
                    trip['Traffic_Exit'] = time
                    close_traffic_interval(trip, vehicle, time, kind)
                if trip and trip.get('OD', {}).get('od_class'):
                    if trip['System_Entry'] is None or link_id != trip['OD']['destination_link']:
                        raise ValueError('Salida del sistema sin entrada o fuera del gateway/destino OD')
                    trip.update(System_Exit=time, Observed_Duration_Seconds=time-trip['System_Entry'])
                if trip and relative(attrs) is not None:
                    fraction=relative(attrs)
                    trip['Destination_Position'] = position(links[link_id],fraction)
                    trip['Destination_Node'] = links[link_id].get('to_node') if fraction == 1 else links[link_id].get('from_node') if fraction == 0 else None
                agents.pop(vehicle,None);vehicle_trips.pop(vehicle,None)
    # An event stream can end with an open link and no cleanup event. Bound
    # visualization by the observed stream, never by an unrelated future clock.
    stream_end = previous if math.isfinite(previous) else None
    if stream_end is not None:
        for vehicle,entry in pending.items():
            finish_observed_tail(vehicle,entry,stream_end,'event_stream_observation_end')
    if horizon is None and segment_sink is None:
        # Trip dictionaries are shared by their segments. Mutating metadata here
        # does not add paths, synthesize arrival events or retain unsampled trips.
        stream_end = previous if math.isfinite(previous) else None
        for segment in segments:
            if segment['Trip'] is not None: segment['Trip']['Observation_End'] = stream_end
    counts.update(observed_persons=len(persons),observed_vehicles=len(selected),reconstructed_vehicles=len(reconstructed),
                  selected_vehicles=sum(selected.values()),vehicles_without_segments=len(selected)-len(reconstructed),
                  drawable_vehicles=len(drawable),vehicles_without_drawable_segments=len(selected)-len(drawable),
                  unsampled_vehicles=len(selected)-sum(selected.values()),
                  pending_link_intervals=len(pending),segments=len(segments))
    counts['observed_departures'] += 0
    visual_summary = (apply_visual_motion(segments, settings=motion.visual_settings) if segment_sink is None else
                      segment_sink.finalize(settings=motion.visual_settings,
                          observation_end=(previous if math.isfinite(previous) else None) if horizon is None else horizon))
    if stats is not None:
        stats.update(counts)
        stats['visual_motion'] = visual_summary
        if transit is not None:
            stats['public_transport'] = transit.audit.summary()
    return segments
