"""Check a small XML emitted by SimZ1IncidentLaneCheck; never open run events."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_incident_replay import parse_incident_events


def check(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Only a small Java contract fixture is accepted')
    root = ET.parse(path).getroot()
    events = [dict(event.attrib) for event in root]
    if root.tag != 'events' or len(events) != 2 or any(
            event.get('runId') != 'fixture-run' or event.get('scope') != 'fixture_only'
            for event in events):
        raise ValueError('Expected exactly the two duration events from SimZ1IncidentLaneCheck')
    identity = dict(run_id='fixture-run', iteration=0, horizon_seconds=2000)
    denied = parse_incident_events(events, **identity)
    if denied['records']:
        raise AssertionError('Production parser accepted a fixture')
    decoded = parse_incident_events(events, **identity, allow_fixture=True)
    if decoded['diagnostics'] or len(decoded['records']) != 1:
        raise AssertionError('Java wire rejected by Python: ' + json.dumps(decoded['diagnostics']))
    record = decoded['records'][0]
    if (record['status'] != 'resolved' or record['start_seconds'] != 0 or record['end_seconds'] != 1800
            or record['duration_seconds'] != 1800 or record['lane'] != 'fixture-lane-0'
            or record['vehicles'] != ['fixture-A-duration', 'fixture-B-duration']
            or record['participants'][1]['vehicle_type'] != 'fixture-bus'
            or record['participants'][1]['person_id'] is not None
            or decoded['adapter_installed'] or record['physics_effect'] != 'none'):
        raise AssertionError('Java/Python identity, interval or provenance mismatch')
    return dict(status='PASS', events=2, records=1, exact_duration_seconds=1800,
                native_adapter_installed=False, default_parser_rejected_fixture=True,
                simulation_executed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture_xml')
    args = parser.parse_args()
    print(json.dumps(check(args.fixture_xml), ensure_ascii=False))
