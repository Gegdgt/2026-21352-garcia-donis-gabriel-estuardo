// Small in-memory display fixtures; no MATSim, replay IO, browser or server.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const context=vm.createContext({});
const Lanes=vm.runInContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VisualLanes;',context);
const metre=6371008.8*Math.PI/180,xy=(x,y)=>[x/metre,y/metre],clone=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,e=1e-5)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
const nearPoint=(a,b)=>{near(a[0]*metre,b[0]*metre);near(a[1]*metre,b[1]*metre);};
function link(from,to,points,extra={}) {
  return {from_node:from,to_node:to,path:points,num_lanes:2,opposing_lanes:0,lane_width_m:3,
    offset_eligible:true,source_way:'main',osm_tags:{},native_lanes:{},
    movement_source:'effective_car_node_adjacency',allowed_to_links:[],...extra};
}
const setup=links=>new Lanes({schema_version:1,links});
const roads=(h,id)=>h.roads().filter(r=>r.Link_ID===id);

// Straight subdivisions, including a 20 cm segment, have constant width and offsets.
const data={a:link('n0','n1',[xy(0,0),xy(100,0)],{allowed_to_links:['b']}),
  b:link('n1','n2',[xy(100,0),xy(100.2,0)],{allowed_to_links:['c']}),
  c:link('n2','n3',[xy(100.2,0),xy(200,0)])};
const before=JSON.stringify(data),straight=setup(data);
assert.equal(straight.roads().length,6);assert.equal(straight.connectors().length,0);
for(let i=0;i<2;i++) {
  nearPoint(roads(straight,'a')[i].path.at(-1),roads(straight,'b')[i].path[0]);
  nearPoint(roads(straight,'b')[i].path.at(-1),roads(straight,'c')[i].path[0]);
  for(const id of ['a','b','c']) {
    const row=roads(straight,id)[i];near(row.width_m,2.46);
    for(const p of row.path)near(p[1]*metre,i===0 ? 1.5 : -1.5);
  }
}
for(const vehicle of ['v1','v2','v3']) {
  const indices=['a','b','c'].map(id=>straight.stableIndex(vehicle,id,2));
  assert.equal(new Set(indices).size,1,'estimated assignment does not change at a subdivision');
}
assert.equal(JSON.stringify(data),before,'native coordinates and metadata untouched');
assert.strictEqual(straight.roads(),straight.roads());assert.strictEqual(straight.connectors(),straight.connectors());
const cached=straight.links.get('a').geometry.offsets;
const cachedSize=cached.size,cachedCurve=cached.get(-1.5);
for(let i=0;i<25;i++)straight.place('a',i,0);
assert.equal(cached.size,cachedSize);assert.strictEqual(cached.get(-1.5),cachedCurve);
assert.equal(straight.snapshot().version,3);assert.equal(straight.snapshot().persistence,'memory_only');
const reordered=setup({c:data.c,b:data.b,a:data.a});
for(const id of Object.keys(data))assert.deepEqual(clone(roads(straight,id)),clone(roads(reordered,id)));

// A reversed 20 cm path used to fit both 25 cm endpoint tolerances.
const shortPath=[xy(0,0),xy(.2,0)],short=setup({tiny:link('a','b',shortPath)});
const reversedShort=[...shortPath].reverse(),shortLink=short.links.get('tiny');
assert.equal(short.compatiblePath(shortLink,shortPath),true);
assert.equal(short.compatiblePath(shortLink,reversedShort),false);
assert.equal(short.compatiblePath(shortLink,[xy(.1,0),xy(.1,0)]),false,'ambiguous direction is not evidence');
const reversedMarker=short.marker({Link_ID:'tiny',vehicle:'v1',path:reversedShort},.25,{},xy(.15,0));
assert.equal(reversedMarker.Visual_Lane_Source,'centerline');nearPoint(reversedMarker.position,xy(.15,0));
const reversedBody=short.centerBody(reversedShort,.25,.02,.01,'tiny');
nearPoint(reversedBody.position,xy(.15,0));

// A native right-angle curve stays a curve; subdivisions reproduce the same joint.
const realCurve=[xy(0,0),xy(50,0),xy(50,50)];
const curved=setup({whole:link('a','c',realCurve)});
const split=setup({first:link('a','b',realCurve.slice(0,2),{allowed_to_links:['last']}),
  last:link('b','c',realCurve.slice(1))});
