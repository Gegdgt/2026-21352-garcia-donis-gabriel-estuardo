"""Report a validated SimZ1 run from compact trips and recorded diagnostics.

No QSim launch, event XML decompression, replay sampling or score conversion.
The manifest is the audited event source; log deltas are reconciled with it.
"""
import argparse
from array import array
from collections import Counter, defaultdict
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from simz1_native_validation import NativeDecisionAudit
from simz1_run import atomic_json, checked_path, parameters, select_run, sha256
from simz1_trip_table import export_table, rows, validate_compact, DEFINITION


PROGRESS_PATTERN = re.compile(r'SIMZ1_PROGRESS simulatedTime=([0-9.eE+-]+) \{(.*)\}\s*$')
DELTAS = {
    'linkTransitions': 'link_transitions', 'arrivals': 'arrivals',
    'rerouteCalculations': 'reroute_calculations', 'waitSignal': 'wait_signal',
    'waitStorage': 'wait_storage', 'waitPriority': 'wait_priority',
    'waitCongestion': 'wait_congestion', 'turnRestrictions': 'turn_restrictions',
    'forcedMoves': 'forced_moves',
}
SETTINGS = (
    'qsim.startTime', 'qsim.endTime', 'qsim.numberOfThreads', 'qsim.stuckTime',
    'qsim.removeStuckVehicles', 'qsim.flowCapacityFactor', 'qsim.storageCapacityFactor',
    'qsim.useLanes', 'signalsystems.useSignalsystems', 'zona1Diagnostics.incidentsEnabled',
    'zona1Priority.enabled', 'zona1Priority.classification', 'zona1Priority.conflicts',
    'zona1Priority.stopSeconds', 'zona1Priority.maxYieldSeconds',
    'simz1Admission.storagePolicy',
    'zona1WithinDayRouting.enabled',
)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def csv_file(path, records, fields):
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def progress_attributes(text):
    """Parse one Java map, retaining nested diagnostic maps as whole values."""
    fields, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == '{': depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0: raise ValueError('Mapa de progreso mal formado')
        elif char == ',' and depth == 0:
            fields.append(text[start:index].strip())
            start = index + 1
    if depth: raise ValueError('Mapa de progreso truncado')
    fields.append(text[start:].strip())
    result = {}
    for field in fields:
        if '=' not in field: raise ValueError('Campo de progreso mal formado')
        key, value = field.split('=', 1)
        if not key or key in result: raise ValueError('Campo de progreso vacio o duplicado')
        result[key] = value
    return result


def progress_log(path, iteration, expected):
    """Read ONE log, preserving its interval clocks and active snapshots."""
    audit = NativeDecisionAudit()
    records = []
    observed_fields = set()
    previous = None
    with Path(path).open(encoding='utf-8', errors='strict') as stream:
        for line_number, line in enumerate(stream, 1):
            match = PROGRESS_PATTERN.search(line)
            if not match:
                if 'SIMZ1_PROGRESS simulatedTime=' in line:
                    raise ValueError('Linea de progreso truncada o mal formada')
                continue
            attributes = progress_attributes(match[2])
            if int(attributes['iteration']) != iteration:
                continue
            time = float(match[1])
            if previous is not None and time <= previous:
                raise ValueError('Progreso duplicado o no monotono; no se suman dos logs/corridas')
            elapsed = float(attributes['elapsedSimSeconds'])
            if previous is not None and not math.isclose(time-elapsed, previous, abs_tol=1e-6):
                raise ValueError('Falta un intervalo de progreso en el log seleccionado')
            attributes['time'] = str(time)
            audit.record_progress(ET.Element('event', attributes))
            record = dict(time=time, interval_start_seconds=time-elapsed,
                          interval_end_seconds=time, elapsed_sim_seconds=elapsed,
                          active_vehicles=int(attributes['activeVehicles']),
                          thread_deadlocks=int(attributes['threadDeadlocks']),
                          classification=attributes['classification'], source_line=line_number)
            # Gauges remain interval observations, never summed into unique vehicles or seconds.
            record['wait_observation'] = {key:attributes[key] for key in (
                'waitAttemptsUnit', 'waitAttempts', 'waitUnknown', 'waitAttemptsByCategory',
                'waitingDistinctVehicles', 'waitingDistinctVehiclesByCategory',
                'maximumObservedWaitAgeSecondsByCategory', 'waitDurationBasis') if key in attributes} or None
            for source, target in DELTAS.items():
                record[target] = int(attributes[source]) if source in attributes else None
            records.append(record)
            observed_fields.update(attributes)
            previous = time
    if not records:
        raise ValueError(f'Sin progreso nativo de iteracion {iteration}: {path}')
    summary = audit.summary()
    if summary['progress_samples'] != expected['progress_samples']:
        raise ValueError('Cantidad de muestras del log no coincide con los eventos auditados')
    for key, value in expected['progress'].items():
        if key not in summary['progress']:
            continue
        actual = summary['progress'][key]
        if isinstance(value, (int, float)):
            equal = math.isclose(actual, value, rel_tol=1e-12, abs_tol=1e-6)
        else:
            equal = actual == value
        if not equal:
            raise ValueError(f'Progreso log/eventos incompatible: {key}: {actual} != {value}')
    return records, dict(path=str(Path(path).resolve()), sha256=sha256(path),
        samples=len(records), checked_against='manifest.results[iteration].native_qsim.progress',
        reconciled=True, available_delta_fields=[target for source, target in DELTAS.items()
                                                if source in observed_fields])


