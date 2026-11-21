// Prepared regression for current diagnostic code. No browser, HTTP service,
// MATSim or historical run is started/read. The fingerprints below are fixtures.
const assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];
const source={source_type:'sqlite-direct-v1',source_manifest_sha256:'c'.repeat(64)};
const build={schema_version:1,fingerprint:'synthetic-client-fingerprint',fixture_only:true};
const journey='diagnostic-journey',path=[xy(-10,5),xy(20,5)];
const spatial={schema_version:1,mode:'gateway-od',
  boundary:{type:'Polygon',coordinates:[[xy(0,0),xy(10,0),xy(10,10),xy(0,10),xy(0,0)]]},
  allowed_links:['road','destination'],internal_links:['road','destination'],entry_gateways:{},exit_gateways:{}};
const lanes={schema_version:1,available:true,lane_width_m:3,links:{road:{
  path,num_lanes:1,opposing_lanes:0,length_m:30,offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{}}}};
const trip={Person_ID:'diagnostic-person',Trip_ID:'diagnostic-person:trip:0001',Departure:0,Arrival:30,
  Status:'completed',Last_Observed_Time:30,Observation_End:120,Origin_Position:path[0],Destination_Position:path[1],
  OD:{od_type:'internal-internal',origin_link:'road',destination_link:'destination',origin_gateway:null,
    destination_gateway:null,origin_zone:null,destination_zone:null,scope:'observed_z1_only',
    door_to_door_seconds:null,metadata_source:'synthetic_gateway_od'}};
const record={vehicle:'diagnostic-vehicle',Agent_ID:trip.Person_ID,Replay_Journey_Key:journey,Link_ID:'road',path,
  timestamps:[0,30],Motion_Plan:{version:1,status:'constant',distance_m:30,cap_mps:1,phases:[[0,30,0,1,0]]}};
const h=harness({},lanes,spatial),checks=[],harnesses=[h];
h.sandbox.config.replay_source=source;h.sandbox.window.simz1ClientBuild=build;
function provenance(row) {
  assert.equal(row.run_id,h.identity.run_id);assert.equal(row.iteration,h.identity.iteration);
  assert.equal(row.run_manifest_sha256,h.identity.run_manifest_sha256);
  assert.deepEqual(plain(row.replay_source),source);assert.deepEqual(plain(row.client_build),build);
}
function identity(row) {
  provenance(row);
  assert.equal(row.person_id,trip.Person_ID);assert.equal(row.trip_id,trip.Trip_ID);
  assert.equal(row.journey_key,journey);
}
(async()=>{
  h.reply(0,{segments:[record],trips:{[journey]:trip},context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
  await flush();h.api.pause();h.api.seek(15);
  const current=h.api.diagnoseVehicle(record.vehicle,15);identity(current);
  assert.equal(current.visible,true);assert.equal(current.reason,'visible');
  assert.equal(current.dimensions_m.length,2);assert.ok(current.dimensions_m.every(Number.isFinite));
  const onDemandFrame=h.api.getVisualDiagnostics(16);provenance(onDemandFrame);
  const onDemand=onDemandFrame.records.find(row=>row.vehicle_id===record.vehicle);
  assert.equal(onDemand.visible,true);assert.equal(onDemand.link_id,'road');
  checks.push({case:'current_and_on_demand_identity',current:plain(current),on_demand:plain(onDemand)});

  const outside=h.api.getVisualDiagnostics(5).records.find(row=>row.vehicle_id===record.vehicle);
  assert.equal(outside.visible,false);assert.equal(outside.reason,'spatial_filter');
  h.api.seek(5);const renderedOutside=h.api.diagnoseVehicle(record.vehicle,5);
  assert.equal(renderedOutside.reason,outside.reason,'on-demand polygon verdict agrees with the actual frame');
  assert.equal(h.count('trips'),0);checks.push({case:'spatial_polygon',record:plain(renderedOutside)});

  // Defense-in-depth unit case: accepted payloads normally cannot contain a
  // disallowed link. Alter only the in-memory fixture membership after loading
  // to exercise the same membership predicate in diagnostics and rendered data.
  h.evaluate('spatialRenderer.allowed.delete("road")');
  const disallowed=h.api.getVisualDiagnostics(16).records.find(row=>row.vehicle_id===record.vehicle);
  assert.equal(disallowed.visible,false);assert.equal(disallowed.reason,'spatial_filter');
  h.api.seek(16);assert.equal(h.count('trips'),0);
  assert.equal(h.api.diagnoseVehicle(record.vehicle,16).reason,disallowed.reason);
  h.evaluate('spatialRenderer.allowed.add("road")');
  checks.push({case:'spatial_link_membership_defense_only',record:plain(disallowed)});

  h.api.seek(15);assert.equal(h.api.selectActive(),true);
  const requestsBeforeTrace=h.requests.length,timeBeforeTrace=h.api.getState().current;
  const selected=h.api.traceSelectedVehicle([15,16,121]);provenance(selected);
  assert.equal(selected.vehicle_id,record.vehicle);
  assert.deepEqual(plain(selected.records.map(row=>row.reason)),['visible','moving','window_not_loaded']);
  assert.equal(h.requests.length,requestsBeforeTrace,'inspection cannot load another window or journey');
  assert.equal(h.api.getState().current,timeBeforeTrace,'inspection cannot change displayed time');

  h.api.seek(31);const arrived=h.api.diagnoseVehicle(record.vehicle,31);
  identity(arrived);assert.equal(arrived.reason,'arrived');assert.equal(arrived.visible,false);
  assert.equal(h.evaluate('timelines.get("diagnostic-vehicle")[0].Trip.Arrival'),30);
  checks.push({case:'observed_arrival_metadata',record:plain(arrived)});

  const fallback=harness({},null,spatial);harnesses.push(fallback);
  fallback.reply(0,{segments:[structuredClone(record)],trips:{[journey]:structuredClone(trip)},
    context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
  await flush();fallback.api.pause();fallback.api.seek(15);
  assert.equal(fallback.count('trips'),1);
  const noQueue=fallback.api.getVisualDiagnostics(16).records.find(row=>row.vehicle_id===record.vehicle);
  assert.equal(noQueue.link_id,'road','fallback diagnostic must retain the identity used by spatial filtering');
  assert.equal(noQueue.visible,true,'a permitted centre must remain visible without lane/queue geometry');
  checks.push({case:'spatial_without_visual_queue_geometry',record:plain(noQueue)});
  console.log(JSON.stringify({status:'PASS',fixture_only:true,
    limitation:'Node VM validates diagnostic contracts, not the source served to a real browser or WebGL visibility.',checks},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const session of harnesses)session.evaluate('continuousReplay.destroy()');
});
