'use strict';
// Recorded V6/V7 intervals, isolated to two actors per fixture. This exercises the
// production loader, controls and renderer; it is not a global browser audit or
// a claim that reconstructed centres are native microscopic observations.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const path=require('node:path');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const plain=value=>JSON.parse(JSON.stringify(value));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const key=r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key,r.Link_ID,r.timestamps]);
const metre=6371008.8*Math.PI/180;
const distance=(a,b)=>Math.hypot((a[0]-b[0])*metre*Math.cos((a[1]+b[1])*Math.PI/360),(a[1]-b[1])*metre);

// Independent polygon SAT, deliberately not calling the production collision
// helper. A gap inflates each end by gap/2, so parallel bodies need gap metres.
// Use the declared model's common local metric frame, not a different latitude
// for each pair: the latter introduces micrometre differences at a strict gap.
function projectionLatitude(fixture) {
  const latitudes = Object.values(fixture.visual_lanes.links).flatMap(link => link.path.map(point => point[1]));
  return (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
}
function polygonsOverlap(a,b,gap=0,latitude=(a.position[1]+b.position[1])/2) {
  const origin=a.position;
  const polygon=body=>{
    const angle=body.heading*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
    const x=(body.position[0]-origin[0])*metre*Math.cos(latitude*Math.PI/180),y=(body.position[1]-origin[1])*metre;
    return [[-1,-1],[-1,1],[1,1],[1,-1]].map(([u,v])=>{
      const along=u*(body.length+gap)/2,side=v*body.width/2;
      return [x+c*along-s*side,y+s*along+c*side];
    });
  };
  const left=polygon(a),right=polygon(b);
  for(const points of [left,right])for(let i=0;i<4;i++) {
    const next=points[(i+1)%4],dx=next[0]-points[i][0],dy=next[1]-points[i][1],norm=Math.hypot(dx,dy);
    const projection=p=>p[0]*(-dy/norm)+p[1]*(dx/norm);
    const aa=left.map(projection),bb=right.map(projection);
    if(Math.max(...aa)<=Math.min(...bb)+1e-6 || Math.max(...bb)<=Math.min(...aa)+1e-6)return false;
  }
  return true;
}
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length:m.Visual_Body_Length_Meters,width:m.Visual_Body_Width_Meters});
const protectedRecord=r=>Object.fromEntries(['vehicle','Replay_Journey_Key','Link_ID','timestamps',
  'Native_Occupancy','Native_Occupancy_Progress','Boundary_Provenance','Observed_Waits','Motion_Plan',
  'Vehicle_Dimensions','Vehicle_Physical_Dimensions','Vehicle_Type','Vehicle_PCU','Vehicle_Family',
  'Movement_End','Motion_Provenance'].map(k=>[k,r[k]]));
const cases=[
  {file:'python/fixtures/simz1_corridor_boundary_24301_5.json',name:'departing bus across car/bus adjacency',
    turnSweep: {start: 24302, end: 24312, step: 0.1,
      follower: 'ptbus_transmetro_L12_003', leader: 'ptbus_transmetro_L12_002'},
    times:[24293.999,24294,24294.001,24298,24301.5,24302,24307.999,24308,24311.999,24312,24312.001,24326]},
  {file:'python/fixtures/simz1_corridor_boundary_29695.json',name:'native zero-duration gateway and following bus',
    times:[29694.999,29695,29695.001,29695.5,29695.999999,29696,29696.001,29697,29698,29700]},
  {
    file: 'python/fixtures/simz1_corridor_boundary_29711.json',
    name: 'V7 stopped follower behind a leader still moving at dwell entry',
    boundaries: [29691, 29716, 29718],
    times: [29690.999999, 29691, 29691.000001, 29692, 29693, 29695, 29711,
      29715.999999, 29716, 29716.000001, 29717, 29717.999999, 29718, 29718.000001, 29720, 29722]
  },
  {
    file: 'python/fixtures/simz1_corridor_boundary_51339_5.json',
    name: 'V7 physical bus length across adjacent stop and signal intervals',
    boundaries: [51331, 51356, 51358, 51362],
    times: [51330.999999, 51331, 51331.000001, 51332, 51333, 51335, 51339.5,
      51355.999999, 51356, 51356.000001, 51357, 51357.999999, 51358, 51358.000001,
      51360, 51361.999999, 51362, 51362.000001, 51363]
  }
];
const sourceDirectory=process.env.SIMZ1_RENDER_SOURCE_DIR || 'python';
const fingerprint=()=>Object.fromEntries(['simz1_visual_lanes.js','simz1_visual_queues.js','simz1_continuous_loader.js',
  'visualizador_z1_controls.js'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(sourceDirectory,name))).digest('hex')]));
