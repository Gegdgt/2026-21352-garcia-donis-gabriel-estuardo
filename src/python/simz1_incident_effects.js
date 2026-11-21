// Presentation only. The native adapter is NOT installed. Production cannot
// activate this module by URL/config/envelope flags. allowFixture is an explicit
// constructor argument used only by isolated tests, never by viewer controls.
class SimZ1IncidentEffects {
  static schema='simz1-lane-incident-replay-v1';
  static color=Object.freeze([255,140,0]);
  static micros(value) {
    if(!Number.isFinite(value) || value<0 || Number(value.toFixed(6))!==value)return null;
    const us=Math.round(value*1e6);return Number.isSafeInteger(us) ? us : null;
  }
  constructor({identity={},allowFixture=false}={}) {
    this.identity={run_id:identity.run_id,iteration:identity.iteration};
    this.allowFixture=allowFixture===true;this.empty=Object.freeze([]);
    this.replace(null,identity);
  }
  replace(envelope,windowIdentity={}) {
    this.rows=this.empty;this.horizon=null;this.reasons={};this.cache=new WeakMap();
    this.received=Array.isArray(envelope?.records) ? envelope.records.length : 0;
    this.status='disabled_no_incident_records';
    const reject=reason=>{this.status=reason;this.reasons[reason]=(this.reasons[reason] || 0)+1;return false;};
    if(envelope==null)return false;
    // Deliberately no acceptsNative or adapter_installed override: a sidefile
    // cannot install the missing native adapter or turn a design into evidence.
    if(!this.allowFixture)return reject('adapter_not_installed');
    if(envelope.schema!==SimZ1IncidentEffects.schema || envelope.scope!=='fixture_only' ||
      envelope.adapter_installed!==false || envelope.adapter_version!=='uninstalled' ||
      envelope.adapter_evidence!=='fixture_gate_only_not_native')return reject('unsupported_fixture_contract');
    for(const key of ['run_id','iteration'])if(this.identity[key]==null ||
      envelope.identity?.[key]!==this.identity[key] || windowIdentity[key]!==this.identity[key])return reject('identity_mismatch');
    if(SimZ1IncidentEffects.micros(envelope.horizon_seconds)==null || envelope.horizon_seconds<=0 || !Array.isArray(envelope.records))
      return reject('invalid_fixture_envelope');
    this.horizon=envelope.horizon_seconds;
    const byId=new Map(),conflicts=new Set();
    for(const row of envelope.records) {
      const reason=this.invalid(row);
      if(reason){this.reasons[reason]=(this.reasons[reason] || 0)+1;if(row?.incident_id)conflicts.add(row.incident_id);continue;}
      if(byId.has(row.incident_id) && JSON.stringify(byId.get(row.incident_id))!==JSON.stringify(row))conflicts.add(row.incident_id);
      else byId.set(row.incident_id,row);
    }
    for(const id of conflicts){byId.delete(id);this.reasons.conflicting_incident_id=(this.reasons.conflicting_incident_id || 0)+1;}
    // A backend fixture batch rejects overlapping incidents on one exact lane
    // or for one participant. Repeat the conservative guard before presentation;
    // no body/proximity test creates or validates an incident here.
    const opportunities=new Map(),reused=new Set();
    for(const row of byId.values()) {
      const previous=opportunities.get(row.opportunity_id);
      if(previous){reused.add(previous);reused.add(row.incident_id);}
      else opportunities.set(row.opportunity_id,row.incident_id);
    }
    for(const id of reused)byId.delete(id);
    if(reused.size)this.reasons.repeated_opportunity_id=reused.size;
    const resources=new Map(),overlapIds=new Set();
    for(const row of byId.values())for(const key of [JSON.stringify(['lane',row.link_id,row.lane]),
      ...row.vehicles.map(id=>JSON.stringify(['vehicle',id]))]) {
      if(!resources.has(key))resources.set(key,[]);resources.get(key).push(row);
    }
    for(const rows of resources.values()) {
      rows.sort((a,b)=>a.start_seconds-b.start_seconds);let group=[],end=-Infinity;
      const finish=()=>{if(group.length>1)for(const row of group)overlapIds.add(row.incident_id);};
      for(const row of rows) {
        if(row.start_seconds>=end){finish();group=[];end=-Infinity;}
        group.push(row);end=Math.max(end,Math.min(row.scheduled_end_seconds,this.horizon));
      }
      finish();
    }
    for(const id of overlapIds)byId.delete(id);
    if(overlapIds.size)this.reasons.overlapping_lane_or_participant_incidents=overlapIds.size;
    this.rows=[...byId.values()];this.status=this.rows.length ? 'fixture_only_no_physics' : 'no_valid_fixture_records';
    return this.rows.length>0;
  }
  invalid(row) {
    if(!row || typeof row.incident_id!=='string' || !row.incident_id || typeof row.opportunity_id!=='string' ||
      !row.opportunity_id || typeof row.link_id!=='string' || !row.link_id || typeof row.lane!=='string' || !row.lane ||
      row.physics_effect!=='none' || row.intended_physics_effect!=='independent_lane_hold' ||
      row.provenance?.scope!=='fixture_only' || row.provenance?.adapter_version!=='uninstalled' ||
      row.provenance?.adapter_evidence!=='fixture_gate_only_not_native' || typeof row.evidence_ref!=='string' || !row.evidence_ref)
      return 'invalid_fixture_record';
    if(!Array.isArray(row.vehicles) || row.vehicles.length!==2 || new Set(row.vehicles).size!==2 ||
      row.vehicles.some(id=>typeof id!=='string' || !id) || !Array.isArray(row.participants) || row.participants.length!==2 ||
      new Set(row.participants.map(p=>p?.vehicle_id)).size!==2 || row.participants.some(p=>!p ||
        !row.vehicles.includes(p.vehicle_id) || p.link_id!==row.link_id || p.lane!==row.lane ||
        typeof p.vehicle_type!=='string' || !p.vehicle_type.trim()))return 'invalid_two_participants';
    const start=SimZ1IncidentEffects.micros(row.start_seconds),end=SimZ1IncidentEffects.micros(row.scheduled_end_seconds);
    if(start==null || end==null || row.start_seconds>=this.horizon || row.duration_seconds!==1800 ||
      end-start!==1800e6)return 'invalid_interval';
    if(row.status==='resolved') {
      if(SimZ1IncidentEffects.micros(row.end_seconds)!==end || row.end_seconds>this.horizon || row.censored_seconds!=null)return 'invalid_resolved_interval';
    } else if(row.status==='censored') {
      if(row.end_seconds!=null || row.censored_seconds!==this.horizon || this.horizon>=row.scheduled_end_seconds)return 'invalid_censored_interval';
    } else return 'terminal_evidence_missing';
    return null;
  }
  active(time) {
    if(!this.rows.length || !Number.isFinite(time))return this.empty;
    // Resolved is half-open at exactly 1800 s. Censored retains the last
    // observed horizon image (only if its participant still exists); passing
    // the horizon never extrapolates activity or invents a recovery event.
    return this.rows.filter(row=>row.start_seconds<=time && time<row.scheduled_end_seconds &&
      (row.status==='censored' ? time<=this.horizon : time<row.end_seconds));
  }
  matches(marker,row) {
    // Fixture events have no universal trip/visit ID. The half-open incident
    // interval plus vehicle, native link and observed lane are all required;
    // this is not sufficient to enable a future production adapter.
    return row.vehicles.includes(marker.vehicle) && marker.Link_ID===row.link_id && marker.Observed_Queue_ID===row.lane;
  }
  note(row) {
    return {incident_id:row.incident_id,scope:'fixture_only',physics_effect:'none',status:'active',
      start_seconds:row.start_seconds,scheduled_end_seconds:row.scheduled_end_seconds,
      censored:row.status==='censored',evidence_ref:row.evidence_ref,
      identity_limit:'fixture_vehicle_link_lane_time;native_visit_id_unavailable'};
  }
  participant(marker,time) {
    if(!marker || !this.rows.length)return null;
    const matches=this.active(time).filter(row=>this.matches(marker,row));
    return matches.length===1 ? this.note(matches[0]) : null;
  }
  frame(markers,time) {
    const active=this.active(time);
    if(!active.length)return {markers,icons:this.empty,active:this.empty,participant_count:0};
    const byVehicle=new Map(),positions=new Map();
    for(const row of active)for(const id of row.vehicles) {
      if(!byVehicle.has(id))byVehicle.set(id,[]);byVehicle.get(id).push(row);
    }
    let decorated=markers,count=0;
    for(let i=0;i<markers.length;i++) {
      const marker=markers[i],candidates=byVehicle.get(marker.vehicle);
      if(!candidates)continue;
      const matches=candidates.filter(row=>this.matches(marker,row));
      if(matches.length!==1)continue;
      const row=matches[0];let copy=this.cache.get(marker);
      if(!copy || copy.Visual_Synthetic_Incident.incident_id!==row.incident_id) {
        copy={...marker,color:SimZ1IncidentEffects.color,Visual_Synthetic_Incident:this.note(row)};
        this.cache.set(marker,copy);
      }
      if(decorated===markers)decorated=markers.slice();decorated[i]=copy;count++;
      if(!positions.has(row.incident_id) && Array.isArray(marker.position) && marker.position.length>=2 &&
        marker.position.every(Number.isFinite))positions.set(row.incident_id,marker.position);
    }
    // No incident XY was measured. In a fixture only, annotate an existing
    // participant's displayed pose, not a claimed location of impact. Missing
    // participants never cause creation/retention of a vehicle or an icon.
    const icons=active.filter(row=>positions.has(row.incident_id)).map(row=>({incident_id:row.incident_id,
      position:positions.get(row.incident_id),position_source:'participant_visual_pose;not_native_incident_location',
      scope:'fixture_only',physics_effect:'none'}));
    return {markers:decorated,icons,active,participant_count:count};
  }
  snapshot(time) {
    return {...this.identity,status:this.status,adapter_installed:false,scope:this.allowFixture ? 'isolated_fixture_test' : 'production_disabled',
      clock:'absolute_simulation_seconds',duration_seconds:1800,time,horizon_seconds:this.horizon,
      valid_records:this.rows.length,active_ids:this.active(time).map(row=>row.incident_id),reasons:{...this.reasons},
      received_records:this.received,rejected_records:this.received-this.rows.length,
      location_evidence:'No native incident coordinate; fixture icons only annotate an existing participant visual pose.'};
  }
  static layer(deck) {
    // One reusable atlas and one instanced layer, independent of incident count.
    if(!this.atlas)this.atlas='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'+
      '<rect x="2" y="2" width="28" height="28" rx="6" fill="#fff" stroke="#ff8c00" stroke-width="3"/>'+
      '<path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z" fill="#ee6511"/></svg>');
    return new deck.IconLayer({id:'synthetic-incident-emergency',data:[],pickable:false,
      iconAtlas:this.atlas,iconMapping:{emergency:{x:0,y:0,width:32,height:32,anchorX:16,anchorY:32,mask:false}},
      getIcon:()=> 'emergency',getPosition:d=>d.position,getSize:20,sizeUnits:'pixels',sizeMinPixels:16,sizeMaxPixels:24,
      billboard:true,parameters:{depthCompare:'always',depthWriteEnabled:false}});
  }
}
