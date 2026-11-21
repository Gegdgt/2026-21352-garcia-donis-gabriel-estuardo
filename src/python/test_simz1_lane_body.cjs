'use strict';
// Recorded V7 regressions through the production loader and renderer. The
// historical browser poses are a negative control; coordinates remain estimates.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const {harness}=require('./test_simz1_continuous_replay.cjs');
const plain=value=>JSON.parse(JSON.stringify(value));
const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const key=row=>JSON.stringify([row.vehicle,row.Replay_Journey_Key,row.Link_ID,row.timestamps]);
const metre=6371008.8*Math.PI/180;
const distance=(a,b)=>Math.hypot((a[0]-b[0])*metre*Math.cos((a[1]+b[1])*Math.PI/360),(a[1]-b[1])*metre);
const body=m=>({position:m.position,heading:m.Visual_Body_Heading_Degrees,
  length:m.Visual_Body_Length_Meters,width:m.Visual_Body_Width_Meters});

// Independent SAT. Only length receives the requested 0.10 m longitudinal
// envelope; a separate renderer warning can retain its additional lateral gap.
function separatingGap(a,b,longitudinalGap=0) {
  const origin=a.position,scale=metre*Math.cos((a.position[1]+b.position[1])*Math.PI/360);
  const polygon=row=>{
    const angle=row.heading*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
    const x=(row.position[0]-origin[0])*scale,y=(row.position[1]-origin[1])*metre;
    return [[-1,-1],[-1,1],[1,1],[1,-1]].map(([i,j])=>{
      const along=i*(row.length+longitudinalGap)/2,side=j*row.width/2;
      return [x+along*c-side*s,y+along*s+side*c];
    });
  };
  const left=polygon(a),right=polygon(b);let separation=-Infinity;
  for(const points of [left,right])for(let i=0;i<4;i++) {
    const next=points[(i+1)%4],dx=next[0]-points[i][0],dy=next[1]-points[i][1],norm=Math.hypot(dx,dy);
    const project=p=>(-dy*p[0]+dx*p[1])/norm,aa=left.map(project),bb=right.map(project);
    separation=Math.max(separation,Math.min(...aa)-Math.max(...bb),Math.min(...bb)-Math.max(...aa));
  }
  return separation;
}
const protectedRecord=row=>Object.fromEntries(['vehicle','Agent_ID','Replay_Journey_Key','Link_ID','timestamps',
  'Native_Occupancy','Native_Occupancy_Progress','Boundary_Provenance','Observed_Waits','Motion_Plan'].map(k=>[k,row[k]]));
const specs=[
  {name:'opposed_carriageways',start:34334,end:34339.5,critical:[34335,34336,34337,34337.5,34339],
    continuous:34336,expectedWarning:false},
  {name:'turning_bus',start:72879,end:72884.5,critical:[72880,72881,72883],
    continuous:72881,expectedWarning:true}
];
const sources=['simz1_visual_lanes.js','simz1_visual_queues.js','simz1_continuous_loader.js','visualizador_z1_controls.js'];
const fingerprint=()=>Object.fromEntries(sources.map(name=>[name,
  crypto.createHash('sha256').update(fs.readFileSync('python/'+name)).digest('hex')]));
const evidence={scope:'Two recorded V7 actor pairs; dense local intervals, reverse/cold seek and continuous playback, not a full-day audit',
  source_sha256:fingerprint(),cases:[]};

