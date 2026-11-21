"""Streaming storage-branch evidence. Counts are attempts, never unique trips.

Snapshot correlations identify candidates for inspection, not root causes. Old
events remain readable and explicitly lack receiver measurements. Only native
decision events count: priority CROSS and progress totals must not count again.
"""
from collections import Counter, defaultdict
import math


STORAGE_DECISIONS = {'storage_wait': 'WAIT', 'storage_forced_move': 'FORCE',
                     'storage_stuck_removal': 'ABORT'}


class StorageAudit:
    def __init__(self):
        self.counts = Counter()
        self.vehicles = defaultdict(set)
        self.missing_vehicle = Counter()
        self.movements = defaultdict(Counter)
        self.hours = defaultdict(Counter)
        self.coverage = Counter()
        self.snapshots = defaultdict(Counter)

    def consume(self, event):
        reason = event.get('reason')
        if event.get('type') != 'simz1NativeDecision' or reason not in STORAGE_DECISIONS:
            return
        if event.get('decision') != STORAGE_DECISIONS[reason]:
            raise ValueError('Decision incompatible con rama de almacenamiento: '+str(dict(event.attrib)))
        self.counts[reason] += 1
        intervention = reason != 'storage_wait'
        if intervention:
            vehicle = event.get('vehicle')
            if vehicle:
                self.vehicles[reason].add(vehicle)
            else:
                self.missing_vehicle[reason] += 1
            time = event.get('time')
            if time is not None and math.isfinite(float(time)):
                self.hours[int(float(time)//3600)][reason] += 1
        key = tuple(event.get(k, '') for k in ('link', 'lane', 'nextLink', 'receivingLane'))
        self.movements[key][reason] += 1
        version = event.get('storageObservationVersion')
        if version is None:
            self.coverage['legacy_events_without_receiver_observation'] += 1
            return
        if version not in ('1', '2') or event.get('receiverAcceptedAtDecision') != 'false' or not key[3]:
            raise ValueError('Observacion de receptor invalida: '+str(dict(event.attrib)))
        self.coverage['events_with_receiver_rejection'] += 1
        snapshot = event.get('storageSnapshot')
        if snapshot == 'not_sampled' and not intervention:
            return
        if snapshot != ('intervention' if intervention else 'sampled_wait'):
            raise ValueError('Muestreo de almacenamiento invalido: '+str(snapshot))
        def number(name):
            try:
                value = float(event.get(name))
                if not math.isfinite(value) or value < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('Medicion de almacenamiento invalida: '+name) from None
            return value
        load = number('receivingLoadIndicator')
        capacity = number('receivingStorageCapacityPcu')
        number('receivingFlowCapacityPcuPerStep')
        number('vehicleSizePcu')
        queues = number('receiverExitQueues')
        rejecting = number('receiverExitQueuesRejecting')
        offering = number('receiverExitQueuesOffering')
        head_observation = event.get('receiverExitHeadObservation')
        if version == '2' and head_observation not in ('observed_serial', 'unavailable_parallel_qsim', 'unavailable_head'):
            raise ValueError('Disponibilidad de cabecera del receptor invalida')
        unavailable = version == '2' and head_observation != 'observed_serial'
        if unavailable and event.get('receiverExitHeadsSignalBlocked') != 'unknown':
            raise ValueError('Cabecera no disponible no permite inferir bloqueo por senal')
        blocked = None if unavailable else number('receiverExitHeadsSignalBlocked')
        if not (offering <= queues and rejecting <= queues and (blocked is None or blocked <= offering)):
            raise ValueError('Conteos de salidas del receptor incompatibles')
        # Check the actual native strict timeout, not time spent in storage_wait.
        if intervention:
            if number('waitSeconds') <= number('stuckTime'):
                raise ValueError('Intervencion sin superar stuckTime')
            expected = 'true' if reason == 'storage_stuck_removal' else 'false'
            if event.get('removeStuckVehicles') != expected:
                raise ValueError('Intervencion incompatible con removeStuckVehicles')
        self.coverage[snapshot+'_snapshots'] += 1
        observations = self.snapshots[reason]
        observations['snapshots'] += 1
        if event.get('receivingLoadSemantics') == 'pcu_excluding_buffer':
            observations['receiver_at_or_above_storage_threshold' if load >= capacity
                         else 'receiver_below_storage_threshold'] += 1
        else:
            observations['receiver_load_semantics_unspecified'] += 1
        if rejecting:
            observations['receiver_has_rejecting_exit_queue'] += 1
        if unavailable:
            self.coverage[head_observation] += 1
            observations['receiver_exit_head_signal_unavailable'] += 1
        elif blocked:
            observations['receiver_has_signal_blocked_exit_head'] += 1
        self.movements[key]['snapshots'] += 1

    def summary(self):
        def unique(reason):
            return None if self.missing_vehicle[reason] else len(self.vehicles[reason])
        interventions = ('storage_forced_move', 'storage_stuck_removal')
        ranked = sorted(self.movements.items(), key=lambda row: (
            -sum(row[1][r] for r in interventions), -row[1]['storage_wait'], row[0]))
        return dict(
            counts={r: self.counts[r] for r in STORAGE_DECISIONS},
            unique_intervention_vehicles={r: unique(r) for r in interventions},
            unique_vehicles_any_intervention=(None if sum(self.missing_vehicle.values()) else
                len(set().union(*(self.vehicles[r] for r in interventions)))),
            interventions_missing_vehicle_id=dict(self.missing_vehicle),
            coverage=dict(self.coverage),
            snapshots_by_branch={r: dict(c) for r, c in sorted(self.snapshots.items())},
            movement_count=len(self.movements),
            top_movements=[dict(zip(('link', 'lane', 'next_link', 'receiving_lane'), key), **counts)
                           for key, counts in ranked[:20]],
            interventions_by_hour=[dict(hour=h, **counts) for h, counts in sorted(self.hours.items())],
            scope=['Decision attempts; unique vehicle IDs are per iteration, not unique people or trips.',
                   'Top movements rank interventions, then waits; no road capacity is changed.',
                   'Snapshot every intervention; WAIT at most once per receiver per 60 simulated seconds.',
                   'Receiver readings are non-atomic and exclude the separate QueueWithBuffer buffer.',
                   'Version 2 reports receiver head signal evidence as unknown during parallel QSim; it is not zero or a blocking cause.',
                   'Exit pressure and signal correlation do not establish a root cause.',
                   'Head clock may include earlier red/priority waits; it is not consecutive storage-wait duration.',
                   'Legacy events have no receiving-queue measurements; missing evidence is not zero occupancy.'])