for(let i=0;i<2;i++) {
  const corner=curved.place('whole',curved.links.get('whole').geometry.distances[1],i).position;
  nearPoint(corner,roads(split,'first')[i].path.at(-1));
  nearPoint(corner,roads(split,'last')[i].path[0]);
  const sign=i===0 ? -1 : 1;
  near(corner[0]*metre,50+sign*1.5);near(corner[1]*metre,-sign*1.5);
  assert.equal(roads(curved,'whole')[i].path.length,5,'source bend retained, no fitted arc');
}
const single=setup({road:link('a','b',[xy(0,0),xy(30,0)],{num_lanes:1})});
assert.equal(single.roads().length,1);
for(const p of single.roads()[0].path)near(p[1],0);

// An inward parallel can intersect a distant section although every link is safe.
// The native open spiral is simple: its final x=19 stays short of x=20.
const spiralPoints=[[0,0],[20,0],[20,20],[0,20],[0,2],[19,2]].map(p=>xy(...p));
const spiralData={};
for(let i=0;i<5;i++)spiralData['s'+i]=link('n'+i,'n'+(i+1),spiralPoints.slice(i,i+2),
  {allowed_to_links:i<4 ? ['s'+(i+1)] : []});
const spiralBefore=JSON.stringify(spiralData),spiral=setup(spiralData);
assert.equal(spiral.simple(spiralPoints),true);
assert.equal(spiral.roads().length,5,'unsafe joined offsets retain the five original axes');
assert.equal(spiral.connectors().length,0);
assert.ok(spiral.snapshot().issues.some(issue=>issue.reason==='unsafe_joined_offset_native_axes_retained' && issue.Link_IDs.length===5));
for(const [id,record] of Object.entries(spiralData)) {
  assert.equal(roads(spiral,id)[0].source,'centerline');
  assert.deepEqual(clone(roads(spiral,id)[0].path),record.path);
  assert.equal(spiral.links.get(id).eligible,false);
}
assert.equal(JSON.stringify(spiralData),spiralBefore);

// Closing an actual loop is adjacency, not an artificial self-intersection.
const loopPoints=[[0,0],[20,0],[20,20],[0,20],[0,0]].map(p=>xy(...p)),loopData={};
for(let i=0;i<4;i++)loopData['l'+i]=link('n'+i,'n'+((i+1)%4),loopPoints.slice(i,i+2),
  {allowed_to_links:['l'+((i+1)%4)]});
const loop=setup(loopData);
assert.equal(loop.roads().length,8);assert.equal(loop.snapshot().issues.length,0);
for(let i=0;i<2;i++)nearPoint(roads(loop,'l3')[i].path.at(-1),roads(loop,'l0')[i].path[0]);

// Four approaches: only explicit terminal destinations get connectors.
const junction={
  wIn:link('w','n',[xy(-40,0),xy(0,0)],{source_way:'west',movement_source:'effective_lane_definitions',
    native_lanes:{q0:{index:0,represented_lanes:1,to_links:['sOut']},
      q1:{index:1,represented_lanes:1,to_links:['eOut']}}}),
  wOut:link('n','w',[xy(0,0),xy(-40,0)],{num_lanes:1,source_way:'west'}),
  eIn:link('e','n',[xy(40,0),xy(0,0)],{num_lanes:1,source_way:'east'}),
  eOut:link('n','e',[xy(0,0),xy(40,0)],{num_lanes:1,source_way:'east'}),
  nIn:link('north','n',[xy(0,40),xy(0,0)],{num_lanes:1,source_way:'north'}),
  nOut:link('n','north',[xy(0,0),xy(0,40)],{num_lanes:1,source_way:'north'}),
  sIn:link('south','n',[xy(0,-40),xy(0,0)],{num_lanes:1,source_way:'south'}),
  sOut:link('n','south',[xy(0,0),xy(0,-40)],{num_lanes:1,source_way:'south'})};
