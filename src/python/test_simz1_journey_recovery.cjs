// Controlled frontend requests and native-shaped records; no QSim or WebGL.
'use strict';
const assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const {fixture}=require('./test_simz1_transit_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function pending(h){return h.requests.find(r=>!r.replied && r.url.startsWith('/api/journey'));}
function answer(h,status=200,payload={},retryAfter='2') {
  const r=pending(h);assert.ok(r,'journey request exists');r.replied=true;
  r.resolve({ok:status===200,status,headers:{get:name=>name==='Retry-After' ? retryAfter : null},
    text:async()=>JSON.stringify(payload),json:async()=>payload});return r;
}
async function setup() {
  const a=fixture(),b=fixture('back',30,50,true),h=harness({}, {schema_version:1,links:{
    road:{path:a.path,num_lanes:1,length_m:111,native_lanes:{},from_node:'a',to_node:'b'},
    scheduled:{path:[[.001,0],[.002,0]],num_lanes:1,length_m:111,native_lanes:{},from_node:'b',to_node:'c'}}});
  a.Trip.Transit.route_links.push('scheduled');
  h.api.pause();h.reply(0,{segments:[a,b],trips:{[a.Replay_Journey_Key]:a.Trip,[b.Replay_Journey_Key]:b.Trip}});await flush();
  h.api.seek(6);h.api.selectActive();return {h,a,b};
}
async function recovery() {
  const {h,a,b}=await setup(),payload={...h.identity,key:a.Replay_Journey_Key,records:[a]};
  answer(h,503,{...h.identity,retryable:true,error:'Servidor ocupado'});await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,'retrying');
  assert.equal(await h.retryTimer(),2000,'Retry-After minimum');
  answer(h,200,payload);await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,'complete');
  assert.equal(h.api.getPerformance().selectionRequests.retries503,1);
  const firstUrl=h.requests.find(r=>r.url.startsWith('/api/journey')).url;
  assert.equal(new URL(firstUrl,'http://localhost').searchParams.get('run_id'),h.identity.run_id);
  assert.equal(new URL(firstUrl,'http://localhost').searchParams.get('key'),a.Replay_Journey_Key);
  h.api.clearSelection();h.api.selectActive();
  for(let n=0;n<5;n++) {
    answer(h,503,{...h.identity,retryable:true});await flush();
    assert.equal(h.api.getState().selectedJourneyStatus,'retrying');
    assert.equal(await h.retryTimer(),Math.max(2000,Math.min(10000,1000*2**n)));
  }
  const obsolete=pending(h);h.api.seek(35);h.api.selectActive();
  assert.equal(obsolete.options.signal.aborted,true);
  obsolete.replied=true;obsolete.resolve({ok:true,json:async()=>payload});await flush();
  assert.notEqual(h.api.getState().selectedJourneyStatus,'complete','late old expedition ignored');
  answer(h,503,{...h.identity,retryable:false,error:'non retryable'});await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,'unavailable');
  assert.equal(h.evaluate('journeyRetry.hidden'),false);
  h.evaluate('journeyRetry.onclick()');
  answer(h,200,{...h.identity,key:b.Replay_Journey_Key,records:[b]});await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,'complete');
  h.api.clearSelection();h.api.selectActive();
  answer(h,503,{...h.identity,run_id:'wrong',retryable:true});await flush();
  assert.equal(h.api.getState().selectedJourneyStatus,'unavailable','busy response identity checked');
  h.evaluate('journeyRetry.onclick()');answer(h,503,{...h.identity,retryable:true});await flush();
  h.api.clearSelection();await flush();
  assert.equal(h.timers.size,0,'cancelled retry timer removed');
  assert.equal(h.api.getPerformance().selectionRequests.pending,0);
  h.api.selectActive();
  answer(h,503,{...h.identity,retryable:true},new Date(Date.now()+45000).toUTCString());await flush();
  const dateDelay=[...h.timers.values()][0].delay;
  assert.ok(dateDelay>=43000 && dateDelay<=45000,'HTTP-date Retry-After is respected beyond capped backoff');
  h.api.clearSelection();await flush();h.api.selectActive();
  answer(h,503,{...h.identity,retryable:true},'invalid-date');await flush();
  assert.equal([...h.timers.values()][0].delay,1000,'invalid Retry-After falls back to bounded backoff');
  h.api.clearSelection();await flush();
  console.log('PASS recovery: temporary/persistent 503, Retry-After, manual retry, stale expedition, wrong identity, cancellation');
}
async function geometry() {
  const {h,a}=await setup(),unknown={...a,Motion_Plan:{status:'unavailable',fallback_reason:'native motion not reconstructible'}};
  answer(h,200,{...h.identity,key:a.Replay_Journey_Key,records:[unknown]});await flush();
  h.sandbox.unknown=unknown;
  assert.equal(h.evaluate('routePlan(unknown).length'),1,'known observed link survives unknown interpolation');
  assert.equal(h.evaluate('markerAt(unknown,6)'),null,'no invented position');
  assert.equal(h.evaluate('splitSelectedRoute([unknown],6).unresolved.length'),1);
  assert.equal(h.count('selected-unresolved'),1);
  assert.equal(h.count('selected-itinerary'),2,'verified scheduled link without observed traversal retained');
  assert.equal(h.evaluate('selectedItinerary[1].position_evidence'),'verified_transit_schedule');
  for(const unknownFirst of [true,false]) {
    const mixed=[0,10].map(start=>({...a,timestamps:[start,start+10],
      Motion_Plan:(start===0)===unknownFirst ? {status:'unavailable',fallback_reason:'unreconstructible half of journey'} :
        {version:1,status:'constant',distance_m:100,cap_mps:12,phases:[[start,start+10,0,10,0]]}}));
    h.sandbox.mixed=mixed;
    for(const time of [5,15]) {
      const split=h.evaluate(`splitSelectedRoute(mixed,${time})`);
      assert.equal(split.unresolved.length,1,'known link geometry persists in either unknown half of the journey');
      assert.ok(split.history.length+split.future.length>=1,'reconstructible half remains separate');
      assert.equal(h.evaluate(`markerAt(mixed[${unknownFirst ? 0 : 1}],${unknownFirst ? 5 : 15})`),null);
    }
  }
  h.sandbox.incomplete={...a,Motion_Plan:{version:1,status:'constant',distance_m:100,cap_mps:12,phases:[[10,20,0,10,0]]}};
  assert.equal(h.evaluate('motionAt(incomplete,15).available'),false,'a missing phase invalidates the whole segment, even inside its remaining phase');
  assert.equal(h.evaluate('routePlan(incomplete).length'),1,'invalid partial motion never removes known geometric evidence');
  h.api.seek(25);assert.equal(h.api.getState().visibleMarkers,0,'between expeditions remains invisible');
  assert.equal(h.api.diagnoseVehicle('same-bus').service_state.state,'between_services');
  assert.equal(h.count('selected-itinerary'),2,'selection keeps static itinerary without pretending bus is present');
  h.api.clearSelection();assert.equal(h.count('selected-itinerary'),0);
  console.log('PASS geometry: itinerary, observed link, unknown position, terminal interval and selection lifetime separate');
}
(async()=>{if(process.argv[2]==='geometry')await geometry();else await recovery();})().catch(e=>{console.error(e);process.exitCode=1;});
