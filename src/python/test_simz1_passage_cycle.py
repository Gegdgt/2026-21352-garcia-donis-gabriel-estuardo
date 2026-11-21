from simz1_history_fixtures import dataset, materialize
"""C529-A focal native queues only; never starts Controller, QSim or Validate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
RUN=materialize('c529')
DIAG=dataset('c529-evidence')
JAVA_PACKAGE='org.matsim.core.mobsim.qsim.qnetsimengine.'
BASELINE='91d3ffce66bee80da3f0450e9d98a5a0316b3ec7'
PRODUCTION=['src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java']+['src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/'+n+'.java' for n in ('SimZ1CorridorOccupancy','Zona1QNodeImpl')]
CHECKS=['SimZ1PriorityReceiverCheck','SimZ1PriorityLookaheadCheck','SimZ1PassageFairnessCheck','SimZ1TenthStreetReceptionCheck','SimZ1DownstreamStorageCheck','SimZ1TransitPassageReleaseCheck','SimZ1TransitPassageNativeCheck']
EVIDENCE_SHA256={
    'early_dependency.json':'7d6945444a26210f73b4bf3a2c327601708df1ed9207867d6cfe923c915605aa',
    'early_cases_minimal.json':'5d1baea4e17a6cc8ac44b12de32b9223e7de121f56ceaab246da2f3fe55fad97',
    'early_case_plans.json':'9594132e02ecda9950972348c91d1a89ec2d3becacfdc838cc7d41bda9596eb6',
    'focus_dependency_evidence.json':'134a9ec27f7453bd3c4fdb55530a410dab09e51fd2cd45d62f415e57b251a826',
    'focus_state_history.json':'4284bebc5ebe4179e3f185f760b92c20f366df72179130b366e9ea0f8fd5b4e3',
    'code_excerpts.txt':'0639297648413f3567c29b22e1312b608fd3ed5119efe70802a22aa4f5cf0be5',
    'code_sources.json':'05233ec0af20e0482ebb266c3b9920d49e9ea4667945f15ef2a25bf43bd60f3f',
    'effective_config_summary.json':'a517d149f2458582b49ce043cfddfad52f9a3e0b73d04d4e7f5c274aa328a998',
}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def integration_checks(folder, receipt_start_sha):
    from simz1_workflow_state import fingerprint
    from test_simz1_sequence_contract import check_protected_sources, HERE
    baseline=json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256']
    checked=check_protected_sources(ROOT,baseline,receipt_start_sha)
    workflow=(ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf8')
    assert workflow.index('python\\test_simz1_passage_cycle.py')<workflow.index("'validated-source.txt'")
    synthetic=folder/'fingerprint';synthetic.mkdir()
    from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
    fixed=list(REQUIRED_FIXTURE_FILES)
    changed=PRODUCTION+['python/test_simz1_passage_cycle.py','python/test_simz1_sequence_contract.py',
        'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1PassageCycleCheck.java',
        'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1PassageAffectedChecks.java','scripts/simz1_workflow.ps1']
    for name in fixed+changed:
        p=synthetic/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
    for name in changed:
        before=fingerprint(synthetic);(synthetic/name).write_text('changed');assert before!=fingerprint(synthetic),name
    (folder/'integration.json').write_text(json.dumps(dict(protected_sources_checked=checked,changed_sources_fingerprinted=changed,
        validate_invokes_focal_check=True,approval_written=False),indent=2)+'\n')
    print('integration/protected sources/fingerprint: PASS',flush=True)

def prepare(folder):
    # Reuse all seven requested evidence artifacts, preserving their identities.
    for name,digest in EVIDENCE_SHA256.items():assert sha(DIAG/name)==digest,'Changed C529 evidence: '+name
    evidence={name:json.loads((DIAG/name).read_text(encoding='utf8')) for name in
        ('early_dependency.json','early_cases_minimal.json','early_case_plans.json',
         'focus_dependency_evidence.json','focus_state_history.json','code_sources.json')}
    assert 'passageMayProceed' in (DIAG/'code_excerpts.txt').read_text(encoding='utf8')
    historical=[]
    for vehicle in ('z1_106044','z1_49500'):
        rows=[e for e in evidence['early_cases_minimal.json']['events'] if e.get('vehicle')==vehicle and e.get('time')=='251.0']
        assert any(e.get('action')=='GO' and e.get('reason')=='permission_not_crossing' for e in rows)
        assert any(e.get('reason')=='passage_control_or_crossing_wait' for e in rows)
        historical.extend(rows)
    (folder/'historical-251.json').write_text(json.dumps(historical,indent=2)+'\n')
    props={}
    links={l.get('id'):l for l in ET.parse(RUN/'inputs/transit-weekday/network.xml').findall('.//link')}
    controlled=set()
    for e in ET.parse(RUN/'inputs/signalsystems-signalsystems.xml').iter():
        if e.tag.split('}')[-1]=='linkId':controlled.add(links[e.get('refId')].get('to'))
    assert not controlled.intersection({'4074069083','579746301'})
    props['controlled']=','.join(sorted(controlled))
    props['network']=(RUN/'inputs/transit-weekday/network.xml').as_posix()
    props['lanes']=(RUN/'inputs/transit-weekday/lanes.xml').as_posix()
    config=json.loads((DIAG/'effective_config_summary.json').read_text())['runtime_relevant']
    for key in ('classification','conflicts','stopSeconds','maxYieldSeconds'):props[key]=config['zona1Priority.'+key]
    for case,vehicle,start in [('A','z1_106044','osm_406654687_6_forward'),('B','z1_49500','osm_381667651_3_forward')]:
        person=ET.fromstring(evidence['early_case_plans.json'][vehicle]);route=person.find('.//route').text.split();route=route[route.index(start):]
        props['path'+case]=','.join(route)
        attrs={a.get('name'):a.text for a in person.findall('./attributes/attribute')}
        props['speed'+case]=attrs['simz1MaximumVelocityMps']
        state=evidence['focus_state_history.json'][0]['cases'][vehicle]
        props['laneEntry'+case]=state['last_lane_event']['time']
        props['earliestExit'+case]=state['first_storage_since_move']['earliestLinkExitTime']
    props['nativeLinks']=','.join(sorted({'osm_406654687_5_forward'}|{lid for item in evidence['early_dependency.json']['storage'] for lid in item['domain']['links'].split(',')}))
    (folder/'fixture.properties').write_text('\n'.join(k+'='+v for k,v in props.items())+'\n',encoding='utf8')
    return evidence

def main():
    from test_simz1_sequence_contract import receipt_snapshot
    receipt_start_sha=receipt_snapshot(ROOT)
    folder=Path(tempfile.mkdtemp(prefix='c529-a-',dir=ROOT/'runtime'));print('C529_A_ARTIFACTS='+str(folder),flush=True)
    preserved=list(DIAG.glob('*'))+list((ROOT/'runtime/workflow').glob('*'))+[RUN/'run-manifest.json',RUN/'inputs/transit-weekday/network.xml',RUN/'inputs/transit-weekday/lanes.xml']+list((RUN/'inputs').glob('signalsystems-*.xml'))
    before={p:sha(p) for p in preserved if p.is_file()}
    evidence=prepare(folder)
    java=Path(os.environ.get('SIMZ1_JDK17',r'C:\Program Files\Java\jdk-17'))/'bin'
    cp=str(ROOT/'target/classes')+os.pathsep+str(ROOT/'target/test-classes')+os.pathsep+(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()
    results=[]
    def command(label,args):
        p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
        (folder/(label+'.log')).write_text(p.stdout+p.stderr,encoding='utf8');results.append(dict(check=label,command=args,exit=p.returncode))
        (folder/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf8')
        if p.returncode:raise AssertionError(label+' failed: '+(p.stdout+p.stderr)[-6000:])
        print(label+': exit=0',flush=True)
        return p.stdout+p.stderr
    try:
        assert 'version "17.' in command('java-version',[str(java/'java.exe'),'-version']),'Requires JDK17'
        names=PRODUCTION+['src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/'+n+'.java' for n in [*CHECKS,'SimZ1PassageCycleCheck','SimZ1PassageAffectedChecks','SimZ1CorridorOccupancyCheck','SimZ1ParallelPassagePriorityCheck','SimZ1PassageTimerCheck','SimZ1CrossingClearanceCheck','SimZ1StorageFixture']]
        (folder/'empty').mkdir()
        command('compile',[str(java/'javac.exe'),'--release','17','-encoding','UTF-8','-proc:none','-cp',cp,'-sourcepath',str(folder/'empty'),'-d',str(folder),*[str(ROOT/n) for n in names]])
        (folder/'sources.json').write_text(json.dumps({n:sha(ROOT/n) for n in names},indent=2)+'\n')
        command('cycle',[str(java/'java.exe'),'-Xmx512m','-cp',str(folder)+os.pathsep+cp,JAVA_PACKAGE+'SimZ1PassageCycleCheck',str(folder)])
        baseline=folder/'baseline';baseline.mkdir();historical={r['path']:r['sha256'] for r in evidence['code_sources.json']}
        for name in PRODUCTION:
            raw=subprocess.run(['git','show',BASELINE+':'+name],cwd=ROOT,capture_output=True,check=True).stdout
            if hashlib.sha256(raw).hexdigest()!=historical[name]:raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            assert hashlib.sha256(raw).hexdigest()==historical[name],name+' does not match C529 historical source'
            (baseline/Path(name).name).write_bytes(raw)
        command('baseline-compile',[str(java/'javac.exe'),'--release','17','-encoding','UTF-8','-proc:none','-cp',cp,'-sourcepath',str(folder/'empty'),'-d',str(baseline),*[str(baseline/Path(n).name) for n in PRODUCTION],str(ROOT/'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1PassageCycleCheck.java')])
        command('baseline-cycle',[str(java/'java.exe'),'-Xmx512m','-cp',str(baseline)+os.pathsep+cp,JAVA_PACKAGE+'SimZ1PassageCycleCheck',str(folder),'before'])
        for name in CHECKS:
            command(name,[str(java/'java.exe'),'-Xmx512m','-cp',str(folder)+os.pathsep+cp,JAVA_PACKAGE+name])
        for part in ('ledger','parallel','clearance','timers'):
            command('existing-'+part,[str(java/'java.exe'),'-Xmx512m','-cp',str(folder)+os.pathsep+cp,JAVA_PACKAGE+'SimZ1PassageAffectedChecks',part])
        integration_checks(folder,receipt_start_sha)
        command('protected-source-mutations',[sys.executable,'-B','-c',
            "import sys,unittest; sys.path.insert(0,'python'); from test_simz1_sequence_contract import ProtectedSourceExpectationTests; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProtectedSourceExpectationTests)); sys.exit(not r.wasSuccessful())"])
    finally:
        after={p:sha(p) for p in before}
        (folder/'preservation.json').write_text(json.dumps(dict(before={str(p.relative_to(ROOT)):v for p,v in before.items()},after={str(p.relative_to(ROOT)):v for p,v in after.items()}),indent=2)+'\n')
        assert before==after,'Historical evidence or approval receipts changed'

if __name__=='__main__':main()
