"""Audit every small PriorityMatrixCheck run from its native event files.

Usage: python python/audit_simz1_priority_matrix.py target/priority-matrix-...
Does not execute a simulation or change any saved scenario.
"""
from collections import Counter
import json
from pathlib import Path
import sys

from simz1_native_validation import NativeDecisionAudit
from simz1_priority_audit import PriorityAudit
from simz1_run import sha256, xml_elements


def audit_matrix(root):
    root = Path(root)
    rows = []
    paired_inputs = {}
    for path in sorted(root.glob('*/run/ITERS/it.*/*.events.xml.gz')):
        label = path.parents[3].name
        case, threads = label.rsplit('-threads-', 1)
        iteration = int(path.parent.name.removeprefix('it.'))
        priority, native = PriorityAudit(), NativeDecisionAudit()
        counts = Counter()
        departed, arrived = set(), set()
        for event in xml_elements(path, 'event', 'events'):
            priority.consume(event.attrib)
            native.consume(event)
            counts[event.get('type')] += 1
            if event.get('type') == 'departure':
                departed.add(event.get('person'))
            if event.get('type') == 'arrival':
                arrived.add(event.get('person'))
        evidence = priority.summary()
        if departed != arrived or counts['stuckAndAbort'] or evidence['pending_heads_at_cut']:
            raise ValueError(f'Incomplete small fixture {label} iteration {iteration}')
        if native.summary()['forced_storage_moves']:
            raise ValueError(f'Forced move invalidates small fixture {label} iteration {iteration}')
        folder = path.parents[3]
        hashes = {name:sha256(folder/name) for name in ('input-plans.xml','input-network.xml')}
        if case in paired_inputs and hashes != paired_inputs[case]:
            raise ValueError(f'Thread comparison changed demand/network in {case}')
        paired_inputs[case] = hashes
        rows.append(dict(case=case,threads=int(threads),iteration=iteration,
                         departed=len(departed),arrived=len(arrived),pending=0,
                         priority=evidence,native=native.summary(),input_sha256=hashes,
                         events=str(path.relative_to(root)),events_sha256=sha256(path)))
    if not rows:
        raise ValueError(f'No small QSim event files found under {root}')
    expected = {(threads,iteration) for threads in (1,4) for iteration in (0,1)}
    for case in paired_inputs:
        actual = {(r['threads'],r['iteration']) for r in rows if r['case']==case}
        if actual != expected:
            raise ValueError(f'Missing paired thread/iteration cases for {case}: {actual}')
    destination = root/'audit.json'
    destination.write_text(json.dumps(dict(cases=len(paired_inputs),event_files=len(rows),
        status='validated',rows=rows),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return destination,len(rows)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    destination,count = audit_matrix(sys.argv[1])
    print(f'PASS {count} native event files; arrivals, pending, forced moves, clocks and actual crossings: {destination}')
