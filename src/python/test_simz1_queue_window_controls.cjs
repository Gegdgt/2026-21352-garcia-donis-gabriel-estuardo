// Prepared integration checks using the existing in-memory DOM/deck/fetch
// harness. No real HTTP, browser, SQLite, MATSim or run writes are performed.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const sourcePath=require('node:path');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale],plain=value=>JSON.parse(JSON.stringify(value));
const flush=()=>new Promise(resolve=>setImmediate(resolve)),sessions=[],evidence=[];
const keyOf=row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key ?? '',row.Link_ID,row.timestamps]);
const trip=(journey,from,to,end)=>({Trip_ID:journey,Person_ID:'person:'+journey,Departure:0,Arrival:end,Status:'completed',
  Origin_Position:from,Destination_Position:to});
function links(path,extra={}) {
  return {schema_version:1,available:true,lane_width_m:3,links:{road:{path,num_lanes:1,opposing_lanes:0,
    offset_eligible:true,from_node:'a',to_node:'b',native_lanes:{},allowed_to_links:[],
    movement_source:'effective_car_node_adjacency',...extra}}};
}
async function ready(h) {
  for(let round=0;round<20 && h.api.getState().buffering;round++) {
    await flush();
    for(const [id,timer] of h.timers)if(timer.delay===0){h.timers.delete(id);timer.fn();}
  }
  assert.equal(h.api.getState().error,null);assert.equal(h.api.getState().buffering,false);
  h.api.pause();
}
function context(row,metadata,complete) {
  const key=keyOf(row);
  return {schema_version:1,policy:'native-hold-closure-v1',by_seed:{[key]:{
    complete,reason:complete ? null : 'record_limit',record_keys:complete ? [key] : []}},
    segments:complete ? [structuredClone(row)] : [],transition_segments:[],
    trips:complete ? {[row.Replay_Journey_Key]:metadata} : {},lane_events:[]};
}
function frameRecord(h,time,vehicle) {
  return h.api.getVisualDiagnostics(time).records.find(row=>row.vehicle_id===vehicle);
}
(async()=>{
  const path=[xy(0,0),xy(100,0)],journey='held-trip',metadata=trip(journey,path[0],path[1],240);
  const held={vehicle:'held-car',Agent_ID:metadata.Person_ID,Vehicle_Type:'car',Replay_Journey_Key:journey,
    Link_ID:'road',path,timestamps:[0,240],Motion_Plan:{version:1,status:'kinematic',distance_m:100,
      hold_start:20,native_wait_boundary:20,cap_mps:5,phases:[[0,20,0,5,0],[20,240,100,0,0]]},
    Observed_Waits:{signal_red:{first:20,last:239,position_evidence:'queue_exit'}}};
  const snapshots=[];
  for(const complete of [true,false,null]) {
    const supported=complete===true;
    const h=harness({},links(path));sessions.push(h);
    const payload={segments:[structuredClone(held)],trips:{[journey]:structuredClone(metadata)},context_segments:[],
      ...(complete==null ? {} : {queue_context:context(held,metadata,complete)}),lane_replay:{events:[]},signal_replay:{series:[]}};
    const original=JSON.stringify(payload);h.reply(0,payload);await ready(h);h.api.seek(30);
    const rendered=frameRecord(h,30,held.vehicle),onDemand=frameRecord(h,31,held.vehicle);
    assert.equal(rendered.visible,true);assert.equal(onDemand.visible,true);
    assert.equal(h.count('trips'),1,'incomplete spacing evidence cannot hide a valid native pose');
    assert.equal(rendered.spacing_compatible,supported);assert.equal(onDemand.spacing_compatible,supported);
    assert.deepEqual(plain(rendered.native_position),plain(onDemand.native_position));
    assert.deepEqual(plain(rendered.dimensions_m),[4.5,1.8]);
    if(supported) {
      assert.equal(rendered.reason,'visible');assert.equal(onDemand.reason,'queued');
      assert(rendered.position[0]<rendered.native_position[0],'complete closure supports estimated stop spacing');
      assert.equal(h.api.getVisualDiagnostics(30).counts.incompleteHoldContext,0);
    } else {
      assert.equal(rendered.reason,'queue_context_incomplete');assert.equal(onDemand.reason,'queue_context_incomplete');
      assert.deepEqual(plain(rendered.position),plain(rendered.native_position));
      assert.equal(h.api.getVisualDiagnostics(30).counts.incompleteHoldContext,1);
      assert.equal(rendered.details.context.reason,complete==null ? 'queue_context_unavailable' : 'record_limit');
    }
    h.api.seek(31);const now=frameRecord(h,31,held.vehicle);
    assert.equal(now.visible,onDemand.visible);assert.equal(now.spacing_compatible,onDemand.spacing_compatible);
    assert.deepEqual(plain(now.position),plain(onDemand.position));
    h.api.seek(30);assert.deepEqual(plain(frameRecord(h,30,held.vehicle).position),plain(rendered.position),'reverse seek keeps the same absolute-time pose');
    assert.equal(JSON.stringify(payload),original,'the harness serializes the fixture; native inputs remain unchanged');
    snapshots.push({complete,rendered:plain(rendered),on_demand:plain(onDemand)});
  }
  evidence.push({case_id:'controls_complete_and_incomplete_closure',snapshots});

  // A seed can fail its own budget while another complete closure legitimately
  // needs it as historical anchor evidence. Those roles cannot overwrite each
  // other merely because the predecessor is currently active.
  {
    const make=(vehicle,start,hold,end)=>({vehicle,Agent_ID:'person:'+vehicle,Vehicle_Type:'car',
      Replay_Journey_Key:'trip:'+vehicle,Link_ID:'road',path,timestamps:[start,end],
      Motion_Plan:{version:1,status:'kinematic',distance_m:100,hold_start:hold,native_wait_boundary:hold,
        phases:[[start,hold,0,100/(hold-start),0],[hold,end,100,0,0]]},
      Observed_Waits:{signal_red:{first:hold,last:end-1,position_evidence:'queue_exit'}}});
    const leader=make('limited-leader',0,10,20),follower=make('complete-follower',1,11,100),members=[keyOf(leader),keyOf(follower)];
    const trips=Object.fromEntries([leader,follower].map(row=>[row.Replay_Journey_Key,{
      ...trip(row.Replay_Journey_Key,path[0],path[1],row.timestamps[1]),Departure:row.timestamps[0],Person_ID:row.Agent_ID}]));
    const h=harness({},links(path));sessions.push(h);
    h.reply(0,{segments:[leader,follower],trips,context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]},
      queue_context:{schema_version:1,policy:'native-hold-closure-v1',
        by_seed:{[members[0]]:{complete:false,reason:'record_limit',record_keys:[]},
          [members[1]]:{complete:true,reason:null,record_keys:members}},segments:[structuredClone(leader),structuredClone(follower)],
        transition_segments:[],trips:structuredClone(trips),lane_events:[]}});
    await ready(h);const trace=[];
    for(const time of [15,21,15,21]) {
      h.api.seek(time);const current=frameRecord(h,time,follower.vehicle);
      assert.equal(current.visible,true);assert.equal(current.spacing_compatible,true);
      const station=current.position[0]*scale;
      assert(Math.abs(station-89.25)<.001,'the complete follower keeps its 95.75 - 6.5 m anchor across leader departure');
      assert.equal(h.count('trips'),time<20 ? 2 : 1);
      if(time<20) {
        const limited=frameRecord(h,time,leader.vehicle);
        assert.equal(limited.visible,true);assert.equal(limited.spacing_compatible,false);
        assert.equal(limited.reason,'queue_context_incomplete');assert.equal(limited.details.context.reason,'record_limit');
      }
      trace.push({time,station_m:station,visible_count:h.count('trips')});
    }
    evidence.push({case_id:'active_seed_failure_does_not_erase_complete_anchor_role',trace});
  }

  // A transition interval can be useful at C's hold=11 without certifying B's
  // own hold=18. The old v2 producer incorrectly omitted B's future dependencies;
  // preserve that captured payload to check that the consumer never promotes it.
  // The current producer includes the complete offline anchor closure instead.
  {
    const fixturePath = sourcePath.join(__dirname, 'fixtures/simz1_queue_context_anchor_roles.json');
    const fixtureBytes = fs.readFileSync(fixturePath);
    const fixture = JSON.parse(fixtureBytes.toString('utf8'));
    const nativeBefore = JSON.stringify(fixture);
    const variants = [];
    const base = links(fixture.active_record.path);
    const geometry = {...base, links: {...base.links,
      upstream: {...base.links.road, from_node: 'upstream-origin', to_node: 'a'}}};
    const productionDirectory = process.env.SIMZ1_RENDER_SOURCE_DIR || 'python';
    const fingerprints = () => Object.fromEntries(['simz1_continuous_loader.js', 'visualizador_z1_controls.js',
      'simz1_visual_queues.js', 'simz1_visual_lanes.js'].map(name => [name,
      crypto.createHash('sha256').update(fs.readFileSync(sourcePath.join(productionDirectory, name))).digest('hex')]));
    const productionBefore = fingerprints();
    for (const backed of [false, true]) {
      const queue = structuredClone(backed ? fixture.complete_queue_context : fixture.auxiliary_queue_context);
      const primaryKeys = new Set(Object.values(queue.by_seed).flatMap(status => status.record_keys));
      const nativeB = [...queue.segments, ...queue.transition_segments].find(row => row.vehicle === 'B' && row.timestamps[0] === 1);
      const bKey = keyOf(nativeB);
      assert.equal(nativeB.Motion_Plan.hold_start, 18);
      assert.equal(fixture.active_record.Motion_Plan.hold_start, 11);
      assert.equal(primaryKeys.has(bKey), backed, 'only a resolved closure can certify the future anchor');
      assert.equal(queue.segments.some(row => row.vehicle === 'future'), backed,
        'the complete producer includes the dependency active at B\'s own hold');
      const h = harness({window_seconds: 30, window_count: 3000}, structuredClone(geometry));
      sessions.push(h);
      h.reply(0, {segments: [], trips: {}, lane_replay: {events: []}, signal_replay: {series: []}});
      const payload = {segments: [structuredClone(fixture.active_record)], trips: queue.trips,
        context_segments: [], queue_context: queue, lane_replay: {events: []}, signal_replay: {series: []}};
      const sourceBefore = JSON.stringify(payload);
      h.api.setQueueGap(0.1);
      h.api.seek(31);
      h.reply(1, payload);
      await ready(h);
      const roster = plain(h.evaluate('queueRoster().map(marker => ({vehicle: marker.vehicle, timestamps: marker.timestamps, hold: marker.Motion_Plan.hold_start, context: marker.Visual_Queue_Context}))'));
      const historicalB = roster.find(row => row.vehicle === 'B' && row.timestamps[0] === 1);
      assert.ok(historicalB, 'auxiliary interval remains available as transition evidence');
      assert.equal(historicalB.context.complete, backed);
      assert.equal(historicalB.context.role, backed ? 'resolved_anchor' : 'auxiliary_transition');
      if (!backed) assert.equal(historicalB.context.reason, 'auxiliary_transition_without_anchor_certificate');
      const anchors = new Map(plain(h.evaluate('Array.from(visualQueueRenderer.anchorCache.base.entries())')));
      assert.equal(anchors.has(bKey), backed, 'an uncertified auxiliary must not acquire an anchor at hold=18');
      if (backed) assert.ok(Number.isFinite(anchors.get(bKey)), 'the backed offline future anchor remains usable');
      assert.equal(JSON.stringify(payload), sourceBefore, 'native records and dependency payload remain unchanged');
      variants.push({backed_future_anchor: backed, primary_record_keys: [...primaryKeys], historical_B: historicalB,
        B_anchor_computed: anchors.has(bKey), B_anchor_m: anchors.get(bKey) ?? null,
        dependency_vehicles: queue.segments.map(row => row.vehicle), source_unchanged: true});
    }
    assert.equal(JSON.stringify(fixture), nativeBefore);
    assert.deepEqual(fingerprints(), productionBefore, 'production remains unchanged during the role regression');
    const result = {case_id: 'auxiliary_transition_cannot_certify_future_hold', status: 'passed',
      scope: 'Consumer role and anchor-certificate contract; this small synthetic geometry is not a spacing-acceptance fixture.',
      fixture: fixturePath, fixture_sha256: crypto.createHash('sha256').update(fixtureBytes).digest('hex'),
      source_sha256: productionBefore, variants};
    evidence.push(result);
    if (process.env.SIMZ1_QUEUE_ROLE_EVIDENCE) fs.writeFileSync(process.env.SIMZ1_QUEUE_ROLE_EVIDENCE,
      JSON.stringify({...result, command: 'node python/test_simz1_queue_window_controls.cjs'}, null, 2) + '\n');
  }

  // On-demand diagnostics and the drawn frame share the native-centre predicate.
  // Eastbound: source is on the edge while the estimated right lane is outside.
  // Westbound: source is just outside while the estimated right lane is inside.
  for(const nativeInside of [true,false]) {
    const path=nativeInside ? [xy(10,0),xy(90,0)] : [xy(90,-.5),xy(10,-.5)];
    const journey='spatial-'+nativeInside,metadata=trip(journey,path[0],path[1],100);
    metadata.OD={od_type:'internal-internal',origin_link:'road',destination_link:'destination',origin_gateway:null,
      destination_gateway:null,origin_zone:null,destination_zone:null,scope:'observed_z1_only',
      door_to_door_seconds:null,metadata_source:'synthetic_gateway_od'};
    const spatial={schema_version:1,mode:'gateway-od',boundary:{type:'Polygon',coordinates:[[
      xy(0,0),xy(100,0),xy(100,100),xy(0,100),xy(0,0)]]},allowed_links:['road','destination'],
      internal_links:['road','destination'],entry_gateways:{},exit_gateways:{}};
    const geometry=links(path,{opposing_lanes:1,reverse_link:'recorded-reverse',length_m:80});
    const row={vehicle:'spatial-car',Agent_ID:metadata.Person_ID,Vehicle_Type:'car',Replay_Journey_Key:journey,
      Link_ID:'road',path,timestamps:[0,100],Motion_Plan:{version:1,status:'constant',distance_m:80,cap_mps:.8,
        phases:[[0,100,0,.8,0]]}};
    const h=harness({},geometry,spatial);sessions.push(h);
    h.reply(0,{segments:[row],trips:{[journey]:metadata},context_segments:[],lane_replay:{events:[]},signal_replay:{series:[]}});
    await ready(h);h.api.seek(50);
    const actual=frameRecord(h,50,row.vehicle),requested=frameRecord(h,51,row.vehicle);
    assert.equal(actual.visible,nativeInside);assert.equal(requested.visible,nativeInside);
    assert.equal(h.count('trips'),Number(nativeInside));
    const diagnosis=h.api.diagnoseVehicle(row.vehicle,50);
    assert.equal(diagnosis.spatial_evidence.native_axis_inside,nativeInside);
    assert.equal(diagnosis.spatial_evidence.rendered_center_inside,!nativeInside);
    if(!nativeInside)assert.equal(requested.reason,'spatial_filter');
    h.api.seek(51);const renderedLater=frameRecord(h,51,row.vehicle);
    assert.equal(renderedLater.visible,requested.visible);assert.deepEqual(plain(renderedLater.position),plain(requested.position));
    evidence.push({case_id:'controls_spatial_offset',native_inside:nativeInside,rendered:plain(actual),on_demand:plain(requested)});
    if(nativeInside) {
      h.evaluate('spatialRenderer.allowed.delete("road")');
      assert.equal(frameRecord(h,52,row.vehicle).visible,false,'link membership still applies to a native centre inside');
      h.api.seek(52);assert.equal(h.count('trips'),0);
      assert.equal(frameRecord(h,52,row.vehicle).reason,'spatial_filter');
    }
  }
  if(process.argv.includes('--evidence'))console.log(JSON.stringify(evidence,null,2));
  else console.log('PASS: complete/incomplete queue context and native-domain visibility agree in controls and diagnostics');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const h of sessions)h.evaluate('continuousReplay.destroy()');
});
