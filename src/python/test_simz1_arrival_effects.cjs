// Synthetic fixtures with controlled monotonic time. No browser/server/MATSim,
// real replay reads, SQLite, exports or event writes. Run explicitly with Node.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({performance:{now:()=>0}});
vm.runInContext(fs.readFileSync('python/simz1_arrival_effects.js','utf8'),context);
const Effects=vm.runInContext('SimZ1ArrivalEffects',context);
const json=value=>JSON.parse(JSON.stringify(value));
const identity={run_id:'arrival-fixture',iteration:0,run_manifest_sha256:'b'.repeat(64)};
function record(vehicle='v',trip='p:1',arrival=10,overrides={}) {
  return {vehicle,Agent_ID:'p',timestamps:[0,arrival],path:[[0,0],[.001,0]],
    Trip:{Trip_ID:trip,Person_ID:'p',Departure:0,Arrival:arrival,Status:'completed',
      Abort:null,Destination_Position:[.001,0],...overrides}};
}
const candidate=(r,extra={})=>Effects.candidate(r,{family:'car',color:[245,65,65],width:1.8,...extra});
function clock() {let now=0;const manager=new Effects({identity,now:()=>now});manager.reset(0,'initial');
  return {manager,set:value=>{now=value;}};}

// Arrival between frames, no exact timestamp, independent of speed/native time.
for(const speed of [1,120]) {
  const {manager:m,set}=clock(),source=record(),original=JSON.stringify(source);
  m.ingest([candidate(source)]);set(50);m.advance(9);assert.equal(m.frame().length,0);
  set(100);m.advance(9+.02*speed+2); // Both frame steps cross 10 without equality.
  assert.equal(m.frame().length,1);assert.equal(m.frame()[0].remaining_ms,5000);
  set(1350);assert.deepEqual(json(m.frame()[0].color.slice(0,3)),[255,255,255]);
  set(2600);assert.deepEqual(json(m.frame()[0].color.slice(0,3)),[245,65,65]);
  set(5099);assert.equal(m.frame().length,1,'pause/buffer: simulated time stays fixed');
  set(5099.999);assert.equal(m.frame()[0].color[3],220,'visible until the exact deadline, without an early fade');
  set(5100);assert.equal(m.frame().length,0,'expires at exactly 5000 real ms');
  assert.equal(JSON.stringify(source),original,'no timestamp/geometry mutation');
}
{
  const {manager:m,set}=clock(),first=candidate(record()),second=candidate(record('v','p:2',20));
  m.ingest([first,first,second,candidate(record('other','q:1',10))]);
  m.advance(11);assert.equal(m.frame().length,2,'multiple simultaneous arrivals');
  m.ingest([first]);m.advance(11);assert.equal(m.snapshot().triggered,2,'window duplicates never restart lifetime');
  set(1200);m.advance(21);assert.equal(m.frame().length,3,'another trip by same vehicle has another effect');
  set(5000);assert.equal(m.frame().length,1);set(6200);assert.equal(m.frame().length,0);
  m.reset(0);m.ingest([first]);m.advance(11);assert.equal(m.frame().length,1,'intentional replay after reverse seek');
  m.reset(36000);m.ingest([first,second]);m.advance(36001);assert.equal(m.frame().length,0,'hour seek has no retrospective notices');
  m.reset(0);m.ingest([first]);m.advance(11);m.setIdentity({...identity,iteration:1});
  assert.equal(m.frame().length,0);assert.equal(m.snapshot().pending_count,0,'new iteration clears old run effects');
  m.reset(0);m.ingest([first]);m.advance(11);m.setIdentity({...identity,run_id:'another-run'});
  assert.equal(m.frame().length,0,'new run clears effects');
}
{
  const {manager:m}=clock();
  const old=Array.from({length:5000},(_,i)=>candidate(record('v'+i,'trip'+i,i+1)));
  m.ingest(old);m.reset(36000,'seek');m.ingest([...old,candidate(record('future','trip-future',36001))]);
  assert.equal(m.snapshot().pending_count,1,'large seek does not retain thousands of historical arrivals');
  m.advance(36001);assert.equal(m.frame().length,1);assert.equal(m.snapshot().triggered,1);
}
const exclusions=[
  ['aborted',record('v','p:1',10,{Status:'aborted',Abort:9})],
  ['arrival_not_confirmed',record('v','p:1',null,{Status:'censored'})],
  ['arrival_not_confirmed',record('v','p:1',null,{Status:'completed'})],
  ['arrival_not_confirmed',record('v','p:1',10,{Status:'censored'})],
  ['final_position_unknown',record('v','p:1',10,{Destination_Position:null})],
  ['outside_replay_horizon',record('v','p:1',86401)],
  ['domain_exit_not_destination_arrival',record('v','p:1',10,{System_Exit:9,
    OD:{od_type:'internal-external',destination_zone:'synthetic-exterior-exit:x',scope:'observed_z1_only'}})],
  ['domain_exit_not_destination_arrival',record('v','p:1',10,{OD:{od_type:'external-external'}})],
  ['service_completion_not_recorded',record(),{family:'bus'}],
  ['service_completion_not_recorded',record(),{family:'passenger'}]
];
for(const [reason,r,extra] of exclusions) {
  const {manager:m}=clock(),row=candidate(r,extra);assert.equal(row.reason,reason);
  m.ingest([row]);m.advance(86400);assert.equal(m.frame().length,0,reason);
}
{
  // Even a native stop-like record or a closed link does not imply an arrival.
  const r=record('bus','service:1',null,{Status:'censored'});r.vehicleArrivesAtFacility=10;r.timestamps=[0,10];
  assert.equal(candidate(r,{family:'bus'}).reason,'arrival_not_confirmed');
  const {manager:m,set}=clock();m.ingest([candidate(record('v','p:1',86400))]);
  m.advance(86399.99);assert.equal(m.frame().length,0);m.advance(86400);assert.equal(m.frame().length,1);
  m.reducedMotion=true;const tinted=json(m.frame()[0].color);
  set(2500);assert.deepEqual(json(m.frame()[0].color),tinted,'accessible mode does not alternate');
  set(4999.999);assert.ok(m.frame()[0].color[3]>0,'reduced-motion tint also survives until the deadline');
  set(5000);assert.equal(m.frame().length,0,'final day pause still expires');
}
{
  // Heap order and duplicate windows, independent of ingestion order.
  const {manager:m}=clock();m.ingest([30,10,20,5].map(t=>candidate(record('v','p:'+t,t))));
  for(const t of [5,10,20,30]){m.advance(t);assert.equal(m.snapshot().triggered,[5,10,20,30].indexOf(t)+1);}
  const {manager:conflict}=clock();conflict.ingest([candidate(record()),candidate(record('v','p:1',11))]);
  conflict.advance(12);assert.equal(conflict.frame().length,0,'conflicting terminal timestamps cannot confirm arrival');
  const {manager:contradiction}=clock();contradiction.ingest([candidate(record()),
    candidate(record('v','p:1',10,{Status:'censored'}))]);
  contradiction.advance(12);assert.equal(contradiction.frame().length,0,'contradictory status cannot confirm arrival');
  class Layer{constructor(props){this.props=props;}}
  const layer=Effects.layer({ScatterplotLayer:Layer});assert.equal(layer.props.pickable,false);
  assert.equal(layer.props.id,'arrival-annotations');assert.equal(layer.props.radiusUnits,'meters');
}