const evidence={scope:'Bounded Node production-pipeline regression; supplied closure of two isolated actors per fixture, not all vehicles in V6/V7',
  source_directory:sourceDirectory,source_sha256:fingerprint(),cases:[]};

function setup(fixture,{reverse=false,gap=.1,requireTwoActors=false,expectedUnavailable=[]}={}) {
  const rows=plain(fixture.records);if(reverse)rows.reverse();
  const metricLatitude = projectionLatitude(fixture);
  const trips=plain(fixture.trips),keys=rows.map(key),replay=harness({},plain(fixture.visual_lanes));
  const payload={segments:rows,trips,context_segments:[],lane_replay:plain(fixture.lane_replay),signal_replay:{series:[]},
    queue_context:{schema_version:1,policy:'native-hold-closure-v1',segments:rows,transition_segments:rows,trips,lane_events:[],
      by_seed:Object.fromEntries(keys.map(k=>[k,{complete:true,reason:null,record_keys:keys}]))}};
  const before=hash({rows,trips});replay.reply(0,{...payload,segments:[]});replay.api.setQueueGap(gap);
  async function at(time,seek=true) {
    if(seek)replay.api.seek(time);
    const index=Math.floor(time/120);if(replay.request(index))replay.reply(index,payload);
    for(let i=0;i<12;i++)await flush();
    assert.equal(replay.api.getState().buffering,false,'fixture has activated, not an empty loading frame');
    assert.ok(Math.abs(replay.api.getRenderPerformance().displayedTime-time)<1e-8,'inspect the actually displayed frame, not a throttled prior frame');
    const diagnostics=plain(replay.api.getVisualDiagnostics(time));
    const markers=plain(replay.evaluate("layers.find(layer=>layer.id==='trips').props.data"));
    const nativeIds=[...new Set(rows.filter(r=>r.timestamps[0]<=time && time<r.timestamps[1]).map(r=>r.vehicle))].sort();
    assert.ok(nativeIds.length > 0, 'test contains actual active actors');
    if (requireTwoActors) assert.deepEqual(nativeIds, [...fixture.expected_vehicles].sort(),
      'both recorded actors are active at every sampled time');
    const expectedMissing = expectedUnavailable.filter(row => row.start < time && time < row.end);
    for (const missing of expectedMissing) {
      const source = rows.find(row => row.vehicle === missing.vehicle && row.timestamps[0] === missing.start && row.timestamps[1] === missing.end);
      assert.ok(source, 'an expected omission must identify the original native interval');
      assert.equal(source.Motion_Plan.status, 'unavailable');
      assert.equal(source.Motion_Plan.fallback_reason, missing.reason);
      assert.deepEqual(source.Motion_Plan.phases, []);
      const diagnostic = diagnostics.records.find(row => row.vehicle_id === missing.vehicle);
      assert.equal(diagnostic.visible, false);
      assert.equal(diagnostic.reason, 'motion_unavailable');
      assert.equal(diagnostic.motion_reason, missing.reason);
      assert.equal(diagnostic.position, null, 'no position is invented for an unavailable native interval');
    }
    const renderedIds = nativeIds.filter(id => !expectedMissing.some(row => row.vehicle === id));
    assert.deepEqual(markers.map(m=>m.vehicle).sort(),renderedIds,
      'every native active actor is rendered exactly once at ' + time + ': ' + JSON.stringify(diagnostics.counts));
    assert.equal(diagnostics.counts.omitted,expectedMissing.length,'only explicitly unavailable source intervals may be omitted');
    assert.equal(diagnostics.counts.unresolvedOverlaps,0,
      'no reported unresolved spacing at ' + time + ': ' + JSON.stringify(diagnostics.collisions));
    assert.equal(diagnostics.counts.incompleteHoldContext,0,'complete isolated native hold closure');
    let comparableGap=null, satPairsChecked=0;
    for(let i=0;i<markers.length;i++) {
      const m=markers[i],source=rows.find(r=>key(r)===key(m));
      assert.ok(source,'rendered marker identifies its actual native interval');
      assert.deepEqual(protectedRecord(m),protectedRecord(source),'renderer preserves native evidence and Motion_Plan');
      if (hash(m.path) !== hash(source.path)) {
        // A blocking dwell uses the recorded lane axis to draw its rigid body.
        // The immutable native point remains explicit in projection provenance.
        assert.equal(source.Motion_Plan.status, 'stationary');
        assert.equal(source.Boundary_Provenance.start, 'VehicleArrivesAtFacility');
        assert.equal(source.Boundary_Provenance.end, 'VehicleDepartsAtFacility');
        assert.deepEqual(source.path[0], source.path[1], 'only a stationary endpoint may be normalized');
        assert.deepEqual(m.path, fixture.visual_lanes.links[source.Link_ID].path,
          'dwell body geometry comes from the supplied network axis');
        assert.equal(m.Visual_Facility_Footprint_Projection.source, 'estimated_body_behind_native_service_endpoint');
        assert.deepEqual(m.Visual_Facility_Footprint_Projection.native_endpoint, source.path[0],
          'original facility point remains inspectable');
        assert.equal(m.Visual_Facility_Footprint_Projection.continuous_position_observed, false);
      }
      assert.equal(m.Visual_Body_Length_Meters,13.5,'native bus length is preserved');
      assert.equal(m.Visual_Body_Width_Meters,2.5);
      assert.equal(m.Visual_Body_Clipped,false,'no clipping to conceal contact');
      assert.notEqual(m.Visual_Occupancy_Position_Observed,true,'projection cannot claim observed coordinates');
      assert.ok(m.Visual_Occupancy_Position_Observed===false || m.Visual_Queue_Source==='native_link_entry_center_estimated_orientation',
        'projection has explicit provenance: '+time+' '+m.vehicle+' '+m.Visual_Queue_Source);
      for(const other of markers.slice(0,i)) {
        satPairsChecked++;
        assert.equal(polygonsOverlap(body(m),body(other),0,metricLatitude),false,'independent SAT excludes physical body overlap at '+time);
        assert.equal(polygonsOverlap(body(m),body(other),.1,metricLatitude),false,
          'independent longitudinal 0.10m safety envelope at ' + time + ': ' + JSON.stringify([m, other].map(marker => ({
            vehicle: marker.vehicle, ...body(marker), domain: marker.Visual_Occupancy_Domain,
            center_m: marker.Visual_Queue_Center_Meters, source: marker.Visual_Queue_Source
          }))));
        if(m.Visual_Occupancy_Domain===other.Visual_Occupancy_Domain && m.Visual_Lane_Index===other.Visual_Lane_Index) {
          const gap=Math.abs(m.Visual_Queue_Center_Meters-other.Visual_Queue_Center_Meters)-
            (m.Visual_Body_Length_Meters+other.Visual_Body_Length_Meters)/2;
          assert.ok(gap>=.1-1e-6,'comparable corridor front-to-tail gap >=0.10m: '+gap);
          comparableGap=comparableGap===null?gap:Math.min(comparableGap,gap);
        }
      }
    }
    assert.equal(hash({rows,trips}),before,'source payload unchanged after seek');
    return {time,markers,comparable_gap_m:comparableGap,sat_pairs_checked:satPairsChecked,
      expected_motion_omissions:expectedMissing.map(row => ({vehicle:row.vehicle,reason:row.reason,start:row.start,end:row.end}))};
  }
  return {at,async playback(times,speed) {
    const result=[await at(times[0])];replay.api.setSpeed(speed);replay.api.play();
    for(const time of times.slice(1)) {
      // Supply an already-requested next window before the clock crosses it.
      // The real server prefetches this data; leaving that request unanswered
      // would test a network stall instead of continuous geometric placement.
      const index = Math.floor(time / 120);
      if (replay.request(index)) {
        replay.reply(index, payload);
        for (let tick = 0; tick < 12; tick++) await flush();
      }
      replay.frame((time-times[0])*1000/speed);
      assert.ok(Math.abs(replay.api.getState().current-time)<1e-8,
        'continuous clock reaches ' + time + ' at ' + speed + 'x: ' + JSON.stringify(replay.api.getState()));
      result.push(await at(time,false));
    }
    replay.api.pause();return result;
  },destroy(){replay.evaluate('continuousReplay.destroy()');}};
}

