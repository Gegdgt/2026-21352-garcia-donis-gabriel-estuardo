// Small deterministic geometry fixtures: no MATSim, server, browser or replay IO.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=['simz1_visual_lanes.js','simz1_visual_queues.js'].map(file=>fs.readFileSync(path.join(__dirname,file),'utf8')).join('\n');
const sandbox={};vm.createContext(sandbox);
const [VisualLanes,VisualQueues]=vm.runInContext(source+'\n[SimZ1VisualLanes,SimZ1VisualQueues];',sandbox);
const metres=6371008.8*Math.PI/180,clone=value=>JSON.parse(JSON.stringify(value));
function near(actual,expected,tolerance=1e-7) {assert.ok(Math.abs(actual-expected)<=tolerance,`${actual} ~= ${expected}`);}
function setup(length=100,count=1,extra={}) {
  const road={num_lanes:count,path:[[0,0],[length/metres,0]],length_m:length,lane_width_m:3,
    offset_eligible:true,opposing_lanes:0,native_lanes:{},...extra};
  const lanes=new VisualLanes({schema_version:1,start_reference:'link_end',links:{road}});
  return {lanes,queue:new VisualQueues(lanes),road};
}
function marker(fixture,vehicle,time,options={}) {
  const start=options.start ?? 10,hold=options.hold ?? 20,end=options.end ?? 200;
  const length=fixture.lanes.describe('road').length_m;
  const fraction=Math.max(0,Math.min(1,(time-start)/(hold-start)));
  const segment={vehicle,Link_ID:'road',path:fixture.road.path,timestamps:[start,end],
    Motion_Plan:{version:1,distance_m:length,hold_start:hold,native_wait_boundary:hold,
      phases:[[start,hold,0,length/(hold-start),0],[hold,end,length,0,0]]},
    Observed_Waits:options.waits ?? {signal_red:{first:hold,last:end-1,attempts:3,
      sources:['MATSim15_QNode_native_branch'],position_evidence:'queue_exit'}},
    Waiting:time>=hold,Visual_Speed_kmh:time>=hold ? 0 : length/(hold-start)*3.6,
    Visual_Distance_m:fraction*length,Visual_Motion_Fraction:fraction};
  const observation=options.nativeLane ? {lane:options.nativeLane,event:{type:'entered lane',link:'road',
    lane:options.nativeLane,vehicle,time:options.observedEntry ?? start}} : {};
  return {...segment,...fixture.lanes.marker(segment,fraction,observation,[fraction*length/metres,0]),
    Observed_Queue_ID:options.nativeLane ?? null,Observed_Queue_Entry:options.observedEntry ?? start};
}
function byVehicle(frame) {return Object.fromEntries(frame.markers.map(m=>[m.vehicle,m]));}
function positions(frame) {return Object.fromEntries(frame.markers.map(m=>[m.vehicle,m.position]));}
function partition(frame) {
  assert.equal(frame.counts.waitingEvidence,frame.counts.positioned+frame.counts.overflow+frame.counts.unrepresentable);
  assert.equal(frame.counts.active,frame.counts.visible+frame.counts.omitted);
  assert.equal(new Set([...frame.markers,...frame.omitted].map(m=>m.vehicle)).size,frame.counts.active);
}
function fullBodies(frame,length) {
  for(const m of frame.markers.filter(m=>m.Visual_Queue_Source)) {
    near(m.Visual_Body_Length_Meters,4.5);assert.equal(m.Visual_Body_Clipped,false);
    assert.equal(m.Visual_Body_Path.length,2,'a rigid body never bends along the road');
    assert.ok(m.Visual_Body_Width_Meters>0 && m.Visual_Body_Width_Meters<=1.8);
    assert.ok(m.Visual_Queue_Opacity>0 && m.Visual_Body_Opacity>0);
    assert.ok(m.Visual_Body_Path.every(p=>p.every(Number.isFinite)));
  }
}
const straight=setup(),input=['a','b','c'].map(id=>marker(straight,id,50)),before=JSON.stringify(input);
const queued=straight.queue.frame(input,50),cars=byVehicle(queued);
assert.equal(queued.counts.waitingEvidence,3);assert.equal(queued.counts.positioned,3);partition(queued);fullBodies(queued,100);
near(cars.a.Visual_Queue_Center_Meters,95.75);near(cars.a.Visual_Queue_Center_Meters-cars.b.Visual_Queue_Center_Meters,6.5);
near(cars.b.Visual_Queue_Center_Meters-cars.c.Visual_Queue_Center_Meters,6.5);
assert.ok(cars.a.Visual_Queue_Center_Meters+2.25<=98,'front bumper stays behind inferred stop setback');
assert.equal(cars.a.Visual_Queue_Source,'estimated_spacing_native_wait');
assert.equal(cars.a.Waiting,true);assert.equal(cars.a.Visual_Speed_kmh,0);
assert.deepEqual(clone(cars.a.Motion_Plan),clone(input[0].Motion_Plan));
assert.equal(JSON.stringify(input),before,'no input paths, native fields or Motion_Plan changes');
assert.deepEqual(clone(positions(straight.queue.frame([...input].reverse(),50))),clone(positions(queued)),'array ordering cannot alter positions');
const withDifferentPredecessors=input.map((m,index)=>({...clone(m),Observed_Queue_Entry:119-index}));
assert.deepEqual(clone(positions(straight.queue.frame(withDifferentPredecessors,50))),clone(positions(queued)),'window lane predecessor does not reorder the roster');

