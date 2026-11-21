'use strict';
// Small metric fixtures only: no network, replay database, browser or MATSim.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const [Catalog,Lanes,Queues]=vm.runInNewContext(['simz1_visual_lanes.js','simz1_visual_queues.js'].map(name=>
  fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+'\n[SimZ1VehicleCatalog,SimZ1VisualLanes,SimZ1VisualQueues]');
const plain=value=>JSON.parse(JSON.stringify(value)),near=(a,b,e=1e-6)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale];
const defaults=[['Normal',4.5,1.8],['Motociclista',2.1,.8],['TransportePesado',10,2.5],['TransitBus',12,2.5]];
for(const [Vehicle_Type,length,width] of defaults) {
  const record={Vehicle_Type,Vehicle_PCU:999},resolved=Catalog.resolve(record);
  assert.deepEqual([resolved.dimensions.length_m,resolved.dimensions.width_m],[length,width]);
  assert.equal(resolved.dimensions_origin,'family_assumption');assert.equal(resolved.dimensions.assumed,true);
  assert.equal(resolved.physical.dimensions,null);assert.equal(resolved.physical.dimensions_status,'not_recorded');
  assert.equal(resolved.physical.pcu,999,'PCU is retained separately, never converted to metres');
}
const physical={length_m:10.8,width_m:2.35,source:'MATSim_VehicleType_XML',nature:'configured',
  measurement_status:'not_established_by_vehicle_type',assumed:null,
  provenance:{vehicle_type:'bus',artifact_source:'fixture',artifact_path:'vehicles.xml',artifact_sha256:'fixture-only'}};
const record={vehicle:'identity',Vehicle_Type:'TransitBus',Vehicle_PCU:2.75,Vehicle_Physical_Dimensions:physical};
const before=JSON.stringify(record),registered=Catalog.resolve(record);
assert.equal(registered.dimensions_origin,'recorded_physical');
assert.deepEqual(plain(registered.dimensions),physical);
assert.equal(registered.dimensions.measurement_status,'not_established_by_vehicle_type');
assert.equal(registered.physical.dimensions_status,'recorded');
const override={length_m:11.5,width_m:2.45,source:'explicit_presentation_fixture',assumed:true};
const explicit=Catalog.resolve({...record,Vehicle_Dimensions:override});
assert.equal(explicit.dimensions_origin,'recorded_visual');near(explicit.dimensions.length_m,11.5);
assert.equal(explicit.physical.dimensions.length_m,10.8,'a visual override does not rewrite configured dimensions');
const invalidValues=[{},false,[],{length_m:0,width_m:1,source:'bad'},
  {length_m:5,width_m:Infinity,source:'bad'},{length_m:5,width_m:2,source:'   '}];
for(const value of invalidValues) {
  const fallback=Catalog.resolve({...record,Vehicle_Dimensions:value});
  assert.equal(fallback.dimensions_origin,'recorded_physical');near(fallback.dimensions.length_m,10.8);
  assert.equal(fallback.dimension_diagnostics.length,1);
  const assumed=Catalog.resolve({...record,Vehicle_Dimensions:value,Vehicle_Physical_Dimensions:value});
  assert.equal(assumed.dimensions_origin,'family_assumption');near(assumed.dimensions.length_m,12);
  assert.equal(assumed.physical.dimensions_status,'invalid');assert.equal(assumed.dimension_diagnostics.length,2);
}
assert.equal(JSON.stringify(record),before);
assert.equal(Catalog.resolve({Agent_Type:'TransportePublico',Vehicle_Physical_Dimensions:physical}).dimensions,null,
  'dimension metadata cannot create a service vehicle for a passenger');

