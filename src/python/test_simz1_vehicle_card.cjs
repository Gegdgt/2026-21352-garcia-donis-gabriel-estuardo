// Vehicle-card regressions run in the existing deterministic VM harness.
// No browser, server, SQLite, protected run, or replay regeneration is involved.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const keyA='a'.repeat(64),keyB='c'.repeat(64);
const fieldKeys=['currentSpeed','elapsed','estimatedDuration','maximumSpeed','name','type'];
const tripA={Trip_ID:'person-real-001:trip:0001',Person_ID:'person-real-001',Departure:25200,
  Arrival:32400,Status:'completed',Origin_Position:[0,0],Destination_Position:[.01,0]};
const tripB={Trip_ID:'person-real-002:trip:0001',Person_ID:'person-real-002',Departure:25200,
  Arrival:30000,Status:'completed',Origin_Position:[0,0],Destination_Position:[.01,.01]};
const recordA={vehicle:'vehicle-real-001',Agent_ID:'person-real-001',Link_ID:'main-link',
  Replay_Journey_Key:keyA,Trip:tripA,Profile:'Normal',path:[[0,0],[.01,0]],timestamps:[25200,32400],
  Speed_kmh:33,Max_Speed_kmh:95,Free_Speed_kmh:30,
  Motion_Provenance:{vehicle_limit_mps:50/3.6},
  Motion_Plan:{version:1,status:'kinematic',distance_m:66000,cap_mps:10,
    phases:[[25200,25800,0,10,0],[25800,26400,6000,0,0],[26400,32400,6000,10,0]]}};
const recordB={vehicle:'vehicle-real-002',Agent_ID:'person-real-002',Link_ID:'second-link',
  Replay_Journey_Key:keyB,Trip:tripB,Profile:'Normal',Agent_Type:'Motociclista',Agent_Schema:'simz1-six-v1',
  Vehicle_Type:'Motociclista',Vehicle_PCU:.25,path:[[0,0],[.01,.01]],timestamps:[25200,30000],
  Motion_Provenance:{vehicle_limit_mps:60/3.6},
  Motion_Plan:{version:1,status:'constant',distance_m:24000,cap_mps:5,phases:[[25200,30000,0,5,0]]}};
const fixture=[recordA,recordB];

function card(h){return h.api.getState().vehicleCard;}
function marker(h,vehicle=recordA.vehicle){return h.api.layers.find(layer=>layer.id==='trips').props.data.find(row=>row.vehicle===vehicle);}
function hover(h,object,x=100,y=100){h.sandbox.deckInstance.props.onHover({object,x,y},{pointerType:'mouse'});}
function click(h,object){
  h.listeners.pointerdown({target:h.canvas,pointerType:'mouse'});
  h.sandbox.deckInstance.props.onClick({object},{type:'click',tapCount:1});
}
function journeyRequests(h){return h.requests.filter(request=>request.url.startsWith('/api/journey'));}
function replyJourney(h,request,record){
  request.replied=true;
  request.resolve({ok:true,status:200,json:async()=>({...h.identity,key:record.Replay_Journey_Key,
    records:[structuredClone(record)]})});
}
function replyWindow(h,index){
  const start=index*3600,end=start+3600;
  h.reply(index,{segments:fixture.filter(row=>row.timestamps[0]<end && row.timestamps[1]>start).map(row=>structuredClone(row)),
    trips:{[keyA]:structuredClone(tripA),[keyB]:structuredClone(tripB)}});
}
async function seek(h,time){
  h.api.seek(time);
  const index=Math.floor(time/3600);
  if(h.request(index))replyWindow(h,index);
  await flush();
  assert.equal(h.api.getState().current,time,'seek uses requested simulated time');
}
async function ready(time=25260){
  const h=harness({end_seconds:86400,window_seconds:3600,window_count:24,
    source_time_horizon:{start_seconds:0,end_seconds:86400},metrics_window:{start_seconds:0,end_seconds:86400}});
  h.api.pause();replyWindow(h,0);await flush();await seek(h,time);return h;
}
function hidden(h,message){
  assert.equal(card(h).visible,false,message);
  assert.equal(h.evaluate('vehicleCard.hidden'),true,'[hidden] completely hides card');
}
function fields(h){
  const value=card(h).fields;
  assert.deepEqual(Object.keys(value).sort(),fieldKeys,'exactly the requested six fields');
  return value;
}
function computed(h,object,time=25260){
  h.sandbox.cardFixture=structuredClone(object);
  return h.evaluate(`buildVehicleCardFields(cardFixture,${time})`);
}

