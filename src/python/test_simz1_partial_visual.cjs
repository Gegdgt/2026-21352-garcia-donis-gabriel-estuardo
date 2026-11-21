'use strict';
// Isolated DOM/fetch fixtures. No native events, SQLite, server or QSim.
const assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto'),vm=require('node:vm');
const sourceDirectory=process.env.SIMZ1_RENDER_SOURCE_DIR || 'python';
const Loader=require(path.resolve(sourceDirectory,'simz1_continuous_loader.js'));
const {harness}=require(path.resolve('python/test_simz1_continuous_replay.cjs'));
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const key=row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key ?? '',row.Link_ID,row.timestamps]);
const identity={run_id:'validated-real-draw',iteration:0,run_manifest_sha256:'b'.repeat(64),source_version:'c'.repeat(64)};
const policy={policy:'partial-native-v1',pending_reason:'reconstruction_pending',body_position_available:false,
  native_status:'completed',native_validation:'valid'};
const roads={schema_version:1,available:true,lane_width_m:3,links:{
  road:{path:[xy(0,0),xy(100,0)],num_lanes:1,opposing_lanes:0,offset_eligible:true,from_node:'a',to_node:'b',
    native_lanes:{},allowed_to_links:['next'],movement_source:'effective_car_node_adjacency'},
  next:{path:[xy(100,0),xy(200,0)],num_lanes:1,opposing_lanes:0,offset_eligible:true,from_node:'b',to_node:'c',
    native_lanes:{},allowed_to_links:[],movement_source:'effective_car_node_adjacency'},
  other:{path:[xy(0,50),xy(200,50)],num_lanes:1,opposing_lanes:0,offset_eligible:true,from_node:'d',to_node:'e',
    native_lanes:{},allowed_to_links:[],movement_source:'effective_car_node_adjacency'}}};
const pending={vehicle:'pending-car',Agent_ID:'pending-person',Vehicle_Type:'car',Replay_Journey_Key:'pending-trip',
  Link_ID:'road',path:roads.links.road.path,timestamps:[0,40],
  Motion_Plan:{version:1,status:'kinematic',distance_m:100,hold_start:20,native_wait_boundary:20,cap_mps:5,
    phases:[[0,20,0,5,0],[20,40,100,0,0]]},
  Observed_Waits:{signal_red:{first:20,last:39,position_evidence:'queue_exit'}}};
const dependent={...pending,Link_ID:'next',path:roads.links.next.path,timestamps:[40,80],Observed_Waits:{},
  Motion_Plan:{version:1,status:'constant',distance_m:100,cap_mps:5,phases:[[40,80,0,2.5,0]]}};
const other={vehicle:'valid-car',Agent_ID:'valid-person',Vehicle_Type:'car',Replay_Journey_Key:'valid-trip',
  Link_ID:'other',path:roads.links.other.path,timestamps:[0,80],
  Motion_Plan:{version:1,status:'constant',distance_m:200,cap_mps:5,phases:[[0,80,0,2.5,0]]}};
const trips={
  'pending-trip':{Trip_ID:'pending-trip',Person_ID:'pending-person',Departure:0,Arrival:80,Status:'completed',
    Origin_Position:pending.path[0],Destination_Position:dependent.path[1]},
  'valid-trip':{Trip_ID:'valid-trip',Person_ID:'valid-person',Departure:0,Arrival:80,Status:'completed',
    Origin_Position:other.path[0],Destination_Position:other.path[1]}};
function payload(partial=true){return {...identity,...(partial?{visual_policy:policy.policy}:{}),index:0,start_seconds:0,end_seconds:120,
  segments:structuredClone([pending,dependent,other]),context_segments:[],trips:structuredClone(trips),
  lane_replay:{events:[]},signal_replay:{series:[]},incidents:[],
  queue_context:{schema_version:1,policy:'native-hold-closure-v1',...(partial?{visual_policy:policy.policy}:{}),
    by_seed:{[key(pending)]:{complete:false,reason:partial?'reconstruction_pending':'record_limit',
      ...(partial?{body_position_available:false}:{}),record_keys:[]}},segments:[],transition_segments:[],trips:{},lane_events:[]}};}
