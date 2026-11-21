// Actual Chrome/Edge + WebGL checks. Node 22, no npm dependencies, no DOM stubs.
// Usage: node scripts/validation/check_continuous_browser.cjs http://127.0.0.1:8792 [output-directory] [--baseline]
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const base = process.argv[2] || 'http://127.0.0.1:8792';
const baseline = process.argv.includes('--baseline');
const project = path.resolve(__dirname, '../..');
const outputArgument = process.argv[3] === '--baseline' ? undefined : process.argv[3];
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
  headless:true,viewport:[1440,960],base,checks:[],errors:[],samples:[]};
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
async function inspectVisualLanes(label) {
  const snapshot=await evaluate(`(()=>{
    const state=simz1Continuous.getState(),roads=simz1Continuous.layers.find(layer=>layer.id==='roads'),
      centers=simz1Continuous.layers.find(layer=>layer.id==='visual-lane-centers'),
      trips=simz1Continuous.layers.find(layer=>layer.id==='trips'),markers=trips?.props.data || [],
      overflow=simz1Continuous.layers.find(layer=>layer.id==='queue-overflow');
    const rows=roads?.props.data || [],byLink=new Map();
    for(const row of rows){if(!byLink.has(row.Link_ID))byLink.set(row.Link_ID,[]);byLink.get(row.Link_ID).push(row);}
    const parallel=Array.from(byLink.values()).filter(group=>group.length>1);
    const distinctParallel=parallel.filter(group=>group[0].path.some((point,index)=>index>0&&index<group[0].path.length-1&&
      group.slice(1).some(row=>Math.hypot(point[0]-row.path[index][0],point[1]-row.path[index][1])>1e-12)));
    return {summary:state.visualLanes,visibleMarkers:state.visibleMarkers,
      roads:{type:roads?.constructor.layerName,widthUnits:roads?.props.widthUnits,
        count:rows.length,parallelLinks:parallel.length,distinctParallelLinks:distinctParallel.length,
        valid:rows.every(row=>typeof row.Link_ID==='string'&&
          (Number.isInteger(row.lane_index)&&row.lane_index>=0 || row.lane_index===null&&row.source==='centerline')&&
          Number.isFinite(row.width_m)&&row.width_m>0&&Array.isArray(row.path)&&row.path.length>=2&&row.path.every(point=>point.length>=2&&point.slice(0,2).every(Number.isFinite)))},
      centers:centers ? {type:centers.constructor.layerName,widthUnits:centers.props.widthUnits,
        widthAccessor:typeof centers.props.getWidth,
        validWidths:centers.props.data.every(row=>{const width=centers.props.getWidth(row);
          return Number.isFinite(width)&&width>0&&width<=.12&&width<=row.width_m;}),
        minPixels:centers.props.widthMinPixels,count:centers.props.data.length} : null,
      trips:{type:trips?.constructor.layerName,widthUnits:trips?.props.widthUnits,
        widthAccessor:typeof trips?.props.getWidth,pathAccessor:typeof trips?.props.getPath,
        validBodies:markers.every(marker=>{const width=trips.props.getWidth(marker),body=trips.props.getPath(marker);
          return Number.isFinite(width)&&width>0&&width<=1.8&&width===marker.Visual_Body_Width_Meters&&
            (!Number.isFinite(marker.Visual_Lane_Width_Meters)||width<=marker.Visual_Lane_Width_Meters)&&
            Number.isFinite(marker.Visual_Body_Length_Meters)&&marker.Visual_Body_Length_Meters>=0&&marker.Visual_Body_Length_Meters<=4.5+1e-7&&
            Array.isArray(body)&&body.length>=2&&body.every(point=>Array.isArray(point)&&point.length>=2&&point.slice(0,2).every(Number.isFinite));}),
        validOpacity:markers.every(marker=>{const color=trips.props.getColor(marker),
          alpha=(marker.Visual_Queue_Opacity ?? 1)*(marker.Visual_Body_Opacity ?? 1);
          return Array.isArray(color)&&color.length===4&&color.every(Number.isFinite)&&
            Number.isFinite(alpha)&&alpha>=0&&alpha<=1&&
            color[3]===(alpha>0 ? Math.max(1,Math.round(255*alpha)) : 0);}),
        minPixels:trips?.props.widthMinPixels},
      queues:state.visualQueues,
      overflow:overflow ? {type:overflow.constructor.layerName,rows:overflow.props.data.length,
        valid:overflow.props.data.every(row=>row.queue_overflow===true&&typeof row.Link_ID==='string'&&
          Number.isInteger(row.count)&&row.count>0&&typeof row.reason==='string'&&
          Array.isArray(row.position)&&row.position.length>=2&&row.position.slice(0,2).every(Number.isFinite))} : null,
      provenanceValid:markers.every(marker=>['native','estimated','centerline'].includes(marker.Visual_Lane_Source)&&
        Number.isFinite(marker.Visual_Lane_Offset_Meters)&&
        (marker.Visual_Lane_Source!=='native'||typeof marker.Observed_Queue_ID==='string'&&marker.Observed_Queue_ID.length>0)),
      sourceCounts:Object.fromEntries(['native','estimated','centerline'].map(source=>[source,markers.filter(marker=>marker.Visual_Lane_Source===source).length]))};
  })()`);
  report.visual_lanes=report.visual_lanes || [];report.visual_lanes.push({label,...snapshot});
  check(label+': validated visual lane geometry available',snapshot.summary?.available);
  check(label+': lane geometry has source links',snapshot.summary.links>0);
  check(label+': parallel road paths',snapshot.roads.type,'PathLayer');
  check(label+': road width is in meters',snapshot.roads.widthUnits,'meters');
  check(label+': valid source identity and lane path geometry',snapshot.roads.count>0 && snapshot.roads.valid);
  check(label+': parallel lanes separate between shared endpoints',snapshot.roads.distinctParallelLinks,snapshot.roads.parallelLinks);
  check(label+': rendered lanes match actual road paths',snapshot.summary.renderedLanes,snapshot.roads.count);
  check(label+': lane centers are independent paths',snapshot.centers?.type,'PathLayer');
  check(label+': lane center width is in meters',snapshot.centers.widthUnits,'meters');
  check(label+': lane center width accessor',snapshot.centers.widthAccessor,'function');
  check(label+': lane center widths fit each path',snapshot.centers.validWidths);
  check(label+': lane centers have no pixel enlargement',snapshot.centers.minPixels,0);
  check(label+': center lines match road lanes',snapshot.centers.count,snapshot.roads.count);
  check(label+': vehicle bodies are paths',snapshot.trips.type,'PathLayer');
  check(label+': vehicle body width uses meters',snapshot.trips.widthUnits,'meters');
  check(label+': per-body width accessor',snapshot.trips.widthAccessor,'function');
  check(label+': per-body path accessor',snapshot.trips.pathAccessor,'function');
  check(label+': finite vehicle bodies fit world lane width',snapshot.trips.validBodies);
  check(label+': body transparency follows visual queue state',snapshot.trips.validOpacity);
  check(label+': vehicle bodies have no pixel enlargement',snapshot.trips.minPixels,0);
  check(label+': visual queue layout available',snapshot.queues?.available);
  check(label+': waiting evidence is accounted for',snapshot.queues.positioned+snapshot.queues.overflow+snapshot.queues.unrepresentable,snapshot.queues.waitingEvidence);
  check(label+': queue counters are nonnegative integers',['waitingEvidence','positioned','overflow','unrepresentable','redistributed','unknownPositionWait','bodyUnrepresentable'].every(key=>Number.isInteger(snapshot.queues[key])&&snapshot.queues[key]>=0));
  check(label+': overflow has an explicit warning layer',snapshot.overflow?.type,'TextLayer');
  check(label+': overflow rows retain link, position, count and reason',snapshot.overflow.valid);
  check(label+': marker lane source is explicit',snapshot.provenanceValid);
  check(label+': native marker count matches rendered provenance',snapshot.summary.nativeMarkers,snapshot.sourceCounts.native);
  check(label+': estimated marker count matches rendered provenance',snapshot.summary.estimatedMarkers,snapshot.sourceCounts.estimated);
  check(label+': centerline marker count matches rendered provenance',snapshot.summary.centerlineMarkers,snapshot.sourceCounts.centerline);
  check(label+': lane counters partition visible markers',snapshot.summary.nativeMarkers+snapshot.summary.estimatedMarkers+snapshot.summary.centerlineMarkers,snapshot.visibleMarkers);
}
async function laneMarkerSnapshot() {
  return evaluate(`simz1Continuous.layers.find(layer=>layer.id==='trips').props.data.map(marker=>({
    vehicle:marker.vehicle,link:marker.Link_ID,journey:marker.Replay_Journey_Key,
    lane:marker.Visual_Lane_Index,source:marker.Visual_Lane_Source,offset:marker.Visual_Lane_Offset_Meters,position:marker.position,
    body:marker.Visual_Body_Path,width:marker.Visual_Body_Width_Meters,length:marker.Visual_Body_Length_Meters,
    queue:marker.Visual_Queue_State,queueOffset:marker.Visual_Queue_Offset_Meters,opacity:marker.Visual_Queue_Opacity,
    bodyOpacity:marker.Visual_Body_Opacity
  })).sort((a,b)=>(a.vehicle+'|'+a.link).localeCompare(b.vehicle+'|'+b.link)).slice(0,20)`);
}

