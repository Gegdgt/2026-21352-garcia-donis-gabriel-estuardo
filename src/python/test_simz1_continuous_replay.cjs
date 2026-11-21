// Deterministic loader/control contract tests. These do not measure WebGL FPS.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const sourceDirectory=process.env.SIMZ1_RENDER_SOURCE_DIR || 'python';
const source=name=>fs.readFileSync(require('node:path').join(sourceDirectory,name),'utf8');
const loaderSource=source('simz1_continuous_loader.js');
const hudSource=source('simz1_continuous_hud.js');
const lanesSource=source('simz1_visual_lanes.js');
const queuesSource=source('simz1_visual_queues.js');
const pickingSource=source('simz1_vehicle_picking.js');
const spatialSource=source('simz1_spatial_view.js');
const arrivalsSource=source('simz1_arrival_effects.js');
const incidentsSource=source('simz1_incident_effects.js');
const controlsSource=source('visualizador_z1_controls.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function element(tag='div') {
  const node={tagName:tag.toUpperCase(),style:{},children:[],textContent:'',innerHTML:'',attributes:{},
    append(...nodes){this.children.push(...nodes);},appendChild(node){this.children.push(node);},
    setAttribute(key,value){this.attributes[key]=value;},focus(){this.focused=true;},
    contains(other){return this===other || this.children.some(child=>child.contains?.(other));}};
  return node;
}
const key='a'.repeat(64);
const fixtureDegreesPerMetre=180/(6371008.8*Math.PI);
const trip={Trip_ID:'person:trip:0001',Departure:86390,Arrival:86430,Status:'completed',
  Origin_Position:[0,0],Destination_Position:[40*fixtureDegreesPerMetre,0]};
