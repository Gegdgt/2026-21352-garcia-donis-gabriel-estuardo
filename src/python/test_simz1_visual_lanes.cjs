// Deterministic display geometry only: no MATSim, browser, server or replay IO.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8');
const sandbox={};vm.createContext(sandbox);
const VisualLanes=vm.runInContext(source+'\nSimZ1VisualLanes;',sandbox);
const clone=value=>JSON.parse(JSON.stringify(value));
const metres=6371008.8*Math.PI/180;
const east=[[0,0],[.001,0]],west=[...east].reverse();
function link(lanes,extra={}) {return {num_lanes:lanes,path:east,length_m:.001*metres,lane_width_m:3,
  offset_eligible:true,opposing_lanes:0,native_lanes:{},...extra};}
function setup(links) {return new VisualLanes({schema_version:1,start_reference:'link_end',links});}
function segment(id='road',vehicle='a',geometry=east) {return {Link_ID:id,vehicle,path:geometry,
  timestamps:[0,240],Motion_Plan:{version:1,distance_m:111,phases:[[0,240,0,.4625,0]]}};}
function centre(geometry,fraction) {
  return geometry[0].map((v,i)=>v+(geometry[geometry.length-1][i]-v)*fraction);
}
function marker(helper,s,fraction=.5,observation={}) {return helper.marker(s,fraction,observation,centre(s.path,fraction));}
function native(lane,id='road',vehicle='a') {return {lane,event:{type:'entered lane',link:id,lane,vehicle,time:0}};}
function near(actual,expected,tolerance=1e-8) {assert.ok(Math.abs(actual-expected)<=tolerance,`${actual} ~= ${expected}`);}
const one=setup({road:link(1)}),single=marker(one,segment());
assert.equal(one.roads().length,1);near(single.Visual_Lane_Offset_Meters,0);
assert.equal(single.Visual_Lane_Index,0);assert.equal(single.Visual_Lane_Source,'centerline');
near(single.position[0],.0005);near(single.position[1],0);
for(const count of [2,3]) {
  const helper=setup({road:link(count)}),roads=helper.roads();
  assert.equal(roads.length,count,'one world-space path per directional lane');
  assert.ok(roads.every(r=>r.width_m>0 && r.width_m<=3 && r.width_min_pixels===0));
  const assigned=new Set();
  for(let i=0;i<80;i++)assigned.add(marker(helper,segment('road','vehicle-'+i)).Visual_Lane_Index);
  assert.equal(assigned.size,count,'stable assignment can represent every lane');
  for(let i=0;i<count;i++) {
    const mid=roads[i].path.find(p=>Math.abs(p[0]-.0005)<1e-8);
    assert.ok(mid,'road includes midpoint');near(-mid[1]*metres,(i-(count-1)/2)*3,1e-6);
  }
}
const bidirectional=setup({east:link(1,{reverse_link:'west',opposing_lanes:1}),
  west:link(1,{path:west,reverse_link:'east',opposing_lanes:1})});
assert.equal(bidirectional.roads().length,2,'one plus one, never two lanes per direction');
const outbound=marker(bidirectional,segment('east')),inbound=marker(bidirectional,segment('west','b',west));
near(outbound.Visual_Lane_Offset_Meters,1.5);near(inbound.Visual_Lane_Offset_Meters,1.5);
assert.ok(outbound.position[1]<0 && inbound.position[1]>0,'right-hand sides follow travel direction');
near((inbound.position[1]-outbound.position[1])*metres,3,1e-6);
const asymmetric=setup({east:link(2,{reverse_link:'west',opposing_lanes:1}),
  west:link(1,{path:west,reverse_link:'east',opposing_lanes:2})});
assert.equal(asymmetric.roads().length,3,'2+1 preserves exactly three directional lanes');

// Independent carriageways already have their own OSM axes: no opposing offset.
const separateWest=[[.001,.0001],[0,.0001]];
const separated=setup({east:link(1),west:link(1,{path:separateWest})});
assert.equal(separated.roads().length,2);
near(marker(separated,segment('east')).Visual_Lane_Offset_Meters,0);
const separateCar=marker(separated,segment('west','b',separateWest));
near(separateCar.Visual_Lane_Offset_Meters,0);near(separateCar.position[1],.0001);
const multiSeparated=setup({east:link(2),west:link(2,{path:separateWest})});
assert.equal(multiSeparated.roads().filter(r=>r.Link_ID==='east').length,2);
assert.equal(multiSeparated.roads().filter(r=>r.Link_ID==='west').length,2);
// Crossing in XY creates neither connectors nor extra lanes. Layer is evidence,
// not a fabricated elevation in metres.
const crossing=[[.0005,-.001],[.0005,.001]];
const grade=setup({upper:link(1,{osm_tags:{bridge:'yes',layer:'1'}}),
  lower:link(1,{path:crossing,osm_tags:{tunnel:'yes',layer:'-1'}})});
