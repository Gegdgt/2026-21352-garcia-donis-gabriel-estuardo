'use strict';
// Display-footprint contracts only; no browser, GPU, server or QSim.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const Picking=require('./simz1_vehicle_picking.js');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const metres=6371008.8*Math.PI/180,latitude=14.64,xScale=metres*Math.cos(latitude*Math.PI/180);
const geo=(x,y)=>[-90.52+x/xScale,latitude+y/metres];
const metric=p=>[(p[0]+90.52)*xScale,(p[1]-latitude)*metres];
function body(vehicle,length,width,heading=0,centre=[0,0],extra={}) {
  const angle=heading*Math.PI/180,dx=Math.cos(angle)*length/2,dy=Math.sin(angle)*length/2;
  return {vehicle,position:geo(...centre),Visual_Body_Representable:true,
    Visual_Body_Path:[geo(centre[0]-dx,centre[1]-dy),geo(centre[0]+dx,centre[1]+dy)],
    Visual_Body_Length_Meters:length,Visual_Body_Width_Meters:width,
    Visual_Body_Heading_Degrees:heading,...extra};
}
function projector(pixelsPerMetre,bearing=0,pitch=0) {
  const angle=bearing*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),foreshorten=Math.cos(pitch*Math.PI/180);
  // Plane homography: all four corners project, with a positive denominator.
  // This tests perspective geometry without claiming to execute Deck or a GPU.
  return position=>{
    const [x,y]=metric(position),u=x*c-y*s,v=x*s+y*c,w=1+v*Math.sin(pitch*Math.PI/180)/500;
    return [500+u*pixelsPerMetre/w,350+v*foreshorten*pixelsPerMetre/w];
  };
}
function hit(rows,xy,project,extra={}) {
  return Picking.pick(rows,{x:xy[0],y:xy[1],project,width:1000,height:700,...extra});
}

// A declared malformed rigid body cannot silently become a legacy point hitbox.
const invalid=body('invalid',12,2.5),validPoint={vehicle:'legacy-point',position:geo(0,0)};
for(const changes of [{Visual_Body_Path:[geo(0,0)]},{Visual_Body_Path:[geo(0,0),geo(0,0)]},
    {Visual_Body_Path:[geo(-6,0),geo(0,0),geo(6,0)]},{Visual_Body_Width_Meters:0},
    {Visual_Body_Width_Meters:NaN},{Visual_Body_Path:null}]) {
  assert.equal(hit([{...invalid,...changes}],[500,350],projector(10)),null,
    'invalid declared body must not manufacture a centre hit');
}
assert.equal(hit([validPoint],[508,350],projector(10)).object,validPoint,'legacy point-only payload keeps its 8px aperture');

for(const [family,length,width] of [['car',4.5,1.8],['motorcycle',2.1,.8],['truck',10,2.5],['bus',12,2.5],['articulated',18,2.5]]) {
  for(const zoomScale of [.5,4,24])for(const bearing of [0,90,180,270])for(const pitch of [0,60]) {
    const marker=body(family,length,width,37),project=projector(zoomScale,bearing,pitch);
    const input=JSON.stringify(marker),geographicOutline=Picking.bodyOutline(marker),worldOutline=geographicOutline.map(metric);
    assert.ok(Math.abs(Math.hypot(worldOutline[1][0]-worldOutline[0][0],worldOutline[1][1]-worldOutline[0][1])-length)<1e-5);
    assert.ok(Math.abs(Math.hypot(worldOutline[2][0]-worldOutline[1][0],worldOutline[2][1]-worldOutline[1][1])-width)<1e-5,
      'footprint measures the displayed width in the local metric plane at Guatemala latitude');
    const outline=geographicOutline.map(project),centre=project(marker.position);
    const a=outline[0],b=outline[1],mid=[(a[0]+b[0])/2,(a[1]+b[1])/2];
    let nx=-(b[1]-a[1]),ny=b[0]-a[0],norm=Math.hypot(nx,ny);nx/=norm;ny/=norm;
    if(nx*(mid[0]-centre[0])+ny*(mid[1]-centre[1])<0){nx=-nx;ny=-ny;}
    for(const [pointerType,radius] of [['mouse',8],['touch',18]]) {
      const near=[mid[0]+nx*(radius-.0001),mid[1]+ny*(radius-.0001)];
      const far=[mid[0]+nx*(radius+.0001),mid[1]+ny*(radius+.0001)];
      const selected=hit([marker],near,project,{pointerType});
      assert.equal(selected.object,marker);assert.equal(selected.radiusPixels,radius);
      assert.equal(hit([marker],far,project,{pointerType}),null,'aperture is CSS pixels from the projected edge at every scale');
    }
    const changedPhysics={...marker,Vehicle_PCU:999,Vehicle_Dimensions:{length_m:50,width_m:10,source:'native-fixture'},
      Visual_Safety_Envelope:{length_m:100,width_m:20}};
    assert.deepEqual(Picking.bodyOutline(changedPhysics),Picking.bodyOutline(marker),
      'PCU, physical dimensions and safety envelope cannot inflate the already displayed footprint');
    assert.equal(hit([changedPhysics],centre,project,{radiusPixels:0}).insideBody,true);
    assert.equal(JSON.stringify(marker),input);
  }
}

