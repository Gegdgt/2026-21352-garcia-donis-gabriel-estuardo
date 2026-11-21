// Actual Chrome/Edge + WebGL checks. Node 22, no npm dependencies, no DOM stubs.
// Usage: node scripts/validation/check_simz1_transit_browser.cjs URL output-directory native-samples.json
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const base = process.argv[2] || 'http://127.0.0.1:8792';
const samples = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const project = path.resolve(__dirname, '../..');
const outputArgument = process.argv[3];
const out = path.resolve(outputArgument || path.join(project, 'runtime', 'validation',
  'continuous-browser-' + Date.now() + '-' + require('node:crypto').randomUUID()));
const executable = process.env.SIMZ1_BROWSER || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
].find(p => fs.existsSync(p));
if (!executable) throw new Error('No Chrome/Edge executable available');
fs.mkdirSync(out, {recursive:true});
const profile = path.join(project, 'runtime', 'replay', 'browser-profile-' + require('node:crypto').randomUUID());
fs.mkdirSync(profile, {recursive:true});
const browser = spawn(executable, ['--headless=new', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--window-size=1440,960', '--force-device-scale-factor=1',
  '--remote-debugging-port=0', '--user-data-dir='+profile, 'about:blank'], {windowsHide:true});
const sleep = ms => new Promise(resolve => setTimeout(resolve,ms));
let ws, nextId=0, session, stderr='', failures=[];
const pending = new Map(), events=[];
const report = {browser_executable:executable,real_browser:true,dom_stubs:false,
  headless:true,viewport:[1440,960],base,checks:[],errors:[],samples:[],console:[],failedRequests:[],httpErrors:[],requests:[]};
