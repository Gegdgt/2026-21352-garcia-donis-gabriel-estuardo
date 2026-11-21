"""Audit an existing SimZ1 HTML against its validated run; never export or run QSim."""
import argparse
from collections import Counter, defaultdict
import json
import gzip
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from simz1_run import atomic_json, select_run, sha256
from simz1_visual_motion import sample_motion


def audit_native_wait_samples(events_path, segments):
    """Check each native QNode WAIT against its exported visual plan."""
    by_link=defaultdict(list)
    for segment in segments:
        by_link[(segment['vehicle'],segment['Link_ID'])].append(segment)
    for records in by_link.values():
        records.sort(key=lambda segment: tuple(segment['timestamps']))
    counts,reasons,signal_states,errors=Counter(),Counter(),Counter(),[]
    maximum_speed=maximum_distance_error=0.0
    with gzip.open(events_path,'rb') as stream:
        for _,element in ET.iterparse(stream,events=('end',)):
            if element.tag!='event':
                continue
            event=element.attrib
            if event.get('type')=='simz1NativeDecision' and event.get('decision')=='WAIT':
                reason=event.get('reason','')
                if reason in ('congestion_queue','signal_queue_not_green') or event.get('source')=='MATSim15_queue_post_step':
                    counts['unknown_queue_position_excluded'] += 1
                else:
                    time=float(event['time'])
                    reasons[reason] += 1
                    signal_states[event.get('signalState','not_recorded')] += 1
                    candidates=[segment for segment in by_link[(event.get('vehicle'),event.get('link'))]
                                if segment['timestamps'][0]<=time<=segment['timestamps'][1]]
                    if not candidates:
                        counts['no_matching_segment'] += 1
                        errors.append(dict(reason='native_wait_without_segment',vehicle=event.get('vehicle'),link=event.get('link'),time=time))
                    else:
                        plan=candidates[-1]['Motion_Plan']
                        position,speed=sample_motion(plan,time)
                        if plan['status']=='unavailable':
                            counts['unavailable_visual_gap'] += 1
                        elif position is None or speed is None:
                            errors.append(dict(reason='native_wait_without_visual_state',vehicle=event.get('vehicle'),time=time))
                        else:
                            maximum_speed=max(maximum_speed,speed)
                            maximum_distance_error=max(maximum_distance_error,abs(position-plan['distance_m']))
                            if speed>1e-7 or abs(position-plan['distance_m'])>1e-6:
                                errors.append(dict(reason='visual_motion_during_native_wait',vehicle=event.get('vehicle'),link=event.get('link'),time=time,speed_mps=speed))
                            else:
                                counts['stationary_at_recorded_endpoint'] += 1
            element.clear()
    return dict(valid=not errors,counts=dict(counts),reasons=dict(reasons),native_signal_states=dict(signal_states),
                max_visual_speed_during_wait_mps=maximum_speed,max_wait_endpoint_distance_error_m=maximum_distance_error,
                errors=errors,scope='Actual simz1NativeDecision WAIT events at QNode; upstream queue delay excluded because position is unknown')


def source_paths(selection):
    paths = {selection['directory'] / 'run-manifest.json'}
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                path = (selection['directory'] / value['path']).resolve()
                if path.is_relative_to(selection['directory']) and path.is_file():
                    paths.add(path)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(selection['manifest'])
    return sorted(paths)


