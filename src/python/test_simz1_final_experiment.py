"""Authorized policy boundaries, missing evidence and independent selection."""
import copy
import gzip
import json
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight_completion import POLICY, assigned_window, evaluate, policy_document
from simz1_scale_contract import draw_total, experiment, require_scale, specification

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'scenarios/zona1/experiments/final-20261102-v1.json'

class CompletionPolicyTests(unittest.TestCase):
    def result(self,finish,departure=100,**kw):
        # Synthetic timing fixture. Native physical tests cover the proof producer.
        values=dict(entry=departure,traffic_exit=finish,arrival=finish,
            clearance=dict(minimum_gap_m=.1,rear_plus_gap_clearance_m=0))
        values.update(kw)
        return evaluate(dict(vehicle_id='fixture',route_id='r',departure_seconds=departure),**values)

    def test_boundaries_and_original_window(self):
        self.assertEqual(policy_document()['version'],POLICY)
        for close,departure in ((18000,100),(57600,33000),(104400,80000)):
            for finish,expected in ((close-1,'nominal'),(close,'tolerated'),(close+3599,'tolerated'),
                    (close+3600,'tolerated'),(close+3600+.001,'excess_tolerance')):
                r=self.result(finish,departure)
                self.assertEqual(r['classification'],expected,(finish,r))
                self.assertEqual(r['deadline_seconds'],close+3600)
            self.assertEqual(self.result(close+3601,departure)['delay_seconds'],3601)
        self.assertEqual(self.result(32400,100)['classification'],'excess_tolerance')
        self.assertEqual(self.result(86401,80000)['classification'],'nominal')
        self.assertEqual(self.result(21600,100,entry=19800)['classification'],'technical_physical_error')
        self.assertEqual(self.result(60000,100,entry=33000)['classification'],'technical_physical_error')
        for time in (18000,30000,57600,70000,86400,-1,float('nan')):
            with self.assertRaises(ValueError):assigned_window(time)

    def test_missing_abort_and_physical_negative(self):
        for field in ('entry','traffic_exit','arrival','clearance'):
            self.assertEqual(self.result(1000,**{field:None})['classification'],'pending_not_evaluable')
        self.assertEqual(self.result(1000,aborted=True)['trip_outcome'],'aborted')
        for proof in (dict(minimum_gap_m=0,rear_plus_gap_clearance_m=1),
                      dict(minimum_gap_m=.1,rear_plus_gap_clearance_m=-.01),{}):
            self.assertEqual(self.result(1000,clearance=proof)['classification'],'technical_physical_error')
        self.assertEqual(self.result(1000,traffic_exit=1001)['classification'],'technical_physical_error')
        self.assertEqual(self.result(float('nan'))['classification'],'technical_physical_error')

    def test_historical_13_are_only_retrospective_timing(self):
        from simz1_history_fixtures import dataset
        source=dataset('second-avenue')/'Run-3-first-window-violations.json'
        rows=json.loads(source.read_bytes())['violations'];self.assertEqual(len(rows),13)
        delays=[]
        for row in rows:
            self.assertEqual(assigned_window(row['departure_seconds']),(0,18000))
            delay=row['arrival_seconds']-18000;self.assertGreater(delay,0);self.assertLessEqual(delay,3600);delays.append(delay)
            result=evaluate(row,entry=row['entry_seconds'],arrival=row['arrival_seconds'],nominal_violation=True)
            self.assertEqual(result['classification'],'pending_not_evaluable')
        self.assertEqual((min(delays),max(delays)),(13,920))

    def test_xml_and_gzip_closure_still_required(self):
        from simz1_run import xml_elements
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'events.xml.gz'
            for body in (b'<events><event time="1" type="arrival"/>',b'<events><event time="1" type="arrival"/></events>'):
                raw=gzip.compress(body)
                for value in (raw if not body.endswith(b'</events>') else raw[:-8],):
                    path.write_bytes(value)
                    with self.assertRaises((ValueError,EOFError,ET.ParseError,OSError)):
                        list(xml_elements(path,'event','events'))

