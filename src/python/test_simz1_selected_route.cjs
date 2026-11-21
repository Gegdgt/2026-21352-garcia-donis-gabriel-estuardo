// In-memory production controls. No browser, server, historical data or export.
'use strict';
const assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];
const plain=value=>JSON.parse(JSON.stringify(value));
const curve=[xy(0,0),xy(20,0),xy(30,10),xy(30,30)],straight=[xy(100,30),xy(200,30)];
const distance=20+Math.sqrt(200)+20,key='a'.repeat(64),otherKey='c'.repeat(64);
const trip={Trip_ID:'trip-a',Person_ID:'person-a',Departure:10,Arrival:180,Status:'completed',
  Origin_Position:curve[0],Destination_Position:straight.at(-1)};
const otherTrip={...trip,Trip_ID:'trip-b',Person_ID:'person-b'};
function record(link,path,start,end,length=distance) {
  return {vehicle:'vehicle-a',Agent_ID:'person-a',Replay_Journey_Key:key,Link_ID:link,path,timestamps:[start,end],Trip:trip,
    Motion_Plan:{version:1,status:'constant',distance_m:length,cap_mps:10,phases:[[start,end,0,length/(end-start),0]]}};
}
const rows=[record('curve',curve,10,50),record('curve',curve,80,110),
  {...record('unknown',[curve.at(-1),straight[0]],110,119),Motion_Plan:{status:'unavailable'}},
  record('straight',straight,130,170,100)];
const other={...record('curve',curve,10,50),vehicle:'vehicle-b',Agent_ID:'person-b',Replay_Journey_Key:otherKey,Trip:otherTrip};
const lanes={schema_version:1,available:true,links:{curve:{path:curve,num_lanes:2,length_m:distance,
  native_lanes:{left:{index:0,represented_lanes:1,start_m:distance},right:{index:1,represented_lanes:1,start_m:distance}}},
  straight:{path:straight,num_lanes:1,length_m:100}}};
