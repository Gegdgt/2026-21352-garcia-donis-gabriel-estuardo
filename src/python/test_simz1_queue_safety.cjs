// In-memory fixtures only. Run explicitly; no browser, HTTP, SQLite or MATSim.
// SIMZ1_QUEUE_SOURCE can point to a saved pre-change queue renderer for comparison.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const queueSource=process.env.SIMZ1_QUEUE_SOURCE || path.join(__dirname,'simz1_visual_queues.js');
const code=fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\n'+fs.readFileSync(queueSource,'utf8');
const [Lanes,Queues]=vm.runInNewContext(code+'\n[SimZ1VisualLanes,SimZ1VisualQueues]',{});
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],clone=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,e=.001)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
function road(from,to,extra={}) {
  return {path:[xy(...from),xy(...to)],num_lanes:1,lane_width_m:3,offset_eligible:true,
    opposing_lanes:0,native_lanes:{},movement_source:'effective_car_node_adjacency',allowed_to_links:[],...extra};
}
function setup(links={r:road([0,0],[150,0])},settings={}) {
  const lanes=new Lanes({schema_version:1,links});return {links,lanes,q:new Queues(lanes,settings)};
}
function car(f,id,time,{link='r',start=0,hold=20,end=4000,wait=true,lane=0,fraction=null,journey=id}={}) {
  const distance=f.lanes.describe(link).length_m;
  const progress=fraction ?? Math.min(1,Math.max(0,(time-start)/((wait ? hold : end)-start)));
  const raw={vehicle:id,Agent_ID:id,Replay_Journey_Key:journey,Link_ID:link,path:f.links[link].path,
    timestamps:[start,end],Motion_Plan:{version:1,status:'kinematic',distance_m:distance,
      ...(wait ? {hold_start:hold,native_wait_boundary:hold} : {}),
      phases:wait ? [[start,hold,0,distance/(hold-start),0],[hold,end,distance,0,0]] : [[start,end,0,distance/(end-start),0]]},
    Observed_Waits:wait ? {signal_red:{first:hold,last:end-1,position_evidence:'queue_exit'}} : {},
    Waiting:wait && time>=hold,Visual_Speed_kmh:wait && time>=hold ? 0 : 18,
    Visual_Motion_Fraction:progress,Visual_Distance_m:progress*distance};
  return {...raw,...f.lanes.marker(raw,progress,{},xy(0,0)),Visual_Lane_Index:lane,
    position:f.lanes.place(link,progress*distance,lane).position};
}
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters});
function clear(f,frame,count) {
  assert.equal(frame.markers.length,count,'cannot pass clearance by hiding a supported car');
  assert.equal(frame.omitted.length,0);
  for(let i=0;i<frame.markers.length;i++)for(let j=0;j<i;j++)
    assert.equal(f.q.envelopesOverlap(body(frame.markers[i]),body(frame.markers[j])),false);
  assert.equal(frame.counts.active,frame.counts.visible+frame.counts.omitted);
}
const reports=[];
function evidence(name,frame) {reports.push({fixture:name,...clone(frame.diagnostics)});}

// Two/five/ten coincident native endpoint holds, with stable entry FIFO.
for(const n of [2,5,10]) {
  const f=setup(),roster=Array.from({length:n},(_,i)=>car(f,'q'+i,50,{start:i/10}));
  const unchanged=JSON.stringify(roster),frame=f.q.frame(roster,50);
  clear(f,frame,n);assert.equal(frame.counts.queued,n);
  assert.ok(frame.counts.overlapsDetected>0);assert.equal(frame.counts.unresolvedOverlaps,0);
  for(let i=1;i<n;i++)near(frame.markers[i-1].Visual_Queue_Center_Meters-frame.markers[i].Visual_Queue_Center_Meters,6.5);
  const positions=x=>clone(x.markers.map(m=>[m.vehicle,m.position]));
  for(const time of [3500,50,2000,50]) {
    const next=f.q.frame([...roster].reverse(),time);
    assert.deepEqual(positions(next),positions(frame),'seek, pause and prolonged red cannot move stopped bodies');
  }
  assert.equal(JSON.stringify(roster),unchanged,'native timestamps, phases, widths and velocities are immutable');
  evidence('same_lane_'+n,frame);
}