const early=straight.queue.frame([marker(straight,'forming',10.001)],10.001);
assert.equal(early.counts.overflow,0,'a body entering a slot that fits is not capacity overflow');
assert.equal(early.counts.unrepresentable,0);assert.equal(early.markers[0].Visual_Queue_State,'forming');
const forming1=straight.queue.frame([marker(straight,'forming',15)],15).markers[0];
const forming2=straight.queue.frame([marker(straight,'forming',15.00001)],15.00001).markers[0];
assert.equal(forming1.Visual_Queue_State,'forming');assert.ok(Math.abs(forming2.position[0]-forming1.position[0])*metres<.001);

const short=setup(12),shortFrame=short.queue.frame(['a','b','c','d'].map(id=>marker(short,id,50)),50);
assert.equal(shortFrame.counts.incompatiblePosition,3);partition(shortFrame);fullBodies(shortFrame,12);
assert.equal(shortFrame.omitted.length,0);assert.equal(shortFrame.markers.length,4,'known native bodies remain visible with explicit incompatibility');
assert.equal(shortFrame.markers.filter(m=>m.Visual_Diagnostic?.constraint_violation===true).length,3);
assert.equal(shortFrame.markers.filter(m=>m.Visual_Queue_Compatible===false).length,4,
  'the first body is also incompatible when it intersects a retained native body');
assert.ok(shortFrame.counts.unresolvedOverlaps>0);
assert.equal(new Set(shortFrame.diagnostics.collisions.filter(row=>row.resolution==='unresolved')
  .flatMap(row=>row.vehicles.map(vehicle=>vehicle.vehicle_id))).size,4);
assert.deepEqual([...shortFrame.markers,...shortFrame.omitted].map(m=>m.vehicle).sort(),['a','b','c','d']);
const terminal=setup(100,1,{native_lanes:{terminal:{index:0,represented_lanes:1,start_m:12},original:{index:null,represented_lanes:1,start_m:100}}});
const limited=terminal.queue.frame(['a','b','c'].map(id=>marker(terminal,id,50,{nativeLane:'terminal'})),50);
assert.equal(limited.markers.length,3);assert.equal(limited.counts.incompatiblePosition,2);
assert.equal(limited.markers[0].Visual_Queue_Storage_Meters,12);
assert.equal(limited.markers[0].Visual_Queue_Storage_Source,'native_lane_extent_visual_capacity');
const nativeOrder=setup(100,1,{native_lanes:{terminal:{index:0,represented_lanes:1,start_m:80}}});
const nativeOrdered=byVehicle(nativeOrder.queue.frame([
  marker(nativeOrder,'a',50,{nativeLane:'terminal',observedEntry:12}),
  marker(nativeOrder,'b',50,{nativeLane:'terminal',observedEntry:11})],50));