const sessions=[],flush=()=>new Promise(resolve=>setImmediate(resolve));
function create({partial=true,badHash=false,withoutGeometry=false,geometry=roads}={}) {
  const requests=[];
  const options=partial?{visual_policy:policy.policy}:{};
  const fetch=(url,requestOptions)=>{
    const u=new URL(url,'http://localhost');
    if(u.pathname==='/api/hud')return Promise.resolve({ok:true,status:200,json:async()=>({schema_version:1,...identity,
      ...(partial?{visual_policy:policy.policy}:{}),replay_window:{start_seconds:0,end_seconds:90000},
      source_time_horizon:{start_seconds:0,end_seconds:90000},metrics_window:{start_seconds:0,end_seconds:90001},
      counts:{persons_generated:2,planned_trips:2,completed_trips:2,pending_censored_trips:0,reconstructed_vehicles:2,vehicles_with_events:2},
      native_active_series:null})});
    return new Promise((resolve,reject)=>requests.push({url,requestOptions,resolve,reject}));
  };
  const h=harness(options,withoutGeometry?null:structuredClone(geometry),null,undefined,
    {fetch,config:partial?{partial_visual_policy:structuredClone(policy)}:{}});
  h.sandbox.crypto=crypto.webcrypto;sessions.push(h);
  h.replyFixture=value=>{
    const request=requests.find(r=>!r.done && new URL(r.url,'http://localhost').pathname==='/api/window');
    assert.ok(request);request.done=true;
    assert.equal(new URL(request.url,'http://localhost').searchParams.get('visual_policy'),partial?policy.policy:null);
    request.resolve({ok:true,status:200,headers:{get:name=>badHash && name==='X-SimZ1-JSON-SHA256'?'0'.repeat(64):null},
      text:async()=>JSON.stringify(value)});
  };
  h.replyJourney=vehicle=>{
    const request=requests.findLast(r=>!r.done && new URL(r.url,'http://localhost').pathname==='/api/journey');
    assert.ok(request);request.done=true;
    assert.equal(new URL(request.url,'http://localhost').searchParams.get('visual_policy'),partial?policy.policy:null);
    const journey=vehicle==='pending-car'?'pending-trip':'valid-trip';
    const records=(vehicle==='pending-car'?[pending,dependent]:[other]).map(row=>({...structuredClone(row),Trip:structuredClone(trips[journey])}));
    request.resolve({ok:true,status:200,json:async()=>({...identity,...(partial?{visual_policy:policy.policy}:{}),
      key:journey,records,lane_replay:{events:[]}})});
  };
  return h;
}
async function settle(h) {
  for(let round=0;round<30;round++) {
    await flush();for(const [id,timer] of h.timers)if(timer.delay===0){h.timers.delete(id);timer.fn();}
    if(!h.api.getState().buffering || h.api.getState().error)break;
  }
}
async function ready(h){await settle(h);assert.equal(h.api.getState().error,null);assert.equal(h.api.getState().buffering,false);h.api.pause();}
function diagnose(h,time,vehicle){h.api.seek(time);return h.api.diagnoseVehicle(vehicle,time);}
(async()=>{
  const originalWorker=global.Worker;
  global.Worker=class {
    constructor(url){this.source=fetch(url).then(r=>r.text());}
    postMessage(data){this.source.then(source=>{
      const self={postMessage:result=>this.onmessage({data:result})};
      vm.runInNewContext(source,{self,performance,TextDecoder,Map,Set,Number,Object,Array,JSON});
      self.onmessage({data});
    }).catch(error=>this.onerror(error));}
    terminate(){}
  };
  try {
    const loader=new Loader({...identity,visual_policy:policy.policy,start_seconds:0,end_seconds:120,window_seconds:120,window_count:1});
    const decoded=await loader.decode(JSON.stringify(payload()),0,{controller:new AbortController()});
    assert.equal(decoded.mode,'worker');assert.equal(decoded.payload.visual_policy,policy.policy);
    assert.equal(decoded.prepared.queueContexts.get(key(dependent)).reason,'reconstruction_pending');
    const incompatible=payload();delete incompatible.visual_policy;
    await assert.rejects(loader.decode(JSON.stringify(incompatible),0,{controller:new AbortController()}),/Politica visual incompatible/);
  } finally {if(originalWorker===undefined)delete global.Worker;else global.Worker=originalWorker;}
  const original=JSON.stringify(payload()),h=create();h.replyFixture(payload());await ready(h);
  assert.equal(h.api.getState().hud.status,'ready');
  assert.equal(h.api.getVisualDiagnostics().visual_policy,policy.policy);
  assert.equal(h.api.getVisualDiagnostics().visual_certification,'partial_not_certified');
  assert.throws(()=>h.evaluate(`(()=>{const marker=markerAt(timelines.get('pending-car')[0],30);
    const forged={...marker,Visual_Queue_Context:{...marker.Visual_Queue_Context,checkpoint:{
      schema:'native-queue-phase-capsule-v1',complete:true,input:'tampered-source-signature',settings:visualQueueRenderer.settings}}};
    return visualQueueRenderer.frame([forged],30,transitionNeighbors,[forged]);})()`),/Checkpoint visual incompatible/,
    'partial omission must not bypass source-signature validation');
  for(const time of [30,50,30,50]) {
    const row=diagnose(h,time,'pending-car');
    assert.equal(row.visible,false);assert.equal(row.position,null);assert.equal(row.candidate_position,null);
    assert.equal(row.native_center_position,null);assert.equal(row.visual_diagnostic.native_position,null);
    assert.equal(row.visual_diagnostic.longitudinal_station_m,null);
    assert.equal(row.visual_diagnostic.body_geometry_source,'unavailable_visual_reconstruction');
    assert.equal(row.reason,'reconstruction_pending');assert.equal(h.count('trips'),1);
    assert.equal(h.api.diagnoseVehicle('valid-car',time).visible,true);
    const onDemand=h.api.getVisualDiagnostics(time+1).records.find(r=>r.vehicle_id==='pending-car');
    assert.equal(onDemand.visible,false);assert.equal(onDemand.position,null);
  }
  assert.equal(JSON.stringify(payload()),original,'native fixture source remains untouched');
  h.api.seek(30);h.evaluate('inspectClickedObject(timelines.get("pending-car")[0])');h.replyJourney('pending-car');await flush();
  assert.equal(h.api.getState().selectedVehicleId,'pending-car');assert.ok(h.count('selected-history')+h.count('selected-future')>0);
  assert.match(h.evaluate('vehiclePositionStatus.textContent'),/Posición no disponible/);
  assert.equal(h.count('vehicle-focus-halo'),0,'hidden body has no stale highlight');
  h.api.pause();const paused=h.api.getState().current;h.frame(5000);assert.equal(h.api.getState().current,paused);
  h.api.selectActive(0);h.replyJourney('valid-car');await flush();
  assert.equal(h.api.getState().selectedVehicleId,'valid-car');assert.equal(h.evaluate('vehiclePositionStatus.hidden'),true);
  assert.equal(h.evaluate('partialVisualStatus.textContent'),'Vista parcial: algunos vehículos no tienen posición verificable y pueden no aparecer.');
  assert.equal(h.evaluate('technicalHelpContent.contains(partialVisualStatus)'),true,'coverage note stays in collapsed Help');
  assert.notEqual(h.evaluate('partialVisualStatus.className'),'simz1-warning','partial coverage is not a permanent warning');
  assert.equal(h.evaluate('partialVisualStatus.title || ""'),'');
  const publicText=h.evaluate(`JSON.stringify((function walk(node){return [node.textContent,node.innerHTML,node.title,node.attributes,
    ...(node.children || []).map(walk)];})(document.body))`);
  assert.doesNotMatch(publicText,/L12|tres casos|3 casos/,'no historical case notice in text, title or accessibility attributes');
  assert.match(h.evaluate('queueStatus.textContent'),/reconstruction_pending/, 'technical omission classifications remain accessible');
  const normal=create({partial:false});normal.replyFixture(payload(false));await ready(normal);
  assert.equal(diagnose(normal,30,'pending-car').visible,true,'default incomplete-context behavior remains unchanged');
  const noGeometry=create({withoutGeometry:true});noGeometry.replyFixture(payload());await ready(noGeometry);
  assert.equal(diagnose(noGeometry,30,'pending-car').position,null);assert.equal(noGeometry.count('trips'),0,
    'missing geometry cannot establish independence from an unknown body');
  const unavailable=create(),unavailablePayload=payload();
  unavailablePayload.segments[0].Motion_Plan={status:'unavailable',fallback_reason:'missing events'};
  unavailable.replyFixture(unavailablePayload);await ready(unavailable);
  assert.equal(diagnose(unavailable,30,'pending-car').reason,'reconstruction_pending');
  assert.equal(unavailable.api.getVisualDiagnostics(31).records.find(r=>r.vehicle_id==='pending-car').position,null);
  assert.equal(unavailable.count('trips'),1);
  const neighbour=create(),neighbourPayload=payload(),neighbourRow=neighbourPayload.segments[2];
  neighbourRow.Link_ID='road';neighbourRow.path=structuredClone(pending.path);neighbourRow.timestamps=[0,40];
  neighbourRow.Motion_Plan={version:1,status:'constant',distance_m:100,cap_mps:5,phases:[[0,40,0,2.5,0]]};
  neighbour.replyFixture(neighbourPayload);await ready(neighbour);
  for(const time of [39,20,39]) {
    const row=diagnose(neighbour,time,'valid-car');
    assert.equal(row.visible,false);assert.equal(row.position,null);assert.equal(row.reason,'reconstruction_pending');
    assert.equal(row.visual_diagnostic.spacing_compatible,false,'omitting an obstacle must never turn spacing compatible');
  }
  const differentLink=create(),differentPayload=payload(),differentRow=differentPayload.segments[2];
  differentRow.Link_ID='next';differentRow.path=structuredClone(dependent.path);differentRow.timestamps=[0,40];
  differentRow.Motion_Plan={version:1,status:'constant',distance_m:100,cap_mps:5,phases:[[0,40,0,2.5,0]]};
  differentLink.replyFixture(differentPayload);await ready(differentLink);
  assert.equal(diagnose(differentLink,39,'valid-car').reason,'reconstruction_pending',
    'different link IDs do not prove independence from a connected pending body');
  const later=create(),laterPayload=payload(),laterRow=laterPayload.segments[2];
  laterRow.Link_ID='road';laterRow.path=structuredClone(pending.path);laterRow.timestamps=[100,120];
  laterRow.Motion_Plan={version:1,status:'constant',distance_m:100,cap_mps:5,phases:[[100,120,0,5,0]]};
  laterPayload.trips['valid-trip'].Departure=100;laterPayload.trips['valid-trip'].Arrival=120;
  later.replyFixture(laterPayload);await ready(later);
  assert.equal(diagnose(later,110,'valid-car').visible,true,'disjoint epochs do not manufacture a body dependency');
  const chainGeometry=structuredClone(roads);
  chainGeometry.links.third={...chainGeometry.links.next,path:[xy(200,0),xy(300,0)],from_node:'c',to_node:'f'};
  chainGeometry.links.next.allowed_to_links=['third'];
  chainGeometry.links.side={...chainGeometry.links.other,path:[xy(0,0),xy(20,0)],from_node:'s',to_node:'t'};
  chainGeometry.occupancy_corridors={schema:'corridor-length-v1',corridors:Object.fromEntries(
    [['A','road'],['B','next'],['C','third']].map(([id,link])=>[id,{link_ids:[link],represented_lanes:1}]))};
  const chainPayload=payload(),native=id=>({policy:'corridor-length-v1',corridor_id:id,model_slot:0,ordinal:1});
  const chainRows=[['road','A',0,20],['next','B',20,40],['third','C',40,80]].map(([link,id,start,end])=>({
    ...structuredClone(pending),Link_ID:link,path:chainGeometry.links[link].path,timestamps:[start,end],
    Native_Occupancy:native(id),Observed_Waits:{},Motion_Plan:{version:1,status:'constant',distance_m:100,
      cap_mps:5,phases:[[start,end,0,100/(end-start),0]]}}));
  chainRows[2].Motion_Plan={version:1,status:'kinematic',distance_m:100,cap_mps:5,hold_start:60,
    native_wait_boundary:60,phases:[[40,60,0,5,0],[60,80,100,0,0]]};
  chainRows[2].Observed_Waits={signal_red:{first:60,last:79,position_evidence:'queue_exit'}};
  chainPayload.segments=[...chainRows,{...structuredClone(other),Link_ID:'side',path:chainGeometry.links.side.path,timestamps:[50,80],
    Motion_Plan:{version:1,status:'constant',distance_m:20,cap_mps:5,phases:[[50,80,0,20/30,0]]}}];
  chainPayload.trips['valid-trip'].Departure=50;
  chainPayload.queue_context.by_seed={[key(chainRows[2])]:{complete:false,reason:'reconstruction_pending',body_position_available:false,record_keys:[]}};
  const chain=create({geometry:chainGeometry});chain.replyFixture(chainPayload);await ready(chain);
  assert.equal(diagnose(chain,60,'valid-car').reason,'reconstruction_pending',
    'recursive rear release uses all available previous corridors even across earlier native epochs');
  assert.equal(chain.api.diagnoseVehicle('valid-car',60).position,null);

  const options={...identity,visual_policy:policy.policy};
  for(const mutate of [p=>delete p.visual_policy,p=>p.visual_policy='other',p=>p.run_id='foreign',
      p=>delete p.queue_context.visual_policy,p=>p.queue_context.by_seed[key(pending)].complete=true,
      p=>p.queue_context.by_seed[key(pending)].body_position_available=true,
      p=>p.queue_context.by_seed[key(pending)].checkpoint={schema:'forged'}]) {
    const value=payload();mutate(value);assert.throws(()=>Loader.validateRecords(value,options,0,0,120));
  }
  const forged=payload();forged.queue_context.checkpoints={};forged.queue_context.checkpoint_contract={identity:{...identity,run_id:'foreign'}};
  assert.throws(()=>Loader.validateRecords(forged,options,0,0,120),'partial mode cannot swallow a malformed checkpoint signature');
  const bad=create({badHash:true});bad.replyFixture(payload());await settle(bad);
  assert.match(bad.api.getState().error,/Integridad de ventana incompatible/);assert.equal(bad.count('trips'),0);
  assert.throws(()=>harness({visual_policy:policy.policy},roads,null,undefined,
    {config:{partial_visual_policy:{...policy,native_validation:'invalid'}}}),/Contrato de visualizacion parcial incompatible/);
  console.log('PASS: partial body omission, contiguous dependencies, routes, pause/seeks, other selection, default mode, policy identity and integrity guards');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const h of sessions)h.evaluate('continuousReplay.destroy()');
});