assert.equal(grade.roads().length,2);
assert.deepEqual([...new Set(grade.roads().map(r=>r.Link_ID))].sort(),['lower','upper']);

const nativeLink=link(2,{native_lanes:{left:{index:0,represented_lanes:1,start_m:60},
  right:{index:1,represented_lanes:1,start_m:60},original:{index:null,represented_lanes:2,start_m:111}}});
const selected=setup({road:nativeLink}),vehicle=segment();
const left=marker(selected,vehicle,.75,native('left')),right=marker(selected,vehicle,.75,native('right'));
assert.equal(left.Visual_Lane_Source,'native');assert.equal(left.Visual_Lane_Index,0);
assert.equal(right.Visual_Lane_Source,'native');assert.equal(right.Visual_Lane_Index,1);
assert.ok(left.position[1]>right.position[1]);
assert.equal(marker(selected,vehicle,.1,native('right')).Visual_Lane_Source,'native','native membership takes priority over estimated longitudinal fraction');
assert.equal(marker(selected,vehicle,.75,native('right','other')).Visual_Lane_Source,'estimated','another link event is not evidence');
assert.equal(marker(selected,vehicle,.75,native('right','road','other')).Visual_Lane_Source,'estimated','another vehicle event is not evidence');
for(const observation of [{},native('missing'),native('original')]) {
  const first=marker(selected,vehicle,.5,observation);
  assert.equal(first.Visual_Lane_Source,'estimated');
  assert.deepEqual(clone(first),clone(marker(selected,clone(vehicle),.5,observation)),'new window objects preserve assignment');
  const before=marker(selected,{...vehicle,window_index:0},.499999,observation);
  const after=marker(selected,{...clone(vehicle),window_index:1},.500001,observation);
  assert.equal(before.Visual_Lane_Index,after.Visual_Lane_Index,'120-second boundary cannot choose another lane');
  near(before.position[1],after.position[1],1e-10);
  assert.deepEqual(clone(marker(selected,{...vehicle,zoom:4,time:0},.5,observation)),
    clone(marker(selected,{...vehicle,zoom:20,time:90000},.5,observation)),'world-space positions do not depend on zoom or playback clock');
}
const beforeInputs=JSON.stringify({nativeLink,vehicle});
selected.roads();marker(selected,vehicle,.75,native('left'));
assert.equal(JSON.stringify({nativeLink,vehicle}),beforeInputs,'native metadata, paths and Motion_Plan are never mutated');

