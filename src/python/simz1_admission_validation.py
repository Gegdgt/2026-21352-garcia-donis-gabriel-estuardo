"""Audit explicit SimZ1 admission evidence; never reinterpret historical FORCE.

turn_go is a turn permission. Only the separate post-insertion simz1Admission
receipt confirms receiver admission; neither measures continuous body spacing.
"""
from collections import Counter
import math


POLICIES = {'matsim15-native', 'strict-receiver-v1'}


class AdmissionAudit:
    def __init__(self, expected_policy=None):
        if expected_policy is not None and expected_policy not in POLICIES:
            raise ValueError('Politica de admision esperada desconocida')
        self.expected_policy = expected_policy
        self.policies = Counter()
        self.commits = 0
        self.conflict_waits = 0
        self.timeout_waits = 0

    def consume(self, event):
        kind = event.get('type')
        if kind not in ('simz1NativeDecision', 'simz1Admission'):
            return
        policy = event.get('admissionPolicy')
        if policy is None:
            if self.expected_policy == 'strict-receiver-v1' or kind == 'simz1Admission':
                raise ValueError('Decision sin evidencia de la politica estricta esperada')
            self.policies['legacy_unattributed'] += 1
            return
        if policy not in POLICIES or event.get('admissionPolicyVersion') != '1':
            raise ValueError('Politica/version de admision desconocida')
        if self.expected_policy is not None and policy != self.expected_policy:
            raise ValueError('Politica de admision difiere de la configuracion efectiva')
        if kind == 'simz1Admission':
            try:
                time = float(event.get('time'))
                if not math.isfinite(time) or time < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('Instante de admision invalido') from None
            if (policy != 'strict-receiver-v1' or event.get('decision') != 'GO' or
                    event.get('reason') != 'receiver_accepted' or event.get('receiverAcceptedAtDecision') != 'true' or
                    any(not event.get(key) for key in ('vehicle','person','link','nextLink','lane','receivingLane','node'))):
                raise ValueError('Comprobante de admision sin receptor aceptado o identidad completa')
            self.commits += 1
            return
        self.policies[policy] += 1
        reason, decision = event.get('reason'), event.get('decision')
        if policy == 'strict-receiver-v1':
            if decision == 'FORCE' or reason == 'storage_stuck_removal':
                raise ValueError('FORCE/remocion de almacenamiento incompatible con admision estricta')
            if reason == 'storage_wait':
                if decision != 'WAIT' or event.get('receiverAcceptedAtDecision') != 'false':
                    raise ValueError('WAIT estricto sin rechazo receptor observado')
                try:
                    wait, stuck = float(event.get('waitSeconds')), float(event.get('stuckTime'))
                    if not all(math.isfinite(v) and v >= 0 for v in (wait, stuck)):
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError('Reloj de almacenamiento estricto invalido') from None
                exceeded = wait > stuck
                if event.get('storageTimeoutExceeded') != str(exceeded).lower():
                    raise ValueError('Indicador de timeout no coincide con el reloj nativo')
                self.timeout_waits += exceeded
            if reason == 'admission_conflict_executed':
                if decision != 'WAIT' or event.get('waitCategory') != 'yield':
                    raise ValueError('Conflicto de admision no conservado como WAIT')
                self.conflict_waits += 1

    def summary(self):
        return dict(expected_policy=self.expected_policy, native_decisions_by_policy=dict(self.policies),
                    confirmed_receiver_admissions=self.commits,
                    conflict_wait_attempts=self.conflict_waits, storage_waits_beyond_stuck_time=self.timeout_waits,
                    physical_spacing_proven=False,
                    note='turn_go is permission only; simz1Admission is emitted after insertion. '
                         'Neither proves continuous body spacing or network-wide freedom from gridlock.')
