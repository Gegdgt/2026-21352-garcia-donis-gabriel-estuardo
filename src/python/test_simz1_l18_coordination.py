"""Versioned synthetic coordination: native original duty, negatives and parity.

Bounded fixtures only; no Run1000 or large-experiment approval is manufactured.
"""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from simz1_local_signal_variant import BASE, POLICY, inspect_config
from simz1_temporal_passage import TemporalPassage, fixed_transit_audit, COMPATIBLE
from test_simz1_temporal_passage import HISTORICAL, ROOT, EVIDENCE

CONFIG=BASE/'config-l18-local-v1.xml'


def main():
    out=Path(tempfile.mkdtemp(prefix='l18-coordination-',dir=ROOT/'runtime'))
    print('Evidence:',out,flush=True)
    results=[]
    def command(name,args):
        with (out/(name+'.log')).open('w',encoding='utf-8') as log:
            p=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        results.append(dict(name=name,exit_code=p.returncode))
        print(name,p.returncode,flush=True)
        if p.returncode:raise AssertionError((out/(name+'.log')).read_text(encoding='utf-8')[-4000:])
    try:
        info=inspect_config(CONFIG)
        assert info['effective_offsets']=={'579787032':0,'333531372':60}
        assert not info['observed_timing']
        cp=os.pathsep.join([str(ROOT/'target/classes'),str(ROOT/'target/test-classes'),str(ROOT/'src/main/resources'),(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()])
        java=Path(r'C:\Program Files\Java\jdk-17\bin\java.exe'); control=BASE/'signalControl-l18-local-v1.xml'
        command('native-full-original-L18',[java,'-Xmx3g','-cp',cp,'gt.edu.uvg.sim.zona1.SimZ1L18NativeTripCheck',HISTORICAL,control,out/'native'])
        # Same effective historical network/lanes as the native fixture, with
        # only the explicit control variant replaced.
        import xml.etree.ElementTree as ET
        tree=ET.parse(HISTORICAL/'config-simz1.xml')
        for module in tree.getroot().findall('module'):
            for param in module.findall('param'):
                value=param.get('value','')
                if value and (HISTORICAL/value).is_file():param.set('value',str((HISTORICAL/value).resolve()))
        tree.find("module[@name='signalsystems']/param[@name='signalcontrol']").set('value',str(control))
        effective=out/'effective.xml';tree.write(effective,encoding='utf-8',xml_declaration=True)
        temporal=TemporalPassage(effective,HISTORICAL)
        public=fixed_transit_audit(temporal,HISTORICAL/'inputs/transit-weekday/transitSchedule.xml',HISTORICAL/'inputs/transit-weekday/transitVehicles.xml')
        assert public['status']=='compatible',public
        (out/'fixed-service-python.json').write_text(json.dumps(public,indent=2))
        by_route={r['route']:r['status'] for r in public['routes']}
        for route in json.loads((HISTORICAL/'inputs/freight-weekday/routes.json').read_text())['routes']:
            by_route[route['route_id']]=temporal.query(tuple(route['link_ids']),8.,40/3.6)[0]
        java_rows=json.loads((out/'native/fixed-service-java.json').read_text())
        assert len(java_rows)==28 and len(by_route)==28
        for row in java_rows:assert row['status']==by_route[row['route']]==COMPATIBLE,row
        local=json.loads((out/'native/local-movements-java.json').read_text())
        for row in local:
            assert temporal.query(tuple(row['path']),row['body'],row['speed'],row['lane'],False)[0]==row['status']==COMPATIBLE,row
        policy=json.loads(POLICY.read_text());assert len(policy['local'])==7 and policy['exhaustive_assignments']==6400
        witness=json.loads((EVIDENCE/'signal_fixture_input.json').read_text())
        witness['path']=next(r['route_link_ids'] for r in public['routes'] if r['route']=='L18_6245758_part1')
        witness['currentIndex']=witness['path'].index('osm_420120098_2_forward')
        for mode in ('receiver_full','connector_conflict','red'):
            folder=out/mode;folder.mkdir();(folder/'signal_fixture_input.json').write_text(json.dumps(witness))
            command(mode,[java,'-Xmx2g','-cp',cp,'org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1FixedServiceTemporalCheck',folder,control,mode])
            negative=json.loads((folder/'negative-result.json').read_text())
            assert negative['native_moves']==0 and negative['reservations_unchanged']
            if mode!='red':assert negative['joint_permission_ticks']==54 # 18 ticks in each of three complete 80s cycles.
        from test_simz1_lane_policy_integration import generation_options,SEED
        from generate_montecarlo_z1 import generar
        with (out/'preparation-100.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
            generar(CONFIG,out/'preparation-100',seed=SEED,**generation_options())
        manifest=json.loads((out/'preparation-100/run-manifest.json').read_text())
        assert manifest['signal_variant']['policy']==info['policy']
        assert manifest['counts']['non_public_vehicles_configured']==100
        assert manifest['counts']['public_transport_vehicles_configured']==269
        print('real preparation 100, all fixed services, local parity: PASS',flush=True)
        results.append(dict(name='real-preparation-100-and-parity',exit_code=0,local_witnesses=len(local)))
    finally:
        (out/'results.json').write_text(json.dumps(results,indent=2))


if __name__=='__main__':main()
