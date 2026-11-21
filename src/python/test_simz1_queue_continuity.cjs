// Explicitly run synthetic continuity checks; never opens a browser/server,
// simulates QSim, writes a run, or changes native timestamps/Motion_Plan.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const sources=['simz1_visual_lanes.js','simz1_visual_queues.js','simz1_spatial_view.js'];
const [Lanes,Queues,Spatial]=vm.runInNewContext(sources.map(name=>fs.readFileSync(path.join(__dirname,name),'utf8')).join('\n')+
  '\n[SimZ1VisualLanes,SimZ1VisualQueues,SimZ1SpatialView]',{});
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],clone=value=>JSON.parse(JSON.stringify(value));
const near=(a,b,tolerance=1e-5)=>assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);
const evidence=[];
function road(points,from,to,targets=[],extra={}) {
  return {path:points.map(p=>xy(...p)),from_node:from,to_node:to,allowed_to_links:targets,
    num_lanes:1,lane_width_m:3,opposing_lanes:0,native_lanes:{},offset_eligible:true,
    movement_source:'effective_car_node_adjacency',osm_tags:{},...extra};
}
function setup(links) { const lanes=new Lanes({schema_version:1,links});return {links,lanes,queue:new Queues(lanes)}; }
function record(f,vehicle,link,start,end,{hold=null,type='car'}={}) {
  const distance=f.lanes.describe(link).length_m,stop=hold ?? end;
  return {vehicle,Agent_ID:'person:'+vehicle,Replay_Journey_Key:'trip:'+vehicle,
    Trip:{Trip_ID:'trip:'+vehicle,Person_ID:'person:'+vehicle},Vehicle_Type:type,Link_ID:link,path:f.links[link].path,timestamps:[start,end],
    Motion_Plan:{version:1,status:'kinematic',distance_m:distance,...(hold==null ? {} : {hold_start:hold,native_wait_boundary:hold}),
      phases:[[start,stop,0,distance/(stop-start),0],...(hold==null ? [] : [[hold,end,distance,0,0]])]},
    Observed_Waits:hold==null ? {} : {priority_stop:{first:hold,last:end,position_evidence:'queue_exit'}}};
}
function marker(f,row,time) {
  const stop=row.Motion_Plan.hold_start ?? row.timestamps[1],fraction=Math.max(0,Math.min(1,(time-row.timestamps[0])/(stop-row.timestamps[0])));
  return {...row,...f.lanes.marker(row,fraction,{},row.path[0]),Visual_Motion_Fraction:fraction,
    Visual_Distance_m:fraction*row.Motion_Plan.distance_m,Waiting:row.Motion_Plan.hold_start!=null && time>=row.Motion_Plan.hold_start};
}
function body(row) {
  return {position:row.position,heading:row.Visual_Body_Heading_Degrees,length_m:row.Visual_Body_Length_Meters,width_m:row.Visual_Body_Width_Meters};
}
function distance(f,a,b) {
  return Math.hypot((a[0]-b[0])*f.lanes.projection.xScale,(a[1]-b[1])*f.lanes.projection.yScale);
}
function rigid(f,value,length,width) {
  assert(value);assert.equal(value.path.length,2);near(value.length_m,length);near(value.width_m,width);
  near(distance(f,...value.path),length);assert.equal(value.opacity,1);assert.equal(value.clipped,false);
}

// A 20 cm connector still carries a full rigid body at both half-open boundaries.
const turn=setup({a:road([[-40,0],[0,0]],'west','j1',['b']),
  b:road([[0,0],[0,.2]],'j1','j2',['c']),c:road([[0,.2],[0,40.2]],'j2','north')});
