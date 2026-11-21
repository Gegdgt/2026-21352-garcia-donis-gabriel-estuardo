"""Temporal passage-credit fixtures; real HEAD and native link events retained."""
import copy
import unittest

from simz1_priority_audit import PriorityAudit


def policy(link, node, *, stop=True, eligible=True):
    return dict(type='simz1PriorityPolicy', time='0', node=node, link=link,
                enabled='true', eligible=str(eligible).lower(), controlled='false',
                role='street' if stop else 'avenue', control='stop' if stop else 'free',
                classificationSource='network_attribute', stopSeconds='5.0',
                appliedStopSeconds='5.0' if stop and eligible else '0.0', conflictPolicy='conservative')


def passage(action, time):
    return dict(type='simz1OccupancyPassage', action=action, time=str(time), vehicle='v',
                policy='corridor-length-v1', source='synchronous_QSim_corridor_ledger',
                positionsObserved='false', laneObserved='false', corridor='receiver', reservationOrdinal='7',
                passageKind='downstream_receipt', passageLinks='c,d', passageSlots='0,0', receiptLink='e',
                passageStopLinks='c,d', passageStopSeconds='5.0,0.0', lockedNodes='n0,cn,dn',
                passageHoldStartTime='10.0', passageAuthorizedTime='15.0', passageRequiredStopSeconds='5.0')


def decision(action, time, *, credited=True):
    event = dict(type='simz1Priority', action=action, time=str(time), node='cn', link='c', nextLink='d',
                 lane='c.0', person='p', vehicle='v', visit='1', role='street', control='stop',
                 classificationSource='network_attribute', stopSeconds='5.0', appliedStopSeconds='5.0',
                 conflictPolicy='conservative', headTime='20.0', readyTime='25.0',
                 reason=dict(HEAD='queue_head', GO='permission_not_crossing', CROSS='executed')[action])
    if credited and action != 'HEAD':
        data = passage('ACQUIRE', 15)
        event.update({field: value for field, value in data.items() if field.startswith('passage') or field in ('receiptLink',)})
        event.update(passageReservationOrdinal='7', passageCorridor='receiver', passageStopCreditSeconds='5.0')
    return event


def stream(*, credited=True, release_before_cross=True):
    cross_time = 20 if credited else 25
    rows = [policy('w', 'n0', stop=False, eligible=False), policy('c', 'cn'), policy('d', 'dn', stop=False),
            dict(type='simz1OccupancyPassageHold', time='10', vehicle='v', link='w', requestedLink='c',
                 source='native_admission_hold', positionsObserved='false', passageHoldStartTime='10.0',
                 passageRequiredStopSeconds='5.0', passageStopLinks='c,d', passageStopSeconds='5.0,0.0'),
            dict(type='left link', time='15', vehicle='v', link='w'),
            dict(type='entered link', time='15', vehicle='v', link='c'), passage('ACQUIRE', 15),
            decision('HEAD', 20), decision('GO', cross_time, credited=credited),
            dict(type='left link', time=str(cross_time), vehicle='v', link='c'),
            dict(type='entered link', time=str(cross_time), vehicle='v', link='d')]
    if release_before_cross:
        rows.append(passage('RELEASE', cross_time))
    rows.append(decision('CROSS', cross_time, credited=credited))
    if not release_before_cross:
        rows.append(passage('RELEASE', cross_time))
    return rows