(async()=>{
  const h=await ready();
  hidden(h,'no permanent empty card before hover or selection');
  assert.equal(h.evaluate('vehicleCard.id'),'simz1-vehicle-card');
  assert.equal(h.evaluate('vehicleCardClose.id'),'simz1-vehicle-card-close');
  const cardRows=h.evaluate('vehicleCard.children.find(node=>node.tagName==="DL")');
  assert.ok(cardRows,'the compact card has one field list');
  assert.equal(cardRows.children.filter(node=>node.tagName==='DT').length,6,'exactly six visible field labels');
  assert.equal(cardRows.children.filter(node=>node.tagName==='DD').length,6,'exactly six visible field values');
  const beforeRequests=h.requests.length,beforeDeckUpdates=h.sandbox.deckInstance.updates;
  const beforeLayers=h.api.layers;
  hover(h,marker(h));
  assert.equal(card(h).visible,true);assert.equal(card(h).pinned,false);
  assert.equal(card(h).personId,recordA.Agent_ID);assert.equal(card(h).vehicleId,recordA.vehicle);
  assert.equal(fields(h).name,'Vehículo '+recordA.vehicle,'vehicle identity takes presentation precedence; person ID remains in API');
  assert.equal(fields(h).type,'Carro','historical profile receives a presentation label only');
  assert.match(fields(h).currentSpeed,/^36(?:\.0)? km\/h$/);
  assert.match(fields(h).maximumSpeed,/^50(?:\.0)? km\/h$/,'vehicle limit is neither road limit, plan cap nor observed maximum');
  assert.equal(fields(h).estimatedDuration,'—','future recorded arrival is not a prediction');
  for(let index=0;index<50;index++)hover(h,marker(h),100+index,100);
  assert.equal(h.requests.length,beforeRequests,'cursor movement never queries journey or window endpoints');
  assert.equal(h.sandbox.deckInstance.updates,beforeDeckUpdates,'hover updates DOM without rebuilding/submitting layers');
  assert.equal(h.api.layers,beforeLayers,'hover retains the existing layer array');
  assert.equal(h.evaluate('vehicleCard.children.find(node=>node.tagName==="DL")'),cardRows,
    'card rows are retained rather than rebuilt for cursor movement');
  h.sandbox.window.innerWidth=420;h.sandbox.window.innerHeight=260;
  h.evaluate('vehicleCard.offsetWidth=220;vehicleCard.offsetHeight=180');
  hover(h,marker(h),415,255);
  const placement=h.evaluate('({left:parseFloat(vehicleCard.style.left),top:parseFloat(vehicleCard.style.top)})');
  assert.ok(placement.left>=8 && placement.left+220<=412,'hover card stays inside horizontal viewport');
  assert.ok(placement.top>=8 && placement.top+180<=252,'hover card stays inside vertical viewport');
  hover(h,null);hidden(h,'leaving vehicle hides ephemeral card');
  hover(h,marker(h));h.canvas.onpointerleave();hidden(h,'leaving the canvas hides ephemeral card');
  console.log('PASS: hover/leave, six fields, real identity, historical type, current/maximum separation and no hover fetch/layer churn');

  const tracking=await ready(26100);
  const viewport={width:1000,height:800,project:position=>[100+position[0]*100000,100+position[1]*100000]};
  tracking.sandbox.deckInstance.getViewports=()=>[viewport];
  tracking.canvas.getBoundingClientRect=()=>({left:35,top:50,right:1035,bottom:850,width:1000,height:800});
  const stoppedMarker=marker(tracking),pixel=viewport.project(stoppedMarker.position);
  hover(tracking,stoppedMarker,...pixel);
  assert.equal(card(tracking).visible,true);assert.equal(fields(tracking).currentSpeed,'0 km/h');
  tracking.evaluate('render();render()');assert.equal(card(tracking).visible,true,'paused renders preserve hover on stationary vehicle');
  tracking.sandbox.trackingVehicle=recordA.vehicle;
  tracking.evaluate('const savedTrackingVisibility=visibilityRecords.get(trackingVehicle)');
  tracking.evaluate('visibilityRecords.set(trackingVehicle,{visible:false,reason:"fixture_omitted"});checkVehicleHover();updateVehicleCard()');
  hidden(tracking,'hover clears when the current marker becomes unrepresentable');
  tracking.evaluate('visibilityRecords.set(trackingVehicle,savedTrackingVisibility)');hover(tracking,stoppedMarker,...pixel);
  tracking.evaluate('(()=>{const key=tripKey(hovered),rows=recordsByTrip.get(key);recordsByTrip.set(key,rows.map(row=>({...row,vehicle:"handoff-other"})));checkVehicleHover();updateVehicleCard();recordsByTrip.set(key,rows);})()');
  hidden(tracking,'hover cannot follow another vehicle solely because its person/trip matches');
  hover(tracking,stoppedMarker,...pixel);
  tracking.api.setSpeed(1);tracking.api.play();tracking.frame(60000);
  assert.equal(card(tracking).visible,true,'recorded stop remains beneath unmoved pointer during playback');
  tracking.frame(360000);tracking.api.pause();
  hidden(tracking,'hover clears when moving vehicle leaves existing picking radius without cursor movement');
  assert.equal(journeyRequests(tracking).length,0,'following hover never fetches full journeys');
  const technicalUpdates=tracking.sandbox.deckInstance.updates,technicalRequests=tracking.requests.length;
  hover(tracking,{system_id:'signal',group_id:'group',Link_ID:'signal-link'},200,200);
  assert.match(tracking.evaluate('info.textContent'),/Semaforo: signal/,'paused signal hover updates diagnostic text');
  assert.match(tracking.evaluate('info.textContent'),/RED/,'signal state comes from existing replay');
  hidden(tracking,'a signal does not masquerade as a six-field vehicle card');
  assert.equal(tracking.sandbox.deckInstance.updates,technicalUpdates,'signal hover updates only DOM');
  assert.equal(tracking.requests.length,technicalRequests,'signal hover does not request SQLite-backed endpoints');
  hover(tracking,null);assert.equal(tracking.evaluate('info.style.display'),'none','signal leave clears diagnostic text');
  console.log('PASS: hover persists on a stop, leaves with moving vehicle, and paused signal inspection updates only DOM');

  hover(h,marker(h));click(h,marker(h));
  assert.equal(card(h).pinned,true);assert.equal(card(h).visible,true);
  const firstRequest=journeyRequests(h)[0];assert.ok(firstRequest,'one complete-journey request on selection');
  const pinnedBeforeStop=JSON.stringify(card(h));
  click(h,{transit_stop:true,stop_id:'synthetic-only'});
  assert.equal(JSON.stringify(card(h)),pinnedBeforeStop,'stop inspection preserves all six fields of the pinned vehicle');
  assert.equal(journeyRequests(h).length,1,'stop click neither replaces nor reloads selected journey');
  click(h,marker(h));assert.equal(journeyRequests(h).length,1,'repeated same-agent click shares pending journey request');
  hover(h,marker(h,recordB.vehicle));
  assert.equal(card(h).personId,recordA.Agent_ID,'pinned agent takes priority over another hover');
  hover(h,null);assert.equal(card(h).visible,true,'leaving cursor preserves pin');
  h.canvas.onpointerleave();assert.equal(card(h).visible,true,'leaving canvas preserves pin');
  click(h,marker(h,recordB.vehicle));
  assert.equal(card(h).personId,recordB.Agent_ID);assert.equal(fields(h).type,'Moto');
  assert.equal(fields(h).name,'Vehículo '+recordB.vehicle,'selection immediately replaces the previous vehicle name');
  assert.equal(firstRequest.options.signal.aborted,true,'changing selection cancels older request');
  const secondRequest=journeyRequests(h)[1];assert.ok(secondRequest);
  replyJourney(h,secondRequest,recordB);await flush();
  click(h,marker(h,recordB.vehicle));assert.equal(journeyRequests(h).length,2,
    'repeated same-agent click reuses loaded journey');
  const secondIdentity=h.api.getState().selectedKey;
  replyJourney(h,firstRequest,recordA);await flush();
  assert.equal(card(h).personId,recordB.Agent_ID,'late older response cannot replace selected identity');
  assert.equal(fields(h).name,'Vehículo '+recordB.vehicle,'late older response cannot restore the previous vehicle name');
  assert.equal(h.api.getState().selectedKey,secondIdentity);
  h.listeners.pointerdown({target:h.evaluate('vehicleCardClose'),pointerType:'mouse'});
  assert.equal(card(h).visible,true,'pointerdown inside card does not clear selection before its control runs');
  h.evaluate('vehicleCardClose.onclick()');hidden(h,'X closes pin and hover');
  assert.equal(h.api.getState().selectedKey,null);
  click(h,marker(h));h.listeners.keydown({key:'Escape'});hidden(h,'Escape closes pin');
  click(h,marker(h));click(h,null);hidden(h,'background click closes pin');
  assert.equal(h.evaluate('runPanel.children.map(node=>node.textContent).join("")'),'Vehículos particulares: 179235 · Transporte público: — · Camiones: —',
    'independent population count survives all selection interactions');
  console.log('PASS: pin priority, changing agent, stale asynchronous response, X/Escape/background and independent population count');

  // Explicit categories can be shown; numeric IDs, speeds, and target shares
  // must never manufacture a missing category or relabel a historical profile.
  const pure=await ready();
  for(const [value,label] of [['Normal','Carro'],['Motociclista','Moto'],['Liebre','Carro liebre'],['Tortuga','Carro Tortuga'],
    ['TransportePublico','Transporte público'],['TransportePesado','Camión']]) {
    assert.equal(computed(pure,{...recordA,Agent_Type:value,Agent_Schema:'simz1-six-v1'}).type,label);
  }
  for(const [profile,label] of [['Normal','Carro'],['Liebre','Carro liebre'],['Tortuga','Carro Tortuga']])
    assert.equal(computed(pure,{...recordA,Profile:profile}).type,label,'label does not rename recorded profile');
  const unknown={...recordA,Profile:undefined,Agent_Type:undefined,Vehicle_Type:undefined};
  assert.equal(computed(pure,unknown).type,'No registrado');
  assert.equal(computed(pure,{...unknown,vehicle:'moto-25',Agent_ID:'bus-10',Speed_kmh:90}).type,'No registrado');
  assert.equal(computed(pure,{...unknown,Profile:'Motociclista'}).type,'No registrado','new categories need effective metadata');
  assert.equal(computed(pure,{...unknown,Vehicle_Type:'Tortuga'}).type,'Carro Tortuga');
  assert.notEqual(recordA.vehicle,tripA.Person_ID,'fixture keeps vehicle and person identities distinct');
  assert.equal(computed(pure,{...recordA,vehicle:undefined}).name,'Vehículo '+recordA.Agent_ID,
    'recorded Agent_ID supplies the historical name when vehicle identity is unavailable');
  assert.equal(computed(pure,{...recordA,vehicle:undefined,Agent_ID:undefined}).name,'Vehículo '+tripA.Person_ID,
    'trip person identity supplies the historical name when vehicle and Agent_ID are unavailable');
  assert.equal(computed(pure,{...recordA,Agent_ID:undefined}).name,'Vehículo '+recordA.vehicle,
    'vehicle identity takes precedence over a distinct trip person identity');
  assert.equal(computed(pure,{...unknown,Agent_ID:undefined,Trip:{...tripA,Person_ID:undefined}}).name,'Vehículo '+recordA.vehicle,
    'vehicle identity supplies the name when no person identity is available');
  assert.equal(computed(pure,{...unknown,vehicle:undefined,Agent_ID:undefined,Trip:{...tripA,Person_ID:undefined}}).name,'Vehículo —',
    'missing identity stays unavailable without altering stored person/vehicle keys');
  assert.equal(computed(pure,{...unknown,vehicle:null,Agent_ID:null,Trip:null}).name,'Vehículo —',
    'null identities and missing trip remain explicitly unavailable');
  assert.equal(computed(pure,{...recordA,Motion_Provenance:undefined}).maximumSpeed,'—','observed Max_Speed_kmh is not a vehicle maximum');
  const unsupported={...recordA,Motion_Plan:{version:1,status:'unavailable',fallback_reason:'fixture has no movement evidence'}};
  assert.equal(computed(pure,unsupported).currentSpeed,'—','missing motion is not stationary');
  const geometryOnly={...recordA,Motion_Plan:undefined,Motion_Provenance:undefined,
    Motion_Speed_kmh:undefined,Speed_kmh:undefined,path:[[0,0],[0,0]]};
  assert.equal(computed(pure,geometryOnly).currentSpeed,'—','fixed visual geometry alone is not evidence of a registered stop');
  assert.equal(computed(pure,{...recordA,Trip:{...tripA,Departure:undefined}}).elapsed,'—',
    'segment/window start is not substituted for a missing registered departure');
  assert.equal(computed(pure,recordA,26100).currentSpeed,'0 km/h','registered zero-speed phase is stationary');
  const crawlSpeed=.02/3.6;
  const crawling={...recordA,Motion_Plan:{version:1,status:'constant',distance_m:crawlSpeed*7200,
    cap_mps:crawlSpeed,phases:[[25200,32400,0,crawlSpeed,0]]}};
  assert.equal(computed(pure,crawling).currentSpeed,'<0.1 km/h','positive crawl speed must not round into a false stop');
  assert.equal(computed(pure,recordA,26100).elapsed,'15 min simulados');
  assert.equal(computed(pure,recordA,30000).elapsed,'1 h 20 min simulados');
  assert.equal(computed(pure,{...recordA,Trip:{...tripA,Arrival:28800}}).estimatedDuration,'—');
  assert.equal(computed(pure,{...recordA,Trip:{...tripA,Arrival:null}}).estimatedDuration,'—');
  const censored={...recordA,Trip:{...tripA,Arrival:null,Status:'censored',Last_Observed_Time:26100,
    Observation_End:26400,Observation_End_Provenance:'configured_horizon'}};
  assert.equal(computed(pure,censored,25800).elapsed,'10 min simulados');
  assert.equal(computed(pure,censored,27000).elapsed,'15 min simulados',
    'censored elapsed cannot extend beyond the last individual observation');
  assert.equal(computed(pure,{...censored,Trip:{...censored.Trip,Last_Observed_Time:27000}},28000).elapsed,'20 min simulados',
    'configured observation horizon caps elapsed before later cleanup events');
  const legacyCensored={...recordA,timestamps:[25200,26100],Trip:{...tripA,Arrival:null,Status:'censored'}};
  assert.equal(computed(pure,legacyCensored,27000).elapsed,'15 min simulados',
    'legacy censored journey without end metadata stops elapsed at its last known segment end');
  pure.sandbox.cardFixture=structuredClone(recordA);
  pure.sandbox.cardHandoffState={trip:structuredClone(tripA),active:structuredClone(recordB),
    records:[structuredClone(recordA),structuredClone(recordB)],visible:true,reason:'measured_segment'};
  const handoff=pure.evaluate('buildVehicleCardFields(cardFixture,25260,cardHandoffState)');
  assert.equal(handoff.currentSpeed,'—','another vehicle in the same person journey cannot supply selected vehicle speed');
  assert.equal(handoff.type,'Carro');assert.equal(handoff.maximumSpeed,'50 km/h',
    'selected vehicle keeps its own type and maximum during another vehicle segment');
  console.log('PASS: six backed types, unknown historical type, no inferred category, unknown motion/maximum/estimate and recorded wait 0');

  const identity=await ready();click(identity,marker(identity));
  replyJourney(identity,journeyRequests(identity)[0],{...recordA,vehicle:'a-different-vehicle'});await flush();
  assert.equal(card(identity).vehicleId,recordA.vehicle);
  assert.equal(identity.api.getState().selectedJourneyStatus,'unavailable',
    'same person/trip with another vehicle is not accepted as this selected vehicle');
  assert.equal(identity.api.getState().selectedRecords,0,'invalid vehicle payload is not installed into selection');
  console.log('PASS: journey response must preserve selected vehicle as well as run/person/trip identity');

  const clock=await ready(25200);
  click(clock,marker(clock));replyJourney(clock,journeyRequests(clock)[0],recordA);await flush();
  clock.api.setSpeed(1);clock.api.play();clock.frame(900000);clock.api.pause();
  assert.equal(clock.api.getState().current,26100);assert.equal(fields(clock).elapsed,'15 min simulados');
  assert.equal(fields(clock).currentSpeed,'0 km/h');
  const pausedFields=JSON.stringify(fields(clock)),pausedIdentity=clock.api.getState().selectedKey;
  clock.frame(906000);assert.equal(JSON.stringify(fields(clock)),pausedFields,'pause freezes simulated telemetry');
  await seek(clock,25200);clock.api.setSpeed(120);clock.api.play();clock.frame(913500);clock.api.pause();
  assert.equal(clock.api.getState().current,26100);assert.equal(fields(clock).elapsed,'15 min simulados','120x changes wall-time rate only');
  assert.equal(clock.api.getState().selectedKey,pausedIdentity);
  const beforeBuffer=JSON.stringify(fields(clock)),beforeBufferTime=clock.api.getState().current;
  clock.api.seek(30000);
  assert.equal(clock.api.getState().buffering,true);assert.equal(card(clock).visible,true);assert.equal(card(clock).pinned,true);
  assert.equal(card(clock).personId,recordA.Agent_ID);assert.equal(JSON.stringify(fields(clock)),beforeBuffer,
    'buffering retains telemetry for last validated simulation time');
  clock.frame(999000);assert.equal(clock.api.getState().current,beforeBufferTime,'buffering cannot advance simulated elapsed time');
  replyWindow(clock,8);await flush();
  assert.equal(fields(clock).elapsed,'1 h 20 min simulados');assert.equal(card(clock).personId,recordA.Agent_ID);
  assert.equal(journeyRequests(clock).length,1,'window switch and seek reuse selected full journey');
  await seek(clock,25260);assert.match(fields(clock).currentSpeed,/^36(?:\.0)? km\/h$/);
  assert.equal(card(clock).personId,recordA.Agent_ID,'reverse seek preserves selection');
  const pinnedPlacement=JSON.stringify(clock.evaluate('vehicleCard.style'));
  const props=clock.sandbox.deckInstance.props;
  props.onViewStateChange({viewState:{...props.viewState,zoom:16,bearing:45,pitch:55}});
  assert.equal(JSON.stringify(clock.evaluate('vehicleCard.style')),pinnedPlacement,'pinned placement stays stable through zoom/rotation');
  assert.equal(clock.api.getState().selectedKey,pausedIdentity);
  await seek(clock,32400);
  assert.equal(card(clock).visible,true,'arrived agent remains pinned for inspection');
  assert.equal(fields(clock).elapsed,'2 h simulados','elapsed caps at observed arrival once reached');
  assert.equal(fields(clock).currentSpeed,'—','no active segment at arrival is not invented movement or stopped speed');
  assert.equal(fields(clock).estimatedDuration,'—','completion does not turn actual duration into a prediction');
  await seek(clock,33000);assert.equal(fields(clock).elapsed,'2 h simulados');
  await seek(clock,25100);assert.equal(card(clock).personId,recordA.Agent_ID,'seek before departure preserves identity');
  assert.equal(fields(clock).currentSpeed,'—');
  clock.api.clearSelection();hidden(clock,'cleared card remains entirely hidden');
  console.log('PASS: 1x/120x simulation clock, pause, seek/window/buffering, camera stability, exact arrival and no retrospective prediction');

  const shell=fs.readFileSync('python/visualizador_z1_continuous.html','utf8');
  assert.match(shell,/#simz1-vehicle-card[^}]*\{[^}]*background/i,'dark compact card has explicit style');
  assert.match(shell,/#simz1-vehicle-card\[hidden\][^}]*\{[^}]*display\s*:\s*none/i,
    'hidden attribute wins over card layout styles');
  console.log('PASS: hidden CSS keeps an unselected card out of the map');
})().catch(error=>{console.error(error);process.exitCode=1;});
