// Synthetic frontend integration. No browser, HTTP server, native run or export.
'use strict';
const assert=require('node:assert/strict'),{harness}=require('./test_simz1_continuous_replay.cjs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(departure='out',start=0,end=20,finished=false) {
  const key=(departure==='out' ? 'a' : 'b').repeat(64),driver='internal-only';
  const transit={schema:'simz1-transit-replay-v1',vehicle_id:'same-bus',driver_id:driver,line_id:'line',route_id:'route',departure_id:departure,
    service_id:'TuBus-fixture',operator:'synthetic',domain_scope:'synthetic_fixture',
    source:{schedule_sha256:'a'.repeat(64),vehicles_sha256:'b'.repeat(64)},route_links:['road'],
    activity_intervals:finished ? [] : [{start:5,end:10,state:'stop',facility_id:'s',source:'native_facility_events'},
      {start:end,end:30,state:'terminal',source:'native_arrival_until_next_dispatch'}],
    terminal_status:finished ? 'service_finished' : 'between_services',service_end_confirmed:finished,
    completion_source:'native_driver_arrival_after_traffic_exit'};
  const trip={Person_ID:null,Driver_ID:driver,Trip_ID:'transit:'+JSON.stringify(['same-bus','line','route',departure]),
    Departure:start,Arrival:end,Status:'completed',Transit:transit,Destination_Position:[.001,0]};
  return {vehicle:'same-bus',Agent_ID:null,Driver_ID:driver,Vehicle_Family:'bus',Vehicle_Type:'custom-actual-type',
    Vehicle_Dimensions:{length_m:12,width_m:2.5,source:'synthetic-assumed',assumed:true},Replay_Journey_Key:key,
    Trip:trip,Link_ID:'road',timestamps:[start,end],path:[[0,0],[.001,0]],
    Motion_Provenance:{vehicle_limit_mps:12},Motion_Plan:{version:1,status:'constant',distance_m:100,cap_mps:12,
      phases:[[start,end,0,100/(end-start),0]]},Speed_kmh:18};
}
if(require.main===module)(async()=>{
  const h=harness(),a=fixture(),b=fixture('back',30,50,true);
  h.sandbox.equalTimeBoundaries=[{...a,timestamps:[20,20]},{...b,timestamps:[20,20]}];
  assert.equal(h.evaluate('SimZ1ContinuousLoader.prepare({segments:equalTimeBoundaries}).transitionRecords.size'),2,
    'coincident zero-length boundaries of distinct expeditions never share transition identity');
  h.api.pause();h.reply(0,{segments:[a,b],trips:{[a.Replay_Journey_Key]:a.Trip,[b.Replay_Journey_Key]:b.Trip}});await flush();
  h.api.seek(6);
  assert.equal(h.api.getState().activeAgents,0,'internal driver is not road demand');
  assert.equal(h.api.getState().activePublicVehicles,1);
  assert.equal(h.api.getState().hud.data.counts.persons_generated,179235,'B never changes N');
  assert.equal(h.api.diagnoseVehicle('same-bus').service_state.state,'stop');
  h.sandbox.testBus=a;
  const card=h.evaluate('buildVehicleCardFields(testBus,6)');
  assert.equal(Object.keys(card).length,6);assert.equal(card.type,'Transporte público');
  assert.equal(card.name,'Vehículo same-bus');assert.equal(card.maximumSpeed,'43.2 km/h');
  assert.equal(h.evaluate('SimZ1VehicleCatalog.resolve(testBus).dimensions.length_m'),12);
  assert.equal(h.evaluate('SimZ1VehicleCatalog.resolve(testBus).service'),'TuBus-fixture');
  assert.equal(h.evaluate('SimZ1ArrivalEffects.candidate(testBus,{family:"bus"}).reason'),'service_completion_not_recorded');
  h.api.seek(25);assert.equal(h.api.getState().activePublicVehicles,0);
  assert.equal(h.api.diagnoseVehicle('same-bus').service_state.state,'between_services');
  h.api.seek(35);assert.equal(h.api.getState().activePublicVehicles,1);
  assert.equal(h.api.diagnoseVehicle('same-bus').trip_id,b.Trip.Trip_ID);
  h.sandbox.testBus=b;
  assert.equal(h.evaluate('SimZ1ArrivalEffects.candidate(testBus,{family:"bus"}).reason'),'confirmed_native_arrival');
  const invalid=structuredClone(b);invalid.Driver_ID='another-driver';h.sandbox.invalidBus=invalid;
  assert.throws(()=>h.evaluate('SimZ1ContinuousLoader.transitTrip(invalidBus.Trip,invalidBus)'),/incompatible/);
  h.api.selectActive(0);h.journey({key:b.Replay_Journey_Key,records:[b]});await flush();
  assert.equal(h.api.getPerformance().selectionRequests.completed,1);
  h.api.selectActive(0);assert.equal(h.api.getPerformance().selectionRequests.cacheHits,1);
  assert.equal(h.api.getPerformance().selectionRequests.started,1);
  h.api.clearSelection();assert.equal(h.api.getPerformance().selectionRequests.retainedJourneys,0);
  h.evaluate('continuousReplay.destroy()');
  assert.equal(h.api.getPerformance().loader.pendingRequests,0);
  assert.equal(h.api.getPerformance().loader.cachedWindows,0);
  console.log('PASS synthetic transit identity, two expeditions, dwell/terminal, six fields, selection and closure');
})().catch(error=>{console.error(error);process.exitCode=1;});
module.exports={fixture};
