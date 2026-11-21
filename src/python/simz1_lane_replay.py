"""Preserve MATSim lane membership events without inventing lane coordinates.

MATSim 15 LaneEnterEvent/LaneLeaveEvent contain time, vehicle, link and lane.
They do not contain a longitudinal position, a lateral position or overtaking.
The replay retains file order for events at the same time. Traffic boundaries
clear membership, including the final link when no LaneLeaveEvent is emitted.
"""
import math


class LaneEventReplay:
    def __init__(self, links, *, event_sink=None):
        self.links = links
        self.events = [] if event_sink is None else event_sink
        self.last = {}
        self.vehicles = set()
        self.queues = set()
        self.entries = 0
        self.exits = 0
        self.unpaired_exits = 0
        self.entries_without_lane_exit = 0

    def add(self, attrs):
        kind = attrs.get('type')
        if kind not in ('entered lane', 'left lane', 'vehicle enters traffic', 'vehicle leaves traffic'):
            return
        vehicle = attrs.get('vehicle')
        if not vehicle:
            if kind in ('entered lane', 'left lane'):
                raise ValueError('Evento de carril sin vehiculo')
            return
        previous = self.last.get(vehicle)
        if kind in ('vehicle enters traffic', 'vehicle leaves traffic'):
            # Do not manufacture a lane exit from an arrival or traffic event.
            if previous and previous['type'] == 'entered lane':
                time = self._time(attrs)
                if time < previous['time']:
                    raise ValueError(f'Eventos de carril fuera de orden: {vehicle}')
                self.events.append(dict(type=kind, time=time, vehicle=vehicle))
                self.entries_without_lane_exit += 1
            self.last.pop(vehicle, None)
            return
        time = self._time(attrs)
        link, lane = attrs.get('link'), attrs.get('lane')
        if link not in self.links or not lane:
            raise ValueError(f'Evento de carril sin referencia valida: {vehicle}, {link}, {lane}')
        if previous and time < previous['time']:
            raise ValueError(f'Eventos de carril fuera de orden: {vehicle}')
        record = dict(type=kind, time=time, vehicle=vehicle, link=link, lane=lane)
        if kind == 'entered lane':
            self.entries += 1
            if previous and previous['type'] == 'entered lane':
                self.entries_without_lane_exit += 1
        else:
            self.exits += 1
            record['entry_observed'] = bool(previous and previous['type'] == 'entered lane'
                                            and previous['link'] == link and previous['lane'] == lane)
            if not record['entry_observed']:
                # Native insertion can emit a first "left lane" without an entry.
                self.unpaired_exits += 1
        self.events.append(record)
        self.last[vehicle] = record
        self.vehicles.add(vehicle)
        self.queues.add((link, lane))

    @staticmethod
    def _time(attrs):
        time = float(attrs['time'])
        if not math.isfinite(time):
            raise ValueError('Tiempo no finito en evento de carril')
        return time

    def payload(self, sample_rate=1.0):
        return dict(model='QSim lane queues', events=self.events, sample_rate=sample_rate,
                    event_count=self.entries + self.exits, entered_lane_events=self.entries,
                    left_lane_events=self.exits, vehicles_with_events=len(self.vehicles),
                    distinct_observed_queues=len(self.queues),
                    exits_without_observed_entry=self.unpaired_exits,
                    entries_without_observed_lane_exit=self.entries_without_lane_exit,
                    open_entries_at_end=sum(e['type'] == 'entered lane' for e in self.last.values()),
                    observed_fields=['time', 'vehicle', 'link', 'lane', 'type'],
                    longitudinal_position_observed=False, lateral_position_observed=False,
                    drawing='interpolated_link_centerline_without_lane_offsets')