function road(points,extra={}) {
  return {path:points,num_lanes:1,lane_width_m:3.5,opposing_lanes:0,offset_eligible:true,native_lanes:{},
    from_node:'start',to_node:'end',allowed_to_links:[],movement_source:'effective_car_node_adjacency',...extra};
}
function marker(lanes,id,Vehicle_Type,fraction,start=0,end=100,extra={}) {
  const data=lanes.links.get(id).data,raw={vehicle:'identity',Agent_ID:'person',Replay_Journey_Key:'trip',
    Vehicle_Type,Link_ID:id,path:data.path,timestamps:[start,end],Visual_Motion_Fraction:fraction,
    Motion_Plan:{version:1,status:'constant',distance_m:lanes.describe(id).length_m,
      phases:[[start,end,0,lanes.describe(id).length_m/(end-start),0]]},...extra};
  return {...raw,...lanes.marker(raw,fraction,{},xy(0,0))};
}
function corners(body) {
  const a=body.heading*Math.PI/180,c=Math.cos(a),s=Math.sin(a),x=body.position[0]*scale,y=body.position[1]*scale;
  return [[-1,-1],[-1,1],[1,1],[1,-1]].map(([forward,side])=>[
    x+forward*c*body.length_m/2-side*s*body.width_m/2,y+forward*s*body.length_m/2+side*c*body.width_m/2]);
}
function pointDistance(point,points) {
  let best=Infinity;
  for(let i=1;i<points.length;i++) {
    const a=points[i-1].map(v=>v*scale),b=points[i].map(v=>v*scale),dx=b[0]-a[0],dy=b[1]-a[1];
    const t=Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)));
    best=Math.min(best,Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy));
  }
  return best;
}
const arc=Array.from({length:13},(_,i)=>{const a=i*5*Math.PI/180;return xy(80*Math.sin(a),80*(1-Math.cos(a)));});
const lanes=new Lanes({schema_version:1,links:{curve:road(arc),straight:road([xy(0,0),xy(100,0)])}});
for(const [type,length,width] of defaults)for(const fraction of [.25,.5,.75]) {
  const m=marker(lanes,'curve',type,fraction),source=JSON.stringify(m),body=lanes.vehicleBody(m);
  near(body.length_m,length);near(body.width_m,width);assert.equal(body.clipped,false);assert.equal(body.opacity,1);
  assert.deepEqual(plain(body.position),plain(m.position),'a longer body does not displace its recorded centre');
  near(Math.hypot((body.path[1][0]-body.path[0][0])*lanes.projection.xScale,
    (body.path[1][1]-body.path[0][1])*lanes.projection.yScale),length);
  assert.ok(corners(body).every(point=>pointDistance(point,arc)<=3.5/2+1e-5),'bodies fit this demonstrably wide, gentle fixture');
  assert.equal(JSON.stringify(m),source);
}
const configured=marker(lanes,'straight','TransitBus',.5,0,100,{Vehicle_Physical_Dimensions:physical});
near(lanes.vehicleBody(configured).length_m,10.8);near(lanes.vehicleBody(configured).width_m,2.35);
const invalid=marker(lanes,'straight','TransitBus',.5,0,100,{Vehicle_Dimensions:{length_m:0}});
const retained=new Queues(lanes).frame([invalid,marker(lanes,'curve','Normal',.5,0,100,{vehicle:'other'})],50);
assert.equal(retained.markers.length,2);assert.equal(retained.omitted.length,0,'one malformed optional dimension record cannot abort a frame');

// A narrow 90-degree node does not define a swept turning path for a rigid bus.
// The renderer must preserve dimensions/centre and expose estimated support,
// not shrink or shift it to manufacture containment in these two road strips.
const incoming=road([xy(0,0),xy(50,0)],{to_node:'junction',allowed_to_links:['out']}),
  outgoing=road([xy(50,0),xy(50,50)],{from_node:'junction'});
const turn=new Lanes({schema_version:1,links:{in:incoming,out:outgoing}});
for(const type of ['TransportePesado','TransitBus']) {
  const a=marker(turn,'in',type,1,0,10),b=marker(turn,'out',type,0,10,20),original=JSON.stringify([a,b]);
  const moving=turn.vehicleBody(a,{next:b}),after=turn.vehicleBody(b,{previous:a});
  near(moving.heading,45);near(after.heading,45);assert.deepEqual(plain(moving.position),plain(after.position));
  assert.equal(moving.support,'observed_transition_estimated_pose');
  assert.ok(corners(moving).some(point=>Math.min(pointDistance(point,incoming.path),pointDistance(point,outgoing.path))>1.75),
    'this narrow-corner fixture is not evidence that a full long body fits');
  const stopped=turn.vehicleBody({...a,Waiting:true},{next:b});
  near(stopped.heading,0);assert.equal(stopped.support,'current_link');
  near(stopped.length_m,Catalog.resolve(a).dimensions.length_m);assert.equal(stopped.clipped,false);
  assert.equal(JSON.stringify([a,b]),original);
}
console.log('PASS: exact defaults, visual/physical/fallback precedence, malformed-record retention, PCU independence, long rigid curves and honest narrow-turn limits');
