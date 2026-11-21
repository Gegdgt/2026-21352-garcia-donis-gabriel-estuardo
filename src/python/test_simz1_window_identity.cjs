// Prepared, not executed: exercise the production loader's index preparation.
// No HTTP, browser, server, SQLite, MATSim or source-run mutation.
const assert=require('node:assert/strict');
const Loader=require('./simz1_continuous_loader.js');
const fixture=require('./fixtures/simz1-visibility-temporal-controls.json');
const base=structuredClone(fixture.records[0]);
base.Trip=structuredClone(fixture.trips[base.Replay_Journey_Key]);
const reversedObject=value=>value && typeof value==='object' ? Array.isArray(value) ? value.map(reversedObject) :
  Object.fromEntries(Object.entries(value).reverse().map(([key,row])=>[key,reversedObject(row)])) : value;
const rows=index=>{
  if(!index)return [];
  return [...index.byStart,...rows(index.left),...rows(index.right)];
};
const payload=(segments,context=[])=>({segments,context_segments:context,lane_replay:{events:[]},signal_replay:{series:[]}});
{
  const native=payload([base,structuredClone(base),reversedObject(base)],[structuredClone(base)]),before=JSON.stringify(native);
  const prepared=Loader.prepare(native);
  assert.equal(prepared.timelines.get(base.vehicle).length,1);
  assert.equal(prepared.transitionTimelines.get(base.vehicle).length,1);
  assert.equal(rows(prepared.intervalIndex).length,1);
  assert.equal(prepared.timelines.get(base.vehicle)[0],base,'retain the canonical native object');
  assert.equal(prepared.transitionRecords.values().next().value.previous,undefined);
  assert.equal(prepared.transitionRecords.values().next().value.next,undefined,'a duplicate cannot be its own transition neighbour');
  assert.equal(JSON.stringify(native),before,'the native payload, records and timestamps remain untouched');
}
{
  const contradictory=structuredClone(base);contradictory.Motion_Plan.cap_mps=2;
  const overlapping=structuredClone(base);overlapping.timestamps=[119,121];
  overlapping.Motion_Plan.phases=[[119,121,0,1,0]];
  const prepared=Loader.prepare(payload([base,contradictory,overlapping]));
  assert.equal(prepared.timelines.get(base.vehicle).length,3,'changed evidence and overlapping intervals are not duplicates');
  assert.equal(rows(prepared.intervalIndex).length,3,'ambiguity remains visible to the production interval selector');
  assert.equal(prepared.transitionTimelines.get(base.vehicle).length,3);
}
{
  const second=structuredClone(fixture.records[1]);second.Trip=base.Trip;
  const left=Loader.prepare(payload([base],[structuredClone(base),second]));
  const right=Loader.prepare(payload([second],[base,structuredClone(second)]));
  assert.equal(left.timelines.get(base.vehicle).length,1);
  assert.equal(right.timelines.get(base.vehicle).length,1);
  for(const prepared of [left,right]) {
    assert.equal(prepared.transitionTimelines.get(base.vehicle).length,2);
    const before=prepared.transitionRecords.get(JSON.stringify([base.vehicle,base.Link_ID,...base.timestamps]));
    const after=prepared.transitionRecords.get(JSON.stringify([second.vehicle,second.Link_ID,...second.timestamps]));
    assert.equal(before.next.Link_ID,second.Link_ID);assert.equal(after.previous.Link_ID,base.Link_ID);
  }
}
{
  const entered={vehicle:base.vehicle,time:119,type:'entered lane',link:base.Link_ID,lane:'lane-a'};
  const left={vehicle:base.vehicle,time:119,type:'left lane',link:base.Link_ID,lane:'lane-a'};
  const native=payload([base]);native.lane_replay.events=[entered,left];
  native.context_lane_events=[structuredClone(left)];
  native.queue_context={by_seed:{},segments:[],transition_segments:[],lane_events:[structuredClone(left)]};
  const prepared=Loader.prepare(native),events=prepared.laneTimelines.get(base.vehicle);
  assert.deepEqual(events,[entered,left],'a latest-predecessor context copy cannot reverse native same-timestamp order');
  assert.equal(events.at(-1).type,'left lane');
}
{
  const identity={run_id:'fractional-context',iteration:0,run_manifest_sha256:'a'.repeat(64)};
  const record={...structuredClone(base),vehicle:'\u00f1\ud83d\ude97',Replay_Journey_Key:'viaje',Link_ID:'calle',timestamps:[1e-7,1e-6]};
  record.Trip={...record.Trip,Departure:1e-7,Arrival:1e-6,Status:'completed'};
  record.Motion_Plan={version:1,status:'constant',distance_m:9e-7,cap_mps:1,phases:[[1e-7,1e-6,0,1,0]]};
  const pythonKey='["\\u00f1\\ud83d\\ude97","viaje","calle",[1e-07,1e-06]]';
  const canonical=JSON.stringify([record.vehicle,record.Replay_Journey_Key,record.Link_ID,record.timestamps]);
  const queue={schema_version:1,policy:'native-hold-closure-v1',
    by_seed:{[pythonKey]:{complete:true,reason:null,record_keys:[pythonKey]}},
    segments:[structuredClone(record)],transition_segments:[],trips:{viaje:record.Trip},lane_events:[]};
  const native={...identity,index:0,start_seconds:0,end_seconds:120,...payload([record]),trips:{viaje:record.Trip},queue_context:queue};
  const timestamps=JSON.stringify(record.timestamps);
  Loader.validateRecords(native,identity,0,0,120);
  const prepared=Loader.prepare(native);
  assert.equal(prepared.queueContexts.get(canonical).complete,true);
  assert.deepEqual([...prepared.queueContextMembers],[canonical]);
  assert.equal(JSON.stringify(record.timestamps),timestamps,'canonical identity text does not rewrite native timestamps');
  queue.by_seed[canonical]={complete:true,reason:null,record_keys:[canonical]};
  Loader.validateRecords(native,identity,0,0,120);
  assert.equal(Loader.prepare(native).queueContexts.size,1,'equivalent JSON spellings have one context identity');
  queue.by_seed[canonical]={complete:false,reason:'record_limit',record_keys:[]};
  assert.throws(()=>Loader.validateRecords(native,identity,0,0,120),/contradictorios/);
  assert.throws(()=>Loader.prepare(native),/contradictorios/,'preparation also rejects contradictory canonical identities');
}
{
  const records=['root','base','other'].map(vehicle=>({...structuredClone(base),vehicle}));
  const keys=records.map(r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key,r.Link_ID,r.timestamps]));
  const status=(members,phases)=>({complete:true,record_keys:members,support_certificate:{
    policy:'native-causal-epochs-v1',complete:true,poses_certified:false,phase_keys:phases}});
  const native=payload(records);
  native.queue_context={dependency_policy:'native-causal-epochs-v1',segments:records,transition_segments:[],lane_events:[],
    by_seed:{[keys[0]]:status(keys.slice(0,2),{[keys[0]]:'final',[keys[1]]:'base'}),
      [keys[1]]:{complete:false,reason:'record_limit',record_keys:[]}}};
  let prepared=Loader.prepare(native);
  assert.equal(prepared.queueContextPhases.get(keys[1]),'base');
  assert.equal(prepared.queueContexts.get(keys[1]).complete,false,'membership cannot promote an incomplete active seed');
  native.queue_context.by_seed[keys[2]]=status([keys[2],keys[1]],{[keys[2]]:'final',[keys[1]]:'final'});
  prepared=Loader.prepare(native);
  assert.equal(prepared.queueContextPhases.get(keys[1]),'final','final dominates base only through complete seed support');
  assert.equal(prepared.queueContexts.get(keys[1]).complete,false);
  delete native.queue_context.by_seed[keys[2]];
  delete native.queue_context.by_seed[keys[1]];
  assert.equal(Loader.prepare(native).queueContexts.get(keys[1]).phase,'base','new members retain their certified phase');
  const valid=structuredClone(native);
  for(const mutate of [
    q=>delete q.by_seed[keys[0]].support_certificate.phase_keys[keys[1]],
    q=>q.by_seed[keys[0]].support_certificate.phase_keys[keys[1]]='unknown',
    q=>q.by_seed[keys[0]].support_certificate.phase_keys[keys[0]]='base',
    q=>q.by_seed[keys[0]].support_certificate.poses_certified=true,
    q=>delete q.by_seed[keys[0]].support_certificate]) {
    const broken=structuredClone(valid);mutate(broken.queue_context);
    assert.throws(()=>Loader.prepare(broken),/causales/,'missing/altered phase evidence must fail closed');
  }
  const identity={run_id:'checkpoint-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64)},settings={gap_m:2,lateral_clearance_m:.1,stop_line_setback_m:2};
  const contract={identity,settings,generation:2,...Object.fromEntries(
    ['index_sha256','kernel_sha256','geometry_sha256','graph_sha256','root_digest'].map(key=>[key,'b'.repeat(64)]))};
  const proof=native.queue_context.by_seed[keys[0]].support_certificate;
  Object.assign(proof,{converged:true,generation:2,graph_sha256:contract.graph_sha256,root_digest:contract.root_digest});
  const capsule={schema:'native-queue-phase-capsule-v1',complete:true,input:{fixture:true},prepared:{fixture:true},settings,
    base:{anchor_m:1},final:{anchor_m:1,turn_bounds:[]},release:null,fifo:[]};
  const baseCapsule=structuredClone(capsule);delete baseCapsule.final;
  native.queue_context.checkpoint_contract=contract;
  native.queue_context.checkpoints={[keys[0]]:capsule,[keys[1]]:baseCapsule};
  assert.equal(Loader.queueCheckpoints(native.queue_context,identity).get(keys[0]),capsule);
  assert.equal(Loader.prepare(native).queueContexts.get(keys[0]).checkpoint,capsule);
  const pinned={...identity,checkpoint_library_root:contract.root_digest};
  assert.equal(Loader.queueCheckpoints(native.queue_context,pinned).get(keys[0]),capsule);
  const foreign=structuredClone(native.queue_context);
  foreign.checkpoint_contract.root_digest='c'.repeat(64);
  foreign.by_seed[keys[0]].support_certificate.root_digest='c'.repeat(64);
  assert.throws(()=>Loader.queueCheckpoints(foreign,pinned),/Checkpoint/,
    'internally consistent capsules cannot replace the independently requested library');
  assert.throws(()=>Loader.queueCheckpoints(native.queue_context,{...pinned,checkpoint_library_root:'bad'}),/Checkpoint/);
  for(const mutate of [
    q=>q.checkpoint_contract.identity.iteration=1,
    q=>q.checkpoint_contract.index_sha256='bad',
    q=>q.by_seed[keys[0]].support_certificate.converged=false,
    q=>q.by_seed[keys[0]].support_certificate.generation=1,
    q=>q.by_seed[keys[0]].support_certificate.root_digest='c'.repeat(64),
    q=>q.checkpoints[keys[0]].complete=false,
    q=>q.checkpoints[keys[0]].settings={...q.checkpoints[keys[0]].settings,gap_m:3},
    q=>q.checkpoints[keys[2]]=q.checkpoints[keys[0]]]) {
    const broken=structuredClone(native);mutate(broken.queue_context);
    assert.throws(()=>Loader.queueCheckpoints(broken.queue_context,identity),/checkpoint|Checkpoint|Capsula/);
  }
}
console.log('PASS: immutable window identity and causal phase coverage; no promotion of failed seeds.');
