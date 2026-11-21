'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const classes=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+'\n({L:SimZ1VisualLanes,Q:SimZ1VisualQueues});');
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
function road(a,b,extra={}) {return {path:[xy(...a),xy(...b)],num_lanes:1,opposing_lanes:0,from_node:'a',to_node:'b',
  offset_eligible:true,lane_width_m:3,native_lanes:{},movement_source:'effective_car_node_adjacency',allowed_to_links:[],...extra};}
function session(links) {const lanes=new classes.L({schema_version:1,available:true,links});return {lanes,queues:new classes.Q(lanes)};}
function car(s,id,{link='r',time=50,hold=20,wait=true,start=0}={}) {
  const path=s.lanes.links.get(link).data.path,length=s.lanes.links.get(link).geometry.length;
  const fraction=wait ? Math.min(1,(time-start)/(hold-start)) : .5;
  const record={vehicle:id,Agent_ID:id,Replay_Journey_Key:'j:'+id,Link_ID:link,path,timestamps:[start,100],
    Vehicle_Type:'car',Motion_Plan:{version:1,status:'kinematic',distance_m:length,hold_start:wait ? hold : undefined,
      phases:wait ? [[start,hold,0,length/(hold-start),0],[hold,100,length,0,0]] : [[0,100,0,length/100,0]]},
    Observed_Waits:wait ? {signal_red:{first:hold,last:99,position_evidence:'queue_exit'}} : {}};
  return {...record,...s.lanes.marker(record,fraction,{},path[0]),Visual_Motion_Fraction:fraction,Waiting:wait && time>=hold};
}
for(const n of [2,5,10]) {
  const s=session({r:road([0,0],[100,0])}),markers=Array.from({length:n},(_,i)=>car(s,'q'+i,{start:i*.1,hold:20+i*.1}));
  const frame=s.queues.frame(markers,50);
  assert.equal(frame.markers.length,n);assert.equal(frame.omitted.length,0);assert.equal(frame.counts.unresolvedOverlaps,0);
  assert.ok(frame.markers.every(m=>m.Visual_Body_Length_Meters===4.5 && m.Visual_Body_Width_Meters===1.8));
}
const crowded=session({r:road([0,0],[2,0])}),crowd=Array.from({length:10},(_,i)=>car(crowded,'v'+i));
const crowdedFrame=crowded.queues.frame(crowd,50),posesBefore=JSON.stringify(crowdedFrame.markers);
assert.equal(crowdedFrame.markers.length,10);assert.equal(crowdedFrame.diagnostics.sampleCollisions({limit:3}).total_matches,45);
const own=crowdedFrame.diagnostics.sampleCollisions({vehicle_ids:['v9'],limit:2});
assert.equal(own.total_matches,9);assert.equal(own.returned,2);assert.equal(own.truncated,true);
assert.ok(own.records.every(row=>row.vehicles.some(v=>v.vehicle_id==='v9')),'filter identity before expanding/truncating');
assert.equal(crowdedFrame.diagnostics.summarizeCollisions().unresolved_body_overlap,45);
assert.equal(JSON.stringify(crowdedFrame.markers),posesBefore,'diagnostic expansion cannot alter poses or counts');
assert.ok(own.records.every(row=>row.physical_state==='unknown_from_queue_events' && !row.physical_incompatibility_confirmed));
assert.throws(()=>crowdedFrame.diagnostics.sampleCollisions({limit:501}));
const manyFrame=crowded.queues.frame(Array.from({length:20},(_,i)=>car(crowded,'many'+i)),50);
assert.equal(manyFrame.diagnostics.collisions.length,100);
assert.equal(manyFrame.diagnostics.collision_sample.total_pairs,190);
assert.equal(manyFrame.diagnostics.collision_sample.truncated,true);
const lastOwn=manyFrame.diagnostics.sampleCollisions({vehicle_ids:['many19'],limit:2});
assert.equal(lastOwn.total_matches,19);assert.equal(lastOwn.returned,2);
assert.ok(lastOwn.records.every(row=>row.vehicles.some(v=>v.vehicle_id==='many19')));
for(const [name,links,expected] of [
  ['crossing',{r:road([-50,0],[50,0]),s:road([0,-50],[0,50],{from_node:'c',to_node:'d'})},'body_overlap'],
  ['parallel_envelopes',{r:road([-50,0],[50,0]),s:road([-50,1.9],[50,1.9],{from_node:'c',to_node:'d'})},'safety_envelope_only']]) {
  const s=session(links),frame=s.queues.frame([car(s,'a',{wait:false}),car(s,'b',{link:'s',wait:false})],50);
  const collision=frame.diagnostics.sampleCollisions({limit:1}).records[0];
  assert.equal(frame.markers.length,2,name);assert.equal(collision.final_overlap_kind,expected);
  assert.equal(collision.same_link,false);assert.equal(collision.same_visual_lane,false);
}
// Native FORCE-shaped evidence is provenance, not a command to erase, move or
// classify a rendered body as an accident. The renderer never consumes it.
const withForce=crowd.map((m,i)=>i ? m : {...m,Native_Decision:{decision:'FORCE',time:49,source:'synthetic_fixture'}});
const forceFrame=crowded.queues.frame(withForce,50);
assert.deepEqual(plain(forceFrame.markers.map(m=>[m.vehicle,m.position,m.Visual_Body_Path])),
  plain(crowdedFrame.markers.map(m=>[m.vehicle,m.position,m.Visual_Body_Path])));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const p=[xy(0,0),xy(100,0)],r={vehicle:'v',Agent_ID:'p',Replay_Journey_Key:'j',Link_ID:'r',path:p,timestamps:[0,100],
    Motion_Plan:{version:1,status:'constant',distance_m:100,cap_mps:2,phases:[[0,100,0,1,0]]}};
  const h=harness({}, {schema_version:1,available:true,links:{r:road([0,0],[100,0])}});
  try {
    h.reply(0,{segments:[r],trips:{j:{Trip_ID:'j',Person_ID:'p',Departure:0,Arrival:100,Status:'completed',Origin_Position:p[0],Destination_Position:p[1]}},
      context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
    await flush();h.api.pause();h.api.seek(50);
    const source=JSON.stringify(h.evaluate('timelines.get("v")[0].Motion_Plan')),before=h.api.diagnoseVehicle('v',50);
    const requested=h.api.diagnoseVehicle('v',51);
    for(const row of [before,requested]) {
      assert.equal(row.body_support,'current_link');assert.equal(row.queue_reason,'moving');
      assert.equal(row.lane_source,'centerline');assert.equal(row.native_center_position_source,'estimated_link_interpolation_from_recorded_interval');
      assert.ok(Number.isFinite(row.longitudinal_station_m));
    }
    h.api.seek(51);const after=h.api.diagnoseVehicle('v',51);
    for(const key of ['body_support','queue_reason','lane_source','longitudinal_station_m','display_station_m'])
      assert.equal(requested[key],after[key],key+' must survive on-demand inspection');
    h.api.seek(50);assert.deepEqual(plain(h.api.diagnoseVehicle('v',50).position),plain(before.position));
    assert.equal(JSON.stringify(h.evaluate('timelines.get("v")[0].Motion_Plan')),source);
  } finally {h.evaluate('continuousReplay.destroy()');}
  console.log('PASS: 2/5/10 queues, crossing bodies, envelope-only conflicts, bounded identity samples, FORCE provenance and on-demand/seek evidence');
})().catch(error=>{console.error(error);process.exitCode=1;});
