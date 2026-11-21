"""Interpretation gates, separate from MATSim file integrity. No result imputation."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

PROFILES = ('Normal', 'Tortuga', 'Liebre', 'Motociclista', 'MotocicletaLenta', 'MotocicletaRapida')
DEFAULT_MIN_COMPLETION = .90  # Explicit project screening target, NOT empirical calibration.


def assess(report: dict, minimum: float = DEFAULT_MIN_COMPLETION, require_six: bool = False) -> dict:
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError('minimum debe estar entre 0 y 1')
    counts = report.get('counts', {})
    total = counts.get('selected_rows', 0)
    complete, aborted, censored = (counts.get(k, 0) for k in ('completed','aborted','censored'))
    if any(type(v) is not int or v < 0 for v in (total,complete,aborted,censored)):
        raise ValueError('Conteos invalidos en resumen de perfiles')
    if total != complete + aborted + censored:
        raise ValueError('El balance de etapas seleccionadas no cierra')
    by_profile = {p['profile']: p.get('n_total', 0) for p in report.get('profiles', [])}
    missing = [p for p in PROFILES if by_profile.get(p, 0) == 0]
    rate = complete/total if total else None
    observed = report.get('provenance', {}).get('table', {}).get('observed', {})
    anomalies = observed.get('anomalies', {})
    # Legacy "duplicates" may be a valid PersonStuck + VehicleAborts pair. Do not
    # retroactively relabel them without an independently validated event stream.
    unresolved = {k: v for k, v in anomalies.items() if v and
                  k in ('unmapped_vehicle_abort','abort_after_arrival','arrival_after_abort',
                        'unmatched_arrivals','unmatched_abort','duplicate_terminal_events')}
    mix = report.get('provenance', {}).get('demand_composition') or {}
    configured = report.get('provenance', {}).get('population_counts') or {}
    empty_private = (mix.get('schema_version') == 'simz1-nonpublic-composition-v1' and
                     mix.get('total_non_public_vehicles') == 0 and mix.get('private_vehicles') == 0 and
                     configured.get('planned_persons') == 0 and total == 0)
    reasons = []
    freight = report.get('provenance', {}).get('freight_transport_observed', {}) or {}
    day = report.get('provenance', {}).get('day_observation') or {}
    fixed_day = day.get('policy') == 'fixed-day-24h-v1'
    # Persist the same fixed-day profile guard used by the normal launcher,
    # so plot/replay artifacts cannot silently downgrade its screening result.
    require_six=require_six or fixed_day and configured.get('planned_persons',0)>=6
    private_groups=[r for r in day.get('groups',[]) if r.get('family') in ('carro','moto')]
    scheduled_private=sum(r.get('scheduled_requests',0) for r in private_groups)
    completed_private=sum(r.get('completed',0) for r in private_groups)
    scheduled_private_rate=completed_private/scheduled_private if scheduled_private else None
    if fixed_day and scheduled_private and scheduled_private_rate<minimum:
        reasons.append('scheduled_private_completion_below_declared_target')
    if fixed_day and day.get('pending_classifications', {}).get('prolonged_traffic_review_required', 0):
        reasons.append('private_pending_traffic_exceeds_3600_seconds_at_cut')
    if fixed_day and day.get('counts',{}).get('exited_without_arrival',0):
        reasons.append('traffic_exit_without_arrival_requires_review')
    from simz1_freight_completion import EXPERIMENTAL_POLICIES
    if freight.get('completion_policy') in EXPERIMENTAL_POLICIES:
        if freight.get('experimental_acceptance') != 'satisfied' and not (
                fixed_day and freight.get('experimental_acceptance') == 'not_evaluable'):
            reasons.append('freight_completion_tolerance_not_satisfied')
    if not empty_private and (rate is None or rate < minimum):
        reasons.append('completion_below_declared_target')
    if unresolved:
        reasons.append('terminal_events_need_reconciliation')
    if require_six and missing and not empty_private:
        reasons.append('required_profiles_missing')
    zero_completion_hours = [r['hour'] for r in report.get('family_hour', [])
                             if r.get('family') == 'Carro' and r.get('n_total', 0) > 0
                             and r.get('n_complete') == 0]
    return dict(schema_version=1, run_id=report.get('run_id'), iteration=report.get('iteration'),
        status=('review_required' if reasons else 'not_applicable_no_private_demand' if empty_private else 'screening_pass'), reasons=reasons,
        completion_rate=rate, censored_rate=censored/total if total else None,
        freight_completion_policy=freight.get('completion_policy'),
        freight_experimental_acceptance=freight.get('experimental_acceptance'),
        freight_completion_classifications=freight.get('completion_classifications'),
        day_observation=day or None,
        execution=day.get('execution'), technical_integrity=day.get('technical_integrity'),
        day_coverage_end_seconds=day.get('coverage_end_seconds'),
        scheduled_trips_completion_rate=day.get('completion_rate'),
        scheduled_trips_denominator=day.get('scheduled_trips'),
        scheduled_private_trips_denominator=scheduled_private if fixed_day else None,
        scheduled_private_completion_rate=scheduled_private_rate,
        selected_rows=total, completed=complete, aborted=aborted, censored=censored,
        declared_min_completion_rate=minimum, require_six_profiles=require_six,
        threshold_basis='Project screening target; not a legal/empirical validity criterion',
        missing_profiles=missing, observed_profile_counts=by_profile,
        unresolved_terminal_counts=unresolved,
        terminal_reconciliation_version=observed.get('terminal_reconciliation_version'),
        terminal_reconciliation=observed.get('terminal_reconciliation'),
        censoring_breakdown=observed.get('censoring_breakdown'),
        car_departure_hours_without_arrivals=zero_completion_hours,
        duration_scope='Conditional on a valid observed arrival; NOT the mean of all generated trips',
        interpretation='Censored means no arrival in the observation window. It is not a zero duration, '
            'a proven crash, or proof that every vehicle was circulating. Low afternoon means may '
            'reflect selective completion. A faster configured vehicle need not have a lower unconditional mean.',
        physics_changed=False, empirical_calibration=False,
        policy_warning='Strict receiver admission can retain queues instead of forcing/removing vehicles; '
            'this report does not prove gridlock or identify a saturated link without event evidence.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--min-completion-rate', type=float, default=DEFAULT_MIN_COMPLETION)
    parser.add_argument('--require-six-profiles', action='store_true')
    parser.add_argument('--check', action='store_true', help='Codigo 3 si requiere revision; no cambia MATSim')
    args = parser.parse_args()
    try:
        report = assess(json.loads(args.summary.read_text(encoding='utf-8')),
                        args.min_completion_rate, args.require_six_profiles)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 3 if args.check and report['status'] not in ('screening_pass', 'not_applicable_no_private_demand') else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'No se pudo evaluar calidad: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