function setup(fixture,reverse=false) {
  const rows=plain(fixture.records);if(reverse)rows.reverse();
  const trips=plain(fixture.trips),keys=rows.map(key),metadata=plain(fixture.visual_lanes);
  const replay=harness({},metadata);
  const payload={segments:rows,trips,context_segments:[],lane_replay:plain(fixture.lane_replay),signal_replay:{series:[]},
    queue_context:{schema_version:1,policy:'native-hold-closure-v1',segments:rows,transition_segments:rows,trips,lane_events:[],
      by_seed:Object.fromEntries(keys.map(k=>[k,{complete:true,reason:null,record_keys:keys}]))}};
  const sourceHash=hash(payload),metadataHash=hash(metadata);
  replay.reply(0,{...payload,segments:[]});replay.api.setQueueGap(.1);
  async function at(time,seek=true) {
    if(seek)replay.api.seek(time);
    const index=Math.floor(time/120);if(replay.request(index))replay.reply(index,payload);
    for(let turn=0;turn<160;turn++) {
      // The bounded loader yields through zero-delay timers for >48 records.
      for(const [id,timer] of replay.timers)if(timer.delay===0){replay.timers.delete(id);timer.fn();}
      await new Promise(resolve=>setImmediate(resolve));
      if(turn>=4 && !replay.api.getState().buffering)break;
    }
    assert.equal(replay.api.getState().buffering,false,'fixture prepared before assertions');
    assert.ok(Math.abs(replay.api.getRenderPerformance().displayedTime-time)<1e-8,
      'inspect the requested rendered frame '+time+' (actual '+replay.api.getRenderPerformance().displayedTime+')');
    const markers=plain(replay.evaluate("layers.find(layer=>layer.id==='trips').props.data"));
    const diagnostics=replay.api.getVisualDiagnostics(time),summary=plain(diagnostics.summarizeCollisions());
    const expected=[...new Set(rows.filter(r=>r.timestamps[0]<=time && time<r.timestamps[1]).map(r=>r.vehicle))].sort();
    assert.deepEqual(expected,fixture.expected_vehicles,'both fixture actors are active');
    assert.deepEqual(markers.map(m=>m.vehicle).sort(),expected,'no omission conceals contact');
    assert.equal(diagnostics.counts.omitted,0);
    assert.equal(diagnostics.counts.incompleteHoldContext,0,'complete supplied hold closure');
    assert.equal(summary.unresolved_body_overlap,0,'production agrees that physical bodies do not touch');
    const gap=separatingGap(...markers.map(body),.1);
    assert.ok(gap>=-1e-6,'independent SAT preserves the 0.10 m longitudinal envelope at '+time+': '+gap);
    for(const marker of markers) {
      const source=rows.find(r=>key(r)===key(marker));
      assert.deepEqual(protectedRecord(marker),protectedRecord(source),'native evidence and motion are preserved');
      assert.equal(marker.Visual_Body_Length_Meters,13.5);
      assert.equal(marker.Visual_Body_Width_Meters,2.5);
      assert.equal(marker.Visual_Body_Clipped,false);
      assert.equal(marker.Visual_Occupancy_Position_Observed,false);
      assert.ok(['estimated_front_anchored_recorded_lane_chord','estimated_rear_across_recorded_transition'].includes(marker.Visual_Body_Support),
        'body has explicit reconstructed-pose provenance at '+time);
      const reconstruction=marker.Visual_Body_Reconstruction;
      assert.equal(reconstruction.source,'front_anchored_recorded_lane_chord_v1');
      assert.equal(reconstruction.positions_observed,false);
      assert.equal(reconstruction.dimensions_preserved,true);
      assert.deepEqual(reconstruction.front_position,marker.Visual_Body_Path[1]);
      assert.deepEqual(reconstruction.rear_position,marker.Visual_Body_Path[0]);
      assert.ok(reconstruction.source_parts.length>0);
      for(const part of reconstruction.source_parts) {
        assert.ok(metadata.links[part.link_id],'source link comes from effective metadata');
        assert.ok(Number.isSafeInteger(part.slot) && part.slot>=0 && part.slot<metadata.links[part.link_id].num_lanes);
      }
      assert.ok(Math.abs(distance(...marker.Visual_Body_Path)-13.5)<.001,'whole body keeps physical length');
      if(marker.Visual_Queue_Holding)assert.ok(marker.Visual_Queue_Stop_Clearance_Meters>=-1e-6,'held front stays before conflict boundary');
    }
    assert.equal(hash(payload),sourceHash,'source payload including original paths is immutable');
    assert.equal(hash(metadata),metadataHash,'lane count and width metadata are immutable');
    return {time,markers,summary,longitudinal_envelope_separation_m:gap};
  }
  return {at,replay,destroy(){replay.evaluate('continuousReplay.destroy()');}};
}
function equalPose(a,b) {
  for(const marker of a.markers) {
    const other=b.markers.find(m=>m.vehicle===marker.vehicle);
    assert.ok(distance(marker.position,other.position)<1e-5,'cold/reverse seek gives the same centre');
    assert.ok(Math.abs(marker.Visual_Body_Heading_Degrees-other.Visual_Body_Heading_Degrees)<1e-6);
    assert.deepEqual(marker.Visual_Body_Reconstruction,other.Visual_Body_Reconstruction);
  }
}