function segment(id,start,end,from,to) {
  return {vehicle:'a',Agent_ID:'person',Link_ID:id,Replay_Journey_Key:key,path:[[from*fixtureDegreesPerMetre,0],[to*fixtureDegreesPerMetre,0]],
    timestamps:[start,end],Speed_kmh:3.6,Max_Speed_kmh:43.2,
    Motion_Plan:{version:1,status:'constant',distance_m:to-from,cap_mps:12,phases:[[start,end,0,1,0]]}};
}
const a0=segment('a0',86390,86400,0,10),a1=segment('a1',86400,86420,10,30),a2=segment('a2',86420,86430,30,40);
function harness(options={},visualLanes=null,spatialDemand=null,sessionStorage=undefined,testOptions={}) {
  const requests=[],hudRequests=[],viewerErrors=[],timers=new Map();let now=0,nextTimer=0;
  let hudStatus=200,hudPopulation=179235;
  const listeners={},canvas=element('canvas');
  const layer=id=>({id,props:{data:[]},clone(props){return {...this,id:props.id ?? this.id,props:{...this.props,...props}};}});
  const layers=['roads','trips','signals','incidents','map-labels','selected-history-casing','selected-future-casing','selected-history','selected-future','selected-origin','selected-destination',
    'vehicle-focus-halo','vehicle-focus-outline','arrival-annotations','synthetic-incident-emergency'].map(layer);
  const identity={run_id:'validated-real-draw',iteration:0,run_manifest_sha256:'b'.repeat(64),source_version:'c'.repeat(64)};
  const config={visual_lanes:visualLanes,hud:{...identity,planned_persons:1,planned_trips:1}, // Stale HTML totals must never reach HUD.
    initialViewState:{longitude:-90.513,latitude:14.636,zoom:14.5,pitch:45,bearing:0},
    spatial_demand:spatialDemand ? {...spatialDemand,identity,validated:true} : null,
    replay_window:{start_seconds:0,end_seconds:90000},
    continuous:{...identity,start_seconds:0,end_seconds:90000,window_seconds:120,window_count:750,
      source_time_horizon:{start_seconds:0,end_seconds:90000},metrics_window:{start_seconds:0,end_seconds:90001},
      window_endpoint:'/api/window',journey_endpoint:'/api/journey',total_reconstructed_vehicles:1,...options}};
  if(testOptions.temporalPolicy)config.temporal_policy=testOptions.temporalPolicy;
  if(testOptions.experimentalObservation)config.experimental_observation=testOptions.experimentalObservation;
  if(testOptions.config)Object.assign(config,testOptions.config);
  const sandbox={URLSearchParams,AbortController,TextEncoder,TextDecoder,console,
    reportError(error,source){viewerErrors.push({error,source});},
    setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
    performance:{now:()=>now},requestAnimationFrame(){},config,replaySegments:[],incidentRecords:[],layers,
    window:{location:{href:''},sessionStorage},document:{hidden:false,createElement:element,body:element('body'),
      addEventListener(name,handler){assert.equal(listeners[name],undefined,'no duplicate '+name+' listener');listeners[name]=handler;}},
    fetch(url,options){
      if(url.startsWith('/api/hud')) {hudRequests.push({url,options});return Promise.resolve({ok:hudStatus===200,status:hudStatus,json:async()=>({
        schema_version:1,...identity,replay_window:{start_seconds:config.continuous.start_seconds,end_seconds:config.continuous.end_seconds},
        source_time_horizon:config.continuous.source_time_horizon,metrics_window:config.continuous.metrics_window,
        vehicle_summary:{schema_version:1,private_vehicles:testOptions.temporalPolicy ? testOptions.cohortCounts?.principal_cohort_persons ?? null : hudPopulation,
          public_vehicles:null,private_basis:testOptions.temporalPolicy ? 'verified_main_cohort_one_vehicle_per_person' : 'verified_private_one_vehicle_per_person',
          public_basis:'missing_unique_fleet_evidence',temporal_policy:Boolean(testOptions.temporalPolicy)},
        counts:{persons_generated:hudPopulation,planned_trips:358470,completed_trips:300000,pending_censored_trips:58470,
          reconstructed_vehicles:142000,vehicles_with_events:144000,...testOptions.cohortCounts},native_active_series:null})});}
      return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
    },
    deckInstance:{props:{layers},updates:0,getCanvas:()=>canvas,setProps(props){this.updates++;Object.assign(this.props,props);}}};
  if(testOptions.fetch)sandbox.fetch=testOptions.fetch;
  if(testOptions.realClock)Object.assign(sandbox,{performance,setTimeout,clearTimeout});
  // Explicit isolated-test injection; not a config, URL or viewer API option.
  const fixtureIncidents=testOptions.incidentFixture===true ?
    'SimZ1IncidentEffects=class extends SimZ1IncidentEffects {constructor(o){super({...o,allowFixture:true});}};' : '';
  vm.createContext(sandbox);vm.runInContext([loaderSource,hudSource,lanesSource,queuesSource,pickingSource,spatialSource,arrivalsSource,
    incidentsSource,fixtureIncidents,controlsSource].join('\n'),sandbox);
  const evaluate=source=>vm.runInContext(source,sandbox);
  const api=sandbox.window.simz1Continuous;
  function request(index) {return requests.findLast(r=>!r.replied && new URL(r.url,'http://localhost').pathname==='/api/window' && Number(new URL(r.url,'http://localhost').searchParams.get('index'))===index);}
  function payload(index,overrides={}) {
    const o=config.continuous,start=o.start_seconds+index*o.window_seconds;
    const end=index===o.window_count-1 ? (o.data_end_seconds ?? o.end_seconds) : Math.min(o.end_seconds,start+o.window_seconds);
    return {...identity,index,start_seconds:start,end_seconds:end,
      segments:[a0,a1,a2].filter(s=>s.timestamps[0]<end && s.timestamps[1]>start).map(record=>structuredClone(record)),
      trips:{[key]:structuredClone(trip)},
      signal_replay:{series:[{system_id:'signal',group_id:'group',states:[[0,'RED'],[86400,'GREEN']].filter(s=>s[0]<end)}]},
      lane_replay:{events:[]},incidents:[],...overrides};
  }
  function reply(index,overrides={},status=200,retryAfter=null) {
    const r=request(index);assert.ok(r,'window request '+index);r.replied=true;
    const text=JSON.stringify(payload(index,overrides));
    r.resolve({ok:status===200,status,headers:{get:name=>name==='Retry-After' ? retryAfter : null},text:async()=>text});return r;
  }
  return {sandbox,evaluate,api,requests,hudRequests,viewerErrors,request,reply,payload,identity,timers,listeners,canvas,
    setHudStatus(status){hudStatus=status;},
    setHudPopulation(value){hudPopulation=value;},
    setNow(value){now=value;}, // Wall time can pass with RAF suspended in a hidden tab.
    async retryTimer(){const [id,timer]=timers.entries().next().value || [];assert.ok(timer,'one pending retry timer');timers.delete(id);timer.fn();await flush();return timer.delay;},
    frame(value){now=value;evaluate(`animate(${value})`);},
    journey(overrides={},status=200) {
      const r=requests.find(r=>!r.replied && r.url.startsWith('/api/journey'));assert.ok(r);r.replied=true;
      r.resolve({ok:status===200,status,json:async()=>({...identity,key,records:[a0,a1,a2].map(r=>({...structuredClone(r),Trip:structuredClone(trip)})),...overrides})});
    },
    count(id){return evaluate(`layers.find(l=>l.id===${JSON.stringify(id)}).props.data.length`);}};
}
module.exports={harness,segment,key};
if(require.main===module)(async()=>{
  // HUD-only fixtures: no browser, server or protected run files.
  const stored=new Map(),session={getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)};
  const presentation=harness({},null,null,session);
  presentation.reply(0);await flush();
  const initialHudRequests=presentation.hudRequests.length;
  const firstRetry=presentation.api.reloadHud(),sameRetry=presentation.api.reloadHud();
  assert.strictEqual(firstRetry,sameRetry,'simultaneous retries share one request');
  await firstRetry;
  assert.equal(presentation.hudRequests.length,initialHudRequests+1,'one in-flight metadata fetch');
  const panelText=()=>presentation.evaluate('runPanel.children.map(node=>node.textContent).join("")');
  for(const count of [100000,179235,0]) {
    presentation.setHudPopulation(count);await presentation.api.reloadHud();
    assert.equal(panelText(),'Vehículos particulares: '+count+' · Transporte público: — · Camiones: —');
  }
  presentation.setHudPopulation(undefined);await presentation.api.reloadHud();
  assert.equal(panelText(),'Vehículos particulares: — · Transporte público: — · Camiones: —','missing count never falls back to stale HTML totals');
  assert.equal(presentation.evaluate('runPanel.children.length'),4,'private, public and freight fleet counts');
  assert.equal(presentation.evaluate('technicalHelp.contains(runIdentityLabel) && !runPanel.contains(runIdentityLabel)'),true);
  assert.equal(presentation.evaluate('hud.contains(runError) && !technicalHelp.contains(runError)'),true,'errors remain outside collapsed Help');
  assert.equal(presentation.evaluate('technicalHelpContent.contains(info) && !uiShell.children.includes(info)'),true,
    'extended technical diagnostics stay in Ayuda, separate from the six-field card');
  const shell=fs.readFileSync('python/visualizador_z1_continuous.html','utf8');
  const compactStyle=shell.match(/#simz1-run-panel\{([^}]+)\}/)[1];
  assert.match(compactStyle,/pointer-events:none/,'compact count does not intercept map clicks');
  assert.match(compactStyle,/width:max-content/);assert.match(compactStyle,/place-self:end end/);
  assert.equal(presentation.evaluate('technicalHelp.contains(runFields.get("run_id"))'),true);
  assert.equal(presentation.evaluate('hud.contains(runError) && hud.contains(runRetry) && !technicalHelp.contains(runError) && !technicalHelp.contains(runRetry)'),true,'errors and retry remain outside collapsed Help');
  presentation.api.setSpeed(1);presentation.frame(1000);
  const beforeToggle=JSON.stringify(presentation.api.getState());
  const beforeUpdates=presentation.sandbox.deckInstance.updates,hudToggleRequests=presentation.requests.length;
  presentation.evaluate('hideBar.onclick()');
  assert.equal(presentation.evaluate('hud.hidden && !showBar.hidden && showBar.focused'),true);
  assert.equal(presentation.evaluate('showBar.attributes["aria-expanded"]'),'false');
  assert.equal(presentation.evaluate('showBar.attributes["aria-controls"]'),'simz1-controls');
  assert.equal(JSON.stringify(presentation.api.getState()),beforeToggle,'hiding preserves all replay/cache state');
  assert.equal(presentation.sandbox.deckInstance.updates,beforeUpdates,'hiding never updates Deck/camera/layers');
  assert.equal(presentation.requests.length,hudToggleRequests,'hiding makes no data requests');
  presentation.frame(2000);
  assert.equal(presentation.api.getState().current,2,'replay continues while controls are hidden');
  const reopened=harness({},null,null,session);
  assert.equal(reopened.evaluate('hud.hidden && !showBar.hidden'),true,'preference survives another viewer in the session');
  presentation.api.setSpeed(120);presentation.frame(2100);
  assert.equal(presentation.api.getState().current,14,'120x continues while controls are hidden');
  const beforeShow=JSON.stringify(presentation.api.getState());
  presentation.evaluate('showBar.onclick()');
  assert.equal(JSON.stringify(presentation.api.getState()),beforeShow,'showing preserves replay/cache state');
  assert.equal(presentation.evaluate('!hud.hidden && showBar.hidden && hideBar.focused'),true);
  assert.equal(presentation.evaluate('hideBar.attributes["aria-expanded"]'),'true');
  assert.equal(stored.get('simz1.controls.hidden'),'false');
  const storageUnavailable=harness();storageUnavailable.evaluate('hideBar.onclick();showBar.onclick()');
  assert.equal(storageUnavailable.evaluate('hud.hidden'),false,'controls work when sessionStorage is unavailable');

  {
    const camera=harness(),instance=camera.api.deck,props=instance.props;
    camera.reply(0);await flush();
    const click=(object=null,type='click')=>{
      camera.listeners.pointerdown({target:camera.canvas,pointerType:'mouse'});
      props.onClick({object},{type,tapCount:type==='dblclick' ? 2 : 1});
    };
    const view=()=>JSON.stringify(camera.api.getState().camera.viewState);
    const initialView=view();
    assert.equal(props.controller.dragMode,'pan');assert.equal(props.controller.dragPan,true);
    assert.equal(props.controller.dragRotate,false);assert.equal(props.controller.doubleClickZoom,false);
    assert.equal(props.controller.scrollZoom,true);assert.equal(props.getCursor({isDragging:false}),'grab');
    click();assert.equal(camera.api.getState().camera.mode,'pan');
    click(null,'dblclick');assert.equal(camera.api.getState().camera.mode,'rotate');
    assert.equal(view(),initialView,'double click does not zoom or reset the view');
    assert.equal(props.controller.dragMode,'rotate');assert.equal(props.controller.dragRotate,true);
    assert.equal(props.controller.dragPan,false);assert.equal(props.controller.scrollZoom,true);
    assert.equal(props.controller.doubleClickZoom,false);
    assert.equal(props.getCursor({isDragging:false}),'crosshair');assert.match(camera.canvas.title,/ROTAR/);
    assert.equal(camera.listeners.click,undefined);assert.equal(camera.listeners.dblclick,undefined);
    assert.equal(camera.timers.size,0,'no competing click/double-click timer');

    props.onDragStart();assert.equal(props.getCursor({isDragging:true}),'grabbing');
    props.onViewStateChange({viewState:{...props.viewState,bearing:359,pitch:55}});
    props.onClick({object:null},{type:'click'});
    assert.equal(camera.api.getState().camera.mode,'rotate','drag cannot be processed as a background click');
    props.onDragEnd();props.onClick({object:null},{type:'click'});
    assert.equal(camera.api.getState().camera.mode,'rotate','post-drag click is ignored until next pointerdown');
    const rotated=view();
    camera.listeners.keydown({key:'Escape'});
    assert.equal(camera.api.getState().camera.mode,'pan');assert.equal(view(),rotated);
    click(null,'dblclick');click();
    assert.equal(camera.api.getState().camera.mode,'pan');assert.equal(view(),rotated,'single click preserves orientation');

    camera.listeners.pointerdown({target:camera.canvas,pointerType:'mouse'});props.onDragStart();
    props.onViewStateChange({viewState:{...props.viewState,longitude:-90.51,latitude:14.64}});props.onDragEnd();
    assert.equal(props.viewState.bearing,359);assert.equal(props.viewState.pitch,55,'panning retains rotation');
    props.onViewStateChange({viewState:{...props.viewState,zoom:16}});
    assert.equal(props.viewState.zoom,16,'wheel/controller view state is accepted');
    props.onViewStateChange({viewState:{...props.viewState,pitch:100}});assert.equal(props.viewState.pitch,60);
    props.onViewStateChange({viewState:{...props.viewState,pitch:-10}});assert.equal(props.viewState.pitch,0);
    const valid=view();
    props.onViewStateChange({viewState:{...props.viewState,pitch:NaN}});assert.equal(view(),valid);
    click(null,'dblclick');
    const cameraState=JSON.stringify(camera.api.getState().camera);
    camera.listeners.pointerdown({target:camera.evaluate('hideBar'),pointerType:'mouse'});
    camera.evaluate('hideBar.onclick()');
    camera.listeners.pointerdown({target:camera.evaluate('showBar'),pointerType:'mouse'});
    camera.evaluate('showBar.onclick()');
    assert.equal(JSON.stringify(camera.api.getState().camera),cameraState,'HUD keeps camera and mode');
    camera.api.pause();camera.api.seek(121);camera.reply(1);await flush();
    camera.api.setSpeed(1);camera.api.play();camera.frame(1000);camera.api.pause();
    assert.equal(JSON.stringify(camera.api.getState().camera),cameraState,'seek/window/play/pause never reset camera');
    assert.equal(camera.api.deck,instance,'same Deck instance throughout');
    console.log('PASS: camera pan/rotate, exclusive click handling, drag guards, controlled view state, pitch bounds, HUD and replay continuity');
  }

  const h=harness();const deck=h.api.deck,roads=h.api.layers[0];
  assert.equal(h.api.getState().buffering,true);h.frame(5000);assert.equal(h.api.getState().current,0);
  h.reply(0);await flush();assert.equal(h.api.getState().buffering,false);assert.ok(h.request(1),'prefetch immediate successor');
  h.api.pause();const updates=h.sandbox.deckInstance.updates;h.frame(6000);h.frame(7000);
  assert.equal(h.sandbox.deckInstance.updates,updates,'paused frames do not redraw/rebuild layers');
  assert.equal(h.evaluate('seeker.min'),0);assert.equal(h.evaluate('seeker.max'),86400);
  assert.equal(h.evaluate('runFields.get("persons_generated").textContent'),'179235');
  assert.equal(h.evaluate('runFields.get("planned_trips").textContent'),'358470');
  assert.equal(h.evaluate('runFields.get("reconstructed_vehicles").textContent'),'142000');
  assert.equal(h.api.getState().visibleMarkers,0);
  assert.equal(h.evaluate('clock.textContent'),'Hora simulada 00:00:00 | Dibujados 0 | 120x');
  assert.match(h.evaluate('runScope.textContent'),/fuente: 25 h/);
  assert.match(h.evaluate('runScope.textContent'),/no recalculados a 24 h/);
  assert.match(h.evaluate('technicalStats.textContent'),/Vehículos con eventos: 144000/);
  assert.match(h.evaluate('technicalStats.textContent'),/Activos QSim: no disponibles/);
  assert.equal(h.evaluate('technicalHelp.open'),false);
  assert.equal(h.evaluate('hud.contains(totalAgents)'),false,'no duplicate global count in controls');
  assert.equal(h.evaluate('legend.innerHTML').replace(/<[^>]+>/g,'').replace('&gt;','>').replace('&lt;','<'),
    'Verde >40 | Amarillo 15–40 | Rojo <15 | Blanco = 0 km/h');
  h.setHudStatus(503);
  const hudFailure=h.api.reloadHud();
  assert.equal(h.evaluate('runFields.get("persons_generated").textContent'),'—','reload clears prior values synchronously');
  assert.doesNotMatch(h.evaluate('clock.textContent'),/Personas|totales/);
  assert.equal(h.evaluate('runFields.get("private_vehicles").textContent'),'—');
  await hudFailure;
  assert.equal(h.api.getState().hud.status,'error');
  assert.match(h.evaluate('runError.textContent'),/Detalle técnico en Ayuda/);
  assert.match(h.evaluate('runErrorDetail.textContent'),/HTTP 503/);
  assert.equal(h.evaluate('technicalHelp.contains(runErrorDetail)'),true);
  assert.equal(h.viewerErrors.length,0,'HUD failure is not repeated in the map error log');
  assert.equal(h.evaluate('runScope.textContent'),'');
  assert.equal(h.evaluate('[...runFields.values()].every(node=>node.textContent==="—")'),true);
  assert.equal(h.api.getState().paused,true);assert.equal(h.api.getState().current,0);
  h.setHudStatus(200);const hudRetry=h.api.reloadHud();
  assert.equal(h.api.getState().hud.error,null,'retry clears old error immediately');
  await hudRetry;
  assert.equal(h.evaluate('runError.textContent'),'');
  assert.equal(h.evaluate('runErrorDetail.textContent'),'');
  assert.equal(h.evaluate('runErrorDetail.hidden'),true);
  assert.equal(h.viewerErrors.length,0,'successful retry leaves no stale global total error');
  assert.equal(h.evaluate('runFields.get("persons_generated").textContent'),'179235');
  for(const [field,value] of [['run_id','another-run'],['iteration',1],['run_manifest_sha256','f'.repeat(64)],['source_version','e'.repeat(64)]]) {
    h.evaluate(`runHud.options={...runHud.options,${field}:${JSON.stringify(value)}}`);
    await h.api.reloadHud();
    assert.equal(h.api.getState().hud.status,'error');
    assert.match(h.evaluate('runErrorDetail.textContent'),/Identidad de indicadores incompatible/);
    assert.equal(h.evaluate('[...runFields.values()].every(node=>node.textContent==="—")'),true,
      'incompatible '+field+' cannot leave prior-run totals');
    h.evaluate('runHud.options=config.continuous');await h.api.reloadHud();
    assert.equal(h.api.getState().hud.status,'ready');
    assert.equal(h.evaluate('runErrorDetail.textContent'),'');
  }
  assert.equal(h.viewerErrors.length,0,'identity failures remain one technical HUD detail and clear on recovery');
  assert.equal(h.api.getState().clockFormat,'24h');
  for(const [seconds,h24,h12] of [[0,'00:00:00','12:00:00 AM'],[540,'00:09:00','12:09:00 AM'],
    [43740,'12:09:00','12:09:00 PM'],[86340,'23:59:00','11:59:00 PM'],[43199,'11:59:59','11:59:59 AM'],
    [43200,'12:00:00','12:00:00 PM'],[86399,'23:59:59','11:59:59 PM'],
    [86400,'24:00:00 (fin de observación)','24:00:00 (fin de observación)']]) {
    assert.equal(h.evaluate(`formatClock(${seconds},'24h')`),h24);
    assert.equal(h.evaluate(`formatClock(${seconds},'12h')`),h12);
  }
  assert.equal(h.evaluate('formatClock(86401)'),'Fuera de jornada');
  assert.equal(h.evaluate('formatClock(90000)'),'Fuera de jornada');
  assert.equal(h.evaluate('JSON.stringify(continuousReplay.bounds(720))'),'[86400,86520]','legacy source windows keep their native identity');
  assert.equal(h.evaluate('replayTrip({Departure:86390,Arrival:86400,Status:"completed"}).Status'),'completed','arrival exactly at closure is observed');
  assert.equal(h.evaluate('replayTrip({Departure:86390,Arrival:86400,Status:"completed"}).Arrival'),86400,'never replace an observed arrival');
  assert.equal(h.evaluate('replayTrip({Departure:86390,Abort:86400,Status:"aborted"}).Status'),'censored','abort exactly at closure is a censored trip');
  assert.equal(h.evaluate('replayTrip({Departure:86390,Abort:86399,Status:"aborted"}).Status'),'aborted','real abort before closure remains observed');
  assert.equal(h.evaluate('replayTrip({Departure:86390,Abort:86399,Status:"censored"}).Status'),'censored','native censoring is never promoted to real abort');
  h.api.setClockFormat('12h');assert.match(h.evaluate('clock.textContent'),/^Hora simulada 12:00:00 AM/);
  h.evaluate('clockFormatButton.onclick()');assert.match(h.evaluate('clock.textContent'),/^Hora simulada 00:00:00/);
  h.api.seek(-100);assert.equal(h.api.getState().current,0,'negative seek clamps to day start');
  h.api.seek(Number.NaN);assert.equal(h.api.getState().current,0,'invalid seek cannot poison clock');
  assert.equal(h.evaluate("hud.children.filter(x=>x.className==='simz1-block-navigation').length"),0);
  h.api.seek(86399);assert.equal(h.request(1).options.signal.aborted,true,'seek cancels obsolete prefetch');
  h.reply(719);await flush();assert.equal(h.api.getState().current,86399);
  assert.equal(h.count('trips'),1);assert.equal(h.api.layers[0],roads,'fixed map layer retained');
  assert.equal(h.api.deck,deck,'one Deck instance');assert.equal(h.sandbox.window.location.href,'');
  assert.equal(h.evaluate('timelines.get("a")[0].Max_Speed_kmh'),43.2,'full-trip native maximum retained');
  h.api.selectActive();assert.equal(h.count('selected-history'),0,'no partial route shown as complete');
  h.journey();await flush();assert.equal(h.api.getState().selectedRecords,3);
  const selectedKey=h.api.getState().selectedKey;
  {
    const props=h.sandbox.deckInstance.props,marker=props.layers.find(layer=>layer.id==='trips').props.data[0];
    const click=(object,type='click')=>{
      h.listeners.pointerdown({target:h.canvas,pointerType:'mouse'});
      props.onClick({object},{type,tapCount:type==='dblclick' ? 2 : 1});
    };
    click(marker);assert.equal(h.api.getState().selectedKey,selectedKey,'click retains selected vehicle');
    click(marker,'dblclick');assert.equal(h.api.getState().camera.mode,'pan','double click on vehicle cannot enable rotation');
    click(null,'dblclick');assert.equal(h.api.getState().selectedKey,selectedKey,'background double click is not also a selection click');
    props.onDragStart();props.onClick({object:null},{type:'click'});props.onDragEnd();
    props.onClick({object:null},{type:'click'});
    assert.equal(h.api.getState().selectedKey,selectedKey,'drag never clears the selected vehicle');
    h.listeners.keydown({key:'Escape'});assert.equal(h.api.getState().selectedKey,null,'Escape closes pinned information');
    click(marker);assert.equal(h.api.getState().selectedKey,selectedKey,'reselection restores the same identity');
    assert.equal(h.api.getState().selectedJourneyStatus,'loading','Escape releases the prior complete journey');
    assert.equal(h.count('selected-future'),0,'no partial route while the new complete journey is pending');
    h.journey();await flush();
    assert.equal(h.api.getState().selectedJourneyStatus,'complete');
  }
  const selectedState=JSON.stringify(h.api.getState()),selectedUpdates=h.sandbox.deckInstance.updates;
  h.evaluate('hideBar.onclick()');
  h.listeners.pointerdown({target:h.evaluate('showBar'),pointerType:'mouse'});
  h.evaluate('showBar.onclick()');
  assert.equal(JSON.stringify(h.api.getState()),selectedState,'recovery button preserves selection, time, speed and cache');
  assert.equal(h.sandbox.deckInstance.updates,selectedUpdates,'toggle leaves camera and layers intact');
  assert.equal(h.count('selected-future'),1,'future route stops at day closure');
  assert.equal(h.count('selected-destination'),0,'a source arrival after midnight is not a day arrival');
  assert.equal(h.api.getState().selectedTripStatus,'censored');assert.equal(h.api.getState().selectedArrival,null);
  assert.match(h.evaluate('info.textContent'),/censurado a las 24 h/);
  assert.equal(h.evaluate('selectedHistory[0].Trip.Arrival'),86430,'native arrival remains unchanged');
  assert.equal(h.evaluate('selectedHistory[0].Trip.Status'),'completed','source status remains unchanged');
  assert.match(h.evaluate('clock.textContent'),/^Hora simulada 23:59:59/);
  assert.equal(h.request(720),undefined,'paused inspection does not request the next window');
  h.api.setSpeed(1);h.api.play();h.api.seek(86399);h.reply(720);await flush();h.frame(8000);
  assert.equal(h.api.getState().current,86400);assert.equal(h.api.getState().buffering,false);
  assert.equal(h.api.getState().selectedKey,selectedKey);assert.equal(h.api.getState().selectedRecords,3);
  assert.equal(h.evaluate('signalStateAt("signal","group",current)'),'GREEN');
  assert.ok(h.evaluate('clock.textContent').startsWith('Hora simulada 24:00:00 |'));
  assert.match(h.evaluate('clock.title'),/fin de observación/);
  assert.equal(h.api.getState().paused,true);assert.equal(h.request(721),undefined,'never prefetch beyond the closure window');
  h.api.play();assert.equal(h.api.getState().paused,true,'play at closure does not open another day');
  assert.equal(h.evaluate('layers.find(l=>l.id==="trips").props.data[0].position[0]'),10*fixtureDegreesPerMetre);
  assert.equal(h.count('selected-history'),1);assert.equal(h.count('selected-future'),0);
  assert.match(h.evaluate('info.textContent'),/censurado a las 24 h/);
  h.api.setClockFormat('12h');assert.match(h.evaluate('clock.textContent'),/^Hora simulada 24:00:00 \|/);
  h.api.setClockFormat('24h');h.api.setSpeed(120);h.frame(8100);assert.equal(h.api.getState().current,86400);
  h.api.pause();h.api.seek(86395);assert.equal(h.api.getState().current,86395);
  assert.equal(h.api.getState().selectedKey,selectedKey);
  assert.equal(h.evaluate('layers.find(l=>l.id==="trips").props.data[0].position[0]'),5*fixtureDegreesPerMetre);
  h.api.seek(86435);assert.equal(h.api.getState().selectedKey,selectedKey,'selection identity remains at day closure');
  assert.equal(h.api.getState().current,86400,'seek after midnight clamps to closure');
  assert.equal(h.count('selected-future'),0,'no second-day route is displayed');
  h.api.seek(86395);assert.equal(h.count('selected-future'),1,'reverse seek restores the same day route');
  h.api.play();h.frame(8200);assert.equal(h.api.getState().current,86400,'120x stops exactly at closure');
  assert.equal(h.api.getState().paused,true);
  console.log('PASS: exact 0..86400 day, 12/24 h clock, 23:59:59 to closing24:00, clamped seeks, 1x/120x and censored midnight trip with native source untouched');

  const hudClock=harness();hudClock.api.pause();hudClock.reply(0);await flush();
  for(const [time,label] of [[540,'00:09:00'],[43740,'12:09:00'],[86340,'23:59:00'],[86400,'24:00:00']]) {
    hudClock.api.seek(time);
    const index=Math.floor(time/120);
    if(hudClock.request(index))hudClock.reply(index);
    await flush();
    assert.equal(hudClock.api.getState().current,time);
    assert.equal(hudClock.api.getState().paused,true);
    assert.ok(hudClock.evaluate('clock.textContent').startsWith('Hora simulada '+label+' | Dibujados '));
    assert.match(hudClock.evaluate('clock.textContent'),/Dibujados \d+ \| 120x$/);
    assert.equal(hudClock.evaluate('runFields.get("planned_trips").textContent'),'358470');
  }
  console.log('PASS: HUD real totals 179235 with zero visible markers, distinct trips/vehicles, API failure clearing/recovery and paused seeks at 00:09,12:09,23:59,24:00');

  h.api.seek(40000);const failedIndex=Math.floor(40000/120);
  assert.equal(h.evaluate('seeker.value'),40000,'slider retains requested hour while clock waits for data');
  h.reply(failedIndex,{},500);await flush();assert.match(h.api.getState().error,/HTTP 500/);
  const frozen=h.api.getState().current;h.api.play();h.frame(100000);assert.equal(h.api.getState().current,frozen);
  h.api.retry();h.reply(failedIndex);await flush();assert.equal(h.api.getState().current,40000);
  h.frame(100100);assert.ok(Math.abs(h.api.getState().current-40012)<1e-8,'buffering wall time is never added');
  h.api.pause();h.api.seek(50000);h.api.seek(60000);
  const stale=h.request(Math.floor(50000/120));assert.equal(stale.options.signal.aborted,true);
  h.reply(Math.floor(50000/120));await flush();assert.equal(h.api.getState().current,40012);
  h.reply(500);await flush();assert.equal(h.api.getState().current,60000);
  assert.equal(h.api.getState().selectedKey,selectedKey,'full selected journey outlives its window');
  assert.equal(h.api.getState().cache.cachedWindows<=3,true);
  h.api.seek(70000);h.reply(Math.floor(70000/120),{run_id:'wrong-run'});await flush();
  assert.match(h.api.getState().error,/Identidad/);assert.equal(h.api.getState().current,60000);
  h.api.retry();h.reply(Math.floor(70000/120));await flush();assert.equal(h.api.getState().current,70000);
  h.api.seek(90000);h.reply(720);await flush();assert.equal(h.api.getState().current,86400);
  assert.equal(h.api.getState().paused,true);assert.ok(h.evaluate('clock.textContent').startsWith('Hora simulada 24:00:00 |'));
  assert.equal(h.api.deck,deck);assert.equal(h.api.layers[0],roads);
  assert.ok(h.api.getState().cache.peakPending<=2);assert.ok(h.api.getState().cache.peakCachedWindows<=3);
  assert.ok(h.api.getState().cache.evictions>0);
  console.log('PASS: frozen clock under HTTP failure, explicit retry, cancelled/stale seeks, identity rejection, bounded cache/requests and exact 24:00 endpoint');

  const boundary=harness();boundary.reply(0);await flush();boundary.api.seek(119);boundary.api.setSpeed(1);
  boundary.frame(0);boundary.frame(1000);assert.equal(boundary.api.getState().current,119);
  assert.equal(boundary.api.getState().pendingTime,120);boundary.frame(10000);assert.equal(boundary.api.getState().current,119);
  boundary.reply(1);await flush();assert.equal(boundary.api.getState().current,120);
  boundary.frame(11000);assert.equal(boundary.api.getState().current,121,'automatic crossing resumes without skipped buffered time');
  const small=harness({cache_bytes:1});small.reply(0);await flush();
  assert.equal(small.api.getState().cache.cachedWindows,1);assert.equal(small.api.getState().cache.oversizedActiveWindow,true);
  assert.ok(small.request(1),'the base cache budget cannot disable successor prefetch');
  small.api.seek(121);small.reply(1);await flush();assert.equal(small.api.getState().cache.cachedWindows,1);
  assert.equal(small.api.getState().cache.retainedSegments,0);
  const endpoint=harness({end_seconds:86400,window_count:720,data_end_seconds:86400});endpoint.api.pause();endpoint.api.seek(86400);
  endpoint.reply(719,{segments:[segment('last-native',86399,86401,0,2)],
    trips:{[key]:{...trip,Departure:86399,Arrival:86401}},
    signal_replay:{series:[{system_id:'signal',group_id:'group',states:[[86400,'YELLOW']]}]},
    lane_replay:{events:[{vehicle:'a',link:'last-native',lane:'last-native.original',type:'entered lane',time:86400}]}});
  await flush();assert.equal(endpoint.api.getState().current,86400);assert.equal(endpoint.count('trips'),1);
  assert.equal(endpoint.evaluate('signalStateAt("signal","group",current)'),'YELLOW');
  assert.equal(endpoint.evaluate('layers.find(l=>l.id==="trips").props.data[0].Observed_Queue_ID'),'last-native.original');
  assert.equal(endpoint.evaluate('timelines.get("a")[0].timestamps[1]'),86401,'native evidence past slider endpoint is preserved');
  assert.equal(endpoint.request(720),undefined,'24 h source stops at its own last native window');
  endpoint.api.selectActive();endpoint.journey({records:[{...segment('last-native',86399,86401,0,2),Trip:{...trip,Departure:86399,Arrival:86401}}]});await flush();
  assert.equal(endpoint.api.getState().selectedTripStatus,'censored');assert.equal(endpoint.api.getState().selectedArrival,null);
  assert.ok(Math.abs(endpoint.evaluate('layers.find(l=>l.id==="selected-history").props.data[0].path.at(-1)[0]')-fixtureDegreesPerMetre)<1e-12,'display route clips at the native interpolated closure position');
  assert.equal(endpoint.count('selected-future'),0);
  console.log('PASS: automatic noncached boundary resumes exact target and one oversized native window is retained transparently without truncation');
  for(const ready of [false,true])for(const playbackSpeed of [1,120]) {
    const crossing=harness(),native={...segment('crossing',28070,28110,0,40),Replay_Journey_Key:key};
    const data={segments:[native],trips:{[key]:{Trip_ID:'boundary-trip',Departure:28070,Arrival:28110,Status:'completed'}}};
    crossing.api.pause();crossing.api.seek(28079);crossing.reply(233,structuredClone(data));await flush();
    assert.equal(crossing.request(234),undefined,'paused loaded window does not speculate');
    crossing.api.setSpeed(playbackSpeed);crossing.api.play();crossing.api.seek(28079);
    if(ready){crossing.reply(234,structuredClone(data));await flush();}
    const originalTimes=crossing.evaluate('JSON.stringify(timelines.get("a")[0].timestamps)');
    crossing.frame(1000/playbackSpeed);
    if(!ready) {
      assert.equal(crossing.api.getState().current,28079);assert.equal(crossing.api.getState().pendingTime,28080);
      assert.equal(crossing.api.getState().visibleMarkers,1,'last complete frame remains available');
      crossing.reply(234,structuredClone(data));await flush();
    }
    assert.equal(crossing.api.getState().current,28080);assert.equal(crossing.api.getState().visibleMarkers,1);
    crossing.api.pause();const held=crossing.api.getState().current;crossing.frame(2000/playbackSpeed);
    assert.equal(crossing.api.getState().current,held);
    crossing.api.play();crossing.frame(3000/playbackSpeed);
    assert.ok(Math.abs(crossing.api.getState().current-28081)<1e-7);
    // At 120x this RAF is only 8.33 ms after play's immediate draw. Pause
    // presents the exact current instant without requiring an extra 120 Hz draw.
    crossing.api.pause();
    assert.equal(crossing.evaluate('JSON.stringify(timelines.get("a")[0].timestamps)'),originalTimes);
    assert.ok(Math.abs(crossing.evaluate('layers.find(l=>l.id==="trips").props.data[0].position[0]')-11*fixtureDegreesPerMetre)<1e-12);
    const perf=crossing.api.getPerformance();
    assert.ok(perf.transitions.some(row=>row.index===234 && row.readyBeforeDemand===ready));
    assert.ok(perf.loader.activationSamples.every(row=>Number.isFinite(row.activationMs)));
    crossing.api.seek(28079);
    if(crossing.api.getState().buffering){crossing.reply(233,structuredClone(data));await flush();}
    assert.equal(crossing.api.getState().current,28079);assert.equal(crossing.api.getState().visibleMarkers,1);
  }
  console.log('PASS: 07:47:59 to 07:48:01 at 1x/120x, ready/late prefetch, pause/resume and backward seek');
  console.log('PASS: slider stops exactly86400 while native segment endpoint86401, closing signal and queue evidence remain available; source window identity is preserved');
  const errors=harness();errors.api.pause();
  for(let index=1;index<=24;index++) {
    errors.api.seek(index*120);errors.reply(index,{},400);await flush();
    assert.equal(errors.api.getState().buffering,true);assert.equal(errors.evaluate('continuousRetry.hidden'),false);
    assert.ok(errors.api.getState().cache.rememberedFailures<=16);
  }
  errors.api.retry();errors.reply(24);await flush();assert.equal(errors.api.getState().current,24*120);
  assert.equal(errors.api.getState().error,null);assert.equal(errors.evaluate('continuousRetry.hidden'),true);
  assert.equal(errors.api.getState().cache.pendingRequests,0,'paused error recovery has no speculative successor');
  console.log('PASS: repeated HTTP errors retain at most 16 failures; visible retry recovers latest seek without stale requests');
  const wrongJourney=harness();wrongJourney.api.pause();wrongJourney.api.seek(86395);wrongJourney.reply(719);await flush();
  wrongJourney.api.selectActive();wrongJourney.journey({source_version:'d'.repeat(64)});await flush();
  assert.equal(wrongJourney.api.getState().selectedJourneyStatus,'unavailable','a route from a different export is never displayed');
  assert.equal(wrongJourney.api.getState().selectedRecords,0);
  const journeyRequest=wrongJourney.requests.find(r=>r.url.startsWith('/api/journey'));
  assert.equal(new URL(journeyRequest.url,'http://local').searchParams.get('source_version'),wrongJourney.identity.source_version);
  assert.equal(journeyRequest.options.cache,'no-store');
  wrongJourney.api.retryJourney();wrongJourney.journey();await flush();
  assert.equal(wrongJourney.api.getState().selectedJourneyStatus,'complete');
  const journeyError=harness();journeyError.api.pause();journeyError.api.seek(86395);journeyError.reply(719);await flush();
  journeyError.api.selectActive();journeyError.journey({retryable:false},503);await flush();
  assert.equal(journeyError.api.getState().selectedJourneyStatus,'unavailable');
  assert.match(journeyError.api.getState().selectedJourneyError,/HTTP 503/);
  assert.equal(journeyError.evaluate('journeyRetry.hidden'),false);
  assert.equal(journeyError.count('selected-history'),0,'failed fetch cannot expose a partial full trip');
  const failedJourneyKey=journeyError.api.getState().selectedKey;
  journeyError.api.retryJourney();assert.equal(journeyError.evaluate('journeyRetry.hidden'),true);
  journeyError.journey();await flush();assert.equal(journeyError.api.getState().selectedJourneyStatus,'complete');
  assert.equal(journeyError.api.getState().selectedKey,failedJourneyKey);
  assert.equal(journeyError.api.getState().selectedRecords,3);
  assert.equal(journeyError.count('selected-history'),1);
  console.log('PASS: dedicated manual journey retry recovers explicitly non-retryable HTTP503 without losing selection or showing partial route');
  const localSeek=harness();localSeek.api.pause();localSeek.api.seek(63000);localSeek.reply(525);await flush();
  assert.equal(localSeek.request(526),undefined,'paused seek loads only the required window');
  localSeek.api.play();localSeek.api.seek(63000);localSeek.api.pause();
  const usefulPrefetch=localSeek.request(526),requestCount=localSeek.api.getState().cache.requests;
  assert.ok(usefulPrefetch);localSeek.api.seek(63005);localSeek.api.seek(63119);
  assert.equal(usefulPrefetch.options.signal.aborted,false,'same-window seek preserves useful pending successor');
  assert.equal(localSeek.request(526),usefulPrefetch,'same successor request identity survives repeated seeks');
  assert.equal(localSeek.api.getState().cache.requests,requestCount,'same-window seeks do not duplicate server queries');
  localSeek.reply(526);await flush();localSeek.api.seek(63120);
  assert.equal(localSeek.api.getState().current,63120);assert.equal(localSeek.api.getState().buffering,false);
  console.log('PASS: seeks within window525 retain the single useful526 prefetch and cross without duplicated server queries');
  const fast=harness();fast.reply(0);await flush();fast.api.setSpeed(1);fast.api.play();
  const initialCacheState=fast.evaluate('continuousState');
  fast.evaluate(`let statusWrites=[];let statusValue=continuousStatus.textContent;
    Object.defineProperty(continuousStatus,'textContent',{get:()=>statusValue,set:value=>{statusWrites.push(value);statusValue=value;}});`);
  fast.frame(0);fast.frame(1000);fast.frame(2000);
  assert.equal(fast.api.getState().current,2);
  assert.equal(fast.evaluate('continuousState'),initialCacheState,'active-window frames do not notify an unchanged cache');
  assert.equal(fast.evaluate('statusWrites.length'),0,'active-window playback never briefly announces loading or rewrites stable status');
  assert.equal(fast.api.getState().buffering,false);
  console.log('PASS: ready-window frames advance time without cache churn or repeated loading/status DOM writes');
  const busy=harness();busy.reply(0,{},503,'1.5');await flush();
  assert.equal(busy.api.getState().error,null,'transient busy response buffers without a permanent error');
  assert.equal(busy.api.getState().cache.pendingRequests,1);assert.equal(busy.api.getState().cache.retries503,1);
  assert.equal(await busy.retryTimer(),1500,'honor Retry-After before the next HTTP attempt');
  busy.reply(0);await flush();assert.equal(busy.api.getState().buffering,false);
  assert.equal(busy.requests.filter(r=>new URL(r.url,'http://localhost').searchParams.get('index')==='0').length,2);
  assert.equal(busy.api.getState().cache.peakPending,1,'mandatory retry finishes before successor speculation starts');
  busy.reply(1,{},503);await flush();const retryCount=busy.api.getState().cache.retries503;
  busy.api.seek(20);busy.api.seek(119);
  assert.equal(busy.api.getState().cache.retries503,retryCount,'seeking within the current window leaves one successor retry');
  assert.equal(busy.timers.size,1);await busy.retryTimer();busy.reply(1);await flush();busy.api.seek(120);
  assert.equal(busy.api.getState().current,120);assert.equal(busy.api.getState().buffering,false);
  console.log('PASS: HTTP503 retries automatically in its original slot, honors Retry-After and preserves useful successor retries');
  const exhausted=harness(),delays=[];
  for(let attempt=0;attempt<8;attempt++) {
    exhausted.reply(0,{},503);await flush();
    assert.equal(exhausted.api.getState().error,null);delays.push(await exhausted.retryTimer());
  }
  assert.deepEqual(delays,[1000,2000,4000,8000,10000,10000,10000,10000]);
  assert.equal(exhausted.evaluate('continuousRetry.hidden'),true);
  assert.equal(exhausted.api.getState().cache.httpAttempts,9);assert.equal(exhausted.api.getState().cache.pendingRequests,1);
  exhausted.reply(0);await flush();assert.equal(exhausted.api.getState().buffering,false);
  const abortBackoff=harness();abortBackoff.reply(0,{},503);await flush();
  const obsoleteRequest=abortBackoff.requests[0],obsoleteTimer=[...abortBackoff.timers.values()][0];
  abortBackoff.api.seek(24000);
  assert.equal(obsoleteRequest.options.signal.aborted,true);assert.equal(abortBackoff.timers.size,0);
  obsoleteTimer.fn();await flush();
  assert.equal(abortBackoff.requests.filter(r=>new URL(r.url,'http://localhost').searchParams.get('index')==='0').length,1,'late backoff callback cannot revive an obsolete request');
  abortBackoff.reply(200);await flush();assert.equal(abortBackoff.api.getState().current,24000);
  assert.equal(abortBackoff.api.getState().error,null);assert.ok(abortBackoff.api.getState().cache.peakPending<=2);
  const permanent=harness();permanent.reply(0,{},400);await flush();
  assert.match(permanent.api.getState().error,/HTTP 400/);assert.equal(permanent.timers.size,0);
  const partial=harness({start_seconds:600,end_seconds:1200,window_count:5});
  assert.match(partial.evaluate('technicalHelpContent.innerHTML'),/Fuente parcial: 600\.\.1200 s/);
  const wrongWindow=harness();wrongWindow.api.pause();wrongWindow.api.seek(86400);
  wrongWindow.reply(720,{end_seconds:86400});await flush();
  assert.match(wrongWindow.api.getState().error,/Ventana temporal/,'display boundary cannot replace native source window identity');
  assert.equal(wrongWindow.api.getState().current,0,'incompatible window freezes the prior clock');
  console.log('PASS: sustained503 remains recoverable; abort cancels backoff and stale timer; HTTP400 is never retried');
  // The same native segment straddles two cache windows; neither its geometry
  // nor an estimated lane may depend on the loaded block or paused frame.
  const lanePath=[[-90.52,14.64],[-90.519,14.64]],laneConfig={schema_version:1,available:true,lane_width_m:3,
    links:{east:{num_lanes:2,path:lanePath,length_m:108,opposing_lanes:0,offset_eligible:true,
      native_lanes:{right:{index:1,represented_lanes:1,start_m:80}}}}};
  const laneSegment={vehicle:'lane-car',Agent_ID:'lane-person',Link_ID:'east',Replay_Journey_Key:key,
    timestamps:[100,140],path:lanePath,Speed_kmh:9.72};
  for(const observed of [false,true]) {
    const lanes=harness({},laneConfig),native=observed ? [{vehicle:'lane-car',link:'east',lane:'right',type:'entered lane',time:110}] : [];
    const overrides={segments:[structuredClone(laneSegment)],trips:{[key]:{Trip_ID:'lane-trip',Departure:100,Arrival:140,Status:'completed'}},
      lane_replay:{events:native}};
    lanes.reply(0,overrides);await flush();lanes.api.pause();lanes.api.seek(119);
    const before=JSON.parse(lanes.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data[0])'));
    assert.equal(before.Visual_Lane_Source,observed ? 'native' : 'estimated');
    assert.match(lanes.evaluate('tooltipText(layers.find(l=>l.id==="trips").props.data[0])'),
      observed ? /ID nativo/ : /asignacion estimada/);
    lanes.api.seek(120);lanes.reply(1,overrides);await flush();
    const across=JSON.parse(lanes.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data[0])'));
    assert.equal(across.Visual_Lane_Index,before.Visual_Lane_Index);
    assert.equal(across.Visual_Lane_Source,before.Visual_Lane_Source);
    assert.equal(across.Visual_Lane_Offset_Meters,before.Visual_Lane_Offset_Meters);
    lanes.frame(5000);lanes.frame(10000);
    assert.equal(lanes.api.getState().current,120);
    lanes.api.seek(119);
    assert.equal(lanes.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data[0])'),JSON.stringify(before));
    assert.equal(lanes.evaluate('JSON.stringify(timelines.get("lane-car").map(({path,timestamps,Speed_kmh})=>({path,timestamps,Speed_kmh})))'),
      JSON.stringify([{path:laneSegment.path,timestamps:laneSegment.timestamps,Speed_kmh:laneSegment.Speed_kmh}]),
      'hydrated segments retain native geometry, times and measured speed through window replacement');
    assert.equal(lanes.api.getState().visualLanes[observed ? 'nativeMarkers' : 'estimatedMarkers'],1);
  }
  console.log('PASS: estimated/native lanes retain assignment at window boundary, pause and reverse seek; provenance is visible');
  {
    const named=structuredClone(laneConfig);named.links.east.osm_tags={name:'7a Avenida'};
    const labels=harness({},named);labels.reply(0);await flush();labels.api.pause();
    labels.sandbox.deckInstance.getViewports=()=>[{width:1000,height:600,
      project:p=>[(p[0]+90.52)*500000+100,300-(p[1]-14.64)*500000]}];
    const camera=labels.sandbox.deckInstance.props,current=labels.api.getState().current,requests=labels.requests.length;
    camera.onViewStateChange({viewState:{...camera.viewState,zoom:17}});
    assert.equal(labels.count('map-labels'),1,'labels update on zoom while replay is paused');
    camera.onViewStateChange({viewState:{...camera.viewState,zoom:14}});
    assert.equal(labels.count('map-labels'),0);
    assert.equal(labels.api.getState().current,current);assert.equal(labels.requests.length,requests);
    assert.equal(labels.api.getState().paused,true);
  }
  const queuedConfig=structuredClone(laneConfig);queuedConfig.links.east.num_lanes=1;queuedConfig.links.east.native_lanes={};
  const queued=harness({},queuedConfig),queueRecords=['queue-a','queue-b'].map((vehicle,index)=>({
    ...structuredClone(laneSegment),vehicle,Agent_ID:vehicle,Replay_Journey_Key:String(index+1).padStart(64,'0'),
    timestamps:[100,160],Movement_End:110,Wait_Evidence:'native_wait_observation',
    Observed_Waits:{signal_red:{first:110,last:159,attempts:50,sources:['MATSim15_QNode_native_branch'],position_evidence:'queue_exit'}},
    Motion_Plan:{version:1,status:'kinematic',distance_m:100,cap_mps:20,hold_start:110,native_wait_boundary:110,
      phases:[[100,110,0,20,-2],[110,160,100,0,0]]}}));
  const queueNative=JSON.stringify(queueRecords);
  const queuePayload={segments:queueRecords,trips:Object.fromEntries(queueRecords.map(record=>[record.Replay_Journey_Key,
    {Trip_ID:record.vehicle,Departure:100,Arrival:160,Status:'completed'}])),lane_replay:{events:[]}};
  // Production requires the complete native hold closure before repositioning;
  // an isolated visible-window roster is deliberately insufficient evidence.
  const queueKeys=queueRecords.map(record=>JSON.stringify([record.vehicle,record.Replay_Journey_Key,record.Link_ID,record.timestamps]));
  queuePayload.queue_context={schema_version:1,policy:'native-hold-closure-v1',
    by_seed:Object.fromEntries(queueKeys.map(key=>[key,{complete:true,reason:null,record_keys:queueKeys}])),
    segments:queueRecords,transition_segments:[],trips:queuePayload.trips,lane_events:[]};
  queued.reply(0,structuredClone(queuePayload));await flush();queued.api.pause();queued.api.seek(119);
  assert.equal(queued.api.getState().visualQueues.positioned,2);
  const queuePositions=queued.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data.map(m=>m.position))');
  queued.api.seek(120);queued.reply(1,structuredClone(queuePayload));await flush();
  assert.equal(queued.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data.map(m=>m.position))'),queuePositions);
  assert.match(queued.evaluate('queueStatus.textContent'),/Colocados: 2/);
  assert.equal(queued.evaluate('technicalHelp.contains(queueStatus) && !runPanel.contains(queueStatus)'),true,
    'overflow and queue diagnostics stay accessible only in technical help');
  assert.match(queued.evaluate('tooltipText(layers.find(l=>l.id==="trips").props.data[0])'),/Espaciado\/orden inferidos/);
  queued.sandbox.deckInstance.getViewports=()=>[{width:800,height:600,
    project:position=>[400+(position[0]+90.519)*100000,300+(position[1]-14.64)*100000]}];
  const front=queued.api.layers.find(layer=>layer.id==='trips').props.data[0];
  const project=queued.sandbox.deckInstance.getViewports()[0].project,screen=project(front.position);
  queued.sandbox.deckInstance.props.onClick({x:screen[0]+7,y:screen[1],object:null},{pointerType:'mouse'});
  assert.equal(queued.api.getState().selectedKey,queued.evaluate('tripKey(layers.find(l=>l.id==="trips").props.data[0])'));
  const selectedQueue=queued.api.getState().selectedKey;
  queued.api.clearSelection();
  queued.sandbox.deckInstance.props.onClick({x:screen[0]+17,y:screen[1],object:null},{pointerType:'touch'});
  assert.equal(queued.api.getState().selectedKey,selectedQueue,'touch hitbox does not enlarge the visual body');
  queued.api.setQueueGap(4);assert.equal(queued.api.getState().current,120);assert.equal(queued.api.getState().paused,true);
  assert.equal(queued.api.getState().selectedKey,selectedQueue);assert.equal(queued.api.getState().visualQueues.gap_m,4);
  queued.api.setQueueGap(2);queued.api.seek(119);
  assert.equal(queued.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data.map(m=>m.position))'),queuePositions);
  assert.throws(()=>queued.api.setQueueGap(-1),/0\.\.10/);
  queued.evaluate('const gapControl=technicalHelpContent.children.flatMap(node=>node.children || []).find(node=>node.id==="simz1-queue-gap");gapControl.value=11;gapControl.onchange();');
  assert.equal(queued.api.getState().visualQueues.gap_m,2,'invalid gap input cannot escape as a UI exception');
  assert.equal(queued.evaluate('JSON.stringify(timelines.get("queue-a")[0].Motion_Plan)'),JSON.stringify(queueRecords[0].Motion_Plan));
  assert.equal(JSON.stringify(queueRecords),queueNative);
  const diagnostics=queued.api.getVisualDiagnostics();
  assert.equal(diagnostics.counts.active,2);assert.equal(diagnostics.counts.visible,2);assert.equal(diagnostics.counts.omitted,0);
  assert.equal(diagnostics.counts.queued,2);assert.ok(diagnostics.counts.overlapsResolved>0);
  assert.ok(diagnostics.records.every(r=>r.vehicle_id && r.position && r.dimensions_m));
  assert.equal(queued.api.layers.some(l=>l.id==='queue-overflow'),false);
  queued.api.setSafetyEnvelope({lateral_clearance_m:.2});
  assert.equal(queued.api.getState().picking.mouseRadiusPixels,8);assert.equal(queued.api.getState().picking.touchRadiusPixels,18);
  assert.equal(queued.api.layers.find(l=>l.id==='trips').props.data[0].Visual_Body_Width_Meters,1.8);
  queued.api.setSafetyEnvelope({lateral_clearance_m:.1});
  const savedCurrent=queued.api.getState().current;
  const trace=queued.api.traceVehicle('queue-a',[110,115,119]);
  assert.ok(trace.every(r=>r.visible && r.visual_diagnostic.position));
  assert.equal(queued.api.getState().current,savedCurrent,'inspection is read-only, no implicit seek');
  let queueWall=1000;
  for(const replaySpeed of [1,120]) {
    queued.api.pause();queued.api.seek(115);queued.api.setSpeed(replaySpeed);queued.api.play();
    queueWall+=1000/replaySpeed;queued.frame(queueWall);
    assert.equal(queued.api.getState().visibleMarkers,2);
    assert.equal(queued.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data.map(m=>m.position))'),queuePositions);
  }
  queued.api.pause();queued.api.seek(119);
  console.log('PASS: queue spacing, body picking, configurable gap, pause and window/reverse-seek preserve native motion');
  const domain={schema_version:1,mode:'gateway-od',allowed_links:['east','exit'],internal_links:[],
    entry_gateways:{east:{link_id:'east'}},exit_gateways:{exit:{link_id:'exit'}},
    boundary:{type:'Polygon',coordinates:[[[-90.521,14.639],[-90.518,14.639],[-90.518,14.641],[-90.521,14.641],[-90.521,14.639]]]}};
  const spatial=harness({},laneConfig,domain),od={od_type:'external-external',origin_link:'east',destination_link:'exit',
    origin_gateway:'east',destination_gateway:'exit',origin_zone:'synthetic-exterior-entry:east',destination_zone:'synthetic-exterior-exit:exit',
    scope:'observed_z1_only',door_to_door_seconds:null,metadata_source:'synthetic_gateway_od'};
  const spatialTrip={Trip_ID:'spatial-trip',Departure:100,Arrival:140,Status:'completed',OD:od,
    Origin_Position:lanePath[0],Destination_Position:lanePath[1]};
  const spatialPayload={segments:[structuredClone(laneSegment)],trips:{[key]:spatialTrip},lane_replay:{events:[]}};
  spatial.reply(0,spatialPayload);await flush();spatial.api.pause();spatial.api.seek(119);spatial.api.selectActive();
  assert.equal(spatial.api.getState().visibleMarkers,1);assert.ok(spatial.api.getState().selectedKey);
  assert.match(spatial.evaluate('info.textContent'),/Tiempo puerta a puerta: N\/D/);
  spatial.api.seek(120);
  spatial.reply(1,{...spatialPayload,trips:{[key]:{...spatialTrip,OD:undefined}}});await flush();
  assert.match(spatial.api.getState().error,/OD espacial/);
  assert.equal(spatial.api.getState().visibleMarkers,1);assert.equal(spatial.api.getState().loadedVehicles,1);
  assert.ok(spatial.api.getState().selectedKey);assert.equal(spatial.api.getState().current,119);
  assert.equal(spatial.api.getState().visibilityStatus,'waiting_for_window');
  spatial.api.retry();spatial.reply(1,spatialPayload);await flush();
  assert.equal(spatial.api.getState().current,120);assert.equal(spatial.api.getState().visibleMarkers,1);
  assert.equal(spatial.api.getState().error,null);
  spatial.api.selectActive();
  spatial.evaluate('pinned={...pinned,Trip:{...pinned.Trip,Arrival:null,Status:"censored"}};selectAgent(pinned);render()');
  assert.equal(spatial.count('selected-destination'),0,'traffic-exit position alone is never an observed arrival flag');
  assert.match(spatial.evaluate('info.textContent'),/Tiempo completo en tramo modelado Z1: N\/D/);
  assert.match(spatial.evaluate('info.textContent'),/\(censurado; tiempo observado\)/);
  console.log('PASS: spatial OD survives windows; invalid payload retains last validated frame and selection; retry restores data');

  const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];
  const paths={incoming:[xy(0,0),xy(10,0)],short:[xy(10,0),xy(10,.2)],outgoing:[xy(10,.2),xy(10,10)]};
  const ids=Object.keys(paths),times=[[110,120],[120,121],[121,130]],distances=[10,.2,9.8];
  const configTurn={schema_version:1,available:true,links:Object.fromEntries(ids.map((id,i)=>[id,{
    path:paths[id],num_lanes:1,source_way:id,from_node:'n'+i,to_node:'n'+(i+1),osm_tags:{},native_lanes:{},
    movement_source:'effective_car_node_adjacency',allowed_to_links:ids.slice(i+1,i+2)}]))};
  const turnRecords=ids.map((id,i)=>({vehicle:'turn-car',Agent_ID:'turn-person',Replay_Journey_Key:key,Link_ID:id,
    path:paths[id],timestamps:times[i],Motion_Plan:{version:1,status:'constant',distance_m:distances[i],
      phases:[[...times[i],0,distances[i]/(times[i][1]-times[i][0]),0]]}}));
  const tripsTurn={[key]:{Trip_ID:'turn-trip',Departure:110,Arrival:130,Status:'completed'}};
  const turn=harness({},configTurn);
  turn.reply(0,{segments:turnRecords.slice(0,1),context_segments:turnRecords.slice(1,2),trips:tripsTurn});await flush();
  turn.api.pause();turn.api.seek(119.999);turn.api.selectActive();
  const last=turn.api.layers.find(l=>l.id==='trips').props.data[0],selected=turn.api.getState().selectedKey;
  assert.equal(last.Visual_Body_Path.length,2);assert.equal(last.Visual_Body_Opacity,1);
  turn.api.seek(120);
  assert.equal(turn.api.getState().current,119.999);assert.equal(turn.api.getState().visibleMarkers,1);
  assert.equal(turn.api.diagnoseVehicle('turn-car',120).reason,'window_not_loaded');
  turn.reply(1,{segments:turnRecords.slice(1),context_segments:turnRecords.slice(0,1),trips:tripsTurn});await flush();
  const exact=turn.api.layers.find(l=>l.id==='trips').props.data[0];
  assert.equal(exact.Link_ID,'short');assert.equal(exact.Visual_Entity_ID,last.Visual_Entity_ID);
  assert.equal(turn.api.getState().selectedKey,selected);assert.equal(exact.Visual_Body_Length_Meters,4.5);
  assert.ok(Math.abs(exact.Visual_Body_Heading_Degrees-last.Visual_Body_Heading_Degrees)<.1);
  const diagnostic=turn.api.diagnoseVehicle('turn-car');
  assert.equal(diagnostic.previous_link,'incoming');assert.equal(diagnostic.next_link,'outgoing');
  assert.equal(diagnostic.reason,'visible');assert.equal(diagnostic.person_id,'turn-person');
  assert.equal(diagnostic.trip_id,'turn-trip');assert.ok(diagnostic.position);
  turn.api.seek(120.5);const pausedPose=turn.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data[0])');
  turn.frame(1000);turn.frame(2000);assert.equal(turn.evaluate('JSON.stringify(layers.find(l=>l.id==="trips").props.data[0])'),pausedPose);
  let wall=2000;
  for(const speed of [1,120]) {
    turn.api.pause();turn.api.seek(119.5);turn.api.setSpeed(speed);turn.api.play();wall+=1000/speed;turn.frame(wall);
    assert.ok(Math.abs(turn.api.getState().current-120.5)<1e-8);
    assert.equal(turn.api.getState().visibleMarkers,1);assert.equal(turn.api.diagnoseVehicle('turn-car').reason,'visible');
  }
  const missing=harness({},configTurn);
  missing.reply(0,{segments:[turnRecords[0],{...turnRecords[0],timestamps:[115,115]}],trips:tripsTurn});await flush();
  missing.api.pause();missing.api.seek(115);assert.equal(missing.api.getState().visibleMarkers,1,'zero-length record cannot mask active interval');
  missing.api.seek(120.5);missing.reply(1,{segments:[turnRecords[2]],context_segments:[turnRecords[0]],trips:tripsTurn});await flush();
  assert.equal(missing.api.getState().visibleMarkers,0);assert.equal(missing.api.diagnoseVehicle('turn-car').reason,'unknown_interval');
  assert.equal(missing.api.diagnoseVehicle('turn-car').position,null);
  const unavailable=harness({},configTurn),unknownMotion={...turnRecords[0],Motion_Plan:{status:'unavailable',fallback_reason:'missing events'}};
  unavailable.reply(0,{segments:[unknownMotion],trips:tripsTurn});await flush();unavailable.api.pause();unavailable.api.seek(115);
  assert.equal(unavailable.api.diagnoseVehicle('turn-car').reason,'motion_unavailable');
  assert.equal(unavailable.api.diagnoseVehicle('turn-car').position,null);
  assert.equal(unavailable.api.getVisualDiagnostics().counts.active,1);
  assert.equal(unavailable.api.getVisualDiagnostics().counts.omissionReasons.motion_unavailable,1);
  assert.equal(unavailable.api.getVisualDiagnostics().counts.unsupportedPosition,1);
  const overlaps=harness({},configTurn);
  overlaps.reply(0,{segments:[turnRecords[0],{...turnRecords[0],timestamps:[115,119]}],trips:tripsTurn});await flush();
  overlaps.api.pause();overlaps.api.seek(116);
  assert.equal(overlaps.api.diagnoseVehicle('turn-car').reason,'overlapping_intervals');
  assert.equal(overlaps.api.getState().visibleMarkers,0,'ambiguous intervals are not resolved by guessing');
  console.log('PASS: rigid turn, tiny link, half-open boundary, stable identity, pause/seek, 1x/120x, context windows and unknown intervals');
})().catch(error=>{console.error(error);process.exitCode=1;});
