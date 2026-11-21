// Deterministic regressions for picking + the actual displayed rigid body.
// No server, SQLite, MATSim or generated replay data is used.
const assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];
const keyA='1'.repeat(64),keyB='2'.repeat(64);
const path=[xy(0,0),xy(200,0)];
const laneConfig={schema_version:1,available:true,lane_width_m:3,links:{parallel:{
  path,num_lanes:2,opposing_lanes:0,length_m:200,offset_eligible:true,
  native_lanes:{left:{index:0,represented_lanes:1,start_m:200},right:{index:1,represented_lanes:1,start_m:200}}}}};
const trips={
  [keyA]:{Trip_ID:'trip-a',Person_ID:'person-a',Departure:90,Arrival:140,Status:'completed',Origin_Position:path[0],Destination_Position:path[1]},
  [keyB]:{Trip_ID:'trip-b',Person_ID:'person-b',Departure:90,Arrival:140,Status:'completed',Origin_Position:path[0],Destination_Position:path[1]}};
const records=[
  {vehicle:'vehicle-a',Agent_ID:'person-a',Replay_Journey_Key:keyA,Link_ID:'parallel',path,timestamps:[90,140],
    Motion_Plan:{version:1,status:'kinematic',distance_m:200,cap_mps:5,
      phases:[[90,130,0,5,0],[130,140,200,0,0]]}},
  {vehicle:'vehicle-b',Agent_ID:'person-b',Replay_Journey_Key:keyB,Link_ID:'parallel',path,timestamps:[90,140],
    Motion_Plan:{version:1,status:'kinematic',distance_m:200,cap_mps:10,
      phases:[[90,110,0,10,-.5],[110,120,100,0,0],[120,140,100,5,0]]}}];
const payload={segments:records,trips,lane_replay:{events:records.map((row,index)=>({
  vehicle:row.vehicle,link:'parallel',lane:index ? 'right' : 'left',type:'entered lane',time:90}))}};