assert.ok(nativeOrdered.b.Visual_Queue_Center_Meters>nativeOrdered.a.Visual_Queue_Center_Meters,'observed entry to the current native lane orders its queue');
assert.equal(nativeOrdered.b.Visual_Queue_Order_Source,'native_lane_entry');
assert.equal(nativeOrdered.b.Visual_Queue_Entry_Seconds,11);
const shared=terminal.queue.frame(['a','b','c'].map(id=>marker(terminal,id,50,{nativeLane:'original'})),50);
assert.equal(shared.counts.positioned,3,'shared upstream lane does not invent a unique terminal region');
assert.equal(shared.markers[0].Visual_Queue_Storage_Source,'link_geometry_visual_capacity');
const shorterEffective=setup(100,1,{length_m:12});
assert.equal(shorterEffective.queue.frame(['a','b'].map(id=>marker(shorterEffective,id,50)),50).counts.incompatiblePosition,1,'effective length also bounds compatible storage when chord is longer');

const unknown={congestion_queue:{first:20,last:100,sources:['MATSim15_queue_post_step'],position_evidence:'unknown_queue_position'}};
assert.equal(straight.queue.frame([marker(straight,'unknown',15,{waits:unknown})],15).counts.unknownPositionWait,0);
const unknownFrame=straight.queue.frame([marker(straight,'unknown',30,{waits:unknown})],30);
assert.equal(unknownFrame.counts.unknownPositionWait,1);assert.equal(unknownFrame.counts.waitingEvidence,1);
assert.equal(unknownFrame.markers.length,1,'unknown WAIT plus a validated endpoint hold supports estimated spacing, not a measured position');
near(unknownFrame.markers[0].Visual_Queue_Center_Meters,95.75);
assert.equal(unknownFrame.counts.bodyUnrepresentable,0);
const residual=straight.queue.frame([marker(straight,'residual',15,{waits:{}})],15);
assert.equal(residual.counts.waitingEvidence,0);assert.equal(residual.markers.length,1);
const noStationary=marker(straight,'not-stopped',15);noStationary.Motion_Plan.phases=[[10,200,0,100/190,0]];
assert.equal(straight.queue.frame([noStationary],15).counts.waitingEvidence,0,'WAIT record alone does not override native motion');
const malformed=marker(straight,'malformed',15);malformed.Motion_Plan.phases={};
assert.equal(straight.queue.frame([malformed],15).counts.waitingEvidence,0,'malformed phases fail closed without inventing a queue');

const multi=setup(100,2,{native_lanes:{left:{index:0,represented_lanes:1,start_m:80},right:{index:1,represented_lanes:1,start_m:80}}});
const parallel=multi.queue.frame([marker(multi,'left',50,{nativeLane:'left'}),marker(multi,'right',50,{nativeLane:'right'})],50);
assert.equal(parallel.counts.positioned,2);fullBodies(parallel,100);
const parallelCars=byVehicle(parallel);assert.ok(parallelCars.left.position[1]>parallelCars.right.position[1]);
const crossSeparation=(parallelCars.left.position[1]-parallelCars.right.position[1])*metres;
assert.ok(parallelCars.left.Visual_Body_Width_Meters<=crossSeparation,'tapered lane body fits its lateral strip');
const narrow=setup(100,1,{lane_width_m:.5});
const narrowFrame=narrow.queue.frame([marker(narrow,'narrow',50)],50);
assert.equal(narrowFrame.markers.length,1);assert.equal(narrowFrame.omitted.length,0);
assert.equal(narrowFrame.markers[0].Visual_Queue_State,'body_geometry_unavailable');
assert.equal(narrowFrame.markers[0].Visual_Queue_Compatible,false);
near(narrowFrame.markers[0].Visual_Body_Width_Meters,1.8); // Never shrink the car or widen the road.
const reverse=setup(100,1,{path:[[100/metres,0],[0,0]],reverse_link:'out',opposing_lanes:1});
const reverseCar=reverse.queue.frame([marker(reverse,'reverse',50)],50).markers[0];
assert.ok(reverseCar.position[1]>0,'body remains on right side of reverse direction');
assert.ok(reverseCar.Visual_Body_Path.every(p=>p[0]>=0 && p[0]*metres<=100));
const curve=setup(100,1,{path:[[0,0],[50/metres,0],[50/metres,50/metres]]});
const curveFrame=curve.queue.frame([marker(curve,'curve',50)],50);assert.equal(curveFrame.counts.positioned,1);
assert.ok(curveFrame.markers[0].Visual_Body_Path.every(p=>p.every(Number.isFinite)));