// Production controls + loader integration, not a second implementation of
// the animation logic. HTTP is an in-memory promise; time only moves on frame().
const {harness,segment,key}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function payload(start,end,arrival,{status='completed',vehicle='a',tripId='person:1',tripOverrides={}}={}) {
  const s=segment('road',start,end,0,end-start);s.vehicle=vehicle;s.Vehicle_Type='car';
  return {segments:[s],trips:{[key]:{Person_ID:'person',Trip_ID:tripId,Departure:start,
    Arrival:arrival,Status:status,Destination_Position:s.path.at(-1),...tripOverrides}}};
}
(async()=>{
  for(const speed of [1,120]) {
    const h=harness();h.reply(0,payload(0,2,2));await flush();h.api.setSpeed(speed);h.frame(0);
    const arrivedAt=3000/speed;h.frame(arrivedAt);
    assert.equal(h.count('arrival-annotations'),1,'crossed timestamp at '+speed+'x');
    assert.equal(h.count('trips'),0,'annotation is not an active body');
    assert.equal(h.api.getState().activeAgents,0);assert.equal(h.api.getState().visibleMarkers,0);
    assert.deepEqual(json(h.api.getArrivalDiagnostics().active[0].color.slice(0,3)),[245,65,65],'native motion colour retained');
    h.api.pause();const timers=h.timers.size;
    h.frame(arrivedAt+4999);assert.equal(h.count('arrival-annotations'),1);
    assert.equal(h.api.layers.find(layer=>layer.id==='arrival-annotations').props.data[0].color[3],220);
    h.frame(arrivedAt+5000);assert.equal(h.count('arrival-annotations'),0,'expiry bypasses draw coalescing');
    assert.equal(h.timers.size,timers,'no per-agent timers');
    assert.equal(h.api.getArrivalDiagnostics().active.length,0);
  }
  for(const speed of [1,120]) {
    // Publishing an arrival bypasses even a deliberate one-Hz draw limit.
    const h=harness();h.reply(0,payload(0,.005,.005));await flush();h.api.setSpeed(speed);
    h.evaluate('maxDrawHz=1');h.frame(0);h.frame(10);
    assert.equal(h.count('arrival-annotations'),1,'first crossing is drawn inside the coalescing interval at '+speed+'x');
    assert.equal(h.count('trips'),0);assert.equal(h.api.getState().activeAgents,0);
    assert.equal(h.api.getArrivalDiagnostics().active[0].started_ms,10);
    h.api.pause();h.frame(5009);assert.equal(h.count('arrival-annotations'),1);
    h.frame(5010);assert.equal(h.count('arrival-annotations'),0,'deadline also bypasses one-Hz coalescing');
  }
  {
    const h=harness();h.reply(0,payload(0,2,2));await flush();h.frame(0);h.frame(25);
    const simulated=h.api.getState().current;
    h.sandbox.document.hidden=true;h.listeners.visibilitychange();
    h.setNow(5025); // No RAF while hidden: the shared clock still passes 5000 ms.
    h.sandbox.document.hidden=false;h.listeners.visibilitychange();
    assert.equal(h.count('arrival-annotations'),0,'returning to the tab immediately removes an expired effect');
    assert.equal(h.api.getState().current,simulated,'visibility change cannot advance simulated time');
    h.frame(5026);assert.equal(h.api.getState().current,simulated,'resume rebases the RAF clock');
    assert.equal(h.api.getArrivalDiagnostics().triggered,1,'no retrospective arrivals on tab return');
  }
  {
    const h=harness();h.reply(0,payload(0,2,2));await flush();h.api.pause();
    assert.equal(h.api.selectActive(0),true);
    const selected=h.api.getState().selectedVehicleId;
    h.api.play();h.frame(25);h.api.pause();
    const card=json(h.api.getState().vehicleCard),requests=h.requests.length;
    assert.equal(h.count('arrival-annotations'),1);assert.equal(h.api.selectActive(0),false,'annotation cannot be selected as an active body');
    assert.equal(h.api.getState().activeAgents,0);assert.equal(h.api.getState().visibleMarkers,0);
    h.frame(1275);assert.deepEqual(json(h.api.getState().vehicleCard),card,'pulse does not recolor or change the six-field card');
    h.frame(5025);assert.equal(h.api.getState().selectedVehicleId,selected,'annotation expiry preserves independent selection');
    assert.equal(h.requests.length,requests,'pulse and expiry never fetch a journey');
  }
  for(const [name,status,arrival,tripOverrides] of [
    ['abort','aborted',null,{Abort:2}],['unknown interval','censored',null,{}],
    ['domain exit','completed',2,{OD:{od_type:'internal-external'}}],
    ['missing final position','completed',2,{Destination_Position:null}]
  ]) {
    const h=harness();h.reply(0,payload(0,2,arrival,{status,tripOverrides}));await flush();
    h.frame(0);h.frame(25);assert.equal(h.count('trips'),0,name+' ends its active interval');
    assert.equal(h.count('arrival-annotations'),0,name+' is never substituted with an arrival notice');
    assert.equal(h.api.getArrivalDiagnostics().triggered,0);
  }
  {
    // Missing geometry before a later confirmed arrival must not announce it early.
    const h=harness();h.reply(0,payload(0,2,6));await flush();h.frame(0);h.frame(25);
    assert.equal(h.count('trips'),0);assert.equal(h.count('arrival-annotations'),0,'unknown interval is not an arrival');
    h.frame(50);assert.equal(h.count('arrival-annotations'),1,'only the recorded arrival triggers the final marker');
  }
  {
    const h=harness(),source=payload(0,6,6);
    source.segments[0].Motion_Plan={status:'unavailable',reason:'fixture_missing_motion'};
    h.reply(0,source);await flush();h.frame(0);h.frame(10);
    assert.equal(h.evaluate('activeRecordsAt(current).length'),1);assert.equal(h.count('trips'),0,'active interval can have no drawable body');
    assert.equal(h.count('arrival-annotations'),0,'an omitted vehicle cannot activate arrival');
    h.frame(50);assert.equal(h.count('arrival-annotations'),1,'confirmed later arrival uses only the supplied final position');
  }
  {
    const h=harness();h.reply(0,payload(118,119,119));await flush();h.api.pause();h.api.seek(118);
    h.api.play();h.frame(10);assert.equal(h.count('arrival-annotations'),1);
    h.frame(20);assert.equal(h.api.getState().buffering,true);const frozen=h.api.getState().current;
    h.frame(5010);assert.equal(h.count('arrival-annotations'),0,'expires during buffer');
    assert.equal(h.api.getState().current,frozen);
    h.reply(1,{segments:[],trips:{}});await flush();
    assert.equal(h.api.getArrivalDiagnostics().triggered,1,'activation cannot repeat old arrival');
  }
  {
    const h=harness();h.reply(0,payload(118,119,119));await flush();h.api.pause();h.api.seek(118);
    h.reply(1,{segments:[],trips:{}});await flush();h.api.play();h.frame(10);
    const start=h.api.getArrivalDiagnostics().active[0].started_ms;
    h.frame(20);assert.equal(h.api.getState().cache.activeIndex,1);
    assert.equal(h.api.getArrivalDiagnostics().active[0].started_ms,start,'cached window replacement cannot restart the real-time lifetime');
    h.api.pause();h.frame(5010);assert.equal(h.count('arrival-annotations'),0);
  }
  {
    const h=harness();h.reply(0,payload(118,120,120));await flush();h.api.pause();h.api.seek(118);
    h.api.play();h.frame(2000);assert.equal(h.api.getState().pendingTime,120,'slow frame visits next window instead of skipping 120');
    h.reply(1,{segments:[],trips:{}});await flush();
    assert.equal(h.count('arrival-annotations'),1,'old-window endpoint survives atomic replacement');
    assert.equal(h.api.getArrivalDiagnostics().active[0].arrival,120);
    h.api.seek(3600);assert.equal(h.count('arrival-annotations'),0,'seek clears immediately, even before its window arrives');
    h.reply(30,payload(3600,3602,3602));await flush();assert.equal(h.count('arrival-annotations'),0);
    h.api.seek(0); // Clear pending metadata without requiring an arrival.
    assert.equal(h.api.getArrivalDiagnostics().active.length,0);
  }
  {
    const h=harness();h.reply(0,payload(0,2,2));await flush();h.frame(0);h.frame(25);
    assert.equal(h.count('arrival-annotations'),1);h.api.pause();h.api.seek(0);
    assert.equal(h.count('arrival-annotations'),0,'same-window reverse seek clears annotations');
    h.api.play();h.frame(50);assert.equal(h.count('arrival-annotations'),1,'replay creates fresh 5 s effect');
  }
  {
    const h=harness();h.reply(0,{segments:[],trips:{}});await flush();h.api.pause();h.api.seek(86399);
    h.reply(719,payload(86398,86400,86400));await flush();h.api.play();h.frame(20);
    h.reply(720,{segments:[],trips:{}});await flush();
    assert.equal(h.api.getState().current,86400);assert.equal(h.api.getState().paused,true);
    assert.equal(h.count('arrival-annotations'),1);h.frame(5020);assert.equal(h.count('arrival-annotations'),0);
    assert.equal(h.api.getState().current,86400,'no wrap or five simulated seconds added');
  }
  console.log('PASS: 5000 real ms, 1x/120x, pause/buffer, crossed arrivals, windows, identities, exclusions, seek and 24 h');
})().catch(error=>{console.error(error);process.exitCode=1;});