def audit(selection, html_path, report):
    sources = source_paths(selection)
    before = {str(path.relative_to(selection['directory'])): sha256(path) for path in sources}
    html = Path(html_path).read_text(encoding='utf-8')
    payload = json.loads(re.search(r'<script id="replay-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    if payload.get('hud',{}).get('run_id') != selection['manifest']['run_id'] or payload.get('hud',{}).get('iteration') != selection['iteration']:
        raise ValueError('HTML no corresponde a la corrida/iteracion validada seleccionada')
    provenance_path=Path(html_path).with_suffix('.provenance.json')
    exported=json.loads(provenance_path.read_text(encoding='utf-8')) if provenance_path.is_file() else None
    segments = next(layer['data'] for layer in payload['layers'] if layer['id'] == 'trips')
    errors, counts, groups, fallback_reasons = [], Counter(), defaultdict(list), Counter()
    largest_distance_error = largest_phase_position_jump = largest_phase_speed_jump = largest_cap_excess = 0.0
    maximum_connected_speed_jump = 0.0
    connected_examples = []
    for index, segment in enumerate(segments):
        plan = segment['Motion_Plan']
        status, phases = plan['status'], plan['phases']
        counts[status] += 1
        if plan.get('fallback_reason'):
            fallback_reasons[plan['fallback_reason']] += 1
        trip = segment.get('Trip') or {}
        groups[(segment['vehicle'], segment.get('Agent_ID'), trip.get('Trip_ID', trip.get('Departure')))].append(segment)
        start, end = segment['timestamps']
        distance, cap = plan['distance_m'], plan.get('cap_mps')
        def error(label):
            errors.append(dict(segment=index, vehicle=segment['vehicle'], link=segment['Link_ID'], reason=label))
        if distance != segment['Distance_m']:
            error('plan_distance_changed')
        if segment['Speed_kmh'] is not None and end > start:
            if abs(segment['Speed_kmh'] - 3.6*distance/(end-start)) > 1e-6:
                error('measured_speed_changed')
        if status == 'unavailable':
            if phases or sample_motion(plan, start) != (None, None):
                error('unavailable_has_motion')
            continue
        if not phases:
            if distance > 1e-8 or end > start:
                error('missing_phases')
            continue
        if abs(phases[0][0]-start)>1e-7 or abs(phases[-1][1]-end)>1e-7:
            error('native_time_boundary_changed')
        integrated, previous_speed, previous_time = 0.0, None, start
        for t0,t1,s0,v0,a in phases:
            if not all(math.isfinite(value) for value in (t0,t1,s0,v0,a)) or t1<t0:
                error('invalid_phase')
                continue
            dt=t1-t0
            v1=v0+a*dt
            jump=abs(s0-integrated)
            largest_phase_position_jump=max(largest_phase_position_jump,jump)
            if jump>1e-6 or abs(t0-previous_time)>1e-7:
                error('phase_position_or_time_discontinuity')
            if min(v0,v1)<-1e-7:
                error('negative_speed')
            if cap is not None:
                excess=max(v0,v1)-cap
                largest_cap_excess=max(largest_cap_excess,excess)
                if excess>1e-7:
                    error('speed_cap_exceeded')
            if previous_speed is not None:
                speed_jump=abs(v0-previous_speed)
                largest_phase_speed_jump=max(largest_phase_speed_jump,speed_jump)
                if plan['feasible'] and speed_jump>1e-6:
                    error('feasible_phase_speed_discontinuity')
            if distance>1e-8 and plan.get('native_wait_boundary') is None and dt>1e-8 and max(v0,v1)<=1e-8:
                error('unobserved_stationary_hold')
            integrated += v0*dt+.5*a*dt*dt
            previous_speed,previous_time=v1,t1
        distance_error=abs(integrated-distance)
        largest_distance_error=max(largest_distance_error,distance_error)
        if distance_error>1e-6:
            error('distance_not_conserved')
        previous_position=-1e-7
        for sample in range(21):
            time=start+(end-start)*sample/20
            position,speed=sample_motion(plan,time)
            if position<previous_position-1e-7 or not -1e-7<=position<=distance+1e-7:
                error('position_outside_monotone_path')
            if speed<0 or cap is not None and speed>cap+1e-7:
                error('sampled_speed_outside_bounds')
            previous_position=position
        wait=plan.get('native_wait_boundary')
        if wait is not None:
            for time in (wait,(wait+end)/2,end):
                position,speed=sample_motion(plan,time)
                if abs(position-distance)>1e-6 or speed>1e-7:
                    error('native_endpoint_wait_not_preserved')
            counts['native_endpoint_waits_preserved'] += 1
    for records in groups.values():
        records.sort(key=lambda segment: tuple(segment['timestamps']))
        for left,right in zip(records,records[1:]):
            if abs(left['timestamps'][1]-right['timestamps'][0])>1e-8 or any(abs(a-b)>=1e-9 for a,b in zip(left['path'][-1],right['path'][0])):
                continue
            counts['connected_boundaries'] += 1
            lp,rp=left['Motion_Plan'],right['Motion_Plan']
            vleft,vright=lp.get('exit_speed_mps'),rp.get('entry_speed_mps')
            if vleft is None or vright is None:
                counts['unavailable_boundaries'] += 1
            else:
                jump=abs(vleft-vright)
                maximum_connected_speed_jump=max(maximum_connected_speed_jump,jump)
                if jump<1e-7:
                    counts['continuous_boundaries'] += 1
                else:
                    counts['explicit_discontinuous_boundaries'] += 1
                    if rp.get('entry_continuity')!='discontinuous_fallback':
                        errors.append(dict(reason='unlabelled_boundary_speed_jump',vehicle=right['vehicle'],link=right['Link_ID']))
                    if len(connected_examples)<12:
                        connected_examples.append(dict(vehicle=right['vehicle'],from_link=left['Link_ID'],to_link=right['Link_ID'],
                            time=right['timestamps'][0],exit_speed_mps=vleft,entry_speed_mps=vright,
                            left_status=lp['status'],right_status=rp['status'],reason=rp.get('fallback_reason')))
    native_wait_audit=audit_native_wait_samples(selection['events'],segments)
    errors.extend(native_wait_audit['errors'])
    after = {str(path.relative_to(selection['directory'])): sha256(path) for path in sources}
    result = dict(run_id=selection['manifest']['run_id'],iteration=selection['iteration'],
        scope='Audit of existing HTML and saved MATSim events only; neither export nor QSim was run',html_path=str(html_path),html_sha256=sha256(html_path),
        vehicles=len({s['vehicle'] for s in segments}),segments=len(segments),counts=dict(counts),
        fallback_reasons=dict(fallback_reasons),errors=errors,valid=not errors and before==after,
        max_distance_error_m=largest_distance_error,max_phase_position_jump_m=largest_phase_position_jump,
        max_phase_speed_jump_mps=largest_phase_speed_jump,max_cap_excess_mps=largest_cap_excess,
        max_connected_speed_jump_mps=maximum_connected_speed_jump,discontinuous_examples=connected_examples,
        native_wait_event_audit=native_wait_audit,
        source_files_unchanged=before==after,source_hashes_before=before,source_hashes_after=after,
        exporter=exported,
        limitations=['Fallback boundary speed discontinuities remain explicit; no observed acceleration is claimed.',
                     'Unavailable intervals are visual gaps and cannot be reconstructed within the known speed cap.'])
    atomic_json(report,result)
    if not result['valid']:
        raise ValueError(f'Visual audit failed: {len(errors)} violations; source_unchanged={before==after}')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,help='Omitir selecciona latest-successful validado; HTML debe coincidir')
    parser.add_argument('--iteration',type=int)
    parser.add_argument('--html',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='Informe JSON; nunca modifica el HTML')
    args=parser.parse_args()
    result=audit(select_run(args.run_dir,args.iteration),args.html,args.output)
    print(json.dumps({key:result[key] for key in ('run_id','iteration','vehicles','segments','counts','valid','source_files_unchanged','max_distance_error_m','max_cap_excess_mps')},indent=2))