for(const [type,length,width] of [['car',4.5,1.8],['motorcycle',2.1,.8],['bus',12,2.5]]) {
  const rows=[record(turn,type,'a',0,10,{type}),record(turn,type,'b',10,11,{type}),record(turn,type,'c',11,21,{type})];
  const snapshot=JSON.stringify(rows),a=marker(turn,rows[0],10),b=marker(turn,rows[1],10),c=marker(turn,rows[2],11);
  const left=turn.lanes.vehicleBody(a,{next:b}),right=turn.lanes.vehicleBody(b,{previous:a,next:c});
  near(distance(turn,left.position,right.position),0);near(left.heading,right.heading);
  for(const time of [10,10.001,10.5,10.999,11]) {
    const pose=turn.lanes.vehicleBody(marker(turn,rows[1],time),{previous:a,next:c});
    rigid(turn,pose,length,width);
  }
  // Adjustment is not a hold: the entering body keeps the observed joint pose.
  const forming={...b,Visual_Queue_Center_Meters:0,Visual_Queue_Holding:false,Waiting:false};
  const moving=turn.lanes.vehicleBody(forming,{previous:a,next:c});
  near(moving.heading,left.heading);near(distance(turn,moving.position,left.position),0);
  const held=turn.lanes.vehicleBody({...forming,Visual_Queue_Holding:true},{previous:a,next:c});
  near(held.heading,90);assert.equal(held.support,'current_link');
  const nativeHeld=turn.lanes.vehicleBody({...forming,Waiting:true},{previous:a,next:c});
  near(nativeHeld.heading,90); // Native hold takes precedence over an erroneous moving flag.
  const legacy=turn.lanes.vehicleBody({...forming,Visual_Queue_Holding:undefined},{previous:a,next:c});
  near(legacy.heading,90);
  assert.equal(JSON.stringify(rows),snapshot);
  evidence.push({case_id:'forming_joint_'+type,heading_before:left.heading,heading_forming:moving.heading,
    heading_held:held.heading,dimensions_m:[length,width]});
}

// Integration: frame() must explicitly distinguish moving spacing from the
// later hold; testing vehicleBody's flag in isolation would miss a bad caller.
const entering=setup({a:road([[-40,0],[0,0]],'west','junction',['b']),
  b:road([[0,0],[0,40]],'junction','north')});
const approach=record(entering,'forming-turn','a',0,10),waitRecord=record(entering,'forming-turn','b',10,30,{hold:20});
const approachEnd=marker(entering,approach,10),waitStart=marker(entering,waitRecord,10),waitPose=marker(entering,waitRecord,20);
const priorBody=entering.lanes.vehicleBody(approachEnd,{next:waitStart}),enterRoster=[waitPose];
const formed=entering.queue.frame([waitStart],10,()=>({previous:approachEnd}),enterRoster);
assert.equal(formed.markers.length,1);assert.equal(formed.omitted.length,0);
assert.equal(formed.markers[0].Visual_Queue_State,'forming');
near(formed.markers[0].Visual_Body_Heading_Degrees,priorBody.heading);
near(distance(entering,formed.markers[0].position,priorBody.position),0);
assert.equal(formed.markers[0].Visual_Body_Support,'observed_transition_estimated_pose');
const stopped=entering.queue.frame([waitPose],20,()=>({previous:approachEnd}),enterRoster);
assert.equal(stopped.markers[0].Visual_Queue_State,'queued');near(stopped.markers[0].Visual_Body_Heading_Degrees,90);
evidence.push({case_id:'frame_forming_transition',prior_heading:priorBody.heading,
  forming_heading:formed.markers[0].Visual_Body_Heading_Degrees,held_heading:stopped.markers[0].Visual_Body_Heading_Degrees});

// Piecewise straight axis: heading changes continuously around each bend while
// the body stays rigid, including a long vehicle and 359/0 angular wrap.
const curve=setup({bend:road([[0,0],[30,0],[30,30],[60,30]],'start','end')});
const geometry=curve.lanes.links.get('bend').geometry;
for(const length of [2.1,4.5,12,18])for(const station of geometry.distances.slice(1,-1)) {
  const before=curve.lanes.body('bend',station-1e-6,0,length,2),at=curve.lanes.body('bend',station,0,length,2),
    after=curve.lanes.body('bend',station+1e-6,0,length,2);
  for(const value of [before,at,after])rigid(curve,value,length,2);
  assert(Math.abs(before.heading-after.heading)<.001);
}
near(curve.lanes.interpolateHeading(359,1,.5),0);

