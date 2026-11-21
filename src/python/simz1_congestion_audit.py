"""Read-only streaming investigation of uncompleted SimZ1 trips and receiver waits.

Never restarts MATSim, edits a native file, changes a timestamp, or invents an
arrival. Explicit --events acknowledges reading the existing large event stream.
Memory is O(people + network links), not O(events). Equal timestamps are valid.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from simz1_trip_audit import TripAudit
from simz1_storage_diagnostics import StorageAudit


def cycles(edges):
    """Iterative strongly connected components; candidate wait cycles, not proof."""
    graph, inverse = defaultdict(set), defaultdict(set)
    for a, b in edges:
        if a and b:
            graph[a].add(b); graph[b]; inverse[b].add(a); inverse[a]
    visited, order = set(), []
    for start in sorted(graph):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(sorted(graph[start])))]
        while stack:
            node, successors = stack[-1]
            target = next(successors, None)
            if target is None:
                order.append(node); stack.pop()
            elif target not in visited:
                visited.add(target); stack.append((target, iter(sorted(graph[target]))))
    visited, result = set(), []
    for start in reversed(order):
        if start in visited:
            continue
        component, stack = [], [start]
        visited.add(start)
        while stack:
            node = stack.pop(); component.append(node)
            for target in sorted(inverse[node]):
                if target not in visited:
                    visited.add(target); stack.append(target)
        if len(component) > 1 or start in graph[start]:
            result.append(sorted(component))
    return sorted(result, key=lambda row: (-len(row), row))


class CongestionAudit:
    def __init__(self, horizon=86400, limit=20, wait_recency_seconds=120):
        self.horizon, self.limit, self.recency = horizon, limit, wait_recency_seconds
        self.trips = TripAudit(horizon)
        self.storage = StorageAudit()
        self.hourly_network = []
        self.next_probe = 3600
        self.counts, self.reasons, self.policies = Counter(), Counter(), Counter()
        self.receiving_waits, self.origin_departures, self.censored_origins = Counter(), Counter(), Counter()
        self.locations, self.occupancy, self.peak_occupancy = {}, Counter(), Counter()
        self.latest_storage_wait, self.internal_drivers, self.transit_vehicles = {}, set(), set()
        self.hourly_departures, self.hourly_arrivals, self.hourly_entries = Counter(), Counter(), Counter()
        self.snapshot = None
        self.last_time, self.last_arrival, self.last_entry = None, None, None
        self.examples = []

    def _snapshot(self, at):
        edge_counts = Counter((a, b) for a, b, t in self.latest_storage_wait.values()
                              if 0 <= at-t <= self.recency)
        groups = cycles(edge_counts)
        return dict(observed_time=at, active_vehicles_from_traffic_events=len(self.locations),
                    top_occupied_links=self.occupancy.most_common(self.limit),
                    pending_departed_legs=len(self.trips.pending),
                    recent_storage_wait_edges=[dict(link=a, next_link=b, vehicles=n) for (a,b),n in edge_counts.most_common(self.limit)],
                    storage_wait_recency_seconds=self.recency,
                    candidate_wait_cycles=groups[:self.limit], candidate_wait_cycle_count=len(groups),
                    scope='Last observed receiver waits within stated recency, not a simultaneous storage snapshot or deadlock proof')

    def _leave(self, vehicle):
        old = self.locations.pop(vehicle, None)
        if old is not None:
            self.occupancy[old] -= 1
            if not self.occupancy[old]: del self.occupancy[old]
        self.latest_storage_wait.pop(vehicle, None)

    def consume(self, a):
        t = float(a.get('time', 'nan'))
        if not math.isfinite(t) or t < 0 or self.last_time is not None and t < self.last_time:
            raise ValueError(f'Eventos fuera de orden o tiempo invalido: {dict(a)}')
        # Sparse probes before processing events at the boundary. This keeps
        # the time series independent of cleanup and costs O(24 * active queue heads).
        while self.next_probe <= self.horizon and t >= self.next_probe:
            self.hourly_network.append(self._snapshot(self.next_probe))
            self.next_probe += 3600
        # Preserve the observed network before cleanup events at/after the cut.
        if t >= self.horizon and self.snapshot is None:
            self.snapshot = self._snapshot(self.horizon)
        self.last_time = t
        self.counts['events_seen'] += 1
        kind, vehicle = a.get('type'), a.get('vehicle')
        if kind == 'TransitDriverStarts':
            if a.get('driverId'): self.internal_drivers.add(a['driverId'])
            if a.get('vehicleId'): self.transit_vehicles.add(a['vehicleId'])
            return
        if a.get('person') in self.internal_drivers or vehicle in self.transit_vehicles:
            self.counts['transit_events_separate'] += 1
            return
        if kind == 'departure':
            self.origin_departures[a.get('link', 'unknown')] += 1
            self.hourly_departures[int(t//3600)] += 1
        if kind == 'arrival':
            self.hourly_arrivals[int(t//3600)] += 1; self.last_arrival = t
        if kind == 'vehicle enters traffic':
            self.hourly_entries[int(t//3600)] += 1; self.last_entry = t
        if kind in ('vehicle enters traffic', 'entered link') and vehicle:
            link = a.get('link')
            if link and self.locations.get(vehicle) != link:
                self._leave(vehicle); self.locations[vehicle] = link
                self.occupancy[link] += 1
                self.peak_occupancy[link] = max(self.peak_occupancy[link], self.occupancy[link])
            self.latest_storage_wait.pop(vehicle, None)
        elif kind in ('left link', 'vehicle leaves traffic', 'vehicle aborts') and vehicle:
            self._leave(vehicle)
        if kind == 'simz1NativeDecision':
            self.storage.consume(ET.Element('event', dict(a)))
            reason = a.get('reason', 'unknown'); self.reasons[reason] += 1
            self.policies[a.get('admissionPolicy', 'unattributed')] += 1
            if reason == 'storage_wait':
                edge = a.get('link'), a.get('nextLink')
                self.receiving_waits[edge] += 1
                if vehicle and all(edge): self.latest_storage_wait[vehicle] = (*edge, t)
            elif vehicle:
                self.latest_storage_wait.pop(vehicle, None)
        closed = self.trips.consume(a)
        if closed:
            for v in closed['vehicles']: self._leave(v)
            if closed['status'] == 'censored':
                self.censored_origins[closed.get('departure_link') or 'unknown'] += 1
            if closed['status'] != 'completed' and len(self.examples) < self.limit:
                self.examples.append({k: closed.get(k) for k in ('person','index','departure','abort','status',
                                                               'vehicles','boarded','traffic_entered','traffic_left')})

    def summary(self):
        trip_summary = self.trips.summary()
        origins = Counter(self.censored_origins)
        for trip in self.trips.unfinished(): origins[trip.get('departure_link') or 'unknown'] += 1
        return dict(schema_version=1, event_end_seconds=self.last_time, counts=dict(self.counts),
                    trips=trip_summary, last_arrival_seconds=self.last_arrival,
                    last_traffic_entry_seconds=self.last_entry,
                    by_event_hour={str(h): dict(departures=self.hourly_departures[h],
                        traffic_entries=self.hourly_entries[h], arrivals=self.hourly_arrivals[h])
                        for h in sorted(set(range(24))|self.hourly_departures.keys()|self.hourly_arrivals.keys())},
                    top_departure_links=self.origin_departures.most_common(self.limit),
                    top_censored_origin_links=origins.most_common(self.limit),
                    top_peak_occupied_links=self.peak_occupancy.most_common(self.limit),
                    native_decisions_by_reason=dict(self.reasons), policies_observed=dict(self.policies),
                    storage_observations=self.storage.summary(), hourly_network_before_boundary=self.hourly_network,
                    top_receiver_wait_edges=[dict(link=a, next_link=b, attempts=n) for (a,b),n in self.receiving_waits.most_common(self.limit)],
                    horizon_snapshot=self.snapshot or self._snapshot(self.last_time or 0), examples=self.examples,
                    limitations=['WAIT counts are attempts, not seconds or unique trips.',
                        'Observed occupancy is vehicle count, not PCU or measured saturation.',
                        'A wait-cycle candidate is not proof of permanent physical deadlock.',
                        'No arrival is imputed. Source completed/valid only certifies its recorded integrity.',
                        'Driver boardings without traffic entry are distinct from circulating vehicles.'])


def scan(path, horizon=86400, progress=False):
    audit = CongestionAudit(horizon)
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as stream:
        iterator = ET.iterparse(stream, events=('start','end'))
        _, root = next(iterator)
        if root.tag != 'events': raise ValueError('Se esperaba events XML')
        for action, element in iterator:
            if action == 'end' and element.tag == 'event':
                audit.consume(element.attrib)
                if progress and audit.counts['events_seen'] % 1000000 == 0:
                    print(f"Eventos leidos: {audit.counts['events_seen']:,}; t={audit.last_time}", file=sys.stderr, flush=True)
                element.clear(); root.clear()
    return audit.summary()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--iteration', type=int, default=0)
    parser.add_argument('--events', action='store_true', required=True, help='Autoriza leer eventos existentes; no simula')
    args = parser.parse_args()
    try:
        from simz1_run import select_run, checked_path, parameters, atomic_json
        selection = select_run(args.run_dir, args.iteration)
        run, manifest = selection['directory'], selection['manifest']
        report = scan(selection['events'], manifest['time_horizon']['end_seconds'], progress=True)
        config = parameters(checked_path(run, manifest['effective_config']))
        report.update(run_id=manifest['run_id'], iteration=args.iteration,
                      storage_policy=config.get('simz1Admission.storagePolicy','matsim15-native'),
                      source_events=manifest['results'][str(args.iteration)]['events'], source_read_only=True)
        product = manifest.get('trip_products', {}).get(str(args.iteration), {})
        if 'summary' in product:
            native = json.loads(checked_path(run, product['summary']).read_text(encoding='utf-8'))
            report['native_summary'] = native
            mapping = {'rows':'departures','completed':'completed_trips','aborted':'aborted_before_horizon','censored':'pending_trips_at_horizon'}
            report['event_minus_compact_counts'] = {k: report['trips'][v]-native.get('counts',{}).get(k,0) for k,v in mapping.items()}
        # New derivative only; never rewrite native compact CSV, manifest or stats.
        out = run/'analysis'/f'it.{args.iteration}'/'diagnostico_trafico'
        import uuid
        target = out/('audit-'+uuid.uuid4().hex[:12]+'.json')
        atomic_json(target, report)
        print(f'Diagnostico de eventos (no modifica corrida): {target}')
        print(json.dumps(report['trips'], ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, EOFError) as exc:
        print(f'Diagnostico detenido: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
