"""Departure cohorts and absolute event hours; pending trips remain censored."""
from collections import Counter, defaultdict
import math
from simz1_temporal import trip_id


class TripAudit:
    def __init__(self, horizon=None, *, fixed_day=False):
        self.horizon = horizon
        self.fixed_day=fixed_day
        self.cleanup_started=False
        self.pending, self.aborted = {}, {}  # aborted retained for API compatibility
        self.vehicle_people, self.closed_vehicles, self.last_terminal = {}, {}, {}
        self.last_terminal_sources, self.closed_vehicle_sources = {}, {}
        self.reconciliation = Counter()
        self.censoring = Counter()
        self.finished = Counter()
        self.anomalies = Counter()
        self.ordinals = Counter()
        self.cohorts, self.hours = defaultdict(Counter), defaultdict(Counter)
        self.stats = dict(departures=0, arrivals=0, completed_trips=0,
                          incomplete_trips=0, unmatched_arrivals=0, ignored_events=0)

    def consume(self, attrs):
        kind = attrs.get('type')
        if kind=='simz1DayCut' and self.fixed_day:
            if self.cleanup_started:raise ValueError('Duplicate fixed-day cleanup marker')
            self.cleanup_started=True
            return None
        if kind not in ('departure','arrival','stuckAndAbort','vehicle enters traffic','vehicle leaves traffic','PersonEntersVehicle','vehicle aborts'):
            self.stats['ignored_events'] += 1
            return None
        person = attrs.get('person')
        vehicle = attrs.get('vehicle')
        time = float(attrs.get('time','nan'))
        if not math.isfinite(time) or time < 0: raise ValueError('Evento de viaje sin tiempo valido')
        if kind == 'vehicle aborts':
            person = self.vehicle_people.get(vehicle)
            if person is None:
                self.record_terminal_anomaly(self.closed_vehicles.get(vehicle),time,'unmapped_vehicle_abort',
                                             kind, self.closed_vehicle_sources.get(vehicle))
                return None
        if not person or not math.isfinite(time) or time < 0:
            raise ValueError('Evento de viaje sin persona o tiempo valido')
        if kind == 'PersonEntersVehicle':
            # Native QSim emits boarding before a driver can enter the road.
            # Passenger modes must never steal the bus driver's identity.
            trip = self.pending.get(person)
            if trip is None or trip['mode'] != 'car':
                return None
            if not vehicle or time < trip['departure']:
                raise ValueError('Abordaje sin vehiculo o anterior a departure')
            self.bind_vehicle(trip, vehicle)
            trip['boarded'] = True
            self.reconciliation['driver_boardings_observed'] += 1
            return None
        if kind == 'vehicle leaves traffic':
            trip = self.pending.get(person)
            if trip is not None and vehicle in trip['vehicles']:
                trip['traffic_left'] = True
            return None
        hour = int(time//3600)
        if kind == 'vehicle enters traffic':
            if not vehicle: raise ValueError('Entrada de trafico sin vehicle')
            trip = self.pending.get(person)
            if trip is None:
                self.anomalies['traffic_entry_without_departure'] += 1
                return None
            if time < trip['departure']: raise ValueError('Entrada al trafico anterior a departure')
            self.bind_vehicle(trip, vehicle)
            trip['traffic_entered'] = True
            trip['traffic_left'] = False
        elif kind == 'departure':
            if person in self.pending:
                if time == self.pending[person]['departure'] and attrs.get('legMode','unknown') == self.pending[person]['mode']:
                    self.anomalies['duplicate_departures'] += 1
                    return None
                raise ValueError(f'Departure duplicado sin arrival: {person}')
            self.ordinals[person] += 1
            self.pending[person] = dict(person=person, departure=time, index=self.ordinals[person],
                                        mode=attrs.get('legMode','unknown'),vehicles=[],departure_link=attrs.get('link'),
                                        boarded=False,traffic_entered=False,traffic_left=False)
            self.last_terminal.pop(person,None)
            self.last_terminal_sources.pop(person,None)
            self.stats['departures'] += 1
            self.hours[hour]['departures'] += 1
            self.cohorts[hour]['departures'] += 1
        elif kind == 'arrival':
            self.stats['arrivals'] += 1
            self.hours[hour]['arrivals'] += 1
            trip = self.pending.pop(person,None)
            if trip is None:
                self.stats['unmatched_arrivals'] += 1
                terminal = self.last_terminal.get(person)
                self.anomalies['duplicate_arrivals' if terminal == ('completed',time) else
                               'arrival_after_abort' if terminal and terminal[0] != 'completed' else 'unmatched_arrivals'] += 1
                return None
            if time < trip['departure']:
                raise ValueError(f'Arrival anterior a departure: {person}')
            if attrs.get('legMode',trip['mode']) != trip['mode']:
                raise ValueError(f'Modo incompatible en arrival: {person}')
            self.stats['completed_trips'] += 1
            self.cohorts[int(trip['departure']//3600)]['completed'] += 1
            self.close(trip,'completed',time,kind)
            return dict(**trip, arrival=time, status='completed', censored=False, abort=None,arrival_link=attrs.get('link'))
        elif kind in ('stuckAndAbort','vehicle aborts'):
            trip = self.pending.pop(person,None)
            if trip is None:
                self.record_terminal_anomaly(self.last_terminal.get(person),time,'unmatched_abort',
                                             kind,self.last_terminal_sources.get(person))
                return None
            if time < trip['departure']: raise ValueError(f'Aborto anterior a departure: {person}')
            self.hours[hour]['abort_events'] += 1
            censored = (self.cleanup_started and time>=self.horizon) if self.fixed_day else self.horizon is not None and time >= self.horizon
            status = 'censored' if censored else 'aborted'
            self.finished[status] += 1
            self.finished['horizon_abort_events'] += censored
            cohort = self.cohorts[int(trip['departure']//3600)]
            cohort['censored' if censored else 'aborted_before_horizon'] += 1
            cohort['horizon_abort_events'] += censored
            self.close(trip,status,time,kind)
            return dict(**trip, arrival=None, status=status,censored=censored,abort=time)
        return None

    def bind_vehicle(self, trip, vehicle):
        if trip['mode'] == 'pt':
            # A generic canonical PT leg may reference a shared service vehicle;
            # that is not a unique road-driver binding. Transit audits are separate.
            if vehicle not in trip['vehicles']:
                trip['vehicles'].append(vehicle)
            return
        owner = self.vehicle_people.get(vehicle)
        if owner is not None and owner != trip['person']:
            raise ValueError(f'Vehiculo con dos conductores activos: {vehicle}')
        if vehicle not in trip['vehicles']:
            trip['vehicles'].append(vehicle)
        self.vehicle_people[vehicle] = trip['person']
        self.closed_vehicles.pop(vehicle, None)
        self.closed_vehicle_sources.pop(vehicle, None)

    @staticmethod
    def censoring_state(trip):
        if trip.get('traffic_left'):
            return 'left_traffic_without_arrival'
        if trip.get('traffic_entered'):
            return 'entered_traffic_without_arrival'
        if trip.get('boarded'):
            return 'boarded_without_traffic_entry'
        return 'no_traffic_entry_evidence'

    def close(self, trip, status, time, source=None):
        self.last_terminal[trip['person']] = (status,time)
        sources = {source} if source else set()
        self.last_terminal_sources[trip['person']] = sources
        if status == 'censored':
            self.censoring[self.censoring_state(trip)] += 1
        for vehicle in trip['vehicles']:
            if self.vehicle_people.get(vehicle) == trip['person']:
                self.vehicle_people.pop(vehicle,None)
                self.closed_vehicles[vehicle] = (status,time)
                self.closed_vehicle_sources[vehicle] = sources

    def record_terminal_anomaly(self, terminal, time, missing, kind=None, sources=None):
        # Different native terminal events for the same leg/time form a pair;
        # repeated events of the same type remain an anomaly.
        if (terminal and terminal[0] != 'completed' and terminal[1] == time
                and sources is not None and kind not in sources
                and kind in ('stuckAndAbort','vehicle aborts')
                and sources.intersection(('stuckAndAbort','vehicle aborts'))):
            sources.add(kind)
            self.reconciliation['paired_terminal_events'] += 1
            return
        self.anomalies['abort_after_arrival' if terminal and terminal[0]=='completed' else
                       'duplicate_terminal_events' if terminal and terminal[1]==time else missing] += 1
        if terminal is None and missing == 'unmapped_vehicle_abort':
            self.reconciliation['unmapped_vehicle_abort_at_horizon' if self.horizon is not None and time >= self.horizon
                                else 'unmapped_vehicle_abort_before_horizon'] += 1

    def unfinished(self):
        for person, trip in self.pending.items():
            yield dict(**trip, arrival=None, status='censored', censored=True, abort=None)

    def summary(self):
        early, censored = self.finished['aborted'], self.finished['censored'] + len(self.pending)
        counts = dict(self.stats, incomplete_trips=early+censored, aborted_trips=early+self.finished['horizon_abort_events'],
                      aborted_before_horizon=early,horizon_abort_events=self.finished['horizon_abort_events'],
                      pending_trips_at_horizon=censored, anomalies=dict(self.anomalies))
        censoring = Counter(self.censoring)
        for trip in self.pending.values():
            censoring[self.censoring_state(trip)] += 1
        counts.update(terminal_reconciliation_version=2, terminal_reconciliation=dict(self.reconciliation),
                      censoring_breakdown=dict(censoring))
        counts['completion_rate'] = self.stats['completed_trips']/self.stats['departures'] if self.stats['departures'] else None
        cohorts = {h:Counter(values) for h,values in self.cohorts.items()}
        for trip in self.unfinished():
            values = cohorts.setdefault(int(trip['departure']//3600),Counter())
            values['censored' if trip['censored'] else 'aborted_before_horizon'] += 1
            values['horizon_abort_events'] += trip['censored'] and trip['abort'] is not None
        all_hours = set(range(24)) | self.hours.keys() | cohorts.keys()
        counts['by_departure_hour'] = {str(h): {key:cohorts.get(h,{}).get(key,0) for key in
            ('departures','completed','aborted_before_horizon','censored','horizon_abort_events')} for h in sorted(all_hours)}
        counts['by_event_hour'] = {str(h): {key:self.hours.get(h,{}).get(key,0) for key in
            ('departures','arrivals','abort_events')} for h in sorted(all_hours)}
        counts['departures_after_demand_window'] = sum(v.get('departures',0) for h,v in self.hours.items() if h >= 24)
        counts['hour_semantics'] = 'Absolute hours, never modulo 24. Cohorts use actual departure hour; arrivals also counted at their own event hour.'
        return counts


def row_identity(trip):
    return trip_id(trip['person'], trip['index'])
