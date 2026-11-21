// Prepared controls, not evidence that a historical disappearance has this cause.
// Imports the existing harness, which evaluates the production loader/controls.
// No browser, server, MATSim, population or protected run is opened.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1-visibility-temporal-controls.json'),'utf8'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));
const h=harness(),trace=[];
function reply(index) {
  const window=fixture.windows.find(row=>row.index===index);
  h.reply(index,{
    segments:window.segment_indexes.map(i=>structuredClone(fixture.records[i])),
    context_segments:window.context_indexes.map(i=>structuredClone(fixture.records[i])),
    trips:structuredClone(fixture.trips),lane_replay:{events:[]},context_lane_events:[],signal_replay:{series:[]}
  });
}
function inspect(name) {
  const check=fixture.checks.find(row=>row.case===name);
  const record=plain(h.api.diagnoseVehicle(check.vehicle,check.time));
  assert.equal(record.reason,check.expected_reason,name);
  if(check.expected_link)assert.equal(record.current_link,check.expected_link,name);
  trace.push({case:name,fixture_source:fixture.evidence_kind,iteration:h.identity.iteration,...record});
  return record;
}
(async()=>{
  reply(0);await flush();h.api.pause();h.api.seek(119.999);
  inspect('before_boundary');
  const nativeBefore=plain(h.evaluate('timelines.get("temporal-v")[0]'));
  assert.equal(h.evaluate('timelines.get("temporal-v").length'),1,'context is not an active row');
  assert.equal(h.evaluate('transitionTimelines.get("temporal-v").length'),2,'context remains available for transition geometry');
  assert.equal(h.evaluate('activeRecordsAt(120).filter(r=>r.vehicle==="temporal-v").length'),0,
    'the previous native interval ends exclusively; an unloaded successor must not be extrapolated');

  h.api.seek(120);
  assert.equal(h.api.getState().buffering,true);
  assert.equal(h.api.getState().current,119.999,'the displayed clock does not advance into an unloaded window');
  assert.equal(h.count('trips'),2,'the last validated frame survives while the successor is pending');
  inspect('boundary_pending');
  reply(1);await flush();
  assert.equal(h.api.getState().buffering,false);
  inspect('boundary_ready');
  assert.equal(h.evaluate('continuousReplay.cache.size'),2,'both source windows may remain cached');
  assert.equal(h.evaluate('timelines.get("spanning-v").length'),1,'only active-window rows feed the active index');
  assert.equal(h.evaluate('transitionTimelines.get("temporal-v").length'),3,'one prior context and two active-window records');
  assert.deepEqual(plain(h.evaluate('continuousReplay.cache.get(0).payload.segments[0]')),nativeBefore,
    'activation must not mutate prior native times or Motion_Plan');
  h.api.seek(120.001);inspect('retained_window_identity');
  assert.equal(h.evaluate('activeRecordsAt(120.001).filter(r=>r.vehicle==="spanning-v").length'),1);
  h.api.seek(123);const gap=inspect('known_window_unknown_interval');
  assert.equal(gap.buffering,false,'a known-window data gap is distinct from waiting for data');
  assert.equal(gap.visible,false);assert.equal(gap.position,null);
  assert.deepEqual(gap.candidate_links,[]);
  assert.equal(h.evaluate('timelines.get("temporal-v")[0].Trip.Arrival'),null,
    'missing geometry must not become a fabricated arrival');
  h.api.seek(125);inspect('after_gap');
  console.log(JSON.stringify({fixture:fixture.evidence_kind,status:'PASS',
    limitations:fixture.limitations,trace},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>h.evaluate('continuousReplay.destroy()'));
