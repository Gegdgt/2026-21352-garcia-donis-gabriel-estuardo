'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1_boundary_paths.json'),'utf8'));
const flush=()=>new Promise(resolve=>setImmediate(resolve)),plain=value=>JSON.parse(JSON.stringify(value));
(async()=>{
  const before=JSON.stringify(fixture);
  for(const row of fixture.cases) {
    const segment=row.segment,index=row.time/120;
    const h=harness({end_seconds:136800,window_count:1140},fixture.visual_lanes,null,undefined,
      {temporalPolicy:fixture.temporal_policy});
    h.api.seek(row.time);h.reply(index,{segments:[segment],trips:{[segment.Replay_Journey_Key]:row.trip},
      context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
    for(let i=0;i<20 && h.api.getState().buffering;i++)await flush();h.api.pause();
    assert.equal(h.count('trips'),1,row.segment.vehicle);
    const marker=h.api.layers.find(layer=>layer.id==='trips').props.data[0];
    assert.equal(marker.Visual_Queue_State,'recorded_path_lateral_unknown');
    assert.equal(marker.Visual_Queue_Compatible,false);assert.equal(marker.Visual_Queue_Redistribution,false);
    assert.equal(marker.Visual_Lane_Index,null);
    assert.deepEqual(plain(marker.position),plain(marker.Visual_Native_Center_Position),'preserve source pose, no lateral offset');
    assert.deepEqual(plain(marker.Motion_Plan),segment.Motion_Plan);
    assert.equal(marker.Visual_Recorded_Boundary_Path.continuous_position_observed,false);
    assert.equal(marker.Visual_Recorded_Boundary_Path.position_basis,segment.Motion_Plan.distance_m===0 ?
      'fixed_recorded_boundary_position':'interpolated_within_recorded_boundary_path');
    h.sandbox.source={...segment,Trip:row.trip};
    for(const mutation of [
      'source.Boundary_Provenance.start_relative=.9',
      'source.Boundary_Provenance.end="unobserved"',
      'source.Motion_Plan.distance_m+=3',
      'source.path[0][0]+=.01',
    ]) {
      h.sandbox.source=plain({...segment,Trip:row.trip});h.evaluate(mutation);
      assert.equal(h.evaluate('visualLaneRenderer.recordedBoundaryPath(source)'),null,'incompatible provenance remains unsupported');
    }
    if(row.trip.Transit) {
      h.sandbox.source=plain({...segment,Trip:row.trip});delete h.sandbox.source.Trip.Transit;
      assert.equal(h.evaluate('visualLaneRenderer.recordedBoundaryPath(source)'),null,'a facility endpoint needs native activity evidence');
    }
  }
  assert.equal(JSON.stringify(fixture),before);
  console.log('PASS three actual stationary/partial boundary paths, unchanged source poses/motion, unknown lateral placement and14 rejected inconsistent records');
})().catch(error=>{console.error(error);process.exitCode=1;});
