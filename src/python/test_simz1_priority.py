from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ejecutar_simz1 import main
from generate_montecarlo_z1 import generar, SCENARIO
from simz1_config_validation import ConfigurationError
from simz1_priority_audit import PriorityAudit
from simz1_run import load_manifest, parameters, sha256


def policy():
    return dict(type='simz1PriorityPolicy', time='0', node='n', link='w', enabled='true', eligible='true',
                controlled='false', role='street', classificationSource='network_attribute', stopSeconds='5.0', conflictPolicy='conservative')


def decision(action, time, reason=None):
    return dict(type='simz1Priority', time=str(time), node='n', link='w', nextLink='e', lane='w.1',
                person='p', vehicle='v', visit='1', role='street', classificationSource='network_attribute',
                headTime='10.0', readyTime='15.0', stopSeconds='5.0', conflictPolicy='conservative', action=action,
                reason=reason or dict(HEAD='queue_head', WAIT='priority_stop', GO='permission_not_crossing', CROSS='executed')[action])


class PriorityTests(unittest.TestCase):
    def test_options_preserved_and_cli_propagates_without_changing_demand(self):
        with tempfile.TemporaryDirectory() as folder:
            original = sha256(SCENARIO/'config-simz1.xml')
            first, second = Path(folder)/'priority on', Path(folder)/'priority off'
            generar(SCENARIO/'config-simz1.xml',first,19,agents=1,corridor_policy='redistribute')
            argv = ['ejecutar_simz1.py','--seed','19','--agents','1','--corridor-policy','redistribute',
                    '--iterations','2','--run-dir',str(second),'--no-unsignalized-priority',
                    '--priority-stop-seconds','7.5','--priority-classification','orientation',
                    '--priority-conflicts','verified-node-table','--priority-max-yield-seconds','12']
            with patch('sys.argv',argv),patch('ejecutar_simz1.ejecutar') as execute:
                main()
            self.assertEqual(execute.call_args.args[-1],2)
            values = parameters(second/'config-simz1.xml')
            self.assertEqual(values['zona1Priority.enabled'],'false')
            self.assertEqual(values['zona1Priority.stopSeconds'],'7.5')
            self.assertEqual(values['zona1Priority.classification'],'orientation')
            self.assertEqual(values['zona1Priority.conflicts'],'verified-node-table')
            self.assertEqual(float(values['zona1Priority.maxYieldSeconds']),12)
            self.assertEqual(sha256(first/'plans.xml'),sha256(second/'plans.xml'))
            self.assertEqual(original,sha256(SCENARIO/'config-simz1.xml'))
            state=load_manifest(second)
            self.assertEqual(state['configuration_validation']['unsignalized_priority']['stop_seconds'],7.5)
            self.assertTrue(any(c['parameter']=='zona1Priority.enabled' and c['after']=='false' for c in state['configuration_overrides']))

    def test_invalid_options_fail_before_creating_run(self):
        with tempfile.TemporaryDirectory() as folder:
            for option in (dict(priority_stop_seconds=-1),dict(priority_stop_seconds=float('nan')),
                           dict(priority_stop_seconds=float('inf')),dict(priority_classification='guess'),
                           dict(priority_conflicts='ignore-conflicts'),dict(priority_max_yield_seconds=-1),
                           dict(priority_max_yield_seconds=float('nan'))):
                directory=Path(folder)/'rejected'
                with self.assertRaises(ConfigurationError):
                    generar(SCENARIO/'config-simz1.xml',directory,1,agents=1,corridor_policy='redistribute',**option)
                self.assertFalse(directory.exists())

    def test_wait_storage_is_not_crossing_or_restarted_stop(self):
        audit=PriorityAudit()
        for event in (policy(),decision('HEAD',10),decision('WAIT',11),decision('GO',15),
                      decision('WAIT',15,'storage_wait'),decision('GO',20)):
            audit.consume(event)
        self.assertEqual(audit.summary()['executed_crossings'],0)
        for kind,link in [('left link','w'),('entered link','e')]:
            audit.consume(dict(type=kind,time='20',vehicle='v',link=link))
        audit.consume(decision('CROSS',20))
        result=audit.summary()
        self.assertEqual(result['minimum_street_head_to_cross_seconds'],10)
        self.assertEqual(result['pending_heads_at_cut'],0)
        self.assertEqual(result['decision_reasons']['storage_wait'],1)

    def test_early_cross_missing_actual_events_clock_reset_and_exclusion_fail(self):
        for variant in ('early','no events','reset','signal','unregistered','changed clock','duplicate cross'):
            audit=PriorityAudit(); record=policy()
            if variant=='signal':record['controlled']='true'
            with self.subTest(variant=variant),self.assertRaises(ValueError):
                if variant!='unregistered':audit.consume(record)
                audit.consume(decision('HEAD',10))
                if variant=='reset':audit.consume(decision('HEAD',11))
                if variant=='changed clock':
                    event=decision('GO',16);event.update(headTime='11.0',readyTime='16.0');audit.consume(event)
                audit.consume(decision('GO',14 if variant=='early' else 15))
                if variant=='duplicate cross':
                    for kind,link in [('left link','w'),('entered link','e')]:audit.consume(dict(type=kind,time='15',vehicle='v',link=link))
                    audit.consume(decision('CROSS',15))
                audit.consume(decision('CROSS',15))

    def test_pending_and_legacy_are_not_fabricated_crossings(self):
        audit=PriorityAudit()
        self.assertEqual(audit.summary()['status'],'not_instrumented')
        audit.consume(policy());audit.consume(decision('HEAD',10));audit.consume(decision('WAIT',11))
        result=audit.summary()
        self.assertEqual(result['executed_crossings'],0)
        self.assertEqual(result['pending_heads_at_cut'],1)
        self.assertIsNone(result['minimum_street_head_to_cross_seconds'])

    def test_missing_cross_callback_or_missing_head_rejected(self):
        for missing in ('HEAD','CROSS'):
            audit=PriorityAudit();audit.consume(policy())
            if missing=='CROSS':audit.consume(decision('HEAD',10));audit.consume(decision('GO',15))
            with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'sin cabecera|sin CROSS'):
                for kind,link in [('left link','w'),('entered link','e')]:audit.consume(dict(type=kind,time='15',vehicle='v',link=link))
                audit.summary()

    def test_repeat_visits_use_new_clock_and_iteration_uses_new_audit(self):
        for iteration in (0,1):
            audit=PriorityAudit();audit.consume(policy())
            for visit,start in [(1,10),(2,30)]:
                for action,delta in [('HEAD',0),('GO',5),('CROSS',5)]:
                    event=decision(action,start+delta);event.update(visit=str(visit),headTime=str(float(start)),readyTime=str(float(start+5)))
                    if action=='CROSS':
                        for kind,link in [('left link','w'),('entered link','e')]:audit.consume(dict(type=kind,time=str(start+delta),vehicle='v',link=link))
                    audit.consume(event)
            self.assertEqual(audit.summary()['executed_crossings'],2)

    def test_free_avenue_and_yield_street_have_no_mandatory_stop(self):
        for role, control in (('avenue', 'free'), ('street', 'yield')):
            with self.subTest(role=role, control=control):
                audit=PriorityAudit(); row=policy()
                row.update(role=role, control=control, appliedStopSeconds='0.0')
                audit.consume(row)
                for action in ('HEAD', 'GO', 'CROSS'):
                    record=decision(action,10)
                    record.update(role=role, control=control, appliedStopSeconds='0.0', readyTime='10.0')
                    if action=='CROSS':
                        for kind,link in [('left link','w'),('entered link','e')]:
                            audit.consume(dict(type=kind,time='10',vehicle='v',link=link))
                    audit.consume(record)
                result=audit.summary()
                self.assertEqual(result['head_to_cross_by_role'][role]['mean_seconds'],0)
                self.assertEqual(result['pending_heads_at_cut'],0)
                self.assertEqual(result['forced_priority_crossings'],0)

    def test_artificial_avenue_stop_and_changed_control_rejected(self):
        for mutation in ('avenue-stop','yield-clock','changed-control'):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                audit=PriorityAudit(); row=policy(); record=decision('HEAD',10)
                if mutation=='avenue-stop':
                    row.update(role='avenue',control='stop',appliedStopSeconds='5.0')
                    record.update(role='avenue',control='stop',appliedStopSeconds='5.0')
                elif mutation=='yield-clock':
                    row.update(control='yield',appliedStopSeconds='0.0')
                    record.update(control='yield',appliedStopSeconds='0.0')
                else:
                    row.update(control='stop',appliedStopSeconds='5.0')
                    record.update(control='yield',appliedStopSeconds='0.0',readyTime='10.0')
                audit.consume(row);audit.consume(record)

    def test_native_wait_causes_are_attempts_and_do_not_fabricate_crossings(self):
        audit=PriorityAudit()
        for reason in ('priority_stop','priority_yield_conflict','priority_fairness','signal_red',
                       'storage_wait','turn_restriction','congestion_flow_capacity'):
            audit.consume(dict(type='simz1NativeDecision',reason=reason,decision='ABORT' if reason=='turn_restriction' else 'WAIT'))
        result=audit.summary()
        self.assertEqual(result['native_wait_causes'],{'mandatory_stop':1,'yield':2,'signal':1,'insufficient_storage':1,'turn_restriction':1,'congestion':1})
        self.assertEqual(result['executed_crossings'],0)
        self.assertEqual(result['maximum_head_to_cross_seconds'],0)


if __name__ == '__main__':unittest.main()
