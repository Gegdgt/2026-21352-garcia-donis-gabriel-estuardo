'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),cp=require('node:child_process');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]',{});
const scale=6371008.8*Math.PI/180,settings={gap_m:.1,lateral_clearance_m:.1,stop_line_setback_m:2},plain=x=>JSON.parse(JSON.stringify(x));
const geometry={schema_version:1,available:true,links:{road:{path:[[0,0],[100/scale,0]],num_lanes:1,lane_width_m:3.5,
  opposing_lanes:0,offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{},allowed_to_links:[],movement_source:'effective_car_node_adjacency',osm_tags:{}}},
  occupancy_corridors:{schema:'corridor-length-v1',corridors:{road:{link_ids:['road'],represented_lanes:1}}}};
const lanes=new Lanes(geometry),q=new Queues(lanes,settings);
function record(id,start,hold,ordinal){return {vehicle:id,Agent_ID:id,Replay_Journey_Key:'journey-'+id,Link_ID:'road',
  timestamps:[start,50],path:geometry.links.road.path,Vehicle_Type:'bus',Vehicle_Dimensions:{length_m:12,width_m:2.5,source:'synthetic_fixture',assumed:true},Trip:{Trip_ID:'trip-'+id},
  Native_Occupancy:{policy:'corridor-length-v1',corridor_id:'road',model_slot:0,ordinal},Boundary_Provenance:{start:'entered link',end:'left link',start_relative:0,end_relative:1},
  Motion_Plan:{version:1,status:'kinematic',distance_m:100,hold_start:hold,native_wait_boundary:hold,phases:[[start,hold,0,100/(hold-start),0],[hold,50,100,0,0]]},
  Observed_Waits:{signal_red:{first:hold,last:49,position_evidence:'queue_exit',sources:['MATSim15_QNode_native_branch']}}};}
const records=[record('first',0,5,1),record('second',1,10,2),record('root',2,15,3)],target=records.at(-1),key=q.key(target);
function marker(row,time,checkpoint=null){const fraction=q.fractionAt(row,time);return {...row,...lanes.marker(row,fraction,{},row.path[0]),
  Visual_Motion_Fraction:fraction,Visual_Distance_m:fraction*100,Visual_Queue_Context:{complete:true,phase:'final',...(checkpoint?{checkpoint}:{})}};}