// Progress used to sort the later vehicle in front of the stopped head.
const fifo=setup(),first=car(fifo,'first',30,{start:0}),second=car(fifo,'second',30,{start:1});
first.Visual_Motion_Fraction=.95;second.Visual_Motion_Fraction=1;
const ordered=fifo.q.frame([second,first],30);clear(fifo,ordered,2);
assert.equal(ordered.markers[0].vehicle,'first');
assert.ok(ordered.markers[0].Visual_Queue_Center_Meters>ordered.markers[1].Visual_Queue_Center_Meters);

// A predecessor's recorded exit does not propel a still-stationary follower.
const stable=setup(),lead=car(stable,'lead',50,{end:100}),tail=car(stable,'tail',50,{start:1});
const before=stable.q.frame([lead,tail],99,undefined,[lead,tail]);
const after=stable.q.frame([tail],101,undefined,[lead,tail]);
near(before.markers.find(m=>m.vehicle==='tail').position[0],after.markers[0].position[0],1e-12);
assert.equal(after.markers[0].Visual_Speed_kmh,0);
assert.deepEqual(clone(after.markers),clone(new Queues(stable.lanes).frame([tail],101,undefined,[lead,tail]).markers));

// Parallel lanes: keep their lane membership and reference dimensions.
const parallel=setup({r:road([0,0],[150,0],{num_lanes:2})});
const parallelFrame=parallel.q.frame([car(parallel,'left',50,{lane:0}),car(parallel,'right',50,{lane:1})],50);
clear(parallel,parallelFrame,2);near(Math.abs(parallelFrame.markers[0].position[1]-parallelFrame.markers[1].position[1])*scale,3);
for(const m of parallelFrame.markers){near(m.Visual_Body_Length_Meters,4.5);near(m.Visual_Body_Width_Meters,1.8);}
// At 45 degrees, vertical separation projects as dy/sqrt(2) on both body axes.
// dy=2 overlaps (1.414 < 1.8); dy=3 does not (2.121 > 1.8), even though the
// world-axis bounding boxes overlap. Keep both cases to exercise oriented SAT.
const oriented={position:xy(0,0),heading:45,length_m:4.5,width_m:1.8};
assert.equal(parallel.q.bodiesOverlap(oriented,{...oriented,position:xy(0,2)}),true);
assert.equal(parallel.q.bodiesOverlap(oriented,{...oriented,position:xy(0,3)}),false);
// Separation envelopes include clearance; the physical body keeps its width.
const nearby={...oriented,position:xy(0,2.7)};
assert.equal(parallel.q.bodiesOverlap(oriented,nearby),false);
assert.equal(parallel.q.envelopesOverlap(oriented,nearby),true);
// A wider safety envelope staggers the two lanes; it does not widen the cars.
parallel.q.configure({lateral_clearance_m:.7});
const staggered=parallel.q.frame([car(parallel,'left',50,{lane:0}),car(parallel,'right',50,{lane:1})],50);
clear(parallel,staggered,2);assert.ok(staggered.counts.overlapsResolved>0);
near(staggered.markers[0].Visual_Body_Width_Meters,1.8);evidence('adjacent_lane_envelopes',staggered);

// Two distinct supported lanes whose drawn bodies intersect: global SAT must
// recover both within their own lane, independently of Map/input order.
const adjacent=setup({a:road([0,0],[100,0]),b:road([0,1.5],[100,1.5])});
const adjacentCars=[car(adjacent,'adj-a',50,{link:'a'}),car(adjacent,'adj-b',50,{link:'b'})];
const adjacentFrame=adjacent.q.frame(adjacentCars,50);clear(adjacent,adjacentFrame,2);
assert.ok(adjacentFrame.diagnostics.collisions.some(c=>c.body_overlap && c.resolution==='resolved_spacing'));
assert.deepEqual(clone(adjacent.q.frame([...adjacentCars].reverse(),50).markers),clone(adjacentFrame.markers));
evidence('adjacent_bodies',adjacentFrame);

// Shared intersection: two queues stop before the perpendicular road strips.
const junction=setup({a:road([-100,0],[0,0],{from_node:'west',to_node:'j'}),
  b:road([0,-100],[0,0],{from_node:'south',to_node:'j'})});
