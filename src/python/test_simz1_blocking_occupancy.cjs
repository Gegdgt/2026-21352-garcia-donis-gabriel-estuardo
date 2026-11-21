'use strict';
// Reproducible metric fixtures; times and lane endpoint evidence are synthetic.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const [Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(n=>fs.readFileSync('python/'+n,'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]');
const scale=6371008.8*Math.PI/180,xy=x=>[x/scale,0];
const road={path:[xy(0),xy(200)],length_m:200,num_lanes:1,lane_width_m:3.5,opposing_lanes:0,
  offset_eligible:true,from_node:'a',to_node:'b',allowed_to_links:[],native_lanes:{q:{index:0,represented_lanes:1,start_m:200,to_lanes:[]}}};
const lanes=new Lanes({schema_version:1,links:{r:road}}),queues=new Queues(lanes,{gap_m:.1});
const evidence=[];
function waiting(id,type,start=0,reason='signal_red') {
  const raw={vehicle:id,Agent_ID:id,Replay_Journey_Key:id,Vehicle_Type:type,Link_ID:'r',path:road.path,timestamps:[start,100],
    Motion_Plan:{version:1,status:'kinematic',distance_m:200,hold_start:20,native_wait_boundary:20,
      phases:[[start,20,0,200/(20-start),0],[20,100,200,0,0]]},
    Observed_Waits:{[reason]:{first:20,last:99,position_evidence:'queue_exit'}},Visual_Motion_Fraction:1,Waiting:true};
  return {...raw,...lanes.marker(raw,1,{},xy(200))};
}
for(const type of ['TransitBus','TransportePesado','Normal','Tortuga','Motociclista'])for(const reason of ['signal_red','storage_wait']) {
  const input=[waiting('leader',type,0,reason),waiting('car','Normal',1,reason),waiting('moto','Motociclista',2,reason)];
  const before=JSON.stringify(input);
  for(const t of [21,50,99,21]) {
    const f=queues.frame(input,t),m=f.markers;
    assert.equal(m.length,3);assert.equal(f.counts.unresolvedOverlaps,0);
    for(let i=0;i<m.length;i++) {
      assert.ok(m[i].Visual_Queue_Stop_Clearance_Meters>=-1e-7);
      if(i)assert.ok((m[i-1].position[0]-m[i].position[0])*scale-(m[i-1].Visual_Body_Length_Meters+m[i].Visual_Body_Length_Meters)/2>=.1-1e-7);
    }
    evidence.push({leader_type:type,reason,time:t,visible:m.length,unresolved_overlaps:f.counts.unresolvedOverlaps,
      minimum_gap_m:Math.min(...m.slice(1).map((row,i)=>(m[i].position[0]-row.position[0])*scale-(m[i].Visual_Body_Length_Meters+row.Visual_Body_Length_Meters)/2)),
      minimum_stop_clearance_m:Math.min(...m.map(row=>row.Visual_Queue_Stop_Clearance_Meters))});
  }
  assert.equal(JSON.stringify(input),before);
}
const stop={start:10,end:100,state:'stop',source:'native_facility_events',link_id:'r',relative_position:1,
  position_source:'native_lane_membership_and_verified_lane_endpoint',lane_id:'q',facility_id:'s',is_blocking_lane:true};
const bus={vehicle:'bus',Agent_ID:'bus',Replay_Journey_Key:'bus',Vehicle_Type:'TransitBus',Link_ID:'r',path:[xy(200),xy(200)],timestamps:[10,100],
  Boundary_Provenance:{start:'VehicleArrivesAtFacility',end:'VehicleDepartsAtFacility',start_relative:1,end_relative:1},
  Trip:{Transit:{schema:'simz1-transit-replay-v1',vehicle_id:'bus',activity_intervals:[stop]}},
  Motion_Plan:{status:'stationary',distance_m:0},Visual_Motion_Fraction:0,Waiting:true};
const projected={...bus,...lanes.marker(bus,0,{},xy(200))};
const f=queues.frame([projected,waiting('car','Normal',11),waiting('moto','Motociclista',12)],30);
assert.equal(f.markers.length,3);assert.equal(f.counts.unresolvedOverlaps,0);
const b=f.markers.find(m=>m.vehicle==='bus');
assert.ok(b.Visual_Facility_Footprint_Projection);assert.ok(b.Visual_Queue_Stop_Clearance_Meters>=-1e-7);
assert.equal(b.Visual_Facility_Footprint_Projection.continuous_position_observed,false);
assert.equal(bus.path[0][0],xy(200)[0]);assert.equal(bus.Motion_Plan.status,'stationary');
// A departed bus remains context for a follower whose native hold started
// during its dwell. Window replacement must not move that frozen follower.
const shortStop=JSON.parse(JSON.stringify(bus));shortStop.timestamps[1]=25;shortStop.Trip.Transit.activity_intervals[0].end=25;
const contextBus={...shortStop,...lanes.marker(shortStop,0,{},xy(200))};
const follower=waiting('follower','Normal',11),context=[contextBus,follower];
const early=queues.frame([contextBus,follower],21,()=>({}),context).markers.find(m=>m.vehicle==='follower');
const late=queues.frame([follower],30,()=>({}),context).markers[0];
assert.deepEqual(JSON.parse(JSON.stringify(late.position)),JSON.parse(JSON.stringify(early.position)));
const single=new Lanes({schema_version:1,links:{r:{...road,native_lanes:{}}}});
const singleBus=JSON.parse(JSON.stringify(bus));singleBus.Trip.Transit.activity_intervals[0].position_source='MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment';
delete singleBus.Trip.Transit.activity_intervals[0].lane_id;
const singleMarker={...singleBus,...single.marker(singleBus,0,{},xy(200))};
const singleFrame=new Queues(single).frame([singleMarker],30);
assert.ok(singleFrame.markers[0].Visual_Facility_Footprint_Projection);
assert.ok(singleFrame.markers[0].Visual_Queue_Stop_Clearance_Meters>=-1e-7);
fs.mkdirSync('runtime/validation',{recursive:true});
fs.writeFileSync('runtime/validation/occupancy-fixtures.json',JSON.stringify({scope:'synthetic production-renderer metric fixtures; not native centimetric measurements',cases:evidence,
  blocking_facility_projection:b.Visual_Facility_Footprint_Projection,departed_stop_context_preserved:true,single_queue_without_lane_assignment:true},null,2));
console.log('PASS: bus/truck/car/tortoise/motorcycle FIFO, 0.10m, signal/storage stop lines, blocking facility footprint, immutable source, repeat seek');