async function pointerTarget(pointerType) {
  const offset=pointerType==='touch' ? 14 : 6;
  return evaluate(`(()=>{
    const viewport=simz1Continuous.deck.getViewports()[0],canvas=simz1Continuous.deck.getCanvas(),rect=canvas.getBoundingClientRect();
    if(typeof viewport.project!=='function')throw new Error('Viewport.project is unavailable');
    const markers=simz1Continuous.layers.find(layer=>layer.id==='trips').props.data,points=[],buckets=new Map(),obstacles=[];
    const cell=32,bucket=(x,y)=>Math.floor(x/cell)+','+Math.floor(y/cell);
    for(const marker of markers){
      if(marker.Visual_Queue_Representable===false||marker.Visual_Queue_Opacity===0||marker.Visual_Body_Opacity===0||marker.opacity===0)continue;
      const point=viewport.project(marker.position);
      if(!point.slice(0,2).every(Number.isFinite)||point[0]<0||point[1]<0||point[0]>viewport.width||point[1]>viewport.height)continue;
      const row={marker,x:point[0],y:point[1]};points.push(row);
      const key=bucket(row.x,row.y);if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(row);
    }
    for(const layer of simz1Continuous.layers){
      if(layer.id==='trips'||!layer.props.pickable||!Array.isArray(layer.props.data))continue;
      for(const row of layer.props.data){
        if(row.vehicle)continue;
        const position=typeof layer.props.getPosition==='function' ? layer.props.getPosition(row) : row.position;
        if(!Array.isArray(position))continue;
        const point=viewport.project(position);if(point.slice(0,2).every(Number.isFinite))obstacles.push(point);
      }
    }
    // Keep the target away from icon/overflow picks that intentionally retain GPU selection.
    const stride=Math.max(1,Math.floor(points.length/500));
    for(let index=0;index<points.length;index+=stride){const candidate=points[index];
      for(const angle of [0,Math.PI/2,Math.PI,3*Math.PI/2,Math.PI/4,3*Math.PI/4,5*Math.PI/4,7*Math.PI/4]){
        const x=candidate.x+${offset}*Math.cos(angle),y=candidate.y+${offset}*Math.sin(angle);
        if(x<36||y<36||x>viewport.width-36||y>viewport.height-36||obstacles.some(point=>Math.hypot(point[0]-x,point[1]-y)<36))continue;
        let nearest=null,minimum=Infinity,second=Infinity;
        for(let bx=Math.floor(x/cell)-1;bx<=Math.floor(x/cell)+1;bx++)for(let by=Math.floor(y/cell)-1;by<=Math.floor(y/cell)+1;by++)
          for(const row of buckets.get(bx+','+by)||[]){const distance=Math.hypot(row.x-x,row.y-y);
            if(distance<minimum){second=minimum;minimum=distance;nearest=row;}else second=Math.min(second,distance);}
        if(nearest!==candidate||second-minimum<.25)continue;
        const marker=candidate.marker,trip=marker.Trip;
        if(trip?.Trip_ID==null)continue;
        return {x:rect.left+x,y:rect.top+y,distance:minimum,pointerType:${JSON.stringify(pointerType)},
          expectedKey:JSON.stringify([marker.Agent_ID ?? trip.Person_ID ?? null,['id',trip.Trip_ID]]),
          vehicle:String(marker.vehicle),zoom:viewport.zoom,devicePixelRatio};
      }
    }
    return null;
  })()`);
}

