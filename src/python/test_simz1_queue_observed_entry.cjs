'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/simz1_observed_entry.json'),'utf8'));
const flush=()=>new Promise(resolve=>setImmediate(resolve)),plain=value=>JSON.parse(JSON.stringify(value));
(async()=>{
  const original=JSON.stringify(fixture),segment=fixture.segment,journey=segment.Replay_Journey_Key;
  const h=harness({end_seconds:136800,window_count:1140},fixture.visual_lanes);
  h.api.seek(21624);h.reply(180,{segments:[segment],trips:{[journey]:fixture.trip},
    context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
  for(let i=0;i<20 && h.api.getState().buffering;i++)await flush();
  h.api.pause();
  for(const [time,visible] of [[21624,true],[21624.1,false],[21624.9,false],[21625,false],[21624,true]]) {
    h.api.seek(time);await flush();
    assert.equal(h.count('trips'),Number(visible),`actual source visibility at${time}`);
    if(visible) {
      const marker=h.api.layers.find(layer=>layer.id==='trips').props.data[0];
      assert.deepEqual(plain(marker.position),segment.path[0],'retain exact native entry centre, no offset');
      assert.equal(marker.Visual_Speed_kmh,null,'neither zero nor an invented speed');
      assert.equal(marker.Visual_Motion_Status,'observed_event_position');
      assert.equal(marker.Visual_Queue_State,'native_link_entry_position');
      assert.equal(marker.Visual_Queue_Compatible,false);
      assert.equal(marker.Visual_Queue_Redistribution,false);
      assert.equal(marker.Visual_Lane_Index,null);
      assert.equal(marker.Visual_Native_Event_Position.instant_only,true);
      assert.deepEqual(plain(marker.Motion_Plan),segment.Motion_Plan,'unavailable motion remains unavailable');
      h.sandbox.savedNativeEntry=marker;
    }
  }
  const later=h.evaluate('visualQueueRenderer.frame([savedNativeEntry],21624.5)');
  assert.equal(later.markers.length,0,'even a stale exact-entry marker cannot fill the interior');
  assert.equal(later.omitted[0].Visual_Queue_State,'motion_unavailable');
  const spoof=h.evaluate('visualQueueRenderer.frame([{...savedNativeEntry,Visual_Speed_kmh:0}],21624)');
  assert.equal(spoof.markers.length,0,'zero speed does not grant the exact native event exception');
  assert.equal(JSON.stringify(fixture),original);
  console.log('PASS actual ctx_pre_00311: queue renderer preserves exact21624 native entry, null speed, unavailable interior, arrival and reverse seek');
})().catch(error=>{console.error(error);process.exitCode=1;});
