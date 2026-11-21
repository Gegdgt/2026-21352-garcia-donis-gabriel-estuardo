// Tiny native-interval fixtures; no browser, server, simulation or replay files.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const code=['simz1_visual_lanes.js','simz1_visual_queues.js'].map(f=>fs.readFileSync(path.join(__dirname,f),'utf8')).join('\n');
const [Lanes,Queues]=vm.runInNewContext(code+'\n[SimZ1VisualLanes,SimZ1VisualQueues];',{});
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],clone=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,e=1e-5)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
const links={a:{from_node:'n0',to_node:'n1',path:[xy(0,0),xy(10,0)],allowed_to_links:['b']},
  b:{from_node:'n1',to_node:'n2',path:[xy(10,0),xy(10,.2)],allowed_to_links:['c']},
  c:{from_node:'n2',to_node:'n3',path:[xy(10,.2),xy(10,10)],allowed_to_links:[]}};
for(const [id,link] of Object.entries(links))Object.assign(link,{num_lanes:1,source_way:id,osm_tags:{},
  movement_source:'effective_car_node_adjacency',offset_eligible:true,native_lanes:{}});
const lanes=new Lanes({schema_version:1,links}),queue=new Queues(lanes);
function marker(id,start,end,fraction) {
  const raw={vehicle:'v',Agent_ID:'p',Replay_Journey_Key:'journey',Link_ID:id,path:links[id].path,timestamps:[start,end],
    Visual_Motion_Fraction:fraction,Visual_Speed_kmh:3.6,color:[245,65,65],Observed_Waits:{},
    Motion_Plan:{version:1,status:'constant',distance_m:lanes.describe(id).length_m}};
  return {...raw,...lanes.marker(raw,fraction,{},xy(0,0))};
}
const a=marker('a',0,10,1),b=marker('b',10,11,0),c=marker('c',11,21,0),before=JSON.stringify([a,b,c]);
const first=lanes.vehicleBody(a,{next:b}),second=lanes.vehicleBody(b,{previous:a,next:c});
near(first.heading,45);near(second.heading,45);
near(first.position[0],second.position[0]);near(first.position[1],second.position[1]);
for(const body of [first,second,lanes.vehicleBody(marker('b',10,11,.5),{previous:a,next:c})]) {
  assert.equal(body.path.length,2,'rigid centre axis, never a bent polyline');
  near(body.length_m,4.5);near(body.width_m,1.8);assert.equal(body.opacity,1);assert.equal(body.clipped,false);
  near(Math.hypot((body.path[1][0]-body.path[0][0])*scale,(body.path[1][1]-body.path[0][1])*scale),4.5);
}
assert.equal(first.support,'observed_transition_estimated_pose');
const held={...a,Visual_Queue_Center_Meters:5.5,position:xy(5.5,0),Waiting:true};
const heldBody=lanes.vehicleBody(held,{next:b});
near(heldBody.heading,0);near(heldBody.position[0]*scale,5.5);
assert.equal(heldBody.support,'current_link','a wait never rotates toward the next link');
const enteredBody=lanes.vehicleBody(b,{previous:a,next:c});
assert.ok(Math.hypot((enteredBody.position[0]-heldBody.position[0])*scale,
  (enteredBody.position[1]-heldBody.position[1])*scale)<=4.5+1e-5,
  'the discrete exit stays within the stop margin; no relocation to another carriageway');
const wider=clone(links);wider.a.num_lanes=2;
const lateral=new Lanes({schema_version:1,links:wider});
const left={...a,...lateral.marker(a,1,{},a.position)},right={...b,...lateral.marker(b,0,{},b.position)};
const leftBody=lateral.vehicleBody(left,{next:right}),rightBody=lateral.vehicleBody(right,{previous:left});
for(let i=0;i<2;i++)near(leftBody.position[i]*scale,rightBody.position[i]*scale);
near(leftBody.heading,rightBody.heading);
const straightLinks={a:{...links.a,num_lanes:2},b:{...links.b,num_lanes:2,path:[xy(10,0),xy(20,0)],allowed_to_links:[]}};
const straightLanes=new Lanes({schema_version:1,links:straightLinks});
const laneEnd={...a,Visual_Lane_Index:0,position:straightLanes.place('a',10,0).position};
const laneStart={...b,path:straightLinks.b.path,Visual_Lane_Index:1,position:straightLanes.place('b',0,1).position};
const beforeChange=straightLanes.vehicleBody(laneEnd,{next:laneStart}),afterChange=straightLanes.vehicleBody(laneStart,{previous:laneEnd});
near(beforeChange.position[1]*scale,1.5);near(afterChange.position[1]*scale,-1.5);
assert.equal(beforeChange.support,'current_link','a straight lane discontinuity never averages a car between two lanes');
assert.equal(afterChange.support,'current_link');
near(lanes.interpolateHeading(359,0,.5),359.5);near(lanes.interpolateHeading(359,1,.5),0);
near(lanes.interpolateHeading(1,359,.5),0);
for(const incompatible of [{...b,timestamps:[10.1,11]},{...b,vehicle:'other'},{...b,Replay_Journey_Key:'other'}])
  assert.equal(lanes.vehicleBody(a,{next:incompatible}).support,'current_link','no bridge over missing/incompatible events');
const forbidden=clone(links);forbidden.a.allowed_to_links=[];
assert.equal(new Lanes({schema_version:1,links:forbidden}).vehicleBody(a,{next:b}).support,'current_link');
const upper=clone(links);upper.b.osm_tags={bridge:'yes',layer:'1'};
assert.equal(new Lanes({schema_version:1,links:upper}).vehicleBody(a,{next:b}).support,'current_link');
for(const fraction of [0,.01,.5,.99,1]) {
  const frame=queue.frame([marker('b',10,11,fraction)],10+fraction,()=>({previous:a,next:c}));
  assert.equal(frame.markers.length,1,'short links and exact endpoints do not hide a known centre');
  near(frame.markers[0].Visual_Body_Length_Meters,4.5);near(frame.markers[0].Visual_Body_Opacity,1);
}
const fixed={...a,path:[links.a.path[1],links.a.path[1]],Visual_Motion_Fraction:0,position:links.a.path[1],Visual_Lane_Index:null};
assert.ok(lanes.vehicleBody(fixed),'recorded stationary endpoint has a rigid body');
assert.equal(lanes.vehicleBody({...fixed,Link_ID:'unknown',path:[xy(3,3),xy(3,3)]}),null,'unknown orientation is diagnosed, never invented');
assert.equal(JSON.stringify([a,b,c]),before,'events, geometry, color and Motion_Plan remain immutable');
console.log('PASS: rigid dimensions, short links, observed turns, angular wrap, stationary points and unknown transitions');
