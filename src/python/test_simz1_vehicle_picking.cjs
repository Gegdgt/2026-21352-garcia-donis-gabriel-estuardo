// Pure in-memory picking fixtures. No browser, server, MATSim or population generation.
'use strict';
const assert=require('node:assert/strict');
const Picking=require('./simz1_vehicle_picking.js');
const point=(vehicle,x,y,extra={})=>({vehicle,Link_ID:'east',position:[x,y],...extra});
const screen={width:300,height:200,project:position=>position};
const pick=(markers,x,y,options={})=>Picking.pick(markers,{...screen,x,y,...options});

const tinyWhite=point('white',100,80,{color:[255,255,255],Visual_Lane_Marker_Radius_Meters:.03});
assert.equal(Picking.key({...tinyWhite,Replay_Journey_Key:'trip',Link_ID:'before'}),
  Picking.key({...tinyWhite,Replay_Journey_Key:'trip',Link_ID:'after'}),'graphic identity survives a link change');
const largeRed=point('red',110,80,{color:[245,65,65],Visual_Lane_Marker_Radius_Meters:.8});
const nativeCopy=JSON.stringify([tinyWhite,largeRed]);
assert.equal(pick([tinyWhite],108,80).object,tinyWhite,'mouse hitbox includes the exact 8px edge');
assert.equal(pick([tinyWhite],108.001,80),null);
assert.equal(pick([tinyWhite],117,80),null,'mouse cannot use the touch radius');
assert.equal(pick([tinyWhite],117,80,{pointerType:'touch'}).object,tinyWhite);
assert.equal(pick([tinyWhite],118,80,{pointerType:'touch'}).radiusPixels,18);
assert.equal(pick([tinyWhite],118.001,80,{pointerType:'touch'}),null);
assert.equal(pick([tinyWhite,largeRed],101,80,{pointerType:'touch'}).object,tinyWhite,'color and visible radius do not bias picking');
assert.equal(pick([tinyWhite,largeRed],109,80,{pointerType:'touch'}).object,largeRed,'nearest center wins across adjacent lanes');
assert.equal(pick([largeRed,tinyWhite],109,80,{pointerType:'touch'}).object,largeRed,'array order does not choose a lane');
const tiedWhite=point('a-white',95,80,{color:[255,255,255]}),tiedRed=point('b-red',105,80,{color:[245,65,65]});
assert.equal(pick([tiedRed,tiedWhite],100,80).object,tiedWhite,'an exact white/red tie uses identity, not color');
assert.equal(JSON.stringify([tinyWhite,largeRed]),nativeCopy,'selection cannot mutate native/visual marker data');
console.log('PASS: independent mouse/touch hitbox, white/red vehicles, tiny markers and nearest parallel lane');

const left=point('a',95,50),right=point('b',105,50);
assert.equal(pick([right,left],100,50).object,left);
assert.equal(pick([left,right],100,50).object,left,'equal distance uses stable vehicle identity');
const sameVehicleLeft=point('same',95,50,{Link_ID:'a'}),sameVehicleRight=point('same',105,50,{Link_ID:'b'});
assert.equal(Picking.key(sameVehicleLeft),Picking.key(sameVehicleRight),'link boundaries retain one vehicle identity');
for(const rows of [[sameVehicleRight,sameVehicleLeft],[sameVehicleLeft,sameVehicleRight]])
  assert.equal(Picking.key(pick(rows,100,50).object),Picking.key(sameVehicleLeft),
    'duplicate representations of one vehicle cannot become distinct selected identities');
const sameLinkEarlier=point('same',95,50,{Replay_Journey_Key:'a'}),sameLinkLater=point('same',105,50,{Replay_Journey_Key:'b'});
assert.equal(pick([sameLinkLater,sameLinkEarlier],100,50).object,sameLinkEarlier,'journey identity resolves the remaining tie');
const dense=Array.from({length:225},(_,index)=>point('vehicle-'+index,20+(index%15)*2,20+Math.floor(index/15)*2));
assert.equal(pick(dense,34.2,34.1,{pointerType:'touch'}).object.vehicle,'vehicle-112');
assert.equal(pick([...dense].reverse(),34.2,34.1,{pointerType:'touch'}).object.vehicle,'vehicle-112');
const tenThousand=Array.from({length:10000},(_,index)=>point('dense-'+index,10+(index%100)*2,10+Math.floor(index/100)*2));
assert.equal(pick(tenThousand,110.1,110.1).object.vehicle,'dense-5050','10k candidates retain exact nearest selection');
console.log('PASS: dense overlap selects the nearest vehicle, with deterministic ties independent of render order');

