// Optional real WebGL regression. No HTTP server, SQLite, MATSim or run files.
// node .\python\check_simz1_vehicle_focus_browser.cjs
// Chrome uses CDP pipes; only the application's pinned deck.gl CDN needs Internet.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'..');
const out=path.join(project,'runtime','validation','vehicle-focus-'+Date.now());
const browserPath=process.env.SIMZ1_BROWSER || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
].find(value=>fs.existsSync(value));
if(!browserPath)throw new Error('No Chrome/Edge executable available');
fs.mkdirSync(out,{recursive:true});

function fixture() {
  const origin=[-90.513,14.636],scale=6371008.8*Math.PI/180;
  const xy=(x,y)=>[origin[0]+x/(scale*Math.cos(origin[1]*Math.PI/180)),origin[1]+y/scale];
  const identity={run_id:'offline-vehicle-focus-fixture',iteration:0,run_manifest_sha256:'b'.repeat(64)};
  const keyA='a'.repeat(64),keyB='c'.repeat(64);
  const links={east:{path:[xy(0,0),xy(200,0)],from_node:'west',to_node:'corner',allowed_to_links:['north']},
    north:{path:[xy(200,0),xy(200,200)],from_node:'corner',to_node:'north-end',allowed_to_links:[]}};
  for(const [id,link] of Object.entries(links))Object.assign(link,{num_lanes:2,lane_width_m:3,
    length_m:200,offset_eligible:true,opposing_lanes:0,osm_tags:{},movement_source:'effective_car_node_adjacency',
    native_lanes:Object.fromEntries([0,1].map(index=>[id+'.'+index,{index,represented_lanes:1,start_m:200}]))});
  const tripA={Trip_ID:'person-A:trip:1',Person_ID:'person-A',Departure:0,Arrival:420,Status:'completed',
    Origin_Position:xy(0,0),Destination_Position:xy(200,200)};
  const tripB={Trip_ID:'person-B:trip:1',Person_ID:'person-B',Departure:48,Arrival:88,Status:'completed',
    Origin_Position:xy(0,0),Destination_Position:xy(200,0)};
  const record=(vehicle,person,key,link,start,end,phases,trip)=>({vehicle,Agent_ID:person,Replay_Journey_Key:key,
    Link_ID:link,path:links[link].path,timestamps:[start,end],Trip:trip,Profile:'Normal',
    Motion_Provenance:{vehicle_limit_mps:15},Motion_Plan:{version:1,status:'kinematic',distance_m:200,phases},
    Speed_kmh:phases[0][3]*3.6,Max_Speed_kmh:54});
  const rows=[record('vehicle-A','person-A',keyA,'east',0,220,[[0,100,0,1,0],[100,120,100,0,0],[120,220,100,1,0]],tripA),
    record('vehicle-A','person-A',keyA,'north',220,420,[[220,420,0,1,0]],tripA),
    record('vehicle-B','person-B',keyB,'east',48,88,[[48,88,0,5,0]],tripB)];
  const events=[{vehicle:'vehicle-A',link:'east',lane:'east.0',time:0,type:'entered lane'},
    {vehicle:'vehicle-B',link:'east',lane:'east.1',time:48,type:'entered lane'},
    {vehicle:'vehicle-A',link:'north',lane:'north.0',time:220,type:'entered lane'}];
  const layers=[{id:'roads','@@type':'LineLayer',data:[]},
    ...['selected-history','selected-future'].map(id=>({id,'@@type':'PathLayer',data:[],getPath:'@@=path'})),
    {id:'trips','@@type':'ScatterplotLayer',data:[]},
    {id:'signals','@@type':'ScatterplotLayer',data:[]},
    {id:'incidents','@@type':'ScatterplotLayer',data:[]},
    ...['selected-origin','selected-destination'].map(id=>({id,'@@type':'ScatterplotLayer',data:[],getPosition:'@@=position',getRadius:1}))];
  const config={layers,initialViewState:{longitude:xy(75,0)[0],latitude:origin[1],zoom:20,pitch:0,bearing:0},
    visual_lanes:{schema_version:1,available:true,identity,links},hud:{...identity,planned_persons:2,planned_trips:2},
    continuous:{...identity,start_seconds:0,end_seconds:86400,window_seconds:120,window_count:720,
      total_reconstructed_vehicles:2,worker:false,window_endpoint:'/api/window',journey_endpoint:'/api/journey',
      source_time_horizon:{start_seconds:0,end_seconds:86400},metrics_window:{start_seconds:0,end_seconds:86400}}};
  return {identity,config,rows,events,trips:{[keyA]:tripA,[keyB]:tripB},turn:xy(200,0)};
}
const data=fixture();
let html=fs.readFileSync(path.join(__dirname,'visualizador_z1_continuous.html'),'utf8');
for(const [token,file] of Object.entries({__LOADER__:'simz1_continuous_loader.js',__HUD__:'simz1_continuous_hud.js',
  __VISUAL_LANES__:'simz1_visual_lanes.js',__VISUAL_QUEUES__:'simz1_visual_queues.js',
  __VEHICLE_PICKING__:'simz1_vehicle_picking.js',__SPATIAL_VIEW__:'simz1_spatial_view.js',__CONTROLS__:'visualizador_z1_controls.js'})) {
  assert.equal(html.split(token).length,2,'one application placeholder '+token);
  html=html.replace(token,()=>fs.readFileSync(path.join(__dirname,file),'utf8'));
}
const mock=`const fixture=${JSON.stringify(data)};window.fixtureRequests=[];window.fixture=fixture;
window.fetch=async input=>{const url=new URL(input,'http://fixture.invalid/');fixtureRequests.push(url.pathname+url.search);
let value;if(url.pathname==='/api/config')value=fixture.config;
else if(url.pathname==='/api/window'){const index=Number(url.searchParams.get('index')),start=index*120,end=Math.min(86400,start+120);
value={...fixture.identity,index,start_seconds:start,end_seconds:end,trips:fixture.trips,
segments:fixture.rows.filter(row=>row.timestamps[0]<end&&row.timestamps[1]>start),
context_segments:fixture.rows.filter(row=>row.timestamps[0]>=end||row.timestamps[1]<=start),
lane_replay:{events:fixture.events},signal_replay:{series:[]},incidents:[]};}
else if(url.pathname==='/api/journey'){const key=url.searchParams.get('key');value={...fixture.identity,key,records:fixture.rows.filter(row=>row.Replay_Journey_Key===key)};}
else if(url.pathname==='/api/hud')value={schema_version:1,...fixture.identity,replay_window:{start_seconds:0,end_seconds:86400},
source_time_horizon:fixture.config.continuous.source_time_horizon,metrics_window:fixture.config.continuous.metrics_window,
counts:{persons_generated:2,planned_trips:2,reconstructed_vehicles:2,vehicles_with_events:2,completed_trips:2,pending_censored_trips:0},native_active_series:null};
else throw new Error('Unexpected fixture request '+url.pathname);
return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});};`;
html=html.replace('(async () => {',()=>mock+'\n(async () => {');
const fixtureFile=path.join(out,'fixture.html');fs.writeFileSync(fixtureFile,html);
const browser=spawn(browserPath,['--headless=new','--no-first-run','--no-default-browser-check',
  '--disable-background-networking','--window-size=1280,900','--force-device-scale-factor=1',
  '--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-gpu-sandbox',
  '--remote-debugging-pipe','--user-data-dir='+path.join(out,'profile'),'about:blank'],
  {windowsHide:true,stdio:['ignore','ignore','pipe','pipe','pipe']});
