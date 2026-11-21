// Prepared contract checks. Explicit execution only; no browser, server,
// population, SQLite, MATSim, export or historical file mutation.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const files=['simz1_visual_lanes.js','simz1_visual_queues.js'];
const source=files.map(name=>fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n');
const [Lanes,Queues,Catalog]=vm.runInNewContext(source+'\n[SimZ1VisualLanes,SimZ1VisualQueues,SimZ1VehicleCatalog]',{});
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];
const plain=value=>JSON.parse(JSON.stringify(value));
const close=(a,b,tolerance=.001)=>assert(Math.abs(a-b)<=tolerance,`${a} != ${b}`);
const families=['TransitBus','TransportePesado','Normal','Motocicleta'];
const expected={TransitBus:[12,2.5],TransportePesado:[10,2.5],Normal:[4.5,1.8],Motocicleta:[2.1,.8]};
const reports=[];
function road(points,extra={}) {
  return {path:points.map(point=>xy(...point)),num_lanes:1,lane_width_m:3.5,
    opposing_lanes:0,offset_eligible:true,native_lanes:{},osm_tags:{},
    movement_source:'effective_car_node_adjacency',allowed_to_links:[],...extra};
}
function setup(links={r:road([[0,0],[300,0]])},settings={}) {
  const lanes=new Lanes({schema_version:1,links});return {links,lanes,queues:new Queues(lanes,settings)};
}
function marker(f,id,time,{link='r',start=0,end=4000,hold=20,wait=true,type='Normal',nativeEntry=start,lane=0,fraction=null}={}) {
  const distance=f.lanes.describe(link).length_m;
  const progress=fraction ?? Math.max(0,Math.min(1,(time-start)/((wait ? hold : end)-start)));
  const record={vehicle:id,Agent_ID:'person-'+id,Replay_Journey_Key:'journey-'+id,
    Trip:{Trip_ID:'person-'+id+':trip:0001'},Vehicle_Type:type,Vehicle_PCU:type==='TransitBus' ? 2.8 : 1,
    Link_ID:link,path:f.links[link].path,timestamps:[start,end],
    Motion_Plan:{version:1,status:'kinematic',distance_m:distance,
      ...(wait ? {hold_start:hold,native_wait_boundary:hold} : {}),
      phases:wait ? [[start,hold,0,distance/(hold-start),0],[hold,end,distance,0,0]] :
        [[start,end,0,distance/(end-start),0]]},
    Observed_Waits:wait ? {signal_red:{first:hold,last:end-1,position_evidence:'queue_exit',
      sources:['MATSim15_QNode_native_branch']}} : {},
    Visual_Motion_Fraction:progress,Visual_Distance_m:distance*progress,
    Waiting:wait && time>=hold,Visual_Speed_kmh:wait && time>=hold ? 0 : 18};
  const position=f.lanes.place(link,progress*distance,lane).position;
  return {...record,...f.lanes.marker(record,progress,{},position),position,
    Visual_Lane_Index:lane,Visual_Lane_Source:'native',Observed_Queue_ID:link+'.lane.'+lane,
    Observed_Queue_Entry:nativeEntry};
}
const body=marker=>({position:marker.position,heading:marker.Visual_Body_Heading_Degrees,
  length_m:marker.Visual_Body_Length_Meters,width_m:marker.Visual_Body_Width_Meters});