class ExperimentTests(unittest.TestCase):
    def test_exact_scenarios_and_largest_remainders(self):
        self.assertEqual(json.loads(SPEC.read_bytes()),specification())
        expected={'buses':(0,0,0),'quarter':(24200,30250,550),'half':(48400,60500,1100),'max-test':(96800,121000,2200)}
        for key,counts in expected.items():
            row=experiment(SPEC,key);quota=require_scale(row['total_non_public_vehicles'],iterations=row['iterations'],experiment_spec=SPEC,experiment_scenario=key)
            self.assertEqual(tuple(quota[k] for k in ('carro','moto','pesado')),counts)
            self.assertEqual(quota['public_transport'],269)
        for key in ('full-1','full-10'):
            row=experiment(SPEC,key);quota=require_scale(row['total_non_public_vehicles'],iterations=row['iterations'],experiment_spec=SPEC,experiment_scenario=key)
            self.assertEqual(sum(quota[k] for k in ('carro','moto','pesado')),204186)
        self.assertEqual(experiment(SPEC,'full-10')['iterations'],10)
        self.assertEqual(list(range(experiment(SPEC,'full-10')['iterations'])),list(range(10)))
        self.assertEqual(draw_total(),draw_total())

    def test_invalid_contracts_rejected(self):
        for n in (0,55000,220000,204186):
            with self.assertRaises(ValueError):require_scale(n)
        for key,kwargs in [('max-test',dict(total=180000)),('full-10',dict(total=204186,iterations=11)),
                           ('max-test',dict(total=220000,seed=1))]:
            with self.assertRaises(ValueError):require_scale(**kwargs,experiment_spec=SPEC,experiment_scenario=key)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'mutated.json';value=specification();value['draw']['selected_non_public_vehicles']=220000
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):experiment(path,'full-1')

class FreightAuditPolicyTests(unittest.TestCase):
    def audit(self,finish,entry=100,arrival=True):
        from simz1_freight import FreightAudit
        geometry=dict(body_length_m=8.,minimum_gap_m=.1,route_link_start_m={'a':0.},
            entry_distance_from_route_start_m=30.,exit_distance_from_route_start_m=80.)
        row=dict(vehicle_id='truck',route_id='r',departure_seconds=100,link_ids=['a'],
            completion_policy=POLICY,native_gateway=geometry)
        audit=FreightAudit({'truck':row})
        def event(t,kind,**kwargs):audit.consume(dict(time=str(t),type=kind,**kwargs))
        event(0,'simz1OccupancyDomain',link='a',corridor='c',linkOffsetMeters='0',linkLengthMeters='100')
        event(100,'departure',person='truck',link='a')
        event(entry,'simz1OccupancyReservation',action='ENTER',vehicle='truck',link='a',corridor='c',
            bodyLengthMeters='8',footprintMeters='8.1',reservationOrdinal='1')
        event(entry,'simz1OccupancyProgress',vehicle='truck',link='a',corridor='c',modeledFrontLowerBoundMeters='0')
        event(entry,'vehicle enters traffic',vehicle='truck',link='a')
        event(finish,'simz1OccupancyProgress',vehicle='truck',link='a',corridor='c',modeledFrontLowerBoundMeters='88.1')
        event(finish,'vehicle leaves traffic',vehicle='truck',link='a')
        if arrival:event(finish,'arrival',person='truck',link='a')
        return audit

    def test_tolerance_changes_timing_acceptance_only_and_reset(self):
        from simz1_freight import require_approved_results
        from simz1_result_quality import assess
        for finish,classification in ((17999,'nominal'),(18000,'tolerated'),(21599,'tolerated'),(21600,'tolerated'),(21600.01,'excess_tolerance')):
            audit=self.audit(finish);result=audit.summary()
            self.assertEqual(result['status'],'valid')
            self.assertEqual(result['completion_classifications'][classification],1)
            self.assertEqual(result['restricted_window_violations'],int(finish>=18000))
            manifest={'results':{'9':{'freight_transport_events':result}}}
            require_approved_results(manifest)
            quality=assess(dict(counts=dict(selected_rows=1,completed=1,aborted=0,censored=0),
                provenance=dict(freight_transport_observed=result)))
            self.assertEqual(quality['status'],'review_required' if finish>21600 else 'screening_pass')
            audit.reset();self.assertEqual(audit.summary()['arrivals_observed'],0)
            self.assertFalse(audit.gateway.summary()['complete'])
        with self.assertRaisesRegex(ValueError,'outside its assigned'):self.audit(21600,entry=19800)
        missing=self.audit(20000,arrival=False).summary()
        self.assertEqual(missing['status'],'invalid')
        with self.assertRaises(ValueError):require_approved_results({'results':{'0':{'freight_transport_events':missing}}})