let nextId=0,session,buffer='',stderr='',pageReady=false;const pending=new Map();
browser.stderr.on('data',chunk=>{stderr+=chunk;fs.appendFileSync(path.join(out,'browser-stderr.log'),chunk);});
const report={real_browser:true,webgl:false,webgl_backend:'SwiftShader software WebGL2',http_server:false,scientific_run_access:false,
  browser:browserPath,checks:[],errors:[],output:out};
browser.on('error',error=>report.errors.push(error.message));
browser.on('exit',(code,signal)=>{
  for(const [id,call] of pending){clearTimeout(call.timer);call.reject(new Error('Browser exited: '+code+' '+signal));pending.delete(id);}
});
browser.stdio[4].on('data',chunk=>{
  buffer+=chunk.toString('utf8');let boundary;
  while((boundary=buffer.indexOf('\0'))>=0) {
    const raw=buffer.slice(0,boundary);buffer=buffer.slice(boundary+1);if(!raw)continue;
    const message=JSON.parse(raw),call=pending.get(message.id);
    if(call){pending.delete(message.id);clearTimeout(call.timer);message.error ? call.reject(new Error(JSON.stringify(message.error))) : call.resolve(message.result);}
  }
});
function command(method,params={},target=session) {
  if(browser.exitCode!==null || browser.signalCode!==null)return Promise.reject(new Error('Browser already exited'));
  const id=++nextId;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);
    pending.set(id,{resolve,reject,timer});
    browser.stdio[3].write(JSON.stringify({id,method,params,...(target?{sessionId:target}:{})})+'\0');
  });
}
async function evaluate(expression) {
  const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description || JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(expression,timeout=20000) {
  const start=Date.now();
  while(Date.now()-start<timeout){const result=await evaluate(expression);if(result)return result;await sleep(100);}
  throw new Error('Timed out: '+expression);
}
function check(label,condition){assert.ok(condition,label);report.checks.push(label);}
async function seek(time) {
  await evaluate(`simz1Continuous.pause();simz1Continuous.seek(${time})`);
  await until(`(()=>{const s=simz1Continuous.getState();return !s.buffering&&s.current===${time}})()`);
}
async function target(vehicle) {
  return evaluate(`(()=>{const api=simz1Continuous,marker=api.layers.find(l=>l.id==='trips').props.data.find(m=>m.vehicle===${JSON.stringify(vehicle)});
  if(!marker)throw new Error('Missing displayed vehicle');const p=api.deck.getViewports()[0].project(marker.position),r=api.deck.getCanvas().getBoundingClientRect();
  return {x:r.left+p[0],y:r.top+p[1]};})()`);
}
async function pointer(vehicle,click=false) {
  const point=await target(vehicle);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',...point,buttons:0,pointerType:'mouse'});
  // Let hover picking finish before the next independent pointer gesture.
  await sleep(100);
  if(click){
    await command('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',buttons:1,clickCount:1,pointerType:'mouse'});
    await sleep(50);
    await command('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',buttons:0,clickCount:1,pointerType:'mouse'});
    await until(`simz1Continuous.getState().selectedVehicleId===${JSON.stringify(vehicle)}`,3000);
    await sleep(350); // Separate single-click cases from the double-tap recognizer.
  }
}
async function verify(label,vehicle,mode='pinned') {
  const result=await evaluate(`(()=>{const api=simz1Continuous,s=api.getState(),trips=api.layers.find(l=>l.id==='trips'),
  layer=api.layers.find(l=>l.id==='vehicle-focus-outline'),rows=layer.props.data,row=rows.find(r=>r.mode===${JSON.stringify(mode)}),
  marker=trips.props.data.find(m=>m.vehicle===${JSON.stringify(vehicle)});
  return {vehicle:s.selectedVehicleId,person:s.selectedPersonId,exact:row?.marker===marker&&!!marker,
  actual:row?.marker.vehicle,closed:row?.outline.length===5&&JSON.stringify(row.outline[0])===JSON.stringify(row.outline[4]),
  mode:row?.mode,color:row?.color,bodyColor:marker?.color,bodyPath:marker?.Visual_Body_Path,
  cardFields:Object.keys(s.vehicleCard.fields||{}),rows:rows.map(r=>({vehicle:r.marker.vehicle,mode:r.mode}))};})()`);
  report.samples=report.samples||[];report.samples.push({label,...result});
  check(label+': contour aliases the exact current rendered vehicle object',result.exact&&result.actual===vehicle);
  check(label+': rigid contour is closed',result.closed);
  if(mode==='pinned'){
    check(label+': selected vehicle_id and person_id match the highlighted body',result.vehicle===vehicle&&result.person===vehicle.replace('vehicle-','person-'));
    check(label+': six contextual fields retained',result.cardFields.length===6);
  }
  return result;
}
async function screenshot(name) {
  const image=await command('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(image.data,'base64'));
}
(async()=>{
  try {
    const tab=await command('Target.createTarget',{url:'about:blank'},null);
    session=(await command('Target.attachToTarget',{targetId:tab.targetId,flatten:true},null)).sessionId;
    await command('Page.enable');await command('Runtime.enable');pageReady=true;console.log('CDP connected; loading offline fixture');
    await command('Page.navigate',{url:pathToFileURL(fixtureFile).href});
    await until('Boolean(window.simz1Continuous) || (window.simz1Errors?.length ? "error" : false)',30000);
    const startupErrors=await evaluate('window.simz1Errors || []');
    assert.deepEqual(startupErrors,[],'application initializes without WebGL/CDN errors');
    await seek(60);
    await until('simz1Continuous.deck.isInitialized && simz1Continuous.layers.find(l=>l.id==="trips").props.data.length===2');
    report.webgl=await evaluate('!!simz1Continuous.deck.getCanvas().getContext("webgl2")');
    check('actual browser has WebGL2',report.webgl);
    await evaluate(`(()=>{window.fixtureGestures=[];
      for(const name of ['pointerdown','pointerup','click'])document.addEventListener(name,event=>
        fixtureGestures.push({dom:name,target:event.target.tagName,x:event.clientX,y:event.clientY}),true);
      })()`);
    // isInitialized precedes the first completed GPU frame. Exercise the
    // production handlers unchanged, after the actual canvas has been drawn.
    await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))');
    check('vehicle speed colors render over both focus layers',await evaluate('(()=>{const ids=simz1Continuous.layers.map(l=>l.id);return ["vehicle-focus-halo","vehicle-focus-outline"].every(id=>ids.indexOf(id)<ids.indexOf("trips"))})()'));
    check('no initial selection',await evaluate('simz1Continuous.getState().vehicleHighlights.length===0'));
    await pointer('vehicle-A');await until('simz1Continuous.getState().vehicleHighlights.some(r=>r.mode==="hover")');
    const hover=await verify('temporary mouse hover','vehicle-A','hover');
    await pointer('vehicle-A',true);const first=await verify('first click','vehicle-A');
    check('hover and pinned colors differ',JSON.stringify(hover.color)!==JSON.stringify(first.color));
    await pointer('vehicle-B');await verify('neighbor hover preserves pinned identity','vehicle-A');
    await verify('neighbor receives only temporary highlight','vehicle-B','hover');
    await pointer('vehicle-B',true);const second=await verify('second click','vehicle-B');
    check('cars retain distinct original speed colors',JSON.stringify(first.bodyColor)!==JSON.stringify(second.bodyColor));
    check('previous pin removed',second.rows.filter(row=>row.mode==='pinned').length===1&&second.rows.find(row=>row.mode==='pinned').vehicle==='vehicle-B');
    await screenshot('parallel-second-selected');
    await pointer('vehicle-A',true);await seek(110);await verify('stopped vehicle','vehicle-A');
    check('stop keeps original white speed color',await evaluate('simz1Continuous.layers.find(l=>l.id==="trips").props.data[0].Visual_Speed_kmh===0'));
    await seek(125);await verify('crossing a loading window','vehicle-A');
    await seek(60);await verify('backward seek','vehicle-A');
    await evaluate('simz1Continuous.setSpeed(1);simz1Continuous.play()');await sleep(200);await evaluate('simz1Continuous.pause()');
    await verify('playback and pause','vehicle-A');
    await seek(220);
    await evaluate('simz1Continuous.deck.props.onViewStateChange({viewState:{...simz1Continuous.getState().camera.viewState,longitude:fixture.turn[0],latitude:fixture.turn[1],bearing:37,pitch:35}})');
    await verify('turn and camera rotation','vehicle-A');await screenshot('turn-selected');
    await evaluate('document.getElementById("simz1-vehicle-card-close").click()');
    check('closing clears pin and both contours',await evaluate('simz1Continuous.getState().selectedVehicleId===null&&simz1Continuous.layers.find(l=>l.id==="vehicle-focus-outline").props.data.length===0'));
    check('no reported application errors',await evaluate('window.simz1Errors.length===0'));
    report.passed=true;
  } catch(error) {
    report.passed=false;report.errors.push(error.stack || error.message);
    if(pageReady)try {
      report.viewerErrors=await evaluate('window.simz1Errors || []');
      report.gestures=await evaluate('window.fixtureGestures || []');
      report.state=await evaluate('window.simz1Continuous?.getState()');await screenshot('failure');
    }catch {}
    process.exitCode=1;
  } finally {
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
    fs.writeFileSync(path.join(out,'browser-stderr.log'),stderr);
    try {await command('Browser.close',{},null);}catch {}
    for(const call of pending.values())clearTimeout(call.timer);browser.kill();
    console.log((report.passed?'PASS':'FAIL')+': real WebGL vehicle focus; '+path.join(out,'report.json'));
    if(!report.passed)console.error(report.errors.join('\n'));
  }
})();