// Mixed bodies in a held FIFO retain their reference dimensions and stations
// during pause, reverse seeks and the earlier leader's recorded departure.
const straight=setup({q:road([[0,0],[200,0]],'a','b',['next'],{source_way:'same'}),
  next:road([[200,0],[400,0]],'b','c',[],{source_way:'same'})});
const records=[record(straight,'bus','q',0,60,{hold:20,type:'bus'}),
  record(straight,'moto','q',1,90,{hold:21,type:'motorcycle'}),
  record(straight,'car','q',2,120,{hold:22,type:'car'}),record(straight,'bus','next',60,100,{type:'bus'})];
const immutable=JSON.stringify(records),roster=records.filter(row=>row.Motion_Plan.hold_start!=null).map(row=>marker(straight,row,row.Motion_Plan.hold_start));
const neighbors=pose=>{
  const previous=records.find(row=>row.vehicle===pose.vehicle && row.timestamps[1]===pose.timestamps[0]);
  const next=records.find(row=>row.vehicle===pose.vehicle && row.timestamps[0]===pose.timestamps[1]);
  return {previous:previous ? marker(straight,previous,previous.timestamps[1]) : null,next:next ? marker(straight,next,next.timestamps[0]) : null};
};
const frame=time=>straight.queue.frame(records.filter(row=>row.timestamps[0]<=time && time<row.timestamps[1]).map(row=>marker(straight,row,time)),time,neighbors,roster);
const first=frame(30),positions=value=>clone(value.markers.map(row=>[row.vehicle,row.position,row.Visual_Body_Heading_Degrees]));
assert.equal(first.markers.length,3);assert.equal(first.omitted.length,0);
for(let i=0;i<first.markers.length;i++)for(let j=0;j<i;j++)assert.equal(straight.queue.envelopesOverlap(body(first.markers[i]),body(first.markers[j])),false);
for(const time of [30,45,75,30]) {
  const value=frame(time);
  if(time<60)assert.deepEqual(positions(value),positions(first));
  else for(const id of ['moto','car'])near(distance(straight,first.markers.find(row=>row.vehicle===id).position,value.markers.find(row=>row.vehicle===id).position),0);
}
const beforeHold=frame(19.999).markers.find(row=>row.vehicle==='bus'),atHold=frame(20).markers.find(row=>row.vehicle==='bus');
assert(distance(straight,beforeHold.position,atHold.position)<.02);
const beforeExit=frame(59.999),afterExit=frame(60),heldBus=beforeExit.markers.find(row=>row.vehicle==='bus'),exitedBus=afterExit.markers.find(row=>row.vehicle==='bus');
assert(beforeExit.diagnostics.limitations.some(row=>row.vehicle_id==='bus' && row.reason==='queue_exit_has_no_substep_trajectory'));
assert.equal(heldBus.Waiting,true);assert.equal(exitedBus.Waiting,false);
const releaseDisplacement=distance(straight,heldBus.position,exitedBus.position);
assert(releaseDisplacement>0,'recorded instantaneous exit cannot imply an invented substep trajectory');
evidence.push({case_id:'recorded_discrete_release',vehicle_id:'bus',before_time:59.999,after_time:60,
  displacement_m:releaseDisplacement,before_heading:heldBus.Visual_Body_Heading_Degrees,after_heading:exitedBus.Visual_Body_Heading_Degrees,
  limitation:'queue_exit_has_no_substep_trajectory'});
assert.equal(JSON.stringify(records),immutable);

// A short compatible subdivision does not authorize a backwards approach.
// With a 12 m body and a 2 m link, L-head is negative: scaling it by the
// increasing native fraction used to draw the bus reversing before hold.
// Preserve the known native pose and diagnose the unsupported queue projection.
const short=setup({up:road([[0,0],[50,0]],'s','j',['tiny'],{source_way:'section'}),
  tiny:road([[50,0],[52,0]],'j','k',['out'],{source_way:'section'}),
  out:road([[52,0],[102,0]],'k','t',[],{source_way:'section'})});
