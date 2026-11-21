// Full continuous HTML + embedded production scripts, with in-memory DOM,
// Deck lifecycle and HTTP responses. No browser, server, run files or SQLite.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
let html=read('visualizador_z1_continuous.html');
for(const [marker,file] of Object.entries({__LOADER__:'simz1_continuous_loader.js',
  __VISUAL_LANES__:'simz1_visual_lanes.js',__VISUAL_QUEUES__:'simz1_visual_queues.js',
  __VEHICLE_PICKING__:'simz1_vehicle_picking.js',__SPATIAL_VIEW__:'simz1_spatial_view.js',
  __SIGNAL_GEOMETRY__:'simz1_signal_geometry.js',
  __ARRIVAL_EFFECTS__:'simz1_arrival_effects.js',
  __INCIDENT_EFFECTS__:'simz1_incident_effects.js',
  __TRANSIT_STOPS__:'simz1_transit_stops.js',
  __AGGREGATE_VIEW__:'simz1_aggregate_view.js',
  __HUD__:'simz1_continuous_hud.js',__CONTROLS__:'visualizador_z1_controls.js'})) {
  assert.equal(html.split(marker).length,2,'one embedded source: '+marker);
  html=html.replace(marker,()=>read(file));
}
const source=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const identity={run_id:'in-memory-229629',iteration:0,run_manifest_sha256:'b'.repeat(64),source_version:'c'.repeat(64)};
const horizon={start_seconds:0,end_seconds:86400},key='a'.repeat(64);
const metres=6371008.8*Math.PI/180,xy=(x,y)=>[x/metres,y/metres];

