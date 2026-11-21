// Visual annotations only. No event mutation, native lifetime extension, timers,
// queue membership or dependence on simulation speed. One manager per viewer.
class SimZ1ArrivalEffects {
  static durationMs=5000;
  static candidate(record,{family='unknown',color=[160,160,180],width=1.8,horizon=86400}={}) {
    const trip=record.Trip || {},tripId=trip.Trip_ID ?? record.Replay_Journey_Key;
    const row={vehicle_id:record.vehicle,person_id:record.Agent_ID ?? trip.Person_ID ?? null,
      trip_id:tripId ?? null,arrival:trip.Arrival,link_id:trip.OD?.destination_link ?? null,
      position:Array.isArray(trip.Destination_Position) ? trip.Destination_Position.slice() : null,position_source:'Trip.Destination_Position',
      color:color.slice(0,3),radius_m:Math.max(.25,width/2),
      observed_through:record.timestamps?.[1] ?? -Infinity,family,
      scope:trip.OD?.scope ?? 'native_model_arrival; exterior_scope_not_recorded'};
    row.local_key=JSON.stringify([row.vehicle_id,row.trip_id]);
    if(row.vehicle_id==null || row.trip_id==null)row.reason='identity_unknown';
    else if(trip.Abort!=null || trip.Status==='aborted')row.reason='aborted';
    else if(trip.Status!=='completed' || !Number.isFinite(trip.Arrival))row.reason='arrival_not_confirmed';
    else if(!Number.isFinite(trip.Departure) || trip.Arrival<trip.Departure)row.reason='invalid_trip_interval';
    else if(trip.Arrival>horizon || trip.Departure>=horizon)row.reason='outside_replay_horizon';
    else if(trip.OD?.od_type?.endsWith('-external') || trip.OD?.destination_zone?.startsWith('synthetic-exterior-exit:'))
      row.reason='domain_exit_not_destination_arrival';
    // The source currently records person-leg arrivals, not service completion.
    // A native transit stop or passenger arrival cannot terminate its bus.
    else if(['bus','articulated_bus','passenger'].includes(family) &&
      !(trip.Transit?.schema==='simz1-transit-replay-v1' && trip.Transit?.vehicle_id===record.vehicle &&
        trip.Transit?.service_end_confirmed===true && trip.Transit?.terminal_status==='service_finished' &&
        trip.Transit?.completion_source==='native_driver_arrival_after_traffic_exit'))row.reason='service_completion_not_recorded';
    else if(!Array.isArray(row.position) || row.position.length<2 ||
      !row.position.every(Number.isFinite) || Math.abs(row.position[0])>180 || Math.abs(row.position[1])>90)
      row.reason='final_position_unknown';
    else row.reason='confirmed_native_arrival';
    return row;
  }
  constructor({identity,now=()=>performance.now(),reducedMotion=false}={}) {
    this.now=now;this.reducedMotion=reducedMotion;this.setIdentity(identity);
  }
  setIdentity(identity={}) {
    const key=JSON.stringify([identity.run_id,identity.iteration,identity.run_manifest_sha256]);
    if(this.identityKey===key)return false;
    this.identityKey=key;this.identity={run_id:identity.run_id,iteration:identity.iteration,
      run_manifest_sha256:identity.run_manifest_sha256};this.reset(null,'run_change');return true;
  }
  reset(time,reason='seek') {
    this.time=time;this.pending=new Map();this.heap=[];this.active=new Map();
    this.lastReset=reason;this.triggered=0;this.windowReasons={};this.windowExamples=[];
  }
  key(row) {return JSON.stringify([this.identityKey,row.vehicle_id,row.trip_id]);}
  // Compact candidates are prepared once per window, never by scanning the
  // fleet each frame. Heap entries exist once per identity, including overlaps.
  ingest(rows) {
    this.windowReasons={};this.windowExamples=[];
    for(const row of rows) {
      this.windowReasons[row.reason]=(this.windowReasons[row.reason] || 0)+1;
      if(row.reason!=='confirmed_native_arrival') {
        const old=this.pending.get(this.key(row));if(old)old.conflict=true;
        if(this.windowExamples.length<20)this.windowExamples.push(row);
        continue;
      }
      if(this.time!=null && row.arrival<=this.time)continue;
      const key=this.key(row),old=this.pending.get(key);
      if(old) {
        if(old.arrival!==row.arrival)old.conflict=true;
        else if(row.observed_through>old.observed_through)this.pending.set(key,{...row,key,conflict:old.conflict});
      } else {
        this.pending.set(key,{...row,key});this.push({key,arrival:row.arrival});
      }
    }
  }
  push(item) {
    const heap=this.heap;let i=heap.length;heap.push(item);
    while(i>0) {const parent=(i-1)>>>1;if(heap[parent].arrival<=item.arrival)break;
      heap[i]=heap[parent];i=parent;}heap[i]=item;
  }
  pop() {
    const heap=this.heap,first=heap[0],last=heap.pop();
    if(heap.length) {let i=0;
      while(i*2+1<heap.length) {let child=i*2+1;
        if(child+1<heap.length && heap[child+1].arrival<heap[child].arrival)child++;
        if(heap[child].arrival>=last.arrival)break;heap[i]=heap[child];i=child;}
      heap[i]=last;}
    return first;
  }
  advance(time) {
    if(!Number.isFinite(time))return;
    if(this.time==null){this.time=time;return;}
    if(time<this.time){this.reset(time,'reverse_seek');return;}
    const previous=this.time,now=this.now();this.time=time;
    while(this.heap.length && this.heap[0].arrival<=time) {
      const {key}=this.pop(),row=this.pending.get(key);this.pending.delete(key);
      if(!row || row.arrival<=previous || row.conflict || this.active.has(key))continue;
      this.active.set(key,{...row,started_ms:now,expires_ms:now+SimZ1ArrivalEffects.durationMs});this.triggered++;
    }
  }
  frame() {
    const now=this.now(),rows=[];
    for(const [key,row] of this.active) {
      const elapsed=Math.max(0,now-row.started_ms);
      if(elapsed>=SimZ1ArrivalEffects.durationMs){this.active.delete(key);continue;}
      // Two slow 2.5 s cycles with continuous derivatives; no flash or square
      // wave. Reduced motion keeps a fixed tint and only fades its last second.
      const white=this.reducedMotion ? .45 : (1-Math.cos(elapsed*2*Math.PI/2500))/2;
      // Keep the normal pulse visible until the exact deadline. Rounding a
      // last-second fade used to make it fully transparent before 5000 ms.
      const alpha=this.reducedMotion ? Math.max(1,Math.round(220*Math.min(1,
        (SimZ1ArrivalEffects.durationMs-elapsed)/1000))) : 220;
      rows.push({...row,color:[...row.color.map(c=>Math.round(c+(255-c)*white)),alpha],
        annotation:true,remaining_ms:SimZ1ArrivalEffects.durationMs-elapsed});
    }
    return rows;
  }
  needsFrame() {return this.active.size>0;}
  expiryDue() {return (this.active.values().next().value?.expires_ms ?? Infinity)<=this.now();}
  snapshot() {
    return {...this.identity,duration_ms:SimZ1ArrivalEffects.durationMs,clock:'performance.now',
      style:this.reducedMotion ? 'steady_tint_and_fade' : 'soft_pulse',last_reset:this.lastReset,
      simulated_time:this.time,triggered:this.triggered,active:this.frame(),pending_count:this.pending.size,
      upcoming:[...this.pending.values()].sort((a,b)=>a.arrival-b.arrival).slice(0,20),
      window_reasons:{...this.windowReasons},excluded_examples:this.windowExamples.slice()};
  }
  static layer(deck) {
    return new deck.ScatterplotLayer({id:'arrival-annotations',data:[],pickable:false,
      getPosition:row=>row.position,getRadius:row=>row.radius_m,getFillColor:row=>row.color,
      radiusUnits:'meters',radiusMinPixels:3,radiusMaxPixels:10,
      stroked:true,getLineColor:row=>[255,255,255,row.color[3]],getLineWidth:1,lineWidthUnits:'pixels',
      parameters:{depthCompare:'always',depthWriteEnabled:false}});
  }
}