def trip_metrics(path, run_id, iteration, mode='car'):
    """Exact per-leg durations, one numeric array, no per-person chart fan-out."""
    import numpy as np
    counts = Counter()
    cohorts = defaultdict(Counter)
    values = array('d')
    for row in rows(path):
        if row['run_id'] != run_id or row['iteration'] != iteration:
            raise ValueError('Viajes de otra corrida/iteracion')
        counts['all_modes_departures'] += 1
        if mode != 'all' and row['mode'] != mode:
            counts['other_mode'] += 1
            continue
        counts['departures'] += 1
        counts[row['status']] += 1
        cohort = cohorts[int(row['departure'] // 3600)]
        cohort['departures'] += 1
        cohort[row['status']] += 1
        if row['status'] == 'completed':
            values.append(row['duration_seconds'])
    durations = np.frombuffer(values, dtype='float64')
    quantiles = np.quantile(durations, [.05, .25, .50, .75, .95, .99]) if len(values) else [None]*6
    return dict(mode=mode, departures=counts['departures'],
        all_modes_departures=counts['all_modes_departures'], other_mode=counts['other_mode'],
        completed=counts['completed'], aborted_before_horizon=counts['aborted'],
        censored_at_horizon=counts['censored'], completion_rate=ratio(counts['completed'], counts['departures']),
        durations_completed_only=dict(n=len(values), excluded=counts['departures']-len(values),
            mean_seconds=float(durations.mean()) if len(values) else None,
            minimum_seconds=float(durations.min()) if len(values) else None,
            maximum_seconds=float(durations.max()) if len(values) else None,
            **dict(zip(('p05_seconds','p25_seconds','p50_seconds','p75_seconds','p95_seconds','p99_seconds'), quantiles))),
        by_departure_hour={str(h): dict(c) for h, c in sorted(cohorts.items())},
        definition=DEFINITION)


def hourly_metrics(temporal, intervals):
    """Keep exact event hours apart from progress-report interval attribution."""
    by_end_hour = defaultdict(Counter)
    snapshots = {}
    fields = set()
    for interval in intervals:
        hour = int(interval['time'] // 3600)
        target = by_end_hour[hour]
        target['progress_samples'] += 1
        # Never divide integer observations over hours or invent precise event times.
        if interval['elapsed_sim_seconds'] and int(interval['interval_start_seconds'] // 3600) != hour:
            target['intervals_crossing_hour_boundary'] += 1
        for name in DELTAS.values():
            if interval[name] is not None:
                target['reported_delta_'+name] += interval[name]
                fields.add('reported_delta_'+name)
        snapshots[hour] = interval
    event_hours = temporal.get('by_event_hour', {})
    cohorts = temporal.get('by_departure_hour', {})
    hours = sorted(set(map(int, event_hours)) | set(map(int, cohorts)) | set(by_end_hour))
    result = []
    for hour in hours:
        events, cohort = event_hours.get(str(hour), {}), cohorts.get(str(hour), {})
        snapshot = snapshots.get(hour)
        item = dict(hour=hour, departures_at_event_hour=events.get('departures', 0),
                    arrivals_at_event_hour=events.get('arrivals', 0),
                    accepted_abort_trip_terminals_at_event_hour=events.get('abort_events', 0),
                    cohort_departures=cohort.get('departures', 0),
                    cohort_completed=cohort.get('completed', 0),
                    cohort_censored=cohort.get('censored', 0),
                    cohort_aborted_before_horizon=cohort.get('aborted_before_horizon', 0),
                    active_snapshot_time=snapshot['time'] if snapshot else None,
                    active_vehicles_snapshot=snapshot['active_vehicles'] if snapshot else None,
                    progress_samples=by_end_hour[hour]['progress_samples'],
                    intervals_crossing_hour_boundary=by_end_hour[hour]['intervals_crossing_hour_boundary'])
        item.update({name: by_end_hour[hour][name] for name in sorted(fields)})
        result.append(item)
    return result


def collect_report(selection, table=None, mode='car'):
    directory, manifest, iteration = selection['directory'], selection['manifest'], selection['iteration']
    result = manifest['results'][str(iteration)]
    product = manifest['trip_products'][str(iteration)]
    if table is None:
        table = checked_path(directory, product['compact'])
        validate_compact(table, manifest['run_id'], iteration,
                         horizon=manifest['time_horizon']['end_seconds'])
    trips = trip_metrics(table, manifest['run_id'], iteration, mode)
    expected = product['counts']
    if trips['all_modes_departures'] != expected['rows']:
        raise ValueError('La cantidad de viajes no coincide con el manifiesto')
    if mode == 'all' or not trips['other_mode']:
        for key, field in (('completed','completed'), ('aborted_before_horizon','aborted'),
                           ('censored_at_horizon','censored')):
            if trips[key] != expected[field]:
                raise ValueError(f'Estado de viajes incompatible: {key}')
    native = result['native_qsim']
    log = directory/'output/logfile.log'
    intervals, progress_source = progress_log(log, iteration, native)
    horizon = manifest['time_horizon']['end_seconds']
    horizon_records = [record for record in intervals if record['time'] <= horizon]
    at_horizon = horizon_records[-1] if horizon_records else None
    config = parameters(checked_path(directory, manifest['effective_config']))
    forced = native['forced_storage_moves']
    event_departures = result['counts']['observed_departures']
    elapsed = None
    if manifest.get('started_utc') and manifest.get('finished_utc'):
        elapsed = (datetime.fromisoformat(manifest['finished_utc'])-
                   datetime.fromisoformat(manifest['started_utc'])).total_seconds()
    report = dict(schema_version=1, run_id=manifest['run_id'], run_dir=str(directory), iteration=iteration,
        manifest_sha256=sha256(directory/'run-manifest.json'),
        source_records=dict(compact=product['compact'], events=result['events'],
                            effective_config=manifest['effective_config'], progress_log=progress_source),
        seeds=dict(demand=manifest['demand_seed'], matsim=manifest['matsim_seed']),
        planned=manifest['counts'], demand_window=manifest.get('demand_window'),
        horizon=manifest['time_horizon'], observed_event_end_seconds=result['observed_event_end_seconds'],
        effective_settings={key:config.get(key) for key in SETTINGS},
        input_hashes={name: record['sha256'] for name,record in manifest['inputs'].items()},
        trips=trips, event_counts=result['counts'],
        pending=dict(censored_legs_at_cut=result['counts']['pending_legs_at_horizon'],
            active_vehicles_snapshot=at_horizon['active_vehicles'] if at_horizon else None,
            active_snapshot_seconds=at_horizon['time'] if at_horizon else None,
            snapshot_exactly_at_horizon=at_horizon is not None and at_horizon['time'] == horizon,
            maximum_active_vehicles=native['progress']['max_active_vehicles']),
        native=dict(forced_storage_moves=forced, storage_stuck_removals=native['storage_stuck_removals'],
            forced_per_1000_observed_departures=1000*forced/event_departures if event_departures else None,
            reason_attempts=native['reasons'], wait_category_attempts=native.get('wait_categories'),
            progress=native['progress'], physical_stability=native['physical_stability']),
        runtime=dict(launcher_including_validation_seconds=elapsed,
            qsim_instrumented_wall_seconds=native['progress']['wall_nanos']/1e9,
            qsim_process_cpu_seconds=native['progress']['process_cpu_nanos']/1e9),
        notes=[
            'Durations include only completed departure-arrival legs. Censored/aborted legs have no invented duration.',
            'Terminal completeness uses the full audited file through observed_event_end_seconds; final QSim cleanup may be one step beyond the configured horizon. Active snapshots retain their own timestamp.',
            'Cleanup aborts at/after the horizon are censored legs, not early aborts. Accepted abort-trip terminals are deduplicated; observed_abort_events counts raw vehicle/person events and can be larger.',
            'Pending legs at the horizon include departures not completed; activeVehicles is a network-entry minus network-exit snapshot. These are different populations.',
            'Native WAIT counters count decision attempts, not seconds, unique vehicles or independent episodes.',
            'Hour columns departures/arrivals use exact absolute event hours. reported_delta_* columns assign whole progress intervals to their report-end hour; intervals crossing an hour are flagged, never prorated.',
            'Missing historical wait categories/congestion instrumentation remain unavailable; they are not inferred as zero.',
            'Events are reused from the validated manifest, without another XML decompression pass. select_run checks source hashes.',
            'Forced storage moves do not prove physical stability, even when the process finishes successfully.',
        ])
    return report, intervals, hourly_metrics(result['temporal_events'], intervals)


def compare_reports(current, historical):
    current_horizon, historical_horizon = current.get('horizon'), historical.get('horizon')
    current_end = current.get('observed_event_end_seconds')
    historical_end = historical.get('observed_event_end_seconds')
    def valid_time(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    def valid_horizon(value):
        return (isinstance(value, dict) and valid_time(value.get('start_seconds')) and
                valid_time(value.get('end_seconds')) and value['end_seconds'] > value['start_seconds'])
    comparable_horizons = (valid_horizon(current_horizon) and valid_horizon(historical_horizon) and
        all(current_horizon[key] == historical_horizon[key] for key in ('start_seconds', 'end_seconds')) and
        valid_time(current_end) and valid_time(historical_end) and current_end == historical_end)
    scopes = {}
    for label, horizon, observed_end in (('current', current_horizon, current_end),
                                        ('historical', historical_horizon, historical_end)):
        for edge in ('start_seconds', 'end_seconds'):
            scopes[label+'_configured_'+edge] = horizon.get(edge) if isinstance(horizon, dict) else None
        scopes[label+'_observed_event_end_seconds'] = observed_end
    def wait_count(report, progress_key, reason):
        native = report['native']
        progress = native.get('progress', {})
        return progress[progress_key] if progress_key in progress else native.get('reason_attempts', {}).get(reason)

    fields = {
        'planned_persons': lambda r:r['planned']['planned_persons'],
        'observed_departures': lambda r:r['trips']['all_modes_departures'],
        'completed_legs': lambda r:r['event_counts']['completed_legs'],
        'pending_legs_at_horizon': lambda r:r['pending']['censored_legs_at_cut'],
        'active_vehicles_snapshot': lambda r:r['pending']['active_vehicles_snapshot'],
        'maximum_active_vehicles': lambda r:r['pending'].get('maximum_active_vehicles'),
        'aborted_before_horizon': lambda r:r['event_counts']['aborted_before_horizon'],
        'forced_storage_moves': lambda r:r['native']['forced_storage_moves'],
        'forced_per_1000_observed_departures': lambda r:r['native']['forced_per_1000_observed_departures'],
        'wait_storage_attempts': lambda r:wait_count(r, 'wait_storage', 'storage_wait'),
        'wait_congestion_attempts': lambda r:wait_count(r, 'wait_congestion', 'congestion_queue'),
        'completion_rate': lambda r:r['trips']['completion_rate'],
        'completed_mean_seconds': lambda r:r['trips']['durations_completed_only']['mean_seconds'],
        'completed_p50_seconds': lambda r:r['trips']['durations_completed_only']['p50_seconds'],
        'completed_p95_seconds': lambda r:r['trips']['durations_completed_only']['p95_seconds'],
    }
    comparisons = []
    for name, value in fields.items():
        old, new = value(historical), value(current)
        delta = new-old if comparable_horizons and new is not None and old is not None else None
        comparisons.append(dict(metric=name, historical=old, current=new, **scopes, delta=delta,
                                relative_change=ratio(delta, old) if delta is not None else None,
                                absolute_reduction=-delta if delta is not None else None,
                                relative_reduction=ratio(-delta, old) if delta is not None else None))
    differences = {}
    for key in set(current['effective_settings']) | set(historical['effective_settings']):
        old, new = historical['effective_settings'].get(key), current['effective_settings'].get(key)
        if old != new:
            differences[key] = dict(historical=old, current=new)
    return dict(current_run=current['run_id'], historical_run=historical['run_id'],
        current_directory=current['run_dir'], historical_directory=historical['run_dir'],
        current_horizon=current_horizon, historical_horizon=historical_horizon,
        current_observed_event_end_seconds=current_end, historical_observed_event_end_seconds=historical_end,
        comparable_horizons=comparable_horizons,
        metrics=comparisons, effective_setting_differences=differences,
        same_planned_person_count=current['planned']['planned_persons']==historical['planned']['planned_persons'],
        matching_input_hashes={key:current['input_hashes'].get(key)==historical['input_hashes'].get(key)
                              for key in sorted(set(current['input_hashes']) | set(historical['input_hashes']))},
        causal_effect_established=False,
        metric_semantics=dict(wait_storage_attempts='Native storage_wait decision attempts, not seconds or unique vehicles.',
            wait_congestion_attempts='Native queue observations; null means not instrumented in that run.',
            maximum_active_vehicles='Maximum observed native activeVehicles snapshot, not total unique vehicles.',
            horizon_comparability='Every current/historical column uses its labeled parent horizon and observed file end. '
                'Deltas/reductions are unavailable unless both configured windows and observed file ends are known and equal.',
            absolute_reduction='historical minus current; a descriptive difference, not an isolated treatment effect.',
            relative_reduction='(historical-current)/historical; undefined for a zero or missing historical value.'),
        limitation='Descriptive comparison of distinct runs and demand loads. Normalized counts do not isolate the effect of priority changes, and completed-only durations are affected by censoring.')


def plot_operations(report, intervals, hourly, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    hours = [row['hour'] for row in hourly]
    axes[0, 0].bar([hour-.2 for hour in hours], [row['departures_at_event_hour'] for row in hourly],
                   width=.4, label='Salidas')
    axes[0, 0].bar([hour+.2 for hour in hours], [row['arrivals_at_event_hour'] for row in hourly],
                   width=.4, label='Llegadas')
    axes[0, 0].set(title='Eventos por hora absoluta', ylabel='Etapas')
    axes[0, 0].legend()
    time = [row['time']/3600 for row in intervals]
    axes[0, 1].plot(time, [row['active_vehicles'] for row in intervals], color='#087eaa')
    axes[0, 1].set(title='Vehiculos dentro de la red: muestras nativas', ylabel='Vehiculos activos')
    for field, label in [('wait_signal','Senal'), ('wait_storage','Almacenamiento'),
                         ('wait_priority','Prioridad'), ('wait_congestion','Cola/congestion')]:
        known = [row for row in intervals if row[field] is not None and row['elapsed_sim_seconds'] > 0]
        if known:
            axes[1, 0].plot([row['time']/3600 for row in known],
                           [row[field]/row['elapsed_sim_seconds'] for row in known], label=label)
    axes[1, 0].set(title='Frecuencia de decisiones WAIT por intervalo', ylabel='Intentos / segundo simulado')
    axes[1, 0].legend()
    cumulative, values = 0, []
    for row in intervals:
        cumulative += row['forced_moves']
        values.append(cumulative)
    axes[1, 1].step(time, values, where='post', color='#af3939')
    axes[1, 1].set(title='Movimientos forzados acumulados', ylabel='Decisiones storage_forced_move')
    for axis in axes.flat:
        axis.set_xlabel('Hora absoluta simulada')
        axis.set_ylim(bottom=0)
        axis.grid(alpha=.2)
    counts = report['event_counts']
    fig.suptitle(f"{report['run_id']} / iteracion {report['iteration']}\n"
                 f"Completos={counts['completed_legs']}; pendientes al corte={counts['pending_legs_at_horizon']}; "
                 f"abortados antes del corte={counts['aborted_before_horizon']}")
    fig.text(.5, .01, 'WAIT cuenta intentos, no duraciones ni personas unicas. Activos en red y viajes pendientes son poblaciones distintas.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .035, 1, 1))
    fig.savefig(Path(destination)/'operational_timeline.png', dpi=160)
    plt.close(fig)


def plot_readable_hourly_profiles(report, destination):
    """Render all 24 cohorts with separate count rows, using exported quantiles."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    with (Path(destination)/'percentiles_profile_hour.csv').open(encoding='utf-8', newline='') as stream:
        summaries = list(csv.DictReader(stream))
    profiles = [row for row in summaries if row['view'] == 'profile']
    hourly = sorted((row for row in summaries if row['view'] == 'hour'), key=lambda row:int(row['hour']))
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={'width_ratios':[1, 1.7]})
    if profiles:
        boxes = []
        for row in profiles:
            quantiles = [float(row[key]) if row[key] else float('nan')
                         for key in ('p05_seconds','p25_seconds','p50_seconds','p75_seconds','p95_seconds')]
            boxes.append(dict(label=f"{row['profile']}\nN={row['n_complete']}; excl={row['n_excluded']}",
                              **dict(zip(('whislo','q1','med','q3','whishi'), quantiles))))
        axes[0].bxp(boxes, showfliers=False)
    else:
        axes[0].text(.5, .5, 'Sin completos', transform=axes[0].transAxes, ha='center')
    hours = [int(row['hour']) for row in hourly]
    def values(key):
        return [float(row[key]) if row[key] else float('nan') for row in hourly]
    axes[1].plot(hours, values('p50_seconds'), 'o-', label='p50')
    axes[1].fill_between(hours, values('p05_seconds'), values('p95_seconds'), alpha=.25, label='p05-p95')
    axes[1].set_xticks(hours, [f"{row['hour']}\n{row['n_complete']}\n{row['n_excluded']}" for row in hourly], fontsize=8)
    axes[1].legend()
    axes[1].grid(alpha=.2)
    axes[0].set(ylabel='Duracion completada (s)', title='Perfiles: caja p25-p75; bigotes p05-p95', ylim=(0,None))
    axes[1].set(ylabel='Duracion completada (s)', title='Distribucion por hora', ylim=(0,None),
                xlabel='Hora absoluta de salida\nFilas bajo cada hora: completos / excluidos del modo')
    trips = report['trips']
    fig.suptitle(f"{report['run_id']} / iteracion {report['iteration']} / modo={trips['mode']}\n"
                 f"N completos={trips['completed']}; excluidos={trips['all_modes_departures']-trips['completed']} "
                 f"(otro modo={trips['other_mode']})")
    fig.tight_layout()
    fig.savefig(Path(destination)/'profile_hour_distribution.png', dpi=160)
    plt.close(fig)


def export_report(selection, baseline=None, mode='car', plots=True):
    destination = selection['directory']/'analysis/prompt13'/f"it.{selection['iteration']}"
    destination.mkdir(parents=True, exist_ok=True)
    table, provenance = export_table(selection, destination/'individual_trips.csv.gz')
    report, intervals, hourly = collect_report(selection, table, mode)
    report['individual_table'] = dict(path=str(table), sha256=provenance['csv_sha256'],
                                      rows=report['trips']['all_modes_departures'], sampled=False)
    atomic_json(destination/'operational_report.json', report)
    csv_file(destination/'progress_intervals.csv', intervals, list(intervals[0]))
    csv_file(destination/'operational_hourly.csv', hourly, list(hourly[0]))
    if plots:
        from simz1_trip_distributions import plot_distributions
        plot_distributions(table, destination, f"{report['run_id']} / iteracion {report['iteration']}", mode)
        plot_readable_hourly_profiles(report, destination)
        plot_operations(report, intervals, hourly, destination)
    if baseline:
        historical, _, _ = collect_report(baseline, mode=mode)
        comparison = compare_reports(report, historical)
        atomic_json(destination/'historical_reference.json', historical)
        atomic_json(destination/'historical_comparison.json', comparison)
        csv_file(destination/'historical_comparison.csv', comparison['metrics'],
                 ['metric', 'historical', 'current',
                  'historical_configured_start_seconds', 'historical_configured_end_seconds', 'historical_observed_event_end_seconds',
                  'current_configured_start_seconds', 'current_configured_end_seconds', 'current_observed_event_end_seconds',
                  'delta', 'relative_change', 'absolute_reduction', 'relative_reduction'])
    return destination, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--iteration', type=int, default=0)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--baseline-iteration', type=int, default=0)
    parser.add_argument('--mode', default='car')
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args()
    try:
        selection = select_run(args.run_dir, args.iteration, require_events=False)
        baseline = select_run(args.baseline_dir, args.baseline_iteration, require_events=False) if args.baseline_dir else None
        destination, report = export_report(selection, baseline, args.mode, not args.no_plots)
        print(json.dumps(dict(destination=str(destination), trips=report['trips'],
                              pending=report['pending'], forced_moves=report['native']['forced_storage_moves']),
                         ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'No se pudo generar el informe operativo: {exc}\n')


if __name__ == '__main__':
    main()
