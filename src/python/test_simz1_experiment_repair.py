"""Small deterministic fixtures only: no MATSim, server, browser, or massive demand."""
from collections import Counter
from contextlib import redirect_stdout
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import synthetic_people, generar, SCENARIO
from simz1_agent_types import load_catalog, active_types, allocation_counts, sample_departures, execution_blockers
from simz1_population import population_spec, person_vehicle_type
from simz1_result_quality import assess, PROFILES
from simz1_experiment_preflight import check
from simz1_congestion_audit import CongestionAudit, scan, cycles
from simz1_trip_audit import TripAudit

CATALOG = SCENARIO/'agent-types-car-moto-v1.json'


def feed(audit, kind, t, person=None, vehicle=None, **extra):
    record=dict(type=kind,time=str(t),**extra)
    if person is not None:record['person']=person
    if vehicle is not None:record['vehicle']=vehicle
    return audit.consume(record)


class ExperimentRepairTests(unittest.TestCase):
    def test_effective_catalog_and_exact_quotas_without_generating_massive_demand(self):
        c=load_catalog(CATALOG)
        self.assertEqual(set(active_types(c)),set(PROFILES))
        for n in (120,1000,150000,183154,250000):
            totals=allocation_counts(n,c)
            self.assertEqual(sum(totals.values()),n)
            self.assertTrue(all(totals[k]>0 for k in PROFILES))
            self.assertEqual(totals['TransportePesado'],0)
        self.assertEqual(execution_blockers(active_types(c),c),[])
        original=load_catalog(SCENARIO/'agent-types-road-v1.json')
        self.assertTrue(execution_blockers(active_types(original),original))
        self.assertEqual(original['allocation']['road_weights']['TransportePesado'],5)

    def test_temporal_peaks_are_explicit_and_repeatable(self):
        c=load_catalog(CATALOG)
        first=[sample_departures('Motociclista',1,17,f'p{i}',c)[0] for i in range(120)]
        self.assertEqual(first,[sample_departures('Motociclista',1,17,f'p{i}',c)[0] for i in range(120)])
        self.assertTrue(all(0<=t<86400 for t in first))
        self.assertGreater(c['temporal_demand']['hourly_weights'][7],c['temporal_demand']['hourly_weights'][2])
        for invalid in ([1]*23,[float('nan')]*24,[0]*24,[-1]*24):
            bad=copy.deepcopy(c);bad['temporal_demand']['hourly_weights']=invalid
            from simz1_agent_types import validate_catalog
            with self.assertRaises(ValueError):validate_catalog(bad)

    def test_uniform_origins_and_legacy_rng_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=ET.Element('network');nodes=ET.SubElement(root,'nodes');links=ET.SubElement(root,'links')
            for i in range(10):ET.SubElement(nodes,'node',id=str(i),x=str((i%5)*100),y=str((i//5)*100))
            for i in range(10):
                link=ET.SubElement(links,'link',id=f'l{i}',**{'from':str(i),'to':str((i+1)%10),'modes':'car'})
                attrs=ET.SubElement(link,'attributes');ET.SubElement(attrs,'attribute',name='osm:name').text='Avenida Elena' if i==0 else f'Calle {i}'
            network=Path(folder)/'network.xml';ET.ElementTree(root).write(network)
            def generate(policy=None):
                opts={} if policy is None else dict(origin_policy=policy)
                with redirect_stdout(io.StringIO()):
                    people,report,_=synthetic_people(network,17,population_spec(agents=120),'redistribute',**opts)
                    encoded=[ET.tostring(p) for p in people]
                return encoded,report
            old,old_report=generate()
            explicit,_=generate('legacy-corridors');self.assertEqual(old,explicit)
            new,new_report=generate('uniform-nodes-v1')
            self.assertEqual(new,generate('uniform-nodes-v1')[0]);self.assertNotEqual(old,new)
            self.assertGreater(old_report['physical_origins_by_corridor']['Avenida Elena'],60)
            self.assertLess(new_report['physical_origins_by_corridor']['Avenida Elena'],30)
            self.assertEqual(new_report['corridor_share'],0)
            self.assertEqual(sum(new_report['first_origins_by_link'].values()),120)

    def test_actual_small_generated_xml_has_all_six_types_and_native_inputs_preserved(self):
        from simz1_run import sha256,load_manifest
        source=SCENARIO/'config-simz1.xml';before=sha256(source)
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            run=Path(folder)/'new-six-profile-run'
            report=generar(source,run,20261023,agents=120,corridor_policy='redistribute',
                           origin_policy='uniform-nodes-v1',agent_catalog=CATALOG,storage_policy='strict-receiver-v1')
            manifest=load_manifest(run)
            plans=run/manifest['inputs']['plans']['path']
            counts=Counter(person_vehicle_type(p) for p in ET.parse(plans).getroot().findall('person'))
            self.assertEqual(set(counts),set(PROFILES));self.assertEqual(sum(counts.values()),120)
            vehicles=ET.parse(run/'inputs'/'vehicles.xml').getroot()
            native_types=Counter(e.get('type') for e in vehicles.iter() if e.tag.rsplit('}',1)[-1]=='vehicle')
            self.assertEqual(native_types,counts)  # actual vehicle assignments, not only person labels
            type_nodes={e.get('id'):e for e in vehicles.iter() if e.tag.rsplit('}',1)[-1]=='vehicleType'}
            self.assertTrue(set(PROFILES).issubset(type_nodes))
            moto=type_nodes['Motociclista']
            pcu=next(e for e in moto if e.tag.rsplit('}',1)[-1]=='passengerCarEquivalents')
            self.assertEqual(float(pcu.get('pce')),0.25)
            self.assertEqual(report['vehicle_family_counts']['moto'],sum(counts[k] for k in PROFILES[3:]))
            self.assertEqual(report['origin_policy'],'uniform-nodes-v1')
            self.assertEqual(manifest['status'],'prepared')
        self.assertEqual(sha256(source),before)

    def test_preflight_rejects_blueprint_with_unsupported_heavy_and_accepts_executable(self):
        result=check(SCENARIO/'config-simz1.xml',CATALOG,120,120,'uniform-nodes-v1','strict-receiver-v1')
        self.assertEqual(result['status'],'preflight_pass')
        with self.assertRaises(ValueError):check(SCENARIO/'config-simz1.xml',SCENARIO/'agent-types-road-v1.json',120,120,'uniform-nodes-v1','strict-receiver-v1')

    def test_driver_boarding_maps_vehicle_before_road_entry_without_faking_arrival(self):
        audit=TripAudit(100)
        feed(audit,'departure',1,'p',legMode='car')
        feed(audit,'PersonEntersVehicle',1,'p','different-vehicle')
        row=feed(audit,'vehicle aborts',100,vehicle='different-vehicle')
        self.assertEqual(row['person'],'p');self.assertEqual(row['status'],'censored')
        self.assertIsNone(row['arrival']);self.assertFalse(row['traffic_entered'])
        feed(audit,'stuckAndAbort',100,'p')
        s=audit.summary()
        self.assertEqual(s['pending_trips_at_horizon'],1)
        self.assertEqual(s['censoring_breakdown'],{'boarded_without_traffic_entry':1})
        self.assertEqual(s['terminal_reconciliation']['paired_terminal_events'],1)
        self.assertNotIn('unmapped_vehicle_abort',s['anomalies'])

    def test_early_abort_pair_reverse_order_and_actual_duplicate(self):
        audit=TripAudit(100)
        feed(audit,'departure',1,'p',legMode='car');feed(audit,'PersonEntersVehicle',1,'p','v')
        feed(audit,'stuckAndAbort',5,'p');feed(audit,'vehicle aborts',5,vehicle='v')
        feed(audit,'vehicle aborts',5,vehicle='v')
        s=audit.summary()
        self.assertEqual(s['aborted_before_horizon'],1)
        self.assertEqual(s['terminal_reconciliation']['paired_terminal_events'],1)
        self.assertEqual(s['anomalies']['duplicate_terminal_events'],1)

    def test_passenger_does_not_overwrite_road_driver_and_two_drivers_rejected(self):
        audit=TripAudit(100)
        feed(audit,'departure',1,'d',legMode='car');feed(audit,'PersonEntersVehicle',1,'d','v')
        feed(audit,'departure',1,'passenger',legMode='pt');feed(audit,'PersonEntersVehicle',1,'passenger','v')
        self.assertEqual(audit.vehicle_people['v'],'d')
        feed(audit,'departure',2,'other',legMode='car')
        with self.assertRaises(ValueError):feed(audit,'PersonEntersVehicle',2,'other','v')

    def test_traffic_entry_vs_exit_and_unknown_identity_not_guessed(self):
        audit=TripAudit(100)
        for i in range(3):feed(audit,'departure',1,f'p{i}',legMode='car')
        feed(audit,'vehicle enters traffic',2,'p1','v1')
        feed(audit,'vehicle enters traffic',2,'p2','v2')
        feed(audit,'vehicle leaves traffic',3,'p2','v2')
        feed(audit,'vehicle aborts',100,vehicle='p0') # person == vehicle is NOT identity evidence
        s=audit.summary()
        self.assertEqual(s['pending_trips_at_horizon'],3)
        self.assertEqual(s['anomalies']['unmapped_vehicle_abort'],1)
        self.assertEqual(s['censoring_breakdown'],{'no_traffic_entry_evidence':1,'entered_traffic_without_arrival':1,'left_traffic_without_arrival':1})
        self.assertEqual(s,audit.summary())

    def test_quality_rejects_incomplete_and_missing_profiles_without_faking_means(self):
        report=dict(run_id='r',iteration=0,counts=dict(selected_rows=100,completed=21,aborted=0,censored=79),profiles=[])
        before=copy.deepcopy(report);q=assess(report,require_six=True)
        self.assertEqual(report,before);self.assertEqual(q['status'],'review_required')
        self.assertIn('completion_below_declared_target',q['reasons'])
        self.assertIn('required_profiles_missing',q['reasons'])
        report['counts'].update(completed=100,censored=0)
        report['profiles']=[dict(profile=p,n_total=10) for p in PROFILES]
        self.assertEqual(assess(report,require_six=True)['status'],'screening_pass')

    def test_streaming_audit_snapshots_waits_before_cleanup_not_deadlock_claim(self):
        a=CongestionAudit(100)
        for p,v,link in [('p','v','a'),('q','w','b')]:
            feed(a,'departure',1,p,legMode='car',link=link)
            feed(a,'PersonEntersVehicle',1,p,v)
            feed(a,'vehicle enters traffic',1,p,v,link=link)
        feed(a,'simz1NativeDecision',99,vehicle='v',link='a',nextLink='b',reason='storage_wait',decision='WAIT',admissionPolicy='strict-receiver-v1')
        feed(a,'simz1NativeDecision',99,vehicle='w',link='b',nextLink='a',reason='storage_wait',decision='WAIT',admissionPolicy='strict-receiver-v1')
        feed(a,'vehicle aborts',100,vehicle='v');feed(a,'stuckAndAbort',100,'p')
        feed(a,'vehicle aborts',100,vehicle='w');feed(a,'stuckAndAbort',100,'q')
        s=a.summary();self.assertEqual(s['horizon_snapshot']['active_vehicles_from_traffic_events'],2)
        self.assertEqual(s['horizon_snapshot']['candidate_wait_cycles'],[['a','b']])
        self.assertEqual(s['trips']['pending_trips_at_horizon'],2)
        self.assertEqual(s,a.summary())
        with self.assertRaises(ValueError):feed(a,'departure',90,'x')

    def test_hourly_network_snapshots_and_storage_evidence_preserve_unknowns(self):
        audit=CongestionAudit(7200)
        feed(audit,'departure',1,'p',legMode='car',link='a')
        feed(audit,'PersonEntersVehicle',1,'p','v')
        feed(audit,'vehicle enters traffic',2,'p','v',link='a')
        feed(audit,'simz1NativeDecision',3599,vehicle='v',link='a',nextLink='b',
             reason='storage_wait',decision='WAIT',admissionPolicy='strict-receiver-v1')
        feed(audit,'vehicle leaves traffic',3600,'p','v',link='a')
        feed(audit,'arrival',3600,'p',legMode='car',link='a')
        feed(audit,'simz1Progress',7200)
        report=audit.summary()
        self.assertEqual([r['active_vehicles_from_traffic_events'] for r in report['hourly_network_before_boundary']],[1,0])
        self.assertEqual(report['storage_observations']['coverage']['legacy_events_without_receiver_observation'],1)
        self.assertEqual(report['storage_observations']['counts']['storage_wait'],1)
        self.assertEqual(report['storage_observations']['snapshots_by_branch'],{})

    def test_wait_cycle_algorithm_and_gzip_stream(self):
        self.assertEqual(cycles([('a','b'),('b','c')]),[])
        self.assertEqual(cycles([('a','b'),('b','a'),('c','c')]),[['a','b'],['c']])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events.xml.gz'
            with gzip.open(p,'wt') as f:f.write('<events><event type="departure" time="1" person="p" legMode="car"/><event type="arrival" time="2" person="p" legMode="car"/></events>')
            s=scan(p,100);self.assertEqual(s['trips']['completed_trips'],1)


if __name__=='__main__':unittest.main()
