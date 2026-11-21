// Run explicitly against an ALREADY RUNNING loopback server. Does not start a
// server, regenerate data or change the run. Launches its own browser only when
// this CLI is executed by the user. Node 22+; no npm dependencies.
// node scripts/validation/measure_continuous_boundary.cjs --label after --output runtime/after.json
'use strict';
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const args=process.argv.slice(2),option=(name,fallback)=>{const i=args.indexOf('--'+name);return i<0 ? fallback : args[i+1];};
const base=option('base','http://localhost:8793'),output=path.resolve(option('output','runtime/simz1-window-measurement.json'));
const start=Number(option('start','28051')),end=Number(option('end','28105')),speed=Number(option('speed','1'));
const timeout=Number(option('timeout','240000')),label=option('label','measurement');
if(![1,120].includes(speed) || !(start<28080 && end>28081))throw new Error('Use speed 1/120 and an interval spanning 07:48:00');
const url=new URL(base);if(!['localhost','127.0.0.1','[::1]'].includes(url.hostname))throw new Error('Loopback only');
const executable=process.env.SIMZ1_BROWSER || ['C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p=>fs.existsSync(p));
if(!executable)throw new Error('Set SIMZ1_BROWSER to Chrome or Edge');
fs.mkdirSync(path.dirname(output),{recursive:true});
const profile=path.resolve('runtime','window-measurement-profile-'+require('node:crypto').randomUUID());
fs.mkdirSync(profile,{recursive:true});
const browser=spawn(executable,['--headless=new','--no-first-run','--no-default-browser-check','--window-size=1440,960',
  '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true});
let ws,session,stderr='',sequence=0;
const pending=new Map(),requests=new Map(),report={label,base,start,end,speed,real_browser:true,
  started_at:new Date().toISOString(),samples:[],network:[],errors:[],completed:false};
browser.stderr.on('data',data=>{stderr+=data;});browser.on('error',error=>report.errors.push(error.message));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function command(method,params={},sessionId=session) {
  const id=++sequence;
  const promise=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout '+method));},Math.min(timeout,90000));
    pending.set(id,{resolve,reject,timer});
  });
  ws.send(JSON.stringify({id,method,params,...(sessionId ? {sessionId} : {})}));return promise;
}
async function evaluate(expression) {
  const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description || JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function waitFor(expression) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){const value=await evaluate(expression);if(value)return value;await sleep(200);}
  throw new Error('Timeout '+expression);
}
(async()=>{
  const deadline=Date.now()+30000;
  while(!/DevTools listening on (ws:\/\/\S+)/.test(stderr) && Date.now()<deadline)await sleep(100);
  const address=stderr.match(/DevTools listening on (ws:\/\/\S+)/)?.[1];if(!address)throw new Error('Browser startup failed: '+stderr);
  ws=new WebSocket(address);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{
    const m=JSON.parse(event.data);
    if(m.id) {
      const p=pending.get(m.id);if(!p)return;clearTimeout(p.timer);pending.delete(m.id);
      if(m.error)p.reject(new Error(JSON.stringify(m.error)));else p.resolve(m.result);return;
    }
    const d=m.params;
    if(m.method==='Network.requestWillBeSent' && d.request.url.includes('/api/window?')) {
      requests.set(d.requestId,{url:d.request.url,index:Number(new URL(d.request.url).searchParams.get('index')),sent:d.timestamp});
    }
    const row=d?.requestId && requests.get(d.requestId);
    if(row && m.method==='Network.responseReceived')Object.assign(row,{status:d.response.status,
      headers:d.response.headers,timing:d.response.timing,headersAt:d.timestamp});
    if(row && m.method==='Network.loadingFinished') {
      Object.assign(row,{finished:d.timestamp,encodedBytes:d.encodedDataLength,httpMs:(d.timestamp-row.sent)*1000});
      report.network.push(row);requests.delete(d.requestId);
    }
    if(row && m.method==='Network.loadingFailed') {
      report.network.push({...row,failed:d.errorText,canceled:d.canceled});requests.delete(d.requestId);
    }
  };
  report.browser=await command('Browser.getVersion',{},null);
  const target=await command('Target.createTarget',{url:'about:blank'},null);
  session=(await command('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
  await command('Page.addScriptToEvaluateOnNewDocument',{source:`window.boundaryLongTasks=[];window.boundaryJsonParses=[];
    const nativeParse=JSON.parse;JSON.parse=function(...args){const t=performance.now(),result=nativeParse.apply(this,args);
      if(result && Array.isArray(result.segments) && Number.isInteger(result.index)) {
        window.boundaryJsonParses.push({index:result.index,parseMs:performance.now()-t,characters:args[0].length});
        if(window.boundaryJsonParses.length>32)window.boundaryJsonParses.shift();
      }return result;};
    if(typeof PerformanceObserver==='function')try{new PerformanceObserver(list=>{
      for(const e of list.getEntries())window.boundaryLongTasks.push({start:e.startTime,duration:e.duration});
      if(window.boundaryLongTasks.length>2000)window.boundaryLongTasks.splice(0,window.boundaryLongTasks.length-2000);
    }).observe({type:'longtask',buffered:true});}catch{}`});
  await command('Page.navigate',{url:base+'/index.html'});
  await waitFor('Boolean(window.simz1Continuous)');
  // Only public APIs are reachable here: loader/controls are lexical variables
  // inside the application's async IIFE, not globals available to CDP evaluate.
  report.config=await evaluate(`fetch('./api/config').then(r=>r.json()).then(c=>({continuous:c.continuous,hud:c.hud}))`);
  await evaluate(`simz1Continuous.pause();simz1Continuous.setSpeed(${speed});simz1Continuous.seek(${start});`);
  await waitFor(`(()=>{const s=simz1Continuous.getState();return !s.buffering && s.current===${start}})()`);
  // Start immediately. Waiting for prefetch here would conceal the reported bug.
  report.play_wall_start=Date.now();await evaluate('simz1Continuous.play()');
  let previous=null;
  const finishBy=Date.now()+timeout;
  while(Date.now()<finishBy) {
    const sample=await evaluate(`(()=>{const s=simz1Continuous.getState();return {current:s.current,speed:s.speed,paused:s.paused,
      buffering:s.buffering,pendingTime:s.pendingTime,visible:s.visibleMarkers,active:s.activeAgents,
      cache:s.cache,error:s.error,now:performance.now()}})()`);
    sample.wall_ms=Date.now()-report.play_wall_start;
    if(previous && sample.current===previous.current && !sample.paused)sample.stalledSinceSampleMs=sample.wall_ms-previous.wall_ms;
    report.samples.push(sample);previous=sample;
    if(sample.current>=end){report.completed=true;break;}
    if(sample.error)throw new Error(sample.error);
    await sleep(250);
  }
  await evaluate('simz1Continuous.pause()');
  report.performance=await evaluate('simz1Continuous.getPerformance?.() || null');
  report.render=await evaluate('simz1Continuous.getRenderPerformance?.() || null');
  report.long_tasks=await evaluate('window.boundaryLongTasks');
  report.main_thread_json_parse=await evaluate('window.boundaryJsonParses');
  report.resources=await evaluate(`performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/window?')).map(r=>({
    url:r.name,duration:r.duration,responseStart:r.responseStart,responseEnd:r.responseEnd,
    encodedBodySize:r.encodedBodySize,decodedBodySize:r.decodedBodySize,transferSize:r.transferSize}))`);
  report.heap=await command('Runtime.getHeapUsage');
  report.server=await evaluate(`fetch('./api/metrics?'+new URLSearchParams({run_id:simz1Continuous.getState().run_id,
    iteration:String(simz1Continuous.getState().iteration),run_manifest_sha256:${JSON.stringify(report.config.continuous.run_manifest_sha256)}})).then(r=>r.json())`);
  const first=report.samples.find(s=>s.current>=28080);
  report.crossing={observed:Boolean(first),first_wall_ms:first?.wall_ms ?? null,
    ideal_wall_ms:(28080-start)/speed*1000,
    lateness_ms:first ? first.wall_ms-(28080-start)/speed*1000 : null,
    note:'Wall measurement includes render stalls and up to 250 ms polling error; no performance result is synthesized.'};
  if(!report.completed)throw new Error('Playback did not reach requested end within timeout');
})().catch(error=>{report.errors.push(error.stack || String(error));process.exitCode=1;}).finally(async()=>{
  report.finished_at=new Date().toISOString();
  fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(output);
  try{if(ws?.readyState===WebSocket.OPEN)await command('Browser.close',{},null);}catch{}
  ws?.close();browser.kill();for(const p of pending.values())clearTimeout(p.timer);
});