const windowCars=t=>['a','b'].map(id=>marker(straight,id,t,{start:100,hold:110,end:160}));
const leftWindow=straight.queue.frame(windowCars(119.999),119.999),rightWindow=straight.queue.frame(clone(windowCars(120.001)),120.001);
assert.deepEqual(clone(positions(leftWindow)),clone(positions(rightWindow)),'internal 120 s boundary does not rebuild positions');
straight.queue.frame(windowCars(150),150);
assert.deepEqual(clone(positions(straight.queue.frame(windowCars(119.999),119.999))),clone(positions(leftWindow)),'seek and history do not affect absolute-time placement');
const leader=t=>marker(straight,'a',t,{start:10,hold:20,end:120});
const follower=t=>marker(straight,'b',t,{start:11,hold:21,end:160});
const beforeEnd=byVehicle(straight.queue.frame([leader(119.999),follower(119.999)],119.999)).b;
const afterEnd=byVehicle(straight.queue.frame([follower(120.001)],120.001,undefined,[leader(119.999),follower(120.001)])).b;
assert.ok(beforeEnd && afterEnd);
near(beforeEnd.Visual_Queue_Center_Meters,89.25); // No early release inside a stopped phase.
near(afterEnd.Visual_Queue_Center_Meters,89.25); // A recorded stopped phase cannot jump after the predecessor exits.
for(const time of [198,198.5,199,199.5,199.99]) {
  const frame=straight.queue.frame(['a','b','c'].map(id=>marker(straight,id,time)),time);partition(frame);fullBodies(frame,100);
  assert.equal(frame.markers.length,3,'simultaneous exit times never collapse the queue before exit');
  const row=byVehicle(frame);near(row.a.Visual_Queue_Center_Meters-row.b.Visual_Queue_Center_Meters,6.5);
  near(row.b.Visual_Queue_Center_Meters-row.c.Visual_Queue_Center_Meters,6.5);
  assert.ok(row.a.Visual_Queue_Center_Meters+2.25<=98);
  assert.ok(frame.markers.every(m=>m.Visual_Queue_Opacity===1));
}
const normalEntry=marker(straight,'entry',10,{waits:{}}),normalExit=marker(straight,'exit',20,{waits:{}});
assert.equal(straight.queue.frame([normalEntry],10).markers.length,1);
assert.equal(straight.queue.frame([normalExit],20).markers.length,1);
const clipped=straight.queue.frame([marker(straight,'tip',10.1,{waits:{}})],10.1).markers[0];
assert.equal(clipped.Visual_Body_Clipped,false);near(clipped.Visual_Body_Length_Meters,4.5);
assert.equal(clipped.Visual_Body_Opacity,1,'boundary does not fade a supported centre');
const degenerate={...marker(straight,'bad',15,{waits:{}}),Link_ID:'missing',path:[[0,0],[0,0]],Visual_Lane_Index:null};
const unavailable=straight.queue.frame([degenerate],15);assert.equal(unavailable.counts.bodyUnrepresentable,1);assert.equal(unavailable.markers.length,0);