(async()=>{
  for(const spec of specs) {
    const file='python/fixtures/simz1_lane_body_'+spec.name+'.json';
    const fixture=JSON.parse(fs.readFileSync(file,'utf8'));
    assert.ok(separatingGap(...fixture.historical_bad_bodies)<0,'negative control detects original browser body contact');
    const times=new Set();
    for(let time=spec.start;time<=spec.end+1e-7;time+=.1)times.add(Number(time.toFixed(1)));
    for(const time of spec.critical)for(const delta of [-.000001,0,.000001])times.add(time+delta);
    const ordered=[...times].sort((a,b)=>a-b),instance=setup(fixture),frames=[];
    for(const time of ordered)frames.push(await instance.at(time));
    for(const frame of [...frames].reverse())equalPose(frame,await instance.at(frame.time));
    for(const time of spec.critical) {
      const cold=setup(fixture,true);equalPose(frames.find(f=>f.time===time),await cold.at(time));cold.destroy();
      const current=await instance.at(time);
      for(const marker of current.markers) {
        const trace=plain(instance.replay.evaluate(`(()=>{
          const row=layers.find(layer=>layer.id==='trips').props.data.find(row=>row.vehicle===${JSON.stringify(marker.vehicle)});
          return visualLaneRenderer.occupancyFrontPath(visualLaneRenderer.occupancy(row),row.Visual_Queue_Center_Meters,
            row.Visual_Queue_Center_Meters,row.Visual_Body_Length_Meters,
            {current:row,resolve:transitionNeighbors,...transitionNeighbors(row)});
        })()`));
        assert.ok(trace,'the conservative front-path helper supports the drawn pose');
        assert.equal(trace.source,'estimated_recorded_lane_front_path_v1');
        assert.equal(trace.positions_observed,false);
        assert.equal(trace.path.length,1);
        assert.ok(distance(trace.path[0],marker.Visual_Body_Path[1])<1e-5,'helper uses exactly the same reconstructed front');
      }
    }
    if(spec.name==='opposed_carriageways') {
      await instance.at(34336);
      const traces=plain(instance.replay.evaluate(`(()=>{
        const row=layers.find(layer=>layer.id==='trips').props.data.find(row=>row.vehicle==='ptbus_transmetro_L12_011'),
          occupancy=visualLaneRenderer.occupancy(row),neighbors={current:row,resolve:transitionNeighbors,...transitionNeighbors(row)};
        const estimated={...row,Native_Occupancy:null,Visual_Lane_Source:'estimated',Visual_Lane_Index:0};
        return {forward:visualLaneRenderer.occupancyFrontPath(occupancy,-10,2,13.5,neighbors),
          reverse:visualLaneRenderer.occupancyFrontPath(occupancy,2,-10,13.5,neighbors),
          outside:visualLaneRenderer.occupancyFrontPath(occupancy,1e6,1e6+1,13.5,neighbors),
          estimated_multilane_part:visualLaneRenderer.occupancyPathPart(estimated)};
      })()`));
      assert.ok(traces.forward.path.length>=5,'span includes offset-join vertices, not only its endpoints');
      assert.ok(traces.forward.stations_m.some(station=>Math.abs(station)<1e-7),'native junction is included');
      assert.deepEqual(traces.reverse.path,[...traces.forward.path].reverse());
      assert.deepEqual(traces.reverse.stations_m,[...traces.forward.stations_m].reverse());
      assert.equal(traces.outside,null,'unsupported geometry cannot silently extrapolate a front path');
      assert.equal(traces.estimated_multilane_part,null,'estimated hash-selected lane is not reported as native proof');
    }
    const before=frames.find(f=>f.time===spec.continuous-.000001),at=frames.find(f=>f.time===spec.continuous),
      after=frames.find(f=>f.time===spec.continuous+.000001);
    const continuity=[];
    for(const marker of at.markers) {
      const prior=before.markers.find(m=>m.vehicle===marker.vehicle),next=after.markers.find(m=>m.vehicle===marker.vehicle);
      const jump=Math.max(distance(prior.position,marker.position),distance(marker.position,next.position));
      const frontJump=Math.max(distance(prior.Visual_Body_Path[1],marker.Visual_Body_Path[1]),
        distance(marker.Visual_Body_Path[1],next.Visual_Body_Path[1]));
      assert.ok(jump<.001 && frontJump<.001,'continuous centre and estimated front across native link transition');
      continuity.push({vehicle:marker.vehicle,maximum_center_step_m:jump,maximum_front_step_m:frontJump});
    }
    for(const speed of [1,120]) {
      const playback=setup(fixture);
      await playback.at(spec.start);playback.replay.api.setSpeed(speed);playback.replay.api.play();
      for(let step=speed===120 ? 2 : 1;step<=5;step+=speed===120 ? 2 : 1) {
        playback.replay.frame(step*1000/speed);
        const current=await playback.at(spec.start+step,false);
        equalPose(frames.find(f=>f.time===current.time),current);
      }
      playback.replay.api.pause();playback.destroy();
    }
    const warnings=frames.filter(f=>f.summary.unresolved_safety_envelope_only>0).map(f=>f.time);
    if(spec.expectedWarning)assert.ok(warnings.includes(72881),'additional lateral-envelope warning stays visible');
    const connectors=plain(instance.replay.evaluate('visualLaneRenderer.connectors()'));
    if(spec.name==='opposed_carriageways') {
      const join=connectors.find(c=>c.Link_ID==='osm_64387809_7_forward' && c.To_Link_ID==='osm_60237259_0_forward' &&
        c.source==='recorded_native_slot_pair_estimated_lane_join');
      assert.ok(join,'native slots support a visible, documented local lane connector');
      assert.equal(join.positions_observed,false);
      assert.equal(join.width_m,3*.82,'decorative road width is not changed');
      assert.ok(join.before_span_m<=join.endpoint_separation_m && join.after_span_m<=join.endpoint_separation_m);
    }
    evidence.cases.push({fixture:file,fixture_sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),
      samples:frames.length,minimum_longitudinal_envelope_separating_axis_m:Math.min(...frames.map(f=>f.longitudinal_envelope_separation_m)),
      physical_body_contacts:0,longitudinal_0_10_m_contacts:0,additional_lateral_envelope_warning_times:warnings,continuity,
      critical_frames:spec.critical.map(time=>{const frame=frames.find(f=>f.time===time);return {time,summary:frame.summary,
        longitudinal_envelope_separation_m:frame.longitudinal_envelope_separation_m,
        bodies:frame.markers.map(m=>({vehicle:m.vehicle,...body(m),reconstruction:m.Visual_Body_Reconstruction}))};})});
    instance.destroy();console.log('PASS: '+spec.name+' — '+frames.length+' samples, physical bodies, 0.10 m longitudinal gap, source traceability, reverse/cold seek and playback');
  }
  assert.deepEqual(fingerprint(),evidence.source_sha256,'production sources stayed stable during this suite');
  evidence.status='passed';
  if(process.env.SIMZ1_LANE_BODY_EVIDENCE)fs.writeFileSync(process.env.SIMZ1_LANE_BODY_EVIDENCE,JSON.stringify(evidence,null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