function preserved(frame,roster) {
  const originals=new Map(roster.map(record=>[record.vehicle,record]));
  const all=[...frame.markers,...frame.omitted];
  assert.equal(all.length,originals.size,'every active vehicle retains exactly one traceable identity');
  assert.equal(new Set(all.map(row=>row.vehicle)).size,originals.size);
  assert.equal(frame.counts.active,frame.counts.visible+frame.counts.omitted);
  for(const row of all) {
    const original=originals.get(row.vehicle);
    assert(original);
    for(const field of ['vehicle','Agent_ID','Replay_Journey_Key','Link_ID','Vehicle_PCU','Visual_Speed_kmh'])
      assert.equal(row[field],original[field],field+' must not change');
    for(const field of ['timestamps','path','Motion_Plan','Observed_Waits','Trip'])
      assert.deepEqual(plain(row[field]),plain(original[field]),field+' must not change');
  }
}
function compatibleFit(f,frame,roster,{stationOrder=true}={}) {
  preserved(frame,roster);
  assert.equal(frame.markers.length,roster.length,'clearance cannot pass by dropping a supported vehicle');
  assert.equal(frame.omitted.length,0);
  assert.equal(frame.counts.incompatiblePosition,0);
  for(let i=0;i<frame.markers.length;i++) {
    const row=frame.markers[i],dimensions=expected[row.Vehicle_Type];
    assert(row.Visual_Queue_Compatible!==false);
    assert.deepEqual([row.Visual_Body_Length_Meters,row.Visual_Body_Width_Meters],dimensions);
    assert.equal(row.Visual_Body_Path.length,2,'body remains rigid on curves');
    assert.equal(row.Visual_Body_Clipped,false);
    assert.equal(row.Visual_Body_Opacity,1,'no fade near a node or at an interval boundary');
    assert.equal(row.Visual_Queue_Opacity,1);
    for(let j=0;j<i;j++)assert.equal(f.queues.envelopesOverlap(body(row),body(frame.markers[j])),false,
      'all body pairs must have metric clearance');
    if(i && stationOrder) {
      const predecessor=frame.markers[i-1];
      assert(predecessor.Visual_Queue_Center_Meters-row.Visual_Queue_Center_Meters>=
        (predecessor.Visual_Body_Length_Meters+row.Visual_Body_Length_Meters)/2+f.queues.settings.gap_m-1e-6);
    }
  }
}
function positions(frame) {
  return plain(frame.markers.map(row=>[row.vehicle,row.position,row.Visual_Body_Heading_Degrees]));
}

// Queue lengths and mixed dimensions use real metric half-length sums, not PCU.
for(const count of [2,5,10])for(const reverse of [false,true]) {
  const f=setup({r:road(reverse ? [[300,0],[0,0]] : [[0,0],[300,0]])});
  const roster=Array.from({length:count},(_,i)=>marker(f,'mixed-'+String(i).padStart(2,'0'),50,
    {type:families[i%families.length],start:i/10,hold:20+i/10,nativeEntry:2+i/10}));
  const untouched=JSON.stringify(roster),frame=f.queues.frame(roster,50);
  compatibleFit(f,frame,roster);
  assert.deepEqual(plain(frame.markers.map(row=>row.vehicle)),roster.map(row=>row.vehicle));
  for(const time of [3500,50,150,50]) {
    const replay=f.queues.frame([...roster].reverse(),time,undefined,roster);
    compatibleFit(f,replay,roster);
    assert.deepEqual(positions(replay),positions(frame),'pause, reverse seek and long red retain stopped positions');
  }
  assert.equal(JSON.stringify(roster),untouched);
  reports.push({case:'mixed_'+count+(reverse ? '_reverse' : ''),visible:frame.markers.length,
    incompatible:frame.counts.incompatiblePosition,unresolved:frame.counts.unresolvedOverlaps});
}

// A long curve provides enough length; every body and every pair remain checked.
const curve=setup({r:road([[0,0],[150,0],[150,80]])});
const curved=Array.from({length:10},(_,i)=>marker(curve,'curve-'+i,50,
  {type:families[i%families.length],start:i/10,hold:20+i/10}));
compatibleFit(curve,curve.queues.frame(curved,50),curved);

// A recorded red allows the inferred metric setback; a free movement does not.
const junction=setup({r:road([[-100,0],[0,0]],{from_node:'west',to_node:'j'}),
  crossing:road([[0,-100],[0,0]],{from_node:'south',to_node:'j',num_lanes:4})});
const stopped=marker(junction,'red',50),stopFrame=junction.queues.frame([stopped],50);
compatibleFit(junction,stopFrame,[stopped]);
const head=stopFrame.markers[0],setback=junction.lanes.intersectionSetback('r',0);
close(head.Visual_Queue_Center_Meters+head.Visual_Body_Length_Meters/2,100-setback-2);
assert.match(head.Visual_Queue_Source,/estimated/);
const moving=marker(junction,'free',50,{wait:false,end:100,fraction:.999});
const freeFrame=junction.queues.frame([moving],50);
assert.equal(freeFrame.markers.length,1);
assert.equal(freeFrame.markers[0].Visual_Queue_Center_Meters,undefined);
assert.deepEqual(plain(freeFrame.markers[0].position),plain(moving.position));

