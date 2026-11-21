"""One bounded, read-only prefix scan for vehicle-level SimZ1 native evidence.

The event hash is taken from the verified run manifest, NOT recomputed. The
caller pins the compressed size. Prefix chronology and unchanged stat metadata
are checked; suffix chronology relies on the already validated native run.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import xml.etree.ElementTree as ET

from simz1_run_directory import check_new_directory


def _window(start, end):
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start <= end <= 86401:
        raise ValueError('Windows require 0 <= start <= end <= 86401')
    return start, end


def _events(path):
    with gzip.open(path, 'rb') as stream:
        iterator = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(iterator)
        if root.tag != 'events':
            raise ValueError('Expected native events XML root')
        for action, element in iterator:
            if action == 'end' and element.tag == 'event':
                yield dict(element.attrib)
                element.clear()
                root.clear()


def _mechanism_context(path, vehicles, end, context_links, snapshot_times, max_events, max_records, progress):
    """Keep emitted ledger state and lane membership, never infer buffer occupancy.

    A TRANSFER updates one identity; WAIT is not an acquisition. Snapshot values
    are copied from native events, not a replay of admission/physics algorithms.
    """
    checkpoints = sorted(set(snapshot_times))
    if not 1 <= len(context_links) <= 16 or len(checkpoints) > 16:
        raise ValueError('Mechanism context requires 1..16 links and at most 16 snapshot times')
    for point in checkpoints:
        _window(point, end)
    domains, corridors, members, reservations, passages = {}, set(), {}, {}, {}
    latest, records, snapshots, attempts = {}, [], [], {}
    triggered, selected_reasons = set(), Counter()
    retained, checkpoint = 0, 0
    previous, observed, first_excluded = -math.inf, 0, None
    movement = {'departure', 'arrival', 'vehicle enters traffic', 'vehicle leaves traffic',
                'entered link', 'left link', 'entered lane', 'left lane'}
    observed_types = {'simz1NativeDecision', 'simz1Priority', 'simz1OccupancyProgress',
                      'simz1OccupancyReservation', 'simz1OccupancyPassage',
                      'simz1OccupancyPassageHold', 'simz1Admission'}

    def budget(extra):
        nonlocal retained
        retained += extra
        state = len(domains)+len(members)+len(reservations)+len(passages)+len(latest)+2*len(attempts)
        if retained+state > max_records:
            raise ValueError('Mechanism context exceeded max_records; no partial result may be published')

    def frame(point, seq, reason):
        # Membership is the last emitted enter-lane event without a matching
        # leave. It does not identify the native vehQueue/buffer partition.
        actors = set(members) | set(reservations) | set(passages) | vehicles
        evidence = [r for (ident, _), r in latest.items() if ident in actors]
        budget(len(members)+len(reservations)+len(passages)+len(evidence)+1)
        snapshots.append(dict(time=point, after_event_seq=seq, trigger=reason,
                              lane_membership=dict(members), emitted_reservations=dict(reservations),
                              emitted_passages=dict(passages), latest_actor_evidence=evidence,
                              buffer_membership='not observable from enter/leave-lane events'))

    iterator = _events(path)
    seq = 0
    try:
        for seq, attrs in enumerate(iterator, 1):
            if seq > max_events:
                raise ValueError('Native prefix exceeded max_events; no partial result may be published')
            observed = float(attrs.get('time', 'nan'))
            if not math.isfinite(observed) or observed < previous:
                raise ValueError(f'Non-monotone or invalid native time at event {seq}; unsafe early stop')
            previous = observed
            while checkpoint < len(checkpoints) and observed > checkpoints[checkpoint]:
                frame(checkpoints[checkpoint], seq-1, 'after_all_events_at_requested_time')
                checkpoint += 1
            if observed > end:
                first_excluded = dict(seq=seq, time=observed)
                break
            if progress and seq % 250_000 == 0:
                progress(seq, observed, retained)
            kind, ident = attrs.get('type'), attrs.get('vehicle') or attrs.get('person')
            link, corridor = attrs.get('link'), attrs.get('corridor')
            row = dict(seq=seq, time=observed, attributes=attrs)
            selected = ident in vehicles
            if kind == 'simz1OccupancyDomain' and link in context_links:
                domains[link] = row; corridors.add(corridor)
            scope = link in context_links or attrs.get('nextLink') in context_links or corridor in corridors
            if kind in {'simz1OccupancyPassage', 'simz1OccupancyPassageHold', 'simz1OccupancyReservation'}:
                scope = scope or attrs.get('requestedLink') in context_links or bool(context_links.intersection(
                    (attrs.get('passageLinks', '')+','+attrs.get('exitLinks', '')).split(',')))
            if kind == 'entered lane' and link in context_links:
                members[ident] = row
            elif kind == 'left lane' and ident in members and members[ident]['attributes'].get('lane') == attrs.get('lane'):
                members.pop(ident)
            elif kind in {'vehicle leaves traffic', 'vehicle aborts', 'stuckAndAbort'}:
                members.pop(ident, None)
            if kind == 'simz1OccupancyReservation':
                action = attrs.get('action')
                if action == 'EXIT':
                    reservations.pop(ident, None)
                elif action in {'ENTER', 'TRANSFER'}:
                    if scope:
                        reservations[ident] = row
                    else:
                        reservations.pop(ident, None)
            if kind == 'simz1OccupancyPassage':
                if attrs.get('action') == 'RELEASE':
                    passages.pop(ident, None)
                elif attrs.get('action') == 'ACQUIRE' and (scope or selected):
                    passages[ident] = row
            if ident and kind in observed_types and (scope or selected):
                latest[ident, kind] = row
            if selected and kind == 'simz1NativeDecision':
                reason = attrs.get('reason')
                selected_reasons[reason] += 1
                key = ident, link, attrs.get('nextLink'), reason
                if key not in attempts:
                    attempts[key] = dict(vehicle=ident, first=row, last=row, count=0)
                attempts[key]['last'] = row; attempts[key]['count'] += 1
                trigger = ('first_wait',)+key
                if scope and attrs.get('decision') == 'WAIT' and trigger not in triggered:
                    triggered.add(trigger); frame(observed, seq, dict(first_wait=row))
            if selected and (kind in movement or kind in {'simz1Admission', 'simz1OccupancyReservation',
                                                          'simz1OccupancyPassage', 'simz1OccupancyPassageHold'}):
                budget(1); records.append(row)
            # Snapshots immediately after actual admissions allow comparison
            # with completed trucks; GO alone never triggers an admission frame.
            if selected and kind == 'simz1Admission' and attrs.get('nextLink') in context_links:
                frame(observed, seq, dict(actual_admission=row))
            budget(0)
    finally:
        iterator.close()
    if first_excluded is None and previous < end:
        raise ValueError('Native source ended before the requested window end')
    if set(domains) != context_links:
        raise ValueError('Missing emitted corridor metadata for context links: '+', '.join(sorted(context_links-set(domains))))
    while checkpoint < len(checkpoints):
        frame(checkpoints[checkpoint], seq, 'after_all_events_at_requested_time')
        checkpoint += 1
    return dict(mode='mechanism_context', vehicles=sorted(vehicles), context_links=sorted(context_links),
                domains=domains, records=records, snapshots=snapshots,
                selected_attempts=list(attempts.values()), selected_native_reasons=dict(selected_reasons),
                record_count=retained, limits_include_live_state=True,
                limitations=['No buffer/vehQueue partition or continuous position is reconstructed.',
                             'GO is permission; only simz1Admission records a successful receiver transfer.',
                             'Lane neighbours and modeled leaders are evidence, not inferred causal blockers.',
                             'Priority reservationVehicle is distinct from a corridor body reservation.',
                             'Aggregate usedMeters in retained events has its original event time, not the snapshot time.'],
                scan=dict(event_prefix_records=seq, first_excluded_event=first_excluded,
                          prefix_nondecreasing=True, reached_end_of_file=first_excluded is None,
                          final_observed_time=observed, max_events=max_events, max_records=max_records))


def scan(path, vehicles, start, end, *, global_window=None, focus_links=(), focus_windows=(),
         max_events=100_000_000, max_records=50_000, progress=None, person_ids=(), context_links=(),
         mechanism_context=False, snapshot_times=()):
    start, end = _window(start, end)
    global_start, global_end = _window(*(global_window or (start, end)))
    windows = [_window(*window) for window in focus_windows]
    if global_end > end or any(b > end for _, b in windows):
        raise ValueError('Every diagnostic window must end within the scanned prefix')
    vehicles, focus_links = set(vehicles), set(focus_links)
    if not 1 <= len(vehicles) <= 128 or any(not isinstance(v, str) or not v for v in vehicles):
        raise ValueError('Select 1..128 explicit vehicle IDs')
    if not 1 <= max_events <= 100_000_000 or not 1 <= max_records <= 50_000:
        raise ValueError('Event/record bounds exceed the supported inspection limits')
    if len(person_ids) > 128 or len(context_links) > 16:
        raise ValueError('At most 128 explicit persons and 16 context links')
    if mechanism_context:
        if start != 0 or person_ids or focus_links or focus_windows or global_window:
            raise ValueError('Mechanism context requires start=0 and explicit vehicle/context IDs only')
        return _mechanism_context(path, vehicles, end, set(context_links), snapshot_times,
                                  max_events, max_records, progress)
    if snapshot_times:
        raise ValueError('snapshot_times requires mechanism_context')
    persons, selected_persons, records = defaultdict(set), set(person_ids), []
    context_links = set(context_links)
    types, reasons, selected_reasons = Counter(), Counter(), Counter()
    previous, first_excluded, observed = -math.inf, None, 0
    iterator = _events(path)
    try:
        for seq, attrs in enumerate(iterator, 1):
            if seq > max_events:
                raise ValueError('Native prefix exceeded max_events; no partial result may be published')
            observed = float(attrs.get('time', 'nan'))
            if not math.isfinite(observed) or observed < previous:
                raise ValueError(f'Non-monotone or invalid native time at event {seq}; unsafe early stop')
            previous = observed
            if progress and seq % 250_000 == 0:
                progress(seq, observed, len(records))
            if observed > end:
                first_excluded = dict(seq=seq, time=observed)
                break
            vehicle, person = attrs.get('vehicle'), attrs.get('person')
            if vehicle in vehicles and person:
                persons[vehicle].add(person)
                selected_persons.add(person)
            kind, reason = attrs.get('type'), attrs.get('reason')
            if global_start <= observed <= global_end:
                types[kind] += 1
                if kind == 'simz1NativeDecision':
                    reasons[reason] += 1
            selected = vehicle in vehicles or person in selected_persons
            selected = selected and start <= observed <= end
            focus = (kind == 'simz1NativeDecision' and reason == 'storage_forced_move' and
                     (attrs.get('link') in focus_links or attrs.get('nextLink') in focus_links) and
                     any(a <= observed <= b for a, b in windows))
            context = start <= observed <= end and attrs.get('link') in context_links
            if selected or focus or context:
                if len(records) >= max_records:
                    raise ValueError('Native evidence exceeded max_records; no truncated result may be published')
                records.append(dict(seq=seq, time=observed,
                                    selection=('vehicle' if vehicle in vehicles else 'observed_person') if selected else 'context_link' if context else 'focus_link_force',
                                    attributes=attrs))
                if selected and kind == 'simz1NativeDecision':
                    selected_reasons[reason] += 1
    finally:
        iterator.close()
    if first_excluded is None and previous < end:
        raise ValueError('Native source ended before the requested window end')
    return dict(window=dict(start_seconds=start, end_seconds=end, endpoints='inclusive'),
                vehicles=sorted(vehicles), observed_person_ids={v: sorted(persons[v]) for v in sorted(vehicles)},
                requested_person_ids=sorted(person_ids), context_links=sorted(context_links),
                global_window=dict(start_seconds=global_start, end_seconds=global_end, endpoints='inclusive'),
                global_event_types=dict(types), global_native_reasons=dict(reasons),
                selected_native_reasons=dict(selected_reasons),
                focus_links=sorted(focus_links), focus_windows=windows,
                records=records, record_count=len(records),
                scan=dict(event_prefix_records=seq if 'seq' in locals() else 0,
                          first_excluded_event=first_excluded, prefix_nondecreasing=True,
                          reached_end_of_file=first_excluded is None, final_observed_time=observed,
                          max_events=max_events, max_records=max_records,
                          suffix_order='not rescanned; relies on validated run manifest chronology'))


def inspect(run_directory, iteration, run_id, manifest_sha256, events_bytes, vehicles, start, end, **options):
    directory = Path(run_directory).resolve(strict=True)
    manifest_path = directory/'run-manifest.json'
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError('Run manifest hash mismatch')
    manifest = json.loads(raw)
    if (manifest.get('run_id') != run_id or manifest.get('status') != 'completed' or
            manifest.get('validation', {}).get('status') != 'valid'):
        raise ValueError('Expected an already completed/valid native run with matching identity')
    source = manifest['results'][str(iteration)]['events']
    if not re.fullmatch('[0-9a-f]{64}', source['sha256']):
        raise ValueError('Missing expected native event SHA-256')
    path = (directory/source['path']).resolve(strict=True)
    if not path.is_relative_to(directory) or path.suffix != '.gz':
        raise ValueError('Native gzip event source must stay inside the historical run')
    before = path.stat()
    if not isinstance(events_bytes, int) or events_bytes <= 0 or before.st_size != events_bytes:
        raise ValueError('Compressed native event size differs from the caller-pinned size')
    result = scan(path, vehicles, start, end, **options)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or manifest_path.read_bytes() != raw:
        raise ValueError('Native source/manifest changed during inspection; no evidence may be published')
    return dict(schema='simz1-native-sample-v1', read_only=True,
                identity=dict(run_id=run_id, iteration=iteration, run_manifest_sha256=manifest_sha256),
                source=dict(path=str(path), expected_sha256=source['sha256'], bytes=before.st_size,
                            mtime_ns=before.st_mtime_ns, content_hash_recomputed=False,
                            verification='manifest hash and caller-pinned size verified; source stat unchanged'),
                evidence=result,
                limitations=['Native WAIT/FORCE counts are attempts, not waiting duration or unique vehicles.',
                             'Link/lane membership and receiver rejection do not observe continuous body coordinates.',
                             'Non-atomic receiver snapshots and unknown parallel receiver signals remain explicit.',
                             'A finite prefix scan cannot independently revalidate the full gzip hash or unread suffix.'])


def inspect_failed(run_directory, iteration, run_id, manifest_sha256, events_bytes, vehicles, start, end, **options):
    """Explicit diagnostic of a failed run; never grants completed/valid provenance."""
    directory = Path(run_directory).resolve(strict=True)
    manifest_path = directory/'run-manifest.json'
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != manifest_sha256 or manifest.get('run_id') != run_id:
        raise ValueError('Failed run identity/hash mismatch')
    if manifest.get('status') != 'failed' or iteration < 0:
        raise ValueError('Diagnostic requires an explicitly failed run and nonnegative iteration')
    path = (directory/'output/ITERS'/f'it.{iteration}'/f'{iteration}.events.xml.gz').resolve(strict=True)
    if not path.is_relative_to(directory):
        raise ValueError('Failed native source must stay inside the historical run')
    before = path.stat()
    if type(events_bytes) is not int or events_bytes <= 0 or before.st_size != events_bytes:
        raise ValueError('Compressed native event size differs from the caller-pinned size')
    result = scan(path, vehicles, start, end, **options)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or manifest_path.read_bytes() != raw:
        raise ValueError('Failed source/manifest changed during inspection')
    result['scan']['suffix_order'] = 'unknown: failed run; no validated chronology or complete gzip assumed'
    return dict(schema='simz1-failed-native-sample-v1', read_only=True, diagnostic_only=True,
        identity=dict(run_id=run_id, iteration=iteration, run_manifest_sha256=manifest_sha256),
        source=dict(path=str(path), bytes=before.st_size, mtime_ns=before.st_mtime_ns,
                    content_hash_recomputed=False, verification='identity and stat only; events not validated'),
        evidence=result, limitations=['Failure/truncation or bounds exhaustion yields no published partial report.',
            'Context-link actors are candidates, not proven blockers; inspect native queue/rejection evidence.',
            'No inference about unread events, completed trips, congestion resolution or the full event hash.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--iteration', type=int, default=0)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--events-bytes', type=int, required=True)
    parser.add_argument('--vehicle', action='append', required=True)
    parser.add_argument('--person', action='append', default=[], help='Explicit known driver ID, including departure before traffic entry')
    parser.add_argument('--context-link', action='append', default=[], help='Bounded window context; at most 16 links, not proof of blocking')
    parser.add_argument('--mechanism-context', action='store_true', help='Bounded ledger/lane snapshots and actual selected movements; no physics replay')
    parser.add_argument('--snapshot-time', action='append', type=float, default=[], help='Inclusive end-of-tick snapshot; requires --mechanism-context, at most 16')
    parser.add_argument('--failed-diagnostic', action='store_true', help='Read a failed run explicitly; never labels its events validated')
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--global-window', nargs=2, type=float)
    parser.add_argument('--focus-link', action='append', default=[])
    parser.add_argument('--focus-window', nargs=2, type=float, action='append', default=[])
    parser.add_argument('--max-events', type=int, default=100_000_000)
    parser.add_argument('--max-records', type=int, default=50_000)
    parser.add_argument('--output-new', type=Path, required=True, help='NEW directory; existing outputs are never overwritten')
    args = parser.parse_args(argv)
    target = check_new_directory(args.output_new)
    if target.resolve().is_relative_to(args.run_dir.resolve()):
        raise ValueError('Diagnostic output must be outside the source run')
    began = time.monotonic()
    def progress(seq, observed, kept):
        print(f'Native prefix: {seq:,} events; t={observed}; retained={kept}; elapsed={time.monotonic()-began:.1f}s',
              file=sys.stderr, flush=True)
    reader = inspect_failed if args.failed_diagnostic else inspect
    result = reader(args.run_dir, args.iteration, args.run_id, args.manifest_sha256, args.events_bytes,
                     args.vehicle, args.start, args.end, global_window=args.global_window,
                     focus_links=args.focus_link, focus_windows=args.focus_window,
                     max_events=args.max_events, max_records=args.max_records, progress=progress,
                     person_ids=args.person, context_links=args.context_link,
                     mechanism_context=args.mechanism_context, snapshot_times=args.snapshot_time)
    target.mkdir(parents=True, exist_ok=False)
    destination = target/'native-sample.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(output=str(destination), records=result['evidence']['record_count'],
                          selected_native_reasons=result['evidence']['selected_native_reasons'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
