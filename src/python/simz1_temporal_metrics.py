"""Native traffic balances for an absolute, continuous observation period.

Memory is O(demand persons + fleet + observed trips + time bins), never O(events).
Departure/boarding is not traffic entry; a traffic exit is not a destination
arrival. The domain here is explicitly the computational network, not an
inferred geographic polygon. No historical source is modified by this module.
"""
from collections import Counter, defaultdict
import csv
import gzip
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

GROUPS = ('main', 'context', 'public')
EVENTS = {'departure', 'arrival', 'vehicle enters traffic', 'vehicle leaves traffic',
          'vehicle aborts', 'stuckAndAbort', 'TransitDriverStarts', 'simz1NativeDecision',
          'simz1TransitBoundary', 'PersonEntersVehicle'}


def event_stream(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        for action, element in context:
            if action == 'end' and element.tag == 'event':
                if element.get('type') in EVENTS:
                    yield dict(element.attrib)
                element.clear()
                root.clear()


def scheduled_public_departures(path):
    """Read each absolute scheduled expedition, never infer it from fleet size."""
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        if root.tag != 'transitSchedule':
            raise ValueError('Public schedule must be a native transitSchedule')
        for action, element in context:
            if action != 'end':
                continue
            if element.tag == 'departure':
                raw = element.get('departureTime')
                try:
                    if ':' in raw:
                        hours, minutes, seconds = map(float, raw.split(':'))
                        if hours < 0 or hours != int(hours) or not 0 <= minutes < 60 or not 0 <= seconds < 60:
                            raise ValueError('Invalid civil components')
                        value = hours * 3600 + minutes * 60 + seconds
                    else:
                        value = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError('Invalid absolute public scheduled departure') from exc
                if not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid absolute public scheduled departure')
                yield value
            element.clear()
            root.clear()


class TemporalTrafficAudit:
    def __init__(self, metadata, windows, bin_seconds=900, public_schedule=None):
        self.metadata, self.windows = metadata, windows
        self.start = float(windows['simulation']['start_seconds'])
        self.end = float(windows['simulation']['end_seconds'])
        if self.start != 0 or not math.isfinite(self.end) or self.end <= self.start:
            raise ValueError('Observation requires a finite nonnegative technical origin')
        if not isinstance(bin_seconds, (int, float)) or not math.isfinite(bin_seconds) or bin_seconds <= 0:
            raise ValueError('Bin duration must be positive')
        self.step = float(bin_seconds)
        self.count = math.ceil((self.end - self.start) / self.step)
        self.bins = [Counter() for _ in range(self.count)]
        self.active, self.pending, self.drivers = {}, {}, {}
        self.active_counts, self.pending_counts = Counter(), Counter()
        self.last_time = self.start
        self.completed_bins = 0
        self.ordinals, self.trips = Counter(), {}
        self.person_trip, self.vehicle_person, self.person_vehicle = {}, {}, {}
        self.anomalies, self.outside, self.boundary_actions = Counter(), Counter(), Counter()
        self.unique_entered = set()
        self.public_schedule_known = public_schedule is not None
        self.public_planned_total = 0 if self.public_schedule_known else None
        self.public_planned_outside = 0 if self.public_schedule_known else None
        if public_schedule is not None:
            for time in public_schedule:
                if not isinstance(time, (int, float)) or not math.isfinite(time) or time < 0:
                    raise ValueError('Invalid absolute public scheduled departure')
                self.public_planned_total += 1
                if self.start <= time <= self.end:
                    self.bins[self.index(time)]['planned_public'] += 1
                else:
                    self.public_planned_outside += 1
        for person in metadata.values():
            time = person.get('planned_departure_seconds')
            if time is not None and self.start <= time < self.end:
                self.bins[self.index(time)]['planned_' + self.group(person['person_id'])] += 1

    def group(self, person):
        if person in self.drivers:
            return 'public'
        record = self.metadata.get(person)
        if record is None:
            return None
        return 'main' if record.get('population_cohort', 'main') == 'main' else 'context'

    def index(self, time):
        return min(self.count - 1, int((time - self.start) // self.step))

    def advance(self, time):
        time = min(float(time), self.end)
        if time < self.last_time:
            raise ValueError('Native event times went backwards')
        while self.last_time < time:
            index = self.index(self.last_time)
            boundary = min(self.end, self.start + (index + 1) * self.step)
            until = min(time, boundary)
            dt = until - self.last_time
            row = self.bins[index]
            for group in GROUPS:
                row['active_vehicle_seconds_' + group] += self.active_counts[group] * dt
                row['pending_person_seconds_' + group] += self.pending_counts[group] * dt
            self.last_time = until
            if until == boundary:
                for group in GROUPS:
                    row['active_end_' + group] = self.active_counts[group]
                    row['pending_end_' + group] = self.pending_counts[group]
                self.completed_bins = index + 1

    def remove_pending(self, person, row, reason):
        group = self.pending.pop(person, None)
        if group is not None:
            self.pending_counts[group] -= 1
            row[reason + '_' + group] += 1

    def remove_active(self, vehicle, row, reason):
        group = self.active.pop(vehicle, None)
        if group is not None:
            self.active_counts[group] -= 1
            row[reason + '_' + group] += 1

    def consume(self, event):
        kind = event.get('type')
        if kind not in EVENTS:
            return
        now = float(event['time'])
        if not math.isfinite(now) or now < 0:
            raise ValueError('Invalid native event time')
        self.advance(now)
        # QSim can emit a valid traffic exit/arrival at the configured final
        # second; native cleanup is at end + 1. Keep that final tick in the
        # event balance, while its zero-duration endpoint adds no occupancy area.
        if now > self.end:
            self.outside[kind] += 1
            return
        row = self.bins[self.index(now)]
        if kind == 'simz1NativeDecision':
            category = event.get('waitCategory') or event.get('wait_category')
            reason = event.get('reason', '')
            if category or 'wait' in reason or reason.startswith('signal_'):
                row['native_wait_decisions'] += 1
            return
        if kind == 'simz1TransitBoundary':
            self.boundary_actions[event.get('action', 'unknown')] += 1
            # These service events do not replace native traffic entry/exit.
            return
        person, vehicle = event.get('person'), event.get('vehicle') or event.get('vehicleId')
        if kind == 'TransitDriverStarts':
            person = event.get('driverId')
            if person in self.metadata:
                raise ValueError('Public driver collides with road demand')
            self.drivers[person] = vehicle
            row['public_expedition_starts'] += 1
            return
        if kind == 'vehicle aborts':
            person = self.vehicle_person.get(vehicle)
        group = self.group(person)
        if group is None:
            self.anomalies['unclassified_' + kind] += 1
            return
        if kind == 'departure':
            if person in self.pending or person in self.person_trip and self.person_trip[person].get('open'):
                raise ValueError('Repeated departure without a terminal event')
            self.ordinals[person] += 1
            trip = dict(person_id=person, trip_index=self.ordinals[person], group=group,
                        departure=now, traffic_entry=None, traffic_exit=None, open=True)
            self.trips[(person, self.ordinals[person])] = trip
            self.person_trip[person] = trip
            self.pending[person] = group
            self.pending_counts[group] += 1
            row['departures_' + group] += 1
        elif kind == 'PersonEntersVehicle':
            if person in self.pending and vehicle:
                self.vehicle_person[vehicle] = person
                self.person_vehicle[person] = vehicle
            # Boarding is only an identity binding; never an active increment.
        elif kind == 'vehicle enters traffic':
            if not vehicle or vehicle in self.active:
                raise ValueError('Vehicle traffic entry is duplicate or missing identity')
            self.active[vehicle] = group
            self.active_counts[group] += 1
            self.vehicle_person[vehicle] = person
            self.person_vehicle[person] = vehicle
            self.unique_entered.add(vehicle)
            row['entries_' + group] += 1
            self.remove_pending(person, row, 'pending_inserted')
            trip = self.person_trip.get(person)
            if trip is not None:
                trip['traffic_entry'] = now
            else:
                self.anomalies['traffic_entry_without_departure'] += 1
        elif kind == 'vehicle leaves traffic':
            if vehicle not in self.active:
                self.anomalies['traffic_exit_without_active'] += 1
            self.remove_active(vehicle, row, 'traffic_exits')
            trip = self.person_trip.get(person)
            if trip is not None:
                trip['traffic_exit'] = now
        elif kind == 'arrival':
            row['arrivals_' + group] += 1
            self.remove_pending(person, row, 'pending_arrival_without_entry')
            trip = self.person_trip.get(person)
            if trip is not None:
                trip.update(open=False, arrival=now)
            if self.person_vehicle.get(person) in self.active:
                self.anomalies['arrival_without_traffic_exit'] += 1
            # Arrival never subtracts active again: native traffic exit does.
        elif kind in ('vehicle aborts', 'stuckAndAbort'):
            vehicle = vehicle or self.person_vehicle.get(person)
            self.remove_active(vehicle, row, 'explicit_removals')
            self.remove_pending(person, row, 'pending_explicit_removals')
            trip = self.person_trip.get(person)
            if trip is not None:
                trip.update(open=False, abort=now)

    def finish(self):
        self.advance(self.end)
        # The final snapshot is after events at exactly end, unlike interior
        # right-boundary snapshots, which precede that boundary's next bin.
        for group in GROUPS:
            self.bins[-1]['active_end_' + group] = self.active_counts[group]
            self.bins[-1]['pending_end_' + group] = self.pending_counts[group]
        records, previous = [], Counter()
        for index, values in enumerate(self.bins):
            start, end = self.start + index * self.step, min(self.end, self.start + (index + 1) * self.step)
            row = dict(start_seconds=start, end_seconds=end, duration_seconds=end-start,
                       final_boundary_inclusive=index == self.count - 1)
            row.update(values)
            for group in GROUPS:
                row['active_start_' + group] = previous['active_' + group]
                row['pending_start_' + group] = previous['pending_' + group]
                for prefix in ('planned', 'departures', 'entries', 'traffic_exits', 'explicit_removals', 'arrivals',
                               'pending_inserted', 'pending_arrival_without_entry', 'pending_explicit_removals',
                               'active_end', 'pending_end', 'active_vehicle_seconds', 'pending_person_seconds'):
                    row.setdefault(prefix + '_' + group, 0)
                row['active_mean_' + group] = row['active_vehicle_seconds_' + group] / (end-start)
                row['pending_mean_' + group] = row['pending_person_seconds_' + group] / (end-start)
                row['active_balance_error_' + group] = (previous['active_' + group] + row['entries_' + group]
                    - row['traffic_exits_' + group] - row['explicit_removals_' + group] - row['active_end_' + group])
                row['pending_balance_error_' + group] = (previous['pending_' + group] + row['departures_' + group]
                    - row['pending_inserted_' + group] - row['pending_arrival_without_entry_' + group]
                    - row['pending_explicit_removals_' + group] - row['pending_end_' + group])
                previous['active_' + group] = row['active_end_' + group]
                previous['pending_' + group] = row['pending_end_' + group]
            if not self.public_schedule_known:
                row['planned_public'] = None
            records.append(row)
        return records


def cohort_rows(table, metadata, audit, policy):
    from simz1_trip_table import rows
    groups = defaultdict(Counter)
    study = policy['windows']['study']
    for row in rows(table):
        person = metadata.get(row['person_id'])
        if person is None:
            continue
        cohort = person.get('population_cohort', 'main')
        planned = person.get('planned_departure_seconds', row['departure'])
        hour = math.floor((planned - study['start_seconds']) / 3600)
        group = groups[(cohort, hour)]
        group['trips'] += 1
        group[row['status']] += 1
        trip = audit.trips.get((row['person_id'], row['trip_index']), {})
        entry = trip.get('traffic_entry')
        if row['status'] == 'censored':
            group['censored_never_entered' if entry is None else 'censored_entered'] += 1
        if entry is not None:
            group['inserted_trips'] += 1
            group['insertion_wait_seconds_sum'] += entry - row['departure']
        group['departure_delay_seconds_sum'] += row['departure'] - planned
        if row['status'] == 'completed':
            group['valid_duration_seconds_sum'] += row['duration_seconds']
        group['observed_departure_after_study'] += row['departure'] >= study['end_seconds']
    result = []
    for (cohort, hour), value in sorted(groups.items()):
        result.append(dict(cohort=cohort, planned_hour_relative_to_study=hour, **value,
            completion_rate=value['completed']/value['trips'],
            mean_insertion_wait_seconds=value['insertion_wait_seconds_sum']/value['inserted_trips'] if value['inserted_trips'] else None,
            mean_valid_duration_seconds=value['valid_duration_seconds_sum']/value['completed'] if value['completed'] else None))
    return result


def _write_csv(path, records):
    fields = list(dict.fromkeys(key for row in records for key in row))
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def analyze_temporal(events, table, metadata, policy, destination, run_id, iteration, *, public_schedule=None):
    destination = Path(destination)
    audit = TemporalTrafficAudit(metadata, policy['windows'], public_schedule=public_schedule)
    for event in event_stream(events):
        audit.consume(event)
    series = audit.finish()
    cohorts = cohort_rows(table, metadata, audit, policy)
    errors = [dict(bin=index, key=key, value=value) for index, row in enumerate(series)
              for key, value in row.items() if 'balance_error' in key and value]
    if errors:
        raise ValueError('Native vehicle conservation failed: ' + str(errors[:5]))
    if audit.anomalies:
        raise ValueError('Native temporal identity/event anomalies: ' + str(dict(audit.anomalies)))
    report = dict(schema_version='simz1-temporal-metrics-v1', run_id=run_id, iteration=iteration,
        temporal_policy=policy, domain='computational_network',
        definitions=dict(active='Native vehicle enters traffic until vehicle leaves traffic or explicit removal; arrival is a separate outcome and never subtracted twice.',
            pending='Observed driver departure without native traffic entry; boarding alone is not entry.',
            snapshots='Interior active_end/pending_end precede the interval right boundary; the final technical snapshot includes native events at exactly observation end.',
            means='Exact integral of piecewise-constant counts divided by actual interval duration; snapshots are not summed as unique vehicles.',
            cohort='Immutable planned departure and main/context identity; valid arrivals after study midnight retain their departure cohort.',
            waits='native_wait_decisions counts emitted decision events, not unique vehicles or seconds.',
            observation_end='Events at exactly technical end remain observed, consistent with valid canonical arrivals. Later cleanup events are separately counted; occupancy integrals cover [start,end).',
            planned_public='Expeditions from the validated absolute native transit schedule, independent of observed starts and fleet size. Null means no validated schedule was available, not zero service.',
            exits='Traffic exits are computational-network exits, not assumed geographic boundary crossings or destination arrivals.'),
        conservation=dict(status='passed', errors=errors), native_anomalies=dict(audit.anomalies),
        outside_observation_events=dict(audit.outside), public_boundary_actions=dict(audit.boundary_actions),
        unique_vehicles_ever_entered=len(audit.unique_entered),
        public_schedule=dict(status='available' if audit.public_schedule_known else 'unavailable',
            planned_expeditions=audit.public_planned_total, outside_observation=audit.public_planned_outside),
        active_at_observation_end=dict(audit.active_counts), pending_at_observation_end=dict(audit.pending_counts),
        bins=len(series), cohorts=cohorts)
    _write_csv(destination/'flujo_ocupacion_15min.csv', series)
    _write_csv(destination/'cohortes_temporales.csv', cohorts)
    (destination/'metricas_temporales.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    render(series, cohorts, destination, policy, run_id, iteration)
    return report


def render(series, cohorts, destination, policy, run_id, iteration):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    start = policy['windows']['study']['start_seconds']
    x = [(row['start_seconds'] - start)/3600 for row in series]
    title = f'{run_id} | iteracion {iteration} | horas relativas al inicio de jornada'
    definitions = (
        ('demanda_salida_insercion.png', 'Viajes/eventos por intervalo', [('planned_main', 'Planificada principal'), ('departures_main', 'PersonDeparture principal'), ('entries_main', 'Entrada efectiva principal'), ('departures_context', 'Salidas contexto')]),
        ('ocupacion_y_pendientes.png', 'Vehiculos activos / personas pendientes', [('active_mean_main', 'Activos principales: promedio temporal'), ('active_end_main', 'Activos principales: fotografia al limite'), ('pending_mean_main', 'Pendientes principales: promedio temporal'), ('active_mean_context', 'Activos contexto: promedio'), ('active_mean_public', 'Buses activos: promedio')]),
        ('llegadas_y_salidas.png', 'Eventos por intervalo (no sumar ambas curvas)', [('arrivals_main', 'Llegadas validas principales'), ('traffic_exits_main', 'Salidas nativas de trafico principales'), ('arrivals_public', 'Llegadas publicas'), ('traffic_exits_public', 'Salidas de trafico publicas')]),
    )
    for filename, ylabel, fields in definitions:
        fig, ax = plt.subplots(figsize=(13, 5))
        for key, label in fields:
            ax.plot(x, [row.get(key, 0) for row in series], label=label, linewidth=1.3)
        ax.axvspan(0, 24, color='#d9edf7', alpha=.22, label='Jornada principal')
        ax.set(xlabel='Hora absoluta relativa a la jornada (negativa = calentamiento; >24 = extension)', ylabel=ylabel, title=title)
        ax.legend(fontsize=8); ax.grid(alpha=.2); fig.tight_layout()
        fig.savefig(Path(destination)/filename, dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(13, 5))
    selected = [row for row in cohorts if row['cohort'] == 'main']
    for key, label in [('completed', 'Llegadas validas'), ('censored_never_entered', 'Censurados sin entrar'), ('censored_entered', 'Censurados que circularon')]:
        ax.plot([row['planned_hour_relative_to_study'] for row in selected], [row.get(key, 0) for row in selected], 'o-', label=label)
    ax.set(xlabel='Hora planificada de la cohorte principal', ylabel='Viajes (incluye censura, no imputa duracion)', title=title)
    ax.legend(); ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(Path(destination)/'cohortes_y_censura.png', dpi=160); plt.close(fig)