const moving=point('moving',10,12),zoomOne=position=>[position[0]*5,position[1]*5],zoomTwo=position=>[position[0]*10,position[1]*10];
assert.equal(pick([moving],57,60,{project:zoomOne}).object,moving);
assert.equal(pick([moving],107,120,{project:zoomTwo}).object,moving,'hitbox stays in CSS pixels after zoom');
assert.equal(pick([moving],57,60,{project:zoomTwo}),null,'zoom does not reuse a cached projection');
assert.equal(pick([moving],107,120,{project:zoomTwo}).distancePixels,7);
assert.equal(pick([],107,120,{project:zoomTwo}),null,'seek to an empty window cannot retain a stale hit');
const sought=point('moving',20,12);
assert.equal(pick([sought],107,120,{project:zoomTwo}),null,'seek uses only the supplied current marker position');
assert.equal(pick([sought],200,120,{project:zoomTwo}).object,sought);
assert.equal(pick([moving],107,120,{project:zoomTwo}).object,moving,'reverse seek restores the same geometric pick');
console.log('PASS: zoom, pause/repeated picks and forward/reverse seeks use current positions without stale cache');

assert.equal(pick([point('offscreen',-1,50)],0,50),null,'offscreen centers are excluded');
assert.equal(pick([tinyWhite],-1,80),null,'a pointer outside the map cannot select');
assert.equal(pick([tinyWhite],100,80,{width:0}),null);
assert.equal(pick([tinyWhite],100,80,{height:NaN}),null);
assert.equal(pick([tinyWhite],100,80,{radiusPixels:-1}),null);
assert.equal(pick([tinyWhite],100,80,{radiusPixels:0}).object,tinyWhite);
assert.equal(pick([tinyWhite],100,80,{project:()=>[NaN,80]}),null);
assert.equal(pick([tinyWhite],100,80,{project:()=>{throw new Error('invalid projection');}}),null);
assert.equal(pick([point('',100,80),point(null,100,80),point('invalid',NaN,80)],100,80),null);
assert.equal(pick([point('transparent',100,80,{opacity:0})],100,80),null,'explicitly invisible markers cannot be picked');
assert.equal(pick([point('released',100,80,{Visual_Queue_Opacity:0})],100,80),null,'invisible queue release cannot be picked');
assert.equal(pick([point('tip',100,80,{Visual_Body_Opacity:0})],100,80),null,'invisible boundary body cannot be picked');
assert.equal(pick([point('hidden-queue',100,80,{Visual_Queue_Representable:false})],100,80),null,'unrepresentable queue vehicles cannot be picked');
assert.equal(pick([point('hidden-queue',100,80,{Visual_Queue_Representable:false}),tinyWhite],100,80).object,tinyWhite);
assert.equal(pick([point('edge',300,200)],300,200).object.vehicle,'edge');
assert.equal(Picking.pick(null,{...screen,x:1,y:1}),null);
assert.equal(Picking.pick([],{}),null);
console.log('PASS: invalid data, missing identity, out-of-viewport pointers and projection failures do not create hits');

// Actual rigid-body footprints in geographic coordinates, projected to CSS px.
const metresPerDegree=6371008.8*Math.PI/180;
const geo=(x,y)=>[x/metresPerDegree,y/metresPerDegree];
const body=(vehicle,x,y,length=12,width=2,heading=0,extra={})=>{
  const angle=heading*Math.PI/180,dx=Math.cos(angle)*length/2,dy=Math.sin(angle)*length/2;
  return {...point(vehicle,...geo(x,y)),Agent_ID:'person-'+vehicle,
    Visual_Body_Path:[geo(x-dx,y-dy),geo(x+dx,y+dy)],Visual_Body_Width_Meters:width,
    Visual_Body_Length_Meters:length,Visual_Body_Heading_Degrees:heading,Visual_Body_Representable:true,...extra};
};
const projectGeo=position=>position.map(value=>value*metresPerDegree);
const pickBody=(markers,x,y,options={})=>pick(markers,x,y,{project:projectGeo,...options});
const parallelWhite=body('a-white-body',100,50,12,2,0,{color:[255,255,255]});
const parallelRed=body('b-red-body',100,54,12,2,0,{color:[245,65,65]});
const bodiesBefore=JSON.stringify([parallelWhite,parallelRed]);
const outline=Picking.bodyOutline(parallelWhite);
assert.equal(outline.length,5);assert.deepEqual(outline[0],outline[4]);
assert.notEqual(outline[0],outline[4],'closed outline does not alias its first point');
assert.equal(outline[0][0],parallelWhite.Visual_Body_Path[0][0],'outline keeps actual rigid-body endpoints');
assert.equal(outline[1][0],parallelWhite.Visual_Body_Path[1][0]);
for(const rows of [[parallelWhite,parallelRed],[parallelRed,parallelWhite]]) {
  const first=pickBody(rows,104,50.8),second=pickBody(rows,104,53.4);
  assert.equal(first.object,parallelWhite);assert.equal(first.insideBody,true);assert.equal(first.distancePixels,0);
  assert.equal(second.object,parallelRed);assert.equal(second.object.Agent_ID,'person-b-red-body');
  assert.equal(pickBody(rows,100,52).object,parallelWhite,'equal body-edge and centre distances use stable identity');
}
assert.equal(JSON.stringify([parallelWhite,parallelRed]),bodiesBefore,'outline and body picks never mutate colour, pose or identity');
const longCar=body('long',100,80,40,4,0,{color:[40,210,95]});
const nearEndNeighbor=body('near-end',119,84,12,2,0,{color:[255,210,40]});
const endHit=pickBody([nearEndNeighbor,longCar],118,81);
assert.equal(endHit.object,longCar,'a click on the actual body beats a closer neighbouring centre');
assert.ok(endHit.centerDistancePixels>Picking.radius());assert.equal(endHit.insideBody,true);
assert.equal(pickBody([longCar],120,80,{radiusPixels:0}).object,longCar,'body end remains clickable with zero aperture');
assert.equal(pickBody([longCar],120.001,80,{radiusPixels:0}),null);
assert.equal(pickBody([longCar],128,80).object,longCar,'8 px mouse aperture is measured from the body edge');
assert.equal(pickBody([longCar],128.001,80),null);
assert.equal(pickBody([longCar],138,80,{pointerType:'touch'}).object,longCar);
assert.equal(pickBody([longCar],138.001,80,{pointerType:'touch'}),null);
console.log('PASS: parallel rigid bodies, original colours, real IDs, endpoints and body-first mouse/touch picking');