const curve=[[0,0],[.001,0],[.001,.001]],curved=setup({road:link(2,{path:curve})});
const curvedSegment=segment('road','curve-car',curve),quarter=marker(curved,curvedSegment,.25);
assert.ok(quarter.position[0]>0 && quarter.position[0]<.001);assert.ok(Math.abs(quarter.position[1])<3/metres);
const curveChord=segment('road','curve-car',[curve[0],curve[curve.length-1]]);
assert.deepEqual(clone(marker(curved,curveChord,.25).position),clone(quarter.position),'validated effective curve replaces the compatible exported chord');
const corner=marker(curved,curvedSegment,.5),prior=marker(curved,curvedSegment,.5-1e-8),next=marker(curved,curvedSegment,.5+1e-8);
near(Math.abs(corner.Visual_Lane_Offset_Meters),1.5);
assert.ok(Math.abs(corner.position[1])*metres>1.49,'real corner keeps its parallel offset');
near(prior.position[0],next.position[0],1e-8);near(prior.position[1],next.position[1],1e-8);
assert.ok(curved.roads().every(r=>r.path.every(p=>p.every(Number.isFinite))));
for(const f of [0,1])near(marker(selected,vehicle,f,native('right')).Visual_Lane_Offset_Meters,1.5);
const tiny=[[0,0],[.000005,0]],short=setup({road:link(3,{path:tiny})});
assert.ok(Math.abs(marker(short,segment('road','a',tiny)).Visual_Lane_Offset_Meters)<=3);
near(marker(short,segment('road','a',tiny)).Visual_Lane_Marker_Radius_Meters,.8);
const tinyLength=.000005*metres,shortNative={};
for(let index=0;index<4;index++)shortNative['lane-'+index]={index,represented_lanes:1,start_m:tinyLength*.8};
const fourShort=setup({road:link(4,{path:tiny,length_m:tinyLength,native_lanes:shortNative})});
const fourMarkers=Array.from({length:4},(_,index)=>marker(fourShort,segment('road','a',tiny),.5,native('lane-'+index)));
const offsets=fourMarkers.map(m=>m.Visual_Lane_Offset_Meters),spacing=offsets[1]-offsets[0];
assert.ok(spacing>0);assert.equal(new Set(offsets).size,4,'short four-lane link never collapses lane pairs');
near(offsets[2]-offsets[1],spacing);near(offsets[3]-offsets[2],spacing);
near(offsets[0],-4.5);near(offsets[3],4.5);near(spacing,3);
for(const m of fourMarkers)assert.ok(m.Visual_Lane_Marker_Radius_Meters*2<spacing,'marker fits uniform lane spacing');
const fourRoads=fourShort.roads();assert.equal(fourRoads.length,4);
const mids=fourRoads.map(r=>r.path.find(p=>Math.abs(p[0]-.0000025)<1e-12));
assert.equal(new Set(mids.map(p=>p[1])).size,4,'four road strips remain distinct at the midpoint');
for(const road of fourRoads)near(road.width_m,2.46);
const narrow=setup({road:link(2,{lane_width_m:.5})});
near(marker(narrow,vehicle).Visual_Lane_Marker_Radius_Meters,.15);
const reversed=selected.marker(segment('road','a',west),.5,{},[10,20]);
assert.equal(reversed.Visual_Lane_Source,'centerline');assert.deepEqual(clone(reversed.position),[10,20]);
const mismatched=selected.marker(segment('road','a',[[0,0],[.002,0]]),.5,{},[10,20]);
assert.equal(mismatched.Visual_Lane_Source,'centerline');assert.deepEqual(clone(mismatched.position),[10,20]);
assert.ok(mismatched.Visual_Lane_Marker_Radius_Meters<=.8);
for(const geometry of [[[0,0],[0,0]],[[0,0],[NaN,0]],[[0,0],[0,90]]]) {
  const helper=setup({road:link(2,{path:geometry})}),fallback=helper.marker(segment('road','a',geometry),.5,{},[10,20]);
  assert.deepEqual(clone(fallback.position),[10,20]);assert.equal(fallback.Visual_Lane_Source,'centerline');
  assert.equal(helper.roads().length,0,'invalid geometry does not create lanes');
}
const ineligible=setup({road:link(2,{offset_eligible:false})});
assert.equal(marker(ineligible,vehicle).Visual_Lane_Source,'centerline');assert.equal(ineligible.roads().length,1);
assert.equal(ineligible.roads()[0].source,'centerline','valid original road survives ambiguous lane metadata');
assert.deepEqual(clone(ineligible.roads()[0].path),east);
const invalidCount=setup({road:link(null)});
assert.equal(invalidCount.roads().length,1);assert.equal(invalidCount.roads()[0].lane_index,null);
const repeat=setup({road:link(2,{path:[[0,0],[0,0],[.001,0]]})});
assert.ok(marker(repeat,segment('road','a',[[0,0],[0,0],[.001,0]])).position.every(Number.isFinite));
const targetPath=[[.001,0],[.001,.001]],turnLanes=setup({
  road:link(2,{from_node:'a',to_node:'b',allowed_to_links:['exit'],movement_source:'effective_lane_definitions',
    native_lanes:{left:{index:0,represented_lanes:1,start_m:80,to_links:['exit']},
      right:{index:1,represented_lanes:1,start_m:80,to_links:['elsewhere']}}}),
  exit:link(1,{path:targetPath,from_node:'b',to_node:'c'})});
const turnStart={...segment(),Agent_ID:'person',Replay_Journey_Key:'journey'},
  turnEnd={...segment('exit','a',targetPath),Agent_ID:'person',Replay_Journey_Key:'journey',timestamps:[240,300]};
const allowed=marker(turnLanes,turnStart,.9,{next_segment:turnEnd});
assert.equal(allowed.Visual_Lane_Index,0,'a unique permitted outgoing lane constrains the estimated assignment');
assert.equal(allowed.Visual_Lane_Source,'estimated','toLink is not a measured lateral position');
const observedRight=marker(turnLanes,turnStart,.9,{...native('right'),next_segment:turnEnd});
assert.equal(observedRight.Visual_Lane_Index,1,'a recorded native lane is never overwritten by a route estimate');
console.log('PASS: metric visual lanes 1/2/3, opposed directions, native and stable estimated assignment, window/zoom invariance, curves and conservative fallback');
