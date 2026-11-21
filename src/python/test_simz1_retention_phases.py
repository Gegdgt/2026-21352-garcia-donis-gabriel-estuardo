"""C529-D: native 80s phases and one production reroute installer, no simulation.
--with-routing-regressions also runs the affected C529-B Java/Python checks.
All outputs are component evidence, never approvals or completed-run artifacts.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from test_simz1_native_od import ROOT, DIAG, RUN, PRODUCTION, sha, write
from test_simz1_active_retention import COMPANIONS

BASELINE='340657007640f3c5e7a55d3dbdca39a63d48f09b'
JAVA='src/main/java/gt/edu/uvg/sim/zona1/'
TEST='src/test/java/gt/edu/uvg/sim/zona1/'
NATIVE='src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/'
BEFORE={JAVA+'SimZ1ActiveRetention.java':'f38c6d72350c8134d18719db9f853cbed9e6acec6530d1250e6e4a3a3ac1aa50',
        JAVA+'CongestionAwareRerouting.java':'fb8665999316ff2e913bf87ea56e46444f24941ad14e05f3f829c1f7c164da00'}
PHASE=[NATIVE+'SimZ1RetentionFixture.java',NATIVE+'SimZ1RetentionPhases.java',TEST+'SimZ1RetentionPhaseCheck.java']
EXTRA=[TEST+n+'.java' for n in ('SimZ1RetentionCheck','SimZ1RetentionLifecycleCheck','SimZ1RetentionInstallationCheck')]+[
       NATIVE+'SimZ1RetentionInstallationFixture.java',NATIVE+'SimZ1OpposedReturnRerouteCheck.java']
SIGNAL='scenarios/zona1/od/balanced-gateway-v1/access-review-v2/signalControl.xml'

def integration(folder,receipt_start_sha):
    from test_simz1_sequence_contract import check_protected_sources,HERE
    from simz1_workflow_state import fingerprint
    checked=check_protected_sources(ROOT,json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256'],receipt_start_sha)
    workflow=(ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf8')
    assert workflow.index('python\\test_simz1_active_retention.py')<workflow.index('python\\test_simz1_retention_phases.py')<workflow.index("'validated-source.txt'")
    names=[*BEFORE,*PHASE,*EXTRA,'python/test_simz1_retention_phases.py','python/test_simz1_sequence_contract.py','scripts/simz1_workflow.ps1']
    from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
    fixed=list(REQUIRED_FIXTURE_FILES)
    synthetic=folder/'fingerprint';synthetic.mkdir()
    for name in fixed+names:
        p=synthetic/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic fingerprint input')
    for name in names:
        before=fingerprint(synthetic);(synthetic/name).write_text('mutated');assert before!=fingerprint(synthetic),name
    write(folder/'integration.json',dict(protected_sources_checked=checked,fingerprinted=names,
        validate_calls_D_after_C=True,validate_executed=False,approval_written=False))

def signal_evidence(folder):
    root=ET.parse(ROOT/SIGNAL).getroot();ns={'s':'http://www.matsim.org/files/dtd'}
    systems=root.findall('s:signalSystem',ns);counts=Counter()
    for system in systems:
        for plan in system.findall('.//s:signalPlan',ns):
            assert plan.find('s:cycleTime',ns).get('sec')=='80'
            for group in plan.findall('s:signalGroupSettings',ns):
                counts[(int(group.find('s:onset',ns).get('sec')),int(group.find('s:dropping',ns).get('sec')))]+=1
    assert len(systems)==163 and counts=={(0,47):155,(49,78):150},counts
    write(folder/'signal-evidence.json',dict(source=SIGNAL,sha256=sha(ROOT/SIGNAL),systems=len(systems),groups=sum(counts.values()),
        intervals=[dict(onset=a,dropping=b,count=n,cycle=80) for (a,b),n in sorted(counts.items())],
        interpretation='Native green+amber permission is within onset..dropping; not extra amber after dropping'))

def main():
    from test_simz1_sequence_contract import receipt_snapshot
    receipt_start_sha=receipt_snapshot(ROOT)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--with-routing-regressions',action='store_true');args=parser.parse_args()
    folder=Path(tempfile.mkdtemp(prefix='c529-d-',dir=ROOT/'runtime'));print('Evidence:',folder,flush=True)
    # Read-only evidence, all receipts, and unchanged A/B controls are pinned for this suite.
    # Native component checks use the preserved exact plan fragments in DIAG;
    # no phase reads the old massive population.
    preserved=[p for p in DIAG.iterdir() if p.is_file()]+[RUN/n for n in ('run-manifest.json','config-simz1.xml')]
    preserved += [p for p in (ROOT/'runtime/workflow').rglob('*') if p.is_file()]
    preserved += [ROOT/p for p in COMPANIONS+PRODUCTION if p not in BEFORE]
    preserved += [ROOT/SIGNAL,ROOT/'python/simz1_balanced_od_audit.py',ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/preserved-input-hashes.json']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in preserved};steps=[];ok=False
    def command(name,arguments,timeout=60,expected=0,contains=None):
        p=subprocess.run(list(map(str,arguments)),cwd=ROOT,capture_output=True,text=True,timeout=timeout)
        output=p.stdout+p.stderr;(folder/(name+'.log')).write_text(output,encoding='utf8')
        steps.append(dict(name=name,exit_code=p.returncode,expected_exit_code=expected,command=list(map(str,arguments))))
        print(name+': exit '+str(p.returncode)+(' (expected rejection)' if expected else ''),flush=True)
        if p.returncode!=expected or contains and contains not in output:raise AssertionError(output[-6000:])
    try:
        signal_evidence(folder);java=Path(r'C:\Program Files\Java\jdk-17\bin')
        command('JDK17',[java/'java.exe','-version'],contains='version "17.')
        cp=os.pathsep.join([str(ROOT/'target/classes'),str(ROOT/'target/test-classes'),(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()])
        empty=folder/'empty';empty.mkdir();old=folder/'before';old.mkdir();new=folder/'after';new.mkdir()
        for name,digest in BEFORE.items():
            source=subprocess.check_output(['git','show',BASELINE+':'+name],cwd=ROOT)
            if hashlib.sha256(source).hexdigest()!=digest:source=source.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            assert hashlib.sha256(source).hexdigest()==digest,name
            (old/Path(name).name).write_bytes(source)
        write(folder/'before-sources.json',dict(revision=BASELINE,sha256=BEFORE,scope='C529-C committed production, isolated compilation without rollback'))
        def compile(name,out,files,classpath=cp):command(name,[java/'javac.exe','--release','17','-encoding','UTF-8','-proc:none','-cp',classpath,'-sourcepath',empty,'-d',out,*files])
        def run(name,out,clazz,*params,expected=0,contains=None):
            classpath=os.pathsep.join([str(out),str(new),str(ROOT/'src/main/resources'),cp])
            command(name,[java/'java.exe','-Xmx768m','-cp',classpath,'gt.edu.uvg.sim.zona1.'+clazz,*params],expected=expected,contains=contains)
        common=[ROOT/p for p in PRODUCTION+COMPANIONS if p not in BEFORE]
        compile('before-compile',old,[old/Path(p).name for p in BEFORE]+common+[ROOT/p for p in PHASE])
        run('before-phases',old,'SimZ1RetentionPhaseCheck',old,'before')
        compile('after-compile',new,[ROOT/p for p in PRODUCTION+COMPANIONS+PHASE+EXTRA])
        run('after-phases',new,'SimZ1RetentionPhaseCheck',new,'after')
        run('lifecycle',new,'SimZ1RetentionLifecycleCheck')
        run('installation',new,'SimZ1RetentionInstallationCheck',new)
        run('C529-C-regression',new,'SimZ1RetentionCheck')
        # Behavioural mutants are isolated classes, never edits of protected production.
        active=JAVA+'SimZ1ActiveRetention.java';reroute=JAVA+'CongestionAwareRerouting.java'
        mutants=[('red-clears',active,'if(signalPause)return new Wait','if(signalPause)return null;\n            if(false)return new Wait','SimZ1RetentionPhaseCheck','Physical accumulation differs'),
                 ('red-credited',active,'old.started,now,old.accumulatedSeconds,true','old.started,now,old.accumulatedSeconds+gap,true','SimZ1RetentionPhaseCheck','Physical accumulation differs'),
                 ('reservation-bypassed',reroute,'candidate,index,network));\n        if(invalid!=null)', 'candidate,index,network));\n        invalid=null; // isolated mutation\n        if(invalid!=null)','SimZ1RetentionInstallationCheck','Expected actual reservation rejection')]
        for name,path,needle,replacement,clazz,message in mutants:
            mutation=folder/('mutation-'+name);mutation.mkdir();source=(ROOT/path).read_text(encoding='utf8');assert source.count(needle)==1
            altered=mutation/Path(path).name;altered.write_text(source.replace(needle,replacement),encoding='utf8')
            compile(name+'-compile',mutation,[altered],os.pathsep.join([str(new),cp]))
            params=[mutation,'after'] if clazz=='SimZ1RetentionPhaseCheck' else [mutation]
            run(name,mutation,clazz,*params,expected=1,contains=message)
        integration(folder,receipt_start_sha)
        command('protected-mutations',[sys.executable,'-B','-m','unittest','discover','-s','python','-p','test_simz1_sequence_contract.py','-k','ProtectedSourceExpectationTests','-v'])
        if args.with_routing_regressions:command('C529-B-routing-regressions',[sys.executable,'-B','python/test_simz1_native_od.py'],180)
        ok=True
    finally:
        unchanged={name:sha(ROOT/name)==digest for name,digest in hashes.items()}
        write(folder/'focused-results.json',dict(status='PASS' if ok and all(unchanged.values()) else 'FAIL',commands=steps,unchanged_sources=unchanged,
            controller_started=False,qsim_run=False,validate_executed=False,approval_written=False,
            scope='Component evidence only: no full-network clearance, certified arrival or 180000 approval'))
        assert all(unchanged.values()),unchanged
    return 0

if __name__=='__main__':sys.exit(main())
