'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1_facility_positions.json'),'utf8'));
const sandbox={};vm.createContext(sandbox);
const [Lanes,Queues]=vm.runInContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+'\n[SimZ1VisualLanes,SimZ1VisualQueues]',sandbox);
const lanes=new Lanes(fixture.visual_lanes),queues=new Queues(lanes),clone=value=>JSON.parse(JSON.stringify(value));
const before=JSON.stringify(fixture);
const markers=fixture.segments.map(segment=>({...segment,Visual_Motion_Fraction:0,Waiting:true,Visual_Speed_kmh:0,
  Visual_Native_Center_Position:segment.path[0],...lanes.marker(segment,0,{},segment.path[0])}));
const frame=queues.frame(markers,48000);
assert.equal(frame.counts.active,7);assert.equal(frame.counts.visible,7);assert.equal(frame.counts.omitted,0);
assert.equal(frame.counts.redistributed,0);
for(const marker of frame.markers) {
  const source=fixture.segments.find(row=>row.vehicle===marker.vehicle);
  assert.deepEqual(clone(marker.position),source.path[0],'native centre is not snapped, offset or moved');
  assert.equal(marker.Visual_Lane_Index,null,'a serial native lane never invents a lateral terminal lane');
  assert.equal(marker.Visual_Queue_Compatible,false);
  assert.equal(marker.Visual_Queue_Redistribution,false);
  assert.equal(marker.Visual_Queue_Representable,true);
  assert.equal(marker.Visual_Body_Length_Meters,source.Vehicle_Dimensions.length_m);
  assert.equal(marker.Visual_Body_Clipped,false);
  assert.ok(Number.isFinite(marker.Visual_Body_Heading_Degrees));
  assert.deepEqual(clone(marker.Motion_Plan),source.Motion_Plan);
  assert.equal(marker.Visual_Native_Facility_Position.orientation_source,'estimated_local_network_tangent');
}
assert.ok(frame.markers.some(row=>row.Visual_Queue_State==='native_facility_body_exceeds_link'),
  'short links retain the actual centre and explicitly report unsupported body extent');
assert.ok(frame.diagnostics.collisions?.length || frame.counts.unresolvedOverlaps>0,
  'coincident native bus centres must remain a diagnosed overlap, not be moved apart');
assert.equal(JSON.stringify(fixture),before,'source fixture is immutable');

const mutations=[
  row=>delete row.Trip,
  row=>row.Trip.Transit.vehicle_id='another-bus',
  row=>row.Trip.Transit.activity_intervals[0].lane_id='missing-native-lane',
  row=>row.Trip.Transit.activity_intervals[0].position_source='assumed',
  row=>row.Trip.Transit.activity_intervals[0].end+=1,
  row=>row.Boundary_Provenance.end_relative=.8,
  row=>row.Motion_Plan.status='unavailable',
  row=>row.Motion_Plan.distance_m=2,
  row=>{row.path[0][0]+=.01;row.path[1][0]+=.01;},
];
for(const mutate of mutations) {
  const row=clone(fixture.segments[0]);mutate(row);
  assert.equal(lanes.nativeFacilityPose(row),null,'inconsistent station evidence must not create a position');
}
const wrongExtent=clone(fixture.visual_lanes),first=fixture.segments[0];
const native=wrongExtent.links[first.Link_ID].native_lanes;
native[native[first.Trip.Transit.activity_intervals[0].lane_id].to_lanes[0]].start_m*=.7;
assert.equal(new Lanes(wrongExtent).nativeFacilityPose(first),null,'source fraction must match native serial lane endpoint');
const samePoint=clone(first);samePoint.Boundary_Provenance.start='entered link';samePoint.Boundary_Provenance.end='left link';
assert.equal(lanes.nativeFacilityPose(samePoint),null,'arbitrary zero-distance movement is not a native stop');
console.log('PASS: seven actual interior facility positions; exact centres, no lane assignment, explicit short-body/overlap limits and eleven rejection cases');
