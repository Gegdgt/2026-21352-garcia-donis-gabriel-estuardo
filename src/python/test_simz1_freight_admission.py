"""Freight authorization and v7 selection controls; inert fixtures, no QSim/receipts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import simz1_freight_completion as timing
import simz1_scale_contract as scale
from simz1_freight import FreightAudit

PLANNED = 50620.17320287385
WINDOW = [32400, 57600]
DEADLINE = 61200


def row(policy=timing.TOLERATED_ENTRY_POLICY, planned=PLANNED):
    # Historical schedule and assigned window; deliberately synthetic route/body proof.
    return dict(vehicle_id='freight_000392', driver_id='freight_000392', route_id='synthetic-audit',
        departure_seconds=planned, link_ids=['a'], assigned_window_seconds=WINDOW,
        completion_policy=policy, native_gateway=dict(body_length_m=8., minimum_gap_m=.1,
            route_link_start_m={'a':0.}, entry_distance_from_route_start_m=30.,
            exit_distance_from_route_start_m=80.))


def send(audit, kind, time, **attributes):
    return audit.consume(dict(type=kind, time=str(time), person='freight_000392',
        vehicle='freight_000392', link='a', **attributes))


def begin(policy=timing.TOLERATED_ENTRY_POLICY):
    audit=FreightAudit({'freight_000392':row(policy)})
    send(audit, 'simz1OccupancyDomain', 0, corridor='c', linkOffsetMeters='0', linkLengthMeters='100')
    send(audit, 'departure', 50621)
    return audit


def enter(audit, time):
    send(audit, 'simz1OccupancyReservation', time, action='ENTER', corridor='c',
         bodyLengthMeters='8', footprintMeters='8.1', reservationOrdinal='1')
    send(audit, 'simz1OccupancyProgress', time, corridor='c', modeledFrontLowerBoundMeters='0')
    send(audit, 'vehicle enters traffic', time)


def finish(audit, time):
    send(audit, 'simz1OccupancyProgress', time, corridor='c', modeledFrontLowerBoundMeters='88.1')
    send(audit, 'vehicle leaves traffic', time)
    send(audit, 'arrival', time)


def rejection(time=61201):
    return dict(type='simz1FreightAdmissionRejected', time=str(time), person='freight_000392',
        vehicle='freight_000392', link='a', reason='assigned_entry_deadline_expired',
        scheduledDeparture=str(PLANNED), assignedWindowStart='32400', assignedWindowClose='57600',
        latestEntryTime='61200', completionDeadline='61200', latestEntryInclusive='true',
        completionPolicy=timing.TOLERATED_ENTRY_POLICY,
        entryPolicy='assigned_window_close_plus3600_inclusive')


class FreightAdmissionTests(unittest.TestCase):
    def test_nominal_tolerance_and_inclusive_entry_boundary(self):
        for policy in timing.EXPERIMENTAL_POLICIES:
            for stamp in (50621, 57599, 57600, 59400, 61200, 61200.001, 61201, 72000, 86309):
                expected=stamp<57600 if policy==timing.POLICY else stamp<=61200
                with self.subTest(policy=policy,time=stamp):
                    self.assertEqual(timing.entry_permitted(PLANNED,stamp,policy),expected)
                    result=timing.evaluate(row(policy),entry=stamp)
                    self.assertEqual(result['classification'],'pending_not_evaluable' if expected else 'technical_physical_error')
                    self.assertEqual(result['deadline_seconds'],DEADLINE)
                    if not expected:self.assertTrue(result['entry_violation'])

    def test_tolerance_does_not_create_new_scheduled_departure_windows(self):
        for planned in (18000,19800,32400-1,57600,59400,61200,75600-1,86400):
            with self.subTest(planned=planned),self.assertRaises(ValueError):
                timing.entry_permitted(planned,planned,timing.TOLERATED_ENTRY_POLICY)
        for invalid in (True,float('nan'),float('inf'),-1):
            with self.subTest(value=invalid),self.assertRaises(ValueError):timing.assigned_window(invalid)

    def test_final_completion_deadline_is_not_extended_from_actual_entry(self):
        proof=dict(minimum_gap_m=.1,rear_plus_gap_clearance_m=0)
        for stamp,classification in ((57599,'nominal'),(57600,'tolerated'),(61200,'tolerated'),
                                     (61200.001,'excess_tolerance'),(64800,'excess_tolerance')):
            entry=50621 if stamp<59400 else 59400
            result=timing.evaluate(row(),entry=entry,traffic_exit=stamp,arrival=stamp,clearance=proof)
            self.assertEqual(result['classification'],classification)
            self.assertEqual(result['deadline_seconds'],61200)
            self.assertEqual(result['nominal_violation'],stamp>=57600)
        for proof in (None,dict(minimum_gap_m=.09,rear_plus_gap_clearance_m=0),
                      dict(minimum_gap_m=.1,rear_plus_gap_clearance_m=-1)):
            result=timing.evaluate(row(),entry=59400,traffic_exit=61200,arrival=61200,clearance=proof)
            self.assertNotIn(result['classification'],('nominal','tolerated'))

    def test_actual_audit_accepts_tolerance_and_preserves_excess_finding(self):
        for end,classification,accepted in ((61200,'tolerated','satisfied'),(61201,'excess_tolerance','not_satisfied')):
            audit=begin();enter(audit,59400);finish(audit,end);result=audit.summary()
            self.assertEqual(result['completion_classifications'][classification],1)
            self.assertEqual(result['experimental_acceptance'],accepted)
            self.assertEqual(result['restricted_window_violations'],1)
            self.assertEqual(result['completion_records'][0]['deadline_seconds'],61200)

    def test_screening_keeps_v2_completion_deadline_and_fixed_day_censoring(self):
        from simz1_result_quality import assess
        for end,status in ((61200,'screening_pass'),(61201,'review_required')):
            audit=begin();enter(audit,59400);finish(audit,end)
            result=assess(dict(counts=dict(selected_rows=1,completed=1,aborted=0,censored=0),
                provenance=dict(freight_transport_observed=audit.summary())))
            self.assertEqual(result['status'],status)
            self.assertEqual('freight_completion_tolerance_not_satisfied' in result['reasons'],end>61200)
        pending=begin().summary()
        self.assertEqual(pending['experimental_acceptance'],'not_evaluable')
        result=assess(dict(counts=dict(selected_rows=1,completed=1,aborted=0,censored=0),
            provenance=dict(freight_transport_observed=pending,
                day_observation=dict(policy='fixed-day-24h-v1'))))
        self.assertEqual(result['status'],'screening_pass')
        self.assertNotIn('freight_completion_tolerance_not_satisfied',result['reasons'])

    def test_unauthorized_and_historical_tolerance_entries_are_rejected_without_entry_record(self):
        for policy,stamp in ((timing.POLICY,59400),(timing.TOLERATED_ENTRY_POLICY,61200.001),
                             (timing.TOLERATED_ENTRY_POLICY,72000),(timing.TOLERATED_ENTRY_POLICY,86309)):
            audit=begin(policy)
            with self.subTest(policy=policy,time=stamp),self.assertRaises(ValueError):enter(audit,stamp)
            self.assertFalse(audit.entries);self.assertFalse(audit.seen);self.assertFalse(audit.traffic)

    def test_late_duplicate_and_nonmonotone_events_are_not_new_authorizations(self):
        audit=begin();enter(audit,59400)
        with self.assertRaises(ValueError):send(audit,'vehicle enters traffic',59400)
        self.assertEqual(audit.entries,{'freight_000392':59400})
        audit=begin();enter(audit,59400)
        with self.assertRaises(ValueError):send(audit,'vehicle enters traffic',59399)
        audit=begin()
        with self.assertRaises(ValueError):send(audit,'departure',59400)
        self.assertFalse(audit.entries)

    def test_expired_waiting_actor_remains_pending_without_fabricated_entry_or_completion(self):
        audit=begin();audit.consume(rejection());result=audit.summary()
        self.assertEqual(result['waiting_for_insertion'],1)
        self.assertEqual(result['arrivals_observed'],0)
        self.assertEqual(result['observed_traffic_entries'],{})
        self.assertEqual(result['terminal_events'],{})
        self.assertEqual(result['admission_rejections']['freight_000392']['status'],'authorization_expired_not_admitted')
        self.assertEqual(result['completion_records'][0]['classification'],'pending_not_evaluable')
        with self.assertRaises(ValueError):audit.consume(rejection())
        for field,value in [('time','61200'),('completionDeadline','64800'),('vehicle','other'),
                            ('latestEntryInclusive','false'),('reason','arbitrary')]:
            audit=begin();event=rejection();event[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):audit.consume(event)
            self.assertFalse(audit.entries)

    def test_policy_resources_remain_separate_and_reject_mutation_or_absence(self):
        historical=timing.RESOURCE.read_bytes();modern=timing.ENTRY_RESOURCE.read_bytes()
        self.assertEqual(timing.policy_document(timing.POLICY)['entry_policy'],'original_assigned_nominal_window_only')
        self.assertEqual(timing.policy_document(timing.TOLERATED_ENTRY_POLICY)['entry_policy'],'assigned_window_close_plus3600_inclusive')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'policy.json'
            with patch.object(timing,'ENTRY_RESOURCE',path):
                for key,value in [('tolerance_seconds',14400),('deadline_inclusive',False),
                                  ('entry_policy','original_assigned_nominal_window_only'),
                                  ('nominal_windows_seconds',[[0,61200]]),('observation_end_seconds',108000)]:
                    mutated=json.loads(modern);mutated[key]=value;path.write_text(json.dumps(mutated))
                    with self.subTest(key=key),self.assertRaises(ValueError):timing.policy_document(timing.TOLERATED_ENTRY_POLICY)
                path.unlink()
                with self.assertRaises(FileNotFoundError):timing.policy_document(timing.TOLERATED_ENTRY_POLICY)
        self.assertEqual(timing.RESOURCE.read_bytes(),historical)


class FreightExperimentSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=scale.PROJECT/scale.FREIGHT_SPEC
        cls.doc=json.loads(cls.path.read_bytes())
        cls.selected={n:scale.experiment(cls.path,'run'+str(n)) for n in (1000,10000,55000,110000)}

    def test_new_variant_preserves_v6_inputs_counts_and_physical_policy(self):
        historical_path=scale.PROJECT/scale.ORIGIN_SPEC;historical=historical_path.read_bytes()
        old=json.loads(historical)
        self.assertEqual(self.doc,scale.freight_specification())
        self.assertEqual(self.doc['derived_from'],dict(path=scale.ORIGIN_SPEC,sha256=hashlib.sha256(historical).hexdigest()))
        for key in ('draw','demand_seed','service_date','public_vehicles','demand_end_seconds',
                    'observation_end_seconds','native_qsim_end_seconds','scenarios','base_inputs',
                    'signal_variant','origin_admission_policy','postprocessing'):
            self.assertEqual(self.doc[key],old[key],key)
        self.assertEqual(len({s['base_scenario_identity'] for s in self.selected.values()}),1)
        self.assertNotEqual(self.selected[1000]['base_scenario_identity'],scale.experiment(historical_path,'run1000')['base_scenario_identity'])
        for n,selected in self.selected.items():
            self.assertEqual(scale.origin_policy_for_selection(selected),scale.GAP_ORIGIN_POLICY)
            self.assertEqual(scale.launch_postprocessing_policy(selected),'native_diagnostic_v1')
            self.assertEqual(scale.require_scale(n,20261023,1,self.path,selected['scenario']),selected['composition'])
            self.assertEqual(selected['freight_completion_policy'],timing.TOLERATED_ENTRY_POLICY)
        self.assertEqual(historical_path.read_bytes(),historical)

    def test_mutated_selection_and_old_trial_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mutated.json'
            for key,value in [('freight_completion_policy',timing.POLICY),('observation_end_seconds',108000),
                              ('demand_seed',7),('public_vehicles',270),('unknown_override',True)]:
                doc=copy.deepcopy(self.doc);doc[key]=value;path.write_text(json.dumps(doc))
                with self.subTest(key=key),self.assertRaises(ValueError):scale.experiment(path,'run55000')
        with self.assertRaises(ValueError):scale.experiment(self.path,'max-test')
        old=scale.experiment(scale.PROJECT/scale.ORIGIN_SPEC,'run1000')
        with self.assertRaises(ValueError):scale.verify_selection_identity(old,self.selected[1000])
        changed=copy.deepcopy(self.selected[1000]);changed['freight_timing_policy']['policy_sha256']='0'*64
        with self.assertRaises(ValueError):scale.verify_selection_identity(changed,self.selected[1000])

    def test_v7_generator_preserves_selected_physical_policy_and_rejects_loss(self):
        import generate_montecarlo_z1 as generator
        from simz1_config_validation import validate_configuration, admission_execution_contract
        from test_simz1_origin_policy_contract import fixture_config, set_param
        root=fixture_config();set_param(root,'simz1Admission.originPolicy',None)
        self.assertEqual(generator.apply_origin_admission_selection(root,self.selected[1000]),scale.GAP_ORIGIN_POLICY)
        self.assertEqual(validate_configuration(root)['origin_admission_policy'],scale.GAP_ORIGIN_POLICY)
        actual=copy.deepcopy(root)
        self.assertEqual(admission_execution_contract(root,actual)['origin_policy'],scale.GAP_ORIGIN_POLICY)
        set_param(actual,'simz1Admission.originPolicy',None)
        with self.assertRaises(ValueError):admission_execution_contract(root,actual)
        with self.assertRaises(ValueError):generator.apply_origin_admission_selection(root,None)

    def test_trial_identity_binds_v7_and_never_promotes_v6(self):
        import simz1_workflow_state as workflow
        selected=self.selected[1000]
        manifest=dict(experiment=selected,time_horizon=dict(start_seconds=0,end_seconds=86400),
            demand_seed=20261023,matsim_seed=20261023,iterations=dict(first=0,last=0,requested=1,completed=[0]))
        od=dict(od_mode='balanced-gateway-v1')
        self.assertEqual(workflow.trial_experiment_identity(manifest,od),selected['base_scenario_identity'])
        for key,value in [('freight_completion_policy',timing.POLICY),('freight_timing_policy',{}),
                          ('base_scenario_identity','0'*64),('origin_admission_policy',{})]:
            changed=copy.deepcopy(manifest);changed['experiment'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):workflow.trial_experiment_identity(changed,od)
        old=scale.experiment(scale.PROJECT/scale.ORIGIN_SPEC,'run1000')
        historical=dict(manifest,experiment=old)
        self.assertEqual(workflow.trial_experiment_identity(historical,od),old['base_scenario_identity'])
        self.assertNotEqual(old['base_scenario_identity'],selected['base_scenario_identity'])
        relabeled=copy.deepcopy(historical);relabeled['experiment']['schema']=scale.FREIGHT_SCHEMA
        with self.assertRaises(ValueError):workflow.trial_experiment_identity(relabeled,od)

    def test_native_manifest_binds_new_policy_and_original_physical_admission(self):
        selected=self.selected[1000];physical=selected['origin_admission_policy'];freight=selected['freight_timing_policy'];plans='1'*64
        manifest=dict(experiment=dict(selected,initial_population_sha256=plans,
            population_identity_basis='initial plans bytes; iteration count does not enter demand RNG or population serialization'),
            origin_admission_policy=dict(physical,effective_policy=physical['version'],source='explicit versioned experiment',
                artifact=dict(path='inputs/origin-admission-policy.json',sha256=physical['policy_sha256'])),
            freight_completion_policy=timing.TOLERATED_ENTRY_POLICY,
            inputs={'plans':dict(path='plans.xml',sha256=plans),'input:freight-completion-policy.json':
                dict(path='inputs/freight-completion-policy.json',sha256=freight['policy_sha256'])},
            iterations=dict(first=0,last=0,requested=1,completed=[]),demand_seed=20261023,matsim_seed=20261023,
            demand_composition=dict(total_non_public_vehicles=1000,family_counts=dict(carro=440,moto=550,pesado=10)),
            spatial_demand=dict(mode='balanced-gateway-v1'),counts=dict(public_transport_vehicles_configured=269))
        scale.validate_manifest_selection(manifest,selected)
        variants=[]
        for key in ('freight_completion_policy','origin_admission_policy'):
            changed=copy.deepcopy(manifest);changed.pop(key);variants.append(changed)
        changed=copy.deepcopy(manifest);changed['inputs'].pop('input:freight-completion-policy.json');variants.append(changed)
        changed=copy.deepcopy(manifest);changed['inputs']['input:freight-completion-policy.json']['sha256']='0'*64;variants.append(changed)
        for i,changed in enumerate(variants):
            with self.subTest(case=i),self.assertRaises(ValueError):scale.validate_manifest_selection(changed,selected)


if __name__=='__main__':unittest.main()
