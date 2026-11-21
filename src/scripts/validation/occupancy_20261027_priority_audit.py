"""Read-only PriorityAudit runner for reproducible native passage fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter, deque

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python'))
from simz1_priority_audit import PriorityAudit
from simz1_native_validation import NativeDecisionAudit
from simz1_run import xml_elements


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--independent-native', action='store_true', help='Audit priority and native decisions independently, retaining first error per auditor')
    parser.add_argument('--manifest', type=Path, help='Read-only admission-policy identity for a single real run')
    args = parser.parse_args()
    result = dict(command=sys.argv, fixtures=[])
    if args.manifest and len(args.events) != 1:
        raise ValueError('One manifest can identify only one event source')
    manifest_hash = sha256(args.manifest) if args.manifest else None
    manifest = json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest else {}
    failures = False
    for path in args.events:
        before = sha256(path)
        if args.independent_native:
            audits = dict(priority=PriorityAudit(), native=NativeDecisionAudit(
                manifest.get('effective_configuration_validation', {}).get('admission_policy')))
            statuses = {name: dict(status='running') for name in audits}
            counts, recent = Counter(), deque(maxlen=30)
            event_count = 0
            for event in xml_elements(path, 'event', 'events'):
                event_count += 1
                counts[event.get('type')] += 1
                for name, audit in audits.items():
                    if statuses[name]['status'] == 'failed':
                        continue
                    try:
                        audit.consume(event.attrib if name == 'priority' else event)
                    except Exception as error:
                        statuses[name] = dict(status='failed', event_number=event_count,
                            first_error=str(error), error_type=type(error).__name__, event=dict(event.attrib),
                            preceding_events=list(recent))
                        failures = True
                        print(json.dumps(dict(auditor=name,status='failed',event_number=event_count,time=event.get('time'),
                                              error=str(error)), ensure_ascii=False), flush=True)
                recent.append(dict(event.attrib))
                if event_count % 2000000 == 0:
                    print(json.dumps(dict(events_read=event_count,time=event.get('time'),statuses={
                        name: value['status'] for name,value in statuses.items()})), flush=True)
            for name, audit in audits.items():
                if statuses[name]['status'] == 'failed':
                    continue
                try:
                    statuses[name] = dict(status='passed',summary=audit.summary())
                except Exception as error:
                    statuses[name] = dict(status='failed',at_end_of_stream=True,first_error=str(error),error_type=type(error).__name__)
                    failures = True
            after = sha256(path)
            if before != after:
                raise RuntimeError('Source events changed during audit: ' + str(path))
            result['fixtures'].append(dict(events=str(path),source_sha256=before,source_unchanged=True,
                                           event_count=event_count,event_types=dict(counts),audits=statuses))
            continue
        audit = PriorityAudit()
        event_count = 0
        for event in xml_elements(path, 'event', 'events'):
            audit.consume(event.attrib)
            event_count += 1
        summary = audit.summary()
        after = sha256(path)
        if before != after:
            raise RuntimeError('Source events changed during audit: ' + str(path))
        result['fixtures'].append(dict(events=str(path), source_sha256=before,
                                       source_unchanged=True, event_count=event_count, summary=summary))
    result['source_files'] = {str(path.relative_to(ROOT)): sha256(path) for path in (
        ROOT / 'python/simz1_priority_audit.py', ROOT / 'python/simz1_priority_passage.py',
        ROOT / 'python/simz1_native_validation.py', ROOT / 'python/simz1_admission_validation.py',
        ROOT / 'python/test_simz1_priority_passage.py', Path(__file__).resolve())}
    if args.manifest:
        if manifest_hash != sha256(args.manifest):
            raise RuntimeError('Run manifest changed during the read-only audit')
        result['manifest'] = dict(path=str(args.manifest),sha256=manifest_hash,unchanged=True,run_id=manifest['run_id'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if args.independent_native:
        print(json.dumps(dict(output=str(args.output),fixtures=[dict(events=row['events'],event_count=row['event_count'],
            statuses={name:value['status'] for name,value in row['audits'].items()}) for row in result['fixtures']]),indent=2))
        return 1 if failures else 0
    print(json.dumps(dict(output=str(args.output), fixtures=[dict(events=row['events'],
        crossings=row['summary']['executed_crossings'],
        passage_stop_credit=row['summary']['passage_stop_credit']) for row in result['fixtures']]), indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