async function inspectRealPointer(label,pointerType='mouse') {
  await evaluate('simz1Continuous.clearSelection()');
  const target=await pointerTarget(pointerType);
  check(label+': current visible vehicle has an unambiguous screen target',!!target);
  check(label+': probe is inside the declared CSS-pixel aperture',target.distance<=(pointerType==='touch'?18:8));
  if(pointerType==='touch')check(label+': touch probe lies outside the mouse aperture',target.distance>8);
  report.pointer_checks=report.pointer_checks || [];report.pointer_checks.push({label,...target});
  if(pointerType==='mouse'){
    await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:target.x,y:target.y,buttons:0,pointerType:'mouse'});
    await until(`document.getElementById('simz1-active-telemetry').textContent.split(String.fromCharCode(10)).includes(${JSON.stringify('Vehiculo: '+target.vehicle)})`);
    check(label+': hover does not pin a selection',(await state()).selectedKey,null);
    await command('Input.dispatchMouseEvent',{type:'mousePressed',x:target.x,y:target.y,button:'left',buttons:1,clickCount:1,pointerType:'mouse'});
    await command('Input.dispatchMouseEvent',{type:'mouseReleased',x:target.x,y:target.y,button:'left',buttons:0,clickCount:1,pointerType:'mouse'});
  }else{
    await command('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
    try{
      await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y,id:1,radiusX:1,radiusY:1,force:1}]});
      await sleep(60);
      await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    }finally{await command('Emulation.setTouchEmulationEnabled',{enabled:false});}
  }
  await until(`simz1Continuous.getState().selectedKey===${JSON.stringify(target.expectedKey)}`);
  check(label+': real pointer selects the nearest current displayed centre',(await state()).selectedKey,target.expectedKey);
  if(pointerType==='touch')await sleep(350); // Prevent the next independent probe becoming a double tap.
  return target;
}

