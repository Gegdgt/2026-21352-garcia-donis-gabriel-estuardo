'use strict';
const assert=require('node:assert/strict');
const {harness,segment,key}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const h=harness({end_seconds:86400,window_count:720},null,null,undefined,
    {experimentalObservation:{policy:'fixed-day-24h-v1',demand_end_seconds:86400,observation_end_seconds:86400}});
  h.reply(0,{segments:[],trips:{}});await flush();h.api.pause();
  assert.equal(h.evaluate('seeker.max'),86400);
  const pending={Trip_ID:'person:trip:0001',Departure:86340,Arrival:null,Status:'censored',Observation_End:86400};
  h.api.seek(86399);h.reply(719,{segments:[segment('pending',86340,86400,0,60)],trips:{[key]:pending}});await flush();
  assert.equal(h.api.getState().current,86399);
  h.api.seek(86401);await flush();
  assert.equal(h.api.getState().current,86400);assert.equal(h.api.getState().paused,true);
  assert.equal(h.evaluate('replayTrip({Arrival:null,Status:"censored",Departure:86340}).Arrival'),null);
  assert.equal(h.evaluate('replayTrip({Arrival:86400,Status:"completed"}).Status'),'completed');
  assert.equal(h.evaluate('replayTrip({Arrival:null,Abort:86400,Status:"aborted"}).Status'),'aborted');
  assert.equal(h.evaluate('replayTrip({Arrival:null,Abort:86400,Status:"censored"}).Status'),'censored');
  assert.match(h.evaluate('runScope.textContent'),/observacion 00-24 h/);
  assert.doesNotMatch(h.evaluate('runScope.textContent'),/seguimiento historico/);
  console.log('PASS fixed-day cutoff, real arrival T, real abort T, cleanup censoring and no postcut playback');
})().catch(error=>{console.error(error);process.exitCode=1;});