const plain=value=>JSON.parse(JSON.stringify(value));
const layer=(h,id)=>h.api.layers.find(row=>row.id===id);
const marker=(h,id)=>layer(h,'trips').props.data.find(row=>row.vehicle===id);
const highlights=h=>layer(h,'vehicle-focus-outline').props.data;
const requests=h=>h.requests.filter(row=>row.url.startsWith('/api/journey'));
function close(actual,expected,message,tolerance=1e-7){assert.ok(Math.abs(actual-expected)<tolerance,message+`: ${actual} vs ${expected}`);}
function viewport(h,angle=0) {
  const radians=angle*Math.PI/180,c=Math.cos(radians),s=Math.sin(radians);
  const view={width:1200,height:900,project:p=>[400+2*metres*(p[0]*c-p[1]*s),400-2*metres*(p[0]*s+p[1]*c)]};
  h.sandbox.deckInstance.getViewports=()=>[view];return view;
}
function pointer(h,kind,vehicle,wrongObject=null) {
  const current=marker(h,vehicle),view=h.sandbox.deckInstance.getViewports()[0],screen=view.project(current.position);
  const info={object:wrongObject,x:screen[0],y:screen[1]};
  if(kind==='click')h.listeners.pointerdown({target:h.canvas,pointerType:'mouse'});
  h.sandbox.deckInstance.props[kind==='click' ? 'onClick' : 'onHover'](info,{type:kind,pointerType:'mouse',tapCount:1});
  return current;
}
function assertFocus(h,vehicle,mode='pinned') {
  const rows=highlights(h),row=rows.find(row=>row.mode===mode),body=marker(h,vehicle);
  assert.ok(row,`one ${mode} highlight`);assert.ok(body,'highlighted vehicle is displayed');
  assert.equal(row.marker,body,'highlight points at the EXACT current trips-layer object, not a reconstructed route marker');
  assert.equal(row.marker.vehicle,vehicle,'the highlighted body has the selected real vehicle_id');
  assert.equal(row.marker.Agent_ID,vehicle.replace('vehicle','person'),'person_id belongs to this body');
  assert.equal(layer(h,'vehicle-focus-halo').props.data,rows,'halo and contour use identical identities and poses');
  const outline=row.outline,bodyPath=body.Visual_Body_Path;
  assert.equal(outline.length,5);assert.deepEqual(plain(outline[0]),plain(outline[4]),'closed rigid footprint');
  // Independent geometry checks: rear/front edge centres, width, longitudinal
  // orientation and centroid must match the existing rendered body exactly.
  for(const [indices,endpoint] of [[[0,3],bodyPath[0]],[[1,2],bodyPath[1]]]) {
    close((outline[indices[0]][0]+outline[indices[1]][0])/2,endpoint[0],'body endpoint longitude',1e-12);
    close((outline[indices[0]][1]+outline[indices[1]][1])/2,endpoint[1],'body endpoint latitude',1e-12);
  }
  const xScale=metres*Math.cos((bodyPath[0][1]+bodyPath[1][1])*Math.PI/360);
  close(Math.hypot((outline[0][0]-outline[3][0])*xScale,(outline[0][1]-outline[3][1])*metres),
    body.Visual_Body_Width_Meters,'outline uses the real body width');
  const bodyDx=(bodyPath[1][0]-bodyPath[0][0])*xScale,bodyDy=(bodyPath[1][1]-bodyPath[0][1])*metres;
  const ringDx=(outline[1][0]-outline[0][0])*xScale,ringDy=(outline[1][1]-outline[0][1])*metres;
  close(ringDx,bodyDx,'outline longitudinal direction x');close(ringDy,bodyDy,'outline longitudinal direction y');
  if(mode==='pinned') {
    assert.equal(h.api.getState().selectedVehicleId,vehicle);
    assert.equal(h.api.getState().selectedPersonId,body.Agent_ID);
    assert.equal(h.api.getState().vehicleCard.vehicleId,vehicle,'existing contextual card shares identity');
    assert.deepEqual(Object.keys(h.api.getState().vehicleCard.fields).sort(),
      ['currentSpeed','elapsed','estimatedDuration','maximumSpeed','name','type'],'six-field card contract is preserved');
  }
  assert.ok(rows.length<=2,'only pinned + hovered bodies can be highlighted');return row;
}
function assertEmpty(h) {
  assert.equal(highlights(h).length,0);assert.equal(layer(h,'vehicle-focus-halo').props.data.length,0);
  assert.equal(h.api.getState().selectedVehicleId,null);assert.equal(h.api.getState().selectedPersonId,null);
}
async function replyJourney(h,vehicle,fixture=records,tripTable=trips) {
  const selected=fixture.find(row=>row.vehicle===vehicle),request=requests(h).findLast(row=>!row.replied);
  assert.ok(request);request.replied=true;request.resolve({ok:true,status:200,json:async()=>({
    ...h.identity,key:selected.Replay_Journey_Key,records:fixture.filter(row=>row.vehicle===vehicle).map(row=>
      ({...structuredClone(row),Trip:structuredClone(tripTable[row.Replay_Journey_Key])}))})});
  await flush();
}
async function ready() {
  const h=harness({},structuredClone(laneConfig));h.reply(0,structuredClone(payload));await flush();
  h.api.pause();h.api.seek(110);viewport(h);h.evaluate('refreshMapLabels()');return h;
}

