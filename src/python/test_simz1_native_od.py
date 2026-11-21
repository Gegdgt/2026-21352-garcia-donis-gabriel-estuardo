from simz1_history_fixtures import dataset, materialize
"""C529-B: exact historical counterexample and small native routing fixtures only.
No Controller, QSim.run, population generation, approval or arrival certificates.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
DIAG=dataset('c529-evidence')
RUN=materialize('c529')
BASELINE='91d3ffce66bee80da3f0450e9d98a5a0316b3ec7'
PACKAGE='gt.edu.uvg.sim.zona1.'
NAMES=('SimZ1TripOd','SimZ1RouteSafety','SimZ1TurnRouter','CongestionAwareRerouting','ExperiencedTimeRouting','SimZ1ActiveRetention')
PRODUCTION=[f'src/main/java/gt/edu/uvg/sim/zona1/{n}.java' for n in NAMES]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
def gateway(name,chain,cross,entry):return dict(id=name,anchor_link=chain[0 if entry else -1],observation_link=chain[-1 if entry else 0],crossing_link=cross,link_ids=chain)

def prepare(folder):
    manifest=json.loads((RUN/'run-manifest.json').read_bytes())
    m=json.loads((DIAG/'monitor_first_rejection.json').read_bytes());reroute=m['last_reroute']
    assert m['uncached_original_method_rejection'] and reroute['time']=='720.0'
    def route(value):return value.strip('[]').split(', ')
    xml=ET.fromstring(json.loads((DIAG/'early_case_plans.json').read_bytes())['z1_60650'])
    attrs={e.get('name'):e.text for e in xml.findall('./attributes/attribute')}
    trip=xml.find('.//leg/attributes/attribute[@name="simz1TripId"]').text
    historical=dict(name='historical_z1_60650',run=str(RUN),network=str(RUN/'inputs/transit-weekday/network.xml'),
        lanes=str(RUN/'inputs/transit-weekday/lanes.xml'),person='z1_60650',trip=trip,attributes=attrs,
        old=route(reroute['oldRoute']),candidate=route(reroute['candidateRoute']),index=int(reroute['routeIndex']),lane=reroute['lane'],accepted=False)
    assert trip=='z1_60650:trip:0001' and historical['index']==2
    assert historical['old']==m['record']['route_link_ids']
    write(folder/'historical.json',historical)
    # Read the cited diagnostic summaries as evidence, not as rerun instructions.
    assert 'z1_60650' in (DIAG/'DIAGNOSTICO_C529.md').read_text(encoding='utf8')
    assert 'CongestionAwareRerouting' in (DIAG/'code_excerpts.txt').read_text(encoding='utf8')
    json.loads((DIAG/'rerouting_decisions_summary.json').read_bytes())
    entry=gateway('entry-eC',['e0','eC','eI'],'eC',True)
    exit_=gateway('exit-xC',['xI','xC','xE'],'xC',False)
    edges=[('e0','0','1',10),('eC','1','2',10),('eI','2','3',10),('i','3','4',10),('j','4','5',10),
        ('xI','5','6',10),('xC','6','7',10),('xE','7','8',10),('wrong','5','6',1),('outside','5','6',1),
        ('loop','4','3',10),('return','6','4',10),('other-eI','2','3',1)]
    interior=['eI','i','j','xI','wrong','loop','return']
    spatial=dict(mode='balanced-gateway-v1',allowed_links=[e[0] for e in edges if e[0]!='outside'],internal_links=['i','j','wrong','loop','return'],
        internal_origins={'i':{}},entry_gateways={'e0':entry},exit_gateways={'xE':exit_})
    from simz1_od_policy import CLASS_BY_TYPE
    def case(name,kind,old,candidate,index,spatial):
        origin,destination=old[0],old[-1];en=spatial['entry_gateways'].get(origin);ex=spatial['exit_gateways'].get(destination)
        metadata=dict(od_type=kind,od_class=CLASS_BY_TYPE[kind],origin_link=origin,destination_link=destination,
            origin_gateway=origin if en else None,destination_gateway=destination if ex else None,
            origin_zone=en['id'] if en else None,destination_zone=ex['id'] if ex else None,
            origin_observation_link=en['observation_link'] if en else None,destination_observation_link=ex['observation_link'] if ex else None,
            entry_crossing_link=en['crossing_link'] if en else None,exit_crossing_link=ex['crossing_link'] if ex else None,
            scope='observed_z1_and_declared_anchors_only',door_to_door_seconds=None,metadata_source='simz1-private-gateway-trip-v1',
            route_link_ids=old,body_length_m=4.5,minimum_gap_m=.1)
        trip=name+':trip:0001'
        return dict(name=name,person=name,trip=trip,old=old,candidate=candidate,index=index,accepted=old==candidate,
            attributes=dict(simz1SpatialOD=json.dumps({trip:metadata}),simz1Trips=json.dumps([dict(id=trip,index=1,origin_link=origin,destination_link=destination,planned_departure=0)])))
    old=['e0','eC','eI','i','j','xI','xC','xE'];bad=old[:5]+['wrong','xC','xE']
    cases=[case(name,'external-external',old,bad,index,spatial) for name,index in [('entry_pending',1),('entry_completed',3),('before_exit',4)]]
    cases.append(case('skip_entry','external-external',old,['e0','eC','other-eI']+old[3:],1,spatial))
    cases.append(case('within_exit','external-external',old,old,6,spatial))
    repeated=old[:4]+['loop','i']+old[4:]
    cases.append(case('second_occurrence','external-external',repeated,repeated,5,spatial))
    repeated_exit=old[:6]+['return','j','xI']+old[6:]
    cases.append(case('repeated_exit_observation','external-external',repeated_exit,repeated_exit,8,spatial))
    cases.append(case('outside_domain','external-external',old,old[:5]+['outside','xC','xE'],4,spatial))
    for kind,path in [('internal-internal',['i','j']),('internal-external',old[3:]),('external-internal',old[:5])]:
        cases.append(case(kind,kind,path,path,0,spatial))
    synthetic=dict(edges=edges,spatial=spatial,cases=cases);write(folder/'synthetic.json',synthetic)
    from test_simz1_sequence_contract import A,V,B,C
    en=gateway('seq-entry',['s0','sC','sI'],'sC',True);ex=gateway('seq-exit',[V,B,'sE'],B,False)
    edges2=[('s0','0','1',10),('sC','1','2',10),('sI','2','a',10),(A,'a','j',10),
        ('H','j','c',50),(C,'c','j',50),(V,'j','v',10),(B,'v','m',10),('sE','m','end',10)]
    spatial2=dict(mode='balanced-gateway-v1',allowed_links=[e[0] for e in edges2],internal_links=[A,'H',C],internal_origins={A:{}},entry_gateways={'s0':en},exit_gateways={'sE':ex})
    path2=['s0','sC','sI',A,'H',C,V,B,'sE'];bad2=['s0','sC','sI',A,V,B,'sE']
    seq=case('sequence_17478998_join','external-external',path2,bad2,3,spatial2);seq['forbidden_prefix']=['s0','sC','sI',A,V]
    sequence=dict(edges=edges2,spatial=spatial2,cases=[seq]);write(folder/'sequence.json',sequence)
    return historical,synthetic,sequence,manifest

def auditor_parity(folder,historical,synthetic,sequence,manifest):
    from simz1_balanced_od import BalancedGatewayModel, model_from_document
    from simz1_balanced_od_audit import PrivateODAudit
    from simz1_sequence_contract import SequenceContract
    # Source evidence hashes are checked; construct only the effective graph, no population/audited arrivals.
    for key in ('network','zone_boundary','od_source_osm'):
        ref=manifest['inputs'][key];assert sha(RUN/ref['path'])==ref['sha256']
    ref=manifest['balanced_od']['access_catalog'];access=RUN/ref['path'];assert sha(access)==ref['sha256']
    model=model_from_document(historical['network'],RUN/manifest['inputs']['zone_boundary']['path'],historical['lanes'],
        RUN/manifest['inputs']['od_source_osm']['path'],access,json.loads(access.read_bytes()),'EPSG:32615')
    projected=set(manifest['spatial_demand']['allowed_links'])
    for table,entry in ((model.entry_gateways,True),(model.exit_gateways,False)):
        for row in table.values():
            chain=row['link_ids'];at=chain.index(row['crossing_link']);projected.difference_update(chain[:at+1] if entry else chain[at:])
    assert projected==model.interior,'Java manifest-domain projection differs from original Python geometry model'
    outputs={r['name']:r for r in json.loads((folder/'java-cases.json').read_bytes())}
    comparisons=[]
    def compare(model,row):
        metadata=json.loads(row['attributes']['simz1SpatialOD'])[row['trip']]
        record=metadata
        audit=PrivateODAudit(model,{row['trip']:record})
        for name in (row['name'],row['name']+'_alternative'):
            result=outputs[name];reason=None
            try:audit.validate_observed_route(row['trip'],result['path'],complete=True)
            except ValueError as e:reason=str(e)
            assert (reason is None)==result['accepted'],(name,reason,result)
            if name=='historical_z1_60650':assert reason=='Private route skipped part of its verified exit chain'
            comparisons.append(dict(name=name,accepted=reason is None,reason=reason))
    compare(model,historical)
    for fixture in (synthetic,sequence):
        model=BalancedGatewayModel.__new__(BalancedGatewayModel);model.sequences=SequenceContract()
        model.links={k:dict(from_node=a,to_node=b,length=length,freespeed=10) for k,a,b,length in fixture['edges']}
        model.lane_movements={k:{b for b,row in model.links.items() if row['from_node']==v['to_node']} for k,v in model.links.items()}
        spatial=fixture['spatial'];model.entry_gateways=spatial['entry_gateways'];model.exit_gateways=spatial['exit_gateways']
        model.interior=set(spatial['allowed_links']);model.classification=dict.fromkeys(model.links,'interior')
        for table,entry in ((model.entry_gateways,True),(model.exit_gateways,False)):
            for row in table.values():
                chain=row['link_ids'];at=chain.index(row['crossing_link']);model.interior.difference_update(chain[:at+1] if entry else chain[at:])
                model.classification[row['crossing_link']]='entry_crossing' if entry else 'exit_crossing'
        model.internal_links=spatial['internal_links']
        for row in fixture['cases']:compare(model,row)
    write(folder/'python-parity.json',dict(cases=comparisons,original_auditor_unchanged=True,synthetic_routes_only=True))
    print(f'original Python auditor parity: PASS ({len(comparisons)} routes)',flush=True)

def main():
    from test_simz1_sequence_contract import receipt_snapshot
    receipt_start_sha=receipt_snapshot(ROOT)
    folder=Path(tempfile.mkdtemp(prefix='c529-b-',dir=ROOT/'runtime'));print('Evidence:',folder,flush=True)
    evidence=[*DIAG.iterdir(),RUN/'run-manifest.json',RUN/'config-simz1.xml',ROOT/'runtime/workflow/validated-balanced-gateway-v1.json',ROOT/'runtime/workflow/validated-source.txt',ROOT/'python/simz1_balanced_od_audit.py']
    evidence=[p for p in evidence if p.is_file()];before={str(p.relative_to(ROOT)):sha(p) for p in evidence}
    for n in ('UnsignalizedPriority','SimZ1CorridorOccupancy','Zona1QNodeImpl'):
        p=ROOT/('src/main/java/gt/edu/uvg/sim/zona1/' if n=='UnsignalizedPriority' else 'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/')/(n+'.java');before[str(p.relative_to(ROOT))]=sha(p)
    steps=[]
    def command(name,args,timeout=90):
        p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=timeout);(folder/(name+'.log')).write_text(p.stdout+p.stderr,encoding='utf8')
        steps.append(dict(name=name,exit_code=p.returncode,command=list(map(str,args))));print(name+': exit '+str(p.returncode),flush=True)
        if p.returncode:raise AssertionError((p.stdout+p.stderr)[-7000:])
    ok=False
    try:
        data=prepare(folder);java=Path(r'C:\Program Files\Java\jdk-17\bin')
        cp=os.pathsep.join([str(ROOT/'target/classes'),str(ROOT/'target/test-classes'),(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()])
        empty=folder/'empty';empty.mkdir();baseline=folder/'before';baseline.mkdir();after=folder/'after';after.mkdir()
        sources={r['path']:r['sha256'] for r in json.loads((DIAG/'code_sources.json').read_bytes())}
        for name in PRODUCTION[1:5]:
            blob=subprocess.check_output(['git','show',BASELINE+':'+name],cwd=ROOT)
            if hashlib.sha256(blob).hexdigest()!=sources[name]:blob=blob.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            assert hashlib.sha256(blob).hexdigest()==sources[name],name
            (baseline/Path(name).name).write_bytes(blob)
        checks=[ROOT/f'src/test/java/gt/edu/uvg/sim/zona1/{n}.java' for n in ('SimZ1OdHistoricalBeforeCheck','SimZ1OdContractCheck','RouteSafetyCheck','FastestTimeRoutingCheck','GatewayRouteSafetyCheck')]
        probe=ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/Restriction17478998Probe.java'
        command('before-compile',[str(java/'javac.exe'),'--release','17','-encoding','UTF-8','-proc:none','-cp',cp,'-sourcepath',str(empty),'-d',str(baseline),*[str(p) for p in baseline.glob('*.java')],str(checks[0])])
        def run(name,classes,clazz,*args):command(name,[str(java/'java.exe'),'-Xmx768m','-cp',os.pathsep.join([str(classes),str(ROOT/'src/main/resources'),cp]),clazz,*map(str,args)])
        run('before',baseline,PACKAGE+'SimZ1OdHistoricalBeforeCheck',folder/'historical.json')
        companions=[ROOT/'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1OdReservationsCheck.java']
        companions += [ROOT/'src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java']
        companions += [ROOT/f'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/{n}.java' for n in ('SimZ1CorridorOccupancy','Zona1QNodeImpl')]
        command('after-compile',[str(java/'javac.exe'),'--release','17','-encoding','UTF-8','-proc:none','-cp',cp,'-sourcepath',str(empty),'-d',str(after),*[str(ROOT/p) for p in PRODUCTION],*map(str,checks),str(probe),*map(str,companions)])
        run('after',after,PACKAGE+'SimZ1OdContractCheck',folder)
        auditor_parity(folder,*data)
        for name in ('RouteSafetyCheck','FastestTimeRoutingCheck','GatewayRouteSafetyCheck','Restriction17478998Probe'):
            run(name,after,PACKAGE+name)
        # These mains are component fixtures, not their similarly named simulation suites.
        for name in ('SimZ1OpposedReturnRerouteCheck','SimZ1ReturnSignalRerouteCheck','SimZ1OdReservationsCheck'):
            run(name,after,'org.matsim.core.mobsim.qsim.qnetsimengine.'+name)
        integration(folder,command,receipt_start_sha)
        ok=True
    finally:
        unchanged={name:sha(ROOT/name)==digest for name,digest in before.items()};assert all(unchanged.values()),unchanged
        write(folder/'focused-results.json',dict(status='PASS' if ok else 'FAIL',commands=steps,unchanged_sources=unchanged,
            controller_started=False,qsim_run=False,validate_executed=False,approval_written=False,
            scope='C529-B focal routing only; no simulation result or 180000 approval'))
    return 0

def integration(folder,command,receipt_start_sha):
    from test_simz1_sequence_contract import check_protected_sources,HERE
    from simz1_workflow_state import fingerprint
    baseline=json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256']
    checked=check_protected_sources(ROOT,baseline,receipt_start_sha)
    workflow=(ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf8');assert workflow.index('python\\test_simz1_native_od.py')<workflow.index("'validated-source.txt'")
    synthetic=folder/'fingerprint';synthetic.mkdir()
    from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
    fixed=list(REQUIRED_FIXTURE_FILES)
    changed=PRODUCTION+['python/test_simz1_native_od.py','python/test_simz1_sequence_contract.py','scripts/simz1_workflow.ps1',
        'src/test/java/gt/edu/uvg/sim/zona1/SimZ1OdContractCheck.java','src/test/java/gt/edu/uvg/sim/zona1/SimZ1OdHistoricalBeforeCheck.java',
        'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1OdReservationsCheck.java']
    for name in fixed+changed:
        p=synthetic/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
    for name in changed:
        before=fingerprint(synthetic);(synthetic/name).write_text('changed');assert before!=fingerprint(synthetic),name
    command('protected-source-mutations',[sys.executable,'-B','-c',"import sys,unittest;sys.path.insert(0,'python');from test_simz1_sequence_contract import ProtectedSourceExpectationTests;r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProtectedSourceExpectationTests));sys.exit(not r.wasSuccessful())"])
    write(folder/'integration.json',dict(protected_sources_checked=checked,fingerprinted=changed,validate_invokes_focal_check=True,approval_written=False))

if __name__=='__main__':sys.exit(main())
