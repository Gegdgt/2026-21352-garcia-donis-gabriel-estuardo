"""Production temporal-routing checks, Java/Python parity and fixed-service gate.

Never runs a massive simulation or produces approval receipts. The actual fixed
L18 incompatibility is an expected rejection, not a successful preparation.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_temporal_passage import TemporalPassage, COMPATIBLE, IMPOSSIBLE, UNKNOWN, fixed_transit_audit, require_fixed_transit

ROOT = Path(__file__).resolve().parents[1]
from simz1_history_fixtures import temporal
HISTORICAL, EVIDENCE = temporal()


class PeriodicTests(unittest.TestCase):
    def configured(self, step):
        temp = tempfile.TemporaryDirectory(prefix='temporal-step-format-')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base/'network.xml').write_text('<network><nodes><node id="a" x="0" y="0"/>'
            '<node id="b" x="100" y="0"/></nodes><links><link id="road" from="a" to="b" '
            'length="100" permlanes="1" capacity="2000" freespeed="10" modes="car"/></links></network>',encoding='utf-8')
        config = ET.fromstring('<config><module name="network"><param name="inputNetworkFile" value="network.xml"/>'
            '</module><module name="qsim"><param name="timeStepSize" value="1"/></module></config>')
        config.find("module[@name='qsim']/param[@name='timeStepSize']").set('value',step)
        return TemporalPassage(config,base)

    def test_native_clock_step_preserves_numeric_passage_budget(self):
        for numeric,clock in [('1','00:00:01'),('2','00:00:02')]:
            with self.subTest(step=clock):
                before,after = self.configured(numeric),self.configured(clock)
                self.assertEqual(before.step,after.step)
                self.assertEqual(before.traversal('road',None,10),after.traversal('road',None,10))
                self.assertEqual(before.capacity,after.capacity)
                self.assertEqual(before.windows(()),after.windows(()))

    def test_malformed_clock_step_still_rejected(self):
        for value in ('not-a-time','00:00','00:00:01:00'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.configured(value)

    def test_invalid_numeric_step_cannot_prove_a_passage(self):
        for value in ('0','-1','nan','inf','-inf'):
            with self.subTest(value=value):self.assertEqual(UNKNOWN,self.configured(value).windows(()))

    def fixture(self, offset=0, cycle=80, unknown=False):
        t=TemporalPassage.__new__(TemporalPassage);t.step=1.
        t.signals={'a':[('a','g',frozenset({'a.lane.0'}),frozenset())],
                   'b':[('b','g',frozenset({'b.lane.0'}),frozenset())]}
        t.plans={'a':dict(cycle=80,offset=0,groups={'g':(49,78)}),
                 'b':None if unknown else dict(cycle=cycle,offset=offset,groups={'g':(0,47)})}
        return t

    def test_distinct_controls_and_offsets(self):
        rows=(('a','a.lane.0','b',0.,True),('b','b.lane.0','c',4.,False))
        self.assertEqual(IMPOSSIBLE,self.fixture().windows(rows))
        self.assertEqual(COMPATIBLE,self.fixture(40).windows(rows))
        self.assertEqual(COMPATIBLE,self.fixture(cycle=81).windows(rows))
        self.assertEqual(UNKNOWN,self.fixture(cycle=100003).windows(rows))
        self.assertEqual(UNKNOWN,self.fixture(unknown=True).windows(rows))
        self.assertEqual(COMPATIBLE,self.fixture().windows(rows[:1]))

    def test_clearance_and_unresolved_lane(self):
        t=self.fixture()
        self.assertEqual(IMPOSSIBLE,t.windows((('b','b.lane.0','c',43.,False),)))
        self.assertEqual(COMPATIBLE,t.windows((('b','b.lane.0','c',42.,False),)))
        self.assertEqual(UNKNOWN,t.windows((('b',None,'c',4.,False),)))
        t.step=2**.5
        self.assertEqual(UNKNOWN,t.windows((('b','b.lane.0','c',5.,False),)))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preflights',action='store_true');args=parser.parse_args()
    folder=Path(tempfile.mkdtemp(prefix='temporal-passage-',dir=ROOT/'runtime'));print('Evidence:',folder,flush=True)
    steps=[]
    def command(name,arguments,timeout=180):
        with (folder/(name+'.log')).open('w',encoding='utf-8') as log:
            p=subprocess.run(list(map(str,arguments)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        steps.append(dict(name=name,exit_code=p.returncode,command=list(map(str,arguments))))
        print(name,'exit',p.returncode,flush=True)
        if p.returncode:raise AssertionError((folder/(name+'.log')).read_text(encoding='utf-8')[-5000:])
    passed=False
    try:
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(PeriodicTests)
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise AssertionError('periodic negatives failed')
        cp=os.pathsep.join([str(ROOT/'target/classes'),str(ROOT/'target/test-classes'),str(ROOT/'src/main/resources'),(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()])
        java=Path(r'C:\Program Files\Java\jdk-17\bin\java.exe')
        for name in ('gt.edu.uvg.sim.zona1.SimZ1TemporalRouteCheck','org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1TemporalInstallationCheck'):
            command(name.rsplit('.',1)[-1],[java,'-Xmx2g','-cp',cp,name,EVIDENCE,folder])
        command('native-red-negative',[java,'-Xmx2g','-cp',cp,'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1TemporalInstallationCheck',EVIDENCE,folder,'red'])
        temporal=TemporalPassage(HISTORICAL/'config-simz1.xml',HISTORICAL)
        result=json.loads((folder/'route-result.json').read_text())
        for key,status in (('old',IMPOSSIBLE),('candidate',COMPATIBLE)):
            assert temporal.query(tuple(result[key][result['index']:]),4.5,50/3.6)[0]==status
        report=fixed_transit_audit(temporal,HISTORICAL/'inputs/transit-weekday/transitSchedule.xml',HISTORICAL/'inputs/transit-weekday/transitVehicles.xml')
        (folder/'fixed-service-python.json').write_text(json.dumps(report,indent=2)+'\n')
        java_rows=json.loads((folder/'fixed-service-java.json').read_text());public={r['route']:r for r in report['routes']}
        freight=json.loads((HISTORICAL/'inputs/freight-weekday/routes.json').read_text())
        freight={r['route_id']:r for r in freight['routes']}
        for row in java_rows:
            actual=public[row['route']]['status'] if row['class']=='bus' else temporal.query(tuple(freight[row['route']]['link_ids']),8.,40/3.6)[0]
            assert actual==row['status'],row
        try:require_fixed_transit(report)
        except ValueError as exc:assert 'L18_6245758_part1' in str(exc)
        else:raise AssertionError('Fixed service impossibility was silently accepted')
        # The fixed-route witness has the actual L18 prefix; the native probe
        # uses an optimistic road actor without dwell, so a stop cannot explain
        # its zero movement or make the absent signal intersection appear.
        native=folder/'fixed-native';native.mkdir()
        witness=json.loads((EVIDENCE/'signal_fixture_input.json').read_text())
        witness['path']=public['L18_6245758_part1']['route_link_ids'];witness['currentIndex']=witness['path'].index('osm_420120098_2_forward')
        (native/'signal_fixture_input.json').write_text(json.dumps(witness,indent=2))
        command('fixed-native',[java,'-Xmx2g','-cp',cp,'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1FixedServiceTemporalCheck',native])
        proof=json.loads((native/'signal_fixture_result.json').read_text());assert proof['nativeMoves']==0 and proof['simultaneousPermissiveTicks']==0 and proof['bodyMeters']==13.5
        if args.preflights:
            from test_simz1_lane_policy_integration import CONFIG,CATALOG,OD,PUBLIC,FREIGHT,generation_options,SEED
            from simz1_balanced_launch import check
            from simz1_experiment_preflight import check as experiment_check
            from generate_montecarlo_z1 import generar
            cases=[('balanced_preflight_180000',lambda:check(CONFIG,CATALOG,180000,OD/'perimeter.geojson',OD/'access.json',OD/'mix.json',transit_service=PUBLIC)),
                   ('experiment_preflight_180000',lambda:experiment_check(CONFIG,CATALOG,180000,180000,'lane-length-access-v1','strict-receiver-v1',PUBLIC,'2026-10-23',True,
                       freight_service=FREIGHT,freight_service_date='2026-10-23',freight_vehicles=1800,whole_vehicle_reservation=True,qsim_threads=1,
                       destination_policy='lane-length-destinations-v1',od_mode='balanced-gateway-v1',zone_boundary=OD/'perimeter.geojson',od_access_catalog=OD/'access.json',od_mix_file=OD/'mix.json',seed=SEED)),
                   ('real_preparation_100',lambda:generar(CONFIG,folder/'preparation-100',seed=SEED,**generation_options()))]
            for name,call in cases:
                with (folder/(name+'.log')).open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
                    try:call()
                    except ValueError as exc:
                        log.write(str(exc)+'\n');assert 'TEMPORAL_FIXED_SERVICE_INCOMPATIBLE' in str(exc) and 'L18_6245758_part1' in str(exc),str(exc)
                        steps.append(dict(name=name,status='expected_model_rejection',native_execution=False,reason=str(exc)))
                    else:raise AssertionError(name+' accepted incompatible service')
        passed=True
    finally:
        (folder/'focused-results.json').write_text(json.dumps(dict(status='PASS' if passed else 'FAIL',checks=steps,
            massive_started=False,approval_written=False,scenario_acceptable=False),indent=2)+'\n')
    print('PASS temporal repair checks; fixed L18 scenario remains blocked; no approval receipt',flush=True)


if __name__=='__main__':main()
