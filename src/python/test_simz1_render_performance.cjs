// Correctness/operation-count regressions, not timing assertions. No browser/HTTP.
'use strict';
const assert=require('node:assert/strict'),{loadFixture}=require('./simz1_render_fixtures.cjs');
const positions=h=>JSON.stringify(h.api.layers.find(l=>l.id==='trips').props.data.map(m=>[m.vehicle,m.position,m.Visual_Body_Heading_Degrees]));
(async()=>{
  const {h,fixture}=await loadFixture(30,'dense'),native=JSON.stringify(fixture.payload);
  const roads=h.api.layers.find(l=>l.id==='roads'),trips=h.api.layers.find(l=>l.id==='trips'),before=positions(h);
  h.api.resetRenderMetrics();h.api.seek(31);h.api.seek(32);
  const perf=h.api.getRenderPerformance(),frame=perf.frames.at(-1);
  assert.equal(positions(h),before);assert.equal(h.api.getState().visibleMarkers,30);
  assert.equal(h.api.layers.find(l=>l.id==='roads'),roads,'static layer identity retained');
  assert.equal(h.api.layers.find(l=>l.id==='trips'),trips,'stationary rows do not invalidate GPU attributes');
  assert.equal(perf.counters.tripLayerUpdates,0);assert.ok(frame.queueProfile.anchorCacheHit);
  assert.equal(frame.queueProfile.finalMarkerReuses,30);assert.ok(frame.allocations.markerReuses>=30);
  assert.ok(frame.queueProfile.overlapCalls>0,'safety collisions remain enabled even when GPU data is reused');
  assert.ok(Object.values(frame.stages).every(Number.isFinite));
  const diagnostic=h.api.getVisualDiagnostics();
  assert.ok(diagnostic.collisions.length>0);assert.equal(diagnostic.counts.unresolvedOverlaps,0);
  assert.equal(diagnostic.collisions.length,Math.min(100,diagnostic.counts.overlapsDetected),'default evidence expansion is bounded');
  assert.equal(diagnostic.collision_sample.total_pairs,diagnostic.counts.overlapsDetected,'all detected pairs remain counted');
  assert.ok(diagnostic.collisions.every(row=>row.time===32 && row.vehicles.every(v=>v.vehicle_id)));
  const builds=perf.counters.labelBuilds,deck=h.sandbox.deckInstance,updates=deck.updates;
  h.evaluate('render();render()');assert.equal(deck.updates,updates,'repeated pause frame does not submit identical layers');
  assert.equal(h.api.getRenderPerformance().counters.labelBuilds,builds);
  deck.props.onViewStateChange({viewState:{...deck.props.viewState,bearing:30}});
  assert.equal(h.api.getRenderPerformance().counters.labelBuilds,builds+1,'camera invalidates labels only');
  assert.equal(positions(h),before);
  h.api.seek(60);assert.equal(h.evaluate('signalStateAt("s","g",current)'),'GREEN');
  h.api.seek(59.9);assert.equal(h.evaluate('signalStateAt("s","g",current)'),'RED');
  assert.throws(()=>h.api.setQueueGap(0));assert.equal(positions(h),before,'invalid gap cannot mutate the active setting');
  h.api.setQueueGap(3);assert.notEqual(positions(h),before,'envelope change invalidates cached anchors');
  h.api.setQueueGap(2);assert.equal(positions(h),before);assert.equal(JSON.stringify(fixture.payload),native);

  // Compare the scalar SAT with the previous oriented-rectangle formulation.
  h.evaluate(`function referenceSAT(a,b,gap=0){const p=visualLaneRenderer.projection,
    d=[(b.position[0]-a.position[0])*p.xScale,(b.position[1]-a.position[1])*p.yScale],
    axes=o=>{const r=o.heading*Math.PI/180;return [[Math.cos(r),Math.sin(r)],[-Math.sin(r),Math.cos(r)]];},
    aa=axes(a),bb=axes(b),dot=(u,v)=>u[0]*v[0]+u[1]*v[1],
    radius=(o,basis,axis)=>Math.abs(dot(basis[0],axis))*(o.length_m+gap)/2+Math.abs(dot(basis[1],axis))*o.width_m/2;
    return [...aa,...bb].every(axis=>Math.abs(dot(d,axis))<radius(a,aa,axis)+radius(b,bb,axis)-1e-7);}
    for(let i=0;i<2000;i++){const a={position:[0,0],heading:i*17.13,length_m:4.5,width_m:1.8},
      b={position:[Math.sin(i)*.0001,Math.cos(i*7)*.0001],heading:i*29.7,length_m:4.5,width_m:1.8};
      if(visualQueueRenderer.bodiesOverlap(a,b,2)!==referenceSAT(a,b,2))throw new Error('SAT mismatch '+i);
      if(visualQueueRenderer.envelopesOverlap(a,b)!==referenceSAT(visualQueueRenderer.envelope(a),visualQueueRenderer.envelope(b)))
        throw new Error('Envelope SAT mismatch '+i);}`);
  const {h:turn}=await loadFixture(30,'turn');
  turn.api.seek(37.49);const a=JSON.parse(positions(turn));turn.api.seek(37.51);const b=JSON.parse(positions(turn));
  assert.notDeepEqual(a,b,'positions continue through Motion_Plan within a native interval');
  turn.api.seek(37.49);assert.equal(positions(turn),JSON.stringify(a),'reverse seek gives the same rigid poses');
  turn.api.setSpeed(1);turn.api.setRenderRate(30);turn.api.play();turn.frame(0);
  const rendered=turn.api.getRenderPerformance().frames.length;
  turn.frame(10);assert.ok(turn.api.getState().current>37.49,'clock advances independently of drawing cadence');
  assert.equal(turn.api.getRenderPerformance().frames.length,rendered);
  turn.frame(40);assert.ok(turn.api.getRenderPerformance().frames.length>rendered);
  assert.equal(turn.api.getState().visibleMarkers,30);
  // An immediate seek also resets the draw interval, independently of 1x/120x.
  // Sampled frames evaluate the absolute trajectory time, never accumulated poses.
  for(const speed of [1,120]) {
    turn.api.pause();turn.api.setSpeed(speed);turn.api.seek(37.49);turn.api.play();
    let frames=turn.api.getRenderPerformance().frames.length;
    const wall=turn.evaluate('performance.now()');
    turn.frame(wall+10);
    assert.equal(turn.api.getRenderPerformance().frames.length,frames);
    assert.ok(Math.abs(turn.api.getState().current-(37.49+.01*speed))<1e-10);
    turn.api.seek(37.51);frames=turn.api.getRenderPerformance().frames.length;
    turn.frame(wall+40);
    assert.equal(turn.api.getRenderPerformance().frames.length,frames,'seek draw restarts cadence');
    turn.frame(wall+50);
    assert.equal(turn.api.getRenderPerformance().frames.length,frames+1);
    const time=turn.api.getState().current,drawn=positions(turn);
    assert.ok(Math.abs(time-(37.51+.04*speed))<1e-10);
    turn.api.pause();turn.api.seek(time);assert.equal(positions(turn),drawn,'RAF and direct seek use identical native instants');
  }
  // Warm caches and a cold queue evaluation must preserve full marker metadata,
  // FIFO output, safety diagnostics and the immutable source trajectories.
  for(const viewer of [h,turn]) {
    viewer.api.pause();
    const source='continuousReplay.cache.get(continuousReplay.activeIndex).payload.segments';
    const native=viewer.evaluate(`JSON.stringify(${source})`);
    const capture=()=>JSON.parse(JSON.stringify({markers:viewer.api.layers.find(l=>l.id==='trips').props.data,
      diagnostics:viewer.api.getVisualDiagnostics()}));
    for(const time of [19.99,20,37.49,37.51,114.999,115,30]) {
      viewer.api.seek(time);
      const expected=viewer.evaluate(`${source}.filter(r=>r.timestamps[0]<=current && current<r.timestamps[1])`);
      const warm=capture();
      assert.equal(viewer.api.getState().activeAgents,new Set(expected.map(r=>r.Agent_ID)).size);
      assert.deepEqual(warm.markers.map(m=>m.vehicle).sort(),Array.from(expected,r=>r.vehicle).sort());
      viewer.evaluate('visualQueueRenderer.configure({});lastMarkerTime=null;render()');
      assert.deepEqual(capture(),warm,'warm/cold parity at '+time);
      assert.equal(viewer.evaluate(`JSON.stringify(${source})`),native);
    }
  }
  console.log('PASS: SAT parity, retained safety/identities, hold caches, GPU invalidation, labels, signals, seek, continuous motion and independent draw cadence');
})().catch(error=>{console.error(error);process.exitCode=1;});