// Selecting the far end of a long body beats a closer neighbouring centre.
const bus=body('bus-end',18,2.5),neighbor=body('car-neighbor',4.5,1.8,0,[8,3]);
for(const project of [projector(24),projector(24,90,60),projector(24,270,60)]) {
  const pointer=project(geo(8,1));
  for(const rows of [[bus,neighbor],[neighbor,bus]]) {
    const selected=hit(rows,pointer,project);
    assert.equal(selected.object,bus);assert.equal(selected.insideBody,true);
    assert.ok(selected.centerDistancePixels>selected.radiusPixels,'centre radius must not truncate a long bus');
  }
}

// Curved source geometry still produces one final rigid envelope. Pick that
// envelope, not the bent road path or an inferred articulation not in the data.
const Lanes=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VisualLanes');
const curve={path:[geo(0,0),geo(12,0),geo(12,16)],length_m:28,num_lanes:1,opposing_lanes:0,
  lane_width_m:3,offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{},allowed_to_links:[]};
const lanes=new Lanes({schema_version:1,available:true,links:{curve}});
for(const [family,length,width] of [['truck',10,2.5],['bus',12,2.5]]) {
  const raw={vehicle:family,Vehicle_Type:family,Link_ID:'curve',path:curve.path,timestamps:[0,100]};
  const placed={...raw,...lanes.marker(raw,11/28,{},curve.path[0]),Visual_Motion_Fraction:11/28};
  const rigid=lanes.vehicleBody(placed,{},length,width);
  const marker={...placed,position:rigid.position,Visual_Body_Path:rigid.path,
    Visual_Body_Length_Meters:rigid.length_m,Visual_Body_Width_Meters:rigid.width_m,Visual_Body_Representable:true};
  assert.equal(rigid.path.length,2);assert.ok(rigid.heading>0 && rigid.heading<90);
  for(const project of [projector(16),projector(16,180,60)]) {
    const end=rigid.path[1],pointer=project([rigid.position[0]*.1+end[0]*.9,rigid.position[1]*.1+end[1]*.9]);
    assert.equal(hit([marker],pointer,project,{radiusPixels:0}).object,marker);
  }
}
console.log('PASS: declared body validity, 8/18 CSS-pixel margins, independent PCU/native/envelope, long bodies, rotations and pitched curved poses');

