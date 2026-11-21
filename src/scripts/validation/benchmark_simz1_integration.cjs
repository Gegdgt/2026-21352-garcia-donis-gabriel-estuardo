// User-run CPU fixtures only. Report never claims measured WebGL/GPU FPS.
'use strict';
const fs=require('node:fs'),path=require('node:path'),{performance}=require('node:perf_hooks');
const {loadFixture}=require('../../python/simz1_render_fixtures.cjs');
const args=process.argv.slice(2),option=(key,fallback)=>{const i=args.indexOf(key);return i<0 ? fallback : args[i+1];};
const output=option('--output',null),frames=Number(option('--frames','30'));
if(!output || !Number.isInteger(frames) || frames<5 || frames>300)throw new Error('Explicit --output and --frames 5..300 required');
const destination=path.resolve(output),parent=path.dirname(destination);
if(!fs.statSync(parent).isDirectory() || fs.existsSync(destination))throw new Error('Existing parent and NEW report required');
const space=fs.statfsSync(parent);if(space.bavail*space.bsize<64*1024*1024)throw new Error('Less than 64 MiB free');
const summary=values=>{const sorted=[...values].sort((a,b)=>a-b);return {samples:sorted.length,
  p50:sorted[Math.floor(sorted.length*.5)],p95:sorted[Math.floor(sorted.length*.95)],max:sorted.at(-1)};};
const report={status:'running',schema:'simz1-integration-benchmark-v1',scope:'Synthetic CPU; mock Deck/DOM; no measured WebGL FPS',
  node:process.version,cases:[],featurePolicy:'All queues, spacing checks and vehicles enabled; B=N/5 is an explicit synthetic benchmark assumption, not observed.'};
(async()=>{
  for(const count of [100,1000])for(const mode of ['dense','turn'])for(const busEvery of [0,6])for(const speed of [1,120]) {
    const buses=busEvery ? count/5 : 0,total=count+buses;
    const {h,fixture}=await loadFixture(total,mode,{busEvery}),native=JSON.stringify(fixture.payload);
    h.setHudPopulation(count);await h.api.reloadHud();
    h.sandbox.performance.now=()=>performance.now();
    h.api.pause();h.api.setSpeed(speed);h.api.resetRenderMetrics();global.gc?.();
    const before=process.memoryUsage(),durations=[],samples=[];
    // Same simulated interval at both rates; real-frame density differs, as in playback.
    for(let i=0;i<frames;i++) {
      const time=30+30*i/frames,tick=performance.now();h.api.seek(time);
      durations.push(performance.now()-tick);samples.push(h.api.getPerformance().frames.at(-1));
      const state=h.api.getState();
      if(state.visibleMarkers!==total || state.activeAgents!==count || state.activePublicVehicles!==buses ||
         state.hud.data.counts.persons_generated!==count)throw new Error('Fixture omitted vehicles or mixed N and B');
    }
    h.api.seek(30);h.api.seek(59);h.api.seek(30); // reverse seeks must retain identical identities.
    const previous=h.api.getState().current;h.api.seek(121);
    if(!h.api.getState().buffering || h.api.getState().current!==previous)throw new Error('Buffering did not hold the clock');
    const closeStarted=performance.now();h.api.clearSelection();h.evaluate('continuousReplay.destroy()');
    const closeLoaderMs=performance.now()-closeStarted;
    const closed=h.api.getPerformance().loader;
    if(closed.cachedWindows || closed.pendingRequests || closed.retainedBytes)throw new Error('Loader retained owned resources after destroy');
    if(JSON.stringify(fixture.payload)!==native)throw new Error('Fixture timestamps or source mutated');
    global.gc?.();const after=process.memoryUsage();
    report.cases.push({roadPersons:count,publicB:buses,totalVehicles:total,mode,busEvery,speed,wallStepEquivalentMs:30/frames/speed*1000,
      seekAndRenderCpuMs:summary(durations),samples,heapBefore:before.heapUsed,heapAfter:after.heapUsed,
      retainedHeapDelta:after.heapUsed-before.heapUsed,heapNote:'Viewer harness still referenced; loader resources only are closed.',
      gcAvailable:Boolean(global.gc),closeLoaderMs,closed,
      staticFeatures:'Measure real enabled stops/signals separately with the existing-tab harness; mock Deck has no GPU.'});
  }
  report.status='complete';
})().catch(error=>{report.status='failed';report.error=error.stack;process.exitCode=1;}).finally(()=>{
  fs.writeFileSync(destination,JSON.stringify(report,null,2),{flag:'wx'});console.log(destination);
});