async function harness({hidden=false,hudFault=false,labelsFault=false,stops=false,fleet=false,search='',hudHttp=200,aggregates=false}={}) {
  const frames=new Map(),requests=[],windowListeners={},documentListeners={},errors=[],signalUpdates=[];
  const faults={hud:hudFault,labels:labelsFault,render:false,advance:false,hudHttp};
  let now=0,nextFrame=0,instance;
  function element(tag='div') {
    let content='';
    return {tagName:tag.toUpperCase(),style:{},attributes:{},children:[],hidden:false,
      append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}},
      appendChild(node){this.append(node);return node;},
      replaceChildren(...nodes){this.children=[];this.append(...nodes);},
      remove(){this.parent.children=this.parent.children.filter(node=>node!==this);},
      contains(node){return this===node || this.children.some(child=>child.contains(node));},
      setAttribute(name,value){this.attributes[name]=String(value);},focus(){this.focused=true;},
      set textContent(value){
        if(faults.hud && this.id==='simz1-run-error') {faults.hud=false;throw new Error('HUD presentation sentinel');}
        content=String(value);
      },
      get textContent(){return content+this.children.map(child=>child.textContent).join('');}};
  }
  const body=element('body'),container=element(),status=element();
  container.id='deck-container';status.id='load-status';body.append(container,status);
  function find(id,node=body) {return node.id===id ? node : node.children.map(child=>find(id,child)).find(Boolean);}
  const document={body,createElement:element,getElementById:find,
    get hidden(){if(faults.advance){faults.advance=false;throw new Error('animation sentinel');}return false;},
    addEventListener:(name,handler)=>{documentListeners[name]=handler;}};
  const window={location:{search},sessionStorage:{getItem:()=>String(hidden),setItem:(_,value)=>{hidden=value==='true';}},
    addEventListener:(name,handler)=>{windowListeners[name]=handler;}};
  class Layer {
    constructor(props){
      this.id=props.id;this.props=props;
      if(props.id==='signal-lamps' && props.updateTriggers?.getColor)signalUpdates.push({
        trigger:Array.from(props.updateTriggers.getColor),colors:Array.from(props.data,row=>Array.from(props.getColor(row)))});
    }
    clone(props){return new Layer({...this.props,...props});}
  }
  class Viewport {
    constructor(props){Object.assign(this,props);}
    project(position){
      // Inject only label projection failure; signals now project 3D bounds too.
      if(faults.labels && position.length===2)throw new Error('label projection sentinel');
      return [100+position[0]*metres,300-position[1]*metres];
    }
  }
  class Deck {
    constructor(props){
      instance=this;this.props={...props};this.isInitialized=false;this.earlyViewportCalls=0;
      this.canvas=element('canvas');props.parent.append(this.canvas);
    }
    getCanvas(){return this.canvas;}
    getViewports(){
      // The real v9.1.14 method asserts viewManager before onLoad; the old
      // controls-only harness omitted this method and missed the regression.
      if(!this.isInitialized){this.earlyViewportCalls++;throw new Error('deck.gl: assertion failed.');}
      return [new Viewport({...this.props.viewState,width:900,height:600})];
    }
    setProps(props){
      if(faults.render && props.layers){faults.render=false;throw new Error('render sentinel');}
      Object.assign(this.props,props);
    }
    ready(){
      this.isInitialized=true;
      // Deck updates canvas size before calling onLoad.
      this.props.onResize?.({width:900,height:600});this.props.onLoad();
    }
  }
  const config={hud:{...identity,planned_persons:1}, // Never use stale HTML totals.
    replay_source:{source_manifest_sha256:identity.source_version},
    initialViewState:{longitude:0,latitude:0,zoom:17,pitch:0,bearing:0},
    continuous:{...identity,...horizon,window_seconds:120,window_count:720,
      source_time_horizon:horizon,metrics_window:horizon,window_endpoint:'/api/window'},
    visual_lanes:{schema_version:1,available:true,identity,links:{road:{
      path:[xy(0,0),xy(600,0)],num_lanes:1,offset_eligible:true,length_m:600,osm_tags:{name:'7a Avenida'}}}},
    layers:[{'@@type':'LineLayer',id:'roads',data:[{from:xy(0,0),to:xy(600,0)}]},
      ...['selected-history','selected-future'].map(id=>({'@@type':'PathLayer',id,data:[],getPath:'@@=path'})),
      {'@@type':'ScatterplotLayer',id:'trips',data:[]},
      {'@@type':'IconLayer',id:'signals',data:[{system_id:'s',group_id:'g',signal_id:'head',Link_ID:'road',lane_ids:['native'],position:xy(300,0)}]},
      {'@@type':'IconLayer',id:'incidents',data:[]}]};
  if(stops)config.transit_stops={...(stops===true ? JSON.parse(read('fixtures/simz1-stop-signs-synthetic.json')) : stops),identity};
  if(aggregates)config.aggregate_view={available:true,endpoint:'/api/aggregate'};
  const sandbox={document,window,deck:{Deck,WebMercatorViewport:Viewport,PathLayer:Layer,LineLayer:Layer,
      ScatterplotLayer:Layer,IconLayer:Layer,TextLayer:Layer,SimpleMeshLayer:Layer},URLSearchParams,AbortController,TextEncoder,
    console:{error:(...args)=>errors.push(args)},
    performance:{now:()=>now},
    requestAnimationFrame:fn=>{const id=++nextFrame;frames.set(id,fn);return id;},
    fetch:async(url,options)=>{
      requests.push({url,options});
      if(url==='./api/config')return {ok:true,json:async()=>structuredClone(config)};
      if(url.startsWith('/api/aggregate')) {
        const time=Number(new URL(url,'http://memory').searchParams.get('time'));
        return {ok:true,json:async()=>({schema_version:1,no_positions:true,identity,time_seconds:time,
          coverage:{native_active:1,unassociated_active:0},
          origins:[{origin_link:'road',family:'carro',scheduled_total:2,scheduled_due:2,requested:2,
            entered:1,waiting_admission:1,retired_waiting:0,arrived:0,active_origin_cohort:1,oldest_pending_request:0,latest_entry:0,
            hourly:[{hour:0,scheduled:2,requested:2,entered:1,arrived:0,waiting_admission_end:1}]}],
          links:[{link_id:'road',active_count:1,families:{carro:1},last_change_time:0,
            latest_entry:0,latest_leave:null,time_since_change:time}]})};
      }
      if(url.startsWith('/api/hud'))return {ok:faults.hudHttp===200,status:faults.hudHttp,json:async()=>({schema_version:1,...identity,
        replay_window:horizon,source_time_horizon:horizon,metrics_window:horizon,
        vehicle_summary:{schema_version:1,private_vehicles:229629,public_vehicles:fleet ? 120 : null,
          temporal_policy:false,private_basis:'verified_private_one_vehicle_per_person',
          public_basis:fleet ? 'unique_configured_fleet_ids' : 'missing_unique_fleet_evidence'},
        counts:{persons_generated:229629,planned_trips:459258,completed_trips:400000,
          pending_censored_trips:59258,reconstructed_vehicles:229629,vehicles_with_events:229629},native_active_series:null,
        public_transport:fleet ? {configured:{road_demand_persons:229629,public_transport_vehicles_configured:120,
          fleet_vehicle_ids:Array.from({length:120},(_,i)=>'bus-'+i),
          fleet_by_system:{transmetro:80,tubus:40}}} : null})};
      if(url.startsWith('/api/window')) {
        const index=Number(new URL(url,'http://memory').searchParams.get('index')),start=index*120,end=start+120;
        const payload={...identity,index,start_seconds:start,end_seconds:end,
          segments:[{vehicle:'v',Agent_ID:'p',Link_ID:'road',Replay_Journey_Key:key,
            timestamps:[0,86400],path:[xy(0,0),xy(600,0)],Speed_kmh:.025,Max_Speed_kmh:.025,
            Motion_Plan:{version:1,status:'constant',distance_m:600,cap_mps:1,phases:[[0,86400,0,600/86400,0]]}}],
          trips:{[key]:{Trip_ID:'p:1',Departure:0,Arrival:86400,Status:'completed'}},
          signal_replay:{series:[{system_id:'s',group_id:'g',states:[[0,'OFF'],[0,'RED'],[60,'GREEN']]}]},
          lane_replay:{events:[]},incidents:[]};
        return {ok:true,status:200,text:async()=>JSON.stringify(payload)};
      }
      throw new Error('Unexpected network request '+url);
    }};
  window.deck=sandbox.deck;
  vm.createContext(sandbox);
  await vm.runInContext(source,sandbox,{filename:'continuous-assembled.html'});await flush();
  return {window,instance,find,requests,errors,faults,status,frames,windowListeners,signalUpdates,
    get api(){return window.simz1Continuous;},
    button(label){return find('simz1-controls').children.flatMap(function walk(node){return [node,...node.children.flatMap(walk)];})
      .find(node=>node.tagName==='BUTTON' && node.textContent===label);},
    frame(timestamp){now=timestamp;assert.equal(frames.size,1,'exactly one replay animation scheduled');
      const [id,fn]=frames.entries().next().value;frames.delete(id);fn(timestamp);},
    layer(id){return instance.props.layers.find(layer=>layer.id===id);}};
}