// Insufficient storage cannot reduce the configured stop margin. Keep the
// supported native body and an explicit constraint warning instead.
const shortEnough=setup(6),shortWait=shortEnough.queue.frame([marker(shortEnough,'fits',50)],50);
assert.equal(shortWait.markers.length,1);assert.equal(shortWait.markers[0].Visual_Queue_Compatible,false);
assert.equal(shortWait.markers[0].Visual_Queue_Reduced_Margin,false);
assert.equal(shortWait.markers[0].Visual_Diagnostic.constraint_violation,true);
const tinyWait=setup(.2),tinyFrame=tinyWait.queue.frame([marker(tinyWait,'tiny',50)],50);
assert.equal(tinyFrame.markers.length,1);assert.equal(tinyFrame.omitted.length,0);
assert.equal(tinyFrame.markers[0].vehicle,'tiny');assert.equal(tinyFrame.markers[0].Visual_Queue_Compatible,false);
assert.equal(tinyFrame.counts.incompatiblePosition,1);
const ambiguous=setup(100,3,{offset_eligible:false});
const ambiguousFrame=ambiguous.queue.frame([marker(ambiguous,'unknown-lane',50)],50);
assert.equal(ambiguousFrame.markers.length,0,'an ambiguous multilane axis is not a fabricated lane');
assert.equal(ambiguousFrame.omitted[0].Visual_Queue_State,'geometry_or_lane_unavailable');
for(const reason of ['priority_yield','storage_wait','intersection_conflict','signal_not_green','congestion_queue','signal_queue_not_green']) {
  const waits={[reason]:{first:20,position_evidence:reason.includes('queue') ? 'unknown_queue_position' : 'queue_exit'}};
  const frame=straight.queue.frame([marker(straight,reason,199.999,{waits})],199.999);
  assert.equal(frame.counts.positioned,1);assert.ok(frame.markers[0].Visual_Queue_Center_Meters+2.25<=98);
}
// Formation uses full following clearance too, not a fraction of the pitch.
const forming=straight.queue.frame(['a','b','c'].map(id=>marker(straight,id,15)),15);
assert.equal(forming.markers.length,3);
for(let i=1;i<forming.markers.length;i++)assert.ok(
  forming.markers[i-1].Visual_Queue_Center_Meters-forming.markers[i].Visual_Queue_Center_Meters>=6.5-1e-7);
// Moving followers of a stopped head use the same lane, without changing speed.
const approaching=marker(straight,'z',19.9,{waits:{}}),following=straight.queue.frame([marker(straight,'a',19.9,{hold:19}),approaching],19.9);
const followed=byVehicle(following).z;
assert.equal(followed.Visual_Queue_State,'following');assert.equal(followed.Visual_Speed_kmh,approaching.Visual_Speed_kmh);
assert.ok(byVehicle(following).a.Visual_Queue_Center_Meters-followed.Visual_Queue_Center_Meters>=6.5-1e-7);

// The offset includes the real width of the crossing, not just node distance.
const crossingRoad={...straight.road,from_node:'in',to_node:'junction',allowed_to_links:['cross'],movement_source:'effective_car_node_adjacency'};
const cross={...straight.road,num_lanes:6,from_node:'junction',to_node:'out',path:[[100/metres,0],[100/metres,100/metres]]};
const crossingLanes=new VisualLanes({schema_version:1,links:{road:crossingRoad,cross}});
const crossing={road:crossingRoad,lanes:crossingLanes,queue:new VisualQueues(crossingLanes)};
const stopped=crossing.queue.frame([marker(crossing,'crossing',199.999)],199.999).markers[0];
const margin=crossingLanes.intersectionSetback('road',0);
assert.ok(margin>8);assert.ok(stopped.Visual_Queue_Center_Meters+2.25<=100-margin-2+1e-7);
near(stopped.Visual_Body_Heading_Degrees,0);

// Body clearance on a bend is checked in the local metric plane as well.
const curvedQueue=curve.queue.frame(Array.from({length:10},(_,i)=>marker(curve,String(i).padStart(2,'0'),50)),50);
assert.equal(curvedQueue.markers.length,10,'clearance must retain every body when the curve has room');
assert.equal(curvedQueue.counts.incompatiblePosition,0);
for(let i=1;i<curvedQueue.markers.length;i++)for(let j=0;j<i;j++) {
  const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
  assert.equal(curve.queue.envelopesOverlap(body(curvedQueue.markers[j]),body(curvedQueue.markers[i])),false);
}

straight.queue.configure({gap_m:.1});const tight=byVehicle(straight.queue.frame(input,50));
near(tight.a.Visual_Queue_Center_Meters-tight.b.Visual_Queue_Center_Meters,4.6);
straight.queue.configure({gap_m:10});const wide=byVehicle(straight.queue.frame(input,50));
near(wide.a.Visual_Queue_Center_Meters-wide.b.Visual_Queue_Center_Meters,14.5);
for(const settings of [{gap_m:0},{gap_m:.099},{gap_m:-1},{gap_m:11},{car_length_m:0},{car_width_m:NaN}])assert.throws(()=>new VisualQueues(straight.lanes,settings));
assert.throws(()=>straight.queue.frame([],NaN));
console.log('SimZ1 visual queues: evidence, spacing, native lane extent, bounded bodies, release and seek fixtures passed.');
