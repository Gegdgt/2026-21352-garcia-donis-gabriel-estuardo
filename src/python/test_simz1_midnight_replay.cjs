'use strict';
const assert=require('node:assert/strict');
const {harness,segment,key}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const policy={schema_version:'simz1-weekday-continuous-v1',study_date:'2026-10-28',timezone:'America/Guatemala',
    windows:{study:{start_seconds:21600,end_seconds:108000},simulation:{start_seconds:0,end_seconds:136800}}};
  const h=harness({end_seconds:136800,window_count:1140,source_time_horizon:{start_seconds:0,end_seconds:136800},
    metrics_window:{start_seconds:0,end_seconds:136801}},null,null,undefined,
    {temporalPolicy:policy,cohortCounts:{persons_generated:1396,principal_cohort_persons:1000,context_persons:396,
      warmup_context_persons:320,post_context_persons:76}});
  h.reply(0,{segments:[],trips:{}});await flush();h.api.pause();
  assert.equal(h.evaluate('seeker.max'),136800);
  assert.match(h.evaluate('cohortLabel.textContent'),/1000.*396.*320.*76/);
  assert.equal(h.evaluate('runFields.get("private_vehicles").textContent'),'1000','context vehicles are not added to N');
  assert.equal(h.evaluate('technicalHelp.contains(cohortLabel) && !runPanel.contains(cohortLabel)'),true);
  assert.equal(h.evaluate('formatClock(21599)'), 'D-1 23:59:59 GT');
  assert.equal(h.evaluate('formatClock(21600)'), 'D+0 00:00:00 GT');
  assert.equal(h.evaluate('formatClock(107999)'), 'D+0 23:59:59 GT');
  assert.equal(h.evaluate('formatClock(108000)'), 'D+1 00:00:00 GT');
  const trip={Trip_ID:'person:trip:0001',Departure:107990,Arrival:108030,Status:'completed'};
  const a=segment('before',107990,108000,0,10),b=segment('after',108000,108030,10,40);
  h.api.seek(107999);if(h.request(899))h.reply(899,{segments:[a],trips:{[key]:trip}});await flush();
  assert.equal(h.api.getState().current,107999);assert.equal(h.count('trips'),1);
  assert.equal(h.request(900),undefined,'paused seek does not speculate into the next study day');
  h.api.play();h.api.seek(107999);
  h.reply(900,{segments:[b],trips:{[key]:trip}});await flush();
  h.frame(1000);h.api.pause();
  assert.ok(h.api.getState().current>=108000,'play traverses midnight instead of resetting');
  h.api.seek(108001);await flush();assert.equal(h.api.getState().current,108001);assert.equal(h.count('trips'),1);
  assert.equal(h.evaluate('timelines.get("a")[0].Trip.Arrival'),108030,'arrival remains absolute and valid');
  h.api.seek(107999);if(h.request(899))h.reply(899,{segments:[a],trips:{[key]:trip}});await flush();
  assert.equal(h.api.getState().current,107999,'backwards seek preserves absolute time');
  h.api.seek(136800);h.reply(1139,{segments:[],trips:{}});await flush();
  assert.equal(h.api.getState().paused,true);
  assert.match(h.evaluate('continuousStatus.textContent'),/Fin de observación/);
  console.log('PASS continuous midnight playback, pause, seek, source windows and cohort totals');
  const experimental=harness({end_seconds:108000,window_count:900},null,null,undefined,
    {experimentalObservation:{policy:'freight-close-plus3600-v1',demand_end_seconds:86400,observation_end_seconds:108000}});
  experimental.reply(0,{segments:[],trips:{}});await flush();experimental.api.pause();
  assert.equal(experimental.evaluate('seeker.max'),108000);
  experimental.api.seek(97200);experimental.reply(810,{segments:[],trips:{}});await flush();
  assert.equal(experimental.api.getState().current,97200,'27:00 remains observable');
  experimental.api.seek(86400);experimental.reply(720,{segments:[],trips:{}});await flush();
  assert.equal(experimental.api.getState().current,86400,'backward hour navigation retains identity');
  experimental.api.seek(108000);experimental.reply(899,{segments:[],trips:{}});await flush();
  assert.equal(experimental.api.getState().current,108000);assert.equal(experimental.api.getState().paused,true);
  assert.equal(experimental.evaluate("visibleByUserChoice({Vehicle_Family:'unknown'})"),true,'default never removes unclassified actors');
  experimental.evaluate("typeFilter.value='motorcycle'");
  assert.equal(experimental.evaluate("visibleByUserChoice({Visual_Vehicle_Presentation:{family:'motorcycle'}})"),true);
  assert.equal(experimental.evaluate("visibleByUserChoice({Visual_Vehicle_Presentation:{family:'car'}})"),false);
  experimental.evaluate("typeFilter.value='bus';routeFilter.value='L18'");
  assert.equal(experimental.evaluate("visibleByUserChoice({Trip:{Transit:{route_id:'L18'}}})"),true);
  assert.equal(experimental.evaluate("visibleByUserChoice({Trip:{Transit:{route_id:'L17'}}})"),false);
  assert.equal(experimental.api.getState().current,108000,'display filters cannot shift native time');
  console.log('PASS experimental 24-30 follow-up selection, backward seek and exact endpoint');
})().catch(error=>{console.error(error);process.exitCode=1;});