async function inspectPickingViews() {
  const saved=await evaluate(`(()=>{const view=simz1Continuous.deck.getViewports()[0];
    const marker=simz1Continuous.layers.find(layer=>layer.id==='trips').props.data.find(row=>row.Visual_Queue_Opacity!==0&&row.Visual_Body_Opacity!==0&&row.Visual_Queue_Representable!==false&&row.opacity!==0);
    return {view:{longitude:view.longitude,latitude:view.latitude,zoom:view.zoom,pitch:view.pitch,bearing:view.bearing},focus:marker?.position};})()`);
  check('Picking has an actual visible source vehicle',Array.isArray(saved.focus));
  try{
    for(const [zoom,dpr] of [[17,1],[18,2]]){
      await command('Emulation.setDeviceMetricsOverride',{width:1440,height:960,deviceScaleFactor:dpr,mobile:false});
      await evaluate(`(async()=>{simz1Continuous.deck.setProps({initialViewState:{longitude:${saved.focus[0]},latitude:${saved.focus[1]},zoom:${zoom},pitch:0,bearing:0}});await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));})()`);
      await inspectRealPointer('mouse zoom '+zoom+' DPR '+dpr,'mouse');
      await inspectRealPointer('touch zoom '+zoom+' DPR '+dpr,'touch');
    }
  }finally{
    await command('Emulation.setDeviceMetricsOverride',{width:1440,height:960,deviceScaleFactor:1,mobile:false});
    await evaluate(`(async()=>{simz1Continuous.deck.setProps({initialViewState:${JSON.stringify(saved.view)}});await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));})()`);
  }
}