// Integration regression: an old hovered vehicle remains within the aperture
// while a different final body moves directly under an unmoved mouse on seek.
async function hoverChangesWithSeek() {
  const xy=x=>[x/metres,0];
  const road={path:[xy(0),xy(100)],length_m:100,num_lanes:2,opposing_lanes:0,lane_width_m:3,offset_eligible:true,
    from_node:'n0',to_node:'n1',native_lanes:{'r.a':{index:0,represented_lanes:1,start_m:100,to_lanes:[]},
      'r.b':{index:1,represented_lanes:1,start_m:100,to_lanes:[]}},allowed_to_links:[],movement_source:'effective_lane_definitions'};
  const records=[{vehicle:'A',start:0,end:100,speed:1},{vehicle:'B',start:10,end:60,speed:2}].map(r=>({
    vehicle:r.vehicle,Agent_ID:r.vehicle,Replay_Journey_Key:r.vehicle,Vehicle_Type:'car',Link_ID:'r',path:road.path,
    timestamps:[r.start,r.end],Motion_Plan:{version:1,status:'constant',distance_m:100,phases:[[r.start,r.end,0,r.speed,0]]}}));
  const h=harness({}, {schema_version:1,available:true,links:{r:road}});
  try {
    h.reply(0,{segments:records,trips:Object.fromEntries(records.map(r=>[r.vehicle,{Trip_ID:r.vehicle,Departure:r.timestamps[0],Arrival:r.timestamps[1],Status:'completed'}])),
      lane_replay:{events:records.map((r,i)=>({vehicle:r.vehicle,link:'r',lane:i?'r.b':'r.a',type:'entered lane',time:r.timestamps[0]}))}});
    await new Promise(resolve=>setImmediate(resolve));h.api.pause();h.api.seek(10);
    const viewport={width:800,height:600,project:p=>[100+p[0]*metres,200+p[1]*metres]};
    h.sandbox.deckInstance.getViewports=()=>[viewport];
    const journeyQueries=h.requests.filter(request=>request.url.startsWith('/api/journey')).length;
    h.evaluate('let pickingCalls=0; const previousPick=SimZ1VehiclePicking.pick; SimZ1VehiclePicking.pick=function(...args){pickingCalls++;return previousPick.apply(this,args);};');
    const markers=()=>h.api.layers.find(l=>l.id==='trips').props.data;
    const b=markers().find(m=>m.vehicle==='B'),pointer=viewport.project([10/metres,b.position[1]]);
    h.sandbox.deckInstance.props.onHover({object:null,x:pointer[0],y:pointer[1]},{pointerType:'mouse'});
    assert.equal(h.api.getState().vehicleCard.vehicleId,'A');
    h.api.seek(15);
    assert.equal(Picking.pick(markers(),{x:pointer[0],y:pointer[1],...viewport}).object.vehicle,'B');
    assert.equal(h.api.getState().vehicleCard.vehicleId,'B','seek must reevaluate the winner, not merely retain an old neighbour within tolerance');
    assert.equal(h.api.getState().selectedKey,null,'hover refresh does not pin a vehicle');
    h.api.seek(10);assert.equal(h.api.getState().vehicleCard.vehicleId,'A','reverse seek restores the geometric hover winner');
    const calls=h.evaluate('pickingCalls');h.api.pause();h.api.pause();
    assert.equal(h.evaluate('pickingCalls'),calls,'unchanged paused frames do not rescan the fleet');
    assert.equal(h.requests.filter(request=>request.url.startsWith('/api/journey')).length,journeyQueries,
      'hover replacement and paused refresh never request a journey');
    // A previous touch must not widen a later mouse hover when animation/seek
    // rechecks it without a new mouse button press (hybrid input hardware).
    h.listeners.pointerdown({target:h.canvas,pointerType:'touch'});
    h.sandbox.deckInstance.props.onHover({object:null,x:pointer[0],y:pointer[1]},{pointerType:'mouse'});
    assert.equal(h.api.getState().vehicleCard.vehicleId,'A');
    h.api.seek(25);
    assert.equal(Picking.pick(markers(),{x:pointer[0],y:pointer[1],...viewport,pointerType:'mouse'}),null);
    assert.equal(h.api.getState().vehicleCard.visible,false,'mouse refresh cannot inherit the previous touch aperture');
    console.log('PASS: hover follows the actual body under a stationary mouse across forward/reverse seek');
  } finally {h.evaluate('continuousReplay.destroy()');}
}
hoverChangesWithSeek().catch(error=>{console.error(error);process.exitCode=1;});
