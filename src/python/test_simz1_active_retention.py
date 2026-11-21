"""C529-C: completed-observation expiry and live native receiver retention.
Only JDK17 component fixtures. --with-routing-regressions also runs focal C529-B.
Never starts a simulation or writes approval/arrival/completed-run artifacts.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from test_simz1_native_od import ROOT, DIAG, RUN, BASELINE, PRODUCTION, sha, write

PACKAGE='gt.edu.uvg.sim.zona1.'
REROUTING='src/main/java/gt/edu/uvg/sim/zona1/CongestionAwareRerouting.java'
CHECKS=['src/test/java/gt/edu/uvg/sim/zona1/'+n+'.java' for n in ('SimZ1RetentionBeforeCheck','SimZ1RetentionCheck')]
FIXTURE='src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1RetentionFixture.java'
COMPANIONS=['src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java']+[
    'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/'+n+'.java' for n in ('SimZ1CorridorOccupancy','Zona1QNodeImpl')]

def evidence(folder):
    summary=json.loads((DIAG/'routing_observation_summary.json').read_bytes())
    decisions=json.loads((DIAG/'rerouting_decisions_summary.json').read_bytes())
    with (DIAG/'reroute_trigger_timeline.csv').open(encoding='utf-8-sig',newline='') as f:
        timeline=[r for r in csv.DictReader(f) if float(r['time']) in (31920,31980)]
    assert len(timeline)==2 and [int(r['severe_links']) for r in timeline]==[6,0]
    assert all(int(r['budget'])==100 for r in timeline)
    assert int(timeline[1]['calculations'])==0 and int(timeline[1]['candidates'])==0
    sample=summary['last_severe']['links']['osm_1057486080_2_forward']
    assert sample['duration']==209 and sample['observed_at']==31658
    assert 31920-sample['observed_at']<=300<31980-sample['observed_at']
    assert decisions['cohort_size']==89100
    heads={name:decisions['cases'][name]['selected'] for name in ('z1_106044','z1_49500')}
    assert not any(heads.values())
    assert '31980' in (DIAG/'DIAGNOSTICO_C529.md').read_text(encoding='utf8')
    assert 'CongestionAwareRerouting' in (DIAG/'code_excerpts.txt').read_text(encoding='utf8')
    write(folder/'historical-evidence.json',dict(timeline=timeline,completed_sample=sample,initial_heads_selected=heads,
        source='existing C529 summaries only; no historical event rescan or simulation',
        source_sha256={p.name:sha(p) for p in DIAG.iterdir() if p.is_file()}))

def integration(folder,receipt_start_sha):
    from test_simz1_sequence_contract import check_protected_sources,HERE
    from simz1_workflow_state import fingerprint
    checked=check_protected_sources(ROOT,json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256'],receipt_start_sha)
    workflow=(ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf8')
    assert workflow.index('python\\test_simz1_native_od.py')<workflow.index('python\\test_simz1_active_retention.py')<workflow.index("'validated-source.txt'")
    changed=[REROUTING,'src/main/java/gt/edu/uvg/sim/zona1/SimZ1ActiveRetention.java',*CHECKS,FIXTURE,
        'python/test_simz1_active_retention.py','python/test_simz1_native_od.py','python/test_simz1_sequence_contract.py','scripts/simz1_workflow.ps1']
    from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
    fixed=list(REQUIRED_FIXTURE_FILES)
    synthetic=folder/'fingerprint';synthetic.mkdir()
    for name in fixed+changed:
        p=synthetic/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
    for name in changed:
        before=fingerprint(synthetic);(synthetic/name).write_text('changed');assert before!=fingerprint(synthetic),name
    write(folder/'integration.json',dict(protected_sources_checked=checked,fingerprinted=changed,
        validate_invokes_after_C529_B=True,validate_executed=False,approval_written=False))

def main():
    from test_simz1_sequence_contract import receipt_snapshot
    receipt_start_sha=receipt_snapshot(ROOT)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--with-routing-regressions',action='store_true');args=parser.parse_args()
    folder=Path(tempfile.mkdtemp(prefix='c529-c-',dir=ROOT/'runtime'));print('Evidence:',folder,flush=True)
    # These component fixtures consume exact plan fragments in DIAG, not the
    # disposable complete population. Preserve all of their real inputs.
    preserved=[p for p in DIAG.iterdir() if p.is_file()]+[RUN/'run-manifest.json',RUN/'config-simz1.xml',
        ROOT/'runtime/workflow/validated-balanced-gateway-v1.json',ROOT/'runtime/workflow/validated-source.txt',ROOT/'python/simz1_balanced_od_audit.py']
    # A unchanged; B routing/OD sources unchanged except the authorized retention integration.
    preserved += [ROOT/p for p in COMPANIONS+PRODUCTION if p!=REROUTING and not p.endswith('SimZ1ActiveRetention.java')]
    before={str(p.relative_to(ROOT)):sha(p) for p in preserved if p.is_file()};steps=[];ok=False
    def command(name,arguments,timeout=60):
        p=subprocess.run(list(map(str,arguments)),cwd=ROOT,capture_output=True,text=True,timeout=timeout)
        (folder/(name+'.log')).write_text(p.stdout+p.stderr,encoding='utf8');steps.append(dict(name=name,exit_code=p.returncode,command=list(map(str,arguments))))
        print(name+': exit '+str(p.returncode),flush=True)
        if p.returncode:raise AssertionError((p.stdout+p.stderr)[-6000:])
    try:
        evidence(folder);java=Path(r'C:\Program Files\Java\jdk-17\bin')
        cp=os.pathsep.join([str(ROOT/'target/classes'),str(ROOT/'target/test-classes'),(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()])
        empty=folder/'empty';empty.mkdir();old=folder/'before';old.mkdir();new=folder/'after';new.mkdir()
        sources={r['path']:r['sha256'] for r in json.loads((DIAG/'code_sources.json').read_bytes())}
        original=subprocess.check_output(['git','show',BASELINE+':'+REROUTING],cwd=ROOT)
        if hashlib.sha256(original).hexdigest()!=sources[REROUTING]:original=original.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        assert hashlib.sha256(original).hexdigest()==sources[REROUTING]
        (old/'CongestionAwareRerouting.java').write_bytes(original)
        write(folder/'before-source.json',dict(revision=BASELINE,path=REROUTING,sha256=sources[REROUTING],
            scope='exact historical detector; isolated compilation, no production rollback; native controls retain C529-A'))
        common=[ROOT/p for p in PRODUCTION+COMPANIONS if p not in (REROUTING,'src/main/java/gt/edu/uvg/sim/zona1/SimZ1ActiveRetention.java')]
        def compile(name,out,files):command(name,[java/'javac.exe','--release','17','-encoding','UTF-8','-proc:none','-cp',cp,'-sourcepath',empty,'-d',out,*files])
        def run(name,out,clazz):command(name,[java/'java.exe','-Xmx768m','-cp',os.pathsep.join([str(out),str(ROOT/'src/main/resources'),cp]),PACKAGE+clazz])
        compile('before-compile',old,[old/'CongestionAwareRerouting.java',*common,ROOT/FIXTURE,ROOT/CHECKS[0]])
        run('before',old,'SimZ1RetentionBeforeCheck')
        compile('after-compile',new,[ROOT/p for p in PRODUCTION+COMPANIONS+CHECKS+[FIXTURE]])
        run('after',new,'SimZ1RetentionCheck')
        integration(folder,receipt_start_sha)
        if args.with_routing_regressions:
            command('C529-B-routing-regressions',[sys.executable,'-B','python/test_simz1_native_od.py'],180)
        ok=True
    finally:
        unchanged={name:sha(ROOT/name)==digest for name,digest in before.items()};assert all(unchanged.values()),unchanged
        write(folder/'focused-results.json',dict(status='PASS' if ok else 'FAIL',commands=steps,unchanged_sources=unchanged,
            controller_started=False,qsim_run=False,validate_executed=False,approval_written=False,
            scope='C529-C focal component evidence; does not establish network clearance, arrivals or 180000 approval'))
    return 0

if __name__=='__main__':sys.exit(main())