const intersection=setup(junction);
assert.equal(intersection.roads().length,9);
assert.equal(intersection.connectors().length,2);
assert.deepEqual(clone(intersection.connectors().map(r=>[r.Link_ID,r.To_Link_ID]).sort()),[['wIn','eOut'],['wIn','sOut']]);
assert.ok(intersection.connectors().every(r=>r.path.length===2 && r.source==='permitted_movement_schematic'));
const prohibited=clone(junction);prohibited.wIn.native_lanes.q0.to_links=[];
assert.ok(setup(prohibited).connectors().every(r=>r.To_Link_ID!=='sOut'));
const unknown=clone(junction);unknown.wIn.native_lanes={};unknown.wIn.movement_source='unavailable_lane_mapping';
assert.equal(setup(unknown).connectors().length,0);
const ambiguous=clone(junction);ambiguous.eOut.num_lanes=2;
assert.ok(setup(ambiguous).snapshot().ambiguousTargetLaneMovements>0);
const hook=clone(junction);hook.wIn.native_lanes.q1.to_links=['sOut'];
assert.ok(setup(hook).snapshot().reversingConnectorsOmitted>0);

// Shared XY is not topology, and incompatible levels cannot become a connector.
const levels=clone(junction);levels.sOut.osm_tags={layer:'-1',tunnel:'yes'};
assert.ok(setup(levels).connectors().every(r=>r.To_Link_ID!=='sOut'));
const disconnected=clone(junction);disconnected.sOut.from_node='other-node-at-same-xy';
assert.ok(setup(disconnected).connectors().every(r=>r.To_Link_ID!=='sOut'));
const grade=setup({upper:link('u1','u2',[xy(-20,0),xy(20,0)],{num_lanes:1,osm_tags:{bridge:'yes',layer:'1'}}),
  lower:link('l1','l2',[xy(0,-20),xy(0,20)],{num_lanes:1,osm_tags:{layer:'0'}})});
assert.equal(grade.roads().length,2);assert.equal(grade.connectors().length,0);

// Real separate axes remain separate, even with matching street/way metadata.
const separate=setup({a:link('a','b',[xy(0,0),xy(50,0)]),
  b:link('c','d',[xy(50,12),xy(0,12)])});
assert.equal(separate.roads().length,4);assert.equal(separate.connectors().length,0);
assert.notEqual(separate.links.get('a').assignmentKey,separate.links.get('b').assignmentKey);

// Too-tight offsets must not loop, collapse lane widths or erase the real curve.
const tightPath=[xy(0,0),xy(.2,0),xy(.2,.2)];
const tight=setup({tiny:link('a','b',tightPath)});
assert.equal(tight.roads().length,1);assert.equal(tight.roads()[0].source,'centerline');
assert.deepEqual(clone(tight.roads()[0].path),tightPath);
assert.ok(tight.snapshot().issues.length>0);
const tightSegment={Link_ID:'tiny',vehicle:'v1',path:[tightPath[0],tightPath[2]]};
const retained=tight.marker(tightSegment,.5,{},xy(.1,.1));
nearPoint(retained.position,tightPath[1]);
assert.equal(retained.Visual_Lane_Source,'centerline');
const retainedBody=tight.centerBody(tightSegment.path,.5,.1,.05,'tiny');
assert.equal(retainedBody.path.length,2,'rigid body rotates at the effective bend');
nearPoint(retainedBody.position,tightPath[1]);
assert.equal(straight.simple([[0,0],[2,2],[0,2],[2,0]]),false);

// Guatemala latitude: all links share one metre conversion, including normals.
const latitude=14.64,sx=metre*Math.cos(latitude*Math.PI/180),p=(x,y)=>[-90.52+x/sx,latitude+y/metre];
const local=setup({a:link('a','b',[p(0,0),p(50,0)],{allowed_to_links:['b']}),
  b:link('b','c',[p(50,0),p(50,50)])});
assert.strictEqual(local.links.get('a').geometry.origin,local.links.get('b').geometry.origin);
near(local.links.get('a').geometry.xScale,local.links.get('b').geometry.xScale);
for(let i=0;i<2;i++)nearPoint(roads(local,'a')[i].path.at(-1),roads(local,'b')[i].path[0]);
near(Math.abs(local.place('a',0,0).position[1]-local.place('a',0,1).position[1])*metre,3);
console.log('PASS: static parallel geometry, subdivision continuity, real curves, permitted connectors, levels, short links and metric units');
