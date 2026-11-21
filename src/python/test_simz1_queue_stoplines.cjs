'use strict';
// Pure display fixtures: native transition permission belongs to the Java
// policy tests, not to the distance between these estimated rigid bodies.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(n=>
  fs.readFileSync(path.join(__dirname,n),'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres],plain=x=>JSON.parse(JSON.stringify(x));
function road(points,lanes=1) {return {path:points.map(p=>xy(...p)),num_lanes:lanes,opposing_lanes:0,
  lane_width_m:3,offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{},
  movement_source:'effective_car_node_adjacency',allowed_to_links:[]};}
function setup(data=road([[0,0],[150,0]])) {
  const lanes=new Lanes({schema_version:1,available:true,links:{r:data}});return {data,lanes,q:new Queues(lanes)};
}
function held(s,id,{start=0,hold=20,end=4000,lane=0,reason='signal_red'}={}) {
  const length=s.lanes.describe('r').length_m;
  const raw={vehicle:id,Agent_ID:id,Replay_Journey_Key:'trip:'+id,Vehicle_Type:'car',Link_ID:'r',path:s.data.path,timestamps:[start,end],
    Motion_Plan:{version:1,status:'kinematic',distance_m:length,hold_start:hold,native_wait_boundary:hold,
      phases:[[start,hold,0,length/(hold-start),0],[hold,end,length,0,0]]},
    Observed_Waits:{[reason]:{first:hold,last:end-1,position_evidence:'queue_exit'}},
    Visual_Motion_Fraction:1,Visual_Speed_kmh:0,Waiting:true};
  return {...raw,...s.lanes.marker(raw,1,{},s.data.path.at(-1)),Visual_Lane_Index:lane,
    position:s.lanes.place('r',length,lane).position};
}
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
function valid(s,frame,n) {
  assert.equal(frame.markers.length,n);assert.equal(frame.omitted.length,0);assert.equal(frame.counts.unresolvedOverlaps,0);
  for(const [i,m] of frame.markers.entries()) {
    assert.equal(m.Visual_Body_Length_Meters,4.5);assert.equal(m.Visual_Body_Width_Meters,1.8);
    assert.ok(m.Visual_Queue_Stop_Clearance_Meters>=-1e-7,'every corner remains before the stop cross-section');
    assert.equal(m.Visual_Queue_Stop_Boundary.explicit,false);
    assert.equal(m.Visual_Queue_Stop_Boundary.source,'inferred_road_strip_and_visual_setback');
    for(const other of frame.markers.slice(0,i))assert.equal(s.q.envelopesOverlap(body(m),body(other)),false);
  }
}
for(const n of [2,5,10]) {
  const s=setup(),roster=Array.from({length:n},(_,i)=>held(s,'q'+i,{start:i*.1})),source=JSON.stringify(roster);
  const first=s.q.frame(roster,50);valid(s,first,n);
  for(const time of [3000,50,2000]) {
    const next=s.q.frame([...roster].reverse(),time);valid(s,next,n);
    assert.deepEqual(plain(next.markers.map(m=>[m.vehicle,m.position])),plain(first.markers.map(m=>[m.vehicle,m.position])));
  }
  assert.equal(JSON.stringify(roster),source);
}
// The former width rejection confused a safety envelope with the rigid car.
// The envelope extends into the adjacent lane, where staggering provides room.
const parallel=setup(road([[0,0],[150,0]],2));parallel.q.configure({lateral_clearance_m:.7});
valid(parallel,parallel.q.frame([held(parallel,'left'),held(parallel,'right',{lane:1})],50),2);

// A half-length subtraction alone misses the corner protruding over the line.
const bend=setup(road([[0,0],[50,0],[50,3.3]])),corner=held(bend,'corner');
const line=bend.lanes.stopBoundary('r',0,2),naiveStation=line.station_m-2.25;
const naive={...corner,Visual_Queue_Center_Meters:naiveStation,position:bend.lanes.place('r',naiveStation,0).position};
assert.ok(bend.q.stopClearance(bend.lanes.vehicleBody(naive),line)<-.1,'counterexample: centre/half-length test admits a protruding body');
const fixed=bend.q.frame([corner],50);valid(bend,fixed,1);
assert.ok(fixed.markers[0].Visual_Queue_Center_Meters<naiveStation);

// Full-receiver WAIT evidence supports the same visual line. FORCE-shaped
// provenance is not interpreted by the renderer: incomplete closure alone
// causes retention here. Actual FORCE permission belongs to the native tests.
const storage=setup();valid(storage,storage.q.frame([held(storage,'blocked',{reason:'storage_wait'})],50),1);
const forced={...held(storage,'forced'),Visual_Queue_Context:{complete:false,reason:'record_limit'},
  Native_Decision:{decision:'FORCE',time:25,source:'synthetic_fixture'}};
const raw=JSON.stringify(forced),retained=storage.q.frame([forced],50).markers[0];
assert.deepEqual(plain(retained.position),plain(forced.position));assert.equal(retained.Visual_Queue_Compatible,false);
assert.equal(retained.Visual_Queue_State,'queue_context_incomplete');assert.ok(retained.Visual_Queue_Stop_Clearance_Meters<0);
assert.equal(JSON.stringify(forced),raw);

// Strict receiver events establish WAIT at the queue exit, not centimetric
// tracking. Configured long bodies must use their own dimensions and stay in
// the same evidenced lane beyond the historical ten-second FORCE threshold.
// The recorded capacities/PCU and event plans remain outside this renderer.
for(const reason of ['signal_red','storage_wait']) {
  const s=setup(road([[0,0],[150,0]],2));
  const roster=[['bus',18,2.5,2.8,0],['truck',16.5,2.55,3.5,1]].map(([type,length,width,pcu,lane])=>{
    const row=held(s,type,{hold:20,lane,reason});
    return {...row,Vehicle_Type:type==='bus' ? 'TransitBus' : 'TransportePesado',Vehicle_PCU:pcu,
      Vehicle_Physical_Dimensions:{length_m:length,width_m:width,source:'configured_vehicle_type_fixture',
        nature:'configured',measurement_status:'not_established_by_vehicle_type'},
      Observed_Waits:{[reason]:{first:20,last:3999,position_evidence:'queue_exit',
        sources:['SimZ1_QNode_strict_receiver_v1']}}};
  });
  const untouched=JSON.stringify(roster);
  const first=s.q.frame(roster,20);
  assert.equal(first.markers.length,2);assert.equal(first.omitted.length,0);
  assert.equal(first.counts.unresolvedOverlaps,0);
  for(const time of [29.999,30,30.001,3000,20]) {
    const frame=s.q.frame(roster,time);
    assert.deepEqual(plain(frame.markers.map(m=>[m.vehicle,m.position])),
      plain(first.markers.map(m=>[m.vehicle,m.position])),'elapsed WAIT cannot release the visual hold');
    for(const original of roster) {
      const m=frame.markers.find(row=>row.vehicle===original.vehicle);
      assert.equal(m.Visual_Lane_Index,original.Visual_Lane_Index,'no display-only overtaking');
      assert.equal(m.Visual_Body_Length_Meters,original.Vehicle_Physical_Dimensions.length_m);
      assert.equal(m.Visual_Body_Width_Meters,original.Vehicle_Physical_Dimensions.width_m);
      assert.ok(m.Visual_Queue_Stop_Clearance_Meters>=-1e-7,'complete long body stays behind the boundary');
      assert.equal(m.Visual_Queue_Compatible,true);assert.equal(m.Visual_Body_Clipped,false);
      assert.equal(m.Waiting,true);assert.equal(m.Visual_Speed_kmh,0);assert.equal(m.Vehicle_PCU,original.Vehicle_PCU);
      assert.deepEqual(plain(m.Motion_Plan),plain(original.Motion_Plan));
      assert.deepEqual(plain(m.Observed_Waits),plain(original.Observed_Waits));
      const diagnostic=s.q.describePose(m);
      assert.equal(diagnostic.dimension_contract.continuous_physical_spacing_observed,false);
      assert.equal(diagnostic.dimension_contract.visual_body.source,'configured_vehicle_type_fixture');
      assert.equal(diagnostic.stop_boundary.explicit,false,'a display setback is not a surveyed stop bar');
    }
  }
  assert.equal(JSON.stringify(roster),untouched);
}

const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const data=road([[0,0],[150,0]],2);data.length_m=150;
  data.native_lanes={'r.0':{index:0,represented_lanes:1,start_m:150,to_lanes:[]},
    'r.1':{index:1,represented_lanes:1,start_m:150,to_lanes:[]}};
  const s=setup(data),car=held(s,'controlled',{end:100}),key=JSON.stringify([car.vehicle,car.Replay_Journey_Key,car.Link_ID,car.timestamps]);
  const event={vehicle:car.vehicle,link:'r',lane:'r.0',type:'entered lane',time:0};
  const metadata={Trip_ID:car.Replay_Journey_Key,Person_ID:car.Agent_ID,Departure:0,Arrival:100,Status:'completed',
    Origin_Position:data.path[0],Destination_Position:data.path[1]};
  const trips={[car.Replay_Journey_Key]:metadata},h=harness({}, {schema_version:1,available:true,links:{r:data}});
  try {
    h.evaluate('globalThis.signalGeometry={records:'+JSON.stringify([
      {Link_ID:'r',system_id:'s',group_id:'g0',signal_id:'sig0',lane_ids:['r.0'],turning_moves:[]},
      {Link_ID:'r',system_id:'s',group_id:'g1',signal_id:'sig1',lane_ids:['r.1'],turning_moves:[]},
      {Link_ID:'other',system_id:'s',group_id:'wrong',signal_id:'wrong',lane_ids:[],turning_moves:[]}])+',updateLayers:layers=>layers};');
    h.reply(0,{segments:[car],trips,context_segments:[],lane_replay:{events:[event]},
      queue_context:{schema_version:1,policy:'native-hold-closure-v1',by_seed:{[key]:{complete:true,reason:null,record_keys:[key]}},
        segments:[car],transition_segments:[],trips,lane_events:[event]},
      signal_replay:{series:[{system_id:'s',group_id:'g0',states:[[0,'RED'],[40,'GREEN']]},
        {system_id:'s',group_id:'g1',states:[[0,'GREEN']]}]}});
    await flush();h.api.pause();h.api.seek(30);
    const red=h.api.diagnoseVehicle(car.vehicle,30),green=h.api.diagnoseVehicle(car.vehicle,50);
    assert.equal(red.signal_controls.length,2,'other links cannot control this observed lane');
    assert.equal(red.signal_controls[0].applies_to_observed_movement,true);assert.equal(red.signal_controls[0].state,'RED');
    assert.equal(red.signal_controls[1].applies_to_observed_movement,false);
    assert.equal(h.evaluate('signalControlEvidence("r",null,null,30)[0].applies_to_observed_movement'),null,
      'an estimated visual lane cannot identify the signal controlling the native vehicle');
    assert.equal(green.signal_controls[0].state,'GREEN');assert.equal(green.signal_controls[0].observation_time,40);
    assert.deepEqual(plain(green.position),plain(red.position),'green alone cannot override the recorded hold/exit');
    assert.ok(red.stop_clearance_m>=-1e-7);assert.equal(red.stop_boundary.explicit,false);
    h.api.seek(50);assert.deepEqual(plain(h.api.diagnoseVehicle(car.vehicle,50).position),plain(green.position));
    h.api.seek(30);assert.deepEqual(plain(h.api.diagnoseVehicle(car.vehicle,30).position),plain(red.position));
  } finally {h.evaluate('continuousReplay.destroy()');}
  console.log('PASS: full-body stop planes, 2/5/10 stable queues, strict receiver WAIT beyond ten seconds, configured long bus/truck, adjacent-lane margins, curved corners, immutable FORCE provenance and native red/green lane scope');
})().catch(error=>{console.error(error);process.exitCode=1;});
