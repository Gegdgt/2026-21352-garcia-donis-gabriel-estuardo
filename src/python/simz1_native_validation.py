"""Interpret native QSim decisions without confusing traffic waits and failures."""
from collections import Counter, defaultdict
import json
import math
from simz1_storage_diagnostics import StorageAudit
from simz1_admission_validation import AdmissionAudit


STORAGE_WAIT_REASONS = frozenset((
    'receiver_native_storage', 'receiver_storage_or_terminal_slot',
    'passage_receipt_storage_or_slot', 'passage_receipt_native_queue', 'passage_native_storage',
    'passage_receipt_locked', 'passage_previous_not_cleared'))
WAIT_CATEGORIES = frozenset(('mandatory_stop', 'yield', 'signal', 'insufficient_storage',
                             'congestion', 'turn_restriction', 'none'))


def native_wait_category(reason):
    """Version 2 raw-reason classification; no inference of movement or duration."""
    reason = reason or ''
    if reason == 'priority_stop': return 'mandatory_stop'
    if reason.startswith('priority_') or reason in ('intersection_conflict', 'admission_conflict_executed'):
        return 'yield'
    if reason.startswith('signal_'): return 'signal'
    if reason.startswith('storage_') or reason in STORAGE_WAIT_REASONS: return 'insufficient_storage'
    if reason.startswith('congestion_'): return 'congestion'
    if reason == 'turn_restriction' or reason.startswith('turn_abort_'): return 'turn_restriction'
    if reason in ('turn_go', 'receiver_accepted'): return 'none'
    return 'unknown'


def checked_wait_category(event):
    """Preserve historical observations; unknown is explicit only in version 2."""
    category, version = event.get('waitCategory'), event.get('waitCategoryVersion')
    if version not in (None, '2'):
        raise ValueError('Version de categoria de espera nativa desconocida: '+str(version))
    if version == '2':
        if event.get('attemptUnit') != 'native_decision_event':
            raise ValueError('Unidad de intento nativo version 2 ausente o incompatible')
        if category != native_wait_category(event.get('reason')):
            raise ValueError('Categoria de espera nativa incompatible con reason version 2: '+str(category))
    elif category is not None and category not in WAIT_CATEGORIES:
        raise ValueError('Categoria de espera nativa desconocida: '+str(category))
    return category


