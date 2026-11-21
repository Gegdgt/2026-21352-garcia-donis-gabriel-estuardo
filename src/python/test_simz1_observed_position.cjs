'use strict';
const assert=require('node:assert/strict');
const {harness,segment,key}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const record=segment('last-link',10,11,0,8);
  record.Motion_Plan={version:1,status:'unavailable',distance_m:8,cap_mps:4,
    phases:[],fallback_reason:'distance_exceeds_speed_cap'};
  record.Boundary_Provenance={start:'entered link',start_relative:0,end:'vehicle leaves traffic',end_relative:1};
  const trip={Trip_ID:'person:trip:0001',Departure:0,Arrival:11,Status:'completed'};
  const h=harness();h.reply(0,{segments:[record],trips:{[key]:trip}});await flush();h.api.pause();
  h.api.seek(10);await flush();
  let motion=h.evaluate('motionAt(timelines.get("a")[0],10)');
  assert.equal(motion.available,true);assert.equal(motion.fraction,0);
  assert.equal(motion.speed_kmh,null);assert.equal(motion.instant_only,true);
  assert.equal(h.count('trips'),1,'exact native entry remains visible');
  h.api.seek(10.5);await flush();assert.equal(h.count('trips'),0,'no invented interior movement');
  assert.equal(h.api.diagnoseVehicle('a').reason,'motion_unavailable');
  h.api.seek(11);await flush();assert.equal(h.count('trips'),0,'arrival is not an active vehicle');
  h.api.seek(10);await flush();assert.equal(h.count('trips'),1,'backwards seek retains exact evidence');
  const unknown={...record,Boundary_Provenance:{start:'unknown',start_relative:0}};
  const u=harness();u.reply(0,{segments:[unknown],trips:{[key]:trip}});await flush();u.api.pause();u.api.seek(10);
  assert.equal(u.count('trips'),0,'unknown endpoints do not acquire invented positions');
  console.log('PASS exact native entry position, unknown speed, unavailable interior, arrival and reverse seek');
})().catch(error=>{console.error(error);process.exitCode=1;});