// XY overlap alone cannot prove an interaction across explicitly different levels.
for(const separated of [false,true]) {
  const levels=setup({a:road([[-100,0],[100,0]],{osm_tags:{layer:'0',bridge:'no'}}),
    b:road([[0,-100],[0,100]],{osm_tags:{layer:separated ? '1' : '0',bridge:separated ? 'yes' : 'no'}})});
  const cars=[marker(levels,'west-east',50,{link:'a',wait:false,end:100,fraction:.5}),
    marker(levels,'south-north',50,{link:'b',wait:false,end:100,fraction:.5})];
  const frame=levels.queues.frame(cars,50);preserved(frame,cars);
  assert.equal(frame.markers.length,2);
  assert.equal(levels.queues.bodiesOverlap(body(frame.markers[0]),body(frame.markers[1])),true);
  assert.equal(frame.counts.unresolvedOverlaps,separated ? 0 : 1);
  for(const collision of frame.diagnostics.collisions)assert.equal(collision.physical_incompatibility_confirmed,false,
    'graphical SAT is not evidence of a forced QSim move');
}

// Crossing a window with the same immutable roster cannot release a stopped tail.
const window=setup(),leader=marker(window,'leader',50,{end:120}),tail=marker(window,'tail',50,{start:1,hold:21});
const context=[leader,tail],before=window.queues.frame(context,119.999,undefined,context);
const baseline=before.markers.find(row=>row.vehicle==='tail');
for(const time of [120,120.001,150,120]) {
  const frame=window.queues.frame([tail],time,undefined,plain(context));
  assert.equal(frame.markers.length,1);
  assert.deepEqual(plain(frame.markers[0].position),plain(baseline.position));
  assert.equal(frame.markers[0].Visual_Speed_kmh,0);
}
// Duplicate-window transport is tested in test_simz1_visibility_temporal.cjs;
// this placement test does not fabricate duplicate native event identities.

// Short/too-narrow slots preserve known native bodies with visible incompatibility.
for(const geometry of [road([[0,0],[2,0]]),road([[0,0],[100,0]],{lane_width_m:1})]) {
  const f=setup({r:geometry}),input=marker(f,'cannot-fit',50);
  const frame=f.queues.frame([input],50);preserved(frame,[input]);
  assert.equal(frame.markers.length,1);assert.equal(frame.omitted.length,0);
  const retained=frame.markers[0];
  assert.equal(retained.Visual_Queue_Compatible,false);
  assert.equal(retained.Visual_Diagnostic.constraint_violation,true);
  assert.equal(retained.Visual_Body_Opacity,1);
  assert.equal(retained.Visual_Body_Length_Meters,4.5);
  assert.equal(retained.Visual_Body_Width_Meters,1.8);
  assert.deepEqual(plain(retained.position),plain(input.position),'known pose is retained without inventing upstream storage');
  assert.equal(frame.counts.incompatiblePosition,1);
  assert(!frame.diagnostics.collisions.some(row=>row.resolution==='resolved_spacing'));
}

// A closed incompatible Motion_Plan must stay unavailable; it is NOT proof of FORCE.
const history=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures','simz1-visibility-history.json'),'utf8'));
assert.equal(history.source.run_id,'simz1-0dd152dabbc24d1d84d9b738c449cc35');
assert.equal(history.source.iteration,0);
assert.deepEqual(history.cases.map(row=>row.segments[0].record.vehicle),['z1_43360','z1_38616','z1_167074']);
const waitCase=history.cases.find(row=>row.case_id==='short_link_native_wait_z1_38616');
const waitRecord=waitCase.segments.find(row=>row.sqlite_segment_id===151).record;
assert.equal(waitRecord.Observed_Waits.priority_stop.first,41);
assert.equal(waitRecord.Observed_Waits.priority_stop.last,45);
assert.equal(waitRecord.Observed_Waits.storage_forced_move,undefined);
const assignment=history.effective_geometry_excerpt.lane_assignments.find(row=>
  row.attributes.linkIdRef===waitRecord.Link_ID);
assert(assignment,'historical namespace-qualified lane assignment must be retained');
const lane=assignment.children.find(row=>row.tag==='lane' && row.attributes.id.endsWith('.lane.0'));
const extent=Number(lane.children.find(row=>row.tag==='startsAt').attributes.meterFromLinkEnd);
assert(extent<4.5/2,'native terminal lane is shorter than a half-body; do not invent storage');
for(const row of history.cases.flatMap(item=>item.trace))
  assert.equal(row.qsim_forced_movement,'not_established_by_this_evidence');
assert.equal(Catalog.resolve(waitRecord).physical.pcu,waitRecord.Vehicle_PCU);

console.log(JSON.stringify({status:'queue_contract_assertions_completed',
  scope:'pure metric geometry and historical evidence checks; no browser or QSim execution',
  cases:reports,historical_native_lane_extent_m:extent,
  forced_movement_evidence:'not present in these three historical fixture cases'},null,2));
