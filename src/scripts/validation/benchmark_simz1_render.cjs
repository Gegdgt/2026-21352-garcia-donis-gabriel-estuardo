// Explicit CPU benchmark; fake Deck/DOM, real JS timers and V8 allocation samples.
// No HTTP, browser, simulation, SQLite, or protected-run reads. Node 22+.
'use strict';
const fs=require('node:fs'),path=require('node:path'),inspector=require('node:inspector');
const {performance,PerformanceObserver}=require('node:perf_hooks');
const args=process.argv.slice(2),opt=(key,fallback)=>{const i=args.indexOf('--'+key);return i<0 ? fallback : args[i+1];};
process.env.SIMZ1_RENDER_SOURCE_DIR=path.resolve(opt('source','python'));
const {loadFixture}=require('../../python/simz1_render_fixtures.cjs');
const iterations=Number(opt('frames','30')),output=path.resolve(opt('output','runtime/render-benchmark.json'));
if(!Number.isInteger(iterations) || iterations<5)throw new Error('--frames must be an integer >=5');
const gc=[],gcObserver=new PerformanceObserver(list=>{for(const e of list.getEntries())gc.push({time:e.startTime,duration:e.duration,kind:e.detail.kind});});
gcObserver.observe({entryTypes:['gc']});
const session=new inspector.Session();session.connect();
const post=(method,params={})=>new Promise((resolve,reject)=>session.post(method,params,(error,result)=>error ? reject(error) : resolve(result)));
const quantile=(sorted,q)=>sorted[Math.min(sorted.length-1,Math.floor(sorted.length*q))];
const report={source:process.env.SIMZ1_RENDER_SOURCE_DIR,node:process.version,date:new Date().toISOString(),iterations,
  scope:'CPU with simulated Deck/DOM. cpuCapacityFps is NOT presented/WebGL FPS; sampledAllocatedBytes is statistical, heapDelta is net retained memory.',cases:[]};
(async()=>{
  for(const count of [100,1000,3000])for(const mode of ['dense','moving','turn']) {
    const {h,fixture}=await loadFixture(count,mode);
    const native=JSON.stringify(fixture.payload);
    h.sandbox.performance.now=()=>performance.now();
    const operations={
      playback_1x:i=>h.evaluate(`current=${30+i/60};lastMarkerTime=null;render()`),
      repeated_frame:()=>h.evaluate('render()'),
      pause:()=>h.frame(performance.now()),
      camera:i=>h.sandbox.deckInstance.props.onViewStateChange({viewState:{...h.sandbox.deckInstance.props.viewState,bearing:i%2 ? 15 : 0}}),
      seek:i=>h.api.seek(i%2 ? 45 : 30),
      cold_seek:i=>{h.evaluate('visualQueueRenderer.configure({});lastMarkerTime=null');h.api.seek(i%2 ? 45 : 30);},
      signal_boundary:i=>h.api.seek(i%2 ? 60 : 59.99)
    };
    for(const [name,operation] of Object.entries(operations)) {
      h.api.pause();h.api.seek(30);h.api.resetRenderMetrics?.();
      // Warm only one frame; retain the first measured sample as well as p95.
      operation(0);global.gc?.();await new Promise(resolve=>setImmediate(resolve));
      const mem=process.memoryUsage(),start=performance.now(),gcStart=gc.length,durations=[],stages=[];
      await post('HeapProfiler.startSampling',{samplingInterval:32768,includeObjectsCollectedByMajorGC:true,includeObjectsCollectedByMinorGC:true});
      for(let i=0;i<iterations;i++) {
        const tick=performance.now();operation(i+1);durations.push(performance.now()-tick);
        if(name!=='pause' && name!=='camera')stages.push(h.api.getPerformance().frames.at(-1));
        await new Promise(resolve=>setImmediate(resolve));
      }
      const elapsed=performance.now()-start,after=process.memoryUsage();
      const {profile}=await post('HeapProfiler.stopSampling');
      let sampled=0;const sum=node=>{sampled+=node.selfSize;for(const child of node.children || [])sum(child);};sum(profile.head);
      const sorted=[...durations].sort((a,b)=>a-b),mean=durations.reduce((a,b)=>a+b,0)/durations.length;
      if(h.api.getState().visibleMarkers!==count || h.api.getState().activeAgents!==count)
        throw new Error('Fixture lost vehicles: '+[count,mode,name,h.api.getState().visibleMarkers].join('/'));
      report.cases.push({count,mode,operation:name,firstMs:durations[0],meanMs:mean,p50Ms:quantile(sorted,.5),p95Ms:quantile(sorted,.95),maxMs:sorted.at(-1),
        cpuCapacityFps:1000/mean,callsPerWallSecond:iterations/elapsed*1000,sampledAllocatedBytes:sampled,
        heapDelta:after.heapUsed-mem.heapUsed,heapUsed:after.heapUsed,rss:after.rss,
        gc:gc.slice(gcStart),counters:h.api.getRenderPerformance?.().counters || null,stages,
        visible:h.api.getState().visibleMarkers,active:h.api.getState().activeAgents,
        positions:h.api.layers.find(l=>l.id==='trips').props.data.map(m=>[m.vehicle,m.position,m.Visual_Body_Heading_Degrees])});
      if(JSON.stringify(fixture.payload)!==native)throw new Error('Native fixture mutated');
    }
    h.evaluate('continuousReplay.destroy()');
  }
})().catch(error=>{report.error=error.stack;process.exitCode=1;}).finally(()=>{
  gcObserver.disconnect();session.disconnect();fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(output);
});