const event=(time,type='entered lane',lane='left')=>({vehicle:'vehicle-a',link:'curve',lane,type,time});
const laneEvents=[event(20),event(40,'left lane'),event(40,'entered lane','right'),event(50,'left lane','right')];
const layer=(h,id)=>h.api.layers.find(row=>row.id===id);
const data=(h,id)=>layer(h,'selected-'+id).props.data;
const snapshot=h=>JSON.stringify([data(h,'history'),data(h,'future')]);
const requests=h=>h.requests.filter(request=>request.url.startsWith('/api/journey'));
function closePoint(actual,expected) {
  assert.ok(actual.every((value,i)=>Math.abs(value-expected[i])<1e-10),`${actual} vs ${expected}`);
}
async function ready(events=[],expectedStatus='complete') {
  const h=harness({},structuredClone(lanes));
  h.reply(0,{segments:[...structuredClone(rows.slice(0,3)),structuredClone(other)],
    trips:{[key]:trip,[otherKey]:otherTrip},lane_replay:{events:[]}});await flush();
  h.api.pause();h.api.seek(35);
  const index=layer(h,'trips').props.data.findIndex(row=>row.vehicle==='vehicle-a');assert.ok(index>=0);
  assert.equal(h.api.selectActive(index),true);assert.equal(data(h,'history').length,0);
  h.journey({key,records:structuredClone(rows),lane_replay:{events}});await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,expectedStatus);return h;
}
(async()=>{
  const before=JSON.stringify({rows,lanes,laneEvents});
  const h=await ready();
  assert.equal(data(h,'history').length,1);assert.equal(data(h,'future').length,3);
  const history=data(h,'history')[0].path,future=data(h,'future')[0].path;
  closePoint(history[1],curve[1]);assert.ok(history.length>=3,'partial route keeps intermediate bend');
  closePoint(future.at(-1),curve.at(-1));closePoint(history.at(-1),future[0]);
  assert.equal(data(h,'future').filter(row=>row.Link_ID==='curve').length,2,'repeated links retain both occurrences');
  assert.ok([...data(h,'history'),...data(h,'future')].every(row=>row.Link_ID!=='unknown'),'no inferred unknown interval');
  assert.ok([...data(h,'history'),...data(h,'future')].every(row=>row.lane===null),'no fabricated hashed lane');
  assert.equal(data(h,'future').at(-1).path[0][0],straight[0][0],'disconnected segment starts at its own source');
  assert.equal(data(h,'history-casing'),data(h,'history'));assert.equal(data(h,'future-casing'),data(h,'future'));
  assert.equal(h.evaluate('routeLegend.hidden'),false);
  const selected=layer(h,'trips').props.data.find(row=>row.vehicle==='vehicle-a');
  const focus=layer(h,'vehicle-focus-outline').props.data.find(row=>row.mode==='pinned');
  assert.equal(focus.marker,selected,'exact selected rigid body, not the route position');
  assert.equal(h.api.getState().vehicleCard.vehicleId,'vehicle-a');
  assert.equal(Object.keys(h.api.getState().vehicleCard.fields).length,6);
  const fixed=snapshot(h),requestCount=requests(h).length;
  h.frame(1000);h.frame(2000);assert.equal(snapshot(h),fixed,'pause preserves paths');
  h.sandbox.deckInstance.props.onViewStateChange({viewState:{...h.api.getState().camera.viewState,zoom:22,pitch:60,bearing:80}});
  assert.equal(snapshot(h),fixed,'camera never changes route metres');assert.equal(requests(h).length,requestCount);
  h.api.seek(65);assert.equal(data(h,'history').length,1);assert.equal(data(h,'future').length,2,'event gap remains separate');
  h.api.seek(120);
  h.reply(1,{segments:[structuredClone(rows[3])],trips:{[key]:trip},lane_replay:{events:[]}});await flush();
  h.api.seek(150);assert.equal(data(h,'history').filter(row=>row.Link_ID==='curve').length,2);
  h.api.seek(35);assert.equal(snapshot(h),fixed,'reverse seek across a window restores exact route');
  assert.equal(requests(h).length,requestCount,'window changes do not refetch the journey');
  h.api.seek(180);
  for(const id of ['history','future','history-casing','future-casing','origin','destination'])assert.equal(data(h,id).length,0,'arrival clears '+id);
  assert.equal(h.evaluate('routeLegend.hidden'),true);assert.equal(h.api.getState().selectedArrival,180);
  h.api.seek(35);assert.equal(snapshot(h),fixed,'arrival is reversible by seek');
  h.api.clearSelection();assert.equal(data(h,'history').length,0);assert.equal(h.evaluate('routeLegend.hidden'),true);

  const native=await ready(laneEvents);
  const pieces=[...data(native,'history'),...data(native,'future')];
  assert.ok(pieces.some(row=>row.lane==='left'));assert.ok(pieces.some(row=>row.lane==='right'));
  assert.ok(pieces.filter(row=>row.timestamps[0]===80).every(row=>row.lane===null),'prior occurrence does not leak its lane');
  const nativeSnapshot=snapshot(native);
  native.api.seek(45);native.api.seek(35);assert.equal(snapshot(native),nativeSnapshot,'equal-time leave/enter order is stable');
  const boundaries=await ready([event(20),
    {vehicle:'vehicle-a',time:45,type:'vehicle leaves traffic'},
    {vehicle:'vehicle-a',time:79,type:'vehicle enters traffic'}]);
  assert.ok([...data(boundaries,'history'),...data(boundaries,'future')].some(row=>row.lane==='left'));
  assert.ok(data(boundaries,'future').filter(row=>row.timestamps[0]===80).every(row=>row.lane===null),
    'traffic boundaries clear prior lane without inventing a lane exit or position');
  await ready([{vehicle:'vehicle-a',time:20,type:'invented-lane-change'}],'unavailable');
  await ready([{vehicle:'vehicle-a',time:20,type:'entered lane'}],'unavailable');
  const late=structuredClone(lanes);late.links.curve.native_lanes.left.start_m=distance*.2;
  const local=harness({},late);local.sandbox.testRows=structuredClone(rows);local.sandbox.testEvent=event(10);
  const plans=local.evaluate('journeyLaneTimelines=new Map([["vehicle-a",[testEvent]]]);routePlan(testRows[0])');
  assert.ok(plans.some(part=>part.row.lane===null));
  assert.ok(plans.some(part=>part.row.lane==='left'));
  assert.ok(plans.filter(part=>part.row.lane).every(part=>part.from>=.8-1e-10),'terminal native lane stays within its extent');
  // Endpoint-only exports still use the compatible network curve.
  local.sandbox.endpointOnly={...structuredClone(rows[0]),path:[curve[0],curve.at(-1)]};
  const curved=local.evaluate('journeyLaneTimelines=new Map();routePlan(endpointOnly)');
  assert.equal(curved[0].row.path.length,4);

  // Selection changes discard the old route immediately; late HTTP cannot repaint it.
  const switcher=await ready();
  const indexB=layer(switcher,'trips').props.data.findIndex(row=>row.vehicle==='vehicle-b');assert.ok(indexB>=0);
  switcher.api.selectActive(indexB);const pending=requests(switcher).at(-1);
  assert.equal(data(switcher,'history').length,0);switcher.api.clearSelection();
  pending.replied=true;pending.resolve({ok:true,json:async()=>({...switcher.identity,key:otherKey,records:[other]})});await flush();
  assert.equal(data(switcher,'history').length,0);assert.equal(switcher.api.getState().selectedVehicleId,null);
  switcher.api.selectActive(indexB);switcher.journey({key:otherKey,records:[structuredClone(other)]});await flush();
  assert.equal(switcher.api.getState().selectedJourneyStatus,'complete');assert.ok(data(switcher,'history').length);
  assert.ok([...data(switcher,'history'),...data(switcher,'future')].every(row=>row.vehicle==='vehicle-b'));
  assert.equal(switcher.api.getState().selectedVehicleId,'vehicle-b');
  assert.equal(JSON.stringify({rows,lanes,laneEvents}),before,'source timestamps, geometry and lane evidence immutable');
  console.log('PASS: curves, repeated links, gaps, native lanes, parallel selection, cache, pause/camera/windows, arrival and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
