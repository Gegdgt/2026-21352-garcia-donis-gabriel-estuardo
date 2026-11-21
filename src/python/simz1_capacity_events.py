"""Streaming observations of car traffic, not an estimate of physical capacity.

The caller supplies validated network/lanes and a chronological event iterable.
No files, events, configuration or QSim state are changed. Lane events never
increase link occupancy. Native WAIT records count attempts, not seconds.
"""
from collections import Counter
import math

from simz1_event_validation import MovementAudit
from simz1_native_validation import NativeDecisionAudit


class CapacityEventAudit:
    def __init__(self, links, lane_movements=None, *, start_seconds=0,
                 end_seconds=86400, evidence_limit=20, corridor_links=None):
        if (type(start_seconds) not in (int, float) or type(end_seconds) not in (int, float) or
                not math.isfinite(start_seconds) or not math.isfinite(end_seconds) or
                not 0 <= start_seconds < end_seconds <= 86400):
            raise ValueError('La ventana debe estar dentro de 0..86400 segundos')
        if type(evidence_limit) is not int or evidence_limit < 0:
            raise ValueError('evidence_limit debe ser un entero no negativo')
        self.links, self.start, self.end = links, float(start_seconds), float(end_seconds)
        self.limit = evidence_limit
        self.movement = MovementAudit(links, lane_movements)
        self.native = NativeDecisionAudit()
        self.progress_fields = Counter()
        self.counts, self.errors, self.evidence = Counter(), Counter(), []
        self.modes, self.person_modes, self.people, self.person_vehicles = {}, {}, {}, {}
        self.locations, self.pending, self.terminal = {}, {}, {}
        self.trip_counts = Counter()
        self.wait_categories, self.wait_reasons = Counter(), Counter()
        self.waits, self.wait_examples = {}, []
        self.closed_waits = self.persistent_waits = 0
        self.max_wait_span = 0.
        self.last_time = None
        self.metrics = {link: dict(max_occupancy_vehicles=0, vehicle_seconds=0.,
            entries_by_hour=[0]*24, exits_by_hour=[0]*24, network_entries=0,
            network_exits=0, closure=dict(link_entries=0, link_exits=0,
                                        network_entries=0, network_exits=0))
            for link, (_, _, modes) in links.items() if 'car' in modes}
        self.occupancy = Counter()
        self.touched = {link:self.start for link in self.metrics}
        self.corridors, self.corridor_metrics = {}, {}
        if corridor_links is not None and not isinstance(corridor_links, dict):
            raise ValueError('corridor_links debe mapear nombres a conjuntos de enlaces car')
        for name, members in (corridor_links or {}).items():
            if not isinstance(name, str) or not name.strip() or isinstance(members, (str, bytes)):
                raise ValueError('Corredor sin nombre o conjunto de enlaces valido')
            try:
                members = set(members)
            except TypeError as error:
                raise ValueError('Enlaces de corredor invalidos') from error
            if not members or not members.issubset(self.metrics):
                raise ValueError('El corredor requiere enlaces car conocidos y no vacios')
            self.corridors[name] = members
            self.corridor_metrics[name] = dict(entries_by_hour=[0]*24,
                exits_by_hour=[0]*24, origin_injections=0,
                closure=dict(entries=0, exits=0, origin_injections=0))

    def _error(self, category, message, event):
        self.errors[category] += 1
        if len(self.evidence) < self.limit:
            self.evidence.append(dict(category=category, reason=str(message),
                                      event=dict(event.attrib)))

    def _touch(self, link, time):
        now = min(self.end, max(self.start, time))
        self.metrics[link]['vehicle_seconds'] += self.occupancy[link]*(now-self.touched[link])
        self.touched[link] = now

    def _enter(self, vehicle, link, time):
        if vehicle in self.locations:
            return  # Compatible initial LinkEnter after vehicle enters traffic.
        self._touch(link, time)
        self.locations[vehicle] = link
        self.occupancy[link] += 1
        row = self.metrics[link]
        row['max_occupancy_vehicles'] = max(row['max_occupancy_vehicles'], self.occupancy[link])

    def _leave(self, vehicle, time):
        link = self.locations.pop(vehicle, None)
        if link is not None:
            self._touch(link, time)
            self.occupancy[link] -= 1

    def _link_count(self, link, field, time):
        row = self.metrics[link]
        if time == self.end:
            row['closure'][field] += 1
        elif field == 'link_entries':
            row['entries_by_hour'][int(time//3600)] += 1
        elif field == 'link_exits':
            row['exits_by_hour'][int(time//3600)] += 1
        if field in ('network_entries', 'network_exits'):
            row[field] += 1

    def _corridor_count(self, source, target, time, *, origin=False):
        for name, members in self.corridors.items():
            if origin:
                if target not in members:
                    continue
                self.corridor_metrics[name]['origin_injections'] += 1
                field = 'origin_injections'
            elif source not in members and target in members:
                field = 'entries'
            elif source in members and target not in members:
                field = 'exits'
            else:
                continue  # Internal serial links are not repeated corridor entries.
            if time == self.end:
                self.corridor_metrics[name]['closure'][field] += 1
            elif not origin:
                self.corridor_metrics[name][field+'_by_hour'][int(time//3600)] += 1

    @staticmethod
    def _wait_record(record, ending, censored):
        return dict(record, sources=sorted(record['sources']),
            observed_span_seconds=record['last_seconds']-record['first_seconds'],
            continuous_wait_seconds_lower_bound=0., close_reason=ending,
            censored_at_horizon=censored)

    def _close_wait(self, vehicle, ending, censored=False):
        record = self.waits.pop(vehicle, None)
        if record is None:
            return
        record = self._wait_record(record, ending, censored)
        self.closed_waits += 1
        self.persistent_waits += record['last_seconds'] > record['first_seconds']
        self.max_wait_span = max(self.max_wait_span, record['observed_span_seconds'])
        self.wait_examples.append(record)
        self.wait_examples.sort(key=lambda row:(-row['observed_span_seconds'],
                                                row['vehicle'], row['first_seconds']))
        del self.wait_examples[self.limit:]

    def _native(self, event, time):
        previous_samples = self.native.progress_samples
        try:
            self.native.consume(event)
        except ValueError as error:
            self._error('invalid_native_decisions', error, event)
        if self.native.progress_samples > previous_samples:
            for key in ('waitCongestion', 'turnRestrictions'):
                self.progress_fields[key] += event.get(key) is not None
        if event.get('type') != 'simz1NativeDecision':
            return
        self.counts['native_decisions'] += 1
        vehicle, link = event.get('vehicle'), event.get('link')
        if self.modes.get(vehicle) != 'car':
            self.counts['native_decisions_without_confirmed_car_mode'] += 1
        if event.get('decision') != 'WAIT':
            self._close_wait(vehicle, 'native_non_wait_decision',
                             event.get('decision') == 'ABORT' and time == self.end)
            return
        category, reason = event.get('waitCategory'), event.get('reason')
        self.wait_categories[category or 'unavailable'] += 1
        self.wait_reasons[reason or 'unavailable'] += 1
        if not vehicle or link not in self.links or not reason:
            self._error('invalid_wait_identity', 'WAIT sin vehicle/link/reason validos', event)
            return
        native_seconds = event.get('waitSeconds')
        if native_seconds is not None:
            try:
                native_seconds = float(native_seconds)
                if not math.isfinite(native_seconds) or native_seconds < 0:
                    raise ValueError('waitSeconds invalido')
            except ValueError as error:
                self._error('invalid_native_wait_seconds', error, event)
                native_seconds = None
        record = self.waits.get(vehicle)
        if record is not None and (record['link'] != link or record['reason'] != reason or
                                   record['category'] != category):
            self._close_wait(vehicle, 'different_link_or_reason')
            record = None
        if record is None:
            record = dict(vehicle=vehicle, link=link, reason=reason, category=category,
                first_seconds=time, last_seconds=time, attempts=0,
                max_observation_gap_seconds=0., native_wait_seconds_max=None, sources=set())
            self.waits[vehicle] = record
        record['max_observation_gap_seconds'] = max(record['max_observation_gap_seconds'], time-record['last_seconds'])
        record['last_seconds'] = time
        record['attempts'] += 1
        record['sources'].add(event.get('source') or 'unavailable')
        if native_seconds is not None:
            record['native_wait_seconds_max'] = max(record['native_wait_seconds_max'] or 0., native_seconds)

    def _trips(self, event, time):
        kind, person, vehicle = event.get('type'), event.get('person'), event.get('vehicle')
        if kind == 'vehicle aborts':
            person = self.people.get(vehicle)
        if kind == 'departure':
            mode = event.get('legMode')
            if person:
                self.person_modes[person] = mode
            if mode != 'car':
                self.counts['trip_events_other_or_unknown_mode'] += 1
                return
            if not person or person in self.pending:
                self._error('invalid_trip_events', 'Departure car sin persona o duplicado', event)
                return
            if time == self.end:
                self._error('invalid_trip_events', 'Departure en el cierre, fuera de demanda [inicio,fin)', event)
                return
            self.pending[person] = time
            self.terminal.pop(person, None)
            self.trip_counts['departures'] += 1
        elif kind in ('arrival', 'stuckAndAbort', 'vehicle aborts'):
            terminal = self.terminal.get(person)
            if kind == 'arrival' and terminal and terminal[0] == 'horizon_abort':
                self._error('invalid_trip_events', 'Arrival posterior a aborto de cierre', event)
                return
            if person not in self.pending:
                if terminal == ('aborted', time) and kind != 'arrival':
                    self.counts['duplicate_terminal_abort_events'] += 1
                elif event.get('legMode') == 'car' or self.person_modes.get(person) == 'car':
                    self._error('invalid_trip_events', 'Terminal car sin departure pendiente', event)
                return
            if event.get('legMode', 'car') != 'car':
                self._error('invalid_trip_events', 'Modo terminal distinto de departure car', event)
                return
            if kind == 'arrival':
                self.trip_counts['arrivals'] += 1
                self.trip_counts['completed_trips'] += 1
                self.trip_counts['arrivals_at_closure'] += time == self.end
                self.pending.pop(person)
                self.terminal[person] = ('arrived', time)
            elif time < self.end:
                self.trip_counts['aborted_before_horizon'] += 1
                self.pending.pop(person)
                self.terminal[person] = ('aborted', time)
            elif terminal != ('horizon_abort', time):
                self.trip_counts['horizon_abort_events'] += 1
                self.terminal[person] = ('horizon_abort', time)
            else:
                self.counts['duplicate_terminal_abort_events'] += 1
            for tracked in self.person_vehicles.get(person, ()):
                if self.people.get(tracked) != person:
                    continue  # A reused vehicle may already belong to a later trip.
                self._close_wait(tracked, 'trip_terminal_event', kind != 'arrival' and time == self.end)
                if kind != 'arrival' and time < self.end:
                    self._leave(tracked, time)

    def consume(self, event):
        """Consume one XML event; retain bounded evidence instead of aborting an audit."""
        self.counts['events_seen'] += 1
        try:
            time = float(event.get('time', 'nan'))
            if not math.isfinite(time) or time < 0:
                raise ValueError('Tiempo ausente, no finito o negativo')
            if self.last_time is not None and time < self.last_time:
                raise ValueError('Eventos fuera de orden temporal')
        except (TypeError, ValueError) as error:
            self._error('invalid_event_times', error, event)
            return
        self.last_time = time
        if time < self.start or time > self.end:
            self.counts['events_before_window' if time < self.start else 'events_after_window'] += 1
            return
        self.counts['events_in_window'] += 1
        kind, vehicle, link = event.get('type'), event.get('vehicle'), event.get('link')
        if kind in ('entered lane', 'left lane'):
            self.counts['lane_events_ignored'] += 1
            return
        if kind in ('simz1NativeDecision', 'simz1Progress'):
            self._native(event, time)
            return
        if kind in ('departure', 'arrival', 'stuckAndAbort', 'vehicle aborts'):
            self._trips(event, time)
            return
        if kind == 'zona1InvalidCurrentRoute':
            try:
                self.movement.consume(event)
            except ValueError as error:
                self._error('invalid_current_route_events', error, event)
            return
        if kind not in ('vehicle enters traffic', 'vehicle leaves traffic', 'entered link', 'left link'):
            return
        if kind == 'vehicle enters traffic':
            person = event.get('person')
            if person and vehicle and self.people.get(vehicle) != person:
                previous = self.people.get(vehicle)
                if previous in self.person_vehicles:
                    self.person_vehicles[previous].discard(vehicle)
            self.modes[vehicle] = event.get('networkMode') or self.person_modes.get(person)
            if person and vehicle:
                self.people[vehicle] = person
                self.person_vehicles.setdefault(person, set()).add(vehicle)
        mode = self.modes.get(vehicle)
        if mode != 'car':
            self.counts['link_events_unknown_mode' if mode is None else 'link_events_other_mode'] += 1
            if kind == 'vehicle leaves traffic':
                self.modes.pop(vehicle, None)
            return
        predecessor = self.movement.previous_leave.get(vehicle)
        try:
            self.movement.consume(event)
            if link not in self.metrics:
                raise ValueError('Enlace no habilitado para car')
            current = self.locations.get(vehicle)
            if kind == 'vehicle enters traffic' and current is not None:
                raise ValueError('Entrada al trafico duplicada sin salida')
            if kind in ('left link', 'vehicle leaves traffic') and current is not None and current != link:
                raise ValueError('Salida no coincide con ocupacion conocida')
            if kind == 'left link' and current is None:
                raise ValueError('LinkLeave sin ocupacion conocida')
        except ValueError as error:
            self._error('invalid_physical_transitions', error, event)
            return
        if kind in ('vehicle enters traffic', 'entered link'):
            self._enter(vehicle, link, time)
            self._link_count(link, 'network_entries' if kind == 'vehicle enters traffic' else 'link_entries', time)
            if kind == 'vehicle enters traffic':
                self._corridor_count(None, link, time, origin=True)
            elif predecessor is not None:
                self._corridor_count(predecessor['link'], link, time)
        else:
            self._leave(vehicle, time)
            self._close_wait(vehicle, 'link_leave' if kind == 'left link' else 'network_exit')
            self._link_count(link, 'link_exits' if kind == 'left link' else 'network_exits', time)
            if kind == 'vehicle leaves traffic':
                self.modes.pop(vehicle, None)

    def summary(self):
        """Return an idempotent JSON-compatible summary; missing evidence stays explicit."""
        links = {}
        for link, row in self.metrics.items():
            links[link] = dict(row, entries_by_hour=list(row['entries_by_hour']),
                exits_by_hour=list(row['exits_by_hour']), closure=dict(row['closure']),
                vehicle_seconds=row['vehicle_seconds']+self.occupancy[link]*(self.end-self.touched[link]),
                occupancy_at_horizon_vehicles=self.occupancy[link], occupancy_pcu=None,
                saturation_ratio=None)
        active = [self._wait_record(record, 'observation_horizon', True) for record in self.waits.values()]
        examples = sorted(self.wait_examples+active,
            key=lambda row:(-row['observed_span_seconds'], row['vehicle'], row['first_seconds']))[:self.limit]
        native = self.native.summary()
        native.update(available=bool(self.counts['native_decisions']),
            scope='all_observed_native_decisions; car mode is not encoded in the native event',
            wait_attempts_by_category=dict(sorted(self.wait_categories.items())),
            wait_attempts_by_reason=dict(sorted(self.wait_reasons.items())))
        if not native['available']:
            for key in ('forced_storage_moves', 'storage_stuck_removals'):
                native[key] = None
        native['progress_field_availability'] = {}
        for source, target in (('waitCongestion', 'wait_congestion'),
                               ('turnRestrictions', 'turn_restrictions')):
            available = bool(self.native.progress_samples) and self.progress_fields[source] == self.native.progress_samples
            native['progress_field_availability'][source] = dict(
                observed_samples=self.progress_fields[source],
                total_samples=self.native.progress_samples, available=available)
            if not available:
                native['progress'][target] = None
        if not self.native.progress_samples:
            native['progress'] = None
        progress = dict(available=bool(self.native.progress_samples),
            classification='recorded_native_progress_only' if self.native.progress_samples else 'unavailable',
            observed_classifications=dict(sorted(self.native.classifications.items())) if self.native.progress_samples else None,
            samples=self.native.progress_samples,
            max_thread_deadlocks=self.native.progress['max_thread_deadlocks'] if self.native.progress_samples else None,
            no_advancement_proven=None,
            note='No progress samples is not evidence of a stalled simulation.')
        incomplete = bool(self.counts['link_events_unknown_mode'] or self.counts['events_before_window'])
        trips = {key:self.trip_counts[key] for key in ('departures', 'arrivals', 'completed_trips',
            'aborted_before_horizon', 'horizon_abort_events', 'arrivals_at_closure')}
        trips['pending_at_horizon'] = len(self.pending)
        return dict(schema_version=1, status='invalid' if self.errors else 'incomplete' if incomplete else 'ok',
            window=dict(start_seconds=self.start, end_seconds=self.end,
                        end_is_day_closure=self.end == 86400),
            hour_bins=[dict(start_seconds=h*3600, end_seconds=(h+1)*3600) for h in range(24)],
            link_metrics=links, active_car_vehicles_at_horizon=len(self.locations),
            corridor_throughput={name:dict(row, entries_by_hour=list(row['entries_by_hour']),
                exits_by_hour=list(row['exits_by_hour']), closure=dict(row['closure']))
                for name, row in sorted(self.corridor_metrics.items())},
            occupancy_coverage='confirmed_car_events_only' if incomplete else 'observed_car_event_stream',
            trips=trips, native=native, progress=progress,
            persistent_wait=dict(episodes=self.closed_waits+len(active),
                repeated_observation_episodes=self.persistent_waits+sum(row['observed_span_seconds'] > 0 for row in active),
                max_observed_span_seconds=max([self.max_wait_span]+[row['observed_span_seconds'] for row in active]),
                examples=examples, examples_truncated=self.closed_waits+len(active) > self.limit,
                note='Span is repeated observation of the same vehicle/link/reason, not continuous waiting. '
                     'Unobserved gaps remain unknown; the defensible continuous-duration lower bound is zero. '
                     'native_wait_seconds_max uses native clocks, not seconds attributable to this reason.'),
            validation=dict(invalid_physical_transitions=self.errors['invalid_physical_transitions'],
                invalid_native_decisions=self.errors['invalid_native_decisions'],
                physical_transitions=self.movement.counts['physical_transitions'],
                counts=dict(sorted(self.errors.items())), evidence=list(self.evidence)),
            counts=dict(sorted(self.counts.items())),
            notes=['Occupancy is vehicles reconstructed from confirmed car link/network events, never lane events or PCU.',
                'Throughput counts left-link events only; network entries/exits and exact closure events remain separate.',
                'Corridor throughput counts validated outside-inside link transitions, not sums of serial-link throughput; origin injections are separate.',
                'A pending trip is not an active-network occupancy count. No arrival is invented at the horizon.',
                'Vehicle-seconds integrate observed occupancy until the requested horizon; completeness is a caller responsibility.',
                'This report does not demonstrate physical capacity, saturation, global stability or absence of deadlocks.'])


def audit_capacity_events(events, links, lane_movements=None, **kwargs):
    """Audit an event iterator in one pass, retaining no event stream in memory."""
    audit = CapacityEventAudit(links, lane_movements, **kwargs)
    for event in events:
        audit.consume(event)
    return audit.summary()