const shortRows=[record(short,'long-body','up',0,10,{type:'bus'}),
  record(short,'long-body','tiny',10,30,{type:'bus',hold:20}),record(short,'long-body','out',30,40,{type:'bus'})];
const shortNative=JSON.stringify(shortRows),shortRoster=[marker(short,shortRows[1],20)],shortTrace=[];
for(const time of [10,10.1,15,19.999,20,25,29.999]) {
  const result=short.queue.frame([marker(short,shortRows[1],time)],time,()=>({previous:marker(short,shortRows[0],10),
    next:marker(short,shortRows[2],30)}),shortRoster);
  assert.equal(result.markers.length,1,'a supported native pose remains inspectable despite an impossible queue projection');
  assert.equal(result.omitted.length,0);
  const row=result.markers[0],station=(row.position[0]-short.links.tiny.path[0][0])*short.lanes.projection.xScale;
  near(row.Visual_Body_Length_Meters,12);near(row.Visual_Body_Width_Meters,2.5);
  assert(station>=-1e-7,'forming must not move backwards onto the prior interval');
  if(shortTrace.length)assert(station>=shortTrace.at(-1).station_m-1e-7,'native increasing progress cannot become backwards visual motion');
  shortTrace.push({time,station_m:station,queue_state:row.Visual_Queue_State,reason:row.Visual_Queue_Reason});
}
near(shortTrace.at(-1).station_m,shortTrace.find(row=>row.time===20).station_m);
assert.equal(JSON.stringify(shortRows),shortNative);
evidence.push({case_id:'short_link_prehold_no_reverse',vehicle_id:'long-body',trace:shortTrace});

// A spatial boundary tests the supported centre and never cuts the rigid body.
const identity={run_id:'fixture:continuity',iteration:0,run_manifest_sha256:'a'.repeat(64)};
const spatial=new Spatial({schema_version:1,mode:'gateway-od',validated:true,identity,allowed_links:['q'],
  boundary:{type:'Polygon',coordinates:[[xy(0,-20),xy(200,-20),xy(200,20),xy(0,20),xy(0,-20)]]}},identity);
for(const [type,length,width] of [['motorcycle',2.1,.8],['bus',12,2.5]]) {
  const row=record(straight,'edge:'+type,'q',0,20,{type}),pose=marker(straight,row,0),value=straight.lanes.vehicleBody(pose);
  rigid(straight,value,length,width);
  const rendered={...pose,position:value.position,Visual_Body_Path:value.path,Visual_Body_Length_Meters:length,Visual_Body_Width_Meters:width};
  assert.equal(spatial.markers([rendered])[0],rendered,'centre at the boundary keeps the whole nominal body');
}
// The lane offset is a display estimate, not evidence that the native centre
// left the validated domain. Conversely it cannot pull an outside trip in.
const boundaryOffset={vehicle:'offset',Link_ID:'q',position:xy(100,-21),Visual_Native_Center_Position:xy(100,-20)};
assert.equal(spatial.contains(boundaryOffset.position),false);
assert.equal(spatial.markerVisible(boundaryOffset),true);
assert.equal(spatial.markers([boundaryOffset])[0],boundaryOffset);
const nativeOutside={...boundaryOffset,position:xy(100,-19),Visual_Native_Center_Position:xy(100,-21)};
assert.equal(spatial.markerVisible(nativeOutside),false);
assert.equal(spatial.markers([nativeOutside]).length,0);
assert.equal(spatial.markerVisible({...boundaryOffset,Link_ID:'not-allowed'}),false);
assert.equal(spatial.markerVisible({Link_ID:'q',position:xy(100,-19)}),true,'legacy caller uses its supported centre');
assert.equal(spatial.markerVisible({Link_ID:'q',position:xy(100,-21)}),false);
evidence.push({case_id:'spatial_native_centre_membership',offset_outside_native_inside_visible:true,
  offset_inside_native_outside_visible:false,disallowed_link_visible:false,legacy_fallback:'position'});
if(process.argv.includes('--evidence'))console.log(JSON.stringify(evidence,null,2));
else console.log('PASS: rigid boundaries, moving/held joint distinction, mixed queues, reverse seek and documented discrete release');
