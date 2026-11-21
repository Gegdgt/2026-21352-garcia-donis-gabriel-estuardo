/* Native records are hydrated, never resampled or clipped. One active window,
 * one prefetched successor and bounded retained windows; full journeys have a
 * separate one-selection lifetime in the shared controls. */
class SimZ1ContinuousLoader {
  static visualPolicy(payload,expected=payload) {
    const mode=payload?.visual_policy ?? null,wanted=expected?.visual_policy ?? null;
    if(mode!==wanted || mode!==null && mode!=='partial-native-v1')
      throw new Error('Politica visual incompatible');
    return mode;
  }
  static recordKey(record) {
    const key=[record.vehicle,record.Link_ID,...record.timestamps];
    if(record.Trip?.Transit)key.push(record.Replay_Journey_Key ?? record.Trip.Trip_ID);
    return JSON.stringify(key);
  }
  static transitTrip(trip,record=null) {
    const t=trip?.Transit;if(t==null)return null;
    const fields=['vehicle_id','driver_id','line_id','route_id','departure_id'];
    if(t.schema!=='simz1-transit-replay-v1' || fields.some(k=>typeof t[k]!=='string' || !t[k]) ||
       trip.Person_ID!=null || trip.Driver_ID!==t.driver_id ||
       trip.Trip_ID!=='transit:'+JSON.stringify([t.vehicle_id,t.line_id,t.route_id,t.departure_id]) ||
       !['approved_domain','synthetic_fixture','computational_network'].includes(t.domain_scope) ||
       ['schedule_sha256','vehicles_sha256'].some(k=>!/^[a-f\d]{64}$/i.test(t.source?.[k] || '')) ||
       !Array.isArray(t.route_links) || !t.route_links.length || t.route_links.some(k=>typeof k!=='string' || !k) ||
       record && (record.vehicle!==t.vehicle_id || record.Driver_ID!==t.driver_id || record.Agent_ID!=null ||
                  record.Vehicle_Family!=='bus' || !t.route_links.includes(record.Link_ID)))
      throw new Error('Identidad/procedencia de expedicion publica incompatible');
    let previous=-Infinity;
    if(!Array.isArray(t.activity_intervals))throw new Error('Actividades publicas ausentes');
    for(const row of t.activity_intervals) {
      if(!Number.isFinite(row.start) || row.start<previous || row.end!=null && (!Number.isFinite(row.end) || row.end<row.start) ||
         !['stop','terminal'].includes(row.state) || !row.source)throw new Error('Actividad publica incompatible');
      previous=row.end ?? Infinity;
    }
    return t;
  }
  static transitState(record,time) {
    const trip=record?.Trip,t=trip?.Transit;if(!t)return null;
    const rows=t.activity_intervals || [];let lo=0,hi=rows.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(rows[mid].start<=time)lo=mid+1;else hi=mid;}
    const row=rows[lo-1];
    if(Number.isFinite(trip.Abort) && time>=trip.Abort)return {state:trip.Status,source:'native_abort'};
    if(trip.Status==='censored' && Number.isFinite(trip.Last_Observed_Time) && time>trip.Last_Observed_Time)
      return {state:'censored_or_open_interval',source:'last_native_observation'};
    if(row && (row.end==null || time<row.end))return {...row,state:row.state==='terminal' ? 'between_services' : 'stop'};
    if(Number.isFinite(trip.Arrival) && time>=trip.Arrival)return {
      state:row?.state==='terminal' && row.end!=null && time>=row.end ? 'expedition_completed' : t.terminal_status,
      source:t.completion_source};
    if(time<trip.Departure)return {state:'before_departure',source:'native_departure'};
    const waits=Object.entries(record.Observed_Waits || {}).filter(([,w])=>w.first<=time && time<=w.last);
    return {state:waits.length ? 'congestion_or_control_wait' : 'in_service',
      source:waits.length ? 'native_wait_events' : 'native_dispatch',wait_reasons:waits.map(([key])=>key)};
  }
  constructor(options, hooks={}) {
    this.options=Object.freeze({...options});this.hooks=hooks;
    this.cache=new Map();this.pending=new Map();this.failures=new Map();
    this.activeIndex=null;this.wantedIndex=null;this.generation=0;
    this.maxWindows=Math.max(1,Math.min(4,options.cache_windows || 3));
    this.prefetchAhead=Math.min(this.maxWindows-1,Math.max(1,Math.min(3,options.prefetch_ahead || 1)));
    this.baseBytes=options.cache_bytes || 64*1024*1024;
    this.hardBytes=Math.max(this.baseBytes,options.cache_hard_bytes || 512*1024*1024);
    this.maxBytes=this.baseBytes;this.prefetchBlocked=null;this.requestSequence=0;
    this.samples=[];this.activationSamples=[];this.knownSizes=new Map();
    this.maxFailures=16;
    this.maxRequests=Math.max(1,Math.min(3,options.max_requests || 2));this.retainedBytes=0;this.destroyed=false;
    this.metrics={requests:0,httpAttempts:0,retries503:0,completed:0,aborted:0,errors:0,evictions:0,activations:0,
      peakCachedWindows:0,peakRetainedBytes:0,peakPending:0,receivedBytes:0,lastLoadMs:0,
      prefetchHits:0,demandMisses:0,budgetAborts:0,lastActivationMs:0};
  }
  static canonicalQueueKey(value) {
      let key;try {key=JSON.parse(value);} catch {throw new Error('Clave de contexto de cola invalida');}
      if(!Array.isArray(key) || key.length!==4 || key.slice(0,3).some(part=>typeof part!=='string') ||
        !Array.isArray(key[3]) || key[3].length!==2 || !key[3].every(Number.isFinite) || key[3][1]<key[3][0])
        throw new Error('Clave de contexto de cola invalida');
      // Python/JS may encode identical numbers and Unicode differently. Only
      // metadata identity text is normalized; native timestamps stay untouched.
      return JSON.stringify(key);
  }
  static queueStatuses(queue) {
    const canonical=SimZ1ContinuousLoader.canonicalQueueKey;
    const equal=(a,b)=>a===b || a!=null && b!=null && typeof a==='object' && typeof b==='object' &&
      Array.isArray(a)===Array.isArray(b) && Object.keys(a).length===Object.keys(b).length &&
      Object.keys(a).every(key=>Object.prototype.hasOwnProperty.call(b,key) && equal(a[key],b[key]));
    const result=new Map();
    for(const [raw,status] of Object.entries(queue?.by_seed || {})) {
      if(!status || typeof status.complete!=='boolean' || !Array.isArray(status.record_keys))
        throw new Error('Completitud de contexto de cola incompatible');
      const key=canonical(raw),row={...status,record_keys:[...new Set(status.record_keys.map(canonical))]};
      if(queue.dependency_policy==='native-causal-epochs-v1' && row.complete) {
        const certificate=row.support_certificate,phases={};
        if(certificate?.policy!=='native-causal-epochs-v1' || certificate.complete!==true ||
           certificate.poses_certified!==false || !certificate.phase_keys ||
           typeof certificate.phase_keys!=='object' || Array.isArray(certificate.phase_keys))
          throw new Error('Certificado de fases causales incompatible');
        for(const [member,phase] of Object.entries(certificate.phase_keys)) {
          const canonicalMember=canonical(member);
          if(!['base','final'].includes(phase) || phases[canonicalMember] && phases[canonicalMember]!==phase)
            throw new Error('Fases causales contradictorias');
          phases[canonicalMember]=phase;
        }
        if(phases[key]!=='final' || Object.keys(phases).length!==row.record_keys.length ||
           row.record_keys.some(member=>!Object.prototype.hasOwnProperty.call(phases,member)))
          throw new Error('Cobertura de fases causales incompleta');
        row.support_certificate={...certificate,phase_keys:phases};
      }
      if(result.has(key) && !equal(result.get(key),row))throw new Error('Estados de contexto de cola contradictorios para la misma identidad');
      result.set(key,row);
    }
    return result;
  }
  static queueCheckpoints(queue,identity=null) {
    const result=new Map(),raw=queue?.checkpoints;
    const statuses=SimZ1ContinuousLoader.queueStatuses(queue);
    const required=new Set([...statuses.values()].filter(row=>row.complete &&
      row.support_certificate?.converged===true).flatMap(row=>row.record_keys));
    if(raw==null) {
      if(required.size)throw new Error('Checkpoint sin capsulas requeridas por el contexto convergente');
      return result;
    }
    if(typeof raw!=='object' || Array.isArray(raw))throw new Error('Capsulas de soporte invalidas');
    const contract=queue.checkpoint_contract,hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    if(!contract || !Number.isSafeInteger(contract.generation) || contract.generation<0 ||
       ['index_sha256','kernel_sha256','geometry_sha256','graph_sha256','root_digest'].some(key=>!hash(contract[key])) ||
       !contract.identity || typeof contract.identity.run_id!=='string' || !contract.identity.run_id ||
       !Number.isSafeInteger(contract.identity.iteration) || contract.identity.iteration<0 ||
       !hash(contract.identity.run_manifest_sha256))throw new Error('Contrato de checkpoint incompleto');
    if(identity && ['run_id','iteration','run_manifest_sha256'].some(key=>identity[key]!==contract.identity[key]))
      throw new Error('Identidad de checkpoint incompatible');
    if(identity?.checkpoint_library_root!=null &&
       (!hash(identity.checkpoint_library_root) || contract.root_digest!==identity.checkpoint_library_root))
      throw new Error('Checkpoint de otra biblioteca que la respuesta solicitada');
    const settings=contract.settings;
    if(!settings || Object.keys(settings).sort().join(',')!=='gap_m,lateral_clearance_m,stop_line_setback_m' ||
       !Object.values(settings).every(Number.isFinite) || settings.gap_m<.1 || settings.gap_m>10 ||
       settings.lateral_clearance_m<0 || settings.lateral_clearance_m>1 || settings.stop_line_setback_m<0)
      throw new Error('Margenes de checkpoint incompatibles');
    if(identity?.checkpoint_settings && Object.keys(settings).some(key=>identity.checkpoint_settings[key]!==settings[key]))
      throw new Error('Margenes de checkpoint distintos de la reconstruccion solicitada');
    const members=new Set([...statuses.values()].filter(row=>row.complete).flatMap(row=>row.record_keys));
    for(const [key,capsule] of Object.entries(raw)) {
      const canonical=SimZ1ContinuousLoader.canonicalQueueKey(key);
      if(result.has(canonical) || !members.has(canonical) || capsule?.schema!=='native-queue-phase-capsule-v1' ||
         capsule.complete!==true || !capsule.input || !capsule.prepared ||
         Object.keys(settings).some(name=>capsule.settings?.[name]!==settings[name]))
        throw new Error('Capsula sin soporte completo compatible');
      const witnesses=[...statuses.values()].filter(row=>row.complete && row.record_keys.includes(canonical));
      const phase=witnesses.some(row=>(row.support_certificate?.phase_keys?.[canonical]??'final')==='final')?'final':'base';
      const certified=witnesses.some(row=>{
        const proof=row.support_certificate;
        return proof?.converged===true && proof.generation===contract.generation &&
          proof.graph_sha256===contract.graph_sha256 && proof.root_digest===contract.root_digest &&
          (phase==='base' || proof.phase_keys?.[canonical]==='final');
      });
      if(!certified)throw new Error('Checkpoint sin convergencia acreditada');
      if(!Number.isFinite(capsule.base?.anchor_m) || phase==='final' &&
         (!Number.isFinite(capsule.final?.anchor_m) || !Array.isArray(capsule.final.turn_bounds)) ||
         !Object.prototype.hasOwnProperty.call(capsule,'release') || !Array.isArray(capsule.fifo))
        throw new Error('Capsula sin resultados de fase completos');
      result.set(canonical,capsule);
    }
    for(const key of required)if(!result.has(key))
      throw new Error('Checkpoint sin cobertura completa de capsulas requeridas');
    return result;
  }
  // Pure preparation shared by the worker and the small-fixture fallback.
  // Every index refers to the same hydrated records (structured clone preserves
  // these aliases); neither timestamps nor Motion_Plan are copied/recomputed.
  static prepare(payload) {
    const visualPolicy=SimZ1ContinuousLoader.visualPolicy(payload);
    const started=performance.now(),phases={};let tick=started;
    const measure=name=>{const now=performance.now();phases[name]=now-tick;tick=now;};
    const timelines=new Map(),recordsByTrip=new Map(),transitionTimelines=new Map(),transitionRecords=new Map(),
      laneTimelines=new Map(),signalTimelines=new Map(),journeys=new Map(),holdRecords=[];
    const add=(map,key,row)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(row);};
    const tripKey=r=>JSON.stringify([r.Agent_ID ?? r.Trip?.Person_ID ?? null,
      r.Trip?.Trip_ID!=null ? ['id',r.Trip.Trip_ID] : Number.isFinite(r.Trip?.Departure) ? ['departure',r.Trip.Departure] :
        ['segment',r.vehicle,...r.timestamps]]);
    // Repeated immutable rows are one observation. Compare the full JSON value
    // only when identities collide: different plans/paths remain contradictory
    // evidence rather than being silently replaced by their neighbour/window.
    const equal=(a,b)=>{
      if(a===b)return true;
      if(a===null || b===null || typeof a!=='object' || typeof b!=='object' || Array.isArray(a)!==Array.isArray(b))return false;
      const keys=Object.keys(a);
      return keys.length===Object.keys(b).length && keys.every(key=>Object.prototype.hasOwnProperty.call(b,key) && equal(a[key],b[key]));
    };
    const unique=groups=>{
      const buckets=new Map(),result=[];
      for(const rows of groups)for(const record of rows) {
        const key=JSON.stringify([record.vehicle,record.Agent_ID ?? null,record.Replay_Journey_Key ?? null,record.Link_ID,record.timestamps]);
        const bucket=buckets.get(key);
        if(bucket?.some(previous=>equal(previous,record)))continue;
        if(bucket)bucket.push(record);else buckets.set(key,[record]);
        result.push(record);
      }
      return result;
    };
    const activeSegments=unique([payload.segments]);
    const queue=payload.queue_context,queueContexts=SimZ1ContinuousLoader.queueStatuses(queue),
      queueContextCheckpoints=SimZ1ContinuousLoader.queueCheckpoints(queue,payload.run_id!=null?payload:null);
    const queueContextMembers=new Set([...queueContexts.values()].filter(row=>row.complete).flatMap(row=>row.record_keys));
    const queueContextPhases=new Map();
    for(const row of queueContexts.values())if(row.complete)for(const member of row.record_keys) {
      const phase=row.support_certificate?.phase_keys?.[member] ?? 'final';
      if(!queueContextPhases.has(member) || phase==='final')queueContextPhases.set(member,phase);
    }
    const queueKey=r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key ?? '',r.Link_ID,r.timestamps]);
    const queueRosterRecords=unique([queue?.segments || []]).filter(row=>queueContextMembers.has(queueKey(row)));
    for(const key of queueContextMembers) {
      if(!queueContexts.has(key))queueContexts.set(key,
        {complete:true,reason:null,member_of_complete_closure:true,phase:queueContextPhases.get(key)});
      else if(queueContexts.get(key).complete)queueContexts.set(key,
        {...queueContexts.get(key),phase:queueContextPhases.get(key)});
      if(queueContexts.get(key).complete && queueContextCheckpoints.has(key))queueContexts.set(key,
        {...queueContexts.get(key),checkpoint:queueContextCheckpoints.get(key)});
    }
    const order=(a,b)=>a.timestamps[0]-b.timestamps[0];
    for(const r of activeSegments){add(timelines,r.vehicle,r);add(recordsByTrip,tripKey(r),r);}
    for(const map of [timelines,recordsByTrip])for(const rows of map.values())rows.sort(order);
    measure('vehicleTripIndexesMs');
    for(const r of unique([activeSegments,payload.context_segments || [],queueRosterRecords,queue?.transition_segments || []])) {
      add(transitionTimelines,r.vehicle,r);add(journeys,JSON.stringify([r.vehicle,r.Replay_Journey_Key ?? tripKey(r)]),r);
    }
    for(const rows of transitionTimelines.values()) {
      rows.sort(order);
    }
    for(const r of unique([queueRosterRecords,queue?.transition_segments || []]))if(Number.isFinite(SimZ1ContinuousLoader.facilityDepartureHold(r) ?? r.Motion_Plan?.hold_start ?? r.Motion_Plan?.native_wait_boundary ??
      (r.Motion_Plan?.status==='stationary' && r.Boundary_Provenance?.start==='VehicleArrivesAtFacility' &&
       r.Boundary_Provenance?.end==='VehicleDepartsAtFacility' ? r.timestamps[0] : null) ??
      (r.Native_Occupancy?.policy==='corridor-length-v1' ? r.timestamps[0] : null)))holdRecords.push(r);
    for(const rows of journeys.values()) {
      rows.sort((a,b)=>order(a,b) || a.timestamps[1]-b.timestamps[1]);
      for(let i=0;i<rows.length;i++)transitionRecords.set(SimZ1ContinuousLoader.recordKey(rows[i]),
        {previous:rows[i-1],next:rows[i+1]});
    }
    if(visualPolicy==='partial-native-v1') {
      // A moving body can depend on an adjacent pending HOLD through its rear,
      // release or interpolation. Propagate unavailability only over the
      // available contiguous intervals of the same native journey. This is
      // conservative display suppression, never a complete causal certificate.
      const records=new Map([...journeys.values()].flat().map(row=>[queueKey(row),row]));
      const pending=[...queueContexts].filter(([,row])=>row.reason==='reconstruction_pending').map(([key])=>key);
      const visited=new Set(pending);
      for(let index=0;index<pending.length;index++) {
        const key=pending[index],record=records.get(key);if(!record)continue;
        const pair=transitionRecords.get(SimZ1ContinuousLoader.recordKey(record)) || {};
        for(const adjacent of [pair.previous,pair.next]) {
          if(!adjacent || adjacent.vehicle!==record.vehicle || adjacent.Replay_Journey_Key!==record.Replay_Journey_Key ||
             adjacent.timestamps[1]!==record.timestamps[0] && record.timestamps[1]!==adjacent.timestamps[0])continue;
          const member=queueKey(adjacent);
          if(visited.has(member) || queueContexts.get(member)?.complete===true && queueContextCheckpoints.get(member)?.final)continue;
          visited.add(member);pending.push(member);
          queueContexts.set(member,{complete:false,reason:'reconstruction_pending',body_position_available:false,
            record_keys:[],dependency_key:key,availability:'dependent_on_unreconstructed_interval'});
        }
      }
    }
    measure('transitionIndexesMs');
    const seen=new Set();
    // Complete in-window native order wins at equal timestamps. Context carries
    // only the latest predecessor, which must not move before an earlier event
    // from the complete window when the duplicate latest row is removed.
    for(const rows of [payload.lane_replay?.events || [],queue?.lane_events || [],payload.context_lane_events || []])for(const event of rows) {
      const key=JSON.stringify(event);if(seen.has(key))continue;seen.add(key);add(laneTimelines,event.vehicle,event);
    }
    for(const rows of laneTimelines.values())rows.sort((a,b)=>a.time-b.time);
    for(const series of payload.signal_replay?.series || [])signalTimelines.set(JSON.stringify([series.system_id,series.group_id]),series.states);
    measure('laneSignalIndexesMs');
    // Sort starts once, not once per recursive subtree as the old activation did.
    const build=sorted=>{
      if(!sorted.length)return null;
      const center=sorted[sorted.length>>>1].timestamps[0],left=[],right=[],cross=[];
      for(const r of sorted) {
        if(r.timestamps[1]<=center)left.push(r);else if(r.timestamps[0]>center)right.push(r);else cross.push(r);
      }
      return {center,byStart:cross,byEnd:[...cross].sort((a,b)=>b.timestamps[1]-a.timestamps[1]),left:build(left),right:build(right)};
    };
    const intervalIndex=build(activeSegments.filter(r=>r.timestamps[1]>r.timestamps[0]).sort(order));
    measure('intervalIndexMs');
    return {timelines,recordsByTrip,transitionTimelines,transitionRecords,laneTimelines,signalTimelines,holdRecords,
      queueContexts,queueContextMembers,queueContextPhases,queueContextCheckpoints,queueRosterRecords,
      incidents:payload.incidents || [],syntheticIncidents:payload.synthetic_incidents ?? null,
      intervalIndex,phases,totalMs:performance.now()-started};
  }
  static facilityDepartureHold(record) {
    const boundary=record.Boundary_Provenance,plan=record.Motion_Plan;
    return plan?.status==='stationary' && plan.distance_m===0 &&
      boundary?.start==='VehicleDepartsAtFacility' && Number.isFinite(boundary.start_relative) &&
      boundary.start_relative===boundary.end_relative && record.Native_Occupancy?.policy==='corridor-length-v1' ?
      record.timestamps[0] : null;
  }
  static validateRecords(payload,o,index,start,end) {
    const visualPolicy=SimZ1ContinuousLoader.visualPolicy(payload,o);
    if(payload.run_id!==o.run_id || payload.iteration!==o.iteration || payload.run_manifest_sha256!==o.run_manifest_sha256 ||
       o.source_version!=null && payload.source_version!==o.source_version ||
       o.checkpoint_library_root!=null && payload.checkpoint_library_root!==o.checkpoint_library_root)
      throw new Error('Identidad de corrida, iteracion o manifest incompatible');
    if(payload.index!==index || payload.start_seconds!==start || payload.end_seconds!==end || !Array.isArray(payload.segments) ||
      !payload.trips || typeof payload.trips!=='object')throw new Error('Ventana temporal recibida incompatible');
    if(payload.context_segments!==undefined && !Array.isArray(payload.context_segments))throw new Error('Contexto de transicion invalido');
    if(payload.context_lane_events!==undefined && !Array.isArray(payload.context_lane_events))throw new Error('Eventos de contexto invalidos');
    const queue=payload.queue_context;
    if(visualPolicy==='partial-native-v1' && !queue || queue && (queue.visual_policy ?? null)!==visualPolicy)
      throw new Error('Modo de contexto de cola incompatible');
    if(queue!=null && (queue.schema_version!==1 || queue.policy!=='native-hold-closure-v1' ||
      !queue.by_seed || typeof queue.by_seed!=='object' || !queue.trips || typeof queue.trips!=='object' ||
      !Array.isArray(queue.segments) || !Array.isArray(queue.transition_segments) || !Array.isArray(queue.lane_events)))
      throw new Error('Contrato de contexto de cola invalido');
    const same=(a,b)=>a===b || a!=null && b!=null && typeof a==='object' && typeof b==='object' &&
      Array.isArray(a)===Array.isArray(b) && Object.keys(a).length===Object.keys(b).length &&
      Object.keys(a).every(key=>Object.prototype.hasOwnProperty.call(b,key) && same(a[key],b[key]));
    for(const [key,trip] of Object.entries(queue?.trips || {}))if(Object.prototype.hasOwnProperty.call(payload.trips,key) && !same(payload.trips[key],trip))
      throw new Error('Metadatos de viaje contradictorios en contexto de cola');
    for(const rows of [payload.segments,payload.context_segments || [],queue?.segments || [],queue?.transition_segments || []])for(const record of rows) {
      const trip=Object.prototype.hasOwnProperty.call(payload.trips,record.Replay_Journey_Key) ? payload.trips[record.Replay_Journey_Key] : queue?.trips?.[record.Replay_Journey_Key];
      if(!trip || !Array.isArray(record.timestamps) ||
        record.timestamps.length!==2 || !record.timestamps.every(Number.isFinite) || record.timestamps[1]<record.timestamps[0])
        throw new Error('Tramo o identidad de viaje invalida en ventana');
      record.Trip=trip;
      SimZ1ContinuousLoader.transitTrip(trip,record);
    }
    if(queue) {
      SimZ1ContinuousLoader.queueCheckpoints(queue,o);
      const keys=new Set(queue.segments.map(r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key ?? '',r.Link_ID,r.timestamps]))),members=new Set();
      for(const [key,row] of SimZ1ContinuousLoader.queueStatuses(queue)) {
        if(row.reason==='reconstruction_pending' && (visualPolicy!=='partial-native-v1' || row.complete!==false ||
           row.body_position_available!==false || row.record_keys.length || row.checkpoint!=null || row.support_certificate!=null))
          throw new Error('Disponibilidad parcial de cuerpo incompatible');
        if(!row || typeof row.complete!=='boolean' || !Array.isArray(row.record_keys) ||
           row.complete && (!row.record_keys.includes(key) || row.record_keys.some(member=>typeof member!=='string' || !keys.has(member))) ||
           !row.complete && row.record_keys.length)throw new Error('Completitud de contexto de cola incompatible');
        if(row.complete)for(const member of row.record_keys)members.add(member);
        if(row.complete && queue.dependency_policy==='native-causal-epochs-v1') {
          const identity=row.support_certificate.source_contract?.identity ??
            (row.support_certificate.converged===true ? queue.checkpoint_contract?.identity : null);
          if(!identity || identity.run_id!==o.run_id || identity.iteration!==o.iteration ||
             identity.run_manifest_sha256!==o.run_manifest_sha256)
            throw new Error('Identidad del soporte causal incompatible');
        }
      }
      if([...keys].some(key=>!members.has(key)))throw new Error('Roster parcial de cola sin cierre completo');
      for(const event of queue.lane_events)if(!event || typeof event.vehicle!=='string' || !Number.isFinite(event.time))
        throw new Error('Evento de carril de contexto invalido');
    }
    const groups=new Set();
    for(const series of payload.signal_replay?.series || []) {
      const key=JSON.stringify([series.system_id,series.group_id]);
      if(groups.has(key) || !Array.isArray(series.states))throw new Error('Serie nativa de semaforo incompatible');groups.add(key);
    }
    return payload;
  }
  decode(raw,index,token) {
    const options=this.options,[start,end]=this.bounds(index),requestId=++this.requestSequence;
    // One worker per live response, at most maxRequests. Abort terminates it;
    // there is no unbounded worker queue behind a sequence of seeks.
    if(options.worker!==false && typeof Worker==='function' && typeof Blob==='function' && typeof URL!=='undefined' && typeof URL.createObjectURL==='function') {
      return new Promise((resolve,reject)=>{
        const source=SimZ1ContinuousLoader.toString()+`;self.onmessage=({data:d})=>{try {
          const t=performance.now(),text=typeof d.raw==='string' ? d.raw : new TextDecoder().decode(d.raw),decoded=performance.now();
          const payload=JSON.parse(text),parsed=performance.now();
          SimZ1ContinuousLoader.validateRecords(payload,d.options,d.index,d.start,d.end);const validated=performance.now();
          const prepared=SimZ1ContinuousLoader.prepare(payload),finished=performance.now();
          self.postMessage({requestId:d.requestId,index:d.index,payload,prepared,metrics:{decodeMs:decoded-t,parseMs:parsed-decoded,validateMs:validated-parsed,
            prepareMs:finished-validated,preparePhases:prepared.phases,workerComputeMs:finished-t}});
        }catch(e){self.postMessage({requestId:d.requestId,index:d.index,error:e.message});}};`;
        const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));
        let worker;
        const cleanup=()=>{worker?.terminate();URL.revokeObjectURL(url);token.controller.signal.removeEventListener('abort',abort);token.worker=null;};
        const abort=()=>{cleanup();const e=new Error('Preparacion cancelada');e.name='AbortError';reject(e);};
        try {
          worker=new Worker(url);token.worker=worker;
          token.controller.signal.addEventListener('abort',abort,{once:true});
          worker.onmessage=({data})=>{
            if(data.requestId!==requestId || data.index!==index)return;
            cleanup();if(data.error)reject(new Error(data.error));else resolve({...data,mode:'worker'});
          };
          worker.onerror=event=>{cleanup();reject(new Error(event.message || 'Fallo al preparar ventana en Worker'));};
          worker.postMessage({requestId,index,start,end,raw,options:{run_id:options.run_id,iteration:options.iteration,
            run_manifest_sha256:options.run_manifest_sha256,source_version:options.source_version,
            visual_policy:options.visual_policy,
            checkpoint_library_root:options.checkpoint_library_root,checkpoint_settings:options.checkpoint_settings}},
            typeof raw==='string' ? [] : [raw]);
          if(token.controller.signal.aborted)abort();
        } catch(error){cleanup();reject(error);}
      });
    }
    const t=performance.now(),text=typeof raw==='string' ? raw : new TextDecoder().decode(raw),decoded=performance.now(),payload=JSON.parse(text),parsed=performance.now();
    SimZ1ContinuousLoader.validateRecords(payload,options,index,start,end);const validated=performance.now();
    const prepared=SimZ1ContinuousLoader.prepare(payload);
    return Promise.resolve({payload,prepared,mode:'main_thread_fallback',metrics:{decodeMs:decoded-t,parseMs:parsed-decoded,validateMs:validated-parsed,
      prepareMs:performance.now()-validated,preparePhases:prepared.phases}});
  }
  indexAt(time) {
    const o=this.options;
    return Math.max(0,Math.min(o.window_count-1,Math.floor((time-o.start_seconds)/o.window_seconds)));
  }
  bounds(index) {
    const o=this.options,start=o.start_seconds+index*o.window_seconds;
    return [start,index===o.window_count-1 ? (o.data_end_seconds ?? o.end_seconds) : Math.min(o.end_seconds,start+o.window_seconds)];
  }
  snapshot() {
    return {...this.metrics,activeIndex:this.activeIndex,wantedIndex:this.wantedIndex,
      cachedIndices:[...this.cache.keys()],pendingIndices:[...this.pending.keys()],
      retryingIndices:[...this.pending.entries()].filter(([,request])=>request.retrying).map(([index])=>index),
      cachedWindows:this.cache.size,pendingRequests:this.pending.size,
      rememberedFailures:this.failures.size,
      retainedBytes:this.retainedBytes,cacheByteBudget:this.maxBytes,
      cacheBaseBytes:this.baseBytes,cacheHardBytes:this.hardBytes,prefetchBlocked:this.prefetchBlocked,
      knownWindowBytes:Object.fromEntries(this.knownSizes),loadSamples:this.samples.slice(),activationSamples:this.activationSamples.slice(),
      // JSON bytes are a reproducible cache bound, not a measurement of JS heap.
      cacheByteAccounting:'UTF-8 JSON response bytes; JS heap measured separately',
      oversizedActiveWindow:(this.cache.get(this.activeIndex)?.bytes || 0)>this.baseBytes,
      overHardBytes:Math.max(0,this.retainedBytes-this.hardBytes),
      hardLimitException:this.retainedBytes<=this.hardBytes ? null : this.cache.size===1 ?
        'single_required_window' : 'active_and_wanted_transaction',
      retainedSegments:[...this.cache.values()].reduce((n,item)=>n+item.payload.segments.length,0),
      retainedContextSegments:[...this.cache.values()].reduce((n,item)=>n+(item.payload.context_segments?.length || 0),0)};
  }
  notify() { this.hooks.onState?.(this.snapshot()); }
  validate(payload,index) {
    SimZ1ContinuousLoader.validateRecords(payload,this.options,index,...this.bounds(index));
    this.hooks.validatePayload?.(payload);
    return payload;
  }
  touch(index) {
    const item=this.cache.get(index);
    if (item) {this.cache.delete(index);this.cache.set(index,item);}
    return item;
  }
  evict() {
    const anchor=this.cache.get(this.wantedIndex) || this.cache.get(this.activeIndex);
    const base=this.wantedIndex ?? this.activeIndex;
    const successors=Array.from({length:this.prefetchAhead},(_,n)=>base+n+1);
    const aheadBytes=successors.reduce((sum,index)=>sum+(this.cache.get(index)?.bytes || 0),0);
    // Budget follows observed decoded sizes, with a fixed ceiling. The active
    // and wanted windows survive a transaction even if one alone is oversized.
    this.maxBytes=Math.min(this.hardBytes,Math.max(this.maxBytes,this.baseBytes,(anchor?.bytes || 0)+aheadBytes));
    while (this.cache.size>this.maxWindows || this.retainedBytes>this.maxBytes && this.cache.size>1) {
      const protectedNext=(this.wantedIndex ?? this.activeIndex)+1;
      const candidates=[...this.cache.keys()].filter(index=>index!==this.activeIndex && index!==this.wantedIndex);
      const victim=candidates.find(index=>!successors.includes(index)) ?? candidates.sort((a,b)=>b-a)[0];
      if (victim==null) break;
      if(victim===protectedNext)this.prefetchBlocked={index:victim,reason:'pair_exceeds_hard_limit',bytes:this.cache.get(victim).bytes};
      this.retainedBytes-=this.cache.get(victim).bytes;this.cache.delete(victim);this.metrics.evictions++;
    }
    this.metrics.peakCachedWindows=Math.max(this.metrics.peakCachedWindows,this.cache.size);
    this.metrics.peakRetainedBytes=Math.max(this.metrics.peakRetainedBytes,this.retainedBytes);
  }
  activate(index) {
    const item=this.touch(index);if(!item)return false;
    if(this.activeIndex!==index) {
      const began=performance.now(),previousIndex=this.activeIndex;
      // Validation and preparation finished before publishing any live index.
      this.hooks.onWindow?.(item.payload,item.prepared);
      this.activeIndex=index;this.metrics.activations++;
      if(item.prefetched)this.metrics.prefetchHits++;
      this.metrics.lastActivationMs=performance.now()-began;
      this.activationSamples.push({index,previousIndex,activationMs:this.metrics.lastActivationMs,
        readyBeforeDemand:item.prefetched,bytes:item.bytes});
      if(this.activationSamples.length>32)this.activationSamples.shift();
    }
    this.evict();this.notify();return true;
  }
  cancelExcept(keep) {
    for(const [index,request] of this.pending) if(!keep.has(index)) {
      request.controller.abort();this.pending.delete(index);this.metrics.aborted++;
    }
  }
  rememberFailure(index,message) {
    this.failures.delete(index);this.failures.set(index,message);
    while(this.failures.size>this.maxFailures) {
      const victim=[...this.failures.keys()].find(key=>key!==this.wantedIndex);
      this.failures.delete(victim);
    }
  }
  requestTime(time,{seek=false,retry=false}={}) {
    const index=this.indexAt(time);
    if(seek) {
      this.generation++;
      // Seeking within the active window must not cancel its useful successor:
      // abort only stops the client, while a local SQLite query may still run.
      // Re-requesting the same successor would occupy both server query slots.
      this.cancelExcept(new Set(Array.from({length:this.prefetchAhead+1},(_,n)=>index+n)));
      if(retry)this.failures.delete(index);
    }
    this.wantedIndex=index;
    if(this.activate(index)) {this.prefetch(index);return true;}
    if(this.failures.has(index)) {this.hooks.onError?.(index,new Error(this.failures.get(index)));return false;}
    // Demand always takes priority over an irrelevant speculative fetch.
    if(this.pending.size>=this.maxRequests && !this.pending.has(index))this.cancelExcept(new Set([index]));
    if(!this.pending.has(index))this.metrics.demandMisses++;
    this.fetchWindow(index);this.prefetch(index);this.notify();return false;
  }
  prefetch(index) {
    // A cold mandatory SQLite window can consume the query budget by itself.
    // Callers may defer speculation until its complete, validated activation;
    // the default retains the historical eager-loader contract.
    if(this.wantedIndex!==index || this.activeIndex!==index || !this.cache.has(index))return;
    if(this.hooks.canPrefetch?.()===false)return;
    for(let next=index+1;next<=index+this.prefetchAhead;next++) {
    if(next>this.indexAt(this.options.visible_end_seconds ?? this.options.end_seconds) ||
       next>=this.options.window_count || this.cache.has(next) || this.pending.has(next) ||
       this.maxWindows<2 || this.pending.size>=this.maxRequests)continue;
    const bytes=this.knownSizes.get(next),current=this.cache.get(index)?.bytes || this.knownSizes.get(index) || 0;
    if(bytes && current+bytes>this.hardBytes) {this.prefetchBlocked={index:next,reason:'pair_exceeds_hard_limit',bytes};return;}
    this.prefetchBlocked=null;
    this.fetchWindow(next);
    }
  }
  retryDelay(response,retry) {
    const backoff=Math.min(10000,1000*2**Math.min(retry,4));
    const header=response.headers?.get?.('Retry-After')?.trim();
    if(!header)return backoff;
    const requested=/^\d+(?:\.\d+)?$/.test(header) ? Number(header)*1000 : Date.parse(header)-Date.now();
    // Retry-After is a minimum. One demanded window waits, without a fixed
    // attempt limit; sustained saturation polls at most once every ten seconds.
    return Number.isFinite(requested) ? Math.max(backoff,requested,0) : backoff;
  }
  waitForRetry(milliseconds,signal) {
    return new Promise((resolve,reject)=>{
      let timer=null;
      const abort=()=>{if(timer!=null)clearTimeout(timer);signal.removeEventListener('abort',abort);
        const error=new Error('Peticion temporal cancelada');error.name='AbortError';reject(error);};
      signal.addEventListener('abort',abort,{once:true});
      timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},milliseconds);
      if(signal.aborted)abort();
    });
  }
  fetchWindow(index) {
    if(this.destroyed || this.pending.has(index) || this.cache.has(index) || this.failures.has(index))return;
    const controller=new AbortController(),token={controller,started:performance.now()};
    this.pending.set(index,token);this.metrics.requests++;
    this.metrics.peakPending=Math.max(this.metrics.peakPending,this.pending.size);
    const started=performance.now(),o=this.options;
    const query=new URLSearchParams({index:String(index),run_id:o.run_id,iteration:String(o.iteration),
      run_manifest_sha256:o.run_manifest_sha256});
    if(o.source_version!=null)query.set('source_version',o.source_version);
    if(o.visual_policy!=null)query.set('visual_policy',o.visual_policy);
    if(o.checkpoint_library_root!=null)query.set('checkpoint_library_root',o.checkpoint_library_root);
    (async()=>{
      try {
        let response;
        for(let retry=0;;retry++) {
          if(controller.signal.aborted || this.pending.get(index)!==token)return;
          this.metrics.httpAttempts++;
          query.set('priority',index===this.wantedIndex ? 'demand' : 'prefetch');
          response=await fetch(o.window_endpoint+'?'+query,{signal:controller.signal,cache:'no-store'});
          if(controller.signal.aborted || this.pending.get(index)!==token)return;
          if(response.ok)break;
          let failure;
          try {failure=JSON.parse(await response.text());} catch (_) {failure=null;}
          if(controller.signal.aborted || this.pending.get(index)!==token)return;
          // Saturation is distinct from a SQL/validation failure. An old
          // server's 503 is still compatible, but an explicit non-retryable
          // response remains visible and offers a manual retry.
          if(failure?.run_id!=null && (failure.run_id!==o.run_id || failure.iteration!==o.iteration ||
             failure.run_manifest_sha256!==o.run_manifest_sha256 ||
             o.source_version!=null && failure.source_version!==o.source_version))throw new Error('Respuesta de espera de otra identidad');
          if(failure?.run_id!=null)SimZ1ContinuousLoader.visualPolicy(failure,o);
          if(response.status!==503 || failure?.retryable===false)
            throw new Error('Carga temporal HTTP '+response.status+(failure?.error ? ': '+failure.error : ''));
          token.waitReason=failure?.error || 'Servidor ocupado; la carga se reintentara automaticamente';
          this.metrics.retries503++;token.retrying=true;this.notify();
          await this.waitForRetry(this.retryDelay(response,retry),controller.signal);
          token.retrying=false;this.notify();
        }
        const headersAt=performance.now(),declared=Number(response.headers?.get?.('X-SimZ1-JSON-Bytes'));
        if(declared>0)this.knownSizes.set(index,declared);
        const anchor=this.cache.get(this.wantedIndex) || this.cache.get(this.activeIndex);
        if(index!==this.wantedIndex && declared>0 && (anchor?.bytes || this.knownSizes.get(this.wantedIndex) || 0)+declared>this.hardBytes) {
          this.prefetchBlocked={index,reason:'pair_exceeds_hard_limit',bytes:declared};
          controller.abort();this.pending.delete(index);this.metrics.aborted++;this.metrics.budgetAborts++;this.notify();return;
        }
        let raw=response.arrayBuffer ? await response.arrayBuffer() : await response.text();
        if(controller.signal.aborted || this.pending.get(index)!==token)return;
        const bodyAt=performance.now(),bytes=typeof raw==='string' ?
          (typeof TextEncoder==='function' ? new TextEncoder().encode(raw).byteLength : raw.length*2) : raw.byteLength;
        if(declared>0 && bytes!==declared)throw new Error('Respuesta de ventana truncada: longitud incompatible');
        const expectedHash=response.headers?.get?.('X-SimZ1-JSON-SHA256');
        if(expectedHash && typeof crypto!=='undefined' && crypto.subtle) {
          const digest=await crypto.subtle.digest('SHA-256',typeof raw==='string' ? new TextEncoder().encode(raw) : raw);
          const actual=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
          if(actual!==expectedHash)throw new Error('Integridad de ventana incompatible');
          if(controller.signal.aborted || this.pending.get(index)!==token)return;
        }
        this.knownSizes.set(index,bytes);
        const job=this.decode(raw,index,token),dispatchAt=performance.now();raw=null;
        const decoded=await job,preparedAt=performance.now();
        if(controller.signal.aborted || this.pending.get(index)!==token)return;
        const {payload,prepared}=decoded;
        // Recheck the worker envelope before accepting it; no stale run/index
        // can reach hooks even if a worker or fetch completes after a seek.
        if(payload.index!==index || payload.run_id!==o.run_id || payload.iteration!==o.iteration ||
          payload.run_manifest_sha256!==o.run_manifest_sha256 ||
          o.source_version!=null && payload.source_version!==o.source_version)throw new Error('Respuesta preparada de otra identidad');
        SimZ1ContinuousLoader.visualPolicy(payload,o);
        const validation=this.hooks.validatePayload?.(payload,controller.signal);
        if(validation?.then)await validation;
        if(controller.signal.aborted || this.pending.get(index)!==token)return;
        const spatialAt=performance.now(),runtimePreparation=this.hooks.preparePayload?.(payload,prepared,controller.signal);
        if(runtimePreparation?.then)await runtimePreparation;
        if(controller.signal.aborted || this.pending.get(index)!==token)return;
        const readyAt=performance.now();
        const sample={index,bytes,loadMs:readyAt-started,headersMs:headersAt-started,
          bodyReadAndBrowserDecompressMs:bodyAt-headersAt,dispatchMs:dispatchAt-bodyAt,
          preparationRoundTripMs:preparedAt-bodyAt,spatialValidationMs:spatialAt-preparedAt,runtimePreparationMs:readyAt-spatialAt,
          mode:decoded.mode,...decoded.metrics,server:payload.timings_seconds || null,
          serverTiming:response.headers?.get?.('Server-Timing') || null,
          prefetched:index!==this.wantedIndex,segments:payload.segments.length};
        this.samples.push(sample);if(this.samples.length>32)this.samples.shift();
        this.pending.delete(index);
        this.cache.set(index,{payload,prepared,bytes,prefetched:index!==this.wantedIndex});this.retainedBytes+=bytes;
        this.metrics.completed++;this.metrics.receivedBytes+=bytes;this.metrics.lastLoadMs=performance.now()-started;
        if(index===this.wantedIndex) {
          this.activate(index);this.hooks.onReady?.(index);this.prefetch(index);
        }
        this.evict();this.notify();
      } catch(error) {
        if(controller.signal.aborted || this.pending.get(index)!==token)return;
        if(error instanceof TypeError && /fetch|network|connection/i.test(error.message))
          error=new Error('Conexion con el replay interrumpida: '+error.message+'. Compruebe el servidor y reintente');
        this.pending.delete(index);this.rememberFailure(index,error.message);this.metrics.errors++;
        this.hooks.onError?.(index,error);this.notify();
      }
    })();
  }
  retry(time) {return this.requestTime(time,{seek:true,retry:true});}
  destroy() {this.destroyed=true;this.cancelExcept(new Set());this.cache.clear();this.failures.clear();this.retainedBytes=0;}
}
if(typeof module!=='undefined' && module.exports)module.exports=SimZ1ContinuousLoader;