class PriorityPassageTests(unittest.TestCase):
    def audit(self, rows):
        audit = PriorityAudit()
        for row in rows:
            audit.consume(row)
        return audit.summary()

    def test_verified_upstream_credit_keeps_real_head_and_ready_and_release_can_precede_cross(self):
        for release_before in (True, False):
            with self.subTest(release_before_cross=release_before):
                rows = stream(release_before_cross=release_before); original = copy.deepcopy(rows)
                result = self.audit(rows)
                self.assertEqual(result['executed_crossings'], 1)
                self.assertEqual(result['actions'], dict(HEAD=1, GO=1, CROSS=1))
                self.assertEqual(result['minimum_street_head_to_cross_seconds'], 0)
                self.assertEqual(result['pending_heads_at_cut'], 0)
                credit = result['passage_stop_credit']
                self.assertEqual(credit['counts']['prepaid_stop_crossings'], 1)
                self.assertEqual(credit['active_acquisitions'], 0)
                self.assertEqual(rows, original)

    def test_normal_stop_still_works_without_claiming_passage_credit(self):
        result = self.audit(stream(credited=False))
        self.assertEqual(result['minimum_street_head_to_cross_seconds'], 5)
        self.assertEqual(result['passage_stop_credit']['counts'].get('prepaid_stop_crossings', 0), 0)

    def test_missing_or_falsified_proof_cannot_short_circuit_stop(self):
        mutations = {
            'missing hold': lambda rows: [r for r in rows if r['type'] != 'simz1OccupancyPassageHold'],
            'missing acquire': lambda rows: [r for r in rows if not (r['type'] == 'simz1OccupancyPassage' and r['action'] == 'ACQUIRE')],
            'missing policy': lambda rows: [r for r in rows if not (r['type'] == 'simz1PriorityPolicy' and r['link'] == 'd')],
            'missing head': lambda rows: [r for r in rows if r.get('action') != 'HEAD'],
            'missing go': lambda rows: [r for r in rows if r.get('action') != 'GO'],
            'missing native leave': lambda rows: [r for r in rows if not (r['type'] == 'left link' and r['link'] == 'c')],
            'missing native enter': lambda rows: [r for r in rows if not (r['type'] == 'entered link' and r['link'] == 'd')],
            'missing cross': lambda rows: [r for r in rows if r.get('action') != 'CROSS'],
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.audit(mutation(stream()))
        for kind, action, field, value in [
            ('simz1OccupancyPassageHold', None, 'passageHoldStartTime', '9'),
            ('simz1OccupancyPassageHold', None, 'source', 'assumed'),
            ('simz1OccupancyPassageHold', None, 'requestedLink', 'wrong'),
            ('left link', None, 'time', '14'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'passageAuthorizedTime', '14'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'passageHoldStartTime', '11'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'passageRequiredStopSeconds', '0'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'passageStopSeconds', '0.0,0.0'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'lockedNodes', 'n0,dn'),
            ('simz1OccupancyPassage', 'ACQUIRE', 'source', 'assumed'),
            ('simz1Priority', 'GO', 'passageReservationOrdinal', '8'),
            ('simz1Priority', 'GO', 'passageCorridor', 'wrong'),
            ('simz1Priority', 'GO', 'passageStopCreditSeconds', '4'),
            ('simz1Priority', 'GO', 'passageLinks', 'c,wrong'),
            ('simz1Priority', 'GO', 'nextLink', 'wrong'),
            ('simz1Priority', 'GO', 'headTime', '19'),
            ('simz1Priority', 'GO', 'readyTime', '20'),
            ('simz1Priority', 'GO', 'passageAuthorizedTime', 'nan'),
            ('simz1Priority', 'CROSS', 'passageStopCreditSeconds', '0'),
        ]:
            with self.subTest(kind=kind, action=action, field=field), self.assertRaises(ValueError):
                rows = stream()
                target = next(r for r in rows if r['type'] == kind and (action is None or r.get('action') == action))
                target[field] = value
                self.audit(rows)

    def test_credit_does_not_authorize_go_after_release_or_cross_with_other_token(self):
        rows = stream(); release = next(r for r in rows if r.get('action') == 'RELEASE'); rows.remove(release)
        rows.insert(next(i for i, r in enumerate(rows) if r.get('action') == 'GO'), release)
        with self.assertRaisesRegex(ValueError, 'ACQUIRE y lock'):
            self.audit(rows)
        rows = stream(); cross = next(r for r in rows if r.get('action') == 'CROSS')
        for field in [key for key in cross if key.startswith('passage') or key == 'receiptLink']:
            del cross[field]
        with self.assertRaisesRegex(ValueError, 'CROSS omitio'):
            self.audit(rows)
        rows = stream(credited=False, release_before_cross=False)
        cross = next(r for r in rows if r.get('action') == 'CROSS')
        cross.update(decision('CROSS', 25, credited=True))
        with self.assertRaisesRegex(ValueError, 'CROSS agrego'):
            self.audit(rows)

    def test_duplicate_heads_and_double_cross_remain_invalid(self):
        rows = stream(); head_index = next(i for i, r in enumerate(rows) if r.get('action') == 'HEAD')
        rows.insert(head_index + 1, decision('HEAD', 20))
        with self.assertRaisesRegex(ValueError, 'cabecera reiniciada'):
            self.audit(rows)
        rows = stream(); rows.append(decision('CROSS', 20))
        with self.assertRaisesRegex(ValueError, 'cronometro o visita'):
            self.audit(rows)

    def test_native_activity_hold_and_same_link_lane_transfer_do_not_invent_future_head(self):
        rows = stream(); hold = next(r for r in rows if r['type'] == 'simz1OccupancyPassageHold'); hold['link'] = 'c'
        rows = [r for r in rows if not (r['type'] in ('left link', 'entered link') and r['time'] == '15')]
        acquire_index = next(i for i, r in enumerate(rows) if r.get('action') == 'ACQUIRE')
        rows[acquire_index:acquire_index] = [dict(type='entered lane', time='12', vehicle='v', link='c', lane='c.0'),
                                           dict(type='vehicle enters traffic', time='15', vehicle='v', link='c')]
        self.assertEqual(self.audit(rows)['executed_crossings'], 1)

    def test_total_stop_credit_pays_each_eligible_connector_before_authorization(self):
        for authorized, succeeds in ((20, True), (19, False)):
            with self.subTest(authorized=authorized):
                rows = stream()
                rows[2] = policy('d', 'dn')
                for row in rows:
                    if 'passageStopLinks' in row:
                        row.update(passageStopSeconds='5.0,5.0', passageRequiredStopSeconds='10.0')
                    if 'passageAuthorizedTime' in row:
                        row['passageAuthorizedTime'] = str(authorized)
                    if row.get('time') == '15':
                        row['time'] = str(authorized)
                    elif row.get('time') == '20':
                        row['time'] = '25'
                    if row['type'] == 'simz1Priority':
                        row.update(headTime='25.0', readyTime='30.0')
                if succeeds:
                    self.assertEqual(self.audit(rows)['executed_crossings'], 1)
                else:
                    with self.assertRaisesRegex(ValueError, 'antes de pagar todas las paradas'):
                        self.audit(rows)

    def test_ineligible_stop_policy_does_not_invent_prepaid_seconds(self):
        rows = stream()
        rows[2] = policy('d', 'dn', eligible=False)
        self.assertEqual(self.audit(rows)['executed_crossings'], 1)
        for row in rows:
            if 'passageStopLinks' in row:
                row.update(passageStopSeconds='5.0,5.0', passageRequiredStopSeconds='10.0')
        with self.assertRaisesRegex(ValueError, 'segundos difieren de politica de d'):
            self.audit(rows)

    def test_historical_passage_without_credit_keeps_ordinary_stop_requirement(self):
        rows = stream(credited=False)
        rows = [r for r in rows if r['type'] != 'simz1OccupancyPassageHold']
        for row in rows:
            if row['type'] == 'simz1OccupancyPassage':
                for field in list(row):
                    if field in ('passageHoldStartTime', 'passageAuthorizedTime', 'passageRequiredStopSeconds', 'passageStopLinks', 'passageStopSeconds'):
                        del row[field]
        self.assertEqual(self.audit(rows)['executed_crossings'], 1)
        next(r for r in rows if r.get('action') == 'GO')['time'] = '20'
        with self.assertRaisesRegex(ValueError, 'parada minima omitida'):
            self.audit(rows)


if __name__ == '__main__':
    unittest.main()
