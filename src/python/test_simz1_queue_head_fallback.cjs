'use strict';
// An observed QNode head is separate from the missing predecessor closure.
// Only presentation is estimated; FORCE/timing/queue events stay immutable.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(n=>
  fs.readFileSync(path.join(__dirname,n),'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const scale=6371008.8*Math.PI/180,xy=x=>[x/scale,0],plain=x=>JSON.parse(JSON.stringify(x));
function setup(length=100,original=20,geometric=length) {
  const data={path:[xy(0),xy(geometric)],length_m:length,num_lanes:1,opposing_lanes:0,lane_width_m:3,offset_eligible:true,
    from_node:'a',to_node:'b',native_lanes:{'r.original':{index:null,represented_lanes:1,start_m:length,to_lanes:['r.0']},
      'r.0':{index:0,represented_lanes:1,start_m:length-original,to_lanes:[]}},allowed_to_links:[],movement_source:'effective_lane_definitions'};
  const lanes=new Lanes({schema_version:1,available:true,links:{r:data}});return {data,lanes,q:new Queues(lanes)};
}
function record(s,id='head',{start=0,hold=80,end=4000,source='MATSim15_QNode_native_branch',reason='storage_wait'}={}) {
  const length=s.data.length_m;
  return {vehicle:id,Agent_ID:id,Replay_Journey_Key:'j:'+id,Vehicle_Type:'car',Link_ID:'r',path:s.data.path,timestamps:[start,end],
    Motion_Plan:{version:1,status:'kinematic',distance_m:length,hold_start:hold,native_wait_boundary:hold,
      phases:[[start,hold,0,length/(hold-start),0],[hold,end,length,0,0]]},
    Observed_Waits:{[reason]:{first:hold,last:end-1,attempts:10,sources:[source],position_evidence:'queue_exit'}},
    Visual_Queue_Context:{complete:false,reason:'row_limit'}};
}
function marker(s,raw,time,entry=16,lane='r.0') {
  const observed=time<entry ? 'r.original' : lane,entered=time<entry ? raw.timestamps[0] : entry;
  const fraction=s.q.fractionAt(raw,time),event={vehicle:raw.vehicle,link:'r',lane:observed,type:'entered lane',time:entered};
  return {...raw,...s.lanes.marker(raw,fraction,{lane:observed,event,observed_at:time},xy(fraction*s.data.length_m)),
    Observed_Queue_ID:observed,Observed_Queue_Entry:entered,Visual_Motion_Fraction:fraction,
    Visual_Speed_kmh:time>=raw.Motion_Plan.hold_start ? 0 : s.data.length_m/(raw.Motion_Plan.hold_start-raw.timestamps[0])*3.6,
    Waiting:time>=raw.Motion_Plan.hold_start};
}
function frame(s,raw,time,entry=16) {return s.q.frame([marker(s,raw,time,entry)],time).markers[0];}
const s=setup(),raw=record(s),source=JSON.stringify(raw);
const enter=frame(s,raw,16),before=frame(s,raw,16-1e-6),nearHold=frame(s,raw,80-1e-6),held=frame(s,raw,80);
assert.ok(Math.abs((enter.position[0]-before.position[0])*scale)<.00001,'no new jump at a supported terminal entry');
assert.deepEqual(plain(enter.position),plain(marker(s,raw,16).position),'fallback starts at the existing terminal pose');
assert.ok(Math.abs((held.position[0]-nearHold.position[0])*scale)<.00001,'preparation meets the hold anchor continuously');
assert.equal(held.Visual_Queue_State,'queue_context_incomplete');assert.equal(held.Visual_Queue_Compatible,false);
assert.equal(held.Visual_Queue_Head_Projection.available,true);assert.ok(held.Visual_Queue_Stop_Clearance_Meters>=0);
assert.equal(held.Visual_Lane_Source,'native');assert.equal(held.Visual_Body_Length_Meters,4.5);assert.equal(held.Visual_Body_Width_Meters,1.8);
for(const time of [3000,80,1000,80])assert.deepEqual(plain(frame(s,raw,time).position),plain(held.position));
assert.equal(JSON.stringify(raw),source);
const stations=[16,20,30,50,70,80].map(t=>frame(s,raw,t).Visual_Queue_Center_Meters);
assert.ok(stations.every((at,i)=>i===0 || at>=stations[i-1]),'no backward relocation to activate the head fallback');
assert.equal(held.Visual_Queue_Head_Projection.original_to_terminal_continuity,'unknown_without_observed_lateral_history');

const strict=record(s,'strict',{source:'SimZ1_QNode_strict_receiver_v1',reason:'admission_conflict_executed'});
assert.equal(frame(s,strict,90).Visual_Queue_Head_Projection.available,true);
const post=record(s,'post',{source:'MATSim15_queue_post_step',reason:'congestion_queue'});
post.Observed_Waits.congestion_queue.position_evidence='unknown_queue_position';
assert.equal(frame(s,post,90).Visual_Queue_Head_Projection.available,false);
assert.equal(frame(s,raw,10).Visual_Queue_Head_Projection,undefined,'original aggregated queue cannot become a terminal head');
assert.equal(frame(s,raw,90,85).Visual_Queue_Head_Projection.available,false,'WAIT before the current lane entry is not evidence for that lane');

const second=record(s,'other',{hold:81}),ambiguous=s.q.frame([marker(s,raw,90),marker(s,second,90)],90);
assert.equal(ambiguous.markers.length,2);assert.ok(ambiguous.counts.unresolvedOverlaps>0);
for(const m of ambiguous.markers)assert.equal(m.Visual_Queue_Head_Projection.reason,'ambiguous_qnode_heads');
// Uniqueness is an interval fact, not a property of the current active roster.
// A departed contradictory head must not activate B backwards during its hold.
const departed=record(s,'departed',{hold:80,end:100}),survivor=record(s,'survivor',{hold:81,end:200});
const known=[marker(s,departed,80),marker(s,survivor,81)];
const observedSurvivor=marker(s,survivor,101);
for(const time of [90,101,150,90,101]) {
  const active=[...(time<100 ? [marker(s,departed,time)] : []),marker(s,survivor,time)];
  const result=s.q.frame(active,time,()=>({}),known);
  assert.equal(result.markers.length,active.length,'context never resurrects a departed body');
  const body=result.markers.find(m=>m.vehicle==='survivor');
  assert.equal(body.Visual_Queue_Head_Projection.reason,'ambiguous_qnode_heads');
  assert.deepEqual(plain(body.position),plain(observedSurvivor.position),'a known contradictory claim cannot disappear at another vehicle exit or seek');
  assert.equal(body.Visual_Speed_kmh,0);
}
// A raw context row without a validated domain does not supply affirmative
// head evidence; nor can an active earlier/original pose erase a known claim.
assert.equal(s.q.headWaitClaim(departed,80),null);
const preparingTime=17,lateEntry=18;
const preparing=s.q.frame([marker(s,departed,preparingTime,lateEntry),marker(s,survivor,preparingTime)],
  preparingTime,()=>({}),known);
assert.equal(preparing.markers.find(m=>m.vehicle==='survivor').Visual_Queue_Head_Projection.reason,'ambiguous_qnode_heads');
const short=setup(6,3),tooSmall=record(short);
assert.equal(frame(short,tooSmall,90,40).Visual_Queue_Head_Projection.reason,'head_body_exceeds_native_domain');

// Recorded z1_225775 boundaries/phase values from the preserved Prompt4
// native-summary: its inferred terminal entry is already past any valid head
// anchor. Keeping that limitation is mandatory; a fallback cannot reverse it.
const historic=setup(10.585954162778616,2.117190832555723,10.568314721332623);
const r=record(historic,'z1_225775',{start:24481,hold:28980,end:28990});
r.Motion_Plan.phases=[[24481,24481.00117647881,0,0,2],
  [24481.00117647881,28979.999327726393,1.384102391811283e-6,.0023529576212174184,0],
  [28979.999327726393,28980,10.585953371923468,.0023529576212174184,-3.5],
  [28980,28990,10.585954162778616,0,0]];
const unmodified=marker(historic,r,28987,28963),rejected=frame(historic,r,28987,28963);
assert.equal(rejected.Visual_Queue_Head_Projection.reason,'entry_pose_beyond_supported_stop_anchor');
assert.deepEqual(plain(rejected.position),plain(unmodified.position));assert.equal(rejected.vehicle,'z1_225775');
assert.deepEqual(plain(rejected.timestamps),[24481,28990]);
const force={...raw,Native_Decision:{decision:'FORCE',time:4000,vehicle:'head',source:'synthetic_fixture'}};
const forceResult=frame(s,force,90);
assert.deepEqual(plain(forceResult.Native_Decision),plain(force.Native_Decision));
assert.deepEqual(plain(forceResult.Motion_Plan),plain(raw.Motion_Plan));
assert.deepEqual(plain(forceResult.timestamps),plain(raw.timestamps));
console.log('PASS: strict QNode-head evidence, terminal-entry/hold continuity, absolute seek, contextual ambiguous heads after exit, small domains, 225775 rejection and immutable FORCE provenance');