function equalPose(a,b,message) {
  assert.deepEqual(a.markers.map(m=>m.vehicle).sort(),b.markers.map(m=>m.vehicle).sort());
  for(const left of a.markers) {
    const right=b.markers.find(m=>m.vehicle===left.vehicle);
    assert.ok(distance(left.position,right.position)<1e-6,message+' position '+left.vehicle);
    assert.ok(Math.abs(left.Visual_Body_Heading_Degrees-right.Visual_Body_Heading_Degrees)<1e-7,message+' heading');
    assert.equal(left.Visual_Occupancy_Domain,right.Visual_Occupancy_Domain,message+' domain');
  }
}

(async()=>{
  for(const spec of cases) {
    const fixture=JSON.parse(fs.readFileSync(spec.file,'utf8')),before=hash(fixture);
    assert.equal(fixture.expected_vehicles.length,2);
    assert.equal(fixture.historical_bad_bodies.length,2);
    assert.equal(polygonsOverlap(...fixture.historical_bad_bodies.map(body),0,projectionLatitude(fixture)),true,
      'negative control: independent SAT detects the original browser contact');
    const create = options => setup(fixture, {requireTwoActors: Boolean(spec.boundaries || spec.turnSweep), ...options});
    const warm=create(),frames=[];
    try {
      for(const time of spec.times)frames.push(await warm.at(time));
      console.log('PASS: '+spec.name+' — visible bodies, independent SAT and protected source data');
      for(const frame of [...frames].reverse())equalPose(frame,await warm.at(frame.time),'reverse seek');
      console.log('PASS: '+spec.name+' — absolute-time reverse seek');
      for(const frame of frames.filter(row=>[fixture.time,29696,24312,...(spec.boundaries || [])].includes(row.time))) {
        const cold=create({reverse:true});
        try {equalPose(frame,await cold.at(frame.time),'cold seek with reversed input record order');}
        finally {cold.destroy();}
      }
      console.log('PASS: '+spec.name+' — cold seek and reversed record order');
      const defaultGap=create({gap:2});
      try {await defaultGap.at(fixture.time);}finally{defaultGap.destroy();}
      const continuousSamples=[];
      for(const speed of [1,120]) {
        const continuous=create();
        try {
          // The production viewer draws at 60 Hz. At 120x, two simulated
          // seconds provide a complete display interval; sub-millisecond seek
          // checks above intentionally remain separate from RAF playback.
          const expected=[];
          for(const frame of frames)if(Number.isInteger(frame.time) &&
            (!expected.length || frame.time-expected.at(-1).time >= (speed===120?2:1)))expected.push(frame);
          assert.ok(expected.length>=2,'continuous verification crosses an interval boundary');
          const played=await continuous.playback(expected.map(row=>row.time),speed);
          for(let i=0;i<expected.length;i++)equalPose(expected[i],played[i],speed+'x continuous playback');
          continuousSamples.push({speed,times:expected.map(row=>row.time),display_rate_hz:60});
        }finally{continuous.destroy();}
      }
      console.log('PASS: '+spec.name+' — continuous playback at 1x and 120x matches absolute-time poses');
      const boundaryContinuity = [];
      for (const boundary of spec.boundaries || []) {
        const samples = [boundary - 0.000001, boundary, boundary + 0.000001]
          .map(time => frames.find(frame => Math.abs(frame.time - time) < 1e-8));
        assert.ok(samples.every(Boolean), 'sample both sides of each native interval boundary');
        for (const vehicle of fixture.expected_vehicles) {
          const positions = samples.map(frame => frame.markers.find(marker => marker.vehicle === vehicle).position);
          const before = distance(positions[0], positions[1]);
          const after = distance(positions[1], positions[2]);
          // A 1 us movement at ordinary road speeds is below this 0.1 mm bound.
          // Larger changes expose a discontinuous release or a changed stop anchor.
          assert.ok(before < 0.0001, `${vehicle}: no jump into ${boundary}: ${before} m`);
          assert.ok(after < 0.0001, `${vehicle}: no jump out of ${boundary}: ${after} m`);
          boundaryContinuity.push({time: boundary, vehicle, before_m: before, after_m: after});
        }
      }
      if (boundaryContinuity.length) console.log('PASS: ' + spec.name + ' - continuous dwell and release boundaries');
      let turnSweep = null;
      if (spec.turnSweep) {
        const sweep = spec.turnSweep;
        const count = Math.round((sweep.end - sweep.start) / sweep.step) + 1;
        const times = Array.from({length: count}, (_, index) => Number((sweep.start + index * sweep.step).toFixed(6)));
        assert.equal(times.length, 101, 'dense turn regression includes both endpoints');
        assert.equal(times.at(-1), sweep.end);
        // This V6 source interval is explicitly not reconstructible. Preserve
        // its omission rather than granting a vacuous two-body geometry PASS.
        const unavailable = [{vehicle: sweep.leader, start: 24309, end: 24311, reason: 'distance_exceeds_speed_cap'}];
        const sweepReplay = create({expectedUnavailable: unavailable});
        const samples = [];
        try {
          for (const time of times) samples.push(await sweepReplay.at(time));
          const first = samples[0].markers.find(marker => marker.vehicle === sweep.follower);
          let maximumDisplacement = 0;
          let originalBounds = null;
          for (const frame of samples) {
            const follower = frame.markers.find(marker => marker.vehicle === sweep.follower);
            const displacement = distance(first.position, follower.position);
            maximumDisplacement = Math.max(maximumDisplacement, displacement);
            assert.ok(displacement < 0.000001, 'stopped follower keeps one immutable anchor through the complete turn at ' + frame.time);
            if (frame.time < sweep.end) {
              assert.equal(follower.Visual_Queue_Holding, true, 'native HOLD remains represented throughout its interval');
              const bounds = follower.Visual_Queue_Turn_Clearance;
              assert.ok(Array.isArray(bounds) && bounds.length > 0, 'turn clearance has explicit provenance');
              assert.ok(bounds.some(bound => bound.leader === sweep.leader));
              for (const bound of bounds) {
                assert.equal(bound.source, 'conservative_rigid_turn_front_projection_v1');
                assert.equal(bound.positions_observed, false);
                assert.equal(bound.hold_start, sweep.start);
                assert.equal(bound.front_path.source, 'estimated_recorded_lane_front_path_v1');
                assert.equal(bound.front_path.positions_observed, false);
                assert.ok(bound.front_path.path.length >= 2, 'the bound uses a supplied route, not an isolated point');
              }
              if (!originalBounds) originalBounds = bounds;
              else assert.deepEqual(bounds, originalBounds, 'the complete turn bound is fixed at the native hold epoch');
            }
          }
          for (const frame of [...samples].reverse()) equalPose(frame, await sweepReplay.at(frame.time), 'turn sweep reverse seek');
          for (const frame of samples) {
            const cold = create({reverse: true, expectedUnavailable: unavailable});
            try {equalPose(frame, await cold.at(frame.time), 'turn sweep cold seek with reversed record order');}
            finally {cold.destroy();}
          }
          const paired = samples.filter(frame => frame.markers.length === 2);
          const incomplete = samples.filter(frame => frame.expected_motion_omissions.length > 0);
          assert.equal(paired.length, 82, '82 samples have two supported visible bodies');
          assert.equal(incomplete.length, 19, '19 samples preserve the unavailable interval explicitly');
          assert.ok(paired.every(frame => frame.sat_pairs_checked === 1));
          assert.ok(incomplete.every(frame => frame.markers.length === 1 && frame.sat_pairs_checked === 0));
          turnSweep = {start: sweep.start, end: sweep.end, step_seconds: sweep.step, frames: samples.length,
            geometry_coverage: 'partial', two_visible_actor_frames: paired.length,
            unavailable_motion_frames: incomplete.map(frame => ({time:frame.time,omissions:frame.expected_motion_omissions})),
            follower: sweep.follower, leader: sweep.leader,
            maximum_follower_displacement_m: maximumDisplacement, independent_longitudinal_gap_m: 0.1,
            independent_body_contacts: 0, independent_longitudinal_contacts: 0, reverse_seek: true,
            cold_seek_every_sample: true, source_unchanged: true, turn_clearance: originalBounds,
            limitation: 'Pair geometry is verified only for 82 samples. The other 19 require an explicit distance_exceeds_speed_cap omission and are not certified as collision-free.'};
          console.log('PASS: dense turn sweep - 101 samples, fixed follower, 82 two-body SAT checks, 19 explicit unavailable-motion cases, cold/reverse seeks');
        } finally {sweepReplay.destroy();}
      }
      if(fixture.time===29695) {
        const location=(time,id)=>frames.find(row=>row.time===time).markers.find(m=>m.vehicle.endsWith(id)).position;
        const leaderJump=distance(location(29694.999,'_006'),location(29695,'_006'));
        const followerJump=distance(location(29695.999999,'_007'),location(29696,'_007'));
        assert.ok(leaderJump<.02,'leader must remain continuous when its occupancy domain changes: '+leaderJump);
        assert.ok(followerJump<.0001,'follower must remain continuous at release from the zero-distance gateway: '+followerJump);
        evidence.continuity={leader_transition_m:leaderJump,follower_release_m:followerJump};
        console.log('PASS: leader domain transition and follower gateway release remain continuous');
      }
      assert.equal(hash(fixture),before,'fixture including native source and motion plans remains unchanged');
      evidence.cases.push({name:spec.name,fixture:spec.file,fixture_sha256:crypto.createHash('sha256').update(fs.readFileSync(spec.file)).digest('hex'),
        requested_gap_m:.1,also_checked_default_gap_m:2,continuous_playback:continuousSamples,
        independent_sat: {projection: 'common local metric frame at network bounding-box latitude',
          latitude_degrees: projectionLatitude(fixture), tolerance_m: 0.000001},
        boundary_continuity: boundaryContinuity,
        turn_sweep: turnSweep,
        frames:frames.map(frame=>({time:frame.time,actors:frame.markers.length,comparable_gap_m:frame.comparable_gap_m,
          poses:frame.markers.map(m=>({vehicle:m.vehicle,position:m.position,heading:m.Visual_Body_Heading_Degrees,
            domain:m.Visual_Occupancy_Domain,source:m.Visual_Queue_Source}))})),independent_body_contacts:0,source_unchanged:true});
    } finally {warm.destroy();}
  }
  assert.deepEqual(fingerprint(),evidence.source_sha256,'production files remain unchanged during the verification');
  evidence.status='passed';evidence.command='node python/test_simz1_corridor_boundary.cjs';
  if(process.env.SIMZ1_BOUNDARY_EVIDENCE)fs.writeFileSync(process.env.SIMZ1_BOUNDARY_EVIDENCE,JSON.stringify(evidence,null,2)+'\n');
  console.log('PASS: corridor boundary regression - ' + evidence.cases.length + ' causal fixtures, '+evidence.cases.reduce((sum,row)=>sum+row.frames.length,0)+' ordered samples plus cold/reverse seeks');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
