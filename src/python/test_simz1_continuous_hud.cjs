// Small metadata-only contracts: no server, browser, simulation or replay data.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'simz1_continuous_hud.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
function options(run='run-a') {
  return {run_id:run,iteration:0,run_manifest_sha256:(run==='run-a' ? 'a' : 'b').repeat(64),source_version:'d'.repeat(64),
    start_seconds:0,end_seconds:86400,
    source_time_horizon:{start_seconds:0,end_seconds:90000},
    metrics_window:{start_seconds:0,end_seconds:90001}};
}
function payload(o=options(),count=179235) {
  return {schema_version:1,run_id:o.run_id,iteration:o.iteration,run_manifest_sha256:o.run_manifest_sha256,source_version:o.source_version,
    replay_window:{start_seconds:o.start_seconds,end_seconds:o.end_seconds},
    source_time_horizon:clone(o.source_time_horizon),metrics_window:clone(o.metrics_window),
    counts:{persons_generated:count,planned_trips:count+17,completed_trips:125001,
      pending_censored_trips:54251,reconstructed_vehicles:179210,vehicles_with_events:179211},
    native_active_series:null};
}
function harness(o=options()) {
  const requests=[],states=[];
  const sandbox={URLSearchParams,AbortController,
    fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));}};
  vm.createContext(sandbox);
  const Hud=vm.runInContext(source+'\nSimZ1ContinuousHud;',sandbox);
  const hud=new Hud(o,{onState:state=>states.push(clone(state))});
  return {hud,requests,states,
    reply(index,data=payload(o),status=200){requests[index].resolve({ok:status===200,status,json:async()=>clone(data)});},
    fail(index,message){requests[index].reject(new Error(message));}};
}
function fixedFreight() {
  const o=options();o.source_time_horizon.end_seconds=o.metrics_window.end_seconds=86400;
  const p=payload(o);p.screening={status:'review_required'};
  p.freight_transport={configured:{enabled:true,vehicles_configured:4,departures_scheduled:4,
    fleet_vehicle_ids:['f1','f2','f3','f4']},observed:{vehicles_observed:2,departures_observed:4,
    arrivals_observed:1,fleet_vehicle_ids:['f1','f2'],status:'valid',technical_integrity:'valid',
    day_observation_policy:'fixed-day-24h-v1',active_in_traffic_at_cut:1,waiting_for_insertion:2,
    scheduled_not_departed_at_cut:0,censored_at_horizon:3,active_or_censored:3,missing_departures:0,
    aborted_expeditions:0,observed_traffic_entries:{f1:10,f2:20},observed_traffic_exits:{f1:30},
    terminal_events:{f1:{status:'completed',time:31},f2:{status:'aborted',time:86400}},
    completion_records:[1,2,3,4].map(i=>({vehicle_id:'f'+i,entry_seconds:({1:10,2:20})[i]??null,
      traffic_exit_seconds:i===1?30:null,arrival_seconds:i===1?31:null,
      trip_outcome:i===1?'completed':'censored_at_horizon'}))}};
  p.day_observation={policy:'fixed-day-24h-v1',execution:'native_day_completed',
    technical_integrity:'verified_precleanup_census',coverage_end_seconds:86400,
    groups:[{family:'pesado',od:'service',scheduled_hour:0,scheduled_requests:4,incorporations:2,
      real_arrivals:1,completed:1,active_at_cut:1,waiting_for_incorporation:2}]};
  return {o,p};
}
(async()=>{
  const h=harness();
  assert.equal(h.requests.length,0,'constructor does not start a request');
  const loading=h.hud.load();
  assert.equal(h.requests.length,1);assert.equal(h.states.length,1);
  assert.deepEqual(clone(h.hud.snapshot()),{status:'loading',data:null,error:null});
  const url=new URL(h.requests[0].url,'http://localhost');
  assert.equal(url.pathname,'/api/hud');
  for(const key of ['run_id','iteration','run_manifest_sha256','source_version','start_seconds','end_seconds'])
    assert.equal(url.searchParams.get(key),String(options()[key]),'query '+key);
  assert.equal(h.requests[0].options.cache,'no-store');
  h.reply(0);await loading;
  assert.equal(h.hud.snapshot().status,'ready');
  assert.equal(h.hud.snapshot().data.counts.persons_generated,179235);
  assert.equal(h.hud.snapshot().data.counts.planned_trips,179252);
  assert.equal(h.hud.snapshot().data.native_active_series,null,'unavailable QSim activity remains null');
  assert.deepEqual(h.states.map(s=>s.status),['loading','ready']);

  const reloading=h.hud.load();
  assert.deepEqual(clone(h.hud.snapshot()),{status:'loading',data:null,error:null},'reload clears displayed values synchronously');
  h.reply(1,payload(),503);await reloading;
  assert.equal(h.hud.snapshot().status,'error');assert.equal(h.hud.snapshot().data,null);
  assert.match(h.hud.snapshot().error,/HTTP 503/);
  const retry=h.hud.load();
  assert.equal(h.hud.snapshot().error,null,'retry clears the old error synchronously');
  const optional=payload();
  for(const key of ['completed_trips','pending_censored_trips','reconstructed_vehicles','vehicles_with_events'])optional.counts[key]=null;
  h.reply(2,optional);await retry;assert.equal(h.hud.snapshot().status,'ready');
  assert.equal(h.hud.snapshot().data.counts.completed_trips,null);
  assert.equal(h.requests.length,3,'no automatic polling or retries');

  // Presentation is backed by an explicit count contract, not a renamed person scalar.
  assert.equal(h.hud.constructor.vehicleSummary(payload()).private_vehicles,null);
  for(const n of [0,120]) {
    const sample=harness(),pending=sample.hud.load(),data=payload(options(),n);
    data.public_transport={configured:{enabled:true,road_demand_persons:n,
      public_transport_vehicles_configured:2,fleet_vehicle_ids:['bus-a','bus-b'],
      service_counts:[{configured_vehicle_ids:['bus-a']},{configured_vehicle_ids:['bus-a']},{configured_vehicle_ids:['bus-b']}]}};
    data.vehicle_summary={schema_version:1,private_vehicles:n,public_vehicles:2,temporal_policy:false,
      private_basis:'verified_private_one_vehicle_per_person',public_basis:'unique_configured_fleet_ids'};
    sample.reply(0,data);await pending;
    assert.equal(sample.hud.snapshot().status,'ready');
    const summary=sample.hud.constructor.vehicleSummary(sample.hud.snapshot().data);
    assert.equal(summary.private_vehicles,n);assert.equal(summary.public_vehicles,2,'repeated bus service is not extra fleet');
    for(let frame=0;frame<10;frame++)sample.hud.constructor.vehicleSummary(sample.hud.snapshot().data);
    assert.equal(sample.requests.length,1,'presentation adds no metadata requests');
  }
  const temporal=harness(),temporalLoad=temporal.hud.load(),temporalData=payload(options(),120);
  temporalData.counts={...temporalData.counts,principal_cohort_persons:100,context_persons:20,warmup_context_persons:15,post_context_persons:5};
  temporalData.vehicle_summary={schema_version:1,private_vehicles:100,public_vehicles:0,temporal_policy:true,
    private_basis:'verified_main_cohort_one_vehicle_per_person',public_basis:'explicitly_disabled'};
  temporalData.public_transport={configured:{enabled:false,road_demand_persons:120,public_transport_vehicles_configured:0}};
  temporalData.freight_transport={configured:{enabled:true,vehicles_configured:12,departures_scheduled:12},
    observed:{vehicles_observed:12,departures_observed:12}};
  temporal.reply(0,temporalData);await temporalLoad;
  assert.equal(temporal.hud.snapshot().status,'ready');
  assert.equal(temporal.hud.constructor.vehicleSummary(temporal.hud.snapshot().data).private_vehicles,100);
  assert.equal(temporal.hud.constructor.vehicleSummary(temporal.hud.snapshot().data).public_vehicles,0);
  for(const key of ['vehicles_observed','departures_observed']) {
    const data=clone(temporalData);data.freight_transport.observed[key]--;
    assert.throws(()=>temporal.hud.validate(data,options()),/histórico/,'full-service guard '+key);
  }

  const fixed=fixedFreight(),fixedHud=harness(fixed.o).hud;
  const original=JSON.stringify(fixed.p);
  assert.equal(fixedHud.validate(fixed.p,fixed.o).screening.status,'review_required');
  assert.equal(fixed.p.freight_transport.observed.vehicles_observed,2);
  assert.equal(JSON.stringify(fixed.p),original,'validation does not rewrite native counts');
  for(const [name,mutate] of [
    ['entries above configured',p=>p.freight_transport.observed.vehicles_observed=5],
    ['arrivals above entries',p=>p.freight_transport.observed.arrivals_observed=3],
    ['negative waiting',p=>p.freight_transport.observed.waiting_for_insertion=-1],
    ['boolean count',p=>p.freight_transport.observed.active_in_traffic_at_cut=true],
    ['missing required count',p=>delete p.freight_transport.observed.arrivals_observed],
    ['missing configured count',p=>delete p.freight_transport.configured.vehicles_configured],
    ['missing freight',p=>delete p.freight_transport],
    ['missing configured',p=>delete p.freight_transport.configured],
    ['missing enabled',p=>delete p.freight_transport.configured.enabled],
    ['false enabled',p=>p.freight_transport.configured.enabled=false],
    ['duplicate configured ID',p=>p.freight_transport.configured.fleet_vehicle_ids[1]='f1'],
    ['duplicate observed ID',p=>p.freight_transport.observed.fleet_vehicle_ids[1]='f1'],
    ['foreign observed ID',p=>p.freight_transport.observed.fleet_vehicle_ids[1]='foreign'],
    ['missing day policy',p=>delete p.day_observation.policy],
    ['corrupt day object',p=>p.day_observation='corrupt'],
    ['missing observed policy',p=>delete p.freight_transport.observed.day_observation_policy],
    ['missing groups',p=>delete p.day_observation.groups],
    ['duplicate group',p=>p.day_observation.groups.push(clone(p.day_observation.groups[0]))],
    ['bad group balance',p=>p.day_observation.groups[0].waiting_for_incorporation=1],
    ['missing base counter',p=>delete p.day_observation.groups[0].incorporations],
    ['foreign entry',p=>p.freight_transport.observed.observed_traffic_entries.foreign=10],
    ['corrupt time',p=>p.freight_transport.observed.observed_traffic_entries.f2='20'],
    ['exit before entry',p=>p.freight_transport.observed.observed_traffic_exits.f1=1],
    ['duplicate census ID',p=>p.freight_transport.observed.completion_records[1].vehicle_id='f1'],
    ['missing census time',p=>delete p.freight_transport.observed.completion_records[2].entry_seconds],
    ['fabricated arrival',p=>p.freight_transport.observed.completion_records[1].arrival_seconds=50],
    ['arrival before exit',p=>{p.freight_transport.observed.terminal_events.f1.time=29;
      p.freight_transport.observed.completion_records[0].arrival_seconds=29;}],
    ['missing terminal',p=>delete p.freight_transport.observed.terminal_events],
    ['early abort',p=>p.freight_transport.observed.terminal_events.f2.time=80000],
    ['false completion',p=>p.freight_transport.observed.completion_records[1].trip_outcome='completed'],
    ['bad censored balance',p=>p.freight_transport.observed.censored_at_horizon=2],
  ]) {
    const data=clone(fixed.p);mutate(data);
    assert.throws(()=>fixedHud.validate(data,fixed.o),/incompatible/,name);
  }
  const unstarted=clone(fixed.p);
  Object.assign(unstarted.freight_transport.observed,{departures_observed:3,waiting_for_insertion:1,
    scheduled_not_departed_at_cut:1,missing_departures:1});
  Object.assign(unstarted.day_observation.groups[0],{waiting_for_incorporation:1,scheduled_not_departed:1});
  assert.equal(fixedHud.validate(unstarted,fixed.o).freight_transport.observed.vehicles_observed,2);
  const noSource=options();delete noSource.source_version;
  assert.throws(()=>fixedHud.validate(payload(),noSource),/Identidad/,'source version is mandatory');
  for(const mutate of [p=>p.vehicle_summary.private_vehicles=120,p=>p.vehicle_summary.private_basis='planned_persons',
      p=>p.vehicle_summary.public_vehicles=12,p=>p.vehicle_summary.private_vehicles=undefined]) {
    const sample=harness(),pending=sample.hud.load(),data=clone(temporalData);mutate(data);
    sample.reply(0,data);await pending;
    assert.equal(sample.hud.snapshot().status,'error');assert.equal(sample.hud.snapshot().data,null);
  }
  const changedCount=temporal.hud.load(options('run-b'));
  assert.equal(temporal.hud.snapshot().data,null,'identity transition clears both fleet totals');
  temporal.reply(1,payload(options('run-b')),503);await changedCount;
  assert.equal(temporal.hud.snapshot().data,null,'failed identity reload cannot retain old vehicle totals');

  for(const N of [1,120,250000]) {
    const sample=harness(),pending=sample.hud.load(),data=payload(options(),N);
    data.public_transport={configured:{road_demand_persons:N,public_transport_vehicles_configured:120,
      fleet_by_system:{transmetro:80,tubus:40}}};
    sample.reply(0,data);await pending;
    assert.equal(sample.hud.snapshot().status,'ready');
    assert.equal(sample.hud.snapshot().data.public_transport.configured.public_transport_vehicles_configured,120);
    assert.equal(sample.hud.snapshot().data.counts.persons_generated,N);
  }

  const wrongPayloads=[
    ['schema',p=>p.schema_version=2],
    ['run',p=>p.run_id='other'],['iteration',p=>p.iteration=1],['hash',p=>p.run_manifest_sha256='c'.repeat(64)],
    ['source version',p=>p.source_version='e'.repeat(64)],['missing source version',p=>delete p.source_version],
    ['replay start',p=>p.replay_window.start_seconds=1],['replay end',p=>p.replay_window.end_seconds=90000],
    ['source',p=>p.source_time_horizon.end_seconds=86400],['metrics',p=>p.metrics_window.end_seconds=86400],
    ['extra horizon key',p=>p.metrics_window.unknown=true],
    ['required null',p=>p.counts.persons_generated=null],['missing required',p=>delete p.counts.planned_trips],
    ['negative',p=>p.counts.pending_censored_trips=-1],['fraction',p=>p.counts.completed_trips=1.5],
    ['unsafe integer',p=>p.counts.reconstructed_vehicles=Number.MAX_SAFE_INTEGER+1],
    ['string',p=>p.counts.vehicles_with_events='12'],['missing optional',p=>delete p.counts.vehicles_with_events],
    ['unvalidated activity',p=>p.native_active_series=[]]
  ];
  for(const [name,mutate] of wrongPayloads) {
    const sample=harness(),pending=sample.hud.load(),data=payload();mutate(data);
    sample.reply(0,data);await pending;
    assert.equal(sample.hud.snapshot().status,'error',name);
    assert.equal(sample.hud.snapshot().data,null,name+' never displays unvalidated values');
    assert.deepEqual(sample.states.map(s=>s.status),['loading','error'],name);
  }

  const changed=harness(),first=changed.hud.load(),nextOptions=options('run-b');
  nextOptions.hud_endpoint='/custom/hud?mode=summary';
  const second=changed.hud.load(nextOptions);
  assert.equal(changed.requests[0].options.signal.aborted,true,'changing run aborts previous request');
  assert.equal(changed.hud.snapshot().data,null);
  const changedUrl=new URL(changed.requests[1].url,'http://localhost');
  assert.equal(changedUrl.pathname,'/custom/hud');assert.equal(changedUrl.searchParams.get('mode'),'summary');
  assert.equal(changedUrl.searchParams.get('run_id'),'run-b');
  changed.reply(1,payload(nextOptions,241));await second;
  changed.reply(0,payload(options(),179235));await first;
  assert.equal(changed.hud.snapshot().data.run_id,'run-b');
  assert.equal(changed.hud.snapshot().data.counts.persons_generated,241,'late old-run response ignored');
  assert.deepEqual(changed.states.map(s=>s.status),['loading','loading','ready']);

  const revised=harness(),oldSource=revised.hud.load(),newSource={...options(),source_version:'e'.repeat(64)};
  const newLoad=revised.hud.load(newSource);
  revised.reply(1,payload(newSource,240));await newLoad;
  revised.reply(0,payload(options(),179235));await oldSource;
  assert.equal(revised.hud.snapshot().data.source_version,newSource.source_version,'late response from same run/iteration but old source ignored');
  assert.equal(revised.hud.snapshot().data.counts.persons_generated,240);

  const staleError=harness(),oldFailure=staleError.hud.load(),current=staleError.hud.load(options('run-b'));
  staleError.fail(0,'late failure');await oldFailure;
  assert.deepEqual(clone(staleError.hud.snapshot()),{status:'loading',data:null,error:null});
  staleError.reply(1,payload(options('run-b'),237));await current;
  assert.equal(staleError.hud.snapshot().data.counts.persons_generated,237);
  assert.equal(staleError.states.some(s=>s.status==='error'),false,'obsolete failure never leaks into new state');

  const delayed=harness(),old=delayed.hud.load();let finishJson;
  delayed.requests[0].resolve({ok:true,status:200,json:()=>new Promise(resolve=>{finishJson=resolve;})});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(typeof finishJson,'function');
  const fresh=delayed.hud.load();
  delayed.reply(1,payload(options(),123));await fresh;
  finishJson(payload(options(),179235));await old;
  assert.equal(delayed.hud.snapshot().data.counts.persons_generated,123,'stale decoded response ignored even for same run');
  assert.deepEqual(delayed.states.map(s=>s.status),['loading','loading','ready']);
  console.log('PASS: async HUD totals, identity and horizons, loading/error resets, no invented active count, stale response/error rejection');
})().catch(error=>{console.error(error);process.exitCode=1;});
