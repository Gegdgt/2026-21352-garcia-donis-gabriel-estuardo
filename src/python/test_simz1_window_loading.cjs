// Pure loader/preparation fixtures. No server, browser, files from runs or timers at simulation speed.
'use strict';
const assert=require('node:assert/strict'),Loader=require('./simz1_continuous_loader.js');
const {Worker:Thread}=require('node:worker_threads'),{resolveObjectURL}=require('node:buffer');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const identity={run_id:'window-fixture',iteration:0,run_manifest_sha256:'a'.repeat(64),source_version:'b'.repeat(64)};
function setup(extra={},hooks={}) {
  const requests=[],activations=[];
  const loader=new Loader({...identity,start_seconds:0,end_seconds:86400,window_seconds:120,window_count:720,
    window_endpoint:'/window',cache_bytes:1000,cache_hard_bytes:30000,worker:false,...extra},
    {onWindow:(payload,prepared)=>activations.push({payload,prepared}),...hooks});
  global.fetch=(url,options)=>new Promise(resolve=>requests.push({index:Number(new URL(url,'http://local').searchParams.get('index')),options,resolve}));
  const payload=index=>({...identity,index,start_seconds:index*120,end_seconds:(index+1)*120,padding:'x'.repeat(2000),
    segments:[{vehicle:'v',Agent_ID:'p',Link_ID:'road',Replay_Journey_Key:'trip',timestamps:[28070,28110],
      path:[[0,0],[.001,0]],Motion_Plan:{version:1,status:'constant',distance_m:40,phases:[[28070,28110,0,1,0]]}}],
    trips:{trip:{Trip_ID:'t',Departure:28070,Arrival:28110}},signal_replay:{series:[]},lane_replay:{events:[]}});
  const request=index=>requests.findLast(r=>r.index===index && !r.replied);
  function reply(index,override={}) {
    const r=request(index);assert.ok(r,'pending '+index);r.replied=true;
    const text=JSON.stringify({...payload(index),...override});
    r.resolve({ok:true,status:200,headers:{get:key=>key==='X-SimZ1-JSON-Bytes' ? String(Buffer.byteLength(text)) : null},
      arrayBuffer:async()=>new TextEncoder().encode(text).buffer,text:async()=>text});
  }
  return {loader,requests,activations,payload,reply,request};
}
// Execute the actual generated worker source on a Node thread, with a minimal
// browser messaging adapter. No browser or HTTP service is involved.
class FixtureWorker {
  constructor(url) {
    this.ready=resolveObjectURL(url).text().then(source=>{
      if(this.terminated)return;
      this.thread=new Thread(`const {parentPort}=require('node:worker_threads');
        globalThis.self={postMessage:data=>parentPort.postMessage(data)};
        ${source}
        parentPort.on('message',data=>self.onmessage({data}));`,{eval:true});
      this.thread.on('message',data=>this.onmessage?.({data}));
      this.thread.on('error',error=>this.onerror?.({message:error.message}));
    });
  }
  postMessage(data,transfer){this.ready.then(()=>this.thread?.postMessage(data,transfer));}
  terminate(){this.terminated=true;this.thread?.terminate();}
}
const originalFetch=global.fetch,originalWorker=global.Worker;
(async()=>{
  const eager=setup();eager.loader.requestTime(28079);
  assert.deepEqual(eager.requests.map(row=>row.index),[233,234],'unspecified option preserves eager successor prefetch');
  eager.loader.destroy();

  let releaseRequiredPreparation;
  const demanded=setup({prefetch_after_ready:true},{preparePayload:()=>new Promise(resolve=>{releaseRequiredPreparation=resolve;})});
  demanded.loader.requestTime(28079);
  assert.deepEqual(demanded.requests.map(row=>row.index),[233],'required window owns the cold query slot');
  demanded.reply(233);await flush();
  assert.equal(demanded.loader.activeIndex,null,'a response is not ready until runtime preparation finishes');
  assert.equal(demanded.request(234),undefined,'no speculative fetch while required preparation remains pending');
  releaseRequiredPreparation();await flush();
  assert.equal(demanded.loader.activeIndex,233);
  assert.ok(demanded.request(234),'prepared active window may prefetch its successor');
  demanded.loader.destroy();

  let playing=false;
  const playback=setup({prefetch_after_ready:true},{canPrefetch:()=>playing});
  playback.loader.requestTime(28079,{seek:true});playback.reply(233);await flush();
  assert.equal(playback.loader.activeIndex,233);
  assert.equal(playback.request(234),undefined,'paused seek has no speculative query after readiness');
  for(let i=0;i<3;i++)playback.loader.requestTime(28079.5,{seek:true});
  assert.equal(playback.requests.length,1,'repeated paused seeks reuse only the mandatory window');
  playing=true;
  assert.equal(playback.loader.requestTime(28079.75),true);
  assert.ok(playback.request(234),'playback resumes successor prefetch on the active window');
  playing=false;playback.reply(234);await flush();
  assert.equal(playback.loader.requestTime(28080,{seek:true}),true,'pausing does not discard a completed useful prefetch');
  assert.equal(playback.request(235),undefined,'paused activation does not chain speculation');
  playback.loader.destroy();
  console.log('PASS: optional ready-first prefetch waits for preparation; pause suppresses speculation and playback resumes it; eager default stays compatible');

  for(const source_version of [undefined,'c'.repeat(64)]) {
    const mismatch=setup();mismatch.loader.requestTime(0);
    mismatch.reply(0,{source_version});await flush();
    assert.equal(mismatch.loader.activeIndex,null,'same run/iteration cannot accept an incompatible source version');
    assert.equal(mismatch.loader.cache.size,0);assert.equal(mismatch.loader.metrics.errors,1);
    mismatch.loader.destroy();
  }
  const obsolete=setup();obsolete.loader.requestTime(0);obsolete.loader.destroy();
  const replacement=setup({source_version:'c'.repeat(64)});replacement.loader.requestTime(0);
  replacement.reply(0,{source_version:'c'.repeat(64)});await flush();
  obsolete.reply(0);await flush();
  assert.equal(obsolete.activations.length,0,'late response from a destroyed session cannot activate');
  assert.equal(replacement.activations.at(-1).payload.source_version,'c'.repeat(64));
  assert.equal(replacement.loader.cache.size,1,'replacement cache only contains its own source');
  replacement.loader.destroy();
  const ready=setup();ready.loader.requestTime(28079,{seek:true});
  assert.ok(ready.request(234),'07:48 successor starts before current response completes');
  ready.reply(233);await flush();const active=ready.activations.at(-1);
  assert.equal(ready.loader.activeIndex,233);ready.reply(234);await flush();
  assert.equal(ready.loader.cache.size,2,'large pair survives the former fixed budget');
  assert.ok(ready.loader.maxBytes>ready.loader.baseBytes);assert.ok(ready.loader.maxBytes<=ready.loader.hardBytes);
  const n=ready.requests.length;
  assert.equal(ready.loader.requestTime(28080),true);assert.equal(ready.loader.requestTime(28081),true);
  assert.equal(ready.requests.filter(r=>r.index===234).length,1);assert.ok(ready.requests.length<=n+1);
  const next=ready.activations.at(-1);
  assert.deepEqual(next.payload.segments,active.payload.segments,'window crossing does not clip/resample a native record');
  assert.equal(next.prepared.timelines.get('v')[0],next.payload.segments[0],'all prepared indexes share record identities');
  assert.equal(next.prepared.transitionTimelines.get('v')[0],next.payload.segments[0]);
  assert.equal(next.prepared.intervalIndex.byStart[0],next.payload.segments[0]);
  assert.equal(ready.loader.snapshot().prefetchHits,1);
  assert.equal(ready.loader.requestTime(28079,{seek:true}),true,'reverse seek reuses retained previous window when it fits');
  ready.loader.destroy();

  const slow=setup();slow.loader.requestTime(28079);slow.reply(233);await flush();
  assert.equal(slow.loader.requestTime(28080),false);assert.equal(slow.loader.activeIndex,233);
  slow.reply(234);await flush();assert.equal(slow.loader.activeIndex,234);
  assert.ok(slow.loader.samples.every(s=>['headersMs','bodyReadAndBrowserDecompressMs','parseMs','validateMs','prepareMs','runtimePreparationMs'].every(k=>Number.isFinite(s[k]))));
  slow.loader.destroy();

  // Hard limit is distinct from the adaptive floor. Do not repeatedly download
  // a successor known to exceed it; keep the active native window intact.
  const hard=setup({cache_hard_bytes:3000});hard.loader.requestTime(28079);hard.reply(233);await flush();hard.reply(234);await flush();
  assert.equal(hard.loader.activeIndex,233);assert.equal(hard.loader.cache.size,1);
  assert.equal(hard.loader.prefetchBlocked.reason,'pair_exceeds_hard_limit');
  const before=hard.requests.length;for(let i=0;i<10;i++)hard.loader.requestTime(28079.5);
  assert.equal(hard.requests.length,before,'no prefetch eviction/reload loop');
  hard.loader.requestTime(28080);hard.reply(234);await flush();assert.equal(hard.loader.activeIndex,234);hard.loader.destroy();

  const oversized=setup({cache_hard_bytes:3000});oversized.loader.requestTime(28079);
  oversized.reply(233,{padding:'x'.repeat(12000)});await flush();
  assert.equal(oversized.loader.activeIndex,233,'a mandatory window is never truncated to fit the cache');
  assert.ok(oversized.loader.retainedBytes>oversized.loader.hardBytes);
  assert.equal(oversized.loader.snapshot().hardLimitException,'single_required_window');
  assert.equal(oversized.activations[0].payload.segments.length,1);oversized.loader.destroy();

  let release,preparing;
  const stale=setup({}, {preparePayload:(payload)=>payload.index===236 ? new Promise(resolve=>{release=resolve;preparing=true;}) : undefined});
  stale.loader.requestTime(28079);stale.reply(233);await flush();
  stale.loader.requestTime(28320,{seek:true});stale.reply(236);await flush();assert.equal(preparing,true);
  stale.loader.requestTime(28079,{seek:true});release();await flush();
  assert.equal(stale.loader.activeIndex,233,'late preparation cannot override a more recent seek');
  assert.ok(!stale.activations.some(a=>a.payload.index===236));stale.loader.destroy();

  const bad=setup();bad.loader.requestTime(28079);bad.reply(233,{run_id:'other-run'});await flush();
  assert.equal(bad.loader.activeIndex,null);assert.equal(bad.activations.length,0);bad.loader.destroy();

  global.Worker=FixtureWorker;
  const threaded=setup({worker:true});
  try {
    threaded.loader.requestTime(28079);threaded.reply(233);
    const deadline=Date.now()+10000;
    while(threaded.loader.activeIndex==null && !threaded.loader.metrics.errors && Date.now()<deadline)
      await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(threaded.loader.activeIndex,233,'actual worker must publish the requested native window');
    const {payload,prepared}=threaded.activations[0];
    assert.equal(threaded.loader.samples[0].mode,'worker');
    assert.equal(prepared.timelines.get('v')[0],payload.segments[0],'structured clone retains aliases across payload and indexes');
    assert.deepEqual(payload.segments[0].timestamps,[28070,28110]);
    assert.equal(payload.run_id,identity.run_id);
  } finally {threaded.loader.destroy();}
  console.log('PASS: 07:47:59/07:48:00/07:48:01, adaptive bounded cache, prepared indexes, stale seeks and identity');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{global.fetch=originalFetch;global.Worker=originalWorker;});
