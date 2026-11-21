"""Absolute dated duties for a continuous weekday experiment; no new fleet.

The existing verified one-day timetable is repeated on its eligible civil days.
Vehicle IDs and physical routes remain unchanged. Departures are dated, clipped
to the experiment's demand service window, and still obey the native duty gate.
"""
from copy import deepcopy
from datetime import date, timedelta
import math


def continuous_plan(plan, temporal_policy):
    if temporal_policy is None:
        return plan
    p = temporal_policy
    if p.get('schema_version') != 'simz1-weekday-continuous-v1':
        raise ValueError('Unsupported temporal transit policy')
    study = p['windows']['study']
    simulation = p['windows']['simulation']
    cutoff = p['windows']['post_demand']['end_seconds']
    day = date.fromisoformat(p['study_date'])
    if p['timezone'] != 'America/Guatemala' or plan['service_date'] != day.isoformat():
        raise ValueError('Transit date/timezone differs from temporal policy')
    result = deepcopy(plan)
    result['services'], result['roster'] = [], []
    calendar = []
    first = math.floor((simulation['start_seconds'] - study['start_seconds']) / 86400)
    last = math.floor((cutoff - study['start_seconds']) / 86400)
    original_roster = {r['departure_id']: r for r in plan['roster']}
    for offset in range(first, last + 1):
        civil = day + timedelta(days=offset)
        shift = study['start_seconds'] + offset * 86400
        enabled = civil.weekday() < 5
        calendar.append(dict(date=civil.isoformat(), simulation_midnight_seconds=shift,
                             enabled=enabled, basis='existing weekday policy; weekends inactive'))
        if not enabled:
            continue
        suffix = '__' + civil.strftime('%Y%m%d')
        for original in plan['services']:
            service = deepcopy(original)
            service['service_id'] += suffix
            service['opens_s'] = max(simulation['start_seconds'], original['opens_s'] + shift)
            service['closes_s'] = original['closes_s'] + shift
            service['departure_cutoff_s'] = min(cutoff, service['closes_s'])
            service['service_date'] = civil.isoformat()
            if service['opens_s'] >= service['departure_cutoff_s']:
                continue
            any_departures = False
            for route in service['routes']:
                route['route_id'] += suffix
                kept = []
                for dep in route['departures']:
                    old = original_roster[dep['departure_id']]
                    start, end = dep['time_s'] + shift, old['end_time_s'] + shift
                    if not service['opens_s'] <= start < service['departure_cutoff_s'] or end > service['closes_s']:
                        continue
                    dep['departure_id'] += suffix
                    dep['time_s'] = start
                    kept.append(dep)
                    row = dict(old, departure_id=dep['departure_id'], service_id=service['service_id'],
                               route_id=route['route_id'], departure_time_s=start, end_time_s=end,
                               closes_s=service['closes_s'], departure_cutoff_s=service['departure_cutoff_s'],
                               civil_service_date=civil.isoformat())
                    result['roster'].append(row)
                route['departures'] = kept
                any_departures |= bool(kept)
            if any_departures:
                result['services'].append(service)
    result['roster'].sort(key=lambda r: (r['vehicle_id'], r['departure_time_s']))
    result['temporal_calendar'] = dict(schema_version='simz1-absolute-transit-calendar-v1',
        timezone=p['timezone'], study_date=p['study_date'], policy_sha256=p['policy_sha256'],
        days=calendar, new_departures_end_seconds=cutoff,
        closing='no_new_departures_finish_active; delayed and pending duties remain native outcomes',
        fleet_reused_across_days=True, weekdays=[0, 1, 2, 3, 4])
    return result