const stopped=junction.q.frame([car(junction,'west',50,{link:'a'}),car(junction,'south',50,{link:'b'})],50);
clear(junction,stopped,2);
for(const m of stopped.markers)assert.ok(m.Visual_Queue_Center_Meters+2.25<=100-junction.lanes.intersectionSetback(m.Link_ID,0)-2+.001);
evidence('stop_line_perpendicular',stopped);
// No WAIT evidence for two free movements at the same node: retain identities
// and report uncertainty; neither fabricate a red light nor discard the loser.
const crossing=junction.q.frame([car(junction,'cross-a',50,{link:'a',wait:false,fraction:1}),
  car(junction,'cross-b',50,{link:'b',wait:false,fraction:1})],50);
assert.equal(crossing.markers.length,2);assert.equal(crossing.omitted.length,0);
assert.equal(crossing.counts.unresolvedOverlaps,1);
assert.equal(crossing.diagnostics.collisions[0].physical_incompatibility_confirmed,false);
evidence('possible_event_incompatibility',crossing);

// Rigid turns at many stations: all pairwise envelopes, not just the predecessor.
const bend=setup({r:road([0,0],[50,50],{path:[xy(0,0),xy(50,0),xy(50,50)]})});
for(const time of [12,12.5,13,13.5,14,15,16,18,20,50]) {
  const frame=bend.q.frame(Array.from({length:5},(_,i)=>car(bend,'bend'+i,time,{start:i/10})),time);
  clear(bend,frame,5);
  for(const m of frame.markers){assert.equal(m.Visual_Body_Path.length,2);near(m.Visual_Body_Length_Meters,4.5);}
}

// The old ! 1 and ! 3 remain traceable by ID when the geometry really cannot fit.
for(const n of [2,4]) {
  const short=setup({r:road([0,0],[12,0])});
  const frame=short.q.frame(Array.from({length:n},(_,i)=>car(short,'short'+i,50)),50);
  assert.equal(frame.markers.length,n);assert.equal(frame.omitted.length,0);
  const incompatible=frame.markers.filter(m=>m.Visual_Diagnostic?.constraint_violation===true);
  assert.equal(incompatible.length,n-1);
  assert.equal(frame.counts.incompatiblePosition,n-1);
  assert.ok(incompatible.every(m=>m.Visual_Diagnostic.constraint_violation && m.Visual_Body_Opacity===1));
  assert.ok(incompatible.every(m=>['storage_exceeded','queue_projection_reverses_motion'].includes(m.Visual_Queue_State)));
  assert.equal(frame.markers.filter(m=>m.Visual_Queue_Compatible===false).length,n,
    'the first placed body also reports its conflict with retained native bodies');
  assert.ok(frame.counts.unresolvedOverlaps>0);
  const conflicting=new Set(frame.diagnostics.collisions.filter(row=>row.resolution==='unresolved')
    .flatMap(row=>row.vehicles.map(vehicle=>vehicle.vehicle_id)));
  assert.equal(conflicting.size,n,'both sides of every unresolved overlap remain identifiable');
  assert.equal(frame.diagnostics.records.length,n);
  evidence('former_bang_'+(n-1),frame);
}
// A recorded subdivision proves topology, but does not supply an approach that
// can end at a negative station without reversing after this interval starts.
const links={up:road([0,0],[50,0],{from_node:'s',to_node:'j',source_way:'way',allowed_to_links:['r']}),
  r:road([50,0],[52,0],{from_node:'j',to_node:'t',source_way:'way'})};
const short=setup(links),waiting=Array.from({length:5},(_,i)=>car(short,'spill'+i,50,{start:10+i/10,hold:20}));
const predecessors=new Map(waiting.map(m=>[m.vehicle,car(short,m.vehicle,10,{link:'up',wait:false,start:0,end:m.timestamps[0],fraction:1})]));
const neighbors=m=>({previous:predecessors.get(m.vehicle)});
const spill=short.q.frame(waiting,50,neighbors);
assert.equal(spill.markers.length,5);assert.equal(spill.omitted.length,0);
assert.equal(spill.counts.incompatiblePosition,5);
assert.ok(spill.markers.every(m=>m.Link_ID==='r' && m.Visual_Queue_Display_Link_ID!=='up' &&
  m.Visual_Queue_Compatible===false && m.Visual_Diagnostic.upstream_supported===true));