const rotated=body('rotated',100,80,40,4,45),rotatedNeighbor=body('rotated-neighbor',113,97,12,2,45);
assert.equal(pickBody([rotatedNeighbor,rotated],113,93).object,rotated,'vehicle heading is part of its clickable footprint');
const cameraRotate=position=>{
  const [x,y]=projectGeo(position);return [80+(x-y)*.7,20+(x+y)*.7];
};
const cameraPerspective=position=>{
  const [x,y]=projectGeo(position),w=1+y/400;return [(100+x)/w,(50+y)/w];
};
for(const project of [cameraRotate,cameraPerspective]) {
  const pixel=project(geo(118,81));
  const picked=pickBody([nearEndNeighbor,longCar],...pixel,{project,radiusPixels:0});
  assert.equal(picked.object,longCar);assert.equal(picked.insideBody,true,
    'project every world-space corner through the current rotated/pitched viewport');
}
const overlapA=body('overlap-a',100,80,20,8),overlapB=body('overlap-b',104,80,20,8);
for(const rows of [[overlapA,overlapB],[overlapB,overlapA]]) {
  assert.equal(pickBody(rows,103,80).object,overlapB,'overlapping interiors prefer the closest centre');
  assert.equal(pickBody(rows,102,80).object,overlapA,'overlapping equal centres use stable identity');
}
const duplicateA=body('same-body',95,80,20,8),duplicateB=body('same-body',105,80,20,8);
const duplicatePick=pickBody([duplicateA,duplicateB],100,80).object;
assert.equal(pickBody([duplicateB,duplicateA],100,80).object,duplicatePick,
  'even duplicate identity and equal-distance geometry ties are independent of draw order');
const tripPersonA={...overlapA,Agent_ID:undefined,Trip:{Trip_ID:'one-trip',Person_ID:'person-a'}};
const tripPersonB={...tripPersonA,Trip:{Trip_ID:'one-trip',Person_ID:'person-b'}};
assert.notEqual(Picking.key(tripPersonA),Picking.key(tripPersonB),'real person identity participates when Agent_ID is absent');
console.log('PASS: rigid rotation, camera projection, overlapping bodies and stable vehicle/person ties');

const partial=body('partly-visible',-3,80,10,2);
assert.equal(pickBody([partial],1,80).object,partial,'visible body remains pickable after its centre leaves the viewport');
assert.equal(pickBody([body('offscreen-body',-9,80,10,2)],0,80),null,'fully offscreen body is excluded');
assert.equal(pickBody([body('hidden-body',100,80,10,2,0,{Visual_Body_Representable:false})],100,80),null);
assert.equal(pickBody([longCar],118,81,{project:position=>position===longCar.position ? [100,80] : [NaN,80]}),null,
  'failed corner projection cannot fall back to another body shape');
assert.equal(Picking.bodyOutline(tinyWhite),null,'legacy point markers retain the centre fallback');
assert.equal(Picking.bodyOutline({...longCar,Visual_Body_Path:[geo(100,80),geo(100,80)]}),null);
assert.equal(Picking.bodyOutline({...longCar,Visual_Body_Width_Meters:0}),null);
assert.equal(pickBody([],118,81),null,'absence of visible bodies never retains a previous selection');
console.log('PASS: viewport-crossing bodies, invalid footprint/projection and no stale or hidden selection');
