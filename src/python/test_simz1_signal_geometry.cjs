// Pure network/projection/state fixtures. No GPU, browser, server or MATSim.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const context=vm.createContext({});
for(const file of ['simz1_visual_lanes.js','simz1_signal_geometry.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,file),'utf8'),context);
const Signals=vm.runInContext('SimZ1SignalGeometry',context),Lanes=vm.runInContext('SimZ1VisualLanes',context);
const metre=180/(6371008.8*Math.PI),xy=(x,y)=>[x*metre,y*metre];
const paths={north:[xy(0,-20),xy(0,0)],east:[xy(-20,0),xy(0,0)],
  south:[xy(0,20),xy(0,0)],west:[xy(20,0),xy(0,0)],
  curve:[xy(-20,-20),xy(0,-20),xy(0,0),xy(0,0)],short:[xy(0,-1),xy(0,0)]};
const laneSpec={schema_version:1,links:Object.fromEntries(Object.entries(paths).map(([id,path])=>[id,
  {path,num_lanes:1,offset_eligible:true,from_node:id,to_node:'junction',native_lanes:{}}]))};
const lanes=new Lanes(laneSpec);
const records=Object.keys(paths).map((id,i)=>({signal_id:id,system_id:'native-system',group_id:i%2 ? 'side' : 'main',
  Link_ID:id,lane_ids:[id+'.lane.0'],position:[...xy(i*3,0),2],angle:i%2 ? 90 : 0,icon:'unknown'}));
records.push({...records[0],signal_id:'north-lane-1',lane_ids:['north.lane.1'],position:[...xy(-3,0),2]});
records.push({...records[0],signal_id:'missing',Link_ID:'missing',position:xy(-6,0)});
const original=JSON.stringify(records),sourceLanes=JSON.stringify(laneSpec),model=new Signals(records,lanes);
const plain=value=>JSON.parse(JSON.stringify(value));
const near=(a,b,epsilon=1e-8)=>assert.ok(Math.abs(a-b)<epsilon,`${a} vs ${b}`);
const transform=(m,p)=>[0,1,2].map(i=>m[i]*p[0]+m[4+i]*p[1]+m[8+i]*p[2]);
for(const [id,expected] of [['north',[0,-1,0]],['east',[-1,0,0]],['south',[0,1,0]],['west',[1,0,0]],['curve',[0,-1,0]],['short',[0,-1,0]]]) {
  const row=model.records.find(row=>row.signal_id===id),g=row.Signal_Geometry;
  assert.equal(g.source,'directed_link_terminal_tangent');
  transform(g.transform,[0,1,0]).forEach((value,i)=>near(value,expected[i]));
  assert.deepEqual(plain(transform(g.transform,[0,0,1])),[0,0,1],'pole remains vertical');
  assert.deepEqual(plain(g.source_anchor),records.find(row=>row.signal_id===id).position);
  assert.equal(g.anchor[2],2,'source altitude preserved');
  assert.equal(g.placement.source,'effective_terminal_lane_border');
  const u=g.approach_unit_enu,at=g.anchor.slice(0,2).map(v=>v/metre);
  const along=-(at[0]*u[0]+at[1]*u[1]);
  assert.ok(along>0 && along<lanes.links.get(id).geometry.edges.at(-1).length,'anchor stays alongside its terminal segment');
  if(id!=='curve')near(along,g.placement.setback_m);
  near(at[0]*u[1]-at[1]*u[0],3*.41+.5);
  assert.ok(g.placement.setback_m<lanes.links.get(id).geometry.edges.at(-1).length);
  const r=transform(g.transform,[1,0,0]),f=transform(g.transform,[0,1,0]);
  near(r[0]*f[0]+r[1]*f[1],0);near(r[0]*f[1]-r[1]*f[0],1);
}
const byLane=model.records.filter(row=>row.Link_ID==='north');
assert.equal(byLane.length,2);assert.notDeepEqual(plain(byLane[0].lane_ids),plain(byLane[1].lane_ids));
assert.deepEqual(plain(byLane[0].Signal_Geometry.transform),plain(byLane[1].Signal_Geometry.transform));
assert.equal(model.unoriented.length,1);assert.equal(model.unoriented[0].Signal_Geometry.transform,null);
assert.equal(model.issues[0].reason,'directed_link_geometry_unavailable');
assert.equal(Signals.terminalTangent([xy(1,1),xy(1,1)]),null);
assert.equal(Signals.terminalTangent([[NaN,0],xy(1,1)]),null);
const invalid=new Signals([{...records[0],position:[NaN,0]}],lanes);
assert.equal(invalid.oriented.length,1,'bad legacy anchor repaired using its own effective link');
const clipped=new Signals(records,lanes,{allowed:new Set(['north']),contains:p=>p[1]<0});
assert.equal(clipped.oriented.length,2,'corrected anchors determine boundary membership');
// Use the displayed lane convention for opposite carriageways.
const two=new Lanes({schema_version:1,links:{n:{path:paths.north,num_lanes:1,opposing_lanes:1,reverse_link:'s'},
  s:{path:[...paths.north].reverse(),num_lanes:1,opposing_lanes:1,reverse_link:'n'}}});
const opposed=new Signals(['n','s'].map(id=>({...records[0],Link_ID:id,signal_id:id})),two);
assert.ok(opposed.oriented[0].Signal_Geometry.anchor[0]>0);
assert.ok(opposed.oriented[1].Signal_Geometry.anchor[0]<0);

// Independent perspective camera: ENU -> rotated view -> pinhole. It includes
// altitude and location-dependent depth, unlike a 2D projection stub.
function viewport(zoom,bearing,pitch,width=1200,height=800,cx=0,cy=0) {
  const b=bearing*Math.PI/180,t=pitch*Math.PI/180,ppm=512*2**zoom/(2*Math.PI*6371008.8),distance=1.5*height/ppm;
  return {zoom,bearing,pitch,width,height,longitude:cx*metre,latitude:cy*metre,project(p) {
    const x=p[0]/metre-cx,y=p[1]/metre-cy,z=p[2] || 0;
    const rx=x*Math.cos(b)-y*Math.sin(b),ry=x*Math.sin(b)+y*Math.cos(b);
    const depth=distance-ry*Math.sin(t)-z*Math.cos(t),k=1.5*height/depth;
    return [width/2+k*rx,height/2-k*(ry*Math.cos(t)+z*Math.sin(t))];
  }};
}
class Layer {constructor(props){this.id=props.id;this.props=props;}clone(props){return new Layer({...this.props,...props});}}
const deck={SimpleMeshLayer:Layer}; // TextLayer intentionally unavailable.
let layers=model.layers(deck,viewport(17,0,0));
assert.equal(layers.length,3,'constant instanced layer count');
let body=layers.find(row=>row.id==='signals'),lamp=layers.find(row=>row.id==='signal-lamps');
assert.equal(body.props.data.length,7);assert.equal(lamp.props.data.length,21,'exactly three front lamps per native signal');
assert.equal(new Set(layers.map(layer=>layer.id)).size,layers.length,'body and lamps each have exactly one layer');
assert.equal(body.props.mesh.attributes.POSITION.value.length/9,24,'only pole and vertical housing: two boxes, no top head');
for(const row of body.props.data) {
  assert.equal(body.props.data.filter(other=>other.Signal_Geometry===row.Signal_Geometry).length,1,'one housing instance per native signal');
  const lamps=lamp.props.data.filter(other=>other.Signal_Geometry===row.Signal_Geometry);
  assert.deepEqual(plain(lamps.map(other=>other.Signal_Lamp)),[0,1,2]);
  assert.ok(lamps.every(other=>other.Signal_Surface==='front'),'no upper/head repeat surface');
  for(const other of lamps) {
    const m=other.Signal_Lamp_Transform;
    assert.deepEqual(plain(transform(m,[0,0,1])),[0,0,1],'each circular front lamp stays in a vertical plane');
    transform(m,[0,1,0]).forEach((value,i)=>near(value,row.Signal_Geometry.front_unit_enu[i] || 0));
  }
}
const bodyPositions=body.props.mesh.attributes.POSITION.value,d=Signals.dimensions;
for(let i=0;i<bodyPositions.length;i+=3) {
  assert.ok(Math.abs(bodyPositions[i+1])<=d.head_depth_m/2+1e-7,'no housing extends backwards into the old horizontal head');
  assert.ok(bodyPositions[i+2]<=d.head_top_m+1e-7);
}
const lampPositions=lamp.props.mesh.attributes.POSITION.value;
for(let i=0;i<lampPositions.length;i+=3) {
  near(lampPositions[i+1],0);
  const radius=Math.hypot(lampPositions[i],lampPositions[i+2]);
  assert.ok(radius<1e-7 || Math.abs(radius-d.lamp_radius_m)<1e-7,'lamp is a circular disk');
}
const sameJunction=body.props.data.filter(row=>['north','south'].includes(row.signal_id));
assert.equal(sameJunction.length,2,'opposite approaches at the same node both retain their legitimate head');
assert.equal(sameJunction[0].Signal_Geometry.intersection_key,sameJunction[1].Signal_Geometry.intersection_key);
sameJunction[0].Signal_Geometry.front_unit_enu.forEach((value,i)=>near(value,-sameJunction[1].Signal_Geometry.front_unit_enu[i]));
assert.equal(body.props.billboard,undefined);assert.equal(body.props.sizeScale,1);
assert.equal(body.props.parameters.depthWriteEnabled,true);assert.equal(lamp.props.parameters.cullMode,'back');
assert.equal(body.props.mesh,model.layers(deck)[0].props.mesh,'cached mesh shared across instances and views');
const poses=JSON.stringify(model.snapshot().records),mesh=body.props.mesh;
function actualExtent(row,layers,view) {
  const projected=[],origin=row.Signal_Geometry.anchor;
  for(const layer of layers)for(const instance of layer.props.data) {
    if(instance.Signal_Geometry!==row.Signal_Geometry)continue;
    const m=layer.props.getTransformMatrix(instance),vertices=layer.props.mesh.attributes.POSITION.value;
    for(let i=0;i<vertices.length;i+=3) {
      const p=transform(m,Array.from(vertices.slice(i,i+3))).map((v,k)=>v+m[12+k]);
      projected.push(view.project([origin[0]+p[0]*metre/Math.cos(origin[1]*Math.PI/180),origin[1]+p[1]*metre,(origin[2] || 0)+p[2]]));
    }
  }
  return Math.max(...[0,1].map(k=>Math.max(...projected.map(p=>p[k]))-Math.min(...projected.map(p=>p[k]))));
}
for(const zoom of [12,14,16,17,19,22])for(const bearing of [0,37,90,180,270])for(const pitch of [0,30,45,60,80]) {
  const view=viewport(zoom,bearing,pitch);
  layers=model.updateLayers(layers,view);body=layers.find(row=>row.id==='signals');
  assert.equal(body.props.mesh,mesh);
  assert.equal(JSON.stringify(model.snapshot().records),poses,'camera never changes access, anchor or ENU orientation');
  const min=model.detail ? 24 : 18,max=model.detail ? 34 : 22;
  assert.ok(body.props.data.length);
  for(const row of body.props.data) {
    const m=body.props.getTransformMatrix(row),g=row.Signal_Geometry,scale=model.frame.get(g).scale;
    const projected=Signals.extent(row,scale,view);
    assert.ok(projected>=min && projected<=max,`${zoom}/${bearing}/${pitch}: ${projected}`);
    const measured=actualExtent(row,layers,view);
    assert.ok(measured>=min-.3 && measured<=max,`actual instanced mesh extent: ${measured}`);
    transform(m,[0,1,0]).forEach((value,i)=>near(value/scale,-(g.approach_unit_enu[i] || 0)));
    near(m[8],0);near(m[9],0);near(m[10],scale);near(m[12],0);near(m[13],0);
    assert.equal(body.props.getPosition(row),g.anchor);
    const rowLamps=layers.find(layer=>layer.id==='signal-lamps').props.data.filter(lamp=>lamp.Signal_Geometry===g);
    assert.equal(rowLamps.length,3,'zenith, side and rotated cameras never add a second head');
    for(const instance of rowLamps) {
      const m=layers.find(layer=>layer.id==='signal-lamps').props.getTransformMatrix(instance);
      near(m[8],0);near(m[9],0);near(m[10],scale);
    }
  }
  assert.strictEqual(model.updateLayers(layers,view),layers,'no rebuild for paused or identical view');
}
for(const pitch of [0,60])for(const cy of [-65,65])for(const zoom of [17,19]) {
  layers=model.updateLayers(layers,viewport(zoom,90,pitch,500,700,0,cy));
  for(const render of model.snapshot().rendered)assert.ok(render.extent>=24 && render.extent<=34);
}
for(const id of ['signals','signal-lamps','signal-unoriented']) {
  const empty=new Signals([],lanes).layers(deck,viewport(17,0,45)).find(layer=>layer.id===id);
  assert.equal(empty.props.data.length,0);
  assert.equal(empty.props.getTransformMatrix(undefined),undefined,'v9.1 probes data[0] even for an empty layer');
}
// Every native node survives: never suppress nearby intersections in screen cells.
const largeSpec={schema_version:1,links:{}},largeRecords=[];
for(let node=0;node<200;node++)for(const direction of ['north','south','east','west']) {
  const id=node+direction;largeSpec.links[id]={...laneSpec.links[direction],to_node:'node'+node};
  largeRecords.push({...records[0],signal_id:id,Link_ID:id});
}
const many=new Signals(largeRecords,new Lanes(largeSpec));
let manyLayers=many.layers(deck,viewport(14,0,45));
assert.equal(manyLayers.length,3);assert.equal(many.visible.length,200);assert.equal(many.clusters.size,200);
assert.equal(many.visibleLamps.length,600);
manyLayers=many.updateLayers(manyLayers,viewport(16.5,0,45));assert.equal(many.visible.length,200);
manyLayers=many.updateLayers(manyLayers,viewport(17,0,45));assert.equal(many.visible.length,800);
manyLayers=many.updateLayers(manyLayers,viewport(16.3,0,45));assert.equal(many.visible.length,800);
manyLayers=many.updateLayers(manyLayers,viewport(16,0,45));assert.equal(many.visible.length,200);
assert.equal(manyLayers[0].props.mesh,mesh);assert.equal(many.layers(deck).length,3);
const builds=many.viewBuilds;
for(let i=0;i<100;i++)assert.strictEqual(many.updateLayers(manyLayers,viewport(16,0,45)),manyLayers);
assert.equal(many.viewBuilds,builds,'no camera work during clock ticks');
model.prepareView(viewport(14,0,0));
assert.match(model.tooltip(model.overview[0],(_,group)=>group==='main' ? 'RED' : 'GREEN',42).text,/Rojo/);
assert.match(model.tooltip(model.overview[0],(_,group)=>group==='main' ? 'RED' : 'GREEN',42).text,/Verde/);
for(const mesh of Object.values(Signals.meshes())) {
  const p=mesh.attributes.POSITION.value,n=mesh.attributes.NORMAL.value;
  assert.equal(p.length%9,0);assert.equal(n.length,p.length);
  for(let i=0;i<p.length;i+=9) {
    const a=[p[i+3]-p[i],p[i+4]-p[i+1],p[i+5]-p[i+2]],b=[p[i+6]-p[i],p[i+7]-p[i+1],p[i+8]-p[i+2]];
    const cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
    assert.ok(cross[0]*n[i]+cross[1]*n[i+1]+cross[2]*n[i+2]>0,'outward winding matches normal');
  }
}
model.prepareView(viewport(17,0,45));lamp=model.layers(deck)[2];
for(const state of ['RED','YELLOW','GREEN','REDYELLOW','OFF','UNKNOWN']) {
  const stateAt=(system,group,time)=>{assert.equal(system,'native-system');assert.ok(['main','side'].includes(group));assert.equal(time,42);return state;};
  const props=Signals.stateProps('signal-lamps',stateAt,42);
  for(const row of lamp.props.data) {
    const on=state===['RED','YELLOW','GREEN'][row.Signal_Lamp] || state==='REDYELLOW' && row.Signal_Lamp<2;
    assert.deepEqual(plain(props.getColor(row)),plain(on ? Signals.colors[['RED','YELLOW','GREEN'][row.Signal_Lamp]] : Signals.colors.OFF));
  }
  assert.equal(Signals.stateProps('signals',stateAt,42),null,'state never rotates/rebuilds body');
  assert.equal(Signals.stateProps('signal-state-labels',stateAt,42),null,'no textual substitute');
}
assert.equal(JSON.stringify(records),original);assert.equal(JSON.stringify(laneSpec),sourceLanes);
assert.equal(JSON.stringify(model.snapshot().records),poses);
console.log('PASS: one vertical head and three circular front lamps per signal, opposite approaches retained, bounded perspective sizes, zenith/side/rotated cameras, 800 instanced signals, native colors and immutable inputs');
if(process.argv[2]) {
  const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),native=JSON.stringify(input);
  const real=new Signals(input.signals,new Lanes(input.visual_lanes));
  assert.equal(JSON.stringify(input),native);
  assert.equal(real.oriented.length,input.signals.length,'all effective accesses can be oriented');
  const shifts=real.records.map(r=>r.Signal_Geometry.placement.displacement_m).sort((a,b)=>a-b);
  console.log(JSON.stringify({signals:real.records.length,intersections:real.clusters.size,
    corrected:real.snapshot().corrected_anchors,issues:real.issues,
    displacement_m:{min:shifts[0],median:shifts[Math.floor(shifts.length/2)],max:shifts.at(-1)}}));
}
