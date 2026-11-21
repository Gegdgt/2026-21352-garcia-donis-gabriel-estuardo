'use strict';
// Serial queue domains use effective native metadata and time-valid lane events.
// Continuous centres remain estimates. No browser, server, SQLite or simulation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],plain=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,e=.001)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
function road({length=100,original=20,lanes=1,points=[[0,0],[100,0]]}={}) {
  const ids=Array.from({length:lanes},(_,i)=>'r.lane.'+i);
  return {path:points.map(p=>xy(...p)),length_m:length,num_lanes:lanes,opposing_lanes:0,lane_width_m:3,
    from_node:'a',to_node:'b',offset_eligible:true,movement_source:'effective_car_node_adjacency',allowed_to_links:[],
    native_lanes:{'r.original':{index:null,represented_lanes:lanes,start_m:length,to_lanes:ids},
      ...Object.fromEntries(ids.map((id,index)=>[id,{index,represented_lanes:1,start_m:length-original,to_lanes:[]}]))}};
}
function setup(data=road()) {const lanes=new Lanes({schema_version:1,available:true,links:{r:data}});return {data,lanes,q:new Queues(lanes)};}
function observed(s,id='v',{fraction=.8,lane='r.original',time=50,eventTime=0,wait=false}={}) {
  const raw={vehicle:id,Agent_ID:id,Replay_Journey_Key:'j:'+id,Link_ID:'r',Vehicle_Type:'car',path:s.data.path,timestamps:[0,100],
    Motion_Plan:{version:1,status:'constant',distance_m:s.data.length_m,phases:[[0,100,0,s.data.length_m/100,0]],
      ...(wait ? {hold_start:20,native_wait_boundary:20} : {})},
    Observed_Waits:wait ? {signal_red:{first:20,last:99,position_evidence:'queue_exit'}} : {},
    Visual_Speed_kmh:wait ? 0 : 3.6,Visual_Motion_Fraction:fraction,Waiting:wait,
    Observed_Queue_ID:lane,Observed_Queue_Entry:eventTime};
  const event={vehicle:id,type:'entered lane',lane,link:'r',time:eventTime};
  const observation={lane,event,observed_at:time};
  return {raw,observation,marker:{...raw,...s.lanes.marker(raw,fraction,observation,s.data.path[0])}};
}
const s=setup(),a=observed(s),source=JSON.stringify(a.raw);
assert.equal(a.marker.Visual_Lane_Index,null);assert.equal(a.marker.Visual_Lane_Source,'centerline');
near(a.marker.position[0]*scale,20);near(a.marker.Visual_Native_Queue_Extent.from_m,0);
near(a.marker.Visual_Native_Queue_Extent.to_m,20);
assert.equal(a.marker.Visual_Queue_Extent_Projection.applied,true);
assert.equal(a.marker.Visual_Queue_Extent_Projection.continuous_position_observed,false);
near(a.marker.Visual_Queue_Extent_Projection.source_station_m,80);
near(a.marker.Visual_Queue_Extent_Projection.projected_station_m,20);
assert.equal(JSON.stringify(a.raw),source,'raw Motion_Plan and timing are immutable');
const body=s.lanes.vehicleBody(a.marker);near(body.position[0]*scale,20);near(body.length_m,4.5);near(body.width_m,1.8);

// A shared original queue can represent two terminal lanes without identifying
// a parallel lane. Unequal downstream starts do not justify a guessed domain.
const multi=setup(road({lanes:2})),multiCar=observed(multi);
assert.equal(multiCar.marker.Visual_Native_Queue_Extent.available,true);
assert.equal(multiCar.marker.Visual_Lane_Index,null);
const ambiguousData=road({lanes:2});ambiguousData.native_lanes['r.lane.1'].start_m=70;
const ambiguous=setup(ambiguousData),unknown=observed(ambiguous);
assert.equal(unknown.marker.Visual_Native_Queue_Extent.available,false);
assert.equal(unknown.marker.Visual_Queue_Extent_Projection,null);
near(unknown.marker.position[0]*scale,80);assert.equal(unknown.marker.Visual_Lane_Index,null);
assert.equal(ambiguous.q.frame([unknown.marker],50).markers.length,1);

// Domain acceptance requires an observation belonging to this interval/vehicle.
for(const edit of [
  (raw,o)=>{o.event.vehicle='other';},(raw,o)=>{o.event.link='other';},
  (raw,o)=>{o.event.type='left lane';},(raw,o)=>{o.event.time=-1;},
  (raw,o)=>{o.event.time=51;},(raw,o)=>{raw.timestamps=[NaN,100];},
  (raw,o)=>{raw.timestamps=[0,undefined];},(raw,o)=>{raw.timestamps=[100,0];}
]) {
  const x=observed(s);edit(x.raw,x.observation);
  assert.equal(s.lanes.marker(x.raw,.8,x.observation,s.data.path[0]).Visual_Native_Queue_Extent,undefined);
}

// Native metres are not geometric metres. The projected centre follows the
// validated polyline, not its endpoint chord, and the rigid body is not clipped.
const curved=setup(road({length:200,original:120,points:[[0,0],[50,0],[50,50]]}));
const curve=observed(curved),curveBody=curved.lanes.vehicleBody(curve.marker);
near(curve.marker.Visual_Native_Queue_Extent.to_m,120);
near(curve.marker.Visual_Native_Queue_Extent.geometry_to_m,60);
near(curveBody.position[0]*scale,50);near(curveBody.position[1]*scale,10);
near(curveBody.length_m,4.5);near(curveBody.width_m,1.8);

