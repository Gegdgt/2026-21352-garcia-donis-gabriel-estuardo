"""Versioned freight timing contracts; never moves actors or rewrites events."""
import json
import math
from pathlib import Path

POLICY='freight-close-plus3600-v1'
TOLERATED_ENTRY_POLICY='freight-entry-and-completion-close-plus3600-v2'
EXPERIMENTAL_POLICIES=(POLICY,TOLERATED_ENTRY_POLICY)
HISTORICAL='nominal-residence-v2'
RESOURCE=Path(__file__).resolve().parents[1]/'src/main/resources/simz1/freight-completion-v1.json'
ENTRY_RESOURCE=RESOURCE.with_name('freight-entry-completion-v2.json')
WINDOWS=((0,18000),(32400,57600),(75600,104400))

def policy_document(policy=POLICY):
    if policy not in EXPERIMENTAL_POLICIES:raise ValueError('Unknown freight timing policy')
    doc=json.loads((ENTRY_RESOURCE if policy==TOLERATED_ENTRY_POLICY else RESOURCE).read_bytes())
    if (doc['version']!=policy or doc['tolerance_seconds']!=3600 or doc['nominal_windows_seconds']!=list(map(list,WINDOWS))
            or doc['observation_end_seconds']!=(86400 if policy==TOLERATED_ENTRY_POLICY else 108000) or doc['demand_end_seconds_exclusive']!=86400
            or doc['deadline_inclusive'] is not True):raise ValueError('Changed freight completion policy contract')
    expected='assigned_window_close_plus3600_inclusive' if policy==TOLERATED_ENTRY_POLICY else 'original_assigned_nominal_window_only'
    if doc.get('entry_policy')!=expected:raise ValueError('Changed freight entry policy contract')
    if policy==TOLERATED_ENTRY_POLICY and any(type(doc.get(k)) is not type(v) or doc.get(k)!=v for k,v in dict(
            schema='simz1-freight-completion-policy',entry_deadline_equals_completion_deadline=True,
            assumption_status='synthetic_experiment_not_legal_permission',window_assignment='original_roster_planned_departure',
            observation_policy='fixed-day-24h-v1',nominal_violation_retained=True,
            deadline_does_not_interrupt_qsim=True,historical_runs_reinterpreted=False,
            completion_requires=['native_arrival','traffic_exit','native_body_plus_0.10m_clearance'],
            expired_origin_behavior='retain_native_fifo_wait_until_normal_day_census_and_cleanup').items()):
        raise ValueError('Changed freight entry/completion evidence contract')
    return doc

def assigned_window(departure):
    if type(departure) not in (int,float) or not math.isfinite(departure) or not 0<=departure<86400:
        raise ValueError('Invalid original freight scheduled departure')
    for a,b in WINDOWS:
        if a<=departure<b:return (a,b)
    raise ValueError('Freight scheduled outside nominal windows')


def entry_permitted(departure, entry, policy=POLICY):
    if policy not in EXPERIMENTAL_POLICIES:raise ValueError('Unknown freight timing policy')
    a,b=assigned_window(departure)
    return (type(entry) in (int,float) and math.isfinite(entry) and entry>=max(a,departure-1.01)
            and (entry<=b+3600 if policy==TOLERATED_ENTRY_POLICY else entry<b))

def observation_contract(manifest):
    selected=manifest.get('experiment')
    if selected is None:return None
    from simz1_day_observation import enabled, POLICY as DAY
    if enabled(manifest):
        if selected.get('observation_end_seconds')!=86400 or manifest.get('time_horizon')!=dict(start_seconds=0,end_seconds=86400):
            raise ValueError('Fixed-day manifest horizon differs')
        return dict(policy=DAY,demand_end_seconds=86400,observation_end_seconds=86400,
            demand_window=dict(start_seconds=0,end_seconds=86400),followup_window=None)
    if (selected.get('freight_completion_policy')!=POLICY or selected.get('demand_end_seconds')!=86400 or
            selected.get('observation_end_seconds')!=108000 or
            manifest.get('time_horizon')!=dict(start_seconds=0,end_seconds=108000)):
        raise ValueError('Unrecognized experimental observation contract')
    return dict(policy=POLICY,demand_end_seconds=86400,observation_end_seconds=108000,
        demand_window=dict(start_seconds=0,end_seconds=86400),followup_window=dict(start_seconds=86400,end_seconds=108000))

def evaluate(row, *, entry=None, traffic_exit=None, arrival=None, clearance=None, aborted=False, nominal_violation=False):
    """clearance is the independent native ledger proof, NOT a last-link label.

    Its sampled time is an upper bound for clearance, not an invented exact
    crossing time. Arrival and exit remain separate observations.
    """
    a,b=assigned_window(row['departure_seconds'])
    policy=row.get('completion_policy',POLICY)
    if policy not in EXPERIMENTAL_POLICIES:raise ValueError('Unknown freight timing policy')
    result=dict(vehicle_id=row.get('vehicle_id'),route_id=row.get('route_id'),policy=policy,
        assigned_window_seconds=[a,b],window_close_seconds=b,deadline_seconds=b+3600,
        scheduled_departure_seconds=row['departure_seconds'],entry_seconds=entry,
        traffic_exit_seconds=traffic_exit,arrival_seconds=arrival,
        clearance_proof=clearance,clearance_time_basis='sampled_native_lower_bound_not_exact_crossing',
        delay_seconds=None,nominal_violation=nominal_violation,classification='pending_not_evaluable',
        trip_outcome='aborted' if aborted else 'pending',technical_integrity='not_evaluable')
    values=(entry,traffic_exit,arrival)
    if any(v is not None and (type(v) not in (int,float) or not math.isfinite(v)) for v in values):
        result.update(classification='technical_physical_error',technical_integrity='invalid');return result
    if entry is not None and not entry_permitted(row['departure_seconds'],entry,policy):
        result.update(classification='technical_physical_error',technical_integrity='invalid',entry_violation=True);return result
    if aborted or any(v is None for v in values) or clearance is None:return result
    gap=clearance.get('minimum_gap_m');rear=clearance.get('rear_plus_gap_clearance_m')
    if (gap!=0.1 or type(rear) not in (int,float) or not math.isfinite(rear) or rear < -1e-7
            or not row['departure_seconds']-1.01<=entry<=traffic_exit<=arrival):
        result.update(classification='technical_physical_error',technical_integrity='invalid');return result
    finish=max(traffic_exit,arrival)
    nominal=nominal_violation or finish>=b
    result.update(trip_outcome='completed',technical_integrity='valid',delay_seconds=max(0,finish-b),nominal_violation=nominal,
        classification='nominal' if not nominal else 'tolerated' if finish<=b+3600 else 'excess_tolerance')
    return result
