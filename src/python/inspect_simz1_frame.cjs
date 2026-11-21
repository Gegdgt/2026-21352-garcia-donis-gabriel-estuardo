/* Offline execution of the real loader, controls, lane and queue code.
 * DOM/Deck/fetch are in-memory adapters; no browser, HTTP or simulation runs. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const {performance}=require('node:perf_hooks');
const sources=['simz1_continuous_loader.js','simz1_continuous_hud.js','simz1_visual_lanes.js',
  'simz1_visual_queues.js','simz1_vehicle_picking.js','simz1_spatial_view.js','simz1_arrival_effects.js','simz1_incident_effects.js','visualizador_z1_controls.js'];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function element(tag='div') {
  return {tagName:tag.toUpperCase(),style:{},children:[],textContent:'',innerHTML:'',attributes:{},
    append(...rows){this.children.push(...rows);},appendChild(row){this.children.push(row);},
    setAttribute(key,value){this.attributes[key]=value;},focus(){this.focused=true;},
    contains(row){return this===row || this.children.some(child=>child.contains?.(row));}};
}
function offlineHarness(config,windows,hud=null) {
  const identity=config.continuous;
  if(!identity || !config.visual_lanes?.available || ['run_id','iteration','run_manifest_sha256'].some(
    key=>identity[key]!==config.visual_lanes.identity?.[key]))throw new Error('Effective lane/run identity mismatch');
  const byWindow=new Map(windows.map(row=>[row.index,row])),requests=[],errors=[],canvas=element('canvas'),listeners={};
  const ids=new Set([...(config.layers || []).map(row=>row.id),'roads','trips','signals','incidents','map-labels',
    'selected-history-casing','selected-future-casing','selected-history','selected-future','selected-origin',
    'selected-destination','vehicle-focus-halo','vehicle-focus-outline','arrival-annotations','synthetic-incident-emergency']);
  const layers=[...ids].map(id=>({id,props:{data:[]},clone(props){return {...this,props:{...this.props,...props}};}}));
  const sandbox={URLSearchParams,AbortController,TextEncoder,performance,setTimeout,clearTimeout,
    console:{log(){},warn(){},error(...args){errors.push(args.map(String).join(' '));}},
    config,replaySegments:[],incidentRecords:[],layers,requestAnimationFrame(){},
    window:{location:{href:'http://offline.invalid/'},simz1ClientBuild:config.client_build ?? null},
    document:{hidden:false,createElement:element,body:element('body'),addEventListener(name,handler){listeners[name]=handler;}},
    deckInstance:{props:{layers},getCanvas:()=>canvas,setProps(props){Object.assign(this.props,props);}},
    fetch(url,options={}) {
      const parsed=new URL(url,'http://offline.invalid/'),index=Number(parsed.searchParams.get('index'));
      requests.push({path:parsed.pathname,index:parsed.searchParams.has('index') ? index : null});
      if(parsed.pathname.endsWith('/hud'))return Promise.resolve({ok:!!hud,status:hud ? 200 : 404,json:async()=>hud});
      const row=parsed.pathname.endsWith('/window') ? byWindow.get(index) : null;
      if(row)return Promise.resolve({ok:true,status:200,headers:{get:()=>null},text:async()=>JSON.stringify(row)});
      // Missing prefetch/startup windows remain unavailable. Never synthesize a
      // successful empty window; an explicit seek outside supplied data rejects.
      return new Promise((resolve,reject)=>options.signal?.addEventListener('abort',()=>{
        const error=new Error('Offline request aborted');error.name='AbortError';reject(error);
      },{once:true}));
    }};
  vm.createContext(sandbox);
  const loadedSources=Object.fromEntries(sources.map(name=>[name,fs.readFileSync(path.join(__dirname,name),'utf8')]));
  const sourceHashes=Object.fromEntries(Object.entries(loadedSources).map(([name,raw])=>[name,crypto.createHash('sha256').update(raw).digest('hex')]));
  vm.runInContext(Object.values(loadedSources).join('\n'),sandbox);
  const evaluate=script=>vm.runInContext(script,sandbox),api=sandbox.window.simz1Continuous;
  api.pause();
  return {api,evaluate,requests,errors,sourceHashes,async seek(time) {
    const index=Math.min(identity.window_count-1,Math.floor((time-identity.start_seconds)/identity.window_seconds));
    if(!byWindow.has(index))throw new Error('Offline window not supplied: '+index);
    api.seek(time);
    for(let i=0;i<2000 && api.getState().buffering;i++)await flush();
    const state=api.getState();
    if(state.buffering || state.error || state.current!==time)throw new Error(state.error || 'Offline window did not activate');
    return state;
  },destroy(){evaluate('continuousReplay.destroy()');}};
}
function distance(a,b) {
  if(!Array.isArray(a) || !Array.isArray(b))return Infinity;
  const scale=6371008.8*Math.PI/180;
  return Math.hypot((a[0]-b[0])*scale*Math.cos((a[1]+b[1])*.5*Math.PI/180),(a[1]-b[1])*scale);
}
function poseHash(markers) {
  const rows=markers.map(m=>[m.vehicle,m.Link_ID,m.position,m.Visual_Body_Path,m.Visual_Body_Width_Meters,
    m.Visual_Body_Length_Meters,m.Visual_Body_Heading_Degrees,m.color]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
  return crypto.createHash('sha256').update(JSON.stringify(rows)).digest('hex');
}
async function inspect(input,{times=input.times,limit=12}={}) {
  if(!Array.isArray(times) || !times.length || times.length>20 || times.some(t=>!Number.isFinite(t) || t<0 || t>86400) ||
     !Number.isSafeInteger(limit) || limit<1 || limit>100)throw new Error('Invalid offline times/sample limit');
  const h=offlineHarness(input.config,input.windows,input.hud),frames=[],focus=input.focus || {};
  try {
    for(const time of times) {
      process.stderr.write('Evaluating full native roster at '+time+' s\n');
      const started=performance.now(),state=await h.seek(time),diagnostics=h.api.getVisualDiagnostics(time);
      const markers=h.api.layers.find(layer=>layer.id==='trips').props.data;
      const center=focus.center || focus.position,near=markers.filter(m=>!center ||
        distance(m.position,center)<=(focus.radius_m || 100) || distance(m.Visual_Native_Center_Position,center)<=(focus.radius_m || 100));
      const selected=new Set(focus.vehicle_ids || []),ordered=[...near].sort((a,b)=>distance(a.position,center)-distance(b.position,center) || a.vehicle.localeCompare(b.vehicle));
      for(const condition of [m=>m.Visual_Speed_kmh>0 && m.Visual_Speed_kmh<15,m=>m.Visual_Speed_kmh===0])
        for(const marker of ordered.filter(condition).slice(0,Math.ceil(limit/2)))if(selected.size<limit)selected.add(marker.vehicle);
      for(const marker of ordered)if(selected.size<limit)selected.add(marker.vehicle);
      const ids=[...selected].slice(0,limit),sample=diagnostics.sampleCollisions?.({vehicle_ids:ids,limit:100});
      const traceTime=h.api.getState().current,requestsBefore=h.requests.length;
      const vehicles=ids.map(vehicle=>h.api.traceVehicle(vehicle,[time])[0]);
      if(h.api.getState().current!==traceTime || h.requests.length!==requestsBefore)throw new Error('Read-only diagnostics changed replay state');
      const reasons={};for(const row of diagnostics.records)reasons[row.reason]=(reasons[row.reason] || 0)+1;
      const focusReasons={},focusPhases={before_hold:0,during_hold:0,no_hold:0};
      for(const marker of near) {
        const reason=marker.Visual_Queue_State || 'unknown';focusReasons[reason]=(focusReasons[reason] || 0)+1;
        const hold=marker.Motion_Plan?.hold_start ?? marker.Motion_Plan?.native_wait_boundary;
        focusPhases[Number.isFinite(hold) ? time<hold ? 'before_hold' : 'during_hold' : 'no_hold']++;
      }
      const collisionSummary=diagnostics.summarizeCollisions?.();
      const nativeQueueProjection={available:0,unavailable:0,projected:0,focus_projected:0,
        shared_upstream:0,terminal:0,station_outside_domain:0,unexpected_display_link:0,projection_by_link:{}};
      const headProjection={available:0,applied:0,focus_available:0,holding:0,preparing:0,unavailable_reasons:{},
        available_vehicle_ids:[],rejected_vehicle_ids:{}};
      const nearIds=new Set(near.map(m=>m.vehicle));
      for(const marker of markers) {
        const head=marker.Visual_Queue_Head_Projection;
        if(head?.available) {
          headProjection.available++;if(head.applied)headProjection.applied++;
          if(nearIds.has(marker.vehicle))headProjection.focus_available++;
          headProjection[time>=head.head_wait.hold ? 'holding' : 'preparing']++;
          headProjection.available_vehicle_ids.push(marker.vehicle);
        } else if(head) {
          headProjection.unavailable_reasons[head.reason]=(headProjection.unavailable_reasons[head.reason] || 0)+1;
          if(head.head_wait) {
            if(!headProjection.rejected_vehicle_ids[head.reason])headProjection.rejected_vehicle_ids[head.reason]=[];
            headProjection.rejected_vehicle_ids[head.reason].push(marker.vehicle);
          }
        }
        const domain=marker.Visual_Native_Queue_Extent;
        if(!domain?.available){nativeQueueProjection.unavailable++;continue;}
        nativeQueueProjection.available++;nativeQueueProjection[domain.kind]++;
        if(marker.Visual_Queue_Extent_Projection?.applied) {
          nativeQueueProjection.projected++;
          if(nearIds.has(marker.vehicle))nativeQueueProjection.focus_projected++;
          nativeQueueProjection.projection_by_link[marker.Link_ID]=(nativeQueueProjection.projection_by_link[marker.Link_ID] || 0)+1;
        }
        const station=marker.Visual_Queue_Center_Meters ?? marker.Visual_Native_Queue_Station_Meters;
        if(!Number.isFinite(station) || station<domain.geometry_from_m-1e-7 || station>domain.geometry_to_m+1e-7)
          nativeQueueProjection.station_outside_domain++;
        if(marker.Visual_Queue_Display_Link_ID && marker.Visual_Queue_Display_Link_ID!==marker.Link_ID)
          nativeQueueProjection.unexpected_display_link++;
      }
      const active=h.evaluate('activeRecordsAt(current).map(row=>row.vehicle)');
      frames.push({time,window_index:state.cache.activeIndex,elapsed_ms:performance.now()-started,
        counts:diagnostics.counts,reason_counts:reasons,active_records:active.length,unique_active_vehicles:new Set(active).size,
        visible_markers:markers.length,unique_visible_vehicles:new Set(markers.map(m=>m.vehicle)).size,
        pose_sha256:poseHash(markers),focus_marker_count:near.length,selected_vehicle_ids:ids,
        focus_reason_counts:focusReasons,focus_phase_counts:focusPhases,collision_summary:collisionSummary,
        native_queue_projection:nativeQueueProjection,head_stop_projection:headProjection,
        collisions:sample,vehicles,markers:markers.filter(m=>selected.has(m.vehicle)).map(m=>({vehicle_id:m.vehicle,
          link_id:m.Link_ID,interval:m.timestamps,position:m.position,native_position:m.Visual_Native_Center_Position,
          body_path:m.Visual_Body_Path,heading:m.Visual_Body_Heading_Degrees,length_m:m.Visual_Body_Length_Meters,
          width_m:m.Visual_Body_Width_Meters,lane:m.Visual_Lane_Index,lane_source:m.Visual_Lane_Source,
          observed_lane_id:m.Observed_Queue_ID,visual_speed_kmh:m.Visual_Speed_kmh,color:m.color,
          queue_state:m.Visual_Queue_State,body_support:m.Visual_Body_Support,
          motion_status:m.Visual_Motion_Status,motion_reason:m.Visual_Motion_Fallback_Reason,
          motion_hold_start:m.Motion_Plan?.hold_start ?? m.Motion_Plan?.native_wait_boundary,
          motion_fraction:m.Visual_Motion_Fraction,waiting:m.Waiting}))});
    }
    return {schema:'simz1-offline-frame-report-v1',read_only:true,provenance:input.provenance,
      identity:Object.fromEntries(['run_id','iteration','run_manifest_sha256'].map(key=>[key,input.config.continuous[key]])),
      sources:h.sourceHashes,
      focus,frames,requests:h.requests,errors:h.errors,
      limitations:['Real loader/controls/geometry/queue code; DOM and Deck are in-memory adapters, without GPU or browser.',
        'Entire supplied window and queue closure are evaluated; only returned evidence is sampled.',
        'Red/white encode estimated visual speed, not signal state or a confirmed physical accident.',
        'Observed queue events do not provide measured lateral positions or prove physical incompatibility.']};
  } finally {h.destroy();}
}
if(require.main===module)(async()=>{
  const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);return i<0 ? null : args[i+1];};
  const filename=option('--input');if(!filename)throw new Error('Required: --input frame-input.json [--times 28987] [--limit 12] [--output-new path]');
  const output=option('--output-new');if(output && fs.existsSync(output))throw new Error('Output already exists; choose a new inspection file');
  const input=JSON.parse(fs.readFileSync(filename,'utf8'));
  if(option('--vehicles'))input.focus={...input.focus,vehicle_ids:option('--vehicles').split(',')};
  const result=await inspect(input,{times:option('--times') ? option('--times').split(',').map(Number) : input.times,
    limit:option('--limit') ? Number(option('--limit')) : 12});
  const encoded=JSON.stringify(result,null,2)+'\n';
  if(output){fs.writeFileSync(output,encoded,{flag:'wx'});console.log(JSON.stringify({output,frames:result.frames.map(row=>({time:row.time,
    active:row.active_records,visible:row.visible_markers,focus:row.focus_marker_count,vehicles:row.selected_vehicle_ids,counts:row.counts}))}));}
  else console.log(encoded);
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
module.exports={offlineHarness,inspect};