class NativeDecisionAudit:
    def __init__(self, expected_admission_policy=None):
        self.reasons = Counter()
        self.wait_categories = Counter()
        self.wait_attempts_v2 = Counter()
        self.wait_vehicles_v2 = defaultdict(set)
        self.wait_missing_vehicle_v2 = Counter()
        self.wait_age_maximum_v2 = {}
        self.wait_age_missing_v2 = Counter()
        self.abort_categories_v2 = Counter()
        self.category_v2_events = 0
        self.progress_samples = 0
        self.progress = dict(process_cpu_nanos=0, cpu_timed_samples=0, wall_nanos=0,
                             elapsed_sim_seconds=0., max_simulated_time=None, max_step_count=0,
                             link_transitions=0, arrivals=0, reroute_calculations=0,
                             wait_signal=0, wait_storage=0, wait_priority=0, wait_congestion=0,
                             turn_restrictions=0, forced_moves=0, storage_stuck_removals=0,
                             max_active_vehicles=0, max_thread_deadlocks=0)
        self.classifications = Counter()
        self.storage = StorageAudit()
        self.admission = AdmissionAudit(expected_admission_policy)

    def record_progress(self, event):
        def invalid(reason):
            raise ValueError('Metricas de avance nativo invalidas: '+json.dumps(
                dict(reason=reason, event=dict(event.attrib)), ensure_ascii=False))
        def number(key, floating=False, minimum=0):
            try:
                value = float(event.get(key)) if floating else int(event.get(key))
                if not math.isfinite(value) or value < minimum:
                    raise ValueError()
            except (TypeError, ValueError):
                invalid(f'{key} fuera de rango')
            return value
        counters = {key:number(key) for key in ('wallNanos', 'linkTransitions', 'arrivals',
                    'rerouteCalculations', 'waitSignal', 'waitStorage', 'waitPriority', 'forcedMoves',
                    'activeVehicles', 'threadDeadlocks', 'stepCount')}
        cpu = number('processCpuNanos', minimum=-1)
        # Older event files do not include the queue and restriction observations.
        for key in ('waitCongestion', 'turnRestrictions', 'storageStuckRemovals'):
            counters[key] = number(key) if event.get(key) is not None else 0
        elapsed, time = number('elapsedSimSeconds', True), number('time', True)
        classification = event.get('classification')
        if not classification:
            invalid('classification ausente')
        if 'deadlock' in classification and not counters['threadDeadlocks']:
            invalid('diagnostico de deadlock sin evidencia de hilos bloqueados')
        self.progress_samples += 1
        for source, target in (('wallNanos', 'wall_nanos'), ('linkTransitions', 'link_transitions'),
                ('arrivals', 'arrivals'), ('rerouteCalculations', 'reroute_calculations'),
                ('waitSignal', 'wait_signal'), ('waitStorage', 'wait_storage'),
                ('waitPriority', 'wait_priority'), ('waitCongestion', 'wait_congestion'),
                ('turnRestrictions', 'turn_restrictions'), ('forcedMoves', 'forced_moves'),
                ('storageStuckRemovals', 'storage_stuck_removals')):
            self.progress[target] = self.progress.get(target, 0) + counters[source]
        self.progress['elapsed_sim_seconds'] += elapsed
        if cpu >= 0:
            self.progress['process_cpu_nanos'] += cpu
            self.progress['cpu_timed_samples'] += 1
        for source, target in (('stepCount', 'max_step_count'), ('activeVehicles', 'max_active_vehicles'),
                               ('threadDeadlocks', 'max_thread_deadlocks')):
            self.progress[target] = max(self.progress[target], counters[source])
        self.progress['max_simulated_time'] = max(time, self.progress['max_simulated_time'] or 0)
        self.classifications[classification] += 1

    def consume(self, event):
        self.admission.consume(event)
        if event.get('type') == 'simz1Progress':
            self.record_progress(event)
        if event.get('type') != 'simz1NativeDecision':
            return
        reason = event.get('reason')
        if not reason:
            raise ValueError('Decision nativa sin reason: '+json.dumps(dict(event.attrib)))
        self.reasons[reason] += 1
        self.storage.consume(event)
        category = checked_wait_category(event)
        if category is not None:
            version2 = event.get('waitCategoryVersion') == '2'
            if version2: self.category_v2_events += 1
            if event.get('decision') == 'WAIT' or not version2 and event.get('decision') == 'ABORT':
                self.wait_categories[category] += 1
            if version2 and event.get('decision') == 'ABORT':
                self.abort_categories_v2[category] += 1
            if version2 and event.get('decision') == 'WAIT':
                self.wait_attempts_v2[category] += 1
                vehicle = event.get('vehicle')
                if vehicle: self.wait_vehicles_v2[category].add(vehicle)
                else: self.wait_missing_vehicle_v2[category] += 1
                age = event.get('waitSeconds')
                if age is None:
                    self.wait_age_missing_v2[category] += 1
                else:
                    try:
                        age = float(age)
                        if not math.isfinite(age) or age < 0 or event.get('waitSecondsBasis') not in (
                                'age_since_earliest_link_exit_not_sum_of_wait_attempts',
                                'head_age_since_last_movement_not_reason_duration'):
                            raise ValueError()
                    except (TypeError, ValueError):
                        raise ValueError('Edad observada de espera nativa version 2 invalida') from None
                    self.wait_age_maximum_v2[category] = max(age, self.wait_age_maximum_v2.get(category, 0))
        if reason.startswith('turn_abort_') or reason == 'turn_restriction':
            raise ValueError('ABORT nativo por ruta invalida, distinto de WAIT por rojo: '+
                             json.dumps(dict(event.attrib), ensure_ascii=False))
        if reason in ('turn_go', 'storage_forced_move') and event.get('signalState', '').upper() in (
                'RED', 'REDYELLOW', 'RED_YELLOW'):
            raise ValueError('Movimiento con senal nativa que no permite paso: '+
                             json.dumps(dict(event.attrib), ensure_ascii=False))
        if reason in ('turn_go', 'storage_forced_move') and event.get('nativeHasGreen') == 'false':
            raise ValueError('Movimiento sin permiso verde de la cola nativa: '+
                             json.dumps(dict(event.attrib), ensure_ascii=False))
        # MATSim 15 DefaultSignalizeableItem.checkGreen also permits YELLOW and
        # OFF. Preserve native amber clearance; the queue permission is decisive.

    def summary(self):
        interventions = self.reasons['storage_forced_move'] + self.reasons['storage_stuck_removal']
        return dict(decisions=sum(self.reasons.values()), reasons=dict(sorted(self.reasons.items())),
                    wait_categories=dict(sorted(self.wait_categories.items())),
                    wait_categories_basis='historical_WAIT_or_ABORT;version2_WAIT_only',
                    wait_observation_v2=dict(
                        coverage='observed' if self.category_v2_events else 'not_instrumented',
                        native_decision_events_with_version2=self.category_v2_events,
                        attempt_unit='native_decision_WAIT_events',
                        attempts_by_category=dict(sorted(self.wait_attempts_v2.items())),
                        distinct_vehicles_by_category={k:len(v) for k,v in sorted(self.wait_vehicles_v2.items())},
                        distinct_vehicles=len(set().union(*self.wait_vehicles_v2.values())),
                        attempts_without_vehicle_by_category=dict(sorted(self.wait_missing_vehicle_v2.items())),
                        maximum_observed_age_seconds_by_category=dict(sorted(self.wait_age_maximum_v2.items())),
                        attempts_without_age_by_category=dict(sorted(self.wait_age_missing_v2.items())),
                        age_basis='maximum_native_head_age_gauge_not_summed_attempts_or_reason_duration',
                        abort_events_by_category=dict(sorted(self.abort_categories_v2.items()))),
                    progress_samples=self.progress_samples,
                    progress=dict(self.progress, classifications=dict(sorted(self.classifications.items()))),
                    forced_storage_moves=self.reasons['storage_forced_move'],
                    storage_stuck_removals=self.reasons['storage_stuck_removal'],
                    storage_diagnostics=self.storage.summary(),
                    admission_diagnostics=self.admission.summary(),
                    physical_stability=dict(status='not_demonstrated' if interventions else
                                            'no_interventions_observed' if self.reasons else 'not_instrumented',
                                            proven=False,
                                            note='Una corrida finalizada o ausencia de intervenciones observadas '
                                                 'no acredita estabilidad fisica de otras cargas o escenarios'))
