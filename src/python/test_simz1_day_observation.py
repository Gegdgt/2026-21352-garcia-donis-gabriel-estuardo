"""Fixed-day policy and census controls; no generation and no QSim in this suite."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from simz1_day_observation import classify, DayAudit, FIELDS, POLICY
from simz1_scale_contract import day_specification, specification, experiment, require_scale
from simz1_trip_audit import TripAudit


class DayPolicyTests(unittest.TestCase):
    def row(self, family='carro',scheduled=86340,departure=86340,entry=86340,**kw):
        return dict(family=family,scheduled_departure=scheduled,departure=departure,traffic_entry=entry,**kw)

    def test_recent_private_pending(self):
        r=classify(self.row())
        self.assertEqual(r['status'],'active_at_cut');self.assertEqual(r['pending_class'],'recent_at_horizon')
        self.assertEqual(r['observed_traffic_seconds'],60);self.assertIsNone(r['complete_duration_seconds'])

    def test_hour_exclusive_and_old_request(self):
        self.assertEqual(classify(self.row(scheduled=82800,departure=82800,entry=82800))['pending_class'],'recent_at_horizon')
        self.assertEqual(classify(self.row(entry=82799))['pending_class'],'prolonged_traffic_review_required')
        r=classify(self.row(scheduled=100,departure=100,entry=86399))
        self.assertEqual(r['pending_class'],'recent_entry_old_request');self.assertEqual(r['incorporation_delay_seconds'],86299)

    def test_truck_three_hours_night_and_bus(self):
        for family in ('pesado','bus'):
            r=classify(self.row(family=family,scheduled=75600,departure=75600,entry=75600))
            self.assertEqual(r['observed_traffic_seconds'],10800)
            self.assertEqual(r['pending_class'],'horizon_censored_no_private_duration_threshold')

    def test_waiting_and_null_is_not_zero(self):
        r=classify(self.row(scheduled=100,departure=100,entry=None))
        self.assertEqual(r['status'],'waiting_for_incorporation');self.assertIsNone(r['observed_traffic_seconds'])
        self.assertEqual(classify(self.row(departure=None,entry=None))['status'],'scheduled_not_departed')

    def test_arrival_inclusive_T_and_physical_after_rejected(self):
        self.assertEqual(classify(self.row(arrival=86400))['complete_duration_seconds'],60)
        with self.assertRaises(ValueError):classify(self.row(arrival=86401))

    def test_prior_abort_and_interruption(self):
        aborted=classify(self.row(abort_before_cleanup=86399))
        self.assertEqual(aborted['status'],'aborted_before_cut')
        self.assertEqual(aborted['observed_traffic_seconds'],59)
        self.assertEqual(classify(self.row(scheduled=50000,departure=50000,entry=50000),cut=59159,reached=False)['status'],'interrupted_before_horizon')

    def test_exit_without_arrival_is_not_active_or_completed(self):
        row=self.row(entry=86340,traffic_exit=86350)
        for abort in (None,86399):
            r=classify(dict(row,abort_before_cleanup=abort))
            self.assertEqual(r['observed_traffic_seconds'],10)
            self.assertEqual(r['observed_traffic_end_seconds'],86350)
            self.assertEqual(r['observed_traffic_end_basis'],'traffic_exit')
            self.assertEqual(r['status'],'exited_without_arrival' if abort is None else 'aborted_before_cut')
            self.assertIsNone(r['complete_duration_seconds'])
        with self.assertRaises(ValueError):classify(self.row(entry=86340,traffic_exit=86339))

    def test_six_selectors_no_redraw(self):
        old=specification();new=day_specification()
        for key in ('draw','demand_seed','service_date','public_vehicles','scenarios','signal_variant'):
            self.assertEqual(old[key],new[key])
        path=Path(__file__).resolve().parents[1]/'scenarios/zona1/experiments/final-20261103-24h-v2.json'
        for scenario,total,it in [('buses',0,1),('quarter',55000,1),('half',110000,1),('full-1',204186,1),('full-10',204186,10),('max-test',220000,1)]:
            selection=experiment(path,scenario)
            self.assertEqual((selection['total_non_public_vehicles'],selection['iterations'],selection['observation_end_seconds']),(total,it,86400))
            composition=require_scale(total,20261023,it,path,scenario)
            if scenario=='max-test':self.assertEqual(composition,dict(carro=96800,moto=121000,pesado=2200,public_transport=269))

    def test_cleanup_pair_counted_once_prior_abort_at_T_remains_real(self):
        for marker,censored in ((False,False),(True,True)):
            a=TripAudit(86400,fixed_day=True)
            a.consume(dict(type='departure',time='86340',person='p',legMode='car'))
            a.consume(dict(type='vehicle enters traffic',time='86340',person='p',vehicle='v'))
            if marker:a.consume(dict(type='simz1DayCut',time='86400'))
            r=a.consume(dict(type='stuckAndAbort',time='86400',person='p'))
            a.consume(dict(type='vehicle aborts',time='86400',vehicle='v'))
            self.assertEqual(r['censored'],censored)
            self.assertEqual(a.summary()['incomplete_trips'],1)
            self.assertEqual(a.summary()['aborted_before_horizon'],int(not censored))

    def audit(self,folder):
        expected={'p':dict(vehicle_id='p',scheduled_departure=86340.,family='carro')}
        row=dict(expected['p'],trip_id='p',**{k:None for k in FIELDS})
        row.update(departure=86340.,traffic_entry=86340.,last_transition=86340.,last_link='a')
        saved=dict(classify(row),run_id='r',iteration=0,policy=POLICY,cleanup_abort_events=2)
        path=Path(folder)/'census.gz'
        with gzip.open(path,'wt') as stream:stream.write(json.dumps(saved)+'\n')
        return DayAudit(path,'r',0,expected)

    def test_native_census_crosschecked_and_no_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit=self.audit(tmp)
            for event in [dict(type='departure',time='86340',person='p',link='a'),
                          dict(type='vehicle enters traffic',time='86340',person='p',vehicle='p',link='a'),
                          dict(type='simz1DayCut',time='86400',lastCompletedStep='86400',policy=POLICY,iteration='0',run_id='r'),
                          dict(type='stuckAndAbort',time='86400',person='p'),
                          dict(type='vehicle aborts',time='86400',vehicle='p')]:audit.consume(event)
            report=audit.finish()
            self.assertEqual(report['counts'],{'active_at_cut':1});self.assertEqual(report['completion_rate'],0)
            self.assertEqual(audit.frozen['p']['cleanup_abort_events'],2)
            with self.assertRaises(ValueError):audit.consume(dict(type='arrival',time='86401',person='p'))

    def test_census_without_cut_or_mutated_arrival_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit=self.audit(tmp)
            with self.assertRaises(ValueError):audit.finish()
            with self.assertRaises(ValueError):audit.consume(dict(type='simz1DayCut',time='59159',lastCompletedStep='59159'))

    def test_marker_identity_and_input_metadata_mutations_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for field,wrong in [('policy','WRONG'),('iteration','999'),('run_id','another-run')]:
                audit=self.audit(tmp)
                marker=dict(type='simz1DayCut',time='86400',lastCompletedStep='86400',policy=POLICY,iteration='0',run_id='r')
                marker[field]=wrong
                with self.assertRaises(ValueError):audit.consume(marker)
            audit=self.audit(tmp)
            expected={key:{f:row[f] for f in ('vehicle_id','scheduled_departure','family')} for key,row in audit.rows.items()}
            for field,wrong in [('od','{"0":{"od_class":"FABRICATED_OD"}}'),('profile','fabricated-profile')]:
                saved=copy.deepcopy(audit.native['p']);saved[field]=wrong
                with gzip.open(audit.path,'wt') as stream:stream.write(json.dumps(saved)+'\n')
                with self.assertRaises(ValueError):DayAudit(audit.path,'r',0,expected)

if __name__=='__main__':unittest.main()
