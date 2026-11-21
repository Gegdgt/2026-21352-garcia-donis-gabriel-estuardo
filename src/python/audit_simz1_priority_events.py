"""Read-only comparison of native waits in explicitly selected event files.

Example: python python/audit_simz1_priority_events.py --output report.json events.xml.gz
No simulation, inferred crossings, or reinterpretation of historical policies.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from simz1_native_validation import NativeDecisionAudit
from simz1_priority_audit import PriorityAudit
from simz1_run import sha256, xml_elements


def audit_events(path):
    priority, native = PriorityAudit(), NativeDecisionAudit()
    types, reasons_by_role = Counter(), Counter()
    stops_by_node = Counter()
    departures, durations = {}, []
    for element in xml_elements(path, 'event', 'events'):
        event = element.attrib
        priority.consume(event)
        native.consume(element)
        kind = event['type']
        types[kind] += 1
        if kind == 'departure':
            departures[event['person']] = float(event['time'])
        elif kind == 'arrival':
            start = departures.pop(event['person'], None)
            if start is not None:
                durations.append(float(event['time']) - start)
        elif kind == 'simz1Priority' and event['action'] == 'WAIT':
            reasons_by_role[event['role'] + ':' + event['reason']] += 1
            if event['reason'] == 'priority_stop':
                stops_by_node[event['node']] += 1
    return dict(events=str(path), events_sha256=sha256(path), event_types=dict(types),
                departures=types['departure'], arrivals=types['arrival'],
                pending_trips_at_cut=len(departures), aborted=types['stuckAndAbort'],
                mean_completed_trip_seconds=sum(durations)/len(durations) if durations else None,
                priority=priority.summary(), native=native.summary(),
                priority_wait_attempts_by_role_reason=dict(reasons_by_role),
                mandatory_stop_attempts_by_node=dict(sorted(stops_by_node.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    reports = [audit_events(path) for path in args.events]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    for row in reports:
        print(json.dumps({key:row[key] for key in ('events','departures','arrivals',
                         'pending_trips_at_cut','aborted','mean_completed_trip_seconds',
                         'priority_wait_attempts_by_role_reason')}))
    print(args.output)


if __name__ == '__main__':
    main()