(async()=>{
  const original=JSON.stringify(payload),h=await ready();assertEmpty(h);
  const a=marker(h,'vehicle-a'),b=marker(h,'vehicle-b');
  assert.equal(layer(h,'trips').props.data.length,2);
  assert.equal(a.Visual_Lane_Source,'native');assert.equal(b.Visual_Lane_Source,'native');
  assert.equal(a.Visual_Lane_Index,0);assert.equal(b.Visual_Lane_Index,1);
  close(a.position[0],b.position[0],'two parallel vehicles at the same longitudinal station',1e-12);
  close(Math.abs(a.position[1]-b.position[1])*metres,3,'one lane width between distinct bodies');
  assert.notDeepEqual(plain(a.color),plain(b.color),'two independent original speed colors');
  const originalMarkers=JSON.stringify(layer(h,'trips').props.data),tripLayer=layer(h,'trips'),tripData=tripLayer.props.data;
  const staticLayers=new Map(h.api.layers.filter(row=>!['trips','vehicle-focus-halo','vehicle-focus-outline',
    'selected-history','selected-future','selected-origin','selected-destination'].includes(row.id)).map(row=>[row.id,row]));
  const creates=h.api.getRenderPerformance().counters.markerCreates;
  pointer(h,'hover','vehicle-a',b);const hover=assertFocus(h,'vehicle-a','hover');
  assert.equal(h.api.getState().selectedVehicleId,null,'hover never pins');
  const afterHover=h.api.layers,afterHoverUpdates=h.sandbox.deckInstance.updates;
  for(let i=0;i<20;i++)pointer(h,'hover','vehicle-a',b);
  assert.equal(h.api.layers,afterHover,'repeated hover on same body reuses layers');
  assert.equal(h.sandbox.deckInstance.updates,afterHoverUpdates,'unchanged hover never resubmits layers');
  assert.equal(requests(h).length,0,'hover performs no journey query');
  pointer(h,'click','vehicle-a',b);let pin=assertFocus(h,'vehicle-a');
  assert.notDeepEqual(plain(pin.color),plain(hover.color),'pinned and temporary colors differ');
  assert.equal(highlights(h).length,1,'hover over pinned car does not duplicate its contour');
  const requestCount=requests(h).length;
  for(let i=0;i<10;i++)pointer(h,'click','vehicle-a',b);
  assert.equal(requests(h).length,requestCount,'repeated clicks do not requery SQLite');
  pointer(h,'hover','vehicle-b',a);assertFocus(h,'vehicle-a');assertFocus(h,'vehicle-b','hover');
  assert.equal(highlights(h).length,2,'neighbor can be hovered without changing pinned vehicle');
  h.canvas.onpointerleave();assertFocus(h,'vehicle-a');assert.equal(highlights(h).length,1);
  pointer(h,'click','vehicle-b',a);assertFocus(h,'vehicle-b');
  assert.equal(highlights(h).length,1);assert.equal(highlights(h).some(row=>row.marker.vehicle==='vehicle-a'),false,
    'click on the adjacent body removes previous highlight despite the overlapping picking aperture');
  assert.equal(layer(h,'trips'),tripLayer);assert.equal(layer(h,'trips').props.data,tripData);
  assert.equal(JSON.stringify(tripData),originalMarkers,'selection preserves body, lane, speed color and source motion');
  assert.equal(h.api.getRenderPerformance().counters.markerCreates,creates,'hover/click never recalculate all markers');
  for(const [id,before] of staticLayers)assert.equal(layer(h,id),before,`${id} is not rebuilt for selection`);
  await replyJourney(h,'vehicle-b');assertFocus(h,'vehicle-b');
  assert.ok(layer(h,'selected-history').props.data.length,'full journey can coexist with body highlight');
  assert.ok(layer(h,'selected-future').props.data.length);
  assert.notEqual(marker(h,'vehicle-b').position[1],path[0][1],'selected body stays on native visual lane, off route axis');
  assert.deepEqual(plain(marker(h,'vehicle-b').color),[255,255,255],'stopped vehicle keeps white speed color');
  const stoppedOutline=JSON.stringify(assertFocus(h,'vehicle-b').outline),stoppedRequests=requests(h).length;
  h.api.setSpeed(1);h.api.play();h.frame(1000);h.frame(2000);h.api.pause();
  assert.equal(JSON.stringify(assertFocus(h,'vehicle-b').outline),stoppedOutline,'highlight stays attached during recorded stop');
  assert.equal(requests(h).length,stoppedRequests,'playback does not poll journey endpoint');
  h.api.seek(120);h.reply(1,structuredClone(payload));await flush();
  assertFocus(h,'vehicle-b');assert.equal(h.api.getState().current,120);
  h.api.seek(124);assertFocus(h,'vehicle-b');
  h.api.seek(110);assert.equal(JSON.stringify(assertFocus(h,'vehicle-b').outline),stoppedOutline,'reverse seek restores exact earlier body pose');
  const camera=h.sandbox.deckInstance.props,requestsBeforeCamera=h.requests.length;
  viewport(h,73);camera.onViewStateChange({viewState:{...camera.viewState,bearing:73,pitch:55}});
  assertFocus(h,'vehicle-b');assert.equal(h.requests.length,requestsBeforeCamera,'camera changes need no data query');
  pointer(h,'click','vehicle-a',marker(h,'vehicle-b'));assertFocus(h,'vehicle-a');
  h.evaluate('vehicleCardClose.onclick()');assertEmpty(h);
  h.api.setSpeed(1);h.api.play();const beforeClose=h.api.getState().current;h.frame(3000);
  assert.ok(h.api.getState().current>beforeClose,'closing selection does not stop animation');assertEmpty(h);h.api.pause();
  assert.equal(JSON.stringify(payload),original,'fixture native geometry, timings and Motion_Plan are immutable');
  const sourceRows=h.evaluate('JSON.stringify([...timelines.values()].flat().map(({vehicle,path,timestamps,Motion_Plan})=>({vehicle,path,timestamps,Motion_Plan})))');
  assert.equal(sourceRows,JSON.stringify(records.map(({vehicle,path,timestamps,Motion_Plan})=>({vehicle,path,timestamps,Motion_Plan}))),
    'hydrated source motion and geometry remain unchanged through interaction and window replacement');
  console.log('PASS: parallel native lanes, exact vehicle/person identity, speed colors, hover/pin/click replacement, stop, windows, reverse seek, camera, card close and bounded selection work');

  // A pinned snapshot cannot transfer its contour to a replacement body sharing
  // a journey/person, or a different person attached to the same vehicle ID.
  const identity=await ready();pointer(identity,'click','vehicle-a');assertFocus(identity,'vehicle-a');
  identity.evaluate('(()=>{const row=visibilityRecords.get("vehicle-a");visibilityRecords.set("vehicle-a",{...row,marker:{...row.marker,vehicle:"vehicle-other"}});refreshVehicleHighlights();})()');
  assert.equal(highlights(identity).length,0,'same trip/person does not authorize another vehicle body');
  identity.evaluate('(()=>{const body=layers.find(row=>row.id==="trips").props.data.find(row=>row.vehicle==="vehicle-a");visibilityRecords.set("vehicle-a",{visible:true,marker:{...body,Agent_ID:"person-other"}});refreshVehicleHighlights();})()');
  assert.equal(highlights(identity).length,0,'same vehicle/trip does not authorize another person body');
  identity.api.clearSelection();assertEmpty(identity);
  console.log('PASS: no highlight can transfer to another vehicle/person sharing a journey identity');

  const paths={incoming:[xy(0,0),xy(10,0)],short:[xy(10,0),xy(10,.2)],outgoing:[xy(10,.2),xy(10,10)]};
  const ids=Object.keys(paths),times=[[110,120],[120,121],[121,130]],distances=[10,.2,9.8];
  const turnConfig={schema_version:1,available:true,links:Object.fromEntries(ids.map((id,i)=>[id,{
    path:paths[id],num_lanes:1,source_way:id,from_node:'n'+i,to_node:'n'+(i+1),osm_tags:{},native_lanes:{},
    movement_source:'effective_car_node_adjacency',allowed_to_links:ids.slice(i+1,i+2)}]))};
  const turnRecords=ids.map((id,i)=>({vehicle:'vehicle-turn',Agent_ID:'person-turn',Replay_Journey_Key:keyA,Link_ID:id,
    path:paths[id],timestamps:times[i],Motion_Plan:{version:1,status:'constant',distance_m:distances[i],
      phases:[[...times[i],0,distances[i]/(times[i][1]-times[i][0]),0]]}}));
  const turnTrips={[keyA]:{Trip_ID:'turn-trip',Departure:110,Arrival:130,Status:'completed'}};
  const turn=harness({},turnConfig);viewport(turn);
  turn.reply(0,{segments:turnRecords.slice(0,1),context_segments:turnRecords.slice(1,2),trips:turnTrips});await flush();
  turn.api.pause();turn.api.seek(119.5);pointer(turn,'click','vehicle-turn');const beforeTurn=plain(assertFocus(turn,'vehicle-turn').outline);
  turn.api.seek(120);assertFocus(turn,'vehicle-turn');
  assert.equal(turn.api.getState().current,119.5,'buffering retains last displayed selection/body pair');
  turn.reply(1,{segments:turnRecords.slice(1),context_segments:turnRecords.slice(0,1),trips:turnTrips});await flush();
  assertFocus(turn,'vehicle-turn');assert.equal(marker(turn,'vehicle-turn').Link_ID,'short');
  turn.api.seek(120.25);const turning=assertFocus(turn,'vehicle-turn'),turningHeading=turning.marker.Visual_Body_Heading_Degrees;
  assert.ok(turningHeading>0 && turningHeading<90,`fixture actually exercises a rotated rigid body in the intersection: ${turningHeading}`);
  assert.notDeepEqual(plain(turning.outline),beforeTurn,'body highlight follows the actual changing turn pose');
  const pausedOutline=turning.outline;turn.frame(1000);turn.frame(2000);
  assert.equal(assertFocus(turn,'vehicle-turn').outline,pausedOutline,'paused frames retain exact contour object');
  turn.api.seek(119.5);assert.deepEqual(plain(assertFocus(turn,'vehicle-turn').outline),beforeTurn,'reverse seek across window restores orientation');
  turn.api.setSpeed(1);turn.api.play();turn.frame(3000);turn.api.pause();
  assert.equal(turn.api.getState().current,120.5);assertFocus(turn,'vehicle-turn');
  turn.api.seek(130);assert.equal(highlights(turn).length,0,'selected trip remains identified but absent body is never highlighted');
  assert.equal(turn.api.getState().selectedVehicleId,'vehicle-turn');
  turn.api.seek(119.5);assertFocus(turn,'vehicle-turn');turn.api.clearSelection();assertEmpty(turn);
  console.log('PASS: real rigid turn, buffered window boundary, pause/play, reverse seek and absent body retain selected identity without route-axis artifacts');
})().catch(error=>{console.error(error);process.exitCode=1;});
