// Actual Chrome/Edge + WebGL checks. Node 22, no npm dependencies, no DOM stubs.
// Usage: node scripts/validation/occupancy_20261027_browser_audit.cjs URL output-directory [times.json]
// times.json can be an array of seconds or {times:[...]}; at most96 seeks plus4 playback frames.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const crypto = require('node:crypto');
function independentSat(a,b,projection,gap=0,lateral=0) {
  const corners=body=>{
    const angle=body.heading*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
    const x=(body.position[0]-projection.origin[0])*projection.xScale,y=(body.position[1]-projection.origin[1])*projection.yScale;
    const half=(body.length_m+gap)/2,side=body.width_m/2+lateral;
    return {axes:[[c,s],[-s,c]],points:[[-half,-side],[-half,side],[half,side],[half,-side]].map(([u,v])=>[x+u*c-v*s,y+u*s+v*c])};
  };
  const aa=corners(a),bb=corners(b);
  for(const [x,y] of [...aa.axes,...bb.axes]) {
    const pa=aa.points.map(p=>p[0]*x+p[1]*y),pb=bb.points.map(p=>p[0]*x+p[1]*y);
    if(Math.max(...pa)<=Math.min(...pb)+1e-7 || Math.max(...pb)<=Math.min(...pa)+1e-7)return false;
  }
  return true;
}
if(process.argv.includes('--self-test')) {
  const assert=require('node:assert/strict'),p={origin:[0,0],xScale:1,yScale:1};
  const a={position:[0,0],length_m:4.5,width_m:1.8,heading:0};
  assert.equal(independentSat(a,{...a,position:[4.49,0]},p),true);
  assert.equal(independentSat(a,{...a,position:[4.59,0]},p,.1,0),true);
  assert.equal(independentSat(a,{...a,position:[4.6,0]},p,.1,0),false);
  const adjacent={...a,position:[0,1.9]};
  assert.equal(independentSat(a,adjacent,p),false);
  assert.equal(independentSat(a,adjacent,p,.1,0),false);
  assert.equal(independentSat(a,adjacent,p,.1,.1),true);
  const angle=Math.PI/6,rotated={...a,heading:30};
  assert.equal(independentSat(rotated,{...rotated,position:[4.59*Math.cos(angle),4.59*Math.sin(angle)]},p,.1,0),true);
  console.log('PASS: independent corner SAT physical body,0.09/0.10m longitudinal gap,rotated body and lateral-only warning');
  process.exit(0);
}
const base = process.argv[2] || 'http://127.0.0.1:8792';
const requestedSamples = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : null;
const targetedRegression=requestedSamples?.targeted_regression===true;
const requestedTimes=Array.isArray(requestedSamples)?requestedSamples:requestedSamples?.times;
if(requestedTimes && (!requestedTimes.length || requestedTimes.length>96 || !requestedTimes.every(Number.isFinite)))throw new Error('Provide 1-96 finite sample times; four frames are reserved for actual playback');
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
  headless:true,viewport:[1440,960],base,seek_timeout_seconds:240,checks:[],errors:[],samples:[],console:[],failedRequests:[],httpErrors:[],requests:[]};
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
async function state() {return evaluate('simz1Continuous.getState()');}
async function seek(time) {
  const began=Date.now();
  const horizon=report.initial.hud.data.replay_window;
  const expected = Math.max(horizon.start_seconds,Math.min(horizon.end_seconds,time));
  await evaluate(`simz1Continuous.pause(); simz1Continuous.seek(${time});`);
  await until(`(()=>{const s=simz1Continuous.getState();return !s.buffering && Math.abs(s.current-${expected})<.01})()`,report.seek_timeout_seconds*1000);
  report.samples.push({time:expected,seek_seconds:(Date.now()-began)/1000});
  return state();
}
async function capture(name) {
  const image=await command('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(image.data,'base64'));
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
  report.client_build=await evaluate('window.simz1ClientBuild || null');
  const clientFiles={template:'visualizador_z1_continuous.html',controls:'visualizador_z1_controls.js',
    loader:'simz1_continuous_loader.js',hud:'simz1_continuous_hud.js',lanes:'simz1_visual_lanes.js',
    picking:'simz1_vehicle_picking.js',queues:'simz1_visual_queues.js',spatial:'simz1_spatial_view.js',
    signals:'simz1_signal_geometry.js',arrivals:'simz1_arrival_effects.js',
    incident_effects:'simz1_incident_effects.js',stops:'simz1_transit_stops.js'};
  const sourceHash=file=>crypto.createHash('sha256').update(fs.readFileSync(path.join(project,'python',file),'utf8').replace(/\r\n?/g,'\n')).digest('hex');
  if(!report.client_build?.components)throw new Error('Client renderer build provenance is missing');
  for(const [component,file] of Object.entries(clientFiles))
    if(report.client_build.components[component]!==sourceHash(file))throw new Error('Served renderer differs from current source: '+component);
  report.client_sources_verified=true;
  report.metric_projection=await evaluate(`(async()=>{
    const config=await fetch('/api/config').then(r=>r.json()),links=config.visual_lanes.links;
    const points=Object.values(links).flatMap(link=>link.path||[]).filter(p=>Array.isArray(p)&&p.length>=2&&p.slice(0,2).every(Number.isFinite)&&Math.abs(p[0])<=180&&Math.abs(p[1])<85);
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),origin=[(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2];
    const scale=6371008.8*Math.PI/180;
    window.__simz1AuditGeometry={projection:{origin,xScale:scale*Math.cos(origin[1]*Math.PI/180),yScale:scale},
      spacing:simz1Continuous.getVehicleCatalog().spacing,
      levels:Object.fromEntries(Object.entries(links).map(([id,link])=>[id,['bridge','tunnel','layer'].map(key=>link.osm_tags?.[key]??null)]))};
    return {...window.__simz1AuditGeometry.projection,spacing:window.__simz1AuditGeometry.spacing,source:'same local equirectangular plane from validated visual_lanes bounding midpoint; independent corner SAT',identity:config.continuous};
  })()`);
  for(const field of ['run_id','iteration','run_manifest_sha256','source_version'])
    if(report.metric_projection.identity[field]!==report.initial.hud.data[field])throw new Error('SAT geometry identity mismatch: '+field);
  report.hud_fleet_text=await evaluate('document.getElementById("simz1-fixed-public-fleet")?.textContent || ""');
  if(requestedSamples?.identity)for(const field of ['run_id','iteration','run_manifest_sha256','source_version'])
    if(report.initial.hud.data[field]!==requestedSamples.identity[field])throw new Error('Sample identity mismatch: '+field);
  const scripts=await evaluate('Array.from(document.scripts,s=>({src:s.src,type:s.type,id:s.id,text:s.textContent}))');
  report.script_sources=scripts.map(({text,...metadata})=>({...metadata,bytes:Buffer.byteLength(text),sha256:crypto.createHash('sha256').update(text).digest('hex')}));
  report.scope=targetedRegression?'Targeted regression frames only; no whole-day, presentation or playback acceptance':
    'Bounded real replay audit, native data unchanged; samples are not a global certificate';
  report.targeted_regression=targetedRegression;
  report.frames=[];
  const times=requestedTimes||[3600,3660,16320.5,25200,28800,32400,34200,34230,34260,34320,34500,36000,43200,57600,64800,77400,77520];
  if(times.length>96)throw new Error('Use at most96 seek samples; four additional frames are reserved for real1x/120x playback');
  const horizon=report.initial.hud.data.replay_window;
  if(times.some(time=>time<horizon.start_seconds||time>horizon.end_seconds))throw new Error('Sample time outside native replay horizon');
  let images=0;const capturedFamilies=new Set(),capturedQueues=new Set();report.family_screenshots=[];report.queue_screenshots=[];
  const readFrame=async time=>evaluate(`(()=>{const d=simz1Continuous.getVisualDiagnostics(${time});
      const collisions=d.collisions.filter(c=>c.resolution==='unresolved').slice(0,12);
      const ids=new Set(collisions.flatMap(c=>c.vehicles.map(v=>v.vehicle_id)));
      const allMarkers=simz1Continuous.layers.find(l=>l.id==='trips').props.data;
      const diagnosticsByVehicle=new Map(d.records.map(record=>[record.vehicle_id,record]));
      const markers=allMarkers.filter(m=>ids.has(m.vehicle));
      const rendered_bodies=allMarkers.map(m=>({vehicle:m.vehicle,family:m.Vehicle_Family||diagnosticsByVehicle.get(m.vehicle)?.presentation?.family,position:m.position,
        length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters,heading:diagnosticsByVehicle.get(m.vehicle)?.heading,
        link_id:m.Link_ID,lane:m.Visual_Lane_Index,
        native_occupancy:m.Native_Occupancy,domain:m.Visual_Occupancy_Domain,reference:m.Visual_Occupancy_Reference,
        center_m:m.Visual_Queue_Center_Meters,display_link:m.Visual_Queue_Display_Link_ID,
        held:m.Visual_Queue_Holding===true||m.Visual_Queue_State==='queued',queue_state:m.Visual_Queue_State,
        native_holding_flag:m.Visual_Queue_Holding,stop_clearance_m:m.Visual_Queue_Stop_Clearance_Meters}));
      const families={};for(const r of d.records)if(r.visible){const family=r.presentation?.family||'unknown';families[family]=(families[family]||0)+1;}
      const groups=new Map();for(const m of rendered_bodies)if(m.domain&&Number.isFinite(m.center_m)){
        const key=JSON.stringify([m.domain,m.lane]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(m);}
      const corridor_gaps=[];for(const [domain,rows] of groups){rows.sort((a,b)=>b.center_m-a.center_m);
        for(let i=1;i<rows.length;i++)corridor_gaps.push({domain,leader:rows[i-1].vehicle,follower:rows[i].vehicle,
          gap_m:rows[i-1].center_m-rows[i].center_m-(rows[i-1].length_m+rows[i].length_m)/2});}
      const sat=${independentSat.toString()},geometry=window.__simz1AuditGeometry;
      const independent_sat={body_pairs:0,longitudinal_pairs:0,full_envelope_pairs:0,lateral_only_pairs:0,unsupported_bodies:0,pairs_checked:0,violations:[]};
      const bodies=rendered_bodies.filter(body=>{
        const valid=Array.isArray(body.position)&&body.position.slice(0,2).every(Number.isFinite)&&[body.heading,body.length_m,body.width_m].every(Number.isFinite)&&body.length_m>0&&body.width_m>0;
        if(!valid)independent_sat.unsupported_bodies++;return valid;});
      for(let i=0;i<bodies.length;i++)for(let j=i+1;j<bodies.length;j++) {
        const a=bodies[i],b=bodies[j],levelA=geometry.levels[a.link_id],levelB=geometry.levels[b.link_id];
        if(levelA&&levelB&&levelA.some((value,index)=>value!==levelB[index]))continue;
        const body=sat(a,b,geometry.projection),longitudinal=sat(a,b,geometry.projection,.1,0),
          full=sat(a,b,geometry.projection,geometry.spacing.gap_m,geometry.spacing.lateral_clearance_per_side_m);
        independent_sat.pairs_checked++;independent_sat.body_pairs+=Number(body);independent_sat.longitudinal_pairs+=Number(longitudinal);
        independent_sat.full_envelope_pairs+=Number(full);independent_sat.lateral_only_pairs+=Number(full&&!longitudinal);
        if((body||longitudinal||full)&&independent_sat.violations.length<12)
          independent_sat.violations.push({vehicles:[a.vehicle,b.vehicle],body_overlap:body,longitudinal_overlap:longitudinal,lateral_only:full&&!longitudinal});
      }
      return {time:${time},counts:d.counts,summary:d.summarizeCollisions?.(),families,collisions,records:d.records,markers,
        rendered_bodies,corridor_gaps,independent_sat,held_stop_violations:rendered_bodies.filter(m=>m.held&&Number.isFinite(m.stop_clearance_m)&&m.stop_clearance_m< -1e-7)};})()`);
  for(const time of times) {
    await seek(time);
    const frame={...await readFrame(time),audit_kind:'paused_seek'};
    report.frames.push(frame);
    console.log(JSON.stringify({time,counts:frame.counts,summary:frame.summary}));
    for(const family of ['car','motorcycle','bus','truck'])if(!capturedFamilies.has(family)) {
      const representative=frame.records.find(r=>r.visible&&r.presentation?.family===family&&r.position);
      if(representative) {
        await evaluate(`simz1Continuous.deck.setProps({viewState:{longitude:${representative.position[0]},latitude:${representative.position[1]},zoom:20,pitch:0,bearing:0}})`);
        await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        const name='family-'+family+'-'+time;await capture(name);capturedFamilies.add(family);
        report.family_screenshots.push({family,time,vehicle:representative.vehicle_id,file:name+'.png',dimensions_m:representative.dimensions_m});
      }
    }
    for(const family of ['bus','truck']) {
      const bodies=new Map(frame.rendered_bodies.map(body=>[body.vehicle,body]));
      const gap=frame.corridor_gaps.find(row=>bodies.get(row.leader)?.family===family&&bodies.get(row.leader)?.held);
      const body=gap?bodies.get(gap.leader):frame.rendered_bodies.find(row=>row.family===family&&row.held&&Number.isFinite(row.stop_clearance_m));
      const kind=gap?'queue':'held-body',key=kind+'-'+family;
      if(body&&!capturedQueues.has(key)) {
        const follower=gap?bodies.get(gap.follower):null;
        const point=follower?[(body.position[0]+follower.position[0])/2,(body.position[1]+follower.position[1])/2]:body.position;
        await evaluate(`simz1Continuous.deck.setProps({viewState:{longitude:${point[0]},latitude:${point[1]},zoom:20,pitch:0,bearing:0}})`);
        await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        const name=key+'-'+time;await capture(name);capturedQueues.add(key);
        report.queue_screenshots.push({family,kind,time,leader:body.vehicle,follower:follower?.vehicle||null,
          gap_m:gap?.gap_m??null,stop_clearance_m:body.stop_clearance_m,file:name+'.png'});
      }
    }
    if(images<5 && frame.collisions.length) {
      const ids=frame.collisions[0].vehicles.map(v=>v.vehicle_id);
      const point=frame.records.find(r=>ids.includes(r.vehicle_id)&&r.position)?.position;
      if(point) {
        await evaluate(`simz1Continuous.deck.setProps({viewState:{longitude:${point[0]},latitude:${point[1]},zoom:20,pitch:0,bearing:0}})`);
        await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        await capture('overlap-'+time);images++;
      }
    }
  }
  report.playback=[];
  if(!targetedRegression) {
  const truckWait=requestedSamples?.samples?.find(sample=>sample.category==='truck_wait');
  const busQueue=report.queue_screenshots.find(sample=>sample.family==='bus'&&sample.kind==='queue') ||
    requestedSamples?.samples?.find(sample=>sample.category==='bus_dwell');
  if(!busQueue)throw new Error('No real bus queue/dwell available for the bounded playback check');
  const windowSeconds=report.metric_projection.identity.window_seconds;
  const boundary=Math.min(horizon.end_seconds-2,(Math.floor((busQueue.time-horizon.start_seconds)/windowSeconds)+1)*windowSeconds+horizon.start_seconds);
  for(const test of [{speed:1,time:(truckWait||busQueue).time,target_family:truckWait?'truck':'bus'},
                    {speed:120,time:boundary-.25,boundary,target_family:'bus'}]) {
    if(test.boundary!=null)await seek(test.boundary+1);
    await seek(test.time);
    await evaluate(`simz1Continuous.setSpeed(${test.speed});`);
    const before=await state(),beforeFrame={...await readFrame(before.current),audit_kind:'playback_start',playback_speed:test.speed};
    report.frames.push(beforeFrame);
    const cacheBefore=await evaluate('simz1Continuous.getPerformance().loader'),began=Date.now();
    await evaluate('simz1Continuous.play();');
    const target=test.boundary!=null?test.boundary+.1:before.current+.25;
    await until(`(()=>{const s=simz1Continuous.getState();return !s.buffering&&s.current>=${target}})()`,120000);
    await evaluate('simz1Continuous.pause();');
    const after=await state(),afterFrame={...await readFrame(after.current),audit_kind:'playback_end',playback_speed:test.speed};
    report.frames.push(afterFrame);
    const crossed=Math.floor((after.current-horizon.start_seconds)/windowSeconds)>Math.floor((before.current-horizon.start_seconds)/windowSeconds);
    const evidence={speed:test.speed,target_family:test.target_family,start_time:before.current,end_time:after.current,
      clock_advance_seconds:after.current-before.current,wall_seconds:(Date.now()-began)/1000,
      boundary_preloaded:test.boundary??null,crossed_window:crossed,loader_before:cacheBefore,
      loader_after:await evaluate('simz1Continuous.getPerformance().loader'),
      visible_body_instances:beforeFrame.rendered_bodies.length+afterFrame.rendered_bodies.length,
      independent_sat_pairs:beforeFrame.independent_sat.pairs_checked+afterFrame.independent_sat.pairs_checked};
    evidence.status=evidence.clock_advance_seconds>.1&&evidence.visible_body_instances>0&&(test.speed!==120||crossed)?'passed':'failed';
    report.playback.push(evidence);
    const representative=afterFrame.records.find(record=>record.visible&&record.presentation?.family===test.target_family&&record.position);
    if(representative)await evaluate(`simz1Continuous.deck.setProps({viewState:{longitude:${representative.position[0]},latitude:${representative.position[1]},zoom:20,pitch:0,bearing:0}})`);
    await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    await capture('playback-'+test.speed+'x');
  }
  report.playback_contract={status:report.playback.length===2&&report.playback.every(test=>test.status==='passed')&&
    report.playback.reduce((sum,test)=>sum+test.independent_sat_pairs,0)>0?'passed':'failed',
    note:'Actual play/pause clock progression at1x and120x; four audited body frames, including a preloaded window boundary. No continuous-time global certificate.'};
  } else report.playback_contract={status:'not_requested',note:'Targeted regression of named defective frames; this report is not final acceptance.'};
  report.aggregate={sampled_frames:report.frames.length,families:{},body_overlaps:0,envelope_only_overlaps:0,
    incomplete_hold_context:0,held_stop_violations:0,held_bodies_checked:0,held_stop_clearances_checked:0,held_families:{},
    active_marker_instances:0,visible_marker_instances:0,omitted_marker_instances:0,omission_reasons:{},warning_reasons:{},
    independent_body_pairs:0,independent_longitudinal_pairs:0,independent_lateral_only_pairs:0,independent_full_envelope_pairs:0,sat_unsupported_bodies:0,
    independent_sat_pairs_checked:0,minimum_held_stop_clearance_m:null,minimum_modeled_corridor_gap_m:null};
  for(const frame of report.frames){const a=report.aggregate;
    a.body_overlaps+=frame.summary?.unresolved_body_overlap||0;a.envelope_only_overlaps+=frame.summary?.unresolved_safety_envelope_only||0;
    a.incomplete_hold_context+=frame.counts.incompleteHoldContext||0;a.held_stop_violations+=frame.held_stop_violations.length;
    a.independent_body_pairs+=frame.independent_sat.body_pairs;a.independent_longitudinal_pairs+=frame.independent_sat.longitudinal_pairs;
    a.independent_lateral_only_pairs+=frame.independent_sat.lateral_only_pairs;a.independent_full_envelope_pairs+=frame.independent_sat.full_envelope_pairs;
    a.independent_sat_pairs_checked+=frame.independent_sat.pairs_checked;
    a.sat_unsupported_bodies+=frame.independent_sat.unsupported_bodies;
    a.held_bodies_checked+=frame.rendered_bodies.filter(body=>body.held).length;
    for(const body of frame.rendered_bodies)if(body.held)a.held_families[body.family]=(a.held_families[body.family]||0)+1;
    a.held_stop_clearances_checked+=frame.rendered_bodies.filter(body=>body.held&&Number.isFinite(body.stop_clearance_m)).length;
    for(const body of frame.rendered_bodies)if(body.held&&Number.isFinite(body.stop_clearance_m))
      a.minimum_held_stop_clearance_m=a.minimum_held_stop_clearance_m==null?body.stop_clearance_m:Math.min(a.minimum_held_stop_clearance_m,body.stop_clearance_m);
    a.active_marker_instances+=frame.counts.active||0;a.visible_marker_instances+=frame.counts.visible||0;
    a.omitted_marker_instances+=frame.counts.omitted||0;
    for(const [reason,count] of Object.entries(frame.counts.omissionReasons||{}))a.omission_reasons[reason]=(a.omission_reasons[reason]||0)+count;
    for(const [reason,count] of Object.entries(frame.counts.warningReasons||{}))a.warning_reasons[reason]=(a.warning_reasons[reason]||0)+count;
    for(const [family,count] of Object.entries(frame.families))a.families[family]=(a.families[family]||0)+count;
    for(const gap of frame.corridor_gaps)a.minimum_modeled_corridor_gap_m=a.minimum_modeled_corridor_gap_m==null?gap.gap_m:Math.min(a.minimum_modeled_corridor_gap_m,gap.gap_m);}
  const visible=report.frames.flatMap(frame=>frame.records.filter(row=>row.visible).map(row=>({time:frame.time,...row})));
  const trucks=visible.filter(row=>row.presentation?.family==='truck');
  const tubus=visible.filter(row=>row.presentation?.family==='bus' &&
    (/^tubus$/i.test(row.presentation.operator||'') || /^tubus(?:_|$)/i.test(row.presentation.service||'')));
  const sameSize=(dimensions,length=12,width=2.5)=>dimensions && Math.abs(dimensions.length_m-length)<1e-7 && Math.abs(dimensions.width_m-width)<1e-7;
  const proof=row=>({vehicle:row.vehicle_id,time:row.time,label:row.presentation.label,operator:row.presentation.operator,
    service:row.presentation.service,rendered_dimensions_m:row.dimensions_m,
    visual:row.presentation.dimensions,physical:row.presentation.physical?.dimensions});
  const addCheck=(name,passed,evidence)=>report.checks.push({name,passed,evidence});
  addCheck('four_vehicle_families_rendered',['car','motorcycle','bus','truck'].every(family=>report.aggregate.families[family]>0),report.aggregate.families);
  addCheck('freight_label_in_hud',report.hud_fleet_text.includes('Transporte pesado'),report.hud_fleet_text);
  addCheck('freight_marker_label',trucks.length>0 && trucks.every(row=>row.presentation.label==='Transporte pesado'),trucks.slice(0,4).map(proof));
  addCheck('truck_native_and_visual_dimensions_match_12x2_5',trucks.length>0 && trucks.every(row=>
    sameSize(row.presentation.dimensions) && sameSize(row.presentation.physical?.dimensions) &&
    row.dimensions_m?.length===2 && Math.abs(row.dimensions_m[0]-12)<1e-7 && Math.abs(row.dimensions_m[1]-2.5)<1e-7),trucks.slice(0,4).map(proof));
  addCheck('tubus_native_and_visual_dimensions_match_12x2_5',tubus.length>0 && tubus.every(row=>
    sameSize(row.presentation.dimensions) && sameSize(row.presentation.physical?.dimensions)),tubus.slice(0,4).map(proof));
  const freight=report.initial.hud.data.freight_transport;
  addCheck('freight_hud_counts_observed',freight?.configured?.enabled===true && freight.configured.vehicles_configured>0 &&
    freight.observed?.vehicles_observed>0 && freight.observed?.departures_observed>0,
    {configured:freight?.configured?.vehicles_configured,observed:freight?.observed?.vehicles_observed,departures:freight?.observed?.departures_observed});
  report.presentation_contract={status:report.checks.every(check=>check.passed)?'passed':'failed',
    scope:'Actual sampled markers, recorded configured dimensions and visible HUD; does not certify other frames or physical microscopic positions.'};
  report.occupancy_coverage={held_bodies:report.aggregate.held_bodies_checked,
    held_stop_clearances:report.aggregate.held_stop_clearances_checked,
    requested_freight_wait:requestedSamples?.freight_wait_available===true,
    observed_held_truck_instances:report.aggregate.held_families.truck||0,
    status:report.aggregate.held_bodies_checked>0 && report.aggregate.held_stop_clearances_checked>0 &&
      (!requestedSamples?.freight_wait_available || report.aggregate.held_families.truck>0)?'passed':'failed',
    note:'A zero-denominator stop-line audit cannot pass. Internal corridor parts without a stop boundary are counted as held bodies only.'};
  report.projection_coverage={status:report.aggregate.omitted_marker_instances===0?'complete':'partial',
    active_marker_instances:report.aggregate.active_marker_instances,visible_marker_instances:report.aggregate.visible_marker_instances,
    omitted_marker_instances:report.aggregate.omitted_marker_instances,reasons:report.aggregate.omission_reasons,
    note:'Omitted poses are not certified as collision-free; counts are repeated marker instances across sampled frames, not unique vehicles.'};
  report.sampled_occupancy={status:report.aggregate.body_overlaps===0 && report.aggregate.independent_body_pairs===0 &&
    report.aggregate.independent_longitudinal_pairs===0 && report.aggregate.sat_unsupported_bodies===0 &&
    report.aggregate.incomplete_hold_context===0 && report.aggregate.held_stop_violations===0 &&
    report.occupancy_coverage.status==='passed' &&
    (report.aggregate.minimum_modeled_corridor_gap_m==null || report.aggregate.minimum_modeled_corridor_gap_m>=.10-1e-7)?'passed':'failed',
    scope:'Only visible bodies in these sampled frames; omitted projections are reported separately and not certified. Modeled body/gap/intersection diagnostics retain their native/derived provenance.'};
  report.status='audited';
  for(const [component,file] of Object.entries(clientFiles))
    if(report.client_build.components[component]!==sourceHash(file))throw new Error('Renderer source changed during audit: '+component);
  report.client_sources_unchanged_during_audit=true;
  if(report.sampled_occupancy.status==='failed' || !targetedRegression &&
    (report.presentation_contract.status==='failed' || report.playback_contract.status==='failed'))process.exitCode=1;
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