const input={op:'init',identity:{run_id:'synthetic-checkpoint-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64)},visual_lanes:geometry,settings};
const requests=['base','final','interpolate','fifo'].map(role=>({key,role,epoch:role==='fifo'?14:15,stage:role==='fifo'?[3,key]:null}));
const job={op:'solve',records,phases:Object.fromEntries(records.map(r=>[q.key(r),'final'])),checkpoints:{},lane_events:[],requests};
const processResult=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{input:JSON.stringify(input)+'\n'+JSON.stringify(job)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(processResult.status,0,processResult.stderr);const replies=processResult.stdout.trim().split(/\r?\n/).map(line=>JSON.parse(line));
assert.equal(replies[0].status,'ready');assert.equal(replies[1].status,'resolved',JSON.stringify(replies[1]));
const states=replies[1].states;assert.equal(states.length,4);for(let i=0;i<states.length;i++){
  for(const name of ['key','role','epoch','stage'])assert.deepEqual(states[i][name],requests[i][name]);assert.equal(states[i].result.available,true);}
const compactTripJob={...job,records:records.map(({Trip,...record})=>record),
  trips:Object.fromEntries(records.map(record=>[record.Replay_Journey_Key,record.Trip]))};
const compactProcess=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify(input)+'\n'+JSON.stringify(compactTripJob)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(compactProcess.status,0,compactProcess.stderr);
const compactReply=JSON.parse(compactProcess.stdout.trim().split(/\r?\n/).at(-1));
assert.equal(compactReply.status,'resolved');assert.deepEqual(compactReply.states,states,'compact transport is lossless, including Trip identity');
const wrongTripJob={...compactTripJob,records:records.map(row=>({...row,Trip:{...row.Trip,Trip_ID:'tampered'}}))};
const wrongTripProcess=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify(input)+'\n'+JSON.stringify(wrongTripJob)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(wrongTripProcess.status,0,wrongTripProcess.stderr);
assert.match(JSON.parse(wrongTripProcess.stdout.trim().split(/\r?\n/).at(-1)).error,/differs from inline/);
const auxiliary={...record('outside-evaluated-epochs',60,65,10),timestamps:[60,80],
  Motion_Plan:{version:1,status:'constant',distance_m:100,phases:[[60,80,0,5,0]]},Observed_Waits:{}};
const scopedJob={...job,records:[...records,auxiliary],constraint_keys:records.map(row=>q.key(row))};
function kernelReply(packet){const child=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify(input)+'\n'+JSON.stringify(packet)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
  assert.equal(child.status,0,child.stderr);return JSON.parse(child.stdout.trim().split(/\r?\n/).at(-1));}
const scopedReply=kernelReply(scopedJob);assert.equal(scopedReply.status,'resolved');assert.deepEqual(scopedReply.states,states);
assert.equal(scopedReply.geometry_records,4);assert.equal(scopedReply.constraint_records,3,
  'out-of-epoch geometry stays present without entering the causal roster');
assert.match(kernelReply({...scopedJob,constraint_keys:scopedJob.constraint_keys.filter(value=>value!==key)}).error,/coverage is incomplete/,
  'a required own request must never disappear from the causal roster');
const capsule={schema:'native-queue-phase-capsule-v1',complete:true,input:states[0].input,prepared:states[0].prepared,settings,
  base:states[0].result,final:states[1].result,release:states[0].release,fifo:[{epoch:14,stage:[3,key],result:states[3].result}]};
const invalidInterpolation={...job,records:[target],phases:{},requests:[requests.find(row=>row.role==='interpolate')]};
const rejectedProcess=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify(input)+'\n'+JSON.stringify(invalidInterpolation)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(rejectedProcess.status,0,rejectedProcess.stderr);
assert.match(JSON.parse(rejectedProcess.stdout.trim().split(/\r?\n/).at(-1)).error,/Interpolacion HOLD sin fase/,
  'an eligible HOLD must not be silently reclassified as auxiliary motion to evaluate interpolation');
const unavailableRecord={...target,Motion_Plan:{...target.Motion_Plan,status:'unavailable',phases:[],hold_start:null,
  native_wait_boundary:null,fallback_reason:'fixture_unobserved_motion'}};
const unavailableJob={...job,records:[unavailableRecord],phases:{},requests:requests.filter(row=>['interpolate','fifo'].includes(row.role))};
const unavailableProcess=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify(input)+'\n'+JSON.stringify(unavailableJob)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(unavailableProcess.status,0,unavailableProcess.stderr);
const unavailableReply=JSON.parse(unavailableProcess.stdout.trim().split(/\r?\n/).at(-1));assert.equal(unavailableReply.status,'resolved');
for(const state of unavailableReply.states)assert.deepEqual(state.result,{available:false,pose:null,reason:'motion_unavailable'},
  'a resolved absence stays absent at interpolation and FIFO evaluation');
const full=records.map(r=>marker(r,r.Motion_Plan.hold_start)),bounded=[marker(target,15,capsule)];
function signature(frame){const row=frame.markers.find(r=>r.vehicle==='root');assert.ok(row);return plain({position:row.position,
  heading:row.Visual_Body_Heading_Degrees,center:row.Visual_Queue_Center_Meters,state:row.Visual_Queue_State,
  body:[row.Visual_Body_Length_Meters,row.Visual_Body_Width_Meters,row.Visual_Body_Clipped],turn:row.Visual_Queue_Turn_Clearance??[]});}
const samples=[];
for(const time of [14,14.999,15,20,49.999,14]){
  const expected=signature(new Queues(lanes,settings).frame([marker(target,time)],time,()=>({}),full));
  const actual=signature(new Queues(lanes,settings).frame([marker(target,time,capsule)],time,()=>({}),bounded));
  assert.deepEqual(actual,expected,'checkpoint equals the complete original context at absolute time '+time);samples.push({time,...actual});
}
function rejected(mutate,pattern){const broken=plain(capsule);mutate(broken);assert.throws(()=>new Queues(lanes,settings).frame([marker(target,20,broken)],20,()=>({}),[marker(target,15,broken)]),pattern);}
rejected(value=>value.complete=false,/Checkpoint/);
rejected(value=>value.input+=' ',/Checkpoint/);
rejected(value=>value.settings.gap_m=2,/Checkpoint/);
rejected(value=>value.prepared+=' ',/Checkpoint/);
rejected(value=>value.base.anchor_m=Infinity,/no finita/);
rejected(value=>delete value.final.turn_bounds,/giro/);
rejected(value=>delete value.prepared,/Firma/);
rejected(value=>delete value.final,/fase corporal requerida/);
rejected(value=>delete value.base,/fase corporal requerida/);
const fakePending=marker(target,20,{...capsule,final:undefined});
fakePending.Visual_Queue_Context.checkpoint_pending=['final'];
assert.throws(()=>new Queues(lanes,settings).frame([fakePending],20,()=>({}),[fakePending]),/fase corporal requerida/,
  'a consumer cannot promote its own pending phase to production authority');
const altered={...target,Native_Occupancy:{...target.Native_Occupancy,ordinal:99}};
assert.throws(()=>new Queues(lanes,settings).frame([marker(altered,20,capsule)],20),/Checkpoint/);
assert.equal(JSON.stringify(records),JSON.stringify(job.records),'source records unchanged');

// Release propagation is a sequence of exact production passes, not a
// simultaneous SCC edge. The previous corridor's queued anchor changes the
// new corridor's starting point and therefore a transferred leader's body.
const releaseGeometry=plain(geometry);
releaseGeometry.links.a={...plain(geometry.links.road),to_node:'join',allowed_to_links:['b']};
releaseGeometry.links.b={...plain(geometry.links.road),path:[[100/scale,0],[200/scale,0]],from_node:'join',to_node:'end'};
delete releaseGeometry.links.road;
releaseGeometry.occupancy_corridors.corridors={a:{link_ids:['a'],represented_lanes:1},b:{link_ids:['b'],represented_lanes:1}};
const releaseLanes=new Lanes(releaseGeometry),releaseQueue=new Queues(releaseLanes,settings);
function releaseRecord(id,link,start,hold,end,ordinal,f0=0){
  const row=record(id,start,hold??end,ordinal),distance=100*(1-f0),stop=hold??end;
  row.Link_ID=link;row.timestamps=[start,end];row.Native_Occupancy.corridor_id=link;
  row.path=[releaseLanes.place(link,f0*100,0).position,releaseGeometry.links[link].path[1]];
  row.Boundary_Provenance.start_relative=f0;
  row.Motion_Plan={version:1,status:'kinematic',distance_m:distance,
    ...(hold==null?{}:{hold_start:hold,native_wait_boundary:hold}),
    phases:[[start,stop,0,distance/(stop-start),0],...(hold==null?[]:[[hold,end,distance,0,0]])]};
  row.Observed_Waits=hold==null?{}:{signal_red:{first:hold,last:end-1,position_evidence:'queue_exit',sources:['MATSim15_QNode_native_branch']}};
  return row;
}
const releaseRows=[releaseRecord('head','a',0,1,9,1),releaseRecord('front','a',1,5,10,2),
  releaseRecord('front','b',10,null,20,100),releaseRecord('forming','a',8,15,30,3,.95),releaseRecord('held','a',9,10,30,4)];
const releaseMarker=(row,time)=>{const fraction=releaseQueue.fractionAt(row,time);return {...row,
  ...releaseLanes.marker(row,fraction,{},row.path[0]),Visual_Motion_Fraction:fraction,
  Visual_Distance_m:fraction*row.Motion_Plan.distance_m,Visual_Queue_Context:{complete:true,phase:'final'}};};
const releaseRoster=releaseRows.map(row=>releaseMarker(row,row.Motion_Plan.hold_start??row.timestamps[0]));
const neighbors=row=>row.vehicle==='front'?(row.Link_ID==='a'?{next:releaseRows[2]}:{previous:releaseRows[1]}):{};
const releaseKey=releaseQueue.key(releaseRows[4]);
const releaseRequests=[{key:releaseKey,role:'final',epoch:10,stage:null},
  {key:releaseQueue.key(releaseRows[2]),role:'fifo',epoch:10.1,stage:[4,releaseKey]}];
const normal=new Queues(releaseLanes,settings);normal.frame([],10,neighbors,releaseRoster);
const expectedStates=plain(releaseRequests.map(request=>normal.supportState(request).result));
let previousRelease=new Map(),externalStates,firstStates;const generations=[];
for(let generation=0;generation<releaseRows.length+2;generation++){
  const external=new Queues(releaseLanes,settings);
  external.frame([],10,neighbors,releaseRoster,{external:true,depth:generation,anchors:previousRelease});
  externalStates=plain(releaseRequests.map(request=>external.supportState(request).result));
  if(generation===0)firstStates=externalStates;
  generations.push({generation,changed:external.releasePass.changed,root_anchor:externalStates[0].anchor_m});
  previousRelease=new Map(Object.entries(external.releasePass.next).filter(([,row])=>row!==null));
  if(!external.releasePass.changed)break;
}
assert.equal(generations.at(-1).changed,false,'external production passes converge before certification');
assert.ok(generations.length>=2,'release default must not be accepted as a converged checkpoint');
assert.notDeepEqual(firstStates,expectedStates,'fixture exercises a real deferred release dependency');
assert.deepEqual(externalStates,expectedStates,'external generation fixed point equals the complete recursive renderer');
assert.equal(normal.releasePass.changed,false);

// A direct departed projection keeps its unconstrained centre. Only its future
// swept-front endpoint uses the anchor phase available at the caller's stage.
const projectionGeometry=plain(geometry);
projectionGeometry.links.side={...plain(geometry.links.road),path:[[0,1/scale],[100/scale,1/scale]],from_node:'c',to_node:'d'};
projectionGeometry.occupancy_corridors.corridors.side={link_ids:['side'],represented_lanes:1};
const projectionRoot=record('projection',1,10,2),projectionForeign={...record('foreign',0,5,1),Link_ID:'side',
  path:projectionGeometry.links.side.path,Native_Occupancy:{policy:'corridor-length-v1',corridor_id:'side',model_slot:0,ordinal:1}};
const projectionKey=q.key(projectionRoot),projectionRows=[projectionRoot,projectionForeign];
const projectionJob={op:'solve',records:projectionRows,phases:Object.fromEntries(projectionRows.map(row=>[q.key(row),'final'])),
  checkpoints:{},lane_events:[],requests:[null,[2,projectionKey],[3,projectionKey]].map(stage=>({key:projectionKey,role:'interpolate',epoch:4,stage}))};
function projectedReply(packet){const child=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify({...input,visual_lanes:projectionGeometry})+'\n'+JSON.stringify(packet)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
  assert.equal(child.status,0,child.stderr);return JSON.parse(child.stdout.trim().split(/\r?\n/).at(-1));}
const projectionReply=projectedReply(projectionJob);assert.equal(projectionReply.status,'resolved');
const [legacyProjection,baseProjection,finalProjection]=projectionReply.states;
assert.deepEqual(baseProjection.result,legacyProjection.result,'null interpolation stage retains BASE semantics exactly');
assert.equal(finalProjection.result.center_m,baseProjection.result.center_m,'FINAL departed centre is unconstrained interpolation');
assert.deepEqual(finalProjection.result.pose,baseProjection.result.pose,'stage does not alter the directly interpolated body');
assert.ok(finalProjection.result.front_trace.to_center_m<baseProjection.result.front_trace.to_center_m,
  'future turn trace must end at the FINAL anchor when the stage has already processed it');
assert.deepEqual(finalProjection.stage,[3,projectionKey],'helper preserves the explicitly requested stage');
assert.match(projectedReply({...projectionJob,phases:{...projectionJob.phases,[projectionKey]:'base'},
  requests:[projectionJob.requests[2]]}).error,/BASE.*FINAL/,'a BASE-only capsule cannot provide a FINAL swept endpoint');
assert.match(projectedReply({...projectionJob,requests:[{...projectionJob.requests[2],stage:[null,projectionKey]}]}).error,/Etapa/,
  'an invalid projected stage cannot fall back silently to BASE');

// Native shared-upstream evidence has no representable anchor in this branch.
// A complete schedule proof excludes its sole active-service exception; it
// never supplies a guessed lane, ordinal, zero anchor or body.
const absenceGeometry=plain(geometry);
absenceGeometry.links.road.native_lanes={original:{index:null,represented_lanes:1,start_m:100,to_links:[],to_lanes:['terminal']},
  terminal:{index:0,represented_lanes:1,start_m:80,to_links:[],to_lanes:[]}};
const absenceRecord=record('absent',1,10,2);delete absenceRecord.Native_Occupancy;
const absenceKey=q.key(absenceRecord),absenceProof={schema:'native-blocking-facility-support-v1',identity:input.identity,
  source_sqlite_sha256:'b'.repeat(64),schedule_sha256:'c'.repeat(64),reader_sha256:'d'.repeat(64),blocking_links:[]};
const absenceJob={op:'solve',records:[absenceRecord],phases:{[absenceKey]:'final'},checkpoints:{},
  lane_events:[{vehicle:absenceRecord.vehicle,time:1,type:'entered lane',link:'road',lane:'original'}],
  requests:['base','final','fifo'].map(role=>({key:absenceKey,role,epoch:10,stage:role==='fifo'?[3,absenceKey]:null}))};
function absentReply(packet,proof=absenceProof){const child=cp.spawnSync(process.execPath,[path.join(__dirname,'simz1_queue_checkpoint.cjs')],{
  input:JSON.stringify({...input,visual_lanes:absenceGeometry,...(proof?{facility_support:proof}:{})})+'\n'+JSON.stringify(packet)+'\n',encoding:'utf8',maxBuffer:4*1024*1024});
  assert.equal(child.status,0,child.stderr);const replies=child.stdout.trim().split(/\r?\n/).map(line=>JSON.parse(line));
  return replies[0].status==='error'?replies[0]:replies.at(-1);}
const absenceReply=absentReply(absenceJob);assert.equal(absenceReply.status,'resolved',absenceReply.error);
assert.equal(absenceReply.constraint_records,0);assert.equal(absenceReply.geometry_records,1,'absence preserves native geometric observation');
for(const state of absenceReply.states){assert.equal(state.result.available,false);assert.equal(state.result.pose,null);}
for(const state of absenceReply.states.slice(0,2)){
  assert.equal(state.result.anchor_m,null);assert.equal(state.result.pose_available,false);
  assert.equal(state.result.reason,'shared_upstream_without_blocking_facility');}
assert.equal(absenceReply.states[2].result.reason,'native_occupancy_unavailable');
assert.equal(new Set(absenceReply.states.map(state=>state.prepared)).size,1,'absence phases share one source preparation certificate');
const fifoAbsence=absentReply({...absenceJob,phases:{},requests:[absenceJob.requests[2]]},null);
assert.equal(fifoAbsence.status,'resolved');assert.equal(fifoAbsence.states[0].result.available,false,
  'FIFO without native occupancy terminates before predecessor/anchor reads, even without schedule proof');
assert.match(absentReply(absenceJob,null).error,/entrada representable/,'missing schedule proof cannot certify absent BASE or FINAL');
assert.match(absentReply(absenceJob,{...absenceProof,blocking_links:['road']}).error,/entrada representable/,
  'a possible active blocking service keeps the fallback ambiguity unresolved');
assert.match(absentReply(absenceJob,{...absenceProof,identity:{...input.identity,iteration:1}}).error,/facility.*invalid/);
assert.match(absentReply(absenceJob,{...absenceProof,schedule_sha256:'invalid'}).error,/facility.*invalid/);
const nativePositive=absentReply({...absenceJob,records:[{...absenceRecord,Native_Occupancy:{policy:'corridor-length-v1',corridor_id:'road',model_slot:0,ordinal:2}}],
  requests:absenceJob.requests.slice(0,2)});
assert.equal(nativePositive.status,'resolved');for(const state of nativePositive.states)assert.equal(state.result.available,true,
  'a valid native occupancy cannot be removed by the facility absence predicate');
const terminalEvents=[...absenceJob.lane_events,
  {vehicle:absenceRecord.vehicle,time:2,type:'left lane',link:'road',lane:'original'},
  {vehicle:absenceRecord.vehicle,time:2,type:'entered lane',link:'road',lane:'terminal'}];
const terminalReply=absentReply({...absenceJob,lane_events:terminalEvents});assert.equal(terminalReply.status,'resolved');
for(const state of terminalReply.states.slice(0,2))assert.equal(state.result.available,true,
  'an intermediate native terminal entry prevents shared-upstream absence at HOLD');
assert.equal(terminalReply.states[2].result.available,false,'terminal lane entry does not invent corridor occupancy');
const classifyJob={...absenceJob,op:'classify',requests:[{key:absenceKey,role:'classify',epoch:10,stage:null}]};
const classifyTerminal=absentReply({...classifyJob,lane_events:terminalEvents});assert.equal(classifyTerminal.status,'classified');
assert.equal(classifyTerminal.pose_requests,0,'classification must stop before any BASE/FINAL/FIFO pose is evaluated');
assert.deepEqual(classifyTerminal.states[0].classification,{complete:true,represented:true,eligible:true,
  group_key:JSON.stringify(['road',0]),order_time:2,hold:10,start:1,end:50,native_entry:true,
  occupancy:null,departure:null,departure_complete:true,reason:null});
assert.ok(!Object.hasOwn(classifyTerminal.states[0],'result'),'classification cannot be passed off as a position capsule');
const classifyShared=absentReply(classifyJob);assert.equal(classifyShared.states[0].classification.complete,true);
assert.equal(classifyShared.states[0].classification.represented,false);
assert.equal(classifyShared.states[0].classification.reason,'shared_upstream_without_blocking_facility');
const classifyUnproven=absentReply(classifyJob,null);assert.equal(classifyUnproven.states[0].classification.complete,false,
  'an unproven shared-upstream branch cannot erase a possible blocking-service exception');
const classifyNative=kernelReply({...job,op:'classify',requests:records.map(row=>({key:q.key(row),role:'classify',epoch:row.Motion_Plan.hold_start,stage:null}))});
assert.equal(classifyNative.status,'classified');assert.equal(classifyNative.pose_requests,0);
for(const [i,state]of classifyNative.states.entries()){
  assert.equal(state.classification.group_key,JSON.stringify(['corridor:road',0]));assert.equal(state.classification.order_time,i+1);
  assert.deepEqual(state.classification.occupancy,{corridor:'road',slot:0,ordinal:i+1});assert.equal(state.classification.complete,true);
  assert.equal(state.classification.departure_complete,false,'a bounded geometry packet alone does not certify complete predecessor history');}
assert.match(absentReply({...classifyJob,requests:[{...classifyJob.requests[0],epoch:9}]}).error,/immutable hold epoch/);
assert.match(absentReply({...classifyJob,checkpoints:{[absenceKey]:capsule}}).error,/Invalid source classification/);

// A native bus may remain stationary after service and then leave traffic.
// Its active reservation is still a HOLD: the terminating event name does not
// make FIFO/project readers independent of that immutable bodily phase.
const terminalDeparture={...record('terminal-departure',10,11,7),timestamps:[10,12],
  path:[geometry.links.road.path[1],geometry.links.road.path[1]],
  Boundary_Provenance:{start:'VehicleDepartsAtFacility',end:'vehicle leaves traffic',start_relative:1,end_relative:1},
  Motion_Plan:{version:1,status:'stationary',distance_m:0,hold_start:null,native_wait_boundary:null,phases:[[10,12,0,0,0]]},
  Observed_Waits:{}};
const departureKey=q.key(terminalDeparture),departureMarker=at=>marker(terminalDeparture,at),
  departureRequests=['base','final','fifo'].map(role=>({key:departureKey,role,epoch:role==='fifo'?11:10,
    stage:role==='fifo'?[8,departureKey]:null}));
assert.deepEqual(plain(q.evidence(departureMarker(10),10)),{eligible:true,unknown:false,start:10,end:12,hold:10});
assert.equal(q.evidence({...departureMarker(10),Boundary_Provenance:{...terminalDeparture.Boundary_Provenance,end:'left link'}},10).hold,10);
const departureJob={op:'solve',records:[terminalDeparture],lane_events:[],phases:{[departureKey]:'final'},checkpoints:{},requests:departureRequests};
const departureReply=kernelReply(departureJob);assert.equal(departureReply.status,'resolved',departureReply.error);
for(const row of departureReply.states.slice(0,2)){
  assert.equal(row.result.available,true);assert.equal(row.result.pose_available,true);assert.equal(row.result.within_storage,true);}
assert.equal(departureReply.states[2].result.center_m,departureReply.states[1].result.anchor_m);
const departureFrames=new Queues(lanes,settings),departurePositions=[];
for(const time of [10,11,11.999,10]){
  const frame=departureFrames.frame([departureMarker(time)],time,()=>({}),[departureMarker(10)]);
  assert.equal(frame.markers.length,1);assert.equal(frame.markers[0].Visual_Queue_Compatible,true);
  departurePositions.push(plain(frame.markers[0].position));}
assert.ok(departurePositions.every(value=>JSON.stringify(value)===JSON.stringify(departurePositions[0])));
for(const role of ['fifo','interpolate'])assert.match(kernelReply({...departureJob,phases:{},requests:[{
  key:departureKey,role,epoch:11,stage:role==='fifo'?[8,departureKey]:null}]}).error,/HOLD sin fase corporal certificada/,
  'missing HOLD phase must still fail, including after native vehicle leaves traffic');
for(const change of [
  {Native_Occupancy:null},
  {Motion_Plan:{...terminalDeparture.Motion_Plan,status:'kinematic',distance_m:1,phases:[[10,12,0,.5,0]]}},
  {Boundary_Provenance:{...terminalDeparture.Boundary_Provenance,start_relative:.9}},
  {Boundary_Provenance:{...terminalDeparture.Boundary_Provenance,start:'entered link'}}]){
  const altered={...terminalDeparture,...change};assert.equal(q.evidence(marker(altered,10),10).eligible,false,
    'departure timestamp alone does not invent a stationary bodily reservation');}
console.log(JSON.stringify({status:'PASS',cases:49,scope:'synthetic complete-context equivalence, production component kernel, external release generations, stage-scoped interpolation, certified source absences and pre-anchor source classification',
  samples,generations,projection:{center:baseProjection.result.center_m,base_endpoint:baseProjection.result.front_trace.to_center_m,
    final_endpoint:finalProjection.result.front_trace.to_center_m},absence:absenceReply.states.map(row=>({role:row.role,result:row.result})),
  classification:classifyTerminal.states[0],terminal_departure:{hold:10,final_anchor:departureReply.states[1].result.anchor_m,
    seek_positions:departurePositions,missing_phase_rejected:true},
  kernel_memory:replies[1].memory,capsule},null,2));
