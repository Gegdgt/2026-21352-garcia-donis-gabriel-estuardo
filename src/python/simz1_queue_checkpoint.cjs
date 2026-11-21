'use strict';
// Bounded component evaluator. The geometry/queue classes and marker/motion
// functions below are loaded directly from their production files. No native
// simulation, event edits, test harness, browser or alternate pose law.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),readline=require('node:readline');
const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8'),controls=read('visualizador_z1_controls.js');
function section(start,end){const a=controls.indexOf(start),b=controls.indexOf(end,a+start.length);
  if(a<0||b<0||controls.indexOf(start,a+1)>=0)throw new Error('Production marker function boundary changed: '+start);
  return controls.slice(a,b);}
const functions=[section('function laneObservationAt(','\nlet incidents ='),section('function motionAt(','function centerPosition('),
  section('function centerPosition(','function visualLaneText('),section('function markerAt(','function routeSlice('),
  section('function transitionNeighbors(','function queueHoldTime('),section('function queueHoldTime(','function queueRoster('),
  section('function markerKey(','function queueStateLabel(')].join('\n');
let sandbox=null;
function initialize(packet){
  if(sandbox)throw new Error('Kernel already initialized');
  if(packet.facility_support!=null){
    const proof=packet.facility_support,hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    if(!proof || Object.keys(proof).sort().join(',')!=='blocking_links,identity,reader_sha256,schedule_sha256,schema,source_sqlite_sha256' ||
       proof.schema!=='native-blocking-facility-support-v1' || !proof.identity ||
       ['run_id','iteration','run_manifest_sha256'].some(key=>proof.identity[key]!==packet.identity?.[key]) ||
       ['source_sqlite_sha256','schedule_sha256','reader_sha256'].some(key=>!hash(proof[key])) ||
       !Array.isArray(proof.blocking_links) || proof.blocking_links.some((link,i,all)=>typeof link!=='string'||!link||i>0&&all[i-1]>=link))
      throw new Error('Native blocking-facility support is invalid or belongs to another source');
  }
  sandbox={INIT:packet,performance,console:{log(){throw new Error('Kernel stdout is protocol only');}}};vm.createContext(sandbox);
  const setup=`
    const config={continuous:INIT.identity},continuousMode=true,MOTION_STOP_TOLERANCE_KMH=1e-4;
    const visualLaneRenderer=new SimZ1VisualLanes(INIT.visual_lanes);
    const visualQueueRenderer=new SimZ1VisualQueues(visualLaneRenderer,INIT.settings);
    const facilitySupport=INIT.facility_support??null;
    const markerMemo=new WeakMap(),entityMemo=new WeakMap(),presentationMemo=new WeakMap(),validatedMotionPlans=new WeakMap();
    const renderCounters={markerReuses:0,markerCreates:0};
    let laneTimelines=new Map(),transitionRecords=new Map(),transitionPoseCache=new Map(),queueContexts=new Map();
    const visualSpeedColor=()=>[0,0,0]; // Colour is not consumed by the position kernel.
    const tripKey=r=>r.Replay_Journey_Key;
    function canonicalKey(key){return JSON.stringify(JSON.parse(key));}
    function execute(packet){
      const classifying=packet.op==='classify';
      const records=packet.records,phases=new Map(Object.entries(packet.phases||{}).map(([key,value])=>[canonicalKey(key),value]));
      const checkpoints=new Map(Object.entries(packet.checkpoints||{}).map(([key,value])=>[canonicalKey(key),value]));
      if(classifying && (checkpoints.size || packet.external_pass || packet.release_states ||
         new Set(packet.requests.map(row=>canonicalKey(row.key))).size!==packet.requests.length ||
         packet.requests.some(row=>row.role!=='classify'||row.stage!==null)))
        throw new Error('Invalid source classification request');
      let constraints=null;
      if(packet.constraint_keys!==undefined){
        if(!Array.isArray(packet.constraint_keys))throw new Error('Invalid causal constraint keys');
        constraints=new Set(packet.constraint_keys.map(canonicalKey));
        const sourceKeys=new Set(records.map(record=>visualQueueRenderer.key(record)));
        if(constraints.size!==packet.constraint_keys.length || [...constraints].some(key=>!sourceKeys.has(key)) ||
           [...phases.keys(),...checkpoints.keys(),...packet.requests.map(request=>canonicalKey(request.key))].some(key=>!constraints.has(key)))
          throw new Error('Causal constraint coverage is incomplete');
      }
      const pending=new Map();
      if(packet.external_pass)for(const request of packet.requests)if(request.role==='base'||request.role==='final'){
        const key=canonicalKey(request.key);if(!pending.has(key))pending.set(key,[]);pending.get(key).push(request.role);}
      if(!Array.isArray(records)||records.length>512)throw new Error('Component record limit exceeded');
      laneTimelines=new Map();transitionRecords=new Map();transitionPoseCache=new Map();queueContexts=new Map();
      for(const event of packet.lane_events||[]){if(!laneTimelines.has(event.vehicle))laneTimelines.set(event.vehicle,[]);laneTimelines.get(event.vehicle).push(event);}
      for(const rows of laneTimelines.values())rows.sort((a,b)=>a.time-b.time);
      const journeys=new Map();
      for(const record of records){
        if(!record.Trip)throw new Error('Native trip metadata missing');
        const group=JSON.stringify([record.vehicle,record.Replay_Journey_Key]);
        if(!journeys.has(group))journeys.set(group,[]);journeys.get(group).push(record);
        const key=visualQueueRenderer.key(record),phase=phases.get(key);
        queueContexts.set(key,{complete:Boolean(phase),role:phase?'resolved_anchor':'auxiliary_transition',phase:phase??'base',
          ...(pending.has(key)?{checkpoint_pending:pending.get(key)}:{}),
          ...(checkpoints.has(key)?{checkpoint:checkpoints.get(key)}:{})});
      }
      for(const rows of journeys.values()){
        rows.sort((a,b)=>a.timestamps[0]-b.timestamps[0]||a.timestamps[1]-b.timestamps[1]);
        for(let i=0;i<rows.length;i++)transitionRecords.set(markerKey(rows[i]),{previous:rows[i-1],next:rows[i+1]});
      }
      const roster=[],anchorAbsences=new Map(),classificationMarkers=new Map(),queriedInterpolation=new Set(packet.requests.filter(row=>row.role==='interpolate').map(row=>canonicalKey(row.key))),
        queriedFIFO=new Set(packet.requests.filter(row=>row.role==='fifo').map(row=>canonicalKey(row.key)));
      const absentPrepared=record=>JSON.stringify(SimZ1VisualQueues.canonical({key:visualQueueRenderer.key(record),representable:false,
        native_occupancy:false,anchor_absence:anchorAbsences.has(visualQueueRenderer.key(record))?
          {...anchorAbsences.get(visualQueueRenderer.key(record)),facility_support:facilitySupport}:null}));
      for(const record of records){
        if(constraints && !constraints.has(visualQueueRenderer.key(record)))continue;
        const at=queueHoldTime(record);if(!Number.isFinite(at))continue;
        const marker=markerAt(record,at);if(marker){
          if(classifying)classificationMarkers.set(visualQueueRenderer.key(record),marker);
          const absence=visualQueueRenderer.contextAnchorAbsence(marker,{current:marker,...transitionNeighbors(marker)},facilitySupport);
          if(absence){
            const key=visualQueueRenderer.key(record);anchorAbsences.set(key,absence);
            const saved=checkpoints.get(key);
            if(saved && (saved.input!==SimZ1VisualQueues.checkpointInput(record) || saved.prepared!==absentPrepared(record) ||
               JSON.stringify(SimZ1VisualQueues.canonical(saved.settings))!==JSON.stringify(SimZ1VisualQueues.canonical(INIT.settings)) ||
               ['base','final'].some(phase=>saved[phase] && (saved[phase].available!==false || saved[phase].anchor_m!==null || saved[phase].pose!==null))))
              throw new Error('Anchor absence checkpoint differs from its verified source');
            continue;
          }
          if((queriedInterpolation.has(visualQueueRenderer.key(record)) || queriedFIFO.has(visualQueueRenderer.key(record))&&visualLaneRenderer.occupancy(marker)) && visualQueueRenderer.evidence(marker,at).eligible &&
             !phases.has(visualQueueRenderer.key(record)))throw new Error('Interpolacion HOLD sin fase corporal certificada');
          roster.push(marker);}}
      visualQueueRenderer.anchorCache=null;visualQueueRenderer.releaseCache=null;
      const time=packet.requests.find(request=>Number.isFinite(request.epoch))?.epoch??0;
      const releaseState=classifying?{classifyOnly:true,external:true,depth:0,anchors:new Map()}:packet.external_pass?{external:true,depth:packet.generation,
        anchors:new Map(Object.entries(packet.release_states||{}).filter(([,value])=>value!==null).map(([key,value])=>[canonicalKey(key),value]))}:null;
      const frame=visualQueueRenderer.frame([],time,transitionNeighbors,roster,releaseState);
      if(classifying) {
        const states=packet.requests.map(request=>{
          const key=canonicalKey(request.key),record=records.find(row=>visualQueueRenderer.key(row)===key),marker=classificationMarkers.get(key);
          if(!record || request.epoch!==queueHoldTime(record) || phases.get(key)!=='final')
            throw new Error('Source classification requires its own immutable hold epoch and complete marker role');
          let classification=frame.classifications[key];
          if(!classification) {
            const evidence=marker&&visualQueueRenderer.evidence(marker,request.epoch),occupancy=marker&&visualLaneRenderer.occupancy(marker),
              reason=anchorAbsences.get(key)?.reason??(marker&&!occupancy&&!evidence.eligible?'inactive_context_without_occupancy_or_hold':null);
            classification={complete:Boolean(reason),represented:false,eligible:Boolean(evidence?.eligible),group_key:null,order_time:null,
              hold:Number.isFinite(evidence?.hold)?evidence.hold:null,start:record.timestamps[0],end:record.timestamps[1],native_entry:false,
              occupancy:occupancy?{corridor:occupancy.corridor.id,slot:occupancy.reservationSlot,ordinal:occupancy.ordinal}:null,
              departure:null,departure_complete:!occupancy,reason:reason??'unproven_context_absence'};
          }
          return {...request,input:SimZ1VisualQueues.checkpointInput(record),classification};
        });
        return {op:'classify',status:'classified',states,pose_requests:frame.pose_requests,
          constraint_records:roster.length,geometry_records:records.length};
      }
      const states=packet.requests.map(request=>{
        const normalized={...request,key:canonicalKey(request.key),stage:request.stage?[request.stage[0],canonicalKey(request.stage[1])]:null};
        const record=records.find(row=>visualQueueRenderer.key(row)===normalized.key);
        if(!record)throw new Error('Support request source record missing');
        const unavailable=(reason,anchor=false)=>({...request,result:{available:false,...(anchor?{anchor_m:null,pose_available:false}:{}),pose:null,reason},
          input:SimZ1VisualQueues.checkpointInput(record),prepared:absentPrepared(record),release:null,release_proposed:null,release_recipe:null});
        if(['base','final'].includes(request.role) && anchorAbsences.has(normalized.key))
          return unavailable(anchorAbsences.get(normalized.key).reason,true);
        // A native entered-link event can supply a single endpoint even when
        // the open interval has no admissible interpolation. The ordinary
        // queue frame omits such an inactive record, and fractionAt/FIFO cannot
        // turn its empty phase list into a body. Certify that absence exactly.
        if(['interpolate','fifo'].includes(request.role) && record?.Motion_Plan?.status==='unavailable' &&
           visualQueueRenderer.fractionAt(record,request.epoch)===null) {
          return {...request,result:{available:false,pose:null,reason:'motion_unavailable'},
            input:SimZ1VisualQueues.checkpointInput(record),
            prepared:JSON.stringify(SimZ1VisualQueues.canonical({key:normalized.key,representable:false,reason:'motion_unavailable'})),
            release:null,release_proposed:null,release_recipe:null};
        }
        let state;
        try{state=visualQueueRenderer.supportState(normalized);}catch(error){
          if(request.role==='fifo' && !visualLaneRenderer.occupancy(record) && error.message==='Estado de soporte sin entrada representable')
            return unavailable('native_occupancy_unavailable');
          throw error;
        }
        return {...state,key:request.key,epoch:request.epoch,stage:request.stage,
          result:{available:true,...state.result}};
      });
      return {op:'solve',status:'resolved',states,limitations:frame.diagnostics.limitations,
        generation:packet.generation??null,external_pass:Boolean(packet.external_pass),
        releases_next:visualQueueRenderer.releasePass.next,release_changed:visualQueueRenderer.releasePass.changed,
        constraint_records:roster.length,geometry_records:records.length};
    }
  `;
  vm.runInContext([read('simz1_continuous_loader.js'),read('simz1_visual_lanes.js'),read('simz1_visual_queues.js'),setup,functions].join('\n'),sandbox);
  return {op:'init',status:'ready'};
}
function solve(packet){if(!sandbox)throw new Error('Kernel not initialized');sandbox.PACKET=packet;
  try{
    if(packet.trips!==undefined){
      if(!packet.trips || typeof packet.trips!=='object' || Array.isArray(packet.trips) || !Array.isArray(packet.records))
        throw new Error('Invalid compact trip transport');
      const trips=packet.trips,tripBytes=new Map(),used=new Set(),records=[];
      const equal=require('node:util').isDeepStrictEqual;
      let expandedRecordsBytes=2;
      for(const raw of packet.records){
        const journey=raw.Replay_Journey_Key;
        if(typeof journey!=='string' || !Object.hasOwn(trips,journey) || !trips[journey] || typeof trips[journey]!=='object' || Array.isArray(trips[journey]))
          throw new Error('Compact native trip metadata missing');
        const trip=trips[journey];used.add(journey);
        if(raw.Trip!==undefined && !equal(raw.Trip,trip))throw new Error('Compact trip differs from inline native metadata');
        if(!tripBytes.has(journey))tripBytes.set(journey,Buffer.byteLength(JSON.stringify(trip),'utf8'));
        const stripped={...raw};delete stripped.Trip;
        expandedRecordsBytes+=Buffer.byteLength(JSON.stringify(stripped),'utf8')+8+tripBytes.get(journey)+(records.length?1:0);
        records.push({...stripped,Trip:trip});
      }
      if(Object.keys(trips).length!==used.size)throw new Error('Compact transport contains unreferenced trips');
      const envelope={...packet,records:[]};delete envelope.trips;
      const expandedBytes=Buffer.byteLength(JSON.stringify(envelope),'utf8')-2+expandedRecordsBytes;
      if(expandedBytes>64*1024*1024)throw new Error('Component expanded decoded-byte limit exceeded');
      sandbox.PACKET={...envelope,records};
    }
    return vm.runInContext('execute(PACKET)',sandbox);
  }finally{delete sandbox.PACKET;}}
const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
lines.on('line',line=>{
  try{
    if(Buffer.byteLength(line,'utf8')>64*1024*1024)throw new Error('Component decoded-byte limit exceeded');
    const packet=JSON.parse(line),result=packet.op==='init'?initialize(packet):['solve','classify'].includes(packet.op)?solve(packet):null;
    if(!result)throw new Error('Unknown kernel operation');
    result.memory={rss_bytes:process.memoryUsage().rss,heap_used_bytes:process.memoryUsage().heapUsed,max_rss_bytes:process.resourceUsage().maxRSS*1024};
    process.stdout.write(JSON.stringify(result)+'\n');
  }catch(error){process.stdout.write(JSON.stringify({status:'error',error:error.message})+'\n');}
});
