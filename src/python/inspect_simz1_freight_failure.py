"""Read-only, bounded freight evidence from one explicitly identified failed run.

Never revalidates a run, publishes artifacts or synthesizes terminal events.
Gzip CRC and complete XML are asserted only after reaching EOF within the budget.
"""
import argparse
from collections import Counter, deque
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import zlib

MOVEMENT = {'vehicle enters traffic', 'vehicle leaves traffic', 'entered link',
            'left link', 'entered lane', 'left lane'}
KINDS = MOVEMENT | {'departure', 'arrival', 'stuckAndAbort', 'vehicle aborts',
                    'simz1NativeDecision', 'simz1Admission'}


def scan_events(path, expected_ids, targets, violation_times, *, max_bytes, max_seconds):
    """Retain fixed-size samples, not the stream; return explicit partial evidence."""
    if max_bytes <= 0 or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('Extraction budgets must be positive and finite')
    expected_ids, targets = set(expected_ids), set(targets)
    if not targets <= expected_ids:
        raise ValueError('Target outside saved roster')
    path = Path(path)
    before = path.stat()
    deadline = time.monotonic() + max_seconds
    counts = {ident: Counter() for ident in expected_ids}
    details = {ident: dict(recent_movements=deque(maxlen=8), first_events={}) for ident in targets}
    size, event_count, status, error = 0, 0, 'limit_reached', None
    parser = ET.XMLPullParser(events=('start', 'end'))
    root = None
    try:
        with gzip.open(path, 'rb') as stream:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Time budget reached; EOF/CRC not established')
                block = stream.read(min(65536, max_bytes-size+1))
                size += len(block)
                if size > max_bytes:
                    raise TimeoutError('Uncompressed byte budget reached; EOF/CRC not established')
                if not block:
                    parser.close()
                    status = 'complete'
                    break
                parser.feed(block)
                for action, element in parser.read_events():
                    if root is None:
                        if action != 'start' or element.tag != 'events':
                            raise ValueError('Expected events XML root')
                        root = element
                    if action != 'end' or element.tag != 'event':
                        continue
                    event_count += 1
                    attrs = element.attrib
                    ident = attrs.get('person') or attrs.get('vehicle')
                    kind = attrs.get('type')
                    if ident in expected_ids and kind in KINDS:
                        counts[ident][kind] += 1
                        if ident in details:
                            row, observed = details[ident], dict(attrs)
                            row['first_events'].setdefault(kind, observed)
                            if kind in MOVEMENT:
                                row['last_movement'] = observed
                                row['recent_movements'].append(observed)
                            if kind == 'simz1NativeDecision':
                                row['last_native_decision'] = observed
                                if attrs.get('storageSnapshot') in {'sampled_wait', 'intervention'}:
                                    row['last_storage_snapshot'] = observed
                            if kind == 'simz1Admission':
                                row['last_admission'] = observed
                            if (ident in violation_times and
                                    float(attrs['time']) == violation_times[ident] and
                                    kind == 'simz1NativeDecision'):
                                row.setdefault('decision_at_reported_first_violation', observed)
                    element.clear()
                    root.clear()
    except TimeoutError as exc:
        error = str(exc)
    except (OSError, EOFError, ET.ParseError, ValueError, zlib.error) as exc:
        status, error = 'invalid_stream', str(exc)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        status, error = 'source_changed', 'Source changed during extraction; no integrity conclusion'
    for row in details.values():
        row['recent_movements'] = list(row['recent_movements'])
    return dict(status=status, gzip_crc_and_xml_complete=status == 'complete', error=error,
                compressed_bytes=before.st_size, uncompressed_bytes_read=size, events_scanned=event_count,
                counts_scope='complete_stream' if status == 'complete' else 'partial_prefix_only',
                event_counts={ident: dict(counts[ident]) for ident in sorted(counts)},
                affected_events=details)