class ObservationAndReplayTests(unittest.TestCase):
    def test_replay_followup_is_explicit_and_historical_clip_is_preserved(self):
        from simz1_freight_completion import observation_contract
        from simz1_continuous_replay import daily_window
        native=dict(experiment=experiment(SPEC,'max-test'),time_horizon=dict(start_seconds=0,end_seconds=108000))
        for selected,expected_end in ((False,86400),(True,108000)):
            source={'replay_window':dict(start_seconds=0,end_seconds=108000)}
            config={'continuous':{},'time_horizon':source['replay_window']}
            if selected:config['experimental_observation']=observation_contract(native)
            view=dict(replay_window=dict(source['replay_window']),window_seconds=120)
            daily_window(config,view,source)
            self.assertEqual(view['replay_window']['end_seconds'],expected_end)
        native['time_horizon']['end_seconds']=90000
        with self.assertRaises(ValueError):observation_contract(native)

    def test_small_balanced_report_images_empty_private_and_iteration_identity(self):
        from simz1_balanced_launch_report import Observation,report
        from simz1_freight import FreightAudit
        from test_simz1_balanced_gateway_od import model
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='balanced-report-fixture-') as td:
            root=Path(td);(root/'run-manifest.json').write_text('{"fixture":true}')
            events=root/'events.xml'
            events.write_text('<events><event time="86400" type="simz1Progress"/><event time="108000" type="simz1Progress"/></events>')
            for iteration in (0,9):
                artifact=dict(path='events.xml',sha256='synthetic-component-fixture')
                od=Observation(model(),{}).od.finish()
                result=dict(events=artifact,private_od_events=dict(od,source=dict(run_id='synthetic-report-fixture',events=artifact)),
                    freight_transport_events=FreightAudit({}).summary(),public_transport_events={'fixture':'no observed bus events supplied'})
                native=dict(run_id='synthetic-report-fixture',status='completed',validation=dict(status='valid'),
                    iterations=dict(completed=[iteration]),results={str(iteration):result},balanced_od={'audit':{'fixture':True}})
                with patch('simz1_balanced_launch_report.load_manifest',return_value=native), \
                     patch('simz1_balanced_launch_report.require_native_success'), \
                     patch('simz1_balanced_launch_report.select_run',return_value={'manifest':native}), \
                     patch('simz1_balanced_launch_report.checked_path',return_value=events), \
                     patch('simz1_balanced_launch_report.context',side_effect=lambda *_:(Observation(model(),{}),{})), \
                     patch('simz1_balanced_launch_report.manifest_identity',return_value={'fixture':True}):
                    report(root,iteration)
                    # Reuse validates identity and every generated artifact without rescanning.
                    with patch('simz1_balanced_launch_report.xml_elements',side_effect=AssertionError('Unnecessary rescan')):report(root,iteration)
                folder=root/f'analysis/it.{iteration}/balanced-launch';doc=json.loads((folder/'report.json').read_text())
                self.assertEqual(doc['iteration'],iteration);self.assertEqual(doc['freight_applicability'],'not_applicable_no_freight')
                self.assertEqual(doc['observation_coverage_seconds'],108000)
                for name in ('demand-day.png','followup.png'):
                    with Image.open(folder/name) as picture:picture.verify()
                self.assertTrue((folder/'followup-24-30.csv').is_file())

    def test_balanced_metadata_is_bound_to_person_and_validation(self):
        from simz1_gateway_od import validated_spatial_demand,validate_od_metadata
        from test_simz1_balanced_gateway_od import model,record
        row=record()
        with patch('simz1_balanced_od_audit.validate_manifest',return_value=(model(),{'p':dict(row,planned_departure=10)})) as verified:
            spatial=validated_spatial_demand(ROOT,dict(spatial_demand=dict(mode='balanced-gateway-v1')))
        verified.assert_called_once_with(ROOT,dict(spatial_demand=dict(mode='balanced-gateway-v1')),postprocessing=True)
        self.assertEqual(validate_od_metadata(row,spatial,person_id='p'),row)
        for ident,value,domain in [('other',row,spatial),('p',dict(row,origin_link='wrong'),spatial),('p',row,dict(spatial))]:
            with self.assertRaises(ValueError):validate_od_metadata(value,domain,person_id=ident)

    def test_followup_does_not_change_private_departures_or_routes(self):
        from generate_montecarlo_z1 import gateway_people
        from simz1_temporal import temporal_spec
        from simz1_agent_types import load_catalog
        from simz1_demand_composition import split
        from simz1_od_policy import named_percentages
        from test_simz1_balanced_gateway_od import model,MIX,CATALOG,SEED
        catalog=load_catalog(CATALOG);snapshots=[]
        for drain in (0,21600):
            temporal=temporal_spec(drain=drain)
            if drain:temporal['observation_policy']=POLICY
            people,report,_=gateway_people(model(),SEED,dict(mode='montecarlo',kind='fixed',minimum=99,maximum=99),
                named_percentages(MIX),temporal,catalog=catalog,balanced_composition=split(100,catalog),balanced_percentages=MIX)
            snapshots.append([ET.tostring(p) for p in people])
        self.assertEqual(*snapshots)
        # The new option changes observation only; it is not a general gateway drain permission.
        with self.assertRaises(ValueError):gateway_people(model(),SEED,dict(mode='montecarlo',kind='fixed',minimum=0,maximum=0),
            named_percentages(MIX),temporal_spec(drain=21600),catalog=catalog)

    def test_iteration_9_selected_without_fallback(self):
        from simz1_balanced_launch_report import report
        native=dict(status='completed',validation=dict(status='valid'))
        with patch('simz1_balanced_launch_report.load_manifest',return_value=native), \
             patch('simz1_balanced_launch_report.require_native_success'), \
             patch('simz1_balanced_launch_report.select_run',side_effect=ValueError('missing iteration 9')) as select:
            with self.assertRaisesRegex(ValueError,'missing iteration 9'):report(ROOT,9)
            select.assert_called_once_with(ROOT,9)

    def test_retired_historical_selector_cannot_select_or_block_explicit_results(self):
        from simz1_run import select_run,selection_warning
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);latest=folder/'latest-successful.json';attempt=folder/'latest-attempt.json'
            retired=dict(status='invalidated_by_authorized_cleanup',run_id=None,run_directory=None,
                reason='Historical deletion; no replacement acceptance')
            latest.write_text(json.dumps(retired));attempt.write_text(json.dumps(retired))
            with patch('simz1_run.load_manifest',side_effect=AssertionError('No fallback allowed')):
                with self.assertRaisesRegex(ValueError,'sin fallback'):select_run(latest_path=latest)
                self.assertIn('explicit',selection_warning({'run_id':'explicit'},latest))
            latest.write_text('{}')
            with self.assertRaisesRegex(ValueError,'incompleta'):select_run(latest_path=latest)
            attempt.write_text('{}')
            with self.assertRaisesRegex(ValueError,'sin identidad'):selection_warning({'run_id':'explicit'},latest)
            # Explicit identity never bypasses native invalidity, even with a retired pointer.
            with patch('simz1_run.load_manifest',return_value=dict(run_id='bad',status='failed',validation=dict(status='invalid'))):
                with self.assertRaisesRegex(ValueError,'Corrida no valida'):select_run(folder,0,latest_path=latest)

if __name__=='__main__':unittest.main()
