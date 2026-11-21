"""Bounded regression tests for the new restart workflow; never launches QSim or a server."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

import simz1_runtime_check as runtime
import simz1_workflow_state as state

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reset_simz1_runs',ROOT/'scripts/maintenance/reset_simz1_runs.py')
reset=importlib.util.module_from_spec(spec);spec.loader.exec_module(reset)

class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        protected=self.root/reset.PROTECTED;protected.mkdir(parents=True)
        (protected/'run-manifest.json').write_text(json.dumps(dict(run_id=reset.PROTECTED_ID,folder=str(protected),status='failed')))
    def base(self):
        (self.root/'pom.xml').write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"><properties><maven.compiler.release>17</maven.compiler.release></properties></project>')
        for name in runtime.REQUIRED_CLASSES:
            p=self.root/'target/classes'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'\xca\xfe\xba\xbe'+struct.pack('>HH',0,61))
    def run_folder(self,name='run-test',status='completed'):
        p=self.root/'scenarios/zona1/montecarlo'/name;p.mkdir(parents=True)
        m=dict(run_id='simz1-'+hashlib.sha256(name.encode()).hexdigest()[:32],folder=str(p),status=status,validation={'status':'valid'})
        (p/'run-manifest.json').write_text(json.dumps(m));(p/'output_events.xml.gz').write_bytes(b'test output not a simulation')
        return p,m
    def quality_run(self,n=1000):
        # Historical acceptance fixture. Saved-policy verification has its own
        # XML/roster regressions in test_simz1_public_fleet_version.py.
        ids = [f'historical_bus_{i:03d}' for i in range(120)]
        snapshot = dict(public_transport_vehicles_configured=120, fleet_vehicle_ids=ids,
                        fleet_by_system=dict(transmetro=80, tubus=40))
        verifier = mock.patch.object(state, 'verified_weekday_fleet', return_value=snapshot)
        verifier.start(); self.addCleanup(verifier.stop)
        p,m=self.run_folder();m.update(counts={'planned_persons':n, 'public_transport_vehicles_configured':120},iterations={'last':0},public_transport={'enabled':True},
            results={'0':{'public_transport_events':dict(road_demand_persons=n,public_transport_vehicles_configured=120,
                transit_drivers_added_to_demand=0,transit_drivers_internal_observed=120,observed_expedition_starts=240,
                public_transport_vehicle_ids_observed=ids,public_transport_vehicle_ids_in_traffic=ids,
                peak_active_public_vehicles_network=50,active_public_vehicles_network=0,trips={'completed_trips':240,'aborted_before_horizon':0})}})
        (p/'run-manifest.json').write_text(json.dumps(m));q=p/'analysis/it.0/graficas_perfiles/calidad_resultados.json';q.parent.mkdir(parents=True)
        q.write_text(json.dumps(dict(run_id=m['run_id'],iteration=0,status='screening_pass')))
        return p,m,q
    def test_java17_headers_and_required_classes(self):
        self.base();self.assertEqual(runtime.verify(self.root)['class_major'],61)
    def test_reject_java25_stale_class(self):
        self.base();p=self.root/'target/classes/Old.class';p.write_bytes(b'\xca\xfe\xba\xbe'+struct.pack('>HH',0,69))
        with self.assertRaisesRegex(ValueError,'Stale'):runtime.verify(self.root)
    def test_reject_preview_or_missing_classes(self):
        self.base();p=self.root/'target/classes'/runtime.REQUIRED_CLASSES[0];p.write_bytes(b'\xca\xfe\xba\xbe'+struct.pack('>HH',65535,61))
        with self.assertRaisesRegex(ValueError,'Preview'):runtime.verify(self.root)
        p.unlink()
        with self.assertRaisesRegex(ValueError,'Missing'):runtime.verify(self.root)
    def test_dependency_identity_missing_and_duplicate(self):
        self.base();jar=self.root/'deps.jar'
        with zipfile.ZipFile(jar,'w') as z:
            for name in runtime.DEPENDENCY_CLASSES:z.writestr(name,b'fixture')
        cp=self.root/'cp.txt';cp.write_text(str(jar));self.assertEqual(len(runtime.verify(self.root,cp)['dependency_sources']),3)
        cp.write_text(str(jar)+os.pathsep+str(jar))
        with self.assertRaisesRegex(ValueError,'Duplicate'):runtime.verify(self.root,cp)
        cp.write_text(str(self.root/'missing.jar'))
        with self.assertRaisesRegex(ValueError,'Incomplete'):runtime.verify(self.root,cp)
    def test_inventory_does_not_delete(self):
        p,_=self.run_folder();plan=reset.inventory(self.root,set());self.assertEqual(len(plan['runs']),1);self.assertTrue(p.exists())
    def test_cleanup_only_selected_generated_files(self):
        p,m=self.run_folder();base=p.parent;pointer=base/'latest-successful.json';pointer.write_text(json.dumps({'run_id':m['run_id'],'folder':str(p)}))
        source=self.root/'scenarios/zona1/network.xml';source.write_text('<network/>')
        plan=reset.inventory(self.root,set());result=reset.apply(self.root,plan,reset.CONFIRM,git_files=set(),process_rows=[])
        self.assertFalse(p.exists());self.assertFalse(pointer.exists());self.assertEqual(source.read_text(),'<network/>')
        self.assertTrue((Path(result['backups'])/(m['run_id']+'.json')).is_file())
    def test_wrong_confirmation_blocks(self):
        p,_=self.run_folder();plan=reset.inventory(self.root,set())
        with self.assertRaises(ValueError):reset.apply(self.root,plan,'yes',git_files=set(),process_rows=[])
        self.assertTrue(p.exists())
    def test_changed_plan_blocks_before_delete(self):
        p,_=self.run_folder();plan=reset.inventory(self.root,set());(p/'new.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):reset.apply(self.root,plan,reset.CONFIRM,git_files=set(),process_rows=[])
        self.assertTrue((p/'run-manifest.json').exists())
    def test_preserve_active_runs_and_tracked_files(self):
        a,_=self.run_folder('run-active','running');b,_=self.run_folder('run-tracked');plan=reset.inventory(self.root,{b.relative_to(self.root).as_posix()+'/run-manifest.json'})
        self.assertEqual(plan['runs'],[]);self.assertEqual(len(plan['skipped']),3)
    def test_preserve_sources_and_wal(self):
        p,_=self.run_folder();(p/'do_not_delete.py').write_text('x=1')
        self.assertEqual(reset.inventory(self.root,set())['runs'],[])
        (p/'do_not_delete.py').unlink();(p/'replay.sqlite-wal').write_bytes(b'active')
        self.assertEqual(reset.inventory(self.root,set())['runs'],[])
    def test_reject_symlink(self):
        p,_=self.run_folder();outside=self.root/'outside';outside.mkdir();(outside/'keep.json').write_text('{}')
        try:(p/'escape').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):reset.inventory(self.root,set())
        self.assertTrue((outside/'keep.json').exists())
    def test_trial_requires_observed_buses_not_just_config(self):
        p,m,q=self.quality_run();self.assertEqual(state.inspect(p,1000)['road_persons'],1000)
        m['results']['0']['public_transport_events']['transit_drivers_internal_observed']=0
        (p/'run-manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'dispatch'):state.inspect(p,1000)
    def test_trial_rejects_small_or_incomplete_run(self):
        p,m,q=self.quality_run(120)
        with self.assertRaisesRegex(ValueError,'Expected 1000'):state.inspect(p,1000)
        m['counts']['planned_persons']=1000;m['status']='failed';(p/'run-manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'not completed'):state.inspect(p,1000)
    def test_trial_rejects_pending_public_vehicles(self):
        p,m,q=self.quality_run();m['results']['0']['public_transport_events']['active_public_vehicles_network']=1
        (p/'run-manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'remain'):state.inspect(p,1000)
    def test_trial_rejects_wrong_quality_identity(self):
        p,m,q=self.quality_run();q.write_text(json.dumps(dict(run_id='different',iteration=0,status='screening_pass')))
        with self.assertRaisesRegex(ValueError,'quality'):state.inspect(p,1000)
    def test_actual_launch_installs_fleet_and_forks(self):
        java=(ROOT/'src/main/java/gt/edu/uvg/sim/zona1/RunZona1Simulation.java').read_text()
        py=(ROOT/'python/ejecutar_simz1.py').read_text();pom=(ROOT/'pom.xml').read_text()
        self.assertIn('installTransit(controler);',java);self.assertIn('SimZ1FailureReport.print',java)
        self.assertIn('exec:exec@simz1-fork',py);self.assertIn('<maven.compiler.release>17</maven.compiler.release>',pom)
    def test_vehicle_specific_lane_guard_is_used(self):
        safety=(ROOT/'src/main/java/gt/edu/uvg/sim/zona1/SimZ1RouteSafety.java').read_text()
        node=(ROOT/'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1QNodeImpl.java').read_text()
        self.assertIn('sharesRoadMode(link, target)',safety);self.assertIn('laneAllowsVehicle',node)
        self.assertIn('scenario.getTransitVehicles().getVehicles().keySet()',safety)
    def test_no_downloads_or_latest_directory_selection(self):
        ps=(ROOT/'scripts/simz1_workflow.ps1').read_text()
        self.assertNotIn('Sort-Object CreationTime',ps);self.assertNotIn('git apply',ps)
        self.assertIn('require-trial',ps);self.assertIn('sqlite-source-manifest.json',ps)

if __name__=='__main__':unittest.main()
