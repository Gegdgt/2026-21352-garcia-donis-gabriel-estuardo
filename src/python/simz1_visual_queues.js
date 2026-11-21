/* Absolute-time display spacing only. No native event, speed or motion phase is changed. */
class SimZ1VisualQueues {
  constructor(lanes,settings={},visualPolicy=null) {
    if(visualPolicy!==null && visualPolicy!=='partial-native-v1')throw new Error('Politica visual de colas incompatible');
    this.lanes=lanes;this.visualPolicy=visualPolicy;this.configure(settings);
  }
  configure(settings={}) {
    // Only representation margins here. Bodies come from the shared catalog.
    // gap is TOTAL longitudinal inflation; lateral clearance is per side.
    const defaults={gap_m:2,lateral_clearance_m:.1,stop_line_setback_m:2};
    if(Object.keys(settings).some(key=>!Object.hasOwn(defaults,key)))throw new Error('Ajuste de margen visual desconocido');
    const next={...defaults,...this.settings,...settings};
    for(const key of Object.keys(defaults))if(!Number.isFinite(next[key]) || next[key]<0)throw new Error('Ajuste visual de cola invalido: '+key);
    if(next.gap_m<.1 || next.gap_m>10)throw new Error('Separacion visual fuera del rango 0.10..10 m');
    if(next.lateral_clearance_m>1)throw new Error('Margen lateral fuera del rango 0..1 m');
    this.settings=next;this.boxes=new WeakMap();this.anchorCache=null;this.finalMarkers=new WeakMap();
    this.profile=null;this.releaseCache=null;
  }
  bodiesOverlap(a,b,gap=0) {
    return this.overlap(a,b,gap,0);
  }
  box(body) {
    let box=this.boxes.get(body);
    if(!box || box.px!==body.position[0] || box.py!==body.position[1] || box.heading!==body.heading ||
      box.half!==body.length_m/2 || box.side!==body.width_m/2 || box.projection!==this.lanes.projection) {
      const radians=body.heading*Math.PI/180,c=Math.cos(radians),s=Math.sin(radians),p=this.lanes.projection;
      box={c,s,ac:Math.abs(c),as:Math.abs(s),half:body.length_m/2,side:body.width_m/2,
        px:body.position[0],py:body.position[1],heading:body.heading,projection:p,
        x:(body.position[0]-p.origin[0])*p.xScale,y:(body.position[1]-p.origin[1])*p.yScale};
      this.boxes.set(body,box);
    }
    return box;
  }
  overlap(a,b,gap,lateral) {
    if(!a || !b)return false;
    if(this.profile)this.profile.overlapCalls++;
    const aa=this.box(a),bb=this.box(b),scale=this.lanes.projection;
    const dx=(b.position[0]-a.position[0])*scale.xScale,dy=(b.position[1]-a.position[1])*scale.yScale;
    const ah=aa.half+gap/2,aw=aa.side+lateral,bh=bb.half+gap/2,bw=bb.side+lateral;
    if(Math.abs(dx)>=aa.ac*ah+aa.as*aw+bb.ac*bh+bb.as*bw ||
       Math.abs(dy)>=aa.as*ah+aa.ac*aw+bb.as*bh+bb.ac*bw)return false;
    if(this.profile)this.profile.satTests++;
    const c=Math.abs(aa.c*bb.c+aa.s*bb.s),s=Math.abs(aa.c*bb.s-aa.s*bb.c),epsilon=1e-7;
    return Math.abs(dx*aa.c+dy*aa.s)<ah+bh*c+bw*s-epsilon &&
      Math.abs(-dx*aa.s+dy*aa.c)<aw+bh*s+bw*c-epsilon &&
      Math.abs(dx*bb.c+dy*bb.s)<bh+ah*c+aw*s-epsilon &&
      Math.abs(-dx*bb.s+dy*bb.c)<bw+ah*s+aw*c-epsilon;
  }
  envelope(body) {
    return {...body,length_m:body.length_m+this.settings.gap_m,
      width_m:body.width_m+2*this.settings.lateral_clearance_m};
  }
  envelopesOverlap(a,b) { return this.overlap(a,b,this.settings.gap_m,this.settings.lateral_clearance_m); }
  stopClearance(body,boundary) {
    if(!body || !boundary?.available)return null;
    const p=this.lanes.projection,[ux,uy]=boundary.forward,angle=body.heading*Math.PI/180;
    const centre=(body.position[0]-boundary.position[0])*p.xScale*ux+
      (body.position[1]-boundary.position[1])*p.yScale*uy;
    const front=body.length_m/2*Math.abs(Math.cos(angle)*ux+Math.sin(angle)*uy)+
      body.width_m/2*Math.abs(-Math.sin(angle)*ux+Math.cos(angle)*uy);
    return -centre-front;
  }
  key(marker) { return JSON.stringify([marker.vehicle,marker.Replay_Journey_Key ?? '',marker.Link_ID,marker.timestamps]); }
  static canonical(value) {
    if(typeof value==='number' && !Number.isFinite(value))throw new Error('Valor no finito en certificado visual');
    if(value===undefined)return null;
    if(value===null || typeof value!=='object')return value;
    if(Array.isArray(value))return value.map(item=>this.canonical(item));
    return Object.fromEntries(Object.keys(value).sort().map(key=>[key,this.canonical(value[key])]));
  }
  static checkpointInput(marker) {
    // These are the immutable source fields read by motion, queue and body
    // reconstruction. Native progress remains available for diagnostics; it is
    // not read by this display-position kernel and is never rewritten here.
    const fields=['vehicle','Agent_ID','Replay_Journey_Key','Link_ID','timestamps','path','Boundary_Provenance',
      'Motion_Plan','Observed_Waits','Native_Occupancy','Vehicle_Type','Vehicle_Dimensions','Vehicle_Physical_Dimensions',
      'Vehicle_Family','Vehicle_PCU','Agent_Type','Profile','Driving_Profile','Vehicle_Articulated',
      'Trip','Movement_End','Motion_Speed_kmh','Speed_kmh','Motion_Provenance'];
    return JSON.stringify(this.canonical(Object.fromEntries(fields.map(key=>[key,marker[key]]))));
  }
  checkpoint(marker) {
    const value=marker.Visual_Queue_Context?.checkpoint;if(value==null)return null;
    if(value.schema!=='native-queue-phase-capsule-v1' || value.complete!==true ||
       value.input!==SimZ1VisualQueues.checkpointInput(marker) ||
       JSON.stringify(SimZ1VisualQueues.canonical(value.settings))!==JSON.stringify(SimZ1VisualQueues.canonical(this.settings)))
      throw new Error('Checkpoint visual incompatible con fuente o margenes');
    for(const phase of ['base','final'])if(value[phase] && !Number.isFinite(value[phase].anchor_m))
      throw new Error('Ancla de checkpoint no finita');
    if(value.final && !Array.isArray(value.final.turn_bounds))throw new Error('Restricciones de giro de checkpoint ausentes');
    if(value.fifo!=null && !Array.isArray(value.fifo))throw new Error('Epocas FIFO de checkpoint invalidas');
    if(value.interpolate!=null && !Array.isArray(value.interpolate))throw new Error('Epocas de interpolacion de checkpoint invalidas');
    if((value.base || value.final || value.fifo?.length || value.interpolate?.length) && typeof value.prepared!=='string')
      throw new Error('Firma de preparacion de checkpoint ausente');
    SimZ1VisualQueues.canonical(value);return value;
  }
  preparedCheckpoint(entry) {
    return JSON.stringify(SimZ1VisualQueues.canonical({key:entry.key,order:entry.orderTime,eligible:entry.eligible,
      hold:entry.hold,start:entry.start,end:entry.end,lower:entry.lower,head:entry.head,
      desired_start:entry.desiredStart,desired_end:entry.desiredEnd,dimensions:entry.dimensions,
      occupancy:entry.occupancy?{corridor:entry.occupancy.corridor.id,slot:entry.occupancy.slot,
        reservation_slot:entry.occupancy.reservationSlot,ordinal:entry.occupancy.ordinal,offset:entry.occupancy.offset}:null,
      stop_boundary:entry.stopBoundary,previous:entry.adjacent?.previous?this.key(entry.adjacent.previous):null,
      next:entry.adjacent?.next?this.key(entry.adjacent.next):null}));
  }
  fractionAt(marker,time) {
    const plan=marker.Motion_Plan,phases=plan?.phases;
    if(!Array.isArray(phases) || !(plan.distance_m>=0))return null;
    const p=phases.find(p=>Array.isArray(p) && p[0]<=time && time<=p[1] && p.slice(0,5).every(Number.isFinite));
    if(!p)return null;
    if(plan.distance_m===0)return plan.status==='stationary' && p.slice(2,5).every(v=>v===0) ? 0 : null;
    const dt=time-p[0];return Math.max(0,Math.min(1,(p[2]+p[3]*dt+p[4]*dt*dt/2)/plan.distance_m));
  }
  blockingFacilityBoundary(marker,side) {
    const arrival=side==='end',boundary=marker.Boundary_Provenance;
    if(boundary?.[side] !== (arrival ? 'VehicleArrivesAtFacility' : 'VehicleDepartsAtFacility'))return null;
    const index=arrival ? 1 : 0,time=marker.timestamps?.[index],fraction=boundary[side+'_relative'];
    const stop=marker.Trip?.Transit?.activity_intervals?.find(row=>row.is_blocking_lane===true &&
      (arrival ? row.start : row.end)===time && row.relative_position===fraction);
    return this.lanes.nativeFacilityEndpoint(marker,stop,marker.path?.[index]);
  }
  evidence(marker,time) {
    const facility=this.lanes.nativeFacilityPose(marker);
    if(facility?.blocking_queue && (this.lanes.occupancy(marker) || this.lanes.describe(marker.Link_ID)?.lane_count===1)) {
      const [start,end]=marker.timestamps;
      return {eligible:true,unknown:false,start,end,hold:start};
    }
    // A bus can finish passenger service while still waiting in the same
    // queue. The zero-distance native interval preserves that endpoint even
    // before its first QNode WAIT (or when it leaves at the next time step).
    // Keep its body reserved across the facility departure boundary.
    const departure=this.blockingFacilityBoundary(marker,'start');
    const nativeDeparture=marker.Boundary_Provenance?.start==='VehicleDepartsAtFacility' && this.lanes.occupancy(marker);
    if((departure || nativeDeparture) && marker.Motion_Plan?.status==='stationary' && marker.Motion_Plan.distance_m===0 &&
       marker.Boundary_Provenance.start_relative===marker.Boundary_Provenance.end_relative &&
       (this.lanes.occupancy(marker) || this.lanes.describe(marker.Link_ID)?.lane_count===1)) {
      const [start,end]=marker.timestamps;
      return {eligible:true,unknown:false,start,end,hold:start};
    }
    const waits=marker.Observed_Waits || {},endpoint=[],unlocated=[];let unknown=false;
    for(const [reason,wait] of Object.entries(waits)) {
      if(!wait || typeof wait!=='object' || !Number.isFinite(wait.first))continue;
      const sources=Array.isArray(wait.sources) ? wait.sources : [wait.sources];
      const unknownHere=wait.position_evidence==='unknown_queue_position' || sources.includes('MATSim15_queue_post_step') ||
        reason==='congestion_queue' || reason==='signal_queue_not_green';
      unknown ||= unknownHere && wait.first<=time;
      if(unknownHere)unlocated.push(wait.first);
      if(!unknownHere && (wait.position_evidence==='queue_exit' || sources.includes('MATSim15_QNode_native_branch') ||
         sources.includes('SimZ1_QNode_strict_receiver_v1') || reason.startsWith('priority_') ||
         ['storage_wait','intersection_conflict','signal_red','signal_redyellow','signal_not_green','admission_conflict_executed'].includes(reason)))endpoint.push(wait.first);
    }
    const plan=marker.Motion_Plan,[start,end]=marker.timestamps || [];
    const hold=plan?.hold_start ?? plan?.native_wait_boundary;
    const stopped=Array.isArray(plan?.phases) && plan.phases.some(p=>Array.isArray(p) && p.length>=5 && p.slice(0,5).every(Number.isFinite) &&
      p[0]<=hold+1e-7 && p[1]>=end-1e-7 && Math.abs(p[3])<1e-8 && Math.abs(p[4])<1e-8 &&
      Number.isFinite(plan.distance_m) && Math.abs(p[2]-plan.distance_m)<1e-5);
    // A post-step WAIT does not locate a queue. It can support display spacing
    // only together with an existing Motion_Plan hold at this link's endpoint.
    const eligible=[start,end,hold].every(Number.isFinite) && start<=hold && hold<end &&
      start<=time && time<end && stopped && [...endpoint,...unlocated].some(first=>first>=start && first<=hold+1e-7);
    return {eligible:Boolean(eligible),unknown,start,end,hold};
  }
  contextAnchorAbsence(marker,neighbors,facilitySupport) {
    // This is the exact shared-upstream exclusion used by frame below. The
    // complete, identity-checked schedule descriptor is supplied by the kernel
    // bridge; it proves that no active blocking service can enable the
    // single-lane exception. No native ordinal or lateral slot is invented.
    if(!facilitySupport || facilitySupport.schema!=='native-blocking-facility-support-v1' ||
       !Array.isArray(facilitySupport.blocking_links) || facilitySupport.blocking_links.includes(marker?.Link_ID) ||
       !marker || this.lanes.occupancy(marker) || marker.Visual_Native_Queue_Kind!=='shared_upstream' ||
       marker.Motion_Plan?.status==='unavailable' || this.fraction(marker)==null)return null;
    const dimensions=SimZ1VehicleCatalog.resolve(marker).dimensions;
    if(!dimensions || !this.lanes.vehicleBody(marker,neighbors,dimensions.length_m,dimensions.width_m))return null;
    return {reason:'shared_upstream_without_blocking_facility',link_id:marker.Link_ID};
  }
  headWaitClaim(marker,time) {
    const e=this.evidence(marker,time),d=marker.Visual_Native_Queue_Extent;
    if(!e.eligible || !d?.available || d.kind!=='terminal' || marker.Visual_Lane_Source!=='native' ||
       d.lane_id!==marker.Observed_Queue_ID || d.event_time!==marker.Observed_Queue_Entry || d.event_time>e.hold)return null;
    for(const [reason,wait] of Object.entries(marker.Observed_Waits || {})) {
      const sources=Array.isArray(wait?.sources) ? wait.sources : [wait?.sources];
      const source=sources.find(s=>['MATSim15_QNode_native_branch','SimZ1_QNode_strict_receiver_v1'].includes(s));
      if(source && !sources.includes('MATSim15_queue_post_step') && wait.position_evidence==='queue_exit' &&
         !['congestion_queue','signal_queue_not_green'].includes(reason) && Number.isFinite(wait.first) &&
         wait.first>=d.event_time && Math.abs(wait.first-e.hold)<1e-7)
        return {key:JSON.stringify([marker.Link_ID,d.lane_id]),vehicle_id:marker.vehicle,record_key:this.key(marker),
          source,reason,lane_id:d.lane_id,lane_entry:d.event_time,hold:e.hold,end:e.end};
    }
    return null;
  }
  independentHeadPose(entry,claim,time,neighbors) {
    const unavailable=reason=>({projection:{available:false,reason,head_wait:claim}});
    if(!claim || claim.ambiguous)return unavailable(claim ? 'ambiguous_qnode_heads' : 'qnode_head_not_proven');
    const d=entry.marker.Visual_Native_Queue_Extent,boundary=entry.stopBoundary,g=this.lanes.links.get(entry.marker.Link_ID).geometry;
    const half=entry.dimensions.length_m/2,radius=Math.hypot(half,entry.dimensions.width_m/2);
    const lower=d.geometry_from_m+half;
    if(!boundary?.available || d.geometry_to_m-d.geometry_from_m<entry.dimensions.length_m)return unavailable('head_body_exceeds_native_domain');
    const entered=this.fractionAt(entry.marker,claim.lane_entry),held=this.fractionAt(entry.marker,claim.hold);
    if(entered==null || held==null || held<entered || claim.hold<=claim.lane_entry)return unavailable('head_approach_time_unavailable');
    const start=Math.max(d.geometry_from_m,Math.min(d.geometry_to_m,entered*entry.link.length_m));
    const terminalStart=g.distances.at(-2);
    // Without the predecessor closure, support only a single directed terminal
    // edge. Its monotone centre path plus a circumscribed radius bounds every
    // orientation of the full body throughout the approach, not just at WAIT.
    if(start<terminalStart-1e-7 || boundary.station_m<terminalStart)return unavailable('head_approach_geometry_unproven');
    let anchor=Math.min(boundary.station_m-radius,d.geometry_to_m-half),anchorPose=null;
    for(;anchor>=Math.max(lower,terminalStart)-1e-7;anchor-=.25) {
      const candidate=this.pose(entry,anchor,true,neighbors,true);
      if(!candidate)continue;
      const [ux,uy]=boundary.forward,p=this.lanes.projection;
      const distance=(boundary.position[0]-candidate.body.position[0])*p.xScale*ux+
        (boundary.position[1]-candidate.body.position[1])*p.yScale*uy;
      if(distance>=radius-1e-7){anchorPose=candidate;break;}
    }
    if(!anchorPose)return unavailable('head_body_exceeds_stop_storage');
    if(start>anchor+1e-7)return unavailable('entry_pose_beyond_supported_stop_anchor');
    if(held-entered<1e-9 && anchor-start>1e-7)return unavailable('head_approach_motion_unavailable');
    const relevant=(entry.marker.Motion_Plan?.phases || []).filter(p=>p[0]<claim.hold && p[1]>claim.lane_entry);
    if(!relevant.length || relevant.some(p=>p.slice(0,5).some(v=>!Number.isFinite(v)) ||
       p[3]+p[4]*Math.max(0,claim.lane_entry-p[0])<-1e-7 || p[3]+p[4]*(Math.min(p[1],claim.hold)-p[0])<-1e-7))
      return unavailable('head_approach_reverses_source_motion');
    const progress=time>=claim.hold ? 1 : Math.max(0,Math.min(1,(entry.fraction-entered)/(held-entered || 1)));
    const station=start+(anchor-start)*progress,pose=this.pose(entry,station,true,neighbors,time>=claim.hold);
    if(!pose)return unavailable('head_body_pose_unavailable');
    return {body:pose.body,projection:{available:true,applied:Math.abs(station-(entry.marker.Visual_Native_Queue_Station_Meters ??
      entry.fraction*entry.link.length_m))>1e-7,source:'estimated_qnode_head_stop_boundary',head_wait:claim,
      entry_station_m:start,anchor_station_m:anchor,station_m:station,continuous_position_observed:false,
      original_to_terminal_continuity:'unknown_without_observed_lateral_history',
      preparation:'absolute_motion_progress_within_current_terminal_interval'}};
  }
  retainedPoseSource(marker) {
    return marker.Visual_Native_Event_Position ? 'native_link_entry_center_estimated_orientation' :
      marker.Visual_Native_Facility_Position ? 'native_facility_center_estimated_orientation' :
      marker.Visual_Recorded_Boundary_Path ? 'recorded_boundary_path_estimated_orientation' :
      marker.Visual_Queue_Head_Projection?.available ? 'estimated_qnode_head_stop_boundary' :
      marker.Visual_Queue_Extent_Projection?.applied ? 'estimated_queue_extent_projection' : 'recorded_interval_motion';
  }
  fraction(marker) {
    const fraction=marker.Visual_Motion_Fraction ?? (marker.Motion_Plan?.distance_m>0 ?
      marker.Visual_Distance_m/marker.Motion_Plan.distance_m : null);
    return Number.isFinite(fraction) ? Math.max(0,Math.min(1,fraction)) : null;
  }
  withBody(marker,body,presentation=marker.Visual_Vehicle_Presentation ?? SimZ1VehicleCatalog.resolve(marker)) {
    const dimensions=presentation.dimensions;
    return {...marker,position:body?.position ?? marker.position,Visual_Body_Path:body?.path || [],
      Visual_Vehicle_Presentation:presentation,
      Visual_Safety_Envelope:dimensions ? {length_m:dimensions.length_m+this.settings.gap_m,
        width_m:dimensions.width_m+2*this.settings.lateral_clearance_m,
        gap_m:this.settings.gap_m,lateral_clearance_m:this.settings.lateral_clearance_m} : null,
      Visual_Body_Heading_Degrees:body?.heading ?? null,Visual_Body_Support:body?.support ?? null,
      Visual_Body_Reconstruction:body?.reconstruction ?? null,
      Visual_Body_Width_Meters:body?.width_m ?? 0,
      Visual_Body_Length_Meters:body?.length_m ?? 0,Visual_Body_Nominal_Length_Meters:dimensions?.length_m ?? null,
      Visual_Body_Clipped:body?.clipped ?? true,Visual_Body_Opacity:body?.opacity ?? 0,
      Visual_Body_Representable:Boolean(body && body.width_m>0 && body.length_m>0 && body.opacity>0),
      Visual_Queue_Stop_Clearance_Meters:this.stopClearance(body,marker.Visual_Queue_Stop_Boundary)};
  }
  describePose(marker) {
    if(!marker)return {};
    if(marker.Visual_Queue_State==='reconstruction_pending')return {
      queue_state:'reconstruction_pending',body_support:null,body_reconstruction:null,turn_clearance:null,
      lane_source:null,observed_lane_id:marker.Observed_Queue_ID ?? null,
      observed_lane_entry_time:marker.Observed_Queue_Entry ?? null,longitudinal_station_m:null,
      display_link:null,display_station_m:null,native_occupancy:marker.Native_Occupancy ?? null,
      native_occupancy_progress:marker.Native_Occupancy_Progress ?? [],
      native_position_source:'unavailable_visual_reconstruction',body_geometry_source:'unavailable_visual_reconstruction'};
    const presentation=marker.Visual_Vehicle_Presentation;
    const link=this.lanes?.describe(marker.Link_ID),fraction=marker.Visual_Motion_Fraction;
    const station=marker.Visual_Queue_Center_Meters ?? marker.Visual_Native_Queue_Station_Meters ??
      (link && Number.isFinite(fraction) ? fraction*link.length_m : null);
    return {queue_state:marker.Visual_Queue_State ?? null,body_support:marker.Visual_Body_Support ?? null,
      body_reconstruction:marker.Visual_Body_Reconstruction ?? null,
      turn_clearance:marker.Visual_Queue_Turn_Clearance ?? null,
      lane_source:marker.Visual_Lane_Source ?? null,observed_lane_id:marker.Observed_Queue_ID ?? null,
      observed_lane_entry_time:marker.Observed_Queue_Entry ?? null,longitudinal_station_m:station,
      display_link:marker.Visual_Queue_Display_Link_ID ?? marker.Link_ID,
      display_station_m:marker.Visual_Queue_Display_Station_Meters ?? station,
      stop_margin_m:marker.Visual_Queue_Stop_Margin_Meters ?? null,
      stop_boundary:marker.Visual_Queue_Stop_Boundary ?? null,
      stop_clearance_m:marker.Visual_Queue_Stop_Clearance_Meters ?? null,
      native_queue_extent:marker.Visual_Native_Queue_Extent ?? null,
      queue_extent_projection:marker.Visual_Queue_Extent_Projection ?? null,
      head_stop_projection:marker.Visual_Queue_Head_Projection ?? null,
      facility_footprint_projection:marker.Visual_Facility_Footprint_Projection ?? null,
      facility_boundary_projection:marker.Visual_Facility_Boundary_Projection ?? null,
      native_occupancy:marker.Native_Occupancy ?? null,
      native_occupancy_progress:marker.Native_Occupancy_Progress ?? [],
      occupancy_domain:marker.Visual_Occupancy_Domain ?? null,
      occupancy_reference:marker.Visual_Occupancy_Reference ?? null,
      dimension_contract:{
        physical_dimensions:presentation?.physical?.dimensions ?? null,
        pcu:presentation?.physical?.pcu ?? marker.Vehicle_PCU ?? null,
        visual_body:{length_m:marker.Visual_Body_Length_Meters ?? null,width_m:marker.Visual_Body_Width_Meters ?? null,
          origin:presentation?.dimensions_origin ?? null,source:presentation?.dimensions?.source ?? null,
          assumed:presentation?.dimensions?.assumed ?? null,provenance:presentation?.dimensions?.provenance ?? null},
        safety_envelope:marker.Visual_Safety_Envelope ?? null,
        dimension_diagnostics:presentation?.dimension_diagnostics ?? [],
        continuous_physical_spacing_observed:false},
      native_position_source:'estimated_link_interpolation_from_recorded_interval',
      body_geometry_source:'rigid_presentation_envelope_on_inferred_pose'};
  }
  // Only an observed, unambiguous subdivision can supply an upstream slot.
  upstream(entry,neighbors) {
    const marker=entry.marker,previous=neighbors(marker)?.previous;
    const a=this.lanes.links.get(previous?.Link_ID),b=this.lanes.links.get(marker.Link_ID);
    if(!previous || previous.Motion_Plan?.status==='unavailable' || !this.lanes.observedConnection(previous,marker) ||
      !this.lanes.sameSection(a,b) || a.assignmentKey!==b.assignmentKey ||
      !this.lanes.connects(a,b) || previous.Visual_Lane_Index!==marker.Visual_Lane_Index ||
      b.lanes>1 && (previous.Visual_Lane_Source!=='native' || marker.Visual_Lane_Source!=='native') ||
      this.lanes.intersectionSetback(previous.Link_ID,previous.Visual_Lane_Index)>1e-7 ||
      entry.storage.length_m<entry.link.length_m-1e-7)return null;
    const end=this.lanes.place(a.id,a.geometry.length,previous.Visual_Lane_Index)?.position;
    const start=this.lanes.place(b.id,0,marker.Visual_Lane_Index)?.position;
    if(!end || !start || Math.hypot((end[0]-start[0])*this.lanes.projection.xScale,
      (end[1]-start[1])*this.lanes.projection.yScale)>.25)return null;
    const storage=this.lanes.storage(a.id,previous.Visual_Lane_Index,
      previous.Visual_Lane_Source==='native' ? previous.Observed_Queue_ID : null);
    return {marker:previous,length:a.geometry.length,extent:storage.length_m};
  }
  pose(entry,center,adjusted,neighbors,holding=true) {
    if(this.profile)this.profile.poseRequests++;
    if(entry.occupancy && entry.checkpoint) {
      const states=[entry.checkpoint.base,entry.checkpoint.final,...(entry.checkpoint.fifo||[]).map(row=>row.result),
        ...(entry.checkpoint.interpolate||[]).map(row=>row.result)];
      const saved=states.find(row=>row && (row.anchor_m??row.center_m)===center && Object.hasOwn(row,'pose'));
      if(saved) {
        if(saved.pose===null)return null;
        const body=saved.pose?.body;
        if(!body || body.length_m!==entry.dimensions.length_m || body.width_m!==entry.dimensions.width_m ||
           !Array.isArray(body.position) || body.position.length!==2 || !body.position.every(Number.isFinite) ||
           !Number.isFinite(body.heading) || saved.pose.center!==center)throw new Error('Geometria de checkpoint incompatible');
        return saved.pose;
      }
    }
    if(entry.occupancy) {
      const result=this.lanes.occupancyBody(entry.occupancy,center,entry.dimensions.length_m,entry.dimensions.width_m,
        {...neighbors(entry.marker),current:entry.marker,resolve:neighbors});
      if(result?.body)result.body.support=result.reference;
      if(result && entry.eligible && this.stopClearance(result.body,entry.stopBoundary)<-1e-7)return null;
      return result;
    }
    const observedDomain=entry.marker.Visual_Native_Queue_Extent;
    // A still-observed queue belongs to this link. An earlier interval is not
    // permission to put its centre upstream of that serial domain.
    if(observedDomain?.available && (center<observedDomain.geometry_from_m-1e-7 ||
       center>observedDomain.geometry_to_m+1e-7))return null;
    if(entry.cachedPose?.center===center && entry.cachedPose.adjusted===adjusted && entry.cachedPose.holding===holding) {
      if(this.profile)this.profile.poseCacheHits++;
      return entry.cachedPose.result;
    }
    let record=entry.marker,station=center,displayLink=record.Link_ID;
    if(center<0 && entry.upstream) {
      record={...entry.upstream.marker,vehicle:entry.marker.vehicle};
      station=entry.upstream.length+center;displayLink=record.Link_ID;
    }
    const placement=this.lanes.place(displayLink,station,record.Visual_Lane_Index);
    const domain=record.Visual_Native_Queue_Extent;
    if(domain?.available && (station<domain.geometry_from_m-1e-7 || station>domain.geometry_to_m+1e-7))return null;
    if(!placement)return null;
    const rendered={...record,position:placement.position};
    if(adjusted) {
      rendered.Visual_Queue_Center_Meters=station;
      rendered.Visual_Queue_Holding=holding;
    }
    const body=this.lanes.vehicleBody(rendered,adjusted && holding ? {} : neighbors(entry.marker),
      entry.dimensions.length_m,entry.dimensions.width_m);
    // Test the full oriented body, not just its centre or half-length along
    // the path. This also catches corners protruding across a curved approach.
    if(entry.eligible && adjusted && this.stopClearance(body,entry.stopBoundary)<-1e-7)return null;
    const result=body ? {body,center,station,displayLink} : null;
    entry.cachedPose={center,adjusted,holding,result};return result;
  }
  // Broad phase in the same metric plane as SAT. No camera/zoom-dependent bins.
  spatialIndex() {
    const cells=new Map(),scratch=new Set(),size=16;
    const visit=(body,accept)=>{
      const b=this.box(body),half=b.half+this.settings.gap_m/2,side=b.side+this.settings.lateral_clearance_m;
      const rx=b.ac*half+b.as*side,ry=b.as*half+b.ac*side;
      for(let i=Math.floor((b.x-rx)/size);i<=Math.floor((b.x+rx)/size);i++)
        for(let j=Math.floor((b.y-ry)/size);j<=Math.floor((b.y+ry)/size);j++)accept(i+','+j);
    };
    return {add:row=>visit(row.body,key=>{if(!cells.has(key))cells.set(key,[]);cells.get(key).push(row);}),
      query:body=>{scratch.clear();visit(body,key=>{const rows=cells.get(key);if(rows)for(const row of rows)scratch.add(row);});
        if(this.profile){this.profile.spatialQueries++;this.profile.broadCandidates+=scratch.size;}return scratch;}};
  }
  frame(markers,time,neighbors=()=>({}),context=markers,releaseState=null) {
    const pinnedReleases=new Map();
    for(const marker of [...context,...markers]){const checkpoint=this.checkpoint(marker);
      if(checkpoint?.release)pinnedReleases.set(this.key(marker),checkpoint.release);}
    releaseState=releaseState ?? {anchors:new Map([...(this.releaseCache?.context===context ? this.releaseCache.anchors : []),...pinnedReleases]),depth:0};
    if(!Number.isFinite(time))throw new Error('Tiempo visual de cola invalido');
    const now=()=>typeof performance==='undefined' ? 0 : performance.now();
    let tick=now();const began=tick,profile=this.profile={overlapCalls:0,satTests:0,poseRequests:0,poseCacheHits:0,
      spatialQueries:0,broadCandidates:0,anchorCacheHit:false,finalMarkerReuses:0};
    const phase=name=>{const end=now();profile[name]=end-tick;tick=end;};
    const s=this.settings;
    const separation=(a,b)=>(a.dimensions.length_m+b.dimensions.length_m)/2+s.gap_m;
    const counts={active:markers.length,visible:0,omitted:0,omissionReasons:{},waitingEvidence:0,positioned:0,
      overflow:0,unrepresentable:0,redistributed:0,unknownPositionWait:0,bodyUnrepresentable:0,
      overlapping:0,following:0,overlapsDetected:0,overlapsResolved:0,unresolvedOverlaps:0,queued:0,unsupportedPosition:0,
      incompatiblePosition:0,warningReasons:{}};
    const groups=new Map(),visible=[],omitted=[],retained=[],indicators=new Map(),collisions=[],limitations=[];
    const activeKeys=new Set(markers.map(m=>this.key(m))),entries=new Map();
    const compare=(a,b)=>a.orderTime-b.orderTime || (a.key<b.key ? -1 : a.key>b.key ? 1 : 0);
    const omit=(entry,reason,detail={})=>{
      const marker={...entry.marker,Visual_Queue_Representable:false,Visual_Queue_State:reason,
        Visual_Queue_Reason:reason,Visual_Queue_Opacity:0,Visual_Diagnostic:detail};
      if(reason==='reconstruction_pending')Object.assign(marker,{position:null,Visual_Body_Path:[],
        Visual_Body_Heading_Degrees:null,Visual_Body_Representable:false,Visual_Body_Opacity:0,
        Visual_Native_Center_Position:null,Visual_Body_Support:null,Visual_Body_Reconstruction:null,
        Visual_Queue_Center_Meters:null,Visual_Queue_Display_Station_Meters:null,
        Visual_Queue_Compatible:false,Visual_Queue_Source:'unavailable_visual_reconstruction'});
      omitted.push(marker);counts.omissionReasons[reason]=(counts.omissionReasons[reason] || 0)+1;
      if(entry.eligible)counts[reason==='storage_exceeded' ? 'overflow' : 'unrepresentable']++;
      else counts.bodyUnrepresentable++;
      const key=JSON.stringify([marker.Link_ID,marker.Visual_Lane_Index,reason]);
      if(!indicators.has(key))indicators.set(key,{Link_ID:marker.Link_ID,Visual_Lane_Index:marker.Visual_Lane_Index,
        position:marker.position,count:0,reason,vehicle_ids:[]});
      const row=indicators.get(key);row.count++;row.vehicle_ids.push(marker.vehicle);
    };
    // A failed spacing constraint is not evidence that the native pose vanished.
    // Retain its known rigid body (including an evidenced domain projection);
    // do not call it a valid queue slot or reduce a metric margin to fit a link.
    const retain=(entry,reason,detail={})=>{
      if(!entry.body){omit(entry,reason,detail);return;}
      retained.push({entry,reason,detail});counts.incompatiblePosition++;
      counts.warningReasons[reason]=(counts.warningReasons[reason] || 0)+1;
      if(reason==='storage_exceeded' || reason==='queue_projection_reverses_motion')counts.overflow++;
      else counts.unrepresentable++;
      limitations.push({vehicle_id:entry.marker.vehicle,reason,...detail,
        pose_source:this.retainedPoseSource(entry.marker),
        spacing_compatible:false,physical_incompatibility_confirmed:false});
    };
    // Context contains immutable interval records, including departed predecessors.
    // It reserves a stopped vehicle's slot at hold_start, not at the current FPS.
    const roster=new Map(context.map(m=>[this.key(m),m])),contextOnly=new Set(),incompleteActive=[];
    const blockingSingleLinks=new Set(markers.filter(m=>this.lanes.describe(m.Link_ID)?.lane_count===1 &&
      this.lanes.nativeFacilityPose(m)?.blocking_queue).map(m=>m.Link_ID));
    const headClaims=new Map(),knownHeadClaims=new Map(),headsByLane=new Map();
    const rememberHead=claim=>{
      if(claim)knownHeadClaims.set(JSON.stringify([claim.record_key,claim.key]),claim);
    };
    // A departed head remains contradictory evidence for another claim whose
    // hold interval overlapped it. Evaluate immutable context at its own hold,
    // not at this frame's time; otherwise removing a body could activate a new
    // anchor halfway through a stopped interval. Context without a validated
    // terminal domain cannot create a head claim or erase a supported one.
    for(const marker of context)rememberHead(this.headWaitClaim(marker,
      marker.Motion_Plan?.hold_start ?? marker.Motion_Plan?.native_wait_boundary));
    for(const marker of markers) {
      const claim=this.headWaitClaim(marker,time);if(!claim)continue;
      headClaims.set(claim.record_key,claim);rememberHead(claim);
    }
    for(const claim of knownHeadClaims.values()) {
      if(!headsByLane.has(claim.key))headsByLane.set(claim.key,[]);
      headsByLane.get(claim.key).push(claim);
    }
    for(const claim of headClaims.values())claim.ambiguous=headsByLane.get(claim.key).some(other=>
      other.record_key!==claim.record_key && Math.max(claim.hold,other.hold)<Math.min(claim.end,other.end));
    for(const m of markers) {
      const key=this.key(m);
      const baseOnly=m.Visual_Queue_Context?.phase==='base';
      if((m.Visual_Queue_Context?.complete===false || baseOnly) && roster.get(key)?.Visual_Queue_Context?.complete===true && this.evidence(m,time).eligible) {
        // Another complete seed may require this interval as historical anchor
        // evidence, even if its own per-seed budget fails. Keep that contextual
        // role separate from the active body, which must remain incompatible.
        contextOnly.add(key);incompleteActive.push([key,baseOnly ? {...m,Visual_Queue_Context:{...m.Visual_Queue_Context,
          complete:false,reason:'base_anchor_only_not_final_pose'}} : m,true]);
      } else roster.set(key,baseOnly ? {...m,Visual_Queue_Context:{...m.Visual_Queue_Context,
        complete:false,reason:'base_anchor_only_not_final_pose'}} : m);
    }
    function* rosterRows() {
      for(const [key,raw] of roster)yield [key,raw,activeKeys.has(key) && !contextOnly.has(key)];
      yield* incompleteActive;
    }
    for(const [key,raw,active] of rosterRows()) {
      const anchorPhase=raw.Visual_Queue_Context?.phase ?? 'final';
      if(!['base','final'].includes(anchorPhase))throw new Error('Fase de contexto de cola desconocida');
      if(this.visualPolicy==='partial-native-v1' && raw.Visual_Queue_Context?.reason==='reconstruction_pending') {
        const availability=raw.Visual_Queue_Context;
        if(availability.complete!==false || availability.body_position_available!==false ||
           availability.record_keys?.length || availability.checkpoint!=null || availability.support_certificate!=null)
          throw new Error('Disponibilidad parcial de cola incompatible');
        if(active)omit({marker:raw,eligible:false},'reconstruction_pending',{context:availability,
          note:'Posicion no disponible; reconstruccion pendiente. No se reutiliza una pose anterior.'});
        continue;
      }
      const link=this.lanes?.describe(raw.Link_ID);
      const hold=raw.Motion_Plan?.hold_start ?? raw.Motion_Plan?.native_wait_boundary;
      const evidence=this.evidence(raw,active ? time : hold);
      // A neighbour needed for a rigid rear/transition is not automatically
      // a certificate for its own HOLD. The backend must resolve every future
      // anchor used by offline interpolation; auxiliary rows remain movement
      // evidence only and cannot acquire an invented complete anchor here.
      if(!active && raw.Visual_Queue_Context?.role==='auxiliary_transition')evidence.eligible=false;
      if(!active && !evidence.eligible && !this.lanes.occupancy(raw))continue;
      let fraction=this.fraction(raw);
      let marker={...raw,Visual_Motion_Fraction:fraction},index=raw.Visual_Lane_Index;
      const nativeEntryInstant=active && time===raw.timestamps?.[0] && raw.Motion_Plan?.status==='unavailable' &&
        raw.Visual_Motion_Status==='observed_event_position' && raw.Visual_Motion_Source==='native_entered_link_at_exact_timestamp' &&
        raw.Visual_Speed_kmh===null && fraction===0 && raw.Boundary_Provenance?.start==='entered link' &&
        raw.Boundary_Provenance.start_relative===0 && this.lanes.validPoint(raw.path?.[0]);
      if(nativeEntryInstant)marker={...marker,position:[...raw.path[0]],Visual_Lane_Index:null,Visual_Lane_Source:'centerline',
        Visual_Lane_Offset_Meters:0,Visual_Native_Event_Position:{time,instant_only:true,
          source:'native_entered_link_at_exact_timestamp',orientation_source:'estimated_local_network_tangent',speed_kmh:null}};
      // Recover an unambiguous one-lane axis; never guess a multilane membership.
      if(!nativeEntryInstant && index==null && raw.Visual_Native_Queue_Kind!=='shared_upstream' && link?.eligible && link.lane_count===1 &&
        this.lanes.compatiblePath(this.lanes.links.get(raw.Link_ID),raw.path)) {
        index=0;marker={...marker,...this.lanes.marker(raw,fraction,{},raw.position)};
      }
      if(!this.lanes.validPoint(marker.position) && link?.eligible && Number.isSafeInteger(index) && fraction!=null) {
        const point=this.lanes.place(marker.Link_ID,fraction*link.length_m,index);
        if(point)marker.position=point.position;
      }
      const presentation=marker.Visual_Vehicle_Presentation ?? SimZ1VehicleCatalog.resolve(marker),dimensions=presentation.dimensions;
      const adjacent=nativeEntryInstant ? {} : neighbors(marker),body=dimensions ? this.lanes?.vehicleBody(marker,adjacent,dimensions.length_m,dimensions.width_m) : null;
      const nativeEntry=marker.Visual_Lane_Source==='native' && Number.isFinite(marker.Observed_Queue_Entry) &&
        marker.Observed_Queue_Entry>=evidence.start && marker.Observed_Queue_Entry<=(active ? time : hold) &&
        marker.Observed_Queue_Entry<(evidence.end ?? Infinity);
      const occupancy=this.lanes.occupancy(marker);
      const orderTime=occupancy ? occupancy.ordinal : nativeEntry ? marker.Observed_Queue_Entry : evidence.start;
      const entry={key,raw,adjacent,presentation,dimensions,marker:this.withBody(marker,body,presentation),body,link,fraction,orderTime,nativeEntry,active,head:0,occupancy,anchorPhase,
        checkpoint:this.checkpoint(raw),...evidence};
      if(entry.checkpoint && entry.eligible)for(const needed of anchorPhase==='final'?['base','final']:['base']) {
        const producing=releaseState.external===true && raw.Visual_Queue_Context?.checkpoint_pending?.includes(needed);
        if(!entry.checkpoint[needed] && !producing)throw new Error('Checkpoint no contiene la fase corporal requerida: '+needed);
      }
      if(active) {
        if(evidence.unknown)counts.unknownPositionWait++;
        if(evidence.eligible)counts.waitingEvidence++;
      }
      if(fraction==null || raw.Motion_Plan?.status==='unavailable' && !nativeEntryInstant) {
        if(active)omit(entry,'motion_unavailable',{motion_reason:raw.Motion_Plan?.fallback_reason ?? 'missing_fraction'});continue;
      }
      if(nativeEntryInstant) {
        if(body)retain(entry,'native_link_entry_position',{instant_only:true,time,speed_kmh:null,
          note:'Centro de entrada nativo solo en este timestamp; orientacion local estimada, velocidad y trayectoria interior no disponibles.'});
        else omit(entry,'geometry_or_lane_unavailable',{instant_only:true,time});
        continue;
      }
      if(marker.Visual_Native_Facility_Position && body) {
        const facility=marker.Visual_Native_Facility_Position;
        if(facility.blocking_queue && link?.eligible && (occupancy || link.lane_count===1)) {
          // QSim records a queue service endpoint, not the centre of a rigid
          // body. A blocking single-lane stop can reserve an estimated body
          // upstream of that endpoint; retain the native endpoint separately.
          index=occupancy?.slot ?? 0;fraction=1;entry.fraction=1;
          Object.assign(entry,{eligible:true,hold:raw.timestamps[0],start:raw.timestamps[0],end:raw.timestamps[1]});
          Object.assign(evidence,{eligible:true,hold:raw.timestamps[0],start:raw.timestamps[0],end:raw.timestamps[1]});
          marker={...marker,path:this.lanes.links.get(raw.Link_ID).data.path,Visual_Lane_Index:index,
            Visual_Lane_Source:'estimated_single_lane_blocking_stop',Visual_Motion_Fraction:1,
            Visual_Facility_Footprint_Projection:{source:'estimated_body_behind_native_service_endpoint',
              native_endpoint:facility.position,native_station_m:facility.station_m,continuous_position_observed:false}};
          entry.marker=marker;entry.facilityStation=facility.station_m;
        } else {
        const within=facility.station_m-dimensions.length_m/2>=0 &&
          facility.station_m+dimensions.length_m/2<=link.length_m;
        // The native facility fixes the centre. Preserve it even when a full
        // configured body cannot fit this short link; never move the stop,
        // fabricate a lateral slot or call the resulting envelope compatible.
        if(active)retain(entry,within ? 'native_facility_position' : 'native_facility_body_exceeds_link',
          {facility,body_extent_within_current_link:within,
            note:'Centro nativo conservado; orientacion local estimada y posicion lateral no observada. No es una plaza de cola validada.'});
        continue;
        }
      }
      if(!occupancy && marker.Visual_Native_Queue_Kind==='shared_upstream' && body &&
         !(link?.lane_count===1 && blockingSingleLinks.has(marker.Link_ID))) {
        // The native aggregated queue identifies a serial domain, not one of
        // its represented parallel lanes. Keep every rigid body visible and
        // explicit about insufficient position/storage evidence; never hash
        // these vehicles into a supposedly observed terminal lane.
        if(active)retain(entry,evidence.eligible && marker.Visual_Queue_Context?.complete===false ?
          'queue_context_incomplete' : marker.Visual_Native_Queue_Extent?.available ?
            'shared_upstream_queue_position_unknown' : 'native_queue_extent_unknown',
          {context:marker.Visual_Queue_Context ?? null,native_queue_extent:marker.Visual_Native_Queue_Extent,
            queue_extent_projection:marker.Visual_Queue_Extent_Projection});
        continue;
      }
      if(!occupancy && marker.Visual_Native_Queue_Kind==='shared_upstream' && link?.eligible && link.lane_count===1 && blockingSingleLinks.has(marker.Link_ID)) {
        index=0;marker={...marker,Visual_Lane_Index:0,Visual_Lane_Source:'estimated_single_lane_native_queue'};
        entry.marker=marker;
      }
      const validLane=link?.eligible && Number.isSafeInteger(index) && index>=0 && index<link.lane_count &&
        (occupancy || this.lanes.compatiblePath(this.lanes.links.get(marker.Link_ID),marker.path));
      if(!validLane || typeof marker.vehicle!=='string') {
        const recorded=active && body && this.lanes.recordedBoundaryPath(marker);
        if(recorded) {
          entry.marker={...entry.marker,Visual_Recorded_Boundary_Path:recorded};
          retain(entry,'recorded_path_lateral_unknown',{path_evidence:recorded,
            note:'Centro y movimiento conservados de la fuente; posicion lateral y plaza de cola no determinadas. No se redistribuye ni se afirma observacion continua.'});
          continue;
        }
        // A recorded single-lane fixed endpoint still has a supported rigid pose.
        if(active && body && link?.lane_count===1 && !evidence.eligible) {
          entry.fixed=true;entries.set(key,entry);
        } else if(active)omit(entry,'geometry_or_lane_unavailable');
        continue;
      }
      // The unadjusted centreline body can exceed a short link even though
      // the recorded corridor supplies its complete footprint. Build that
      // front-referenced pose below before deciding it is unrepresentable.
      if(!body && !occupancy){if(active)omit(entry,'body_unrepresentable');continue;}
      entry.storage=this.lanes.storage(marker.Link_ID,index,nativeEntry ? marker.Observed_Queue_ID : null);
      entry.stopBoundary=this.lanes.stopBoundary(marker.Link_ID,index,s.stop_line_setback_m);
      const intersection=entry.stopBoundary?.geometric_setback_m ?? this.lanes.intersectionSetback(marker.Link_ID,index);
      const half=dimensions.length_m/2;
      // The line is shared by all body lengths on this lane. Both the road-strip
      // boundary and the configurable setback are visual estimates, not a measured
      // stop bar. Insufficient storage never reduces the requested margin.
      entry.head=intersection+s.stop_line_setback_m+half;
      if(Number.isFinite(entry.facilityStation))entry.head=Math.max(entry.head,link.length_m-entry.facilityStation+half+s.gap_m);
      entry.desired=fraction*(link.length_m-(entry.eligible ? entry.head : 0));
      entry.upstream=evidence.eligible ? this.upstream(entry,neighbors) : null;
      entry.lower=entry.upstream ? -entry.upstream.extent+half : link.length_m-entry.storage.length_m+half;
      if(occupancy) {
        const localEnd=occupancy.offset+link.length_m;
        const internalEnd=occupancy.corridor.parts.at(-1).link.id!==marker.Link_ID;
        // OSM subdivisions inside a reserved corridor are not intersections.
        // The native QSim reference is the vehicle front, not its body centre.
        const margin=internalEnd ? 0 : intersection+s.stop_line_setback_m;
        entry.stopBoundary=internalEnd ? null : entry.stopBoundary;
        const front=Number.isFinite(entry.facilityStation) ? Math.min(localEnd-margin,occupancy.offset+entry.facilityStation) : localEnd-margin;
        entry.axisLength=occupancy.corridor.length;entry.head=entry.axisLength-front+half;
        const f0=marker.Boundary_Provenance?.start_relative ?? 0,f1=marker.Boundary_Provenance?.end_relative ?? 1;
        entry.desiredStart=occupancy.offset+f0*link.length_m-half;
        entry.desiredEnd=(entry.eligible ? front : occupancy.offset+f1*link.length_m)-half;
        const facilityArrival=this.blockingFacilityBoundary(marker,'end'),facilityDeparture=this.blockingFacilityBoundary(marker,'start');
        if(facilityArrival || facilityDeparture) {
          // Approach, dwell and departure share the same estimated front anchor.
          // The recorded service endpoint remains available as native evidence.
          const anchor=endpoint=>Math.min(localEnd-margin,occupancy.offset+endpoint.station_m)-half;
          if(facilityArrival)entry.desiredEnd=anchor(facilityArrival);
          if(facilityDeparture) {
            entry.desiredStart=anchor(facilityDeparture);
            if(f0===f1 && marker.Motion_Plan?.status==='stationary')entry.desiredEnd=entry.desiredStart;
          }
          entry.marker={...entry.marker,Visual_Facility_Boundary_Projection:{
            source:'estimated_front_at_verified_blocking_service_endpoint',arrival:facilityArrival,departure:facilityDeparture,
            positions_observed:false,source_event_times_unchanged:true}};
        }
        const previous=adjacent?.previous,prior=previous && this.lanes.occupancy(previous);
        if(prior && facilityDeparture &&
           previous.Link_ID===marker.Link_ID && prior.ordinal===occupancy.ordinal &&
           prior.corridor.id===occupancy.corridor.id && previous.timestamps[1]===marker.timestamps[0] &&
           this.evidence(previous,previous.timestamps[1]-1e-7).eligible) {
          entry.continuationPreviousKey=this.key(previous);
          const resolved=releaseState.anchors.get(entry.key);
          if(resolved?.previous_key===entry.continuationPreviousKey && Number.isFinite(resolved.anchor_m)) {
            entry.desiredStart=resolved.anchor_m;
            if(marker.Motion_Plan?.status==='stationary') {
              entry.desiredEnd=resolved.anchor_m;
              entry.head=entry.axisLength-resolved.anchor_m;
            }
            entry.marker={...entry.marker,Visual_Facility_Continuation_Projection:{
              source:'estimated_facility_departure_from_historical_fifo_anchor',anchor_m:resolved.anchor_m,
              previous_interval:previous.timestamps,positions_observed:false,source_event_times_unchanged:true}};
          }
        }
        if(prior && f0===0 && this.lanes.observedConnection(previous,marker) &&
           (this.evidence(previous,previous.timestamps[1]-1e-7).eligible ||
            previous.Motion_Plan?.status==='stationary' && this.blockingFacilityBoundary(previous,'start'))) {
          const boundary=this.lanes.stopBoundary(previous.Link_ID,prior.slot,s.stop_line_setback_m);
          entry.releasePreviousKey=this.key(previous);
          const resolved=releaseState.anchors.get(entry.key),backed=resolved?.previous_key===entry.releasePreviousKey;
          occupancy.releaseSetback=backed ? resolved.setback_m : (boundary?.geometric_setback_m ?? 0)+s.stop_line_setback_m;
          entry.desiredStart-=occupancy.releaseSetback;
          entry.marker={...entry.marker,Visual_Occupancy_Release_Projection:{
            source:backed ? 'estimated_release_from_historical_fifo_anchor' : 'estimated_release_from_preceding_stop_boundary',
            setback_m:occupancy.releaseSetback,historical_anchor_available:backed,
            previous_anchor_m:backed ? resolved.previous_anchor_m : null,
            previous_link:previous.Link_ID,positions_observed:false,source_event_times_unchanged:true}};
        }
        entry.desired=entry.desiredStart+fraction*(entry.desiredEnd-entry.desiredStart);
        entry.lower=occupancy.corridor.parts[0].offset-half-(occupancy.releaseSetback ?? 0);entry.adjusted=true;
        entry.storage={length_m:occupancy.corridor.data.lane_capacity_m ?? occupancy.corridor.data.length_m,
          source:'native_corridor_length_reservation'};
        entry.marker={...entry.marker,Visual_Lane_Index:occupancy.slot,Visual_Lane_Source:'native_modeled_occupancy_slot',
          Visual_Occupancy_Domain:occupancy.corridor.id,Visual_Occupancy_Ordinal:occupancy.ordinal,
          Visual_Occupancy_Path_Length_Meters:occupancy.corridor.length,
          Visual_Occupancy_Reference:'front',Visual_Occupancy_Position_Observed:false};
      }
      if(evidence.eligible)entry.marker={...entry.marker,Visual_Queue_Source:'estimated_spacing_native_wait',
        Visual_Queue_Entry_Seconds:occupancy ? evidence.start : orderTime,Visual_Queue_Order_Source:occupancy ? 'native_corridor_reservation_ordinal' : nativeEntry ? 'native_lane_entry' : 'estimated_link_entry',
        Visual_Queue_Redistribution:true,Visual_Queue_Storage_Meters:entry.storage.length_m,
        Visual_Queue_Storage_Source:entry.storage.source,Visual_Queue_Stop_Margin_Meters:entry.head-half,
        Visual_Queue_Stop_Line_Meters:link.length_m-intersection-s.stop_line_setback_m,
        Visual_Queue_Stop_Line_Source:'inferred_road_strip_and_visual_setback',
        Visual_Queue_Stop_Boundary:entry.stopBoundary,
        Visual_Queue_Geometric_Setback_Meters:intersection,Visual_Queue_Configured_Setback_Meters:s.stop_line_setback_m,
        Visual_Queue_Reduced_Margin:false,
        Visual_Queue_Reason:'Espaciado visual estimado; WAIT, Motion_Plan y capacidad intactos'};
      if(evidence.eligible && marker.Visual_Queue_Context?.complete===false) {
        if(active) {
          const head=this.independentHeadPose(entry,headClaims.get(key),time,neighbors);
          entry.marker={...entry.marker,Visual_Queue_Head_Projection:head.projection};
          if(head.body) {
            entry.body=head.body;entry.marker=this.withBody({...entry.marker,
              Visual_Queue_Center_Meters:head.projection.station_m,Visual_Queue_Holding:time>=evidence.hold,
              Visual_Queue_Display_Link_ID:marker.Link_ID,Visual_Queue_Display_Station_Meters:head.projection.station_m},head.body,entry.presentation);
          }
          retain(entry,'queue_context_incomplete',{context:marker.Visual_Queue_Context,head_stop_projection:head.projection});
        }
        continue;
      }
      entries.set(key,entry);
      const groupKey=JSON.stringify([occupancy ? 'corridor:'+occupancy.corridor.id : marker.Link_ID,occupancy ? occupancy.reservationSlot : index]);
      entry.groupKey=groupKey;
      entry.preparedCheckpoint=this.preparedCheckpoint(entry);
      if(entry.checkpoint?.prepared!=null && entry.checkpoint.prepared!==entry.preparedCheckpoint)
        throw new Error('Checkpoint visual incompatible con geometria, precedencia o liberacion');
      if(!groups.has(groupKey))groups.set(groupKey,[]);groups.get(groupKey).push(entry);
    }
    phase('entriesMs');
    // An ordinal orders reservations only inside one corridor. A vehicle
    // entering the next corridor receives a newer ordinal while its rear may
    // still occupy the preceding one. Its recorded transition preserves FIFO.
    const departureBoundary=entry=>{
      if(Object.hasOwn(entry,'departureBoundary'))return entry.departureBoundary;
      let current=entry.marker,previous=entry.adjacent?.previous;
      const native=entry.occupancy,seen=new Set();
      while(native && previous && !seen.has(this.key(previous))) {
        seen.add(this.key(previous));
        const prior=this.lanes.occupancy(previous);
        if(!prior || previous.timestamps[1]!==current.timestamps[0])break;
        const sameLink=previous.Link_ID===current.Link_ID &&
          previous.Boundary_Provenance?.end_relative===current.Boundary_Provenance?.start_relative;
        if(!sameLink && !this.lanes.observedConnection(previous,current))break;
        if(prior.corridor.id!==native.corridor.id)
          return entry.departureBoundary={previous,current,occupancy:prior};
        if(prior.ordinal!==native.ordinal || prior.reservationSlot!==native.reservationSlot)break;
        current=previous;previous=neighbors(previous)?.previous;
      }
      return entry.departureBoundary=null;
    };
    const priorOccupancy=entry=>departureBoundary(entry)?.occupancy;
    const precedes=(leader,follower)=>{
      if(!leader.occupancy || !follower.occupancy || leader.marker.vehicle===follower.marker.vehicle)return false;
      const a=leader.occupancy,b=follower.occupancy;
      if(a.corridor.id===b.corridor.id && a.reservationSlot===b.reservationSlot)return a.ordinal<b.ordinal;
      const p=priorOccupancy(leader);
      return Boolean(p && p.corridor.id===b.corridor.id && p.reservationSlot===b.reservationSlot && p.ordinal<b.ordinal);
    };
    const departedByGroup=new Map();
    for(const entry of entries.values()) {
      const p=priorOccupancy(entry);
      if(p && entry.occupancy && p.corridor.id!==entry.occupancy.corridor.id) {
        const key=JSON.stringify(['corridor:'+p.corridor.id,p.reservationSlot]);
        if(!departedByGroup.has(key))departedByGroup.set(key,[]);departedByGroup.get(key).push(entry);
      }
    }
    if(releaseState.classifyOnly===true) {
      // The graph may classify a native terminal entry even when the corridor
      // occupancy cannot be represented. Export the same prepared group/order
      // used below, before evaluating any BASE, FINAL, FIFO or release result.
      // A classification is source metadata, never a position certificate.
      const occupancy=value=>value?{corridor:value.corridor.id,slot:value.reservationSlot,ordinal:value.ordinal}:null;
      return {classifications:Object.fromEntries([...entries].map(([key,entry])=>{
        const complete=typeof entry.groupKey==='string' && Number.isFinite(entry.orderTime) &&
          Boolean(entry.occupancy || entry.nativeEntry && entry.marker.Visual_Native_Queue_Kind==='terminal');
        return [key,{complete,represented:true,eligible:Boolean(entry.eligible),group_key:entry.groupKey??null,
          order_time:Number.isFinite(entry.orderTime)?entry.orderTime:null,hold:Number.isFinite(entry.hold)?entry.hold:null,
          start:entry.start,end:entry.end,native_entry:Boolean(entry.nativeEntry),occupancy:occupancy(entry.occupancy),
          departure:occupancy(priorOccupancy(entry)),departure_complete:!entry.occupancy,
          reason:complete?null:'unproven_context_entry'}];
      })),pose_requests:profile.poseRequests};
    }
    const rawIndex=this.spatialIndex();
    for(const entry of entries.values())if(entry.active && entry.body) {
      for(const other of rawIndex.query(entry.body)) {
        const a=this.lanes.links.get(entry.marker.Link_ID),b=this.lanes.links.get(other.entry.marker.Link_ID);
        if((!a || !b || this.lanes.compatibleLevel(a,b)) && this.envelopesOverlap(entry.body,other.body))
          collisions.push(this.collision(entry,{body:entry.body},other,time,'pending'));
      }
      rawIndex.add({entry,body:entry.body});
    }
    phase('rawCollisionsMs');
    const anchorInputs=[...entries.values()].filter(e=>e.eligible || e.occupancy);
    const previousAnchors=this.anchorCache;
    // Only immutable hold geometry is cached. Membership, native lane entry,
    // neighbour poses, configuration and window roster must all still match.
    const reuse=previousAnchors?.context===context && previousAnchors.stamps.length===anchorInputs.length && anchorInputs.every((e,i)=>{
      const p=previousAnchors.stamps[i],m=e.marker;
      return p[0]===e.key && p[1]===m.Visual_Lane_Index && p[2]===e.orderTime && p[3]===m.Motion_Plan && p[4]===m.Observed_Waits &&
        p[5]===m.path && p[6]===m.timestamps && p[7]===e.lower && p[8]===e.head && p[9]===e.adjacent?.previous && p[10]===e.adjacent?.next &&
        p[11]===e.dimensions.length_m && p[12]===e.dimensions.width_m && p[13]===e.desiredStart && p[14]===e.desiredEnd && p[15]===e.eligible && p[16]===e.anchorPhase && p[17]===e.checkpoint;
    });
    const stamps=reuse ? previousAnchors.stamps : anchorInputs.map(e=>[e.key,e.marker.Visual_Lane_Index,e.orderTime,e.marker.Motion_Plan,e.marker.Observed_Waits,
      e.marker.path,e.marker.timestamps,e.lower,e.head,e.adjacent?.previous,e.adjacent?.next,e.dimensions.length_m,e.dimensions.width_m,e.desiredStart,e.desiredEnd,e.eligible,e.anchorPhase,e.checkpoint]);
    profile.anchorCacheHit=Boolean(reuse);
    const baseAnchors=reuse ? previousAnchors.base : new Map(),finalAnchors=reuse ? previousAnchors.final : new Map(),candidates=[];
    for(const group of groups.values()) {
      // FIFO from recorded entry; progress must never swap identities in a queue.
      group.sort(compare);
      for(let i=0;i<group.length;i++)if(group[i-1]?.orderTime===group[i].orderTime || group[i+1]?.orderTime===group[i].orderTime)
        group[i].marker={...group[i].marker,Visual_Queue_Order_Ambiguous:true};
      const anchors=[];
      for(const entry of group) {
        // A leader may finish service at precisely the follower's arrival.
        // Its following movement still occupies this corridor at that epoch;
        // considering HOLD rows alone would put both bodies at the stop.
        if(!entry.eligible && entry.occupancy)anchors.push(entry);
        if(entry.eligible) {
          if(entry.checkpoint?.base) {
            entry.anchor=entry.checkpoint.base.anchor_m;baseAnchors.set(entry.key,entry.anchor);anchors.push(entry);continue;
          }
          if(reuse){entry.anchor=previousAnchors.base.get(entry.key);baseAnchors.set(entry.key,entry.anchor);continue;}
          let anchor=(entry.axisLength ?? entry.link.length_m)-entry.head;
          for(const earlier of anchors)if(earlier.start<=entry.hold && entry.hold<earlier.end) {
            const f=this.fractionAt(earlier.marker,entry.hold);
            const before=earlier.eligible && entry.hold>=earlier.hold ? earlier.anchor : f==null ? null :
              Math.min(earlier.occupancy ? earlier.desiredStart+f*(earlier.desiredEnd-earlier.desiredStart) : f*(earlier.link.length_m-earlier.head),earlier.anchor ?? Infinity);
            if(before!=null)anchor=Math.min(anchor,before-separation(earlier,entry));
          }
          // Reserve bend clearance at the same absolute hold epoch as FIFO.
          // A departed leader cannot make a stopped follower jump forward.
          const occupied=anchors.filter(e=>e.start<=entry.hold && entry.hold<e.end && e.hold<=entry.hold)
            .map(e=>this.pose(e,e.anchor,true,neighbors)).filter(Boolean);
          let pose=this.pose(entry,anchor,true,neighbors);
          while(anchor>=entry.lower && (!pose || occupied.some(p=>this.envelopesOverlap(p.body,pose.body)))) {
            anchor-=.25;pose=this.pose(entry,anchor,true,neighbors);
          }
          entry.anchor=anchor;baseAnchors.set(entry.key,anchor);anchors.push(entry);
        }
      }
      let leader=null;
      for(const entry of group.filter(e=>e.active)) {
        const limit=leader ? leader.center-separation(leader,entry) : Infinity;
        entry.center=entry.eligible && time>=entry.hold ? entry.anchor : Math.min(entry.desired,entry.anchor ?? Infinity,limit);
        entry.following=entry.center<entry.desired-1e-7 && !entry.eligible;
        entry.adjusted=Boolean(entry.occupancy) || entry.eligible || entry.following;
        // Preserve the slot even if its body cannot be represented.
        leader=entry;
        if(!entry.occupancy && entry.eligible && entry.anchor<0) {
          retain(entry,'queue_projection_reverses_motion',{anchor_m:entry.anchor,lower_m:entry.lower,
            upstream_supported:Boolean(entry.upstream),note:'A connected predecessor alone does not supply a continuous approach to a negative station.'});continue;
        }
        if(entry.eligible && entry.anchor<entry.lower-1e-7 || entry.adjusted && (entry.center<0 && !entry.upstream && !entry.occupancy ||
          (time>=entry.hold || entry.following) && entry.center<entry.lower-1e-7)) {
          retain(entry,'storage_exceeded',{center_m:entry.center,anchor_m:entry.anchor,lower_m:entry.lower,upstream_supported:Boolean(entry.upstream)});continue;
        }
        // The rigid body must fit its lane. Safety envelopes can extend into
        // the next lane: oriented SAT can still stagger their centres safely.
        if(entry.adjusted && entry.dimensions.width_m>entry.link.lane_width_m+1e-7) {
          retain(entry,'body_geometry_unavailable',{lane_width_m:entry.link.lane_width_m,
            requested_width_m:entry.dimensions.width_m,envelope_width_m:entry.dimensions.width_m+2*s.lateral_clearance_m});continue;
        }
        entry.pose=this.pose(entry,entry.center,entry.adjusted,neighbors,entry.eligible && time>=entry.hold);
        if(!entry.pose){retain(entry,'boundary_transition',{center_m:entry.center});continue;}
        candidates.push(entry);
      }
    }
    for(const entry of entries.values())if(entry.fixed)candidates.push({...entry,pose:{body:entry.body},adjusted:false});
    // Freeze cross-lane clearance at hold_start too. Departed context rows are
    // constraints only if their recorded hold overlapped this hold's start.
    const holdIndex=this.spatialIndex(),sweptConstraints=new Map();
    const turnBound=(entry,leader,center,pose)=>{
      if(!leader.occupancy || !pose?.body || leader.eligible && entry.hold>=leader.hold)return null;
      const end=leader.eligible ? Math.min(leader.desiredEnd,leader.anchor ?? Infinity) : leader.desiredEnd;
      if(!Number.isFinite(end) || end<center-1e-7)return null;
      const carried=[...(leader.checkpoint?.fifo||[]),...(leader.checkpoint?.interpolate||[])].map(row=>row.result?.front_trace)
        .find(row=>row && row.from_center_m===center && row.to_center_m===end && row.length_m===leader.dimensions.length_m);
      const trace=carried?carried.trace:this.lanes.occupancyFrontPath?.(leader.occupancy,center,end,leader.dimensions.length_m,
        {...neighbors(leader.marker),current:leader.marker,resolve:neighbors});
      if(!trace?.path?.length)return null;
      const edge=this.lanes.links.get(entry.marker.Link_ID)?.geometry.edges.at(-1);
      if(!edge)return null;
      const axis=entry.stopBoundary?.forward ?? [edge.dx,edge.dy],p=this.lanes.projection;
      const metric=point=>[(point[0]-p.origin[0])*p.xScale,(point[1]-p.origin[1])*p.yScale];
      const points=trace.path.map(metric),angle=pose.body.heading*Math.PI/180;
      const turning=Math.cos(angle)*axis[0]+Math.sin(angle)*axis[1]<1-1e-7 || points.some((point,i)=>{
        if(!i)return false;const dx=point[0]-points[i-1][0],dy=point[1]-points[i-1][1],length=Math.hypot(dx,dy);
        return length>1e-7 && (dx*axis[0]+dy*axis[1])/length<1-1e-7;
      });
      if(!turning)return null;
      // Every corner of the intact, inflated body lies within this radius
      // of its front. The minimum front projection over the recorded lane
      // curve therefore bounds the complete turn, including between frames.
      // Freeze this conservative display bound at HOLD; never move a stopped
      // follower after the leader's rotating rear has reached it.
      const radius=Math.hypot(leader.dimensions.length_m+s.gap_m/2,leader.dimensions.width_m/2+s.lateral_clearance_m);
      const limit=Math.min(...points.map(point=>point[0]*axis[0]+point[1]*axis[1]))-radius;
      return {axis,limit,source:'conservative_rigid_turn_front_projection_v1',positions_observed:false,
        leader:leader.marker.vehicle,leader_interval:leader.marker.timestamps,hold_start:entry.hold,
        radius_m:radius,front_path:trace,scope:'display_clearance_only; native events and Motion_Plan unchanged'};
    };
    const beyondTurnBound=(body,bound)=>{
      const box=this.box(body),a=bound.axis;
      const support=(box.half+s.gap_m/2)*Math.abs(box.c*a[0]+box.s*a[1])+
        (box.side+s.lateral_clearance_m)*Math.abs(-box.s*a[0]+box.c*a[1]);
      return box.x*a[0]+box.y*a[1]+support>bound.limit+1e-7;
    };
    // A forming predecessor may itself follow the rear of a vehicle already
    // in the next corridor. Its unconstrained Motion_Plan is not the pose that
    // final FIFO placement will display. Freeze a new HOLD behind that same
    // constrained predecessor at the HOLD epoch, including transitive leaders.
    // This is a display reconstruction on the existing recorded geometry; it
    // neither advances native time nor turns a missing trajectory into motion.
    let finalStage=null;
    const requirePhaseAtStage=entry=>{
      if(entry.eligible && entry.anchorPhase==='base' && finalStage && compare(entry,finalStage)<0)
        throw new Error('Certificado BASE no cubre la dependencia FINAL requerida');
    };
    const fifoPoseAt=(entry,epoch,memo=new Map(),visiting=new Set())=>{
      if(memo.has(entry.key))return memo.get(entry.key);
      if(visiting.has(entry.key) || !entry.occupancy || !(entry.start<=epoch && epoch<entry.end))return null;
      const cached=entry.checkpoint?.fifo?.find(row=>row.epoch===epoch && row.stage?.[0]===finalStage?.orderTime && row.stage?.[1]===finalStage?.key);
      if(cached) {
        if(cached.result?.available===false){memo.set(entry.key,null);return null;}
        if(cached.result?.available!==true || !Number.isFinite(cached.result.center_m))throw new Error('Checkpoint FIFO incompleto');
        const pose=this.pose(entry,cached.result.center_m,true,neighbors,entry.eligible&&epoch>=entry.hold);
        if(!pose || JSON.stringify(SimZ1VisualQueues.canonical(pose))!==JSON.stringify(SimZ1VisualQueues.canonical(cached.result.pose)))
          throw new Error('Checkpoint FIFO no reproduce su geometria');
        const result={entry,center:cached.result.center_m,pose};memo.set(entry.key,result);return result;
      }
      requirePhaseAtStage(entry);
      visiting.add(entry.key);
      const finish=value=>{visiting.delete(entry.key);memo.set(entry.key,value);return value;};
      const fraction=this.fractionAt(entry.marker,epoch);
      if(fraction==null)return finish(null);
      const held=entry.eligible && epoch>=entry.hold;
      let center=held ? entry.anchor : Math.min(entry.desiredStart+fraction*(entry.desiredEnd-entry.desiredStart),entry.anchor ?? Infinity);
      if(!Number.isFinite(center))return finish(null);
      if(held) {
        const pose=this.pose(entry,center,true,neighbors,true);
        return finish(pose ? {entry,center,pose} : null);
      }
      const predecessors=[...(groups.get(entry.groupKey) || []),...(departedByGroup.get(entry.groupKey) || [])]
        .filter(other=>other!==entry && other.start<=epoch && epoch<other.end && precedes(other,entry));
      const leaders=[],bounds=[];
      for(const other of predecessors) {
        const projection=fifoPoseAt(other,epoch,memo,visiting);
        if(!projection)return finish(null);
        leaders.push(projection);
        // The departing rear may rotate toward this lane between samples.
        // Use the existing swept-front certificate, not an arbitrary extra gap
        // or the smallest separation seen at a chosen animation frame.
        const bound=turnBound({...entry,hold:epoch},other,projection.center,projection.pose);
        if(bound)bounds.push(bound);
        if(!held && other.groupKey===entry.groupKey)center=Math.min(center,projection.center-separation(other,entry));
      }
      let pose=this.pose(entry,center,true,neighbors,held);
      if(!pose)return finish(null);
      const blocked=candidate=>bounds.some(bound=>beyondTurnBound(candidate.body,bound)) ||
        leaders.some(other=>this.envelopesOverlap(candidate.body,other.pose.body));
      if(!held && blocked(pose)) {
        let blockedAt=center,clear=null;
        for(let next=center-.25;next>=entry.lower-.250001;next-=.25) {
          const at=Math.max(entry.lower,next),candidate=this.pose(entry,at,true,neighbors,false);
          if(candidate && !blocked(candidate)) {
            clear=at;
            for(let i=0;i<9;i++) {
              const mid=(clear+blockedAt)/2,test=this.pose(entry,mid,true,neighbors,false);
              if(test && !blocked(test))clear=mid;else blockedAt=mid;
            }
            break;
          }
          blockedAt=at;if(at===entry.lower)break;
        }
        if(clear==null)return finish(null);
        // Final placement's 25 cm / 2^9 bisection can land on either side of
        // the previous frame's estimate by less than one search cell. Reserve
        // that explicit numerical error bound in the historical certificate;
        // otherwise a frozen follower can lose micrometres of its margin.
        center=clear-.25/2**9;
        if(center<entry.lower)return finish(null);
        pose=this.pose(entry,center,true,neighbors,false);
      }
      return finish(pose ? {entry,center,pose} : null);
    };
    for(const entry of [...entries.values()].filter(e=>e.eligible && Number.isFinite(e.anchor)).sort(compare)) {
      if(entry.anchorPhase==='base') {
        // The support graph proves that consumers read this entry before its
        // final pass in compare order. Its BASE anchor is complete; its FINAL
        // anchor is deliberately not certified and may not enter holdIndex.
        // Active bodies require their own final certificate above.
        entry.anchor=baseAnchors.get(entry.key);finalAnchors.set(entry.key,entry.anchor);
        continue;
      }
      finalStage=entry;
      if(entry.checkpoint?.final) {
        const saved=entry.checkpoint.final;entry.anchor=saved.anchor_m;finalAnchors.set(entry.key,entry.anchor);
        if(saved.turn_bounds.length){sweptConstraints.set(entry.key,saved.turn_bounds);entry.marker={...entry.marker,Visual_Queue_Turn_Clearance:saved.turn_bounds};}
        const pose=this.pose(entry,entry.anchor,true,neighbors);
        if(pose)holdIndex.add({entry,body:pose.body});
        if(entry.active && entry.center>entry.anchor){entry.center=entry.anchor;entry.pose=this.pose(entry,entry.center,true,neighbors,time>=entry.hold);}
        continue;
      }
      if(reuse) {
        const bounds=previousAnchors.sweptConstraints?.get(entry.key);
        if(bounds){sweptConstraints.set(entry.key,bounds);entry.marker={...entry.marker,Visual_Queue_Turn_Clearance:bounds};}
        entry.anchor=previousAnchors.final.get(entry.key);finalAnchors.set(entry.key,entry.anchor);
        if(entry.active && entry.center>entry.anchor){entry.center=entry.anchor;entry.pose=this.pose(entry,entry.center,true,neighbors,time>=entry.hold);}
        continue;
      }
      if(entry.occupancy) {
        const memo=new Map();
        for(const earlier of groups.get(entry.groupKey) || [])if(earlier.start<=entry.hold && entry.hold<earlier.end && precedes(earlier,entry)) {
          const projection=fifoPoseAt(earlier,entry.hold,memo);
          if(projection)entry.anchor=Math.min(entry.anchor,projection.center-separation(earlier,entry));
        }
      }
      const departed=(departedByGroup.get(entry.groupKey) || []).filter(other=>
        other.start<=entry.hold && entry.hold<other.end && precedes(other,entry)).map(other=>{
          requirePhaseAtStage(other);
          const fraction=this.fractionAt(other.marker,entry.hold);
          const center=other.eligible && entry.hold>=other.hold ? other.anchor : fraction==null ? null :
            other.desiredStart+fraction*(other.desiredEnd-other.desiredStart);
          const pose=Number.isFinite(center) ? this.pose(other,center,true,neighbors,false) : null;
          return pose ? {...pose,turnBound:turnBound(entry,other,center,pose)} : null;
        }).filter(Boolean);
      const bounds=departed.map(pose=>pose.turnBound).filter(Boolean);
      if(bounds.length){sweptConstraints.set(entry.key,bounds);entry.marker={...entry.marker,Visual_Queue_Turn_Clearance:bounds};}
      const blocked=pose=>bounds.some(bound=>beyondTurnBound(pose.body,bound)) ||
        departed.some(other=>this.envelopesOverlap(pose.body,other.body)) || [...holdIndex.query(pose.body)].some(row=>row.entry.hold<=entry.hold && entry.hold<row.entry.end &&
        this.lanes.compatibleLevel(this.lanes.links.get(entry.marker.Link_ID),this.lanes.links.get(row.entry.marker.Link_ID)) &&
        this.envelopesOverlap(pose.body,row.body));
      let pose=this.pose(entry,entry.anchor,true,neighbors);
      while(entry.anchor>=entry.lower && (!pose || blocked(pose))) {
        entry.anchor-=.25;pose=this.pose(entry,entry.anchor,true,neighbors);
      }
      if(pose)holdIndex.add({entry,body:pose.body});
      if(entry.active && entry.center>entry.anchor) {
        entry.center=entry.anchor;entry.pose=this.pose(entry,entry.center,true,neighbors,time>=entry.hold);
      }
      finalAnchors.set(entry.key,entry.anchor);
    }
    this.anchorCache={context,stamps,base:baseAnchors,final:finalAnchors,sweptConstraints};
    // A follower may have waited several body lengths behind the stop line.
    // Reconstruct that immutable anchor before projecting its next interval.
    // Dependencies run from an earlier HOLD to a later interval, so bounded
    // refinement converges independently of playback history or frame rate.
    const releaseAnchors=new Map(releaseState.external?[]:pinnedReleases);let changed=false;
    for(const entry of entries.values())if(entry.continuationPreviousKey) {
      const previous=entries.get(entry.continuationPreviousKey);
      if(!Number.isFinite(previous?.anchor) || previous.anchor<previous.lower-1e-7 ||
         previous.marker.Visual_Queue_Context?.complete===false)continue;
      const row={previous_key:entry.continuationPreviousKey,anchor_m:previous.anchor};
      releaseAnchors.set(entry.key,row);
      const old=releaseState.anchors.get(entry.key);
      if(!old || old.previous_key!==row.previous_key || Math.abs(old.anchor_m-row.anchor_m)>1e-7)changed=true;
    }
    for(const entry of entries.values())if(entry.releasePreviousKey) {
      const priorEntry=entries.get(entry.releasePreviousKey),prior=priorEntry?.occupancy;
      if(!prior || !Number.isFinite(priorEntry.anchor) || priorEntry.anchor<priorEntry.lower-1e-7 ||
         priorEntry.marker.Visual_Queue_Context?.complete===false)continue;
      const setback=Math.max(0,prior.offset+priorEntry.link.length_m-priorEntry.anchor-priorEntry.dimensions.length_m/2);
      const row={previous_key:entry.releasePreviousKey,previous_anchor_m:priorEntry.anchor,setback_m:setback};
      releaseAnchors.set(entry.key,row);
      const old=releaseState.anchors.get(entry.key);
      if(!old || old.previous_key!==row.previous_key || Math.abs(old.setback_m-setback)>1e-7)changed=true;
    }
    if([...releaseState.anchors.keys()].some(key=>!releaseAnchors.has(key)))changed=true;
    if(changed && !releaseState.external && releaseState.depth<=entries.size)
      return this.frame(markers,time,neighbors,context,{anchors:releaseAnchors,depth:releaseState.depth+1});
    if(changed)limitations.push({reason:releaseState.external?'external_release_pass_pending':'release_anchor_refinement_incomplete',spacing_compatible:false});
    this.releaseCache={context,anchors:releaseAnchors};
    this.releasePass={external:Boolean(releaseState.external),generation:releaseState.depth,changed,
      next:Object.fromEntries([...entries.keys()].map(key=>[key,releaseAnchors.get(key)??null]))};
    // Offline support preparation calls this exact kernel after a component's
    // dependencies are certified. It does not integrate animation frames or
    // invent a position for the renderer's null/cyclic FIFO result.
    this.supportState=request=>{
      const entry=entries.get(request.key);if(!entry)throw new Error('Estado de soporte sin entrada representable');
      let result;
      const frontTrace=(center,pose,anchor=entry.anchor)=>{
        const end=entry.eligible?Math.min(entry.desiredEnd,anchor??Infinity):entry.desiredEnd;
        return Number.isFinite(center)&&Number.isFinite(end)&&entry.occupancy?{from_center_m:center,to_center_m:end,length_m:entry.dimensions.length_m,
          trace:this.lanes.occupancyFrontPath?.(entry.occupancy,center,end,entry.dimensions.length_m,
            {...neighbors(entry.marker),current:entry.marker,resolve:neighbors})??null}:null;
      };
      if(request.role==='base'||request.role==='final') {
        const anchor=(request.role==='base'?baseAnchors:finalAnchors).get(entry.key),pose=this.pose(entry,anchor,true,neighbors,true);
        result={anchor_m:anchor,pose,pose_available:Boolean(pose),lower_m:entry.lower,within_storage:anchor>=entry.lower-1e-7,
          ...(request.role==='final'?{turn_bounds:sweptConstraints.get(entry.key)??[]}:{})};
      }
      else if(request.role==='interpolate') {
        // FINAL's departed-body path reads unconstrained interpolation, not
        // recursive FIFO. Its swept future front nevertheless ends at the
        // BASE or FINAL anchor available at that exact final-pass stage.
        // Ordinary BASE interpolation retains the historical null stage.
        let endpointAnchor=baseAnchors.get(entry.key);
        if(request.stage!=null) {
          if(!Array.isArray(request.stage)||request.stage.length!==2||!Number.isFinite(request.stage[0])||typeof request.stage[1]!=='string')
            throw new Error('Etapa de proyeccion de soporte invalida');
          const earlier=compare(entry,{orderTime:request.stage[0],key:request.stage[1]})<0;
          if(entry.eligible && earlier && entry.anchorPhase==='base')
            throw new Error('Certificado BASE no cubre la proyeccion FINAL requerida');
          endpointAnchor=(earlier?finalAnchors:baseAnchors).get(entry.key);
        }
        const fraction=this.fractionAt(entry.marker,request.epoch),center=fraction==null?null:entry.desiredStart+fraction*(entry.desiredEnd-entry.desiredStart),
          pose=Number.isFinite(center)?this.pose(entry,center,true,neighbors,false):null;
        result={desired_start_m:entry.desiredStart,desired_end_m:entry.desiredEnd,lower_m:entry.lower,head_m:entry.head,
          center_m:center,pose,pose_available:Boolean(pose),front_trace:frontTrace(center,pose,endpointAnchor)};
      }
      else if(request.role==='fifo') {
        if(!Array.isArray(request.stage)||request.stage.length!==2||!Number.isFinite(request.stage[0])||typeof request.stage[1]!=='string')
          throw new Error('Etapa FIFO de soporte invalida');
        const savedStage=finalStage,savedAnchors=new Map([...entries.values()].map(row=>[row,row.anchor]));
        finalStage={orderTime:request.stage[0],key:request.stage[1]};
        try {
          for(const row of entries.values())if(row.eligible)row.anchor=(compare(row,finalStage)<0?finalAnchors:baseAnchors).get(row.key);
          const value=fifoPoseAt(entry,request.epoch);
          result=value?{available:true,center_m:value.center,pose:value.pose,front_trace:frontTrace(value.center,value.pose)}:{available:false};
        } finally {for(const [row,anchor]of savedAnchors)row.anchor=anchor;finalStage=savedStage;}
      } else throw new Error('Rol de soporte desconocido');
      if(['base','final'].includes(request.role)&&!Number.isFinite(result.anchor_m))throw new Error('Ancla de soporte ausente');
      const priorKey=entry.continuationPreviousKey??entry.releasePreviousKey,prior=entry.adjacent?.previous,
        priorOccupancy=prior&&this.lanes.occupancy(prior),priorDimensions=prior&&SimZ1VehicleCatalog.resolve(prior).dimensions;
      const recipe=entry.continuationPreviousKey?{kind:'continuation',previous_key:priorKey}:entry.releasePreviousKey&&priorOccupancy&&priorDimensions?
        {kind:'setback',previous_key:priorKey,previous_offset_m:priorOccupancy.offset,
          previous_link_length_m:this.lanes.describe(prior.Link_ID).length_m,previous_half_m:priorDimensions.length_m/2}:null;
      return {...request,result,release:(releaseState.external?releaseState.anchors:releaseAnchors).get(entry.key)??null,
        release_proposed:releaseAnchors.get(entry.key)??null,release_recipe:recipe,
        input:SimZ1VisualQueues.checkpointInput(entry.raw),prepared:entry.preparedCheckpoint};
    };
    phase('anchorsMs');
    const index=this.spatialIndex(),placed=new Map();
    // Resolve bodies in deterministic FIFO order. A conflicting
    // free movement is evidence of a limitation, not permission to move its time.
    // Stable topological order: each lane's FIFO plus recorded departures into
    // its next corridor. Geometry alone cannot reorder unrelated traffic.
    candidates.sort(compare);
    const byGroup=new Map(),edges=new Map(candidates.map(e=>[e,new Set()])),indegree=new Map(candidates.map(e=>[e,0]));
    for(const entry of candidates)if(entry.groupKey){if(!byGroup.has(entry.groupKey))byGroup.set(entry.groupKey,[]);byGroup.get(entry.groupKey).push(entry);}
    const edge=(a,b)=>{if(a!==b && !edges.get(a).has(b)){edges.get(a).add(b);indegree.set(b,indegree.get(b)+1);}};
    for(const group of byGroup.values())for(let i=1;i<group.length;i++)edge(group[i-1],group[i]);
    for(const entry of candidates) {
      const p=priorOccupancy(entry);if(!p || p.corridor.id===entry.occupancy?.corridor.id)continue;
      const follower=(byGroup.get(JSON.stringify(['corridor:'+p.corridor.id,p.reservationSlot])) || []).find(other=>precedes(entry,other));
      if(follower)edge(entry,follower);
    }
    const ready=candidates.filter(e=>indegree.get(e)===0),ordered=[];
    while(ready.length){ready.sort(compare);const entry=ready.shift();ordered.push(entry);
      for(const next of edges.get(entry)){indegree.set(next,indegree.get(next)-1);if(indegree.get(next)===0)ready.push(next);}}
    if(ordered.length===candidates.length)candidates.splice(0,candidates.length,...ordered);
    else limitations.push({reason:'native_fifo_transition_order_cycle',spacing_compatible:false});
    const compatible=(a,b)=>{
      const left=this.lanes.links.get(a.marker.Link_ID),right=this.lanes.links.get(b.marker.Link_ID);
      return !left || !right || this.lanes.compatibleLevel(left,right);
    };
    const conflicts=(entry,pose)=>[...index.query(pose.body)].filter(other=>compatible(entry,other.entry) &&
      this.envelopesOverlap(pose.body,other.body));
    for(const entry of candidates) {
      let pose=entry.pose,center=entry.center;
      // Cross-lane anchor clearance may have exhausted storage after the first
      // lane pass. Apply the same whole-interval policy after that adjustment.
      if(!entry.occupancy && entry.eligible && entry.anchor<0) {
        retain(entry,'queue_projection_reverses_motion',{anchor_m:entry.anchor,lower_m:entry.lower,
          upstream_supported:Boolean(entry.upstream)});continue;
      }
      if(entry.eligible && entry.anchor<entry.lower-1e-7) {
        retain(entry,'storage_exceeded',{anchor_m:entry.anchor,lower_m:entry.lower});continue;
      }
      if(!pose || entry.adjusted && time>=entry.hold && center<entry.lower-1e-7) {
        retain(entry,'storage_exceeded',{center_m:center,lower_m:entry.lower});continue;
      }
      const blockers=conflicts(entry,pose),original=pose;
      // Also constrain followers after a predecessor was pushed back by a bend
      // or by another lane; this never grants a different lane or extra storage.
      const laneKey=entry.groupKey ?? JSON.stringify([entry.marker.Link_ID,entry.marker.Visual_Lane_Index]);
      const preceding=placed.get(laneKey);
      if(!entry.fixed && preceding && center>preceding.center-separation(preceding,entry)+1e-7) {
        if(entry.eligible && time>=entry.hold)limitations.push({vehicle_id:entry.marker.vehicle,
          reason:'fifo_conflicts_with_recorded_hold',center_m:center,predecessor_center_m:preceding.center});
        else {
          center=preceding.center-separation(preceding,entry);
          pose=this.pose(entry,center,true,neighbors,entry.eligible && time>=entry.hold);entry.adjusted=true;entry.following=!entry.eligible;
        }
      }
      let hit=pose===original || !pose ? blockers : conflicts(entry,pose);
      if(hit.length && !entry.fixed) {
        // Only an evidenced queue/follower may be relocated, never a free car
        // crossing another free car at the same native instant.
        const frozen=entry.eligible && time>=entry.hold;
        const supported=!frozen && (entry.eligible || entry.following || hit.some(row=>precedes(row.entry,entry) || row.entry.eligible &&
          row.entry.groupKey===entry.groupKey));
        if(supported) {
          entry.adjusted=true;entry.following=!entry.eligible;
          const initial=center,lower=entry.lower;
          // Bounded search of existing geometry. 25 cm is only a search step;
          // binary refinement finds the closest admissible station to 1 mm.
          let blocked=initial;
          for(let next=initial-.25;next>=lower-.250001;next-=.25) {
            const at=Math.max(lower,next),candidate=this.pose(entry,at,true,neighbors,false);
            if(candidate && !conflicts(entry,candidate).length) {
              let clear=at;
              for(let n=0;n<9;n++) {
                const mid=(clear+blocked)/2,test=this.pose(entry,mid,true,neighbors,false);
                if(test && !conflicts(entry,test).length)clear=mid;else blocked=mid;
              }
              center=clear;pose=this.pose(entry,center,true,neighbors,false);hit=[];break;
            }
            blocked=at;if(at===lower)break;
          }
          if(hit.length) {
            const ids=hit.map(row=>row.entry.marker.vehicle);
            for(const other of hit)collisions.push(this.collision(entry,original,other,time,'no_supported_slot'));
            retain(entry,'storage_exceeded',{blocking_vehicle_ids:ids,original_reason:'body_overlap',lower_m:lower});
            placed.set(laneKey,{center:Math.min(center,lower)-entry.dimensions.length_m-s.gap_m,dimensions:entry.dimensions});continue;
          }
        }
      }
      if(!pose || entry.adjusted && (time>=entry.hold || entry.following) && center<entry.lower-1e-7) {
        retain(entry,'storage_exceeded',{center_m:center,lower_m:entry.lower});continue;
      }
      for(const other of blockers)collisions.push(this.collision(entry,original,other,time,
        hit.includes(other) ? 'unresolved' : 'resolved_spacing'));
      for(const other of hit)if(!blockers.includes(other))collisions.push(this.collision(entry,pose,other,time,'unresolved'));
      const state=entry.eligible ? time<entry.hold ? 'forming' : 'queued' : entry.following ? 'following' : 'moving';
      const saved=this.finalMarkers.get(entry.raw),old=saved?.marker,b=pose.body;
      const reusable=saved?.context===context && saved.center===center && saved.state===state &&
        old.Visual_Queue_Display_Link_ID===(entry.adjusted ? pose.displayLink : undefined) &&
        old.position[0]===b.position[0] && old.position[1]===b.position[1] && old.Visual_Body_Heading_Degrees===b.heading &&
        old.Visual_Body_Support===b.support && old.Visual_Body_Length_Meters===b.length_m && old.Visual_Body_Width_Meters===b.width_m &&
        old.Visual_Body_Opacity===b.opacity && old.Visual_Body_Clipped===b.clipped &&
        old.Visual_Queue_Order_Ambiguous===entry.marker.Visual_Queue_Order_Ambiguous &&
        old.Visual_Unresolved_Conflicts.length===hit.length && old.Visual_Unresolved_Conflicts.every((id,i)=>id===hit[i].entry.marker.vehicle);
      let marker=reusable ? old : {...entry.marker,Visual_Queue_Representable:true,Visual_Queue_Compatible:hit.length===0,Visual_Queue_Opacity:1,
        Visual_Queue_State:state,Visual_Queue_Holding:entry.eligible && time>=entry.hold,
        Visual_Unresolved_Conflicts:hit.map(row=>row.entry.marker.vehicle)};
      if(!reusable && entry.adjusted)marker={...marker,Visual_Queue_Center_Meters:center,
        Visual_Queue_Display_Link_ID:pose.displayLink,Visual_Queue_Display_Station_Meters:pose.station,
        Visual_Queue_Offset_Meters:(entry.occupancy ? entry.occupancy.offset : 0)+entry.fraction*entry.link.length_m-center,
        Visual_Queue_Source:entry.occupancy ? 'estimated_front_referenced_native_corridor' : entry.marker.Visual_Queue_Source || 'estimated_following_on_recorded_link'};
      if(reusable)profile.finalMarkerReuses++;
      else {marker=this.withBody(marker,pose.body,entry.presentation);this.finalMarkers.set(entry.raw,{context,center,state,marker});}
      visible.push(marker);
      index.add({body:pose.body,entry});if(!entry.fixed)placed.set(laneKey,{center,dimensions:entry.dimensions});
      if(entry.eligible)counts.positioned++;
      if(state==='queued')counts.queued++;
      if(entry.following)counts.following++;
      if(marker.Visual_Queue_Offset_Meters>1e-7)counts.redistributed++;
      if(entry.eligible && time>=entry.hold)limitations.push({vehicle_id:marker.vehicle,
        reason:'queue_exit_has_no_substep_trajectory',hold_start:entry.hold,exit_time:entry.end});
      if(marker.Visual_Queue_Order_Ambiguous)limitations.push({vehicle_id:marker.vehicle,
        reason:'simultaneous_entry_order_estimated_by_stable_identity',entry_time:entry.orderTime});
      if(marker.Motion_Plan?.feasible===false || marker.Visual_Motion_Fallback_Reason)limitations.push({vehicle_id:marker.vehicle,
        reason:'native_motion_limitation_preserved',motion_status:marker.Motion_Plan?.status,
        motion_reason:marker.Motion_Plan?.fallback_reason ?? marker.Visual_Motion_Fallback_Reason});
    }
    for(const {entry,reason,detail} of retained) {
      const pose={body:entry.body};
      const hit=conflicts(entry,pose);
      for(const other of hit)collisions.push(this.collision(entry,pose,other,time,'unresolved'));
      const marker=this.withBody({...entry.marker,Visual_Queue_Representable:true,Visual_Queue_Compatible:false,
        Visual_Queue_Opacity:1,Visual_Queue_State:reason,Visual_Queue_Reason:reason,
        Visual_Queue_Source:this.retainedPoseSource(entry.marker)==='recorded_interval_motion' ?
          'recorded_interval_pose_spacing_incompatible' : this.retainedPoseSource(entry.marker),Visual_Queue_Redistribution:false,
        Visual_Unresolved_Conflicts:hit.map(row=>row.entry.marker.vehicle),
        Visual_Diagnostic:{...detail,constraint_violation:true,pose_source:this.retainedPoseSource(entry.marker),
          physical_incompatibility_confirmed:false}},entry.body,entry.presentation);
      visible.push(marker);index.add({entry,body:entry.body});
    }
    phase('placementMs');
    counts.visible=visible.length;counts.omitted=omitted.length;counts.unsupportedPosition=omitted.length;
    const finalBodies=new Map(visible.map(m=>[m.vehicle,{position:m.position,heading:m.Visual_Body_Heading_Degrees,
      length_m:m.Visual_Body_Length_Meters,width_m:m.Visual_Body_Width_Meters}]));
    const unique=new Map();
    for(const row of collisions) {
      const ids=[row.entry.marker.vehicle,row.other.entry.marker.vehicle],key=JSON.stringify([...ids].sort());
      if(unique.has(key))continue;
      const a=finalBodies.get(ids[0]),b=finalBodies.get(ids[1]);
      row.resolution=!a || !b ? 'no_supported_slot' : this.envelopesOverlap(a,b) ? 'unresolved' : 'resolved_spacing';
      row.classification=row.resolution==='resolved_spacing' ? 'graphical_spacing' : 'insufficient_geometry_or_possible_event_incompatibility';
      row.final_positions=[a?.position ?? null,b?.position ?? null];row.final_bodies=[a,b];unique.set(key,row);
    }
    const overlapEvidence=[...unique.values()];
    const unresolved=new Map();
    for(const row of overlapEvidence)if(row.resolution==='unresolved') {
      const a=row.entry.marker.vehicle,b=row.other.entry.marker.vehicle;
      if(!unresolved.has(a))unresolved.set(a,new Set());if(!unresolved.has(b))unresolved.set(b,new Set());
      unresolved.get(a).add(b);unresolved.get(b).add(a);
    }
    // The conflict belongs to both bodies, regardless of insertion/FIFO order.
    // Preserve immutable marker caches; only evidence for affected bodies changes.
    for(let i=0;i<visible.length;i++)if(unresolved.has(visible[i].vehicle))visible[i]={...visible[i],
      Visual_Queue_Compatible:false,Visual_Unresolved_Conflicts:[...unresolved.get(visible[i].vehicle)].sort()};
    counts.overlapsDetected=overlapEvidence.length;
    counts.overlapsResolved=overlapEvidence.filter(row=>row.resolution==='resolved_spacing').length;
    counts.unresolvedOverlaps=overlapEvidence.filter(row=>row.resolution==='unresolved').length;
    counts.overlapping=overlapEvidence.filter(row=>row.resolution==='no_supported_slot').length;
    // Detection and counts stay on every frame. Verbose evidence is expanded
    // only when the technical API asks for it, never to update a map layer.
    let diagnosticRows=null,collisionRows=null,collisionSummary=null;
    const records=()=>[...visible,...omitted].map(marker=>({vehicle_id:marker.vehicle,time,link_id:marker.Link_ID,
      lane:marker.Visual_Lane_Index,position:marker.position,heading:marker.Visual_Body_Heading_Degrees,
      dimensions_m:[marker.Visual_Body_Length_Meters,marker.Visual_Body_Width_Meters],
      visible:marker.Visual_Queue_Representable!==false,reason:marker.Visual_Queue_State,
      interval:marker.timestamps,display_link:marker.Visual_Queue_Display_Link_ID,
      source:marker.Visual_Queue_Source ?? marker.Position_Evidence ?? 'interpolated_link_pose',
      spacing_compatible:marker.Visual_Queue_Compatible,stop_line_m:marker.Visual_Queue_Stop_Line_Meters,
      stop_line_source:marker.Visual_Queue_Stop_Line_Source,native_position:marker.Visual_Native_Center_Position,
      envelope:marker.Visual_Safety_Envelope,presentation:marker.Visual_Vehicle_Presentation,details:marker.Visual_Diagnostic ?? null,
      ...this.describePose(marker)}));
    phase('diagnosticsMs');profile.totalMs=now()-began;profile.collisionPairs=overlapEvidence.length;
    const expand=row=>this.expandCollision(row);
    const summarizeCollisions=()=>{
      if(collisionSummary)return {...collisionSummary};
      const result={total_pairs:overlapEvidence.length,resolved_spacing:0,unresolved_body_overlap:0,
        unresolved_safety_envelope_only:0,unavailable_pose:0};
      for(const row of overlapEvidence) {
        if(row.resolution==='resolved_spacing')result.resolved_spacing++;
        else if(row.resolution==='no_supported_slot')result.unavailable_pose++;
        else {const [a,b]=row.final_bodies;result[this.bodiesOverlap(a,b) ? 'unresolved_body_overlap' : 'unresolved_safety_envelope_only']++;}
      }
      collisionSummary=result;return {...result};
    };
    const sampleCollisions=({vehicle_ids=[],limit=100}={})=>{
      if(!Array.isArray(vehicle_ids) || vehicle_ids.length>2000 || vehicle_ids.some(id=>typeof id!=='string') ||
         !Number.isSafeInteger(limit) || limit<0 || limit>500)throw new Error('Muestra de conflictos invalida');
      const selected=new Set(vehicle_ids),rows=[];let total=0;
      for(const row of overlapEvidence)if(!selected.size || selected.has(row.entry.marker.vehicle) || selected.has(row.other.entry.marker.vehicle)) {
        total++;if(rows.length<limit)rows.push(expand(row));
      }
      return {total_matches:total,returned:rows.length,truncated:rows.length<total,records:rows};
    };
    return {markers:visible,omitted,overflow:[...indicators.values()],counts,performance:profile,
      diagnostics:{time,counts,get records(){return diagnosticRows ??= records();},
        get collisions(){return collisionRows ??= overlapEvidence.slice(0,100).map(expand);},
        collision_sample:{total_pairs:overlapEvidence.length,returned:Math.min(100,overlapEvidence.length),
          truncated:overlapEvidence.length>100,limit:100},sampleCollisions,summarizeCollisions,limitations}};
  }
  collision(entry,pose,other,time,resolution) {
    const bodyOverlap=this.bodiesOverlap(pose.body,other.body);
    return {entry,pose,other,time,resolution,body_overlap:bodyOverlap};
  }
  expandCollision(row) {
    const {entry,pose,other,time,resolution,body_overlap:bodyOverlap}=row;
    const [finalA,finalB]=row.final_bodies || [],finalBodyOverlap=finalA && finalB ? this.bodiesOverlap(finalA,finalB) : null;
    const evidence=e=>({vehicle_id:e.marker.vehicle,link_id:e.marker.Link_ID,lane:e.marker.Visual_Lane_Index,
      interval:e.marker.timestamps,waits:e.marker.Observed_Waits ?? {},motion_status:e.marker.Motion_Plan?.status,
      motion_reason:e.marker.Motion_Plan?.fallback_reason ?? e.marker.Visual_Motion_Fallback_Reason ?? null});
    return {time,vehicles:[evidence(entry),evidence(other.entry)],positions:[pose.body.position,other.body.position],
      headings:[pose.body.heading,other.body.heading],dimensions_m:[pose.body.length_m,pose.body.width_m],
      vehicle_dimensions_m:[[pose.body.length_m,pose.body.width_m],[other.body.length_m,other.body.width_m]],
      body_overlap:bodyOverlap,resolution,classification:resolution==='resolved_spacing' ? 'graphical_spacing' :
        'insufficient_geometry_or_possible_event_incompatibility',
      original_overlap_kind:bodyOverlap ? 'body_overlap' : 'safety_envelope_only',
      final_body_overlap:finalBodyOverlap,
      final_overlap_kind:resolution==='no_supported_slot' ? 'unavailable_pose' : resolution==='resolved_spacing' ?
        'clear' : finalBodyOverlap ? 'body_overlap' : 'safety_envelope_only',
      same_link:entry.marker.Link_ID===other.entry.marker.Link_ID,
      same_visual_lane:entry.marker.Link_ID===other.entry.marker.Link_ID &&
        Number.isSafeInteger(entry.marker.Visual_Lane_Index) && entry.marker.Visual_Lane_Index===other.entry.marker.Visual_Lane_Index,
      geometry_evidence:'inferred_rigid_body_pose; native_lane_id_does_not_measure_lateral_position',
      physical_state:'unknown_from_queue_events',
      final_positions:row.final_positions,
      physical_incompatibility_confirmed:false};
  }
}