function controlsPresent(h) {
  assert.ok(h.api,'public replay API retained: '+h.status.textContent);
  for(const id of ['simz1-ui','simz1-controls','simz1-show-bar','simz1-run-panel','simz1-clock','simz1-time-slider'])
    assert.ok(h.find(id),'retained '+id);
  assert.equal(Number(h.find('simz1-time-slider').min),0);
  assert.equal(Number(h.find('simz1-time-slider').max),86400);
  assert.equal(h.find('simz1-count-persons_generated').textContent,'229629');
  assert.ok(h.find('simz1-run-panel').textContent.startsWith('Vehículos particulares: 229629 · Transporte público: '));
  assert.ok(h.find('simz1-fixed-public-fleet'),'independent configured fleet field');
  assert.equal(h.find('simz1-served-identity').textContent,'Corrida: '+identity.run_id+' · Iteración 0');
  assert.equal(h.frames.size,1);
  assert.ok(h.layer('arrival-annotations'),'full HTML installs the separate annotation layer');
  assert.equal(h.layer('arrival-annotations').props.pickable,false,'annotations do not intercept vehicle selection');
  assert.equal(h.layer('synthetic-incident-emergency').props.pickable,false,'emergencies do not intercept vehicle selection');
}

(async()=>{
  const aggregateRun=await harness({aggregates:true});
  aggregateRun.instance.ready();await flush();
  controlsPresent(aggregateRun);
  assert.equal(aggregateRun.window.simz1Aggregate.getState().status,'ready');
  assert.equal(aggregateRun.layer('simz1-aggregate-origins').props.data.length,1);
  assert.equal(aggregateRun.layer('simz1-aggregate-links').props.data.length,1);
  assert.equal(aggregateRun.layer('trips').props.data.length,1,'aggregate evidence never adds a body');
  for(const instant of [240,23400,30600,33300,37800,72300,82800]) {
    aggregateRun.api.seek(instant);await flush();
    assert.equal(aggregateRun.window.simz1Aggregate.getState().time,instant);
    assert.equal(aggregateRun.layer('trips').props.data.length,1);
  }
  aggregateRun.window.simz1Aggregate.selectOrigin('road');
  assert.match(aggregateRun.find('simz1-aggregate-details').textContent,/Programados/);
  const aggregateRequests=()=>aggregateRun.requests.filter(r=>r.url.startsWith('/api/aggregate')).length;
  const requestsBefore=aggregateRequests();
  aggregateRun.find('simz1-type-filter').value='motorcycle';aggregateRun.find('simz1-type-filter').onchange();
  assert.equal(aggregateRun.layer('simz1-aggregate-origins').props.data.length,0);
  assert.equal(aggregateRequests(),requestsBefore,'family filter reuses immutable evidence');
  aggregateRun.find('simz1-type-filter').value='all';aggregateRun.find('simz1-type-filter').onchange();
  aggregateRun.find('simz1-route-filter').value='bus-route';aggregateRun.find('simz1-route-filter').onchange();
  assert.equal(aggregateRun.layer('simz1-aggregate-links').props.data.length,0,'unsupported route breakdown is explicit');
  aggregateRun.find('simz1-route-filter').value='';aggregateRun.find('simz1-route-filter').onchange();
  assert.equal(aggregateRun.layer('simz1-aggregate-links').props.data.length,1);
  assert.equal(aggregateRun.errors.length,0);
  for(const [field,value] of [['run_id','other-run'],['iteration','9'],['source_version','f'.repeat(64)]]) {
    const wrong=await harness({search:'?'+new URLSearchParams({[field]:value})});
    assert.equal(wrong.api,undefined,'requested identity mismatch never initializes '+field);
    assert.match(wrong.status.textContent,/Identidad solicitada/);
    assert.equal(wrong.requests.length,1,'mismatched config cannot issue windows or HUD');
  }
  const publicRun=await harness({fleet:true});
  controlsPresent(publicRun);
  assert.equal(publicRun.find('simz1-fixed-public-fleet').textContent,
    ' · Transporte público: 120');
  const h=await harness();
  controlsPresent(h);
  assert.equal(h.instance.isInitialized,false,'HTTP/HUD can finish before GPU initialization');
  assert.equal(h.instance.earlyViewportCalls,0,'never call getViewports before Deck is ready');
  assert.equal(h.api.getStopDiagnostics().accepted,0,'missing catalog never creates guessed stops');
  const physicalSignal=h.layer('signals'),signalPose=JSON.stringify(h.api.getSignalDiagnostics().records);
  assert.ok(physicalSignal.props.mesh,'upright mesh exists before viewport initialization');
  assert.equal(h.layer('signal-lamps').props.data.length,3,'one head has exactly three front lamps');
  assert.equal(h.instance.props.layers.filter(layer=>layer.id==='signals').length,1,'legacy IconLayer is replaced, never overlaid');
  assert.equal(new Set(h.instance.props.layers.map(layer=>layer.id)).size,h.instance.props.layers.length,'no duplicate rendering layers');
  assert.equal(physicalSignal.props.iconAtlas,undefined,'only the mesh signal survives bootstrap');
  assert.equal(h.layer('signal-state-labels'),undefined,'no map letters at any zoom');
  assert.equal(physicalSignal.props.billboard,undefined);
  assert.equal(h.api.getSignalDiagnostics().oriented,1);
  const initialSignals=h.signalUpdates.filter(update=>update.trigger[0]===0);
  assert.ok(new Set(initialSignals.map(update=>update.trigger[1])).size>=2,'initial load invalidates attributes even while the clock stays at zero');
  const red=[[255,55,55,255],[54,62,70,255],[54,62,70,255]],green=[[54,62,70,255],[54,62,70,255],[40,235,105,255]];
  assert.deepEqual(initialSignals.at(-1).colors,red,'equal-time OFF then RED keeps native last-event order');
  assert.ok(h.requests.some(r=>r.url.startsWith('/api/hud')),'initial HUD notification did not abort fetch');
  assert.ok(h.requests.some(r=>r.url.startsWith('/api/window')),'initial render did not abort window request');
  h.instance.props.onResize({width:900,height:600});
  assert.equal(h.instance.earlyViewportCalls,0,'early resize also waits for Deck');
  h.instance.ready();
  const originalCamera={...h.api.getState().camera.viewState};
  for(const bearing of [0,90,180,270])for(const pitch of [0,30,45,60]) {
    h.instance.props.onViewStateChange({viewState:{...originalCamera,bearing,pitch}});
    assert.strictEqual(h.layer('signals').props.mesh,physicalSignal.props.mesh,'camera reuses mesh and changes only display scale');
    assert.equal(JSON.stringify(h.api.getSignalDiagnostics().records),signalPose,'same access, lanes, anchor and ENU orientation');
  }
  h.instance.props.onViewStateChange({viewState:originalCamera});
  const lampColors=()=>Array.from(h.layer('signal-lamps').props.data,row=>Array.from(h.layer('signal-lamps').props.getColor(row)));
  const displayedSignal=h.layer('signals');
  assert.deepEqual(lampColors(),red);
  h.api.seek(60);assert.deepEqual(lampColors(),green);
  h.api.seek(120);await flush();assert.equal(h.layer('signal-lamps').props.updateTriggers.getColor[0],120,'new window rebinds its native series even if color stays green');
  assert.deepEqual(lampColors(),green);
  h.api.seek(0);assert.deepEqual(lampColors(),red,'reverse seek restores native state');
  assert.strictEqual(h.layer('signals'),displayedSignal,'native changes update lamps, never pose');
  assert.ok(h.layer('roads').props.data.length);
  assert.ok(h.layer('signals').props.data.length);
  assert.ok(h.layer('map-labels').props.data.length,'labels refresh onLoad');
  assert.equal(h.layer('map-labels').props.background,false,'no opaque label boxes over roads');
  assert.equal(h.layer('map-labels').props.pickable,false);
  assert.ok(h.instance.props.layers.indexOf(h.layer('map-labels'))<h.instance.props.layers.indexOf(h.layer('trips')),
    'vehicles draw after map labels');
  assert.equal(h.errors.length,0);
  assert.equal(h.status.hidden,true);
  h.api.seek(36000);await flush();
  assert.equal(h.layer('trips').props.data.length,1,'validated in-memory vehicle drawn');
  for(const id of ['selected-history','selected-future']) {
    const route=h.layer(id);
    assert.equal(route.props.getWidth,id==='selected-history' ? 4 : 2);assert.equal(route.props.widthUnits,'pixels');
    assert.equal(route.props.widthMaxPixels,4);assert.equal(route.props.getColor[3],255,'readable opaque stroke');
    assert.deepEqual({...route.props.parameters},{depthCompare:'always',depthWriteEnabled:false});
    assert.ok(route.props.getColor[2]>route.props.getColor[1],'violet route is distinct from yellow hover and cyan pin');
    assert.ok(h.instance.props.layers.indexOf(route)<h.instance.props.layers.indexOf(h.layer('trips')));
    const casing=h.layer(id+'-casing');
    assert.equal(casing.props.widthMaxPixels,6);
    assert.ok(h.instance.props.layers.indexOf(casing)>h.instance.props.layers.indexOf(h.layer('visual-lane-centers')));
    assert.ok(h.instance.props.layers.indexOf(casing)<h.instance.props.layers.indexOf(h.layer('selected-history')));
  }
  for(const id of ['vehicle-focus-halo','vehicle-focus-outline']) {
    const layer=h.layer(id);
    assert.ok(layer,'continuous HTML installs '+id);
    assert.equal(layer.props.pickable,false,'focus never intercepts picking');
    assert.equal(layer.props.billboard,false,'contour stays on the rigid ground body when camera tilts');
    assert.equal(layer.props.widthUnits,'pixels');
    assert.equal(layer.props.data.length,0,'no focus without a selection');
    assert.ok(h.instance.props.layers.indexOf(layer)<h.instance.props.layers.indexOf(h.layer('trips')),
      'original traffic paints over inward contour stroke, including subpixel bodies');
  }
  const selected=h.layer('trips').props.data[0];
  const pixel=h.instance.getViewports()[0].project(selected.position);
  h.instance.props.onHover({object:selected,x:pixel[0],y:pixel[1]},{pointerType:'mouse'});
  const contour=h.layer('vehicle-focus-outline'),focus=contour.props.data[0];
  assert.equal(focus.marker,selected,'HTML highlight resolves exact displayed vehicle object');
  assert.equal(focus.mode,'hover');assert.equal(contour.props.getPath(focus),focus.outline);
  assert.deepEqual(Array.from(contour.props.getColor(focus)),[255,218,70,255]);
  assert.deepEqual(Array.from(h.layer('trips').props.getColor(selected)),[...selected.color.slice(0,3),255],
    'body retains original speed color under the unfilled contour');
  h.instance.getCanvas().onpointerleave();assert.equal(h.layer('vehicle-focus-outline').props.data.length,0);
  const position=h.layer('trips').props.data[0].position.slice();
  h.button('1x').onclick();h.frame(1000);await flush();
  assert.equal(h.api.getState().current,36001);
  assert.notDeepEqual(h.layer('trips').props.data[0].position,position,'vehicle moves with absolute simulated time');
  h.button('Pausar').onclick();h.frame(2000);
  assert.equal(h.api.getState().current,36001);
  h.button('120x').onclick();h.button('Reproducir').onclick();h.frame(3000);await flush();
  assert.equal(h.api.getState().current,36121);
  h.find('simz1-time-slider').value='30000';h.find('simz1-time-slider').oninput();await flush();
  assert.equal(h.api.getState().current,30000,'slider seek loads a different window');
  assert.match(h.find('simz1-clock').textContent,/08:20:00/);
  controlsPresent(h);

  const withStops=await harness({stops:true});withStops.instance.ready();controlsPresent(withStops);
  assert.equal(withStops.instance.earlyViewportCalls,0);
  assert.equal(withStops.api.getStopDiagnostics().visible,3);
  const stopPose=JSON.stringify(withStops.api.getStopDiagnostics().records);
  const stopPaths=JSON.stringify(withStops.layer('transit-stop-directions').props.data);
  const stopCamera={...withStops.api.getState().camera.viewState};
  for(const bearing of [0,90,180,270])for(const pitch of [0,30,60]) {
    withStops.instance.props.onViewStateChange({viewState:{...stopCamera,bearing,pitch}});
    assert.equal(JSON.stringify(withStops.api.getStopDiagnostics().records),stopPose);
    assert.equal(JSON.stringify(withStops.layer('transit-stop-directions').props.data),stopPaths);
  }
  assert.ok(withStops.instance.props.layers.indexOf(withStops.layer('transit-stop-signs'))<
    withStops.instance.props.layers.indexOf(withStops.layer('trips')),'vehicle bodies draw above stop signs');
  const busStop=withStops.layer('transit-stop-signs').props.data.find(row=>row.stop_id==='synthetic-west');
  const requestCount=withStops.requests.length;
  withStops.instance.props.onHover({object:busStop,x:200,y:200},{pointerType:'mouse'});
  assert.match(withStops.instance.props.getTooltip({object:busStop}).text,/TuBus · F2/);
  withStops.instance.props.onClick({object:busStop},{type:'click',tapCount:1});
  assert.equal(withStops.requests.length,requestCount,'stop inspection does not fetch journeys or windows');
  withStops.instance.props.onViewStateChange({viewState:{...stopCamera,zoom:15}});
  assert.ok(withStops.layer('transit-stop-signs').props.data.length>0,'low zoom groups instead of hiding every stop');
  assert.equal(withStops.api.getStopDiagnostics().represented,3);
  withStops.instance.props.onViewStateChange({viewState:{...stopCamera,zoom:18}});
  assert.equal(withStops.layer('transit-stop-names').props.data.length,3);
  assert.equal(withStops.errors.length,0);controlsPresent(withStops);

  const catalogSpec=JSON.parse(read('fixtures/simz1-stop-signs-synthetic.json'));
  catalogSpec.simulation_usage={status:'not_configured',used_by_simulation:false};
  for(const row of catalogSpec.records) {
    delete row.Link_ID;delete row.bearing_degrees;delete row.direction;
    row.annotation_kind='catalog_only';row.native_access_status='unmapped';
    row.coordinate_evidence={element:row.stop_id,timestamp:'synthetic'};
    row.simulation_usage=catalogSpec.simulation_usage;
  }
  const catalogOnly=await harness({stops:catalogSpec});catalogOnly.instance.ready();
  assert.equal(catalogOnly.api.getStopDiagnostics().accepted,3);
  assert.equal(catalogOnly.layer('transit-stop-directions').props.data.length,0);
  assert.match(catalogOnly.instance.props.getTooltip({object:catalogOnly.layer('transit-stop-signs').props.data[0]}).text,
    /no tiene transporte público configurado/);
  assert.equal(catalogOnly.layer('trips').props.data.length,h.layer('trips').props.data.length,
    'catalog annotations never inject simulated vehicles');
  assert.equal(catalogOnly.errors.length,0);controlsPresent(catalogOnly);

  const hidden=await harness({hidden:true});hidden.instance.ready();controlsPresent(hidden);
  assert.equal(hidden.find('simz1-controls').hidden,true);
  assert.equal(hidden.find('simz1-show-bar').hidden,false,'stored preference never hides both controls');
  hidden.find('simz1-show-bar').onclick();assert.equal(hidden.find('simz1-controls').hidden,false);
  hidden.find('simz1-hide-bar').onclick();assert.equal(hidden.find('simz1-show-bar').hidden,false);

  for(const options of [{hudFault:true},{labelsFault:true},{labelsFault:true,hidden:true}]) {
    const broken=await harness(options);broken.instance.ready();controlsPresent(broken);
    if(options.hudFault) {
      assert.equal(broken.api.getState().hud.status,'ready','a later successful presentation clears the transient HUD failure');
      assert.equal(broken.find('simz1-run-error-detail').textContent,'');
      assert.equal(broken.status.hidden,true,'a recovered HUD failure leaves no stale map error');
    } else {
      assert.equal(broken.status.hidden,false,'onLoad must not erase an independent map error');
      assert.match(broken.status.textContent,/sentinel/);
      assert.match(broken.status.textContent,/Error:/,'stack/error type retained');
    }
    assert.ok(broken.requests.some(r=>r.url.startsWith('/api/hud')));
    assert.ok(broken.requests.some(r=>r.url.startsWith('/api/window')));
    broken.api.seek(36000);await flush();broken.api.setSpeed(1);broken.frame(1000);await flush();
    assert.equal(broken.api.getState().current,36001,'optional presentation failure cannot stop animation');
    assert.equal(broken.layer('trips').props.data.length,1);
    assert.ok(broken.layer('roads').props.data.length);
    assert.ok(broken.layer('signals').props.data.length);
    if(options.hidden){assert.equal(broken.find('simz1-show-bar').hidden,false);broken.find('simz1-show-bar').onclick();}
    controlsPresent(broken);
  }
  const hudUnavailable=await harness({hudHttp:503});hudUnavailable.instance.ready();
  assert.equal(hudUnavailable.api.getState().hud.status,'error');
  assert.match(hudUnavailable.find('simz1-run-error-detail').textContent,/HTTP 503/);
  assert.equal(hudUnavailable.status.hidden,true,'HUD rejection does not enter the global map error area');
  assert.equal(hudUnavailable.errors.length,0,'one visible technical detail, no duplicate console/global report');
  hudUnavailable.api.seek(36000);await flush();hudUnavailable.api.setSpeed(1);hudUnavailable.frame(1000);await flush();
  assert.equal(hudUnavailable.api.getState().current,36001,'failed metadata does not stop map playback');
  const beforeHudRetry=hudUnavailable.requests.filter(row=>row.url.startsWith('/api/hud')).length;
  hudUnavailable.faults.hudHttp=200;
  const retryA=hudUnavailable.api.reloadHud(),retryB=hudUnavailable.api.reloadHud();
  assert.strictEqual(retryA,retryB);await retryA;
  assert.equal(hudUnavailable.requests.filter(row=>row.url.startsWith('/api/hud')).length,beforeHudRetry+1);
  assert.equal(hudUnavailable.find('simz1-run-error-detail').textContent,'');
  assert.equal(hudUnavailable.status.hidden,true);controlsPresent(hudUnavailable);

  // A later projection failure in the resize callback is also isolated.
  h.faults.labels=true;h.instance.props.onResize({width:800,height:500});
  assert.match(h.status.textContent,/label projection sentinel/);controlsPresent(h);
  h.api.setSpeed(1);h.faults.render=true;h.frame(4000);await flush();
  assert.match(h.status.textContent,/render sentinel/);controlsPresent(h);
  h.frame(5000);await flush();assert.equal(h.layer('trips').props.data.length,1);

  // Force advance() itself to throw while reading document visibility. Its finally
  // must keep requestAnimationFrame alive, even outside the render guard.
  h.api.seek(30119);await flush();h.faults.advance=true;h.frame(6000);await flush();
  assert.match(h.status.textContent,/animation sentinel/);controlsPresent(h);
  h.frame(7000);await flush();assert.ok(h.api.getState().current>=30120);

  const before=h.instance.props.layers;
  h.instance.props.onError(new Error('GPU sentinel',{cause:new Error('original cause')}),{id:'map-labels'});
  assert.strictEqual(h.instance.props.layers,before,'reportError must not call Deck or clear layers');
  assert.match(h.status.textContent,/original cause/);controlsPresent(h);
  h.windowListeners.error({error:new Error('global sentinel')});
  h.windowListeners.unhandledrejection({reason:'rejected sentinel'});
  assert.match(h.status.textContent,/global sentinel/);assert.match(h.status.textContent,/rejected sentinel/);
  h.instance.props.onLoad();assert.equal(h.status.hidden,false,'late load cannot hide diagnostics');
  console.log('PASS: full continuous bootstrap, delayed Deck readiness, totals, playback, persisted toolbar, isolated faults and visible diagnostics');
})().catch(error=>{console.error(error);process.exitCode=1;});