browser.stderr.on('data',d=>{stderr+=d;});
browser.on('error',e=>{failures.push(e.message);});
async function command(method,params={},sessionId=session) {
  const id=++nextId;
  const result=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},60000);
    pending.set(id,{resolve,reject,timer});
  });
  ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
  return result;
}
async function evaluate(expression,awaitPromise=true) {
  const r=await command('Runtime.evaluate',{expression,awaitPromise,returnByValue:true});
  if(r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function until(expression,timeout=45000) {
  const start=Date.now();
  while(Date.now()-start<timeout) {const result=await evaluate(expression);if(result)return result;await sleep(100);}
  throw new Error('Timed out: '+expression);
}
function check(name,actual,expected=true) {assert.deepEqual(actual,expected,name);report.checks.push({name,pass:true});}
async function state() {return evaluate('simz1Continuous.getState()');}
async function seek(time) {
  const expected = Math.max(0,Math.min(86400,time));
  await evaluate(`simz1Continuous.pause(); simz1Continuous.seek(${time});`);
  await until(`(()=>{const s=simz1Continuous.getState();return !s.buffering && Math.abs(s.current-${expected})<.01})()`);
  return state();
}
async function capture(name) {
  const image=await command('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(image.data,'base64'));
}
async function marker(sample) {
  return evaluate(`(()=>{const m=simz1Continuous.layers.find(l=>l.id==='trips').props.data.find(m=>m.vehicle===${JSON.stringify(sample.vehicle)});
    return m?{vehicle:m.vehicle,position:m.position,bodyLength:m.Visual_Body_Length_Meters,bodyWidth:m.Visual_Body_Width_Meters,
      family:m.Vehicle_Family,trip:m.Trip,opacity:m.Visual_Body_Opacity,queueOpacity:m.Visual_Queue_Opacity,
      key:m.Replay_Journey_Key,diagnostic:simz1Continuous.diagnoseVehicle(m.vehicle)}:null;})()`);
}
async function inspectVehicle(name,sample) {
  await seek(sample.time);let m=await marker(sample);
  check(name+': native vehicle is rendered',!!m && m.opacity!==0 && m.queueOpacity!==0);
  check(name+': correct expedition/trip',m.key,sample.key);
  await evaluate(`simz1Continuous.clearSelection();simz1Continuous.deck.setProps({viewState:{longitude:${m.position[0]},latitude:${m.position[1]},zoom:19,pitch:0,bearing:0}})`);
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const point=await evaluate(`(()=>{const m=simz1Continuous.layers.find(l=>l.id==='trips').props.data.find(m=>m.vehicle===${JSON.stringify(sample.vehicle)}),
    v=simz1Continuous.deck.getViewports()[0],p=v.project(m.position),r=simz1Continuous.deck.getCanvas().getBoundingClientRect();
    return {x:r.left+p[0],y:r.top+p[1]};})()`);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',...point,buttons:0});
  await until(`!document.getElementById('simz1-vehicle-card').hidden && document.getElementById('simz1-vehicle-card').textContent.includes(${JSON.stringify(sample.vehicle)})`);
  check(name+': hover does not pin selection',(await state()).selectedKey,null);
  await command('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',buttons:1,clickCount:1});
  await command('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',buttons:0,clickCount:1});
  await until('simz1Continuous.getState().selectedJourneyStatus === "complete"');
  const selected=await state();
  const fields=selected.vehicleCard.fields;
  check(name+': card has six fields',Object.keys(fields).length,6);
  check(name+': six fields displayed in DOM',await evaluate("document.querySelectorAll('#simz1-vehicle-card dt').length"),6);
  check(name+': native pointer selected correct vehicle',selected.selectedVehicleId,sample.vehicle);
  check(name+': complete selected route',selected.selectedRecords>0);
  const route=await evaluate("simz1Continuous.layers.filter(l=>['selected-history','selected-future'].includes(l.id)).map(l=>({id:l.id,records:l.props.data.length}))");
  check(name+': route layers populated',route.some(l=>l.records>0));
  report.samples.push({kind:name,...sample,marker:m,selected,fields,route,pointer:point});
  await capture(name+'-selected');
  return m;
}
async function main() {
  const started=Date.now();
  while(!/DevTools listening on (ws:\/\/\S+)/.test(stderr)) {
    if(failures.length || Date.now()-started>20000)throw new Error('Browser start failed: '+stderr+failures.join(','));
    await sleep(100);
  }
  ws=new WebSocket(stderr.match(/DevTools listening on (ws:\/\/\S+)/)[1]);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  const requestUrls=new Map();
  ws.onmessage=message=>{
    const data=JSON.parse(message.data);
    if(data.id){const p=pending.get(data.id);if(!p)return;clearTimeout(p.timer);pending.delete(data.id);data.error?p.reject(new Error(JSON.stringify(data.error))):p.resolve(data.result);return;}
    events.push(data);
    if(data.method==='Runtime.exceptionThrown')report.errors.push(data.params.exceptionDetails);
    if(data.method==='Runtime.consoleAPICalled')report.console.push(data.params);
    if(data.method==='Network.requestWillBeSent'){requestUrls.set(data.params.requestId,data.params.request.url);report.requests.push(data.params.request.url);}
    if(data.method==='Network.loadingFailed')report.failedRequests.push({...data.params,url:requestUrls.get(data.params.requestId)});
    if(data.method==='Network.responseReceived'&&data.params.response.status>=400)report.httpErrors.push(data.params.response);
  };
  report.version=await command('Browser.getVersion',{},null);
  const target=await command('Target.createTarget',{url:'about:blank'},null);
  session=(await command('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
  await command('Page.navigate',{url:base+'/index.html'});
  await until('!!window.simz1Continuous',60000);
  await until('!simz1Continuous.getState().buffering && simz1Continuous.getState().hud?.status==="ready"',60000);
  report.initial=await state();
  report.webgl=await evaluate(`(()=>{const gl=document.querySelector('canvas').getContext('webgl2');if(!gl)return null;
    const d=gl.getExtension('WEBGL_debug_renderer_info');return {version:gl.getParameter(gl.VERSION),renderer:d?gl.getParameter(d.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),context_lost:gl.isContextLost()}})()`);
  check('Real WebGL context',!!report.webgl&&!report.webgl.context_lost);
  check('Correct native run identity',report.initial.run_id,samples.run_id);
  check('Private persons independent of services',report.initial.hud.data.counts.persons_generated,samples.private_persons ?? 100);
  check('120 separate public buses',report.initial.hud.data.public_transport.configured.public_transport_vehicles_configured,120);
  if(samples.freight) {
    check('Independent freight HUD fleet',report.initial.hud.data.freight_transport.configured.vehicles_configured,samples.freight_configured);
    check('Observed freight HUD fleet',report.initial.hud.data.freight_transport.observed.vehicles_observed,samples.freight_configured);
    const freight=await inspectVehicle('freight',samples.freight);
    check('Freight public-size length',freight.bodyLength,12);
    check('Freight public-size width',freight.bodyWidth,2.5);
    check('Freight visible type',await evaluate('simz1Continuous.getState().vehicleCard.fields.type'),'Transporte pesado');
    report.freight=freight;
  }
  check('Road geometry rendered',await evaluate("simz1Continuous.layers.find(l=>l.id==='roads').props.data.length>0"));
  report.api=await evaluate(`(async()=>{const config=await (await fetch('/api/config',{cache:'no-store'})).json(),i=config.continuous;
    const q=new URLSearchParams({run_id:i.run_id,iteration:i.iteration,run_manifest_sha256:i.run_manifest_sha256});
    const hud=await (await fetch('/api/hud?'+q+'&start_seconds=0&end_seconds=86400')).json();
    const window=await (await fetch('/api/window?'+q+'&index='+Math.floor(${samples.bus.time}/i.window_seconds))).json();
    const journey=await (await fetch('/api/journey?'+q+'&key='+encodeURIComponent(${JSON.stringify(samples.bus.key)}))).json();
    return {identity:i,hud,window:{run_id:window.run_id,iteration:window.iteration,run_manifest_sha256:window.run_manifest_sha256,segments:window.segments?.length},journey:{run_id:journey.run_id,key:journey.key,records:journey.records?.length}};})()`);
  for(const k of ['hud','window','journey'])check('/api/'+k+' identity',report.api[k].run_id,samples.run_id);
  check('/api/journey native key',report.api.journey.key,samples.bus.key);
  await seek(0);check('No active fleet before service',(await state()).activePublicVehicles,0);await capture('midnight');
  const car=await inspectVehicle('car',samples.car),moto=await inspectVehicle('moto',samples.moto),bus=await inspectVehicle('bus',samples.bus);
  report.occupancy=await evaluate(`(()=>{const d=simz1Continuous.getVisualDiagnostics(${samples.bus.time});return {
    counts:d.counts,collision_summary:d.collision_summary,records:d.records.filter(r=>r.vehicle_id===${JSON.stringify(samples.bus.vehicle)})};})()`);
  if(samples.bus.stop.is_blocking_lane) {
    const stopBody=report.occupancy.records[0];
    check('Blocking bus has supported spacing',stopBody.spacing_compatible,true);
    check('Complete bus front before estimated stop line',stopBody.stop_clearance_m>=-1e-7);
    check('Facility footprint declares estimated position',stopBody.facility_footprint_projection.continuous_position_observed,false);
  }
  check('Subminimum gap rejected without state mutation',await evaluate(`(()=>{const before=simz1Continuous.getVisualDiagnostics().records.map(r=>r.position);try{simz1Continuous.setQueueGap(0);return false;}catch(e){return JSON.stringify(before)===JSON.stringify(simz1Continuous.getVisualDiagnostics().records.map(r=>r.position));}})()`));
  check('Rendered dimensions bus > car > moto',bus.bodyLength>car.bodyLength && car.bodyLength>moto.bodyLength);
  report.stops=await evaluate(`(()=>{const l=simz1Continuous.layers.find(l=>l.id==='transit-stop-signs');return {count:l.props.data.length,
    green:l.props.data.filter(r=>r.icon.startsWith('green')).length,blue:l.props.data.filter(r=>r.icon.startsWith('blue')).length,
    valid:l.props.data.every(r=>r.display_cluster || r.icon.startsWith(r.services.every(s=>s.system==='transmetro')?'green':r.services.every(s=>s.system!=='transmetro')?'blue':'mixed'))};})()`);
  check('Green Transmetro and blue other buses',report.stops.green>0&&report.stops.blue>0&&report.stops.valid);
  // The atlas is a GPU resource after loading. Its actual rendered colors
  // are checked in the saved PNG, not by assuming it stays a URL in props.
  check('Stationary native stop state',bus.diagnostic.service_state.state,'stop');
  await seek(samples.bus.time+1);const dwell=await marker(samples.bus);check('Dwell retains position',dwell.position,bus.position);
  await seek(samples.bus.move_time);const continued=await marker(samples.bus);
  check('Bus continues after native departure',!!continued&&continued.key===bus.key&&JSON.stringify(continued.position)!==JSON.stringify(bus.position));
  await capture('bus-after-stop');
  await seek(samples.bus.arrival+1);check('Bus does not extend outside domain',await marker(samples.bus),null);
  await seek(samples.bus.time);check('Reverse seek restores stop position',(await marker(samples.bus)).position,bus.position);
  const paused=(await state()).current;await sleep(200);check('Pause retains clock',(await state()).current,paused);
  report.playback=[];
  for(const speed of [1,120]){
    const t=speed===120?Math.floor(samples.bus.time/120)*120+119:samples.bus.time;
    await seek(t);await evaluate(`simz1Continuous.setSpeed(${speed});simz1Continuous.play()`);
    const before=await state(),wall=Date.now();await sleep(speed===1?1200:1800);await evaluate('simz1Continuous.pause()');const after=await state(),elapsed=(Date.now()-wall)/1000;
    report.playback.push({speed,before,after,elapsed});check(speed+'x advances time',after.current>before.current);
    if(speed===1)check('1x wall-clock rate',Math.abs(after.current-before.current-elapsed)<.5);
    else check('120x crosses time window',Math.floor(after.current/120)>Math.floor(before.current/120));
  }
  await seek(86399);check('No active fleet after service',(await state()).activePublicVehicles,0);
  await seek(samples.bus.time);await capture('final-stop');
  check('No JavaScript exceptions',report.errors.length,0);
  check('No console errors',report.console.filter(e=>e.type==='error').length,0);
  // The server intentionally denies files outside its static allowlist.
  // Keep the browser's optional favicon probe in the evidence, separately
  // from assets/API failures that would prevent the viewer from operating.
  report.nonBlockingHttpErrors=report.httpErrors.filter(r=>new URL(r.url).pathname==='/favicon.ico');
  check('No failed application/API HTTP responses',report.httpErrors.length-report.nonBlockingHttpErrors.length,0);
  check('No unexpected network failures',report.failedRequests.filter(e=>!e.canceled).length,0);
  report.status='passed';
}
main().catch(async error=>{report.status='failed';report.failure=error.stack;process.exitCode=1;
  try{report.failure_state=await evaluate('({state:window.simz1Continuous?.getState(),body:document.body?.innerText?.slice(0,2000)})');await capture('failure');}catch{}
}).finally(async()=>{
  try{if(ws?.readyState===WebSocket.OPEN)await command('Browser.close',{},null);}catch{}
  ws?.close();browser.kill();
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));
  fs.writeFileSync(path.join(out,'browser-stderr.log'),stderr);
  console.log(JSON.stringify({status:report.status,checks:report.checks.length,failure:report.failure,output:out},null,2));
});