assert.ok(spill.counts.unresolvedOverlaps>0,'retained native overlap is not declared repaired');
assert.ok(spill.markers.every(m=>m.position[0]*scale>=0 && m.position[0]*scale<=52));
const missingTime=short.q.frame(waiting,50,m=>({previous:{...predecessors.get(m.vehicle),timestamps:[0,9]}}));
assert.equal(missingTime.markers.length,5);
assert.ok(missingTime.markers.every(m=>m.Visual_Queue_Compatible===false && m.Visual_Queue_Display_Link_ID!=='up'));
const wrong=setup({...links,up:{...links.up,source_way:'other_street'}});
const wrongStreet=wrong.q.frame(waiting,50,neighbors);
assert.equal(wrongStreet.markers.length,5);
assert.ok(wrongStreet.markers.every(m=>m.Visual_Queue_Compatible===false && m.Visual_Queue_Display_Link_ID!=='up'));
evidence('topology_without_continuous_spillback_approach',spill);

// Exact connected-link boundary has a body on both sides, same identity/pose.
const incoming=car(short,'transition',10,{link:'up',wait:false,start:0,end:10,fraction:1});
const outgoing=car(short,'transition',10,{link:'r',wait:false,start:10,end:12,fraction:0});
const a=short.q.frame([incoming],9.999,()=>({next:outgoing})).markers[0];
const b=short.q.frame([outgoing],10,()=>({previous:incoming})).markers[0];
assert.equal(a.vehicle,b.vehicle);near(a.position[0],b.position[0],1e-12);near(a.Visual_Body_Heading_Degrees,b.Visual_Body_Heading_Degrees);
evidence('link_boundary',short.q.frame([outgoing],10,()=>({previous:incoming})));

// Unknown geometry/motion is not fixed by inventing a pose. Known one-lane
// geometry can recover a missing visual lane index.
const unknown=setup(),known=car(unknown,'recover',50);known.Visual_Lane_Index=null;
assert.equal(unknown.q.frame([known],50).markers.length,1);
const distanceOnly={...car(unknown,'distance-only',50),Visual_Motion_Fraction:undefined};
assert.equal(unknown.q.frame([distanceOnly],50).markers.length,1,'distance and validated plan recover a missing fraction');
const missingCenter={...car(unknown,'missing-center',50),position:null};
assert.equal(unknown.q.frame([missingCenter],50).markers.length,1,'a valid lane/fraction recovers the geometric centre');
const missing={...car(unknown,'missing',50),Link_ID:'missing',Visual_Lane_Index:null,path:[xy(2,2),xy(2,2)]};
const unavailableMotion={...car(unknown,'unavailable-motion',50),Motion_Plan:{status:'unavailable',fallback_reason:'distance_exceeds_speed_cap'}};
const invalid=unknown.q.frame([missing,unavailableMotion],50);
assert.equal(invalid.markers.length,0);
assert.equal(invalid.omitted.find(m=>m.vehicle==='unavailable-motion').Visual_Diagnostic.motion_reason,'distance_exceeds_speed_cap');
assert.equal(invalid.counts.unsupportedPosition,2);evidence('unknown_and_unavailable_not_forced_evidence',invalid);
const orientation={...car(unknown,'unknown-orientation',50),Observed_Waits:{},
  path:[xy(3,3),xy(3,3)],position:xy(3,3)};
const unsupported=unknown.q.frame([orientation],50);
assert.equal(unsupported.omitted.length,1);
assert.ok(['geometry_or_lane_unavailable','body_unrepresentable'].includes(unsupported.omitted[0].Visual_Queue_State));
const shell=fs.readFileSync(path.join(__dirname,'visualizador_z1_continuous.html'),'utf8');
const controls=fs.readFileSync(path.join(__dirname,'visualizador_z1_controls.js'),'utf8');
assert.doesNotMatch(shell,/id:'queue-overflow'|getText:d=>'! '/);
assert.match(controls,/getVisualDiagnostics/);assert.match(controls,/Diagnosticar vehiculo/);
assert.throws(()=>parallel.q.configure({lateral_clearance_m:1.1}));
if(process.argv.includes('--evidence'))console.log(JSON.stringify(reports,null,2));
else console.log('PASS: queue safety, stable holds, cross-lane SAT, traceable omissions and supported continuity');
