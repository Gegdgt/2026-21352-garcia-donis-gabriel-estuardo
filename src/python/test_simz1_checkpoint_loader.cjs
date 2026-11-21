'use strict';
// Loader trust/membership tests. Synthetic capsules are not geometric evidence.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),
  Loader=require('./simz1_continuous_loader.js');
const fixture=require('./fixtures/simz1-visibility-temporal-controls.json');
const identity={run_id:'checkpoint-loader-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64)};
const settings={gap_m:2,lateral_clearance_m:.1,stop_line_setback_m:2};
const records=['root','member','unrelated'].map(vehicle=>({...structuredClone(fixture.records[0]),vehicle}));
for(const row of records)row.Trip=structuredClone(fixture.trips[row.Replay_Journey_Key]);
const key=row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key,row.Link_ID,row.timestamps]);
const [root,member,unrelated]=records.map(key);
function native(){
  const contract={identity:structuredClone(identity),settings:structuredClone(settings),generation:2,
    ...Object.fromEntries(['index_sha256','kernel_sha256','geometry_sha256','graph_sha256','root_digest'].map(name=>[name,'b'.repeat(64)]))};
  const capsule=final=>({schema:'native-queue-phase-capsule-v1',complete:true,input:'{}',prepared:'{}',
    settings:structuredClone(settings),base:{anchor_m:10},...(final?{final:{anchor_m:10,turn_bounds:[]}}:{}),
    release:null,fifo:[]});
  const proof={policy:'native-causal-epochs-v1',complete:true,poses_certified:false,converged:true,
    generation:2,graph_sha256:contract.graph_sha256,root_digest:contract.root_digest,
    phase_keys:{[root]:'final',[member]:'base'}};
  return {...identity,segments:[records[0]],context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]},
    queue_context:{schema_version:1,policy:'native-hold-closure-v1',dependency_policy:'native-causal-epochs-v1',
      segments:records.slice(0,2),transition_segments:[],lane_events:[],trips:{},
      by_seed:{[root]:{complete:true,reason:null,record_keys:[root,member],support_certificate:proof}},
      checkpoint_contract:contract,checkpoints:{[root]:capsule(true),[member]:capsule(false)}}};
}
const failures=[],passed=[];
function test(name,run){try{run();passed.push(name);}catch(error){failures.push({name,error:error.stack});}}
function rejects(name,mutate,{prepare=false}={}){test(name,()=>{
  const payload=native();mutate(payload.queue_context,payload);
  assert.throws(()=>prepare?Loader.prepare(payload):Loader.queueCheckpoints(payload.queue_context,identity));
});}
test('complete witness authorizes both its seed and nonseed member',()=>{
  const payload=native(),prepared=Loader.prepare(payload);
  assert.equal(prepared.queueContexts.get(member).complete,true);
  assert.equal(prepared.queueContexts.get(member).phase,'base');
  assert.equal(prepared.queueContexts.get(member).checkpoint,payload.queue_context.checkpoints[member]);
});
rejects('converged closure cannot omit its root capsule',queue=>delete queue.checkpoints[root]);
rejects('converged closure cannot omit a historical member capsule',queue=>delete queue.checkpoints[member]);
rejects('converged closure cannot omit its entire capsule map',queue=>delete queue.checkpoints);
rejects('converged closure cannot replace its capsule map with null',queue=>queue.checkpoints=null);
rejects('converged closure cannot use an empty capsule map',queue=>queue.checkpoints={});
rejects('direct preparation cannot silently reconstruct a missing root capsule',queue=>delete queue.checkpoints[root],{prepare:true});
test('a failed active seed remains failed despite certified historical membership',()=>{
  const payload=native();payload.queue_context.by_seed[member]={complete:false,reason:'record_limit',record_keys:[]};
  const prepared=Loader.prepare(payload);
  assert.equal(prepared.queueContexts.get(member).complete,false);
  assert.equal(prepared.queueContexts.get(member).checkpoint,undefined);
  assert.ok(prepared.queueContextCheckpoints.has(member),'historical member evidence remains separately available');
});
rejects('member-only capsule cannot bypass false convergence',queue=>{
  delete queue.checkpoints[root];queue.by_seed[root].support_certificate.converged=false;
});
rejects('member-only capsule cannot bypass missing convergence',queue=>{
  delete queue.checkpoints[root];delete queue.by_seed[root].support_certificate.converged;
});
rejects('member-only capsule cannot reuse a previous generation',queue=>{
  delete queue.checkpoints[root];queue.by_seed[root].support_certificate.generation=1;
});
rejects('member-only capsule cannot reuse another root digest',queue=>{
  delete queue.checkpoints[root];queue.by_seed[root].support_certificate.root_digest='c'.repeat(64);
});
rejects('final effective phase requires a converged final witness',queue=>{
  queue.by_seed[unrelated]={complete:true,record_keys:[unrelated,member],support_certificate:{
    ...structuredClone(queue.by_seed[root].support_certificate),converged:false,
    phase_keys:{[unrelated]:'final',[member]:'final'}}};
  queue.segments.push(records[2]);queue.checkpoints[member].final={anchor_m:10,turn_bounds:[]};
});
rejects('FINAL capsule requires BASE anchor',queue=>delete queue.checkpoints[root].base);
rejects('FINAL capsule requires FINAL anchor',queue=>delete queue.checkpoints[root].final);
rejects('BASE capsule requires BASE anchor',queue=>delete queue.checkpoints[member].base);
rejects('finite scalar and turn constraints are mandatory',queue=>queue.checkpoints[root].final.anchor_m=Infinity);
rejects('missing turn bounds cannot be interpreted as no constraints',queue=>delete queue.checkpoints[root].final.turn_bounds);
rejects('release absence cannot be interpreted as null release',queue=>delete queue.checkpoints[root].release);
rejects('FIFO query table must have its declared shape',queue=>queue.checkpoints[root].fifo={});
rejects('capsule settings must match the checkpoint contract',queue=>queue.checkpoints[member].settings.gap_m=3);
rejects('nonmember capsule has no complete witness',queue=>queue.checkpoints[unrelated]=queue.checkpoints[member]);
rejects('direct preparation cannot cross the native run identity',queue=>queue.checkpoint_contract.identity.run_id='foreign',{prepare:true});
rejects('truthy completeness is not a complete certificate',queue=>queue.by_seed[root].complete='true',{prepare:true});
(async()=>{
  const name='production controls preserve historical capsules without promoting failed active seeds';
  try {
    const payload=native();payload.queue_context.by_seed[member]={complete:false,reason:'record_limit',record_keys:[]};
    const prepared=Loader.prepare(payload);
    prepared.holdRecords=records; // Explicit synthetic roster; no motion/geometry claim.
    const source=fs.readFileSync(path.join(__dirname,'visualizador_z1_controls.js'),'utf8'),
      start=source.indexOf('async function preparePartialAvailability('),
      preparation=source.indexOf('async function prepareContinuousWindow(',start),
      end=source.indexOf('\nfunction replaceContinuousWindow(',preparation);
    assert.ok(start>=0&&preparation>start&&end>preparation,'production preparation and its real availability dependency exist');
    const markerAt=(record,time,lane,context)=>({...record,Visual_Queue_Context:context.queueContexts.get(key(record))});
    await vm.runInNewContext(source.slice(start,end)+'\nprepareContinuousWindow(payload,prepared,null);',{
      payload,prepared,partialVisualPolicy:null,arrivalEffects:null,FINAL:86400,queueHoldTime:row=>row.timestamps[0],markerAt,
      preparationYield:async()=>{},activeRecordsAt:()=>[]});
    const cache=new Map(prepared.queueRosterCache.map(row=>[key(row),row.Visual_Queue_Context]));
    assert.equal(cache.get(root).phase,'final');
    assert.equal(cache.get(root).checkpoint,payload.queue_context.checkpoints[root]);
    assert.equal(cache.get(member).phase,'base');
    assert.equal(cache.get(member).checkpoint,payload.queue_context.checkpoints[member]);
    assert.equal(prepared.queueContexts.get(member).complete,false,'active body is still incomplete');
    assert.equal(cache.get(unrelated).complete,false);
    assert.equal(cache.get(unrelated).role,'auxiliary_transition');
    assert.equal(cache.get(unrelated).checkpoint,undefined);
    passed.push(name);
  }catch(error){failures.push({name,error:error.stack});}
  console.log(JSON.stringify({passed:passed.length,failed:failures.length,cases:passed,failures},null,2));
  if(failures.length)process.exitCode=1;
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