def inspect_run(run, expected_run_id, iteration, max_bytes, max_seconds):
    run = Path(run).resolve(strict=True)
    manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8-sig'))
    if manifest['run_id'] != expected_run_id or Path(manifest['folder']).resolve() != run:
        raise ValueError('Run identity/folder mismatch')
    if manifest['status'] != 'failed':
        raise ValueError('This reader requires the explicitly selected failed run')
    requested = manifest['iterations']
    first, last = requested.get('first', 0), requested['last']
    if type(first) is not int or type(last) is not int or not 0 <= first <= last:
        raise ValueError('Invalid requested iteration interval')
    produced = []
    for folder in (run/'output/ITERS').glob('it.*'):
        suffix = folder.name.removeprefix('it.')
        if not folder.is_dir() or not suffix.isdecimal():
            continue
        number = int(suffix)
        # Requested last is a plan, not evidence that QSim reached it. An
        # incomplete later stream is still produced: never silently inspect an
        # older successful audit when the latest attempted output is missing it.
        if not any((folder/f'{number}.{name}').is_file()
                   for name in ('events.xml.gz', 'simz1-freight-audit.csv')):
            continue
        if not folder.resolve().is_relative_to(run):
            raise ValueError('Produced iteration outside saved run')
        if not first <= number <= last:
            raise ValueError('Produced iteration outside requested interval')
        produced.append(number)
    if not produced:
        raise ValueError('No produced freight/event iteration in failed run')
    latest = max(produced)
    if iteration is None:
        iteration = latest
    if type(iteration) is not int or iteration != latest:
        raise ValueError(f'This reader requires the latest produced iteration ({latest}), not requested last ({last})')

    def pinned_json(name):
        record = manifest['inputs']['input:freight-weekday/'+name]
        path = (run/record['path']).resolve(strict=True)
        if not path.is_relative_to(run):
            raise ValueError('Saved input outside this run')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Saved freight input hash mismatch: '+name)
        return json.loads(raw)

    roster, service = pinned_json('roster.json'), pinned_json('service.json')
    expected = {row['vehicle_id']: row for row in roster}
    if len(expected) != len(roster) or len(expected) != service['vehicles']:
        raise ValueError('Saved roster identities/count disagree')
    folder = run/'output/ITERS'/f'it.{iteration}'
    report_path = folder/f'{iteration}.simz1-freight-audit.csv'
    events_path = folder/f'{iteration}.events.xml.gz'
    if not report_path.is_file() or not events_path.is_file():
        raise ValueError(f'Latest produced iteration {iteration} has missing freight evidence; no fallback to an older iteration')
    with report_path.open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    reports = {row['vehicle']: row for row in records}
    if len(reports) != len(records) or reports.keys() != expected.keys():
        raise ValueError('Native report does not reconcile every saved roster identity exactly once')
    targets = sorted(ident for ident, row in reports.items()
                     if row['trip_outcome'] != 'completed' or row['schedule_compliance'] == 'violated')
    violations = {ident: float(row['violation_observed']) for ident, row in reports.items()
                  if row['violation_observed']}
    evidence = scan_events(events_path, expected, targets, violations,
                           max_bytes=max_bytes, max_seconds=max_seconds)
    return dict(run_id=expected_run_id, run_directory=str(run), iteration=iteration,
                last_requested_iteration=last, last_produced_iteration=latest,
                run_status_unchanged=manifest['status'], does_not_revalidate_or_approve=True,
                allowed_windows_seconds=service['allowed_windows_seconds'],
                residence_policy=service['residence_policy'], native_report=str(report_path),
                expected_ids=sorted(expected),
                native_outcomes={outcome: sorted(ident for ident, row in reports.items() if row['trip_outcome'] == outcome)
                                 for outcome in sorted({row['trip_outcome'] for row in records})},
                affected={ident: dict(planned_departure=expected[ident]['departure_seconds'],
                                     route_id=expected[ident]['route_id'],
                                     planned_entry_link=expected[ident]['link_ids'][0],
                                     planned_exit_link=expected[ident]['link_ids'][-1],
                                     native_report=reports[ident]) for ident in targets},
                extraction=evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--expected-run-id', required=True)
    parser.add_argument('--iteration', type=int,
                        help='Explicit latest produced iteration; omitted selects it from saved event/audit files')
    parser.add_argument('--max-uncompressed-mib', type=int, default=32768)
    parser.add_argument('--max-seconds', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        result = inspect_run(args.run_dir, args.expected_run_id, args.iteration,
                             args.max_uncompressed_mib*1024*1024, args.max_seconds)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        status = result['extraction']['status']
        return 0 if status == 'complete' else 2 if status == 'limit_reached' else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, 'Freight evidence refused: '+str(exc)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