// Terminal membership has a lateral index, but still bounds its serial centre.
const terminal=observed(s,'terminal',{fraction:.05,lane:'r.lane.0'});
assert.equal(terminal.marker.Visual_Lane_Source,'native');assert.equal(terminal.marker.Visual_Lane_Index,0);
near(terminal.marker.position[0]*scale,20);
const terminalFrame=s.q.frame([terminal.marker],50);
assert.equal(terminalFrame.markers.length,1);
assert.ok(terminalFrame.markers[0].position[0]*scale>=20-.001,'solver cannot move back into original queue');
const entry={marker:terminal.marker,dimensions:{length_m:4.5,width_m:1.8}};
assert.equal(s.q.pose(entry,19,true,()=>({})),null);
assert.equal(s.q.pose(entry,101,true,()=>({})),null);
near(s.q.pose(entry,25,true,()=>({})).body.position[0]*scale,25);
assert.equal(s.q.pose({...entry,upstream:{marker:{...terminal.marker,Visual_Native_Queue_Extent:null},length:100}},
  -1,true,()=>({})),null,'a preceding interval cannot move a currently observed terminal queue to another link');

// Recorded transitions can inform heading, but must not shift the bounded
// centre toward the neighbouring link's differently offset endpoint.
const current=road({lanes:2}),previous={...road({lanes:2,points:[[-100,0],[0,0]]}),from_node:'p',to_node:'a',allowed_to_links:['r']};
const transitionLanes=new Lanes({schema_version:1,available:true,links:{r:current,p:previous}});
const transitionSession={data:current,lanes:transitionLanes},first=observed(transitionSession,'turn',{fraction:0,lane:'r.original'}).marker;
const before={...first,Link_ID:'p',path:previous.path,timestamps:[-100,0],Visual_Lane_Index:0};
const transitionBody=transitionLanes.vehicleBody(first,{previous:before});
assert.deepEqual(plain(transitionBody.position),plain(first.position));

// Impossible storage is explicit: all 2/5/10 full-sized bodies remain present,
// and coincident projected centres cannot be called resolved spacing.
for(const n of [2,5,10]) {
  const crowded=setup(road({length:10.586,original:2.117,points:[[0,0],[10.586,0]]}));
  const markers=Array.from({length:n},(_,i)=>observed(crowded,'q'+i,{fraction:.95,wait:true}).marker);
  const frame=crowded.q.frame(markers,50);
  assert.equal(frame.markers.length,n);assert.equal(frame.omitted.length,0);
  assert.equal(frame.counts.incompatiblePosition,n);assert.equal(frame.counts.overlapsResolved,0);
  assert.equal(frame.diagnostics.summarizeCollisions().unresolved_body_overlap,n*(n-1)/2);
  for(const m of frame.markers) {
    near(m.position[0]*scale,2.117);near(m.Visual_Body_Length_Meters,4.5);near(m.Visual_Body_Width_Meters,1.8);
    assert.equal(m.Visual_Lane_Index,null);assert.equal(m.Visual_Queue_Compatible,false);
  }
}

const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const h=harness({}, {schema_version:1,available:true,links:{r:road()}}),raw=observed(s).raw;
  try {
    h.reply(0,{segments:[raw],trips:{'j:v':{Trip_ID:'j:v',Person_ID:'v',Departure:0,Arrival:100,Status:'completed',
      Origin_Position:raw.path[0],Destination_Position:raw.path[1]}},context_segments:[],
      lane_replay:{events:[{vehicle:'v',link:'r',lane:'r.original',time:0,type:'entered lane'},
        {vehicle:'v',link:'r',lane:'r.original',time:70,type:'left lane'},
        {vehicle:'v',link:'r',lane:'r.lane.0',time:70,type:'entered lane'}]},signal_replay:{series:[]}});
    await flush();h.api.pause();h.api.seek(50);
    const original=h.api.diagnoseVehicle('v',50),planned=JSON.stringify(h.evaluate('timelines.get("v")[0].Motion_Plan'));
    near(original.position[0]*scale,20);assert.equal(original.observed_lane_id,'r.original');
    assert.equal(original.visual_lane,null);assert.equal(original.queue_extent_projection.applied,true);
    const later=h.api.diagnoseVehicle('v',80);assert.equal(later.observed_lane_id,'r.lane.0');
    h.api.seek(80);assert.deepEqual(plain(h.api.diagnoseVehicle('v',80).position),plain(later.position));
    h.api.seek(50);assert.deepEqual(plain(h.api.diagnoseVehicle('v',50).position),plain(original.position));
    assert.equal(JSON.stringify(h.evaluate('timelines.get("v")[0].Motion_Plan')),planned);
  } finally {h.evaluate('continuousReplay.destroy()');}
  console.log('PASS: native serial original/terminal domains, geometry scale/curve, ambiguous/stale evidence, full bodies, 2/5/10 storage, solver bounds, on-demand and seek');
})().catch(error=>{console.error(error);process.exitCode=1;});