async function inspectQueueGap() {
  const before=await state(),positions=await laneMarkerSnapshot();
  const view=await evaluate('JSON.stringify(simz1Continuous.deck.getViewports().map(v=>({longitude:v.longitude,latitude:v.latitude,zoom:v.zoom,pitch:v.pitch,bearing:v.bearing})))');
  await evaluate(`window.queueNativeSnapshot=new Map(simz1Continuous.layers.find(layer=>layer.id==='trips').props.data.slice(0,64).map(marker=>[
    JSON.stringify([marker.vehicle,marker.Link_ID,...marker.timestamps]),JSON.stringify([marker.timestamps,marker.Movement_End,marker.Speed_kmh,marker.Motion_Plan,marker.Observed_Waits,marker.Boundary_Provenance,marker.Trip])]));`);
  try{
    const gap=before.visualQueues.gap_m<10 ? before.visualQueues.gap_m+1 : before.visualQueues.gap_m-1;
    await evaluate(`simz1Continuous.setQueueGap(${gap})`);
    const after=await state();
    check('Queue gap is configurable',after.visualQueues.gap_m,gap);
    check('Queue gap preserves the clock',after.current,before.current);
    check('Queue gap preserves selection',after.selectedKey,before.selectedKey);
    check('Queue gap preserves the camera',await evaluate('JSON.stringify(simz1Continuous.deck.getViewports().map(v=>({longitude:v.longitude,latitude:v.latitude,zoom:v.zoom,pitch:v.pitch,bearing:v.bearing})))'),view);
    const evidence=await evaluate(`(()=>{let compared=0;for(const marker of simz1Continuous.layers.find(layer=>layer.id==='trips').props.data){
      const key=JSON.stringify([marker.vehicle,marker.Link_ID,...marker.timestamps]);if(!window.queueNativeSnapshot.has(key))continue;compared++;
      if(window.queueNativeSnapshot.get(key)!==JSON.stringify([marker.timestamps,marker.Movement_End,marker.Speed_kmh,marker.Motion_Plan,marker.Observed_Waits,marker.Boundary_Provenance,marker.Trip]))return {compared,equal:false};
    }return {compared,equal:true};})()`);
    check('Queue layout preserves sampled native fields',evidence.compared>0&&evidence.equal);
    await inspectVisualLanes('changed-queue-gap');
  }finally{
    await evaluate(`simz1Continuous.setQueueGap(${before.visualQueues.gap_m});window.queueNativeSnapshot=null;`);
  }
  check('Restoring queue gap restores exact deterministic body positions',await laneMarkerSnapshot(),positions);
}
async function inspectLayout(label,width,height) {
  await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const layout=await evaluate(`(()=>{
    const ids=['deck-container','simz1-controls','simz1-run-panel','simz1-active-telemetry'];
    const rects=Object.fromEntries(ids.map(id=>{const element=document.getElementById(id),r=element.getBoundingClientRect();
      return [id,{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height,visible:getComputedStyle(element).display!=='none'}]}));
    const overlaps=[];for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++){
      const a=rects[ids[i]],b=rects[ids[j]];if(a.visible&&b.visible&&Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1)overlaps.push([ids[i],ids[j]]);
    }
    return {rects,overlaps,viewport:[innerWidth,innerHeight],horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1,
      helpOpen:document.getElementById('simz1-help').open};
  })()`);
  report.layouts=report.layouts || [];report.layouts.push({label,...layout});
  check(label+': separate map and panel cells',layout.overlaps,[]);
  check(label+': usable map',layout.rects['deck-container'].width>=240 && layout.rects['deck-container'].height>=180);
  check(label+': no horizontal overflow',layout.horizontalOverflow,false);
  check(label+': permanent run panel',layout.rects['simz1-run-panel'].visible && layout.rects['simz1-run-panel'].height>0);
  check(label+': help closed by default',layout.helpOpen,false);
  await evaluate('document.getElementById("simz1-help").open=true');
  await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  check(label+': expanded help cannot cover the map',await evaluate(`(()=>{
    const help=document.getElementById('simz1-help').getBoundingClientRect(),controls=document.getElementById('simz1-controls').getBoundingClientRect(),map=document.getElementById('deck-container').getBoundingClientRect();
    return Math.min(help.bottom,controls.bottom)<=map.y+1 && help.height<=innerHeight*.2+1;
  })()`));
  await capture('layout-'+label);
  await evaluate('document.getElementById("simz1-help").open=false');
}
async function frameSample(label,milliseconds) {
  return evaluate(`(async()=>{
    const begin=performance.now(),samples=[],initial=simz1Continuous.getState(),draws=simz1Continuous.deck.metrics?.framesRedrawn; let last=begin,bufferedFrames=0;
    await new Promise(resolve=>{function step(t){samples.push(t-last);last=t;if(simz1Continuous.getState().buffering)bufferedFrames++;if(t-begin>=${milliseconds})resolve();else requestAnimationFrame(step);}requestAnimationFrame(step);});
    samples.sort((a,b)=>a-b);return {label:${JSON.stringify(label)},wall_ms:performance.now()-begin,frames:samples.length,
      raf_p50_ms:samples[Math.floor(samples.length*.5)],raf_p95_ms:samples[Math.floor(samples.length*.95)],
      initial,final:simz1Continuous.getState(),bufferedFrames,deckFramesBefore:draws,deckMetrics:simz1Continuous.deck.metrics,
      heap:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize}:null};
  })()`);
}
async function main() {
  const started=Date.now();
  while(!/DevTools listening on (ws:\/\/\S+)/.test(stderr)) {
    if(failures.length || Date.now()-started>15000) throw new Error('Browser start failed: '+stderr+failures.join(','));
    await sleep(100);
  }
  ws=new WebSocket(stderr.match(/DevTools listening on (ws:\/\/\S+)/)[1]);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=message=>{
    const data=JSON.parse(message.data);
    if(data.id) {const p=pending.get(data.id);if(!p)return;clearTimeout(p.timer);pending.delete(data.id);data.error?p.reject(new Error(JSON.stringify(data.error))):p.resolve(data.result);}
    else {events.push(data);if(data.method==='Runtime.exceptionThrown')report.errors.push(data.params.exceptionDetails);}
  };
  report.version=await command('Browser.getVersion',{},null);
  const target=await command('Target.createTarget',{url:'about:blank'},null);
  session=(await command('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await command('Page.enable');await command('Runtime.enable');await command('Network.enable');await command('Performance.enable');
  const loading=Date.now();
  await command('Page.navigate',{url:baseline?base:base+'/index.html'});
  if(baseline) {
    await until('!!document.querySelector("#simz1-clock")?.textContent',120000);
    report.cold_ready_ms=Date.now()-loading;
    await evaluate(`document.querySelectorAll('button').forEach(b=>{if(b.textContent==='Pausar')b.click()})`);
    report.heap=await command('Runtime.getHeapUsage');
    report.ui=await evaluate(`({clock:document.querySelector('#simz1-clock').textContent,summary:document.querySelector('#simz1-run-summary').textContent,slider:[document.querySelector('#simz1-time-slider').min,document.querySelector('#simz1-time-slider').max]})`);
    report.webgl=await evaluate(`(()=>{const gl=document.querySelector('canvas').getContext('webgl2'),d=gl.getExtension('WEBGL_debug_renderer_info');return {version:gl.getParameter(gl.VERSION),renderer:d?gl.getParameter(d.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}})()`);
    await evaluate(`(()=>{const s=document.querySelector('#simz1-time-slider');s.value=63000;s.dispatchEvent(new Event('input'));document.querySelectorAll('button').forEach(b=>{if(b.textContent==='1x')b.click()});document.querySelectorAll('button').forEach(b=>{if(b.textContent==='Reproducir')b.click()})})()`);
    report.samples.push(await evaluate(`(async()=>{const begin=performance.now(),samples=[],initial=document.querySelector('#simz1-clock').textContent;let last=begin;await new Promise(resolve=>{function step(t){samples.push(t-last);last=t;if(t-begin>=5000)resolve();else requestAnimationFrame(step)}requestAnimationFrame(step)});samples.sort((a,b)=>a-b);return {speed:1,initial,final:document.querySelector('#simz1-clock').textContent,wall_ms:performance.now()-begin,frames:samples.length,raf_p50_ms:samples[Math.floor(samples.length*.5)],raf_p95_ms:samples[Math.floor(samples.length*.95)]}})()`));
    report.metrics=await command('Performance.getMetrics');
    await capture('paged-largest');report.status='baseline-measured';return;
  }
  await until('!!window.simz1Continuous',60000);
  await until('!simz1Continuous.getState().buffering',60000);
  await until('simz1Continuous.getState().hud?.status === "ready"',60000);
  report.hud_source=await evaluate(`(()=>{const source=simz1Continuous.getState().hud.data;
    const query=new URLSearchParams({run_id:source.run_id,iteration:source.iteration,run_manifest_sha256:source.run_manifest_sha256,
      start_seconds:source.replay_window.start_seconds,end_seconds:source.replay_window.end_seconds});
    return fetch('/api/hud?'+query,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('HUD source HTTP '+response.status);return response.json()});})()`);
  report.cold_ready_ms=Date.now()-loading;
  report.initial=await state();
  report.webgl=await evaluate(`(()=>{const c=document.querySelector('canvas');const gl=c?.getContext('webgl2');if(!gl)return null;const d=gl.getExtension('WEBGL_debug_renderer_info');return {version:gl.getParameter(gl.VERSION),renderer:d?gl.getParameter(d.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),vendor:d?gl.getParameter(d.UNMASKED_VENDOR_WEBGL):gl.getParameter(gl.VENDOR),context_lost:gl.isContextLost()}})()`);
  check('Real WebGL context',!!report.webgl&&!report.webgl.context_lost);
  check('Single timeline',await evaluate('document.querySelectorAll("#simz1-time-slider").length'),1);
  check('No block navigation',await evaluate('document.querySelectorAll(".simz1-block-navigation").length'),0);
  check('Global timeline start',await evaluate('Number(document.querySelector("#simz1-time-slider").min)'),0);
  check('Global timeline end',await evaluate('Number(document.querySelector("#simz1-time-slider").max)'),86400);
  check('Mouse selection aperture uses CSS pixels',report.initial.picking.mouseRadiusPixels,8);
  check('Touch selection aperture uses CSS pixels',report.initial.picking.touchRadiusPixels,18);
  report.initial_pause=await seek(0);
  await inspectVisualLanes('day-start');
  check('24h midnight clock',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 00:00:00")'));
  await evaluate('simz1Continuous.setClockFormat("12h")');
  check('12h midnight clock',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 12:00:00 AM")'));
  await evaluate('simz1Continuous.setClockFormat("24h")');
  check('Negative seek clamps to day start',(await seek(-1)).current,0);
  check('Exactly seven permanent run rows',await evaluate('document.querySelectorAll("#simz1-run-panel dt").length'),7);
  for(const field of ['persons_generated','planned_trips','completed_trips','pending_censored_trips','reconstructed_vehicles']) {
    const expected=report.hud_source.counts[field];
    check('HUD value matches validated source: '+field,await evaluate(`document.getElementById('simz1-count-${field}').textContent`),
      expected==null ? '—' : String(expected));
  }
  check('HUD run identity',await evaluate('document.getElementById("simz1-count-run_id").textContent'),report.hud_source.run_id);
  check('HUD iteration',await evaluate('document.getElementById("simz1-count-iteration").textContent'),String(report.hud_source.iteration));
  check('Clock total comes from verified persons',await evaluate(`document.getElementById('simz1-clock').textContent.includes('Personas totales ${report.hud_source.counts.persons_generated}')`));
  for(const [time,label] of [[540,'00:09:00'],[43740,'12:09:00'],[86340,'23:59:00'],[86400,'24:00:00']]) {
    await seek(time);check('Clock at '+label,await evaluate(`document.getElementById('simz1-clock').textContent.startsWith('Hora simulada ${label}')`));
    const before=await state();await sleep(150);const afterPause=await state();
    check('Paused clock retained at '+label,afterPause.current,before.current);
    check('HUD source retained through seek '+label,afterPause.hud.data.run_id,report.hud_source.run_id);
    check('Clock visible markers at '+label,await evaluate(`document.getElementById('simz1-clock').textContent.includes('Visibles ${afterPause.visibleMarkers} |')`));
  }
  for(const dimensions of [[1440,960],[760,800],[375,740]]) await inspectLayout(dimensions.join('x'),...dimensions);
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:960,deviceScaleFactor:1,mobile:false});
  await seek(0);
  await capture('continuous-initial');
  await evaluate('window.originalDeck=simz1Continuous.deck;window.originalRoads=simz1Continuous.layers.find(l=>l.id==="roads");void 0');
  await until('simz1Continuous.getState().cache.cachedIndices.includes(1)');
  await evaluate('simz1Continuous.setSpeed(120);simz1Continuous.play()');
  report.samples.push(await frameSample('ready-120x',500));
  await evaluate('simz1Continuous.pause()');
  const fast=report.samples.at(-1);
  check('120x wall-clock rate when data is ready',Math.abs((fast.final.current-fast.initial.current)-120*fast.wall_ms/1000)<10);
  check('Ready 120x sample has no buffering',fast.bufferedFrames,0);
  const denseStarted=Date.now();report.dense=await seek(63000);report.dense_seek_ms=Date.now()-denseStarted;
  check('Source run identity',report.dense.run_id,report.hud_source.run_id);
  await inspectVisualLanes('dense-paused');
  const lanePositions=await laneMarkerSnapshot();
  await sleep(150);
  check('Paused lane positions remain deterministic',await laneMarkerSnapshot(),lanePositions);
  await seek(63001);await seek(63000);
  check('Reverse seek restores lane offsets and positions',await laneMarkerSnapshot(),lanePositions);
  await inspectPickingViews();
  await inspectQueueGap();
  report.heap_dense=await command('Runtime.getHeapUsage');
  await evaluate('simz1Continuous.setSpeed(1);simz1Continuous.play()');
  report.samples.push(await frameSample('dense-1x',5000));
  await evaluate('simz1Continuous.pause()');
  const one=report.samples.at(-1);check('1x wall-clock rate',Math.abs((one.final.current-one.initial.current)-one.wall_ms/1000)<.5);
  await seek(63119);
  await inspectRealPointer('real click before internal window boundary');
  await until('simz1Continuous.getState().selectedJourneyStatus === "complete"');
  const selected=await state();report.selected=selected;
  await evaluate(`(async()=>{simz1Continuous.deck.setProps({initialViewState:{longitude:-90.516,latitude:14.64,zoom:14,pitch:20,bearing:15}});await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));window.savedCamera=JSON.stringify(simz1Continuous.deck.getViewports().map(v=>({longitude:v.longitude,latitude:v.latitude,zoom:v.zoom,pitch:v.pitch,bearing:v.bearing})))})()`);
  await evaluate('simz1Continuous.setSpeed(120);simz1Continuous.play()');
  report.samples.push(await frameSample('dense-120x-across-windows',6000));
  await evaluate('simz1Continuous.pause()');
  const after=await state();
  check('Automatic window crossing',after.current>63120);
  check('Selection identity survives',after.selectedKey,selected.selectedKey);
  check('Complete route retained',after.selectedRecords,selected.selectedRecords);
  await inspectVisualLanes('after-window-crossing');
  check('Deck initialized once',await evaluate('simz1Continuous.deck===window.originalDeck'));
  check('Fixed roads retained',await evaluate('simz1Continuous.layers.find(l=>l.id==="roads")===window.originalRoads'));
  check('Camera retained across windows',await evaluate('JSON.stringify(simz1Continuous.deck.getViewports().map(v=>({longitude:v.longitude,latitude:v.latitude,zoom:v.zoom,pitch:v.pitch,bearing:v.bearing})))===window.savedCamera'));
  await seek(63119);check('Reverse seek retains journey',(await state()).selectedKey,selected.selectedKey);
  await inspectRealPointer('real click after window crossing and reverse seek');
  await inspectLayout('375x740-selected',375,740);
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:960,deviceScaleFactor:1,mobile:false});
  await capture('continuous-selected');
  await seek(86399);
  check('Last second in 24h format',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 23:59:59")'));
  await evaluate('simz1Continuous.setClockFormat("12h")');
  check('Last second in 12h format',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 11:59:59 PM")'));
  await evaluate('simz1Continuous.setClockFormat("24h");simz1Continuous.setSpeed(120);simz1Continuous.play()');
  report.samples.push(await frameSample('midnight-120x',1000));
  await until('!simz1Continuous.getState().buffering && simz1Continuous.getState().current===86400');
  report.terminal=await state();
  check('Day closes at exactly 86400',report.terminal.current,86400);
  check('24:00 endpoint pauses automatically',report.terminal.paused);
  check('24:00 closes the day',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 24:00:00 |")'));
  await evaluate('simz1Continuous.setClockFormat("12h")');
  check('12h format preserves day closing label',await evaluate('document.querySelector("#simz1-clock").textContent.startsWith("Hora simulada 24:00:00 |")'));
  await evaluate('simz1Continuous.setClockFormat("24h")');
  check('Seek beyond day clamps to closing tick',(await seek(90000)).current,86400);
  await seek(0);check('Backward seek to midnight',(await state()).current,0);
  // Use a genuine local HTTP400 response for one demanded request, then retry.
  await evaluate(`window.realFetch=window.fetch;window.failedOnce=false;window.fetch=(url,options)=>{if(!window.failedOnce && String(url).includes('/api/window')){window.failedOnce=true;const u=new URL(url,location.href);u.searchParams.set('index','-1');return window.realFetch(u,options)}return window.realFetch(url,options)};simz1Continuous.seek(43200)`);
  await until('!!simz1Continuous.getState().error');
  report.http_error=await state();check('HTTP failure freezes time',report.http_error.current,0);
  await evaluate('window.fetch=window.realFetch;simz1Continuous.retry()');await until('!simz1Continuous.getState().buffering');
  check('HTTP retry succeeds',(await state()).current,43200);
  await evaluate(`window.realFetch=window.fetch;window.fetch=(url,options)=>String(url).includes('/api/hud')?window.realFetch('/api/window?index=-1',options):window.realFetch(url,options);simz1Continuous.reloadHud()`);
  await until('simz1Continuous.getState().hud.status === "error"');
  check('HUD API error is visible',await evaluate('!!document.getElementById("simz1-run-error").textContent'));
  check('Permanent HUD remains present after API error',await evaluate('getComputedStyle(document.getElementById("simz1-run-panel")).display !== "none"'));
  check('Failed HUD does not reuse stale totals',await evaluate('Array.from(document.querySelectorAll("#simz1-run-panel dd")).every(node=>node.textContent==="—")'));
  check('Failed HUD clock exposes unavailable total',await evaluate('document.getElementById("simz1-clock").textContent.includes("Personas totales —")'));
  await evaluate('window.fetch=window.realFetch;simz1Continuous.reloadHud()');
  await until('simz1Continuous.getState().hud.status === "ready"');
  check('HUD API retry restores verified identity',(await state()).hud.data.run_id,report.hud_source.run_id);
  // Rapid seeks must cancel irrelevant requests and never apply a stale response.
  await evaluate('simz1Continuous.seek(10000);simz1Continuous.seek(70000);simz1Continuous.seek(24000)');
  await until('!simz1Continuous.getState().buffering && simz1Continuous.getState().current===24000');
  check('Obsolete requests cancelled',(await state()).cache.aborted>0);
  await evaluate('simz1Continuous.clearSelection()');check('Selection clears',(await state()).selectedKey,null);
  report.memory=[];
  for(const t of [0,21600,43200,63000,86400,86399,36000,63000,0]) {
    await seek(t);await command('HeapProfiler.collectGarbage');
    const s=await state();report.memory.push({time:t,heap:await command('Runtime.getHeapUsage'),cache:s.cache});
    check('Bounded window cache at '+t,s.cache.cachedWindows<=3);
    check('Bounded retained response bytes at '+t,s.cache.retainedBytes<=s.cache.cacheByteBudget || s.cache.oversizedActiveWindow);
    check('Bounded pending requests at '+t,s.cache.pendingRequests<=2);
  }
  report.navigation_count=events.filter(e=>e.method==='Page.frameNavigated'&&!e.params.frame.parentId).length;
  check('No page reload',report.navigation_count,1);
  check('No JavaScript exceptions',report.errors.length,0);
  report.status='passed';
}
main().catch(async error=>{report.status='failed';report.failure=error.stack;process.exitCode=1;
  try {report.failure_state=await evaluate('({state:window.simz1Continuous?.getState(),load:document.getElementById("load-status")?.textContent,body:document.body?.innerText?.slice(0,1200)})');await capture('failure');}catch{}
}).finally(async()=>{
  try{if(ws?.readyState===WebSocket.OPEN)await command('Browser.close',{},null);}catch{}
  ws?.close();browser.kill();
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));
  fs.writeFileSync(path.join(out,'browser-stderr.log'),stderr);
  console.log(JSON.stringify(report,null,2));
});
