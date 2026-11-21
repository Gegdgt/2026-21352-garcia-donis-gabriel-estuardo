'use strict';
// Synthetic regression for a complete FIFO closure: a HOLD follower behind a
// forming bus whose predecessor has transferred to the next corridor.
// No native events, server, SQLite, browser or QSim. Optional saved JS baseline.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const queueSource=process.env.SIMZ1_QUEUE_SOURCE || path.join(__dirname,'simz1_visual_queues.js');
const [Lanes,Queues]=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\n'+
  fs.readFileSync(queueSource,'utf8')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]',{});
const scale=6371008.8*Math.PI/180,xy=(x,y=0)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,epsilon=1e-6)=>assert.ok(Math.abs(a-b)<epsilon,`${a} != ${b}`);
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
function setup(){
  const road=(x0,x1,from,to,next=[])=>({path:[xy(x0),xy(x1)],num_lanes:1,lane_width_m:3.5,opposing_lanes:0,
    offset_eligible:true,from_node:from,to_node:to,native_lanes:{},allowed_to_links:next,movement_source:'effective_car_node_adjacency'});
  const links={a:road(0,100,'in','joint',['b']),b:road(100,200,'joint','out'),other:road(0,100,'x','y')};
  links.other.path=[xy(0,20),xy(100,20)];
  const lanes=new Lanes({schema_version:1,available:true,links,occupancy_corridors:{schema:'corridor-length-v1',corridors:
    Object.fromEntries(Object.keys(links).map(k=>[k,{link_ids:[k],represented_lanes:1}]))}});
  return {lanes,links,q:new Queues(lanes,{gap_m:.1})};
}
function record(f,id,link,start,hold,end,ordinal,f0=0){
  const distance=(1-f0)*100,stop=hold??end;
  return {vehicle:id,Agent_ID:id,Replay_Journey_Key:'trip:'+id,Link_ID:link,
    Vehicle_Type:'bus',Vehicle_Dimensions:{length_m:12,width_m:2.5,source:'synthetic_fixture',assumed:true},
    path:[f.lanes.place(link,f0*100,0).position,f.links[link].path[1]],timestamps:[start,end],
    Native_Occupancy:{policy:'corridor-length-v1',corridor_id:link,model_slot:0,ordinal},
    Boundary_Provenance:{start:'entered link',end:'left link',start_relative:f0,end_relative:1},
    Motion_Plan:{version:1,status:'kinematic',distance_m:distance,...(hold==null?{}:{hold_start:hold,native_wait_boundary:hold}),
      phases:[[start,stop,0,distance/(stop-start),0],...(hold==null?[]:[[hold,end,distance,0,0]])]},
    Observed_Waits:hold==null?{}:{signal_red:{first:hold,last:end-1,position_evidence:'queue_exit',sources:['MATSim15_QNode_native_branch']}},
    Visual_Queue_Context:{complete:true,role:'resolved_anchor'}};
}
function marker(f,r,t){
  const fraction=f.q.fractionAt(r,t);
  return {...r,...f.lanes.marker(r,fraction,{},r.path[0]),Visual_Motion_Fraction:fraction,Visual_Distance_m:fraction*r.Motion_Plan.distance_m};
}
function fixture(){
  const f=setup(),prior=record(f,'front','a',0,5,10,1),front=record(f,'front','b',10,null,20,100),
    forming=record(f,'forming','a',8,15,30,2,.95),held=record(f,'held','a',9,10,30,3);
  const raw=[prior,front,forming,held],roster=raw.map(r=>marker(f,r,r.Motion_Plan.hold_start??r.timestamps[0]));
  const neighbors=m=>m.vehicle==='front'?m.Link_ID==='a'?{next:front}:{previous:prior}:{};
  return {...f,raw,roster,neighbors,prior,front,forming,held};
}
function render(f,time,{reverse=false,q=f.q}={}){
  let active=f.raw.filter(r=>r.timestamps[0]<=time&&time<r.timestamps[1]).map(r=>marker(f,r,time));
  if(reverse)active.reverse();return q.frame(active,time,f.neighbors,f.roster);
}
const f=fixture(),saved=JSON.stringify(f.raw),report=[];
let frozen;
for(const time of [10,10.001,11,14.999,15,19.999,20,29.999,10]){
  const frame=render(f,time),a=frame.markers.find(m=>m.vehicle==='forming'),b=frame.markers.find(m=>m.vehicle==='held');
  assert.equal(frame.markers.length,f.raw.filter(r=>r.timestamps[0]<=time&&time<r.timestamps[1]).length,'all supported bodies retained');
  assert.equal(frame.omitted.length,0);assert.equal(f.q.envelopesOverlap(body(a),body(b)),false,'HOLD must include the forming predecessor\'s transitive FIFO constraint');
  assert.equal(b.Visual_Queue_State,'queued');
  if(frozen)assert.deepEqual(plain(b.position),frozen,'HOLD never drifts when its predecessor leaves');
  frozen=plain(b.position);
  const cold=render(f,time,{reverse:true,q:new Queues(f.lanes,{gap_m:.1})}).markers.find(m=>m.vehicle==='held');
  assert.deepEqual(plain(cold.position),frozen,'cold and reverse traversal equal warm seeks');
  report.push({time,forming:a.Visual_Queue_Center_Meters,held:b.Visual_Queue_Center_Meters});
}
assert.equal(JSON.stringify(f.raw),saved,'native identity, intervals, geometry and Motion_Plan immutable');
const beforeHold=render(f,9.999999).markers.find(m=>m.vehicle==='held');
assert.ok(Math.abs(beforeHold.position[0]-frozen[0])*scale<.001,'continuous approach to frozen HOLD');

