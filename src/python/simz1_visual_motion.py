"""Additive, cap-bounded visual motion; never changes MATSim events or travel times.

Each phase is [absolute t0, absolute t1, distance at t0, speed at t0,
acceleration].  Integrating the phases gives the supplied network distance.
Native QNode WAIT proves an exit stop; a queue delay or an unexplained residual
does not.  Impossible intervals are explicit fallbacks, not invented physics.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import math


DEFAULT_SETTINGS = {
    'enabled': True,
    'profiles': {
        'Tortuga': {'acceleration_mps2': 1.0, 'deceleration_mps2': 1.5},
        'Normal': {'acceleration_mps2': 1.5, 'deceleration_mps2': 2.5},
        'Liebre': {'acceleration_mps2': 2.0, 'deceleration_mps2': 3.5},
    },
    'max_rate_multiplier': 4.0,
    'minimum_ramp_seconds': 0.15,
}
_EPS = 1e-8


def _number(value, name, minimum=0, strict=False):
    if isinstance(value, bool):
        raise ValueError(f'{name} debe ser numerico')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{name} debe ser numerico') from None
    if not math.isfinite(value) or value < minimum or strict and value == minimum:
        raise ValueError(f'{name} fuera de rango')
    return value


def normalize_settings(raw=None):
    """Validate and deep-copy the public JSON settings, including partial profiles."""
    if raw is None:
        return deepcopy(DEFAULT_SETTINGS)
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_SETTINGS):
        raise ValueError('Configuracion de movimiento visual desconocida')
    result = deepcopy(DEFAULT_SETTINGS)
    if 'enabled' in raw:
        if type(raw['enabled']) is not bool:
            raise ValueError('enabled debe ser booleano')
        result['enabled'] = raw['enabled']
    if 'profiles' in raw:
        profiles = raw['profiles']
        if not isinstance(profiles, dict) or set(profiles) - set(result['profiles']):
            raise ValueError('Perfil de movimiento visual desconocido')
        for name, rates in profiles.items():
            if not isinstance(rates, dict) or set(rates) - set(result['profiles'][name]):
                raise ValueError(f'Parametros de perfil desconocidos: {name}')
            for key, value in rates.items():
                result['profiles'][name][key] = _number(value, key, strict=True)
    for key, minimum in (('max_rate_multiplier', 1), ('minimum_ramp_seconds', 0)):
        if key in raw:
            result[key] = _number(raw[key], key, minimum)
    return result


def _base(distance, start, end, cap, acceleration, deceleration):
    return dict(version=1, phases=[], distance_m=distance, start_time=start, end_time=end,
                cap_mps=cap, acceleration_mps2=acceleration, deceleration_mps2=deceleration,
                reference_acceleration_mps2=acceleration, reference_deceleration_mps2=deceleration,
                rate_adaptation_factor=1.0, source='kinematic_solver', fallback_reason=None,
                feasible=True, continuous_position_observed=False, hold_start=None)


def _uniform_fallback(distance, start, end, cap, acceleration, deceleration, reason):
    plan = _base(distance, start, end, cap, acceleration, deceleration)
    duration = end - start
    plan.update(status='fallback', feasible=False, fallback_reason=reason,
                source='boundary_preserving_fallback')
    if distance > 0 and (duration <= 0 or cap is not None and distance/duration > cap + 1e-9):
        plan.update(status='unavailable', entry_speed_mps=None, exit_speed_mps=None,
                    fallback_reason='zero_duration_positive_distance' if duration <= 0 else 'distance_exceeds_speed_cap')
        return plan
    speed = distance / duration if duration > 0 else 0.0
    plan.update(entry_speed_mps=speed, exit_speed_mps=speed)
    if duration > 0:
        plan['phases'] = [[start, end, 0.0, speed, 0.0]]
    return plan


def _endpoint_fallback(distance, start, end, wait, cap, rates, reason):
    """Reduce smoothing, not observed waiting: linear approach then native hold."""
    plan = _uniform_fallback(distance,start,wait,cap,rates['acceleration_mps2'],rates['deceleration_mps2'],reason)
    plan['end_time'] = end
    plan['source'] = 'native_wait_fallback'
    if plan['status'] == 'unavailable':
        plan['fallback_reason'] = 'native_wait_boundary_exceeds_speed_cap'
        return plan
    plan.update(hold_start=wait,exit_speed_mps=0.0)
    if end-wait>_EPS:
        plan['phases'].append([wait,end,distance,0.0,0.0])
    return plan


def _phases(parts, start):
    """Integrate local (t0,t1,v0,a) phases, merging identical adjacent slopes."""
    phases, distance = [], 0.0
    for t0, t1, speed, acceleration in parts:
        if t1 - t0 <= 1e-10:
            continue
        phase = [start+t0, start+t1, distance, max(0.0, speed), acceleration]
        if phases and abs(phases[-1][4] - acceleration) < 1e-10:
            last = phases[-1]
            at_boundary = last[3] + last[4]*(phase[0]-last[0])
            if abs(at_boundary-phase[3]) < 1e-7:
                last[1] = phase[1]
            else:
                phases.append(phase)
        else:
            phases.append(phase)
        duration = t1-t0
        distance += speed*duration + 0.5*acceleration*duration*duration
    return phases


def _envelope_parts(duration, cap, entry, exit_speed, acceleration, deceleration):
    upper = [(0.0, cap), (acceleration, entry), (-deceleration, exit_speed+deceleration*duration)]
    lower = [(0.0, 0.0), (-deceleration, entry), (acceleration, exit_speed-acceleration*duration)]
    points = {0.0, duration}
    for lines in (upper, lower):
        for i, (slope, intercept) in enumerate(lines):
            for other_slope, other_intercept in lines[:i]:
                if slope == other_slope:
                    continue
                time = (other_intercept-intercept)/(slope-other_slope)
                if 0 < time < duration:
                    points.add(time)
    times, pieces = sorted(points), []
    lower_distance = upper_distance = 0.0
    for t0, t1 in zip(times, times[1:]):
        mid = (t0+t1)/2
        high = min(upper, key=lambda line: line[0]*mid+line[1])
        low = max(lower, key=lambda line: line[0]*mid+line[1])
        delta = t1-t0
        high0, low0 = high[0]*t0+high[1], low[0]*t0+low[1]
        upper_distance += high0*delta + 0.5*high[0]*delta*delta
        lower_distance += low0*delta + 0.5*low[0]*delta*delta
        pieces.append((t0, t1, low0, low[0], high0, high[0]))
    return pieces, lower_distance, upper_distance


def _bounded(distance, start, end, entry, exit_speed, cap, acceleration, deceleration):
    """Exact feasibility and construction for fixed speeds, time, distance and cap."""
    duration = end-start
    if duration <= 0:
        return [] if distance == 0 and entry == exit_speed == 0 else None
    if distance == 0 and entry == exit_speed == 0:
        return [[start,end,0.0,0.0,0.0]]
    tolerance = max(_EPS, distance*1e-10)
    if min(entry, exit_speed) < 0 or max(entry, exit_speed) > cap + _EPS:
        return None
    if exit_speed-entry > acceleration*duration+_EPS or entry-exit_speed > deceleration*duration+_EPS:
        return None
    pieces, low, high = _envelope_parts(duration, cap, entry, exit_speed, acceleration, deceleration)
    if distance < low-tolerance or distance > high+tolerance:
        return None
    # A single acceleration/cruise/brake trapezoid is easier to interpret when
    # possible; the envelope interpolation also covers slow feasible valleys.
    peak_low = max(entry, exit_speed)
    peak_high = min(cap, (duration+entry/acceleration+exit_speed/deceleration)/(1/acceleration+1/deceleration))
    def area(peak):
        return peak*duration-(peak-entry)**2/(2*acceleration)-(peak-exit_speed)**2/(2*deceleration)
    if peak_high >= peak_low and area(peak_low)-tolerance <= distance <= area(peak_high)+tolerance:
        left, right = peak_low, peak_high
        for _ in range(45):
            middle = (left+right)/2
            if area(middle) < distance:
                left = middle
            else:
                right = middle
        peak = (left+right)/2
        accelerate_until = max(0.0, (peak-entry)/acceleration)
        brake_from = duration-max(0.0, (peak-exit_speed)/deceleration)
        return _phases([(0, accelerate_until, entry, acceleration),
                        (accelerate_until, brake_from, peak, 0.0),
                        (brake_from, duration, peak, -deceleration)], start)
    weight = 0 if abs(high-low) <= tolerance else max(0.0, min(1.0, (distance-low)/(high-low)))
    return _phases([(t0,t1,(1-weight)*vlow+weight*vhigh,(1-weight)*alow+weight*ahigh)
                    for t0,t1,vlow,alow,vhigh,ahigh in pieces], start)


def _status(phases):
    if not phases or all(abs(p[3])+abs(p[4]) < _EPS for p in phases):
        return 'stationary'
    return 'kinematic' if any(abs(p[4]) > _EPS for p in phases) else 'constant'


def solve_motion(distance_m, start, end, entry_speed_mps, exit_speed_mps, cap_mps,
                 acceleration_mps2=1.5, deceleration_mps2=2.5):
    """Solve a bounded interval with fixed endpoint speeds and hard rate limits.

    An infeasible interval returns a labelled cap-safe uniform fallback.  If even
    the average exceeds the cap, phases are empty and status is ``unavailable``.
    """
    distance = _number(distance_m, 'distance_m')
    start, end = _number(start, 'start'), _number(end, 'end')
    if end < start:
        raise ValueError('Intervalo de movimiento negativo')
    entry, exit_speed = _number(entry_speed_mps, 'entry_speed'), _number(exit_speed_mps, 'exit_speed')
    cap = _number(cap_mps, 'cap_mps', strict=True)
    acceleration = _number(acceleration_mps2, 'acceleration_mps2', strict=True)
    deceleration = _number(deceleration_mps2, 'deceleration_mps2', strict=True)
    phases = _bounded(distance,start,end,entry,exit_speed,cap,acceleration,deceleration)
    if phases is None:
        return _uniform_fallback(distance,start,end,cap,acceleration,deceleration,'endpoint_speed_or_rate_infeasible')
    plan = _base(distance,start,end,cap,acceleration,deceleration)
    plan.update(phases=phases,status=_status(phases),entry_speed_mps=entry,exit_speed_mps=exit_speed)
    return plan


def sample_motion(plan, time):
    """Evaluate the same phase integral used by the browser; no frame history."""
    phases = plan.get('phases', [])
    if plan.get('status') == 'unavailable':
        return None, None
    if not phases:
        return (0.0, 0.0) if plan.get('distance_m',0) == 0 else (None,None)
    time = _number(time, 'time')
    if time <= phases[0][0]:
        return 0.0, phases[0][3]
    if time >= phases[-1][1]:
        return plan['distance_m'], max(0.0, phases[-1][3]+phases[-1][4]*(phases[-1][1]-phases[-1][0]))
    for t0,t1,s0,speed,acceleration in phases:
        if time < t1:
            delta = max(0.0,time-t0)
            return min(plan['distance_m'],max(0.0,s0+speed*delta+0.5*acceleration*delta*delta)), max(0.0,speed+acceleration*delta)
    return plan['distance_m'], plan['exit_speed_mps']


def _material_ramps_long_enough(phases, minimum):
    duration = change = 0.0
    sign = 0
    for t0,t1,_,_,acceleration in phases + [[0,0,0,0,0]]:
        current = 1 if acceleration > _EPS else -1 if acceleration < -_EPS else 0
        if current != sign:
            if abs(change) > 0.25 and duration+_EPS < minimum:
                return False
            duration = change = 0.0
        if current:
            duration += t1-t0
            change += acceleration*(t1-t0)
        sign = current
    return True


def _feasible(distance, start, end, entry, exit_speed, cap, acceleration, deceleration):
    """Test the same envelope bounds without building unused phase records.

    The maximal envelope is an acceleration/cruise/brake trapezoid. The minimal
    one brakes to a valley, cruises (possibly at zero), then accelerates. Their
    integrals below equal those of _envelope_parts. Near a floating-point
    decision boundary, retain the original piecewise calculation as the oracle.
    """
    duration = end-start
    if duration <= 0:
        return distance == 0 and entry == exit_speed == 0
    if distance == 0 and entry == exit_speed == 0:
        return True
    if min(entry,exit_speed) < 0 or max(entry,exit_speed) > cap+_EPS:
        return False
    if exit_speed-entry > acceleration*duration+_EPS or entry-exit_speed > deceleration*duration+_EPS:
        return False
    reciprocal = 1/acceleration+1/deceleration
    peak = min(cap,(duration+entry/acceleration+exit_speed/deceleration)/reciprocal)
    valley = max(0.0,(entry/deceleration+exit_speed/acceleration-duration)/reciprocal)
    high = peak*duration-(peak-entry)**2/(2*acceleration)-(peak-exit_speed)**2/(2*deceleration)
    low = valley*duration+(entry-valley)**2/(2*deceleration)+(exit_speed-valley)**2/(2*acceleration)
    tolerance = max(_EPS,distance*1e-10)
    lower,upper = low-tolerance,high+tolerance
    rounding_guard = 64*math.ulp(max(1.0,abs(distance),abs(low),abs(high)))
    if min(abs(distance-lower),abs(distance-upper)) <= rounding_guard:
        return _bounded(distance,start,end,entry,exit_speed,cap,acceleration,deceleration) is not None
    return lower <= distance <= upper


def _fit(distance,start,end,entry,exit_speed,cap,rates,settings):
    acceleration, deceleration = rates['acceleration_mps2'], rates['deceleration_mps2']
    phases = _bounded(distance,start,end,entry,exit_speed,cap,acceleration,deceleration)
    factor = 1.0
    if phases is None:
        maximum = settings['max_rate_multiplier']
        phases = _bounded(distance,start,end,entry,exit_speed,cap,acceleration*maximum,deceleration*maximum)
        if phases is None:
            return None
        lower, upper = 1.0, maximum
        for _ in range(32):
            middle = (lower+upper)/2
            if not _feasible(distance,start,end,entry,exit_speed,cap,acceleration*middle,deceleration*middle):
                lower = middle
            else:
                upper = middle
        factor = upper
        phases = _bounded(distance,start,end,entry,exit_speed,cap,acceleration*factor,deceleration*factor)
        if phases is None:
            # Numerical guard: phase construction remains authoritative. The
            # old search is retained for an exceptional disagreement, preserving
            # the known feasible maximum and the original iteration count.
            lower,upper = 1.0,maximum
            for _ in range(32):
                middle = (lower+upper)/2
                if _bounded(distance,start,end,entry,exit_speed,cap,acceleration*middle,deceleration*middle) is None:
                    lower = middle
                else:
                    upper = middle
            factor = upper
            phases = _bounded(distance,start,end,entry,exit_speed,cap,acceleration*factor,deceleration*factor)
    if not _material_ramps_long_enough(phases,settings['minimum_ramp_seconds']):
        return None
    plan = _base(distance,start,end,cap,acceleration*factor,deceleration*factor)
    plan.update(phases=phases,status=_status(phases),entry_speed_mps=entry,exit_speed_mps=exit_speed,
                reference_acceleration_mps2=acceleration,reference_deceleration_mps2=deceleration,
                rate_adaptation_factor=factor)
    return plan


def _endpoint_wait(segment):
    result = []
    for reason, record in segment.get('Observed_Waits',{}).items():
        if not isinstance(record,dict) or record.get('first') is None:
            continue
        sources = record.get('sources',[])
        if isinstance(sources,str):
            sources = [sources]
        unknown = record.get('position_evidence') == 'unknown_queue_position' or 'MATSim15_queue_post_step' in sources or reason in ('congestion_queue','signal_queue_not_green')
        endpoint = record.get('position_evidence') == 'queue_exit' or any(source in sources for source in
            ('MATSim15_QNode_native_branch','SimZ1_QNode_strict_receiver_v1')) or reason.startswith('priority_') or reason in ('storage_wait','intersection_conflict','signal_red','signal_redyellow','signal_not_green','admission_conflict_executed')
        if endpoint and not unknown:
            result.append(_number(record['first'],'wait first'))
    return min(result) if result else None


def _info(segment):
    start,end = map(float,segment['timestamps'])
    distance = float(segment.get('Distance_m',0))
    if not all(math.isfinite(v) for v in (start,end,distance)) or min(start,distance)<0 or end<start:
        raise ValueError('Segmento visual invalido')
    provenance = segment.get('Motion_Provenance',{})
    limits = [provenance.get('vehicle_limit_mps'),provenance.get('link_speed_at_entry_mps')]
    known = [_number(v,'speed_limit',strict=True) for v in limits if v is not None]
    interval_minimum = provenance.get('minimum_link_speed_in_interval_mps')
    if interval_minimum is not None:
        known.append(_number(interval_minimum,'minimum_link_speed_in_interval_mps',strict=True))
    cap = min(known) if known else None
    wait = _endpoint_wait(segment)
    if wait is not None:
        wait = max(start,min(end,wait))
    movement_end = wait if wait is not None else end
    duration = movement_end-start
    average = distance/duration if duration>0 else 0.0
    complete = all(value is not None for value in limits) and provenance.get('fallback_reason') != 'unregistered_network_changes'
    return dict(start=start,end=end,distance=distance,cap=cap,complete_limits=complete,
                stop=wait,move_end=movement_end,average=average,
                target=min(cap,average) if cap is not None else average)


def _connected(left,right):
    if abs(left['timestamps'][1]-right['timestamps'][0]) > _EPS:
        return False
    a,b = left.get('path',[]),right.get('path',[])
    return bool(a and b and len(a[-1])==len(b[0]) and all(abs(x-y)<1e-9 for x,y in zip(a[-1],b[0])))


def _key(segment):
    trip = segment.get('Trip') or {}
    return str(segment.get('vehicle','')),str(segment.get('Agent_ID','')),str(trip.get('Trip_ID',trip.get('Departure','')))


def apply_visual_motion(segments, settings=None):
    """Attach Motion_Plan only, with bounded continuity across connected trip links.

    This intentionally leaves timestamps, Movement_End, Speed_kmh and all native
    provenance untouched.  Returned counters describe visual reconstruction.
    """
    settings = normalize_settings(settings)
    counts, groups = Counter(),defaultdict(list)
    for segment in segments:
        if 'timestamps' in segment and 'path' in segment:
            groups[_key(segment)].append(segment)
    for group in groups.values():
        group.sort(key=lambda segment: (segment['timestamps'][0],segment['timestamps'][1]))
        infos = [_info(segment) for segment in group]
        previous = None
        for index,(segment,info) in enumerate(zip(group,infos)):
            start,end,distance,cap = (info[key] for key in ('start','end','distance','cap'))
            profile = segment.get('Profile','Normal')
            rates = settings['profiles'].get(profile,settings['profiles']['Normal'])
            connected = index>0 and _connected(group[index-1],segment)
            next_connected = index+1<len(group) and _connected(segment,group[index+1])
            entry = info['target']
            if info['stop'] is not None and cap is not None:
                entry = cap  # Initial speed is unobserved, not a fabricated launch from rest.
            if connected and previous is not None:
                entry = previous.get('exit_speed_mps')
                if entry is None:
                    entry = info['target']
            exit_speed = 0.0 if info['stop'] is not None else info['target']
            if info['stop'] is None and next_connected:
                next_info = infos[index+1]
                if cap is not None and next_info['cap'] is not None:
                    # The interval nearest its cap has least freedom to change
                    # endpoint speed; honor it first instead of stopping at a node.
                    own_ratio = info['average']/cap
                    next_ratio = next_info['average']/next_info['cap']
                    desired = info['target'] if own_ratio>=next_ratio else next_info['target']
                    exit_speed = min(cap,next_info['cap'],desired)
            reason = None
            if not settings['enabled']:
                reason = 'smoothing_disabled'
            elif segment.get('Motion_Provenance',{}).get('fallback_reason') == 'unregistered_network_changes':
                reason = 'unregistered_network_changes'
            elif not info['complete_limits']:
                reason = 'missing_speed_limit'
            elif segment.get('Inferred'):
                reason = 'inferred_interval_geometry'
            elif segment.get('Motion_Provenance',{}).get('changes_inside_interval'):
                reason = 'speed_change_with_unknown_internal_entry'
            plan = None
            if reason is None and distance==0:
                plan = solve_motion(0,start,end,0,0,cap,rates['acceleration_mps2'],rates['deceleration_mps2'])
            elif reason is None:
                candidates = [(entry,exit_speed)]
                if not connected:
                    candidates.extend((value,exit_speed) for value in (info['target'],cap) if value!=entry)
                if info['stop'] is None:
                    end_cap=cap if not next_connected or infos[index+1]['cap'] is None else min(cap,infos[index+1]['cap'])
                    candidates.extend((entry,value) for value in (min(info['target'],end_cap),end_cap) if value!=exit_speed)
                for candidate_entry,candidate_exit in candidates:
                    candidate = _fit(distance,start,info['move_end'],candidate_entry,candidate_exit,cap,rates,settings)
                    if candidate is not None and info['stop'] is None and any(
                            t1-t0>_EPS and (max(v0,v0+a*(t1-t0))<=_EPS or
                                t0>start+_EPS and v0<=_EPS or
                                t1<info['move_end']-_EPS and v0+a*(t1-t0)<=_EPS)
                            for t0,t1,_,v0,a in candidate['phases']):
                        # The lower feasible envelope can contain a stationary
                        # valley. Without an exit WAIT this is not stop evidence.
                        candidate = None
                    if candidate is not None and (plan is None or candidate['rate_adaptation_factor'] < plan['rate_adaptation_factor']-1e-8):
                        plan = candidate
                    if plan is not None and plan['rate_adaptation_factor']==1:
                        break
                if plan is not None and info['stop'] is not None:
                    plan['hold_start'] = info['stop']
                    if end-info['stop']>_EPS:
                        plan['phases'].append([info['stop'],end,distance,0.0,0.0])
                    plan['end_time'] = end
                if plan is None:
                    reason = 'native_wait_kinematics_infeasible' if info['stop'] is not None else 'continuous_speed_or_rate_infeasible'
            if plan is None:
                plan = (_endpoint_fallback(distance,start,end,info['stop'],cap,rates,reason) if info['stop'] is not None else
                        _uniform_fallback(distance,start,end,cap,rates['acceleration_mps2'],rates['deceleration_mps2'],reason))
            elif info['stop'] is not None:
                plan['source'] = 'native_wait'
            elif segment.get('Observed_Waits'):
                plan['source'] = 'queue_delay_estimate'
            else:
                plan['source'] = 'continuous_link'
            plan.update(profile=profile if profile in settings['profiles'] else 'Normal',
                        profile_source='recorded_profile' if profile in settings['profiles'] else 'default_visual_reference',
                        recorded_profile=profile, rate_model='visual_interpolation_only_not_qsim_acceleration',
                        limits_complete=info['complete_limits'],native_wait_boundary=info['stop'])
            if connected and previous is not None:
                left,right = previous.get('exit_speed_mps'),plan.get('entry_speed_mps')
                matched = left is not None and right is not None and abs(left-right)<1e-7
                continuity = 'matched' if matched else 'unavailable_boundary' if left is None or right is None else 'discontinuous_fallback'
                plan['entry_continuity'] = previous['exit_continuity'] = continuity
                if not matched:
                    counts['discontinuous_boundaries'] += 1
            else:
                plan['entry_continuity'] = 'unobserved_boundary'
            plan.setdefault('exit_continuity','unobserved_boundary')
            segment['Motion_Plan'] = previous = plan
            counts[plan['status']] += 1
            counts['adapted_rates'] += plan.get('rate_adaptation_factor',1)>1+1e-7
            counts['native_wait_holds'] += plan.get('hold_start') is not None
    return dict(version=1,enabled=settings['enabled'],segments=sum(counts.get(key,0) for key in ('kinematic','constant','stationary','fallback','unavailable')),
                counts=dict(counts),settings=settings)