// No observed transition means no inferred leader relation across corridors.
const disconnected=fixture();disconnected.neighbors=()=>({});
const without=render(disconnected,10).markers.find(m=>m.vehicle==='held');
assert.ok(without.Visual_Queue_Center_Meters>report[0].held+5,'unknown ancestry is not silently invented');

// An unrecorded trajectory must stay unavailable; a complete closure does not
// authorize manufacturing either its pose or its predecessor constraints.
const missing=fixture();missing.forming.Motion_Plan={status:'unavailable',fallback_reason:'fixture_missing_native_motion',distance_m:5,phases:[]};
missing.roster=missing.raw.map(r=>marker(missing,r,r.Motion_Plan.hold_start??r.timestamps[0]));
const unavailable=render(missing,10);
assert.equal(unavailable.omitted.find(m=>m.vehicle==='forming').Visual_Queue_State,'motion_unavailable');
assert.ok(!unavailable.markers.some(m=>m.vehicle==='forming'));

// A complete member's anchor cannot upgrade a seed whose closure is missing.
const partial=fixture();partial.held.Visual_Queue_Context={complete:false,reason:'fixture_missing_predecessor'};
partial.roster=partial.raw.map(r=>marker(partial,r,r.Motion_Plan.hold_start??r.timestamps[0]));
const uncertain=render(partial,10).markers.find(m=>m.vehicle==='held');
assert.equal(uncertain.Visual_Queue_State,'queue_context_incomplete');assert.equal(uncertain.Visual_Queue_Compatible,false);

// A foreign corridor is not a FIFO predecessor.
const foreign=fixture(),unrelated=record(foreign,'unrelated','other',0,11,50,0);
foreign.raw.push(unrelated);foreign.roster.push(marker(foreign,unrelated,11));
near(render(foreign,10).markers.find(m=>m.vehicle==='held').Visual_Queue_Center_Meters,report[0].held);

// Future HOLD anchors remain real dependencies, including a leader whose own
// predecessor enters after the follower's HOLD. Never prune by HOLD time alone.
const future=setup(),root=record(future,'root','a',9,10,50,3),next=record(future,'future','a',0,11,50,2),
  earlier=record(future,'later-predecessor','a',10.1,10.5,50,1);
const rootAt12=marker(future,root,12),all=[root,next,earlier].map(r=>marker(future,r,r.Motion_Plan.hold_start));
const full=new Queues(future.lanes,{gap_m:.1}).frame([rootAt12],12,()=>({}),all).markers[0];
const incomplete=new Queues(future.lanes,{gap_m:.1}).frame([rootAt12],12,()=>({}),all.slice(0,2)).markers[0];
assert.notEqual(full.Visual_Queue_Center_Meters,incomplete.Visual_Queue_Center_Meters,'future same-group predecessor remains necessary');
console.log(JSON.stringify({status:'PASS',cases:6,samples:report},null,2));
